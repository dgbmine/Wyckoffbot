"""
============================================================
SCOUT CORE – Wyckoff Institutional Analysis Engine
Strict evidence‑based phase detection. No narrative without
support from at least 2 non‑contradicting factors.
============================================================
"""

from __future__ import annotations
import numpy as np
import pandas as pd
import yfinance as yf
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
import warnings

warnings.filterwarnings("ignore")

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
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
        # Add SPY & VIX
        spy_params = {}
        if start and end:
            spy_params = {"start": start, "end": end}
        else:
            spy_params = {"period": period}
        spy_df = yf.Ticker("SPY").history(**spy_params, auto_adjust=False)
        vix_df = yf.Ticker("^VIX").history(**spy_params, auto_adjust=False)
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
        mask = probs >= th
        trades_count = mask.sum()
        if trades_count >= max(3, len(y) * 0.05):
            win_rate = y[mask].mean()
            score = win_rate * (1 + np.log1p(trades_count) / 10)
            if score > best_score:
                best_score = score
                best_thresh = th
    return best_thresh

def check_phase_entry_allowed(phase, risk_profile):
    if "TRANSITION" in phase or "Markdown" in phase or "Distribution" in phase:
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

# ------------------------------------------------------------
# Factor Engine (reduced noise, pure institutional factors)
# ------------------------------------------------------------
class FactorEngine:
    def __init__(self, cfg: BacktestConfig):
        self.cfg = cfg

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute the essential 10 factors used by the Wyckoff Analyst."""
        f = pd.DataFrame(index=df.index)
        rng = df["High"] - df["Low"]
        vol_ma20 = df["Volume"].rolling(20).mean()
        spread_ma20 = rng.rolling(20).mean()
        close_diff = df["Close"].diff()

        # 1. Effort vs Result (absorption)
        f["f_effort_vs_result"] = (df["Volume"] / vol_ma20) / (rng / spread_ma20.replace(0, 1e-5))
        # 2. Stopping Volume (down day, huge volume, close in upper half)
        f["f_stopping_volume"] = (
            (close_diff < 0) &
            (df["Volume"] > vol_ma20 * 1.5) &
            (df["Close"] > df["Low"] + rng * 0.6)
        ).astype(float)
        # 3. OBV Velocity (10-day)
        obv_raw = np.sign(close_diff) * df["Volume"]
        obv_cum = obv_raw.cumsum()
        f["f_obv_velocity"] = (obv_cum.diff(10) / obv_cum.abs().rolling(10).mean().replace(0, np.nan)).fillna(0)
        # 4. Structural Break (break above 20-period high or below low)
        high20 = df["High"].rolling(20).max().shift(1)
        low20 = df["Low"].rolling(20).min().shift(1)
        f["f_struct_break"] = ((df["Close"] > high20).astype(int) - (df["Close"] < low20).astype(int))
        # 5. Momentum (close vs 50-day MA)
        ma50 = df["Close"].rolling(50).mean()
        f["f_momentum"] = (df["Close"] - ma50) / ma50
        # 6. Volume Ratio (current vs average)
        f["f_vol_ratio"] = df["Volume"] / vol_ma20
        # 7. Spread compression (Bollinger-like)
        f["f_spread_compression"] = rng / spread_ma20
        # 8. Relative Strength vs SPY (20-day)
        if "spy_close" in df.columns:
            spy_ret = df["spy_close"].pct_change(20)
        else:
            spy_ret = 0
        f["f_rs_spy"] = df["Close"].pct_change(20) - spy_ret
        # 9. Liquidity Sweep (Wyckoff Spring)
        low20_min = df["Low"].rolling(20).min().shift(1)
        f["f_spring"] = (
            (df["Low"] < low20_min) &
            (df["Close"] > df["Open"]) &
            (df["Close"] > low20_min)
        ).astype(float)
        # 10. Wyckoff Accumulation Score (simple numeric)
        f["f_accum_score"] = f["f_stopping_volume"] + f["f_spring"] + (f["f_effort_vs_result"] > 2).astype(float)
        return f.fillna(0)

# ------------------------------------------------------------
# Wyckoff Analyst – The strict decision engine
# ------------------------------------------------------------
class WyckoffAnalyst:
    """
    Determines the current Wyckoff phase based on hard evidence.
    Produces an Evidence Ledger and a CIS (Composite Institutional Score).
    """
    @staticmethod
    def _price_structure(df: pd.DataFrame) -> str:
        """Is price in an uptrend, downtrend, or range?"""
        if len(df) < 50:
            return "uncertain"
        ma20 = df["Close"].rolling(20).mean()
        ma50 = df["Close"].rolling(50).mean()
        last = df.iloc[-1]
        if last["Close"] > ma20.iloc[-1] and ma20.iloc[-1] > ma50.iloc[-1] and last["Close"] > last["Open"]:
            return "bullish"
        elif last["Close"] < ma20.iloc[-1] and ma20.iloc[-1] < ma50.iloc[-1] and last["Close"] < last["Open"]:
            return "bearish"
        else:
            return "neutral"

    @staticmethod
    def _volume_obv(df: pd.DataFrame) -> str:
        """Volume and OBV direction."""
        vol_ma20 = df["Volume"].rolling(20).mean()
        last_vol = df["Volume"].iloc[-1]
        if last_vol > vol_ma20.iloc[-1] * 1.3:
            vol_state = "high"
        elif last_vol < vol_ma20.iloc[-1] * 0.7:
            vol_state = "low"
        else:
            vol_state = "normal"
        obv_raw = np.sign(df["Close"].diff()) * df["Volume"]
        obv_cum = obv_raw.cumsum()
        obv_trend = "up" if obv_cum.iloc[-1] > obv_cum.iloc[-20] else "down"
        return f"{vol_state}_{obv_trend}"

    @staticmethod
    def _momentum(df: pd.DataFrame) -> str:
        """Momentum based on rate of change and ADX-like measure."""
        roc = df["Close"].pct_change(10).iloc[-1]
        if roc > 0.05:
            return "strong_up"
        elif roc < -0.05:
            return "strong_down"
        elif roc > 0:
            return "mild_up"
        else:
            return "mild_down"

    @staticmethod
    def determine_phase(df: pd.DataFrame) -> Tuple[str, float, Dict]:
        """
        Returns (phase_str, cis_score, evidence_ledger).
        If contradictions exist, phase is set to "TRANSITION STATE – CONFLICTING SIGNALS".
        """
        # Compute factors
        engine = FactorEngine(BacktestConfig())
        factors = engine.compute(df)
        latest = factors.iloc[-1]

        # Evidence categories
        positive = []
        negative = []
        neutral = []
        dominant = None

        # 1. Price Structure
        ps = WyckoffAnalyst._price_structure(df)
        if ps == "bullish":
            positive.append("Price Structure bullish (close > MA20 > MA50)")
        elif ps == "bearish":
            negative.append("Price Structure bearish (close < MA20 < MA50)")
        else:
            neutral.append("Price Structure neutral / range‑bound")

        # 2. Volume / OBV
        vo = WyckoffAnalyst._volume_obv(df)
        if "high_up" in vo:
            positive.append("High volume with rising OBV → institutional buying")
        elif "high_down" in vo:
            negative.append("High volume with falling OBV → distribution")
        elif "low_up" in vo:
            neutral.append("Low volume, OBV up → quiet accumulation")
        elif "low_down" in vo:
            neutral.append("Low volume, OBV down → lack of interest")
        else:
            neutral.append("Volume/OBV neutral")

        # 3. Momentum
        mom = WyckoffAnalyst._momentum(df)
        if "strong_up" in mom:
            positive.append("Strong upward momentum (>5% over 10d)")
        elif "strong_down" in mom:
            negative.append("Strong downward momentum (<-5% over 10d)")
        else:
            neutral.append("Momentum mild")

        # Additional factors
        if latest["f_spring"] > 0:
            positive.append("Spring detected (liquidity sweep below support, recovery)")
        else:
            neutral.append("No Spring")

        if latest["f_effort_vs_result"] > 2.5:
            positive.append("Absorption (effort vs result > 2.5)")
        elif latest["f_effort_vs_result"] < 0.5:
            negative.append("No effort (volume high but range wide)")   # actually could be neutral

        if latest["f_rs_spy"] > 0.03:
            positive.append("Relative strength vs SPY > 3% (alpha)")
        elif latest["f_rs_spy"] < -0.03:
            negative.append("Relative weakness vs SPY < -3% (underperformance)")

        # CIS score calculation (simple weighted sum)
        weights = {
            "bullish_ps": 3 if ps == "bullish" else -3 if ps == "bearish" else 0,
            "vol_obv": 2 if "high_up" in vo else -2 if "high_down" in vo else 0,
            "momentum": 2 if "strong_up" in mom else -2 if "strong_down" in mom else 0,
            "spring": 2 if latest["f_spring"] > 0 else 0,
            "effort": 2 if latest["f_effort_vs_result"] > 2.5 else 0,
            "rs": 1 if latest["f_rs_spy"] > 0.03 else -1 if latest["f_rs_spy"] < -0.03 else 0,
        }
        cis = 50 + sum(weights.values()) * 5  # scale so 0-100
        cis = np.clip(cis, 0, 100)

        # Build Evidence Ledger
        evidence = {
            "Positive Factors": positive if positive else ["No clear positive signals"],
            "Negative Factors": negative if negative else ["No clear negative signals"],
            "Neutral / Mixed": neutral,
            "Dominant Driver": None,
        }

        # Determine phase
        # First check contradictions: if both strong bull and bear signals co-exist -> TRANSITION
        if ("Price Structure bullish" in positive and "Strong downward momentum" in negative) or \
           ("Price Structure bearish" in negative and "Strong upward momentum" in positive):
            phase = "TRANSITION STATE – CONFLICTING SIGNALS"
            evidence["Dominant Driver"] = "Contradictory signals (price vs momentum)"
            return phase, cis, evidence

        # If no clear dominant driver can be found, also transition
        # We decide dominant driver based on the most heavily weighted evidence
        if len(positive) >= 3 and "Price Structure bullish" in positive:
            if latest["f_spring"] > 0:
                phase = "Phase C (Spring / Liquidity Sweep)"
            elif latest["f_effort_vs_result"] > 2.5:
                phase = "Phase D (SOS / Absorption)"
            elif ps == "bullish":
                phase = "Phase E (Markup)" if latest["f_rs_spy"] > 0.02 else "Re-accumulation"
            else:
                phase = "Phase B (Accumulation)"
            evidence["Dominant Driver"] = "Bullish price structure + institutional activity"
        elif len(negative) >= 3 and "Price Structure bearish" in negative:
            phase = "Markdown (Institutional Distribution)"
            evidence["Dominant Driver"] = "Bearish price structure + heavy selling"
        elif len(positive) >= 2 and "Absorption" in positive:
            phase = "Phase A (Selling Climax) → Possible transition"
            evidence["Dominant Driver"] = "Absorption / Stopping Volume"
        elif "No clear positive signals" in positive and "No clear negative signals" in negative:
            phase = "TRANSITION STATE – NEUTRAL / LOW CONVICTION"
            evidence["Dominant Driver"] = "No dominant institutional footprint"
        else:
            # Mixed but not contradictory enough -> TRANSITION
            phase = "TRANSITION STATE – CONFLICTING SIGNALS"
            evidence["Dominant Driver"] = "Mixed evidence, no clear bias"

        return phase, cis, evidence

# ------------------------------------------------------------
# Backtest (unchanged logic, now uses WyckoffAnalyst)
# ------------------------------------------------------------
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
    analyst = WyckoffAnalyst()
    # We'll compute phase per bar for backtest (vectorized)
    phases = pd.Series("TRANSITION", index=df.index)
    cis_series = pd.Series(0.0, index=df.index)
    for i in range(60, len(df)):
        window_df = df.iloc[:i+1]
        ph, cis, _ = analyst.determine_phase(window_df)
        phases.iloc[i] = ph
        cis_series.iloc[i] = cis
    df['wyckoff_phase'] = phases
    df['cis_score'] = cis_series
    df['Daily_Return'] = df['Close'].pct_change().fillna(0)

    # Optional AI model
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
    Generate a strict, evidence‑based explanation using the Evidence Ledger.
    No free narrative.
    """
    analyst = WyckoffAnalyst()
    phase, cis, evidence = analyst.determine_phase(df)
    positive = "\n".join(f"- {p}" for p in evidence["Positive Factors"])
    negative = "\n".join(f"- {n}" for n in evidence["Negative Factors"])
    neutral  = "\n".join(f"- {n}" for n in evidence["Neutral / Mixed"])
    dominant = evidence["Dominant Driver"] or "None"

    md = f"""## ⚖️ Evidence Ledger (Wyckoff Strict)

### Positive Factors
{positive}

### Negative Factors
{negative}

### Neutral / Mixed
{neutral}

**Dominant Driver:** {dominant}

**Current Phase:** {phase}  
**Composite Institutional Score (CIS):** {cis:.1f}

---
**Resolution:** {phase if "TRANSITION" not in phase else "No tradeable phase – await clearer evidence."}
"""
    return md
