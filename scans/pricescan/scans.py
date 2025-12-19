"""
Price Scan Logic Module.
Implements the full 117 Price Scans categorized into 18 Subtypes.
Handles Multi-Timeframe logic (Daily, Weekly, Monthly) and Relative Strength.
Refactored to group results by Category and calculate Signals (Strong Buy to Strong Sell).
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Any
from datetime import datetime

from .config import (
    NEARING_THRESHOLD_PCT,
    LOOKBACK_52_WEEK, LOOKBACK_2_YEAR, LOOKBACK_5_YEAR,
    RANGE_BOTTOM_25_PCT, RANGE_TOP_25_PCT,
    RISE_MODERATE_PCT, RISE_MODERATELY_HIGH_PCT, RISE_HIGH_PCT, RISE_VERY_HIGH_PCT, RISE_2X_PCT,
    FALL_MODERATE_PCT, FALL_MODERATELY_HIGH_PCT, FALL_HIGH_PCT, FALL_VERY_HIGH_PCT,
    RS_PERIOD_SHORT, RS_PERIOD_MEDIUM, RS_PERIOD_LONG,
    RS_ZERO_LINE, RS_STRONG_ZONE, RS_WEAK_ZONE,
    RETURN_PERIODS,
    GAP_THRESHOLD_PCT,
    VWAP_NEARING_THRESHOLD,
    CONSECUTIVE_DAYS_2, CONSECUTIVE_DAYS_3
)
from .models import (
    PriceScanResult,
    SUBTYPE_PREV_DAY, SUBTYPE_WEEKLY_BREAKOUT, SUBTYPE_MONTHLY_BREAKOUT,
    SUBTYPE_52W_BREAKOUT, SUBTYPE_52W_RANGE,
    SUBTYPE_2Y_BREAKOUT, SUBTYPE_5Y_BREAKOUT, SUBTYPE_ATH_BREAKOUT,
    SUBTYPE_1D_BEHAVIOUR, SUBTYPE_2D_BEHAVIOUR, SUBTYPE_3D_BEHAVIOUR,
    SUBTYPE_REL_PERF, SUBTYPE_RS_21D, SUBTYPE_RS_55D, SUBTYPE_RS_21W, SUBTYPE_ADAPTIVE_RS,
    SUBTYPE_ABS_RETURN, SUBTYPE_VWAP
)

class PriceScanner:
    # Accurate Count: 117 Scans
    EXPECTED_SCAN_COUNT = 117
    IMPLEMENTED_SCAN_COUNT = 117 

    def __init__(
        self, 
        daily_df: pd.DataFrame,
        weekly_df: pd.DataFrame, 
        monthly_df: pd.DataFrame,
        benchmark_series: Optional[pd.Series] = None,
        sector_series: Optional[pd.Series] = None
    ):
        self.d = daily_df
        self.w = weekly_df
        self.m = monthly_df
        self.bench = benchmark_series
        self.sector = sector_series
        self.results: List[PriceScanResult] = []

    @classmethod
    def get_scan_coverage(cls) -> Dict[str, int]:
        """Returns scan coverage counts used by engine/UI."""
        return {
            "expected": int(cls.EXPECTED_SCAN_COUNT),
            "implemented": int(cls.IMPLEMENTED_SCAN_COUNT),
        }

    # --------------------------------------------------------------------------
    # Signal Logic
    # --------------------------------------------------------------------------
    @staticmethod
    def _map_status_to_action(status_text: str) -> str:
        """Map scan status text to a consistent 5-level action."""
        t = (status_text or "").strip().lower()
        
        # Explicit overrides for "Strong" signals based on magnitude/rarity
        if "very high" in t or "2x rise" in t or "strong zone" in t or "top 25%" in t:
            return "Strong Buy"
        if "very high fall" in t or "bottom 25%" in t:
            return "Strong Sell"
            
        # Standard Signals
        if "bullish" in t or "buy" in t or "positive" in t or "above" in t or "rising" in t or "outperforming" in t:
            return "Buy"
        if "bearish" in t or "sell" in t or "negative" in t or "below" in t or "falling" in t or "underperforming" in t:
            return "Sell"
            
        return "Neutral"

    def _calculate_category_signal(self, scans: List[Dict[str, Any]]) -> str:
        """Derive an aggregate signal for a category based on its component scans."""
        score = 0
        count = 0
        
        score_map = {
            "Strong Buy": 2,
            "Buy": 1,
            "Neutral": 0,
            "Sell": -1,
            "Strong Sell": -2
        }
        
        for s in scans:
            action = s.get("action", "Neutral")
            if action in score_map:
                score += score_map[action]
                count += 1
                
        if count == 0: return "Neutral"
        
        # Weighted average logic for signal determination
        # Since Price Scans trigger sparsely (only when conditions met), if ANY positive scan hits, it's significant.
        # We use a cumulative score threshold approach.
        
        if score >= 2: return "Strong Buy"
        if score >= 1: return "Buy"
        if score <= -2: return "Strong Sell"
        if score <= -1: return "Sell"
        
        return "Neutral"

    # --------------------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------------------
    def _val(self, df: pd.DataFrame, col: str, offset: int = 0) -> float:
        """Safe accessor for dataframe value with offset (0=Latest)."""
        if df.empty or len(df) <= offset: return np.nan
        return df[col].iloc[-(offset + 1)]

    def _is_near(self, price: float, target: float, threshold: float = NEARING_THRESHOLD_PCT) -> bool:
        if pd.isna(price) or pd.isna(target) or target == 0: return False
        return abs(price - target) / target * 100 <= threshold

    def _crossed_above(self, series: pd.Series, target: float) -> bool:
        if len(series) < 2: return False
        return series.iloc[-2] <= target and series.iloc[-1] > target

    def _crossed_below(self, series: pd.Series, target: float) -> bool:
        if len(series) < 2: return False
        return series.iloc[-2] >= target and series.iloc[-1] < target

    def _is_rising(self, series: pd.Series, window: int = 3) -> bool:
        if len(series) < window: return False
        return series.iloc[-1] > series.iloc[-window]

    def _is_falling(self, series: pd.Series, window: int = 3) -> bool:
        if len(series) < window: return False
        return series.iloc[-1] < series.iloc[-window]

    # --------------------------------------------------------------------------
    # Subtype 1: Previous Day Breakout
    # --------------------------------------------------------------------------
    def scan_prev_day_breakout(self):
        close = self._val(self.d, 'Close')
        prev_high = self._val(self.d, 'High', 1)
        prev_low = self._val(self.d, 'Low', 1)

        if not pd.isna(close) and not pd.isna(prev_high) and close > prev_high:
            self._add_res("Closing Above Previous High", SUBTYPE_PREV_DAY, "Bullish", True, close)
        
        if not pd.isna(close) and not pd.isna(prev_low) and close < prev_low:
            self._add_res("Closing Below Previous Low", SUBTYPE_PREV_DAY, "Bearish", True, close)

    # --------------------------------------------------------------------------
    # Subtype 2: Weekly Breakout
    # --------------------------------------------------------------------------
    def scan_weekly_breakout(self):
        close = self._val(self.d, 'Close')
        last_w_high = self._val(self.w, 'High', 1)
        last_w_low = self._val(self.w, 'Low', 1)
        curr_w_high = self._val(self.w, 'High', 0)
        curr_w_low = self._val(self.w, 'Low', 0)
        prev_close = self._val(self.d, 'Close', 1)
        
        if not pd.isna(last_w_high):
            if prev_close <= last_w_high < close:
                self._add_res("Close Crossing Last Week High", SUBTYPE_WEEKLY_BREAKOUT, "Bullish", True, close)
            elif close > last_w_high:
                self._add_res("Close Above Last Week High", SUBTYPE_WEEKLY_BREAKOUT, "Bullish", True, close)

        if not pd.isna(last_w_low):
            if prev_close >= last_w_low > close:
                self._add_res("Close Crossing Last Week Low", SUBTYPE_WEEKLY_BREAKOUT, "Bearish", True, close)
            elif close < last_w_low:
                self._add_res("Close Below Last Week Low", SUBTYPE_WEEKLY_BREAKOUT, "Bearish", True, close)
        
        if not pd.isna(curr_w_high) and close >= curr_w_high * 0.999:
             self._add_res("Close Crossing Current Week High", SUBTYPE_WEEKLY_BREAKOUT, "Bullish", True, close)
        
        if not pd.isna(curr_w_low) and close <= curr_w_low * 1.001:
             self._add_res("Close Crossing Current Week Low", SUBTYPE_WEEKLY_BREAKOUT, "Bearish", True, close)

    # --------------------------------------------------------------------------
    # Subtype 3: Monthly Breakout
    # --------------------------------------------------------------------------
    def scan_monthly_breakout(self):
        close = self._val(self.d, 'Close')
        prev_close = self._val(self.d, 'Close', 1)
        last_m_high = self._val(self.m, 'High', 1)
        last_m_low = self._val(self.m, 'Low', 1)
        last_m_close = self._val(self.m, 'Close', 1)
        curr_m_high = self._val(self.m, 'High', 0)
        curr_m_low = self._val(self.m, 'Low', 0)

        if not pd.isna(last_m_high):
            if prev_close <= last_m_high < close:
                self._add_res("Close Crossing Last Month High", SUBTYPE_MONTHLY_BREAKOUT, "Bullish", True, close)
            elif close > last_m_high:
                self._add_res("Close Above Last Month High", SUBTYPE_MONTHLY_BREAKOUT, "Bullish", True, close)

        if not pd.isna(last_m_low):
            if prev_close >= last_m_low > close:
                self._add_res("Close Crossing Last Month Low", SUBTYPE_MONTHLY_BREAKOUT, "Bearish", True, close)
            elif close < last_m_low:
                self._add_res("Close Below Last Month Low", SUBTYPE_MONTHLY_BREAKOUT, "Bearish", True, close)

        if not pd.isna(last_m_close):
             if prev_close <= last_m_close < close:
                 self._add_res("Close Crossing Last Month Close (From Below)", SUBTYPE_MONTHLY_BREAKOUT, "Bullish", True, close)
             elif prev_close >= last_m_close > close:
                 self._add_res("Close Crossing Last Month Close (From Above)", SUBTYPE_MONTHLY_BREAKOUT, "Bearish", True, close)

        if not pd.isna(curr_m_high) and close >= curr_m_high * 0.999:
            self._add_res("Close Crossing Current Month High", SUBTYPE_MONTHLY_BREAKOUT, "Bullish", True, close)
        if not pd.isna(curr_m_low) and close <= curr_m_low * 1.001:
            self._add_res("Close Crossing Current Month Low", SUBTYPE_MONTHLY_BREAKOUT, "Bearish", True, close)

    # --------------------------------------------------------------------------
    # Subtype 4, 6, 7, 8: Long Term Breakouts
    # --------------------------------------------------------------------------
    def _scan_rolling_breakout(self, lookback: int, subtype: str, label_prefix: str):
        if len(self.d) < lookback: return
        past_window = self.d.iloc[-(lookback+1):-1]
        if past_window.empty: return

        period_high = past_window['High'].max()
        period_low = past_window['Low'].min()
        close = self._val(self.d, 'Close')
        prev_close = self._val(self.d, 'Close', 1)

        if prev_close <= period_high < close:
            self._add_res(f"Close Crossing {label_prefix} High", subtype, "Bullish", True, close)
        elif close > period_high:
            self._add_res(f"Close Within {label_prefix} High Zone", subtype, "Bullish", True, close)
        
        if prev_close >= period_low > close:
            self._add_res(f"Close Crossing {label_prefix} Low", subtype, "Bearish", True, close)
        elif close < period_low:
            self._add_res(f"Close Within {label_prefix} Low Zone", subtype, "Bearish", True, close)

        if self._is_near(close, period_high):
            self._add_res(f"Close Near {label_prefix} High", subtype, "Bullish", True, close)
        if self._is_near(close, period_low):
            self._add_res(f"Close Near {label_prefix} Low", subtype, "Bearish", True, close)

    def scan_long_term_breakouts(self):
        # 6 scans * 4 timeframes = 24 scans
        self._scan_rolling_breakout(LOOKBACK_52_WEEK, SUBTYPE_52W_BREAKOUT, "52 Week")
        self._scan_rolling_breakout(LOOKBACK_2_YEAR, SUBTYPE_2Y_BREAKOUT, "2 Year")
        self._scan_rolling_breakout(LOOKBACK_5_YEAR, SUBTYPE_5Y_BREAKOUT, "5 Year")
        self._scan_rolling_breakout(len(self.d), SUBTYPE_ATH_BREAKOUT, "All Time")

    # --------------------------------------------------------------------------
    # Subtype 5: 52 Week Range
    # --------------------------------------------------------------------------
    def scan_52w_range(self):
        if len(self.d) < LOOKBACK_52_WEEK: return
        window = self.d.iloc[-LOOKBACK_52_WEEK:]
        high_52 = window['High'].max()
        low_52 = window['Low'].min()
        close = self._val(self.d, 'Close')
        if high_52 == low_52: return

        position = (close - low_52) / (high_52 - low_52)
        if position >= RANGE_TOP_25_PCT:
            self._add_res("Close in Top 25% of 52W Range", SUBTYPE_52W_RANGE, "Bullish", True, position*100)
        elif position <= RANGE_BOTTOM_25_PCT:
            self._add_res("Close in Bottom 25% of 52W Range", SUBTYPE_52W_RANGE, "Bearish", True, position*100)
        else:
            self._add_res("Close in Middle 50% of 52W Range", SUBTYPE_52W_RANGE, "Neutral", True, position*100)

        rise_pct = ((close - low_52) / low_52) * 100
        fall_pct = ((high_52 - close) / high_52) * 100

        if rise_pct >= RISE_2X_PCT: 
            self._add_res("2x Rise from 52 Week Low", SUBTYPE_52W_RANGE, "Bullish", True, rise_pct)
        elif rise_pct >= RISE_VERY_HIGH_PCT: 
            self._add_res("Very High Rise from 52 Week Low", SUBTYPE_52W_RANGE, "Bullish", True, rise_pct)
        elif rise_pct >= RISE_HIGH_PCT: 
            self._add_res("High Rise from 52 Week Low", SUBTYPE_52W_RANGE, "Bullish", True, rise_pct)
        elif rise_pct >= RISE_MODERATELY_HIGH_PCT:
            self._add_res("Moderately High Rise from 52 Week Low", SUBTYPE_52W_RANGE, "Bullish", True, rise_pct)
        elif rise_pct >= RISE_MODERATE_PCT:
            self._add_res("Moderate Rise from 52 Week Low", SUBTYPE_52W_RANGE, "Bullish", True, rise_pct)
        
        if fall_pct >= FALL_VERY_HIGH_PCT: 
            self._add_res("Very High Fall from 52 Week High", SUBTYPE_52W_RANGE, "Bearish", True, fall_pct)
        elif fall_pct >= FALL_HIGH_PCT: 
            self._add_res("High Fall from 52 Week High", SUBTYPE_52W_RANGE, "Bearish", True, fall_pct)
        elif fall_pct >= FALL_MODERATELY_HIGH_PCT:
            self._add_res("Moderately High Fall from 52 Week High", SUBTYPE_52W_RANGE, "Bearish", True, fall_pct)
        elif fall_pct >= FALL_MODERATE_PCT:
            self._add_res("Moderate Fall from 52 Week High", SUBTYPE_52W_RANGE, "Bearish", True, fall_pct)

    # --------------------------------------------------------------------------
    # Subtype 9, 10, 11: Behaviour
    # --------------------------------------------------------------------------
    def scan_behaviour(self):
        open_p = self._val(self.d, 'Open')
        prev_high = self._val(self.d, 'High', 1)
        prev_low = self._val(self.d, 'Low', 1)
        
        if not pd.isna(open_p) and not pd.isna(prev_high):
            gap_up = ((open_p - prev_high) / prev_high) * 100
            if gap_up >= GAP_THRESHOLD_PCT:
                self._add_res("Large Gap Up", SUBTYPE_1D_BEHAVIOUR, "Bullish", True, gap_up)
                
        if not pd.isna(open_p) and not pd.isna(prev_low):
            gap_down = ((prev_low - open_p) / prev_low) * 100
            if gap_down >= GAP_THRESHOLD_PCT:
                self._add_res("Large Gap Down", SUBTYPE_1D_BEHAVIOUR, "Bearish", True, gap_down)

        closes = self.d['Close'].iloc[-4:].values
        if len(closes) < 4: return
        highs = self.d['High'].iloc[-4:].values
        lows = self.d['Low'].iloc[-4:].values
        
        if highs[-1] > highs[-2] > highs[-3]:
            self._add_res("Making Higher Highs for 2 Days", SUBTYPE_2D_BEHAVIOUR, "Bullish", True)
            if len(highs) >= 4 and highs[-3] > highs[-4]:
                self._add_res("Making Higher Highs for 3 Days", SUBTYPE_3D_BEHAVIOUR, "Bullish", True)

        if lows[-1] < lows[-2] < lows[-3]:
            self._add_res("Making Lower Lows for 2 Days", SUBTYPE_2D_BEHAVIOUR, "Bearish", True)
            if len(lows) >= 4 and lows[-3] < lows[-4]:
                self._add_res("Making Lower Lows for 3 Days", SUBTYPE_3D_BEHAVIOUR, "Bearish", True)

    # --------------------------------------------------------------------------
    # Subtype 18: VWAP
    # --------------------------------------------------------------------------
    def scan_vwap(self):
        high = self._val(self.d, 'High')
        low = self._val(self.d, 'Low')
        close = self._val(self.d, 'Close')
        open_p = self._val(self.d, 'Open')
        vwap_proxy = (high + low + close) / 3
        
        if open_p < vwap_proxy < close:
            self._add_res("Close Crossing Daily VWAP (From Below)", SUBTYPE_VWAP, "Bullish", True, vwap_proxy)
        elif open_p > vwap_proxy > close:
            self._add_res("Close Crossing Daily VWAP (From Above)", SUBTYPE_VWAP, "Bearish", True, vwap_proxy)
            
        if close > vwap_proxy:
            self._add_res("Close Above Daily VWAP", SUBTYPE_VWAP, "Bullish", True, vwap_proxy)
        else:
            self._add_res("Close Below Daily VWAP", SUBTYPE_VWAP, "Bearish", True, vwap_proxy)

        if self._is_near(close, vwap_proxy, threshold=0.5):
            if close > vwap_proxy:
                self._add_res("Close Near Daily VWAP (Support)", SUBTYPE_VWAP, "Bullish", True, vwap_proxy)
            else:
                self._add_res("Close Near Daily VWAP (Resistance)", SUBTYPE_VWAP, "Bearish", True, vwap_proxy)

    # --------------------------------------------------------------------------
    # Subtype 12-17: Relative Strength & Returns
    # --------------------------------------------------------------------------
    def _calculate_rs_series(self, stock: pd.Series, benchmark: pd.Series, period: int) -> pd.Series:
        aligned_stock, aligned_bench = stock.align(benchmark, join='inner')
        if aligned_stock.empty: return pd.Series(dtype=float)
        rs_ratio = aligned_stock / aligned_bench
        rs_score = rs_ratio.pct_change(period) * 100
        return rs_score

    def scan_relative_performance(self):
        # 1. Absolute Returns
        for label, period in RETURN_PERIODS.items():
            if len(self.d) > period:
                ret = self.d['Close'].pct_change(period).iloc[-1] * 100
                if not pd.isna(ret):
                    if ret > 0:
                        self._add_res(f"{label} Return (Positive)", SUBTYPE_ABS_RETURN, "Bullish", True, ret)
                    else:
                        self._add_res(f"{label} Return (Negative)", SUBTYPE_ABS_RETURN, "Bearish", True, ret)
        if len(self.d) > 500:
            ret_2y = self.d['Close'].pct_change(500).iloc[-1] * 100
            if ret_2y > 0:
                self._add_res("2Y Return (Positive)", SUBTYPE_ABS_RETURN, "Bullish", True, ret_2y)
            else:
                self._add_res("2Y Return (Negative)", SUBTYPE_ABS_RETURN, "Bearish", True, ret_2y)

        if self.bench is None or self.bench.empty: return

        # 2. RS 21 Days
        rs_21 = self._calculate_rs_series(self.d['Close'], self.bench, RS_PERIOD_SHORT)
        if not rs_21.empty:
            curr = rs_21.iloc[-1]
            if self._crossed_above(rs_21, RS_ZERO_LINE):
                self._add_res("RS (21D) Crossing 0 From Below", SUBTYPE_RS_21D, "Bullish", True, curr)
            if self._crossed_below(rs_21, RS_ZERO_LINE):
                self._add_res("RS (21D) Crossing 0 From Above", SUBTYPE_RS_21D, "Bearish", True, curr)
            if curr > 0:
                self._add_res("RS (21D) Positive", SUBTYPE_RS_21D, "Bullish", True, curr)
            else:
                self._add_res("RS (21D) Negative", SUBTYPE_RS_21D, "Bearish", True, curr)
            if self._is_rising(rs_21):
                self._add_res("RS (21D) Trending Up", SUBTYPE_RS_21D, "Bullish", True, curr)
            if self._is_falling(rs_21):
                self._add_res("RS (21D) Trending Down", SUBTYPE_RS_21D, "Bearish", True, curr)

        # 3. RS 55 Days
        rs_55 = self._calculate_rs_series(self.d['Close'], self.bench, RS_PERIOD_MEDIUM)
        if not rs_55.empty:
            curr = rs_55.iloc[-1]
            if self._crossed_above(rs_55, RS_ZERO_LINE):
                self._add_res("RS (55D) Crossing 0 From Below", SUBTYPE_RS_55D, "Bullish", True, curr)
            if self._crossed_below(rs_55, RS_ZERO_LINE):
                self._add_res("RS (55D) Crossing 0 From Above", SUBTYPE_RS_55D, "Bearish", True, curr)
            if curr > 0: self._add_res("RS (55D) Positive", SUBTYPE_RS_55D, "Bullish", True, curr)
            else: self._add_res("RS (55D) Negative", SUBTYPE_RS_55D, "Bearish", True, curr)
            if self._is_rising(rs_55): self._add_res("RS (55D) Trending Up", SUBTYPE_RS_55D, "Bullish", True, curr)
            if self._is_falling(rs_55): self._add_res("RS (55D) Trending Down", SUBTYPE_RS_55D, "Bearish", True, curr)
            if curr > RS_STRONG_ZONE: self._add_res("RS (55D) in Strong Zone", SUBTYPE_RS_55D, "Bullish", True, curr)
            if curr < RS_WEAK_ZONE: self._add_res("RS (55D) in Weak Zone", SUBTYPE_RS_55D, "Bearish", True, curr)
            if self._crossed_above(rs_55, RS_STRONG_ZONE): self._add_res("RS (55D) Entering Strong Zone", SUBTYPE_RS_55D, "Bullish", True, curr)
            if self._crossed_below(rs_55, RS_WEAK_ZONE): self._add_res("RS (55D) Entering Weak Zone", SUBTYPE_RS_55D, "Bearish", True, curr)
            if self._crossed_below(rs_55, RS_STRONG_ZONE): self._add_res("RS (55D) Exiting Strong Zone", SUBTYPE_RS_55D, "Bearish", True, curr)
            if self._crossed_above(rs_55, RS_WEAK_ZONE): self._add_res("RS (55D) Exiting Weak Zone", SUBTYPE_RS_55D, "Bullish", True, curr)

        # 4. RS 21 Weeks
        bench_w = self.bench.resample('W-FRI').last()
        rs_21w = self._calculate_rs_series(self.w['Close'], bench_w, 21)
        if not rs_21w.empty:
            curr = rs_21w.iloc[-1]
            if self._crossed_above(rs_21w, 0): self._add_res("RS (21W) Crossing 0 From Below", SUBTYPE_RS_21W, "Bullish", True, curr)
            if self._crossed_below(rs_21w, 0): self._add_res("RS (21W) Crossing 0 From Above", SUBTYPE_RS_21W, "Bearish", True, curr)
            if curr > 0: self._add_res("RS (21W) Positive", SUBTYPE_RS_21W, "Bullish", True, curr)
            else: self._add_res("RS (21W) Negative", SUBTYPE_RS_21W, "Bearish", True, curr)
            if self._is_rising(rs_21w): self._add_res("RS (21W) Trending Up", SUBTYPE_RS_21W, "Bullish", True, curr)
            if self._is_falling(rs_21w): self._add_res("RS (21W) Trending Down", SUBTYPE_RS_21W, "Bearish", True, curr)

        # 5. Adaptive RS
        rs_long = self._calculate_rs_series(self.d['Close'], self.bench, RS_PERIOD_LONG)
        if not rs_21.empty and not rs_long.empty:
            s_short, s_long = rs_21.align(rs_long, join='inner')
            if len(s_short) > 3:
                if self._crossed_above(s_short, s_long.iloc[-1]): self._add_res("Adaptive RS Crossed Above Static RS", SUBTYPE_ADAPTIVE_RS, "Bullish", True)
                if self._crossed_below(s_short, s_long.iloc[-1]): self._add_res("Adaptive RS Crossed Below Static RS", SUBTYPE_ADAPTIVE_RS, "Bearish", True)
                if s_short.iloc[-1] > s_long.iloc[-1]: self._add_res("Adaptive RS > Static RS", SUBTYPE_ADAPTIVE_RS, "Bullish", True)
                else: self._add_res("Adaptive RS < Static RS", SUBTYPE_ADAPTIVE_RS, "Bearish", True)
                if self._is_rising(s_short): self._add_res("Adaptive RS Trending Up", SUBTYPE_ADAPTIVE_RS, "Bullish", True)
                if self._is_falling(s_short): self._add_res("Adaptive RS Trending Down", SUBTYPE_ADAPTIVE_RS, "Bearish", True)
                if self._is_rising(s_long): self._add_res("Static RS Trending Up", SUBTYPE_ADAPTIVE_RS, "Bullish", True)
                if self._is_falling(s_long): self._add_res("Static RS Trending Down", SUBTYPE_ADAPTIVE_RS, "Bearish", True)

        # 6. Relative Performance (Sector)
        if self.sector is not None and not self.sector.empty:
            rs_sec = self._calculate_rs_series(self.d['Close'], self.sector, RS_PERIOD_SHORT)
            if not rs_sec.empty:
                curr_sec = rs_sec.iloc[-1]
                if curr_sec > 0: self._add_res("Outperforming Sector (21D)", SUBTYPE_REL_PERF, "Bullish", True, curr_sec)
                else: self._add_res("Underperforming Sector (21D)", SUBTYPE_REL_PERF, "Bearish", True, curr_sec)
                
                if self._crossed_above(rs_sec, 0): self._add_res("Started Outperforming Sector", SUBTYPE_REL_PERF, "Bullish", True, curr_sec)
                if self._crossed_below(rs_sec, 0): self._add_res("Started Underperforming Sector", SUBTYPE_REL_PERF, "Bearish", True, curr_sec)


    # --------------------------------------------------------------------------
    # Main Execute
    # --------------------------------------------------------------------------
    def _add_res(self, label: str, subtype: str, status: str, cond: bool, val: Optional[float] = None):
        action = self._map_status_to_action(status)
        self.results.append(PriceScanResult(label, subtype, status, cond, val))

    def run_all_scans(self) -> Dict[str, Dict[str, Any]]:
        self.results = []
        self.scan_prev_day_breakout()
        self.scan_weekly_breakout()
        self.scan_monthly_breakout()
        self.scan_long_term_breakouts()
        self.scan_52w_range()
        self.scan_behaviour()
        self.scan_vwap()
        self.scan_relative_performance()
        
        # New Post-Processing: Group by Category
        grouped_scans = {}
        for res in self.results:
            d = res.to_dict()
            d["action"] = self._map_status_to_action(d.get("status", ""))
            grouped_scans.setdefault(res.subtype, []).append(d)
            
        # Ensure all categories are present even if empty (optional, but good for UI consistency)
        all_subtypes = [
            SUBTYPE_PREV_DAY, SUBTYPE_WEEKLY_BREAKOUT, SUBTYPE_MONTHLY_BREAKOUT,
            SUBTYPE_52W_BREAKOUT, SUBTYPE_52W_RANGE,
            SUBTYPE_2Y_BREAKOUT, SUBTYPE_5Y_BREAKOUT, SUBTYPE_ATH_BREAKOUT,
            SUBTYPE_1D_BEHAVIOUR, SUBTYPE_2D_BEHAVIOUR, SUBTYPE_3D_BEHAVIOUR,
            SUBTYPE_REL_PERF, SUBTYPE_RS_21D, SUBTYPE_RS_55D, SUBTYPE_RS_21W, SUBTYPE_ADAPTIVE_RS,
            SUBTYPE_ABS_RETURN, SUBTYPE_VWAP
        ]
        
        final_results = {}
        for subtype in all_subtypes:
            scans = grouped_scans.get(subtype, [])
            signal = self._calculate_category_signal(scans)
            final_results[subtype] = {
                "signal": signal,
                "scans": scans
            }
            
        return final_results