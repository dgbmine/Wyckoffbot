"""
============================================================
INSTITUTIONAL SCOUT PRO — WYCKOFF ANALYST EDITION V16.0
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
        calculate_advanced_metrics, calculate_phase_followthrough, explain_score_simple
    )
    SCOUT_CORE_AVAILABLE = True
except ImportError:
    try:
        from scout import (
            clean_filename, get_data, calculate_optimal_threshold, check_phase_entry_allowed,
            BacktestConfig, FactorEngine, run_wyckoff_anchored_backtest, explain_score,
            calculate_advanced_metrics, calculate_phase_followthrough, explain_score_simple
        )
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
        padding: 1.15rem 1.4rem; border-radius: 22px;
        background: linear-gradient(135deg, rgba(7,14,25,0.88), rgba(13,25,43,0.92));
        box-shadow: 0 18px 44px rgba(0,0,0,.28); margin-bottom: 1rem;
        border: 1px solid rgba(125,155,190,0.18);
    }
    .main-header h1 { margin: 0; font-size: 2.1rem; color: #eaf4ff; font-weight: 700; }
    .main-header p { color: #9db0c9; font-size: 1.05rem; }
    
    [data-testid="stMetric"] {
        background: rgba(15, 23, 42, 0.95) !important;
        border: 1px solid rgba(56, 189, 248, 0.3) !important;
        border-radius: 12px;
        padding: 1rem;
    }
    [data-testid="stMetricValue"] {
        color: #38bdf8 !important;
        font-weight: 700 !important;
    }
    [data-testid="stMetricLabel"] {
        color: #f1f5f9 !important;
        font-weight: 500 !important;
    }
    [data-testid="stMetricDelta"] {
        color: #34d399 !important;
    }
    
    /* Cards for Trading Scout */
    .scout-card {
        background: rgba(15, 23, 42, 0.8);
        border: 1px solid rgba(56, 189, 248, 0.2);
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 20px;
    }
    .scout-title { color: #e0f2fe; font-size: 1.5rem; font-weight: 700; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 10px; margin-bottom: 15px;}
    .scout-prob { font-size: 2.2rem; font-weight: bold; color: #38bdf8; text-align: center; margin: 10px 0; }
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

def _run_scan_row(engine, ticker: str, scan_th: float):
    df = get_cached_data(ticker, period="1y")
    if df is None or len(df) <= 60:
        return None
    factors = engine.compute(df)
    cis = engine.composite_cis(factors, df)
    phase = engine.get_wyckoff_phase(df)
    score = float(cis.iloc[-1])
    if score < scan_th:
        return None
    allowed = check_phase_entry_allowed(str(phase.iloc[-1]), "Balanced")
    return {"Ticker": ticker, "Score": round(score, 1), "Phase": str(phase.iloc[-1]), "Allowed?": "✅ כן" if allowed else "❌ לא", "_df": df}

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
                    
                if is_bearish:
                    html = f"""
                    <div style="display:flex; justify-content:space-around; align-items:center; background:#1e293b; padding:20px; border-radius:12px; margin-top:10px;">
                        <div style="text-align:center; padding:15px; border-radius:8px; width:45%; transition:0.3s; {get_bg(['Distribution', 'Supply'])}">הפצה (Distribution)<br><span style="font-size:0.85em">מוסדיים מוכרים</span></div>
                        <div style="color:#475569; font-size:1.8em;">➔</div>
                        <div style="text-align:center; padding:15px; border-radius:8px; width:45%; transition:0.3s; {get_bg('Markdown')}">ירידות (Markdown)<br><span style="font-size:0.85em">פיזור סחורה</span></div>
                    </div>
                    """
                else:
                    html = f"""
                    <div style="display:flex; justify-content:space-between; align-items:center; background:#1e293b; padding:15px 10px; border-radius:12px; margin-top:10px; font-size:0.9em;">
                        <div style="text-align:center; padding:10px 5px; border-radius:8px; width:18%; transition:0.3s; {get_bg(['Phase A'])}">שלב A<br><span style="font-size:0.8em">בלימה</span></div>
                        <div style="color:#475569;">➔</div>
                        <div style="text-align:center; padding:10px 5px; border-radius:8px; width:18%; transition:0.3s; {get_bg(['Phase B', 'Accumulation'])}">שלב B<br><span style="font-size:0.8em">בניית כוח</span></div>
                        <div style="color:#475569;">➔</div>
                        <div style="text-align:center; padding:10px 5px; border-radius:8px; width:18%; transition:0.3s; {get_bg(['Phase C', 'Spring'])}">שלב C<br><span style="font-size:0.8em">ניעור</span></div>
                        <div style="color:#475569;">➔</div>
                        <div style="text-align:center; padding:10px 5px; border-radius:8px; width:18%; transition:0.3s; {get_bg(['Phase D', 'Re-accumulation'])}">שלב D<br><span style="font-size:0.8em">פריצה</span></div>
                        <div style="color:#475569;">➔</div>
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

