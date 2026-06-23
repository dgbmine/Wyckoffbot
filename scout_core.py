"""
============================================================
SCOUT CORE V16.9 — WYCKOFF INSTITUTIONAL ENGINE
============================================================
"""

import numpy as np
import pandas as pd
import yfinance as yf
from dataclasses import dataclass
import warnings
import logging

warnings.filterwarnings("ignore")
logger = logging.getLogger("scout_core")

def clean_filename(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).replace(' ', '_')

def get_data(ticker, period="2y", start=None, end=None):
    try:
        tkr = yf.Ticker(ticker)
        if start is not None and end is not None:
            df = tkr.history(start=start, end=end, auto_adjust=False)
            if df is None or df.empty or len(df) < 40:
                df = tkr.history(start=start, end=end)
        else:
            df = tkr.history(period=period, auto_adjust=False)
            if df is None or df.empty or len(df) < 40:
                df = tkr.history(period=period)

        if df is None or df.empty or len(df) < 40:
            return None

        def _safe_tz_drop(idx):
            idx = pd.to_datetime(idx)
            if getattr(idx, 'tz', None) is not None: return idx.tz_convert(None)
            return idx

        df.index = _safe_tz_drop(df.index)
        df = df[~df.index.duplicated(keep='first')]
        df.dropna(subset=['Close', 'Volume'], inplace=True)
        df = df.sort_index()

        if start is not None and end is not None:
            spy_df = yf.Ticker("SPY").history(start=start, end=end, auto_adjust=False)
            if spy_df is None or spy_df.empty: spy_df = yf.Ticker("SPY").history(start=start, end=end)
        else:
            spy_df = yf.Ticker("SPY").history(period=period, auto_adjust=False)
            if spy_df is None or spy_df.empty: spy_df = yf.Ticker("SPY").history(period=period)

        if spy_df is not None and not spy_df.empty:
            spy_df.index = _safe_tz_drop(spy_df.index)
            spy_df = spy_df[~spy_df.index.duplicated(keep='first')]
            spy_df.dropna(subset=['Close'], inplace=True)
            df = df.join(spy_df[["Close"]].rename(columns={"Close": "spy_close"}), how="left")
            df['spy_close'] = df['spy_close'].ffill()
        else:
            df["spy_close"] = np.nan

        return df
    except Exception as e:
        logger.error(f"Error in get_data for {ticker}: {e}")
        return None

