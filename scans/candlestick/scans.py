"""
Candlestick Scan Logic.
Iterates through all 24 patterns (via PatternRecognizer) and groups them.
"""
from typing import Dict, Any, List, Optional
import pandas as pd
from .config import (
    CAT_BULLISH, CAT_BULLISH_CONT, CAT_BULLISH_REV,
    CAT_BEARISH, CAT_BEARISH_CONT, CAT_BEARISH_REV,
    CAT_NEUTRAL
)
from .patterns import PatternRecognizer
from .models import CandleScanResult

class CandleScanner:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.pr = PatternRecognizer(df)
        self.results: List[CandleScanResult] = []

    def _add(self, label: str, category: str, cond: bool, action: str):
        if cond:
            self.results.append(CandleScanResult(
                label=label, 
                category=category, 
                status="Pattern Formed", 
                condition_met=True, 
                value=float(self.df['Close'].iloc[-1]), 
                action=action
            ))

    def run_all_scans(self) -> Dict[str, Dict[str, Any]]:
        self.results = []
        if self.df.empty: return {}

        # -----------------------------------------------------------
        # 1. Bullish Scans
        # -----------------------------------------------------------
        self._add("White Marubozu", CAT_BULLISH, self.pr.white_marubozu(), "Buy")

        # -----------------------------------------------------------
        # 2. Bullish Continuation Scans
        # -----------------------------------------------------------
        self._add("Bullish Engulfing", CAT_BULLISH_CONT, self.pr.bullish_engulfing(), "Buy")
        self._add("Rising Three Methods", CAT_BULLISH_CONT, self.pr.rising_three_methods(), "Buy")

        # -----------------------------------------------------------
        # 3. Bullish Reversal Scans
        # -----------------------------------------------------------
        self._add("Hammer", CAT_BULLISH_REV, self.pr.hammer(), "Strong Buy")
        self._add("Inverted Hammer", CAT_BULLISH_REV, self.pr.inverted_hammer(), "Buy")
        self._add("Piercing Pattern", CAT_BULLISH_REV, self.pr.piercing_pattern(), "Strong Buy")
        self._add("Morning Star", CAT_BULLISH_REV, self.pr.morning_star(), "Strong Buy")
        self._add("Bullish Harami", CAT_BULLISH_REV, self.pr.bullish_harami(), "Buy")
        self._add("Three White Soldiers", CAT_BULLISH_REV, self.pr.three_white_soldiers(), "Strong Buy")
        self._add("Three Inside Up", CAT_BULLISH_REV, self.pr.three_inside_up(), "Buy")
        self._add("Three Outside Up", CAT_BULLISH_REV, self.pr.three_outside_up(), "Buy")
        self._add("Bullish Counterattack", CAT_BULLISH_REV, self.pr.bullish_counterattack(), "Buy")

        # -----------------------------------------------------------
        # 4. Bearish Scans
        # -----------------------------------------------------------
        self._add("Black Marubozu", CAT_BEARISH, self.pr.black_marubozu(), "Sell")

        # -----------------------------------------------------------
        # 5. Bearish Continuation Scans
        # -----------------------------------------------------------
        self._add("Falling Three Methods", CAT_BEARISH_CONT, self.pr.falling_three_methods(), "Sell")

        # -----------------------------------------------------------
        # 6. Bearish Reversal Scans
        # -----------------------------------------------------------
        self._add("Hanging Man", CAT_BEARISH_REV, self.pr.hanging_man(), "Sell")
        self._add("Shooting Star", CAT_BEARISH_REV, self.pr.shooting_star(), "Strong Sell")
        self._add("Dark Cloud Cover", CAT_BEARISH_REV, self.pr.dark_cloud_cover(), "Strong Sell")
        self._add("Evening Star", CAT_BEARISH_REV, self.pr.evening_star(), "Strong Sell")
        self._add("Bearish Harami", CAT_BEARISH_REV, self.pr.bearish_harami(), "Sell")
        self._add("Three Black Crows", CAT_BEARISH_REV, self.pr.three_black_crows(), "Strong Sell")
        self._add("Three Inside Down", CAT_BEARISH_REV, self.pr.three_inside_down(), "Sell")
        self._add("Three Outside Down", CAT_BEARISH_REV, self.pr.three_outside_down(), "Sell")
        self._add("Bearish Counterattack", CAT_BEARISH_REV, self.pr.bearish_counterattack(), "Sell")

        # -----------------------------------------------------------
        # 7. Neutral Scans
        # -----------------------------------------------------------
        self._add("Doji", CAT_NEUTRAL, self.pr.doji(), "Neutral")

        # -----------------------------------------------------------
        # Grouping & Signaling
        # -----------------------------------------------------------
        grouped = {}
        for res in self.results:
            grouped.setdefault(res.category, []).append(res.to_dict())

        # Final structure with aggregated signals
        final = {}
        all_cats = [
            CAT_BULLISH, CAT_BULLISH_CONT, CAT_BULLISH_REV,
            CAT_BEARISH, CAT_BEARISH_CONT, CAT_BEARISH_REV,
            CAT_NEUTRAL
        ]
        
        for cat in all_cats:
            scans = grouped.get(cat, [])
            signal = self._calculate_signal(scans, cat)
            final[cat] = {"signal": signal, "scans": scans}
            
        return final

    def _calculate_signal(self, scans: List[Dict[str, Any]], category: str) -> str:
        """
        Determines the aggregate signal for a category.
        If any scan is triggered in a directional category, that direction is the signal.
        """
        if not scans: return "Neutral"
        
        # Override based on category nature
        if "Bullish" in category:
            # Check if any "Strong Buy" scan triggered
            if any(s.get('action') == 'Strong Buy' for s in scans):
                return "Strong Buy"
            return "Buy"
            
        if "Bearish" in category:
            if any(s.get('action') == 'Strong Sell' for s in scans):
                return "Strong Sell"
            return "Sell"
            
        return "Neutral"