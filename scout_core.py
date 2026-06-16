import numpy as np
import pandas as pd
import yfinance as yf
from dataclasses import dataclass
import warnings
import streamlit as st

warnings.filterwarnings("ignore")

# ---------- Helper Functions ----------
def clean_filename(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).replace(' ', '_')

def get_data(ticker, period="1y", start=None, end=None):
    try:
        if start is not None and end is not None:
            df = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=False)
        else:
            df = yf.Ticker(ticker).history(period=period, auto_adjust=False)

        if df is None or df.empty or len(df) < 40:
            return None

        df.index = pd.to_datetime(df.index).tz_localize(None)
        df = df.sort_index()

        if start is not None and end is not None:
            spy_df = yf.Ticker("SPY").history(start=start, end=end, auto_adjust=False)
            vix_df = yf.Ticker("^VIX").history(start=start, end=end, auto_adjust=False)
        else:
            spy_df = yf.Ticker("SPY").history(period=period, auto_adjust=False)
            vix_df = yf.Ticker("^VIX").history(period=period, auto_adjust=False)

        if spy_df is not None and not spy_df.empty:
            spy_df.index = pd.to_datetime(spy_df.index).tz_localize(None)
            df = df.join(spy_df[["Close"]].rename(columns={"Close": "spy_close"}), how="left")
        else:
            df["spy_close"] = np.nan

        if vix_df is not None and not vix_df.empty:
            vix_df.index = pd.to_datetime(vix_df.index).tz_localize(None)
            df = df.join(vix_df[["Close"]].rename(columns={"Close": "vix_close"}), how="left")
        else:
            df["vix_close"] = np.nan

        return df
    except Exception:
        return None

def calculate_optimal_threshold(model, X, y):
    try:
        probs = model.predict_proba(X)[:, 1] * 100
    except Exception:
        return 65

    best_thresh = 50
    best_score  = 0
    for th in range(50, 95, 2):
        mask         = probs >= th
        trades_count = mask.sum()
        if trades_count >= max(3, len(y) * 0.05):
            win_rate = y[mask].mean()
            score    = win_rate * (1 + np.log1p(trades_count) / 10)
            if score > best_score:
                best_score  = score
                best_thresh = th
    return best_thresh

def check_phase_entry_allowed(phase, risk_profile):
    if "לא בתהליך" in phase or "Markdown" in phase or "Distribution" in phase:
        return False
    if risk_profile == "Aggressive":
        return any(p in phase for p in ["Phase C", "Phase D", "Phase E", "Spring", "LPS", "SOS", "Breakout", "Markup"])
    elif risk_profile == "Balanced":
        return any(p in phase for p in ["Phase D", "Phase E", "LPS", "SOS", "Breakout", "Markup"])
    elif risk_profile == "Conservative":
        return any(p in phase for p in ["Phase E", "Markup"])
    return False

@dataclass
class BacktestConfig:
    commission: float = 0.001
    initial_capital: float = 100_000.0
    hold_days: int = 40
    period: str = "2y"
    stop_loss_pct: float = 0.05
    atr_multiplier: float = 2.0

