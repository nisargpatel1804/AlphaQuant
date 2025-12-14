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

        path = self._project_root() / "fundamentals" / "source" / "master_industry_map.json"
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

        start_date = (datetime.now() - timedelta(days=BETA_LOOKBACK_YEARS * 365 + 30)).strftime('%Y-%m-%d')
        symbols = [self._to_nse_symbol(m) for m in members]

        try:
            data = yf.download(symbols, start=start_date, progress=False, auto_adjust=True, group_by="column", threads=True)
            if data is None or getattr(data, "empty", True):
                return industry, None

            # Extract Close prices as a DataFrame with one column per symbol.
            if isinstance(data.columns, pd.MultiIndex):
                try:
                    close_df = data["Close"]
                except Exception:
                    return industry, None
            else:
                # Single ticker fallback
                close_df = pd.DataFrame({symbols[0]: data.get("Close")})

            if isinstance(close_df, pd.Series):
                close_df = close_df.to_frame(name=symbols[0])

            close_df = close_df.dropna(how="all")
            if close_df.empty:
                return industry, None

            # Compute member betas vs benchmark.
            bench = benchmark_series.dropna()
            bench_rets = bench.pct_change().dropna()
            variance = bench_rets.var()
            if variance == 0 or pd.isna(variance):
                return industry, None

            betas: List[float] = []
            for col in close_df.columns:
                s = close_df[col].dropna()
                if len(s) < 35:
                    continue
                stock_rets = s.pct_change().dropna()
                common_idx = stock_rets.index.intersection(bench_rets.index)
                if len(common_idx) < 30:
                    continue
                cov = stock_rets.loc[common_idx].cov(bench_rets.loc[common_idx])
                if pd.isna(cov):
                    continue
                beta = float(cov / variance)
                if not np.isfinite(beta):
                    continue
                betas.append(beta)

            if not betas:
                return industry, None

            avg_beta = float(np.mean(betas))
            self._industry_beta_cache[industry] = avg_beta
            return industry, avg_beta
        except Exception:
            return industry, None

    def fetch_benchmark(self) -> pd.Series:
        """
        Fetches Nifty 50 (or config benchmark) closing prices for Beta calculations.
        Caches the result to avoid repeated calls.
        """
        if self._benchmark_cache is not None:
            return self._benchmark_cache

        # Download sufficient history for Beta (default 1y)
        # We add a small buffer to ensure we have enough data points
        start_date = (datetime.now() - timedelta(days=BETA_LOOKBACK_YEARS * 365 + 30)).strftime('%Y-%m-%d')
        
        try:
            data = yf.download(BENCHMARK_TICKER, start=start_date, progress=False)
            
            if data.empty:
                raise ValueError(f"Benchmark data for {BENCHMARK_TICKER} is empty.")

            # Flatten MultiIndex columns if present (common in newer yfinance)
            if isinstance(data.columns, pd.MultiIndex):
                # If structure is (Price, Ticker), get 'Close' level
                # Dropping the Ticker level
                try:
                    close_data = data['Close'][BENCHMARK_TICKER]
                except KeyError:
                    # Fallback if ticker level isn't explicit
                    close_data = data['Close']
            else:
                close_data = data['Close']

            # Ensure it's a Series, not a DataFrame
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
        # 2 years is chosen to support 200 SMA and 6-month Momentum with 
        # enough buffer to not result in NaNs at the start of the analysis window.
        try:
            # interval="1d" is standard. auto_adjust=True handles splits/dividends nicely.
            df = yf.download(symbol, period="1y", interval="1d", progress=False, auto_adjust=True)
            
            if df.empty:
                raise ValueError(f"No data returned for symbol: {symbol}")

            # 3. Clean & Flatten Data
            # yfinance>=0.2.0 returns MultiIndex columns (Price, Ticker). We need simple (Open, High...)
            if isinstance(df.columns, pd.MultiIndex):
                # Drop the ticker level, keeping just Open, High, Low, Close, Volume
                df.columns = df.columns.get_level_values(0)

            # Ensure required columns exist
            required_cols = {'Open', 'High', 'Low', 'Close', 'Volume'}
            if not required_cols.issubset(df.columns):
                # Sometimes 'Adj Close' is returned instead of 'Close' if auto_adjust=False
                # But with auto_adjust=True, we should get standard columns.
                # Renaming just in case logic varies by version.
                df.rename(columns={'Adj Close': 'Close'}, inplace=True)
                if not required_cols.issubset(df.columns):
                    raise ValueError(f"Missing required columns in data. Found: {df.columns.tolist()}")

            # 4. Generate Weekly Data
            # Resample to Weekly, ending on Friday ('W-FRI')
            weekly_agg = {
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }
            weekly_df = df.resample('W-FRI').agg(weekly_agg)
            
            # Drop incomplete weeks if they have no data (e.g. holidays spanning full week - rare)
            weekly_df.dropna(inplace=True)

            return df, weekly_df

        except Exception as e:
            print(f"Failed to fetch data for {ticker}: {e}")
            # Return empty DFs to handle gracefully upstream
            return pd.DataFrame(), pd.DataFrame()