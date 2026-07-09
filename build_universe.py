#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_universe.py — מייצר יקום סריקה מסונן מרשימת נאסד"ק (רץ אצלך, לא ב-Cloud Run).

מה זה עושה:
  1. מוריד את רשימת הסמלים הרשמית והחינמית של נאסד"ק (nasdaqtrader.com).
  2. מסנן כל מניה לפי 3 קריטריונים — עם "דילוג-מוקדם" ליעילות:
        • מחיר אחרון           >= $5
        • ווליום דולרי יומי     >= $20,000,000   (מחיר × ווליום ממוצע ~3 חודשים)
        • שווי שוק              >= $1,000,000,000
     דילוג-מוקדם: מושכים קודם מחיר+ווליום (שליפה קלה אחת). מי שנכשל — מדולג *מיד*
     בלי שליפת שווי-השוק הכבדה. שווי-שוק נשלף רק על מי שעבר את מחיר+ווליום.
  3. כותב nasdaq_universe.json — אתה מעלה אותו לגיטהאב, לצד app.py.

האפליקציה טוענת את הקובץ אוטומטית (עם חותמת תאריך ואזהרת התיישנות אחרי 14 יום),
וכל שלושת מסלולי הסריקה (תמצא לי / סורק טכני / סריקה ממוקדת) משתמשים בו.
אם הקובץ חסר/פגום — האפליקציה נופלת חיננית ליקום האצור (~146). *הניתוח עצמו תמיד
נשלף חי* — הקובץ קובע רק מי מועמד לסריקה, לא נתונים.

התקנה והרצה:
    pip install yfinance pandas requests
    python build_universe.py
    # אופציות:
    #   --include-nyse     כלול גם NYSE/AMEX (לא רק נאסד"ק)
    #   --workers 8        חוטים מקבילים (הורד ל-4 אם יש חסימות rate-limit)
    #   --limit 300        הגבל מספר סמלים (לבדיקה מהירה)
    #   --out FILE         שם קובץ פלט (ברירת מחדל nasdaq_universe.json)

