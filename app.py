"""
============================================================
INSTITUTIONAL SCOUT PRO V20.0 (Premium Institutional Visual Overhaul)
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
        synthesize_verdict, build_fundamental_narrative, build_fundamental_bullets, scan_top_opportunities, render_verdict_banner_html
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
        def build_fundamental_narrative(fd, t, v=None, current_phase=""): return "מודול ניתוח חסר."
        def build_fundamental_bullets(fd, t, current_phase=""): return ["מודול ניתוח חסר."]
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

        def build_fundamental_narrative(fd, t, v=None, current_phase=""):
            return "מודול ניתוח חסר."

        def build_fundamental_bullets(fd, t, current_phase=""):
            return ["מודול ניתוח חסר."]

        def scan_top_opportunities(tickers, top_n=5, mode="Balanced"):
            return []

        def render_verdict_banner_html(v, ticker="", cis_score=None, current_phase="", valuation=None, valuation_color="#94a3b8", extra_chips=None):
            return ""


# --- MarketScanner (מנוע סריקת שוק נפרד עם Early Pruning) ---
try:
    import scout_core as _sc_module
    from market_scanner import MarketScanner
    MARKET_SCANNER_AVAILABLE = SCOUT_CORE_AVAILABLE
except Exception as _ms_exc:
    MARKET_SCANNER_AVAILABLE = False
    MarketScanner = None
    logger.warning("market_scanner not available: %s", _ms_exc)


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
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Hebrew:wght@300;400;500;600;700;800&family=Inter:wght@400;500;600;700;800;900&display=swap');

    /* ============================================================
       INSTITUTIONAL MINIMALIST PREMIUM DESIGN SYSTEM (V20.0)
       Palette: deep graduated navy canvas, single precise cyan accent,
       layered depth shadows, light glassmorphism on raised surfaces.
       ============================================================ */
    :root {
        --bg-0: #080c16;          /* canvas - deeper */
        --bg-1: #0d1424;          /* surface */
        --bg-2: #121b2e;          /* raised surface */
        --bg-3: #19233a;          /* hover / active */
        --glass: rgba(18,27,46,0.62);          /* glassmorphism surface fill */
        --glass-border: rgba(255,255,255,0.06); /* hairline highlight on glass edges */
        --line: rgba(148,163,184,0.10);
        --line-strong: rgba(148,163,184,0.22);
        --txt-1: #e8eef7;         /* primary text */
        --txt-2: #9fb0c8;         /* secondary */
        --txt-3: #64748b;         /* muted */
        --accent: #38bdf8;        /* single brand accent - used sparingly, precisely */
        --accent-soft: rgba(56,189,248,0.35);
        --pos: #22c55e;
        --pos-soft: #4ade80;
        --neg: #ef4444;
        --warn: #eab308;
        --warn-soft: #facc15;
        --radius: 20px;
        --radius-lg: 24px;
        /* מערכת צללים מדורגת: עומק עדין + הדגשה פנימית עליונה דקה */
        --shadow: 0 10px 38px rgba(0,0,0,0.28), inset 0 1px 0 rgba(255,255,255,0.04);
        --shadow-hover: 0 20px 54px rgba(0,0,0,0.4), 0 0 0 1px var(--accent-soft), inset 0 1px 0 rgba(255,255,255,0.06);
    }

    html, body, [class*="css"] {
        font-family: 'IBM Plex Sans Hebrew', 'Inter', sans-serif;
        direction: rtl; text-align: right;
        background: var(--bg-0); color: var(--txt-1);
        letter-spacing: 0.1px;
    }
    /* היררכיית טיפוגרפיה: כותרות כבדות וגדולות, line-height נדיב לטקסט רץ */
    h1 { font-weight: 800 !important; letter-spacing: -0.4px !important; }
    h2 { font-weight: 700 !important; letter-spacing: -0.3px !important; }
    h3, h4 { font-weight: 700 !important; letter-spacing: -0.2px !important; }
    p, .stMarkdown p { line-height: 1.75; }
    /* טקסט משני קטן ומדויק */
    .stCaption, [data-testid="stCaptionContainer"] { font-size: 0.93rem !important; color: var(--txt-3) !important; line-height: 1.65 !important; }

    /* Focus states ברורים - נגישות + פוליש */
    button:focus-visible, a:focus-visible, input:focus-visible, textarea:focus-visible,
    [data-baseweb="select"]:focus-within {
        outline: 2px solid var(--accent) !important;
        outline-offset: 2px !important;
    }

    /* Scrollbar מותאם אישית גלובלי (WebKit + Firefox) */
    ::-webkit-scrollbar { width: 10px; height: 10px; }
    ::-webkit-scrollbar-track { background: var(--bg-0); }
    ::-webkit-scrollbar-thumb { background: var(--line-strong); border-radius: 10px; }
    ::-webkit-scrollbar-thumb:hover { background: var(--accent); }
    * { scrollbar-width: thin; scrollbar-color: var(--line-strong) var(--bg-0); }

    /* Micro-animation: fade-in עדין לבלוקים מרכזיים בטעינה */
    @keyframes premiumFadeIn {
        from { opacity: 0; transform: translateY(8px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    /* רקע מקצועי עדין: navy עמוק + רשת דקה (כמו נייר גרפים/דאטה) + זוהר accent רך.
       מאוד עדין כדי לשמור על "Institutional Minimalist" - לא צעקני. */
    .stApp {
        background-color: var(--bg-0);
        background-image:
            radial-gradient(900px circle at 12% -8%, rgba(56,189,248,0.07), transparent 45%),
            radial-gradient(800px circle at 100% 0%, rgba(125,108,255,0.05), transparent 40%),
            linear-gradient(rgba(56,189,248,0.030) 1px, transparent 1px),
            linear-gradient(90deg, rgba(56,189,248,0.030) 1px, transparent 1px);
        background-size: 100% 100%, 100% 100%, 44px 44px, 44px 44px;
        background-attachment: fixed;
    }
    .block-container { padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1180px; }

    /* רווח נדיב יותר בין sections */
    .element-container { margin-bottom: 4px; }

    hr { border-color: var(--line) !important; }

    /* ============================================================
       STICKY COLLAPSING NAV (Q1) - מלווה בגלילה, מתכווץ לפס דק
       בגלילה למטה ונפתח שוב בתנועה קלה למעלה
       ============================================================ */
    #sticky-nav-anchor {
        position: sticky; top: 0; z-index: 999;
        background: var(--bg-0);
        transition: all 0.28s ease;
    }
    /* כשמסומן collapsed (גלילה למטה) - הכותרת מתכווצת לפס דק */
    body.nav-collapsed .main-header {
        padding: 0.35rem 1.2rem !important;
        transition: all 0.28s ease;
    }
    body.nav-collapsed .main-header h1 { font-size: 1.0rem !important; transition: all 0.28s ease; }
    body.nav-collapsed .main-header p { display: none !important; }
    .main-header { transition: all 0.28s ease; }
    .main-header h1 { transition: all 0.28s ease; }

    /* ============================================================
       FLOATING BACK BUTTON (Q3) - כפתור חזור צף בפינה התחתונה
       ============================================================ */
    .float-back-wrap {
        position: fixed; bottom: 22px; left: 22px; z-index: 1000;
    }
    .float-back-wrap a {
        display: inline-flex; align-items: center; gap: 6px;
        background: linear-gradient(135deg, #0ea5e9, #38bdf8);
        color: #04121f; font-weight: 700; font-size: 0.9rem;
        padding: 11px 18px; border-radius: 30px; text-decoration: none;
        box-shadow: 0 6px 22px rgba(56,189,248,0.4);
        transition: transform 0.18s ease, filter 0.18s ease;
    }
    .float-back-wrap a:hover { transform: translateY(-2px); filter: brightness(1.08); }

    /* ---------- Header (Premium) ---------- */
    .main-header {
        padding: 1.8rem 2.2rem; border-radius: var(--radius-lg);
        background:
            radial-gradient(130% 150% at 100% 0%, rgba(56,189,248,0.09), transparent 55%),
            linear-gradient(135deg, rgba(10,16,28,0.94), rgba(15,22,40,0.97));
        backdrop-filter: blur(6px);
        box-shadow: var(--shadow); margin-bottom: 0;
        border: 1px solid var(--glass-border);
        animation: premiumFadeIn 0.4s ease;
    }
    .main-header h1 { margin: 0; font-size: 2.15rem; color: var(--txt-1); font-weight: 800; letter-spacing: -0.5px; }
    .main-header p { color: var(--txt-2); font-size: 0.98rem; margin-top: 8px; font-weight: 400; line-height: 1.7; }

    /* ---------- Metrics ---------- */
    [data-testid="stMetric"] {
        background: var(--bg-1) !important;
        border: 1px solid var(--glass-border) !important;
        border-radius: var(--radius); padding: 1.3rem 1.4rem;
        box-shadow: var(--shadow);
    }
    [data-testid="stMetricValue"] { color: var(--accent) !important; font-weight: 800 !important; }
    [data-testid="stMetricLabel"] { color: var(--txt-2) !important; font-weight: 500 !important; }
    [data-testid="stMetricDelta"] { color: var(--pos-soft) !important; }

    /* ---------- Buttons (Institutional Premium - 3D) ---------- */
    .stButton > button {
        border-radius: 14px !important; font-weight: 600 !important;
        border: 1px solid var(--line-strong) !important;
        background: linear-gradient(180deg, var(--bg-3), var(--bg-2)) !important; color: var(--txt-1) !important;
        box-shadow: 0 4px 14px rgba(0,0,0,0.38), inset 0 1px 0 rgba(255,255,255,0.06) !important;
        transition: all 0.22s cubic-bezier(.2,.8,.2,1) !important;
        padding: 0.55rem 1.1rem !important;
    }
    .stButton > button:hover {
        border-color: var(--accent) !important;
        transform: translateY(-3px);
        box-shadow: 0 12px 30px rgba(56,189,248,0.3), inset 0 1px 0 rgba(255,255,255,0.09) !important;
    }
    .stButton > button:active { transform: translateY(0); box-shadow: 0 2px 6px rgba(0,0,0,0.4) !important; }
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #0284c7, #0ea5e9 45%, #38bdf8) !important;
        color: #04121f !important; border: none !important; font-weight: 800 !important;
        box-shadow: 0 10px 32px rgba(56,189,248,0.42), inset 0 1px 0 rgba(255,255,255,0.28), 0 0 0 1px rgba(56,189,248,0.28) !important;
    }
    .stButton > button[kind="primary"]:hover {
        filter: brightness(1.1); transform: translateY(-4px) scale(1.01);
        box-shadow: 0 18px 46px rgba(56,189,248,0.58), inset 0 1px 0 rgba(255,255,255,0.32), 0 0 0 1px rgba(56,189,248,0.45) !important;
    }

    /* selectbox / radio / inputs */
    .stTextInput input, .stSelectbox div[data-baseweb="select"] > div {
        background: var(--bg-1) !important; border-color: var(--line-strong) !important;
        border-radius: 12px !important; color: var(--txt-1) !important;
        transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
    }
    .stTextInput input:focus, .stSelectbox div[data-baseweb="select"]:focus-within > div {
        border-color: var(--accent) !important; box-shadow: 0 0 0 3px rgba(56,189,248,0.15) !important;
    }

    /* expander */
    .streamlit-expanderHeader, [data-testid="stExpander"] summary {
        background: var(--bg-1) !important; border-radius: 14px !important;
        border: 1px solid var(--glass-border) !important; font-weight: 600 !important;
        transition: border-color 0.2s ease !important;
    }
    .streamlit-expanderHeader:hover, [data-testid="stExpander"] summary:hover {
        border-color: var(--accent-soft) !important;
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
        padding: 14px 28px; border-radius: var(--radius); margin: 8px 0 26px 0;
        border: 1px solid var(--glass-border);
        box-shadow: var(--shadow);
    }
    .price-header .ph-ticker { font-size: 0.84rem; color: var(--txt-2); font-weight: 600; letter-spacing: 0.5px; }
    .price-header .ph-price  { font-size: 2.1rem; color: var(--txt-1); font-weight: 800; line-height: 1.05; margin-top: 4px; }
    .price-header .ph-time   { font-size: 0.78rem; color: var(--txt-3); margin-top: 6px; }
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
        border: 1px solid var(--glass-border);
        border-radius: var(--radius-lg); overflow: hidden;
        margin: 14px 0 32px 0; box-shadow: var(--shadow);
        backdrop-filter: blur(4px);
        transition: box-shadow 0.3s ease, transform 0.3s cubic-bezier(.2,.8,.2,1);
        animation: premiumFadeIn 0.4s ease;
    }
    .verdict-banner:hover { transform: translateY(-3px); box-shadow: var(--shadow-hover); }
    .verdict-banner .vb-accent {
        width: 6px; flex: 0 0 6px; background: var(--vb-color);
        box-shadow: 0 0 24px color-mix(in srgb, var(--vb-color) 60%, transparent);
    }
    .verdict-banner .vb-body { padding: 30px 32px; flex: 1; }
    .vb-top { display:flex; align-items:center; gap:14px; flex-wrap:wrap; margin-bottom: 8px; }
    .vb-ticker {
        font-family:'Inter',sans-serif; font-weight:800; font-size:1.05rem; color:var(--txt-2);
        background: var(--bg-3); padding: 5px 14px; border-radius: 9px; letter-spacing:0.5px;
    }
    .vb-headline { font-size: 1.6rem; font-weight: 800; line-height: 1.2; }
    .vb-action { font-size: 1.05rem; font-weight: 700; margin: 8px 0 12px 0; line-height: 1.6; }
    .vb-detail { font-size: 0.98rem; color: var(--txt-2); line-height: 1.8; }
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
        border-radius: 14px; padding: 18px 22px; margin: 6px 0 24px 0;
        font-size: 0.97rem; color: var(--txt-1); line-height: 1.8;
    }
    .narrative-box {
        background: linear-gradient(145deg, var(--bg-2), var(--bg-1));
        border: 1px solid var(--line); border-right: 3px solid var(--accent);
        border-radius: var(--radius); padding: 28px 32px; margin: 16px 0 32px 0;
        font-size: 1.0rem; color: var(--txt-1); line-height: 1.85;
        box-shadow: var(--shadow);
    }
    .narrative-title { color: var(--accent); font-weight: 800; font-size: 1.05rem; display:block; margin-bottom: 12px; letter-spacing:0.3px; }

    /* ============================================================
       HOME — Opportunity pick cards
       ============================================================ */
    .pick-card {
        background: linear-gradient(155deg, var(--glass), var(--bg-1));
        backdrop-filter: blur(5px);
        border: 1px solid var(--glass-border); border-radius: var(--radius-lg);
        padding: 30px 32px; margin-bottom: 14px; height: 100%; min-height: 220px;
        box-shadow: var(--shadow);
        transition: transform 0.28s cubic-bezier(.2,.8,.2,1), border-color 0.28s ease, box-shadow 0.28s ease;
        animation: carouselCardIn 0.32s cubic-bezier(.2,.8,.2,1);
    }
    .pick-card:hover {
        transform: translateY(-6px);
        border-color: var(--accent-soft);
        box-shadow: var(--shadow-hover);
    }
    .pick-rank { font-family:'Inter'; font-size: 0.72rem; color: var(--txt-3); font-weight: 800; letter-spacing: 1.5px; }
    .pick-ticker { font-family:'Inter'; font-size: 1.7rem; font-weight: 800; color: var(--txt-1); line-height: 1.05; margin: 2px 0; }
    .pick-headline { font-size: 0.93rem; font-weight: 700; margin: 14px 0 14px 0; line-height:1.6; }
    .pick-meta { font-size: 0.85rem; color: var(--txt-2); line-height: 1.85; margin-bottom: 8px; }
    .pick-score-pill {
        display:inline-block; background: rgba(56,189,248,0.12); color: var(--accent);
        border-radius: 14px; padding: 6px 16px; font-size: 0.8rem; font-weight: 700; margin-top: 16px;
    }

    /* ============================================================
       CAROUSEL OVERLAY ARROWS - חצים אמיתיים (st.button) הממוקמים
       position:absolute על גבי הכרטיס. ממוקדים לפי תוכן (סימני <span>
       ייחודיים) דרך :has() - בלי לנחש שום class פנימי של Streamlit, מה
       שגרם לכישלון בניסיון קודם. כל חץ הוא st.container() אמיתי משלו,
       ילד אמיתי של ה-stage החיצוני (גם הוא st.container() אמיתי) - קינון
       DOM מובטח, לא תג HTML פתוח חוצה-קריאות.
       ============================================================ */
    @keyframes carouselCardIn {
        from { opacity: 0; transform: translateY(6px) scale(0.985); }
        to   { opacity: 1; transform: translateY(0) scale(1); }
    }
    .carousel-pick-card {
        animation: carouselCardIn 0.32s cubic-bezier(.2,.8,.2,1);
        padding-left: 76px !important;
        padding-right: 76px !important;
    }
    /* ה-stage עצמו: position:relative, מאותר לפי תוכן (cs-stage-marker) */
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"] > span.cs-stage-marker) {
        position: relative !important;
    }
    /* container החץ הבא (▶) - מאותר לפי cs-next-marker, ממוקם absolute בימין */
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"] > span.cs-next-marker) {
        position: absolute !important;
        top: 50% !important; transform: translateY(-50%) !important;
        right: 12px !important; z-index: 30 !important;
    }
    /* container החץ הקודם (◀) - מאותר לפי cs-prev-marker, ממוקם absolute בשמאל */
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"] > span.cs-prev-marker) {
        position: absolute !important;
        top: 50% !important; transform: translateY(-50%) !important;
        left: 12px !important; z-index: 30 !important;
    }
    /* עיצוב הכפתורים עצמם - עיגולים תלת-מימדיים גדולים עם hover glow חזק */
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"] > span.cs-next-marker) button,
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"] > span.cs-prev-marker) button {
        width: 64px !important; height: 64px !important; min-height: 64px !important;
        border-radius: 50% !important; padding: 0 !important;
        font-size: 1.6rem !important; font-weight: 800 !important;
        background: linear-gradient(160deg, var(--bg-3), var(--bg-1)) !important;
        border: 1px solid var(--line-strong) !important;
        box-shadow: 0 6px 20px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.07), 0 0 0 1px rgba(56,189,248,0.2) !important;
        transition: transform 0.18s cubic-bezier(.2,.8,.2,1), box-shadow 0.2s ease, border-color 0.2s ease !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"] > span.cs-next-marker) button:hover,
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"] > span.cs-prev-marker) button:hover {
        border-color: var(--accent) !important;
        box-shadow: 0 0 34px rgba(56,189,248,0.7), 0 8px 26px rgba(56,189,248,0.45), inset 0 1px 0 rgba(255,255,255,0.1) !important;
        transform: translateY(-50%) scale(1.1) !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"] > span.cs-next-marker) button:disabled,
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"] > span.cs-prev-marker) button:disabled {
        opacity: 0.25 !important; box-shadow: none !important; transform: translateY(-50%) !important;
    }

    /* ============================================================
       SWIPE CAROUSEL (תוספת) - כרטיסים בשורה אופקית עם scroll-snap. המשתמש
       מחליק ימינה/שמאלה (מגע/trackpad) והכרטיסים נתפסים למקום עם החלקה חלקה.
       ============================================================ */
    .swipe-hint {
        text-align: center; font-size: 0.95rem; font-weight: 700;
        color: var(--accent); margin: 4px 0 12px 0; letter-spacing: 0.3px;
        opacity: 0.9;
    }
    .swipe-track {
        display: flex; flex-direction: row;
        gap: 16px;
        overflow-x: auto; overflow-y: hidden;
        scroll-snap-type: x mandatory;
        scroll-behavior: smooth;
        -webkit-overflow-scrolling: touch;   /* החלקה חלקה ב-iOS */
        padding: 6px 4px 16px 4px;
        scrollbar-width: thin;
        scrollbar-color: var(--line-strong) transparent;
    }
    /* פס גלילה דק ועדין (WebKit) */
    .swipe-track::-webkit-scrollbar { height: 8px; }
    .swipe-track::-webkit-scrollbar-track { background: transparent; }
    .swipe-track::-webkit-scrollbar-thumb {
        background: var(--line-strong); border-radius: 10px;
    }
    .swipe-track::-webkit-scrollbar-thumb:hover { background: var(--accent); }

    /* כל כרטיס תופס כמעט את כל הרוחב (כרטיס אחד נראה בכל פעם, רמז לבא אחריו) */
    .swipe-card {
        scroll-snap-align: center;
        flex: 0 0 88%;
        min-width: 88%;
        box-sizing: border-box;
        background: linear-gradient(155deg, var(--glass), var(--bg-1));
        backdrop-filter: blur(5px);
        border: 1px solid var(--glass-border);
        border-radius: var(--radius-lg);
        padding: 26px 28px;
        min-height: 190px;
        box-shadow: var(--shadow);
        transition: border-color 0.25s ease, box-shadow 0.25s ease, transform 0.25s cubic-bezier(.2,.8,.2,1);
    }
    .swipe-card:hover {
        border-color: var(--accent-soft);
        box-shadow: var(--shadow-hover);
        transform: translateY(-4px);
    }
    .swipe-card-top { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 10px; }
    .swipe-card .pick-ticker { font-size: 1.6rem; }
    .swipe-price { font-size: 0.9rem; }

    .carousel-index-badge {
        text-align:center; font-weight: 700; color: var(--txt-2);
        background: var(--bg-1); border: 1px solid var(--line);
        border-radius: 20px; padding: 6px 18px; display: inline-block;
        font-size: 0.85rem; letter-spacing: 0.5px; margin: 10px auto 0 auto;
    }
    .carousel-index-row { text-align: center; margin-top: 12px; }

    /* ============================================================
       HOME LANDING - שני כפתורים עגולים גדולים + אנימציית שטרות
       ============================================================ */
    .home-landing { text-align: center; padding: 34px 0 12px 0; animation: premiumFadeIn 0.45s ease; }
    .home-landing-title {
        font-size: 2.3rem; font-weight: 800; color: var(--txt-1);
        margin-bottom: 10px; letter-spacing: -0.6px;
    }
    .home-landing-sub { font-size: 1.0rem; color: var(--txt-2); margin-bottom: 40px; line-height: 1.7; }
    .home-orb-label {
        text-align: center; font-size: 1.18rem; font-weight: 800;
        margin-top: 16px; color: var(--txt-1);
    }
    .home-orb-desc { text-align:center; font-size: 0.88rem; color: var(--txt-3); margin-top: 6px; line-height: 1.6; }

    .orb-check .stButton > button, .orb-find .stButton > button {
        width: 230px !important; height: 230px !important; border-radius: 50% !important;
        font-size: 1.6rem !important; font-weight: 800 !important; line-height: 1.3 !important;
        border: none !important; color: #04121f !important;
        margin: 0 auto !important; display: block !important;
        transition: transform 0.25s cubic-bezier(.2,.8,.2,1), box-shadow 0.25s ease, filter 0.2s ease !important;
        white-space: pre-line !important;
    }
    .orb-check .stButton > button {
        background: radial-gradient(circle at 35% 30%, #5eead4, #0ea5e9) !important;
        box-shadow: 0 14px 50px rgba(14,165,233,0.5), inset 0 -8px 22px rgba(0,0,0,0.18) !important;
    }
    .orb-check .stButton > button:hover {
        transform: translateY(-6px) scale(1.04); filter: brightness(1.08);
        box-shadow: 0 22px 64px rgba(14,165,233,0.65), inset 0 -8px 22px rgba(0,0,0,0.18) !important;
    }
    .orb-find .stButton > button {
        background: radial-gradient(circle at 35% 30%, #c084fc, #d4af37) !important;
        color: #1a1206 !important;
        box-shadow: 0 14px 50px rgba(192,132,252,0.5), inset 0 -8px 22px rgba(0,0,0,0.2) !important;
    }
    .orb-find .stButton > button:hover {
        transform: translateY(-6px) scale(1.04); filter: brightness(1.08);
        box-shadow: 0 22px 64px rgba(212,175,55,0.65), inset 0 -8px 22px rgba(0,0,0,0.2) !important;
    }

    .find-loader-wrap { text-align:center; padding: 20px 0; position: relative; }
    .find-loader {
        width: 230px; height: 230px; border-radius: 50%; margin: 0 auto;
        background: radial-gradient(circle at 35% 30%, #c084fc, #d4af37);
        display: flex; align-items: center; justify-content: center;
        box-shadow: 0 14px 60px rgba(212,175,55,0.6);
        position: relative; overflow: hidden;
        animation: findPulse 1.6s ease-in-out infinite;
    }
    @keyframes findPulse {
        0%,100% { box-shadow: 0 14px 60px rgba(212,175,55,0.5); }
        50%     { box-shadow: 0 14px 80px rgba(212,175,55,0.9); }
    }
    .find-pct { font-size: 3.4rem; font-weight: 800; color: #1a1206; z-index:2; }

    /* ============================================================
       OFFICE SCENE - סצנת משרד אנליסטים עובד (אנימציית CSS לשלב "תמצא לי")
       ============================================================ */
    .office-scene {
        position: relative; height: 190px; width: 100%;
        margin: 4px auto 6px auto; max-width: 560px;
        overflow: hidden; border-radius: 16px;
        background: linear-gradient(180deg, #0c1828 0%, #0a1422 70%, #0a1220 100%);
        border: 1px solid var(--line);
        box-shadow: inset 0 2px 24px rgba(0,0,0,0.45);
    }
    .office-floor {
        position: absolute; bottom: 0; left: 0; right: 0; height: 46px;
        background: linear-gradient(180deg, rgba(56,189,248,0.06), rgba(56,189,248,0.02));
        border-top: 1px solid rgba(56,189,248,0.18);
    }
    .office-window {
        position: absolute; top: 16px; left: 8%; width: 70px; height: 46px;
        border-radius: 5px; border: 1px solid rgba(56,189,248,0.18);
        background: linear-gradient(135deg, rgba(56,189,248,0.10), rgba(56,189,248,0.02));
        overflow: hidden;
    }
    .office-window::after {
        content:''; position:absolute; top:-20px; left:-40px; width:30px; height:90px;
        background: rgba(255,255,255,0.06); transform: rotate(25deg);
        animation: windowSheen 5s ease-in-out infinite;
    }
    @keyframes windowSheen { 0%,100%{ transform: translateX(0) rotate(25deg);} 50%{ transform: translateX(120px) rotate(25deg);} }

    .desk-unit { position: absolute; bottom: 30px; width: 18%; height: 120px; }
    .desk {
        position: absolute; bottom: 0; left: 0; right: 0; height: 12px;
        background: linear-gradient(180deg, #243449, #182335);
        border-radius: 3px; box-shadow: 0 3px 8px rgba(0,0,0,0.4);
    }
    .desk-wide { left: 0; right: 0; }

    /* מסך מחשב + תרשים מתחלף */
    .monitor {
        position: absolute; bottom: 12px; left: 4px; width: 34px; height: 26px;
        background: #0a1220; border: 2px solid #2b3c54; border-radius: 3px;
        box-shadow: 0 0 10px rgba(56,189,248,0.15);
    }
    .monitor-big { width: 44px; height: 32px; left: 50%; transform: translateX(-50%); }
    .monitor-chart {
        position: absolute; left: 3px; right: 3px; bottom: 3px; height: 14px;
        background:
          linear-gradient(90deg, transparent 49%, rgba(56,189,248,0.5) 50%, transparent 51%) 0 0/100% 100%,
          linear-gradient(180deg, transparent, rgba(56,189,248,0.12));
        clip-path: polygon(0 80%, 15% 60%, 30% 70%, 45% 35%, 60% 50%, 75% 20%, 100% 30%, 100% 100%, 0 100%);
        animation: chartPulse 1.6s ease-in-out infinite;
    }
    @keyframes chartPulse { 0%,100%{ opacity:0.55; } 50%{ opacity:1; } }
    .monitor-bars { position:absolute; left:4px; right:4px; bottom:3px; height:20px; display:flex; align-items:flex-end; gap:3px; }
    .monitor-bars span { flex:1; background: linear-gradient(180deg, #38bdf8, #0ea5e9); border-radius:1px 1px 0 0; animation: barGrow 1.4s ease-in-out infinite; }
    .monitor-bars span:nth-child(2){ animation-delay:0.18s; }
    .monitor-bars span:nth-child(3){ animation-delay:0.36s; }
    .monitor-bars span:nth-child(4){ animation-delay:0.54s; }
    .monitor-bars span:nth-child(5){ animation-delay:0.72s; }
    @keyframes barGrow { 0%,100%{ height:25%; } 50%{ height:90%; } }

    .keyboard {
        position: absolute; bottom: 12px; right: 4px; width: 22px; height: 6px;
        background: #2b3c54; border-radius: 2px;
    }

    /* קלסר מדפדף */
    .folder {
        position: absolute; bottom: 12px; left: 50%; transform: translateX(-50%);
        width: 30px; height: 22px; background: #1e2c40; border:1px solid #34507a;
        border-radius: 2px;
    }
    .folder-page {
        position:absolute; top:2px; left:3px; right:3px; height:16px; background:#cdd9ea;
        border-radius:1px; transform-origin: left center;
        animation: flipPage 1.8s ease-in-out infinite;
    }
    @keyframes flipPage {
        0%,100%{ transform: rotateY(0deg); opacity:1; }
        45%{ transform: rotateY(-150deg); opacity:0.7; }
        50%{ transform: rotateY(-150deg); opacity:0.7; }
        95%{ transform: rotateY(0deg); opacity:1; }
    }

    /* דמות אנליסט */
    .analyst { position: absolute; bottom: 12px; left: 50%; transform: translateX(-50%); width: 26px; height: 42px; }
    .analyst-head {
        position: absolute; top: 0; left: 50%; transform: translateX(-50%);
        width: 14px; height: 14px; border-radius: 50%;
        background: linear-gradient(160deg, #5a6b82, #3d4d63);
    }
    .analyst-body {
        position: absolute; bottom: 0; left: 50%; transform: translateX(-50%);
        width: 22px; height: 26px; border-radius: 8px 8px 4px 4px;
        background: linear-gradient(160deg, #38bdf8, #1d6fa5);
    }
    .analyst-body.body-alt { background: linear-gradient(160deg, #a78bfa, #7c5fd0); }
    .analyst-arm {
        position: absolute; width: 4px; height: 12px; border-radius: 3px;
        background: #2f8fc4; bottom: 14px;
    }

    /* תנועות שונות */
    .analyst-typing-head { animation: headBob 1.4s ease-in-out infinite; }
    @keyframes headBob { 0%,100%{ transform: translateX(-50%) translateY(0);} 50%{ transform: translateX(-50%) translateY(2px);} }
    .arm-type-l { left: 1px; animation: typeArm 0.5s ease-in-out infinite; }
    .arm-type-r { right: 1px; animation: typeArm 0.5s ease-in-out infinite 0.25s; }
    @keyframes typeArm { 0%,100%{ height:12px; } 50%{ height:8px; } }

    .analyst-look-head { animation: lookHead 3s ease-in-out infinite; }
    @keyframes lookHead { 0%,100%{ transform: translateX(-50%) rotate(0deg);} 50%{ transform: translateX(-50%) rotate(-12deg);} }
    .arm-point { right: 0px; height: 14px; transform-origin: bottom; animation: pointArm 3s ease-in-out infinite; }
    @keyframes pointArm { 0%,100%{ transform: rotate(20deg);} 50%{ transform: rotate(-30deg);} }

    .analyst-read-head { animation: readHead 2.4s ease-in-out infinite; }
    @keyframes readHead { 0%,100%{ transform: translateX(-50%) rotate(8deg);} 50%{ transform: translateX(-50%) rotate(-4deg);} }
    .arm-flip { right: 2px; animation: flipArm 1.8s ease-in-out infinite; }
    @keyframes flipArm { 0%,100%{ transform: rotate(10deg);} 45%{ transform: rotate(-25deg);} }

    /* שני אנליסטים שמדברים */
    .analyst-discuss-l { left: 18%; }
    .analyst-discuss-r { left: 54%; }
    .analyst-discuss-head { animation: nod 2s ease-in-out infinite; }
    .analyst-discuss-head2 { animation: nod 2s ease-in-out infinite 1s; }
    @keyframes nod { 0%,100%{ transform: translateX(-50%) rotate(0);} 30%{ transform: translateX(-50%) rotate(8deg);} 60%{ transform: translateX(-50%) rotate(-6deg);} }
    .arm-gesture { right: 0; animation: gesture 2.2s ease-in-out infinite; }
    .arm-gesture2 { left: 0; animation: gesture 2.2s ease-in-out infinite 0.6s; }
    @keyframes gesture { 0%,100%{ transform: rotate(15deg);} 50%{ transform: rotate(-20deg);} }
    .speech-bubble {
        position: absolute; top: 4px; left: 40%; width: 16px; height: 11px;
        background: rgba(255,255,255,0.85); border-radius: 6px;
        animation: bubblePop 2.6s ease-in-out infinite;
    }
    .speech-bubble::after {
        content:''; position:absolute; bottom:-4px; left:4px; width:0; height:0;
        border-left:3px solid transparent; border-right:3px solid transparent; border-top:5px solid rgba(255,255,255,0.85);
    }
    @keyframes bubblePop { 0%,40%,100%{ transform: scale(0); opacity:0; } 55%,85%{ transform: scale(1); opacity:1; } }

    .office-caption {
        margin-top: 14px; font-size: 1.0rem; color: var(--txt-2);
        font-weight: 600; text-align: center;
    }

    /* ============================================================
       FUNDAMENTAL screen
       ============================================================ */
    .fund-card {
        background: linear-gradient(155deg, var(--bg-2), var(--bg-1)); border: 1px solid var(--glass-border);
        border-radius: var(--radius-lg); padding: 30px 32px; margin-bottom: 24px;
        box-shadow: var(--shadow);
    }
    .fund-table-title {
        color: var(--txt-1); font-size: 1.1rem; font-weight: 700;
        margin-bottom: 18px; padding-bottom: 14px; border-bottom: 1px solid var(--line);
    }
    .fund-meta-row { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }
    .fund-meta-box {
        flex: 1; min-width: 200px; background: var(--bg-1);
        border: 1px solid var(--line); border-radius: 16px; padding: 18px 20px;
        transition: transform 0.2s cubic-bezier(.2,.8,.2,1), border-color 0.2s ease;
    }
    .fund-meta-box:hover { transform: translateY(-3px); border-color: var(--accent-soft); }
    .fund-meta-label { font-size: 0.83rem; color: var(--txt-2); margin-bottom: 8px; }
    .fund-meta-value { font-size: 1.3rem; font-weight: 700; color: var(--txt-1); }
    /* legacy fund verdict box aliases */
    .fund-verdict-box { text-align:center; border-radius:var(--radius-lg); padding:28px; margin-bottom:24px; border:1px solid var(--glass-border); box-shadow: var(--shadow); }
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
        border: 1px solid var(--glass-border); border-radius: var(--radius-lg);
        padding: 34px 32px; box-shadow: var(--shadow);
        backdrop-filter: blur(4px);
        position: relative; overflow: hidden;
        transition: border-color 0.25s cubic-bezier(.2,.8,.2,1), transform 0.25s cubic-bezier(.2,.8,.2,1), box-shadow 0.25s ease;
    }
    .scout-card::before {
        content:''; position:absolute; top:0; left:0; right:0; height:4px;
        background: linear-gradient(90deg, transparent, var(--accent), transparent); opacity:0.8;
    }
    .scout-card:hover { transform: translateY(-6px); border-color: var(--accent-soft); box-shadow: var(--shadow-hover); }
    .scout-header { display:flex; justify-content:space-between; align-items:center; margin-bottom: 22px; flex-wrap: wrap; gap: 10px; }
    .scout-title { color: var(--txt-1); font-size: 1.8rem; font-weight: 800; margin:0; display:flex; align-items:center; flex-wrap: wrap; }
    .scout-title-sub { font-size: 1rem; color: var(--txt-2); font-weight: 400; padding-right: 12px; }
    .scout-badge { padding: 8px 20px; border-radius: 30px; font-size: 0.95rem; font-weight: 700; background: var(--bg-3); border: 1px solid var(--line-strong); white-space: nowrap; }
    .scout-prob-container { text-align: center; margin-bottom: 18px; }
    .scout-prob-label { margin:0; color: var(--txt-2); font-weight:600; letter-spacing:1.5px; font-size:0.85rem; text-transform:uppercase; }
    .scout-prob { font-size: 4.4rem; font-weight: 800; color: var(--accent); margin: 8px 0 14px 0; line-height: 1; text-shadow: 0 0 35px rgba(56,189,248,0.4); }
    .scout-phase-pill { display:inline-block; background: var(--bg-0); padding: 9px 20px; border-radius: 25px; border: 1px solid var(--line); }
    .scout-divider { border-top: 1px solid var(--line); margin: 24px 0; }
    .scout-stats-grid { display:flex; flex-direction:column; gap: 20px; margin-bottom: 22px; }
    .scout-stat-box { flex:1; background: var(--bg-1); border:1px solid var(--glass-border); border-radius:18px; padding: 24px; display:flex; flex-direction:column; transition: border-color 0.2s ease, transform 0.2s ease; }
    .scout-stat-box:hover { border-color: var(--accent-soft); transform: translateY(-2px); }
    .scout-section-title { color: var(--txt-1); font-size: 1.08rem; font-weight: 700; margin-bottom: 16px; border-bottom: 1px solid var(--line); padding-bottom: 12px; }
    .scout-list-item { font-size: 1.0rem; color: var(--txt-2); margin-bottom: 14px; display:flex; justify-content:space-between; align-items:center; flex-wrap: wrap; gap: 6px; }
    .scout-alert-box { padding: 20px 24px; border-radius: 16px; margin-top: 24px; border-right: 4px solid var(--neg); background: rgba(239,68,68,0.06); }
    .scout-alert-title { font-size: 1.05rem; color: var(--txt-1); font-weight:bold; margin-bottom:12px; display:block; }
    .scout-alert-text { font-size: 0.92rem; display:block; color: var(--txt-2); line-height: 1.7; margin-bottom: 6px; }
    .trap-section-label { font-size: 0.82rem; color: var(--txt-2); font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin: 14px 0 8px 0; display:block; }
    .trap-fund-highlight { background: rgba(239,68,68,0.10); border-right: 3px solid var(--neg); padding: 12px 16px; border-radius: 10px; font-weight: 600; color: #fecaca !important; }
    .edu-box { background: rgba(56,189,248,0.05); border-right: 3px solid var(--accent); padding: 18px 20px; margin-top: 20px; border-radius: 12px; font-size: 0.93rem; color: var(--txt-1); line-height: 1.85; flex-grow: 1; }
    .edu-box-title { color: var(--accent); font-weight: 700; display:block; margin-bottom: 10px; font-size: 1.0rem; }

    /* Roadmap inside scout card */
    .roadmap-box { background: var(--bg-1); border-radius: 16px; padding: 24px 28px; margin-top: 24px; margin-bottom: 14px; border-right: 3px solid var(--accent); display:flex; justify-content:center; align-items:center; gap: 28px; font-size: 0.95rem; color: var(--txt-2); flex-wrap: wrap; box-shadow: var(--shadow); }
    .roadmap-step { display:flex; flex-direction:column; align-items:center; gap: 4px; }
    .roadmap-label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 6px; color: var(--txt-3); }
    .roadmap-value { font-weight: 600; color: var(--txt-1); font-size: 1.0rem; }
    .roadmap-arrow { color: var(--txt-3); font-size: 1.3rem; font-weight: bold; }

    /* Staged trade plan */
    .plan-stage { background: var(--bg-1); border:1px solid var(--glass-border); border-radius: 14px; padding: 16px 20px; margin-bottom: 12px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; transition: border-color 0.2s ease; }
    .plan-stage:hover { border-color: var(--accent-soft); }
    .plan-stage-label { font-weight: 700; color: var(--txt-1); font-size: 1.0rem; }
    .plan-stage-val { font-weight: 800; font-size: 1.15rem; }
    .plan-stage-note { font-size: 0.85rem; color: var(--txt-2); width:100%; margin-top: 6px; line-height:1.65; }

    /* ============================================================
       INSTITUTIONAL MAP cards
       ============================================================ */
    .map-card {
        background: linear-gradient(180deg, var(--bg-2) 0%, var(--bg-1) 100%);
        padding: 34px 28px; border-radius: var(--radius-lg); text-align: center;
        box-shadow: var(--shadow); margin-bottom: 28px; border: 1px solid var(--glass-border);
        transition: transform 0.25s cubic-bezier(.2,.8,.2,1), border-color 0.25s ease, box-shadow 0.25s ease;
    }
    .map-card:hover { transform: translateY(-6px); border-color: var(--accent-soft); box-shadow: var(--shadow-hover); }
    .map-card h4 { margin:0; font-size: 1.3rem; color: var(--txt-1); font-weight: 700; }
    .map-card-label { font-size: 0.88rem; color: var(--txt-2); margin: 14px 0 8px 0; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }
    .map-card-score { margin:0; font-size: 3.2rem; font-weight: 800; line-height: 1.1; }
    .map-desc { font-size: 0.92rem; color: var(--txt-2); margin-top: 20px; line-height: 1.75; padding-top: 18px; border-top: 1px dashed var(--line-strong); }

    /* ============================================================
       MOBILE - מבטיח שכרטיסיות (Trading Scout, Home Picks) לא נחתכות,
       נערמות אנכית עם whitespace תקין, וטקסט/מספרים גדולים מצטמצמים
       ============================================================ */
    @media (max-width: 640px) {
        .block-container { padding-left: 0.7rem; padding-right: 0.7rem; }
        .scout-card { padding: 20px 16px; }
        .scout-title { font-size: 1.3rem; }
        .scout-prob { font-size: 3.0rem; }
        .scout-badge { font-size: 0.82rem; padding: 6px 14px; }
        .pick-card { padding: 14px 14px; }
        .pick-ticker { font-size: 1.35rem; }
        .vb-headline { font-size: 1.2rem !important; }
        .vb-body { padding: 18px 18px !important; }
        .price-header .ph-price { font-size: 1.6rem; }
        .main-header h1 { font-size: 1.3rem; }
        .map-card-score { font-size: 2.2rem; }
        .narrative-box { padding: 16px 18px; }
        .float-back-wrap { bottom: 14px; left: 14px; }
        .float-back-wrap a { padding: 9px 14px; font-size: 0.82rem; }
        /* חצי Overlay במובייל - גדולים ונוחים למגע (56-60px) */
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"] > span.cs-next-marker) button,
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"] > span.cs-prev-marker) button {
            width: 58px !important; height: 58px !important; min-height: 58px !important;
            font-size: 1.45rem !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"] > span.cs-next-marker) { right: 6px !important; }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"] > span.cs-prev-marker) { left: 6px !important; }
        .carousel-pick-card { padding-left: 64px !important; padding-right: 64px !important; }
        /* כרטיסי החלקה במובייל - כרטיס כמעט מלא, עם רמז לבא אחריו */
        .swipe-card { flex: 0 0 90%; min-width: 90%; padding: 16px 16px; min-height: 175px; }
        .swipe-hint { font-size: 0.9rem; }
        .swipe-card .pick-ticker { font-size: 1.4rem; }
        .carousel-index-row { margin-top: 16px; }
        /* כפתורים עגולים במובייל (180-200px) עם טקסט גדול וברור, ורווח נדיב מסביב */
        .home-landing { padding: 22px 0 16px 0; }
        .home-landing-sub { margin-bottom: 44px; }
        .orb-check .stButton > button, .orb-find .stButton > button {
            width: 190px !important; height: 190px !important; font-size: 1.35rem !important;
            line-height: 1.4 !important;
        }
        .home-orb-label { font-size: 1.25rem; margin-top: 18px; }
        .home-orb-desc { font-size: 0.9rem; padding: 0 8px; margin-top: 8px; }
        .find-loader { width: 190px; height: 190px; }
        .find-pct { font-size: 2.8rem; }
        .home-landing-title { font-size: 1.5rem; }
    }

    /* nav */
    .topnav-spacer { height: 8px; }
    </style>

    <script>
    (function() {
        // מאזין גלילה: מתכווץ בגלילה למטה, נפתח בתנועה קלה למעלה (Q1)
        if (window._navScrollBound) return;
        window._navScrollBound = true;
        var lastY = 0;
        var doc = window.parent.document;
        function onScroll() {
            try {
                var y = window.parent.scrollY || doc.documentElement.scrollTop || 0;
                var body = doc.body;
                if (y > lastY && y > 80) {
                    body.classList.add('nav-collapsed');      // גלילה למטה -> כיווץ
                } else if (y < lastY - 4) {
                    body.classList.remove('nav-collapsed');    // תנועה קלה למעלה -> פתיחה
                }
                if (y <= 5) body.classList.remove('nav-collapsed'); // בראש העמוד -> תמיד פתוח
                lastY = y;
            } catch (e) {}
        }
        try {
            (window.parent || window).addEventListener('scroll', onScroll, {passive: true});
        } catch (e) {}
    })();
    </script>
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
    if "nav_request" not in st.session_state:
        st.session_state.nav_request = None      # פעולת ניווט בהמתנה, מעובדת בראש main() לפני ה-widgets
    if "handoff_pending" not in st.session_state:
        st.session_state.handoff_pending = False  # דגל חד-פעמי: טיקר טרי הועבר, מסך היעד צריך להפעיל ניתוח אוטומטי
    if "market_scan_results" not in st.session_state:
        st.session_state.market_scan_results = None
    if "home_card_index" not in st.session_state:
        st.session_state.home_card_index = 0       # אינדקס דפדוף כרטיסיות במסך הבית
    if "scan_card_index" not in st.session_state:
        st.session_state.scan_card_index = 0        # אינדקס דפדוף כרטיסיות בסריקת שוק
    if "auto_run_market_scan" not in st.session_state:
        st.session_state.auto_run_market_scan = False  # טריגר חד-פעמי מכפתור "סריקת שוק מלאה" בבית
    if "home_mode" not in st.session_state:
        st.session_state.home_mode = "landing"   # landing (שני כפתורים) / check (סריקה ידנית) / results (קרוסלה)
    if "home_scan_results" not in st.session_state:
        st.session_state.home_scan_results = None  # תוצאות "תמצא לי" לשמירה בין ריצות
    if "run_find_scan" not in st.session_state:
        st.session_state.run_find_scan = False     # טריגר חד-פעמי להפעלת סריקת "תמצא לי"


# יקום סריקה למסך הבית - 24 מניות מובילות (מהיר)
HOME_SCAN_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "CRM",
    "JPM", "V", "MA", "UNH", "LLY", "COST", "HD", "PG",
    "XOM", "CVX", "AMD", "PANW", "NFLX", "ABBV", "WMT", "KO",
]


def go_to_screen(page: str, ticker: str = None) -> None:
    """
    מבקש מעבר מסך (Cross-Screen Handoff). במקום לשנות מצב widget תוך כדי ריצה (מה שגרם
    ל-StreamlitAPIException וכפתורים 'תקועים'), אנו מתורים בקשת ניווט שתעובד בראש main()
    *לפני* שה-widget של nav_select נוצר. זו הדרך היציבה היחידה ב-Streamlit.
    """
    try:
        st.session_state.nav_request = {
            "page": page,
            "ticker": ticker.strip().upper() if ticker else None,
            "kind": "goto",
        }
    except Exception:
        # אם משום מה לא ניתן לתור את הבקשה - לפחות נעדכן ישירות, בלי לקרוס
        st.session_state.current_page = page
    st.rerun()  # מחוץ ל-try: st.rerun מממש את עצמו ע"י חריגה פנימית שאסור לבלוע


def go_back() -> None:
    """מבקש חזרה למסך הקודם לפי היסטוריית הניווט (מעובד בראש main())."""
    try:
        st.session_state.nav_request = {"kind": "back"}
    except Exception:
        pass
    st.rerun()


def _process_nav_request() -> None:
    """
    מעבד בקשת ניווט בהמתנה - חייב לרוץ בראש main(), לפני render_top_nav וכל widget אחר.
    כאן מותר למחוק/לאפס keys של widgets כי הם עדיין לא אותחלו בריצה הנוכחית.
    """
    req = st.session_state.get("nav_request")
    if not req:
        return
    st.session_state.nav_request = None  # צריכת הבקשה

    if req.get("kind") == "back":
        history = st.session_state.get("nav_history", [])
        if history:
            st.session_state.current_page = history.pop()
    else:  # goto
        page = req.get("page")
        ticker = req.get("ticker")
        prev_page = st.session_state.get("current_page")
        if prev_page and prev_page != page:
            st.session_state.setdefault("nav_history", [])
            st.session_state.nav_history.append(prev_page)
        if ticker:
            st.session_state.handoff_ticker = ticker
            # דגל חד-פעמי: ניווט טרי עם טיקר התרחש עכשיו. המסך שירונדר הבא (ורק הוא)
            # "יצרוך" אותו ויפעיל ניתוח אוטומטי - גם אם הטיקר זהה לביקור קודם באותו מסך.
            # זה מחליף את התלות הישנה ב-_home_consumed_handoff/_fund_consumed_handoff/_scout_consumed_handoff
            # שהייתה נכשלת בדיוק במקרה הזה (ביקור חוזר עם אותו טיקר לא היה מפעיל ניתוח מחדש).
            st.session_state.handoff_pending = True
        if page:
            st.session_state.current_page = page

    # איפוס מפתח ה-widget של התפריט כדי שיאותחל מחדש לפי current_page (מותר - עוד לפני יצירתו)
    if "nav_select" in st.session_state:
        del st.session_state["nav_select"]


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


def _render_pick_result_card(p: dict, idx: int, key_prefix: str, dest_page: str = "🏠 בית") -> None:
    """
    רכיב משותף לכרטיס תוצאת סריקה (מניה + Verdict + ציון) - מקור אמת יחיד.
    משמש גם ב-_render_top_picks וגם ב-_render_market_scanner, כדי למנוע כפילות קוד
    וסיכון לאי-עקביות בין שני מסכי הסריקה.
    """
    price_html = render_price_inline(p["ticker"])
    st.markdown(
        f"""<div class='pick-card' style='border-right:5px solid {p['color']}; border-top:none; margin-bottom:8px;'>
            <div style='display:flex; align-items:center; gap:14px; flex-wrap:wrap;'>
                <span class='pick-rank'>#{idx+1}</span>
                <span class='pick-ticker' style='font-size:1.5rem;'>{p['ticker']}</span>
                <span>{price_html}</span>
            </div>
            <div class='pick-headline' style='color:{p['color']}; margin-top:8px;'>{p['headline']}</div>
            <div class='pick-meta'>תמחור: <b style='color:{p['valuation_color']}'>{p['valuation']}</b> · CIS {p['cis']:.0f}
                · Wyckoff: {p.get('phase','-')} · FCF: {p['fcf_yield']} · P/E: {p['pe']} · {p['sector_he']}</div>
            <div class='pick-score-pill'>ציון משוקלל: {p['composite']:.0f}</div>
        </div>""",
        unsafe_allow_html=True,
    )
    if st.button(f"📊 ניתוח מלא ל-{p['ticker']}", key=f"{key_prefix}_{p['ticker']}_{idx}", use_container_width=True):
        if dest_page == "📈 Trading Scout":
            # תיקון קריטי: קובעים את מצב הבית מראש ל-"results" (קרוסלה) כדי שכל דרך
            # חזרה - כפתור הניווט הכללי "⬅️ חזור למסך הקודם", הכפתור הצף, או
            # "⬅️ חזור לקרוסלה" הספציפי - תנחת תמיד על הקרוסלה ולא על מסך הנחיתה
            # (שני העיגולים) או על ראש העמוד.
            st.session_state.home_mode = "results"
        go_to_screen(dest_page, p["ticker"])


def _render_card_carousel(results: list, key_prefix: str, index_key: str, dest_page: str = "🏠 בית") -> None:
    """
    קרוסלה משולבת: כרטיס יחיד מודגש (לפי index_key) עם חצי Overlay אמיתיים
    משני צידיו - בנוסף, למטה, רצועת Swipe של כל הכרטיסים לצפייה/החלקה מהירה.

    *** איך ה-Overlay האמיתי הושג (אחרי 3 ניסיונות קודמים שנכשלו) ***:
    בניסיון V19.2 קודם ניחשתי class CSS שStreamlit כביכול מוסיף ל-
    st.container(key=...) - הניחוש היה כנראה שגוי, ולכן position:relative
    לא הוחל בשום מקום, וה-position:absolute "ברח" לקואורדינטות של כל
    העמוד (זו הסיבה שהחצים צפו לפינה אקראית).

    הפעם: בלי ניחוש class בכלל. כל חץ יושב בתוך st.container() *אמיתי*
    משלו (קינון DOM מובטח ע"י Streamlit), עם תג <span> ייחודי וזעיר בתוכו
    כ"סימן הכר". ה-CSS משתמש ב-:has() כדי לאתר *לפי תוכן* (לא לפי שם
    class מנוחש) איזה container מכיל איזה סימן, וממקם אותו position:absolute
    בהתאם. שני החצים וה כרטיס כולם ילדים אמיתיים של st.container() חיצוני
    משותף (stage) שמסומן position:relative - כך שה-absolute positioning
    מתייחס נכון לגבולות האזור, לא לכל העמוד.

    הבהרה קריטית ליציבות: לחיצת חץ משנה אך ורק את index_key + st.rerun()
    (ריענון Streamlit תקין, לא רענון דפדפן) - לא נוגעת ב-current_page/
    nav_request/handoff_ticker, ולכן נשארת תמיד באותו מסך.
    """
    if not results:
        return

    total = len(results)
    cur = st.session_state.get(index_key, 0)
    if not isinstance(cur, int) or cur < 0 or cur >= total:
        cur = 0
        st.session_state[index_key] = 0

    p = results[cur]
    try:
        price_html = render_price_inline(p["ticker"])
    except Exception:
        price_html = ""

    # --- stage: container אמיתי המכיל את הכרטיס + שני תת-containers (חץ כל אחד) ---
    stage = st.container()
    with stage:
        # סימן הכר לעוגן ה-position:relative של כל האזור (מאותר ב-CSS דרך :has(),
        # לא דרך ניחוש class)
        st.markdown("<span class='cs-stage-marker'></span>", unsafe_allow_html=True)

        try:
            st.markdown(
                f"""<div class='pick-card carousel-pick-card' style='border-right:5px solid {p['color']}; border-top:none;'>
                    <div style='display:flex; align-items:center; gap:14px; flex-wrap:wrap;'>
                        <span class='pick-rank'>#{cur+1}</span>
                        <span class='pick-ticker' style='font-size:1.6rem;'>{p['ticker']}</span>
                        <span>{price_html}</span>
                    </div>
                    <div class='pick-headline' style='color:{p['color']}; margin-top:8px;'>{p['headline']}</div>
                    <div class='pick-meta'>תמחור: <b style='color:{p['valuation_color']}'>{p['valuation']}</b> · CIS {p['cis']:.0f}
                        · Wyckoff: {p.get('phase','-')} · FCF: {p['fcf_yield']} · P/E: {p['pe']} · {p['sector_he']}</div>
                    <div class='pick-score-pill'>ציון משוקלל: {p['composite']:.0f}</div>
                </div>""",
                unsafe_allow_html=True,
            )
        except Exception as exc:
            st.error(f"שגיאה בהצגת הכרטיס: {exc}")

        # חץ "▶" (הבא) - container אמיתי משלו, מסומן ע"י cs-next-marker
        next_box = st.container()
        with next_box:
            st.markdown("<span class='cs-next-marker'></span>", unsafe_allow_html=True)
            if st.button("▶", key=f"{key_prefix}_next", disabled=(cur >= total - 1), help="המניה הבאה"):
                _ok = False
                try:
                    st.session_state[index_key] = min(total - 1, cur + 1)
                    _ok = True
                except Exception as exc:
                    st.error(f"שגיאה במעבר כרטיס: {exc}")
                if _ok:
                    st.rerun()  # מחוץ ל-try כדי לא לבלוע את חריגת ה-rerun הפנימית

        # חץ "◀" (הקודם) - container אמיתי משלו, מסומן ע"י cs-prev-marker
        prev_box = st.container()
        with prev_box:
            st.markdown("<span class='cs-prev-marker'></span>", unsafe_allow_html=True)
            if st.button("◀", key=f"{key_prefix}_prev", disabled=(cur <= 0), help="המניה הקודמת"):
                _ok = False
                try:
                    st.session_state[index_key] = max(0, cur - 1)
                    _ok = True
                except Exception as exc:
                    st.error(f"שגיאה במעבר כרטיס: {exc}")
                if _ok:
                    st.rerun()

    # אינדקס מעוצב
    st.markdown(
        f"<div class='carousel-index-row'><span class='carousel-index-badge'>כרטיס {cur + 1} מתוך {total}</span></div>",
        unsafe_allow_html=True,
    )

    # כפתור "ניתוח מלא" - כפתור Streamlit אמיתי (צריך לוגיקת home_mode + ניווט)
    if st.button(f"📊 ניתוח מלא ל-{p['ticker']}", key=f"{key_prefix}_full_{p['ticker']}_{cur}", use_container_width=True, type="primary"):
        if dest_page == "📈 Trading Scout":
            # קביעת מצב הבית מראש ל-"results" כדי שכל דרך חזרה תנחת על הקרוסלה
            st.session_state.home_mode = "results"
        go_to_screen(dest_page, p["ticker"])

    # --- שמירה על Swipe כתוספת: רצועת כל הכרטיסים להחלקה/צפייה מהירה ---
    st.markdown(
        "<div class='swipe-hint'>👈 או החלק ימינה ושמאלה לצפייה מהירה בכולן 👉</div>",
        unsafe_allow_html=True,
    )
    parts = ["<div class='swipe-track'>"]
    for i, sp in enumerate(results):
        try:
            sp_price_html = render_price_inline(sp["ticker"])
        except Exception:
            sp_price_html = ""
        parts.append(
            f"<div class='swipe-card' style='border-right:5px solid {sp['color']};'>"
            f"<div class='swipe-card-top'>"
            f"<span class='pick-rank'>#{i+1}</span>"
            f"<span class='pick-ticker'>{sp['ticker']}</span>"
            f"<span class='swipe-price'>{sp_price_html}</span>"
            f"</div>"
            f"<div class='pick-headline' style='color:{sp['color']};'>{sp.get('headline','')}</div>"
            f"<div class='pick-meta'>תמחור: <b style='color:{sp['valuation_color']}'>{sp['valuation']}</b> · CIS {sp['cis']:.0f}"
            f" · Wyckoff: {sp.get('phase','-')} · FCF: {sp['fcf_yield']} · P/E: {sp['pe']} · {sp['sector_he']}</div>"
            f"<div class='pick-score-pill'>ציון משוקלל: {sp['composite']:.0f}</div>"
            f"</div>"
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


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
            try:
                if not SCOUT_CORE_AVAILABLE:
                    st.error("מודול הליבה חסר.")
                elif MARKET_SCANNER_AVAILABLE:
                    # מנוע הסריקה החדש עם Early Pruning - מהיר יותר על יקום רחב
                    prog = st.progress(0.0)
                    status = st.empty()

                    def _home_cb(done, total, ticker, stats):
                        try:
                            prog.progress(min(1.0, done / max(1, total)))
                            status.caption(f"נסרקו {done}/{total} · עברו: {stats['passed']}")
                        except Exception:
                            pass

                    scanner = MarketScanner(_sc_module)
                    with st.spinner(f"סורק {len(pool)} מניות (Early Pruning, {eta})..."):
                        out = scanner.scan_market(
                            mode="balanced", max_tickers=len(pool), universe=pool,
                            top_n=5, progress_callback=_home_cb,
                        )
                    prog.progress(1.0)
                    st.session_state.home_top_picks = out["results"]
                    st.session_state.home_card_index = 0  # איפוס דפדוף לסריקה חדשה
                else:
                    with st.spinner(f"סורק {len(pool)} מניות לאיתור שילובי איכות ({eta})..."):
                        st.session_state.home_top_picks = scan_top_opportunities(pool, top_n=5, mode="Balanced")
                        st.session_state.home_card_index = 0
            except Exception as exc:
                # הגנה קריטית: שגיאה לא צפויה כאן מוצגת מקומית, לא מקריסה את הסקריפט
                st.error(f"⚠️ שגיאה בסריקה: {exc}")
                st.session_state.home_top_picks = []
    with c2:
        st.caption(f"זמן משוער לסריקה: {eta}")

    picks = st.session_state.get("home_top_picks")
    if picks is None:
        st.info("בחר רוחב חיפוש ולחץ 'סרוק' כדי לקבל את 5 המניות הבולטות ביותר כרגע לפי שכלול וואיקוף + פונדמנטלי.")
    elif not picks:
        st.warning("לא נמצאו כרגע שילובים איכותיים (איסוף מוסדי + פונדמנטל חזק) ביקום הסריקה. נסה רוחב חיפוש גדול יותר, או שהשוק במצב המתנה.")
    else:
        # תצוגת כרטיסיות עם דפדוף (Carousel) - כרטיס אחד בכל פעם עם חצים
        _render_card_carousel(picks, key_prefix="home_pick", index_key="home_card_index", dest_page="🏠 בית")

    st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
    if st.button("🗺️ אפשרות לסריקות נוספות (לפי סקטור)", use_container_width=True, key="more_scans_btn"):
        go_to_screen("🗺️ מפה מוסדית")

    # --- כפתור סריקת שוק מלאה (כל השוק) - מפעיל אוטומטית את הסורק הכללי במפה ---
    if st.button("🔭 סריקת שוק מלאה (כל השוק)", use_container_width=True, type="primary", key="home_full_market_scan"):
        st.session_state.auto_run_market_scan = True
        go_to_screen("🗺️ מפה מוסדית")
    st.caption("סריקה רחבה על כל השוק האמריקאי עם Early Pruning.")

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
        bullets = build_fundamental_bullets(fdata, ticker, current_phase=current_phase)
        st.markdown("<div class='narrative-box'><span class='narrative-title'>🦅 ניתוח ערך - הנקודות המרכזיות</span>"
                    + "".join(f"<div style='margin:6px 0; line-height:1.6;'>• {b}</div>" for b in bullets)
                    + "</div>", unsafe_allow_html=True)
        with st.expander("📖 הסבר נוסף (ניתוח מלא ומלל חופשי)", expanded=False):
            narrative = build_fundamental_narrative(fdata, ticker, verdict, current_phase=current_phase)
            st.markdown(narrative)
    else:
        st.caption("⚠️ לא ניתן היה לשאוב נתונים פונדמנטליים עבור מניה זו כרגע - ההכרעה לעיל מבוססת על Wyckoff בלבד.")

    cta1, cta2, cta3 = st.columns([1, 1, 1.4])
    with cta1:
        if st.button("🎯 קבל אסטרטגיית מסחר", type="primary", use_container_width=True, key="home_to_strategy"):
            go_to_screen("📈 Trading Scout", ticker)
    with cta2:
        if st.button("📊 ניתוח פונדמנטלי מלא", use_container_width=True, key="home_to_fundamental"):
            go_to_screen("📊 ניתוח פונדמנטלי", ticker)
    with cta3:
        st.caption("אסטרטגיית מסחר = תוכנית כניסה/סטופ/יעדים. ניתוח פונדמנטלי מלא = טבלת מכפילים מפורטת והסברים.")


def _render_find_money_animation(pct: int) -> None:
    """
    סצנת 'משרד אנליסטים עובד' - אנימציית CSS אלגנטית: דמויות ליד שולחנות
    מקלידות, בוחנות גרפים, מדפדפות בקלסרים ודנות ביניהן. כולל עיגול טעינה
    + אחוזים גדולים. הפונקציה שומרת על שמה (משמשת את _run_find_scan).

    קריטי: כל ה-HTML חייב להיבנות כמחרוזת רציפה אחת *ללא שורות ריקות וללא
    הזחה* - שורה ריקה בתוך בלוק HTML גורמת למעבד ה-markdown של Streamlit
    לסגור את הבלוק ולהציג את שאר ה-HTML כטקסט גולמי (זה היה הבאג של ה-HTML
    שדלף מאחורי העיגול). לכן הסצנה נבנית כאן כרשימת חלקים שמחוברים בלי
    תווי שורה.
    """
    parts = [
        "<div class='office-scene'>",
        "<div class='office-window'></div>",
        "<div class='office-window' style='left:auto; right:8%;'></div>",
        # אנליסט 1 - מקליד
        "<div class='desk-unit' style='left:6%;'>",
        "<div class='analyst'>",
        "<div class='analyst-head analyst-typing-head'></div>",
        "<div class='analyst-body'></div>",
        "<div class='analyst-arm arm-type-l'></div>",
        "<div class='analyst-arm arm-type-r'></div>",
        "</div>",
        "<div class='desk'>",
        "<div class='monitor'><div class='monitor-chart'></div></div>",
        "<div class='keyboard'></div>",
        "</div>",
        "</div>",
        # אנליסט 2 - בוחן גרף
        "<div class='desk-unit' style='left:28%;'>",
        "<div class='analyst'>",
        "<div class='analyst-head analyst-look-head'></div>",
        "<div class='analyst-body'></div>",
        "<div class='analyst-arm arm-point'></div>",
        "</div>",
        "<div class='desk'>",
        "<div class='monitor monitor-big'><div class='monitor-bars'><span></span><span></span><span></span><span></span><span></span></div></div>",
        "<div class='keyboard'></div>",
        "</div>",
        "</div>",
        # אנליסט 3 - מדפדף בקלסר
        "<div class='desk-unit' style='left:50%;'>",
        "<div class='analyst'>",
        "<div class='analyst-head analyst-read-head'></div>",
        "<div class='analyst-body'></div>",
        "<div class='analyst-arm arm-flip'></div>",
        "</div>",
        "<div class='desk'>",
        "<div class='folder'><div class='folder-page'></div></div>",
        "</div>",
        "</div>",
        # שני אנליסטים - דנים ביניהם
        "<div class='desk-unit' style='left:72%; width:24%;'>",
        "<div class='analyst analyst-discuss-l'>",
        "<div class='analyst-head analyst-discuss-head'></div>",
        "<div class='analyst-body'></div>",
        "<div class='analyst-arm arm-gesture'></div>",
        "</div>",
        "<div class='analyst analyst-discuss-r' style='left:54%;'>",
        "<div class='analyst-head analyst-discuss-head2'></div>",
        "<div class='analyst-body body-alt'></div>",
        "<div class='analyst-arm arm-gesture2'></div>",
        "</div>",
        "<div class='speech-bubble'></div>",
        "<div class='desk desk-wide'></div>",
        "</div>",
        "<div class='office-floor'></div>",
        "</div>",
    ]
    # חיבור בלי תווי שורה כלל - בלוק HTML רציף אחד
    st.markdown("".join(parts), unsafe_allow_html=True)
    st.markdown(
        f"<div class='find-loader-wrap'><div class='find-loader'><span class='find-pct'>{pct}%</span></div>"
        f"<div class='office-caption'>המערכת סורקת עבורך את השוק...</div></div>",
        unsafe_allow_html=True,
    )


def _run_find_scan() -> None:
    """מריץ סריקת שוק מלאה עם אנימציית שטרות + אחוזי התקדמות, ושומר תוצאות ב-session_state."""
    universe = _build_market_universe()
    anim_slot = st.empty()

    if not MARKET_SCANNER_AVAILABLE:
        with anim_slot.container():
            st.error("מנוע הסריקה אינו זמין כרגע.")
        st.session_state.home_scan_results = []
        return

    scanner = MarketScanner(_sc_module)

    def _cb(done, total, ticker, stats):
        try:
            pct = int(min(100, done / max(1, total) * 100))
            with anim_slot.container():
                _render_find_money_animation(pct)
        except Exception:
            pass

    try:
        out = scanner.scan_market(
            mode="balanced", max_tickers=min(len(universe), 1500),
            universe=universe, top_n=20, progress_callback=_cb,
        )
        st.session_state.home_scan_results = out["results"]
        st.session_state.scan_card_index = 0
    except Exception as exc:
        st.session_state.home_scan_results = []
        anim_slot.error(f"⚠️ שגיאה בסריקה: {exc}")
        return
    anim_slot.empty()


def screen_home() -> None:
    mode = st.session_state.get("home_mode", "landing")

    # ===================== מצב נחיתה: שני כפתורים עגולים =====================
    if mode == "landing":
        st.markdown(
            "<div class='home-landing'>"
            "<div class='home-landing-title'>📈 Wyckoff Institutional Analyst</div>"
            "<div class='home-landing-sub'>רדאר הכסף החכם - מה תרצה לעשות?</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        _c1, col_check, _cmid, col_find, _c2 = st.columns([1, 2, 0.4, 2, 1])
        with col_check:
            st.markdown("<div class='orb-check'>", unsafe_allow_html=True)
            if st.button("🔍\nתבדוק לי", key="orb_check_btn"):
                st.session_state.home_mode = "check"
                st.rerun()
            st.markdown("</div><div class='home-orb-label'>תבדוק לי</div>"
                        "<div class='home-orb-desc'>הזן טיקר וקבל ניתוח Wyckoff + פונדמנטלי מלא</div>",
                        unsafe_allow_html=True)
        with col_find:
            st.markdown("<div class='orb-find'>", unsafe_allow_html=True)
            if st.button("💰\nתמצא לי", key="orb_find_btn"):
                st.session_state.home_mode = "results"
                st.session_state.run_find_scan = True
                st.rerun()
            st.markdown("</div><div class='home-orb-label'>תמצא לי</div>"
                        "<div class='home-orb-desc'>סריקת שוק מלאה - המערכת תמצא עבורך את ההזדמנויות</div>",
                        unsafe_allow_html=True)
        return

    # ===================== מצב תוצאות: אנימציה + קרוסלה =====================
    if mode == "results":
        top_l, top_r = st.columns([3, 1])
        with top_r:
            if st.button("⬅️ חזרה לתפריט", key="results_back_home", use_container_width=True):
                st.session_state.home_mode = "landing"
                st.rerun()

        if st.session_state.get("run_find_scan", False):
            st.session_state.run_find_scan = False
            st.markdown("<div class='home-landing-title' style='text-align:center;'>💰 מחפש עבורך הזדמנויות...</div>", unsafe_allow_html=True)
            _run_find_scan()
            st.rerun()  # הסריקה הסתיימה - ריצה מחדש נקייה שתציג את הקרוסלה

        results = st.session_state.get("home_scan_results")
        st.markdown("<div class='home-landing-title' style='text-align:center;'>🌟 ההזדמנויות שנמצאו עבורך</div>", unsafe_allow_html=True)
        if results is None:
            st.info("טוען...")
        elif not results:
            st.warning("לא נמצאו כרגע שילובים איכותיים (איסוף מוסדי + פונדמנטל חזק). נסה שוב מאוחר יותר.")
        else:
            st.caption(f"נמצאו {len(results)} מניות איכותיות. דפדף בין הכרטיסים ולחץ 'ניתוח מלא' למעבר לתוכנית מסחר.")
            # לחיצה על כרטיס -> Trading Scout (ניתוח Wyckoff + פונדמנטלי + תוכנית מסחר)
            _render_card_carousel(results, key_prefix="find_scan", index_key="scan_card_index", dest_page="📈 Trading Scout")
        return

    # ===================== מצב בדיקה ידנית (הזרימה המקורית המלאה) =====================
    # כותרת + כפתור חזרה לתפריט
    back_l, back_r = st.columns([3, 1])
    with back_r:
        if st.button("⬅️ חזרה לתפריט", key="check_back_home", use_container_width=True):
            st.session_state.home_mode = "landing"
            st.rerun()

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
    is_new_home_handoff = bool(handoff_tkr) and st.session_state.get("handoff_pending", False)
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
        st.session_state.handoff_pending = False  # נוצל - ניקוי חד-פעמי, לא משאיר מפתח ישן מיותר

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

        with st.expander("📊 ציון הסתברות ומפת פאזות Wyckoff (Deep Dive)", expanded=False):
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

        with st.expander("📝 הסבר פשוט למתחילים (בשפה מדוברת)", expanded=False):
            st.markdown(explain_score_simple(result["df"], result["current_phase"], result["current_cis"], result["allowed"]))

        render_explain_score(result["df"], result["current_phase"], result["current_cis"], expanded=False)


def _build_market_universe() -> list:
    """בונה יקום סריקה רחב מאיחוד כל רשימות הטיקרים הקיימות + יקום ברירת המחדל של הסורק."""
    universe = []
    for lst in (GROWTH_TICKERS, VALUE_TICKERS, COMMODITIES_TICKERS):
        for t in lst:
            universe.append(t)
    try:
        from market_scanner import DEFAULT_UNIVERSE
        universe.extend(DEFAULT_UNIVERSE)
    except Exception:
        pass
    seen = set()
    return [t for t in universe if not (t in seen or seen.add(t))]


def _render_market_scanner() -> None:
    """מנוע סריקת שוק עם Early Pruning - סריקה ידנית, progress bar וזמן משוער."""
    st.markdown("#### 🔭 סורק שוק רחב (Market Scanner + Early Pruning)")
    st.caption("סורק מאות מניות במהירות בעזרת גיזום מוקדם: מסנן קודם לפי מחיר/נפח, אז לפי קווים אדומים של Wyckoff, ורק מי ששרד עובר ניתוח פונדמנטלי מלא. מחזיר רק שילובים חזקים.")

    if not MARKET_SCANNER_AVAILABLE:
        st.warning("מנוע הסריקה אינו זמין (חסר market_scanner.py או scout_core).")
        return

    universe = _build_market_universe()
    mode_labels = {
        "fast": f"סריקה מהירה ({min(len(universe), 1200)} מניות, ספים מחמירים)",
        "balanced": f"סריקה מאוזנת ({min(len(universe), 1500)} מניות)",
        "full": f"סריקה מלאה ({len(universe)} מניות)",
    }
    col_mode, col_btn = st.columns([2.5, 1])
    with col_mode:
        mode = st.radio(
            "מצב סריקה",
            options=list(mode_labels.keys()),
            format_func=lambda k: mode_labels[k],
            key="market_scan_mode",
            horizontal=False,
        )
    max_map = {"fast": 1200, "balanced": 1500, "full": 3000}
    eta = MarketScanner.estimate_time(min(len(universe), max_map[mode]), mode)
    with col_btn:
        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
        run_scan = st.button("🔭 הפעל סריקת שוק", type="primary", use_container_width=True, key="run_market_scan")
        st.caption(f"זמן משוער: {eta}")

    # הפעלה אוטומטית כשהגענו מכפתור "סריקת שוק מלאה" שבמסך הבית (חד-פעמי)
    auto_scan = st.session_state.get("auto_run_market_scan", False)
    if auto_scan:
        st.session_state.auto_run_market_scan = False
        run_scan = True

    if run_scan:
        try:
            scanner = MarketScanner(_sc_module)
            prog_bar = st.progress(0.0)
            status = st.empty()

            def _cb(done, total, ticker, stats):
                try:
                    prog_bar.progress(min(1.0, done / max(1, total)))
                    status.caption(
                        f"נסרקו {done}/{total} · עברו: {stats['passed']} · "
                        f"גוזמו (מהיר/Wyckoff/פונדמנטלי): {stats['pruned_quick']}/{stats['pruned_wyckoff']}/{stats['pruned_fundamental']}"
                    )
                except Exception:
                    pass

            with st.spinner(f"סורק שוק במצב '{mode}' ({eta})..."):
                scan_out = scanner.scan_market(
                    mode=mode, max_tickers=max_map[mode], universe=universe,
                    top_n=20, progress_callback=_cb,
                )
            prog_bar.progress(1.0)
            st.session_state.market_scan_results = scan_out
            st.session_state.scan_card_index = 0  # איפוס דפדוף לסריקה חדשה
        except Exception as exc:
            # הגנה קריטית: שגיאה לא צפויה כאן מוצגת מקומית, לא מקריסה את הסקריפט
            st.error(f"⚠️ שגיאה בסריקת השוק: {exc}")
            st.session_state.market_scan_results = None

    scan_out = st.session_state.get("market_scan_results")
    if scan_out:
        stats = scan_out["stats"]
        st.success(
            f"✅ הסריקה הושלמה ב-{scan_out['elapsed']:.1f} שניות · "
            f"נסרקו {stats['scanned']} · נמצאו {len(scan_out['results'])} הזדמנויות חזקות."
        )
        st.caption(
            f"גיזום: מהיר {stats['pruned_quick']} · Wyckoff {stats['pruned_wyckoff']} · "
            f"פונדמנטלי {stats['pruned_fundamental']} · חלש {stats['pruned_weak']} · שגיאות {stats['errors']}"
        )

        results = scan_out["results"]
        if not results:
            st.info("לא נמצאו מניות שעברו את כל מסנני האיכות בסריקה זו.")
        else:
            # תצוגת כרטיסיות עם דפדוף (Carousel) - זהה למסך הבית
            _render_card_carousel(results, key_prefix="mscan", index_key="scan_card_index", dest_page="🏠 בית")

    st.markdown("<hr style='border-color:rgba(255,255,255,0.08); margin:22px 0;'>", unsafe_allow_html=True)


def screen_institutional_map() -> None:
    st.markdown("### 🗺️ Institutional Map - מפת כסף חכם סקטוריאלית")
    st.markdown("מסך זה ממפה את הסקטורים המרכזיים בשוק ומציג את ממוצע ה-**Institutional Accumulation Probability** (הסתברות לצבירה מוסדית) שלהם. הנתונים מתעדכנים על בסיס מניות מובילות בכל סקטור ומוצגים מהגבוה לנמוך.")

    # --- מנוע סריקת שוק רחב (Early Pruning) ---
    _render_market_scanner()

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
                try:
                    if not SCOUT_CORE_AVAILABLE:
                        st.error("מודול הליבה חסר.")
                    elif MARKET_SCANNER_AVAILABLE:
                        # אותו מנוע MarketScanner עם Early Pruning, מוגבל לטיקרים של הסקטור הזה
                        scanner = MarketScanner(_sc_module)
                        prog_sec = st.progress(0.0)
                        status_sec = st.empty()

                        def _sec_cb(done, total, ticker, stats):
                            try:
                                prog_sec.progress(min(1.0, done / max(1, total)))
                                status_sec.caption(f"נסרקו {done}/{total} · עברו: {stats['passed']}")
                            except Exception:
                                pass

                        with st.spinner(f"סורק {len(data['tickers'])} מניות ב{sector} (Early Pruning)..."):
                            sec_out = scanner.scan_market(
                                mode="balanced", max_tickers=len(data["tickers"]),
                                universe=data["tickers"], top_n=6, progress_callback=_sec_cb,
                            )
                        prog_sec.progress(1.0)
                        st.session_state[scan_key] = sec_out["results"]
                    else:
                        with st.spinner(f"סורק {len(data['tickers'])} מניות ב{sector}..."):
                            st.session_state[scan_key] = scan_top_opportunities(data["tickers"], top_n=6, mode="Balanced")
                except Exception as exc:
                    # הגנה קריטית: שגיאה לא צפויה (לדוגמה תקלת רשת חולפת) מוצגת כאן בתוך
                    # ה-expander של הסקטור הזה בלבד - היא לעולם לא מקריסה את כל הסקריפט
                    # ולכן לא יכולה "לזרוק" את המשתמש למסך הבית.
                    st.error(f"⚠️ שגיאה בסריקת {sector}: {exc}")
                    st.session_state[scan_key] = []

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
    is_new_fund_handoff = bool(handoff_fund) and st.session_state.get("handoff_pending", False)
    if is_new_fund_handoff and "fund_tkr" in st.session_state:
        del st.session_state["fund_tkr"]

    default_fund = handoff_fund or "MSFT"
    tkr = st.text_input("הזן סימול לניתוח פונדמנטלי מקיף:", value=default_fund, key="fund_tkr").strip().upper()

    run_fund = st.button("📈 נתח פונדמנטלית", type="primary", use_container_width=True)
    auto_fund = is_new_fund_handoff
    if auto_fund:
        st.session_state.handoff_pending = False  # נוצל - ניקוי חד-פעמי

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
        with st.expander("📐 מכפילים ויחסים מלאים (Deep Dive - מחושבים עצמית, בסדר חשיבות ניתוח ערך)", expanded=False):
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
    # כפתור חזרה לקרוסלה - מוצג רק אם הגענו מקרוסלת "תמצא לי" (יש תוצאות שמורות)
    if st.session_state.get("home_scan_results"):
        _bk_l, _bk_r = st.columns([3, 1])
        with _bk_r:
            if st.button("⬅️ חזור לקרוסלה", key="ts_back_to_carousel", use_container_width=True):
                st.session_state.home_mode = "results"
                go_to_screen("🏠 בית")

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
    is_new_scout_handoff = bool(handoff) and st.session_state.get("handoff_pending", False)
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
        st.session_state.handoff_pending = False  # נוצל - ניקוי חד-פעמי

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
        for _scout_idx, tkr in enumerate(show_scout_tickers):
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

                # === שלב 2: הסבר קצר ואנושי - למה דווקא המניה הזו, עכשיו (Q16: bullets + הסבר נוסף) ===
                if _fund:
                    _why_phase = rec_data.get('current_phase', '')
                    why_bullets = build_fundamental_bullets(_fund, tkr, current_phase=_why_phase)
                    st.markdown(
                        f"<div class='narrative-box'><span class='narrative-title'>🦅 למה דווקא {tkr}, עכשיו?</span>"
                        + "".join(f"<div style='margin:6px 0; line-height:1.6;'>• {b}</div>" for b in why_bullets)
                        + "</div>",
                        unsafe_allow_html=True,
                    )
                    with st.expander(f"📖 הסבר נוסף ל-{tkr} (ניתוח מלא ומלל חופשי)", expanded=False):
                        st.markdown(build_fundamental_narrative(_fund, tkr, _verdict, current_phase=_why_phase))

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
                with st.expander(f"🔍 Drill-down מלא ל-{tkr}: Wyckoff, Smart Money ואסטרטגיית מסחר", expanded=False):
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
    """סרגל ניווט עליון מלווה בגלילה (sticky, מתכווץ) עם המבורגר — כולל כפתורי חזור/למעלה וכפתור חזור צף."""
    st.markdown("<div id='page-top'></div>", unsafe_allow_html=True)
    st.markdown("<div id='sticky-nav-anchor'>", unsafe_allow_html=True)

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

    # --- כפתורים מלווים: חזור למסך הקודם + חזרה לראש העמוד (Q4: a+c) ---
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
    st.markdown("</div>", unsafe_allow_html=True)  # /sticky-nav-anchor

    # --- כפתור חזור צף בפינה התחתונה (Q3) - נגיש מכל גלילה ---
    if has_history:
        st.markdown(
            "<div class='float-back-wrap'><a href='#page-top' "
            "onclick=\"try{var h=window.parent.document.querySelectorAll('button'); "
            "for(var i=0;i<h.length;i++){if(h[i].innerText.indexOf('חזור למסך הקודם')>-1){h[i].click();break;}}}catch(e){} return false;\">"
            "⬅️ חזור</a></div>",
            unsafe_allow_html=True,
        )


def main() -> None:
    init_session_state()
    _process_nav_request()   # מעבד בקשות ניווט לפני יצירת widgets - מונע StreamlitAPIException
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
