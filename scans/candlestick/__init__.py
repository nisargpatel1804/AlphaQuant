"""
Candlestick Analysis Module (AlphaQuant).
Provides tools for identifying 24 key candlestick patterns across 7 categories
(Bullish, Bearish, Reversal, Continuation, Neutral).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .main import CandleEngine as CandleEngine
from .models import TickerCandleData, CandleScanResult
from .fetcher import CandleFetcher
from .scans import CandleScanner
from .patterns import PatternRecognizer

__all__ = [
    "CandleEngine",
    "TickerCandleData",
    "CandleScanResult",
    "CandleFetcher",
    "CandleScanner",
    "PatternRecognizer"
]


def __getattr__(name: str) -> Any:
    if name == "CandleEngine":
        from .main import CandleEngine

        return CandleEngine
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")