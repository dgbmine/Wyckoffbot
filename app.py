"""
============================================================
INSTITUTIONAL SCOUT PRO V17.0 (Unified UX / Hamburger / Price Headers)
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

SCOUT_CORE_IMPORT_ERROR: Optional[str] = None

try:
    from scout_core import (
        clean_filename, get_data, calculate_optimal_threshold, check_phase_entry_allowed,
        BacktestConfig, FactorEngine, run_wyckoff_anchored_backtest, explain_score,
        calculate_advanced_metrics, calculate_phase_followthrough, explain_score_simple,
        build_smart_money_dashboard, generate_roadmap, calculate_wyckoff_probability,
        detect_failure_risks, generate_replay_analogies, get_fundamental_data,
        synthesize_verdict
    )
    SCOUT_CORE_AVAILABLE = True
except Exception as _imp_exc1:
    _first_error = f"{type(_imp_exc1).__name__}: {_imp_exc1}"
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
        def get_fundamental_data(t): return {}
        def synthesize_verdict(fd, c, p, t=""): return {"headline":"-","detail":"-","color":"#94a3b8","tier":"NEUTRAL"}
        
        SCOUT_CORE_AVAILABLE = True
    except Exception as _imp_exc2:
        SCOUT_CORE_AVAILABLE = False
        SCOUT_CORE_IMPORT_ERROR = f"scout_core: {_first_error} | scout (fallback): {type(_imp_exc2).__name__}: {_imp_exc2}"
        logger.warning("scout module not available: %s", SCOUT_CORE_IMPORT_ERROR)

        def explain_score(df: pd.DataFrame, phase: str, cis: float) -> str:
            return "מערכת ניתוח חסרה. טען את הקובץ המתאים."
            
        def explain_score_simple(df: pd.DataFrame, phase: str, cis: float, allowed: bool) -> str:
            return "חסר מודול."
            
        def calculate_advanced_metrics(trades, initial_capital=100000.0):
            return {}
        
        def calculate_phase_followthrough(df, horizon=20, threshold_pct=0.04):
            return {}

        def synthesize_verdict(fd, c, p, t=""):
            return {"headline": "מערכת סינתזה חסרה.", "detail": "-", "color": "#94a3b8", "tier": "NEUTRAL"}


st.set_page_config(
    layout="wide",
    page_title="Wyckoff Institutional Analyst",
    page_icon="📈",
    initial_sidebar_state="expanded",
)

GROWTH_TICKERS = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","CRM","NFLX",
    "AMD","ADBE","CSCO","TXN","QCOM","INTC","INTU","ADI",
    "PANW","CRWD","FTNT","ZS","DDOG","SNOW","MDB","NET","PLTR",
    "UBER","ABNB","COIN","SOFI","UPST","ONTO","KLAC","LRCX","AMAT",
    "MRVL","SMCI","DELL","HPQ","RBLX","U","TTWO","EA"
]

VALUE_TICKERS = [
    "BRK-B","JPM","JNJ","V","UNH","PG","MA","HD","MRK","ABBV","PEP","KO",
    "COST","WMT","LLY","TMO","MCD","ACN","BAC","ABT","DHR",
    "HON","NKE","AMGN","PM","IBM","SBUX","GS","CAT","BA"
]

COMMODITIES_TICKERS = [
    "XOM","CVX","SLB","EOG","OXY","COP","PSX","VLO","FCX","NEM",
    "GOLD","AEM","WPM","FNV","PAAS","AG","GLD","SLV",
    "HAL","BKR","DVN","FANG","CTRA","MRO"
]

SECTOR_MAP: Dict[str, List[str]] = {
    "הכול (כל השוק האמריקאי)": sorted(list(set(GROWTH_TICKERS + VALUE_TICKERS + COMMODITIES_TICKERS))),
    "צמיחה וטכנולוגיה (Growth)": GROWTH_TICKERS,
    "ערך ומדד (Value/Index)": VALUE_TICKERS,
    "סחורות ואנרגיה (Commodities)": COMMODITIES_TICKERS,
}

MIN_TRADES_FOR_VALID_MODEL = 10
TRADES_FALLBACK_THRESHOLD = 35

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

def render_explain_score(df: pd.DataFrame, phase: str, cis: float, expanded: bool = False) -> None:
    expander_label = f"🔬 מידע למקצוענים - Evidence Ledger ונתונים גולמיים (CIS: {cis:.1f})"
    with st.expander(expander_label, expanded=expanded):
        try:
            explanation_md = explain_score(df, phase, cis)
            st.markdown(explanation_md)
        except Exception as exc:
            st.warning(f"לא ניתן לחשב הסבר: {exc}")

def render_monitor_metrics(metrics: dict):
    st.markdown("### 📊 ביצועי מסחר (מערכת Backtest כספית)")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("רווח נקי (Total Profit)", f"${metrics['total_profit']:,.2f}")
    with col2:
        st.metric("דרואו דאון מקסימלי (Max DD)", f"{metrics['max_drawdown']:.2f}%")
    with col3:
        st.metric("סה\"כ עסקאות (Total Trades)", metrics['total_trades'])
        st.caption(f"✅ {metrics['winning_trades']} מרוויחות | ❌ {metrics['losing_trades']} מפסידות")
    with col4:
        st.metric("אישורי וואיקוף - אחוזי הצלחה", f"{metrics['wyckoff_success_rate']:.1f}%")
    
    if metrics.get('annual_pnl'):
        st.markdown("#### 📅 דוח רווח/הפסד שנתי")
        annual_df = pd.DataFrame([
            {"שנה": str(year), "רווח/הפסד ($)": pnl}
            for year, pnl in metrics['annual_pnl'].items()
        ]).sort_values("שנה")
        
        def color_pnl(val):
            color = '#16a34a' if val > 0 else '#dc2626'
            return f'color: {color}'
            
        st.dataframe(annual_df.style.map(color_pnl, subset=['רווח/הפסד ($)']), use_container_width=True, hide_index=True)
    else:
        st.info("אין נתוני מסחר שנתיים להצגה.")

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
    
    [data-testid="stMetric"] {
        background: rgba(15, 23, 42, 0.95) !important;
        border: 1px solid rgba(56, 189, 248, 0.3) !important;
        border-radius: 12px;
        padding: 1.2rem;
    }
    [data-testid="stMetricValue"] { color: #38bdf8 !important; font-weight: 700 !important; }
    [data-testid="stMetricLabel"] { color: #f1f5f9 !important; font-weight: 500 !important; }
    [data-testid="stMetricDelta"] { color: #34d399 !important; }
    
    /* ======== Trading Scout Premium Cards ======== */
    .scout-wrapper {
        width: 100%;
        margin-bottom: 40px; 
    }
    .scout-card {
        background: linear-gradient(145deg, rgba(16, 24, 48, 0.95), rgba(28, 40, 68, 0.98));
        border: 1px solid rgba(56, 189, 248, 0.28);
        border-radius: 22px;
        padding: 32px 28px;
        box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
        transition: transform 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease;
        position: relative;
        overflow: hidden;
    }
    .scout-card::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0; height: 5px;
        background: linear-gradient(90deg, transparent, #38bdf8, transparent);
        opacity: 0.85;
    }
    .scout-card:hover {
        transform: translateY(-4px);
        border-color: rgba(56, 189, 248, 0.7);
        box-shadow: 0 20px 55px rgba(0, 0, 0, 0.45);
    }
    .scout-header {
        display: flex; justify-content: space-between; align-items: center; 
        margin-bottom: 24px;
    }
    .scout-title { 
        color: #f8fafc; font-size: 2rem; font-weight: 800; 
        margin: 0; letter-spacing: 0.5px; display: flex; align-items: center;
    }
    .scout-title-sub { font-size: 1.1rem; color: #94a3b8; font-weight: 400; padding-right: 12px; }
    .scout-badge {
        padding: 8px 20px; border-radius: 30px; 
        font-size: 1rem; font-weight: 700; letter-spacing: 0.5px;
        background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.15);
    }
    .scout-prob-container { text-align: center; margin-bottom: 20px; }
    .scout-prob-label { margin:0; color:#cbd5e1; font-weight: 600; letter-spacing: 1.5px; font-size: 1rem; text-transform: uppercase; }
    .scout-prob { 
        font-size: 4.8rem; font-weight: 800; color: #38bdf8; 
        margin: 10px 0 16px 0; line-height: 1;
        text-shadow: 0 0 35px rgba(56,189,248,0.45); 
    }
    .scout-phase-pill {
        display: inline-block; background: rgba(0,0,0,0.35); padding: 10px 20px; 
        border-radius: 25px; border: 1px solid rgba(255,255,255,0.08);
    }
    
    /* ======== Roadmap In-Card ======== */
    .roadmap-box {
        background: rgba(255, 255, 255, 0.03);
        border-radius: 14px;
        padding: 22px 28px;
        margin-top: 24px;
        margin-bottom: 14px;
        border-right: 3px solid #38bdf8;
        display: flex;
        justify-content: center;
        align-items: center;
        gap: 28px;
        font-size: 1rem;
        color: #94a3b8;
        flex-wrap: wrap;
    }
    .roadmap-step {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 4px;
    }
    .roadmap-label { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 6px; color: #64748b; }
    .roadmap-value { font-weight: 600; color: #f8fafc; font-size: 1.02rem; }
    .roadmap-arrow { color: #475569; font-size: 1.3rem; font-weight: bold; }
    
    .scout-divider {
        border-top: 1px solid rgba(255,255,255,0.08); margin: 28px 0;
    }
    
    /* ======== Stacked Vertical Layout for Sections ======== */
    .scout-stats-grid { 
        display: flex; 
        flex-direction: column; /* CHANGED FROM ROW TO COLUMN */
        gap: 24px; 
        margin-bottom: 24px; 
    }
    .scout-stat-box {
        flex: 1; background: rgba(255, 255, 255, 0.02);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 16px; padding: 22px; display: flex; flex-direction: column;
    }
    .scout-section-title {
        color: #e0f2fe; font-size: 1.15rem; font-weight: 700; 
        margin-bottom: 16px; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 10px;
    }
    .scout-list-item {
        font-size: 1.05rem; color: #cbd5e1; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;
    }
    .scout-alert-box {
        padding: 20px 24px; border-radius: 14px; margin-top: 24px;
        border-right: 5px solid #dc2626; background: rgba(220, 38, 38, 0.08);
    }
    .scout-alert-title { font-size: 1.1rem; color:#f8fafc; font-weight:bold; margin-bottom:12px; display:block; }
    .scout-alert-text { font-size: 0.95rem; display:block; color:#cbd5e1; line-height: 1.6; margin-bottom: 6px; }
    .trap-section-label {
        font-size: 0.85rem; color: #94a3b8; font-weight: 700; text-transform: uppercase;
        letter-spacing: 0.5px; margin: 14px 0 8px 0; display: block;
    }
    .trap-fund-highlight {
        background: rgba(239, 68, 68, 0.12);
        border-right: 3px solid #ef4444;
        padding: 10px 14px;
        border-radius: 8px;
        font-weight: 600;
        color: #fecaca !important;
    }
    
    .edu-box {
        background: rgba(56, 189, 248, 0.05);
        border-right: 4px solid #38bdf8;
        padding: 16px;
        margin-top: 20px;
        border-radius: 8px;
        font-size: 0.95rem;
        color: #e2e8f0;
        line-height: 1.7;
        flex-grow: 1; 
    }
    .edu-box-title {
        color:#38bdf8; 
        font-weight: 700;
        display:block; 
        margin-bottom:10px;
        font-size: 1.05rem;
    }

    /* ======== Fundamental Analysis Screen ======== */
    .fund-card {
        background: rgba(255, 255, 255, 0.02);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 18px;
        padding: 28px 30px;
        margin-bottom: 22px;
    }
    .fund-verdict-box {
        text-align: center;
        border-radius: 18px;
        padding: 26px;
        margin-bottom: 22px;
        border: 1px solid rgba(255,255,255,0.08);
    }
    .fund-verdict-label { font-size: 1rem; color: #94a3b8; margin-bottom: 6px; }
    .fund-verdict-value { font-size: 2.4rem; font-weight: 800; letter-spacing: 0.5px; }
    .fund-verdict-sub { font-size: 0.95rem; color: #cbd5e1; margin-top: 8px; }
    .fund-synth-box {
        background: rgba(56, 189, 248, 0.06);
        border-right: 4px solid #38bdf8;
        border-radius: 12px;
        padding: 18px 22px;
        margin-bottom: 22px;
        font-size: 1.1rem;
        font-weight: 700;
        color: #f8fafc;
    }
    .fund-meta-row {
        display: flex; gap: 18px; flex-wrap: wrap; margin-bottom: 22px;
    }
    .fund-meta-box {
        flex: 1; min-width: 220px;
        background: rgba(255, 255, 255, 0.02);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 14px; padding: 18px 20px;
    }
    .fund-meta-label { font-size: 0.85rem; color: #94a3b8; margin-bottom: 6px; }
    .fund-meta-value { font-size: 1.2rem; font-weight: 700; color: #f8fafc; }
    .fund-table-title {
        color: #e0f2fe; font-size: 1.15rem; font-weight: 700;
        margin-bottom: 14px; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 10px;
    }

    /* ======== Institutional Map Visual Layout ======== */
    .map-card {
        background: linear-gradient(180deg, rgba(16, 24, 45, 0.95) 0%, rgba(12, 18, 36, 0.6) 100%);
        padding: 32px 26px; border-radius: 20px; text-align: center;
        box-shadow: 0 8px 30px rgba(0,0,0,0.3); margin-bottom: 30px;
        border: 1px solid rgba(255,255,255,0.08);
        transition: transform 0.25s ease, background 0.25s ease, border-color 0.25s ease;
    }
    .map-card:hover {
        transform: translateY(-5px); border-color: rgba(56, 189, 248, 0.5);
        background: linear-gradient(180deg, rgba(22, 36, 62, 0.98) 0%, rgba(12, 18, 36, 0.7) 100%);
    }
    .map-card h4 { margin:0; font-size:1.4rem; color:#f8fafc; font-weight:700; letter-spacing: 0.5px; }
    .map-card-label { font-size:1rem; color:#94a3b8; margin: 12px 0 6px 0; font-weight:600; text-transform: uppercase; letter-spacing: 1px; }
    .map-card-score { margin:0; font-size: 3.4rem; font-weight:800; line-height: 1.1; }
    .map-desc {
        font-size: 0.95rem; color: #cbd5e1; margin-top: 20px; line-height: 1.6; padding-top: 16px; border-top: 1px dashed rgba(255,255,255,0.15);
    }
    /* ======== Top Navigation Bar (persistent hamburger, top-right) ======== */
    .topnav-spacer { height: 8px; }
    div[data-testid="stHorizontalBlock"] .nav-btn-wrap button {
        background: rgba(255,255,255,0.04) !important;
        border: 1px solid rgba(56,189,248,0.18) !important;
        color: #cbd5e1 !important;
        border-radius: 12px !important;
        font-weight: 600 !important;
    }

    /* ======== Price + Timestamp Header (appears next to every ticker) ======== */
    .price-header {
        display: inline-flex; flex-direction: column; align-items: flex-start;
        background: linear-gradient(145deg, rgba(30,41,59,0.7), rgba(15,23,42,0.92));
        padding: 10px 22px; border-radius: 14px; margin: 6px 0 14px 0;
        border: 1px solid rgba(56, 189, 248, 0.22);
        box-shadow: 0 4px 15px rgba(0,0,0,0.22);
    }
    .price-header .ph-ticker { font-size: 0.95rem; color: #94a3b8; font-weight: 600; }
    .price-header .ph-price  { font-size: 1.9rem; color: #f8fafc; font-weight: 800; line-height: 1.1; }
    .price-header .ph-time   { font-size: 0.78rem; color: #64748b; margin-top: 2px; }
    .price-header .ph-chg-pos { color: #34d399; font-weight: 700; font-size: 1rem; }
    .price-header .ph-chg-neg { color: #f87171; font-weight: 700; font-size: 1rem; }

    /* ======== Unified Verdict Banner (Wyckoff + Fundamental in one) ======== */
    .verdict-banner {
        border-radius: 18px; padding: 22px 26px; margin: 8px 0 20px 0;
        border: 1px solid rgba(255,255,255,0.08);
        display: flex; flex-direction: column; gap: 8px;
    }
    .verdict-headline { font-size: 1.55rem; font-weight: 800; letter-spacing: 0.3px; }
    .verdict-detail { font-size: 1rem; color: #e2e8f0; line-height: 1.6; }
    .verdict-chips { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 6px; }
    .verdict-chip {
        background: rgba(0,0,0,0.28); border: 1px solid rgba(255,255,255,0.1);
        border-radius: 20px; padding: 6px 16px; font-size: 0.9rem; color: #cbd5e1; font-weight: 600;
    }
    .reason-box {
        background: rgba(56, 189, 248, 0.05); border-right: 4px solid #38bdf8;
        border-radius: 10px; padding: 14px 18px; margin: 6px 0 18px 0;
        font-size: 0.98rem; color: #e2e8f0; line-height: 1.7;
    }
    </style>""", unsafe_allow_html=True)

