"""
Data models for Volume and Delivery Scans.
"""
from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List

@dataclass
class VolumeDeliveryResult:
    """
    The calculated outcome of a single scan execution.
    """
    label: str
    category: str
    status: str            # e.g., "High Delivery", "Volume Spike"
    condition_met: bool
    value: Optional[float] = None
    action: str = "Neutral" # Derived signal (Buy/Sell/Neutral)
    
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
class TickerVolumeDeliveryData:
    """
    Container for the final aggregated results for a specific ticker.
    """
    ticker: str
    timestamp: str
    last_close: float
    last_volume: float
    industry: Optional[str]
    
    # Structure: Dict[CategoryName, {'signal': str, 'scans': List[Dict]}]
    categories: Dict[str, Any]
    
    scan_summary: Dict[str, Any] = field(default_factory=dict)