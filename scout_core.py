import numpy as np
import pandas as pd
import yfinance as yf
from dataclasses import dataclass
import warnings
import plotly.graph_objects as go
import streamlit as st

warnings.filterwarnings("ignore")


# ---------- Helper Functions ----------
def clean_filename(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).replace(' ', '_')


def get_data(ticker, period="1y", start=None, end=None):
    try:
        if start is not None and end is not None:
            df = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=False)
        else:
            df = yf.Ticker(ticker).history(period=period, auto_adjust=False)

        if df is None or df.empty or len(df) < 40:
            return None

        df.index = pd.to_datetime(df.index).tz_localize(None)
        df = df.sort_index()

        if start is not None and end is not None:
            spy_df = yf.Ticker("SPY").history(start=start, end=end, auto_adjust=False)
            vix_df = yf.Ticker("^VIX").history(start=start, end=end, auto_adjust=False)
        else:
            spy_df = yf.Ticker("SPY").history(period=period, auto_adjust=False)
            vix_df = yf.Ticker("^VIX").history(period=period, auto_adjust=False)

        if spy_df is not None and not spy_df.empty:
            spy_df.index = pd.to_datetime(spy_df.index).tz_localize(None)
            df = df.join(spy_df[["Close"]].rename(columns={"Close": "spy_close"}), how="left")
        else:
            df["spy_close"] = np.nan

        if vix_df is not None and not vix_df.empty:
            vix_df.index = pd.to_datetime(vix_df.index).tz_localize(None)
            df = df.join(vix_df[["Close"]].rename(columns={"Close": "vix_close"}), how="left")
        else:
            df["vix_close"] = np.nan

        return df
    except Exception:
        return None


def check_phase_entry_allowed(phase, risk_profile):
    if "לא בתהליך" in phase:
        return False
    if risk_profile == "Aggressive":
        return any(p in phase for p in ["Phase C", "Phase D", "Phase E", "Spring", "LPS", "SOS", "Breakout"])
    elif risk_profile == "Balanced":
        return any(p in phase for p in ["Phase D", "Phase E", "LPS", "SOS", "Breakout"])
    elif risk_profile == "Conservative":
        return any(p in phase for p in ["Phase E", "Breakout"])
    return False


@dataclass
class BacktestConfig:
    commission: float = 0.001
    initial_capital: float = 100_000.0
    hold_days: int = 40
    period: str = "2y"
    stop_loss_pct: float = 0.05
    atr_multiplier: float = 2.0


# ---------- Human-readable explanation helpers ----------
def _fmt_pct(x):
    try:
        return f"{x:.1%}"
    except Exception:
        return "—"


def _classify_relative(value, reference):
    if pd.isna(value) or pd.isna(reference) or reference == 0:
        return "לא מספיק נתונים"
    ratio = value / reference
    if ratio >= 1.8:
        return "חריג מאוד"
    if ratio >= 1.25:
        return "מעל הממוצע"
    if ratio <= 0.6:
        return "נמוך מאוד"
    return "סביב הממוצע"


