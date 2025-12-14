import argparse
import json
import logging
import sys
import time
import os
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Set, Optional


# Ensure we can import from the `fundamentals/` folder.
_FUNDAMENTALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _FUNDAMENTALS_DIR not in sys.path:
    sys.path.insert(0, _FUNDAMENTALS_DIR)

# Import local modules
from screener_scraper import get_nifty_tickers, USER_AGENTS

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)

MARKET_URL = "https://www.screener.in/market/?sort=total_market_cap&order=desc"

class IndustryMapper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENTS[0]})

    def fetch_industry_pe_map(self) -> Dict[str, float]:
        """Fetch {industry_name: median_pe} from Screener market page."""
        pe_map: Dict[str, float] = {}
        try:
            response = self.session.get(MARKET_URL, timeout=20)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            table = soup.select_one("table.data-table")
            if not table:
                return pe_map

            headers = [th.get_text(strip=True).lower() for th in table.select("thead th")]
            pe_idx = None
            for i, header in enumerate(headers):
                if header in {"p/e", "pe", "p e", "median pe", "median p/e"} or "p/e" in header or "pe" == header:
                    pe_idx = i
                    break

            for row in table.select("tbody tr"):
                cols = row.find_all(["td", "th"])
                if not cols:
                    continue
                name_el = row.select_one('a[title="Industry"], a[href*="/market/"]')
                industry = (name_el.get_text(strip=True) if name_el else cols[0].get_text(strip=True)).strip()
                if not industry:
                    continue

                value_text = None
                if pe_idx is not None and pe_idx < len(cols):
                    value_text = cols[pe_idx].get_text(strip=True)
                else:
                    # Fallback: try to find something that looks like a PE number in the row.
                    for c in cols:
                        t = c.get_text(" ", strip=True)
                        if t and any(ch.isdigit() for ch in t) and len(t) <= 8:
                            value_text = t
                if not value_text:
                    continue

                cleaned = value_text.replace(",", "").strip()
                try:
                    pe = float(cleaned)
                except Exception:
                    continue
                if pe > 0:
                    pe_map[industry] = pe

        except Exception:
            return pe_map
        return pe_map

    def fetch_all_industries(self) -> Dict[str, str]:
        """
        Scrapes the main market page to find ALL industry names and their URLs.
        Returns: { "Private Sector Bank": "https://...", ... }
        """
        print(f"🌍 Fetching Industry Master List from: {MARKET_URL}")
        industries = {}
        try:
            response = self.session.get(MARKET_URL, timeout=20)
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
            
            print(f"✅ Found {len(industries)} industries/sectors.")
            return industries

        except Exception as e:
            print(f"❌ Error fetching market page: {e}")
            return {}

    def fetch_tickers_from_industry_page(self, url: str) -> Set[str]:
        """Scrape all tickers from a specific Industry page, handling pagination."""
        tickers = set()
        page_num = 1
        seen_on_previous_page = set()
        
        # Ensure sorting by market cap desc
        separator = "&" if "?" in url else "?"
        base_url = f"{url}{separator}sort=market+capitalization&order=desc"
            
        print(f"   ⬇️  Fetching tickers from: {base_url}")
        
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
                print(f"      ⚠️ Error fetching page {page_num}: {e}")
                break
                
        return tickers

def main():
    parser = argparse.ArgumentParser(description="Map Industry stocks to Nifty 500")
    parser.add_argument("industry", type=str, help="Industry Name (exact) or 'ALL' to map everything")
    args = parser.parse_args()

    # 1. Get Nifty 500 Universe
    try:
        nifty_tickers = set(get_nifty_tickers())
        print(f"📋 Loaded {len(nifty_tickers)} tickers from Nifty 500.")
    except Exception as e:
        print(f"❌ Failed to fetch Nifty tickers: {e}")
        sys.exit(1)

    mapper = IndustryMapper()

    # Fetch industry PE map once so it can be stored in the master map output.
    industry_pe_map = mapper.fetch_industry_pe_map()

    # 2. Get All Industries
    all_industries = mapper.fetch_all_industries()
    if not all_industries:
        print("❌ Could not fetch industry list. Check network.")
        sys.exit(1)

    # 3. Determine Execution Plan
    if args.industry.upper() == "ALL":
        target_industries = all_industries
        print(f"🚀 Mode: Mapping ALL {len(target_industries)} industries.")
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
            print(f"🚀 Mode: Single Industry '{target_key}'")
        else:
            print(f"❌ Industry '{args.industry}' not found in Screener's list.")
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
            print(f"   ❌ Failed to scrape {ind_name}: {e}")
            continue

        # Match
        matched = []
        for t in sector_tickers:
            if t in nifty_tickers:
                matched.append(t)
        
        print(f"   ✅ Matched {len(matched)} Nifty 500 stocks.")
        
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
    print(f"🏁 DONE. Total Industries Mapped: {len(full_mapping)}")
    print(f"    Total Nifty 500 Stocks Categorized: {total_mappings}")
    
    if args.industry.upper() == "ALL" or len(full_mapping) > 0:
        master_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "master_industry_map.json")
        with open(master_file, "w") as f:
            json.dump(full_mapping, f, indent=4)
        print(f"💾 Master mapping saved to: {master_file}")

if __name__ == "__main__":
    main()