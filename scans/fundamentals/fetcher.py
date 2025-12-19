"""
Data ingestion helpers covering Screener.in scraping.
Handles HTML parsing, strict URL logic, and financial table extraction.
"""
from __future__ import annotations

import asyncio
import sys
import json
import os
import random
import re
import requests
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Set

# Ensure Windows uses the Proactor event loop so subprocesses work
if sys.platform.startswith("win"):
    policy = asyncio.get_event_loop_policy()
    if not isinstance(policy, asyncio.WindowsProactorEventLoopPolicy):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            # Best-effort: if this fails, allow the import to proceed and
            # let runtime errors surface where appropriate.
            pass

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

# Import shared constants from utils
from .utils import USER_AGENTS

# ----------------------------------------------------------------------
# Key Mapping Constants
# ----------------------------------------------------------------------

SHAREHOLDING_ROWS = {
    "promoters": "promoters",
    "fiis": "fiis",
    "foreign_institutional_investors": "fiis",
    "diis": "diis",
    "domestic_institutional_investors": "diis",
    "government": "government",
    "public": "public",
    "no_of_shareholders": "no_of_shareholders",
    "number_of_shareholders": "no_of_shareholders",
    "pledged": "pledged_percent",
    "pledged_shares": "pledged_percent",
    "no_of_shares_pledged": "pledged_percent",
}

QUARTERLY_MAP = {
    "sales": "sales",
    "revenue": "sales",
    "interest_earned": "sales",  # For Banks
    "expenses": "expenses",
    "operating_profit": "operating_profit",
    "opm_percent": "opm_percent",
    "other_income": "other_income",
    "interest": "interest",
    "depreciation": "depreciation",
    "profit_before_tax": "pbt",
    "pbt": "pbt",
    "tax_percent": "tax_percent",
    "net_profit": "net_profit",
    "eps_in_rs": "eps",
    "eps": "eps",
}

PROFIT_LOSS_MAP = {
    "sales": "sales",
    "revenue": "sales",
    "interest_earned": "sales", # For Banks
    "expenses": "expenses",
    "operating_profit": "operating_profit",
    "opm_percent": "opm_percent",
    "net_profit": "net_profit",
    "eps_in_rs": "eps",
    "eps": "eps",
    "dividend_payout_percent": "dividend_payout_percent",
    "dividend_payout": "dividend_payout_percent",
}

BALANCE_SHEET_MAP = {
    "equity_capital": "equity_capital",
    "reserves": "reserves",
    "borrowings": "borrowings",
    "long_term_borrowings": "long_term_borrowings",
    "short_term_borrowings": "short_term_borrowings",
    "lease_liabilities": "lease_liabilities",
    "other_borrowings": "borrowings",
    "other_liabilities": "other_liabilities",
    "non_controlling_int": "non_controlling_interest",
    "trade_payables": "trade_payables",
    "other_liability_items": "other_liability_items",
    "current_liabilities": "current_liabilities",
    "total_liabilities": "total_liabilities",
    "fixed_assets": "fixed_assets",
    "land": "land",
    "building": "building",
    "plant_machinery": "plant_machinery",
    "ships_vessels": "ships_vessels",
    "equipments": "equipments",
    "furniture_n_fittings": "furniture_fittings",
    "vehicles": "vehicles",
    "intangible_assets": "intangible_assets",
    "other_fixed_assets": "other_fixed_assets",
    "gross_block": "gross_block",
    "accumulated_depreciation": "accumulated_depreciation",
    "cwip": "cwip",
    "capital_work_in_progress": "cwip",
    "investments": "investments",
    "current_assets": "current_assets",
    "other_assets": "other_assets",
    "other_asset_items": "other_asset_items",
    "total_assets": "total_assets",
    "inventories": "inventories",
    "trade_receivables": "trade_receivables",
    "cash_equivalents": "cash_equivalents",
    "cash_n_equivalents": "cash_equivalents",
    "loans_n_advances": "loans_advances",
    "loansadvances": "loans_advances",
    "advances": "loans_advances", # For Banks
    "deposits": "borrowings", # For Banks (Deposits are liabilities)
}

