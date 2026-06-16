# ============================================================
# INSTITUTIONAL SCOUT PRO — WYCKOFF ANALYST EDITION V14.0
# Streamlit app for advanced Wyckoff-style market analysis
# Optimized for Google Cloud Run
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

logging.basicConfig(
    level=logging.INFO,
    format='{"time": "%(asctime)s", "level": "%(levelname)s", "msg": "%(message)s"}',
    stream=sys.stdout,
)
logger = logging.getLogger("scout")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

_CLOUD_RUN = (
    os.environ.get("K_SERVICE") is not None
    or os.environ.get("CLOUD_RUN", "").lower() == "true"
)
_TMP_ROOT = "/tmp/scout" if _CLOUD_RUN else BASE_DIR

MODEL_DIR               = os.path.join(_TMP_ROOT, "models")
BATCH_CONFIG_FILE       = os.path.join(MODEL_DIR, "batch_config.json")
AUTO_TRAINER_STATUS_FILE= os.path.join(MODEL_DIR, "auto_trainer_status.json")
AUTO_TRAINER_DONE_FLAG  = os.path.join(MODEL_DIR, "auto_trainer.done")
AUTO_TRAINER_LOG_FILE   = os.path.join(_TMP_ROOT, "auto_trainer_error.log")
AUTO_TRAINER_PID_FILE   = os.path.join(MODEL_DIR, "auto_trainer.pid")
AUTO_TRAINER_STOP_FILE  = os.path.join(MODEL_DIR, "auto_trainer.stop")
AUTO_TRAINER_LOCK_FILE  = os.path.join(MODEL_DIR, "auto_trainer.lock")

# ============================================================
# Optional imports from scout_core
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
        explain_score, 
    )
    SCOUT_CORE_AVAILABLE = True
except ImportError as _imp_exc:
    SCOUT_CORE_AVAILABLE = False
    logger.warning("scout_core not available: %s", _imp_exc)
    def explain_score(df: pd.DataFrame, phase: str, cis: float) -> str:
        return f"**ציון CIS:** {cis:.1f}\n**שלב Wyckoff:** {phase}\n\nהמערכת מזהה התנהגות שוק. טען את scout_core.py לקבלת הסבר אנליסט מלא ומקיף."

st.set_page_config(
    layout="wide",
    page_title="Wyckoff Institutional Analyst",
    page_icon="📈",
    initial_sidebar_state="expanded",
)

GROWTH_TICKERS = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","CRM","NFLX","AMD","ADBE","CSCO","TXN","QCOM","INTC","INTU","ADI",
    "PANW","CRWD","FTNT","ZS","DDOG","SNOW","MDB","NET","PLTR","UBER","ABNB","COIN","SOFI","UPST","ONTO","KLAC","LRCX","AMAT",
    "MRVL","SMCI","DELL","HPQ","RBLX","U","TTWO","EA"
]

VALUE_TICKERS = [
    "BRK-B","JPM","JNJ","V","UNH","PG","MA","HD","MRK","ABBV","PEP","KO","COST","WMT","LLY","TMO","MCD","ACN","BAC","ABT","DHR",
    "HON","NKE","AMGN","PM","IBM","SBUX","GS","CAT","BA"
]

COMMODITIES_TICKERS = [
    "XOM","CVX","SLB","EOG","OXY","COP","PSX","VLO","FCX","NEM","GOLD","AEM","WPM","FNV","PAAS","AG","GLD","SLV","HAL","BKR",
    "DVN","FANG","CTRA","MRO"
]

SECTOR_MAP: Dict[str, List[str]] = {
    "הכול (כל השוק האמריקאי)": sorted(list(set(GROWTH_TICKERS + VALUE_TICKERS + COMMODITIES_TICKERS))),
    "צמיחה וטכנולוגיה (Growth)": GROWTH_TICKERS,
    "ערך ומדד (Value/Index)": VALUE_TICKERS,
    "סחורות ואנרגיה (Commodities)": COMMODITIES_TICKERS,
}

MIN_TRADES_FOR_VALID_MODEL = 10
TRADES_FALLBACK_THRESHOLD  = 35

def ensure_dirs() -> None:
    os.makedirs(MODEL_DIR, exist_ok=True)

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
        pass
    return loaded

def render_explain_score(df: pd.DataFrame, phase: str, cis: float, context: str = "") -> None:
    expander_label = f"🧑‍🏫 ניתוח Wyckoff אנושי (ציון {cis:.1f})"
    with st.expander(expander_label, expanded=True):
        try:
            explanation_md = explain_score(df, phase, cis)
            st.markdown(explanation_md)
        except Exception as exc:
            st.warning(f"לא ניתן לחשב הסבר: {exc}")

