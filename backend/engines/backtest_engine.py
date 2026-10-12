# backend/engines/backtest_engine.py

from __future__ import annotations

import csv
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import yfinance as yf

# Use the unified quantitative metrics hub for capital weighting
from backend.engines.metrics_engine import MetricsEngine

NIFTY_500_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]

# Risk-Free Rate Proxy (e.g., RBI Repo Rate ~6.5%)
RISK_FREE_RATE = 0.065
TRADING_DAYS_PER_YEAR = 252


def get_nifty_tickers(retries: int = 4) -> List[str]:
    sess = requests.Session()
    for attempt in range(1, retries + 1):
        try:
            resp = sess.get(NIFTY_500_URL, timeout=30, headers={"User-Agent": random.choice(USER_AGENTS)})
            resp.raise_for_status()
            reader = csv.DictReader(resp.content.decode("utf-8", errors="replace").splitlines())
            return [row["Symbol"].strip().upper() for row in reader if row.get("Symbol")]
        except requests.RequestException:
            if attempt == retries: break
    
    fallback = Path(__file__).resolve().parent.parent / "source" / "ind_nifty500list.csv"
    if fallback.exists():
        with fallback.open("r", encoding="utf-8") as handle:
            return [row["Symbol"].strip().upper() for row in csv.DictReader(handle) if row.get("Symbol")]
    return []


def get_start_date(timeframe_code: str) -> date:
    today = date.today()
    mapping = {
        "1W": timedelta(weeks=1), "1M": timedelta(days=30), "2M": timedelta(days=60),
        "3M": timedelta(days=90), "6M": timedelta(days=180), "1Y": timedelta(days=365),
        "2Y": timedelta(days=730), "3Y": timedelta(days=1095), "5Y": timedelta(days=1825),
        "10Y": timedelta(days=3650),
    }
    if timeframe_code == "Max": return date(2000, 1, 1)
    return today - mapping.get(timeframe_code, timedelta(days=365))


def fetch_historical_data(tickers: List[str], start_str: str) -> Tuple[pd.DataFrame, pd.Series]:
    """Fetches and aligns Adjusted Close prices for the portfolio universe and Benchmark."""
    symbols = [t if t.endswith((".NS", ".BO")) else f"{t}.NS" for t in tickers]
    
    # 1. Fetch Benchmark (^NSEI)
    try:
        bench_hist = yf.download("^NSEI", start=start_str, interval="1d", progress=False, auto_adjust=True)
        if isinstance(bench_hist.columns, pd.MultiIndex):
            bench_hist.columns = bench_hist.columns.get_level_values(0)
        benchmark_series = bench_hist["Close"].dropna()
    except Exception:
        benchmark_series = pd.Series(dtype=float)

    # 2. Fetch Assets
    series_map = {}
    for t, sym in zip(tickers, symbols):
        try:
            hist = yf.download(sym, start=start_str, interval="1d", progress=False, auto_adjust=True)
            if hist.empty: continue
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.get_level_values(0)
            close = hist["Close"].dropna()
            if not close.empty: series_map[t] = close
        except Exception: continue

    if not series_map:
        return pd.DataFrame(), benchmark_series

    # Forward fill to handle missing daily prints, then drop entirely empty rows
    aligned_df = pd.concat(series_map, axis=1)
    aligned_df = aligned_df.ffill().dropna(how="all")
    
    # Align benchmark to identical timeframe
    if not benchmark_series.empty:
        benchmark_series = benchmark_series.reindex(aligned_df.index).ffill()

    return aligned_df, benchmark_series


def calculate_target_weights(
    tickers: List[str], scheme: str, factor_metric: Optional[str] = None
) -> Dict[str, float]:
    """
    Computes initial capital allocation weights based on AlphaQuant metrics.
    Ensures weights always sum to exactly 1.0.
    """
    if scheme == "Equal Weight" or not tickers:
        return {t: 1.0 / len(tickers) for t in tickers}

    engine = MetricsEngine()
    weights_raw = {}
    valid_tickers = []

    for t in tickers:
        try:
            metrics = engine.build_flat_metrics(t)
            if scheme == "Market Cap":
                val = metrics.get("Market Capitalization")
            elif scheme == "Factor" and factor_metric:
                val = metrics.get(factor_metric)
            elif scheme == "Inverse Volatility":
                # Proxy historical volatility via recent ATR divided by current price
                atr = metrics.get("ATR_14")
                price = metrics.get("Current price")
                val = (1.0 / (atr / price)) if atr and price and price > 0 else None
            else:
                val = None

            if val is not None and val > 0:
                weights_raw[t] = float(val)
                valid_tickers.append(t)
        except Exception: pass

    # If all metrics failed, fallback to Equal Weight
    total_val = sum(weights_raw.values())
    if total_val == 0 or not valid_tickers:
        return {t: 1.0 / len(tickers) for t in tickers}

    return {t: weights_raw.get(t, 0) / total_val for t in tickers}


