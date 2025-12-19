"""
Configuration for Candlestick Scans.
Defines thresholds for identifying specific candle shapes (Doji, Marubozu, etc.).
"""
from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "scans" / "candlestick" / "results"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------
# Candle Shape Thresholds
# --------------------------------------------------------------------------

# Doji: Body size <= 3% of total range
DOJI_BODY_THRESHOLD = 0.03 

# Marubozu: Shadow size <= 5% of body size (Very small wicks)
MARUBOZU_SHADOW_THRESHOLD = 0.05 

# Hammer/Hanging Man: Lower shadow >= 2x Body
HAMMER_SHADOW_MULTIPLIER = 2.0
HAMMER_UPPER_SHADOW_LIMIT = 0.1 # Upper shadow should be small relative to body

# Long Candle: Body > Average Body * Multiplier
# We use a moving average of body sizes to determine if a candle is "Long" relative to recent volatility.
LONG_BODY_MULTIPLIER = 1.5
AVG_BODY_PERIOD = 10

# --------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------
CAT_BULLISH = "Bullish Scans"
CAT_BULLISH_CONT = "Bullish Continuation Scans"
CAT_BULLISH_REV = "Bullish Reversal Scans"
CAT_BEARISH = "Bearish Scans"
CAT_BEARISH_CONT = "Bearish Continuation Scans"
CAT_BEARISH_REV = "Bearish Reversal Scans"
CAT_NEUTRAL = "Neutral Scans"