def inject_css() -> None:
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Hebrew:wght@300;400;500;600;700&display=swap');
        html, body, [class*="css"] {
            font-family: 'IBM Plex Sans Hebrew', sans-serif;
            direction: rtl; text-align: right; background: #0b1220; color: #d9e6f2;
        }
        .main-header {
            padding: 1.15rem 1.4rem; border-radius: 22px;
            background: linear-gradient(135deg, rgba(7,14,25,0.88), rgba(13,25,43,0.92));
            box-shadow: 0 18px 44px rgba(0,0,0,.28); margin-bottom: 1rem; border: 1px solid rgba(125,155,190,0.18);
        }
        .main-header h1 { margin: 0; font-size: 2.1rem; color: #eaf4ff; font-weight: 700; }
        .main-header p { color: #9db0c9; font-size: 1.05rem; }
        .stMetric { background: rgba(10,18,33,0.88); border: 1px solid rgba(59,130,246,0.3); border-radius: 16px; padding: 0.75rem 0.9rem;}
        </style>
    """, unsafe_allow_html=True)

@st.cache_data(ttl=3600, max_entries=64, show_spinner=False)
def get_cached_data(ticker: str, period: str = "1y", start: Optional[str] = None, end: Optional[str] = None):
    return get_data(ticker, period, start, end) if SCOUT_CORE_AVAILABLE else None

def _compute_wyckoff(ticker: str):
    df = get_cached_data(ticker)
    if df is None or df.empty: return None
    engine  = FactorEngine(BacktestConfig())
    factors = engine.compute(df)
    phases  = engine.get_wyckoff_phase(df)
    cis     = engine.composite_cis(factors, df)
    current_phase = str(phases.iloc[-1])
    current_cis   = float(cis.iloc[-1])
    allowed       = check_phase_entry_allowed(current_phase, "Balanced")
    return {"df": df, "factors": factors, "cis": cis, "current_phase": current_phase, "current_cis": current_cis, "allowed": allowed, "num_bars": len(df)}

def _run_scan_row(engine, ticker: str, scan_th: float):
    df = get_cached_data(ticker, period="6mo")
    if df is None or len(df) <= 30: return None
    factors = engine.compute(df)
    cis   = engine.composite_cis(factors, df)
    phase = engine.get_wyckoff_phase(df)
    score = float(cis.iloc[-1])
    if score < scan_th: return None
    return {"Ticker": ticker, "Score": round(score, 1), "Phase": str(phase.iloc[-1]), "_df": df}

def init_session_state() -> None:
    if "model_archive" not in st.session_state:
        st.session_state.model_archive = load_all_models_from_disk()
    if "use_ml" not in st.session_state:
        st.session_state.use_ml = False
    if "ml_model" not in st.session_state:
        st.session_state.ml_model = None

# ============================================================
# Screens
# ============================================================

def screen_wyckoff() -> None:
    st.markdown("### ⬛ Wyckoff Institutional Analyst")
    ticker = st.text_input("Ticker לניתוח", value="NVDA").strip().upper()
    
    if st.button("▶ הרץ ניתוח מוסדי", use_container_width=True, type="primary"):
        with st.spinner("מחשב מנוע Wyckoff מתקדם..."):
            result = _compute_wyckoff(ticker)
        if result is None:
            st.error("אין נתונים זמינים או נדרש לפחות 60 ימי מסחר.")
            return

        left, right = st.columns([1.15, 1])
        with left:
            m1, m2 = st.columns(2)
            m1.metric("Ticker", ticker)
            m2.metric("Phase", result["current_phase"])
            render_explain_score(result["df"], result["current_phase"], result["current_cis"])

        with right:
            st.markdown("### מפת שוק (Price & Volume)")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=result["df"].index, y=result["df"]["Close"], name="Close", line=dict(color='#7dd3fc')))
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#d9e6f2"), margin=dict(l=0, r=0, t=10, b=0)
            )
            st.plotly_chart(fig, use_container_width=True)

def screen_backtest() -> None:
    st.markdown("### 📊 Backtest Engine")
    ticker = st.text_input("Ticker לבדיקה", value="COST").strip().upper()
    bt_threshold = st.slider("סף כניסה (CIS Threshold)", 40, 95, 65)

    if st.button("▶ הרץ סימולציה", type="primary"):
        with st.spinner("מריץ Backtest היסטורי..."):
            df, audit_df = run_wyckoff_anchored_backtest(ticker, st.session_state.use_ml, bt_threshold, period="2y")
        if df is None or df.empty:
            st.error("אין נתונים.")
            return

        t_count = len(audit_df)
        st.metric("עסקאות סה״כ", t_count)
        
        engine = FactorEngine(BacktestConfig())
        cis_series = engine.composite_cis(engine.compute(df), df)
        phases = engine.get_wyckoff_phase(df)
        render_explain_score(df, str(phases.iloc[-1]), float(cis_series.iloc[-1]))

        if audit_df is not None and not audit_df.empty:
            st.dataframe(audit_df)

def screen_scanner() -> None:
    st.markdown("### 🔎 Market Scanner")
    sector_name = st.selectbox("בחר סקטור לסריקה", list(SECTOR_MAP.keys()))
    scan_limit = st.slider("כמות מניות לסריקה", 5, 50, 10)
    scan_th = st.slider("סף מינימלי לתוצאה", 40, 95, 60)

    if st.button("🚀 התחל סריקה מוסדית", type="primary"):
        results = []
        engine = FactorEngine(BacktestConfig())
        for ticker in SECTOR_MAP[sector_name][:scan_limit]:
            row = _run_scan_row(engine, ticker, scan_th)
            if row: results.append(row)
            
        if results:
            top = sorted(results, key=lambda r: r["Score"], reverse=True)[0]
            st.success(f"נמצאו {len(results)} מניות")
            st.dataframe(pd.DataFrame([{k:v for k,v in r.items() if k!="_df"} for r in results]))
            st.markdown(f"#### המובילה: {top['Ticker']}")
            render_explain_score(top["_df"], top["Phase"], top["Score"])
        else:
            st.warning("אף מניה לא עברה את סף ה-CIS הנוכחי.")

def screen_monitor() -> None:
    st.markdown("### 👁️ הורדת מודלים (Cloud Monitor)")
    st.caption("כאן תוכל להוריד מודלים שאומנו על ידי מנוע ה-AI למחשב המקומי שלך.")
    
    if st.button("🔄 רענן מודלים מהדיסק"):
        st.session_state.model_archive = load_all_models_from_disk()
        
    archive = st.session_state.model_archive
    if archive:
        cols = st.columns(3)
        for i, slot in enumerate(list(archive.keys())):
            safe_slot  = clean_filename(str(slot))
            model_path = os.path.join(MODEL_DIR, f"model_{safe_slot}.pkl")
            num_trades = archive[slot].get("metadata", {}).get("num_trades", "?")
            acc = archive[slot].get("metadata", {}).get("train_acc", 0.0)
            
            if os.path.exists(model_path):
                with open(model_path, "rb") as f:
                    data = f.read()
                cols[i % 3].download_button(
                    label=f"⬇️ הורד {slot} | Acc: {acc:.0%}",
                    data=data,
                    file_name=f"model_{safe_slot}.pkl",
                    mime="application/octet-stream",
                    use_container_width=True,
                )
    else:
        st.info("לא נמצאו מודלים בתיקייה. הרץ את הטריינר תחילה.")

def screen_ml_trainer() -> None:
    st.markdown("### 🧠 Wyckoff Pattern AI Trainer")
    st.caption("אימון מודל Random Forest לזיהוי דפוסי איסוף עבר לפי ה-Factor Engine המשודרג.")
    
    if st.button("🚀 הפעל אימון נתונים אסינכרוני", type="primary"):
        ensure_dirs()
        trainer_path = os.path.join(BASE_DIR, "auto_trainer_fixed.py")
        if os.path.exists(trainer_path):
            try:
                subprocess.Popen([sys.executable, trainer_path], cwd=BASE_DIR, close_fds=True)
                st.success("הטריינר רץ ברקע. בדוק את מסך ה-Monitor בקרוב כדי להוריד את הקבצים.")
            except Exception as e:
                st.error(f"שגיאה בהפעלת הטריינר: {e}")
        else:
            st.error("הקובץ auto_trainer_fixed.py לא נמצא בשרת.")

def main() -> None:
    init_session_state()
    inject_css()
    st.markdown('<div class="main-header"><h1>Wyckoff Institutional Analyst</h1><p>מערכת זיהוי דפוסי איסוף, הפצה וכניסת כסף חכם | Cloud Run Edition</p></div>', unsafe_allow_html=True)

    tabs = st.tabs(["⬛ Wyckoff", "📊 Backtest", "🔎 Scanner", "🧠 ML Trainer", "👁️ Monitor"])
    screen_fns = [screen_wyckoff, screen_backtest, screen_scanner, screen_ml_trainer, screen_monitor]
    for tab, fn in zip(tabs, screen_fns):
        with tab: fn()

if __name__ == "__main__":
    main()
