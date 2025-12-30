"""
Seasonality scraper for Moneycontrol.

Features:
- Extracts the SEASONALITY ANALYSIS section (from the H1 header through the first seasonality table)
- Parses the JSON payload from __NEXT_DATA__ (apiData) for structured values
- Supports scraping:
  1) Generic landing page: https://www.moneycontrol.com/markets/seasonality-analysis
  2) Specific stock pages via id=...: .../seasonality-analysis?id=<ID>&type=stock&ex=N
  3) All stocks that have a moneycontrol_link in stock_links.json (root of repo)

Output:
- Writes JSON files under data/shared/seasonality
  File name pattern:
    - index.json for the generic landing page
    - <id>.json for explicit ids
    - <symbol>.json for symbols from stock_links.json (falls back to <id>.json if symbol unknown)

CLI:
  - python scrapers/shared/seasonality.py                # scrape landing + sample ids + all from stock_links.json
  - python scrapers/shared/seasonality.py --ids RI,TEL   # scrape explicit ids
  - python scrapers/shared/seasonality.py --symbols RELIANCE,INFY  # scrape by symbols from stock_links.json
  - python scrapers/shared/seasonality.py --all          # scrape all from stock_links.json

Notes:
- Resiliently locates the H1 text "SEASONALITY ANALYSIS" and the following table with Year/Jan..Dec headers.
- Stores both the raw HTML snippet and the structured apiData when available.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup, Tag


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
UA_ROTATION = [
    USER_AGENT,
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]
COMMON_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}


def _get(url: str, session: Optional[requests.Session] = None, timeout: int = 25) -> Optional[requests.Response]:
    sess = session or requests.Session()
    try:
        resp = sess.get(url, headers={**COMMON_HEADERS, "User-Agent": USER_AGENT, "Referer": "https://www.moneycontrol.com/"}, timeout=timeout)
        if resp.status_code >= 400:
            return None
        return resp
    except Exception:
        return None


def _warmup_session(sess: requests.Session) -> None:
    """Hit a few site pages to pick up cookies before target fetch."""
    try:
        sess.headers.update({**COMMON_HEADERS, "User-Agent": USER_AGENT})
        # landing
        sess.get("https://www.moneycontrol.com/", timeout=15)
        sess.get("https://www.moneycontrol.com/markets/seasonality-analysis", timeout=15)
    except Exception:
        pass


def _fetch_with_retries(url: str, session: Optional[requests.Session] = None, max_retries: int = 4, sleep: float = 0.6) -> Optional[requests.Response]:
    sess = session or requests.Session()
    _warmup_session(sess)
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        ua = UA_ROTATION[attempt % len(UA_ROTATION)]
        try:
            resp = sess.get(
                url,
                headers={**COMMON_HEADERS, "User-Agent": ua, "Referer": "https://www.moneycontrol.com/markets/seasonality-analysis"},
                timeout=25,
            )
            # Some WAFs return 403/503 while still setting cookies. Retry after short delay.
            if resp.status_code in (200, 201):
                return resp
            if resp.status_code in (403, 429, 503):
                time.sleep(sleep)
                continue
            # For other 4xx/5xx, no point retrying too much
            if 400 <= resp.status_code < 600:
                time.sleep(0.3)
                continue
            return resp
        except Exception as e:
            last_exc = e
            time.sleep(sleep)
            continue
    return None


def _workspace_root() -> str:
    # Walk up directories looking for a repository root indicator such as
    # `stock_links.json` or `app.py`. This makes the script resilient when
    # placed under `AlphaQuant/` or `scrapers/shared/` layouts.
    here = os.path.dirname(os.path.abspath(__file__))
    cur = here
    for _ in range(6):
        # Prefer an explicit stock_links.json at this level
        if os.path.exists(os.path.join(cur, "stock_links.json")):
            return cur
        # Accept repo root indicators as fallback
        if os.path.exists(os.path.join(cur, "app.py")) or os.path.exists(os.path.join(cur, "requirements.txt")):
            return cur
        parent = os.path.abspath(os.path.join(cur, ".."))
        if parent == cur:
            break
        cur = parent
    # Last resort: return the parent directory of this file
    return os.path.abspath(os.path.join(here, ".."))


def _repo_root() -> str:
    """Find the repository root (where top-level app.py/requirements.txt/RESULTS live).

    This walks up from the module directory and prefers a directory containing
    `app.py`, `requirements.txt`, `.git` or an existing `RESULTS` folder.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    cur = here
    for _ in range(10):
        if os.path.exists(os.path.join(cur, "app.py")) or os.path.exists(os.path.join(cur, "requirements.txt")) or os.path.exists(os.path.join(cur, "RESULTS")) or os.path.exists(os.path.join(cur, ".git")):
            return cur
        parent = os.path.abspath(os.path.join(cur, ".."))
        if parent == cur:
            break
        cur = parent
    # Fallback to workspace_root if nothing else found
    return _workspace_root()


