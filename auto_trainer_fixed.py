# auto_trainer_fixed.py – BATCHED MODE + FULL AUTO FALLBACK + GITKEEP PERSISTENCE
# ─────────────────────────────────────────────────────────────
# אם קיים batch_config.json → מריץ רק את הסקטור/המניות שנבחרו ב-UI
# אם לא קיים → מריץ אימון מלא על כל הסקטורים (כמו בעבר)
# דואג ליצירת קובץ .gitkeep כדי להכריח את GitHub לעקוב אחרי התיקייה
# ─────────────────────────────────────────────────────────────

import os
import sys
import json
import time
import pickle
import traceback
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder

# ── השתקת Streamlit (מונע ScriptRunContext) ──
import streamlit as _st
class _FakeStSession:
    def __getattr__(self, name):
        return None
_st.session_state = _FakeStSession()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

LOG_FILE = os.path.join(BASE_DIR, "auto_trainer_error.log")

def log_message(msg):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {msg}\n")

from scout_core import (
    clean_filename,
    calculate_optimal_threshold,
    FactorEngine,
    BacktestConfig,
    run_wyckoff_anchored_backtest,
)

import yfinance as yf

MODEL_DIR = os.path.join(BASE_DIR, "models")
STATUS_FILE = os.path.join(MODEL_DIR, "auto_trainer_status.json")
DONE_FLAG = os.path.join(MODEL_DIR, "auto_trainer.done")
PID_FILE = os.path.join(MODEL_DIR, "auto_trainer.pid")
STOP_FILE = os.path.join(MODEL_DIR, "auto_trainer.stop")
LOCK_FILE = os.path.join(MODEL_DIR, "auto_trainer.lock")
BATCH_CONFIG_FILE = os.path.join(MODEL_DIR, "batch_config.json")

# ─── רשימות מלאות לריצה אוטומטית (ללא batch_config) ─────────
GROWTH_TICKERS = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","CRM",
    "NFLX","AMD","ADBE","CSCO","TXN","QCOM","INTC","INTU","ADI",
    "PANW","CRWD","FTNT","ZS","DDOG","SNOW","MDB","NET","PLTR",
    "UBER","ABNB","COIN","SOFI","UPST","ONTO","KLAC","LRCX",
    "AMAT","MRVL","SMCI","DELL","HPQ","RBLX","U","TTWO","EA",
]

VALUE_TICKERS = [
    "BRK-B","JPM","JNJ","V","UNH","PG","MA","HD","MRK","ABBV",
    "PEP","KO","COST","WMT","LLY","TMO","MCD","ACN","BAC","ABT",
    "DHR","RTX","HON","NKE","AMGN","PM","IBM","SBUX","GS","CAT",
    "BA","GE","SPGI","AXP","BLK","DE","ISRG","MDLZ","GILD",
    "REGN","SYK","ZTS","MMC","AON","TJX","SCHW","CB","USB","WFC",
    "C","MS","CVS","CI","AMT","PLD","CCI","EQIX","SPG","O",
    "WELL","DLR","DIS","CMCSA","DAL","UAL","AAL","LUV","FDX",
    "UPS","XPO","ODFL","DKNG","MGM","CZR","RCL","CCL","MAR","HLT",
]

COMMODITIES_TICKERS = [
    "XOM","CVX","SLB","EOG","OXY","COP","PSX","VLO",
    "FCX","NEM","GOLD","AEM","WPM","FNV","PAAS","AG",
    "GLD","SLV",
]

FULL_SECTORS_LIST = [
    ("Growth (צמיחה)", GROWTH_TICKERS),
    ("Value/Index (ערך/מדד)", VALUE_TICKERS),
    ("Commodities (סחורות)", COMMODITIES_TICKERS),
]

# ─── Helper: יצירת התיקייה וקובץ gitkeep כדי שגיטהאב יעקוב אחריה ───
def ensure_model_dir():
    os.makedirs(MODEL_DIR, exist_ok=True)
    gitkeep_path = os.path.join(MODEL_DIR, ".gitkeep")
    if not os.path.exists(gitkeep_path):
        try:
            with open(gitkeep_path, "w") as f:
                f.write("") # קובץ ריק שמאותת לגיטהאב לשמור את התיקייה
        except Exception as e:
            log_message(f"Could not create .gitkeep: {e}")

