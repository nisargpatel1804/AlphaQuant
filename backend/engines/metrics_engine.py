# backend/engines/metrics_engine.py

"""
AlphaQuant Native Metrics Engine - Pure Time-Series Architecture
- Absolute Chronology: Maps fundamental data to exact years/quarters (e.g. "Sales 2018", "Sales Jun 2025").
- Universal Aggregations: Computes Medians, Means, and CAGRs for 1Y, 2Y, 3Y, 5Y, 7Y, 10Y dynamically.
- Strict Alignment: Pairs YFinance exact cycle closing prices with specific Annual/Quarterly reports.
- Math Domain Safety: Prevents division-by-zero, negative CAGRs, and null index crashes.
- Zero Taxonomy Mapping: Flattens raw DOM keys natively.
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backend.core.db import get_scan_result
from backend.core.utils import normalize_ticker

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("MetricsEngine")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "output" / "data"

# ==============================================================================
# SAFE MATH & UTILITY HELPERS
# ==============================================================================
def safe_float(val: Any) -> Optional[float]:
    if val is None: return None
    if isinstance(val, (int, float)): 
        return float(val) if not (math.isnan(val) or math.isinf(val)) else None
    try:
        f = float(str(val).strip())
        return f if not (math.isnan(f) or math.isinf(f)) else None
    except (ValueError, TypeError): 
        return None

def safe_div(num: Any, den: Any, multiplier: float = 1.0) -> Optional[float]:
    n, d = safe_float(num), safe_float(den)
    if n is None or d is None or d == 0: return None
    return round((n / d) * multiplier, 4)

def safe_cagr(latest: Any, past: Any, years: int) -> Optional[float]:
    l_val, p_val = safe_float(latest), safe_float(past)
    if l_val is None or p_val is None or p_val <= 0 or l_val <= 0 or years <= 0: return None
    try:
        return round((((l_val / p_val) ** (1.0 / years)) - 1.0) * 100.0, 4)
    except Exception: return None

def safe_mean(vals: List[Any]) -> Optional[float]:
    valid = [f for x in vals if (f := safe_float(x)) is not None]
    return round(sum(valid) / len(valid), 4) if valid else None

def safe_median(vals: List[Any]) -> Optional[float]:
    valid = [f for x in vals if (f := safe_float(x)) is not None]
    return round(float(np.median(valid)), 4) if valid else None

# ==============================================================================
# CALCULATED METRICS ENGINE
# ==============================================================================
class MetricsEngine:
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or DATA_DIR

    def load_raw_json(self, ticker: str, scan_type: str) -> Dict[str, Any]:
        ticker_norm = normalize_ticker(ticker)
        file_path = self.data_dir / f"{ticker_norm}_{scan_type}.json"
        
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f) or {}
            except Exception as e:
                logger.debug(f"Local file read failed for {ticker_norm} [{scan_type}]: {e}")
        try:
            cached = get_scan_result(ticker_norm, scan_type)
            if cached: return cached
        except Exception: pass
        return {}

    def load_all_ticker_scans(self, ticker: str) -> Dict[str, Any]:
        scan_types = ["fundamentals", "technicals", "eod_data", "seasonality", "peers"]
        return {st: self.load_raw_json(ticker, st) for st in scan_types}

    def build_flat_metrics(self, ticker: str, raw_scans: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        ticker_norm = normalize_ticker(ticker)
        if raw_scans is None: raw_scans = self.load_all_ticker_scans(ticker_norm)

        m: Dict[str, Any] = {"Ticker": ticker_norm}

        fund = raw_scans.get("fundamentals", {})
        if not fund:
            return m

        # 1. UNDERIVABLE CONSTANTS (Face Value, Current Price, etc.)
        for key, val in fund.get("top_ratios", {}).items():
            if not isinstance(val, str) or "/" not in val:
                m[key.strip()] = safe_float(val)
            else:
                m[key.strip()] = val

        hist_prices = fund.get("historical_prices", {})
        raw_fin = fund.get("raw_financials", {})

        # ----------------------------------------------------------------------
        # 2. ABSOLUTE YEARLY TIME-SERIES & AGGREGATIONS (P&L, BS, CF, Ratios)
        # ----------------------------------------------------------------------
        def _flatten_annual_table(table_key: str):
            table = raw_fin.get(table_key, {})
            headers = table.get("headers", [])
            
            for row_name, col_data in table.get("rows", {}).items():
                clean_name = row_name.strip()
                valid_vals = []
                
                # Extract explicitly by year
                for h in headers:
                    val = safe_float(col_data.get(h))
                    if val is not None:
                        # Extract the year natively (e.g. "Mar 2016" -> "2016", "TTM" -> "TTM")
                        match = re.search(r'\b(20\d\d)\b', h)
                        period_label = match.group(1) if match else h.strip()
                        m[f"{clean_name} {period_label}"] = val
                        valid_vals.append(val)
                
                valid_len = len(valid_vals)
                if valid_len == 0: continue

                # Universal "Latest" pointer for cross-domain queries
                m[f"{clean_name}"] = valid_vals[-1]

                # Rolling Aggregations: Medians, Means, and CAGRs (1, 2, 3, 5, 7, 10 Years)
                for y in [1, 2, 3, 5, 7, 10]:
                    if valid_len >= y:
                        m[f"Average {clean_name} {y}Years"] = safe_mean(valid_vals[-y:])
                        m[f"Median {clean_name} {y}Years"] = safe_median(valid_vals[-y:])
                    if valid_len >= y + 1:
                        m[f"{clean_name} growth {y}Years"] = safe_cagr(valid_vals[-1], valid_vals[-(y+1)], y)

                # Dynamic MAX Depth
                if valid_len > 2:
                    actual_max_years = valid_len - 1
                    m[f"{clean_name} growth MAX"] = safe_cagr(valid_vals[-1], valid_vals[0], actual_max_years)
                    m[f"Average {clean_name} MAX"] = safe_mean(valid_vals)
                    m[f"Median {clean_name} MAX"] = safe_median(valid_vals)

        _flatten_annual_table("profit_loss_annual")
        _flatten_annual_table("balance_sheet")
        _flatten_annual_table("cash_flow")
        _flatten_annual_table("ratios")

        # ----------------------------------------------------------------------
        # 3. ABSOLUTE QUARTERLY TIME-SERIES & AGGREGATIONS
        # ----------------------------------------------------------------------
        def _flatten_quarterly_table(table_key: str):
            table = raw_fin.get(table_key, {})
            q_headers = table.get("headers", [])
            
            for row_name, col_data in table.get("rows", {}).items():
                clean_name = row_name.strip()
                valid_vals = []

                # Extract explicitly by quarter label (e.g. "Jun 2026")
                for h in q_headers:
                    val = safe_float(col_data.get(h))
                    if val is not None:
                        m[f"{clean_name} {h.strip()}"] = val
                        valid_vals.append(val)
                
                valid_len = len(valid_vals)
                if valid_len == 0: continue

                # Universal "Latest" Pointer
                m[f"{clean_name} latest quarter"] = valid_vals[-1]

                # Rolling Aggregations: Medians and Means for Quarters
                for q in [1, 2, 3, 4, 8, 10]:
                    if valid_len >= q:
                        m[f"Average {clean_name} {q}Quarters"] = safe_mean(valid_vals[-q:])
                        m[f"Median {clean_name} {q}Quarters"] = safe_median(valid_vals[-q:])
                
                if valid_len >= 5:
                    m[f"YOY Quarterly {clean_name} growth"] = safe_div((valid_vals[-1] or 0) - (valid_vals[-5] or 0), valid_vals[-5], 100.0)

        _flatten_quarterly_table("quarterly_results")
        
        # Shareholding logic
        sh_table = raw_fin.get("shareholding", {}).get("quarterly", {})
        sh_headers = sh_table.get("headers", [])
        for row_name, col_data in sh_table.get("rows", {}).items():
            clean_name = row_name.strip()
            valid_vals = []
            for h in sh_headers:
                val = safe_float(col_data.get(h))
                if val is not None:
                    m[f"{clean_name} holding {h.strip()}"] = val
                    valid_vals.append(val)
            
            valid_len = len(valid_vals)
            if valid_len > 0:
                m[f"{clean_name} holding"] = valid_vals[-1]
                if valid_len >= 2: m[f"Change in {clean_name} holding"] = safe_div((valid_vals[-1] or 0) - (valid_vals[-2] or 0), 1.0)
                if valid_len >= 13: m[f"Change in {clean_name} holding 3Years"] = safe_div((valid_vals[-1] or 0) - (valid_vals[-13] or 0), 1.0)

        # ----------------------------------------------------------------------
        # 4. HISTORICAL YFINANCE ALIGNMENT (Absolute PE, PB, Dividend Yield)
        # ----------------------------------------------------------------------
        pl_table = raw_fin.get("profit_loss_annual", {})
        pl_headers = pl_table.get("headers", [])
        
        pe_hist, dy_hist = [], []
        
        for h in pl_headers:
            match = re.search(r'\b(20\d\d)\b', h)
            if match:
                year_str = match.group(1)
                hist_p = hist_prices.get(year_str)
                if hist_p is not None:
                    # Time-Series P/E
                    h_eps = safe_float(pl_table.get("rows", {}).get("EPS in Rs", {}).get(h))
                    if h_eps and h_eps > 0:
                        pe = round(hist_p / h_eps, 2)
                        m[f"Stock P/E {year_str}"] = pe
                        pe_hist.append(pe)
                    
                    # Time-Series Dividend Yield
                    h_div_pct = safe_float(pl_table.get("rows", {}).get("Dividend Payout %", {}).get(h))
                    if h_div_pct is not None and h_eps is not None:
                        dy = round(((h_div_pct / 100.0) * h_eps) / hist_p * 100.0, 2)
                        m[f"Dividend yield {year_str}"] = dy
                        dy_hist.append(dy)

        if pe_hist: m["Stock P/E"] = pe_hist[-1]
        if dy_hist: m["Dividend yield"] = dy_hist[-1]
        
        for y in [1, 2, 3, 5, 7, 10]:
            if len(pe_hist) >= y: 
                m[f"Average Historical PE {y}Years"] = safe_mean(pe_hist[-y:])
                m[f"Median Historical PE {y}Years"] = safe_median(pe_hist[-y:])
            if len(dy_hist) >= y: 
                m[f"Average Dividend Yield {y}Years"] = safe_mean(dy_hist[-y:])
                m[f"Median Dividend Yield {y}Years"] = safe_median(dy_hist[-y:])

        # Time-Series Stock Price CAGRs
        curr_price = m.get("Current Price")
        if curr_price:
            curr_year_str = str(datetime.now().year)
            for y in [1, 2, 3, 5, 7, 10]:
                past_price = hist_prices.get(str(int(curr_year_str) - y))
                m[f"Stock Price CAGR {y}Years"] = safe_cagr(curr_price, past_price, y)

        # ----------------------------------------------------------------------
        # 5. CROSS-DOMAIN VALUATION & MULTIPLES
        # ----------------------------------------------------------------------
        # Pointers mapped automatically by the latest available flat arrays
        top_line = m.get("Sales") or m.get("Revenue") or m.get("Interest Earned") or m.get("Interest")
        bottom_line = m.get("Net Profit") or m.get("Profit for the year")
        op_line = m.get("Operating Profit") or m.get("Financing Profit")
        
        eps = m.get("EPS in Rs")
        face_value = m.get("Face Value", 10.0)
        debt = m.get("Borrowings")
        assets = m.get("Total Assets")
        eq = m.get("Equity Capital") or m.get("Share Capital")
        res = m.get("Reserves")
        cfo = m.get("Cash from Operating Activity")

        tech = raw_scans.get("technicals", {})
        eod = raw_scans.get("eod_data", {})
        cm_data = eod.get("cash_market_data", {})
        
        if not curr_price:
            m["Current Price"] = safe_float(cm_data.get("close_price")) or safe_float(tech.get("last_close"))
            curr_price = m.get("Current Price")

        # Dynamic Shares Outstanding & Market Cap
        if m.get("Market Cap") and curr_price:
            m["Number of equity shares"] = round(m["Market Cap"] / curr_price, 2)
        elif curr_price and bottom_line and eps and eps > 0:
            m["Number of equity shares"] = round(bottom_line / eps, 2)
            m["Market Cap"] = round(curr_price * m["Number of equity shares"], 2)
        elif curr_price and eq:
            m["Number of equity shares"] = round(eq / face_value, 2)
            m["Market Cap"] = round(curr_price * m["Number of equity shares"], 2)
            
        mc = m.get("Market Cap")
        m["Market Capitalization"] = mc

        m["Price to Sales"] = safe_div(mc, top_line)
        m["Enterprise Value"] = round((mc or 0) + (debt or 0), 2) if mc is not None else None
        
        if op_line is not None and op_line > 0:
            m["EV / EBITDA"] = safe_div(m.get("Enterprise Value"), op_line + (m.get("Other Income", 0) or 0))

        if eq is not None and res is not None and m.get("Number of equity shares"):
            m["Book Value Calculated"] = round((eq + res) / m.get("Number of equity shares"), 2)
            if not m.get("Book Value"): m["Book Value"] = m["Book Value Calculated"]

        bv = m.get("Book Value")
        if eps is not None and eps > 0 and bv is not None and bv > 0:
            m["Graham Number"] = round(math.sqrt(22.5 * eps * bv), 2)
        else:
            m["Graham Number"] = None

        m["Price to book value"] = safe_div(curr_price, bv)

        # ----------------------------------------------------------------------
        # 6. PIOTROSKE F-SCORE PROXY
        # ----------------------------------------------------------------------
        f_score = 0
        roa = safe_div(bottom_line, assets, 100.0)
        
        # We find the previous year keys dynamically
        # Since TTM is last, -2 is strictly "Last Year" logically
        bottom_line_ly = m.get("Net Profit last year") or m.get("Profit for the year last year")
        assets_ly = m.get("Total Assets last year")
        roa_ly = safe_div(bottom_line_ly, assets_ly, 100.0)
        
        opm = m.get("OPM %") or m.get("Financing Margin %")
        opm_ly = m.get("OPM % last year") or m.get("Financing Margin % last year")
        
        ato = safe_div(top_line, assets)
        top_line_ly = m.get("Sales last year") or m.get("Revenue last year") or m.get("Interest Earned last year") or m.get("Interest last year")
        ato_ly = safe_div(top_line_ly, assets_ly)
        
        if roa and roa > 0: f_score += 1
        if cfo and cfo > 0: f_score += 1
        if roa and roa_ly and roa > roa_ly: f_score += 1
        if cfo and bottom_line and cfo > bottom_line: f_score += 1
        
        debt_ly = m.get("Borrowings last year")
        if debt is not None and debt_ly is not None and debt < debt_ly: f_score += 1
        
        curr_ratio = safe_div(m.get("Other Assets"), m.get("Other Liabilities"))
        curr_ratio_ly = safe_div(m.get("Other Assets last year"), m.get("Other Liabilities last year"))
        if curr_ratio is not None and curr_ratio_ly is not None and curr_ratio > curr_ratio_ly: f_score += 1
        
        if eq is not None and m.get("Equity Capital last year") is not None and eq <= m.get("Equity Capital last year"): f_score += 1
        if opm is not None and opm_ly is not None and opm > opm_ly: f_score += 1
        if ato is not None and ato_ly is not None and ato > ato_ly: f_score += 1
        
        m["Piotroski score"] = f_score

        # ----------------------------------------------------------------------
        # 7. TECHNICALS & DERIVATIVES (EOD)
        # ----------------------------------------------------------------------
        d1_inds = tech.get("1d_indicators", {})
        price_action = tech.get("price_action", {})
        returns = price_action.get("returns", {})
        vol_analysis = tech.get("volume_analysis", {})

        fut_data = eod.get("futures_data", {})
        opt_data = eod.get("options_data", {})

        m["DMA 50"] = safe_float(d1_inds.get("SMA_50", {}).get("value"))
        m["DMA 200"] = safe_float(d1_inds.get("SMA_200", {}).get("value"))
        m["RSI"] = safe_float(d1_inds.get("RSI_14", {}).get("value"))
        m["MACD"] = safe_float(d1_inds.get("MACD", {}).get("values", {}).get("macd_line"))
        m["ADX"] = safe_float(d1_inds.get("ADX_14", {}).get("values", {}).get("adx"))
        m["SuperTrend"] = d1_inds.get("SuperTrend_10_3", {}).get("status")
        
        m["Return over 1week"] = safe_float(returns.get("1W"))
        m["Return over 1month"] = safe_float(returns.get("1M"))
        m["Return over 3months"] = safe_float(returns.get("3M"))
        m["Return over 6months"] = safe_float(returns.get("6M"))

        m["Volume"] = safe_float(tech.get("last_volume"))
        m["Volume 1week average"] = safe_float(vol_analysis.get("Weekly_Volume", {}).get("average_volume"))
        m["Volume 1month average"] = safe_float(vol_analysis.get("Monthly_Volume", {}).get("average_volume"))
        
        m["Delivery Percentage"] = safe_float(cm_data.get("delivery_percentage"))
        m["Delivery Quantity"] = safe_float(cm_data.get("delivery_quantity"))

        m["Industry PE"] = safe_float(fund.get("top_ratios", {}).get("Industry PE")) or 25.0

        m["Futures Build-up"] = fut_data.get("build_up_status")
        m["PCR"] = safe_float(opt_data.get("pcr_oi"))
        m["Max Pain"] = safe_float(opt_data.get("max_pain_strike"))
        m["Resistance Strike"] = safe_float(opt_data.get("resistance_strike_ce", {}).get("strike"))
        m["Support Strike"] = safe_float(opt_data.get("support_strike_pe", {}).get("strike"))

        return m

    def build_universe_dataframe(self, tickers: List[str]) -> pd.DataFrame:
        rows = []
        logger.info(f"Building quantitative metrics DataFrame for {len(tickers)} tickers...")
        for t in tickers:
            try: rows.append(self.build_flat_metrics(t))
            except Exception as e: logger.error(f"Error building flat metrics for {t}: {e}")

        df = pd.DataFrame(rows)
        if not df.empty: df.set_index("Ticker", inplace=True)
        return df

if __name__ == "__main__":
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE"
    engine = MetricsEngine()
    metrics = engine.build_flat_metrics(symbol)
    
    print("=" * 80)
    print(f" ALPHAQUANT METRICS ENGINE: [{symbol}]")
    print("=" * 80)
    print(f"Total Natively Derived Variables: {len(metrics)}")
    print("\nSAMPLE EXTRACTED METRICS:")
    
    sample_keys = [
        "Sales 2016", "Sales 2026", "Sales TTM", "Average Sales 5Years", "Median Sales 10Years", "Sales growth MAX",
        "Net Profit Jun 2025", "Average Net Profit 4Quarters", "YOY Quarterly Net Profit growth",
        "Stock P/E 2022", "Average Historical PE 5Years", "Dividend yield 2019",
        "Graham Number", "Piotroski score", "Enterprise Value"
    ]
    for k in sample_keys:
        if k in metrics:
            print(f"  • {k:<38}: {metrics.get(k)}")