# frontend/components.py

from __future__ import annotations
from typing import Any, Dict, List, Optional

import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import dash_table, html
import dash_bootstrap_components as dbc

# ----------------------------------------------------------------------
# COLOR PALETTE (Clean Light Theme)
# ----------------------------------------------------------------------
COLOR_BLUE = "#2962ff"     # Primary brand blue
COLOR_ORANGE = "#ff7f0e"
COLOR_GREEN = "#198754"    # Bootstrap success
COLOR_RED = "#dc3545"      # Bootstrap danger
COLOR_PURPLE = "#8b5cf6"
COLOR_YELLOW = "#ffb300"
COLOR_TEXT_MAIN = "#212529"
COLOR_TEXT_MUTED = "#6c757d"
COLOR_MEDIAN = "#dc3545"

def _light_layout(title: str = "", height: int = 380) -> dict:
    """Base layout for all light-themed Plotly charts."""
    return dict(
        title=dict(text=title, font=dict(color=COLOR_TEXT_MAIN, size=15, family="Inter, sans-serif")),
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=height,
        margin=dict(l=40, r=30, t=50, b=30),
        font=dict(color=COLOR_TEXT_MUTED, family="Inter, sans-serif"),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

def _empty_figure(title: str, message: str = "Data Unavailable", height: int = 350) -> go.Figure:
    """Returns a clean empty figure when data is missing, preventing dummy assumptions."""
    fig = go.Figure()
    fig.update_layout(**_light_layout(title, height=height))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.add_annotation(text=message, xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False, font=dict(size=14, color=COLOR_TEXT_MUTED))
    return fig

# ======================================================================
# 1. MAIN DASHBOARD COMPONENTS
# ======================================================================

def create_mmi_gauge(mmi_data: Optional[Dict[str, Any]]) -> go.Figure:
    """Generates MMI gauge dial."""
    if not mmi_data or mmi_data.get("value") is None:
        return _empty_figure("Market Mood Index", "MMI Data Unavailable", 250)

    mmi_value = round(mmi_data.get("value"), 2)
    zone_code = mmi_data.get("zone_fear", 1)
    
    zone_names = {0: "Extreme Fear", 1: "Fear", 2: "Greed", 3: "Extreme Greed"}
    zone_text = zone_names.get(zone_code, "Neutral")

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=mmi_value,
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': f"Zone: <b>{zone_text}</b>", 'font': {'size': 14, 'color': COLOR_TEXT_MAIN}},
        number={'font': {'size': 38, 'color': COLOR_TEXT_MAIN}},
        gauge={
            'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "#dee2e6"},
            'bar': {'color': COLOR_BLUE, 'thickness': 0.25},
            'bgcolor': "rgba(0,0,0,0)",
            'borderwidth': 0,
            'steps': [
                {'range': [0, 30], 'color': 'rgba(220, 53, 69, 0.2)'},     # Extreme Fear
                {'range': [30, 50], 'color': 'rgba(255, 179, 0, 0.2)'},   # Fear
                {'range': [50, 70], 'color': 'rgba(41, 98, 255, 0.2)'},    # Greed
                {'range': [70, 100], 'color': 'rgba(25, 135, 84, 0.2)'}     # Extreme Greed
            ],
            'threshold': {
                'line': {'color': COLOR_TEXT_MAIN, 'width': 4},
                'thickness': 0.75,
                'value': mmi_value
            }
        }
    ))
    fig.update_layout(**_light_layout("", height=250))
    return fig

