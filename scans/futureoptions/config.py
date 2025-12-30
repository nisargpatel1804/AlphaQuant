"""
Configuration for Futures and Options Scans.
Defines thresholds for PCR and Aggressive Volume definitions.
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

# PCR (Put Call Ratio)
PCR_HIGH_THRESHOLD = 1.5  # Often indicates Overbought/Bullish sentiment
PCR_LOW_THRESHOLD = 0.6   # Often indicates Oversold/Bearish sentiment

# Aggressive Scan Multipliers (Volume Spike needed to be 'Aggressive')
AGGRESSIVE_VOL_MULT = 1.5 # Volume must be 1.5x average to be 'Aggressive'

# Lookback for averages
AVG_PERIOD_VOL = 10

# --------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------
CAT_FUT_OI = "Futures Open Interest"
CAT_FUT_LONG = "Futures Long Position"
CAT_FUT_SHORT = "Futures Short Position"
CAT_PCR = "Put Call Ratio"