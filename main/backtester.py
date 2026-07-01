import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
from dateutil.relativedelta import relativedelta
import requests
import random
import csv
import time
from pathlib import Path
import io
import plotly.graph_objects as go
from plotly.subplots import make_subplots

NIFTY_500_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# --- Page Config ---
st.set_page_config(page_title="Pro Portfolio Backtester", layout="wide", page_icon="📈")

# --- Custom CSS ---
st.markdown("""
<style>
    /* Dark Background for App */
    .stApp { background-color: #0E1117; color: white; }
    
    /* Compact container spacing */
    .block-container { padding-top: 1rem; padding-bottom: 5rem; }
    
    /* Typography - White text for Dark Mode */
    h1, h2, h3 { color: #FAFAFA; font-family: 'Segoe UI', sans-serif; }
    
    /* Metrics styling */
    div[data-testid="stMetricValue"] { font-size: 1.4rem; color: #FAFAFA; font-weight: 600; }
    div[data-testid="stMetricLabel"] { color: #A0A0A0; font-size: 0.9rem; }
    
    /* Button bar styling */
    .stRadio > div { 
        flex-direction: row; 
        gap: 8px; 
        overflow-x: auto;
        padding-bottom: 5px;
    }
    
    /* Ensure Expander and Inputs look good in Dark Mode */
    .streamlit-expanderHeader { color: #FAFAFA; background-color: #262730; }
    
    /* Checkbox styling */
    .stCheckbox label { color: #FAFAFA; }
</style>
""", unsafe_allow_html=True)

# --- Helper Functions ---

@st.cache_data(ttl=3600)
def get_nifty500_tickers():
    """
    Fetches the latest Nifty 500 constituents from NSE Archives.
    """
    url = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        session = requests.Session()
        session.headers.update(headers)
        # Visit home to get cookies
        session.get("https://www.nseindia.com", timeout=5)
        
        response = session.get(url, timeout=10)
        response.raise_for_status()
        
        df = pd.read_csv(io.StringIO(response.content.decode('utf-8')))
        
        if 'Symbol' in df.columns:
            # Filter and Format
            symbols = df['Symbol'].dropna().unique().tolist()
            tickers = [f"{sym.strip()}.NS" for sym in symbols]
            return sorted(tickers)
        return []
    except Exception:
        # Fallback to cached/local Nifty 500 list if NSE is blocking
        try:
            tickers = get_nifty_tickers()
            return sorted([f"{sym}.NS" for sym in tickers]) if tickers else []
        except Exception:
            return []


def get_nifty_tickers(retries=4):
    sess = requests.Session()
    for attempt in range(1, retries + 1):
        try:
            resp = sess.get(NIFTY_500_URL, timeout=30, headers={"User-Agent": random.choice(USER_AGENTS)})
            resp.raise_for_status()
            reader = csv.DictReader(io.StringIO(resp.content.decode("utf-8", errors="replace")))
            return [row["Symbol"].strip().upper() for row in reader if row.get("Symbol")]
        except requests.RequestException:
            if attempt == retries:
                break
            time.sleep(1.5 * attempt)

    fallback_path = Path(__file__).resolve().parent.parent / "main" / "source" / "ind_nifty500list.csv"
    if fallback_path.exists():
        with fallback_path.open("r", encoding="utf-8") as f:
            return [row["Symbol"].strip().upper() for row in csv.DictReader(f) if row.get("Symbol")]
    return []


def get_start_date(timeframe_code):
    today = datetime.date.today()
    mapping = {
        "1W": datetime.timedelta(weeks=1),
        "1M": relativedelta(months=1),
        "2M": relativedelta(months=2),
        "3M": relativedelta(months=3),
        "6M": relativedelta(months=6),
        "1Y": relativedelta(years=1),
        "2Y": relativedelta(years=2),
        "3Y": relativedelta(years=3),
        "5Y": relativedelta(years=5),
        "10Y": relativedelta(years=10),
    }
    
    if timeframe_code == "Max": 
        return datetime.date(2000, 1, 1)
        
    delta = mapping.get(timeframe_code)
    return today - delta if delta else today - relativedelta(years=1)

