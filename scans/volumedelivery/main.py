"""
Volume and Delivery Execution Engine.
Orchestrates Fetching -> Scanning -> Saving.
"""
import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

# Add project root to sys.path to allow imports if run as script
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from .config import OUTPUT_DIR
from .fetcher import VolumeDeliveryFetcher
from .scans import VolumeDeliveryScanner
from .models import TickerVolumeDeliveryData
from ..fundamentals.utils import get_nifty_tickers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

class VolumeDeliveryEngine:
    def __init__(self):
        self.fetcher = VolumeDeliveryFetcher()

    def process_ticker(self, ticker: str) -> Optional[TickerVolumeDeliveryData]:
        """
        Runs the full Volume/Delivery scan pipeline for a single ticker.
        """
        logger.info(f"Processing Volume/Delivery for {ticker}...")
        
        # 1. Fetch Data
        d_df, w_df, m_df = self.fetcher.fetch_data(ticker)
        
        if d_df.empty:
            logger.warning(f"Skipping {ticker}: No data available.")
            return None

        # 2. Run Scans
        scanner = VolumeDeliveryScanner(d_df, w_df, m_df)
        category_results = scanner.run_all()
        
        # 3. Calculate Summary Stats
        trig_count = sum(len(c['scans']) for c in category_results.values())
        
        # Count signals
        signal_counts = {"Strong Buy": 0, "Buy": 0, "Neutral": 0, "Sell": 0, "Strong Sell": 0}
        for cat_data in category_results.values():
            sig = cat_data.get('signal', 'Neutral')
            if sig in signal_counts:
                signal_counts[sig] += 1

        # 4. Safe Data Access
        last_vol = 0.0
        if 'Volume' in d_df.columns and not d_df['Volume'].empty:
            last_vol = float(d_df['Volume'].iloc[-1])

        last_close = 0.0
        if 'Close' in d_df.columns and not d_df['Close'].empty:
            last_close = float(d_df['Close'].iloc[-1])
        
        # 5. Construct Result Object
        # Note: Industry can be injected if integrated with a global industry map
        industry = None 
        
        return TickerVolumeDeliveryData(
            ticker=ticker,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            last_close=last_close,
            last_volume=last_vol,
            industry=industry,
            categories=category_results,
            scan_summary={
                "triggered_total": trig_count,
                "signals": signal_counts
            }
        )

    def save_results(self, data: TickerVolumeDeliveryData):
        """Saves the result object to JSON."""
        file_path = OUTPUT_DIR / f"{data.ticker}_vd.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                # Convert dataclass to dict
                json_dict = {
                    "ticker": data.ticker,
                    "timestamp": data.timestamp,
                    "last_close": data.last_close,
                    "last_volume": data.last_volume,
                    "industry": data.industry,
                    "categories": data.categories,
                    "scan_summary": data.scan_summary,
                }
                json.dump(json_dict, f, indent=4)
            logger.info(f"Saved results to {file_path}")
        except Exception as e:
            logger.error(f"Failed to save results for {data.ticker}: {e}")

def main():
    parser = argparse.ArgumentParser(description="ReScanX Volume & Delivery Engine")
    parser.add_argument("--ticker", type=str, help="Run for a single ticker (e.g., RELIANCE)")
    parser.add_argument("--all", action="store_true", help="Run for all Nifty 500 stocks")
    parser.add_argument("--limit", type=int, help="Limit number of stocks")
    parser.add_argument("--batch-size", type=int, default=10, help="Pause after N stocks")
    
    args = parser.parse_args()

    engine = VolumeDeliveryEngine()
    target_tickers = []

    if args.ticker:
        target_tickers = [args.ticker.strip().upper()]
    elif args.all:
        try:
            target_tickers = get_nifty_tickers()
            logger.info(f"Loaded {len(target_tickers)} Nifty 500 stocks.")
        except Exception as e:
            logger.critical(f"Failed to load Nifty list: {e}")
            sys.exit(1)
    else:
        logger.warning("No target specified. Use --ticker or --all.")
        parser.print_help()
        return

    if args.limit:
        target_tickers = target_tickers[:args.limit]

    logger.info(f"Starting Scan for {len(target_tickers)} stocks...")

    processed_count = 0
    for i, ticker in enumerate(target_tickers):
        try:
            result = engine.process_ticker(ticker)
            if result:
                engine.save_results(result)
                
                # Console Summary
                summary = result.scan_summary.get("signals", {})
                sb = summary.get("Strong Buy", 0)
                b = summary.get("Buy", 0)
                vol_str = f"{int(result.last_volume):,}"
                logger.info(f"[{i+1}/{len(target_tickers)}] {ticker}: Vol={vol_str} | SB={sb}, Buy={b}")
            
        except KeyboardInterrupt:
            logger.info("Scan interrupted by user.")
            break
        except Exception as e:
            logger.error(f"Unexpected error processing {ticker}: {e}")
            
        processed_count += 1
        if processed_count % args.batch_size == 0 and processed_count < len(target_tickers):
             time.sleep(1.0) # Rate limiting

    logger.info("Volume & Delivery Execution Complete.")

if __name__ == "__main__":
    main()