"""
Strike Options Analysis Module (ReScanX).
Provides tools for analyzing option chains, identifying key support/resistance levels
based on Open Interest (Call High OI, Put High OI), and detecting high activity strikes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scans.strikeoptions.main import StrikeOptionsEngine as StrikeOptionsEngine
from scans.strikeoptions.models import TickerStrikeData, StrikeScanResult
from scans.strikeoptions.fetcher import StrikeOptionsFetcher
from scans.strikeoptions.scans import StrikeOptionsScanner

__all__ = [
    "StrikeOptionsEngine",
    "TickerStrikeData",
    "StrikeScanResult",
    "StrikeOptionsFetcher",
    "StrikeOptionsScanner"
]


def __getattr__(name: str) -> Any:
    if name == "StrikeOptionsEngine":
        from scans.strikeoptions.main import StrikeOptionsEngine

        return StrikeOptionsEngine
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")