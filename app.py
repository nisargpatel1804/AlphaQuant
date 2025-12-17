"""
ReScanX Master Dashboard.
Integrates Fundamentals, Technicals, and Price Scans into a unified Streamlit interface.
"""
from __future__ import annotations

import sys
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

# 1. Setup Project Path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 2. Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# 3. Conditional Imports (Graceful Degradation)
HAS_FUNDAMENTALS = False
HAS_TECHNICALS = False
HAS_PRICESCANS = False

# --- Fundamentals ---
try:
    from fundamentals.fetcher import ScreenerScraper
    from fundamentals.utils import get_nifty_tickers, load_master_industry_map, build_ticker_to_industry_and_pe, apply_industry_context
    from fundamentals.scans import FundamentalScans
    HAS_FUNDAMENTALS = True
except ImportError as e:
    logger.warning(f"Fundamentals module not loaded: {e}")

# --- Technicals ---
try:
    from technicals.fetcher import TechnicalFetcher
    from technicals.indicators import TechnicalIndicators
    from technicals.scans import TechnicalScans
    HAS_TECHNICALS = True
except ImportError as e:
    logger.warning(f"Technicals module not loaded: {e}")

# --- Price Scans ---
try:
    from pricescan.main import PriceScanEngine
    from pricescan.models import TickerPriceScanData
    HAS_PRICESCANS = True
except ImportError as e:
    logger.warning(f"Price Scan module not loaded: {e}")


