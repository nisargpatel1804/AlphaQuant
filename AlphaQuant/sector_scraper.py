"""MoneyControl Sector and Industry Analysis Scraper

This module scrapes data from MoneyControl's sector and industry analysis pages:
- https://www.moneycontrol.com/markets/sector-analysis
- https://www.moneycontrol.com/markets/industry-analysis

The scraper extracts comprehensive information about each sector/industry including:
- Sector/Industry name and performance trend
- Market capitalization and change percentage
- Advance/Decline ratio
- Sector PE ratio
- Sector earnings YoY growth
- Number of industries and stocks
- Individual sector/industry page links

Output is saved in JSON format with structured data for analysis.
"""

import json
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
import logging
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    raise SystemExit(
        "Required packages not installed. Please install: pip install requests beautifulsoup4"
    ) from e

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default output directory for AlphaQuant outputs
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "RESULTS" / "AlphaQuant"
DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

class MoneyControlSectorScraper:
    """Scraper for MoneyControl sector and industry analysis pages."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
    
    def extract_numeric_value(self, text: str) -> Optional[float]:
        """Extract numeric value from text, handling Indian number format."""
        if not text or text == '-':
            return None
        
        # Remove parentheses and extra spaces
        text = re.sub(r'[(),\s]', '', text)
        
        # Handle negative values
        is_negative = text.startswith('-') or text.startswith('−')
        text = text.lstrip('-−')
        
        # Handle percentage values
        if '%' in text:
            text = text.replace('%', '')
        
        try:
            value = float(text.replace(',', ''))
            return -value if is_negative else value
        except ValueError:
            return None
    
    def extract_market_cap(self, text: str) -> Optional[int]:
        """Extract market cap value and convert to crores."""
        if not text or text == '-':
            return None
        
        # Remove commas and extra spaces
        text = re.sub(r'[,\s]', '', text)
        
        try:
            return int(text)
        except ValueError:
            return None
    
    def extract_advance_decline(self, text: str) -> tuple[Optional[int], Optional[int]]:
        """Extract advance and decline numbers from text like '19|21'."""
        if not text or '|' not in text:
            return None, None
        
        try:
            parts = text.split('|')
            if len(parts) == 2:
                advance = int(parts[0].strip()) if parts[0].strip() != '-' else None
                decline = int(parts[1].strip()) if parts[1].strip() != '-' else None
                return advance, decline
        except ValueError:
            pass
        
        return None, None
    
    def determine_trend(self, svg_element) -> str:
        """Determine the trend based on SVG icon classes."""
        if not svg_element:
            return "Neutral"
        
        # Look for parent elements with trend indicators
        parent = svg_element.parent
        while parent and parent.name != 'div':
            parent = parent.parent
        
        if parent:
            class_names = ' '.join(parent.get('class', []))
            text_content = parent.get_text().strip()
            
            if 'Bearish' in text_content or 'bearish' in class_names.lower():
                return "Bearish"
            elif 'Bullish' in text_content or 'bullish' in class_names.lower():
                return "Bullish"
            elif 'VeryBullish' in text_content or 'very' in text_content.lower():
                return "Very Bullish"
            elif 'Neutral' in text_content or 'neutral' in class_names.lower():
                return "Neutral"
        
        return "Unknown"
    
    def scrape_sector_data(self, url: str) -> Dict[str, Any]:
        """Scrape sector or industry data from the given URL."""
        logger.info(f"Scraping data from: {url}")
        
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Determine if this is sector or industry analysis
            page_type = "sector" if "sector-analysis" in url else "industry"
            
            # Find all sector/industry cards
            cards = soup.find_all('a', class_=re.compile(r'CardWeb_grayBoxStrip'))
            sectors_data = []
            for card in cards:
                try:
                    sector_info = self.parse_sector_card(card)
                    if sector_info:
                        # Remove 'url' field from sector_info
                        sector_info.pop('url', None)
                        sectors_data.append(sector_info)
                except Exception as e:
                    logger.warning(f"Error parsing sector card: {e}")
                    continue
            # Extract sectoral indices if present
            sectoral_indices = self.extract_sectoral_indices(soup)
            return {
                # No metadata
                "total_sectors": len(sectors_data),
                "sectors": sectors_data,
                "sectoral_indices": sectoral_indices
            }
            
        except requests.RequestException as e:
            logger.error(f"Error fetching data from {url}: {e}")
            return {"error": f"Failed to fetch data: {e}", "url": url}
        except Exception as e:
            logger.error(f"Error parsing data from {url}: {e}")
            return {"error": f"Failed to parse data: {e}", "url": url}
    
    def parse_sector_card(self, card) -> Optional[Dict[str, Any]]:
        """Parse individual sector/industry card data."""
        sector_data = {}
        
        # Extract sector name
        name_elem = card.find('span', class_=re.compile(r'sectors_name'))
        if name_elem:
            sector_data['name'] = name_elem.get_text().strip()
        else:
            return None
        
        # Extract sector URL
        href = card.get('href', '')
        if href:
            sector_data['url'] = href if href.startswith('http') else f"https://www.moneycontrol.com{href}"
        
        # Extract trend/sentiment
        trend_elem = card.find('span', class_=re.compile(r'fontStyle'))
        if trend_elem:
            sector_data['trend'] = trend_elem.get_text().strip()
        else:
            # Try to determine from SVG or other indicators
            svg_elem = card.find('svg')
            sector_data['trend'] = self.determine_trend(svg_elem)
        
        # Extract market cap
        mcap_elem = card.find('span', class_=re.compile(r'value.*font14'))
        if mcap_elem and 'M. Cap' in card.get_text():
            mcap_text = mcap_elem.get_text().strip()
            sector_data['market_cap_cr'] = self.extract_market_cap(mcap_text)
            
            # Extract market cap change percentage
            change_elem = mcap_elem.find_next('span', class_=re.compile(r'(plus|minus)'))
            if change_elem:
                change_text = change_elem.get_text().strip()
                sector_data['market_cap_change_pct'] = self.extract_numeric_value(change_text)
        
        # Extract advance/decline data
        adv_decline_text = ""
        adv_decline_elems = card.find_all('span', class_=re.compile(r'advDecline'))
        if adv_decline_elems and len(adv_decline_elems) >= 2:
            advance_text = adv_decline_elems[0].get_text().strip()
            decline_text = adv_decline_elems[1].get_text().strip()
            adv_decline_text = f"{advance_text}|{decline_text}"
            
        advance, decline = self.extract_advance_decline(adv_decline_text)
        sector_data['advance_count'] = advance
        sector_data['decline_count'] = decline
        
        # Extract sector PE
        pe_section = card.find(string=re.compile(r'sector.*PE'))
        if pe_section:
            pe_parent = pe_section.parent
            while pe_parent and not pe_parent.find('span', class_=re.compile(r'value')):
                pe_parent = pe_parent.parent
            
            if pe_parent:
                pe_elem = pe_parent.find('span', class_=re.compile(r'value'))
                if pe_elem:
                    pe_text = pe_elem.get_text().strip()
                    sector_data['sector_pe'] = self.extract_numeric_value(pe_text)
        
        # Extract sector earnings YoY
        earnings_section = card.find(string=re.compile(r'sector.*Earnings.*YOY'))
        if earnings_section:
            earnings_parent = earnings_section.parent
            while earnings_parent and not earnings_parent.find_next('span', class_=re.compile(r'value')):
                earnings_parent = earnings_parent.parent
            
            if earnings_parent:
                earnings_value_elem = earnings_parent.find_next('span', class_=re.compile(r'value'))
                earnings_change_elem = earnings_parent.find_next('span', class_=re.compile(r'(plus|minus)'))
                
                if earnings_value_elem:
                    earnings_text = earnings_value_elem.get_text().strip()
                    sector_data['sector_earnings_cr'] = self.extract_market_cap(earnings_text)
                
                if earnings_change_elem:
                    change_text = earnings_change_elem.get_text().strip()
                    sector_data['sector_earnings_yoy_pct'] = self.extract_numeric_value(change_text)
        
        # Extract industries and stocks count
        count_section = card.find('span', class_=re.compile(r'stocksNum'))
        if count_section:
            count_text = count_section.get_text()
            
            # Extract industries count
            industries_match = re.search(r'Industries\s*:\s*(\d+)', count_text)
            if industries_match:
                sector_data['industries_count'] = int(industries_match.group(1))
            
            # Find stocks count in the next stocksNum span
            stocks_span = count_section.find_next('span', class_=re.compile(r'stocksNum'))
            if stocks_span:
                stocks_text = stocks_span.get_text()
                stocks_match = re.search(r'Stocks\s*:\s*(\d+)', stocks_text)
                if stocks_match:
                    sector_data['stocks_count'] = int(stocks_match.group(1))
        
        return sector_data
    
    def extract_sectoral_indices(self, soup) -> List[Dict[str, Any]]:
        """Extract sectoral indices data from the page."""
        indices_data = []
        
        # Find the sectoral indices table
        indices_table = soup.find('table', class_=re.compile(r'sectorialIndicesTable'))
        
        if indices_table:
            rows = indices_table.find_all('tr')[1:]  # Skip header row
            
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 3:
                    index_data = {
                        'name': cells[0].get_text().strip(),
                        'price': self.extract_numeric_value(cells[1].get_text().strip()),
                        'change_pct': self.extract_numeric_value(cells[2].get_text().strip())
                    }
                    indices_data.append(index_data)
        
        return indices_data
    
    def scrape_both_pages(self) -> Dict[str, Any]:
        """Scrape both sector and industry analysis pages."""
        sector_url = "https://www.moneycontrol.com/markets/sector-analysis/"
        industry_url = "https://www.moneycontrol.com/markets/industry-analysis/"
        
        logger.info("Starting comprehensive sector and industry analysis scraping...")
        
        # Scrape sector analysis
        sector_data = self.scrape_sector_data(sector_url)
        time.sleep(2)  # Be respectful to the server
        
        # Scrape industry analysis
        industry_data = self.scrape_sector_data(industry_url)
        
        # Combine results (no scraping_metadata)
        combined_data = {
            "sector_analysis": sector_data,
            "industry_analysis": industry_data,
            "summary": {
                "total_sectors": sector_data.get("total_sectors", 0),
                "total_industries": industry_data.get("total_sectors", 0),
                "total_entities": sector_data.get("total_sectors", 0) + industry_data.get("total_sectors", 0)
            }
        }
        return combined_data
    
    def save_to_json(self, data: Dict[str, Any], filename: str = None) -> str:
        """Save scraped data to JSON file."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = DEFAULT_OUTPUT_DIR / f"moneycontrol_sector_analysis_{timestamp}.json"
        
        try:
            # Accept Path or string
            out_path = Path(filename)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Data saved to {out_path}")
            return str(out_path)
        except Exception as e:
            logger.error(f"Error saving data to {filename}: {e}")
            raise


def main():
    """Main function to run the scraper."""
    scraper = MoneyControlSectorScraper()
    
    try:
        # Scrape both pages
        data = scraper.scrape_both_pages()
        return data
    except Exception as e:
        logger.error(f"Error during scraping: {e}")
        raise


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="MoneyControl Sector & Industry Analysis Scraper")
    parser.add_argument('--save-json', metavar='PATH', type=str, help='Save scraped data to JSON file at PATH')
    args = parser.parse_args()

    scraper = MoneyControlSectorScraper()
    data = scraper.scrape_both_pages()
    if args.save_json:
        scraper.save_to_json(data, args.save_json)
        print(f"Saved real scraped data to {args.save_json}")
