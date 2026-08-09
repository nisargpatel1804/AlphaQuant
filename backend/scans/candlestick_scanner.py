# backend/scans/candlestick_scanner.py

"""
Candlestick Scanner (AlphaQuant)
Consolidated single-file module for fetching daily OHLCV data, calculating 
24 precise candlestick patterns, and categorizing signals.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import numpy as np
import pandas as pd
import requests
import yfinance as yf

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")

# ==============================================================================
# 1. CONFIGURATION & PATHS
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
OUTPUT_DIR = BASE_DIR / "output" / "data"                  # backend/output/data/
SOURCE_DIR = BASE_DIR / "source"                           # backend/source/

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NIFTY_500_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"

# Candle Shape Thresholds
DOJI_BODY_THRESHOLD = 0.03 
MARUBOZU_SHADOW_THRESHOLD = 0.05 
HAMMER_SHADOW_MULTIPLIER = 2.0
HAMMER_UPPER_SHADOW_LIMIT = 0.1 
LONG_BODY_MULTIPLIER = 1.5
AVG_BODY_PERIOD = 10

# Categories
CAT_BULLISH = "Bullish Scans"
CAT_BULLISH_CONT = "Bullish Continuation Scans"
CAT_BULLISH_REV = "Bullish Reversal Scans"
CAT_BEARISH = "Bearish Scans"
CAT_BEARISH_CONT = "Bearish Continuation Scans"
CAT_BEARISH_REV = "Bearish Reversal Scans"
CAT_NEUTRAL = "Neutral Scans"

# ==============================================================================
# 2. UTILITIES & DATA MODELS
# ==============================================================================
def load_master_industry_map() -> List[Dict[str, Any]]:
    path = SOURCE_DIR / "master_industry_map.json"
    if not path.exists(): return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [row for row in data if isinstance(row, dict)]
    except Exception: return []

def get_industry_for_ticker(ticker: str, master_map: List[Dict[str, Any]]) -> Optional[str]:
    target = ticker.strip().upper()
    for entry in master_map:
        if target in [str(t).strip().upper() for t in entry.get("stocks", [])]:
            return entry.get("industry")
    return None

def get_nifty_tickers(retries: int = 4) -> List[str]:
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
    ]
    sess = requests.Session()
    for attempt in range(1, retries + 1):
        try:
            resp = sess.get(NIFTY_500_URL, timeout=30, headers={"User-Agent": random.choice(user_agents)})
            resp.raise_for_status()
            reader = csv.DictReader(resp.content.decode("utf-8", errors="replace").splitlines())
            return [row["Symbol"].strip().upper() for row in reader if row.get("Symbol")]
        except requests.RequestException:
            if attempt == retries: break
            time.sleep(1.5 * attempt)
            
    fallback = SOURCE_DIR / "ind_nifty500list.csv"
    if fallback.exists():
        with open(fallback, "r", encoding="utf-8") as f:
            return [row["Symbol"].strip().upper() for row in csv.DictReader(f) if row.get("Symbol")]
    return []

@dataclass
class CandleScanResult:
    label: str            
    category: str         
    status: str           
    condition_met: bool
    value: Optional[float] = None 
    action: str = "Neutral" 
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "category": self.category,
            "status": self.status,
            "value": self.value,
            "action": self.action,
            "condition_met": self.condition_met
        }

@dataclass
class TickerCandleData:
    ticker: str
    timestamp: str
    last_close: float
    industry: Optional[str]
    categories: Dict[str, Any]
    scan_summary: Dict[str, Any] = field(default_factory=dict)

# ==============================================================================
# 3. FETCHER (YFinance)
# ==============================================================================
class CandleFetcher:
    def fetch_data(self, ticker: str) -> pd.DataFrame:
        symbol = ticker.strip().upper()
        if not symbol.endswith((".NS", ".BO")):
            symbol = f"{symbol}.NS"

        try:
            df = yf.download(symbol, period="3mo", interval="1d", progress=False, auto_adjust=True)
            if df.empty and symbol.endswith(".NS"):
                df = yf.download(symbol.replace(".NS", ".BO"), period="3mo", interval="1d", progress=False, auto_adjust=True)
            if df.empty: return pd.DataFrame()

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            col_map = {'Adj Close': 'Close', 'adj close': 'Close', 'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}
            df.rename(columns=col_map, inplace=True)
            df.columns = [c.capitalize() if isinstance(c, str) else c for c in df.columns]
            return df
        except Exception as e:
            logging.error(f"Fetch error for {ticker}: {e}")
            return pd.DataFrame()

# ==============================================================================
# 4. PATTERN RECOGNITION MATH
# ==============================================================================
class PatternRecognizer:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.open, self.close, self.high, self.low = df['Open'], df['Close'], df['High'], df['Low']
        
        self.body = abs(self.close - self.open)
        self.range = (self.high - self.low).replace(0, np.nan) 
        
        self.upper_shadow = self.high - np.maximum(self.close, self.open)
        self.lower_shadow = np.minimum(self.close, self.open) - self.low
        
        self.avg_body = self.body.rolling(AVG_BODY_PERIOD).mean()
        self.is_bullish = self.close > self.open
        self.is_bearish = self.close < self.open

    def _is_doji(self, idx=-1):
        rng = self.range.iloc[idx]
        if pd.isna(rng): return False
        return (self.body.iloc[idx] / rng) <= DOJI_BODY_THRESHOLD

    def _is_long(self, idx=-1):
        if pd.isna(self.avg_body.iloc[idx]): return False
        return self.body.iloc[idx] > (self.avg_body.iloc[idx] * LONG_BODY_MULTIPLIER)

    def _is_small(self, idx=-1):
        if pd.isna(self.avg_body.iloc[idx]): return True
        return self.body.iloc[idx] < self.avg_body.iloc[idx]

    # --- 1. Bullish Scans ---
    def white_marubozu(self):
        i = -1
        if not self.is_bullish.iloc[i] or not self._is_long(i): return False
        return (self.upper_shadow.iloc[i] <= self.body.iloc[i] * MARUBOZU_SHADOW_THRESHOLD) and \
               (self.lower_shadow.iloc[i] <= self.body.iloc[i] * MARUBOZU_SHADOW_THRESHOLD)

    # --- 2. Bullish Continuation ---
    def bullish_engulfing(self):
        i = -1
        if not (self.is_bearish.iloc[i-1] and self.is_bullish.iloc[i]): return False
        return (self.close.iloc[i] > self.open.iloc[i-1]) and (self.open.iloc[i] < self.close.iloc[i-1])

    def rising_three_methods(self):
        if len(self.df) < 5: return False
        first_long = self._is_long(-5) and self.is_bullish.iloc[-5]
        last_long = self._is_long(-1) and self.is_bullish.iloc[-1] and (self.close.iloc[-1] > self.close.iloc[-5])
        if not (first_long and last_long): return False
        middle_candles = self.df.iloc[-4:-1]
        for idx in range(3):
            if not (middle_candles['High'].iloc[idx] < self.high.iloc[-5] and middle_candles['Low'].iloc[idx] > self.low.iloc[-5]):
                return False
        return True

    # --- 3. Bullish Reversal ---
    def hammer(self):
        i = -1
        if len(self.df) < 6: return False
        is_downtrend = self.close.iloc[i] < self.close.iloc[i-5]
        is_pattern = (self.lower_shadow.iloc[i] >= HAMMER_SHADOW_MULTIPLIER * self.body.iloc[i]) and \
                     (self.upper_shadow.iloc[i] <= self.body.iloc[i] * HAMMER_UPPER_SHADOW_LIMIT)
        return is_downtrend and is_pattern

    def inverted_hammer(self):
        i = -1
        if len(self.df) < 6: return False
        is_downtrend = self.close.iloc[i] < self.close.iloc[i-5]
        is_pattern = (self.upper_shadow.iloc[i] >= HAMMER_SHADOW_MULTIPLIER * self.body.iloc[i]) and \
                     (self.lower_shadow.iloc[i] <= self.body.iloc[i] * HAMMER_UPPER_SHADOW_LIMIT)
        return is_downtrend and is_pattern

    def piercing_pattern(self):
        i = -1
        if not (self.is_bearish.iloc[i-1] and self.is_bullish.iloc[i]): return False
        midpoint = self.close.iloc[i-1] + ((self.open.iloc[i-1] - self.close.iloc[i-1]) / 2)
        return (self.open.iloc[i] < self.low.iloc[i-1]) and (self.close.iloc[i] > midpoint)

    def morning_star(self):
        if len(self.df) < 3: return False
        i = -1
        first = self.is_bearish.iloc[i-2] and self._is_long(i-2)
        second = self._is_small(i-1)
        third = self.is_bullish.iloc[i] and self._is_long(i) and (self.close.iloc[i] > (self.open.iloc[i-2] + self.close.iloc[i-2])/2)
        return first and second and third

    def bullish_harami(self):
        i = -1
        if not (self.is_bearish.iloc[i-1] and self.is_bullish.iloc[i]): return False
        return self._is_long(i-1) and (self.open.iloc[i] < self.open.iloc[i-1]) and \
               (self.close.iloc[i] > self.close.iloc[i-1]) and self._is_small(i)

    def three_white_soldiers(self):
        if len(self.df) < 3: return False
        return all(self.is_bullish.iloc[i] for i in range(-3, 0)) and \
               all(self._is_long(i) for i in range(-3, 0)) and \
               (self.close.iloc[-1] > self.close.iloc[-2] > self.close.iloc[-3])

    def three_inside_up(self):
        if len(self.df) < 3: return False
        harami = self.is_bearish.iloc[-3] and self.is_bullish.iloc[-2] and \
                 (self.open.iloc[-2] < self.open.iloc[-3]) and (self.close.iloc[-2] > self.close.iloc[-3])
        confirm = self.is_bullish.iloc[-1] and (self.close.iloc[-1] > self.close.iloc[-2])
        return harami and confirm

    def three_outside_up(self):
        if len(self.df) < 3: return False
        engulfing = self.is_bearish.iloc[-3] and self.is_bullish.iloc[-2] and \
                    (self.close.iloc[-2] > self.open.iloc[-3]) and (self.open.iloc[-2] < self.close.iloc[-3])
        confirm = self.is_bullish.iloc[-1] and (self.close.iloc[-1] > self.close.iloc[-2])
        return engulfing and confirm

    def bullish_counterattack(self):
        i = -1
        if not (self.is_bearish.iloc[i-1] and self.is_bullish.iloc[i]): return False
        is_long_bear = self._is_long(i-1)
        close_match = abs(self.close.iloc[i] - self.close.iloc[i-1]) / self.close.iloc[i-1] < 0.005 
        return is_long_bear and close_match

    # --- 4. Bearish Scans ---
    def black_marubozu(self):
        i = -1
        if not self.is_bearish.iloc[i] or not self._is_long(i): return False
        return (self.upper_shadow.iloc[i] <= self.body.iloc[i] * MARUBOZU_SHADOW_THRESHOLD) and \
               (self.lower_shadow.iloc[i] <= self.body.iloc[i] * MARUBOZU_SHADOW_THRESHOLD)

    # --- 5. Bearish Continuation ---
    def falling_three_methods(self):
        if len(self.df) < 5: return False
        first_long = self._is_long(-5) and self.is_bearish.iloc[-5]
        last_long = self._is_long(-1) and self.is_bearish.iloc[-1] and (self.close.iloc[-1] < self.close.iloc[-5])
        if not (first_long and last_long): return False
        middle_candles = self.df.iloc[-4:-1]
        for idx in range(3):
            if not (middle_candles['Low'].iloc[idx] > self.low.iloc[-5] and middle_candles['High'].iloc[idx] < self.high.iloc[-5]):
                return False
        return True

    # --- 6. Bearish Reversal ---
    def hanging_man(self):
        i = -1
        if len(self.df) < 6: return False
        is_uptrend = self.close.iloc[i] > self.close.iloc[i-5]
        is_pattern = (self.lower_shadow.iloc[i] >= HAMMER_SHADOW_MULTIPLIER * self.body.iloc[i]) and \
                     (self.upper_shadow.iloc[i] <= self.body.iloc[i] * HAMMER_UPPER_SHADOW_LIMIT)
        return is_uptrend and is_pattern

    def shooting_star(self):
        i = -1
        if len(self.df) < 6: return False
        is_uptrend = self.close.iloc[i] > self.close.iloc[i-5]
        is_pattern = (self.upper_shadow.iloc[i] >= HAMMER_SHADOW_MULTIPLIER * self.body.iloc[i]) and \
                     (self.lower_shadow.iloc[i] <= self.body.iloc[i] * HAMMER_UPPER_SHADOW_LIMIT)
        return is_uptrend and is_pattern

    def dark_cloud_cover(self):
        i = -1
        if not (self.is_bullish.iloc[i-1] and self.is_bearish.iloc[i]): return False
        midpoint = self.close.iloc[i-1] - ((self.close.iloc[i-1] - self.open.iloc[i-1]) / 2)
        return (self.open.iloc[i] > self.high.iloc[i-1]) and (self.close.iloc[i] < midpoint)

    def evening_star(self):
        if len(self.df) < 3: return False
        i = -1
        first = self.is_bullish.iloc[i-2] and self._is_long(i-2)
        second = self._is_small(i-1)
        third = self.is_bearish.iloc[i] and self._is_long(i) and (self.close.iloc[i] < (self.open.iloc[i-2] + self.close.iloc[i-2])/2)
        return first and second and third

    def bearish_harami(self):
        i = -1
        if not (self.is_bullish.iloc[i-1] and self.is_bearish.iloc[i]): return False
        return self._is_long(i-1) and (self.open.iloc[i] < self.close.iloc[i-1]) and \
               (self.close.iloc[i] > self.open.iloc[i-1]) and self._is_small(i)

    def three_black_crows(self):
        if len(self.df) < 3: return False
        return all(self.is_bearish.iloc[i] for i in range(-3, 0)) and \
               all(self._is_long(i) for i in range(-3, 0)) and \
               (self.close.iloc[-1] < self.close.iloc[-2] < self.close.iloc[-3])

    def three_inside_down(self):
        if len(self.df) < 3: return False
        harami = self.is_bullish.iloc[-3] and self.is_bearish.iloc[-2] and \
                 (self.open.iloc[-2] < self.close.iloc[-3]) and (self.close.iloc[-2] > self.open.iloc[-3])
        confirm = self.is_bearish.iloc[-1] and (self.close.iloc[-1] < self.close.iloc[-2])
        return harami and confirm

    def three_outside_down(self):
        if len(self.df) < 3: return False
        engulfing = self.is_bullish.iloc[-3] and self.is_bearish.iloc[-2] and \
                    (self.close.iloc[-2] < self.open.iloc[-3]) and (self.open.iloc[-2] > self.close.iloc[-3])
        confirm = self.is_bearish.iloc[-1] and (self.close.iloc[-1] < self.close.iloc[-2])
        return engulfing and confirm

    def bearish_counterattack(self):
        i = -1
        if not (self.is_bullish.iloc[i-1] and self.is_bearish.iloc[i]): return False
        is_long_bull = self._is_long(i-1)
        close_match = abs(self.close.iloc[i] - self.close.iloc[i-1]) / self.close.iloc[i-1] < 0.005 
        return is_long_bull and close_match

    # --- 7. Neutral ---
    def doji(self):
        return self._is_doji(-1)

# ==============================================================================
# 5. SCANNER (Signal Execution)
# ==============================================================================
class CandleScanner:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.pr = PatternRecognizer(df)
        self.results: List[CandleScanResult] = []

    def _add(self, label: str, category: str, cond: bool, action: str):
        if cond:
            self.results.append(CandleScanResult(
                label=label, 
                category=category, 
                status="Pattern Formed", 
                condition_met=True, 
                value=float(self.df['Close'].iloc[-1]), 
                action=action
            ))

    def run_all_scans(self) -> Dict[str, Dict[str, Any]]:
        self.results = []
        if self.df.empty: return {}

        # 1. Bullish Scans
        self._add("White Marubozu", CAT_BULLISH, self.pr.white_marubozu(), "Buy")

        # 2. Bullish Continuation
        self._add("Bullish Engulfing", CAT_BULLISH_CONT, self.pr.bullish_engulfing(), "Buy")
        self._add("Rising Three Methods", CAT_BULLISH_CONT, self.pr.rising_three_methods(), "Buy")

        # 3. Bullish Reversal
        self._add("Hammer", CAT_BULLISH_REV, self.pr.hammer(), "Strong Buy")
        self._add("Inverted Hammer", CAT_BULLISH_REV, self.pr.inverted_hammer(), "Buy")
        self._add("Piercing Pattern", CAT_BULLISH_REV, self.pr.piercing_pattern(), "Strong Buy")
        self._add("Morning Star", CAT_BULLISH_REV, self.pr.morning_star(), "Strong Buy")
        self._add("Bullish Harami", CAT_BULLISH_REV, self.pr.bullish_harami(), "Buy")
        self._add("Three White Soldiers", CAT_BULLISH_REV, self.pr.three_white_soldiers(), "Strong Buy")
        self._add("Three Inside Up", CAT_BULLISH_REV, self.pr.three_inside_up(), "Buy")
        self._add("Three Outside Up", CAT_BULLISH_REV, self.pr.three_outside_up(), "Buy")
        self._add("Bullish Counterattack", CAT_BULLISH_REV, self.pr.bullish_counterattack(), "Buy")

        # 4. Bearish
        self._add("Black Marubozu", CAT_BEARISH, self.pr.black_marubozu(), "Sell")

        # 5. Bearish Continuation
        self._add("Falling Three Methods", CAT_BEARISH_CONT, self.pr.falling_three_methods(), "Sell")

        # 6. Bearish Reversal
        self._add("Hanging Man", CAT_BEARISH_REV, self.pr.hanging_man(), "Sell")
        self._add("Shooting Star", CAT_BEARISH_REV, self.pr.shooting_star(), "Strong Sell")
        self._add("Dark Cloud Cover", CAT_BEARISH_REV, self.pr.dark_cloud_cover(), "Strong Sell")
        self._add("Evening Star", CAT_BEARISH_REV, self.pr.evening_star(), "Strong Sell")
        self._add("Bearish Harami", CAT_BEARISH_REV, self.pr.bearish_harami(), "Sell")
        self._add("Three Black Crows", CAT_BEARISH_REV, self.pr.three_black_crows(), "Strong Sell")
        self._add("Three Inside Down", CAT_BEARISH_REV, self.pr.three_inside_down(), "Sell")
        self._add("Three Outside Down", CAT_BEARISH_REV, self.pr.three_outside_down(), "Sell")
        self._add("Bearish Counterattack", CAT_BEARISH_REV, self.pr.bearish_counterattack(), "Sell")

        # 7. Neutral
        self._add("Doji", CAT_NEUTRAL, self.pr.doji(), "Neutral")

        # Grouping & Signaling
        grouped = {}
        for res in self.results:
            grouped.setdefault(res.category, []).append(res.to_dict())

        final = {}
        all_cats = [CAT_BULLISH, CAT_BULLISH_CONT, CAT_BULLISH_REV, CAT_BEARISH, CAT_BEARISH_CONT, CAT_BEARISH_REV, CAT_NEUTRAL]
        for cat in all_cats:
            scans = grouped.get(cat, [])
            signal = self._calculate_signal(scans, cat)
            final[cat] = {"signal": signal, "scans": scans}
            
        return final

    def _calculate_signal(self, scans: List[Dict[str, Any]], category: str) -> str:
        if not scans: return "Neutral"
        if "Bullish" in category:
            if any(s.get('action') == 'Strong Buy' for s in scans): return "Strong Buy"
            return "Buy"
        if "Bearish" in category:
            if any(s.get('action') == 'Strong Sell' for s in scans): return "Strong Sell"
            return "Sell"
        return "Neutral"

# ==============================================================================
# 6. ORCHESTRATOR (Main Engine)
# ==============================================================================
def process_stock(ticker: str, fetcher: CandleFetcher, master_map: List[Dict[str, Any]]) -> Optional[TickerCandleData]:
    logging.info(f"Processing Candlestick Patterns for {ticker}...")
    
    df = fetcher.fetch_data(ticker)
    if df.empty:
        logging.warning(f"No data for {ticker}. Skipping.")
        return None
        
    scanner = CandleScanner(df)
    category_results = scanner.run_all_scans()
    
    trig_count = sum(len(c['scans']) for c in category_results.values())
    signal_counts = {"Strong Buy": 0, "Buy": 0, "Neutral": 0, "Sell": 0, "Strong Sell": 0}
    
    for cat_data in category_results.values():
        sig = cat_data.get('signal', 'Neutral')
        if sig in signal_counts: signal_counts[sig] += 1
            
    last_close = float(df['Close'].iloc[-1]) if 'Close' in df.columns and not df['Close'].empty else 0.0
    industry = get_industry_for_ticker(ticker, master_map)

    result = TickerCandleData(
        ticker=ticker,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        last_close=last_close,
        industry=industry,
        categories=category_results,
        scan_summary={"triggered_total": trig_count, "signals": signal_counts}
    )

    file_path = OUTPUT_DIR / f"{ticker}_candlestick.json"
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({
                "ticker": result.ticker,
                "timestamp": result.timestamp,
                "last_close": result.last_close,
                "industry": result.industry,
                "categories": result.categories,
                "scan_summary": result.scan_summary
            }, f, indent=4)
    except Exception as e:
        logging.error(f"Failed to save results for {ticker}: {e}")

    return result

def main():
    parser = argparse.ArgumentParser(description="Candlestick Scan Engine")
    parser.add_argument("--ticker", type=str, help="Ticker to scan")
    parser.add_argument("--limit", type=int, help="Limit total stocks processed")
    args = parser.parse_args()

    fetcher = CandleFetcher()
    master_map = load_master_industry_map()
    
    tickers = [args.ticker.upper()] if args.ticker else get_nifty_tickers()
    if args.limit: tickers = tickers[:args.limit]

    for t in tickers:
        process_stock(t, fetcher, master_map)

if __name__ == "__main__":
    main()