@st.cache_data(ttl=3600, max_entries=64, show_spinner=False)
def get_cached_data(ticker: str, period: str = "2y", start: Optional[str] = )
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

SCOUT_CORE_IMPORT_ERROR: Optional[str] = None

try:
    from scout_core import (
        clean_filename, get_data, calculate_optimal_threshold, check_phase_entry_allowed,
        BacktestConfig, FactorEngine, run_wyckoff_anchored_backtest, explain_score,
        calculate_advanced_metrics, calculate_phase_followthrough, explain_score_simple,
        build_smart_money_dashboard, generate_roadmap, calculate_wyckoff_probability,
        detect_failure_risks, generate_replay_analogies, get_fundamental_data
    )
    SCOUT_CORE_AVAILABLE = True
except Exception as _imp_exc1:
    _first_error = f"{type(_imp_exc1).__name__}: {_imp_exc1}"
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
        def get_fundamental_data(t): return {}
        
        SCOUT_CORE_AVAILABLE = True
    except Exception as _imp_exc2:
        SCOUT_CORE_AVAILABLE = False
        SCOUT_CORE_IMPORT_ERROR = f"scout_core: {_first_error} | scout (fallback): {type(_imp_exc2).__name__}: {_imp_exc2}"
        logger.warning("scout module not available: %s", SCOUT_CORE_IMPORT_ERROR)

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
    "AMD","ADBE","CSCO","TXN","QCOM","INTC","INTU","ADI",
    "PANW","CRWD","FTNT","ZS","DDOG","SNOW","MDB","NET","PLTR",
    "UBER","ABNB","COIN","SOFI","UPST","ONTO","KLAC","LRCX","AMAT",
    "MRVL","SMCI","DELL","HPQ","RBLX","U","TTWO","EA"
]

VALUE_TICKERS = [
    "BRK-B","JPM","JNJ","V","UNH","PG","MA","HD","MRK","ABBV","PEP","KO",
    "COST","WMT","LLY","TMO","MCD","ACN","BAC","ABT","DHR",
    "HON","NKE","AMGN","PM","IBM","SBUX","GS","CAT","BA"
]

COMMODITIES_TICKERS = [
    "XOM","CVX","SLB","EOG","OXY","COP","PSX","VLO","FCX","NEM",
    "GOLD","AEM","WPM","FNV","PAAS","AG","GLD","SLV",
    "HAL","BKR","DVN","FANG","CTRA","MRO"
]

SECTOR_MAP: Dict[str, List[str]] = {
    "הכול (כל השוק האמריקאי)": sorted(list(set(GROWTH_TICKERS + VALUE_TICKERS + COMMODITIES_TICKERS))),
    "צמיחה וטכנולוגיה (Growth)": GROWTH_TICKERS,
    "ערך ומדד (Value/Index)": VALUE_TICKERS,
    "סחורות ואנרגיה (Commodities)": COMMODITIES_TICKERS,
}

MIN_TRADES_FOR_VALID_MODEL = 10
TRADES_FALLBACK_THRESHOLD = 35

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

def render_explain_score(df: pd.DataFrame, phase: str, cis: float, expanded: bool = False) -> None:
    expander_label = f"🔬 מידע למקצוענים - Evidence Ledger ונתונים גולמיים (CIS: {cis:.1f})"
    with st.expander(expander_label, expanded=expanded):
        try:
            explanation_md = explain_score(df, phase, cis)
            st.markdown(explanation_md)
        except Exception as exc:
            st.warning(f"לא ניתן לחשב הסבר: {exc}")