def create_advance_decline_bar(advances: int, declines: int, total: int) -> html.Div:
    """Renders a real-time Market Breadth (Advance/Decline) horizontal bar using pure HTML/CSS to avoid DBC version conflicts."""
    if not total or total <= 0:
        return html.Div("Market Breadth Data Unavailable", className="text-muted text-center py-4")

    # Safety fallbacks
    advances = advances or 0
    declines = declines or 0

    adv_pct = round((advances / total) * 100, 1)
    dec_pct = round((declines / total) * 100, 1)
    unchanged = max(0, total - (advances + declines))
    unch_pct = round((unchanged / total) * 100, 1)
    
    return html.Div([
        html.Div([
            html.Span(f"Advances: {advances} ({adv_pct}%)", className="text-success fw-bold float-start"),
            html.Span(f"Declines: {declines} ({dec_pct}%)", className="text-danger fw-bold float-end"),
        ], className="mb-1 clearfix small"),
        # Native Bootstrap 5 Progress Bar structure avoids the deprecated 'multi' kwarg in DBC
        html.Div(className="progress", style={"height": "14px", "borderRadius": "7px", "backgroundColor": "#e9ecef"}, children=[
            html.Div(className="progress-bar bg-success", style={"width": f"{adv_pct}%"}),
            html.Div(className="progress-bar bg-secondary", style={"width": f"{unch_pct}%"}),
            html.Div(className="progress-bar bg-danger", style={"width": f"{dec_pct}%"}),
        ]),
        html.Div(f"Total Tracked: {total} | Unchanged: {unchanged}", className="text-muted text-center mt-2 style-micro")
    ])

def create_metric_card(title: str, value: str, subtext: str, is_positive: bool = True) -> dbc.Card:
    """KPI summary metric card for quick stats."""
    color = COLOR_GREEN if is_positive else COLOR_RED
    return dbc.Card(
        dbc.CardBody([
            html.H6(title, className="card-subtitle text-muted mb-1", style={"fontSize": "0.8rem"}),
            html.H3(value, className="card-title my-1", style={"fontWeight": "700", "color": COLOR_TEXT_MAIN}),
            html.P(subtext, className="card-text mb-0", style={"color": color, "fontSize": "0.85rem", "fontWeight": "600"})
        ]),
        className="aq-metric-card border-secondary bg-transparent shadow-sm mb-3"
    )

def create_sector_treemap(sector_analysis: Optional[Dict[str, Any]]) -> go.Figure:
    """Generates Sector Treemap directly from sector.json structure."""
    if not sector_analysis or not sector_analysis.get("sectors"):
        return _empty_figure("Sector Performance", "Sector Data Unavailable", 340)

    sectors = sector_analysis.get("sectors", [])
    names, parents, values, colors, hover_texts = [], [], [], [], []
    
    for sec in sectors:
        mcap = sec.get("market_cap_cr")
        if mcap is None or mcap <= 0:
            continue  # Skip if no valid market cap
            
        names.append(sec.get("name", "Unknown"))
        parents.append("")
        values.append(mcap)
        chg = sec.get("market_cap_change_pct", 0.0)
        colors.append(chg)
        
        adv = sec.get("advance_count") or 0
        dec = sec.get("decline_count") or 0
        hover_texts.append(
            f"<b>{sec.get('name')}</b><br>"
            f"Market Cap: ₹{mcap:,.0f} Cr<br>"
            f"1D Change: {chg}%<br>"
            f"Advances/Declines: {adv} / {dec}"
        )

    if not names:
        return _empty_figure("Sector Performance", "Valid Sector Data Unavailable", 340)

    fig = go.Figure(go.Treemap(
        labels=names,
        parents=parents,
        values=values,
        marker=dict(
            colors=colors,
            colorscale=[[0, COLOR_RED], [0.5, "#e9ecef"], [1, COLOR_GREEN]],
            cmid=0,
            showscale=True,
            colorbar=dict(title="1D %", len=0.8)
        ),
        hovertext=hover_texts,
        hoverinfo="text",
        textinfo="label+value"
    ))
    fig.update_layout(**_light_layout("Sector Capital Allocation & 1D Trend", height=340))
    return fig

# ======================================================================
# 2. FUNDAMENTAL SCAN VISUALIZATIONS
# ======================================================================

