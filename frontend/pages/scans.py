# frontend/pages/scans.py

from __future__ import annotations
import json
import os
import requests

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html, register_page

# Import the upgraded visualization components
from frontend.components import (
    create_historical_valuation_chart,
    create_growth_metrics_chart,
    create_ev_ebitda_chart,
    create_pb_chart,
    create_margins_chart,
    create_shareholding_chart,
    render_screener_datatable
)

register_page(__name__, path_template="/scans/<symbol>", name="Scans", title="AlphaQuant Scans")

API_BASE = os.getenv("ALPHAQUANT_API_BASE", "http://127.0.0.1:8000")

# --------------------------------------------------------------------
# Main Page Layout (Strictly Light Theme)
# --------------------------------------------------------------------
def layout(symbol: str | None = None, **kwargs):
    symbol = (symbol or "RELIANCE").strip().upper()
    
    return dbc.Container(
        [
            dcc.Store(id="scan-symbol-store", data=symbol),
            dcc.Location(id="scan-redirect"),

            # Header Bar
            dbc.Row([
                dbc.Col([
                    html.H2([
                        html.Span(f"{symbol} ", className="fw-bold text-dark"),
                        html.Span("Quantitative Analysis", className="text-primary fs-4")
                    ], className="mb-0")
                ], md=8),
                dbc.Col([
                    dbc.InputGroup([
                        dbc.Input(
                            id="scan-symbol-input", 
                            value=symbol, 
                            placeholder="Enter Ticker (e.g. INFY)", 
                            className="bg-light text-dark border-secondary",
                            autoComplete="off"
                        ),
                        dbc.Button(html.I(className="bi bi-search"), id="scan-submit-btn", color="primary")
                    ])
                ], md=4)
            ], className="align-items-center mb-4 py-2 border-bottom"),

            # Main Navigation Tabs
            dbc.Tabs([
                dbc.Tab(label="Fundamentals", tab_id="tab-fundamentals", label_class_name="fw-bold"),
                dbc.Tab(label="Technicals", tab_id="tab-technicals"),
                dbc.Tab(label="Price Scans", tab_id="tab-pricescan"),
                dbc.Tab(label="Volume & Delivery", tab_id="tab-volumedelivery"),
                dbc.Tab(label="Futures & Options", tab_id="tab-fo"),
                dbc.Tab(label="Strike Options", tab_id="tab-strikeoptions"),
                dbc.Tab(label="Candlestick Scans", tab_id="tab-candlestick"),
            ], id="main-scan-tabs", active_tab="tab-fundamentals", className="mb-4 border-bottom"),

            # Content Area with Loading Spinner
            dcc.Loading(
                id="loading-scan-data",
                type="dot",
                color="#2962ff",
                children=html.Div(id="scan-tab-content-container", className="min-vh-100")
            )
        ],
        fluid=True,
        className="py-3"
    )

@callback(
    Output("scan-redirect", "pathname"),
    Input("scan-submit-btn", "n_clicks"),
    Input("scan-symbol-input", "n_submit"),
    State("scan-symbol-input", "value"),
    prevent_initial_call=True
)
def handle_symbol_search(n_clicks, n_submit, symbol):
    if symbol:
        return f"/scans/{symbol.strip().upper()}"
    return dash.no_update

@callback(
    Output("scan-tab-content-container", "children"),
    Input("main-scan-tabs", "active_tab"),
    Input("scan-symbol-store", "data")
)
def render_tab_content(active_tab, symbol):
    if not symbol:
        return html.Div("No symbol provided.", className="text-warning")

    endpoint_map = {
        "tab-fundamentals": "fundamentals",
        "tab-technicals": "technicals",
        "tab-pricescan": "pricescan",
        "tab-volumedelivery": "volumedelivery",
        "tab-fo": "fo",
        "tab-strikeoptions": "strike",
        "tab-candlestick": "candlestick"
    }
    
    scan_type = endpoint_map.get(active_tab, "fundamentals")
    
    try:
        resp = requests.get(f"{API_BASE}/api/v1/{scan_type}/{symbol}", timeout=15)
        resp.raise_for_status()
        json_data = resp.json().get("data", {})
    except Exception as e:
        return dbc.Alert(f"Failed to fetch {scan_type} data for {symbol}: {str(e)}", color="danger")

    if not json_data:
        return dbc.Alert(f"No {scan_type} data available for {symbol}.", color="warning")

    if active_tab == "tab-fundamentals":
        return build_fundamentals_layout(json_data)

    # Generic JSON output for Quantitative Scans (Light Theme)
    return dbc.Card([
        dbc.CardHeader(html.H5(f"{scan_type.capitalize()} Analysis Engine Output", className="mb-0 text-dark")),
        dbc.CardBody([
            html.Pre(
                json.dumps(json_data, indent=4), 
                className="bg-light text-success p-3 rounded border",
                style={"maxHeight": "700px", "overflowY": "auto", "fontSize": "0.85rem"}
            )
        ])
    ], className="aq-metric-card shadow-sm")

