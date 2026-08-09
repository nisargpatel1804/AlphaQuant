# frontend/pages/home.py

from __future__ import annotations
import os
import requests
from requests.exceptions import RequestException

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, callback, dcc, html, register_page

# Import the upgraded visualization components
from frontend.components import (
    create_mmi_gauge,
    create_advance_decline_bar,
    create_sector_treemap
)

register_page(__name__, path="/", name="Dashboard", title="AlphaQuant Terminal")

# Setup API routing with environment variable fallback
API_BASE = os.getenv("ALPHAQUANT_API_BASE", "http://127.0.0.1:8000")
BACKEND_API_URL = f"{API_BASE}/api/v1"

# ----------------------------------------------------------------------
# DASHBOARD LAYOUT (Strictly Light Theme)
# ----------------------------------------------------------------------
layout = dbc.Container(
    [
        # Polling Interval (Refreshes data every 30 seconds automatically)
        dcc.Interval(id="dashboard-interval", interval=30000, n_intervals=0),

        # HERO ROW 1: Macro Market Gauge & Breadth
        dbc.Row([
            # MMI Gauge Card
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-speedometer2 text-primary me-2"),
                        html.Span("Market Mood Index (MMI)", className="fw-bold text-dark")
                    ], className="bg-transparent border-0 pb-0"),
                    dbc.CardBody(
                        dcc.Graph(id="mmi-gauge-graph", config={"displayModeBar": False})
                    )
                ], className="aq-metric-card h-100 shadow-sm")
            ], lg=4, md=12, className="mb-3"),

            # Market Return Snapshot & Breadth Cards
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-graph-up-arrow text-success me-2"),
                        html.Span("Nifty & Market Sentiment Metrics", className="fw-bold text-dark")
                    ], className="bg-transparent border-0 pb-0"),
                    dbc.CardBody([
                        # Market Breadth Bar will be injected here
                        html.Div(id="advance-decline-container", className="mb-3"),
                        
                        html.Hr(className="my-3"),
                        
                        # MMI & Return Stats will be injected here
                        html.Div(id="mmi-stats-container"),
                        
                        html.Hr(className="my-3"),
                        
                        # Universe KPI Stats
                        dbc.Row([
                            dbc.Col([
                                html.Div([
                                    html.Small("Tracked Sectors", className="text-muted d-block"),
                                    html.H4(id="kpi-total-sectors", children="N/A", className="fw-bold text-dark mb-0")
                                ])
                            ], width=4),
                            dbc.Col([
                                html.Div([
                                    html.Small("Tracked Industries", className="text-muted d-block"),
                                    html.H4(id="kpi-total-industries", children="N/A", className="fw-bold text-primary mb-0")
                                ])
                            ], width=4),
                            dbc.Col([
                                html.Div([
                                    html.Small("Nifty Universe Size", className="text-muted d-block"),
                                    html.H4(id="kpi-total-entities", children="N/A", className="fw-bold text-success mb-0")
                                ])
                            ], width=4),
                        ])
                    ])
                ], className="aq-metric-card h-100 shadow-sm")
            ], lg=8, md=12, className="mb-3")
        ]),

        # HERO ROW 2: Sector Treemap
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-grid-3x3-gap-fill text-warning me-2"),
                        html.Span("Sector Capital Allocation & Performance", className="fw-bold text-dark")
                    ], className="bg-transparent border-0 pb-0"),
                    dbc.CardBody(
                        dcc.Graph(id="sector-treemap-graph", config={"displayModeBar": False})
                    )
                ], className="aq-metric-card shadow-sm mb-3")
            ], width=12)
        ]),

        # HERO ROW 3: Sector Index Tracker Table
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-list-columns-reverse text-info me-2"),
                        html.Span("Major Sectoral Indices Snapshot", className="fw-bold text-dark")
                    ], className="bg-transparent border-0"),
                    dbc.CardBody(id="sectoral-indices-table-container")
                ], className="aq-metric-card shadow-sm mb-3")
            ], width=12)
        ])
    ],
    fluid=True,
    className="py-2"
)