def create_historical_valuation_chart(historical_ratios: Dict[str, Any]) -> go.Figure:
    """Renders Price vs P/E Ratio trend over time."""
    if not historical_ratios: 
        return _empty_figure("Historical Valuation", "Data Unavailable")
        
    years = sorted(list(historical_ratios.keys()))
    prices = [historical_ratios[y].get("close_price") for y in years]
    pes = [historical_ratios[y].get("pe_ratio") for y in years]

    if not any(prices) and not any(pes):
        return _empty_figure("Historical Valuation", "Data Unavailable")

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Scatter(x=years, y=prices, name="Close Price (₹)", line=dict(color=COLOR_BLUE, width=3), mode="lines+markers"),
        secondary_y=False,
    )

    fig.add_trace(
        go.Scatter(x=years, y=pes, name="P/E Ratio", line=dict(color=COLOR_ORANGE, width=2, dash="dash"), mode="lines+markers"),
        secondary_y=True,
    )

    fig.update_layout(**_light_layout("Price vs. P/E Multiple Trend", height=350))
    fig.update_xaxes(title_text="Fiscal Year", gridcolor="rgba(0,0,0,0.05)")
    fig.update_yaxes(title_text="Stock Price (₹)", secondary_y=False, gridcolor="rgba(0,0,0,0.05)")
    fig.update_yaxes(title_text="P/E Ratio", secondary_y=True, showgrid=False)
    return fig

def create_growth_metrics_chart(historical_ratios: Dict[str, Any]) -> go.Figure:
    """Renders YoY Sales Growth % vs Profit Growth % bars."""
    if not historical_ratios: 
        return _empty_figure("Growth Metrics", "Data Unavailable")
        
    years = sorted(list(historical_ratios.keys()))
    sales_growth = [historical_ratios[y].get("sales_growth_pct") for y in years]
    profit_growth = [historical_ratios[y].get("profit_growth_pct") for y in years]

    if not any(sales_growth) and not any(profit_growth):
        return _empty_figure("Growth Metrics", "Data Unavailable")

    fig = go.Figure()
    fig.add_trace(go.Bar(x=years, y=sales_growth, name="Sales Growth YoY %", marker_color=COLOR_BLUE, opacity=0.85))
    fig.add_trace(go.Bar(x=years, y=profit_growth, name="Profit Growth YoY %", marker_color=COLOR_GREEN, opacity=0.85))

    fig.update_layout(**_light_layout("YoY Sales & Net Profit Growth (%)", height=350))
    fig.update_layout(barmode='group')
    fig.update_yaxes(gridcolor="rgba(0,0,0,0.05)")
    fig.update_xaxes(gridcolor="rgba(0,0,0,0.05)")
    return fig

def create_ev_ebitda_chart(historical_ratios: Dict[str, Any]) -> go.Figure:
    """Renders EV/EBITDA multiple trend over time."""
    if not historical_ratios: 
        return _empty_figure("EV / EBITDA", "Data Unavailable")
        
    years = sorted(list(historical_ratios.keys()))
    evs = [historical_ratios[y].get("ev_ebitda") for y in years]
    valid_evs = [v for v in evs if v is not None]
    
    if not valid_evs:
        return _empty_figure("EV / EBITDA", "Data Unavailable")
        
    median_ev = round(sum(valid_evs) / len(valid_evs), 2)

    return multi_line_figure(
        "Historical EV / EBITDA Multiple",
        years,
        {"EV/EBITDA": evs},
        yaxis_title="EV/EBITDA Multiple",
        show_median=True,
        median_value=median_ev,
        median_label=f"Median = {median_ev}x",
        height=350
    )

def create_pb_chart(historical_ratios: Dict[str, Any]) -> go.Figure:
    """Renders Price-to-Book (P/B) ratio trend over time."""
    if not historical_ratios: 
        return _empty_figure("P/B Ratio", "Data Unavailable")
        
    years = sorted(list(historical_ratios.keys()))
    pbs = [historical_ratios[y].get("pb_ratio") for y in years]
    valid_pbs = [v for v in pbs if v is not None]
    
    if not valid_pbs:
        return _empty_figure("P/B Ratio", "Data Unavailable")
        
    median_pb = round(sum(valid_pbs) / len(valid_pbs), 2)

    return multi_line_figure(
        "Historical Price to Book (P/B) Ratio",
        years,
        {"P/B": pbs},
        yaxis_title="P/B Ratio",
        show_median=True,
        median_value=median_pb,
        median_label=f"Median = {median_pb}x",
        height=350
    )

