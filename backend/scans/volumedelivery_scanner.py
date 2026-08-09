# backend/scans/volumedelivery_scanner.py

"""
Volume & Delivery Scanner (AlphaQuant)
Consolidated single-file module for fetching OHLCV data, analyzing daily, weekly, 
and monthly volume/delivery trends, detecting spikes, and generating 
accumulation/distribution signals.
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
BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
OUTPUT_DIR = BASE_DIR / "output" / "data"                  # backend/output/data/
SOURCE_DIR = BASE_DIR / "source"                           # backend/source/

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NIFTY_500_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"

# Thresholds
HIGH_DELIVERY_PCT = 50.0       # > 50% delivery is considered high
VERY_HIGH_DELIVERY_PCT = 75.0  # > 75% delivery

HIGH_VOLUME_MULT = 1.5         # 1.5x the average volume
VERY_HIGH_VOLUME_MULT = 2.5    # 2.5x the average volume

AVG_PERIOD_DAILY = 10          # 10-day average for daily scans
AVG_PERIOD_WEEKLY = 4          # 4-week average
AVG_PERIOD_MONTHLY = 3         # 3-month average

# Categories
CAT_DAILY_VD = "Daily Volume & Delivery"
CAT_WEEKLY_VD = "Weekly Volume & Delivery"
CAT_MONTHLY_VD = "Monthly Volume & Delivery"

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
class VolumeDeliveryResult:
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
class TickerVolumeDeliveryData:
    ticker: str
    timestamp: str
    last_close: float
    last_volume: float
    industry: Optional[str]
    categories: Dict[str, Any]
    scan_summary: Dict[str, Any] = field(default_factory=dict)

# ==============================================================================
# 3. FETCHER (YFinance Integration)
# ==============================================================================
class VolumeDeliveryFetcher:
    def fetch_data(self, ticker: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        symbol = ticker.strip().upper()
        if not symbol.endswith((".NS", ".BO")):
            symbol = f"{symbol}.NS"

        try:
            df = yf.download(symbol, period="1y", interval="1d", progress=False, auto_adjust=True, threads=False)
            
            if df.empty and symbol.endswith(".NS"):
                df = yf.download(symbol.replace(".NS", ".BO"), period="1y", interval="1d", progress=False, auto_adjust=True)

            if df.empty:
                logger.warning(f"No data for {symbol}")
                return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            col_map = {'Adj Close': 'Close', 'adj close': 'Close', 'volume': 'Volume', 'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close'}
            df.rename(columns=col_map, inplace=True)
            df.columns = [c.capitalize() if isinstance(c, str) else c for c in df.columns]

            # Delivery fields are synthesized when the source data does not provide them.
            if 'Delivery_qty' not in df.columns: df['Delivery_qty'] = None 
            if 'Delivery_pct' not in df.columns: df['Delivery_pct'] = None

            weekly_df = self._resample(df, 'W-FRI')
            monthly_df = self._resample(df, 'ME')

            return df, weekly_df, monthly_df

        except Exception as e:
            logger.error(f"Fetch error for {ticker}: {e}")
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    def _resample(self, df: pd.DataFrame, rule: str) -> pd.DataFrame:
        if df.empty: return pd.DataFrame()
        
        agg_dict = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}
        if 'Delivery_qty' in df.columns and df['Delivery_qty'].notna().any():
             agg_dict['Delivery_qty'] = 'sum'
        
        agg_dict = {k: v for k, v in agg_dict.items() if k in df.columns}
        
        try:
            res = df.resample(rule).agg(agg_dict).dropna(subset=['Close'])
            if 'Delivery_qty' in res.columns and 'Volume' in res.columns:
                res['Delivery_pct'] = (res['Delivery_qty'] / res['Volume'].replace(0, 1)) * 100
            else:
                 res['Delivery_pct'] = None
            return res
        except Exception:
            return pd.DataFrame()

# ==============================================================================
# 4. SCANNER (Signal Engine)
# ==============================================================================
class VolumeDeliveryScanner:
    def __init__(self, daily_df: pd.DataFrame, weekly_df: pd.DataFrame, monthly_df: pd.DataFrame):
        self.d = daily_df
        self.w = weekly_df
        self.m = monthly_df
        self.results: List[VolumeDeliveryResult] = []

    def _get_val(self, df: pd.DataFrame, col: str, offset: int = 0) -> Optional[float]:
        col_match = next((c for c in df.columns if c.lower() == col.lower()), None)
        if df.empty or col_match is None or len(df) <= offset:
            return None
        val = df[col_match].iloc[-(offset + 1)]
        return float(val) if pd.notna(val) else None

    def _determine_action(self, df: pd.DataFrame, is_bullish_event: bool) -> str:
        if df.empty or len(df) < 2: return "Neutral"
        
        close_col = next((c for c in df.columns if c.lower() == 'close'), None)
        if not close_col: return "Neutral"

        close = df[close_col].iloc[-1]
        prev_close = df[close_col].iloc[-2]
        
        if is_bullish_event:
            return "Buy" if close > prev_close else "Neutral" 
        
        if close > prev_close * 1.01: return "Strong Buy"
        if close > prev_close: return "Buy"
        if close < prev_close * 0.99: return "Strong Sell"
        if close < prev_close: return "Sell"
        return "Neutral"

    def _add_res(self, label: str, category: str, status: str, cond: bool, val: Optional[float], action: str):
        if cond:
            self.results.append(VolumeDeliveryResult(label, category, status, cond, val, action))

    def _run_period_scans(self, df: pd.DataFrame, category: str, avg_period: int):
        if df.empty or len(df) < avg_period + 1: return

        vol = self._get_val(df, 'Volume')
        del_qty = self._get_val(df, 'Delivery_qty') 
        del_pct = self._get_val(df, 'Delivery_pct')
        
        prev_vol = self._get_val(df, 'Volume', 1)
        prev_del_qty = self._get_val(df, 'Delivery_qty', 1)
        
        vol_col = next((c for c in df.columns if c.lower() == 'volume'), None)
        avg_vol = df[vol_col].rolling(window=avg_period).mean().iloc[-1] if vol_col else None
        
        avg_del_qty = None
        del_qty_col = next((c for c in df.columns if c.lower() == 'delivery_qty'), None)
        if del_qty_col:
            avg_del_qty = df[del_qty_col].rolling(window=avg_period).mean().iloc[-1]

        # 1. High Trade Quantity (Volume > Average)
        if vol and avg_vol and vol > avg_vol * HIGH_VOLUME_MULT:
            status = "Volume Spike"
            if vol > avg_vol * VERY_HIGH_VOLUME_MULT: status = "Ultra High Volume"
            action = self._determine_action(df, False)
            self._add_res("High Trade Quantity", category, status, True, vol, action)

        # 2. Higher Trade Quantity (Volume > Prev Volume)
        if vol and prev_vol and vol > prev_vol:
            action = self._determine_action(df, False)
            self._add_res("Higher Trade Quantity", category, "Higher than Prev", True, vol, "Buy" if action in ["Buy", "Strong Buy"] else "Sell")

        # 3. High Delivery Percentage
        if del_pct is not None:
            if del_pct > HIGH_DELIVERY_PCT:
                status = "High Delivery %"
                action = self._determine_action(df, True)
                self._add_res("High Delivery Percentage", category, status, True, del_pct, action)

        # 4. High Delivery Quantity (vs Average)
        if del_qty is not None and avg_del_qty is not None:
            if del_qty > avg_del_qty * HIGH_VOLUME_MULT:
                action = self._determine_action(df, True)
                self._add_res("High Delivery Quantity", category, "Delivery Spike", True, del_qty, action)

        # 5. Higher Delivery Quantity (vs Prev)
        if del_qty is not None and prev_del_qty is not None:
            if del_qty > prev_del_qty:
                action = self._determine_action(df, True)
                self._add_res("Higher Delivery Quantity", category, "Rising Delivery", True, del_qty, action)

    def run_all(self) -> Dict[str, Dict[str, Any]]:
        self.results = []
        
        self._run_period_scans(self.d, CAT_DAILY_VD, AVG_PERIOD_DAILY)
        self._run_period_scans(self.w, CAT_WEEKLY_VD, AVG_PERIOD_WEEKLY)
        self._run_period_scans(self.m, CAT_MONTHLY_VD, AVG_PERIOD_MONTHLY)
        
        grouped = {}
        for res in self.results:
            grouped.setdefault(res.category, []).append(res.to_dict())
            
        final_output = {}
        for cat in [CAT_DAILY_VD, CAT_WEEKLY_VD, CAT_MONTHLY_VD]:
            scans = grouped.get(cat, [])
            signal = self._calculate_signal(scans)
            final_output[cat] = {
                "signal": signal,
                "scans": scans
            }
            
        return final_output

    def _calculate_signal(self, scans: List[Dict[str, Any]]) -> str:
        if not scans: return "Neutral"
        score = sum({"Strong Buy": 2, "Buy": 1, "Sell": -1, "Strong Sell": -2}.get(s.get("action", "Neutral"), 0) for s in scans)
        if score >= 2: return "Strong Buy"
        if score >= 1: return "Buy"
        if score <= -2: return "Strong Sell"
        if score <= -1: return "Sell"
        return "Neutral"

# ==============================================================================
# 5. ORCHESTRATOR (Main Engine)
# ==============================================================================
def process_stock(ticker: str, fetcher: VolumeDeliveryFetcher, master_map: List[Dict[str, Any]]) -> Optional[TickerVolumeDeliveryData]:
    logger.info(f"Processing Volume/Delivery for {ticker}...")
    
    d_df, w_df, m_df = fetcher.fetch_data(ticker)
    if d_df.empty: return None

    scanner = VolumeDeliveryScanner(d_df, w_df, m_df)
    category_results = scanner.run_all()
    
    trig_count = sum(len(c['scans']) for c in category_results.values())
    signal_counts = {"Strong Buy": 0, "Buy": 0, "Neutral": 0, "Sell": 0, "Strong Sell": 0}
    for cat_data in category_results.values():
        sig = cat_data.get('signal', 'Neutral')
        if sig in signal_counts: signal_counts[sig] += 1

    last_vol = float(d_df['Volume'].iloc[-1]) if 'Volume' in d_df.columns and not d_df['Volume'].empty else 0.0
    last_close = float(d_df['Close'].iloc[-1]) if 'Close' in d_df.columns and not d_df['Close'].empty else 0.0
    industry = get_industry_for_ticker(ticker, master_map)

    result = TickerVolumeDeliveryData(
        ticker=ticker,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        last_close=last_close,
        last_volume=last_vol,
        industry=industry,
        categories=category_results,
        scan_summary={"triggered_total": trig_count, "signals": signal_counts}
    )

    file_path = OUTPUT_DIR / f"{ticker}_volumedelivery.json"
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({
                "ticker": result.ticker,
                "timestamp": result.timestamp,
                "last_close": result.last_close,
                "last_volume": result.last_volume,
                "industry": result.industry,
                "categories": result.categories,
                "scan_summary": result.scan_summary
            }, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save results for {ticker}: {e}")

    return result

def main():
    parser = argparse.ArgumentParser(description="Volume & Delivery Scan Engine")
    parser.add_argument("--ticker", type=str, help="Ticker to scan")
    parser.add_argument("--limit", type=int, help="Limit total stocks processed")
    args = parser.parse_args()

    fetcher = VolumeDeliveryFetcher()
    master_map = load_master_industry_map()
    
    tickers = [args.ticker.upper()] if args.ticker else get_nifty_tickers()
    if args.limit: tickers = tickers[:args.limit]

    for t in tickers:
        process_stock(t, fetcher, master_map)

if __name__ == "__main__":
    main()