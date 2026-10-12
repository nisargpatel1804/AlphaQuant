# backend/auxiliary_scrapers.py

"""
AlphaQuant Auxiliary Scrapers (Consolidated)
Merges global market-level data fetching into a single unified file:
1. ScreenerIndustryScraper: Global Industry Median P/E and ticker mapping.
2. MoneyControlSectorScraper: Sector Advance/Decline, Trend, and MCap changes.
   (Includes the strict Screener -> MoneyControl Crosswalk).
3. MoneyControlSeasonalityScraper: Monthly return probabilities and trends.
4. TickerTapeMMIScraper: Global Market Mood Index (Fear/Greed).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup, Tag
from playwright.async_api import async_playwright

# ----------------------------------------------------------------------
# Configuration & Paths
# ----------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
SOURCE_DIR = BASE_DIR / "source"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
STOCK_LINKS_PATH = SOURCE_DIR / "stock_links.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("AuxiliaryScrapers")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

# ==============================================================================
# 1. SCREENER INDUSTRY SCRAPER
# ==============================================================================
class ScreenerIndustryScraper:
    MARKET_INDUSTRIES_URL = "https://www.screener.in/markets/"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENTS[0]})

    @staticmethod
    def _normalize_number(text: str) -> Optional[float]:
        if not text: return None
        cleaned = text.replace(",", "").replace("×", "").replace("x", "").replace("%", "").strip()
        if cleaned in {"", "-", "—", "na", "n/a", "none"}: return None
        try: value = float(cleaned)
        except Exception: return None
        return value if value > 0 else None

    @staticmethod
    def _extract_industry_pe_from_html(html: str) -> Dict[str, float]:
        pe_map: Dict[str, float] = {}
        soup = BeautifulSoup(html, "html.parser")
        table = soup.select_one("table.data-table")
        if not table: return pe_map

        def _cell_text(cell) -> str:
            try: return cell.get_text(" ", strip=True)
            except Exception: return ""

        header_row = None
        thead = table.find("thead")
        if thead: header_row = thead.find("tr")
        if header_row is None:
            for tr in table.select("tr"):
                row_text = _cell_text(tr).lower()
                if "median" in row_text and ("p/e" in row_text or "pe" in row_text):
                    header_row = tr; break
        if header_row is None:
            for tr in table.select("tr"):
                ths = tr.find_all("th")
                if ths and any(_cell_text(th) for th in ths):
                    header_row = tr; break

        header_cells = header_row.find_all(["th", "td"]) if header_row else []
        headers = [_cell_text(c).lower() for c in header_cells]

        pe_idx = None
        for i, header in enumerate(headers):
            normalized = " ".join(header.split())
            if ("p/e" in normalized or normalized in {"pe", "p e"}) and "median" in normalized:
                pe_idx = i; break
        if pe_idx is None:
            for i, header in enumerate(headers):
                normalized = " ".join(header.split())
                if "p/e" in normalized or normalized in {"pe", "p e"}:
                    pe_idx = i; break

        for row in table.select("tr"):
            if row is header_row: continue
            cols = row.find_all("td")
            if not cols: continue

            name_el = row.select_one('a[title="Industry"], a[href*="/market/"]')
            industry = (name_el.get_text(" ", strip=True) if name_el else (cols[1].get_text(" ", strip=True) if len(cols) > 1 else cols[0].get_text(" ", strip=True))).strip()
            if not industry: continue

            value_text = None
            if pe_idx is not None and pe_idx < len(cols): value_text = cols[pe_idx].get_text(strip=True)
            else:
                if len(cols) >= 6: value_text = cols[5].get_text(strip=True)
                else:
                    for c in cols[3:]:
                        t = c.get_text(" ", strip=True)
                        if t and any(ch.isdigit() for ch in t) and len(t) <= 12:
                            value_text = t; break

            pe = ScreenerIndustryScraper._normalize_number(value_text or "")
            if pe is not None: pe_map[industry] = pe

        return pe_map

    async def _fetch_market_html_playwright(self, url: str) -> Optional[str]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(user_agent=random.choice(USER_AGENTS))
                page = await context.new_page()
                await page.goto(url, wait_until="networkidle", timeout=60000)
                try: await page.wait_for_selector("table.data-table", timeout=15000)
                except Exception: pass
                await page.wait_for_timeout(750)
                return await page.content()
            finally:
                await browser.close()

    def fetch_industry_pe_map(self) -> Dict[str, float]:
        try:
            self.session.headers.update({"User-Agent": random.choice(USER_AGENTS)})
            response = self.session.get(self.MARKET_INDUSTRIES_URL, timeout=25)
            response.raise_for_status()
            pe_map = self._extract_industry_pe_from_html(response.text)
            if pe_map: return pe_map
        except Exception as e: logger.warning(f"Static industry PE scrape failed: {e}")

        try:
            html = asyncio.run(self._fetch_market_html_playwright(self.MARKET_INDUSTRIES_URL))
            return self._extract_industry_pe_from_html(html) if html else {}
        except Exception as e:
            logger.warning(f"Playwright industry PE scrape failed: {e}")
            return {}

    def fetch_all_industries(self) -> Dict[str, str]:
        industries = {}
        try:
            response = self.session.get(self.MARKET_INDUSTRIES_URL, timeout=20)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            links = soup.select("div.sidebar a") + soup.select("a[href*='/market/']")
            for link in links:
                text = link.get_text(strip=True)
                href = link.get("href", "")
                if "/market/" in href and text:
                    if text.lower() in ["screens", "tools", "feed", "premium", "home", "market"]: continue
                    if "sort=" in href: continue
                    full_url = "https://www.screener.in" + href if href.startswith("/") else href
                    if text.strip() not in industries and len(text.strip()) > 2:
                        industries[text.strip()] = full_url
            return industries
        except Exception as e:
            logger.error(f"Error fetching market page: {e}")
            return {}

    def fetch_tickers_from_industry_page(self, url: str) -> Set[str]:
        tickers, page_num, seen = set(), 1, set()
        base_url = f"{url}{'&' if '?' in url else '?'}sort=market+capitalization&order=desc"

        while True:
            try:
                response = self.session.get(f"{base_url}&page={page_num}", timeout=15)
                if response.status_code == 404: break
                soup = BeautifulSoup(response.text, "html.parser")
                rows = soup.select("table.data-table tbody tr")
                if not rows: break
                current_batch = set()
                for row in rows:
                    a_tag = row.select_one("a[href*='/company/']")
                    if a_tag:
                        parts = a_tag.get("href", "").strip("/").split("/")
                        if len(parts) >= 2: current_batch.add(parts[1].strip().upper())
                if not current_batch or current_batch == seen: break
                tickers.update(current_batch)
                seen = current_batch
                if not soup.select_one("div.pagination") or page_num > 20: break
                page_num += 1
                time.sleep(0.5)
            except Exception: break
        return tickers

# ==============================================================================
# 2. MONEYCONTROL SECTOR SCRAPER & DETERMINISTIC CROSSWALK
# ==============================================================================

INDUSTRY_TO_SECTOR_CROSSWALK = {
    "Pharmaceuticals": "Healthcare", "Industrial Products": "Capital Goods", "Auto Components & Equipments": "Automobile & Ancillaries",
    "Civil Construction": "Infrastructure", "Other Textile Products": "Textiles", "Non Banking Financial Company (NBFC)": "Finance",
    "Residential, Commercial Projects": "Real Estate", "Specialty Chemicals": "Chemicals", "Iron & Steel Products": "Metals & Mining",
    "Computers - Software & Consulting": "Software & IT Services", "IT Enabled Services": "Software & IT Services", "Diversified Commercial Services": "Miscellaneous",
    "Other Electrical Equipment": "Electricals", "Gems, Jewellery And Watches": "Diamond & Jewellery", "Trading & Distributors": "Trading",
    "Heavy Electrical Equipment": "Electricals", "Packaging": "Containers & Packaging", "Logistics Solution Provider": "Logistics",
    "Hotels & Resorts": "Hospitality", "Commodity Chemicals": "Chemicals", "Investment Company": "Finance", "Other Agricultural Products": "Agri",
    "Garments & Apparels": "Textiles", "Plastic Products - Industrial": "Plastic Products", "Aerospace & Defense": "Capital Goods",
    "Cement & Cement Products": "Construction Materials", "Other Industrial Products": "Capital Goods", "Stockbroking & Allied": "Finance",
    "Sugar": "FMCG", "Other Financial Services": "Finance", "Hospital": "Healthcare", "Other Food Products": "FMCG", "Packaged Foods": "FMCG",
    "Power Generation": "Power", "Software Products": "Software & IT Services", "Paper & Paper Products": "Paper", "Pesticides & Agrochemicals": "Chemicals",
    "Breweries & Distilleries": "Alcohol", "Household Appliances": "Consumer Durables", "Speciality Retail": "Retailing", "Cables - Electricals": "Electricals",
    "Castings & Forgings": "Capital Goods", "Private Sector Bank": "Banks", "Fertilizers": "Chemicals", "Aluminium, Copper & Zinc Products": "Metals & Mining",
    "Edible Oil": "FMCG", "Tea & Coffee": "FMCG", "Consumer Electronics": "Consumer Durables", "Medical Equipment & Supplies": "Healthcare",
    "Computers Hardware & Equipments": "Software & IT Services", "Healthcare Service Provider": "Healthcare", "Compressors, Pumps & Diesel Engines": "Capital Goods",
    "Dyes And Pigments": "Chemicals", "E-Retail/ E-Commerce": "Retailing", "Education": "Miscellaneous", "Holding Company": "Finance",
    "Housing Finance Company": "Finance", "Iron & Steel": "Metals & Mining", "Personal Care": "FMCG", "Road AssetsToll, Annuity, Hybrid-Annuity": "Infrastructure",
    "Tyres & Rubber Products": "Automobile & Ancillaries", "Film Production, Distribution & Exhibition": "Media & Entertainment", "Other Construction Materials": "Construction Materials",
    "Petrochemicals": "Chemicals", "Electrodes & Refractories": "Capital Goods", "Financial Technology (Fintech)": "Finance", "Industrial Minerals": "Metals & Mining",
    "Media & Entertainment": "Media & Entertainment", "Plywood Boards/ Laminates": "Construction Materials", "Public Sector Bank": "Banks", "Restaurants": "Hospitality",
    "Rubber": "Automobile & Ancillaries", "Waste Management": "Miscellaneous", "Consulting Services": "Miscellaneous", "Dairy Products": "FMCG",
    "Diversified Retail": "Retailing", "Footwear": "Footwear", "Furniture, Home Furnishing": "Consumer Durables", "Telecom - Equipment & Accessories": "Telecom",
    "Tour, Travel Related Services": "Hospitality", "2/3 Wheelers": "Automobile & Ancillaries", "Advertising & Media Agencies": "Media & Entertainment",
    "Aluminium": "Metals & Mining", "Asset Management Company": "Finance", "TV Broadcasting & Software Production": "Media & Entertainment",
    "Ferro & Silica Manganese": "Metals & Mining", "Healthcare Research, Analytics & Technology": "Healthcare", "LPG/CNG/PNG/LNG Supplier": "Oil & Gas",
    "Other Bank": "Banks", "Paints": "Construction Materials", "Plastic Products - Consumer": "Plastic Products", "Shipping": "Logistics",
    "Telecom - Infrastructure": "Telecom", "Trading - Chemicals": "Trading", "Abrasives & Bearings": "Capital Goods", "Ceramics": "Construction Materials",
    "Financial Institution": "Finance", "Houseware": "Consumer Durables", "Lubricants": "Oil & Gas", "Passenger Cars & Utility Vehicles": "Automobile & Ancillaries",
    "Real Estate Investment Trusts (REITs)": "Real Estate", "Refineries & Marketing": "Oil & Gas", "Trading - Metals": "Trading", "Water Supply & Management": "Infrastructure",
    "Business Process Outsourcing (BPO)/ Knowledge Process Outsourcing (KPO)": "Software & IT Services", "Diversified": "Diversified", "Oil Exploration & Production": "Oil & Gas",
    "Seafood": "FMCG", "Telecom - Cellular & Fixed line services": "Telecom", "Amusement Parks/ Other Recreation": "Miscellaneous", "Animal Feed": "Agri",
    "Construction Vehicles": "Automobile & Ancillaries", "General Insurance": "Insurance", "Household Products": "FMCG", "Integrated Power Utilities": "Power",
    "Internet & Catalogue Retail": "Retailing", "Life Insurance": "Insurance", "Sponge Iron": "Metals & Mining", "Airline": "Aviation", "Auto Dealer": "Automobile & Ancillaries",
    "Depositories, Clearing Houses and Other Intermediaries": "Finance", "Diversified FMCG": "FMCG", "Diversified Metals": "Metals & Mining", "E-Learning": "Miscellaneous",
    "Explosives": "Chemicals", "Leather And Leather Products": "Footwear", "Meat Products including Poultry": "FMCG", "Microfinance Institutions": "Finance",
    "Oil Equipment & Services": "Oil & Gas", "Other Consumer Services": "Miscellaneous", "Print Media": "Media & Entertainment", "Real Estate related services": "Real Estate",
    "Stationary": "Paper", "Web based media and service": "Software & IT Services", "Cigarettes & Tobacco Products": "FMCG", "Coal": "Metals & Mining",
    "Commercial Vehicles": "Automobile & Ancillaries", "Copper": "Metals & Mining", "Digital Entertainment": "Media & Entertainment", "Exchange and Data Platform": "Finance",
    "Glass - Industrial": "Manufacturing", "Granites & Marbles": "Construction Materials", "Industrial Gases": "Industrial Gases & Fuels", "Offshore Support Solution Drilling": "Oil & Gas",
    "Other Telecom Services": "Telecom", "Port & Port services": "Infrastructure", "Power - Transmission": "Power", "Printing & Publication": "Media & Entertainment",
    "Road Transport": "Logistics", "Ship Building & Allied Services": "Ship Building", "Wellness": "Healthcare", "Biotechnology": "Healthcare",
    "Distributors": "Trading", "Diversified consumer products": "FMCG", "Financial Products Distributor": "Finance", "Jute & Jute Products": "Textiles",
    "Railway Wagons": "Capital Goods", "Trading - Textile Products": "Trading", "Airport & Airport services": "Aviation", "Carbon Black": "Chemicals",
    "Dredging": "Infrastructure", "Electronic Media": "Media & Entertainment", "Gas Transmission/Marketing": "Oil & Gas", "Leisure Products": "Consumer Durables",
    "Oil Storage & Transportation": "Oil & Gas", "Other Beverages": "FMCG", "Other Capital Market related Services": "Finance", "Pharmacy Retail": "Retailing",
    "Precious Metals": "Metals & Mining", "Ratings": "Finance", "Sanitary Ware": "Construction Materials", "Tractors": "Automobile & Ancillaries",
    "Trading - Auto components": "Trading", "Trading - Minerals": "Trading", "Transport Related Services": "Logistics", "Zinc": "Metals & Mining",
    "None": "Miscellaneous", "Data Processing Services": "Software & IT Services", "Dealers-Commercial Vehicles, Tractors, Construction Vehicles": "Automobile & Ancillaries",
    "Forest Products": "Paper", "Glass - Consumer": "Consumer Durables", "Industrial Machinery": "Capital Goods", "Insurance Distributors": "Insurance",
    "Multi Utilities": "Power", "Pig Iron": "Metals & Mining", "Power Distribution": "Power", "Power Trading": "Power", "Printing Inks": "Chemicals", "Trading - Gas": "Trading"
}

class MoneyControlSectorScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Upgrade-Insecure-Requests': '1',
        })

    def extract_numeric_value(self, text: str) -> Optional[float]:
        if not text or text == '-': return None
        text = re.sub(r'[(),\s%]', '', text)
        is_negative = text.startswith('-') or text.startswith('−')
        try:
            val = float(text.lstrip('-−'))
            return -val if is_negative else val
        except ValueError: return None

    def extract_market_cap(self, text: str) -> Optional[int]:
        if not text or text == '-': return None
        try: return int(re.sub(r'[,\s]', '', text))
        except ValueError: return None

    def extract_advance_decline(self, text: str) -> tuple[Optional[int], Optional[int]]:
        if not text or '|' not in text: return None, None
        try:
            parts = text.split('|')
            return (int(parts[0].strip()) if parts[0].strip() != '-' else None,
                    int(parts[1].strip()) if parts[1].strip() != '-' else None)
        except ValueError: return None, None

    def determine_trend(self, svg_element) -> str:
        if not svg_element: return "Neutral"
        parent = svg_element.parent
        while parent and parent.name != 'div': parent = parent.parent
        if parent:
            class_names = ' '.join(parent.get('class', [])).lower()
            text_content = parent.get_text().strip().lower()
            if 'bearish' in text_content or 'bearish' in class_names: return "Bearish"
            elif 'verybullish' in text_content or 'very' in text_content: return "Very Bullish"
            elif 'bullish' in text_content or 'bullish' in class_names: return "Bullish"
        return "Neutral"

    def parse_sector_card(self, card) -> Optional[Dict[str, Any]]:
        name_elem = card.find('span', class_=re.compile(r'sectors_name'))
        if not name_elem: return None
        sector_data = {'name': name_elem.get_text().strip()}

        trend_elem = card.find('span', class_=re.compile(r'fontStyle'))
        sector_data['trend'] = trend_elem.get_text().strip() if trend_elem else self.determine_trend(card.find('svg'))

        mcap_elem = card.find('span', class_=re.compile(r'value.*font14'))
        if mcap_elem and 'M. Cap' in card.get_text():
            sector_data['market_cap_cr'] = self.extract_market_cap(mcap_elem.get_text().strip())
            change_elem = mcap_elem.find_next('span', class_=re.compile(r'(plus|minus)'))
            if change_elem: sector_data['market_cap_change_pct'] = self.extract_numeric_value(change_elem.get_text().strip())

        adv_decline_elems = card.find_all('span', class_=re.compile(r'advDecline'))
        adv, dec = self.extract_advance_decline(f"{adv_decline_elems[0].get_text().strip()}|{adv_decline_elems[1].get_text().strip()}" if len(adv_decline_elems) >= 2 else "")
        sector_data['advance_count'] = adv
        sector_data['decline_count'] = dec

        return sector_data

    def scrape_sector_data(self, url: str) -> Dict[str, Any]:
        try:
            response = self.session.get(url, timeout=30)
            soup = BeautifulSoup(response.content, 'html.parser')
            cards = soup.find_all('a', class_=re.compile(r'CardWeb_grayBoxStrip'))
            sectors_data = [self.parse_sector_card(c) for c in cards if self.parse_sector_card(c)]
            
            indices_table = soup.find('table', class_=re.compile(r'sectorialIndicesTable'))
            sectoral_indices = []
            if indices_table:
                for row in indices_table.find_all('tr')[1:]:
                    cells = row.find_all('td')
                    if len(cells) >= 3:
                        sectoral_indices.append({
                            'name': cells[0].get_text().strip(),
                            'price': self.extract_numeric_value(cells[1].get_text().strip()),
                            'change_pct': self.extract_numeric_value(cells[2].get_text().strip())
                        })

            return {"total_sectors": len(sectors_data), "sectors": sectors_data, "sectoral_indices": sectoral_indices}
        except Exception as e:
            logger.error(f"Error fetching data from {url}: {e}")
            return {}

    def scrape_both_pages(self) -> Dict[str, Any]:
        sector_data = self.scrape_sector_data("https://www.moneycontrol.com/markets/sector-analysis/")
        time.sleep(1)
        industry_data = self.scrape_sector_data("https://www.moneycontrol.com/markets/industry-analysis/")
        return {
            "sector_analysis": sector_data,
            "industry_analysis": industry_data
        }

# ==============================================================================
# 3. MONEYCONTROL SEASONALITY SCRAPER
# ==============================================================================
@dataclass
class SeasonalityResult:
    api_data: Optional[Dict[str, Any]]
    errors: List[str]

class MoneyControlSeasonalityScraper:
    def __init__(self):
        self.session = requests.Session()

    def _fetch_with_retries(self, url: str) -> Optional[requests.Response]:
        for attempt in range(4):
            try:
                resp = self.session.get(url, headers={"User-Agent": random.choice(USER_AGENTS)}, timeout=25)
                if resp.status_code in (200, 201): return resp
                if 400 <= resp.status_code < 600: time.sleep(0.5); continue
            except Exception: time.sleep(0.5)
        return None

    def scrape_single(self, url: str) -> SeasonalityResult:
        resp = self._fetch_with_retries(url)
        if not resp: return SeasonalityResult(api_data=None, errors=["failed_fetch"])
        
        soup = BeautifulSoup(resp.text, "html.parser")
        script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        api_data = None
        if script_tag and script_tag.string:
            try: api_data = json.loads(script_tag.string).get("props", {}).get("pageProps", {}).get("apiData")
            except Exception: pass
            
        def _strip_color(obj):
            if isinstance(obj, dict): return {k: _strip_color(v) for k, v in obj.items() if k not in ("colour", "disclaimer")}
            elif isinstance(obj, list): return [_strip_color(x) for x in obj]
            return obj

        return SeasonalityResult(api_data=_strip_color(api_data) if api_data else {}, errors=[] if api_data else ["snippet_not_found"])

# ==============================================================================
# 4. TICKERTAPE MMI SCRAPER
# ==============================================================================
class TickerTapeMMIScraper:
    def __init__(self):
        self.session = requests.Session()

    def _parse_float(self, txt: str) -> Optional[float]:
        if not txt: return None
        m = re.search(r"-?\d+(?:\.\d+)?", txt.replace(",", ""))
        return float(m.group()) if m else None

    def _zone_from_value(self, v: Optional[float]) -> Optional[str]:
        if v is None: return None
        if v < 25: return "Extreme Fear"
        if v < 50: return "Fear"
        if v < 75: return "Greed"
        return "Extreme Greed"

    def fetch_market_mood_index(self) -> Dict[str, Any]:
        try:
            resp = self.session.get("https://www.tickertape.in/market-mood-index", headers={"User-Agent": USER_AGENTS[0]}, timeout=25)
            if not resp or resp.status_code >= 400: return {}
            soup = BeautifulSoup(resp.text, "html.parser")
            text = soup.get_text(" ", strip=True)

            value, zone, changes, nifty_returns = None, None, {}, {}
            next_data = soup.find("script", id="__NEXT_DATA__")
            
            if next_data and next_data.string:
                try:
                    nd = json.loads(next_data.string).get("props", {}).get("pageProps", {}).get("nowData", {})
                    if nd:
                        value = float(nd.get("currentValue") or nd.get("indicator") or 0)
                        zone = self._zone_from_value(value)
                        
                        def _mk_change(prev):
                            if not prev or value is None: return None
                            old = float(prev.get("indicator") or 0)
                            if old == 0: return None
                            return {"change_percent": round(((value - old) / old) * 100.0, 2)}
                            
                        if _mk_change(nd.get("lastDay")): changes["yesterday"] = _mk_change(nd.get("lastDay"))["change_percent"]
                        if _mk_change(nd.get("lastWeek")): changes["last_week"] = _mk_change(nd.get("lastWeek"))["change_percent"]
                        if _mk_change(nd.get("lastMonth")): changes["last_month"] = _mk_change(nd.get("lastMonth"))["change_percent"]
                        
                        def _ret(prev_nifty, curr_nifty):
                            return round(((float(curr_nifty) - float(prev_nifty)) / float(prev_nifty)) * 100.0, 2) if prev_nifty and curr_nifty and float(prev_nifty) != 0 else None

                        curr_nifty = nd.get("nifty")
                        nifty_returns["yesterday"] = _ret(nd.get("lastDay", {}).get("nifty"), curr_nifty)
                        nifty_returns["week"] = _ret(nd.get("lastWeek", {}).get("nifty"), curr_nifty)
                        nifty_returns["month"] = _ret(nd.get("lastMonth", {}).get("nifty"), curr_nifty)
                except Exception: pass

            if value is None:
                m_zone = re.search(r"MMI\s+(Extreme Fear|Fear|Greed|Extreme Greed)\s+zone\s+(\d{1,3}(?:\.\d+)?)", text, re.I)
                if m_zone:
                    zone, value = m_zone.group(1).title(), self._parse_float(m_zone.group(2))

            active_zone = f"zone_{zone.lower().replace(' ', '_')}" if zone else None
            one_hot = {active_zone: 1} if active_zone else {}

            return {
                "market_mood_index": {
                    "value": value,
                    **one_hot,
                    "changes_percent": changes,
                    "nifty_returns": {k: v for k, v in nifty_returns.items() if v is not None}
                }
            }
        except Exception as e:
            logger.error(f"MMI Scrape Failed: {e}")
            return {}


# ==============================================================================
# 5. PUBLIC API EXPORTS
# ==============================================================================

def get_industry_pe_map() -> Dict[str, float]:
    return ScreenerIndustryScraper().fetch_industry_pe_map()

def get_industry_master_list() -> Dict[str, Any]:
    inds = ScreenerIndustryScraper().fetch_all_industries()
    return {"industries": inds, "count": len(inds)}

def get_industry_tickers(url: str) -> Dict[str, Any]:
    tickers = ScreenerIndustryScraper().fetch_tickers_from_industry_page(url)
    return {"url": url, "tickers": sorted(list(tickers)), "count": len(tickers)}

def get_sector_report() -> Dict[str, Any]:
    return MoneyControlSectorScraper().scrape_both_pages()

def get_mapped_sector_data(screener_industry: str) -> Dict[str, Any]:
    """Uses the Crosswalk to map a Screener industry to MC sector momentum."""
    mc_sector = INDUSTRY_TO_SECTOR_CROSSWALK.get(screener_industry)
    if not mc_sector: return {}
    
    report = get_sector_report()
    sectors = report.get("sector_analysis", {}).get("sectors", [])
    for s in sectors:
        if s.get("name") == mc_sector:
            return s
    return {}

def get_seasonality_report(symbol: str) -> Dict[str, Any]:
    try:
        with open(STOCK_LINKS_PATH, "r") as f:
            links = json.load(f)
    except Exception: links = {}
    
    entry = links.get(symbol.strip().upper(), {})
    stock_id = entry.get("moneycontrol_link", "").rstrip("/").split("/")[-1] if entry.get("moneycontrol_link") else symbol.strip().upper()
    url = f"https://www.moneycontrol.com/markets/seasonality-analysis?id={stock_id}&type=stock&ex=N"
    
    res = MoneyControlSeasonalityScraper().scrape_single(url)
    if not res.api_data:
        res = MoneyControlSeasonalityScraper().scrape_single("https://www.moneycontrol.com/markets/seasonality-analysis")
    return res.api_data or {}

def get_tickertape_report() -> Dict[str, Any]:
    return TickerTapeMMIScraper().fetch_market_mood_index()