"""
============================================================
INSTITUTIONAL SCOUT PRO V16.8
Streamlit app for advanced Wyckoff-style market analysis
Optimized for Google Cloud Run
============================================================
"""

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
from plotly.subplots import make_subplots
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

MODEL_DIR = os.path.join(_TMP_ROOT, "models")
BATCH_CONFIG_FILE = os.path.join(MODEL_DIR, "batch_config.json")
AUTO_TRAINER_STATUS_FILE = os.path.join(MODEL_DIR, "auto_trainer_status.json")
AUTO_TRAINER_DONE_FLAG = os.path.join(MODEL_DIR, "auto_trainer.done")
AUTO_TRAINER_PID_FILE = os.path.join(MODEL_DIR, "auto_trainer.pid")
AUTO_TRAINER_STOP_FILE = os.path.join(MODEL_DIR, "auto_trainer.stop")
AUTO_TRAINER_LOCK_FILE = os.path.join(MODEL_DIR, "auto_trainer.lock")

AUTO_TRAINER_LOG_FILE = os.path.join(_TMP_ROOT, "auto_trainer_error.log")

try:
    from scout_core import (
        clean_filename, get_data, calculate_optimal_threshold, check_phase_entry_allowed,
        BacktestConfig, FactorEngine, run_wyckoff_anchored_backtest, explain_score,
        calculate_advanced_metrics, calculate_phase_followthrough, explain_score_simple,
        build_smart_money_dashboard, generate_roadmap, calculate_wyckoff_probability,
        detect_failure_risks, generate_replay_analogies, get_fundamental_data
    )
    SCOUT_CORE_AVAILABLE = True
except ImportError:
    try:
        from scout import (
            clean_filename, get_data, calculate_optimal_threshold, check_phase_entry_allowed,
            BacktestConfig, FactorEngine, run_wyckoff_anchored_backtest, explain_score,
            calculate_advanced_metrics, calculate_phase_followthrough, explain_score_simple
        )
        def build_smart_money_dashboard(f): return {}
        def generate_roadmap(p): return {"previous_phase":"-", "next_phase":"-", "action_plan":"", "what_if_success":"", "what_if_fail":""}
        def calculate_wyckoff_probability(d, f, p, m, c): return {"accumulation_chance": c, "breakout_30d": 0, "distribution_risk": 0, "educational_note": ""}
        def detect_failure_risks(d, f, p, a, al, t): return ["מערכת הגנה אינה זמינה במלואה."]
        def generate_replay_analogies(t, p, a, f): return []
        def get_fundamental_data(t, cis_score=None): return {}
        
        SCOUT_CORE_AVAILABLE = True
    except ImportError as _imp_exc:
        SCOUT_CORE_AVAILABLE = False
        logger.warning("scout module not available: %s", _imp_exc)

        def explain_score(df: pd.DataFrame, phase: str, cis: float) -> str:
            return "מערכת ניתוח חסרה. טען את הקובץ המתאים."
            
        def explain_score_simple(df: pd.DataFrame, phase: str, cis: float, allowed: bool) -> str:
            return "חסר מודול."
            
        def calculate_advanced_metrics(trades, initial_capital=100000.0):
            return {}
        
        def calculate_phase_followthrough(df, horizon=20, threshold_pct=0.04):
            return {}

st.set_page_config(
    layout="wide",
    page_title="Wyckoff Institutional Analyst",
    page_icon="📈",
    initial_sidebar_state="expanded",
)

GROWTH_TICKERS = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","CRM","NFLX",
    "AMD","ADBE","CSCO","TXN","QCOM","INTC","INTU","ADI"
]
VALUE_TICKERS = [
    "BRK-B","JPM","JNJ","V","UNH","PG","MA","HD","MRK","ABBV","PEP","KO"
]
COMMODITIES_TICKERS = [
    "XOM","CVX","SLB","EOG","OXY","COP","PSX","VLO","FCX","NEM","GLD","SLV"
]

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
    except Exception:
        pass
    return loaded

def navigate_to(page: str, ticker: Optional[str] = None):
    """פונקציית ניווט חלקה בין מסכים ושמירת סטייט"""
    st.session_state.current_page = page
    if ticker:
        st.session_state.current_ticker = ticker.strip().upper()
    try:
        st.rerun()
    except AttributeError:
        st.experimental_rerun()

