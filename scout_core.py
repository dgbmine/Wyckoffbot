import numpy as np
import pandas as pd
import yfinance as yf
from dataclasses import dataclass
import warnings
import streamlit as st
from datetime import datetime
import logging

warnings.filterwarnings("ignore")

# הגדרת לוגר מקומי לדיאגנוסטיקה
logger = logging.getLogger("scout_core")

# ---------- Helper Functions ----------
def clean_filename(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).replace(' ', '_')

def get_data(ticker, period="2y", start=None, end=None):
    try:
        tkr = yf.Ticker(ticker)
        
        # ניסיון ראשון - הגישה המועדפת
        if start is not None and end is not None:
            df = tkr.history(start=start, end=end, auto_adjust=False)
            if df is None or df.empty or len(df) < 40:
                df = tkr.history(start=start, end=end)  # גיבוי לספריות yfinance חדשות
        else:
            df = tkr.history(period=period, auto_adjust=False)
            if df is None or df.empty or len(df) < 40:
                df = tkr.history(period=period)  # גיבוי לספריות yfinance חדשות

        if df is None or df.empty or len(df) < 40:
            return None

        # מנגנון קילוף אזורי זמן בטוח לקריסות TypeError
        def _safe_tz_drop(idx):
            idx = pd.to_datetime(idx)
            if getattr(idx, 'tz', None) is not None:
                return idx.tz_convert(None)
            return idx

        df.index = _safe_tz_drop(df.index)
        
        # ניקוי רשומות כפולות וחסרות לשיפור יציבות הנתונים
        df = df[~df.index.duplicated(keep='first')]
        df.dropna(subset=['Close', 'Volume'], inplace=True)
        df = df.sort_index()

        # הורדת נתוני עזר (SPY ו-VIX)
        if start is not None and end is not None:
            spy_df = yf.Ticker("SPY").history(start=start, end=end, auto_adjust=False)
            if spy_df is None or spy_df.empty:
                spy_df = yf.Ticker("SPY").history(start=start, end=end)
                
            vix_df = yf.Ticker("^VIX").history(start=start, end=end, auto_adjust=False)
            if vix_df is None or vix_df.empty:
                vix_df = yf.Ticker("^VIX").history(start=start, end=end)
        else:
            spy_df = yf.Ticker("SPY").history(period=period, auto_adjust=False)
            if spy_df is None or spy_df.empty:
                spy_df = yf.Ticker("SPY").history(period=period)

            vix_df = yf.Ticker("^VIX").history(period=period, auto_adjust=False)
            if vix_df is None or vix_df.empty:
                vix_df = yf.Ticker("^VIX").history(period=period)

        if spy_df is not None and not spy_df.empty:
            spy_df.index = _safe_tz_drop(spy_df.index)
            spy_df = spy_df[~spy_df.index.duplicated(keep='first')]
            spy_df.dropna(subset=['Close'], inplace=True)
            df = df.join(spy_df[["Close"]].rename(columns={"Close": "spy_close"}), how="left")
            df['spy_close'] = df['spy_close'].ffill()
        else:
            df["spy_close"] = np.nan

        if vix_df is not None and not vix_df.empty:
            vix_df.index = _safe_tz_drop(vix_df.index)
            vix_df = vix_df[~vix_df.index.duplicated(keep='first')]
            vix_df.dropna(subset=['Close'], inplace=True)
            df = df.join(vix_df[["Close"]].rename(columns={"Close": "vix_close"}), how="left")
            df['vix_close'] = df['vix_close'].ffill()
        else:
            df["vix_close"] = np.nan

        return df
    except Exception as e:
        logger.error(f"Error in get_data for {ticker}: {e}")
        return None

