from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html, register_page
import os
import requests


register_page(__name__, path="/backtester", name="Backtester", title="AlphaQuant Backtester")

API_BASE = os.getenv("ALPHAQUANT_API_BASE", "http://127.0.0.1:8000")


def layout(**kwargs):
    return dbc.Container(
        [
            dcc.Store(id="backtest-store"),
            html.H2("Backtester"),
            dbc.Row(
                [
                    dbc.Col(dbc.Textarea(id="backtest-tickers", value="RELIANCE,INFY,TCS", style={"minHeight": "90px"}), md=6),
                    dbc.Col(
                        [
                            dbc.Input(id="backtest-capital", type="number", value=1000000, min=0, step=50000, className="mb-2"),
                            dbc.Select(id="backtest-timeframe", value="2Y", options=[{"label": v, "value": v} for v in ["1W", "1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "Max"]]),
                            dbc.Button("Run Backtest", id="backtest-run", color="primary", className="mt-2 w-100"),
                        ],
                        md=6,
                    ),
                ],
                className="mb-3",
            ),
            dbc.Card(dbc.CardBody([html.Div(id="backtest-summary"), dcc.Graph(id="backtest-chart")]), className="glass-card"),
        ],
        fluid=True,
    )


@callback(
    Output("backtest-store", "data"),
    Input("backtest-run", "n_clicks"),
    State("backtest-tickers", "value"),
    State("backtest-capital", "value"),
    State("backtest-timeframe", "value"),
    prevent_initial_call=True,
)
def run_backtest(n_clicks, tickers_text, capital, timeframe):
    tickers = [part.strip().upper() for part in (tickers_text or "").split(",") if part.strip()]
    response = requests.post(
        f"{API_BASE}/api/v1/backtester",
        json={"tickers": tickers, "capital": capital or 0, "timeframe": timeframe or "2Y"},
        timeout=180,
    )
    response.raise_for_status()
    return response.json()


@callback(
    [Output("backtest-summary", "children"), Output("backtest-chart", "figure")],
    Input("backtest-store", "data"),
    prevent_initial_call=True,
)
def render_backtest(data):
    if not data:
        return html.Div("Run a backtest to see portfolio results."), {"data": [], "layout": {"template": "plotly_dark"}}

    summary = data.get("summary", {})
    chart = data.get("chart", {"data": [], "layout": {}})
    summary_text = html.Div(
        [
            html.P(f"Status: {summary.get('status', 'unknown')}"),
            html.P(f"Portfolio return: {summary.get('portfolio_return_pct', 0)}%"),
            html.P(f"Max drawdown: {summary.get('portfolio_max_drawdown_pct', 0)}%"),
        ]
    )
    return summary_text, chart
