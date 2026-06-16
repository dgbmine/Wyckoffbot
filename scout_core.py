import numpy as np
import pandas as pd
import yfinance as yf
from dataclasses import dataclass
import warnings
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
import plotly.graph_objects as go
import streamlit as st

warnings.filterwarnings("ignore")

# ---------- Helper Functions ----------
def clean_filename(name):
    return "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).replace(' ', '_')

def get_data(ticker, period="1y", start=None, end=None):
    try:
        if start is not None and end is not None:
            df = yf.Ticker(ticker).history(start=start, end=end)
        else:
            df = yf.Ticker(ticker).history(period=period)

        if df is None or len(df) < 40:
            return None

        df.index = pd.to_datetime(df.index).tz_localize(None)

        if start is not None and end is not None:
            spy_df = yf.Ticker("SPY").history(start=start, end=end)
            vix_df = yf.Ticker("^VIX").history(start=start, end=end)
        else:
            spy_df = yf.Ticker("SPY").history(period=period)
            vix_df = yf.Ticker("^VIX").history(period=period)

        if spy_df is not None and not spy_df.empty:
            spy_df.index = pd.to_datetime(spy_df.index).tz_localize(None)
            df = df.join(spy_df[['Close']].rename(columns={'Close': 'spy_close'}), how='left')
        else:
            df['spy_close'] = np.nan

        if vix_df is not None and not vix_df.empty:
            vix_df.index = pd.to_datetime(vix_df.index).tz_localize(None)
            df = df.join(vix_df[['Close']].rename(columns={'Close': 'vix_close'}), how='left')
        else:
            df['vix_close'] = np.nan

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
    commission:      float = 0.001
    initial_capital: float = 100_000.0
    hold_days:       int   = 40
    period:          str   = "2y"
    stop_loss_pct:   float = 0.05
    atr_multiplier:  float = 2.0

