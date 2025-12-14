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
    scraper: ScreenerScraper,
    ticker_to_industry: Dict[str, str],
    industry_pe_map: Dict[str, float],
    force: bool = True
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

    # NOTE (Dec 2025): This pipeline intentionally runs in "no database" mode.
    # It always scrapes fresh data and computes scans locally.
    #
    # Future fallback (commented): re-enable DB caching + upsert.
    # from fundamentals.database import SupabaseManager
    # manager = SupabaseManager()
    # existing_record = manager.fetch_ticker(ticker)
    # if not force and existing_record and not manager.needs_refresh(existing_record, hours=24):
    #     payload = existing_record
    # else:
    #     payload = scraper.fetch_company_payload(ticker)
    #     payload["ticker"] = ticker
    #     manager.upsert_record(payload)

    payload: Optional[Dict[str, Any]] = None
    logging.info(f"Fetching fresh data for {ticker}...")
    try:
        # Add a small jitter to reduce bursty traffic when running batches.
        if not force:
            time.sleep(random.uniform(0.5, 1.5))

        payload = scraper.fetch_company_payload(ticker)
        payload["ticker"] = ticker

        apply_industry_context(
            payload,
            ticker=ticker,
            ticker_to_industry=ticker_to_industry,
            industry_to_pe=industry_pe_map
        )
    except Exception:
        logging.exception(f"Failed to fetch data for {ticker}")
        return None

    # 3. Run Fundamental Scans
    try:
        scanner = FundamentalScans(payload)
        scan_results = scanner.run_scans()
        metadata = scanner.metadata
    except Exception as e:
        logging.error(f"Error running scans for {ticker}: {e}")
        return None

    # 4. Compile Report (Updated Structure)
    report = {
        "ticker": ticker,
        "timestamp": datetime.now().isoformat(),
        "industry_context": {
            "industry": metadata.get("industry", "Unknown"),
            "current_price": metadata.get("current_price"),
            "pe": metadata.get("stock_pe"),
            "industry_pe": metadata.get("industry_pe"),
            "market_cap": metadata.get("market_cap")
        },
        "scan_summary": {
            "High": len(scan_results.get("High", [])),
            "Moderate": len(scan_results.get("Moderate", [])),
            "Low": len(scan_results.get("Low", [])),
            "Pending": len(scan_results.get("Pending", [])),
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
    # Always fresh now; flag kept for backward compatibility.
    parser.add_argument("--force", action="store_true", help="(Deprecated) No effect; data is always fetched fresh")
    parser.add_argument("--batch-size", type=int, default=10, help="Pause after N stocks")
    
    args = parser.parse_args()

    # Initialize Services (no database)
    try:
        scraper = ScreenerScraper(use_industry_pe_map=False)
    except Exception as e:
        logging.critical(f"Initialization failed: {e}")
        sys.exit(1)

    master_map = load_master_industry_map()
    ticker_to_ind, ind_to_pe = build_ticker_to_industry_and_pe(master_map)

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

    if args.limit:
        tickers = tickers[:args.limit]

    processed = 0
    failures = 0
    
    for ticker in tickers:
        result = process_ticker(
            ticker,
            scraper=scraper,
            ticker_to_industry=ticker_to_ind,
            industry_pe_map=ind_to_pe,
            force=True
        )
        
        if result:
            s = result["scan_summary"]
            logging.info(f"Result {ticker}: High={s['High']} Mod={s['Moderate']} Low={s['Low']} Pending={s['Pending']}")
        else:
            failures += 1

        processed += 1
        
        if processed % args.batch_size == 0 and processed < len(tickers):
            logging.info("Batch pause (2s)...")
            time.sleep(2)

    logging.info(f"Run Complete. Processed: {processed}, Failures: {failures}")

if __name__ == "__main__":
    main()