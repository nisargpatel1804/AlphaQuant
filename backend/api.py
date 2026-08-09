# backend/api.py

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.models import BacktestRequest, BacktestResponse, ScanResponse
from backend.utils import normalize_ticker, to_serializable

# Database cache
from backend.db import get_scan_result, upsert_scan_result

# Scanner modules
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

# Backtester
from backend.backtester_core import build_backtest_summary

# Service modules (placed directly under backend/)
from backend.seasonality import get_seasonality_report
from backend.sector import get_sector_report
from backend.tickertape import get_tickertape_report
from backend.peers import get_peers_report
from backend.industry import get_industry_master_list, get_industry_pe_map, get_industry_tickers

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# FastAPI app
# ----------------------------------------------------------------------
app = FastAPI(title="AlphaQuant API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------------
# Health check
# ----------------------------------------------------------------------
@app.get("/health")
def health_check():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ----------------------------------------------------------------------
# Scanner factory (inline)
# ----------------------------------------------------------------------
async def _resolve_fundamentals(ticker: str) -> Dict[str, Any]:
    return await scrape_screener_complete(ticker)


def _resolve_technicals(ticker: str) -> Dict[str, Any]:
    return to_serializable(run_technicals(ticker, TechnicalFetcher()))


def _resolve_pricescan(ticker: str) -> Dict[str, Any]:
    return to_serializable(run_pricescan(ticker, PriceScanFetcher(), SectorManager()))


def _resolve_candlestick(ticker: str) -> Dict[str, Any]:
    return to_serializable(run_candlestick(ticker, CandleFetcher(), load_candlestick_map()))


def _resolve_fo(ticker: str) -> Dict[str, Any]:
    return to_serializable(run_fo(ticker, FOFetcher(), load_fo_map()))


def _resolve_strikeoptions(ticker: str) -> Dict[str, Any]:
    return to_serializable(run_strikeoptions(ticker, StrikeOptionsFetcher(), load_strike_map()))


def _resolve_volumedelivery(ticker: str) -> Dict[str, Any]:
    return to_serializable(run_volumedelivery(ticker, VolumeDeliveryFetcher(), load_volume_map()))


SCAN_RESOLVERS: Dict[str, Callable[[str], Any]] = {
    "fundamentals": _resolve_fundamentals,
    "technicals": _resolve_technicals,
    "pricescan": _resolve_pricescan,
    "candlestick": _resolve_candlestick,
    "fo": _resolve_fo,
    "strikeoptions": _resolve_strikeoptions,
    "volumedelivery": _resolve_volumedelivery,
}


async def run_scan_async(scan_name: str, ticker: str) -> Dict[str, Any]:
    scanner = scan_name.strip().lower()
    normalized = normalize_ticker(ticker)
    resolver = SCAN_RESOLVERS.get(scanner)
    if resolver is None:
        raise KeyError(f"Unknown scanner: {scan_name}")

    result = resolver(normalized)
    if asyncio.iscoroutine(result):
        result = await result
    return to_serializable(result)


async def _cached_or_compute(scan_name: str, ticker: str) -> Dict[str, Any]:
    """
    Try to fetch from the database cache; if not found, compute and store.
    If the scanner returns None, store an empty dict and return that.
    """
    ticker = ticker.upper()
    cached = get_scan_result(ticker, scan_name)
    if cached is not None:
        return cached

    # Compute on the fly
    data = await run_scan_async(scan_name, ticker)
    if data is not None:
        upsert_scan_result(ticker, scan_name, data)
    else:
        logger.warning(f"Scanner '{scan_name}' returned no data for {ticker}. Storing empty dict.")
        data = {}
        upsert_scan_result(ticker, scan_name, data)  # store empty dict to avoid repeated computation
    return data


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------

# 1. Fundamentals
@app.get("/api/v1/fundamentals/{ticker}", response_model=ScanResponse)
async def get_fundamentals(ticker: str):
    try:
        data = await _cached_or_compute("fundamentals", ticker)
        return {
            "ticker": ticker.upper(),
            "scanner": "fundamentals",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# 2. Technicals
@app.get("/api/v1/technicals/{ticker}", response_model=ScanResponse)
async def get_technicals(ticker: str):
    try:
        data = await _cached_or_compute("technicals", ticker)
        return {
            "ticker": ticker.upper(),
            "scanner": "technicals",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# 3. Price Scans
@app.get("/api/v1/pricescan/{ticker}", response_model=ScanResponse)
async def get_pricescan(ticker: str):
    try:
        data = await _cached_or_compute("pricescan", ticker)
        return {
            "ticker": ticker.upper(),
            "scanner": "pricescan",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# 4. Candlestick
@app.get("/api/v1/candlestick/{ticker}", response_model=ScanResponse)
async def get_candlestick(ticker: str):
    try:
        data = await _cached_or_compute("candlestick", ticker)
        return {
            "ticker": ticker.upper(),
            "scanner": "candlestick",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# 5. Futures & Options
@app.get("/api/v1/fo/{ticker}", response_model=ScanResponse)
async def get_fo(ticker: str):
    try:
        data = await _cached_or_compute("fo", ticker)
        return {
            "ticker": ticker.upper(),
            "scanner": "fo",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# 6. Strike Options
@app.get("/api/v1/strike/{ticker}", response_model=ScanResponse)
async def get_strike(ticker: str):
    try:
        data = await _cached_or_compute("strikeoptions", ticker)
        return {
            "ticker": ticker.upper(),
            "scanner": "strikeoptions",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# 7. Volume & Delivery
@app.get("/api/v1/volumedelivery/{ticker}", response_model=ScanResponse)
async def get_volumedelivery(ticker: str):
    try:
        data = await _cached_or_compute("volumedelivery", ticker)
        return {
            "ticker": ticker.upper(),
            "scanner": "volumedelivery",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# 8. Backtester
@app.post("/api/v1/backtester", response_model=BacktestResponse)
def run_backtest(request: BacktestRequest):
    summary = build_backtest_summary(request.tickers, request.capital, request.timeframe)
    return BacktestResponse(
        generated_at=summary["generated_at"],
        summary=summary["summary"],
        chart=summary.get("chart"),
    )


# 9. Seasonality
@app.get("/api/v1/seasonality/{symbol}")
def read_seasonality(symbol: str):
    try:
        return get_seasonality_report(symbol)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# 10. Sector
@app.get("/api/v1/sector")
def read_sector():
    try:
        return get_sector_report()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# 11. Tickertape
@app.get("/api/v1/tickertape")
def read_tickertape():
    try:
        return get_tickertape_report()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# 12. Peers
@app.get("/api/v1/peers/{symbol}")
def read_peers(symbol: str):
    try:
        return get_peers_report(symbol)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# 13. Industry – PE map
@app.get("/api/v1/industry/pe-map")
def read_industry_pe_map():
    try:
        return get_industry_pe_map()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# 14. Industry – list
@app.get("/api/v1/industry/list")
def read_industry_list():
    try:
        return get_industry_master_list()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# 15. Industry – tickers by URL
@app.get("/api/v1/industry/tickers")
def read_industry_tickers(url: str = Query(..., description="Screener industry page URL")):
    try:
        return get_industry_tickers(url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ----------------------------------------------------------------------
# Optional: if you want to run uvicorn directly from this file
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)