def get_fundamental_data(ticker: str, cis_score: float = None, current_phase: str = "") -> dict:
    """
    מודול עומק פונדמנטלי - Bill Ackman Style.
    מתמקד בתזרים מזומנים (FCF/OCF), יעילות (Margins), ויחס חוב (Net Debt/EBITDA).
    הסינתזה קשיחה לחלוטין ולעולם לא תאשר "High Conviction" בפאזה שלילית.
    """
    try:
        tkr = yf.Ticker(ticker)
        info = tkr.info or {}
        
        try:
            cf = tkr.cashflow
            bs = tkr.balance_sheet
            fin = tkr.financials
        except:
            cf, bs, fin = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        # תזרים מזומנים
        ocf, ocf_yoy, fcf = "N/A", "N/A", "N/A"
        fcf_val = 0
        ocf_yoy_val = None
        if not cf.empty and "Operating Cash Flow" in cf.index and len(cf.columns) >= 2:
            ocf_val = cf.loc["Operating Cash Flow"].iloc[0]
            ocf_prev = cf.loc["Operating Cash Flow"].iloc[1]
            ocf = f"${ocf_val / 1e9:.2f}B" if pd.notna(ocf_val) else "N/A"
            if pd.notna(ocf_val) and pd.notna(ocf_prev) and ocf_prev != 0:
                ocf_yoy_val = ((ocf_val - ocf_prev) / abs(ocf_prev)) * 100
                ocf_yoy = f"{ocf_yoy_val:.1f}%"
            
            if "Capital Expenditure" in cf.index:
                capex = cf.loc["Capital Expenditure"].iloc[0]
                if pd.notna(ocf_val) and pd.notna(capex):
                    fcf_val = ocf_val + capex 
                    fcf = f"${fcf_val / 1e9:.2f}B"

        # הכנסות ויעילות
        rev_growth, op_margin = "N/A", "N/A"
        rev_growth_val, op_margin_val = None, None
        if not fin.empty and "Total Revenue" in fin.index and len(fin.columns) >= 2:
            rev = fin.loc["Total Revenue"].iloc[0]
            rev_prev = fin.loc["Total Revenue"].iloc[1]
            if pd.notna(rev) and pd.notna(rev_prev) and rev_prev != 0:
                rev_growth_val = ((rev - rev_prev) / abs(rev_prev)) * 100
                rev_growth = f"{rev_growth_val:.1f}%"
            
            if "Operating Income" in fin.index:
                op_inc = fin.loc["Operating Income"].iloc[0]
                if pd.notna(rev) and pd.notna(op_inc) and rev != 0:
                    op_margin_val = (op_inc / rev) * 100
                    op_margin = f"{op_margin_val:.1f}%"

        # יחס חוב נטו
        net_debt_ebitda = "N/A"
        net_debt_val = None
        if not bs.empty and not fin.empty:
            try:
                total_debt = bs.loc["Total Debt"].iloc[0] if "Total Debt" in bs.index else 0
                cash = bs.loc["Cash And Cash Equivalents"].iloc[0] if "Cash And Cash Equivalents" in bs.index else 0
                ebitda = fin.loc["EBITDA"].iloc[0] if "EBITDA" in fin.index else None
                if pd.notna(total_debt) and pd.notna(cash) and ebitda and ebitda > 0:
                    net_debt_val = (total_debt - cash) / ebitda
                    net_debt_ebitda = f"{net_debt_val:.2f}x"
            except: pass

        pe_forward = info.get("forwardPE")
        sector = info.get("sector", "Unknown")
        
        sector_benchmarks = {
            "Technology": {"pe": 25, "op_margin": 20.0, "rev_growth": 15.0},
            "Financial Services": {"pe": 14, "op_margin": 25.0, "rev_growth": 8.0},
            "Healthcare": {"pe": 20, "op_margin": 15.0, "rev_growth": 10.0},
            "Consumer Cyclical": {"pe": 18, "op_margin": 10.0, "rev_growth": 8.0},
            "Energy": {"pe": 12, "op_margin": 15.0, "rev_growth": 5.0}
        }
        bench = sector_benchmarks.get(sector, {"pe": 18, "op_margin": 12.0, "rev_growth": 8.0})

        valuation, color = "הוגן", "#eab308"
        pe_diff = 0
        if pe_forward:
            pe_diff = pe_forward - bench["pe"]
            if pe_forward < bench["pe"] * 0.8: valuation, color = "זול", "#16a34a"
            elif pe_forward > bench["pe"] * 1.25: valuation, color = "יקר", "#ef4444"

        # בניית הסברים ספציפיים למניה (Popovers)
        ocf_txt = f"עבור {ticker}, נרשמה {'צמיחה חיובית' if ocf_yoy_val and ocf_yoy_val > 0 else 'ירידה/חולשה'} של {ocf_yoy} בתזרים התפעולי מול השנה שעברה. זהו הכסף האמיתי שנכנס לעסק."
        fcf_txt = f"התזרים החופשי של {ticker} עומד על {fcf}. {'החברה מייצרת מזומן פנוי בריא לדיבידנדים או קניות חוזרות.' if fcf_val > 0 else 'נורת אזהרה: החברה שורפת מזומנים לאחר השקעות הון, מה שמחליש את המאזן.'}"
        
        rg_diff = (rev_growth_val - bench['rev_growth']) if rev_growth_val is not None else 0
        rg_txt = f"עבור {ticker}, צמיחת ההכנסות ({rev_growth}) היא {'גבוהה' if rg_diff > 0 else 'נמוכה'} מהממוצע בסקטור ה-{sector} ({bench['rev_growth']}%). זה מצביע על {'התרחבות אגרסיבית' if rg_diff > 0 else 'אובדן נתח שוק או סטגנציה'} ביחס למתחרים."
        
        om_diff = (op_margin_val - bench['op_margin']) if op_margin_val is not None else 0
        om_txt = f"עבור {ticker}, שולי הרווח התפעולי של {op_margin} {'גבוהים ומרשימים' if om_diff > 0 else 'נמוכים משמעותית'} ביחס לממוצע בסקטור ה-{sector} ({bench['op_margin']}%) — מה שמעיד על יעילות תפעולית {'טובה וחפיר תחרותי' if om_diff > 0 else 'נמוכה יחסית למתחרים'}."
        
        nd_txt = f"יחס חוב נטו ל-EBITDA עומד על {net_debt_ebitda}. {'המצב תקין ורמת המינוף שמרנית.' if net_debt_val and net_debt_val < 3 else 'באנליזת Ackman, יחס מעל 3x מהווה דגל אדום המייצר סיכון לפשיטת רגל והשמדת ערך.'}"
        pe_txt = f"המכפיל העתידי הוא {round(pe_forward,1) if pe_forward else 'N/A'}. ממוצע סקטור ה-{sector} הוא {bench['pe']}, ולכן {ticker} נסחרת ב{'פרמיה על צמיחה ואיכות' if pe_diff > 0 else 'דיסקאונט שמהווה הזדמנות ערך או לחלופין Value Trap'}."

        explanations = {"ocf": ocf_txt, "fcf": fcf_txt, "rev_growth": rg_txt, "op_margin": om_txt, "net_debt": nd_txt, "pe": pe_txt}
                
        next_earnings = "לא ידוע"
        try:
            calendar = tkr.calendar
            if calendar is not None and not calendar.empty and "Earnings Date" in calendar.index:
                dates = calendar.loc["Earnings Date"]
                next_earnings = dates[0].strftime("%Y-%m-%d") if isinstance(dates, list) and len(dates)>0 else (dates.strftime("%Y-%m-%d") if hasattr(dates, "strftime") else "לא ידוע")
        except: pass

        # === סינתזה אגרסיבית מונעת מלכודות ===
        synthesis = "חסרים נתונים פיננסיים לאנליזה."
        if cis_score is not None:
            is_collecting = cis_score >= 65
            is_distributing = cis_score <= 40
            is_bearish_phase = any(p in current_phase for p in ["Distribution", "Markdown", "Heavy Supply", "Failed", "Selling Climax"])
            is_bullish_phase = any(p in current_phase for p in ["Phase C", "Spring", "Phase D", "Phase E", "Markup", "LPS", "Re-accumulation"])
            
            strong_cash = op_margin_val and (op_margin_val > bench["op_margin"] * 0.8) and (fcf_val > 0)
            high_debt = net_debt_val > 3.0 if net_debt_val else False

            # חוק ברזל: ללא אופטימיות בפאזה דובית.
            if is_bearish_phase:
                if high_debt or not strong_cash:
                    synthesis = "☠️ סכין נופלת (Toxic Value Trap): חברה ששורפת מזומנים, חלשה מול הסקטור והמוסדיים זורקים סחורה בפאזה שלילית. להתרחק מיד."
                else:
                    synthesis = "🚨 מלכודת ערך (Value Trap): למרות תמחור נוח לכאורה, הפאזה היא Markdown (ירידות). המוסדיים בורחים. אל תתפוס סכין נופלת."
            
            elif is_bullish_phase and is_collecting:
                if strong_cash and valuation != "יקר" and not high_debt:
                    synthesis = "🔥 High Conviction: שילוב עוצמתי - תזרים חזק ביחס לסקטור, מאזן נקי ואיסוף מוסדי אגרסיבי. פוזיציית לונג אידיאלית."
                elif valuation == "יקר" and strong_cash:
                    synthesis = "🚀 פרמיית איכות (Quality Premium): המוסדיים משלמים ביוקר על הנהלה שמדפיסה מזומן ומכה את הסקטור. מגמה עוצמתית."
                elif high_debt or not strong_cash:
                    synthesis = "⚠️ ספקולציית מומנטום: יש איסוף טכני חיובי, אבל החברה שורפת מזומן או ממונפת מדי. כניסה מסוכנת המבוססת על טכני בלבד."
            
            else: # דשדוש / ניטרלי
                if is_collecting and strong_cash:
                    synthesis = "⚖️ איסוף שקט באיכות גבוהה: כסף חכם בונה פוזיציה בנכס עם תזרים עדיף על הסקטור. המתן לפריצה טכנית."
                elif is_distributing:
                    synthesis = "📉 מומנטום שלילי: הון זורם החוצה מחברה שמתקשה לייצר ערך. אין שום סיבה פונדמנטלית או טכנית להיות כאן."
                else:
                    synthesis = "💤 כסף מת: העסק בינוני והכסף החכם לא מתערב כרגע. עדיף לשמור הון להזדמנויות ברורות."

        return {
            "ocf": ocf, "ocf_yoy": ocf_yoy, "fcf": fcf, "rev_growth": rev_growth,
            "op_margin": op_margin, "net_debt_ebitda": net_debt_ebitda,
            "pe_forward": round(pe_forward, 2) if pe_forward else "N/A",
            "sector": sector, "valuation": valuation, "valuation_color": color,
            "next_earnings": next_earnings, "synthesis": synthesis, "explanations": explanations
        }
    except Exception as e:
        logger.error(f"Error fetching fundamentals for {ticker}: {e}")
        return {}

