"""
Data Fetcher for Candlestick Analysis.
Fetches daily OHLCV data required for pattern recognition.
"""
import yfinance as yf
import pandas as pd
import logging
from typing import Tuple, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CandleFetcher:
    def __init__(self):
        pass

    def fetch_data(self, ticker: str) -> pd.DataFrame:
        """
        Fetches Daily data.
        Returns: daily_df
        """
        symbol = ticker.strip().upper()
        if not symbol.endswith((".NS", ".BO")):
            symbol = f"{symbol}.NS"

        try:
            # Need enough history for multi-day patterns and average body calculation
            df = yf.download(
                symbol, 
                period="3mo", 
                interval="1d", 
                progress=False, 
                auto_adjust=True, 
                threads=False
            )
            
            if df.empty:
                return pd.DataFrame()

            if isinstance(df.columns, pd.MultiIndex):
                # Flatten MultiIndex (Price Type, Ticker) -> Price Type
                df.columns = df.columns.get_level_values(0)
            
            col_map = {
                'Adj Close': 'Close', 'adj close': 'Close', 
                'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close',
                'volume': 'Volume'
            }
            # Rename columns if they exist in map
            df.rename(columns=col_map, inplace=True)
            
            # Ensure proper capitalization for all columns (Open, High, Low, Close)
            df.columns = [c.capitalize() if isinstance(c, str) else c for c in df.columns]

            return df

        except Exception as e:
            logger.error(f"Fetch error for {ticker}: {e}")
            return pd.DataFrame()