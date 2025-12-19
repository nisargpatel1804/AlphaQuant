"""
Data models for Strike Wise Options Scans.
"""
from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List

@dataclass
class StrikeScanResult:
    """
    The calculated outcome of a single scan execution.
    """
    label: str            # e.g. "Highest Call OI"
    category: str         # e.g. "Call Options OI"
    strike_price: float   # The strike where the condition met
    value: float          # The metric value (e.g. OI count, Change %)
    action: str = "Neutral" # Derived signal (Buy/Sell/Neutral) -> High Call OI = Resistance (Sell/Neutral)
    
    def to_dict(self) -> Dict[str, Any]:
        """Converts to dictionary for JSON serialization/UI."""
        return {
            "label": self.label,
            "category": self.category,
            "strike_price": self.strike_price,
            "value": self.value,
            "action": self.action
        }

@dataclass
class TickerStrikeData:
    """
    Container for the final aggregated results for a specific ticker.
    """
    ticker: str
    timestamp: str
    last_close: float
    expiry_date: str
    
    # Structure: Dict[CategoryName, {'signal': str, 'scans': List[Dict]}]
    categories: Dict[str, Any]
    
    scan_summary: Dict[str, Any] = field(default_factory=dict)