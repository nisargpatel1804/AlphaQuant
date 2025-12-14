"""
Core Logic Module for Technical Scans (Refactored).
Implements mutually exclusive checks to determine the specific state of indicators.
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass

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
    BETA_HIGH_THRESHOLD, BETA_LOW_THRESHOLD
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
        
        # Moving Averages (Price vs MA)
        ("check_sma_20_status", "Price vs SMA 20", "Simple Moving Averages"),
        ("check_sma_50_status", "Price vs SMA 50", "Simple Moving Averages"),
        ("check_sma_200_status", "Price vs SMA 200", "Simple Moving Averages"),
        ("check_ema_20_status", "Price vs EMA 20", "Exponential Moving Averages"),
        
        # Crossovers
        ("check_ma_crossover_50_200", "Golden/Death Cross", "Simple Moving Averages"),
        ("check_price_cross_sma_20", "Price Crossover SMA 20", "Simple Moving Averages"),
        
        # Oscillators
        ("check_rsi_status", "RSI Zone", "RSI"),
        ("check_rsi_trend", "RSI Trend", "RSI"),
        ("check_cci_status", "CCI Zone", "CCI"),
        ("check_mfi_status", "MFI Zone", "MFI"),
        ("check_stoch_status", "Stochastic Zone", "Stochastic"),
        ("check_willr_status", "Williams %R Zone", "Williams %R"),
        
        # Trend
        ("check_macd_status", "MACD Signal", "MACD"),
        ("check_adx_status", "ADX Trend Strength", "ADX"),
        ("check_supertrend_status", "SuperTrend Status", "SuperTrend"),
        ("check_psar_status", "Parabolic SAR", "Parabolic SAR"),
        
        # Volatility
        ("check_bb_status", "Bollinger Bands Position", "Bollinger Bands"),
        ("check_bb_width", "Bollinger Bands Width", "Bollinger Bands"),
        
        # Ichimoku
        ("check_ichimoku_cloud", "Cloud Status", "Ichimoku"),
        ("check_ichimoku_tk", "TK Cross", "Ichimoku"),
        
        # Beta
        ("check_beta_status", "Beta Status", "Beta"),
    ]
    return tuple(TechScanDefinition(*s) for s in scans)


class TechnicalScans:
    SCANS = _build_tech_scans()

    def __init__(self, daily_df: pd.DataFrame, weekly_df: pd.DataFrame):
        self.df = daily_df
        self.w_df = weekly_df
        self._current_value: Optional[float] = None

    # --- Helpers ---
    def _get_val(self, series: pd.Series, offset: int = 0) -> float:
        if len(series) < offset + 1: return np.nan
        return series.iloc[-(offset + 1)]

    def _record_value(self, val: Any) -> None:
        if isinstance(val, (int, float, np.number)):
            self._current_value = float(val)
        else:
            self._current_value = None

    def _is_rising(self, series: pd.Series, period: int = 1) -> bool:
        if len(series) < period + 1: return False
        return series.iloc[-1] > series.iloc[-(period + 1)]

    def _is_nearing(self, price: float, target: float) -> bool:
        if pd.isna(price) or pd.isna(target) or target == 0: return False
        return abs(price - target) / abs(target) * 100 <= NEARING_THRESHOLD_PCT

    def _crossed(self, series_a: pd.Series, series_b: Any) -> int:
        """Returns 1 if Crossed Above, -1 if Crossed Below, 0 otherwise."""
        if len(series_a) < 2: return 0
        curr_a, prev_a = series_a.iloc[-1], series_a.iloc[-2]
        
        if isinstance(series_b, (int, float)):
            curr_b, prev_b = series_b, series_b
        else:
            if len(series_b) < 2: return 0
            curr_b, prev_b = series_b.iloc[-1], series_b.iloc[-2]

        if pd.isna(curr_a) or pd.isna(prev_a) or pd.isna(curr_b) or pd.isna(prev_b):
            return 0

        if prev_a <= prev_b and curr_a > curr_b: return 1
        if prev_a >= prev_b and curr_a < curr_b: return -1
        return 0

    # ------------------------------------------------------------------
    # SCAN LOGIC (Mutually Exclusive)
    # ------------------------------------------------------------------

    # --- Momentum ---
    def _check_momentum(self, period_days: int) -> str:
        close = self.df['Close']
        if len(close) <= period_days + 1: return "Pending"
        
        roc = close.pct_change(period_days) * 100
        curr = roc.iloc[-1]
        self._record_value(curr)
        
        if curr > MOMENTUM_BULLISH_THRESHOLD: return "Bullish Zone"
        if curr < MOMENTUM_BEARISH_THRESHOLD: return "Bearish Zone"
        return "Neutral Zone"

    def check_momentum_1m(self) -> str: return self._check_momentum(21)
    def check_momentum_3m(self) -> str: return self._check_momentum(63)
    def check_momentum_6m(self) -> str: return self._check_momentum(126)

    # --- Moving Averages ---
    def _check_ma_status(self, col_name: str) -> str:
        if col_name not in self.df.columns: return "Pending"
        ma = self.df[col_name].iloc[-1]
        price = self.df['Close'].iloc[-1]
        self._record_value(ma)
        
        if self._is_nearing(price, ma): return f"Near Support/Res"
        if price > ma: return "Above (Bullish)"
        return "Below (Bearish)"

    def check_sma_20_status(self) -> str: return self._check_ma_status('SMA_20')
    def check_sma_50_status(self) -> str: return self._check_ma_status('SMA_50')
    def check_sma_200_status(self) -> str: return self._check_ma_status('SMA_200')
    def check_ema_20_status(self) -> str: return self._check_ma_status('EMA_20')

    def check_ma_crossover_50_200(self) -> str:
        if 'SMA_50' not in self.df.columns or 'SMA_200' not in self.df.columns: return "Pending"
        cross = self._crossed(self.df['SMA_50'], self.df['SMA_200'])
        if cross == 1: return "Golden Cross (Bullish)"
        if cross == -1: return "Death Cross (Bearish)"
        
        # State check if no cross
        if self.df['SMA_50'].iloc[-1] > self.df['SMA_200'].iloc[-1]: return "Golden Alignment"
        return "Death Alignment"

    def check_price_cross_sma_20(self) -> str:
        if 'SMA_20' not in self.df.columns: return "Pending"
        cross = self._crossed(self.df['Close'], self.df['SMA_20'])
        if cross == 1: return "Crossed Above"
        if cross == -1: return "Crossed Below"
        return "No Crossover"

    # --- Oscillators ---
    def check_rsi_status(self) -> str:
        if 'RSI' not in self.df.columns: return "Pending"
        rsi = self.df['RSI'].iloc[-1]
        self._record_value(rsi)
        
        if rsi > RSI_OVERBOUGHT: return "Overbought"
        if rsi < RSI_OVERSOLD: return "Oversold"
        if rsi > RSI_BULLISH_ZONE: return "Bullish Zone"
        return "Bearish Zone"

    def check_rsi_trend(self) -> str:
        if 'RSI' not in self.df.columns: return "Pending"
        return "Rising" if self._is_rising(self.df['RSI']) else "Falling"

    def check_cci_status(self) -> str:
        if 'CCI' not in self.df.columns: return "Pending"
        cci = self.df['CCI'].iloc[-1]
        self._record_value(cci)
        
        if cci > CCI_OVERBOUGHT: return "Overbought"
        if cci < CCI_OVERSOLD: return "Oversold"
        if cci > 0: return "Bullish"
        return "Bearish"

    def check_mfi_status(self) -> str:
        if 'MFI' not in self.df.columns: return "Pending"
        mfi = self.df['MFI'].iloc[-1]
        self._record_value(mfi)
        
        if mfi > MFI_OVERBOUGHT: return "Overbought"
        if mfi < MFI_OVERSOLD: return "Oversold"
        if mfi > 50: return "Bullish"
        return "Bearish"

    def check_stoch_status(self) -> str:
        if 'STOCH_K' not in self.df.columns: return "Pending"
        k = self.df['STOCH_K'].iloc[-1]
        self._record_value(k)
        
        if k > STOCH_OVERBOUGHT: return "Overbought"
        if k < STOCH_OVERSOLD: return "Oversold"
        return "Neutral"

    def check_willr_status(self) -> str:
        if 'WILLR' not in self.df.columns: return "Pending"
        wr = self.df['WILLR'].iloc[-1]
        self._record_value(wr)
        
        if wr > WILLR_OVERBOUGHT: return "Overbought"
        if wr < WILLR_OVERSOLD: return "Oversold"
        return "Neutral"

    # --- Trend ---
    def check_macd_status(self) -> str:
        if 'MACD_LINE' not in self.df.columns: return "Pending"
        line = self.df['MACD_LINE'].iloc[-1]
        signal = self.df['MACD_SIGNAL'].iloc[-1]
        
        cross = self._crossed(self.df['MACD_LINE'], self.df['MACD_SIGNAL'])
        if cross == 1: return "Bullish Crossover"
        if cross == -1: return "Bearish Crossover"
        
        if line > signal and line > 0: return "Strong Bullish"
        if line > signal: return "Bullish"
        if line < signal and line < 0: return "Strong Bearish"
        return "Bearish"

    def check_adx_status(self) -> str:
        if 'ADX' not in self.df.columns: return "Pending"
        adx = self.df['ADX'].iloc[-1]
        pdi = self.df['PLUS_DI'].iloc[-1]
        mdi = self.df['MINUS_DI'].iloc[-1]
        self._record_value(adx)
        
        trend_str = "Strong Trend" if adx > ADX_STRONG_TREND else "Weak Trend"
        direction = "Bullish" if pdi > mdi else "Bearish"
        return f"{direction} ({trend_str})"

    def check_supertrend_status(self) -> str:
        if 'SUPERTREND_DIR' not in self.df.columns: return "Pending"
        direction = self.df['SUPERTREND_DIR'].iloc[-1] # 1=Buy, -1=Sell
        
        # Check cross
        prev = self.df['SUPERTREND_DIR'].iloc[-2]
        if prev != direction:
            return "Buy Signal" if direction == 1 else "Sell Signal"
            
        return "Bullish" if direction == 1 else "Bearish"

    def check_psar_status(self) -> str:
        if 'PSAR' not in self.df.columns: return "Pending"
        close = self.df['Close'].iloc[-1]
        psar = self.df['PSAR'].iloc[-1]
        self._record_value(psar)
        
        if self._crossed(self.df['Close'], self.df['PSAR']) == 1: return "Bullish Reversal"
        if self._crossed(self.df['Close'], self.df['PSAR']) == -1: return "Bearish Reversal"
        
        return "Bullish" if close > psar else "Bearish"

    # --- Volatility ---
    def check_bb_status(self) -> str:
        if 'BB_UPPER' not in self.df.columns: return "Pending"
        close = self.df['Close'].iloc[-1]
        upper = self.df['BB_UPPER'].iloc[-1]
        lower = self.df['BB_LOWER'].iloc[-1]
        
        if close > upper: return "Above Upper Band"
        if close < lower: return "Below Lower Band"
        return "Within Bands"

    def check_bb_width(self) -> str:
        if 'BB_WIDTH' not in self.df.columns: return "Pending"
        w = self.df['BB_WIDTH']
        curr = w.iloc[-1]
        
        # Check history for squeeze
        if len(w) > 30:
            hist = w.iloc[-30:]
            if curr <= np.percentile(hist, BB_SQUEEZE_PERCENTILE): return "Squeeze"
            if curr >= np.percentile(hist, BB_EXPANSION_PERCENTILE): return "Expansion"
        return "Normal"

    # --- Ichimoku ---
    def check_ichimoku_cloud(self) -> str:
        if 'SPAN_A' not in self.df.columns: return "Pending"
        close = self.df['Close'].iloc[-1]
        a = self.df['SPAN_A'].iloc[-1]
        b = self.df['SPAN_B'].iloc[-1]
        
        if close > max(a, b): return "Above Cloud (Bullish)"
        if close < min(a, b): return "Below Cloud (Bearish)"
        return "Inside Cloud (Neutral)"

    def check_ichimoku_tk(self) -> str:
        if 'TENKAN' not in self.df.columns: return "Pending"
        cross = self._crossed(self.df['TENKAN'], self.df['KIJUN'])
        if cross == 1: return "TK Cross (Bullish)"
        if cross == -1: return "TK Cross (Bearish)"
        return "No Cross"

    # --- Beta ---
    def check_beta_status(self) -> str:
        if 'BETA' not in self.df.columns: return "Pending"
        beta = self.df['BETA'].iloc[-1]
        self._record_value(beta)
        if pd.isna(beta): return "Pending"
        
        if beta > 1.5: return "High Beta"
        if beta < 0.5: return "Low Beta"
        return "Moderate Beta"

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------
    def run_all(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Executes all defined checks.
        Returns dictionary grouped by classification: Bullish, Bearish, Neutral, Pending.
        """
        results: Dict[str, List[Dict[str, Any]]] = {
            "Bullish": [],
            "Bearish": [],
            "Neutral": [],
            "Pending": []
        }
        
        for definition in self.SCANS:
            method = getattr(self, definition.name)
            self._current_value = None
            try:
                result_text = method()
            except Exception:
                result_text = "Pending"
            
            payload = {
                "label": definition.label,
                "category": definition.category,
                "status": result_text,
                "value": self._current_value
            }

            # Map result string to bucket
            txt = result_text.lower()
            bucket = "Neutral"
            
            if "pending" in txt or "missing" in txt:
                bucket = "Pending"
            elif any(x in txt for x in ["bullish", "buy", "golden", "above upper", "rising", "positive", "expansion", "support"]):
                bucket = "Bullish"
                # Overbought is tricky; usually implies strength but also caution. 
                # StockEdge treats overbought as a 'Bullish' scan category generally.
                if "overbought" in txt: bucket = "Bullish"
            elif any(x in txt for x in ["bearish", "sell", "death", "below lower", "falling", "negative", "resistance"]):
                bucket = "Bearish"
                if "oversold" in txt: bucket = "Bearish"
            
            # Specific overrides
            if "squeeze" in txt: bucket = "Neutral" # Consolidation
            if "high beta" in txt: bucket = "Neutral" # High vol isn't necessarily bullish
            
            results[bucket].append(payload)

        return results