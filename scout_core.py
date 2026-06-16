import numpy as np
import pandas as pd
import yfinance as yf
from dataclasses import dataclass
import warnings
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

def calculate_optimal_threshold(model, X, y):
    try:
        probs = model.predict_proba(X)[:, 1] * 100
    except Exception:
        return 65

    best_thresh = 50
    best_score  = 0
    for th in range(50, 95, 2):
        mask         = probs >= th
        trades_count = mask.sum()
        if trades_count >= max(3, len(y) * 0.05):
            win_rate = y[mask].mean()
            score    = win_rate * (1 + np.log1p(trades_count) / 10)
            if score > best_score:
                best_score  = score
                best_thresh = th
    return best_thresh

def check_phase_entry_allowed(phase, risk_profile):
    if "לא בתהליך" in phase or "Markdown" in phase or "Distribution" in phase:
        return False
    if risk_profile == "Aggressive":
        return any(p in phase for p in ["Phase C", "Phase D", "Phase E", "Spring", "LPS", "SOS", "Breakout", "Markup", "Re-accumulation"])
    elif risk_profile == "Balanced":
        return any(p in phase for p in ["Phase D", "Phase E", "LPS", "SOS", "Breakout", "Markup", "Re-accumulation"])
    elif risk_profile == "Conservative":
        return any(p in phase for p in ["Phase E", "Markup"])
    return False

