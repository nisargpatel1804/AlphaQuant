"""AlphaQuant Master Dashboard.

Integrates Fundamentals, Technicals, Price Scans, Volume & Delivery, Futures & Options,
Strike Options, and Candlestick Scans into a unified interface.
"""
from __future__ import annotations

import sys
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st
import pandas as pd

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
HAS_VOLUMEDELIVERY = False
HAS_FUTUREOPTIONS = False
HAS_STRIKEOPTIONS = False
HAS_CANDLESTICK = False

# Fundamentals
try:
    from scans.fundamentals.fetcher import ScreenerScraper
    from scans.fundamentals.utils import get_nifty_tickers, load_master_industry_map, build_ticker_to_industry_and_pe, apply_industry_context
    from scans.fundamentals.scans import FundamentalScans
    HAS_FUNDAMENTALS = True
except ImportError as e:
    logger.warning(f"Fundamentals module not loaded: {e}")

# Technicals
try:
    from scans.technicals.fetcher import TechnicalFetcher
    from scans.technicals.indicators import TechnicalIndicators
    from scans.technicals.scans import TechnicalScans
    HAS_TECHNICALS = True
except ImportError as e:
    logger.warning(f"Technicals module not loaded: {e}")

# Price Scans
try:
    from scans.pricescan.main import PriceScanEngine
    from scans.pricescan.models import TickerPriceScanData
    HAS_PRICESCANS = True
except ImportError as e:
    logger.warning(f"Price Scan module not loaded: {e}")

# Volume & Delivery
try:
    from scans.volumedelivery.main import VolumeDeliveryEngine
    HAS_VOLUMEDELIVERY = True
except ImportError as e:
    logger.warning(f"Volume & Delivery module not loaded: {e}")

# Futures & Options
try:
    from scans.futureoptions.main import FOEngine
    HAS_FUTUREOPTIONS = True
except ImportError as e:
    logger.warning(f"Futures & Options module not loaded: {e}")

# Strike Options
try:
    from scans.strikeoptions.main import StrikeOptionsEngine
    HAS_STRIKEOPTIONS = True
except ImportError as e:
    logger.warning(f"Strike Options module not loaded: {e}")

# Candlestick Scans
try:
    from scans.candlestick.main import CandleEngine
    HAS_CANDLESTICK = True
except ImportError as e:
    logger.warning(f"Candlestick module not loaded: {e}")


