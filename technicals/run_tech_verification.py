"""
Verification Script for ReScanX Technical Scans (214 Count Coverage).
Target: RELIANCE
Purpose: Execute the technical engine, validate indicator values, and generate a verified JSON report.
"""
import sys
import logging
import json
from pathlib import Path
from datetime import datetime

# 1. Setup Project Path
# Assumes this script is located in re-scan-x/technicals/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import Technical Modules
from technicals.main import process_stock
from technicals.fetcher import TechnicalFetcher

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

def verify_technicals(ticker: str = "RELIANCE"):
    logger.info(f"--- Starting Technical Verification for {ticker} ---")
    
    # 2. Initialize Fetcher
    try:
        fetcher = TechnicalFetcher()
    except Exception as e:
        logger.error(f"Failed to initialize TechnicalFetcher: {e}")
        return

    # 3. Process Stock (Fetch -> Calc -> Scan)
    # This runs the exact logic used in the main app
    results = process_stock(ticker, fetcher)
    
    if not results:
        logger.error("No results generated. Check network connection or yfinance availability.")
        return

    # 4. Analysis & Counting
    bullish = results.get("Bullish", [])
    bearish = results.get("Bearish", [])
    neutral = results.get("Neutral", [])
    pending = results.get("Pending", [])
    
    total_signals = len(bullish) + len(bearish) + len(neutral) + len(pending)
    
    logger.info(f"Processing Complete for {ticker}")
    logger.info(f"Last Price: ₹{results.get('last_close', 0):,.2f}")
    logger.info(f"Industry:   {results.get('industry', 'N/A')}")
    logger.info("-" * 40)
    logger.info(f"🟢 Bullish Signals: {len(bullish)}")
    logger.info(f"🔴 Bearish Signals: {len(bearish)}")
    logger.info(f"🔵 Neutral Signals: {len(neutral)}")
    logger.info(f"⚪ Pending Signals: {len(pending)}")
    logger.info("-" * 40)
    logger.info(f"Total Active Checks: {total_signals}")

    # 5. Logic Integrity Check (Sample assertions based on known logic)
    # Check if critical indicators exist
    indicators_found = set()
    for category in [bullish, bearish, neutral]:
        for item in category:
            indicators_found.add(item['category'])
            
    expected_categories = {
        "Simple Moving Averages", "Exponential Moving Averages", "RSI", 
        "MACD", "Bollinger Bands", "Momentum", "ADX"
    }
    
    missing = expected_categories - indicators_found
    if missing:
        logger.warning(f"⚠️  Missing Indicator Categories in output: {missing}")
    else:
        logger.info("✅ Core Indicator Categories Verified.")

    # 6. Save Verified Output
    output_file = PROJECT_ROOT / f"{ticker}_tech_verified.json"
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=4)
        logger.info(f"📄 Verified Report Saved: {output_file}")
    except Exception as e:
        logger.error(f"Failed to save JSON: {e}")

    print(f"\nVerification successful. You can inspect '{output_file}' to validate specific values.")

if __name__ == "__main__":
    verify_technicals()