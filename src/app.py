"""Streamlit dashboard for Nifty 500 fundamental scans."""
from __future__ import annotations

from typing import Any, Dict, List

import nest_asyncio
import streamlit as st

from db_manager import SupabaseManager
from screener_scraper import ScreenerScraper, get_nifty_tickers
from scans import FundamentalScans

# Fix async conflict: Allow nested event loops for Playwright within Streamlit
nest_asyncio.apply()


MONOCHROME_CSS = """
    <style>
    :root {
        --mono-bg: #f2f3f6;
        --mono-panel: #ffffff;
        --mono-panel-muted: #f7f8fa;
        --mono-border: #c5cad3;
        --mono-divider: #dfe3ea;
        --mono-text: #0f1116;
        --mono-muted: #3d4148;
        --mono-accent: #111318;
    }
    html, body, .stApp, [data-testid="stAppViewContainer"] {
        background-color: var(--mono-bg);
        color: var(--mono-text) !important;
    }
    [data-testid="stSidebar"] {
        background-color: var(--mono-panel-muted);
        border-right: 1px solid var(--mono-border);
    }
    [data-testid="stSidebar"] * {
        color: var(--mono-text) !important;
    }
    .block-container {
        padding-top: 1.5rem;
    }
    div[data-testid="stMetric"] {
        background-color: var(--mono-panel);
        border: 1px solid var(--mono-border);
        border-radius: 6px;
        padding: 0.75rem;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.03);
    }
    div[data-testid="stMetricValue"], div[data-testid="stMetricLabel"],
    div[data-testid="stMetricDelta"] {
        color: var(--mono-text) !important;
    }
    div[data-testid="stMetricDelta"] {
        opacity: 0.8;
    }
    .stButton button {
        background-color: var(--mono-panel);
        border: 1px solid var(--mono-border);
        color: var(--mono-text) !important;
        border-radius: 4px;
    }
    .stButton button:hover {
        border-color: var(--mono-accent);
        background-color: var(--mono-panel-muted);
    }
    .stTabs [data-baseweb="tab-list"] {
        border-bottom: 1px solid var(--mono-divider);
    }
    .stTabs [data-baseweb="tab"] {
        color: var(--mono-muted) !important;
    }
    .stTabs [aria-selected="true"] {
        color: var(--mono-text) !important;
        border-bottom: 2px solid var(--mono-accent);
    }
    div[data-testid="stExpander"] {
        border: 1px solid var(--mono-border);
        background-color: var(--mono-panel);
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.02);
    }
    div[data-testid="stExpander"] summary {
        color: #ffffff !important;
        background-color: #111318;
    }
    div[data-testid="stExpander"] summary * {
        color: #ffffff !important;
    }
    div[data-testid="stExpander"] div[role="button"] {
        background-color: #111318 !important;
    }
    div[data-testid="stExpander"] div[role="button"] * {
        color: #ffffff !important;
    }
    div[data-testid="stInfo"], div[data-testid="stSuccess"],
    div[data-testid="stWarning"], div[data-testid="stError"] {
        background-color: var(--mono-panel-muted);
        border: 1px solid var(--mono-border);
        color: var(--mono-text) !important;
    }
    div[data-testid="stInfo"] *,
    div[data-testid="stSuccess"] *,
    div[data-testid="stWarning"] *,
    div[data-testid="stError"] * {
        color: var(--mono-text) !important;
    }
    div[data-testid="stInfo"] > div:first-child,
    div[data-testid="stSuccess"] > div:first-child,
    div[data-testid="stWarning"] > div:first-child,
    div[data-testid="stError"] > div:first-child {
        border-left: 3px solid var(--mono-accent);
        padding-left: 0.75rem;
    }
    .stMarkdown p,
    .stMarkdown span,
    .stMarkdown li,
    .stMarkdown strong,
    label,
    .stTextInput label,
    .stSelectbox label,
    .stSelectbox option,
    input {
        color: var(--mono-text) !important;
    }
    .stMarkdown small,
    div[data-testid="stCaptionContainer"],
    div[data-testid="stCaptionContainer"] * {
        color: var(--mono-muted) !important;
    }
    hr {
        border-color: var(--mono-divider);
    }
    /* Ensure all text elements have dark color */
    h1, h2, h3, h4, h5, h6, p, span, div, label {
        color: var(--mono-text) !important;
    }
    </style>
"""


def _inject_monochrome_theme() -> None:
    """Push a monochromatic light theme into the Streamlit app."""
    st.markdown(MONOCHROME_CSS, unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def cached_tickers() -> List[str]:
    """Cache the Nifty 500 list to avoid re-fetching on every interaction."""
    try:
        return get_nifty_tickers()
    except Exception:
        return []


def main() -> None:
    st.set_page_config(
        page_title="ReScanX Fundamentals",
        page_icon="R",
        layout="wide"
    )
    _inject_monochrome_theme()

    manager = SupabaseManager()
    scraper = ScreenerScraper()

    # --- Sidebar Controls ---
    with st.sidebar:
        st.title("ReScanX")
        st.markdown("### Nifty 500 Screener")
        
        tickers = cached_tickers()
        if not tickers:
            st.error("Failed to load ticker list.")
            return

        ticker = st.selectbox(
            "Select Stock", 
            tickers, 
            index=tickers.index("RELIANCE") if "RELIANCE" in tickers else 0
        )
        
        st.markdown("---")
        force_refresh = st.button("Force Refresh Data", help="Clear cache and re-scrape Screener.in")
        
        st.markdown("### About")
        st.info(
            "This tool performs **107 Fundamental Scans** tailored to Indian stocks. "
            "It automatically detects sectors (Banks, IT, etc.) to skip irrelevant metrics like Inventory or Debt-Free checks."
        )

    if not ticker:
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
                    manager.upsert_record(payload)
                    st.success("Data updated successfully!")
                except Exception as e:
                    st.error(f"Scraping failed: {str(e)}")
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
    st.caption(f"**Sector:** {metadata.get('industry', 'Unknown')} | **Archetype:** {scanner.archetype} (Smart Filters Applied)")

    # --- Scorecard ---
    counts = {key: len(values) for key, values in results.items()}
    
    st.divider()
    score_c1, score_c2, score_c3, score_c4 = st.columns(4)
    score_c1.metric("Passed", counts.get("passed", 0))
    score_c2.metric("Failed", counts.get("failed", 0))
    score_c3.metric("Pending", counts.get("pending", 0))
    score_c4.metric("Skipped", counts.get("skipped", 0))

    # --- Detailed Results Tabs ---
    tab_pass, tab_fail, tab_pend, tab_skip, tab_raw = st.tabs([
        "Passed", 
        "Failed", 
        "Pending",
        "Skipped",
        "Raw Data"
    ])

    with tab_pass:
        _display_grouped(results.get("passed", []), "No scans passed yet.", is_success=True)

    with tab_fail:
        _display_grouped(results.get("failed", []), "No failed scans (Great!).", is_success=False)

    with tab_pend:
        st.markdown(
            "> **Note:** Scans appear here when data is **unavailable or incomplete** from the source."
        )
        _display_list(results.get("pending", []), "No pending scans.")

    with tab_skip:
        st.markdown(
            "> **Note:** Scans are **skipped** because they are **not applicable** to this industry/sector. "
            "For example, Inventory checks are skipped for Banks and IT companies."
        )
        _display_list(results.get("skipped", []), "No scans skipped for this sector.")

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