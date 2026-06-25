"""
============================================================
MARKET SCANNER V1.1 (V18.0) — Institutional Scout Pro
מנוע סריקת שוק נפרד עם Early Pruning (גיזום מוקדם)
============================================================
עקרון מרכזי: לסרוק מהר מאות-אלפי מניות ע"י "גיזום" אגרסיבי בכל שלב -
מבצעים את הבדיקות הזולות קודם (מחיר/נפח/שווי שוק), ורק מי שעובר אותן
ממשיך לבדיקות היקרות (Wyckoff מלא, ואז פונדמנטלי מלא).
כך נמנעים מהרצת ניתוח כבד על מניות שנפסלות ממילא.

נשען לחלוטין על מנוע scout_core הקיים - אינו משכפל לוגיקה אנליטית.
תואם Google Cloud Run (ללא תלות חיצונית מעבר ל-scout_core/yfinance).
============================================================
"""

import logging
import time
from datetime import datetime, date

logger = logging.getLogger(__name__)

# רשימת ברירת מחדל ליקום הסריקה (Large/Mid Cap נזילות).
# ניתן להזרים רשימה חיצונית גדולה יותר דרך הפרמטר universe ב-scan_market.
DEFAULT_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "AVGO", "TSLA", "BRK-B",
    "JPM", "V", "MA", "UNH", "LLY", "COST", "HD", "PG", "XOM", "CVX",
    "AMD", "PANW", "NFLX", "ABBV", "WMT", "KO", "CRM", "ORCL", "ADBE", "CSCO",
    "ACN", "INTU", "IBM", "TXN", "QCOM", "DELL", "HPQ", "INTC", "SMCI", "AMAT",
    "LRCX", "KLAC", "ONTO", "MRVL", "ADI", "BAC", "GS", "MS", "WFC", "C",
    "AXP", "BLK", "SCHW", "SPGI", "JNJ", "MRK", "ABT", "AMGN", "TMO", "DHR",
    "PFE", "BMY", "GILD", "CVS", "MDT", "ISRG", "VRTX", "REGN", "PG", "PEP",
    "MCD", "NKE", "SBUX", "LOW", "TGT", "BKNG", "MAR", "DIS", "CMCSA", "T",
    "VZ", "TMUS", "COP", "SLB", "EOG", "OXY", "PSX", "VLO", "MPC", "KMI",
    "FCX", "NEM", "GOLD", "AEM", "WPM", "PAAS", "AG", "NUE", "CAT", "DE",
    "BA", "GE", "HON", "UPS", "RTX", "LMT", "GD", "UNP", "CSX", "EMR",
    "PLD", "AMT", "EQIX", "SPG", "O", "CCI", "PYPL", "SQ", "SHOP", "UBER",
    "ABNB", "SNOW", "PLTR", "NOW", "PANW", "CRWD", "ZS", "DDOG", "NET", "MDB",
]


