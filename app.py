"""Streamlit dashboard for Nifty 500 fundamental scans."""
from __future__ import annotations

import sys
from pathlib import Path

from typing import Any, Dict, List

import nest_asyncio
import streamlit as st

# Allow importing modules from the `fundamentals/` folder when running:
# `streamlit run fundamentals/app/app.py`
_FUNDAMENTALS_DIR = Path(__file__).resolve().parent
if str(_FUNDAMENTALS_DIR) not in sys.path:
    sys.path.insert(0, str(_FUNDAMENTALS_DIR))

from db_manager import SupabaseManager
from fundamentals.screener_scraper import ScreenerScraper, get_nifty_tickers
from fundamentals.scans import FundamentalScans


def _load_master_industry_map() -> List[Dict[str, Any]]:
    path = _FUNDAMENTALS_DIR / "fundamentals" / "source" / "master_industry_map.json"
    if not path.exists():
        return []
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def _build_ticker_to_industry_and_pe(master_map: List[Dict[str, Any]]) -> tuple[Dict[str, str], Dict[str, float]]:
    ticker_to_industry: Dict[str, str] = {}
    industry_to_pe: Dict[str, float] = {}

    for entry in master_map:
        industry = (entry.get("industry") or "").strip()
        tickers = entry.get("stocks") or []
        pe = entry.get("industry_pe")

        if industry:
            try:
                if pe is not None:
                    industry_to_pe[industry] = float(pe)
            except Exception:
                pass

        if industry and isinstance(tickers, list):
            for ticker in tickers:
                t = str(ticker).strip().upper()
                if t:
                    ticker_to_industry[t] = industry

    return ticker_to_industry, industry_to_pe


def _apply_industry_context(
    payload: Dict[str, Any],
    *,
    ticker: str,
    ticker_to_industry: Dict[str, str],
    industry_to_pe: Dict[str, float],
) -> None:
    t = ticker.strip().upper()
    industry = ticker_to_industry.get(t)
    if not industry:
        return

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        payload["metadata"] = metadata

    metadata["industry"] = industry
    pe = industry_to_pe.get(industry)
    if pe is not None:
        metadata["industry_pe"] = pe
        payload["industry_pe"] = pe

# Fix async conflict: Allow nested event loops for Playwright within Streamlit
nest_asyncio.apply()


@st.cache_data(show_spinner=False)
def cached_tickers() -> List[str]:
    """Cache the Nifty 500 list to avoid re-fetching on every interaction."""
    try:
        return get_nifty_tickers()
    except Exception:
        return []


@st.cache_resource(show_spinner=False)
def cached_industry_context() -> tuple[ScreenerScraper, Dict[str, str], Dict[str, float]]:
    scraper = ScreenerScraper(use_industry_pe_map=False)
    master_map = _load_master_industry_map()
    ticker_to_industry, industry_to_pe = _build_ticker_to_industry_and_pe(master_map)
    return scraper, ticker_to_industry, industry_to_pe