def calculate_risk_metrics(
    portfolio_daily: pd.Series, benchmark_daily: pd.Series
) -> Dict[str, float]:
    """Calculates institutional risk-adjusted return and correlation metrics."""
    if len(portfolio_daily) < 2:
        return {}

    daily_returns = portfolio_daily.pct_change().dropna()
    bench_returns = benchmark_daily.pct_change().dropna() if not benchmark_daily.empty else pd.Series(dtype=float)

    metrics = {}
    trading_days = len(portfolio_daily)
    
    # CAGR
    total_return = (portfolio_daily.iloc[-1] / portfolio_daily.iloc[0]) - 1
    cagr = ((1 + total_return) ** (TRADING_DAYS_PER_YEAR / trading_days)) - 1 if trading_days > 0 else 0
    metrics["cagr"] = round(cagr * 100, 2)
    metrics["total_return"] = round(total_return * 100, 2)

    # Volatility (Annualized)
    ann_vol = daily_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    
    # Sharpe & Sortino
    if ann_vol > 0:
        metrics["sharpe_ratio"] = round((cagr - RISK_FREE_RATE) / ann_vol, 2)
        downside_returns = daily_returns[daily_returns < 0]
        down_vol = downside_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
        metrics["sortino_ratio"] = round((cagr - RISK_FREE_RATE) / down_vol, 2) if down_vol > 0 else None
    else:
        metrics["sharpe_ratio"] = metrics["sortino_ratio"] = None

    # Drawdown Dynamics
    roll_max = portfolio_daily.cummax()
    drawdowns = (portfolio_daily / roll_max) - 1.0
    max_dd = drawdowns.min()
    metrics["max_drawdown"] = round(max_dd * 100, 2)
    
    metrics["calmar_ratio"] = round(cagr / abs(max_dd), 2) if max_dd < 0 else None

    # Max Drawdown Duration (Days underwater)
    underwater = drawdowns < 0
    underwater_streaks = underwater.groupby((~underwater).cumsum()).sum()
    metrics["max_drawdown_days"] = int(underwater_streaks.max())

    # Alpha / Beta vs Benchmark
    if not bench_returns.empty:
        common = daily_returns.index.intersection(bench_returns.index)
        if len(common) > 10:
            cov = daily_returns.loc[common].cov(bench_returns.loc[common])
            var = bench_returns.loc[common].var()
            beta = cov / var if var > 0 else 1.0
            
            bench_cagr = ((1 + (benchmark_daily.iloc[-1] / benchmark_daily.iloc[0]) - 1) ** (TRADING_DAYS_PER_YEAR / trading_days)) - 1
            
            # Jensen's Alpha = Port_Return - [RiskFree + Beta * (Market_Return - RiskFree)]
            expected_return = RISK_FREE_RATE + beta * (bench_cagr - RISK_FREE_RATE)
            alpha = cagr - expected_return

            metrics["beta"] = round(beta, 2)
            metrics["jensens_alpha"] = round(alpha * 100, 2)

    return metrics


