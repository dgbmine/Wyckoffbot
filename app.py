# ============================================================
# INSTITUTIONAL SCOUT PRO — CLOUD RUN EDITION V12.0
# Streamlit app for Wyckoff-style market analysis
# Optimized for Google Cloud Run (port 8080, structured logging,
# subprocess safety, memory management, session hygiene)
# ============================================================

from __future__ import annotations

import json
import logging
import math
import os
import pickle
import signal
import subprocess
import sys
import time
import traceback
import gc
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder

# ============================================================
# Structured logging (Cloud Run → Cloud Logging compatible)
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='{"time": "%(asctime)s", "level": "%(levelname)s", "msg": "%(message)s"}',
    stream=sys.stdout,
)
logger = logging.getLogger("scout")

# ============================================================
# Base paths / environment
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# Cloud Run: use /tmp for ephemeral writable storage
_CLOUD_RUN = os.environ.get("K_SERVICE") is not None or os.environ.get("CLOUD_RUN", "").lower() == "true"
_TMP_ROOT = "/tmp/scout" if _CLOUD_RUN else BASE_DIR

MODEL_DIR = os.path.join(_TMP_ROOT, "models")
BATCH_CONFIG_FILE = os.path.join(MODEL_DIR, "batch_config.json")
AUTO_TRAINER_STATUS_FILE = os.path.join(MODEL_DIR, "auto_trainer_status.json")
AUTO_TRAINER_DONE_FLAG = os.path.join(MODEL_DIR, "auto_trainer.done")
AUTO_TRAINER_LOG_FILE = os.path.join(_TMP_ROOT, "auto_trainer_error.log")
AUTO_TRAINER_PID_FILE = os.path.join(MODEL_DIR, "auto_trainer.pid")
AUTO_TRAINER_STOP_FILE = os.path.join(MODEL_DIR, "auto_trainer.stop")
AUTO_TRAINER_LOCK_FILE = os.path.join(MODEL_DIR, "auto_trainer.lock")

# Cloud Run port (Streamlit reads $PORT automatically via config, but we log it)
_PORT = int(os.environ.get("PORT", 8080))
logger.info("Scout starting on port %d | Cloud Run: %s", _PORT, _CLOUD_RUN)

# ============================================================
# Optional import from scout_core
# ============================================================

try:
    from scout_core import (
        clean_filename,
        get_data,
        calculate_optimal_threshold,
        check_phase_entry_allowed,
        BacktestConfig,
        FactorEngine,
        run_wyckoff_anchored_backtest,
        build_research_ground_truth,
    )
    SCOUT_CORE_AVAILABLE = True
    logger.info("scout_core loaded successfully")
except Exception as exc:
    SCOUT_CORE_AVAILABLE = False
    logger.warning("scout_core not available: %s — using stubs", exc)

    def clean_filename(name: str) -> str:
        keep = [ch for ch in str(name) if ch.isalnum() or ch in ("-", "_", ".")]
        return "".join(keep)[:120] or "model"

    @dataclass
    class BacktestConfig:
        lookback: int = 252
        min_bars: int = 60

    class FactorEngine:
        MIN_BARS_REQUIRED = 60

        def __init__(self, config: Optional[BacktestConfig] = None):
            self.config = config or BacktestConfig()

        def compute(self, df: pd.DataFrame) -> pd.DataFrame:
            if df is None or len(df) < self.MIN_BARS_REQUIRED:
                return pd.DataFrame()
            out = pd.DataFrame(index=df.index.copy())
            close = df["Close"].astype(float)
            volume = df["Volume"].astype(float)
            out["ret_1"] = close.pct_change().fillna(0)
            out["ret_5"] = close.pct_change(5).fillna(0)
            vol_mean = volume.rolling(20).mean()
            vol_std = volume.rolling(20).std().replace(0, np.nan)
            out["vol_z"] = ((volume - vol_mean) / vol_std).replace([np.inf, -np.inf], np.nan).fillna(0)
            out["range"] = ((df["High"] - df["Low"]) / close.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0)
            out["trend_20"] = (close / close.rolling(20).mean() - 1).fillna(0)
            out["trend_50"] = (close / close.rolling(50).mean() - 1).fillna(0)
            out["mom_14"] = close.diff(14).fillna(0)
            return out

        def get_wyckoff_phase(self, df: pd.DataFrame) -> pd.Series:
            close = df["Close"].astype(float)
            ma20 = close.rolling(20).mean()
            ma50 = close.rolling(50).mean()
            phase = pd.Series(index=df.index, dtype="object")
            phase[:] = "Neutral"
            phase[(close > ma20) & (ma20 > ma50)] = "Markup"
            phase[(close < ma20) & (ma20 < ma50)] = "Markdown"
            phase[(close < ma20) & (close > ma50)] = "Accumulation"
            phase[(close > ma20) & (close < ma50)] = "Distribution"
            return phase.fillna("Neutral")

        def composite_cis(self, factors: pd.DataFrame, df: pd.DataFrame) -> pd.Series:
            close = df["Close"].astype(float)
            vol = df["Volume"].astype(float).replace(0, np.nan)
            mom = close.pct_change(10).fillna(0)
            trend = (close / close.rolling(30).mean() - 1).fillna(0)
            vol_score = ((vol / vol.rolling(20).mean()) - 1).replace([np.inf, -np.inf], np.nan).fillna(0)
            score = 50 + 20 * np.tanh(3 * trend) + 15 * np.tanh(3 * mom) + 10 * np.tanh(vol_score)
            return score.clip(0, 100)

    def get_data(ticker: str, period: Optional[str] = "1y", start: Optional[str] = None, end: Optional[str] = None) -> Optional[pd.DataFrame]:
        try:
            t = yf.Ticker(ticker)
            if start or end:
                df = t.history(start=start, end=end)
            else:
                df = t.history(period=period or "1y")
            return df if (df is not None and not df.empty) else None
        except Exception as exc:
            logger.warning("get_data(%s) failed: %s", ticker, exc)
            return None

    def calculate_optimal_threshold(*args, **kwargs):
        return 65

    def check_phase_entry_allowed(*args, **kwargs):
        return True

    def run_wyckoff_anchored_backtest(*args, **kwargs):
        raise NotImplementedError("run_wyckoff_anchored_backtest only available in scout_core")

    def build_research_ground_truth(*args, **kwargs):
        return pd.DataFrame()

# ============================================================
# App config — must be first Streamlit call
# ============================================================

st.set_page_config(
    layout="wide",
    page_title="Institutional Scout Pro",
    page_icon="📈",
    initial_sidebar_state="expanded",
)

# ============================================================
# Universe definitions
# ============================================================

