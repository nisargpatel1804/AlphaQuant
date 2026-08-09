# backend/scans/technical_scanner.py

"""
Technical Scanner (AlphaQuant)
Consolidated single-file module for fetching OHLCV data, calculating indicators, 
and executing all technical scans using yfinance and pandas_ta.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import yfinance as yf

try:
    import pandas_ta as ta  # type: ignore
    _HAS_PANDAS_TA = True
except Exception:
    ta = None
    _HAS_PANDAS_TA = False

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")

# ==============================================================================
# 1. PATHS & CONFIGURATION
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
OUTPUT_DIR = BASE_DIR / "output" / "data"                  # backend/output/data/
SOURCE_DIR = BASE_DIR / "source"                           # backend/source/

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NIFTY_500_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
BENCHMARK_TICKER = "^NSEI"
BETA_LOOKBACK_YEARS = 1

# thresholds and parameters
NEARING_THRESHOLD_PCT = 1.5 
MA_PERIODS = [5, 10, 20, 30, 50, 100, 200]
WEEKLY_MA_PERIODS = [5, 10, 20, 50]
VWMA_PERIOD = 20
HMA_PERIOD = 9

RSI_PERIOD, RSI_OVERBOUGHT, RSI_OVERSOLD, RSI_BULLISH_ZONE = 14, 70, 30, 50
CCI_PERIOD, CCI_OVERBOUGHT, CCI_OVERSOLD, CCI_ZERO = 20, 100, -100, 0
STOCH_K_PERIOD, STOCH_D_PERIOD, STOCH_SMOOTH_K, STOCH_OVERBOUGHT, STOCH_OVERSOLD = 14, 3, 3, 80, 20
STOCHRSI_PERIOD, STOCHRSI_RSI_LENGTH, STOCHRSI_STOCH_LENGTH = 14, 14, 14
STOCHRSI_K, STOCHRSI_D, STOCHRSI_K_PERIOD, STOCHRSI_D_PERIOD = 3, 3, 3, 3
WILLR_PERIOD, WILLR_OVERBOUGHT, WILLR_OVERSOLD, WILLR_MIDPOINT = 14, -20, -80, -50
MFI_PERIOD, MFI_OVERBOUGHT, MFI_OVERSOLD, MFI_MIDPOINT = 14, 80, 20, 50
ROC_PERIOD, ROC_BULLISH_THRESHOLD = 14, 0
AO_FAST, AO_SLOW = 5, 34
ULTOSC_MIN, ULTOSC_MID, ULTOSC_MAX, UO_SHORT, UO_MEDIUM, UO_LONG = 7, 14, 28, 7, 14, 28
BBP_EMA_PERIOD, BULL_BEAR_EMA = 13, 13
MOMENTUM_PERIOD = 10

MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
ADX_PERIOD, ADX_SMOOTHING = 14, 14
ADX_WEAK_TREND, ADX_STRONG_TREND, ADX_VERY_STRONG_TREND, ADX_NO_TREND = 20, 25, 40, 10
SUPERTREND_LENGTH, SUPERTREND_MULTIPLIER = 7, 3
PSAR_AF_START, PSAR_AF_INC, PSAR_AF_MAX = 0.02, 0.02, 0.2
ICHIMOKU_TENKAN_PERIOD, ICHIMOKU_KIJUN_PERIOD, ICHIMOKU_SENKOU_B_PERIOD, ICHIMOKU_DISPLACEMENT = 9, 26, 52, 26

BB_LENGTH, BB_STD_DEV = 20, 2
BB_SQUEEZE_PERCENTILE, BB_EXPANSION_PERCENTILE = 20, 80
ATR_PERIOD, ATR_TREND_LOOKBACK = 14, 3
NR4_LOOKBACK, NR7_LOOKBACK = 4, 7

MOMENTUM_BULLISH_THRESHOLD, MOMENTUM_BEARISH_THRESHOLD = 5.0, -5.0
MOMENTUM_NEUTRAL_LOW, MOMENTUM_NEUTRAL_HIGH = -2.0, 2.0
BETA_HIGH_THRESHOLD, BETA_LOW_THRESHOLD, BETA_NEUTRAL = 1.5, 0.5, 1.0
PIVOT_CPR_FACTOR = 1.1

# ==============================================================================
# 2. UTILITIES & DATA LOADING
# ==============================================================================
def load_master_industry_map() -> List[Dict[str, Any]]:
    path = SOURCE_DIR / "master_industry_map.json"
    if not path.exists(): return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [row for row in data if isinstance(row, dict)]
    except Exception: return []

def get_stocks_for_industry(industry_name: str) -> List[str]:
    master_map = load_master_industry_map()
    target = industry_name.lower().strip()
    for entry in master_map:
        if target in entry.get("industry", "").lower():
            return entry.get("stocks", [])
    return []

def get_nifty_tickers(retries: int = 4) -> List[str]:
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0",
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
            if attempt == retries: break
            time.sleep(1.5 * attempt)
            
    fallback = SOURCE_DIR / "ind_nifty500list.csv"
    if fallback.exists():
        with open(fallback, "r", encoding="utf-8") as f:
            return [row["Symbol"].strip().upper() for row in csv.DictReader(f) if row.get("Symbol")]
    return []

# ==============================================================================
# 3. FETCHER (YFinance Integration)
# ==============================================================================
class TechnicalFetcher:
    def __init__(self):
        self._benchmark_cache: Optional[pd.Series] = None
        self._industry_map_cache: Optional[List[dict]] = None
        self._ticker_to_industry_cache: Optional[Dict[str, str]] = None
        self._industry_beta_cache: Dict[str, float] = {}

    def get_industry_for_ticker(self, ticker: str) -> Optional[str]:
        if self._ticker_to_industry_cache is None:
            rows = load_master_industry_map()
            self._industry_map_cache = rows
            self._ticker_to_industry_cache = {
                str(t).strip().upper(): str(row.get("industry", "")).strip()
                for row in rows for t in (row.get("stocks", []) or []) if isinstance(t, str)
            }
        return self._ticker_to_industry_cache.get(ticker.strip().upper())

    def fetch_benchmark(self) -> pd.Series:
        if self._benchmark_cache is not None:
            return self._benchmark_cache
        start_date = (datetime.now() - timedelta(days=BETA_LOOKBACK_YEARS * 365 + 60)).strftime('%Y-%m-%d')
        try:
            data = yf.download(BENCHMARK_TICKER, start=start_date, progress=False, auto_adjust=True, threads=False)
            if data is None or data.empty: raise ValueError(f"Benchmark empty for {BENCHMARK_TICKER}")
            close_data = data['Close'][BENCHMARK_TICKER] if isinstance(data.columns, pd.MultiIndex) else data['Close']
            self._benchmark_cache = close_data.iloc[:, 0] if isinstance(close_data, pd.DataFrame) else close_data
            return self._benchmark_cache
        except Exception as e:
            logging.error(f"Error fetching benchmark: {e}")
            return pd.Series(dtype=float)

    def fetch_stock_data(self, ticker: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
        symbol = f"{ticker.strip().upper()}.NS" if not ticker.endswith((".NS", ".BO")) else ticker
        try:
            df = yf.download(symbol, period="2y", interval="1d", progress=False, auto_adjust=True)
            if df.empty and symbol.endswith(".NS"):
                df = yf.download(symbol.replace(".NS", ".BO"), period="2y", interval="1d", progress=False, auto_adjust=True)
            if df.empty: raise ValueError(f"No data for {symbol}")

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                
            col_map = {'Adj Close': 'Close', 'adj close': 'Close', 'close': 'Close', 'open': 'Open', 'high': 'High', 'low': 'Low', 'volume': 'Volume'}
            df.rename(columns=col_map, inplace=True)

            required = {'Open', 'High', 'Low', 'Close', 'Volume'}
            if not required.issubset(df.columns):
                if 'Volume' in (required - set(df.columns)): df['Volume'] = 0
                else: raise ValueError("Missing required OHLC columns")

            weekly_agg = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}
            agg_to_use = {k: v for k, v in weekly_agg.items() if k in df.columns}
            weekly_df = df.resample('W-FRI').agg(agg_to_use).dropna()
            
            return df, weekly_df
        except Exception as e:
            logging.error(f"Failed to fetch {ticker}: {e}")
            return pd.DataFrame(), pd.DataFrame()

# ==============================================================================
# 4. INDICATORS (Math Engine)
# ==============================================================================
class TechnicalIndicators:
    @staticmethod
    def _wma(series: pd.Series, length: int) -> pd.Series:
        if length <= 0: return pd.Series(index=series.index, dtype=float)
        weights = np.arange(1, length + 1, dtype=float)
        def _apply(x: np.ndarray) -> float:
            return float(np.dot(x, weights) / weights.sum()) if x.size == length and np.all(np.isfinite(x)) else np.nan
        return series.rolling(window=length, min_periods=length).apply(_apply, raw=True)

    @staticmethod
    def _hma(series: pd.Series, length: int) -> pd.Series:
        if length <= 0: return pd.Series(index=series.index, dtype=float)
        raw = 2 * TechnicalIndicators._wma(series, max(int(length / 2), 1)) - TechnicalIndicators._wma(series, length)
        return TechnicalIndicators._wma(raw, max(int(np.sqrt(length)), 1))

    @staticmethod
    def add_all_indicators(df: pd.DataFrame, is_weekly: bool = False, benchmark_data: Optional[pd.Series] = None) -> pd.DataFrame:
        if df.empty: return df
        df.sort_index(ascending=True, inplace=True)
        TechnicalIndicators.add_moving_averages(df, is_weekly)
        TechnicalIndicators.add_oscillators(df)
        TechnicalIndicators.add_trend_indicators(df)
        TechnicalIndicators.add_volatility_indicators(df)
        TechnicalIndicators.add_ichimoku(df)
        TechnicalIndicators.add_volume_weighted_indicators(df)
        
        if not is_weekly:
            TechnicalIndicators.add_pivots(df)
            if benchmark_data is not None: TechnicalIndicators.add_beta(df, benchmark_data)
        return df

    @staticmethod
    def add_volume_weighted_indicators(df: pd.DataFrame) -> None:
        if 'Close' in df.columns and 'Volume' in df.columns:
            pv = df['Close'] * df['Volume']
            df[f'VWMA_{VWMA_PERIOD}'] = pv.rolling(VWMA_PERIOD).sum() / df['Volume'].rolling(VWMA_PERIOD).sum()
        if 'Close' in df.columns:
            df[f'HMA_{HMA_PERIOD}'] = TechnicalIndicators._hma(df['Close'], HMA_PERIOD)

    @staticmethod
    def add_moving_averages(df: pd.DataFrame, is_weekly: bool) -> None:
        periods = WEEKLY_MA_PERIODS if is_weekly else MA_PERIODS
        for p in periods:
            df[f'SMA_{p}'] = df['Close'].rolling(window=p, min_periods=p).mean()
            df[f'EMA_{p}'] = df['Close'].ewm(span=p, adjust=False, min_periods=p).mean()

    @staticmethod
    def add_oscillators(df: pd.DataFrame) -> None:
        # RSI
        delta = df['Close'].diff()
        gain = delta.where(delta > 0, 0).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
        df['RSI'] = 100 - (100 / (1 + (gain / loss)))

        # Momentum & ROC
        df['ROC'] = df['Close'].pct_change(periods=ROC_PERIOD) * 100
        df[f'MOMENTUM_{MOMENTUM_PERIOD}'] = df['Close'] - df['Close'].shift(MOMENTUM_PERIOD)

        # Awesome Oscillator
        median = (df['High'] + df['Low']) / 2
        df['AO'] = median.rolling(AO_FAST).mean() - median.rolling(AO_SLOW).mean()

    @staticmethod
    def add_trend_indicators(df: pd.DataFrame) -> None:
        fast_ema = df['Close'].ewm(span=MACD_FAST, adjust=False).mean()
        slow_ema = df['Close'].ewm(span=MACD_SLOW, adjust=False).mean()
        df['MACD_LINE'] = fast_ema - slow_ema
        df['MACD_SIGNAL'] = df['MACD_LINE'].ewm(span=MACD_SIGNAL, adjust=False).mean()
        df['MACD_HIST'] = df['MACD_LINE'] - df['MACD_SIGNAL']

    @staticmethod
    def add_volatility_indicators(df: pd.DataFrame) -> None:
        mid = df['Close'].rolling(window=BB_LENGTH).mean()
        std = df['Close'].rolling(window=BB_LENGTH).std()
        df['BB_MIDDLE'], df['BB_UPPER'], df['BB_LOWER'] = mid, mid + (BB_STD_DEV * std), mid - (BB_STD_DEV * std)
        
        tr = pd.concat([df['High'] - df['Low'], (df['High'] - df['Close'].shift(1)).abs(), (df['Low'] - df['Close'].shift(1)).abs()], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(window=ATR_PERIOD).mean()

    @staticmethod
    def add_ichimoku(df: pd.DataFrame) -> None:
        df['TENKAN'] = (df['High'].rolling(9).max() + df['Low'].rolling(9).min()) / 2
        df['KIJUN'] = (df['High'].rolling(26).max() + df['Low'].rolling(26).min()) / 2
        df['SPAN_A'] = ((df['TENKAN'] + df['KIJUN']) / 2).shift(26)
        df['SPAN_B'] = ((df['High'].rolling(52).max() + df['Low'].rolling(52).min()) / 2).shift(26)

    @staticmethod
    def add_pivots(df: pd.DataFrame) -> None:
        h, l, c = df['High'].shift(1), df['Low'].shift(1), df['Close'].shift(1)
        o = df['Open'].shift(1)
        rng = (h - l)
        
        p = (h + l + c) / 3
        df['PIVOT_CLASSIC_P'] = p
        df['PIVOT_CLASSIC_R1'] = 2 * p - l
        df['PIVOT_CLASSIC_S1'] = 2 * p - h
        df['PIVOT_CLASSIC_R2'] = p + rng
        df['PIVOT_CLASSIC_S2'] = p - rng
        df['PIVOT_CLASSIC_R3'] = h + 2 * (p - l)
        df['PIVOT_CLASSIC_S3'] = l - 2 * (h - p)

        df['PIVOT_FIB_P'] = p
        df['PIVOT_FIB_R1'] = p + 0.382 * rng
        df['PIVOT_FIB_S1'] = p - 0.382 * rng
        df['PIVOT_FIB_R2'] = p + 0.618 * rng
        df['PIVOT_FIB_S2'] = p - 0.618 * rng
        df['PIVOT_FIB_R3'] = p + 1.000 * rng
        df['PIVOT_FIB_S3'] = p - 1.000 * rng

        factor = PIVOT_CPR_FACTOR
        df['PIVOT_CAM_R1'] = c + rng * factor / 12
        df['PIVOT_CAM_R2'] = c + rng * factor / 6
        df['PIVOT_CAM_R3'] = c + rng * factor / 4
        df['PIVOT_CAM_R4'] = c + rng * factor / 2
        df['PIVOT_CAM_S1'] = c - rng * factor / 12
        df['PIVOT_CAM_S2'] = c - rng * factor / 6
        df['PIVOT_CAM_S3'] = c - rng * factor / 4
        df['PIVOT_CAM_S4'] = c - rng * factor / 2

        pw = (h + l + 2 * c) / 4
        df['PIVOT_WOODIE_P'] = pw
        df['PIVOT_WOODIE_R1'] = 2 * pw - l
        df['PIVOT_WOODIE_S1'] = 2 * pw - h
        df['PIVOT_WOODIE_R2'] = pw + rng
        df['PIVOT_WOODIE_S2'] = pw - rng
        df['PIVOT_WOODIE_R3'] = h + 2 * (pw - l)
        df['PIVOT_WOODIE_S3'] = l - 2 * (h - pw)

        x = np.where(c < o, h + 2 * l + c, np.where(c > o, 2 * h + l + c, h + l + 2 * c))
        x = pd.Series(x, index=df.index, dtype=float)
        df['PIVOT_DEMARK_P'] = x / 4
        df['PIVOT_DEMARK_R1'] = x / 2 - l
        df['PIVOT_DEMARK_S1'] = x / 2 - h

    @staticmethod
    def add_beta(df: pd.DataFrame, benchmark: pd.Series) -> None:
        common_idx = df.index.intersection(benchmark.index)
        if len(common_idx) > 30:
            cov = df.loc[common_idx, 'Close'].pct_change().cov(benchmark.loc[common_idx].pct_change())
            var = benchmark.loc[common_idx].pct_change().var()
            df['BETA'] = cov / var if var != 0 else 1.0
        else:
            df['BETA'] = 1.0

# ==============================================================================
# 5. SCANNER (Signal Engine)
# ==============================================================================
@dataclass(frozen=True)
class TechScanDef:
    name: str; label: str; category: str

class TechnicalScans:
    SCANS = (
        # Momentum
        TechScanDef("check_momentum_1m", "Momentum (1M)", "Momentum"),
        TechScanDef("check_momentum_3m", "Momentum (3M)", "Momentum"),
        TechScanDef("check_momentum_6m", "Momentum (6M)", "Momentum"),
        TechScanDef("check_momentum_10", "Momentum (10)", "Momentum"),
        
        # Moving Averages
        TechScanDef("check_sma_10_status", "Price vs SMA 10", "Simple Moving Averages"),
        TechScanDef("check_sma_20_status", "Price vs SMA 20", "Simple Moving Averages"),
        TechScanDef("check_sma_30_status", "Price vs SMA 30", "Simple Moving Averages"),
        TechScanDef("check_sma_50_status", "Price vs SMA 50", "Simple Moving Averages"),
        TechScanDef("check_sma_100_status", "Price vs SMA 100", "Simple Moving Averages"),
        TechScanDef("check_sma_200_status", "Price vs SMA 200", "Simple Moving Averages"),
        
        TechScanDef("check_ema_10_status", "Price vs EMA 10", "Exponential Moving Averages"),
        TechScanDef("check_ema_20_status", "Price vs EMA 20", "Exponential Moving Averages"),
        TechScanDef("check_ema_30_status", "Price vs EMA 30", "Exponential Moving Averages"),
        TechScanDef("check_ema_50_status", "Price vs EMA 50", "Exponential Moving Averages"),
        TechScanDef("check_ema_100_status", "Price vs EMA 100", "Exponential Moving Averages"),
        TechScanDef("check_ema_200_status", "Price vs EMA 200", "Exponential Moving Averages"),
        
        TechScanDef("check_hma_status", f"Hull Moving Average ({HMA_PERIOD})", "Hull Moving Average"),
        TechScanDef("check_vwma_status", f"VWMA ({VWMA_PERIOD})", "Volume Weighted MA"),
        TechScanDef("check_ma_crossover_50_200", "Golden/Death Cross", "Simple Moving Averages"),
        TechScanDef("check_price_cross_sma_20", "Price Crossover SMA 20", "Simple Moving Averages"),
        
        # Oscillators
        TechScanDef("check_rsi_status", "RSI Zone", "RSI"),
        TechScanDef("check_rsi_trend", "RSI Trend", "RSI"),
        TechScanDef("check_cci_status", "CCI Zone", "CCI"),
        TechScanDef("check_mfi_status", "MFI Zone", "MFI"),
        TechScanDef("check_stoch_status", "Stochastic %K", "Stochastic"),
        TechScanDef("check_stochrsi_status", "Stochastic RSI Fast", "Stoch RSI"),
        TechScanDef("check_willr_status", "Williams %R", "Williams %R"),
        TechScanDef("check_ao_status", "Awesome Oscillator", "Awesome Oscillator"),
        TechScanDef("check_ultosc_status", "Ultimate Oscillator", "Ultimate Oscillator"),
        TechScanDef("check_bbp_status", "Bull Bear Power", "Bull/Bear Power"),
        
        # Trend
        TechScanDef("check_macd_status", "MACD Level", "MACD"),
        TechScanDef("check_adx_status", "ADX Trend Strength", "ADX"),
        TechScanDef("check_supertrend_status", "SuperTrend Status", "SuperTrend"),
        TechScanDef("check_psar_status", "Parabolic SAR", "Parabolic SAR"),
        
        # Volatility
        TechScanDef("check_bb_status", "Bollinger Bands Position", "Bollinger Bands"),
        TechScanDef("check_bb_width", "Bollinger Bands Width", "Bollinger Bands"),
        
        # Ichimoku
        TechScanDef("check_ichimoku_cloud", "Cloud Status", "Ichimoku"),
        TechScanDef("check_ichimoku_base", "Ichimoku Base Line", "Ichimoku"),
        TechScanDef("check_ichimoku_tk", "TK Cross", "Ichimoku"),
        
        # Beta
        TechScanDef("check_beta_status", "Beta Status", "Beta"),
        
        # Pivots (Classic)
        TechScanDef("check_pivot_classic_p", "Pivot Classic P", "Pivots - Classic"),
        TechScanDef("check_pivot_classic_r1", "Pivot Classic R1", "Pivots - Classic"),
        TechScanDef("check_pivot_classic_s1", "Pivot Classic S1", "Pivots - Classic"),
        TechScanDef("check_pivot_classic_r2", "Pivot Classic R2", "Pivots - Classic"),
        TechScanDef("check_pivot_classic_s2", "Pivot Classic S2", "Pivots - Classic"),
        TechScanDef("check_pivot_classic_r3", "Pivot Classic R3", "Pivots - Classic"),
        TechScanDef("check_pivot_classic_s3", "Pivot Classic S3", "Pivots - Classic"),

        # Pivots (Fibonacci)
        TechScanDef("check_pivot_fib_p", "Pivot Fibonacci P", "Pivots - Fibonacci"),
        TechScanDef("check_pivot_fib_r1", "Pivot Fibonacci R1", "Pivots - Fibonacci"),
        TechScanDef("check_pivot_fib_s1", "Pivot Fibonacci S1", "Pivots - Fibonacci"),
        TechScanDef("check_pivot_fib_r2", "Pivot Fibonacci R2", "Pivots - Fibonacci"),
        TechScanDef("check_pivot_fib_s2", "Pivot Fibonacci S2", "Pivots - Fibonacci"),
        TechScanDef("check_pivot_fib_r3", "Pivot Fibonacci R3", "Pivots - Fibonacci"),
        TechScanDef("check_pivot_fib_s3", "Pivot Fibonacci S3", "Pivots - Fibonacci"),

        # Pivots (Camarilla)
        TechScanDef("check_pivot_cam_r1", "Pivot Camarilla R1", "Pivots - Camarilla"),
        TechScanDef("check_pivot_cam_r2", "Pivot Camarilla R2", "Pivots - Camarilla"),
        TechScanDef("check_pivot_cam_r3", "Pivot Camarilla R3", "Pivots - Camarilla"),
        TechScanDef("check_pivot_cam_r4", "Pivot Camarilla R4", "Pivots - Camarilla"),
        TechScanDef("check_pivot_cam_s1", "Pivot Camarilla S1", "Pivots - Camarilla"),
        TechScanDef("check_pivot_cam_s2", "Pivot Camarilla S2", "Pivots - Camarilla"),
        TechScanDef("check_pivot_cam_s3", "Pivot Camarilla S3", "Pivots - Camarilla"),
        TechScanDef("check_pivot_cam_s4", "Pivot Camarilla S4", "Pivots - Camarilla"),

        # Pivots (Woodie)
        TechScanDef("check_pivot_woodie_p", "Pivot Woodie P", "Pivots - Woodie"),
        TechScanDef("check_pivot_woodie_r1", "Pivot Woodie R1", "Pivots - Woodie"),
        TechScanDef("check_pivot_woodie_s1", "Pivot Woodie S1", "Pivots - Woodie"),
        TechScanDef("check_pivot_woodie_r2", "Pivot Woodie R2", "Pivots - Woodie"),
        TechScanDef("check_pivot_woodie_s2", "Pivot Woodie S2", "Pivots - Woodie"),
        TechScanDef("check_pivot_woodie_r3", "Pivot Woodie R3", "Pivots - Woodie"),
        TechScanDef("check_pivot_woodie_s3", "Pivot Woodie S3", "Pivots - Woodie"),

        # Pivots (DeMark)
        TechScanDef("check_pivot_demark_p", "Pivot DeMark P", "Pivots - DeMark"),
        TechScanDef("check_pivot_demark_r1", "Pivot DeMark R1", "Pivots - DeMark"),
        TechScanDef("check_pivot_demark_s1", "Pivot DeMark S1", "Pivots - DeMark"),
    )

    def __init__(self, daily_df: pd.DataFrame, weekly_df: pd.DataFrame):
        self.df = daily_df
        self.w_df = weekly_df
        self._current_value: Optional[float] = None
        self._current_min: Optional[float] = None
        self._current_max: Optional[float] = None

    # --- Helpers ---
    def _get_val(self, series: pd.Series, offset: int = 0) -> float:
        if len(series) < offset + 1: return np.nan
        return series.iloc[-(offset + 1)]

    def _record_series(self, series: pd.Series, offset: int = 0) -> None:
        try:
            if series is None or len(series) == 0:
                self._current_value = self._current_min = self._current_max = None
                return
            val = self._get_val(series, offset=offset)
            self._current_value = float(val) if isinstance(val, (int, float, np.number)) and np.isfinite(val) else None
            s = series.dropna()
            if s.empty:
                self._current_min = self._current_max = None
                return
            mn, mx = float(s.min()), float(s.max())
            self._current_min = mn if np.isfinite(mn) else None
            self._current_max = mx if np.isfinite(mx) else None
        except Exception:
            self._current_value = self._current_min = self._current_max = None

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

    @staticmethod
    def _map_status_to_action(status_text: str) -> str:
        t = (status_text or "").strip().lower()
        if not t or "pending" in t or "missing" in t or "squeeze" in t or "neutral" in t or "no cross" in t or "inside" in t: return "Neutral"
        if "strong buy" in t or "overbought" in t: return "Strong Buy" 
        if "strong sell" in t or "oversold" in t: return "Strong Sell" 
        if "bullish" in t or "buy" in t or "above" in t or "rising" in t or "positive" in t: return "Buy"
        if "bearish" in t or "sell" in t or "below" in t or "falling" in t or "negative" in t: return "Sell"
        return "Neutral"

    # --- Momentum Scans ---
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
        col = f'MOMENTUM_{MOMENTUM_PERIOD}'
        if col not in self.df.columns: return "Pending"
        self._record_series(self.df[col])
        curr = self.df[col].iloc[-1]
        if pd.isna(curr): return "Pending"
        return "Buy" if curr > 0 else "Sell"

    # --- MA Scans ---
    def _check_ma_status(self, col_name: str) -> str:
        if col_name not in self.df.columns: return "Pending"
        ma = self.df[col_name].iloc[-1]
        price = self.df['Close'].iloc[-1]
        self._record_series(self.df[col_name])
        if self._is_nearing(price, ma): return "Near Support/Res"
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

    # --- Oscillator Scans ---
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

    # --- Trend Scans ---
    def check_macd_status(self) -> str:
        if 'MACD_LINE' not in self.df.columns: return "Pending"
        line, sig = self.df['MACD_LINE'].iloc[-1], self.df['MACD_SIGNAL'].iloc[-1]
        self._record_series(self.df['MACD_LINE'])
        return "Buy" if line > sig else "Sell"

    def check_adx_status(self) -> str:
        if 'ADX' not in self.df.columns: return "Pending"
        self._record_series(self.df['ADX'])
        if self.df['ADX'].iloc[-1] < ADX_STRONG_TREND: return "Neutral"
        return "Buy" if self.df['PLUS_DI'].iloc[-1] > self.df['MINUS_DI'].iloc[-1] else "Sell"

    def check_supertrend_status(self) -> str:
        if 'SUPERTREND_DIR' not in self.df.columns: return "Pending"
        if 'SUPERTREND' in self.df.columns: self._record_series(self.df['SUPERTREND'])
        return "Buy" if self.df['SUPERTREND_DIR'].iloc[-1] == 1 else "Sell"

    def check_psar_status(self) -> str:
        if 'PSAR' not in self.df.columns: return "Pending"
        self._record_series(self.df['PSAR'])
        return "Buy" if self.df['Close'].iloc[-1] > self.df['PSAR'].iloc[-1] else "Sell"

    # --- Volatility Scans ---
    def check_bb_status(self) -> str:
        if 'BB_UPPER' not in self.df.columns: return "Pending"
        self._record_series(self.df['BB_UPPER'])
        c = self.df['Close'].iloc[-1]
        if c > self.df['BB_UPPER'].iloc[-1]: return "Above Upper Band"
        if c < self.df['BB_LOWER'].iloc[-1]: return "Below Lower Band"
        return "Within Bands"

    def check_bb_width(self) -> str:
        if 'BB_WIDTH' not in self.df.columns: return "Pending"
        self._record_series(self.df['BB_WIDTH'])
        return "Neutral"

    # --- Ichimoku Scans ---
    def check_ichimoku_cloud(self) -> str:
        if 'SPAN_A' not in self.df.columns: return "Pending"
        self._record_series(self.df['SPAN_A'])
        c = self.df['Close'].iloc[-1]
        mx, mn = max(self.df['SPAN_A'].iloc[-1], self.df['SPAN_B'].iloc[-1]), min(self.df['SPAN_A'].iloc[-1], self.df['SPAN_B'].iloc[-1])
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

    # --- Beta Scan ---
    def check_beta_status(self) -> str:
        if 'BETA' not in self.df.columns: return "Pending"
        self._record_series(self.df['BETA'])
        return "Neutral"

    # --- Pivot Scans ---
    def _check_price_vs_level(self, col: str) -> str:
        if col not in self.df.columns: return "Pending"
        self._record_series(self.df[col])
        lvl, pr = self.df[col].iloc[-1], self.df['Close'].iloc[-1]
        if self._is_nearing(pr, lvl): return "Near Level"
        return "Buy" if pr > lvl else "Sell"

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

    # --- Orchestrator ---
    def run_all(self) -> Dict[str, Dict[str, Any]]:
        grouped_scans: Dict[str, List[Dict[str, Any]]] = {}
        for definition in self.SCANS:
            method = getattr(self, definition.name)
            self._current_value = self._current_min = self._current_max = None
            try: result_text = method()
            except Exception: result_text = "Pending"
            
            action = self._map_status_to_action(result_text)
            grouped_scans.setdefault(definition.category, []).append({
                "label": definition.label,
                "status": result_text,
                "value": self._current_value,
                "min_value": self._current_min,
                "max_value": self._current_max,
                "action": action
            })

        final_results = {}
        for category, scans in grouped_scans.items():
            score = sum({"Strong Buy": 2, "Buy": 1, "Sell": -1, "Strong Sell": -2}.get(i["action"], 0) for i in scans)
            count = len(scans)
            avg_score = score / count if count > 0 else 0
            
            if avg_score >= 1.5: cat_sig = "Strong Buy"
            elif avg_score >= 0.5: cat_sig = "Buy"
            elif avg_score <= -1.5: cat_sig = "Strong Sell"
            elif avg_score <= -0.5: cat_sig = "Sell"
            else: cat_sig = "Neutral"

            final_results[category] = {"signal": cat_sig, "scans": scans}
        return final_results

# ==============================================================================
# 6. ORCHESTRATOR (Main)
# ==============================================================================
def process_stock(ticker: str, fetcher: TechnicalFetcher) -> Dict[str, Any]:
    logging.info(f"Processing {ticker}...")
    try:
        daily_df, weekly_df = fetcher.fetch_stock_data(ticker)
        if daily_df.empty: return {}

        bench = fetcher.fetch_benchmark()
        ind = fetcher.get_industry_for_ticker(ticker)

        TechnicalIndicators.add_all_indicators(daily_df, benchmark_data=bench)
        TechnicalIndicators.add_all_indicators(weekly_df, is_weekly=True)

        scanner = TechnicalScans(daily_df, weekly_df)
        cats = scanner.run_all()
        
        report = {
            "ticker": ticker,
            "timestamp": datetime.now().isoformat(),
            "last_close": float(daily_df["Close"].iloc[-1]),
            "industry": ind,
            "categories": cats
        }
        
        with open(OUTPUT_DIR / f"{ticker}_technical.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=4)
        return report
    except Exception as e:
        logging.error(f"Failed {ticker}: {e}")
        return {}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, help="Single ticker")
    parser.add_argument("--limit", type=int, help="Limit total")
    parser.add_argument("--industry", type=str, help="Filter by industry")
    args = parser.parse_args()

    fetcher = TechnicalFetcher()
    tickers = [args.ticker.upper()] if args.ticker else get_stocks_for_industry(args.industry) if args.industry else get_nifty_tickers()
    if args.limit: tickers = tickers[:args.limit]

    for t in tickers:
        process_stock(t, fetcher)

if __name__ == "__main__":
    main()