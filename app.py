"""
============================================================
INSTITUTIONAL SCOUT PRO V16.10
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
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import yfinance as yf

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("scout")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path: sys.path.append(BASE_DIR)

_TMP_ROOT = "/tmp/scout" if os.environ.get("K_SERVICE") else BASE_DIR

try:
    from scout_core import (
        get_data, BacktestConfig, FactorEngine, run_wyckoff_anchored_backtest,
        explain_score_simple, build_smart_money_dashboard, get_fundamental_data
    )
    SCOUT_CORE_AVAILABLE = True
except ImportError:
    SCOUT_CORE_AVAILABLE = False
    def get_fundamental_data(t, cis_score=None, current_phase=""): return {}

st.set_page_config(layout="wide", page_title="Wyckoff Institutional Analyst", page_icon="📈", initial_sidebar_state="collapsed")

# Hide default sidebar globally
st.markdown("""
    <style>
        [data-testid="collapsedControl"] { display: none !important; }
        section[data-testid="stSidebar"] { display: none !important; }
    </style>
""", unsafe_allow_html=True)

GROWTH_TICKERS = ["AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO"]
VALUE_TICKERS = ["BRK-B","JPM","JNJ","V","UNH","PG","HD","MRK"]

def get_cached_data_and_time(ticker: str, period: str = "1y") -> tuple:
    df = get_data(ticker, period) if SCOUT_CORE_AVAILABLE else None
    if df is not None and not df.empty:
        curr_price = df['Close'].iloc[-1]
        last_time = df.index[-1].strftime('%d.%m.%Y %H:%M')
        return df, curr_price, last_time
    return None, 0.0, "N/A"

def _compute_wyckoff(ticker: str):
    df, _, _ = get_cached_data_and_time(ticker)
    if df is None: return None
    engine = FactorEngine(BacktestConfig())
    factors = engine.compute(df)
    phases = engine.get_wyckoff_phase(df)
    cis = engine.composite_cis(factors, df)
    return {
        "df": df, "factors": factors, "cis": cis,
        "current_phase": str(phases.iloc[-1]), "current_cis": float(cis.iloc[-1])
    }

def navigate_to(page: str, ticker: Optional[str] = None):
    st.session_state.current_page = page
    if ticker: st.session_state.current_ticker = ticker.strip().upper()
    st.rerun()

def render_top_bar():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Hebrew:wght@400;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'IBM Plex Sans Hebrew', sans-serif; direction: rtl; text-align: right; background: #0b1220; color: #d9e6f2; }
    
    .top-menu-bar { display:flex; justify-content:space-between; align-items:center; background:linear-gradient(135deg, rgba(7,14,25,0.9), rgba(13,25,43,0.95)); padding:15px 25px; border-radius:15px; border:1px solid rgba(125,155,190,0.2); margin-bottom:20px; box-shadow:0 8px 30px rgba(0,0,0,0.3); }
    .top-title { font-size:1.8rem; font-weight:700; color:#eaf4ff; margin:0; }
    .top-subtitle { font-size:1rem; color:#9db0c9; margin:0; }
    
    .stepper-container { display: flex; justify-content: space-between; align-items: center; background: #0f172a; padding: 15px 30px; border-radius: 16px; border: 1px solid rgba(56, 189, 248, 0.3); margin-bottom: 30px; }
    .step-item { font-size: 1.1rem; font-weight: 600; }
    .step-active { color: #38bdf8; text-shadow: 0 0 10px rgba(56,189,248,0.4); }
    .step-inactive { color: #475569; }
    
    .metric-card { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 15px; text-align: center; height: 100%; display: flex; flex-direction: column; justify-content: center; }
    .metric-label { color: #94a3b8; font-size: 0.9rem; margin-bottom: 5px; font-weight: 600; }
    .metric-value { color: #f8fafc; font-size: 1.8rem; margin: 0; font-weight: bold; }
    
    .hot-card-container { background: linear-gradient(145deg, #1e293b, #0f172a); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 18px; margin-bottom: 15px; text-align:center; transition: 0.2s; }
    .hot-card-container:hover { transform: translateY(-4px); border-color: #38bdf8; }
    .ticker-price-badge { font-size:1.6rem; font-weight:bold; color:#fff; display:block; margin:5px 0; }
    .ticker-time-badge { font-size:0.75rem; color:#94a3b8; display:block; }
    
    .menu-button-style button {
        background: transparent !important;
        border: 1px solid rgba(255,255,255,0.2) !important;
        color: #f8fafc !important;
        font-size: 1.6rem !important;
        border-radius: 8px !important;
        transition: 0.3s;
    }
    .menu-button-style button:hover { border-color: #38bdf8 !important; color: #38bdf8 !important; background: rgba(56,189,248,0.1) !important; }
    </style>
    """, unsafe_allow_html=True)
    
    col_title, col_menu = st.columns([6, 1])
    with col_title:
        st.markdown("<div class='top-menu-bar'><div style='display:flex; flex-direction:column;'><h1 class='top-title'>📈 Wyckoff Institutional Analyst</h1><p class='top-subtitle'>(הזן מניות משלך למעקב מוסדי חכם)</p></div></div>", unsafe_allow_html=True)
    with col_menu:
        st.markdown("<div style='margin-top:20px;' class='menu-button-style'></div>", unsafe_allow_html=True)
        # Mobile Menu Toggle using session state
        if st.button("☰", key="mobile_menu_btn", use_container_width=True):
            st.session_state.menu_open = not st.session_state.get("menu_open", False)

    # Custom Hamburger Overlay Menu
    if st.session_state.get("menu_open", False):
        with st.container():
            st.markdown("<div style='background:linear-gradient(145deg, #1e293b, #0f172a); padding:20px; border-radius:15px; border:1px solid #38bdf8; margin-bottom:25px; box-shadow:0 8px 30px rgba(0,0,0,0.5);'>", unsafe_allow_html=True)
            st.markdown("<h3 style='margin-top:0; color:#e0f2fe;'>🧭 תפריט ניווט ראשי</h3>", unsafe_allow_html=True)
            c1, c2, c3, c4 = st.columns(4)
            if c1.button("🏠 מסך הבית וסריקה", use_container_width=True):
                st.session_state.menu_open = False; navigate_to("Home")
            if c2.button("🔍 ניתוח נכס מעמיק", use_container_width=True):
                st.session_state.menu_open = False; navigate_to("Deep Analysis")
            if c3.button("📈 בניית תוכנית מסחר", use_container_width=True):
                st.session_state.menu_open = False; navigate_to("Trading Scout")
            if c4.button("📊 Backtest היסטורי", use_container_width=True):
                st.session_state.menu_open = False; navigate_to("Backtest")
            st.markdown("</div>", unsafe_allow_html=True)