def screen_scanner() -> None:
    st.markdown("### 🔎 Market Scanner")
    st.info("⚠️ **הבהרה:** המערכת היא כלי עזר אנליטי בלבד ואינה מהווה ייעוץ השקעות. ממוקד באיתור הסתברות גבוהה לצבירה מוסדית.")
    sector_name = st.selectbox("בחר סקטור לסריקה", list(SECTOR_MAP.keys()))
    scan_limit = st.slider("כמות מניות לסריקה", 5, 50, 10)
    scan_th = st.slider("סף מינימלי לתוצאה (CIS)", 40, 95, 60)

    if st.button("🚀 התחל סריקה מוסדית", type="primary"):
        results = []
        engine = FactorEngine(BacktestConfig())
        for ticker in SECTOR_MAP[sector_name][:scan_limit]:
            row = _run_scan_row(engine, ticker, scan_th)
            if row:
                results.append(row)
        if results:
            top = sorted(results, key=lambda r: r["Score"], reverse=True)[0]
            st.success(f"נמצאו {len(results)} מניות")
            st.dataframe(pd.DataFrame([{k: v for k, v in r.items() if k != "_df"} for r in results]))
            st.markdown(f"#### המובילה בהסתברות לצבירה: {top['Ticker']}")
        else:
            st.warning("אף מניה לא עברה את סף ה-CIS הנוכחי.")

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

