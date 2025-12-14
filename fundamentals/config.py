"""
Configuration constants for the Fundamentals module.
Centralizes URLs, User Agents, and File Paths.
"""
from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
# Assuming this file is at re-scan-x/fundamentals/config.py
FUNDAMENTALS_DIR = Path(__file__).resolve().parent
SOURCE_DIR = FUNDAMENTALS_DIR / "source"

# Data Files
MASTER_INDUSTRY_MAP_PATH = SOURCE_DIR / "master_industry_map.json"
TICKER_MAPPING_PATH = SOURCE_DIR / "ticker_mapping.json"
CONSOLIDATED_LIST_PATH = SOURCE_DIR / "consolidated.json"
NON_CONSOLIDATED_LIST_PATH = SOURCE_DIR / "nonconsolidated.json"
NIFTY_500_CSV_PATH = SOURCE_DIR / "ind_nifty500list.csv"

# --------------------------------------------------------------------------
# URLs
# --------------------------------------------------------------------------
NIFTY_500_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
SCREENER_BASE_URL = "https://www.screener.in/company/{ticker}/"
MARKET_INDUSTRIES_URL = "https://www.screener.in/market/?sort=total_market_cap&order=desc"

# --------------------------------------------------------------------------
# Scraping Settings
# --------------------------------------------------------------------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:118.0) Gecko/20100101 Firefox/118.0",
]

DEFAULT_TIMEOUT = 30