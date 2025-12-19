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

from .main import PriceScanEngine
from .scans import PriceScanner

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

    # 4. Analyze Triggered Scans
    # The result object stores categorized scans in `result.categories`
    # We iterate through categories to count signals
    categories = result.categories
    signal_counts = {"Strong Buy": 0, "Buy": 0, "Neutral": 0, "Sell": 0, "Strong Sell": 0}
    total_triggered = 0
    
    logger.info("-" * 40)
    logger.info(f"{'CATEGORY':<30} | {'SIGNAL':<12} | {'SCANS'}")
    logger.info("-" * 40)

    for cat_name, data in categories.items():
        signal = data.get('signal', 'Neutral')
        scans = data.get('scans', [])
        scan_count = len(scans)
        total_triggered += scan_count
        
        if signal in signal_counts:
            signal_counts[signal] += 1
            
        # Color code output
        sig_icon = "⚪"
        if "Buy" in signal: sig_icon = "🟢"
        elif "Sell" in signal: sig_icon = "🔴"
        
        # Only log categories that have triggered scans or a non-neutral signal
        if scan_count > 0 or signal != "Neutral":
            logger.info(f"{cat_name:<30} | {sig_icon} {signal:<10} | {scan_count}")

    logger.info("-" * 40)
    logger.info(f"Total Scans Triggered: {total_triggered}")
    logger.info(f"Signal Summary: {signal_counts}")

    # 5. Save Detailed Report
    output_file = PROJECT_ROOT / "scans" / "pricescan" / "results" / f"{ticker}_verified_117.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        # Convert dataclass to dict
        data_dict = {
            "ticker": result.ticker,
            "timestamp": result.timestamp,
            "last_close": result.last_close,
            "industry": result.industry,
            "scan_summary": result.scan_summary,
            "categories": result.categories  # This holds the structured data
        }
        json.dump(data_dict, f, indent=4)
        
    logger.info(f"📄 Detailed report saved to: {output_file}")
    print("\nRun the Streamlit app to view these results interactively:")
    print("streamlit run app.py")

if __name__ == "__main__":
    verify_reliance()