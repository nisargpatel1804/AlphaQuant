# frontend/app.py

from __future__ import annotations
import json
import sys
from pathlib import Path

import dash
import dash_bootstrap_components as dbc
from dash import Dash, dcc, html, Input, Output, State, callback

# --- FIX FOR ModuleNotFoundError ---
APP_DIR = Path(__file__).resolve().parent
# Add the AlphaQuant root directory to Python's path
sys.path.insert(0, str(APP_DIR.parent)) 
# -----------------------------------

BACKEND_SOURCE_DIR = APP_DIR.parent / "backend" / "source"

# Load symbols for native HTML5 autocomplete dropdown
def load_symbols() -> list[str]:
    symbols = set()
    try:
        # Load from consolidated list
        consolidated_path = BACKEND_SOURCE_DIR / "consolidated.json"
        if consolidated_path.exists():
            with open(consolidated_path, "r", encoding="utf-8") as f:
                symbols.update(json.load(f))
        
        # Load from non-consolidated list
        nonconsolidated_path = BACKEND_SOURCE_DIR / "nonconsolidated.json"
        if nonconsolidated_path.exists():
            with open(nonconsolidated_path, "r", encoding="utf-8") as f:
                symbols.update(json.load(f))
    except Exception as e:
        print(f"Warning: Could not load symbol lists for autocomplete: {e}")
    
    return sorted(list(symbols))

ALL_SYMBOLS = load_symbols()

app = Dash(
    __name__,
    use_pages=True,
    pages_folder=str(APP_DIR / "pages"),
    assets_folder=str(APP_DIR / "assets"),
    external_stylesheets=[dbc.themes.FLATLY, dbc.icons.BOOTSTRAP], # Enforce Light Theme
    suppress_callback_exceptions=True,
)

server = app.server

# 1. Institutional Navigation Bar (Light Theme)
navbar = dbc.Navbar(
    dbc.Container(
        [
            dbc.NavbarBrand(
                [
                    html.I(className="bi bi-cpu-fill text-primary me-2"),
                    html.Span("ALPHA", className="fw-bold text-dark"),
                    html.Span("QUANT", className="fw-bold text-primary"),
                ],
                href="/",
                className="d-flex align-items-center"
            ),
            
            # Live Market Status Badge
            html.Div(
                [
                    html.Span(className="pulse-green me-2"),
                    html.Span("NSE/BSE LIVE", className="small fw-bold text-success me-3 d-none d-md-inline")
                ],
                className="d-flex align-items-center"
            ),

            dbc.Nav(
                [
                    dbc.NavItem(dbc.NavLink([html.I(className="bi bi-speedometer2 me-1"), "Dashboard"], href="/", active="exact")),
                    dbc.NavItem(dbc.NavLink([html.I(className="bi bi-search me-1"), "Scans"], href="/scans/RELIANCE", active="exact")),
                    dbc.NavItem(dbc.NavLink([html.I(className="bi bi-graph-up-arrow me-1"), "Backtester"], href="/backtester", active="exact")),
                    dbc.NavItem(dbc.NavLink([html.I(className="bi bi-calendar3 me-1"), "Seasonality"], href="/seasonality", active="exact")),
                    dbc.NavItem(dbc.NavLink([html.I(className="bi bi-pie-chart me-1"), "Sectors"], href="/sector", active="exact")),
                    dbc.NavItem(dbc.NavLink([html.I(className="bi bi-activity me-1"), "Tickertape"], href="/tickertape", active="exact")),
                ],
                navbar=True,
                className="ms-auto",
                pills=True
            ),
            
            # Quick Jump Search Input with Autocomplete
            dbc.InputGroup(
                [
                    dbc.Input(
                        id="nav-search-input", 
                        placeholder="Search Symbol (e.g. INFY)...", 
                        type="text", 
                        size="sm", 
                        list="symbols-list", # Links to the HTML5 datalist
                        className="bg-light text-dark border-secondary",
                        autoComplete="off"
                    ),
                    dbc.Button(html.I(className="bi bi-search"), id="nav-search-btn", color="primary", size="sm")
                ],
                className="ms-3 d-none d-lg-flex",
                style={"maxWidth": "220px"}
            )
        ],
        fluid=True
    ),
    color="white",
    dark=False,
    sticky="top",
    className="aq-navbar border-bottom py-2"
)

# 2. SEBI Compliant Footer (Light Theme)
footer = html.Footer(
    dbc.Container(
        dbc.Row([
            dbc.Col([
                html.H6("AlphaQuant Analytics Engine", className="text-dark font-weight-bold mb-2"),
                html.P(
                    "AlphaQuant is an automated quantitative market scanner and algorithmic research platform for Indian Equities (NSE/BSE). Data is updated via multi-source API integrations.",
                    className="small text-muted mb-0"
                )
            ], lg=6, className="mb-3 mb-lg-0"),
            dbc.Col([
                html.H6("System Status", className="text-dark font-weight-bold mb-2"),
                html.Div([
                    html.Span("Database Status: ", className="small text-muted"),
                    html.Span("Connected (REST)", className="small text-success fw-bold me-3"),
                    html.Span("Last Engine Refresh: ", className="small text-muted"),
                    html.Span("Live", className="small text-dark fw-bold")
                ])
            ], lg=3, className="mb-3 mb-lg-0"),
            dbc.Col([
                html.H6("Regulatory Disclaimer", className="text-dark font-weight-bold mb-2"),
                html.P(
                    "Disclaimer: Not a SEBI registered investment advisor. Information provided is strictly for educational and quantitative research purposes.",
                    className="style-micro text-muted mb-0"
                )
            ], lg=3),
        ]),
        fluid=True,
        className="py-4 px-4"
    ),
    className="bg-light border-top mt-5"
)

app.layout = html.Div(
    [
        dcc.Location(id="url"),
        # HTML5 Datalist for autocomplete suggestions
        html.Datalist(
            id="symbols-list",
            children=[html.Option(value=sym) for sym in ALL_SYMBOLS]
        ),
        navbar,
        dbc.Container(dash.page_container, fluid=True, className="page-shell py-4 px-4"),
        footer
    ],
    className="app-root bg-light text-dark",
    style={"minHeight": "100vh"}
)

@callback(
    Output("url", "pathname"),
    Input("nav-search-btn", "n_clicks"),
    Input("nav-search-input", "n_submit"),
    State("nav-search-input", "value"),
    prevent_initial_call=True
)
def handle_nav_search(n_clicks, n_submit, symbol):
    if symbol:
        return f"/scans/{symbol.strip().upper()}"
    return dash.no_update

if __name__ == "__main__":
    # dev_tools_ui=False disables the Dash debug toolbar in the bottom right corner
    app.run(debug=True, port=8050, dev_tools_ui=False, dev_tools_props_check=False)