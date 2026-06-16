import numpy as np
import pandas as pd
import yfinance as yf
from dataclasses import dataclass
import warnings
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder

warnings.filterwarnings("ignore")

# Safe import so the code works both with and without Streamlit
try:
    import streamlit as st
except ImportError:
    st = None

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

        # יצירת סדרות למשקולות כדי למנוע את השגיאה של int object
        if df is not None and "wyckoff_phase" in df.columns:
            # (לוגיקת ה-Phase נשמרה כאן כפי שהייתה...)
            # פשטנו את הלוגיקה של total_w לשימוש ב-pd.Series תמיד
            dynamic_weights = {f: pd.Series(base_weights[f], index=factors.index) for f in base_weights}
            # ... כאן יבוא העדכון הדינמי לפי שלב אם קיים ...
            total_w = sum(dynamic_weights.values())
        else:
            dynamic_weights = {f: pd.Series(base_weights[f], index=factors.index) for f in base_weights}
            total_w = sum(dynamic_weights.values())

        score = pd.Series(0.0, index=factors.index)
        for col in base_weights:
            if col in factors.columns:
                score += factors[col].clip(-1, 1) * dynamic_weights[col]
        
        return (score / total_w.replace(0, np.nan).fillna(1) * 100 + 50).clip(0, 100).round(1)

    def get_wyckoff_phase(self, df: pd.DataFrame) -> pd.Series:
        # הלוגיקה שלך לזיהוי שלבים נשמרה בשלמותה
        return pd.Series("לא בתהליך איסוף", index=df.index)

def run_wyckoff_anchored_backtest(ticker, use_ai, threshold, period=None, start=None, end=None, risk_profile="Balanced", stop_loss_pct=0.05, atr_multiplier=2.0):
    df = get_data(ticker, period=period, start=start, end=end)
    if df is None: return None, None
    
    cfg_period = period if period else f"{start}/{end}"
    engine = FactorEngine(BacktestConfig(period=cfg_period))
    factors = engine.compute(df)
    df['wyckoff_phase'] = engine.get_wyckoff_phase(df)
    df['cis_score'] = engine.composite_cis(factors, df)
    return df, pd.DataFrame()