def create_margins_chart(historical_ratios: Dict[str, Any]) -> go.Figure:
    """Renders Operating Profit Margin (OPM %) vs Net Profit Margin (NPM %)."""
    if not historical_ratios: 
        return _empty_figure("Margins", "Data Unavailable")
        
    years = sorted(list(historical_ratios.keys()))
    opms = [historical_ratios[y].get("opm_percent") for y in years]
    npms = [historical_ratios[y].get("npm_percent") for y in years]

    if not any(opms) and not any(npms):
        return _empty_figure("Margins", "Data Unavailable")

    return multi_line_figure(
        "Operating Margin (OPM) vs Net Margin (NPM)",
        years,
        {"OPM %": opms, "NPM %": npms},
        yaxis_title="Margin (%)",
        height=350
    )

def create_shareholding_chart(shareholding_data: Dict[str, Any], is_quarterly: bool = True) -> go.Figure:
    """Renders stacked bar charts for Promoter, FII, DII, Public, and Gov holdings over time."""
    section_key = "quarterly" if is_quarterly else "yearly"
    shp = shareholding_data.get(section_key, {})
    headers = shp.get("headers", [])
    rows = shp.get("rows", {})

    if not headers or not rows:
        return _empty_figure(f"Shareholding Pattern Trend ({section_key.capitalize()})", "Data Unavailable")

    fig = go.Figure()
    colors = {
        "Promoters": COLOR_BLUE,
        "FIIs": COLOR_GREEN,
        "DIIs": COLOR_YELLOW,
        "Government": COLOR_PURPLE,
        "Public": COLOR_RED
    }

    added_traces = False
    for category, val_dict in rows.items():
        if category in colors:
            y_vals = [val_dict.get(h, 0.0) for h in headers]
            if any(y_vals):
                fig.add_trace(go.Bar(
                    x=headers,
                    y=y_vals,
                    name=category,
                    marker_color=colors[category]
                ))
                added_traces = True

    if not added_traces:
        return _empty_figure(f"Shareholding Pattern Trend ({section_key.capitalize()})", "Data Unavailable")

    fig.update_layout(**_light_layout(f"Shareholding Pattern Trend ({section_key.capitalize()})", height=350))
    fig.update_layout(barmode='stack')
    fig.update_yaxes(range=[0, 100], title="Holding %", gridcolor="rgba(0,0,0,0.05)")
    fig.update_xaxes(gridcolor="rgba(0,0,0,0.05)")
    return fig

# ======================================================================
# 3. GENERIC / CUSTOM VISUALIZATIONS
# ======================================================================

def multi_line_figure(
    title: str,
    x_values: list,
    series_dict: dict,
    yaxis_title: str = "Value",
    height: int = 380,
    show_median: bool = False,
    median_value: float = None,
    median_label: str = "Median",
) -> go.Figure:
    """
    Multi‑line chart with optional median line – Light Mode.
    Lines use smooth splines and a consistent color cycle.
    """
    fig = go.Figure()
    color_cycle = [COLOR_BLUE, COLOR_ORANGE, COLOR_GREEN, COLOR_PURPLE, COLOR_YELLOW]
    
    for i, (name, values) in enumerate(series_dict.items()):
        fig.add_trace(go.Scatter(
            x=x_values,
            y=values,
            mode='lines+markers',
            name=name,
            line=dict(width=3, shape='spline', color=color_cycle[i % len(color_cycle)]),
            marker=dict(size=6, color=color_cycle[i % len(color_cycle)])
        ))
        
    if show_median and median_value is not None:
        fig.add_hline(
            y=median_value,
            line_dash="dash",
            line_color=COLOR_MEDIAN,
            annotation_text=median_label,
            annotation_position="top right",
            annotation_font_color=COLOR_TEXT_MAIN
        )
        
    fig.update_layout(**_light_layout(title, height))
    fig.update_yaxes(title_text=yaxis_title, gridcolor="rgba(0,0,0,0.05)")
    fig.update_xaxes(gridcolor="rgba(0,0,0,0.05)")
    return fig

