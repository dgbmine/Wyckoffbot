# ============================================================
# INSTITUTIONAL SCOUT PRO - FINAL UI V10.16
# Safe Subprocess Background Auto-Trainer Control & Robust Model Loading
# ============================================================

import sys
import os
import json
import pickle
import time
import traceback
import subprocess
import signal
from datetime import datetime

import pandas as pd
import numpy as np
import yfinance as yf
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder

import streamlit as st
import plotly.graph_objects as go

# ── נתיב בסיס מוחלט ───────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# ייבוא מפורש מ-scout_core — אין import *
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

# ============================================================
# Paths / Files & Smart Resolution
# ============================================================
MODEL_DIR = os.path.join(BASE_DIR, "models")

def _hunt_for_trainer():
    """
    מחפש את auto_trainer_fixed.py בצורה אגרסיבית:
    1. באותה תיקייה של app.py
    2. בתיקיית העבודה הנוכחית
    3. בתיקיית ההורה
    4. חיפוש רקורסיבי בתיקיית BASE_DIR (עד עומק 3)
    """
    target_name = "auto_trainer_fixed.py"
    primary = os.path.join(BASE_DIR, target_name)
    if os.path.isfile(primary):
        return primary
    cwd_candidate = os.path.join(os.getcwd(), target_name)
    if os.path.isfile(cwd_candidate):
        return cwd_candidate
    parent_candidate = os.path.join(os.path.dirname(BASE_DIR), target_name)
    if os.path.isfile(parent_candidate):
        return parent_candidate
    for root, dirs, files in os.walk(BASE_DIR):
        depth = root[len(BASE_DIR):].count(os.sep)
        if depth > 3:
            continue
        if target_name in files:
            return os.path.join(root, target_name)
    return primary

TRAINER_SCRIPT = _hunt_for_trainer()
TRAINER_AVAILABLE = os.path.isfile(TRAINER_SCRIPT)

AUTO_TRAINER_STATUS_FILE = os.path.join(MODEL_DIR, "auto_trainer_status.json")
AUTO_TRAINER_DONE_FLAG = os.path.join(MODEL_DIR, "auto_trainer.done")
AUTO_TRAINER_LOG_FILE = os.path.join(BASE_DIR, "auto_trainer_error.log")
AUTO_TRAINER_PID_FILE = os.path.join(MODEL_DIR, "auto_trainer.pid")
AUTO_TRAINER_STOP_FILE = os.path.join(MODEL_DIR, "auto_trainer.stop")
AUTO_TRAINER_LOCK_FILE = os.path.join(MODEL_DIR, "auto_trainer.lock")

# קובץ קונפיגורציה ל-Batch Training
BATCH_CONFIG_FILE = os.path.join(MODEL_DIR, "batch_config.json")

st.set_page_config(layout="wide", page_title="Institutional Scout Pro")

# ============================================================
# Helpers
# ============================================================
def save_model_to_disk(slot_name, model, metadata, encoder):
    os.makedirs(MODEL_DIR, exist_ok=True)
    safe_name = clean_filename(str(slot_name))
    file_path = os.path.join(MODEL_DIR, f"model_{safe_name}.pkl")
    with open(file_path, "wb") as f:
        pickle.dump({"model": model, "metadata": metadata, "phase_encoder": encoder}, f, protocol=pickle.HIGHEST_PROTOCOL)
    return file_path

def load_all_models_from_disk():
    loaded = {}
    if os.path.exists(MODEL_DIR):
        for filename in os.listdir(MODEL_DIR):
            if filename.startswith("model_") and filename.endswith(".pkl"):
                filepath = os.path.join(MODEL_DIR, filename)
                try:
                    with open(filepath, "rb") as f:
                        data = pickle.load(f)
                    slot = data.get("metadata", {}).get("slot")
                    if not slot:
                        slot = filename.replace("model_", "").replace(".pkl", "")
                    loaded[slot] = data
                except Exception as e:
                    print(f"Error loading model {filename}: {e}")
                    pass
    return loaded

def load_all_research_dfs_from_disk():
    archive = {}
    if os.path.exists("research_labels"):
        for filename in os.listdir("research_labels"):
            if filename.endswith(".csv"):
                filepath = os.path.join("research_labels", filename)
                try:
                    df = pd.read_csv(filepath)
                    key = filename.replace("research_", "").replace(".csv", "")
                    archive[key] = df
                except Exception:
                    pass
    return archive

def read_auto_trainer_status():
    default = {
        "state": "idle",
        "message": "לא רץ כרגע",
        "progress": 0,
        "current_slot": "N/A",
        "updated_at": "N/A",
        "started_at": "N/A",
        "finished_at": "N/A",
        "pid": "N/A",
    }
    if os.path.exists(AUTO_TRAINER_STATUS_FILE):
        try:
            with open(AUTO_TRAINER_STATUS_FILE, "r", encoding="utf-8") as f:
                default.update(json.load(f))
        except Exception:
            pass
    elif os.path.exists(AUTO_TRAINER_DONE_FLAG):
        default.update({"state": "completed", "message": "האימון הסתיים", "progress": 100})
    return default

def _is_pid_running(pid):
    if pid is None:
        return False
    try:
        pid = int(pid)
    except Exception:
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False

