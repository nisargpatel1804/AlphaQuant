"""
Data Ingestion Module for Price Scans.
Responsible for fetching raw OHLCV data and aggregating it into 
Daily, Weekly, and Monthly timeframes for multi-period analysis.
"""
import yfinance as yf
import pandas as pd
import logging
from typing import Tuple, Optional, Dict
from datetime import datetime, timedelta
import time

from scans.pricescan.config import (
    BENCHMARK_TICKER, 
    FETCH_HISTORY_DURATION, 
    FETCH_INTERVAL,
    YF_BATCH_SIZE,
    YF_MAX_RETRIES,
    YF_RETRY_BACKOFF_SECONDS,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PriceScanFetcher:
    _benchmark_cache: Optional[pd.Series] = None

    def __init__(self):
        pass

    def fetch_stock_data(self, ticker: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Fetches raw daily data and generates aggregated timeframes.
        
        Args:
            ticker (str): Stock symbol (e.g., "RELIANCE").
            
        Returns:
            Tuple containing:
            - Daily DataFrame
            - Weekly DataFrame (Ends on Friday)
            - Monthly DataFrame (Ends on Month End)
        """
        # 1. Prepare Symbol
        symbol = self._normalize_ticker(ticker)
        
        # 2. Fetch Raw Data
        try:
            # fetch_history_duration is typically '5y' or '10y' to support long-term breakouts
            # Retry logic for resilience
            df = pd.DataFrame()
            for attempt in range(1, int(YF_MAX_RETRIES) + 2):
                try:
                    df = yf.download(
                        symbol, 
                        period=FETCH_HISTORY_DURATION, 
                        interval=FETCH_INTERVAL, 
                        auto_adjust=True, 
                        progress=False,
                        threads=False # False here because we usually call this inside a loop or specifically
                    )
                    if not df.empty:
                        break
                except Exception as e:
                    if attempt > int(YF_MAX_RETRIES):
                        logger.warning(f"Failed to fetch data for {symbol} after {attempt} attempts: {e}")
                    else:
                        time.sleep(min(float(YF_RETRY_BACKOFF_SECONDS) * attempt, 10.0))
            
            if df.empty:
                # Try .BO fallback if .NS fails and it was auto-appended
                if symbol.endswith(".NS"):
                    alt_symbol = symbol.replace(".NS", ".BO")
                    try:
                        df = yf.download(
                            alt_symbol, 
                            period=FETCH_HISTORY_DURATION, 
                            interval=FETCH_INTERVAL, 
                            auto_adjust=True, 
                            progress=False,
                            threads=False
                        )
                    except Exception:
                        pass

                if df.empty:
                    logger.warning(f"No data found for {symbol}")
                    return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

            # 3. Clean Columns
            df = self._clean_columns(df)
            
            # 4. Generate Aggregates
            weekly_df = self._resample_data(df, rule='W-FRI')
            monthly_df = self._resample_data(df, rule='ME') # 'ME' is Month End (pandas >= 2.2), use 'M' for older

            return df, weekly_df, monthly_df

        except Exception as e:
            logger.error(f"Error fetching data for {ticker}: {e}")
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    def fetch_benchmark(self) -> pd.Series:
        """
        Fetches and caches the Benchmark (Nifty 50) closing prices.
        Used for Relative Strength and Beta calculations.
        """
        if self.__class__._benchmark_cache is not None:
            return self.__class__._benchmark_cache

        logger.info(f"Fetching Benchmark Data ({BENCHMARK_TICKER})...")
        try:
            df = yf.download(
                BENCHMARK_TICKER, 
                period=FETCH_HISTORY_DURATION, 
                interval=FETCH_INTERVAL, 
                auto_adjust=True, 
                progress=False
            )
            
            if df.empty:
                logger.error("Benchmark data fetch returned empty.")
                return pd.Series(dtype=float)

            df = self._clean_columns(df)
            
            # Cache the Close series
            # Ensure it's a Series, handle potential MultiIndex if yfinance returns columns like (Close, ^NSEI)
            close_col = df['Close']
            if isinstance(close_col, pd.DataFrame):
                # If multiple columns (rare for single ticker download but possible), take first
                close_col = close_col.iloc[:, 0]
                
            self.__class__._benchmark_cache = close_col
            return self.__class__._benchmark_cache

        except Exception as e:
            logger.error(f"Failed to fetch benchmark: {e}")
            return pd.Series(dtype=float)

    def _normalize_ticker(self, ticker: str) -> str:
        """Ensures ticker has .NS suffix for NSE if not present."""
        t = ticker.strip().upper()
        if not t.endswith((".NS", ".BO", ".BSE")):
            return f"{t}.NS"
        return t

    def _clean_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardizes DataFrame columns to Open, High, Low, Close, Volume.
        Removes MultiIndex levels if present (common in newer yfinance).
        """
        if isinstance(df.columns, pd.MultiIndex):
            # If (Price, Ticker) structure, drop Ticker level
            try:
                # Attempt to get level 0 (Price Type)
                df.columns = df.columns.get_level_values(0)
            except IndexError:
                pass
        
        # Ensure we have the standard names
        # Sometimes 'Adj Close' is present instead of 'Close' if auto_adjust=False
        # But we use auto_adjust=True, so 'Close' is actually Adjusted Close.
        
        # Rename lower case to Title Case if needed
        # Create a mapping dictionary for safety
        col_map = {
            'adj close': 'Close',
            'Adj Close': 'Close',
            'close': 'Close',
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'volume': 'Volume'
        }
        
        # Apply mapping
        new_cols = []
        for c in df.columns:
            if isinstance(c, str):
                lower_c = c.lower()
                if lower_c in col_map:
                    new_cols.append(col_map[lower_c])
                else:
                    new_cols.append(c.capitalize()) # Default capitalization
            else:
                new_cols.append(c)
        df.columns = new_cols
        
        return df

    def _resample_data(self, df: pd.DataFrame, rule: str) -> pd.DataFrame:
        """
        Resamples Daily data into Weekly/Monthly candles.
        Aggregations:
        - Open: First
        - High: Max
        - Low: Min
        - Close: Last
        - Volume: Sum
        """
        if df.empty:
            return pd.DataFrame()

        agg_dict = {
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }
        
        # Handle cases where Volume might be missing
        if 'Volume' not in df.columns:
            agg_dict.pop('Volume')

        # Filter agg_dict to only include columns present in df
        agg_dict = {k: v for k, v in agg_dict.items() if k in df.columns}

        try:
            resampled = df.resample(rule).agg(agg_dict)
            # Drop incomplete periods (optional, but good for validity)
            # For 'W-FRI', the last week might be incomplete if run on Wed.
            # We keep it for "Current Week" scans.
            # Only drop rows where *all* OHLC are NaN (e.g. gaps)
            ohlc_cols = [c for c in ['Open', 'High', 'Low', 'Close'] if c in df.columns]
            return resampled.dropna(subset=ohlc_cols, how='all')
        except Exception as e:
            # Fallback for older pandas versions if 'ME' rule fails
            if rule == 'ME':
                try:
                    return df.resample('M').agg(agg_dict).dropna(subset=ohlc_cols, how='all')
                except:
                    pass
            logger.warning(f"Resampling failed for rule {rule}: {e}")
            return pd.DataFrame()