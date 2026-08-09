from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import Input, Output, callback, dcc, html, register_page
import json
import os
import requests


register_page(__name__, path="/sector", name="Sector", title="AlphaQuant Sector")

API_BASE = os.getenv("ALPHAQUANT_API_BASE", "http://127.0.0.1:8000")


layout = dbc.Container(
    [
        dcc.Store(id="sector-store"),
        html.H2("Sector"),
        dbc.Button("Load Sector Analysis", id="sector-load", color="primary", className="mb-3"),
        dbc.Card(dbc.CardBody([html.Div(id="sector-summary"), html.Pre(id="sector-output", className="json-output")]), className="glass-card"),
    ],
    fluid=True,
)


@callback(Output("sector-store", "data"), Input("sector-load", "n_clicks"), prevent_initial_call=True)
def load_sector(n_clicks):
    response = requests.get(f"{API_BASE}/api/v1/sector", timeout=180)
    response.raise_for_status()
    return response.json()


@callback([Output("sector-summary", "children"), Output("sector-output", "children")], Input("sector-store", "data"), prevent_initial_call=True)
def render_sector(data):
    if not data:
        return html.Div("Load the sector analysis to inspect the Moneycontrol scraper output."), ""
    summary = data.get("summary", {})
    summary_node = html.Div([html.P(f"Total sectors: {summary.get('total_sectors', 0)}"), html.P(f"Total industries: {summary.get('total_industries', 0)}")])
    return summary_node, json.dumps(data, indent=2, default=str)
