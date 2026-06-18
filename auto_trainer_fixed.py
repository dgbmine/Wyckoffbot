# ============================================================
# auto_trainer_fixed.py – ADVANCED WYCKOFF ML TRAINER
# ============================================================
import gc
import json
import os
import pickle
import sys
import traceback
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix

try:
    import streamlit as _st  # type: ignore
    try:
        if not hasattr(_st, "session_state"):
            class _FakeStSession:
                def __getattr__(self, name):
                    return None
            _st.session_state = _FakeStSession()
    except Exception:
        pass
except Exception:
    class _FakeStModule:
        session_state = None
        def __getattr__(self, name):
            return None
    _st = _FakeStModule()  # type: ignore

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

_CLOUD_RUN = (
    os.environ.get("K_SERVICE") is not None
    or os.environ.get("CLOUD_RUN", "").lower() == "true"
)
_TMP_ROOT = "/tmp/scout" if _CLOUD_RUN else BASE_DIR

MODEL_DIR = os.path.join(_TMP_ROOT, "models")
BATCH_CONFIG_FILE = os.path.join(MODEL_DIR, "batch_config.json")
STATUS_FILE = os.path.join(MODEL_DIR, "auto_trainer_status.json")
DONE_FLAG = os.path.join(MODEL_DIR, "auto_trainer.done")
LOG_FILE = os.path.join(_TMP_ROOT, "auto_trainer_error.log")

TRAINING_PERIOD = "6y"
BASE_THRESHOLD = 50
MIN_TRADES_FOR_ML = 10

def _ensure_dirs():
    os.makedirs(MODEL_DIR, exist_ok=True)
    log_dir = os.path.dirname(LOG_FILE)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

def log_message(msg):
    try:
        _ensure_dirs()
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{stamp} - {msg}\n"
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    except Exception:
        try:
            sys.stderr.write(f"[trainer log fallback] {line}")
        except Exception:
            pass

def log_exception(prefix, exc):
    try:
        log_message(f"{prefix}: {exc}")
        log_message(traceback.format_exc())
    except Exception:
        pass

_SCOUT_IMPORT_ERROR = None
try:
    from scout_core import (
        clean_filename,
        calculate_optimal_threshold,
        FactorEngine,
        BacktestConfig,
        run_wyckoff_anchored_backtest,
    )
except Exception as e:
    log_exception("CRITICAL ERROR: Failed to import scout_core", e)
    _SCOUT_IMPORT_ERROR = str(e)

TECH_TICKERS = [
    "AAPL","MSFT","NVDA","GOOGL","GOOG","AMZN","META","AVGO","CRM","ORCL",
    "ADBE","AMD","INTC","QCOM","TXN","ADI","NOW","SNPS","CDNS","ANSS",
    "KLAC","LRCX","AMAT","MU","PANW","CRWD","ZS","NET","DDOG","MDB",
    "TEAM","WDAY","SHOP","INTU","IBM","HPQ","HPE","FTNT","CSCO","MRVL",
    "ON","ROP","FSLR","OKTA","PLTR","ANET","DELL","SMCI","MSI","SNOW"
]

GROWTH_TICKERS = [
    "TSLA","NFLX","UBER","ABNB","CMG","RBLX","ROKU","PYPL","SQ","COIN",
    "MSTR","DASH","ETSY","SNAP","PINS","LCID","RIVN","HOOD","CRSP","U",
    "EA","TTWO","BIDU","FVRR","AFRM","NICE","OKTA","DOCU","ZS","NET",
    "DDOG","MDB","TEAM","SNOW","PLTR","W","CAVA","DUOL","CELH","SFM"
]

VALUE_TICKERS = [
    "BRK-B","JPM","BAC","WFC","C","GS","MS","BK","SCHW","AXP",
    "BLK","SPGI","ICE","CME","COF","USB","PNC","TFC","NTRS","STT",
    "ALL","AFL","MET","PRU","CB","TRV","AJG","BRO","AON","CBRE",
    "JNJ","PG","KO","PEP","WMT","COST","HD","LOW","CVX","XOM"
]

