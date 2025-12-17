"""
Utility Module for Price Scans.
Provides helper functions for:
1. Resampling Daily OHLCV data into Weekly/Monthly aggregates.
2. Aligning time-series data (Stock vs Benchmark) for Relative Strength calculations.
3. Common data transformation and validation tasks.
"""
import pandas as pd
import numpy as np
from typing import Tuple, Optional

def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """
    Resamples a Daily OHLCV DataFrame to a specified timeframe.
    
    Args:
        df (pd.DataFrame): Daily data with DateTimeIndex. 
                           Must contain 'Open', 'High', 'Low', 'Close'. 
                           'Volume' is optional.
        rule (str): Pandas offset alias (e.g., 'W-FRI' for Weekly ending Friday, 
                    'ME' or 'M' for Month End).

    Returns:
        pd.DataFrame: Resampled DataFrame. Returns empty DF on failure.
    """
    if df.empty:
        return pd.DataFrame()

    # Define aggregation logic
    agg_dict = {
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last'
    }

    # Add Volume aggregation if column exists
    if 'Volume' in df.columns:
        agg_dict['Volume'] = 'sum'

    try:
        # Perform resampling
        resampled = df.resample(rule).agg(agg_dict)
        
        # Drop rows where all OHLC values are NaN (e.g., periods with no trading)
        resampled.dropna(subset=['Open', 'High', 'Low', 'Close'], how='all', inplace=True)
        
        return resampled
    except Exception as e:
        # Fallback for older Pandas versions where 'ME' might not be supported
        if rule == 'ME':
            try:
                return df.resample('M').agg(agg_dict).dropna()
            except Exception:
                pass
        print(f"Error resampling data with rule '{rule}': {e}")
        return pd.DataFrame()

def align_series(
    series1: pd.Series, 
    series2: pd.Series, 
    join: str = 'inner',
    ffill: bool = True
) -> Tuple[pd.Series, pd.Series]:
    """
    Aligns two time-series (e.g., Stock Close and Benchmark Close) to the same index.
    
    Args:
        series1 (pd.Series): First series (e.g., Stock).
        series2 (pd.Series): Second series (e.g., Benchmark/Sector).
        join (str): Join method ('inner', 'outer', 'left', 'right'). Default 'inner'.
        ffill (bool): If True, forward fills NaN values after alignment (useful for outer joins).

    Returns:
        Tuple[pd.Series, pd.Series]: The two aligned series.
    """
    if series1.empty or series2.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    # Align the series based on index (Date)
    s1_aligned, s2_aligned = series1.align(series2, join=join)

    if ffill:
        s1_aligned = s1_aligned.ffill()
        s2_aligned = s2_aligned.ffill()

    # After ffill, drop any remaining NaNs (e.g., at the start of data)
    # to ensure calculations like pct_change don't fail or return bad data
    valid_mask = s1_aligned.notna() & s2_aligned.notna()
    
    return s1_aligned[valid_mask], s2_aligned[valid_mask]

def calculate_relative_strength(
    stock_close: pd.Series, 
    benchmark_close: pd.Series, 
    window: int
) -> pd.Series:
    """
    Calculates the Relative Strength (RS) score over a specific window.
    RS is calculated as the ROC (Rate of Change) of the Ratio line.
    
    Logic:
    1. Ratio = Stock Close / Benchmark Close
    2. RS Score = Ratio.pct_change(window) * 100
    
    Args:
        stock_close (pd.Series): Daily/Weekly closing prices of the stock.
        benchmark_close (pd.Series): Daily/Weekly closing prices of the benchmark.
        window (int): Lookback period (e.g., 21, 55).

    Returns:
        pd.Series: RS Score series.
    """
    # 1. Align data strictly (inner join implies we need both to exist)
    s_close, b_close = align_series(stock_close, benchmark_close, join='inner')
    
    if len(s_close) < window + 1:
        return pd.Series(dtype=float)

    # 2. Calculate Ratio Line
    # Handle division by zero
    ratio_line = s_close.div(b_close.replace(0, np.nan))
    
    # 3. Calculate Rate of Change of the Ratio
    rs_score = ratio_line.pct_change(periods=window) * 100
    
    return rs_score

def normalize_ticker(ticker: str) -> str:
    """
    Standardizes ticker names for NSE (adding .NS suffix).
    
    Args:
        ticker (str): Input ticker (e.g., "RELIANCE").

    Returns:
        str: Normalized ticker (e.g., "RELIANCE.NS").
    """
    t = ticker.strip().upper()
    if not t.endswith((".NS", ".BO", ".BSE")):
        return f"{t}.NS"
    return t

def safe_pct_change(current: float, reference: float) -> Optional[float]:
    """
    Calculates percentage change safely handling zeros and NaNs.
    
    Args:
        current (float): Current value.
        reference (float): Reference/Previous value.

    Returns:
        float: Percentage change or None if invalid.
    """
    if pd.isna(current) or pd.isna(reference) or reference == 0:
        return None
    return ((current - reference) / abs(reference)) * 100