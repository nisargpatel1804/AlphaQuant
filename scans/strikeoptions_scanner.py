"""
Strike Options Scanner (AlphaQuant)
Consolidated single-file module for fetching Option Chains, identifying key 
Support/Resistance levels based on Open Interest, and detecting high activity strikes.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
OUTPUT_DIR = BASE_DIR.parent / "Output" / "strikeoptions"
SOURCE_DIR = BASE_DIR.parent / "main" / "source"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NIFTY_500_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"

# Thresholds
MIN_OI_THRESHOLD = 100  # Minimum Open Interest to consider a strike "significant"
MIN_VOL_THRESHOLD = 50  # Minimum Volume to consider "Active"

# Categories
CAT_CALL_OI = "Call Options OI"
CAT_PUT_OI = "Put Options OI"
CAT_ACTIVITY = "Options Activity"

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
class StrikeScanResult:
    label: str            
    category: str         
    strike_price: float   
    value: float          
    action: str = "Neutral" 
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "category": self.category,
            "strike_price": self.strike_price,
            "value": self.value,
            "action": self.action
        }

@dataclass
class TickerStrikeData:
    ticker: str
    timestamp: str
    last_close: float
    expiry_date: str
    industry: Optional[str]
    categories: Dict[str, Any]
    scan_summary: Dict[str, Any] = field(default_factory=dict)

# ==============================================================================
# 3. FETCHER (YFinance Integration)
# ==============================================================================
class StrikeOptionsFetcher:
    def fetch_option_chain(self, ticker: str) -> Tuple[pd.DataFrame, pd.DataFrame, float, str]:
        symbol = ticker.strip().upper()
        if not symbol.endswith((".NS", ".BO")):
            symbol = f"{symbol}.NS"

        try:
            yf_ticker = yf.Ticker(symbol)
            expirations = yf_ticker.options
            
            if not expirations:
                logger.warning(f"No options data found for {symbol}")
                return pd.DataFrame(), pd.DataFrame(), 0.0, ""

            nearest_expiry = expirations[0]
            chain = yf_ticker.option_chain(nearest_expiry)
            calls, puts = chain.calls, chain.puts
            
            hist = yf_ticker.history(period="1d")
            price = float(hist['Close'].iloc[-1]) if not hist.empty else 0.0

            return calls, puts, price, nearest_expiry

        except Exception as e:
            logger.error(f"Error fetching options for {ticker}: {e}")
            return pd.DataFrame(), pd.DataFrame(), 0.0, ""

# ==============================================================================
# 4. SCANNER (Signal Engine)
# ==============================================================================
class StrikeOptionsScanner:
    def __init__(self, calls: pd.DataFrame, puts: pd.DataFrame):
        self.calls = calls
        self.puts = puts
        self.results: List[StrikeScanResult] = []

    def _process_side(self, df: pd.DataFrame, option_type: str):
        if df.empty: return

        if 'openInterest' in df.columns:
            df['openInterest'] = pd.to_numeric(df['openInterest'], errors='coerce').fillna(0)
        else:
            return 

        if 'volume' in df.columns:
            df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0)
        else:
            df['volume'] = 0
        
        # Filter noise: Ignore illiquid strikes
        valid_df = df[df['openInterest'] > MIN_OI_THRESHOLD]
        if valid_df.empty: return

        # 1. High OI (Highest Open Interest)
        max_oi_idx = valid_df['openInterest'].idxmax()
        max_oi_row = valid_df.loc[max_oi_idx]
        
        cat = CAT_CALL_OI if option_type == "Call" else CAT_PUT_OI
        
        self.results.append(StrikeScanResult(
            label=f"Highest {option_type} OI",
            category=cat,
            strike_price=float(max_oi_row['strike']),
            value=float(max_oi_row['openInterest']),
            action="Neutral" # Support/Resistance levels are inherently neutral until price interacts
        ))
        
        # 2. Active Contracts (Highest Volume)
        vol_df = df[df['volume'] > MIN_VOL_THRESHOLD]
        if not vol_df.empty:
            max_vol_idx = vol_df['volume'].idxmax()
            max_vol_row = vol_df.loc[max_vol_idx]
            
            self.results.append(StrikeScanResult(
                label=f"Most Active {option_type}",
                category=CAT_ACTIVITY,
                strike_price=float(max_vol_row['strike']),
                value=float(max_vol_row['volume']),
                action="Neutral"
            ))

    def run_all_scans(self) -> Dict[str, Dict[str, Any]]:
        self.results = []
        
        self._process_side(self.calls, "Call")
        self._process_side(self.puts, "Put")
        
        grouped = {}
        for res in self.results:
            grouped.setdefault(res.category, []).append(res.to_dict())
            
        final_output = {}
        for cat in [CAT_CALL_OI, CAT_PUT_OI, CAT_ACTIVITY]:
            scans = grouped.get(cat, [])
            final_output[cat] = {"signal": "Neutral", "scans": scans}
            
        return final_output

# ==============================================================================
# 5. ORCHESTRATOR (Main Engine)
# ==============================================================================
def process_stock(ticker: str, fetcher: StrikeOptionsFetcher, master_map: List[Dict[str, Any]]) -> Optional[TickerStrikeData]:
    logger.info(f"Processing Strike Options for {ticker}...")
    
    calls, puts, price, expiry = fetcher.fetch_option_chain(ticker)
    
    if calls.empty and puts.empty:
        logger.warning(f"Skipping {ticker}: No option chain data found.")
        return None
        
    scanner = StrikeOptionsScanner(calls, puts)
    category_results = scanner.run_all_scans()
    
    trig_count = sum(len(c['scans']) for c in category_results.values())
    signal_counts = {"Strong Buy": 0, "Buy": 0, "Neutral": 0, "Sell": 0, "Strong Sell": 0}
    for cat_data in category_results.values():
        sig = cat_data.get('signal', 'Neutral')
        if sig in signal_counts: signal_counts[sig] += 1
            
    industry = get_industry_for_ticker(ticker, master_map)

    result = TickerStrikeData(
        ticker=ticker,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        last_close=price,
        expiry_date=expiry,
        industry=industry,
        categories=category_results,
        scan_summary={"triggered_total": trig_count, "signals": signal_counts}
    )

    file_path = OUTPUT_DIR / f"{ticker}_strikeoptions.json"
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({
                "ticker": result.ticker,
                "timestamp": result.timestamp,
                "last_close": result.last_close,
                "expiry_date": result.expiry_date,
                "industry": result.industry,
                "categories": result.categories,
                "scan_summary": result.scan_summary
            }, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save results for {ticker}: {e}")

    return result

def main():
    parser = argparse.ArgumentParser(description="Strike Options Scan Engine")
    parser.add_argument("--ticker", type=str, help="Ticker to scan")
    parser.add_argument("--limit", type=int, help="Limit total stocks processed")
    args = parser.parse_args()

    fetcher = StrikeOptionsFetcher()
    master_map = load_master_industry_map()
    
    tickers = [args.ticker.upper()] if args.ticker else get_nifty_tickers()
    if args.limit: tickers = tickers[:args.limit]

    for t in tickers:
        process_stock(t, fetcher, master_map)

if __name__ == "__main__":
    main()