HEALTHCARE_TICKERS = [
    "UNH","JNJ","LLY","MRK","ABBV","PFE","TMO","DHR","MDT","AMGN",
    "GILD","ISRG","SYK","ZTS","REGN","VRTX","BSX","ELV","CI","HCA",
    "CAH","MCK","HUM","IQV","BMY","BIIB","ALGN","ILMN","PODD","EW",
    "MOH","CRL","WST","HOLX","DGX","BAX","BMY","CVS","UHS","TEL"
]

FINANCIALS_TICKERS = [
    "JPM","BAC","C","WFC","GS","MS","SCHW","BLK","AXP","COF",
    "USB","PNC","TFC","BK","STT","NTRS","CME","ICE","SPGI","CBOE",
    "AIG","MET","PRU","ALL","AFL","TRV","CB","AJG","BRO","RJF",
    "SYF","MTB","FITB","HBAN","KEY","RF","CFG","FIS","FI","GPN",
    "PYPL","COIN","V","MA","DFS","BKNG","WRB","AGO","L","RDN"
]

ENERGY_MATERIALS_TICKERS = [
    "XOM","CVX","COP","SLB","EOG","OXY","HAL","APA","DVN","MRO",
    "FANG","PSX","VLO","MPC","KMI","WMB","OKE","EQT","CTRA","HES",
    "NOC","NUE","FCX","NEM","ALB","APD","LIN","ECL","CF","DD",
    "PPG","SHW","MLM","VMC","EMN","MOS","RPM","DOW","LNG","SLCA"
]

CONSUMER_TICKERS = [
    "AMZN","WMT","COST","TGT","HD","LOW","MCD","SBUX","NKE","TJX",
    "ROST","DG","DLTR","KR","GIS","KHC","CL","KO","PEP","MDLZ",
    "HSY","KDP","SYY","YUM","CMG","MGM","LVS","RCL","CCL","NCLH",
    "DPZ","FIVE","ULTA","ORLY","AZO","TGT","BBY","TROW","NVR","TSCO",
    "LEVI","WBA","CHD","EL","LULU","SBUX","WYNN","EXPE","NCLH","BKNG"
]

INDUSTRIALS_TICKERS = [
    "CAT","DE","HON","UPS","UNP","CSX","NSC","EMR","ITW","PH",
    "ETN","GD","LMT","NOC","RTX","BA","TXT","ROP","FAST","GWW",
    "URI","IR","OTIS","JCI","CMI","CARR","AOS","DOV","XYL","ROK",
    "AME","HWM","PCAR","FDX","EXPD","CHRW","ODFL","JBHT","WM","RSG"
]

MIDCAP_TICKERS = [
    "SNPS","CDNS","ANSS","ANET","PANW","CRWD","ZS","NET","DDOG","MDB",
    "TEAM","SNOW","PLTR","FSLR","ENPH","SEDG","TER","ZBRA","TYL","DECK",
    "CPRT","PAYC","VEEV","HUBS","CRL","DOCS","MELI","SE","PDD","EXAS",
    "ELF","CART","ARM","APP","VRT","UAL","ALK","CCL","RCL","PINS"
]

DEFENSIVE_TICKERS = [
    "KO","PEP","PG","PM","MO","KMB","CL","GIS","KHC","MDLZ",
    "HSY","KDP","CAG","HRL","SJM","KR","WMT","COST","DLTR","DG",
    "NEE","DUK","SO","AEP","EXC","ED","D","XEL","SRE","ES",
    "O","PLD","AMT","CCI","EQIX","DLR","WELL","VICI","PSA","AVB"
]

_RAW_BUCKETS = {
    "Tech": TECH_TICKERS,
    "Growth": GROWTH_TICKERS,
    "Value": VALUE_TICKERS,
    "Healthcare": HEALTHCARE_TICKERS,
    "Financials": FINANCIALS_TICKERS,
    "Energy": ENERGY_MATERIALS_TICKERS,
    "Consumer": CONSUMER_TICKERS,
    "Industrials": INDUSTRIALS_TICKERS,
    "MidCaps": MIDCAP_TICKERS,
    "Defensive": DEFENSIVE_TICKERS,
}

def _dedupe_keep_order(items):
    seen = set()
    out = []
    for x in items:
        if not x or not isinstance(x, str):
            continue
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

UNIVERSE_TICKERS = _dedupe_keep_order(
    [ticker for bucket in _RAW_BUCKETS.values() for ticker in bucket]
)

