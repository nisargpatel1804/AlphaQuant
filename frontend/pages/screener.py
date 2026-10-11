# frontend/pages/screener.py

from __future__ import annotations

import os
import re
import requests
import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html, dash_table, register_page, ctx

register_page(__name__, path="/query", name="Search Query", title="AlphaQuant Screener")

API_BASE = os.getenv("ALPHAQUANT_API_BASE", "http://127.0.0.1:8000")
BACKEND_API_URL = f"{API_BASE}/api/v1"

# Fetch available metrics on startup
try:
    resp = requests.get(f"{BACKEND_API_URL}/screener/metrics", timeout=5)
    AVAILABLE_METRICS = resp.json().get("metrics", []) if resp.status_code == 200 else []
except Exception:
    AVAILABLE_METRICS = []

# ----------------------------------------------------------------------
# LAYOUT (Mirroring the Screener.in UI exactly)
# ----------------------------------------------------------------------
layout = dbc.Container([
    
    html.H4("Create a Search Query", className="fw-bold text-dark mt-3 mb-4"),

    dbc.Row([
        # LEFT COLUMN: Query Input & Autocomplete
        dbc.Col([
            html.Div("Query", className="mb-2 text-dark", style={"fontSize": "15px"}),
            html.Div([
                dcc.Textarea(
                    id="screener-query-input",
                    style={
                        "width": "100%",
                        "height": "220px",
                        "fontFamily": "Inter, sans-serif",
                        "fontSize": "15px",
                        "lineHeight": "1.6",
                        "padding": "12px",
                        "borderRadius": "6px",
                        "border": "1px solid #8b5cf6", # Purple outline like Screener
                        "boxShadow": "0 0 0 1px rgba(139, 92, 246, 0.2)",
                        "resize": "vertical",
                        "outline": "none"
                    },
                    value=""
                ),
                # Autocomplete dropdown container (positioned immediately below)
                html.Div(id="autocomplete-container", style={"position": "relative", "width": "100%"})
            ], style={"position": "relative"}),

            dbc.Button(
                [html.I(className="bi bi-play-fill me-1"), "RUN THIS QUERY"], 
                id="run-screen-btn", 
                color="primary", 
                className="mt-4 fw-bold px-4 py-2",
                style={"backgroundColor": "#6366f1", "borderColor": "#6366f1", "borderRadius": "4px"}
            )
        ], md=7, lg=8),

        # RIGHT COLUMN: Custom Query Example
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H6("Custom query example", className="mb-3 text-dark"),
                    html.P("Market Capitalization > 500 AND\nPrice to Earning < 15 AND\nReturn on capital employed > 22%", 
                           style={"whiteSpace": "pre-wrap", "color": "#4b5563", "fontSize": "14px", "lineHeight": "1.7"}),
                    html.A("Detailed guide on creating screens", href="#", className="text-primary small text-decoration-none mt-2 d-inline-block", style={"color": "#6366f1"})
                ], className="p-4")
            ], className="border rounded bg-white shadow-sm", style={"borderColor": "#e5e7eb"})
        ], md=5, lg=4)
    ], className="mb-5"),

    # ERROR / RESULTS SECTION
    html.Div(id="query-error-message", className="text-danger mb-3 fw-bold"),
    
    html.Div([
        html.H5(id="result-count-title", className="fw-bold mb-3 d-none"),
        dcc.Loading(
            id="loading-screener-results",
            type="circle",
            color="#6366f1",
            children=html.Div(id="screener-results-container")
        )
    ])

], fluid=True, className="py-2 px-4", style={"maxWidth": "1200px"})

# ----------------------------------------------------------------------
# CALLBACKS
# ----------------------------------------------------------------------