# ─── Helper: קריאת batch_config ──────────────────────────────
def read_batch_config():
    if not os.path.exists(BATCH_CONFIG_FILE):
        return None
    try:
        with open(BATCH_CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if "slot" in cfg and "tickers" in cfg and isinstance(cfg["tickers"], list):
            return cfg
    except Exception as e:
        log_message(f"שגיאה בקריאת batch_config.json: {e}")
    return None

# ─── Helper: כתיבת סטטוס ──────────────────────────────────────
def write_status(state, message="", progress=0, current_slot="N/A", started_at=None, finished_at=None, error=None):
    ensure_model_dir()
    payload = {
        "state": state,
        "message": message,
        "progress": int(progress),
        "current_slot": current_slot,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "started_at": started_at or datetime.now().isoformat(timespec="seconds"),
        "finished_at": finished_at or "N/A",
    }
    if error:
        payload["error"] = str(error)
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

# ─── Helper: הורדת מאקרו (SPY + VIX) ─────────────────────────
def _safe_download_macro(start_date, end_date):
    try:
        spy_obj = yf.Ticker("SPY")
        vix_obj = yf.Ticker("^VIX")
        spy = spy_obj.history(start=start_date, end=end_date)
        vix = vix_obj.history(start=start_date, end=end_date)
        if "Close" not in spy.columns or "Close" not in vix.columns:
            raise ValueError("Missing Close column")
        spy_close = spy["Close"].rename("SPY_Close")
        vix_close = vix["Close"].rename("VIX_Close")
        macro = pd.concat([spy_close, vix_close], axis=1).ffill().bfill()
        macro.index = pd.to_datetime(macro.index).date
        return macro
    except Exception as e:
        log_message(f"מאקרו נכשל: {e}")
        return None

# ─── לוגיקת איסוף עסקאות לסקטור/רשימה ──────────────────────
def train_sector(slot, tickers, start_date, end_date, base_threshold=35, risk_profile="Aggressive"):
    features_list = []
    errors = 0
    added_trades = 0
    engine = FactorEngine(BacktestConfig())

    macro = _safe_download_macro(start_date, end_date)
    total = len(tickers)

    for idx, ticker in enumerate(tickers):
        if os.path.exists(STOP_FILE):
            log_message(f"Stop request detected after {idx}/{total} tickers. Breaking.")
            break

        time.sleep(0.5)

        try:
            bt_df, audit_df = run_wyckoff_anchored_backtest(
                ticker,
                use_ai=False,
                threshold=base_threshold,
                period=None,
                start=start_date,
                end=end_date,
                risk_profile=risk_profile,
            )
            if audit_df is None or audit_df.empty:
                log_message(f"  [{slot}] {ticker} ({idx+1}/{total}): אין עסקאות בתקופה עם threshold={base_threshold}")
                continue

            df = bt_df.copy()

            if macro is not None and not df.empty:
                df["date_key"] = df.index.date
                df = df.merge(macro, left_on="date_key", right_index=True, how="left")
                df.drop(columns="date_key", inplace=True)
                for col in ["SPY_Close", "VIX_Close"]:
                    if col in df.columns:
                        df[col] = df[col].ffill().bfill().fillna(0)

            ticker_trades = 0
            for _, trade in audit_df.iterrows():
                entry_dt = pd.Timestamp(trade["entry_date"])
                if entry_dt not in df.index:
                    continue
                window_df = (
                    df.loc[:entry_dt].iloc[-200:]
                    if len(df.loc[:entry_dt]) > 200
                    else df.loc[:entry_dt]
                )
                try:
                    factors = engine.compute(window_df)
                    if len(factors) == 0:
                        continue
                    factors = factors.replace([np.inf, -np.inf], np.nan).fillna(0)
                    feature_row = factors.iloc[-1].to_dict()

                    raw_phase = df.loc[entry_dt]["wyckoff_phase"]
                    if isinstance(raw_phase, pd.Series):
                        raw_phase = raw_phase.iloc[-1]

                    feature_row["phase"] = raw_phase
                    feature_row["label"] = 1 if trade["win"] else 0
                    feature_row["ticker"] = ticker
                    feature_row["entry_date"] = trade["entry_date"]
                    features_list.append(feature_row)
                    added_trades += 1
                    ticker_trades += 1
                except Exception:
                    continue

            if ticker_trades > 0:
                log_message(f"  [{slot}] {ticker} ({idx+1}/{total}): נאספו {ticker_trades} עסקאות")
            else:
                log_message(f"  [{slot}] {ticker} ({idx+1}/{total}): 0 עסקאות שניתן לחלץ features")

        except Exception as e:
            errors += 1
            log_message(f"  [{slot}] {ticker} ({idx+1}/{total}) שגיאה: {e}")
            continue

    return features_list, added_trades, errors


# ─── בניית מודל מ-combined_df ─────────────────────────────────
def build_and_save_model(slot, combined_df, started_at):
    if combined_df.empty:
        log_message(f"[{slot}] דילוג — אין נתונים.")
        return False

    if combined_df["label"].nunique() < 2:
        log_message(
            f"[{slot}] דילוג — אין שתי מחלקות. "
            f"סה\"כ עסקאות: {len(combined_df)}, "
            f"Win: {combined_df['label'].sum()}, Loss: {(combined_df['label']==0).sum()}"
        )
        return False

    safe_slot_name = clean_filename(str(slot))

    history_path = os.path.join(MODEL_DIR, f"training_data_{safe_slot_name}.csv")
    combined_df.to_csv(history_path, index=False)
    log_message(f"[{slot}] CSV נשמר: {history_path} ({len(combined_df)} שורות)")

    y = combined_df["label"].values
    le = LabelEncoder()
    phase_encoded = le.fit_transform(combined_df["phase"].fillna("לא בתהליך איסוף"))
    phase_dummies = pd.get_dummies(phase_encoded, prefix="phase").astype(int)

    drop_cols = ["phase", "label", "ticker", "entry_date"]
    tech_factors = combined_df.drop(
        columns=[c for c in drop_cols if c in combined_df.columns]
    ).select_dtypes(include=[np.number])

    X = (
        pd.concat(
            [tech_factors.reset_index(drop=True), phase_dummies.reset_index(drop=True)],
            axis=1,
        )
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0)
    )

    model = RandomForestClassifier(
        n_estimators=100,
        max_depth=3,
        min_samples_leaf=3,
        oob_score=True,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X, y)

    try:
        train_acc = model.oob_score_
    except Exception:
        train_acc = model.score(X, y)

    optimal_th = calculate_optimal_threshold(model, X, y)

    meta = {
        "train_ticker": "AUTO_TRAINER_MASTER_LIBRARY",
        "train_acc": train_acc,
        "test_acc": train_acc,
        "slot": slot,
        "model_type": "Wyckoff-Anchored",
        "num_trades": len(combined_df),
        "recommended_threshold": optimal_th,
    }

    file_path = os.path.join(MODEL_DIR, f"model_{safe_slot_name}.pkl")
    tmp_path = file_path + ".tmp"
    with open(tmp_path, "wb") as f:
        pickle.dump(
            {"model": model, "metadata": meta, "phase_encoder": le},
            f,
            protocol=pickle.HIGHEST_PROTOCOL,
        )
    os.replace(tmp_path, file_path)

    log_message(
        f"[{slot}] ✅ מודל נשמר: {file_path} | "
        f"עסקאות: {len(combined_df)} | "
        f"OOB: {train_acc*100:.1f}% | "
        f"Threshold: {optimal_th}"
    )
    return True


