import argparse
import asyncio
import json
import logging
import sys
import time
import os
import random
import requests
from bs4 import BeautifulSoup
from typing import Dict, Set, Optional

# Ensure subprocess support on Windows by preferring the Proactor event loop
if sys.platform.startswith("win"):
    policy = asyncio.get_event_loop_policy()
    if not isinstance(policy, asyncio.WindowsProactorEventLoopPolicy):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass

from playwright.async_api import async_playwright

# Ensure we can import from the `fundamentals/` folder.
# This assumes the script is running from fundamentals/source/
_FUNDAMENTALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_FUNDAMENTALS_DIR)

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Import from the new refactored modules
from fundamentals.utils import get_nifty_tickers
from fundamentals.config import USER_AGENTS, MARKET_INDUSTRIES_URL

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)

class IndustryMapper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENTS[0]})

    @staticmethod
    def _normalize_number(text: str) -> Optional[float]:
        if not text:
            return None
        cleaned = (
            text.replace(",", "")
            .replace("×", "")
            .replace("x", "")
            .replace("%", "")
            .strip()
        )
        if cleaned in {"", "-", "—", "na", "n/a", "none"}:
            return None
        try:
            value = float(cleaned)
        except Exception:
            return None
        return value if value > 0 else None

    @staticmethod
    def _extract_industry_pe_from_html(html: str) -> Dict[str, float]:
        """Parse Screener market HTML and extract {industry_name: median_pe}."""
        pe_map: Dict[str, float] = {}
        soup = BeautifulSoup(html, "html.parser")

        table = soup.select_one("table.data-table")
        if not table:
            return pe_map

        def _cell_text(cell) -> str:
            try:
                return cell.get_text(" ", strip=True)
            except Exception:
                return ""

        # Screener tables sometimes have no <thead>; the header may appear inside <tbody>
        # and may be rendered using <th> or even <td>.
        header_row = None

        thead = table.find("thead")
        if thead:
            header_row = thead.find("tr")

        if header_row is None:
            # Prefer the row that explicitly contains "Median P/E".
            for tr in table.select("tr"):
                row_text = _cell_text(tr).lower()
                if "median" in row_text and ("p/e" in row_text or "p e" in row_text or "pe" in row_text):
                    header_row = tr
                    break

        if header_row is None:
            # Fallback: first row that contains <th>.
            for tr in table.select("tr"):
                ths = tr.find_all("th")
                if ths and any(_cell_text(th) for th in ths):
                    header_row = tr
                    break

        header_cells = []
        if header_row is not None:
            header_cells = header_row.find_all(["th", "td"])
        headers = [_cell_text(c).lower() for c in header_cells]

        pe_idx: Optional[int] = None
        for i, header in enumerate(headers):
            normalized = " ".join(header.split())
            if ("p/e" in normalized or normalized in {"pe", "p e"}) and "median" in normalized:
                pe_idx = i
                break
        if pe_idx is None:
            for i, header in enumerate(headers):
                normalized = " ".join(header.split())
                if "p/e" in normalized or normalized in {"p/e", "pe", "p e"}:
                    pe_idx = i
                    break

        # Data rows contain <td>. Skip any header-like rows.
        for row in table.select("tr"):
            if row is header_row:
                continue

            cols = row.find_all("td")
            if not cols:
                continue

            name_el = row.select_one('a[title="Industry"], a[href*="/market/"]')
            industry = (
                (name_el.get_text(" ", strip=True) if name_el else (cols[1].get_text(" ", strip=True) if len(cols) > 1 else cols[0].get_text(" ", strip=True)))
                .strip()
            )
            if not industry:
                continue

            value_text: Optional[str] = None

            if pe_idx is not None and pe_idx < len(cols):
                value_text = cols[pe_idx].get_text(strip=True)
            else:
                # Heuristic for Screener "Industries" overview layout:
                # [0]=S.No., [1]=Industry, [2]=No. of Companies, [3]=Total MCap, [4]=Median MCap, [5]=Median P/E, ...
                # If we fail to detect headers, prefer the known Median P/E column to avoid
                # accidentally reading "No. of Companies" (e.g., 150 for Pharmaceuticals).
                if len(cols) >= 6:
                    value_text = cols[5].get_text(strip=True)
                else:
                    # Last resort: find a plausible number-like cell, but skip the first numeric column
                    # which is often "No. of Companies".
                    for c in cols[3:]:
                        t = c.get_text(" ", strip=True)
                        if not t:
                            continue
                        if any(ch.isdigit() for ch in t) and len(t) <= 12:
                            value_text = t
                            break

            pe = IndustryMapper._normalize_number(value_text or "")
            if pe is not None:
                pe_map[industry] = pe

        return pe_map

    async def _fetch_market_html_playwright(self, url: str) -> Optional[str]:
        """Fetch fully-rendered HTML via Playwright (Screener pages are often JS-rendered)."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(user_agent=random.choice(USER_AGENTS))
                page = await context.new_page()
                await page.goto(url, wait_until="networkidle", timeout=60_000)

                # Give client-side rendering a moment if needed.
                try:
                    await page.wait_for_selector("table.data-table", timeout=15_000)
                except Exception:
                    pass
                await page.wait_for_timeout(750)

                return await page.content()
            finally:
                await browser.close()

    def fetch_industry_pe_map(self) -> Dict[str, float]:
        """Fetch {industry_name: median_pe} from Screener market page."""
        # 1) Fast path: static HTML via requests
        try:
            self.session.headers.update({"User-Agent": random.choice(USER_AGENTS)})
            response = self.session.get(MARKET_INDUSTRIES_URL, timeout=25)
            response.raise_for_status()
            pe_map = self._extract_industry_pe_from_html(response.text)
            if pe_map:
                logging.info(f"Industry Median P/E scraped (static): {len(pe_map)}")
                return pe_map
        except Exception as e:
            logging.warning(f"Static industry PE scrape failed: {e}")

        # 2) Fallback: rendered HTML via Playwright
        try:
            # This script is intended to be run as a CLI tool, so a plain asyncio.run is fine.
            html = asyncio.run(self._fetch_market_html_playwright(MARKET_INDUSTRIES_URL))
            if not html:
                return {}
            pe_map = self._extract_industry_pe_from_html(html)
            if pe_map:
                logging.info(f"Industry Median P/E scraped (playwright): {len(pe_map)}")
            else:
                logging.warning("Playwright fetch succeeded but no Median P/E values were found. Page structure may have changed or access may be blocked.")
            return pe_map
        except Exception as e:
            logging.warning(f"Playwright industry PE scrape failed: {e}")
            return {}

    def fetch_all_industries(self) -> Dict[str, str]:
        """
        Scrapes the main market page to find ALL industry names and their URLs.
        Returns: { "Private Sector Bank": "https://...", ... }
        """
        print(f"Fetching Industry Master List from: {MARKET_INDUSTRIES_URL}")
        industries = {}
        try:
            response = self.session.get(MARKET_INDUSTRIES_URL, timeout=20)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Industries are typically in the sidebar or a specific list container
            # Look for links containing '/market/' but exclude generic sorts
            links = soup.select("div.sidebar a") + soup.select("a[href*='/market/']")
            
            for link in links:
                text = link.get_text(strip=True)
                href = link.get("href", "")
                
                # Filter for valid industry links (usually numeric IDs or specific slugs)
                # Generic links like 'Market Cap' sorting shouldn't be included if they don't look like sectors
                if "/market/" in href and text:
                    # Exclude "See all", "Screens", etc.
                    if text.lower() in ["screens", "tools", "feed", "premium", "home", "market"]:
                        continue
                    if "sort=" in href: # Skip sorting links
                        continue
                        
                    full_url = "https://www.screener.in" + href if href.startswith("/") else href
                    
                    # Store mapping (Cleaning text)
                    clean_name = text.strip()
                    # Filter out duplicates or non-industry links
                    if clean_name not in industries and len(clean_name) > 2:
                        industries[clean_name] = full_url
            
            print(f"Found {len(industries)} industries/sectors.")
            return industries

        except Exception as e:
            print(f"ERROR: Error fetching market page: {e}")
            return {}

    def fetch_tickers_from_industry_page(self, url: str) -> Set[str]:
        """Scrape all tickers from a specific Industry page, handling pagination."""
        tickers = set()
        page_num = 1
        seen_on_previous_page = set()
        
        # Ensure sorting by market cap desc
        separator = "&" if "?" in url else "?"
        base_url = f"{url}{separator}sort=market+capitalization&order=desc"
            
        print(f"   Fetching tickers from: {base_url}")
        
        while True:
            target = f"{base_url}&page={page_num}"
            try:
                response = self.session.get(target, timeout=15)
                if response.status_code == 404: 
                    break 
                
                soup = BeautifulSoup(response.text, "html.parser")
                rows = soup.select("table.data-table tbody tr")
                if not rows: 
                    break
                
                current_batch = set()
                for row in rows:
                    a_tag = row.select_one("a[href*='/company/']")
                    if a_tag:
                        href = a_tag.get("href", "")
                        parts = href.strip("/").split("/")
                        if len(parts) >= 2:
                            symbol = parts[1].strip().upper()
                            current_batch.add(symbol)
                
                if not current_batch:
                    break
                
                # Deduplication Check
                if current_batch == seen_on_previous_page:
                    break
                
                initial_len = len(tickers)
                tickers.update(current_batch)
                new_len = len(tickers)
                
                if new_len == initial_len and page_num > 1:
                     break

                seen_on_previous_page = current_batch
                
                # Check pagination
                pagination = soup.select_one("div.pagination")
                if not pagination:
                     break
                
                if page_num > 20: 
                    break

                page_num += 1
                time.sleep(0.5) 
                
            except Exception as e:
                print(f"      WARN: Error fetching page {page_num}: {e}")
                break
                
        return tickers

def main():
    parser = argparse.ArgumentParser(description="Map Industry stocks to Nifty 500")
    parser.add_argument(
        "industry",
        nargs="?",
        default="ALL",
        type=str,
        help="Industry Name (exact) or 'ALL' to map everything",
    )
    parser.add_argument(
        "--update-pe-only",
        action="store_true",
        help="Only refresh industry_pe values in the existing master_industry_map.json (no ticker scraping).",
    )
    args = parser.parse_args()

    mapper = IndustryMapper()

    # Fast path: refresh PE values only in an existing master map.
    if args.update_pe_only:
        output_dir = os.path.dirname(os.path.abspath(__file__))
        master_file = os.path.join(output_dir, "master_industry_map.json")
        if not os.path.exists(master_file):
            print(f"ERROR: master_industry_map.json not found at: {master_file}")
            sys.exit(1)

        try:
            with open(master_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception as e:
            print(f"ERROR: Failed to read master map: {e}")
            sys.exit(1)

        if not isinstance(existing, list):
            print("ERROR: master_industry_map.json is not a list")
            sys.exit(1)

        industry_pe_map = mapper.fetch_industry_pe_map()
        if not industry_pe_map:
            print("ERROR: Failed to fetch industry median P/E from Screener.")
            sys.exit(1)

        def _norm(name: str) -> str:
            return " ".join(str(name or "").split()).strip().lower()

        pe_by_norm = {_norm(k): v for k, v in industry_pe_map.items()}

        updated = 0
        missing = 0
        for entry in existing:
            if not isinstance(entry, dict):
                continue
            ind = (entry.get("industry") or "").strip()
            pe = pe_by_norm.get(_norm(ind))
            if pe is None:
                missing += 1
                continue
            entry["industry_pe"] = pe
            updated += 1

        with open(master_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=4)

        print(f"OK: Updated industry_pe for {updated} industries (missing: {missing}).")
        sys.exit(0)

    # 1. Get Nifty 500 Universe
    try:
        nifty_tickers = set(get_nifty_tickers())
        print(f"Loaded {len(nifty_tickers)} tickers from Nifty 500.")
    except Exception as e:
        print(f"ERROR: Failed to fetch Nifty tickers: {e}")
        sys.exit(1)

    # Fetch industry PE map once so it can be stored in the master map output.
    industry_pe_map = mapper.fetch_industry_pe_map()

    # 2. Get All Industries
    all_industries = mapper.fetch_all_industries()
    if not all_industries:
        print("ERROR: Could not fetch industry list. Check network.")
        sys.exit(1)

    # 3. Determine Execution Plan
    if args.industry.upper() == "ALL":
        target_industries = all_industries
        print(f"Mode: Mapping ALL {len(target_industries)} industries.")
    else:
        # Fuzzy match or exact match
        target_key = None
        for name in all_industries:
            if args.industry.lower() == name.lower():
                target_key = name
                break
            if args.industry.lower() in name.lower():
                target_key = name
        
        if target_key:
            target_industries = {target_key: all_industries[target_key]}
            print(f"Mode: Single Industry '{target_key}'")
        else:
            print(f"ERROR: Industry '{args.industry}' not found in Screener's list.")
            print("Available options (first 10):", list(all_industries.keys())[:10])
            sys.exit(1)

    # 4. Execute Mapping
    total_mappings = 0
    full_mapping = []

    print("\n" + "="*60)
    for idx, (ind_name, ind_url) in enumerate(target_industries.items(), 1):
        print(f"[{idx}/{len(target_industries)}] Processing: {ind_name}")
        
        # Scrape
        try:
            sector_tickers = mapper.fetch_tickers_from_industry_page(ind_url)
        except Exception as e:
            print(f"   ERROR: Failed to scrape {ind_name}: {e}")
            continue

        # Match
        matched = []
        for t in sector_tickers:
            if t in nifty_tickers:
                matched.append(t)
        
        print(f"   Matched {len(matched)} Nifty 500 stocks.")
        
        if matched:
            mapping_entry = {
                "industry": ind_name,
                "url": ind_url,
                "industry_pe": industry_pe_map.get(ind_name),
                "stocks": matched
            }
            full_mapping.append(mapping_entry)
            total_mappings += len(matched)
        
        if len(target_industries) > 1:
            time.sleep(1.5)

    # 5. Final Output
    print("="*60)
    print(f"DONE. Total Industries Mapped: {len(full_mapping)}")
    print(f"    Total Nifty 500 Stocks Categorized: {total_mappings}")
    
    # Save to the source folder relative to this script
    output_dir = os.path.dirname(os.path.abspath(__file__))
    master_file = os.path.join(output_dir, "master_industry_map.json")
    
    if args.industry.upper() == "ALL" or len(full_mapping) > 0:
        with open(master_file, "w", encoding="utf-8") as f:
            json.dump(full_mapping, f, indent=4)
        print(f"Saved master mapping to: {master_file}")

if __name__ == "__main__":
    main()