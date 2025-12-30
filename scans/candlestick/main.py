"""
Candlestick Execution Engine.
Orchestrates Fetching -> Scanning -> Saving.
"""
import logging
from datetime import datetime
from typing import Optional
import json
import sys
from pathlib import Path

# Add project root to sys.path to allow imports from sibling modules if run directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scans.candlestick.fetcher import CandleFetcher
from scans.candlestick.scans import CandleScanner
from scans.candlestick.models import TickerCandleData
from scans.candlestick.config import OUTPUT_DIR

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

class CandleEngine:
    def __init__(self):
        self.fetcher = CandleFetcher()

    def process_ticker(self, ticker: str) -> Optional[TickerCandleData]:
        """
        Runs the full Candlestick scan pipeline for a single ticker.
        """
        logger.info(f"Processing Candlestick Patterns for {ticker}...")
        
        # 1. Fetch Data
        df = self.fetcher.fetch_data(ticker)
        
        if df.empty:
            logger.warning(f"No data for {ticker}. Skipping.")
            return None
            
        # 2. Run Scans
        scanner = CandleScanner(df)
        # Returns Dict[Category, {'signal': str, 'scans': List[Dict]}]
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
        last_close = 0.0
        if 'Close' in df.columns and not df['Close'].empty:
            last_close = float(df['Close'].iloc[-1])

        # 5. Construct Result Object
        return TickerCandleData(
            ticker=ticker,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            last_close=last_close,
            industry=None, # Can be injected if integrated with global industry map
            categories=category_results,
            scan_summary={
                "triggered_total": trig_count,
                "signals": signal_counts
            }
        )

    def save_results(self, data: TickerCandleData):
        """Saves the result object to JSON."""
        file_path = OUTPUT_DIR / f"{data.ticker}_candle.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                # Convert dataclass to dict
                json_dict = {
                    "ticker": data.ticker,
                    "timestamp": data.timestamp,
                    "last_close": data.last_close,
                    "industry": data.industry,
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
    parser = argparse.ArgumentParser(description="Candlestick Scan Engine")
    parser.add_argument("ticker", nargs='?', type=str, help="Ticker to scan")
    parser.add_argument("--ticker", type=str, help="Ticker to scan")
    args = parser.parse_args()

    ticker = args.ticker or "RELIANCE"

    engine = CandleEngine()
    result = engine.process_ticker(ticker)
    
    if result:
        engine.save_results(result)
        summary = result.scan_summary
        logger.info(f"Scan Complete for {result.ticker}. Triggered Patterns: {summary.get('triggered_total')}")