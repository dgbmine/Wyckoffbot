"""
============================================================
INSTITUTIONAL SCOUT PRO V17.7 (Stale-Widget Handoff Fix + Back/Top Nav + No Charts + Value-Analysis Naming)
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
        synthesize_verdict, build_fundamental_narrative, scan_top_opportunities, render_verdict_banner_html
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
        def build_fundamental_narrative(fd, t, v=None): return "מודול ניתוח חסר."
        def scan_top_opportunities(tickers, top_n=5, mode="Balanced"): return []
        def render_verdict_banner_html(v, ticker="", cis_score=None, current_phase="", valuation=None, valuation_color="#94a3b8", extra_chips=None): return ""
        
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

        def build_fundamental_narrative(fd, t, v=None):
            return "מודול ניתוח חסר."

        def scan_top_opportunities(tickers, top_n=5, mode="Balanced"):
            return []

        def render_verdict_banner_html(v, ticker="", cis_score=None, current_phase="", valuation=None, valuation_color="#94a3b8", extra_chips=None):
            return ""


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
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Hebrew:wght@300;400;500;600;700&family=Inter:wght@400;500;600;700;800&display=swap');

    /* ============================================================
       INSTITUTIONAL MINIMALIST DESIGN SYSTEM (V17.1)
       Palette: deep navy canvas, single cyan accent, semantic RGB
       ============================================================ */
    :root {
        --bg-0: #0a0e1a;          /* canvas */
        --bg-1: #0f1626;          /* surface */
        --bg-2: #151d30;          /* raised surface */
        --bg-3: #1c2640;          /* hover / active */
        --line: rgba(148,163,184,0.12);
        --line-strong: rgba(148,163,184,0.20);
        --txt-1: #e8eef7;         /* primary text */
        --txt-2: #9fb0c8;         /* secondary */
        --txt-3: #64748b;         /* muted */
        --accent: #38bdf8;        /* single brand accent */
        --pos: #22c55e;
        --pos-soft: #4ade80;
        --neg: #ef4444;
        --warn: #eab308;
        --warn-soft: #facc15;
        --radius: 16px;
        --radius-lg: 22px;
        --shadow: 0 10px 40px rgba(0,0,0,0.35);
    }

    html, body, [class*="css"] {
        font-family: 'IBM Plex Sans Hebrew', 'Inter', sans-serif;
        direction: rtl; text-align: right;
        background: var(--bg-0); color: var(--txt-1);
        letter-spacing: 0.1px;
    }
    .block-container { padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1180px; }

    /* generous whitespace between stacked blocks */
    .element-container { margin-bottom: 2px; }

    h1,h2,h3,h4 { letter-spacing: -0.2px; }
    hr { border-color: var(--line) !important; }

    /* ---------- Header ---------- */
    .main-header {
        padding: 1.3rem 1.7rem; border-radius: var(--radius-lg);
        background:
            radial-gradient(120% 140% at 100% 0%, rgba(56,189,248,0.10), transparent 55%),
            linear-gradient(135deg, rgba(10,16,28,0.92), rgba(15,22,40,0.96));
        box-shadow: var(--shadow); margin-bottom: 0;
        border: 1px solid var(--line);
    }
    .main-header h1 { margin: 0; font-size: 1.9rem; color: var(--txt-1); font-weight: 800; }
    .main-header p { color: var(--txt-2); font-size: 0.98rem; margin-top: 6px; font-weight: 400; }

    /* ---------- Metrics ---------- */
    [data-testid="stMetric"] {
        background: var(--bg-1) !important;
        border: 1px solid var(--line) !important;
        border-radius: var(--radius); padding: 1.1rem 1.2rem;
    }
    [data-testid="stMetricValue"] { color: var(--accent) !important; font-weight: 800 !important; }
    [data-testid="stMetricLabel"] { color: var(--txt-2) !important; font-weight: 500 !important; }
    [data-testid="stMetricDelta"] { color: var(--pos-soft) !important; }

    /* ---------- Buttons ---------- */
    .stButton > button {
        border-radius: 12px !important; font-weight: 600 !important;
        border: 1px solid var(--line-strong) !important;
        background: var(--bg-2) !important; color: var(--txt-1) !important;
        transition: all 0.18s ease !important;
    }
    .stButton > button:hover {
        border-color: var(--accent) !important;
        background: var(--bg-3) !important;
        transform: translateY(-1px);
    }
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #0ea5e9, #38bdf8) !important;
        color: #04121f !important; border: none !important; font-weight: 700 !important;
        box-shadow: 0 6px 20px rgba(56,189,248,0.25) !important;
    }
    .stButton > button[kind="primary"]:hover { filter: brightness(1.08); transform: translateY(-1px); }

    /* selectbox / radio / inputs */
    .stTextInput input, .stSelectbox div[data-baseweb="select"] > div {
        background: var(--bg-1) !important; border-color: var(--line-strong) !important;
        border-radius: 10px !important; color: var(--txt-1) !important;
    }

    /* expander */
    .streamlit-expanderHeader, [data-testid="stExpander"] summary {
        background: var(--bg-1) !important; border-radius: 12px !important;
        border: 1px solid var(--line) !important; font-weight: 600 !important;
    }

    /* ---------- Section eyebrow label ---------- */
    .section-label {
        font-size: 0.74rem; letter-spacing: 2px; text-transform: uppercase;
        color: var(--txt-3); font-weight: 700; margin: 4px 0 10px 0; display:block;
    }

    /* ============================================================
       PRICE HEADER (price + timestamp next to every ticker)
       ============================================================ */
    .price-header {
        display: inline-flex; flex-direction: column; align-items: flex-start;
        background: linear-gradient(145deg, var(--bg-2), var(--bg-1));
        padding: 12px 24px; border-radius: var(--radius); margin: 6px 0 22px 0;
        border: 1px solid var(--line-strong);
        box-shadow: 0 4px 18px rgba(0,0,0,0.25);
    }
    .price-header .ph-ticker { font-size: 0.82rem; color: var(--txt-2); font-weight: 600; letter-spacing: 0.5px; }
    .price-header .ph-price  { font-size: 2.05rem; color: var(--txt-1); font-weight: 800; line-height: 1.05; margin-top: 2px; }
    .price-header .ph-time   { font-size: 0.76rem; color: var(--txt-3); margin-top: 4px; }
    .price-header .ph-chg-pos { color: var(--pos-soft); font-weight: 700; font-size: 1rem; }
    .price-header .ph-chg-neg { color: var(--neg); font-weight: 700; font-size: 1rem; }

    /* ============================================================
       VERDICT BANNER — the single unified "bottom line" component
       ============================================================ */
    .verdict-banner {
        position: relative; display: flex; gap: 0;
        background:
            radial-gradient(140% 120% at 100% 0%, color-mix(in srgb, var(--vb-color) 12%, transparent), transparent 60%),
            linear-gradient(135deg, var(--bg-2), var(--bg-1));
        border: 1px solid var(--line-strong);
        border-radius: var(--radius-lg); overflow: hidden;
        margin: 10px 0 28px 0; box-shadow: var(--shadow);
    }
    .verdict-banner .vb-accent {
        width: 6px; flex: 0 0 6px; background: var(--vb-color);
        box-shadow: 0 0 24px color-mix(in srgb, var(--vb-color) 60%, transparent);
    }
    .verdict-banner .vb-body { padding: 26px 28px; flex: 1; }
    .vb-top { display:flex; align-items:center; gap:14px; flex-wrap:wrap; margin-bottom: 6px; }
    .vb-ticker {
        font-family:'Inter',sans-serif; font-weight:800; font-size:1.05rem; color:var(--txt-2);
        background: var(--bg-3); padding: 4px 12px; border-radius: 8px; letter-spacing:0.5px;
    }
    .vb-headline { font-size: 1.55rem; font-weight: 800; line-height: 1.15; }
    .vb-action { font-size: 1.05rem; font-weight: 700; margin: 6px 0 10px 0; line-height: 1.5; }
    .vb-detail { font-size: 0.98rem; color: var(--txt-2); line-height: 1.7; }
    .vb-chips { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; }
    .vb-chip {
        background: var(--bg-3); border: 1px solid var(--line);
        border-radius: 20px; padding: 5px 14px; font-size: 0.82rem; color: var(--txt-2); font-weight: 600;
    }
    .vb-chip b { color: var(--txt-1); }

    /* legacy verdict-* classes kept as aliases so nothing breaks */
    .verdict-eyebrow { font-size:0.74rem; letter-spacing:2px; text-transform:uppercase; color:var(--txt-3); font-weight:700; }
    .verdict-headline { font-size: 1.5rem; font-weight: 800; }
    .verdict-detail { font-size: 0.98rem; color: var(--txt-2); line-height: 1.7; }
    .verdict-chips { display:flex; gap:10px; flex-wrap:wrap; margin-top:12px; }
    .verdict-chip { background:var(--bg-3); border:1px solid var(--line); border-radius:20px; padding:5px 14px; font-size:0.82rem; color:var(--txt-2); font-weight:600; }
    .verdict-accent-bar { height:4px; border-radius:4px; }

    /* ============================================================
       REASON / NARRATIVE boxes (the human "why")
       ============================================================ */
    .reason-box {
        background: var(--bg-1); border-right: 3px solid var(--accent);
        border-radius: 12px; padding: 15px 20px; margin: 4px 0 20px 0;
        font-size: 0.97rem; color: var(--txt-1); line-height: 1.75;
    }
    .narrative-box {
        background: linear-gradient(145deg, var(--bg-2), var(--bg-1));
        border: 1px solid var(--line); border-right: 3px solid var(--accent);
        border-radius: var(--radius); padding: 24px 28px; margin: 12px 0 28px 0;
        font-size: 1.0rem; color: var(--txt-1); line-height: 1.9;
    }
    .narrative-title { color: var(--accent); font-weight: 800; font-size: 1.05rem; display:block; margin-bottom: 12px; letter-spacing:0.3px; }

    /* ============================================================
       HOME — Opportunity pick cards
       ============================================================ */
    .pick-card {
        background: linear-gradient(155deg, var(--bg-2), var(--bg-1));
        border: 1px solid var(--line); border-radius: var(--radius);
        padding: 18px 20px; margin-bottom: 12px; height: 100%;
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .pick-card:hover { transform: translateY(-3px); border-color: var(--accent); }
    .pick-rank { font-family:'Inter'; font-size: 0.72rem; color: var(--txt-3); font-weight: 800; letter-spacing: 1.5px; }
    .pick-ticker { font-family:'Inter'; font-size: 1.7rem; font-weight: 800; color: var(--txt-1); line-height: 1.05; margin: 2px 0; }
    .pick-headline { font-size: 0.92rem; font-weight: 700; margin: 8px 0 8px 0; line-height:1.4; }
    .pick-meta { font-size: 0.8rem; color: var(--txt-2); line-height: 1.65; }
    .pick-score-pill {
        display:inline-block; background: rgba(56,189,248,0.12); color: var(--accent);
        border-radius: 14px; padding: 3px 12px; font-size: 0.78rem; font-weight: 700; margin-top: 10px;
    }

    /* ============================================================
       FUNDAMENTAL screen
       ============================================================ */
    .fund-card {
        background: var(--bg-1); border: 1px solid var(--line);
        border-radius: var(--radius); padding: 24px 26px; margin-bottom: 20px;
    }
    .fund-table-title {
        color: var(--txt-1); font-size: 1.1rem; font-weight: 700;
        margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--line);
    }
    .fund-meta-row { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 20px; }
    .fund-meta-box {
        flex: 1; min-width: 200px; background: var(--bg-1);
        border: 1px solid var(--line); border-radius: 14px; padding: 16px 18px;
    }
    .fund-meta-label { font-size: 0.8rem; color: var(--txt-2); margin-bottom: 6px; }
    .fund-meta-value { font-size: 1.25rem; font-weight: 700; color: var(--txt-1); }
    /* legacy fund verdict box aliases */
    .fund-verdict-box { text-align:center; border-radius:var(--radius); padding:24px; margin-bottom:20px; border:1px solid var(--line); }
    .fund-verdict-label { font-size:0.9rem; color:var(--txt-2); margin-bottom:6px; }
    .fund-verdict-value { font-size:2.2rem; font-weight:800; }
    .fund-verdict-sub { font-size:0.9rem; color:var(--txt-2); margin-top:8px; }
    .fund-synth-box { background:var(--bg-1); border-right:3px solid var(--accent); border-radius:12px; padding:16px 20px; margin-bottom:20px; font-size:1.05rem; font-weight:700; color:var(--txt-1); }

    /* ============================================================
       TRADING SCOUT — premium cards
       ============================================================ */
    .scout-wrapper { width: 100%; margin-bottom: 34px; }
    .scout-card {
        background: linear-gradient(155deg, var(--bg-2), var(--bg-1));
        border: 1px solid var(--line-strong); border-radius: var(--radius-lg);
        padding: 30px 28px; box-shadow: var(--shadow);
        position: relative; overflow: hidden;
        transition: border-color 0.2s ease, transform 0.2s ease;
    }
    .scout-card::before {
        content:''; position:absolute; top:0; left:0; right:0; height:4px;
        background: linear-gradient(90deg, transparent, var(--accent), transparent); opacity:0.8;
    }
    .scout-card:hover { transform: translateY(-3px); border-color: rgba(56,189,248,0.5); }
    .scout-header { display:flex; justify-content:space-between; align-items:center; margin-bottom: 22px; }
    .scout-title { color: var(--txt-1); font-size: 1.8rem; font-weight: 800; margin:0; display:flex; align-items:center; }
    .scout-title-sub { font-size: 1rem; color: var(--txt-2); font-weight: 400; padding-right: 12px; }
    .scout-badge { padding: 8px 20px; border-radius: 30px; font-size: 0.95rem; font-weight: 700; background: var(--bg-3); border: 1px solid var(--line-strong); }
    .scout-prob-container { text-align: center; margin-bottom: 18px; }
    .scout-prob-label { margin:0; color: var(--txt-2); font-weight:600; letter-spacing:1.5px; font-size:0.85rem; text-transform:uppercase; }
    .scout-prob { font-size: 4.4rem; font-weight: 800; color: var(--accent); margin: 8px 0 14px 0; line-height: 1; text-shadow: 0 0 35px rgba(56,189,248,0.4); }
    .scout-phase-pill { display:inline-block; background: var(--bg-0); padding: 9px 20px; border-radius: 25px; border: 1px solid var(--line); }
    .scout-divider { border-top: 1px solid var(--line); margin: 24px 0; }
    .scout-stats-grid { display:flex; flex-direction:column; gap: 20px; margin-bottom: 22px; }
    .scout-stat-box { flex:1; background: var(--bg-1); border:1px solid var(--line); border-radius:16px; padding: 20px; display:flex; flex-direction:column; }
    .scout-section-title { color: var(--txt-1); font-size: 1.08rem; font-weight: 700; margin-bottom: 14px; border-bottom: 1px solid var(--line); padding-bottom: 10px; }
    .scout-list-item { font-size: 1.0rem; color: var(--txt-2); margin-bottom: 12px; display:flex; justify-content:space-between; align-items:center; }
    .scout-alert-box { padding: 18px 22px; border-radius: 14px; margin-top: 22px; border-right: 4px solid var(--neg); background: rgba(239,68,68,0.06); }
    .scout-alert-title { font-size: 1.05rem; color: var(--txt-1); font-weight:bold; margin-bottom:12px; display:block; }
    .scout-alert-text { font-size: 0.92rem; display:block; color: var(--txt-2); line-height: 1.6; margin-bottom: 6px; }
    .trap-section-label { font-size: 0.82rem; color: var(--txt-2); font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin: 14px 0 8px 0; display:block; }
    .trap-fund-highlight { background: rgba(239,68,68,0.10); border-right: 3px solid var(--neg); padding: 10px 14px; border-radius: 8px; font-weight: 600; color: #fecaca !important; }
    .edu-box { background: rgba(56,189,248,0.05); border-right: 3px solid var(--accent); padding: 16px; margin-top: 18px; border-radius: 10px; font-size: 0.93rem; color: var(--txt-1); line-height: 1.75; flex-grow: 1; }
    .edu-box-title { color: var(--accent); font-weight: 700; display:block; margin-bottom: 10px; font-size: 1.0rem; }

    /* Roadmap inside scout card */
    .roadmap-box { background: var(--bg-1); border-radius: 14px; padding: 20px 26px; margin-top: 22px; margin-bottom: 12px; border-right: 3px solid var(--accent); display:flex; justify-content:center; align-items:center; gap: 26px; font-size: 0.95rem; color: var(--txt-2); flex-wrap: wrap; }
    .roadmap-step { display:flex; flex-direction:column; align-items:center; gap: 4px; }
    .roadmap-label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 6px; color: var(--txt-3); }
    .roadmap-value { font-weight: 600; color: var(--txt-1); font-size: 1.0rem; }
    .roadmap-arrow { color: var(--txt-3); font-size: 1.3rem; font-weight: bold; }

    /* Staged trade plan */
    .plan-stage { background: var(--bg-1); border:1px solid var(--line); border-radius: 12px; padding: 14px 18px; margin-bottom: 10px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; }
    .plan-stage-label { font-weight: 700; color: var(--txt-1); font-size: 1.0rem; }
    .plan-stage-val { font-weight: 800; font-size: 1.15rem; }
    .plan-stage-note { font-size: 0.84rem; color: var(--txt-2); width:100%; margin-top: 4px; line-height:1.5; }

    /* ============================================================
       INSTITUTIONAL MAP cards
       ============================================================ */
    .map-card {
        background: linear-gradient(180deg, var(--bg-2) 0%, var(--bg-1) 100%);
        padding: 30px 24px; border-radius: var(--radius-lg); text-align: center;
        box-shadow: var(--shadow); margin-bottom: 26px; border: 1px solid var(--line);
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .map-card:hover { transform: translateY(-4px); border-color: rgba(56,189,248,0.5); }
    .map-card h4 { margin:0; font-size: 1.3rem; color: var(--txt-1); font-weight: 700; }
    .map-card-label { font-size: 0.88rem; color: var(--txt-2); margin: 12px 0 6px 0; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }
    .map-card-score { margin:0; font-size: 3.2rem; font-weight: 800; line-height: 1.1; }
    .map-desc { font-size: 0.9rem; color: var(--txt-2); margin-top: 18px; line-height: 1.6; padding-top: 16px; border-top: 1px dashed var(--line-strong); }

    /* nav */
    .topnav-spacer { height: 8px; }
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
    if "current_page" not in st.session_state:
        st.session_state.current_page = "🏠 בית"
    if "handoff_ticker" not in st.session_state:
        st.session_state.handoff_ticker = None
    if "home_top_picks" not in st.session_state:
        st.session_state.home_top_picks = None
    if "plan_detail_level" not in st.session_state:
        st.session_state.plan_detail_level = "מלא"
    if "tech_unlocked" not in st.session_state:
        st.session_state.tech_unlocked = False
    if "home_result_ticker" not in st.session_state:
        st.session_state.home_result_ticker = None
    if "fund_result_ticker" not in st.session_state:
        st.session_state.fund_result_ticker = None
    if "scout_result_tickers" not in st.session_state:
        st.session_state.scout_result_tickers = None
    if "nav_history" not in st.session_state:
        st.session_state.nav_history = []


# יקום סריקה למסך הבית - 24 מניות מובילות (מהיר)
HOME_SCAN_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "CRM",
    "JPM", "V", "MA", "UNH", "LLY", "COST", "HD", "PG",
    "XOM", "CVX", "AMD", "PANW", "NFLX", "ABBV", "WMT", "KO",
]


def go_to_screen(page: str, ticker: str = None) -> None:
    """ניווט בין מסכים עם העברת טיקר (Cross-Screen Handoff). שומר היסטוריה לכפתור 'חזור'."""
    prev_page = st.session_state.get("current_page")
    if prev_page and prev_page != page:
        st.session_state.setdefault("nav_history", [])
        st.session_state.nav_history.append(prev_page)
    if ticker:
        st.session_state.handoff_ticker = ticker.strip().upper()
    st.session_state.current_page = page
    # תיקון קריטי: אסור להקצות ל-st.session_state["nav_select"] אחרי שה-widget עם אותו
    # key כבר אותחל באותה הרצה (render_top_nav רץ בתחילת main(), לפני קריאה זו) - זה גורם
    # ל-StreamlitAPIException. הפתרון הנכון: למחוק את המפתח (מותר), כך שבהרצה הבאה ה-selectbox
    # יאותחל מחדש לפי current_page/index, בלי "לקפוץ" חזרה לבחירה הקודמת.
    if "nav_select" in st.session_state:
        del st.session_state["nav_select"]
    st.rerun()


def go_back() -> None:
    """חזרה למסך הקודם לפי היסטוריית הניווט (לא מוסיף רישום חדש להיסטוריה - זו צריכת היסטוריה)."""
    history = st.session_state.get("nav_history", [])
    if not history:
        return
    prev_page = history.pop()
    st.session_state.current_page = prev_page
    if "nav_select" in st.session_state:
        del st.session_state["nav_select"]
    st.rerun()


_TECH_PASSWORD = "0549414442"


def _require_technician_password(screen_label: str) -> bool:
    """
    שער סיסמת טכנאי למסכים מתקדמים (Monitor / Backtest / ML Trainer).
    מחזיר True אם הגישה אושרה (כבר באותו session או הוקלדה כעת נכון), אחרת מציג
    שדה סיסמה ומחזיר False (כדי שהמסך הקורא יפסיק לרנדר תוכן רגיש).
    """
    if st.session_state.get("tech_unlocked"):
        return True

    st.markdown(f"### 🔒 {screen_label} - מסך מוגן")
    st.info("מסך זה מוגן בסיסמת טכנאי. הזן סיסמה כדי להמשיך.")
    pwd = st.text_input("סיסמת טכנאי", type="password", key=f"tech_pwd_input_{screen_label}")
    if st.button("🔓 אשר גישה", key=f"tech_pwd_btn_{screen_label}"):
        if pwd == _TECH_PASSWORD:
            st.session_state.tech_unlocked = True
            st.rerun()
        else:
            st.error("סיסמה שגויה.")
    return False


@st.cache_data(ttl=900, max_entries=128, show_spinner=False)
def get_price_and_time(ticker: str) -> tuple:
    """מחזיר (מחיר נוכחי, שינוי %, מחרוזת תאריך/שעה אחרונה). מקור: get_data דרך הקאש."""
    try:
        df = get_cached_data(ticker, period="6mo")
        if df is None or df.empty:
            return 0.0, 0.0, "N/A"
        price = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2]) if len(df) > 1 else price
        chg_pct = ((price - prev) / prev * 100) if prev else 0.0
        try:
            last_time = df.index[-1].strftime("%d.%m.%Y %H:%M")
        except Exception:
            last_time = str(df.index[-1])
        return price, chg_pct, last_time
    except Exception:
        return 0.0, 0.0, "N/A"


def render_price_header(ticker: str) -> None:
    """
    כותרת מחיר אחידה - מחיר נוכחי + 'מעודכן ל: תאריך ושעה' + שינוי יומי.
    חייבת להופיע בכל מקום שמוצג טיקר (Home, Fundamental, Trading Scout, Backtest, Monitor).
    """
    if not ticker:
        return
    price, chg_pct, last_time = get_price_and_time(ticker)
    if price <= 0:
        st.caption(f"⚠️ לא ניתן היה לשאוב מחיר עדכני עבור {ticker} כרגע.")
        return
    chg_cls = "ph-chg-pos" if chg_pct >= 0 else "ph-chg-neg"
    chg_sign = "+" if chg_pct >= 0 else ""
    st.markdown(
        f"""<div class='price-header'>
            <span class='ph-ticker'>{ticker}</span>
            <span class='ph-price'>${price:,.2f} <span class='{chg_cls}'>{chg_sign}{chg_pct:.2f}%</span></span>
            <span class='ph-time'>🕒 מעודכן ל: {last_time}</span>
        </div>""",
        unsafe_allow_html=True,
    )


def render_price_inline(ticker: str) -> str:
    """גרסה מוקטנת של כותרת המחיר, מוטבעת בתוך כרטיסים צפופים (Picks, סריקת סקטור)."""
    if not ticker:
        return ""
    price, chg_pct, last_time = get_price_and_time(ticker)
    if price <= 0:
        return "<span style='color:#64748b; font-size:0.78rem;'>מחיר לא זמין</span>"
    chg_cls = "ph-chg-pos" if chg_pct >= 0 else "ph-chg-neg"
    chg_sign = "+" if chg_pct >= 0 else ""
    return (
        f"<span style='font-weight:800; color:#e8eef7;'>${price:,.2f}</span> "
        f"<span class='{chg_cls}' style='font-size:0.82rem;'>{chg_sign}{chg_pct:.2f}%</span>"
        f"<br><span style='font-size:0.72rem; color:#64748b;'>🕒 {last_time}</span>"
    )


def render_verdict_banner(verdict: dict, ticker: str = "", cis_score: float = None,
                          current_phase: str = "", valuation: str = None,
                          valuation_color: str = "#94a3b8", extra_chips: list = None) -> None:
    """
    רכיב 'שורה תחתונה' אחיד - נקודת האמת הוויזואלית היחידה בכל המסכים.
    מאציל ל-render_verdict_banner_html שב-scout_core (כולל שורת פקודה אסרטיבית).
    היררכיה: כותרת הכרעה -> פקודת פעולה -> הסבר אנושי -> צ'יפים (ראיות).
    """
    if not verdict:
        return
    html = render_verdict_banner_html(
        verdict, ticker=ticker, cis_score=cis_score, current_phase=current_phase,
        valuation=valuation, valuation_color=valuation_color, extra_chips=extra_chips,
    )
    st.markdown(html, unsafe_allow_html=True)


# ============================================================
# Screens
# ============================================================

def _get_home_scan_pool(width_label: str) -> list:
    """בונה את יקום הסריקה בפועל לפי רוחב החיפוש שנבחר."""
    master = SECTOR_MAP.get("הכול (כל השוק האמריקאי)", [])
    if width_label == "24":
        return HOME_SCAN_UNIVERSE
    if width_label == "50":
        pool = list(HOME_SCAN_UNIVERSE)
        for t in master:
            if t not in pool:
                pool.append(t)
            if len(pool) >= 50:
                break
        return pool
    # "100+"
    pool = list(HOME_SCAN_UNIVERSE)
    for t in master:
        if t not in pool:
            pool.append(t)
    return pool


def _render_top_picks() -> None:
    """מציג עד 5 מניות בהזדמנות מצוינת (Wyckoff + פונדמנטלי איכותי). לחיצה -> ניתוח מלא."""
    st.markdown("#### 🌟 ההזדמנויות הבולטות בשוק כרגע (Wyckoff + פונדמנטלי)")
    st.caption("המערכת סורקת מניות מובילות ומציגה רק שילובים איכותיים: איסוף מוסדי מובהק יחד עם תמחור/איכות פונדמנטלית (סדר עדיפות ניתוח ערך). לחיצה על מניה פותחת ניתוח מלא.")

    if "home_scan_width" not in st.session_state:
        st.session_state.home_scan_width = "24"
    width_options = {
        "24": "24 מניות (~10-15 שניות)",
        "50": "50 מניות (~25-35 שניות)",
        "100+": "100+ מניות (~45-70 שניות)",
    }
    width_label = st.radio(
        "🔧 רוחב חיפוש (כמה מניות לסרוק)",
        options=list(width_options.keys()),
        format_func=lambda k: width_options[k],
        key="home_scan_width",
        horizontal=True,
        help="יקום גדול יותר = סיכוי גבוה יותר למצוא הזדמנות, אך הסריקה איטית יותר.",
    )
    pool = _get_home_scan_pool(width_label)
    eta = {"24": "10-15 שניות", "50": "כ-25-35 שניות", "100+": "כ-45-70 שניות"}[width_label]

    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button(f"🔍 סרוק {len(pool)} מניות", use_container_width=True, type="primary", key="scan_picks_btn"):
            if not SCOUT_CORE_AVAILABLE:
                st.error("מודול הליבה חסר.")
            else:
                with st.spinner(f"סורק {len(pool)} מניות לאיתור שילובי איכות ({eta})..."):
                    st.session_state.home_top_picks = scan_top_opportunities(pool, top_n=5, mode="Balanced")
    with c2:
        st.caption(f"זמן משוער לסריקה: {eta}")

    picks = st.session_state.get("home_top_picks")
    if picks is None:
        st.info("בחר רוחב חיפוש ולחץ 'סרוק' כדי לקבל את 5 המניות הבולטות ביותר כרגע לפי שכלול וואיקוף + פונדמנטלי.")
    elif not picks:
        st.warning("לא נמצאו כרגע שילובים איכותיים (איסוף מוסדי + פונדמנטל חזק) ביקום הסריקה. נסה רוחב חיפוש גדול יותר, או שהשוק במצב המתנה.")
    else:
        cols = st.columns(len(picks))
        for i, (col, p) in enumerate(zip(cols, picks)):
            with col:
                price_html = render_price_inline(p['ticker'])
                st.markdown(
                    f"""<div class='pick-card' style='border-top:4px solid {p['color']}; padding-bottom:10px;'>
                        <div class='pick-rank'>#{i+1}</div>
                        <div class='pick-ticker'>{p['ticker']}</div>
                        <div style='margin:4px 0 10px 0;'>{price_html}</div>
                    </div>""",
                    unsafe_allow_html=True,
                )
                # --- אותו רכיב Verdict Banner בדיוק כמו בכל מסך אחר (עקביות) ---
                verdict_like = {
                    "headline": p["headline"], "detail": p["detail"], "color": p["color"],
                    "tier": p["tier"], "action_line": p.get("action_line", ""),
                    "confidence": p.get("confidence", ""),
                }
                render_verdict_banner(
                    verdict_like, cis_score=p["cis"], current_phase=p.get("phase", ""),
                    valuation=p["valuation"], valuation_color=p["valuation_color"],
                    extra_chips=[f"FCF <b>{p['fcf_yield']}</b>", f"P/E <b>{p['pe']}</b>"],
                )
                st.markdown(
                    f"<div class='pick-score-pill'>ציון משוקלל: {p['composite']:.0f} · {p['sector_he']}</div>",
                    unsafe_allow_html=True,
                )
                if st.button(f"📊 נתח את {p['ticker']}", key=f"pick_{p['ticker']}_{i}", use_container_width=True):
                    go_to_screen("📊 ניתוח פונדמנטלי", p["ticker"])

    st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
    if st.button("🗺️ אפשרות לסריקות נוספות (לפי סקטור)", use_container_width=True, key="more_scans_btn"):
        go_to_screen("🗺️ מפה מוסדית")

    st.markdown("<hr style='border-color:rgba(255,255,255,0.08); margin:22px 0;'>", unsafe_allow_html=True)


def _render_home_fundamental_summary(ticker: str, cis_score: float, current_phase: str) -> None:
    """
    השורה התחתונה האחידה במסך הבית: סינתזת Wyckoff + פונדמנטלי (ניתוח ערך).
    הבאנר חייב להופיע *תמיד* - גם אם שאיבת הנתונים הפונדמנטליים נכשלה (synthesize_verdict
    יודע להתמודד עם fund_data חסר ולהציג הודעה ניטרלית ברורה, ולא לדלג על הרכיב כליל).
    """
    fdata = get_fundamental_data(ticker) or {}

    verdict = synthesize_verdict(fdata, cis_score, current_phase, ticker)
    valuation = fdata.get("valuation", "-") if fdata else None
    pe_disp = (fdata.get('pe_forward') if fdata.get('pe_forward') != 'N/A' else fdata.get('pe_trailing', 'N/A')) if fdata else "N/A"

    render_verdict_banner(
        verdict, ticker=ticker, cis_score=cis_score, current_phase=current_phase,
        valuation=valuation, valuation_color=fdata.get("valuation_color", "#94a3b8"),
        extra_chips=([
            f"מכפיל רווח <b>{pe_disp}</b>",
            f"FCF <b>{fdata.get('fcf_yield', 'N/A')}</b>",
            f"צמיחה <b>{fdata.get('rev_growth', 'N/A')}</b>",
        ] if fdata else None),
    )

    if fdata:
        narrative = build_fundamental_narrative(fdata, ticker, verdict)
        st.markdown(
            f"<div class='narrative-box'><span class='narrative-title'>🦅 ניתוח חופשי - מצב המניה הספציפי</span>{narrative}</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("⚠️ לא ניתן היה לשאוב נתונים פונדמנטליים עבור מניה זו כרגע - ההכרעה לעיל מבוססת על Wyckoff בלבד.")

    cta1, cta2 = st.columns([1, 2])
    with cta1:
        if st.button("🎯 קבל אסטרטגיית מסחר", type="primary", use_container_width=True, key="home_to_strategy"):
            go_to_screen("📈 Trading Scout", ticker)
    with cta2:
        st.caption("מעבר למסך המסחר עם ניתוח מוכן: מחיר כניסה, סטופ מדורג, יעדי שחרור חלקי וגודל פוזיציה - הכל לפי סיכום וואיקוף + פונדמנטלי.")


def screen_home() -> None:
    st.markdown("### 🏠 Wyckoff Analyst - רדאר הכסף החכם")

    st.markdown("""
    **ברוכים הבאים למערכת המוסדית!** המטרה: לענות על שאלה אחת - **"מה ההסתברות שגוף מוסדי אוסף כעת את המניה?"** - ולשלב זאת עם תמחור פונדמנטלי - ניתוח ערך.
    """)
    st.info("⚠️ **הבהרה:** המערכת היא כלי עזר אנליטי בלבד ואינה מהווה ייעוץ השקעות.")

    # --- 5 ההזדמנויות הבולטות בשוק ---
    _render_top_picks()

    # --- חיפוש מניה ספציפית ---
    st.markdown("#### 🔎 ניתוח מניה ספציפית")
    handoff_tkr = st.session_state.get("handoff_ticker")
    is_new_home_handoff = bool(handoff_tkr) and st.session_state.get("_home_consumed_handoff") != handoff_tkr
    if is_new_home_handoff and "home_ticker_input" in st.session_state:
        # תיקון קריטי: מוחקים את ה-widget הקודם כדי ש-value החדש (מהמסך הקודם) באמת יוצג -
        # אחרת Streamlit משאיר את הערך הישן שכבר הוקצה לאותו key, ונראה כאילו "לא קרה כלום".
        del st.session_state["home_ticker_input"]

    default_tkr = handoff_tkr or "NVDA"
    ticker = st.text_input("Ticker לניתוח (לדוגמה NVDA, TSLA, SPY)", value=default_tkr, key="home_ticker_input").strip().upper()

    run_clicked = st.button("▶ הרץ ניתוח מוסדי + פונדמנטלי", use_container_width=True, type="primary")
    # תמיכה ב-handoff: אם הגענו ממסך אחר עם טיקר, הרץ אוטומטית פעם אחת
    auto_run = is_new_home_handoff
    if auto_run:
        st.session_state._home_consumed_handoff = handoff_tkr

    # תיקון קריטי: אם נשמור את תוצאת הניתוח רק לפי run_clicked/auto_run (מצב חד-פעמי),
    # כל לחיצה על כפתור *בתוך* בלוק התוצאות (כמו "קבל אסטרטגיית מסחר") תגרום לבלוק כולו
    # להיעלם בריצה החדשה - כי run_clicked חוזר ל-False וה-handoff כבר נצרך. הפתרון: לשמור
    # את הטיקר המנותח ב-session_state כדי שהבלוק יישאר מוצג בכל ריצה הבאה, לא משנה איזה
    # widget גרם לה.
    if run_clicked or auto_run:
        st.session_state.home_result_ticker = ticker

    show_ticker = st.session_state.get("home_result_ticker")
    if show_ticker:
        ticker = show_ticker
        with st.spinner("מחשב מנוע Wyckoff מתקדם..."):
            result = _compute_wyckoff(ticker)

        if result is None:
            if not SCOUT_CORE_AVAILABLE:
                st.error("מודול הליבה (scout_core) לא נטען בהצלחה - לכן לא ניתן לשאוב נתונים.")
                if SCOUT_CORE_IMPORT_ERROR:
                    st.code(SCOUT_CORE_IMPORT_ERROR)
                st.caption("בדוק ב-requirements.txt שכל הספריות מותקנות, ושאין שגיאת ייבוא בקובץ scout_core.py.")
            else:
                st.error("אין נתונים זמינים או נדרש לפחות 60 ימי מסחר.")
            return

        render_price_header(ticker)

        # === השורה התחתונה (Verdict Banner) - ראשון ובולט, לפני כל פירוט טכני ===
        _render_home_fundamental_summary(ticker, result["current_cis"], result["current_phase"])

        # === מכאן ואילך: עומק טכני (Deep Dive) - וואיקוף מפורט ===
        st.markdown("<hr style='border-color: rgba(255,255,255,0.08); margin:26px 0 18px 0;'>", unsafe_allow_html=True)
        st.markdown("<div class='section-label'>🔍 ניתוח טכני מעמיק - Wyckoff Deep Dive</div>", unsafe_allow_html=True)

        with st.expander("📊 ציון הסתברות ומפת פאזות Wyckoff (Deep Dive)", expanded=True):
            left, right = st.columns([1, 1.3])

            with left:
                _cis_val = result["current_cis"]
                _cis_color = "#16a34a" if _cis_val >= 65 else ("#eab308" if _cis_val >= 40 else "#ef4444")
                st.markdown(
                    f"""<div style='text-align:center; background:var(--bg-1); border:1px solid var(--line-strong);
                        border-radius:var(--radius-lg); padding:28px 16px;'>
                        <div style='font-size:0.85rem; color:var(--txt-2); letter-spacing:1px; text-transform:uppercase;'>
                            הסתברות לצבירה (CIS)
                        </div>
                        <div style='font-size:3.6rem; font-weight:800; color:{_cis_color}; line-height:1.1; margin:10px 0;'>
                            {_cis_val:.0f}
                        </div>
                        <div style='font-size:0.85rem; color:var(--txt-3);'>מתוך 100</div>
                    </div>""",
                    unsafe_allow_html=True,
                )
                st.caption("ציון 0-100 המודד את עוצמת כניסת הכספים המוסדיים.")

            with right:
                st.markdown("#### איפה אנחנו בתהליך? (Wyckoff Phase)")
                cp = result["current_phase"]
                is_transition = any(x in cp for x in ["TRANSITION", "UNCERTAIN", "לא בתהליך"])
                if is_transition:
                    st.info("ℹ️ לא נמצא שלב Wyckoff מובהק כרגע (מעבר/חוסר ודאות).")
                    st.caption(f"**זיהוי מלא:** `{cp}`")
                else:
                    is_bearish = any(x in cp for x in ["Distribution", "Markdown", "Supply"])
                    def get_bg(phase_markers):
                        if isinstance(phase_markers, str):
                            phase_markers = [phase_markers]
                        if any(m in cp for m in phase_markers):
                            return "background:#38bdf8; color:#0f172a; font-weight:bold; border:2px solid #fff; transform:scale(1.05);"
                        return "background:rgba(255,255,255,0.05); color:#64748b;"
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

        with st.expander("📝 הסבר פשוט למתחילים (בשפה מדוברת)", expanded=True):
            st.markdown(explain_score_simple(result["df"], result["current_phase"], result["current_cis"], result["allowed"]))

        render_explain_score(result["df"], result["current_phase"], result["current_cis"], expanded=False)


def screen_institutional_map() -> None:
    st.markdown("### 🗺️ Institutional Map - מפת כסף חכם סקטוריאלית")
    st.markdown("מסך זה ממפה את הסקטורים המרכזיים בשוק ומציג את ממוצע ה-**Institutional Accumulation Probability** (הסתברות לצבירה מוסדית) שלהם. הנתונים מתעדכנים על בסיס מניות מובילות בכל סקטור ומוצגים מהגבוה לנמוך.")

    MAP_SECTORS = {
        "טכנולוגיה (Technology)": {
            "tickers": ["AAPL", "MSFT", "NVDA", "AVGO", "CRM", "ADBE", "CSCO", "ACN",
                        "INTU", "IBM", "TXN", "QCOM", "AMD", "DELL", "HPQ"],
            "desc": "סקטור עתיר צמיחה, משמש לעיתים קרובות כמוביל מומנטום שוק ומאופיין בכניסת הון מוסדי טרנדי."
        },
        "סמיקונדקטורס (Semiconductors)": {
            "tickers": ["AMD", "TXN", "QCOM", "INTC", "SMCI", "AVGO", "AMAT", "LRCX",
                        "KLAC", "ONTO", "MRVL", "ADI"],
            "desc": "תעשיית השבבים - מתפקדת כברומטר מוביל לתיאבון הסיכון של המוסדיים לשוק כולו."
        },
        "פיננסים (Financials)": {
            "tickers": ["JPM", "V", "MA", "BAC", "GS", "BRK-B", "WMT",
                        "COST", "MCD", "HD"],
            "desc": "מוטה ריבית ומחזור כלכלי. איסוף כאן מעיד לרוב על ציפייה מוסדית להתרחבות כלכלית."
        },
        "בריאות (Healthcare)": {
            "tickers": ["JNJ", "UNH", "LLY", "MRK", "ABBV", "ABT", "AMGN", "TMO", "DHR"],
            "desc": "סקטור דפנסיבי המשולב בצמיחה. משמש מקלט בטוח בעת אי-ודאות מוסדית לחלוקת סיכונים."
        },
        "אנרגיה וסחורות (Energy & Commodities)": {
            "tickers": ["XOM", "CVX", "GLD", "SLV", "COP", "SLB", "EOG", "OXY", "PSX",
                        "VLO", "FCX", "NEM", "GOLD", "AEM", "WPM", "PAAS", "AG"],
            "desc": "גידור אינפלציוני ונכסים קשים. כסף חכם זורם לכאן להגנה או ספקולציות מאקרו."
        }
    }
    for _sec, _d in MAP_SECTORS.items():
        _d["tickers"] = list(dict.fromkeys([t for t in _d["tickers"] if t and isinstance(t, str)]))

    if st.button("🗺️ טען מפה מוסדית מחושבת", type="primary"):
        with st.spinner("סורק מניות בכל סקטור לחילוץ נתוני איסוף (Smart Money Flow) - יכול לקחת כדקה עם רשימות מורחבות..."):
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

            st.session_state["map_sector_results"] = sector_results

    sector_results = st.session_state.get("map_sector_results")
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

    st.markdown("---")
    st.markdown("### 🔍 סריקת מניות מעניינות בתוך סקטור")
    st.caption("לכל סקטור ניתן להריץ סריקה מלאה (15-20 מניות) ולקבל רק שילובים איכותיים של Wyckoff + פונדמנטלי. לחיצה על 'ניתוח עומק' פותחת ניתוח מלא במסך הבית.")

    for sector, data in MAP_SECTORS.items():
        with st.expander(f"{sector} ({len(data['tickers'])} מניות)", expanded=False):
            st.caption(data["desc"])
            scan_key = f"sector_picks::{sector}"
            if st.button(f"🔍 סרוק מניות מעניינות ב{sector}", key=f"sector_scan_btn::{sector}", use_container_width=True):
                if not SCOUT_CORE_AVAILABLE:
                    st.error("מודול הליבה חסר.")
                else:
                    with st.spinner(f"סורק {len(data['tickers'])} מניות ב{sector}..."):
                        st.session_state[scan_key] = scan_top_opportunities(data["tickers"], top_n=6, mode="Balanced")

            results = st.session_state.get(scan_key)
            if results is None:
                st.caption("לחץ על הכפתור לעיל כדי לסרוק את הסקטור.")
            elif not results:
                st.info("לא נמצאו כרגע שילובים איכותיים בסקטור זה.")
            else:
                for r in results:
                    rcol1, rcol2 = st.columns([3, 1])
                    with rcol1:
                        st.markdown(
                            f"**{r['ticker']}** &nbsp; {render_price_inline(r['ticker'])}<br>"
                            f"<span style='color:{r['color']}'>{r['headline']}</span> · "
                            f"תמחור: <b style='color:{r['valuation_color']}'>{r['valuation']}</b> · CIS {r['cis']:.0f} · ציון {r['composite']:.0f}",
                            unsafe_allow_html=True,
                        )
                    with rcol2:
                        if st.button("📊 ניתוח עומק", key=f"sector_deep::{sector}::{r['ticker']}", use_container_width=True):
                            go_to_screen("🏠 בית", r["ticker"])


def screen_fundamental() -> None:
    st.markdown("### 📊 Fundamental Analysis - ניתוח ערך וחברה")
    st.markdown("מסך זה מנתח את הבריאות הפיננסית של החברה והתמחור שלה ביחס לסקטור, ומשלב זאת עם נתוני הכסף החכם.")
    
    handoff_fund = st.session_state.get("handoff_ticker")
    is_new_fund_handoff = bool(handoff_fund) and st.session_state.get("_fund_consumed_handoff") != handoff_fund
    if is_new_fund_handoff and "fund_tkr" in st.session_state:
        del st.session_state["fund_tkr"]

    default_fund = handoff_fund or "MSFT"
    tkr = st.text_input("הזן סימול לניתוח פונדמנטלי מקיף:", value=default_fund, key="fund_tkr").strip().upper()

    run_fund = st.button("📈 נתח פונדמנטלית", type="primary", use_container_width=True)
    auto_fund = is_new_fund_handoff
    if auto_fund:
        st.session_state._fund_consumed_handoff = handoff_fund

    # תיקון קריטי: שמירת הטיקר המנותח ב-session_state כדי שבלוק התוצאות (והכפתור
    # "קבל אסטרטגיית מסחר" שבתוכו) לא יתאפס כשלוחצים על כפתור כלשהו בתוכו.
    if run_fund or auto_fund:
        st.session_state.fund_result_ticker = tkr

    show_fund_ticker = st.session_state.get("fund_result_ticker")
    if show_fund_ticker:
        tkr = show_fund_ticker
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
            cis_score = 0.0
            current_phase = ""
            if df is not None and not df.empty:
                engine = FactorEngine(BacktestConfig())
                factors = engine.compute(df)
                cis_score = float(engine.composite_cis(factors, df).iloc[-1])
                current_phase = str(engine.get_wyckoff_phase(df).iloc[-1])

        # --- כותרת מחיר אחידה ליד הטיקר ---
        render_price_header(tkr)

        # --- סינתזה קשיחה אחת (נקודת אמת יחידה, ללא סתירות) ---
        verdict_obj = synthesize_verdict(fdata, cis_score, current_phase, tkr)
        v_color_val = fdata.get("valuation_color", "#94a3b8")
        valuation = fdata.get("valuation", "-")

        # === השורה התחתונה האחידה (אותו רכיב בכל המסכים) ===
        st.markdown("<div class='section-label'>השורה התחתונה — הכרעה מאוחדת</div>", unsafe_allow_html=True)
        render_verdict_banner(
            verdict_obj, ticker=tkr, cis_score=cis_score, current_phase=(current_phase or "—"),
            valuation=valuation, valuation_color=v_color_val,
        )

        # === למה היא זולה/יקרה, וביחס למה (נימוק מפורש) ===
        st.markdown(
            f"<div class='reason-box'>💡 <b>למה {tkr} מתומחרת כ'{valuation}'?</b> {fdata.get('valuation_reason', '-')}</div>",
            unsafe_allow_html=True
        )
        with st.popover("ℹ️ ביחס למה משווים תמחור?"):
            st.write(
                f"התמחור נמדד תמיד ביחס לסקטור הספציפי ({fdata.get('sector_he', fdata.get('sector','-'))}), "
                "ולא ביחס לשוק הכללי. לכל סקטור 'נורמות' מכפיל שונות — חברת טכנולוגיה צומחת תיסחר "
                "במכפילים גבוהים יותר מבנק או חברת אנרגיה, ולכן ההשוואה תמיד יחסית-ענפית ולא מוחלטת."
            )
            st.caption("דוגמה: טכנולוגיה — 'זול' מתחת ל-22, 'יקר' מעל 35. פיננסים/אנרגיה — 'זול' מתחת ל-12, 'יקר' מעל 18.")

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
                "<div class='fund-meta-box'>",
                "<div class='fund-meta-label'>💵 תשואת תזרים (FCF Yield)</div>",
                f"<div class='fund-meta-value'>{fdata.get('fcf_yield', 'N/A')}</div>",
                "</div>",
                "</div>",
            ]),
            unsafe_allow_html=True
        )

        # === נרטיב חופשי על מצב המניה הספציפי (ניתוח ערך) ===
        narrative = build_fundamental_narrative(fdata, tkr, verdict_obj)
        st.markdown(
            f"<div class='narrative-box'><span class='narrative-title'>🦅 ניתוח חופשי - מצב המניה הספציפי (ניתוח ערך)</span>{narrative}</div>",
            unsafe_allow_html=True,
        )

        # === טבלת מכפילים - מסודרת לפי סדר חשיבות ניתוח ערך (Deep Dive - בתוך expander) ===
        ex = fdata.get("explanations", {})
        with st.expander("📐 מכפילים ויחסים מלאים (Deep Dive - מחושבים עצמית, בסדר חשיבות ניתוח ערך)", expanded=True):
            metrics = [
                # (1) מכפיל רווח - הראשון שבודקים בניתוח ערך
                ("Forward P/E (מכפיל רווח עתידי)", fdata.get("pe_forward", "-"), ex.get("pe_forward", "")),
                ("Trailing P/E (מכפיל רווח נוכחי)", fdata.get("pe_trailing", "-"), ex.get("pe_trailing", "")),
                # (2) תזרים מזומנים
                ("FCF Yield (תשואת תזרים חופשי)", fdata.get("fcf_yield", "-"), ex.get("fcf_yield", "")),
                # (3) צמיחה
                ("צמיחת הכנסות (YoY)", fdata.get("rev_growth", "-"), ex.get("rev_growth", "")),
                ("EPS Growth (צמיחת רווח)", fdata.get("eps_growth", "-"), ex.get("eps_growth", "")),
                ("PEG Ratio", fdata.get("peg", "-"), ex.get("peg", "")),
                # (4) איכות
                ("שולי תפעול (Op. Margin)", fdata.get("op_margin", "-"), ex.get("op_margin", "")),
                ("ROE (תשואה להון)", fdata.get("roe", "-"), ex.get("roe", "")),
                # (5) תמחור משלים
                ("EV/EBITDA", fdata.get("ev_ebitda", "-"), ex.get("ev_ebitda", "")),
                ("P/S (מכירות)", fdata.get("ps", "-"), ex.get("ps", "")),
                ("P/B (הון)", fdata.get("pb", "-"), ex.get("pb", "")),
                # (6) מינוף/בטחון
                ("חוב נטו / EBITDA (מינוף)", fdata.get("net_debt_ebitda", "-"), ex.get("net_debt_ebitda", "")),
            ]

            header_l, header_r1, header_r2 = st.columns([2.2, 1.6, 1])
            with header_l:
                st.markdown("**מדד**")
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
                        st.write(desc if desc else "אין הסבר זמין למדד זה.")

        # === מעבר לאסטרטגיית מסחר עם הטיקר הנוכחי ===
        cta1, cta2 = st.columns([1, 2])
        with cta1:
            if st.button("🎯 קבל אסטרטגיית מסחר", type="primary", use_container_width=True, key="fund_to_strategy"):
                go_to_screen("📈 Trading Scout", tkr)
        with cta2:
            st.caption("מעבר למסך המסחר עם תוכנית מוכנה: כניסה מדורגת, סטופ מדורג, יעדי שחרור חלקי וגודל פוזיציה - לפי סיכום וואיקוף + פונדמנטלי.")

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

    # בחירת רמת פירוט לתוכנית המסחר
    plan_level = st.radio(
        "רמת פירוט בתוכנית המסחר:",
        ["בסיסי (כניסה + סטופ + 2 יעדים)", "מלא (כניסה מדורגת + יעדי שחרור חלקי + גידור)", "מלא + גודל פוזיציה מומלץ"],
        index=1, horizontal=True, key="plan_level_radio"
    )
    plan_level_key = {"בסיסי (כניסה + סטופ + 2 יעדים)": "basic",
                      "מלא (כניסה מדורגת + יעדי שחרור חלקי + גידור)": "full",
                      "מלא + גודל פוזיציה מומלץ": "sizing"}[plan_level]

    # אם הגענו ממסך אחר עם טיקר - נמלא אותו בטיקר הראשון
    handoff = st.session_state.get("handoff_ticker")
    is_new_scout_handoff = bool(handoff) and st.session_state.get("_scout_consumed_handoff") != handoff
    if is_new_scout_handoff and "ts_ticker_0" in st.session_state:
        # תיקון קריטי: בלי זה ה-widget הראשון משאיר את הטיקר הישן (כבר הוקצה ל-key הזה),
        # ה-value החדש מתעלם ממנו, ונראה כאילו "לא קרה כלום" בלחיצה על קבל אסטרטגיית מסחר.
        del st.session_state["ts_ticker_0"]

    default_tickers = ["NVDA", "AAPL", "META", "TSLA"]
    if handoff:
        default_tickers = [handoff, "", "", ""]

    cols_input = st.columns(4)
    tickers_input = []
    for i in range(4):
        val = cols_input[i].text_input(f"טיקר {i+1}", value=default_tickers[i], key=f"ts_ticker_{i}").strip().upper()
        tickers_input.append(val)

    run_scout = st.button("💡 הפעל רדאר חכם - קבל הסתברויות ותוכניות", type="primary", use_container_width=True)
    auto_scout = is_new_scout_handoff
    if auto_scout:
        st.session_state._scout_consumed_handoff = handoff

    # תיקון קריטי: שמירת רשימת הטיקרים המנותחים ב-session_state כדי שבלוק התוצאות
    # (והכפתור "פירוט פונדמנטלי מלא" שבתוכו) לא יתאפס כשלוחצים על כפתור כלשהו בתוכו.
    if run_scout or auto_scout:
        st.session_state.scout_result_tickers = list(tickers_input)

    show_scout_tickers = st.session_state.get("scout_result_tickers")
    if show_scout_tickers:
        if not SCOUT_CORE_AVAILABLE:
            st.error("מודול הליבה חסר, לא ניתן לייצר המלצה.")
            return

        from trading_scout import get_trading_recommendation

        # UI rendering in sequential order (Stacked Vertically to avoid cutoffs)
        for tkr in show_scout_tickers:
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

                render_price_header(tkr)

                # === שלב 1: השורה התחתונה האחידה (Verdict Banner) - ראשון ובולט ===
                _verdict = rec_data.get("verdict")
                _fund = rec_data.get("fundamental", {}) or {}
                if _verdict:
                    render_verdict_banner(
                        _verdict, ticker=tkr,
                        cis_score=rec_data.get('prob_engine', {}).get('accumulation_chance'),
                        current_phase=rec_data.get('current_phase', ''),
                        valuation=_fund.get('valuation'),
                        valuation_color=_fund.get('valuation_color', '#94a3b8'),
                        extra_chips=[f"המלצה <b>{rec_data.get('recommendation','-')}</b>"],
                    )

                # === שלב 2: הסבר קצר ואנושי - למה דווקא המניה הזו, עכשיו ===
                if _fund:
                    why_narrative = build_fundamental_narrative(_fund, tkr, _verdict, current_phase=rec_data.get('current_phase', ''))
                    st.markdown(
                        f"<div class='narrative-box'><span class='narrative-title'>🦅 למה דווקא {tkr}, עכשיו?</span>{why_narrative}</div>",
                        unsafe_allow_html=True,
                    )

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
                    "<div class='scout-section-title'>🏢 תמחור פונדמנטלי</div>",
                    f"<div class='scout-list-item'><span>הערכת תמחור כוללת:</span> <span style='font-weight:800; font-size:1.3rem; color:{rec_data.get('fundamental', {}).get('valuation_color', '#fff')}'>{rec_data.get('fundamental', {}).get('valuation', '-')}</span></div>",
                    f"<div class='scout-list-item'><span>דוח רווחים קרוב:</span> <span>{rec_data.get('fundamental', {}).get('next_earnings', 'N/A')}</span></div>",
                    "</div>",
                    
                    "</div>", # Close scout-stats-grid
                    
                    f"<div class='scout-alert-box' style='border-color: {alert_border}; background: {alert_bg};'>",
                    "<span class='scout-alert-title'>🛡️ מערכת הגנה ממלכודות (Failure Detection):</span>",
                    failure_html,
                    "</div>",
                    "</div>",
                    "</div>",
                ]

                # === שלב 3: Drill-down אחד מאוחד - ניתוח טכני + אסטרטגיית מסחר, עם whitespace ברור בין החלקים ===
                with st.expander(f"🔍 Drill-down מלא ל-{tkr}: Wyckoff, Smart Money ואסטרטגיית מסחר", expanded=True):
                    st.markdown("".join(card_parts), unsafe_allow_html=True)

                    st.markdown("<div style='height:34px;'></div>", unsafe_allow_html=True)
                    st.markdown("<hr style='border-color: rgba(148,163,184,0.18); margin-bottom:28px;'>", unsafe_allow_html=True)

                    st.markdown("#### 🗺️ תרחישי מפת הדרכים (What-if Analysis)")
                    st.markdown(f"**✅ אם התבנית מצליחה:** {roadmap_success}")
                    st.markdown(f"**❌ אם התבנית נכשלת:** {roadmap_fail}")

                    st.markdown("---")
                    st.markdown("#### 🎯 תוכנית מסחר (Trading Plan)")
                    st.markdown(f"**פעולה מומלצת:** {rec_data['action']}")

                    tp = rec_data.get("trade_plan", {})
                    if rec in ("SELL", "STRONG SELL"):
                        st.warning("🚫 לא קיימת תוכנית כניסה ללונג במצב זה. ההסתברות לצבירה מוסדית נמוכה / הנכס בפאזת הפצה.")
                    elif not tp:
                        st.info("אין תוכנית מסחר זמינה.")
                    elif plan_level_key == "basic":
                        b = tp.get("basic", {})
                        st.markdown(
                            f"""<div class='plan-stage'><span class='plan-stage-label'>📍 כניסה</span><span class='plan-stage-val' style='color:#38bdf8'>${b.get('entry','-')}</span></div>
                            <div class='plan-stage'><span class='plan-stage-label'>🛑 סטופ הגנה</span><span class='plan-stage-val' style='color:#f87171'>${b.get('stop','-')} ({b.get('stop_pct','-')}%)</span></div>
                            <div class='plan-stage'><span class='plan-stage-label'>🎯 יעד 1</span><span class='plan-stage-val' style='color:#34d399'>${b.get('tp1','-')} (+{b.get('tp1_pct','-')}%)</span></div>
                            <div class='plan-stage'><span class='plan-stage-label'>🎯 יעד 2</span><span class='plan-stage-val' style='color:#34d399'>${b.get('tp2','-')} (+{b.get('tp2_pct','-')}%)</span></div>
                            <div class='plan-stage'><span class='plan-stage-label'>⚖️ יחס סיכוי/סיכון</span><span class='plan-stage-val'>{b.get('rr','-')}</span></div>""",
                            unsafe_allow_html=True
                        )
                    else:
                        f = tp.get("full", {})
                        st.markdown(
                            f"""<div class='plan-stage'><span class='plan-stage-label'>📍 כניסה (חצי עכשיו)</span><span class='plan-stage-val' style='color:#38bdf8'>${f.get('entry_now','-')}</span>
                            <span class='plan-stage-note'>חצי שני בפולבק קל לאזור ${f.get('entry_pullback','-')} - כניסה מדורגת מקטינה סיכון תזמון.</span></div>
                            <div class='plan-stage'><span class='plan-stage-label'>🛑 סטופ ראשוני</span><span class='plan-stage-val' style='color:#f87171'>${f.get('stop_initial','-')}</span>
                            <span class='plan-stage-note'>אחרי יעד 1 - העלה את הסטופ לנקודת הכניסה (${f.get('stop_after_tp1','-')}) = עסקה ללא סיכון.</span></div>
                            <div class='plan-stage'><span class='plan-stage-label'>🎯 יעד 1 (+{f.get('tp1_pct','-')}%)</span><span class='plan-stage-val' style='color:#34d399'>${f.get('tp1','-')}</span>
                            <span class='plan-stage-note'>{f.get('tp1_action','')}</span></div>
                            <div class='plan-stage'><span class='plan-stage-label'>🎯 יעד 2 (+{f.get('tp2_pct','-')}%)</span><span class='plan-stage-val' style='color:#34d399'>${f.get('tp2','-')}</span>
                            <span class='plan-stage-note'>{f.get('tp2_action','')}</span></div>
                            <div class='plan-stage'><span class='plan-stage-label'>🎯 יעד 3 (+{f.get('tp3_pct','-')}%)</span><span class='plan-stage-val' style='color:#34d399'>${f.get('tp3','-')}</span>
                            <span class='plan-stage-note'>{f.get('tp3_action','')}</span></div>
                            <div class='plan-stage' style='border-color:rgba(239,68,68,0.3);'><span class='plan-stage-label'>⛔ נקודת הפרת תזה</span><span class='plan-stage-val' style='color:#f87171'>${f.get('invalidation','-')}</span>
                            <span class='plan-stage-note'>{f.get('invalidation_note','')}</span></div>
                            <div class='plan-stage'><span class='plan-stage-label'>⚖️ יחס סיכוי/סיכון</span><span class='plan-stage-val'>{f.get('rr','-')}</span>
                            <span class='plan-stage-note'>טווח זמן אופטימלי: {f.get('timeframe','-')}</span></div>""",
                            unsafe_allow_html=True
                        )
                        if plan_level_key == "sizing":
                            s = tp.get("sizing", {})
                            st.markdown(
                                f"""<div class='plan-stage' style='border-color:rgba(56,189,248,0.35);'>
                                <span class='plan-stage-label'>💼 גודל פוזיציה מומלץ</span>
                                <span class='plan-stage-val' style='color:#38bdf8'>{s.get('position_pct','-')}% מהתיק</span>
                                <span class='plan-stage-note'>{s.get('risk_note','')} (הפסד מקסימלי בסטופ: ~{s.get('max_loss_at_stop_pct','-')}% על הפוזיציה)</span></div>""",
                                unsafe_allow_html=True
                            )

                    st.markdown("---")
                    st.markdown("#### ⏮️ היסטוריית תבניות (Replay Engine)")
                    st.markdown(f"תרחישים מוסדיים אנלוגיים מהעבר המצליבים את נתוני הכסף החכם הנוכחיים של **{tkr}**:")
                    for rep in rec_data['replay']:
                        st.markdown(f"- {rep}")

                st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)
                if st.button(f"📊 פירוט פונדמנטלי מלא ל-{tkr}", key=f"scout_to_fund_{tkr}", use_container_width=True):
                    go_to_screen("📊 ניתוח פונדמנטלי", tkr)

def screen_backtest() -> None:
    if not _require_technician_password("Backtest Engine"):
        return
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

        render_price_header(ticker)
            
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
    if not _require_technician_password("Institutional Performance Monitor"):
        return
    st.markdown("### 👁️ Institutional Performance Monitor")
    
    st.markdown("#### ניתוח עומק לנכס (Performance Analytics)")
    col_t, col_p, col_b = st.columns([2, 1, 1])
    test_ticker = col_t.text_input("הזן סימול (Ticker) לחילוץ מטריקות ודרואו-דאון:", value="NVDA", key="monitor_ticker").strip().upper()
    
    monitor_period = col_p.selectbox("בחר תקופת היסטוריה לאנליזה:", ["2y", "5y", "10y", "max"], index=2)
    
    if col_b.button("📈 חלץ מטריקות מתקדמות", use_container_width=True):
        with st.spinner(f"מחשב מדדים היסטוריים ל-{test_ticker}..."):
            from scout_core import run_wyckoff_anchored_backtest, calculate_advanced_metrics, calculate_phase_followthrough
            df, audit_df = run_wyckoff_anchored_backtest(test_ticker, use_ai=st.session_state.use_ml, threshold=65, period=monitor_period)
            render_price_header(test_ticker)
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
    if not _require_technician_password("Wyckoff Pattern AI Trainer"):
        return
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

def render_top_nav() -> None:
    """סרגל ניווט עליון קבוע עם המבורגר בפינה הימנית — מלווה בכל מסך, כולל כפתורי חזור/למעלה."""
    st.markdown("<div id='page-top'></div>", unsafe_allow_html=True)

    PAGES = [
        "🏠 בית", "🗺️ מפה מוסדית", "📊 ניתוח פונדמנטלי",
        "📈 Trading Scout", "📊 Backtest", "👁️ Monitor", "🧠 ML Trainer",
    ]
    # שורה עליונה: כותרת בצד אחד, המבורגר (selectbox) בפינה הימנית
    title_col, menu_col = st.columns([4, 1.4])
    with title_col:
        st.markdown(
            '<div class="main-header" style="margin-bottom:0;"><h1>📈 Wyckoff Institutional Analyst</h1>'
            '<p>זיהוי איסוף, הפצה וכניסת כסף חכם | Cloud Run Edition</p></div>',
            unsafe_allow_html=True
        )
    with menu_col:
        st.markdown("<div class='topnav-spacer'></div>", unsafe_allow_html=True)
        current = st.session_state.get("current_page", PAGES[0])
        idx = PAGES.index(current) if current in PAGES else 0
        chosen = st.selectbox(
            "☰ תפריט",
            PAGES,
            index=idx,
            key="nav_select",
            help="מעבר מהיר בין מסכי המערכת",
        )
        if chosen != st.session_state.get("current_page"):
            prev_page = st.session_state.get("current_page")
            if prev_page:
                st.session_state.setdefault("nav_history", [])
                st.session_state.nav_history.append(prev_page)
            st.session_state.current_page = chosen
            st.session_state.handoff_ticker = None  # ניווט ידני - בלי טיקר תקוע
            st.rerun()

    # --- כפתורים מלווים: חזור למסך הקודם + חזרה לראש העמוד ---
    has_history = bool(st.session_state.get("nav_history"))
    back_col, top_col, _spacer = st.columns([1.3, 1.3, 3.4])
    with back_col:
        if st.button("⬅️ חזור למסך הקודם", key="nav_back_btn", use_container_width=True, disabled=not has_history):
            go_back()
    with top_col:
        st.markdown(
            "<a href='#page-top' style=\"display:block; text-align:center; text-decoration:none; "
            "background:var(--bg-2); border:1px solid var(--line-strong); border-radius:12px; "
            "padding:0.5rem 0; color:var(--txt-1); font-weight:600; font-size:0.95rem;\">⬆️ חזרה לראש העמוד</a>",
            unsafe_allow_html=True,
        )

    st.markdown("<hr style='border-color:rgba(255,255,255,0.08); margin:14px 0 18px 0;'>", unsafe_allow_html=True)


def main() -> None:
    init_session_state()
    inject_css()

    render_top_nav()

    page = st.session_state.get("current_page", "🏠 בית")
    router = {
        "🏠 בית": screen_home,
        "🗺️ מפה מוסדית": screen_institutional_map,
        "📊 ניתוח פונדמנטלי": screen_fundamental,
        "📈 Trading Scout": screen_trading_scout,
        "📊 Backtest": screen_backtest,
        "👁️ Monitor": screen_monitor,
        "🧠 ML Trainer": screen_ml_trainer,
    }
    screen_fn = router.get(page, screen_home)
    screen_fn()


if __name__ == "__main__":
    main()
