"""
Volume and Delivery Scan Logic.
Implements 15 scans across 3 categories (Daily, Weekly, Monthly).
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional

from scans.volumedelivery.config import (
    CAT_DAILY_VD, CAT_WEEKLY_VD, CAT_MONTHLY_VD,
    HIGH_DELIVERY_PCT, VERY_HIGH_DELIVERY_PCT,
    HIGH_VOLUME_MULT, VERY_HIGH_VOLUME_MULT,
    AVG_PERIOD_DAILY, AVG_PERIOD_WEEKLY, AVG_PERIOD_MONTHLY
)
from scans.volumedelivery.models import VolumeDeliveryResult

class VolumeDeliveryScanner:
    def __init__(self, daily_df: pd.DataFrame, weekly_df: pd.DataFrame, monthly_df: pd.DataFrame):
        self.d = daily_df
        self.w = weekly_df
        self.m = monthly_df
        self.results: List[VolumeDeliveryResult] = []

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------
    def _get_val(self, df: pd.DataFrame, col: str, offset: int = 0) -> Optional[float]:
        # Handle case-insensitive column matching
        col_match = next((c for c in df.columns if c.lower() == col.lower()), None)
        if df.empty or col_match is None or len(df) <= offset:
            return None
        val = df[col_match].iloc[-(offset + 1)]
        return float(val) if pd.notna(val) else None

    def _determine_action(self, df: pd.DataFrame, is_bullish_event: bool) -> str:
        """
        Determine Buy/Sell based on price action accompanying the volume event.
        High Volume + Price Up -> Buy (Accumulation)
        High Volume + Price Down -> Sell (Distribution)
        """
        if df.empty or len(df) < 2: return "Neutral"
        
        close_col = next((c for c in df.columns if c.lower() == 'close'), None)
        if not close_col: return "Neutral"

        close = df[close_col].iloc[-1]
        prev_close = df[close_col].iloc[-2]
        
        if is_bullish_event:
            # If the event itself is bullish (e.g. High Delivery), 
            # we check price to confirm accumulation
            return "Buy" if close > prev_close else "Neutral" # High delivery on drop might be support, but safer to call neutral
        
        # General Volume Spike logic
        if close > prev_close * 1.01: return "Strong Buy"
        if close > prev_close: return "Buy"
        if close < prev_close * 0.99: return "Strong Sell"
        if close < prev_close: return "Sell"
        return "Neutral"

    def _add_res(self, label: str, category: str, status: str, cond: bool, val: Optional[float], action: str):
        if cond:
            self.results.append(VolumeDeliveryResult(label, category, status, cond, val, action))

    # ----------------------------------------------------------------
    # Core Scan Logic (Generic for Timeframes)
    # ----------------------------------------------------------------
    def _run_period_scans(self, df: pd.DataFrame, category: str, avg_period: int):
        if df.empty or len(df) < avg_period + 1: return

        # Current Values
        vol = self._get_val(df, 'Volume')
        del_qty = self._get_val(df, 'Delivery_qty') # Note: fetcher standardizes to Delivery_qty
        del_pct = self._get_val(df, 'Delivery_pct')
        
        # Previous Values
        prev_vol = self._get_val(df, 'Volume', 1)
        prev_del_qty = self._get_val(df, 'Delivery_qty', 1)
        
        # Averages
        vol_col = next((c for c in df.columns if c.lower() == 'volume'), None)
        avg_vol = df[vol_col].rolling(window=avg_period).mean().iloc[-1] if vol_col else None
        
        avg_del_qty = None
        del_qty_col = next((c for c in df.columns if c.lower() == 'delivery_qty'), None)
        if del_qty_col:
            avg_del_qty = df[del_qty_col].rolling(window=avg_period).mean().iloc[-1]

        # 1. High Trade Quantity (Volume > Average)
        if vol and avg_vol and vol > avg_vol * HIGH_VOLUME_MULT:
            status = "Volume Spike"
            if vol > avg_vol * VERY_HIGH_VOLUME_MULT: status = "Ultra High Volume"
            action = self._determine_action(df, False)
            self._add_res("High Trade Quantity", category, status, True, vol, action)

        # 2. Higher Trade Quantity (Volume > Prev Volume)
        if vol and prev_vol and vol > prev_vol:
            action = self._determine_action(df, False)
            self._add_res("Higher Trade Quantity", category, "Higher than Prev", True, vol, "Buy" if action in ["Buy", "Strong Buy"] else "Sell")

        # --- Delivery Scans (Check if data exists) ---
        
        # 3. High Delivery Percentage
        if del_pct is not None:
            if del_pct > HIGH_DELIVERY_PCT:
                status = "High Delivery %"
                action = self._determine_action(df, True)
                self._add_res("High Delivery Percentage", category, status, True, del_pct, action)
        # else: Data Unavailable - handled implicitly by not adding result

        # 4. High Delivery Quantity (vs Average)
        if del_qty is not None and avg_del_qty is not None:
            if del_qty > avg_del_qty * HIGH_VOLUME_MULT:
                action = self._determine_action(df, True)
                self._add_res("High Delivery Quantity", category, "Delivery Spike", True, del_qty, action)

        # 5. Higher Delivery Quantity (vs Prev)
        if del_qty is not None and prev_del_qty is not None:
            if del_qty > prev_del_qty:
                action = self._determine_action(df, True)
                self._add_res("Higher Delivery Quantity", category, "Rising Delivery", True, del_qty, action)

    # ----------------------------------------------------------------
    # Execution
    # ----------------------------------------------------------------
    def run_all(self) -> Dict[str, Dict[str, Any]]:
        self.results = []
        
        self._run_period_scans(self.d, CAT_DAILY_VD, AVG_PERIOD_DAILY)
        self._run_period_scans(self.w, CAT_WEEKLY_VD, AVG_PERIOD_WEEKLY)
        self._run_period_scans(self.m, CAT_MONTHLY_VD, AVG_PERIOD_MONTHLY)
        
        # Group by Category & Calculate Category Signal
        grouped = {}
        for res in self.results:
            cat = res.category
            grouped.setdefault(cat, []).append(res.to_dict())
            
        final_output = {}
        # Ensure all 3 categories exist
        for cat in [CAT_DAILY_VD, CAT_WEEKLY_VD, CAT_MONTHLY_VD]:
            scans = grouped.get(cat, [])
            signal = self._calculate_signal(scans)
            final_output[cat] = {
                "signal": signal,
                "scans": scans
            }
            
        return final_output

    def _calculate_signal(self, scans: List[Dict[str, Any]]) -> str:
        if not scans: return "Neutral"
        
        score = 0
        for s in scans:
            a = s.get("action", "Neutral")
            if a == "Strong Buy": score += 2
            elif a == "Buy": score += 1
            elif a == "Strong Sell": score -= 2
            elif a == "Sell": score -= 1
            
        if score >= 2: return "Strong Buy"
        if score >= 1: return "Buy"
        if score <= -2: return "Strong Sell"
        if score <= -1: return "Sell"
        return "Neutral"