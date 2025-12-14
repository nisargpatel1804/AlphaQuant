import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

_OUTPUT_DIR = Path(__file__).resolve().parent / "json"
_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Import local modules
# Support both:
# - `python fundamentals/verify.py` (direct script run)
# - `python -m fundamentals.verify` / `import fundamentals.verify` (package run)
if __package__:
    from .screener_scraper import ScreenerScraper, get_nifty_tickers
    from .scans import FundamentalScans
else:
    from screener_scraper import ScreenerScraper, get_nifty_tickers
    from scans import FundamentalScans


def _master_map_path() -> Path:
    fundamentals_dir = Path(__file__).resolve().parent
    return fundamentals_dir / "source" / "master_industry_map.json"


def load_master_industry_map() -> List[Dict[str, Any]]:
    path = _master_map_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def build_ticker_to_industry_and_pe(master_map: List[Dict[str, Any]]) -> tuple[Dict[str, str], Dict[str, float]]:
    ticker_to_industry: Dict[str, str] = {}
    industry_to_pe: Dict[str, float] = {}
    for entry in master_map:
        industry = (entry.get("industry") or "").strip()
        tickers = entry.get("stocks") or []
        pe = entry.get("industry_pe")

        if industry:
            try:
                if pe is not None:
                    industry_to_pe[industry] = float(pe)
            except Exception:
                pass

        if industry and isinstance(tickers, list):
            for ticker in tickers:
                t = str(ticker).strip().upper()
                if t:
                    ticker_to_industry[t] = industry

    return ticker_to_industry, industry_to_pe


def apply_industry_context(
    payload: Dict[str, Any],
    *,
    ticker: str,
    ticker_to_industry: Dict[str, str],
    industry_to_pe: Dict[str, float],
) -> Dict[str, Any]:
    t = ticker.strip().upper()
    industry = ticker_to_industry.get(t)

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        payload["metadata"] = metadata

    if industry:
        metadata["industry"] = industry
        pe = industry_to_pe.get(industry)
        if pe is not None:
            metadata["industry_pe"] = pe
            payload["industry_pe"] = pe

    return payload

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)


def build_scan_context() -> tuple[ScreenerScraper, Dict[str, str], Dict[str, float]]:
    """Load industry name + industry P/E from the run_industry_check output, then scrape stocks."""
    scraper = ScreenerScraper(use_industry_pe_map=False)
    master_map = load_master_industry_map()
    ticker_to_industry, industry_to_pe = build_ticker_to_industry_and_pe(master_map)
    return scraper, ticker_to_industry, industry_to_pe

