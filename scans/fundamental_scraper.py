"""
Complete Screener.in scraper – final structure.
- Scrapes: quarterly results (no Raw PDF), annual P&L, balance sheet, cash flow, ratios, shareholding.
- Uses yfinance only for historical close prices.
- Computes all core metrics into core_metrics.historical_ratios.
"""

import asyncio
import json
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup, Tag
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

OUTPUT_DIR = Path("temp")
OUTPUT_DIR.mkdir(exist_ok=True)

SOURCE_DIR = Path("../main/source")
CONSOLIDATED_FILE = SOURCE_DIR / "consolidated.json"
NONCONSOLIDATED_FILE = SOURCE_DIR / "nonconsolidated.json"

ROUND_DECIMALS = 2


def is_consolidated(ticker: str) -> bool:
    try:
        with open(CONSOLIDATED_FILE, "r") as f:
            cons = set(json.load(f))
        with open(NONCONSOLIDATED_FILE, "r") as f:
            noncons = set(json.load(f))
        return ticker in cons and ticker not in noncons
    except Exception:
        return False


def clean_number(text: str, round_dp: Optional[int] = ROUND_DECIMALS) -> Optional[float]:
    """Convert string to float. Empty/dash/na become 0.0. Returns None only for parsing errors."""
    if not text or text.strip() in {"", "-", "—", "na", "N/A"}:
        return 0.0
    cleaned = re.sub(r"[₹,%]", "", text)
    cleaned = re.sub(r"[a-zA-Z]", "", cleaned)
    cleaned = cleaned.replace(",", "").strip()
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    try:
        val = float(cleaned)
        if round_dp is not None:
            val = round(val, round_dp)
        return val
    except ValueError:
        return None


def parse_financial_table(table: Tag, clean_metric_names: bool = True) -> Dict[str, Any]:
    """Parse a standard Screener financial table (no product segments)."""
    if not table:
        return {"headers": [], "rows": {}}

    rows = table.find_all("tr")
    if len(rows) < 2:
        return {"headers": [], "rows": {}}

    header_cells = rows[0].find_all(["th", "td"])
    headers = [cell.get_text(strip=True) for cell in header_cells][1:]

    data = {}
    rowspan_remain = {}

    for row_idx, row in enumerate(rows[1:], start=1):
        cells = row.find_all(["td", "th"])
        if not cells:
            continue

        first_cell = cells[0]
        metric = first_cell.get_text(strip=True)
        if clean_metric_names:
            metric = metric.rstrip('+')

        if not metric and row_idx in rowspan_remain:
            metric = rowspan_remain[row_idx]
        elif metric and first_cell.get("rowspan"):
            rowspan = int(first_cell.get("rowspan", 1))
            for i in range(1, rowspan):
                rowspan_remain[row_idx + i] = metric

        if not metric:
            continue

        values = {}
        for col_idx, cell in enumerate(cells[1:], start=0):
            if col_idx < len(headers):
                period = headers[col_idx]
                values[period] = clean_number(cell.get_text(strip=True))

        data[metric] = values

    return {"headers": headers, "rows": data}


def get_yfinance_prices(ticker: str) -> Dict[str, float]:
    """Fetch yearly closing prices from yfinance."""
    symbol = f"{ticker}.NS" if not ticker.endswith((".NS", ".BO")) else ticker
    stock = yf.Ticker(symbol)

    end_date = datetime.now()
    start_date = end_date - timedelta(days=10 * 365 + 60)
    price_data = stock.history(start=start_date, end=end_date, interval="1d")
    if price_data.empty:
        return {}

    if price_data.index.tz is not None:
        price_data.index = price_data.index.tz_localize(None)

    yearly_prices = {}
    for year in range(start_date.year, end_date.year + 1):
        year_data = price_data[price_data.index.year == year]
        if not year_data.empty:
            yearly_prices[str(year)] = round(year_data['Close'].iloc[-1], ROUND_DECIMALS)

    return yearly_prices