class MarketScanner:
    """
    סורק שוק עם גיזום מוקדם (Early Pruning) רב-שלבי.

    שלב 0 - סינון זול וראשוני (quick_filter): שווי שוק, מחיר, נפח ממוצע.
    שלב 1 - קווים אדומים של Wyckoff (passes_wyckoff_red_lines):
            פאזה לא חיובית / מתחת ל-SMA50 / RS שלילי משמעותי -> דילוג מיידי.
    שלב 2 - ניתוח פונדמנטלי מלא רק למי ששרד, ואז קווים אדומים פונדמנטליים
            (passes_fundamental_red_lines): יקר+חוב גבוה+FCF נמוך -> דילוג.
    שלב 3 - דירוג משולב והחזרת רק המניות החזקות.
    """

    BEARISH_PHASE_KEYWORDS = [
        "Distribution", "Markdown", "Failed Spring", "Heavy Supply",
        "Failed", "Selling Climax", "Supply",
    ]
    BULLISH_PHASE_KEYWORDS = [
        "Phase C", "Spring", "Phase D", "Phase E", "Markup",
        "LPS", "SOS", "Re-accumulation", "Accumulation",
    ]

    # ספי שלב-0 לפי מצב סריקה. "full" הוא השם הקנוני (V18.0); "deep" נשמר כתאימות לאחור.
    MODE_PRESETS = {
        "fast": {"min_cap": 2e9, "min_price": 5.0, "min_vol": 600_000, "default_max": 1200},
        "balanced": {"min_cap": 1e9, "min_price": 5.0, "min_vol": 400_000, "default_max": 1500},
        "full": {"min_cap": 1e9, "min_price": 5.0, "min_vol": 400_000, "default_max": 3000},
        "deep": {"min_cap": 5e8, "min_price": 3.0, "min_vol": 250_000, "default_max": 3000},
    }

    def __init__(self, scout_core, min_cap=1e9, min_price=5.0, min_avg_volume=400_000):
        """
        scout_core: המודול scout_core (מוזרק כדי לא ליצור תלות מעגלית ולשמור על מקור-אמת יחיד).
        שאר הפרמטרים: ספי ברירת מחדל לשלב 0, ניתנים לכוונון.
        """
        self.sc = scout_core
        self.min_cap = min_cap
        self.min_price = min_price
        self.min_avg_volume = min_avg_volume
        self.engine = scout_core.FactorEngine(scout_core.BacktestConfig())
        # קאש יומי: טיקרים שכבר נסרקו היום (מפתח -> תוצאה או None אם נפסל)
        self._cache = {}
        self._cache_date = date.today()

    # ---------------------------------------------------------------
    # שלב 0 - סינון זול וראשוני
    # ---------------------------------------------------------------
    def quick_filter(self, ticker, df, info=None):
        """
        בדיקה זולה על בסיס נתונים שכבר נשלפו (df) + info אופציונלי.
        מחזיר (passed: bool, reason: str).
        """
        if df is None or df.empty or len(df) < 60:
            return False, "אין מספיק היסטוריית מסחר (פחות מ-60 ימים)"

        last_price = float(df["Close"].iloc[-1])
        if last_price < self.min_price:
            return False, f"מחיר נמוך מדי (${last_price:.2f} < ${self.min_price})"

        avg_vol = float(df["Volume"].tail(30).mean())
        if avg_vol < self.min_avg_volume:
            return False, f"נפח ממוצע נמוך ({avg_vol:,.0f} < {self.min_avg_volume:,.0f})"

        # שווי שוק - אם זמין ב-info; אחרת לא חוסמים (כדי לא לפסול בטעות)
        if info:
            mcap = info.get("marketCap")
            if mcap and mcap < self.min_cap:
                return False, f"שווי שוק נמוך (${mcap/1e9:.2f}B < ${self.min_cap/1e9:.1f}B)"

        return True, "עבר סינון ראשוני"

    # ---------------------------------------------------------------
    # שלב 1 - קווים אדומים של Wyckoff (Early Exit חזק)
    # ---------------------------------------------------------------
    def passes_wyckoff_red_lines(self, df, factors=None, phase=None):
        """
        Early-Exit מהיר על בסיס Wyckoff. מחזיר (passed, reason, payload).
        payload כולל cis/phase כדי לא לחשב פעמיים.
        """
        try:
            if factors is None:
                factors = self.engine.compute(df)
            if phase is None:
                phase = str(self.engine.get_wyckoff_phase(df).iloc[-1])

            # 1. פאזה לא חיובית -> דילוג מיידי
            if any(k in phase for k in self.BEARISH_PHASE_KEYWORDS):
                return False, f"פאזה שלילית ({phase})", {"phase": phase}
            if not any(k in phase for k in self.BULLISH_PHASE_KEYWORDS):
                return False, f"פאזה לא חיובית מובהקת ({phase})", {"phase": phase}

            # 2. מחיר מתחת ל-SMA50 -> דילוג
            sma50 = float(df["Close"].tail(50).mean())
            last_price = float(df["Close"].iloc[-1])
            if last_price < sma50:
                return False, f"מחיר (${last_price:.2f}) מתחת ל-SMA50 (${sma50:.2f})", {"phase": phase}

            # 3. Relative Strength מול SPY שלילי משמעותי -> דילוג
            rs_spy = self.sc._extract_last(factors, "f_rs_spy", 0.0)
            if rs_spy < -0.03:
                return False, f"חולשה יחסית מול השוק (RS {rs_spy:+.1%})", {"phase": phase}

            cis = float(self.engine.composite_cis(factors, df).iloc[-1])
            return True, "עבר קווים אדומים Wyckoff", {"phase": phase, "cis": cis, "factors": factors}
        except Exception as exc:
            logger.warning("passes_wyckoff_red_lines failed: %s", exc)
            return False, f"שגיאת חישוב Wyckoff: {exc}", {}

    # ---------------------------------------------------------------
    # שלב 2 - קווים אדומים פונדמנטליים
    # ---------------------------------------------------------------
    def passes_fundamental_red_lines(self, fund_data):
        """
        פוסל שילוב גרוע מובהק: יקר + מינוף גבוה + תזרים חופשי נמוך.
        מחזיר (passed, reason).
        """
        if not fund_data:
            return True, "אין נתונים פונדמנטליים - לא פוסל"

        raw = fund_data.get("_raw", {})
        valuation = fund_data.get("valuation", "הוגן")
        fcf_y = raw.get("fcf_yield", 0.0)
        nde = raw.get("net_debt_ebitda", 0.0)

        expensive = valuation == "יקר"
        high_debt = nde and nde > 3.0
        weak_fcf = fcf_y is not None and fcf_y < 1.0

        if expensive and high_debt and weak_fcf:
            return False, f"שילוב גרוע: יקר + מינוף גבוה ({nde:.1f}x) + תזרים חלש ({fcf_y:.1f}%)"
        return True, "עבר קווים אדומים פונדמנטליים"

    # ---------------------------------------------------------------
    # ניתוח מלא של טיקר בודד (אחרי שעבר את כל הגיזומים)
    # ---------------------------------------------------------------
    def _full_analyze(self, ticker, wyckoff_payload):
        phase = wyckoff_payload.get("phase", "")
        cis = wyckoff_payload.get("cis", 0.0)

        fund_data = self.sc.get_fundamental_data(ticker)
        ok_fund, fund_reason = self.passes_fundamental_red_lines(fund_data)
        if not ok_fund:
            return None, fund_reason

        verdict = self.sc.synthesize_verdict(fund_data, cis, phase, ticker)
        # רק שילובים חזקים נכנסים לתוצאות
        if verdict.get("tier") not in ("STRONG_BUY", "BUY"):
            return None, f"דירוג לא חזק מספיק ({verdict.get('tier')})"

        raw = fund_data.get("_raw", {}) if fund_data else {}
        fund_quality = 0.0
        fund_quality += min(30, (raw.get("fcf_yield", 0) or 0) * 5)
        fund_quality += 20 if (fund_data and fund_data.get("valuation") == "זול") else (
            10 if (fund_data and fund_data.get("valuation") == "הוגן") else 0)
        om = raw.get("op_margin", 0) or 0
        bom = raw.get("bench_om", 12) or 12
        fund_quality += 15 if (om and om > bom) else 0
        fund_quality += 10 if (raw.get("peg", 0) and 0 < raw.get("peg") < 1.5) else 0
        fund_quality += 10 if ((raw.get("net_debt_ebitda", 0) or 0) < 2) else 0
        fund_quality = min(85, fund_quality) + 15

        tier_bonus = {"STRONG_BUY": 12, "BUY": 6}.get(verdict.get("tier"), 0)
        composite = round(cis * 0.5 + fund_quality * 0.5 + tier_bonus, 1)

        result = {
            "ticker": ticker,
            "cis": round(cis, 1),
            "phase": phase,
            "valuation": fund_data.get("valuation", "-") if fund_data else "-",
            "valuation_color": fund_data.get("valuation_color", "#94a3b8") if fund_data else "#94a3b8",
            "fcf_yield": fund_data.get("fcf_yield", "N/A") if fund_data else "N/A",
            "pe": (fund_data.get("pe_forward") if fund_data and fund_data.get("pe_forward") != "N/A"
                   else (fund_data.get("pe_trailing", "N/A") if fund_data else "N/A")),
            "sector_he": fund_data.get("sector_he", "") if fund_data else "",
            "headline": verdict.get("headline", ""),
            "detail": verdict.get("detail", ""),
            "action_line": verdict.get("action_line", ""),
            "confidence": verdict.get("confidence", ""),
            "tier": verdict.get("tier", ""),
            "color": verdict.get("color", "#16a34a"),
            "composite": composite,
        }
        return result, "עבר ניתוח מלא"

    # ---------------------------------------------------------------
    # סריקה ראשית
    # ---------------------------------------------------------------
    def scan_market(self, mode="balanced", max_tickers=1500, universe=None,
                    top_n=20, progress_callback=None):
        """
        סורק את היקום עם גיזום מוקדם. סינכרוני (Streamlit-friendly).

        mode: "fast" / "balanced" / "full" - קובע ספי שלב-0 וגודל ברירת מחדל.
        max_tickers: תקרת מניות לסריקה.
        universe: רשימת טיקרים (ברירת מחדל DEFAULT_UNIVERSE).
        top_n: כמה תוצאות מובילות להחזיר.
        progress_callback(done, total, ticker, stats): לעדכון progress bar.

        מחזיר dict: {"results": [...], "stats": {...}, "elapsed": secs}
        """
        preset = self.MODE_PRESETS.get(mode, self.MODE_PRESETS["balanced"])
        self.min_cap = preset["min_cap"]
        self.min_price = preset["min_price"]
        self.min_avg_volume = preset["min_vol"]

        universe = universe or DEFAULT_UNIVERSE
        # הסרת כפילויות תוך שמירת סדר
        seen = set()
        universe = [t for t in universe if not (t in seen or seen.add(t))]
        universe = universe[:max_tickers]
        total = len(universe)

        # רענון קאש יומי
        if self._cache_date != date.today():
            self._cache = {}
            self._cache_date = date.today()

        results = []
        stats = {
            "total": total, "scanned": 0,
            "pruned_quick": 0, "pruned_wyckoff": 0,
            "pruned_fundamental": 0, "pruned_weak": 0,
            "passed": 0, "errors": 0, "from_cache": 0,
        }
        start = time.time()

        for i, ticker in enumerate(universe):
            stats["scanned"] += 1

            # קאש יומי
            if ticker in self._cache:
                stats["from_cache"] += 1
                cached = self._cache[ticker]
                if cached is not None:
                    results.append(cached)
                    stats["passed"] += 1
                if progress_callback:
                    progress_callback(i + 1, total, ticker, stats)
                continue

            try:
                df = self.sc.get_data(ticker, period="1y")
                info = None
                # שלב 0
                ok_quick, _ = self.quick_filter(ticker, df, info)
                if not ok_quick:
                    stats["pruned_quick"] += 1
                    self._cache[ticker] = None
                    if progress_callback:
                        progress_callback(i + 1, total, ticker, stats)
                    continue

                # שלב 1 - Wyckoff red lines
                ok_wy, _, payload = self.passes_wyckoff_red_lines(df)
                if not ok_wy:
                    stats["pruned_wyckoff"] += 1
                    self._cache[ticker] = None
                    if progress_callback:
                        progress_callback(i + 1, total, ticker, stats)
                    continue

                # שלב 2+3 - ניתוח מלא + פונדמנטלי
                result, reason = self._full_analyze(ticker, payload)
                if result is None:
                    if "פונדמנטל" in reason:
                        stats["pruned_fundamental"] += 1
                    else:
                        stats["pruned_weak"] += 1
                    self._cache[ticker] = None
                    if progress_callback:
                        progress_callback(i + 1, total, ticker, stats)
                    continue

                self._cache[ticker] = result
                results.append(result)
                stats["passed"] += 1
            except Exception as exc:
                stats["errors"] += 1
                logger.warning("scan_market failed for %s: %s", ticker, exc)
            finally:
                if progress_callback:
                    progress_callback(i + 1, total, ticker, stats)

        results.sort(key=lambda x: x["composite"], reverse=True)
        elapsed = time.time() - start
        return {"results": results[:top_n], "stats": stats, "elapsed": elapsed}

    @staticmethod
    def estimate_time(total, mode="balanced"):
        """אומדן זמן גס (שניות) לפי כמות מניות ומצב - לתצוגת UX לפני סריקה."""
        per_ticker = {"fast": 0.18, "balanced": 0.22, "full": 0.28, "deep": 0.28}.get(mode, 0.22)
        secs = total * per_ticker
        if secs < 90:
            return f"כ-{int(secs)} שניות"
        return f"כ-{secs/60:.1f} דקות"

    async def scan_market_async(self, mode="balanced", max_tickers=1500, universe=None,
                                top_n=20, progress_callback=None):
        """
        עטיפה אסינכרונית לתאימות לחתימה המבוקשת. מאחר ש-Streamlit אינו ידידותי ל-event loop
        ארוך, היא פשוט מריצה את הסריקה הסינכרונית (שהיא ה-source of truth) ומחזירה את אותו מבנה.
        """
        return self.scan_market(mode=mode, max_tickers=max_tickers, universe=universe,
                                top_n=top_n, progress_callback=progress_callback)
