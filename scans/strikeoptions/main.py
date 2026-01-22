"""
Strike Options Execution Engine.
Orchestrates Fetching -> Scanning -> Saving.
"""
import logging
from datetime import datetime
from typing import Optional
import json
import sys
from pathlib import Path

# Add project root to sys.path if run directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scans.strikeoptions.fetcher import StrikeOptionsFetcher
from scans.strikeoptions.scans import StrikeOptionsScanner
from scans.strikeoptions.models import TickerStrikeData
from scans.strikeoptions.config import OUTPUT_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

class StrikeOptionsEngine:
    def __init__(self):
        self.fetcher = StrikeOptionsFetcher()

    def process_ticker(self, ticker: str) -> Optional[TickerStrikeData]:
        """
        Runs the full Strike Options scan pipeline for a single ticker.
        """
        logger.info(f"Processing Strike Options for {ticker}...")
        
        # 1. Fetch Option Chain (Nearest Expiry)
        calls, puts, price, expiry = self.fetcher.fetch_option_chain(ticker)
        
        if calls.empty and puts.empty:
            logger.warning(f"No option chain data found for {ticker}")
            return None
            
        # 2. Run Scans
        scanner = StrikeOptionsScanner(calls, puts)
        category_results = scanner.run_all_scans()
        
        # 3. Calculate Summary Stats
        trig_count = sum(len(c['scans']) for c in category_results.values())
        
        # Count signals (mostly Neutral for strike levels, but good to have logic ready)
        signal_counts = {"Strong Buy": 0, "Buy": 0, "Neutral": 0, "Sell": 0, "Strong Sell": 0}
        for cat_data in category_results.values():
            sig = cat_data.get('signal', 'Neutral')
            if sig in signal_counts:
                signal_counts[sig] += 1
        
        # 4. Construct Result Object
        return TickerStrikeData(
            ticker=ticker,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            last_close=price,
            expiry_date=expiry,
            categories=category_results,
            scan_summary={
                "triggered_total": trig_count,
                "signals": signal_counts
            }
        )

    def save_results(self, data: TickerStrikeData):
        """Saves the result object to JSON."""
        file_path = OUTPUT_DIR / f"{data.ticker}_strike.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                # Convert dataclass to dict
                json_dict = {
                    "ticker": data.ticker,
                    "timestamp": data.timestamp,
                    "last_close": data.last_close,
                    "expiry_date": data.expiry_date,
                    "categories": data.categories,
                    "scan_summary": data.scan_summary
                }
                json.dump(json_dict, f, indent=4)
            logger.info(f"Saved results to {file_path}")
        except Exception as e:
            logger.error(f"Failed to save results for {data.ticker}: {e}")

if __name__ == "__main__":
    # Simple test execution
    import argparse
    parser = argparse.ArgumentParser(description="Strike Options Scan Engine")
    parser.add_argument("ticker", nargs='?', type=str, help="Ticker to scan")
    parser.add_argument("--ticker", type=str, help="Ticker to scan")
    args = parser.parse_args()

    ticker = args.ticker
    if not ticker:
        print("Error: ticker is required. Use --ticker <SYMBOL>.")
        raise SystemExit(1)

    engine = StrikeOptionsEngine()
    result = engine.process_ticker(ticker)
    if result:
        engine.save_results(result)
        print(f"Test complete. Expiry: {result.expiry_date}")