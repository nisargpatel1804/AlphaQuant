"""
Data ingestion layer for Technical Analysis.
Handles fetching Daily/Weekly OHLCV data and Benchmark indices via yfinance.
"""
import json
import yfinance as yf
import pandas as pd
from typing import Tuple, Optional, Dict, List
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np

from .config import BENCHMARK_TICKER, BETA_LOOKBACK_YEARS

class TechnicalFetcher:
    def __init__(self):
        self._benchmark_cache: Optional[pd.Series] = None
        self._industry_map_cache: Optional[List[dict]] = None
        self._ticker_to_industry_cache: Optional[Dict[str, str]] = None
        self._industry_beta_cache: Dict[str, float] = {}

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    def _load_master_industry_map(self) -> List[dict]:
        if self._industry_map_cache is not None:
            return self._industry_map_cache

        path = self._project_root().parent / "source" / "master_industry_map.json"
        if not path.exists():
            self._industry_map_cache = []
            self._ticker_to_industry_cache = {}
            return self._industry_map_cache

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            rows = [row for row in data if isinstance(row, dict)]
            self._industry_map_cache = rows

            ticker_map: Dict[str, str] = {}
            for row in rows:
                industry = str(row.get("industry", "")).strip()
                for t in row.get("stocks", []) or []:
                    if not isinstance(t, str):
                        continue
                    tt = t.strip().upper()
                    if tt and industry and tt not in ticker_map:
                        ticker_map[tt] = industry

            self._ticker_to_industry_cache = ticker_map
            return rows
        except Exception:
            self._industry_map_cache = []
            self._ticker_to_industry_cache = {}
            return self._industry_map_cache

    def get_industry_for_ticker(self, ticker: str) -> Optional[str]:
        self._load_master_industry_map()
        if self._ticker_to_industry_cache is None:
            return None
        t = ticker.strip().upper()
        return self._ticker_to_industry_cache.get(t)

    def _get_industry_members(self, industry: str) -> List[str]:
        rows = self._load_master_industry_map()
        target = industry.strip().lower()
        for row in rows:
            if str(row.get("industry", "")).strip().lower() == target:
                members = [m.strip().upper() for m in (row.get("stocks", []) or []) if isinstance(m, str)]
                return [m for m in members if m]
        return []

    def _to_nse_symbol(self, ticker: str) -> str:
        clean = ticker.strip().upper()
        if clean.endswith(".NS") or clean.endswith(".BO"):
            return clean
        return f"{clean}.NS"

    def fetch_industry_beta_avg(self, ticker: str, benchmark_series: pd.Series) -> Tuple[Optional[str], Optional[float]]:
        """Returns (industry_name, avg_beta_of_industry_members_vs_benchmark)."""
        industry = self.get_industry_for_ticker(ticker)
        if not industry:
            return None, None

        if industry in self._industry_beta_cache:
            return industry, self._industry_beta_cache[industry]

        members = self._get_industry_members(industry)
        if len(members) < 2:
            return industry, None

        # Increase lookback for beta calculation to ensure sufficient data overlap
        start_date = (datetime.now() - timedelta(days=BETA_LOOKBACK_YEARS * 365 + 60)).strftime('%Y-%m-%d')
        symbols = [self._to_nse_symbol(m) for m in members]

        try:
            # Download in bulk for efficiency
            # auto_adjust=True accounts for splits/dividends which is crucial for returns
            data = yf.download(symbols, start=start_date, progress=False, auto_adjust=True, group_by="column", threads=True)
            
            if data is None or getattr(data, "empty", True):
                return industry, None

            # Extract Close prices
            if isinstance(data.columns, pd.MultiIndex):
                try:
                    close_df = data["Close"]
                except KeyError:
                    # Fallback if 'Close' is not a top-level key (rare with group_by='column' but possible)
                    return industry, None
            else:
                # Single ticker scenario (unlikely given check len(members) < 2, but robust)
                close_df = pd.DataFrame({symbols[0]: data.get("Close")})

            if isinstance(close_df, pd.Series):
                close_df = close_df.to_frame(name=symbols[0])

            close_df = close_df.dropna(how="all")
            if close_df.empty:
                return industry, None

            # Prepare benchmark returns
            bench = benchmark_series.dropna()
            # Align benchmark date range with stock data to avoid mismatch errors
            bench = bench[bench.index >= pd.Timestamp(start_date)]
            
            bench_rets = bench.pct_change().dropna()
            variance = bench_rets.var()
            
            if variance == 0 or pd.isna(variance):
                return industry, None

            betas: List[float] = []
            for col in close_df.columns:
                s = close_df[col].dropna()
                # Ensure minimal data points for statistical significance
                if len(s) < 60:
                    continue
                
                stock_rets = s.pct_change().dropna()
                
                # Intersection of dates
                common_idx = stock_rets.index.intersection(bench_rets.index)
                if len(common_idx) < 30:
                    continue
                
                # Calculate Beta: Covariance(Stock, Bench) / Variance(Bench)
                cov = stock_rets.loc[common_idx].cov(bench_rets.loc[common_idx])
                if pd.isna(cov):
                    continue
                
                beta = float(cov / variance)
                
                # Filter outliers (e.g., erroneous data spikes)
                if np.isfinite(beta) and -5.0 < beta < 5.0:
                    betas.append(beta)

            if not betas:
                return industry, None

            avg_beta = float(np.mean(betas))
            self._industry_beta_cache[industry] = avg_beta
            return industry, avg_beta
            
        except Exception as e:
            print(f"Error calculating industry beta for {industry}: {e}")
            return industry, None

    def fetch_benchmark(self) -> pd.Series:
        """
        Fetches Nifty 50 (or config benchmark) closing prices for Beta calculations.
        Caches the result to avoid repeated calls.
        """
        if self._benchmark_cache is not None:
            return self._benchmark_cache

        # Download sufficient history for Beta (default 1y)
        start_date = (datetime.now() - timedelta(days=BETA_LOOKBACK_YEARS * 365 + 60)).strftime('%Y-%m-%d')
        
        try:
            # auto_adjust=True is critical for accurate index returns
            data = yf.download(BENCHMARK_TICKER, start=start_date, progress=False, auto_adjust=True, threads=False)
            
            if data.empty:
                # Retry once with a broader date or alternative ticker if needed, but raising here is safer
                raise ValueError(f"Benchmark data for {BENCHMARK_TICKER} is empty.")

            # Handle column structure
            if isinstance(data.columns, pd.MultiIndex):
                try:
                    close_data = data['Close'][BENCHMARK_TICKER]
                except KeyError:
                    # If multi-index doesn't have the ticker level as expected
                    if 'Close' in data.columns.get_level_values(0):
                         close_data = data['Close']
                    else:
                         # Last resort: take first column if singular
                         close_data = data.iloc[:, 0]
            else:
                close_data = data['Close']

            # Ensure Series format
            if isinstance(close_data, pd.DataFrame):
                close_data = close_data.iloc[:, 0]

            self._benchmark_cache = close_data
            return self._benchmark_cache

        except Exception as e:
            print(f"Error fetching benchmark {BENCHMARK_TICKER}: {e}")
            return pd.Series(dtype=float)

    def fetch_stock_data(self, ticker: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Fetches Daily OHLCV data and generates Weekly OHLCV data.
        
        Args:
            ticker (str): The stock symbol (e.g., "RELIANCE").
            
        Returns:
            Tuple[pd.DataFrame, pd.DataFrame]: (daily_df, weekly_df)
        """
        # 1. Format Ticker for NSE
        clean_ticker = ticker.strip().upper()
        if not clean_ticker.endswith(".NS") and not clean_ticker.endswith(".BO"):
            symbol = f"{clean_ticker}.NS"
        else:
            symbol = clean_ticker

        # 2. Fetch Data (2 Years Daily)
        # 2 years supports 200 SMA and long-term momentum with buffers
        try:
            # auto_adjust=True handles splits/dividends.
            df = yf.download(symbol, period="2y", interval="1d", progress=False, auto_adjust=True)
            
            if df.empty:
                # Try fetching with .BO if .NS fails (optional fallback logic)
                if symbol.endswith(".NS"):
                    alt_symbol = symbol.replace(".NS", ".BO")
                    df = yf.download(alt_symbol, period="2y", interval="1d", progress=False, auto_adjust=True)
                
                if df.empty:
                    raise ValueError(f"No data returned for symbol: {symbol}")

            # 3. Clean & Flatten Data
            if isinstance(df.columns, pd.MultiIndex):
                # Drop the ticker level, keeping Price Type (Open, Close, etc.)
                df.columns = df.columns.get_level_values(0)

            # Standardize Column Names
            # yfinance sometimes returns 'Adj Close' if auto_adjust=False, but we use True.
            # We map specific known variations just in case.
            col_map = {
                'Adj Close': 'Close',
                'adj close': 'Close',
                'close': 'Close',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'volume': 'Volume'
            }
            df.rename(columns=col_map, inplace=True)

            # Validation
            required_cols = {'Open', 'High', 'Low', 'Close', 'Volume'}
            if not required_cols.issubset(df.columns):
                missing = required_cols - set(df.columns)
                # If Volume is missing, we can sometimes proceed, but scans relying on it will fail.
                # Ideally, we construct a dummy volume if critical, but raising is safer for now.
                # Some indices don't have volume.
                if 'Volume' in missing and len(missing) == 1:
                    df['Volume'] = 0 # Dummy fill for indices
                else:
                    raise ValueError(f"Missing columns: {missing}")

            # 4. Generate Weekly Data
            # Resample to Weekly, ending on Friday ('W-FRI')
            weekly_agg = {
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }
            
            # Filter aggregation dict to only include present columns
            agg_to_use = {k: v for k, v in weekly_agg.items() if k in df.columns}
            
            weekly_df = df.resample('W-FRI').agg(agg_to_use)
            
            # Drop incomplete weeks ONLY if they contain NaNs (e.g., future dates or gaps)
            weekly_df.dropna(inplace=True)

            return df, weekly_df

        except Exception as e:
            print(f"Failed to fetch data for {ticker}: {e}")
            return pd.DataFrame(), pd.DataFrame()