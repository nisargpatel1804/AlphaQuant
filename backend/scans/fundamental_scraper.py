# backend/scans/fundamental_scraper.py

"""
Complete Screener.in scraper – production-ready structure with extended metrics.
- Scrapes: quarterly results, annual P&L, balance sheet, cash flow, ratios, shareholding.
- Uses yfinance for historical annual close prices.
- Computes core metrics into core_metrics.historical_ratios:
    - P/E Ratio, P/B Ratio, EV/EBITDA, Market Cap/Sales, NPM %
    - ROE %, ROCE %, OPM %, Dividend Yield %, Dividend Payout %
    - YoY Sales Growth %, Profit Growth %, EPS Growth %
"""

import asyncio
import json
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, List

import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup, Tag
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
OUTPUT_DIR = BASE_DIR / "output" / "data"                  # backend/output/data/
SOURCE_DIR = BASE_DIR / "source"                           # backend/source/

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CONSOLIDATED_FILE = SOURCE_DIR / "consolidated.json"
NONCONSOLIDATED_FILE = SOURCE_DIR / "nonconsolidated.json"

ROUND_DECIMALS = 2


def is_consolidated(ticker: str) -> bool:
    """Check whether to use consolidated or standalone URL for Screener."""
    try:
        with open(CONSOLIDATED_FILE, "r", encoding="utf-8") as f:
            cons = set(json.load(f))
        with open(NONCONSOLIDATED_FILE, "r", encoding="utf-8") as f:
            noncons = set(json.load(f))
        return ticker in cons and ticker not in noncons
    except Exception:
        return False


def clean_number(text: str, round_dp: Optional[int] = ROUND_DECIMALS) -> Optional[float]:
    """Convert raw string to float. Empty/dash/na become 0.0."""
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
    """Parse a standard Screener financial table into headers and rows dict."""
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
    """Fetch yearly closing prices from yfinance for March fiscal year ends."""
    symbol = f"{ticker}.NS" if not ticker.endswith((".NS", ".BO")) else ticker
    stock = yf.Ticker(symbol)

    end_date = datetime.now()
    start_date = end_date - timedelta(days=11 * 365 + 60)
    price_data = stock.history(start=start_date, end=end_date, interval="1d")
    if price_data.empty:
        return {}

    if price_data.index.tz is not None:
        price_data.index = price_data.index.tz_localize(None)

    yearly_prices = {}
    for year in range(start_date.year, end_date.year + 1):
        # Look for March data first (NSE fiscal year end)
        march_data = price_data[(price_data.index.year == year) & (price_data.index.month == 3)]
        if not march_data.empty:
            yearly_prices[str(year)] = round(float(march_data['Close'].iloc[-1]), ROUND_DECIMALS)
        else:
            year_data = price_data[price_data.index.year == year]
            if not year_data.empty:
                yearly_prices[str(year)] = round(float(year_data['Close'].iloc[-1]), ROUND_DECIMALS)

    return yearly_prices


def sort_periods(periods: List[str]) -> List[str]:
    """Sort fiscal periods like 'Mar 2015', 'Jun 2020' by year and month."""
    month_order = {"Mar": 3, "Jun": 6, "Sep": 9, "Dec": 12}
    def key_func(p):
        parts = p.split()
        if len(parts) == 2:
            month, year = parts[0], int(parts[1])
            return (year, month_order.get(month, 0))
        return (0, 0)
    return sorted(periods, key=key_func)


def period_to_year(period: str) -> Optional[str]:
    """Extract year string fromperiod like 'Mar 2024'."""
    parts = period.split()
    if len(parts) == 2 and parts[0] in ["Mar", "Jun", "Sep", "Dec"]:
        return parts[1]
    return None