def run_single_stock(
    ticker: str,
    max_retries: int = 3,
    *,
    scraper: Optional[ScreenerScraper] = None,
    ticker_to_industry: Optional[Dict[str, str]] = None,
    industry_pe_map: Optional[Dict[str, float]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Fetches data and runs scans for a single ticker.
    Returns the scan report dictionary if successful, None otherwise.
    """
    ticker = ticker.upper().strip()
    
    # 0. Build context (industry mapping + industry PE) once.
    if scraper is None or ticker_to_industry is None or industry_pe_map is None:
        scraper, ticker_to_industry, industry_pe_map = build_scan_context()

    # 1. Scrape Real-Time Data with retry logic
    for attempt in range(max_retries):
        try:
            data = scraper.fetch_company_payload(ticker)
            data["ticker"] = ticker
            apply_industry_context(
                data,
                ticker=ticker,
                ticker_to_industry=ticker_to_industry,
                industry_to_pe=industry_pe_map,
            )
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
    # Persist only pass/fail/pending.
    passed = results.get("pass", [])
    failed = results.get("fail", [])
    pending = results.get("pending", [])

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
            "total_pass": len(passed),
            "total_fail": len(failed),
            "total_pending": len(pending),
        },
        "pass": passed,
        "fail": failed,
        "pending": pending,
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
        with open(_OUTPUT_DIR / f"{ticker}_screener.json", "w", encoding="utf-8") as f:
            json.dump(raw_data, f, indent=4)
    except Exception as e:
        logging.error(f"Failed to save screener JSON: {e}")

    # Save scan results
    try:
        with open(_OUTPUT_DIR / f"{ticker}_scan.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=4)
        logging.info(f"💾 Saved reports for {ticker}")
    except Exception as e:
        logging.error(f"Failed to save scan JSON: {e}")


def find_industry_entry(name: str, master_map: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    target = name.strip().lower()
    for entry in master_map:
        industry_name = entry.get("industry", "").strip().lower()
        if industry_name == target:
            return entry
    for entry in master_map:
        industry_name = entry.get("industry", "").strip().lower()
        if target in industry_name or industry_name in target:
            return entry
    return None


def run_industry_scans(entry: Dict[str, Any], limit: int = 101, delay: float = 2.0) -> None:
    industry_name = entry.get("industry", "<unknown>")
    tickers = [ticker.upper() for ticker in entry.get("stocks", [])]
    if not tickers:
        logging.warning(f"No tickers found for industry {industry_name}.")
        return

    scan_list = tickers[:limit]
    print("\n" + "=" * 60)
    print(f" 🏭 Industry Scan: {industry_name} ({len(scan_list)} of {len(tickers)} symbols) ")
    print("=" * 60)

    processed = 0
    failures = 0

    scraper, ticker_to_industry, industry_pe_map = build_scan_context()

    for idx, ticker in enumerate(scan_list, start=1):
        print(f"\n[{idx}/{len(scan_list)}] {ticker} ...", end="", flush=True)
        report = run_single_stock(
            ticker,
            scraper=scraper,
            ticker_to_industry=ticker_to_industry,
            industry_pe_map=industry_pe_map,
        )
        if not report:
            print(" ❌ Failed")
            failures += 1
            time.sleep(delay)
            continue

        pending = report["scan_summary"].get("total_pending", 0)
        archetype = report["archetype"]

        print(f" Pending={pending} (Arch: {archetype})")

        if pending > 0:
            save_stock_files(report)
        processed += 1
        time.sleep(delay)

    print("\n" + "=" * 60)
    print(f"🎯 Industry scan done: {industry_name}. Processed {processed} successes, {failures} failures.")
    print("=" * 60)

def main():
    parser = argparse.ArgumentParser(
        description="RE-SCAN-X: Smart Scan Mode",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("start_index_or_ticker", nargs="?", help="Start index (1-based), ticker symbol, or industry name")
    parser.add_argument("--count", type=int, default=5, help="Stop after finding N pending stocks (default: 5)")
    parser.add_argument("--ticker", type=str, help="Scan a specific ticker instead of using index")
    parser.add_argument("--industry", "-i", type=str, help="Scan all tickers for a master industry mapping")
    
    args = parser.parse_args()

    scraper, ticker_to_industry, industry_pe_map = build_scan_context()

    positional_arg = args.start_index_or_ticker
    start_index = 1
    ticker_target = args.ticker.upper() if args.ticker else None
    industry_entry = None
    master_map: List[Dict[str, Any]] = []
    has_master_map = False

    def ensure_master_map() -> bool:
        nonlocal master_map, has_master_map
        if not has_master_map:
            master_map = load_master_industry_map()
            has_master_map = len(master_map) > 0
            if not has_master_map:
                logging.warning(
                    "Industry map not found. Run fundamentals/source/run_industry_check.py ALL to generate fundamentals/source/master_industry_map.json."
                )
        return has_master_map

    if args.industry and ticker_target:
        logging.error("Cannot specify --ticker and --industry together.")
        sys.exit(1)

    if args.industry:
        if not ensure_master_map():
            logging.critical(
                "Industry map missing. Run fundamentals/source/run_industry_check.py ALL to (re)generate fundamentals/source/master_industry_map.json."
            )
            sys.exit(1)
        industry_entry = find_industry_entry(args.industry, master_map)
        if not industry_entry:
            logging.critical(
                f"Industry '{args.industry}' not found in master map. Rebuild via fundamentals/source/run_industry_check.py ALL."
            )
            sys.exit(1)
    elif positional_arg and not ticker_target:
        positional_arg = positional_arg.strip()
        try:
            start_index = int(positional_arg)
        except ValueError:
            if ensure_master_map():
                industry_entry = find_industry_entry(positional_arg, master_map)
                if not industry_entry:
                    ticker_target = positional_arg.upper()
            else:
                if " " in positional_arg:
                    logging.critical(
                        "Industry map missing. Rebuild via fundamentals/source/run_industry_check.py ALL to enable industry lookups."
                    )
                    sys.exit(1)
                ticker_target = positional_arg.upper()

    if industry_entry:
        run_industry_scans(industry_entry)
        return
    
    if ticker_target:
        # Scan single ticker (supports positional symbol with no flags)
        logging.info(f"Scanning specific ticker: {ticker_target}")
        report = run_single_stock(
            ticker_target,
            scraper=scraper,
            ticker_to_industry=ticker_to_industry,
            industry_pe_map=industry_pe_map,
        )
        if report:
            pending_count = report["scan_summary"].get("total_pending", 0)
            industry = report["industry_context"]["industry"]
            archetype = report["archetype"]

            if pending_count > 0:
                print(f"PENDING: {pending_count} (Arch: {archetype})")
            else:
                pass_count = report["scan_summary"].get("total_pass", 0)
                fail_count = report["scan_summary"].get("total_fail", 0)
                print(f"PASS: {pass_count} | FAIL: {fail_count} (Arch: {archetype})")
            print(f"   -> Industry: {industry}")
            if pending_count > 0:
                save_stock_files(report)
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

    # 2. Slice List
    start_pos = max(0, start_index - 1)
    if start_pos >= len(tickers):
        logging.error("Start index out of range.")
        sys.exit(1)
    
    target_tickers = tickers[start_pos:]
    logging.info(f"Starting scan from #{start_index} ({target_tickers[0]})")
    logging.info(f"Target: Find {args.count} stocks with PENDING data issues.")

    pending_found = 0
    stocks_processed = 0

    print("\n" + "="*60)
    print(f" 🕵️  HUNT MODE: Searching for {args.count} Pending Stocks")
    print("="*60)

    for i, ticker in enumerate(target_tickers):
        idx = start_index + i
        print(f"\nProcessing #{idx}: {ticker} ... ", end="", flush=True)
        
        report = run_single_stock(
            ticker,
            scraper=scraper,
            ticker_to_industry=ticker_to_industry,
            industry_pe_map=industry_pe_map,
        )
        
        if not report:
            print("❌ Failed")
            continue

        pending_count = report["scan_summary"].get("total_pending", 0)
        industry = report["industry_context"]["industry"]
        archetype = report["archetype"]

        if pending_count > 0:
            print(f"⚠️  PENDING: {pending_count} (Arch: {archetype})")
            print(f"   -> Industry: {industry}")
            save_stock_files(report)
            pending_found += 1
        else:
            pass_count = report["scan_summary"].get("total_pass", 0)
            fail_count = report["scan_summary"].get("total_fail", 0)
            print(f"PASS: {pass_count} | FAIL: {fail_count} (Arch: {archetype})")
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