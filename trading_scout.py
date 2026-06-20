"""
============================================================
TRADING SCOUT PRO — PROBABILITY & REPLAY ENGINE V3.0
מודול משלים ל-Wyckoff Institutional Analyst - רדאר כסף חכם
============================================================
"""

import pandas as pd
import numpy as np
from scout_core import get_data, FactorEngine, BacktestConfig, check_phase_entry_allowed

def get_trading_recommendation(ticker: str, mode: str = "Balanced") -> dict:
    """
    מודול המלצות מסחר מבוסס Wyckoff וציון מוסדי (CIS).
    עונה על השאלה: "מה ההסתברות שזה צבירה מוסדית אמיתית?"
    השדרוג כולל Probability Engine חכם יותר המושפע עמוקות מהפאזה ומה-OBV,
    Failure Detection מדויק, ו-Replay דינמי התלוי לחלוטין בתבנית הנוכחית.
    """
    df = get_data(ticker, period="1y")
    if df is None or df.empty or len(df) < 60:
        return {
            "recommendation": "ERROR",
            "reason": f"לא נמצאו נתונים מספיקים עבור {ticker} (נדרשים לפחות 60 ימי מסחר תקינים)."
        }

    engine = FactorEngine(BacktestConfig())
    factors = engine.compute(df)
    phases = engine.get_wyckoff_phase(df)
    cis_series = engine.composite_cis(factors, df)

    current_phase = str(phases.iloc[-1])
    cis_score = float(cis_series.iloc[-1])
    close_price = float(df['Close'].iloc[-1])

    # === שליפת נתונים מתקדמים מהליבה (בטיחותי) ===
    obv_vel = float(factors.get('f07_obv_velocity', pd.Series([0.0])).iloc[-1])
    struct_break = float(factors.get('f35_struct_break', pd.Series([0.0])).iloc[-1])
    absorption = float(factors.get('f04_absorption', pd.Series([1.0])).iloc[-1])
    rs_spy = float(factors.get('f_rs_spy', pd.Series([0.0])).iloc[-1])
    
    # שליפת Effort vs Result אם קיים, אחרת ממוצע נייטרלי
    effort_vs_result = float(factors.get('f_effort_vs_result', pd.Series([1.0])).iloc[-1])

    # === חישוב הסתברות מוסדית משוקללת (Risk Mode) ===
    prob_modifier = 1.0
    if mode == "Conservative":
        prob_modifier = 0.85
    elif mode == "Optimistic":
        prob_modifier = 1.15

    accum_prob = min(99, max(1, int(cis_score * prob_modifier)))

    # === חישוב ATR דינמי לניהול סיכונים (14 יום) ===
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift(1)).abs()
    low_close = (df['Low'] - df['Close'].shift(1)).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = float(true_range.rolling(14).mean().iloc[-1]) if not pd.isna(true_range.rolling(14).mean().iloc[-1]) else close_price * 0.02

    # יעדים וסטופים דינמיים לפי מרווחי תנודתיות (ATR)
    stop_loss_price = close_price - (atr * 2)
    stop_loss_pct = ((stop_loss_price - close_price) / close_price) * 100
    tp1_price = close_price + (atr * 3.5)
    tp1_pct = ((tp1_price - close_price) / close_price) * 100
    tp2_price = close_price + (atr * 7)
    tp2_pct = ((tp2_price - close_price) / close_price) * 100
    
    rr_ratio = f"1:{round(abs((tp1_price - close_price) / (close_price - stop_loss_price)), 1)}"

    allowed = check_phase_entry_allowed(current_phase, "Balanced")
    is_positive_phase = any(p in current_phase for p in ["Phase C", "Spring", "Phase D", "Phase E", "LPS", "SOS", "Breakout", "Markup", "Re-accumulation"])

    # === Smart Money Dashboard ===
    dashboard = {
        "OBV Flow": "✅ כניסת הון אגרסיבית" if obv_vel > 0.02 else ("❌ יציאת הון" if obv_vel < -0.02 else "⚠️ נייטרלי / מעורב"),
        "Structure": "✅ שבירת מבנה (BOS)" if struct_break > 0 else "❌ דשדוש או ירידה",
        "Absorption": "✅ ספיגת היצע מוכחת" if absorption > 1.2 else "⚠️ אין ספיגה משמעותית",
        "Rel. Strength": "✅ מוביל על השוק" if rs_spy > 0 else "❌ מפגר אחרי השוק"
    }

    # === Wyckoff Probability Engine - Smart Dynamics ===
    bo_modifier = 0
    # פאזות C ו-D מקפיצות את סיכויי הפריצה משמעותית אם יש תמיכה של כסף פנימי
    if "Phase C" in current_phase or "Spring" in current_phase: bo_modifier += 25
    if "Phase D" in current_phase or "LPS" in current_phase: bo_modifier += 20
    if struct_break > 0: bo_modifier += 15
    if obv_vel > 0: bo_modifier += 15
    if absorption > 1.3: bo_modifier += 10
    
    breakout_chance = min(98, int((accum_prob * 0.35) + bo_modifier))

    dist_modifier = 0
    if "Distribution" in current_phase or "Markdown" in current_phase: dist_modifier += 50
    if obv_vel < 0: dist_modifier += 25
    if rs_spy < -0.02: dist_modifier += 15
    
    distribution_risk = min(98, max(2, int((100 - accum_prob) * 0.45 + dist_modifier)))

    prob_engine = {
        "accumulation_chance": accum_prob,
        "breakout_30d": breakout_chance,
        "distribution_risk": distribution_risk,
    }

    # === Failure Detection - High Precision Warnings ===
    failure_warnings = []
    
    if "Spring" in current_phase and obv_vel < 0:
        failure_warnings.append("🔴 Fake Spring Alert: המניה מייצרת תבנית 'ניעור' אך ה-OBV שלילי. כסף חכם *לא* מגבה את העלייה הזו.")
        
    if ("Distribution" in current_phase or "Markdown" in current_phase) and accum_prob < 45:
        failure_warnings.append("🔴 Heavy Distribution Confirmed: סכנה ממשית. מוסדיים משחררים סחורה והמחיר לא עומד בלחץ.")
        
    if is_positive_phase and effort_vs_result > 2.5 and close_price < df['Open'].iloc[-1]:
        failure_warnings.append("⚠️ Supply Overhang (מאמץ מול תוצאה): למרות העליות, קיימת התנגדות קשיחה מלמעלה. קונים מתאמצים ללא תוצאה הולמת.")
        
    if "Markup" in current_phase and rs_spy < -0.02:
        failure_warnings.append("⚠️ Weak Leader: המניה בפייז חיובי, אבל חלשה משמעותית ממדד ה-S&P 500 (RS שלילי).")
        
    if not failure_warnings:
        failure_warnings.append("✅ Clear Skies: לא זוהו אזהרות מוסדיות או מלכודות קלאסיות. זרימת ההון תקינה ועקבית.")

    # === Dynamic Replay Engine ===
    replay = []
    if "Phase C" in current_phase or "Spring" in current_phase:
        if accum_prob >= 70:
            replay.append("🔍 BTC (Jan 2023) - ניעור נזילות חד למטה (Spring) מלווה מיד בקנייה מוסדית כבדה שהחלה את שוק השוורים.")
            replay.append("🔍 META (Nov 2022) - ספיגת היצע מוחלטת בנמוכים, היפוך אלים כלפי מעלה.")
        else:
            replay.append("⚠️ DIS (2023) - תבנית Spring כושלת. המחיר ניסה לעלות ללא גיבוי של כסף חכם (OBV חלש) והמשיך לרדת.")
            
    elif "Phase D" in current_phase or "LPS" in current_phase:
        if accum_prob >= 65:
            replay.append("🔍 NVDA (Q1 2023) - בניית כוח מסיבית (LPS) צמוד להתנגדות לפני פריצה מעלה (SOS). קלאסיקה מוסדית.")
        else:
            replay.append("⚠️ PYPL (Late 2021) - ניסיון פריצה כושל. היעדר מומנטום של כסף חכם הוביל למלכודת שוורים (Bull Trap).")
            
    elif "Phase E" in current_phase or "Markup" in current_phase:
        if accum_prob >= 75:
            replay.append("🔍 SMCI (2023) - מגמת Markup אגרסיבית עם זרימת הון שלא פוסקת (No Supply bars).")
        else:
            replay.append("⚠️ הקיטור אוזל? היסטורית, כשהאיסוף המוסדי יורד במהלך Markup, זהו סימן מקדים ל-Distribution מתקרב.")
            
    elif "Distribution" in current_phase or "Markdown" in current_phase:
        replay.append("🔍 TSLA (Late 2022) - פיזור סחורה שיטתי על ידי מוסדיים. ה-OBV ירד לפני שהמחיר קרס משמעותית.")
        replay.append("🔍 NFLX (Early 2022) - לאחר אישור החולשה, הנזילות יצאה והמניה חוותה Markdown אלים.")
        
    else: # Transition / Phase A / Phase B
        replay.append("🔍 AMZN (Mid 2023) - תהליך שחיקה ודשדוש ממושך. בניית בסיס (Cause) לפני שמוסדיים מחליטים על כיוון.")

    # === לוגיקת המלצה (Action Plan) ===
    if accum_prob >= 75 and is_positive_phase:
        rec = "STRONG BUY"
        action = "כניסה מועדפת (High Conviction). ההסתברות לצבירה מוסדית אמיתית גבוהה מאוד. שקול כניסה אגרסיבית."
    elif accum_prob >= 65 and allowed:
        rec = "BUY"
        action = "פתח פוזיציה בהתאם לניהול הסיכונים. קיימת טביעת אצבע ברורה של כסף חכם."
    elif (50 <= accum_prob < 65) or (accum_prob >= 65 and not is_positive_phase):
        rec = "HOLD"
        action = "המתן. אמנם קיימת נוכחות של הון פנימי, אך הפאזה הטכנית אינה מספקת אישור מספק לפריצה מיידית."
    elif "Distribution" in current_phase or "Markdown" in current_phase:
        rec = "STRONG SELL"
        action = "הסבירות לצבירה היא אפסית. זהו פיזור מוסדי מובהק (Distribution). שקול הגנות (שורט) או יציאה מיידית."
    else:
        rec = "SELL"
        action = "הסתברות נמוכה לאיסוף. מומנטום הכסף החכם שלילי. חפש נקודות יציאה טקטית בתיקון הקרוב מעלה."

    reason = f"הסתברות מוסדית של {accum_prob}% מצביעה על {rec}. התוצאה משוקללת עם הפאזה הנוכחית ({current_phase}) וזרימת ה-OBV."
    simple_explain = "לפי ניתוח הרדאר, הכסף החכם כרגע " + ("קונה באופן אגרסיבי ודוחף את המחיר כלפי מעלה (צבירה)." if accum_prob >= 65 else ("ממתין בצד, ללא החלטה ברורה כרגע." if accum_prob >= 50 else "מוכר ומפזר סחורה לציבור הרחב (הפצה).")) + " פעל בהתאם לתוכנית המסחר."

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
        "timeframe": "5-20 ימי מסחר",
        "reason": reason,
        "simple_explain": simple_explain,
        "prob_engine": prob_engine,
        "dashboard": dashboard,
        "failure_warnings": failure_warnings,
        "replay": replay
    }
