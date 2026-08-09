from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import Input, Output, callback, dcc, html, register_page
import json
import os
import requests


register_page(__name__, path="/tickertape", name="Tickertape", title="AlphaQuant Tickertape")

API_BASE = os.getenv("ALPHAQUANT_API_BASE", "http://127.0.0.1:8000")


layout = dbc.Container(
    [
        dcc.Store(id="tickertape-store"),
        html.H2("Tickertape"),
        dbc.Button("Load Market Mood", id="tickertape-load", color="primary", className="mb-3"),
        dbc.Card(dbc.CardBody([html.Div(id="tickertape-summary"), html.Pre(id="tickertape-output", className="json-output")]), className="glass-card"),
    ],
    fluid=True,
)


@callback(Output("tickertape-store", "data"), Input("tickertape-load", "n_clicks"), prevent_initial_call=True)
def load_tickertape(n_clicks):
    response = requests.get(f"{API_BASE}/api/v1/tickertape", timeout=120)
    response.raise_for_status()
    return response.json()


@callback([Output("tickertape-summary", "children"), Output("tickertape-output", "children")], Input("tickertape-store", "data"), prevent_initial_call=True)
def render_tickertape(data):
    if not data:
        return html.Div("Load the Tickertape market mood feed to inspect sentiment data."), ""
    mmi = data.get("market_mood_index", {})
    summary = html.Div([html.P(f"Zone: {mmi.get('zone', 'unknown')}"), html.P(f"Current value: {mmi.get('value', 'n/a')}")])
    return summary, json.dumps(data, indent=2, default=str)
