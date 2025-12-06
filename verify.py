import argparse
import json
import logging
import sys
import time
from datetime import datetime

# Add src directory to path for imports
sys.path.append('src')

# Import local modules
# Ensure these files (screener_scraper.py, scans.py) are in the same directory
from screener_scraper import ScreenerScraper, get_nifty_tickers
from scans import FundamentalScans

# Configure logging to show info on console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)

def verify_ticker(ticker: str, output_file: bool = True):
    """
    Fetches real-time data for a single ticker and runs fundamental scans.
    Returns True on success, False on failure.
    """
    ticker = ticker.upper().strip()
    logging.info(f"Starting verification for: {ticker}")

    # 1. Scrape Real-Time Data
    scraper = ScreenerScraper()
    try:
        logging.info(f"Fetching data from Screener.in for {ticker}...")
        # Direct fetch, bypassing database
        data = scraper.fetch_company_payload(ticker)
        data["ticker"] = ticker
        logging.info("Data fetch successful.")
    except Exception as e:
        logging.error(f"Failed to fetch data for {ticker}. Error: {e}")
        return False

    # 2. Run Fundamental Scans
    try:
        logging.info("Running 107 fundamental scans...")
        scanner = FundamentalScans(data)
        results = scanner.run_scans()
        metadata = scanner.metadata
    except Exception as e:
        logging.error(f"Error running scans: {e}")
        return False

    # 3. Structure the Output - Scan Results
    scan_report = {
        "ticker": ticker,
        "timestamp": datetime.now().isoformat(),
        "industry_context": {
            "industry": metadata.get("industry", "Unknown"),
            "current_price": metadata.get("current_price"),
            "pe": metadata.get("stock_pe"),
            "industry_pe": metadata.get("industry_pe"),
            "market_cap": metadata.get("market_cap")
        },
        "scan_summary": {
            "total_pending": len(results.get("pending", [])),
            "total_skipped": len(results.get("skipped", []))
        },
        "pending": results.get("pending", []),
        "skipped": results.get("skipped", [])
    }

    # 4. Display Summary to Console
    print("\n" + "="*60)
    print(f" 🔍 RE-SCAN-X REPORT: {ticker}")
    print("="*60)
    print(f" Industry:  {scan_report['industry_context']['industry']}")
    print(f" Price:     ₹{scan_report['industry_context'].get('current_price', 'N/A')}")
    print(f" PE Ratio:  {scan_report['industry_context']['pe']} (Ind: {scan_report['industry_context']['industry_pe']})")
    print("-" * 60)
    print(f" ⏳ PENDING:  {scan_report['scan_summary']['total_pending']}")
    print(f" ⏭️  SKIPPED:  {scan_report['scan_summary']['total_skipped']}")
    print("="*60)

    if scan_report["pending"]:
        print("\n⏳ PENDING SCANS (Data Missing):")
        for item in scan_report["pending"]:
            print(f"   - {item['label']}")

    if scan_report["skipped"]:
        print("\n⏭️ SKIPPED SCANS (Not Applicable):")
        for item in scan_report["skipped"]:
            print(f"   - {item['label']}")

    print("\n" + "="*60)

    # 5. Save to JSON Files
    if output_file:
        # Save screener data
        screener_filename = f"json/{ticker}_screener.json"
        try:
            with open(screener_filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            logging.info(f"Screener data saved to: {screener_filename}")
        except Exception as e:
            logging.error(f"Failed to save screener JSON file: {e}")
        
        # Save scan results
        scan_filename = f"json/{ticker}_scan.json"
        try:
            with open(scan_filename, "w", encoding="utf-8") as f:
                json.dump(scan_report, f, indent=4)
            logging.info(f"Scan results saved to: {scan_filename}")
        except Exception as e:
            logging.error(f"Failed to save scan JSON file: {e}")
    
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="RE-SCAN-X: Run fundamental scans on stocks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python verify.py RELIANCE              # Scan single ticker
  python verify.py                       # Scan all Nifty 500 stocks
  python verify.py 1 5                   # Scan stocks 1 to 5
  python verify.py 5 15                  # Scan stocks 5 to 15
        """
    )
    parser.add_argument("ticker", nargs="?", help="Stock ticker symbol OR start index")
    parser.add_argument("end", nargs="?", type=int, help="End index (inclusive, only if ticker is a number)")
    
    args = parser.parse_args()
    
    # Determine if ticker is actually a range start
    is_range = False
    start_idx = None
    end_idx = None
    
    if args.ticker:
        # Check if ticker is a number (range mode)
        try:
            start_idx = int(args.ticker)
            if args.end is not None:
                end_idx = args.end
                is_range = True
            else:
                # Single number without end - treat as ticker
                is_range = False
        except ValueError:
            # Not a number, it's a ticker symbol
            is_range = False
    
    # Case 1: Single ticker provided
    if args.ticker and not is_range:
        logging.info(f"Running scans for single ticker: {args.ticker}")
        verify_ticker(args.ticker)
        sys.exit(0)
    
    # Case 2 & 3: Range or all tickers
    logging.info("Fetching Nifty 500 tickers...")
    try:
        tickers = get_nifty_tickers()
        logging.info(f"Found {len(tickers)} tickers from Nifty 500.")
    except Exception as e:
        logging.error(f"Failed to fetch tickers: {e}")
        sys.exit(1)
    
    # Determine range
    if is_range and start_idx is not None and end_idx is not None:
        # Range-based scan (1-indexed, inclusive)
        start_pos = max(1, start_idx)
        end_pos = min(len(tickers), end_idx)
        selected_tickers = tickers[start_pos - 1:end_pos]  # Convert to 0-indexed
        logging.info(f"Processing stocks {start_pos} to {end_pos} ({len(selected_tickers)} stocks)")
    else:
        # All tickers
        selected_tickers = tickers
        logging.info(f"Processing all {len(selected_tickers)} stocks")
    
    # Process tickers
    success_count = 0
    failure_count = 0
    
    for i, ticker in enumerate(selected_tickers, 1):
        actual_position = (tickers.index(ticker) + 1) if ticker in tickers else i
        logging.info(f"Processing {i}/{len(selected_tickers)} (#{actual_position} in Nifty 500): {ticker}")
        
        if verify_ticker(ticker):
            success_count += 1
        else:
            failure_count += 1
        
        # Rate limiting to be respectful to the server
        if i < len(selected_tickers):
            time.sleep(1)
    
    # Final summary
    print("\n" + "="*60)
    print(f" BATCH PROCESSING COMPLETE")
    print("="*60)
    print(f" Total Processed: {len(selected_tickers)}")
    print(f" ✅ Successful:   {success_count}")
    print(f" ❌ Failed:       {failure_count}")
    print("="*60)