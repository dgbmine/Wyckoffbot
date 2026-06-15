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
    """
    Download stock data along with SPY and VIX macro data.
    Adds 'spy_close' and 'vix_close' columns to the returned DataFrame.
    """
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


def build_research_ground_truth(bt_df, audit_df, window_days=180):
    if bt_df is None or audit_df is None or audit_df.empty:
        return pd.DataFrame()

    bt_df = bt_df.copy()
    bt_df.index = pd.to_datetime(bt_df.index).tz_localize(None)
    enriched = []

    for _, trade in audit_df.iterrows():
        try:
            entry_ts = pd.Timestamp(trade["entry_date"])
            exit_ts  = pd.Timestamp(trade["exit_date"])
            if entry_ts not in bt_df.index:
                continue

            entry_px = float(trade.get("entry_price", bt_df.loc[entry_ts, "Close"]))
            eval_end = min(entry_ts + pd.Timedelta(days=window_days), bt_df.index.max())
            future   = bt_df.loc[entry_ts:eval_end].copy()
            if future.empty:
                continue

            prior_start = entry_ts - pd.DateOffset(months=6)
            prior       = bt_df.loc[prior_start:entry_ts].copy()
            if prior.empty:
                prior = bt_df.loc[:entry_ts].tail(126).copy()

            future_max_close    = float(future["Close"].max())
            future_min_close    = float(future["Close"].min())
            future_max_return   = round((future_max_close / entry_px - 1) * 100, 2)
            future_max_drawdown = round((future_min_close / entry_px - 1) * 100, 2)

            prior_high    = prior["High"].max() if not prior.empty else np.nan
            prior_vol_ma20 = prior["Volume"].rolling(20).mean().iloc[-1] if len(prior) >= 20 else prior["Volume"].mean()

            breakout_confirmed = False
            days_to_breakout   = None
            if pd.notna(prior_high):
                vol_ma_future = future["Volume"].rolling(20).mean()
                vol_ma_future = vol_ma_future.fillna(future["Volume"].expanding().mean())
                breakout_mask = (
                    (future["High"] > prior_high * 1.01) &
                    (future["Volume"] > vol_ma_future * 1.2)
                )
                if breakout_mask.any():
                    breakout_idx       = breakout_mask[breakout_mask].index[0]
                    breakout_confirmed = True
                    days_to_breakout   = int((pd.Timestamp(breakout_idx) - entry_ts).days)

            markup_confirmed = (
                future["wyckoff_phase"]
                .astype(str)
                .str.contains("Spring|LPS|SOS|Breakout", regex=True)
                .any()
            )
            volume_expansion_confirmed = bool(
                pd.notna(prior_vol_ma20) and future["Volume"].max() > (prior_vol_ma20 * 1.2)
            )
            relative_strength_confirmed = bool(
                len(future) >= 10 and
                future["Close"].iloc[-1] > future["Close"].rolling(50, min_periods=10).mean().iloc[-1]
            )

            if trade.get("exit_type") == "Pattern_Recognition_Failure":
                research_label = "False_Positive"
            elif (
                future_max_return >= 15 and
                breakout_confirmed and
                markup_confirmed and
                volume_expansion_confirmed
            ):
                research_label = "True_Accumulation"
            elif future_max_return >= 10 and (breakout_confirmed or markup_confirmed or relative_strength_confirmed):
                research_label = "Possible_Accumulation"
            else:
                research_label = "False_Positive"

            enriched.append({
                **trade.to_dict(),
                "future_max_return":            future_max_return,
                "future_max_drawdown":          future_max_drawdown,
                "days_to_breakout":             days_to_breakout,
                "days_in_trade":                int((exit_ts - entry_ts).days),
                "breakout_confirmed":           bool(breakout_confirmed),
                "markup_confirmed":             bool(markup_confirmed),
                "relative_strength_confirmed":  bool(relative_strength_confirmed),
                "volume_expansion_confirmed":   bool(volume_expansion_confirmed),
                "research_label":               research_label,
            })
        except Exception:
            continue

    return pd.DataFrame(enriched)


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

        tp        = (df["High"] + df["Low"] + df["Close"]) / 3
        body      = (df["Close"] - df["Open"]).abs()
        rng       = df["High"] - df["Low"]
        vol_ma20  = df["Volume"].rolling(20).mean()
        rvol      = df["Volume"] / vol_ma20.replace(0, np.nan)
        spread_ma20 = rng.rolling(20).mean()

        f["f04_absorption"] = (
            ((df["Volume"] > vol_ma20 * 1.5) & (rng < spread_ma20 * 0.8)) &
            (df["Close"] <= df["Low"].rolling(20).min() * 1.05)
        ).astype(float)
        f["f36_wyckoff_score"] = self._compute_quick_wyckoff(df)

        price_bins = pd.cut(df["Close"], bins=40, labels=False)
        f["f01_liquidity_gap"] = (
            (df.groupby(price_bins)["Volume"].transform("sum") <
             df.groupby(price_bins)["Volume"].transform("mean") * 0.5)
            .astype(float).rolling(5).mean()
        )

        sma20 = df["Close"].rolling(20).mean()
        std20 = df["Close"].rolling(20).std()
        atr14 = pd.concat(
            [rng,
             (df["High"] - df["Close"].shift(1)).abs(),
             (df["Low"]  - df["Close"].shift(1)).abs()],
            axis=1
        ).max(axis=1).rolling(14).mean()

        f["f02_volatility_squeeze"] = (
            (((2 * std20) / sma20.replace(0, np.nan)) <
             ((2 * std20) / sma20.replace(0, np.nan)).rolling(20).mean() * 0.75) &
            (atr14 < atr14.rolling(20).mean() * 0.75)
        ).astype(float)

        spy_slope = (
            df.get("spy_close", df["Close"]).rolling(50).mean().diff(10) /
            df.get("spy_close", df["Close"]).rolling(50).mean().shift(10).replace(0, np.nan)
        )
        f["f03_regime"] = (spy_slope > 0.01).astype(float) - (spy_slope < -0.01).astype(float)

        resist = df["High"].rolling(20).max().shift(1)
        f["f05_breakout_quality"] = (
            (df["Close"] > resist) & (df["Close"].rolling(3).mean() > resist.shift(1))
        ).astype(float)
        f["f06_cis_weight"] = np.clip(
            1.0 / (std20 / std20.rolling(60).mean().replace(0, np.nan)).replace(0, np.nan), 0.5, 2.0
        )

        obv = (np.sign(df["Close"].diff()) * df["Volume"]).cumsum()
        f["f07_obv_velocity"] = (
            obv.diff(10) / obv.abs().rolling(10).mean().replace(0, np.nan)
        ).clip(-3, 3)

        f["f08_dist_from_ma"]  = (df["Close"] / sma20) - 1
        f["f10_temporal_seq"]  = (f["f04_absorption"].rolling(30).max() * (rvol < 0.7).astype(float))
        f["f11_kill_switch"]   = (
            (df["Close"].pct_change() < -0.05) | (rvol > 4.0)
        ).astype(float)
        f["f14_inst_intent"]   = (
            f["f04_absorption"] * 0.3 +
            f["f07_obv_velocity"].clip(0, 1) * 0.4 +
            f["f10_temporal_seq"] * 0.3
        ).clip(0, 1)
        f["f15_mtf"] = (
            (df["Close"] > sma20).astype(float) *
            (df["Close"].rolling(5).mean() > df["Close"].rolling(5).mean().rolling(4).mean()).astype(float)
        )

        support = df["Low"].rolling(20).min().shift(1)
        f["f20_liquidity_sweep"] = (
            (df["Low"] < support) & (df["Close"] > support)
        ).astype(float)
        f["f22_sr_strength"] = (
            (df["Low"].rolling(5).min() <= df["Low"].rolling(20).min() * 1.005)
            .astype(float).rolling(20).sum() / 20
        )
        f["f26_accept_reject"] = (
            ((df["Close"] > (df["High"] + df["Low"]) / 2) & (df["Volume"] > vol_ma20)).astype(float).rolling(5).mean() -
            ((df["Close"] < (df["High"] + df["Low"]) / 2) & (df["Volume"] > vol_ma20)).astype(float).rolling(5).mean()
        )
        f["f28_inst_part"] = (
            (body > body.rolling(20).mean() * 1.5) & (rvol > 1.5)
        ).astype(float)
        f["f31_bear_trap"] = (
            (df["Close"] < df["Low"].rolling(20).min().shift(1)) &
            (df["Close"].shift(1) > df["Low"].rolling(20).min().shift(2))
        ).astype(float)
        f["f35_struct_break"] = (
            (df["Close"] > df["High"].rolling(20).max().shift(1)).astype(float) -
            (df["Close"] < df["Low"].rolling(20).min().shift(1)).astype(float)
        )

        # MACRO ENRICHMENT
        if 'spy_close' in df.columns:
            spy_sma200 = df['spy_close'].rolling(200).mean()
            f['f_macro_spy_dist'] = df['spy_close'] / spy_sma200.replace(0, np.nan) - 1
            f['f_macro_spy_bull'] = (df['spy_close'] > spy_sma200).astype(float)
        else:
            f['f_macro_spy_dist'] = 0.0
            f['f_macro_spy_bull'] = 0.0

        if 'vix_close' in df.columns:
            vix_ma21  = df['vix_close'].rolling(21).mean()
            vix_std21 = df['vix_close'].rolling(21).std()
            f['f_macro_vix_zscore'] = (df['vix_close'] - vix_ma21) / vix_std21.replace(0, np.nan)
        else:
            f['f_macro_vix_zscore'] = 0.0

        if 'spy_close' in df.columns:
            stock_ret60 = df['Close'].pct_change(60)
            spy_ret60   = df['spy_close'].pct_change(60)
            f['f_macro_rel_str'] = (1 + stock_ret60) / (1 + spy_ret60).replace(0, np.nan) - 1
        else:
            f['f_macro_rel_str'] = 0.0

        return f.fillna(0)

    def composite_cis(self, factors: pd.DataFrame, df: pd.DataFrame = None) -> pd.Series:
        use_ml        = False
        model         = None
        phase_encoder = None

        if st is not None and getattr(st, 'session_state', None):
            use_ml        = getattr(st.session_state, 'use_ml', False)
            model         = getattr(st.session_state, 'ml_model', None)
            phase_encoder = getattr(st.session_state, 'phase_encoder', None)

        # ── תיקון: וודא ש-phase_encoder הוא אובייקט אמיתי ──
        if phase_encoder is not None and not hasattr(phase_encoder, "classes_"):
            phase_encoder = None

        # ── תיקון: וודא של-model יש predict_proba ──
        if use_ml and model is not None and hasattr(model, "predict_proba"):
            X_pred = factors.copy()
            if phase_encoder is not None and df is not None and "wyckoff_phase" in df.columns:
                phases = df["wyckoff_phase"].fillna("לא בתהליך איסוף")
                try:
                    phase_labels = phase_encoder.transform(phases)
                    for i, label in enumerate(phase_encoder.classes_):
                        X_pred[f"phase_{label}"] = (phase_labels == i).astype(int)
                except Exception:
                    for label in phase_encoder.classes_:
                        X_pred[f"phase_{label}"] = 0
            expected_features = getattr(model, "feature_names_in_", None)
            if expected_features is not None:
                for c in expected_features:
                    if c not in X_pred.columns:
                        X_pred[c] = 0
                X_pred = X_pred[expected_features]
            try:
                probs = model.predict_proba(X_pred)[:, 1]
            except Exception:
                probs = model.predict(X_pred)
            score = pd.Series(probs * 100, index=factors.index)
        else:
            w   = {
                "f04_absorption":    6,
                "f07_obv_velocity":  5,
                "f14_inst_intent":   6,
                "f20_liquidity_sweep": 3,
                "f26_accept_reject": 3,
                "f35_struct_break":  2,
            }
            tot   = sum(abs(v) for v in w.values() if v != 0)
            score = pd.Series(0.0, index=factors.index)
            for col, weight in w.items():
                if col in factors.columns:
                    score += factors[col].clip(-1, 1) * weight
            score = (score / tot * 100 + 50).clip(0, 100)

        if "f36_wyckoff_score" in factors.columns:
            wyckoff_score = factors["f36_wyckoff_score"]
            boost_floor   = np.where(wyckoff_score >= 0.9, 65.0, 0.0)
            score         = np.maximum(score, boost_floor)
            boost         = np.where(wyckoff_score > 0.5, (wyckoff_score - 0.5) * 40, 0)
            score         = score + boost
        if "f11_kill_switch" in factors.columns:
            score = score * (1 - factors["f11_kill_switch"])

        return score.round(1).clip(0, 100)

    def get_wyckoff_phase(self, df: pd.DataFrame) -> pd.Series:
        phases = pd.Series("לא בתהליך איסוף", index=df.index)
        if len(df) < 40:
            return phases
        has_sc, has_ar, has_st = False, False, False
        sc_idx, sc_low, ar_high = 0, 0, 0
        for i in range(40, len(df)):
            window = df.iloc[max(0, i-90):i+1]
            if len(window) < 40:
                continue
            vol_ma        = window['Volume'].rolling(20).mean()
            current_phase = "לא בתהליך איסוף"
            for j in range(1, len(window)):
                vol      = window['Volume'].iloc[j]
                vol_ma_j = vol_ma.iloc[j]
                close    = window['Close'].iloc[j]
                low      = window['Low'].iloc[j]
                high     = window['High'].iloc[j]
                open_px  = window['Open'].iloc[j]
                if not has_sc:
                    if close < open_px and vol > vol_ma_j * 2.0 and close <= window['Close'].iloc[max(0, j-20):j].min():
                        has_sc        = True
                        sc_idx        = j
                        sc_low        = low
                        current_phase = "Phase A (SC)"
                elif has_sc and not has_ar and (j - sc_idx <= 15):
                    if close > open_px and close > window['Close'].iloc[j-1]:
                        has_ar        = True
                        ar_high       = high
                        current_phase = "Phase B (AR)"
                elif has_ar and not has_st:
                    if vol < window['Volume'].iloc[sc_idx] * 0.75 and abs(low - sc_low)/sc_low < 0.05:
                        has_st        = True
                        current_phase = "Phase B (ST)"
                elif has_st:
                    if low < sc_low and close > sc_low:
                        current_phase = "Phase C (Spring)"
                    elif low > sc_low and low < window['Low'].iloc[j-1] and vol < vol_ma_j:
                        current_phase = "Phase D (LPS)"
                    elif close > ar_high and vol > vol_ma_j * 1.5:
                        current_phase = "Phase D (SOS)"
                        has_sc  = False
                        has_ar  = False
                        has_st  = False
                    elif close > ar_high * 1.02:
                        current_phase = "Phase E (Breakout)"
            phases.iloc[i] = current_phase
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
        return None, None

    cfg_period = period if period else f"{start}/{end}"
    engine     = FactorEngine(
        BacktestConfig(
            period=cfg_period,
            stop_loss_pct=stop_loss_pct,
            atr_multiplier=atr_multiplier,
        )
    )
    factors             = engine.compute(df)
    df['wyckoff_phase'] = engine.get_wyckoff_phase(df)
    df['cis_score']     = engine.composite_cis(factors, df)
    df['Daily_Return']  = df['Close'].pct_change().fillna(0)

    high_low    = df['High'] - df['Low']
    high_close  = (df['High'] - df['Close'].shift(1)).abs()
    low_close   = (df['Low']  - df['Close'].shift(1)).abs()
    true_range  = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr_series  = true_range.rolling(14).mean()

    positions   = []
    audit_logs  = []
    in_position = False
    entry_price = 0
    entry_phase = ""
    entry_date  = None
    peak_price  = 0
    cis_at_entry     = 0
    stop_loss_level  = 0

    for i in range(len(df)):
        current_phase = df['wyckoff_phase'].iloc[i]
        current_cis   = df['cis_score'].iloc[i]
        phase_allowed = check_phase_entry_allowed(current_phase, risk_profile)
        score_allowed = current_cis >= threshold

        if not in_position:
            if phase_allowed and score_allowed:
                positions.append(1)
                in_position      = True
                entry_price      = df['Close'].iloc[i]
                entry_phase      = current_phase
                entry_date       = df.index[i]
                peak_price       = entry_price
                cis_at_entry     = current_cis
                atr_val          = atr_series.iloc[i] if not pd.isna(atr_series.iloc[i]) else 0
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
                ret     = (exit_px - entry_price) / entry_price
                max_dd  = (peak_price - min(entry_price, exit_px)) / peak_price if peak_price > 0 else 0
                audit_logs.append({
                    "entry_date":       entry_date.strftime("%Y-%m-%d"),
                    "exit_date":        df.index[i].strftime("%Y-%m-%d"),
                    "phase_at_entry":   entry_phase,
                    "entry_price":      round(entry_price, 2),
                    "exit_price":       round(exit_px, 2),
                    "return_pct":       round(ret * 100, 2),
                    "win":              ret > 0,
                    "max_drawdown_pct": round(max_dd * 100, 2),
                    "exit_type":        "Pattern_Recognition_Failure",
                    "phase_at_exit":    current_phase,
                    "cis_at_entry":     cis_at_entry,
                })
                in_position = False
                continue

            if "לא בתהליך" in current_phase or current_cis < threshold - 15:
                positions.append(0)
                exit_px = df['Close'].iloc[i]
                ret     = (exit_px - entry_price) / entry_price
                max_dd  = (peak_price - min(entry_price, exit_px)) / peak_price if peak_price > 0 else 0
                audit_logs.append({
                    "entry_date":       entry_date.strftime("%Y-%m-%d"),
                    "exit_date":        df.index[i].strftime("%Y-%m-%d"),
                    "phase_at_entry":   entry_phase,
                    "entry_price":      round(entry_price, 2),
                    "exit_price":       round(exit_px, 2),
                    "return_pct":       round(ret * 100, 2),
                    "win":              ret > 0,
                    "max_drawdown_pct": round(max_dd * 100, 2),
                    "exit_type":        "Phase_Change",
                    "phase_at_exit":    current_phase,
                    "cis_at_entry":     cis_at_entry,
                })
                in_position = False
            else:
                positions.append(1)
                if df['Close'].iloc[i] > peak_price:
                    peak_price = df['Close'].iloc[i]

    df['Position']       = pd.Series(positions, index=df.index[:len(positions)]).shift(1).fillna(0)
    df['Strategy_Return'] = df['Position'] * df['Daily_Return']
    df['Cum_Strategy']   = (1 + df['Strategy_Return']).cumprod() - 1
    df['Cum_Baseline']   = (1 + df['Daily_Return']).cumprod() - 1
    return df, pd.DataFrame(audit_logs) if audit_logs else pd.DataFrame()