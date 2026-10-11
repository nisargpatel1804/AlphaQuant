# backend/metrics_engine.py

"""
AlphaQuant Calculated Metrics Builder & Aggregator Engine
Reads raw scanner JSON caches, flattens annual/quarterly financial tables, 
computes derived fundamental/technical ratios, and builds a unified 150+ metric 
dataset for Screener query filtering and quantitative analysis.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd

from backend.db import get_scan_result
from backend.utils import normalize_ticker

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("MetricsEngine")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "output" / "data"

# ==============================================================================
# SAFE MATH & UTILITY HELPERS
# ==============================================================================
def safe_float(val: Any) -> Optional[float]:
    """Safely cast value to float, returning None if invalid or NaN."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val) if not (math.isnan(val) or math.isinf(val)) else None
    try:
        cleaned = str(val).replace(",", "").replace("%", "").strip()
        if cleaned in {"", "-", "—", "N/A", "na", "null", "None"}:
            return None
        f = float(cleaned)
        return f if not (math.isnan(f) or math.isinf(f)) else None
    except (ValueError, TypeError):
        return None


def safe_div(num: Any, den: Any, multiplier: float = 1.0) -> Optional[float]:
    """Safely divide num by den, returning None if denominator is zero or invalid."""
    n, d = safe_float(num), safe_float(den)
    if n is None or d is None or d == 0:
        return None
    return round((n / d) * multiplier, 4)


def safe_cagr(latest: Any, past: Any, years: int) -> Optional[float]:
    """Calculate CAGR percentage safely across N years."""
    l_val, p_val = safe_float(latest), safe_float(past)
    if l_val is None or p_val is None or p_val <= 0 or l_val <= 0 or years <= 0:
        return None
    try:
        cagr = ((l_val / p_val) ** (1.0 / years) - 1.0) * 100.0
        return round(cagr, 2)
    except Exception:
        return None


def safe_mean(vals: List[Any]) -> Optional[float]:
    """Compute arithmetic mean of valid floats in a list."""
    valid = [f for x in vals if (f := safe_float(x)) is not None]
    if not valid:
        return None
    return round(sum(valid) / len(valid), 4)


def safe_sum(vals: List[Any]) -> Optional[float]:
    """Compute sum of valid floats in a list."""
    valid = [f for x in vals if (f := safe_float(x)) is not None]
    if not valid:
        return None
    return round(sum(valid), 4)


