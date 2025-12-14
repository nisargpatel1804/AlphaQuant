"""
Utility helper functions for the Fundamentals module.
Handles Nifty ticker discovery, industry mapping loading, and common data utilities.
"""
from __future__ import annotations

import csv
import json
import os
import random
import time
import requests
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

# Constants
NIFTY_500_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# Path Resolution
# Assuming this file is at root/fundamentals/utils.py
_FUNDAMENTALS_DIR = Path(__file__).resolve().parent
_SOURCE_DIR = _FUNDAMENTALS_DIR / "source"

def get_nifty_tickers(
    session: Optional[requests.Session] = None,
    *,
    retries: int = 4,
    backoff_seconds: float = 1.5,
) -> List[str]:
    """
    Return the list of clean tickers from the official Nifty 500 CSV.
    Tries to download first, falls back to local file if download fails.
    """
    sess = session or requests.Session()
    # Handle SSL context for legacy environments if needed, generally requests handles it
    adapters = requests.adapters.HTTPAdapter(max_retries=0)
    sess.mount("https://", adapters)
    
    last_error: Optional[Exception] = None

    # 1. Try Downloading
    for attempt in range(1, retries + 1):
        try:
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            response = sess.get(NIFTY_500_URL, timeout=30, headers=headers)
            response.raise_for_status()
            
            decoded = response.content.decode("utf-8", errors="replace")
            reader = csv.DictReader(decoded.splitlines())
            tickers = []
            for row in reader:
                symbol = (row.get("Symbol") or "").strip().upper()
                if symbol:
                    tickers.append(symbol)
            return tickers
        except requests.RequestException as exc:
            last_error = exc
            if attempt == retries:
                break
            sleep_for = min(backoff_seconds * attempt, 10.0)
            time.sleep(sleep_for)

    # 2. Fallback to Local File
    fallback_path = _SOURCE_DIR / "ind_nifty500list.csv"
    if fallback_path.exists():
        try:
            with open(fallback_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                return [row["Symbol"].strip().upper() for row in reader if row.get("Symbol")]
        except Exception:
            pass

    # If all fails
    raise RuntimeError("Failed to download Nifty 500 list and no local fallback found.") from last_error


def load_master_industry_map() -> List[Dict[str, Any]]:
    """Loads the master industry mapping JSON file."""
    path = _SOURCE_DIR / "master_industry_map.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
    except Exception:
        return []


def build_ticker_to_industry_and_pe(master_map: List[Dict[str, Any]]) -> Tuple[Dict[str, str], Dict[str, float]]:
    """
    Processes the master map into lookup dictionaries.
    
    Returns:
        ticker_to_industry (dict): {"RELIANCE": "Refineries", ...}
        industry_to_pe (dict): {"Refineries": 12.5, ...}
    """
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
            except (ValueError, TypeError):
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
) -> None:
    """
    Enriches a stock payload dictionary with Industry Name and Industry PE
    based on the lookups provided. Modifies payload in-place.
    """
    t = ticker.strip().upper()
    industry = ticker_to_industry.get(t)
    
    # Ensure metadata dict exists
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        payload["metadata"] = metadata

    if industry:
        metadata["industry"] = industry
        pe = industry_to_pe.get(industry)
        if pe is not None:
            metadata["industry_pe"] = pe
            # Also set at root level if your schema uses it there
            payload["industry_pe"] = pe