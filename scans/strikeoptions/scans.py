"""
Strike Wise Options Scan Logic.
Implements 8 scans: High OI, OI Gainer/Loser, Active Contracts for Calls & Puts.
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional

from .config import (
    CAT_CALL_OI, CAT_PUT_OI, CAT_ACTIVITY,
    MIN_OI_THRESHOLD, MIN_VOL_THRESHOLD
)
from .models import StrikeScanResult

class StrikeOptionsScanner:
    def __init__(self, calls: pd.DataFrame, puts: pd.DataFrame):
        self.calls = calls
        self.puts = puts
        self.results: List[StrikeScanResult] = []

    def _process_side(self, df: pd.DataFrame, option_type: str):
        """
        Generic logic for Calls (Resistance) or Puts (Support).
        df columns expected: [strike, lastPrice, openInterest, change, volume, percentChange]
        """
        if df.empty: return

        # Ensure numeric columns to prevent errors
        # yfinance sometimes returns strings or mixed types
        if 'openInterest' in df.columns:
            df['openInterest'] = pd.to_numeric(df['openInterest'], errors='coerce').fillna(0)
        else:
            return # Cannot process without OI

        if 'volume' in df.columns:
            df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0)
        else:
            df['volume'] = 0
        
        # Filter noise: Ignore illiquid strikes
        valid_df = df[df['openInterest'] > MIN_OI_THRESHOLD]
        if valid_df.empty: return

        # -----------------------------------------------------------
        # 1. High OI (Highest Open Interest)
        # -----------------------------------------------------------
        # Logic: Find the strike with the maximum Open Interest.
        # Call High OI = Major Resistance.
        # Put High OI = Major Support.
        max_oi_idx = valid_df['openInterest'].idxmax()
        max_oi_row = valid_df.loc[max_oi_idx]
        
        cat = CAT_CALL_OI if option_type == "Call" else CAT_PUT_OI
        
        # Signal Logic:
        # High Call OI is Resistance -> Generally neutral until price interaction.
        # High Put OI is Support -> Generally neutral.
        action = "Neutral" 
        
        self.results.append(StrikeScanResult(
            label=f"Highest {option_type} OI",
            category=cat,
            strike_price=float(max_oi_row['strike']),
            value=float(max_oi_row['openInterest']),
            action=action
        ))

        # -----------------------------------------------------------
        # 2 & 3. OI Gainer / Loser (Change in OI)
        # -----------------------------------------------------------
        # Constraint: yfinance `option_chain` returns a snapshot. 
        # It typically has 'change' (Price Change) but NOT 'changeInOpenInterest'.
        # Without historical data or a dedicated field, we cannot reliably compute 
        # "OI Gainer" or "OI Loser" from a single snapshot.
        #
        # Implementation Decision: We skip these scans to avoid false data.
        # A full implementation would require a database storing yesterday's chain.
        
        # -----------------------------------------------------------
        # 4. Active Contracts (Highest Volume)
        # -----------------------------------------------------------
        # Logic: Find the strike with the highest trading volume.
        # Indicates where the market action is concentrated today.
        vol_df = df[df['volume'] > MIN_VOL_THRESHOLD]
        if not vol_df.empty:
            max_vol_idx = vol_df['volume'].idxmax()
            max_vol_row = vol_df.loc[max_vol_idx]
            
            self.results.append(StrikeScanResult(
                label=f"Most Active {option_type}",
                category=CAT_ACTIVITY,
                strike_price=float(max_vol_row['strike']),
                value=float(max_vol_row['volume']),
                action="Neutral" # High activity is volatility/interest, direction ambiguous without price context
            ))

    def run_all_scans(self) -> Dict[str, Dict[str, Any]]:
        self.results = []
        
        self._process_side(self.calls, "Call")
        self._process_side(self.puts, "Put")
        
        # Group by Category & Format Output
        grouped = {}
        for res in self.results:
            grouped.setdefault(res.category, []).append(res.to_dict())
            
        final_output = {}
        # Ensure categories exist in output even if empty
        for cat in [CAT_CALL_OI, CAT_PUT_OI, CAT_ACTIVITY]:
            scans = grouped.get(cat, [])
            
            # Aggregate Signal Logic for Strikes
            # Currently Neutral because support/resistance levels are static info.
            signal = "Neutral" 
            
            final_output[cat] = {
                "signal": signal,
                "scans": scans
            }
            
        return final_output