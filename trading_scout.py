"""
============================================================
TRADING SCOUT PRO V5.4
מודול משלים ל-Wyckoff Institutional Analyst - רדאר כסף חכם
============================================================
"""

import pandas as pd
import numpy as np
from scout_core import (
    get_data, FactorEngine, BacktestConfig, check_phase_entry_allowed,
    build_smart_money_dashboard, generate_roadmap, calculate_wyckoff_probability,
    detect_failure_risks, generate_replay_analogies, get_fundamental_data
)

def get_trading_recommendation(ticker: str, mode: str = "Balanced") -> dict:
    """
    מודול המלצות מסחר הדוק, משלב וואיקוף ואזהרות פונדמנטליות.
    מוודא עקביות מוחלטת בין הדיאגנוזה הפונדמנטלית הקשיחה (Ackman Style)
    לבין פקודת המסחר הטכנית.
    """
    df = get_data(ticker, period="1y")
    if df is None or df.empty or len(df) < 60:
        return {"recommendation": "ERROR", "reason": f"לא נמצאו נתונים מספיקים עבור {ticker}."}

    engine = FactorEngine(BacktestConfig())
    factors = engine.compute(df)
    phases = engine.get_wyckoff_phase(df)
    cis_series = engine.composite_cis(factors, df)

    current_phase = str(phases.iloc[-1])
    cis_score = float(cis_series.iloc[-1])
    accum_prob = min(99, max(1, int(cis_score)))
    allowed = check_phase_entry_allowed(current_phase, mode)

    # חילוץ עומק פונדמנטלי המשלב את הפאזה הנוכחית לסינתזה עקבית
    fund_data = get_fundamental_data(ticker, cis_score=cis_score, current_phase=current_phase)

    # מערכת הגנה ממלכודות שמשלבת גם אזהרות קאש-פלואו ומאזן
    orig_warnings = detect_failure_risks(df, factors, current_phase, accum_prob, allowed, ticker)
    warnings_list = [w for w in orig_warnings if "Clear Skies" not in w]

    synth_text = fund_data.get("synthesis", "")
    is_toxic = any(word in synth_text for word in ["רעילה", "Toxic", "מלכודת ערך", "סכין נופלת", "🚨", "☠️"])
    is_bearish_phase = any(p in current_phase for p in ["Distribution", "Markdown", "Heavy Supply", "Failed", "Selling Climax"])

    if is_toxic or is_bearish_phase:
        warnings_list.append("🚨 סכין נופלת / מלכודת רעילה: הכסף החכם נוטש. חולשה מאזנית או טכנית קיצונית. להתרחק!")
    elif "פרמיית איכות" in synth_text or "High Conviction" in synth_text:
        warnings_list.append("🟢 פרמיית איכות פונדמנטלית: החברה יעילה תזרימית ומגובה במבנה איסוף מוסדי מובהק.")

    if not warnings_list:
        warnings_list.append(f"✅ שמיים נקיים: לא אותרו מלכודות תזרימיות או טכניות ב-{ticker}.")

    # תכנון עסקאות טכני
    close_price = df['Close'].iloc[-1]
    atr = (df['High'] - df['Low']).rolling(14).mean().iloc[-1]
    
    stop_loss_price = close_price - (atr * 2.5) if not pd.isna(atr) else close_price * 0.95
    tp1_price = close_price + (atr * 3) if not pd.isna(atr) else close_price * 1.05
    tp2_price = close_price + (atr * 6) if not pd.isna(atr) else close_price * 1.10

    sl_pct = (close_price - stop_loss_price) / close_price * 100
    tp1_pct = (tp1_price - close_price) / close_price * 100
    tp2_pct = (tp2_price - close_price) / close_price * 100

    risk = close_price - stop_loss_price
    reward = tp1_price - close_price
    rr_ratio = f"1:{round(reward / risk, 1)}" if risk > 0 else "N/A"

    is_positive_phase = any(p in current_phase for p in ["Phase C", "Spring", "Phase D", "Phase E", "LPS", "SOS", "Breakout", "Markup", "Re-accumulation"])

    # קביעת המלצה קשיחה - עקביות מלאה עם הפונדמנטלי וללא פשרות בפאזה דובית
    if is_toxic or is_bearish_phase:
        rec = "STRONG SELL"
        action = "התרחק מיד! 🚨 סכין נופלת. לחץ מכירות מוסדי אגרסיבי, נתמך בחולשה מבנית ו/או פיננסית. אל תתפוס תחתיות."
    elif accum_prob >= 75 and is_positive_phase and not is_toxic:
        rec = "STRONG BUY"
        action = "כניסה מועדפת. המוסדיים אוספים סחורה באגרסיביות ויש תמיכה מאזנית עוצמתית."
    elif accum_prob >= 65 and allowed and not is_toxic:
        rec = "BUY"
        action = "פתח פוזיציה מדורגת. טביעת אצבע ברורה של כסף חכם לקראת פריצה טכנית."
    elif (50 <= accum_prob < 65) or (accum_prob >= 65 and not is_positive_phase):
        rec = "HOLD"
        action = "המתן. ישנם ניצני עניין אך הפאזה אינה בשלה, או שישנו חסרון פונדמנטלי הדורש מעקב."
    else:
        rec = "SELL"
        action = "מומנטום כסף חכם שלילי. אין הון פנימי שדוחף קדימה. שקול לממש רווחים."

    reason = f"הסתברות של {accum_prob}% לאיסוף בפאזת {current_phase}, נתמך באנליזת תזרים ואיכות עסקים."

    return {
        "recommendation": rec,
        "current_phase": current_phase,
        "action": action,
        "entry_price": round(close_price, 2),
        "stop_loss_price": round(stop_loss_price, 2),
        "stop_loss_pct": round(sl_pct, 1),
        "tp1_price": round(tp1_price, 2),
        "tp1_pct": round(tp1_pct, 1),
        "tp2_price": round(tp2_price, 2),
        "tp2_pct": round(tp2_pct, 1),
        "rr_ratio": rr_ratio,
        "timeframe": "1-3 שבועות (Swing)",
        "dashboard": build_smart_money_dashboard(factors),
        "roadmap": generate_roadmap(current_phase),
        "prob_engine": calculate_wyckoff_probability(df, factors, current_phase, mode, cis_score),
        "failure_warnings": warnings_list,
        "replay": generate_replay_analogies(ticker, current_phase, accum_prob, factors),
        "fundamental": fund_data,
        "reason": reason
    }
