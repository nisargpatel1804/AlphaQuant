# backend/backtester_core.py

from __future__ import annotations

import csv
import datetime as dt
import random
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd
import requests
import yfinance as yf

from backend.scans.pricescan_scanner import get_nifty_tickers


NIFTY_500_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


def get_nifty_tickers(retries: int = 4) -> List[str]:
    sess = requests.Session()
    for attempt in range(1, retries + 1):
        try:
            resp = sess.get(NIFTY_500_URL, timeout=30, headers={"User-Agent": random.choice(USER_AGENTS)})
            resp.raise_for_status()
            reader = csv.DictReader(resp.content.decode("utf-8", errors="replace").splitlines())
            return [row["Symbol"].strip().upper() for row in reader if row.get("Symbol")]
        except requests.RequestException:
            if attempt == retries:
                break
    fallback = Path(__file__).resolve().parent / "source" / "ind_nifty500list.csv"
    if fallback.exists():
        with fallback.open("r", encoding="utf-8") as handle:
            return [row["Symbol"].strip().upper() for row in csv.DictReader(handle) if row.get("Symbol")]
    return []


def get_nifty500_tickers() -> List[str]:
    return [f"{ticker}.NS" for ticker in get_nifty_tickers()]


def get_start_date(timeframe_code: str) -> dt.date:
    today = dt.date.today()
    mapping = {
        "1W": dt.timedelta(weeks=1),
        "1M": dt.timedelta(days=30),
        "2M": dt.timedelta(days=60),
        "3M": dt.timedelta(days=90),
        "6M": dt.timedelta(days=180),
        "1Y": dt.timedelta(days=365),
        "2Y": dt.timedelta(days=730),
        "3Y": dt.timedelta(days=1095),
        "5Y": dt.timedelta(days=1825),
        "10Y": dt.timedelta(days=3650),
    }
    if timeframe_code == "Max":
        return dt.date(2000, 1, 1)
    delta = mapping.get(timeframe_code)
    return today - delta if delta else today - dt.timedelta(days=365)


def calculate_auto_range(series_list: Iterable[pd.Series], padding: float = 0.1) -> List[float]:
    min_val = float("inf")
    max_val = float("-inf")
    has_data = False

    for series in series_list:
        if series is not None and not series.empty:
            min_val = min(min_val, float(series.min()))
            max_val = max(max_val, float(series.max()))
            has_data = True

    if not has_data:
        return [0.0, 1.0]

    span = max_val - min_val
    if span == 0:
        span = abs(max_val) * 0.1 if max_val != 0 else 1.0

    return [min_val - span * padding, max_val + span * padding]


def build_backtest_summary(tickers: List[str], capital: float, timeframe: str) -> Dict[str, Any]:
    normalized = [ticker.strip().upper() for ticker in tickers if ticker and ticker.strip()]
    if not normalized:
        return {
            "generated_at": dt.datetime.utcnow(),
            "summary": {
                "tickers": [],
                "capital": capital,
                "timeframe": timeframe,
                "universe_size": 0,
                "status": "no_tickers_selected",
            },
            "chart": {"data": [], "layout": {"title": "Select at least one ticker"}},
        }

    start_date = get_start_date(timeframe)
    start_str = start_date.isoformat()

    series_map: Dict[str, pd.Series] = {}
    for ticker in normalized:
        symbol = ticker if ticker.endswith((".NS", ".BO")) else f"{ticker}.NS"
        try:
            history = yf.download(symbol, start=start_str, interval="1d", progress=False, auto_adjust=True)
            if history.empty:
                continue
            if isinstance(history.columns, pd.MultiIndex):
                history.columns = history.columns.get_level_values(0)
            close = history["Close"].dropna().copy()
            if close.empty:
                continue
            series_map[ticker] = close / close.iloc[0] * 100
        except Exception:
            continue

    if not series_map:
        return {
            "generated_at": dt.datetime.utcnow(),
            "summary": {
                "tickers": normalized,
                "capital": capital,
                "timeframe": timeframe,
                "universe_size": len(normalized),
                "status": "no_price_data",
            },
            "chart": {"data": [], "layout": {"title": "No price history available"}},
        }

    aligned = pd.concat(series_map, axis=1).dropna(how="all")
    aligned = aligned.ffill().dropna(how="any")
    if aligned.empty:
        aligned = pd.concat(series_map, axis=1).ffill().dropna(how="all")

    portfolio = aligned.mean(axis=1)
    ending_values = {ticker: round(float(series.iloc[-1]), 2) for ticker, series in series_map.items() if not series.empty}
    total_return_pct = round(float((portfolio.iloc[-1] - 100.0)), 2)
    max_drawdown_pct = round(float(((portfolio / portfolio.cummax()) - 1).min() * 100.0), 2)

    chart_data = [
        {
            "x": [index.isoformat() for index in aligned.index],
            "y": aligned[column].round(2).tolist(),
            "type": "scatter",
            "mode": "lines",
            "name": column,
        }
        for column in aligned.columns
    ]
    chart_data.append(
        {
            "x": [index.isoformat() for index in portfolio.index],
            "y": portfolio.round(2).tolist(),
            "type": "scatter",
            "mode": "lines",
            "name": "Equal-weight portfolio",
            "line": {"width": 4},
        }
    )

    return {
        "generated_at": dt.datetime.utcnow(),
        "summary": {
            "tickers": normalized,
            "capital": capital,
            "timeframe": timeframe,
            "universe_size": len(normalized),
            "status": "ready",
            "period_start": start_str,
            "period_end": aligned.index[-1].isoformat(),
            "ending_values": ending_values,
            "portfolio_return_pct": total_return_pct,
            "portfolio_max_drawdown_pct": max_drawdown_pct,
        },
        "chart": {
            "data": chart_data,
            "layout": {
                "title": "Equal-weight backtest performance",
                "template": "plotly_dark",
                "paper_bgcolor": "rgba(0,0,0,0)",
                "plot_bgcolor": "rgba(0,0,0,0)",
                "margin": {"l": 30, "r": 20, "t": 50, "b": 30},
                "legend": {"orientation": "h"},
            },
        },
    }