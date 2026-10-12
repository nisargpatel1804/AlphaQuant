# backend/api.py

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ==============================================================================
# 1. API REQUEST & RESPONSE MODELS (Consolidated from models.py)
# ==============================================================================
class ScreenerRequest(BaseModel):
    query: str

class ScanRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=20)

class ScanResponse(BaseModel):
    ticker: str
    scanner: str
    generated_at: datetime
    data: Dict[str, Any] = Field(
        ..., 
        description="Nested dictionary containing structured scan outputs."
    )

class BacktestRequest(BaseModel):
    tickers: List[str] = Field(default_factory=list)
    capital: float = Field(default=1_000_000, ge=0)
    timeframe: str = "2Y"

class BacktestResponse(BaseModel):
    generated_at: datetime
    summary: Dict[str, Any]
    chart: Optional[Dict[str, Any]] = None


# ==============================================================================
# 2. INTERNAL IMPORTS
# ==============================================================================
from backend.core.utils import normalize_ticker, to_serializable
from backend.core.db import get_scan_result, upsert_scan_result

# Master Scan Engines
from backend.scans.fundamental_scraper import scrape_screener_complete
from backend.scans.technical_scanner import process_stock as run_technicals
from backend.scans.eod_market_scanner import EODDataFetcher, EODMarketScanner

# Quantitative Engines
from backend.engines.backtest_engine import build_backtest_summary
from backend.engines.metrics_engine import MetricsEngine
from backend.engines.screener_engine import run_screener_query, get_available_metrics

# Consolidated Auxiliary Scrapers
from backend.scans.auxiliary_scrapers import (
    get_seasonality_report,
    get_sector_report,
    get_mapped_sector_data,
    get_tickertape_report,
    get_industry_pe_map,
    get_industry_master_list,
    get_industry_tickers
)

logger = logging.getLogger(__name__)

