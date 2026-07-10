"""
============================================================
INSTITUTIONAL SCOUT PRO V27.1 (Parallel Scan + Countdown — סריקה מקבילית)
Streamlit app for advanced Wyckoff-style market analysis
Optimized for Google Cloud Run

V27.1 — חוויית המתנה חדשה + מנוע סריקה מקבילי ("תמצא לי" + סריקה ממוקדת):
  • אין תוצאות חלקיות: הסריקה רצה ב-thread רקע; הכרטיסיות מופיעות רק בסיום
    המלא (store→st.rerun, דפוס V25.7).
  • בזמן הסריקה: הודעה גדולה "מבצע סריקת שוק מלאה... זה עלול לקחת 1-3 דקות",
    שעון ספירה לאחור "⏳ זמן משוער שנותר: M:SS" שמתעדכן כל ~שנייה (st.empty +
    לולאה עם sleep), ו-progress bar עם אחוזים (התקדמות משוקללת בין השלבים).
  • מקביליות: ThreadPoolExecutor עם 10 workers מוריד את הנתונים לכל היקום
    במקביל (חימום מטמון get_cached_data) + Early Pruning (df ריק/<60 ברים נפסל
    לפני ניתוח Wyckoff); MarketScanner (הליבה, ללא שינוי) רץ אז על מטמון חם —
    ההאצה בלי לשכפל את לוגיקת הסורק. ScriptRunContext מוצמד ל-workers.
  • בסריקה הממוקדת גם שלב סינון-הצירים רץ בתוך הרקע (משקלים 0.5/0.3/0.2) —
    השעון מכסה את כל התהליך.
  • כפתורי ההרצה/איפוס/חזרה מנוטרלים (disabled) בזמן שסריקה פעילה.
  • לא שונה דבר מעבר לכך: מסך המפה, הרדאר, הניתוחים — ללא נגיעה.

V27.0 — רדאר סקטורים (כפתור רביעי בבית) + טקסונומיה גרנולרית + ניקוי:
  • טקסונומיה חדשה (_map_sectors_dict): 20 סקטורים גרנולריים ממופים מהיקום
    המובנה (515) — כולל בנקים אזוריים, נדל"ן מניב, ביוטק, בנייה למגורים,
    תעופה וביטחוניות, תשלומים ופינטק, מתכות יקרות ועוד. משמש גם את ציר
    הסקטור בסריקה הממוקדת (במקום 5 הסקטורים הישנים עם ~15 מניות).
  • כפתור "🌐 רדאר סקטורים": לוח חום — לכל סקטור Wyckoff מבני על ETF מייצג
    (SMH/KRE/XLE/XLRE/ITB/GDX...) + תמחור לפי 2 מובילות. פלט חד-משמעי:
    🚀 מתפוצץ / 🟢 הזדמנות / 🌱 איסוף / 😴 רדום / ⚠️ סכנה / 🔻 הפצה / 🔥 חוטף אש,
    עם ימים-בפאזה, מוכנות-למהלך, והערת ערך ("זול במובילות = הזדמנות ערך").
    ממוין מהחם לקר; כפתור "ניתוח" פותח ניתוח מלא של ה-ETF (מקור אמת יחיד).
  • דפוס store→rerun (V25.7) — הלוח יציב, בלי הבהובים.
  • ניקוי: מפת ה-CIS הכבדה (סריקת כל מניה בכל סקטור) וסריקת-הסקטורים הישנה
    הוסרו ממסך המפה — הוחלפו ברדאר (מהיר: ETF אחד לסקטור במקום מאות שליפות).

V26.1 — דעיכה מדורגת של ניעור (משוב: "Spring טרי · 25 ימים" עדיין סתירה):
        התיקון הקודם השאיר צוק בינארי (יום 25 "טרי", יום 26 "פג") ותווית "טרי"
        שגויה לניעור בן 5 שבועות. כעת סקאלה תלת-שלבית:
  • טרי (≤10 ברים): "Spring טרי" · score 70 · מוכנות "🟡 מתקרב — ממתין לאישור".
  • מזדקן (11-25): "עדיין בתוקף אך מזדקן — ככל שמתארך ללא SOS, הקריאה נחלשת" ·
    score יורד (70→58, אמצע 60→52 ⇒ ביטחון יורד) · מוכנות "🟠 ממתין זמן רב —
    הניעור מאבד תוקף" · rank יורד (2→1) ⇒ נדחק למטה במיון "קרוב למהלך".
  • פג (>25): "הקריאה פגה" → ACC_BASE (מ-V26.0).
  המעבר בין המסרים הדרגתי; אין עוד היפוך ביום אחד. BKNG/WULF מאומתים.

V26.0 — טריות אירועים + עיגון ספירת-ימים (תיקון הפער הלוגי "86 ימים בשלב C"):
        Spring הוא אירוע *נקודתי* — "86 ימים ברצף בפאזת ניעור, רחוק מפריצה" היה
        שילוב בלתי-אפשרי. שני שורשים תוקנו:
  • טריות אירועים: עקרון "המיקום גובר על אירוע ישן" (V21.1) חל כעת גם על אירועי
    Phase C — Spring/UTAD ישנים מ-25 ברים (~5 שבועות) אינם מכתיבים state.
    ניעור ישן ללא SOS ⇒ "הקריאה פגה" → ACC_BASE (שלב B) עם הסבר מפורש; אפ-ת'ראסט
    ישן ⇒ המבנה הנוכחי מכריע (ענפי המיקום). detect_wyckoff_events מחזיר age_bars.
  • עיגון-אירוע לספירת הימים: ACC_SPRING נספר מאז ה-Spring, ACC_CONFIRM מאז
    ה-SOS (אם קיים), DIST_WARNING מאז ה-Upthrust; ללא עוגן — ימי-טווח כמקודם.
    כך "6 ימים בפאזה" אחרי ניעור טרי, לא 86.
  • תווית מוכנות מתוקנת: Spring טרי = אזור הכניסה הקלאסי ⇒ "🟡 מתקרב — ניעור
    ממתין לאישור (SOS)" (לא "רחוק"). ACC_BASE נשאר "רחוק".
  • שער ה-OBV (V25.1) ורגרסיית BKNG/WULF — ללא שינוי, מאומתים.

V25.9 — "מוכנות למהלך" (Breakout Readiness): מ"מה הפאזה" ל"כמה קרוב למהלך".
        תווית מילולית בלבד (קרוב מאוד / מתקרב / רחוק / כבר במהלך) + ימים ברצף
        בפאזה — *ללא ציון מספרי* (לפי בקשת המשתמש). שכבת אפליקציה בלבד.
  • _breakout_readiness(ws): טהור — לפי מצב FSM, מיקום בטווח ודגל caution. רלוונטי
    רק לכיוון שורי (איסוף/Markup); בהפצה/ירידה/חוסר-מבנה לא מוצג.
  • _compute_days_in_phase(df,tr): ימים ברצף בפאזה — בטווח: ימים בתוך התמיכה/
    התנגדות; במגמה: ימים מעל/מתחת ל-SMA20. נשמר ב-wyckoff_state["days_in_phase"].
  • תצוגה: (א) מסלול טרייד — שורת סיפור "🚀 מוכנות למהלך" עם התווית + הימים +
    הסבר; (ב) הסורק — צ'יפ "מוכנות: … · N ימים" בכרטיס; (ג) הסריקה הממוקדת —
    צ'ק-בוקס "מיין לפי קרבה למהלך" שמדרג את הקרובים לפריצה קודם (rank פנימי,
    לא מוצג). כך "לא רק 'זו צבירה', אלא אילו נכסים הכי קרובים ליציאה למהלך".

V25.8 — תיקון באג: כפתור "📊 ניתוח מלא" בקרוסלה (סריקה ממוקדת + טכני/סקטור) לא הגיב.
  • הסיבה: הכרטיסים במסך הבית מנווטים ל-"🏠 בית" (dest_page) — אבל home_mode
    נשאר "focused"/"results", כך שמצב "check" (שצורך את ה-handoff ומריץ ניתוח)
    לא רץ. ה-handoff_ticker נקבע אך לא נצרך → "לא קורה כלום".
  • התיקון: בכל כפתורי הניתוח שמובילים ל-"🏠 בית" (קרוסלה, כרטיס בודד, וכפתור
    "ניתוח עומק" בסקטורים) — קובעים home_mode="check" לפני הניווט. כעת הלחיצה
    פותחת את מסך בחירת המסלול (⚡/🏦) והניתוח המלא, בעקביות עם שאר המערכת.
  • מסלול "תמצא לי" (dest=Trading Scout) לא נגע ונשאר תקין.

V25.7 — תיקון באג: הקרוסלה בסריקה הממוקדת הבהבה ונעלמה בסיום הסריקה.
  • הסיבה: הסריקה *והרינדור* של הקרוסלה קרו באותה ריצה עם ה-spinner/progress
    הזמניים — ה-placeholders שנוקו התנגשו עם הקרוסלה בעץ האלמנטים של Streamlit,
    והיא "יותמה" (הופיעה לרגע ונעלמה).
  • התיקון: אימוץ הדפוס המוכח ממסלול "תמצא לי" — סורקים ומסננים בלחיצה, שומרים
    את התוצאות ב-session_state, ואז st.rerun() לריצה נקייה שמרנדרת את הקרוסלה
    מה-state בלבד (בלי UI זמני מעליה). כפתורי החצים/דפדוף יציבים כעת.
  • רמז עדין: אם משנים פילטר בלי ללחוץ "הרץ" — התוצאות הקודמות נשארות עם הודעה
    לרענן. שאר הסורקים (תמצא לי / טכני / סקטוריאלי) נבדקו — תקינים, לא נגעתי בהם.

V25.6 — יקום מובנה מורחב: S&P 500 + Nasdaq 100 (~515 מניות ייחודיות) מוטמע
        בקוד, ללא סקריפט/קובץ. משפיע על שלושת מסלולי הסריקה מיידית.
  • SP500_NDX100_TICKERS: רשימה קבועה תואמת-yfinance (BRK-B/BF-B בפורמט דש),
    ממוזגת ליקום ברירת המחדל יחד עם רשימות האפליקציה והסחורות (GLD/SLV/IAU).
  • כיסוי: כמעט כל שווי השוק האמריקאי הגדול/בינוני. טיקר שהוסר/שונה — מדולג חינני.
  • ה-cap של הסריקה הממוקדת ל"הכל" הועלה מ-300 ל-כל היקום (515) — עקבי עם "תמצא לי".
  • שדרוג אופציונלי נשמר: מי שרוצה כיסוי דינמי מלא של נאסד"ק יכול עדיין להעלות
    nasdaq_universe.json (build_universe.py) — הוא ימוזג מעל הרשימה המובנית.

V25.5 — יקום סריקה מתצורה חיצונית (נאסד"ק מסונן) — משפיע על שלושת מסלולי הסריקה:
  • _build_market_universe טוען nasdaq_universe.json אם קיים (מיוצר offline ע"י
    build_universe.py לפי מחיר≥$5, שווי≥$1B, ווליום-דולרי≥$20M), ממוזג עם היקום
    האצור (שמירת סחורות/ETF). חסר/פגום → נפילה חיננית ל-~146 האצורות (לא קורס).
  • הניתוח עצמו תמיד נשלף חי — קובץ היקום קובע רק *מי מועמד לסריקה*, לא נתונים.
  • שקיפות: שורת סטטוס בכל מסלולי הסריקה — מספר מניות + תאריך עדכון, ואזהרה אם
    הקובץ ישן מ-14 יום ("מומלץ לרענן; הניתוח אינו מושפע").
  • build_universe.py (קובץ נפרד להרצה מקומית + העלאה לגיטהאב): דילוג-מוקדם —
    מחיר+ווליום קודם (שליפה קלה), ושליפת שווי-שוק רק לעוברים.

V25.4 — סריקה ממוקדת (כפתור שלישי בבית) — סריקת שוק שמשלבת את כל הצירים:
  • כפתור "🎯 סריקה ממוקדת" במסך הנחיתה (מצב home חדש "focused"), נפרד לחלוטין
    מחיפוש הערך ("תמצא לי") ומהסורק הטכני.
  • 4 צירים, כל אחד עם "הכל" (ברירת מחדל) או ערך ספציפי: פאזת Wyckoff (סלוט 7
    פאזות), איכות עסקית A-F (multiselect), תמחור זול/הוגן/יקר (multiselect),
    וסקטור. השארת הכל על ברירת המחדל = סריקה כללית; בחירה בכל ציר = חיתוך משולב.
  • _focused_filter: מנוע טהור (ניתן לבדיקה) — מסננים זולים קודם (תמחור מתוצאת
    הסריקה + סקטור), ואז יקרים (FSM מבני + איכות מותאמת-Durability) עד cap=40.
  • מקור אמת יחיד: פאזה מ-_quick_structural_state, איכות מ-_quality_adjusted —
    עקבי עם מסכי הניתוח. סקטור ספציפי מצמצם את יקום הסריקה (מהיר יותר).
  • ביצועים: סריקה נשמרת ב-session; שינוי פאזה/איכות/תמחור מסנן מיידית ללא
    סריקה חוזרת (רק שינוי סקטור מפעיל סריקה מחדש). כפתור "אפס הכל".
  • MAP_SECTORS הוחלץ לפונקציה ברמת המודול (_map_sectors_dict) לשימוש משותף.

V25.3 — סריקה לפי פאזת Wyckoff (בסורק הטכני בלבד — נפרד מחיפוש הערך בבית):
  • שני מסלולי סריקה טכנית: "🔍 סריקה כללית" (כמו היום) / "🎯 סריקה לפי פאזת
    Wyckoff" — בחירה בפאזה פותחת סלוט (selectbox) עם 7 הפאזות המבניות.
  • מקור אמת יחיד גם בסריקה: הסינון מאומת מול ה-FSM המבני (_quick_structural_state,
    cache ~30ד'), לא מול תוויות המנוע הגולמי — אין סתירה בין הסורק לניתוח.
  • ביצועים: במצב פאזה הסורק מחזיר עד 40 מועמדים (במקום 20) כדי להגדיל סיכוי
    התאמה; אימות ה-FSM רץ רק על ששרדו את הסריקה, עם progress. החלפת פאזה אחרי
    סריקה מסננת מיידית (מהמטמון) בלי סריקה חוזרת.
  • _filter_results_by_phase: פונקציה טהורה (ניתנת להזרקת quick_fn) — נבדקת.
  • מצב ריק ידידותי: "אין כרגע מניות בפאזה X בין המועמדים — הרחב סריקה או החלף פאזה."
  • חל גם על הסריקה הסקטוריאלית (radio+סלוט משותפים לכל הסקטורים; pool 12 במצב
    פאזה) — ושורות תוצאות הסקטור עברו לתגית הפאזה המבנית האחידה (הוסר
    pick_phase_caution הישן משם; מקור אמת יחיד בכל נקודות הסריקה).

V25.2 — ייצוב + פוליש של הפיצול (תיקון סתירות BKNG שנותרו):
  • טקסטים של Caution קצרים וברורים: "⚠️ שלב D בזהירות — תיקון אפשרי. המתן
    לאישור (שפל גבוה-יותר + נפח דועך)." (במקום משפט ארוך).
  • "סכין נופלת" מותר *רק* בשבירה מאושרת (DIST_ACTIVE/MARKDOWN). בכל מצב אחר
    (כולל DIST_WARNING וכולל שלב D בזהירות) — מוחלף במסר מדוד, בכל המסכים.
  • _calibrate_verdict_tone שוכתב: מסנכרן צ'יפ ביטחון תמיד לפאזה המבנית; מוריד
    תג קנייה ל-WATCH כשהמצב "בזהירות"; לעולם לא משדרג לכיוון קנייה (הבטחת הליבה).
  • מסלול טרייד — הערך מוצג כהקשר החזקה בלבד: "מתאים להחזקה ארוכת-טווח, אך
    התזמון לטרייד עדיין לא בשל". מסלול השקעה — וויקוף כהקשר תזמוני בלבד.
  • סורק: תגיות התאמה מדויקות — "⚡ טרייד + זהירות" / "⚡ טרייד · 🏦 השקעה" /
    "🏦 השקעה" / "⏳ מעקב" (כולל דגל caution ב-FSM המהיר).

V25.1 — חיזוק הפיצול + שער זרימת-כסף (תיקון סתירת BKNG הנוכחית):
  • שער OBV לזיהוי הפצה: אפ-ת'ראסט/BC בפסגה = הפצה *רק אם* זרימת הכסף (OBV)
    או השבועי מאשרים היצע. OBV חיובי + שבועי לא-דובי ⇒ ניעור/כישלון-פריצה בתוך
    איסוף = שלב D *בזהירות*, לא "אזהרת הפצה". (הפצה עם OBV עולה היא סתירה.)
  • דגל "בזהירות" (caution): מצב שורי עם דחייה/תיקון בפסגה → התווית הופכת
    "שלב D — בזהירות", הסטטוס caution, והשורה התחתונה מזהירה — אך התוכנית נשמרת.
    כך BKNG במסלול טרייד = "שלב D + זהירות" (לא סכין נופלת), ובמסלול השקעה = A + החזק.
  • סף המיקום ל-שלב D רוכך (0.62→0.55) כדי לזהות LPS אחרי פולבק תוך שמירת OBV חיובי.

V25.0 — פיצול מסלולים (טרייד/השקעה) — פתרון הסתירות הלוגיות (משוב BKNG #2).
        האבחון: כשוויקוף (תזמון קצר) והערך (שווי ארוך) חלוקים — שניהם נכונים
        במקביל, אך אסור לערבב אותם למסר אחד ("סכין נופלת" מול "שילוב אידיאלי").
        בנוסף תוקנו סתירות פנימיות אמיתיות. הכל בשכבת האפליקציה; הליבה לא נגעה.
  • מסך בחירת מסלול: אחרי כל ניתוח (הקלדה או קליק מסריקה) — 2 כפתורים בלבד:
    "🏦 ניתוח להשקעה ארוכת טווח" / "⚡ ניתוח לטרייד (סווינג)". החלפה בכל שלב.
  • מסלול טרייד: וויקוף מבני בראש (שורה תחתונה, חיוגים, תוכנית, playbook); הערך
    מוצג כהקשר החזקה בלבד. חיוג הערך לא ישדר "שילוב אידיאלי" כשהתזמון שלילי
    (_horizon_safe_vq_sub). הבאנר הפונדמנטלי הישן הוסר מהמסלול (ערבב שווי לתזמון).
  • מסלול השקעה (render_invest_lens): ערך+איכות בראש — verdict השקעתי, חיוגי
    איכות/תמחור/תזמון-הקשר, מטריצה+פילרים+עקביות+Reverse-DCF במרכז; וויקוף
    כשורת הקשר תזמון בלבד + מעבר למסלול טרייד לתזמון מפורט.
  • כיול טון (_calibrate_verdict_tone): DIST_WARNING בביטחון <60 ⇒ "אזהרה מדודה —
    המבנה טרם נשבר", לא "סכין נופלת" (השמור לשבירה מאושרת). צ'יפ ה"ביטחון" בבאנר
    מסונכרן תמיד לביטחון-הפאזה המבני (סוף הסתירה "ביטחון גבוה" מול חיוג 46).
    לעולם לא משדרג לכיוון קנייה — הבטחת הברזל של הליבה נשמרת.
  • הסורק ("תמצא לי"): כל כרטיס מקבל תגית תזמון מבני (FSM מהיר, cache 30ד') +
    תגית התאמה ("מתאים ל: ⚡ טרייד · 🏦 השקעה" / "🏦 השקעה בלבד — תזמון שלילי" /
    "⏳ מעקב בלבד") — הסורק כבר לא ממליץ בסתירה לניתוח.
  • ראיות סותרות (_weekly_conflict_note): כשההקשר השבועי מנוגד לקריאה היומית —
    נאמר מפורשות שזו הסיבה לביטחון הנמוך (סוף הסתירה "שבועי תומך איסוף" מול
    "אזהרת הפצה" ללא הסבר).

V24.0 — כיול היסטורי (Reliability, רכיב 2 של Tier 3). "היסטורית, כשהמניה הזו
        הגיעה לשלב הזה — מה קרה ב-20 הימים הבאים?". שכבת אפליקציה בלבד; הליבה
        לא נגעה, ונעשה שימוש ב-calculate_phase_followthrough הקיים.
  • זהירות lookahead: calculate_phase_followthrough הוא walk-forward מובנה — לכל
    נקודה בעבר ההצלחה נמדדת רק על החלון העתידי שלה (closes[i+1:i+1+horizon]),
    והלולאה עוצרת ב-n-horizon, כך שהבר הנוכחי והעתיד הלא-ידוע שלו לעולם לא
    נספרים. איני מוסיף שום מידע עתידי משלי — רק מאגד תוצאות היסטוריות.
  • _phase_followthrough_cached: עטיפה עם cache חזק (שעה) — מושכת היסטוריה,
    מחשבת פאזת מנוע לכל בר, ומריצה את ה-followthrough. עמיד-כשל (כל כשל → {}).
  • compute_phase_reliability: ממפה מצב מבני → מפתחות פאזה, מאגד total/success,
    ומחזיר שיעור הצלחה + summary. פחות מ-4 דגימות → "אין די דגימות היסטוריות".
  • _apply_reliability_to_confidence: modifier *קטן* לביטחון (אנטי-הגזמת-ביטחון) —
    היסטוריה חזקה (≥65%, ≥6 דגימות) +5; חלשה (<40%) −8; אחרת 0. *לא* משנה
    state/status (שמירה על העיקרון של לא-להציף UNDETERMINED). WULF (UNDETERMINED)
    ⇒ אין מפתחות ⇒ אין שינוי (מוגן).
  • תצוגה: שורת "📊 היסטורית" בסיפור (רק כשיש די דגימות). המסכים הבסיסיים
    נטענים מהר; ה-followthrough תחת cache חזק (lazy per-ticker).
  • נבדק: BKNG (Phase D 78% ⇒ ביטחון +5), WULF (מוגן, ללא שינוי), חלש (25% ⇒ −8),
    <4 דגימות ⇒ מדולג, כשל שליפה ⇒ חינני.

V23.0 — איכות רב-שנתית (Durability, רכיב 1 של Tier 3). מוסיף את ממד הזמן לאיכות:
        עקביות FCF (חיובי בכל אחת מ-5 השנים?) ומגמת מרווחים (חפיר מתחזק/נשחק).
        נכנס כ-MODIFIER פנימי לציון האיכות מ-Tier 2 — הציון נשאר A-F, רק מדויק
        יותר. שכבת אפליקציה בלבד; הליבה לא נגעה. (רכיב 2 — כיול היסטורי — נדחה ל-3.1.)
  • _durability_from_statements (לוגיקה טהורה, נבדקת): מקבל cashflow+financials,
    סופר FCF=OCF+capex חיובי לאורך עד 5 שנים, מודד מגמת מרווח תפעולי, ומחזיר
    modifier בנקודות ציון (-20..+10) + פירוט.
  • compute_durability: עטיפת שליפה עם cache חזק (24ש' — דוחות משתנים רבעונית),
    עמיד-כשל לחלוטין. אם אין ≥3 שנות נתונים → "אין די היסטוריה לכיול עקביות"
    (modifier=0, בלי קריסה) — ונשארים עם דירוג ה-snapshot מ-Tier 2.
  • _quality_adjusted: ציון סופי = snapshot + modifier, ממופה מחדש ל-A-F. זהו
    הדירוג היחיד שמוצג בכל המסכים (חיוג שלישי, סיפור, מסקנה, שכנוע).
  • הפירוט הרב-שנתי (FCF X/5, מגמת מרווחים, שורת snapshot→modifier→adjusted)
    מוצג רק ב-expander "🏢 ניתוח ערך ואיכות". המסכים הראשיים נטענים מהר (Tier 2),
    והעומק הרב-שנתי תחת cache. 3 החיוגים ומבנה הסיפור לא השתנו.
  • נבדק: BKNG ⇒ A + FCF 5/5 (עקבי); WULF ⇒ F + FCF 0/5 מרווחים נשחקים (מוגן,
    UNDETERMINED); JNJ ⇒ snapshot A, עקביות 5/5 ⇒ A מאושר.

V22.0 — שכבת ערך ואיכות (סגנון ניתוח-ערך). ממלאת את החיוג השלישי בעומק אמיתי,
        ללא נגיעה בליבה ובלי קריאות רשת נוספות (מבוסס fd['_raw'] שכבר נשאב).
        עיקרון: וויקוף = תזמון; ערך/איכות = שכנוע. האיכות *אינה* מזיזה כניסה/סטופ/יעד.
  • compute_quality_score: ציון איכות לפי עקרונות ערך — FCF (יצירת מזומן),
    חפיר/כוח-תמחור (מרווח תפעולי מול הסקטור), תשואה על הון (ROE), חוזק מאזן
    (מינוף), צמיחה. מחושב פנימית 0-100 ומוצג כ-A-F.
  • compute_implied_growth (Reverse-DCF): מנרמל מחיר ל-1, פותר את צמיחת ה-FCF
    הגלומה (r=9%, צמיחה סופית 2.5%, 10 שנים), ומשווה לצמיחה בפועל ⇒ זול/הוגן/יקר.
    אין FCF חיובי ⇒ "לא ניתן לתמחר לפי תזרים" (אות לעסק ספקולטיבי).
  • 3 חיוגים נשמרים נפרדים. החיוג השלישי מציג כעת ערך + ציון איכות (A-F) +
    מסקנת השילוב המילולית (לוגיקת מטריצה).
  • הסיפור העקבי: נוספה שורת "🏢 העסק" (איכות + Reverse-DCF) ושורת "🎯 שכנוע"
    (להחזיק Runner מול לקחת רווח — נגזר מהאיכות, מופיע רק כשיש תוכנית פעילה).
  • מטריצת ערך×איכות (ריבוע צבעוני) — רק ב-expander "🏢 ניתוח ערך ואיכות"
    (בית + Trading Scout); במסכים הראשיים רק המסקנה המילולית + צבע.
  • נבדק: BKNG ⇒ איכות A + זול (החזק Runner); WULF ⇒ איכות F + ספקולטיבי
    (טקטי, קח רווח) ונשאר UNDETERMINED מוגן.

V21.1 — תיקון משוב BKNG: סתירה לוגית (אותה מניה הוצגה גם בשלב C וגם D).
        שני תיקונים, ללא נגיעה בליבה (הכל בשכבת האפליקציה):
  1. לוגיקת ה-FSM — "המיקום הנוכחי גובר על אירוע ישן": בתוך טווח מסחר,
     מחיר בחצי העליון (≥62%) עם OBV חיובי ⇒ שלב D (ACC_CONFIRM) — גם אם
     ה-Spring היה מזמן. Spring (שלב C) נקבע רק כשהמחיר עדיין בחצי התחתון
     (≤38%) או מתאושש דרך האמצע. תוקן הבאג שבו אירוע Spring ישן "חטף" את
     הסיווג ל-C כשהמחיר כבר התקדם לעבר הפריצה.
  2. מקור אמת יחיד לפאזה — wyckoff_state["phase_he"] (מהמנוע המבני) הוא כעת
     הפאזה היחידה שמוצגת בכל המסכים: באנר, drill-down, מפת דרכים, ותוכנית
     המסחר ב-Trading Scout. ה-trading_scout ממשיך לחשב הסתברויות/מנגנון
     ברקע, אך התווית המוצגת באה ממקור אחד. נוסף _structural_roadmap
     (היינו/אנחנו/היעד קוהרנטי עם ה-state). גם טקסט ה-verdict (synthesize_verdict)
     מקבל כעת את הפאזה המבנית — כך שאף פרוזה לא מזכירה פאזה גולמית סותרת.
     הליבה (get_wyckoff_phase) נשארת לשקיפות בלבד ("קריאת מנוע גולמית").
     תוצאה: BKNG ⇒ שלב D בכל המסך, ללא אזכור C; WULF ⇒ נשאר UNDETERMINED מוגן.

V21.0 — היפוך ההיררכיה: מנוע מבני (טווח מסחר + רצף אירועים) הוא כעת הקובע
        הראשי של הפאזה; ה-CIS (מהליבה) הופך לקלט *מאַשר*, לא קובע. כל השינויים
        בשכבת האפליקציה בלבד — FactorEngine, get_wyckoff_phase, composite_cis
        והליבה המוגנת אינם נוגעים. עיקרון-על: הפאזה נקבעת קודם מבנית (שערים
        קשיחים), ורק אז מחושב ביטחון — כך CIS=100 לבדו לא יוצר פאזת איסוף.
  • מכונת מצבים (8 states): MARKDOWN / ACC_BASE / ACC_SPRING / ACC_CONFIRM /
    MARKUP / DIST_WARNING / DIST_ACTIVE / UNDETERMINED. הקביעה *מודעת-רצף*:
    נשלטת ע"י האירוע המכריע האחרון + מיקום המחיר (SOS אחרי SOW ישן ⇒ שורי).
  • אישור רב-טווחי (gate): _to_weekly (resample ללא רשת) + assess_weekly_context.
    השבועי מבדיל איסוף-חוזר (תיקון ב-WEEKLY_MARKUP) מהפצה (WEEKLY_TOPPING).
  • ציון ביטחון רציף (0-100), נפרד מ-CIS: מבנה 35% · VSA 20% · שבועי 20% ·
    איכות-טווח 10% · CIS 10% (מאַשר) · הסכמת-מנוע 5%. ספים 70/50/30.
  • סטופים ויעדים *מבוססי-מבנה* (לא ATR): סטופ מתחת לשפל הניעור/התמיכה;
    יעדים מ-Cause & Effect + ההתנגדות. תוכנית נוצרת רק ל-ACC_SPRING/CONFIRM
    בביטחון ≥50 בתוך טווח — אחרת אין תוכנית כפויה.
  • Playbook 'אם-אז' לכל מצב: שורה תחתונה קודם, מסלול צפוי, ומה לעשות אם
    משתבש (לחזק / לצאת / לצאת חלקית) + ציפיית זמן.
  • ממשק: 3 חיוגים נפרדים (טביעת אצבע מוסדית / ביטחון פאזה / ערך) + סיפור עקבי
    שמתחיל תמיד מהשורה התחתונה הפשוטה. WULF ⇒ UNDETERMINED, ביטחון נמוך,
    "טביעת כסף חכם חזקה אך אין מבנה טווח תקין", ללא כניסה.

V20.4 — שער עקביות פאזה (Phase Coherence Gate) — תיקון משוב WULF #2:
        כשהמנוע נותן תווית פאזה *בטוחה* אך *סותרת את המבנה* — המערכת לא כופה
        אותה, אלא אומרת "אין פאזה מאושרת, ממתינים לאישור" וממליצה לסרוק שוב
        ביום המסחר הבא. הכל בשכבת האפליקציה; הליבה לא נגעה.
  • assess_phase_coherence: תווית תלוית-טווח (Re-accumulation/LPS/BUEC/Phase B)
    שנכפית כשאין טווח מסחר אמיתי (מהלך פרבולי >55% רוחב, או <=2 חציות אמצע) —
    מסומנת כלא-עקבית. LPS/BUEC הם 'נקודת תמיכה אחרונה' *בתוך* טווח — בלי טווח אין LPS.
  • *מכויל שלא לכפות יתר על המידה*: תוויות מגמה (Markup/Markdown) ותוויות היפוך
    (Spring/Phase C/A) אינן נבדקות; מקרי-גבול (רוחב 45-55%) עוברים. נבדק על מספר
    תרחישים — תופס את WULF (גם כשאזהרת ההפצה לא נדלקת) ולא פוסל איסוף-חוזר אמיתי בטווח.
  • _RESCAN_HINT: בכל מצב "אין פאזה מאושרת" (מעבר/הפצה/אי-עקביות) נוספת המלצה
    מפורשת לסרוק שוב ביום המסחר הבא במקום לכפות פאזה.
  • הפאזה לתצוגה (display_phase) מוזרמת גם לבאנר ההכרעה ולנקודות הניתוח — כך
    שהצ'יפ "Wyckoff: ..." והנקודה "📍 פאזה נוכחית" משקפים "אין פאזה מאושרת", לא תווית כפויה.

V20.3 — שכבת ניתוח Wyckoff מעמיק (מבוססת מחקר על המתודולוגיה הקנונית:
        Wyckoff Analytics / StockCharts ChartSchool / Tom Williams VSA).
        כל התוספות בשכבת האפליקציה — FactorEngine והליבה המוגנת לא נגעו.
  1. Trading Range Engine (detect_trading_range): מזהה תמיכה/התנגדות/רוחב/מיקום
     המחיר בטווח — היסוד שכל אירועי Wyckoff עוגנים אליו.
  2. זיהוי אירועים מבניים (detect_wyckoff_events): Spring/Shakeout, Upthrust/UTAD,
     SOS/פריצה, SOW/שבירה — האירועים שמצדיקים את הפאזה (המנוע נתן פאזות בלבד, לא אירועים).
  3. VSA Bar Classifier (classify_vsa_bars): Selling/Buying Climax, Stopping Volume,
     No Demand/No Supply, Upthrust, SOS, Effort vs Result — קריאת נר-נר לפי Tom Williams.
  4. יעדי Cause & Effect (wyckoff_cause_effect_targets): השלכת רוחב הטווח (פרוקסי
     לספירת P&F אופקית) ליעדי מחיר שמרני/בסיס/מורחב — חלופה מתודולוגית ליעדי ה-ATR.
  5. שולב כ-expander "🔬 ניתוח Wyckoff מעמיק" במסכי "תבדוק לי" ו-Trading Scout.

V20.2.1 — תיקון מיקוד לסיווג פאזה (משוב WULF):
  • שכבת האימות (refine_wyckoff_phase) הורחבה לזיהוי "סיכון הפצה / תיקון בנפח גבוה":
    כשהמנוע מתייג המשך-עלייה (Re-accumulation/Phase D/E) אך הפולבק עמוק (≥10% מהשיא)
    ובנפח מכירות מתרחב — המערכת *לא כופה* תווית שורית אלא מסמנת "אין פאזה מאושרת,
    ממתינים לאישור" עם ראיות. שורש הבעיה: ענף ה-Re-accumulation בליבה בודק רק נפח נר-בודד
    וללא תקרת עומק לפולבק (הליבה לא שונתה — התיקון בשכבת האפליקציה בלבד).
  • עיקרון חדש: כשאין פאזה מובהקת, המערכת אומרת זאת מפורשות ("יצאנו מ-X / ממתינים ל-Y").
  • סגירת פער הצגה: מסלול הסריקה (קרוסלה/Swipe/סקטור) הציג עד כה את תווית המנוע הגולמית
    ולא עבר דרך שכבת האימות — לכן WULF הופיע כ-"Re-accumulation". נוסף pick_phase_caution
    שמחיל את אותו זיהוי "סיכון הפצה" גם על כרטיסי הסריקה (תווית + צ'יפ אזהרה במקום "🔥 איסוף חזק").

V20.2 — שיפורים מבוססי משוב שטח (סבב ראשון, סוחר וויקוף 1-3 שנות ניסיון):
  1. דיוק זיהוי פאזות: שכבת אימות (Confirmation Overlay) מעל מנוע הליבה
     שמשדרגת מצבי "TRANSITION" שגויים כשמבנה המחיר/נפח ברור (תיקון "בעיית WULF"),
     מבלי לגעת במנוע ה-FactorEngine המוגן.
  2. הסבר "למה הפאזה הזו": Evidence Engine שמפרט נפח, מחיר, ספיגה, OBV, RS.
  3. נתונים: רצועת סטטוס טריות (Data Freshness) + אזהרת נתון חסר/מיושן + רבעון אחרון שדווח.
  4. CIS: מפענח משמעות הציון ("מה אומר 78") + פירוט פקטורים ("למה קיבלתי את הציון").
  5. תוכנית מסחר Swing ישימה: כניסה/סטופ/יעדים מדורגים + תרחישי Shakeout/Breakout
     + הפרדה ברורה בין וויקוף (קצר-בינוני) לפונדמנטלי (ארוך).
  6. סריקה: הדגשת מניות בפאזת C / Spring / Shakeout / איסוף חזק + Macro Technical Radar קל.
  כל השינויים בשכבת האפליקציה בלבד — קבצי הליבה (scout_core / market_scanner / trading_scout)
  לא שונו כדי לשמר את ה-IP והיציבות.
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
import time as _time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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

    .orb-check .stButton > button, .orb-find .stButton > button, .orb-focus .stButton > button, .orb-sectors .stButton > button {
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
    .orb-focus .stButton > button {
        width: 190px !important; height: 190px !important; font-size: 1.4rem !important;
        background: radial-gradient(circle at 35% 30%, #34d399, #059669) !important;
        color: #04121f !important;
        box-shadow: 0 14px 50px rgba(16,185,129,0.5), inset 0 -8px 22px rgba(0,0,0,0.2) !important;
    }
    .orb-focus .stButton > button:hover {
        transform: translateY(-6px) scale(1.04); filter: brightness(1.08);
        box-shadow: 0 22px 64px rgba(16,185,129,0.65), inset 0 -8px 22px rgba(0,0,0,0.2) !important;
    }
    .orb-sectors .stButton > button {
        width: 190px !important; height: 190px !important; font-size: 1.4rem !important;
        background: radial-gradient(circle at 35% 30%, #a78bfa, #7c3aed) !important;
        color: #0b0420 !important;
        box-shadow: 0 14px 50px rgba(139,92,246,0.5), inset 0 -8px 22px rgba(0,0,0,0.2) !important;
    }
    .orb-sectors .stButton > button:hover {
        transform: translateY(-6px) scale(1.04); filter: brightness(1.08);
        box-shadow: 0 22px 64px rgba(139,92,246,0.65), inset 0 -8px 22px rgba(0,0,0,0.2) !important;
    }
    .sector-row { background: rgba(15,23,42,0.55); border-radius: 12px; padding: 10px 14px;
        margin-bottom: 8px; }
    .sector-head { font-size: 1.02rem; }
    .sector-etf { color: #94a3b8; font-size: 0.85rem; }
    .sector-sub { color: #cbd5e1; font-size: 0.86rem; margin-top: 4px; }
    .sector-note { color: #fbbf24; font-size: 0.82rem; margin-top: 4px; }

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

    /* ============================================================
       V20.2 FEEDBACK COMPONENTS (Institutional Minimalist preserved)
       ============================================================ */

    /* --- רצועת סטטוס נתונים (Data Freshness) --- */
    .data-status {
        display: flex; flex-wrap: wrap; align-items: center; gap: 10px;
        background: var(--glass); border: 1px solid var(--glass-border);
        border-radius: 14px; padding: 10px 14px; margin: 6px 0 14px 0;
        backdrop-filter: blur(6px);
    }
    .ds-chip {
        display: inline-flex; align-items: center; gap: 6px;
        font-size: 0.86rem; color: var(--txt-2); font-weight: 600;
        background: rgba(255,255,255,0.03); border: 1px solid var(--line);
        border-radius: 10px; padding: 5px 11px;
    }
    .ds-chip b { color: var(--txt-1); font-weight: 700; }
    .ds-fresh  { border-color: rgba(34,197,94,0.4);  color: var(--pos-soft); }
    .ds-warn   { border-color: rgba(234,179,8,0.45);  color: var(--warn-soft); }
    .ds-stale  { border-color: rgba(239,68,68,0.5);   color: #fca5a5; background: rgba(239,68,68,0.06); }
    .ds-fresh b, .ds-warn b, .ds-stale b { color: inherit; }

    /* --- בלוק ראיות פאזה (Why this phase) --- */
    .phase-evidence {
        background: var(--glass); border: 1px solid var(--glass-border);
        border-radius: var(--radius); padding: 18px 20px; margin: 4px 0 8px 0;
        backdrop-filter: blur(8px); box-shadow: var(--shadow);
    }
    .pe-head { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom: 6px; }
    .pe-phase-pill {
        font-weight: 800; font-size: 1.05rem; color: #0f172a;
        background: var(--accent); border-radius: 10px; padding: 4px 12px;
    }
    .pe-phase-pill.bear { background: var(--neg); color: #fff; }
    .pe-phase-pill.neut { background: rgba(148,163,184,0.25); color: var(--txt-1); }
    .pe-refined-tag {
        font-size: 0.78rem; font-weight: 700; color: var(--warn-soft);
        border: 1px dashed rgba(234,179,8,0.55); border-radius: 8px; padding: 2px 8px;
    }
    .pe-summary { color: var(--txt-2); font-size: 0.95rem; line-height: 1.7; margin: 6px 0 12px 0; }
    .pe-item {
        display: flex; gap: 10px; align-items: flex-start; padding: 7px 0;
        border-top: 1px solid var(--line); font-size: 0.93rem; line-height: 1.6;
    }
    .pe-item:first-of-type { border-top: none; }
    .pe-ico { flex: 0 0 auto; font-size: 1rem; margin-top: 1px; }
    .pe-pos .pe-ico { color: var(--pos-soft); }
    .pe-neg .pe-ico { color: #fca5a5; }
    .pe-neu .pe-ico { color: var(--txt-3); }
    .pe-label { color: var(--txt-1); font-weight: 700; }
    .pe-val { color: var(--accent); font-weight: 800; }

    /* --- כרטיס משמעות CIS --- */
    .cis-meaning {
        display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
        background: var(--glass); border: 1px solid var(--glass-border);
        border-radius: var(--radius); padding: 16px 20px; margin: 6px 0;
        backdrop-filter: blur(8px);
    }
    .cm-num { font-size: 2.6rem; font-weight: 900; line-height: 1; }
    .cm-body { flex: 1 1 240px; }
    .cm-band { font-weight: 800; font-size: 1.05rem; }
    .cm-meaning { color: var(--txt-2); font-size: 0.92rem; line-height: 1.65; margin-top: 3px; }
    .cm-scale { display:flex; height: 8px; border-radius: 6px; overflow:hidden; margin-top:10px; width:100%; }
    .cm-seg { flex:1; }

    /* --- תוכנית סווינג / תרחישים --- */
    .swing-sep {
        display:flex; align-items:center; gap:10px; margin: 18px 0 8px 0;
        font-weight: 800; font-size: 1rem; color: var(--txt-1);
    }
    .swing-sep .sep-tag {
        font-size: 0.72rem; font-weight: 700; padding: 2px 9px; border-radius: 8px;
        border: 1px solid var(--line-strong); color: var(--txt-2);
    }
    .swing-sep .tag-short { color: var(--accent); border-color: var(--accent-soft); }
    .swing-sep .tag-long  { color: var(--pos-soft); border-color: rgba(34,197,94,0.4); }
    .scenario-grid { display:grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 6px; }
    @media (max-width: 720px) { .scenario-grid { grid-template-columns: 1fr; } }
    .scenario-card {
        border: 1px solid var(--line); border-radius: 16px; padding: 14px 16px;
        background: rgba(255,255,255,0.02);
    }
    .scenario-card.bull { border-color: rgba(34,197,94,0.35); background: rgba(34,197,94,0.05); }
    .scenario-card.bear { border-color: rgba(239,68,68,0.35); background: rgba(239,68,68,0.06); }
    .sc-title { font-weight: 800; font-size: 0.98rem; margin-bottom: 6px; }
    .sc-title.bull { color: var(--pos-soft); }
    .sc-title.bear { color: #fca5a5; }
    .sc-body { color: var(--txt-2); font-size: 0.9rem; line-height: 1.65; }
    .sc-body b { color: var(--txt-1); }

    /* --- צ'יפ הדגשה לכרטיסי סריקה (Phase C / Spring / Shakeout / איסוף חזק) --- */
    .phase-hot-badge {
        display: inline-block; font-size: 0.74rem; font-weight: 800;
        padding: 3px 9px; border-radius: 8px; margin-right: 6px;
        letter-spacing: 0.2px; vertical-align: middle;
    }
    .hot-spring { background: rgba(56,189,248,0.16); color: var(--accent); border: 1px solid var(--accent-soft); }
    .hot-accum  { background: rgba(34,197,94,0.14);  color: var(--pos-soft); border: 1px solid rgba(34,197,94,0.4); }
    .hot-shake  { background: rgba(234,179,8,0.14);   color: var(--warn-soft); border: 1px solid rgba(234,179,8,0.45); }

    /* --- Macro Technical Radar --- */
    .macro-radar {
        background: var(--glass); border: 1px solid var(--glass-border);
        border-radius: var(--radius); padding: 14px 18px; margin: 8px 0 16px 0;
        backdrop-filter: blur(8px); box-shadow: var(--shadow);
    }
    .mr-head { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px; margin-bottom:8px; }
    .mr-title { font-weight: 800; font-size: 1rem; color: var(--txt-1); }
    .mr-regime { font-weight: 800; font-size: 0.95rem; padding: 4px 12px; border-radius: 10px; }
    .mr-grid { display:flex; flex-wrap:wrap; gap: 10px; }
    .mr-cell {
        flex: 1 1 120px; border: 1px solid var(--line); border-radius: 12px;
        padding: 9px 12px; background: rgba(255,255,255,0.02);
    }
    .mr-cell-name { font-size: 0.78rem; color: var(--txt-3); font-weight: 700; }
    .mr-cell-val { font-size: 1.0rem; font-weight: 800; margin-top: 2px; }
    .mr-note { color: var(--txt-2); font-size: 0.86rem; line-height: 1.6; margin-top: 8px; }
    /* V20.3 — Trading Range position bar */
    .wyck-tr-bar { position: relative; height: 10px; border-radius: 6px; margin-top: 10px;
        background: linear-gradient(90deg, #16a34a 0%, #eab308 50%, #dc2626 100%); opacity: 0.85; }
    .wyck-tr-dot { position: absolute; top: 50%; width: 16px; height: 16px; border-radius: 50%;
        background: #f8fafc; border: 3px solid #0f172a; transform: translate(-50%, -50%);
        box-shadow: 0 0 10px rgba(248,250,252,0.6); }
    /* V21.0 — Structural summary: bottom-line banner + 3 dials + consistent story */
    .struct-bottomline { background: linear-gradient(135deg, rgba(30,41,59,0.92), rgba(15,23,42,0.92));
        border: 1px solid rgba(148,163,184,0.28); border-radius: 14px; padding: 16px 18px;
        font-size: 1.06rem; font-weight: 700; color: #f1f5f9; line-height: 1.55; margin: 6px 0 14px 0;
        box-shadow: 0 6px 22px rgba(0,0,0,0.28); }
    .sbl-tag { display:inline-block; background: rgba(99,102,241,0.22); color:#c7d2fe;
        font-size: 0.7rem; font-weight: 800; padding: 2px 10px; border-radius: 999px;
        margin-left: 10px; vertical-align: middle; letter-spacing: 0.5px; }
    .dial { background: rgba(30,41,59,0.55); border: 1px solid rgba(148,163,184,0.18);
        border-radius: 14px; padding: 14px 10px; text-align:center; min-height: 118px;
        display:flex; flex-direction:column; justify-content:center; }
    .dial-val { font-size: 2.05rem; font-weight: 800; line-height: 1.05; }
    .dial-label { font-size: 0.92rem; font-weight: 700; color: #e2e8f0; margin-top: 6px; }
    .dial-sub { font-size: 0.74rem; color: #94a3b8; margin-top: 4px; line-height:1.35; }
    .story-box { background: rgba(15,23,42,0.45); border: 1px solid rgba(148,163,184,0.14);
        border-radius: 14px; padding: 6px 16px; margin: 14px 0 4px 0; }
    .story-row { display:flex; gap: 14px; padding: 11px 0; border-bottom: 1px solid rgba(148,163,184,0.10);
        align-items: flex-start; }
    .story-row:last-child { border-bottom: none; }
    .story-k { flex: 0 0 130px; font-weight: 800; color: #cbd5e1; font-size: 0.9rem; }
    .story-v { flex: 1; color: #e5e7eb; font-size: 0.92rem; line-height: 1.6; }
    .story-ul { margin: 0; padding-right: 18px; }
    .story-ul li { margin: 2px 0; }
    .story-foot { color: #94a3b8; font-size: 0.78rem; margin-top: 12px; padding-top: 10px;
        border-top: 1px dashed rgba(148,163,184,0.18); line-height: 1.5; }
    /* V22.0 — Value & Quality: grade pill + matrix */
    .grade-pill { display:inline-block; min-width: 22px; padding: 1px 8px; margin-right: 8px;
        border-radius: 8px; color: #0b1220; font-weight: 900; font-size: 1.05rem; vertical-align: middle; }
    .vq-detail { background: rgba(15,23,42,0.4); border: 1px solid rgba(148,163,184,0.14);
        border-radius: 12px; padding: 14px 16px; }
    .vq-headline { font-weight: 800; font-size: 1.0rem; margin-bottom: 8px; }
    .vq-grade-row { font-size: 0.92rem; color: #e2e8f0; margin-bottom: 14px; }
    .vq-score { color: #94a3b8; font-size: 0.82rem; }
    .vq-matrix { display: grid; grid-template-columns: 96px 1fr 1fr 1fr; gap: 5px;
        max-width: 420px; margin: 6px 0 14px 0; align-items: center; }
    .vq-corner { }
    .vq-axis { font-size: 0.74rem; color: #94a3b8; text-align: center; font-weight: 700; }
    .vq-axis-row { text-align: right; padding-left: 8px; }
    .vq-cell { height: 34px; border-radius: 7px; opacity: 0.42; }
    .vq-cell-active { opacity: 1; box-shadow: 0 0 0 3px #f8fafc, 0 0 12px rgba(248,250,252,0.5); }
    .vq-sub { font-size: 0.88rem; color: #cbd5e1; line-height: 1.6; margin-top: 8px; }
    /* V25.0 — Dual-lens + scanner timing/fit chips */
    .timing-chip { display:inline-block; padding: 3px 10px; border-radius: 999px; font-size: 0.78rem;
        font-weight: 700; margin-left: 6px; }
    .fit-chip { display:inline-block; padding: 3px 10px; border-radius: 999px; font-size: 0.78rem;
        font-weight: 700; background: rgba(148,163,184,0.14); color: #cbd5e1;
        border: 1px solid rgba(148,163,184,0.25); }
    .ready-chip { display:inline-block; padding: 3px 10px; border-radius: 999px; font-size: 0.78rem;
        font-weight: 700; background: rgba(59,130,246,0.14); color: #bfdbfe;
        border: 1px solid rgba(59,130,246,0.3); margin-top: 4px; }
    .lens-current { font-weight: 800; color: #cbd5e1; font-size: 0.95rem; padding: 8px 2px; }
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

    # === V20.2: שכבת אימות + ראיות + טריות נתונים (אפליקטיבי, מעל המנוע המוגן) ===
    refined_phase, was_refined, refine_note, phase_status = refine_wyckoff_phase(df, factors, current_phase)
    freshness = assess_data_freshness(df)

    # === V21.0: המנוע המבני הוא כעת הקובע הראשי של הפאזה (ה-CIS הופך למאַשר) ===
    df_weekly = _to_weekly(df)
    weekly_ctx = assess_weekly_context(df_weekly)
    wyckoff_state = analyze_wyckoff_structural(df, weekly_ctx, factors, current_cis, current_phase)
    # V24.0 — כיול היסטורי (Tier 3.1): שיעור הצלחה של המצב הזה במניה הזו + modifier קטן לביטחון
    reliability = compute_phase_reliability(ticker, wyckoff_state["state"])
    _apply_reliability_to_confidence(wyckoff_state, reliability)
    wyckoff_state["reliability"] = reliability
    display_phase = wyckoff_state["phase_he"]          # ← מבני, לא המנוע הגולמי
    phase_status = wyckoff_state["status"]             # confirmed / transition / caution
    phase_confidence = wyckoff_state["confidence"]
    evidence = build_phase_evidence(df, factors, current_phase)

    return {
        "df": df,
        "factors": factors,
        "cis": cis,
        "current_phase": current_phase,        # פלט המנוע המקורי (לשקיפות בלבד)
        "display_phase": display_phase,         # ← V21.0: התווית המבנית הקובעת
        "phase_refined": was_refined,
        "phase_refine_note": wyckoff_state["bottom_line"],
        "phase_status": phase_status,           # confirmed / transition / caution
        "phase_confidence": phase_confidence,   # ← V21.0: ביטחון פאזה רציף (0-100), נפרד מ-CIS
        "wyckoff_state": wyckoff_state,         # ← V21.0: אובייקט המצב המבני המלא
        "weekly_ctx": weekly_ctx,
        "phase_evidence": evidence,
        "freshness": freshness,
        "current_cis": current_cis,
        "allowed": allowed,
        "num_bars": len(df)
    }


# ============================================================
# V20.2 — שכבת אימות פאזות, מנוע ראיות, טריות נתונים, פירוש CIS,
# תוכנית סווינג ו-Macro Radar. הכל ברמת האפליקציה בלבד.
# המנוע (FactorEngine) ושאר פונקציות הליבה המוגנות אינם נוגעים בכלל.
# ============================================================

# --- מילון פאזות עברי קצר (לתצוגה אנושית) ---
_PHASE_HE = {
    "Phase A": "שלב A — בלימת ירידות (Selling Climax)",
    "Phase B": "שלב B — איסוף שקט / בניית כוח",
    "Phase C": "שלב C — ניעור (Spring) ובדיקת תחתית",
    "Phase D": "שלב D — הכנה לפריצה (SOS/LPS)",
    "Phase E": "שלב E — מגמת עלייה (Markup)",
    "Re-accumulation": "איסוף חוזר (LPS/BUEC)",
    "Markdown": "מגמת ירידה (Markdown)",
    "Distribution": "הפצה מוסדית (Distribution)",
    "Selling Climax": "שיא מכירות (Phase A)",
    "Failed Sweep": "ניעור שנכשל — אזהרה",
    "TRANSITION": "מצב מעבר / חוסר ודאות",
    "לא בתהליך": "לא בתהליך איסוף מובהק",
}


def _phase_family(phase: str) -> str:
    """מסווג פאזה למשפחה: bullish_adv / bullish_early / bearish / transition / none."""
    p = phase or ""
    if any(k in p for k in ("Distribution", "Markdown", "Heavy Supply", "Failed Sweep")):
        return "bearish"
    if any(k in p for k in ("Phase E", "Markup", "Phase D", "SOS", "LPS", "Re-accumulation", "Breakout")):
        return "bullish_adv"
    if any(k in p for k in ("Phase C", "Spring", "Phase B", "Accumulation", "Phase A", "Selling Climax")):
        return "bullish_early"
    if any(k in p for k in ("TRANSITION", "UNCERTAIN", "לא בתהליך")):
        return "transition"
    return "none"


def _sma(series: pd.Series, n: int):
    try:
        return float(series.rolling(n).mean().iloc[-1])
    except Exception:
        return float("nan")


def detect_distribution_risk(df: pd.DataFrame) -> dict:
    """
    מזהה 'תיקון/הפצה בנפח גבוה' שמתחזה לאיסוף חוזר: פולבק עמוק מהשיא המלווה בנפח
    מכירות גובר — חתימה הפוכה מ-LPS/BUEC רגוע (שדורש נפח *דועך*).
    מחזיר: {risk, dist_pct, reasons[], support, resistance, signals}
    """
    res = {"risk": False, "dist_pct": 0.0, "reasons": [], "support": None, "resistance": None, "signals": 0}
    try:
        if df is None or len(df) < 60:
            return res
        close, openp, vol = df["Close"], df["Open"], df["Volume"]
        c = float(close.iloc[-1])
        v_ma = float(vol.rolling(20).mean().iloc[-1]) or 1.0
        s20, s50 = _sma(close, 20), _sma(close, 50)
        high60 = float(df["High"].rolling(60).max().iloc[-1])
        low60 = float(df["Low"].rolling(60).min().iloc[-1])
        res["resistance"] = round(high60, 2)
        res["support"] = round(s50, 2) if not pd.isna(s50) else round(low60, 2)

        dist = (high60 - c) / high60 if high60 else 0.0
        res["dist_pct"] = round(dist * 100, 1)
        deep_pullback = dist >= 0.10  # ירד 10%+ מתחת לשיא 60 יום

        # רגל הפולבק = מנקודת השיא של 60 יום ועד עכשיו
        recent60 = df.tail(60)
        try:
            leg = df.loc[recent60["High"].idxmax():]
        except Exception:
            leg = df.tail(10)
        up_vol = float(leg.loc[leg["Close"] >= leg["Open"], "Volume"].sum())
        dn_vol = float(leg.loc[leg["Close"] < leg["Open"], "Volume"].sum())
        supply_dominates = dn_vol > up_vol * 1.15

        last5 = df.tail(5)
        heavy_supply_bar = bool(((last5["Volume"] > v_ma * 1.4) & (last5["Close"] < last5["Open"])).any())
        below_s20 = (not pd.isna(s20)) and c < s20

        if supply_dominates:
            res["reasons"].append("נפח הירידות גובר על נפח העליות לאורך הפולבק (היצע מוסדי)")
        if heavy_supply_bar:
            res["reasons"].append("נר ירידה אחרון בנפח חריג (≥x1.4 מהממוצע) — לחץ מכירה אקטיבי")
        if below_s20:
            res["reasons"].append("המחיר שבר את ממוצע 20 — אובדן מבנה קצר-טווח")
        res["signals"] = int(supply_dominates) + int(heavy_supply_bar) + int(below_s20)
        res["risk"] = bool(deep_pullback and res["signals"] >= 2)
    except Exception:
        pass
    return res


def describe_phase_transition(df: pd.DataFrame, engine_phase: str = "") -> dict:
    """
    מנסח 'יצאנו מ-X / ממתינים לאישור ל-Y' כשאין פאזה מאושרת — לפי מבנה המחיר,
    במקום לכפות התאמה לפאזה. מחזיר: {exited, awaiting, watch}.
    """
    ctx = {"exited": "", "awaiting": "", "watch": ""}
    try:
        if df is None or len(df) < 60:
            ctx["awaiting"] = "נדרשים יותר נתונים (≥60 ימי מסחר) לזיהוי פאזה מובהקת."
            return ctx
        close = df["Close"]
        c = float(close.iloc[-1])
        s20, s50, s200 = _sma(close, 20), _sma(close, 50), _sma(close, 200)
        if pd.isna(s200):
            s200 = s50
        high60 = float(df["High"].rolling(60).max().iloc[-1])
        low60 = float(df["Low"].rolling(60).min().iloc[-1])
        dist_high = (high60 - c) / high60 if high60 else 0.0

        above_200 = c > s200
        below_50 = (not pd.isna(s50)) and c < s50
        near_low = c <= low60 * 1.06

        if above_200 and dist_high >= 0.07 and not below_50:
            ctx["exited"] = "מגמת עלייה (Phase E / Markup)"
            ctx["awaiting"] = "אישור איסוף חוזר (Re-accumulation) — או תחילת הפצה"
            ctx["watch"] = (f"להמשך עלייה: שפל גבוה-יותר בנפח דועך ואז סגירה מעל ${round(high60,2)} בנפח. "
                            f"לחולשה: סגירה יומית מתחת ${round(s50,2)} בנפח גבוה.")
        elif below_50 and above_200:
            ctx["exited"] = "טווח איסוף (Phase B)"
            ctx["awaiting"] = "ניעור (Phase C / Spring) או פריצה ראשונה (Phase D / SOS)"
            ctx["watch"] = (f"מחפשים ניעור מתחת ${round(low60,2)} שחוזר מיד מעלה בנפח (Spring), "
                            f"או סגירה מעל ${round(high60,2)} בנפח כפריצת SOS.")
        elif near_low and not above_200:
            ctx["exited"] = "מגמת ירידה (Markdown)"
            ctx["awaiting"] = "בלימת מכירות (Phase A) ותחילת בנייה מחדש"
            ctx["watch"] = (f"מחפשים נר בלימה בנפח חריג סביב ${round(low60,2)} שנסגר בחצי העליון, "
                            f"ולאחריו התייצבות מעל ${round(s20,2)}.")
        else:
            ctx["exited"] = "מצב לא מובהק (ממוצעים שזורים)"
            ctx["awaiting"] = "התגבשות מבנה ברור — מעל/מתחת לממוצעים מרכזיים"
            ctx["watch"] = (f"אזור החלטה סביב ${round(c,2)}: סגירה מעל ${round(high60,2)} = כוח, "
                            f"מתחת ${round(low60,2)} = חולשה.")
    except Exception:
        pass
    return ctx


# ============================================================
# V20.3 — שכבת ניתוח וויקוף מעמיק (Wyckoff Deep Analysis).
# מבוססת מחקר על המתודולוגיה הקנונית: Wyckoff Analytics / StockCharts
# ChartSchool (אירועי TR, חוק Cause & Effect) ו-Tom Williams VSA
# (No Demand/No Supply/Stopping Volume/Climax/Upthrust).
# שכבת אפליקציה בלבד — קוראת OHLCV גולמי, לא נוגעת ב-FactorEngine
# ובפונקציות הליבה המוגנות. מוסכמות זהות למנוע: vol_ma20=ממוצע נפח 20,
# spread=High-Low מול spread_ma20, ומיקום הסגירה בתוך הנר.
# ============================================================

def _bar_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """מטריקות בסיס לכל נר (מוסכמות זהות ל-FactorEngine): ספרד, ספרד יחסי,
    נפח יחסי, מיקום סגירה בתוך הנר (0=שפל,1=שיא), וכיוון."""
    m = pd.DataFrame(index=df.index)
    rng = (df["High"] - df["Low"]).replace(0, 1e-9)
    m["spread_ratio"] = rng / rng.rolling(20).mean().replace(0, 1e-9)
    vma = df["Volume"].rolling(20).mean().replace(0, 1e-9)
    m["vol_ratio"] = df["Volume"] / vma
    m["close_pos"] = ((df["Close"] - df["Low"]) / rng).clip(0, 1)
    m["up_bar"] = df["Close"] > df["Close"].shift(1)
    return m


def detect_trading_range(df: pd.DataFrame, lookback: int = 70) -> dict:
    """
    מזהה את טווח המסחר (Trading Range) הנוכחי — היסוד של ניתוח וויקוף: תמיכה/
    התנגדות, רוחב, מיקום המחיר בטווח, מס' נגיעות. מבחין בין *טווח אמיתי* (המחיר
    מתנודד — חוצה את האמצע מספר פעמים, רוחב סביר) לבין *מגמה* (תנועה כיוונית ללא
    קונסולידציה) — כדי לא להשליך 'טווח' מזויף על מניה במגמה חדה (שורש עיוות ה-TR
    הקודם). מחזיר dict עם is_range. קצוות לפי אחוזונים (עמיד לספייק בודד).
    """
    res = {"valid": False, "is_range": False, "support": None, "resistance": None,
           "midpoint": None, "width_pct": 0.0, "position": 0.5, "location": "—",
           "bars": 0, "touches_s": 0, "touches_r": 0, "crossings": 0}
    try:
        if df is None or len(df) < 40:
            return res
        win = df.tail(min(lookback, len(df)))
        c = float(win["Close"].iloc[-1])
        res_hi = float(win["High"].quantile(0.92))
        sup_lo = float(win["Low"].quantile(0.08))
        if res_hi <= sup_lo:
            return res
        tol = (res_hi - sup_lo) * 0.04
        touches_r = int((win["High"] >= res_hi - tol).sum())
        touches_s = int((win["Low"] <= sup_lo + tol).sum())
        width_pct = (res_hi - sup_lo) / sup_lo * 100.0
        mid = (res_hi + sup_lo) / 2.0
        pos = (c - sup_lo) / (res_hi - sup_lo)
        # מבחן 'טווח מול מגמה': כמה פעמים הסגירה חוצה את אמצע הטווח
        above = win["Close"] > mid
        crossings = int((above != above.shift(1)).iloc[1:].sum())
        is_range = (crossings >= 3) and (5.0 <= width_pct <= 45.0)
        if not is_range:
            loc = "trending"
        elif c > res_hi * 1.015:
            loc = "breakout_up"
        elif c < sup_lo * 0.985:
            loc = "breakdown"
        elif pos >= 0.66:
            loc = "upper"
        elif pos <= 0.34:
            loc = "lower"
        else:
            loc = "middle"
        bars_in = int(((win["Close"] <= res_hi * 1.02) & (win["Close"] >= sup_lo * 0.98)).sum())
        res.update({"valid": True, "is_range": bool(is_range), "support": round(sup_lo, 2),
                    "resistance": round(res_hi, 2), "midpoint": round(mid, 2),
                    "width_pct": round(width_pct, 1), "position": round(float(max(0.0, min(1.0, pos))), 2),
                    "location": loc, "bars": bars_in, "touches_s": touches_s,
                    "touches_r": touches_r, "crossings": crossings})
    except Exception:
        pass
    return res


def classify_vsa_bars(df: pd.DataFrame, n: int = 15) -> list:
    """
    מסווג את n הנרות האחרונים לפי Volume Spread Analysis (Tom Williams):
    Selling/Buying Climax, Stopping Volume, Spring/Shakeout, Upthrust, SOS,
    No Demand, No Supply, Effort vs Result. כל תווית מבוססת ספרד יחסי, נפח יחסי
    ומיקום הסגירה — מוסכמות זהות למנוע. רקע המגמה (מעל/מתחת SMA20) משמש לקונטקסט
    הקלימקסים. מחזיר את הנרות המסומנים בלבד (מהישן לחדש).
    """
    out = []
    try:
        if df is None or len(df) < 30:
            return out
        m = _bar_metrics(df)
        closes, vols = df["Close"], df["Volume"]
        s20 = closes.rolling(20).mean()
        for i in range(max(2, len(df) - n), len(df)):
            sr = float(m["spread_ratio"].iloc[i]); vr = float(m["vol_ratio"].iloc[i])
            cp = float(m["close_pos"].iloc[i]); up = bool(m["up_bar"].iloc[i])
            v = float(vols.iloc[i]); v_prev2 = float(min(vols.iloc[i - 1], vols.iloc[i - 2]))
            c = float(closes.iloc[i])
            hi5 = float(df["High"].iloc[max(0, i - 5):i].max())
            lo5 = float(df["Low"].iloc[max(0, i - 5):i].min())
            trend_up = (not pd.isna(s20.iloc[i])) and c > float(s20.iloc[i])
            label = tone = note = None

            if sr >= 1.6 and vr >= 2.0 and cp >= 0.5 and not trend_up:
                label, tone, note = "Selling Climax (SC)", "pos", "ספרד רחב + נפח אולטרה + סגירה בחצי העליון אחרי ירידה — ידיים חזקות סופגות היצע."
            elif sr >= 1.6 and vr >= 2.0 and cp <= 0.5 and trend_up:
                label, tone, note = "Buying Climax (BC)", "neg", "ספרד רחב + נפח אולטרה + סגירה בחצי התחתון בשיא מגמה — חתימת הפצה לקהל."
            elif float(df["High"].iloc[i]) > hi5 and cp <= 0.33 and vr >= 1.2:
                label, tone, note = "Upthrust (UT)", "neg", "חדירה מעל שיא קצר-טווח שנדחתה (סגירה בתחתית) — מלכודת שוורים / היצע."
            elif float(df["Low"].iloc[i]) < lo5 and c > lo5 and cp >= 0.5 and vr >= 1.2:
                label, tone, note = "Spring / Shakeout", "pos", "חדירה מתחת לשפל קצר-טווח שנבלעה מיד (סגירה גבוהה) — מלכודת דובים / Phase C."
            elif (not up) and vr >= 1.8 and cp >= 0.5 and not trend_up:
                label, tone, note = "Stopping Volume", "pos", "נר ירידה בנפח גבוה שנסגר בחצי העליון — ביקוש נכנס וסופג (לא אות קנייה לבד)."
            elif up and sr >= 1.3 and vr >= 1.2 and cp >= 0.66:
                label, tone, note = "Sign of Strength (SOS)", "pos", "נר עלייה רחב בנפח, סגירה בשליש העליון — ביקוש שולט."
            elif up and sr <= 0.7 and v < v_prev2 and cp <= 0.5:
                label, tone, note = "No Demand", "neg", "נר עלייה צר בנפח דל (מתחת ל-2 הקודמים) — היעדר עניין מוסדי בעליות."
            elif (not up) and sr <= 0.7 and v < v_prev2 and cp >= 0.5:
                label, tone, note = "No Supply", "pos", "נר ירידה צר בנפח דל — לחץ המכירה מתייבש (חיובי ליד תמיכה)."
            elif vr >= 1.6 and sr <= 0.8:
                label, tone, note = "Effort vs Result", "neu", "נפח גבוה אך תנועה קטנה — מאמץ ללא תוצאה: ספיגה נגדית (היצע/ביקוש סמוי)."

            if label:
                out.append({"date": df.index[i].strftime("%d.%m"), "label": label, "tone": tone,
                            "note": note, "vol_ratio": round(vr, 1), "close_pos": round(cp, 2)})
    except Exception:
        pass
    return out


def detect_wyckoff_events(df: pd.DataFrame, tr: dict) -> list:
    """
    מזהה אירועי Wyckoff מבניים עוגנים לטווח המסחר (TR): Spring/Shakeout (Phase C),
    Upthrust/UTAD (Phase C הפצה), SOS/פריצה (Jump the Creek), ו-SOW/שבירה. מחזיר
    את המופע האחרון מכל סוג, מהחדש לישן, עם תאריך/מחיר/תיאור. דורש TR תקין.
    """
    found = []
    try:
        if df is None or len(df) < 40 or not tr.get("is_range"):
            return found
        sup, rst = tr["support"], tr["resistance"]
        m = _bar_metrics(df)
        win_n = min(max(tr.get("bars", 60), 40) + 20, len(df), 100)
        for i in range(max(2, len(df) - win_n), len(df)):
            hi = float(df["High"].iloc[i]); lo = float(df["Low"].iloc[i]); c = float(df["Close"].iloc[i])
            cp = float(m["close_pos"].iloc[i]); vr = float(m["vol_ratio"].iloc[i])
            if lo < sup and c > sup and cp >= 0.45:
                found.append((i, "Spring / Shakeout (Phase C)", c,
                              f"חדירה ל-${round(lo,2)} מתחת לתמיכה ${sup} וחזרה מעל — מלכודת דובים. כניסת לונג קלאסית, סטופ מתחת לשפל הניעור.", "pos"))
            elif hi > rst and c < rst and cp <= 0.55:
                found.append((i, "Upthrust / UTAD (Phase C)", c,
                              f"חדירה ל-${round(hi,2)} מעל התנגדות ${rst} ודחייה חזרה פנימה — מלכודת שוורים. אזהרת הפצה / כניסת שורט.", "neg"))
            elif c > rst and vr >= 1.3 and cp >= 0.6:
                found.append((i, "SOS / פריצה (Phase D→E)", c,
                              f"סגירה מעל ${rst} בנפח (×{round(vr,1)}) — קפיצה מעל ה-Creek, אישור Markup.", "pos"))
            elif c < sup and vr >= 1.3 and cp <= 0.4:
                found.append((i, "SOW / שבירה (Phase D→E)", c,
                              f"סגירה מתחת ${sup} בנפח (×{round(vr,1)}) — שבירת תמיכה, אישור Markdown.", "neg"))
        found.sort(key=lambda e: e[0], reverse=True)
        seen, uniq = set(), []
        for i, name, price, desc, tone in found:
            key = name.split("/")[0].strip()
            if key in seen:
                continue
            seen.add(key)
            uniq.append({"date": df.index[i].strftime("%d.%m.%Y"), "event": name,
                         "price": round(price, 2), "desc": desc, "tone": tone,
                         "age_bars": int(len(df) - 1 - i)})
        return uniq[:5]
    except Exception:
        return found


def wyckoff_cause_effect_targets(df: pd.DataFrame, tr: dict) -> dict:
    """
    יעדי מחיר לפי חוק הסיבה והתוצאה (Cause & Effect): רוחב טווח המסחר הוא ה'סיבה'
    הצבורה; המהלך שאחרי הפריצה הוא ה'תוצאה'. פרוקסי לספירת P&F האופקית מתוך OHLCV:
    יעד = רמת הפריצה ± (רוחב הטווח × מכפיל). מחזיר יעדי עלייה (מאיסוף) וירידה (מהפצה),
    שמרני(×1)/בסיס(×2)/מורחב(×3), עם אחוזי תנועה מהמחיר הנוכחי.
    """
    res = {"valid": False}
    try:
        if not tr.get("is_range"):   # יעדי Cause & Effect תקפים רק לטווח מסחר אמיתי, לא למגמה
            return res
        sup, rst = tr["support"], tr["resistance"]
        width = rst - sup
        if width <= 0:
            return res
        c = float(df["Close"].iloc[-1])

        def pct(p):
            return round((p - c) / c * 100, 1)

        up = {k: {"price": round(rst + width * mlt, 2), "pct": pct(rst + width * mlt)}
              for k, mlt in (("conservative", 1.0), ("base", 2.0), ("extended", 3.0))}
        # יעדי ירידה נחתכים ל-0 כרצפה (מחיר לא יכול להיות שלילי)
        down = {k: {"price": max(0.01, round(sup - width * mlt, 2)), "pct": pct(max(0.01, sup - width * mlt))}
                for k, mlt in (("conservative", 1.0), ("base", 2.0), ("extended", 3.0))}
        res = {"valid": True, "width": round(width, 2), "width_pct": tr["width_pct"],
               "breakout_up": rst, "breakdown": sup, "up": up, "down": down}
    except Exception:
        pass
    return res


# הודעת ברירת-מחדל כשאין פאזה מאושרת — מנחה לסרוק שוב במקום לכפות פאזה
_RESCAN_HINT = ("📅 מומלץ לסרוק שוב ביום המסחר הבא: אם ייווצר מבנה ברור (טווח/פריצה/ניעור) — "
                "הפאזה תאומת. אין צורך לכפות פאזה כשהמבנה לא תומך בה.")


def _obv_slope(df: pd.DataFrame, n: int = 10):
    """שיפוע OBV מנורמל (כיוון זרימת ההון): חיובי=הון נכנס, שלילי=הון יוצא. None אם אין די נתונים."""
    try:
        if df is None or len(df) < n + 2:
            return None
        obv = (np.sign(df["Close"].diff()) * df["Volume"]).cumsum()
        denom = obv.abs().rolling(n).mean().replace(0, np.nan)
        val = float((obv.diff(n) / denom).iloc[-1])
        return val if pd.notna(val) else None
    except Exception:
        return None


def assess_phase_coherence(df: pd.DataFrame, engine_phase: str, tr: dict):
    """
    בודק עקביות בין תווית הפאזה (מהמנוע) לבין המבנה הבלתי-תלוי. מטרה: לתפוס מקרים
    כמו WULF — תווית תלוית-טווח ('Re-accumulation/LPS/BUEC') שנכפית כשאין בכלל טווח
    מסחר (מהלך פרבולי/מגמתי). מחזיר (is_coherent, reason, watch_for).

    *שמרני בכוונה* — מתוכנן שלא לפסול פאזות תקינות, כדי שהמערכת לא תאמר 'אין פאזה'
    יותר מדי. התנאים:
      1. רק תוויות שמהותית *מחייבות טווח* נבדקות (LPS/BUEC הם אירועים בתוך טווח).
         תוויות מגמה (Phase E/Markup/Markdown) ותוויות היפוך (Spring/Phase C/A) — לא.
      2. הסתירה חייבת להיות *חד-משמעית*: לא רק is_range=False, אלא טווח פרבולי
         בעליל (>55%) או כמעט ללא תנודה (<=2 חציות אמצע) — לא מקרי-גבול.
    """
    try:
        p = engine_phase or ""
        range_dependent = any(k in p for k in ("Re-accumulation", "LPS", "BUEC", "Phase B"))
        if not range_dependent or tr is None or not tr.get("valid"):
            return True, "", ""
        clearly_no_range = (not tr.get("is_range")) and (
            tr.get("width_pct", 0.0) > 55.0 or tr.get("crossings", 99) <= 2
        )
        if not clearly_no_range:
            return True, "", ""
        extra = ""
        obv = _obv_slope(df)
        if obv is not None and obv < 0:
            extra = " בנוסף, זרימת ההון (OBV) שלילית — הון נטו יוצא, מה שמחזק שאין כאן איסוף מוסדי."
        reason = (f"התווית '{p}' מחייבת טווח מסחר — LPS/BUEC הם 'נקודת התמיכה האחרונה' *בתוך* טווח. "
                  f"אך המבנה כאן הוא מהלך מגמתי/פרבולי ללא טווח מובהק (רוחב {tr.get('width_pct')}%, "
                  f"חציות-אמצע: {tr.get('crossings')}).{extra}")
        watch = ("מה לחפש: היווצרות טווח מסחר אמיתי (תמיכה/התנגדות שנבחנות מספר פעמים) עם נפח דועך "
                 "בתיקונים. סגירה מעל ההתנגדות בנפח = חידוש עלייה; סגירה מתחת לתמיכה בנפח = חולשה.")
        return False, reason, watch
    except Exception:
        return True, "", ""


# ============================================================
# V21.0 — Structural Wyckoff Engine (Tier 1)
# מנוע מבני שמניע את הפאזה הראשית במקום ה-CIS. שכבת אפליקציה בלבד —
# FactorEngine והליבה המוגנת אינם נוגעים (הליבה הופכת לקלט *מאַשר*).
# עיקרון-על: הפאזה נקבעת קודם מבנית (שערים קשיחים: טווח + gate שבועי),
# ורק אז מחושב ביטחון. CIS/שבועי מזינים את הביטחון — לא עוקפים את הקביעה.
# מבנה 8 מצבים. כל הפונקציות עמידות (try/except) ל-Cloud Run.
# ============================================================

# --- 8 מצבי מכונת המצבים (states) ---
_WSTATES = {
    "MARKDOWN":     {"he": "מגמת ירידה (Markdown)",          "track": "bear", "simple": "המניה במגמת ירידה — לא אזור קנייה."},
    "ACC_BASE":     {"he": "שלב A/B — בניית בסיס (איסוף)",     "track": "bull", "simple": "נבנה בסיס בתחתית — מוקדם, לעקוב ולא להיכנס עדיין."},
    "ACC_SPRING":   {"he": "שלב C — ניעור (Spring)",          "track": "bull", "simple": "זוהה ניעור — אזור הכניסה הקלאסי, בכפוף לאישור."},
    "ACC_CONFIRM":  {"he": "שלב D — אישור איסוף (SOS/LPS)",    "track": "bull", "simple": "האיסוף אושר — אזור תוספת לפני הפריצה."},
    "MARKUP":       {"he": "שלב E — מגמת עלייה (Markup)",      "track": "bull", "simple": "מגמת עלייה — לרכוב עם סטופ נגרר."},
    "DIST_WARNING": {"he": "אזהרת הפצה (Distribution)",        "track": "bear", "simple": "סימני הפצה בפסגה — זהירות, לשקול צמצום."},
    "DIST_ACTIVE":  {"he": "הפצה פעילה / שבירה",               "track": "bear", "simple": "הפצה אושרה — אזור יציאה."},
    "UNDETERMINED": {"he": "אין פאזה מאושרת — ממתינים למבנה",  "track": "none", "simple": "אין מבנה טווח ברור — עדיף להמתין."},
}


def _to_weekly(df: pd.DataFrame):
    """resample של ה-daily הקיים ל-W-FRI — ללא קריאת רשת נוספת. None אם אין די נתונים."""
    try:
        if df is None or len(df) < 30:
            return None
        w = df[["Open", "High", "Low", "Close", "Volume"]].resample("W-FRI").agg(
            {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
        return w if len(w) >= 12 else None
    except Exception:
        return None


def assess_weekly_context(dfw: pd.DataFrame) -> dict:
    """
    הקשר רב-טווחי (ה-gate): מגמה שבועית מחיר מול SMA10/30 + שיפוע, וזיהוי
    Topping/Bottoming. מחזיר regime + weekly_bias[-1..+1]. זהו מה שמבדיל
    איסוף-חוזר (תיקון ב-WEEKLY_MARKUP) מהפצה (תיקון ב-WEEKLY_TOPPING).
    """
    res = {"regime": "WEEKLY_UNKNOWN", "weekly_bias": 0.0,
           "note": "אין די נתונים שבועיים לקונטקסט רב-טווחי."}
    try:
        if dfw is None or len(dfw) < 12:
            return res
        close = dfw["Close"]
        c = float(close.iloc[-1])
        s10 = float(close.rolling(10).mean().iloc[-1])
        s30 = float(close.rolling(min(30, len(dfw))).mean().iloc[-1])
        s10_prev = float(close.rolling(10).mean().iloc[-5]) if len(dfw) > 15 else s10
        slope = (s10 - s10_prev) / s10_prev if s10_prev else 0.0
        hi12 = float(dfw["High"].tail(12).max())
        lo12 = float(dfw["Low"].tail(12).min())
        off_high = c < hi12 * 0.92
        off_low = c > lo12 * 1.08

        if c > s10 > s30 and slope > 0.004:
            regime, bias = "WEEKLY_MARKUP", 0.8
        elif c < s10 < s30 and slope < -0.004:
            regime, bias = "WEEKLY_MARKDOWN", -0.8
        elif c > s30 and off_high and slope <= 0.004:
            regime, bias = "WEEKLY_TOPPING", 0.0      # היה למעלה, מתהפך מהשיא
        elif c < s30 and off_low and slope >= -0.004:
            regime, bias = "WEEKLY_BOTTOMING", 0.0     # היה למטה, מתבסס
        else:
            regime, bias = "WEEKLY_RANGE", round(max(-0.4, min(0.4, slope * 20)), 2)
        notes = {
            "WEEKLY_MARKUP": "טווח-זמן שבועי במגמת עלייה — תיקון יומי כאן הוא הקשר של איסוף-חוזר.",
            "WEEKLY_MARKDOWN": "טווח-זמן שבועי במגמת ירידה — קריאות שוריות יומיות חשודות (נגד הזרם).",
            "WEEKLY_TOPPING": "טווח-זמן שבועי מתהפך מהשיא — תיקון יומי כאן נוטה להקשר של הפצה.",
            "WEEKLY_BOTTOMING": "טווח-זמן שבועי מתבסס בתחתית — תומך בקריאות איסוף.",
            "WEEKLY_RANGE": "טווח-זמן שבועי דשדושי — אין הטיה רב-טווחית ברורה.",
        }
        res = {"regime": regime, "weekly_bias": round(float(bias), 2), "note": notes[regime]}
    except Exception:
        pass
    return res


def _structure_features(df: pd.DataFrame, tr: dict, events: list, vsa: list) -> dict:
    """מסכם את התמונה המבנית לקלט נקי ל-FSM (מגמה, OBV, פרבולי-שבור, נוכחות אירועים)."""
    f = {"trend": "flat", "obv_dir": 0.0, "parabolic_broken": False,
         "has_spring": False, "has_sos": False, "has_utad": False, "has_sow": False,
         "has_sc": False, "has_bc": False, "has_stopping": False,
         "has_no_demand": False, "has_no_supply": False,
         "dist_from_high": 0.0, "pos_bucket": "mid"}
    try:
        close = df["Close"]
        c = float(close.iloc[-1])
        s20, s50, s200 = _sma(close, 20), _sma(close, 50), _sma(close, 200)
        up = (not any(pd.isna(x) for x in (s20, s50))) and c > s20 > s50
        dn = (not any(pd.isna(x) for x in (s20, s50))) and c < s20 < s50
        f["trend"] = "up" if up else ("down" if dn else "flat")
        f["obv_dir"] = _obv_slope(df) or 0.0
        high60 = float(df["High"].rolling(min(60, len(df))).max().iloc[-1])
        f["dist_from_high"] = (high60 - c) / high60 if high60 else 0.0
        big_run = (not pd.isna(s200)) and c > s200 * 1.15
        f["parabolic_broken"] = (not tr.get("is_range")) and f["dist_from_high"] >= 0.10 \
            and f["obv_dir"] < 0 and big_run
        ev = " ".join(e.get("event", "") for e in (events or []))
        f["has_spring"] = "Spring" in ev
        f["has_sos"] = "SOS" in ev
        f["has_utad"] = ("Upthrust" in ev) or ("UTAD" in ev)
        f["has_sow"] = "SOW" in ev
        vn = " ".join(b.get("label", "") for b in (vsa or []))
        f["has_sc"] = "Selling Climax" in vn
        f["has_bc"] = "Buying Climax" in vn
        f["has_stopping"] = "Stopping Volume" in vn
        f["has_no_demand"] = "No Demand" in vn
        f["has_no_supply"] = "No Supply" in vn
        pos = tr.get("position", 0.5)
        f["pos_bucket"] = "low" if pos <= 0.34 else ("high" if pos >= 0.66 else "mid")
    except Exception:
        pass
    return f


def classify_wyckoff_state(df: pd.DataFrame, tr: dict, events: list, vsa: list, weekly_ctx: dict) -> dict:
    """
    מכונת המצבים — קובעת את ה-state המבני עם שערים קשיחים. סדר הבדיקות מהחזק
    לחלש; הפרבולי-שבור (WULF) נבדק *ראשון* כדי שלא ייפול בטעות ל-MARKUP.
    מחזיר {state, structural_score, evidence[], required_missing[], features}.
    """
    f = _structure_features(df, tr, events, vsa)
    is_range = bool(tr.get("is_range"))
    pos = f["pos_bucket"]
    wb = float(weekly_ctx.get("weekly_bias", 0.0))
    state, sscore, evid, missing = "UNDETERMINED", 25, [], []
    caution = False   # V25.1: דגל "בזהירות" — מצב שורי עם סיכון תיקון (למשל אפ-ת'ראסט + OBV חיובי)

    # האירוע המכריע *האחרון* (events ממוין מהחדש לישן) + מיקום המחיר ביחס לטווח —
    # כדי שפריצה (SOS) שאחרי שבירה ישנה (SOW) תזוהה כשורית, ולא להפך (מודעות לרצף).
    c = float(df["Close"].iloc[-1]) if df is not None and len(df) else 0.0
    sup = tr.get("support") or 0.0
    rst = tr.get("resistance") or 0.0
    latest = None
    latest_age = 0
    for e in (events or []):
        en = e.get("event", "")
        if "SOW" in en:
            latest = "SOW"
        elif "SOS" in en:
            latest = "SOS"
        elif "Spring" in en:
            latest = "Spring"
        elif ("Upthrust" in en) or ("UTAD" in en):
            latest = "UTAD"
        if latest:
            latest_age = int(e.get("age_bars", 0) or 0)
            break
    # V26.0: טריות אירועים — "המיקום גובר על אירוע ישן" חל גם על אירועי Phase C:
    # Spring/UTAD ישנים מ-25 ברים (~5 שבועות) אינם מכתיבים state; המבנה הנוכחי מכריע.
    EVENT_FRESH_BARS = 25   # תפוגה: מעבר לזה האירוע לא מכתיב state
    EVENT_YOUNG_BARS = 10   # "טרי" באמת: עד ~שבועיים; 11-25 = "מזדקן" (בתוקף אך נחלש)
    spring_fresh = (latest == "Spring" and latest_age <= EVENT_FRESH_BARS)
    spring_young = (latest == "Spring" and latest_age <= EVENT_YOUNG_BARS)
    utad_fresh = (latest == "UTAD" and latest_age <= EVENT_FRESH_BARS)
    broke_up = rst and c > rst * 1.01
    broke_dn = sup and c < sup * 0.99

    if f["parabolic_broken"]:
        state, sscore = "UNDETERMINED", 20
        evid = [f"מהלך פרבולי מורחב עם תיקון של ~{f['dist_from_high']*100:.0f}% בנפח ו-OBV יורד — אין טווח מסחר נקי."]
        missing = ["היווצרות טווח מסחר אמיתי (תמיכה/התנגדות שנבחנות מספר פעמים)"]
    elif is_range:
        pos_val = tr.get("position", 0.5)
        obv_ok = f["obv_dir"] >= -0.05
        obv_pos = f["obv_dir"] >= 0.0
        # 1) מחיר כבר עזב את הטווח (פריצה/שבירה) — קודם כל
        if broke_dn or latest == "SOW":
            state, sscore = "DIST_ACTIVE", 70
            evid = ["שבירת תמיכת הטווח בנפח (SOW) — הפצה מאושרת."]
        elif broke_up or latest == "SOS":
            state, sscore = "ACC_CONFIRM", 78
            evid = ["SOS / פריצה מעל ההתנגדות בנפח — איסוף מאושר, אזור LPS לתוספת לפני המשך."]
        elif utad_fresh or (f["has_bc"] and pos_val >= 0.6):
            # V25.1: אפ-ת'ראסט = הפצה *רק אם זרימת הכסף/השבועי מאשרים היצע*. OBV חיובי
            # ושבועי לא-דובי ⇒ סביר יותר ניעור/כישלון-פריצה בתוך איסוף (שלב D בזהירות), לא הפצה.
            dist_confirmed = (not obv_pos) or (wb < 0.0)
            if dist_confirmed:
                state, sscore = "DIST_WARNING", 58
                evid = ["Upthrust בפסגת הטווח + זרימת הון/הקשר שבועי תומכים היצע — סימני הפצה."]
                missing = ["SOW (שבירת תמיכה בנפח) לאישור הפצה"]
            else:
                state, sscore, caution = "ACC_CONFIRM", 56, True
                evid = ["דחייה/אפ-ת'ראסט בפסגה — אך OBV חיובי והשבועי לא-דובי: סביר יותר ניעור/"
                        "כישלון-פריצה בתוך איסוף (שלב D) מאשר הפצה. זהירות עד התייצבות."]
                missing = ["SOS — סגירה מעל ההתנגדות בנפח; היזהר משבירת תמיכה בנפח (יבטל את הקריאה)"]
        # 2) מחיר *בתוך* הטווח — המיקום הנוכחי גובר על אירוע ישן (תיקון BKNG):
        elif pos_val >= 0.55 and obv_pos:
            # חצי עליון + הון נכנס ⇒ מתקדם לעבר הפריצה (LPS) = שלב D, גם אם ה-Spring היה מזמן.
            # תיקון פולבק תוך שמירה על OBV חיובי = LPS תקין, עם דגל זהירות אם ירד מהשיא.
            state, sscore = "ACC_CONFIRM", 68 if pos_val >= 0.62 else 60
            if f["dist_from_high"] >= 0.05:
                caution = True
            evid = ["מחיר בחצי העליון של הטווח עם OBV חיובי — מתקדם לעבר הפריצה (LPS). האיסוף בשלב מתקדם (D)."]
            missing = ["SOS — סגירה מעל ההתנגדות בנפח לאישור הפריצה"]
        elif pos_val <= 0.38:
            # חצי תחתון — שלב C רק אם הניעור *טרי*; ניעור ישן = הקריאה פגה, חוזרים לבסיס
            if spring_fresh:
                if spring_young:
                    state, sscore = "ACC_SPRING", 70
                    evid = [f"Spring טרי (לפני {latest_age} ימי מסחר) בתחתית הטווח — חדירה מתחת לתמיכה ובליעה מיידית (מלכודת דובים)."]
                    missing = ["SOS (אישור) להמשך לשלב D"]
                else:
                    state, sscore = "ACC_SPRING", 58
                    evid = [f"Spring לפני {latest_age} ימי מסחר — עדיין בתוקף אך מזדקן: ככל שמתארך ללא SOS, הקריאה נחלשת."]
                    missing = ["SOS בקרוב — אחרת הניעור יסווג כפג והמניה תחזור לבניית בסיס"]
            elif latest == "Spring":
                state, sscore = "ACC_BASE", 46
                evid = [f"ניעור (Spring) לפני ~{latest_age} ימי מסחר שלא קיבל אישור (SOS) — הקריאה פגה; הבסיס ממשיך להיבנות (שלב B)."]
                missing = ["Spring חדש או SOS — טריגר עדכני לכניסה"]
            elif f["has_sc"] or f["has_stopping"] or wb < 0:
                state, sscore = "ACC_BASE", 50
                evid = ["טווח מסחר בתחתית עם בלימת ירידות — בניית בסיס (איסוף מוקדם)."]
                missing = ["Spring (ניעור) או SOS — הטריגרים לכניסה"]
            else:
                state, sscore = "ACC_BASE", 42
                evid = ["מחיר בתחתית הטווח — בנייה מוקדמת, ללא אירוע מאשר עדיין."]
                missing = ["Spring/SOS — הטריגרים לכניסה"]
        else:
            # אמצע הטווח — אזור החלטה; מכריעים לפי אירוע + OBV + שבועי
            if spring_fresh and obv_ok:
                state, sscore = ("ACC_SPRING", 60) if spring_young else ("ACC_SPRING", 52)
                _sp_note = "טרי" if spring_young else f"מזדקן ({latest_age} ימים ללא SOS)"
                evid = [f"Spring {_sp_note} (לפני {latest_age} ימי מסחר) שמתאושש דרך אמצע הטווח — איסוף בשלב C."]
                missing = ["SOS לאישור שלב D"]
            elif f["has_sos"] and obv_pos:
                state, sscore = "ACC_CONFIRM", 64
                evid = ["SOS קודם + החזקה באמצע הטווח (LPS) — איסוף מאושר."]
            elif wb >= 0.3:
                state, sscore = "ACC_BASE", 45
                evid = ["טווח מסחר בהקשר שבועי חיובי, ללא אירוע מאשר מובהק עדיין."]
                missing = ["אירוע מאשר (Spring/SOS)"]
            elif wb <= -0.3 and not obv_pos:
                state, sscore = "DIST_WARNING", 42
                evid = ["טווח מסחר בהקשר שבועי שלילי + OBV לא-חיובי — סיכון הפצה, ללא אישור עדיין."]
            else:
                state, sscore = "UNDETERMINED", 32
                evid = ["מחיר באמצע הטווח ללא אירוע מאשר וללא הטיה רב-טווחית — אזור החלטה לא ברור."]
                missing = ["אירוע מאשר (Spring/SOS/UTAD/SOW)"]
    elif f["trend"] == "up" and f["obv_dir"] >= -0.05:
        state, sscore = "MARKUP", 65
        evid = ["מבנה מגמת עלייה (שיאים/שפלים עולים, OBV תומך)."]
    elif f["trend"] == "down":
        state, sscore = "MARKDOWN", 65
        evid = ["מבנה מגמת ירידה (שיאים/שפלים יורדים)."]
    else:
        state, sscore = "UNDETERMINED", 25
        evid = ["אין טווח מסחר ואין מבנה מגמה ברור."]
        missing = ["מבנה ברור (טווח או מגמה)"]

    return {"state": state, "structural_score": sscore, "evidence": evid,
            "required_missing": missing, "features": f, "caution": caution}


def compute_phase_confidence(state_obj: dict, weekly_ctx: dict, vsa: list,
                             cis: float, engine_phase: str, tr: dict) -> dict:
    """
    ציון ביטחון רציף (0-100) — *נפרד מ-CIS*. מודד כמה הקריאה המבנית חזקה ונקייה.
    משקלים: שלמות מבנית 35% · אישור VSA 20% · יישור שבועי 20% · איכות טווח 10% ·
    אישור CIS 10% · הסכמת מנוע 5%. CIS הוא מאַשר (10%), לא קובע.
    """
    f = state_obj.get("features", {})
    state = state_obj.get("state", "UNDETERMINED")
    track = _WSTATES.get(state, {}).get("track", "none")
    structural = max(0.0, min(1.0, state_obj.get("structural_score", 25) / 100.0))

    vp = sum(1 for b in (vsa or []) if b.get("tone") == "pos")
    vn = sum(1 for b in (vsa or []) if b.get("tone") == "neg")
    if track == "bull":
        vsa_c = 1.0 if vp > vn else (0.5 if vp == vn else 0.2)
    elif track == "bear":
        vsa_c = 1.0 if vn > vp else (0.5 if vp == vn else 0.2)
    else:
        vsa_c = 0.3

    wb = float(weekly_ctx.get("weekly_bias", 0.0))
    if track == "bull":
        weekly_c = max(0.0, min(1.0, (wb + 1) / 2))
    elif track == "bear":
        weekly_c = max(0.0, min(1.0, (-wb + 1) / 2))
    else:
        weekly_c = 0.3

    if tr.get("is_range"):
        rq = min(1.0, 0.5 + 0.07 * (tr.get("touches_s", 0) + tr.get("touches_r", 0)))
    else:
        rq = 0.1 if state in ("MARKUP", "MARKDOWN") else 0.0

    try:
        cisv = float(cis)
    except Exception:
        cisv = 50.0
    if track == "bull":
        cis_c = max(0.0, min(1.0, (cisv - 40) / 40))
    elif track == "bear":
        cis_c = max(0.0, min(1.0, (60 - cisv) / 40))
    else:
        cis_c = 0.3

    fam = _phase_family(engine_phase)
    eng = 1.0 if ((track == "bull" and fam in ("bullish_adv", "bullish_early"))
                  or (track == "bear" and fam == "bearish")) else 0.3

    conf = 100 * (0.35 * structural + 0.20 * vsa_c + 0.20 * weekly_c
                  + 0.10 * rq + 0.10 * cis_c + 0.05 * eng)
    conf = int(round(max(0, min(100, conf))))
    band = "high" if conf >= 70 else ("mid" if conf >= 50 else ("low" if conf >= 30 else "none"))
    breakdown = {"מבנה": round(structural * 100), "VSA": round(vsa_c * 100),
                 "שבועי": round(weekly_c * 100), "טווח": round(rq * 100),
                 "CIS": round(cis_c * 100), "מנוע": round(eng * 100)}
    return {"confidence": conf, "band": band, "breakdown": breakdown}


def build_structural_trade_plan(state_obj: dict, tr: dict, events: list,
                                df: pd.DataFrame, confidence: int) -> dict:
    """
    תוכנית סווינג *מבוססת מבנה* (לא ATR). רק למצבים שורי-פעולה (ACC_SPRING/CONFIRM)
    בביטחון ≥50 ובתוך טווח אמיתי. סטופ = שבירה מבנית (מתחת לשפל הניעור/התמיכה);
    יעדים = Cause & Effect + ההתנגדות. אחרת valid=False (אין תוכנית כפויה).
    """
    res = {"valid": False}
    try:
        state = state_obj.get("state")
        if state not in ("ACC_SPRING", "ACC_CONFIRM") or confidence < 50 or not tr.get("is_range"):
            return res
        c = float(df["Close"].iloc[-1])
        sup, rst, mid = tr["support"], tr["resistance"], tr["midpoint"]
        recent_low = float(df["Low"].tail(15).min())
        spring_low = recent_low
        for e in (events or []):
            if "Spring" in e.get("event", ""):
                spring_low = min(spring_low, float(e.get("price", recent_low)))
                break
        stop = round(min(spring_low, sup) * 0.985, 2)             # מתחת לשפל המבני
        entry_lo = round(min(c, sup * 1.01), 2)
        entry_hi = round(max(c, mid), 2)
        ce = wyckoff_cause_effect_targets(df, tr)
        if ce.get("valid"):
            t1, t2, t3 = rst, ce["up"]["conservative"]["price"], ce["up"]["base"]["price"]
        else:
            t1, t2, t3 = rst, round(rst * 1.10, 2), round(rst * 1.20, 2)
        risk = c - stop
        rr = round((t2 - c) / risk, 1) if risk > 0 else 0.0
        invalid = f"סגירה יומית מתחת ${stop} בנפח — הניעור/האישור נכשל, הקריאה בטלה (צא)."
        time_txt = "סווינג של 2-6 שבועות; צפה לפריצה/אישור בתוך הטווח הזה."
        res = {"valid": True, "entry_lo": entry_lo, "entry_hi": entry_hi, "stop": stop,
               "t1": round(t1, 2), "t2": round(t2, 2), "t3": round(t3, 2),
               "rr": rr, "invalidation": invalid, "time": time_txt}
    except Exception:
        pass
    return res


def build_phase_playbook(state_obj: dict, tr: dict, events: list, confidence: int,
                         cis: float = 0.0) -> dict:
    """
    ה-Playbook ('אם-אז') לכל מצב — שורה תחתונה פשוטה קודם, ואז המסלול הצפוי
    ומה לעשות אם משתבש (לחזק/לצאת/לצאת חלקית). זהו הלב של ההסבר להדיוט.
    """
    state = state_obj.get("state", "UNDETERMINED")
    missing = state_obj.get("required_missing", [])
    pb = {"bottom_line": "", "primary": "", "if_fails": "", "if_chops": "",
          "time": "", "actions": []}

    if state == "ACC_SPRING":
        pb["bottom_line"] = "זוהה ניעור (Spring) — אזור הכניסה הקלאסי של וויקוף. כניסה על המבחן, סטופ מתחת לשפל הניעור."
        pb["primary"] = "אם הניעור מחזיק ומגיע SOS (פריצת אמצע-טווח בנפח) → חזק את הפוזיציה והעלה סטופ לשפל הניעור."
        pb["if_fails"] = "אם סגירה חזרה מתחת לשפל הניעור בנפח → ניעור כושל. צא מיד — צפוי Markdown."
        pb["if_chops"] = "אם דשדוש ללא כיוון → המתן, החזק חצי פוזיציה עד אישור SOS."
        pb["time"] = "צפה ל-SOS תוך 1-3 שבועות; אם לא קורה — ה-setup מתיישן, הקטן/צא."
    elif state == "ACC_CONFIRM":
        pb["bottom_line"] = "האיסוף אושר (SOS + LPS) — אזור תוספת לפני הפריצה."
        pb["primary"] = "ה-LPS (פולבק בנפח נמוך לתמיכה/רמת הפריצה) הוא אזור התוספת. החזק ליעד ה-Cause & Effect."
        pb["if_fails"] = "אם ה-LPS נכשל (סגירה מתחת לתמיכה בנפח) → צמצם או צא, האישור התבטל."
        pb["if_chops"] = "דשדוש מעל התמיכה = בריא. החזק."
        pb["time"] = "צפה לפריצה תוך 1-4 שבועות."
    elif state == "MARKUP":
        pb["bottom_line"] = "מגמת עלייה (Markup) — לרכוב עם סטופ נגרר מתחת לשפלים העולים."
        pb["primary"] = "גרור סטופ מתחת לכל שפל-עולה. שחרר חלקית לתוך נפח קלימקטי (Buying Climax)."
        pb["if_fails"] = "אם נשבר שפל-עולה בנפח → צמצם; אם מופיע UTAD/Buying-Climax → צא."
        pb["if_chops"] = "קונסולידציה במגמה = בריא (אפשרי איסוף-חוזר). החזק, אל תרדוף."
        pb["time"] = "מגמה — מוחזק כל עוד מבנה השפלים העולים שלם."
    elif state == "ACC_BASE":
        pb["bottom_line"] = "נבנה בסיס בתחתית — מוקדם. עקוב, אל תיכנס עדיין."
        pb["primary"] = "המתן ל-Spring (ניעור) או ל-SOS — אלו הטריגרים לכניסה."
        pb["if_fails"] = "אם המחיר שובר את תחתית הבסיס בנפח → אין איסוף, הימנע."
        pb["if_chops"] = "דשדוש בבסיס = בנייה תקינה. המשך לעקוב."
        pb["time"] = "בנייה יכולה להימשך שבועות-חודשים; אין למהר."
    elif state == "DIST_WARNING":
        pb["bottom_line"] = "סימני הפצה בפסגה — זהירות. אם אתה מחזיק, שקול צמצום לתוך חוזק."
        pb["primary"] = "אל תיכנס לונג. אם מחזיק — צמצם חלקית, הדק סטופ."
        pb["if_fails"] = "אם SOW (שבירת תמיכה בנפח) → צא לגמרי."
        pb["if_chops"] = "אם פריצה מחודשת מעל ההתנגדות בנפח → האזהרה בטלה, חזרה ל-Markup."
        pb["time"] = "החלטה בדרך כלל בתוך 1-4 שבועות."
    elif state == "DIST_ACTIVE":
        pb["bottom_line"] = "הפצה אושרה / שבירה — אזור יציאה. אין לונג."
        pb["primary"] = "צא מפוזיציות לונג. כיוון המהלך הבא מטה."
        pb["if_fails"] = "התאוששות מעל התמיכה השבורה בנפח גבוה תבטל את התרחיש — נדיר, דרוש אישור."
        pb["time"] = "—"
    elif state == "MARKDOWN":
        pb["bottom_line"] = "מגמת ירידה — להימנע מלונג. המתן לבלימה (Selling Climax) ובניית בסיס."
        pb["primary"] = "אין כניסת לונג. חפש SC + AR + טווח כדי לשקול איסוף עתידי."
        pb["if_fails"] = "—"
        pb["time"] = "—"
    else:  # UNDETERMINED
        strong_cis = ""
        try:
            if float(cis) >= 70:
                strong_cis = "יש טביעת כסף חכם חזקה, אבל "
        except Exception:
            pass
        pb["bottom_line"] = f"אין פאזת וויקוף ברורה כרגע — {strong_cis}אין מבנה טווח תקין. עדיף להמתין."
        pb["primary"] = ("מה יהפוך את זה לסחיר: " + "; ".join(missing) + ".") if missing \
            else "מה יהפוך את זה לסחיר: היווצרות טווח מסחר עם אירוע מאשר (Spring/SOS)."
        pb["if_fails"] = "אין פוזיציה לנהל — אין כניסה מומלצת."
        pb["if_chops"] = ""
        pb["time"] = _RESCAN_HINT
    return pb


def _compute_days_in_phase(df: pd.DataFrame, tr: dict, is_bull: bool,
                           state: str = None, events: list = None) -> int:
    """
    V25.9 — ימים ברצף בפאזה הנוכחית. V26.0: עיגון-אירוע — פאזות שמוגדרות ע"י אירוע
    נספרות *מאז האירוע* (Spring→שלב C, SOS→שלב D, Upthrust→אזהרת הפצה), כי Spring
    הוא אירוע נקודתי: "86 ימים בשלב C" היה שילוב בלתי-אפשרי של ימי-טווח עם תווית-אירוע.
    ללא עוגן-אירוע: טווח = ימים בתוך תמיכה/התנגדות; מגמה = ימים מעל/מתחת SMA20.
    """
    try:
        if state and events:
            _anchor = {"ACC_SPRING": "Spring", "ACC_CONFIRM": "SOS",
                       "DIST_WARNING": "Upthrust"}.get(state)
            if _anchor:
                for e in events:
                    if _anchor in (e.get("event", "") or ""):
                        return int(e.get("age_bars", 0) or 0) + 1
        closes = df["Close"].values
        if tr.get("is_range") and tr.get("support") and tr.get("resistance"):
            lo = float(tr["support"]) * 0.97
            hi = float(tr["resistance"]) * 1.03
            d = 0
            for pxv in closes[::-1]:
                if lo <= float(pxv) <= hi:
                    d += 1
                else:
                    break
            return d
        ma = _sma(df["Close"], 20)
        d = 0
        for i in range(len(closes) - 1, -1, -1):
            m = ma.iloc[i] if hasattr(ma, "iloc") else ma[i]
            if m != m:  # NaN
                break
            if (is_bull and float(closes[i]) >= float(m)) or ((not is_bull) and float(closes[i]) <= float(m)):
                d += 1
            else:
                break
        return d
    except Exception:
        return 0


def analyze_wyckoff_structural(df: pd.DataFrame, weekly_ctx: dict, factors,
                               cis: float, engine_phase: str) -> dict:
    """
    התזמורת: מריץ את כל הצינור המבני ומחזיר wyckoff_state אחיד. נקרא מ-_compute_wyckoff.
    """
    tr = detect_trading_range(df)
    events = detect_wyckoff_events(df, tr)
    vsa = classify_vsa_bars(df, 15)
    state_obj = classify_wyckoff_state(df, tr, events, vsa, weekly_ctx)
    conf = compute_phase_confidence(state_obj, weekly_ctx, vsa, cis, engine_phase, tr)
    confidence = conf["confidence"]
    state = state_obj["state"]
    meta = _WSTATES.get(state, _WSTATES["UNDETERMINED"])

    if state == "UNDETERMINED":
        status = "transition"
    elif meta["track"] == "bear" and state != "MARKDOWN":
        status = "caution"
    elif confidence < 30:
        status = "transition"
    else:
        status = "confirmed"

    plan = build_structural_trade_plan(state_obj, tr, events, df, confidence)
    playbook = build_phase_playbook(state_obj, tr, events, confidence, cis)

    # V25.1: דגל "בזהירות" — מצב שורי עם סיכון תיקון. משנה תווית + שורה תחתונה + סטטוס
    # (מ-confirmed ל-caution) כדי שהמסר יהיה "שלב D אבל היזהר", לא אישור נקי.
    caution = bool(state_obj.get("caution")) and meta["track"] == "bull"
    phase_he = meta["he"]
    bottom_line = playbook["bottom_line"]
    if caution:
        phase_he = meta["he"] + " — בזהירות"
        if status == "confirmed":
            status = "caution"
        _cau_head = "שלב D בזהירות" if state == "ACC_CONFIRM" else (meta["he"] + " בזהירות")
        bottom_line = (f"⚠️ {_cau_head} — תיקון אפשרי. המתן לאישור (שפל גבוה-יותר + נפח דועך) "
                       f"לפני כניסה/תוספת.")

    # V25.9: "ימים ברצף בפאזה" — proxy יציב למשך הפאזה, מהנתונים הקיימים.
    days_in_phase = _compute_days_in_phase(df, tr, meta["track"] == "bull",
                                           state=state, events=events)

    return {"state": state, "phase_he": phase_he, "track": meta["track"], "simple": meta["simple"],
            "status": status, "confidence": confidence, "conf_band": conf["band"],
            "conf_breakdown": conf["breakdown"], "evidence": state_obj["evidence"],
            "missing": state_obj["required_missing"], "tr": tr, "events": events, "vsa": vsa,
            "weekly": weekly_ctx, "plan": plan, "playbook": playbook, "caution": caution,
            "days_in_phase": days_in_phase, "bottom_line": bottom_line}


def _breakout_readiness(ws: dict) -> dict:
    """
    V25.9 — מוכנות ליציאה למהלך (Markup): תווית מילולית (קרוב/מתקרב/רחוק) + ימים
    ברצף בפאזה. *ללא ציון מספרי* — לפי בקשת המשתמש. טהור (מקבל wyckoff_state בלבד),
    עמיד-כשל. readiness_rank הוא לצורכי *מיון בלבד* ואינו מוצג.
    מחזיר: {applicable, label, emoji, days, rank, note}.
    """
    try:
        state = ws.get("state", "")
        tr = ws.get("tr") or {}
        pos = float(tr.get("position", 0.5))
        days = int(ws.get("days_in_phase", 0) or 0)
        caution = bool(ws.get("caution"))
        # לא רלוונטי לכיוון דובי / חוסר מבנה — אין "מוכנות למהלך עלייה"
        if state in ("DIST_WARNING", "DIST_ACTIVE", "MARKDOWN", "UNDETERMINED", ""):
            return {"applicable": False, "days": days, "rank": 0}
        if state == "MARKUP":
            return {"applicable": True, "label": "כבר במהלך", "emoji": "🚀", "days": days,
                    "rank": 5, "note": "המהלך כבר החל — המניה בשלב עלייה (Markup)."}
        if state == "ACC_CONFIRM":
            if caution:
                lab, em, rk = "מתקרב — תיקון בתוך שלב D", "🟡", 3
                note = "היה קרוב, אך יש תיקון בפסגה; המתן לאישור שהתמיכה מחזיקה."
            elif pos >= 0.66:
                lab, em, rk = "קרוב מאוד לפריצה", "🟢", 4
                note = "בשלב D בחלק העליון של הטווח — קרוב לנקודת פריצה (SOS)."
            elif pos >= 0.5:
                lab, em, rk = "מתקרב לפריצה", "🟢", 3
                note = "בשלב D, מתקדם לעבר ההתנגדות — עוד לא בפסגת הטווח."
            else:
                lab, em, rk = "מתקרב — חזר לאמצע הטווח", "🟡", 2
                note = "בשלב D אך המחיר נסוג לאמצע הטווח (LPS) — צובר לקראת ניסיון נוסף."
        elif state == "ACC_SPRING":
            if days <= 10:
                lab, em, rk = "מתקרב — ניעור ממתין לאישור (SOS)", "🟡", 2
                note = "שלב C (Spring טרי) — אזור הכניסה הקלאסי; המעבר לשלב D מותנה באישור SOS."
            else:
                lab, em, rk = "ממתין זמן רב — הניעור מאבד תוקף", "🟠", 1
                note = (f"ניעור ללא אישור (SOS) כבר {days} ימי מסחר — ככל שמתארך, הקריאה נחלשת; "
                        f"ללא SOS בקרוב הניעור ייחשב כפג והמניה תסווג כבניית בסיס.")
        else:  # ACC_BASE
            lab, em, rk = "רחוק — מוקדם, בסיס נבנה", "🔴", 1
            note = "שלב A/B — תחילת האיסוף; מוקדם מדי להערכת קרבה למהלך."
        return {"applicable": True, "label": lab, "emoji": em, "days": days, "rank": rk, "note": note}
    except Exception:
        return {"applicable": False, "days": 0, "rank": 0}


def _readiness_days_he(days: int) -> str:
    """ניסוח עברי לימים ברצף בפאזה."""
    if days <= 0:
        return ""
    if days == 1:
        return "יום 1 בפאזה"
    return f"{days} ימים ברצף בפאזה"


def refine_wyckoff_phase(df: pd.DataFrame, factors: pd.DataFrame, engine_phase: str):
    """
    שכבת אימות (Confirmation Overlay) מעל פלט מנוע הליבה. *אינה* משנה את FactorEngine —
    רק קוראת את אותם נתונים גולמיים. שלושה מצבים אפשריים בפלט (status):
      • "confirmed"  — תווית פאזה מאושרת (של המנוע, או שדרוג ודאי ממצב מעבר).
      • "transition" — אין פאזה מאושרת: מנוסח 'יצאנו מ-X / ממתינים לאישור ל-Y' (לא כופים פאזה).
      • "caution"    — המנוע נתן תווית המשך-עלייה, אך הראיות מצביעות על תיקון/הפצה בנפח גבוה.

    רקע (תיקון "בעיית WULF" בשני הכיוונים):
      (א) המנוע מסווג Phase E רק אם OBV וגם RS חיוביים — לכן פריצה אמיתית שאחד הסינונים
          המשניים בקושי פספס נזרקת ל-TRANSITION. כאן משדרגים כשמבנה המחיר חד-משמעי.
      (ב) ענף ה-Re-accumulation של המנוע בודק רק נפח של נר בודד (v<v_ma) וללא תקרת עומק
          לפולבק — לכן ירידה חדה ועמוקה בנפח גבוה (כמו WULF) מתויגת בטעות כ'איסוף חוזר רגוע'.
          כאן מורידים תווית כזו ל'סיכון הפצה / ממתינים לאישור', במקום לכפות פאזה שורית.

    מחזיר: (display_phase, was_refined, note, status)
    שמרני: לעולם לא מוריד תווית ודאית *תקינה* של המנוע; פועל רק על מעבר או על המשך-עלייה חשוד.
    """
    try:
        fam = _phase_family(engine_phase)

        # ---------- (1) caution: תווית המשך-עלייה שנראית כמו הפצה בנפח גבוה ----------
        is_continuation = (
            any(k in engine_phase for k in ("Re-accumulation", "Phase E", "Markup", "Phase D", "LPS", "SOS", "Breakout"))
            and "Spring" not in engine_phase and "Phase C" not in engine_phase
        )
        if is_continuation:
            risk = detect_distribution_risk(df)
            if risk["risk"]:
                why = "; ".join(risk["reasons"][:3])
                note = (
                    f"המנוע סיווג '{engine_phase}' (המשך עלייה), אך זהו אינו פולבק רגוע: המחיר ירד "
                    f"כ-{risk['dist_pct']:.0f}% מהשיא, ו-{why}. זו חתימת נפח של תיקון/הפצה — איסוף "
                    f"חוזר אמיתי (LPS/BUEC) דורש נפח *דועך*, לא מתרחב. לכן אין כרגע פאזה חדשה מאושרת. "
                    f"ממתינים לאישור: שפל גבוה-יותר בנפח נמוך ואז סגירה מעל ${risk['resistance']} בנפח "
                    f"(חידוש עלייה) — או סגירה יומית מתחת ${risk['support']} בנפח (מעבר מאושר להפצה). {_RESCAN_HINT}"
                )
                return "⚠️ מצב מעבר — סיכון הפצה / תיקון בנפח גבוה (Distribution Risk)", True, note, "caution"

        # ---------- (2) המנוע ודאי (לא מעבר) → בדיקת עקביות מבנית לפני אישור ----------
        # תופס מקרים כמו WULF: תווית תלוית-טווח (Re-accumulation/LPS/BUEC) שנכפית כשאין טווח.
        if fam != "transition":
            tr_ctx = detect_trading_range(df)
            coherent, c_reason, c_watch = assess_phase_coherence(df, engine_phase, tr_ctx)
            if not coherent:
                note = (f"המנוע סיווג '{engine_phase}', אך הסיווג אינו עקבי עם המבנה. {c_reason} "
                        f"לכן המערכת *אינה כופה* פאזת איסוף. {c_watch} {_RESCAN_HINT}")
                return "מצב מעבר — אין פאזה מאושרת (ממתינים לאישור)", True, note, "transition"
            return engine_phase, False, "", "confirmed"

        # אין מספיק נתונים → לא כופים פאזה, מסבירים שממתינים
        if df is None or len(df) < 60:
            ctx = describe_phase_transition(df, engine_phase)
            note = f"יצאנו מ: {ctx['exited']}. ממתינים לאישור כניסה ל: {ctx['awaiting']}. מה לחפש: {ctx['watch']} {_RESCAN_HINT}"
            return "מצב מעבר — אין פאזה מאושרת (ממתינים לאישור)", True, note, "transition"

        close = df["Close"]
        c = float(close.iloc[-1])
        o = float(df["Open"].iloc[-1])
        v = float(df["Volume"].iloc[-1])
        v_ma = float(df["Volume"].rolling(20).mean().iloc[-1]) if len(df) >= 20 else v
        s20, s50, s200 = _sma(close, 20), _sma(close, 50), _sma(close, 200)
        if not any(pd.isna(x) for x in (s20, s50)):
            if pd.isna(s200):
                s200 = s50
            high60 = float(df["High"].rolling(60).max().iloc[-1])
            vol_exp = (v > v_ma * 1.5) if v_ma else False

            # OBV slope (10) ו-RS — בדיוק הסינונים המשניים שהמנוע מקפיד עליהם
            obv = (np.sign(close.diff()) * df["Volume"]).cumsum()
            obv_slope = float(obv.diff(10).iloc[-1]) if len(obv) >= 10 else 0.0
            rs = 0.0
            if "spy_close" in df.columns:
                try:
                    rs = float((close.pct_change(20).iloc[-1] - df["spy_close"].pct_change(20).iloc[-1]))
                except Exception:
                    rs = 0.0

            near_high = c >= high60 * 0.97
            full_stack = c > s20 and s20 > s50 and s50 > s200

            # ---------- (3) שדרוג ממצב מעבר כשמבנה המחיר חד-משמעי ----------
            # (3a) Markup ברור: סטאק ממוצעים מלא + צמוד לשיא 60 יום
            if full_stack and near_high:
                why = []
                if obv_slope <= 0:
                    why.append("זרימת ההון (OBV) שטוחה/שלילית קלות")
                if rs <= 0:
                    why.append("עוצמה יחסית מול השוק עדיין לא חיובית")
                reason = " ו".join(why) if why else "אישור משני חלקי בלבד"
                note = (f"מבנה המחיר חד-משמעית במגמת עלייה (סגירה מעל כל הממוצעים, צמוד לשיא 60 יום), "
                        f"אך המנוע סיווג 'מעבר' כי {reason}. שכבת האימות משדרגת ל-Phase E.")
                return "Phase E (Markup) — אומת אפליקטיבית", True, note, "confirmed"

            # (3b) Breakout/SOS ברור: מעל SMA50, נר ירוק, נפח מתרחב, קרוב לשיא
            if c > s50 and c > o and vol_exp and c >= high60 * 0.92:
                note = ("פריצה בעוצמה: סגירה ירוקה מעל ממוצע 50, התרחבות נפח משמעותית וקרבה לשיא 60 יום. "
                        "המנוע נשאר ב'מעבר' (לרוב בגלל OBV), אך מבנה הפריצה ברור — שודרג ל-Phase D (SOS).")
                return "Phase D (SOS / Breakout) — אומת אפליקטיבית", True, note, "confirmed"

            # (3c) Spring/Shakeout ברור שלא תוייג: שפל חדש שנבלע + סגירה ירוקה בנפח גבוה
            low60 = float(df["Low"].rolling(60).min().shift(1).iloc[-1])
            is_new_low = float(df["Low"].iloc[-1]) < low60
            if is_new_low and c > o and vol_exp and obv_slope >= 0:
                note = ("ניעור נזילות (Spring): שפל חדש מתחת לטווח שנבלע מיד עם סגירה ירוקה ונפח גבוה, "
                        "וה-OBV מחזיק. תבנית Phase C קלאסית ששכבת האימות מדגישה.")
                return "Phase C (Spring / Liquidity Sweep) — אומת אפליקטיבית", True, note, "confirmed"

        # ---------- (4) באמת אין פאזה מובהקת → 'יצאנו מ-X / ממתינים ל-Y' (לא כופים פאזה) ----------
        ctx = describe_phase_transition(df, engine_phase)
        note = f"יצאנו מ: {ctx['exited']}. ממתינים לאישור כניסה ל: {ctx['awaiting']}. מה לחפש: {ctx['watch']}"
        return "מצב מעבר — אין פאזה מאושרת (ממתינים לאישור)", True, note, "transition"
    except Exception:
        return engine_phase, False, "", "confirmed"


def build_phase_evidence(df: pd.DataFrame, factors: pd.DataFrame, phase: str) -> list:
    """
    מנוע ראיות: מסביר *למה* המערכת חושבת שזו הפאזה — לפי נפח, מחיר, ספיגה, OBV, RS,
    שבירת מבנה ו-Effort vs Result. קורא את עמודות הפקטורים האמיתיות של המנוע.
    מחזיר רשימת dict: {tone: pos/neg/neu, label, value, text}.
    """
    out = []
    try:
        if df is None or df.empty:
            return out
        close = df["Close"]
        c = float(close.iloc[-1])
        o = float(df["Open"].iloc[-1])
        v = float(df["Volume"].iloc[-1])
        v_ma = float(df["Volume"].rolling(20).mean().iloc[-1]) if len(df) >= 20 else (v or 1.0)
        vol_ratio = (v / v_ma) if v_ma else 1.0
        s20, s50, s200 = _sma(close, 20), _sma(close, 50), _sma(close, 200)
        if pd.isna(s200):
            s200 = s50
        high60 = float(df["High"].rolling(60).max().iloc[-1]) if len(df) >= 60 else c
        low60 = float(df["Low"].rolling(60).min().iloc[-1]) if len(df) >= 60 else c
        rng60 = max(1e-9, high60 - low60)
        pos_in_range = (c - low60) / rng60 * 100.0

        def f(col, default=0.0):
            try:
                if factors is not None and col in factors.columns:
                    val = factors[col].iloc[-1]
                    return float(val) if pd.notna(val) else default
            except Exception:
                pass
            return default

        absorption = f("f04_absorption")
        obv_vel = f("f07_obv_velocity")
        liq_sweep = f("f20_liquidity_sweep")
        struct_break = f("f35_struct_break")
        effort = f("f_effort_vs_result", 1.0)
        stopping = f("f_stopping_volume")
        rs = f("f_rs_spy")

        # --- מבנה מחיר ---
        if c > s20 and s20 > s50 and s50 > s200:
            out.append({"tone": "pos", "label": "מבנה מחיר", "value": "סטאק שורי מלא",
                        "text": "המחיר מעל ממוצעי 20/50/200 בסדר עולה — תמיכה מבנית מלאה למגמת עלייה."})
        elif c < s20 and s20 < s50:
            out.append({"tone": "neg", "label": "מבנה מחיר", "value": "מבנה חלש",
                        "text": "המחיר מתחת לממוצעי 20 ו-50 — היצע כלוא מעל מכביד על כל ניסיון עלייה."})
        else:
            out.append({"tone": "neu", "label": "מבנה מחיר", "value": "דשדוש",
                        "text": "הממוצעים שזורים — אין כיוון מבני מובהק, מצב טיפוסי לאיסוף/הפצה."})

        # --- מיקום בטווח 60 יום ---
        if pos_in_range >= 80:
            out.append({"tone": "pos", "label": "מיקום בטווח", "value": f"{pos_in_range:.0f}% מהטווח",
                        "text": "המחיר בקצה העליון של טווח 60 הימים — קרבה לפריצה / כבר באזור עליון."})
        elif pos_in_range <= 20:
            out.append({"tone": "neu", "label": "מיקום בטווח", "value": f"{pos_in_range:.0f}% מהטווח",
                        "text": "המחיר בתחתית טווח 60 הימים — כאן מתרחשים Spring וניעורים, או המשך חולשה."})
        else:
            out.append({"tone": "neu", "label": "מיקום בטווח", "value": f"{pos_in_range:.0f}% מהטווח",
                        "text": "המחיר באמצע טווח 60 הימים — אזור החלטה."})

        # --- נפח ---
        if vol_ratio >= 1.5:
            tone = "pos" if c >= o else "neg"
            direction = "קונים אגרסיביים" if c >= o else "לחץ מכירה"
            out.append({"tone": tone, "label": "נפח", "value": f"x{vol_ratio:.1f} מהממוצע",
                        "text": f"נפח גבוה משמעותית מהרגיל ({direction}) — נוכחות של כסף גדול (מוסדי) בנר זה."})
        elif vol_ratio <= 0.7:
            out.append({"tone": "neu", "label": "נפח", "value": f"x{vol_ratio:.1f} מהממוצע",
                        "text": "נפח דליל — אין דחיפה מוסדית פעילה כרגע לאף כיוון."})
        else:
            out.append({"tone": "neu", "label": "נפח", "value": f"x{vol_ratio:.1f} מהממוצע",
                        "text": "נפח ממוצע — ללא אנומליה."})

        # --- ספיגה (Absorption) ---
        if absorption >= 1.2:
            out.append({"tone": "pos", "label": "ספיגה (Absorption)", "value": f"{absorption:.2f}",
                        "text": "מאמץ מכירה גבוה נספג בלי שהמחיר נשבר — מישהו גדול קונה את ההיצע בשקט."})
        elif absorption > 0:
            out.append({"tone": "neu", "label": "ספיגה (Absorption)", "value": f"{absorption:.2f}",
                        "text": "ספיגת היצע מתונה — אין עדות חזקה לקנייה מוסדית סמויה."})

        # --- OBV (זרימת הון) ---
        if obv_vel > 0.02:
            out.append({"tone": "pos", "label": "זרימת הון (OBV)", "value": f"{obv_vel:+.2f}",
                        "text": "ה-OBV עולה — הון נטו זורם פנימה ב-10 הימים האחרונים, אישור לכניסת כסף."})
        elif obv_vel < -0.02:
            out.append({"tone": "neg", "label": "זרימת הון (OBV)", "value": f"{obv_vel:+.2f}",
                        "text": "ה-OBV יורד — הון נטו זורם החוצה. דגל אזהרה גם אם המחיר מחזיק."})
        else:
            out.append({"tone": "neu", "label": "זרימת הון (OBV)", "value": f"{obv_vel:+.2f}",
                        "text": "זרימת הון שטוחה — אין אישור OBV חזק לכיוון."})

        # --- ניעור נזילות / שבירת מבנה ---
        if liq_sweep >= 1:
            out.append({"tone": "pos", "label": "ניעור נזילות", "value": "זוהה",
                        "text": "המחיר חדר אל מתחת לשפל וחזר מעליו — קצירת נזילות קלאסית (Spring) לפני מהלך."})
        if struct_break > 0:
            out.append({"tone": "pos", "label": "שבירת מבנה", "value": "כלפי מעלה",
                        "text": "סגירה מעל שיא 20 הימים — Sign of Strength מבני."})
        elif struct_break < 0:
            out.append({"tone": "neg", "label": "שבירת מבנה", "value": "כלפי מטה",
                        "text": "סגירה מתחת לשפל 20 הימים — שבירה שלילית של המבנה."})

        # --- Effort vs Result ---
        if effort > 2.5 and c < o:
            out.append({"tone": "neg", "label": "מאמץ מול תוצאה", "value": f"{effort:.1f}",
                        "text": "נפח גבוה ללא התקדמות מחיר (אף ירידה) — מוכר עקשן מכביד מלמעלה (Supply Overhang)."})

        # --- עוצמה יחסית מול השוק ---
        if rs > 0.02:
            out.append({"tone": "pos", "label": "עוצמה יחסית (RS)", "value": f"{rs:+.1%}",
                        "text": "חזקה מ-S&P 500 ב-20 יום — מובילת שוק, מוסדיים מעדיפים אותה."})
        elif rs < -0.02:
            out.append({"tone": "neg", "label": "עוצמה יחסית (RS)", "value": f"{rs:+.1%}",
                        "text": "חלשה מהשוק ב-20 יום — בתיקון שוק מניות כאלה נופלות ראשונות."})

        # --- בלימת מחזורים (Stopping Volume) ---
        if stopping >= 1:
            out.append({"tone": "pos", "label": "בלימת מחזורים", "value": "זוהה",
                        "text": "נר ירידה בנפח חריג שנבלם בחצי העליון — בלימת נפילה (Phase A)."})

    except Exception:
        pass
    return out


def assess_data_freshness(df: pd.DataFrame, fund_data: dict = None) -> dict:
    """
    בודק טריות נתוני מחיר (מודע לסופ"ש) + איכות נתונים פונדמנטליים.
    מחזיר dict עם סטטוס מחיר/פונדמנטלי, גיל בימי מסחר, ושדות חסרים.
    """
    res = {
        "price_status": "unknown", "price_label": "—", "price_last": "—",
        "missing_sessions": 0, "fund_status": "ok", "fund_label": "",
        "missing_fields": [], "earnings_flag": "",
    }
    try:
        if df is not None and not df.empty:
            last_ts = pd.to_datetime(df.index[-1])
            last_date = last_ts.date()
            today = datetime.now().date()
            res["price_last"] = last_ts.strftime("%d.%m.%Y")
            try:
                bdays = int(np.busday_count(last_date, today))
                is_bday_last = bool(np.is_busday(last_date))
                missing = bdays - (1 if is_bday_last else 0)
            except Exception:
                missing = (today - last_date).days
            missing = max(0, missing)
            res["missing_sessions"] = missing
            age_cal = (today - last_date).days
            if missing <= 0:
                res["price_status"] = "fresh"
                res["price_label"] = "נתוני מחיר עדכניים"
            elif missing == 1 and age_cal <= 4:
                res["price_status"] = "warn"
                res["price_label"] = "ייתכן שטרם נכלל יום המסחר האחרון"
            else:
                res["price_status"] = "stale"
                res["price_label"] = f"⚠️ נתוני מחיר מיושנים ({missing} ימי מסחר חסרים)"
        else:
            res["price_status"] = "stale"
            res["price_label"] = "⚠️ אין נתוני מחיר"
    except Exception:
        pass

    # --- איכות פונדמנטלית ---
    try:
        if fund_data:
            key_fields = {
                "מכפיל רווח": fund_data.get("pe_forward") if fund_data.get("pe_forward") != "N/A" else fund_data.get("pe_trailing"),
                "FCF": fund_data.get("fcf_yield"),
                "צמיחה": fund_data.get("rev_growth"),
                "שולי תפעול": fund_data.get("op_margin"),
            }
            missing = [k for k, val in key_fields.items() if val in (None, "N/A")]
            res["missing_fields"] = missing
            if len(missing) >= 3:
                res["fund_status"] = "stale"
                res["fund_label"] = f"⚠️ נתונים פונדמנטליים חסרים ({', '.join(missing)})"
            elif missing:
                res["fund_status"] = "warn"
                res["fund_label"] = f"חלק מהנתונים הפונדמנטליים חסרים ({', '.join(missing)})"

            ne = fund_data.get("next_earnings", "")
            if ne and ne not in ("לא ידוע", "N/A"):
                try:
                    ne_date = datetime.strptime(ne, "%Y-%m-%d").date()
                    delta = (ne_date - datetime.now().date()).days
                    if delta < 0:
                        res["earnings_flag"] = "דוח רווחים אמור היה לצאת — ייתכן שהנתונים מקדימים את הדוח האחרון"
                    elif delta <= 7:
                        res["earnings_flag"] = f"דוח רווחים בעוד {delta} ימים — סיכון אירוע גבוה, הימנע מכניסה רגע לפני"
                except Exception:
                    pass
    except Exception:
        pass
    return res


@st.cache_data(ttl=86400, max_entries=256, show_spinner=False)
def get_latest_report_info(ticker: str) -> dict:
    """מחזיר את הרבעון האחרון שדווח (תאריך + פיגור) מתוך הדוחות הרבעוניים של yfinance."""
    try:
        tkr = yf.Ticker(ticker)
        qf = getattr(tkr, "quarterly_financials", None)
        if qf is None or getattr(qf, "empty", True):
            qf = getattr(tkr, "quarterly_income_stmt", None)
        if qf is None or getattr(qf, "empty", True):
            return {}
        cols = list(qf.columns)
        if not cols:
            return {}
        latest = pd.to_datetime(max(cols))
        q = (latest.month - 1) // 3 + 1
        lag = (datetime.now().date() - latest.date()).days
        return {"quarter_label": f"Q{q} {latest.year}", "date": latest.strftime("%d.%m.%Y"), "lag_days": lag}
    except Exception:
        return {}


def interpret_cis(cis: float, current_phase: str = "") -> dict:
    """מפענח את משמעות ציון ה-CIS למשתמש ('מה אומר 78') — band, label, meaning, color."""
    try:
        cis = float(cis)
    except Exception:
        cis = 0.0
    if cis >= 75:
        band, color = "שכנוע גבוה (High Conviction)", "#16a34a"
        meaning = "המערכת מזהה כניסת כסף מוסדי חזקה ועקבית. זהו האזור שבו השילוב הטכני הכי בשל לפעולה."
    elif cis >= 65:
        band, color = "איסוף פעיל", "#22c55e"
        meaning = "יש טביעת אצבע ברורה של כסף חכם שנכנס. סביבת כניסה טובה, בכפוף לתזמון הפאזה."
    elif cis >= 55:
        band, color = "התבססות / בנייה", "#eab308"
        meaning = "ניצנים של עניין מוסדי, אך עוד לא תמונה חד-משמעית. כדאי לעקוב ולחכות לאישור."
    elif cis >= 40:
        band, color = "ניטרלי / המתנה", "#f59e0b"
        meaning = "אין עדיפות ברורה לקונים או מוכרים. המערכת לא רואה כאן יתרון מובהק כרגע."
    else:
        band, color = "חולשה / להימנע", "#ef4444"
        meaning = "אין עניין מוסדי, או שיש יציאת הון. ציון נמוך = להתרחק מלונג עד לשינוי."

    note = ""
    fam = _phase_family(current_phase)
    if "סיכון הפצה" in current_phase or "Distribution Risk" in current_phase:
        note = ("הציון משקף את העבר (הצבירה שהניעה את העלייה), אך כעת זוהה תיקון/הפצה בנפח גבוה. "
                "אל תתבסס על הציון לבדו — המתן לאישור פאזה לפני כניסה.")
    elif "אין פאזה מאושרת" in current_phase or "ממתינים לאישור" in current_phase:
        note = ("אין פאזה טכנית מאושרת כרגע — הציון מודד עוצמת כסף, לא תזמון. "
                "המתן לאישור כניסה לפאזה לפני פעולה.")
    elif cis >= 65 and fam == "bearish":
        note = "שים לב: הציון גבוה אך הפאזה הטכנית דובית — ייתכן איסוף מוקדם מדי. דרוש אישור פאזה."
    return {"band": band, "color": color, "meaning": meaning, "note": note, "score": round(cis, 1)}


# משקלים מתוך FactorEngine.composite_cis (משוקפים נאמנה לצורך הסבר; לא משנים את המנוע)
_CIS_WEIGHTS = {
    "f14_inst_intent": (6, "כוונה מוסדית", "מדד מורכב לנוכחות מוסדית (ספיגה+OBV+ניעור)"),
    "f20_liquidity_sweep": (5, "ניעור נזילות", "חדירה מתחת לשפל וחזרה מעליו (Spring)"),
    "f04_absorption": (4, "ספיגת היצע", "מאמץ מכירה שנספג בלי שבירת מחיר"),
    "f07_obv_velocity": (4, "מהירות OBV", "קצב זרימת הון נטו פנימה/החוצה"),
    "f_effort_vs_result": (4, "מאמץ מול תוצאה", "האם הנפח מתורגם לתנועת מחיר"),
    "f_stopping_volume": (4, "בלימת מחזורים", "בלימת נפילה בנפח חריג (Phase A)"),
    "f_rs_spy": (4, "עוצמה יחסית", "ביצוע מול S&P 500 ב-20 יום"),
    "f26_accept_reject": (3, "קבלה/דחייה", "סגירות מעל/מתחת אמצע הנר בנפח"),
    "f35_struct_break": (3, "שבירת מבנה", "סגירה מעל שיא / מתחת שפל 20 יום"),
    "f_reaccumulation": (3, "איסוף חוזר", "פולבק רגוע מעל ממוצע 50 בנפח נמוך"),
}


def build_cis_factor_breakdown(factors: pd.DataFrame) -> list:
    """
    'למה קיבלתי את הציון' — מפרק את ה-CIS לפקטורים לפי המשקלים של המנוע.
    מחזיר רשימת dict: {label, value, weight, dir(+/-/0), text}, ממוינת לפי משקל.
    """
    out = []
    if factors is None:
        return out
    for col, (w, label, desc) in _CIS_WEIGHTS.items():
        try:
            if col not in factors.columns:
                continue
            raw = factors[col].iloc[-1]
            val = float(raw) if pd.notna(raw) else 0.0
        except Exception:
            continue
        # כיוון התרומה: ערך חיובי תורם לציון, שלילי גורע (המנוע מנרמל סביב 50)
        if val > 0.05:
            direction = "+"
        elif val < -0.05:
            direction = "-"
        else:
            direction = "0"
        out.append({"label": label, "value": round(val, 2), "weight": w, "dir": direction, "text": desc})
    out.sort(key=lambda x: x["weight"], reverse=True)
    return out


def build_swing_trade_plan(rec_data: dict) -> dict:
    """
    בונה תוכנית מסחר Swing ישימה מהשדות ש-trading_scout כבר מחזיר
    (entry_price/stop_loss_price/tp1_price/tp2_price/current_phase).
    משחזר ATR מתוך (כניסה-סטופ)/2 ובונה: כניסה מדורגת, סטופ, 3 יעדים עם פעולות
    שחרור חלקי, R:R, טווח זמן, ותרחישי Shakeout/Breakout תלויי-פאזה.
    מחזיר {} אם המצב אינו מתאים ללונג.
    """
    try:
        rec = rec_data.get("recommendation", "")
        if rec in ("SELL", "STRONG SELL", "ERROR"):
            return {}
        entry = float(rec_data.get("entry_price", 0) or 0)
        stop = float(rec_data.get("stop_loss_price", 0) or 0)
        if entry <= 0 or stop <= 0 or stop >= entry:
            return {}
        atr = max(1e-6, (entry - stop) / 2.0)  # שוחזר: הסטופ במקור = כניסה - 2*ATR
        phase = rec_data.get("current_phase", "")
        fam = _phase_family(phase)

        entry_pullback = round(entry - atr * 0.6, 2)
        tp1 = float(rec_data.get("tp1_price", round(entry + atr * 3.5, 2)) or round(entry + atr * 3.5, 2))
        tp2 = float(rec_data.get("tp2_price", round(entry + atr * 7.0, 2)) or round(entry + atr * 7.0, 2))
        tp3 = round(entry + atr * 10.5, 2)

        def pct(p):
            return round((p - entry) / entry * 100, 1)

        risk = entry - stop
        rr1 = round((tp1 - entry) / risk, 1) if risk else 0
        rr2 = round((tp2 - entry) / risk, 1) if risk else 0

        # טווח זמן Swing לפי פאזה
        if fam == "bullish_adv":
            timeframe = "2–6 שבועות (מהלך כבר התחיל)"
        elif "Phase C" in phase or "Spring" in phase:
            timeframe = "3–8 שבועות (מ-Spring ועד SOS)"
        else:
            timeframe = "4–10 שבועות (התבססות → פריצה)"

        # תרחיש Shakeout
        if "Phase E" in phase or "Markup" in phase:
            shakeout = (f"ירידה חדה אל אזור <b>${entry_pullback}</b> בתוך מגמה היא לרוב בדיקת תמיכה בריאה. "
                        f"כל עוד הסגירה היומית מעל הסטופ <b>${round(stop,2)}</b> — אין הפרת תזה; שקול תוספת בפולבק.")
        else:
            shakeout = (f"ניעור (Spring) מתחת ל-<b>${round(stop,2)}</b> בנפח גבוה שחוזר מעל הכניסה באותו יום = "
                        f"לרוב אות חיובי, לא יציאה. הפרת תזה אמיתית = <u>סגירה יומית</u> מתחת ל-<b>${round(stop,2)}</b>. "
                        f"כניסה חוזרת = החזרה מעל <b>${round(entry,2)}</b> בנפח.")
        # תרחיש Breakout
        breakout = (f"פריצת התנגדות בנפח מתרחב מאשרת את המהלך. פעולה: החזק/הוסף, והעלה סטופ אל מתחת לאזור הפריצה. "
                    f"יעד ראשון <b>${round(tp1,2)}</b> (+{pct(tp1)}%), ולאחריו <b>${round(tp2,2)}</b> (+{pct(tp2)}%).")

        return {
            "valid": True,
            "phase": phase,
            "entry": round(entry, 2),
            "entry_pullback": entry_pullback,
            "stop": round(stop, 2),
            "stop_pct": pct(stop),
            "tp1": round(tp1, 2), "tp1_pct": pct(tp1), "tp1_action": "שחרר ~⅓, העלה סטופ לנקודת הכניסה (עסקה ללא סיכון).",
            "tp2": round(tp2, 2), "tp2_pct": pct(tp2), "tp2_action": "שחרר ~⅓ נוסף, עבור ל-Trailing Stop.",
            "tp3": round(tp3, 2), "tp3_pct": pct(tp3), "tp3_action": "יתרה רצה עם סטופ נגרר עד היפוך/תשישות.",
            "rr1": rr1, "rr2": rr2,
            "timeframe": timeframe,
            "shakeout": shakeout,
            "breakout": breakout,
        }
    except Exception:
        return {}


@st.cache_data(ttl=1800, show_spinner=False)
def compute_macro_radar() -> dict:
    """
    Macro Technical Radar קל (שכבה תומכת): מצב טכני של SPY / QQQ / IWM מול ממוצעים +
    מומנטום 20 יום, ו-VIX (מצורף לכל df ע"י get_data). מסיק משטר Risk-On/Neutral/Risk-Off.
    """
    out = {"cells": [], "regime": "—", "color": "#94a3b8", "note": "", "vix": None}
    try:
        score = 0
        n = 0
        names = {"SPY": "S&P 500", "QQQ": "נאסד\"ק", "IWM": "Small Caps"}
        vix_val = None
        for sym, he in names.items():
            df = get_cached_data(sym, period="1y")
            if df is None or df.empty or len(df) < 60:
                continue
            c = float(df["Close"].iloc[-1])
            s50 = _sma(df["Close"], 50)
            s200 = _sma(df["Close"], 200)
            if pd.isna(s200):
                s200 = s50
            mom = float(df["Close"].pct_change(20).iloc[-1]) * 100 if len(df) >= 21 else 0.0
            if vix_val is None and "vix_close" in df.columns:
                try:
                    vv = df["vix_close"].iloc[-1]
                    vix_val = float(vv) if pd.notna(vv) else None
                except Exception:
                    vix_val = None
            cell_score = 0
            if c > s50:
                cell_score += 1
            if c > s200:
                cell_score += 1
            if mom > 0:
                cell_score += 1
            n += 1
            score += cell_score
            if cell_score >= 2 and c > s50:
                state, scolor = "חיובי", "#22c55e"
            elif cell_score <= 1:
                state, scolor = "חלש", "#ef4444"
            else:
                state, scolor = "מעורב", "#eab308"
            out["cells"].append({"name": he, "state": state, "mom": round(mom, 1), "color": scolor})

        if vix_val is not None:
            out["vix"] = round(vix_val, 1)

        if n == 0:
            return out
        ratio = score / (n * 3.0)
        vix_pen = 0.0
        if vix_val is not None:
            if vix_val >= 25:
                vix_pen = -0.15
            elif vix_val <= 15:
                vix_pen = 0.05
        ratio = max(0.0, min(1.0, ratio + vix_pen))
        if ratio >= 0.66:
            out["regime"], out["color"] = "Risk-On", "#22c55e"
            out["note"] = "השוק הרחב במגמה חיובית — רוח גבית למניות חזקות ולפריצות וויקוף."
        elif ratio <= 0.4:
            out["regime"], out["color"] = "Risk-Off", "#ef4444"
            out["note"] = "השוק הרחב חלש — סלקטיביות גבוהה; פריצות נוטות להיכשל בסביבה כזו."
        else:
            out["regime"], out["color"] = "Neutral", "#eab308"
            out["note"] = "השוק הרחב מעורב — עדיף להתמקד במובילי סקטור עם RS חיובי בלבד."
        if vix_val is not None:
            out["note"] += f" (VIX {out['vix']})"
    except Exception:
        pass
    return out


# ============================================================
# V20.2 — רכיבי תצוגה (Render helpers)
# ============================================================

def _phase_hot_badge(phase: str, cis: float = 0.0) -> str:
    """מחזיר צ'יפ HTML להדגשת מניה בפאזת C / Spring / Shakeout / איסוף חזק / סיכון הפצה (אחרת '')."""
    p = phase or ""
    if "Distribution Risk" in p or "סיכון הפצה" in p:
        return "<span class='phase-hot-badge hot-shake'>⚠️ סיכון הפצה</span>"
    if "Spring" in p or "Phase C" in p:
        if "Strong" in p:
            return "<span class='phase-hot-badge hot-spring'>🎯 Spring חזק</span>"
        return "<span class='phase-hot-badge hot-spring'>🎯 Spring / Phase C</span>"
    if "Failed Sweep" in p or "Shakeout" in p:
        return "<span class='phase-hot-badge hot-shake'>⚠️ Shakeout</span>"
    try:
        if cis and float(cis) >= 75 and _phase_family(p) in ("bullish_adv", "bullish_early"):
            return "<span class='phase-hot-badge hot-accum'>🔥 איסוף חזק</span>"
    except Exception:
        pass
    return ""


@st.cache_data(ttl=1800, show_spinner=False)
def pick_phase_caution(ticker: str, engine_phase: str):
    """
    לכרטיסי סריקה (קרוסלה / Swipe / סקטור): מסלול הסריקה מציג את תווית המנוע הגולמית
    ואינו עובר דרך refine_wyckoff_phase. כאן מיישמים את אותה שכבת-אימות נקודתית:
    אם המנוע נתן תווית 'המשך עלייה' (Re-accumulation/Phase D/E) אך מדובר בתיקון/הפצה
    בנפח גבוה (כמו WULF) — מחליפים לתווית 'סיכון הפצה'. שכבת אפליקציה בלבד (המנוע לא נוגע).
    מחזיר (display_phase, is_risk, dist_pct).
    """
    ep = engine_phase or ""
    is_cont = (
        any(k in ep for k in ("Re-accumulation", "Phase E", "Markup", "Phase D", "LPS", "SOS", "Breakout"))
        and "Spring" not in ep and "Phase C" not in ep
    )
    if not is_cont or not ticker:
        return ep, False, 0.0
    try:
        df = get_cached_data(ticker, period="1y")
        risk = detect_distribution_risk(df)
        if risk.get("risk"):
            return "⚠️ סיכון הפצה — תיקון בנפח גבוה (Distribution Risk)", True, float(risk.get("dist_pct", 0.0))
    except Exception:
        pass
    return ep, False, 0.0


# ============================================================
# V22.0 — Value & Quality layer (Tier 2, סגנון ערך)
# ממלא את החיוג השלישי בעומק אמיתי: ציון איכות (8 עקרונות → A-F) ו-Reverse-DCF
# (צמיחה גלומה במחיר מול צמיחה בפועל). שכבת אפליקציה בלבד; מבוסס על הנתונים
# שכבר נשאבים (fd['_raw']) — אפס קריאות רשת נוספות. לא נוגע בנקודות הכניסה/סטופ/
# יעדים (הן נשארות מבניות); משפיע רק על שורת השכנוע (להחזיק Runner / לקחת רווח).
# ============================================================

def compute_quality_score(fd: dict) -> dict:
    """
    ציון איכות עסקי בסגנון ערך. מפרק לפילרים: FCF (יצירת מזומן), חפיר/כוח-תמחור
    (מרווח מול סקטור), תשואה על הון (ROE), מאזן (מינוף), צמיחה. מחזיר
    {score(0-100 פנימי), grade(A-F לתצוגה), drivers[], summary}.
    """
    res = {"score": None, "grade": "—", "drivers": [],
           "summary": "אין די נתונים פונדמנטליים לדירוג איכות."}
    try:
        raw = fd.get("_raw") or {}
        if not raw:
            return res
        fcf = float(raw.get("fcf_yield") or 0.0)
        om = float(raw.get("op_margin") or 0.0)
        bench_om = float(raw.get("bench_om") or 10.0)
        roe = float(raw.get("roe_pct") or 0.0)
        ndte_v = raw.get("net_debt_ebitda")
        ndte = float(ndte_v) if ndte_v is not None else 0.0
        rg = float(raw.get("rev_growth") or 0.0)
        drivers = []

        # 1) יצירת FCF (30) — ליבת ניתוח הערך
        if fcf >= 6:   s_fcf, t = 30, f"FCF {fcf:.1f}% — מכונת מזומנים"
        elif fcf >= 4: s_fcf, t = 23, f"FCF {fcf:.1f}% — בריא"
        elif fcf >= 2: s_fcf, t = 14, f"FCF {fcf:.1f}% — בינוני"
        elif fcf > 0:  s_fcf, t = 7,  f"FCF {fcf:.1f}% — חלש"
        else:          s_fcf, t = 0,  "FCF שלילי/אפסי — שורף מזומן"
        drivers.append(t)
        # 2) חפיר / כוח תמחור (25) — מרווח תפעולי מול הסקטור
        edge = om - bench_om
        if om <= 0:        s_moat, t = 0,  f"שולי תפעול שליליים ({om:.0f}%)"
        elif edge >= 15:   s_moat, t = 25, f"מרווח {om:.0f}% מעל סקטור {bench_om:.0f}% — חפיר חזק"
        elif edge >= 5:    s_moat, t = 19, f"מרווח {om:.0f}% מעל סקטור {bench_om:.0f}% — כוח תמחור"
        elif edge >= -3:   s_moat, t = 12, f"מרווח {om:.0f}% ~ סקטור {bench_om:.0f}%"
        else:              s_moat, t = 5,  f"מרווח {om:.0f}% מתחת סקטור {bench_om:.0f}% — חלש"
        drivers.append(t)
        # 3) תשואה על הון (20)
        if roe >= 20:   s_roc, t = 20, f"ROE {roe:.0f}% — גבוהה"
        elif roe >= 15: s_roc, t = 15, f"ROE {roe:.0f}% — טובה"
        elif roe >= 8:  s_roc, t = 10, f"ROE {roe:.0f}% — בינונית"
        elif roe > 0:   s_roc, t = 5,  f"ROE {roe:.0f}% — נמוכה"
        else:           s_roc, t = 0,  f"ROE שלילי ({roe:.0f}%)"
        drivers.append(t)
        # 4) חוזק מאזן (15) — מינוף חוב נטו/EBITDA
        if ndte <= 0:    s_bs, t = 15, "מאזן איתן — ללא חוב נטו / מזומן עודף"
        elif ndte < 1:   s_bs, t = 15, f"מינוף {ndte:.1f}x — איתן"
        elif ndte < 2:   s_bs, t = 11, f"מינוף {ndte:.1f}x — סביר"
        elif ndte < 3:   s_bs, t = 7,  f"מינוף {ndte:.1f}x — בינוני"
        elif ndte < 4:   s_bs, t = 3,  f"מינוף {ndte:.1f}x — גבוה"
        else:            s_bs, t = 0,  f"מינוף {ndte:.1f}x — מסוכן"
        drivers.append(t)
        # 5) צמיחה (10)
        if rg >= 15:   s_g, t = 10, f"צמיחה {rg:.0f}% — מהירה"
        elif rg >= 8:  s_g, t = 7,  f"צמיחה {rg:.0f}% — יציבה"
        elif rg >= 3:  s_g, t = 5,  f"צמיחה {rg:.0f}% — מתונה"
        elif rg >= 0:  s_g, t = 2,  f"צמיחה {rg:.0f}% — איטית"
        else:          s_g, t = 0,  f"הכנסות מתכווצות ({rg:.0f}%)"
        drivers.append(t)

        score = s_fcf + s_moat + s_roc + s_bs + s_g
        grade = ("A" if score >= 80 else "B" if score >= 68 else
                 "C" if score >= 55 else "D" if score >= 40 else "F")
        if grade in ("A", "B"):
            summ = "עסק איכותי — מכונת מזומנים עם יתרון תחרותי ומאזן בריא."
        elif grade == "C":
            summ = "עסק סביר — איכות בינונית, לא בולט לטוב או לרע."
        else:
            summ = "עסק באיכות נמוכה — חולשה בתזרים/רווחיות/מאזן. סיכון מוגבר."
        res = {"score": score, "grade": grade, "drivers": drivers, "summary": summ}
    except Exception:
        pass
    return res


def compute_implied_growth(fd: dict) -> dict:
    """
    Reverse-DCF פשוט ושקוף: מנרמלים מחיר ל-1, FCF_0 = תשואת ה-FCF, ומחפשים את
    שיעור צמיחת ה-FCF שמצדיק את המחיר (r=9%, צמיחה סופית 2.5%, 10 שנים). משווים
    לצמיחה בפועל ⇒ זול/הוגן/יקר. אם אין FCF חיובי — לא ניתן לתמחר כך (אות ספקולטיבי).
    """
    res = {"valid": False,
           "summary": "אין FCF חיובי — לא ניתן לתמחר לפי תזרים. זהו עסק תלוי-צמיחה/ספקולטיבי."}
    try:
        raw = fd.get("_raw") or {}
        fcf = float(raw.get("fcf_yield") or 0.0) / 100.0
        rg = float(raw.get("rev_growth") or 0.0)
        ni = float(raw.get("ni_growth") or 0.0)
        if fcf <= 0:
            return res
        actual = max(0.0, min(40.0, (rg * 0.6 + ni * 0.4) if ni else rg))
        r, g_term, yrs = 0.09, 0.025, 10

        def pv(gp):
            g = gp / 100.0
            tot, f = 0.0, fcf
            for t in range(1, yrs + 1):
                f *= (1 + g)
                tot += f / ((1 + r) ** t)
            term = (f * (1 + g_term) / (r - g_term)) / ((1 + r) ** yrs)
            return tot + term

        lo, hi = -5.0, 60.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if pv(mid) < 1:
                lo = mid
            else:
                hi = mid
        implied = round((lo + hi) / 2, 1)
        gap = round(actual - implied, 1)
        if implied <= actual * 0.8:
            verdict = "זול"
        elif implied >= actual * 1.2 + 2:
            verdict = "יקר"
        else:
            verdict = "הוגן"
        vtxt = {"זול": "מתומחר בחסר (זול)", "יקר": "מתומחר ביוקר", "הוגן": "מתומחר בהוגן"}[verdict]
        summ = (f"המחיר מגלם צמיחת FCF של ~{implied:.0f}% לשנה; העסק צומח בפועל ~{actual:.0f}% "
                f"⇒ {vtxt}.")
        res = {"valid": True, "implied": implied, "actual": round(actual, 1),
               "verdict": verdict, "gap": gap, "summary": summ}
    except Exception:
        pass
    return res


# ============================================================
# V23.0 — Multi-year Durability (Tier 3.0, רכיב 1)
# מוסיף את ממד הזמן לאיכות: עקביות FCF (חיובי כל שנה?) ומגמת מרווחים (חפיר
# מתחזק/נשחק) על פני עד 5 שנים. נכנס כ-MODIFIER פנימי לציון האיכות (Tier 2);
# הציון נשאר A-F, רק מדויק יותר. שכבת אפליקציה בלבד, cache חזק, עמיד-כשל:
# אם אין די היסטוריה → modifier=0 + "אין די היסטוריה" (בלי קריסה).
# הלוגיקה מופרדת מהשליפה (פונקציה טהורה הניתנת לבדיקה).
# ============================================================

def _statement_row(frame, *names):
    """מחזיר שורה שלמה (כל השנים, מהחדש לישן) של השם הראשון שנמצא, או None."""
    try:
        if frame is None or getattr(frame, "empty", True):
            return None
        for nm in names:
            if nm in frame.index:
                vals = []
                for x in frame.loc[nm].values:
                    if x is None:
                        continue
                    try:
                        fx = float(x)
                    except Exception:
                        continue
                    if fx == fx:  # not NaN
                        vals.append(fx)
                if vals:
                    return vals
    except Exception:
        pass
    return None


def _durability_from_statements(cf, fin) -> dict:
    """
    לוגיקה טהורה (נבדקת בקלות): מקבלת cashflow + financials, מחזירה
    {valid, modifier(נק' ציון, -20..+10), summary, fcf_pos, fcf_total, margin_trend, detail[]}.
    """
    res = {"valid": False, "modifier": 0,
           "summary": "אין די היסטוריה לכיול עקביות (פחות מ-3 שנות נתונים).",
           "fcf_pos": 0, "fcf_total": 0, "margin_trend": "—", "detail": []}
    try:
        ocf = _statement_row(cf, "Operating Cash Flow",
                             "Cash Flow From Continuing Operating Activities",
                             "Total Cash From Operating Activities")
        cpx = _statement_row(cf, "Capital Expenditure", "Capital Expenditures")
        rev = _statement_row(fin, "Total Revenue", "Operating Revenue")
        opi = _statement_row(fin, "Operating Income", "Total Operating Income As Reported")

        if not ocf or len(ocf) < 3:
            return res

        # --- עקביות FCF (FCF = תזרים תפעולי + capex; ב-yfinance capex שלילי) ---
        n = min(len(ocf), 5)
        fcf_years = []
        for i in range(n):
            c = cpx[i] if (cpx and i < len(cpx)) else 0.0
            fcf_years.append(ocf[i] + c)
        fcf_total = len(fcf_years)
        fcf_pos = sum(1 for f in fcf_years if f > 0)

        # --- מגמת מרווחים (op_income/revenue): השוואת חדש מול ישן ---
        margin_trend = "—"
        if rev and opi and len(rev) >= 3 and len(opi) >= 3:
            k = min(len(rev), len(opi), 5)
            margins = [opi[i] / rev[i] for i in range(k) if rev[i]]
            if len(margins) >= 3:
                recent = sum(margins[:2]) / len(margins[:2])     # ממוצע 2 העדכניות
                old = sum(margins[-2:]) / len(margins[-2:])       # ממוצע 2 הישנות
                diff = recent - old
                margin_trend = ("מתחזק" if diff > 0.02 else
                                "נשחק" if diff < -0.02 else "יציב")

        # --- חישוב ה-modifier ---
        modifier = 0
        detail = []
        ratio = fcf_pos / fcf_total if fcf_total else 0.0
        if ratio >= 1.0:
            modifier += 6
            detail.append(f"FCF חיובי ב-{fcf_pos}/{fcf_total} השנים — עקבי")
        elif ratio >= 0.6:
            detail.append(f"FCF חיובי ב-{fcf_pos}/{fcf_total} השנים — תנודתי חלקית")
        else:
            modifier -= 12
            detail.append(f"FCF חיובי רק ב-{fcf_pos}/{fcf_total} השנים — תנודתי")

        if margin_trend == "מתחזק":
            modifier += 4
            detail.append("מרווחים מתחזקים לאורך זמן — חפיר מתחזק")
        elif margin_trend == "נשחק":
            modifier -= 8
            detail.append("מרווחים נשחקים לאורך זמן — חפיר נחלש")
        elif margin_trend == "יציב":
            detail.append("מרווחים יציבים לאורך זמן")

        modifier = max(-20, min(10, modifier))
        if modifier > 0:
            summ = f"היסטוריה עקבית מחזקת את האיכות (FCF {fcf_pos}/{fcf_total}, מרווחים {margin_trend})."
        elif modifier < 0:
            summ = f"היסטוריה תנודתית מחלישה את האיכות (FCF {fcf_pos}/{fcf_total}, מרווחים {margin_trend})."
        else:
            summ = f"היסטוריה יציבה (FCF {fcf_pos}/{fcf_total}, מרווחים {margin_trend})."

        res = {"valid": True, "modifier": modifier, "summary": summ,
               "fcf_pos": fcf_pos, "fcf_total": fcf_total,
               "margin_trend": margin_trend, "detail": detail}
    except Exception:
        pass
    return res


@st.cache_data(ttl=86400, max_entries=256, show_spinner=False)
def compute_durability(ticker: str) -> dict:
    """
    עטיפת שליפה (cache חזק — 24ש', הדוחות משתנים רק רבעונית). מושכת cashflow+
    financials מ-yfinance ומריצה את הלוגיקה הטהורה. עמיד-כשל לחלוטין.
    """
    try:
        tk = yf.Ticker(ticker)
        try:
            cf = tk.cashflow
        except Exception:
            cf = None
        try:
            fin = tk.financials
        except Exception:
            fin = None
        return _durability_from_statements(cf, fin)
    except Exception:
        return {"valid": False, "modifier": 0,
                "summary": "אין די היסטוריה לכיול עקביות.", "fcf_pos": 0,
                "fcf_total": 0, "margin_trend": "—", "detail": []}


def _quality_adjusted(fd: dict, durability: dict) -> dict:
    """
    ציון האיכות הסופי = snapshot (Tier 2) + modifier רב-שנתי (Tier 3), ממופה
    מחדש ל-A-F. זהו הציון היחיד שמוצג בכל המסכים (מקור אמת אחד לאיכות).
    """
    snap = compute_quality_score(fd)
    if snap.get("score") is None:
        snap = dict(snap)
        snap["modifier"] = 0
        snap["score_adj"] = None
        return snap
    mod = int((durability or {}).get("modifier", 0))
    final = max(0, min(100, snap["score"] + mod))
    grade = ("A" if final >= 80 else "B" if final >= 68 else
             "C" if final >= 55 else "D" if final >= 40 else "F")
    out = dict(snap)
    out["score_adj"] = final
    out["grade"] = grade           # ← הדרגה המותאמת היא הדרגה הקובעת
    out["modifier"] = mod
    return out


def _grade_color(grade: str) -> str:
    return {"A": "#16a34a", "B": "#22c55e", "C": "#eab308",
            "D": "#f59e0b", "F": "#ef4444"}.get(grade, "#94a3b8")


def _value_quality_conclusion(valuation: str, grade: str):
    """לוגיקת המטריצה כמסקנה מילולית + צבע (למסכים הראשיים)."""
    v = (valuation or "").strip()
    cheap, exp = ("זול" in v), ("יקר" in v)
    good, bad = (grade in ("A", "B")), (grade in ("D", "F"))
    if cheap and good: return "עסק איכותי במחיר אטרקטיבי — שילוב אידיאלי.", "#16a34a"
    if cheap and bad:  return "זול אך באיכות נמוכה — היזהר ממלכודת ערך.", "#f59e0b"
    if exp and good:   return "עסק מצוין אך יקר — דרושה סבלנות או מחיר טוב יותר.", "#eab308"
    if exp and bad:    return "יקר וגם איכות נמוכה — ספקולטיבי, לא להחזקה.", "#ef4444"
    if good:           return "עסק איכותי במחיר הוגן — בסיס טוב להחזקה.", "#22c55e"
    if bad:            return "איכות נמוכה — גם במחיר הוגן, סיכון מוגבר.", "#f59e0b"
    return "תמחור ואיכות סבירים.", "#94a3b8"


def _conviction_note(grade: str, confidence: int) -> str:
    """שורת שכנוע: להחזיק Runner מעבר ליעד או לקחת רווח — נגזר מהאיכות (לא מזיז סטופ/יעד)."""
    good, bad = (grade in ("A", "B")), (grade in ("D", "F"))
    if good and confidence >= 50:
        return ("האיכות הגבוהה תומכת בהחזקת ה-Runner מעבר ליעד הראשון — אפשר לתת לרווח "
                "לרוץ עם סטופ נגרר (העסק שווה החזקה ארוכה).")
    if bad:
        return ("האיכות נמוכה — זו עסקה טקטית בלבד. קח רווח ביעדים, אל תחזיק מעבר להם "
                "ואל תתאהב בנייר.")
    return ("איכות בינונית — החזק עד היעדים לפי התוכנית; הארכת Runner רק אם המבנה נשאר חזק.")


def render_value_quality_detail(ticker: str, fd: dict) -> None:
    """תוכן ה-expander 'ניתוח ערך ואיכות': מטריצה + פילרי איכות + עקביות רב-שנתית + Reverse-DCF."""
    dura = compute_durability(ticker)              # V23.0
    qual = _quality_adjusted(fd, dura)             # דרגה מותאמת-עקביות
    ig = compute_implied_growth(fd)
    grade = qual.get("grade", "—")
    snap_score = qual.get("score")
    adj_score = qual.get("score_adj")
    modifier = qual.get("modifier", 0)
    valuation = fd.get("valuation", "—")
    gcol = _grade_color(grade)
    vq_text, vq_col = _value_quality_conclusion(valuation, grade)

    # מטריצה 3x3 (איכות × ערך) עם התא הנוכחי מודגש
    v = (valuation or "").strip()
    col = 0 if "זול" in v else (2 if "יקר" in v else 1)
    qrow = {"A": 0, "B": 0, "C": 1, "D": 2, "F": 2}.get(grade, 1)
    cells = [["#16a34a", "#22c55e", "#eab308"],
             ["#22c55e", "#eab308", "#f59e0b"],
             ["#f59e0b", "#f59e0b", "#ef4444"]]
    col_lbls = ["זול", "הוגן", "יקר"]
    row_lbls = ["איכות גבוהה", "איכות בינונית", "איכות נמוכה"]
    grid = "<div class='vq-matrix'>"
    grid += "<div class='vq-corner'></div>"
    for cl in col_lbls:
        grid += f"<div class='vq-axis'>{cl}</div>"
    for ri in range(3):
        grid += f"<div class='vq-axis vq-axis-row'>{row_lbls[ri]}</div>"
        for ci in range(3):
            active = " vq-cell-active" if (ri == qrow and ci == col) else ""
            grid += f"<div class='vq-cell{active}' style='background:{cells[ri][ci]};'></div>"
    grid += "</div>"

    drivers_html = "".join(f"<li>{d}</li>" for d in qual.get("drivers", []))
    ig_html = ig.get("summary", "")

    # שורת ההתאמה (snapshot → modifier → adjusted)
    if dura.get("valid") and snap_score is not None:
        adj_line = (f"ציון snapshot {snap_score} {('+' if modifier >= 0 else '')}{modifier} "
                    f"(עקביות רב-שנתית) = <b>{adj_score}</b> ⇒ דרגה {grade}")
        dura_html = "<b>עקביות (5 שנים):</b><ul class='story-ul'>" + \
                    "".join(f"<li>{x}</li>" for x in dura.get("detail", [])) + "</ul>"
    else:
        adj_line = f"ציון snapshot {snap_score if snap_score is not None else '—'} ⇒ דרגה {grade}"
        dura_html = f"<b>עקביות (5 שנים):</b> {dura.get('summary', 'אין די היסטוריה לכיול עקביות.')}"

    st.markdown(
        f"<div class='vq-detail'>"
        f"<div class='vq-headline' style='color:{vq_col};'>השילוב: {vq_text}</div>"
        f"<div class='vq-grade-row'>איכות עסקית: <span class='grade-pill' style='background:{gcol};'>{grade}</span>"
        f"<span class='vq-score'>({adj_line})</span> · תמחור: <b>{valuation}</b></div>"
        f"{grid}"
        f"<div class='vq-sub'><b>פילרי האיכות (snapshot, סגנון ערך):</b><ul class='story-ul'>{drivers_html}</ul></div>"
        f"<div class='vq-sub'>{dura_html}</div>"
        f"<div class='vq-sub'><b>תמחור לפי תזרים (Reverse-DCF):</b> {ig_html}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


# ============================================================
# V24.0 — Historical Phase Reliability (Tier 3.1, כיול)
# "היסטורית, כשהמניה הזו הגיעה לשלב הזה — מה קרה ב-20 הימים הבאים?"
# משתמש ב-calculate_phase_followthrough הקיים מהליבה (walk-forward מובנה: לכל
# נקודה בעבר, ההצלחה נמדדת רק על החלון העתידי שלה, והלולאה עוצרת ב-n-horizon —
# כך שהבר הנוכחי והעתיד הלא-ידוע שלו לעולם לא נספרים). אני *לא* מוסיף שום מידע
# עתידי משלי. cache חזק, עמיד-כשל: אין די דגימות → "אין די דגימות היסטוריות".
# משפיע רק כ-modifier *קטן* לביטחון הפאזה (אנטי-הגזמת-ביטחון) — לא משנה state/status.
# ============================================================

# מיפוי המצב המבני → מפתחות הפאזה של המנוע הגולמי (כפי ש-followthrough מתייג)
_STATE_FT_KEYS = {
    "ACC_SPRING":   ["Phase C", "Spring"],
    "ACC_CONFIRM":  ["Phase D"],
    "MARKUP":       ["Phase E"],
    "DIST_WARNING": ["Distribution", "Heavy Supply"],
    "DIST_ACTIVE":  ["Markdown", "Distribution"],
    "MARKDOWN":     ["Markdown"],
    # ACC_BASE (שלב A/B) ו-UNDETERMINED — לא נמדדים ב-followthrough → אין שיעור
}


@st.cache_data(ttl=3600, max_entries=128, show_spinner=False)
def _phase_followthrough_cached(ticker: str) -> dict:
    """
    עטיפת שליפה עם cache חזק: מושך היסטוריה, מחשב את פאזת המנוע לכל בר, ומריץ את
    calculate_phase_followthrough הקיים. מחזיר {phase_str: {total, success, rate}}.
    עמיד-כשל: כל כשל → {}.
    """
    try:
        df = get_cached_data(ticker)
        if df is None or df.empty or len(df) < 80:
            return {}
        engine = FactorEngine(BacktestConfig())
        df = df.copy()
        df["wyckoff_phase"] = engine.get_wyckoff_phase(df)
        return calculate_phase_followthrough(df, horizon=20, threshold_pct=0.04) or {}
    except Exception:
        return {}


def compute_phase_reliability(ticker: str, state: str) -> dict:
    """
    שיעור ההצלחה ההיסטורי של המצב הנוכחי *במניה הזו*. מאגד את כל מפתחות הפאזה
    התואמים למצב, ומחזיר {valid, rate, total, success, band, summary}. פחות מ-4
    דגימות → valid=False ("אין די דגימות היסטוריות").
    """
    res = {"valid": False, "rate": None, "total": 0, "success": 0, "band": "none",
           "summary": "אין די דגימות היסטוריות לשלב זה במניה הזו לכיול."}
    try:
        keys = _STATE_FT_KEYS.get(state, [])
        if not keys:
            return res
        stats = _phase_followthrough_cached(ticker)
        if not stats:
            return res
        total = success = 0
        for ph, s in stats.items():
            if any(k in str(ph) for k in keys):
                total += int(s.get("total", 0))
                success += int(s.get("success", 0))
        if total < 4:
            return res
        rate = round(success / total * 100)
        band = "high" if rate >= 65 else ("mid" if rate >= 45 else "low")
        verb = ("עלתה/פרצה" if state in ("ACC_SPRING", "ACC_CONFIRM") else
                "המשיכה לעלות" if state == "MARKUP" else
                "ירדה" if state in ("DIST_WARNING", "DIST_ACTIVE") else
                "המשיכה לרדת" if state == "MARKDOWN" else "מומשה")
        summary = (f"היסטורית, כשהמניה הגיעה לשלב זה, היא {verb} תוך ~20 יום "
                   f"ב-{rate}% מהמקרים ({total} דגימות).")
        res = {"valid": True, "rate": rate, "total": total, "success": success,
               "band": band, "summary": summary}
    except Exception:
        pass
    return res


def _apply_reliability_to_confidence(wyckoff_state: dict, reliability: dict) -> None:
    """
    מחיל modifier *קטן* של שיעור ההצלחה ההיסטורי על ביטחון הפאזה (in-place).
    אנטי-הגזמת-ביטחון: היסטוריה חלשה מורידה, חזקה מעלה מעט. *לא* משנה state/status
    (כדי לא לגרום לפאזה 'להיעלם' — שמירה על העיקרון של לא-להציף UNDETERMINED).
    """
    try:
        if not reliability.get("valid"):
            return
        rate, total = reliability["rate"], reliability["total"]
        adj = 0
        if total >= 6 and rate >= 65:
            adj = 5
        elif total >= 6 and rate < 40:
            adj = -8
        if adj:
            nc = max(0, min(100, int(wyckoff_state.get("confidence", 0)) + adj))
            wyckoff_state["confidence"] = nc
            wyckoff_state["conf_band"] = ("high" if nc >= 70 else "mid" if nc >= 50
                                          else "low" if nc >= 30 else "none")
            reliability["applied"] = adj
    except Exception:
        pass


def _dial_color(kind: str, val) -> str:
    """צבע למד לפי סוג: cis / confidence."""
    try:
        v = float(val)
    except Exception:
        return "#94a3b8"
    if kind == "cis":
        return "#16a34a" if v >= 65 else ("#eab308" if v >= 45 else "#ef4444")
    if kind == "confidence":
        return "#16a34a" if v >= 70 else ("#eab308" if v >= 50 else ("#f59e0b" if v >= 30 else "#ef4444"))
    return "#94a3b8"


def _structural_roadmap(state: str) -> dict:
    """מפת דרכים קוהרנטית עם ה-state המבני (מקור אמת יחיד): היינו / אנחנו / היעד + פעולה."""
    M = {
        "MARKDOWN":     ("הפצה / פסגה", "מגמת ירידה (Markdown)", "בלימה ובניית בסיס (SC)", "להימנע מלונג; להמתין לבלימה ולבניית בסיס."),
        "ACC_BASE":     ("מגמת ירידה / בלימה", "בניית בסיס (שלב A/B)", "ניעור (Spring, שלב C)", "לעקוב; להמתין לטריגר Spring/SOS לפני כניסה."),
        "ACC_SPRING":   ("בניית בסיס (B)", "ניעור (Spring, שלב C)", "אישור (SOS/LPS, שלב D)", "כניסה על המבחן, סטופ מתחת לשפל הניעור."),
        "ACC_CONFIRM":  ("ניעור (Spring, C)", "אישור איסוף (שלב D)", "פריצה ומגמת עלייה (שלב E)", "חזק/הוסף לקראת הפריצה; אזור LPS לתוספת."),
        "MARKUP":       ("אישור (שלב D)", "מגמת עלייה (שלב E)", "פסגה / הפצה עתידית", "לרכוב עם סטופ נגרר; לשחרר חלקית לתוך חוזק."),
        "DIST_WARNING": ("מגמת עלייה (E)", "אזהרת הפצה", "שבירה (SOW) או חזרה לעלייה", "זהירות; לשקול צמצום לתוך חוזק."),
        "DIST_ACTIVE":  ("אזהרת הפצה", "הפצה / שבירה", "מגמת ירידה (Markdown)", "לצאת מפוזיציות לונג."),
        "UNDETERMINED": ("—", "אין פאזה מאושרת", "היווצרות מבנה ברור", "להמתין; לסרוק שוב ביום המסחר הבא."),
    }
    prev, cur, nxt, act = M.get(state, M["UNDETERMINED"])
    return {"prev": prev, "current": cur, "next": nxt, "action": act}


def render_structural_summary(ticker: str, intel: dict, show_plan: bool = True) -> None:
    """
    V21.0 — התצוגה הראשית של 'תבדוק לי': שורה תחתונה פשוטה קודם, אחריה 3 חיוגים
    נפרדים (טביעת אצבע / ביטחון פאזה / ערך), ואז הסיפור העקבי. הלב של ההנגשה.
    """
    ws = intel.get("wyckoff_state")
    if not ws:
        return
    cis = intel.get("current_cis", 0.0)
    conf = ws.get("confidence", 0)
    pb = ws.get("playbook", {})
    plan = ws.get("plan", {})
    fd = get_fundamental_data(ticker) or {}
    valuation = fd.get("valuation", "—")
    val_color = fd.get("valuation_color", "#94a3b8")
    qual = compute_quality_score(fd)          # V22.0: snapshot איכות
    _dura = compute_durability(ticker)        # V23.0: עקביות רב-שנתית (cache חזק, עמיד-כשל)
    qual = _quality_adjusted(fd, _dura)       # ← ציון מותאם-עקביות (A-F, מקור יחיד)
    grade = qual.get("grade", "—")
    gcol = _grade_color(grade)
    ig = compute_implied_growth(fd)           # V22.0: Reverse-DCF — צמיחה גלומה
    vq_text, vq_col = _value_quality_conclusion(valuation, grade)
    vq_text, vq_col = _horizon_safe_vq_sub(vq_text, vq_col, ws.get("track", "none"), ws.get("state", ""))
    conf_band_he = {"high": "ביטחון גבוה", "mid": "ביטחון בינוני",
                    "low": "ביטחון נמוך", "none": "אין ביטחון"}.get(ws.get("conf_band"), "")

    # ---------- (1) שורה תחתונה — תמיד ראשונה, פשוטה ----------
    st.markdown(
        f"<div class='struct-bottomline'><span class='sbl-tag'>שורה תחתונה</span>{ws.get('bottom_line','')}</div>",
        unsafe_allow_html=True,
    )

    # ---------- (2) שלושה חיוגים נפרדים ----------
    cis_col = _dial_color("cis", cis)
    conf_col = _dial_color("confidence", conf)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            f"<div class='dial'><div class='dial-val' style='color:{cis_col};'>{cis:.0f}</div>"
            f"<div class='dial-label'>טביעת אצבע מוסדית</div>"
            f"<div class='dial-sub'>כמה כסף חכם נוכח (0-100)</div></div>", unsafe_allow_html=True)
    with c2:
        st.markdown(
            f"<div class='dial'><div class='dial-val' style='color:{conf_col};'>{conf}</div>"
            f"<div class='dial-label'>ביטחון פאזה · {conf_band_he}</div>"
            f"<div class='dial-sub'>{ws.get('phase_he','')}</div></div>", unsafe_allow_html=True)
    with c3:
        st.markdown(
            f"<div class='dial'><div class='dial-val' style='color:{val_color}; font-size:1.35rem;'>{valuation}"
            f"<span class='grade-pill' style='background:{gcol};'>{grade}</span></div>"
            f"<div class='dial-label'>ערך · איכות</div>"
            f"<div class='dial-sub' style='color:{vq_col};'>{vq_text}</div></div>", unsafe_allow_html=True)

    # ---------- (3) הסיפור העקבי — נבנה כמחרוזת HTML *רציפה אחת* (st.markdown יחיד) ----------
    evid = ws.get("evidence", [])
    evid_html = "".join(f"<li>{e}</li>" for e in evid) if evid else "<li>—</li>"
    rows = []
    rows.append(f"<div class='story-row'><span class='story-k'>📍 איפה אנחנו</span>"
                f"<span class='story-v'>{ws.get('phase_he','')} · ביטחון {conf}</span></div>")
    # 🚀 מוכנות למהלך — תווית מילולית (קרוב/מתקרב/רחוק) + ימים ברצף בפאזה. רק כשרלוונטי.
    _rd = _breakout_readiness(ws)
    if _rd.get("applicable"):
        _dtxt = _readiness_days_he(_rd.get("days", 0))
        _dsuf = f" · {_dtxt}" if _dtxt else ""
        rows.append(f"<div class='story-row'><span class='story-k'>🚀 מוכנות למהלך</span>"
                    f"<span class='story-v'>{_rd.get('emoji','')} <b>{_rd.get('label','')}</b>{_dsuf}"
                    f" — {_rd.get('note','')}</span></div>")
    # 📊 היסטורית — שיעור הצלחה של המצב הזה במניה הזו (Tier 3.1). מוצג רק אם יש די דגימות.
    _rel = ws.get("reliability", {})
    if _rel.get("valid"):
        _rcol = {"high": "#16a34a", "mid": "#eab308", "low": "#ef4444"}.get(_rel.get("band"), "#94a3b8")
        rows.append(f"<div class='story-row'><span class='story-k'>📊 היסטורית</span>"
                    f"<span class='story-v' style='color:{_rcol};'>{_rel['summary']}</span></div>")
    rows.append(f"<div class='story-row'><span class='story-k'>🔍 למה</span>"
                f"<span class='story-v'><ul class='story-ul'>{evid_html}</ul></span></div>")
    if pb.get("primary"):
        rows.append(f"<div class='story-row'><span class='story-k'>👀 מה צפוי</span>"
                    f"<span class='story-v'>{pb['primary']}</span></div>")
    if plan.get("valid") and show_plan:
        rows.append(f"<div class='story-row'><span class='story-k'>📋 התוכנית (מבנית)</span>"
                    f"<span class='story-v'>כניסה ${plan['entry_lo']}–${plan['entry_hi']} · "
                    f"סטופ <b style='color:#ef4444;'>${plan['stop']}</b> (מתחת לשפל המבני) · "
                    f"יעדים ${plan['t1']} / ${plan['t2']} / ${plan['t3']} · R:R {plan['rr']}</span></div>")
        rows.append(f"<div class='story-row'><span class='story-k'>⛔ פסילה</span>"
                    f"<span class='story-v'>{plan['invalidation']}</span></div>")
        rows.append(f"<div class='story-row'><span class='story-k'>🎯 שכנוע</span>"
                    f"<span class='story-v'>{_conviction_note(grade, conf)}</span></div>")
    if pb.get("if_fails"):
        chops = f" · <b>אם דשדוש:</b> {pb['if_chops']}" if pb.get("if_chops") else ""
        rows.append(f"<div class='story-row'><span class='story-k'>⚠️ אם משתבש</span>"
                    f"<span class='story-v'><b>אם נכשל:</b> {pb['if_fails']}{chops}</span></div>")
    if pb.get("time"):
        rows.append(f"<div class='story-row'><span class='story-k'>⏱️ זמן</span>"
                    f"<span class='story-v'>{pb['time']}</span></div>")
    # 🏢 העסק — איכות + תמחור. במסלול טרייד זהו *הקשר החזקה בלבד*: אם התזמון לא בשל
    # (caution/דובי/לא-מוגדר) אך העסק איכותי — נאמר מפורשות שזה לטווח ארוך, לא לכניסה עכשיו.
    _ctx = ""
    if grade in ("A", "B") and (ws.get("track") == "bear" or ws.get("caution")
                                or ws.get("state") == "UNDETERMINED"):
        _ctx = "מתאים להחזקה ארוכת-טווח, אך התזמון לטרייד עדיין לא בשל. "
    _biz = _ctx + f"איכות <b style='color:{gcol};'>{grade}</b> — {qual.get('summary','')}"
    if ig.get("summary"):
        _biz += f" {ig['summary']}"
    rows.append(f"<div class='story-row'><span class='story-k'>🏢 העסק</span>"
                f"<span class='story-v'>{_biz}</span></div>")
    wk = ws.get("weekly", {})
    _conflict = _weekly_conflict_note(ws.get("track", "none"), wk, conf)
    foot = (f"<div class='story-foot'>הקשר רב-טווחי: {wk.get('note','—')}{_conflict} · "
            f"קריאת מנוע גולמית: <code>{intel.get('current_phase','—')}</code></div>")
    st.markdown(f"<div class='story-box'>{''.join(rows)}{foot}</div>", unsafe_allow_html=True)


def render_data_status(ticker: str, df: pd.DataFrame = None, fund_data: dict = None,
                       freshness: dict = None) -> None:
    """רצועת סטטוס נתונים אחידה: טריות מחיר + רבעון אחרון שדווח + אזהרות חסר/אירוע."""
    if freshness is None:
        freshness = assess_data_freshness(df, fund_data)
    elif fund_data and not freshness.get("fund_label") and not freshness.get("earnings_flag"):
        # freshness חושב ב-_compute_wyckoff ללא נתונים פונדמנטליים — משלימים את חלק הפונדמנטל/דוחות
        _f2 = assess_data_freshness(df, fund_data)
        freshness = {
            **freshness,
            "fund_status": _f2.get("fund_status", freshness.get("fund_status", "ok")),
            "fund_label": _f2.get("fund_label", ""),
            "missing_fields": _f2.get("missing_fields", []),
            "earnings_flag": _f2.get("earnings_flag", ""),
        }
    chips = []
    # מחיר
    pstatus = freshness.get("price_status", "unknown")
    pcls = {"fresh": "ds-fresh", "warn": "ds-warn", "stale": "ds-stale"}.get(pstatus, "")
    pico = {"fresh": "🟢", "warn": "🟡", "stale": "🔴"}.get(pstatus, "⚪")
    chips.append(f"<span class='ds-chip {pcls}'>{pico} {freshness.get('price_label','—')} · "
                 f"<b>{freshness.get('price_last','—')}</b></span>")
    # רבעון אחרון שדווח
    rep = get_latest_report_info(ticker) if ticker else {}
    if rep:
        lag = rep.get("lag_days", 0)
        lag_txt = f" (לפני {lag} ימים)" if isinstance(lag, int) else ""
        chips.append(f"<span class='ds-chip'>📑 רבעון אחרון שדווח: <b>{rep['quarter_label']}</b>{lag_txt}</span>")
    # פונדמנטלי חסר
    if freshness.get("fund_status") in ("warn", "stale") and freshness.get("fund_label"):
        fcls = "ds-stale" if freshness["fund_status"] == "stale" else "ds-warn"
        chips.append(f"<span class='ds-chip {fcls}'>{freshness['fund_label']}</span>")
    # אירוע רווחים
    if freshness.get("earnings_flag"):
        chips.append(f"<span class='ds-chip ds-warn'>📅 {freshness['earnings_flag']}</span>")
    st.markdown(f"<div class='data-status'>{''.join(chips)}</div>", unsafe_allow_html=True)


def render_phase_evidence(intel: dict, ticker: str = "") -> None:
    """מציג בלוק 'איפה אנחנו בתהליך + למה' עם הראיות. כשאין פאזה מאושרת — אומר זאת מפורשות."""
    phase = intel.get("display_phase", intel.get("current_phase", "—"))
    evidence = intel.get("phase_evidence", []) or []
    status = intel.get("phase_status", "confirmed")
    refined = intel.get("phase_refined", False)
    note = intel.get("phase_refine_note", "")

    # צבע ה-pill לפי סטטוס: caution=אדום, transition=ענבר, אחרת לפי משפחת הפאזה
    if status == "caution":
        pill_cls = "bear"
    elif status == "transition":
        pill_cls = "neut"
    else:
        fam = _phase_family(phase)
        pill_cls = "bear" if fam == "bearish" else ("" if fam in ("bullish_adv", "bullish_early") else "neut")

    parts = ["<div class='phase-evidence'>", "<div class='pe-head'>",
             f"<span class='pe-phase-pill {pill_cls}'>{phase}</span>"]
    if status == "caution":
        parts.append("<span class='pe-refined-tag' style='background:rgba(239,68,68,0.16); color:#fca5a5;'>שכבת אימות — אזהרה</span>")
    elif status == "transition":
        parts.append("<span class='pe-refined-tag' style='background:rgba(245,158,11,0.16); color:#fcd34d;'>ללא פאזה מאושרת</span>")
    elif refined:
        parts.append("<span class='pe-refined-tag'>אומת ע\"י שכבת אימות</span>")
    parts.append("</div>")

    # באנר מרכזי: כשאין פאזה מאושרת / סיכון הפצה — מציגים את הנרטיב 'יצאנו מ-X / ממתינים ל-Y' בבירור
    if status in ("transition", "caution") and note:
        if status == "caution":
            banner_style = "border-right:4px solid #ef4444; background:rgba(239,68,68,0.08);"
            icon = "⚠️"
        else:
            banner_style = "border-right:4px solid #f59e0b; background:rgba(245,158,11,0.08);"
            icon = "🧭"
        parts.append(
            f"<div class='pe-summary' style='{banner_style} padding:12px 14px; border-radius:10px; "
            f"line-height:1.7; color:#e2e8f0;'>{icon} {note}</div>"
        )
    elif refined and note:
        parts.append(f"<div class='pe-summary'>🔎 {note}</div>")

    # הראיות הגולמיות נשארות אינפורמטיביות בכל מצב
    if not evidence:
        parts.append("<div class='pe-summary'>אין מספיק נתונים גולמיים לפירוט ראיות.</div>")
    else:
        if status in ("transition", "caution"):
            parts.append("<div class='pe-summary' style='color:#94a3b8; font-size:0.84rem;'>הראיות הגולמיות (לכל כיוון):</div>")
        for ev in evidence:
            tone = ev.get("tone", "neu")
            ico = {"pos": "▲", "neg": "▼", "neu": "■"}.get(tone, "■")
            parts.append(
                f"<div class='pe-item pe-{tone}'>"
                f"<span class='pe-ico'>{ico}</span>"
                f"<span><span class='pe-label'>{ev.get('label','')}:</span> "
                f"<span class='pe-val'>{ev.get('value','')}</span> — {ev.get('text','')}</span>"
                f"</div>"
            )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def render_cis_meaning(cis: float, factors: pd.DataFrame = None, current_phase: str = "") -> None:
    """כרטיס משמעות CIS ('מה אומר הציון') + expander 'למה קיבלתי את הציון'."""
    info = interpret_cis(cis, current_phase)
    color = info["color"]
    seg_colors = ["#ef4444", "#f59e0b", "#eab308", "#22c55e", "#16a34a"]
    scale = "".join(f"<span class='cm-seg' style='background:{sc};'></span>" for sc in seg_colors)
    note_html = f"<div style='color:#facc15; font-size:0.85rem; margin-top:6px;'>⚠️ {info['note']}</div>" if info["note"] else ""
    st.markdown(
        f"<div class='cis-meaning'>"
        f"<div class='cm-num' style='color:{color};'>{info['score']:.0f}</div>"
        f"<div class='cm-body'>"
        f"<div class='cm-band' style='color:{color};'>{info['band']}</div>"
        f"<div class='cm-meaning'>{info['meaning']} <span style='color:#64748b;'>(0–100, מודד עוצמת כניסת כסף מוסדי)</span></div>"
        f"<div class='cm-scale'>{scale}</div>"
        f"{note_html}"
        f"</div></div>",
        unsafe_allow_html=True,
    )
    breakdown = build_cis_factor_breakdown(factors)
    if breakdown:
        with st.expander("❓ למה קיבלתי את הציון הזה? (פירוט הפקטורים)", expanded=False):
            st.caption("הציון משוקלל מ-10 פקטורים. כל פקטור תורם לפי משקלו; '▲' תורם לציון, '▼' גורע, '■' ניטרלי.")
            for b in breakdown:
                ico = {"+": "▲", "-": "▼", "0": "■"}[b["dir"]]
                dcolor = {"+": "#22c55e", "-": "#ef4444", "0": "#64748b"}[b["dir"]]
                st.markdown(
                    f"<div style='display:flex; gap:10px; padding:5px 0; border-bottom:1px solid rgba(148,163,184,0.1);'>"
                    f"<span style='color:{dcolor}; font-weight:800;'>{ico}</span>"
                    f"<span style='flex:1;'><b>{b['label']}</b> "
                    f"<span style='color:#64748b;'>(משקל {b['weight']})</span> — {b['text']}</span>"
                    f"<span style='color:{dcolor}; font-weight:700;'>{b['value']:+.2f}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )


def render_macro_radar(compact: bool = False) -> None:
    """מציג את ה-Macro Technical Radar (שכבה תומכת)."""
    radar = compute_macro_radar()
    if not radar.get("cells"):
        return
    cells_html = "".join(
        f"<div class='mr-cell'><div class='mr-cell-name'>{c['name']}</div>"
        f"<div class='mr-cell-val' style='color:{c['color']};'>{c['state']} "
        f"<span style='font-size:0.78rem; color:#64748b;'>({c['mom']:+.1f}%)</span></div></div>"
        for c in radar["cells"]
    )
    st.markdown(
        f"<div class='macro-radar'>"
        f"<div class='mr-head'>"
        f"<span class='mr-title'>🛰️ Macro Technical Radar</span>"
        f"<span class='mr-regime' style='background:{radar['color']}20; color:{radar['color']};'>{radar['regime']}</span>"
        f"</div>"
        f"<div class='mr-grid'>{cells_html}</div>"
        f"<div class='mr-note'>💡 {radar['note']}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_swing_plan(plan: dict, rec_data: dict) -> None:
    """מציג תוכנית Swing ישימה + תרחישי Shakeout/Breakout, בהפרדה וויקוף/פונדמנטלי."""
    if not plan or not plan.get("valid"):
        st.info("אין תוכנית כניסה ללונג במצב הנוכחי (הסתברות צבירה נמוכה / פאזת הפצה).")
        return

    st.markdown(
        "<div class='swing-sep'>🎯 תוכנית מסחר — Swing "
        "<span class='sep-tag tag-short'>וויקוף · טווח קצר-בינוני</span></div>",
        unsafe_allow_html=True,
    )
    st.caption(f"טווח זמן אופטימלי: {plan['timeframe']} · פאזה: {plan['phase']}")
    st.markdown(
        f"""<div class='plan-stage'><span class='plan-stage-label'>📍 כניסה (חצי עכשיו)</span>
        <span class='plan-stage-val' style='color:#38bdf8'>${plan['entry']}</span>
        <span class='plan-stage-note'>חצי שני בפולבק קל לאזור ${plan['entry_pullback']} — כניסה מדורגת מקטינה סיכון תזמון.</span></div>
        <div class='plan-stage'><span class='plan-stage-label'>🛑 סטופ הגנה</span>
        <span class='plan-stage-val' style='color:#f87171'>${plan['stop']} ({plan['stop_pct']}%)</span>
        <span class='plan-stage-note'>אחרי יעד 1 — העלה את הסטופ לנקודת הכניסה = עסקה ללא סיכון.</span></div>
        <div class='plan-stage'><span class='plan-stage-label'>🎯 יעד 1 (R:R 1:{plan['rr1']})</span>
        <span class='plan-stage-val' style='color:#34d399'>${plan['tp1']} (+{plan['tp1_pct']}%)</span>
        <span class='plan-stage-note'>{plan['tp1_action']}</span></div>
        <div class='plan-stage'><span class='plan-stage-label'>🎯 יעד 2 (R:R 1:{plan['rr2']})</span>
        <span class='plan-stage-val' style='color:#34d399'>${plan['tp2']} (+{plan['tp2_pct']}%)</span>
        <span class='plan-stage-note'>{plan['tp2_action']}</span></div>
        <div class='plan-stage'><span class='plan-stage-label'>🎯 יעד 3 (Runner)</span>
        <span class='plan-stage-val' style='color:#34d399'>${plan['tp3']} (+{plan['tp3_pct']}%)</span>
        <span class='plan-stage-note'>{plan['tp3_action']}</span></div>""",
        unsafe_allow_html=True,
    )

    # תרחישים
    st.markdown("<div class='swing-sep'>🗺️ תרחישים — מה אם?</div>", unsafe_allow_html=True)
    st.markdown(
        f"<div class='scenario-grid'>"
        f"<div class='scenario-card bear'><div class='sc-title bear'>🌀 אם Shakeout / ניעור</div>"
        f"<div class='sc-body'>{plan['shakeout']}</div></div>"
        f"<div class='scenario-card bull'><div class='sc-title bull'>🚀 אם Breakout / פריצה</div>"
        f"<div class='sc-body'>{plan['breakout']}</div></div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # הפרדת פונדמנטלי (טווח ארוך)
    fund = rec_data.get("fundamental", {}) or {}
    if fund:
        valuation = fund.get("valuation", "-")
        vcolor = fund.get("valuation_color", "#94a3b8")
        st.markdown(
            "<div class='swing-sep'>🏢 שכבה פונדמנטלית "
            "<span class='sep-tag tag-long'>טווח ארוך · נפרד מהתזמון</span></div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div class='sc-body' style='padding:4px 2px;'>"
            f"התמחור (<b style='color:{vcolor};'>{valuation}</b>), ה-FCF (<b>{fund.get('fcf_yield','N/A')}</b>) "
            f"והצמיחה (<b>{fund.get('rev_growth','N/A')}</b>) קובעים את כדאיות <u>ההחזקה לטווח ארוך</u> — "
            f"לא את נקודת הכניסה. תוכנית הסווינג למעלה מבוססת וויקוף (תזמון); הפונדמנטל הוא שיקול ההחזקה/הגדלה."
            f"</div>",
            unsafe_allow_html=True,
        )


def render_wyckoff_deep_analysis(ticker: str, intel: dict) -> None:
    """ניתוח Wyckoff מעמיק: Trading Range + אירועים מבניים + VSA + יעדי Cause & Effect.
    שכבת אפליקציה בלבד (קוראת OHLCV, לא נוגעת בליבה)."""
    df = intel.get("df")
    if df is None or len(df) < 40:
        st.caption("נדרשים לפחות 40 ימי מסחר לניתוח Wyckoff מעמיק.")
        return
    tr = detect_trading_range(df)
    events = detect_wyckoff_events(df, tr)
    vsa = classify_vsa_bars(df, n=15)
    targets = wyckoff_cause_effect_targets(df, tr)
    _tone_col = {"pos": "#22c55e", "neg": "#ef4444", "neu": "#eab308"}
    _tone_ico = {"pos": "▲", "neg": "▼", "neu": "■"}

    # --- 1. Trading Range ---
    if tr.get("valid") and tr.get("is_range"):
        loc_he = {"breakout_up": "פריצה מעל הטווח (Markup)", "breakdown": "שבירה מתחת לטווח (Markdown)",
                  "upper": "שליש עליון — קרוב להתנגדות", "lower": "שליש תחתון — קרוב לתמיכה",
                  "middle": "אמצע הטווח — אזור קונפליקט"}.get(tr["location"], tr["location"])
        pos_pct = max(0, min(100, int(tr["position"] * 100)))
        st.markdown(
            f"<div class='phase-evidence'><div class='pe-head'>"
            f"<span class='pe-phase-pill'>📦 טווח מסחר (Trading Range)</span>"
            f"<span style='color:#94a3b8; font-size:0.85rem;'>{loc_he}</span></div>"
            f"<div class='wyck-tr-bar'><div class='wyck-tr-dot' style='left:{pos_pct}%;'></div></div>"
            f"<div style='display:flex; justify-content:space-between; font-size:0.8rem; color:#94a3b8; margin-top:6px;'>"
            f"<span>🟢 תמיכה ${tr['support']}</span><span>רוחב {tr['width_pct']}%</span>"
            f"<span>🔴 התנגדות ${tr['resistance']}</span></div>"
            f"<div class='pe-summary'>המחיר ב-{pos_pct}% מהטווח · נגיעות תמיכה: {tr['touches_s']} · "
            f"התנגדות: {tr['touches_r']} · ~{tr['bars']} ברים בטווח (גודל ה'סיבה' לפי חוק Cause & Effect).</div></div>",
            unsafe_allow_html=True,
        )
    elif tr.get("valid"):
        # מגמה — אין טווח מסחר מובהק (לא משליכים 'טווח' מזויף)
        st.markdown(
            f"<div class='phase-evidence'><div class='pe-head'>"
            f"<span class='pe-phase-pill'>📈 מגמה — אין טווח מסחר מובהק</span></div>"
            f"<div class='pe-summary'>המחיר במהלך כיווני ללא קונסולידציה ברורה (חצה את אמצע הטווח רק "
            f"{tr.get('crossings',0)} פעמים). אירועי TR ויעדי Cause & Effect דורשים טווח אמיתי — לכן מוצגת "
            f"כאן קריאת VSA נר-נר בלבד. לזיהוי פאזה/סיכון ראה את הניתוח הראשי למעלה.</div></div>",
            unsafe_allow_html=True,
        )

    # --- 2. אירועי Wyckoff מבניים ---
    if events:
        st.markdown("<div class='section-label' style='margin-top:12px;'>🎯 אירועי Wyckoff מזוהים</div>", unsafe_allow_html=True)
        for ev in events:
            col = _tone_col[ev["tone"]]
            st.markdown(
                f"<div class='plan-stage' style='border-color:{col}44;'>"
                f"<span class='plan-stage-label' style='color:{col};'>{ev['event']}</span>"
                f"<span class='plan-stage-val' style='color:{col};'>${ev['price']} · {ev['date']}</span>"
                f"<span class='plan-stage-note'>{ev['desc']}</span></div>",
                unsafe_allow_html=True,
            )

    # --- 3. VSA — נרות אחרונים ---
    if vsa:
        st.markdown("<div class='section-label' style='margin-top:12px;'>📊 VSA — קריאת נרות אחרונים (Volume Spread Analysis)</div>", unsafe_allow_html=True)
        rows = []
        for b in vsa[::-1][:7]:
            col = _tone_col[b["tone"]]
            rows.append(
                f"<div class='pe-item pe-{b['tone']}'>"
                f"<span class='pe-ico' style='color:{col};'>{_tone_ico[b['tone']]}</span>"
                f"<span><b>{b['date']}</b> · <span style='color:{col};'>{b['label']}</span> "
                f"<span style='color:#64748b;'>(נפח ×{b['vol_ratio']})</span> — {b['note']}</span></div>"
            )
        st.markdown("".join(rows), unsafe_allow_html=True)

    # --- 4. יעדי Cause & Effect ---
    if targets.get("valid"):
        st.markdown("<div class='section-label' style='margin-top:12px;'>🎯 יעדי Cause & Effect (השלכת רוחב הטווח)</div>", unsafe_allow_html=True)
        st.caption(f"חוק הסיבה והתוצאה: רוחב הטווח (${targets['width']}, {targets['width_pct']}%) הוא ה'סיבה' הצבורה. "
                   f"היעדים נמדדים מרמת הפריצה — שמרני (×1), בסיס (×2), מורחב (×3). פרוקסי לספירת P&F אופקית.")
        up, down = targets["up"], targets["down"]
        st.markdown(
            f"<div class='scenario-grid'>"
            f"<div class='scenario-card bull'><div class='sc-title bull'>⬆️ פריצה מעל ${targets['breakout_up']}</div>"
            f"<div class='sc-body'>שמרני <b>${up['conservative']['price']}</b> ({up['conservative']['pct']:+}%) · "
            f"בסיס <b>${up['base']['price']}</b> ({up['base']['pct']:+}%) · "
            f"מורחב <b>${up['extended']['price']}</b> ({up['extended']['pct']:+}%)</div></div>"
            f"<div class='scenario-card bear'><div class='sc-title bear'>⬇️ שבירה מתחת ${targets['breakdown']}</div>"
            f"<div class='sc-body'>שמרני <b>${down['conservative']['price']}</b> ({down['conservative']['pct']:+}%) · "
            f"בסיס <b>${down['base']['price']}</b> ({down['base']['pct']:+}%) · "
            f"מורחב <b>${down['extended']['price']}</b> ({down['extended']['pct']:+}%)</div></div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    if not (tr.get("valid") or events or vsa):
        st.caption("לא זוהה מבנה טווח מסחר מובהק כרגע (ייתכן שהמניה במגמה חדה ללא קונסולידציה).")


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
    _cphase, _timing_html, _fit_html = _structural_timing_chip(p["ticker"], p.get("phase", ""), p.get("valuation", ""))
    hot_html = _phase_hot_badge(_cphase, p.get("cis", 0))
    st.markdown(
        f"""<div class='pick-card' style='border-right:5px solid {p['color']}; border-top:none; margin-bottom:8px;'>
            <div style='display:flex; align-items:center; gap:14px; flex-wrap:wrap;'>
                <span class='pick-rank'>#{idx+1}</span>
                <span class='pick-ticker' style='font-size:1.5rem;'>{p['ticker']}</span>
                <span>{price_html}</span>
                {hot_html}
            </div>
            <div style='margin-top:8px;'>{_timing_html} {_fit_html}</div>
            <div class='pick-headline' style='color:{p['color']}; margin-top:8px;'>{p['headline']}</div>
            <div class='pick-meta'>תמחור: <b style='color:{p['valuation_color']}'>{p['valuation']}</b> · CIS {p['cis']:.0f}
                · Wyckoff: {_cphase} · FCF: {p['fcf_yield']} · P/E: {p['pe']} · {p['sector_he']}</div>
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
        elif dest_page == "🏠 בית":
            st.session_state.home_mode = "check"  # V25.8 FIX: אחרת ה-handoff לא נצרך
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
    _cphase, _timing_html, _fit_html = _structural_timing_chip(p["ticker"], p.get("phase", ""), p.get("valuation", ""))
    hot_html = _phase_hot_badge(_cphase, p.get("cis", 0))

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
                        {hot_html}
                    </div>
                    <div style='margin-top:8px;'>{_timing_html} {_fit_html}</div>
                    <div class='pick-headline' style='color:{p['color']}; margin-top:8px;'>{p['headline']}</div>
                    <div class='pick-meta'>תמחור: <b style='color:{p['valuation_color']}'>{p['valuation']}</b> · CIS {p['cis']:.0f}
                        · Wyckoff: {_cphase} · FCF: {p['fcf_yield']} · P/E: {p['pe']} · {p['sector_he']}</div>
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
        elif dest_page == "🏠 בית":
            # V25.8 FIX: פתיחת הניתוח המלא *בתוך* הבית מחייבת מצב "check" — אחרת נשארים
            # ב-focused/results, ה-handoff לא נצרך, והכפתור "לא עושה כלום".
            st.session_state.home_mode = "check"
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
        sp_cphase, _spt, _spf = _structural_timing_chip(sp["ticker"], sp.get("phase", ""), sp.get("valuation", ""))
        sp_hot = _phase_hot_badge(sp_cphase, sp.get("cis", 0))
        parts.append(
            f"<div class='swipe-card' style='border-right:5px solid {sp['color']};'>"
            f"<div class='swipe-card-top'>"
            f"<span class='pick-rank'>#{i+1}</span>"
            f"<span class='pick-ticker'>{sp['ticker']}</span>"
            f"<span class='swipe-price'>{sp_price_html}</span>"
            f"{sp_hot}"
            f"</div>"
            f"<div class='pick-headline' style='color:{sp['color']};'>{sp.get('headline','')}</div>"
            f"<div class='pick-meta'>תמחור: <b style='color:{sp['valuation_color']}'>{sp['valuation']}</b> · CIS {sp['cis']:.0f}"
            f" · Wyckoff: {sp_cphase} · FCF: {sp['fcf_yield']} · P/E: {sp['pe']} · {sp['sector_he']}</div>"
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
        # V20.2: שכבת מאקרו תומכת מעל תוצאות הסריקה (Risk-On/Off רחב)
        render_macro_radar(compact=True)
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


# ============================================================
# V25.0 — Dual-Lens Analysis (פיצול מסלולים: טרייד / השקעה)
# פתרון הסתירות הלוגיות (משוב BKNG #2): כשה-Wyckoff (תזמון קצר) והערך (שווי ארוך)
# חלוקים — שניהם נכונים במקביל, אבל אסור לערבב אותם למסר אחד. לכן:
# (1) מסך בחירת מסלול (2 כפתורים) אחרי כל ניתוח; (2) כיול טון ל-verdict כך שלא
# ייאמר "סכין נופלת/ביטחון גבוה" על אזהרה בביטחון 46; (3) תגיות תזמון מבני בסורק
# כדי שהסורק לא ימליץ על מה שהניתוח מיד יזהיר מפניו; (4) הסבר "ראיות סותרות"
# כשהשבועי מנוגד ליומי. שכבת אפליקציה בלבד.
# ============================================================

def _get_analysis_lens(ticker: str):
    """המסלול הנבחר (trade/invest) עבור הטיקר הנוכחי; None = טרם נבחר (מסך בחירה)."""
    try:
        if st.session_state.get("analysis_lens_ticker") != ticker:
            return None
        return st.session_state.get("analysis_lens")
    except Exception:
        return None


def _set_analysis_lens(ticker: str, lens: str) -> None:
    st.session_state["analysis_lens_ticker"] = ticker
    st.session_state["analysis_lens"] = lens


def _render_lens_chooser(ticker: str) -> None:
    """מסך בחירת מסלול — מינימלי בכוונה (2 כפתורים), כדי לא להכביד על המשתמש."""
    st.markdown("<div class='section-label' style='margin-top:18px;'>באיזו עדשה לנתח את המניה?</div>",
                unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🏦 ניתוח להשקעה ארוכת טווח", use_container_width=True, type="primary",
                     key=f"lens_invest_{ticker}"):
            _set_analysis_lens(ticker, "invest")
            st.rerun()
        st.caption("ערך, איכות ותמחור — האם העסק שווה החזקה של שנים, והאם המחיר אטרקטיבי.")
    with c2:
        if st.button("⚡ ניתוח לטרייד (סווינג)", use_container_width=True, type="primary",
                     key=f"lens_trade_{ticker}"):
            _set_analysis_lens(ticker, "trade")
            st.rerun()
        st.caption("תזמון Wyckoff — פאזה, כניסה, סטופ, יעדים ותרחישים לשבועות הקרובים.")
    st.caption("ההפרדה מונעת ערבוב בין תזמון קצר-טווח לשווי ארוך-טווח (שני המסלולים מתייחסים זה לזה כהקשר, לא כהכרעה). אפשר להחליף מסלול בכל שלב.")


def _render_lens_switch(current: str, ticker: str) -> None:
    """שורת החלפת מסלול בראש כל ניתוח."""
    other = "invest" if current == "trade" else "trade"
    label = "🏦 עבור לניתוח השקעה ארוכת טווח" if other == "invest" else "⚡ עבור לניתוח לטרייד (סווינג)"
    cur_he = "⚡ מסלול נוכחי: טרייד / סווינג" if current == "trade" else "🏦 מסלול נוכחי: השקעה ארוכת טווח"
    c1, c2 = st.columns([1.1, 1])
    with c1:
        st.markdown(f"<div class='lens-current'>{cur_he}</div>", unsafe_allow_html=True)
    with c2:
        if st.button(label, use_container_width=True, key=f"lens_switch_{ticker}_{current}"):
            _set_analysis_lens(ticker, other)
            st.rerun()


def _calibrate_verdict_tone(verdict: dict, ws: dict):
    """
    מכייל את טון ה-verdict מהליבה לפי המצב המבני, כדי למנוע סתירות תצוגה:
    (א) צ'יפ ה"ביטחון" בבאנר מסונכרן תמיד לביטחון-הפאזה המבני (לא עוד 'ביטחון גבוה'
        לצד חיוג 46); (ב) DIST_WARNING בביטחון נמוך = אזהרה מדודה, לא "סכין נופלת" —
    הניסוח ההוא שמור לשבירה מאושרת (DIST_ACTIVE/MARKDOWN). לעולם לא משדרג
    לכיוון קנייה (הבטחת הברזל של הליבה נשמרת) — רק מרכך ניסוח בתוך AVOID.
    """
    try:
        if not verdict or not isinstance(verdict, dict) or not ws:
            return verdict
        state = ws.get("state", "")
        conf = int(ws.get("confidence", 0))
        caution = bool(ws.get("caution"))
        band_he = "גבוה" if conf >= 70 else ("בינוני" if conf >= 50 else "נמוך")
        verdict["confidence"] = f"{band_he} ({conf})"   # (א) צ'יפ ביטחון = ביטחון הפאזה
        headline = verdict.get("headline", "") or ""
        knife = ("סכין" in headline) or ("נופל" in headline)
        confirmed_bear = state in ("DIST_ACTIVE", "MARKDOWN")   # רק כאן "סכין נופלת" מותר

        # (ב) "סכין נופלת"/תג דובי-חזק שאינו במצב שבירה מאושרת → מוחלף במסר מדוד לפי המצב
        if (knife or verdict.get("tier") == "STRONG_AVOID") and not confirmed_bear:
            if state == "DIST_WARNING":
                verdict["headline"] = "⚠️ אזהרת הפצה — תזמון שלילי (המבנה טרם נשבר)"
                verdict["action_line"] = ("אין כניסת לונג. מחזיקים — צמצום חלקי + הידוק סטופ. "
                                          "שבירת תמיכה בנפח = יציאה; פריצה מחודשת = האזהרה בטלה.")
                verdict["color"], verdict["tier"] = "#f59e0b", "AVOID"
            elif caution:
                verdict["headline"] = "⚠️ שלב D בזהירות — תיקון אפשרי"
                verdict["action_line"] = "המתן לאישור (שפל גבוה-יותר + נפח דועך) לפני כניסה/תוספת. אל תרדוף."
                verdict["color"], verdict["tier"] = "#eab308", "WATCH"
            elif state == "UNDETERMINED":
                verdict["headline"] = "⏳ אין מבנה מאושר — המתן"
                verdict["action_line"] = "אין תזמון כניסה כרגע. סרוק שוב כשייווצר מבנה ברור."
                verdict["color"], verdict["tier"] = "#94a3b8", "NEUTRAL"

        # (ג) שלב D "בזהירות" אך הליבה נתנה תג קנייה → מורידים ל-WATCH (השווי נשמר, לא "קנה עכשיו")
        if caution and verdict.get("tier") in ("STRONG_BUY", "BUY", "OPPORTUNITY"):
            verdict["tier"] = "WATCH"
            verdict["headline"] = "⚠️ שלב D בזהירות — תיקון אפשרי"
            verdict["action_line"] = ("המתן לאישור (שפל גבוה-יותר + נפח דועך) לפני כניסה/תוספת. "
                                      + (verdict.get("action_line") or ""))
            if verdict.get("color") in ("#16a34a", "#22c55e"):
                verdict["color"] = "#eab308"
    except Exception:
        pass
    return verdict


def _weekly_conflict_note(track: str, weekly_ctx: dict, confidence) -> str:
    """כשההקשר השבועי מנוגד לקריאה היומית — אומרים זאת מפורשות (זה מסביר את הביטחון הנמוך)."""
    try:
        wb = float((weekly_ctx or {}).get("weekly_bias", 0.0))
        regime = (weekly_ctx or {}).get("regime", "")
        if track == "bear" and (wb >= 0.2 or regime == "WEEKLY_BOTTOMING"):
            return (f" ⚠️ שים לב: ההקשר השבועי נוטה דווקא לאיסוף — ראיות סותרות בין הטווחים, "
                    f"וזו בדיוק הסיבה שהביטחון רק {confidence}.")
        if track == "bull" and (wb <= -0.2 or regime == "WEEKLY_TOPPING"):
            return (f" ⚠️ שים לב: ההקשר השבועי שלילי — ראיות סותרות בין הטווחים, "
                    f"לכן הביטחון מוגבל ({confidence}).")
    except Exception:
        pass
    return ""


def _horizon_safe_vq_sub(vq_text: str, vq_col: str, track: str, state: str):
    """
    חיוג הערך במסלול טרייד לא ישדר 'שילוב אידיאלי' (=קנה עכשיו) כשהתזמון שלילי:
    שווי חיובי + מבנה דובי ⇒ 'שיקול החזקה ארוכה, לא כניסה'.
    """
    try:
        positive = ("אידיאלי" in vq_text) or ("בסיס טוב" in vq_text)
        if positive and track == "bear":
            return "עסק איכותי/זול — אך התזמון כרגע שלילי: שיקול לטווח ארוך, לא לכניסה עכשיו", "#eab308"
        if positive and state == "UNDETERMINED":
            return vq_text + " (שיקול ארוך-טווח; אין תזמון מבני כרגע)", vq_col
    except Exception:
        pass
    return vq_text, vq_col


@st.cache_data(ttl=1800, max_entries=128, show_spinner=False)
def _quick_structural_state(ticker: str) -> dict:
    """FSM מהיר לתגיות הסורק (ללא CIS/כיול): מצב, תווית ומסלול. עמיד-כשל."""
    try:
        df = get_cached_data(ticker)
        if df is None or df.empty or len(df) < 60:
            return {}
        tr = detect_trading_range(df)
        events = detect_wyckoff_events(df, tr)
        vsa = classify_vsa_bars(df, 15)
        wc = assess_weekly_context(_to_weekly(df))
        so = classify_wyckoff_state(df, tr, events, vsa, wc)
        meta = _WSTATES.get(so["state"], _WSTATES["UNDETERMINED"])
        cau = bool(so.get("caution")) and meta["track"] == "bull"
        days = _compute_days_in_phase(df, tr, meta["track"] == "bull",
                                      state=so["state"], events=events)
        rd = _breakout_readiness({"state": so["state"], "tr": tr, "days_in_phase": days, "caution": cau})
        return {"state": so["state"], "phase_he": meta["he"] + (" — בזהירות" if cau else ""),
                "track": meta["track"], "caution": cau, "days_in_phase": days, "readiness": rd}
    except Exception:
        return {}


def _timing_fit_labels(qs: dict, valuation: str):
    """לוגיקה טהורה (נבדקת): מצב מבני + תמחור ⇒ (תווית פאזה, צ'יפ תזמון, צ'יפ התאמה)."""
    if not qs:
        return None, "", ""
    phase_he, track, state = qs.get("phase_he", ""), qs.get("track", ""), qs.get("state", "")
    caution = bool(qs.get("caution"))
    v = valuation or ""
    cheap, exp = ("זול" in v), ("יקר" in v)
    # V25.9: צ'יפ מוכנות למהלך (רק לכיוון שורי/רלוונטי) — תווית מילולית + ימים ברצף
    rd = qs.get("readiness") or {}
    ready_chip = ""
    if rd.get("applicable"):
        _dtxt = _readiness_days_he(rd.get("days", 0))
        _dsuf = f" · {_dtxt}" if _dtxt else ""
        ready_chip = (f"<span class='ready-chip'>{rd.get('emoji','')} מוכנות: "
                      f"{rd.get('label','')}{_dsuf}</span>")
    if track == "bull":
        _tc = ("rgba(234,179,8,0.16)", "#fde68a", "rgba(234,179,8,0.4)") if caution else \
              ("rgba(22,163,74,0.16)", "#86efac", "rgba(22,163,74,0.35)")
        timing = (f"<span class='timing-chip' style='background:{_tc[0]}; color:{_tc[1]}; "
                  f"border:1px solid {_tc[2]};'>{'⚠️' if caution else '⚡'} תזמון: {phase_he}</span>")
        if caution:
            fit = "<span class='fit-chip'>מתאים ל: ⚡ טרייד + זהירות</span>"
        elif exp:
            fit = "<span class='fit-chip'>מתאים ל: ⚡ טרייד (יקר להשקעה)</span>"
        else:
            fit = "<span class='fit-chip'>מתאים ל: ⚡ טרייד · 🏦 השקעה</span>"
    elif track == "bear":
        timing = f"<span class='timing-chip' style='background:rgba(239,68,68,0.14); color:#fca5a5; border:1px solid rgba(239,68,68,0.35);'>⚠️ תזמון: {phase_he}</span>"
        fit = ("<span class='fit-chip'>מתאים ל: 🏦 השקעה (תזמון שלילי)</span>" if cheap
               else "<span class='fit-chip'>⏳ מעקב</span>")
    else:
        timing = f"<span class='timing-chip' style='background:rgba(148,163,184,0.14); color:#cbd5e1; border:1px solid rgba(148,163,184,0.3);'>⏳ תזמון: אין מבנה מאושר</span>"
        fit = ("<span class='fit-chip'>מתאים ל: 🏦 השקעה (בהדרגה)</span>" if cheap
               else "<span class='fit-chip'>⏳ מעקב</span>")
    return phase_he, timing, (fit + (" " + ready_chip if ready_chip else ""))


def _structural_timing_chip(ticker: str, engine_phase: str, valuation: str = ""):
    """עטיפה לסורק: FSM מהיר → תגיות; נפילה חיננית ל-pick_phase_caution הישן."""
    try:
        qs = _quick_structural_state(ticker)
        ph, timing, fit = _timing_fit_labels(qs, valuation)
        if ph:
            return ph, timing, fit
    except Exception:
        pass
    try:
        cphase, _, _ = pick_phase_caution(ticker, engine_phase)
    except Exception:
        cphase = engine_phase
    return cphase, "", ""


def _focused_filter(results, phase_state=None, grade_set=None, valuation_set=None,
                    sector_tickers=None, cap=40, quick_fn=None, fund_fn=None,
                    dura_fn=None, qadj_fn=None, progress_cb=None, attach_readiness=False):
    """
    V25.4 — מנוע הסריקה הממוקדת: משלב עד 4 צירים, כל אחד אופציונלי (None = "הכל"):
      • phase_state — פאזת FSM מבנית (מקור האמת היחיד לפאזה).
      • grade_set   — קבוצת דרגות איכות A-F (מותאם-Durability).
      • valuation_set — קבוצת תמחור {זול/הוגן/יקר} (מגיע מתוצאת הסריקה — ללא שליפה).
      • sector_tickers — סינון חברות בטיקרים של סקטור.
    מסננים זולים (תמחור/סקטור) קודם, ואז היקרים (FSM/איכות) על מה ששרד, עד cap.
    V25.9: attach_readiness=True מצרף לכל תוצאה את מוכנות-המהלך (_readiness) — לצורך
    מיון "הכי קרוב לפריצה". טהור וניתן לבדיקה. מחזיר (filtered, checked).
    """
    qf = quick_fn or _quick_structural_state
    ff = fund_fn or get_fundamental_data
    dfn = dura_fn or compute_durability
    qa = qadj_fn or _quality_adjusted
    pool = []
    for r in (results or []):
        tk = r.get("ticker")
        if not tk:
            continue
        if sector_tickers is not None and tk not in sector_tickers:
            continue
        if valuation_set is not None and (r.get("valuation", "") not in valuation_set):
            continue
        pool.append(r)
    pool = pool[:cap]
    out, checked = [], 0
    for i, r in enumerate(pool):
        tk = r["ticker"]
        checked += 1
        if progress_cb:
            try:
                progress_cb(i + 1, len(pool), tk)
            except Exception:
                pass
        q = dict(r)
        need_fsm = (phase_state is not None) or attach_readiness
        if need_fsm:
            try:
                qs = qf(tk) or {}
            except Exception:
                qs = {}
            if phase_state is not None and qs.get("state") != phase_state:
                continue
            q["_fsm_phase_he"] = qs.get("phase_he", "")
            q["_fsm_caution"] = bool(qs.get("caution"))
            q["_readiness"] = qs.get("readiness") or {}
        if grade_set is not None:
            try:
                fd = ff(tk) or {}
                grade = qa(fd, dfn(tk)).get("grade", "—")
            except Exception:
                grade = "—"
            if grade not in grade_set:
                continue
            q["_focus_grade"] = grade
        out.append(q)
    if attach_readiness:
        # מיון "הכי קרוב למהלך": rank גבוה קודם, ואז יותר ימים ברצף בפאזה
        out.sort(key=lambda x: ((x.get("_readiness") or {}).get("rank", 0),
                                (x.get("_readiness") or {}).get("days", 0)), reverse=True)
    return out, checked


def _filter_results_by_phase(results, target_state, quick_fn=None, cap=40, progress_cb=None):
    """
    V25.3 — סינון תוצאות סריקה לפי פאזת FSM *מבנית* (מקור האמת היחיד לפאזה, גם בסריקה).
    מריץ את ה-FSM המהיר (cached ~30ד') רק על מועמדים ששרדו את הסריקה (עד cap), ומחזיר
    רק את אלו שנמצאים כרגע בפאזה שנבחרה. טהור וניתן לבדיקה (quick_fn ניתן להזרקה).
    """
    qf = quick_fn or _quick_structural_state
    out, checked = [], 0
    pool = list(results or [])[:cap]
    for i, p in enumerate(pool):
        tk = p.get("ticker")
        if not tk:
            continue
        checked += 1
        if progress_cb:
            try:
                progress_cb(i + 1, len(pool), tk)
            except Exception:
                pass
        try:
            qs = qf(tk) or {}
        except Exception:
            qs = {}
        if qs.get("state") == target_state:
            q = dict(p)
            q["_fsm_phase_he"] = qs.get("phase_he", "")
            q["_fsm_caution"] = bool(qs.get("caution"))
            out.append(q)
    return out, checked


def render_invest_lens(ticker: str, intel: dict) -> None:
    """
    מסלול השקעה ארוכת טווח: ערך+איכות בראש, וויקוף כהקשר תזמון בלבד.
    שורה תחתונה פשוטה קודם (חוק הברזל), אז חיוגי השקעה, עומק מלא, והקשר תזמון.
    """
    ws = intel.get("wyckoff_state") or {}
    fd = get_fundamental_data(ticker) or {}
    dura = compute_durability(ticker)
    qa = _quality_adjusted(fd, dura)
    ig = compute_implied_growth(fd)
    grade = qa.get("grade", "—")
    gcol = _grade_color(grade)
    valuation = fd.get("valuation", "—")
    vcol = fd.get("valuation_color", "#94a3b8")
    vq_text, vq_col = _value_quality_conclusion(valuation, grade)
    phase_he = ws.get("phase_he", "—")
    conf = ws.get("confidence", 0)
    track = ws.get("track", "none")

    good, bad = grade in ("A", "B"), grade in ("D", "F")
    cheap, exp = ("זול" in (valuation or "")), ("יקר" in (valuation or ""))
    if track == "bull" and conf >= 50:
        timing_line = f"התזמון הטכני תומך כרגע ({phase_he}, ביטחון {conf}) — אפשר לשקול כניסה מדורגת."
    elif track == "bear":
        timing_line = (f"התזמון הטכני שלילי כרגע ({phase_he}, ביטחון {conf}) — למשקיע ארוך טווח: "
                       f"כניסה מדורגת/המתנה לרגיעה, אין צורך לרדוף.")
    else:
        timing_line = f"אין תזמון טכני ברור ({phase_he}) — כניסה מדורגת לפי ערך, לא לפי גרף."

    if good and cheap:
        head, act, tier, color = ("🏦 עסק איכותי במחיר אטרקטיבי — מועמד השקעה",
                                  "בחינת כניסה מדורגת לטווח ארוך. " + timing_line, "OPPORTUNITY", "#16a34a")
    elif good and exp:
        head, act, tier, color = ("🏆 עסק מצוין אך יקר — רשימת המתנה",
                                  "המתן למחיר טוב יותר או כניסה מדורגת קטנה. " + timing_line, "NEUTRAL", "#eab308")
    elif bad:
        head, act, tier, color = ("⚠️ איכות נמוכה — לא מתאים להשקעה ארוכת טווח",
                                  "גם במחיר נמוך — סיכון מלכודת ערך. אם בכלל, זהו נכס למסלול טרייד בלבד.",
                                  "AVOID", "#ef4444")
    else:
        head, act, tier, color = ("⚖️ עסק סביר — לא בולט לטוב או לרע",
                                  "אין דחיפות; עדיף מועמדים איכותיים/זולים יותר. " + timing_line, "NEUTRAL", "#94a3b8")
    invest_verdict = {"headline": head, "action_line": act, "tier": tier, "color": color,
                      "detail": f"{qa.get('summary','')} {ig.get('summary','')}",
                      "confidence": ("גבוה" if (good and dura.get("valid")) else "בינוני")}
    render_verdict_banner(
        invest_verdict, ticker=ticker, cis_score=None, current_phase=f"תזמון: {phase_he}",
        valuation=valuation, valuation_color=vcol,
        extra_chips=[f"איכות <b style='color:{gcol};'>{grade}</b>"],
    )

    # --- חיוגי השקעה: איכות / תמחור / תזמון (הקשר) ---
    c1, c2, c3 = st.columns(3)
    with c1:
        dsub = (f"FCF חיובי {dura.get('fcf_pos')}/{dura.get('fcf_total')} שנים · מרווחים {dura.get('margin_trend')}"
                if dura.get("valid") else "לפי דוח אחרון (אין די היסטוריה)")
        st.markdown(f"<div class='dial'><div class='dial-val' style='color:{gcol};'>{grade}</div>"
                    f"<div class='dial-label'>איכות עסקית</div><div class='dial-sub'>{dsub}</div></div>",
                    unsafe_allow_html=True)
    with c2:
        isub = ig.get("summary", "—") if ig.get("valid") else "אין FCF חיובי — לא ניתן לתמחר לפי תזרים"
        st.markdown(f"<div class='dial'><div class='dial-val' style='color:{vcol}; font-size:1.5rem;'>{valuation}</div>"
                    f"<div class='dial-label'>תמחור (Reverse-DCF)</div><div class='dial-sub'>{isub}</div></div>",
                    unsafe_allow_html=True)
    with c3:
        ccol = _dial_color("confidence", conf)
        st.markdown(f"<div class='dial'><div class='dial-val' style='color:{ccol};'>{conf}</div>"
                    f"<div class='dial-label'>תזמון וויקוף (הקשר)</div>"
                    f"<div class='dial-sub'>{phase_he} · תזמון מפורט — במסלול טרייד</div></div>",
                    unsafe_allow_html=True)

    # --- העומק המלא (כאן זה המנה העיקרית, לא expander) ---
    st.markdown("<div class='section-label'>🏢 ניתוח ערך ואיכות — מטריצה, פילרים, עקביות, Reverse-DCF</div>",
                unsafe_allow_html=True)
    render_value_quality_detail(ticker, fd)

    if fd:
        try:
            bullets = build_fundamental_bullets(fd, ticker, current_phase=phase_he)
            if bullets:
                st.markdown("<div class='section-label'>🦅 ניתוח ערך — הנקודות המרכזיות</div>", unsafe_allow_html=True)
                st.markdown("\n".join(f"• {b}" for b in bullets))
        except Exception:
            pass
        with st.expander("📖 הסבר נוסף (ניתוח מלא ומלל חופשי)", expanded=False):
            try:
                st.markdown(build_fundamental_narrative(fd, ticker, invest_verdict, current_phase=phase_he))
            except Exception:
                st.caption("לא ניתן להפיק מלל מלא כרגע.")

    # --- הקשר תזמון (וויקוף) — שורה אחת + מעבר למסלול טרייד ---
    st.markdown(f"<div class='story-box'><div class='story-row'><span class='story-k'>⏱️ תזמון (הקשר)</span>"
                f"<span class='story-v'>{ws.get('bottom_line','—')} {timing_line}</span></div></div>",
                unsafe_allow_html=True)

    cta1, cta2 = st.columns(2)
    with cta1:
        if st.button("📊 ניתוח פונדמנטלי מלא (טבלת מכפילים)", use_container_width=True, key="home_to_fundamental_i"):
            go_to_screen("📊 ניתוח פונדמנטלי", ticker)
    with cta2:
        if st.button("⚡ לתזמון כניסה מפורט — מסלול טרייד", use_container_width=True, key="invest_to_trade_lens"):
            _set_analysis_lens(ticker, "trade")
            st.rerun()


def _render_home_fundamental_summary(ticker: str, cis_score: float, current_phase: str,
                                     display_phase: str = None) -> None:
    """
    השורה התחתונה האחידה במסך הבית: סינתזת Wyckoff + פונדמנטלי (ניתוח ערך).
    הבאנר חייב להופיע *תמיד* - גם אם שאיבת הנתונים הפונדמנטליים נכשלה (synthesize_verdict
    יודע להתמודד עם fund_data חסר ולהציג הודעה ניטרלית ברורה, ולא לדלג על הרכיב כליל).

    display_phase = הפאזה לתצוגה אחרי שכבת האימות (V20.4). כשהמנוע נתן תווית שאינה
    עקבית עם המבנה (כמו WULF), display_phase = 'אין פאזה מאושרת' — וזה מה שמוצג בצ'יפ
    ובנקודות, כדי לא להציג פאזה כפויה. לוגיקת ה-verdict עצמה נשארת על הפאזה הגולמית.
    """
    fdata = get_fundamental_data(ticker) or {}
    disp = display_phase or current_phase

    # V21.1: מקור אמת יחיד — גם טקסט ה-verdict משתמש בפאזה המבנית (disp), לא בגולמית.
    # התוויות המבניות מכילות את מילות-המפתח (SOS/Spring) כך שהסתעפות ה-verdict נשמרת;
    # 'אין פאזה מאושרת' נופל ל-verdict ניטרלי/זהיר — וזה הרצוי.
    verdict = synthesize_verdict(fdata, cis_score, disp, ticker)
    valuation = fdata.get("valuation", "-") if fdata else None
    pe_disp = (fdata.get('pe_forward') if fdata.get('pe_forward') != 'N/A' else fdata.get('pe_trailing', 'N/A')) if fdata else "N/A"

    render_verdict_banner(
        verdict, ticker=ticker, cis_score=cis_score, current_phase=disp,
        valuation=valuation, valuation_color=fdata.get("valuation_color", "#94a3b8"),
        extra_chips=([
            f"מכפיל רווח <b>{pe_disp}</b>",
            f"FCF <b>{fdata.get('fcf_yield', 'N/A')}</b>",
            f"צמיחה <b>{fdata.get('rev_growth', 'N/A')}</b>",
        ] if fdata else None),
    )

    if fdata:
        bullets = build_fundamental_bullets(fdata, ticker, current_phase=disp)
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


# ============================================================
# V27.1 — Parallel Scan Engine + חוויית המתנה (שעון ספירה לאחור)
# עיקרון: השליפות (צוואר הבקבוק) רצות במקביל (ThreadPool 10 workers) לחימום
# המטמון + early-pruning; ואז MarketScanner (הליבה, ללא שינוי) רץ מהיר על מטמון
# חם. הסריקה כולה רצה ב-thread רקע בזמן שה-main מציג שעון מתעדכן כל שנייה.
# אין תוצאות חלקיות — הכרטיסיות מופיעות רק בסוף (store→st.rerun, דפוס V25.7).
# ============================================================

def _fmt_mmss(sec: float) -> str:
    """פורמט M:SS לשעון (עמיד-כשל)."""
    try:
        s = max(0, int(round(sec)))
        return f"{s // 60}:{s % 60:02d}"
    except Exception:
        return "--:--"


def _scan_eta(status: dict) -> float:
    """
    זמן משוער שנותר (שניות) לפי התקדמות משוקללת בין השלבים:
    fetch (מקבילי) / scan (ליבה) / filter (אופציונלי). חישוב טהור וניתן לבדיקה.
    """
    try:
        w = status.get("weights") or {"fetch": 0.55, "scan": 0.45}
        frac = 0.0
        for stage, weight in w.items():
            tot = max(1, int(status.get(f"{stage}_total", 0) or 0))
            done = min(tot, int(status.get(f"{stage}_done", 0) or 0))
            frac += weight * (done / tot)
        frac = max(0.0, min(1.0, frac))
        elapsed = max(0.001, _time.time() - float(status.get("start_ts", _time.time())))
        if frac < 0.02:
            # אין עדיין מדגם — אומדן שמרני לפי גודל היקום (~0.35ש' לשליפה במקביל)
            tot = max(1, int(status.get("fetch_total", 200) or 200))
            return max(20.0, tot * 0.35)
        est_total = elapsed / frac
        return max(0.0, est_total - elapsed)
    except Exception:
        return 60.0


def _scan_progress_frac(status: dict) -> float:
    """שבר ההתקדמות הכולל (0..1) לפי אותם משקלים."""
    try:
        w = status.get("weights") or {"fetch": 0.55, "scan": 0.45}
        frac = 0.0
        for stage, weight in w.items():
            tot = max(1, int(status.get(f"{stage}_total", 0) or 0))
            done = min(tot, int(status.get(f"{stage}_done", 0) or 0))
            frac += weight * (done / tot)
        return max(0.0, min(1.0, frac))
    except Exception:
        return 0.0


def _parallel_prefetch(universe: list, status: dict, fetch_fn=None, workers: int = 10) -> list:
    """
    שלב 1 — חימום מטמון מקבילי + Early Pruning:
    ThreadPoolExecutor (ברירת מחדל 10 workers) מושך את הנתונים לכל טיקר במקביל
    (get_cached_data — נשמר במטמון, כך שהסריקה שאחריו פוגעת במטמון חם), ופוסל
    מוקדם טיקרים בלי נתונים תקינים (df ריק / <60 ברים) לפני ניתוח Wyckoff מלא.
    מחזיר את היקום המקוצץ. עמיד-כשל: טיקר שנכשל — מדולג.
    """
    ff = fetch_fn or get_cached_data
    status["fetch_total"] = len(universe)
    status["fetch_done"] = 0
    survivors = []

    # הצמדת ScriptRunContext ל-workers (מונע אזהרות Streamlit מתוך threads)
    try:
        from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
        _ctx = get_script_run_ctx()
    except Exception:
        add_script_run_ctx, _ctx = None, None

    def _init():
        if add_script_run_ctx and _ctx:
            try:
                add_script_run_ctx(threading.current_thread(), _ctx)
            except Exception:
                pass

    def _one(tk):
        try:
            df = ff(tk)
            ok = df is not None and not df.empty and len(df) >= 60
        except Exception:
            ok = False
        return tk, ok

    try:
        with ThreadPoolExecutor(max_workers=max(2, workers), initializer=_init) as ex:
            futs = {ex.submit(_one, tk): tk for tk in universe}
            for fut in as_completed(futs):
                try:
                    tk, ok = fut.result()
                except Exception:
                    tk, ok = futs[fut], False
                status["fetch_done"] = int(status.get("fetch_done", 0)) + 1
                status["ticker"] = tk
                if ok:
                    survivors.append(tk)
    except Exception:
        # נפילה חיננית: בלי מקביליות — היקום המלא ימשיך לסורק (מטמון קר)
        status["fetch_done"] = status["fetch_total"]
        return list(universe)
    # שמירת הסדר המקורי (דטרminיזם מול הסורק)
    keep = set(survivors)
    return [t for t in universe if t in keep]


def _scan_job(universe: list, top_n: int, status: dict, box: dict, do_filter=None) -> None:
    """
    עבודת הסריקה המלאה (רצה ב-thread רקע): prefetch מקבילי → MarketScanner (ליבה,
    מטמון חם) → סינון אופציונלי (סריקה ממוקדת). התוצאה/שגיאה נכתבת ל-box; ה-main
    thread מציג בינתיים שעון ספירה לאחור. אין נגיעה ב-UI מכאן (thread-safe).
    """
    try:
        pruned = _parallel_prefetch(universe, status, workers=10)
        status["scan_total"] = max(1, min(len(pruned), int(status.get("scan_cap", len(pruned)))))

        def _cb(done, total, ticker, stats):
            status["scan_total"] = max(1, int(total or 1))
            status["scan_done"] = int(done or 0)
            status["ticker"] = ticker
            try:
                status["passed"] = int(stats.get("passed", 0))
            except Exception:
                pass

        scanner = MarketScanner(_sc_module)
        out = scanner.scan_market(mode="balanced", max_tickers=len(pruned) or 1,
                                  universe=pruned, top_n=top_n, progress_callback=_cb)
        results = (out or {}).get("results", []) or []
        status["scan_done"] = status.get("scan_total", 1)
        if do_filter is not None:
            filtered = do_filter(results, status)
            box["results"] = results
            box["filtered"] = filtered
        else:
            box["results"] = results
    except Exception as exc:
        box["error"] = str(exc)
    finally:
        box["done"] = True


def _run_scan_with_countdown(universe: list, top_n: int, headline: str,
                             weights: dict = None, do_filter=None) -> dict:
    """
    מריץ סריקה מלאה ברקע ומציג בזמן אמת: הודעה גדולה, שעון "זמן משוער שנותר: M:SS"
    שמתעדכן כל שנייה, ו-progress bar באחוזים. חוסם עד סיום מלא — אין תוצאות חלקיות.
    מחזיר box: {"results":[...], "filtered":[...]? , "error":str?}.
    """
    status = {"start_ts": _time.time(),
              "weights": weights or {"fetch": 0.55, "scan": 0.45},
              "fetch_total": len(universe), "fetch_done": 0,
              "scan_total": 1, "scan_done": 0, "passed": 0, "ticker": ""}
    box = {"done": False}
    th = threading.Thread(target=_scan_job, args=(universe, top_n, status, box, do_filter),
                          daemon=True)
    th.start()

    _msg = st.empty()
    _clock = st.empty()
    _bar = st.progress(0.0)
    _sub = st.empty()
    _msg.markdown(
        f"<div style='text-align:center; padding:14px 8px 4px;'>"
        f"<div style='font-size:1.35rem; font-weight:800;'>🔎 {headline}</div>"
        f"<div style='color:#94a3b8; margin-top:4px;'>זה עלול לקחת 1-3 דקות — התוצאות יוצגו רק בסיום המלא.</div>"
        f"</div>", unsafe_allow_html=True)
    while not box.get("done"):
        frac = _scan_progress_frac(status)
        eta = _scan_eta(status)
        _clock.markdown(
            f"<div style='text-align:center; font-size:1.6rem; font-weight:800; "
            f"font-variant-numeric: tabular-nums; margin:2px 0 6px;'>"
            f"⏳ זמן משוער שנותר: {_fmt_mmss(eta)}</div>", unsafe_allow_html=True)
        try:
            _bar.progress(frac, text=f"{int(frac * 100)}%")
        except TypeError:
            _bar.progress(frac)
        stage_he = "מוריד נתונים במקביל (10 ערוצים)" if status.get("fetch_done", 0) < status.get("fetch_total", 0) \
            else "ניתוח Wyckoff + פונדמנטלי"
        _sub.caption(f"{stage_he} · {status.get('ticker','')} · עברו סינון: {status.get('passed', 0)}")
        _time.sleep(0.5)
    th.join(timeout=5)
    _msg.empty(); _clock.empty(); _bar.empty(); _sub.empty()
    return box


def _run_find_scan() -> None:
    """
    V27.1 — סריקת "תמצא לי": מנוע מקבילי (prefetch ב-10 ערוצים + Early Pruning)
    ברקע, בזמן שהמשתמש רואה הודעה גדולה + שעון ספירה לאחור מתעדכן כל שנייה +
    progress באחוזים. אין תוצאות חלקיות — הכרטיסיות מופיעות רק בסיום המלא.
    """
    _render_universe_status()
    universe = _build_market_universe()
    if not MARKET_SCANNER_AVAILABLE:
        st.error("מנוע הסריקה אינו זמין כרגע.")
        st.session_state.home_scan_results = []
        return
    st.session_state["scan_busy"] = True
    box = _run_scan_with_countdown(universe, top_n=20, headline="מבצע סריקת שוק מלאה...")
    st.session_state["scan_busy"] = False
    if box.get("error"):
        st.session_state.home_scan_results = []
        st.error(f"⚠️ שגיאה בסריקה: {box['error']}")
        return
    st.session_state.home_scan_results = box.get("results", [])
    st.session_state.scan_card_index = 0


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
        # V25.4/V27.0 — שורה שנייה: סריקה ממוקדת + רדאר סקטורים
        st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
        _f1, col_focus, _fmid, col_sect, _f2 = st.columns([1, 2, 0.4, 2, 1])
        with col_focus:
            st.markdown("<div class='orb-focus'>", unsafe_allow_html=True)
            if st.button("🎯\nסריקה ממוקדת", key="orb_focus_btn"):
                st.session_state.home_mode = "focused"
                st.rerun()
            st.markdown("</div><div class='home-orb-label'>סריקה ממוקדת</div>"
                        "<div class='home-orb-desc'>שלב פאזה · איכות · תמחור · סקטור — כל אחד 'הכל' או ספציפי</div>",
                        unsafe_allow_html=True)
        with col_sect:
            st.markdown("<div class='orb-sectors'>", unsafe_allow_html=True)
            if st.button("🌐\nרדאר סקטורים", key="orb_sectors_btn"):
                st.session_state.home_mode = "sectors"
                st.rerun()
            st.markdown("</div><div class='home-orb-label'>רדאר סקטורים</div>"
                        "<div class='home-orb-desc'>מי מתפוצץ, מי חוטף אש, מי רדום — Wyckoff + ערך לכל סקטור</div>",
                        unsafe_allow_html=True)
        return

    # ===================== מצב רדאר סקטורים (V27.0) =====================
    if mode == "sectors":
        _tl, _tr = st.columns([3, 1])
        with _tr:
            if st.button("⬅️ חזרה לתפריט", key="sectors_back_home", use_container_width=True):
                st.session_state.home_mode = "landing"
                st.rerun()
        st.markdown("### 🌐 רדאר סקטורים — מי מתפוצץ, מי חוטף אש, מי רדום")
        st.caption("Wyckoff מבני לכל סקטור דרך ETF מייצג (מקור האמת של המערכת) + תמחור לפי "
                   "מובילות הסקטור. הניתוח נשמר במטמון ~30 דק'.")
        if not MARKET_SCANNER_AVAILABLE:
            st.warning("מנוע הניתוח אינו זמין.")
            return
        b1, b2 = st.columns([2, 1])
        with b1:
            run_board = st.button("🌐 סרוק את כל הסקטורים", type="primary",
                                  use_container_width=True, key="sector_board_run")
        with b2:
            if st.button("↺ אפס", use_container_width=True, key="sector_board_reset"):
                for k in ("sector_board_rows", "sector_board_done", "sector_board_err"):
                    st.session_state.pop(k, None)
                st.rerun()

        if run_board:
            try:
                _pb = st.progress(0.0)
                _ps = st.empty()

                def _bcb(i, n, name):
                    try:
                        _pb.progress(min(1.0, i / max(1, n)))
                        _ps.caption(f"מנתח סקטור {i}/{n} · {name}")
                    except Exception:
                        pass

                with st.spinner("מנתח Wyckoff + תמחור לכל סקטור..."):
                    rows = _sector_board_rows(_map_sectors_dict(), progress_cb=_bcb)
                _pb.empty()
                _ps.empty()
                st.session_state["sector_board_rows"] = rows
                st.session_state["sector_board_done"] = True
                st.session_state.pop("sector_board_err", None)
            except Exception as exc:
                st.session_state["sector_board_rows"] = []
                st.session_state["sector_board_done"] = True
                st.session_state["sector_board_err"] = str(exc)
            st.rerun()  # רינדור נקי מה-state (דפוס V25.7 — בלי UI זמני מעל הלוח)

        if st.session_state.get("sector_board_done"):
            if st.session_state.get("sector_board_err"):
                st.error(f"⚠️ שגיאה: {st.session_state.pop('sector_board_err')}")
            rows = st.session_state.get("sector_board_rows") or []
            if not rows:
                st.info("לא התקבלו נתוני סקטורים — נסה שוב בעוד רגע (ייתכן עומס נתונים).")
            else:
                st.markdown(f"<div class='section-label'>🌐 {len(rows)} סקטורים · ממוין מהחם לקר</div>",
                            unsafe_allow_html=True)
                for r in rows:
                    h = r["heat"]
                    rd = r.get("readiness") or {}
                    _rdy = ""
                    if rd.get("applicable"):
                        _rdy = f" · {rd.get('emoji','')} {rd.get('label','')}"
                    _val = (f" · תמחור: <b>{r['valuation']}</b> (לפי {r['val_src']})"
                            if r.get("valuation") else "")
                    _note = f"<div class='sector-note'>💡 {h['note']}</div>" if h.get("note") else ""
                    c1, c2 = st.columns([4.2, 1])
                    with c1:
                        st.markdown(
                            f"<div class='sector-row' style='border-right: 4px solid {h['color']};'>"
                            f"<div class='sector-head'>{h['emoji']} <b>{r['sector']}</b> "
                            f"<span class='sector-etf'>({r['etf']})</span> — "
                            f"<span style='color:{h['color']}; font-weight:800;'>{h['he']}</span></div>"
                            f"<div class='sector-sub'>{r['phase_he']} · {r['days']} ימים בפאזה{_rdy}{_val}</div>"
                            f"{_note}</div>",
                            unsafe_allow_html=True)
                    with c2:
                        if st.button(f"📊 ניתוח ({r['etf']})", key=f"sect_full_{r['etf']}",
                                     use_container_width=True):
                            st.session_state.home_mode = "check"
                            go_to_screen("🏠 בית", r["etf"])
                st.caption("לחיצה על 'ניתוח' פותחת ניתוח מלא של ה-ETF המייצג (מסלול טרייד מלא; "
                           "בעדשת השקעה נתוני חברה בודדת לא רלוונטיים ל-ETF).")
        return

    # ===================== מצב סריקה ממוקדת (V25.4) =====================
    if mode == "focused":
        _tl, _tr = st.columns([3, 1])
        with _tr:
            if st.button("⬅️ חזרה לתפריט", key="focused_back_home", use_container_width=True,
                         disabled=st.session_state.get("scan_busy", False)):
                st.session_state.home_mode = "landing"
                st.rerun()
        st.markdown("### 🎯 סריקה ממוקדת")
        st.caption("סריקת שוק שמשלבת את כל המנועים. בחר בכל ציר 'הכל' או ערך ספציפי — יוצגו רק מניות "
                   "שעומדות בכל התנאים יחד. השארת כל הצירים על ברירת המחדל = סריקה כללית לגמרי.")
        _render_universe_status()

        if not MARKET_SCANNER_AVAILABLE:
            st.warning("מנוע הסריקה אינו זמין (חסר market_scanner.py או scout_core).")
            return

        MS = _map_sectors_dict()
        ALL = "— הכל —"
        _phases = ["ACC_BASE", "ACC_SPRING", "ACC_CONFIRM", "MARKUP",
                   "DIST_WARNING", "DIST_ACTIVE", "MARKDOWN"]

        c1, c2 = st.columns(2)
        with c1:
            phase_sel = st.selectbox("פאזת Wyckoff", [ALL] + _phases,
                                     format_func=lambda k: k if k == ALL else _WSTATES[k]["he"],
                                     key="focus_phase")
            sector_sel = st.selectbox("סקטור", [ALL] + list(MS.keys()), key="focus_sector")
        with c2:
            grade_sel = st.multiselect("איכות עסקית (A–F) · השאר ריק = הכל",
                                       ["A", "B", "C", "D", "F"], default=[], key="focus_grades")
            val_sel = st.multiselect("תמחור · השאר ריק = הכל",
                                     ["זול", "הוגן", "יקר"], default=[], key="focus_vals")

        sort_ready = st.checkbox("🚀 מיין לפי קרבה למהלך (הקרובים לפריצה קודם)",
                                 value=False, key="focus_sort_ready")

        # מיפוי בחירות → ארגומנטים (None = הכל)
        phase_state = None if phase_sel == ALL else phase_sel
        grade_set = set(grade_sel) if grade_sel else None
        valuation_set = set(val_sel) if val_sel else None
        if sector_sel == ALL:
            sector_tickers, scan_universe = None, _build_market_universe()
        else:
            sector_tickers = set(MS[sector_sel]["tickers"])
            scan_universe = MS[sector_sel]["tickers"]

        # שורת סיכום הפילטרים הפעילים
        _chips = [("פאזה", _WSTATES[phase_state]["he"] if phase_state else "הכל"),
                  ("איכות", "/".join(sorted(grade_set)) if grade_set else "הכל"),
                  ("תמחור", "/".join(valuation_set) if valuation_set else "הכל"),
                  ("סקטור", sector_sel if sector_sel != ALL else "הכל")]
        st.markdown(" ".join(f"<span class='fit-chip'>{k}: {v}</span>" for k, v in _chips),
                    unsafe_allow_html=True)

        b1, b2 = st.columns([2, 1])
        with b1:
            run_focus = st.button("🎯 הרץ סריקה ממוקדת", type="primary",
                                  use_container_width=True, key="focus_run",
                                  disabled=st.session_state.get("scan_busy", False))
        with b2:
            if st.button("↺ אפס הכל", use_container_width=True, key="focus_reset",
                         disabled=st.session_state.get("scan_busy", False)):
                for k in ("focus_phase", "focus_sector", "focus_grades", "focus_vals",
                          "focus_raw", "focus_raw_sector", "focus_done", "focus_filtered",
                          "focus_checked", "focus_applied_sig", "focus_card_index", "focus_error",
                          "focus_sort_ready"):
                    st.session_state.pop(k, None)
                st.rerun()

        # חתימת הפילטרים הנוכחית (לזיהוי אם המשתמש שינה בחירה מאז ההרצה האחרונה)
        _focus_sig = f"{phase_sel}|{sector_sel}|{','.join(sorted(grade_sel))}|{','.join(sorted(val_sel))}|{int(sort_ready)}"

        # === V25.7 FIX: סורקים *ומסננים* בלחיצה, שומרים תוצאות, ואז st.rerun() לרינדור
        # נקי — בדיוק כמו מסלול "תמצא לי". כך הקרוסלה לא מתרנדרת באותה ריצה עם
        # ה-spinner/progress הזמניים (שגרמו לה להבהב ולהיעלם). ===
        if run_focus:
            try:
                need_scan = (st.session_state.get("focus_raw") is None
                             or st.session_state.get("focus_raw_sector") != sector_sel)
                _checked_box = {"n": 0}

                def _do_filter(results, status):
                    """שלב הסינון רץ בתוך עבודת הרקע — השעון ממשיך לתקתק."""
                    status["filter_total"] = min(40, max(1, len(results)))
                    status["filter_done"] = 0

                    def _fcb(i, n, tk):
                        status["filter_total"] = max(1, int(n or 1))
                        status["filter_done"] = int(i or 0)
                        status["ticker"] = tk

                    flt, checked = _focused_filter(
                        results, phase_state=phase_state, grade_set=grade_set,
                        valuation_set=valuation_set, sector_tickers=sector_tickers,
                        cap=40, progress_cb=_fcb, attach_readiness=sort_ready)
                    _checked_box["n"] = checked
                    status["filter_done"] = status.get("filter_total", 1)
                    return flt

                st.session_state["scan_busy"] = True
                if need_scan:
                    box = _run_scan_with_countdown(
                        scan_universe, top_n=60, headline="מבצע סריקה ממוקדת מלאה...",
                        weights={"fetch": 0.5, "scan": 0.3, "filter": 0.2},
                        do_filter=_do_filter)
                    if box.get("error"):
                        raise RuntimeError(box["error"])
                    st.session_state["focus_raw"] = box.get("results", [])
                    st.session_state["focus_raw_sector"] = sector_sel
                    filtered = box.get("filtered", [])
                else:
                    # יקום כבר סרוק (מטמון) — רק סינון, עדיין דרך השעון (מהיר)
                    raw = st.session_state.get("focus_raw") or []
                    _status = {"start_ts": _time.time(),
                               "weights": {"filter": 1.0}, "filter_total": 1, "filter_done": 0}
                    filtered = _do_filter(raw, _status)
                st.session_state["scan_busy"] = False
                st.session_state["focus_filtered"] = filtered
                st.session_state["focus_checked"] = _checked_box["n"]
                st.session_state["focus_applied_sig"] = _focus_sig
                st.session_state["focus_card_index"] = 0
                st.session_state["focus_done"] = True
            except Exception as exc:
                st.session_state["scan_busy"] = False
                st.session_state["focus_filtered"] = []
                st.session_state["focus_checked"] = 0
                st.session_state["focus_applied_sig"] = _focus_sig
                st.session_state["focus_done"] = True
                st.session_state["focus_error"] = str(exc)
            st.rerun()  # ריצה מחדש נקייה — הקרוסלה תרונדר בלי UI זמני מעליה

        # --- רינדור מתוך ה-state בלבד (ללא סריקה/סינון כאן) ---
        if st.session_state.get("focus_done"):
            if st.session_state.get("focus_error"):
                st.error(f"⚠️ שגיאה בסריקה: {st.session_state.pop('focus_error')}")
            # אם המשתמש שינה פילטר מאז ההרצה — רמז עדין לרענן (התוצאות הן מההרצה הקודמת)
            if st.session_state.get("focus_applied_sig") != _focus_sig:
                st.info("שינית פילטר — לחץ '🎯 הרץ סריקה ממוקדת' כדי לעדכן את התוצאות.")
            filtered = st.session_state.get("focus_filtered") or []
            checked = st.session_state.get("focus_checked", 0)
            st.markdown(f"<div class='section-label'>🎯 נמצאו {len(filtered)} מניות "
                        f"({checked} נבדקו מבנית)</div>", unsafe_allow_html=True)
            if not filtered:
                st.info("אין מניות שעומדות בכל התנאים יחד. נסה לרכך ציר אחד "
                        "(למשל 'הכל' באיכות או בפאזה), או לבחור סקטור אחר.")
            else:
                _render_card_carousel(filtered, key_prefix="focus",
                                      index_key="focus_card_index", dest_page="🏠 בית")
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
        # V25.2 fix: איפוס העדשה בכל הרצת ניתוח *חדשה* — כך מסך בחירת המסלול (⚡/🏦)
        # תמיד מופיע אחרי "הרץ ניתוח". החלפת מסלול (rerun ללא run_clicked) שומרת על הבחירה.
        st.session_state.pop("analysis_lens", None)
        st.session_state.pop("analysis_lens_ticker", None)

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

        # === V20.2: רצועת סטטוס נתונים (טריות מחיר + רבעון אחרון + אזהרות) ===
        _home_fdata = get_fundamental_data(ticker) or {}
        render_data_status(ticker, result["df"], _home_fdata, result.get("freshness"))

        # === V25.0: פיצול מסלולים — המשתמש בוחר עדשה (טרייד/השקעה) לפני הניתוח ===
        _lens = _get_analysis_lens(ticker)
        if _lens is None:
            _render_lens_chooser(ticker)
            return
        if _lens == "invest":
            _render_lens_switch("invest", ticker)
            render_invest_lens(ticker, result)
            return
        _render_lens_switch("trade", ticker)

        # === מסלול טרייד: שורה תחתונה + 3 חיוגים + הסיפור העקבי (V21.0) ===
        render_structural_summary(ticker, result)

        # === V22.0: ניתוח ערך ואיכות (הקשר החזקה) — expander ===
        with st.expander("🏢 ניתוח ערך ואיכות — מטריצה, פילרי איכות, Reverse-DCF", expanded=False):
            render_value_quality_detail(ticker, get_fundamental_data(ticker) or {})

        # V25.0: הבאנר הפונדמנטלי הוסר מהמסלול הזה — הוא ערבב שווי ארוך-טווח לתוך מסך
        # תזמון ("סכין נופלת"/"ביטחון גבוה" מול חיוג 46). מסקנות השקעה — במסלול ההשקעה.
        _c1, _c2, _c3 = st.columns([1, 1, 1.4])
        with _c1:
            if st.button("🎯 קבל אסטרטגיית מסחר", type="primary", use_container_width=True, key="home_to_strategy"):
                go_to_screen("📈 Trading Scout", ticker)
        with _c2:
            if st.button("📊 ניתוח פונדמנטלי מלא", use_container_width=True, key="home_to_fundamental"):
                go_to_screen("📊 ניתוח פונדמנטלי", ticker)
        with _c3:
            st.caption("מסקנות השקעה ארוכת טווח — במסלול ההשקעה (🔄 למעלה) או במסך הפונדמנטלי המלא.")

        # === V20.2: מה אומר הציון + למה הפאזה הזו (בולט, לא קבור ב-expander) ===
        st.markdown("<div class='section-label'>🧭 מה אומר הציון, ולמה הפאזה הזו</div>", unsafe_allow_html=True)
        render_cis_meaning(result["current_cis"], result["factors"], result["display_phase"])
        render_phase_evidence(result, ticker)

        # === V20.3: ניתוח Wyckoff מעמיק — TR / אירועים / VSA / Cause & Effect (expander) ===
        with st.expander("🔬 ניתוח Wyckoff מעמיק — טווח מסחר, אירועים, VSA, יעדי Cause & Effect", expanded=False):
            render_wyckoff_deep_analysis(ticker, result)

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
                cp = result["display_phase"]
                pstatus = result.get("phase_status", "confirmed")
                wait_note = result.get("phase_refine_note", "")
                # כשאין פאזה מאושרת — אומרים זאת מפורשות ולא כופים שלב על הסקאלה
                if pstatus in ("transition", "caution"):
                    if pstatus == "caution":
                        st.warning("⚠️ **אין פאזה מאושרת.** שכבת האימות מזהה תיקון/הפצה בנפח גבוה — לא איסוף חוזר רגוע.")
                    else:
                        st.info("ℹ️ **אין שלב Wyckoff מאושר כרגע.** זהו מצב מעבר בין פאזות — המערכת לא כופה התאמה.")
                    if wait_note:
                        accent = "#ef4444" if pstatus == "caution" else "#f59e0b"
                        st.markdown(
                            f"<div style='border-right:4px solid {accent}; background:rgba(148,163,184,0.06); "
                            f"padding:12px 14px; border-radius:10px; line-height:1.75; margin-top:8px; color:#e2e8f0;'>"
                            f"{wait_note}</div>",
                            unsafe_allow_html=True,
                        )
                    st.caption(f"**זיהוי גולמי של המנוע:** `{result['current_phase']}` · **תצוגה:** `{cp}`")
                elif any(x in cp for x in ["TRANSITION", "UNCERTAIN", "לא בתהליך"]):
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



def _map_sectors_dict() -> dict:
    """
    V27.0 — מפת סקטורים גרנולרית (20 קבוצות) ממופה מהיקום המובנה (S&P500+NDX100).
    מבנה כל ערך: tickers (חברי הסקטור מהיקום), desc, ולסקטורים עם ETF נזיל:
    etf (פרוקסי ל-Wyckoff סקטוריאלי) + leaders (2 מובילות לתמחור מייצג).
    משמש את הסריקה הממוקדת (ציר סקטור) ואת רדאר הסקטורים במסך הבית.
    """
    S = lambda s: s.split()
    MAP_SECTORS = {
        "שבבים ומוליכים למחצה": {
            "etf": "SMH", "leaders": ["NVDA", "AVGO"],
            "tickers": S("NVDA AVGO AMD INTC QCOM TXN ADI MU LRCX KLAC AMAT NXPI MCHP ON "
                         "MPWR TER SWKS MRVL FSLR ENPH"),
            "desc": "יצרניות שבבים, ציוד ייצור ואנרגיה סולארית-טכנולוגית"},
        "תוכנה, ענן וסייבר": {
            "etf": "IGV", "leaders": ["MSFT", "CRM"],
            "tickers": S("MSFT ORCL ADBE CRM NOW INTU SNPS CDNS ADSK WDAY PANW CRWD FTNT ZS "
                         "GEN ANSS PLTR SNOW DDOG TEAM MDB NET AKAM PAYC DAY ROP IT CTSH ACN IBM"),
            "desc": "תוכנה ארגונית, ענן, סייבר ושירותי IT"},
        "חומרה, רשתות ותשתית IT": {
            "etf": "XLK", "leaders": ["AAPL", "CSCO"],
            "tickers": S("AAPL CSCO ANET APH MSI TEL HPQ HPE DELL TDY GLW KEYS CDW ZBRA STX "
                         "WDC NTAP JNPR FFIV TRMB JBL SMCI"),
            "desc": "חומרה, רשתות, אחסון ותשתיות מחשוב"},
        "תקשורת, מדיה ואינטרנט": {
            "etf": "XLC", "leaders": ["GOOGL", "META"],
            "tickers": S("GOOGL GOOG META NFLX CMCSA DIS T VZ TMUS CHTR WBD EA TTWO OMC IPG "
                         "LYV MTCH PINS SNAP RBLX ROKU PARA FOXA FOX NWSA NWS"),
            "desc": "פלטפורמות אינטרנט, סטרימינג, טלקום ומדיה"},
        "בנקים גדולים ושוקי הון": {
            "etf": "XLF", "leaders": ["JPM", "GS"],
            "tickers": S("BRK-B JPM BAC WFC C GS MS BK STT NTRS SPGI BLK SCHW ICE CME MCO "
                         "MSCI NDAQ CBOE MKTX AMP RJF IVZ BEN FDS"),
            "desc": "בנקי ענק, בתי השקעות, בורסות וניהול נכסים"},
        "בנקים אזוריים וקטנים": {
            "etf": "KRE", "leaders": ["USB", "PNC"],
            "tickers": S("USB PNC TFC FITB RF MTB HBAN CFG KEY ZION"),
            "desc": "בנקים אזוריים — רגישים לריבית ולאשראי מקומי"},
        "ביטוח": {
            "etf": "KIE", "leaders": ["PGR", "CB"],
            "tickers": S("PGR CB MMC AON AJG AFL MET TRV ALL AIG PRU HIG WTW CINF L GL ACGL "
                         "WRB EG BRO PFG"),
            "desc": "מבטחות, ברוקרים וביטוח-משנה"},
        "תשלומים ופינטק": {
            "etf": "IPAY", "leaders": ["V", "MA"],
            "tickers": S("V MA AXP PYPL FI FIS GPN DFS SYF CPAY JKHY COF"),
            "desc": "רשתות תשלום, כרטיסי אשראי וטכנולוגיה פיננסית"},
        "ביוטק": {
            "etf": "XBI", "leaders": ["VRTX", "REGN"],
            "tickers": S("AMGN GILD VRTX REGN BIIB MRNA"),
            "desc": "ביוטכנולוגיה — פיתוח תרופות חדשניות"},
        "בריאות — תרופות, מכשור ושירותים": {
            "etf": "XLV", "leaders": ["LLY", "UNH"],
            "tickers": S("UNH JNJ LLY ABBV MRK TMO ABT DHR PFE ISRG SYK BSX MDT CI ZTS BDX "
                         "HCA ELV CVS MCK COR HUM CNC IDXX IQV A GEHC RMD DXCM EW MTD WAT WST "
                         "ALGN ZBH STE HOLX BAX COO PODD TFX RVTY MOH UHS DVA CTLT TECH CRL "
                         "LH DGX VTRS BMY"),
            "desc": "פארמה גדולה, מכשור רפואי, ביטוחי בריאות ושירותים"},
        "אנרגיה — נפט וגז": {
            "etf": "XLE", "leaders": ["XOM", "CVX"],
            "tickers": S("XOM CVX COP SLB EOG MPC PSX WMB OKE VLO OXY HES KMI FANG BKR HAL "
                         "DVN TRGP CTRA MRO APA EQT TPL"),
            "desc": "הפקה, זיקוק, צנרת ושירותי נפט וגז"},
        "תשתיות חשמל ומים": {
            "etf": "XLU", "leaders": ["NEE", "SO"],
            "tickers": S("NEE DUK SO D AEP SRE EXC XEL PEG ED WEC PCG EIX AWK DTE ETR AEE PPL "
                         "FE CMS ATO CNP NI LNT EVRG AES PNW NRG CEG VST"),
            "desc": "חברות חשמל, מים ותשתיות — כולל ספקיות AI-power"},
        "נדל\"ן מניב (REITs)": {
            "etf": "XLRE", "leaders": ["PLD", "AMT"],
            "tickers": S("PLD AMT EQIX WELL SPG PSA O CCI DLR CBRE EXR VICI AVB SBAC EQR IRM "
                         "WY INVH ARE MAA ESS KIM UDR DOC HST REG CPT BXP FRT"),
            "desc": "נדל\"ן מניב — לוגיסטיקה, דאטה-סנטרים, מגורים ומסחר"},
        "תעופה וביטחוניות": {
            "etf": "ITA", "leaders": ["RTX", "LMT"],
            "tickers": S("BA GE RTX LMT NOC GD LHX TDG HWM AXON TXT"),
            "desc": "ביטחוניות, תעופה ומנועים"},
        "תעשייה ותחבורה": {
            "etf": "XLI", "leaders": ["CAT", "UNP"],
            "tickers": S("CAT HON UNP DE ETN UPS ADP MMM ITW CSX EMR FDX NSC WM PH TT CTAS "
                         "PCAR GEV CARR OTIS CMI PAYX FAST RSG AME ROK ODFL DAL UAL LUV VRSK "
                         "EFX IR DOV XYL WAB FTV GWW URI PWR BR JCI SNA SWK IEX NDSN PNR ALLE "
                         "ROL GNRC HUBB CHRW J AOS EXPD VLTO CPRT LII"),
            "desc": "מכונות, רכבות, שילוח, תעופה אזרחית ושירותי תעשייה"},
        "בנייה למגורים": {
            "etf": "ITB", "leaders": ["DHI", "LEN"],
            "tickers": S("DHI LEN NVR PHM BLDR MAS MHK"),
            "desc": "קבלני מגורים וחומרי בנייה — רגישים לריבית המשכנתאות"},
        "צריכה בסיסית": {
            "etf": "XLP", "leaders": ["PG", "COST"],
            "tickers": S("PG KO PEP COST WMT PM MO MDLZ CL KMB GIS KHC STZ MNST KDP HSY SYY "
                         "ADM KR MKC CHD CLX TAP TSN CAG HRL SJM CPB K BG BF-B EL LW KVUE WBA"),
            "desc": "מזון, משקאות, טואלטיקה וקמעונאות בסיסית — דפנסיבי"},
        "קמעונאות, מסעדות ופנאי": {
            "etf": "XLY", "leaders": ["AMZN", "HD"],
            "tickers": S("AMZN HD MCD NKE LOW SBUX TJX ORLY CMG MAR HLT LULU ROST YUM AZO "
                         "GRMN DRI GPC KMX LKQ MGM WYNN CZR LVS NCLH RCL CCL POOL TSCO ULTA "
                         "BBY DECK TPR RL HAS WHR DPZ DG DLTR TGT CROX ABNB UBER LYFT DASH "
                         "EXPE BKNG TRIP EBAY ETSY W"),
            "desc": "צריכה מחזורית — קמעונאות, מסעדות, מלונאות, נסיעות ופנאי"},
        "רכב וניידות": {
            "leaders": ["TSLA", "GM"],
            "tickers": S("TSLA GM F RIVN APTV BWA"),
            "desc": "יצרניות רכב, EV וספקיות רכיבים (ללא ETF ייעודי בלוח)"},
        "חומרים וכימיקלים": {
            "etf": "XLB", "leaders": ["LIN", "SHW"],
            "tickers": S("LIN SHW APD ECL DOW DD PPG CTVA IFF ALB CF MOS CE FMC VMC MLM PKG "
                         "IP AMCR AVY BALL SW"),
            "desc": "כימיקלים, גזים תעשייתיים, אגרו וחומרי אריזה"},
        "מתכות יקרות וכרייה": {
            "etf": "GDX", "leaders": ["NEM", "FCX"],
            "tickers": S("NEM FCX NUE STLD"),
            "desc": "מכרות זהב/כסף/נחושת, פלדה וסחורות מתכת"},
    }
    # מיזוג רשימת הסחורות של האפליקציה (GLD/SLV/IAU/מכרות) לסקטור המתכות
    try:
        MAP_SECTORS["מתכות יקרות וכרייה"]["tickers"] = list(dict.fromkeys(
            MAP_SECTORS["מתכות יקרות וכרייה"]["tickers"] + list(COMMODITIES_TICKERS)))
    except Exception:
        pass
    for _sec, _v in MAP_SECTORS.items():
        _v["tickers"] = list(dict.fromkeys([t for t in _v["tickers"] if t and isinstance(t, str)]))
    return MAP_SECTORS


def _sector_heat(state: str, caution: bool, valuation: str = "") -> dict:
    """
    V27.0 — מסווג 'חום' סקטוריאלי: מצב FSM ⇒ דלי מילולי חד-משמעי להדיוט.
    order = לצורכי מיון הלוח בלבד (חם→קר). טהור, ללא ציונים מספריים.
    """
    table = {
        "MARKUP":       ("🚀", "מתפוצץ — במהלך עלייה", 0, "#16a34a"),
        "ACC_CONFIRM":  ("🟢", "הזדמנות — קרוב לפריצה", 1, "#22c55e"),
        "ACC_SPRING":   ("🌱", "איסוף — ניעור בתחתית", 2, "#84cc16"),
        "ACC_BASE":     ("🌱", "איסוף מוקדם — בונה בסיס", 3, "#a3e635"),
        "UNDETERMINED": ("😴", "רדום — אין מבנה ברור", 4, "#94a3b8"),
        "DIST_WARNING": ("⚠️", "סכנה — סימני הפצה", 5, "#f59e0b"),
        "DIST_ACTIVE":  ("🔻", "הפצה פעילה — הימנע", 6, "#f97316"),
        "MARKDOWN":     ("🔥", "חוטף אש — מגמת ירידה", 7, "#ef4444"),
    }
    emoji, he, order, color = table.get(state, table["UNDETERMINED"])
    if state == "ACC_CONFIRM" and caution:
        emoji, he, order, color = "🟡", "הזדמנות בזהירות — תיקון בשלב D", 2, "#eab308"
    note = ""
    if order <= 3 and "זול" in (valuation or ""):
        note = "תמחור זול במובילות = הזדמנות ערך"
    elif order >= 5 and "יקר" in (valuation or ""):
        note = "גם יקר וגם מבנה שלילי — זהירות כפולה"
    return {"emoji": emoji, "he": he, "order": order, "color": color, "note": note}


def _sector_board_rows(sectors: dict, quick_fn=None, fund_fn=None, progress_cb=None) -> list:
    """
    V27.0 — מנוע לוח הרדאר: לכל סקטור עם ETF — Wyckoff מבני על ה-ETF (מקור האמת
    היחיד, cache ~30ד') + תמחור לפי מובילות הסקטור. טהור (הזרקת פונקציות), עמיד-כשל.
    מחזיר שורות ממוינות מהחם לקר.
    """
    qf = quick_fn or _quick_structural_state
    ff = fund_fn or get_fundamental_data
    items = [(n, d) for n, d in (sectors or {}).items() if d.get("etf")]
    rows = []
    for i, (name, d) in enumerate(items):
        if progress_cb:
            try:
                progress_cb(i + 1, len(items), name)
            except Exception:
                pass
        try:
            qs = qf(d["etf"]) or {}
        except Exception:
            qs = {}
        if not qs.get("phase_he"):
            continue
        val, vsrc = "", ""
        for ld in (d.get("leaders") or [])[:2]:
            try:
                fd = ff(ld) or {}
                if fd.get("valuation"):
                    val, vsrc = fd["valuation"], ld
                    break
            except Exception:
                continue
        heat = _sector_heat(qs.get("state", ""), bool(qs.get("caution")), val)
        rows.append({"sector": name, "etf": d["etf"], "desc": d.get("desc", ""),
                     "phase_he": qs.get("phase_he", ""), "days": int(qs.get("days_in_phase", 0) or 0),
                     "readiness": qs.get("readiness") or {}, "heat": heat,
                     "valuation": val, "val_src": vsrc})
    rows.sort(key=lambda r: (r["heat"]["order"], -r["days"]))
    return rows


# ============================================================
# V25.6 — יקום מובנה: S&P 500 + Nasdaq 100 (~500 מניות ייחודיות)
# רשימה קבועה מוטמעת (ללא קובץ/סקריפט). ממוזגת אוטומטית ליקום הסריקה, כך
# ששלושת המסלולים (תמצא לי / סורק טכני / סריקה ממוקדת) מכסים כמעט את כל שווי
# השוק האמריקאי. סמלים במבנה תואם-yfinance (למשל BRK-B, BF-B). טיקר שהוסר/
# שונה — פשוט מדולג חינני בשליפה. אם יועלה nasdaq_universe.json הוא ימוזג מעל זה.
# ============================================================
SP500_NDX100_TICKERS = [
    # --- Mega / large-cap tech + communication ---
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "AVGO", "TSLA", "ORCL",
    "ADBE", "CRM", "CSCO", "ACN", "AMD", "INTC", "IBM", "QCOM", "TXN", "INTU",
    "NOW", "AMAT", "ADI", "MU", "LRCX", "KLAC", "SNPS", "CDNS", "ANET", "PANW",
    "CRWD", "FTNT", "ROP", "APH", "MSI", "ADSK", "NXPI", "MCHP", "TEL", "IT",
    "CTSH", "HPQ", "HPE", "DELL", "WDAY", "TDY", "GLW", "KEYS", "ON", "FSLR",
    "MPWR", "CDW", "ANSS", "TER", "ZBRA", "SWKS", "STX", "WDC", "NTAP", "JNPR",
    "AKAM", "FFIV", "TRMB", "GEN", "JBL", "SMCI", "ENPH", "PLTR", "SNOW", "DDOG",
    "TEAM", "ZS", "MDB", "NET", "PANW", "WDAY", "MRVL",
    # --- Communication services / media / internet ---
    "NFLX", "CMCSA", "DIS", "T", "VZ", "TMUS", "CHTR", "WBD", "EA", "TTWO",
    "OMC", "IPG", "LYV", "MTCH", "PINS", "SNAP", "RBLX", "ROKU", "PARA", "FOXA",
    "FOX", "NWSA", "NWS", "ABNB", "UBER", "LYFT", "DASH", "EXPE", "BKNG", "TRIP",
    # --- Consumer discretionary / retail ---
    "HD", "MCD", "NKE", "LOW", "SBUX", "TJX", "BKNG", "ORLY", "CMG", "MAR",
    "HLT", "GM", "F", "RIVN", "LULU", "ROST", "YUM", "AZO", "DHI", "LEN",
    "NVR", "PHM", "GRMN", "APTV", "BWA", "DRI", "EBAY", "ETSY", "GPC", "KMX",
    "LKQ", "MGM", "WYNN", "CZR", "LVS", "NCLH", "RCL", "CCL", "POOL", "TSCO",
    "ULTA", "BBY", "DECK", "TPR", "RL", "HAS", "MHK", "WHR", "DPZ", "DG",
    "DLTR", "TGT", "W", "CROX",
    # --- Consumer staples ---
    "PG", "KO", "PEP", "COST", "WMT", "PM", "MO", "MDLZ", "CL", "KMB",
    "GIS", "KHC", "STZ", "MNST", "KDP", "HSY", "SYY", "ADM", "KR", "MKC",
    "CHD", "CLX", "TAP", "TSN", "CAG", "HRL", "SJM", "CPB", "K", "BG",
    "BF-B", "EL", "LW", "DG", "KVUE", "WBA",
    # --- Health care ---
    "UNH", "JNJ", "LLY", "ABBV", "MRK", "TMO", "ABT", "DHR", "PFE", "AMGN",
    "ISRG", "SYK", "BSX", "MDT", "GILD", "VRTX", "REGN", "CI", "ZTS", "BDX",
    "HCA", "ELV", "CVS", "MCK", "COR", "HUM", "CNC", "BIIB", "IDXX", "IQV",
    "A", "GEHC", "RMD", "DXCM", "MRNA", "EW", "MTD", "WAT", "WST", "ALGN",
    "ZBH", "STE", "HOLX", "BAX", "COO", "PODD", "TFX", "RVTY", "MOH", "UHS",
    "DVA", "CTLT", "TECH", "CRL", "LH", "DGX", "VTRS", "BMY",
    # --- Financials ---
    "BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "AXP", "SPGI",
    "BLK", "C", "SCHW", "PGR", "CB", "MMC", "FI", "PYPL", "ICE", "CME",
    "AON", "USB", "PNC", "AJG", "MCO", "TFC", "COF", "AFL", "MET", "TRV",
    "ALL", "BK", "AIG", "PRU", "MSCI", "AMP", "FIS", "GPN", "DFS", "NDAQ",
    "STT", "HIG", "WTW", "FITB", "RF", "CINF", "MTB", "HBAN", "CFG", "KEY",
    "NTRS", "SYF", "BRO", "PFG", "L", "GL", "RJF", "IVZ", "CBOE", "MKTX",
    "ACGL", "WRB", "EG", "FDS", "JKHY", "BEN", "ZION", "CPAY",
    # --- Industrials ---
    "GE", "CAT", "RTX", "HON", "UNP", "BA", "LMT", "DE", "ETN", "UPS",
    "ADP", "GD", "NOC", "MMM", "ITW", "CSX", "EMR", "FDX", "NSC", "WM",
    "PH", "TT", "CTAS", "PCAR", "GEV", "CARR", "OTIS", "CMI", "PAYX", "FAST",
    "RSG", "AME", "ROK", "ODFL", "DAL", "UAL", "LUV", "VRSK", "EFX", "IR",
    "DOV", "XYL", "HWM", "WAB", "FTV", "LHX", "TDG", "GWW", "URI", "PWR",
    "AXON", "BR", "JCI", "SNA", "SWK", "IEX", "NDSN", "EMN", "PNR", "ALLE",
    "MAS", "ROL", "GNRC", "HUBB", "DAY", "CHRW", "J", "TXT", "AOS", "PAYC",
    "EXPD", "VLTO", "CPRT", "LII", "BLDR",
    # --- Energy ---
    "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "WMB", "OKE", "VLO",
    "OXY", "HES", "KMI", "FANG", "BKR", "HAL", "DVN", "TRGP", "CTRA", "MRO",
    "APA", "EQT", "TPL",
    # --- Utilities ---
    "NEE", "DUK", "SO", "D", "AEP", "SRE", "EXC", "XEL", "PEG", "ED",
    "WEC", "PCG", "EIX", "AWK", "DTE", "ETR", "AEE", "PPL", "FE", "CMS",
    "ATO", "CNP", "NI", "LNT", "EVRG", "AES", "PNW", "NRG", "CEG", "VST",
    # --- Materials ---
    "LIN", "SHW", "APD", "ECL", "FCX", "NUE", "NEM", "DOW", "DD", "PPG",
    "CTVA", "VMC", "MLM", "IFF", "ALB", "PKG", "IP", "AMCR", "AVY", "CF",
    "STLD", "NDSN", "BALL", "MOS", "CE", "EMN", "FMC", "SW",
    # --- Real estate (REITs) ---
    "PLD", "AMT", "EQIX", "WELL", "SPG", "PSA", "O", "CCI", "DLR", "CBRE",
    "EXR", "VICI", "AVB", "SBAC", "EQR", "IRM", "WY", "INVH", "ARE", "MAA",
    "ESS", "KIM", "UDR", "DOC", "HST", "REG", "CPT", "BXP", "FRT",
]


_UNIVERSE_JSON_CANDIDATES = ("nasdaq_universe.json",)


def _universe_json_path():
    """מאתר את קובץ היקום ליד app.py או בתיקיית העבודה."""
    bases = []
    try:
        bases.append(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass
    bases.append(os.getcwd())
    for b in bases:
        for name in _UNIVERSE_JSON_CANDIDATES:
            p = os.path.join(b, name)
            if os.path.exists(p):
                return p
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def _load_universe_file():
    """
    טוען את קובץ היקום המסונן (nasdaq_universe.json) אם קיים ותקין.
    מחזיר (tickers, meta) או (None, None). עמיד-כשל לחלוטין.
    """
    try:
        p = _universe_json_path()
        if not p:
            return None, None
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        tickers = [str(t).strip().upper() for t in data.get("tickers", [])
                   if t and isinstance(t, str)]
        tickers = [t for t in tickers if t]
        if len(tickers) < 20:            # קובץ ריק/פגום → נפילה ליקום האצור
            return None, None
        gen = str(data.get("generated_at", ""))
        age_days = None
        try:
            age_days = (datetime.now() - datetime.strptime(gen, "%Y-%m-%d")).days
        except Exception:
            age_days = None
        meta = {"generated_at": gen, "count": len(tickers), "age_days": age_days,
                "criteria": data.get("criteria", {})}
        return tickers, meta
    except Exception:
        return None, None


def _curated_fallback_universe() -> list:
    """
    יקום ברירת המחדל המובנה: S&P 500 + Nasdaq 100 (~500) + רשימות האפליקציה
    (צמיחה/ערך/סחורות) + היקום הדיפולטי של הסורק. ללא קובץ חיצוני. אם יועלה
    nasdaq_universe.json — הוא ימוזג מעל זה (ב-_build_market_universe).
    """
    universe = list(SP500_NDX100_TICKERS)
    for lst in (GROWTH_TICKERS, VALUE_TICKERS, COMMODITIES_TICKERS):
        for t in lst:
            universe.append(t)
    try:
        from market_scanner import DEFAULT_UNIVERSE
        universe.extend(DEFAULT_UNIVERSE)
    except Exception:
        pass
    seen = set()
    return [t for t in universe if t and not (t in seen or seen.add(t))]


def _build_market_universe() -> list:
    """
    יקום הסריקה (משותף לשלושת המסלולים: 'תמצא לי', סורק טכני, סריקה ממוקדת).
    אם קיים nasdaq_universe.json (מסונן offline ע"י build_universe.py לפי מחיר/שווי/
    ווליום) — משתמשים בו, ממוזג עם היקום האצור (כדי לא לאבד סחורות/ETF שאינם בנאסד"ק).
    אחרת — נופלים ליקום האצור (~146). לעולם לא קורס.
    """
    tickers, _meta = _load_universe_file()
    base = _curated_fallback_universe()
    if tickers:
        seen = set()
        return [t for t in (tickers + base) if not (t in seen or seen.add(t))]
    return base


def _universe_meta() -> dict:
    """מטא-דאטה של קובץ היקום (לתצוגת חותמת תאריך + אזהרת התיישנות)."""
    _t, meta = _load_universe_file()
    return meta or {}


def _render_universe_status() -> None:
    """שורת סטטוס יקום: מקור + תאריך עדכון + אזהרה אם הקובץ ישן מ-14 יום."""
    meta = _universe_meta()
    if not meta:
        _n = len(_curated_fallback_universe())
        st.caption(f"🔭 יקום סריקה: {_n} מניות מובנות (S&P 500 + Nasdaq 100 + רשימות האפליקציה). "
                   "לכיסוי דינמי של כל נאסד\"ק המסונן — אפשר להעלות nasdaq_universe.json לצד app.py.")
        return
    n = meta.get("count", 0)
    gen = meta.get("generated_at", "—")
    age = meta.get("age_days")
    if age is not None and age > 14:
        st.warning(f"🔭 יקום סריקה: {n} מניות (נאסד\"ק מסונן + אצור) · עודכן {gen} "
                   f"— לפני {age} ימים. מומלץ לרענן (הרץ build_universe.py) — הרשימה עלולה "
                   f"להיות מיושנת. הניתוח עצמו תמיד נשלף חי ואינו מושפע.")
    else:
        _age_txt = f" · לפני {age} ימים" if age is not None else ""
        st.caption(f"🔭 יקום סריקה: {n} מניות (נאסד\"ק מסונן + אצור) · עודכן {gen}{_age_txt}.")


def _render_market_scanner() -> None:
    """מנוע סריקת שוק עם Early Pruning - סריקה ידנית, progress bar וזמן משוער."""
    st.markdown("#### 🔭 סורק שוק רחב (Market Scanner + Early Pruning)")
    st.caption("סורק מאות מניות במהירות בעזרת גיזום מוקדם: מסנן קודם לפי מחיר/נפח, אז לפי קווים אדומים של Wyckoff, ורק מי ששרד עובר ניתוח פונדמנטלי מלא. מחזיר רק שילובים חזקים.")

    if not MARKET_SCANNER_AVAILABLE:
        st.warning("מנוע הסריקה אינו זמין (חסר market_scanner.py או scout_core).")
        return

    _render_universe_status()

    # === V25.3: שני מסלולי סריקה טכנית — כללית / לפי פאזת Wyckoff (נפרד מחיפוש הערך בבית) ===
    scan_type = st.radio(
        "סוג סריקה",
        options=["general", "phase"],
        format_func=lambda k: "🔍 סריקה כללית" if k == "general" else "🎯 סריקה לפי פאזת Wyckoff",
        key="market_scan_type",
        horizontal=True,
    )
    target_state = None
    if scan_type == "phase":
        _phase_opts = ["ACC_BASE", "ACC_SPRING", "ACC_CONFIRM", "MARKUP",
                       "DIST_WARNING", "DIST_ACTIVE", "MARKDOWN"]
        target_state = st.selectbox(
            "בחר את הפאזה שאתה מחפש",
            options=_phase_opts,
            format_func=lambda k: _WSTATES[k]["he"],
            key="market_scan_phase",
        )
        st.caption("הסריקה רצה כרגיל, ואז כל מועמד מאומת מול המנוע המבני (FSM) — יוצגו רק מניות "
                   "שנמצאות *כרגע* בפאזה שבחרת. החלפת פאזה אחרי סריקה מסננת מיידית, בלי סריקה חוזרת.")

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
                    top_n=(40 if scan_type == "phase" else 20), progress_callback=_cb,
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
        elif scan_type == "phase" and target_state:
            # === V25.3: סינון מבני לפי הפאזה שנבחרה (מקור אמת יחיד — FSM) ===
            _plabel = _WSTATES[target_state]["he"]
            _pb = st.progress(0.0)
            _ps = st.empty()

            def _fsm_cb(i, n, tk):
                try:
                    _pb.progress(min(1.0, i / max(1, n)))
                    _ps.caption(f"מאמת פאזה מבנית {i}/{n} · {tk}")
                except Exception:
                    pass

            filtered, checked = _filter_results_by_phase(results, target_state, progress_cb=_fsm_cb)
            _pb.empty()
            _ps.empty()
            st.markdown(f"<div class='section-label'>🎯 תוצאות מסוננות לפאזה: {_plabel}</div>",
                        unsafe_allow_html=True)
            st.caption(f"אומתו מבנית {checked} מועמדים מהסריקה · נמצאו {len(filtered)} בפאזה שנבחרה. "
                       f"(האימות נשמר במטמון כ-30 דק' — החלפת פאזה מסננת מיידית.)")
            if not filtered:
                st.info(f"אין כרגע מניות בפאזת '{_plabel}' בין המועמדים ששרדו את הסריקה. "
                        f"אפשר להרחיב ל'סריקה מלאה', או לבחור פאזה אחרת בסלוט — הסינון יתעדכן מיד.")
            else:
                _render_card_carousel(filtered, key_prefix="mscan_ph",
                                      index_key="scan_card_index_ph", dest_page="🏠 בית")
        else:
            # תצוגת כרטיסיות עם דפדוף (Carousel) - זהה למסך הבית
            _render_card_carousel(results, key_prefix="mscan", index_key="scan_card_index", dest_page="🏠 בית")

    st.markdown("<hr style='border-color:rgba(255,255,255,0.08); margin:22px 0;'>", unsafe_allow_html=True)


def screen_institutional_map() -> None:
    st.markdown("### 🗺️ Institutional Map - מפת כסף חכם סקטוריאלית")
    st.markdown("מסך זה ממפה את הסקטורים המרכזיים בשוק ומציג את ממוצע ה-**Institutional Accumulation Probability** (הסתברות לצבירה מוסדית) שלהם. הנתונים מתעדכנים על בסיס מניות מובילות בכל סקטור ומוצגים מהגבוה לנמוך.")

    # --- V20.2: Macro Technical Radar (שכבת רקע מאקרו תומכת) ---
    render_macro_radar()

    # --- מנוע סריקת שוק רחב (Early Pruning) ---
    _render_market_scanner()

    st.markdown("---")
    st.info("🌐 ניתוח סקטוריאלי מלא (Wyckoff + ערך לכל סקטור) עבר לרדאר הסקטורים במסך הבית — מהיר, מבוסס ETF מייצג, וללא סריקות כבדות.")


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
            struct_phase = ""
            _ws_f = None
            if df is not None and not df.empty:
                engine = FactorEngine(BacktestConfig())
                factors = engine.compute(df)
                cis_score = float(engine.composite_cis(factors, df).iloc[-1])
                current_phase = str(engine.get_wyckoff_phase(df).iloc[-1])
                # V21.1: מקור אמת יחיד — גם המסך הפונדמנטלי מציג את הפאזה המבנית
                try:
                    _wctx = assess_weekly_context(_to_weekly(df))
                    _ws_f = analyze_wyckoff_structural(df, _wctx, factors, cis_score, current_phase)
                    struct_phase = _ws_f["phase_he"]
                except Exception:
                    struct_phase = current_phase

        # --- כותרת מחיר אחידה ליד הטיקר ---
        render_price_header(tkr)

        # --- סינתזה קשיחה אחת (נקודת אמת יחידה, ללא סתירות) ---
        _phase_disp = struct_phase or current_phase or "—"
        verdict_obj = synthesize_verdict(fdata, cis_score, _phase_disp, tkr)
        verdict_obj = _calibrate_verdict_tone(verdict_obj, _ws_f)
        v_color_val = fdata.get("valuation_color", "#94a3b8")
        valuation = fdata.get("valuation", "-")

        # === השורה התחתונה האחידה (אותו רכיב בכל המסכים) ===
        st.markdown("<div class='section-label'>השורה התחתונה — הכרעה מאוחדת</div>", unsafe_allow_html=True)
        render_verdict_banner(
            verdict_obj, ticker=tkr, cis_score=cis_score, current_phase=_phase_disp,
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

                # === V20.2: intel אפליקטיבי (פאזה מאומתת + ראיות + טריות + פירוש CIS) ===
                _intel = _compute_wyckoff(tkr)
                _fund0 = rec_data.get("fundamental", {}) or {}
                if _intel:
                    render_data_status(tkr, _intel["df"], _fund0, _intel.get("freshness"))
                else:
                    render_data_status(tkr, None, _fund0)

                # === V21.1: מקור אמת יחיד לפאזה — wyckoff_state מהמנוע המבני (לכל המסך) ===
                if _intel and _intel.get("wyckoff_state"):
                    _ws = _intel["wyckoff_state"]
                    _struct_phase = _ws["phase_he"]
                    _srm = _structural_roadmap(_ws["state"])
                    render_structural_summary(tkr, _intel, show_plan=False)
                else:
                    _struct_phase = rec_data.get('current_phase', '')
                    _srm = None

                # === V22.0: ניתוח ערך ואיכות — מטריצה + פילרים + Reverse-DCF (expander) ===
                with st.expander("🏢 ניתוח ערך ואיכות — מטריצה, פילרי איכות, Reverse-DCF", expanded=False):
                    render_value_quality_detail(tkr, get_fundamental_data(tkr) or {})

                # === שלב 1: השורה התחתונה האחידה (Verdict Banner) - ראשון ובולט ===
                _fund = rec_data.get("fundamental", {}) or {}
                _verdict = rec_data.get("verdict")
                # V21.1: מקור אמת יחיד — בנה מחדש את ה-verdict עם הפאזה המבנית (אותה
                # synthesize_verdict הקנונית), כך שגם טקסט ההכרעה לא יזכיר פאזה גולמית סותרת.
                if _intel and _intel.get("wyckoff_state"):
                    try:
                        _cis_v = rec_data.get('prob_engine', {}).get('accumulation_chance')
                        if _cis_v is None:
                            _cis_v = _intel.get("current_cis", 0)
                        _verdict = synthesize_verdict(_fund, _cis_v, _struct_phase, tkr)
                    except Exception:
                        _verdict = rec_data.get("verdict")
                    _verdict = _calibrate_verdict_tone(_verdict, _intel.get("wyckoff_state"))
                if _verdict:
                    render_verdict_banner(
                        _verdict, ticker=tkr,
                        cis_score=rec_data.get('prob_engine', {}).get('accumulation_chance'),
                        current_phase=_struct_phase,
                        valuation=_fund.get('valuation'),
                        valuation_color=_fund.get('valuation_color', '#94a3b8'),
                        extra_chips=[f"המלצה <b>{rec_data.get('recommendation','-')}</b>"],
                    )

                # === V20.2: מה אומר הציון + למה הפאזה הזו (בולט) ===
                if _intel:
                    render_cis_meaning(_intel["current_cis"], _intel["factors"], _intel["display_phase"])
                    render_phase_evidence(_intel, tkr)
                    # === V20.3: ניתוח Wyckoff מעמיק (expander) ===
                    with st.expander("🔬 ניתוח Wyckoff מעמיק — טווח מסחר, אירועים, VSA, יעדי Cause & Effect", expanded=False):
                        render_wyckoff_deep_analysis(tkr, _intel)

                # === שלב 2: הסבר קצר ואנושי - למה דווקא המניה הזו, עכשיו (Q16: bullets + הסבר נוסף) ===
                if _fund:
                    _why_phase = _struct_phase
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
                # V21.1: מפת דרכים קוהרנטית עם הפאזה המבנית (מקור אמת יחיד)
                if _srm:
                    roadmap_prev, roadmap_next, roadmap_action = _srm["prev"], _srm["next"], _srm["action"]
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
                    f"<span style='color:#f8fafc; font-weight:700; font-size:1.05rem; margin-right: 6px;'>{_struct_phase}</span>",
                    "</div>",
                    "</div>",
                    
                    # Visual Roadmap - חצים תוקנו לשמאל
                    "<div class='roadmap-box'>",
                    "<div class='roadmap-step'><span class='roadmap-label'>היינו ב:</span><span class='roadmap-value'>", roadmap_prev, "</span></div>",
                    "<div class='roadmap-arrow'>←</div>",
                    "<div class='roadmap-step'><span class='roadmap-label'>אנחנו ב:</span><span class='roadmap-value' style='color:#38bdf8;'>", _struct_phase, "</span></div>",
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

                    # === V20.2: תוכנית מסחר Swing ישימה (מתקנת באג trade_plan חסר) ===
                    st.markdown(f"**פעולה מומלצת:** {rec_data['action']}")
                    # קוהרנטיות עם שכבת האימות: אם זוהה סיכון הפצה / אין פאזה מאושרת — מתריעים מעל התוכנית
                    _ps = (_intel or {}).get("phase_status", "confirmed")
                    if _ps == "caution":
                        st.warning("⚠️ שכבת האימות מזהה **סיכון הפצה / תיקון בנפח גבוה**. התוכנית למטה מבוססת תווית פאזת הליבה — שקול להמתין לאישור (שפל גבוה-יותר בנפח דועך + סגירה מעל ההתנגדות בנפח) לפני כניסה.")
                    elif _ps == "transition":
                        st.info("ℹ️ אין פאזה טכנית מאושרת כרגע (מצב מעבר). התוכנית למטה היא תרחיש מותנה — דרוש אישור כניסה לפאזה לפני פעולה.")
                    if rec in ("SELL", "STRONG SELL"):
                        st.warning("🚫 לא קיימת תוכנית כניסה ללונג במצב זה. ההסתברות לצבירה מוסדית נמוכה / הנכס בפאזת הפצה.")
                    else:
                        _swing = build_swing_trade_plan(rec_data)
                        if isinstance(_swing, dict) and _struct_phase:
                            _swing['phase'] = _struct_phase   # V21.1: מקור אמת יחיד לפאזה גם בכותרת התוכנית
                        render_swing_plan(_swing, rec_data)

                        # גודל פוזיציה (כשנבחרה רמת פירוט מתאימה) - מבוסס סיכון 1% לעסקה
                        if _swing and _swing.get("valid") and plan_level_key == "sizing":
                            stop_dist = abs(_swing["stop_pct"]) or 1.0
                            pos_pct = round(min(25.0, 1.0 / (stop_dist / 100.0)), 1)  # 1% סיכון תיק
                            st.markdown(
                                f"<div class='plan-stage' style='border-color:rgba(56,189,248,0.35);'>"
                                f"<span class='plan-stage-label'>💼 גודל פוזיציה מומלץ</span>"
                                f"<span class='plan-stage-val' style='color:#38bdf8'>~{pos_pct}% מהתיק</span>"
                                f"<span class='plan-stage-note'>מחושב כך שהפסד בסטופ ({stop_dist:.1f}% מרחק) ≈ 1% מהתיק. "
                                f"זהו תקרת חשיפה — אפשר להקטין לפי שיקול דעת.</span></div>",
                                unsafe_allow_html=True,
                            )

                        # מפת דרכים (השלמה תמציתית למודל הוויקוף)
                        with st.expander("🗺️ מפת דרכים מורחבת (מודל הוויקוף)", expanded=False):
                            st.markdown(f"**היינו ב:** {roadmap_prev} → **אנחנו ב:** {_struct_phase} → **היעד הסביר:** {roadmap_next}")
                            st.markdown(f"**✅ אם התבנית מצליחה:** {roadmap_success}")
                            st.markdown(f"**❌ אם התבנית נכשלת:** {roadmap_fail}")

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

# V20.2 – תוקנו: דיוק פאזות, הסברים, תוכנית מסחר, נתונים.
# V20.3 – נוסף: ניתוח Wyckoff מעמיק (Trading Range, אירועים, VSA, יעדי Cause & Effect) — שכבת אפליקציה בלבד.
# V20.4 – נוסף: שער עקביות פאזה — לא כופה תווית שסותרת את המבנה; אומר "אין פאזה מאושרת, סרוק שוב מחר".
# V21.0 – היפוך: מנוע מבני (8 states + gate שבועי + ביטחון רציף + סטופים/יעדים מבניים + playbook + 3 חיוגים) מניע את הפאזה; CIS מאַשר. שכבת אפליקציה בלבד.
# V21.1 – תיקון BKNG: (1) FSM — מיקום נוכחי גובר על אירוע ישן (חצי עליון+OBV חיובי ⇒ שלב D). (2) מקור אמת יחיד — wyckoff_state["phase_he"] בכל המסכים.
# V22.0 – שכבת ערך ואיכות (Tier 2): ציון איכות A-F (8 עקרונות) + Reverse-DCF (צמיחה גלומה) → חיוג שלישי + שורת שכנוע (Runner/רווח). לא מזיז כניסה/סטופ/יעד. שכבת אפליקציה בלבד.
# V23.0 – איכות רב-שנתית (Tier 3.0): עקביות FCF (5 שנים) + מגמת מרווחים → modifier פנימי לציון (נשאר A-F). cache חזק, עמיד-כשל. פירוט ב-expander. שכבת אפליקציה בלבד.
# V24.0 – כיול היסטורי (Tier 3.1): שיעור הצלחה של המצב במניה (calculate_phase_followthrough, walk-forward) → שורת "היסטורית" + modifier קטן לביטחון. WULF מוגן. cache חזק. שכבת אפליקציה בלבד.
# V25.0 – פיצול מסלולים טרייד/השקעה + כיול טון verdict + תגיות תזמון בסורק + הסבר ראיות-סותרות. פתרון סתירות BKNG. שכבת אפליקציה בלבד.
# V25.1 – שער OBV להפצה (אפ-ת'ראסט+OBV חיובי ⇒ שלב D בזהירות, לא הפצה) + דגל caution. BKNG: טרייד=D+זהירות, השקעה=A+החזק. שכבת אפליקציה בלבד.
# V25.2 – ייצוב Dual-Lens: טקסטי caution קצרים, 'סכין נופלת' רק בשבירה מאושרת, tier→WATCH בזהירות, תגיות סורק מדויקות. שכבת אפליקציה בלבד.
# V25.2-fix – באג: מסך בחירת המסלול לא הופיע כשעדשה נשמרה מריצה קודמת. תוקן: איפוס העדשה בכל 'הרץ ניתוח' (החלפת מסלול נשמרת).
# V25.3 – סריקה לפי פאזה בסורק הטכני: מסלול כללי/לפי-פאזה + סלוט 7 פאזות; סינון מאומת FSM (מקור אמת יחיד); pool 40; החלפת פאזה מסננת מיידית. שכבת אפליקציה בלבד. כולל סריקה סקטוריאלית (תגיות מבניות אחידות).
# V25.4 – סריקה ממוקדת (כפתור 3 בבית): שילוב פאזה+איכות+תמחור+סקטור, כל ציר 'הכל' או ספציפי; מנוע _focused_filter טהור; מקור אמת יחיד; cache חכם. שכבת אפליקציה בלבד.
# V25.5 – יקום נאסד"ק מסונן מקובץ חיצוני (build_universe.py→nasdaq_universe.json): מחיר/שווי/ווליום, מיזוג+fallback ל-146, אזהרת התיישנות 14 יום. הניתוח תמיד חי.
# V25.6 – יקום מובנה S&P 500 + Nasdaq 100 (~515) מוטמע בקוד, ללא סקריפט; ממוזג עם סחורות; cap סריקה ממוקדת → 515. קובץ JSON נשאר שדרוג אופציונלי.
# V25.7 – תיקון הבהוב/היעלמות הקרוסלה בסריקה ממוקדת: scan+filter→store→st.rerun→render-from-state (דפוס 'תמצא לי'). שאר הסורקים לא נגעו.
# V25.8 – תיקון כפתור 'ניתוח מלא' בקרוסלה: קביעת home_mode='check' לפני ניווט ל-'🏠 בית' (אחרת ה-handoff לא נצרך). מסלול 'תמצא לי' לא נגע.
# V25.9 – מוכנות למהלך (Breakout Readiness): תווית מילולית קרוב/מתקרב/רחוק + ימים ברצף בפאזה (ללא ציון). בטרייד/סורק/סריקה-ממוקדת (+מיון לפי קרבה). שכבת אפליקציה בלבד.
# V26.0 – טריות אירועים: Spring/UTAD ישנים (>25 ברים) לא מכתיבים state ('הקריאה פגה'→בסיס); ספירת ימים מעוגנת-אירוע (Spring/SOS/UTAD); תווית ניעור='מתקרב'. BKNG/WULF מאומתים.
# V26.1 – דעיכה מדורגת לניעור: טרי(≤10)/מזדקן(11-25, score+rank יורדים, 'מאבד תוקף')/פג(>25). אין צוק בינארי. BKNG/WULF מאומתים.
# V27.0 – רדאר סקטורים: 20 סקטורים גרנולריים מהיקום, לוח-חום Wyckoff+ערך לפי ETF+מובילות (כפתור 4 בבית); הוסרו מפת-CIS וסריקת הסקטורים הכבדות. שכבת אפליקציה בלבד.
# V27.1 – מנוע סריקה מקבילי (ThreadPool 10) + שעון ספירה לאחור מתעדכן כל שנייה + אפס תוצאות חלקיות. 'תמצא לי' והסריקה הממוקדת בלבד.