def render_stepper():
    page = st.session_state.current_page
    c1 = "step-active" if page == "Home" else "step-inactive"
    c2 = "step-active" if page == "Deep Analysis" else "step-inactive"
    c3 = "step-active" if page == "Trading Scout" else "step-inactive"
    st.markdown(f"""
    <div class="stepper-container">
        <div class="step-item {c1}">1️⃣ חיפוש וסריקה</div>
        <div style='color:#334155;'>➔</div>
        <div class="step-item {c2}">2️⃣ ניתוח עומק פונדמנטלי וטכני</div>
        <div style='color:#334155;'>➔</div>
        <div class="step-item {c3}">3️⃣ בניית תוכנית מסחר</div>
    </div>
    """, unsafe_allow_html=True)

def render_price_header(ticker: str, price: float, time_str: str, align: str = "center"):
    st.markdown(f"""
    <div style='text-align:{align}; margin-bottom:10px; background: rgba(0,0,0,0.2); padding: 10px 20px; border-radius: 12px; display: inline-block; border: 1px solid rgba(255,255,255,0.05);'>
        <span style='font-size: 1.1rem; color: #94a3b8; font-weight:600; display:block;'>מחיר נוכחי</span>
        <span class='ticker-price-badge'>${price:,.2f}</span>
        <span class='ticker-time-badge'>מעודכן ל: {time_str}</span>
    </div>
    """, unsafe_allow_html=True)