# ─── ריצת סקטור יחיד (כולל merge עם CSV קיים) ───────────────
def process_sector(slot, tickers, start_date, end_date, base_threshold, started_at, sector_idx, total_sectors):
    log_message(f"{'='*50}")
    log_message(f"מתחיל סקטור: {slot} | {len(tickers)} מניות | Threshold: {base_threshold}")

    write_status(
        state="running",
        message=f"מעבד סקטור: {slot} ({len(tickers)} מניות)",
        progress=int((sector_idx / total_sectors) * 100),
        current_slot=slot,
        started_at=started_at,
    )

    features_list, added_trades, errors = train_sector(
        slot=slot,
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        base_threshold=base_threshold,
    )

    log_message(f"[{slot}] איסוף הסתיים: {added_trades} עסקאות חדשות, {errors} שגיאות")

    safe_slot_name = clean_filename(str(slot))
    history_path = os.path.join(MODEL_DIR, f"training_data_{safe_slot_name}.csv")

    new_df = pd.DataFrame(features_list) if features_list else pd.DataFrame()

    if os.path.exists(history_path):
        try:
            hist_df = pd.read_csv(history_path)
            log_message(f"[{slot}] נמצאו {len(hist_df)} עסקאות קיימות בדיסק")
            if not new_df.empty:
                combined_df = pd.concat([hist_df, new_df], ignore_index=True)
                combined_df = combined_df.drop_duplicates(
                    subset=["ticker", "entry_date"], keep="last"
                )
            else:
                combined_df = hist_df
        except Exception as e:
            log_message(f"[{slot}] שגיאה בקריאת CSV קיים: {e} — משתמש רק בנתונים חדשים")
            combined_df = new_df
    else:
        combined_df = new_df

    if combined_df.empty:
        log_message(f"[{slot}] ⚠️  אין נתונים כלל — מדלג על אימון המודל")
        return

    build_and_save_model(slot, combined_df, started_at)


