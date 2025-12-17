"""
Verification Script for ReScanX Price Scans (117 Count).
Target: RELIANCE
Purpose: Execute the engine, save full JSON output, and verify scan counts.
"""
import sys
import logging
from pathlib import Path
import json

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pricescan.main import PriceScanEngine
from pricescan.scans import PriceScanner

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

def verify_reliance():
    logger.info("--- Starting Price Scan Verification for RELIANCE ---")
    
    # 1. Initialize Engine (Use existing sectors to speed up)
    try:
        engine = PriceScanEngine(update_sectors=False)
    except Exception as e:
        logger.error(f"Failed to initialize engine: {e}")
        return

    # 2. Process Ticker
    ticker = "RELIANCE"
    result = engine.process_ticker(ticker)
    
    if not result:
        logger.error("Scan returned no results. Check internet connection or yfinance.")
        return

    # 3. Analyze Coverage
    summary = result.scan_summary
    logger.info(f"Scan Coverage Expected:    {summary.get('expected_total', 0)}")
    logger.info(f"Scan Coverage Implemented: {summary.get('implemented_total', 0)}")
    
    if summary.get('implemented_total') != 117:
        logger.warning(f"⚠️ MISMATCH: Expected 117 scans, but code reports {summary.get('implemented_total')}.")
    else:
        logger.info("✅ SUCCESS: 117 Scans Logic Verified.")

    # 4. Analyze Triggers
    bull = len(result.scan_results.get("Bullish", []))
    bear = len(result.scan_results.get("Bearish", []))
    neutral = len(result.scan_results.get("Neutral", []))
    
    logger.info(f"Results for {ticker}:")
    logger.info(f"  🟢 Bullish: {bull}")
    logger.info(f"  🔴 Bearish: {bear}")
    logger.info(f"  🔵 Neutral: {neutral}")
    logger.info(f"  Total Triggered: {bull + bear + neutral}")

    # 5. Save Detailed Report
    output_file = PROJECT_ROOT / "pricescan" / "results" / f"{ticker}_verified_117.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        # Convert dataclass to dict
        data_dict = {
            "ticker": result.ticker,
            "timestamp": result.timestamp,
            "last_close": result.last_close,
            "industry": result.industry,
            "scan_summary": result.scan_summary,
            "scan_results": result.scan_results
        }
        json.dump(data_dict, f, indent=4)
        
    logger.info(f"📄 Detailed report saved to: {output_file}")
    print("\nRun the Streamlit app to view these results interactively:")
    print("streamlit run app.py")

if __name__ == "__main__":
    verify_reliance()