def calculate_auto_range(series_list, padding=0.1):
    """
    Calculates Y-axis range with explicit padding to prevent cutoff.
    Handles both positive and negative values correctly.
    """
    min_val = float('inf')
    max_val = float('-inf')
    has_data = False
    
    for s in series_list:
        if s is not None and not s.empty:
            min_val = min(min_val, s.min())
            max_val = max(max_val, s.max())
            has_data = True
            
    if not has_data:
        return [0, 1]
        
    # Range span
    span = max_val - min_val
    if span == 0: span = abs(max_val) * 0.1 if max_val != 0 else 1.0
        
    # Apply padding
    y_min = min_val - (span * padding)
    y_max = max_val + (span * padding)
    
    return [y_min, y_max]

def create_stock_chart(ticker, df_full, visible_start_date):
    # Indicators
    df_full['50DMA'] = df_full['Close'].rolling(window=50).mean()
    df_full['200DMA'] = df_full['Close'].rolling(window=200).mean()
    
    # Slice
    df = df_full[df_full.index >= pd.Timestamp(visible_start_date)].copy()
    if df.empty: return go.Figure()

    start_price = df['Close'].iloc[0]
    end_price = df['Close'].iloc[-1]
    trend_color = '#00C853' if end_price >= start_price else '#D50000' 

    # --- Robust Scaling ---
    y_range = calculate_auto_range([df['Close'], df['50DMA'], df['200DMA']], padding=0.08)

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, 
        row_heights=[0.75, 0.25], specs=[[{"secondary_y": False}], [{"secondary_y": False}]]
    )

    # Price
    fig.add_trace(go.Scatter(
        x=df.index, y=df['Close'], name="Price", mode='lines',
        line=dict(color=trend_color, width=2),
        hovertemplate='<b>Price</b>: ₹%{y:,.2f}'
    ), row=1, col=1)

    # DMAs
    fig.add_trace(go.Scatter(
        x=df.index, y=df['50DMA'], name="50 DMA", mode='lines',
        line=dict(color='#FF9800', width=1.5), hovertemplate='50DMA: ₹%{y:,.2f}'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df.index, y=df['200DMA'], name="200 DMA", mode='lines',
        line=dict(color='#424242', width=1.5), hovertemplate='200DMA: ₹%{y:,.2f}'
    ), row=1, col=1)

    # Volume
    fig.add_trace(go.Bar(
        x=df.index, y=df['Volume'], name="Volume", 
        marker_color='rgba(100, 100, 255, 0.3)', marker_line_width=0,
        hovertemplate='Vol: %{y:.2s}'
    ), row=2, col=1)

    # Volume Scaling
    if not df['Volume'].empty:
        vol_95 = df['Volume'].quantile(0.95)
        vol_max_limit = vol_95 * 1.5 if vol_95 > 0 else df['Volume'].max()
    else:
        vol_max_limit = 100

    fig.update_layout(
        title=dict(text=f"<b>{ticker}</b>", font=dict(size=20, color='black')),
        height=500, margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", y=1.02, xanchor="right", x=1, font=dict(color="black")),
        paper_bgcolor='white', plot_bgcolor='white',
        hovermode="x unified", hoverdistance=100,
    )
    
    fig.update_xaxes(
        showgrid=False, linecolor='#e0e0e0', rangebreaks=[dict(bounds=["sat", "mon"])], 
        showspikes=True, spikethickness=1, spikecolor="#888888", spikemode="across", tickfont=dict(color='#666')
    )
    # Apply calculated range to Y-axis
    fig.update_yaxes(
        showgrid=True, gridcolor='#f5f5f5', zeroline=False, 
        tickfont=dict(color='#666'), showspikes=False, 
        range=y_range, # FIX: Explicit range prevents cutoff
        row=1, col=1
    )
    fig.update_yaxes(showgrid=False, showticklabels=False, range=[0, vol_max_limit], row=2, col=1)
    fig.update_xaxes(rangeslider_visible=False)
    
    return fig

