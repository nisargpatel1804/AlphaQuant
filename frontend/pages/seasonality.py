from __future__ import annotations

import json
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html, register_page
import os
import requests


register_page(__name__, path="/seasonality", name="Seasonality", title="AlphaQuant Seasonality")

API_BASE = os.getenv("ALPHAQUANT_API_BASE", "http://127.0.0.1:8000")


def layout(**kwargs):
    return dbc.Container(
        [
            dcc.Store(id="seasonality-store"),
            html.H2("Seasonality"),
            dbc.Row(
                [
                    dbc.Col(dbc.Input(id="seasonality-symbol", value="RELIANCE", placeholder="Symbol"), md=8),
                    dbc.Col(dbc.Button("Load Seasonality", id="seasonality-load", color="primary", className="w-100"), md=4),
                ],
                className="mb-3",
            ),
            dbc.Card(dbc.CardBody([html.Div(id="seasonality-summary"), html.Pre(id="seasonality-output", className="json-output")]), className="glass-card"),
        ],
        fluid=True,
    )


@callback(
    Output("seasonality-store", "data"),
    Input("seasonality-load", "n_clicks"),
    State("seasonality-symbol", "value"),
    prevent_initial_call=True,
)
def load_seasonality(n_clicks, symbol):
    response = requests.get(f"{API_BASE}/api/v1/seasonality/{(symbol or 'RELIANCE').strip().upper()}", timeout=180)
    response.raise_for_status()
    return response.json()


@callback(
    [Output("seasonality-summary", "children"), Output("seasonality-output", "children")],
    Input("seasonality-store", "data"),
    prevent_initial_call=True,
)
def render_seasonality(data):
    if not data:
        return html.Div("Load seasonality data to inspect the extracted Moneycontrol payload."), ""
    summary = html.Div([html.P(f"Kind: {data.get('kind', 'unknown')}"), html.P(f"Errors: {', '.join(data.get('errors', [])) or 'none'}")])
    return summary, json.dumps(data, indent=2, default=str)