def main() -> None:
    st.set_page_config(
        page_title="ReScanX Fundamentals",
        page_icon="R",
        layout="wide"
    )

    manager = SupabaseManager()
    scraper, ticker_to_industry, industry_pe_map = cached_industry_context()

    # --- Sidebar Controls ---
    with st.sidebar:
        st.title("ReScanX")
        st.markdown("### Nifty 500 Screener")
        
        tickers = cached_tickers()
        if not tickers:
            st.error("Failed to load ticker list.")
            return

        # Search and select stock
        ticker = st.selectbox(
            "Select Stock", 
            tickers, 
            index=tickers.index("RELIANCE") if "RELIANCE" in tickers else 0
        )
        
        scan_type = "Fundamentals"  # Default
        force_refresh = False
        
        if ticker:
            st.markdown("---")
            scan_type = st.radio(
                "Choose Scan Type",
                ["Fundamentals", "Technicals (Coming Soon)"],
                index=0,
                help="Fundamentals: 101 scans on financial data\nTechnicals: Chart analysis (not yet implemented)"
            )
            
            if scan_type == "Fundamentals":
                force_refresh = st.button("Force Refresh Data", help="Clear cache and re-scrape Screener.in")
            else:
                st.info("Technicals scan is not yet implemented. Please select Fundamentals.")
        
        st.markdown("### About")
        st.info(
            "This tool performs **101 Fundamental Scans** tailored to Indian stocks. "
            "It strictly processes data from consolidated or standalone sources based on Nifty 500 definitions. "
            "Scans are classified as Pass, Fail, or Pending based on data availability."
        )

    if not ticker or scan_type != "Fundamentals":
        return

    # --- Data Fetching Logic ---
    data = manager.fetch_ticker(ticker)
    
    # Check if data is stale (>24h) or missing, or if user forced refresh
    needs_refresh = force_refresh or not data or SupabaseManager.needs_refresh(data)

    if needs_refresh:
        status_container = st.empty()
        with status_container.container():
            with st.spinner(f"Scraping latest data for {ticker} from Screener.in..."):
                try:
                    payload = scraper.fetch_company_payload(ticker)
                    payload["ticker"] = ticker
                    _apply_industry_context(
                        payload,
                        ticker=ticker,
                        ticker_to_industry=ticker_to_industry,
                        industry_to_pe=industry_pe_map,
                    )
                    manager.upsert_record(payload)
                    st.success("Data updated successfully!")
                except Exception as e:
                    error_msg = str(e)
                    if "getaddrinfo failed" in error_msg or "Name resolution failure" in error_msg:
                        st.error("Unable to connect to Screener.in. Please check your internet connection and try again.")
                    else:
                        st.error(f"Scraping failed: {error_msg}")
                    # If scrape fails but we have old data, try to use it
                    if not data:
                        return
        
        # Re-fetch fresh data
        data = manager.fetch_ticker(ticker)
        status_container.empty() # Clear loading message

    if not data:
        st.error("Unable to load data. Please try refreshing.")
        return

    # --- Execution Logic ---
    scanner = FundamentalScans(data)
    results = scanner.run_scans()
    metadata = scanner.metadata

    # --- Dashboard Header ---
    st.header(f"{ticker} Analysis")
    
    # Top Metrics Row
    m1, m2, m3, m4 = st.columns(4)
    
    price = metadata.get('current_price')
    mcap = metadata.get('market_cap')
    pe = metadata.get('stock_pe')
    ind_pe = metadata.get('industry_pe')
    
    m1.metric("Current Price", f"₹ {price:,.2f}" if price else "—")
    m2.metric("Market Cap", f"₹ {mcap:,.0f} Cr" if mcap else "—")
    m3.metric("Stock P/E", f"{pe:.1f}" if pe else "—")
    m4.metric("Industry P/E", f"{ind_pe:.1f}" if ind_pe else "—")

    # Industry Context
    st.caption(f"**Sector:** {metadata.get('industry', 'Unknown')} | **Archetype:** {scanner.archetype}")

    # --- Scorecard ---
    counts = {
        "pass": len(results.get("pass", [])),
        "fail": len(results.get("fail", [])),
        "pending": len(results.get("pending", [])),
    }
    
    st.divider()
    score_c1, score_c2, score_c3, score_c4 = st.columns(4)
    score_c1.metric("Passed", counts.get("pass", 0))
    score_c2.metric("Failed", counts.get("fail", 0))
    score_c3.metric("Pending", counts.get("pending", 0))
    score_c4.metric("Total Scans", counts.get("pass", 0) + counts.get("fail", 0) + counts.get("pending", 0))

    # --- Detailed Results Tabs ---
    tab_pass, tab_fail, tab_pend, tab_raw = st.tabs([
        "Passed",
        "Failed",
        "Pending",
        "Raw Data",
    ])

    with tab_pass:
        _display_grouped(results.get("pass", []), "No scans passed yet.", is_success=True)

    with tab_fail:
        _display_grouped(results.get("fail", []), "No failed scans.", is_success=False)

    with tab_pend:
        st.markdown(
            "> **Pending** means the scan is **non-calculable** with the available data."
        )
        _display_list(results.get("pending", []), "No pending scans.")

    with tab_raw:
        with st.expander("Inspect JSON Payload", expanded=False):
            st.json(data)


# --- Helper Rendering Functions ---

def _display_grouped(items: List[Dict[str, Any]], empty_message: str, is_success: bool) -> None:
    """Group scans by category inside expanders."""
    if not items:
        st.info(empty_message)
        return
        
    # Group items by category
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(item["category"], []).append(item)
    
    # Render categories
    for category, rows in grouped.items():
        # Add count to category header
        header = f"{category} ({len(rows)})"
        with st.expander(header, expanded=True):
            for row in rows:
                value_str = _format_value(row.get("value"))
                label_prefix = "[PASS]" if is_success else "[FAIL]"
                st.markdown(f"**{label_prefix} {row['label']}** {value_str}")


def _display_list(items: List[Dict[str, Any]], empty_message: str) -> None:
    """Simple list for pending items."""
    if not items:
        st.info(empty_message)
        return
    
    for item in items:
        st.markdown(f"- **{item['label']}** ({item['category']})")


def _format_value(value: Any) -> str:
    """Format numeric values for display."""
    if value is None:
        return ""
    
    if isinstance(value, float):
        # Format percentage-like numbers logic could be added here if needed
        # For now, general float formatting
        if abs(value) > 1000:
            return f"— **{value:,.0f}**"
        return f"— **{value:,.2f}**"
        
    return f"— **{value}**"


if __name__ == "__main__":
    main()