# 4. Page Configuration
st.set_page_config(
    page_title="AlphaQuant Analytics",
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
    return TechnicalFetcher() if HAS_TECHNICALS else None

@st.cache_resource(show_spinner="Initializing Sector Engine...")
def get_pricescan_engine():
    return PriceScanEngine(update_sectors=False) if HAS_PRICESCANS else None

@st.cache_resource(show_spinner=False)
def get_volume_engine():
    return VolumeDeliveryEngine() if HAS_VOLUMEDELIVERY else None

@st.cache_resource(show_spinner=False)
def get_fo_engine():
    return FOEngine() if HAS_FUTUREOPTIONS else None

@st.cache_resource(show_spinner=False)
def get_strike_engine():
    return StrikeOptionsEngine() if HAS_STRIKEOPTIONS else None

@st.cache_resource(show_spinner=False)
def get_candle_engine():
    return CandleEngine() if HAS_CANDLESTICK else None

# --------------------------------------------------------------------------
# Main UI Logic
# --------------------------------------------------------------------------

def main():
    # --- Sidebar ---
    with st.sidebar:
        st.title("AlphaQuant")
        st.caption("v3.0 | Complete Suite")
        
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
        if HAS_VOLUMEDELIVERY: available_modules.append("Volume & Delivery")
        if HAS_FUTUREOPTIONS: available_modules.append("Futures & Options")
        if HAS_STRIKEOPTIONS: available_modules.append("Strike Options")
        if HAS_CANDLESTICK: available_modules.append("Candlestick Scans")
        
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
        
    elif scan_type == "Volume & Delivery":
        engine = get_volume_engine()
        render_volume_delivery(selected_ticker, engine, force_refresh)
        
    elif scan_type == "Futures & Options":
        engine = get_fo_engine()
        render_fo(selected_ticker, engine, force_refresh)
        
    elif scan_type == "Strike Options":
        engine = get_strike_engine()
        render_strike(selected_ticker, engine, force_refresh)
        
    elif scan_type == "Candlestick Scans":
        engine = get_candle_engine()
        render_candle(selected_ticker, engine, force_refresh)

# --------------------------------------------------------------------------
# Renderers
# --------------------------------------------------------------------------

def render_fundamentals(ticker: str, scraper: Any, t_map: Dict, p_map: Dict, force: bool):
    st.title(f"Fundamentals: {ticker}")
    
    if not scraper:
        st.error("Fundamentals engine not initialized.")
        return

    cache_key = f"fund_{ticker}"
    if force or cache_key not in st.session_state:
        with st.spinner(f"Scraping Fundamentals for {ticker}..."):
            try:
                payload = scraper.fetch_company_payload(ticker)
                payload["ticker"] = ticker
                apply_industry_context(payload, ticker=ticker, ticker_to_industry=t_map, industry_to_pe=p_map)
                
                scanner = FundamentalScans(payload)
                # Now returns categories dict
                results = scanner.run_scans()
                
                st.session_state[cache_key] = {
                    "data": payload,
                    "categories": results,
                    "meta": scanner.metadata
                }
            except Exception as e:
                st.error(f"Analysis failed: {e}")
                return

    data = st.session_state[cache_key]
    meta = data["meta"]
    categories = data["categories"]

    # Metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Price", f"₹{meta.get('current_price', 0):,.2f}")
    c2.metric("Market Cap", f"₹{meta.get('market_cap', 0):,.0f} Cr")
    c3.metric("Stock P/E", f"{meta.get('stock_pe', 0):.1f}")
    c4.metric("Industry P/E", f"{meta.get('industry_pe', 0):.1f}")
    st.caption(f"Sector: **{meta.get('industry', 'N/A')}**")

    st.divider()

    # --- FUNDAMENTALS SUMMARY GRID ---
    layout_order = [
        "Profitability", "Turnover", "Solvency", "Cash Flow",
        "Valuation", "Dividends", "Efficiency", "Shareholding"
    ]
    _render_card_grid(categories, layout_order, mode="fund")
                            
    with st.expander("Raw Data JSON"):
        st.json(data["data"])


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
                
                ind_name = None
                if hasattr(fetcher, 'fetch_industry_beta_avg'):
                    ind_name, ind_beta = fetcher.fetch_industry_beta_avg(ticker, bench)
                    d_df["INDUSTRY_BETA_AVG"] = ind_beta

                TechnicalIndicators.add_all_indicators(d_df, is_weekly=False, benchmark_data=bench)
                TechnicalIndicators.add_all_indicators(w_df, is_weekly=True)
                
                scanner = TechnicalScans(d_df, w_df)
                results = scanner.run_all()
                
                st.session_state[cache_key] = {
                    "categories": results,
                    "last_close": d_df['Close'].iloc[-1],
                    "industry": ind_name
                }
            except Exception as e:
                st.error(f"Technical analysis failed: {e}")
                return

    data = st.session_state[cache_key]
    categories = data["categories"] 
    
    st.metric("Last Close", f"₹{data['last_close']:,.2f}")
    if data['industry']: st.caption(f"Sector: **{data['industry']}**")
    
    st.divider()

    # --- TECHNICAL SUMMARY GRID ---
    layout_order = [
        "Simple Moving Averages", "Exponential Moving Averages", "Hull Moving Average", "Volume Weighted MA",
        "RSI", "CCI", "Momentum", "MACD", "ADX", "SuperTrend", "Parabolic SAR",
        "Stochastic", "Williams %R", "MFI", "Awesome Oscillator", "Bull/Bear Power", "Ultimate Oscillator", "Stoch RSI",
        "Bollinger Bands", "Ichimoku", "Beta",
        "Pivots - Classic", "Pivots - Fibonacci", "Pivots - Camarilla", "Pivots - Woodie", "Pivots - DeMark"
    ]
    _render_card_grid(categories, layout_order, mode="tech")


def render_price_scans(ticker: str, engine: Any, force: bool):
    st.title(f"Price Scans: {ticker}")
    if not engine: return

    cache_key = f"price_{ticker}"
    if force or cache_key not in st.session_state:
        with st.spinner(f"Running Price Scans for {ticker}..."):
            try:
                res = engine.process_ticker(ticker)
                if res: st.session_state[cache_key] = res
            except Exception as e:
                st.error(f"Price scan failed: {e}")
                return

    data = st.session_state[cache_key]
    categories = data.categories
    summary = getattr(data, "scan_summary", {}) or {}
    
    st.metric("Last Close", f"₹{data.last_close:,.2f}")
    st.caption(f"Sector: **{data.industry}**")
    st.divider()
    
    triggered_total = summary.get("triggered_total", 0)
    st.caption(f"Total Scans Triggered: **{triggered_total}**")

    # --- PRICE SCANS SUMMARY GRID ---
    layout_order = [
        "Previous Day Breakout", "Weekly Breakout", "Monthly Breakout",
        "52 Week Breakout", "52 Week Range", "All Time Breakout",
        "Relative Performance", "Relative Strength (21 Days)", "Relative Strength (55 Days)",
        "Relative Strength (21 Weeks)", "Adaptive & Static RS", "Absolute Return",
        "VWAP Scans", "1 Day Behaviour", "2 Days Behaviour", "3 Days Behaviour"
    ]
    _render_card_grid(categories, layout_order, mode="price")


def render_volume_delivery(ticker: str, engine: Any, force: bool):
    st.title(f"Volume & Delivery: {ticker}")
    if not engine: return
    
    cache_key = f"vd_{ticker}"
    if force or cache_key not in st.session_state:
        with st.spinner("Analyzing Volume/Delivery..."):
            try:
                res = engine.process_ticker(ticker)
                if res: st.session_state[cache_key] = res
            except Exception as e: st.error(f"Error: {e}")
            
    if cache_key in st.session_state:
        data = st.session_state[cache_key]
        st.metric("Last Volume", f"{int(data.last_volume):,}")
        st.divider()
        
        layout_order = ["Daily Volume & Delivery", "Weekly Volume & Delivery", "Monthly Volume & Delivery"]
        _render_card_grid(data.categories, layout_order, mode="vd")


def render_fo(ticker: str, engine: Any, force: bool):
    st.title(f"Futures & Options: {ticker}")
    if not engine: return
    
    cache_key = f"fo_{ticker}"
    if force or cache_key not in st.session_state:
        with st.spinner("Analyzing F&O..."):
            try:
                res = engine.process_ticker(ticker)
                if res: st.session_state[cache_key] = res
            except Exception as e: st.error(f"Error: {e}")
    
    if cache_key in st.session_state:
        data = st.session_state[cache_key]
        oi_val = f"{int(data.last_oi):,}" if data.last_oi else "N/A"
        st.metric("Open Interest", oi_val)
        st.divider()
        
        layout_order = ["Futures Open Interest", "Futures Long Position", "Futures Short Position", "Put Call Ratio"]
        _render_card_grid(data.categories, layout_order, mode="fo")


def render_strike(ticker: str, engine: Any, force: bool):
    st.title(f"Strike Options: {ticker}")
    if not engine: return
    
    cache_key = f"strike_{ticker}"
    if force or cache_key not in st.session_state:
        with st.spinner("Fetching Option Chain..."):
            try:
                res = engine.process_ticker(ticker)
                if res: st.session_state[cache_key] = res
            except Exception as e: st.error(f"Error: {e}")
            
    if cache_key in st.session_state:
        data = st.session_state[cache_key]
        st.metric("Expiry", data.expiry_date)
        st.divider()
        
        layout_order = ["Call Options OI", "Put Options OI", "Options Activity"]
        _render_card_grid(data.categories, layout_order, mode="strike")


def render_candle(ticker: str, engine: Any, force: bool):
    st.title(f"Candlestick Patterns: {ticker}")
    if not engine: return
    
    cache_key = f"candle_{ticker}"
    if force or cache_key not in st.session_state:
        with st.spinner("Identifying Patterns..."):
            try:
                res = engine.process_ticker(ticker)
                if res: st.session_state[cache_key] = res
            except Exception as e: st.error(f"Error: {e}")
            
    if cache_key in st.session_state:
        data = st.session_state[cache_key]
        st.metric("Last Close", f"₹{data.last_close:,.2f}")
        st.divider()
        
        layout_order = [
            "Bullish Scans", "Bullish Continuation Scans", "Bullish Reversal Scans",
            "Bearish Scans", "Bearish Continuation Scans", "Bearish Reversal Scans",
            "Neutral Scans"
        ]
        _render_card_grid(data.categories, layout_order, mode="candle")


# --------------------------------------------------------------------------
# UI Helpers
# --------------------------------------------------------------------------

def _render_card_grid(categories: Dict[str, Any], layout_order: List[str], mode: str = "tech"):
    """
    Renders a unified grid of cards for any module.
    """
    cols = st.columns(3)
    
    for idx, cat_name in enumerate(layout_order):
        if cat_name not in categories: continue
        
        cat_data = categories[cat_name]
        signal = cat_data.get("signal", "Neutral")
        scans = cat_data.get("scans", [])
        
        # Skip empty/neutral cards for sparse modules (Price, Candle, etc.)
        if mode in ["price", "candle", "fo", "vd"] and not scans and signal == "Neutral":
             continue

        sig_color = _get_signal_color(signal)

        with cols[idx % 3]:
            with st.container(border=True):
                st.markdown(f"**{cat_name}**")
                st.markdown(f":{sig_color}[**{signal}**]")
                
                with st.expander("Details", expanded=False):
                    if not scans:
                        st.caption("No details available.")
                    else:
                        for s in scans:
                            val = s.get("value")
                            action = s.get("action", "Neutral")
                            label = s.get("label", "Unknown")
                            status = s.get("status", "")
                            
                            icon = "⚪"
                            if "buy" in action.lower() or "high" in action.lower() and mode=="fund": icon = "🟢"
                            elif "sell" in action.lower() or "low" in action.lower() and mode=="fund": icon = "🔴"
                            elif "neutral" in action.lower(): icon = "🔵"
                            
                            val_disp = f"{val:,.2f}" if isinstance(val, (int, float)) else "-"
                            st.caption(f"{icon} {label}")
                            
                            # Display status/action depending on mode
                            display_text = action if mode == "tech" else status
                            st.markdown(f"<small>{display_text} ({val_disp})</small>", unsafe_allow_html=True)

def _get_signal_color(signal: str) -> str:
    s = signal.lower()
    if "strong buy" in s: return "green"
    if "buy" in s: return "#2e7d32"
    if "strong sell" in s: return "red"
    if "sell" in s: return "#c62828"
    return "blue"

if __name__ == "__main__":
    main()