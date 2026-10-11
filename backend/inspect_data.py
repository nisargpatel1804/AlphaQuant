# backend/inspect_data.py

"""
AlphaQuant Data Coverage & Schema Inspector
Audits stored JSON/Supabase data for a stock to identify complete vs. missing/null fields.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "output" / "data"


def inspect_stock_data(ticker: str) -> None:
    ticker = ticker.strip().upper()
    print("=" * 80)
    print(f" ALPHAQUANT DATA COVERAGE & SCHEMA INSPECTOR: [{ticker}]")
    print("=" * 80)

    scan_types = [
        "fundamentals",
        "technicals",
        "pricescan",
        "candlestick",
        "volumedelivery",
        "fo",
        "strikeoptions",
        "seasonality",
        "peers",
    ]

    total_scans = len(scan_types)
    available_scans = 0

    for st in scan_types:
        file_path = DATA_DIR / f"{ticker}_{st}.json"
        print(f"\n📁 [{st.upper()}]")
        print("-" * 40)

        if not file_path.exists():
            print(f"❌ File missing: {file_path.name}")
            continue

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"❌ Error reading JSON: {e}")
            continue

        if not data:
            print("⚠️ File exists but contains EMPTY dict {}")
            continue

        available_scans += 1

        # Analyze structure based on scanner type
        if st == "fundamentals":
            ratios = data.get("core_metrics", {}).get("historical_ratios", {})
            raw_fin = data.get("raw_financials", {})
            print(f"  • Scraped Timestamp: {data.get('scraped_at')}")
            print(f"  • Historical Ratio Years Count: {len(ratios)} (Years: {list(ratios.keys())})")
            print(f"  • Financial Tables Available: {list(raw_fin.keys())}")
            
            # Check ratio completeness
            if ratios:
                sample_yr = list(ratios.keys())[-1]
                null_keys = [k for k, v in ratios[sample_yr].items() if v is None]
                valid_keys = [k for k, v in ratios[sample_yr].items() if v is not None]
                print(f"  • Year {sample_yr} Valid Metrics ({len(valid_keys)}): {valid_keys}")
                print(f"  • Year {sample_yr} Null Metrics  ({len(null_keys)}): {null_keys}")

        elif st == "technicals":
            cats = data.get("categories", {})
            print(f"  • Last Close: ₹{data.get('last_close')}")
            print(f"  • Indicator Categories ({len(cats)}): {list(cats.keys())}")
            
            pending_count = 0
            active_count = 0
            for cat_name, cat_data in cats.items():
                for scan in cat_data.get("scans", []):
                    if scan.get("status") == "Pending" or scan.get("value") is None:
                        pending_count += 1
                    else:
                        active_count += 1
            print(f"  • Calculated Active Indicators: {active_count}")
            print(f"  • Pending / Null Indicators   : {pending_count}")

        elif st == "pricescan":
            cats = data.get("categories", {})
            summary = data.get("scan_summary", {})
            print(f"  • Subtypes Calculated: {len(cats)}")
            print(f"  • Total Triggered Signals: {summary.get('triggered_total')}")
            print(f"  • Signal Breakdown: {summary.get('signals')}")

        elif st == "candlestick":
            summary = data.get("scan_summary", {})
            print(f"  • Pattern Categories: {len(data.get('categories', {}))}")
            print(f"  • Patterns Triggered: {summary.get('triggered_total')}")

        elif st == "volumedelivery":
            summary = data.get("scan_summary", {})
            print(f"  • Volume Categories: {len(data.get('categories', {}))}")
            print(f"  • Scans Triggered   : {summary.get('triggered_total')}")

        elif st == "fo":
            summary = data.get("scan_summary", {})
            oi = data.get("last_oi")
            pcr = data.get("last_pcr")
            print(f"  • Last Open Interest: {oi if oi is not None else 'NULL (Unavailable)'}")
            print(f"  • Last PCR          : {pcr if pcr is not None else 'NULL (Unavailable)'}")
            print(f"  • Scans Triggered   : {summary.get('triggered_total')}")

        elif st == "seasonality":
            monthly = data.get("avgMonthlyPerf", {})
            datalist = data.get("dataList", [])
            print(f"  • Avg Monthly Perf Months Count: {len(monthly)}")
            print(f"  • Historical Years Available    : {len(datalist)}")

        elif st == "peers":
            peers_list = data.get("peers", [])
            print(f"  • Peers Found Count: {len(peers_list)}")
            if peers_list:
                names = [p.get("name") for p in peers_list[:5]]
                print(f"  • First 5 Peers    : {names}")

    print("\n" + "=" * 80)
    print(f" SUMMARY: [{available_scans}/{total_scans}] Scanner Datasets Successfully Available.")
    print("=" * 80)


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE"
    inspect_stock_data(symbol)