def calculate_advanced_metrics(trades: list, initial_capital: float = 100000.0) -> dict:
    if not trades: return {"max_drawdown": 0.0, "total_profit": 0.0, "total_trades": 0, "winning_trades": 0, "losing_trades": 0, "annual_pnl": {}, "wyckoff_success_rate": 0.0}
    total_trades = len(trades)
    winning_trades = sum(1 for t in trades if t.get('is_win', t.get('profit', 0) > 0))
    losing_trades = total_trades - winning_trades
    total_profit = sum(t.get('profit', 0) for t in trades)
    wyckoff_trades = [t for t in trades if t.get('wyckoff_confirmed', False)]
    wyckoff_wins = sum(1 for t in wyckoff_trades if t.get('is_win', t.get('profit', 0) > 0))
    wyckoff_success_rate = (wyckoff_wins / len(wyckoff_trades) * 100) if wyckoff_trades else 0.0
    equity = initial_capital
    peak = equity
    max_drawdown = 0.0
    annual_profit = {}
    for t in sorted(trades, key=lambda x: pd.to_datetime(x.get('exit_date', x.get('entry_date')))):
        profit = t.get('profit', 0)
        equity += profit
        if equity > peak: peak = equity
        drawdown = ((peak - equity) / peak * 100) if peak > 0 else 0.0
        if drawdown > max_drawdown: max_drawdown = drawdown
        year = pd.to_datetime(t.get('exit_date')).year
        annual_profit[year] = annual_profit.get(year, 0.0) + profit
    return {"max_drawdown": max_drawdown, "total_profit": total_profit, "total_trades": total_trades, "winning_trades": winning_trades, "losing_trades": losing_trades, "annual_pnl": annual_profit, "wyckoff_success_rate": wyckoff_success_rate}

def calculate_optimal_threshold(model, X, y):
    try: probs = model.predict_proba(X)[:, 1] * 100
    except: return 65
    best_thresh, best_score = 50, 0
    for th in range(50, 95, 2):
        mask = probs >= th
        trades_count = mask.sum()
        if trades_count >= max(3, len(y) * 0.05):
            score = y[mask].mean() * (1 + np.log1p(trades_count) / 10)
            if score > best_score: best_score, best_thresh = score, th
    return best_thresh

