# backend/update_all.py

"""
AlphaQuant Multi-Threaded Batch Ingestion & Pre-Computation Engine
Fetches, computes, and persists all stock data across all scanners into local JSON and Supabase DB.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Core Database Persistence
from backend.db import upsert_scan_result
from backend.utils import normalize_ticker, to_serializable

# Scanners
from backend.scans.candlestick_scanner import (
    CandleFetcher,
    load_master_industry_map as load_candlestick_map,
    process_stock as run_candlestick,
)
from backend.scans.fo_scanner import (
    FOFetcher,
    load_master_industry_map as load_fo_map,
    process_stock as run_fo,
)
from backend.scans.fundamental_scraper import scrape_screener_complete
from backend.scans.pricescan_scanner import (
    PriceScanFetcher,
    SectorManager,
    get_nifty_tickers,
    process_stock as run_pricescan,
)
from backend.scans.strikeoptions_scanner import (
    StrikeOptionsFetcher,
    load_master_industry_map as load_strike_map,
    process_stock as run_strikeoptions,
)
from backend.scans.technical_scanner import (
    TechnicalFetcher,
    process_stock as run_technicals,
)
from backend.scans.volumedelivery_scanner import (
    VolumeDeliveryFetcher,
    load_master_industry_map as load_volume_map,
    process_stock as run_volumedelivery,
)

# Services
from backend.peers import get_peers_report
from backend.seasonality import get_seasonality_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("BatchIngestion")

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output" / "data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Shared fetchers & maps to prevent redundant disk I/O
tech_fetcher = TechnicalFetcher()
price_fetcher = PriceScanFetcher()
sector_mgr = SectorManager()
candle_fetcher = CandleFetcher()
candlestick_map = load_candlestick_map()
fo_fetcher = FOFetcher()
fo_map = load_fo_map()
strike_fetcher = StrikeOptionsFetcher()
strike_map = load_strike_map()
vol_fetcher = VolumeDeliveryFetcher()
vol_map = load_volume_map()

# Initialize sector indices once for relative strength scans
logger.info("Initializing Sector Indices...")
sector_mgr.build_all_sector_indices()


def _save_local_and_db(ticker: str, scan_type: str, data: Dict[str, Any]) -> None:
    """Helper to save serializable scan outputs to disk and Supabase DB."""
    if not data:
        data = {}
    clean_data = to_serializable(data)
    
    # Save Local JSON
    file_path = OUTPUT_DIR / f"{ticker}_{scan_type}.json"
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(clean_data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed writing local JSON for {ticker} [{scan_type}]: {e}")

    # Upsert into Supabase Cache
    try:
        upsert_scan_result(ticker, scan_type, clean_data)
    except Exception as e:
        logger.error(f"Supabase upsert failed for {ticker} [{scan_type}]: {e}")


def run_sync_scans(ticker: str) -> Dict[str, Any]:
    """Runs all CPU/IO synchronous stock scans in a thread pool worker."""
    results = {}
    
    # 1. Technicals
    try:
        results["technicals"] = run_technicals(ticker, tech_fetcher)
    except Exception as e:
        logger.error(f"Technicals error on {ticker}: {e}")
        results["technicals"] = {}

    # 2. Price Scans
    try:
        results["pricescan"] = run_pricescan(ticker, price_fetcher, sector_mgr)
    except Exception as e:
        logger.error(f"PriceScan error on {ticker}: {e}")
        results["pricescan"] = {}

    # 3. Candlesticks
    try:
        results["candlestick"] = run_candlestick(ticker, candle_fetcher, candlestick_map)
    except Exception as e:
        logger.error(f"Candlestick error on {ticker}: {e}")
        results["candlestick"] = {}

    # 4. Volume & Delivery
    try:
        results["volumedelivery"] = run_volumedelivery(ticker, vol_fetcher, vol_map)
    except Exception as e:
        logger.error(f"VolumeDelivery error on {ticker}: {e}")
        results["volumedelivery"] = {}

    # 5. F&O
    try:
        results["fo"] = run_fo(ticker, fo_fetcher, fo_map)
    except Exception as e:
        logger.error(f"F&O error on {ticker}: {e}")
        results["fo"] = {}

    # 6. Strike Options
    try:
        results["strikeoptions"] = run_strikeoptions(ticker, strike_fetcher, strike_map)
    except Exception as e:
        logger.error(f"StrikeOptions error on {ticker}: {e}")
        results["strikeoptions"] = {}

    # 7. Seasonality
    try:
        results["seasonality"] = get_seasonality_report(ticker)
    except Exception as e:
        logger.error(f"Seasonality error on {ticker}: {e}")
        results["seasonality"] = {}

    # 8. Peers
    try:
        results["peers"] = get_peers_report(ticker)
    except Exception as e:
        logger.error(f"Peers error on {ticker}: {e}")
        results["peers"] = {}

    return results


async def process_ticker_complete(ticker: str, executor: concurrent.futures.ThreadPoolExecutor) -> None:
    """Orchestrates complete async/sync fetch and storage for a single stock."""
    norm_ticker = normalize_ticker(ticker)
    logger.info(f">>> Starting Complete Batch Pipeline for [{norm_ticker}]...")
    start_t = time.time()

    # Async Task: Playwright Screener Scraper for Fundamentals
    async_tasks = [scrape_screener_complete(norm_ticker)]
    
    # Sync Tasks: Parallel ThreadPool execution for technicals, scans, and math indicators
    loop = asyncio.get_running_loop()
    sync_future = loop.run_in_executor(executor, run_sync_scans, norm_ticker)

    # Gather all results
    fundamentals_res, sync_res = await asyncio.gather(
        asyncio.gather(*async_tasks, return_exceptions=True),
        sync_future
    )

    fund_data = fundamentals_res[0] if isinstance(fundamentals_res[0], dict) else {}

    # Save Fundamentals
    _save_local_and_db(norm_ticker, "fundamentals", fund_data)

    # Save all Sync Scans
    for scan_type, data in sync_res.items():
        _save_local_and_db(norm_ticker, scan_type, data)

    elapsed = time.time() - start_t
    logger.info(f"<<< Completed Batch Pipeline for [{norm_ticker}] in {elapsed:.2f} seconds.")


async def main():
    parser = argparse.ArgumentParser(description="AlphaQuant Batch Ingestion Engine")
    parser.add_argument("--ticker", type=str, help="Process single ticker (e.g. RELIANCE)")
    parser.add_argument("--universe", action="store_true", help="Process full Nifty 500 universe")
    parser.add_argument("--limit", type=int, help="Limit maximum stocks processed")
    parser.add_argument("--workers", type=int, default=4, help="Max parallel worker threads")
    args = parser.parse_args()

    if args.ticker:
        tickers = [args.ticker.strip().upper()]
    elif args.universe:
        tickers = get_nifty_tickers()
    else:
        logger.info("No ticker specified. Defaulting to RELIANCE.")
        tickers = ["RELIANCE"]

    if args.limit:
        tickers = tickers[:args.limit]

    logger.info(f"Starting ingestion for {len(tickers)} stock(s) with {args.workers} workers...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        for ticker in tickers:
            await process_ticker_complete(ticker, executor)


if __name__ == "__main__":
    asyncio.run(main())