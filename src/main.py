"""Entry point for the stock fundamentals ingestion pipeline."""
from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from typing import Iterable, List, Optional

from db_manager import SupabaseManager
from screener_scraper import ScreenerScraper, get_nifty_tickers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def process_ticker(
    ticker: str,
    *,
    manager: SupabaseManager,
    scraper: ScreenerScraper,
    dry_run: bool = False,
    force: bool = False,
    max_retries: int = 3,
) -> None:
    """Fetch data for a single ticker and upsert it to the database with retry logic."""
    ticker = ticker.strip().upper()
    
    # 1. Check freshness if not forcing an update
    # We do this outside the retry loop to avoid unnecessary DB calls
    if not force:
        try:
            existing = manager.fetch_ticker(ticker)
            if existing and not SupabaseManager.needs_refresh(existing):
                logging.info("Processed %s: skipped (data is fresh)", ticker)
                return
        except Exception as e:
            logging.warning("Freshness check failed for %s: %s. Proceeding to scrape.", ticker, e)

    # 2. Scrape data with Retry Logic
    payload = None
    for attempt in range(max_retries):
        try:
            # Scraper now internally handles Standalone vs Consolidated via scr_bind.json
            payload = scraper.fetch_company_payload(ticker)
            payload["ticker"] = ticker
            break  # Success, exit loop
        except Exception as exc:
            error_msg = str(exc)
            is_last_attempt = attempt == max_retries - 1
            
            if "429" in error_msg:
                if is_last_attempt:
                    logging.error("Processed %s: failed (Rate Limited after %d attempts)", ticker, max_retries)
                    return
                
                # Exponential backoff for rate limits: 5s, 10s, 15s...
                wait_time = 5 * (attempt + 1)
                logging.warning("Rate limited for %s. Retrying in %ds...", ticker, wait_time)
                time.sleep(wait_time)
                continue
            
            elif "404" in error_msg:
                logging.error("Processed %s: failed (404 Not Found)", ticker)
                return # Don't retry 404s
            
            else:
                if is_last_attempt:
                    logging.error("Processed %s: failed. Reason: %s", ticker, error_msg)
                    return
                logging.warning("Error fetching %s: %s. Retrying...", ticker, error_msg)
                time.sleep(2) # Short sleep for generic errors

    if not payload:
        return

    # 3. Dry Run / Save
    try:
        if dry_run:
            industry = payload.get("metadata", {}).get("industry", "Unknown")
            logging.info("Processed %s: dry-run success (Industry: %s)", ticker, industry)
            return

        manager.upsert_record(payload)
        logging.info("Processed %s: success", ticker)

    except Exception as exc:
        logging.error("Database save failed for %s: %s", ticker, str(exc))


def chunked(iterable: Iterable[str], size: int) -> Iterable[List[str]]:
    """Yield successive chunks from an iterable."""
    chunk: List[str] = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest Screener fundamentals for the Nifty 500.")
    parser.add_argument("--max-tickers", type=int, default=None, help="Limit number of tickers (for debugging).")
    parser.add_argument("--start-after", type=str, default=None, help="Resume ingestion after a specific ticker.")
    parser.add_argument("--dry-run", action="store_true", help="Scrape data but do not write to Supabase.")
    parser.add_argument("--force", action="store_true", help="Ignore freshness checks and re-scrape everything.")
    parser.add_argument("--batch-size", type=int, default=10, help="Batch size for processing loop.")
    parser.add_argument("--delay-min", type=float, default=2.0, help="Minimum seconds to sleep between requests.")
    parser.add_argument("--delay-max", type=float, default=5.0, help="Maximum seconds to sleep between requests.")
    
    args = parser.parse_args(argv)

    logging.info("Initializing Data Pipeline...")
    
    try:
        manager = SupabaseManager()
        scraper = ScreenerScraper() # Loads scr_bind.json automatically
    except Exception as e:
        logging.critical("Failed to initialize backend services: %s", e)
        return 1

    # 1. Fetch Nifty 500 List
    try:
        tickers = get_nifty_tickers()
        logging.info("Loaded %d tickers from Nifty 500 source.", len(tickers))
    except Exception as e:
        logging.critical("Failed to fetch Nifty 500 list: %s", e)
        return 1

    # 2. Apply Filters (Start After / Max Tickers)
    if args.start_after:
        args.start_after = args.start_after.upper()
        if args.start_after in tickers:
            start_index = tickers.index(args.start_after) + 1
            tickers = tickers[start_index:]
            logging.info("Resuming after %s. Remaining tickers: %d", args.start_after, len(tickers))
        else:
            logging.warning("Ticker %s not found in list. Starting from beginning.", args.start_after)

    if args.max_tickers is not None:
        tickers = tickers[: args.max_tickers]
        logging.info("Limited run to %d tickers.", len(tickers))

    # 3. Randomize Execution
    # Important: Screener.in groups stocks by sector ID. 
    # Shuffling prevents hitting the same "sector server" sequentially, reducing 403/429 blocks.
    random.shuffle(tickers)

    # 4. Process Loop
    total_processed = 0
    for batch in chunked(tickers, args.batch_size):
        for ticker in batch:
            process_ticker(
                ticker, 
                manager=manager, 
                scraper=scraper, 
                dry_run=args.dry_run, 
                force=args.force
            )
            
            # Randomized sleep to mimic human behavior
            sleep_time = random.uniform(args.delay_min, args.delay_max)
            time.sleep(sleep_time)
            
        total_processed += len(batch)
        logging.info("--- Batch Complete. Total Processed: %d/%d ---", total_processed, len(tickers))

    logging.info("Ingestion Pipeline Complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())