def _stock_links_path() -> str:
    return os.path.join(_workspace_root(), "stock_links.json")


def _output_dir() -> str:
    return os.path.join(_workspace_root(), "data", "shared", "seasonality")


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _extract_next_data(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
    try:
        script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if script_tag and script_tag.string:
            return json.loads(script_tag.string)
    except Exception:
        return None
    return None


def _find_seasonality_header(soup: BeautifulSoup) -> Optional[Tag]:
    # Prefer matching by text to avoid CSS hash churn
    header = soup.find(lambda tag: tag.name in {"h1", "h2", "div", "span"}
                       and isinstance(tag, Tag)
                       and tag.get_text(strip=True).upper() == "SEASONALITY ANALYSIS")
    if header:
        return header
    # Fallback by class pattern
    return soup.find(class_=re.compile(r"seasonality.*sec.*title", re.I))


def _is_seasonality_table(tag: Tag) -> bool:
    if tag.name != "table":
        return False
    # Look for expected header labels
    header_text = tag.get_text(separator=" ", strip=True).lower()
    expected = [
        "year", "jan", "feb", "mar", "apr", "may", "jun", "jul",
        "aug", "sep", "oct", "nov", "dec", "yearly returns",
    ]
    return all(x in header_text for x in ["year", "jan", "feb", "mar", "apr", "may", "dec"]) and "yearly" in header_text


def _collect_html_from_header_to_table(header: Tag) -> Tuple[str, Optional[Tag]]:
    # Walk siblings from header onwards until we encounter the target table; include header and table in output
    parts: List[str] = [str(header)]
    current = header
    found_table: Optional[Tag] = None
    # Limit traversal to avoid excessive capture
    for _ in range(0, 200):
        current = current.find_next_sibling()
        if current is None:
            break
        parts.append(str(current))
        if isinstance(current, Tag) and _is_seasonality_table(current):
            found_table = current
            break
    return "".join(parts), found_table


def _extract_seasonality_snippet(html: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    soup = BeautifulSoup(html, "html.parser")
    header = _find_seasonality_header(soup)
    if not header:
        return None, None
    snippet_html, _table = _collect_html_from_header_to_table(header)
    next_data = _extract_next_data(soup)
    api_data = None
    if next_data:
        api_data = next_data.get("props", {}).get("pageProps", {}).get("apiData")
    return snippet_html, api_data


def extract_stock_id_from_moneycontrol_url(url: str) -> Optional[str]:
    try:
        parts = url.rstrip("/").split("/")
        return parts[-1] if len(parts) >= 2 else None
    except Exception:
        return None


def build_seasonality_url_for_id(stock_id: str, exchange: str = "N") -> str:
    return f"https://www.moneycontrol.com/markets/seasonality-analysis?id={stock_id}&type=stock&ex={exchange}"


@dataclass
class SeasonalityResult:
    url: str
    kind: str  # index|stock
    id_or_symbol: Optional[str]
    title: Optional[str]
    snippet_html: Optional[str]
    api_data: Optional[Dict[str, Any]]
    fetched_at: str
    errors: List[str]

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)


def scrape_single(url: str, kind: str, id_or_symbol: Optional[str] = None, session: Optional[requests.Session] = None) -> SeasonalityResult:
    errors: List[str] = []
    # attempt robust fetch with retries and UA rotation
    resp = _fetch_with_retries(url, session=session)
    if not resp:
        return SeasonalityResult(
            url=url,
            kind=kind,
            id_or_symbol=id_or_symbol,
            title=None,
            snippet_html=None,
            api_data=None,
            fetched_at=datetime.utcnow().isoformat() + "Z",
            errors=["failed_fetch"],
        )
    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract page title if present
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None

    snippet_html, api_data = _extract_seasonality_snippet(resp.text)
    if snippet_html is None:
        errors.append("snippet_not_found")

    return SeasonalityResult(
        url=url,
        kind=kind,
        id_or_symbol=id_or_symbol,
        title=title,
        snippet_html=snippet_html,
        api_data=api_data,
        fetched_at=datetime.utcnow().isoformat() + "Z",
        errors=errors,
    )


def save_result(res: SeasonalityResult, symbol_hint: Optional[str] = None) -> str:
    # Special case: RELIANCE goes to RESULTS/AlphaQuant/seasonality_reliance.json
    base = (symbol_hint or (res.id_or_symbol or "UNKNOWN")).upper()
    if base == "RELIANCE":
        # Save RELIANCE seasonality into the top-level RESULTS/scans/AlphaQuant folder
        repo = _repo_root()
        out_dir = os.path.join(repo, "RESULTS", "scans", "AlphaQuant")
        _ensure_dir(out_dir)
        path = os.path.join(out_dir, "seasonality_reliance.json")
    elif res.kind == "index":
        out_dir = _output_dir()
        _ensure_dir(out_dir)
        path = os.path.join(out_dir, "index.json")
    else:
        out_dir = _output_dir()
        _ensure_dir(out_dir)
        path = os.path.join(out_dir, f"{base}.json")
    # Remove 'colour' and 'disclaimer' fields from api_data before saving
    def strip_colour_and_disclaimer(obj):
        if isinstance(obj, dict):
            # Remove 'colour' and 'disclaimer' keys at any level
            return {k: strip_colour_and_disclaimer(v) for k, v in obj.items() if k not in ("colour", "disclaimer")}
        elif isinstance(obj, list):
            return [strip_colour_and_disclaimer(x) for x in obj]
        else:
            return obj

    cleaned_api_data = strip_colour_and_disclaimer(res.api_data) if res.api_data else {}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cleaned_api_data, f, ensure_ascii=False, indent=2)
    return path


