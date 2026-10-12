# backend/scans/fundamental_scraper.py

"""
AlphaQuant Universal Screener.in Scraper – Pure Data Extraction Engine.
- Zero Keyword Hunting & Zero Mapping: Ingests all tables, rows, and headers exactly as they appear in the DOM.
- Strict Numeric Extraction: Cleans all commas, ₹, Cr., Mn, and text artifacts.
- Enforces strict precision: Rounds strictly to 2 decimal places.
- NO DERIVATIVES: Ignores Screener's Compounded Growth tables entirely.
- All CAGRs, Averages, and historical depth metrics are delegated to metrics_engine.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup, Tag
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("FundamentalScraper")

# ----------------------------------------------------------------------
# Configuration & Paths
# ----------------------------------------------------------------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output" / "data"
SOURCE_DIR = BASE_DIR / "source"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CONSOLIDATED_FILE = SOURCE_DIR / "consolidated.json"
NONCONSOLIDATED_FILE = SOURCE_DIR / "nonconsolidated.json"

ROUND_DECIMALS = 2


def is_consolidated(ticker: str) -> bool:
    try:
        with open(CONSOLIDATED_FILE, "r", encoding="utf-8") as f:
            cons = set(json.load(f))
        with open(NONCONSOLIDATED_FILE, "r", encoding="utf-8") as f:
            noncons = set(json.load(f))
        return ticker in cons and ticker not in noncons
    except Exception:
        return False


def clean_cell_value(text: str, round_dp: int = ROUND_DECIMALS) -> Optional[float]:
    """
    STRICT NUMERIC PARSER:
    - Removes all characters EXCEPT digits and decimals (removes commas, Rs, Cr, etc.).
    - Strictly preserves absent/dash/empty data as None (never defaults to 0.0).
    - Correctly parses parenthesized negative accounting entries: (1,234.5) -> -1234.5.
    - Rounds to 2 decimals.
    """
    if not text:
        return None
    raw = text.strip()
    if raw in {"", "-", "—", "na", "N/A", "null", "None"}:
        return None

    is_negative = False
    if raw.startswith("(") and raw.endswith(")"):
        is_negative = True
        raw = raw[1:-1]
    elif raw.startswith("-"):
        is_negative = True
        raw = raw[1:]

    cleaned = re.sub(r'[^\d.]', '', raw)
    if not cleaned or cleaned == '.':
        return None

    try:
        val = float(cleaned)
        if is_negative:
            val = -val
        return round(val, round_dp)
    except ValueError:
        return None


def parse_underivable_top_ratios(soup: BeautifulSoup) -> Dict[str, Any]:
    """
    Extracts ONLY metrics from the top card that cannot be derived from the raw P&L
    (e.g., Face Value, Industry PE). 
    P/E, ROE, ROCE, Market Cap are ignored as they will be computed mathematically.
    """
    ratios: Dict[str, Any] = {}
    ratio_card = soup.select_one("ul#top-ratios, div.company-ratios ul")
    if not ratio_card:
        return ratios

    items = ratio_card.find_all("li")
    for item in items:
        name_tag = item.select_one("span.name")
        val_tag = item.select_one("span.value")
        if not name_tag or not val_tag:
            continue

        raw_name = name_tag.get_text(strip=True)
        raw_val = val_tag.get_text(strip=True)

        if "/" in raw_val and ("high" in raw_name.lower() or "low" in raw_name.lower()):
            parts = [p.strip() for p in raw_val.split("/")]
            high_val = clean_cell_value(parts[0])
            low_val = clean_cell_value(parts[1]) if len(parts) > 1 else None
            ratios["52w_high"] = high_val
            ratios["52w_low"] = low_val
            ratios["High / Low"] = f"{high_val} / {low_val}"
            continue

        # We only capture specific underivable metrics to prevent bloat
        target_keys = {"Market Cap", "Current Price", "Face Value", "Book Value"}
        if any(t in raw_name for t in target_keys):
            ratios[raw_name] = clean_cell_value(raw_val)

    return ratios


def parse_financial_table(table: Tag) -> Dict[str, Any]:
    """
    Dynamically parses financial tables.
    Extracts row headers exactly as provided by the DOM, without any mapping.
    """
    if not table:
        return {"headers": [], "rows": {}}

    rows = table.find_all("tr")
    if not rows or len(rows) < 2:
        return {"headers": [], "rows": {}}

    header_cells = rows[0].find_all(["th", "td"])
    headers = [cell.get_text(strip=True) for cell in header_cells][1:]
    sanitized_headers = [h for h in headers if h]

    data: Dict[str, Dict[str, Optional[float]]] = {}
    rowspan_buffer: Dict[int, str] = {}

    for row_idx, row in enumerate(rows[1:], start=1):
        cells = row.find_all(["td", "th"])
        if not cells:
            continue

        first_cell = cells[0]
        metric = first_cell.get_text(strip=True)
        metric = re.sub(r"\s*\+\s*$", "", metric).strip()

        if not metric and row_idx in rowspan_buffer:
            metric = rowspan_buffer[row_idx]
        elif metric and first_cell.get("rowspan"):
            span_count = int(first_cell.get("rowspan", 1))
            for offset in range(1, span_count):
                rowspan_buffer[row_idx + offset] = metric

        if not metric or metric.lower() in {"raw pdf", "source"}:
            continue

        row_values: Dict[str, Optional[float]] = {}
        for col_idx, cell in enumerate(cells[1:]):
            if col_idx < len(sanitized_headers):
                period = sanitized_headers[col_idx]
                row_values[period] = clean_cell_value(cell.get_text(strip=True))

        # If a key already exists, merge/update it instead of overwriting
        if metric in data:
            data[metric].update(row_values)
        else:
            data[metric] = row_values

    return {"headers": sanitized_headers, "rows": data}


def parse_peers_and_industry(soup: BeautifulSoup, company_symbol: str) -> Dict[str, Any]:
    """Dynamically extracts peer metrics, sector taxonomies, and benchmarks."""
    industry_info: Dict[str, str] = {}
    benchmarks: List[Dict[str, str]] = []
    peers: List[Dict[str, Any]] = []
    peers_clean: List[Dict[str, str]] = []

    for link in soup.select('#peers a[href*="/market/"]'):
        href = link.get("href", "")
        text = link.get_text(strip=True)
        match = re.search(r'IN(\d+)', href)
        if match:
            code_len = len(match.group(1))
            if code_len == 2: industry_info["sector"] = text
            elif code_len == 4: industry_info["industry"] = text
            elif code_len == 6: industry_info["industry_group"] = text
            elif code_len >= 8: industry_info["sub_industry"] = text
        else:
            if "sector" not in industry_info: industry_info["sector"] = text
            elif "industry" not in industry_info: industry_info["industry"] = text
            else: industry_info["sub_industry"] = text

    for link in soup.select('#benchmarks a.tag'):
        benchmarks.append({"name": link.get_text(strip=True), "url": link.get("href", "")})

    peers_section = soup.select_one('#peers')
    if peers_section:
        peers_table = peers_section.select_one('table.data-table') or peers_section.find('table')
        if peers_table:
            rows = peers_table.find_all("tr")
            if rows:
                headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
                for row in rows[1:]:
                    cells = row.find_all(["td", "th"])
                    if not cells: continue

                    company_link = None
                    for cell in cells:
                        a_tag = cell.find("a")
                        if a_tag and "/company/" in a_tag.get("href", ""):
                            company_link = a_tag
                            break

                    if not company_link: continue

                    company_name = company_link.get_text(strip=True)
                    company_url = company_link.get("href", "")
                    symbol = company_url.split("/company/")[-1].split("/")[0] if "/company/" in company_url else ""

                    metrics: Dict[str, Any] = {}
                    for i, cell in enumerate(cells[1:], 1):
                        if i < len(headers):
                            metrics[headers[i]] = clean_cell_value(cell.get_text(strip=True))

                    peers.append({
                        "name": company_name,
                        "symbol": symbol,
                        "url": company_url,
                        "metrics": metrics
                    })
                    peers_clean.append({"name": company_name, "symbol": symbol})

    return {
        "company_symbol": company_symbol,
        "industry_info": industry_info,
        "benchmarks": benchmarks,
        "peers": peers_clean,
        "peers_detailed": peers,
        "peer_count": len(peers_clean)
    }


def get_yfinance_prices(ticker: str) -> Dict[str, float]:
    """Fetches real historical fiscal year-end prices dynamically across the full available depth."""
    symbol = f"{ticker}.NS" if not ticker.endswith((".NS", ".BO")) else ticker
    stock = yf.Ticker(symbol)

    end_date = datetime.now()
    start_date = end_date - timedelta(days=15 * 365) # 15-year lookback to cover absolute MAX requests
    
    try:
        price_data = stock.history(start=start_date, end=end_date, interval="1d")
        if price_data.empty:
            return {}

        if price_data.index.tz is not None:
            price_data.index = price_data.index.tz_localize(None)

        yearly_prices: Dict[str, float] = {}
        for year in range(start_date.year, end_date.year + 1):
            march_data = price_data[(price_data.index.year == year) & (price_data.index.month == 3)]
            if not march_data.empty:
                yearly_prices[str(year)] = round(float(march_data['Close'].iloc[-1]), ROUND_DECIMALS)
            else:
                year_data = price_data[price_data.index.year == year]
                if not year_data.empty:
                    yearly_prices[str(year)] = round(float(year_data['Close'].iloc[-1]), ROUND_DECIMALS)

        return yearly_prices
    except Exception as e:
        logger.debug(f"yfinance price acquisition bypassed for {ticker}: {e}")
        return {}


async def scrape_screener_complete(ticker: str) -> Dict[str, Any]:
    ticker = ticker.strip().upper()
    base_url = f"https://www.screener.in/company/{ticker}/"
    url = base_url + "consolidated/" if is_consolidated(ticker) else base_url

    logger.info(f"Navigating to {url} ...")

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
            await page.wait_for_selector("ul#top-ratios, section#quarters", timeout=30000)
            await page.wait_for_timeout(1000)
        except Exception as exc:
            logger.warning(f"Selector wait warning for {ticker}: {exc}")

        html_initial = await page.content()
        soup_initial = BeautifulSoup(html_initial, "html.parser")

        # 1. Underivable Top Ratios
        top_ratios = parse_underivable_top_ratios(soup_initial)

        # 2. Peers & Industry Hierarchy
        peers_data = parse_peers_and_industry(soup_initial, ticker)

        # 3. Financial Tables (Direct Extraction - No Terminology Map)
        quarterly_data = {}
        q_sec = soup_initial.find("section", id="quarters")
        if q_sec:
            q_tbl = q_sec.find("table", class_="data-table")
            if q_tbl: quarterly_data = parse_financial_table(q_tbl)

        pl_data = {}
        pl_sec = soup_initial.find("section", id="profit-loss")
        if pl_sec:
            pl_tbl = pl_sec.find("table", class_="data-table")
            if pl_tbl: pl_data = parse_financial_table(pl_tbl)

        bs_data = {}
        bs_sec = soup_initial.find("section", id="balance-sheet")
        if bs_sec:
            bs_tbl = bs_sec.find("table", class_="data-table")
            if bs_tbl: bs_data = parse_financial_table(bs_tbl)

        cf_data = {}
        cf_sec = soup_initial.find("section", id="cash-flow")
        if cf_sec:
            cf_tbl = cf_sec.find("table", class_="data-table")
            if cf_tbl: cf_data = parse_financial_table(cf_tbl)

        ratios_data = {}
        r_sec = soup_initial.find("section", id="ratios")
        if r_sec:
            r_tbl = r_sec.find("table", class_="data-table")
            if r_tbl: ratios_data = parse_financial_table(r_tbl)

        # 4. Shareholding Patterns
        shareholding: Dict[str, Any] = {}
        yearly_btn = await page.query_selector('button[data-tab-id="yearly-shp"]')
        if yearly_btn:
            try:
                await yearly_btn.click()
                await page.wait_for_timeout(800)
            except Exception:
                pass

        html_final = await page.content()
        soup_final = BeautifulSoup(html_final, "html.parser")

        sh_sec = soup_final.find("section", id="shareholding")
        if sh_sec:
            q_div = sh_sec.find("div", id="quarterly-shp")
            if q_div:
                q_tbl = q_div.find("table", class_="data-table")
                if q_tbl: shareholding["quarterly"] = parse_financial_table(q_tbl)

            y_div = sh_sec.find("div", id="yearly-shp")
            if y_div:
                y_tbl = y_div.find("table", class_="data-table")
                if y_tbl: shareholding["yearly"] = parse_financial_table(y_tbl)

        await browser.close()

    yearly_prices = get_yfinance_prices(ticker)

    result = {
        "ticker": ticker,
        "scraped_at": datetime.now().isoformat(),
        "top_ratios": top_ratios, # Lean payload
        "industry_info": peers_data.get("industry_info", {}),
        "benchmarks": peers_data.get("benchmarks", []),
        "peers": peers_data.get("peers", []),
        "peers_detailed": peers_data.get("peers_detailed", []),
        "peer_count": peers_data.get("peer_count", 0),
        "historical_prices": yearly_prices,
        "raw_financials": {
            "quarterly_results": quarterly_data,
            "profit_loss_annual": pl_data,
            "balance_sheet": bs_data,
            "cash_flow": cf_data,
            "ratios": ratios_data,
            "shareholding": shareholding,
        }
    }

    peers_file = OUTPUT_DIR / f"{ticker}_peers.json"
    with open(peers_file, "w", encoding="utf-8") as f:
        json.dump(peers_data, f, indent=2, ensure_ascii=False)

    return result


async def main(ticker: str):
    data = await scrape_screener_complete(ticker)
    out_file = OUTPUT_DIR / f"{ticker}_fundamentals.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved optimized dynamic financial data to {out_file}")


if __name__ == "__main__":
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE"
    asyncio.run(main(symbol.upper()))