# ---------- Factor Engine ----------
class FactorEngine:
    def __init__(self, cfg: BacktestConfig):
        self.cfg = cfg

    def _compute_quick_wyckoff(self, df: pd.DataFrame) -> pd.Series:
        score = pd.Series(0.0, index=df.index)
        if len(df) < 40:
            return score
        vol_ma = df["Volume"].rolling(20).mean()
        has_sc, has_ar, has_st = False, False, False
        sc_idx, sc_low, ar_high = 0, 0.0, 0.0
        search_df = df.iloc[-90:]
        for i in range(1, len(search_df)):
            idx = search_df.index[i]
            vol = search_df["Volume"].iloc[i]
            vol_ma_i = vol_ma.loc[idx]
            close = search_df["Close"].iloc[i]
            low = search_df["Low"].iloc[i]
            high = search_df["High"].iloc[i]
            open_px = search_df["Open"].iloc[i]
            if not has_sc:
                if close < open_px and vol > vol_ma_i * 2.0 and close <= search_df["Close"].iloc[max(0, i - 20):i].min():
                    has_sc = True
                    sc_idx = i
                    sc_low = low
                    score.loc[idx] = 0.3
            elif has_sc and not has_ar and (i - sc_idx <= 15):
                if close > open_px and close > search_df["Close"].iloc[i - 1]:
                    has_ar = True
                    ar_high = high
                    score.loc[idx] = 0.4
            elif has_ar and not has_st:
                if vol < search_df["Volume"].iloc[sc_idx] * 0.75 and abs(low - sc_low) / sc_low < 0.05:
                    has_st = True
                    score.loc[idx] = 0.6
            elif has_st:
                if low < sc_low and close > sc_low:
                    score.loc[idx] = 0.8
                elif low > sc_low and low < search_df["Low"].iloc[i - 1] and vol < vol_ma_i:
                    score.loc[idx] = 0.85
                elif close > ar_high and vol > vol_ma_i * 1.5:
                    score.loc[idx] = 1.0
                    has_sc = False
        return score

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        f = pd.DataFrame(index=df.index)
        rng = df["High"] - df["Low"]
        vol_ma20 = df["Volume"].rolling(20).mean()
        rvol = df["Volume"] / vol_ma20.replace(0, np.nan)
        spread_ma20 = rng.rolling(20).mean()

        f["f04_absorption"] = (((df["Volume"] > vol_ma20 * 1.5) & (rng < spread_ma20 * 0.8)) & (df["Close"] <= df["Low"].rolling(20).min() * 1.05)).astype(float)
        f["f36_wyckoff_score"] = self._compute_quick_wyckoff(df)
        f["f07_obv_velocity"] = ((np.sign(df["Close"].diff()) * df["Volume"]).cumsum().diff(10) / (np.sign(df["Close"].diff()) * df["Volume"]).cumsum().abs().rolling(10).mean().replace(0, np.nan)).clip(-3, 3)
        f["f14_inst_intent"] = (f["f04_absorption"] * 0.3 + f["f07_obv_velocity"].clip(0, 1) * 0.4 + (f["f04_absorption"].rolling(30).max() * (rvol < 0.7).astype(float)) * 0.3).clip(0, 1)
        f["f20_liquidity_sweep"] = ((df["Low"] < df["Low"].rolling(20).min().shift(1)) & (df["Close"] > df["Low"].rolling(20).min().shift(1))).astype(float)
        f["f26_accept_reject"] = ((df["Close"] > (df["High"] + df["Low"]) / 2) & (df["Volume"] > vol_ma20)).astype(float).rolling(5).mean() - ((df["Close"] < (df["High"] + df["Low"]) / 2) & (df["Volume"] > vol_ma20)).astype(float).rolling(5).mean()
        f["f35_struct_break"] = (df["Close"] > df["High"].rolling(20).max().shift(1)).astype(float) - (df["Close"] < df["Low"].rolling(20).min().shift(1)).astype(float)

        return f.fillna(0)

    def composite_cis(self, factors: pd.DataFrame, df: pd.DataFrame = None) -> pd.Series:
        base_weights = {
            "f04_absorption": 6,
            "f07_obv_velocity": 5,
            "f14_inst_intent": 6,
            "f20_liquidity_sweep": 3,
            "f26_accept_reject": 3,
            "f35_struct_break": 2,
        }

        dynamic_weights = {f: pd.Series(base_weights[f], index=factors.index) for f in base_weights}
        total_w = sum(dynamic_weights.values())

        score = pd.Series(0.0, index=factors.index)
        for col in base_weights:
            if col in factors.columns:
                score += factors[col].clip(-1, 1) * dynamic_weights[col]

        return (score / total_w.replace(0, np.nan).fillna(1) * 100 + 50).clip(0, 100).round(1)

    def get_wyckoff_phase(self, df: pd.DataFrame) -> pd.Series:
        phases = pd.Series("לא בתהליך איסוף", index=df.index)
        if len(df) < 60:
            return phases

        close = df['Close']
        vol = df['Volume']
        sma20 = close.rolling(20).mean()
        sma50 = close.rolling(50).mean()
        sma200 = close.rolling(200).mean()
        
        vol_ma = vol.rolling(20).mean()
        high20 = df['High'].rolling(20).max()
        low20 = df['Low'].rolling(20).min()

        for i in range(60, len(df)):
            c = close.iloc[i]
            v = vol.iloc[i]
            v_ma = vol_ma.iloc[i]
            h20 = high20.iloc[i-1]
            l20 = low20.iloc[i-1]
            
            s20 = sma20.iloc[i]
            s50 = sma50.iloc[i]
            s200 = sma200.iloc[i] if not pd.isna(sma200.iloc[i]) else s50
            
            if c > s20 and s20 > s50 and c > h20 * 0.95:
                phases.iloc[i] = "Phase E (Markup)"
            elif c > s50 and v > v_ma * 1.2 and c >= h20 * 0.98:
                phases.iloc[i] = "Phase D (SOS)"
            elif df['Low'].iloc[i] < l20 * 1.01 and c > df['Open'].iloc[i] and c < s50:
                phases.iloc[i] = "Phase C (Spring)"
            elif c < s50 and c > l20 and v < v_ma:
                phases.iloc[i] = "Phase B (Accumulation)"
            elif c < l20 and v > v_ma * 1.5 and c > df['Open'].iloc[i]:
                phases.iloc[i] = "Phase A (Selling Climax)"
            elif c < s20 and s20 < s50 and c < s200:
                phases.iloc[i] = "Markdown"
            else:
                phases.iloc[i] = "Phase B (Accumulation)"
                
        return phases