# ==============================================================================
# 3. FASTAPI CONFIGURATION
# ==============================================================================
app = FastAPI(title="AlphaQuant API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ==============================================================================
# 4. SCANNER RESOLVER FACTORY
# ==============================================================================
async def _resolve_fundamentals(ticker: str) -> Dict[str, Any]:
    # This now returns both fundamentals and peers in one shot
    return await scrape_screener_complete(ticker)

def _resolve_technicals(ticker: str) -> Dict[str, Any]:
    return to_serializable(run_technicals(ticker))

def _resolve_eod_data(ticker: str) -> Dict[str, Any]:
    # Fetches F&O + Delivery Bhavcopies dynamically
    fo_df, cm_df, trade_date = EODDataFetcher.fetch_market_data()
    if fo_df is None or cm_df is None:
        return {}
    index_returns = EODDataFetcher.fetch_index_price_changes([ticker])
    scanner = EODMarketScanner(fo_df, cm_df, trade_date, index_returns)
    return to_serializable(scanner.scan_stock(ticker))


SCAN_RESOLVERS: Dict[str, Callable[[str], Any]] = {
    "fundamentals": _resolve_fundamentals,
    "technicals": _resolve_technicals,
    "eod_data": _resolve_eod_data,
}

async def run_scan_async(scan_name: str, ticker: str) -> Dict[str, Any]:
    scanner = scan_name.strip().lower()
    normalized = normalize_ticker(ticker)
    resolver = SCAN_RESOLVERS.get(scanner)
    if resolver is None:
        raise KeyError(f"Unknown scanner module: {scan_name}")

    result = resolver(normalized)
    if asyncio.iscoroutine(result):
        result = await result
    return to_serializable(result)


async def _cached_or_compute(scan_name: str, ticker: str) -> Dict[str, Any]:
    """Try to fetch from DB cache; if missing, compute instantly and store."""
    ticker = ticker.upper()
    cached = get_scan_result(ticker, scan_name)
    if cached is not None:
        return cached

    data = await run_scan_async(scan_name, ticker)
    upsert_scan_result(ticker, scan_name, data if data is not None else {})
    return data or {}


# ==============================================================================
# 5. CORE ENDPOINTS (Master Engines)
# ==============================================================================

@app.get("/api/v1/fundamentals/{ticker}", response_model=ScanResponse)
async def get_fundamentals(ticker: str):
    try:
        data = await _cached_or_compute("fundamentals", ticker)
        return {"ticker": ticker.upper(), "scanner": "fundamentals", "generated_at": datetime.now(timezone.utc).isoformat(), "data": data}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.get("/api/v1/technicals/{ticker}", response_model=ScanResponse)
async def get_technicals(ticker: str):
    """Returns the unified 1d/1w/1m technicals, price action, volume, and candlesticks."""
    try:
        data = await _cached_or_compute("technicals", ticker)
        return {"ticker": ticker.upper(), "scanner": "technicals", "generated_at": datetime.now(timezone.utc).isoformat(), "data": data}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.get("/api/v1/eod/{ticker}", response_model=ScanResponse)
async def get_eod_data(ticker: str):
    """Returns official NSE Delivery % and Derivative F&O Build-Up."""
    try:
        data = await _cached_or_compute("eod_data", ticker)
        return {"ticker": ticker.upper(), "scanner": "eod_data", "generated_at": datetime.now(timezone.utc).isoformat(), "data": data}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ==============================================================================
# 6. AUXILIARY DATA ENDPOINTS (Global Market Context)
# ==============================================================================

@app.get("/api/v1/seasonality/{symbol}")
def read_seasonality(symbol: str):
    try: return get_seasonality_report(symbol)
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.get("/api/v1/sector")
def read_sector():
    try: return get_sector_report()
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.get("/api/v1/sector/mapped/{screener_industry}")
def read_mapped_sector(screener_industry: str):
    """Resolves a specific Screener industry to its parent Moneycontrol sector momentum."""
    try: return get_mapped_sector_data(screener_industry)
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.get("/api/v1/tickertape")
def read_tickertape():
    try: return get_tickertape_report()
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.get("/api/v1/industry/pe-map")
def read_industry_pe_map():
    try: return get_industry_pe_map()
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.get("/api/v1/industry/list")
def read_industry_list():
    try: return get_industry_master_list()
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.get("/api/v1/industry/tickers")
def read_industry_tickers(url: str = Query(..., description="Screener industry page URL")):
    try: return get_industry_tickers(url)
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.get("/api/v1/peers/{symbol}")
def read_peers(symbol: str):
    """Fetches peers locally from the fundamentals cache (preventing dual-scraping)."""
    try:
        cached = get_scan_result(symbol.upper(), "fundamentals")
        if cached: return {"peers": cached.get("peers", []), "peers_detailed": cached.get("peers_detailed", [])}
        return {"peers": []}
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc)) from exc


# ==============================================================================
# 7. QUANTITATIVE ENGINES (Metrics, Screener, Backtesting)
# ==============================================================================

@app.get("/api/v1/metrics/{ticker}")
async def get_metrics(ticker: str):
    """Returns 150+ pre-calculated, flattened metrics for the specified ticker."""
    try:
        engine = MetricsEngine()
        data = engine.build_flat_metrics(ticker)
        return {"ticker": ticker.upper(), "generated_at": datetime.now(timezone.utc).isoformat(), "data": data}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.post("/api/v1/screener/run")
async def execute_screener(request: ScreenerRequest):
    """Evaluates custom screener queries across the universe instantly."""
    results, error, count = run_screener_query(request.query)
    if error: raise HTTPException(status_code=400, detail=error)
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "query": request.query, "match_count": count, "data": results}

@app.get("/api/v1/screener/metrics")
async def get_screener_metrics():
    """Returns all available strict metric names for frontend autocomplete."""
    metrics = get_available_metrics()
    return {"metrics": metrics, "count": len(metrics)}

@app.post("/api/v1/backtester", response_model=BacktestResponse)
def run_backtest(request: BacktestRequest):
    summary = build_backtest_summary(request.tickers, request.capital, request.timeframe)
    return BacktestResponse(generated_at=summary["generated_at"], summary=summary["summary"], chart=summary.get("chart"))


# ==============================================================================
# STARTUP
# ==============================================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)