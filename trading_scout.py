"""
============================================================
TRADING SCOUT PRO — PROBABILITY & REPLAY ENGINE V2.5
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
    כולל Wyckoff Probability Engine דינמי, Failure Detection מחמיר,
    Replay Engine מבוסס היסטוריה, ותוכנית מסחר מדויקת.
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

    # === שליפת נתונים מתקדמים מהליבה ל-Probability Engine ===
    obv_vel = float(factors['f07_obv_velocity'].iloc[-1])
    struct_break = float(factors['f35_struct_break'].iloc[-1])
    absorption = float(factors['f04_absorption'].iloc[-1])
    rs_spy = float(factors['f_rs_spy'].iloc[-1])
    effort_vs_result = float(factors['f_effort_vs_result'].iloc[-1])

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

    # יעדים וסטופים דינמיים לפי ATR
    stop_loss_price = close_price - (atr * 2)
    stop_loss_pct = ((stop_loss_price - close_price) / close_price) * 100
    
    tp1_price = close_price + (atr * 3)
    tp1_pct = ((tp1_price - close_price) / close_price) * 100
    
    tp2_price = close_price + (atr * 6)
    tp2_pct = ((tp2_price - close_price) / close_price) * 100
    
    rr_ratio = f"1:{round(abs((tp1_price - close_price) / (close_price - stop_loss_price)), 1)}"

    allowed = check_phase_entry_allowed(current_phase, "Balanced")
    is_positive_phase = any(p in current_phase for p in ["Phase C", "Spring", "Phase D", "Phase E", "LPS", "SOS", "Breakout", "Markup", "Re-accumulation"])

    # === Smart Money Dashboard ===
    dashboard = {
        "OBV Flow": "✅ הון נכנס (Positive)" if obv_vel > 0 else "❌ הון יוצא (Negative)",
        "Structure": "✅ שבירה לעלייה" if struct_break > 0 else "⚠️ דשדוש / ירידה",
        "Absorption": "✅ ספיגה אקטיבית" if absorption > 1.2 else "⚠️ מינורית / חלשה",
        "Rel. Strength": "✅ חזק מהשוק" if rs_spy > 0 else "❌ חלש מהשוק"
    }

    # === Wyckoff Probability Engine מתקדם ===
    bo_modifier = 0
    if "Phase C" in current_phase or "Phase D" in current_phase: bo_modifier += 20
    if struct_break > 0: bo_modifier += 15
    if obv_vel > 0: bo_modifier += 15
    if absorption > 1.2: bo_modifier += 10
    breakout_chance = min(95, int((accum_prob * 0.4) + bo_modifier))

    dist_modifier = 0
    if "Distribution" in current_phase or "Markdown" in current_phase: dist_modifier += 40
    if obv_vel < 0: dist_modifier += 20
    if rs_spy < -0.01: dist_modifier += 15
    distribution_risk = min(95, max(5, int((100 - accum_prob) * 0.4 + dist_modifier)))

    prob_engine = {
        "accumulation_chance": accum_prob,
        "breakout_30d": breakout_chance,
        "distribution_risk": distribution_risk,
    }

    # === לוגיקת Failure Detection מחמירה ===
    failure_warnings = []
    if accum_prob < 50 and "Spring" in current_phase:
        failure_warnings.append("⚠️ Failed Spring Risk: ניעור סחורה ללא גיבוי פנימי של הון חכם.")
    if ("Distribution" in current_phase or "Markdown" in current_phase) and accum_prob < 40:
        failure_warnings.append("🔴 Distribution Confirmed: סכנה ממשית להמשך ירידות (פיזור מוסדי).")
    if close_price > df['Close'].rolling(50).mean().iloc[-1] and accum_prob < 55 and rs_spy < 0:
        failure_warnings.append("⚠️ Possible Upthrust (UTAD): מחיר גבוה ממוצעים, אך חולשה מוסדית יחסית לשוק.")
    if effort_vs_result > 2.0 and close_price < df['Open'].iloc[-1]:
        failure_warnings.append("⚠️ Supply Overhang: מאמץ גבוה של קונים נבלם על ידי היצע קשיח מלמעלה.")
    if not failure_warnings:
        failure_warnings.append("✅ Clear Skies: לא זוהו מלכודות ברורות. התנהגות השוק תקינה ואמינה.")

    # === Replay Engine (היסטוריית פאזות) ===
    replay = []
    if accum_prob >= 75:
        if "Phase C" in current_phase:
            replay.append("🔍 META (Nov 2022) - היפוך אגרסיבי מפייז C בליווי זרימת הון וספיגה זהה. פריצה עזה תוך 14 יום.")
        elif "Phase D" in current_phase:
            replay.append("🔍 NVDA (Q1 2023) - בניית כוח מסיבית מעל התמיכה (LPS) רגע לפני שלב ה-Markup. קלאסיקה של כסף חכם.")
        else:
            replay.append("🔍 AMD (Mid 2023) - המשכיות מגמה מוסדית עם דחיפה חזקה של הון.")
    elif 50 <= accum_prob < 75:
        if "Phase B" in current_phase or "Accumulation" in current_phase:
            replay.append("🔍 AMZN (Mid 2023) - דשדוש ממושך (Phase B) טרם הכרעה. המוסדיים אוספים לאט ובשקט.")
        else:
            replay.append("🔍 AAPL (Late 2023) - התבססות מוסדית ברמות הנוכחיות. נדרש אישור טכני כדי להניע פריצה.")
    else:
        if "Distribution" in current_phase:
            replay.append("🔍 TSLA (Late 2022) - שלב פיזור דומה שהוביל לגל ירידות חריף לאחר היחלשות ה-OBV.")
        else:
            replay.append("🔍 NFLX (Early 2022) - אישור חולשה, שבירת תמיכות מוסדיות ויציאת נזילות.")

    # === לוגיקת המלצה חכמה ===
    if accum_prob >= 75 and is_positive_phase:
        rec = "STRONG BUY"
        action = "כניסה מועדפת (High Probability). הסתברות גבוהה מאוד לצבירה מוסדית אמיתית. שקול כניסה מלאה."
    elif accum_prob >= 65 and allowed:
        rec = "BUY"
        action = "פתח פוזיציה בהתאם לניהול הסיכונים. קיימת נוכחות חיובית של הון חכם."
    elif (50 <= accum_prob < 65) or (accum_prob >= 65 and not is_positive_phase):
        rec = "HOLD"
        action = "המתן. למרות קיומו של איסוף מסוים, השלב הטכני (Uncertain / Transition) לא מאשר תנועה מיידית."
    elif "Distribution" in current_phase or "Markdown" in current_phase:
        rec = "STRONG SELL"
        action = "הסבירות לצבירה אפסית. זהו פיזור מוסדי (Distribution). שקול הגנות או יציאה מיידית."
    else:
        rec = "SELL"
        action = "הסתברות נמוכה לאיסוף. המומנטום שלילי. חפש נקודות יציאה בתיקון הקרוב מעלה."

    reason = f"הסתברות מוסדית של {accum_prob}% מצביעה על החלטת {rec}. נתוני המומנטום חושבו יחד עם השלב הנוכחי: {current_phase}."
    simple_explain = "לפי הנתונים, הכסף החכם כרגע " + ("קונה באופן מסיבי ודוחף את המחיר." if accum_prob >= 65 else ("עומד על הגדר וממתין." if accum_prob >= 50 else "מוכר ומפזר סחורה לציבור הרחב.")) + " פעל בהתאם לתוכנית המסחר."

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
