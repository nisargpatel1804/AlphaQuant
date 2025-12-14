"""Streamlit dashboard for ReScanX (Fundamentals + Technicals)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import nest_asyncio
import streamlit as st

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# FUNDAMENTALS IMPORTS
from fundamentals.fetcher import ScreenerScraper
from fundamentals.utils import get_nifty_tickers
from fundamentals.scans import FundamentalScans

# TECHNICALS IMPORTS
# Ensure technicals module is reachable
try:
    from technicals.fetcher import TechnicalFetcher
    from technicals.indicators import TechnicalIndicators
    from technicals.scans import TechnicalScans
    HAS_TECHNICALS = True
except ImportError:
    HAS_TECHNICALS = False

# Fix async conflict: Allow nested event loops for Playwright within Streamlit
# nest_asyncio.apply()  # Commented out as it conflicts with Playwright

# --- Helper Functions (Fundamentals) ---

def _load_master_industry_map() -> List[Dict[str, Any]]:
    path = PROJECT_ROOT / "fundamentals" / "source" / "master_industry_map.json"
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

# --- Caching ---

@st.cache_data(show_spinner=False)
def cached_tickers() -> List[str]:
    """Cache the Nifty 500 list to avoid re-fetching on every interaction."""
    try:
        return get_nifty_tickers()
    except Exception:
        return []

@st.cache_resource(show_spinner=False)
def cached_fundamental_context() -> tuple[ScreenerScraper, Dict[str, str], Dict[str, float]]:
    scraper = ScreenerScraper(use_industry_pe_map=False)
    master_map = _load_master_industry_map()
    ticker_to_industry, industry_to_pe = _build_ticker_to_industry_and_pe(master_map)
    return scraper, ticker_to_industry, industry_to_pe

@st.cache_resource(show_spinner=False)
def cached_technical_fetcher() -> Optional[Any]:
    if HAS_TECHNICALS:
        return TechnicalFetcher()
    return None

# --- Main Logic ---

def main() -> None:
    st.set_page_config(
        page_title="ReScanX Dashboard",
        page_icon="📈",
        layout="wide"
    )

    # Initialize Services (no database)
    fund_scraper, ticker_to_industry, industry_pe_map = cached_fundamental_context()
    tech_fetcher = cached_technical_fetcher()

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
        
        st.markdown("---")
        scan_type = st.radio(
            "Choose Scan Type",
            ["Fundamentals", "Technicals"],
            index=0,
            help="Fundamentals: Financial health check\nTechnicals: Trend & momentum check"
        )
        
        # Data is always fetched fresh (no database cache).
        force_refresh = st.button("Refresh Data", help="Re-fetch data now")
        
        st.markdown("---")
        st.markdown("### Legend")
        if scan_type == "Fundamentals":
            st.success("High Quality")
            st.warning("Moderate")
            st.error("Low Quality")
        else:
            st.success("Bullish")
            st.error("Bearish")
            st.info("Neutral")

    if not ticker:
        return

    # --- Routing ---
    if scan_type == "Fundamentals":
        render_fundamentals(ticker, fund_scraper, ticker_to_industry, industry_pe_map, force_refresh)
    elif scan_type == "Technicals":
        if not HAS_TECHNICALS:
            st.error("Technical Analysis module not found. Check installation.")
        else:
            render_technicals(ticker, tech_fetcher, force_refresh)

# --- Renderers ---

def render_fundamentals(
    ticker: str, 
    scraper: ScreenerScraper,
    ticker_map: Dict, 
    pe_map: Dict, 
    force: bool
) -> None:
    # NOTE (Dec 2025): No database mode.
    # Always scrape fresh fundamentals for the selected ticker.
    #
    # Future fallback (commented): enable Supabase caching.
    # from fundamentals.database import SupabaseManager
    # manager = SupabaseManager()
    # data = manager.fetch_ticker(ticker)
    # if force or not data or SupabaseManager.needs_refresh(data):
    #     payload = scraper.fetch_company_payload(ticker)
    #     payload["ticker"] = ticker
    #     manager.upsert_record(payload)
    #     data = payload

    with st.spinner(f"Scraping Fundamentals for {ticker}..."):
        try:
            payload = scraper.fetch_company_payload(ticker)
            payload["ticker"] = ticker
            _apply_industry_context(payload, ticker=ticker, ticker_to_industry=ticker_map, industry_to_pe=pe_map)
            data = payload
            if force:
                st.toast("Data refreshed!", icon="✅")
        except Exception as e:
            st.error(f"Scraping failed: {e}")
            return

    # 2. Run Scans
    scanner = FundamentalScans(data)
    results = scanner.run_scans()
    metadata = scanner.metadata

    # 3. Header
    st.header(f"{ticker} - Fundamentals")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Current Price", f"₹{metadata.get('current_price', 0):,.2f}")
    m2.metric("Market Cap", f"₹{metadata.get('market_cap', 0):,.0f} Cr")
    m3.metric("Stock P/E", f"{metadata.get('stock_pe', 0):.1f}")
    m4.metric("Industry P/E", f"{metadata.get('industry_pe', 0):.1f}")
    st.caption(f"**Sector:** {metadata.get('industry', 'Unknown')}")

    st.divider()

    # 4. Scorecard & Tabs
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("High Quality", len(results.get("High", [])), delta="Strong", delta_color="normal")
    c2.metric("Moderate", len(results.get("Moderate", [])), delta="Avg", delta_color="off")
    c3.metric("Low Quality", len(results.get("Low", [])), delta="Weak", delta_color="inverse")
    c4.metric("Pending", len(results.get("Pending", [])))

    tabs = st.tabs(["High Quality", "Moderate", "Low Quality", "Pending", "Raw Data"])
    
    with tabs[0]: _display_grouped(results.get("High", []), "No high quality metrics found.", "High", mode="fund")
    with tabs[1]: _display_grouped(results.get("Moderate", []), "No moderate metrics found.", "Moderate", mode="fund")
    with tabs[2]: _display_grouped(results.get("Low", []), "No low quality metrics found.", "Low", mode="fund")
    with tabs[3]: _display_grouped(results.get("Pending", []), "No pending metrics.", "Pending", mode="fund")
    with tabs[4]: st.json(data)


def render_technicals(ticker: str, fetcher: TechnicalFetcher, force: bool) -> None:
    # 1. Fetch & Calculate (No database for technicals yet, live fetch usually preferred)
    # Ideally we'd cache this in session_state to avoid re-fetching on slight interactions
    
    if force or f"tech_data_{ticker}" not in st.session_state:
        with st.spinner(f"Fetching Technicals for {ticker}..."):
            try:
                daily_df, weekly_df = fetcher.fetch_stock_data(ticker)
                if daily_df.empty:
                    st.error("No data found.")
                    return
                
                bench = fetcher.fetch_benchmark()
                
                # Industry Beta
                ind_name, ind_beta = None, None
                if hasattr(fetcher, 'fetch_industry_beta_avg'):
                    ind_name, ind_beta = fetcher.fetch_industry_beta_avg(ticker, bench)
                    daily_df["INDUSTRY_BETA_AVG"] = ind_beta

                TechnicalIndicators.add_all_indicators(daily_df, is_weekly=False, benchmark_data=bench)
                TechnicalIndicators.add_all_indicators(weekly_df, is_weekly=True)
                
                scanner = TechnicalScans(daily_df, weekly_df)
                results = scanner.run_all()
                
                # Store in session state
                st.session_state[f"tech_data_{ticker}"] = {
                    "results": results,
                    "daily": daily_df,
                    "meta": {"last_close": daily_df['Close'].iloc[-1], "industry": ind_name}
                }
                
            except Exception as e:
                st.error(f"Technical Analysis failed: {e}")
                return

    # 2. Retrieve from Cache
    cached = st.session_state[f"tech_data_{ticker}"]
    results = cached["results"]
    meta = cached["meta"]
    
    # 3. Header
    st.header(f"{ticker} - Technicals")
    st.metric("Last Close", f"₹{meta['last_close']:,.2f}")
    if meta.get("industry"):
        st.caption(f"**Sector:** {meta['industry']}")

    st.divider()

    # 4. Scorecard & Tabs
    bull_count = len(results.get("Bullish", []))
    bear_count = len(results.get("Bearish", []))
    neut_count = len(results.get("Neutral", []))
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Bullish Signals", bull_count, delta="Buy", delta_color="normal")
    c2.metric("Bearish Signals", bear_count, delta="Sell", delta_color="inverse")
    c3.metric("Neutral Signals", neut_count, delta="Hold", delta_color="off")

    tabs = st.tabs(["Bullish", "Bearish", "Neutral", "Pending"])
    
    with tabs[0]: _display_grouped(results.get("Bullish", []), "No bullish signals.", "Bullish", mode="tech")
    with tabs[1]: _display_grouped(results.get("Bearish", []), "No bearish signals.", "Bearish", mode="tech")
    with tabs[2]: _display_grouped(results.get("Neutral", []), "No neutral signals.", "Neutral", mode="tech")
    with tabs[3]: _display_grouped(results.get("Pending", []), "No pending scans.", "Pending", mode="tech")


# --- Helper Rendering Functions ---

def _display_grouped(items: List[Dict[str, Any]], empty_msg: str, status_type: str, mode: str) -> None:
    if not items:
        st.info(empty_msg)
        return
    
    grouped = {}
    for item in items:
        grouped.setdefault(item["category"], []).append(item)
        
    for cat, rows in grouped.items():
        with st.expander(f"{cat} ({len(rows)})", expanded=True):
            for row in rows:
                val = row.get("value")
                val_str = _format_value(val)
                status_text = row.get('status', status_type)
                
                # Icons
                prefix = "⚪"
                if mode == "fund":
                    if status_type == "High": prefix = "✅"
                    elif status_type == "Moderate": prefix = "⚠️"
                    elif status_type == "Low": prefix = "🔻"
                else: # tech
                    if status_type == "Bullish": prefix = "🟢"
                    elif status_type == "Bearish": prefix = "🔴"
                    elif status_type == "Neutral": prefix = "⚪"

                st.markdown(f"{prefix} **{row['label']}**: {status_text} {val_str}")


def _display_list(items: List[Dict[str, Any]], empty_message: str) -> None:
    if not items:
        st.info(empty_message)
        return
    for item in items:
        st.markdown(f"- **{item['label']}** ({item['category']})")


def _format_value(value: Any) -> str:
    if value is None: return ""
    if isinstance(value, (int, float)):
        if abs(value) > 1000: return f"({value:,.0f})"
        return f"({value:,.2f})"
    return f"({value})"


if __name__ == "__main__":
    main()