def check_phase_entry_allowed(phase, risk_profile):
    if "לא בתהליך" in phase or "Markdown" in phase or "Distribution" in phase or "TRANSITION" in phase or "UNCERTAIN" in phase: return False
    if risk_profile in ["Aggressive", "Balanced"]: return any(p in phase for p in ["Phase C", "Spring", "Phase D", "Phase E", "LPS", "SOS", "Breakout", "Markup", "Re-accumulation"])
    elif risk_profile == "Conservative": return any(p in phase for p in ["Phase E", "Markup"])
    return False

def calculate_phase_followthrough(df: pd.DataFrame, horizon: int = 20, threshold_pct: float = 0.04) -> dict:
    if df is None or df.empty or 'wyckoff_phase' not in df.columns: return {}
    records = []
    phases, closes = df['wyckoff_phase'].values, df['Close'].values
    for i in range(len(df) - horizon):
        curr_phase = str(phases[i])
        if i > 0 and curr_phase == str(phases[i-1]): continue
        is_bull = any(p in curr_phase for p in ["Phase C", "Spring", "Phase D", "Re-accumulation", "Phase E (Markup)"])
        is_bear = any(p in curr_phase for p in ["Markdown", "Distribution", "Heavy Supply"])
        if not is_bull and not is_bear: continue
        future_closes = closes[i+1 : i+1+horizon]
        success = ((np.max(future_closes) - closes[i]) / closes[i] >= threshold_pct) if is_bull else ((closes[i] - np.min(future_closes)) / closes[i] >= threshold_pct)
        records.append({"Phase": curr_phase, "Success": success})
    if not records: return {}
    rdf = pd.DataFrame(records)
    return {phase: {"total": len(group), "success": int(group["Success"].sum()), "rate": float(group["Success"].mean() * 100)} for phase, group in rdf.groupby("Phase")}

@dataclass
class BacktestConfig:
    commission: float = 0.001
    initial_capital: float = 100_000.0
    hold_days: int = 40
    period: str = "2y"
    stop_loss_pct: float = 0.05
    atr_multiplier: float = 2.0

