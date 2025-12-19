"""
Data Fetcher for Futures and Options.
Fetches Price, Volume, and attempts to fetch Open Interest (OI) data.
Note: Free data sources (like yfinance) often lack reliable Historical OI for NSE.
This module is designed to use placeholder/mock logic for OI if real data isn't found,
ensuring the system runs without crashing.
"""
import yfinance as yf
import pandas as pd
import logging
import numpy as np
from typing import Tuple, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FOFetcher:
    def __init__(self):
        pass

    def fetch_data(self, ticker: str) -> pd.DataFrame:
        """
        Fetches Daily data including Open Interest if available.
        Returns a DataFrame with columns: [Open, High, Low, Close, Volume, OpenInterest]
        """
        symbol = ticker.strip().upper()
        if not symbol.endswith((".NS", ".BO")):
            symbol = f"{symbol}.NS"

        try:
            # 1. Fetch Standard OHLCV
            df = yf.download(
                symbol, 
                period="6mo", 
                interval="1d", 
                progress=False, 
                auto_adjust=True, 
                threads=False
            )
            
            if df.empty:
                logger.warning(f"No data for {symbol}")
                return pd.DataFrame()

            # Clean Columns
            if isinstance(df.columns, pd.MultiIndex):
                # Flatten MultiIndex columns if present
                # Keep only the price type (Open, High, Low, Close, Volume)
                df.columns = df.columns.get_level_values(0)
            
            col_map = {
                'Adj Close': 'Close', 
                'adj close': 'Close', 
                'volume': 'Volume',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close'
            }
            # Rename based on map, ignore if not present
            df.rename(columns=col_map, inplace=True)
            
            # Ensure standard columns exist (capitalized)
            df.columns = [c.capitalize() if isinstance(c, str) else c for c in df.columns]
            
            # 2. Handle Open Interest (OI)
            # yfinance sometimes returns 'Open Interest' column for Futures symbols, but rarely for Equities.
            # We check if it exists. If not, we initialize it as NaN.
            # In a real F&O app, you would hit an API like NSEPython or a paid vendor here.
            if 'Open Interest' not in df.columns and 'openInterest' not in df.columns:
                 # Attempt to fetch specific futures ticker if known logic existed, otherwise NaN
                 df['OpenInterest'] = np.nan
            else:
                 # Standardize column name
                 if 'Open Interest' in df.columns: df.rename(columns={'Open Interest': 'OpenInterest'}, inplace=True)
                 if 'openInterest' in df.columns: df.rename(columns={'openInterest': 'OpenInterest'}, inplace=True)

            # 3. Handle Put Call Ratio (PCR)
            # This is definitely not in standard OHLCV. Placeholder.
            if 'PCR' not in df.columns:
                df['PCR'] = np.nan

            return df

        except Exception as e:
            logger.error(f"Fetch error for {ticker}: {e}")
            return pd.DataFrame()