def render_monitor_metrics(metrics: dict):
    st.markdown("### 📊 ביצועי מסחר (מערכת Backtest כספית)")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("רווח נקי (Total Profit)", f"${metrics['total_profit']:,.2f}")
    with col2:
        st.metric("דרואו דאון מקסימלי (Max DD)", f"{metrics['max_drawdown']:.2f}%")
    with col3:
        st.metric("סה\"כ עסקאות (Total Trades)", metrics['total_trades'])
        st.caption(f"✅ {metrics['winning_trades']} מרוויחות | ❌ {metrics['losing_trades']} מפסידות")
    with col4:
        st.metric("אישורי וואיקוף - אחוזי הצלחה", f"{metrics['wyckoff_success_rate']:.1f}%")
    
    if metrics.get('annual_pnl'):
        st.markdown("#### 📅 דוח רווח/הפסד שנתי")
        annual_df = pd.DataFrame([
            {"שנה": str(year), "רווח/הפסד ($)": pnl}
            for year, pnl in metrics['annual_pnl'].items()
        ]).sort_values("שנה")
        
        def color_pnl(val):
            color = '#16a34a' if val > 0 else '#dc2626'
            return f'color: {color}'
            
        st.dataframe(annual_df.style.map(color_pnl, subset=['רווח/הפסד ($)']), use_container_width=True, hide_index=True)
    else:
        st.info("אין נתוני מסחר שנתיים להצגה.")

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
    
    [data-testid="stMetric"] {
        background: rgba(15, 23, 42, 0.95) !important;
        border: 1px solid rgba(56, 189, 248, 0.3) !important;
        border-radius: 12px;
        padding: 1.2rem;
    }
    [data-testid="stMetricValue"] { color: #38bdf8 !important; font-weight: 700 !important; }
    [data-testid="stMetricLabel"] { color: #f1f5f9 !important; font-weight: 500 !important; }
    [data-testid="stMetricDelta"] { color: #34d399 !important; }
    
    /* ======== Trading Scout Premium Cards ======== */
    .scout-wrapper {
        width: 100%;
        margin-bottom: 40px; 
    }
    .scout-card {
        background: linear-gradient(145deg, rgba(16, 24, 48, 0.95), rgba(28, 40, 68, 0.98));
        border: 1px solid rgba(56, 189, 248, 0.28);
        border-radius: 22px;
        padding: 32px 28px;
        box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
        transition: transform 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease;
        position: relative;
        overflow: hidden;
    }
    .scout-card::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0; height: 5px;
        background: linear-gradient(90deg, transparent, #38bdf8, transparent);
        opacity: 0.85;
    }
    .scout-card:hover {
        transform: translateY(-4px);
        border-color: rgba(56, 189, 248, 0.7);
        box-shadow: 0 20px 55px rgba(0, 0, 0, 0.45);
    }
    .scout-header {
        display: flex; justify-content: space-between; align-items: center; 
        margin-bottom: 24px;
    }
    .scout-title { 
        color: #f8fafc; font-size: 2rem; font-weight: 800; 
        margin: 0; letter-spacing: 0.5px; display: flex; align-items: center;
    }
    .scout-title-sub { font-size: 1.1rem; color: #94a3b8; font-weight: 400; padding-right: 12px; }
    .scout-badge {
        padding: 8px 20px; border-radius: 30px; 
        font-size: 1rem; font-weight: 700; letter-spacing: 0.5px;
        background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.15);
    }
    .scout-prob-container { text-align: center; margin-bottom: 20px; }
    .scout-prob-label { margin:0; color:#cbd5e1; font-weight: 600; letter-spacing: 1.5px; font-size: 1rem; text-transform: uppercase; }
    .scout-prob { 
        font-size: 4.8rem; font-weight: 800; color: #38bdf8; 
        margin: 10px 0 16px 0; line-height: 1;
        text-shadow: 0 0 35px rgba(56,189,248,0.45); 
    }
    .scout-phase-pill {
        display: inline-block; background: rgba(0,0,0,0.35); padding: 10px 20px; 
        border-radius: 25px; border: 1px solid rgba(255,255,255,0.08);
    }
    
    /* ======== Roadmap In-Card ======== */
    .roadmap-box {
        background: rgba(255, 255, 255, 0.03);
        border-radius: 14px;
        padding: 22px 28px;
        margin-top: 24px;
        margin-bottom: 14px;
        border-right: 3px solid #38bdf8;
        display: flex;
        justify-content: center;
        align-items: center;
        gap: 28px;
        font-size: 1rem;
        color: #94a3b8;
        flex-wrap: wrap;
    }
    .roadmap-step {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 4px;
    }
    .roadmap-label { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 6px; color: #64748b; }
    .roadmap-value { font-weight: 600; color: #f8fafc; font-size: 1.02rem; }
    .roadmap-arrow { color: #475569; font-size: 1.3rem; font-weight: bold; }
    
    .scout-divider {
        border-top: 1px solid rgba(255,255,255,0.08); margin: 28px 0;
    }
    
    /* ======== Stacked Vertical Layout for Sections ======== */
    .scout-stats-grid { 
        display: flex; 
        flex-direction: column; /* CHANGED FROM ROW TO COLUMN */
        gap: 24px; 
        margin-bottom: 24px; 
    }
    .scout-stat-box {
        flex: 1; background: rgba(255, 255, 255, 0.02);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 16px; padding: 22px; display: flex; flex-direction: column;
    }
    .scout-section-title {
        color: #e0f2fe; font-size: 1.15rem; font-weight: 700; 
        margin-bottom: 16px; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 10px;
    }
    .scout-list-item {
        font-size: 1.05rem; color: #cbd5e1; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;
    }
    .scout-alert-box {
        padding: 20px 24px; border-radius: 14px; margin-top: 24px;
        border-right: 5px solid #dc2626; background: rgba(220, 38, 38, 0.08);
    }
    .scout-alert-title { font-size: 1.1rem; color:#f8fafc; font-weight:bold; margin-bottom:12px; display:block; }
    .scout-alert-text { font-size: 0.95rem; display:block; color:#cbd5e1; line-height: 1.6; margin-bottom: 6px; }
    .trap-section-label {
        font-size: 0.85rem; color: #94a3b8; font-weight: 700; text-transform: uppercase;
        letter-spacing: 0.5px; margin: 14px 0 8px 0; display: block;
    }
    .trap-fund-highlight {
        background: rgba(239, 68, 68, 0.12);
        border-right: 3px solid #ef4444;
        padding: 10px 14px;
        border-radius: 8px;
        font-weight: 600;
        color: #fecaca !important;
    }
    
    .edu-box {
        background: rgba(56, 189, 248, 0.05);
        border-right: 4px solid #38bdf8;
        padding: 16px;
        margin-top: 20px;
        border-radius: 8px;
        font-size: 0.95rem;
        color: #e2e8f0;
        line-height: 1.7;
        flex-grow: 1; 
    }
    .edu-box-title {
        color:#38bdf8; 
        font-weight: 700;
        display:block; 
        margin-bottom:10px;
        font-size: 1.05rem;
    }

    /* ======== Fundamental Analysis Screen ======== */
    .fund-card {
        background: rgba(255, 255, 255, 0.02);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 18px;
        padding: 28px 30px;
        margin-bottom: 22px;
    }
    .fund-verdict-box {
        text-align: center;
        border-radius: 18px;
        padding: 26px;
        margin-bottom: 22px;
        border: 1px solid rgba(255,255,255,0.08);
    }
    .fund-verdict-label { font-size: 1rem; color: #94a3b8; margin-bottom: 6px; }
    .fund-verdict-value { font-size: 2.4rem; font-weight: 800; letter-spacing: 0.5px; }
    .fund-verdict-sub { font-size: 0.95rem; color: #cbd5e1; margin-top: 8px; }
    .fund-synth-box {
        background: rgba(56, 189, 248, 0.06);
        border-right: 4px solid #38bdf8;
        border-radius: 12px;
        padding: 18px 22px;
        margin-bottom: 22px;
        font-size: 1.1rem;
        font-weight: 700;
        color: #f8fafc;
    }
    .fund-meta-row {
        display: flex; gap: 18px; flex-wrap: wrap; margin-bottom: 22px;
    }
    .fund-meta-box {
        flex: 1; min-width: 220px;
        background: rgba(255, 255, 255, 0.02);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 14px; padding: 18px 20px;
    }
    .fund-meta-label { font-size: 0.85rem; color: #94a3b8; margin-bottom: 6px; }
    .fund-meta-value { font-size: 1.2rem; font-weight: 700; color: #f8fafc; }
    .fund-table-title {
        color: #e0f2fe; font-size: 1.15rem; font-weight: 700;
        margin-bottom: 14px; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 10px;
    }

    /* ======== Institutional Map Visual Layout ======== */
    .map-card {
        background: linear-gradient(180deg, rgba(16, 24, 45, 0.95) 0%, rgba(12, 18, 36, 0.6) 100%);
        padding: 32px 26px; border-radius: 20px; text-align: center;
        box-shadow: 0 8px 30px rgba(0,0,0,0.3); margin-bottom: 30px;
        border: 1px solid rgba(255,255,255,0.08);
        transition: transform 0.25s ease, background 0.25s ease, border-color 0.25s ease;
    }
    .map-card:hover {
        transform: translateY(-5px); border-color: rgba(56, 189, 248, 0.5);
        background: linear-gradient(180deg, rgba(22, 36, 62, 0.98) 0%, rgba(12, 18, 36, 0.7) 100%);
    }
    .map-card h4 { margin:0; font-size:1.4rem; color:#f8fafc; font-weight:700; letter-spacing: 0.5px; }
    .map-card-label { font-size:1rem; color:#94a3b8; margin: 12px 0 6px 0; font-weight:600; text-transform: uppercase; letter-spacing: 1px; }
    .map-card-score { margin:0; font-size: 3.4rem; font-weight:800; line-height: 1.1; }
    .map-desc {
        font-size: 0.95rem; color: #cbd5e1; margin-top: 20px; line-height: 1.6; padding-top: 16px; border-top: 1px dashed rgba(255,255,255,0.15);
    }
    </style>
    """, unsafe_allow_html=True)

@st.cache_data(ttl=3600, max_entries=64, show_spinner=False)
def get_cached_data(ticker: str, period: str = "2y", start: Optional[str] = None, end: Optional[str] = None):
    return get_data(ticker, period, start, end) if SCOUT_CORE_AVAILABLE else None

def _compute_wyckoff(ticker: str):
    df = get_cached_data(ticker)
    if df is None or df.empty:
        return None
    engine = FactorEngine(BacktestConfig())
    factors = engine.compute(df)
    phases = engine.get_wyckoff_phase(df)
    cis = engine.composite_cis(factors, df)
    current_phase = str(phases.iloc[-1])
    current_cis = float(cis.iloc[-1])
    allowed = check_phase_entry_allowed(current_phase, "Balanced")
    return {
        "df": df,
        "factors": factors,
        "cis": cis,
        "current_phase": current_phase,
        "current_cis": current_cis,
        "allowed": allowed,
        "num_bars": len(df)
    }

def init_session_state() -> None:
    if "model_archive" not in st.session_state:
        st.session_state.model_archive = load_all_models_from_disk()
    if "use_ml" not in st.session_state:
        st.session_state.use_ml = False
    if "ml_model" not in st.session_state:
        st.session_state.ml_model = None
    if "selected_tickers" not in st.session_state:
        st.session_state.selected_tickers = ["BN", "DELL", "PANW", "GLD", "SLV", "NVDA", "BTC-USD"]

# ============================================================
# Screens
# ============================================================

def screen_home() -> None:
    st.markdown("### 🏠 Wyckoff Analyst - רדאר הכסף החכם")
    
    st.markdown("""
    **ברוכים הבאים למערכת המוסדית!** המטרה העיקרית של המערכת היא לענות על שאלה אחת פשוטה: **"מה ההסתברות שגוף מוסדי אוסף כעת את המניה?"** (Institutional Accumulation Probability).
    
    על פי שיטת ריצ'רד וואיקוף (Wyckoff), כסף חכם (בנקים, קרנות גידור) אינו קונה בבת אחת, אלא "אוסף" סחורה בתהליך מתמשך מתחת לרדאר. המערכת מנתחת מחזורי מסחר, שינויי מבנה, ומדדי זרימת הון כדי לזהות את עקבות הכסף החכם ולהתריע מתי כדאי להצטרף אליהם (שלבי Spring ו-Markup), ומתי לברוח (Distribution).
    """)
    st.info("⚠️ **הבהרה:** המערכת היא כלי עזר אנליטי בלבד ואינה מהווה ייעוץ השקעות.")
    
    ticker = st.text_input("Ticker לניתוח (לדוגמה NVDA, TSLA, SPY)", value="NVDA").strip().upper()

    if st.button("▶ הרץ ניתוח מוסדי", use_container_width=True, type="primary"):
        with st.spinner("מחשב מנוע Wyckoff מתקדם..."):
            result = _compute_wyckoff(ticker)
            
        if result is None:
            if not SCOUT_CORE_AVAILABLE:
                st.error("מודול הליבה (scout_core) לא נטען בהצלחה - לכן לא ניתן לשאוב נתונים.")
                if SCOUT_CORE_IMPORT_ERROR:
                    st.code(SCOUT_CORE_IMPORT_ERROR)
                st.caption("בדוק ב-requirements.txt שכל הספריות (yfinance, pandas, numpy וכו') מותקנות, ושאין שגיאת ייבוא בקובץ scout_core.py.")
            else:
                st.error("אין נתונים זמינים או נדרש לפחות 60 ימי מסחר.")
            return
            
        if result["allowed"] and result["current_cis"] >= 65:
            st.success("🟢 **סיכום כניסה:** השלב הנוכחי חיובי מאוד ותומך בכניסה לעסקה. ההסתברות לצבירה מוסדית אמיתית גבוהה.")
        elif result["allowed"]:
            st.warning("🟡 **סיכום כניסה:** השלב הטכני מתאים, אך המומנטום עדיין חלש (ציון נמוך מ-65). המתן לאישור.")
        else:
            st.error("🔴 **סיכום כניסה:** לא מומלץ. הנכס אינו נמצא כעת בשלב שמתאים לכניסה. סיכוי נמוך לצבירה מוסדית.")

        st.markdown("<hr style='border-color: rgba(255,255,255,0.1); margin:10px 0;'>", unsafe_allow_html=True)
            
        left, right = st.columns([1, 1.3])
        
        with left:
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number",
                value=result["current_cis"],
                title={'text': "הסתברות לצבירה (CIS)", 'font': {'color': "#d9e6f2", 'size': 18}},
                number={'font': {'color': "#d9e6f2"}},
                gauge={
                    'axis': {'range': [0, 100], 'tickcolor': "white"},
                    'bar': {'color': "rgba(255,255,255,0.4)"},
                    'steps': [
                        {'range': [0, 40], 'color': "#dc2626"},
                        {'range': [40, 65], 'color': "#eab308"},
                        {'range': [65, 100], 'color': "#16a34a"}
                    ],
                }
            ))
            fig_gauge.update_layout(height=230, margin=dict(l=20, r=20, t=40, b=20), paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig_gauge, use_container_width=True)
            st.caption("ציון מ-0 עד 100 המודד את עוצמת כניסת הכספים המוסדיים (Institutional Accumulation Probability).")

        with right:
            st.markdown("#### איפה אנחנו בתהליך? (Wyckoff Phase)")
            cp = result["current_phase"]
            
            is_transition = any(x in cp for x in ["TRANSITION", "UNCERTAIN", "לא בתהליך"])
            
            if is_transition:
                st.info("ℹ️ לא נמצא שלב Wyckoff מובהק רלוונטי לתהליך כרגע (הנכס בשלב מעבר או חוסר ודאות).")
                st.caption(f"**זיהוי מלא:** `{cp}`")
            else:
                is_bearish = any(x in cp for x in ["Distribution", "Markdown", "Supply"])
                
                def get_bg(phase_markers):
                    if isinstance(phase_markers, str):
                        phase_markers = [phase_markers]
                    if any(m in cp for m in phase_markers):
                        return "background:#38bdf8; color:#0f172a; font-weight:bold; border:2px solid #fff; transform:scale(1.05);"
                    return "background:rgba(255,255,255,0.05); color:#64748b;"
                    
                # תוקנו החצים לזרימה תקינה מימין לשמאל בעברית (←)
                if is_bearish:
                    html = f"""
                    <div style="display:flex; justify-content:space-around; align-items:center; background:#1e293b; padding:20px; border-radius:12px; margin-top:10px;">
                        <div style="text-align:center; padding:15px; border-radius:8px; width:45%; transition:0.3s; {get_bg(['Distribution', 'Supply'])}">הפצה (Distribution)<br><span style="font-size:0.85em">מוסדיים מוכרים</span></div>
                        <div style="color:#475569; font-size:1.8em;">←</div>
                        <div style="text-align:center; padding:15px; border-radius:8px; width:45%; transition:0.3s; {get_bg('Markdown')}">ירידות (Markdown)<br><span style="font-size:0.85em">פיזור סחורה</span></div>
                    </div>
                    """
                else:
                    html = f"""
                    <div style="display:flex; justify-content:space-between; align-items:center; background:#1e293b; padding:15px 10px; border-radius:12px; margin-top:10px; font-size:0.9em;">
                        <div style="text-align:center; padding:10px 5px; border-radius:8px; width:18%; transition:0.3s; {get_bg(['Phase A'])}">שלב A<br><span style="font-size:0.8em">בלימה</span></div>
                        <div style="color:#475569;">←</div>
                        <div style="text-align:center; padding:10px 5px; border-radius:8px; width:18%; transition:0.3s; {get_bg(['Phase B', 'Accumulation'])}">שלב B<br><span style="font-size:0.8em">בניית כוח</span></div>
                        <div style="color:#475569;">←</div>
                        <div style="text-align:center; padding:10px 5px; border-radius:8px; width:18%; transition:0.3s; {get_bg(['Phase C', 'Spring'])}">שלב C<br><span style="font-size:0.8em">ניעור</span></div>
                        <div style="color:#475569;">←</div>
                        <div style="text-align:center; padding:10px 5px; border-radius:8px; width:18%; transition:0.3s; {get_bg(['Phase D', 'Re-accumulation'])}">שלב D<br><span style="font-size:0.8em">פריצה</span></div>
                        <div style="color:#475569;">←</div>
                        <div style="text-align:center; padding:10px 5px; border-radius:8px; width:18%; transition:0.3s; {get_bg(['Phase E', 'Markup'])}">שלב E<br><span style="font-size:0.8em">מגמה</span></div>
                    </div>
                    """
                st.markdown(html, unsafe_allow_html=True)
                st.caption(f"**זיהוי מלא:** `{cp}`")
            
        st.markdown("<hr style='border-color: rgba(255,255,255,0.05); margin:20px 0;'>", unsafe_allow_html=True)
        
        st.markdown("#### 📉 ניתוח ויזואלי של המחיר והנפח (Price & Volume Action)")
        chart_df = result["df"].iloc[-150:] 
        fig_chart = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
        
        fig_chart.add_trace(go.Candlestick(
            x=chart_df.index, open=chart_df['Open'], high=chart_df['High'], 
            low=chart_df['Low'], close=chart_df['Close'], name="Price"), 
            row=1, col=1)
            
        colors = ['#16a34a' if c >= o else '#dc2626' for c, o in zip(chart_df['Close'], chart_df['Open'])]
        fig_chart.add_trace(go.Bar(
            x=chart_df.index, y=chart_df['Volume'], marker_color=colors, name="Volume"), 
            row=2, col=1)
            
        last_date = chart_df.index[-1]
        last_low = chart_df['Low'].iloc[-1]
        
        cp_marker = result['current_phase']
        if any(x in cp_marker for x in ["Phase C", "Spring", "Phase D", "Phase E", "Markup", "Accumulation", "Re-accumulation"]):
            marker_color = "#16a34a" 
        elif any(x in cp_marker for x in ["TRANSITION", "UNCERTAIN", "לא בתהליך"]):
            marker_color = "#eab308"
        else:
            marker_color = "#dc2626"

        fig_chart.add_annotation(
            x=last_date, y=last_low,
            text=f"📌 {cp_marker}",
            showarrow=True,
            arrowhead=2,
            arrowsize=1.2,
            arrowwidth=2,
            arrowcolor=marker_color,
            ax=0,
            ay=45,
            font=dict(color="white", size=11, weight="bold"),
            bgcolor=marker_color,
            bordercolor="rgba(255,255,255,0.7)",
            borderwidth=1,
            borderpad=3,
            opacity=0.95
        )
            
        fig_chart.update_layout(
            height=450, margin=dict(l=20, r=20, t=20, b=20), 
            xaxis_rangeslider_visible=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)"
        )
        st.plotly_chart(fig_chart, use_container_width=True)
            
        with st.expander("📝 הסבר פשוט למתחילים (בשפה מדוברת)", expanded=True):
            st.markdown(explain_score_simple(result["df"], result["current_phase"], result["current_cis"], result["allowed"]))
            
        render_explain_score(result["df"], result["current_phase"], result["current_cis"], expanded=False)

def screen_institutional_map() -> None:
    st.markdown("### 🗺️ Institutional Map - מפת כסף חכם סקטוריאלית")
    st.markdown("מסך זה ממפה את הסקטורים המרכזיים בשוק ומציג את ממוצע ה-**Institutional Accumulation Probability** (הסתברות לצבירה מוסדית) שלהם. הנתונים מתעדכנים על בסיס מניות מובילות בכל סקטור ומוצגים מהגבוה לנמוך.")
    
    MAP_SECTORS = {
        "טכנולוגיה (Technology)": {
            "tickers": ["AAPL", "MSFT", "NVDA", "AVGO", "CRM"],
            "desc": "סקטור עתיר צמיחה, משמש לעיתים קרובות כמוביל מומנטום שוק ומאופיין בכניסת הון מוסדי טרנדי."
        },
        "סמיקונדקטורס (Semiconductors)": {
            "tickers": ["AMD", "TXN", "QCOM", "INTC", "SMCI"],
            "desc": "תעשיית השבבים - מתפקדת כברומטר מוביל לתיאבון הסיכון של המוסדיים לשוק כולו."
        },
        "פיננסים (Financials)": {
            "tickers": ["JPM", "V", "MA", "BAC", "GS"],
            "desc": "מוטה ריבית ומחזור כלכלי. איסוף כאן מעיד לרוב על ציפייה מוסדית להתרחבות כלכלית."
        },
        "בריאות (Healthcare)": {
            "tickers": ["JNJ", "UNH", "LLY", "MRK", "ABBV"],
            "desc": "סקטור דפנסיבי המשולב בצמיחה. משמש מקלט בטוח בעת אי-ודאות מוסדית לחלוקת סיכונים."
        },
        "אנרגיה וסחורות (Energy & Commodities)": {
            "tickers": ["XOM", "CVX", "GLD", "SLV", "COP"],
            "desc": "גידור אינפלציוני ונכסים קשים. כסף חכם זורם לכאן להגנה או ספקולציות מאקרו."
        }
    }
    
    if st.button("🗺️ טען מפה מוסדית מחושבת", type="primary"):
        with st.spinner("סורק מניות מובילות בכל סקטור לחילוץ נתוני איסוף (Smart Money Flow)..."):
            engine = FactorEngine(BacktestConfig())
            sector_results = {}
            
            for sector, data in MAP_SECTORS.items():
                sector_cis = []
                for t in data["tickers"]:
                    df = get_cached_data(t, period="6mo")
                    if df is not None and not df.empty and len(df) > 40:
                        factors = engine.compute(df)
                        cis = engine.composite_cis(factors, df)
                        sector_cis.append(float(cis.iloc[-1]))
                
                if sector_cis:
                    avg_cis = sum(sector_cis) / len(sector_cis)
                    sector_results[sector] = {"score": avg_cis, "desc": data["desc"]}
            
            if sector_results:
                sorted_sectors = sorted(sector_results.items(), key=lambda item: item[1]["score"], reverse=True)
                
                cols = st.columns(3)
                for i, (sector, data) in enumerate(sorted_sectors):
                    avg_cis = data["score"]
                    with cols[i % 3]:
                        color = "#16a34a" if avg_cis >= 65 else ("#eab308" if avg_cis >= 50 else "#dc2626")
                        st.markdown(f"""
                        <div class='map-card' style='border-top: 6px solid {color};'>
                            <h4>{sector}</h4>
                            <p class='map-card-label'>Smart Money Index</p>
                            <h2 class='map-card-score' style='color:{color}; text-shadow: 0 0 25px {color}40;'>{avg_cis:.1f}%</h2>
                            <p class='map-desc'>{data['desc']}</p>
                        </div>
                        """, unsafe_allow_html=True)
                        
                st.markdown("---")
                st.info("💡 **תובנה מוסדית (Smart Money Insight):** סקטורים עם אינדקס מעל 65% נתונים כעת תחת פעילות איסוף מוסדית עקבית ויש לחפש בהם הזדמנויות למגמת עליה (Long). סקטורים מתחת ל-50% נמצאים תחת לחץ פיזור או התעלמות מוסדית.")
            else:
                st.error("לא ניתן היה לטעון נתונים מספיקים עבור המפה.")

def get_ackman_fundamental_data(ticker: str, cis_score: float = None, current_phase: str = "") -> dict:
    """
    מודול פונדמנטלי קשיח (Bill Ackman Style) - תוסף נוסף ל-get_fundamental_data.
    מבוסס על Cash Flow Yield, PEG Ratio, Margin ומינוף.
    אוכף סנכרון הרמטי עם הפאזה הטכנית. עצמאי - שואב נתונים ישירות מ-yfinance.
    """
    try:
        tkr_obj = yf.Ticker(ticker)
        info = tkr_obj.info or {}

        try: cf = tkr_obj.cashflow
        except Exception: cf = pd.DataFrame()
        try: bs = tkr_obj.balance_sheet
        except Exception: bs = pd.DataFrame()
        try: fin = tkr_obj.financials
        except Exception: fin = pd.DataFrame()

        market_cap = info.get("marketCap", 0)
        fwd_pe = info.get("forwardPE", 0)
        sector = info.get("sector", "Unknown")

        # Cash flow Yield
        ocf, fcf = 0, 0
        if not cf.empty and "Operating Cash Flow" in cf.index:
            ocf = cf.loc["Operating Cash Flow"].iloc[0]
            if "Capital Expenditure" in cf.index:
                fcf = ocf + cf.loc["Capital Expenditure"].iloc[0]  # CapEx typically negative

        fcf_yield = (fcf / market_cap * 100) if market_cap > 0 and fcf > 0 else 0

        # Margins & Growth
        rev_growth, op_margin = 0, 0
        if not fin.empty and "Total Revenue" in fin.index and len(fin.columns) > 1:
            rev_curr = fin.loc["Total Revenue"].iloc[0]
            rev_prev = fin.loc["Total Revenue"].iloc[1]
            if rev_prev and rev_prev != 0:
                rev_growth = ((rev_curr - rev_prev) / abs(rev_prev)) * 100
            if "Operating Income" in fin.index and rev_curr:
                op_margin = (fin.loc["Operating Income"].iloc[0] / rev_curr) * 100

        # Net Debt to EBITDA
        net_debt_ebitda = 0
        if not bs.empty and not fin.empty:
            total_debt = bs.loc["Total Debt"].iloc[0] if "Total Debt" in bs.index else 0
            cash = bs.loc["Cash And Cash Equivalents"].iloc[0] if "Cash And Cash Equivalents" in bs.index else 0
            ebitda = fin.loc["EBITDA"].iloc[0] if "EBITDA" in fin.index else 0
            if ebitda > 0:
                net_debt_ebitda = (total_debt - cash) / ebitda

        peg_ratio = info.get("pegRatio", (fwd_pe / rev_growth) if rev_growth > 0 else 999)

        # Benchmarks
        benchmarks = {
            "Technology": {"pe": 25, "om": 20.0, "rg": 15.0},
            "Financial Services": {"pe": 14, "om": 25.0, "rg": 8.0},
            "Healthcare": {"pe": 20, "om": 15.0, "rg": 10.0},
            "Consumer Cyclical": {"pe": 18, "om": 10.0, "rg": 8.0},
            "Energy": {"pe": 12, "om": 15.0, "rg": 5.0},
        }
        bench = benchmarks.get(sector, {"pe": 18, "om": 12.0, "rg": 8.0})

        valuation, color = "הוגן", "#eab308"
        if fwd_pe and fwd_pe < bench["pe"] * 0.8 and peg_ratio < 1.5:
            valuation, color = "זול", "#16a34a"
        elif fwd_pe and (fwd_pe > bench["pe"] * 1.25 or peg_ratio > 2.5):
            valuation, color = "יקר", "#ef4444"

        # Strict Synthesis Rule (Synchronization)
        synthesis = "ממתין לנתונים..."
        is_toxic = False
        if cis_score is not None:
            is_bearish_phase = any(p in current_phase for p in ["Distribution", "Markdown", "Heavy Supply", "Failed", "Selling Climax", "UNCERTAIN"])
            is_bullish_phase = any(p in current_phase for p in ["Phase C", "Spring", "Phase D", "Phase E", "Markup", "LPS", "Re-accumulation"])

            strong_cash = (fcf_yield > 3.0) and (op_margin > bench["om"] * 0.8)
            high_debt = net_debt_ebitda > 3.0

            if is_bearish_phase or cis_score <= 40:
                is_toxic = True
                if high_debt or not strong_cash:
                    synthesis = f"☠️ Toxic Value Trap (סכין נופלת): הפאזה הטכנית ב-{ticker} היא '{current_phase}' והכסף החכם נוטש. ישנה חולשה תזרימית בליבת העסקים מול סקטור ה-{sector}. התרחק מיד!"
                else:
                    synthesis = f"🚨 סכין נופלת: הנתונים היבשים של {ticker} אולי נראים סבירים, אך הפאזה היא '{current_phase}' והמוסדיים זורקים סחורה בפיזור אגרסיבי. מלכודת ערך קלאסית. אל תתפוס תחתיות."
            elif is_bullish_phase and cis_score >= 65:
                if strong_cash and valuation != "יקר" and not high_debt:
                    synthesis = f"🔥 High Conviction: שילוב אידיאלי ב-{ticker}. תשואת תזרים בריאה ({fcf_yield:.1f}% Yield), יעילות גבוהה מהסקטור ואיסוף מוסדי מובהק. פוזיציית לונג איכותית."
                elif valuation == "יקר" and strong_cash:
                    synthesis = f"🚀 פרמיית איכות: המוסדיים מוכנים לשלם פרמיה יקרה על {ticker} בזכות הנהלה שמדפיסה מזומן ומכה את הסקטור. הטרנד נתמך בעוצמה."
                elif high_debt or not strong_cash:
                    synthesis = f"⚠️ ספקולציית מומנטום: יש איסוף מוסדי, אך החולשה במאזן או בתזרים מצביעה על מהלך טכני ספקולטיבי. סיכון גבוה להחזקה ארוכה."
            else:
                if cis_score >= 60 and strong_cash:
                    synthesis = f"⚖️ איסוף שקט: {ticker} מדפיסה מזומן ונאספת בהדרגה מתחת לרדאר. המתנה לפריצת מחיר (Phase D)."
                else:
                    synthesis = f"💤 כסף מת: חוסר קצה פונדמנטלי וטכני ביחס למתחרות בסקטור ה-{sector}."

        explanations = {
            "fcf_yield": f"תשואת תזרים חופשי (FCF Yield) של {ticker} עומדת על {fcf_yield:.1f}%. במודל הערך של Ackman, זהו הכסף האמיתי שהעסק מייצר ביחס לשווי השוק. מעל 3-4% נחשב לחוסן בריא.",
            "peg_ratio": f"יחס PEG של {peg_ratio:.2f}. מכפיל זה משקלל את תמחור המניה (PE) מול קצב צמיחת ההכנסות. יחס מתחת ל-1.5 מרמז על צמיחה שמתומחרת בחסר.",
            "op_margin": f"שולי הרווח של {op_margin:.1f}%. בהשוואה לסקטור ה-{sector} שעומד על {bench['om']}%, זה מצביע על {'חפיר תחרותי ויכולת תמחור אגרסיבית (Pricing Power)' if op_margin > bench['om'] else 'חוסר יעילות ועלויות כבדות ביחס למתחרים הישירים'}.",
            "net_debt": f"יחס חוב ל-EBITDA עומד על {net_debt_ebitda:.2f}x. מודל מוסדי שמרני דורש מינוף מתחת ל-3x. {'המינוף בטוח וסביר.' if net_debt_ebitda < 3 else 'רמת המינוף הזו מהווה דגל אדום בוהק המייצר סיכון להשמדת ערך בעת משבר!'}"
        }

        return {
            "fcf_yield": f"{fcf_yield:.1f}%",
            "peg_ratio": f"{peg_ratio:.2f}",
            "op_margin": f"{op_margin:.1f}%",
            "rev_growth": f"{rev_growth:.1f}%",
            "net_debt_ebitda": f"{net_debt_ebitda:.2f}x",
            "pe_forward": round(fwd_pe, 2) if fwd_pe else "N/A",
            "sector": sector,
            "valuation": valuation,
            "valuation_color": color,
            "synthesis": synthesis,
            "explanations": explanations,
            "is_toxic": is_toxic
        }
    except Exception as e:
        logger.error(f"Error computing Ackman fundamentals for {ticker}: {e}")
        return {}

def screen_fundamental() -> None:
    st.markdown("### 📊 Fundamental Analysis - ניתוח ערך וחברה")
    st.markdown("מסך זה מנתח את הבריאות הפיננסית של החברה והתמחור שלה ביחס לסקטור, ומשלב זאת עם נתוני הכסף החכם.")
    
    tkr = st.text_input("הזן סימול לניתוח פונדמנטלי מקיף:", value="MSFT", key="fund_tkr").strip().upper()
    
    if st.button("📈 נתח פונדמנטלית", type="primary", use_container_width=True):
        if not SCOUT_CORE_AVAILABLE:
            st.error("מודול הליבה (scout_core) לא נטען בהצלחה - לכן הניתוח הפונדמנטלי אינו זמין.")
            if SCOUT_CORE_IMPORT_ERROR:
                st.code(SCOUT_CORE_IMPORT_ERROR)
            st.caption("בדוק ב-requirements.txt שכל הספריות (yfinance, pandas, numpy וכו') מותקנות, ושאין שגיאת ייבוא בקובץ scout_core.py.")
            return

        with st.spinner(f"שואב נתוני עומק פיננסיים עבור {tkr}..."):
            fdata = get_fundamental_data(tkr)
            if not fdata:
                st.error(f"שגיאה בשאיבת נתונים מ-Yahoo Finance עבור הסימול {tkr}.")
                return
            
            df = get_cached_data(tkr)
            cis_score = 0
            current_phase = ""
            if df is not None and not df.empty:
                engine = FactorEngine(BacktestConfig())
                factors = engine.compute(df)
                cis_score = float(engine.composite_cis(factors, df).iloc[-1])
                current_phase = str(engine.get_wyckoff_phase(df).iloc[-1])
            
            if cis_score >= 65 and fdata["valuation"] == "זול":
                synth = "🔥 High Conviction - כסף חכם אוסף מניה זולה."
            elif cis_score >= 65 and fdata["valuation"] == "יקר":
                synth = "🚀 Growth Momentum - מוסדיים קונים למרות תמחור יקר."
            elif cis_score < 50 and fdata["valuation"] == "זול":
                synth = "⚠️ Value Trap - זולה, אבל ללא כניסת כסף חכם."
            elif cis_score < 50 and fdata["valuation"] == "יקר":
                synth = "🚫 Avoid - יקרה וללא עניין מוסדי."
            else:
                synth = "⚖️ Neutral - המתנה או תמחור הוגן."

            verdict = fdata.get("valuation", "-")
            v_color = fdata.get("valuation_color", "#94a3b8")

            # === שורת המחץ - זול/הוגן/יקר במשקל ויזואלי גבוה ===
            st.markdown(
                "".join([
                    f"<div class='fund-verdict-box' style='border-color:{v_color}50; background:{v_color}12;'>",
                    f"<div class='fund-verdict-label'>{tkr} ביחס לסקטור ({fdata.get('sector', '-')})</div>",
                    f"<div class='fund-verdict-value' style='color:{v_color};'>{verdict}</div>",
                    f"<div class='fund-verdict-sub'>מבוסס על Forward P/E: {fdata.get('pe_forward', 'N/A')}</div>",
                    "</div>",
                ]),
                unsafe_allow_html=True
            )
            with st.popover("ℹ️ ביחס למה משווים?"):
                st.write(
                    "התמחור נמדד ביחס לסקטור הספציפי של החברה, ולא ביחס לשוק הכללי (S&P 500). "
                    "לכל סקטור יש 'נורמות' מכפיל שונות - חברת טכנולוגיה צומחת תיסחר באופן טבעי "
                    "במכפילים גבוהים יותר מבנק או חברת אנרגיה, ולכן ההשוואה תמיד יחסית-ענפית ולא מוחלטת."
                )
                st.caption("לדוגמה: סקטור טכנולוגיה/תקשורת - 'זול' מתחת ל-22, 'יקר' מעל 35. פיננסים/אנרגיה - 'זול' מתחת ל-12, 'יקר' מעל 18.")

            # === סינתזה וואיקוף + פונדמנטלי - משקל ויזואלי גבוה ===
            st.markdown(
                f"<div class='fund-synth-box'>🧭 סינתזת וואיקוף + פונדמנטלי: {synth} &nbsp; (Wyckoff Score: {cis_score:.1f})</div>",
                unsafe_allow_html=True
            )

            # === שורת מטא: סקטור ודוח רווחים קרוב ===
            st.markdown(
                "".join([
                    "<div class='fund-meta-row'>",
                    "<div class='fund-meta-box'>",
                    "<div class='fund-meta-label'>🏢 סקטור</div>",
                    f"<div class='fund-meta-value'>{fdata.get('sector', '-')}</div>",
                    "</div>",
                    "<div class='fund-meta-box'>",
                    "<div class='fund-meta-label'>📅 דוח רווחים קרוב (הבא)</div>",
                    f"<div class='fund-meta-value'>{fdata.get('next_earnings', 'לא ידוע')}</div>",
                    "</div>",
                    "</div>",
                ]),
                unsafe_allow_html=True
            )

            # === טבלת מכפילים מסודרת עם הסבר לכל שורה ===
            st.markdown("<div class='fund-card'>", unsafe_allow_html=True)
            st.markdown("<div class='fund-table-title'>📐 טבלת מכפילים ויחסי תמחור</div>", unsafe_allow_html=True)

            metrics = [
                ("Trailing P/E", fdata.get("pe_trailing", "-"), "מכפיל רווח היסטורי - כמה משלמים על כל דולר שהחברה הרוויחה ב-12 החודשים האחרונים."),
                ("Forward P/E", fdata.get("pe_forward", "-"), "מכפיל רווח עתידי - מתבסס על תחזיות רווח קדימה. זהו המכפיל החשוב ביותר להערכת תמחור עתידי."),
                ("PEG Ratio", fdata.get("peg", "-"), "מכפיל רווח משוקלל בקצב הצמיחה. ערך מתחת ל-1 נחשב לרוב כהזדמנות (המניה 'צומחת מהר יותר ממה שהמכפיל מרמז')."),
                ("EV/EBITDA", fdata.get("ev_ebitda", "-"), "שווי פעילות (חוב+הון) חלקי רווח תפעולי תזרימי. מנקה עיוותי מבנה הון, מס ופחת - שימושי להשוואה בין חברות עם רמות חוב שונות."),
                ("P/S (מכירות)", fdata.get("ps", "-"), "שווי שוק חלקי הכנסות שנתיות. קריטי לחברות טכנולוגיה צומחות שעדיין לא רווחיות, שם P/E לא רלוונטי."),
                ("P/B (הון)", fdata.get("pb", "-"), "שווי שוק חלקי ההון העצמי המאזני של החברה. שימושי בעיקר לבנקים וחברות עם נכסים מוחשיים רבים."),
                ("ROE", fdata.get("roe", "-"), "תשואה להון - כמה רווח מייצרת החברה על כל דולר של בעלי המניות. מדד מרכזי לאיכות ויעילות ההנהלה."),
                ("EPS Growth", fdata.get("eps_growth", "-"), "קצב צמיחת הרווח למניה ביחס לתקופה המקבילה - מדד הצמיחה הבסיסי ביותר של החברה."),
            ]

            header_l, header_r1, header_r2 = st.columns([2.2, 1.6, 1])
            with header_l:
                st.markdown("**מכפיל**")
            with header_r1:
                st.markdown("**ערך**")
            with header_r2:
                st.markdown("**הסבר**")

            for name, val, desc in metrics:
                row_l, row_r1, row_r2 = st.columns([2.2, 1.6, 1])
                with row_l:
                    st.markdown(name)
                with row_r1:
                    st.markdown(f"**{val}**")
                with row_r2:
                    with st.popover("מה זה?"):
                        st.write(desc)

            st.markdown("</div>", unsafe_allow_html=True)

            # === מודול נוסף: Ackman Style Hard Fundamentals (תוסף עצמאי, לא דורס את הטבלה למעלה) ===
            with st.spinner("מריץ מודול Ackman - תזרים מזומנים, מינוף וסנכרון הרמטי..."):
                adata = get_ackman_fundamental_data(tkr, cis_score=cis_score, current_phase=current_phase)

            if adata:
                a_color = adata.get("valuation_color", "#94a3b8")
                st.markdown("<div class='fund-card'>", unsafe_allow_html=True)
                st.markdown("<div class='fund-table-title'>🦅 ניתוח קשיח בסטייל Ackman (FCF, מינוף וסנכרון וואיקוף)</div>", unsafe_allow_html=True)

                st.markdown(
                    f"<div class='fund-synth-box' style='border-color:{a_color}; background:{a_color}10;'>{adata.get('synthesis', '-')}</div>",
                    unsafe_allow_html=True
                )
                if adata.get("is_toxic"):
                    st.warning("☠️ דגל אדום: המודל מזהה חוסר סנכרון בין הפאזה הטכנית לבריאות הפיננסית. זהירות מוגברת.")

                ackman_metrics = [
                    ("FCF Yield", adata.get("fcf_yield", "-"), adata["explanations"]["fcf_yield"]),
                    ("PEG Ratio", adata.get("peg_ratio", "-"), adata["explanations"]["peg_ratio"]),
                    ("שולי תפעול (Op. Margin)", adata.get("op_margin", "-"), adata["explanations"]["op_margin"]),
                    ("צמיחת הכנסות", adata.get("rev_growth", "-"), "קצב צמיחת ההכנסות שנה מול שנה - מבטא את קצב התרחבות העסק בפועל."),
                    ("חוב נטו / EBITDA", adata.get("net_debt_ebitda", "-"), adata["explanations"]["net_debt"]),
                ]

                a_header_l, a_header_r1, a_header_r2 = st.columns([2.2, 1.6, 1])
                with a_header_l:
                    st.markdown("**מדד**")
                with a_header_r1:
                    st.markdown("**ערך**")
                with a_header_r2:
                    st.markdown("**הסבר**")

                for name, val, desc in ackman_metrics:
                    a_row_l, a_row_r1, a_row_r2 = st.columns([2.2, 1.6, 1])
                    with a_row_l:
                        st.markdown(name)
                    with a_row_r1:
                        st.markdown(f"**{val}**")
                    with a_row_r2:
                        with st.popover("מה זה?"):
                            st.write(desc)

                st.markdown("</div>", unsafe_allow_html=True)
            else:
                st.info("לא ניתן היה לחלץ נתוני Ackman עומק (FCF/מינוף) עבור סימול זה כרגע.")

    st.markdown("---")
    st.markdown("#### 🔎 סורק פונדמנטלי-מוסדי (Market Scanner)")
    st.caption("מאתר מניות מסקטורים מובילים שמוגדרות כ'זולות' ובעלות ציון צבירה מוסדית גבוה.")
    if st.button("סרוק הזדמנויות (מניות זולות + כסף חכם)", type="primary"):
        with st.spinner("סורק נתונים עבור עשרות מניות... (עשוי לקחת כדקה)"):
            results = []
            scan_list = GROWTH_TICKERS[:12] + VALUE_TICKERS[:12] 
            for tkr_scan in scan_list:
                fdata = get_fundamental_data(tkr_scan)
                if fdata and fdata.get("valuation") == "זול":
                    df = get_cached_data(tkr_scan, "1y")
                    if df is not None and not df.empty and len(df) > 60:
                        engine = FactorEngine(BacktestConfig())
                        factors = engine.compute(df)
                        cis = engine.composite_cis(factors, df).iloc[-1]
                        if cis >= 50:
                            results.append({
                                "Ticker": tkr_scan,
                                "Sector": fdata.get("sector", ""),
                                "Fwd P/E": fdata.get("pe_forward", ""),
                                "EPS Growth": fdata.get("eps_growth", ""),
                                "Wyckoff CIS": round(float(cis), 1)
                            })
            if results:
                st.dataframe(pd.DataFrame(results).sort_values("Wyckoff CIS", ascending=False), use_container_width=True)
            else:
                st.info("לא נמצאו מניות העונות לקריטריונים (זולות פונדמנטלית + איסוף מוסדי סביר).")

def screen_trading_scout() -> None:
    st.markdown("### 📈 Trading Scout - תכנון עסקאות ובדיקת הסתברויות")
    st.info("⚠️ **הבהרה קריטית:** זהו כלי עזר אנליטי אוטומטי המעריך הסתברויות לאיסוף מוסדי. אינו מהווה תחליף לניהול סיכונים עצמאי או ייעוץ.")
    
    # Mode selector
    mode = st.radio("בחר פרופיל רגישות למודל ההסתברויות (Risk Mode):", ["Conservative (שמרני)", "Balanced (מאוזן)", "Optimistic (אופטימי)"], index=1, horizontal=True)
    mode_map = {"Conservative (שמרני)": "Conservative", "Balanced (מאוזן)": "Balanced", "Optimistic (אופטימי)": "Optimistic"}
    selected_mode = mode_map[mode]

    cols_input = st.columns(4)
    tickers_input = []
    default_tickers = ["NVDA", "AAPL", "META", "TSLA"]
    for i in range(4):
        val = cols_input[i].text_input(f"טיקר {i+1}", value=default_tickers[i], key=f"ts_ticker_{i}").strip().upper()
        tickers_input.append(val)
        
    if st.button("💡 הפעל רדאר חכם - קבל הסתברויות ותוכניות", type="primary", use_container_width=True):
        if not SCOUT_CORE_AVAILABLE:
            st.error("מודול הליבה חסר, לא ניתן לייצר המלצה.")
            return
            
        from trading_scout import get_trading_recommendation
        
        # UI rendering in sequential order (Stacked Vertically to avoid cutoffs)
        for tkr in tickers_input:
            if tkr:
                with st.spinner(f"מנתח טביעות אצבע מוסדיות ופונדמנטליות עבור {tkr}..."):
                    try:
                        rec_data = get_trading_recommendation(tkr, mode=selected_mode)
                    except Exception as e:
                        st.error(f"שגיאה ב-{tkr}: {e}")
                        continue
                        
                if rec_data.get("recommendation") == "ERROR":
                    st.warning(f"**{tkr}:** {rec_data.get('reason')}")
                    continue

                rec = rec_data["recommendation"]
                color_map = {
                    "STRONG BUY": "#22c55e", "BUY": "#4ade80",
                    "HOLD": "#facc15", "SELL": "#fb923c", "STRONG SELL": "#ef4444"
                }
                color = color_map.get(rec, "#94a3b8")
                
                wyckoff_traps = rec_data.get('wyckoff_traps', [])
                fundamental_traps = rec_data.get('fundamental_traps', [])
                is_safe = (not wyckoff_traps) and (not any("Value Trap" in t for t in fundamental_traps))
                alert_border = "#22c55e" if is_safe else "#ef4444"
                alert_bg = "rgba(34, 197, 94, 0.05)" if is_safe else "rgba(239, 68, 68, 0.08)"
                
                smart_money_html = "".join([
                    f"<div class='scout-list-item'><span>{k}:</span> <span style='font-weight:600; color:#f8fafc;'>{v}</span></div>"
                    for k, v in rec_data['dashboard'].items()
                ])

                if not wyckoff_traps and not fundamental_traps:
                    failure_html = (
                        f"<span class='scout-alert-text'>✅ <b>שמיים נקיים</b> - לא זוהו מלכודות Wyckoff "
                        f"או פונדמנטליות עבור {tkr}. השילוב נראה תקין.</span>"
                    )
                else:
                    wyckoff_block = ""
                    if wyckoff_traps:
                        wyckoff_items = "".join([f"<span class='scout-alert-text'>{w}</span>" for w in wyckoff_traps])
                        wyckoff_block = f"<div class='trap-section-label'>📉 מלכודות Wyckoff</div>{wyckoff_items}"
                    else:
                        wyckoff_block = "<div class='trap-section-label'>📉 מלכודות Wyckoff</div><span class='scout-alert-text'>✅ לא זוהו מלכודות טכניות.</span>"

                    fund_block = ""
                    if fundamental_traps:
                        is_value_trap = any("Value Trap" in t for t in fundamental_traps)
                        fund_class = "trap-fund-highlight" if is_value_trap else ""
                        fund_items = "".join([f"<span class='scout-alert-text {fund_class}'>{t}</span>" for t in fundamental_traps])
                        fund_block = f"<div class='trap-section-label'>💰 מלכודות פונדמנטליות</div>{fund_items}"
                    else:
                        fund_block = "<div class='trap-section-label'>💰 מלכודות פונדמנטליות</div><span class='scout-alert-text'>✅ לא זוהו מלכודות פונדמנטליות.</span>"

                    failure_html = wyckoff_block + fund_block
                
                roadmap_prev = rec_data.get('roadmap', {}).get('previous_phase', '—')
                roadmap_next = rec_data.get('roadmap', {}).get('next_phase', '—')
                roadmap_action = rec_data.get('roadmap', {}).get('action_plan', '')
                roadmap_success = rec_data.get('roadmap', {}).get('what_if_success', '')
                roadmap_fail = rec_data.get('roadmap', {}).get('what_if_fail', '')
                
                edu_note = rec_data.get('prob_engine', {}).get('educational_note', 'אין נתונים נוספים.')

                # Render Card Wrapper
                card_parts = [
                    "<div class='scout-wrapper'>",
                    "<div class='scout-card'>",
                    "<div class='scout-header'>",
                    f"<h3 class='scout-title'>{tkr} <span class='scout-title-sub'>| רדאר מוסדי</span></h3>",
                    f"<span class='scout-badge' style='color:{color}; border-color: {color}50;'>{rec}</span>",
                    "</div>",
                    "<div class='scout-prob-container'>",
                    "<p class='scout-prob-label'>Institutional Accumulation</p>",
                    f"<div class='scout-prob' style='color: {color}; text-shadow: 0 0 40px {color}60;'>{rec_data['prob_engine']['accumulation_chance']}%</div>",
                    "<div class='scout-phase-pill'>",
                    "<span style='color:#94a3b8; font-size:0.95rem;'>Wyckoff Phase:</span> ",
                    f"<span style='color:#f8fafc; font-weight:700; font-size:1.05rem; margin-right: 6px;'>{rec_data['current_phase']}</span>",
                    "</div>",
                    "</div>",
                    
                    # Visual Roadmap - חצים תוקנו לשמאל
                    "<div class='roadmap-box'>",
                    "<div class='roadmap-step'><span class='roadmap-label'>היינו ב:</span><span class='roadmap-value'>", roadmap_prev, "</span></div>",
                    "<div class='roadmap-arrow'>←</div>",
                    "<div class='roadmap-step'><span class='roadmap-label'>אנחנו ב:</span><span class='roadmap-value' style='color:#38bdf8;'>", rec_data['current_phase'], "</span></div>",
                    "<div class='roadmap-arrow'>←</div>",
                    "<div class='roadmap-step'><span class='roadmap-label'>היעד סביר:</span><span class='roadmap-value'>", roadmap_next, "</span></div>",
                    "</div>",
                    f"<div style='text-align:center; font-size:0.95rem; color:#cbd5e1; margin-bottom: 20px;'>💡 <b>פעולה נדרשת:</b> {roadmap_action}</div>",

                    "<hr class='scout-divider'>",
                    
                    # Stacked Vertically Section
                    "<div class='scout-stats-grid'>",
                    
                    "<div class='scout-stat-box'>",
                    "<div class='scout-section-title'>📊 מנוע הסתברויות</div>",
                    "<div class='scout-list-item'>",
                    "<span>סיכוי פריצה (30 יום):</span> ",
                    f"<span style='color:#34d399; font-weight:bold; font-size:1.15rem;'>{rec_data['prob_engine']['breakout_30d']}% 🚀</span>",
                    "</div>",
                    "<div class='scout-list-item'>",
                    "<span>סיכון הפצה/שבירה:</span> ",
                    f"<span style='color:#ef4444; font-weight:bold; font-size:1.15rem;'>{rec_data['prob_engine']['distribution_risk']}% 📉</span>",
                    "</div>",
                    f"<div class='edu-box'><span class='edu-box-title'>🎓 פינת הלמידה: מה המספרים אומרים?</span>{edu_note}</div>",
                    "</div>",
                    
                    "<div class='scout-stat-box'>",
                    "<div class='scout-section-title'>👁️ Smart Money Flow</div>",
                    smart_money_html,
                    "</div>",
                    
                    "<div class='scout-stat-box'>",
                    "<div class='scout-section-title'>🏢 סיכום פונדמנטלי מהיר</div>",
                    f"<div class='scout-list-item'><span>מכפיל רווח עתידי (Fwd P/E):</span> <span style='font-weight:bold; color:{rec_data.get('fundamental', {}).get('valuation_color', '#fff')}'>{rec_data.get('fundamental', {}).get('pe_forward', 'N/A')} ({rec_data.get('fundamental', {}).get('valuation', '-')})</span></div>",
                    f"<div class='scout-list-item'><span>דוח רווחים קרוב:</span> <span>{rec_data.get('fundamental', {}).get('next_earnings', 'N/A')}</span></div>",
                    f"<div class='scout-list-item'><span>סינתזה (Wyckoff + Fund):</span> <span style='font-weight:bold;'>{rec_data.get('fundamental', {}).get('synthesis', '-')}</span></div>",
                    "</div>",
                    
                    "</div>", # Close scout-stats-grid
                    
                    f"<div class='scout-alert-box' style='border-color: {alert_border}; background: {alert_bg};'>",
                    "<span class='scout-alert-title'>🛡️ מערכת הגנה ממלכודות (Failure Detection):</span>",
                    failure_html,
                    "</div>",
                    "</div>",
                    "</div>",
                ]
                st.markdown("".join(card_parts), unsafe_allow_html=True)
                
                with st.expander(f"📝 Trading Plan & Replay Engine ל-{tkr}", expanded=False):
                    st.markdown("#### 🗺️ תרחישי מפת הדרכים (What-if Analysis)")
                    st.markdown(f"**✅ תרחיש חיובי במידה והתבנית מצליחה:** {roadmap_success}")
                    st.markdown(f"**❌ תרחיש שלילי במידה והתבנית נכשלת:** {roadmap_fail}")

                    st.markdown("---")
                    st.markdown("#### 🎯 תוכנית מסחר (Trading Plan)")
                    st.markdown(f"**פעולה מומלצת:** {rec_data['action']}")
                    st.markdown(f"**מחיר סגירה (Close):** ${rec_data['entry_price']:.2f}")

                    if rec in ("SELL", "STRONG SELL"):
                        st.warning("🚫 לא קיימת תוכנית מסחר ללונג במצב זה. ההסתברות לצבירה מוסדית נמוכה מדי / הנכס בפאזת הפצה.")
                    else:
                        st.markdown(f"**הגנת הפסד דינמית (Stop Loss):** ${rec_data['stop_loss_price']:.2f} ({rec_data['stop_loss_pct']:.1f}%)")
                        if rec in ("BUY", "STRONG BUY"):
                            st.markdown(f"**יעד ראשון (TP1 - שחרור חצי):** ${rec_data['tp1_price']:.2f} (+{rec_data['tp1_pct']:.1f}%)")
                            st.markdown(f"**יעד שני (TP2 - שחרור מלא):** ${rec_data['tp2_price']:.2f} (+{rec_data['tp2_pct']:.1f}%)")
                            st.markdown(f"**יחס סיכוי/סיכון משוער (R/R):** {rec_data['rr_ratio']}")
                            st.markdown(f"**טווח זמן אופטימלי (Timeframe):** {rec_data['timeframe']}")
                        else:
                            st.info("ℹ️ ההמלצה היא HOLD - מומלץ להמתין לאישור טרנד לפני קביעת יעדים אגרסיביים.")

                    st.markdown("---")
                    st.markdown("#### ⏮️ היסטוריית תבניות (Replay Engine)")
                    st.markdown(f"חיפוש תרחישים מוסדיים אנלוגיים מן העבר המצליבים את נתוני הכסף החכם הנוכחיים של **{tkr}**:")
                    for rep in rec_data['replay']:
                        st.markdown(f"- {rep}")

def screen_backtest() -> None:
    st.markdown("### 📊 Backtest Engine")
    
    st.info("ℹ️ **מה זה בעצם Backtest (בדיקת עבר)?**\n\nמסך זה מאפשר לך 'לחזור בזמן' ולבדוק איך שיטת Wyckoff הייתה עובדת בפועל על המניה שבחרת. המערכת מריצה סימולציה ממוחשבת שבה היא קונה ומוכרת באופן אוטומטי את המניה בכל פעם שהתנאים של כניסת כסף מוסדי (ציון CIS ופאזות איסוף) מתקיימים.\n\n**התוצאות שתראה כאן יעזרו לך להבין:**\n- האם המניה הזו נוטה 'להקשיב' לכללי Wyckoff לאורך זמן?\n- מה ההסתברות שצבירה מוסדית תניב רווח בפועל בנכס הזה?")
    
    col1, col2 = st.columns([1,1])
    ticker = col1.text_input("Ticker לבדיקה", value="COST").strip().upper()
    bt_period = col2.selectbox("תקופת Backtest:", ["1y", "2y", "5y", "10y", "max"], index=1)
    bt_threshold = st.slider("סף כניסה (CIS Threshold)", 40, 95, 65)

    if st.button("▶ הרץ סימולציה", type="primary"):
        with st.spinner("מריץ Backtest היסטורי..."):
            df, audit_df = run_wyckoff_anchored_backtest(
                ticker, st.session_state.use_ml, bt_threshold, period=bt_period
            )
        if df is None or df.empty:
            st.error("אין נתונים.")
            return
            
        t_count = len(audit_df)
        if t_count > 0:
            win_rate = audit_df['is_win'].mean() * 100
            total_profit_pct = df['Cum_Strategy'].iloc[-1] * 100 if 'Cum_Strategy' in df.columns else 0.0
            
            max_dd_pct = 0.0
            if 'Cum_Strategy' in df.columns:
                roll_max = (1 + df['Cum_Strategy']).cummax()
                drawdown = ((1 + df['Cum_Strategy']) - roll_max) / roll_max
                max_dd_pct = drawdown.min() * 100
                
            profit_color = "🟢 רווח" if total_profit_pct > 0 else "🔴 הפסד"
            
            st.success(f"""### 📊 סיכום תוצאות הסימולציה מילולית:
הסימולציה הסתיימה! להלן התוצאות בהתבסס על ההסתברות לצבירה מוסדית:

* 💰 **שורה תחתונה:** האסטרטגיה סיימה ב{profit_color} מצטבר של **{total_profit_pct:.2f}%**.
* 🤝 **פעילות:** המערכת מצאה **{t_count}** הזדמנויות איסוף מוסדי.
* 🎯 **אחוזי הצלחה (Win Rate):** מתוך כל העסקאות, **{win_rate:.1f}%** הסתיימו ברווח.
* 📉 **רגעים קשים (Max Drawdown):** במהלך התקופה, ההפסד המקסימלי הרצוף עמד על **{max_dd_pct:.2f}%**.
""")
        else:
            st.warning("לא בוצעו עסקאות שעמדו בתנאים בתקופה זו. כנראה שהמניה לא חוותה איסוף מוסדי שעמד בסף הנדרש.")
            
        st.metric("עסקאות סה״כ", t_count)
        if audit_df is not None and not audit_df.empty:
            st.dataframe(audit_df)

def screen_monitor() -> None:
    st.markdown("### 👁️ Institutional Performance Monitor")
    
    st.markdown("#### ניתוח עומק לנכס (Performance Analytics)")
    col_t, col_p, col_b = st.columns([2, 1, 1])
    test_ticker = col_t.text_input("הזן סימול (Ticker) לחילוץ מטריקות ודרואו-דאון:", value="NVDA", key="monitor_ticker").strip().upper()
    
    monitor_period = col_p.selectbox("בחר תקופת היסטוריה לאנליזה:", ["2y", "5y", "10y", "max"], index=2)
    
    if col_b.button("📈 חלץ מטריקות מתקדמות", use_container_width=True):
        with st.spinner(f"מחשב מדדים היסטוריים ל-{test_ticker}..."):
            from scout_core import run_wyckoff_anchored_backtest, calculate_advanced_metrics, calculate_phase_followthrough
            df, audit_df = run_wyckoff_anchored_backtest(test_ticker, use_ai=st.session_state.use_ml, threshold=65, period=monitor_period)
            if audit_df is not None and not audit_df.empty:
                trades = audit_df.to_dict('records')
                metrics = calculate_advanced_metrics(trades)
                render_monitor_metrics(metrics)
                
                st.markdown("---")
                st.markdown("#### 🎯 דיוק זיהוי Wyckoff (ללא תלות ברווח)")
                st.caption("מדד Phase Follow-Through: בוחן האם זיהוי השלב הוביל לתנועת מחיר מצופה במונחי הסתברות מוסדית.")
                
                follow_through_stats = calculate_phase_followthrough(df, horizon=20, threshold_pct=0.04)
                if follow_through_stats:
                    ft_df = pd.DataFrame([
                        {"סוג פאזה": k, "סה״כ זיהויים": v["total"], "זיהויים מוצלחים": v["success"], "אחוז דיוק": f"{v['rate']:.1f}%"}
                        for k, v in follow_through_stats.items()
                    ])
                    st.dataframe(ft_df, use_container_width=True, hide_index=True)
                else:
                    st.info("אין מספיק נתוני פאזות לחישוב מדד זה בטווח הזמן שנבחר.")
                
                with st.expander("📝 יומן עסקאות מלא (Audit Log)", expanded=False):
                    st.dataframe(audit_df, use_container_width=True)
            else:
                st.warning("לא נמצאו מספיק עסקאות להפקת מדדים באסטרטגיה הנוכחית עבור נכס זה.")
                
    st.markdown("---")
    st.markdown("#### הורדת מודלים (Cloud Models Archive)")
    if st.button("🔄 רענן מודלים מהדיסק"):
        st.session_state.model_archive = load_all_models_from_disk()

    archive = st.session_state.model_archive
    if archive:
        cols = st.columns(3)
        for i, slot in enumerate(list(archive.keys())):
            safe_slot = clean_filename(str(slot))
            model_path = os.path.join(MODEL_DIR, f"model_{safe_slot}.pkl")
            if os.path.exists(model_path):
                with open(model_path, "rb") as f:
                    data = f.read()
                
                with cols[i % 3]:
                    st.download_button(
                        label=f"⬇️ הורד {slot}",
                        data=data,
                        file_name=f"model_{safe_slot}.pkl",
                        mime="application/octet-stream",
                        use_container_width=True,
                    )
    else:
        st.info("לא נמצאו מודלים בתיקייה. הרץ את הטריינר תחילה.")

def screen_ml_trainer() -> None:
    st.markdown("### 🧠 Wyckoff Pattern AI Trainer (Institutional Grade)")
    st.caption("אימון מודל AI מבוסס על איתור הסתברויות לצבירה מוסדית. מותאם ל-Cloud Run.")

    status = "Waiting"
    progress_text = ""
    is_running = False

    if os.path.exists(AUTO_TRAINER_STATUS_FILE):
        try:
            with open(AUTO_TRAINER_STATUS_FILE, "r", encoding="utf-8") as f:
                status_data = json.load(f)
            raw_status = status_data.get("state") or status_data.get("status") or "Waiting"
            status = raw_status.capitalize()
            progress_text = status_data.get("progress", "")
            if status.lower() == "running":
                is_running = True
        except Exception:
            pass

    if not is_running and os.path.exists(AUTO_TRAINER_PID_FILE):
        is_running = True
        status = "Running"
        progress_text = "מעבד נתונים (PID פעיל)..."

    if os.path.exists(AUTO_TRAINER_DONE_FLAG):
        status = "Completed"
        is_running = False
    elif os.path.exists(AUTO_TRAINER_STATUS_FILE) and status.lower() == "error":
        is_running = False

    if is_running:
        st.info(f"🟢 **סטטוס מערכת:** רץ כרגע ברקע | {progress_text}")
    elif status.lower() == "completed":
        st.success("✅ **סטטוס מערכת:** האימון הסתיים בהצלחה.")
    elif status.lower() == "error":
        st.error("🔴 **סטטוס מערכת:** תהליך נכשל. סקור את הלוגים למטה.")
    else:
        st.warning("⏳ **סטטוס מערכת:** בהמתנה להוראות ביצוע.")

    all_possible_tickers = ["NVDA", "AAPL", "MSFT", "BN", "BTC-USD", "GLD", "TSLA"]

    for t in all_possible_tickers:
        chk_key = f"chk_{t}"
        if chk_key not in st.session_state:
            st.session_state[chk_key] = (t in st.session_state.selected_tickers)

    if not is_running:
        st.markdown("#### 🎯 הקצאת נכסים לאימון")
        cols = st.columns(5)
        for i, t in enumerate(all_possible_tickers):
            cols[i % 5].checkbox(t, key=f"chk_{t}")

        st.session_state.selected_tickers = [
            t for t in all_possible_tickers if st.session_state.get(f"chk_{t}", False)
        ]

        if st.button("🚀 הפעל אימון נתונים (Execute Script)", type="primary", use_container_width=True):
            if not st.session_state.selected_tickers:
                st.error("יש לבחור לפחות מניה אחת לאימון.")
                return

            ensure_dirs()
            try:
                with open(BATCH_CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump({"tickers": list(st.session_state.selected_tickers)}, f)
            except Exception as e:
                st.error(f"שגיאה בכתיבת קונפיגורציה: {e}")
                return

            files_to_clean = [AUTO_TRAINER_DONE_FLAG, AUTO_TRAINER_STATUS_FILE, AUTO_TRAINER_PID_FILE, AUTO_TRAINER_LOG_FILE]
            for fp in files_to_clean:
                if os.path.exists(fp):
                    try:
                        os.remove(fp)
                    except OSError:
                        pass

            trainer_path = os.path.join(BASE_DIR, "auto_trainer_fixed.py")
            if os.path.exists(trainer_path):
                log_fd = open(AUTO_TRAINER_LOG_FILE, "a", encoding="utf-8")
                subprocess.Popen(
                    [sys.executable, trainer_path],
                    cwd=BASE_DIR,
                    stdout=log_fd,
                    stderr=subprocess.STDOUT,
                    close_fds=True,
                    start_new_session=True
                )
                log_fd.close() 
                st.success("הפקודה נשלחה לשרת!")
                time.sleep(1.5)
                st.rerun()

    if st.button("🔄 רענן סטטוס אימון"):
        st.rerun()

    st.markdown("#### 📜 לוגים מהשרת")
    log_content = "ממתין לפקודות שרת..."
    if os.path.exists(AUTO_TRAINER_LOG_FILE):
        try:
            with open(AUTO_TRAINER_LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            log_content = "".join(lines[-100:]) if lines else "קובץ הלוג ריק כרגע."
        except Exception:
            pass
    st.text_area("Log", value=log_content, height=300, disabled=True, label_visibility="collapsed")

def main() -> None:
    init_session_state()
    inject_css()

    st.markdown(
        '<div class="main-header"><h1>📈 Wyckoff Institutional Analyst</h1>'
        '<p>מערכת זיהוי דפוסי איסוף, הפצה וכניסת כסף חכם | Cloud Run Edition</p></div>',
        unsafe_allow_html=True
    )

    # Added Fundamental Analysis to Tabs
    tabs = st.tabs(["🏠 Home (Wyckoff Analyst)", "🗺️ Institutional Map", "📊 Fundamental Analysis", "📈 Trading Scout", "📊 Backtest", "👁️ Monitor", "🧠 ML Trainer"])
    screen_fns = [screen_home, screen_institutional_map, screen_fundamental, screen_trading_scout, screen_backtest, screen_monitor, screen_ml_trainer]
    
    for tab, fn in zip(tabs, screen_fns):
        with tab:
            fn()

if __name__ == "__main__":
    main()