class FactorEngine:
    def __init__(self, cfg: BacktestConfig): self.cfg = cfg

    def _compute_quick_wyckoff(self, df: pd.DataFrame) -> pd.Series:
        score = pd.Series(0.0, index=df.index)
        if len(df) < 40: return score
        vol_ma = df["Volume"].rolling(20).mean()
        has_sc, sc_idx, sc_low, has_ar, ar_high, has_st = False, 0, 0.0, False, 0.0, False
        search_df = df.iloc[-120:] if len(df) > 120 else df 
        for i in range(1, len(search_df)):
            idx, vol, close, low, high, open_px, prev_close = search_df.index[i], search_df["Volume"].iloc[i], search_df["Close"].iloc[i], search_df["Low"].iloc[i], search_df["High"].iloc[i], search_df["Open"].iloc[i], search_df["Close"].iloc[i-1]
            vol_ma_i = vol_ma.loc[idx] if pd.notna(vol_ma.loc[idx]) else 1.0
            local_min = search_df["Close"].iloc[max(0, i - 20):i].min()
            if not has_sc:
                if close < prev_close and vol > vol_ma_i * 2.5 and low <= local_min and close > low + (high - low) * 0.4: has_sc, sc_idx, sc_low, score.loc[idx] = True, i, low, 0.3
            elif has_sc and not has_ar and (i - sc_idx <= 25):
                if close > open_px and close > prev_close and vol > vol_ma_i: has_ar, ar_high, score.loc[idx] = True, high, 0.4
            elif has_ar and not has_st:
                if vol < search_df["Volume"].iloc[sc_idx] * 0.75 and low <= sc_low * 1.05 and close >= sc_low * 0.98: has_st, score.loc[idx] = True, 0.6
            elif has_st:
                if low < sc_low and close > sc_low and vol > vol_ma_i * 1.2: score.loc[idx], sc_low = 0.9, low 
                elif low > sc_low and low < search_df["Low"].iloc[i - 1] and vol < vol_ma_i * 0.8 and close > open_px: score.loc[idx] = 0.85
                elif close > ar_high and vol > vol_ma_i * 1.5 and close - open_px > (high - low) * 0.7: score.loc[idx], has_sc = 1.0, False 
        return score

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        f = pd.DataFrame(index=df.index)
        rng = df["High"] - df["Low"]
        vol_ma20, spread_ma20 = df["Volume"].rolling(20).mean(), rng.rolling(20).mean()
        close_diff, midpoint = df["Close"].diff(), (df["High"] + df["Low"]) / 2
        f["f04_absorption"] = ((df["Volume"] / vol_ma20.replace(0, 1e-5)).clip(0, 5) / (rng / spread_ma20.replace(0, 1e-5)).clip(0.1, 5)) * (1.0 - ((df["Close"] - df["Low"].rolling(20).min()) / (df["High"].rolling(20).max() - df["Low"].rolling(20).min() + 1e-5)).clip(0, 1))
        f["f36_wyckoff_score"] = self._compute_quick_wyckoff(df)
        obv_cum = (np.sign(close_diff) * df["Volume"]).cumsum()
        f["f07_obv_velocity"] = (obv_cum.diff(10) / obv_cum.abs().rolling(10).mean().replace(0, np.nan)).clip(-3, 3)
        rolling_low_10 = df["Low"].shift(1).rolling(10).min()
        f["f20_liquidity_sweep"] = ((df["Low"] < rolling_low_10) & (df["Close"] > rolling_low_10)).astype(float)
        f["f26_accept_reject"] = ((df["Close"] > midpoint) & (df["Volume"] > vol_ma20)).astype(float).rolling(5).mean() - ((df["Close"] < midpoint) & (df["Volume"] > vol_ma20)).astype(float).rolling(5).mean()
        f["f35_struct_break"] = (df["Close"] > df["High"].rolling(20).max().shift(1)).astype(float) - (df["Close"] < df["Low"].rolling(20).min().shift(1)).astype(float)
        f["f14_inst_intent"] = (f["f04_absorption"] * 0.3 + f["f07_obv_velocity"].clip(0, 1) * 0.3 + f["f20_liquidity_sweep"] * 0.4).clip(0, 1)
        f["f_effort_vs_result"] = ((df["Volume"] / vol_ma20) / ((rng / spread_ma20).replace(0, 1e-5)).replace(np.inf, 5)).clip(0, 5)
        f["f_stopping_volume"] = ((close_diff < 0) & (df["Volume"] > (vol_ma20 + df["Volume"].rolling(20).std().fillna(0))) & (df["Close"] > df["Low"] + rng * 0.5)).astype(float)
        f["f_reaccumulation"] = ((df["Close"] > df["Close"].rolling(50).mean()) & (close_diff < 0) & (df["Volume"] < vol_ma20 * 0.8)).astype(float).rolling(5).sum() / 5.0
        f["f_rs_spy"] = (df["Close"].pct_change(20) - df["spy_close"].pct_change(20)).fillna(0) if "spy_close" in df.columns else 0.0
        return f.fillna(0)

    def composite_cis(self, factors: pd.DataFrame, df: pd.DataFrame = None) -> pd.Series:
        base_weights = {"f04_absorption": 4, "f07_obv_velocity": 4, "f14_inst_intent": 6, "f20_liquidity_sweep": 5, "f26_accept_reject": 3, "f35_struct_break": 3, "f_effort_vs_result": 4, "f_stopping_volume": 4, "f_reaccumulation": 3, "f_rs_spy": 4}
        dynamic_weights = {f: pd.Series(base_weights.get(f, 0), index=factors.index) for f in factors.columns if f in base_weights}
        score = pd.Series(0.0, index=factors.index)
        for col in dynamic_weights: score += factors[col].clip(-2, 2) * dynamic_weights[col]
        norm_score = (score / sum(dynamic_weights.values()).replace(0, np.nan).fillna(1) * 100 + 50).clip(0, 100).round(1)
        if "f36_wyckoff_score" in factors.columns: norm_score = (norm_score + factors["f36_wyckoff_score"] * 5).clip(0, 100)
        return norm_score

    def get_wyckoff_phase(self, df: pd.DataFrame) -> pd.Series:
        phases = pd.Series("לא בתהליך איסוף", index=df.index)
        if len(df) < 60: return phases
        close, vol = df['Close'], df['Volume']
        sma20, sma50, sma200 = close.rolling(20).mean(), close.rolling(50).mean(), close.rolling(200).mean()
        vol_ma, high60, low60, atr = vol.rolling(20).mean(), df['High'].rolling(60).max(), df['Low'].rolling(60).min(), (df['High'] - df['Low']).rolling(14).mean()
        obv = (np.sign(close.diff()) * vol).cumsum()
        obv_diff, obv_min60 = obv.diff(10), obv.rolling(60).min()
        rs_spy = (close.pct_change(20) - df["spy_close"].pct_change(20)).fillna(0) if "spy_close" in df.columns else pd.Series(0.0, index=df.index)

        for i in range(60, len(df)):
            c, v, v_ma, h60, l60, a, s20, s50, s200, o_diff, rs = close.iloc[i], vol.iloc[i], vol_ma.iloc[i], high60.iloc[i-1], low60.iloc[i-1], atr.iloc[i], sma20.iloc[i], sma50.iloc[i], sma200.iloc[i] if not pd.isna(sma200.iloc[i]) else sma50.iloc[i], obv_diff.iloc[i], rs_spy.iloc[i]
            prev_phase = phases.iloc[i-1]

            if c > s20 > s50 > s200 and c >= h60 * 0.95: phases.iloc[i] = "Phase E (Markup)" if o_diff > 0 and rs > 0 else "TRANSITION / UNCERTAIN STATE"
            elif "Markup" in prev_phase and c > s200 and c < h60 * 0.95 and v < v_ma: phases.iloc[i] = "Re-accumulation (LPS/BUEC)" if o_diff >= 0 else "TRANSITION / UNCERTAIN STATE"
            elif c > s50 and v > v_ma * 1.5 and c >= h60 * 0.90 and c > df['Open'].iloc[i]: phases.iloc[i] = "Phase D (SOS / Breakout)" if o_diff > 0 else "TRANSITION / UNCERTAIN STATE"
            elif df['Low'].iloc[i] < l60 + a and c < s50:
                is_new_low, positive_close, obv_min_prev = df['Low'].iloc[i] < l60, c > df['Open'].iloc[i], obv_min60.iloc[i-1] if i > 0 and not pd.isna(obv_min60.iloc[i-1]) else obv.iloc[i]
                if is_new_low and v > v_ma * 1.5 and positive_close and obv.iloc[i] >= obv_min_prev: phases.iloc[i] = "Phase C (Strong Spring)"
                elif is_new_low and (not positive_close or obv.iloc[i] < obv_min_prev): phases.iloc[i] = "Failed Sweep / Warning" 
                elif positive_close and v > v_ma * 1.2: phases.iloc[i] = "Phase C (Spring / Liquidity Sweep)"
                else: phases.iloc[i] = "TRANSITION / UNCERTAIN STATE"
            elif "Spring" in prev_phase or "Accumulation" in prev_phase or "Phase C" in prev_phase:
                if c > l60 + a * 2 and c < s50 and v < v_ma * 0.8: phases.iloc[i] = "Phase D (LPS)" if o_diff >= 0 and df['Low'].iloc[i] >= df['Low'].iloc[i-1] else "TRANSITION / UNCERTAIN STATE"
                elif c < s50: phases.iloc[i] = "Phase B (Accumulation)"
                else: phases.iloc[i] = "TRANSITION / UNCERTAIN STATE"
            elif c < l60 * 1.05 and v > v_ma * 2.5 and df['Close'].iloc[i] > df['Low'].iloc[i] + (df['High'].iloc[i] - df['Low'].iloc[i]) * 0.5: phases.iloc[i] = "Phase A (Selling Climax)"
            elif c < s20 < s50 and c < s200: phases.iloc[i] = "Markdown (Institutional Distribution)" if o_diff < 0 else "TRANSITION / UNCERTAIN STATE"
            elif c < s50 and v > v_ma * 2.0 and c < df['Open'].iloc[i]: phases.iloc[i] = "Distribution (Heavy Supply)"
            else: phases.iloc[i] = prev_phase if prev_phase not in ["TRANSITION / UNCERTAIN STATE", "לא בתהליך איסוף"] else "TRANSITION / UNCERTAIN STATE"
        return phases

