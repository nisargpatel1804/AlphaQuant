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

from .config import (
    BENCHMARK_TICKER, 
    FETCH_HISTORY_DURATION, 
    FETCH_INTERVAL
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
            df = yf.download(
                symbol, 
                period=FETCH_HISTORY_DURATION, 
                interval=FETCH_INTERVAL, 
                auto_adjust=True, 
                progress=False,
                threads=False # False here because we usually call this inside a loop or specifically
            )
            
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
            self.__class__._benchmark_cache = df['Close']
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
        required = ['Open', 'High', 'Low', 'Close']
        
        # Rename lower case to Title Case if needed
        df.columns = [c.capitalize() if isinstance(c, str) else c for c in df.columns]
        
        # Validation
        if not set(required).issubset(df.columns):
            # Fallback for 'Adj Close'
            if 'Adj close' in df.columns:
                df.rename(columns={'Adj close': 'Close'}, inplace=True)
            elif 'Adj Close' in df.columns:
                df.rename(columns={'Adj Close': 'Close'}, inplace=True)
                
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

        try:
            resampled = df.resample(rule).agg(agg_dict)
            # Drop incomplete periods (optional, but good for validity)
            # For 'W-FRI', the last week might be incomplete if run on Wed.
            # We keep it for "Current Week" scans.
            return resampled.dropna()
        except Exception as e:
            # Fallback for older pandas versions if 'ME' rule fails
            if rule == 'ME':
                try:
                    return df.resample('M').agg(agg_dict).dropna()
                except:
                    pass
            logger.warning(f"Resampling failed for rule {rule}: {e}")
            return pd.DataFrame()