import pandas as pd
from scout_core import get_data, FactorEngine, BacktestConfig, check_phase_entry_allowed

def get_trading_recommendation(ticker: str) -> dict:
    """
    מודול המלצות מסחר מבוסס Wyckoff וציון מוסדי (CIS).
    מחזיר מילון עם ההמלצה והנתונים הרלוונטיים.
    """
    df = get_data(ticker, period="1y")
    if df is None or df.empty or len(df) < 60:
        return {
            "recommendation": "ERROR",
            "confidence": 0,
            "reason": "אין מספיק נתונים היסטוריים לניתוח הנכס (נדרשים לפחות 60 ימי מסחר).",
            "current_phase": "N/A",
            "cis_score": 0.0,
            "suggested_stop_loss": 0.0,
            "suggested_target": 0.0,
            "close_price": 0.0
        }

    engine = FactorEngine(BacktestConfig())
    factors = engine.compute(df)
    phases = engine.get_wyckoff_phase(df)
    cis_series = engine.composite_cis(factors, df)

    current_phase = str(phases.iloc[-1])
    cis_score = float(cis_series.iloc[-1])
    close_price = float(df['Close'].iloc[-1])

    # חישוב ATR (Average True Range) עבור הגדרת סטופ לוס ויעד רווח דינמיים
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift(1)).abs()
    low_close = (df['Low'] - df['Close'].shift(1)).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    
    atr_series = true_range.rolling(14).mean()
    atr = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else close_price * 0.02

    # מציע סטופ של 2 פעמים ה-ATR ויעד של 4 פעמים ה-ATR (יחס סיכוי/סיכון של 1:2)
    suggested_stop_loss = (atr * 2) / close_price * 100
    suggested_target = (atr * 4) / close_price * 100

    allowed = check_phase_entry_allowed(current_phase, "Balanced")
    
    positive_phases = ["Phase C", "Spring", "Phase D", "Phase E", "LPS", "SOS", "Breakout", "Markup", "Re-accumulation"]
    is_positive_phase = any(p in current_phase for p in positive_phases)

    # לוגיקת קבלת ההחלטות המחמירה
    if cis_score >= 75 and is_positive_phase:
        rec = "STRONG BUY"
        reason = "ציון מוסדי גבוה מאוד המשולב עם שלב Wyckoff חיובי. זרימת הון חכם מובהקת ומומנטום איסוף חזק."
    elif cis_score >= 65 and allowed:
        rec = "BUY"
        reason = "הציון המוסדי והשלב הטכני תומכים שניהם בכניסה. מומלץ לשקול פתיחת פוזיציה בזהירות בהתאם לניהול סיכונים."
    elif 50 <= cis_score < 65:
        rec = "HOLD"
        reason = "מצב ביניים או מעבר טכני. אין הכרעה מוסדית מובהקת לכיוון מסוים, כדאי להמתין לאיתות ברור יותר מהשוק."
    else:
        if any(p in current_phase for p in ["Markdown", "Distribution", "Heavy Supply"]):
            rec = "STRONG SELL"
            reason = "הנכס חווה פיזור סחורה מובהק ולחץ מכירות מוסדי אגרסיבי. סיכון גבוה מאוד למחזיקים בו."
        else:
            rec = "SELL"
            reason = "חולשה מוסדית ברורה וציון כוח נמוך. הנכס אינו מראה סימני איסוף כרגע וככל הנראה ימשיך לדשדש או לרדת."

    return {
        "recommendation": rec,
        "confidence": cis_score,
        "reason": reason,
        "current_phase": current_phase,
        "cis_score": round(cis_score, 1),
        "suggested_stop_loss": round(suggested_stop_loss, 2),
        "suggested_target": round(suggested_target, 2),
        "close_price": round(close_price, 2)
    }
