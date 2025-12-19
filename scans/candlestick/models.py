"""
Data models for Candlestick Scans.
"""
from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List

@dataclass
class CandleScanResult:
    """
    The calculated outcome of a single scan execution.
    """
    label: str            # e.g., "Bullish Engulfing"
    category: str         # e.g., "Bullish Reversal Scans"
    status: str           # e.g., "Pattern Formed"
    condition_met: bool
    value: Optional[float] = None # Close Price on formation
    action: str = "Neutral" # Signal derived from the pattern
    
    def to_dict(self) -> Dict[str, Any]:
        """Converts to dictionary for JSON serialization/UI."""
        return {
            "label": self.label,
            "category": self.category,
            "status": self.status,
            "value": self.value,
            "action": self.action,
            "condition_met": self.condition_met
        }

@dataclass
class TickerCandleData:
    """
    Container for the final aggregated results for a specific ticker.
    """
    ticker: str
    timestamp: str
    last_close: float
    industry: Optional[str]
    
    # Structure: Dict[CategoryName, {'signal': str, 'scans': List[Dict]}]
    categories: Dict[str, Any]
    
    scan_summary: Dict[str, Any] = field(default_factory=dict)