# 1. LIVE INLINE AUTOCOMPLETE
@callback(
    Output("autocomplete-container", "children"),
    Input("screener-query-input", "value")
)
def show_suggestions(text):
    if not text:
        return dash.no_update
    
    # Split the text by common operators and newlines to find the current phrase being typed
    tokens = re.split(r'(\n| > | < | >= | <= | = | AND | OR | NOT )', text)
    current_phrase = tokens[-1].lstrip()
    
    # Don't show dropdown if they haven't typed anything or if it perfectly matches an existing metric
    if len(current_phrase) == 0 or current_phrase.strip() in AVAILABLE_METRICS:
        return None

    search_term = current_phrase.lower()
    
    # Case-insensitive search, but return the strict Case-Sensitive metric name
    matches = [m for m in AVAILABLE_METRICS if search_term in m.lower()][:8]
    
    if not matches:
        return None
        
    # Render the dropdown menu directly mimicking the Screener UI
    items = []
    for i, m in enumerate(matches):
        items.append(
            dbc.ListGroupItem(
                m, 
                id={"type": "suggestion-item", "index": m}, 
                action=True, 
                className="border-0",
                style={
                    "cursor": "pointer", 
                    "padding": "10px 16px",
                    "backgroundColor": "#6366f1" if i == 0 else "white",
                    "color": "white" if i == 0 else "#212529",
                    "fontSize": "14px"
                }
            )
        )
        
    return dbc.ListGroup(
        items, 
        flush=True,
        style={
            "position": "absolute", 
            "zIndex": 1000, 
            "width": "80%", 
            "maxHeight": "250px", 
            "overflowY": "auto", 
            "boxShadow": "0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)",
            "borderRadius": "0 0 6px 6px",
            "border": "1px solid #e5e7eb",
            "borderTop": "none"
        }
    )

# 2. INSERT SELECTED SUGGESTION INTO TEXTAREA
@callback(
    Output("screener-query-input", "value", allow_duplicate=True),
    Input({"type": "suggestion-item", "index": dash.ALL}, "n_clicks"),
    State("screener-query-input", "value"),
    prevent_initial_call=True
)
def insert_suggestion(n_clicks_list, current_text):
    if not dash.ctx.triggered_id:
        return dash.no_update
        
    selected_metric = dash.ctx.triggered_id["index"]
    
    # Split to find the exact token we are replacing
    tokens = re.split(r'(\n| > | < | >= | <= | = | AND | OR | NOT )', current_text)
    
    # Replace the current incomplete typing phrase with the exact strict metric name
    tokens[-1] = selected_metric + " "
    
    return "".join(tokens)

# 3. EXECUTE QUERY & RENDER RESULTS
@callback(
    Output("screener-results-container", "children"),
    Output("result-count-title", "children"),
    Output("result-count-title", "className"),
    Output("query-error-message", "children"),
    Input("run-screen-btn", "n_clicks"),
    State("screener-query-input", "value"),
    prevent_initial_call=True
)
def run_query(n_clicks, query):
    if not query or not query.strip():
        return None, "", "d-none", ""

    try:
        # Pass raw query to API (API handles newline flattening safely now)
        resp = requests.post(f"{BACKEND_API_URL}/screener/run", json={"query": query.strip()}, timeout=10)
        
        if resp.status_code != 200:
            err_msg = resp.json().get("detail", "Invalid Syntax")
            return None, "", "d-none", f"❌ {err_msg}"

        data = resp.json()
        results = data.get("data", [])
        count = data.get("match_count", 0)

        if not results:
            return html.Div("No results found.", className="text-muted py-3"), f"Query Results: 0", "fw-bold mb-3 d-block", ""

        # Determine which columns to display based on the query text
        display_cols = ["Ticker", "Current price"]
        for metric in AVAILABLE_METRICS:
            if metric in query and metric not in display_cols:
                display_cols.append(metric)

        valid_cols = [c for c in display_cols if c in results[0]]

        # Build clean DataTable
        table = dash_table.DataTable(
            data=results,
            columns=[
                {"name": col, "id": col, "type": "numeric", "format": dash_table.Format.Format(precision=2, scheme=dash_table.Format.Scheme.fixed)}
                if col != "Ticker" else {"name": col, "id": col}
                for col in valid_cols
            ],
            page_size=50,
            sort_action="native",
            style_table={"overflowX": "auto", "border": "1px solid #e5e7eb", "borderRadius": "6px"},
            style_cell={
                "backgroundColor": "#ffffff",
                "color": "#374151",
                "padding": "12px 16px",
                "fontSize": "14px",
                "fontFamily": "Inter, sans-serif",
                "borderBottom": "1px solid #e5e7eb",
                "textAlign": "right"
            },
            style_cell_conditional=[
                {"if": {"column_id": "Ticker"}, "textAlign": "left", "fontWeight": "600", "color": "#6366f1"}
            ],
            style_header={
                "backgroundColor": "#f9fafb",
                "color": "#111827",
                "fontWeight": "600",
                "borderBottom": "2px solid #e5e7eb",
                "textAlign": "center"
            }
        )

        return table, f"Query Results: {count}", "fw-bold mb-3 text-dark d-block", ""

    except Exception as e:
        return None, "", "d-none", f"❌ API Connection Error: {str(e)}"