@dataclass
class BacktestConfig:
    commission: float = 0.001
    initial_capital: float = 100_000.0
    hold_days: int = 40
    period: str = "2y"
    stop_loss_pct: float = 0.05
    atr_multiplier: float = 2.0

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
        
        # Deepened lookback for better structural context
        search_df = df.iloc[-120:] if len(df) > 120 else df 
        for i in range(1, len(search_df)):
            idx = search_df.index[i]
            vol = search_df["Volume"].iloc[i]
            vol_ma_i = vol_ma.loc[idx] if pd.notna(vol_ma.loc[idx]) else 1.0
            close = search_df["Close"].iloc[i]
            low = search_df["Low"].iloc[i]
            high = search_df["High"].iloc[i]
            open_px = search_df["Open"].iloc[i]
            prev_close = search_df["Close"].iloc[i-1]
            
            # Dynamic context
            local_min = search_df["Close"].iloc[max(0, i - 20):i].min()
            
            # SC (Selling Climax) - Huge volume on a sharp down move, closing off the lows
            if not has_sc:
                if close < prev_close and vol > vol_ma_i * 2.5 and low <= local_min and close > low + (high - low) * 0.4:
                    has_sc = True
                    sc_idx = i
                    sc_low = low
                    score.loc[idx] = 0.3
            # AR (Automatic Rally) - Rebound from SC driven by short covering
            elif has_sc and not has_ar and (i - sc_idx <= 25):
                if close > open_px and close > prev_close and vol > vol_ma_i:
                    has_ar = True
                    ar_high = high
                    score.loc[idx] = 0.4
            # ST (Secondary Test) - Retest of SC low on lighter volume
            elif has_ar and not has_st:
                if vol < search_df["Volume"].iloc[sc_idx] * 0.75 and low <= sc_low * 1.05 and close >= sc_low * 0.98:
                    has_st = True
                    score.loc[idx] = 0.6
            # Phase C/D/E advancement
            elif has_st:
                # Spring (Phase C) - Liquidity sweep below SC/ST low, closing back inside TR
                if low < sc_low and close > sc_low and vol > vol_ma_i * 1.2: 
                    score.loc[idx] = 0.9 # Very bullish institutional footprint
                    sc_low = low # Update TR floor
                # LPS (Phase D) - Higher low on contracting volume
                elif low > sc_low and low < search_df["Low"].iloc[i - 1] and vol < vol_ma_i * 0.8 and close > open_px: 
                    score.loc[idx] = 0.85
                # SOS / Breakout (Phase D->E) - Strong push through AR high
                elif close > ar_high and vol > vol_ma_i * 1.5 and close - open_px > (high - low) * 0.7: 
                    score.loc[idx] = 1.0
                    has_sc = False # Reset for potential re-accumulation
        return score

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        f = pd.DataFrame(index=df.index)
        rng = df["High"] - df["Low"]
        vol_ma20 = df["Volume"].rolling(20).mean()
        rvol = df["Volume"] / vol_ma20.replace(0, np.nan)
        spread_ma20 = rng.rolling(20).mean()

        close_diff = df["Close"].diff()
        midpoint = (df["High"] + df["Low"]) / 2

        # Core Wyckoff Features
        f["f04_absorption"] = (((df["Volume"] > vol_ma20 * 1.5) & (rng < spread_ma20 * 0.8)) & (df["Close"] <= df["Low"].rolling(20).min() * 1.05)).astype(float)
        f["f36_wyckoff_score"] = self._compute_quick_wyckoff(df)
        
        # OBV Velocity - Enhanced to capture sudden institutional inflows
        obv_raw = np.sign(close_diff) * df["Volume"]
        obv_cum = obv_raw.cumsum()
        f["f07_obv_velocity"] = (obv_cum.diff(10) / obv_cum.abs().rolling(10).mean().replace(0, np.nan)).clip(-3, 3)
        
        # Liquidity Sweep (Spring-like behavior)
        f["f20_liquidity_sweep"] = ((df["Low"] < df["Low"].rolling(20).min().shift(1)) & (df["Close"] > df["Low"].rolling(20).min().shift(1)) & (df["Close"] > df["Open"])).astype(float)
        
        # Accept/Reject Value Areas
        f["f26_accept_reject"] = ((df["Close"] > midpoint) & (df["Volume"] > vol_ma20)).astype(float).rolling(5).mean() - ((df["Close"] < midpoint) & (df["Volume"] > vol_ma20)).astype(float).rolling(5).mean()
        
        # Structural Break (Choch/BOS)
        f["f35_struct_break"] = (df["Close"] > df["High"].rolling(20).max().shift(1)).astype(float) - (df["Close"] < df["Low"].rolling(20).min().shift(1)).astype(float)

        # Institutional Intent = Absorption + Liquidity Sweep + OBV Surge
        f["f14_inst_intent"] = (f["f04_absorption"] * 0.3 + f["f07_obv_velocity"].clip(0, 1) * 0.3 + f["f20_liquidity_sweep"] * 0.4).clip(0, 1)

        # Advanced Wyckoff Pro Features
        # 1. Effort vs Result: High volume (effort) but price didn't drop much (result) -> Bullish
        f["f_effort_vs_result"] = ((df["Volume"] / vol_ma20) / ((rng / spread_ma20).replace(0, 1e-5))).clip(0, 5)
        
        # 2. Stopping Volume: Down day, huge volume, close in upper half of bar
        f["f_stopping_volume"] = ((close_diff < 0) & (df["Volume"] > vol_ma20 * 1.5) & (df["Close"] > df["Low"] + rng * 0.6)).astype(float)
        
        # 3. Re-accumulation Footprint: Price holding above 50SMA, volume drying up on down days
        sma50 = df["Close"].rolling(50).mean()
        f["f_reaccumulation"] = ((df["Close"] > sma50) & (close_diff < 0) & (df["Volume"] < vol_ma20 * 0.8)).astype(float).rolling(5).sum() / 5.0
        
        # 4. Relative Strength vs SPY (True Alpha)
        if "spy_close" in df.columns:
            f["f_rs_spy"] = (df["Close"].pct_change(20) - df["spy_close"].pct_change(20)).fillna(0)
        else:
            f["f_rs_spy"] = 0.0

        return f.fillna(0)

    def composite_cis(self, factors: pd.DataFrame, df: pd.DataFrame = None) -> pd.Series:
        base_weights = {
            "f04_absorption": 4,
            "f07_obv_velocity": 4,
            "f14_inst_intent": 6,
            "f20_liquidity_sweep": 5,
            "f26_accept_reject": 3,
            "f35_struct_break": 3,
            "f_effort_vs_result": 4,
            "f_stopping_volume": 4,
            "f_reaccumulation": 3,
            "f_rs_spy": 4
        }

        dynamic_weights = {f: pd.Series(base_weights.get(f, 0), index=factors.index) for f in factors.columns if f in base_weights}
        total_w = sum(dynamic_weights.values())

        score = pd.Series(0.0, index=factors.index)
        for col in dynamic_weights:
            score += factors[col].clip(-2, 2) * dynamic_weights[col]

        # Normalize to 0-100
        norm_score = (score / total_w.replace(0, np.nan).fillna(1) * 100 + 50).clip(0, 100).round(1)
        
        # Boost based on Wyckoff specific score
        if "f36_wyckoff_score" in factors.columns:
            boost = factors["f36_wyckoff_score"] * 18 # Increased institutional weight
            norm_score = (norm_score + boost).clip(0, 100)
            
        return norm_score

    def get_wyckoff_phase(self, df: pd.DataFrame) -> pd.Series:
        phases = pd.Series("לא בתהליך איסוף", index=df.index)
        if len(df) < 60:
            return phases

        close = df['Close']
        vol = df['Volume']
        sma20 = close.rolling(20).mean()
        sma50 = close.rolling(50).mean()
        sma200 = close.rolling(200).mean()
        
        vol_ma = vol.rolling(20).mean()
        high60 = df['High'].rolling(60).max()
        low60 = df['Low'].rolling(60).min()
        atr = (df['High'] - df['Low']).rolling(14).mean()

        # State machine for institutional phase detection
        for i in range(60, len(df)):
            c = close.iloc[i]
            v = vol.iloc[i]
            v_ma = vol_ma.iloc[i]
            h60 = high60.iloc[i-1]
            l60 = low60.iloc[i-1]
            a = atr.iloc[i]
            
            s20 = sma20.iloc[i]
            s50 = sma50.iloc[i]
            s200 = sma200.iloc[i] if not pd.isna(sma200.iloc[i]) else s50
            
            prev_phase = phases.iloc[i-1]

            # Phase E: Markup (Strong trend)
            if c > s20 and s20 > s50 and s50 > s200 and c >= h60 * 0.95:
                phases.iloc[i] = "Phase E (Markup)"
            # Re-accumulation (Pause in Markup)
            elif "Markup" in prev_phase and c > s200 and c < h60 * 0.95 and v < v_ma:
                phases.iloc[i] = "Re-accumulation (LPS/BUEC)"
            # Phase D: SOS (Sign of Strength) / Breakout from TR
            elif c > s50 and v > v_ma * 1.5 and c >= h60 * 0.90 and c > df['Open'].iloc[i]:
                phases.iloc[i] = "Phase D (SOS / Breakout)"
            # Phase C: Spring / Shakeout (Liquidity sweep below TR)
            elif df['Low'].iloc[i] < l60 + a and c > df['Open'].iloc[i] and c < s50:
                phases.iloc[i] = "Phase C (Spring / Liquidity Sweep)"
            # LPS (Last Point of Support in TR)
            elif "Spring" in prev_phase or "Accumulation" in prev_phase:
                if c > l60 + a * 2 and c < s50 and v < v_ma * 0.8:
                    phases.iloc[i] = "Phase D (LPS)"
                elif c < s50:
                    phases.iloc[i] = "Phase B (Accumulation)"
                else:
                    phases.iloc[i] = prev_phase
            # Phase A: Selling Climax
            elif c < l60 * 1.05 and v > v_ma * 2.5 and df['Close'].iloc[i] > df['Low'].iloc[i] + (df['High'].iloc[i] - df['Low'].iloc[i]) * 0.5:
                phases.iloc[i] = "Phase A (Selling Climax)"
            # Markdown / Distribution
            elif c < s20 and s20 < s50 and c < s200:
                phases.iloc[i] = "Markdown (Institutional Distribution)"
            elif c < s50 and v > v_ma * 2.0 and c < df['Open'].iloc[i]:
                phases.iloc[i] = "Distribution (Heavy Supply)"
            else:
                # Carry forward previous state if no clear signal
                phases.iloc[i] = phases.iloc[i-1] 
                
        return phases


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
        return None, pd.DataFrame()

    cfg_period = period if period else f"{start}/{end}"
    engine = FactorEngine(
        BacktestConfig(
            period=cfg_period,
            stop_loss_pct=stop_loss_pct,
            atr_multiplier=atr_multiplier,
        )
    )
    factors = engine.compute(df)
    df['wyckoff_phase'] = engine.get_wyckoff_phase(df)
    df['cis_score'] = engine.composite_cis(factors, df)
    df['Daily_Return'] = df['Close'].pct_change().fillna(0)

    # Simple AI injection
    if use_ai and st is not None and getattr(st, "session_state", None) and getattr(st.session_state, "ml_model", None) is not None:
        try:
            model = st.session_state.ml_model
            expected_features = getattr(model, "feature_names_in_", None)
            X_pred = factors.copy()
            if expected_features is not None:
                for c in expected_features:
                    if c not in X_pred.columns:
                        X_pred[c] = 0
                X_pred = X_pred[expected_features]
            probs = model.predict_proba(X_pred)[:, 1]
            df['cis_score'] = probs * 100
        except Exception:
            pass

    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift(1)).abs()
    low_close = (df['Low'] - df['Close'].shift(1)).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr_series = true_range.rolling(14).mean()

    positions = []
    audit_logs = []
    in_position = False
    entry_price = 0
    entry_phase = ""
    entry_date = None
    peak_price = 0
    cis_at_entry = 0
    stop_loss_level = 0

    for i in range(len(df)):
        current_phase = df['wyckoff_phase'].iloc[i]
        current_cis = df['cis_score'].iloc[i]
        phase_allowed = check_phase_entry_allowed(current_phase, risk_profile)
        score_allowed = current_cis >= threshold

        if not in_position:
            if phase_allowed and score_allowed:
                positions.append(1)
                in_position = True
                entry_price = df['Close'].iloc[i]
                entry_phase = current_phase
                entry_date = df.index[i]
                peak_price = entry_price
                cis_at_entry = current_cis
                atr_val = atr_series.iloc[i] if not pd.isna(atr_series.iloc[i]) else 0
                if atr_val > 0:
                    stop_loss_level = min(
                        entry_price * (1 - stop_loss_pct),
                        entry_price - atr_val * atr_multiplier,
                    )
                else:
                    stop_loss_level = entry_price * (1 - stop_loss_pct)
            else:
                positions.append(0)
        else:
            if df['Low'].iloc[i] <= stop_loss_level:
                positions.append(0)
                exit_px = stop_loss_level
                ret = (exit_px - entry_price) / entry_price
                audit_logs.append({
                    "entry_date": entry_date.strftime("%Y-%m-%d"),
                    "exit_date": df.index[i].strftime("%Y-%m-%d"),
                    "phase_at_entry": entry_phase,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(exit_px, 2),
                    "return_pct": round(ret * 100, 2),
                    "win": ret > 0,
                    "exit_type": "Stop_Loss",
                    "phase_at_exit": current_phase,
                    "cis_at_entry": cis_at_entry,
                })
                in_position = False
                continue

            if "Markdown" in current_phase or "Distribution" in current_phase or current_cis < threshold - 15:
                positions.append(0)
                exit_px = df['Close'].iloc[i]
                ret = (exit_px - entry_price) / entry_price
                audit_logs.append({
                    "entry_date": entry_date.strftime("%Y-%m-%d"),
                    "exit_date": df.index[i].strftime("%Y-%m-%d"),
                    "phase_at_entry": entry_phase,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(exit_px, 2),
                    "return_pct": round(ret * 100, 2),
                    "win": ret > 0,
                    "exit_type": "Phase_Change",
                    "phase_at_exit": current_phase,
                    "cis_at_entry": cis_at_entry,
                })
                in_position = False
            else:
                positions.append(1)
                if df['Close'].iloc[i] > peak_price:
                    peak_price = df['Close'].iloc[i]

    positions = positions[:len(df)]
    while len(positions) < len(df):
        positions.append(0)

    df['Position'] = pd.Series(positions, index=df.index).shift(1).fillna(0)
    df['Strategy_Return'] = df['Position'] * df['Daily_Return']
    df['Cum_Strategy'] = (1 + df['Strategy_Return']).cumprod() - 1
    df['Cum_Baseline'] = (1 + df['Daily_Return']).cumprod() - 1

    return df, pd.DataFrame(audit_logs)


