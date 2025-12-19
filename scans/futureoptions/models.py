"""
Data models for Futures and Options Scans.
"""
from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List

@dataclass
class FOScanResult:
    """
    The calculated outcome of a single scan execution.
    """
    label: str
    category: str
    status: str            # e.g., "Long Build Up", "High PCR"
    condition_met: bool
    value: Optional[float] = None
    action: str = "Neutral" # Derived signal (Buy/Sell/Neutral)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "category": self.category,
            "status": self.status,
            "value": self.value,
            "action": self.action,
            "condition_met": self.condition_met
        }

@dataclass
class TickerFOData:
    """
    Container for the final aggregated results for a specific ticker.
    """
    ticker: str
    timestamp: str
    last_close: float
    last_oi: Optional[float]
    last_pcr: Optional[float]
    
    # Structure: Dict[CategoryName, {'signal': str, 'scans': List[Dict]}]
    categories: Dict[str, Any]
    
    scan_summary: Dict[str, Any] = field(default_factory=dict)