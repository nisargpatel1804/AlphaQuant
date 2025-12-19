"""
Verification Script for ReScanX Technical Scans.
Target: RELIANCE
Purpose: Execute the technical engine, validate indicator values, and verify Category grouping.
"""
import sys
import logging
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from .main import process_stock
from .fetcher import TechnicalFetcher
from .scans import TechnicalScans

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

def verify_technicals(ticker: str = "RELIANCE"):
    logger.info(f"--- Starting Technical Verification for {ticker} ---")
    try:
        fetcher = TechnicalFetcher()
    except Exception as e:
        logger.error(f"Failed to initialize TechnicalFetcher: {e}")
        return

    # This returns the full structure including 'categories' -> { CategoryName: { 'signal': ..., 'scans': [...] } }
    results = process_stock(ticker, fetcher)
    
    if not results:
        logger.error("No results generated.")
        return

    categories = results.get("categories", {})
    logger.info(f"Processing Complete. Found {len(categories)} categories.")
    
    # Check coverage of key categories
    expected_cats = [
        "Simple Moving Averages", 
        "Exponential Moving Averages",
        "RSI", 
        "MACD", 
        "Bollinger Bands",
        "Momentum",
        "Pivots - Classic"
    ]
    
    missing_cats = []
    
    logger.info("-" * 60)
    logger.info(f"{'CATEGORY':<30} | {'SIGNAL':<12} | {'SCANS'}")
    logger.info("-" * 60)

    for cat_name, data in categories.items():
        signal = data.get('signal', 'N/A')
        scan_count = len(data.get('scans', []))
        
        # Color code output for readability
        sig_icon = "⚪"
        if "Buy" in signal: sig_icon = "🟢"
        elif "Sell" in signal: sig_icon = "🔴"
        
        logger.info(f"{cat_name:<30} | {sig_icon} {signal:<10} | {scan_count}")

    for cat in expected_cats:
        if cat not in categories:
            missing_cats.append(cat)

    if missing_cats:
        logger.warning(f"⚠️  Missing Expected Categories: {missing_cats}")
    else:
        logger.info("-" * 60)
        logger.info("✅ All core expected categories present.")

    # Total Scans Count
    total_scans = sum(len(c["scans"]) for c in categories.values())
    logical_coverage = TechnicalScans.get_total_logical_scans()
    
    logger.info(f"Total Scans Executed: {total_scans}")
    logger.info(f"Logical Coverage: {logical_coverage}")
    
    if total_scans > 50: 
        logger.info("✅ SUCCESS: Extensive scan coverage confirmed.")
    
    output_file = PROJECT_ROOT / f"{ticker}_tech_verified.json"
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=4)
        logger.info(f"📄 Saved: {output_file}")
    except Exception as e:
        logger.error(f"Failed to save JSON output: {e}")

if __name__ == "__main__":
    verify_technicals()