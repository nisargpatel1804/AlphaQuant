"""
Configuration for Volume and Delivery Scans.
Defines constants, thresholds, and lookback periods.
"""
from pathlib import Path

# --------------------------------------------------------------------------
# Paths (centralized RESULTS folder)
# --------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "RESULTS" / "scans" / Path(__file__).resolve().parent.name
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------
# Thresholds
# --------------------------------------------------------------------------
# Delivery Percentage Thresholds
HIGH_DELIVERY_PCT = 50.0       # > 50% delivery is considered high
VERY_HIGH_DELIVERY_PCT = 75.0  # > 75% delivery

# Volume/Quantity Multipliers (vs Average)
HIGH_VOLUME_MULT = 1.5         # 1.5x the average volume
VERY_HIGH_VOLUME_MULT = 2.5    # 2.5x the average volume

# Lookback periods for Averages
AVG_PERIOD_DAILY = 10          # 10-day average for daily scans
AVG_PERIOD_WEEKLY = 4          # 4-week average
AVG_PERIOD_MONTHLY = 3         # 3-month average

# --------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------
CAT_DAILY_VD = "Daily Volume & Delivery"
CAT_WEEKLY_VD = "Weekly Volume & Delivery"
CAT_MONTHLY_VD = "Monthly Volume & Delivery"