def sort_periods(periods):
    """Sort fiscal periods like 'Mar 2015', 'Jun 2020' by year and month."""
    month_order = {"Mar": 3, "Jun": 6, "Sep": 9, "Dec": 12}
    def key_func(p):
        parts = p.split()
        if len(parts) == 2:
            month, year = parts[0], int(parts[1])
            return (year, month_order.get(month, 0))
        return (0, 0)
    return sorted(periods, key=key_func)


async def scrape_screener_complete(ticker: str) -> Dict[str, Any]:
    """Scrape all required tables, compute core metrics."""
    base_url = f"https://www.screener.in/company/{ticker}/"
    if is_consolidated(ticker):
        url = base_url + "consolidated/"
    else:
        url = base_url

    print(f"Loading {url} ...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1280, "height": 720},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.google.com/"}
        )
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except PlaywrightTimeoutError:
            await page.goto(url, wait_until="load", timeout=60000)

        await page.wait_for_selector("ul#top-ratios", timeout=30000)
        await page.wait_for_timeout(2000)

        html_before = await page.content()
        soup_before = BeautifulSoup(html_before, "html.parser")

        # ---- Financial tables ----
        quarterly_main = {}
        q_section = soup_before.find("section", id="quarters")
        if q_section:
            q_table = q_section.find("table", class_="data-table")
            if q_table:
                quarterly_main = parse_financial_table(q_table)
                # Remove "Raw PDF" row if present
                if "Raw PDF" in quarterly_main.get("rows", {}):
                    del quarterly_main["rows"]["Raw PDF"]

        pl_main = {}
        pl_section = soup_before.find("section", id="profit-loss")
        if pl_section:
            pl_table = pl_section.find("table", class_="data-table")
            if pl_table:
                pl_main = parse_financial_table(pl_table)

        bs = {}
        bs_section = soup_before.find("section", id="balance-sheet")
        if bs_section:
            bs_table = bs_section.find("table", class_="data-table")
            if bs_table:
                bs = parse_financial_table(bs_table)

        cf = {}
        cf_section = soup_before.find("section", id="cash-flow")
        if cf_section:
            cf_table = cf_section.find("table", class_="data-table")
            if cf_table:
                cf = parse_financial_table(cf_table)

        ratios_table = {}
        ratios_section = soup_before.find("section", id="ratios")
        if ratios_section:
            r_table = ratios_section.find("table", class_="data-table")
            if r_table:
                ratios_table = parse_financial_table(r_table)

        # ---- Yearly shareholding (click tab) ----
        yearly_tab = await page.query_selector('button[data-tab-id="yearly-shp"]')
        if yearly_tab:
            await yearly_tab.click()
            await page.wait_for_timeout(1000)

        html_final = await page.content()
        soup_final = BeautifulSoup(html_final, "html.parser")

        shareholding = {}
        sh_section = soup_final.find("section", id="shareholding")
        if sh_section:
            q_sh_div = sh_section.find("div", id="quarterly-shp")
            if q_sh_div:
                q_table = q_sh_div.find("table", class_="data-table")
                if q_table:
                    shareholding["quarterly"] = parse_financial_table(q_table)
            y_sh_div = sh_section.find("div", id="yearly-shp")
            if y_sh_div:
                y_table = y_sh_div.find("table", class_="data-table")
                if y_table:
                    shareholding["yearly"] = parse_financial_table(y_table)

        await browser.close()

    # ---- Fetch yearly prices ----
    yearly_prices = get_yfinance_prices(ticker)

    # ---- Compute total equity from balance sheet ----
    total_equity_series = {}
    eq_cap_series = bs.get("rows", {}).get("Equity Capital", {})
    reserves_series = bs.get("rows", {}).get("Reserves", {})
    for period in eq_cap_series:
        if period in reserves_series:
            eq_cap = eq_cap_series.get(period)
            reserves = reserves_series.get(period)
            if eq_cap is not None and reserves is not None:
                total_equity_series[period] = eq_cap + reserves

    # ---- Helper to extract year from period ----
    def period_to_year(period: str) -> Optional[str]:
        parts = period.split()
        if len(parts) == 2 and parts[0] in ["Mar", "Jun", "Sep", "Dec"]:
            return parts[1]
        return None

    # ---- Extract annual P&L rows ----
    pl_rows = pl_main.get("rows", {})
    sales_series = pl_rows.get("Sales", {})
    net_profit_series = pl_rows.get("Net Profit", {})
    eps_series = pl_rows.get("EPS in Rs", {})
    opm_series = pl_rows.get("OPM %", {})
    div_payout_series = pl_rows.get("Dividend Payout %", {})

    # ---- Extract ROCE from ratios table ----
    roce_series = ratios_table.get("rows", {}).get("ROCE %", {})

    # ---- Sort periods chronologically ----
    all_periods = set(sales_series.keys()) | set(net_profit_series.keys()) | set(eps_series.keys())
    sorted_periods = sort_periods([p for p in all_periods if period_to_year(p)])

    # ---- Compute historical ratios per year ----
    historical_ratios = {}
    prev_sales = prev_profit = prev_eps = None

    for period in sorted_periods:
        year = period_to_year(period)
        if not year or year not in yearly_prices:
            continue

        # Get values
        sales = sales_series.get(period)
        net_profit = net_profit_series.get(period)
        eps = eps_series.get(period)
        opm = opm_series.get(period)
        div_payout = div_payout_series.get(period)
        roce = roce_series.get(period)
        total_equity = total_equity_series.get(period)
        price = yearly_prices.get(year)

        # Compute ROE
        roe = round((net_profit / total_equity) * 100, ROUND_DECIMALS) if net_profit and total_equity and total_equity != 0 else None

        # Compute P/E
        pe = round(price / eps, ROUND_DECIMALS) if price and eps and eps > 0 else None

        # Compute Dividend Yield
        div_yield = None
        if div_payout is not None and eps and price and div_payout != 0:
            dps = (div_payout / 100) * eps
            if dps > 0:
                div_yield = round((dps / price) * 100, ROUND_DECIMALS)

        # Compute growth percentages (YoY)
        sales_growth = round(((sales - prev_sales) / prev_sales) * 100, ROUND_DECIMALS) if prev_sales is not None and prev_sales != 0 else None
        profit_growth = round(((net_profit - prev_profit) / prev_profit) * 100, ROUND_DECIMALS) if prev_profit is not None and prev_profit != 0 else None
        eps_growth = round(((eps - prev_eps) / prev_eps) * 100, ROUND_DECIMALS) if prev_eps is not None and prev_eps != 0 else None

        historical_ratios[year] = {
            "pe_ratio": pe,
            "dividend_yield_pct": div_yield,
            "roce_pct": round(roce, ROUND_DECIMALS) if roce is not None else None,
            "roe_pct": roe,
            "close_price": price,
            "sales_growth_pct": sales_growth,
            "profit_growth_pct": profit_growth,
            "eps_growth_pct": eps_growth,
            "opm_percent": round(opm, ROUND_DECIMALS) if opm is not None else None,
            "dividend_payout_percent": round(div_payout, ROUND_DECIMALS) if div_payout is not None else None,
        }

        # Update previous values for next iteration
        prev_sales, prev_profit, prev_eps = sales, net_profit, eps

    # ---- Build final JSON ----
    result = {
        "ticker": ticker,
        "scraped_at": datetime.now().isoformat(),
        "core_metrics": {
            "historical_ratios": historical_ratios
        },
        "raw_financials": {
            "quarterly_results": quarterly_main,
            "profit_loss_annual": pl_main,
            "balance_sheet": bs,
            "cash_flow": cf,
            "ratios": ratios_table,
            "shareholding": shareholding,
        }
    }
    return result


async def main(ticker: str):
    data = await scrape_screener_complete(ticker)
    out_file = OUTPUT_DIR / f"{ticker.lower()}_complete.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved complete data to {out_file}")
    print(f"Historical ratios available for: {list(data['core_metrics']['historical_ratios'].keys())}")


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "INFY"
    asyncio.run(main(ticker.upper()))