# ---------- Factor Engine ----------
class FactorEngine:
    def __init__(self, cfg: BacktestConfig):
        self.cfg = cfg

    def _compute_quick_wyckoff(self, df: pd.DataFrame) -> pd.Series:
        score = pd.Series(0.0, index=df.index)
        if len(df) < 40:
            return score

        vol_ma = df["Volume"].rolling(20).mean()
        has_sc, has_ar, has_st = False, False, False
        sc_idx, sc_low, ar_high = 0, 0.0, 0.0
        search_df = df.iloc[-90:]

        for i in range(1, len(search_df)):
            idx = search_df.index[i]
            vol = search_df["Volume"].iloc[i]
            vol_ma_i = vol_ma.loc[idx]
            close = search_df["Close"].iloc[i]
            low = search_df["Low"].iloc[i]
            high = search_df["High"].iloc[i]
            open_px = search_df["Open"].iloc[i]

            if not has_sc:
                if (
                    close < open_px
                    and vol_ma_i > 0
                    and vol > vol_ma_i * 2.0
                    and close <= search_df["Close"].iloc[max(0, i - 20) : i].min()
                ):
                    has_sc = True
                    sc_idx = i
                    sc_low = low
                    score.loc[idx] = 0.3

            elif has_sc and not has_ar and (i - sc_idx <= 15):
                if close > open_px and close > search_df["Close"].iloc[i - 1]:
                    has_ar = True
                    ar_high = high
                    score.loc[idx] = 0.4

            elif has_ar and not has_st:
                if vol_ma_i > 0 and vol < search_df["Volume"].iloc[sc_idx] * 0.75 and abs(low - sc_low) / max(sc_low, 1e-9) < 0.05:
                    has_st = True
                    score.loc[idx] = 0.6

            elif has_st:
                if low < sc_low and close > sc_low:
                    score.loc[idx] = 0.8
                elif low > sc_low and low < search_df["Low"].iloc[i - 1] and vol < vol_ma_i:
                    score.loc[idx] = 0.85
                elif close > ar_high and vol_ma_i > 0 and vol > vol_ma_i * 1.5:
                    score.loc[idx] = 1.0
                    has_sc = False

        return score

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        f = pd.DataFrame(index=df.index)
        rng = df["High"] - df["Low"]
        vol_ma20 = df["Volume"].rolling(20).mean()
        rvol = df["Volume"] / vol_ma20.replace(0, np.nan)
        spread_ma20 = rng.rolling(20).mean()

        # 1) Absorption: heavy volume, narrow range, price holding near lows.
        f["f04_absorption"] = (
            (
                (df["Volume"] > vol_ma20 * 1.5)
                & (rng < spread_ma20 * 0.8)
                & (df["Close"] <= df["Low"].rolling(20).min() * 1.05)
            )
        ).astype(float)

        # 2) Wyckoff quick signal.
        f["f36_wyckoff_score"] = self._compute_quick_wyckoff(df)

        # 3) OBV velocity: האם הנפח המצטבר תומך בכיוון.
        obv_like = (np.sign(df["Close"].diff()) * df["Volume"]).cumsum()
        denom = obv_like.abs().rolling(10).mean().replace(0, np.nan)
        f["f07_obv_velocity"] = (obv_like.diff(10) / denom).clip(-3, 3)

        # 4) Institutional intent: משקלל ספיגה + OBV + רלטיביות נפח.
        f["f14_inst_intent"] = (
            f["f04_absorption"] * 0.3
            + f["f07_obv_velocity"].clip(0, 1) * 0.4
            + (f["f04_absorption"].rolling(30).max() * (rvol < 0.7).astype(float)) * 0.3
        ).clip(0, 1)

        # 5) Liquidity sweep: שבירה רגעית של תחתית קודמת ואז חזרה מעליה.
        prior_low = df["Low"].rolling(20).min().shift(1)
        f["f20_liquidity_sweep"] = ((df["Low"] < prior_low) & (df["Close"] > prior_low)).astype(float)

        # 6) Acceptance / rejection: האם המחיר סוגר טוב ביחס לטווח עם נפח תומך.
        upper_accept = ((df["Close"] > (df["High"] + df["Low"]) / 2) & (df["Volume"] > vol_ma20)).astype(float)
        lower_reject = ((df["Close"] < (df["High"] + df["Low"]) / 2) & (df["Volume"] > vol_ma20)).astype(float)
        f["f26_accept_reject"] = upper_accept.rolling(5).mean() - lower_reject.rolling(5).mean()

        # 7) Structural break: פריצה מעל מבנה או שבירה מתחתיו.
        f["f35_struct_break"] = (
            (df["Close"] > df["High"].rolling(20).max().shift(1)).astype(float)
            - (df["Close"] < df["Low"].rolling(20).min().shift(1)).astype(float)
        )

        return f.fillna(0)

    def composite_cis(self, factors: pd.DataFrame, df: pd.DataFrame = None) -> pd.Series:
        base_weights = {
            "f04_absorption": 6,
            "f07_obv_velocity": 5,
            "f14_inst_intent": 6,
            "f20_liquidity_sweep": 3,
            "f26_accept_reject": 3,
            "f35_struct_break": 2,
        }

        dynamic_weights = {name: pd.Series(weight, index=factors.index) for name, weight in base_weights.items()}

        if df is not None and "wyckoff_phase" in df.columns:
            phase_series = df["wyckoff_phase"]
            for idx in factors.index:
                phase = phase_series.loc[idx] if idx in phase_series.index else "לא בתהליך איסוף"
                if "Phase C" in phase:
                    dynamic_weights["f04_absorption"].loc[idx] *= 1.4
                    dynamic_weights["f20_liquidity_sweep"].loc[idx] *= 1.3
                elif "Phase D" in phase:
                    dynamic_weights["f35_struct_break"].loc[idx] *= 1.5
                    dynamic_weights["f07_obv_velocity"].loc[idx] *= 1.2
                elif "Phase E" in phase:
                    dynamic_weights["f26_accept_reject"].loc[idx] *= 1.4
                    dynamic_weights["f35_struct_break"].loc[idx] *= 1.2

        total_w = sum(dynamic_weights.values())
        score = pd.Series(0.0, index=factors.index)
        for col in base_weights:
            if col in factors.columns:
                score += factors[col].clip(-1, 1) * dynamic_weights[col]

        return (score / total_w.replace(0, np.nan).fillna(1) * 100 + 50).clip(0, 100).round(1)

    def get_wyckoff_phase(self, df: pd.DataFrame) -> pd.Series:
        if len(df) < 30:
            return pd.Series("לא בתהליך איסוף", index=df.index)

        phases = pd.Series("לא בתהליך איסוף", index=df.index)
        low_20 = df["Low"].rolling(20).min()
        high_20 = df["High"].rolling(20).max()
        vol_ma = df["Volume"].rolling(20).mean()

        for i in range(30, len(df)):
            idx = df.index[i]
            vol_ma_i = vol_ma.iloc[i]
            if pd.isna(vol_ma_i) or vol_ma_i == 0:
                continue

            if (
                df["Low"].iloc[i - 5 : i].min() < low_20.iloc[i - 1]
                and df["Volume"].iloc[i] > vol_ma_i * 1.5
                and df["Close"].iloc[i] > df["Open"].iloc[i]
            ):
                phases.loc[idx] = "Phase C (Spring/LPS)"
            elif df["Close"].iloc[i] > high_20.iloc[i - 1] and df["Volume"].iloc[i] > vol_ma_i:
                phases.loc[idx] = "Phase D (SOS/Breakout)"
            elif (
                df["High"].iloc[i] <= high_20.iloc[i - 1]
                and df["Low"].iloc[i] >= low_20.iloc[i - 1]
                and df["Volume"].iloc[i] < vol_ma_i * 0.7
            ):
                phases.loc[idx] = "Phase B (בסיס/צבירה)"
            elif df["Close"].iloc[i] > df["Close"].iloc[i - 1] and df["Volume"].iloc[i] > vol_ma_i:
                phases.loc[idx] = "Phase E (Markup/עליות)"

        phases = phases.replace("לא בתהליך איסוף", np.nan).ffill().fillna("לא בתהליך איסוף")
        return phases

    def latest_factor_contributions(self, factors: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
        base_weights = {
            "f04_absorption": 6,
            "f07_obv_velocity": 5,
            "f14_inst_intent": 6,
            "f20_liquidity_sweep": 3,
            "f26_accept_reject": 3,
            "f35_struct_break": 2,
        }
        last_idx = factors.index[-1]
        phase = df["wyckoff_phase"].iloc[-1] if "wyckoff_phase" in df.columns else "לא בתהליך איסוף"

        rows = []
        for col, base_w in base_weights.items():
            val = float(factors[col].iloc[-1]) if col in factors.columns else 0.0
            w = base_w
            if "Phase C" in phase and col in {"f04_absorption", "f20_liquidity_sweep"}:
                w *= 1.4 if col == "f04_absorption" else 1.3
            elif "Phase D" in phase and col in {"f35_struct_break", "f07_obv_velocity"}:
                w *= 1.5 if col == "f35_struct_break" else 1.2
            elif "Phase E" in phase and col in {"f26_accept_reject", "f35_struct_break"}:
                w *= 1.4 if col == "f26_accept_reject" else 1.2

            contribution = val * w
            rows.append(
                {
                    "factor": col,
                    "value": val,
                    "weight": w,
                    "contribution": contribution,
                }
            )

        out = pd.DataFrame(rows).sort_values("contribution", ascending=False)
        out.index = [last_idx] * len(out)
        return out


# ---------- Backtest Runner ----------
def run_wyckoff_anchored_backtest(
    ticker,
    use_ai,
    threshold,
    period=None,
    start=None,
    end=None,
    risk_profile="Balanced",
    stop_loss_pct=0.05,
    atr_multiplier=2.0,
):
    df = get_data(ticker, period=period, start=start, end=end)
    if df is None:
        return None, None, None, None

    cfg_period = period if period else f"{start}/{end}"
    engine = FactorEngine(BacktestConfig(period=cfg_period, stop_loss_pct=stop_loss_pct, atr_multiplier=atr_multiplier))
    factors = engine.compute(df)
    df["wyckoff_phase"] = engine.get_wyckoff_phase(df)
    df["cis_score"] = engine.composite_cis(factors, df)
    trades = pd.DataFrame(columns=["Entry Date", "Exit Date", "Return", "Phase"])
    return df, trades, factors, engine


# ---------- Explanation Function ----------
def explain_score(df: pd.DataFrame, current_phase: str, cis_score: float, factors: pd.DataFrame = None, engine: FactorEngine = None) -> str:
    """
    הסבר מילולי פשוט וברור בעברית: למה הציון התקבל, מה השוק עושה, ואילו רמזים חיזקו או החלישו אותו.
    """
    if df is None or df.empty:
        return "אין מספיק נתונים להפקת הסבר."

    latest = df.iloc[-1]
    close = float(latest["Close"])
    open_px = float(latest["Open"])
    high = float(latest["High"])
    low = float(latest["Low"])
    volume = float(latest["Volume"])
    rng = max(high - low, 1e-9)

    sma20 = df["Close"].rolling(20).mean().iloc[-1]
    sma50 = df["Close"].rolling(50).mean().iloc[-1] if len(df) >= 50 else sma20
    vol_ma20 = df["Volume"].rolling(20).mean().iloc[-1]
    vol_ratio = volume / vol_ma20 if vol_ma20 and not pd.isna(vol_ma20) and vol_ma20 > 0 else np.nan

    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean().iloc[-1]
    avg_loss = loss.rolling(14).mean().iloc[-1]
    if pd.isna(avg_loss) or avg_loss == 0:
        rsi = 100.0 if avg_gain and avg_gain > 0 else 50.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

    obv_like = (np.sign(delta) * volume).cumsum()
    obv_diff = obv_like.diff(10).iloc[-1] if len(obv_like) >= 10 else 0

    trend_above = close > sma20 and close > sma50
    trend_below = close < sma20 and close < sma50
    body_pos = (close - low) / rng
    intraday_strength = "סגירה חזקה" if body_pos > 0.7 else "סגירה בינונית" if body_pos > 0.45 else "סגירה חלשה"
    candle_direction = "עלייה יומית" if close > open_px else "ירידה יומית" if close < open_px else "נר ניטרלי"

    score_band = "גבוה מאוד" if cis_score >= 80 else "בינוני-גבוה" if cis_score >= 60 else "ניטרלי" if cis_score >= 40 else "נמוך"

    phase_description = {
        "Phase B (בסיס/צבירה)": "המחיר יושב בתוך טווח. אין עדיין פריצה, אבל יש תחושה של בנייה שקטה מתחת לפני השטח.",
        "Phase C (Spring/LPS)": "יש בדרך כלל ניסיון לנער מוכרים חלשים. לפעמים רואים ניעור מהיר ואז חזרה מעל אזור חשוב.",
        "Phase D (SOS/Breakout)": "המחיר כבר מוכיח עוצמה. יש פריצה מעל אזור התנגדות עם יותר עניין מצד השוק.",
        "Phase E (Markup/עליות)": "המגמה כבר עובדת לטובת הקונים. השוק נוטה להמשיך לעלות כל עוד אין סימני חולשה ברורים.",
    }
    phase_text = phase_description.get(current_phase, f"המערכת מזהה כרגע: {current_phase}")

    parts = []
    parts.append(f"### למה הציון יצא {cis_score:.1f}?")
    parts.append(
        f"הציון נמצא ברמת **{score_band}**. בעברית פשוטה: המערכת רואה בשוק יותר רמזים תומכים מאשר רמזים נגדיים, אבל היא לא מסתכלת רק על מחיר אחד — היא בודקת גם נפח, מבנה, מומנטום והתנהגות סביב השפל והפריצה."
    )

    parts.append(f"### מה המערכת חושבת שהשוק עושה עכשיו?")
    parts.append(f"{phase_text}")

    parts.append("### למה זה מחזק או מחליש את הציון?")

    if trend_above:
        parts.append("המחיר יושב מעל הממוצעים הקצרים והארוכים, ולכן התמונה הכללית נראית תומכת יותר בקונים מאשר במוכרים.")
    elif trend_below:
        parts.append("המחיר מתחת לממוצעים, ולכן המערכת רואה כרגע יותר חולשה מאשר כוח.")
    else:
        parts.append("המחיר נמצא באזור ביניים בין הממוצעים, ולכן התמונה עדיין לא חד-משמעית.")

    if pd.notna(vol_ratio):
        if vol_ratio >= 2:
            parts.append(f"הנפח היום גבוה במיוחד, בערך פי {vol_ratio:.1f} מהממוצע. זה בדרך כלל אומר שיש פה עניין אמיתי ולא רק תנועה אקראית.")
        elif vol_ratio >= 1.2:
            parts.append(f"הנפח מעל הממוצע, בערך פי {vol_ratio:.1f}. זה נותן תמיכה מסוימת לתנועה הנוכחית.")
        elif vol_ratio <= 0.7:
            parts.append(f"הנפח חלש יחסית, בערך פי {vol_ratio:.1f} מהממוצע. זה אומר שהתנועה פחות משכנעת כרגע.")
        else:
            parts.append("הנפח קרוב לממוצע, ולכן הוא לא מוסיף הרבה דרמה לכאן או לכאן.")

    if rsi >= 70:
        parts.append(f"המומנטום חם מאוד (RSI {rsi:.0f}). זה יכול לתמוך בעלייה, אבל גם מזכיר שהמהלך כבר מתוח.")
    elif rsi <= 30:
        parts.append(f"המומנטום חלש מאוד (RSI {rsi:.0f}). לפעמים זה דווקא פותח דלת לתיקון או היפוך.")
    else:
        parts.append(f"המומנטום מאוזן יחסית (RSI {rsi:.0f}), כלומר אין כאן קיצון ברור.")

    if obv_diff > 0:
        parts.append("גם מדד הנפח המצטבר זז בכיוון חיובי, מה שמרמז שהקונים מצטברים בהדרגה.")
    else:
        parts.append("מדד הנפח המצטבר לא תומך חזק בעלייה כרגע, ולכן יש פחות הוכחה לכוח קנייה עקבי.")

    parts.append(f"הנר האחרון מראה {candle_direction} ו-{intraday_strength}, כך שהסגירה של היום עצמה גם נלקחת בחשבון.")

    if factors is not None and engine is not None:
        contrib = engine.latest_factor_contributions(factors, df)
        readable = {
            "f04_absorption": "ספיגה של לחץ מכירה",
            "f07_obv_velocity": "כיוון הנפח המצטבר",
            "f14_inst_intent": "כוונה מוסדית משוערת",
            "f20_liquidity_sweep": "ניעור נזילות",
            "f26_accept_reject": "קבלה או דחייה של המחיר באזור חשוב",
            "f35_struct_break": "שבירת מבנה",
        }
        lines = []
        for _, row in contrib.iterrows():
            label = readable.get(row["factor"], row["factor"])
            val = row["value"]
            weight = row["weight"]
            c = row["contribution"]
            direction = "תומך" if c > 0 else "מחליש" if c < 0 else "ניטרלי"
            lines.append(f"• {label}: הערך שלו כרגע הוא {val:.2f}, המשקל שלו {weight:.1f}, ולכן הוא {direction} בציון הכללי.")
        parts.append("### מה באמת דחף את הציון בפועל?")
        parts.extend(lines)

    parts.append("### איך לקרוא את זה בלי מונחים כבדים?")
    parts.append(
        "תחשוב על המערכת כמו על שופט שמסתכל לא רק על השאלה 'האם המחיר עלה', אלא גם על השאלה 'איך הוא עלה, מי ליווה את המהלך, האם היו מוכרים שנבלעו, והאם נשבר מבנה חשוב'. ככל שיש יותר תשובות חיוביות לשאלות האלה, הציון עולה."
    )

    return "\n\n".join(parts)


# ---------- Streamlit UI ----------
def main():
    st.set_page_config(page_title="Wyckoff Composite CIS", layout="wide")
    st.title("📈 Wyckoff Composite Institutional Score (CIS)")
    st.caption("כלי ניסיוני שמתרגם התנהגות מחיר ונפח לשפה פשוטה וברורה.")

    with st.sidebar:
        st.header("הגדרות")
        ticker = st.text_input("סמל מניה", value="AAPL")
        risk_profile = st.selectbox("פרופיל סיכון", ["Balanced", "Aggressive", "Conservative"])
        period = st.selectbox("תקופת ניתוח", ["1y", "2y", "5y", "6mo"], index=1)
        threshold = st.slider("סף ציון CIS לכניסה", 50, 90, 65)
        stop_loss = st.slider("סטופ לוס (%)", 1, 20, 5) / 100
        atr_mult = st.slider("מכפיל ATR", 1.0, 4.0, 2.0, 0.1)
        run = st.button("הרץ ניתוח")

    if run:
        with st.spinner("טוען נתונים ומחשב..."):
            df, trades, factors, engine = run_wyckoff_anchored_backtest(
                ticker,
                use_ai=False,
                threshold=threshold,
                period=period,
                risk_profile=risk_profile,
                stop_loss_pct=stop_loss,
                atr_multiplier=atr_mult,
            )

        if df is None:
            st.error("לא ניתן לטעון נתונים. בדוק את הסמל והתקופה.")
            return

        cis_score = float(df["cis_score"].iloc[-1])
        current_phase = str(df["wyckoff_phase"].iloc[-1])

        col1, col2, col3 = st.columns(3)
        col1.metric("Composite CIS", f"{cis_score:.1f}")
        col2.metric("Wyckoff Phase", current_phase)
        entry_allowed = check_phase_entry_allowed(current_phase, risk_profile)
        col3.metric("כניסה מותרת?", "✅" if entry_allowed else "🚫")

        with st.expander("🔍 למה המערכת נתנה את הציון הזה?"):
            explanation = explain_score(df, current_phase, cis_score, factors=factors, engine=engine)
            st.markdown(explanation)

        st.subheader("גרף מחיר וציון CIS")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df.index, y=df["Close"], name="מחיר", line=dict(color="blue")))
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["cis_score"],
                name="CIS Score",
                yaxis="y2",
                line=dict(color="orange", dash="dot"),
            )
        )
        fig.update_layout(
            xaxis=dict(title="תאריך"),
            yaxis=dict(title="מחיר"),
            yaxis2=dict(title="ציון CIS", overlaying="y", side="right", range=[0, 100]),
            legend=dict(x=0.01, y=0.99),
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)

        with st.expander("📋 פירוט פקטורים אחרונים"):
            latest_rows = engine.latest_factor_contributions(factors, df).copy()
            latest_rows["value"] = latest_rows["value"].round(2)
            latest_rows["weight"] = latest_rows["weight"].round(2)
            latest_rows["contribution"] = latest_rows["contribution"].round(2)
            st.dataframe(latest_rows.rename(columns={"factor": "פקטור", "value": "ערך", "weight": "משקל", "contribution": "תרומה"}), use_container_width=True)

        st.caption("📌 זיהוי Wyckoff כאן הוא מודל פשוט-חינוכי שמבוסס על מחיר ונפח, לא תחזית ודאית.")


if __name__ == "__main__":
    main()