def screen_trading_scout() -> None:
    st.markdown("### 📈 Trading Scout - תכנון עסקאות ובדיקת הסתברויות")
    st.info("⚠️ **הבהרה קריטית:** זהו כלי עזר אנליטי אוטומטי. הדגש הוא על ההסתברות לאיסוף מוסדי אמיתי. לא משמש ייעוץ.")
    
    # Mode selector
    mode = st.radio("בחר פרופיל הסתברות (Risk Mode):", ["Conservative (שמרני)", "Balanced (מאוזן)", "Optimistic (אופטימי)"], index=1, horizontal=True)
    mode_map = {"Conservative (שמרני)": "Conservative", "Balanced (מאוזן)": "Balanced", "Optimistic (אופטימי)": "Optimistic"}
    selected_mode = mode_map[mode]

    cols_input = st.columns(4)
    tickers_input = []
    default_tickers = ["NVDA", "AAPL", "META", "TSLA"]
    for i in range(4):
        val = cols_input[i].text_input(f"טיקר {i+1}", value=default_tickers[i], key=f"ts_ticker_{i}").strip().upper()
        tickers_input.append(val)
        
    if st.button("💡 קבל המלצות לכל הטיקרים", type="primary", use_container_width=True):
        if not SCOUT_CORE_AVAILABLE:
            st.error("מודול הליבה חסר, לא ניתן לייצר המלצה.")
            return
            
        from trading_scout import get_trading_recommendation
        
        # UI rendering 2x2 Grid
        for i in range(0, 4, 2):
            row_cols = st.columns(2)
            for j in range(2):
                idx = i + j
                if idx < 4 and tickers_input[idx]:
                    tkr = tickers_input[idx]
                    with row_cols[j]:
                        with st.spinner(f"מנתח {tkr}..."):
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
                            "STRONG BUY": "#16a34a", "BUY": "#22c55e",
                            "HOLD": "#eab308", "SELL": "#f97316", "STRONG SELL": "#dc2626"
                        }
                        color = color_map.get(rec, "#94a3b8")
                        
                        st.markdown(f"""
                        <div class='scout-card'>
                            <div class='scout-title'>
                                {tkr} <span style='float:left; color:{color};'>{rec}</span>
                            </div>
                            <p style='text-align:center; margin-bottom:0;'>Institutional Accumulation Probability</p>
                            <div class='scout-prob'>{rec_data['prob_engine']['accumulation_chance']}%</div>
                            <p style='text-align:center; color:#9db0c9; font-size:0.9em; margin-top:-5px;'>Wyckoff Phase: {rec_data['current_phase']}</p>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        t_cols = st.columns(2)
                        with t_cols[0]:
                            st.markdown("**Wyckoff Probability Engine**")
                            st.caption(f"🚀 פריצה ב-30 יום: **{rec_data['prob_engine']['breakout_30d']}%**")
                            st.caption(f"📉 סיכון להפצה: **{rec_data['prob_engine']['distribution_risk']}%**")
                        with t_cols[1]:
                            st.markdown("**Smart Money Dashboard**")
                            for k, v in rec_data['dashboard'].items():
                                st.caption(f"{k}: {v}")
                                
                        st.markdown(f"**Failure Detection (הגנה ממלכודות):**")
                        for warn in rec_data['failure_warnings']:
                            st.caption(warn)
                            
                        with st.expander("📝 תוכנית מסחר מלאה (Trading Plan)", expanded=False):
                            st.markdown(f"**פעולה נדרשת:** {rec_data['action']}")
                            st.markdown(f"**מחיר נוכחי:** ${rec_data['entry_price']:.2f}")
                            st.markdown(f"**Stop Loss:** ${rec_data['stop_loss_price']:.2f} ({rec_data['stop_loss_pct']:.1f}%)")
                            st.markdown(f"**Take Profit 1:** ${rec_data['tp1_price']:.2f} (+{rec_data['tp1_pct']:.1f}%)")
                            st.markdown(f"**Take Profit 2:** ${rec_data['tp2_price']:.2f} (+{rec_data['tp2_pct']:.1f}%)")
                            st.markdown(f"**יחס סיכוי/סיכון:** {rec_data['rr_ratio']}")
                            st.markdown(f"**טווח זמן אופטימלי:** {rec_data['timeframe']}")
                            st.markdown("---")
                            st.markdown(f"**הסבר:** {rec_data['simple_explain']}")
                            
                        with st.expander("⏮️ Wyckoff Replay Engine (היסטוריה דומה)", expanded=False):
                            st.markdown("מצאתי תרחישים מוסדיים דומים בעבר על סמך ציון האיסוף:")
                            for rep in rec_data['replay']:
                                st.markdown(f"- {rep}")

def screen_institutional_map() -> None:
    st.markdown("### 🗺️ Institutional Map - מפת כסף חכם סקטוריאלית")
    st.markdown("מסך זה ממפה את הסקטורים המרכזיים בשוק ומציג את ממוצע ה-**Institutional Accumulation Probability** (הסתברות לצבירה מוסדית) שלהם בהתבסס על מניות מובילות בכל סקטור.")
    
    MAP_SECTORS = {
        "טכנולוגיה (Technology)": ["AAPL", "MSFT", "NVDA", "AVGO", "CRM"],
        "סמיקונדקטורס (Semiconductors)": ["AMD", "TXN", "QCOM", "INTC", "SMCI"],
        "פיננסים (Financials)": ["JPM", "V", "MA", "BAC", "GS"],
        "בריאות (Healthcare)": ["JNJ", "UNH", "LLY", "MRK", "ABBV"],
        "אנרגיה וסחורות (Energy & Commodities)": ["XOM", "CVX", "GLD", "SLV", "COP"]
    }
    
    if st.button("🗺️ טען מפה מוסדית", type="primary"):
        with st.spinner("סורק מניות מובילות בכל סקטור לחילוץ נתוני איסוף..."):
            engine = FactorEngine(BacktestConfig())
            sector_results = {}
            
            for sector, tickers in MAP_SECTORS.items():
                sector_cis = []
                for t in tickers:
                    df = get_cached_data(t, period="6mo")
                    if df is not None and not df.empty and len(df) > 40:
                        factors = engine.compute(df)
                        cis = engine.composite_cis(factors, df)
                        sector_cis.append(float(cis.iloc[-1]))
                
                if sector_cis:
                    avg_cis = sum(sector_cis) / len(sector_cis)
                    sector_results[sector] = avg_cis
            
            if sector_results:
                cols = st.columns(len(sector_results))
                for i, (sector, avg_cis) in enumerate(sector_results.items()):
                    with cols[i]:
                        color = "#16a34a" if avg_cis >= 65 else ("#eab308" if avg_cis >= 50 else "#dc2626")
                        st.markdown(f"""
                        <div style='background:rgba(15, 23, 42, 0.8); border-top:4px solid {color}; padding:15px; border-radius:8px; text-align:center;'>
                            <h4 style='margin:0; font-size:1.1rem; color:#e0f2fe;'>{sector}</h4>
                            <p style='font-size:0.9rem; color:#9db0c9; margin-top:5px;'>Accumulation Index</p>
                            <h2 style='color:{color}; margin:0;'>{avg_cis:.1f}%</h2>
                        </div>
                        """, unsafe_allow_html=True)
                        
                st.markdown("---")
                st.info("💡 **תובנה:** סקטורים עם אינדקס מעל 65% נתונים כעת תחת איסוף מוסדי כבד ויש לחפש בהם הזדמנויות לונג.")
            else:
                st.error("לא ניתן היה לטעון נתונים עבור המפה.")

def main() -> None:
    init_session_state()
    inject_css()

    st.markdown(
        '<div class="main-header"><h1>📈 Wyckoff Institutional Analyst</h1>'
        '<p>מערכת זיהוי דפוסי איסוף, הפצה וכניסת כסף חכם | Cloud Run Edition</p></div>',
        unsafe_allow_html=True
    )

    # סדר הטאבים המבוקש
    tabs = st.tabs(["🧠 ML Trainer", "👁️ Monitor", "📊 Backtest", "📈 Trading Scout", "🗺️ Institutional Map", "🏠 Home (Wyckoff Analyst)"])
    screen_fns = [screen_ml_trainer, screen_monitor, screen_backtest, screen_trading_scout, screen_institutional_map, screen_home]
    
    for tab, fn in zip(tabs, screen_fns):
        with tab:
            fn()

if __name__ == "__main__":
    main()
