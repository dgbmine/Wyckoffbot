# auto_trainer_fixed.py – BATCHED MODE + FULL AUTO FALLBACK
# ─────────────────────────────────────────────────────────────
# מתחבר לפונקציות של scout_core.py, מריץ בדיקות רטרואקטיביות
# ומאמן מודל ML לזיהוי דפוסי איסוף עבר מוצלחים.
# ─────────────────────────────────────────────────────────────

import os
import sys
import json
import time
import pickle
import traceback
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

# ── השתקת Streamlit לטובת ריצת רשת שקטה ──
import streamlit as _st
class _FakeStSession:
    def __getattr__(self, name): return None
_st.session_state = _FakeStSession()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

LOG_FILE = os.path.join(BASE_DIR, "auto_trainer_error.log")

def log_message(msg):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {msg}\n")

from scout_core import (
    clean_filename,
    calculate_optimal_threshold,
    FactorEngine,
    BacktestConfig,
    run_wyckoff_anchored_backtest,
)

MODEL_DIR = os.path.join(BASE_DIR, "models")
STATUS_FILE = os.path.join(MODEL_DIR, "auto_trainer_status.json")
DONE_FLAG = os.path.join(MODEL_DIR, "auto_trainer.done")

# ── רשימות סקטורים ──
GROWTH_TICKERS = ["AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","CRM","NFLX","AMD"]
VALUE_TICKERS = ["BRK-B","JPM","JNJ","V","UNH","PG","MA","HD","MRK","ABBV"]
COMMODITIES_TICKERS = ["XOM","CVX","SLB","EOG","OXY","COP","PSX","VLO","FCX","NEM"]

def write_status(**kwargs):
    try:
        if not os.path.exists(MODEL_DIR): os.makedirs(MODEL_DIR)
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(kwargs, f, ensure_ascii=False, indent=2)
    except:
        pass

def process_sector(slot, tickers, base_threshold=60):
    log_message(f"Starting training for {slot} with {len(tickers)} tickers.")
    all_features = []
    
    for t in tickers:
        try:
            df, audit_df = run_wyckoff_anchored_backtest(t, use_ai=False, threshold=base_threshold, period="2y")
            if audit_df is None or audit_df.empty:
                continue
            
            engine = FactorEngine(BacktestConfig(period="2y"))
            factors = engine.compute(df)
            
            for _, row in audit_df.iterrows():
                entry_date = pd.to_datetime(row['entry_date']).tz_localize(None)
                if entry_date in factors.index:
                    feat = factors.loc[entry_date].to_dict()
                    feat['label'] = 1 if row['win'] else 0
                    feat['ticker'] = t
                    all_features.append(feat)
                    
        except Exception as e:
            log_message(f"Error on {t}: {e}")
            
    if len(all_features) < 5:
        log_message(f"Not enough trades for {slot}. Need at least 5.")
        return
        
    data = pd.DataFrame(all_features)
    X = data.drop(columns=['label', 'ticker'])
    y = data['label']
    
    # אימון מודל Random Forest לזיהוי העסקאות הטובות ביותר
    model = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42, class_weight='balanced')
    model.fit(X, y)
    
    train_acc = model.score(X, y)
    opt_th = calculate_optimal_threshold(model, X, y)
    
    safe_slot = clean_filename(slot)
    model_path = os.path.join(MODEL_DIR, f"model_{safe_slot}.pkl")
    
    # אריזת המודל והכנתו להורדה
    payload = {
        "model": model,
        "metadata": {
            "slot": slot,
            "train_acc": train_acc,
            "num_trades": len(data),
            "recommended_threshold": opt_th
        }
    }
    with open(model_path, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
        
    log_message(f"Successfully trained {slot}. Trades: {len(data)}, Acc: {train_acc:.2%}. Model saved to {model_path}.")

if __name__ == "__main__":
    if not os.path.exists(MODEL_DIR): os.makedirs(MODEL_DIR)
    write_status(state="running", progress=0, message="מתחיל אימון מקיף...")
    
    sectors = {
        "Growth": GROWTH_TICKERS,
        "Value": VALUE_TICKERS,
        "Commodities": COMMODITIES_TICKERS
    }
    
    for i, (name, ticks) in enumerate(sectors.items()):
        write_status(state="running", progress=int((i/len(sectors))*100), message=f"מאמן את סקטור {name}")
        process_sector(name, ticks, base_threshold=55)
        
    with open(DONE_FLAG, "w") as f:
        f.write("done")
    write_status(state="completed", progress=100, message="אימון המודלים הושלם. ניתן להורידם במסך ה-Monitor.")