def load_stock_links(path: Optional[str] = None) -> Dict[str, Any]:
    p = path or _stock_links_path()
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def stock_id_to_symbol_map(links: Dict[str, Any]) -> Dict[str, str]:
    """Build reverse map from Moneycontrol stock id to SYMBOL from stock_links.json."""
    rev: Dict[str, str] = {}
    if not isinstance(links, dict):
        return rev
    for sym, entry in links.items():
        if not isinstance(entry, dict):
            continue
        murl = entry.get("moneycontrol_link")
        if not murl:
            continue
        sid = extract_stock_id_from_moneycontrol_url(murl)
        if sid:
            rev[sid] = str(sym).upper()
    return rev


def scrape_index_and_samples(session: Optional[requests.Session] = None) -> List[str]:
    saved: List[str] = []
    # 1) Landing page (index)
    index_url = "https://www.moneycontrol.com/markets/seasonality-analysis"
    res = scrape_single(index_url, kind="index", id_or_symbol=None, session=session)
    saved.append(save_result(res))

    # 2) Sample IDs provided by user
    sample_ids = ["RI", "TEL", "C", "HDF01", "DRL"]
    # Build reverse map so we can name files by symbol instead of ID
    links = load_stock_links()
    id_to_symbol = stock_id_to_symbol_map(links)
    for sid in sample_ids:
        url = build_seasonality_url_for_id(sid, exchange="N")
        res = scrape_single(url, kind="stock", id_or_symbol=sid, session=session)
        saved.append(save_result(res, symbol_hint=id_to_symbol.get(sid)))
        time.sleep(0.4)
    return saved