def bar_with_lines_figure(
    title: str,
    x_values: list,
    bar_series: dict,
    line_series: dict,
    yaxis_title: str = "Primary",
    y2_title: str = "Margin (%)",
    height: int = 380,
) -> go.Figure:
    """
    Bar chart for primary values and lines for margins (Light Mode).
    """
    fig = go.Figure()
    
    # Bar
    for name, values in bar_series.items():
        fig.add_trace(go.Bar(
            x=x_values,
            y=values,
            name=name,
            marker_color=COLOR_BLUE,
            opacity=0.6
        ))
        
    # Lines
    line_colors = [COLOR_GREEN, COLOR_ORANGE, COLOR_RED, COLOR_PURPLE]
    for i, (name, values) in enumerate(line_series.items()):
        fig.add_trace(go.Scatter(
            x=x_values,
            y=values,
            mode='lines+markers',
            name=name,
            line=dict(width=3, shape='spline', color=line_colors[i % len(line_colors)]),
            marker=dict(size=6, color=line_colors[i % len(line_colors)]),
            yaxis="y2"
        ))
        
    fig.update_layout(**_light_layout(title, height))
    fig.update_yaxes(title_text=yaxis_title, gridcolor="rgba(0,0,0,0.05)")
    fig.update_yaxes(title_text=y2_title, overlaying="y", side="right", showgrid=False)
    fig.update_xaxes(gridcolor="rgba(0,0,0,0.05)")
    return fig

# ======================================================================
# 4. DATATABLE RENDERER
# ======================================================================

def render_screener_datatable(table_data: Dict[str, Any], table_id: str) -> dash_table.DataTable:
    """
    Converts raw Screener table structure into an interactive Light-Themed Dash DataTable.
    """
    headers = table_data.get("headers", [])
    rows_dict = table_data.get("rows", {})

    if not headers or not rows_dict:
        return dash_table.DataTable(id=table_id, data=[], columns=[])

    data_rows = []
    for metric_name, period_values in rows_dict.items():
        row_entry = {"Metric": metric_name}
        for period in headers:
            val = period_values.get(period)
            if isinstance(val, (int, float)):
                row_entry[period] = f"{val:,.2f}"
            else:
                row_entry[period] = val if val is not None else "-"
        data_rows.append(row_entry)

    columns = [{"name": "Metric", "id": "Metric"}] + [{"name": h, "id": h} for h in headers]

    return dash_table.DataTable(
        id=table_id,
        data=data_rows,
        columns=columns,
        fixed_columns={'headers': True, 'data': 1},
        style_table={"overflowX": "auto", "minWidth": "100%"},
        style_cell={
            "backgroundColor": "#ffffff",
            "color": COLOR_TEXT_MAIN,
            "border": "1px solid #dee2e6",
            "padding": "10px",
            "fontSize": "0.85rem",
            "fontFamily": "Inter, sans-serif",
            "minWidth": "110px",
            "textAlign": "right"
        },
        style_cell_conditional=[
            {"if": {"column_id": "Metric"}, "textAlign": "left"}
        ],
        style_header={
            "backgroundColor": "#f8f9fa",
            "color": COLOR_TEXT_MAIN,
            "fontWeight": "700",
            "borderBottom": f"2px solid {COLOR_BLUE}",
            "textAlign": "center"
        },
        style_data_conditional=[
            {"if": {"column_id": "Metric"}, "backgroundColor": "#f8f9fa", "fontWeight": "bold", "color": COLOR_TEXT_MAIN},
            {"if": {"filter_query": "{Metric} = 'Sales'"}, "backgroundColor": "rgba(41, 98, 255, 0.08)", "color": "#0d6efd"},
            {"if": {"filter_query": "{Metric} = 'Net Profit'"}, "backgroundColor": "rgba(25, 135, 84, 0.08)", "color": "#198754", "fontWeight": "bold"},
            {"if": {"filter_query": "{Metric} = 'Operating Profit'"}, "backgroundColor": "rgba(255, 179, 0, 0.08)", "color": "#d97706"}
        ]
    )