CASH_FLOW_MAP = {
    "cash_from_operating_activity": "cash_from_operating",
    "cash_from_investing_activity": "cash_from_investing",
    "cash_from_financing_activity": "cash_from_financing",
    "net_cash_flow": "net_cash_flow",
}

RATIOS_MAP = {
    "debtor_days": "debtor_days",
    "inventory_days": "inventory_days",
    "days_payable": "days_payable",
    "cash_conversion_cycle": "cash_conversion_cycle",
    "working_capital_days": "working_capital_days",
    "roce_percent": "roce_percent",
    "roce": "roce_percent",
}

TOP_RATIO_FIELDS = {
    "market_cap",
    "current_price",
    "high_price",
    "low_price",
    "stock_p_e",
    "stock_pe",
    "book_value",
    "dividend_yield",
    "roce",
    "roe",
    "face_value",
    "industry_pe",
}

MARKET_INDUSTRIES_URL = "https://www.screener.in/market/?sort=total_market_cap&order=desc"


class ScreenerScraper:
    base_url = "https://www.screener.in/company/{ticker}/"
    # Files are now relative to the package structure
    # source/ is at the project root
    source_dir = os.path.join(os.path.dirname(__file__), "..", "..", "source")
    
    ticker_map_file = os.path.join(source_dir, "ticker_mapping.json")
    consolidated_file = os.path.join(source_dir, "consolidated.json")
    non_consolidated_file = os.path.join(source_dir, "nonconsolidated.json")

    def __init__(
        self,
        *,
        session: Optional[requests.Session] = None,
        timeout: int = 30,
        use_playwright: bool = True,
        use_industry_pe_map: bool = True,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout
        self.use_playwright = use_playwright
        self.use_industry_pe_map = use_industry_pe_map
        self._industry_map: Dict[str, float] = {}
        
        # Ensure source directory exists
        os.makedirs(self.source_dir, exist_ok=True)
        
        self._ticker_map: Dict[str, str] = self._load_ticker_map()
        self._consolidated_tickers: Set[str] = self._load_list(self.consolidated_file)
        self._non_consolidated_tickers: Set[str] = self._load_list(self.non_consolidated_file)

    def _load_ticker_map(self) -> Dict[str, str]:
        """Load ticker mapping from cache file."""
        if os.path.exists(self.ticker_map_file):
            try:
                with open(self.ticker_map_file, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _load_list(self, filepath: str) -> Set[str]:
        """Load tickers from a JSON list file."""
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return {t.strip().upper() for t in data}
            except Exception:
                pass
        return set()

    def _save_ticker_map(self) -> None:
        """Save ticker mapping to cache file."""
        try:
            with open(self.ticker_map_file, 'w') as f:
                json.dump(self._ticker_map, f, indent=2)
        except Exception as e:
            print(f"Warning: Failed to save ticker mapping: {e}")

    def _get_ticker_variations(self, ticker: str) -> List[str]:
        """Generate possible ticker variations for a given ticker."""
        variations = [ticker]
        if ticker.endswith('S') and len(ticker) > 1:
            variations.append(ticker[:-1])
        if not ticker.endswith('S'):
            variations.append(ticker + 'S')
        for suffix in ['LTD', 'LIMITED']:
            if ticker.endswith(suffix):
                variations.append(ticker[:-len(suffix)])
        return variations

    def _ensure_industry_map(self) -> None:
        """Lazy load the Industry Median PE map."""
        if not self.use_industry_pe_map:
            return
        if not self._industry_map:
            try:
                self._industry_map = self.fetch_industry_pe_map()
            except Exception:
                pass # Silently fail if industry map is unreachable

    def fetch_industry_pe_map(self) -> Dict[str, float]:
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        response = self.session.get(MARKET_INDUSTRIES_URL, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        industry_map = {}
        
        rows = soup.select("table.data-table tbody tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 6:
                continue
            name_tag = cells[1].find("a")
            if not name_tag:
                continue
            industry_name = name_tag.get_text().strip()
            pe_text = cells[5].get_text().strip()
            pe_value = parse_numeric(pe_text)
            
            if industry_name:
                industry_map[industry_name] = pe_value if pe_value is not None else 0.0
                
        return industry_map

    # --------------------------------------------------------------
    # Public API
    # --------------------------------------------------------------
    def fetch_company_payload(self, ticker: str) -> Dict[str, Any]:
        """Fetch all fundamental data for a given ticker with strict URL logic."""
        self._ensure_industry_map()

        # Download based on strict rules (no auto-switching)
        html, final_url = self._download_company_page(ticker)
        soup = BeautifulSoup(html, "html.parser")

        payload = self._build_payload_from_soup(ticker, soup, final_url)
        
        if self.use_playwright:
            try:
                # Pass the exact URL we resolved to ensure consistency
                enhanced_balance_sheet = fetch_enhanced_balance_sheet(ticker, payload["metadata"]["source_url"])
            except Exception:
                enhanced_balance_sheet = {}
            if enhanced_balance_sheet:
                self._sanitize_balance_sheet(enhanced_balance_sheet)
                payload["balance_sheet"] = enhanced_balance_sheet

        return payload

    # --------------------------------------------------------------
    # HTTP helpers
    # --------------------------------------------------------------
    def _download_company_page(self, ticker: str) -> Tuple[str, str]:
        # Check if we have a cached mapping for this ticker
        actual_ticker = self._ticker_map.get(ticker, ticker)
        
        try:
            return self._fetch_strictly(actual_ticker)
        except requests.HTTPError as e:
            # Only try variations if 404 AND we used the original ticker (not a cached map)
            if e.response.status_code == 404 and actual_ticker == ticker:
                variations = self._get_ticker_variations(ticker)
                for variation in variations:
                    if variation == ticker:
                        continue
                    try:
                        html, url = self._fetch_strictly(variation)
                        # Success! Save this mapping
                        self._ticker_map[ticker] = variation
                        self._save_ticker_map()
                        print(f"✓ Found ticker mapping: {ticker} -> {variation}")
                        return html, url
                    except requests.HTTPError:
                        continue
            # Re-raise if no variations worked
            raise

    def _fetch_strictly(self, ticker: str) -> Tuple[str, str]:
        """
        Fetch data based strictly on the JSON lists.
        - If in non_consolidated.json -> Standalone URL only.
        - If in consolidated.json -> Consolidated URL only.
        - If in neither -> Default to Consolidated (as per Nifty 50 norm).
        """
        
        # 1. Determine Target URL
        if ticker in self._non_consolidated_tickers:
            # STRICT STANDALONE
            target_url = self.base_url.format(ticker=ticker)
            expected_consolidated = False
        else:
            # STRICT CONSOLIDATED (Default for Nifty 500)
            target_url = self.base_url.format(ticker=ticker) + "consolidated/"
            expected_consolidated = True

        # 2. Make Request
        response = self._request_with_headers(target_url)
        
        # 3. Handle Errors (Strict Mode: No Fallbacks)
        if response.status_code == 404:
            raise requests.HTTPError(f"404 Not Found at {target_url}", response=response)
        
        response.raise_for_status()

        # 4. Strict Validation of Redirections
        if expected_consolidated and "/consolidated/" not in response.url:
             # Screener redirected us to Standalone.
             # Strict check: If we ASKED for consolidated and got Standalone, 
             # it means consolidated data doesn't exist.
             if ticker in self._consolidated_tickers:
                 raise requests.HTTPError(
                     f"Strict Check Failed: Requested Consolidated data for {ticker}, but was redirected to Standalone URL: {response.url}", 
                     response=response
                 )
             else:
                 pass

        return response.text, response.url

    def _request_with_headers(self, url: str) -> requests.Response:
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        response = self.session.get(url, headers=headers, timeout=self.timeout, allow_redirects=True)
        return response

    # --------------------------------------------------------------
    # Parsing helpers (Standard)
    # --------------------------------------------------------------
    def _extract_industry_name(self, soup: BeautifulSoup) -> str:
        anchor = soup.select_one('a[title="Industry"]')
        if anchor:
            text = anchor.get_text(strip=True)
            if text: return text
        breadcrumbs = soup.select("div.breadcrumbs a")
        if breadcrumbs:
            text = breadcrumbs[-1].get_text().strip()
            if text: return text
        meta_tag = soup.select_one('meta[itemprop="industry"], meta[name="industry"]')
        if meta_tag:
            content = (meta_tag.get("content") or "").strip()
            if content: return content
        return "Unknown"

    def _parse_top_ratios(self, soup: BeautifulSoup) -> Dict[str, float]:
        data: Dict[str, float] = {}
        widget = soup.select_one("ul#top-ratios")
        if not widget: return data
        for item in widget.select("li"):
            name_el = item.select_one("span.name")
            value_el = item.select_one("span.value") or item.select_one("span.number")
            if not name_el or not value_el: continue
            key = slugify(name_el.get_text())
            if key == "high_low":
                high, low = parse_high_low_pair(value_el.get_text())
                if high: data["high_price"] = high
                if low: data["low_price"] = low
                continue
            if key in TOP_RATIO_FIELDS or key.replace("_", "") in {k.replace("_", "") for k in TOP_RATIO_FIELDS}:
                value = parse_numeric(value_el.get_text())
                if value is not None: data[key] = value
        return data

    def _parse_financial_table(self, soup: BeautifulSoup, section_id: str, field_map: Dict[str, str]) -> Dict[str, Dict[str, float]]:
        table = soup.select_one(f"section#{section_id} table.data-table")
        if not table: return {}
        header_cells = table.select("thead th")
        headers: List[str] = []
        for th in header_cells[1:]:
            header_text = clean_header(th.get_text())
            if header_text: headers.append(header_text)
        result: Dict[str, Dict[str, float]] = {h: {} for h in headers}
        for row in table.select("tbody tr"):
            cells = row.select("td")
            if len(cells) < 2: continue
            label = slugify(cells[0].get_text())
            metric_key = field_map.get(label)
            if not metric_key:
                for k, v in field_map.items():
                    if k in label:
                        metric_key = v
                        break
            if not metric_key: continue
            for header, cell in zip(headers, cells[1:]):
                value = parse_numeric(cell.get_text())
                if value is None: continue
                result.setdefault(header, {})[metric_key] = value
        return {period: fields for period, fields in result.items() if fields}

    def _parse_shareholding(self, soup: BeautifulSoup) -> Tuple[Dict[str, Dict[str, Dict[str, float]]], bool]:
        section = soup.select_one("section#shareholding")
        if not section: return {"quarterly": {}, "yearly": {}}, False
        quarterly, pledge_q = self._parse_shareholding_table(section, "div#quarterly-shp")
        yearly, pledge_y = self._parse_shareholding_table(section, "div#yearly-shp")
        pledge_found = pledge_q or pledge_y
        if not pledge_found:
            for bucket in (quarterly, yearly):
                for period in bucket.values():
                    period.setdefault("pledged_percent", 0.0)
        return {"quarterly": quarterly, "yearly": yearly}, pledge_found

    def _parse_shareholding_table(self, section: BeautifulSoup, wrapper_selector: str) -> Tuple[Dict[str, Dict[str, float]], bool]:
        wrapper = section.select_one(f"{wrapper_selector} table.data-table")
        if not wrapper: return {}, False
        headers = []
        for th in wrapper.select("thead th")[1:]:
            header_text = clean_header(th.get_text())
            if header_text: headers.append(header_text)
        dataset: Dict[str, Dict[str, float]] = {h: {} for h in headers}
        pledge_found = False
        for row in wrapper.select("tbody tr"):
            cells = row.select("td")
            if len(cells) < 2: continue
            label = slugify(cells[0].get_text())
            mapped = SHAREHOLDING_ROWS.get(label)
            if not mapped: continue
            if mapped == "pledged_percent": pledge_found = True
            for header, cell in zip(headers, cells[1:]):
                value = parse_numeric(cell.get_text())
                if value is None: continue
                dataset.setdefault(header, {})[mapped] = value
        return {period: fields for period, fields in dataset.items() if fields}, pledge_found

    def _build_payload_from_soup(self, ticker: str, soup: BeautifulSoup, final_url: str) -> Dict[str, Any]:
        industry = self._extract_industry_name(soup)
        industry_pe = self._industry_map.get(industry) if self.use_industry_pe_map else None

        top_ratios = self._parse_top_ratios(soup)
        if "industry_pe" not in top_ratios and industry_pe is not None:
            top_ratios["industry_pe"] = industry_pe

        quarterly = self._parse_financial_table(soup, "quarters", QUARTERLY_MAP)
        profit_loss = self._parse_financial_table(soup, "profit-loss", PROFIT_LOSS_MAP)
        balance_sheet = self._parse_financial_table(soup, "balance-sheet", BALANCE_SHEET_MAP)
        self._sanitize_balance_sheet(balance_sheet)
        cash_flow = self._parse_financial_table(soup, "cash-flow", CASH_FLOW_MAP)
        ratios = self._parse_financial_table(soup, "ratios", RATIOS_MAP)
        shareholding, pledge_found = self._parse_shareholding(soup)

        metadata = {
            "source_url": final_url,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "pledge_data_missing": not pledge_found,
            "industry": industry,
            "reporting": "consolidated" if "/consolidated/" in (final_url or "") else "standalone",
        }

        payload = {
            "metadata": metadata,
            "quarterly_results": quarterly,
            "profit_loss_annual": profit_loss,
            "balance_sheet": balance_sheet,
            "cash_flow": cash_flow,
            "ratios": ratios,
            "shareholding": shareholding,
            "ticker": ticker,
        }
        payload.update(self._extract_top_ratio_fields(top_ratios))
        return payload

    def _sanitize_balance_sheet(self, balance_sheet: Dict[str, Dict[str, float]]) -> None:
        for data in balance_sheet.values():
            if "current_assets" not in data:
                comps = [data.get(key) for key in ("inventories", "trade_receivables", "cash_equivalents", "loans_advances") if data.get(key) is not None]
                if comps:
                    total = sum(comps)
                    if data.get("other_asset_items") is not None:
                        total += data.get("other_asset_items")
                    data["current_assets"] = total
            if "current_liabilities" not in data:
                comps = [data.get(key) for key in ("trade_payables", "short_term_borrowings") if data.get(key) is not None]
                if comps:
                    total = sum(comps)
                    if data.get("other_liability_items") is not None:
                        total += data.get("other_liability_items")
                    data["current_liabilities"] = total

    def _extract_top_ratio_fields(self, ratios: Dict[str, float]) -> Dict[str, float]:
        mapped = {}
        key_map = {"stock_p_e": "stock_pe", "stock_pe": "stock_pe", "industry_pe": "industry_pe"}
        for key in TOP_RATIO_FIELDS:
            val = ratios.get(key)
            if val is not None:
                target = key_map.get(key, key)
                mapped[target] = val
                continue
            alt_key = key.replace("_", "")
            for r_key, r_val in ratios.items():
                if r_key.replace("_", "") == alt_key:
                    target = key_map.get(key, key)
                    mapped[target] = r_val
                    break
        return mapped

# ----------------------------------------------------------------------
# Utility helpers
# ----------------------------------------------------------------------

def clean_header(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()

def slugify(value: str) -> str:
    value = (value or "").lower()
    value = value.replace("+", " ")
    value = value.replace("%", " percent")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip().replace(" ", "_")

def parse_numeric(value: str) -> Optional[float]:
    if value is None: return None
    text = value.strip()
    if not text or text in {"-", "--"}: return None
    text = text.replace(",", "").replace("₹", "").replace("Rs.", "").replace("Cr.", "").replace("Cr", "").replace("crores", "")
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace("%", "").replace(" ", "")
    if not text: return None
    try:
        number = float(text)
        return -number if negative else number
    except ValueError: return None

def parse_high_low_pair(value: str) -> Tuple[Optional[float], Optional[float]]:
    if not value: return None, None
    parts = value.split("/")
    if len(parts) != 2:
        numeric = parse_numeric(value)
        return numeric, None
    return parse_numeric(parts[0]), parse_numeric(parts[1])

# --------------------------------------------------------------
# Enhanced Playwright-based scraping for nested balance sheet items
# --------------------------------------------------------------

def _normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", text.lower().replace(" ", "_").replace("-", "_").replace("&", "n"))

def _parse_period(text: str) -> Optional[str]:
    text = text.strip()
    match = re.match(r"^([A-Za-z]{3})\s+(\d{4})$", text)
    if match: return text
    return None

async def _expand_balance_sheet_sections(page: Page) -> None:
    try:
        expand_buttons = await page.query_selector_all('section#balance-sheet button.button-plain')
        for button in expand_buttons:
            try:
                if '+' in await button.inner_html():
                    await button.click()
                    await page.wait_for_timeout(200)
            except Exception: continue
    except Exception: pass

async def scrape_balance_sheet_with_playwright(ticker: str, target_url: str = None) -> Dict[str, Dict[str, float]]:
    # Use target_url strictly
    url = target_url or f"https://www.screener.in/company/{ticker}/consolidated/"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=random.choice(USER_AGENTS), viewport={"width": 1920, "height": 1080})
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try: await page.wait_for_selector('section#balance-sheet', timeout=5000)
            except PlaywrightTimeout: return {}
            await _expand_balance_sheet_sections(page)
            balance_sheet: Dict[str, Dict[str, float]] = {}
            section = await page.query_selector('section#balance-sheet')
            if not section: return {}
            table = await section.query_selector('table')
            if not table: return {}
            header_row = await table.query_selector('thead tr')
            if not header_row: return {}
            headers = await header_row.query_selector_all('th')
            periods = []
            for i, th in enumerate(headers):
                if i == 0: continue
                period = _parse_period((await th.inner_text()).strip())
                if period:
                    periods.append(period)
                    balance_sheet[period] = {}
            tbody = await table.query_selector('tbody')
            if not tbody: return {}
            rows = await tbody.query_selector_all('tr')
            for row in rows:
                cells = await row.query_selector_all('td')
                if len(cells) < 2: continue
                label = (await cells[0].inner_text()).strip().replace('+', '').replace('−', '').strip()
                normalized = _normalize_key(label)
                field_name = BALANCE_SHEET_MAP.get(normalized)
                if not field_name:
                    for key, value in BALANCE_SHEET_MAP.items():
                        if key in normalized or normalized in key:
                            field_name = value
                            break
                if not field_name: continue
                for i, period in enumerate(periods):
                    if i + 1 >= len(cells): break
                    value = parse_numeric((await cells[i + 1].inner_text()).strip())
                    if value is not None: balance_sheet[period][field_name] = value
            for period, data in balance_sheet.items():
                if "current_assets" not in data:
                    comps = [data.get(k) for k in ("inventories", "trade_receivables", "cash_equivalents", "loans_advances") if data.get(k) is not None]
                    if comps:
                        val = sum(comps)
                        if data.get("other_asset_items"): val += data["other_asset_items"]
                        data["current_assets"] = val
                if "current_liabilities" not in data:
                    comps = [data.get(k) for k in ("trade_payables", "short_term_borrowings") if data.get(k) is not None]
                    if comps:
                        val = sum(comps)
                        if data.get("other_liability_items"): val += data["other_liability_items"]
                        data["current_liabilities"] = val
            return balance_sheet
        except (PlaywrightTimeout, Exception): return {}
        finally: await browser.close()

def fetch_enhanced_balance_sheet(ticker: str, target_url: str = None) -> Dict[str, Dict[str, float]]:
    return asyncio.run(scrape_balance_sheet_with_playwright(ticker, target_url))