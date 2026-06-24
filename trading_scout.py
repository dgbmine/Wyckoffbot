"""
============================================================
TRADING SCOUT PRO V5.5
מודול משלים ל-Wyckoff Institutional Analyst - רדאר כסף חכם
(רזה וממוקד, נשען לחלוטין על מנוע scout_core החכם)
V5.3: הבטחת ברזל - rec/action לעולם לא יסתרו את synthesize_verdict
V5.4-V5.5: ללא שינוי לוגי - גרסה תואמת ל-scout_core V17.4
============================================================
"""

import pandas as pd
import numpy as np
from scout_core import (
    get_data, FactorEngine, BacktestConfig, check_phase_entry_allowed,
    build_smart_money_dashboard, generate_roadmap, calculate_wyckoff_probability,
    detect_failure_risks, generate_replay_analogies, get_fundamental_data,
    synthesize_verdict
)

def get_trading_recommendation(ticker: str, mode: str = "Balanced") -> dict:
    """
    מודול המלצות מסחר מבוסס Wyckoff המקבל את כל כובד החישוב מ-scout_core.
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
    
    allowed = check_phase_entry_allowed(current_phase, "Balanced")
    is_positive_phase = any(p in current_phase for p in ["Phase C", "Spring", "Phase D", "Phase E", "LPS", "SOS", "Breakout", "Markup", "Re-accumulation"])

    # === שליפת חישובים מתקדמים משכבת הליבה (Core) תוך העברת ה-Ticker ===
    dashboard = build_smart_money_dashboard(factors)
    roadmap = generate_roadmap(current_phase)
    prob_engine = calculate_wyckoff_probability(df, factors, current_phase, mode, cis_score)
    accum_prob = prob_engine['accumulation_chance']
    failure_warnings = detect_failure_risks(df, factors, current_phase, accum_prob, allowed, ticker)
    replay = generate_replay_analogies(ticker, current_phase, accum_prob, factors)
    
    # === שכבה 1: מלכודות Wyckoff טהורות (מהליבה) ===
    # אם כל שהוחזר הוא ההודעה הגנרית "Clear Skies" - אין מלכודת Wyckoff אמיתית.
    wyckoff_traps = [w for w in failure_warnings if not w.startswith("✅ שמיים נקיים")]

    # === סינתזה פונדמנטלית (קשיחה ודטרמיניסטית - נקודת אמת אחת) ===
    fund_data = get_fundamental_data(ticker)
    verdict = synthesize_verdict(fund_data, accum_prob, current_phase, ticker)
    synth = verdict["headline"]
    if fund_data:
        fund_data['synthesis'] = synth
        fund_data['synthesis_detail'] = verdict["detail"]
        fund_data['synthesis_color'] = verdict["color"]
        fund_data['synthesis_tier'] = verdict["tier"]

    # === שכבה 2: מלכודות פונדמנטליות (נגזרות מאותה סינתזה - ללא סתירות) ===
    fundamental_traps = []
    tier = verdict["tier"]
    if tier in ("STRONG_AVOID", "AVOID"):
        fundamental_traps.append(f"⚠️ **Value Trap**: {verdict['detail']}")
    elif tier in ("STRONG_BUY", "BUY"):
        fundamental_traps.append(f"✅ **שילוב חיובי**: {verdict['detail']}")

    # === רשימה מאוחדת (לתאימות לאחור עם קוד קיים שמשתמש ב-failure_warnings הגולמי) ===
    failure_warnings = wyckoff_traps + fundamental_traps
    if not wyckoff_traps and not fundamental_traps:
        failure_warnings = [f"✅ **שמיים נקיים**: לא זוהו מלכודות Wyckoff או פונדמנטליות עבור {ticker}. השילוב נראה תקין."]

    # === חישוב ATR דינמי לניהול סיכונים (14 יום) ===
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift(1)).abs()
    low_close = (df['Low'] - df['Close'].shift(1)).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = float(true_range.rolling(14).mean().iloc[-1]) if not pd.isna(true_range.rolling(14).mean().iloc[-1]) else close_price * 0.02

    stop_loss_price = close_price - (atr * 2)
    stop_loss_pct = ((stop_loss_price - close_price) / close_price) * 100
    tp1_price = close_price + (atr * 3.5)
    tp1_pct = ((tp1_price - close_price) / close_price) * 100
    tp2_price = close_price + (atr * 7)
    tp2_pct = ((tp2_price - close_price) / close_price) * 100
    rr_ratio = f"1:{round(abs((tp1_price - close_price) / (close_price - stop_loss_price)), 1)}"

    # === לוגיקת המלצה סופית (Action Plan) ===
    if "Distribution" in current_phase or "Markdown" in current_phase:
        rec = "STRONG SELL"
        action = "התרחקות מוחלטת (AVOID) או פתיחת פוזיציית שורט. המערכת מזהה פיזור מוסדי מובהק."
    elif accum_prob >= 75 and is_positive_phase:
        rec = "STRONG BUY"
        action = "כניסה מועדפת (High Conviction). ההסתברות לצבירה מוסדית אמיתית גבוהה מאוד. שקול כניסה אגרסיבית."
    elif accum_prob >= 65 and allowed:
        rec = "BUY"
        action = "פתח פוזיציה בהתאם לניהול הסיכונים. קיימת טביעת אצבע ברורה של כסף חכם לקראת מהלך."
    elif (50 <= accum_prob < 65) or (accum_prob >= 65 and not is_positive_phase):
        rec = "HOLD"
        action = "המתן. אמנם קיימת נוכחות של הון פנימי, אך התבנית הטכנית לא בשלה לפריצה מיידית."
    else:
        rec = "SELL"
        action = "הסתברות נמוכה לאיסוף. מומנטום הכסף החכם שלילי. חפש נקודות יציאה טקטית."

    reason = f"הסתברות מוסדית של {accum_prob}% מצביעה על {rec} בפאזת {current_phase}."

    # === הבטחת ברזל נוספת (Defense-in-Depth): rec לעולם לא יסתור את verdict ===
    # אם הסינתזה הקשיחה (synthesize_verdict) קבעה AVOID/STRONG_AVOID - חוסמים BUY/STRONG BUY
    # כאן באופן בלתי תלוי, גם אם לוגיקת ה-rec המקומית (מבוססת accum_prob/allowed) הגיעה למסקנה אחרת.
    if verdict["tier"] in ("STRONG_AVOID", "AVOID") and rec in ("STRONG BUY", "BUY"):
        old_rec = rec
        rec = "STRONG SELL" if verdict["tier"] == "STRONG_AVOID" else "SELL"
        action = (
            f"⚠️ המלצה שונתה אוטומטית מ-{old_rec} ל-{rec}: הסינתזה הקשיחה (Wyckoff + פונדמנטלי) "
            f"חוסמת קנייה במצב זה - '{verdict['headline']}'. {verdict['detail']}"
        )
        reason = f"המלצה מקורית ({old_rec}) נחסמה ע\"י הסינתזה הקשיחה בשל '{verdict['headline']}' בפאזת {current_phase}."

    # === תוכנית מסחר מדורגת ומלאה (3 רמות פירוט) ===
    # כניסה מדורגת: חצי עכשיו, חצי בפולבק קל
    entry_now = round(close_price, 2)
    entry_pullback = round(close_price - atr * 0.8, 2)
    # סטופ מדורג: סטופ ראשוני (טכני) + סטופ הדוק יותר אחרי TP1
    stop_initial = round(stop_loss_price, 2)
    stop_after_tp1 = entry_now  # break-even אחרי מימוש חלקי
    # יעדי שחרור חלקי
    tp1 = round(tp1_price, 2)   # שחרור 1/3
    tp2 = round(tp2_price, 2)   # שחרור 1/3
    tp3 = round(close_price + atr * 11, 2)  # יתרה - trailing
    # גידור: רמת היפוך תזה
    invalidation = round(close_price - atr * 2.5, 2)
    # גודל פוזיציה מומלץ לפי ביטחון (אחוז מהתיק, סיכון מוגבל)
    if rec == "STRONG BUY":
        pos_size_pct, risk_note = 8.0, "ביטחון גבוה - אך לעולם לא לסכן יותר מ-1.5% מהתיק על העסקה."
    elif rec == "BUY":
        pos_size_pct, risk_note = 5.0, "ביטחון בינוני-גבוה - סכן עד 1% מהתיק על העסקה."
    elif rec == "HOLD":
        pos_size_pct, risk_note = 2.5, "פוזיציית בדיקה (Starter) קטנה בלבד עד לאישור טרנד."
    else:
        pos_size_pct, risk_note = 0.0, "אין כניסה ללונג במצב זה."

    trade_plan = {
        # רמה 1 - בסיסי (תאימות מלאה לשדות הישנים)
        "basic": {
            "entry": entry_now,
            "stop": stop_initial,
            "stop_pct": round(stop_loss_pct, 2),
            "tp1": tp1, "tp1_pct": round(tp1_pct, 2),
            "tp2": tp2, "tp2_pct": round(tp2_pct, 2),
            "rr": rr_ratio,
        },
        # רמה 2 - מלא: כניסה/סטופ מדורגים, יעדי שחרור חלקי, גידור
        "full": {
            "entry_now": entry_now,
            "entry_pullback": entry_pullback,
            "stop_initial": stop_initial,
            "stop_after_tp1": stop_after_tp1,
            "tp1": tp1, "tp1_pct": round(tp1_pct, 2), "tp1_action": "שחרר 1/3 מהפוזיציה, העלה סטופ לנקודת הכניסה (Break-Even).",
            "tp2": tp2, "tp2_pct": round(tp2_pct, 2), "tp2_action": "שחרר 1/3 נוסף, הפעל Trailing Stop על היתרה.",
            "tp3": tp3, "tp3_pct": round(((tp3 - close_price) / close_price) * 100, 2), "tp3_action": "יתרה אחרונה - רכיבה על המגמה עם סטופ נגרר.",
            "invalidation": invalidation,
            "invalidation_note": f"אם המחיר נסגר מתחת ל-${invalidation} - התזה הופרה, צא במלואך.",
            "rr": rr_ratio,
            "timeframe": "5-20 ימי מסחר",
        },
        # רמה 3 - מלא + גודל פוזיציה
        "sizing": {
            "position_pct": pos_size_pct,
            "risk_note": risk_note,
            "max_loss_at_stop_pct": round(abs(stop_loss_pct), 2),
        },
    }

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
        "prob_engine": prob_engine,
        "dashboard": dashboard,
        "failure_warnings": failure_warnings,
        "wyckoff_traps": wyckoff_traps,
        "fundamental_traps": fundamental_traps,
        "replay": replay,
        "roadmap": roadmap,
        "fundamental": fund_data,
        "trade_plan": trade_plan,
        "verdict": verdict,
    }