def build_backtest_summary(
    tickers: List[str],
    capital: float,
    timeframe: str,
    weighting_scheme: str = "Equal Weight",
    factor_metric: Optional[str] = None,
    rebalance_freq: str = "None",
    friction_bps: float = 15.0,
    holding_period_days: Optional[int] = None
) -> Dict[str, Any]:
    
    normalized = [t.strip().upper() for t in tickers if t and t.strip()]
    if not normalized:
        return {"generated_at": datetime.now(timezone.utc), "summary": {"status": "no_tickers_selected"}, "chart": {}}

    start_date = get_start_date(timeframe)
    start_str = start_date.isoformat()

    # 1. Fetch Prices
    prices_df, bench_series = fetch_historical_data(normalized, start_str)
    if prices_df.empty:
        return {"generated_at": datetime.now(timezone.utc), "summary": {"status": "no_price_data"}, "chart": {}}

    # 2. Get Initial Target Weights
    target_weights = calculate_target_weights(list(prices_df.columns), weighting_scheme, factor_metric)

    # 3. Simulate Portfolio with Friction & Rebalancing
    friction_rate = friction_bps / 10000.0
    
    # Initialize allocations (shares) and cash
    current_cash = capital
    shares = {t: 0.0 for t in target_weights.keys()}
    
    # Initial Buy
    initial_prices = prices_df.iloc[0]
    for t, w in target_weights.items():
        if t in initial_prices and initial_prices[t] > 0:
            alloc_amt = capital * w
            shares[t] = (alloc_amt * (1 - friction_rate)) / initial_prices[t]
            current_cash -= alloc_amt

    portfolio_values = []
    daily_dates = prices_df.index
    
    rebalance_days = set()
    if rebalance_freq != "None":
        if rebalance_freq == "Monthly": rebalance_days = set(prices_df.resample('ME').last().index)
        elif rebalance_freq == "Quarterly": rebalance_days = set(prices_df.resample('QE').last().index)
        elif rebalance_freq == "Yearly": rebalance_days = set(prices_df.resample('YE').last().index)

    # Simulation Loop
    for i, current_date in enumerate(daily_dates):
        current_prices = prices_df.iloc[i]
        
        # Check Auto-Exit Horizon
        if holding_period_days and i == holding_period_days:
            # Liquidate all
            for t in shares:
                if t in current_prices and not pd.isna(current_prices[t]):
                    current_cash += shares[t] * current_prices[t] * (1 - friction_rate)
                    shares[t] = 0.0

        current_value = current_cash
        for t, s in shares.items():
            if t in current_prices and not pd.isna(current_prices[t]):
                current_value += s * current_prices[t]
        
        portfolio_values.append(current_value)

        # Execute Rebalance
        if current_date in rebalance_days and i > 0 and (not holding_period_days or i < holding_period_days):
            new_shares = {}
            for t, w in target_weights.items():
                target_alloc = current_value * w
                if t in current_prices and not pd.isna(current_prices[t]):
                    current_alloc = shares[t] * current_prices[t]
                    diff = target_alloc - current_alloc
                    
                    if diff > 0: # Buy
                        cost = diff * (1 + friction_rate)
                        current_cash -= cost
                        new_shares[t] = shares[t] + (diff / current_prices[t])
                    elif diff < 0: # Sell
                        proceeds = abs(diff) * (1 - friction_rate)
                        current_cash += proceeds
                        new_shares[t] = shares[t] - (abs(diff) / current_prices[t])
                    else:
                        new_shares[t] = shares[t]
            shares = new_shares

    # 4. Generate Output Series
    port_series = pd.Series(portfolio_values, index=daily_dates)
    normalized_port = (port_series / port_series.iloc[0]) * 100

    if not bench_series.empty:
        normalized_bench = (bench_series / bench_series.iloc[0]) * 100
    else:
        normalized_bench = pd.Series(dtype=float)

    # Calculate Institutional Risk Metrics
    risk_metrics = calculate_risk_metrics(port_series, bench_series)

    # Drawdown Curve
    roll_max = port_series.cummax()
    drawdown_series = ((port_series / roll_max) - 1.0) * 100

    # Monthly Return Matrix
    returns_df = port_series.resample('ME').last().pct_change().dropna() * 100
    monthly_matrix = {}
    for dt_idx, val in returns_df.items():
        yr = str(dt_idx.year)
        mo = dt_idx.strftime('%b')
        if yr not in monthly_matrix: monthly_matrix[yr] = {}
        monthly_matrix[yr][mo] = round(float(val), 2)

    # 5. Build Chart Payload
    chart_data = [
        {
            "x": [idx.isoformat() for idx in normalized_port.index],
            "y": normalized_port.round(2).tolist(),
            "type": "scatter",
            "mode": "lines",
            "name": "Portfolio Strategy",
            "line": {"width": 3, "color": "#00f2fe"}
        }
    ]
    if not normalized_bench.empty:
        chart_data.append({
            "x": [idx.isoformat() for idx in normalized_bench.index],
            "y": normalized_bench.round(2).tolist(),
            "type": "scatter",
            "mode": "lines",
            "name": "Benchmark (Nifty 50)",
            "line": {"width": 2, "color": "#ffaa00", "dash": "dot"}
        })

    # Add Drawdown overlay
    chart_data.append({
        "x": [idx.isoformat() for idx in drawdown_series.index],
        "y": drawdown_series.round(2).tolist(),
        "type": "scatter",
        "mode": "lines",
        "name": "Drawdown %",
        "yaxis": "y2",
        "fill": "tozeroy",
        "line": {"width": 1, "color": "rgba(255, 50, 50, 0.5)"}
    })

    return {
        "generated_at": datetime.now(timezone.utc),
        "summary": {
            "status": "success",
            "universe_size": len(normalized),
            "tickers": normalized,
            "target_weights": {k: round(v*100, 2) for k, v in target_weights.items()},
            "parameters": {
                "initial_capital": capital,
                "timeframe": timeframe,
                "weighting_scheme": weighting_scheme,
                "rebalance_frequency": rebalance_freq,
                "friction_bps": friction_bps,
                "holding_period_days": holding_period_days
            },
            "performance": risk_metrics,
            "monthly_returns": monthly_matrix,
            "disclosures": [
                "Returns calculated using yfinance Adjusted Close (accounts for dividends and splits).",
                "Universe represents current Nifty index members (subject to historical survivorship bias)."
            ]
        },
        "chart": {
            "data": chart_data,
            "layout": {
                "title": f"Quantitative Backtest: {weighting_scheme} Strategy",
                "template": "plotly_dark",
                "paper_bgcolor": "rgba(0,0,0,0)",
                "plot_bgcolor": "rgba(0,0,0,0)",
                "margin": {"l": 50, "r": 50, "t": 50, "b": 30},
                "legend": {"orientation": "h"},
                "yaxis": {"title": "Growth of ₹100"},
                "yaxis2": {"title": "Drawdown %", "overlaying": "y", "side": "right", "range": [-100, 0]}
            }
        }
    }