GROWTH_TICKERS = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","CRM","NFLX","AMD","ADBE","CSCO","TXN","QCOM","INTC","INTU","ADI",
    "PANW","CRWD","FTNT","ZS","DDOG","SNOW","MDB","NET","PLTR","UBER","ABNB","COIN","SOFI","UPST","ONTO","KLAC","LRCX","AMAT",
    "MRVL","SMCI","DELL","HPQ","RBLX","U","TTWO","EA","HUBS","TEAM","WDAY","OKTA","ZM","DOCU","DBX","BOX","ESTC","CFLT","PATH",
    "ASAN","GTLB","PD","VRNS","CYBR","CHKP","TWLO","PINS","SNAP","MTCH","BMBL","ROKU","SPOT","SE","MELI","SQ","AFRM","HOOD","TOST",
    "BILL","PAYC","PCTY","CDAY","WIX","AKAM","SHOP","GLBE","VEEV","ALGN","DXCM","PODD","TNDM","INSP","SWAV","LULU","CROX","YETI",
    "CHWY","ETSY","CVNA","Z","RDFN","OPEN","EXPE","TRIP","BKNG","EXAS","NTLA","CRSP","BEAM","TWST","ILMN","PACB","TXG","VRTX","BNTX",
    "MRNA","NVAX","ENPH","SEDG","FSLR","RUN","NOVA","PLUG","BLDP","FCEL","CHPT","EVGO","LAZR","QS","JOBY","ACHR","RKLB","SPCE","MNMD",
    "MSTR",
]

VALUE_TICKERS = [
    "BRK-B","JPM","JNJ","V","UNH","PG","MA","HD","MRK","ABBV","PEP","KO","COST","WMT","LLY","TMO","MCD","ACN","BAC","ABT","DHR","RTX",
    "HON","NKE","AMGN","PM","IBM","SBUX","GS","CAT","BA","GE","SPGI","AXP","BLK","DE","ISRG","MDLZ","GILD","REGN","SYK","ZTS","MMC",
    "AON","TJX","SCHW","CB","USB","WFC","C","MS","CVS","CI","AMT","PLD","CCI","EQIX","SPG","O","WELL","DLR","DIS","CMCSA","DAL","UAL",
    "AAL","LUV","FDX","UPS","XPO","ODFL","DKNG","MGM","CZR","RCL","CCL","MAR","HLT","PRU","MET","AFL","ALL","TRV","HIG","PGR","CINF",
    "WRB","LNC","PFG","RE","GL","AIZ","KEY","FITB","HBAN","RF","CFG","CMA","ZION","MTB","TFC","PNC","DFS","SYF","COF","ALLY","NTRS",
    "STT","BK","AMP","RJF","LPLA","MCO","NDAQ","ICE","CME","CBOE","EFX","TRU","FICO","VRSK","JCI","CARR","TT","ETN","EMR","ROK","PNR",
    "GGG","ITW","PH","DOV","IR","IEX","NDSN","WAB","LECO","AOS","GWW","URI","RBA","WCC","EME","FIX","PWR","BLDR","BECN","POOL","TSCO",
    "ORLY","AZO","AAP","GPC","LKQ","BBY","KMX","AN","LAD","GPI","ABG","PAG","SAH","KSS","M","JWN","DDS","GPS","AEO","URBN","ROST","BURL",
    "DG","DLTR","TGT","KR",
]

COMMODITIES_TICKERS = [
    "XOM","CVX","SLB","EOG","OXY","COP","PSX","VLO","FCX","NEM","GOLD","AEM","WPM","FNV","PAAS","AG","GLD","SLV","HAL","BKR","NOV",
    "DVN","FANG","CTRA","MRO","OVV","EQT","WMB","KMI","ET","EPD","MPLX","PAA","TRGP","OKE","LNG","DTM","VMC","MLM","EXP","ALB","SQM",
    "LAC","MP","CCJ","UUUU","UEC","NXE","BHP","RIO","VALE","CLF","X","STLD","NUE","RS","AA","CENX","CDE","HL","EXK","FSM","MAG","SSRM",
    "KGC","IAG","EGO","OR","RGLD","USAS","SILV","HMY","GFI","SBSW","HBM","FCG","URA","COPX","LIT","REMX","URNM","SILJ","GDXJ",
]

SECTOR_MAP: Dict[str, List[str]] = {
    "הכול (כל השוק האמריקאי)": sorted(list(set(GROWTH_TICKERS + VALUE_TICKERS + COMMODITIES_TICKERS))),
    "צמיחה וטכנולוגיה (Growth)": GROWTH_TICKERS,
    "ערך ומדד (Value/Index)": VALUE_TICKERS,
    "סחורות ואנרגיה (Commodities)": COMMODITIES_TICKERS,
}

# ============================================================
# Minimum trades constants
# ============================================================

MIN_TRADES_FOR_VALID_MODEL = 10  # below this → warn user
TRADES_FALLBACK_THRESHOLD = 35   # if config threshold yields 0 trades, retry here

# ============================================================
# Utilities
# ============================================================

def ensure_dirs() -> None:
    os.makedirs(MODEL_DIR, exist_ok=True)

def safe_now() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _is_pid_running(pid: Optional[int]) -> bool:
    if pid is None:
        return False
    try:
        pid = int(pid)
    except Exception:
        return False
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True, check=False,
            )
            return str(pid) in result.stdout
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists but we can't signal it
    except Exception:
        return False

def chunk_list(lst: List[str], num_chunks: int = 10) -> List[List[str]]:
    if not lst:
        return []
    chunk_size = max(1, math.ceil(len(lst) / max(1, num_chunks)))
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