def read_trainer_pid():
    if not os.path.exists(AUTO_TRAINER_PID_FILE):
        return None
    try:
        with open(AUTO_TRAINER_PID_FILE, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        pid = int(raw)
    except Exception:
        try:
            os.remove(AUTO_TRAINER_PID_FILE)
        except Exception:
            pass
        return None
    if _is_pid_running(pid):
        return pid
    try:
        os.remove(AUTO_TRAINER_PID_FILE)
    except Exception:
        pass
    return None

def write_trainer_pid(pid):
    os.makedirs(MODEL_DIR, exist_ok=True)
    tmp_file = AUTO_TRAINER_PID_FILE + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(str(int(pid)))
        os.replace(tmp_file, AUTO_TRAINER_PID_FILE)
    except Exception:
        with open(AUTO_TRAINER_PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(int(pid)))

def clear_stop_request():
    if os.path.exists(AUTO_TRAINER_STOP_FILE):
        try:
            os.remove(AUTO_TRAINER_STOP_FILE)
        except Exception:
            pass

def write_stop_request():
    os.makedirs(MODEL_DIR, exist_ok=True)
    payload = {
        "requested_at": datetime.now().isoformat(timespec="seconds"),
        "pid": read_trainer_pid() or "N/A",
    }
    with open(AUTO_TRAINER_STOP_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

def cleanup_stale_trainer_artifacts():
    pid = read_trainer_pid()
    is_running = pid is not None

    if not is_running and os.path.exists(AUTO_TRAINER_STOP_FILE):
        try:
            os.remove(AUTO_TRAINER_STOP_FILE)
        except Exception:
            pass

    if os.path.exists(AUTO_TRAINER_LOCK_FILE):
        status = read_auto_trainer_status()
        if not is_running and status.get("state") in {"running", "stopping"}:
            try:
                os.remove(AUTO_TRAINER_LOCK_FILE)
            except Exception:
                pass
        else:
            try:
                age = time.time() - os.path.getmtime(AUTO_TRAINER_LOCK_FILE)
                if age > 6 * 3600:
                    os.remove(AUTO_TRAINER_LOCK_FILE)
            except Exception:
                pass

def is_trainer_running():
    cleanup_stale_trainer_artifacts()
    status = read_auto_trainer_status()
    pid = read_trainer_pid()
    lock_exists = os.path.exists(AUTO_TRAINER_LOCK_FILE)
    return (
        status.get("state") in {"running", "locked", "stopping"}
        or pid is not None
        or lock_exists
    )

def _send_sigterm(pid):
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(int(pid)), "/T"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.kill(int(pid), signal.SIGTERM)
    except Exception:
        pass

def _send_sigkill(pid):
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.kill(int(pid), signal.SIGKILL)
    except Exception:
        pass

def start_trainer_process(batch_config=None):
    """
    מפעיל את auto_trainer_fixed.py כתהליך נפרד.
    אם batch_config מועבר, כותב קובץ JSON לפני ההפעלה.
    מחזיר PID.
    """
    if not TRAINER_AVAILABLE:
        if os.path.isdir(BASE_DIR):
            files_in_root = os.listdir(BASE_DIR)
            msg = (
                f"קובץ auto_trainer_fixed.py לא נמצא!\n"
                f"נתיב צפוי: {TRAINER_SCRIPT}\n"
                f"תיקיית האפליקציה (BASE_DIR): {BASE_DIR}\n"
                f"קבצים בתיקייה: {files_in_root}\n"
                f"אנא וודא שהקובץ קיים וקריא."
            )
        else:
            msg = f"BASE_DIR אינה תיקייה: {BASE_DIR}"
        raise FileNotFoundError(msg)

    if is_trainer_running():
        raise RuntimeError("האימון כבר רץ כרגע.")

    os.makedirs(MODEL_DIR, exist_ok=True)
    clear_stop_request()

    # כתיבת קונפיגורציית Batch אם סופקה
    if batch_config is not None:
        with open(BATCH_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(batch_config, f, ensure_ascii=False, indent=2)
    else:
        # ריצה מלאה — מחיקת קונפיגורציה קודמת אם קיימת
        if os.path.exists(BATCH_CONFIG_FILE):
            try:
                os.remove(BATCH_CONFIG_FILE)
            except Exception:
                pass

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    log_handle = open(AUTO_TRAINER_LOG_FILE, "a", encoding="utf-8")
    try:
        kwargs = {
            "cwd": os.path.dirname(TRAINER_SCRIPT),
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
            "env": env,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True

        proc = subprocess.Popen([sys.executable, TRAINER_SCRIPT], **kwargs)
        write_trainer_pid(proc.pid)
        return proc.pid
    finally:
        try:
            log_handle.close()
        except Exception:
            pass

def stop_trainer_process(grace_seconds=5):
    pid = read_trainer_pid()
    write_stop_request()

    if pid is None:
        cleanup_stale_trainer_artifacts()
        return True

    _send_sigterm(pid)
    deadline = time.time() + float(grace_seconds)
    while time.time() < deadline:
        if not _is_pid_running(pid):
            break
        time.sleep(0.25)

    if _is_pid_running(pid):
        _send_sigkill(pid)
        time.sleep(0.5)

    try:
        if os.path.exists(AUTO_TRAINER_PID_FILE):
            os.remove(AUTO_TRAINER_PID_FILE)
    except Exception:
        pass
    cleanup_stale_trainer_artifacts()
    return True

def clear_trainer_artifacts():
    files_to_delete = [
        AUTO_TRAINER_STATUS_FILE,
        AUTO_TRAINER_DONE_FLAG,
        AUTO_TRAINER_LOG_FILE,
        AUTO_TRAINER_PID_FILE,
        AUTO_TRAINER_STOP_FILE,
        AUTO_TRAINER_LOCK_FILE,
    ]
    for f in files_to_delete:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

# ============================================================
# Universe
# ============================================================
SCAN_UNIVERSE = list(dict.fromkeys([
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","BRK-B","JPM","JNJ",
    "V","UNH","XOM","PG","MA","HD","CVX","MRK","ABBV","PEP",
    "KO","AVGO","COST","WMT","LLY","TMO","MCD","ACN","BAC","CRM",
    "NFLX","AMD","ADBE","CSCO","ABT","TXN","NEE","DHR","RTX","QCOM",
    "HON","NKE","INTC","AMGN","PM","IBM","SBUX","INTU","GS","CAT",
    "BA","GE","SPGI","AXP","BLK","DE","ISRG","MDLZ","ADI","GILD",
    "REGN","SYK","ZTS","MMC","AON","TJX","SCHW","CB","USB","WFC",
    "C","MS","CVS","CI","SLB","EOG","OXY","COP","PSX","VLO",
    "AMT","PLD","CCI","EQIX","SPG","O","WELL","DLR",
    "FCX","NEM","GOLD","AEM","WPM","FNV","PAAS","AG",
    "PANW","CRWD","FTNT","ZS","DDOG","SNOW","MDB","NET","PLTR",
    "UBER","ABNB","COIN","SOFI","UPST",
    "F","GM","RIVN","NIO",
    "ONTO","KLAC","LRCX","AMAT","MRVL","SMCI","DELL","HPQ",
    "DIS","CMCSA","RBLX","U","TTWO","EA",
    "DAL","UAL","AAL","LUV","FDX","UPS","XPO","ODFL",
    "DKNG","MGM","CZR","RCL","CCL","MAR","HLT",
]))

SECTOR_MAP = {
    "הכול (כל השוק האמריקאי)": SCAN_UNIVERSE,
    "צמיחה וטכנולוגיה (Growth)": [
        "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","CRM",
        "NFLX","AMD","ADBE","CSCO","TXN","QCOM","INTC","INTU","ADI",
        "PANW","CRWD","FTNT","ZS","DDOG","SNOW","MDB","NET","PLTR",
        "UBER","ABNB","COIN","SOFI","UPST","ONTO","KLAC","LRCX",
        "AMAT","MRVL","SMCI","DELL","HPQ","RBLX","U","TTWO","EA",
    ],
    "ערך ומדד (Value/Index)": [
        "BRK-B","JPM","JNJ","V","UNH","PG","MA","HD","MRK","ABBV",
        "PEP","KO","COST","WMT","LLY","TMO","MCD","ACN","BAC","ABT",
        "DHR","RTX","HON","NKE","AMGN","PM","IBM","SBUX","GS","CAT",
        "BA","GE","SPGI","AXP","BLK","DE","ISRG","MDLZ","GILD",
        "REGN","SYK","ZTS","MMC","AON","TJX","SCHW","CB","USB","WFC",
        "C","MS","CVS","CI","AMT","PLD","CCI","EQIX","SPG","O",
        "WELL","DLR","DIS","CMCSA","DAL","UAL","AAL","LUV","FDX",
        "UPS","XPO","ODFL","DKNG","MGM","CZR","RCL","CCL","MAR","HLT",
    ],
    "סחורות ואנרגיה (Commodities)": [
        "XOM","CVX","SLB","EOG","OXY","COP","PSX","VLO",
        "FCX","NEM","GOLD","AEM","WPM","FNV","PAAS","AG",
        "GLD","SLV",
    ],
}

# ============================================================
# רשימות Batches לכל סקטור (10-15 מניות לבאץ', 10 batches)
# ============================================================
GROWTH_BATCHES = [
    ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"],
    ["META", "TSLA", "AVGO", "CRM", "NFLX"],
    ["AMD", "ADBE", "CSCO", "TXN", "QCOM"],
    ["INTC", "INTU", "ADI", "PANW", "CRWD"],
    ["FTNT", "ZS", "DDOG", "SNOW", "MDB"],
    ["NET", "PLTR", "UBER", "ABNB", "COIN"],
    ["SOFI", "UPST", "ONTO", "KLAC", "LRCX"],
    ["AMAT", "MRVL", "SMCI", "DELL", "HPQ"],
    ["RBLX", "U", "TTWO", "EA", "PANW"],
    ["CRWD", "ZS", "DDOG", "NET", "PLTR"],
]

VALUE_BATCHES = [
    ["BRK-B", "JPM", "JNJ", "V", "UNH"],
    ["PG", "MA", "HD", "MRK", "ABBV"],
    ["PEP", "KO", "COST", "WMT", "LLY"],
    ["TMO", "MCD", "ACN", "BAC", "ABT"],
    ["DHR", "RTX", "HON", "NKE", "AMGN"],
    ["PM", "IBM", "SBUX", "GS", "CAT"],
    ["BA", "GE", "SPGI", "AXP", "BLK"],
    ["DE", "ISRG", "MDLZ", "GILD", "REGN"],
    ["SYK", "ZTS", "MMC", "AON", "TJX"],
    ["SCHW", "CB", "USB", "WFC", "C"],
]

COMMODITIES_BATCHES = [
    ["XOM", "CVX", "SLB", "EOG", "OXY"],
    ["COP", "PSX", "VLO", "FCX", "NEM"],
    ["GOLD", "AEM", "WPM", "FNV", "PAAS"],
    ["AG", "GLD", "SLV", "XOM", "CVX"],
    ["SLB", "EOG", "OXY", "COP", "PSX"],
    ["VLO", "FCX", "NEM", "GOLD", "AEM"],
    ["WPM", "FNV", "PAAS", "AG", "GLD"],
    ["SLV", "XOM", "SLB", "FCX", "WPM"],
    ["NEM", "GOLD", "AEM", "FNV", "PAAS"],
    ["AG", "GLD", "SLV", "CVX", "EOG"],
]

SECTOR_BATCHES = {
    "Growth (צמיחה)": GROWTH_BATCHES,
    "Value/Index (ערך/מדד)": VALUE_BATCHES,
    "Commodities (סחורות)": COMMODITIES_BATCHES,
}

# ============================================================
# CSS
# ============================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+Hebrew:wght@300;400;600&display=swap');
html, body, [class*="css"] {
    font-family: 'IBM Plex Sans Hebrew', sans-serif;
    direction: rtl;
    text-align: right;
    box-sizing: border-box;
}
h1, h2, h3, h4, h5, h6 {
    direction: rtl;
}
.header-box {
    border-radius: 12px;
    padding: 24px 32px;
    margin-bottom: 28px;
    color: #e0eaf4;
    line-height: 1.9;
}
.header-box.wyckoff {
    background: linear-gradient(135deg, #0f1923, #1a2a3a);
    border: 1px solid #2a4a6a;
}
.header-box.vp {
    background: linear-gradient(135deg, #160f23, #251535);
    border: 1px solid #4a2a6a;
}
.header-box.vwap {
    background: linear-gradient(135deg, #0f2318, #1a3528);
    border: 1px solid #2a6a4a;
}
.header-box.composite {
    background: linear-gradient(135deg, #1a1208, #2a1e08);
    border: 1px solid #6a4a1a;
}
.header-box.ml {
    background: linear-gradient(135deg, #1c0a20, #2e1236);
    border: 1px solid #7b1fa2;
}
.header-box.scanner {
    background: linear-gradient(135deg, #0f231f, #1a3a35);
    border: 1px solid #26a69a;
}
.header-box.monitor {
    background: linear-gradient(135deg, #2c3e50, #34495e);
    border: 1px solid #7f8c8d;
}
.widget-panel-ai {
    background: #111922;
    border: 1px solid #2d3d4f;
    border-radius: 10px;
    padding: 20px;
    margin-bottom: 24px;
}
.audit-row {
    padding: 12px;
    margin-bottom: 8px;
    border-radius: 5px;
    border-right: 4px solid;
}
.win {
    background: rgba(38, 166, 154, 0.1);
    border-color: #26a69a;
}
.loss {
    background: rgba(239, 83, 80, 0.1);
    border-color: #ef5350;
}
.batch-panel {
    background: #0e1a24;
    border: 1px solid #2a3f52;
    border-radius: 10px;
    padding: 16px;
    margin-bottom: 12px;
}
</style>
""", unsafe_allow_html=True)

# ============================================================
# Cache נתונים
# ============================================================
@st.cache_data(ttl=3600)
def get_cached_data(ticker, period="1y", start=None, end=None):
    try:
        effective_period = None if (start or end) else period
        df = get_data(ticker, effective_period, start, end)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    try:
        t = yf.Ticker(ticker)
        df = t.history(start=start, end=end) if (start or end) else t.history(period=period or "1y")
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    return None

# ============================================================
# Session State
# ============================================================
if "mode" not in st.session_state: st.session_state.mode = "wyckoff"
if "ml_model" not in st.session_state: st.session_state.ml_model = None
if "ml_metadata" not in st.session_state: st.session_state.ml_metadata = None
if "use_ml" not in st.session_state: st.session_state.use_ml = False
if "phase_encoder" not in st.session_state: st.session_state.phase_encoder = None
if "model_archive" not in st.session_state: st.session_state.model_archive = load_all_models_from_disk()
if "research_archive" not in st.session_state: st.session_state.research_archive = load_all_research_dfs_from_disk()

# ============================================================
# UI helpers
# ============================================================
def render_threshold_control(label, key):
    if key not in st.session_state:
        st.session_state[key] = 65
    st.markdown(f"{label}")
    col1, col2 = st.columns([4, 1])
    with col1:
        st.session_state[key] = st.slider("", 40, 95, st.session_state[key], key=f"{key}_slider", label_visibility="collapsed")
    with col2:
        st.number_input("", 40, 95, st.session_state[key], key=f"{key}_num", label_visibility="collapsed")
    return st.session_state[key]

def render_active_ai_selector_widget(screen_identifier):
    st.markdown("<div class='widget-panel-ai'>", unsafe_allow_html=True)
    st.markdown("### 🧠 הגדרות מנוע החלטה AI חכם")
    col_a, col_b, col_c = st.columns([2, 1.5, 1])
    with col_a:
        if st.session_state.model_archive:
            slots_list = list(st.session_state.model_archive.keys())
            selected_slot = st.selectbox("בחר מודל מוסדי פעיל:", slots_list, key=f"selector_slot_{screen_identifier}")
            if st.button("✅ טען והפעל מודל", key=f"activate_btn_{screen_identifier}", use_container_width=True):
                target_data = st.session_state.model_archive[selected_slot]
                st.session_state.ml_model = target_data["model"]
                st.session_state.ml_metadata = target_data["metadata"]
                st.session_state.phase_encoder = target_data.get("phase_encoder")
                st.session_state.use_ml = True
                st.success(f"המודל '{selected_slot}' הופעל בהצלחה!")
                st.rerun()
        else:
            st.info("לא נמצאו מודלים בזיכרון. הרץ אימון ידני או אוטומטי.")
    with col_b:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 רענן מודלים מהדיסק", key=f"sync_git_{screen_identifier}", use_container_width=True):
            st.session_state.model_archive = load_all_models_from_disk()
            st.rerun()
    with col_c:
        st.markdown("<br>", unsafe_allow_html=True)
        ai_toggle = st.checkbox("הפעל שימוש ב-AI", value=st.session_state.use_ml, key=f"checkbox_ai_{screen_identifier}")
        if ai_toggle != st.session_state.use_ml:
            st.session_state.use_ml = ai_toggle
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

def render_trainer_control_panel():
    cleanup_stale_trainer_artifacts()

    status = read_auto_trainer_status()
    pid = read_trainer_pid()
    running = is_trainer_running()
    lock_exists = os.path.exists(AUTO_TRAINER_LOCK_FILE)
    stop_exists = os.path.exists(AUTO_TRAINER_STOP_FILE)

    st.markdown("### 🚦 Auto-Trainer Control")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("מצב", status.get("state", "idle"))
    c2.metric("התקדמות", f"{status.get('progress', 0)}%")
    c3.metric("PID", str(pid) if pid is not None else str(status.get("pid", "N/A")))
    c4.metric("סקטור נוכחי", status.get("current_slot", "N/A"))
    st.caption(
        f"Lock: {'קיים' if lock_exists else 'לא קיים'} | "
        f"Stop request: {'קיים' if stop_exists else 'לא קיים'} | "
        f"Trainer file: {'נמצא' if TRAINER_AVAILABLE else f'לא נמצא ({TRAINER_SCRIPT})'}"
    )

    b1, b2, b3 = st.columns([1.2, 1.2, 2])
    with b1:
        if st.button(
            "🚀 התחל אימון אוטומטי",
            type="primary",
            use_container_width=True,
            disabled=running or not TRAINER_AVAILABLE,
        ):
            try:
                pid_started = start_trainer_process()
                st.success(f"האימון התחיל ברקע. PID: {pid_started}")
                st.rerun()
            except Exception as e:
                st.error(f"לא ניתן להתחיל אימון: {e}")
    with b2:
        if st.button(
            "⏹ עצור אימון",
            type="secondary",
            use_container_width=True,
            disabled=not running,
        ):
            try:
                ok = stop_trainer_process(grace_seconds=5)
                if ok:
                    st.warning("נשלחה בקשת עצירה. הטריינר יסיים את המניה הנוכחית ויעצור בצורה מסודרת.")
                else:
                    st.info("לא נמצא תהליך רץ לעצירה.")
                st.rerun()
            except Exception as e:
                st.error(f"לא ניתן לעצור את האימון: {e}")
    with b3:
        st.info(
            "האימון רץ כתהליך רקע נפרד. Streamlit יכול להתרענן בלי לקטוע את הריצה באמצע. "
            "כפתור העצירה מנצל את המנגנון החדש לעצירה רכה."
        )

    if status.get("state") in {"running", "stopping", "locked"}:
        st.warning(f"סטטוס נוכחי: {status.get('message', 'לא ידוע')}")

# ============================================================
# ניווט
# ============================================================
st.markdown("# INSTITUTIONAL SCOUT PRO")
c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)
nav = [
    ("wyckoff", "⬛ Wyckoff"),
    ("vp", "🔮 VP"),
    ("vwap", "📊 VWAP"),
    ("composite", "📈 Composite"),
    ("backtest", "📊 Backtest"),
    ("ml", "🧠 ML Trainer"),
    ("scanner", "🔎 Scanner"),
    ("monitor", "👁️ Monitor"),
]
for col, (mode_key, label) in zip([c1, c2, c3, c4, c5, c6, c7, c8], nav):
    with col:
        if st.button(
            label,
            use_container_width=True,
            type="primary" if st.session_state.mode == mode_key else "secondary",
            key=f"nav_{mode_key}",
        ):
            st.session_state.mode = mode_key
            st.rerun()
st.markdown("---")

if st.session_state.use_ml and st.session_state.ml_model is not None:
    metadata = st.session_state.ml_metadata or {}
    acc = metadata.get("test_acc", metadata.get("train_acc", 0.0))
    rec_th = metadata.get("recommended_threshold", "לא חושב")
    tr_count = metadata.get("num_trades", "?")
    st.info(
        f"🧠 מצב AI מופעל: {metadata.get('slot', 'כללי')} | "
        f"דיוק OOB אמיתי: {acc*100:.1f}% | "
        f"🎯 ציון סף מומלץ לכניסה: {rec_th} | "
        f"מאומן על {tr_count} עסקאות היסטוריות"
    )

# ============================================================
# מסכים
# ============================================================
def screen_wyckoff():
    st.markdown("""
    <div class='header-box wyckoff'>
        <h2 style='margin:0; color:#e0eaf4;'>⬛ WYCKOFF 3.0 STRUCTURAL ENGINE</h2>
        <p style='opacity:0.85;'>ניתוח מבני מבוסס Wyckoff על ידי FactorEngine</p>
    </div>
    """, unsafe_allow_html=True)
    render_active_ai_selector_widget("wyckoff_screen")
    c1, c2 = st.columns([4, 1])
    with c1:
        ticker = st.text_input("סמל לניתוח:", "NVDA", key="w_ticker")
    with c2:
        st.markdown("<br>", unsafe_allow_html=True)
        btn = st.button("▶ הרץ ניתוח", use_container_width=True, type="primary")
    if btn:
        with st.spinner("מנתח דרך FactorEngine..."):
            df = get_cached_data(ticker.upper())
            if df is None or df.empty:
                st.error("אין נתונים.")
                return
            try:
                engine = FactorEngine(BacktestConfig())
                factors = engine.compute(df)
                phase_series = engine.get_wyckoff_phase(df)
                cis_series = engine.composite_cis(factors, df)
                if factors is None or factors.empty or cis_series is None or len(cis_series) == 0:
                    st.warning("לא התקבלה תוצאת פקטורים תקינה מה-Engine.")
                    return
                current_phase = phase_series.iloc[-1] if hasattr(phase_series, "iloc") else phase_series
                current_cis = float(cis_series.iloc[-1]) if hasattr(cis_series, "iloc") else float(cis_series)
                st.markdown(f"### 📌 סטטוס: {current_phase}")
                st.metric("Composite CIS", f"{current_cis:.1f}")
                if st.session_state.use_ml and st.session_state.ml_model is not None:
                    st.info("ניתוח ה-Wyckoff מבוצע ישירות דרך FactorEngine. מודל ה-AI פעיל בשאר המסכים.")
            except Exception as e:
                st.error(f"שגיאה בחישוב המנוע: {e}")

def screen_backtest():
    st.markdown("""
    <div class='header-box backtest'>
        <h2 style='margin:0; color:#e0eaf4;'>📊 WYCKOFF-ANCHORED BACKTEST ENGINE</h2>
        <p style='opacity:0.85;'>הרצת סימולציה היסטורית עם Wyckoff-Anchored Threshold</p>
    </div>
    """, unsafe_allow_html=True)
    render_active_ai_selector_widget("bt_screen")
    col_r1, _ = st.columns([1, 2])
    with col_r1:
        risk_profile = st.selectbox("🎯 Risk Profile:", ["Aggressive", "Balanced", "Conservative"], index=1)
    c1, c2, _ = st.columns([2, 1.5, 1])
    with c1:
        ticker = st.text_input("סמל לבדיקה:", "COST", key="bt_t")
    with c2:
        render_threshold_control("סף ציון CIS", "bt_threshold")
        bt_threshold = st.session_state["bt_threshold"]
    if st.button("▶ הרץ סימולציה", use_container_width=True, type="primary"):
        with st.spinner("מריץ..."):
            try:
                bt_df, audit_df = run_wyckoff_anchored_backtest(
                    ticker.upper(),
                    st.session_state.use_ml,
                    bt_threshold,
                    period="2y",
                    risk_profile=risk_profile,
                )
            except Exception as e:
                st.error(f"שגיאה בהרצת הבק-טסט: {e}")
                return
            if bt_df is None:
                st.error("שגיאה בנתונים.")
                return
            t_count = len(audit_df)
            w_rate = len(audit_df[audit_df["win"] == True]) / t_count if t_count > 0 else 0
            s_ret = bt_df["Cum_Strategy"].iloc[-1]
            c_m1, c_m2, c_m3 = st.columns(3)
            c_m1.metric("מס' עסקאות", t_count)
            c_m2.metric("Win Rate", f"{w_rate:.1%}" if t_count > 0 else "N/A")
            c_m3.metric("תשואה", f"{s_ret:.2%}")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=bt_df.index, y=bt_df["Cum_Strategy"], name="Wyckoff Strategy"))
            fig.add_trace(go.Scatter(x=bt_df.index, y=bt_df["Cum_Baseline"], name="Baseline", line=dict(dash="dot")))
            st.plotly_chart(fig, use_container_width=True)
            if not audit_df.empty:
                st.markdown("### 📋 Audit Logs")
                for _, row in audit_df.iterrows():
                    cls = "win" if row["win"] else "loss"
                    emoji = "✅" if row["win"] else "❌"
                    st.markdown(
                        f"""
                        <div class='audit-row {cls}'>
                        {emoji} {row['entry_date']} → {row['exit_date']}<br>
                        פאזה: {row['phase_at_entry']} | תשואה: {row['return_pct']}% | יציאה: {row.get('exit_type','N/A')}
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

    st.markdown("---")
    st.markdown("### ⚙️ פעולות מערכת וניקוי תקלות")
    st.markdown("במידה והלמידה נתקעת או שהאפליקציה מתנהגת מוזר - הלחצן הזה ימחק קבצים זמניים, ינקה מטמון וירענן את העמוד מאפס.")
    if st.button("🚀 נקה קבצי סטטוס תקועים ואתחל מערכת (Hard Reboot)", use_container_width=True, type="primary"):
        clear_trainer_artifacts()
        st.cache_data.clear()
        if hasattr(st, "cache_resource"):
            st.cache_resource.clear()
        st.session_state.clear()
        st.components.v1.html("<script>window.parent.location.reload(true);</script>", height=0)

def screen_scanner():
    st.markdown("""
    <div class='header-box scanner'>
        <h2 style='margin:0; color:#e0eaf4;'>🔎 MARKET SCANNER</h2>
        <p style='opacity:0.85;'>סריקת שוק מהירה לאיתור מניות מעל רף הציון</p>
    </div>
    """, unsafe_allow_html=True)
    render_active_ai_selector_widget("scan_screen")
    c1, c2 = st.columns([2, 1])
    with c1:
        chosen_universe = SECTOR_MAP[st.selectbox("📀 בחר סקטור:", list(SECTOR_MAP.keys()), key="scanner_sector")]
    with c2:
        scan_limit = st.slider("כמות מניות:", 5, len(chosen_universe), min(10, len(chosen_universe)), step=5)
    render_threshold_control("סף כניסה (Threshold) לסינון התוצאות:", "scan_threshold")
    scan_th = st.session_state["scan_threshold"]
    if st.button("🚀 התחל סריקה", use_container_width=True, type="primary"):
        results = []
        engine = FactorEngine(BacktestConfig())
        progress = st.progress(0)
        for i, ticker in enumerate(chosen_universe[:scan_limit]):
            df = get_cached_data(ticker, period="6mo")
            if df is not None and len(df) > 30:
                try:
                    f = engine.compute(df)
                    score = engine.composite_cis(f, df).iloc[-1]
                    phase = engine.get_wyckoff_phase(df).iloc[-1]
                    if score >= scan_th:
                        results.append({"Ticker": ticker, "Score": round(score, 1), "Phase": phase})
                except Exception:
                    pass
            progress.progress((i + 1) / scan_limit)
        if results:
            st.success(f"נמצאו {len(results)} מניות שעוברות את רף הציון {scan_th}:")
            st.dataframe(pd.DataFrame(results).sort_values("Score", ascending=False), use_container_width=True)
        else:
            st.warning(f"אף מניה לא חצתה את רף הציון של {scan_th}.")

def screen_vp():
    st.markdown("""
    <div class='header-box vp'>
        <h2 style='margin:0; color:#e0eaf4;'>🔮 VOLUME PROFILE</h2>
        <p style='opacity:0.85;'>ניתוח ווליום פרופיל (בפיתוח)</p>
    </div>
    """, unsafe_allow_html=True)

def screen_vwap():
    st.markdown("""
    <div class='header-box vwap'>
        <h2 style='margin:0; color:#e0eaf4;'>📊 VWAP DEVIATION</h2>
        <p style='opacity:0.85;'>סטיות VWAP (בפיתוח)</p>
    </div>
    """, unsafe_allow_html=True)

def screen_composite():
    st.markdown("""
    <div class='header-box composite'>
        <h2 style='margin:0; color:#e0eaf4;'>📈 COMPOSITE SCORE</h2>
        <p style='opacity:0.85;'>ציון Composite מתקדם (בפיתוח)</p>
    </div>
    """, unsafe_allow_html=True)

def screen_monitor():
    st.markdown("""
    <div class='header-box monitor'>
        <h2 style='margin:0; color:#e0eaf4;'>👁️ UNDER THE HOOD - Lab Monitor</h2>
        <p style='opacity:0.85;'>
        פיקוח בזמן אמת על מה שהמכונה לומדת, הנתונים שהיא צוברת והפקטורים שמניעים אותה.
        </p>
    </div>
    """, unsafe_allow_html=True)
    render_trainer_control_panel()

    if not st.session_state.model_archive:
        st.warning("אין עדיין מודלים בספרייה. הרץ אימון ידני או אוטומטי קודם.")
        if st.button("🔄 רענן מודלים"):
            st.session_state.model_archive = load_all_models_from_disk()
            st.rerun()
        return

    slot = st.selectbox("בחר סקטור למעקב:", list(st.session_state.model_archive.keys()))
    safe_slot = clean_filename(str(slot))
    csv_path = f"models/training_data_{safe_slot}.csv"
    model_data = st.session_state.model_archive[slot]
    model = model_data["model"]
    meta = model_data["metadata"]
    df = pd.DataFrame()
    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            pass

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("דיוק (OOB Score)", f"{meta.get('train_acc', 0)*100:.1f}%")
    c2.metric("סה\"כ עסקאות בבסיס הנתונים", len(df) if not df.empty else 0)
    c3.metric("Threshold מומלץ לכניסה", meta.get("recommended_threshold", 50))
    if not df.empty and "label" in df.columns:
        c4.metric("Win Rate היסטורי גולמי", f"{df['label'].mean()*100:.1f}%")
    else:
        c4.metric("Win Rate היסטורי גולמי", "N/A")
    st.markdown("---")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("### 🧬 מה המודל לומד? (Feature Importance)")
        if hasattr(model, "feature_importances_") and hasattr(model, "feature_names_in_"):
            fi_df = pd.DataFrame({
                "Feature": model.feature_names_in_,
                "Importance": model.feature_importances_,
            }).sort_values("Importance", ascending=True).tail(10)
            fig = go.Figure(go.Bar(
                x=fi_df["Importance"],
                y=fi_df["Feature"],
                orientation="h",
            ))
            fig.update_layout(
                margin=dict(l=0, r=0, t=30, b=0),
                height=350,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("המודל לא מכיל מידע על חשיבות פקטורים.")
    with col_b:
        st.markdown("### 📊 התפלגות מניות בספרייה (Top 10)")
        if not df.empty and "ticker" in df.columns:
            ticker_counts = df["ticker"].value_counts().head(10)
            fig2 = go.Figure(go.Pie(
                labels=ticker_counts.index,
                values=ticker_counts.values,
                hole=0.4,
            ))
            fig2.update_layout(
                margin=dict(l=0, r=0, t=30, b=0),
                height=350,
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("אין מספיק נתונים.")
    st.markdown("---")
    st.markdown("### 📈 התפלגות VIX ברגעי עסקאות")
    if not df.empty:
        vix_col = "f_macro_vix_zscore" if "f_macro_vix_zscore" in df.columns else "vix_close" if "vix_close" in df.columns else None
        if vix_col:
            label_vix = "VIX Z-Score" if vix_col == "f_macro_vix_zscore" else "VIX Close"
            mean_vix = df[vix_col].mean()
            fig_vix = go.Figure()
            fig_vix.add_trace(go.Histogram(x=df[vix_col], nbinsx=25, name=label_vix, opacity=0.75))
            fig_vix.add_vline(
                x=mean_vix,
                line_dash="dash",
                annotation_text=f"ממוצע: {mean_vix:.2f}",
                annotation_position="top right",
            )
            fig_vix.update_layout(
                height=350,
                margin=dict(l=0, r=0, t=40, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_vix, use_container_width=True)
        else:
            st.info("לא נמצאו נתוני VIX בקובץ האימון.")
    st.markdown("---")
    st.markdown("### 🕒 עסקאות אחרונות שנסרקו")
    if not df.empty:
        cols_ok = [c for c in ["entry_date", "ticker", "phase", "label"] if c in df.columns]
        show_df = df[cols_ok].sort_values("entry_date", ascending=False).head(15).copy()
        if "label" in show_df.columns:
            show_df["label"] = show_df["label"].apply(lambda x: "✅ הצלחה" if x == 1 else "❌ כישלון")
        show_df.rename(
            columns={
                "entry_date": "תאריך כניסה",
                "ticker": "מניה",
                "phase": "פאזת Wyckoff",
                "label": "סטטוס קצה",
            },
            inplace=True,
        )
        st.dataframe(show_df, use_container_width=True)

# ============================================================
# ML TRAINER — Batched UI
# ============================================================
def screen_ml_trainer():
    st.markdown(
        """
        <div class='header-box ml'>
            <h2 style='margin:0; color:#e0eaf4;'>🧠 WYCKOFF-ANCHORED ML TRAINER — Batched Mode</h2>
            <p style='opacity:0.85;'>
            בחר Batches ספציפיים לאימון ממוקד וחסכוני. כל Batch = 5 מניות.
            האימון רץ כתהליך רקע — לא מתקע את ה-UI.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    running = is_trainer_running()

    # ─── חלק עליון: אימון ידני בודד (Manual Override) ─────────────────
    with st.expander("🔬 אימון ידני בודד (Manual Override)", expanded=False):
        MODEL_SLOTS = ["Growth (צמיחה)", "Value/Index (ערך/מדד)", "Commodities (סחורות)"]
        c1, c2, c3 = st.columns(3)
        with c1:
            train_ticker = st.text_input("סמל לאימון:", "SPY")
        with c2:
            target_slot = st.selectbox("משבצת אסטרטגית:", MODEL_SLOTS)
        with c3:
            train_risk = st.selectbox("רמת סיכון:", ["Aggressive", "Balanced", "Conservative"])
        c4, c5, c6 = st.columns(3)
        with c4:
            start_date = st.date_input("מתאריך:", value=datetime(2020, 1, 1))
        with c5:
            end_date = st.date_input("עד תאריך:", value=datetime.today())
        with c6:
            render_threshold_control("סף כניסה בסיסי:", "base_threshold")
            base_th = st.session_state["base_threshold"]

        if st.button(
            "🚀 התחל למידה ידנית (הוסף לספרייה)",
            use_container_width=True,
            type="primary",
            disabled=running,
        ):
            with st.spinner("שואב עסקאות ומאמן מודל..."):
                df = get_cached_data(
                    train_ticker.upper(),
                    start=start_date.strftime("%Y-%m-%d"),
                    end=end_date.strftime("%Y-%m-%d"),
                )
                if df is None or len(df) < 60:
                    st.error("אין מספיק נתונים.")
                    return
                engine = FactorEngine(BacktestConfig())
                try:
                    bt_df, audit_df = run_wyckoff_anchored_backtest(
                        train_ticker.upper(),
                        use_ai=False,
                        threshold=base_th,
                        period=None,
                        start=start_date.strftime("%Y-%m-%d"),
                        end=end_date.strftime("%Y-%m-%d"),
                        risk_profile=train_risk,
                    )
                except Exception as e:
                    st.error(f"שגיאה בבק-טסט: {e}")
                    return
                if audit_df is None or audit_df.empty:
                    st.error("לא היו עסקאות בתקופה. נסה להוריד את הסף.")
                    return
                features_list = []
                for _, trade in audit_df.iterrows():
                    entry_dt = pd.Timestamp(trade["entry_date"])
                    if entry_dt in bt_df.index:
                        window_df = (
                            df.loc[:entry_dt].iloc[-200:]
                            if len(df.loc[:entry_dt]) > 200
                            else df.loc[:entry_dt]
                        )
                        try:
                            factors = engine.compute(window_df)
                            if len(factors) > 0:
                                feature_row = factors.iloc[-1].to_dict()
                                feature_row["phase"] = bt_df.loc[entry_dt]["wyckoff_phase"]
                                feature_row["label"] = 1 if trade["win"] else 0
                                feature_row["ticker"] = train_ticker.upper()
                                feature_row["entry_date"] = trade["entry_date"]
                                features_list.append(feature_row)
                        except Exception:
                            continue
                if len(features_list) < 3:
                    st.error("מעט מדי עסקאות לאימון.")
                    return
                new_df = pd.DataFrame(features_list)
                os.makedirs(MODEL_DIR, exist_ok=True)
                safe_slot_name = clean_filename(str(target_slot))
                history_path = os.path.join(MODEL_DIR, f"training_data_{safe_slot_name}.csv")
                if os.path.exists(history_path):
                    hist_df = pd.read_csv(history_path)
                    combined_df = (
                        pd.concat([hist_df, new_df], ignore_index=True)
                        .drop_duplicates(subset=["ticker", "entry_date"], keep="last")
                    )
                else:
                    combined_df = new_df
                combined_df.to_csv(history_path, index=False)
                if combined_df["label"].nunique() < 2:
                    st.error("צריך לפחות שתי מחלקות שונות לאימון מודל.")
                    return
                y = combined_df["label"].values
                le = LabelEncoder()
                phase_encoded = le.fit_transform(combined_df["phase"].fillna("לא בתהליך איסוף"))
                phase_dummies = pd.get_dummies(phase_encoded, prefix="phase").astype(int)
                drop_cols = ["phase", "label", "ticker", "entry_date"]
                tech_factors = (
                    combined_df
                    .drop(columns=[c for c in drop_cols if c in combined_df.columns])
                    .select_dtypes(include=[np.number])
                )
                X = (
                    pd.concat(
                        [tech_factors.reset_index(drop=True), phase_dummies.reset_index(drop=True)],
                        axis=1,
                    )
                    .replace([np.inf, -np.inf], np.nan)
                    .fillna(0)
                )
                model = RandomForestClassifier(
                    n_estimators=100, max_depth=3, min_samples_leaf=3,
                    oob_score=True, random_state=42, n_jobs=-1,
                )
                model.fit(X, y)
                try:
                    train_acc = model.oob_score_
                except Exception:
                    train_acc = model.score(X, y)
                optimal_th = calculate_optimal_threshold(model, X, y)
                meta = {
                    "train_ticker": "MANUAL_ADDITION",
                    "train_acc": train_acc,
                    "test_acc": train_acc,
                    "slot": target_slot,
                    "model_type": "Wyckoff-Anchored",
                    "num_trades": len(combined_df),
                    "recommended_threshold": optimal_th,
                }
                save_path = save_model_to_disk(target_slot, model, meta, le)
                st.session_state.model_archive = load_all_models_from_disk()
                st.session_state.ml_model = model
                st.session_state.ml_metadata = meta
                st.session_state.phase_encoder = le
                st.session_state.use_ml = True
                st.success(f"✅ אימון הושלם! מודל נשמר: {save_path}")
                c_r1, c_r2, c_r3 = st.columns(3)
                c_r1.metric("דיוק OOB", f"{train_acc*100:.1f}%")
                c_r2.metric("סה\"כ עסקאות בספרייה", len(combined_df))
                c_r3.metric("🎯 Threshold מומלץ", optimal_th)

    st.markdown("---")

    # ─── חלק מרכזי: בחירת Batches ─────────────────────────────────────
    st.markdown("### 📦 בחר Batches לאימון מבוזר")

    if running:
        status = read_auto_trainer_status()
        st.warning(
            f"⚠️ אימון פעיל כרגע! סטטוס: **{status.get('state','?')}** — "
            f"{status.get('message','')} ({status.get('progress',0)}%)"
        )

    # Session state לשמירת בחירות
    if "batch_selections" not in st.session_state:
        st.session_state.batch_selections = {
            "Growth (צמיחה)": [False] * 10,
            "Value/Index (ערך/מדד)": [False] * 10,
            "Commodities (סחורות)": [False] * 10,
        }

    sector_display_names = {
        "Growth (צמיחה)":       ("🚀", "Growth (צמיחה)", "Growth (צמיחה)"),
        "Value/Index (ערך/מדד)": ("💎", "Value/Index (ערך/מדד)", "Value/Index (ערך/מדד)"),
        "Commodities (סחורות)": ("⛏️", "Commodities (סחורות)", "Commodities (סחורות)"),
    }

    col_growth, col_value, col_commodities = st.columns(3)
    sector_cols = {
        "Growth (צמיחה)": col_growth,
        "Value/Index (ערך/מדד)": col_value,
        "Commodities (סחורות)": col_commodities,
    }

    for sector_key, col in sector_cols.items():
        emoji, display_name, slot_name = sector_display_names[sector_key]
        batches = SECTOR_BATCHES[sector_key]

        with col:
            st.markdown(f"<div class='batch-panel'>", unsafe_allow_html=True)
            st.markdown(f"#### {emoji} {display_name}")

            # כפתורי Select All / Clear All
            sa_col, ca_col = st.columns(2)
            with sa_col:
                if st.button(
                    "✅ הכל",
                    key=f"select_all_{sector_key}",
                    use_container_width=True,
                    disabled=running,
                ):
                    st.session_state.batch_selections[sector_key] = [True] * 10
                    st.rerun()
            with ca_col:
                if st.button(
                    "❌ נקה",
                    key=f"clear_all_{sector_key}",
                    use_container_width=True,
                    disabled=running,
                ):
                    st.session_state.batch_selections[sector_key] = [False] * 10
                    st.rerun()

            st.markdown("<br>", unsafe_allow_html=True)

            # Checkboxes לכל batch
            for i, batch_tickers in enumerate(batches):
                label_tickers = ", ".join(batch_tickers)
                checked = st.checkbox(
                    f"Batch {i+1}: {label_tickers}",
                    value=st.session_state.batch_selections[sector_key][i],
                    key=f"batch_{sector_key}_{i}",
                    disabled=running,
                )
                st.session_state.batch_selections[sector_key][i] = checked

            # ספירת בחירות
            selected_count = sum(st.session_state.batch_selections[sector_key])
            total_tickers_selected = sum(
                len(batches[i])
                for i in range(10)
                if st.session_state.batch_selections[sector_key][i]
            )
            st.caption(f"נבחרו {selected_count} batches — {total_tickers_selected} מניות")

            # כפתור אימון לסקטור זה
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button(
                f"🚀 הפעל אימון — {display_name}",
                key=f"train_sector_{sector_key}",
                use_container_width=True,
                type="primary",
                disabled=running or selected_count == 0 or not TRAINER_AVAILABLE,
            ):
                # בנה רשימת מניות מהbatches הנבחרים
                tickers_to_train = []
                for i, batch_tickers in enumerate(batches):
                    if st.session_state.batch_selections[sector_key][i]:
                        tickers_to_train.extend(batch_tickers)
                # הסר כפילויות תוך שמירת סדר
                tickers_to_train = list(dict.fromkeys(tickers_to_train))

                batch_config = {
                    "slot": slot_name,
                    "tickers": tickers_to_train,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "mode": "batched",
                }
                try:
                    pid_started = start_trainer_process(batch_config=batch_config)
                    st.success(
                        f"✅ אימון Batched התחיל ברקע!\n"
                        f"סקטור: {display_name} | {len(tickers_to_train)} מניות | PID: {pid_started}"
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"שגיאה בהפעלת הטריינר: {e}")

            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")

    # ─── Auto-Trainer Control Panel ────────────────────────────────────
    render_trainer_control_panel()

    st.markdown("---")

    # ─── יומן ריצה ─────────────────────────────────────────────────────
    with st.expander("📝 יומן ריצה ושגיאות", expanded=False):
        if os.path.exists(AUTO_TRAINER_LOG_FILE):
            try:
                with open(AUTO_TRAINER_LOG_FILE, "r", encoding="utf-8") as f:
                    logs = f.read()
                st.text_area("היומן המלא:", logs[-5000:], height=300)
                if # ============================================================
# INSTITUTIONAL SCOUT PRO — FINAL UI V11.0
# Streamlit app for Wyckoff-style market analysis
# ============================================================

from __future__ import annotations

import json
import math
import os
import pickle
import signal
import subprocess
import sys
import time
import traceback
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
# Base paths / environment
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

MODEL_DIR = os.path.join(BASE_DIR, "models")
BATCH_CONFIG_FILE = os.path.join(MODEL_DIR, "batch_config.json")
AUTO_TRAINER_STATUS_FILE = os.path.join(MODEL_DIR, "auto_trainer_status.json")
AUTO_TRAINER_DONE_FLAG = os.path.join(MODEL_DIR, "auto_trainer.done")
AUTO_TRAINER_LOG_FILE = os.path.join(BASE_DIR, "auto_trainer_error.log")
AUTO_TRAINER_PID_FILE = os.path.join(MODEL_DIR, "auto_trainer.pid")
AUTO_TRAINER_STOP_FILE = os.path.join(MODEL_DIR, "auto_trainer.stop")
AUTO_TRAINER_LOCK_FILE = os.path.join(MODEL_DIR, "auto_trainer.lock")

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
except Exception:
    SCOUT_CORE_AVAILABLE = False

    def clean_filename(name: str) -> str:
        keep = []
        for ch in str(name):
            if ch.isalnum() or ch in ("-", "_", "."):
                keep.append(ch)
        return "".join(keep)[:120] or "model"

    @dataclass
    class BacktestConfig:
        lookback: int = 252
        min_bars: int = 60

    class FactorEngine:
        def __init__(self, config: Optional[BacktestConfig] = None):
            self.config = config or BacktestConfig()

        def compute(self, df: pd.DataFrame) -> pd.DataFrame:
            out = pd.DataFrame(index=df.index.copy())
            close = df["Close"].astype(float)
            volume = df["Volume"].astype(float)
            out["ret_1"] = close.pct_change().fillna(0)
            out["ret_5"] = close.pct_change(5).fillna(0)
            out["vol_z"] = ((volume - volume.rolling(20).mean()) / volume.rolling(20).std()).replace([np.inf, -np.inf], np.nan).fillna(0)
            out["range"] = ((df["High"] - df["Low"]) / close.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0)
            out["trend_20"] = close / close.rolling(20).mean() - 1
            out["trend_50"] = close / close.rolling(50).mean() - 1
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
            if df is None or df.empty:
                return None
            return df
        except Exception:
            return None

    def calculate_optimal_threshold(*args, **kwargs):
        return 65

    def check_phase_entry_allowed(*args, **kwargs):
        return True

    def run_wyckoff_anchored_backtest(*args, **kwargs):
        raise NotImplementedError("run_wyckoff_anchored_backtest is only available in scout_core")

    def build_research_ground_truth(*args, **kwargs):
        return pd.DataFrame()

# ============================================================
# App config
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
    "MSTR"
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
    "DG","DLTR","TGT","KR"
]

COMMODITIES_TICKERS = [
    "XOM","CVX","SLB","EOG","OXY","COP","PSX","VLO","FCX","NEM","GOLD","AEM","WPM","FNV","PAAS","AG","GLD","SLV","HAL","BKR","NOV",
    "DVN","FANG","CTRA","MRO","OVV","EQT","WMB","KMI","ET","EPD","MPLX","PAA","TRGP","OKE","LNG","DTM","VMC","MLM","EXP","ALB","SQM",
    "LAC","MP","CCJ","UUUU","UEC","NXE","BHP","RIO","VALE","CLF","X","STLD","NUE","RS","AA","CENX","CDE","HL","EXK","FSM","MAG","SSRM",
    "KGC","IAG","EGO","OR","RGLD","USAS","SILV","HMY","GFI","SBSW","HBM","FCG","URA","COPX","LIT","REMX","URNM","SILJ","GDXJ"
]

SECTOR_MAP: Dict[str, List[str]] = {
    "הכול (כל השוק האמריקאי)": sorted(list(set(GROWTH_TICKERS + VALUE_TICKERS + COMMODITIES_TICKERS))),
    "צמיחה וטכנולוגיה (Growth)": GROWTH_TICKERS,
    "ערך ומדד (Value/Index)": VALUE_TICKERS,
    "סחורות ואנרגיה (Commodities)": COMMODITIES_TICKERS,
}

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
                capture_output=True,
                text=True,
                check=False,
            )
            return str(pid) in result.stdout
        os.kill(pid, 0)
        return True
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
    payload = {
        "model": model,
        "metadata": metadata,
        "phase_encoder": encoder,
    }
    with open(file_path, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    return file_path

def load_all_models_from_disk() -> Dict[str, Dict[str, Any]]:
    ensure_dirs()
    loaded: Dict[str, Dict[str, Any]] = {}
    for filename in os.listdir(MODEL_DIR):
        if not (filename.startswith("model_") and filename.endswith(".pkl")):
            continue
        filepath = os.path.join(MODEL_DIR, filename)
        try:
            with open(filepath, "rb") as f:
                data = pickle.load(f)
            slot = data.get("metadata", {}).get("slot")
            if not slot:
                slot = filename.replace("model_", "").replace(".pkl", "")
            loaded[str(slot)] = data
        except Exception:
            continue
    return loaded

def read_auto_trainer_status() -> Dict[str, Any]:
    default = {
        "state": "idle",
        "message": "לא רץ כרגע",
        "progress": 0,
        "current_slot": "N/A",
        "updated_at": "N/A",
        "started_at": "N/A",
        "finished_at": "N/A",
        "pid": "N/A",
    }
    if os.path.exists(AUTO_TRAINER_STATUS_FILE):
        try:
            with open(AUTO_TRAINER_STATUS_FILE, "r", encoding="utf-8") as f:
                default.update(json.load(f))
        except Exception:
            pass
    elif os.path.exists(AUTO_TRAINER_DONE_FLAG):
        default.update({"state": "completed", "message": "האימון הסתיים", "progress": 100})
    return default

def read_trainer_pid() -> Optional[int]:
    if not os.path.exists(AUTO_TRAINER_PID_FILE):
        return None
    try:
        with open(AUTO_TRAINER_PID_FILE, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        pid = int(raw)
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
    payload = {"requested_at": safe_now()}
    with open(AUTO_TRAINER_STOP_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

def cleanup_stale_trainer_artifacts() -> None:
    pid = read_trainer_pid()
    if pid is None:
        for path in (AUTO_TRAINER_STOP_FILE, AUTO_TRAINER_LOCK_FILE):
            if os.path.exists(path):
                try:
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
    for root, dirs, files in os.walk(BASE_DIR):
        depth = root[len(BASE_DIR):].count(os.sep)
        if depth > 3:
            continue
        if target_name in files:
            return os.path.join(root, target_name)
    return primary

TRAINER_SCRIPT = _hunt_for_trainer()
TRAINER_AVAILABLE = os.path.isfile(TRAINER_SCRIPT)

def start_trainer_process() -> int:
    if not TRAINER_AVAILABLE:
        raise FileNotFoundError(f"קובץ {TRAINER_SCRIPT} לא נמצא")
    if is_trainer_running():
        raise RuntimeError("האימון כבר רץ כרגע")

    ensure_dirs()
    if os.path.exists(AUTO_TRAINER_STOP_FILE):
        try:
            os.remove(AUTO_TRAINER_STOP_FILE)
        except Exception:
            pass

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    log_handle = open(AUTO_TRAINER_LOG_FILE, "a", encoding="utf-8")

    kwargs: Dict[str, Any] = {
        "cwd": os.path.dirname(TRAINER_SCRIPT),
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
        "env": env,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen([sys.executable, TRAINER_SCRIPT], **kwargs)
    write_trainer_pid(proc.pid)
    return int(proc.pid)

def stop_trainer_process(grace_seconds: int = 5) -> bool:
    pid = read_trainer_pid()
    write_stop_request()

    if pid is None:
        cleanup_stale_trainer_artifacts()
        return True

    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(int(pid)), "/T"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.kill(int(pid), signal.SIGTERM)
    except Exception:
        pass

    deadline = time.time() + float(grace_seconds)
    while time.time() < deadline:
        if not _is_pid_running(pid):
            break
        time.sleep(0.25)

    if _is_pid_running(pid):
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                os.kill(int(pid), signal.SIGKILL)
        except Exception:
            pass

    try:
        os.remove(AUTO_TRAINER_PID_FILE)
    except Exception:
        pass

    cleanup_stale_trainer_artifacts()
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
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

def resolve_default_ticker(universe: List[str]) -> str:
    return universe[0] if universe else "AAPL"

# ============================================================
# Session state
# ============================================================

def init_session_state() -> None:
    defaults = {
        "mode": "wyckoff",
        "ml_model": None,
        "ml_metadata": None,
        "use_ml": False,
        "phase_encoder": None,
        "model_archive": load_all_models_from_disk(),
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
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

# ============================================================
# CSS / Theme
# ============================================================

def inject_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Hebrew:wght@300;400;500;600;700&display=swap');

        html, body, [class*="css"]  {
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
            border: 1px solid rgba(125, 155, 190, 0.22);
            background: linear-gradient(135deg, rgba(7,14,25,0.88), rgba(13,25,43,0.92));
            box-shadow: 0 18px 44px rgba(0,0,0,.28);
            margin-bottom: 1rem;
        }

        .main-header h1 {
            margin: 0;
            font-size: 2.0rem;
            line-height: 1.1;
            color: #eaf4ff;
        }

        .main-header p {
            margin: 0.35rem 0 0;
            color: #9db0c9;
            font-size: 0.95rem;
        }

        .glass-card {
            background: rgba(10, 18, 33, 0.85);
            border: 1px solid rgba(125,155,190,0.18);
            border-radius: 20px;
            padding: 1rem 1.1rem;
            box-shadow: 0 14px 30px rgba(0,0,0,.22);
        }

        .section-title {
            font-size: 1.15rem;
            font-weight: 700;
            color: #eaf4ff;
            margin-bottom: 0.4rem;
        }

        .section-subtitle {
            color: #9db0c9;
            margin-bottom: 0.8rem;
            line-height: 1.7;
        }

        .metric-box {
            background: linear-gradient(180deg, rgba(14, 24, 42, 0.94), rgba(10, 18, 33, 0.96));
            border: 1px solid rgba(76, 129, 189, 0.20);
            border-radius: 16px;
            padding: 0.8rem 0.9rem;
        }

        .audit-row {
            padding: 0.85rem 0.95rem;
            margin-bottom: 0.55rem;
            border-radius: 14px;
            border-right: 4px solid;
            background: rgba(15, 23, 42, 0.65);
        }

        .win { border-color: #26a69a; }
        .loss { border-color: #ef5350; }

        .widget-panel-ai {
            background: rgba(10, 18, 33, 0.92);
            border: 1px solid rgba(76, 129, 189, 0.2);
            border-radius: 18px;
            padding: 1rem 1rem 0.2rem;
            margin-bottom: 1rem;
        }

        .mini-hint {
            color: #9db0c9;
            font-size: 0.88rem;
        }

        .stMetric {
            background: rgba(10, 18, 33, 0.88);
            border: 1px solid rgba(125,155,190,0.15);
            border-radius: 16px;
            padding: 0.75rem 0.9rem;
            box-shadow: 0 10px 25px rgba(0,0,0,.18);
        }

        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, rgba(9, 16, 29, 0.98), rgba(7, 11, 21, 0.98));
            border-left: 1px solid rgba(125,155,190,0.14);
        }

        .stTabs [data-baseweb="tab-list"] {
            gap: 0.35rem;
            background: rgba(8, 14, 26, 0.7);
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

        .stTabs [aria-selected="true"] {
            background: rgba(37, 99, 235, 0.18) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

# ============================================================
# Data cache
# ============================================================

@st.cache_data(ttl=3600, show_spinner=False)
def get_cached_data(ticker: str, period: str = "1y", start: Optional[str] = None, end: Optional[str] = None) -> Optional[pd.DataFrame]:
    try:
        effective_period = None if (start or end) else period
        df = get_data(ticker, effective_period, start, end)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass

    try:
        t = yf.Ticker(ticker)
        if start or end:
            df = t.history(start=start, end=end)
        else:
            df = t.history(period=period or "1y")
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    return None

# ============================================================
# Threshold synchronization helpers
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
                    {"range": [0, 35], "color": "rgba(239,83,80,0.22)"},
                    {"range": [35, 65], "color": "rgba(255,193,7,0.22)"},
                    {"range": [65, 100], "color": "rgba(38,166,154,0.22)"},
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
        f"""
        <div class="main-header">
            <h1>{title}</h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_info_banner() -> None:
    if st.session_state.use_ml and st.session_state.ml_model is not None:
        metadata = st.session_state.ml_metadata or {}
        acc = metadata.get("test_acc", metadata.get("train_acc", 0.0))
        rec_th = metadata.get("recommended_threshold", "לא חושב")
        tr_count = metadata.get("num_trades", "?")
        st.info(
            f"🧠 מצב AI פעיל: {metadata.get('slot', 'כללי')} | דיוק OOB: {float(acc) * 100:.1f}% | "
            f"סף מומלץ: {rec_th} | אימון על {tr_count} עסקאות"
        )

def render_active_ai_selector_widget(screen_identifier: str) -> None:
    with st.container(border=False):
        st.markdown('<div class="widget-panel-ai">', unsafe_allow_html=True)
        st.markdown("### 🧠 הגדרות מנוע החלטה")
        col_a, col_b, col_c = st.columns([2, 1.5, 1], vertical_alignment="bottom")

        with col_a:
            if st.session_state.model_archive:
                slots_list = list(st.session_state.model_archive.keys())
                selected_slot = st.selectbox(
                    "בחר מודל מוסדי פעיל",
                    slots_list,
                    key=f"selector_slot_{screen_identifier}",
                )
                if st.button("✅ טען והפעל מודל", key=f"activate_btn_{screen_identifier}", use_container_width=True):
                    target_data = st.session_state.model_archive[selected_slot]
                    st.session_state.ml_model = target_data["model"]
                    st.session_state.ml_metadata = target_data.get("metadata")
                    st.session_state.phase_encoder = target_data.get("phase_encoder")
                    st.session_state.use_ml = True
                    st.success(f"המודל '{selected_slot}' הופעל בהצלחה")
                    st.rerun()
            else:
                st.info("לא נמצאו מודלים בזיכרון. ניתן להריץ אימון מהמסך הייעודי.")
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

def render_sidebar_tools(screen_key: str, default_ticker: str = "AAPL") -> str:
    with st.sidebar:
        st.markdown("## 🧰 כלי מסך")
        ticker = st.text_input("Ticker", value=st.session_state.get(f"{screen_key}_ticker", default_ticker), key=f"{screen_key}_ticker")
        st.caption("הערך נשמר ב-session_state ומתעדכן מיידית בכל שינוי.")
        st.toggle("הפעל שימוש ב-AI", value=st.session_state.use_ml, key=f"{screen_key}_use_ml_toggle", on_change=_sidebar_ai_toggle_sync, args=(screen_key,))
        return ticker.strip().upper() or default_ticker

def _sidebar_ai_toggle_sync(screen_key: str) -> None:
    st.session_state.use_ml = bool(st.session_state.get(f"{screen_key}_use_ml_toggle", st.session_state.use_ml))

def render_trainer_control_panel() -> None:
    cleanup_stale_trainer_artifacts()
    status = read_auto_trainer_status()
    pid = read_trainer_pid()
    running = is_trainer_running()

    st.markdown("### 🚦 Auto-Trainer Control")
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
                stop_trainer_process(grace_seconds=5)
                st.warning("נשלחה בקשת עצירה רכה")
                st.rerun()
            except Exception as e:
                st.error(f"לא ניתן לעצור: {e}")
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
            except Exception as e:
                st.warning(f"שגיאה בקריאת הלוג: {e}")
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
        with st.spinner("מחשב FactorEngine..."):
            df = get_cached_data(ticker.upper())
            if df is None or df.empty:
                st.error("אין נתונים זמינים")
                return
            try:
                engine = FactorEngine(BacktestConfig())
                factors = engine.compute(df)
                phases = engine.get_wyckoff_phase(df)
                cis = engine.composite_cis(factors, df)

                if factors is None or factors.empty or cis is None or len(cis) == 0:
                    st.warning("לא התקבלה תוצאה תקינה מהמנוע")
                    return

                current_phase = str(phases.iloc[-1]) if hasattr(phases, "iloc") else str(phases)
                current_cis = float(cis.iloc[-1]) if hasattr(cis, "iloc") else float(cis)
                allowed = check_phase_entry_allowed(current_phase, current_cis) if callable(check_phase_entry_allowed) else True

                with left:
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Ticker", ticker.upper())
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
                view = factors.tail(12).copy()
                st.dataframe(view, use_container_width=True)

                st.markdown("### Price Snapshot")
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df.index, y=df["Close"], name="Close"))
                if "Volume" in df.columns:
                    fig.add_trace(go.Scatter(x=df.index, y=df["Volume"] / df["Volume"].max() * df["Close"].max(), name="Volume (scaled)", line=dict(dash="dot")))
                fig.update_layout(
                    height=420,
                    margin=dict(l=0, r=0, t=25, b=0),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#d9e6f2"),
                    legend=dict(orientation="h"),
                )
                st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.error(f"שגיאה בחישוב המנוע: {e}")
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
        with st.spinner("מריץ Backtest..."):
            try:
                bt_df, audit_df = run_wyckoff_anchored_backtest(
                    ticker.upper(),
                    st.session_state.use_ml,
                    bt_threshold,
                    period="2y",
                    risk_profile=risk_profile,
                )
            except NotImplementedError:
                st.warning("run_wyckoff_anchored_backtest לא זמין כרגע ב-scout_core.")
                return
            except Exception as e:
                st.error(f"שגיאה בהרצת הבק-טסט: {e}")
                st.code(traceback.format_exc())
                return

            if bt_df is None or bt_df.empty:
                st.error("אין נתוני backtest")
                return

            t_count = len(audit_df) if audit_df is not None else 0
            w_rate = (len(audit_df[audit_df["win"] == True]) / t_count) if t_count > 0 and "win" in audit_df.columns else 0
            s_ret = float(bt_df["Cum_Strategy"].iloc[-1]) if "Cum_Strategy" in bt_df.columns else float("nan")
            baseline = float(bt_df["Cum_Baseline"].iloc[-1]) if "Cum_Baseline" in bt_df.columns else float("nan")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("עסקאות", t_count)
            m2.metric("Win Rate", f"{w_rate:.1%}" if t_count > 0 else "N/A")
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
                        f"""
                        <div class="audit-row {cls}">
                            {emoji} {row.get('entry_date', 'N/A')} → {row.get('exit_date', 'N/A')}<br>
                            פאזה: {row.get('phase_at_entry', 'N/A')} | תשואה: {row.get('return_pct', 'N/A')}% | יציאה: {row.get('exit_type', 'N/A')}
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

def screen_scanner() -> None:
    st.markdown("### 🔎 Market Scanner")
    st.caption("סריקת יקום מניות ואיתור שמות שעוברים את רף הציון.")
    render_active_ai_selector_widget("scanner")

    c1, c2 = st.columns([2.2, 1], vertical_alignment="bottom")
    with c1:
        sector_name = st.selectbox("בחר סקטור", list(SECTOR_MAP.keys()), key="scanner_sector")
    with c2:
        chosen_universe = SECTOR_MAP[sector_name]
        scan_limit = st.slider("כמות מניות לסריקה", 5, max(5, len(chosen_universe)), min(20, len(chosen_universe)), step=5, key="scanner_limit")

    scan_th = render_threshold_control("סף כניסה לסינון", "scan_threshold")

    if st.button("🚀 התחל סריקה", use_container_width=True, type="primary"):
        results: List[Dict[str, Any]] = []
        engine = FactorEngine(BacktestConfig())
        progress = st.progress(0)
        total = max(1, min(scan_limit, len(chosen_universe)))

        for i, ticker in enumerate(chosen_universe[:scan_limit], start=1):
            df = get_cached_data(ticker, period="6mo")
            if df is not None and len(df) > 30:
                try:
                    factors = engine.compute(df)
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
                except Exception:
                    pass
            progress.progress(min(1.0, i / total))

        if results:
            st.success(f"נמצאו {len(results)} מניות מעל {scan_th}")
            st.dataframe(pd.DataFrame(results).sort_values("Score", ascending=False), use_container_width=True)
        else:
            st.warning(f"אף מניה לא חצתה את רף הציון {scan_th}")

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
            if os.path.exists(model_path):
                with open(model_path, "rb") as f:
                    data = f.read()
                download_cols[i % 3].download_button(
                    label=f"⬇️ הורד {slot}",
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
        except Exception:
            df = pd.DataFrame()

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
            fi_df = pd.DataFrame({"Feature": list(model.feature_names_in_), "Importance": list(model.feature_importances_)}).sort_values("Importance", ascending=True).tail(10)
            fig = go.Figure(go.Bar(x=fi_df["Importance"], y=fi_df["Feature"], orientation="h"))
            fig.update_layout(
                height=350,
                margin=dict(l=0, r=0, t=20, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
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
                height=350,
                margin=dict(l=0, r=0, t=20, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#d9e6f2"),
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
        st.warning(f"⏳ אימון פעיל: {status.get('current_slot', 'N/A')} — {status.get('message', '')} ({status.get('progress', 0)}%)")

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
                    st.error("לא נבחרו מניות")
                else:
                    ensure_dirs()
                    config_data = {
                        "slot": slot_name,
                        "tickers": selected_for_slot,
                        "base_threshold": 35,
                        "created_at": safe_now(),
                    }
                    with open(BATCH_CONFIG_FILE, "w", encoding="utf-8") as f:
                        json.dump(config_data, f, ensure_ascii=False, indent=2)

                    try:
                        pid = start_trainer_process()
                        st.success(f"האימון התחיל בהצלחה. PID: {pid}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"שגיאה בהפעלת הטריינר: {e}")
                        st.code(traceback.format_exc())

    st.markdown("---")
    render_trainer_control_panel()

    st.markdown("---")
    st.markdown("### ⚙️ פעולות מערכת")
    if st.button("🧹 נקה קבצי סטטוס ואתחל", use_container_width=True, type="secondary"):
        clear_trainer_artifacts()
        try:
            st.cache_data.clear()
        except Exception:
            pass
        st.session_state.clear()
        st.rerun()

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
    render_header(
        "INSTITUTIONAL SCOUT PRO",
        "ממשק פינטק מוסדי לניתוח Wyckoff, סריקה, Backtest, אימון מודלים ומעקב. Dark-mode פיננסי, יציב ומודולרי.",
    )
    render_info_banner()

# ============================================================
# Main app
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

    with tabs[0]:
        screen_wyckoff()
    with tabs[1]:
        screen_backtest()
    with tabs[2]:
        screen_scanner()
    with tabs[3]:
        screen_ml_trainer()
    with tabs[4]:
        screen_monitor()
    with tabs[5]:
        screen_vp()
    with tabs[6]:
        screen_vwap()
    with tabs[7]:
        screen_composite()

if __name__ == "__main__":
    main()
("🗑️ נקה יומן"):
                    open(AUTO_TRAINER_LOG_FILE, "w").close()
                    st.rerun()
            except Exception as e:
                st.warning(f"לא ניתן לקרוא את קובץ הלוג: {e}")
        else:
            st.info("קובץ היומן עדיין לא נוצר. יופיע כשהאימון יתחיל.")

# ============================================================
# ניתוב
# ============================================================
routes = {
    "wyckoff": screen_wyckoff,
    "vp": screen_vp,
    "vwap": screen_vwap,
    "composite": screen_composite,
    "backtest": screen_backtest,
    "ml": screen_ml_trainer,
    "scanner": screen_scanner,
    "monitor": screen_monitor,
}
routes[st.session_state.mode]()