# ─── נקודת כניסה ראשית ───────────────────────────────────────
def run_auto_trainer():
    ensure_model_dir()
    
    log_message("=" * 60)
    log_message("=== auto_trainer_fixed.py STARTED ===")

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    with open(LOCK_FILE, "w") as f:
        f.write(datetime.now().isoformat())

    if os.path.exists(DONE_FLAG):
        os.remove(DONE_FLAG)

    started_at = datetime.now().isoformat(timespec="seconds")
    write_status(state="running", message="האימון האוטומטי התחיל", progress=0, started_at=started_at)

    end_date_dt = datetime.today()
    start_date_dt = end_date_dt - timedelta(days=6 * 365)
    start_date = start_date_dt.strftime("%Y-%m-%d")
    end_date = end_date_dt.strftime("%Y-%m-%d")

    base_threshold = 35
    batch_cfg = read_batch_config()

    try:
        if batch_cfg is not None:
            slot = batch_cfg["slot"]
            tickers = batch_cfg["tickers"]
            log_message(f"מצב Batched: סקטור='{slot}', {len(tickers)} מניות: {tickers}")

            process_sector(
                slot=slot,
                tickers=tickers,
                start_date=start_date,
                end_date=end_date,
                base_threshold=base_threshold,
                started_at=started_at,
                sector_idx=0,
                total_sectors=1,
            )

            try:
                os.remove(BATCH_CONFIG_FILE)
            except Exception:
                pass

        else:
            log_message("מצב Full Auto — מריץ את כל הסקטורים")
            total_sectors = len(FULL_SECTORS_LIST)

            for sector_idx, (slot, tickers) in enumerate(FULL_SECTORS_LIST):
                if os.path.exists(STOP_FILE):
                    log_message("עצירה רכה: יוצאים מהלולאה הראשית.")
                    break

                process_sector(
                    slot=slot,
                    tickers=tickers,
                    start_date=start_date,
                    end_date=end_date,
                    base_threshold=base_threshold,
                    started_at=started_at,
                    sector_idx=sector_idx,
                    total_sectors=total_sectors,
                )

        finished_at = datetime.now().isoformat(timespec="seconds")
        write_status(
            state="completed",
            message="האימון הסתיים בהצלחה",
            progress=100,
            started_at=started_at,
            finished_at=finished_at,
        )
        with open(DONE_FLAG, "w", encoding="utf-8") as f:
            f.write(f"completed_at={finished_at}\n")

        log_message(f"=== auto_trainer_fixed.py COMPLETED at {finished_at} ===")

    except Exception as e:
        error_msg = traceback.format_exc()
        log_message(f"Critical error:\n{error_msg}")
        write_status(state="error", message="האימון נכשל", progress=0, error=str(e))
        raise

    finally:
        for fpath in [PID_FILE, LOCK_FILE]:
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except Exception:
                    pass


if __name__ == "__main__":
    run_auto_trainer()