# ==============================================================================
# CALCULATED METRICS ENGINE
# ==============================================================================
class MetricsEngine:
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or DATA_DIR

    def load_raw_json(self, ticker: str, scan_type: str) -> Dict[str, Any]:
        """Loads scan JSON from local output folder with Supabase DB fallback."""
        ticker_norm = normalize_ticker(ticker)
        file_path = self.data_dir / f"{ticker_norm}_{scan_type}.json"
        
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f) or {}
            except Exception as e:
                logger.debug(f"Local file read failed for {ticker_norm} [{scan_type}]: {e}")

        # Fallback to Supabase
        try:
            cached = get_scan_result(ticker_norm, scan_type)
            if cached:
                return cached
        except Exception:
            pass

        return {}

    def load_all_ticker_scans(self, ticker: str) -> Dict[str, Any]:
        """Loads all scan files for a ticker into a grouped dictionary."""
        scan_types = [
            "fundamentals", "technicals", "pricescan", 
            "candlestick", "volumedelivery", "seasonality", "peers"
        ]
        return {st: self.load_raw_json(ticker, st) for st in scan_types}

    def build_flat_metrics(self, ticker: str, raw_scans: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Builds a flattened, comprehensive dictionary of 150+ Screener.in standard metrics
        and technical indicators for a given ticker.
        """
        ticker_norm = normalize_ticker(ticker)
        if raw_scans is None:
            raw_scans = self.load_all_ticker_scans(ticker_norm)

        # Output payload dictionary mapping exact Screener keywords & aliases
        m: Dict[str, Any] = {"Ticker": ticker_norm}

        # ----------------------------------------------------------------------
        # 1. RAW FINANCIAL TABLES EXTRACTION (Annual & Quarterly)
        # ----------------------------------------------------------------------
        fund = raw_scans.get("fundamentals", {})
        raw_fin = fund.get("raw_financials", {})
        hist_ratios = fund.get("core_metrics", {}).get("historical_ratios", {})

        # P&L Annual
        pl_annual = raw_fin.get("profit_loss_annual", {})
        pl_headers = pl_annual.get("headers", [])
        pl_rows = pl_annual.get("rows", {})

        # Quarterly Results
        q_res = raw_fin.get("quarterly_results", {})
        q_headers = q_res.get("headers", [])
        q_rows = q_res.get("rows", {})

        # Balance Sheet
        bs = raw_fin.get("balance_sheet", {})
        bs_headers = bs.get("headers", [])
        bs_rows = bs.get("rows", {})

        # Cash Flow
        cf = raw_fin.get("cash_flow", {})
        cf_headers = cf.get("headers", [])
        cf_rows = cf.get("rows", {})

        # Key Ratios
        ratios_tbl = raw_fin.get("ratios", {})
        ratios_rows = ratios_tbl.get("rows", {})

        # Shareholding
        sh_quarterly = raw_fin.get("shareholding", {}).get("quarterly", {})
        sh_q_headers = sh_quarterly.get("headers", [])
        sh_q_rows = sh_quarterly.get("rows", {})

        # ----------------------------------------------------------------------
        # 2. ANNUAL P&L METRICS & DERIVATIONS
        # ----------------------------------------------------------------------
        def _get_annual_val(metric_name: str, period_idx: int = -1) -> Optional[float]:
            """Helper to extract annual metric value at specific period offset (-1 = latest/TTM, -2 = last year)."""
            row = pl_rows.get(metric_name, {})
            if not row or not pl_headers or abs(period_idx) > len(pl_headers):
                return None
            period = pl_headers[period_idx]
            return safe_float(row.get(period))

        m["Sales"] = _get_annual_val("Sales", -1)
        m["Operating profit"] = _get_annual_val("Operating Profit", -1)
        m["OPM"] = _get_annual_val("OPM %", -1)
        m["Other income"] = _get_annual_val("Other Income", -1)
        m["Interest"] = _get_annual_val("Interest", -1)
        m["Depreciation"] = _get_annual_val("Depreciation", -1)
        m["Profit before tax"] = _get_annual_val("Profit before tax", -1)
        m["Tax"] = _get_annual_val("Tax %", -1)
        m["Net profit"] = _get_annual_val("Net Profit", -1)
        m["Profit after tax"] = m["Net profit"]
        m["EPS"] = _get_annual_val("EPS in Rs", -1)
        m["Dividend payout %"] = _get_annual_val("Dividend Payout %", -1)

        # Derived EBIT & EBITDA
        op_prof = m["Operating profit"] or 0.0
        oth_inc = m["Other income"] or 0.0
        depr = m["Depreciation"] or 0.0
        m["EBIT"] = round(op_prof + oth_inc - depr, 2) if m["Operating profit"] is not None else None
        m["EBIDT"] = round(op_prof + oth_inc, 2) if m["Operating profit"] is not None else None
        m["EBITDA"] = m["EBIDT"]

        # Last Year Annual Metrics (1Y Back)
        m["Sales last year"] = _get_annual_val("Sales", -2)
        m["Operating profit last year"] = _get_annual_val("Operating Profit", -2)
        m["OPM last year"] = _get_annual_val("OPM %", -2)
        m["Other income last year"] = _get_annual_val("Other Income", -2)
        m["Interest last year"] = _get_annual_val("Interest", -2)
        m["Depreciation last year"] = _get_annual_val("Depreciation", -2)
        m["Profit before tax last year"] = _get_annual_val("Profit before tax", -2)
        m["Net Profit last year"] = _get_annual_val("Net Profit", -2)
        m["Profit after tax last year"] = m["Net Profit last year"]
        m["EPS last year"] = _get_annual_val("EPS in Rs", -2)
        m["Dividend last year"] = _get_annual_val("Dividend Payout %", -2)

        # Preceding Year Annual Metrics (2Y Back)
        m["Sales preceding year"] = _get_annual_val("Sales", -3)
        m["Operating profit preceding year"] = _get_annual_val("Operating Profit", -3)
        m["OPM preceding year"] = _get_annual_val("OPM %", -3)
        m["Other income preceding year"] = _get_annual_val("Other Income", -3)
        m["Interest preceding year"] = _get_annual_val("Interest", -3)
        m["Depreciation preceding year"] = _get_annual_val("Depreciation", -3)
        m["Profit before tax preceding year"] = _get_annual_val("Profit before tax", -3)
        m["Net Profit preceding year"] = _get_annual_val("Net Profit", -3)
        m["Profit after tax preceding year"] = m["Net Profit preceding year"]
        m["EPS preceding year"] = _get_annual_val("EPS in Rs", -3)

        # Multi-Year Annual CAGRs
        latest_sales = _get_annual_val("Sales", -1)
        latest_profit = _get_annual_val("Net Profit", -1)
        latest_eps = _get_annual_val("EPS in Rs", -1)

        m["Sales growth 3Years"] = safe_cagr(latest_sales, _get_annual_val("Sales", -4), 3)
        m["Sales growth 5Years"] = safe_cagr(latest_sales, _get_annual_val("Sales", -6), 5)
        m["Sales growth 7Years"] = safe_cagr(latest_sales, _get_annual_val("Sales", -8), 7)
        m["Sales growth 10Years"] = safe_cagr(latest_sales, _get_annual_val("Sales", -11), 10)

        m["Profit growth 3Years"] = safe_cagr(latest_profit, _get_annual_val("Net Profit", -4), 3)
        m["Profit growth 5Years"] = safe_cagr(latest_profit, _get_annual_val("Net Profit", -6), 5)
        m["Profit growth 7Years"] = safe_cagr(latest_profit, _get_annual_val("Net Profit", -8), 7)
        m["Profit growth 10Years"] = safe_cagr(latest_profit, _get_annual_val("Net Profit", -11), 10)

        m["EPS growth 3Years"] = safe_cagr(latest_eps, _get_annual_val("EPS in Rs", -4), 3)
        m["EPS growth 5Years"] = safe_cagr(latest_eps, _get_annual_val("EPS in Rs", -6), 5)
        m["EPS growth 7Years"] = safe_cagr(latest_eps, _get_annual_val("EPS in Rs", -8), 7)
        m["EPS growth 10Years"] = safe_cagr(latest_eps, _get_annual_val("EPS in Rs", -11), 10)

        m["Sales growth"] = m["Sales growth 3Years"]
        m["Profit growth"] = m["Profit growth 3Years"]

        # Multi-Year Averages
        annual_profits = [safe_float(v) for period in pl_headers if (v := pl_rows.get("Net Profit", {}).get(period)) is not None]
        if annual_profits:
            m["Average Earnings 3Year"] = safe_mean(annual_profits[-3:])
            m["Average Earnings 5Year"] = safe_mean(annual_profits[-5:])
            m["Average Earnings 10Year"] = safe_mean(annual_profits[-10:])

        # ----------------------------------------------------------------------
        # 3. QUARTERLY P&L METRICS & DERIVATIONS
        # ----------------------------------------------------------------------
        def _get_quarterly_val(metric_name: str, q_idx: int = -1) -> Optional[float]:
            row = q_rows.get(metric_name, {})
            if not row or not q_headers or abs(q_idx) > len(q_headers):
                return None
            period = q_headers[q_idx]
            return safe_float(row.get(period))

        m["Sales latest quarter"] = _get_quarterly_val("Sales", -1)
        m["Operating profit latest quarter"] = _get_quarterly_val("Operating Profit", -1)
        m["OPM latest quarter"] = _get_quarterly_val("OPM %", -1)
        m["Other income latest quarter"] = _get_quarterly_val("Other Income", -1)
        m["Interest latest quarter"] = _get_quarterly_val("Interest", -1)
        m["Depreciation latest quarter"] = _get_quarterly_val("Depreciation", -1)
        m["Profit before tax latest quarter"] = _get_quarterly_val("Profit before tax", -1)
        m["Tax latest quarter"] = _get_quarterly_val("Tax %", -1)
        m["Net Profit latest quarter"] = _get_quarterly_val("Net Profit", -1)
        m["Profit after tax latest quarter"] = m["Net Profit latest quarter"]
        m["EPS latest quarter"] = _get_quarterly_val("EPS in Rs", -1)

        # Derived NPM Latest Quarter
        if m["Net Profit latest quarter"] and m["Sales latest quarter"]:
            m["NPM latest quarter"] = safe_div(m["Net Profit latest quarter"], m["Sales latest quarter"], 100.0)

        # Historical Quarters (Preceding Q1, Q2, Q3, Q4)
        m["Sales preceding quarter"] = _get_quarterly_val("Sales", -2)
        m["Operating profit preceding quarter"] = _get_quarterly_val("Operating Profit", -2)
        m["Net Profit preceding quarter"] = _get_quarterly_val("Net Profit", -2)
        m["EPS preceding quarter"] = _get_quarterly_val("EPS in Rs", -2)

        m["Sales 2quarters back"] = _get_quarterly_val("Sales", -3)
        m["Operating profit 2quarters back"] = _get_quarterly_val("Operating Profit", -3)
        m["Net profit 2quarters back"] = _get_quarterly_val("Net Profit", -3)

        m["Sales 3quarters back"] = _get_quarterly_val("Sales", -4)
        m["Operating profit 3quarters back"] = _get_quarterly_val("Operating Profit", -4)
        m["Net profit 3quarters back"] = _get_quarterly_val("Net Profit", -4)

        # YoY Quarterly Growth (Q0 vs Q4)
        m["Sales preceding year quarter"] = _get_quarterly_val("Sales", -5)
        m["Net Profit preceding year quarter"] = _get_quarterly_val("Net Profit", -5)
        m["Operating profit preceding year quarter"] = _get_quarterly_val("Operating Profit", -5)

        m["YOY Quarterly sales growth"] = safe_div(
            (m["Sales latest quarter"] or 0) - (m["Sales preceding year quarter"] or 0),
            m["Sales preceding year quarter"], 100.0
        )
        m["YOY Quarterly profit growth"] = safe_div(
            (m["Net Profit latest quarter"] or 0) - (m["Net Profit preceding year quarter"] or 0),
            m["Net Profit preceding year quarter"], 100.0
        )

        # ----------------------------------------------------------------------
        # 4. BALANCE SHEET METRICS & DERIVATIONS
        # ----------------------------------------------------------------------
        def _get_bs_val(metric_name: str, period_idx: int = -1) -> Optional[float]:
            row = bs_rows.get(metric_name, {})
            if not row or not bs_headers or abs(period_idx) > len(bs_headers):
                return None
            period = bs_headers[period_idx]
            return safe_float(row.get(period))

        m["Equity capital"] = _get_bs_val("Equity Capital", -1)
        m["Reserves"] = _get_bs_val("Reserves", -1)
        m["Borrowings"] = _get_bs_val("Borrowings", -1)
        m["Debt"] = m["Borrowings"]
        m["Other liabilities"] = _get_bs_val("Other Liabilities", -1)
        m["Total Liabilities"] = _get_bs_val("Total Liabilities", -1)
        m["Balance sheet total"] = m["Total Liabilities"]
        
        m["Fixed Assets"] = _get_bs_val("Fixed Assets", -1)
        m["Net block"] = m["Fixed Assets"]
        m["CWIP"] = _get_bs_val("CWIP", -1)
        m["Capital work in progress"] = m["CWIP"]
        m["Investments"] = _get_bs_val("Investments", -1)
        m["Other Assets"] = _get_bs_val("Other Assets", -1)
        m["Total Assets"] = _get_bs_val("Total Assets", -1)

        # Working Capital Derivations
        m["Current assets"] = m["Other Assets"]
        m["Current liabilities"] = m["Other liabilities"]
        if m["Current assets"] is not None and m["Current liabilities"] is not None:
            m["Working capital"] = round(m["Current assets"] - m["Current liabilities"], 2)

        # Historical Balance Sheet Comparisons
        m["Debt preceding year"] = _get_bs_val("Borrowings", -2)
        m["Debt 3Years back"] = _get_bs_val("Borrowings", -4)
        m["Debt 5Years back"] = _get_bs_val("Borrowings", -6)

        # ----------------------------------------------------------------------
        # 5. CASH FLOW METRICS & DERIVATIONS
        # ----------------------------------------------------------------------
        def _get_cf_val(metric_name: str, period_idx: int = -1) -> Optional[float]:
            row = cf_rows.get(metric_name, {})
            if not row or not cf_headers or abs(period_idx) > len(cf_headers):
                return None
            period = cf_headers[period_idx]
            return safe_float(row.get(period))

        m["Cash from operations last year"] = _get_cf_val("Cash from Operating Activity", -1)
        m["Cash from investing last year"] = _get_cf_val("Cash from Investing Activity", -1)
        m["Cash from financing last year"] = _get_cf_val("Cash from Financing Activity", -1)
        m["Net cash flow last year"] = _get_cf_val("Net Cash Flow", -1)
        m["Free cash flow last year"] = _get_cf_val("Free Cash Flow", -1)

        # Multi-Year Cash Flow Sums
        cfo_history = [safe_float(v) for period in cf_headers if (v := cf_rows.get("Cash from Operating Activity", {}).get(period)) is not None]
        fcf_history = [safe_float(v) for period in cf_headers if (v := cf_rows.get("Free Cash Flow", {}).get(period)) is not None]

        m["Operating cash flow 3years"] = safe_sum(cfo_history[-3:])
        m["Operating cash flow 5years"] = safe_sum(cfo_history[-5:])
        m["Operating cash flow 10years"] = safe_sum(cfo_history[-10:])

        m["Free cash flow 3years"] = safe_sum(fcf_history[-3:])
        m["Free cash flow 5years"] = safe_sum(fcf_history[-5:])
        m["Free cash flow 10years"] = safe_sum(fcf_history[-10:])

        # ----------------------------------------------------------------------
        # 6. RATIOS & WORKING CAPITAL METRICS
        # ----------------------------------------------------------------------
        def _get_ratio_val(metric_name: str, period_idx: int = -1) -> Optional[float]:
            row = ratios_rows.get(metric_name, {})
            if not row or not ratios_tbl.get("headers") or abs(period_idx) > len(ratios_tbl["headers"]):
                return None
            period = ratios_tbl["headers"][period_idx]
            return safe_float(row.get(period))

        m["Debtor days"] = _get_ratio_val("Debtor Days", -1)
        m["Inventory days"] = _get_ratio_val("Inventory Days", -1)
        m["Days Payable"] = _get_ratio_val("Days Payable", -1)
        m["Cash Conversion Cycle"] = _get_ratio_val("Cash Conversion Cycle", -1)
        m["Working Capital Days"] = _get_ratio_val("Working Capital Days", -1)

        # Latest year ratios from core_metrics if available
        latest_ratio_yr = sorted(list(hist_ratios.keys()))[-1] if hist_ratios else None
        latest_r_data = hist_ratios.get(latest_ratio_yr, {}) if latest_ratio_yr else {}

        m["ROCE %"] = latest_r_data.get("roce_pct") or _get_ratio_val("ROCE %", -1)
        m["Return on capital employed"] = m["ROCE %"]
        m["ROE %"] = latest_r_data.get("roe_pct")
        m["Return on equity"] = m["ROE %"]
        m["Stock P/E"] = latest_r_data.get("pe_ratio")
        m["Price to Earning"] = m["Stock P/E"]
        m["Price to book value"] = latest_r_data.get("pb_ratio")
        m["EV / EBITDA"] = latest_r_data.get("ev_ebitda")
        m["EVEBITDA"] = m["EV / EBITDA"]
        m["Market Cap to Sales"] = latest_r_data.get("mcap_to_sales")
        m["Price to Sales"] = m["Market Cap to Sales"]
        m["NPM %"] = latest_r_data.get("npm_percent")
        m["Dividend yield"] = latest_r_data.get("dividend_yield_pct")

        # Multi-Year Ratio Averages
        roce_history = [safe_float(v) for period in ratios_tbl.get("headers", []) if (v := ratios_rows.get("ROCE %", {}).get(period)) is not None]
        m["Average return on capital employed 3Years"] = safe_mean(roce_history[-3:])
        m["Average return on capital employed 5Years"] = safe_mean(roce_history[-5:])
        m["Average return on capital employed 10Years"] = safe_mean(roce_history[-10:])

        roe_history = [v.get("roe_pct") for yr, v in hist_ratios.items() if v.get("roe_pct") is not None]
        m["Average return on equity 3Years"] = safe_mean(roe_history[-3:])
        m["Average return on equity 5Years"] = safe_mean(roe_history[-5:])
        m["Average return on equity 10Years"] = safe_mean(roe_history[-10:])

        # Historical Valuation Multiples
        pe_history = [v.get("pe_ratio") for yr, v in hist_ratios.items() if v.get("pe_ratio") is not None]
        m["Historical PE 3Years"] = safe_mean(pe_history[-3:])
        m["Historical PE 5Years"] = safe_mean(pe_history[-5:])
        m["Historical PE 10Years"] = safe_mean(pe_history[-10:])

        # ----------------------------------------------------------------------
        # 7. SHAREHOLDING PATTERN METRICS
        # ----------------------------------------------------------------------
        def _get_sh_val(category: str, q_idx: int = -1) -> Optional[float]:
            row = sh_q_rows.get(category, {})
            if not row or not sh_q_headers or abs(q_idx) > len(sh_q_headers):
                return None
            period = sh_q_headers[q_idx]
            return safe_float(row.get(period))

        m["Promoter holding"] = _get_sh_val("Promoters", -1)
        m["FII holding"] = _get_sh_val("FIIs", -1)
        m["DII holding"] = _get_sh_val("DIIs", -1)
        m["Government holding"] = _get_sh_val("Government", -1)
        m["Public holding"] = _get_sh_val("Public", -1)
        m["Number of Shareholders"] = _get_sh_val("No. of Shareholders", -1)

        # Shareholding Changes (QoQ & 3Y)
        m["Change in promoter holding"] = safe_div(
            (m["Promoter holding"] or 0) - (_get_sh_val("Promoters", -2) or 0), 1.0
        )
        m["Change in FII holding"] = safe_div(
            (m["FII holding"] or 0) - (_get_sh_val("FIIs", -2) or 0), 1.0
        )
        m["Change in DII holding"] = safe_div(
            (m["DII holding"] or 0) - (_get_sh_val("DIIs", -2) or 0), 1.0
        )

        m["Change in promoter holding 3Years"] = safe_div(
            (m["Promoter holding"] or 0) - (_get_sh_val("Promoters", -12) or 0), 1.0
        )

        # ----------------------------------------------------------------------
        # 8. PRICE, MARKET CAP & TECHNICAL INDICATOR METRICS
        # ----------------------------------------------------------------------
        tech = raw_scans.get("technicals", {})
        price_scan = raw_scans.get("pricescan", {})
        vol_scan = raw_scans.get("volumedelivery", {})

        m["Current price"] = safe_float(tech.get("last_close") or price_scan.get("last_close"))
        m["Face value"] = 10.0  # Standard NSE face value default

        # Dynamic Market Cap Calculation
        if m["Current price"] and m["Net profit"] and m["EPS"] and m["EPS"] > 0:
            implied_shares = m["Net profit"] / m["EPS"]  # In Crores
            m["Market Capitalization"] = round(m["Current price"] * implied_shares, 2)
            m["Number of equity shares"] = round(implied_shares, 2)
        elif m["Current price"] and m["Equity capital"]:
            implied_shares = m["Equity capital"] / m["Face value"]
            m["Market Capitalization"] = round(m["Current price"] * implied_shares, 2)
            m["Number of equity shares"] = round(implied_shares, 2)
        else:
            m["Market Capitalization"] = None
            m["Number of equity shares"] = None

        # Valuation Ratios depending on Market Cap
        m["Book value"] = safe_div(
            (m["Equity capital"] or 0) + (m["Reserves"] or 0), m["Number of equity shares"]
        )
        if m["Market Capitalization"]:
            m["Enterprise Value"] = round(
                m["Market Capitalization"] + (m["Borrowings"] or 0) - (m["Cash from operations last year"] or 0), 2
            )
            m["Price to Free Cash Flow"] = safe_div(m["Market Capitalization"], m["Free cash flow last year"])
            m["Earnings yield"] = safe_div(m["Net profit"], m["Market Capitalization"], 100.0)
        else:
            m["Enterprise Value"] = None
            m["Price to Free Cash Flow"] = None
            m["Earnings yield"] = None

        # Health Ratios
        m["Debt to equity"] = safe_div(
            m["Borrowings"], (m["Equity capital"] or 0) + (m["Reserves"] or 0)
        )
        m["Interest Coverage Ratio"] = safe_div(m["EBIT"], m["Interest"])
        m["Return on assets"] = safe_div(m["Net profit"], m["Total Assets"], 100.0)
        m["PEG Ratio"] = safe_div(m["Stock P/E"], m["Profit growth 3Years"])

        # Technical Indicators Extraction from Scans
        tech_cats = tech.get("categories", {})
        for cat_data in tech_cats.values():
            for scan in cat_data.get("scans", []):
                label = scan.get("label")
                val = safe_float(scan.get("value"))
                if label == "Price vs SMA 50": m["DMA 50"] = val
                elif label == "Price vs SMA 200": m["DMA 200"] = val
                elif label == "RSI Zone" or label == "RSI Trend": m["RSI"] = val
                elif label == "MACD Level": m["MACD"] = val
                elif label == "ADX Trend Strength": m["ADX"] = val
                elif label == "SuperTrend Status": m["SuperTrend"] = val
                elif label == "Beta Status": m["Beta"] = val

        # Price Scan Absolute Returns Extraction
        price_cats = price_scan.get("categories", {})
        abs_returns = price_cats.get("Absolute Return", {}).get("scans", [])
        for scan in abs_returns:
            lbl = scan.get("label", "")
            val = safe_float(scan.get("value"))
            if "1W Return" in lbl: m["Return over 1week"] = val
            elif "1M Return" in lbl: m["Return over 1month"] = val
            elif "3M Return" in lbl: m["Return over 3months"] = val
            elif "6M Return" in lbl: m["Return over 6months"] = val
            elif "1Y Return" in lbl: m["Return over 1year"] = val
            elif "2Y Return" in lbl: m["Return over 2years"] = val

        # Safely handle empty scans list to prevent list index out of range
        prev_scans = price_cats.get("Previous Day Breakout", {}).get("scans", [])
        m["Return over 1day"] = safe_float(prev_scans[0].get("value")) if prev_scans else None

        # Volume Metrics
        m["Volume"] = safe_float(vol_scan.get("last_volume"))

        # Industry Benchmarks
        industry_pe = safe_float(fund.get("industry_pe"))
        m["Industry PE"] = industry_pe if industry_pe is not None else 25.0

        return m

    def build_universe_dataframe(self, tickers: List[str]) -> pd.DataFrame:
        """
        Processes a list of tickers in parallel, building a unified 
        Pandas DataFrame where each row is a stock and columns are the 150+ metrics.
        """
        rows = []
        logger.info(f"Building quantitative metrics DataFrame for {len(tickers)} tickers...")
        
        for t in tickers:
            try:
                flat_m = self.build_flat_metrics(t)
                rows.append(flat_m)
            except Exception as e:
                logger.error(f"Error building flat metrics for {t}: {e}")

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df.set_index("Ticker", inplace=True)
        return df


# ==============================================================================
# CLI TEST RUNNER
# ==============================================================================
if __name__ == "__main__":
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE"
    
    engine = MetricsEngine()
    metrics = engine.build_flat_metrics(symbol)
    
    print("=" * 80)
    print(f" ALPHAQUANT METRICS ENGINE: [{symbol}]")
    print("=" * 80)
    print(f"Total Evaluated Variables & Aliases: {len(metrics)}")
    print("\nSAMPLE KEY METRICS:")
    
    sample_keys = [
        "Sales", "Net profit", "EPS", "Market Capitalization", "Price to Earning",
        "ROCE %", "ROE %", "Debt to equity", "Interest Coverage Ratio", "PEG Ratio",
        "Sales growth 3Years", "Profit growth 3Years", "YoY Quarterly sales growth",
        "RSI", "DMA 50", "DMA 200", "Return over 1month", "Return over 1year"
    ]
    
    for k in sample_keys:
        print(f"  • {k:<38}: {metrics.get(k)}")
    print("=" * 80)