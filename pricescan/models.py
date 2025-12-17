"""
Data models and constants for Price Scans.
Defines the structure for Scan Definitions and Results.
"""
from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List

# --------------------------------------------------------------------------
# Subtype Constants (The 18 Categories)
# --------------------------------------------------------------------------
SUBTYPE_PREV_DAY = "Previous Day Breakout"
SUBTYPE_WEEKLY_BREAKOUT = "Weekly Breakout"
SUBTYPE_MONTHLY_BREAKOUT = "Monthly Breakout"
SUBTYPE_52W_BREAKOUT = "52 Week Breakout"
SUBTYPE_52W_RANGE = "52 Week Range"
SUBTYPE_2Y_BREAKOUT = "2 Year Breakout"
SUBTYPE_5Y_BREAKOUT = "5 Year Breakout"
SUBTYPE_ATH_BREAKOUT = "All Time Breakout"
SUBTYPE_1D_BEHAVIOUR = "1 Day Behaviour"
SUBTYPE_2D_BEHAVIOUR = "2 Days Behaviour"
SUBTYPE_3D_BEHAVIOUR = "3 Days Behaviour"
SUBTYPE_REL_PERF = "Relative Performance"
SUBTYPE_RS_21D = "Relative Strength (21 Days)"
SUBTYPE_RS_55D = "Relative Strength (55 Days)"
SUBTYPE_RS_21W = "Relative Strength (21 Weeks)"
SUBTYPE_ADAPTIVE_RS = "Adaptive & Static RS"
SUBTYPE_ABS_RETURN = "Absolute Return"
SUBTYPE_VWAP = "VWAP Scans"

@dataclass(frozen=True)
class PriceScanDefinition:
    """
    Immutable metadata defining a specific price scan.
    Used to register scans in the scanner registry.
    """
    func_name: str         # The method name in the scanner class
    label: str             # Display label (e.g., "Close Crossing Last Week High")
    subtype: str           # The group category (e.g., "Weekly Breakout")
    description: str = ""  # Optional detailed tooltip

@dataclass
class PriceScanResult:
    """
    The calculated outcome of a single scan execution.
    """
    label: str
    subtype: str
    status: str            # Textual status (e.g., "Bullish", "Bearish", "Neutral", "Pending")
    condition_met: bool    # True if the specific trigger condition occurred
    value: Optional[float] = None # The numeric value driving the decision (e.g., % Change, RS Score)
    meta: Dict[str, Any] = field(default_factory=dict) # Extra context (e.g., {'benchmark_val': 120})
    
    def to_dict(self) -> Dict[str, Any]:
        """Converts to dictionary for JSON serialization/UI."""
        return {
            "label": self.label,
            # We map 'subtype' to 'category' to match the UI expectation in app.py
            "category": self.subtype,
            "status": self.status,
            "value": self.value,
            "meta": self.meta,
            "condition_met": self.condition_met
        }

@dataclass
class TickerPriceScanData:
    """
    Container for the final aggregated results for a specific ticker.
    """
    ticker: str
    timestamp: str
    last_close: float
    industry: Optional[str]
    # Results grouped by "Bullish", "Bearish", "Neutral", "Pending" or by Subtype
    # The structure here is flexible, but typically we store a flat list or grouped dict.
    scan_results: Dict[str, List[Dict[str, Any]]]

    # Summary metadata (counts/coverage). Optional so older JSON remains compatible.
    scan_summary: Dict[str, Any] = field(default_factory=dict)