SECTOR_BUCKETS = {
    "Tech": _dedupe_keep_order(TECH_TICKERS),
    "Growth": _dedupe_keep_order([t for t in GROWTH_TICKERS if t not in TECH_TICKERS]),
    "Value": _dedupe_keep_order([t for t in VALUE_TICKERS if t not in TECH_TICKERS and t not in GROWTH_TICKERS]),
    "Healthcare": _dedupe_keep_order(HEALTHCARE_TICKERS),
    "Financials": _dedupe_keep_order([t for t in FINANCIALS_TICKERS if t not in TECH_TICKERS]),
    "Energy": _dedupe_keep_order([t for t in ENERGY_MATERIALS_TICKERS if t not in TECH_TICKERS]),
    "Consumer": _dedupe_keep_order([t for t in CONSUMER_TICKERS if t not in TECH_TICKERS]),
    "Industrials": _dedupe_keep_order([t for t in INDUSTRIALS_TICKERS if t not in TECH_TICKERS]),
    "MidCaps": _dedupe_keep_order([t for t in MIDCAP_TICKERS if t not in TECH_TICKERS]),
    "Defensive": _dedupe_keep_order([t for t in DEFENSIVE_TICKERS if t not in TECH_TICKERS]),
}

TRAINING_STATE = {
    "overall_total": len(UNIVERSE_TICKERS),
    "overall_done": 0,
    "overall_success": 0,
    "overall_failed": 0,
    "overall_skipped": 0,
    "current_sector": "",
}

def apply_custom_batch():
    global UNIVERSE_TICKERS
    if os.path.exists(BATCH_CONFIG_FILE):
        try:
            with open(BATCH_CONFIG_FILE, "r") as f:
                data = json.load(f)
                if "tickers" in data and isinstance(data["tickers"], list) and len(data["tickers"]) > 0:
                    custom_tickers = _dedupe_keep_order([str(t).upper() for t in data["tickers"]])
                    log_message(f"Custom batch configuration loaded. Overriding universe to {len(custom_tickers)} selected tickers.")
                    UNIVERSE_TICKERS = custom_tickers
                    TRAINING_STATE["overall_total"] = len(custom_tickers)
                    return [("Selected_Assets", custom_tickers)]
        except Exception as e:
            log_exception("Failed to parse batch_config.json. Falling back to default universe.", e)
    return None

def _safe_json_dump(path, payload):
    _ensure_dirs()
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp_path, path)

def write_status(**kwargs):
    try:
        _ensure_dirs()
        payload = dict(kwargs)
        payload.setdefault("timestamp", datetime.now().isoformat())
        payload.setdefault("overall_total", TRAINING_STATE.get("overall_total", 0))
        payload.setdefault("overall_done", TRAINING_STATE.get("overall_done", 0))
        payload.setdefault("overall_success", TRAINING_STATE.get("overall_success", 0))
        payload.setdefault("overall_failed", TRAINING_STATE.get("overall_failed", 0))
        payload.setdefault("overall_skipped", TRAINING_STATE.get("overall_skipped", 0))
        _safe_json_dump(STATUS_FILE, payload)
    except Exception:
        pass

def _normalize_timestamp(value):
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    try:
        if getattr(ts, "tzinfo", None) is not None:
            ts = ts.tz_localize(None)
    except Exception:
        try:
            ts = ts.tz_convert(None)
        except Exception:
            pass
    try:
        return ts.normalize()
    except Exception:
        return ts

def _normalize_factor_index(df):
    if df is None or df.empty:
        return df
    out = df.copy()
    idx = pd.to_datetime(out.index, errors="coerce")
    try:
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert(None)
    except Exception:
        try:
            idx = idx.tz_localize(None)
        except Exception:
            pass
    try:
        idx = idx.normalize()
    except Exception:
        pass
    out.index = idx
    out = out[~out.index.isna()]
    if not out.index.is_unique:
        out = out[~out.index.duplicated(keep="last")]
    return out

def _status_message_for_sector(slot, processed, total, success, failed, skipped, extra=""):
    pct = 0 if total <= 0 else int((processed / total) * 100)
    base = (
        f"{slot}: {processed}/{total} טיקרס ({pct}%) | "
        f"נכשלו={failed} | דילוגים={skipped} | הצלחות={success}"
    )
    if extra:
        base += f" | {extra}"
    return base

