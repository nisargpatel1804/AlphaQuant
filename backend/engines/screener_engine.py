# backend/engines/screener_engine.py

"""
AlphaQuant Vectorized Screener Engine
- Universal Vectorized Flattening: Evaluates cross-domain rules in milliseconds.
- Safe Tokenization: Converts metric strings to secure tokens to prevent Pandas SyntaxErrors.
- Modular Namespaces: Categorizes metrics into Fundamentals, Technicals, Derivatives, EOD.
- Smart Typeahead: Search API for frontend autocomplete suggestions.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.core.db import get_all_tickers
from backend.engines.metrics_engine import MetricsEngine

logger = logging.getLogger("ScreenerEngine")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "output" / "data"

# Memory Cache for the Universe DataFrame and Metadata
_UNIVERSE_DF: Optional[pd.DataFrame] = None
_METRIC_METADATA: Dict[str, Dict[str, Any]] = {}
_TOKEN_MAP: Dict[str, str] = {}
_REVERSE_TOKEN_MAP: Dict[str, str] = {}


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


def _categorize_metric(metric: str) -> str:
    """Intelligently groups flattened metrics into UI-ready modular namespaces."""
    m = metric.lower()
    if any(x in m for x in ['delivery', 'volume ratio', 'current_volume', 'average_volume']):
        return 'EOD / Volume'
    if any(x in m for x in ['oi', 'pcr', 'max pain', 'strike', 'build-up', 'call', 'put', 'contracts', 'expiry']):
        return 'Derivatives'
    if any(x in m for x in ['sma', 'ema', 'rsi', 'macd', 'atr', 'bollinger', 'supertrend', 'ichimoku', 
                            'stochastic', 'cci', 'mfi', 'williams', 'roc', 'momentum', 'power', 
                            'vwma', 'hma', 'range', 'rs_', 'beta', 'pivot', 'support', 'resistance', 'trend']):
        return 'Technicals'
    return 'Fundamentals'


def _build_metadata_and_tokens(df: pd.DataFrame) -> None:
    """
    Builds typing metadata for the frontend and generates secure VAR_XXX tokens 
    to protect Pandas evaluation from special characters like %, /, (, ).
    """
    global _METRIC_METADATA, _TOKEN_MAP, _REVERSE_TOKEN_MAP
    _METRIC_METADATA.clear()
    _TOKEN_MAP.clear()
    _REVERSE_TOKEN_MAP.clear()

    for i, col in enumerate(df.columns):
        # 1. Type Assessment
        dtype = "numeric" if pd.api.types.is_numeric_dtype(df[col]) else "categorical"
        
        # 2. Namespace Assignment
        category = _categorize_metric(col)
        
        _METRIC_METADATA[col] = {
            "category": category,
            "type": dtype
        }

        # 3. Secure Token Generation
        token = f"VAR_{i:04d}"
        _TOKEN_MAP[col] = token
        _REVERSE_TOKEN_MAP[token] = col


def get_universe_df(force_refresh: bool = False) -> pd.DataFrame:
    """Loads all pre-calculated metrics into a singleton Pandas DataFrame."""
    global _UNIVERSE_DF
    if _UNIVERSE_DF is not None and not _UNIVERSE_DF.empty and not force_refresh:
        return _UNIVERSE_DF

    logger.info("Loading universe into memory for instant vectorized screening...")
    engine = MetricsEngine()
    tickers = get_all_available_tickers()

    _UNIVERSE_DF = engine.build_universe_dataframe(tickers)

    if not _UNIVERSE_DF.empty:
        _build_metadata_and_tokens(_UNIVERSE_DF)

    logger.info(f"Universe loaded: {_UNIVERSE_DF.shape[0]} stocks, {_UNIVERSE_DF.shape[1]} metrics.")
    return _UNIVERSE_DF


def get_available_metrics() -> Dict[str, Dict[str, Any]]:
    """Returns the categorized schema dictionary for the UI Filter Builder."""
    get_universe_df()
    return _METRIC_METADATA


def search_metrics(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Smart recommendation endpoint for the UI Typeahead dropdown.
    Ignores leading/trailing spaces and returns strict valid matches.
    """
    get_universe_df()
    
    if not query or not query.strip():
        return []
        
    safe_query = query.strip().lower()
    results = []
    
    for metric, meta in _METRIC_METADATA.items():
        if safe_query in metric.lower():
            results.append({
                "metric": metric,
                "category": meta["category"],
                "type": meta["type"]
            })
            
    # Sort strictly: Exact prefix matches first, then by shortest string length
    results.sort(key=lambda x: (not x["metric"].lower().startswith(safe_query), len(x["metric"])))
    
    return results[:limit]


def translate_query(user_query: str) -> str:
    """
    Translates literal Screener syntax into safe Pandas operations.
    Strips raw names and replaces them with VAR_XXX tokens to prevent crashes.
    """
    if not user_query or not user_query.strip():
        return ""

    df = get_universe_df()
    if df.empty:
        return ""

    # Strip formatting artifacts
    query = user_query.replace('\n', ' ').replace('`', '')
    query = " ".join(query.split())

    # Standardize Logical Operators
    query = re.sub(r'\bAND\b', 'and', query, flags=re.IGNORECASE)
    query = re.sub(r'\bOR\b', 'or', query, flags=re.IGNORECASE)
    query = re.sub(r'\bNOT\b', 'not', query, flags=re.IGNORECASE)

    # Standardize '=' to '==' for strict Python evaluation
    query = re.sub(r'(?<![<>=!])=(?!=)', '==', query)

    # Sort metrics by length descending so "Sales Growth 3Y" matches before "Sales"
    sorted_metrics = sorted(_TOKEN_MAP.keys(), key=len, reverse=True)

    for metric in sorted_metrics:
        if metric in query:
            token = _TOKEN_MAP[metric]
            # Exact boundary match protecting the specific metric text
            pattern = r'(?<![a-zA-Z0-9_])' + re.escape(metric) + r'(?![a-zA-Z0-9_])'
            query = re.sub(pattern, token, query)

    return query


def run_screener_query(user_query: str) -> Tuple[List[Dict[str, Any]], str, int]:
    """
    Executes the strict vectorized query across the universally flattened DataFrame.
    """
    df = get_universe_df()
    if df.empty:
        return [], "No stock data available in database. Please run update_all.py first.", 0

    if not user_query or not user_query.strip():
        return [], "", 0

    pandas_query = translate_query(user_query)

    # Apply Safe Tokenization mapping to the DataFrame prior to evaluation
    temp_df = df.rename(columns=_TOKEN_MAP)

    try:
        filtered_temp = temp_df.query(pandas_query)
        
        # Restore actual metric names for the frontend payload
        filtered_df = filtered_temp.rename(columns=_REVERSE_TOKEN_MAP)
        
        # Ensure institutional ranking priority
        if "Market Capitalization" in filtered_df.columns:
            filtered_df = filtered_df.sort_values(by="Market Capitalization", ascending=False)

        # JSON safety cast
        clean_filtered = filtered_df.replace({np.nan: None})
        
        # We preserve the index (Ticker) inside the payload for rendering
        clean_filtered = clean_filtered.reset_index().rename(columns={"index": "Ticker"})
        results = clean_filtered.to_dict('records')
        
        return results, "", len(results)
    
    except Exception as e:
        logger.error(f"Screener Query Failed: '{user_query}' -> '{pandas_query}' | Error: {e}")
        return [], f"Query Error: Please ensure metric names match the exact autocomplete suggestions and string values are in quotes. Detail: {str(e)}", 0