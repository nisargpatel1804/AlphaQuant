"""
Core Logic Module for 214 Technical Scans.
Evaluates boolean conditions on pre-calculated indicators.
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Tuple

from .config import (
    NEARING_THRESHOLD_PCT,
    MOMENTUM_BULLISH_THRESHOLD, MOMENTUM_BEARISH_THRESHOLD,
    MOMENTUM_NEUTRAL_LOW, MOMENTUM_NEUTRAL_HIGH,
    RSI_OVERBOUGHT, RSI_OVERSOLD, RSI_BULLISH_ZONE,
    CCI_OVERBOUGHT, CCI_OVERSOLD, CCI_ZERO,
    STOCH_OVERBOUGHT, STOCH_OVERSOLD,
    WILLR_OVERBOUGHT, WILLR_OVERSOLD, WILLR_MIDPOINT,
    MFI_OVERBOUGHT, MFI_OVERSOLD, MFI_MIDPOINT,
    ADX_STRONG_TREND, ADX_NO_TREND, ADX_WEAK_TREND, ADX_VERY_STRONG_TREND,
    BB_SQUEEZE_PERCENTILE, BB_EXPANSION_PERCENTILE,
    BETA_HIGH_THRESHOLD, BETA_LOW_THRESHOLD, BETA_NEUTRAL
)

class TechnicalScans:
    def __init__(self, daily_df: pd.DataFrame, weekly_df: pd.DataFrame):
        self.df = daily_df
        self.w_df = weekly_df
        # pass/fail contain only scans that could be evaluated.
        # skip contains scans that were not computable due to missing columns,
        # insufficient history, or NaN values in required inputs.
        self.results: Dict[str, List[Dict[str, Any]]] = {"pass": [], "fail": [], "skip": []}

    # --------------------------------------------------------------------------
    # Helper Methods
    # --------------------------------------------------------------------------
    def _get_val(self, series: pd.Series, offset: int = 0) -> float:
        """Safely get value from series with offset from end (0 = latest)."""
        if len(series) < offset + 1:
            return np.nan
        return series.iloc[-(offset + 1)]

    def _is_missing(self, value: Any) -> bool:
        if value is None:
            return True
        try:
            return bool(pd.isna(value))
        except Exception:
            return False

    def _gt(self, a: Any, b: Any):
        if self._is_missing(a) or self._is_missing(b):
            return None
        return a > b

    def _lt(self, a: Any, b: Any):
        if self._is_missing(a) or self._is_missing(b):
            return None
        return a < b

    def _skip_many(self, names: List[str], category: str, reason: str = "missing_data") -> None:
        for name in names:
            self._add_result(name, category, None, reason=reason)

    def _crossed_above(self, series_a: pd.Series, series_b: Any):
        """Checks if A crossed above B in the latest candle."""
        if len(series_a) < 2:
            return None
        
        # Handle scalar comparison (e.g., RSI crossing 70)
        if isinstance(series_b, (int, float)):
            prev_b, curr_b = series_b, series_b
        else:
            if len(series_b) < 2:
                return None
            prev_b, curr_b = series_b.iloc[-2], series_b.iloc[-1]

        prev_a, curr_a = series_a.iloc[-2], series_a.iloc[-1]
        
        # Check for NaN
        if pd.isna(prev_a) or pd.isna(curr_a) or pd.isna(prev_b) or pd.isna(curr_b):
            return None

        return prev_a <= prev_b and curr_a > curr_b

    def _crossed_below(self, series_a: pd.Series, series_b: Any):
        """Checks if A crossed below B in the latest candle."""
        if len(series_a) < 2:
            return None
        
        if isinstance(series_b, (int, float)):
            prev_b, curr_b = series_b, series_b
        else:
            if len(series_b) < 2:
                return None
            prev_b, curr_b = series_b.iloc[-2], series_b.iloc[-1]

        prev_a, curr_a = series_a.iloc[-2], series_a.iloc[-1]
        
        if pd.isna(prev_a) or pd.isna(curr_a) or pd.isna(prev_b) or pd.isna(curr_b):
            return None

        return prev_a >= prev_b and curr_a < curr_b

    def _is_nearing(self, price: float, target: float, threshold_pct: float = NEARING_THRESHOLD_PCT):
        """Checks if price is within X% of target."""
        if pd.isna(price) or pd.isna(target) or target == 0:
            return None
        diff_pct = abs(price - target) / abs(target) * 100
        return diff_pct <= threshold_pct

    def _is_rising(self, series: pd.Series, period: int = 1):
        """Checks if series has been rising for 'period' steps."""
        if len(series) < period + 1:
            return None
        subset = series.iloc[-(period + 1):]
        if subset.isna().any():
            return None
        return all(subset.iloc[i] < subset.iloc[i+1] for i in range(period))

    def _is_falling(self, series: pd.Series, period: int = 1):
        """Checks if series has been falling for 'period' steps."""
        if len(series) < period + 1:
            return None
        subset = series.iloc[-(period + 1):]
        if subset.isna().any():
            return None
        return all(subset.iloc[i] > subset.iloc[i+1] for i in range(period))

    def _add_result(self, name: str, category: str, result: Any, value: Any = None, reason: str | None = None):
        entry = {"name": name, "category": category, "label": name}
        if value is not None and not self._is_missing(value):
            entry["value"] = value
        if reason:
            entry["reason"] = reason
            
        if result is None:
            self.results["skip"].append(entry)
        elif result:
            self.results["pass"].append(entry)
        else:
            self.results["fail"].append(entry)

    # --------------------------------------------------------------------------
    # 1. Momentum Score Scans (20 Scans)
    # --------------------------------------------------------------------------
    def run_momentum_scans(self):
        cat = "Momentum Score"
        # We simulate Momentum Score using ROC (Rate of Change)
        # 1M = 21 days, 3M = 63 days, 6M = 126 days
        # If columns don't exist, calculate on fly
        close = self.df['Close']
        
        for period_label, period_days in [("1M", 21), ("3M", 63), ("6M", 126)]:
            if len(close) <= period_days + 1:
                self._skip_many(
                    [
                        f"Momentum Score ({period_label}) Entering Bullish Zone",
                        f"Momentum Score ({period_label}) Entering Bearish Zone",
                        f"Momentum Score ({period_label}) Entering Neutral Zone From Bearish",
                        f"Momentum Score ({period_label}) Entering Neutral Zone From Bullish",
                        f"Increasing Momentum Score ({period_label})",
                        f"Decreasing Momentum Score ({period_label})",
                    ],
                    cat,
                    reason="insufficient_history",
                )
                continue
                
            roc = close.pct_change(period_days) * 100
            curr_score = roc.iloc[-1]
            prev_score = roc.iloc[-2]
            if pd.isna(curr_score) or pd.isna(prev_score):
                self._skip_many(
                    [
                        f"Momentum Score ({period_label}) Entering Bullish Zone",
                        f"Momentum Score ({period_label}) Entering Bearish Zone",
                        f"Momentum Score ({period_label}) Entering Neutral Zone From Bearish",
                        f"Momentum Score ({period_label}) Entering Neutral Zone From Bullish",
                        f"Increasing Momentum Score ({period_label})",
                        f"Decreasing Momentum Score ({period_label})",
                    ],
                    cat,
                    reason="missing_value",
                )
                continue
            
            # Zoning Logic
            # Bullish > 5, Bearish < -5, Neutral -2 to 2 (config dependent)
            
            # Zones
            is_bullish = curr_score > MOMENTUM_BULLISH_THRESHOLD
            is_bearish = curr_score < MOMENTUM_BEARISH_THRESHOLD
            is_neutral = MOMENTUM_NEUTRAL_LOW <= curr_score <= MOMENTUM_NEUTRAL_HIGH
            
            prev_is_bearish = prev_score < MOMENTUM_BEARISH_THRESHOLD
            prev_is_bullish = prev_score > MOMENTUM_BULLISH_THRESHOLD
            prev_is_neutral = MOMENTUM_NEUTRAL_LOW <= prev_score <= MOMENTUM_NEUTRAL_HIGH

            # Scans
            self._add_result(f"Momentum Score ({period_label}) Entering Bullish Zone", cat, is_bullish and not prev_is_bullish, curr_score)
            self._add_result(f"Momentum Score ({period_label}) Entering Bearish Zone", cat, is_bearish and not prev_is_bearish, curr_score)
            self._add_result(f"Momentum Score ({period_label}) Entering Neutral Zone From Bearish", cat, is_neutral and prev_is_bearish, curr_score)
            self._add_result(f"Momentum Score ({period_label}) Entering Neutral Zone From Bullish", cat, is_neutral and prev_is_bullish, curr_score)
            self._add_result(f"Increasing Momentum Score ({period_label})", cat, curr_score > prev_score, curr_score)
            self._add_result(f"Decreasing Momentum Score ({period_label})", cat, curr_score < prev_score, curr_score)

        # Composite (1M 3M 6M)
        try:
            roc_1m = close.pct_change(21).iloc[-1] * 100
            roc_3m = close.pct_change(63).iloc[-1] * 100
            roc_6m = close.pct_change(126).iloc[-1] * 100

            if pd.isna(roc_1m) or pd.isna(roc_3m) or pd.isna(roc_6m):
                self._skip_many(
                    [
                        "Momentum Score (1M 3M 6M) in Bullish Zone",
                        "Momentum Score (1M 3M 6M) in Bearish Zone",
                    ],
                    cat,
                    reason="missing_value",
                )
                return
            
            all_bullish = (roc_1m > MOMENTUM_BULLISH_THRESHOLD and 
                           roc_3m > MOMENTUM_BULLISH_THRESHOLD and 
                           roc_6m > MOMENTUM_BULLISH_THRESHOLD)
                           
            all_bearish = (roc_1m < MOMENTUM_BEARISH_THRESHOLD and 
                           roc_3m < MOMENTUM_BEARISH_THRESHOLD and 
                           roc_6m < MOMENTUM_BEARISH_THRESHOLD)
                           
            self._add_result("Momentum Score (1M 3M 6M) in Bullish Zone", cat, all_bullish)
            self._add_result("Momentum Score (1M 3M 6M) in Bearish Zone", cat, all_bearish)
        except Exception:
            self._skip_many(
                [
                    "Momentum Score (1M 3M 6M) in Bullish Zone",
                    "Momentum Score (1M 3M 6M) in Bearish Zone",
                ],
                cat,
                reason="missing_data",
            )

    # --------------------------------------------------------------------------
    # 2. Simple Moving Averages Scans (26 Scans)
    # --------------------------------------------------------------------------
    def run_sma_scans(self):
        cat = "Simple Moving Averages"
        close = self.df['Close']
        curr_close = close.iloc[-1]
        
        # Close Near SMA / Crossing SMA
        for p in [20, 50, 100, 200]:
            col = f'SMA_{p}'
            if col not in self.df.columns:
                self._skip_many(
                    [
                        f"Closing Near {p} SMA",
                        f"Close Crossing {p} SMA From Below",
                        f"Close Crossing {p} SMA From Above",
                    ],
                    cat,
                    reason="missing_indicator",
                )
                continue
            
            sma_val = self.df[col].iloc[-1]
            sma_series = self.df[col]

            self._add_result(f"Closing Near {p} SMA", cat, self._is_nearing(curr_close, sma_val), sma_val)
            self._add_result(f"Close Crossing {p} SMA From Below", cat, self._crossed_above(close, sma_series), sma_val)
            self._add_result(f"Close Crossing {p} SMA From Above", cat, self._crossed_below(close, sma_series), sma_val)

        # SMA Crossovers
        pairs = [(5, 20), (20, 50), (20, 100), (20, 200), (50, 100), (50, 200), (100, 200)]
        for fast, slow in pairs:
            f_col, s_col = f'SMA_{fast}', f'SMA_{slow}'
            if f_col in self.df.columns and s_col in self.df.columns:
                fast_s = self.df[f_col]
                slow_s = self.df[s_col]
                self._add_result(f"{fast} SMA Crossing {slow} SMA From Below", cat, self._crossed_above(fast_s, slow_s))
                self._add_result(f"{fast} SMA Crossing {slow} SMA From Above", cat, self._crossed_below(fast_s, slow_s))
            else:
                self._skip_many(
                    [
                        f"{fast} SMA Crossing {slow} SMA From Below",
                        f"{fast} SMA Crossing {slow} SMA From Above",
                    ],
                    cat,
                    reason="missing_indicator",
                )

    # --------------------------------------------------------------------------
    # 3. Weekly Simple Moving Averages (12 Scans)
    # --------------------------------------------------------------------------
    def run_weekly_sma_scans(self):
        cat = "Weekly Simple Moving Averages"
        if self.w_df.empty:
            self._skip_many(
                [
                    "Close Near 5 Week SMA",
                    "Close Crossing 5 Week SMA From Below",
                    "Close Crossing 5 Week SMA From Above",
                    "Close Near 10 Week SMA",
                    "Close Crossing 10 Week SMA From Below",
                    "Close Crossing 10 Week SMA From Above",
                    "Close Near 20 Week SMA",
                    "Close Crossing 20 Week SMA From Below",
                    "Close Crossing 20 Week SMA From Above",
                    "Close Near 50 Week SMA",
                    "Close Crossing 50 Week SMA From Below",
                    "Close Crossing 50 Week SMA From Above",
                ],
                cat,
                reason="missing_weekly_data",
            )
            return
        
        close = self.w_df['Close']
        curr_close = close.iloc[-1]
        
        for p in [5, 10, 20, 50]:
            col = f'SMA_{p}'
            if col not in self.w_df.columns:
                self._skip_many(
                    [
                        f"Close Near {p} Week SMA",
                        f"Close Crossing {p} Week SMA From Below",
                        f"Close Crossing {p} Week SMA From Above",
                    ],
                    cat,
                    reason="missing_indicator",
                )
                continue
            
            sma_val = self.w_df[col].iloc[-1]
            sma_series = self.w_df[col]
            
            self._add_result(f"Close Near {p} Week SMA", cat, self._is_nearing(curr_close, sma_val), sma_val)
            self._add_result(f"Close Crossing {p} Week SMA From Below", cat, self._crossed_above(close, sma_series))
            self._add_result(f"Close Crossing {p} Week SMA From Above", cat, self._crossed_below(close, sma_series))

    # --------------------------------------------------------------------------
    # 4. Exponential Moving Averages (26 Scans)
    # --------------------------------------------------------------------------
    def run_ema_scans(self):
        cat = "Exponential Moving Averages"
        close = self.df['Close']
        curr_close = close.iloc[-1]
        
        for p in [20, 50, 100, 200]:
            col = f'EMA_{p}'
            if col not in self.df.columns:
                self._skip_many(
                    [
                        f"Closing Near {p} EMA",
                        f"Close Crossing {p} EMA From Below",
                        f"Close Crossing {p} EMA From Above",
                    ],
                    cat,
                    reason="missing_indicator",
                )
                continue
            
            ema_val = self.df[col].iloc[-1]
            ema_series = self.df[col]
            
            self._add_result(f"Closing Near {p} EMA", cat, self._is_nearing(curr_close, ema_val), ema_val)
            self._add_result(f"Close Crossing {p} EMA From Below", cat, self._crossed_above(close, ema_series))
            self._add_result(f"Close Crossing {p} EMA From Above", cat, self._crossed_below(close, ema_series))

        pairs = [(5, 20), (20, 50), (20, 100), (20, 200), (50, 100), (50, 200), (100, 200)]
        for fast, slow in pairs:
            f_col, s_col = f'EMA_{fast}', f'EMA_{slow}'
            if f_col in self.df.columns and s_col in self.df.columns:
                fast_s = self.df[f_col]
                slow_s = self.df[s_col]
                self._add_result(f"{fast} EMA Crossing {slow} EMA From Below", cat, self._crossed_above(fast_s, slow_s))
                self._add_result(f"{fast} EMA Crossing {slow} EMA From Above", cat, self._crossed_below(fast_s, slow_s))
            else:
                self._skip_many(
                    [
                        f"{fast} EMA Crossing {slow} EMA From Below",
                        f"{fast} EMA Crossing {slow} EMA From Above",
                    ],
                    cat,
                    reason="missing_indicator",
                )

    # --------------------------------------------------------------------------
    # 5. Weekly Exponential Moving Averages (12 Scans)
    # --------------------------------------------------------------------------
    def run_weekly_ema_scans(self):
        cat = "Weekly Exponential Moving Averages"
        if self.w_df.empty:
            self._skip_many(
                [
                    "Close Near 5 Week EMA",
                    "Close Crossing 5 Week EMA From Below",
                    "Close Crossing 5 Week EMA From Above",
                    "Close Near 10 Week EMA",
                    "Close Crossing 10 Week EMA From Below",
                    "Close Crossing 10 Week EMA From Above",
                    "Close Near 20 Week EMA",
                    "Close Crossing 20 Week EMA From Below",
                    "Close Crossing 20 Week EMA From Above",
                    "Close Near 50 Week EMA",
                    "Close Crossing 50 Week EMA From Below",
                    "Close Crossing 50 Week EMA From Above",
                ],
                cat,
                reason="missing_weekly_data",
            )
            return
        close = self.w_df['Close']
        curr_close = close.iloc[-1]
        
        for p in [5, 10, 20, 50]:
            col = f'EMA_{p}'
            if col not in self.w_df.columns:
                self._skip_many(
                    [
                        f"Close Near {p} Week EMA",
                        f"Close Crossing {p} Week EMA From Below",
                        f"Close Crossing {p} Week EMA From Above",
                    ],
                    cat,
                    reason="missing_indicator",
                )
                continue
            
            ema_val = self.w_df[col].iloc[-1]
            ema_series = self.w_df[col]
            
            self._add_result(f"Close Near {p} Week EMA", cat, self._is_nearing(curr_close, ema_val), ema_val)
            self._add_result(f"Close Crossing {p} Week EMA From Below", cat, self._crossed_above(close, ema_series))
            self._add_result(f"Close Crossing {p} Week EMA From Above", cat, self._crossed_below(close, ema_series))

    # --------------------------------------------------------------------------
    # 6. Commodity Channel Index Scans (8 Scans)
    # --------------------------------------------------------------------------
    def run_cci_scans(self):
        cat = "Commodity Channel Index"
        if 'CCI' not in self.df.columns:
            self._skip_many(
                [
                    "CCI Bullish",
                    "CCI Trending Up",
                    "CCI Crossed Above 100",
                    "CCI Bearish",
                    "CCI Trending Down",
                    "CCI Crossed Below -100",
                    "CCI Overbought Zone",
                    "CCI Oversold Zone",
                ],
                cat,
                reason="missing_indicator",
            )
            return
        cci = self.df['CCI']
        curr_cci = cci.iloc[-1]
        
        self._add_result("CCI Bullish", cat, self._gt(curr_cci, CCI_ZERO), curr_cci)
        self._add_result("CCI Trending Up", cat, self._is_rising(cci), curr_cci)
        self._add_result("CCI Crossed Above 100", cat, self._crossed_above(cci, CCI_OVERBOUGHT), curr_cci)
        self._add_result("CCI Bearish", cat, self._lt(curr_cci, CCI_ZERO), curr_cci)
        self._add_result("CCI Trending Down", cat, self._is_falling(cci), curr_cci)
        self._add_result("CCI Crossed Below -100", cat, self._crossed_below(cci, CCI_OVERSOLD), curr_cci)
        self._add_result("CCI Overbought Zone", cat, self._gt(curr_cci, CCI_OVERBOUGHT), curr_cci)
        self._add_result("CCI Oversold Zone", cat, self._lt(curr_cci, CCI_OVERSOLD), curr_cci)

    # --------------------------------------------------------------------------
    # 7. Relative Strength Index Scans (8 Scans)
    # --------------------------------------------------------------------------
    def run_rsi_scans(self):
        cat = "Relative Strength Index"
        if 'RSI' not in self.df.columns:
            self._skip_many(
                [
                    "RSI Bullish",
                    "RSI Trending Up",
                    "RSI Crossed Above 70",
                    "RSI Bearish",
                    "RSI Trending Down",
                    "RSI Crossed Below 30",
                    "RSI Overbought Zone",
                    "RSI Oversold Zone",
                ],
                cat,
                reason="missing_indicator",
            )
            return
        rsi = self.df['RSI']
        curr_rsi = rsi.iloc[-1]
        
        self._add_result("RSI Bullish", cat, self._gt(curr_rsi, RSI_BULLISH_ZONE), curr_rsi)
        self._add_result("RSI Trending Up", cat, self._is_rising(rsi), curr_rsi)
        self._add_result("RSI Crossed Above 70", cat, self._crossed_above(rsi, RSI_OVERBOUGHT), curr_rsi)
        self._add_result("RSI Bearish", cat, self._lt(curr_rsi, RSI_BULLISH_ZONE), curr_rsi)
        self._add_result("RSI Trending Down", cat, self._is_falling(rsi), curr_rsi)
        self._add_result("RSI Crossed Below 30", cat, self._crossed_below(rsi, RSI_OVERSOLD), curr_rsi)
        self._add_result("RSI Overbought Zone", cat, self._gt(curr_rsi, RSI_OVERBOUGHT), curr_rsi)
        self._add_result("RSI Oversold Zone", cat, self._lt(curr_rsi, RSI_OVERSOLD), curr_rsi)

    # --------------------------------------------------------------------------
    # 8. Weekly Relative Strength Index Scans (8 Scans)
    # --------------------------------------------------------------------------
    def run_weekly_rsi_scans(self):
        cat = "Weekly Relative Strength Index"
        if 'RSI' not in self.w_df.columns:
            self._skip_many(
                [
                    "Weekly RSI Bullish",
                    "Weekly RSI Trending Up",
                    "Weekly RSI Crossed Above 70",
                    "Weekly RSI Bearish",
                    "Weekly RSI Trending Down",
                    "Weekly RSI Crossed Below 30",
                    "Weekly RSI Overbought Zone",
                    "Weekly RSI Oversold Zone",
                ],
                cat,
                reason="missing_indicator",
            )
            return
        rsi = self.w_df['RSI']
        curr_rsi = rsi.iloc[-1]
        
        self._add_result("Weekly RSI Bullish", cat, self._gt(curr_rsi, RSI_BULLISH_ZONE), curr_rsi)
        self._add_result("Weekly RSI Trending Up", cat, self._is_rising(rsi), curr_rsi)
        self._add_result("Weekly RSI Crossed Above 70", cat, self._crossed_above(rsi, RSI_OVERBOUGHT), curr_rsi)
        self._add_result("Weekly RSI Bearish", cat, self._lt(curr_rsi, RSI_BULLISH_ZONE), curr_rsi)
        self._add_result("Weekly RSI Trending Down", cat, self._is_falling(rsi), curr_rsi)
        self._add_result("Weekly RSI Crossed Below 30", cat, self._crossed_below(rsi, RSI_OVERSOLD), curr_rsi)
        self._add_result("Weekly RSI Overbought Zone", cat, self._gt(curr_rsi, RSI_OVERBOUGHT), curr_rsi)
        self._add_result("Weekly RSI Oversold Zone", cat, self._lt(curr_rsi, RSI_OVERSOLD), curr_rsi)

    # --------------------------------------------------------------------------
    # 9. Money Flow Index Scans (8 Scans)
    # --------------------------------------------------------------------------
    def run_mfi_scans(self):
        cat = "Money Flow Index"
        if 'MFI' not in self.df.columns:
            self._skip_many(
                [
                    "MFI Bullish",
                    "MFI Trending Up",
                    "MFI Crossed 80 From Below",
                    "MFI Bearish",
                    "MFI Trending Down",
                    "MFI Crossed 20 From Above",
                    "MFI Above 80 (Overbought)",
                    "MFI Below 20 (Oversold)",
                ],
                cat,
                reason="missing_indicator",
            )
            return
        mfi = self.df['MFI']
        curr_mfi = mfi.iloc[-1]
        
        self._add_result("MFI Bullish", cat, self._gt(curr_mfi, MFI_MIDPOINT), curr_mfi)
        self._add_result("MFI Trending Up", cat, self._is_rising(mfi), curr_mfi)
        self._add_result("MFI Crossed 80 From Below", cat, self._crossed_above(mfi, MFI_OVERBOUGHT), curr_mfi)
        self._add_result("MFI Bearish", cat, self._lt(curr_mfi, MFI_MIDPOINT), curr_mfi)
        self._add_result("MFI Trending Down", cat, self._is_falling(mfi), curr_mfi)
        self._add_result("MFI Crossed 20 From Above", cat, self._crossed_below(mfi, MFI_OVERSOLD), curr_mfi)
        self._add_result("MFI Above 80 (Overbought)", cat, self._gt(curr_mfi, MFI_OVERBOUGHT), curr_mfi)
        self._add_result("MFI Below 20 (Oversold)", cat, self._lt(curr_mfi, MFI_OVERSOLD), curr_mfi)

    # --------------------------------------------------------------------------
    # 10. William %R Scans (8 Scans)
    # --------------------------------------------------------------------------
    def run_willr_scans(self):
        cat = "William %R"
        if 'WILLR' not in self.df.columns:
            self._skip_many(
                [
                    "William %R Bullish",
                    "William %R Trending Up",
                    "William %R Crossed -20 From Below",
                    "William %R Bearish",
                    "William %R Trending Down",
                    "William %R Crossed -80 From Above",
                    "William %R in Overbought Zone",
                    "William %R in Oversold Zone",
                ],
                cat,
                reason="missing_indicator",
            )
            return
        wr = self.df['WILLR']
        curr_wr = wr.iloc[-1]
        
        self._add_result("William %R Bullish", cat, self._gt(curr_wr, WILLR_MIDPOINT), curr_wr)
        self._add_result("William %R Trending Up", cat, self._is_rising(wr), curr_wr)
        self._add_result("William %R Crossed -20 From Below", cat, self._crossed_above(wr, WILLR_OVERBOUGHT), curr_wr)
        self._add_result("William %R Bearish", cat, self._lt(curr_wr, WILLR_MIDPOINT), curr_wr)
        self._add_result("William %R Trending Down", cat, self._is_falling(wr), curr_wr)
        self._add_result("William %R Crossed -80 From Above", cat, self._crossed_below(wr, WILLR_OVERSOLD), curr_wr)
        self._add_result("William %R in Overbought Zone", cat, self._gt(curr_wr, WILLR_OVERBOUGHT), curr_wr)
        self._add_result("William %R in Oversold Zone", cat, self._lt(curr_wr, WILLR_OVERSOLD), curr_wr)

    # --------------------------------------------------------------------------
    # 11. Rate of Change Scans (2 Scans)
    # --------------------------------------------------------------------------
    def run_roc_scans(self):
        cat = "Rate of Change"
        if 'ROC' not in self.df.columns:
            self._skip_many(["ROC Trending Up", "ROC Trending Down"], cat, reason="missing_indicator")
            return
        roc = self.df['ROC']
        curr_roc = roc.iloc[-1]
        
        self._add_result("ROC Trending Up", cat, self._is_rising(roc), curr_roc)
        self._add_result("ROC Trending Down", cat, self._is_falling(roc), curr_roc)

    # --------------------------------------------------------------------------
    # 12. MACD Scans (4 Scans)
    # --------------------------------------------------------------------------
    def run_macd_scans(self):
        cat = "MACD"
        if 'MACD_LINE' not in self.df.columns or 'MACD_SIGNAL' not in self.df.columns:
            self._skip_many(
                [
                    "MACD Crossing Signal Line From Below (Bullish)",
                    "MACD Crossing Signal Line From Above (Bearish)",
                    "MACD Moving Above Zero",
                    "MACD Moving Below Zero",
                ],
                cat,
                reason="missing_indicator",
            )
            return
        line = self.df['MACD_LINE']
        sig = self.df['MACD_SIGNAL']
        
        self._add_result("MACD Crossing Signal Line From Below (Bullish)", cat, self._crossed_above(line, sig))
        self._add_result("MACD Crossing Signal Line From Above (Bearish)", cat, self._crossed_below(line, sig))
        self._add_result("MACD Moving Above Zero", cat, self._crossed_above(line, 0))
        self._add_result("MACD Moving Below Zero", cat, self._crossed_below(line, 0))

    # --------------------------------------------------------------------------
    # 13. ADX Scans (10 Scans)
    # --------------------------------------------------------------------------
    def run_adx_scans(self):
        cat = "Average Directional Index"
        if 'ADX' not in self.df.columns or 'PLUS_DI' not in self.df.columns or 'MINUS_DI' not in self.df.columns:
            self._skip_many(
                [
                    "ADX Crossing 25 From Below",
                    "ADX Crossing 40 From Above",
                    "ADX Crossing 10 From Below",
                    "ADX Crossing 25 From Above",
                    "ADX Crossing 40 From Below",
                    "ADX Crossing 10 From Above",
                    "+DI Crossing -DI From Below",
                    "+DI Crossing -DI From Above",
                    "+DI Crossing 25 From Below",
                    "-DI Crossing 25 From Below",
                ],
                cat,
                reason="missing_indicator",
            )
            return
        adx = self.df['ADX']
        pdi = self.df['PLUS_DI']
        mdi = self.df['MINUS_DI']
        
        self._add_result("ADX Crossing 25 From Below", cat, self._crossed_above(adx, ADX_STRONG_TREND))
        self._add_result("ADX Crossing 40 From Above", cat, self._crossed_below(adx, ADX_VERY_STRONG_TREND))
        self._add_result("ADX Crossing 10 From Below", cat, self._crossed_above(adx, ADX_NO_TREND))
        self._add_result("ADX Crossing 25 From Above", cat, self._crossed_below(adx, ADX_STRONG_TREND))
        self._add_result("ADX Crossing 40 From Below", cat, self._crossed_above(adx, ADX_VERY_STRONG_TREND))
        self._add_result("ADX Crossing 10 From Above", cat, self._crossed_below(adx, ADX_NO_TREND))
        self._add_result("+DI Crossing -DI From Below", cat, self._crossed_above(pdi, mdi))
        self._add_result("+DI Crossing -DI From Above", cat, self._crossed_below(pdi, mdi))
        self._add_result("+DI Crossing 25 From Below", cat, self._crossed_above(pdi, 25))
        self._add_result("-DI Crossing 25 From Below", cat, self._crossed_above(mdi, 25))

    # --------------------------------------------------------------------------
    # 14. Average True Range Scans (6 Scans)
    # --------------------------------------------------------------------------
    def run_atr_scans(self):
        cat = "Average True Range"
        if 'ATR' not in self.df.columns:
            self._skip_many(
                [
                    "ATR Increasing for 3 Days",
                    "ATR Increasing for 5 Days",
                    "ATR Increasing for 7 Days",
                    "ATR Decreasing for 3 Days",
                    "ATR Decreasing for 5 Days",
                    "ATR Decreasing for 7 Days",
                ],
                cat,
                reason="missing_indicator",
            )
            return
        atr = self.df['ATR']
        
        self._add_result("ATR Increasing for 3 Days", cat, self._is_rising(atr, 3))
        self._add_result("ATR Increasing for 5 Days", cat, self._is_rising(atr, 5))
        self._add_result("ATR Increasing for 7 Days", cat, self._is_rising(atr, 7))
        self._add_result("ATR Decreasing for 3 Days", cat, self._is_falling(atr, 3))
        self._add_result("ATR Decreasing for 5 Days", cat, self._is_falling(atr, 5))
        self._add_result("ATR Decreasing for 7 Days", cat, self._is_falling(atr, 7))

    # --------------------------------------------------------------------------
    # 15. Bollinger Band Scans (8 Scans)
    # --------------------------------------------------------------------------
    def run_bb_scans(self):
        cat = "Bollinger Bands"
        if 'BB_UPPER' not in self.df.columns or 'BB_LOWER' not in self.df.columns or 'BB_WIDTH' not in self.df.columns:
            self._skip_many(
                [
                    "Close Crossing Upper Bollinger Band From Below",
                    "Close Crossing Lower Bollinger Band From Above",
                    "Close Crossing Upper Bollinger Band From Above",
                    "Close Crossing Lower Bollinger Band From Below",
                    "Narrow Bollinger Band Width (Squeeze)",
                    "Wide Bollinger Band Width (Expansion)",
                    "Close Above Upper Bollinger Band",
                    "Close Below Lower Bollinger Band",
                ],
                cat,
                reason="missing_indicator",
            )
            return
        close = self.df['Close']
        upper = self.df['BB_UPPER']
        lower = self.df['BB_LOWER']
        width = self.df['BB_WIDTH']
        
        # Bandwidth relative checks
        # "Narrow" and "Wide" are relative to recent history (e.g. 6 month percentile)
        # Using simple percentile check if sufficient history
        is_narrow = None
        is_wide = None
        width_hist = width.dropna()
        if len(width_hist) > 100:
            hist = width_hist.iloc[-120:]  # ~6 months history
            curr_w = width.iloc[-1]
            if not pd.isna(curr_w) and len(hist) > 20:
                is_narrow = curr_w <= np.percentile(hist, BB_SQUEEZE_PERCENTILE)
                is_wide = curr_w >= np.percentile(hist, BB_EXPANSION_PERCENTILE)

        self._add_result("Close Crossing Upper Bollinger Band From Below", cat, self._crossed_above(close, upper))
        self._add_result("Close Crossing Lower Bollinger Band From Above", cat, self._crossed_below(close, lower))
        self._add_result("Close Crossing Upper Bollinger Band From Above", cat, self._crossed_below(close, upper))
        self._add_result("Close Crossing Lower Bollinger Band From Below", cat, self._crossed_above(close, lower))
        self._add_result("Narrow Bollinger Band Width (Squeeze)", cat, is_narrow, width.iloc[-1])
        self._add_result("Wide Bollinger Band Width (Expansion)", cat, is_wide, width.iloc[-1])
        self._add_result("Close Above Upper Bollinger Band", cat, self._gt(close.iloc[-1], upper.iloc[-1]))
        self._add_result("Close Below Lower Bollinger Band", cat, self._lt(close.iloc[-1], lower.iloc[-1]))

    # --------------------------------------------------------------------------
    # 16. Stochastic Scans (10 Scans)
    # --------------------------------------------------------------------------
    def run_stochastic_scans(self):
        cat = "Stochastic"
        if 'STOCH_K' not in self.df.columns or 'STOCH_D' not in self.df.columns:
            self._skip_many(
                [
                    "Stochastic Reversing From Oversold Zone From Below",
                    "Stochastic Trending Up",
                    "Stochastic Entering Overbought Zone From Below",
                    "Stochastic Reversing From Overbought Zone",
                    "Stochastic Trending Down",
                    "Stochastic Entering Oversold Zone From Above",
                    "Stochastic %K Crossing %D From Below",
                    "Stochastic %K Crossing %D From Above",
                    "Stochastic In Overbought Zone",
                    "Stochastic In Oversold Zone",
                ],
                cat,
                reason="missing_indicator",
            )
            return
        k = self.df['STOCH_K']
        d = self.df['STOCH_D']
        curr_k = k.iloc[-1]
        
        self._add_result("Stochastic Reversing From Oversold Zone From Below", cat, self._crossed_above(k, STOCH_OVERSOLD), curr_k)
        self._add_result("Stochastic Trending Up", cat, self._is_rising(k), curr_k)
        self._add_result("Stochastic Entering Overbought Zone From Below", cat, self._crossed_above(k, STOCH_OVERBOUGHT), curr_k)
        self._add_result("Stochastic Reversing From Overbought Zone", cat, self._crossed_below(k, STOCH_OVERBOUGHT), curr_k)
        self._add_result("Stochastic Trending Down", cat, self._is_falling(k), curr_k)
        self._add_result("Stochastic Entering Oversold Zone From Above", cat, self._crossed_below(k, STOCH_OVERSOLD), curr_k)
        self._add_result("Stochastic %K Crossing %D From Below", cat, self._crossed_above(k, d))
        self._add_result("Stochastic %K Crossing %D From Above", cat, self._crossed_below(k, d))
        self._add_result("Stochastic In Overbought Zone", cat, self._gt(curr_k, STOCH_OVERBOUGHT), curr_k)
        self._add_result("Stochastic In Oversold Zone", cat, self._lt(curr_k, STOCH_OVERSOLD), curr_k)

    # --------------------------------------------------------------------------
    # 17. Parabolic SAR Scans (2 Scans)
    # --------------------------------------------------------------------------
    def run_psar_scans(self):
        cat = "Parabolic SAR"
        if 'PSAR' not in self.df.columns:
            self._skip_many(
                ["PSAR Indicating Bullish Reversal", "PSAR Indicating Bearish Reversal"],
                cat,
                reason="missing_indicator",
            )
            return
        close = self.df['Close']
        psar = self.df['PSAR']
        
        # Bullish Reversal: Price crosses above PSAR (dots flip to below price)
        # Bearish Reversal: Price crosses below PSAR (dots flip to above price)
        self._add_result("PSAR Indicating Bullish Reversal", cat, self._crossed_above(close, psar))
        self._add_result("PSAR Indicating Bearish Reversal", cat, self._crossed_below(close, psar))

    # --------------------------------------------------------------------------
    # 18. Weekly Parabolic SAR Scans (2 Scans)
    # --------------------------------------------------------------------------
    def run_weekly_psar_scans(self):
        cat = "Weekly Parabolic SAR"
        if self.w_df.empty:
            self._skip_many(
                ["Weekly PSAR Indicating Bullish Reversal", "Weekly PSAR Indicating Bearish Reversal"],
                cat,
                reason="missing_weekly_data",
            )
            return
        if 'PSAR' not in self.w_df.columns:
            self._skip_many(
                ["Weekly PSAR Indicating Bullish Reversal", "Weekly PSAR Indicating Bearish Reversal"],
                cat,
                reason="missing_indicator",
            )
            return
        close = self.w_df['Close']
        psar = self.w_df['PSAR']
        
        self._add_result("Weekly PSAR Indicating Bullish Reversal", cat, self._crossed_above(close, psar))
        self._add_result("Weekly PSAR Indicating Bearish Reversal", cat, self._crossed_below(close, psar))

    # --------------------------------------------------------------------------
    # 19. Narrow Range Scans (6 Scans)
    # --------------------------------------------------------------------------
    def run_nr_scans(self):
        cat = "Narrow Range"
        # Calculate True Range or High-Low range
        df = self.df.copy()
        df['Range'] = df['High'] - df['Low']
        
        if len(df) < 8:
            self._skip_many(
                [
                    "NR 4 (Narrowest Range in 4 Days)",
                    "NR 7 (Narrowest Range in 7 Days)",
                    "NR 4 Breakout",
                    "NR 4 Breakdown",
                    "NR 7 Breakout",
                    "NR 7 Breakdown",
                ],
                cat,
                reason="insufficient_history",
            )
            return
        
        curr_range = df['Range'].iloc[-1]
        
        # NR4: Today's range is the smallest of the last 4 days
        nr4 = curr_range == df['Range'].iloc[-4:].min()
        
        # NR7: Today's range is the smallest of the last 7 days
        nr7 = curr_range == df['Range'].iloc[-7:].min()
        
        # Breakout/Breakdown logic:
        # Check if YESTERDAY was NR4/NR7 and TODAY price moved significantly?
        # Usually scan finds stocks currently IN narrow range, OR breaking out of it.
        # Standard interpretation: "NR4" means today IS an NR4 day.
        # "NR4 Breakout" means Yesterday was NR4, and today Close > Yesterday High.
        
        prev_range = df['Range'].iloc[-2]
        prev_is_nr4 = prev_range == df['Range'].iloc[-5:-1].min()
        prev_is_nr7 = prev_range == df['Range'].iloc[-8:-1].min()
        
        prev_high = df['High'].iloc[-2]
        prev_low = df['Low'].iloc[-2]
        curr_close = df['Close'].iloc[-1]
        
        nr4_breakout = prev_is_nr4 and curr_close > prev_high
        nr4_breakdown = prev_is_nr4 and curr_close < prev_low
        nr7_breakout = prev_is_nr7 and curr_close > prev_high
        nr7_breakdown = prev_is_nr7 and curr_close < prev_low

        self._add_result("NR 4 (Narrowest Range in 4 Days)", cat, nr4)
        self._add_result("NR 7 (Narrowest Range in 7 Days)", cat, nr7)
        self._add_result("NR 4 Breakout", cat, nr4_breakout)
        self._add_result("NR 4 Breakdown", cat, nr4_breakdown)
        self._add_result("NR 7 Breakout", cat, nr7_breakout)
        self._add_result("NR 7 Breakdown", cat, nr7_breakdown)

    # --------------------------------------------------------------------------
    # 20. SuperTrend Scans (4 Scans)
    # --------------------------------------------------------------------------
    def run_supertrend_scans(self):
        cat = "SuperTrend"
        if 'SUPERTREND' not in self.df.columns or 'SUPERTREND_DIR' not in self.df.columns:
            self._skip_many(
                [
                    "SuperTrend Signal Changed To Buy",
                    "SuperTrend Signal Changed To Sell",
                    "Price Nearing SuperTrend Support",
                    "Price Nearing SuperTrend Resistance",
                ],
                cat,
                reason="missing_indicator",
            )
            return
        st = self.df['SUPERTREND']
        direction = self.df['SUPERTREND_DIR'] # 1 is bullish, -1 is bearish
        close = self.df['Close']
        curr_close = close.iloc[-1]
        st_val = st.iloc[-1]
        
        # Signal Change: Direction flipped in the latest candle
        if len(direction) < 2:
            self._skip_many(
                [
                    "SuperTrend Signal Changed To Buy",
                    "SuperTrend Signal Changed To Sell",
                    "Price Nearing SuperTrend Support",
                    "Price Nearing SuperTrend Resistance",
                ],
                cat,
                reason="insufficient_history",
            )
            return

        prev_dir, curr_dir = direction.iloc[-2], direction.iloc[-1]
        if pd.isna(prev_dir) or pd.isna(curr_dir) or pd.isna(st_val) or pd.isna(curr_close):
            self._skip_many(
                [
                    "SuperTrend Signal Changed To Buy",
                    "SuperTrend Signal Changed To Sell",
                    "Price Nearing SuperTrend Support",
                    "Price Nearing SuperTrend Resistance",
                ],
                cat,
                reason="missing_value",
            )
            return
        
        self._add_result("SuperTrend Signal Changed To Buy", cat, prev_dir == -1 and curr_dir == 1)
        self._add_result("SuperTrend Signal Changed To Sell", cat, prev_dir == 1 and curr_dir == -1)
        
        # Nearing support (Price > ST, and price drops near ST)
        nearing_supp = curr_dir == 1 and self._is_nearing(curr_close, st_val)
        # Nearing resistance (Price < ST, and price rises near ST)
        nearing_res = curr_dir == -1 and self._is_nearing(curr_close, st_val)
        
        self._add_result("Price Nearing SuperTrend Support", cat, nearing_supp, st_val)
        self._add_result("Price Nearing SuperTrend Resistance", cat, nearing_res, st_val)

    # --------------------------------------------------------------------------
    # 21. Weekly SuperTrend Scans (4 Scans)
    # --------------------------------------------------------------------------
    def run_weekly_supertrend_scans(self):
        cat = "Weekly SuperTrend"
        if self.w_df.empty:
            self._skip_many(
                [
                    "Weekly SuperTrend Signal Changed To Buy",
                    "Weekly SuperTrend Signal Changed To Sell",
                    "Price Nearing Weekly SuperTrend Support",
                    "Price Nearing Weekly SuperTrend Resistance",
                ],
                cat,
                reason="missing_weekly_data",
            )
            return
        if 'SUPERTREND' not in self.w_df.columns or 'SUPERTREND_DIR' not in self.w_df.columns:
            self._skip_many(
                [
                    "Weekly SuperTrend Signal Changed To Buy",
                    "Weekly SuperTrend Signal Changed To Sell",
                    "Price Nearing Weekly SuperTrend Support",
                    "Price Nearing Weekly SuperTrend Resistance",
                ],
                cat,
                reason="missing_indicator",
            )
            return
        st = self.w_df['SUPERTREND']
        direction = self.w_df['SUPERTREND_DIR']
        close = self.w_df['Close']
        curr_close = close.iloc[-1]
        st_val = st.iloc[-1]
        
        if len(direction) < 2:
            self._skip_many(
                [
                    "Weekly SuperTrend Signal Changed To Buy",
                    "Weekly SuperTrend Signal Changed To Sell",
                    "Price Nearing Weekly SuperTrend Support",
                    "Price Nearing Weekly SuperTrend Resistance",
                ],
                cat,
                reason="insufficient_history",
            )
            return

        prev_dir, curr_dir = direction.iloc[-2], direction.iloc[-1]
        if pd.isna(prev_dir) or pd.isna(curr_dir) or pd.isna(st_val) or pd.isna(curr_close):
            self._skip_many(
                [
                    "Weekly SuperTrend Signal Changed To Buy",
                    "Weekly SuperTrend Signal Changed To Sell",
                    "Price Nearing Weekly SuperTrend Support",
                    "Price Nearing Weekly SuperTrend Resistance",
                ],
                cat,
                reason="missing_value",
            )
            return
        
        self._add_result("Weekly SuperTrend Signal Changed To Buy", cat, prev_dir == -1 and curr_dir == 1)
        self._add_result("Weekly SuperTrend Signal Changed To Sell", cat, prev_dir == 1 and curr_dir == -1)
        self._add_result("Price Nearing Weekly SuperTrend Support", cat, curr_dir == 1 and self._is_nearing(curr_close, st_val), st_val)
        self._add_result("Price Nearing Weekly SuperTrend Resistance", cat, curr_dir == -1 and self._is_nearing(curr_close, st_val), st_val)

    # --------------------------------------------------------------------------
    # 22. Beta Scans (6 Scans)
    # --------------------------------------------------------------------------
    def run_beta_scans(self):
        cat = "Beta"
        if 'BETA' not in self.df.columns:
            self._skip_many(
                [
                    "High Beta - Benchmark Index",
                    "Low Beta - Benchmark Index",
                    "Negative Beta - Benchmark Index",
                    "High Beta - Sectoral Index",
                    "Low Beta - Sectoral Index",
                    "Negative Beta - Sectoral Index",
                ],
                cat,
                reason="missing_indicator",
            )
            return
        beta = self.df['BETA'].iloc[-1]

        if pd.isna(beta):
            self._skip_many(
                [
                    "High Beta - Benchmark Index",
                    "Low Beta - Benchmark Index",
                    "Negative Beta - Benchmark Index",
                    "High Beta - Sectoral Index",
                    "Low Beta - Sectoral Index",
                    "Negative Beta - Sectoral Index",
                ],
                cat,
                reason="missing_value",
            )
            return
        
        # High/Low relative to Benchmark
        self._add_result("High Beta - Benchmark Index", cat, self._gt(beta, BETA_HIGH_THRESHOLD), beta)
        self._add_result("Low Beta - Benchmark Index", cat, self._lt(beta, BETA_LOW_THRESHOLD), beta)
        self._add_result("Negative Beta - Benchmark Index", cat, self._lt(beta, 0), beta)
        
        # Sector (Industry) Beta: compare stock beta vs the industry's average beta.
        # This industry average is computed upstream and stored as a constant column.
        if 'INDUSTRY_BETA_AVG' not in self.df.columns:
            self._skip_many(
                [
                    "High Beta - Sectoral Index",
                    "Low Beta - Sectoral Index",
                    "Negative Beta - Sectoral Index",
                ],
                cat,
                reason="missing_indicator",
            )
            return

        industry_beta = self.df['INDUSTRY_BETA_AVG'].iloc[-1]
        if pd.isna(industry_beta) or pd.isna(beta):
            self._skip_many(
                [
                    "High Beta - Sectoral Index",
                    "Low Beta - Sectoral Index",
                    "Negative Beta - Sectoral Index",
                ],
                cat,
                reason="missing_value",
            )
            return

        self._add_result("High Beta - Sectoral Index", cat, beta > industry_beta, beta)
        self._add_result("Low Beta - Sectoral Index", cat, beta < industry_beta, beta)
        self._add_result("Negative Beta - Sectoral Index", cat, beta < 0, beta)

    # --------------------------------------------------------------------------
    # 23. Ichimoku Cloud Scans (14 Scans)
    # --------------------------------------------------------------------------
    def run_ichimoku_scans(self):
        cat = "Ichimoku Cloud"
        required = {'TENKAN', 'KIJUN', 'SPAN_A', 'SPAN_B'}
        if not required.issubset(set(self.df.columns)):
            self._skip_many(
                [
                    "Price Near Tenkan Sen Support",
                    "Price Near Tenkan Sen Resistance",
                    "Close Crossing Tenkan Sen from Below",
                    "Close Crossing Tenkan Sen from Above",
                    "Price Near Kijun Sen Support",
                    "Price Near Kijun Sen Resistance",
                    "Close Crossing Kijun Sen from Below",
                    "Close Crossing Kijun Sen from Above",
                    "Tenkan Sen Crossing Kijun Sen from Below",
                    "Tenkan Sen Crossing Kijun Sen from Above",
                    "Senkou Span A crossing Senkou Span B from Below",
                    "Senkou Span A crossing Senkou Span B from Above",
                    "Chikou Span Crossing Price from Below",
                    "Chikou Span Crossing Price from Above",
                ],
                cat,
                reason="missing_indicator",
            )
            return
        
        close = self.df['Close']
        curr_close = close.iloc[-1]
        tenkan = self.df['TENKAN']
        kijun = self.df['KIJUN']
        span_a = self.df['SPAN_A']
        span_b = self.df['SPAN_B']
        chikou = self.df['CHIKOU'] # This is shifted backwards in dataframe usually
        
        # NOTE: Chikou Span in pandas_ta is usually the current close shifted back 26 periods.
        # To check "Chikou crossing Price", we actually check if (Close shifted back) crosses (Price at that time).
        # Simplification: Compare Current Close vs Price 26 periods ago? No, Chikou is plotting current close 26 bars back.
        # "Chikou crossing Price" means: Does today's Close cross the price candle from 26 days ago?
        price_26_ago = close.iloc[-26] if len(close) > 26 else 0
        prev_close = close.iloc[-2]
        
        # Tenkan/Kijun Support/Resistance
        above_tenkan = self._gt(close.iloc[-1], tenkan.iloc[-1])
        below_tenkan = self._lt(close.iloc[-1], tenkan.iloc[-1])
        near_tenkan = self._is_nearing(curr_close, tenkan.iloc[-1])
        self._add_result(
            "Price Near Tenkan Sen Support",
            cat,
            (above_tenkan and near_tenkan) if above_tenkan is not None and near_tenkan is not None else None,
        )
        self._add_result(
            "Price Near Tenkan Sen Resistance",
            cat,
            (below_tenkan and near_tenkan) if below_tenkan is not None and near_tenkan is not None else None,
        )
        self._add_result("Close Crossing Tenkan Sen from Below", cat, self._crossed_above(close, tenkan))
        self._add_result("Close Crossing Tenkan Sen from Above", cat, self._crossed_below(close, tenkan))
        
        above_kijun = self._gt(close.iloc[-1], kijun.iloc[-1])
        below_kijun = self._lt(close.iloc[-1], kijun.iloc[-1])
        near_kijun = self._is_nearing(curr_close, kijun.iloc[-1])
        self._add_result(
            "Price Near Kijun Sen Support",
            cat,
            (above_kijun and near_kijun) if above_kijun is not None and near_kijun is not None else None,
        )
        self._add_result(
            "Price Near Kijun Sen Resistance",
            cat,
            (below_kijun and near_kijun) if below_kijun is not None and near_kijun is not None else None,
        )
        self._add_result("Close Crossing Kijun Sen from Below", cat, self._crossed_above(close, kijun))
        self._add_result("Close Crossing Kijun Sen from Above", cat, self._crossed_below(close, kijun))
        
        # TK Cross
        self._add_result("Tenkan Sen Crossing Kijun Sen from Below", cat, self._crossed_above(tenkan, kijun))
        self._add_result("Tenkan Sen Crossing Kijun Sen from Above", cat, self._crossed_below(tenkan, kijun))
        
        # Cloud Twist (Future Cloud)
        # Usually Span A/B are shifted forward. pandas_ta puts them on current date.
        # Check if Span A crosses Span B
        self._add_result("Senkou Span A crossing Senkou Span B from Below", cat, self._crossed_above(span_a, span_b))
        self._add_result("Senkou Span A crossing Senkou Span B from Above", cat, self._crossed_below(span_a, span_b))
        
        # Chikou Crossing Price
        # Logic: Does Current Close Cross Price[T-26]?
        if len(close) > 27:
            p_26 = close.iloc[-26]
            p_27 = close.iloc[-27] # Previous day's reference point
            curr_c = close.iloc[-1]
            prev_c = close.iloc[-2]

            if pd.isna(p_26) or pd.isna(p_27) or pd.isna(curr_c) or pd.isna(prev_c):
                self._add_result("Chikou Span Crossing Price from Below", cat, None, reason="missing_value")
                self._add_result("Chikou Span Crossing Price from Above", cat, None, reason="missing_value")
                return
            
            # Cross Above: Prev Close < Prev Ref AND Curr Close > Curr Ref
            chk_cross_up = prev_c <= p_27 and curr_c > p_26
            chk_cross_down = prev_c >= p_27 and curr_c < p_26
            
            self._add_result("Chikou Span Crossing Price from Below", cat, chk_cross_up)
            self._add_result("Chikou Span Crossing Price from Above", cat, chk_cross_down)
        else:
            self._add_result("Chikou Span Crossing Price from Below", cat, None, reason="insufficient_history")
            self._add_result("Chikou Span Crossing Price from Above", cat, None, reason="insufficient_history")

    # --------------------------------------------------------------------------
    # Orchestrator
    # --------------------------------------------------------------------------
    def run_all(self) -> Dict[str, List[Dict[str, Any]]]:
        """Executes all implemented scans."""
        self.run_momentum_scans()
        self.run_sma_scans()
        self.run_weekly_sma_scans()
        self.run_ema_scans()
        self.run_weekly_ema_scans()
        self.run_cci_scans()
        self.run_rsi_scans()
        self.run_weekly_rsi_scans()
        self.run_mfi_scans()
        self.run_willr_scans()
        self.run_roc_scans()
        self.run_macd_scans()
        self.run_adx_scans()
        self.run_atr_scans()
        self.run_bb_scans()
        self.run_stochastic_scans()
        self.run_psar_scans()
        self.run_weekly_psar_scans()
        self.run_nr_scans()
        self.run_supertrend_scans()
        self.run_weekly_supertrend_scans()
        self.run_beta_scans()
        self.run_ichimoku_scans()
        
        return self.results