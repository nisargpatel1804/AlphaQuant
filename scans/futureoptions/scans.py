"""
Futures and Options Scan Logic.
Implements 14 scans across 4 categories.
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional

from .config import (
    CAT_FUT_OI, CAT_FUT_LONG, CAT_FUT_SHORT, CAT_PCR,
    PCR_HIGH_THRESHOLD, PCR_LOW_THRESHOLD,
    AGGRESSIVE_VOL_MULT, AVG_PERIOD_VOL
)
from .models import FOScanResult

class FOScanner:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.results: List[FOScanResult] = []

    # --- Helpers ---
    def _get(self, col: str, offset: int = 0) -> Optional[float]:
        # Handle cases where column might not exist or dataframe is too short
        if self.df.empty or col not in self.df.columns or len(self.df) <= offset:
            return None
        val = self.df[col].iloc[-(offset + 1)]
        return float(val) if pd.notna(val) else None

    def _add(self, label, category, status, cond, val, action):
        if cond:
            self.results.append(FOScanResult(label, category, status, cond, val, action))

    # --- Scans ---
    def run_all_scans(self) -> Dict[str, Dict[str, Any]]:
        self.results = []
        # Need at least 2 data points for comparisons (Current vs Previous)
        if self.df.empty or len(self.df) < 2: return {}

        # Data Points
        c = self._get('Close')
        prev_c = self._get('Close', 1)
        oi = self._get('OpenInterest')
        prev_oi = self._get('OpenInterest', 1)
        vol = self._get('Volume')
        
        # Calculate Average Volume for 'Aggressive' checks
        avg_vol = None
        if 'Volume' in self.df.columns and len(self.df) >= AVG_PERIOD_VOL:
             avg_vol = self.df['Volume'].rolling(AVG_PERIOD_VOL).mean().iloc[-1]
             
        pcr = self._get('PCR')
        prev_pcr = self._get('PCR', 1)

        # Basic Checks & Conditions
        has_oi = (oi is not None and prev_oi is not None and oi > 0)
        has_pcr = (pcr is not None)
        
        # Price Action
        price_up = (c > prev_c) if (c and prev_c) else False
        price_down = (c < prev_c) if (c and prev_c) else False
        
        # OI Action
        oi_up = (has_oi and oi > prev_oi)
        oi_down = (has_oi and oi < prev_oi)
        
        # Volume Action
        high_vol = False
        if vol and avg_vol:
            high_vol = (vol > avg_vol * AGGRESSIVE_VOL_MULT)

        # -----------------------------------------------------------
        # 1. Futures Open Interest (2 Scans)
        # -----------------------------------------------------------
        if has_oi:
            # High Open Interest
            # Logic: If OI exists, it indicates F&O activity. 
            # Ideally, we'd compare against historical percentiles, but presence is the base check here.
            self._add("High Open Interest", CAT_FUT_OI, "Active", True, oi, "Neutral")
            
            # OI Gainer / Loser
            # Calculate % Change in OI
            oi_change = 0.0
            if prev_oi > 0:
                oi_change = ((oi - prev_oi) / prev_oi) * 100
            
            status = "OI Gainer" if oi_change > 0 else "OI Loser"
            # Rising OI suggests money flowing in (could be long or short), falling is unwinding.
            self._add(f"{status} ({oi_change:.1f}%)", CAT_FUT_OI, status, True, oi_change, "Neutral")
        else:
            self._add("Futures Data", CAT_FUT_OI, "Data Unavailable", True, 0, "Neutral")

        # -----------------------------------------------------------
        # 2. Futures Long Position Scans (4 Scans)
        # -----------------------------------------------------------
        # Long Build Up: Price Up + OI Up
        if price_up and oi_up:
            self._add("Long Build Up", CAT_FUT_LONG, "Bullish", True, c, "Buy")
            # Aggressive New Long: Long Build Up + High Volume
            if high_vol:
                self._add("Aggressive New Long", CAT_FUT_LONG, "Strong Bullish", True, c, "Strong Buy")

        # Short Covering: Price Up + OI Down
        # Traders closing short positions, pushing price up
        if price_up and oi_down:
            self._add("Short Covering", CAT_FUT_LONG, "Bullish", True, c, "Buy")
            # Aggressive Short Covering: Short Covering + High Volume
            if high_vol:
                self._add("Aggressive Short Covering", CAT_FUT_LONG, "Strong Bullish", True, c, "Strong Buy")

        # -----------------------------------------------------------
        # 3. Futures Short Position Scans (4 Scans)
        # -----------------------------------------------------------
        # Short Build Up: Price Down + OI Up
        if price_down and oi_up:
            self._add("Short Build Up", CAT_FUT_SHORT, "Bearish", True, c, "Sell")
            # Aggressive New Short: Short Build Up + High Volume
            if high_vol:
                self._add("Aggressive New Short", CAT_FUT_SHORT, "Strong Bearish", True, c, "Strong Sell")

        # Long Unwinding: Price Down + OI Down
        # Traders closing long positions, pushing price down
        if price_down and oi_down:
            self._add("Long Unwinding", CAT_FUT_SHORT, "Bearish", True, c, "Sell")
            # Aggressive Long Unwinding: Long Unwinding + High Volume
            if high_vol:
                self._add("Aggressive Long Unwinding", CAT_FUT_SHORT, "Strong Bearish", True, c, "Strong Sell")

        # -----------------------------------------------------------
        # 4. Put Call Ratio Scans (4 Scans)
        # -----------------------------------------------------------
        if has_pcr:
            # High PCR: > 1.5 usually indicates Bullish sentiment (more puts sold/written or hedging)
            # However, extreme high can be Overbought/Reversal signal.
            # StockEdge convention: High PCR -> Bullish/Overbought
            if pcr > PCR_HIGH_THRESHOLD:
                self._add("High PCR", CAT_PCR, "Overbought", True, pcr, "Neutral") 
            
            # Low PCR: < 0.6 usually indicates Bearish sentiment (more calls sold)
            if pcr < PCR_LOW_THRESHOLD:
                self._add("Low PCR", CAT_PCR, "Oversold", True, pcr, "Neutral")
            
            # Rising PCR: PCR > Prev PCR
            if prev_pcr and pcr > prev_pcr:
                self._add("Rising PCR", CAT_PCR, "Bullish Sentiment", True, pcr, "Buy")
            
            # Falling PCR: PCR < Prev PCR
            if prev_pcr and pcr < prev_pcr:
                self._add("Falling PCR", CAT_PCR, "Bearish Sentiment", True, pcr, "Sell")
        else:
             self._add("PCR Data", CAT_PCR, "Data Unavailable", True, 0, "Neutral")

        # -----------------------------------------------------------
        # Grouping & Signaling
        # -----------------------------------------------------------
        grouped = {}
        for res in self.results:
            grouped.setdefault(res.category, []).append(res.to_dict())

        final = {}
        # Ensure all categories are present in the output
        for cat in [CAT_FUT_OI, CAT_FUT_LONG, CAT_FUT_SHORT, CAT_PCR]:
            scans = grouped.get(cat, [])
            signal = self._calculate_signal(scans)
            final[cat] = {"signal": signal, "scans": scans}
        
        return final

    def _calculate_signal(self, scans: List[Dict[str, Any]]) -> str:
        """Calculates aggregate signal for a category."""
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