# ----------------------------------------------------------------------
# REAL-TIME DASHBOARD CALLBACK
# ----------------------------------------------------------------------
@callback(
    Output("mmi-gauge-graph", "figure"),
    Output("mmi-stats-container", "children"),
    Output("advance-decline-container", "children"),
    Output("sector-treemap-graph", "figure"),
    Output("sectoral-indices-table-container", "children"),
    Output("kpi-total-sectors", "children"),
    Output("kpi-total-industries", "children"),
    Output("kpi-total-entities", "children"),
    Input("dashboard-interval", "n_intervals")
)
def update_dashboard_data(n):
    # ==========================================
    # 1. Fetch Tickertape MMI Data (Strictly No Dummy Values)
    # ==========================================
    mmi_data = None
    mmi_stats_card = html.Div("Data Unavailable", className="text-muted small")
    
    try:
        resp = requests.get(f"{BACKEND_API_URL}/tickertape", timeout=5)
        resp.raise_for_status() # Explicit check for 500 server errors
        raw_tt = resp.json()
        mmi_data = raw_tt.get("market_mood_index")
        
        if mmi_data:
            changes = mmi_data.get("changes_percent", {})
            nifty_ret = mmi_data.get("nifty_returns", {})
            
            # Safely get values, defaulting to 0.0 if missing to prevent NoneType crash
            yest_change = float(changes.get('yesterday') or 0.0)
            lw_change = float(changes.get('last_week') or 0.0)
            nifty_yest = float(nifty_ret.get('yesterday') or 0.0)
            
            # Format the mini-stat readouts
            mmi_stats_card = dbc.Row([
                dbc.Col([
                    html.Small("MMI Change (1D)", className="text-muted d-block"),
                    html.Span(f"{yest_change:+.2f}%", className="fw-bold text-danger" if yest_change < 0 else "fw-bold text-success")
                ], width=4),
                dbc.Col([
                    html.Small("MMI Change (1W)", className="text-muted d-block"),
                    html.Span(f"{lw_change:+.2f}%", className="fw-bold text-danger" if lw_change < 0 else "fw-bold text-success")
                ], width=4),
                dbc.Col([
                    html.Small("Nifty 1D Return", className="text-muted d-block"),
                    html.Span(f"{nifty_yest:+.2f}%", className="fw-bold text-danger" if nifty_yest < 0 else "fw-bold text-success")
                ], width=4),
            ])
    except RequestException as e:
        print(f"[Dashboard] API Error fetching tickertape data: {e}")
        mmi_stats_card = html.Div("API Unreachable", className="text-danger small fw-bold")

    mmi_gauge_fig = create_mmi_gauge(mmi_data)

    # ==========================================
    # 2. Fetch Sector Data & Calculate Breadth
    # ==========================================
    sector_analysis = None
    sectoral_indices = []
    total_sectors = "N/A"
    total_industries = "N/A"
    total_entities = "N/A"
    total_advances = 0
    total_declines = 0
    
    try:
        resp_sec = requests.get(f"{BACKEND_API_URL}/sector", timeout=5)
        resp_sec.raise_for_status() # Explicit check for 500 server errors
        raw_sec = resp_sec.json()
        sector_analysis = raw_sec.get("sector_analysis")
        
        if sector_analysis:
            sectoral_indices = sector_analysis.get("sectoral_indices", [])
            
            # Aggregate Advance/Decline strictly from available data
            sectors_list = sector_analysis.get("sectors", [])
            for sec in sectors_list:
                total_advances += sec.get("advance_count") or 0
                total_declines += sec.get("decline_count") or 0
            
        # Global KPIs
        summary = raw_sec.get("summary", {})
        total_sectors = str(summary.get("total_sectors", "N/A"))
        total_industries = str(summary.get("total_industries", "N/A"))
        
        # Safely capture total_entities
        raw_entities = summary.get("total_entities")
        total_entities = str(raw_entities) if raw_entities is not None else "N/A"
            
    except RequestException as e:
        print(f"[Dashboard] API Error fetching sector data: {e}")

    # Render Breadth without dummy totals
    math_entities = total_advances + total_declines
    if str(total_entities).isdigit() and int(total_entities) > math_entities:
        math_entities = int(total_entities)
        
    adv_dec_element = create_advance_decline_bar(
        advances=total_advances, 
        declines=total_declines, 
        total=math_entities
    )
    
    sector_treemap_fig = create_sector_treemap(sector_analysis)

    # ==========================================
    # 3. Render Sectoral Indices Table
    # ==========================================
    indices_rows = []
    if not sectoral_indices:
        indices_rows.append(html.Tr([html.Td("Data Unavailable", colSpan=3, className="text-muted text-center py-3")]))
    else:
        for idx in sectoral_indices:
            chg = idx.get("change_pct", 0.0)
            color_class = "text-success" if chg >= 0 else "text-danger"
            indices_rows.append(html.Tr([
                html.Td(idx.get("name", "Unknown"), className="text-dark fw-bold"),
                html.Td(f"₹{idx.get('price', 0):,.2f}", className="text-dark"),
                html.Td(f"{chg:+.2f}%", className=f"{color_class} fw-bold")
            ]))

    indices_table = dbc.Table([
        html.Thead(html.Tr([html.Th("Index"), html.Th("Price"), html.Th("1D Change (%)")])),
        html.Tbody(indices_rows)
    ], bordered=False, hover=True, responsive=True, className="mb-0 small bg-white text-dark")

    return (
        mmi_gauge_fig, 
        mmi_stats_card, 
        adv_dec_element, 
        sector_treemap_fig, 
        indices_table,
        total_sectors,
        total_industries,
        total_entities
    )