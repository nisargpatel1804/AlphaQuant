"""
Core Logic Module for Technical Scans (Refactored).
Implements mutually exclusive checks and groups them by category with isolated signal logic.
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass

from .config import (
    NEARING_THRESHOLD_PCT,
    MOMENTUM_BULLISH_THRESHOLD, MOMENTUM_BEARISH_THRESHOLD,
    RSI_OVERBOUGHT, RSI_OVERSOLD, RSI_BULLISH_ZONE,
    CCI_OVERBOUGHT, CCI_OVERSOLD,
    STOCH_OVERBOUGHT, STOCH_OVERSOLD,
    WILLR_OVERBOUGHT, WILLR_OVERSOLD,
    MFI_OVERBOUGHT, MFI_OVERSOLD,
    ADX_STRONG_TREND,
    BB_SQUEEZE_PERCENTILE, BB_EXPANSION_PERCENTILE,
    HMA_PERIOD, VWMA_PERIOD
)

@dataclass(frozen=True)
class TechScanDefinition:
    name: str
    label: str
    category: str

def _build_tech_scans() -> Tuple[TechScanDefinition, ...]:
    scans = [
        # Momentum
        ("check_momentum_1m", "Momentum (1M)", "Momentum"),
        ("check_momentum_3m", "Momentum (3M)", "Momentum"),
        ("check_momentum_6m", "Momentum (6M)", "Momentum"),
        ("check_momentum_10", "Momentum (10)", "Momentum"),
        
        # Moving Averages
        ("check_sma_10_status", "Price vs SMA 10", "Simple Moving Averages"),
        ("check_sma_20_status", "Price vs SMA 20", "Simple Moving Averages"),
        ("check_sma_30_status", "Price vs SMA 30", "Simple Moving Averages"),
        ("check_sma_50_status", "Price vs SMA 50", "Simple Moving Averages"),
        ("check_sma_100_status", "Price vs SMA 100", "Simple Moving Averages"),
        ("check_sma_200_status", "Price vs SMA 200", "Simple Moving Averages"),
        
        ("check_ema_10_status", "Price vs EMA 10", "Exponential Moving Averages"),
        ("check_ema_20_status", "Price vs EMA 20", "Exponential Moving Averages"),
        ("check_ema_30_status", "Price vs EMA 30", "Exponential Moving Averages"),
        ("check_ema_50_status", "Price vs EMA 50", "Exponential Moving Averages"),
        ("check_ema_100_status", "Price vs EMA 100", "Exponential Moving Averages"),
        ("check_ema_200_status", "Price vs EMA 200", "Exponential Moving Averages"),
        
        ("check_hma_status", f"Hull Moving Average ({HMA_PERIOD})", "Hull Moving Average"),
        ("check_vwma_status", f"VWMA ({VWMA_PERIOD})", "Volume Weighted MA"),

        # Crossovers (Grouped into SMAs for now, or could be separate)
        ("check_ma_crossover_50_200", "Golden/Death Cross", "Simple Moving Averages"),
        ("check_price_cross_sma_20", "Price Crossover SMA 20", "Simple Moving Averages"),
        
        # Oscillators
        ("check_rsi_status", "RSI Zone", "RSI"),
        ("check_rsi_trend", "RSI Trend", "RSI"),
        ("check_cci_status", "CCI Zone", "CCI"),
        ("check_mfi_status", "MFI Zone", "MFI"),
        ("check_stoch_status", "Stochastic %K", "Stochastic"),
        ("check_stochrsi_status", "Stochastic RSI Fast", "Stoch RSI"),
        ("check_willr_status", "Williams %R", "Williams %R"),
        ("check_ao_status", "Awesome Oscillator", "Awesome Oscillator"),
        ("check_ultosc_status", "Ultimate Oscillator", "Ultimate Oscillator"),
        ("check_bbp_status", "Bull Bear Power", "Bull/Bear Power"),
        
        # Trend
        ("check_macd_status", "MACD Level", "MACD"),
        ("check_adx_status", "ADX Trend Strength", "ADX"),
        ("check_supertrend_status", "SuperTrend Status", "SuperTrend"),
        ("check_psar_status", "Parabolic SAR", "Parabolic SAR"),
        
        # Volatility
        ("check_bb_status", "Bollinger Bands Position", "Bollinger Bands"),
        ("check_bb_width", "Bollinger Bands Width", "Bollinger Bands"),
        
        # Ichimoku
        ("check_ichimoku_cloud", "Cloud Status", "Ichimoku"),
        ("check_ichimoku_base", "Ichimoku Base Line", "Ichimoku"),
        ("check_ichimoku_tk", "TK Cross", "Ichimoku"),
        
        # Beta
        ("check_beta_status", "Beta Status", "Beta"),
        
        # Pivots (Classic)
        ("check_pivot_classic_p", "Pivot Classic P", "Pivots - Classic"),
        ("check_pivot_classic_r1", "Pivot Classic R1", "Pivots - Classic"),
        ("check_pivot_classic_s1", "Pivot Classic S1", "Pivots - Classic"),
        ("check_pivot_classic_r2", "Pivot Classic R2", "Pivots - Classic"),
        ("check_pivot_classic_s2", "Pivot Classic S2", "Pivots - Classic"),
        ("check_pivot_classic_r3", "Pivot Classic R3", "Pivots - Classic"),
        ("check_pivot_classic_s3", "Pivot Classic S3", "Pivots - Classic"),

        # Pivots (Fibonacci)
        ("check_pivot_fib_p", "Pivot Fibonacci P", "Pivots - Fibonacci"),
        ("check_pivot_fib_r1", "Pivot Fibonacci R1", "Pivots - Fibonacci"),
        ("check_pivot_fib_s1", "Pivot Fibonacci S1", "Pivots - Fibonacci"),
        ("check_pivot_fib_r2", "Pivot Fibonacci R2", "Pivots - Fibonacci"),
        ("check_pivot_fib_s2", "Pivot Fibonacci S2", "Pivots - Fibonacci"),
        ("check_pivot_fib_r3", "Pivot Fibonacci R3", "Pivots - Fibonacci"),
        ("check_pivot_fib_s3", "Pivot Fibonacci S3", "Pivots - Fibonacci"),

        # Pivots (Camarilla)
        ("check_pivot_cam_r1", "Pivot Camarilla R1", "Pivots - Camarilla"),
        ("check_pivot_cam_r2", "Pivot Camarilla R2", "Pivots - Camarilla"),
        ("check_pivot_cam_r3", "Pivot Camarilla R3", "Pivots - Camarilla"),
        ("check_pivot_cam_r4", "Pivot Camarilla R4", "Pivots - Camarilla"),
        ("check_pivot_cam_s1", "Pivot Camarilla S1", "Pivots - Camarilla"),
        ("check_pivot_cam_s2", "Pivot Camarilla S2", "Pivots - Camarilla"),
        ("check_pivot_cam_s3", "Pivot Camarilla S3", "Pivots - Camarilla"),
        ("check_pivot_cam_s4", "Pivot Camarilla S4", "Pivots - Camarilla"),

        # Pivots (Woodie)
        ("check_pivot_woodie_p", "Pivot Woodie P", "Pivots - Woodie"),
        ("check_pivot_woodie_r1", "Pivot Woodie R1", "Pivots - Woodie"),
        ("check_pivot_woodie_s1", "Pivot Woodie S1", "Pivots - Woodie"),
        ("check_pivot_woodie_r2", "Pivot Woodie R2", "Pivots - Woodie"),
        ("check_pivot_woodie_s2", "Pivot Woodie S2", "Pivots - Woodie"),
        ("check_pivot_woodie_r3", "Pivot Woodie R3", "Pivots - Woodie"),
        ("check_pivot_woodie_s3", "Pivot Woodie S3", "Pivots - Woodie"),

        # Pivots (DeMark)
        ("check_pivot_demark_p", "Pivot DeMark P", "Pivots - DeMark"),
        ("check_pivot_demark_r1", "Pivot DeMark R1", "Pivots - DeMark"),
        ("check_pivot_demark_s1", "Pivot DeMark S1", "Pivots - DeMark"),
    ]
    return tuple(TechScanDefinition(*s) for s in scans)


class TechnicalScans:
    SCANS = _build_tech_scans()

    def __init__(self, daily_df: pd.DataFrame, weekly_df: pd.DataFrame):
        self.df = daily_df
        self.w_df = weekly_df
        self._current_value: Optional[float] = None
        self._current_min: Optional[float] = None
        self._current_max: Optional[float] = None

    @classmethod
    def get_total_logical_scans(cls) -> int:
        return 214 

    # --- Helpers ---
    def _get_val(self, series: pd.Series, offset: int = 0) -> float:
        if len(series) < offset + 1: return np.nan
        return series.iloc[-(offset + 1)]

    def _record_series(self, series: pd.Series, offset: int = 0) -> None:
        """Record current value + min/max over available non-NaN history for a series."""
        try:
            if series is None or len(series) == 0:
                self._current_value = None
                self._current_min = None
                self._current_max = None
                return

            val = self._get_val(series, offset=offset)
            self._current_value = float(val) if isinstance(val, (int, float, np.number)) and np.isfinite(val) else None

            s = series.dropna()
            if s.empty:
                self._current_min = None
                self._current_max = None
                return

            mn = float(s.min())
            mx = float(s.max())
            self._current_min = mn if np.isfinite(mn) else None
            self._current_max = mx if np.isfinite(mx) else None
        except Exception:
            self._current_value = None
            self._current_min = None
            self._current_max = None

    def _record_value(self, val: Any) -> None:
        # Compatibility helper
        if isinstance(val, (int, float, np.number)):
            self._current_value = float(val)
        else:
            self._current_value = None

    @staticmethod
    def _map_status_to_action(status_text: str) -> str:
        """Map scan status text to a consistent 5-level action."""
        t = (status_text or "").strip().lower()
        if not t: return "Neutral"
        if "pending" in t or "missing" in t: return "Neutral"
        if "squeeze" in t or "neutral" in t or "no cross" in t or "inside" in t: return "Neutral"
        
        # Strong Signals
        if "strong buy" in t or "overbought" in t: return "Strong Buy" # Assuming OB is Bullish momentum here
        if "strong sell" in t or "oversold" in t: return "Strong Sell" # Assuming OS is Bearish trend here
        # Note: RSI Overbought is technically strong momentum but can be a sell signal. 
        # For simplicity in this trend-following system: 
        # Overbought (>70) -> Strong momentum (Buy)? Or Mean Reversion (Sell)?
        # StockEdge usually treats "Entering Overbought" as Bullish. Let's stick to trend following.
        
        if "bullish" in t or "buy" in t or "above" in t or "rising" in t or "positive" in t: return "Buy"
        if "bearish" in t or "sell" in t or "below" in t or "falling" in t or "negative" in t: return "Sell"
        
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
        
        avg_score = score / count
        
        if avg_score >= 1.5: return "Strong Buy"
        if avg_score >= 0.5: return "Buy"
        if avg_score <= -1.5: return "Strong Sell"
        if avg_score <= -0.5: return "Sell"
        return "Neutral"

    # --- Common Helpers ---
    def _is_rising(self, series: pd.Series, period: int = 1) -> bool:
        if len(series) < period + 1: return False
        return series.iloc[-1] > series.iloc[-(period + 1)]

    def _is_nearing(self, price: float, target: float) -> bool:
        if pd.isna(price) or pd.isna(target) or target == 0: return False
        return abs(price - target) / abs(target) * 100 <= NEARING_THRESHOLD_PCT

    def _crossed(self, series_a: pd.Series, series_b: Any) -> int:
        if len(series_a) < 2: return 0
        curr_a, prev_a = series_a.iloc[-1], series_a.iloc[-2]
        if isinstance(series_b, (int, float)):
            curr_b, prev_b = series_b, series_b
        else:
            if len(series_b) < 2: return 0
            curr_b, prev_b = series_b.iloc[-1], series_b.iloc[-2]
        if pd.isna(curr_a) or pd.isna(prev_a) or pd.isna(curr_b) or pd.isna(prev_b): return 0
        if prev_a <= prev_b and curr_a > curr_b: return 1
        if prev_a >= prev_b and curr_a < curr_b: return -1
        return 0

    # ------------------------------------------------------------------
    # SCAN LOGIC IMPLEMENTATION
    # ------------------------------------------------------------------

    def _check_momentum(self, period_days: int) -> str:
        close = self.df['Close']
        if len(close) <= period_days + 1: return "Pending"
        roc = close.pct_change(period_days) * 100
        curr = roc.iloc[-1]
        self._record_series(roc)
        if curr > MOMENTUM_BULLISH_THRESHOLD: return "Bullish Zone"
        if curr < MOMENTUM_BEARISH_THRESHOLD: return "Bearish Zone"
        return "Neutral Zone"

    def check_momentum_1m(self) -> str: return self._check_momentum(21)
    def check_momentum_3m(self) -> str: return self._check_momentum(63)
    def check_momentum_6m(self) -> str: return self._check_momentum(126)
    def check_momentum_10(self) -> str:
        col = 'MOMENTUM_10'
        if col not in self.df.columns: return "Pending"
        self._record_series(self.df[col])
        curr = self.df[col].iloc[-1]
        if pd.isna(curr): return "Pending"
        return "Buy" if curr > 0 else "Sell"

    def _check_ma_status(self, col_name: str) -> str:
        if col_name not in self.df.columns: return "Pending"
        ma = self.df[col_name].iloc[-1]
        price = self.df['Close'].iloc[-1]
        self._record_series(self.df[col_name])
        if self._is_nearing(price, ma): return f"Near Support/Res"
        return "Buy" if price > ma else "Sell"

    def check_sma_10_status(self) -> str: return self._check_ma_status('SMA_10')
    def check_sma_20_status(self) -> str: return self._check_ma_status('SMA_20')
    def check_sma_30_status(self) -> str: return self._check_ma_status('SMA_30')
    def check_sma_50_status(self) -> str: return self._check_ma_status('SMA_50')
    def check_sma_100_status(self) -> str: return self._check_ma_status('SMA_100')
    def check_sma_200_status(self) -> str: return self._check_ma_status('SMA_200')
    def check_ema_10_status(self) -> str: return self._check_ma_status('EMA_10')
    def check_ema_20_status(self) -> str: return self._check_ma_status('EMA_20')
    def check_ema_30_status(self) -> str: return self._check_ma_status('EMA_30')
    def check_ema_50_status(self) -> str: return self._check_ma_status('EMA_50')
    def check_ema_100_status(self) -> str: return self._check_ma_status('EMA_100')
    def check_ema_200_status(self) -> str: return self._check_ma_status('EMA_200')
    def check_hma_status(self) -> str: return self._check_ma_status(f'HMA_{HMA_PERIOD}')
    def check_vwma_status(self) -> str: return self._check_ma_status(f'VWMA_{VWMA_PERIOD}')

    def check_ma_crossover_50_200(self) -> str:
        if 'SMA_50' not in self.df.columns: return "Pending"
        cross = self._crossed(self.df['SMA_50'], self.df['SMA_200'])
        if cross == 1: return "Golden Cross (Bullish)"
        if cross == -1: return "Death Cross (Bearish)"
        if self.df['SMA_50'].iloc[-1] > self.df['SMA_200'].iloc[-1]: return "Golden Alignment"
        return "Death Alignment"

    def check_price_cross_sma_20(self) -> str:
        if 'SMA_20' not in self.df.columns: return "Pending"
        cross = self._crossed(self.df['Close'], self.df['SMA_20'])
        if cross == 1: return "Crossed Above"
        if cross == -1: return "Crossed Below"
        return "No Crossover"

    def check_rsi_status(self) -> str:
        if 'RSI' not in self.df.columns: return "Pending"
        self._record_series(self.df['RSI'])
        rsi = self.df['RSI'].iloc[-1]
        if rsi > RSI_OVERBOUGHT: return "Overbought"
        if rsi < RSI_OVERSOLD: return "Oversold"
        return "Neutral"

    def check_rsi_trend(self) -> str:
        if 'RSI' not in self.df.columns: return "Pending"
        self._record_series(self.df['RSI'])
        return "Rising" if self._is_rising(self.df['RSI']) else "Falling"

    def check_cci_status(self) -> str:
        if 'CCI' not in self.df.columns: return "Pending"
        self._record_series(self.df['CCI'])
        cci = self.df['CCI'].iloc[-1]
        if cci > CCI_OVERBOUGHT: return "Overbought"
        if cci < CCI_OVERSOLD: return "Oversold"
        return "Buy" if cci > 0 else "Sell"

    def check_mfi_status(self) -> str:
        if 'MFI' not in self.df.columns: return "Pending"
        self._record_series(self.df['MFI'])
        mfi = self.df['MFI'].iloc[-1]
        if mfi > MFI_OVERBOUGHT: return "Overbought"
        if mfi < MFI_OVERSOLD: return "Oversold"
        return "Neutral"

    def check_stoch_status(self) -> str:
        if 'STOCH_K' not in self.df.columns: return "Pending"
        self._record_series(self.df['STOCH_K'])
        k = self.df['STOCH_K'].iloc[-1]
        if k > STOCH_OVERBOUGHT: return "Overbought"
        if k < STOCH_OVERSOLD: return "Oversold"
        return "Neutral"

    def check_willr_status(self) -> str:
        if 'WILLR' not in self.df.columns: return "Pending"
        self._record_series(self.df['WILLR'])
        wr = self.df['WILLR'].iloc[-1]
        if wr > WILLR_OVERBOUGHT: return "Overbought"
        if wr < WILLR_OVERSOLD: return "Oversold"
        return "Neutral"

    def check_ao_status(self) -> str:
        if 'AO' not in self.df.columns: return "Pending"
        self._record_series(self.df['AO'])
        return "Buy" if self.df['AO'].iloc[-1] > 0 else "Sell"

    def check_stochrsi_status(self) -> str:
        if 'STOCHRSI_K' not in self.df.columns: return "Pending"
        self._record_series(self.df['STOCHRSI_K'])
        k = self.df['STOCHRSI_K'].iloc[-1]
        if k > 80: return "Overbought"
        if k < 20: return "Oversold"
        return "Neutral"

    def check_bbp_status(self) -> str:
        if 'BULL_BEAR_POWER' not in self.df.columns: return "Pending"
        self._record_series(self.df['BULL_BEAR_POWER'])
        return "Buy" if self.df['BULL_BEAR_POWER'].iloc[-1] > 0 else "Sell"

    def check_ultosc_status(self) -> str:
        if 'UO' not in self.df.columns: return "Pending"
        self._record_series(self.df['UO'])
        u = self.df['UO'].iloc[-1]
        if u > 70: return "Overbought"
        if u < 30: return "Oversold"
        return "Neutral"

    def check_macd_status(self) -> str:
        if 'MACD_LINE' not in self.df.columns: return "Pending"
        line = self.df['MACD_LINE'].iloc[-1]
        sig = self.df['MACD_SIGNAL'].iloc[-1]
        self._record_series(self.df['MACD_LINE'])
        return "Buy" if line > sig else "Sell"

    def check_adx_status(self) -> str:
        if 'ADX' not in self.df.columns: return "Pending"
        self._record_series(self.df['ADX'])
        adx = self.df['ADX'].iloc[-1]
        if adx < ADX_STRONG_TREND: return "Neutral"
        return "Buy" if self.df['PLUS_DI'].iloc[-1] > self.df['MINUS_DI'].iloc[-1] else "Sell"

    def check_supertrend_status(self) -> str:
        if 'SUPERTREND_DIR' not in self.df.columns: return "Pending"
        if 'SUPERTREND' in self.df.columns: self._record_series(self.df['SUPERTREND'])
        return "Buy" if self.df['SUPERTREND_DIR'].iloc[-1] == 1 else "Sell"

    def check_psar_status(self) -> str:
        if 'PSAR' not in self.df.columns: return "Pending"
        self._record_series(self.df['PSAR'])
        return "Buy" if self.df['Close'].iloc[-1] > self.df['PSAR'].iloc[-1] else "Sell"

    def check_bb_status(self) -> str:
        if 'BB_UPPER' not in self.df.columns: return "Pending"
        self._record_series(self.df['BB_UPPER']) # Just record one
        c = self.df['Close'].iloc[-1]
        if c > self.df['BB_UPPER'].iloc[-1]: return "Above Upper Band"
        if c < self.df['BB_LOWER'].iloc[-1]: return "Below Lower Band"
        return "Within Bands"

    def check_bb_width(self) -> str:
        if 'BB_WIDTH' not in self.df.columns: return "Pending"
        self._record_series(self.df['BB_WIDTH'])
        return "Neutral" # Descriptive

    def check_ichimoku_cloud(self) -> str:
        if 'SPAN_A' not in self.df.columns: return "Pending"
        self._record_series(self.df['SPAN_A'])
        c = self.df['Close'].iloc[-1]
        mx = max(self.df['SPAN_A'].iloc[-1], self.df['SPAN_B'].iloc[-1])
        mn = min(self.df['SPAN_A'].iloc[-1], self.df['SPAN_B'].iloc[-1])
        if c > mx: return "Above Cloud"
        if c < mn: return "Below Cloud"
        return "Inside Cloud"

    def check_ichimoku_base(self) -> str:
        if 'KIJUN' not in self.df.columns: return "Pending"
        self._record_series(self.df['KIJUN'])
        return "Neutral"

    def check_ichimoku_tk(self) -> str:
        if 'TENKAN' not in self.df.columns: return "Pending"
        cross = self._crossed(self.df['TENKAN'], self.df['KIJUN'])
        if cross == 1: return "TK Cross (Bullish)"
        if cross == -1: return "TK Cross (Bearish)"
        return "No Cross"

    def check_beta_status(self) -> str:
        if 'BETA' not in self.df.columns: return "Pending"
        self._record_series(self.df['BETA'])
        return "Neutral"

    def _check_price_vs_level(self, col: str) -> str:
        if col not in self.df.columns: return "Pending"
        self._record_series(self.df[col])
        lvl = self.df[col].iloc[-1]
        pr = self.df['Close'].iloc[-1]
        if self._is_nearing(pr, lvl): return "Near Level"
        return "Buy" if pr > lvl else "Sell"

    # Pivots
    def check_pivot_classic_p(self): return self._check_price_vs_level('PIVOT_CLASSIC_P')
    def check_pivot_classic_r1(self): return self._check_price_vs_level('PIVOT_CLASSIC_R1')
    def check_pivot_classic_s1(self): return self._check_price_vs_level('PIVOT_CLASSIC_S1')
    def check_pivot_classic_r2(self): return self._check_price_vs_level('PIVOT_CLASSIC_R2')
    def check_pivot_classic_s2(self): return self._check_price_vs_level('PIVOT_CLASSIC_S2')
    def check_pivot_classic_r3(self): return self._check_price_vs_level('PIVOT_CLASSIC_R3')
    def check_pivot_classic_s3(self): return self._check_price_vs_level('PIVOT_CLASSIC_S3')

    def check_pivot_fib_p(self): return self._check_price_vs_level('PIVOT_FIB_P')
    def check_pivot_fib_r1(self): return self._check_price_vs_level('PIVOT_FIB_R1')
    def check_pivot_fib_s1(self): return self._check_price_vs_level('PIVOT_FIB_S1')
    def check_pivot_fib_r2(self): return self._check_price_vs_level('PIVOT_FIB_R2')
    def check_pivot_fib_s2(self): return self._check_price_vs_level('PIVOT_FIB_S2')
    def check_pivot_fib_r3(self): return self._check_price_vs_level('PIVOT_FIB_R3')
    def check_pivot_fib_s3(self): return self._check_price_vs_level('PIVOT_FIB_S3')

    def check_pivot_cam_r1(self): return self._check_price_vs_level('PIVOT_CAM_R1')
    def check_pivot_cam_r2(self): return self._check_price_vs_level('PIVOT_CAM_R2')
    def check_pivot_cam_r3(self): return self._check_price_vs_level('PIVOT_CAM_R3')
    def check_pivot_cam_r4(self): return self._check_price_vs_level('PIVOT_CAM_R4')
    def check_pivot_cam_s1(self): return self._check_price_vs_level('PIVOT_CAM_S1')
    def check_pivot_cam_s2(self): return self._check_price_vs_level('PIVOT_CAM_S2')
    def check_pivot_cam_s3(self): return self._check_price_vs_level('PIVOT_CAM_S3')
    def check_pivot_cam_s4(self): return self._check_price_vs_level('PIVOT_CAM_S4')

    def check_pivot_woodie_p(self): return self._check_price_vs_level('PIVOT_WOODIE_P')
    def check_pivot_woodie_r1(self): return self._check_price_vs_level('PIVOT_WOODIE_R1')
    def check_pivot_woodie_s1(self): return self._check_price_vs_level('PIVOT_WOODIE_S1')
    def check_pivot_woodie_r2(self): return self._check_price_vs_level('PIVOT_WOODIE_R2')
    def check_pivot_woodie_s2(self): return self._check_price_vs_level('PIVOT_WOODIE_S2')
    def check_pivot_woodie_r3(self): return self._check_price_vs_level('PIVOT_WOODIE_R3')
    def check_pivot_woodie_s3(self): return self._check_price_vs_level('PIVOT_WOODIE_S3')

    def check_pivot_demark_p(self): return self._check_price_vs_level('PIVOT_DEMARK_P')
    def check_pivot_demark_r1(self): return self._check_price_vs_level('PIVOT_DEMARK_R1')
    def check_pivot_demark_s1(self): return self._check_price_vs_level('PIVOT_DEMARK_S1')

    # ------------------------------------------------------------------
    # Orchestrator (GROUP BY CATEGORY)
    # ------------------------------------------------------------------
    def run_all(self) -> Dict[str, Dict[str, Any]]:
        """
        Returns a dictionary where keys are CATEGORY names.
        Value is a dict: {'signal': 'Buy', 'scans': [list of detailed scans]}
        """
        # 1. Group scans by category
        grouped_scans: Dict[str, List[Dict[str, Any]]] = {}
        
        for definition in self.SCANS:
            method = getattr(self, definition.name)
            self._current_value = None
            self._current_min = None
            self._current_max = None
            try:
                result_text = method()
            except Exception:
                result_text = "Pending"
            
            action = self._map_status_to_action(result_text)
            
            payload = {
                "label": definition.label,
                "status": result_text,
                "value": self._current_value,
                "min_value": self._current_min,
                "max_value": self._current_max,
                "action": action
            }
            
            grouped_scans.setdefault(definition.category, []).append(payload)

        # 2. Calculate Signal per Category
        final_results = {}
        for category, scans in grouped_scans.items():
            category_signal = self._calculate_category_signal(scans)
            final_results[category] = {
                "signal": category_signal,
                "scans": scans
            }
            
        return final_results