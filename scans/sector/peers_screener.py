"""
Peers Scraper for Screener.in
Fetches peer company names and data from Screener.in company pages
"""

import requests
from bs4 import BeautifulSoup
import json
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import os
from datetime import datetime
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PeersScreener:
    def __init__(self):
        self.base_url = "https://www.screener.in"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Referer': 'https://www.google.com/'
        })
        
    def setup_selenium_driver(self):
        """Setup Chrome driver with appropriate options"""
        chrome_options = Options()
        chrome_options.add_argument("--headless")  # Run in background
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        
        try:
            driver = webdriver.Chrome(options=chrome_options)
            return driver
        except Exception as e:
            logger.error(f"Failed to setup Chrome driver: {e}")
            raise

    def get_peers_with_selenium(self, company_symbol):
        """
        Get peers data using Selenium to handle dynamic content
        """
        driver = None
        try:
            driver = self.setup_selenium_driver()
            url = f"{self.base_url}/company/{company_symbol}/"
            
            logger.info(f"Fetching peers for {company_symbol} from {url}")
            driver.get(url)
            
            # Wait for the page to load
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.ID, "peers"))
            )
            
            # Scroll to peers section to trigger loading
            peers_section = driver.find_element(By.ID, "peers")
            driver.execute_script("arguments[0].scrollIntoView();", peers_section)
            
            # Wait for peers table to load (replace placeholder)
            WebDriverWait(driver, 30).until_not(
                EC.text_to_be_present_in_element((By.ID, "peers-table-placeholder"), "Loading peers table ...")
            )
            
            # Additional wait to ensure data is fully loaded
            time.sleep(5)
            
            # Get the page source after dynamic content loads
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Extract peers data
            peers_data = self.extract_peers_from_soup(soup, company_symbol)
            
            return peers_data
            
        except Exception as e:
            logger.error(f"Error fetching peers for {company_symbol}: {e}")
            return None
        finally:
            if driver:
                driver.quit()

    def extract_peers_from_soup(self, soup, company_symbol):
        """
        Extract peer companies data from BeautifulSoup object
        """
        peers_data = {
            "company_symbol": company_symbol,
            "scraped_at": datetime.now().isoformat(),
            "peers": [],
            "industry_info": {},
            "benchmarks": []
        }

        # Extract industry classification
        industry_links = soup.select('#peers a[href*="/market/"]')
        industry_info = {}
        for link in industry_links:
            href = link.get('href', '')
            text = link.get_text(strip=True)
            if 'IN03' in href:  # Energy sector
                if 'IN0301' in href:  # Oil, Gas & Consumable Fuels
                    if 'IN030103' in href:  # Petroleum Products
                        if 'IN030103001' in href:  # Refineries & Marketing
                            industry_info['sub_industry'] = text
                        else:
                            industry_info['industry_group'] = text
                    else:
                        industry_info['industry'] = text
                else:
                    industry_info['sector'] = text
        if industry_info:
            peers_data["industry_info"] = industry_info

        # Extract benchmark information
        benchmark_links = soup.select('#benchmarks a.tag')
        benchmarks = []
        for link in benchmark_links:
            benchmark_name = link.get_text(strip=True)
            benchmark_url = link.get('href', '')
            benchmarks.append({
                "name": benchmark_name,
                "url": benchmark_url
            })
        peers_data["benchmarks"] = benchmarks

        # Try to extract peers table data from company page (works only if JS rendered content is present)
        peers_table = None
        peers_section = soup.select_one('#peers')
        if peers_section:
            peers_table = peers_section.select_one('table.data-table') or peers_section.find('table')

        if peers_table:
            peers = []
            rows = peers_table.find_all('tr')
            headers = []

            if rows:
                header_row = rows[0]
                headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]

            for row in rows[1:]:
                cells = row.find_all(['td', 'th'])
                if not cells:
                    continue
                company_cell = cells[0]
                company_link = company_cell.find('a')
                if not company_link:
                    continue
                company_name = company_link.get_text(strip=True)
                company_url = company_link.get('href', '')
                company_symbol_peer = ""
                if '/company/' in company_url:
                    company_symbol_peer = company_url.split('/company/')[-1].split('/')[0]

                peer_data = {
                    "name": company_name,
                    "symbol": company_symbol_peer,
                    "url": company_url,
                    "metrics": {}
                }
                for i, cell in enumerate(cells[1:], 1):
                    if i < len(headers):
                        metric_name = headers[i]
                        metric_value = cell.get_text(strip=True)
                        peer_data["metrics"][metric_name] = metric_value
                peers.append(peer_data)

            peers_data["peers"] = peers

        return peers_data

    def get_company_page_and_subindustry(self, company_symbol):
        """Fetch company page and return BeautifulSoup and sub-industry market URL if present."""
        url = f"{self.base_url}/company/{company_symbol}/"
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, 'html.parser')
        # Extract sub-industry URL from peers breadcrumb
        sub_industry_link = None
        for a in soup.select('#peers a[href*="/market/"]'):
            href = a.get('href', '')
            # Prefer the deepest classification link (most slashes)
            if href.startswith('/market/'):
                if (sub_industry_link is None) or (href.count('/') > sub_industry_link.count('/')):
                    sub_industry_link = href
        return soup, (self.base_url + sub_industry_link if sub_industry_link else None)

    def extract_peers_from_market_page(self, market_url):
        """Given a Screener market sub-industry URL, extract companies as peers."""
        resp = self.session.get(market_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, 'html.parser')
        peers = []
        # Market pages typically have a table with company links under /company/<symbol>/
        for a in soup.select('a[href^="/company/"]'):
            symbol = a.get('href', '').split('/company/')[-1].split('/')[0]
            name = a.get_text(strip=True)
            if not symbol or not name:
                continue
            peers.append({
                "name": name,
                "symbol": symbol,
                "url": a.get('href', ''),
            })
        # De-duplicate by symbol and keep order
        seen = set()
        unique_peers = []
        for p in peers:
            if p['symbol'] in seen:
                continue
            seen.add(p['symbol'])
            unique_peers.append(p)
        return unique_peers

    def scrape_peers_via_market(self, company_symbol):
        """Primary method: use market sub-industry page to list peers (no JS needed)."""
        soup, market_url = self.get_company_page_and_subindustry(company_symbol)
        peers_data = self.extract_peers_from_soup(soup, company_symbol)
        if market_url:
            try:
                peers = self.extract_peers_from_market_page(market_url)
                # Remove the company itself from peers list
                peers = [p for p in peers if p['symbol'].upper() != company_symbol.upper()]
                peers_data['peers'] = peers
                peers_data.setdefault('industry_info', {})['market_url'] = market_url
                return peers_data
            except Exception as e:
                logger.warning(f"Failed fetching peers from market page {market_url}: {e}")
                return peers_data
        return peers_data

    def get_peers_static(self, company_symbol):
        """
        Try to get peers data from static HTML (fallback method)
        """
        try:
            url = f"{self.base_url}/company/{company_symbol}/"
            response = self.session.get(url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            peers_data = self.extract_peers_from_soup(soup, company_symbol)
            
            return peers_data
            
        except Exception as e:
            logger.error(f"Error in static scraping for {company_symbol}: {e}")
            return None

    def scrape_peers(self, company_symbol, use_selenium=False):
        """
        Main method to scrape peers data.
        Defaults to static scraping via market page (no Selenium). Set use_selenium=True to force Selenium.
        """
        try:
            data = self.scrape_peers_via_market(company_symbol)
            # If we got a non-empty peers list, return
            if data and data.get('peers'):
                return data
        except Exception as e:
            logger.warning(f"Market scraping path failed for {company_symbol}: {e}")

        if use_selenium:
            return self.get_peers_with_selenium(company_symbol)
        # Fallback to static company page parse (likely empty peers)
        return self.get_peers_static(company_symbol)

    def save_peers_data(self, peers_data, output_dir=None):
        """
        Save peers data to JSON file
        """
        if not peers_data:
            logger.warning("No peers data to save")
            return None
        # Determine default output directory inside repository RESULTS folder
        if output_dir is None:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            output_dir = os.path.join(project_root, 'RESULTS', 'scans', 'sector')
        os.makedirs(output_dir, exist_ok=True)
        # Clean output: only company_symbol and peers (name, symbol)
        company_symbol = peers_data.get("company_symbol", "unknown")
        peers_clean = []
        for peer in peers_data.get("peers", []):
            peers_clean.append({
                "name": peer.get("name"),
                "symbol": peer.get("symbol")
            })
        output = {
            "company_symbol": company_symbol,
            "peers": peers_clean
        }
        filename = f"peers_{company_symbol.lower()}.json"
        filepath = os.path.join(output_dir, filename)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(output, f, indent=2, ensure_ascii=False)
            logger.info(f"Peers data saved to {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Error saving peers data: {e}")
            return None

def main():
    """Main function to run a scrape for a given SYMBOL and save JSON in data/shared.

    Usage: python scrapers/shared/peers_screener.py SYMBOL
    Example: python scrapers/shared/peers_screener.py RELIANCE
    """
    import sys

    if len(sys.argv) < 2:
        print("Usage: python scans/sector/peers_screener.py SYMBOL")
        print("Example: python scans/sector/peers_screener.py RELIANCE")
        return

    company_symbol = sys.argv[1].strip().upper()
    scraper = PeersScreener()
    logger.info(f"Scraping peers data for {company_symbol}")

    # Prefer static market scraping to avoid Selenium hangs
    peers_data = scraper.scrape_peers(company_symbol, use_selenium=False)

    # If empty peers and Selenium is available, try Selenium as a last resort
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