# ---------- Factor Engine ----------
class FactorEngine:
    def __init__(self, cfg: BacktestConfig):
        self.cfg = cfg

    def _compute_quick_wyckoff(self, df: pd.DataFrame) -> pd.Series:
        score    = pd.Series(0.0, index=df.index)
        if len(df) < 40:
            return score
        vol_ma   = df['Volume'].rolling(20).mean()
        has_sc, has_ar, has_st = False, False, False
        sc_idx, sc_low, ar_high = 0, 0, 0
        search_df = df.iloc[-90:]
        for i in range(1, len(search_df)):
            idx      = search_df.index[i]
            vol      = search_df['Volume'].iloc[i]
            vol_ma_i = vol_ma.loc[idx]
            close    = search_df['Close'].iloc[i]
            low      = search_df['Low'].iloc[i]
            high     = search_df['High'].iloc[i]
            open_px  = search_df['Open'].iloc[i]
            if not has_sc:
                if close < open_px and vol > vol_ma_i * 2.0 and close <= search_df['Close'].iloc[max(0, i-20):i].min():
                    has_sc  = True
                    sc_idx  = i
                    sc_low  = low
                    score.loc[idx] = 0.3
            elif has_sc and not has_ar and (i - sc_idx <= 15):
                if close > open_px and close > search_df['Close'].iloc[i-1]:
                    has_ar  = True
                    ar_high = high
                    score.loc[idx] = 0.4
            elif has_ar and not has_st:
                if vol < search_df['Volume'].iloc[sc_idx] * 0.75 and abs(low - sc_low)/sc_low < 0.05:
                    has_st = True
                    score.loc[idx] = 0.6
            elif has_st:
                if low < sc_low and close > sc_low:
                    score.loc[idx] = 0.8
                elif low > sc_low and low < search_df['Low'].iloc[i-1] and vol < vol_ma_i:
                    score.loc[idx] = 0.85
                elif close > ar_high and vol > vol_ma_i * 1.5:
                    score.loc[idx] = 1.0
                    has_sc = False
        return score

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        f = pd.DataFrame(index=df.index)
        rng = df["High"] - df["Low"]
        vol_ma20 = df["Volume"].rolling(20).mean()
        rvol = df["Volume"] / vol_ma20.replace(0, np.nan)
        spread_ma20 = rng.rolling(20).mean()

        f["f04_absorption"] = (((df["Volume"] > vol_ma20 * 1.5) & (rng < spread_ma20 * 0.8)) & (df["Close"] <= df["Low"].rolling(20).min() * 1.05)).astype(float)
        f["f36_wyckoff_score"] = self._compute_quick_wyckoff(df)
        f["f07_obv_velocity"] = ((np.sign(df["Close"].diff()) * df["Volume"]).cumsum().diff(10) / (np.sign(df["Close"].diff()) * df["Volume"]).cumsum().abs().rolling(10).mean().replace(0, np.nan)).clip(-3, 3)
        f["f14_inst_intent"] = (f["f04_absorption"] * 0.3 + f["f07_obv_velocity"].clip(0, 1) * 0.4 + (f["f04_absorption"].rolling(30).max() * (rvol < 0.7).astype(float)) * 0.3).clip(0, 1)
        f["f20_liquidity_sweep"] = ((df["Low"] < df["Low"].rolling(20).min().shift(1)) & (df["Close"] > df["Low"].rolling(20).min().shift(1))).astype(float)
        f["f26_accept_reject"] = ((df["Close"] > (df["High"] + df["Low"]) / 2) & (df["Volume"] > vol_ma20)).astype(float).rolling(5).mean() - ((df["Close"] < (df["High"] + df["Low"]) / 2) & (df["Volume"] > vol_ma20)).astype(float).rolling(5).mean()
        f["f35_struct_break"] = (df["Close"] > df["High"].rolling(20).max().shift(1)).astype(float) - (df["Close"] < df["Low"].rolling(20).min().shift(1)).astype(float)

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
        # Start with base weights as Series for each factor
        dynamic_weights = {f: pd.Series(base_weights[f], index=factors.index) for f in base_weights}

        if df is not None and "wyckoff_phase" in df.columns:
            phase_series = df["wyckoff_phase"]
            # Adjust weights based on Wyckoff phase (symbolic example)
            for idx in factors.index:
                phase = phase_series.loc[idx] if idx in phase_series.index else "לא בתהליך איסוף"
                if "Phase C" in phase:          # Spring / test
                    dynamic_weights["f04_absorption"].loc[idx] *= 1.4
                    dynamic_weights["f20_liquidity_sweep"].loc[idx] *= 1.3
                elif "Phase D" in phase:        # Sign of Strength / LPS
                    dynamic_weights["f35_struct_break"].loc[idx] *= 1.5
                    dynamic_weights["f07_obv_velocity"].loc[idx] *= 1.2
                elif "Phase E" in phase:        # Markup
                    dynamic_weights["f26_accept_reject"].loc[idx] *= 1.4
                    dynamic_weights["f35_struct_break"].loc[idx] *= 1.2
                # Distribution phases would decrease weights, but we keep it simple

        total_w = sum(dynamic_weights.values())
        score = pd.Series(0.0, index=factors.index)
        for col in base_weights:
            if col in factors.columns:
                score += factors[col].clip(-1, 1) * dynamic_weights[col]
        return (score / total_w.replace(0, np.nan).fillna(1) * 100 + 50).clip(0, 100).round(1)

    def get_wyckoff_phase(self, df: pd.DataFrame) -> pd.Series:
        """
        Simplified Wyckoff phase detection.
        Returns a string for each bar indicating the phase.
        """
        if len(df) < 30:
            return pd.Series("לא בתהליך איסוף", index=df.index)

        phases = pd.Series("לא בתהליך איסוף", index=df.index)
        low_20 = df['Low'].rolling(20).min()
        high_20 = df['High'].rolling(20).max()
        vol_ma = df['Volume'].rolling(20).mean()

        # Detect potential Accumulation/Distribution cycles very simply
        for i in range(30, len(df)):
            idx = df.index[i]
            # Look for a selling climax (Phase A) - sharp drop with high volume, then recovery
            if df['Low'].iloc[i-5:i].min() < low_20.iloc[i-1] and df['Volume'].iloc[i] > vol_ma.iloc[i] * 1.5 and df['Close'].iloc[i] > df['Open'].iloc[i]:
                # Potential spring
                phases.loc[idx] = "Phase C (Spring/LPS)"
            # Break above recent high with volume -> Phase D / SOS
            elif df['Close'].iloc[i] > high_20.iloc[i-1] and df['Volume'].iloc[i] > vol_ma.iloc[i]:
                phases.loc[idx] = "Phase D (SOS/Breakout)"
            # Price stays in range, low volume -> Phase B
            elif (df['High'].iloc[i] <= high_20.iloc[i-1]) and (df['Low'].iloc[i] >= low_20.iloc[i-1]) and df['Volume'].iloc[i] < vol_ma.iloc[i] * 0.7:
                phases.loc[idx] = "Phase B (בסיס/צבירה)"
            # Markup with rising volume -> Phase E
            elif df['Close'].iloc[i] > df['Close'].iloc[i-1] and df['Volume'].iloc[i] > vol_ma.iloc[i]:
                phases.loc[idx] = "Phase E (Markup/עליות)"

        # Propagate last phase forward to fill gaps (optional)
        phases = phases.replace("לא בתהליך איסוף", method='ffill').fillna("לא בתהליך איסוף")
        return phases

