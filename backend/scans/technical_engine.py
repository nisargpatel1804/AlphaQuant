# backend/scans/technical_scanner.py

"""
AlphaQuant Unified Technical & Market Data Scanner
Consolidated master engine:
- Fetches 10-year OHLCV data via yfinance once per stock.
- Fetches Benchmark (^NSEI) for Beta and Relative Strength calculations.
- Resamples to Daily (1d), Weekly (1w), and Monthly (1m) timeframes.
- Calculates comprehensive Indicators, Price Action Breakouts, Returns, 
  Relative Strength, and Volume Analysis without truncation.
- Evaluates 27 symmetrically paired Candlestick patterns fractally across 1d, 1w, and 1m.
- Outputs self-describing JSON with parameters, thresholds, raw values, and status.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import yfinance as yf

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("TechnicalScanner")

# ==============================================================================
# 1. CONFIGURATION & PATHS
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output" / "data"
SOURCE_DIR = BASE_DIR / "source"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NIFTY_500_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
BENCHMARK_TICKER = "^NSEI"

# Lookbacks & Thresholds
FETCH_HISTORY_DURATION = "10y"
FETCH_INTERVAL = "1d"

# Timeframe-specific Moving Average Matrices
D_MA_PERIODS = [9, 10, 20, 21, 30, 50, 63, 100, 126, 200, 252]
W_MA_PERIODS = [4, 13, 26, 40, 52, 104]
M_MA_PERIODS = [3, 6, 10, 24, 36, 60]

VWMA_PERIOD = 20
HMA_PERIOD = 9

# Candle Thresholds
DOJI_BODY_THRESHOLD = 0.03
MARUBOZU_SHADOW_THRESHOLD = 0.05
HAMMER_SHADOW_MULTIPLIER = 2.0
HAMMER_UPPER_SHADOW_LIMIT = 0.1
LONG_BODY_MULTIPLIER = 1.5
AVG_BODY_PERIOD = 10

# Return Lookbacks (in daily trading bars)
RETURN_PERIODS = {
    "1W": 5, "1M": 21, "3M": 63, "6M": 126, "1Y": 252,
    "2Y": 504, "3Y": 756, "5Y": 1260, "7Y": 1764, "10Y": 2520
}

# ==============================================================================
# 2. UTILITY HELPERS
# ==============================================================================
def safe_round(val: Any, decimals: int = 2) -> Optional[float]:
    if val is None or pd.isna(val) or np.isinf(val):
        return None
    try:
        return round(float(val), decimals)
    except (ValueError, TypeError):
        return None

def load_master_industry_map() -> List[Dict[str, Any]]:
    path = SOURCE_DIR / "master_industry_map.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

def get_industry_for_ticker(ticker: str, master_map: List[Dict[str, Any]]) -> Optional[str]:
    target = ticker.strip().upper()
    for entry in master_map:
        if target in [str(t).strip().upper() for t in entry.get("stocks", [])]:
            return entry.get("industry")
    return None

def get_nifty_tickers(retries: int = 4) -> List[str]:
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
    ]
    sess = requests.Session()
    for attempt in range(1, retries + 1):
        try:
            resp = sess.get(NIFTY_500_URL, timeout=30, headers={"User-Agent": random.choice(user_agents)})
            resp.raise_for_status()
            reader = csv.DictReader(resp.content.decode("utf-8", errors="replace").splitlines())
            return [row["Symbol"].strip().upper() for row in reader if row.get("Symbol")]
        except requests.RequestException:
            if attempt == retries:
                break
            time.sleep(1.5 * attempt)

    fallback = SOURCE_DIR / "ind_nifty500list.csv"
    if fallback.exists():
        with open(fallback, "r", encoding="utf-8") as f:
            return [row["Symbol"].strip().upper() for row in csv.DictReader(f) if row.get("Symbol")]
    return []

# ==============================================================================
# 3. UNIFIED DATA FETCHER
# ==============================================================================
class UnifiedDataFetcher:
    _benchmark_cache: Optional[pd.Series] = None

    @classmethod
    def fetch_stock_data(cls, ticker: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        symbol = f"{ticker.strip().upper()}.NS" if not ticker.endswith((".NS", ".BO")) else ticker
        df = pd.DataFrame()

        for _ in range(2):
            try:
                df = yf.download(symbol, period=FETCH_HISTORY_DURATION, interval=FETCH_INTERVAL, auto_adjust=True, progress=False, threads=False)
                if not df.empty:
                    break
            except Exception:
                time.sleep(1.5)

        if df.empty and symbol.endswith(".NS"):
            try:
                df = yf.download(symbol.replace(".NS", ".BO"), period=FETCH_HISTORY_DURATION, interval=FETCH_INTERVAL, auto_adjust=True, progress=False, threads=False)
            except Exception:
                pass

        if df.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        col_map = {'Adj Close': 'Close', 'adj close': 'Close', 'close': 'Close', 'open': 'Open', 'high': 'High', 'low': 'Low', 'volume': 'Volume'}
        df.rename(columns=col_map, inplace=True)
        df.columns = [c.capitalize() if isinstance(c, str) else c for c in df.columns]

        required = {'Open', 'High', 'Low', 'Close', 'Volume'}
        if not required.issubset(df.columns):
            if 'Volume' in (required - set(df.columns)):
                df['Volume'] = 0
            else:
                return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        weekly_df = cls._resample(df, 'W-FRI')
        monthly_df = cls._resample(df, 'ME')

        return df, weekly_df, monthly_df

    @classmethod
    def fetch_benchmark(cls) -> pd.Series:
        if cls._benchmark_cache is not None:
            return cls._benchmark_cache
        try:
            df = yf.download(BENCHMARK_TICKER, period="2y", interval="1d", auto_adjust=True, progress=False, threads=False)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                col = df['Close'] if 'Close' in df.columns else df['Adj Close']
                cls._benchmark_cache = col.iloc[:, 0] if isinstance(col, pd.DataFrame) else col
                return cls._benchmark_cache
        except Exception as e:
            logger.error(f"Error fetching benchmark: {e}")
        return pd.Series(dtype=float)

    @staticmethod
    def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
        agg_dict = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}
        agg_to_use = {k: v for k, v in agg_dict.items() if k in df.columns}
        try:
            resampled = df.resample(rule).agg(agg_to_use).dropna(subset=['Close'])
            return resampled
        except Exception:
            if rule == 'ME':
                return df.resample('M').agg(agg_to_use).dropna(subset=['Close'])
            return pd.DataFrame()

# ==============================================================================
# 4. TECHNICAL INDICATORS ENGINE (1D, 1W, 1M)
# ==============================================================================
class TechnicalIndicatorsEngine:
    def __init__(self, df: pd.DataFrame, timeframe: str):
        self.df = df.copy()
        self.tf = timeframe
        self.c = self.df['Close']
        self.h = self.df['High']
        self.l = self.df['Low']
        self.o = self.df['Open']
        self.v = self.df['Volume']
        self.price = float(self.c.iloc[-1]) if not self.c.empty else 0.0

    # --- Math Helpers ---
    @staticmethod
    def _wma(series: pd.Series, length: int) -> pd.Series:
        if length <= 0 or len(series) < length:
            return pd.Series(index=series.index, dtype=float)
        weights = np.arange(1, length + 1, dtype=float)
        def _apply(x: np.ndarray) -> float:
            return float(np.dot(x, weights) / weights.sum()) if x.size == length and np.all(np.isfinite(x)) else np.nan
        return series.rolling(window=length, min_periods=length).apply(_apply, raw=True)

    @classmethod
    def _hma(cls, series: pd.Series, length: int) -> pd.Series:
        if length <= 0:
            return pd.Series(index=series.index, dtype=float)
        raw = 2 * cls._wma(series, max(int(length / 2), 1)) - cls._wma(series, length)
        return cls._wma(raw, max(int(np.sqrt(length)), 1))

    @staticmethod
    def _rsi(series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain = delta.where(delta > 0, 0).ewm(alpha=1/period, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
        return 100 - (100 / (1 + (gain / loss.replace(0, np.nan))))

    # --- Calculations ---
    def calculate_moving_averages(self, ma_periods: List[int]) -> Dict[str, Any]:
        results = {}
        for p in ma_periods:
            if len(self.c) >= p:
                sma_val = safe_round(self.c.rolling(p).mean().iloc[-1])
                ema_val = safe_round(self.c.ewm(span=p, adjust=False).mean().iloc[-1])

                if sma_val is not None:
                    dist_sma = safe_round(((self.price - sma_val) / sma_val) * 100)
                    results[f"SMA_{p}"] = {
                        "name": f"Simple Moving Average ({p})",
                        "timeframe": self.tf,
                        "parameters": {"period": p},
                        "value": sma_val,
                        "distance_pct": dist_sma,
                        "status": "Above MA" if self.price > sma_val else "Below MA"
                    }

                if ema_val is not None:
                    dist_ema = safe_round(((self.price - ema_val) / ema_val) * 100)
                    results[f"EMA_{p}"] = {
                        "name": f"Exponential Moving Average ({p})",
                        "timeframe": self.tf,
                        "parameters": {"period": p},
                        "value": ema_val,
                        "distance_pct": dist_ema,
                        "status": "Above MA" if self.price > ema_val else "Below MA"
                    }

        # VWMA & HMA
        if len(self.c) >= VWMA_PERIOD and self.v.sum() > 0:
            pv = self.c * self.v
            v_sum = self.v.rolling(VWMA_PERIOD).sum().replace(0, np.nan)
            vwma = safe_round((pv.rolling(VWMA_PERIOD).sum() / v_sum).iloc[-1])
            if vwma is not None:
                results[f"VWMA_{VWMA_PERIOD}"] = {
                    "name": f"Volume Weighted Moving Average ({VWMA_PERIOD})",
                    "timeframe": self.tf,
                    "parameters": {"period": VWMA_PERIOD},
                    "value": vwma,
                    "distance_pct": safe_round(((self.price - vwma) / vwma) * 100),
                    "status": "Above MA" if self.price > vwma else "Below MA"
                }

        if len(self.c) >= HMA_PERIOD:
            hma = safe_round(self._hma(self.c, HMA_PERIOD).iloc[-1])
            if hma is not None:
                results[f"HMA_{HMA_PERIOD}"] = {
                    "name": f"Hull Moving Average ({HMA_PERIOD})",
                    "timeframe": self.tf,
                    "parameters": {"period": HMA_PERIOD},
                    "value": hma,
                    "distance_pct": safe_round(((self.price - hma) / hma) * 100),
                    "status": "Above MA" if self.price > hma else "Below MA"
                }

        return results

    def calculate_oscillators(self) -> Dict[str, Any]:
        results = {}

        # 1. Dual-Speed RSI (14 & 9)
        for r_p in [14, 9]:
            if len(self.c) >= r_p + 1:
                rsi_series = self._rsi(self.c, r_p)
                rsi_val = safe_round(rsi_series.iloc[-1])
                trend = "Rising" if rsi_series.iloc[-1] > rsi_series.iloc[-2] else "Falling"
                status = "Overbought" if rsi_val > 70 else "Oversold" if rsi_val < 30 else "Neutral"
                results[f"RSI_{r_p}"] = {
                    "name": f"Relative Strength Index ({r_p})",
                    "timeframe": self.tf,
                    "parameters": {"period": r_p},
                    "thresholds": {"overbought": 70, "oversold": 30},
                    "value": rsi_val,
                    "trend": trend,
                    "status": status
                }

        # 2. Stochastic (14, 3, 3)
        if len(self.c) >= 17:
            low_14 = self.l.rolling(14).min()
            high_14 = self.h.rolling(14).max()
            k_fast = 100 * (self.c - low_14) / (high_14 - low_14).replace(0, np.nan)
            k = k_fast.rolling(3).mean()
            d = k.rolling(3).mean()
            k_val, d_val = safe_round(k.iloc[-1]), safe_round(d.iloc[-1])
            status = "Overbought" if (k_val or 0) > 80 else "Oversold" if (k_val or 0) < 20 else "Neutral"
            results["Stochastic"] = {
                "name": "Stochastic Oscillator",
                "timeframe": self.tf,
                "parameters": {"k_period": 14, "k_smoothing": 3, "d_period": 3},
                "thresholds": {"overbought": 80, "oversold": 20},
                "values": {"k": k_val, "d": d_val},
                "status": status
            }

        # 3. Commodity Channel Index (CCI 20)
        if len(self.c) >= 20:
            tp = (self.h + self.l + self.c) / 3
            tp_sma = tp.rolling(20).mean()
            mad = tp.rolling(20).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
            cci = (tp - tp_sma) / (0.015 * mad.replace(0, np.nan))
            cci_val = safe_round(cci.iloc[-1])
            status = "Overbought" if (cci_val or 0) > 100 else "Oversold" if (cci_val or 0) < -100 else "Neutral"
            results["CCI_20"] = {
                "name": "Commodity Channel Index (20)",
                "timeframe": self.tf,
                "parameters": {"period": 20},
                "thresholds": {"overbought": 100, "oversold": -100},
                "value": cci_val,
                "status": status
            }

        # 4. Money Flow Index (MFI 14)
        if len(self.c) >= 15:
            tp = (self.h + self.l + self.c) / 3
            raw_mf = tp * self.v
            pos_mf = raw_mf.where(tp > tp.shift(1), 0).rolling(14).sum()
            neg_mf = raw_mf.where(tp < tp.shift(1), 0).rolling(14).sum()
            mfr = pos_mf / neg_mf.replace(0, np.nan)
            mfi = 100 - (100 / (1 + mfr))
            mfi_val = safe_round(mfi.iloc[-1])
            status = "Overbought" if (mfi_val or 0) > 80 else "Oversold" if (mfi_val or 0) < 20 else "Neutral"
            results["MFI_14"] = {
                "name": "Money Flow Index (14)",
                "timeframe": self.tf,
                "parameters": {"period": 14},
                "thresholds": {"overbought": 80, "oversold": 20},
                "value": mfi_val,
                "status": status
            }

        # 5. Williams %R (14)
        if len(self.c) >= 14:
            hh = self.h.rolling(14).max()
            ll = self.l.rolling(14).min()
            willr = -100 * (hh - self.c) / (hh - ll).replace(0, np.nan)
            willr_val = safe_round(willr.iloc[-1])
            status = "Overbought" if (willr_val or -50) > -20 else "Oversold" if (willr_val or -50) < -80 else "Neutral"
            results["Williams_R_14"] = {
                "name": "Williams %R (14)",
                "timeframe": self.tf,
                "parameters": {"period": 14},
                "thresholds": {"overbought": -20, "oversold": -80},
                "value": willr_val,
                "status": status
            }

        # 6. Rate of Change (ROC 14)
        if len(self.c) >= 15:
            roc = safe_round((self.c.pct_change(14) * 100).iloc[-1])
            results["ROC_14"] = {
                "name": "Rate of Change (14)",
                "timeframe": self.tf,
                "parameters": {"period": 14},
                "value": roc,
                "status": "Positive Momentum" if (roc or 0) > 0 else "Negative Momentum"
            }

        # 7. Awesome Oscillator (AO 5, 34)
        if len(self.c) >= 34:
            med = (self.h + self.l) / 2
            ao = safe_round((med.rolling(5).mean() - med.rolling(34).mean()).iloc[-1])
            results["Awesome_Oscillator"] = {
                "name": "Awesome Oscillator",
                "timeframe": self.tf,
                "parameters": {"fast_period": 5, "slow_period": 34},
                "value": ao,
                "status": "Bullish" if (ao or 0) > 0 else "Bearish"
            }

        # 8. Momentum (10)
        if len(self.c) >= 11:
            mom = safe_round((self.c - self.c.shift(10)).iloc[-1])
            results["Momentum_10"] = {
                "name": "Momentum (10)",
                "timeframe": self.tf,
                "parameters": {"period": 10},
                "value": mom,
                "status": "Bullish" if (mom or 0) > 0 else "Bearish"
            }

        # 9. Bull / Bear Power (13)
        if len(self.c) >= 13:
            ema13 = self.c.ewm(span=13, adjust=False).mean()
            bbp = safe_round(((self.h - ema13) + (self.l - ema13)).iloc[-1])
            results["Bull_Bear_Power"] = {
                "name": "Bull Bear Power",
                "timeframe": self.tf,
                "parameters": {"period": 13},
                "value": bbp,
                "status": "Bullish" if (bbp or 0) > 0 else "Bearish"
            }

        return results

    def calculate_trend_and_volatility(self) -> Dict[str, Any]:
        results = {}

        # 1. MACD (12, 26, 9)
        if len(self.c) >= 35:
            fast_ema = self.c.ewm(span=12, adjust=False).mean()
            slow_ema = self.c.ewm(span=26, adjust=False).mean()
            macd_line = fast_ema - slow_ema
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            hist = macd_line - signal_line

            m_val = safe_round(macd_line.iloc[-1])
            s_val = safe_round(signal_line.iloc[-1])
            h_val = safe_round(hist.iloc[-1])

            prev_m = macd_line.iloc[-2]
            prev_s = signal_line.iloc[-2]

            if prev_m <= prev_s and macd_line.iloc[-1] > signal_line.iloc[-1]:
                status = "Bullish Crossover"
            elif prev_m >= prev_s and macd_line.iloc[-1] < signal_line.iloc[-1]:
                status = "Bearish Crossover"
            else:
                status = "Bullish Alignment" if m_val > s_val else "Bearish Alignment"

            results["MACD"] = {
                "name": "Moving Average Convergence Divergence",
                "timeframe": self.tf,
                "parameters": {"fast_period": 12, "slow_period": 26, "signal_period": 9},
                "values": {"macd_line": m_val, "signal_line": s_val, "histogram": h_val},
                "status": status
            }

        # 2. ADX & Directional Movement (14)
        if len(self.c) >= 28:
            up_move = self.h - self.h.shift(1)
            down_move = self.l.shift(1) - self.l
            plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
            minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

            prev_close = self.c.shift(1)
            tr = np.maximum(self.h - self.l, np.maximum((self.h - prev_close).abs(), (self.l - prev_close).abs()))

            alpha = 1.0 / 14
            tr_s = pd.Series(tr, index=self.df.index).ewm(alpha=alpha, adjust=False).mean()
            p_dm_s = pd.Series(plus_dm, index=self.df.index).ewm(alpha=alpha, adjust=False).mean()
            m_dm_s = pd.Series(minus_dm, index=self.df.index).ewm(alpha=alpha, adjust=False).mean()

            plus_di = 100 * (p_dm_s / tr_s.replace(0, np.nan))
            minus_di = 100 * (m_dm_s / tr_s.replace(0, np.nan))
            di_sum = plus_di + minus_di
            dx = 100 * (plus_di - minus_di).abs() / di_sum.replace(0, np.nan)
            adx = dx.ewm(alpha=alpha, adjust=False).mean()

            adx_val = safe_round(adx.iloc[-1])
            p_di_val = safe_round(plus_di.iloc[-1])
            m_di_val = safe_round(minus_di.iloc[-1])

            trend_status = "Strong Trend" if (adx_val or 0) >= 25 else "Weak/Ranging Trend"
            dir_status = "Bullish" if (p_di_val or 0) > (m_di_val or 0) else "Bearish"

            results["ADX_14"] = {
                "name": "Average Directional Index (14)",
                "timeframe": self.tf,
                "parameters": {"period": 14},
                "thresholds": {"strong_trend": 25, "weak_trend": 20},
                "values": {"adx": adx_val, "plus_di": p_di_val, "minus_di": m_di_val},
                "status": f"{trend_status} ({dir_status})"
            }

        # 3. ATR (14)
        if len(self.c) >= 15:
            prev_close = self.c.shift(1)
            tr = np.maximum(self.h - self.l, np.maximum((self.h - prev_close).abs(), (self.l - prev_close).abs()))
            atr_val = safe_round(pd.Series(tr, index=self.df.index).rolling(14).mean().iloc[-1])
            results["ATR_14"] = {
                "name": "Average True Range (14)",
                "timeframe": self.tf,
                "parameters": {"period": 14},
                "value": atr_val
            }

        # 4. Bollinger Bands (20, 2.0)
        if len(self.c) >= 20:
            mid = self.c.rolling(20).mean()
            std = self.c.rolling(20).std()
            upper = mid + (2.0 * std)
            lower = mid - (2.0 * std)
            width = ((upper - lower) / mid.replace(0, np.nan)) * 100

            u_val, m_val, l_val, w_val = safe_round(upper.iloc[-1]), safe_round(mid.iloc[-1]), safe_round(lower.iloc[-1]), safe_round(width.iloc[-1])
            if self.price > upper.iloc[-1]:
                status = "Above Upper Band"
            elif self.price < lower.iloc[-1]:
                status = "Below Lower Band"
            else:
                status = "Inside Bands"

            results["Bollinger_Bands"] = {
                "name": "Bollinger Bands",
                "timeframe": self.tf,
                "parameters": {"period": 20, "std_dev": 2.0},
                "values": {"upper_band": u_val, "middle_band": m_val, "lower_band": l_val, "band_width_pct": w_val},
                "status": status
            }

        # 5. Dual-Speed SuperTrend (Standard: 10, 3 | Fast: 7, 3)
        for length, mult in [(10, 3.0), (7, 3.0)]:
            st_val, st_dir = self._calculate_supertrend(length, mult)
            if st_val is not None:
                results[f"SuperTrend_{length}_{int(mult)}"] = {
                    "name": f"SuperTrend ({length}, {mult})",
                    "timeframe": self.tf,
                    "parameters": {"length": length, "multiplier": mult},
                    "value": st_val,
                    "status": "Bullish" if st_dir == 1 else "Bearish"
                }

        # 6. Parabolic SAR (0.02, 0.20)
        psar_val, psar_dir = self._calculate_psar()
        if psar_val is not None:
            results["Parabolic_SAR"] = {
                "name": "Parabolic SAR",
                "timeframe": self.tf,
                "parameters": {"af_start": 0.02, "af_max": 0.20},
                "value": psar_val,
                "status": "Bullish" if psar_dir == 1 else "Bearish"
            }

        # 7. Ichimoku Cloud (9, 26, 52, 26)
        if len(self.c) >= 52:
            tenkan = (self.h.rolling(9).max() + self.l.rolling(9).min()) / 2
            kijun = (self.h.rolling(26).max() + self.l.rolling(26).min()) / 2
            span_a = ((tenkan + kijun) / 2).shift(26)
            span_b = ((self.h.rolling(52).max() + self.l.rolling(52).min()) / 2).shift(26)

            t_val, k_val, sa_val, sb_val = safe_round(tenkan.iloc[-1]), safe_round(kijun.iloc[-1]), safe_round(span_a.iloc[-1]), safe_round(span_b.iloc[-1])

            status = "Neutral"
            if sa_val and sb_val:
                cloud_top = max(sa_val, sb_val)
                cloud_bot = min(sa_val, sb_val)
                if self.price > cloud_top:
                    status = "Above Cloud"
                elif self.price < cloud_bot:
                    status = "Below Cloud"
                else:
                    status = "Inside Cloud"

            results["Ichimoku_Cloud"] = {
                "name": "Ichimoku Cloud",
                "timeframe": self.tf,
                "parameters": {"tenkan_period": 9, "kijun_period": 26, "span_b_period": 52},
                "values": {"tenkan_sen": t_val, "kijun_sen": k_val, "senkou_span_a": sa_val, "senkou_span_b": sb_val},
                "status": status
            }

        # 8. Narrow Range (NR4 / NR7)
        if len(self.df) >= 7:
            rng = self.h - self.l
            is_nr4 = rng.iloc[-1] == rng.iloc[-4:].min()
            is_nr7 = rng.iloc[-1] == rng.iloc[-7:].min()
            nr_status = "NR7 (Narrowest in 7)" if is_nr7 else "NR4 (Narrowest in 4)" if is_nr4 else "Normal"
            results["Narrow_Range"] = {
                "name": "Narrow Range Compression",
                "timeframe": self.tf,
                "value": safe_round(rng.iloc[-1]),
                "status": nr_status
            }

        return results

    def calculate_pivots(self) -> Dict[str, Any]:
        """Calculates full 5-system multi-level pivot points from the PREVIOUS bar."""
        if len(self.df) < 2:
            return {}

        prev_h = float(self.h.iloc[-2])
        prev_l = float(self.l.iloc[-2])
        prev_c = float(self.c.iloc[-2])
        prev_o = float(self.o.iloc[-2])
        rng = prev_h - prev_l

        # Classic
        p_classic = (prev_h + prev_l + prev_c) / 3
        r1_c = 2 * p_classic - prev_l
        s1_c = 2 * p_classic - prev_h
        r2_c = p_classic + rng
        s2_c = p_classic - rng
        r3_c = prev_h + 2 * (p_classic - prev_l)
        s3_c = prev_l - 2 * (prev_h - p_classic)

        # Fibonacci
        p_fib = p_classic
        r1_f = p_fib + 0.382 * rng
        s1_f = p_fib - 0.382 * rng
        r2_f = p_fib + 0.618 * rng
        s2_f = p_fib - 0.618 * rng
        r3_f = p_fib + 1.000 * rng
        s3_f = p_fib - 1.000 * rng

        # Camarilla
        factor = 1.1
        r4_cam = prev_c + rng * factor / 2
        r3_cam = prev_c + rng * factor / 4
        r2_cam = prev_c + rng * factor / 6
        r1_cam = prev_c + rng * factor / 12
        s1_cam = prev_c - rng * factor / 12
        s2_cam = prev_c - rng * factor / 6
        s3_cam = prev_c - rng * factor / 4
        s4_cam = prev_c - rng * factor / 2

        # Woodie
        p_wood = (prev_h + prev_l + 2 * prev_c) / 4
        r1_w = 2 * p_wood - prev_l
        s1_w = 2 * p_wood - prev_h
        r2_w = p_wood + rng
        s2_w = p_wood - rng
        r3_w = prev_h + 2 * (p_wood - prev_l)
        s3_w = prev_l - 2 * (prev_h - p_wood)

        # DeMark
        if prev_c < prev_o:
            x = prev_h + 2 * prev_l + prev_c
        elif prev_c > prev_o:
            x = 2 * prev_h + prev_l + prev_c
        else:
            x = prev_h + prev_l + 2 * prev_c
        p_dm = x / 4
        r1_dm = x / 2 - prev_l
        s1_dm = x / 2 - prev_h

        return {
            "Classic": {
                "timeframe": self.tf,
                "values": {"P": safe_round(p_classic), "R1": safe_round(r1_c), "S1": safe_round(s1_c), "R2": safe_round(r2_c), "S2": safe_round(s2_c), "R3": safe_round(r3_c), "S3": safe_round(s3_c)}
            },
            "Fibonacci": {
                "timeframe": self.tf,
                "values": {"P": safe_round(p_fib), "R1": safe_round(r1_f), "S1": safe_round(s1_f), "R2": safe_round(r2_f), "S2": safe_round(s2_f), "R3": safe_round(r3_f), "S3": safe_round(s3_f)}
            },
            "Camarilla": {
                "timeframe": self.tf,
                "values": {"R4": safe_round(r4_cam), "R3": safe_round(r3_cam), "R2": safe_round(r2_cam), "R1": safe_round(r1_cam), "S1": safe_round(s1_cam), "S2": safe_round(s2_cam), "S3": safe_round(s3_cam), "S4": safe_round(s4_cam)}
            },
            "Woodie": {
                "timeframe": self.tf,
                "values": {"P": safe_round(p_wood), "R1": safe_round(r1_w), "S1": safe_round(s1_w), "R2": safe_round(r2_w), "S2": safe_round(s2_w), "R3": safe_round(r3_w), "S3": safe_round(s3_w)}
            },
            "DeMark": {
                "timeframe": self.tf,
                "values": {"P": safe_round(p_dm), "R1": safe_round(r1_dm), "S1": safe_round(s1_dm)}
            }
        }

    def _calculate_supertrend(self, length: int, multiplier: float) -> Tuple[Optional[float], int]:
        if len(self.c) < length + 1:
            return None, 1

        prev_close = self.c.shift(1)
        tr = np.maximum(self.h - self.l, np.maximum((self.h - prev_close).abs(), (self.l - prev_close).abs()))
        atr = pd.Series(tr, index=self.df.index).ewm(alpha=1/length, adjust=False).mean()

        hl2 = (self.h + self.l) / 2
        basic_upper = hl2 + (multiplier * atr)
        basic_lower = hl2 - (multiplier * atr)

        final_upper = np.zeros(len(self.df))
        final_lower = np.zeros(len(self.df))
        st_dir = np.ones(len(self.df))
        supertrend = np.zeros(len(self.df))

        c_v = self.c.values
        bu_v = basic_upper.values
        bl_v = basic_lower.values

        for i in range(1, len(self.df)):
            final_upper[i] = bu_v[i] if bu_v[i] < final_upper[i-1] or c_v[i-1] > final_upper[i-1] else final_upper[i-1]
            final_lower[i] = bl_v[i] if bl_v[i] > final_lower[i-1] or c_v[i-1] < final_lower[i-1] else final_lower[i-1]

            if st_dir[i-1] == 1:
                if c_v[i] < final_lower[i]:
                    st_dir[i] = -1
                    supertrend[i] = final_upper[i]
                else:
                    st_dir[i] = 1
                    supertrend[i] = final_lower[i]
            else:
                if c_v[i] > final_upper[i]:
                    st_dir[i] = 1
                    supertrend[i] = final_lower[i]
                else:
                    st_dir[i] = -1
                    supertrend[i] = final_upper[i]

        return safe_round(supertrend[-1]), int(st_dir[-1])

    def _calculate_psar(self) -> Tuple[Optional[float], int]:
        if len(self.df) < 5:
            return None, 1
        af = 0.02
        is_long = True
        sar = np.zeros(len(self.df))
        ep = float(self.h.iloc[0])
        sar[0] = float(self.l.iloc[0])

        h_v, l_v = self.h.values, self.l.values
        for i in range(1, len(self.df)):
            prev_sar = sar[i-1]
            if is_long:
                curr_sar = prev_sar + af * (ep - prev_sar)
                curr_sar = min(curr_sar, l_v[i-1], l_v[i-2] if i > 1 else l_v[i-1])
                if l_v[i] < curr_sar:
                    is_long = False
                    curr_sar = ep
                    ep = l_v[i]
                    af = 0.02
                else:
                    if h_v[i] > ep:
                        ep = h_v[i]
                        af = min(af + 0.02, 0.20)
            else:
                curr_sar = prev_sar + af * (ep - prev_sar)
                curr_sar = max(curr_sar, h_v[i-1], h_v[i-2] if i > 1 else h_v[i-1])
                if h_v[i] > curr_sar:
                    is_long = True
                    curr_sar = ep
                    ep = h_v[i]
                    af = 0.02
                else:
                    if l_v[i] < ep:
                        ep = l_v[i]
                        af = min(af + 0.02, 0.20)
            sar[i] = curr_sar

        return safe_round(sar[-1]), 1 if is_long else -1

# ==============================================================================
# 5. PRICE ACTION, BREAKOUTS & RELATIVE STRENGTH ENGINE
# ==============================================================================
class PriceActionEngine:
    def __init__(self, d_df: pd.DataFrame, w_df: pd.DataFrame, m_df: pd.DataFrame, bench_series: Optional[pd.Series] = None):
        self.d = d_df
        self.w = w_df
        self.m = m_df
        self.bench = bench_series
        self.price = float(self.d['Close'].iloc[-1]) if not self.d.empty else 0.0

    def calculate_returns(self) -> Dict[str, Optional[float]]:
        returns = {}
        for label, period in RETURN_PERIODS.items():
            if len(self.d) > period:
                ret = ((self.price - self.d['Close'].iloc[-(period + 1)]) / self.d['Close'].iloc[-(period + 1)]) * 100
                returns[label] = safe_round(ret)
            else:
                returns[label] = None
        return returns

    def calculate_52w_and_range(self) -> Dict[str, Any]:
        lookback = min(len(self.d), 252)
        window = self.d.iloc[-lookback:]
        h52, l52 = float(window['High'].max()), float(window['Low'].min())
        
        pos_pct = safe_round(((self.price - l52) / (h52 - l52)) * 100) if h52 != l52 else 50.0
        rise_pct = safe_round(((self.price - l52) / l52) * 100) if l52 > 0 else 0.0
        fall_pct = safe_round(((h52 - self.price) / h52) * 100) if h52 > 0 else 0.0

        return {
            "52w_high": safe_round(h52),
            "52w_low": safe_round(l52),
            "range_position_pct": pos_pct,
            "rise_from_52w_low_pct": rise_pct,
            "fall_from_52w_high_pct": fall_pct,
            "all_time_high": safe_round(float(self.d['High'].max())),
            "all_time_low": safe_round(float(self.d['Low'].min()))
        }

    def calculate_breakouts(self) -> Dict[str, Any]:
        results = {}

        # 1. Previous Day
        if len(self.d) >= 2:
            prev_h, prev_l = float(self.d['High'].iloc[-2]), float(self.d['Low'].iloc[-2])
            status = "Bullish Breakout (Above Prev High)" if self.price > prev_h else "Bearish Breakdown (Below Prev Low)" if self.price < prev_l else "Inside Prev Day Range"
            results["Previous_Day"] = {"prev_high": safe_round(prev_h), "prev_low": safe_round(prev_l), "status": status, "value": safe_round(((self.price - float(self.d['Close'].iloc[-2])) / float(self.d['Close'].iloc[-2])) * 100)}

        # 2. Weekly
        if len(self.w) >= 2:
            last_w_h, last_w_l = float(self.w['High'].iloc[-2]), float(self.w['Low'].iloc[-2])
            status = "Above Last Week High" if self.price > last_w_h else "Below Last Week Low" if self.price < last_w_l else "Inside Last Week Range"
            results["Last_Week"] = {"last_week_high": safe_round(last_w_h), "last_week_low": safe_round(last_w_l), "status": status}

        # 3. Monthly
        if len(self.m) >= 2:
            last_m_h, last_m_l = float(self.m['High'].iloc[-2]), float(self.m['Low'].iloc[-2])
            status = "Above Last Month High" if self.price > last_m_h else "Below Last Month Low" if self.price < last_m_l else "Inside Last Month Range"
            results["Last_Month"] = {"last_month_high": safe_round(last_m_h), "last_month_low": safe_round(last_m_l), "status": status}

        # 4. Gaps & Behavioral
        if len(self.d) >= 2:
            open_today = float(self.d['Open'].iloc[-1])
            prev_h = float(self.d['High'].iloc[-2])
            prev_l = float(self.d['Low'].iloc[-2])
            gap_up = ((open_today - prev_h) / prev_h) * 100 >= 2.0
            gap_down = ((prev_l - open_today) / prev_l) * 100 >= 2.0
            results["Gaps"] = {"gap_up_2pct": gap_up, "gap_down_2pct": gap_down}

        if len(self.d) >= 4:
            highs = self.d['High'].iloc[-4:].values
            lows = self.d['Low'].iloc[-4:].values
            hh_3d = highs[-1] > highs[-2] > highs[-3] > highs[-4]
            ll_3d = lows[-1] < lows[-2] < lows[-3] < lows[-4]
            results["Consecutive_Runs"] = {"higher_highs_3d": bool(hh_3d), "lower_lows_3d": bool(ll_3d)}

        # 5. VWAP (Typical Price Approximation)
        h, l, c = float(self.d['High'].iloc[-1]), float(self.d['Low'].iloc[-1]), self.price
        vwap = safe_round((h + l + c) / 3)
        results["Daily_VWAP"] = {
            "value": vwap,
            "status": "Above VWAP" if self.price > (vwap or 0) else "Below VWAP"
        }

        return results

    def calculate_relative_strength(self) -> Dict[str, Any]:
        if self.bench is None or self.bench.empty:
            return {}

        stock_c = self.d['Close']
        aligned_s, aligned_b = stock_c.align(self.bench, join='inner')
        aligned_s, aligned_b = aligned_s.ffill(), aligned_b.ffill()

        if len(aligned_s) < 56:
            return {}

        ratio = aligned_s / aligned_b.replace(0, np.nan)
        rs_21 = safe_round(((ratio / ratio.shift(21)) - 1).iloc[-1] * 100)
        rs_55 = safe_round(((ratio / ratio.shift(55)) - 1).iloc[-1] * 100)

        # Beta (1-Year Rolling Covariance/Variance)
        s_ret = aligned_s.pct_change().dropna()
        b_ret = aligned_b.pct_change().dropna()
        common = s_ret.index.intersection(b_ret.index)
        
        beta_val = 1.0
        if len(common) > 30:
            cov = s_ret.loc[common].iloc[-252:].cov(b_ret.loc[common].iloc[-252:])
            var = b_ret.loc[common].iloc[-252:].var()
            beta_val = safe_round(cov / var if var != 0 else 1.0)

        return {
            "RS_21D_vs_Nifty": {"value": rs_21, "status": "Outperforming" if (rs_21 or 0) > 0 else "Underperforming"},
            "RS_55D_vs_Nifty": {"value": rs_55, "status": "Outperforming" if (rs_55 or 0) > 0 else "Underperforming"},
            "Beta_1Y": {"value": beta_val}
        }

# ==============================================================================
# 6. SYMMETRICAL CANDLESTICK PATTERN RECOGNITION (27 PATTERNS)
# ==============================================================================
class CandlestickPatternEngine:
    def __init__(self, df: pd.DataFrame, timeframe: str):
        self.df = df
        self.tf = timeframe
        self.o, self.h, self.l, self.c = df['Open'], df['High'], df['Low'], df['Close']
        self.body = (self.c - self.o).abs()
        self.rng = (self.h - self.l).replace(0, np.nan)
        self.ushad = self.h - np.maximum(self.c, self.o)
        self.lshad = np.minimum(self.c, self.o) - self.l
        self.avg_body = self.body.rolling(10).mean().replace(0, np.nan)
        self.bull = self.c > self.o
        self.bear = self.c < self.o

    def _is_doji(self, i: int) -> bool: 
        return self.body.iloc[i] <= DOJI_BODY_THRESHOLD * self.rng.iloc[i]
    def _is_long(self, i: int) -> bool: 
        return self.body.iloc[i] >= LONG_BODY_MULTIPLIER * self.avg_body.iloc[i]
    def _is_short(self, i: int) -> bool: 
        return self.body.iloc[i] <= 0.5 * self.avg_body.iloc[i]
    def _trend_up(self, i: int) -> bool: 
        return self.c.iloc[i] > self.c.iloc[i-3]
    def _trend_dn(self, i: int) -> bool: 
        return self.c.iloc[i] < self.c.iloc[i-3]

    def evaluate(self) -> List[Dict[str, str]]:
        if len(self.df) < 6: return []
        patterns = []
        i = -1

        def _add(name: str, cat: str, sig: str): 
            patterns.append({"pattern": name, "category": cat, "signal": sig, "timeframe": self.tf})

        # 1. Neutral Doji
        if self._is_doji(i) and self.ushad.iloc[i] > 0.05 * self.rng.iloc[i] and self.lshad.iloc[i] > 0.05 * self.rng.iloc[i]: 
            _add("Doji", "Neutral", "Indecision")

        # 2 & 3. Doji Variants
        if self._is_doji(i) and self.ushad.iloc[i] <= 0.05 * self.rng.iloc[i] and self.lshad.iloc[i] > 0.5 * self.rng.iloc[i]: 
            _add("Dragonfly Doji", "Bullish Reversal", "Buy")
        if self._is_doji(i) and self.lshad.iloc[i] <= 0.05 * self.rng.iloc[i] and self.ushad.iloc[i] > 0.5 * self.rng.iloc[i]: 
            _add("Gravestone Doji", "Bearish Reversal", "Sell")

        # 4 & 5. Marubozu
        if self.bull.iloc[i] and self._is_long(i) and self.ushad.iloc[i] <= MARUBOZU_SHADOW_THRESHOLD * self.body.iloc[i] and self.lshad.iloc[i] <= MARUBOZU_SHADOW_THRESHOLD * self.body.iloc[i]: 
            _add("White Marubozu", "Bullish", "Strong Buy")
        if self.bear.iloc[i] and self._is_long(i) and self.ushad.iloc[i] <= MARUBOZU_SHADOW_THRESHOLD * self.body.iloc[i] and self.lshad.iloc[i] <= MARUBOZU_SHADOW_THRESHOLD * self.body.iloc[i]: 
            _add("Black Marubozu", "Bearish", "Strong Sell")

        # 6, 7, 8, 9. Single Shadows (Trend Dependent)
        if self.lshad.iloc[i] >= HAMMER_SHADOW_MULTIPLIER * self.body.iloc[i] and self.ushad.iloc[i] <= HAMMER_UPPER_SHADOW_LIMIT * self.body.iloc[i]:
            if self._trend_dn(i): _add("Hammer", "Bullish Reversal", "Buy")
            elif self._trend_up(i): _add("Hanging Man", "Bearish Reversal", "Sell")

        if self.ushad.iloc[i] >= HAMMER_SHADOW_MULTIPLIER * self.body.iloc[i] and self.lshad.iloc[i] <= HAMMER_UPPER_SHADOW_LIMIT * self.body.iloc[i]:
            if self._trend_dn(i): _add("Inverted Hammer", "Bullish Reversal", "Buy")
            elif self._trend_up(i): _add("Shooting Star", "Bearish Reversal", "Sell")

        # 10 & 11. Engulfing
        if self.bear.iloc[i-1] and self.bull.iloc[i] and self.c.iloc[i] > self.o.iloc[i-1] and self.o.iloc[i] < self.c.iloc[i-1]: 
            _add("Bullish Engulfing", "Bullish Reversal", "Strong Buy")
        if self.bull.iloc[i-1] and self.bear.iloc[i] and self.c.iloc[i] < self.o.iloc[i-1] and self.o.iloc[i] > self.c.iloc[i-1]: 
            _add("Bearish Engulfing", "Bearish Reversal", "Strong Sell")

        # 12 & 13. Harami
        if self.bear.iloc[i-1] and self._is_long(i-1) and self.bull.iloc[i] and self.c.iloc[i] < self.o.iloc[i-1] and self.o.iloc[i] > self.c.iloc[i-1]: 
            _add("Bullish Harami", "Bullish Reversal", "Buy")
        if self.bull.iloc[i-1] and self._is_long(i-1) and self.bear.iloc[i] and self.c.iloc[i] > self.o.iloc[i-1] and self.o.iloc[i] < self.c.iloc[i-1]: 
            _add("Bearish Harami", "Bearish Reversal", "Sell")

        # 14 & 15. Harami Cross
        if self.bear.iloc[i-1] and self._is_long(i-1) and self._is_doji(i) and self.c.iloc[i] < self.o.iloc[i-1] and self.o.iloc[i] > self.c.iloc[i-1]: 
            _add("Bullish Harami Cross", "Bullish Reversal", "Strong Buy")
        if self.bull.iloc[i-1] and self._is_long(i-1) and self._is_doji(i) and self.c.iloc[i] > self.o.iloc[i-1] and self.o.iloc[i] < self.c.iloc[i-1]: 
            _add("Bearish Harami Cross", "Bearish Reversal", "Strong Sell")

        # 16 & 17. Piercing & Dark Cloud
        if self.bear.iloc[i-1] and self._is_long(i-1) and self.bull.iloc[i] and self.o.iloc[i] < self.l.iloc[i-1] and self.c.iloc[i] > (self.o.iloc[i-1] + self.c.iloc[i-1])/2: 
            _add("Piercing Line", "Bullish Reversal", "Buy")
        if self.bull.iloc[i-1] and self._is_long(i-1) and self.bear.iloc[i] and self.o.iloc[i] > self.h.iloc[i-1] and self.c.iloc[i] < (self.o.iloc[i-1] + self.c.iloc[i-1])/2: 
            _add("Dark Cloud Cover", "Bearish Reversal", "Sell")

        # 18 & 19. Stars
        if self.bear.iloc[i-2] and self._is_long(i-2) and self._is_short(i-1) and self.bull.iloc[i] and self._is_long(i) and self.c.iloc[i] > (self.o.iloc[i-2]+self.c.iloc[i-2])/2: 
            _add("Morning Star", "Bullish Reversal", "Strong Buy")
        if self.bull.iloc[i-2] and self._is_long(i-2) and self._is_short(i-1) and self.bear.iloc[i] and self._is_long(i) and self.c.iloc[i] < (self.o.iloc[i-2]+self.c.iloc[i-2])/2: 
            _add("Evening Star", "Bearish Reversal", "Strong Sell")

        # 20 & 21. Abandoned Baby
        if self.bear.iloc[i-2] and self._is_doji(i-1) and self.bull.iloc[i] and self.h.iloc[i-1] < self.l.iloc[i-2] and self.h.iloc[i-1] < self.l.iloc[i]: 
            _add("Abandoned Baby Bottom", "Bullish Reversal", "Strong Buy")
        if self.bull.iloc[i-2] and self._is_doji(i-1) and self.bear.iloc[i] and self.l.iloc[i-1] > self.h.iloc[i-2] and self.l.iloc[i-1] > self.h.iloc[i]: 
            _add("Abandoned Baby Top", "Bearish Reversal", "Strong Sell")

        # 22 & 23. Soldiers / Crows
        if all(self.bull.iloc[j] and self._is_long(j) for j in range(-3, 0)) and self.c.iloc[-1] > self.c.iloc[-2] > self.c.iloc[-3]: 
            _add("Three White Soldiers", "Bullish Momentum", "Strong Buy")
        if all(self.bear.iloc[j] and self._is_long(j) for j in range(-3, 0)) and self.c.iloc[-1] < self.c.iloc[-2] < self.c.iloc[-3]: 
            _add("Three Black Crows", "Bearish Momentum", "Strong Sell")

        # 24 & 25. Tasuki Gap
        if self.bull.iloc[i-2] and self.bull.iloc[i-1] and self.o.iloc[i-1] > self.c.iloc[i-2] and self.bear.iloc[i] and self.o.iloc[i] < self.c.iloc[i-1] and self.c.iloc[i] < self.o.iloc[i-1] and self.c.iloc[i] > self.c.iloc[i-2]: 
            _add("Upside Tasuki Gap", "Bullish Continuation", "Buy")
        if self.bear.iloc[i-2] and self.bear.iloc[i-1] and self.o.iloc[i-1] < self.c.iloc[i-2] and self.bull.iloc[i] and self.o.iloc[i] > self.c.iloc[i-1] and self.c.iloc[i] > self.o.iloc[i-1] and self.c.iloc[i] < self.c.iloc[i-2]: 
            _add("Downside Tasuki Gap", "Bearish Continuation", "Sell")

        # 26 & 27. Three Methods
        if len(self.df) >= 6:
            if self.bull.iloc[-5] and self._is_long(-5) and all(self.bear.iloc[j] and self._is_short(j) for j in range(-4, -1)) and self.c.iloc[-2] > self.o.iloc[-5] and self.bull.iloc[-1] and self.c.iloc[-1] > self.c.iloc[-5]: 
                _add("Rising Three Methods", "Bullish Continuation", "Strong Buy")
            if self.bear.iloc[-5] and self._is_long(-5) and all(self.bull.iloc[j] and self._is_short(j) for j in range(-4, -1)) and self.c.iloc[-2] < self.o.iloc[-5] and self.bear.iloc[-1] and self.c.iloc[-1] < self.c.iloc[-5]: 
                _add("Falling Three Methods", "Bearish Continuation", "Strong Sell")

        return patterns

# ==============================================================================
# 7. VOLUME ENGINE
# ==============================================================================
class VolumeAnalysisEngine:
    def __init__(self, d_df: pd.DataFrame, w_df: pd.DataFrame, m_df: pd.DataFrame):
        self.d = d_df
        self.w = w_df
        self.m = m_df

    def analyze_volume(self) -> Dict[str, Any]:
        results = {}

        def _calc_vol(df: pd.DataFrame, avg_period: int, prefix: str):
            if len(df) >= avg_period + 1:
                curr_vol = float(df['Volume'].iloc[-1])
                avg_vol = float(df['Volume'].rolling(avg_period).mean().iloc[-1])
                ratio = safe_round(curr_vol / avg_vol if avg_vol > 0 else 1.0)
                status = "Ultra Volume Spike (>2.5x)" if ratio >= 2.5 else "Volume Spike (>1.5x)" if ratio >= 1.5 else "Normal Volume"
                results[prefix] = {
                    "current_volume": curr_vol,
                    "average_volume": safe_round(avg_vol),
                    "volume_ratio": ratio,
                    "status": status
                }

        _calc_vol(self.d, 10, "Daily_Volume")
        _calc_vol(self.w, 4, "Weekly_Volume")
        _calc_vol(self.m, 3, "Monthly_Volume")

        return results

# ==============================================================================
# 8. MASTER ORCHESTRATOR
# ==============================================================================
def process_stock(ticker: str) -> Optional[Dict[str, Any]]:
    ticker = ticker.strip().upper()
    logger.info(f"Processing unified technical scans for [{ticker}]...")

    d_df, w_df, m_df = UnifiedDataFetcher.fetch_stock_data(ticker)
    if d_df.empty:
        logger.warning(f"No OHLCV data found for {ticker}. Skipping.")
        return None

    bench_series = UnifiedDataFetcher.fetch_benchmark()
    master_map = load_master_industry_map()
    industry = get_industry_for_ticker(ticker, master_map)

    # 1. Indicators on 1d, 1w, 1m
    d_engine = TechnicalIndicatorsEngine(d_df, "1d")
    w_engine = TechnicalIndicatorsEngine(w_df, "1w")
    m_engine = TechnicalIndicatorsEngine(m_df, "1m")

    d_indicators = {
        **d_engine.calculate_moving_averages(D_MA_PERIODS),
        **d_engine.calculate_oscillators(),
        **d_engine.calculate_trend_and_volatility(),
        "Pivots": d_engine.calculate_pivots()
    }

    w_indicators = {
        **w_engine.calculate_moving_averages(W_MA_PERIODS),
        **w_engine.calculate_oscillators(),
        **w_engine.calculate_trend_and_volatility(),
        "Pivots": w_engine.calculate_pivots()
    }

    m_indicators = {
        **m_engine.calculate_moving_averages(M_MA_PERIODS),
        **m_engine.calculate_oscillators(),
        **m_engine.calculate_trend_and_volatility(),
        "Pivots": m_engine.calculate_pivots()
    }

    # 2. Price Action Engine (Breakouts, Range, Returns, Relative Strength)
    pa_engine = PriceActionEngine(d_df, w_df, m_df, bench_series)
    price_action = {
        "returns": pa_engine.calculate_returns(),
        "52w_and_ranges": pa_engine.calculate_52w_and_range(),
        "breakouts": pa_engine.calculate_breakouts(),
        "relative_strength": pa_engine.calculate_relative_strength()
    }

    # 3. Candlesticks (Fractal evaluation)
    d_candles = CandlestickPatternEngine(d_df, "1d").evaluate()
    w_candles = CandlestickPatternEngine(w_df, "1w").evaluate()
    m_candles = CandlestickPatternEngine(m_df, "1m").evaluate()

    # 4. Volume
    vol_engine = VolumeAnalysisEngine(d_df, w_df, m_df)
    volume_analysis = vol_engine.analyze_volume()

    # Assemble Payload
    payload = {
        "ticker": ticker,
        "timestamp": datetime.now().isoformat(),
        "last_close": safe_round(d_df['Close'].iloc[-1]),
        "last_volume": float(d_df['Volume'].iloc[-1]),
        "industry": industry,
        "1d_indicators": d_indicators,
        "1w_indicators": w_indicators,
        "1m_indicators": m_indicators,
        "price_action": price_action,
        "candlestick_patterns": d_candles + w_candles + m_candles,
        "volume_analysis": volume_analysis
    }

    # Save to JSON
    out_file = OUTPUT_DIR / f"{ticker}_technicals.json"
    try:
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4)
        logger.info(f"Successfully saved unified technical data to {out_file.name}")
    except Exception as e:
        logger.error(f"Failed to write output file: {e}")

    return payload

def main():
    parser = argparse.ArgumentParser(description="AlphaQuant Unified Technical Scanner")
    parser.add_argument("--ticker", type=str, help="Ticker symbol to scan")
    parser.add_argument("--limit", type=int, help="Limit total tickers processed")
    args = parser.parse_args()

    tickers = [args.ticker.upper()] if args.ticker else get_nifty_tickers()
    if args.limit:
        tickers = tickers[:args.limit]

    logger.info(f"Starting batch technical processing for {len(tickers)} stocks...")
    for t in tickers:
        process_stock(t)

if __name__ == "__main__":
    main()