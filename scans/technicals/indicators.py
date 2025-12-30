"""
Technical Indicator Calculation Module.
Uses pandas_ta if available, otherwise falls back to pure pandas implementations.
"""
import pandas as pd
import numpy as np
from typing import Optional

try:
    import pandas_ta as ta  # type: ignore
    _HAS_PANDAS_TA = True
except Exception:
    # This handles ImportError (missing lib) or RuntimeError (numba version mismatch)
    ta = None
    _HAS_PANDAS_TA = False

from scans.technicals.config import (
    MA_PERIODS, WEEKLY_MA_PERIODS,
    RSI_PERIOD, CCI_PERIOD,
    STOCH_K_PERIOD, STOCH_D_PERIOD, STOCH_SMOOTH_K,
    WILLR_PERIOD, MFI_PERIOD, ROC_PERIOD,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    ADX_PERIOD, ADX_SMOOTHING,
    SUPERTREND_LENGTH, SUPERTREND_MULTIPLIER,
    PSAR_AF_START, PSAR_AF_INC, PSAR_AF_MAX,
    ICHIMOKU_TENKAN_PERIOD, ICHIMOKU_KIJUN_PERIOD, ICHIMOKU_SENKOU_B_PERIOD, ICHIMOKU_DISPLACEMENT,
    BB_LENGTH, BB_STD_DEV, ATR_PERIOD,
    BETA_LOOKBACK_YEARS,
    VWMA_PERIOD, HMA_PERIOD,
    AO_FAST, AO_SLOW,
    MOMENTUM_PERIOD,
    STOCHRSI_RSI_LENGTH, STOCHRSI_STOCH_LENGTH, STOCHRSI_K, STOCHRSI_D,
    BULL_BEAR_EMA,
    UO_SHORT, UO_MEDIUM, UO_LONG,
    PIVOT_CPR_FACTOR
)

