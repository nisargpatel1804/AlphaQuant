"""
Library of 24 Candlestick Pattern Detection Functions.
Each function takes a DataFrame and returns a boolean Series indicating pattern presence on the last row.
"""
import pandas as pd
import numpy as np
from .config import (
    DOJI_BODY_THRESHOLD, MARUBOZU_SHADOW_THRESHOLD,
    HAMMER_SHADOW_MULTIPLIER, HAMMER_UPPER_SHADOW_LIMIT,
    LONG_BODY_MULTIPLIER, AVG_BODY_PERIOD
)

class PatternRecognizer:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        # Pre-calculate basic candle properties
        self.open = df['Open']
        self.close = df['Close']
        self.high = df['High']
        self.low = df['Low']
        
        self.body = abs(self.close - self.open)
        self.range = self.high - self.low
        # Protect against zero range to avoid division by zero
        self.range = self.range.replace(0, np.nan) 
        
        self.upper_shadow = self.high - np.maximum(self.close, self.open)
        self.lower_shadow = np.minimum(self.close, self.open) - self.low
        
        # Rolling average body size for "Long" candle detection
        self.avg_body = self.body.rolling(AVG_BODY_PERIOD).mean()
        
        self.is_bullish = self.close > self.open
        self.is_bearish = self.close < self.open

    # --- Helpers ---
    def _is_doji(self, idx=-1):
        # Body is very small relative to range
        rng = self.range.iloc[idx]
        if pd.isna(rng): return False # Handle zero range case
        return (self.body.iloc[idx] / rng) <= DOJI_BODY_THRESHOLD

    def _is_long(self, idx=-1):
        if pd.isna(self.avg_body.iloc[idx]): return False
        return self.body.iloc[idx] > (self.avg_body.iloc[idx] * LONG_BODY_MULTIPLIER)

    def _is_small(self, idx=-1):
        if pd.isna(self.avg_body.iloc[idx]): return True # Default to small if no history
        return self.body.iloc[idx] < self.avg_body.iloc[idx]

    # ==============================================================================
    # 1. Bullish Scans
    # ==============================================================================
    def white_marubozu(self):
        # Long Bullish Candle + Tiny Shadows
        i = -1
        if not self.is_bullish.iloc[i] or not self._is_long(i): return False
        return (self.upper_shadow.iloc[i] <= self.body.iloc[i] * MARUBOZU_SHADOW_THRESHOLD) and \
               (self.lower_shadow.iloc[i] <= self.body.iloc[i] * MARUBOZU_SHADOW_THRESHOLD)

    # ==============================================================================
    # 2. Bullish Continuation
    # ==============================================================================
    def bullish_engulfing(self):
        # Prev: Bearish, Curr: Bullish. Curr Body covers Prev Body.
        # Often considered Reversal, but StockEdge categorizes as Continuation in specific contexts.
        # Here we implement the strict pattern shape.
        i = -1
        if not (self.is_bearish.iloc[i-1] and self.is_bullish.iloc[i]): return False
        return (self.close.iloc[i] > self.open.iloc[i-1]) and (self.open.iloc[i] < self.close.iloc[i-1])

    def rising_three_methods(self):
        # Long Bullish, followed by 3 small bearish inside the range, then Long Bullish
        # Needs 5 candles.
        if len(self.df) < 5: return False
        
        # 1. First is Long Bullish
        first_long = self._is_long(-5) and self.is_bullish.iloc[-5]
        # 5. Last is Long Bullish and closes above first close
        last_long = self._is_long(-1) and self.is_bullish.iloc[-1] and (self.close.iloc[-1] > self.close.iloc[-5])
        
        if not (first_long and last_long): return False

        # 2,3,4 are small and stay within the range of the first candle
        # Checking if high/low of middle candles are generally contained is the strict rule, 
        # simplified check: they are small and bearish/consolidating
        middle_candles = self.df.iloc[-4:-1]
        for idx in range(3):
            # Check range containment: High < First High, Low > First Low
            if not (middle_candles['High'].iloc[idx] < self.high.iloc[-5] and 
                    middle_candles['Low'].iloc[idx] > self.low.iloc[-5]):
                return False
        return True

    # ==============================================================================
    # 3. Bullish Reversal
    # ==============================================================================
    def hammer(self):
        i = -1
        # Small body, long lower shadow, minimal upper shadow
        # Trend should be down (simplified: close < close[5])
        if len(self.df) < 6: return False
        is_downtrend = self.close.iloc[i] < self.close.iloc[i-5]
        
        is_pattern = (self.lower_shadow.iloc[i] >= HAMMER_SHADOW_MULTIPLIER * self.body.iloc[i]) and \
                     (self.upper_shadow.iloc[i] <= self.body.iloc[i] * HAMMER_UPPER_SHADOW_LIMIT)
        return is_downtrend and is_pattern

    def inverted_hammer(self):
        i = -1
        if len(self.df) < 6: return False
        is_downtrend = self.close.iloc[i] < self.close.iloc[i-5]
        
        is_pattern = (self.upper_shadow.iloc[i] >= HAMMER_SHADOW_MULTIPLIER * self.body.iloc[i]) and \
                     (self.lower_shadow.iloc[i] <= self.body.iloc[i] * HAMMER_UPPER_SHADOW_LIMIT)
        return is_downtrend and is_pattern

    def piercing_pattern(self):
        i = -1
        # Bearish then Bullish. Bullish opens lower but closes > 50% of prev body
        if not (self.is_bearish.iloc[i-1] and self.is_bullish.iloc[i]): return False
        
        midpoint = self.close.iloc[i-1] + ((self.open.iloc[i-1] - self.close.iloc[i-1]) / 2)
        
        return (self.open.iloc[i] < self.low.iloc[i-1]) and (self.close.iloc[i] > midpoint)

    def morning_star(self):
        # Long Bearish -> Small/Doji (Gap Down ideal) -> Long Bullish
        if len(self.df) < 3: return False
        i = -1
        
        first = self.is_bearish.iloc[i-2] and self._is_long(i-2)
        second = self._is_small(i-1) # Color doesn't matter much, but usually gap down
        third = self.is_bullish.iloc[i] and self._is_long(i) and (self.close.iloc[i] > (self.open.iloc[i-2] + self.close.iloc[i-2])/2)
        
        return first and second and third

    def bullish_harami(self):
        # Long Bearish -> Small Bullish inside prev body
        i = -1
        if not (self.is_bearish.iloc[i-1] and self.is_bullish.iloc[i]): return False
        
        return self._is_long(i-1) and \
               (self.open.iloc[i] < self.open.iloc[i-1]) and \
               (self.close.iloc[i] > self.close.iloc[i-1]) and \
               self._is_small(i)

    def three_white_soldiers(self):
        # 3 consecutive long bullish candles closing higher
        if len(self.df) < 3: return False
        return all(self.is_bullish.iloc[i] for i in range(-3, 0)) and \
               all(self._is_long(i) for i in range(-3, 0)) and \
               (self.close.iloc[-1] > self.close.iloc[-2] > self.close.iloc[-3])

    def three_inside_up(self):
        # Bullish Harami (first 2) confirmed by 3rd Bullish closing higher
        if len(self.df) < 3: return False
        
        # Check Harami on [-3, -2]
        harami = self.is_bearish.iloc[-3] and self.is_bullish.iloc[-2] and \
                 (self.open.iloc[-2] < self.open.iloc[-3]) and (self.close.iloc[-2] > self.close.iloc[-3])
        
        # Check confirmation
        confirm = self.is_bullish.iloc[-1] and (self.close.iloc[-1] > self.close.iloc[-2])
        
        return harami and confirm

    def three_outside_up(self):
        # Bullish Engulfing (first 2) confirmed by 3rd Bullish closing higher
        if len(self.df) < 3: return False
        
        engulfing = self.is_bearish.iloc[-3] and self.is_bullish.iloc[-2] and \
                    (self.close.iloc[-2] > self.open.iloc[-3]) and (self.open.iloc[-2] < self.close.iloc[-3])
        
        confirm = self.is_bullish.iloc[-1] and (self.close.iloc[-1] > self.close.iloc[-2])
        
        return engulfing and confirm

    def bullish_counterattack(self):
        # Long Bearish, then Bullish opening much lower but closing at same level as prev close
        i = -1
        if not (self.is_bearish.iloc[i-1] and self.is_bullish.iloc[i]): return False
        
        is_long_bear = self._is_long(i-1)
        # Close equality with some tolerance
        close_match = abs(self.close.iloc[i] - self.close.iloc[i-1]) / self.close.iloc[i-1] < 0.005 
        
        return is_long_bear and close_match

    # ==============================================================================
    # 4. Bearish Scans
    # ==============================================================================
    def black_marubozu(self):
        # Long Bearish Candle + Tiny Shadows
        i = -1
        if not self.is_bearish.iloc[i] or not self._is_long(i): return False
        return (self.upper_shadow.iloc[i] <= self.body.iloc[i] * MARUBOZU_SHADOW_THRESHOLD) and \
               (self.lower_shadow.iloc[i] <= self.body.iloc[i] * MARUBOZU_SHADOW_THRESHOLD)

    # ==============================================================================
    # 5. Bearish Continuation
    # ==============================================================================
    def falling_three_methods(self):
        # Long Bearish, followed by 3 small bullish inside the range, then Long Bearish
        if len(self.df) < 5: return False
        
        first_long = self._is_long(-5) and self.is_bearish.iloc[-5]
        last_long = self._is_long(-1) and self.is_bearish.iloc[-1] and (self.close.iloc[-1] < self.close.iloc[-5])
        
        if not (first_long and last_long): return False

        middle_candles = self.df.iloc[-4:-1]
        for idx in range(3):
            # Check range containment: Low > First Low, High < First High
            if not (middle_candles['Low'].iloc[idx] > self.low.iloc[-5] and 
                    middle_candles['High'].iloc[idx] < self.high.iloc[-5]):
                return False
        return True

    # ==============================================================================
    # 6. Bearish Reversal
    # ==============================================================================
    def hanging_man(self):
        i = -1
        # Same shape as Hammer, but in Uptrend
        if len(self.df) < 6: return False
        is_uptrend = self.close.iloc[i] > self.close.iloc[i-5]
        
        is_pattern = (self.lower_shadow.iloc[i] >= HAMMER_SHADOW_MULTIPLIER * self.body.iloc[i]) and \
                     (self.upper_shadow.iloc[i] <= self.body.iloc[i] * HAMMER_UPPER_SHADOW_LIMIT)
        return is_uptrend and is_pattern

    def shooting_star(self):
        i = -1
        # Same shape as Inverted Hammer, but in Uptrend
        if len(self.df) < 6: return False
        is_uptrend = self.close.iloc[i] > self.close.iloc[i-5]
        
        is_pattern = (self.upper_shadow.iloc[i] >= HAMMER_SHADOW_MULTIPLIER * self.body.iloc[i]) and \
                     (self.lower_shadow.iloc[i] <= self.body.iloc[i] * HAMMER_UPPER_SHADOW_LIMIT)
        return is_uptrend and is_pattern

    def dark_cloud_cover(self):
        i = -1
        # Bullish then Bearish. Bearish opens higher but closes > 50% into prev body
        if not (self.is_bullish.iloc[i-1] and self.is_bearish.iloc[i]): return False
        
        midpoint = self.close.iloc[i-1] - ((self.close.iloc[i-1] - self.open.iloc[i-1]) / 2)
        
        return (self.open.iloc[i] > self.high.iloc[i-1]) and (self.close.iloc[i] < midpoint)

    def evening_star(self):
        # Long Bullish -> Small/Doji (Gap Up ideal) -> Long Bearish
        if len(self.df) < 3: return False
        i = -1
        
        first = self.is_bullish.iloc[i-2] and self._is_long(i-2)
        second = self._is_small(i-1)
        third = self.is_bearish.iloc[i] and self._is_long(i) and (self.close.iloc[i] < (self.open.iloc[i-2] + self.close.iloc[i-2])/2)
        
        return first and second and third

    def bearish_harami(self):
        i = -1
        if not (self.is_bullish.iloc[i-1] and self.is_bearish.iloc[i]): return False
        
        return self._is_long(i-1) and \
               (self.open.iloc[i] < self.close.iloc[i-1]) and \
               (self.close.iloc[i] > self.open.iloc[i-1]) and \
               self._is_small(i)

    def three_black_crows(self):
        if len(self.df) < 3: return False
        return all(self.is_bearish.iloc[i] for i in range(-3, 0)) and \
               all(self._is_long(i) for i in range(-3, 0)) and \
               (self.close.iloc[-1] < self.close.iloc[-2] < self.close.iloc[-3])

    def three_inside_down(self):
        # Bearish Harami (first 2) confirmed by 3rd Bearish closing lower
        if len(self.df) < 3: return False
        
        harami = self.is_bullish.iloc[-3] and self.is_bearish.iloc[-2] and \
                 (self.open.iloc[-2] < self.close.iloc[-3]) and (self.close.iloc[-2] > self.open.iloc[-3])
        
        confirm = self.is_bearish.iloc[-1] and (self.close.iloc[-1] < self.close.iloc[-2])
        return harami and confirm

    def three_outside_down(self):
        # Bearish Engulfing (first 2) confirmed by 3rd Bearish closing lower
        if len(self.df) < 3: return False
        
        engulfing = self.is_bullish.iloc[-3] and self.is_bearish.iloc[-2] and \
                    (self.close.iloc[-2] < self.open.iloc[-3]) and (self.open.iloc[-2] > self.close.iloc[-3])
        
        confirm = self.is_bearish.iloc[-1] and (self.close.iloc[-1] < self.close.iloc[-2])
        return engulfing and confirm

    def bearish_counterattack(self):
        # Long Bullish, then Bearish opening much higher but closing at same level as prev close
        i = -1
        if not (self.is_bullish.iloc[i-1] and self.is_bearish.iloc[i]): return False
        
        is_long_bull = self._is_long(i-1)
        close_match = abs(self.close.iloc[i] - self.close.iloc[i-1]) / self.close.iloc[i-1] < 0.005 
        
        return is_long_bull and close_match

    # ==============================================================================
    # 7. Neutral
    # ==============================================================================
    def doji(self):
        return self._is_doji(-1)