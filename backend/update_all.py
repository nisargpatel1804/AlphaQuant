# backend/update_all.py
"""
Pre‑compute all scanner results and store them in Supabase.
Run this once initially, then schedule daily.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.db import upsert_scan_result
from backend.utils import to_serializable

# Import all scanner functions
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
from backend.scans.pricescan_scanner import get_nifty_tickers

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


async def update_ticker(ticker: str):
    """Compute and store all scans for a single ticker."""
    logger.info(f"Updating {ticker}...")

    # 1. Fundamentals (async)
    try:
        data = await scrape_screener_complete(ticker)
        serialized = to_serializable(data)
        upsert_scan_result(ticker, "fundamentals", serialized)
    except Exception as e:
        logger.error(f"Fundamentals failed for {ticker}: {e}")

    # 2. Technicals
    try:
        data = run_technicals(ticker, TechnicalFetcher())
        if data:
            serialized = to_serializable(data)
            upsert_scan_result(ticker, "technicals", serialized)
    except Exception as e:
        logger.error(f"Technicals failed for {ticker}: {e}")

    # 3. Price Scans
    try:
        data = run_pricescan(ticker, PriceScanFetcher(), SectorManager())
        if data:
            serialized = to_serializable(data)
            upsert_scan_result(ticker, "pricescan", serialized)
    except Exception as e:
        logger.error(f"Price Scans failed for {ticker}: {e}")

    # 4. Candlestick
    try:
        data = run_candlestick(ticker, CandleFetcher(), load_candlestick_map())
        if data:
            serialized = to_serializable(data)
            upsert_scan_result(ticker, "candlestick", serialized)
    except Exception as e:
        logger.error(f"Candlestick failed for {ticker}: {e}")

    # 5. F&O
    try:
        data = run_fo(ticker, FOFetcher(), load_fo_map())
        if data:
            serialized = to_serializable(data)
            upsert_scan_result(ticker, "fo", serialized)
    except Exception as e:
        logger.error(f"F&O failed for {ticker}: {e}")

    # 6. Strike Options
    try:
        data = run_strikeoptions(ticker, StrikeOptionsFetcher(), load_strike_map())
        if data:
            serialized = to_serializable(data)
            upsert_scan_result(ticker, "strikeoptions", serialized)
        else:
            logger.warning(f"No strike options data for {ticker}, skipping store.")
    except Exception as e:
        logger.error(f"Strike Options failed for {ticker}: {e}")

    # 7. Volume & Delivery
    try:
        data = run_volumedelivery(ticker, VolumeDeliveryFetcher(), load_volume_map())
        if data:
            serialized = to_serializable(data)
            upsert_scan_result(ticker, "volumedelivery", serialized)
    except Exception as e:
        logger.error(f"Volume/Delivery failed for {ticker}: {e}")

    logger.info(f"Finished {ticker}")


async def update_all():
    tickers = get_nifty_tickers()  # ~500 symbols
    for t in tickers:
        await update_ticker(t)


if __name__ == "__main__":
    logger.info("Starting full update...")
    asyncio.run(update_all())
    logger.info("Full update complete.")