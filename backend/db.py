# backend/db.py
"""
Database utilities for AlphaQuant using Supabase REST API.
"""

import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in .env")

# Singleton client instance
_supabase: Optional[Client] = None


def get_client() -> Client:
    """Return a Supabase client instance (singleton)."""
    global _supabase
    if _supabase is None:
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


def upsert_scan_result(ticker: str, scan_type: str, data: Dict[str, Any]) -> None:
    """
    Insert or update a scan result using Supabase REST API.

    Args:
        ticker: Stock symbol (e.g., 'RELIANCE').
        scan_type: One of 'fundamentals', 'technicals', 'pricescan', etc.
        data: The full JSON-serializable scan output.
    """
    client = get_client()
    response = client.table("scan_results").upsert(
        {
            "ticker": ticker.upper(),
            "scan_type": scan_type,
            "data": data,
            "updated_at": "now()",
        },
        on_conflict="ticker, scan_type",
    ).execute()

    if hasattr(response, "error") and response.error:
        raise Exception(f"Supabase upsert error: {response.error}")


def get_scan_result(ticker: str, scan_type: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a scan result from Supabase.

    Returns:
        The stored data dictionary, or None if not found.
    """
    client = get_client()
    response = (
        client.table("scan_results")
        .select("data")
        .eq("ticker", ticker.upper())
        .eq("scan_type", scan_type)
        .execute()
    )

    if response.data:
        return response.data[0]["data"]
    return None


def get_all_tickers() -> list[str]:
    """Return a list of all distinct tickers stored in the database."""
    client = get_client()
    response = client.table("scan_results").select("ticker").execute()
    if response.data:
        return sorted({row["ticker"] for row in response.data})
    return []


def get_scan_types_for_ticker(ticker: str) -> list[str]:
    """Return all scan types available for a given ticker."""
    client = get_client()
    response = (
        client.table("scan_results")
        .select("scan_type")
        .eq("ticker", ticker.upper())
        .execute()
    )
    if response.data:
        return [row["scan_type"] for row in response.data]
    return []