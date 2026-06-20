"""
============================================================
TRADING SCOUT PRO — PROBABILITY & REPLAY ENGINE V4.6
מודול משלים ל-Wyckoff Institutional Analyst - רדאר כסף חכם
============================================================
"""

import pandas as pd
import numpy as np
from scout_core import get_data, FactorEngine, BacktestConfig, check_phase_entry_allowed

def get_trading_recommendation(ticker: str, mode: str = "Balanced") -> dict:
    """
    מודול המלצות מסחר מבוסס Wyckoff וציון מוסדי (CIS).
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
    obv_vel = float(factors.get('f07_obv_velocity', pd.Series([0.0])).iloc[-1])
    struct_break = float(factors.get('f35_struct_break', pd.Series([0.0])).iloc[-1])
    absorption = float(factors.get('f04_absorption', pd.Series([1.0])).iloc[-1])
    rs_spy = float(factors.get('f_rs_spy', pd.Series([0.0])).iloc[-1])
    effort_vs_result = float(factors.get('f_effort_vs_result', pd.Series([1.0])).iloc[-1])
    stopping_vol = float(factors.get('f_stopping_volume', pd.Series([0.0])).iloc[-1])

    # === חישוב הסתברות מוסדית (Risk Mode) וקנס הפצה דינמי ===
    prob_modifier = 1.0
    if mode == "Conservative":
        prob_modifier = 0.85
    elif mode == "Optimistic":
        prob_modifier = 1.15

    # אם אנחנו בפיזור, ניתן קנס חמור לציון ה-CIS למניעת קריאות שווא בגלל מחזורים גבוהים של זריקת סחורה
    if "Distribution" in current_phase or "Markdown" in current_phase:
        prob_modifier -= 0.35

    accum_prob = min(99, max(1, int(cis_score * prob_modifier)))

    # === חישוב ATR דינמי לניהול סיכונים (14 יום) ===
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift(1)).abs()
    low_close = (df['Low'] - df['Close'].shift(1)).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = float(true_range.rolling(14).mean().iloc[-1]) if not pd.isna(true_range.rolling(14).mean().iloc[-1]) else close_price * 0.02

    # יעדים וסטופים
    stop_loss_price = close_price - (atr * 2)
    stop_loss_pct = ((stop_loss_price - close_price) / close_price) * 100
    tp1_price = close_price + (atr * 3.5)
    tp1_pct = ((tp1_price - close_price) / close_price) * 100
    tp2_price = close_price + (atr * 7)
    tp2_pct = ((tp2_price - close_price) / close_price) * 100
    rr_ratio = f"1:{round(abs((tp1_price - close_price) / (close_price - stop_loss_price)), 1)}"

    allowed = check_phase_entry_allowed(current_phase, "Balanced")
    is_positive_phase = any(p in current_phase for p in ["Phase C", "Spring", "Phase D", "Phase E", "LPS", "SOS", "Breakout", "Markup", "Re-accumulation"])

    # === Wyckoff Roadmap Mapping ===
    roadmap = {"previous_phase": "לא ידוע", "next_phase": "לא ידוע"}
    if "Phase A" in current_phase:
        roadmap["previous_phase"] = "מגמת ירידה (Markdown)"
        roadmap["next_phase"] = "שלב B (בניית כוח / איסוף)"
    elif "Phase B" in current_phase:
        roadmap["previous_phase"] = "שלב A (בלימה)"
        roadmap["next_phase"] = "שלב C (ניעור / Spring)"
    elif "Phase C" in current_phase or "Spring" in current_phase:
        roadmap["previous_phase"] = "שלב B (איסוף שקט)"
        roadmap["next_phase"] = "שלב D (הכנה לפריצה / SOS)"
    elif "Phase D" in current_phase or "LPS" in current_phase:
        roadmap["previous_phase"] = "שלב C (ניעור)"
        roadmap["next_phase"] = "שלב E (מגמת עליה / Markup)"
    elif "Phase E" in current_phase or "Markup" in current_phase:
        roadmap["previous_phase"] = "שלב D (פריצה)"
        roadmap["next_phase"] = "שלב A עליון (תחילת פיזור)"
    elif "Distribution" in current_phase:
        roadmap["previous_phase"] = "שלב E (מגמת עליה)"
        roadmap["next_phase"] = "מגמת ירידה (Markdown)"
    elif "Markdown" in current_phase:
        roadmap["previous_phase"] = "פיזור מוסדי (Distribution)"
        roadmap["next_phase"] = "שלב A חדש (חיפוש תחתית)"

    # === Smart Money Dashboard ===
    dashboard = {
        "OBV Velocity": "✅ כניסה אגרסיבית" if obv_vel > 0.02 else ("❌ יציאת הון" if obv_vel < -0.02 else "⚠️ נייטרלי / מעורב"),
        "Price Structure": "✅ שבירת מבנה (BOS)" if struct_break > 0 else "❌ דשדוש או ירידה",
        "Supply Absorption": "✅ ספיגה עמוקה" if absorption > 1.2 else "⚠️ אין ספיגה משמעותית",
        "Relative Strength": "✅ מוביל על השוק" if rs_spy > 0 else "❌ מפגר אחרי השוק",
        "Volume Anomalies": "✅ בלימת מחזורים" if stopping_vol > 0 else "⚠️ מחזורים שגרתיים"
    }

    # === Wyckoff Probability Engine ===
    bo_modifier = 0
    dist_modifier = 0
    edu_bo = ""
    edu_dist = ""
    
    # חישוב משקלים דינמי לפי פאזה + בניית טקסט הסבר מלמד
    if "Phase C" in current_phase or "Spring" in current_phase:
        if absorption > 1.2: bo_modifier += 15
        if obv_vel > 0: bo_modifier += 15
        if stopping_vol > 0: bo_modifier += 10
        if rs_spy < -0.02: dist_modifier += 15
        edu_bo = f"הסיכוי לפריצה מבוסס כעת על נתוני שלב C (ניעור מוסדי). המערכת זיהתה " + ("זרימת הון פנימי חזקה (OBV) וספיגת מוכרים, מה שמגביר משמעותית את סיכוי הפריצה." if bo_modifier >= 20 else "שחסרה עדיין דחיפה חזקה של קונים כדי לאשר פריצה מלאה.")
        edu_dist = "הסיכון העיקרי הוא שניעור זה יתברר כהמשך ירידות (Fake Spring)."
        
    elif "Phase D" in current_phase or "LPS" in current_phase:
        if struct_break > 0: bo_modifier += 20
        if obv_vel > 0.02: bo_modifier += 15
        if rs_spy > 0: bo_modifier += 10
        edu_bo = f"בשלב D המטרה היא לפרוץ כלפי מעלה. " + ("זיהינו שבירת מבנה חיובית ועוצמה מול השוק, לכן ההסתברות לפריצה קפצה." if bo_modifier >= 20 else "חסרים עדיין אישורי מחזורים כדי להגדיל את ההסתברות לפריצה מוצלחת.")
        edu_dist = "כל עוד המבנה נשמר, סיכוני ההפצה נמוכים יחסית לשלבים קודמים."
        
    elif "Phase E" in current_phase or "Markup" in current_phase:
        if rs_spy > 0.02: bo_modifier += 15
        if obv_vel > 0.05: bo_modifier += 15
        if effort_vs_result > 2.5: dist_modifier += 25 
        edu_bo = "המניה כבר במגמת עליה מלאה. סיכויי הפריצה משקפים את היכולת להמשיך לייצר שיאים חדשים."
        edu_dist = "בשלב זה אנו מחפשים 'תשישות'. " + ("התגלה מאמץ קונים ללא תוצאה (Effort vs Result גרוע), מה שמקפיץ את סיכון ההפצה!" if dist_modifier >= 25 else "המחזורים נראים בריאים ואין סימני פיזור ברורים.")
        
    elif "Distribution" in current_phase or "Markdown" in current_phase:
        dist_modifier += 40
        bo_modifier = 0
        edu_bo = "המערכת חסמה את סיכויי הפריצה ללונג, מכיוון שהפאזה הטכנית מראה על ירידות או פיזור נזילות של כסף חכם."
        edu_dist = "זיהוי הפצה מובהק. המוסדיים מחלקים סחורה לציבור, ולכן סיכון השבירה מזנק."
        
    else: 
        if stopping_vol > 0: bo_modifier += 15
        if absorption > 1.2: bo_modifier += 10
        if struct_break < 0: dist_modifier += 20
        edu_bo = "המניה נמצאת בשלבי התבססות מוקדמים (דשדוש). סיכויי הפריצה יתחזקו רק אם נראה בלימה עקבית של המחזורים השליליים."
        edu_dist = "בשלב זה קיימת סכנה שהדשדוש יהפוך להמשך מגמת ירידה אם המבנה ימשך להישבר."

    if obv_vel < -0.02: 
        dist_modifier += 25
        edu_dist += " **בנוסף, ה-OBV (זרימת ההון) מצביע על יציאת כסף, מה שמעלה את סיכון ההפצה.**"

    breakout_chance = min(98, max(2, int((accum_prob * 0.40) + bo_modifier)))
    distribution_risk = min(98, max(2, int((100 - accum_prob) * 0.40 + dist_modifier)))

    educational_note = (
        f"<b>• ציון האיסוף ({accum_prob}%):</b> זהו נתון הבסיס. הוא עונה על השאלה: 'כמה כסף מוסדי קונה עכשיו?'. ציון מתחת ל-50 מראה על חוסר עניין.<br><br>"
        f"<b>• סיכוי לפריצה ({breakout_chance}%):</b> {edu_bo}<br><br>"
        f"<b>• סיכון הפצה ({distribution_risk}%):</b> {edu_dist}"
    )

    prob_engine = {
        "accumulation_chance": accum_prob,
        "breakout_30d": breakout_chance,
        "distribution_risk": distribution_risk,
        "educational_note": educational_note
    }

    # === Failure Detection - Sharp & Exclusive Warnings ===
    failure_warnings = []
    
    if "Distribution" in current_phase or "Markdown" in current_phase:
        failure_warnings.append(f"🔴 סכנת מחיקה (Markdown): המערכת מזהה שהכסף החכם משחרר את **{ticker}** בשיטתיות. אל תחפש תחתיות שקריות. יש להימנע מלונג לחלוטין.")
    elif "Spring" in current_phase and obv_vel < 0:
        failure_warnings.append(f"🔴 ניעור שקרי (Fake Spring Alert): למרות השבירה מטה של **{ticker}**, ה-OBV יורד בחדות. זה אינו ניעור מוסדי שמטרתו קנייה, אלא המשך טבעי של לחץ המכירות.")
    elif is_positive_phase and effort_vs_result > 2.5 and close_price < df['Open'].iloc[-1]:
        failure_warnings.append(f"⚠️ היצע צף מעל המחיר (Supply Overhang): הקונים מתאמצים להרים את **{ticker}** ללא שום תוצאה הולמת (Effort vs Result גרוע). ישנו מוכר מוסדי עקשן שמכביד מלמעלה.")
    elif "Markup" in current_phase and rs_spy < -0.02:
        failure_warnings.append(f"⚠️ חולשה בסייקל (Weak Leader): **{ticker}** בפייז חיובי, אך מפגינה חולשה יחסית צורמת מול מדד ה-S&P 500. כשהשוק יתקן, מניות חלשות יקרסו ראשונות.")
    elif accum_prob > 60 and not allowed:
        failure_warnings.append(f"⚠️ חוסר בשלות טכני: קיימים ניצנים של כסף חכם הנכנס ל-**{ticker}**, אך התבנית עצמה עדיין אינה מוכנה למהלך מגמתי (תזמון לקוי). המתן להזדמנות בשלב C או D.")

    if not failure_warnings:
        failure_warnings.append(f"✅ שמיים נקיים (Clear Skies): התנהגות המחיר וזרימת ההון ב-**{ticker}** תקינה לחלוטין. לא זוהו אנומליות, אזהרות מוסדיות או מלכודות קלאסיות בטווח הזמן הקרוב.")

    # === Dynamic Replay Engine - Personalized Analogies ===
    replay = []
    if "Phase C" in current_phase or "Spring" in current_phase:
        if accum_prob >= 70:
            replay.append(f"🔍 טביעת אצבע מוסדית: הניעור הנוכחי ב-**{ticker}** זהה קונספטואלית לתבנית ה-Spring של BTC בינואר 2023 - קצירת נזילות קצרה מטה ומיד אחריה הזרמת הון מסיבית.")
        else:
            replay.append(f"⚠️ מלכודת עבר: הניסיון לייצר Spring ב-**{ticker}** נראה חלש וחסר גיבוי הון, בדומה למלכודות ש-DIS חוותה ב-2023. ללא OBV תומך, המחיר ימשיך לרדת.")
            
    elif "Phase D" in current_phase or "LPS" in current_phase:
        if accum_prob >= 65:
            replay.append(f"🔍 בניית כוח: **{ticker}** מזכירה כעת את ההתבססות האחרונה (LPS) של NVDA רגע לפני הפריצה הגדולה שלה. ישנה ספיגה שקטה צמוד להתנגדות.")
        else:
            replay.append(f"⚠️ פריצת שווא: זרימת ההון הנוכחית מזכירה את ניסיונות הפריצה של PYPL ב-2021 (Bull Trap) - מחיר עולה, אך המוסדיים לא באמת מאמינים בו.")
            
    elif "Phase E" in current_phase or "Markup" in current_phase:
        if accum_prob >= 70:
            replay.append(f"🔍 מומנטום פנימי: הריצה ב-**{ticker}** מלווה בכסף קשיח ולא ספקולטיבי, מזכיר את ההתנהגות של SMCI בטרנד העלייה הבריא שלה, שם כל היצע נבלע מיד.")
        else:
            replay.append(f"⚠️ תשישות טרנד: המומנטום ב-**{ticker}** מתחיל להראות סממנים היסטוריים של היחלשות איסוף מוסדי, שלב קלאסי המקדים כניסה לדשדוש והפצה.")
            
    elif "Distribution" in current_phase or "Markdown" in current_phase:
        replay.append(f"🔍 פיזור נזילות: דפוס הפיזור ב-**{ticker}** משכפל את ההתנהגות של TSLA בסוף 2022 - ה-OBV נשפך לפני המחיר, והמוסדיים נוטשים את הספינה.")
        
    else: 
        if stopping_vol > 0:
            replay.append(f"🔍 בלימת נפילה: בלימת המחזורים החריגה ב-**{ticker}** מזכירה את השלבים הראשונים (Phase A) של AAPL בתחילת 2023, כשהכסף החכם בלם באלימות את הירידות.")
        else:
            replay.append(f"🔍 שחיקה ואיסוף שקט: **{ticker}** נמצאת בשלב קיפאון המזכיר את AMZN באמצע 2023. שחיקה איטית (Phase B) בזמן שקרנות גידור אוספות בשקט וללא לחץ.")

    # === לוגיקת המלצה (Action Plan) ===
    if "Distribution" in current_phase or "Markdown" in current_phase:
        rec = "STRONG SELL"
        action = "התרחקות מוחלטת (AVOID) או פתיחת פוזיציית שורט. זיהוי הפצה מובהק."
    elif accum_prob >= 75 and is_positive_phase:
        rec = "STRONG BUY"
        action = "כניסה מועדפת (High Conviction). ההסתברות לצבירה מוסדית אמיתית גבוהה מאוד. שקול כניסה אגרסיבית."
    elif accum_prob >= 65 and allowed:
        rec = "BUY"
        action = "פתח פוזיציה בהתאם לניהול הסיכונים. קיימת טביעת אצבע ברורה של כסף חכם."
    elif (50 <= accum_prob < 65) or (accum_prob >= 65 and not is_positive_phase):
        rec = "HOLD"
        action = "המתן. אמנם קיימת נוכחות של הון פנימי, אך הפאזה הטכנית אינה מספקת אישור טקטי לפריצה מיידית."
    else:
        rec = "SELL"
        action = "הסתברות נמוכה לאיסוף. מומנטום הכסף החכם שלילי. חפש נקודות יציאה טקטית בתיקון הקרוב מעלה."

    reason = f"הסתברות מוסדית של {accum_prob}% מצביעה על {rec}. התוצאה משוקללת יחד עם הפאזה הנוכחית ({current_phase}), מהירות ה-OBV והמאמץ המושקע ביחס לתוצאה."
    simple_explain = f"לפי ניתוח הרדאר ל-**{ticker}**, הכסף החכם כרגע " + ("קונה באופן אגרסיבי ודוחף את המחיר כלפי מעלה (צבירה מוכחת)." if accum_prob >= 65 else ("ממתין בצד, ללא החלטה ברורה (דשדוש)." if accum_prob >= 50 else "מוכר ומפזר סחורה לציבור הרחב (הפצה ולחץ).")) + " פעל אך ורק בהתאם לתוכנית המסחר המוצעת."

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
        "replay": replay,
        "roadmap": roadmap
    }