def calculate_advanced_metrics(trades: list, initial_capital: float = 100000.0) -> dict:
    if not trades:
        return {
            "max_drawdown": 0.0,
            "total_profit": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "annual_pnl": {},
            "wyckoff_success_rate": 0.0
        }

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
    
    sorted_trades = sorted(trades, key=lambda x: pd.to_datetime(x.get('exit_date', x.get('entry_date'))))
    
    for t in sorted_trades:
        profit = t.get('profit', 0)
        equity += profit
        if equity > peak:
            peak = equity
        drawdown = ((peak - equity) / peak * 100) if peak > 0 else 0.0
        if drawdown > max_drawdown:
            max_drawdown = drawdown
            
        exit_date = pd.to_datetime(t.get('exit_date'))
        year = exit_date.year
        if year not in annual_profit:
            annual_profit[year] = 0.0
        annual_profit[year] += profit

    return {
        "max_drawdown": max_drawdown,
        "total_profit": total_profit,
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "annual_pnl": annual_profit,
        "wyckoff_success_rate": wyckoff_success_rate
    }

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
    if "לא בתהליך" in phase or "Markdown" in phase or "Distribution" in phase or "TRANSITION" in phase or "UNCERTAIN" in phase:
        return False
    if risk_profile == "Aggressive":
        return any(p in phase for p in ["Phase C", "Spring", "Phase D", "Phase E", "LPS", "SOS", "Breakout", "Markup", "Re-accumulation"])
    elif risk_profile == "Balanced":
        return any(p in phase for p in ["Phase C", "Spring", "Phase D", "Phase E", "LPS", "SOS", "Breakout", "Markup", "Re-accumulation"])
    elif risk_profile == "Conservative":
        return any(p in phase for p in ["Phase E", "Markup"])
    return False