הערה: הרצה מלאה סורקת אלפי סמלים ויכולה לקחת כמה דקות. שווי-שוק/ווליום יציבים,
לכן מספיק לרענן פעם בשבוע-שבועיים ולהעלות מחדש.
"""

import argparse
import io
import json
import sys
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
    import pandas as pd
    import yfinance as yf
except ImportError as exc:  # pragma: no cover
    print(f"חסרה ספרייה: {exc}. הרץ:  pip install yfinance pandas requests")
    sys.exit(1)

# ----------------------- קריטריונים (ניתן לשנות כאן) -----------------------
MIN_PRICE = 5.0
MIN_MARKET_CAP = 1_000_000_000       # $1B
MIN_DOLLAR_VOLUME = 20_000_000       # $20M ווליום דולרי יומי ממוצע
VOL_LOOKBACK_DAYS = 63               # ~3 חודשי מסחר לממוצע הווליום

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"  # NYSE/AMEX


def fetch_symbol_list(include_nyse: bool = False) -> list:
    """מוריד את רשימת הסמלים ומנקה יחידות/וורנטים/מניות בכורה וסמלים לא-סחירים."""
    symbols = []

    def _parse(url: str, sym_col: str, etf_col: str = "ETF"):
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text), sep="|")
        # השורה האחרונה בקובץ היא כותרת-תחתית ("File Creation Time...") — מסירים
        if len(df) > 0:
            df = df.iloc[:-1]
        # מסירים Test Issues
        if "Test Issue" in df.columns:
            df = df[df["Test Issue"].astype(str).str.upper() == "N"]
        vals = df[sym_col].dropna().astype(str).tolist()
        return [s.strip().upper() for s in vals]

    try:
        symbols += _parse(NASDAQ_LISTED_URL, "Symbol")
    except Exception as exc:
        print(f"אזהרה: כשל בהורדת רשימת נאסד\"ק ({exc}).")
    if include_nyse:
        try:
            symbols += _parse(OTHER_LISTED_URL, "ACT Symbol")
        except Exception as exc:
            print(f"אזהרה: כשל בהורדת רשימת NYSE/AMEX ({exc}).")

    # ניקוי: מסירים סמלים עם תווים מיוחדים (וורנטים/יחידות/בכורה) וסמלים ארוכים מדי
    clean = []
    for s in symbols:
        if not s or any(ch in s for ch in ".$^/"):
            continue
        if len(s) > 5:
            continue
        clean.append(s)
    return sorted(set(clean))


def check_ticker(sym: str):
    """
    דילוג-מוקדם: מחיר+ווליום קודם (שליפה קלה); שווי-שוק רק אם עבר.
    מחזיר את הסמל אם עבר את כל שלושת הקריטריונים, אחרת None.
    """
    try:
        tk = yf.Ticker(sym)

        # --- שליפה 1: מחיר + ווליום (היסטוריית 3 חודשים) ---
        hist = tk.history(period="3mo", interval="1d", auto_adjust=True)
        if hist is None or hist.empty or len(hist) < 20:
            return None
        price = float(hist["Close"].iloc[-1])
        if not price or price < MIN_PRICE:
            return None  # דילוג מיידי — בלי שליפת שווי-שוק
        avg_vol = float(hist["Volume"].tail(VOL_LOOKBACK_DAYS).mean())
        if price * avg_vol < MIN_DOLLAR_VOLUME:
            return None  # דילוג מיידי — הווליום הדולרי נמוך מדי

        # --- שליפה 2: שווי שוק (רק למי שעבר מחיר+ווליום) ---
        mc = 0.0
        try:
            fi = tk.fast_info
            mc = float(getattr(fi, "market_cap", None) or (fi.get("market_cap") if hasattr(fi, "get") else 0) or 0)
        except Exception:
            mc = 0.0
        if not mc:
            try:
                mc = float(tk.info.get("marketCap") or 0)
            except Exception:
                mc = 0.0
        if not mc or mc < MIN_MARKET_CAP:
            return None

        return sym
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="בונה יקום סריקה מסונן מרשימת נאסד\"ק.")
    ap.add_argument("--include-nyse", action="store_true", help="כלול גם NYSE/AMEX")
    ap.add_argument("--workers", type=int, default=8, help="חוטים מקבילים (ברירת מחדל 8)")
    ap.add_argument("--limit", type=int, default=0, help="הגבל מספר סמלים (לבדיקה)")
    ap.add_argument("--out", default="nasdaq_universe.json", help="קובץ פלט")
    args = ap.parse_args()

    print("מוריד רשימת סמלים...", flush=True)
    symbols = fetch_symbol_list(include_nyse=args.include_nyse)
    if not symbols:
        print("שגיאה: לא הורדו סמלים. בדוק חיבור אינטרנט.")
        sys.exit(1)
    if args.limit:
        symbols = symbols[:args.limit]
    print(f"נמצאו {len(symbols)} סמלים. מסנן לפי מחיר>=${MIN_PRICE:.0f}, "
          f"ווליום-דולרי>=${MIN_DOLLAR_VOLUME:,}, שווי>=${MIN_MARKET_CAP:,} "
          f"(דילוג-מוקדם)...", flush=True)

    passed, done, t0 = [], 0, time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(check_ticker, s): s for s in symbols}
        for fut in as_completed(futs):
            done += 1
            try:
                res = fut.result()
            except Exception:
                res = None
            if res:
                passed.append(res)
            if done % 100 == 0 or done == len(symbols):
                el = time.time() - t0
                rate = done / el if el else 0
                eta = (len(symbols) - done) / rate if rate else 0
                print(f"  {done}/{len(symbols)} נבדקו · {len(passed)} עברו · "
                      f"{el:.0f}s · נותרו ~{eta:.0f}s", flush=True)

    passed = sorted(set(passed))
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d"),
        "criteria": {
            "min_price": MIN_PRICE,
            "min_market_cap": MIN_MARKET_CAP,
            "min_dollar_volume": MIN_DOLLAR_VOLUME,
            "include_nyse": bool(args.include_nyse),
        },
        "count": len(passed),
        "tickers": passed,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print(f"\n✅ נוצר {args.out}: {len(passed)} מניות עברו את הסינון "
          f"(מתוך {len(symbols)} שנבדקו).")
    print("העלה את הקובץ לגיטהאב לצד app.py — האפליקציה תטען אותו אוטומטית.")
    if len(passed) < 20:
        print("⚠️ שים לב: פחות מ-20 מניות עברו — האפליקציה תתעלם ותשתמש ביקום האצור. "
              "בדוק את הקריטריונים/החיבור.")


if __name__ == "__main__":
    main()