def scrape_by_symbols(symbols: Iterable[str], stock_links: Optional[Dict[str, Any]] = None, session: Optional[requests.Session] = None) -> List[str]:
    stock_links = stock_links or load_stock_links()
    saved: List[str] = []
    for sym in symbols:
        entry = stock_links.get(sym.upper()) if isinstance(stock_links, dict) else None
        if not entry or not entry.get("moneycontrol_link"):
            continue
        stock_id = extract_stock_id_from_moneycontrol_url(entry["moneycontrol_link"]) or sym
        url = build_seasonality_url_for_id(stock_id, exchange="N")
        res = scrape_single(url, kind="stock", id_or_symbol=stock_id, session=session)
        saved.append(save_result(res, symbol_hint=sym.upper()))
        time.sleep(0.4)
    return saved


def scrape_all_from_stock_links(session: Optional[requests.Session] = None) -> List[str]:
    links = load_stock_links()
    if not isinstance(links, dict):
        return []
    saved: List[str] = []
    sess = session or requests.Session()
    for sym, entry in links.items():
        money_url = entry.get("moneycontrol_link")
        if not money_url:
            continue
        stock_id = extract_stock_id_from_moneycontrol_url(money_url) or sym
        url = build_seasonality_url_for_id(stock_id, exchange="N")
        res = scrape_single(url, kind="stock", id_or_symbol=stock_id, session=sess)
        saved.append(save_result(res, symbol_hint=sym.upper()))
        time.sleep(0.35)
    return saved


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Moneycontrol Seasonality scraper")
    # Allow positional symbols for convenience: `python3 seasonality.py RELIANCE`
    parser.add_argument("symbols", nargs="*", help="Positional ticker symbols (e.g., RELIANCE)")
    parser.add_argument("--ids", type=str, default="", help="Comma-separated Moneycontrol IDs (e.g., RI,TEL,C)")
    parser.add_argument("--symbols-flag", "--symbols", dest="symbols_flag", type=str, default="", help="Comma-separated symbols present in stock_links.json")
    parser.add_argument("--all", action="store_true", help="Scrape all symbols from stock_links.json")
    parser.add_argument("--sleep", type=float, default=0.3, help="Sleep seconds between requests")
    args = parser.parse_args(argv)

    sess = requests.Session()
    saved_paths: List[str] = []

    # Normalize symbols: combine positional and flag-based inputs
    positional_syms = [s.strip().upper() for s in (args.symbols or []) if s and s.strip()]
    flag_syms = [s.strip().upper() for s in args.symbols_flag.split(",") if s.strip()] if getattr(args, "symbols_flag", "") else []
    combined_symbols = positional_syms + flag_syms

    # Default behavior: index + provided samples + all stock_links
    if not args.ids and not combined_symbols and not args.all:
        saved_paths.extend(scrape_index_and_samples(session=sess))
        saved_paths.extend(scrape_all_from_stock_links(session=sess))
    else:
        if args.ids:
            # Use reverse map to name files by symbol where possible
            links = load_stock_links()
            id_to_symbol = stock_id_to_symbol_map(links)
            for sid in [x.strip() for x in args.ids.split(",") if x.strip()]:
                url = build_seasonality_url_for_id(sid, exchange="N")
                res = scrape_single(url, kind="stock", id_or_symbol=sid, session=sess)
                saved_paths.append(save_result(res, symbol_hint=id_to_symbol.get(sid)))
                time.sleep(args.sleep)
        if combined_symbols:
            saved_paths.extend(scrape_by_symbols(combined_symbols, session=sess))
        if args.all:
            saved_paths.extend(scrape_all_from_stock_links(session=sess))

    # Print a compact summary to stdout
    print(json.dumps({"saved": saved_paths, "count": len(saved_paths)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