# ---------- Backtest Runner ----------
def run_wyckoff_anchored_backtest(ticker, use_ai, threshold, period=None, start=None, end=None, risk_profile="Balanced", stop_loss_pct=0.05, atr_multiplier=2.0):
    df = get_data(ticker, period=period, start=start, end=end)
    if df is None:
        return None, None

    cfg_period = period if period else f"{start}/{end}"
    engine = FactorEngine(BacktestConfig(period=cfg_period, stop_loss_pct=stop_loss_pct, atr_multiplier=atr_multiplier))
    factors = engine.compute(df)
    df['wyckoff_phase'] = engine.get_wyckoff_phase(df)
    df['cis_score'] = engine.composite_cis(factors, df)
    # Dummy trades DataFrame (can be expanded)
    trades = pd.DataFrame(columns=["Entry Date", "Exit Date", "Return", "Phase"])
    return df, trades

# ---------- Explanation Function ----------
def explain_score(df: pd.DataFrame, current_phase: str, cis_score: float) -> str:
    """
    מנתחת את הנתונים הטכניים (מגמה, נפח, מומנטום) ומחזירה הסבר מילולי בעברית.
    """
    if df is None or df.empty:
        return "אין מספיק נתונים להפקת הסבר."

    # Use the latest bar
    latest = df.iloc[-1]
    close = latest['Close']
    volume = latest['Volume']
    # Simple moving averages
    sma20 = df['Close'].rolling(20).mean().iloc[-1]
    sma50 = df['Close'].rolling(50).mean().iloc[-1] if len(df) >= 50 else sma20
    # Volume analysis
    vol_ma20 = df['Volume'].rolling(20).mean().iloc[-1]
    vol_ratio = volume / vol_ma20 if vol_ma20 > 0 else 1
    # RSI 14
    delta = df['Close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean().iloc[-1]
    avg_loss = loss.rolling(14).mean().iloc[-1]
    if avg_loss == 0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
    # OBV direction (10-day change)
    obv = (np.sign(delta) * volume).cumsum()
    obv_diff = obv.diff(10).iloc[-1] if len(obv) >= 10 else 0
    # Trend strength (price vs. SMAs)
    trend = "עולה" if close > sma20 else "יורד"
    above_all = close > max(sma20, sma50)
    below_all = close < min(sma20, sma50)

    # Build explanation parts
    parts = []

    # Score interpretation
    if cis_score >= 80:
        parts.append("📊 **ציון CIS גבוה מאוד** – מצביע על סבירות גבוהה לתנועה חיובית חזקה.")
    elif cis_score >= 60:
        parts.append("📊 **ציון CIS בינוני-גבוה** – האותות תומכים בעליות אך לא בשיאם.")
    elif cis_score >= 40:
        parts.append("📊 **ציון CIS נייטרלי** – האותות מעורבים, יש להמתין לאישוש נוסף.")
    else:
        parts.append("📊 **ציון CIS נמוך** – לחץ מוכר או חוסר מומנטום, מומלץ להיזהר.")

    # Phase description
    phase_description = {
        "Phase B (בסיס/צבירה)": "השוק נמצא בשלב בסיס/צבירה (Phase B) – טווח מסחר צר ודעיכת נפח, סימן להתכנסות לקראת פריצה.",
        "Phase C (Spring/LPS)": "שלב C (ספרינג / LPS) – לעיתים קרובות מבחן אחרון של התמיכה לפני שינוי כיוון, נפח גבוה והיפוך.",
        "Phase D (SOS/Breakout)": "שלב D (סימן לעוצמה / פריצה) – הפריצה מעלה מלווה בנפח גדול, המוסדיים נכנסים.",
        "Phase E (Markup/עליות)": "שלב E (עליות / Markup) – המגמה השורית בעיצומה, נפח עולה תומך בהמשך העליות."
    }
    phase_text = phase_description.get(current_phase, "השלב הנוכחי: " + current_phase)
    parts.append(f"🔄 **שלב Wyckoff:** {phase_text}")

    # Trend analysis
    if above_all:
        parts.append("📈 **מגמה:** המחיר מעל ממוצעים נעים 20 ו-50 – מגמה עולה ברורה.")
    elif below_all:
        parts.append("📉 **מגמה:** המחיר מתחת לממוצעים – מגמה יורדת.")
    else:
        parts.append(f"📊 **מגמה:** המחיר מעל/מתחת ממוצעים נעים בצורה מעורבת (כיוון: {trend}).")

    # Volume
    if vol_ratio > 2:
        parts.append(f"🔊 **נפח מסחר:** גבוה מאוד (פי {vol_ratio:.1f} מהממוצע) – מעיד על עניין מוסדי.")
    elif vol_ratio > 1.2:
        parts.append(f"🔊 **נפח מסחר:** מעל הממוצע (פי {vol_ratio:.1f}) – פעילות מוגברת.")
    elif vol_ratio < 0.5:
        parts.append(f"🔇 **נפח מסחר:** נמוך מאוד – חוסר עניין, אולי דעיכה.")
    else:
        parts.append("🔊 **נפח מסחר:** תקין.")

    # Momentum (RSI)
    if rsi > 70:
        parts.append(f"⚡ **מומנטום (RSI):** {rsi:.0f} – שוק קניות יתר, תיתכן נסיגה.")
    elif rsi < 30:
        parts.append(f"⚡ **מומנטום (RSI):** {rsi:.0f} – שוק מכירות יתר, פוטנציאל להיפוך.")
    else:
        parts.append(f"⚡ **מומנטום (RSI):** {rsi:.0f} – טווח נורמלי.")

    # OBV trend
    if obv_diff > 0:
        parts.append("📦 **תנועת OBV:** צוברת – הנפח תומך במגמה (קנייה).")
    else:
        parts.append("📦 **תנועת OBV:** נחלשת – הצטברות נפח שלילית (מכירה).")

    # Combine
    return "\n\n".join(parts)

# ---------- Streamlit UI ----------
def main():
    st.set_page_config(page_title="Wyckoff Composite CIS", layout="wide")
    st.title("📈 Wyckoff Composite Institutional Score (CIS)")

    with st.sidebar:
        st.header("הגדרות")
        ticker = st.text_input("סמל מניה", value="AAPL")
        risk_profile = st.selectbox("פרופיל סיכון", ["Balanced", "Aggressive", "Conservative"])
        period = st.selectbox("תקופת ניתוח", ["1y", "2y", "5y", "6mo"], index=1)
        threshold = st.slider("סף ציון CIS לכניסה", 50, 90, 65)
        stop_loss = st.slider("סטופ לוס (%)", 1, 20, 5) / 100
        atr_mult = st.slider("מכפיל ATR", 1.0, 4.0, 2.0, 0.1)
        use_ai = False  # Not used in this demo
        run = st.button("הרץ ניתוח")

    if run:
        with st.spinner("טוען נתונים ומחשב..."):
            df, trades = run_wyckoff_anchored_backtest(
                ticker, use_ai, threshold,
                period=period,
                risk_profile=risk_profile,
                stop_loss_pct=stop_loss,
                atr_multiplier=atr_mult
            )

        if df is None:
            st.error("לא ניתן לטעון נתונים. בדוק את הסמל והתקופה.")
            return

        # Extract latest values
        cis_score = df['cis_score'].iloc[-1]
        current_phase = df['wyckoff_phase'].iloc[-1]

        # Display metrics
        col1, col2, col3 = st.columns(3)
        col1.metric("Composite CIS", f"{cis_score:.1f}")
        col2.metric("Wyckoff Phase", current_phase)
        entry_allowed = check_phase_entry_allowed(current_phase, risk_profile)
        col3.metric("כניסה מותרת?", "✅" if entry_allowed else "🚫")

        # Explanation expander
        with st.expander("🔍 לחץ כאן לקבלת הסבר על הציון"):
            explanation = explain_score(df, current_phase, cis_score)
            st.markdown(explanation)

        # Price chart with CIS overlay
        st.subheader("גרף מחיר וציון CIS")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df.index, y=df['Close'], name="מחיר", line=dict(color='blue')))
        fig.add_trace(go.Scatter(x=df.index, y=df['cis_score'], name="CIS Score", yaxis="y2",
                                 line=dict(color='orange', dash='dot')))
        fig.update_layout(
            xaxis=dict(title="תאריך"),
            yaxis=dict(title="מחיר"),
            yaxis2=dict(title="ציון CIS", overlaying="y", side="right", range=[0,100]),
            legend=dict(x=0.01, y=0.99),
            hovermode="x unified"
        )
        st.plotly_chart(fig, use_container_width=True)

        # Additional info
        st.caption("📌 Wyckoff phase detection מבוסס על ניתוח מבנה מחיר ונפח.")

if __name__ == "__main__":
    main()