class TechnicalIndicators:
    """
    Wrapper class to apply technical indicators to a DataFrame in place.
    """

    @staticmethod
    def _wma(series: pd.Series, length: int) -> pd.Series:
        if length <= 0:
            return pd.Series(index=series.index, dtype=float)
        weights = np.arange(1, length + 1, dtype=float)

        def _apply(x: np.ndarray) -> float:
            if x.size != length:
                return np.nan
            if np.any(~np.isfinite(x)):
                return np.nan
            return float(np.dot(x, weights) / weights.sum())

        return series.rolling(window=length, min_periods=length).apply(_apply, raw=True)

    @staticmethod
    def _hma(series: pd.Series, length: int) -> pd.Series:
        if length <= 0:
            return pd.Series(index=series.index, dtype=float)
        half = max(int(length / 2), 1)
        sqrt_len = max(int(np.sqrt(length)), 1)
        wma_half = TechnicalIndicators._wma(series, half)
        wma_full = TechnicalIndicators._wma(series, length)
        raw = 2 * wma_half - wma_full
        return TechnicalIndicators._wma(raw, sqrt_len)

    @staticmethod
    def add_all_indicators(df: pd.DataFrame, is_weekly: bool = False, benchmark_data: Optional[pd.Series] = None) -> pd.DataFrame:
        if df.empty:
            return df

        df.sort_index(ascending=True, inplace=True)

        TechnicalIndicators.add_moving_averages(df, is_weekly)
        TechnicalIndicators.add_oscillators(df)
        TechnicalIndicators.add_trend_indicators(df)
        TechnicalIndicators.add_volatility_indicators(df)
        TechnicalIndicators.add_ichimoku(df)
        
        # Volume weighted and Pivots are typically daily timeframe relevant
        # or require specific data structure (OHLCV)
        TechnicalIndicators.add_volume_weighted_indicators(df)
        
        if not is_weekly:
            TechnicalIndicators.add_pivots(df)
            if benchmark_data is not None:
                TechnicalIndicators.add_beta(df, benchmark_data)

        return df

    @staticmethod
    def add_volume_weighted_indicators(df: pd.DataFrame) -> None:
        # Check required columns
        has_close = 'Close' in df.columns
        has_volume = 'Volume' in df.columns

        # VWMA
        if has_close and has_volume:
            if _HAS_PANDAS_TA:
                try:
                    df[f'VWMA_{VWMA_PERIOD}'] = ta.vwma(df['Close'], df['Volume'], length=VWMA_PERIOD)
                except Exception:
                    pv = df['Close'] * df['Volume']
                    df[f'VWMA_{VWMA_PERIOD}'] = pv.rolling(window=VWMA_PERIOD, min_periods=VWMA_PERIOD).sum() / df['Volume'].rolling(window=VWMA_PERIOD, min_periods=VWMA_PERIOD).sum()
            else:
                pv = df['Close'] * df['Volume']
                df[f'VWMA_{VWMA_PERIOD}'] = pv.rolling(window=VWMA_PERIOD, min_periods=VWMA_PERIOD).sum() / df['Volume'].rolling(window=VWMA_PERIOD, min_periods=VWMA_PERIOD).sum()

        # HMA
        if has_close:
            if _HAS_PANDAS_TA:
                try:
                    df[f'HMA_{HMA_PERIOD}'] = ta.hma(df['Close'], length=HMA_PERIOD)
                except Exception:
                    df[f'HMA_{HMA_PERIOD}'] = TechnicalIndicators._hma(df['Close'], HMA_PERIOD)
            else:
                df[f'HMA_{HMA_PERIOD}'] = TechnicalIndicators._hma(df['Close'], HMA_PERIOD)

    @staticmethod
    def add_moving_averages(df: pd.DataFrame, is_weekly: bool) -> None:
        periods = WEEKLY_MA_PERIODS if is_weekly else MA_PERIODS
        
        for p in periods:
            # Simple Moving Average
            if _HAS_PANDAS_TA:
                df[f'SMA_{p}'] = ta.sma(df['Close'], length=p)
            else:
                df[f'SMA_{p}'] = df['Close'].rolling(window=p, min_periods=p).mean()
            
            # Exponential Moving Average
            if _HAS_PANDAS_TA:
                df[f'EMA_{p}'] = ta.ema(df['Close'], length=p)
            else:
                df[f'EMA_{p}'] = df['Close'].ewm(span=p, adjust=False, min_periods=p).mean()

    @staticmethod
    def add_oscillators(df: pd.DataFrame) -> None:
        # RSI
        if _HAS_PANDAS_TA:
            df['RSI'] = ta.rsi(df['Close'], length=RSI_PERIOD)
        else:
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
            loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
            rs = gain / loss
            df['RSI'] = 100 - (100 / (1 + rs))

        # CCI
        if _HAS_PANDAS_TA:
            df['CCI'] = ta.cci(df['High'], df['Low'], df['Close'], length=CCI_PERIOD)
        else:
            tp = (df['High'] + df['Low'] + df['Close']) / 3
            sma_tp = tp.rolling(window=CCI_PERIOD).mean()
            mad = tp.rolling(window=CCI_PERIOD).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
            # Avoid division by zero
            mad = mad.replace(0, np.nan)
            df['CCI'] = (tp - sma_tp) / (0.015 * mad)

        # Stochastic
        if _HAS_PANDAS_TA:
            stoch = ta.stoch(df['High'], df['Low'], df['Close'], k=STOCH_K_PERIOD, d=STOCH_D_PERIOD, smooth_k=STOCH_SMOOTH_K)
            if stoch is not None:
                k_col = next((c for c in stoch.columns if c.startswith('STOCHk')), None)
                d_col = next((c for c in stoch.columns if c.startswith('STOCHd')), None)
                if k_col: df['STOCH_K'] = stoch[k_col]
                if d_col: df['STOCH_D'] = stoch[d_col]
        else:
            # Manual Stochastic
            low_min = df['Low'].rolling(window=STOCH_K_PERIOD).min()
            high_max = df['High'].rolling(window=STOCH_K_PERIOD).max()
            k_fast = 100 * (df['Close'] - low_min) / (high_max - low_min)
            # Smooth K
            df['STOCH_K'] = k_fast.rolling(window=STOCH_SMOOTH_K).mean()
            # D is SMA of K
            df['STOCH_D'] = df['STOCH_K'].rolling(window=STOCH_D_PERIOD).mean()

        # William %R
        if _HAS_PANDAS_TA:
            df['WILLR'] = ta.willr(df['High'], df['Low'], df['Close'], length=WILLR_PERIOD)
        else:
            low_min = df['Low'].rolling(window=WILLR_PERIOD).min()
            high_max = df['High'].rolling(window=WILLR_PERIOD).max()
            denom = high_max - low_min
            # Avoid division by zero
            denom = denom.replace(0, np.nan)
            df['WILLR'] = -100 * ((high_max - df['Close']) / denom)

        # MFI
        if _HAS_PANDAS_TA:
            df['MFI'] = ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=MFI_PERIOD)
        else:
            tp = (df['High'] + df['Low'] + df['Close']) / 3
            rmf = tp * df['Volume']
            # Split into positive and negative flow
            up = rmf.where(tp > tp.shift(1), 0)
            down = rmf.where(tp < tp.shift(1), 0)
            
            # Rolling sums
            up_sum = up.rolling(window=MFI_PERIOD).sum()
            down_sum = down.rolling(window=MFI_PERIOD).sum()
            
            # Avoid division by zero
            down_sum = down_sum.replace(0, np.nan)
            mfr = up_sum / down_sum
            df['MFI'] = 100 - (100 / (1 + mfr))

        # ROC
        if _HAS_PANDAS_TA:
            df['ROC'] = ta.roc(df['Close'], length=ROC_PERIOD)
        else:
            df['ROC'] = df['Close'].pct_change(periods=ROC_PERIOD) * 100

        # Momentum (TradingView-style): Close - Close[n]
        df[f'MOMENTUM_{MOMENTUM_PERIOD}'] = df['Close'] - df['Close'].shift(MOMENTUM_PERIOD)

        # Awesome Oscillator
        if _HAS_PANDAS_TA:
            try:
                df['AO'] = ta.ao(df['High'], df['Low'], fast=AO_FAST, slow=AO_SLOW)
            except Exception:
                median = (df['High'] + df['Low']) / 2
                df['AO'] = median.rolling(window=AO_FAST, min_periods=AO_FAST).mean() - median.rolling(window=AO_SLOW, min_periods=AO_SLOW).mean()
        else:
            median = (df['High'] + df['Low']) / 2
            df['AO'] = median.rolling(window=AO_FAST, min_periods=AO_FAST).mean() - median.rolling(window=AO_SLOW, min_periods=AO_SLOW).mean()

        # Stochastic RSI Fast
        # Uses RSI already computed above; if RSI is missing, compute a local copy.
        rsi = df.get('RSI')
        if rsi is None:
            # Fallback RSI calculation if not present
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
            loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
            rs_calc = gain / loss
            rsi = 100 - (100 / (1 + rs_calc))

        if _HAS_PANDAS_TA:
            try:
                stochrsi = ta.stochrsi(
                    df['Close'],
                    length=STOCHRSI_STOCH_LENGTH,
                    rsi_length=STOCHRSI_RSI_LENGTH,
                    k=STOCHRSI_K,
                    d=STOCHRSI_D,
                )
                if stochrsi is not None:
                    k_col = next((c for c in stochrsi.columns if c.startswith('STOCHRSIk')), None)
                    d_col = next((c for c in stochrsi.columns if c.startswith('STOCHRSId')), None)
                    if k_col:
                        df['STOCHRSI_K'] = stochrsi[k_col]
                    if d_col:
                        df['STOCHRSI_D'] = stochrsi[d_col]
            except Exception:
                # Fallback manual calculation within try block
                rsi_min = rsi.rolling(window=STOCHRSI_STOCH_LENGTH, min_periods=STOCHRSI_STOCH_LENGTH).min()
                rsi_max = rsi.rolling(window=STOCHRSI_STOCH_LENGTH, min_periods=STOCHRSI_STOCH_LENGTH).max()
                denom = rsi_max - rsi_min
                denom = denom.replace(0, np.nan)
                raw = 100 * (rsi - rsi_min) / denom
                df['STOCHRSI_K'] = raw.rolling(window=STOCHRSI_K, min_periods=STOCHRSI_K).mean()
                df['STOCHRSI_D'] = df['STOCHRSI_K'].rolling(window=STOCHRSI_D, min_periods=STOCHRSI_D).mean()
        else:
            rsi_min = rsi.rolling(window=STOCHRSI_STOCH_LENGTH, min_periods=STOCHRSI_STOCH_LENGTH).min()
            rsi_max = rsi.rolling(window=STOCHRSI_STOCH_LENGTH, min_periods=STOCHRSI_STOCH_LENGTH).max()
            denom = rsi_max - rsi_min
            denom = denom.replace(0, np.nan)
            raw = 100 * (rsi - rsi_min) / denom
            df['STOCHRSI_K'] = raw.rolling(window=STOCHRSI_K, min_periods=STOCHRSI_K).mean()
            df['STOCHRSI_D'] = df['STOCHRSI_K'].rolling(window=STOCHRSI_D, min_periods=STOCHRSI_D).mean()

        # Bull/Bear Power (Elder Ray) + combined
        ema = df['Close'].ewm(span=BULL_BEAR_EMA, adjust=False, min_periods=BULL_BEAR_EMA).mean()
        df['BULL_POWER'] = df['High'] - ema
        df['BEAR_POWER'] = df['Low'] - ema
        df['BULL_BEAR_POWER'] = df['BULL_POWER'] + df['BEAR_POWER']

        # Ultimate Oscillator
        prev_close = df['Close'].shift(1)
        min_low = pd.concat([df['Low'], prev_close], axis=1).min(axis=1)
        max_high = pd.concat([df['High'], prev_close], axis=1).max(axis=1)
        bp = df['Close'] - min_low
        tr = max_high - min_low
        # Replace 0 TR with NaN to avoid div by zero
        tr = tr.replace(0, np.nan)

        avg_s = bp.rolling(window=UO_SHORT, min_periods=UO_SHORT).sum() / tr.rolling(window=UO_SHORT, min_periods=UO_SHORT).sum()
        avg_m = bp.rolling(window=UO_MEDIUM, min_periods=UO_MEDIUM).sum() / tr.rolling(window=UO_MEDIUM, min_periods=UO_MEDIUM).sum()
        avg_l = bp.rolling(window=UO_LONG, min_periods=UO_LONG).sum() / tr.rolling(window=UO_LONG, min_periods=UO_LONG).sum()
        df['UO'] = 100 * (4 * avg_s + 2 * avg_m + avg_l) / 7

    @staticmethod
    def add_pivots(df: pd.DataFrame) -> None:
        required = {'Open', 'High', 'Low', 'Close'}
        if not required.issubset(df.columns):
            return

        h = df['High'].shift(1)
        l = df['Low'].shift(1)
        c = df['Close'].shift(1)
        o = df['Open'].shift(1)
        rng = (h - l)

        # Classic
        p = (h + l + c) / 3
        df['PIVOT_CLASSIC_P'] = p
        df['PIVOT_CLASSIC_R1'] = 2 * p - l
        df['PIVOT_CLASSIC_S1'] = 2 * p - h
        df['PIVOT_CLASSIC_R2'] = p + rng
        df['PIVOT_CLASSIC_S2'] = p - rng
        df['PIVOT_CLASSIC_R3'] = h + 2 * (p - l)
        df['PIVOT_CLASSIC_S3'] = l - 2 * (h - p)

        # Fibonacci
        df['PIVOT_FIB_P'] = p
        df['PIVOT_FIB_R1'] = p + 0.382 * rng
        df['PIVOT_FIB_S1'] = p - 0.382 * rng
        df['PIVOT_FIB_R2'] = p + 0.618 * rng
        df['PIVOT_FIB_S2'] = p - 0.618 * rng
        df['PIVOT_FIB_R3'] = p + 1.000 * rng
        df['PIVOT_FIB_S3'] = p - 1.000 * rng

        # Camarilla
        factor = PIVOT_CPR_FACTOR
        # Formula: R4 = C + RANGE * 1.1/2, R3 = C + RANGE * 1.1/4 etc.
        df['PIVOT_CAM_R1'] = c + rng * factor / 12
        df['PIVOT_CAM_R2'] = c + rng * factor / 6
        df['PIVOT_CAM_R3'] = c + rng * factor / 4
        df['PIVOT_CAM_R4'] = c + rng * factor / 2
        df['PIVOT_CAM_S1'] = c - rng * factor / 12
        df['PIVOT_CAM_S2'] = c - rng * factor / 6
        df['PIVOT_CAM_S3'] = c - rng * factor / 4
        df['PIVOT_CAM_S4'] = c - rng * factor / 2

        # Woodie
        pw = (h + l + 2 * c) / 4
        df['PIVOT_WOODIE_P'] = pw
        df['PIVOT_WOODIE_R1'] = 2 * pw - l
        df['PIVOT_WOODIE_S1'] = 2 * pw - h
        df['PIVOT_WOODIE_R2'] = pw + rng
        df['PIVOT_WOODIE_S2'] = pw - rng
        df['PIVOT_WOODIE_R3'] = h + 2 * (pw - l)
        df['PIVOT_WOODIE_S3'] = l - 2 * (h - pw)

        # DeMark
        # If Close < Open, x = H + 2*L + C
        # If Close > Open, x = 2*H + L + C
        # If Close == Open, x = H + L + 2*C
        x = np.where(
            c < o,
            h + 2 * l + c,
            np.where(c > o, 2 * h + l + c, h + l + 2 * c)
        )
        x = pd.Series(x, index=df.index, dtype=float)
        df['PIVOT_DEMARK_P'] = x / 4
        df['PIVOT_DEMARK_R1'] = x / 2 - l
        df['PIVOT_DEMARK_S1'] = x / 2 - h

    @staticmethod
    def add_trend_indicators(df: pd.DataFrame) -> None:
        # MACD
        if _HAS_PANDAS_TA:
            macd = ta.macd(df['Close'], fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
            if macd is not None:
                line_col = next((c for c in macd.columns if 'MACD_' in c and 'h' not in c and 's' not in c), None)
                hist_col = next((c for c in macd.columns if 'MACDh' in c), None)
                sig_col = next((c for c in macd.columns if 'MACDs' in c), None)
                if line_col: df['MACD_LINE'] = macd[line_col]
                if hist_col: df['MACD_HIST'] = macd[hist_col]
                if sig_col: df['MACD_SIGNAL'] = macd[sig_col]
        else:
            fast_ema = df['Close'].ewm(span=MACD_FAST, adjust=False).mean()
            slow_ema = df['Close'].ewm(span=MACD_SLOW, adjust=False).mean()
            df['MACD_LINE'] = fast_ema - slow_ema
            df['MACD_SIGNAL'] = df['MACD_LINE'].ewm(span=MACD_SIGNAL, adjust=False).mean()
            df['MACD_HIST'] = df['MACD_LINE'] - df['MACD_SIGNAL']

        # ADX
        if _HAS_PANDAS_TA:
            adx = ta.adx(df['High'], df['Low'], df['Close'], length=ADX_PERIOD)
            if adx is not None:
                adx_col = next((c for c in adx.columns if 'ADX_' in c), None)
                pos_col = next((c for c in adx.columns if 'DMP_' in c), None)
                neg_col = next((c for c in adx.columns if 'DMN_' in c), None)
                if adx_col: df['ADX'] = adx[adx_col]
                if pos_col: df['PLUS_DI'] = adx[pos_col]
                if neg_col: df['MINUS_DI'] = adx[neg_col]
        else:
            # Manual ADX (Simplified)
            up = df['High'].diff()
            down = -df['Low'].diff()
            
            # TR Calculation
            tr1 = df['High'] - df['Low']
            tr2 = (df['High'] - df['Close'].shift(1)).abs()
            tr3 = (df['Low'] - df['Close'].shift(1)).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(window=ADX_PERIOD).mean() # Simple ATR for fallback
            
            plus_dm = up.where((up > down) & (up > 0), 0)
            minus_dm = down.where((down > up) & (down > 0), 0)
            
            # Avoid division by zero
            atr = atr.replace(0, np.nan)
            
            plus_di = 100 * (plus_dm.ewm(alpha=1/ADX_PERIOD).mean() / atr)
            minus_di = 100 * (minus_dm.ewm(alpha=1/ADX_PERIOD).mean() / atr)
            
            dx_denom = plus_di + minus_di
            dx_denom = dx_denom.replace(0, np.nan)
            
            dx = (abs(plus_di - minus_di) / dx_denom) * 100
            df['ADX'] = dx.ewm(alpha=1/ADX_PERIOD).mean()
            df['PLUS_DI'] = plus_di
            df['MINUS_DI'] = minus_di

        # SuperTrend
        if _HAS_PANDAS_TA:
            st = ta.supertrend(df['High'], df['Low'], df['Close'], length=SUPERTREND_LENGTH, multiplier=SUPERTREND_MULTIPLIER)
            if st is not None:
                val_col = st.columns[0]
                dir_col = st.columns[1]
                df['SUPERTREND'] = st[val_col]
                df['SUPERTREND_DIR'] = st[dir_col]
        else:
            # Manual SuperTrend
            hl2 = (df['High'] + df['Low']) / 2
            # Re-calculate TR for ATR
            tr1 = df['High'] - df['Low']
            tr2 = (df['High'] - df['Close'].shift(1)).abs()
            tr3 = (df['Low'] - df['Close'].shift(1)).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.ewm(alpha=1/SUPERTREND_LENGTH, adjust=False).mean()
            
            upper = hl2 + (SUPERTREND_MULTIPLIER * atr)
            lower = hl2 - (SUPERTREND_MULTIPLIER * atr)
            
            # Initialization
            st = [0.0] * len(df)
            trend = [1] * len(df)
            
            # Simple iterative logic (Numba would be faster, but this is pure python fallback)
            for i in range(1, len(df)):
                curr_close = df['Close'].iloc[i]
                prev_close = df['Close'].iloc[i-1]
                
                # Approximate look-back for iterative calc (using previous calculated values)
                prev_upper = upper.iloc[i-1] if i > 0 else upper.iloc[i] 
                prev_lower = lower.iloc[i-1] if i > 0 else lower.iloc[i]
                
                # Upper Band Logic
                if upper.iloc[i] < prev_upper or prev_close > prev_upper:
                    upper.iloc[i] = upper.iloc[i]
                else:
                    upper.iloc[i] = prev_upper
                    
                # Lower Band Logic
                if lower.iloc[i] > prev_lower or prev_close < prev_lower:
                    lower.iloc[i] = lower.iloc[i]
                else:
                    lower.iloc[i] = prev_lower
                
                # Trend Logic
                prev_trend = trend[i-1]
                
                if prev_trend == 1:
                    if curr_close < prev_lower:
                        trend[i] = -1
                        st[i] = upper.iloc[i]
                    else:
                        trend[i] = 1
                        st[i] = lower.iloc[i]
                else:
                    if curr_close > prev_upper:
                        trend[i] = 1
                        st[i] = lower.iloc[i]
                    else:
                        trend[i] = -1
                        st[i] = upper.iloc[i]
                        
            df['SUPERTREND'] = st
            df['SUPERTREND_DIR'] = trend

        # Parabolic SAR (PSAR)
        if _HAS_PANDAS_TA:
            psar = ta.psar(df['High'], df['Low'], df['Close'], af0=PSAR_AF_START, af=PSAR_AF_INC, max_af=PSAR_AF_MAX)
            if psar is not None:
                # Combine Long/Short columns
                cols = [c for c in psar.columns if 'PSAR' in c]
                if len(cols) >= 2:
                    df['PSAR'] = psar[cols[0]].combine_first(psar[cols[1]])
        else:
            # Manual PSAR is complex to write efficiently in pure python loop without numba.
            # We will use a simplified trend following proxy if PSAR is strictly required.
            # Fallback: Simple Moving Average as "Trend" proxy if real PSAR fails
            # This avoids crashing but isn't mathematically identical.
            df['PSAR'] = df['Close'].ewm(span=10).mean() # Placeholder to prevent crash

    @staticmethod
    def add_volatility_indicators(df: pd.DataFrame) -> None:
        # Bollinger Bands
        if _HAS_PANDAS_TA:
            bb = ta.bbands(df['Close'], length=BB_LENGTH, std=BB_STD_DEV)
            if bb is not None:
                l = next((c for c in bb.columns if 'BBL' in c), None)
                m = next((c for c in bb.columns if 'BBM' in c), None)
                u = next((c for c in bb.columns if 'BBU' in c), None)
                w = next((c for c in bb.columns if 'BBB' in c), None)
                if l: df['BB_LOWER'] = bb[l]
                if m: df['BB_MIDDLE'] = bb[m]
                if u: df['BB_UPPER'] = bb[u]
                if w: df['BB_WIDTH'] = bb[w]
        else:
            mid = df['Close'].rolling(window=BB_LENGTH).mean()
            std = df['Close'].rolling(window=BB_LENGTH).std()
            df['BB_MIDDLE'] = mid
            df['BB_UPPER'] = mid + (BB_STD_DEV * std)
            df['BB_LOWER'] = mid - (BB_STD_DEV * std)
            
            # Avoid division by zero
            mid_safe = df['BB_MIDDLE'].replace(0, np.nan)
            df['BB_WIDTH'] = ((df['BB_UPPER'] - df['BB_LOWER']) / mid_safe) * 100

        # ATR
        if _HAS_PANDAS_TA:
            df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=ATR_PERIOD)
        else:
            # Re-calc TR
            tr1 = df['High'] - df['Low']
            tr2 = (df['High'] - df['Close'].shift(1)).abs()
            tr3 = (df['Low'] - df['Close'].shift(1)).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            df['ATR'] = tr.rolling(window=ATR_PERIOD).mean()

    @staticmethod
    def add_ichimoku(df: pd.DataFrame) -> None:
        if _HAS_PANDAS_TA:
            ichi, _ = ta.ichimoku(df['High'], df['Low'], df['Close'], tenkan=ICHIMOKU_TENKAN_PERIOD, kijun=ICHIMOKU_KIJUN_PERIOD, senkou=ICHIMOKU_SENKOU_B_PERIOD)
            if ichi is not None:
                # Map columns (pandas_ta names are dynamic)
                df['TENKAN'] = ichi[f'ITS_{ICHIMOKU_TENKAN_PERIOD}']
                df['KIJUN'] = ichi[f'IKS_{ICHIMOKU_KIJUN_PERIOD}']
                df['SPAN_A'] = ichi[f'ISA_{ICHIMOKU_TENKAN_PERIOD}']
                df['SPAN_B'] = ichi[f'ISB_{ICHIMOKU_KIJUN_PERIOD}']
                df['CHIKOU'] = ichi[f'ICS_{ICHIMOKU_KIJUN_PERIOD}']
        else:
            # Manual Ichimoku
            # Tenkan = (Max High + Min Low) / 2 over past 9
            high_9 = df['High'].rolling(window=ICHIMOKU_TENKAN_PERIOD).max()
            low_9 = df['Low'].rolling(window=ICHIMOKU_TENKAN_PERIOD).min()
            df['TENKAN'] = (high_9 + low_9) / 2
            
            # Kijun = (Max High + Min Low) / 2 over past 26
            high_26 = df['High'].rolling(window=ICHIMOKU_KIJUN_PERIOD).max()
            low_26 = df['Low'].rolling(window=ICHIMOKU_KIJUN_PERIOD).min()
            df['KIJUN'] = (high_26 + low_26) / 2
            
            # Span A = (Tenkan + Kijun) / 2 (Shifted forward 26)
            df['SPAN_A'] = ((df['TENKAN'] + df['KIJUN']) / 2).shift(ICHIMOKU_DISPLACEMENT)
            
            # Span B = (Max High + Min Low) / 2 over past 52 (Shifted forward 26)
            high_52 = df['High'].rolling(window=ICHIMOKU_SENKOU_B_PERIOD).max()
            low_52 = df['Low'].rolling(window=ICHIMOKU_SENKOU_B_PERIOD).min()
            df['SPAN_B'] = ((high_52 + low_52) / 2).shift(ICHIMOKU_DISPLACEMENT)
            
            # Chikou = Close shifted backward 26
            df['CHIKOU'] = df['Close'].shift(-ICHIMOKU_DISPLACEMENT)

    @staticmethod
    def add_beta(df: pd.DataFrame, benchmark_series: pd.Series) -> None:
        """Calculates Beta (volatility relative to benchmark)."""
        common_idx = df.index.intersection(benchmark_series.index)
        if len(common_idx) < 30:
            df['BETA'] = np.nan
            return

        stock_rets = df.loc[common_idx, 'Close'].pct_change().dropna()
        bench_rets = benchmark_series.loc[common_idx].pct_change().dropna()
        
        common_idx = stock_rets.index.intersection(bench_rets.index)
        stock_rets = stock_rets.loc[common_idx]
        bench_rets = bench_rets.loc[common_idx]
        
        try:
            covariance = stock_rets.cov(bench_rets)
            variance = bench_rets.var()
            df['BETA'] = covariance / variance if variance != 0 else 1.0
        except Exception:
            df['BETA'] = 1.0