def run_wyckoff_anchored_backtest(ticker, use_ai, threshold, period=None, start=None, end=None, risk_profile="Balanced", stop_loss_pct=0.05, atr_multiplier=2.0):
    df = get_data(ticker, period=period, start=start, end=end)
    if df is None: return None, pd.DataFrame()
    engine = FactorEngine(BacktestConfig(period=period if period else f"{start}/{end}", stop_loss_pct=stop_loss_pct, atr_multiplier=atr_multiplier))
    factors = engine.compute(df)
    df['wyckoff_phase'], df['cis_score'] = engine.get_wyckoff_phase(df), engine.composite_cis(factors, df)
    df['Daily_Return'], df['rs_spy_factor'] = df['Close'].pct_change().fillna(0), factors.get('f_rs_spy', 0.0)

    atr_series = pd.concat([df['High']-df['Low'], (df['High']-df['Close'].shift(1)).abs(), (df['Low']-df['Close'].shift(1)).abs()], axis=1).max(axis=1).rolling(14).mean()
    positions, audit_logs = [], []
    in_position, entry_price, entry_atr, entry_phase, entry_date, entry_index_int, peak_price, cis_at_entry, stop_loss_level = False, 0, 0, "", None, 0, 0, 0, 0
    
    for i in range(len(df)):
        current_phase, current_cis = df['wyckoff_phase'].iloc[i], df['cis_score'].iloc[i]
        if not in_position:
            if check_phase_entry_allowed(current_phase, risk_profile) and current_cis >= threshold and df['rs_spy_factor'].iloc[i] > -0.02:
                positions.append(1)
                in_position, entry_price, entry_phase, entry_date, entry_index_int, peak_price, cis_at_entry = True, df['Close'].iloc[i], current_phase, df.index[i], i, df['Close'].iloc[i], current_cis
                entry_atr = atr_series.iloc[i] if not pd.isna(atr_series.iloc[i]) else 0
                stop_loss_level = min(entry_price * (1 - stop_loss_pct), entry_price - entry_atr * atr_multiplier) if entry_atr > 0 else entry_price * (1 - stop_loss_pct)
            else: positions.append(0)
        else:
            if df['Low'].iloc[i] <= stop_loss_level or "Markdown" in current_phase or "Distribution" in current_phase or current_cis < threshold - 20:
                positions.append(0)
                exit_px = stop_loss_level if df['Low'].iloc[i] <= stop_loss_level else df['Close'].iloc[i]
                ret = (exit_px - entry_price) / entry_price
                is_win = ret > ((entry_atr / entry_price) * 1.2 if entry_atr > 0 else 0.02)
                phase_success = ((df['Close'].iloc[entry_index_int + 1 : min(entry_index_int + 21, len(df))].max() - entry_price) / entry_price) >= 0.04 if entry_index_int + 1 < len(df) and any(p in entry_phase for p in ["Phase C", "Spring", "Phase D", "Re-accumulation", "Phase E", "Markup", "SOS", "LPS"]) else False
                audit_logs.append({"entry_date": entry_date.strftime("%Y-%m-%d"), "exit_date": df.index[i].strftime("%Y-%m-%d"), "phase_at_entry": entry_phase, "entry_price": round(entry_price, 2), "exit_price": round(exit_px, 2), "return_pct": round(ret * 100, 2), "profit": round(10000.0 * ret, 2), "win": is_win, "is_win": is_win, "phase_success": phase_success, "wyckoff_confirmed": True, "exit_type": "Stop_Loss" if df['Low'].iloc[i] <= stop_loss_level else "Phase_Change", "phase_at_exit": current_phase, "cis_at_entry": cis_at_entry})
                in_position = False
            else:
                positions.append(1)
                if df['Close'].iloc[i] > peak_price: peak_price = df['Close'].iloc[i]

    while len(positions) < len(df): positions.append(0)
    df['Position'] = pd.Series(positions, index=df.index).shift(1).fillna(0)
    df['Strategy_Return'] = df['Position'] * df['Daily_Return']
    df['Cum_Strategy'] = (1 + df['Strategy_Return']).cumprod() - 1
    return df, pd.DataFrame(audit_logs)