# ---------- New Diagnostic Function (Phase Follow-Through) ----------
def calculate_phase_followthrough(df: pd.DataFrame, horizon: int = 20, threshold_pct: float = 0.04) -> dict:
    """
    מודד דיוק זיהוי Wyckoff טהור (Phase Follow-Through). 
    בוחן האם זיהוי פאזה הוביל לתנועת מחיר מצופה בתוך חלון הזמן הנתון (horizon), 
    ללא תלות ב-ATR, Stop-Loss או מדדים כלכליים. 
    מחזיר מילון מפורק לפי פאזות.
    """
    if df is None or df.empty or 'wyckoff_phase' not in df.columns:
        return {}
    
    records = []
    phases = df['wyckoff_phase'].values
    closes = df['Close'].values
    
    bullish_phases = ["Phase C", "Spring", "Phase D", "Re-accumulation", "Phase E (Markup)"]
    bearish_phases = ["Markdown", "Distribution", "Heavy Supply"]
    
    n = len(df)
    for i in range(n - horizon):
        curr_phase = str(phases[i])
        prev_phase = str(phases[i-1]) if i > 0 else ""
        
        # סינון לאיתותים אמיתיים (מעבר פאזה בלבד) למניעת אוטו-קורלציה
        if curr_phase == prev_phase:
            continue
            
        is_bull = any(p in curr_phase for p in bullish_phases)
        is_bear = any(p in curr_phase for p in bearish_phases)
        
        if not is_bull and not is_bear:
            continue
            
        future_closes = closes[i+1 : i+1+horizon]
        
        if is_bull:
            max_price = np.max(future_closes)
            ret = (max_price - closes[i]) / closes[i]
            success = ret >= threshold_pct
        else:
            min_price = np.min(future_closes)
            ret = (closes[i] - min_price) / closes[i] 
            success = ret >= threshold_pct
            
        records.append({
            "Phase": curr_phase,
            "Success": success
        })
    
    if not records:
        return {}
        
    rdf = pd.DataFrame(records)
    stats = {}
    for phase, group in rdf.groupby("Phase"):
        stats[phase] = {
            "total": len(group),
            "success": int(group["Success"].sum()),
            "rate": float(group["Success"].mean() * 100)
        }
    return stats

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
            
            local_min = search_df["Close"].iloc[max(0, i - 20):i].min()
            
            if not has_sc:
                if close < prev_close and vol > vol_ma_i * 2.5 and low <= local_min and close > low + (high - low) * 0.4:
                    has_sc = True
                    sc_idx = i
                    sc_low = low
                    score.loc[idx] = 0.3
            elif has_sc and not has_ar and (i - sc_idx <= 25):
                if close > open_px and close > prev_close and vol > vol_ma_i:
                    has_ar = True
                    ar_high = high
                    score.loc[idx] = 0.4
            elif has_ar and not has_st:
                if vol < search_df["Volume"].iloc[sc_idx] * 0.75 and low <= sc_low * 1.05 and close >= sc_low * 0.98:
                    has_st = True
                    score.loc[idx] = 0.6
            elif has_st:
                if low < sc_low and close > sc_low and vol > vol_ma_i * 1.2: 
                    score.loc[idx] = 0.9 
                    sc_low = low 
                elif low > sc_low and low < search_df["Low"].iloc[i - 1] and vol < vol_ma_i * 0.8 and close > open_px: 
                    score.loc[idx] = 0.85
                elif close > ar_high and vol > vol_ma_i * 1.5 and close - open_px > (high - low) * 0.7: 
                    score.loc[idx] = 1.0
                    has_sc = False 
        return score

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        f = pd.DataFrame(index=df.index)
        rng = df["High"] - df["Low"]
        vol_ma20 = df["Volume"].rolling(20).mean()
        rvol = df["Volume"] / vol_ma20.replace(0, np.nan)
        spread_ma20 = rng.rolling(20).mean()

        close_diff = df["Close"].diff()
        midpoint = (df["High"] + df["Low"]) / 2

        vol_ratio = (df["Volume"] / vol_ma20.replace(0, 1e-5)).clip(0, 5)
        spread_ratio = (rng / spread_ma20.replace(0, 1e-5)).clip(0.1, 5)
        recent_min = df["Low"].rolling(20).min()
        recent_max = df["High"].rolling(20).max()
        price_pos_inv = 1.0 - ((df["Close"] - recent_min) / (recent_max - recent_min + 1e-5)).clip(0, 1)
        f["f04_absorption"] = (vol_ratio / spread_ratio) * price_pos_inv

        f["f36_wyckoff_score"] = self._compute_quick_wyckoff(df)
        
        obv_raw = np.sign(close_diff) * df["Volume"]
        obv_cum = obv_raw.cumsum()
        f["f07_obv_velocity"] = (obv_cum.diff(10) / obv_cum.abs().rolling(10).mean().replace(0, np.nan)).clip(-3, 3)
        
        rolling_low_10 = df["Low"].shift(1).rolling(10).min()
        f["f20_liquidity_sweep"] = ((df["Low"] < rolling_low_10) & (df["Close"] > rolling_low_10)).astype(float)
        
        f["f26_accept_reject"] = ((df["Close"] > midpoint) & (df["Volume"] > vol_ma20)).astype(float).rolling(5).mean() - ((df["Close"] < midpoint) & (df["Volume"] > vol_ma20)).astype(float).rolling(5).mean()
        f["f35_struct_break"] = (df["Close"] > df["High"].rolling(20).max().shift(1)).astype(float) - (df["Close"] < df["Low"].rolling(20).min().shift(1)).astype(float)
        f["f14_inst_intent"] = (f["f04_absorption"] * 0.3 + f["f07_obv_velocity"].clip(0, 1) * 0.3 + f["f20_liquidity_sweep"] * 0.4).clip(0, 1)

        f["f_effort_vs_result"] = ((df["Volume"] / vol_ma20) / ((rng / spread_ma20).replace(0, 1e-5)).replace(np.inf, 5)).clip(0, 5)
        
        vol_std = df["Volume"].rolling(20).std().fillna(0)
        f["f_stopping_volume"] = ((close_diff < 0) & (df["Volume"] > (vol_ma20 + vol_std)) & (df["Close"] > df["Low"] + rng * 0.5)).astype(float)
        
        sma50 = df["Close"].rolling(50).mean()
        f["f_reaccumulation"] = ((df["Close"] > sma50) & (close_diff < 0) & (df["Volume"] < vol_ma20 * 0.8)).astype(float).rolling(5).sum() / 5.0
        
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

        norm_score = (score / total_w.replace(0, np.nan).fillna(1) * 100 + 50).clip(0, 100).round(1)
        
        if "f36_wyckoff_score" in factors.columns:
            boost = factors["f36_wyckoff_score"] * 5 
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

        close_diff = close.diff()
        obv = (np.sign(close_diff) * vol).cumsum()
        obv_diff = obv.diff(10)
        obv_min60 = obv.rolling(60).min()
        
        if "spy_close" in df.columns:
            rs_spy = (close.pct_change(20) - df["spy_close"].pct_change(20)).fillna(0)
        else:
            rs_spy = pd.Series(0.0, index=df.index)

        streak = 0
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
            
            o_diff = obv_diff.iloc[i]
            rs = rs_spy.iloc[i]
            
            prev_phase = phases.iloc[i-1]

            if c > s20 and s20 > s50 and s50 > s200 and c >= h60 * 0.95:
                if o_diff > 0 and rs > 0:
                    phases.iloc[i] = "Phase E (Markup)"
                else:
                    phases.iloc[i] = "TRANSITION / UNCERTAIN STATE"
            elif "Markup" in prev_phase and c > s200 and c < h60 * 0.95 and v < v_ma:
                if o_diff >= 0:
                    phases.iloc[i] = "Re-accumulation (LPS/BUEC)"
                else:
                    phases.iloc[i] = "TRANSITION / UNCERTAIN STATE"
            elif c > s50 and v > v_ma * 1.5 and c >= h60 * 0.90 and c > df['Open'].iloc[i]:
                if o_diff > 0:
                    phases.iloc[i] = "Phase D (SOS / Breakout)"
                else:
                    phases.iloc[i] = "TRANSITION / UNCERTAIN STATE"
            elif df['Low'].iloc[i] < l60 + a and c < s50:
                # הבחנה ברורה ומשופרת בין Spring חזק, Spring רגיל ל-False Sweep על בסיס דחיית המחיר
                obv_min_prev = obv_min60.iloc[i-1] if i > 0 and not pd.isna(obv_min60.iloc[i-1]) else obv.iloc[i]
                
                is_new_low = df['Low'].iloc[i] < l60
                positive_close = c > df['Open'].iloc[i]
                # דרישה ל"דחייה" - סגירה בחצי העליון של הנר מעידה על קונים אגרסיביים
                strong_rejection = c > df['Low'].iloc[i] + (df['High'].iloc[i] - df['Low'].iloc[i]) * 0.5
                high_volume = v > v_ma * 1.5
                obv_holds = obv.iloc[i] >= obv_min_prev

                if is_new_low and high_volume and strong_rejection and obv_holds:
                    phases.iloc[i] = "Phase C (Strong Spring)"
                elif is_new_low and (c < df['Low'].iloc[i] + (df['High'].iloc[i] - df['Low'].iloc[i]) * 0.3 or not obv_holds):
                    phases.iloc[i] = "Failed Sweep / Warning" 
                elif positive_close and v > v_ma * 1.2:
                    phases.iloc[i] = "Phase C (Spring / Liquidity Sweep)"
                else:
                    phases.iloc[i] = "TRANSITION / UNCERTAIN STATE"
            elif "Spring" in prev_phase or "Accumulation" in prev_phase or "Phase C" in prev_phase:
                if c > l60 + a * 2 and c < s50 and v < v_ma * 0.8:
                    if o_diff >= 0 and df['Low'].iloc[i] >= df['Low'].iloc[i-1]:
                        phases.iloc[i] = "Phase D (LPS)"
                    else:
                        phases.iloc[i] = "TRANSITION / UNCERTAIN STATE"
                elif c < s50:
                    phases.iloc[i] = "Phase B (Accumulation)"
                else:
                    phases.iloc[i] = "TRANSITION / UNCERTAIN STATE"
            elif c < l60 * 1.05 and v > v_ma * 2.5 and df['Close'].iloc[i] > df['Low'].iloc[i] + (df['High'].iloc[i] - df['Low'].iloc[i]) * 0.5:
                phases.iloc[i] = "Phase A (Selling Climax)"
            elif c < s20 and s20 < s50 and c < s200:
                if o_diff < 0:
                    phases.iloc[i] = "Markdown (Institutional Distribution)"
                else:
                    phases.iloc[i] = "TRANSITION / UNCERTAIN STATE"
            elif c < s50 and v > v_ma * 2.0 and c < df['Open'].iloc[i]:
                phases.iloc[i] = "Distribution (Heavy Supply)"
            else:
                if prev_phase not in ["TRANSITION / UNCERTAIN STATE", "לא בתהליך איסוף"]:
                    phases.iloc[i] = prev_phase 
                else:
                    phases.iloc[i] = "TRANSITION / UNCERTAIN STATE"
            
            if phases.iloc[i] == prev_phase and phases.iloc[i] not in ["TRANSITION / UNCERTAIN STATE", "לא בתהליך איסוף"]:
                streak += 1
                if streak == 100:
                    logger.warning(f"Suspicious Phase Chain Detected: '{phases.iloc[i]}' persisted for {streak} consecutive trading days.")
            else:
                streak = 0
                
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
    
    df['rs_spy_factor'] = factors['f_rs_spy'] if 'f_rs_spy' in factors.columns else 0.0

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
    entry_atr = 0
    entry_phase = ""
    entry_date = None
    entry_index_int = 0
    peak_price = 0
    cis_at_entry = 0
    stop_loss_level = 0
    position_size = 10000.0  

    for i in range(len(df)):
        current_phase = df['wyckoff_phase'].iloc[i]
        current_cis = df['cis_score'].iloc[i]
        
        phase_allowed = check_phase_entry_allowed(current_phase, risk_profile)
        score_allowed = (current_cis >= threshold) and (df['rs_spy_factor'].iloc[i] > -0.02)

        if not in_position:
            if phase_allowed and score_allowed:
                positions.append(1)
                in_position = True
                entry_price = df['Close'].iloc[i]
                entry_phase = current_phase
                entry_date = df.index[i]
                entry_index_int = i
                peak_price = entry_price
                cis_at_entry = current_cis
                entry_atr = atr_series.iloc[i] if not pd.isna(atr_series.iloc[i]) else 0
                
                if entry_atr > 0:
                    stop_loss_level = min(
                        entry_price * (1 - stop_loss_pct),
                        entry_price - entry_atr * atr_multiplier,
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
                profit_dollars = position_size * ret
                
                target_ret = (entry_atr / entry_price) * 1.2 if entry_atr > 0 else 0.02
                is_win = bool(ret > target_ret)
                
                horizon = 20
                phase_success = False
                if entry_index_int + 1 < len(df):
                    end_idx = min(entry_index_int + 1 + horizon, len(df))
                    future_closes = df['Close'].iloc[entry_index_int + 1 : end_idx]
                    is_bull = any(p in entry_phase for p in ["Phase C", "Spring", "Phase D", "Re-accumulation", "Phase E", "Markup", "SOS", "LPS"])
                    is_bear = any(p in entry_phase for p in ["Markdown", "Distribution", "Heavy Supply"])
                    if is_bull:
                        phase_success = bool(((future_closes.max() - entry_price) / entry_price) >= 0.04)
                    elif is_bear:
                        phase_success = bool(((entry_price - future_closes.min()) / entry_price) >= 0.04)

                audit_logs.append({
                    "entry_date": entry_date.strftime("%Y-%m-%d"),
                    "exit_date": df.index[i].strftime("%Y-%m-%d"),
                    "phase_at_entry": entry_phase,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(exit_px, 2),
                    "return_pct": round(ret * 100, 2),
                    "profit": round(profit_dollars, 2),
                    "win": is_win,
                    "is_win": is_win,
                    "phase_success": phase_success,
                    "wyckoff_confirmed": True, 
                    "exit_type": "Stop_Loss",
                    "phase_at_exit": current_phase,
                    "cis_at_entry": cis_at_entry,
                })
                in_position = False
                continue

            if "Markdown" in current_phase or "Distribution" in current_phase or current_cis < threshold - 20:
                positions.append(0)
                exit_px = df['Close'].iloc[i]
                ret = (exit_px - entry_price) / entry_price
                profit_dollars = position_size * ret
                
                target_ret = (entry_atr / entry_price) * 1.2 if entry_atr > 0 else 0.02
                is_win = bool(ret > target_ret)
                
                horizon = 20
                phase_success = False
                if entry_index_int + 1 < len(df):
                    end_idx = min(entry_index_int + 1 + horizon, len(df))
                    future_closes = df['Close'].iloc[entry_index_int + 1 : end_idx]
                    is_bull = any(p in entry_phase for p in ["Phase C", "Spring", "Phase D", "Re-accumulation", "Phase E", "Markup", "SOS", "LPS"])
                    is_bear = any(p in entry_phase for p in ["Markdown", "Distribution", "Heavy Supply"])
                    if is_bull:
                        phase_success = bool(((future_closes.max() - entry_price) / entry_price) >= 0.04)
                    elif is_bear:
                        phase_success = bool(((entry_price - future_closes.min()) / entry_price) >= 0.04)

                audit_logs.append({
                    "entry_date": entry_date.strftime("%Y-%m-%d"),
                    "exit_date": df.index[i].strftime("%Y-%m-%d"),
                    "phase_at_entry": entry_phase,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(exit_px, 2),
                    "return_pct": round(ret * 100, 2),
                    "profit": round(profit_dollars, 2),
                    "win": is_win,
                    "is_win": is_win,
                    "phase_success": phase_success, 
                    "wyckoff_confirmed": True, 
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


def explain_score_simple(df: pd.DataFrame, current_phase: str, cis_score: float, allowed: bool) -> str:
    """
    פונקציית הסבר מפושטת למשתמש הדיוט. מתרגמת מונחים פיננסיים לעברית יומיומית.
    """
    if df is None or df.empty:
        return "אין לנו כרגע מספיק נתונים כדי להפיק הסבר פשוט על הנכס הזה."

    close = df['Close'].iloc[-1]
    vol = df['Volume'].iloc[-1]
    vol_ma20 = df['Volume'].rolling(20).mean().iloc[-1] if len(df) >= 20 else 1.0
    
    sma20 = df['Close'].rolling(20).mean().iloc[-1] if len(df) >= 20 else close
    sma50 = df['Close'].rolling(50).mean().iloc[-1] if len(df) >= 50 else sma20
    sma200 = df['Close'].rolling(200).mean().iloc[-1] if len(df) >= 200 else sma50
    
    rs_spy = 0.0
    if "spy_close" in df.columns:
        rs_spy = (df["Close"].pct_change(20).iloc[-1] - df["spy_close"].pct_change(20).iloc[-1])
    
    text = []
    
    # מה קורה למחיר
    text.append(f"**📈 מה קורה למחיר?**")
    if close > sma20 and sma20 > sma50 and sma50 > sma200:
        text.append("המניה נמצאת כרגע במגמת עלייה חזקה ובריאה. המחיר שומר על יציבות מעל כל הממוצעים החשובים.")
    elif close > sma20 and sma20 > sma50:
        text.append("המניה נמצאת במגמת עלייה טובה בטווח הקצר-בינוני, ומתאוששת.")
    elif close < sma20 and sma20 < sma50:
        text.append("המניה חלשה ונמצאת במגמת ירידה. כרגע קשה לה לטפס למעלה כי יש הרבה מוכרים.")
    else:
        text.append("המניה מדשדשת (הולכת הצידה) - היא לא עולה ולא יורדת בצורה מובהקת, אלא 'אוספת כוח' או 'מפזרת סחורה'.")
        
    text.append("")
    
    # מה קורה לקונים
    text.append(f"**👥 מה קורה להתעניינות הקונים (נפח מסחר)?**")
    if vol > vol_ma20 * 1.2:
        text.append("יש היום התעניינות גבוהה מהרגיל במניה! הרבה קניות או מכירות מתבצעות, מה שמרמז שכסף גדול (משקיעים מוסדיים) מעורב כאן.")
    elif vol < vol_ma20 * 0.8:
        text.append("די שקט היום במניה הזו. אין הרבה קונים או מוכרים פעילים כרגע, מה שמראה שאין 'כסף חכם' שדוחף אותה כרגע לשום כיוון.")
    else:
        text.append("כמות הקניות והמכירות כרגע ממוצעת ורגילה לחלוטין.")
        
    text.append("")
        
    # כוח מול השוק
    text.append(f"**💪 איך היא מתנהגת לעומת השוק הכללי (הבורסה)?**")
    if rs_spy > 0.02:
        text.append("המניה הזו חזקה מהשוק! גם כשקשה מסביב, המשקיעים בוחרים לשים את הכסף שלהם דווקא כאן.")
    elif rs_spy < -0.02:
        text.append("המניה חלשה יותר מהשוק הכללי. נראה שמשקיעים מעדיפים לשים את הכסף שלהם במקומות אחרים עכשיו.")
    else:
        text.append("המניה מתנהגת בערך כמו רוב השוק, בלי להראות יתרון או חסרון מיוחד.")
        
    return "\n".join(text)


def explain_score(df: pd.DataFrame, current_phase: str, cis_score: float) -> str:
    """
    פונקציית ההסבר המקצועית המקורית (Evidence Ledger). משמשת את Backtest ו-Scanner.
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
    
    low60 = df['Low'].rolling(60).min().shift(1).iloc[-1] if len(df) >= 60 else df['Low'].iloc[-1]
    spring_cond = df['Low'].iloc[-1] < low60 and close > df['Open'].iloc[-1]
    
    pos_factors = []
    neg_factors = []
    neutral_mixed = []

    if close > sma20 and sma20 > sma50 and sma50 > sma200:
        pos_factors.append("Price Structure: מבנה שוורי מלא (Close > 20 > 50 > 200)")
        trend_text = "תמיכה מלאה במגמת עלייה מוסדית."
    elif close < sma20 and sma20 < sma50 and sma50 < sma200:
        neg_factors.append("Price Structure: מבנה דובי מלא (Close < 20 < 50 < 200)")
        trend_text = "היצע כלוא (Supply Overhead) ומגמת ירידה."
    else:
        neutral_mixed.append("Price Structure: ממוצעים מעורבים או דשדוש")
        trend_text = "דשדוש מבני ללא כיוון מובהק."

    if obv_diff > 0 and vol_ratio >= 1.2 and close > df['Open'].iloc[-1]:
        pos_factors.append(f"Volume/OBV: התרחבות חיובית וכניסת הון מתמשכת (Vol Ratio: {vol_ratio:.1f}x)")
        obv_text = "חיובית (הון נטו זורם פנימה בעשרת הימים האחרונים)."
    elif obv_diff < 0 and vol_ratio >= 1.2 and close < df['Open'].iloc[-1]:
        neg_factors.append(f"Volume/OBV: לחץ מכירות ויציאת הון מוסדית (Vol Ratio: {vol_ratio:.1f}x)")
        obv_text = "שלילית (הון נטו זורם החוצה מהנכס)."
    else:
        neutral_mixed.append("Volume/OBV: זרימת הון שטוחה או נפח שאינו תומך באופן מובהק")
        obv_text = "ניטרלית או ללא אישור נפח חזק."

    if rs_spy > 0.02:
        pos_factors.append(f"Momentum: עוצמה יחסית חיובית משמעותית ({rs_spy:.2%} מול השוק)")
        mom_text = "מייצר אלפא מובהקת, המוסדיים רודפים אחרי הנכס."
    elif rs_spy < -0.02:
        neg_factors.append(f"Momentum: חולשה יחסית משמעותית ({rs_spy:.2%} מול השוק)")
        mom_text = "מפגר משמעותית מול השוק, עלות אלטרנטיבה גבוהה."
    else:
        neutral_mixed.append("Momentum: עוצמה יחסית שולית או שטוחה ביחס לשוק")
        mom_text = "מייצר תשואה דומה למדד הרחב ללא יתרון תחרותי."

    if effort_result > 1.8 and close > df['Open'].iloc[-1]:
        pos_factors.append("Liquidity/Absorption: מאמץ גבוה מול תוצאה נמוכה כלפי מטה (ספיגת היצע אקטיבית)")
    if spring_cond and vol_ratio > 1.2:
        pos_factors.append("False Breakouts/Traps: ניעור נזילות (Spring) אושר במחזור גבוה מחוץ לטווח המסחר")
    if vol_ratio < 0.7:
        neg_factors.append("Liquidity Behavior: יובש נזילות מוחלט, היעדר נוכחות של כסף חכם")

    is_bullish = len(pos_factors) >= 3 and len(neg_factors) == 0
    is_bearish = len(neg_factors) >= 3 and len(pos_factors) == 0

    if is_bullish:
        dominant_driver = "ACCUMULATION / MARKUP: קונצנזוס חיובי של כניסת הון ועוצמה מבנית."
        logic_text = "קיימת התאמה מלאה בין המחיר, הנפח (OBV) והמומנטום. הנתונים מאשרים נוכחות אקטיבית של כסף חכם הסופג היצע ודוחף כלפי מעלה. הוסר חשש מסתירות."
    elif is_bearish:
        dominant_driver = "DISTRIBUTION / MARKDOWN: קונצנזוס שלילי, לחץ מכירות קשיח."
        logic_text = "קטגוריות הליבה מצביעות מטה פה אחד. מוסדיים מבצעים פיזור סחורה ללא התנגדות. הוסר חשש מסתירות."
        if current_phase not in ["Markdown (Institutional Distribution)", "Distribution (Heavy Supply)", "לא בתהליך איסוף"]:
             current_phase = "TRANSITION / UNCERTAIN STATE"
    else:
        dominant_driver = "TRANSITION: חוסר עקביות או סתירה מהותית בין הפקטורים."
        current_phase = "TRANSITION / UNCERTAIN STATE"
        logic_text = "המערכת מזהה נתונים מעורבים (למשל, מבנה מחיר חיובי מול OBV שלילי). עקב כללי הסתירה הלוגית המחמירים של SCOUT, הנרטיב נפסל עד ליצירת קונצנזוס בין הון למחיר. המצב הנוכחי מוגדר כמעבר בלבד."

    md = f"""### ⚖️ Evidence Ledger

**Positive Factors:**
{chr(10).join(['- ' + f for f in pos_factors]) if pos_factors else '- אין עדות חיובית מוצקה'}

**Negative Factors:**
{chr(10).join(['- ' + f for f in neg_factors]) if neg_factors else '- אין עדות שלילית מוצקה'}

**Neutral / Mixed:**
{chr(10).join(['- ' + f for f in neutral_mixed]) if neutral_mixed else '- אין'}

**Dominant Driver:**
{dominant_driver}

---
### 1. פירוט פאקטורים אמיתי (Raw Data)
* **Price Structure (מבנה מחיר)**: סגירת נר אחרונה ב-{close:.2f}. {trend_text}
* **Volume / OBV (זרימת הון)**: המחזור עומד על פי {vol_ratio:.2f} ממוצע 20 יום. זרימת ה-OBV ל-10 ימים היא {obv_text}
* **Momentum (עוצמה יחסית)**: ה-RS למול ה-SPY ב-20 הימים האחרונים עומד על {rs_spy:.2%}. {mom_text}

### 2. לוגיקה מפורשת (Decision Gate)
{logic_text}
"""
    return md