def save_model_to_disk(slot_name: str, model: Any, metadata: Dict[str, Any], encoder: Any) -> str:
    ensure_dirs()
    safe_name = clean_filename(str(slot_name))
    file_path = os.path.join(MODEL_DIR, f"model_{safe_name}.pkl")
    payload = {"model": model, "metadata": metadata, "phase_encoder": encoder}
    tmp_path = file_path + ".tmp"
    try:
        with open(tmp_path, "wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp_path, file_path)  # atomic write
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    logger.info("Model saved: %s", file_path)
    return file_path

def load_all_models_from_disk() -> Dict[str, Dict[str, Any]]:
    ensure_dirs()
    loaded: Dict[str, Dict[str, Any]] = {}
    try:
        for filename in os.listdir(MODEL_DIR):
            if not (filename.startswith("model_") and filename.endswith(".pkl")):
                continue
            filepath = os.path.join(MODEL_DIR, filename)
            try:
                with open(filepath, "rb") as f:
                    data = pickle.load(f)
                slot = data.get("metadata", {}).get("slot") or filename.replace("model_", "").replace(".pkl", "")
                loaded[str(slot)] = data
            except Exception as exc:
                logger.warning("Could not load model %s: %s", filename, exc)
    except Exception as exc:
        logger.error("load_all_models_from_disk failed: %s", exc)
    return loaded

def read_auto_trainer_status() -> Dict[str, Any]:
    default: Dict[str, Any] = {
        "state": "idle",
        "message": "לא רץ כרגע",
        "progress": 0,
        "current_slot": "N/A",
        "updated_at": "N/A",
        "started_at": "N/A",
        "finished_at": "N/A",
        "pid": "N/A",
    }
    try:
        if os.path.exists(AUTO_TRAINER_STATUS_FILE):
            with open(AUTO_TRAINER_STATUS_FILE, "r", encoding="utf-8") as f:
                default.update(json.load(f))
        elif os.path.exists(AUTO_TRAINER_DONE_FLAG):
            default.update({"state": "completed", "message": "האימון הסתיים", "progress": 100})
    except Exception as exc:
        logger.warning("read_auto_trainer_status failed: %s", exc)
    return default

def read_trainer_pid() -> Optional[int]:
    if not os.path.exists(AUTO_TRAINER_PID_FILE):
        return None
    try:
        with open(AUTO_TRAINER_PID_FILE, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
    except Exception:
        return None
    if _is_pid_running(pid):
        return pid
    try:
        os.remove(AUTO_TRAINER_PID_FILE)
    except Exception:
        pass
    return None

def write_trainer_pid(pid: int) -> None:
    ensure_dirs()
    with open(AUTO_TRAINER_PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(int(pid)))

def write_stop_request() -> None:
    ensure_dirs()
    try:
        with open(AUTO_TRAINER_STOP_FILE, "w", encoding="utf-8") as f:
            json.dump({"requested_at": safe_now()}, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.error("write_stop_request failed: %s", exc)

def cleanup_stale_trainer_artifacts() -> None:
    pid = read_trainer_pid()
    if pid is None:
        for path in (AUTO_TRAINER_STOP_FILE, AUTO_TRAINER_LOCK_FILE):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

def is_trainer_running() -> bool:
    cleanup_stale_trainer_artifacts()
    status = read_auto_trainer_status()
    pid = read_trainer_pid()
    return status.get("state") in {"running", "locked", "stopping"} or pid is not None

def _hunt_for_trainer() -> str:
    target_name = "auto_trainer_fixed.py"
    primary = os.path.join(BASE_DIR, target_name)
    if os.path.isfile(primary):
        return primary
    cwd_candidate = os.path.join(os.getcwd(), target_name)
    if os.path.isfile(cwd_candidate):
        return cwd_candidate
    for root, _dirs, files in os.walk(BASE_DIR):
        if root[len(BASE_DIR):].count(os.sep) > 3:
            continue
        if target_name in files:
            return os.path.join(root, target_name)
    return primary

TRAINER_SCRIPT = _hunt_for_trainer()
TRAINER_AVAILABLE = os.path.isfile(TRAINER_SCRIPT)

def start_trainer_process() -> int:
    if not TRAINER_AVAILABLE:
        raise FileNotFoundError(f"קובץ הטריינר לא נמצא: {TRAINER_SCRIPT}")
    if is_trainer_running():
        raise RuntimeError("האימון כבר רץ כרגע — עצור לפני שמתחיל מחדש")

    ensure_dirs()
    if os.path.exists(AUTO_TRAINER_STOP_FILE):
        try:
            os.remove(AUTO_TRAINER_STOP_FILE)
        except Exception:
            pass

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    # Pass Cloud Run context to child
    env["SCOUT_MODEL_DIR"] = MODEL_DIR
    env["SCOUT_MIN_TRADES"] = str(MIN_TRADES_FOR_VALID_MODEL)
    env["SCOUT_FALLBACK_THRESHOLD"] = str(TRADES_FALLBACK_THRESHOLD)

    log_handle = open(AUTO_TRAINER_LOG_FILE, "a", encoding="utf-8")

    kwargs: Dict[str, Any] = {
        "cwd": os.path.dirname(TRAINER_SCRIPT),
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
        "env": env,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True  # detach from Streamlit's process group

    try:
        proc = subprocess.Popen([sys.executable, TRAINER_SCRIPT], **kwargs)
    except Exception as exc:
        log_handle.close()
        raise RuntimeError(f"לא ניתן להפעיל את הטריינר: {exc}") from exc

    write_trainer_pid(proc.pid)
    logger.info("Trainer started: PID %d", proc.pid)
    return int(proc.pid)

def stop_trainer_process(grace_seconds: int = 8) -> bool:
    pid = read_trainer_pid()
    write_stop_request()

    if pid is None:
        cleanup_stale_trainer_artifacts()
        return True

    # Soft signal first
    try:
        sig = signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM
        os.kill(int(pid), sig)
    except Exception as exc:
        logger.warning("Could not send soft signal to PID %d: %s", pid, exc)

    deadline = time.monotonic() + float(grace_seconds)
    while time.monotonic() < deadline:
        if not _is_pid_running(pid):
            break
        time.sleep(0.3)

    # Hard kill if still alive
    if _is_pid_running(pid):
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                )
            else:
                os.kill(int(pid), signal.SIGKILL)
        except Exception as exc:
            logger.warning("Hard kill failed for PID %d: %s", pid, exc)

    try:
        os.remove(AUTO_TRAINER_PID_FILE)
    except Exception:
        pass

    cleanup_stale_trainer_artifacts()
    logger.info("Trainer stopped (was PID %d)", pid)
    return True

def clear_trainer_artifacts() -> None:
    for path in [
        AUTO_TRAINER_STATUS_FILE,
        AUTO_TRAINER_DONE_FLAG,
        AUTO_TRAINER_LOG_FILE,
        AUTO_TRAINER_PID_FILE,
        AUTO_TRAINER_STOP_FILE,
        AUTO_TRAINER_LOCK_FILE,
    ]:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

def validate_trade_count(num_trades: int, slot_name: str) -> Tuple[bool, str]:
    """
    Returns (is_valid, message).
    Catches the '0 trades' training failure early with actionable guidance.
    """
    if num_trades == 0:
        return False, (
            f"❌ [{slot_name}] האימון הניב 0 עסקאות — "
            "ייתכן שרף ה-CIS גבוה מדי, תקופת הנתונים קצרה מדי, "
            f"או שאין נתוני מחיר תקינים. "
            f"מומלץ: הנמך את ה-threshold ל-{TRADES_FALLBACK_THRESHOLD} ונסה שוב."
        )
    if num_trades < MIN_TRADES_FOR_VALID_MODEL:
        return True, (
            f"⚠️ [{slot_name}] נמצאו רק {num_trades} עסקאות — "
            f"המינימום המומלץ הוא {MIN_TRADES_FOR_VALID_MODEL}. "
            "המודל נשמר אך האמינות נמוכה. שקול להרחיב את תקופת הנתונים או להוסיף מניות."
        )
    return True, f"✅ [{slot_name}] נמצאו {num_trades} עסקאות — אימון תקין."

# ============================================================
# Session state
# ============================================================

_SESSION_DEFAULTS: Dict[str, Any] = {
    "mode": "wyckoff",
    "ml_model": None,
    "ml_metadata": None,
    "use_ml": False,
    "phase_encoder": None,
    "model_archive": None,  # lazy-loaded
    "selected_universe": "הכול (כל השוק האמריקאי)",
    "wyckoff_ticker": "NVDA",
    "backtest_ticker": "COST",
    "scanner_limit": 20,
    "scanner_sector": "צמיחה וטכנולוגיה (Growth)",
    "risk_profile": "Balanced",
    "bt_threshold": 65,
    "scan_threshold": 65,
    "threshold_sync": True,
    "threshold_value": 65,
}

def init_session_state() -> None:
    for k, v in _SESSION_DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v
    # Lazy model archive load
    if st.session_state.model_archive is None:
        st.session_state.model_archive = load_all_models_from_disk()

def _gc_collect() -> None:
    """Explicit GC call to keep Cloud Run memory bounded after heavy operations."""
    gc.collect()

# ============================================================
# CSS / Theme
# ============================================================

def inject_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Hebrew:wght@300;400;500;600;700&display=swap');

        html, body, [class*="css"] {
            font-family: 'IBM Plex Sans Hebrew', sans-serif;
            direction: rtl;
            text-align: right;
            background: #0b1220;
            color: #d9e6f2;
        }

        .stApp {
            background:
                radial-gradient(circle at top left, rgba(38,166,154,0.08), transparent 28%),
                radial-gradient(circle at top right, rgba(59,130,246,0.08), transparent 25%),
                linear-gradient(180deg, #0b1220 0%, #0f172a 100%);
            color: #d9e6f2;
        }

        .main-header {
            padding: 1.15rem 1.4rem;
            border-radius: 22px;
            border: 1px solid rgba(125,155,190,0.22);
            background: linear-gradient(135deg, rgba(7,14,25,0.88), rgba(13,25,43,0.92));
            box-shadow: 0 18px 44px rgba(0,0,0,.28);
            margin-bottom: 1rem;
        }
        .main-header h1 { margin: 0; font-size: 2.0rem; line-height: 1.1; color: #eaf4ff; }
        .main-header p  { margin: 0.35rem 0 0; color: #9db0c9; font-size: 0.95rem; }

        .glass-card {
            background: rgba(10,18,33,0.85);
            border: 1px solid rgba(125,155,190,0.18);
            border-radius: 20px;
            padding: 1rem 1.1rem;
            box-shadow: 0 14px 30px rgba(0,0,0,.22);
        }

        .section-title { font-size: 1.15rem; font-weight: 700; color: #eaf4ff; margin-bottom: 0.4rem; }
        .section-subtitle { color: #9db0c9; margin-bottom: 0.8rem; line-height: 1.7; }

        .metric-box {
            background: linear-gradient(180deg, rgba(14,24,42,0.94), rgba(10,18,33,0.96));
            border: 1px solid rgba(76,129,189,0.20);
            border-radius: 16px;
            padding: 0.8rem 0.9rem;
        }

        .audit-row {
            padding: 0.85rem 0.95rem;
            margin-bottom: 0.55rem;
            border-radius: 14px;
            border-right: 4px solid;
            background: rgba(15,23,42,0.65);
        }
        .win  { border-color: #26a69a; }
        .loss { border-color: #ef5350; }

        .widget-panel-ai {
            background: rgba(10,18,33,0.92);
            border: 1px solid rgba(76,129,189,0.2);
            border-radius: 18px;
            padding: 1rem 1rem 0.2rem;
            margin-bottom: 1rem;
        }

        .mini-hint { color: #9db0c9; font-size: 0.88rem; }

        .stMetric {
            background: rgba(10,18,33,0.88);
            border: 1px solid rgba(125,155,190,0.15);
            border-radius: 16px;
            padding: 0.75rem 0.9rem;
            box-shadow: 0 10px 25px rgba(0,0,0,.18);
        }

        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, rgba(9,16,29,0.98), rgba(7,11,21,0.98));
            border-left: 1px solid rgba(125,155,190,0.14);
        }

        .stTabs [data-baseweb="tab-list"] {
            gap: 0.35rem;
            background: rgba(8,14,26,0.7);
            padding: 0.3rem;
            border-radius: 16px;
            border: 1px solid rgba(125,155,190,0.12);
        }
        .stTabs [data-baseweb="tab"] {
            height: 3rem;
            border-radius: 12px;
            padding: 0 1rem;
            background: transparent;
        }
        .stTabs [aria-selected="true"] { background: rgba(37,99,235,0.18) !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

# ============================================================
# Data cache — TTL=1h, max 64 entries to cap Cloud Run memory
# ============================================================

@st.cache_data(ttl=3600, max_entries=64, show_spinner=False)
def get_cached_data(
    ticker: str,
    period: str = "1y",
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    try:
        effective_period = None if (start or end) else period
        df = get_data(ticker, effective_period, start, end)
        if df is not None and not df.empty:
            return df
    except Exception as exc:
        logger.warning("get_cached_data primary failed for %s: %s", ticker, exc)

    # Fallback: direct yfinance
    try:
        t = yf.Ticker(ticker)
        df = t.history(start=start, end=end) if (start or end) else t.history(period=period or "1y")
        if df is not None and not df.empty:
            return df
    except Exception as exc:
        logger.warning("get_cached_data fallback failed for %s: %s", ticker, exc)
    return None

# ============================================================
# Threshold helpers
# ============================================================

def sync_threshold_from_slider(prefix: str) -> None:
    st.session_state[f"{prefix}_number"] = int(st.session_state[f"{prefix}_slider"])

def sync_threshold_from_number(prefix: str) -> None:
    st.session_state[f"{prefix}_slider"] = int(st.session_state[f"{prefix}_number"])

def render_threshold_control(label: str, key_prefix: str, min_value: int = 40, max_value: int = 95) -> int:
    if f"{key_prefix}_slider" not in st.session_state:
        st.session_state[f"{key_prefix}_slider"] = int(st.session_state.get(key_prefix, 65))
    if f"{key_prefix}_number" not in st.session_state:
        st.session_state[f"{key_prefix}_number"] = int(st.session_state.get(key_prefix, 65))

    st.markdown(f"**{label}**")
    c1, c2 = st.columns([4, 1], vertical_alignment="center")
    with c1:
        st.slider(
            "",
            min_value=min_value,
            max_value=max_value,
            value=int(st.session_state[f"{key_prefix}_slider"]),
            key=f"{key_prefix}_slider",
            label_visibility="collapsed",
            on_change=sync_threshold_from_slider,
            args=(key_prefix,),
        )
    with c2:
        st.number_input(
            "",
            min_value=min_value,
            max_value=max_value,
            value=int(st.session_state[f"{key_prefix}_number"]),
            key=f"{key_prefix}_number",
            label_visibility="collapsed",
            on_change=sync_threshold_from_number,
            args=(key_prefix,),
        )
    st.session_state[key_prefix] = int(st.session_state[f"{key_prefix}_slider"])
    return int(st.session_state[key_prefix])

# ============================================================
# Visual helpers
# ============================================================

def build_gauge(value: float, title: str = "CIS Score") -> go.Figure:
    value = float(np.clip(value, 0, 100))
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=value,
            number={"suffix": "/100", "font": {"size": 28}},
            title={"text": title, "font": {"size": 18}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "#9db0c9"},
                "bar": {"color": "#26a69a"},
                "bgcolor": "rgba(0,0,0,0)",
                "borderwidth": 2,
                "bordercolor": "rgba(125,155,190,0.18)",
                "steps": [
                    {"range": [0, 35],  "color": "rgba(239,83,80,0.22)"},
                    {"range": [35, 65], "color": "rgba(255,193,7,0.22)"},
                    {"range": [65, 100],"color": "rgba(38,166,154,0.22)"},
                ],
                "threshold": {"line": {"color": "#7dd3fc", "width": 4}, "thickness": 0.75, "value": value},
            },
        )
    )
    fig.update_layout(
        height=310,
        margin=dict(l=20, r=20, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#d9e6f2"},
    )
    return fig

def render_header(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="main-header"><h1>{title}</h1><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )

def render_info_banner() -> None:
    if st.session_state.use_ml and st.session_state.ml_model is not None:
        metadata = st.session_state.ml_metadata or {}
        acc = metadata.get("test_acc", metadata.get("train_acc", 0.0))
        rec_th = metadata.get("recommended_threshold", "לא חושב")
        tr_count = metadata.get("num_trades", "?")
        # Surface zero-trades warning even in the banner
        if isinstance(tr_count, int) and tr_count == 0:
            st.error("⚠️ המודל הפעיל אומן על 0 עסקאות — התוצאות לא אמינות!")
        else:
            st.info(
                f"🧠 מצב AI פעיל: {metadata.get('slot', 'כללי')} | "
                f"דיוק OOB: {float(acc) * 100:.1f}% | "
                f"סף מומלץ: {rec_th} | אימון על {tr_count} עסקאות"
            )

def render_active_ai_selector_widget(screen_identifier: str) -> None:
    with st.container(border=False):
        st.markdown('<div class="widget-panel-ai">', unsafe_allow_html=True)
        st.markdown("### 🧠 הגדרות מנוע החלטה")
        col_a, col_b, col_c = st.columns([2, 1.5, 1], vertical_alignment="bottom")

        with col_a:
            archive = st.session_state.model_archive or {}
            if archive:
                slots_list = list(archive.keys())
                selected_slot = st.selectbox(
                    "בחר מודל מוסדי פעיל",
                    slots_list,
                    key=f"selector_slot_{screen_identifier}",
                )
                if st.button("✅ טען והפעל מודל", key=f"activate_btn_{screen_identifier}", use_container_width=True):
                    target_data = archive[selected_slot]
                    meta = target_data.get("metadata", {})
                    num_trades = meta.get("num_trades", -1)
                    # Validate trade count before activating
                    if isinstance(num_trades, int):
                        valid, msg = validate_trade_count(num_trades, selected_slot)
                        if not valid:
                            st.error(msg)
                        else:
                            if num_trades < MIN_TRADES_FOR_VALID_MODEL:
                                st.warning(msg)
                            st.session_state.ml_model = target_data["model"]
                            st.session_state.ml_metadata = meta
                            st.session_state.phase_encoder = target_data.get("phase_encoder")
                            st.session_state.use_ml = True
                            st.success(f"המודל '{selected_slot}' הופעל בהצלחה")
                            st.rerun()
                    else:
                        # No trade count metadata — load anyway with warning
                        st.session_state.ml_model = target_data["model"]
                        st.session_state.ml_metadata = meta
                        st.session_state.phase_encoder = target_data.get("phase_encoder")
                        st.session_state.use_ml = True
                        st.warning("המודל נטען, אך אין מידע על מספר עסקאות האימון.")
                        st.rerun()
            else:
                st.info("לא נמצאו מודלים. הרץ אימון מהמסך הייעודי.")

        with col_b:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🔄 רענן מודלים", key=f"sync_models_{screen_identifier}", use_container_width=True):
                st.session_state.model_archive = load_all_models_from_disk()
                st.rerun()

        with col_c:
            st.markdown("<br>", unsafe_allow_html=True)
            ai_toggle = st.checkbox(
                "הפעל AI",
                value=st.session_state.use_ml,
                key=f"checkbox_ai_{screen_identifier}",
            )
            if ai_toggle != st.session_state.use_ml:
                st.session_state.use_ml = ai_toggle
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

def render_trainer_control_panel() -> None:
    cleanup_stale_trainer_artifacts()
    status = read_auto_trainer_status()
    pid = read_trainer_pid()
    running = is_trainer_running()

    st.markdown("### 🚦 Auto-Trainer Control")

    # Zero-trades alert from last run
    last_trades = status.get("num_trades")
    if last_trades is not None:
        try:
            last_trades = int(last_trades)
            if last_trades == 0:
                st.error(
                    f"⛔ הריצה האחרונה הניבה 0 עסקאות — "
                    f"הנמך את ה-threshold ל-{TRADES_FALLBACK_THRESHOLD} ונסה שוב, "
                    "או הרחב את תקופת הנתונים."
                )
            elif last_trades < MIN_TRADES_FOR_VALID_MODEL:
                st.warning(f"⚠️ הריצה האחרונה: {last_trades} עסקאות (מינימום מומלץ: {MIN_TRADES_FOR_VALID_MODEL})")
        except Exception:
            pass

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("מצב", str(status.get("state", "idle")))
    c2.metric("התקדמות", f"{status.get('progress', 0)}%")
    c3.metric("PID", str(pid) if pid is not None else str(status.get("pid", "N/A")))
    c4.metric("סקטור נוכחי", str(status.get("current_slot", "N/A")))

    b1, b2, b3 = st.columns([1.2, 1.2, 2])
    with b1:
        if st.button("🔄 רענן", use_container_width=True):
            st.rerun()
    with b2:
        if st.button("⏹ עצור אימון", type="secondary", use_container_width=True, disabled=not running):
            try:
                stop_trainer_process(grace_seconds=8)
                st.warning("נשלחה בקשת עצירה רכה — ממתין לסיום...")
                st.rerun()
            except Exception as exc:
                st.error(f"לא ניתן לעצור: {exc}")
    with b3:
        if status.get("state") in {"running", "stopping", "locked"}:
            st.warning(f"סטטוס נוכחי: {status.get('message', '')}")

    with st.expander("📝 יומן ריצה ושגיאות", expanded=False):
        if os.path.exists(AUTO_TRAINER_LOG_FILE):
            try:
                with open(AUTO_TRAINER_LOG_FILE, "r", encoding="utf-8") as f:
                    logs = f.read()
                st.text_area("log_area", logs[-8000:], height=320, label_visibility="collapsed")
                if st.button("🗑️ נקה יומן"):
                    open(AUTO_TRAINER_LOG_FILE, "w").close()
                    st.rerun()
            except Exception as exc:
                st.warning(f"שגיאה בקריאת הלוג: {exc}")
        else:
            st.info("אין נתונים ביומן.")

# ============================================================
# Screens
# ============================================================

def screen_wyckoff() -> None:
    st.markdown("### ⬛ Wyckoff Structural Engine")
    st.caption("ניתוח מבני, ציון Composite, והצגת שעון מוסדי מקצועי.")
    render_active_ai_selector_widget("wyckoff")

    col1, col2 = st.columns([3, 1], vertical_alignment="bottom")
    with col1:
        ticker = st.text_input("Ticker לניתוח", value=st.session_state.wyckoff_ticker, key="wyckoff_ticker")
    with col2:
        run_btn = st.button("▶ הרץ ניתוח", use_container_width=True, type="primary")

    left, right = st.columns([1.15, 1], vertical_alignment="top")

    if run_btn:
        ticker = ticker.strip().upper()
        with st.spinner("מחשב FactorEngine..."):
            df = get_cached_data(ticker)
            if df is None or df.empty:
                st.error(f"אין נתונים זמינים עבור '{ticker}' — בדוק את ה-Ticker.")
                return
            try:
                engine = FactorEngine(BacktestConfig())
                factors = engine.compute(df)
                if factors is None or factors.empty:
                    st.warning(f"המנוע לא הצליח לחשב פקטורים עבור '{ticker}' — ייתכן שיש פחות מ-60 שורות נתון.")
                    return
                phases = engine.get_wyckoff_phase(df)
                cis = engine.composite_cis(factors, df)
                if cis is None or len(cis) == 0:
                    st.warning("לא התקבל ציון CIS תקין.")
                    return

                current_phase = str(phases.iloc[-1])
                current_cis = float(cis.iloc[-1])
                allowed = check_phase_entry_allowed(current_phase, current_cis) if callable(check_phase_entry_allowed) else True

                with left:
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Ticker", ticker)
                    m2.metric("Phase", current_phase)
                    m3.metric("Entry Allowed", "כן" if allowed else "לא")
                    st.plotly_chart(build_gauge(current_cis, "Composite Institutional Score"), use_container_width=True)

                with right:
                    st.markdown("### מדדי מצב")
                    st.metric("Composite CIS", f"{current_cis:.1f}")
                    st.metric("Bars", len(df))
                    st.metric("Last Close", f"{float(df['Close'].iloc[-1]):.2f}")
                    st.metric("Vol", f"{float(df['Volume'].iloc[-1]):,.0f}")

                st.markdown("### נתוני פקטורים אחרונים")
                st.dataframe(factors.tail(12).copy(), use_container_width=True)

                st.markdown("### Price Snapshot")
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df.index, y=df["Close"], name="Close"))
                if "Volume" in df.columns:
                    close_max = df["Close"].max()
                    vol_scaled = df["Volume"] / df["Volume"].max() * close_max
                    fig.add_trace(go.Scatter(x=df.index, y=vol_scaled, name="Volume (scaled)", line=dict(dash="dot")))
                fig.update_layout(
                    height=420,
                    margin=dict(l=0, r=0, t=25, b=0),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#d9e6f2"),
                    legend=dict(orientation="h"),
                )
                st.plotly_chart(fig, use_container_width=True)
                _gc_collect()
            except Exception as exc:
                logger.error("screen_wyckoff error: %s", exc, exc_info=True)
                st.error(f"שגיאה בחישוב המנוע: {exc}")
                st.code(traceback.format_exc())

def screen_backtest() -> None:
    st.markdown("### 📊 Wyckoff-Anchored Backtest")
    st.caption("הרצת סימולציה היסטורית עם אפשרות ל-AI, Threshold, וניתוח עסקאות.")
    render_active_ai_selector_widget("backtest")

    c1, c2, c3 = st.columns([2, 1.5, 1], vertical_alignment="bottom")
    with c1:
        ticker = st.text_input("Ticker לבדיקה", value=st.session_state.backtest_ticker, key="backtest_ticker")
    with c2:
        risk_profile = st.selectbox("Risk Profile", ["Aggressive", "Balanced", "Conservative"], index=1, key="risk_profile")
    with c3:
        bt_threshold = render_threshold_control("סף ציון CIS", "bt_threshold")

    if st.button("▶ הרץ סימולציה", use_container_width=True, type="primary"):
        ticker = ticker.strip().upper()
        with st.spinner("מריץ Backtest..."):
            bt_df, audit_df = None, None
            try:
                bt_df, audit_df = run_wyckoff_anchored_backtest(
                    ticker,
                    st.session_state.use_ml,
                    bt_threshold,
                    period="2y",
                    risk_profile=risk_profile,
                )
            except NotImplementedError:
                st.warning("run_wyckoff_anchored_backtest לא זמין כרגע ב-scout_core.")
                return
            except Exception as exc:
                logger.error("Backtest error for %s: %s", ticker, exc, exc_info=True)
                st.error(f"שגיאה בהרצת הבק-טסט: {exc}")
                st.code(traceback.format_exc())
                return

            if bt_df is None or bt_df.empty:
                st.error("אין נתוני backtest — ייתכן שה-Ticker לא נמצא או שאין מספיק נתוני מחיר.")
                return

            t_count = len(audit_df) if audit_df is not None else 0

            # Zero-trades detection
            if t_count == 0:
                st.error(
                    f"⚠️ הבק-טסט הניב 0 עסקאות עבור '{ticker}' עם סף {bt_threshold}.\n\n"
                    f"💡 נסה:\n"
                    f"• הנמך את הסף ל-{TRADES_FALLBACK_THRESHOLD} ונסה שוב\n"
                    "• הרחב את תקופת הנתונים ל-3y\n"
                    "• וודא שמדובר במניה עם נפח מסחר מספק"
                )
                return

            if t_count < MIN_TRADES_FOR_VALID_MODEL:
                st.warning(f"⚠️ נמצאו רק {t_count} עסקאות — הסטטיסטיקה עשויה להיות לא מהימנה.")

            w_count = len(audit_df[audit_df["win"] == True]) if (audit_df is not None and "win" in audit_df.columns) else 0
            w_rate = w_count / t_count if t_count > 0 else 0
            s_ret = float(bt_df["Cum_Strategy"].iloc[-1]) if "Cum_Strategy" in bt_df.columns else float("nan")
            baseline = float(bt_df["Cum_Baseline"].iloc[-1]) if "Cum_Baseline" in bt_df.columns else float("nan")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("עסקאות", t_count)
            m2.metric("Win Rate", f"{w_rate:.1%}")
            m3.metric("Strategy", f"{s_ret:.2%}" if not np.isnan(s_ret) else "N/A")
            m4.metric("Baseline", f"{baseline:.2%}" if not np.isnan(baseline) else "N/A")

            fig = go.Figure()
            if "Cum_Strategy" in bt_df.columns:
                fig.add_trace(go.Scatter(x=bt_df.index, y=bt_df["Cum_Strategy"], name="Wyckoff Strategy"))
            if "Cum_Baseline" in bt_df.columns:
                fig.add_trace(go.Scatter(x=bt_df.index, y=bt_df["Cum_Baseline"], name="Baseline", line=dict(dash="dot")))
            fig.update_layout(
                height=420,
                margin=dict(l=0, r=0, t=25, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#d9e6f2"),
                legend=dict(orientation="h"),
            )
            st.plotly_chart(fig, use_container_width=True)

            if audit_df is not None and not audit_df.empty:
                st.markdown("### Audit Logs")
                for _, row in audit_df.iterrows():
                    is_win = bool(row.get("win", False))
                    cls = "win" if is_win else "loss"
                    emoji = "✅" if is_win else "❌"
                    st.markdown(
                        f'<div class="audit-row {cls}">'
                        f"{emoji} {row.get('entry_date', 'N/A')} → {row.get('exit_date', 'N/A')}<br>"
                        f"פאזה: {row.get('phase_at_entry', 'N/A')} | "
                        f"תשואה: {row.get('return_pct', 'N/A')}% | "
                        f"יציאה: {row.get('exit_type', 'N/A')}"
                        "</div>",
                        unsafe_allow_html=True,
                    )
            _gc_collect()

def screen_scanner() -> None:
    st.markdown("### 🔎 Market Scanner")
    st.caption("סריקת יקום מניות ואיתור שמות שעוברים את רף הציון.")
    render_active_ai_selector_widget("scanner")

    c1, c2 = st.columns([2.2, 1], vertical_alignment="bottom")
    with c1:
        sector_name = st.selectbox("בחר סקטור", list(SECTOR_MAP.keys()), key="scanner_sector")
    with c2:
        chosen_universe = SECTOR_MAP[sector_name]
        scan_limit = st.slider(
            "כמות מניות לסריקה",
            5, max(5, len(chosen_universe)), min(20, len(chosen_universe)),
            step=5, key="scanner_limit",
        )

    scan_th = render_threshold_control("סף כניסה לסינון", "scan_threshold")

    if st.button("🚀 התחל סריקה", use_container_width=True, type="primary"):
        results: List[Dict[str, Any]] = []
        errors: List[str] = []
        engine = FactorEngine(BacktestConfig())
        progress = st.progress(0)
        total = max(1, min(scan_limit, len(chosen_universe)))

        for i, ticker in enumerate(chosen_universe[:scan_limit], start=1):
            try:
                df = get_cached_data(ticker, period="6mo")
                if df is not None and len(df) > 30:
                    factors = engine.compute(df)
                    if factors is None or factors.empty:
                        continue
                    cis = engine.composite_cis(factors, df)
                    phase = engine.get_wyckoff_phase(df)
                    score = float(cis.iloc[-1]) if hasattr(cis, "iloc") else float(cis)
                    if score >= scan_th:
                        results.append({
                            "Ticker": ticker,
                            "Score": round(score, 1),
                            "Phase": str(phase.iloc[-1]) if hasattr(phase, "iloc") else str(phase),
                            "Close": float(df["Close"].iloc[-1]),
                        })
            except Exception as exc:
                errors.append(f"{ticker}: {exc}")
                logger.warning("Scanner error %s: %s", ticker, exc)
            finally:
                progress.progress(min(1.0, i / total))

        if results:
            st.success(f"נמצאו {len(results)} מניות מעל {scan_th}")
            st.dataframe(pd.DataFrame(results).sort_values("Score", ascending=False), use_container_width=True)
        else:
            st.warning(
                f"אף מניה לא חצתה את רף הציון {scan_th}.\n"
                f"💡 נסה להנמיך את הסף ל-{max(40, scan_th - 10)} ולסרוק שוב."
            )

        if errors:
            with st.expander(f"⚠️ שגיאות סריקה ({len(errors)})", expanded=False):
                st.code("\n".join(errors[:30]))

        _gc_collect()

def screen_monitor() -> None:
    st.markdown("### 👁️ Lab Monitor")
    st.caption("פיקוח על האימון, המודלים, והקבצים שנשמרו בדיסק.")
    render_trainer_control_panel()

    st.markdown("---")
    st.markdown("### 📥 הורדת מודלים מאומנים")
    st.caption("קבצי .pkl מוכנים להורדה, לשמירה או להעלאה ל-GitHub.")
    st.session_state.model_archive = load_all_models_from_disk()

    if st.session_state.model_archive:
        download_cols = st.columns(3)
        for i, slot in enumerate(list(st.session_state.model_archive.keys())):
            safe_slot = clean_filename(str(slot))
            model_path = os.path.join(MODEL_DIR, f"model_{safe_slot}.pkl")
            meta = st.session_state.model_archive[slot].get("metadata", {})
            num_trades = meta.get("num_trades", "?")
            label_extra = f" ({num_trades} עסקאות)" if num_trades != "?" else ""
            if os.path.exists(model_path):
                with open(model_path, "rb") as f:
                    data = f.read()
                download_cols[i % 3].download_button(
                    label=f"⬇️ הורד {slot}{label_extra}",
                    data=data,
                    file_name=f"model_{safe_slot}.pkl",
                    mime="application/octet-stream",
                    key=f"dl_{safe_slot}",
                    use_container_width=True,
                )
    else:
        st.info("אין מודלים זמינים כרגע.")

    st.markdown("---")
    if not st.session_state.model_archive:
        return

    slot = st.selectbox("בחר סקטור למעקב", list(st.session_state.model_archive.keys()), key="monitor_slot")
    safe_slot = clean_filename(str(slot))
    csv_path = os.path.join(MODEL_DIR, f"training_data_{safe_slot}.csv")
    model_data = st.session_state.model_archive[slot]
    model = model_data.get("model")
    meta = model_data.get("metadata", {})

    df = pd.DataFrame()
    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path)
        except Exception as exc:
            logger.warning("Could not read training CSV %s: %s", csv_path, exc)

    num_trades = meta.get("num_trades", len(df) if not df.empty else 0)
    if isinstance(num_trades, int):
        _, trade_msg = validate_trade_count(num_trades, slot)
        st.info(trade_msg)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("OOB / Train", f"{float(meta.get('train_acc', 0.0)) * 100:.1f}%")
    m2.metric("שורות נתונים", len(df) if not df.empty else 0)
    m3.metric("Threshold מומלץ", meta.get("recommended_threshold", 50))
    if not df.empty and "label" in df.columns:
        m4.metric("Win Rate", f"{float(df['label'].mean()) * 100:.1f}%")
    else:
        m4.metric("Win Rate", "N/A")

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("### Feature Importance")
        if hasattr(model, "feature_importances_") and hasattr(model, "feature_names_in_"):
            fi_df = (
                pd.DataFrame({"Feature": list(model.feature_names_in_), "Importance": list(model.feature_importances_)})
                .sort_values("Importance", ascending=True)
                .tail(10)
            )
            fig = go.Figure(go.Bar(x=fi_df["Importance"], y=fi_df["Feature"], orientation="h"))
            fig.update_layout(
                height=350, margin=dict(l=0, r=0, t=20, b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#d9e6f2"),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("למודל אין feature_importances_ זמינים.")

    with col_b:
        st.markdown("### מניות מובילות בספרייה")
        if not df.empty and "ticker" in df.columns:
            ticker_counts = df["ticker"].value_counts().head(10)
            fig2 = go.Figure(go.Pie(labels=ticker_counts.index.tolist(), values=ticker_counts.values.tolist(), hole=0.42))
            fig2.update_layout(
                height=350, margin=dict(l=0, r=0, t=20, b=0),
                paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#d9e6f2"),
            )
            st.plotly_chart(fig2, use_container_width=True)

    if not df.empty:
        st.markdown("### עסקאות אחרונות")
        cols_ok = [c for c in ["entry_date", "ticker", "phase", "label"] if c in df.columns]
        show_df = df[cols_ok].sort_values("entry_date", ascending=False).head(15).copy() if cols_ok else df.head(15).copy()
        if "label" in show_df.columns:
            show_df["label"] = show_df["label"].apply(lambda x: "✅ הצלחה" if int(x) == 1 else "❌ כישלון")
        st.dataframe(show_df, use_container_width=True)

def screen_ml_trainer() -> None:
    st.markdown("### 🧠 Batched ML Trainer")
    st.caption("הפעלת אימון מבוזר לפי סקטור, עם שמירה לדיסק והורדה של המודלים.")
    running = is_trainer_running()
    status = read_auto_trainer_status()

    if running:
        st.warning(
            f"⏳ אימון פעיל: {status.get('current_slot', 'N/A')} — "
            f"{status.get('message', '')} ({status.get('progress', 0)}%)"
        )

    # Zero-trades guard: surface last run result prominently
    last_trades = status.get("num_trades")
    if last_trades is not None and not running:
        try:
            lt = int(last_trades)
            valid, msg = validate_trade_count(lt, status.get("current_slot", "?"))
            if not valid:
                st.error(msg)
            elif lt < MIN_TRADES_FOR_VALID_MODEL:
                st.warning(msg)
        except Exception:
            pass

    st.session_state.model_archive = load_all_models_from_disk()

    sectors_data = [
        ("Growth (צמיחה)", GROWTH_TICKERS),
        ("Value/Index (ערך/מדד)", VALUE_TICKERS),
        ("Commodities (סחורות)", COMMODITIES_TICKERS),
    ]

    cols = st.columns(3)
    for idx, (slot_name, tickers) in enumerate(sectors_data):
        with cols[idx]:
            st.markdown(f"#### {slot_name}")
            chunks = chunk_list(tickers, 10)
            selected_for_slot: List[str] = []
            for i, chunk in enumerate(chunks):
                if not chunk:
                    continue
                hint = f"{chunk[0]}...{chunk[-1]}" if len(chunk) > 1 else chunk[0]
                if st.checkbox(
                    f"אימון Batch {i+1} ({len(chunk)} מניות: {hint})",
                    key=f"chk_{clean_filename(slot_name)}_{i}",
                    disabled=running,
                ):
                    selected_for_slot.extend(chunk)

            if st.button(
                f"🚀 התחל אימון {slot_name.split()[0]}",
                disabled=running,
                use_container_width=True,
                type="primary",
                key=f"btn_{clean_filename(slot_name)}",
            ):
                if not selected_for_slot:
                    st.error("לא נבחרו מניות — סמן לפחות batch אחד.")
                else:
                    ensure_dirs()
                    config_data = {
                        "slot": slot_name,
                        "tickers": selected_for_slot,
                        "base_threshold": TRADES_FALLBACK_THRESHOLD,  # use safe default
                        "min_trades": MIN_TRADES_FOR_VALID_MODEL,
                        "created_at": safe_now(),
                    }
                    try:
                        with open(BATCH_CONFIG_FILE, "w", encoding="utf-8") as f:
                            json.dump(config_data, f, ensure_ascii=False, indent=2)
                        pid = start_trainer_process()
                        st.success(f"האימון התחיל בהצלחה. PID: {pid}")
                        logger.info("Trainer launched for slot '%s', PID=%d, tickers=%d", slot_name, pid, len(selected_for_slot))
                        st.rerun()
                    except Exception as exc:
                        logger.error("start_trainer_process failed: %s", exc, exc_info=True)
                        st.error(f"שגיאה בהפעלת הטריינר: {exc}")
                        st.code(traceback.format_exc())

    st.markdown("---")
    render_trainer_control_panel()

    st.markdown("---")
    st.markdown("### ⚙️ פעולות מערכת")
    col_reset, col_cache = st.columns(2)
    with col_reset:
        if st.button("🧹 נקה קבצי סטטוס ואתחל", use_container_width=True, type="secondary"):
            clear_trainer_artifacts()
            try:
                st.cache_data.clear()
            except Exception:
                pass
            # Only clear non-critical session keys to avoid full reload jank
            for key in ["model_archive", "ml_model", "ml_metadata", "phase_encoder", "use_ml"]:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()
    with col_cache:
        if st.button("🗑️ נקה cache נתונים", use_container_width=True, type="secondary"):
            try:
                st.cache_data.clear()
                st.success("Cache נוקה בהצלחה")
            except Exception as exc:
                st.error(f"שגיאה בניקוי cache: {exc}")

def screen_vp() -> None:
    st.markdown("### 🔮 Volume Profile")
    st.caption("מסך זה מוכן להרחבה עם לוגיקת Volume Profile, HVN/LVN, ואזורי איזון.")
    with st.container(border=True):
        st.write("בפיתוח")
        st.write("המסך מחובר לתבנית המוסדית, ל-sidebar, ול-session_state.")

def screen_vwap() -> None:
    st.markdown("### 📊 VWAP Deviation")
    st.caption("מסך זה מיועד למדידת סטיות ממוצע משוקלל נפח (VWAP).")
    with st.container(border=True):
        st.write("בפיתוח")
        st.write("אפשר להוסיף כאן banding, anchored VWAP, ו-signals.")

def screen_composite() -> None:
    st.markdown("### 📈 Composite Score")
    st.caption("מסך לאיחוד פקטורים, Weighting, וניתוח ציון מורכב.")
    with st.container(border=True):
        st.write("בפיתוח")
        st.write("המסך מוכן להרחבה עם פקטורי טרנד, נפח, ו-absorption.")

# ============================================================
# Top bar / navigation
# ============================================================

def render_top_bar() -> None:
    cloud_badge = " ☁️ Cloud Run" if _CLOUD_RUN else ""
    render_header(
        f"INSTITUTIONAL SCOUT PRO{cloud_badge}",
        "ממשק פינטק מוסדי לניתוח Wyckoff, סריקה, Backtest, אימון מודלים ומעקב. Dark-mode פיננסי, יציב ומודולרי.",
    )
    render_info_banner()

# ============================================================
# Main entry point
# ============================================================

def main() -> None:
    init_session_state()
    inject_css()
    render_top_bar()

    tabs = st.tabs([
        "⬛ Wyckoff",
        "📊 Backtest",
        "🔎 Scanner",
        "🧠 ML Trainer",
        "👁️ Monitor",
        "🔮 VP",
        "📊 VWAP",
        "📈 Composite",
    ])

    screen_fns = [
        screen_wyckoff,
        screen_backtest,
        screen_scanner,
        screen_ml_trainer,
        screen_monitor,
        screen_vp,
        screen_vwap,
        screen_composite,
    ]

    for tab, fn in zip(tabs, screen_fns):
        with tab:
            try:
                fn()
            except Exception as exc:
                logger.error("Unhandled error in %s: %s", fn.__name__, exc, exc_info=True)
                st.error(f"שגיאה לא צפויה במסך זה: {exc}")
                st.code(traceback.format_exc())


if __name__ == "__main__":
    main()
