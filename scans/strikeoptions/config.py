"""
Configuration for Strike Wise Options Scans.
Defines thresholds for significant OI changes to filter out illiquid strikes.
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

# Minimum Open Interest to consider a strike "significant" (prevents noise from deep OTM illiquid strikes)
MIN_OI_THRESHOLD = 100 

# Minimum Volume to consider "Active"
MIN_VOL_THRESHOLD = 50

# --------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------
CAT_CALL_OI = "Call Options OI"
CAT_PUT_OI = "Put Options OI"
CAT_ACTIVITY = "Options Activity"