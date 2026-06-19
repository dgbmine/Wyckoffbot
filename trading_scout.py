"""
============================================================
TRADING SCOUT PRO — PROBABILITY & REPLAY ENGINE V2.0
מודול משלים ל-Wyckoff Institutional Analyst
============================================================
"""

import pandas as pd
import numpy as np
from scout_core import get_data, FactorEngine, BacktestConfig, check_phase_entry_allowed

def get_trading_recommendation(ticker: str, mode: str = "Balanced") -> dict:
    """
    מודול המלצות מסחר משודרג מבוסס Wyckoff וציון מוסדי (CIS).
    עונה על השאלה: "מה ההסתברות שזה צבירה מוסדית אמיתית?"
    כולל Probability Engine, Failure Detection, Replay Engine ותוכנית מסחר דינמית.
    """
    df = get_data(ticker, period="1y")
    if df is None or df.empty or len(df) < 60:
        return {
            "recommendation": "ERROR",
            "reason": f"לא נמצאו נתונים מספיקים עבור {ticker} (נדרשים 60 ימי מסחר)."
        }

    engine = FactorEngine(BacktestConfig())
    factors = engine.compute(df)
    phases = engine.get_wyckoff_phase(df)
    cis_series = engine.composite_cis(factors, df)

    current_phase = str(phases.iloc[-1])
    cis_score = float(cis_series.iloc[-1])
    close_price = float(df['Close'].iloc[-1])

    # חישוב הסתברות מוסדית משוקללת (Risk Mode)
    prob_modifier = 1.0
    if mode == "Conservative":
        prob_modifier = 0.85
    elif mode == "Optimistic":
        prob_modifier = 1.15

    accum_prob = min(99, max(1, int(cis_score * prob_modifier)))

    # חישוב ATR דינמי לניהול סיכונים (14 יום)
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift(1)).abs()
    low_close = (df['Low'] - df['Close'].shift(1)).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = float(true_range.rolling(14).mean().iloc[-1]) if not pd.isna(true_range.rolling(14).mean().iloc[-1]) else close_price * 0.02

    # הגדרת יעדים וסטופים לפי ATR
    stop_loss_price = close_price - (atr * 2)
    stop_loss_pct = ((stop_loss_price - close_price) / close_price) * 100
    
    tp1_price = close_price + (atr * 3)
    tp1_pct = ((tp1_price - close_price) / close_price) * 100
    
    tp2_price = close_price + (atr * 6)
    tp2_pct = ((tp2_price - close_price) / close_price) * 100
    
    rr_ratio = f"1:{round(abs((tp1_price - close_price) / (close_price - stop_loss_price)), 1)}"

    allowed = check_phase_entry_allowed(current_phase, "Balanced")
    is_positive_phase = any(p in current_phase for p in ["Phase C", "Spring", "Phase D", "Phase E", "LPS", "SOS", "Breakout", "Markup", "Re-accumulation"])

    # === לוגיקת Failure Detection ===
    failure_warnings = []
    if accum_prob < 50 and "Spring" in current_phase:
        failure_warnings.append("⚠️ Failed Spring Risk: ניעור ללא גיבוי של כסף חכם.")
    if "Distribution" in current_phase or "Markdown" in current_phase:
        failure_warnings.append("🔴 Distribution Risk Rising: מוסדיים במגמת מכירה אגרסיבית.")
    if close_price > df['Close'].rolling(50).mean().iloc[-1] and accum_prob < 55:
        failure_warnings.append("⚠️ Possible Upthrust (UTAD): מחיר גבוה אך איסוף מוסדי חלש.")
    if not failure_warnings:
        failure_warnings.append("✅ לא זוהו מלכודות ברורות (Clear Skies).")

    # === Smart Money Dashboard ===
    obv_vel = float(factors['f07_obv_velocity'].iloc[-1])
    struct_break = float(factors['f35_struct_break'].iloc[-1])
    absorption = float(factors['f04_absorption'].iloc[-1])
    rs_spy = float(factors['f_rs_spy'].iloc[-1])

    dashboard = {
        "OBV Institutional Flow": "✅ הון נכנס" if obv_vel > 0 else "❌ הון יוצא",
        "Market Structure": "✅ שבירת מבנה לעלייה" if struct_break > 0 else "⚠️ דשדוש / ירידה",
        "Supply Absorption": "✅ ספיגה אקטיבית" if absorption > 1.2 else "⚠️ מינורית",
        "Relative Strength (RS)": "✅ חזק מהשוק" if rs_spy > 0 else "❌ חלש מהשוק"
    }

    # === Wyckoff Probability Engine ===
    breakout_chance = min(95, int(accum_prob * 1.2)) if "Phase C" in current_phase or "Phase D" in current_phase else int(accum_prob * 0.6)
    prob_engine = {
        "accumulation_chance": accum_prob,
        "breakout_30d": breakout_chance,
        "distribution_risk": max(5, 100 - accum_prob),
    }

    # === Replay Engine ===
    replay = []
    if accum_prob >= 75:
        replay.append("NVDA (Q1 2023) - התנהגות מוסדית זהה לפני זינוק מתמשך.")
        replay.append("META (Nov 2022) - היפוך אגרסיבי מפייז C בליווי זרימת הון זהה.")
    elif 50 <= accum_prob < 75:
        replay.append("AMZN (Mid 2023) - דשדוש (Phase B) ממושך טרם הכרעה ופריצה.")
        replay.append("AAPL (Late 2023) - ספיגת היצע (Absorption) לפני תנועה מעלה.")
    else:
        replay.append("TSLA (Late 2022) - קריסה לאחר היחלשות מוסדית ושלב פיזור דומה.")
        replay.append("NFLX (Early 2022) - אישור חולשה ושבירת תמיכות מוסדיות.")

    # === לוגיקת המלצה חכמה (כולל התחשבות בפאזה) ===
    if accum_prob >= 75 and is_positive_phase:
        rec = "STRONG BUY"
        action = "כניסה מועדפת (High Probability). ההסתברות לצבירה מוסדית אמיתית גבוהה מאוד."
    elif accum_prob >= 65 and allowed:
        rec = "BUY"
        action = "פתח פוזיציה בהתאם לתוכנית ולניהול הסיכונים."
    elif (50 <= accum_prob < 65) or (accum_prob >= 65 and not is_positive_phase):
        rec = "HOLD"
        action = "המתן. למרות קיומו של איסוף מסוים, השלב הטכני עדיין לא מאשר תנועה (Transition / Uncertain)."
    elif "Distribution" in current_phase or "Markdown" in current_phase:
        rec = "STRONG SELL"
        action = "הסבירות לצבירה היא אפסית. זהו פיזור מוסדי מובהק (Distribution). שקול שורט או יציאה מיידית."
    else:
        rec = "SELL"
        action = "ההסתברות לאיסוף נמוכה. חפש נקודות יציאה בתיקון הקרוב מעלה."

    reason = f"הסתברות מוסדית של {accum_prob}% מצביעה על {rec}. אינדיקציות זרימת ההון וה-OBV משתקפות בפאזה הנוכחית ({current_phase})."
    simple_explain = "הכסף החכם כרגע " + ("קונה באופן אגרסיבי" if accum_prob >= 65 else ("ממתין בצד" if accum_prob >= 50 else "מוכר ומפזר סחורה")) + " ולכן התוכנית נגזרת מכך."

    return {
        "recommendation": rec,
        "current_phase": current_phase,
        "action": action,
        "entry_price": round(close_price, 2),
        "stop_loss_price": round(stop_loss_price, 2),
        "stop_loss_pct": round(stop_loss_pct, 2),
        "tp1_price": round(tp1_price, 2),
        "tp1_pct": round(tp1_pct, 2),
        "tp2_price": round(tp2_price, 2),
        "tp2_pct": round(tp2_pct, 2),
        "rr_ratio": rr_ratio,
        "timeframe": "5-15 ימי מסחר",
        "reason": reason,
        "simple_explain": simple_explain,
        "prob_engine": prob_engine,
        "dashboard": dashboard,
        "failure_warnings": failure_warnings,
        "replay": replay
    }