def _update_progress(slot, extra=""):
    total = TRAINING_STATE["overall_total"]
    done = TRAINING_STATE["overall_done"]
    success = TRAINING_STATE["overall_success"]
    failed = TRAINING_STATE["overall_failed"]
    skipped = TRAINING_STATE["overall_skipped"]
    progress = 0 if total <= 0 else int((done / total) * 100)
    
    write_status(
        state="running",
        progress=progress,
        message=_status_message_for_sector(
            slot, done, total, success, failed, skipped, extra=extra
        ),
        sector=slot,
    )

def _prepare_training_frame(all_features):
    data = pd.DataFrame(all_features)
    if data.empty:
        return None, None, None, []

    if "label" not in data.columns:
        return None, None, None, []

    drop_cols = [c for c in ["label", "ticker", "entry_date", "exit_date"] if c in data.columns]
    X = data.drop(columns=drop_cols, errors="ignore")
    y = data["label"].astype(int)

    X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    for col in X.columns:
        if not pd.api.types.is_numeric_dtype(X[col]):
            X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0.0)

    nunique = X.nunique(dropna=False)
    keep_cols = nunique[nunique > 1].index.tolist()
    excluded_cols = [c for c in X.columns if c not in keep_cols]
    
    if keep_cols:
        X = X[keep_cols]

    return data, X, y, excluded_cols

