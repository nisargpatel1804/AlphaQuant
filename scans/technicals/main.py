"""
Entry point for the Technical Analysis Pipeline.
Orchestrates Fetching -> Calculation -> Scanning -> Saving.
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Any

# Add project root to sys.path to allow imports from sibling modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scans.technicals.fetcher import TechnicalFetcher
from scans.technicals.indicators import TechnicalIndicators
from scans.technicals.scans import TechnicalScans
from scans.fundamentals.utils import get_nifty_tickers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "RESULTS" / "scans" / "technicals"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def load_master_industry_map() -> List[Dict[str, Any]]:
    """Loads the industry map to filter stocks by sector."""
    path = PROJECT_ROOT / "source" / "master_industry_map.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [row for row in data if isinstance(row, dict)]
    except Exception:
        return []

def get_stocks_for_industry(industry_name: str) -> List[str]:
    """Finds tickers for a given industry (fuzzy match)."""
    master_map = load_master_industry_map()
    target = industry_name.lower().strip()
    
    for entry in master_map:
        if target in entry.get("industry", "").lower():
            return entry.get("stocks", [])
    return []

def process_stock(ticker: str, fetcher: TechnicalFetcher) -> Dict[str, Any]:
    """
    Runs the full technical pipeline for a single stock.
    Returns the scan results dictionary.
    """
    logging.info(f"Processing {ticker}...")
    
    try:
        # 1. Fetch Data
        daily_df, weekly_df = fetcher.fetch_stock_data(ticker)
        
        if daily_df.empty or weekly_df.empty:
            logging.warning(f"Skipping {ticker}: Insufficient data.")
            return {}

        # 2. Fetch Benchmark (Cached)
        benchmark_series = fetcher.fetch_benchmark()

        # 2b. Compute Industry (Sector) Beta as avg beta of industry members vs benchmark
        industry_name = None
        industry_beta_avg = None
        if hasattr(fetcher, 'fetch_industry_beta_avg'):
             industry_name, industry_beta_avg = fetcher.fetch_industry_beta_avg(ticker, benchmark_series)
             # Attach to DF so scans can reference it
             daily_df["INDUSTRY_BETA_AVG"] = industry_beta_avg

        # 3. Calculate Indicators
        # Modifies DataFrames in-place
        TechnicalIndicators.add_all_indicators(daily_df, is_weekly=False, benchmark_data=benchmark_series)
        TechnicalIndicators.add_all_indicators(weekly_df, is_weekly=True)

        # 4. Run Scans (New Logic: Returns Categorized results)
        scanner = TechnicalScans(daily_df, weekly_df)
        # Returns Dict[Category, {'signal': str, 'scans': List}]
        category_results = scanner.run_all()
        
        # 5. Add Metadata
        final_output = {
            "ticker": ticker,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_close": daily_df["Close"].iloc[-1],
            "industry": industry_name,
            "categories": category_results
        }
        
        return final_output

    except Exception as e:
        logging.error(f"Failed to process {ticker}: {e}")
        return {}

def save_results(ticker: str, results: Dict[str, Any]):
    """Saves scan results to a JSON file."""
    filename = OUTPUT_DIR / f"{ticker}_tech.json"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=4)
        logging.info(f"Saved results to {filename}")
    except Exception as e:
        logging.error(f"Failed to save {ticker}: {e}")

def main():
    parser = argparse.ArgumentParser(description="AlphaQuant Technical Analysis Engine")
    parser.add_argument("ticker", nargs='?', type=str, help="Run for a single ticker (positional)")
    parser.add_argument("--ticker", type=str, help="Run for a single ticker")
    parser.add_argument("--limit", type=int, help="Limit the number of stocks to process")
    parser.add_argument("--industry", type=str, help="Run for a specific industry")
    parser.add_argument("--batch-size", type=int, default=10, help="Pause after N stocks")
    
    args = parser.parse_args()
    
    fetcher = TechnicalFetcher()
    tickers = []

    # Determine Universe
    if args.ticker:
        tickers = [args.ticker.upper()]
    elif args.industry:
        tickers = get_stocks_for_industry(args.industry)
        if not tickers:
            logging.error(f"No stocks found for industry '{args.industry}'")
            sys.exit(1)
        logging.info(f"Loaded {len(tickers)} stocks for industry '{args.industry}'")
    else:
        try:
            tickers = get_nifty_tickers()
            logging.info(f"Loaded {len(tickers)} Nifty 500 stocks.")
        except Exception as e:
            logging.critical(f"Failed to load Nifty tickers: {e}")
            sys.exit(1)

    # Apply Limit
    if args.limit:
        tickers = tickers[:args.limit]

    # Execution Loop
    processed_count = 0
    for ticker in tickers:
        results = process_stock(ticker, fetcher)
        
        if results:
            save_results(ticker, results)
            
            # Simplified log: Log signal for a few key categories to verify logic
            cats = results.get("categories", {})
            rsi_sig = cats.get("RSI", {}).get("signal", "N/A")
            sma_sig = cats.get("Simple Moving Averages", {}).get("signal", "N/A")
            logging.info(f"{ticker}: RSI={rsi_sig} | SMA={sma_sig}")

        processed_count += 1
        
        # Rate Limiting / Batching
        if processed_count % args.batch_size == 0 and processed_count < len(tickers):
            logging.info("Batch pause (2s)...")
            time.sleep(2)

    logging.info("Technical Analysis Complete.")

if __name__ == "__main__":
    main()