"""
Technical Analysis Module (AlphaQuant).
Provides tools for fetching market data, calculating indicators,
and executing technical scans.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from scans.technicals.fetcher import TechnicalFetcher
from scans.technicals.indicators import TechnicalIndicators
from scans.technicals.scans import TechnicalScans, TechScanDefinition

if TYPE_CHECKING:
    from scans.technicals.main import process_stock as process_stock

__all__ = [
    "TechnicalFetcher",
    "TechnicalIndicators",
    "TechnicalScans",
    "TechScanDefinition",
    "process_stock"
]


def __getattr__(name: str) -> Any:
    if name == "process_stock":
        from scans.technicals.main import process_stock

        return process_stock
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")