def process_sector(slot, tickers, base_threshold=50):
    TRAINING_STATE["current_sector"] = slot
    tickers = _dedupe_keep_order(tickers or [])

    if not tickers:
        log_message(f"Sector {slot} is empty after dedupe. Skipping.")
        return

    log_message(f"Starting advanced Wyckoff training for {slot} with {len(tickers)} tickers.")
    _update_progress(slot, extra=f"מתחיל אצווה עם {len(tickers)} נכסים")

    all_features = []
    sector_success = 0
    sector_failed = 0
    sector_skipped = 0

    for i, ticker in enumerate(tickers, start=1):
        TRAINING_STATE["overall_done"] += 1
        try:
            df, audit_df = run_wyckoff_anchored_backtest(
                ticker,
                use_ai=False,
                threshold=base_threshold,
                period=TRAINING_PERIOD,
                atr_multiplier=2.5,
            )

            if df is None or getattr(df, "empty", True):
                sector_skipped += 1
                TRAINING_STATE["overall_skipped"] += 1
                _update_progress(slot, extra=f"{ticker} ללא דאטה")
                continue

            if audit_df is None or getattr(audit_df, "empty", True):
                sector_skipped += 1
                TRAINING_STATE["overall_skipped"] += 1
                _update_progress(slot, extra=f"{ticker} ללא עסקאות")
                continue

            engine = FactorEngine(BacktestConfig(period=TRAINING_PERIOD))
            factors = engine.compute(df)

            if factors is None or getattr(factors, "empty", True):
                sector_skipped += 1
                TRAINING_STATE["overall_skipped"] += 1
                _update_progress(slot, extra=f"{ticker} factors ריקים")
                continue

            factors = _normalize_factor_index(factors)

            matched_rows = 0
            for _, row in audit_df.iterrows():
                entry_date = _normalize_timestamp(row.get("entry_date"))
                if entry_date is None or entry_date not in factors.index:
                    continue

                feat = factors.loc[entry_date].to_dict()
                feat["label"] = 1 if bool(row.get("win")) else 0
                feat["ticker"] = ticker
                if "exit_date" in row.index:
                    feat["exit_date"] = row.get("exit_date")
                feat["entry_date"] = row.get("entry_date")
                all_features.append(feat)
                matched_rows += 1

            if matched_rows > 0:
                sector_success += 1
                TRAINING_STATE["overall_success"] += 1
            else:
                sector_skipped += 1
                TRAINING_STATE["overall_skipped"] += 1

            _update_progress(
                slot,
                extra=f"{ticker} עובד | עסקאות מותאמות={matched_rows} | סה\"כ פיצ'רים={len(all_features)}",
            )

        except Exception as e:
            sector_failed += 1
            TRAINING_STATE["overall_failed"] += 1
            log_exception(f"Error on {ticker}", e)
            _update_progress(slot, extra=f"שגיאה ב-{ticker}")

        finally:
            try: del df
            except Exception: pass
            try: del audit_df
            except Exception: pass
            try: del factors
            except Exception: pass
            gc.collect()

        if i % 5 == 0:
            _update_progress(
                slot,
                extra=f"checkpoint {i}/{len(tickers)} | הצלחות={sector_success} | שגיאות={sector_failed}",
            )

    if len(all_features) < MIN_TRADES_FOR_ML:
        msg = (
            f"Not enough trades for {slot} (Found: {len(all_features)}). "
            f"Need at least {MIN_TRADES_FOR_ML} for ML."
        )
        log_message(msg)
        _update_progress(slot, extra=msg)
        return

    data, X, y, excluded_cols = _prepare_training_frame(all_features)
    if data is None or X is None or y is None or X.empty:
        log_message(f"{slot}: prepared dataset is empty after cleanup.")
        _update_progress(slot, extra="dataset ריק אחרי ניקוי")
        return

    excluded_dict = {}
    for col in excluded_cols:
        msg = f"WARNING: feature '{col}' has near-zero variance (unique <= 1). Likely uninformative. Removing from training."
        log_message(msg)
        excluded_dict[col] = "Zero/near-zero variance (nunique <= 1)"

    for col in X.columns:
        try:
            unique_vals = X[col].nunique()
            if unique_vals < 2:
                val_std = X[col].std() if pd.api.types.is_numeric_dtype(X[col]) else 0.0
                log_message(f"WARNING: feature '{col}' has near-zero variance (std={val_std:.4f}, unique={unique_vals}) — likely uninformative.")
        except Exception:
            pass

    if y.nunique(dropna=True) < 2:
        log_message(f"{slot}: not enough class variety to train (labels={y.nunique(dropna=True)}).")
        _update_progress(slot, extra="אין מספיק גיוון בתוויות לאימון")
        return

    model = RandomForestClassifier(
        n_estimators=100,
        max_depth=4, 
        min_samples_split=20,
        min_samples_leaf=10, 
        random_state=42,
        class_weight="balanced",
        n_jobs=-1,
        oob_score=True,
        bootstrap=True
    )

    try:
        model.fit(X, y)
    except Exception as e:
        log_exception(f"Model fit failed for {slot}", e)
        _update_progress(slot, extra="כשל באימון המודל")
        return

    try:
        train_acc = float(model.score(X, y))
    except Exception:
        train_acc = float("nan")
        
    try:
        oob_acc = float(model.oob_score_)
    except Exception:
        oob_acc = float("nan")

    try:
        preds = model.predict(X)
        cm = confusion_matrix(y, preds)
        log_message(f"Confusion Matrix for {slot}: TN={cm[0][0]}, FP={cm[0][1]}, FN={cm[1][0]}, TP={cm[1][1]}")
    except Exception:
        pass

    try:
        opt_th = calculate_optimal_threshold(model, X, y)
    except Exception as e:
        log_exception(f"Threshold calculation failed for {slot}", e)
        opt_th = 0.5
        
    try:
        importances = model.feature_importances_
        feature_names = model.feature_names_in_
        sorted_idx = np.argsort(importances)[::-1]
        top_4_idx = sorted_idx[:4]
        top_features_str = ", ".join([f"{feature_names[i]} ({importances[i]:.1%})" for i in top_4_idx])
        log_message(f"Top 4 Features for {slot}: {top_features_str}")
    except Exception as e:
        log_exception("Failed to extract top features", e)

    safe_slot = clean_filename(slot)
    model_path = os.path.join(MODEL_DIR, f"model_{safe_slot}.pkl")

    payload = {
        "model": model,
        "metadata": {
            "slot": slot,
            "train_acc": train_acc,
            "oob_acc": oob_acc,
            "num_trades": int(len(data)),
            "num_features": int(X.shape[1]),
            "excluded_features": excluded_dict,
            "recommended_threshold": float(opt_th),
            "period": TRAINING_PERIOD,
            "base_threshold": base_threshold,
            "ticker_count": int(len(tickers)),
            "sector_success": int(sector_success),
            "sector_failed": int(sector_failed),
            "sector_skipped": int(sector_skipped),
            "timestamp": datetime.now().isoformat(),
        },
    }

    try:
        with open(model_path, "wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as e:
        log_exception(f"Failed to save model for {slot}", e)
        _update_progress(slot, extra="כשל בשמירת המודל")
        return

    log_message(
        f"Successfully trained {slot}. Trades: {len(data)}, "
        f"Acc: {train_acc:.2%}, OOB Acc: {oob_acc:.2%}. Model saved to {model_path}."
    )
    _update_progress(
        slot,
        extra=f"הושלם | עסקאות={len(data)} | דיוק={train_acc:.2%} | threshold={opt_th:.3f}",
    )

    try: del data, X, y, model, payload, all_features
    except Exception: pass
    gc.collect()

def _build_sector_map_from_universe():
    covered = []
    ordered_buckets = []

    for sector_name in [
        "Tech", "Growth", "Value", "Healthcare", "Financials",
        "Energy", "Consumer", "Industrials", "MidCaps", "Defensive"
    ]:
        tickers = _dedupe_keep_order(SECTOR_BUCKETS.get(sector_name, []))
        ordered_buckets.append((sector_name, tickers))
        covered.extend(tickers)

    covered = set(_dedupe_keep_order(covered))
    missing = [t for t in UNIVERSE_TICKERS if t not in covered]
    if missing:
        ordered_buckets.append(("Misc", missing))

    return ordered_buckets

if __name__ == "__main__":
    try:
        _ensure_dirs()
        
        if _SCOUT_IMPORT_ERROR:
            write_status(
                state="error",
                progress=0,
                message=f"שגיאה קריטית: ייבוא scout_core נכשל ({_SCOUT_IMPORT_ERROR})",
                universe_size=0,
                training_period=TRAINING_PERIOD,
            )
            sys.exit(1)
            
        sector_map = apply_custom_batch()
        if not sector_map:
            sector_map = _build_sector_map_from_universe()
            TRAINING_STATE["overall_total"] = len(UNIVERSE_TICKERS)

        write_status(
            state="running",
            progress=0,
            message=f"מתחיל אימון Wyckoff מקיף ({TRAINING_PERIOD}) על {TRAINING_STATE['overall_total']} נכסים...",
            universe_size=TRAINING_STATE["overall_total"],
            training_period=TRAINING_PERIOD,
        )

        log_message("============================================================")
        log_message("=== auto_trainer_fixed.py STARTED ===")
        log_message(f"Execution Target Size: {TRAINING_STATE['overall_total']} tickers")
        log_message(f"Training period: {TRAINING_PERIOD}")

        total_sectors = len(sector_map)

        for idx, (name, ticks) in enumerate(sector_map, start=1):
            if not ticks:
                continue

            overall_progress = 0 if total_sectors <= 0 else int(((idx - 1) / total_sectors) * 100)
            write_status(
                state="running",
                progress=overall_progress,
                message=f"מעבד אצווה {name} ({idx}/{total_sectors}) עם {len(ticks)} נכסים...",
                current_sector=name,
                universe_size=TRAINING_STATE["overall_total"],
                training_period=TRAINING_PERIOD,
            )

            log_message(f"Processing bucket {name} [{idx}/{total_sectors}] with {len(ticks)} tickers.")
            process_sector(name, ticks, base_threshold=BASE_THRESHOLD)

            gc.collect()

        if TRAINING_STATE["overall_success"] == 0:
            error_msg = "האימון הסתיים ללא נתונים תקינים או ללא עסקאות מותאמות לאף נכס (0 הצלחות). המודלים לא נוצרו."
            log_message(f"ERROR: {error_msg}")
            write_status(
                state="error",
                progress=100,
                message=error_msg,
                universe_size=TRAINING_STATE["overall_total"],
                training_period=TRAINING_PERIOD,
            )
            sys.exit(1) 

        with open(DONE_FLAG, "w", encoding="utf-8") as f:
            f.write("done")

        write_status(
            state="completed",
            progress=100,
            message="הריצה הושלמה בהצלחה. כל המודלים נשמרו.",
            universe_size=TRAINING_STATE["overall_total"],
            training_period=TRAINING_PERIOD,
        )
        log_message("=== auto_trainer_fixed.py COMPLETED SUCCESSFULLY ===")

    except Exception as e:
        log_exception("Fatal training error", e)
        write_status(
            state="error",
            progress=0,
            message=f"שגיאה קריטית באימון: {e}",
            universe_size=TRAINING_STATE.get("overall_total", 0),
            training_period=TRAINING_PERIOD,
        )
        sys.exit(1)
