import argparse
import json
import logging
import sys
import time
from datetime import datetime
from typing import Optional, Dict, Any

# Add src directory to path for imports
sys.path.append('src')

# Import local modules
from screener_scraper import ScreenerScraper, get_nifty_tickers
from scans import FundamentalScans

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)

def run_single_stock(ticker: str, max_retries: int = 3) -> Optional[Dict[str, Any]]:
    """
    Fetches data and runs scans for a single ticker.
    Returns the scan report dictionary if successful, None otherwise.
    """
    ticker = ticker.upper().strip()
    
    # 1. Scrape Real-Time Data with retry logic
    scraper = ScreenerScraper()
    for attempt in range(max_retries):
        try:
            data = scraper.fetch_company_payload(ticker)
            data["ticker"] = ticker
            break  # Success, exit retry loop
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg and attempt < max_retries - 1:
                # Rate limited, wait longer and retry
                wait_time = 5 * (attempt + 1)  # 5s, 10s, 15s
                logging.warning(f"Rate limited for {ticker}, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            else:
                logging.error(f"Failed to fetch data for {ticker}: {e}")
                return None
    
    # If we get here without data, scraping failed
    if 'data' not in locals():
        return None

    # 2. Run Fundamental Scans
    try:
        scanner = FundamentalScans(data)
        results = scanner.run_scans()
        metadata = scanner.metadata
    except Exception as e:
        logging.error(f"Error running scans for {ticker}: {e}")
        return None

    # 3. Structure the Output
    scan_report = {
        "ticker": ticker,
        "timestamp": datetime.now().isoformat(),
        "archetype": scanner.archetype,
        "industry_context": {
            "industry": metadata.get("industry", "Unknown"),
            "current_price": metadata.get("current_price"),
            "pe": metadata.get("stock_pe"),
            "industry_pe": metadata.get("industry_pe"),
            "market_cap": metadata.get("market_cap")
        },
        "scan_summary": {
            "total_pending": len(results.get("pending", [])),
            "total_skipped": len(results.get("skipped", [])),
            "total_unusual": sum(1 for item in results.get("pending", []) if item.get("unusual_for_industry"))
        },
        "pending": results.get("pending", []),
        "skipped": results.get("skipped", []),
        # Pass raw data through for saving
        "_raw_data": data
    }
    return scan_report

def save_stock_files(report: Dict[str, Any]):
    """Saves the _screener.json and _scan.json files."""
    ticker = report["ticker"]
    raw_data = report.pop("_raw_data") # Remove raw data from scan report before saving

    # Save screener data
    try:
        with open(f"json/{ticker}_screener.json", "w", encoding="utf-8") as f:
            json.dump(raw_data, f, indent=4)
    except Exception as e:
        logging.error(f"Failed to save screener JSON: {e}")

    # Save scan results
    try:
        with open(f"json/{ticker}_scan.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=4)
        logging.info(f"💾 Saved reports for {ticker}")
    except Exception as e:
        logging.error(f"Failed to save scan JSON: {e}")

def main():
    parser = argparse.ArgumentParser(
        description="RE-SCAN-X: Smart Scan Mode",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("start_index", type=int, nargs="?", default=1, help="Start index (1-based) from Nifty 500 list")
    parser.add_argument("--count", type=int, default=5, help="Stop after finding N pending stocks (default: 5)")
    parser.add_argument("--ticker", type=str, help="Scan a specific ticker instead of using index")
    
    args = parser.parse_args()
    
    if args.ticker:
        # Scan single ticker
        logging.info(f"Scanning specific ticker: {args.ticker}")
        report = run_single_stock(args.ticker)
        if report:
            pending_count = report["scan_summary"]["total_pending"]
            skipped_count = report["scan_summary"]["total_skipped"]
            unusual_count = report["scan_summary"]["total_unusual"]
            industry = report["industry_context"]["industry"]
            archetype = report["archetype"]
            if pending_count > 0:
                print(f"⚠️  PENDING: {pending_count} (Arch: {archetype})")
                print(f"   -> Industry: {industry}")
                if unusual_count > 0:
                    print(f"   ⚡ Unusual metrics calculated: {unusual_count}")
                save_stock_files(report)
            else:
                status_msg = f"✅ Clean (Skipped: {skipped_count})"
                if unusual_count > 0:
                    status_msg += f" ⚡ Unusual: {unusual_count}"
                print(status_msg)
        else:
            print("❌ Failed")
        return
    
    # 1. Fetch Tickers
    logging.info("Fetching Nifty 500 tickers...")
    try:
        tickers = get_nifty_tickers()
        logging.info(f"Loaded {len(tickers)} tickers.")
    except Exception as e:
        logging.critical(f"Failed to fetch tickers: {e}")
        sys.exit(1)
        logging.critical(f"Failed to fetch tickers: {e}")
        sys.exit(1)

    # 2. Slice List
    start_pos = max(0, args.start_index - 1)
    if start_pos >= len(tickers):
        logging.error("Start index out of range.")
        sys.exit(1)
    
    target_tickers = tickers[start_pos:]
    logging.info(f"Starting scan from #{args.start_index} ({target_tickers[0]})")
    logging.info(f"Target: Find {args.count} stocks with PENDING data issues.")

    pending_found = 0
    stocks_processed = 0

    print("\n" + "="*60)
    print(f" 🕵️  HUNT MODE: Searching for {args.count} Pending Stocks")
    print("="*60)

    for i, ticker in enumerate(target_tickers):
        idx = args.start_index + i
        print(f"\nProcessing #{idx}: {ticker} ... ", end="", flush=True)
        
        report = run_single_stock(ticker)
        
        if not report:
            print("❌ Failed")
            continue

        pending_count = report["scan_summary"]["total_pending"]
        skipped_count = report["scan_summary"]["total_skipped"]
        unusual_count = report["scan_summary"]["total_unusual"]
        industry = report["industry_context"]["industry"]
        archetype = report["archetype"]

        if pending_count > 0:
            print(f"⚠️  PENDING: {pending_count} (Arch: {archetype})")
            print(f"   -> Industry: {industry}")
            if unusual_count > 0:
                print(f"   ⚡ Unusual metrics calculated: {unusual_count}")
            save_stock_files(report)
            pending_found += 1
        else:
            status_msg = f"✅ Clean (Skipped: {skipped_count})"
            if unusual_count > 0:
                status_msg += f" ⚡ Unusual: {unusual_count}"
            print(status_msg)
            # We explicitly DO NOT save clean files to avoid clutter, as requested.

        stocks_processed += 1
        
        if pending_found >= args.count:
            print("\n" + "="*60)
            print(f"🎯 Target Reached! Found {pending_found} pending stocks.")
            print("="*60)
            break
        
        time.sleep(2)  # Increased delay to avoid rate limiting

if __name__ == "__main__":
    main()