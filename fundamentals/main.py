"""
Entry point for the Fundamentals Analysis Pipeline.
Orchestrates Fetching -> DB Storage -> Calculation -> Scanning -> Reporting.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to sys.path to allow imports from sibling modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import from local package
from fundamentals.database import SupabaseManager
from fundamentals.fetcher import ScreenerScraper
from fundamentals.scans import FundamentalScans
from fundamentals.utils import (
    get_nifty_tickers,
    load_master_industry_map,
    build_ticker_to_industry_and_pe,
    apply_industry_context,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)

# Output directory for local JSON dumps (debugging/verify)
RESULTS_DIR = PROJECT_ROOT / "fundamentals" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def process_ticker(
    ticker: str,
    *,
    manager: SupabaseManager,
    scraper: ScreenerScraper,
    ticker_to_industry: Dict[str, str],
    industry_pe_map: Dict[str, float],
    dry_run: bool = False,
    force: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Full pipeline for a single ticker:
    1. Check DB cache (unless forced)
    2. Scrape if needed
    3. Run Scans
    4. Save to DB & Local JSON
    """
    ticker = ticker.strip().upper()
    logging.info(f"--- Processing {ticker} ---")

    # 1. Check Database (Cache)
    existing_record = None
    if not force:
        existing_record = manager.fetch_ticker(ticker)
        
    needs_scrape = force or not existing_record or manager.needs_refresh(existing_record, hours=24)

    payload = existing_record
    
    # 2. Scrape Data (if needed)
    if needs_scrape:
        logging.info(f"Fetching fresh data for {ticker}...")
        try:
            # Random delay to be polite to Screener if scraping multiple
            if not force: 
                time.sleep(random.uniform(1.0, 3.0))
                
            payload = scraper.fetch_company_payload(ticker)
            payload["ticker"] = ticker
            
            # Enrich with Industry Data
            apply_industry_context(
                payload,
                ticker=ticker,
                ticker_to_industry=ticker_to_industry,
                industry_to_pe=industry_pe_map
            )
            
            # Save to DB
            if not dry_run:
                manager.upsert_record(payload)
                logging.info(f"Upserted {ticker} to Supabase.")
                
        except Exception as e:
            logging.error(f"Failed to fetch/save {ticker}: {e}")
            if not payload: # If we have no old data either, give up
                return None
    else:
        logging.info(f"Using cached data for {ticker}")

    # 3. Run Fundamental Scans
    try:
        scanner = FundamentalScans(payload)
        scan_results = scanner.run_scans()
        metadata = scanner.metadata
    except Exception as e:
        logging.error(f"Error running scans for {ticker}: {e}")
        return None

    # 4. Compile Report
    report = {
        "ticker": ticker,
        "timestamp": datetime.now().isoformat(),
        "archetype": getattr(scanner, "archetype", "Generic"),
        "industry_context": {
            "industry": metadata.get("industry", "Unknown"),
            "current_price": metadata.get("current_price"),
            "pe": metadata.get("stock_pe"),
            "industry_pe": metadata.get("industry_pe"),
            "market_cap": metadata.get("market_cap")
        },
        "scan_summary": {
            "pass": len(scan_results.get("pass", [])),
            "fail": len(scan_results.get("fail", [])),
            "pending": len(scan_results.get("pending", [])),
        },
        "results": scan_results
    }

    # 5. Local Save (Scan Results)
    try:
        out_file = RESULTS_DIR / f"{ticker}_fund.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=4)
    except Exception as e:
        logging.error(f"Failed to save local report: {e}")

    return report


def main():
    parser = argparse.ArgumentParser(description="ReScanX Fundamentals Engine")
    parser.add_argument("--ticker", type=str, help="Process a single ticker")
    parser.add_argument("--limit", type=int, help="Limit total stocks processed")
    parser.add_argument("--industry", type=str, help="Process all stocks in a specific industry")
    parser.add_argument("--force", action="store_true", help="Force refresh from Screener (ignore cache)")
    parser.add_argument("--dry-run", action="store_true", help="Run without saving to DB")
    parser.add_argument("--batch-size", type=int, default=10, help="Pause after N stocks")
    
    args = parser.parse_args()

    # Initialize Services
    try:
        manager = SupabaseManager()
        scraper = ScreenerScraper(use_industry_pe_map=False) # PE map handled via utils now
    except Exception as e:
        logging.critical(f"Initialization failed: {e}")
        sys.exit(1)

    # Load Industry Context
    master_map = load_master_industry_map()
    ticker_to_ind, ind_to_pe = build_ticker_to_industry_and_pe(master_map)

    # Determine Universe
    tickers = []
    if args.ticker:
        tickers = [args.ticker.strip().upper()]
    elif args.industry:
        target_industry = args.industry.lower()
        for entry in master_map:
            if target_industry in entry.get("industry", "").lower():
                tickers.extend(entry.get("stocks", []))
        if not tickers:
            logging.error(f"No tickers found for industry '{args.industry}'")
            sys.exit(1)
        logging.info(f"Loaded {len(tickers)} stocks for industry '{args.industry}'")
    else:
        try:
            tickers = get_nifty_tickers()
            logging.info(f"Loaded {len(tickers)} Nifty 500 stocks.")
        except Exception as e:
            logging.critical(f"Failed to load Nifty list: {e}")
            sys.exit(1)

    # Apply Limit
    if args.limit:
        tickers = tickers[:args.limit]

    # Execution Loop
    processed = 0
    failures = 0
    
    for ticker in tickers:
        result = process_ticker(
            ticker,
            manager=manager,
            scraper=scraper,
            ticker_to_industry=ticker_to_ind,
            industry_pe_map=ind_to_pe,
            dry_run=args.dry_run,
            force=args.force
        )
        
        if result:
            summary = result["scan_summary"]
            logging.info(f"Result {ticker}: PASS={summary['pass']} FAIL={summary['fail']} PENDING={summary['pending']}")
        else:
            failures += 1

        processed += 1
        
        # Batch Pausing
        if processed % args.batch_size == 0 and processed < len(tickers):
            logging.info("Batch pause (2s)...")
            time.sleep(2)

    logging.info(f"Run Complete. Processed: {processed}, Failures: {failures}")

if __name__ == "__main__":
    main()