async def scrape_screener_complete(ticker: str) -> Dict[str, Any]:
    """Main orchestrator: Scrape Screener tables and compute historical ratios."""
    ticker = ticker.strip().upper()
    base_url = f"https://www.screener.in/company/{ticker}/"
    url = base_url + "consolidated/" if is_consolidated(ticker) else base_url

    print(f"[SCRAPER] Navigating to {url} ...")

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

        try:
            await page.wait_for_selector("ul#top-ratios", timeout=30000)
            await page.wait_for_timeout(1500)
        except Exception as exc:
            print(f"[WARNING] Top ratios selector wait warning for {ticker}: {exc}")

        html_before = await page.content()
        soup_before = BeautifulSoup(html_before, "html.parser")

        # ---- 1. Quarterly Results ----
        quarterly_main = {}
        q_section = soup_before.find("section", id="quarters")
        if q_section:
            q_table = q_section.find("table", class_="data-table")
            if q_table:
                quarterly_main = parse_financial_table(q_table)
                if "Raw PDF" in quarterly_main.get("rows", {}):
                    del quarterly_main["rows"]["Raw PDF"]

        # ---- 2. Profit & Loss ----
        pl_main = {}
        pl_section = soup_before.find("section", id="profit-loss")
        if pl_section:
            pl_table = pl_section.find("table", class_="data-table")
            if pl_table:
                pl_main = parse_financial_table(pl_table)

        # ---- 3. Balance Sheet ----
        bs = {}
        bs_section = soup_before.find("section", id="balance-sheet")
        if bs_section:
            bs_table = bs_section.find("table", class_="data-table")
            if bs_table:
                bs = parse_financial_table(bs_table)

        # ---- 4. Cash Flow ----
        cf = {}
        cf_section = soup_before.find("section", id="cash-flow")
        if cf_section:
            cf_table = cf_section.find("table", class_="data-table")
            if cf_table:
                cf = parse_financial_table(cf_table)

        # ---- 5. Key Ratios Table ----
        ratios_table = {}
        ratios_section = soup_before.find("section", id="ratios")
        if ratios_section:
            r_table = ratios_section.find("table", class_="data-table")
            if r_table:
                ratios_table = parse_financial_table(r_table)

        # ---- 6. Shareholding (Click Yearly Tab) ----
        shareholding = {}
        yearly_tab = await page.query_selector('button[data-tab-id="yearly-shp"]')
        if yearly_tab:
            try:
                await yearly_tab.click()
                await page.wait_for_timeout(1000)
            except Exception:
                pass

        html_final = await page.content()
        soup_final = BeautifulSoup(html_final, "html.parser")

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

    # ---- Fetch Historical Yearly Prices via yfinance ----
    yearly_prices = get_yfinance_prices(ticker)

    # ---- Extract P&L and Balance Sheet Series ----
    pl_rows = pl_main.get("rows", {})
    bs_rows = bs.get("rows", {})

    sales_series = pl_rows.get("Sales", {})
    net_profit_series = pl_rows.get("Net Profit", {})
    pbt_series = pl_rows.get("Profit before tax", {})
    eps_series = pl_rows.get("EPS in Rs", {})
    opm_series = pl_rows.get("OPM %", {})
    div_payout_series = pl_rows.get("Dividend Payout %", {})
    interest_series = pl_rows.get("Interest", {})
    depr_series = pl_rows.get("Depreciation", {})

    eq_cap_series = bs_rows.get("Equity Capital", {})
    reserves_series = bs_rows.get("Reserves", {})
    borrowings_series = bs_rows.get("Borrowings", {})

    # Compute Total Equity (Book Value)
    total_equity_series = {}
    for period in eq_cap_series:
        if period in reserves_series:
            eq_cap = eq_cap_series.get(period)
            res = reserves_series.get(period)
            if eq_cap is not None and res is not None:
                total_equity_series[period] = eq_cap + res

    # Extract ROCE from ratios
    roce_series = ratios_table.get("rows", {}).get("ROCE %", {})

    # Sort Fiscal Periods Chronologically
    all_periods = set(sales_series.keys()) | set(net_profit_series.keys()) | set(eps_series.keys())
    sorted_periods = sort_periods([p for p in all_periods if period_to_year(p)])

    historical_ratios = {}
    prev_sales = prev_profit = prev_eps = None

    for period in sorted_periods:
        year = period_to_year(period)
        if not year or year not in yearly_prices:
            continue

        sales = sales_series.get(period)
        net_profit = net_profit_series.get(period)
        pbt = pbt_series.get(period, 0.0)
        eps = eps_series.get(period)
        opm = opm_series.get(period)
        div_payout = div_payout_series.get(period)
        roce = roce_series.get(period)
        total_equity = total_equity_series.get(period)
        eq_cap = eq_cap_series.get(period)
        borrowings = borrowings_series.get(period, 0.0)
        interest = interest_series.get(period, 0.0)
        depr = depr_series.get(period, 0.0)
        price = yearly_prices.get(year)

        # Basic Ratios
        roe = round((net_profit / total_equity) * 100, ROUND_DECIMALS) if net_profit and total_equity and total_equity != 0 else None
        pe = round(price / eps, ROUND_DECIMALS) if price and eps and eps > 0 else None

        div_yield = None
        if div_payout is not None and eps and price and div_payout != 0:
            dps = (div_payout / 100) * eps
            if dps > 0:
                div_yield = round((dps / price) * 100, ROUND_DECIMALS)

        # YoY Growth Percentages
        sales_growth = round(((sales - prev_sales) / abs(prev_sales)) * 100, ROUND_DECIMALS) if prev_sales is not None and prev_sales != 0 else None
        profit_growth = round(((net_profit - prev_profit) / abs(prev_profit)) * 100, ROUND_DECIMALS) if prev_profit is not None and prev_profit != 0 else None
        eps_growth = round(((eps - prev_eps) / abs(prev_eps)) * 100, ROUND_DECIMALS) if prev_eps is not None and prev_eps != 0 else None

        # --- EXTENDED VALUATION METRICS ---
        npm_percent = round((net_profit / sales) * 100, ROUND_DECIMALS) if sales and sales != 0 and net_profit is not None else None

        mcap = None
        pb_ratio = None
        mcap_to_sales = None
        ev_ebitda = None

        # Calculate Implied Shares & Market Cap dynamically without assuming Face Value = 10
        implied_shares = None
        if net_profit and eps and eps > 0:
            implied_shares = net_profit / eps  # In Crores
        elif eq_cap and eq_cap > 0:
            implied_shares = eq_cap / 10.0     # Fallback

        if price and implied_shares and implied_shares > 0:
            mcap = price * implied_shares  # Market Cap in ₹ Crores

            if total_equity and total_equity > 0:
                pb_ratio = round(mcap / total_equity, ROUND_DECIMALS)

            if sales and sales > 0:
                mcap_to_sales = round(mcap / sales, ROUND_DECIMALS)

            tax = pbt - net_profit if pbt and net_profit else 0.0
            ebitda = (net_profit or 0.0) + tax + (interest or 0.0) + (depr or 0.0)
            ev = mcap + (borrowings or 0.0)  # Enterprise Value

            if ebitda and ebitda > 0:
                ev_ebitda = round(ev / ebitda, ROUND_DECIMALS)

        historical_ratios[year] = {
            "pe_ratio": pe,
            "pb_ratio": pb_ratio,
            "ev_ebitda": ev_ebitda,
            "mcap_to_sales": mcap_to_sales,
            "npm_percent": npm_percent,
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

        prev_sales, prev_profit, prev_eps = sales, net_profit, eps

    # Final Payload Structure
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
    out_file = OUTPUT_DIR / f"{ticker}_fundamentals.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[SUCCESS] Saved complete data to {out_file}")
    print(f"[METRICS] Historical ratios available for years: {list(data['core_metrics']['historical_ratios'].keys())}")


if __name__ == "__main__":
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE"
    asyncio.run(main(symbol.upper()))