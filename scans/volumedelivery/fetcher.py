"""
Data Fetcher for Volume and Delivery.
Fetches OHLCV data. 
Note: Real-time 'Delivery %' is not available via standard free yfinance.
This fetcher structures the data so Delivery columns can be populated if an external source is added.
"""
import yfinance as yf
import pandas as pd
import logging
from typing import Tuple, Optional
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VolumeDeliveryFetcher:
    def __init__(self):
        pass

    def fetch_data(self, ticker: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Fetches Daily, Weekly, and Monthly data.
        Returns: (daily_df, weekly_df, monthly_df)
        """
        # 1. Normalize Ticker
        symbol = ticker.strip().upper()
        if not symbol.endswith((".NS", ".BO")):
            symbol = f"{symbol}.NS"

        try:
            # 2. Fetch Daily Data (1 Year for averages)
            df = yf.download(
                symbol, 
                period="1y", 
                interval="1d", 
                progress=False, 
                auto_adjust=True, 
                threads=False
            )
            
            if df.empty:
                logger.warning(f"No data for {symbol}")
                return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

            # 3. Clean Columns
            if isinstance(df.columns, pd.MultiIndex):
                # Flatten MultiIndex columns if present
                # Keep only the price type (Open, High, Low, Close, Volume)
                df.columns = df.columns.get_level_values(0)
            
            # Map columns to standard names
            col_map = {
                'Adj Close': 'Close',
                'adj close': 'Close',
                'volume': 'Volume',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close'
            }
            # Rename columns based on map, ignore if not present
            df.rename(columns=col_map, inplace=True)
            
            # Ensure standard columns exist (capitalized)
            df.columns = [c.capitalize() if isinstance(c, str) else c for c in df.columns]

            # 4. Add Placeholder Delivery Columns (If not present)
            # In a production environment, this is where you'd merge NSE Delivery reports
            if 'Delivery_qty' not in df.columns:
                df['Delivery_qty'] = None 
            if 'Delivery_pct' not in df.columns:
                df['Delivery_pct'] = None

            # 5. Resample
            weekly_df = self._resample(df, 'W-FRI')
            monthly_df = self._resample(df, 'ME')

            return df, weekly_df, monthly_df

        except Exception as e:
            logger.error(f"Fetch error for {ticker}: {e}")
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    def _resample(self, df: pd.DataFrame, rule: str) -> pd.DataFrame:
        if df.empty: return pd.DataFrame()
        
        agg_dict = {
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum',
        }
        # If we had delivery data, we'd sum quantity and re-calc pct
        if 'Delivery_qty' in df.columns and df['Delivery_qty'].notna().any():
             agg_dict['Delivery_qty'] = 'sum'
             # Pct cannot be summed, needs recalc after resampling: (DelQty / Vol) * 100
        
        # Filter agg_dict for existing columns
        agg_dict = {k: v for k, v in agg_dict.items() if k in df.columns}
        
        try:
            res = df.resample(rule).agg(agg_dict).dropna(subset=['Close'])
            # Recalc Delivery Pct if possible
            if 'Delivery_qty' in res.columns and 'Volume' in res.columns:
                # Avoid division by zero
                res['Delivery_pct'] = (res['Delivery_qty'] / res['Volume'].replace(0, 1)) * 100
            else:
                 res['Delivery_pct'] = None
            return res
        except Exception:
            return pd.DataFrame()