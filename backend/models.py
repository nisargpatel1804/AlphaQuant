# backend/models.py

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ScanRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=20)


class ScanResponse(BaseModel):
    ticker: str
    scanner: str
    generated_at: datetime
    data: Dict[str, Any] = Field(
        ..., 
        description="Nested dictionary containing structured scan outputs. "
                    "For fundamentals, this expects keys like 'core_metrics' and 'raw_financials'."
    )


class BacktestRequest(BaseModel):
    tickers: List[str] = Field(default_factory=list)
    capital: float = Field(default=1_000_000, ge=0)
    timeframe: str = "2Y"


class BacktestResponse(BaseModel):
    generated_at: datetime
    summary: Dict[str, Any]
    chart: Optional[Dict[str, Any]] = None