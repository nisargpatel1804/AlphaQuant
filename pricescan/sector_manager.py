"""
Sector Manager Module.
Responsible for constructing 'Synthetic Sector Indices' to enable relative performance scans.
Logic:
1. Load Industry Map.
2. Batch fetch price data for all constituents of an industry.
3. Construct a synthetic price series (Index) representing the industry (e.g., Median Daily Returns).
"""
import json
import logging
import pandas as pd
import yfinance as yf
import numpy as np
import time
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from .config import (
    MASTER_INDUSTRY_MAP_PATH, 
    FETCH_HISTORY_DURATION, 
    FETCH_INTERVAL,
    YF_BATCH_SIZE,
    YF_MAX_RETRIES,
    YF_RETRY_BACKOFF_SECONDS,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SectorManager:
    _instance = None
    
    def __new__(cls):
        # Singleton pattern to prevent reloading heavy data multiple times
        if cls._instance is None:
            cls._instance = super(SectorManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        self.industry_map: List[Dict] = []
        self.ticker_to_industry: Dict[str, str] = {}
        # Stores the synthetic price series for each industry
        # Key: Industry Name, Value: pd.Series (Index values)
        self.sector_indices: Dict[str, pd.Series] = {} 
        
        self._load_map()
        self._initialized = True

    def _load_map(self):
        """Loads the master industry mapping JSON."""
        if not MASTER_INDUSTRY_MAP_PATH.exists():
            logger.error(f"Industry Map not found at {MASTER_INDUSTRY_MAP_PATH}")
            return

        try:
            text = MASTER_INDUSTRY_MAP_PATH.read_text(encoding="utf-8")
            self.industry_map = json.loads(text)
            
            # Build quick lookup
            for entry in self.industry_map:
                ind = entry.get("industry", "").strip()
                stocks = entry.get("stocks", [])
                if ind and stocks:
                    for s in stocks:
                        # Clean ticker and map to industry
                        self.ticker_to_industry[s.strip().upper()] = ind
                        
            logger.info(f"Loaded {len(self.industry_map)} industries and {len(self.ticker_to_industry)} ticker mappings.")
            
        except Exception as e:
            logger.error(f"Failed to load industry map: {e}")

    def get_industry_for_ticker(self, ticker: str) -> Optional[str]:
        """Returns the industry name for a given ticker symbol."""
        return self.ticker_to_industry.get(ticker.strip().upper())

    def get_sector_series(self, industry_name: str) -> Optional[pd.Series]:
        """Returns the pre-calculated synthetic series for an industry."""
        return self.sector_indices.get(industry_name)

    def build_all_sector_indices(self, force_refresh: bool = False):
        """
        Main heavy-lifting method.
        1. Collects ALL tickers from the map.
        2. Downloads them in a single batch (highly efficient).
        3. Constructs synthetic indices for every industry.
        """
        if self.sector_indices and not force_refresh:
            return

        all_tickers = list(self.ticker_to_industry.keys())
        if not all_tickers:
            return

        # Prepare symbols for yfinance (add .NS suffix if missing)
        yf_tickers = [f"{t}.NS" if not t.endswith((".NS", ".BO")) else t for t in all_tickers]
        
        # Add Nifty 50 Benchmark to the batch just in case we want to use it for relative comparison base
        if "^NSEI" not in yf_tickers:
            yf_tickers.append("^NSEI")

        logger.info(f"Fetching data for {len(yf_tickers)} stocks to build sector indices...")
        
        try:
            # Slow/unstable networks often cause partial timeouts when requesting 500+ tickers.
            # Mitigation: download in smaller batches and merge results.
            close_prices = self._download_close_prices_batched(yf_tickers)
            
            if close_prices.empty:
                logger.error("Failed to extract close prices from fetched data.")
                return

            # Clean column names (remove .NS suffix for mapping matching)
            # This ensures 'RELIANCE.NS' becomes 'RELIANCE' to match our JSON map
            close_prices.columns = [c.replace('.NS', '').replace('.BO', '') for c in close_prices.columns]
            
            # Now build indices industry by industry
            self._calculate_indices_from_prices(close_prices)
            
            logger.info(f"Successfully constructed {len(self.sector_indices)} synthetic sector indices.")
            
        except Exception as e:
            logger.error(f"Failed to build sector indices: {e}")

    def _download_close_prices_batched(self, yf_tickers: List[str]) -> pd.DataFrame:
        """Download close prices for many tickers in batches to reduce timeouts."""

        if not yf_tickers:
            return pd.DataFrame()

        batch_size = max(1, int(YF_BATCH_SIZE))
        combined: List[pd.DataFrame] = []

        for i in range(0, len(yf_tickers), batch_size):
            chunk = yf_tickers[i:i + batch_size]

            last_exc: Optional[Exception] = None
            for attempt in range(1, int(YF_MAX_RETRIES) + 2):
                try:
                    data = yf.download(
                        chunk,
                        period=FETCH_HISTORY_DURATION,
                        interval=FETCH_INTERVAL,
                        group_by='ticker',
                        auto_adjust=True,
                        threads=True,
                        progress=False,
                    )

                    if data is None or getattr(data, "empty", True):
                        raise ValueError("Empty yfinance response")

                    close_chunk = self._extract_close_prices(data)
                    if close_chunk is None or getattr(close_chunk, "empty", True):
                        raise ValueError("Failed to extract Close prices")

                    combined.append(close_chunk)
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt >= int(YF_MAX_RETRIES) + 1:
                        logger.warning(
                            f"Batch download failed for tickers[{i}:{i + len(chunk)}] ({len(chunk)} symbols): {exc}"
                        )
                        break
                    time.sleep(min(float(YF_RETRY_BACKOFF_SECONDS) * attempt, 10.0))

        if not combined:
            return pd.DataFrame()

        merged = pd.concat(combined, axis=1)
        # Remove duplicate columns if the same ticker appears multiple times across batches.
        merged = merged.loc[:, ~merged.columns.duplicated()]
        return merged

    def _extract_close_prices(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Robustly extracts 'Close' column from yfinance result.
        yfinance structure varies based on number of tickers and version.
        """
        # Case 1: MultiIndex columns with (Ticker, OHLCV) or (OHLCV, Ticker)
        if isinstance(data.columns, pd.MultiIndex):
            # Check level 0 or 1 for 'Close'
            # yfinance<0.2 often used (OHLCV, Ticker), newer uses (Ticker, OHLCV)
            # However, when group_by='ticker' is used, it is usually (Ticker, OHLCV)
            
            # Try to find which level has the price types
            levels = [data.columns.get_level_values(i).unique() for i in range(data.columns.nlevels)]
            close_level_idx = -1
            
            for i, level_values in enumerate(levels):
                if 'Close' in level_values:
                    close_level_idx = i
                    break
            
            if close_level_idx != -1:
                # If 'Close' is in level i, we want to cross-section on it
                try:
                    return data.xs('Close', level=close_level_idx, axis=1)
                except Exception:
                    pass

        # Case 2: Flattened columns or single level (rare with group_by='ticker' and multiple tickers)
        # But possible if only 1 ticker was requested
        if 'Close' in data.columns:
            return data[['Close']]

        # Fallback: Loop through columns and reconstruct
        extracted = {}
        is_multi = isinstance(data.columns, pd.MultiIndex)
        
        for col in data.columns:
            # Check if this column is a 'Close' column
            # Logic: if 'Close' string is in the column tuple or string
            if 'Close' in col:
                # Find the ticker part
                if is_multi:
                    # Filter out 'Close' from the tuple to find ticker
                    ticker_part = [x for x in col if x != 'Close'][0]
                else:
                    # e.g. "RELIANCE.NS Close" (unlikely with auto_adjust) or just "Close"
                    ticker_part = "Unknown" 
                
                extracted[ticker_part] = data[col]

        return pd.DataFrame(extracted)

    def _calculate_indices_from_prices(self, price_df: pd.DataFrame):
        """
        Given a master DF of stock prices, compute industry medians.
        Algorithm:
        1. For Ind X, get subset of cols.
        2. Calc % Change daily.
        3. Take Median of % Changes (Median is robust to outliers/upper circuits).
        4. Construct cumulative index (Base 100).
        """
        
        # Calculate daily returns for entire universe once
        # Filling NaN with 0 is risky for returns, better to leave NaN and handle in aggregation
        # pandas FutureWarning: default fill_method='pad' will change.
        # We explicitly avoid filling to keep returns numerically honest.
        all_returns = price_df.pct_change(fill_method=None)

        for entry in self.industry_map:
            ind_name = entry.get("industry")
            stocks = entry.get("stocks", [])
            
            if not ind_name:
                continue

            # Filter stocks that exist in our downloaded data
            valid_stocks = [s for s in stocks if s in all_returns.columns]
            
            if not valid_stocks:
                continue
                
            # Subset returns for this industry
            sector_returns_df = all_returns[valid_stocks]
            
            # 1. Calculate Representative Daily Return (Median)
            # axis=1 means across columns (stocks) for each day
            # We use median to avoid skew from one stock hitting 20% UC
            sector_daily_ret = sector_returns_df.median(axis=1)
            
            # 2. Construct Synthetic Price Series (Base 100)
            # Start from the first valid date where we have data
            first_valid_idx = sector_daily_ret.first_valid_index()
            if first_valid_idx is None:
                continue
                
            # Slice from first valid date
            sector_daily_ret = sector_daily_ret.loc[first_valid_idx:]
            
            # Fill remaining NaNs with 0 (assuming 0 change if no data for a specific day)
            sector_daily_ret_filled = sector_daily_ret.fillna(0)
            
            # Calculate cumulative product to simulate an index price
            # (1 + r1) * (1 + r2) * ...
            sector_index = (1 + sector_daily_ret_filled).cumprod() * 100
            
            self.sector_indices[ind_name] = sector_index