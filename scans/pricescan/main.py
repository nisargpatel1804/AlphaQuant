"""
Execution Engine for Price Scans.
Orchestrates the pipeline:
1. Initialize Sector Indices (if needed).
2. Fetch Stock Data (Daily, Weekly, Monthly).
3. Align with Benchmark & Sector Data.
4. Run all 117 Scans.
5. Save Results.
"""
import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Add project root to sys.path to allow imports if run as script
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scans.pricescan.config import (
    PRICESCAN_RESULTS_DIR, 
    NIFTY_500_CSV_PATH,
    BENCHMARK_TICKER
)
from scans.pricescan.fetcher import PriceScanFetcher
from scans.pricescan.scans import PriceScanner
from scans.pricescan.sector_manager import SectorManager
from scans.pricescan.models import TickerPriceScanData

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

class PriceScanEngine:
    def __init__(self, update_sectors: bool = False):
        self.fetcher = PriceScanFetcher()
        self.sector_manager = SectorManager()
        
        # Build/Load Sector Indices
        # If update_sectors is True, it re-downloads all data to rebuild indices
        logger.info("Initializing Sector Manager...")
        self.sector_manager.build_all_sector_indices(force_refresh=update_sectors)

    def process_ticker(self, ticker: str) -> Optional[TickerPriceScanData]:
        """
        Runs the full scan pipeline for a single ticker.
        """
        logger.info(f"Processing {ticker}...")
        
        # 1. Fetch Stock Data (Multi-timeframe)
        d_df, w_df, m_df = self.fetcher.fetch_stock_data(ticker)
        
        if d_df.empty:
            logger.warning(f"Skipping {ticker}: No data available.")
            return None

        # 2. Fetch Benchmark
        benchmark_series = self.fetcher.fetch_benchmark()

        # 3. Get Sector Data
        industry_name = self.sector_manager.get_industry_for_ticker(ticker)
        sector_series = None
        if industry_name:
            sector_series = self.sector_manager.get_sector_series(industry_name)
            if sector_series is None:
                logger.debug(f"No synthetic index found for industry: {industry_name}")
        else:
            logger.debug(f"Industry not mapped for {ticker}")

        # 4. Initialize Scanner
        scanner = PriceScanner(
            daily_df=d_df,
            weekly_df=w_df,
            monthly_df=m_df,
            benchmark_series=benchmark_series,
            sector_series=sector_series
        )

        # 5. Run Scans (Returns Dict[Category, {signal, scans}])
        category_results = scanner.run_all_scans()

        # 6. Calculate Summary Metrics
        coverage = PriceScanner.get_scan_coverage()
        
        # Count total scans triggered across all categories
        total_scans_triggered = sum(len(cat_data['scans']) for cat_data in category_results.values())
        
        # Count signal distribution
        signal_counts = {"Strong Buy": 0, "Buy": 0, "Neutral": 0, "Sell": 0, "Strong Sell": 0}
        for cat_data in category_results.values():
            sig = cat_data.get('signal', 'Neutral')
            if sig in signal_counts:
                signal_counts[sig] += 1

        # 7. Construct Output Data
        last_close = d_df['Close'].iloc[-1]
        
        output_data = TickerPriceScanData(
            ticker=ticker,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            last_close=last_close,
            industry=industry_name,
            categories=category_results,
            scan_summary={
                "expected_total": coverage.get("expected", 0),
                "implemented_total": coverage.get("implemented", 0),
                "triggered_total": total_scans_triggered,
                "signals": signal_counts
            },
        )

        return output_data

    def save_results(self, data: TickerPriceScanData):
        """Saves the result object to JSON."""
        file_path = PRICESCAN_RESULTS_DIR / f"{data.ticker}_price.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                # Convert dataclass to dict manually or via helper
                # TickerPriceScanData uses simple types except for 'categories' dict
                json_dict = {
                    "ticker": data.ticker,
                    "timestamp": data.timestamp,
                    "last_close": data.last_close,
                    "industry": data.industry,
                    "categories": data.categories,
                    "scan_summary": data.scan_summary,
                }
                json.dump(json_dict, f, indent=4)
            logger.info(f"Saved results to {file_path}")
        except Exception as e:
            logger.error(f"Failed to save results for {data.ticker}: {e}")

def get_nifty_tickers() -> List[str]:
    """Reads the Nifty 500 CSV source file."""
    if not NIFTY_500_CSV_PATH.exists():
        logger.error(f"Nifty 500 CSV not found at {NIFTY_500_CSV_PATH}")
        return []
    
    import csv
    tickers = []
    try:
        with open(NIFTY_500_CSV_PATH, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                sym = row.get('Symbol')
                if sym:
                    tickers.append(sym.strip().upper())
    except Exception as e:
        logger.error(f"Error reading Nifty CSV: {e}")
    return tickers

def main():
    parser = argparse.ArgumentParser(description="AlphaQuant Price Scan Engine")
    parser.add_argument("ticker", nargs='?', type=str, help="Run for a single ticker (positional)")
    parser.add_argument("--ticker", type=str, help="Run for a single ticker (e.g., RELIANCE)")
    parser.add_argument("--industry", type=str, help="Run for a specific industry (e.g., 'Cement')")
    parser.add_argument("--all", action="store_true", help="Run for all Nifty 500 stocks")
    parser.add_argument("--update-sectors", action="store_true", help="Force rebuild of sector indices")
    
    args = parser.parse_args()

    # 1. Initialize Engine
    engine = PriceScanEngine(update_sectors=args.update_sectors)

    # 2. Determine Target Tickers
    target_tickers = []
    
    ticker_input = args.ticker or getattr(args, 'ticker', None)
    if ticker_input:
        target_tickers = [ticker_input.strip().upper()]
    
    elif args.industry:
        # Find all stocks in that industry from the sector manager's map
        target_ind = args.industry.lower()
        for t, ind in engine.sector_manager.ticker_to_industry.items():
            if target_ind in ind.lower():
                target_tickers.append(t)
        
        if not target_tickers:
            logger.error(f"No tickers found for industry matching '{args.industry}'")
            return
            
    elif args.all:
        target_tickers = get_nifty_tickers()
    
    else:
        logger.warning("No target specified. Use --ticker, --industry, or --all.")
        parser.print_help()
        return

    logger.info(f"Starting Scan for {len(target_tickers)} stocks...")

    # 3. Execution Loop
    for i, ticker in enumerate(target_tickers):
        try:
            result = engine.process_ticker(ticker)
            if result:
                engine.save_results(result)
                
                # Console Summary (Updated to use summary structure)
                summary = result.scan_summary.get("signals", {})
                sb = summary.get("Strong Buy", 0)
                b = summary.get("Buy", 0)
                s = summary.get("Sell", 0)
                ss = summary.get("Strong Sell", 0)
                
                logger.info(f"[{i+1}/{len(target_tickers)}] {ticker}: StrongBuy={sb}, Buy={b}, Sell={s}, StrongSell={ss}")
            
        except KeyboardInterrupt:
            logger.info("Scan interrupted by user.")
            break
        except Exception as e:
            logger.error(f"Unexpected error processing {ticker}: {e}")

    logger.info("Price Scan Execution Complete.")

if __name__ == "__main__":
    main()