def explain_score_simple(df: pd.DataFrame, current_phase: str, cis_score: float, allowed: bool) -> str:
    if df is None or df.empty: return "אין מספיק נתונים."
    close, vol = df['Close'].iloc[-1], df['Volume'].iloc[-1]
    vol_ma20 = df['Volume'].rolling(20).mean().iloc[-1] if len(df) >= 20 else 1.0
    sma20, sma50, sma200 = df['Close'].rolling(20).mean().iloc[-1] if len(df)>=20 else close, df['Close'].rolling(50).mean().iloc[-1] if len(df)>=50 else close, df['Close'].rolling(200).mean().iloc[-1] if len(df)>=200 else close
    rs_spy = (df["Close"].pct_change(20).iloc[-1] - df["spy_close"].pct_change(20).iloc[-1]) if "spy_close" in df.columns else 0.0
    
    text = ["**📈 מה קורה למחיר?**"]
    if close > sma20 > sma50 > sma200: text.append("מגמת עלייה חזקה ובריאה מעל כל הממוצעים החשובים.")
    elif close > sma20 > sma50: text.append("מגמת עלייה טובה בטווח הקצר-בינוני, מתאוששת.")
    elif close < sma20 < sma50: text.append("חלשה ובמגמת ירידה. לחץ מוכרים שולט.")
    else: text.append("המניה מדשדשת (הולכת הצידה) ללא כיוון מובהק כרגע.")
        
    text.append("\n**👥 זרימת ההון (נפח מסחר):**")
    if vol > vol_ma20 * 1.2: text.append("מחזורים גבוהים! כסף גדול מתערב ומייצר עניין חריג.")
    elif vol < vol_ma20 * 0.8: text.append("יובש. אין כסף חכם שדוחף את הנייר לשום כיוון.")
    else: text.append("מחזורי מסחר ממוצעים.")
        
    text.append("\n**💪 עוצמה מול השוק הכללי:**")
    text.append("המניה חזקה יותר מהשוק (מובילה)." if rs_spy > 0.02 else ("המניה חלשה ומפגרת אחרי השוק." if rs_spy < -0.02 else "מתנהגת בדומה לשוק הרחב."))
    return "\n".join(text)

def explain_score(df: pd.DataFrame, current_phase: str, cis_score: float) -> str:
    if df is None or df.empty: return "אין נתונים."
    close, vol_ratio, obv_diff = df['Close'].iloc[-1], df['Volume'].iloc[-1] / (df['Volume'].rolling(20).mean().iloc[-1] if len(df) >= 20 else 1.0), (np.sign(df['Close'].diff()) * df['Volume']).cumsum().diff(10).iloc[-1] if len(df) >= 10 else 0
    rs_spy = (df["Close"].pct_change(20).iloc[-1] - df.get("spy_close", df["Close"]).pct_change(20).iloc[-1]) if "spy_close" in df.columns else 0.0
    pos, neg = [], []
    if close > df['Close'].rolling(20).mean().iloc[-1] > df['Close'].rolling(50).mean().iloc[-1]: pos.append("מבנה מחיר שוורי.")
    elif close < df['Close'].rolling(20).mean().iloc[-1] < df['Close'].rolling(50).mean().iloc[-1]: neg.append("מבנה מחיר דובי.")
    if obv_diff > 0 and vol_ratio >= 1.2 and close > df['Open'].iloc[-1]: pos.append("זרימת הון חיובית משמעותית.")
    elif obv_diff < 0 and vol_ratio >= 1.2 and close < df['Open'].iloc[-1]: neg.append("לחץ מכירות ויציאת הון.")
    if rs_spy > 0.02: pos.append("עוצמה יחסית חיובית מול השוק.")
    elif rs_spy < -0.02: neg.append("חולשה יחסית משמעותית.")
    return f"**Driver:** {'ACCUMULATION' if len(pos) >= 2 and not neg else ('DISTRIBUTION' if len(neg) >= 2 and not pos else 'TRANSITION')}\n\n**Positive:** {pos}\n**Negative:** {neg}"

def _extract_last(factors: pd.DataFrame, col: str, default: float = 0.0) -> float:
    return float(factors[col].iloc[-1]) if col in factors.columns else default

