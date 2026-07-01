"""
Futures & Options Scanner (AlphaQuant)
Consolidated single-file module for fetching Price/Volume data, handling mock/real 
Open Interest and PCR data, and executing F&O sentiment scans.
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
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import requests
import yfinance as yf

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# ==============================================================================
# 1. CONFIGURATION & PATHS
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR.parent / "Output" / "futureoptions"
SOURCE_DIR = BASE_DIR.parent / "main" / "source"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NIFTY_500_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"

# Thresholds
PCR_HIGH_THRESHOLD = 1.5  # Often indicates Overbought/Bullish sentiment
PCR_LOW_THRESHOLD = 0.6   # Often indicates Oversold/Bearish sentiment
AGGRESSIVE_VOL_MULT = 1.5 # Volume must be 1.5x average to be 'Aggressive'
AVG_PERIOD_VOL = 10       # Lookback for averages

# Categories
CAT_FUT_OI = "Futures Open Interest"
CAT_FUT_LONG = "Futures Long Position"
CAT_FUT_SHORT = "Futures Short Position"
CAT_PCR = "Put Call Ratio"

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
class FOScanResult:
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
class TickerFOData:
    ticker: str
    timestamp: str
    last_close: float
    industry: Optional[str]
    last_oi: Optional[float]
    last_pcr: Optional[float]
    categories: Dict[str, Any]
    scan_summary: Dict[str, Any] = field(default_factory=dict)

# ==============================================================================
# 3. FETCHER (YFinance Integration)
# ==============================================================================
class FOFetcher:
    def fetch_data(self, ticker: str) -> pd.DataFrame:
        symbol = ticker.strip().upper()
        if not symbol.endswith((".NS", ".BO")):
            symbol = f"{symbol}.NS"

        try:
            df = yf.download(symbol, period="6mo", interval="1d", progress=False, auto_adjust=True, threads=False)
            if df.empty and symbol.endswith(".NS"):
                df = yf.download(symbol.replace(".NS", ".BO"), period="6mo", interval="1d", progress=False, auto_adjust=True)
                
            if df.empty:
                logger.warning(f"No data for {symbol}")
                return pd.DataFrame()

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            col_map = {'Adj Close': 'Close', 'adj close': 'Close', 'volume': 'Volume', 'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close'}
            df.rename(columns=col_map, inplace=True)
            df.columns = [c.capitalize() if isinstance(c, str) else c for c in df.columns]
            
            # Real F&O APIs inject OI here. Free yfinance lacks reliable OI.
            if 'Open Interest' not in df.columns and 'openInterest' not in df.columns:
                 df['OpenInterest'] = np.nan
            else:
                 if 'Open Interest' in df.columns: df.rename(columns={'Open Interest': 'OpenInterest'}, inplace=True)
                 if 'openInterest' in df.columns: df.rename(columns={'openInterest': 'OpenInterest'}, inplace=True)

            if 'PCR' not in df.columns:
                df['PCR'] = np.nan

            return df

        except Exception as e:
            logger.error(f"Fetch error for {ticker}: {e}")
            return pd.DataFrame()

# ==============================================================================
# 4. SCANNER (Signal Engine)
# ==============================================================================
class FOScanner:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.results: List[FOScanResult] = []

    def _get(self, col: str, offset: int = 0) -> Optional[float]:
        if self.df.empty or col not in self.df.columns or len(self.df) <= offset: return None
        val = self.df[col].iloc[-(offset + 1)]
        return float(val) if pd.notna(val) else None

    def _add(self, label: str, category: str, status: str, cond: bool, val: float, action: str):
        if cond:
            self.results.append(FOScanResult(label, category, status, cond, val, action))

    def run_all_scans(self) -> Dict[str, Dict[str, Any]]:
        self.results = []
        if self.df.empty or len(self.df) < 2: return {}

        c, prev_c = self._get('Close'), self._get('Close', 1)
        oi, prev_oi = self._get('OpenInterest'), self._get('OpenInterest', 1)
        vol = self._get('Volume')
        
        avg_vol = None
        if 'Volume' in self.df.columns and len(self.df) >= AVG_PERIOD_VOL:
             avg_vol = self.df['Volume'].rolling(AVG_PERIOD_VOL).mean().iloc[-1]
             
        pcr, prev_pcr = self._get('PCR'), self._get('PCR', 1)

        has_oi = (oi is not None and prev_oi is not None and oi > 0)
        has_pcr = (pcr is not None)
        price_up = (c > prev_c) if (c and prev_c) else False
        price_down = (c < prev_c) if (c and prev_c) else False
        oi_up = (has_oi and oi > prev_oi)
        oi_down = (has_oi and oi < prev_oi)
        high_vol = False
        if vol and avg_vol: high_vol = (vol > avg_vol * AGGRESSIVE_VOL_MULT)

        # 1. Futures Open Interest
        if has_oi:
            self._add("High Open Interest", CAT_FUT_OI, "Active", True, oi, "Neutral")
            oi_change = ((oi - prev_oi) / prev_oi) * 100 if prev_oi > 0 else 0.0
            status = "OI Gainer" if oi_change > 0 else "OI Loser"
            self._add(f"{status} ({oi_change:.1f}%)", CAT_FUT_OI, status, True, oi_change, "Neutral")
        else:
            self._add("Futures Data", CAT_FUT_OI, "Data Unavailable", True, 0, "Neutral")

        # 2. Futures Long Position Scans
        if price_up and oi_up:
            self._add("Long Build Up", CAT_FUT_LONG, "Bullish", True, c, "Buy")
            if high_vol: self._add("Aggressive New Long", CAT_FUT_LONG, "Strong Bullish", True, c, "Strong Buy")

        if price_up and oi_down:
            self._add("Short Covering", CAT_FUT_LONG, "Bullish", True, c, "Buy")
            if high_vol: self._add("Aggressive Short Covering", CAT_FUT_LONG, "Strong Bullish", True, c, "Strong Buy")

        # 3. Futures Short Position Scans
        if price_down and oi_up:
            self._add("Short Build Up", CAT_FUT_SHORT, "Bearish", True, c, "Sell")
            if high_vol: self._add("Aggressive New Short", CAT_FUT_SHORT, "Strong Bearish", True, c, "Strong Sell")

        if price_down and oi_down:
            self._add("Long Unwinding", CAT_FUT_SHORT, "Bearish", True, c, "Sell")
            if high_vol: self._add("Aggressive Long Unwinding", CAT_FUT_SHORT, "Strong Bearish", True, c, "Strong Sell")

        # 4. Put Call Ratio Scans
        if has_pcr:
            if pcr > PCR_HIGH_THRESHOLD: self._add("High PCR", CAT_PCR, "Overbought", True, pcr, "Neutral") 
            if pcr < PCR_LOW_THRESHOLD: self._add("Low PCR", CAT_PCR, "Oversold", True, pcr, "Neutral")
            if prev_pcr and pcr > prev_pcr: self._add("Rising PCR", CAT_PCR, "Bullish Sentiment", True, pcr, "Buy")
            if prev_pcr and pcr < prev_pcr: self._add("Falling PCR", CAT_PCR, "Bearish Sentiment", True, pcr, "Sell")
        else:
             self._add("PCR Data", CAT_PCR, "Data Unavailable", True, 0, "Neutral")

        # Grouping & Signaling
        grouped = {}
        for res in self.results:
            grouped.setdefault(res.category, []).append(res.to_dict())

        final = {}
        for cat in [CAT_FUT_OI, CAT_FUT_LONG, CAT_FUT_SHORT, CAT_PCR]:
            scans = grouped.get(cat, [])
            signal = self._calculate_signal(scans)
            final[cat] = {"signal": signal, "scans": scans}
        
        return final

    def _calculate_signal(self, scans: List[Dict[str, Any]]) -> str:
        score = sum({"Strong Buy": 2, "Buy": 1, "Sell": -1, "Strong Sell": -2}.get(s.get("action", "Neutral"), 0) for s in scans)
        if score >= 2: return "Strong Buy"
        if score >= 1: return "Buy"
        if score <= -2: return "Strong Sell"
        if score <= -1: return "Sell"
        return "Neutral"

# ==============================================================================
# 5. ORCHESTRATOR (Main Engine)
# ==============================================================================
def process_stock(ticker: str, fetcher: FOFetcher, master_map: List[Dict[str, Any]]) -> Optional[TickerFOData]:
    logger.info(f"Processing F&O for {ticker}...")
    
    df = fetcher.fetch_data(ticker)
    if df.empty:
        logger.warning(f"Skipping {ticker}: No data available.")
        return None
        
    scanner = FOScanner(df)
    category_results = scanner.run_all_scans()
    
    trig_count = sum(len(c['scans']) for c in category_results.values())
    signal_counts = {"Strong Buy": 0, "Buy": 0, "Neutral": 0, "Sell": 0, "Strong Sell": 0}
    for cat_data in category_results.values():
        sig = cat_data.get('signal', 'Neutral')
        if sig in signal_counts: signal_counts[sig] += 1
            
    last_close = float(df['Close'].iloc[-1]) if not df['Close'].empty else 0.0
    industry = get_industry_for_ticker(ticker, master_map)
    
    last_oi = float(df['OpenInterest'].iloc[-1]) if 'OpenInterest' in df.columns and not df['OpenInterest'].isna().iloc[-1] else None
    last_pcr = float(df['PCR'].iloc[-1]) if 'PCR' in df.columns and not df['PCR'].isna().iloc[-1] else None

    result = TickerFOData(
        ticker=ticker,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        last_close=last_close,
        industry=industry,
        last_oi=last_oi,
        last_pcr=last_pcr,
        categories=category_results,
        scan_summary={"triggered_total": trig_count, "signals": signal_counts}
    )

    file_path = OUTPUT_DIR / f"{ticker}_futureoptions.json"
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({
                "ticker": result.ticker,
                "timestamp": result.timestamp,
                "last_close": result.last_close,
                "industry": result.industry,
                "last_oi": result.last_oi,
                "last_pcr": result.last_pcr,
                "categories": result.categories,
                "scan_summary": result.scan_summary
            }, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save results for {ticker}: {e}")

    return result

def main():
    parser = argparse.ArgumentParser(description="Futures & Options Scan Engine")
    parser.add_argument("--ticker", type=str, help="Ticker to scan")
    parser.add_argument("--limit", type=int, help="Limit total stocks processed")
    args = parser.parse_args()

    fetcher = FOFetcher()
    master_map = load_master_industry_map()
    
    tickers = [args.ticker.upper()] if args.ticker else get_nifty_tickers()
    if args.limit: tickers = tickers[:args.limit]

    for t in tickers:
        process_stock(t, fetcher, master_map)

if __name__ == "__main__":
    main()