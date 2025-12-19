"""
Data Fetcher for Strike Wise Options.
Fetches Option Chain for the nearest expiration using yfinance.
"""
import yfinance as yf
import pandas as pd
import logging
from typing import Tuple, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StrikeOptionsFetcher:
    def __init__(self):
        pass

    def fetch_option_chain(self, ticker: str) -> Tuple[pd.DataFrame, pd.DataFrame, float, str]:
        """
        Fetches the option chain for the nearest expiration.
        Returns: (calls_df, puts_df, underlying_price, expiry_date_str)
        """
        # 1. Normalize Ticker (yfinance needs plain ticker for some, .NS for others, usually just ticker works for options if recognized)
        # However, yfinance option_chain usually works on the base Ticker object.
        symbol = ticker.strip().upper()
        if not symbol.endswith((".NS", ".BO")):
            symbol = f"{symbol}.NS" # NSE derivatives usually follow this

        try:
            yf_ticker = yf.Ticker(symbol)
            
            # 2. Get Expirations
            expirations = yf_ticker.options
            if not expirations:
                logger.warning(f"No options data found for {symbol}")
                return pd.DataFrame(), pd.DataFrame(), 0.0, ""

            # 3. Fetch Nearest Chain
            nearest_expiry = expirations[0]
            chain = yf_ticker.option_chain(nearest_expiry)
            
            calls = chain.calls
            puts = chain.puts
            
            # 4. Get Underlying Price (approximate from history if not in chain metadata)
            # Sometimes chain metadata has it, but safe to fetch history
            hist = yf_ticker.history(period="1d")
            price = hist['Close'].iloc[-1] if not hist.empty else 0.0

            return calls, puts, price, nearest_expiry

        except Exception as e:
            logger.error(f"Error fetching options for {ticker}: {e}")
            return pd.DataFrame(), pd.DataFrame(), 0.0, ""