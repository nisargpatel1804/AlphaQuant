"""
Price Scan Scanner (AlphaQuant)
Consolidated single-file module for executing 117 Price Scans.
Includes multi-timeframe Breakouts, VWAP, Behavioural Gaps, and Relative Strength (vs Benchmark & Sector).
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import time
import random
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
logger = logging.getLogger(__name__)

# ==============================================================================
# 1. CONFIGURATION & PATHS
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR.parent / "Output" / "pricescan"
SOURCE_DIR = BASE_DIR.parent / "main" / "source"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NIFTY_500_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
BENCHMARK_TICKER = "^NSEI"

# Fetching Limits
FETCH_HISTORY_DURATION = "5y" 
FETCH_INTERVAL = "1d"
YF_BATCH_SIZE = 100
YF_MAX_RETRIES = 2
YF_RETRY_BACKOFF_SECONDS = 2.0

# Thresholds & Lookbacks
NEARING_THRESHOLD_PCT = 1.5 
LOOKBACK_52_WEEK, LOOKBACK_2_YEAR, LOOKBACK_5_YEAR = 252, 504, 1260
RANGE_BOTTOM_25_PCT, RANGE_TOP_25_PCT = 0.25, 0.75

RISE_MODERATE_PCT, RISE_MODERATELY_HIGH_PCT, RISE_HIGH_PCT, RISE_VERY_HIGH_PCT, RISE_2X_PCT = 10.0, 20.0, 30.0, 50.0, 100.0
FALL_MODERATE_PCT, FALL_MODERATELY_HIGH_PCT, FALL_HIGH_PCT, FALL_VERY_HIGH_PCT = 10.0, 20.0, 30.0, 50.0

RS_PERIOD_SHORT, RS_PERIOD_MEDIUM, RS_PERIOD_LONG = 21, 55, 100
RS_ZERO_LINE, RS_STRONG_ZONE, RS_WEAK_ZONE = 0.0, 0.5, -0.5

RETURN_PERIODS = {"1W": 5, "1M": 21, "3M": 63, "6M": 126, "1Y": 252}
GAP_THRESHOLD_PCT = 2.0
VWAP_NEARING_THRESHOLD = 1.0

# Categories / Subtypes
SUBTYPE_PREV_DAY = "Previous Day Breakout"
SUBTYPE_WEEKLY_BREAKOUT = "Weekly Breakout"
SUBTYPE_MONTHLY_BREAKOUT = "Monthly Breakout"
SUBTYPE_52W_BREAKOUT = "52 Week Breakout"
SUBTYPE_52W_RANGE = "52 Week Range"
SUBTYPE_2Y_BREAKOUT = "2 Year Breakout"
SUBTYPE_5Y_BREAKOUT = "5 Year Breakout"
SUBTYPE_ATH_BREAKOUT = "All Time Breakout"
SUBTYPE_1D_BEHAVIOUR = "1 Day Behaviour"
SUBTYPE_2D_BEHAVIOUR = "2 Days Behaviour"
SUBTYPE_3D_BEHAVIOUR = "3 Days Behaviour"
SUBTYPE_REL_PERF = "Relative Performance"
SUBTYPE_RS_21D = "Relative Strength (21 Days)"
SUBTYPE_RS_55D = "Relative Strength (55 Days)"
SUBTYPE_RS_21W = "Relative Strength (21 Weeks)"
SUBTYPE_ADAPTIVE_RS = "Adaptive & Static RS"
SUBTYPE_ABS_RETURN = "Absolute Return"
SUBTYPE_VWAP = "VWAP Scans"

# ==============================================================================
# 2. DATA MODELS & UTILS
# ==============================================================================
@dataclass
class PriceScanResult:
    label: str
    subtype: str
    status: str            
    condition_met: bool    
    value: Optional[float] = None 
    meta: Dict[str, Any] = field(default_factory=dict) 
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "category": self.subtype,
            "status": self.status,
            "value": self.value,
            "meta": self.meta,
            "condition_met": self.condition_met
        }

@dataclass
class TickerPriceScanData:
    ticker: str
    timestamp: str
    last_close: float
    industry: Optional[str]
    categories: Dict[str, Any]
    scan_summary: Dict[str, Any] = field(default_factory=dict)

def load_master_industry_map() -> List[Dict[str, Any]]:
    path = SOURCE_DIR / "master_industry_map.json"
    if not path.exists(): return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return []

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
            if attempt == retries: break
            time.sleep(1.5 * attempt)
            
    fallback = SOURCE_DIR / "ind_nifty500list.csv"
    if fallback.exists():
        with open(fallback, "r", encoding="utf-8") as f:
            return [row["Symbol"].strip().upper() for row in csv.DictReader(f) if row.get("Symbol")]
    return []

# ==============================================================================
# 3. SECTOR MANAGER (Synthetic Indices)
# ==============================================================================
class SectorManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SectorManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized: return
        self.industry_map: List[Dict] = load_master_industry_map()
        self.ticker_to_industry: Dict[str, str] = {}
        self.sector_indices: Dict[str, pd.Series] = {} 
        
        for entry in self.industry_map:
            ind = entry.get("industry", "").strip()
            for s in entry.get("stocks", []):
                self.ticker_to_industry[s.strip().upper()] = ind
        self._initialized = True

    def get_industry_for_ticker(self, ticker: str) -> Optional[str]:
        return self.ticker_to_industry.get(ticker.strip().upper())

    def get_sector_series(self, industry_name: str) -> Optional[pd.Series]:
        return self.sector_indices.get(industry_name)

    def build_all_sector_indices(self, force_refresh: bool = False):
        if self.sector_indices and not force_refresh: return
        all_tickers = list(self.ticker_to_industry.keys())
        if not all_tickers: return

        yf_tickers = [f"{t}.NS" if not t.endswith((".NS", ".BO")) else t for t in all_tickers]
        if BENCHMARK_TICKER not in yf_tickers: yf_tickers.append(BENCHMARK_TICKER)

        logger.info(f"Fetching {len(yf_tickers)} stocks to build synthetic sector indices...")
        
        try:
            close_prices = self._download_close_prices_batched(yf_tickers)
            if close_prices.empty: return
            close_prices.columns = [c.replace('.NS', '').replace('.BO', '') for c in close_prices.columns]
            self._calculate_indices_from_prices(close_prices)
            logger.info(f"Constructed {len(self.sector_indices)} synthetic sector indices.")
        except Exception as e:
            logger.error(f"Failed to build sector indices: {e}")

    def _download_close_prices_batched(self, yf_tickers: List[str]) -> pd.DataFrame:
        if not yf_tickers: return pd.DataFrame()
        combined: List[pd.DataFrame] = []

        for i in range(0, len(yf_tickers), YF_BATCH_SIZE):
            chunk = yf_tickers[i:i + YF_BATCH_SIZE]
            for attempt in range(1, YF_MAX_RETRIES + 2):
                try:
                    data = yf.download(chunk, period=FETCH_HISTORY_DURATION, interval=FETCH_INTERVAL, group_by='ticker', auto_adjust=True, threads=True, progress=False)
                    if data is None or getattr(data, "empty", True): raise ValueError("Empty yfinance response")
                    
                    extracted = {}
                    is_multi = isinstance(data.columns, pd.MultiIndex)
                    for col in data.columns:
                        if 'Close' in col:
                            ticker_part = [x for x in col if x != 'Close'][0] if is_multi else "Unknown"
                            extracted[ticker_part] = data[col]
                            
                    close_chunk = pd.DataFrame(extracted)
                    if not close_chunk.empty:
                        combined.append(close_chunk)
                    break
                except Exception as exc:
                    if attempt >= YF_MAX_RETRIES + 1: break
                    time.sleep(YF_RETRY_BACKOFF_SECONDS * attempt)

        if not combined: return pd.DataFrame()
        merged = pd.concat(combined, axis=1)
        return merged.loc[:, ~merged.columns.duplicated()]

    def _calculate_indices_from_prices(self, price_df: pd.DataFrame):
        all_returns = price_df.pct_change(fill_method=None)
        for entry in self.industry_map:
            ind_name = entry.get("industry")
            valid_stocks = [s for s in entry.get("stocks", []) if s in all_returns.columns]
            if not ind_name or not valid_stocks: continue
            
            sector_daily_ret = all_returns[valid_stocks].median(axis=1)
            first_valid = sector_daily_ret.first_valid_index()
            if first_valid is None: continue
                
            sector_index = (1 + sector_daily_ret.loc[first_valid:].fillna(0)).cumprod() * 100
            self.sector_indices[ind_name] = sector_index

# ==============================================================================
# 4. FETCHER
# ==============================================================================
class PriceScanFetcher:
    _benchmark_cache: Optional[pd.Series] = None

    def fetch_stock_data(self, ticker: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        symbol = f"{ticker.strip().upper()}.NS" if not ticker.endswith((".NS", ".BO")) else ticker
        
        df = pd.DataFrame()
        for attempt in range(1, YF_MAX_RETRIES + 2):
            try:
                df = yf.download(symbol, period=FETCH_HISTORY_DURATION, interval=FETCH_INTERVAL, auto_adjust=True, progress=False, threads=False)
                if not df.empty: break
            except Exception:
                time.sleep(YF_RETRY_BACKOFF_SECONDS * attempt)
        
        if df.empty and symbol.endswith(".NS"):
            df = yf.download(symbol.replace(".NS", ".BO"), period=FETCH_HISTORY_DURATION, interval=FETCH_INTERVAL, auto_adjust=True, progress=False, threads=False)

        if df.empty: return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        if isinstance(df.columns, pd.MultiIndex):
            try: df.columns = df.columns.get_level_values(0)
            except IndexError: pass
            
        col_map = {'adj close': 'Close', 'Adj Close': 'Close', 'close': 'Close', 'open': 'Open', 'high': 'High', 'low': 'Low', 'volume': 'Volume'}
        df.columns = [col_map.get(c.lower(), c.capitalize() if isinstance(c, str) else c) for c in df.columns]
        
        weekly_df = self._resample_data(df, 'W-FRI')
        monthly_df = self._resample_data(df, 'ME') 

        return df, weekly_df, monthly_df

    def fetch_benchmark(self) -> pd.Series:
        if self.__class__._benchmark_cache is not None:
            return self.__class__._benchmark_cache

        df = yf.download(BENCHMARK_TICKER, period=FETCH_HISTORY_DURATION, interval=FETCH_INTERVAL, auto_adjust=True, progress=False)
        if df.empty: return pd.Series(dtype=float)

        if isinstance(df.columns, pd.MultiIndex):
            try: df.columns = df.columns.get_level_values(0)
            except IndexError: pass
            
        close_col = df['Close'] if 'Close' in df.columns else df['Adj Close']
        if isinstance(close_col, pd.DataFrame): close_col = close_col.iloc[:, 0]
            
        self.__class__._benchmark_cache = close_col
        return self.__class__._benchmark_cache

    def _resample_data(self, df: pd.DataFrame, rule: str) -> pd.DataFrame:
        agg_dict = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}
        agg_dict = {k: v for k, v in agg_dict.items() if k in df.columns}
        try:
            resampled = df.resample(rule).agg(agg_dict)
            ohlc_cols = [c for c in ['Open', 'High', 'Low', 'Close'] if c in df.columns]
            return resampled.dropna(subset=ohlc_cols, how='all')
        except Exception:
            if rule == 'ME': return df.resample('M').agg(agg_dict).dropna(subset=ohlc_cols, how='all')
            return pd.DataFrame()

# ==============================================================================
# 5. SCANNER
# ==============================================================================
class PriceScanner:
    def __init__(self, daily_df: pd.DataFrame, weekly_df: pd.DataFrame, monthly_df: pd.DataFrame, benchmark_series: Optional[pd.Series] = None, sector_series: Optional[pd.Series] = None):
        self.d, self.w, self.m = daily_df, weekly_df, monthly_df
        self.bench, self.sector = benchmark_series, sector_series
        self.results: List[PriceScanResult] = []

    @staticmethod
    def _map_status_to_action(status_text: str) -> str:
        t = (status_text or "").strip().lower()
        if "very high" in t or "2x rise" in t or "strong zone" in t or "top 25%" in t: return "Strong Buy"
        if "very high fall" in t or "bottom 25%" in t: return "Strong Sell"
        if any(x in t for x in ["bullish", "buy", "positive", "above", "rising", "outperforming"]): return "Buy"
        if any(x in t for x in ["bearish", "sell", "negative", "below", "falling", "underperforming"]): return "Sell"
        return "Neutral"

    def _calculate_category_signal(self, scans: List[Dict[str, Any]]) -> str:
        score = sum({"Strong Buy": 2, "Buy": 1, "Sell": -1, "Strong Sell": -2}.get(s.get("action", "Neutral"), 0) for s in scans)
        if not scans: return "Neutral"
        if score >= 2: return "Strong Buy"
        if score >= 1: return "Buy"
        if score <= -2: return "Strong Sell"
        if score <= -1: return "Sell"
        return "Neutral"

    def _val(self, df: pd.DataFrame, col: str, offset: int = 0) -> float:
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

    def _add_res(self, label: str, subtype: str, status: str, cond: bool, val: Optional[float] = None):
        self.results.append(PriceScanResult(label, subtype, status, cond, val))

    # --- 1. Prev Day ---
    def scan_prev_day_breakout(self):
        close, prev_h, prev_l = self._val(self.d, 'Close'), self._val(self.d, 'High', 1), self._val(self.d, 'Low', 1)
        if not pd.isna(close) and not pd.isna(prev_h) and close > prev_h: self._add_res("Closing Above Previous High", SUBTYPE_PREV_DAY, "Bullish", True, close)
        if not pd.isna(close) and not pd.isna(prev_l) and close < prev_l: self._add_res("Closing Below Previous Low", SUBTYPE_PREV_DAY, "Bearish", True, close)

    # --- 2. Weekly Breakout ---
    def scan_weekly_breakout(self):
        close, prev_close = self._val(self.d, 'Close'), self._val(self.d, 'Close', 1)
        last_h, last_l = self._val(self.w, 'High', 1), self._val(self.w, 'Low', 1)
        curr_h, curr_l = self._val(self.w, 'High', 0), self._val(self.w, 'Low', 0)
        
        if not pd.isna(last_h):
            if prev_close <= last_h < close: self._add_res("Close Crossing Last Week High", SUBTYPE_WEEKLY_BREAKOUT, "Bullish", True, close)
            elif close > last_h: self._add_res("Close Above Last Week High", SUBTYPE_WEEKLY_BREAKOUT, "Bullish", True, close)

        if not pd.isna(last_l):
            if prev_close >= last_l > close: self._add_res("Close Crossing Last Week Low", SUBTYPE_WEEKLY_BREAKOUT, "Bearish", True, close)
            elif close < last_l: self._add_res("Close Below Last Week Low", SUBTYPE_WEEKLY_BREAKOUT, "Bearish", True, close)
        
        if not pd.isna(curr_h) and close >= curr_h * 0.999: self._add_res("Close Crossing Current Week High", SUBTYPE_WEEKLY_BREAKOUT, "Bullish", True, close)
        if not pd.isna(curr_l) and close <= curr_l * 1.001: self._add_res("Close Crossing Current Week Low", SUBTYPE_WEEKLY_BREAKOUT, "Bearish", True, close)

    # --- 3. Monthly Breakout ---
    def scan_monthly_breakout(self):
        close, prev_close = self._val(self.d, 'Close'), self._val(self.d, 'Close', 1)
        last_h, last_l, last_c = self._val(self.m, 'High', 1), self._val(self.m, 'Low', 1), self._val(self.m, 'Close', 1)
        curr_h, curr_l = self._val(self.m, 'High', 0), self._val(self.m, 'Low', 0)

        if not pd.isna(last_h):
            if prev_close <= last_h < close: self._add_res("Close Crossing Last Month High", SUBTYPE_MONTHLY_BREAKOUT, "Bullish", True, close)
            elif close > last_h: self._add_res("Close Above Last Month High", SUBTYPE_MONTHLY_BREAKOUT, "Bullish", True, close)

        if not pd.isna(last_l):
            if prev_close >= last_l > close: self._add_res("Close Crossing Last Month Low", SUBTYPE_MONTHLY_BREAKOUT, "Bearish", True, close)
            elif close < last_l: self._add_res("Close Below Last Month Low", SUBTYPE_MONTHLY_BREAKOUT, "Bearish", True, close)

        if not pd.isna(last_c):
             if prev_close <= last_c < close: self._add_res("Close Crossing Last Month Close (From Below)", SUBTYPE_MONTHLY_BREAKOUT, "Bullish", True, close)
             elif prev_close >= last_c > close: self._add_res("Close Crossing Last Month Close (From Above)", SUBTYPE_MONTHLY_BREAKOUT, "Bearish", True, close)

        if not pd.isna(curr_h) and close >= curr_h * 0.999: self._add_res("Close Crossing Current Month High", SUBTYPE_MONTHLY_BREAKOUT, "Bullish", True, close)
        if not pd.isna(curr_l) and close <= curr_l * 1.001: self._add_res("Close Crossing Current Month Low", SUBTYPE_MONTHLY_BREAKOUT, "Bearish", True, close)

    # --- 4. Long Term Breakouts ---
    def _scan_rolling_breakout(self, lookback: int, subtype: str, label_prefix: str):
        if len(self.d) < lookback: return
        past_window = self.d.iloc[-(lookback+1):-1]
        if past_window.empty: return

        p_h, p_l = past_window['High'].max(), past_window['Low'].min()
        close, prev_close = self._val(self.d, 'Close'), self._val(self.d, 'Close', 1)

        if prev_close <= p_h < close: self._add_res(f"Close Crossing {label_prefix} High", subtype, "Bullish", True, close)
        elif close > p_h: self._add_res(f"Close Within {label_prefix} High Zone", subtype, "Bullish", True, close)
        
        if prev_close >= p_l > close: self._add_res(f"Close Crossing {label_prefix} Low", subtype, "Bearish", True, close)
        elif close < p_l: self._add_res(f"Close Within {label_prefix} Low Zone", subtype, "Bearish", True, close)

        if self._is_near(close, p_h): self._add_res(f"Close Near {label_prefix} High", subtype, "Bullish", True, close)
        if self._is_near(close, p_l): self._add_res(f"Close Near {label_prefix} Low", subtype, "Bearish", True, close)

    def scan_long_term_breakouts(self):
        self._scan_rolling_breakout(LOOKBACK_52_WEEK, SUBTYPE_52W_BREAKOUT, "52 Week")
        self._scan_rolling_breakout(LOOKBACK_2_YEAR, SUBTYPE_2Y_BREAKOUT, "2 Year")
        self._scan_rolling_breakout(LOOKBACK_5_YEAR, SUBTYPE_5Y_BREAKOUT, "5 Year")
        self._scan_rolling_breakout(len(self.d), SUBTYPE_ATH_BREAKOUT, "All Time")

    # --- 5. 52 Week Range ---
    def scan_52w_range(self):
        if len(self.d) < LOOKBACK_52_WEEK: return
        window = self.d.iloc[-LOOKBACK_52_WEEK:]
        h52, l52 = window['High'].max(), window['Low'].min()
        close = self._val(self.d, 'Close')
        if h52 == l52: return

        position = (close - l52) / (h52 - l52)
        if position >= RANGE_TOP_25_PCT: self._add_res("Close in Top 25% of 52W Range", SUBTYPE_52W_RANGE, "Bullish", True, position*100)
        elif position <= RANGE_BOTTOM_25_PCT: self._add_res("Close in Bottom 25% of 52W Range", SUBTYPE_52W_RANGE, "Bearish", True, position*100)
        else: self._add_res("Close in Middle 50% of 52W Range", SUBTYPE_52W_RANGE, "Neutral", True, position*100)

        rise_pct, fall_pct = ((close - l52) / l52) * 100, ((h52 - close) / h52) * 100

        if rise_pct >= RISE_2X_PCT: self._add_res("2x Rise from 52 Week Low", SUBTYPE_52W_RANGE, "Bullish", True, rise_pct)
        elif rise_pct >= RISE_VERY_HIGH_PCT: self._add_res("Very High Rise from 52 Week Low", SUBTYPE_52W_RANGE, "Bullish", True, rise_pct)
        elif rise_pct >= RISE_HIGH_PCT: self._add_res("High Rise from 52 Week Low", SUBTYPE_52W_RANGE, "Bullish", True, rise_pct)
        elif rise_pct >= RISE_MODERATELY_HIGH_PCT: self._add_res("Moderately High Rise from 52 Week Low", SUBTYPE_52W_RANGE, "Bullish", True, rise_pct)
        elif rise_pct >= RISE_MODERATE_PCT: self._add_res("Moderate Rise from 52 Week Low", SUBTYPE_52W_RANGE, "Bullish", True, rise_pct)
        
        if fall_pct >= FALL_VERY_HIGH_PCT: self._add_res("Very High Fall from 52 Week High", SUBTYPE_52W_RANGE, "Bearish", True, fall_pct)
        elif fall_pct >= FALL_HIGH_PCT: self._add_res("High Fall from 52 Week High", SUBTYPE_52W_RANGE, "Bearish", True, fall_pct)
        elif fall_pct >= FALL_MODERATELY_HIGH_PCT: self._add_res("Moderately High Fall from 52 Week High", SUBTYPE_52W_RANGE, "Bearish", True, fall_pct)
        elif fall_pct >= FALL_MODERATE_PCT: self._add_res("Moderate Fall from 52 Week High", SUBTYPE_52W_RANGE, "Bearish", True, fall_pct)

    # --- 6. Behaviour ---
    def scan_behaviour(self):
        open_p, prev_h, prev_l = self._val(self.d, 'Open'), self._val(self.d, 'High', 1), self._val(self.d, 'Low', 1)
        
        if not pd.isna(open_p) and not pd.isna(prev_h) and ((open_p - prev_h) / prev_h) * 100 >= GAP_THRESHOLD_PCT:
            self._add_res("Large Gap Up", SUBTYPE_1D_BEHAVIOUR, "Bullish", True, ((open_p - prev_h) / prev_h) * 100)
                
        if not pd.isna(open_p) and not pd.isna(prev_l) and ((prev_l - open_p) / prev_l) * 100 >= GAP_THRESHOLD_PCT:
            self._add_res("Large Gap Down", SUBTYPE_1D_BEHAVIOUR, "Bearish", True, ((prev_l - open_p) / prev_l) * 100)

        if len(self.d) < 4: return
        highs, lows = self.d['High'].iloc[-4:].values, self.d['Low'].iloc[-4:].values
        
        if highs[-1] > highs[-2] > highs[-3]:
            self._add_res("Making Higher Highs for 2 Days", SUBTYPE_2D_BEHAVIOUR, "Bullish", True)
            if len(highs) >= 4 and highs[-3] > highs[-4]: self._add_res("Making Higher Highs for 3 Days", SUBTYPE_3D_BEHAVIOUR, "Bullish", True)

        if lows[-1] < lows[-2] < lows[-3]:
            self._add_res("Making Lower Lows for 2 Days", SUBTYPE_2D_BEHAVIOUR, "Bearish", True)
            if len(lows) >= 4 and lows[-3] < lows[-4]: self._add_res("Making Lower Lows for 3 Days", SUBTYPE_3D_BEHAVIOUR, "Bearish", True)

    # --- 7. VWAP ---
    def scan_vwap(self):
        h, l, c, o = self._val(self.d, 'High'), self._val(self.d, 'Low'), self._val(self.d, 'Close'), self._val(self.d, 'Open')
        vwap = (h + l + c) / 3
        
        if o < vwap < c: self._add_res("Close Crossing Daily VWAP (From Below)", SUBTYPE_VWAP, "Bullish", True, vwap)
        elif o > vwap > c: self._add_res("Close Crossing Daily VWAP (From Above)", SUBTYPE_VWAP, "Bearish", True, vwap)
            
        if c > vwap: self._add_res("Close Above Daily VWAP", SUBTYPE_VWAP, "Bullish", True, vwap)
        else: self._add_res("Close Below Daily VWAP", SUBTYPE_VWAP, "Bearish", True, vwap)

        if self._is_near(c, vwap, threshold=0.5):
            if c > vwap: self._add_res("Close Near Daily VWAP (Support)", SUBTYPE_VWAP, "Bullish", True, vwap)
            else: self._add_res("Close Near Daily VWAP (Resistance)", SUBTYPE_VWAP, "Bearish", True, vwap)

    # --- 8. Relative Strength ---
    def _calculate_rs_series(self, stock: pd.Series, bench: pd.Series, period: int) -> pd.Series:
        aligned_s, aligned_b = stock.align(bench, join='inner')
        aligned_s, aligned_b = aligned_s.ffill(), aligned_b.ffill()
        mask = aligned_s.notna() & aligned_b.notna()
        aligned_s, aligned_b = aligned_s[mask], aligned_b[mask]
        
        if len(aligned_s) < period + 1: return pd.Series(dtype=float)
        b_safe = aligned_b.replace(0, np.nan)
        return (aligned_s.div(b_safe)).pct_change(periods=period) * 100

    def scan_relative_performance(self):
        for label, period in RETURN_PERIODS.items():
            if len(self.d) > period:
                ret = self.d['Close'].pct_change(period).iloc[-1] * 100
                if not pd.isna(ret):
                    if ret > 0: self._add_res(f"{label} Return (Positive)", SUBTYPE_ABS_RETURN, "Bullish", True, ret)
                    else: self._add_res(f"{label} Return (Negative)", SUBTYPE_ABS_RETURN, "Bearish", True, ret)
        
        if len(self.d) > 500:
            ret_2y = self.d['Close'].pct_change(500).iloc[-1] * 100
            if ret_2y > 0: self._add_res("2Y Return (Positive)", SUBTYPE_ABS_RETURN, "Bullish", True, ret_2y)
            else: self._add_res("2Y Return (Negative)", SUBTYPE_ABS_RETURN, "Bearish", True, ret_2y)

        if self.bench is None or self.bench.empty: return

        rs_21 = self._calculate_rs_series(self.d['Close'], self.bench, RS_PERIOD_SHORT)
        if not rs_21.empty:
            curr = rs_21.iloc[-1]
            if self._crossed_above(rs_21, RS_ZERO_LINE): self._add_res("RS (21D) Crossing 0 From Below", SUBTYPE_RS_21D, "Bullish", True, curr)
            if self._crossed_below(rs_21, RS_ZERO_LINE): self._add_res("RS (21D) Crossing 0 From Above", SUBTYPE_RS_21D, "Bearish", True, curr)
            if curr > 0: self._add_res("RS (21D) Positive", SUBTYPE_RS_21D, "Bullish", True, curr)
            else: self._add_res("RS (21D) Negative", SUBTYPE_RS_21D, "Bearish", True, curr)
            if self._is_rising(rs_21): self._add_res("RS (21D) Trending Up", SUBTYPE_RS_21D, "Bullish", True, curr)
            if self._is_falling(rs_21): self._add_res("RS (21D) Trending Down", SUBTYPE_RS_21D, "Bearish", True, curr)

        rs_55 = self._calculate_rs_series(self.d['Close'], self.bench, RS_PERIOD_MEDIUM)
        if not rs_55.empty:
            curr = rs_55.iloc[-1]
            if self._crossed_above(rs_55, RS_ZERO_LINE): self._add_res("RS (55D) Crossing 0 From Below", SUBTYPE_RS_55D, "Bullish", True, curr)
            if self._crossed_below(rs_55, RS_ZERO_LINE): self._add_res("RS (55D) Crossing 0 From Above", SUBTYPE_RS_55D, "Bearish", True, curr)
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

        bench_w = self.bench.resample('W-FRI').last().dropna()
        rs_21w = self._calculate_rs_series(self.w['Close'], bench_w, 21)
        if not rs_21w.empty:
            curr = rs_21w.iloc[-1]
            if self._crossed_above(rs_21w, 0): self._add_res("RS (21W) Crossing 0 From Below", SUBTYPE_RS_21W, "Bullish", True, curr)
            if self._crossed_below(rs_21w, 0): self._add_res("RS (21W) Crossing 0 From Above", SUBTYPE_RS_21W, "Bearish", True, curr)
            if curr > 0: self._add_res("RS (21W) Positive", SUBTYPE_RS_21W, "Bullish", True, curr)
            else: self._add_res("RS (21W) Negative", SUBTYPE_RS_21W, "Bearish", True, curr)
            if self._is_rising(rs_21w): self._add_res("RS (21W) Trending Up", SUBTYPE_RS_21W, "Bullish", True, curr)
            if self._is_falling(rs_21w): self._add_res("RS (21W) Trending Down", SUBTYPE_RS_21W, "Bearish", True, curr)

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

        if self.sector is not None and not self.sector.empty:
            rs_sec = self._calculate_rs_series(self.d['Close'], self.sector, RS_PERIOD_SHORT)
            if not rs_sec.empty:
                curr_sec = rs_sec.iloc[-1]
                if curr_sec > 0: self._add_res("Outperforming Sector (21D)", SUBTYPE_REL_PERF, "Bullish", True, curr_sec)
                else: self._add_res("Underperforming Sector (21D)", SUBTYPE_REL_PERF, "Bearish", True, curr_sec)
                if self._crossed_above(rs_sec, 0): self._add_res("Started Outperforming Sector", SUBTYPE_REL_PERF, "Bullish", True, curr_sec)
                if self._crossed_below(rs_sec, 0): self._add_res("Started Underperforming Sector", SUBTYPE_REL_PERF, "Bearish", True, curr_sec)

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
        
        grouped_scans = {}
        for res in self.results:
            d = res.to_dict()
            d["action"] = self._map_status_to_action(d.get("status", ""))
            grouped_scans.setdefault(res.subtype, []).append(d)
            
        all_subtypes = [
            SUBTYPE_PREV_DAY, SUBTYPE_WEEKLY_BREAKOUT, SUBTYPE_MONTHLY_BREAKOUT, SUBTYPE_52W_BREAKOUT, SUBTYPE_52W_RANGE,
            SUBTYPE_2Y_BREAKOUT, SUBTYPE_5Y_BREAKOUT, SUBTYPE_ATH_BREAKOUT, SUBTYPE_1D_BEHAVIOUR, SUBTYPE_2D_BEHAVIOUR, 
            SUBTYPE_3D_BEHAVIOUR, SUBTYPE_REL_PERF, SUBTYPE_RS_21D, SUBTYPE_RS_55D, SUBTYPE_RS_21W, SUBTYPE_ADAPTIVE_RS,
            SUBTYPE_ABS_RETURN, SUBTYPE_VWAP
        ]
        
        final_results = {}
        for subtype in all_subtypes:
            scans = grouped_scans.get(subtype, [])
            signal = self._calculate_category_signal(scans)
            final_results[subtype] = {"signal": signal, "scans": scans}
            
        return final_results

# ==============================================================================
# 6. ORCHESTRATOR
# ==============================================================================
def process_stock(ticker: str, fetcher: PriceScanFetcher, sector_manager: SectorManager) -> Optional[TickerPriceScanData]:
    logger.info(f"Processing Price Scans for {ticker}...")
    
    d_df, w_df, m_df = fetcher.fetch_stock_data(ticker)
    if d_df.empty: return None

    benchmark_series = fetcher.fetch_benchmark()
    industry_name = sector_manager.get_industry_for_ticker(ticker)
    sector_series = sector_manager.get_sector_series(industry_name) if industry_name else None

    scanner = PriceScanner(d_df, w_df, m_df, benchmark_series, sector_series)
    category_results = scanner.run_all_scans()

    total_scans_triggered = sum(len(c['scans']) for c in category_results.values())
    signal_counts = {"Strong Buy": 0, "Buy": 0, "Neutral": 0, "Sell": 0, "Strong Sell": 0}
    for cat_data in category_results.values():
        sig = cat_data.get('signal', 'Neutral')
        if sig in signal_counts: signal_counts[sig] += 1

    last_close = float(d_df['Close'].iloc[-1]) if not d_df.empty else 0.0
    
    output_data = TickerPriceScanData(
        ticker=ticker,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        last_close=last_close,
        industry=industry_name,
        categories=category_results,
        scan_summary={"triggered_total": total_scans_triggered, "signals": signal_counts}
    )

    file_path = OUTPUT_DIR / f"{ticker}_pricescan.json"
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({
                "ticker": output_data.ticker,
                "timestamp": output_data.timestamp,
                "last_close": output_data.last_close,
                "industry": output_data.industry,
                "categories": output_data.categories,
                "scan_summary": output_data.scan_summary
            }, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save results for {ticker}: {e}")

    return output_data

def main():
    parser = argparse.ArgumentParser(description="AlphaQuant Price Scan Engine")
    parser.add_argument("--ticker", type=str, help="Run for a single ticker (e.g., RELIANCE)")
    parser.add_argument("--industry", type=str, help="Run for a specific industry (e.g., 'Cement')")
    parser.add_argument("--limit", type=int, help="Limit total stocks processed")
    parser.add_argument("--update-sectors", action="store_true", help="Force rebuild of sector indices")
    args = parser.parse_args()

    sector_manager = SectorManager()
    logger.info("Initializing Sector Indices...")
    sector_manager.build_all_sector_indices(force_refresh=args.update_sectors)
    
    fetcher = PriceScanFetcher()

    if args.ticker: tickers = [args.ticker.strip().upper()]
    elif args.industry:
        target_ind = args.industry.lower()
        tickers = [t for t, ind in sector_manager.ticker_to_industry.items() if target_ind in ind.lower()]
    else:
        tickers = get_nifty_tickers()

    if args.limit: tickers = tickers[:args.limit]

    for t in tickers:
        process_stock(t, fetcher, sector_manager)

if __name__ == "__main__":
    main()