def inject_css() -> None:
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Hebrew:wght@300;400;500;600;700&display=swap');
    html, body, [class*="css"] {
        font-family: 'IBM Plex Sans Hebrew', sans-serif;
        direction: rtl; text-align: right; background: #0b1220; color: #d9e6f2;
    }
    .main-header {
        padding: 1.2rem 1.6rem; border-radius: 22px;
        background: linear-gradient(135deg, rgba(7,14,25,0.88), rgba(13,25,43,0.92));
        box-shadow: 0 18px 44px rgba(0,0,0,.28); margin-bottom: 1.5rem;
        border: 1px solid rgba(125,155,190,0.18);
    }
    .main-header h1 { margin: 0; font-size: 2.2rem; color: #eaf4ff; font-weight: 700; }
    .main-header p { color: #9db0c9; font-size: 1.1rem; margin-top: 5px; }
    
    /* Stepper UI */
    .stepper-container {
        display: flex; justify-content: space-between; align-items: center;
        background: #0f172a; padding: 15px 30px; border-radius: 16px;
        border: 1px solid rgba(56, 189, 248, 0.3); margin-bottom: 30px;
        box-shadow: 0 8px 25px rgba(0,0,0,0.2);
    }
    .step-item { font-size: 1.1rem; font-weight: 600; transition: color 0.3s ease; }
    .step-active { color: #38bdf8; text-shadow: 0 0 10px rgba(56,189,248,0.4); }
    .step-inactive { color: #475569; }
    .step-arrow { color: #334155; font-size: 1.2rem; }
    
    /* Global Cards */
    .metric-card {
        background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px; padding: 15px; text-align: center; height: 100%;
        display: flex; flex-direction: column; justify-content: center;
    }
    .metric-label { color: #94a3b8; font-size: 0.9rem; margin-bottom: 5px; font-weight: 600; }
    .metric-value { color: #f8fafc; font-size: 1.8rem; margin: 0; font-weight: bold; }
    
    /* ======== Trading Scout Premium Cards ======== */
    .scout-wrapper { width: 100%; margin-bottom: 40px; }
    .scout-card {
        background: linear-gradient(145deg, rgba(16, 24, 48, 0.95), rgba(28, 40, 68, 0.98));
        border: 1px solid rgba(56, 189, 248, 0.28); border-radius: 22px;
        padding: 32px 28px; box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
    }
    .scout-prob { font-size: 4.8rem; font-weight: 800; color: #38bdf8; margin: 10px 0 16px 0; text-shadow: 0 0 35px rgba(56,189,248,0.45); }
    .roadmap-box {
        background: linear-gradient(145deg, #1e293b, #0f172a) !important;
        border: 1px solid #3b82f6 !important; border-radius: 12px !important;
        padding: 22px !important; margin: 20px 0 !important;
        display: flex; justify-content: center; align-items: center; gap: 15px;
        color: #f8fafc !important; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.25) !important;
    }
    .roadmap-step { display: flex; flex-direction: column; align-items: center; }
    .roadmap-label { font-size: 0.8rem; color: #94a3b8; }
    .roadmap-value { font-weight: 600; color: #f8fafc; }
    .roadmap-arrow { color: #475569; font-size: 1.2rem; font-weight: bold; }
    
    .scout-stats-grid { display: flex; flex-direction: column; gap: 24px; margin-bottom: 24px; }
    .scout-stat-box { flex: 1; background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 16px; padding: 22px; }
    .scout-section-title { color: #e0f2fe; font-size: 1.15rem; font-weight: 700; margin-bottom: 16px; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 10px; }
    .scout-list-item { font-size: 1.05rem; color: #cbd5e1; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; }
    .scout-alert-box { padding: 20px 24px; border-radius: 14px; margin-top: 24px; border-right: 5px solid #dc2626; background: rgba(220, 38, 38, 0.08); }
    .scout-alert-title { font-size: 1.1rem; color:#f8fafc; font-weight:bold; margin-bottom:12px; display:block; }
    .scout-alert-text { font-size: 0.95rem; display:block; color:#cbd5e1; line-height: 1.6; margin-bottom: 6px; }

    div[data-testid="stPopover"] > button {
        background-color: transparent !important; border: 1px solid #475569 !important;
        color: #94a3b8 !important; padding: 4px 12px !important; border-radius: 12px !important;
        font-size: 0.85rem !important; height: auto !important; margin-top: 5px;
    }
    div[data-testid="stPopover"] > button:hover { border-color: #3b82f6 !important; color: #60a5fa !important; }
    
    /* Hot Cards in Home */
    .hot-card-container {
        background: linear-gradient(145deg, #1e293b, #0f172a);
        border: 1px solid rgba(255,255,255,0.1); border-radius: 16px;
        padding: 18px; margin-bottom: 15px; text-align:center;
        transition: transform 0.2s, border-color 0.2s;
    }
    .hot-card-container:hover { transform: translateY(-4px); border-color: #38bdf8; }
    
    </style>
    """, unsafe_allow_html=True)

@st.cache_data(ttl=3600, max_entries=64, show_spinner=False)
def get_cached_data(ticker: str, period: str = "2y", start: Optional[str] = None, end: Optional[str] = None):
    return get_data(ticker, period, start, end) if SCOUT_CORE_AVAILABLE else None

def _compute_wyckoff(ticker: str):
    df = get_cached_data(ticker)
    if df is None or df.empty: return None
    engine = FactorEngine(BacktestConfig())
    factors = engine.compute(df)
    phases = engine.get_wyckoff_phase(df)
    cis = engine.composite_cis(factors, df)
    return {
        "df": df, "factors": factors, "cis": cis,
        "current_phase": str(phases.iloc[-1]), "current_cis": float(cis.iloc[-1]),
        "allowed": check_phase_entry_allowed(str(phases.iloc[-1]), "Balanced")
    }

def init_session_state() -> None:
    if "current_page" not in st.session_state:
        st.session_state.current_page = "Home"
    if "home_view" not in st.session_state:
        st.session_state.home_view = "quick_review"
    if "current_ticker" not in st.session_state:
        st.session_state.current_ticker = "NVDA"
    if "model_archive" not in st.session_state:
        st.session_state.model_archive = load_all_models_from_disk()
    if "use_ml" not in st.session_state:
        st.session_state.use_ml = False
    if "ml_model" not in st.session_state:
        st.session_state.ml_model = None

# ============================================================
# Core Workflow Screens (The Stepper)
# ============================================================

def render_stepper():
    page = st.session_state.current_page
    c1 = "step-active" if page == "Home" else "step-inactive"
    c2 = "step-active" if page == "Deep Analysis" else "step-inactive"
    c3 = "step-active" if page == "Trading Scout" else "step-inactive"
    
    st.markdown(f"""
    <div class="stepper-container">
        <div class="step-item {c1}">1️⃣ מסך הבית וסריקה</div>
        <div class="step-arrow">➔</div>
        <div class="step-item {c2}">2️⃣ ניתוח מעמיק ופונדמנטלי</div>
        <div class="step-arrow">➔</div>
        <div class="step-item {c3}">3️⃣ תוכנית מסחר (Trading Scout)</div>
    </div>
    """, unsafe_allow_html=True)

def screen_home() -> None:
    st.markdown("### 🏠 רדאר הכסף החכם: איפה המוסדיים אוספים סחורה?")
    st.markdown("ברוכים הבאים לתהליך הניתוח המוסדי. בחר את נתיב הפעולה שלך למטה:")
    
    # 3 Big Navigation Buttons
    col_nav1, col_nav2, col_nav3 = st.columns(3)
    
    with col_nav1:
        if st.button("⚡ סקירה מהירה\n(מניות וסקטורים חמים)", use_container_width=True):
            st.session_state.home_view = "quick_review"
    with col_nav2:
        if st.button("🌐 סקירת שוק\n(סורק איסוף מוסדי)", use_container_width=True):
            st.session_state.home_view = "market_review"
    with col_nav3:
        if st.button("🔎 חיפוש פרטני\n(ניתוח מניה ספציפית)", use_container_width=True):
            st.session_state.home_view = "search"

    st.markdown("<hr style='border-color: rgba(255,255,255,0.08); margin:25px 0;'>", unsafe_allow_html=True)
    
    view = st.session_state.home_view
    
    if view == "quick_review":
        st.markdown("#### 🗺️ מפת סקטורים (זרימת הון מוסדית)")
        proxy_sectors = {"טכנולוגיה (XLK)": "XLK", "פיננסים (XLF)": "XLF", "בריאות (XLV)": "XLV", "סמיקונדקטורס (SMH)": "SMH"}
        cols_sec = st.columns(4)
        for i, (sec_name, sec_ticker) in enumerate(proxy_sectors.items()):
            with cols_sec[i]:
                res = _compute_wyckoff(sec_ticker)
                cis_val = res['current_cis'] if res else 0
                color = "#16a34a" if cis_val >= 50 else "#dc2626"
                st.markdown(f"""
                <div style='background:rgba(255,255,255,0.03); padding:15px; border-radius:12px; border-bottom: 4px solid {color}; text-align:center;'>
                    <span style='color:#94a3b8; font-size:0.95rem; display:block; margin-bottom:5px; font-weight:600;'>{sec_name}</span>
                    <span style='color:{color}; font-size:1.6rem; font-weight:bold;'>{cis_val:.1f}</span>
                </div>
                """, unsafe_allow_html=True)
                
        st.markdown("<br>", unsafe_allow_html=True)
        
        st.markdown("#### 🔥 מניות חמות במעקב (Hot List)")
        hot_tickers = ["NVDA", "TSLA", "MSFT", "AAPL", "META", "AMZN"]
        cols_hot = st.columns(3)
        for i, tk in enumerate(hot_tickers):
            with cols_hot[i % 3]:
                with st.spinner(f"טוען נתונים עבור {tk}..."):
                    res = _compute_wyckoff(tk)
                cis_val = res['current_cis'] if res else 0
                phase = res['current_phase'] if res else "לא זמין"
                color = "#16a34a" if cis_val >= 65 else ("#eab308" if cis_val >= 40 else "#dc2626")
                
                st.markdown(f"""
                <div class='hot-card-container' style='border-top: 3px solid {color};'>
                    <h3 style='margin:0; color:#f8fafc; font-size:1.8rem;'>{tk}</h3>
                    <p style='margin:5px 0 0 0; color:#94a3b8; font-size:0.85rem;'>Wyckoff CIS</p>
                    <h2 style='margin:0; color:{color}; text-shadow: 0 0 15px {color}40;'>{cis_val:.1f}</h2>
                    <p style='margin:8px 0 12px 0; color:#cbd5e1; font-size:0.85rem; background:rgba(0,0,0,0.3); border-radius:20px; display:inline-block; padding:4px 12px;'>{phase}</p>
                </div>
                """, unsafe_allow_html=True)
                if st.button(f"נתח את {tk} ➔", key=f"btn_hot_{tk}", use_container_width=True):
                    navigate_to("Deep Analysis", tk)
                    
    elif view == "search":
        st.markdown("#### 🔎 חיפוש וניתוח מניה ספציפית")
        col_s1, col_s2, _ = st.columns([3, 1, 2])
        with col_s1:
            search_ticker = st.text_input("הזן סימול לניתוח (לדוגמה NVDA, AAPL)", value="").strip().upper()
        with col_s2:
            st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
            if st.button("🚀 נתח עכשיו", use_container_width=True, type="primary"):
                if search_ticker:
                    navigate_to("Deep Analysis", search_ticker)
                else:
                    st.error("הזן סימול חוקי.")
                    
    elif view == "market_review":
        st.markdown("#### 🌐 סורק הזדמנויות (Market Scanner)")
        st.caption("מאתר מניות עם שילוב של איסוף מוסדי (CIS > 50) יחד עם תמחור פונדמנטלי סביר (זול/הוגן).")
        if st.button("▶ התחל סריקה (פעולה עשויה לקחת כדקה)", type="primary"):
            with st.spinner("סורק עשרות מניות ואוסף נתונים פונדמנטליים..."):
                results = []
                scan_list = GROWTH_TICKERS[:10] + VALUE_TICKERS[:10] 
                for tkr_scan in scan_list:
                    df = get_cached_data(tkr_scan, "1y")
                    if df is not None and not df.empty and len(df) > 60:
                        engine = FactorEngine(BacktestConfig())
                        factors = engine.compute(df)
                        cis = engine.composite_cis(factors, df).iloc[-1]
                        if cis >= 50:
                            fdata = get_fundamental_data(tkr_scan, cis_score=cis)
                            if fdata and fdata.get("valuation") in ["זול", "הוגן"]:
                                results.append({
                                    "Ticker": tkr_scan,
                                    "Wyckoff CIS": round(float(cis), 1),
                                    "Valuation": fdata.get("valuation", ""),
                                    "Fwd P/E": fdata.get("pe_forward", ""),
                                    "Phase": str(engine.get_wyckoff_phase(df).iloc[-1])
                                })
                if results:
                    df_res = pd.DataFrame(results).sort_values("Wyckoff CIS", ascending=False)
                    st.dataframe(df_res, use_container_width=True)
                    
                    st.markdown("##### ⚡ ניתוח מהיר מתוך התוצאות:")
                    cols_btns = st.columns(min(len(results), 4))
                    for idx, row in enumerate(results[:4]):
                        with cols_btns[idx]:
                            if st.button(f"נתח {row['Ticker']}", key=f"scan_btn_{row['Ticker']}", use_container_width=True):
                                navigate_to("Deep Analysis", row['Ticker'])
                else:
                    st.info("לא נמצאו מניות העונות לקריטריונים המשולבים כרגע.")

def screen_deep_analysis() -> None:
    ticker = st.session_state.current_ticker
    st.markdown(f"## 🔍 ניתוח מעמיק: {ticker}")
    
    col_btn1, col_btn2, _ = st.columns([1, 1, 3])
    with col_btn1:
        if st.button("🔄 חזור לבחירת מניה (Home)", use_container_width=True):
            navigate_to("Home")
    with col_btn2:
        if st.button("▶ המשך לתוכנית מסחר (Trading Scout)", type="primary", use_container_width=True):
            navigate_to("Trading Scout")
            
    st.markdown("---")
    
    if not SCOUT_CORE_AVAILABLE:
        st.error("חסר מודול הליבה.")
        return
        
    with st.spinner(f"מעבד נתונים מקיפים (פונדמנטלי + טכני-מוסדי) עבור {ticker}..."):
        wyckoff_res = _compute_wyckoff(ticker)
        if wyckoff_res is None:
            st.error(f"לא נמצאו נתונים היסטוריים מספקים עבור {ticker}.")
            return
            
        cis_score = wyckoff_res["current_cis"]
        fdata = get_fundamental_data(ticker, cis_score=cis_score)

    # --- חלק עליון: שורה תחתונה משולבת (Wyckoff + Fundamental) ---
    c_left, c_right = st.columns([1, 1])
    with c_left:
        val_text = fdata.get('valuation', 'N/A')
        val_color = fdata.get('valuation_color', '#fff')
        st.markdown(f"""
        <div style='background:#1e293b; padding:20px; border-radius:16px; border-right:6px solid {val_color}; box-shadow:0 8px 20px rgba(0,0,0,0.2); height:100%; display:flex; flex-direction:column; justify-content:center;'>
            <p style='margin:0; color:#94a3b8; text-transform:uppercase; font-size:0.9rem; font-weight:600;'>הערכת שווי פונדמנטלית / תמחור</p>
            <h2 style='margin:5px 0 15px 0; color:#f8fafc; font-size:2.2rem;'>{val_text}</h2>
            <p style='margin:0; font-size:1.15rem; color:#e2e8f0; font-weight:600;'>{fdata.get('synthesis', '')}</p>
        </div>
        """, unsafe_allow_html=True)
    with c_right:
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=cis_score,
            title={'text': "כוח איסוף מוסדי (Wyckoff CIS)", 'font': {'color': "#d9e6f2", 'size': 16}},
            number={'font': {'color': "#d9e6f2", 'size': 35}},
            gauge={
                'axis': {'range': [0, 100], 'tickcolor': "white"},
                'bar': {'color': "rgba(255,255,255,0.4)"},
                'steps': [{'range':[0,40],'color':"#dc2626"}, {'range':[40,65],'color':"#eab308"}, {'range':[65,100],'color':"#16a34a"}],
            }
        ))
        fig_gauge.update_layout(height=180, margin=dict(l=20, r=20, t=30, b=10), paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_gauge, use_container_width=True)

    st.markdown("#### 📊 מטריקות מפתח פיננסיות")
    c1, c2, c3, c4 = st.columns(4)
    def metric_card(col, label, val, desc):
        with col:
            st.markdown(f"<div class='metric-card'><p class='metric-label'>{label}</p><h3 class='metric-value'>{val}</h3></div>", unsafe_allow_html=True)
            with st.popover("מה זה?"): st.write(desc)

    metric_card(c1, "Fwd P/E", fdata.get("pe_forward", "N/A"), "מכפיל רווח עתידי. מבוסס על תחזיות רווח לשנה הבאה. נמוך = זול.")
    metric_card(c2, "PEG", fdata.get("peg", "N/A"), "מכפיל צמיחה. משקלל את המכפיל ביחס לקצב הצמיחה. יחס נמוך מ-1 נחשב אטרקטיבי.")
    metric_card(c3, "P/S", fdata.get("ps", "N/A"), "מכפיל מכירות. שווי שוק חלקי הכנסות. קריטי לחברות טכנולוגיה צומחות.")
    metric_card(c4, "ROE", fdata.get("roe", "N/A"), "תשואה להון העצמי. כמה רווח החברה מייצרת מההון שהושקע בה.")

    st.markdown("---")
    st.markdown("#### 📉 התנהגות המחיר ושלב טכני נוכחי (Price Action)")
    
    chart_df = wyckoff_res["df"].iloc[-150:] 
    fig_chart = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
    fig_chart.add_trace(go.Candlestick(x=chart_df.index, open=chart_df['Open'], high=chart_df['High'], low=chart_df['Low'], close=chart_df['Close'], name="Price"), row=1, col=1)
    colors = ['#16a34a' if c >= o else '#dc2626' for c, o in zip(chart_df['Close'], chart_df['Open'])]
    fig_chart.add_trace(go.Bar(x=chart_df.index, y=chart_df['Volume'], marker_color=colors, name="Volume"), row=2, col=1)
    
    cp_marker = wyckoff_res['current_phase']
    marker_color = "#16a34a" if any(x in cp_marker for x in ["Phase C", "Spring", "Phase D", "Phase E", "Markup", "Accumulation", "Re-accumulation"]) else ("#eab308" if "TRANSITION" in cp_marker else "#dc2626")
    
    fig_chart.add_annotation(
        x=chart_df.index[-1], y=chart_df['Low'].iloc[-1], text=f"📌 {cp_marker}",
        showarrow=True, arrowhead=2, ax=0, ay=45, font=dict(color="white", size=11, weight="bold"),
        bgcolor=marker_color, bordercolor="rgba(255,255,255,0.7)", borderwidth=1, borderpad=3, opacity=0.95
    )
        
    fig_chart.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0), xaxis_rangeslider_visible=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig_chart, use_container_width=True)

    with st.expander("📝 הסבר מילולי פשוט (למה המערכת נתנה את הציון?)", expanded=False):
        st.markdown(explain_score_simple(wyckoff_res["df"], wyckoff_res["current_phase"], wyckoff_res["current_cis"], wyckoff_res["allowed"]))

def screen_trading_scout() -> None:
    ticker = st.session_state.current_ticker
    st.markdown(f"### 📈 תכנון עסקאות והערכת הסתברויות: {ticker}")
    
    col_btn1, col_btn2, _ = st.columns([1, 1, 3])
    with col_btn1:
        if st.button("🔄 חזור לניתוח (Deep Analysis)", use_container_width=True):
            navigate_to("Deep Analysis", ticker)
    with col_btn2:
        mode = st.selectbox("בחר פרופיל רגישות פוזיציה:", ["Conservative", "Balanced", "Optimistic"], index=1, label_visibility="collapsed")
            
    st.markdown("---")
    
    from trading_scout import get_trading_recommendation
    with st.spinner(f"בונה תוכנית מסחר חכמה עבור {ticker}..."):
        try:
            rec_data = get_trading_recommendation(ticker, mode=mode)
        except Exception as e:
            st.error(f"שגיאה בהפקת תוכנית ל-{ticker}: {e}")
            return
            
    if rec_data.get("recommendation") == "ERROR":
        st.warning(rec_data.get('reason'))
        return

    rec = rec_data["recommendation"]
    color_map = {"STRONG BUY": "#22c55e", "BUY": "#4ade80", "HOLD": "#facc15", "SELL": "#fb923c", "STRONG SELL": "#ef4444"}
    color = color_map.get(rec, "#94a3b8")
    
    failure_list = rec_data.get('failure_warnings', [])
    is_safe = any("Clear Skies" in w for w in failure_list)
    is_trap = any("Value Trap" in w for w in failure_list)
    
    alert_border = "#22c55e" if is_safe else ("#f59e0b" if is_trap else "#ef4444")
    alert_bg = "rgba(34, 197, 94, 0.05)" if is_safe else ("rgba(245, 158, 11, 0.08)" if is_trap else "rgba(239, 68, 68, 0.08)")
    
    smart_money_html = "".join([f"<div class='scout-list-item'><span>{k}:</span> <span style='font-weight:600; color:#f8fafc;'>{v}</span></div>" for k, v in rec_data['dashboard'].items()])
    failure_html = "".join([f"<span class='scout-alert-text'>{'⚠️' if 'Value Trap' in warn else '🛡️'} {warn}</span>" for warn in failure_list])
    
    card_parts = [
        "<div class='scout-wrapper'><div class='scout-card'>",
        "<div class='scout-header'>",
        f"<h3 class='scout-title'>{ticker} <span class='scout-title-sub'>| תוכנית מוסדית</span></h3>",
        f"<span class='scout-badge' style='color:{color}; border-color: {color}50;'>{rec}</span>",
        "</div>",
        "<div class='scout-prob-container'>",
        "<p style='color:#cbd5e1; font-weight:600; margin-bottom:0;'>הסתברות לאיסוף מוסדי</p>",
        f"<div class='scout-prob' style='color: {color}; text-shadow: 0 0 40px {color}60;'>{rec_data['prob_engine']['accumulation_chance']}%</div>",
        "<div class='scout-phase-pill'>",
        "<span style='color:#94a3b8;'>Wyckoff Phase:</span> ",
        f"<span style='color:#f8fafc; font-weight:700;'>{rec_data['current_phase']}</span>",
        "</div></div>",
        
        "<div class='roadmap-box'>",
        f"<div class='roadmap-step'><span class='roadmap-label'>היינו ב:</span><span class='roadmap-value'>{rec_data.get('roadmap', {}).get('previous_phase', '-')}</span></div>",
        "<div class='roadmap-arrow'>←</div>",
        f"<div class='roadmap-step'><span class='roadmap-label'>אנחנו ב:</span><span class='roadmap-value' style='color:#38bdf8;'>{rec_data['current_phase']}</span></div>",
        "<div class='roadmap-arrow'>←</div>",
        f"<div class='roadmap-step'><span class='roadmap-label'>היעד סביר:</span><span class='roadmap-value'>{rec_data.get('roadmap', {}).get('next_phase', '-')}</span></div>",
        "</div>",
        f"<div style='text-align:center; font-size:0.95rem; color:#cbd5e1; margin-bottom: 20px;'>💡 <b>פעולה נדרשת:</b> {rec_data.get('roadmap', {}).get('action_plan', '')}</div>",
        
        "<div class='scout-stats-grid'>",
        "<div class='scout-stat-box'><div class='scout-section-title'>📊 מנוע הסתברויות</div>",
        f"<div class='scout-list-item'><span>סיכוי פריצה (30 יום):</span> <span style='color:#34d399; font-weight:bold;'>{rec_data['prob_engine']['breakout_30d']}% 🚀</span></div>",
        f"<div class='scout-list-item'><span>סיכון הפצה/שבירה:</span> <span style='color:#ef4444; font-weight:bold;'>{rec_data['prob_engine']['distribution_risk']}% 📉</span></div>",
        "</div>",
        
        "<div class='scout-stat-box'><div class='scout-section-title'>👁️ Smart Money Flow</div>",
        smart_money_html,
        "</div>",
        
        "<div class='scout-stat-box'><div class='scout-section-title'>🏢 שילוב פונדמנטלי מתומצת</div>",
        f"<div class='scout-list-item'><span>מכפיל עתידי (Fwd P/E):</span> <span style='font-weight:bold; color:{rec_data.get('fundamental', {}).get('valuation_color', '#fff')}'>{rec_data.get('fundamental', {}).get('pe_forward', 'N/A')} ({rec_data.get('fundamental', {}).get('valuation', '-')})</span></div>",
        f"<div class='scout-list-item'><span>דוח רווחים קרוב:</span> <span>{rec_data.get('fundamental', {}).get('next_earnings', 'N/A')}</span></div>",
        f"<div class='scout-list-item'><span>סינתזה:</span> <span style='font-weight:bold;'>{rec_data.get('fundamental', {}).get('synthesis', '-')}</span></div>",
        "</div>",
        "</div>", 
        
        f"<div class='scout-alert-box' style='border-color: {alert_border}; background: {alert_bg};'>",
        "<span class='scout-alert-title'>🛡️ מערכת הגנה ממלכודות (Failure Detection):</span>",
        failure_html,
        "</div></div></div>"
    ]
    st.markdown("".join(card_parts), unsafe_allow_html=True)
    
    st.markdown("#### 🎯 תוכנית מסחר וניהול סיכונים (Trading Plan)")
    st.markdown(f"**פעולה מומלצת:** {rec_data['action']}")
    st.markdown(f"**מחיר סגירה אחרון (Close):** ${rec_data['entry_price']:.2f}")
    if rec not in ("SELL", "STRONG SELL"):
        st.markdown(f"**הגנת הפסד דינמית (SL):** ${rec_data['stop_loss_price']:.2f} ({rec_data['stop_loss_pct']:.1f}%)")
        if rec in ("BUY", "STRONG BUY"):
            st.markdown(f"**יעד ראשון חלקי (TP1):** ${rec_data['tp1_price']:.2f} (+{rec_data['tp1_pct']:.1f}%)")
            st.markdown(f"**יעד שני מלא (TP2):** ${rec_data['tp2_price']:.2f} (+{rec_data['tp2_pct']:.1f}%)")
            st.markdown(f"**יחס סיכוי/סיכון (R/R):** {rec_data['rr_ratio']}")

# ============================================================
# Advanced Tools (Sidebar / Alternative Routes)
# ============================================================

def screen_backtest() -> None:
    st.markdown("### 📊 Backtest Engine")
    col1, col2 = st.columns([1,1])
    ticker = col1.text_input("Ticker לבדיקה", value=st.session_state.current_ticker).strip().upper()
    bt_period = col2.selectbox("תקופת Backtest:", ["1y", "2y", "5y", "10y", "max"], index=1)
    bt_threshold = st.slider("סף כניסה (CIS Threshold)", 40, 95, 65)

    if st.button("▶ הרץ סימולציה", type="primary"):
        with st.spinner("מריץ Backtest היסטורי..."):
            df, audit_df = run_wyckoff_anchored_backtest(ticker, st.session_state.use_ml, bt_threshold, period=bt_period)
        if df is None or df.empty:
            st.error("אין נתונים.")
            return
        t_count = len(audit_df)
        if t_count > 0:
            win_rate = audit_df['is_win'].mean() * 100
            total_profit_pct = df['Cum_Strategy'].iloc[-1] * 100 if 'Cum_Strategy' in df.columns else 0.0
            st.success(f"בוצעו {t_count} עסקאות. רווח מצטבר: {total_profit_pct:.2f}%. אחוז הצלחה: {win_rate:.1f}%.")
            st.dataframe(audit_df)
        else:
            st.warning("לא בוצעו עסקאות שעמדו בתנאים.")

def screen_monitor() -> None:
    st.markdown("### 👁️ Institutional Performance Monitor")
    st.info("כלי ניטור מדדים מתקדמים.")

def screen_ml_trainer() -> None:
    st.markdown("### 🧠 ML Trainer")
    st.info("מודול למידת מכונה (Machine Learning) מותאם ל-Cloud Run.")

def main() -> None:
    init_session_state()
    inject_css()

    st.markdown(
        '<div class="main-header"><h1>📈 Wyckoff Institutional Analyst</h1>'
        '<p>מערכת זיהוי דפוסי איסוף, הפצה וכניסת כסף חכם | אסטרטגיה מוסדית</p></div>',
        unsafe_allow_html=True
    )

    # חלוקה בין זרימת עבודה מרכזית לכלים מתקדמים באמצעות סרגל צד
    st.sidebar.markdown("### 🚀 תהליך ניתוח מרכזי")
    if st.sidebar.button("🏠 מסך הבית (חיפוש וסריקה)", use_container_width=True): navigate_to("Home")
    if st.sidebar.button("🔍 ניתוח נכס מעמיק", use_container_width=True): navigate_to("Deep Analysis")
    if st.sidebar.button("📈 בניית תוכנית מסחר", use_container_width=True): navigate_to("Trading Scout")
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🛠️ כלים מתקדמים למפתחים")
    if st.sidebar.button("📊 Backtest", use_container_width=True): navigate_to("Backtest")
    if st.sidebar.button("👁️ Monitor", use_container_width=True): navigate_to("Monitor")
    if st.sidebar.button("🧠 ML Trainer", use_container_width=True): navigate_to("ML Trainer")

    # ניתוב עמודים בהתאם לסטייט הנוכחי
    page = st.session_state.current_page
    if page in ["Home", "Deep Analysis", "Trading Scout"]:
        render_stepper()
        if page == "Home": screen_home()
        elif page == "Deep Analysis": screen_deep_analysis()
        elif page == "Trading Scout": screen_trading_scout()
    else:
        if page == "Backtest": screen_backtest()
        elif page == "Monitor": screen_monitor()
        elif page == "ML Trainer": screen_ml_trainer()

if __name__ == "__main__":
    main()
