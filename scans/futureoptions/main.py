"""
Futures & Options Execution Engine.
Orchestrates Fetching -> Scanning -> Saving.
"""
import logging
from datetime import datetime
from typing import Optional
import json

# Add project root to sys.path if needed for direct execution
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scans.futureoptions.fetcher import FOFetcher
from scans.futureoptions.scans import FOScanner
from scans.futureoptions.models import TickerFOData
from scans.futureoptions.config import OUTPUT_DIR

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

class FOEngine:
    def __init__(self):
        self.fetcher = FOFetcher()

    def process_ticker(self, ticker: str) -> Optional[TickerFOData]:
        """
        Runs the full F&O scan pipeline for a single ticker.
        """
        logger.info(f"Processing F&O for {ticker}...")
        
        # 1. Fetch Data
        df = self.fetcher.fetch_data(ticker)
        
        if df.empty:
            logger.warning(f"Skipping {ticker}: No data available.")
            return None
            
        # 2. Run Scans
        scanner = FOScanner(df)
        category_results = scanner.run_all_scans()
        
        # 3. Calculate Summary Stats
        trig_count = sum(len(c['scans']) for c in category_results.values())
        
        # Count signals
        signal_counts = {"Strong Buy": 0, "Buy": 0, "Neutral": 0, "Sell": 0, "Strong Sell": 0}
        for cat_data in category_results.values():
            sig = cat_data.get('signal', 'Neutral')
            if sig in signal_counts:
                signal_counts[sig] += 1
                
        # 4. Safe Data Access
        last_close = float(df['Close'].iloc[-1]) if not df['Close'].empty else 0.0
        
        # Open Interest and PCR might be NaN if not available
        last_oi = None
        if 'OpenInterest' in df.columns and not df['OpenInterest'].isna().iloc[-1]:
             last_oi = float(df['OpenInterest'].iloc[-1])
             
        last_pcr = None
        if 'PCR' in df.columns and not df['PCR'].isna().iloc[-1]:
             last_pcr = float(df['PCR'].iloc[-1])
        
        # 5. Construct Result Object
        return TickerFOData(
            ticker=ticker,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            last_close=last_close,
            last_oi=last_oi,
            last_pcr=last_pcr,
            categories=category_results,
            scan_summary={
                "triggered_total": trig_count,
                "signals": signal_counts
            }
        )

    def save_results(self, data: TickerFOData):
        """Saves the result object to JSON."""
        file_path = OUTPUT_DIR / f"{data.ticker}_fo.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                # Convert dataclass to dict
                # Note: TickerFOData contains simple types and a dict for 'categories', which is JSON serializable
                json_dict = {
                    "ticker": data.ticker,
                    "timestamp": data.timestamp,
                    "last_close": data.last_close,
                    "last_oi": data.last_oi,
                    "last_pcr": data.last_pcr,
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
    parser = argparse.ArgumentParser(description="Futures & Options Scan Engine")
    parser.add_argument("ticker", nargs='?', type=str, help="Ticker to scan")
    parser.add_argument("--ticker", type=str, help="Ticker to scan")
    args = parser.parse_args()

    ticker = args.ticker
    if not ticker:
        print("Error: ticker is required. Use --ticker <SYMBOL>.")
        raise SystemExit(1)

    engine = FOEngine()
    result = engine.process_ticker(ticker)
    if result:
        engine.save_results(result)
        print("Test complete.")