"""AlphaQuant Master Dashboard – Integrated with Fundamentals, Technicals, and all 7 scan types.
   Supports symbol input and multi‑tab analysis.
   Fundamentals are loaded only when requested.
"""

from __future__ import annotations

import asyncio
import json
import sys
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

# ----------------------------------------------------------------------
# Setup project path – add scans directory to sys.path
# ----------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
SCANS_DIR = PROJECT_ROOT / "scans"
if SCANS_DIR.exists() and str(SCANS_DIR) not in sys.path:
    sys.path.insert(0, str(SCANS_DIR))

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Import the fundamental scraper (now from scans directory)
# ----------------------------------------------------------------------
try:
    from fundamental_scraper import scrape_screener_complete
except ImportError as e:
    st.error(f"Fundamental scraper module not found. Make sure 'fundamental_scraper.py' is in the 'scans' folder. Error: {e}")
    sys.exit(1)

def run_fundamental_scraper(ticker: str) -> Dict[str, Any]:
    """Run the async scraper and return data."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        data = loop.run_until_complete(scrape_screener_complete(ticker))
        return data
    except Exception as e:
        st.error(f"Fundamental scraping failed: {e}")
        return {}

# ----------------------------------------------------------------------
# Helper functions to display fundamentals in tabular format
# ----------------------------------------------------------------------
def display_historical_ratios(data: Dict[str, Any]):
    """Show core_metrics.historical_ratios as a DataFrame."""
    hist_ratios = data.get("core_metrics", {}).get("historical_ratios", {})
    if not hist_ratios:
        st.info("No historical ratios found.")
        return
    df = pd.DataFrame.from_dict(hist_ratios, orient="index")
    df.index.name = "Year"
    st.subheader("📈 Historical Ratios (Yearly)")
    st.dataframe(df, use_container_width=True)

def display_raw_table(table_dict: Dict[str, Any], title: str):
    """Display a raw financial table (headers + rows) as a DataFrame."""
    if not table_dict or not table_dict.get("rows"):
        st.info(f"No data for {title}")
        return
    rows = table_dict.get("rows", {})
    if not rows:
        return
    # Build DataFrame: rows as metrics, columns as periods
    df = pd.DataFrame(rows).T  # transpose so periods become columns
    # Sort columns (periods) chronologically
    try:
        def period_sort_key(p):
            parts = p.split()
            if len(parts) == 2:
                month, year = parts[0], int(parts[1])
                order = {"Mar": 3, "Jun": 6, "Sep": 9, "Dec": 12}
                return (year, order.get(month, 0))
            return (0, 0)
        sorted_cols = sorted(df.columns, key=period_sort_key)
        df = df[sorted_cols]
    except Exception:
        pass
    st.subheader(title)
    st.dataframe(df, use_container_width=True)

def display_all_fundamental_tables(data: Dict[str, Any]):
    """Display all fundamental data in expandable sections."""
    display_historical_ratios(data)

    with st.expander("📊 Quarterly Results", expanded=False):
        display_raw_table(data.get("quarterly_results", {}), "Quarterly Results")
    with st.expander("📈 Profit & Loss (Annual)", expanded=False):
        display_raw_table(data.get("profit_loss_annual", {}), "Profit & Loss (Annual)")
    with st.expander("📉 Balance Sheet", expanded=False):
        display_raw_table(data.get("balance_sheet", {}), "Balance Sheet")
    with st.expander("💵 Cash Flow", expanded=False):
        display_raw_table(data.get("cash_flow", {}), "Cash Flow")
    with st.expander("📐 Ratios", expanded=False):
        display_raw_table(data.get("ratios", {}), "Ratios")
    with st.expander("👥 Shareholding Pattern", expanded=False):
        shareholding = data.get("shareholding", {})
        if shareholding:
            st.subheader("Quarterly Shareholding")
            display_raw_table(shareholding.get("quarterly", {}), "Quarterly")
            st.subheader("Yearly Shareholding")
            display_raw_table(shareholding.get("yearly", {}), "Yearly")

# ----------------------------------------------------------------------
# Placeholder functions for other scanners (lightweight, do nothing heavy)
# ----------------------------------------------------------------------
def placeholder_analysis(scan_name: str):
    st.info(f"{scan_name} – This analysis will be available in a future update.")

# ----------------------------------------------------------------------
# Streamlit Page Configuration
# ----------------------------------------------------------------------
st.set_page_config(page_title="AlphaQuant", page_icon="📊", layout="wide")

# ----------------------------------------------------------------------
# Root Page / Home
# ----------------------------------------------------------------------
def home_page():
    st.title("📈 AlphaQuant Analytics")
    st.markdown("### Welcome to the complete stock analysis suite")

    col1, col2 = st.columns([3, 1])
    with col1:
        symbol = st.text_input("Enter Stock Symbol (e.g., RELIANCE, INFY, TCS)", value="RELIANCE").strip().upper()
    with col2:
        if st.button("🔍 Analyze", type="primary"):
            st.query_params["symbol"] = symbol
            st.query_params["tab"] = "fundamentals"
            st.rerun()

    st.divider()
    st.subheader("🧰 Additional Tools")
    tool_cols = st.columns(4)
    with tool_cols[0]:
        if st.button("📊 Backtester"):
            st.markdown("[Open Backtester](./backtester)", unsafe_allow_html=True)
            st.info("Backtester will be integrated soon.")
    with tool_cols[1]:
        if st.button("📅 Seasonality"):
            st.info("Seasonality analysis – will be implemented soon.")
    with tool_cols[2]:
        if st.button("🏭 Sector Analysis"):
            st.info("Sector analysis – will be implemented soon.")
    with tool_cols[3]:
        if st.button("📉 Tickertape (MMI)"):
            st.info("Tickertape Market Mood Index – will be implemented soon.")

    st.markdown("---")
    st.markdown("**Note:** The Fundamentals scanner uses the final Screener scraper (Playwright) and may take 20‑40 seconds to load on first run. Other scanners are under development.")

# ----------------------------------------------------------------------
# Scans Page (Multi‑tab) – only fundamentals are loaded on demand
# ----------------------------------------------------------------------
def scans_page(symbol: str):
    st.title(f"📊 {symbol} – Complete Analysis")
    tabs = st.tabs([
        "Fundamentals", "Technicals", "Price Scans", "Volume & Delivery",
        "Futures & Options", "Strike Options", "Candlestick Scans"
    ])

    # ---- Fundamentals Tab ----
    with tabs[0]:
        load_key = f"fund_loaded_{symbol}"
        if load_key not in st.session_state:
            st.session_state[load_key] = False

        if not st.session_state[load_key]:
            if st.button("📥 Load Fundamental Data", type="primary"):
                with st.spinner(f"Loading fundamental data for {symbol} ... (this may take 20‑40 seconds)"):
                    data = run_fundamental_scraper(symbol)
                    if data:
                        st.session_state[f"fund_data_{symbol}"] = data
                        st.session_state[load_key] = True
                        st.rerun()
                    else:
                        st.error("Failed to fetch fundamentals.")
            else:
                st.info("Click the button above to load fundamental data.")
        else:
            data = st.session_state.get(f"fund_data_{symbol}")
            if data:
                display_all_fundamental_tables(data)
            else:
                st.warning("Data unavailable. Please reload.")

    # ---- Other Tabs (placeholders, no heavy operations) ----
    with tabs[1]:
        placeholder_analysis("Technical Analysis")
    with tabs[2]:
        placeholder_analysis("Price Scans")
    with tabs[3]:
        placeholder_analysis("Volume & Delivery")
    with tabs[4]:
        placeholder_analysis("Futures & Options")
    with tabs[5]:
        placeholder_analysis("Strike Options")
    with tabs[6]:
        placeholder_analysis("Candlestick Patterns")

# ----------------------------------------------------------------------
# Main Routing Logic
# ----------------------------------------------------------------------
def main():
    params = st.query_params
    if "symbol" in params:
        symbol = params["symbol"]
        scans_page(symbol)
    else:
        home_page()

if __name__ == "__main__":
    main()