"""
Configuration constants for the Technical Analysis module.
This file defines all lookback periods, thresholds, and parameters required
to execute the 214 Technical Scans similar to StockEdge.
"""

# --------------------------------------------------------------------------
# General Settings
# --------------------------------------------------------------------------
# Tolerance for "Nearing" scans (e.g., "Price Near 50 SMA")
# If price is within 1.5% of the target level, it counts as "Near".
NEARING_THRESHOLD_PCT = 1.5 

# Benchmark for Beta calculations (Nifty 50)
BENCHMARK_TICKER = "^NSEI"
BETA_LOOKBACK_YEARS = 1

# --------------------------------------------------------------------------
# 1. Moving Averages (SMA & EMA)
# --------------------------------------------------------------------------
# The specific periods required by the scans
MA_PERIODS = [5, 10, 20, 30, 50, 100, 200]

# Weekly specific periods
WEEKLY_MA_PERIODS = [5, 10, 20, 50]

# --------------------------------------------------------------------------
# 1b. Additional Moving Averages (For completeness)
# --------------------------------------------------------------------------
VWMA_PERIOD = 20
HMA_PERIOD = 9

# --------------------------------------------------------------------------
# 2. Momentum & Oscillators
# --------------------------------------------------------------------------

# Relative Strength Index (RSI)
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
RSI_BULLISH_ZONE = 50  # Crossing above 50 is often considered bullish

# Commodity Channel Index (CCI)
CCI_PERIOD = 20
CCI_OVERBOUGHT = 100
CCI_OVERSOLD = -100
CCI_ZERO = 0

# Stochastic Oscillator
STOCH_K_PERIOD = 14
STOCH_D_PERIOD = 3
STOCH_SMOOTH_K = 3
STOCH_OVERBOUGHT = 80
STOCH_OVERSOLD = 20

# Stochastic RSI
STOCHRSI_PERIOD = 14
STOCHRSI_RSI_LENGTH = 14
STOCHRSI_STOCH_LENGTH = 14
STOCHRSI_K = 3
STOCHRSI_D = 3
STOCHRSI_K_PERIOD = 3
STOCHRSI_D_PERIOD = 3

# William %R
WILLR_PERIOD = 14
WILLR_OVERBOUGHT = -20  # Note: Will%R ranges from 0 to -100
WILLR_OVERSOLD = -80
WILLR_MIDPOINT = -50

# Money Flow Index (MFI)
MFI_PERIOD = 14
MFI_OVERBOUGHT = 80
MFI_OVERSOLD = 20
MFI_MIDPOINT = 50

# Rate of Change (ROC)
ROC_PERIOD = 14  # Standard default, though scan implies general trend
ROC_BULLISH_THRESHOLD = 0

# Awesome Oscillator
AO_FAST = 5
AO_SLOW = 34

# Ultimate Oscillator
ULTOSC_MIN = 7
ULTOSC_MID = 14
ULTOSC_MAX = 28
UO_SHORT = 7
UO_MEDIUM = 14
UO_LONG = 28

# Bull/Bear Power (Elder Ray)
BBP_EMA_PERIOD = 13
BULL_BEAR_EMA = 13

# Momentum (TradingView style)
MOMENTUM_PERIOD = 10

# --------------------------------------------------------------------------
# 3. Trend Indicators
# --------------------------------------------------------------------------

# Moving Average Convergence Divergence (MACD)
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# Average Directional Index (ADX)
ADX_PERIOD = 14
ADX_SMOOTHING = 14
# Thresholds defined in scans
ADX_WEAK_TREND = 20
ADX_STRONG_TREND = 25
ADX_VERY_STRONG_TREND = 40
ADX_NO_TREND = 10

# SuperTrend
SUPERTREND_LENGTH = 7
SUPERTREND_MULTIPLIER = 3

# Parabolic SAR (PSAR)
PSAR_AF_START = 0.02
PSAR_AF_INC = 0.02
PSAR_AF_MAX = 0.2

# Ichimoku Cloud
ICHIMOKU_TENKAN_PERIOD = 9   # Conversion Line
ICHIMOKU_KIJUN_PERIOD = 26   # Base Line
ICHIMOKU_SENKOU_B_PERIOD = 52 # Leading Span B
ICHIMOKU_DISPLACEMENT = 26    # Lagging Span (Chikou) offset

# --------------------------------------------------------------------------
# 4. Volatility
# --------------------------------------------------------------------------

# Bollinger Bands
BB_LENGTH = 20
BB_STD_DEV = 2
# Bandwidth thresholds for Squeeze/Expansion (Percentiles or absolute values)
# Since "Narrow" is relative, we often compare current bandwidth to its own history.
BB_SQUEEZE_PERCENTILE = 20  # Bottom 20% of historical bandwidth
BB_EXPANSION_PERCENTILE = 80 # Top 80% of historical bandwidth

# Average True Range (ATR)
ATR_PERIOD = 14
ATR_TREND_LOOKBACK = 3 # For "ATR Increasing for 3 days" scans

# Narrow Range (NR)
# NR4: Range is smaller than the previous 3 days (total 4)
# NR7: Range is smaller than the previous 6 days (total 7)
NR4_LOOKBACK = 4
NR7_LOOKBACK = 7

# --------------------------------------------------------------------------
# 5. Momentum Score (Proprietary Proxy)
# --------------------------------------------------------------------------
# Since StockEdge Momentum Score is proprietary, we use Return on Investment (ROI)
# or generic Rate of Change (ROC) over these periods as a strong proxy.
MOMENTUM_PERIODS = {
    "1M": 21,   # ~1 Month trading days
    "3M": 63,   # ~3 Months trading days
    "6M": 126   # ~6 Months trading days
}

# Proxy thresholds for "Zones"
# We define "Bullish Zone" as positive momentum significantly above noise
MOMENTUM_BULLISH_THRESHOLD = 5.0  # e.g., > 5% return
MOMENTUM_BEARISH_THRESHOLD = -5.0 # e.g., < -5% return
MOMENTUM_NEUTRAL_LOW = -2.0
MOMENTUM_NEUTRAL_HIGH = 2.0

# --------------------------------------------------------------------------
# 6. Beta
# --------------------------------------------------------------------------
BETA_HIGH_THRESHOLD = 1.5
BETA_LOW_THRESHOLD = 0.5
BETA_NEUTRAL = 1.0

# --------------------------------------------------------------------------
# 7. Pivots
# --------------------------------------------------------------------------
PIVOT_CPR_FACTOR = 1.1  # Used by Camarilla pivots