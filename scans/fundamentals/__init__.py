"""
Fundamentals Analysis Module (AlphaQuant).
Provides tools for scraping Screener.in, processing financial data,
and executing fundamental health scans.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from scans.fundamentals.fetcher import ScreenerScraper
from scans.fundamentals.scans import FundamentalScans, ScanDefinition
from scans.fundamentals.utils import (
    get_nifty_tickers,
    load_master_industry_map,
    build_ticker_to_industry_and_pe,
    apply_industry_context
)
try:
    from scans.fundamentals.database import SupabaseManager
except Exception:
    # SupabaseManager is optional (may not be present in all environments).
    SupabaseManager = None

if TYPE_CHECKING:
    from scans.fundamentals.main import process_ticker as process_ticker

__all__ = [
    "ScreenerScraper",
    "FundamentalScans",
    "ScanDefinition",
    "get_nifty_tickers",
    "load_master_industry_map",
    "build_ticker_to_industry_and_pe",
    "apply_industry_context",
    "SupabaseManager",
    "process_ticker"
]


def __getattr__(name: str) -> Any:
    if name == "process_ticker":
        from scans.fundamentals.main import process_ticker

        return process_ticker
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")