def explain_score(df: pd.DataFrame, current_phase: str, cis_score: float) -> str:
    """
    Institutional-grade analysis breakdown. Direct, blunt, no fluff.
    """
    if df is None or df.empty:
        return "אין מספיק נתונים לאנליזה מוסדית. נדרשים נתונים היסטוריים נוספים."

    close = df['Close'].iloc[-1]
    vol = df['Volume'].iloc[-1]
    vol_ma20 = df['Volume'].rolling(20).mean().iloc[-1] if len(df) >= 20 else 1.0
    vol_ratio = vol / vol_ma20 if vol_ma20 > 0 else 1.0
    
    delta = df['Close'].diff()
    obv = (np.sign(delta) * df['Volume']).cumsum()
    obv_diff = obv.diff(10).iloc[-1] if len(obv) >= 10 else 0
    
    rng = df['High'].iloc[-1] - df['Low'].iloc[-1]
    spread_ma = (df['High'] - df['Low']).rolling(20).mean().iloc[-1]
    effort_result = (vol / (rng + 1e-5)) / (vol_ma20 / (spread_ma + 1e-5)) if spread_ma > 0 else 1.0
    
    sma20 = df['Close'].rolling(20).mean().iloc[-1] if len(df) >= 20 else close
    sma50 = df['Close'].rolling(50).mean().iloc[-1] if len(df) >= 50 else sma20
    sma200 = df['Close'].rolling(200).mean().iloc[-1] if len(df) >= 200 else sma50
    
    rs_spy = (df["Close"].pct_change(20).iloc[-1] - df.get("spy_close", df["Close"]).pct_change(20).iloc[-1]) if "spy_close" in df.columns else 0.0
    
    high60 = df['High'].rolling(60).max().shift(1).iloc[-1] if len(df) >= 60 else close
    low60 = df['Low'].rolling(60).min().shift(1).iloc[-1] if len(df) >= 60 else df['Low'].iloc[-1]
    breakout = close > high60 * 0.98
    spring_cond = df['Low'].iloc[-1] < low60 and close > df['Open'].iloc[-1]
    
    pros = []
    cons = []

    if effort_result > 1.8 and close > df['Open'].iloc[-1]:
        pros.append("✓ **ספיגת היצע (Absorption / Effort vs Result)**: מחזור מסחר גבוה מאוד שמייצר תנועת מחיר מינימלית כלפי מטה. הכסף החכם קונה לתוך ההיצע. טביעת אצבע מוסדית קלאסית.")
    elif vol_ratio >= 1.5 and close > df['Open'].iloc[-1]:
        pros.append("✓ **איסוף מוסדי אגרסיבי**: המחזור גבוה ב-50%+ מהממוצע ביום עליות. הקונים מנקים את ההיצע באופן אקטיבי.")
    elif vol_ratio < 0.7:
        cons.append("• **יובש נזילות (Liquidity Desert)**: מסחר של כסף קטן (Retail) בלבד. אין נוכחות מוסדית משמעותית כרגע.")
        
    if spring_cond:
        pros.append("✓ **ציד נזילות (Spring / Shakeout)**: המחיר שבר את התמיכה כדי להפעיל פקודות Stop-Loss, ואז דחה את השבירה והתאושש. ניעור קלאסי של שלב C.")
        
    if close > sma20 and close > sma50 and sma50 > sma200:
        pros.append("✓ **מבנה מגמה (Pristine Trend)**: המחיר שומר על כל הממוצעים הנעים המרכזיים. דרך ההתנגדות הקלה היא חד משמעית למעלה.")
    elif close < sma200 and close < sma50:
        cons.append("• **היצע כלוא (Supply Overhead)**: המחיר קבור מתחת לממוצעים 50 ו-200. כל ניסיון עליה צפוי להיתקל בלחץ מכירות מוסדי.")
        
    if obv_diff > 0:
        pros.append("✓ **זרימת פקודות חיובית (Order Flow)**: ה-OBV מתרחב. הון נטו זורם לתוך הנכס בעשרת ימי המסחר האחרונים.")
    else:
        cons.append("• **זרימת פקודות שלילית**: ה-OBV שטוח או יורד. ההון מבצע רוטציה החוצה מהנכס.")
        
    if rs_spy > 0.05:
        pros.append("✓ **ייצור אלפא (Relative Strength)**: ביצועי יתר של מעל 5% מול ה-SPY ב-20 הימים האחרונים. מוסדיים רודפים אחרי עוצמה יחסית.")
    elif rs_spy < -0.05:
        cons.append("• **חולשה יחסית**: פיגור משמעותי מול השוק הרחב. עלות האלטרנטיבה (Opportunity Cost) גבוהה מדי.")

    if breakout:
        pros.append("✓ **סימן לעוצמה (SOS)**: המחיר חותך דרך בלוק ההתנגדות של 60 הימים האחרונים. שלב ההמראה (Markup) מתחיל.")

    if cis_score >= 70:
        pros.append(f"✓ **ציון מוסדי גבוה (CIS: {cis_score:.1f})**: המודלים הכמותיים מאשרים הסתברות גבוהה לאיסוף מבני.")
    elif cis_score < 45:
        cons.append(f"• **ציון מוסדי נמוך (CIS: {cis_score:.1f})**: חותם כמותי המעיד על פיזור (Distribution) או 'כסף מת'.")

    if cis_score >= 70:
        opening = "**הערכת אנליסט:** בלי ללכת סביב. אנחנו רואים כאן טביעת אצבע מוסדית ברורה. הכסף החכם מתמקם באופן אקטיבי, והמסחר מראה ספיגה מכוונת של כל היצע זמין."
    elif cis_score >= 55:
        opening = "**הערכת אנליסט:** שלב מעבר. אנו מזהים סממנים ראשוניים של איסוף, אך התזה טרם קיבלה אישור סופי. יש לנהל סיכונים בקפידה ולהמתין ל-SOS (סימן לעוצמה) אגרסיבי או ל-LPS מאושר."
    else:
        opening = "**הערכת אנליסט:** כסף מת או פיזור מוסדי אקטיבי. פרופיל המחזורים חלש ותנועת המחיר לא מראה שום דחיפות מצד הכסף החכם. אל תבזבזו הון על מאבק במגמה הזו."

    phase_explanations = {
        "Phase A": "### שלב A: בלימת המגמה (Selling Climax)\nקפיטולציה של הציבור. מחזור כבד עוצר את הירידות, אבל התנודתיות עדיין רעילה. אל תנסה לתפוס סכין נופלת. תן לטווח המסחר (TR) להיבנות.",
        "Phase B": "### שלב B: איסוף וצבירה (Building the Cause)\nתנועת מחיר משעממת וקופצנית. זה המקום בו המוסדיים בונים פוזיציה בשקט על פני שבועות או חודשים. התנודתיות מתכווצת. חפש סימני ספיגה בחלק התחתון של הטווח.",
        "Phase C": "### שלב C: ציד נזילות (Spring / Liquidity Sweep)\nהמלכודת האולטימטיבית. המוסדיים מהנדסים שבירה מטה כדי לאסוף נזילות ולהפעיל סטופים של הציבור לפני המהלך האמיתי. חזרה מהירה לתוך הטווח היא איתות קנייה בביטחון גבוה.",
        "Phase D": "### שלב D: אישור עוצמה (SOS & LPS)\nהתזה מאושרת. ההיצע הותש. אנו רואים פריצות מעלה במחזורים גבוהים (SOS) ותיקונים רדודים ללא מחזור (LPS). זהו חלון הכניסה האופטימלי.",
        "Phase E": "### שלב E: המראה (Markup)\nהרכבת יצאה מהתחנה. המחיר במגמה אגרסיבית. נהל סיכונים עם סטופ עוקב ותן למומנטום האלגוריתמי לעשות את העבודה.",
        "Re-accumulation": "### איסוף מחדש (Re-accumulation / LPS)\nהפסקה הכרחית במגמת העלייה. הנכס מעכל את העליות ובונה בסיס חדש. חפש התייבשות מוחלטת של המחזורים בימי ירידות.",
        "Markdown": "### שלב ירידות / פיזור (Distribution)\nהמוסדיים פורקים סיכון. השוק כבד. חסל פוזיציות לונג או שקול שורט. שמירת הון (Capital Preservation) היא בעדיפות עליונה כאן."
    }

    phase_text = phase_explanations.get("Phase B", "### מבנה לא מאושר\nממתין לפרמטרים ברורים של Wyckoff.") 
    for k, v in phase_explanations.items():
        if k in current_phase:
            phase_text = v
            break

    if cis_score >= 75:
        confidence = "גבוהה מאוד (High Conviction)"
    elif cis_score >= 60:
        confidence = "בינונית (Moderate)"
    else:
        confidence = "נמוכה / התרחק (Avoid)"
        
    bottom_line = f"""### 💡 שורה תחתונה:
{ "**הנתונים נוטים בבירור לכיוון של איסוף מוסדי.**" if cis_score >= 60 else "**התזה המבנית שבורה או לא מאושרת. עדיף להקצות הון למקומות אחרים.**" }

**רמת ביטחון מערכת:** {confidence}
"""

    pros_text = "\n".join(pros) if pros else "• לא זוהו טביעות אצבע חיוביות."
    cons_text = "\n".join(cons) if cons else "• אין דגלים אדומים מהותיים במבנה."

    md = f"""{opening}

{phase_text}

### ⚖️ ספר הוכחות (Evidence Ledger):

**טביעות אצבע חיוביות (איסוף/המחיר עולה):**
{pros_text}

**טביעות אצבע שליליות (פיזור/חולשה):**
{cons_text}

---
{bottom_line}
"""
    return md

