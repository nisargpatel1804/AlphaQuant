# backend/peers.py
"""
Peers scraper for Screener.in.

Fetches peer company names and data from Screener.in company pages.
Provides both static scraping (via requests/BeautifulSoup) and dynamic (via Selenium) fallback.
Used by the API endpoint /api/v1/peers/{symbol}.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# ----------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent          # backend/
OUTPUT_DIR = BASE_DIR / "output"                   # backend/output/
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PeersScreener:
    """Scraper for Screener.in peer companies."""

    def __init__(self):
        self.base_url = "https://www.screener.in"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Referer": "https://www.google.com/",
            }
        )

    def setup_selenium_driver(self):
        """Setup Chrome driver with appropriate options."""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        driver = webdriver.Chrome(options=chrome_options)
        return driver

    def extract_peers_from_soup(self, soup: BeautifulSoup, company_symbol: str) -> Dict[str, Any]:
        """Extract peers data from a BeautifulSoup object."""
        peers_data = {
            "company_symbol": company_symbol,
            "scraped_at": datetime.now().isoformat(),
            "peers": [],
            "industry_info": {},
            "benchmarks": [],
        }

        # Extract industry classification
        industry_links = soup.select('#peers a[href*="/market/"]')
        industry_info = {}
        for link in industry_links:
            href = link.get("href", "")
            text = link.get_text(strip=True)
            if "IN03" in href:
                if "IN0301" in href:
                    if "IN030103" in href:
                        if "IN030103001" in href:
                            industry_info["sub_industry"] = text
                        else:
                            industry_info["industry_group"] = text
                    else:
                        industry_info["industry"] = text
                else:
                    industry_info["sector"] = text
        if industry_info:
            peers_data["industry_info"] = industry_info

        # Extract benchmarks
        benchmark_links = soup.select('#benchmarks a.tag')
        benchmarks = []
        for link in benchmark_links:
            benchmarks.append({"name": link.get_text(strip=True), "url": link.get("href", "")})
        peers_data["benchmarks"] = benchmarks

        # Extract peers table (static content)
        peers_table = None
        peers_section = soup.select_one('#peers')
        if peers_section:
            peers_table = peers_section.select_one('table.data-table') or peers_section.find('table')

        if peers_table:
            peers = []
            rows = peers_table.find_all("tr")
            headers = []
            if rows:
                headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]

            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                company_cell = cells[0]
                company_link = company_cell.find("a")
                if not company_link:
                    continue
                company_name = company_link.get_text(strip=True)
                company_url = company_link.get("href", "")
                company_symbol_peer = ""
                if "/company/" in company_url:
                    company_symbol_peer = company_url.split("/company/")[-1].split("/")[0]
                peer_data = {
                    "name": company_name,
                    "symbol": company_symbol_peer,
                    "url": company_url,
                    "metrics": {},
                }
                for i, cell in enumerate(cells[1:], 1):
                    if i < len(headers):
                        peer_data["metrics"][headers[i]] = cell.get_text(strip=True)
                peers.append(peer_data)
            peers_data["peers"] = peers

        return peers_data

    def get_company_page_and_subindustry(self, company_symbol: str):
        """Fetch company page and return BeautifulSoup and sub‑industry market URL if present."""
        url = f"{self.base_url}/company/{company_symbol}/"
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        sub_industry_link = None
        for a in soup.select('#peers a[href*="/market/"]'):
            href = a.get("href", "")
            if href.startswith("/market/"):
                if (sub_industry_link is None) or (href.count("/") > sub_industry_link.count("/")):
                    sub_industry_link = href
        return soup, (self.base_url + sub_industry_link if sub_industry_link else None)

    def extract_peers_from_market_page(self, market_url: str) -> List[Dict[str, str]]:
        """Given a Screener market sub‑industry URL, extract companies as peers."""
        resp = self.session.get(market_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        peers = []
        for a in soup.select('a[href^="/company/"]'):
            symbol = a.get("href", "").split("/company/")[-1].split("/")[0]
            name = a.get_text(strip=True)
            if not symbol or not name:
                continue
            peers.append({"name": name, "symbol": symbol, "url": a.get("href", "")})
        # Deduplicate
        seen = set()
        unique_peers = []
        for peer in peers:
            if peer["symbol"] in seen:
                continue
            seen.add(peer["symbol"])
            unique_peers.append(peer)
        return unique_peers

    def scrape_peers_via_market(self, company_symbol: str) -> Dict[str, Any]:
        """Primary method: use market sub‑industry page to list peers (no JS needed)."""
        soup, market_url = self.get_company_page_and_subindustry(company_symbol)
        peers_data = self.extract_peers_from_soup(soup, company_symbol)
        if market_url:
            try:
                peers = self.extract_peers_from_market_page(market_url)
                # Remove the company itself from peers list
                peers = [p for p in peers if p["symbol"].upper() != company_symbol.upper()]
                peers_data["peers"] = peers
                peers_data.setdefault("industry_info", {})["market_url"] = market_url
                return peers_data
            except Exception as e:
                logger.warning(f"Failed fetching peers from market page {market_url}: {e}")
                return peers_data
        return peers_data

    def get_peers_static(self, company_symbol: str) -> Optional[Dict[str, Any]]:
        """Try to get peers data from static HTML (fallback method)."""
        try:
            url = f"{self.base_url}/company/{company_symbol}/"
            response = self.session.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")
            return self.extract_peers_from_soup(soup, company_symbol)
        except Exception as e:
            logger.error(f"Error in static scraping for {company_symbol}: {e}")
            return None

    def get_peers_with_selenium(self, company_symbol: str) -> Optional[Dict[str, Any]]:
        """Get peers data using Selenium to handle dynamic content."""
        driver = None
        try:
            driver = self.setup_selenium_driver()
            url = f"{self.base_url}/company/{company_symbol}/"
            logger.info(f"Fetching peers for {company_symbol} from {url}")
            driver.get(url)
            WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "peers")))
            peers_section = driver.find_element(By.ID, "peers")
            driver.execute_script("arguments[0].scrollIntoView();", peers_section)
            WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, "#peers table")))
            time.sleep(5)
            soup = BeautifulSoup(driver.page_source, "html.parser")
            return self.extract_peers_from_soup(soup, company_symbol)
        except Exception as e:
            logger.error(f"Error fetching peers for {company_symbol}: {e}")
            return None
        finally:
            if driver:
                driver.quit()

    def scrape_peers(self, company_symbol: str, use_selenium: bool = False) -> Optional[Dict[str, Any]]:
        """Main method to scrape peers data."""
        try:
            data = self.scrape_peers_via_market(company_symbol)
            if data and data.get("peers"):
                return data
        except Exception as e:
            logger.warning(f"Market scraping path failed for {company_symbol}: {e}")
        if use_selenium:
            return self.get_peers_with_selenium(company_symbol)
        return self.get_peers_static(company_symbol)

    def save_peers_data(self, peers_data: Dict[str, Any], output_dir: Optional[Path] = None) -> Optional[str]:
        """Save peers data to JSON file (used by CLI)."""
        if not peers_data:
            logger.warning("No peers data to save")
            return None
        out_dir = output_dir or OUTPUT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        company_symbol = peers_data.get("company_symbol", "unknown")
        peers_clean = [{"name": peer.get("name"), "symbol": peer.get("symbol")} for peer in peers_data.get("peers", [])]
        output = {"company_symbol": company_symbol, "peers": peers_clean}
        filepath = out_dir / f"{company_symbol}_peers.json"
        with open(filepath, "w", encoding="utf-8") as handle:
            json.dump(output, handle, indent=2, ensure_ascii=False)
        logger.info(f"Peers data saved to {filepath}")
        return str(filepath)


# ----------------------------------------------------------------------
# API wrapper
# ----------------------------------------------------------------------
def get_peers_report(symbol: str, use_selenium: bool = False) -> Dict[str, Any]:
    """Return peers data for a given symbol."""
    scraper = PeersScreener()
    data = scraper.scrape_peers(symbol.strip().upper(), use_selenium=use_selenium) or {}
    peers = data.get("peers", []) if isinstance(data, dict) else []
    return {
        "company_symbol": symbol.strip().upper(),
        "peers": peers,
        "industry_info": data.get("industry_info", {}) if isinstance(data, dict) else {},
        "benchmarks": data.get("benchmarks", []) if isinstance(data, dict) else [],
        "peer_count": len(peers),
    }


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main():
    """CLI entry point: python backend/peers.py SYMBOL"""
    import sys
    if len(sys.argv) < 2:
        print("Usage: python backend/peers.py SYMBOL")
        print("Example: python backend/peers.py RELIANCE")
        return

    company_symbol = sys.argv[1].strip().upper()
    scraper = PeersScreener()
    logger.info(f"Scraping peers data for {company_symbol}")

    peers_data = scraper.scrape_peers(company_symbol, use_selenium=False)
    if (not peers_data) or (not peers_data.get('peers')):
        logger.info("Static scraping returned no peers, attempting Selenium fallback...")
        peers_data = scraper.scrape_peers(company_symbol, use_selenium=True)

    if not peers_data:
        logger.error("Failed to scrape peers data")
        return

    output_path = scraper.save_peers_data(peers_data)
    if output_path:
        logger.info("Successfully scraped and saved peers data")
        logger.info(f"Found {len(peers_data.get('peers', []))} peer companies")
        for peer in peers_data.get('peers', []):
            print(f"- {peer.get('name')} ({peer.get('symbol')})")
    else:
        logger.error("Failed to save peers data")


if __name__ == "__main__":
    main()