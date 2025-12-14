"""
Technical Indicator Calculation Module.
Uses pandas_ta to compute all required metrics for the 214 scans.
"""
import pandas as pd
import pandas_ta as ta
import numpy as np
from typing import Optional

from .config import (
    MA_PERIODS, WEEKLY_MA_PERIODS,
    RSI_PERIOD, CCI_PERIOD,
    STOCH_K_PERIOD, STOCH_D_PERIOD, STOCH_SMOOTH_K,
    WILLR_PERIOD, MFI_PERIOD, ROC_PERIOD,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    ADX_PERIOD, ADX_SMOOTHING,
    SUPERTREND_LENGTH, SUPERTREND_MULTIPLIER,
    PSAR_AF_START, PSAR_AF_INC, PSAR_AF_MAX,
    ICHIMOKU_TENKAN_PERIOD, ICHIMOKU_KIJUN_PERIOD, ICHIMOKU_SENKOU_B_PERIOD,
    BB_LENGTH, BB_STD_DEV, ATR_PERIOD,
    BETA_LOOKBACK_YEARS
)

class TechnicalIndicators:
    """
    Wrapper class to apply technical indicators to a DataFrame in place.
    """

    @staticmethod
    def add_all_indicators(df: pd.DataFrame, is_weekly: bool = False, benchmark_data: Optional[pd.Series] = None) -> pd.DataFrame:
        """
        Orchestrates the addition of all technical indicators to the dataframe.
        """
        if df.empty:
            return df

        # Ensure datetime index is sorted
        df.sort_index(ascending=True, inplace=True)

        TechnicalIndicators.add_moving_averages(df, is_weekly)
        TechnicalIndicators.add_oscillators(df)
        TechnicalIndicators.add_trend_indicators(df)
        TechnicalIndicators.add_volatility_indicators(df)
        TechnicalIndicators.add_ichimoku(df)
        
        # Beta is only relevant for Daily data usually, but code supports both if needed
        if benchmark_data is not None and not is_weekly:
            TechnicalIndicators.add_beta(df, benchmark_data)

        return df

    @staticmethod
    def add_moving_averages(df: pd.DataFrame, is_weekly: bool) -> None:
        periods = WEEKLY_MA_PERIODS if is_weekly else MA_PERIODS
        
        for p in periods:
            # Simple Moving Average
            df[f'SMA_{p}'] = ta.sma(df['Close'], length=p)
            
            # Exponential Moving Average
            df[f'EMA_{p}'] = ta.ema(df['Close'], length=p)

    @staticmethod
    def add_oscillators(df: pd.DataFrame) -> None:
        # RSI
        df['RSI'] = ta.rsi(df['Close'], length=RSI_PERIOD)

        # CCI
        df['CCI'] = ta.cci(df['High'], df['Low'], df['Close'], length=CCI_PERIOD)

        # Stochastic (returns STOCHk and STOCHd)
        stoch = ta.stoch(df['High'], df['Low'], df['Close'], k=STOCH_K_PERIOD, d=STOCH_D_PERIOD, smooth_k=STOCH_SMOOTH_K)
        if stoch is not None:
            # IMPORTANT: add returned columns to the caller-provided dataframe in-place.
            # (Re-assigning df would only change the local reference.)
            for col in stoch.columns:
                df[col] = stoch[col]

            # Rename for clarity if pandas_ta uses default names like STOCHk_14_3_3.
            k_col = next((c for c in stoch.columns if c.startswith('STOCHk')), None)
            d_col = next((c for c in stoch.columns if c.startswith('STOCHd')), None)
            if k_col:
                df.rename(columns={k_col: 'STOCH_K'}, inplace=True)
            if d_col:
                df.rename(columns={d_col: 'STOCH_D'}, inplace=True)

        # William %R
        # pandas_ta calculates WillR as negative values (0 to -100) which matches our config
        df['WILLR'] = ta.willr(df['High'], df['Low'], df['Close'], length=WILLR_PERIOD)

        # Money Flow Index (MFI)
        df['MFI'] = ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=MFI_PERIOD)

        # Rate of Change (ROC)
        df['ROC'] = ta.roc(df['Close'], length=ROC_PERIOD)

    @staticmethod
    def add_trend_indicators(df: pd.DataFrame) -> None:
        # MACD
        macd = ta.macd(df['Close'], fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
        if macd is not None:
            for col in macd.columns:
                df[col] = macd[col]

            # Standardize names: MACD line, Histogram, Signal line
            line_col = next((c for c in macd.columns if c.startswith('MACD_') and not c.startswith('MACDh') and not c.startswith('MACDs')), None)
            hist_col = next((c for c in macd.columns if c.startswith('MACDh')), None)
            sig_col = next((c for c in macd.columns if c.startswith('MACDs')), None)
            rename_map = {}
            if line_col:
                rename_map[line_col] = 'MACD_LINE'
            if hist_col:
                rename_map[hist_col] = 'MACD_HIST'
            if sig_col:
                rename_map[sig_col] = 'MACD_SIGNAL'
            if rename_map:
                df.rename(columns=rename_map, inplace=True)

        # ADX (Average Directional Index)
        # Returns ADX, DMP (+DI), DMN (-DI)
        adx = ta.adx(df['High'], df['Low'], df['Close'], length=ADX_PERIOD, lensig=ADX_PERIOD)
        if adx is not None:
            for col in adx.columns:
                df[col] = adx[col]

            # Rename for clarity
            adx_col = next((c for c in adx.columns if c.startswith('ADX')), None)
            pos_col = next((c for c in adx.columns if c.startswith('DMP')), None)
            neg_col = next((c for c in adx.columns if c.startswith('DMN')), None)
            rename_map = {}
            if adx_col:
                rename_map[adx_col] = 'ADX'
            if pos_col:
                rename_map[pos_col] = 'PLUS_DI'
            if neg_col:
                rename_map[neg_col] = 'MINUS_DI'
            if rename_map:
                df.rename(columns=rename_map, inplace=True)

        # SuperTrend
        # Returns SUPERT_7_3.0, SUPERTd_7_3.0 (Direction), SUPERTl_7_3.0 (Long), SUPERTs_7_3.0 (Short)
        st = ta.supertrend(df['High'], df['Low'], df['Close'], length=SUPERTREND_LENGTH, multiplier=SUPERTREND_MULTIPLIER)
        if st is not None:
            for col in st.columns:
                df[col] = st[col]

            # The main SuperTrend value is the first column; direction is commonly the second.
            st_val_col = st.columns[0] if len(st.columns) > 0 else None
            st_dir_col = st.columns[1] if len(st.columns) > 1 else None
            rename_map = {}
            if st_val_col:
                rename_map[st_val_col] = 'SUPERTREND'
            if st_dir_col:
                rename_map[st_dir_col] = 'SUPERTREND_DIR'
            if rename_map:
                df.rename(columns=rename_map, inplace=True)

        # Parabolic SAR
        # Returns PSARl (Long) and PSARs (Short) combined or separate
        # pandas_ta returns combined 'PSARr_...' and direction logic
        psar = ta.psar(df['High'], df['Low'], df['Close'], af0=PSAR_AF_START, af=PSAR_AF_INC, max_af=PSAR_AF_MAX)
        if psar is not None:
            for col in psar.columns:
                df[col] = psar[col]

            # Usually creates PSARl_* and PSARs_*; coalesce into a single PSAR column.
            psar_cols = [c for c in psar.columns if c.startswith('PSAR')]
            if len(psar_cols) >= 2:
                df['PSAR'] = df[psar_cols[0]].combine_first(df[psar_cols[1]])
            elif len(psar_cols) == 1:
                df['PSAR'] = df[psar_cols[0]]

    @staticmethod
    def add_volatility_indicators(df: pd.DataFrame) -> None:
        # Bollinger Bands
        bb = ta.bbands(df['Close'], length=BB_LENGTH, std=BB_STD_DEV)
        if bb is not None:
            for col in bb.columns:
                df[col] = bb[col]

            # Map standard names: BBL (Lower), BBM (Middle), BBU (Upper), BBB (Bandwidth)
            lower = next((c for c in bb.columns if c.startswith('BBL')), None)
            mid = next((c for c in bb.columns if c.startswith('BBM')), None)
            upper = next((c for c in bb.columns if c.startswith('BBU')), None)
            width = next((c for c in bb.columns if c.startswith('BBB')), None)
            rename_map = {}
            if lower:
                rename_map[lower] = 'BB_LOWER'
            if mid:
                rename_map[mid] = 'BB_MIDDLE'
            if upper:
                rename_map[upper] = 'BB_UPPER'
            if width:
                rename_map[width] = 'BB_WIDTH'
            if rename_map:
                df.rename(columns=rename_map, inplace=True)

        # Average True Range (ATR)
        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=ATR_PERIOD)

    @staticmethod
    def add_ichimoku(df: pd.DataFrame) -> None:
        # Ichimoku Cloud
        # Returns: ISA (Span A), ISB (Span B), ITS (Tenkan), IKS (Kijun), ICS (Chikou)
        ichi_df, span_df = ta.ichimoku(df['High'], df['Low'], df['Close'], 
                                       tenkan=ICHIMOKU_TENKAN_PERIOD, 
                                       kijun=ICHIMOKU_KIJUN_PERIOD, 
                                       senkou=ICHIMOKU_SENKOU_B_PERIOD)
        if ichi_df is not None:
            for col in ichi_df.columns:
                df[col] = ichi_df[col]
            # Columns usually named: 'ITS_9', 'IKS_26', 'ICS_26', 'ISA_9', 'ISB_26'
            # We map them to standard names
            df.rename(columns={
                f'ITS_{ICHIMOKU_TENKAN_PERIOD}': 'TENKAN',
                f'IKS_{ICHIMOKU_KIJUN_PERIOD}': 'KIJUN',
                f'ISA_{ICHIMOKU_TENKAN_PERIOD}': 'SPAN_A',
                f'ISB_{ICHIMOKU_KIJUN_PERIOD}': 'SPAN_B',
                f'ICS_{ICHIMOKU_KIJUN_PERIOD}': 'CHIKOU'
            }, inplace=True)

    @staticmethod
    def add_beta(df: pd.DataFrame, benchmark_series: pd.Series) -> None:
        """
        Calculates Beta (volatility relative to benchmark).
        Beta = Covariance(Stock, Market) / Variance(Market)
        """
        # Align dates
        common_idx = df.index.intersection(benchmark_series.index)
        if len(common_idx) < 30: # Need sufficient data
            df['BETA'] = np.nan
            return

        stock_rets = df.loc[common_idx, 'Close'].pct_change().dropna()
        bench_rets = benchmark_series.loc[common_idx].pct_change().dropna()
        
        # Re-align after pct_change (drops first row)
        common_idx = stock_rets.index.intersection(bench_rets.index)
        stock_rets = stock_rets.loc[common_idx]
        bench_rets = bench_rets.loc[common_idx]

        # Calculate Rolling Beta (or static Beta for the period)
        # Using a rolling window ensures we have a time series, but Beta is usually a single scalar for analysis
        # Here we calculate a rolling 1-year beta if possible, or static.
        # Let's populate the column with the latest 1-Year Beta value for simplicity in scanning.
        
        try:
            covariance = stock_rets.cov(bench_rets)
            variance = bench_rets.var()
            if variance == 0:
                beta = 1.0
            else:
                beta = covariance / variance
            
            df['BETA'] = beta
        except Exception:
            df['BETA'] = 1.0 # Default to neutral if calculation fails