def screen_home() -> None:
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("⚡ סקירה מהירה\n(מניות אידיאליות וסקטורים)", use_container_width=True): st.session_state.home_view = "quick"
    with c2:
        if st.button("🌐 סקירת שוק\n(סורק חכם)", use_container_width=True): st.session_state.home_view = "scan"
    with c3:
        if st.button("🔎 חיפוש מניה\n(ספציפית)", use_container_width=True): st.session_state.home_view = "search"

    st.markdown("<hr style='border-color: rgba(255,255,255,0.08); margin:25px 0;'>", unsafe_allow_html=True)
    
    view = st.session_state.home_view
    if view == "quick":
        st.markdown("#### 🗺️ זרימת הון מוסדית בסקטורים נבחרים")
        sectors = {"טכנולוגיה (XLK)": "XLK", "פיננסים (XLF)": "XLF", "בריאות (XLV)": "XLV", "שבבים (SMH)": "SMH"}
        cols_sec = st.columns(4)
        for i, (name, tk) in enumerate(sectors.items()):
            with cols_sec[i]:
                res = _compute_wyckoff(tk)
                _, price, t_str = get_cached_data_and_time(tk)
                cis = res['current_cis'] if res else 0
                color = "#16a34a" if cis >= 50 else "#dc2626"
                st.markdown(f"""
                <div style='background:rgba(255,255,255,0.03); padding:15px; border-radius:12px; border-bottom:4px solid {color}; text-align:center;'>
                    <span style='color:#94a3b8; font-size:1rem; font-weight:600;'>{name}</span>
                    <span class='ticker-price-badge' style='font-size:1.3rem;'>${price:.2f}</span>
                    <span style='color:{color}; font-size:1.4rem; font-weight:bold;'>CIS: {cis:.1f}</span>
                    <span class='ticker-time-badge'>מעודכן ל: {t_str}</span>
                </div>
                """, unsafe_allow_html=True)
                
        st.markdown("<br>#### 🎯 מניות אידיאליות לכניסה כרגע", unsafe_allow_html=True)
        st.caption("מניות אלו מפגינות איסוף מוסדי מובהק (CIS ≥ 65) ונמצאות בפאזת התבססות חיובית (לא Distribution).")
        
        ideal_found = []
        with st.spinner("סורק מניות פוטנציאליות לכניסה אופטימלית..."):
            for tk in ["NVDA", "AAPL", "MSFT", "TSLA", "META", "AMZN", "AMD", "PLTR", "CRM", "AVGO"]:
                res = _compute_wyckoff(tk)
                if res and res['current_cis'] >= 65:
                    phase = res['current_phase']
                    if any(p in phase for p in ["Phase C", "Spring", "Phase D", "Phase E", "Markup", "LPS", "Re-accumulation"]):
                        ideal_found.append(tk)
                if len(ideal_found) >= 4: break
        
        if not ideal_found:
            st.info("לא נמצאו כרגע מניות שעומדות בקריטריונים הקשיחים (CIS > 65 ופאזה טכנית חיובית).")
        else:
            cols_hot = st.columns(min(len(ideal_found), 4))
            for i, tk in enumerate(ideal_found):
                with cols_hot[i]:
                    res = _compute_wyckoff(tk)
                    _, price, t_str = get_cached_data_and_time(tk)
                    cis = res['current_cis']
                    st.markdown(f"""
                    <div class='hot-card-container' style='border-top:3px solid #16a34a;'>
                        <h3 style='margin:0; color:#f8fafc; font-size:1.8rem;'>{tk}</h3>
                        <span class='ticker-price-badge'>${price:.2f}</span>
                        <span class='ticker-time-badge'>מעודכן: {t_str}</span>
                        <h2 style='margin:10px 0 0 0; color:#16a34a;'>CIS: {cis:.1f}</h2>
                        <p style='margin:5px 0 10px 0; color:#cbd5e1; font-size:0.85rem; background:rgba(255,255,255,0.05); padding:3px 8px; border-radius:10px;'>{res['current_phase']}</p>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button(f"נתח את {tk} ➔", key=f"h_{tk}", use_container_width=True):
                        navigate_to("Deep Analysis", tk)
                        
    elif view == "search":
        col_s1, col_s2, _ = st.columns([3, 1, 2])
        with col_s1: search_ticker = st.text_input("הזן סימול לניתוח:", value="").strip().upper()
        with col_s2:
            st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
            if st.button("🚀 נתח עכשיו", use_container_width=True, type="primary"):
                if search_ticker: navigate_to("Deep Analysis", search_ticker)
                
    elif view == "scan":
        st.info("כלי הסריקה מאתר מניות עם שילוב של איסוף ותמחור הוגן (בפיתוח).")
        st.markdown("כדי להשתמש בסורק, מומלץ לחפש טיקר בודד כרגע או לעבור לסקירה מהירה.")

def screen_deep_analysis() -> None:
    ticker = st.session_state.current_ticker
    _, price, t_str = get_cached_data_and_time(ticker)
    
    col_t, col_p, col_b1, col_b2 = st.columns([1.5, 1.5, 1, 1])
    with col_t:
        st.markdown(f"<h2 style='margin:0; padding-top:10px;'>🔍 ניתוח מעמיק: {ticker}</h2>", unsafe_allow_html=True)
    with col_p:
        render_price_header(ticker, price, t_str, align="center")
    with col_b1:
        st.markdown("<div style='margin-top:15px;'></div>", unsafe_allow_html=True)
        if st.button("🔄 חזור לחיפוש", use_container_width=True): navigate_to("Home")
    with col_b2:
        st.markdown("<div style='margin-top:15px;'></div>", unsafe_allow_html=True)
        if st.button("▶ לתוכנית מסחר", type="primary", use_container_width=True): navigate_to("Trading Scout")
            
    st.markdown("---")
    
    with st.spinner(f"מפעיל סינתזה פונדמנטלית וטכנית (Ackman Style) עבור {ticker}..."):
        wyckoff_res = _compute_wyckoff(ticker)
        if wyckoff_res is None:
            st.error(f"אין נתונים מספיקים עבור {ticker}.")
            return
        fdata = get_fundamental_data(ticker, cis_score=wyckoff_res["current_cis"], current_phase=wyckoff_res["current_phase"])

    c_left, c_right = st.columns([1, 1])
    with c_left:
        val_color = fdata.get('valuation_color', '#fff')
        st.markdown(f"""
        <div style='background:#1e293b; padding:25px; border-radius:16px; border-right:6px solid {val_color}; height:100%; display:flex; flex-direction:column; justify-content:center;'>
            <p style='margin:0; color:#94a3b8; text-transform:uppercase; font-size:0.95rem; font-weight:700;'>אבחון פונדמנטלי קשיח (Sector Benchmarked)</p>
            <h2 style='margin:8px 0 15px 0; color:#f8fafc; font-size:2.4rem;'>תמחור: <span style='color:{val_color};'>{fdata.get('valuation', 'N/A')}</span></h2>
            <p style='margin:0; font-size:1.15rem; color:#e2e8f0; font-weight:500; line-height:1.6; padding-right:10px; border-right:3px solid rgba(255,255,255,0.2);'>{fdata.get('synthesis', '')}</p>
        </div>
        """, unsafe_allow_html=True)
    with c_right:
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number", value=wyckoff_res["current_cis"],
            title={'text': "כוח איסוף מוסדי (Wyckoff CIS)", 'font': {'color': "#d9e6f2", 'size': 18}},
            number={'font': {'color': "#d9e6f2", 'size': 40}},
            gauge={'axis': {'range': [0, 100], 'tickcolor': "white"}, 'bar': {'color': "rgba(255,255,255,0.4)"}, 'steps': [{'range':[0,40],'color':"#dc2626"}, {'range':[40,65],'color':"#eab308"}, {'range':[65,100],'color':"#16a34a"}]}
        ))
        fig_gauge.update_layout(height=200, margin=dict(l=20, r=20, t=30, b=10), paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_gauge, use_container_width=True)

    st.markdown("#### 📊 מטריקות תזרים וערך (Cash Flow is Reality)")
    expl = fdata.get('explanations', {})
    
    r1c1, r1c2, r1c3, r1c4 = st.columns(4)
    def m_card(col, lbl, val, pop_txt):
        with col:
            st.markdown(f"<div class='metric-card'><p class='metric-label'>{lbl}</p><h3 class='metric-value'>{val}</h3></div>", unsafe_allow_html=True)
            if pop_txt:
                with st.popover("מה זה? ולמה זה חשוב פה?"): st.write(pop_txt)

    m_card(r1c1, "Op. Cash Flow", fdata.get("ocf"), expl.get("ocf", ""))
    m_card(r1c2, "Free Cash Flow", fdata.get("fcf"), expl.get("fcf", ""))
    m_card(r1c3, "Rev Growth YoY", fdata.get("rev_growth"), expl.get("rev_growth", ""))
    m_card(r1c4, "Op. Margin", fdata.get("op_margin"), expl.get("op_margin", ""))
    
    r2c1, r2c2, r2c3, r2c4 = st.columns(4)
    m_card(r2c1, "Net Debt/EBITDA", fdata.get("net_debt_ebitda"), expl.get("net_debt", ""))
    m_card(r2c2, "Fwd P/E", fdata.get("pe_forward"), expl.get("pe", ""))
    m_card(r2c3, "Sector", fdata.get("sector"), "")
    m_card(r2c4, "Next Earnings", fdata.get("next_earnings"), "")

    st.markdown("---")
    st.markdown("#### 📉 התנהגות המחיר (Price Action) ואזורי נזילות")
    
    chart_df = wyckoff_res["df"].iloc[-150:] 
    fig_chart = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
    fig_chart.add_trace(go.Candlestick(x=chart_df.index, open=chart_df['Open'], high=chart_df['High'], low=chart_df['Low'], close=chart_df['Close'], name="Price"), row=1, col=1)
    colors = ['#16a34a' if c >= o else '#dc2626' for c, o in zip(chart_df['Close'], chart_df['Open'])]
    fig_chart.add_trace(go.Bar(x=chart_df.index, y=chart_df['Volume'], marker_color=colors, name="Volume"), row=2, col=1)
    
    cp_marker = wyckoff_res['current_phase']
    marker_color = "#16a34a" if any(x in cp_marker for x in ["Phase C", "Spring", "Phase D", "Phase E", "Markup", "Re-accumulation", "LPS"]) else ("#eab308" if "TRANSITION" in cp_marker else "#dc2626")
    
    fig_chart.add_annotation(
        x=chart_df.index[-1], y=chart_df['Low'].iloc[-1], text=f"📌 {cp_marker}",
        showarrow=True, arrowhead=2, ax=0, ay=45, font=dict(color="white", size=11, weight="bold"),
        bgcolor=marker_color, bordercolor="rgba(255,255,255,0.7)", borderwidth=1, borderpad=3, opacity=0.95
    )
    fig_chart.update_layout(height=450, margin=dict(l=0, r=0, t=10, b=0), xaxis_rangeslider_visible=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig_chart, use_container_width=True)

def screen_trading_scout() -> None:
    ticker = st.session_state.current_ticker
    _, price, t_str = get_cached_data_and_time(ticker)
    
    col_t, col_p, col_b1, col_b2 = st.columns([1.5, 1.5, 1, 1])
    with col_t:
        st.markdown(f"<h3 style='margin:0; padding-top:15px;'>📈 תכנון עסקאות: {ticker}</h3>", unsafe_allow_html=True)
    with col_p:
        render_price_header(ticker, price, t_str, align="center")
    with col_b1:
        st.markdown("<div style='margin-top:15px;'></div>", unsafe_allow_html=True)
        if st.button("🔄 חזור לניתוח", use_container_width=True): navigate_to("Deep Analysis")
    with col_b2:
        st.markdown("<div style='margin-top:15px;'></div>", unsafe_allow_html=True)
        mode = st.selectbox("רגישות פוזיציה:", ["Conservative", "Balanced", "Optimistic"], index=1, label_visibility="collapsed")
            
    st.markdown("---")
    
    from trading_scout import get_trading_recommendation
    with st.spinner(f"מייצר תוכנית מסחר עקבית (פונדמנטלי + טכני) עבור {ticker}..."):
        try: rec_data = get_trading_recommendation(ticker, mode=mode)
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
    is_trap = any("Value Trap" in w for w in failure_list) or any("רעילה" in w for w in failure_list) or any("סכין נופלת" in w for w in failure_list)
    alert_border = "#22c55e" if is_safe else ("#ef4444" if is_trap else "#f59e0b")
    alert_bg = "rgba(34, 197, 94, 0.05)" if is_safe else ("rgba(239, 68, 68, 0.08)" if is_trap else "rgba(245, 158, 11, 0.08)")
    
    smart_money_html = "".join([f"<div class='scout-list-item'><span>{k}:</span> <span style='font-weight:600; color:#f8fafc;'>{v}</span></div>" for k, v in rec_data['dashboard'].items()])
    failure_html = "".join([f"<span class='scout-alert-text'>{'⚠️' if not is_safe else '🛡️'} {warn}</span>" for warn in failure_list])
    
    card_parts = [
        "<div class='scout-wrapper'><div class='scout-card'>",
        "<div class='scout-header'>",
        f"<h3 class='scout-title'>הכרעת מערכת (Verdict)</h3>",
        f"<span class='scout-badge' style='color:{color}; border-color: {color}50;'>{rec}</span>",
        "</div>",
        f"<div style='text-align:center; font-size:1.15rem; color:#cbd5e1; margin-bottom:20px; font-weight:600; padding:15px; background:rgba(255,255,255,0.05); border-radius:12px;'>💡 {rec_data.get('action', '')}</div>",
        
        "<div class='scout-stats-grid'>",
        "<div class='scout-stat-box'><div class='scout-section-title'>👁️ Smart Money Flow</div>",
        smart_money_html,
        "</div>",
        
        "<div class='scout-stat-box'><div class='scout-section-title'>🏢 סיכום עומק פונדמנטלי</div>",
        f"<div class='scout-list-item'><span>Free Cash Flow:</span> <span style='font-weight:bold;'>{rec_data.get('fundamental', {}).get('fcf', 'N/A')}</span></div>",
        f"<div class='scout-list-item'><span>Net Debt / EBITDA:</span> <span style='font-weight:bold;'>{rec_data.get('fundamental', {}).get('net_debt_ebitda', 'N/A')}</span></div>",
        f"<div class='scout-list-item'><span>סינתזה:</span> <span style='font-weight:bold;'>{rec_data.get('fundamental', {}).get('synthesis', '-')}</span></div>",
        "</div></div>", 
        
        f"<div class='scout-alert-box' style='border-color: {alert_border}; background: {alert_bg};'>",
        "<span class='scout-alert-title'>🛡️ מערכת הגנה קשיחה (Financial & Tech Traps):</span>",
        failure_html,
        "</div></div></div>"
    ]
    st.markdown("".join(card_parts), unsafe_allow_html=True)
    
    st.markdown("#### 🎯 תוכנית מסחר וניהול סיכונים")
    st.markdown(f"**מחיר נוכחי לכניסה (Entry Baseline):** ${rec_data['entry_price']:.2f}")
    if rec not in ("SELL", "STRONG SELL"):
        st.markdown(f"**הגנת הפסד דינמית (SL):** ${rec_data['stop_loss_price']:.2f} (סיכון: {rec_data['stop_loss_pct']:.1f}%)")
        if rec in ("BUY", "STRONG BUY"):
            st.markdown(f"**יעד ראשון חלקי (TP1):** ${rec_data['tp1_price']:.2f} (+{rec_data['tp1_pct']:.1f}%)")
            st.markdown(f"**יעד שני מלא (TP2):** ${rec_data['tp2_price']:.2f} (+{rec_data['tp2_pct']:.1f}%)")
            st.markdown(f"**יחס סיכוי/סיכון (R/R):** {rec_data['rr_ratio']}")

def screen_backtest() -> None:
    st.markdown("### 📊 Backtest Engine")
    ticker = st.text_input("Ticker לבדיקה", value=st.session_state.current_ticker).strip().upper()
    if st.button("▶ הרץ סימולציה", type="primary"):
        with st.spinner("מריץ..."):
            df, audit_df = run_wyckoff_anchored_backtest(ticker, False, 65, period="2y")
            if not audit_df.empty:
                st.success(f"בוצעו {len(audit_df)} עסקאות.")
            else:
                st.warning("לא אותרו עסקאות בתקופה זו.")

def init_session_state() -> None:
    if "current_page" not in st.session_state: st.session_state.current_page = "Home"
    if "home_view" not in st.session_state: st.session_state.home_view = "quick"
    if "current_ticker" not in st.session_state: st.session_state.current_ticker = "NVDA"
    if "menu_open" not in st.session_state: st.session_state.menu_open = False

def main() -> None:
    init_session_state()
    render_top_bar()

    page = st.session_state.current_page
    if page in ["Home", "Deep Analysis", "Trading Scout"]:
        render_stepper()
        if page == "Home": screen_home()
        elif page == "Deep Analysis": screen_deep_analysis()
        elif page == "Trading Scout": screen_trading_scout()
    elif page == "Backtest":
        screen_backtest()

if __name__ == "__main__":
    main()
