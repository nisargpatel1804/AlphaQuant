"""
Configuration module for Price Scans (117 Total).
Defines file paths, lookback periods, thresholds, and logic constants.
"""
from pathlib import Path

# --------------------------------------------------------------------------
# 1. File Path Configuration
# --------------------------------------------------------------------------
# Resolves to D:\Projects\ReScanX (or equivalent root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Source Directory for Fundamentals (Data Source)
FUNDAMENTALS_SOURCE_DIR = PROJECT_ROOT / "fundamentals" / "source"

# Strict paths as requested
NIFTY_500_CSV_PATH = FUNDAMENTALS_SOURCE_DIR / "ind_nifty500list.csv"
MASTER_INDUSTRY_MAP_PATH = FUNDAMENTALS_SOURCE_DIR / "master_industry_map.json"
CONSOLIDATED_LIST_PATH = FUNDAMENTALS_SOURCE_DIR / "consolidated.json"
NON_CONSOLIDATED_LIST_PATH = FUNDAMENTALS_SOURCE_DIR / "nonconsolidated.json"
TICKER_MAPPING_PATH = FUNDAMENTALS_SOURCE_DIR / "ticker_mapping.json"
# Note: run_industry_check.py is a script, usually not read as data, but path defined if needed
INDUSTRY_CHECK_SCRIPT_PATH = FUNDAMENTALS_SOURCE_DIR / "run_industry_check.py"

# Output Directory for Price Scan Results
PRICESCAN_RESULTS_DIR = PROJECT_ROOT / "pricescan" / "results"
PRICESCAN_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------
# 2. General Settings
# --------------------------------------------------------------------------
BENCHMARK_TICKER = "^NSEI"  # Nifty 50
BENCHMARK_SYMBOL_YF = "^NSEI"

# Tolerance for "Nearing" scans (e.g., Price Near 52 Week High)
# 1.5% tolerance window
NEARING_THRESHOLD_PCT = 1.5 

# --------------------------------------------------------------------------
# 3. Breakout Lookback Periods (Trading Days)
# --------------------------------------------------------------------------
# Used for Subtypes 4, 6, 7
LOOKBACK_52_WEEK = 252       # ~1 Year
LOOKBACK_2_YEAR = 504        # ~2 Years
LOOKBACK_5_YEAR = 1260       # ~5 Years

# --------------------------------------------------------------------------
# 4. Range Scan Thresholds (Subtype 5)
# --------------------------------------------------------------------------
# 52 Week Range Position Logic
# Range = (High_52W - Low_52W)
# Position = (Close - Low_52W) / Range

RANGE_BOTTOM_25_PCT = 0.25
RANGE_TOP_25_PCT = 0.75

# "Rise from 52 Week Low" classifications
RISE_MODERATE_PCT = 10.0
RISE_MODERATELY_HIGH_PCT = 20.0
RISE_HIGH_PCT = 30.0
RISE_VERY_HIGH_PCT = 50.0
RISE_2X_PCT = 100.0

# "Fall from 52 Week High" classifications
FALL_MODERATE_PCT = 10.0
FALL_MODERATELY_HIGH_PCT = 20.0
FALL_HIGH_PCT = 30.0
FALL_VERY_HIGH_PCT = 50.0

# --------------------------------------------------------------------------
# 5. Relative Strength Settings (Subtypes 13, 14, 15, 16)
# --------------------------------------------------------------------------
# RS Periods
RS_PERIOD_SHORT = 21         # 21 Days / 21 Weeks
RS_PERIOD_MEDIUM = 55        # 55 Days
RS_PERIOD_LONG = 100         # Proxy for longer term adaptive checks

# RS Zone Thresholds (e.g., RS > 0 is outperforming)
RS_ZERO_LINE = 0.0
RS_STRONG_ZONE = 0.5         # Arbitrary threshold for "High RS Zone" scans
RS_WEAK_ZONE = -0.5

# --------------------------------------------------------------------------
# 6. Absolute Return Periods (Subtype 17)
# --------------------------------------------------------------------------
# Maps labels to trading days
RETURN_PERIODS = {
    "1W": 5,
    "1M": 21,
    "3M": 63,
    "6M": 126,
    "1Y": 252
}

# --------------------------------------------------------------------------
# 7. Behavioural & VWAP (Subtypes 9, 10, 11, 18)
# --------------------------------------------------------------------------
# Gap Scans
GAP_THRESHOLD_PCT = 2.0      # Minimum % for "Large Gap Up/Down"

# VWAP Tolerance
VWAP_NEARING_THRESHOLD = 1.0 # % distance to be considered "Near VWAP"

# Consecutive Days
CONSECUTIVE_DAYS_2 = 2
CONSECUTIVE_DAYS_3 = 3

# --------------------------------------------------------------------------
# 8. Data Fetching
# --------------------------------------------------------------------------
# How much history to fetch to support 5Y breakouts + buffers
FETCH_HISTORY_DURATION = "5y" 
FETCH_INTERVAL = "1d"

# yfinance fetch tuning (helps on slow/unstable networks)
# Keep defaults conservative; SectorManager additionally batches downloads.
YF_BATCH_SIZE = 100
YF_MAX_RETRIES = 2
YF_RETRY_BACKOFF_SECONDS = 2.0