# --- Main App Logic ---

st.title("📊 Smart Portfolio Backtester")

# 1. Data Fetch
with st.spinner("Initializing Ticker List..."):
    tickers = get_nifty500_tickers()

# 2. Controls
with st.container():
    col_sel, col_amt = st.columns([3, 1])
    with col_sel:
        with st.expander("🔎 Select Stocks (Click to Expand)", expanded=True):
            selected_tickers = st.multiselect("Search Nifty 500:", options=tickers, default=[])
    with col_amt:
        initial_capital = st.number_input("Capital (₹)", value=1000000, step=50000)

# 3. Timeframe
timeframes = ["1W", "1M", "2M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "10Y", "Max"]
selected_tf = st.radio("Select Period:", timeframes, index=6, horizontal=True)

st.markdown("---")

if not selected_tickers:
    st.info("Select stocks above to begin analysis.")
    st.stop()

# --- Backtest Execution ---

visible_start_date = get_start_date(selected_tf)
buffer_start_date = visible_start_date - datetime.timedelta(days=365)
end_date = datetime.date.today()

with st.spinner(f"Downloading data for {len(selected_tickers)} stocks..."):
    try:
        user_data = yf.download(selected_tickers, start=buffer_start_date, end=end_date, group_by='ticker', auto_adjust=True, progress=False)
    except Exception as e:
        st.error(f"Data Error: {e}")
        st.stop()

if user_data.empty:
    st.error("No data returned. Try different stocks.")
    st.stop()

# --- Calculations ---

user_closes = pd.DataFrame()

# Extract Closings
for ticker in selected_tickers:
    try:
        if isinstance(user_data.columns, pd.MultiIndex):
            if ticker in user_data.columns.get_level_values(0):
                df = user_data[ticker].copy()
            else:
                continue
        else:
            df = user_data.copy()
        
        if 'Close' not in df.columns:
            continue
            
        df_vis = df[df.index >= pd.Timestamp(visible_start_date)].dropna()
        if not df_vis.empty:
            user_closes[ticker] = df_vis['Close']
    except Exception:
        continue

if user_closes.empty:
    st.warning("Insufficient data available for the selected stocks in this timeframe.")
    st.stop()

# Drop empty columns
user_closes = user_closes.dropna(axis=1, how='all')

# 1. Normalization (Handle IPOs correctly)
# Use bfill to find first valid price, then divide. fillna(1.0) keeps pre-IPO flat.
ipo_fill_prices = user_closes.bfill().iloc[0]
user_norm = (user_closes / ipo_fill_prices).fillna(1.0)

# 2. Portfolio Value
weights = initial_capital / len(user_closes.columns)
user_pos_val = user_norm * weights
portfolio_total = user_pos_val.sum(axis=1)

# 3. Portfolio % Return
portfolio_pct = ((portfolio_total / initial_capital) - 1) * 100

# --- Metrics ---
curr_val = portfolio_total.iloc[-1]
ret_abs = curr_val - initial_capital
ret_pct = (ret_abs / initial_capital) * 100

m1, m2, m3 = st.columns(3)
m1.metric("Initial Capital", f"₹{initial_capital:,.0f}")
m2.metric("Current Value", f"₹{curr_val:,.0f}")
m3.metric("Net Return", f"{ret_pct:.2f}%", f"₹{ret_abs:,.0f}")

# --- Chart 1: Total Portfolio Return ---

st.subheader("🚀 Total Portfolio Return (%)")

port_color = '#00C853' if curr_val >= initial_capital else '#D50000'

# Calculate range with buffer
y_range_port = calculate_auto_range([portfolio_pct], padding=0.1)

fig_port = go.Figure()

fig_port.add_trace(go.Scatter(
    x=portfolio_pct.index, y=portfolio_pct,
    mode='lines', name='My Portfolio',
    line=dict(color=port_color, width=3),
    fill='tozeroy', 
    fillcolor=f"rgba{tuple(int(port_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4)) + (0.1,)}",
    hovertemplate='<b>Return</b>: %{y:.2f}%'
))

fig_port.add_hline(
    y=0, line_dash="dash", line_color="#333", line_width=1,
    annotation_text="Breakeven", annotation_position="top left",
    annotation_font=dict(color='#555', size=10)
)

fig_port.update_layout(
    height=500, margin=dict(l=10,r=10,t=30,b=10), hovermode="x unified",
    paper_bgcolor='white', plot_bgcolor='white', font=dict(color='black'),
    legend=dict(orientation="h", y=1.05, xanchor="left", x=0),
    yaxis_title="Return (%)"
)
fig_port.update_xaxes(
    showgrid=False, rangebreaks=[dict(bounds=["sat", "mon"])], 
    showspikes=True, spikethickness=1, spikecolor="#888888", spikemode="across",
    tickfont=dict(color='#666')
)
st.plotly_chart(fig_port, width='stretch', config={'displayModeBar': False})

# --- Chart 2: Relative Comparison ---

st.subheader("📈 Relative Performance Comparison (%)")
fig_compare = go.Figure()

# Convert individual stocks to % return
pct_series_list = []
for col in user_norm.columns:
    pct_series = (user_norm[col] - 1) * 100
    pct_series_list.append(pct_series)
    
    fig_compare.add_trace(go.Scatter(
        x=pct_series.index, y=pct_series,
        mode='lines', name=col, opacity=0.8, 
        line=dict(width=1.5),
        hovertemplate=f'{col}: %{{y:.2f}}%'
    ))

# Calculate Range with buffer for all stocks
y_range_rel = calculate_auto_range(pct_series_list, padding=0.1)

fig_compare.update_layout(
    height=500, margin=dict(l=10,r=10,t=30,b=10), hovermode="x unified",
    yaxis_title="Return (%)", paper_bgcolor='white', plot_bgcolor='white',
    legend=dict(orientation="h", y=1.05, xanchor="left", x=0, font=dict(color='black')),
    font=dict(color='#333')
)
fig_compare.update_xaxes(
    showgrid=False, rangebreaks=[dict(bounds=["sat", "mon"])], 
    showspikes=True, spikethickness=1, spikecolor="#888888", spikemode="across",
    tickfont=dict(color='#666')
)
fig_compare.update_yaxes(
    showgrid=True, gridcolor='#f5f5f5', tickfont=dict(color='#666'),
    range=y_range_rel # Explicit buffer
)

st.plotly_chart(fig_compare, width='stretch', config={'displayModeBar': False})

# --- Download Button ---
csv = portfolio_pct.to_csv().encode('utf-8')
st.download_button(
    label="📥 Download Portfolio Returns CSV",
    data=csv,
    file_name='portfolio_returns.csv',
    mime='text/csv',
)

# --- Individual Analysis ---

st.markdown("### 📊 Deep Dive: Individual Stocks")
st.markdown("---")

for ticker in selected_tickers:
    try:
        if isinstance(user_data.columns, pd.MultiIndex):
             if ticker in user_data.columns.get_level_values(0):
                 df_full = user_data[ticker].copy()
             else:
                 continue
        else:
             df_full = user_data.copy()
        
        df_full = df_full.dropna()
        if df_full.empty: continue

        with st.container():
            fig = create_stock_chart(ticker, df_full, visible_start_date)
            st.plotly_chart(fig, width='stretch', config={'displayModeBar': False})
            st.markdown("---")
        
    except Exception:
        continue