def run_wyckoff_anchored_backtest(
    ticker,
    use_ai,
    threshold,
    period=None,
    start=None,
    end=None,
    risk_profile="Balanced",
    stop_loss_pct=0.05,
    atr_multiplier=2.0,
):
    df = get_data(ticker, period=period, start=start, end=end)
    if df is None:
        return None, pd.DataFrame()

    cfg_period = period if period else f"{start}/{end}"
    engine = FactorEngine(
        BacktestConfig(
            period=cfg_period,
            stop_loss_pct=stop_loss_pct,
            atr_multiplier=atr_multiplier,
        )
    )
    factors = engine.compute(df)
    df['wyckoff_phase'] = engine.get_wyckoff_phase(df)
    df['cis_score'] = engine.composite_cis(factors, df)
    df['Daily_Return'] = df['Close'].pct_change().fillna(0)

    # Simplified AI injection
    if use_ai and st is not None and getattr(st, "session_state", None) and getattr(st.session_state, "ml_model", None) is not None:
        try:
            model = st.session_state.ml_model
            expected_features = getattr(model, "feature_names_in_", None)
            X_pred = factors.copy()
            if expected_features is not None:
                for c in expected_features:
                    if c not in X_pred.columns:
                        X_pred[c] = 0
                X_pred = X_pred[expected_features]
            probs = model.predict_proba(X_pred)[:, 1]
            df['cis_score'] = probs * 100
        except Exception:
            pass

    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift(1)).abs()
    low_close = (df['Low'] - df['Close'].shift(1)).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr_series = true_range.rolling(14).mean()

    positions = []
    audit_logs = []
    in_position = False
    entry_price = 0
    entry_phase = ""
    entry_date = None
    peak_price = 0
    cis_at_entry = 0
    stop_loss_level = 0

    for i in range(len(df)):
        current_phase = df['wyckoff_phase'].iloc[i]
        current_cis = df['cis_score'].iloc[i]
        phase_allowed = check_phase_entry_allowed(current_phase, risk_profile)
        score_allowed = current_cis >= threshold

        if not in_position:
            if phase_allowed and score_allowed:
                positions.append(1)
                in_position = True
                entry_price = df['Close'].iloc[i]
                entry_phase = current_phase
                entry_date = df.index[i]
                peak_price = entry_price
                cis_at_entry = current_cis
                atr_val = atr_series.iloc[i] if not pd.isna(atr_series.iloc[i]) else 0
                if atr_val > 0:
                    stop_loss_level = min(
                        entry_price * (1 - stop_loss_pct),
                        entry_price - atr_val * atr_multiplier,
                    )
                else:
                    stop_loss_level = entry_price * (1 - stop_loss_pct)
            else:
                positions.append(0)
        else:
            if df['Low'].iloc[i] <= stop_loss_level:
                positions.append(0)
                exit_px = stop_loss_level
                ret = (exit_px - entry_price) / entry_price
                audit_logs.append({
                    "entry_date": entry_date.strftime("%Y-%m-%d"),
                    "exit_date": df.index[i].strftime("%Y-%m-%d"),
                    "phase_at_entry": entry_phase,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(exit_px, 2),
                    "return_pct": round(ret * 100, 2),
                    "win": ret > 0,
                    "exit_type": "Stop_Loss",
                    "phase_at_exit": current_phase,
                    "cis_at_entry": cis_at_entry,
                })
                in_position = False
                continue

            if "Markdown" in current_phase or "Distribution" in current_phase or current_cis < threshold - 15:
                positions.append(0)
                exit_px = df['Close'].iloc[i]
                ret = (exit_px - entry_price) / entry_price
                audit_logs.append({
                    "entry_date": entry_date.strftime("%Y-%m-%d"),
                    "exit_date": df.index[i].strftime("%Y-%m-%d"),
                    "phase_at_entry": entry_phase,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(exit_px, 2),
                    "return_pct": round(ret * 100, 2),
                    "win": ret > 0,
                    "exit_type": "Phase_Change",
                    "phase_at_exit": current_phase,
                    "cis_at_entry": cis_at_entry,
                })
                in_position = False
            else:
                positions.append(1)
                if df['Close'].iloc[i] > peak_price:
                    peak_price = df['Close'].iloc[i]

    # Fill remaining positions to match DF length securely
    positions = positions[:len(df)]
    while len(positions) < len(df):
        positions.append(0)

    df['Position'] = pd.Series(positions, index=df.index).shift(1).fillna(0)
    df['Strategy_Return'] = df['Position'] * df['Daily_Return']
    df['Cum_Strategy'] = (1 + df['Strategy_Return']).cumprod() - 1
    df['Cum_Baseline'] = (1 + df['Daily_Return']).cumprod() - 1

    return df, pd.DataFrame(audit_logs)