def build_fundamentals_layout(fund_data: dict) -> html.Div:
    """Constructs the high-performance Fundamentals UI."""
    core_metrics = fund_data.get("core_metrics", {})
    historical_ratios = core_metrics.get("historical_ratios", {})
    raw_financials = fund_data.get("raw_financials", {})

    latest_year = sorted(list(historical_ratios.keys()))[-1] if historical_ratios else None
    latest_metrics = historical_ratios.get(latest_year, {}) if latest_year else {}

    # Helper function to safely format metrics
    def _fmt(val, suffix="x"):
        if val is None or val == "": return "N/A"
        return f"{val}{suffix}"

    kpi_cards = dbc.Row([
        _kpi_col("Latest P/E Ratio", _fmt(latest_metrics.get('pe_ratio'), "x"), is_neutral=True),
        _kpi_col("P/B Ratio", _fmt(latest_metrics.get('pb_ratio'), "x"), is_neutral=True),
        _kpi_col("EV / EBITDA", _fmt(latest_metrics.get('ev_ebitda'), "x"), is_neutral=True),
        _kpi_col("Return on Equity (ROE)", _fmt(latest_metrics.get('roe_pct'), "%"), is_good=(latest_metrics.get('roe_pct') or 0) >= 15),
        _kpi_col("ROCE", _fmt(latest_metrics.get('roce_pct'), "%"), is_good=(latest_metrics.get('roce_pct') or 0) >= 15),
        _kpi_col("OPM Margin %", _fmt(latest_metrics.get('opm_percent'), "%"), is_good=(latest_metrics.get('opm_percent') or 0) >= 10),
    ], className="g-3 mb-4")

    val_fig = create_historical_valuation_chart(historical_ratios)
    growth_fig = create_growth_metrics_chart(historical_ratios)
    ev_fig = create_ev_ebitda_chart(historical_ratios)
    pb_fig = create_pb_chart(historical_ratios)
    margins_fig = create_margins_chart(historical_ratios)
    shp_fig = create_shareholding_chart(raw_financials.get("shareholding", {}), is_quarterly=True)

    charts_section = html.Div([
        dbc.Row([
            dbc.Col(dbc.Card(dbc.CardBody(dcc.Graph(figure=val_fig, config={"displayModeBar": False})), className="aq-metric-card mb-4"), lg=6, width=12),
            dbc.Col(dbc.Card(dbc.CardBody(dcc.Graph(figure=growth_fig, config={"displayModeBar": False})), className="aq-metric-card mb-4"), lg=6, width=12),
        ]),
        dbc.Row([
            dbc.Col(dbc.Card(dbc.CardBody(dcc.Graph(figure=ev_fig, config={"displayModeBar": False})), className="aq-metric-card mb-4"), lg=6, width=12),
            dbc.Col(dbc.Card(dbc.CardBody(dcc.Graph(figure=pb_fig, config={"displayModeBar": False})), className="aq-metric-card mb-4"), lg=6, width=12),
        ]),
        dbc.Row([
            dbc.Col(dbc.Card(dbc.CardBody(dcc.Graph(figure=margins_fig, config={"displayModeBar": False})), className="aq-metric-card mb-4"), lg=6, width=12),
            dbc.Col(dbc.Card(dbc.CardBody(dcc.Graph(figure=shp_fig, config={"displayModeBar": False})), className="aq-metric-card mb-4"), lg=6, width=12),
        ])
    ])

    tables_section = dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-file-earmark-spreadsheet text-primary me-2"),
            html.Span("Screener Financial Statements", className="fw-bold text-dark")
        ], className="bg-transparent border-0"),
        dbc.CardBody([
            dbc.Tabs([
                dbc.Tab(render_screener_datatable(raw_financials.get("profit_loss_annual", {}), "tbl-pl"), label="Profit & Loss"),
                dbc.Tab(render_screener_datatable(raw_financials.get("quarterly_results", {}), "tbl-qtr"), label="Quarterly"),
                dbc.Tab(render_screener_datatable(raw_financials.get("balance_sheet", {}), "tbl-bs"), label="Balance Sheet"),
                dbc.Tab(render_screener_datatable(raw_financials.get("cash_flow", {}), "tbl-cf"), label="Cash Flow"),
                dbc.Tab(render_screener_datatable(raw_financials.get("ratios", {}), "tbl-rat"), label="Ratios"),
            ], className="mb-3")
        ], className="p-2")
    ], className="aq-metric-card mb-5")

    return html.Div([kpi_cards, charts_section, tables_section])

def _kpi_col(title: str, value: str, is_good: bool = True, is_neutral: bool = False) -> dbc.Col:
    if is_neutral or value == "N/A":
        color_class = "text-dark"
    else:
        color_class = "text-success" if is_good else "text-danger"
        
    return dbc.Col(
        dbc.Card(
            dbc.CardBody([
                html.Small(title, className="text-muted fw-bold d-block text-uppercase", style={"fontSize": "0.7rem"}),
                html.H4(value, className=f"{color_class} fw-bold mt-2 mb-0")
            ]), 
            className="aq-metric-card h-100"
        ), 
        lg=2, md=4, sm=6, width=6
    )