def build_smart_money_dashboard(factors: pd.DataFrame) -> dict:
    return {
        "OBV Velocity": "✅ כניסה אגרסיבית" if _extract_last(factors, 'f07_obv_velocity') > 0.02 else ("❌ יציאת הון" if _extract_last(factors, 'f07_obv_velocity') < -0.02 else "⚠️ נייטרלי / מעורב"),
        "Price Structure": "✅ שבירת מבנה (BOS)" if _extract_last(factors, 'f35_struct_break') > 0 else "❌ דשדוש או ירידה",
        "Supply Absorption": "✅ ספיגה עמוקה" if _extract_last(factors, 'f04_absorption', 1.0) > 1.2 else "⚠️ אין ספיגה משמעותית",
        "Relative Strength": "✅ מוביל על השוק" if _extract_last(factors, 'f_rs_spy') > 0 else "❌ מפגר אחרי השוק",
        "Volume Anomalies": "✅ בלימת מחזורים" if _extract_last(factors, 'f_stopping_volume') > 0 else "⚠️ מחזורים שגרתיים"
    }

def generate_roadmap(current_phase: str) -> dict:
    roadmap = {"previous_phase": "לא ידוע", "next_phase": "לא ידוע", "action_plan": "המתן לאישורים.", "what_if_success": "-", "what_if_fail": "-"}
    if "Phase A" in current_phase: roadmap.update({"previous_phase": "ירידות", "next_phase": "שלב B", "action_plan": "חפש סימני ספיגה."})
    elif "Phase B" in current_phase: roadmap.update({"previous_phase": "שלב A", "next_phase": "שלב C (ניעור)", "action_plan": "היערך לניעור מטה."})
    elif "Phase C" in current_phase or "Spring" in current_phase: roadmap.update({"previous_phase": "שלב B", "next_phase": "שלב D", "action_plan": "תזמון כניסה. סטופ מתחת לניעור."})
    elif "Phase D" in current_phase or "LPS" in current_phase: roadmap.update({"previous_phase": "שלב C", "next_phase": "שלב E", "action_plan": "חזק פוזיציות לקראת פריצה."})
    elif "Phase E" in current_phase or "Markup" in current_phase: roadmap.update({"previous_phase": "שלב D", "next_phase": "פיזור עליון", "action_plan": "נהל עם סטופ דינמי."})
    elif "Distribution" in current_phase: roadmap.update({"previous_phase": "שלב E", "next_phase": "ירידות", "action_plan": "צא מלונג. פיזור סחורה."})
    elif "Markdown" in current_phase: roadmap.update({"previous_phase": "פיזור", "next_phase": "שלב A", "action_plan": "התרחק! המתן לבלימה."})
    return roadmap

def calculate_wyckoff_probability(df: pd.DataFrame, factors: pd.DataFrame, current_phase: str, mode: str, cis_score: float) -> dict:
    prob_modifier = 0.85 if mode == "Conservative" else (1.15 if mode == "Optimistic" else 1.0)
    if "Distribution" in current_phase or "Markdown" in current_phase: prob_modifier -= 0.35
    accum_prob = min(99, max(1, int(cis_score * prob_modifier)))
    bo_mod, dist_mod = (30, 15) if "Phase C" in current_phase or "Spring" in current_phase else ((40, 10) if "Phase D" in current_phase or "LPS" in current_phase else ((30, 25) if "Phase E" in current_phase or "Markup" in current_phase else ((0, 40) if "Distribution" in current_phase or "Markdown" in current_phase else (10, 20))))
    if _extract_last(factors, 'f07_obv_velocity') < -0.02: dist_mod += 25
    return {"accumulation_chance": accum_prob, "breakout_30d": min(98, max(2, int((accum_prob * 0.40) + bo_mod))), "distribution_risk": min(98, max(2, int((100 - accum_prob) * 0.40 + dist_mod))), "educational_note": "ההסתברויות נגזרות ממיקום טכני מוסדי."}

def detect_failure_risks(df: pd.DataFrame, factors: pd.DataFrame, current_phase: str, accum_prob: float, allowed: bool, ticker: str) -> list:
    warnings_list = []
    if "Distribution" in current_phase or "Markdown" in current_phase: warnings_list.append("🔴 סכנת מחיקה: כסף חכם מפזר סחורה. אל תחפש תחתיות.")
    elif "Spring" in current_phase and _extract_last(factors, 'f07_obv_velocity') < 0: warnings_list.append("🔴 ניעור שקרי: ה-OBV יורד בחדות. זה אינו ניעור מוסדי.")
    elif _extract_last(factors, 'f_effort_vs_result') > 2.5 and df['Close'].iloc[-1] < df['Open'].iloc[-1]: warnings_list.append("⚠️ מוכר מוסדי עקשן מכביד מלמעלה (מאמץ קונים ללא תוצאה).")
    if not warnings_list: warnings_list.append(f"✅ שמיים נקיים (Clear Skies): התנהגות המחיר וזרימת ההון תקינה לחלוטין.")
    return warnings_list

def generate_replay_analogies(ticker: str, current_phase: str, accum_prob: float, factors: pd.DataFrame) -> list:
    if "Phase C" in current_phase: return ["🔍 הניעור הנוכחי מזכיר את ה-Spring של BTC בינואר 2023 - קצירת נזילות מהירה."]
    elif "Phase D" in current_phase: return ["🔍 מזכיר את ההתבססות של NVDA רגע לפני הפריצה הגדולה שלה."]
    elif "Distribution" in current_phase: return ["🔍 דפוס הפיזור משכפל את התנהגות TSLA בסוף 2022."]
    return ["🔍 איסוף שקט. שחיקה המזכירה את AMZN ב-2023 - קרנות גידור אוספות בשקט וללא לחץ."]