def explain_score(df: pd.DataFrame, current_phase: str, cis_score: float) -> str:
    """
    מנתחת את הנתונים ומפיקה נרטיב של 'אנליסט וירטואלי' להסבר הציון.
    """
    if df is None or df.empty:
        return "אין מספיק נתונים להפקת הסבר."

    close = df['Close'].iloc[-1]
    vol = df['Volume'].iloc[-1]
    vol_ma20 = df['Volume'].rolling(20).mean().iloc[-1] if len(df) >= 20 else 1.0
    vol_ratio = vol / vol_ma20 if vol_ma20 > 0 else 1.0
    
    delta = df['Close'].diff()
    obv = (np.sign(delta) * df['Volume']).cumsum()
    obv_diff = obv.diff(10).iloc[-1] if len(obv) >= 10 else 0
    
    sma20 = df['Close'].rolling(20).mean().iloc[-1] if len(df) >= 20 else close
    sma50 = df['Close'].rolling(50).mean().iloc[-1] if len(df) >= 50 else sma20
    
    high20 = df['High'].rolling(20).max().shift(1).iloc[-1] if len(df) >= 20 else close
    breakout = close > high20
    
    # חישוב יתרונות וחסרונות בשפה אנושית
    pros = []
    cons = []

    if vol_ratio >= 1.2:
        pros.append("✓ **נפח מסחר גבוה מהממוצע** (מעיד על עניין מוסדי אקטיבי)")
    elif vol_ratio < 0.8:
        cons.append("• **נפח מסחר נמוך** (חוסר נוכחות של כסף חכם)")
        
    if close > sma20 and close > sma50:
        pros.append("✓ **מבנה מחיר חיובי** (המחיר שומר על תמיכת הממוצעים הנעים)")
    else:
        cons.append("• **מבנה מחיר לא מבוסס** (המחיר עדיין נאבק בהתנגדויות של הממוצעים הנעים)")
        
    if obv_diff > 0:
        pros.append("✓ **הנפח זורם לכיוון הקונים** (אינדיקטור ה-OBV בעלייה, יותר כסף נכנס מאשר יוצא)")
    else:
        cons.append("• **אין כניסת כספים מובהקת** (ה-OBV מדשדש או יורד)")
        
    if breakout:
        pros.append("✓ **נרשמה פריצה של אזור התנגדות קודם** (אישור טכני חשוב)")
    else:
        cons.append("• **אין עדיין אישור לפריצה טכנית** (המחיר מדשדש באזורי הבסיס)")

    if cis_score >= 65:
        pros.append("✓ **ציון מוסדי (CIS) חזק** התומך באפשרות איסוף סחורה שקטה (Absorption)")
    elif cis_score < 50:
        cons.append("• **ציון מוסדי (CIS) חלש**, מומנטום האיסוף המוסדי עדיין בינוני-חלש")

    # פתיח הנרטיב האנושי
    if cis_score >= 65:
        opening = "המערכת מזהה שהמחיר מתחיל להראות סימני התחזקות מובהקים.\n\nבימים האחרונים נרשמה פעילות מסחר התומכת בכניסת כספים. תופעה זו יכולה להעיד על כניסת גופים גדולים שאוספים סחורה מבלי להעלות את המחיר בצורה חדה."
    elif cis_score >= 50:
        opening = "המערכת מזהה התעוררות מתונה במניה, אך התמונה טרם הוכרעה.\n\nישנם ניצנים של עניין מצד קונים, אך נדרש אישור נוסף לכך שמדובר באיסוף מוסדי אמיתי."
    else:
        opening = "המערכת לא מזהה כרגע סימני עוצמה משמעותיים.\n\nנראה כי המוכרים עדיין נותנים את הטון, או שהמניה שרויה בתקופת המתנה ללא עניין חריג מצד הכסף החכם."

    # הסבר חינוכי של שלבי Wyckoff
    phase_explanations = {
        "Phase A": "### שלב A - עצירת המגמה הקודמת (Stopping the Trend)\n\nבשלב זה המערכת מזהה בלימה של הירידות. ישנו מאבק ראשוני בין קונים למוכרים. זהו הסימן הראשון שהשוק מנסה לייצר תחתית, אך עדיין מוקדם לקבוע כיוון מסחר בטוח.",
        "Phase B": "### שלב B - צבירה ובניית בסיס (Building a Cause)\n\nהשוק נמצא בשלב של איסוף שקט. המחיר נע בטווח מסחר ('ריינג''), ומטרת הגופים המוסדיים היא לקנות כמות גדולה של סחורה לאורך זמן מבלי לייצר עליות שמושכות תשומת לב.",
        "Phase C": "### שלב C - מבחן תמיכה וניעור (Spring)\n\nבשלב זה מתבצע לרוב ניעור של 'ידיים חלשות'. השוק יורד מתחת לתמיכות באופן זמני רק כדי לעלות חזרה בעוצמה (Stop Hunting). זהו אישור קריטי לכך שהכסף החכם 'שתה' את הנזילות לקראת גל עליות.",
        "Phase D": "### שלב D - סימן לעוצמה (Sign Of Strength)\n\nזהו השלב שבו השוק מתחיל להראות סימני עוצמה ברורים.\nלאחר תקופה של צבירה שקטה, הביקוש מתחיל לגבור על ההיצע.\n\nבשלב זה לעיתים קרובות ניתן לראות:\n* פריצות מעלה (SOS)\n* מחזורי מסחר (נפחים) גבוהים\n* ירידה בכמות המוכרים\n\nזהו אחד השלבים החשובים ביותר במעבר מצבירה לתחילת גל עליות משמעותי.",
        "Phase E": "### שלב E - מגמה עולה (Markup)\n\nהמגמה החיובית כבר מבוססת לחלוטין. המניה פרצה את אזורי האיסוף והיא בתנועה חזקה מעלה. בשלב זה המוסדיים כבר מחזיקים בפוזיציה והציבור הרחב מתחיל להצטרף לעליות.",
        "Markdown": "### שלב הירידות (Markdown / Distribution)\n\nהמניה נמצאת תחת לחץ מכירות. הגופים הגדולים כנראה בשלב הפצה (מכירת הסחורה) או שהם ממתינים למחירים נמוכים יותר. לא מומלץ לחפש נקודות כניסה כרגע."
    }

    # שיוך שלב
    phase_text = phase_explanations.get("Phase B") 
    for k, v in phase_explanations.items():
        if k in current_phase:
            phase_text = v
            break

    # סיכום מנהלים - שורה תחתונה
    if cis_score >= 75:
        confidence = "גבוהה"
    elif cis_score >= 60:
        confidence = "בינונית-גבוהה"
    elif cis_score >= 45:
        confidence = "בינונית"
    else:
        confidence = "נמוכה"
        
    bottom_line = f"""### 💡 שורה תחתונה:

המניה מציגה מספר סימנים {"**המעידים על אפשרות ברורה של איסוף מוסדי**" if cis_score >= 60 else "**מעורבים לגבי כניסת כסף חכם**"}.

{"מרבית האינדיקטורים נמצאים בכיוון חיובי, ומצביעים על לחץ קניות פוטנציאלי." if cis_score >= 60 else "עדיין נדרש אישור נוסף מצד פעולת המחיר (Price Action) ומחזורי המסחר."}

**רמת הביטחון הנוכחית של המערכת:** {confidence}.
"""

    pros_text = "\n".join(pros) if pros else "✓ אין סימנים חיוביים בולטים בשלב זה."
    cons_text = "\n".join(cons) if cons else "• לא זוהו חולשות מהותיות במבנה."

    # הרכבת ה-Markdown הסופי
    md = f"""{opening}

{phase_text}

### ⚖️ פירוט הציון לגורמים:

**מה חיזק את הציון?**
{pros_text}

**מה החליש את הציון?**
{cons_text}

---
{bottom_line}
"""
    return md