# 4. Page Configuration
st.set_page_config(
    page_title="ReScanX Analytics",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --------------------------------------------------------------------------
# Resource Caching
# --------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_cached_tickers() -> List[str]:
    """Cache the Nifty 500 list."""
    if HAS_FUNDAMENTALS:
        try:
            return get_nifty_tickers()
        except Exception:
            return []
    return []

@st.cache_resource(show_spinner=False)
def get_fundamental_resources():
    """Cache the scraper and industry maps."""
    if not HAS_FUNDAMENTALS: return None, {}, {}
    scraper = ScreenerScraper(use_industry_pe_map=False)
    master_map = load_master_industry_map()
    ticker_to_ind, ind_to_pe = build_ticker_to_industry_and_pe(master_map)
    return scraper, ticker_to_ind, ind_to_pe

@st.cache_resource(show_spinner=False)
def get_technical_fetcher():
    """Cache the Technical Fetcher."""
    if HAS_TECHNICALS:
        return TechnicalFetcher()
    return None

@st.cache_resource(show_spinner="Initializing Sector Engine...")
def get_pricescan_engine():
    """
    Cache the PriceScanEngine.
    CRITICAL: This builds/loads Sector Indices on first run.
    """
    if HAS_PRICESCANS:
        # update_sectors=False ensures we rely on existing data if available for speed
        return PriceScanEngine(update_sectors=False)
    return None

# --------------------------------------------------------------------------
# Main UI Logic
# --------------------------------------------------------------------------

def main():
    # --- Sidebar ---
    with st.sidebar:
        st.title("ReScanX")
        st.caption("v2.0 | Integrated Analytics")
        
        # Ticker Selection
        tickers = get_cached_tickers()
        if not tickers:
            st.error("Ticker list unavailable.")
            return

        default_idx = tickers.index("RELIANCE") if "RELIANCE" in tickers else 0
        selected_ticker = st.selectbox("Select Ticker", tickers, index=default_idx)
        
        st.divider()
        
        # Module Selection
        available_modules = []
        if HAS_FUNDAMENTALS: available_modules.append("Fundamentals")
        if HAS_TECHNICALS: available_modules.append("Technicals")
        if HAS_PRICESCANS: available_modules.append("Price Scans")
        
        if not available_modules:
            st.error("No analysis modules found.")
            return

        scan_type = st.radio("Analysis Type", available_modules)
        
        st.divider()
        force_refresh = st.button("Refresh Data", icon="🔄", help="Force re-fetch of live data")

    # --- Routing ---
    if scan_type == "Fundamentals":
        scraper, t_map, p_map = get_fundamental_resources()
        render_fundamentals(selected_ticker, scraper, t_map, p_map, force_refresh)
        
    elif scan_type == "Technicals":
        fetcher = get_technical_fetcher()
        render_technicals(selected_ticker, fetcher, force_refresh)
        
    elif scan_type == "Price Scans":
        engine = get_pricescan_engine()
        render_price_scans(selected_ticker, engine, force_refresh)

# --------------------------------------------------------------------------
# Renderers
# --------------------------------------------------------------------------

def render_fundamentals(ticker: str, scraper: Any, t_map: Dict, p_map: Dict, force: bool):
    st.title(f"Fundamentals: {ticker}")
    
    if not scraper:
        st.error("Fundamentals engine not initialized.")
        return

    # Session State Caching for Live Scrape
    cache_key = f"fund_{ticker}"
    if force or cache_key not in st.session_state:
        with st.spinner(f"Scraping Fundamentals for {ticker}..."):
            try:
                payload = scraper.fetch_company_payload(ticker)
                payload["ticker"] = ticker
                apply_industry_context(payload, ticker=ticker, ticker_to_industry=t_map, industry_to_pe=p_map)
                
                scanner = FundamentalScans(payload)
                results = scanner.run_scans()
                
                st.session_state[cache_key] = {
                    "data": payload,
                    "results": results,
                    "meta": scanner.metadata
                }
            except Exception as e:
                st.error(f"Analysis failed: {e}")
                return

    # Render
    data = st.session_state[cache_key]
    meta = data["meta"]
    results = data["results"]

    # Metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Price", f"₹{meta.get('current_price', 0):,.2f}")
    c2.metric("Market Cap", f"₹{meta.get('market_cap', 0):,.0f} Cr")
    c3.metric("Stock P/E", f"{meta.get('stock_pe', 0):.1f}")
    c4.metric("Industry P/E", f"{meta.get('industry_pe', 0):.1f}")
    st.caption(f"Sector: **{meta.get('industry', 'N/A')}**")

    st.divider()

    # Tabs
    tabs = st.tabs(["High Quality", "Moderate", "Low Quality", "Pending", "Raw JSON"])
    with tabs[0]: _render_scan_group(results.get("High", []), "fund", "High")
    with tabs[1]: _render_scan_group(results.get("Moderate", []), "fund", "Moderate")
    with tabs[2]: _render_scan_group(results.get("Low", []), "fund", "Low")
    with tabs[3]: _render_scan_group(results.get("Pending", []), "fund", "Pending")
    with tabs[4]: st.json(data["data"])


def render_technicals(ticker: str, fetcher: Any, force: bool):
    st.title(f"Technicals: {ticker}")
    
    if not fetcher:
        st.error("Technical engine not initialized.")
        return

    cache_key = f"tech_{ticker}"
    if force or cache_key not in st.session_state:
        with st.spinner(f"Analyzing Technicals for {ticker}..."):
            try:
                d_df, w_df = fetcher.fetch_stock_data(ticker)
                if d_df.empty:
                    st.warning("No data returned.")
                    return
                
                bench = fetcher.fetch_benchmark()
                
                # Industry Beta
                ind_name = None
                if hasattr(fetcher, 'fetch_industry_beta_avg'):
                    ind_name, ind_beta = fetcher.fetch_industry_beta_avg(ticker, bench)
                    d_df["INDUSTRY_BETA_AVG"] = ind_beta

                TechnicalIndicators.add_all_indicators(d_df, is_weekly=False, benchmark_data=bench)
                TechnicalIndicators.add_all_indicators(w_df, is_weekly=True)
                
                scanner = TechnicalScans(d_df, w_df)
                results = scanner.run_all()
                
                st.session_state[cache_key] = {
                    "results": results,
                    "last_close": d_df['Close'].iloc[-1],
                    "industry": ind_name
                }
            except Exception as e:
                st.error(f"Technical analysis failed: {e}")
                return

    data = st.session_state[cache_key]
    results = data["results"]
    
    st.metric("Last Close", f"₹{data['last_close']:,.2f}")
    if data['industry']: st.caption(f"Sector: **{data['industry']}**")
    
    st.divider()
    
    # Scorecard
    c1, c2, c3 = st.columns(3)
    c1.metric("Bullish", len(results.get("Bullish", [])), delta="Signals")
    c2.metric("Bearish", len(results.get("Bearish", [])), delta_color="inverse", delta="Signals")
    c3.metric("Neutral", len(results.get("Neutral", [])), delta_color="off", delta="Signals")

    tabs = st.tabs(["Bullish", "Bearish", "Neutral", "Pending"])
    with tabs[0]: _render_scan_group(results.get("Bullish", []), "tech", "Bullish")
    with tabs[1]: _render_scan_group(results.get("Bearish", []), "tech", "Bearish")
    with tabs[2]: _render_scan_group(results.get("Neutral", []), "tech", "Neutral")
    with tabs[3]: _render_scan_group(results.get("Pending", []), "tech", "Pending")


def render_price_scans(ticker: str, engine: Any, force: bool):
    st.title(f"Price Scans: {ticker}")
    
    if not engine:
        st.error("Price Scan engine not initialized.")
        return

    cache_key = f"price_{ticker}"
    if force or cache_key not in st.session_state:
        with st.spinner(f"Running Price Scans for {ticker}..."):
            try:
                # engine.process_ticker returns a TickerPriceScanData dataclass
                result_obj = engine.process_ticker(ticker)
                
                if result_obj is None:
                    st.warning("No data processed.")
                    return

                st.session_state[cache_key] = result_obj
            except Exception as e:
                st.error(f"Price scan failed: {e}")
                return

    data = st.session_state[cache_key] # This is TickerPriceScanData object
    results = data.scan_results # Dict[str, List[Dict]]
    summary = getattr(data, "scan_summary", {}) or {}
    
    st.metric("Last Close", f"₹{data.last_close:,.2f}")
    st.caption(f"Sector: **{data.industry}**")
    
    st.divider()
    
    # Scorecard
    c1, c2, c3 = st.columns(3)
    c1.metric("Bullish Scans", len(results.get("Bullish", [])), delta="Triggered")
    c2.metric("Bearish Scans", len(results.get("Bearish", [])), delta_color="inverse", delta="Triggered")
    c3.metric("Neutral / Range", len(results.get("Neutral", [])), delta_color="off", delta="Triggered")

    # Coverage / completion info (answers: "do these sum to 117?")
    expected_total = summary.get("expected_total")
    implemented_total = summary.get("implemented_total")
    triggered_total = summary.get("triggered_total")
    if expected_total and implemented_total is not None and triggered_total is not None:
        st.caption(
            f"Coverage: Triggered **{triggered_total}** / Implemented **{implemented_total}** (Target: **{expected_total}**). "
            f"Counts in the tabs reflect *triggered* scans only."
        )

    tabs = st.tabs(["Bullish", "Bearish", "Neutral", "Pending"])
    with tabs[0]: _render_scan_group(results.get("Bullish", []), "price", "Bullish")
    with tabs[1]: _render_scan_group(results.get("Bearish", []), "price", "Bearish")
    with tabs[2]: _render_scan_group(results.get("Neutral", []), "price", "Neutral")
    with tabs[3]: _render_scan_group(results.get("Pending", []), "price", "Pending")


# --------------------------------------------------------------------------
# UI Helpers
# --------------------------------------------------------------------------

def _render_scan_group(items: List[Dict[str, Any]], mode: str, group_name: str):
    """
    Renders a list of scan results grouped by their Category/Subtype.
    """
    if not items:
        st.info(f"No {group_name.lower()} scans found.")
        return

    # Group items by 'category' (which is mapped from 'subtype' in Price Scans)
    grouped = {}
    for item in items:
        cat = item.get("category", "Uncategorized")
        grouped.setdefault(cat, []).append(item)
    
    # Render Expanders
    for category, rows in grouped.items():
        with st.expander(f"{category} ({len(rows)})", expanded=True):
            for row in rows:
                label = row.get("label", "Unknown")
                val = row.get("value")
                status = row.get("status", "")
                
                # Format Value
                val_display = ""
                if val is not None:
                    if isinstance(val, (int, float)):
                        val_display = f"({val:,.2f})"
                    else:
                        val_display = f"({val})"

                # Icon Logic
                icon = "⚪"
                if mode == "fund":
                    if group_name == "High": icon = "✅"
                    elif group_name == "Moderate": icon = "⚠️"
                    elif group_name == "Low": icon = "🔻"
                elif mode in ["tech", "price"]:
                    if group_name == "Bullish": icon = "🟢"
                    elif group_name == "Bearish": icon = "🔴"
                    elif group_name == "Neutral": icon = "🔵"

                st.markdown(f"{icon} **{label}** : {status} {val_display}")

if __name__ == "__main__":
    main()