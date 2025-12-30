"""
Price Scan Module (AlphaQuant).
Implements 117 Price Scans across 18 subtypes including:
- Breakouts (Daily, Weekly, Monthly, 52W, ATH)
- Behavioural Scans (Gap, Sequences)
- Relative Strength (vs Benchmark & vs Sector)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scans.pricescan.main import PriceScanEngine as PriceScanEngine
from scans.pricescan.models import TickerPriceScanData, PriceScanResult
from scans.pricescan.fetcher import PriceScanFetcher
from scans.pricescan.sector_manager import SectorManager
from scans.pricescan.scans import PriceScanner

__all__ = [
    "PriceScanEngine",
    "TickerPriceScanData",
    "PriceScanResult",
    "PriceScanFetcher",
    "SectorManager",
    "PriceScanner"
]


def __getattr__(name: str) -> Any:
    if name == "PriceScanEngine":
        from scans.pricescan.main import PriceScanEngine

        return PriceScanEngine
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")