# backend/screener_engine.py

"""
AlphaQuant Vectorized Screener Engine
Loads the universe into memory and evaluates STRICT case-sensitive Screener.in
syntax queries using Pandas vectorization in milliseconds.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.db import get_all_tickers
from backend.metrics_engine import MetricsEngine

logger = logging.getLogger("ScreenerEngine")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "output" / "data"

# Memory Cache for the Universe DataFrame
_UNIVERSE_DF: Optional[pd.DataFrame] = None
_AVAILABLE_METRICS: List[str] = []


def get_all_available_tickers() -> List[str]:
    """Retrieves all distinct tickers from DB and local JSON cache."""
    tickers = set()
    try:
        db_tickers = get_all_tickers()
        if db_tickers:
            tickers.update(db_tickers)
    except Exception as e:
        logger.debug(f"DB ticker fetch notice: {e}")

    if DATA_DIR.exists():
        for p in DATA_DIR.glob("*_fundamentals.json"):
            sym = p.stem.replace("_fundamentals", "").upper()
            if sym:
                tickers.add(sym)

    if not tickers:
        tickers = {"RELIANCE"}

    return sorted(list(tickers))


def get_universe_df(force_refresh: bool = False) -> pd.DataFrame:
    """Loads all pre-calculated metrics into a singleton Pandas DataFrame."""
    global _UNIVERSE_DF, _AVAILABLE_METRICS
    if _UNIVERSE_DF is not None and not _UNIVERSE_DF.empty and not force_refresh:
        return _UNIVERSE_DF

    logger.info("Loading universe into memory for instant vectorized screening...")
    engine = MetricsEngine()
    tickers = get_all_available_tickers()

    _UNIVERSE_DF = engine.build_universe_dataframe(tickers)

    if not _UNIVERSE_DF.empty:
        _AVAILABLE_METRICS = sorted(list(_UNIVERSE_DF.columns))

    logger.info(f"Universe loaded: {_UNIVERSE_DF.shape[0]} stocks, {_UNIVERSE_DF.shape[1]} metrics.")
    return _UNIVERSE_DF


def get_available_metrics() -> List[str]:
    """Returns the list of all strictly available screening metrics."""
    get_universe_df()
    return _AVAILABLE_METRICS


def translate_query(user_query: str) -> str:
    """
    Translates exact Screener.in syntax to Pandas query syntax.
    Enforces STRICT CASE-SENSITIVITY for metric names.
    Flattens newlines to prevent Pandas SyntaxError 500s.
    """
    if not user_query or not user_query.strip():
        return ""

    df = get_universe_df()
    if df.empty:
        return ""

    # 1. FIX THE 500 ERROR: Flatten all newlines so Pandas eval() doesn't crash
    query = user_query.replace('\n', ' ')
    query = " ".join(query.split())

    # 2. Strict case-sensitive replacement of exact available metric names
    # Sort by length descending to match longest phrases first (e.g. "Sales growth 3Years" before "Sales")
    metrics = sorted(list(df.columns), key=len, reverse=True)

    for metric in metrics:
        if metric in query:
            # Custom regex boundary: Match the metric exactly if it's not already wrapped in backticks `
            # Lookbehinds/Lookaheads ensure we don't accidentally replace partial words
            pattern = r'(?:(?<=^)|(?<=[^\w`]))(' + re.escape(metric) + r')(?:(?=[^\w`])|(?=$))'
            query = re.sub(pattern, r'`\1`', query)

    # 3. Standardize logical operators for Pandas
    query = re.sub(r'\bAND\b', 'and', query)
    query = re.sub(r'\bOR\b', 'or', query)
    query = re.sub(r'\bNOT\b', 'not', query)

    # 4. Convert standalone '=' to '==' (ignoring >=, <=, !=, ==)
    query = re.sub(r'(?<![<>=!])=(?!=)', '==', query)

    return query


def run_screener_query(user_query: str) -> Tuple[List[Dict[str, Any]], str, int]:
    """
    Executes the query across the universe and returns the matching stocks.
    """
    df = get_universe_df()
    if df.empty:
        return [], "No stock data available in database. Please run update_all.py first.", 0

    if not user_query or not user_query.strip():
        return [], "", 0

    pandas_query = translate_query(user_query)

    try:
        filtered_df = df.query(pandas_query)
        
        if "Market Capitalization" in filtered_df.columns:
            filtered_df = filtered_df.sort_values(by="Market Capitalization", ascending=False)

        clean_filtered = filtered_df.replace({np.nan: None})
        results = clean_filtered.reset_index().to_dict('records')
        return results, "", len(results)
    
    except Exception as e:
        logger.error(f"Screener Query Failed: '{user_query}' -> '{pandas_query}' | Error: {e}")
        return [], f"Query Error: Ensure metric names match exactly (Case-Sensitive). Details: {str(e)}", 0