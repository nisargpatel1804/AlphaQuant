"""Tickertape scraping utilities: Market Mood Index only."""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup



# No per-stock scraping; only global endpoints are used.


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}

log = logging.getLogger("tickertape_scraper")
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)


# ---------------- Data Models ----------------

@dataclass
class ScorecardCategory:
    rating: Optional[str]
    description: Optional[str]


@dataclass
class Scorecard:
    symbol: str
    url: str
    performance: ScorecardCategory
    valuation: ScorecardCategory
    growth: ScorecardCategory
    profitability: ScorecardCategory
    entry_point: ScorecardCategory
    red_flags: ScorecardCategory
    sentiment_summary: Optional[str]
    growth_drivers: List[str]
    challenges: List[str]
    raw_errors: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "url": self.url,
            "performance": asdict(self.performance),
            "valuation": asdict(self.valuation),
            "growth": asdict(self.growth),
            "profitability": asdict(self.profitability),
            "entry_point": asdict(self.entry_point),
            "red_flags": asdict(self.red_flags),
            "sentiment_summary": self.sentiment_summary,
            "growth_drivers": self.growth_drivers,
            "challenges": self.challenges,
            "raw_errors": self.raw_errors,
        }


@dataclass
class MarketMoodIndex:
    value: Optional[float]
    zone: Optional[str]
    changes: Dict[str, Any]
    nifty_returns: Dict[str, Any]

    def __init__(self, value, zone, changes, nifty_returns):
        self.value = value
        self.zone = zone
        self.changes = changes
        self.nifty_returns = nifty_returns

    def to_dict(self) -> Dict[str, Any]:
        # Only include the active zone one-hot field
        zone_labels = ["Extreme Fear", "Fear", "Greed", "Extreme Greed"]
        active_zone = None
        for z in zone_labels:
            if self.zone == z:
                active_zone = f"zone_{z.lower().replace(' ', '_')}"
                break
        one_hot = {active_zone: 1} if active_zone else {}
        # Only keep change_percent for each period in changes
        changes_pct = {period: data["change_percent"] for period, data in self.changes.items() if "change_percent" in data}
        return {
            "value": self.value,
            **one_hot,
            "changes_percent": changes_pct,
            "nifty_returns": self.nifty_returns,
        }


# Market Sectors are now handled via Moneycontrol in market_sector.py


# ---------------- HTTP helpers ----------------

def _get(url: str, session: Optional[requests.Session] = None) -> Optional[requests.Response]:
    sess = session or requests.Session()
    try:
        resp = sess.get(url, headers=HEADERS, timeout=25)
        if resp.status_code >= 400:
            log.warning("HTTP %s %s", resp.status_code, url)
            return None
        return resp
    except Exception as e:  # pragma: no cover network
        log.warning("Request failed %s: %s", url, e)
        return None


def _parse_float(txt: str) -> Optional[float]:
    if not txt:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", txt.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def _zone_from_value(v: Optional[float]) -> Optional[str]:
    """Map numeric MMI value to UI zone buckets as a fallback."""
    if v is None:
        return None
    try:
        f = float(v)
    except Exception:
        return None
    if f < 25:
        return "Extreme Fear"
    if f < 50:
        return "Fear"
    if f < 75:
        return "Greed"
    return "Extreme Greed"


# ---------------- Parsing functions ----------------

def fetch_market_mood_index(session: Optional[requests.Session] = None, html: Optional[str] = None) -> MarketMoodIndex:
    """Scrape Market Mood Index (MMI) and change stats from Tickertape.

    If html is provided, parse that instead of performing a network request.
    """
    url = "https://www.tickertape.in/market-mood-index"
    # errors: List[str] = []
    if html is None:
        resp = _get(url, session)
        if not resp:  # pragma: no cover network
            return MarketMoodIndex(None, None, None, None, {}, {}, {}, ["fetch failed"])
        page_html = resp.text
    else:
        page_html = html

    soup = BeautifulSoup(page_html, "html.parser")
    # Collapse to visible text so regex over content works even if layout changes
    text = soup.get_text(" ", strip=True)
    
    # Initialize variables
    value = None
    zone = None
    changes: Dict[str, Any] = {}
    nifty_returns: Dict[str, Any] = {}
    
    # First try the __NEXT_DATA__ JSON which holds canonical numbers
    next_data_tag = soup.find("script", id="__NEXT_DATA__")
    if next_data_tag and next_data_tag.string:
        nd = json.loads(next_data_tag.string)
        now = nd.get("props", {}).get("pageProps", {}).get("nowData", {})
        if now:
            current_val = now.get("currentValue") or now.get("indicator")
            if current_val is not None:
                value = float(current_val)
            if zone is None:
                zone = _zone_from_value(value)
            def _mk_change(prev: Dict[str, Any]) -> Optional[Dict[str, Any]]:
                if not prev or value is None:
                    return None
                old = prev.get("indicator")
                if old is None:
                    return None
                try:
                    old_f = float(old)
                    new_f = float(value)
                except Exception:
                    return None
                delta = new_f - old_f
                pct = (delta / old_f * 100.0) if old_f != 0 else 0.0
                return {
                    "from": round(old_f, 2),
                    "to": round(new_f, 2),
                    "change": round(delta, 2),
                    "change_percent": round(pct, 2),
                }
            day = now.get("lastDay", {})
            week = now.get("lastWeek", {})
            month = now.get("lastMonth", {})
            ch = _mk_change(day)
            if ch:
                changes["yesterday"] = ch
            ch = _mk_change(week)
            if ch:
                changes["last_week"] = ch
            ch = _mk_change(month)
            if ch:
                changes["last_month"] = ch
            def _ret(prev_nifty: Optional[float], curr_nifty: Optional[float]) -> Optional[float]:
                try:
                    if prev_nifty is None or curr_nifty is None:
                        return None
                    prev_f = float(prev_nifty)
                    cur_f = float(curr_nifty)
                    if prev_f == 0:
                        return 0.0
                    return round(((cur_f - prev_f) / prev_f) * 100.0, 2)
                except Exception:
                    return None
            curr_nifty = now.get("nifty")
            d_nifty = day.get("nifty") if isinstance(day, dict) else None
            w_nifty = week.get("nifty") if isinstance(week, dict) else None
            m_nifty = month.get("nifty") if isinstance(month, dict) else None
            r = _ret(d_nifty, curr_nifty)
            if r is not None:
                nifty_returns["yesterday"] = r
            r = _ret(w_nifty, curr_nifty)
            if r is not None:
                nifty_returns["week"] = r
            r = _ret(m_nifty, curr_nifty)
            if r is not None:
                nifty_returns["month"] = r

    # Fallback to visible headline like: "MMI Extreme Fear zone 18.53" if JSON absent
    if value is None or zone is None:
        m_zone_val = re.search(
            r"MMI\s+(Extreme Fear|Fear|Greed|Extreme Greed)\s+zone\s+(\d{1,3}(?:\.\d+)?)",
            text,
            re.I,
        )
        if m_zone_val:
            zone = zone or m_zone_val.group(1).title()
            value = value or _parse_float(m_zone_val.group(2))
        else:
            for script in soup.find_all("script"):
                s = (script.string or "")
                if not s:
                    continue
                if "marketMood" in s or "mmi" in s.lower():
                    vm = re.search(r"\b(\d{1,3}(?:\.\d{1,2})?)\b", s)
                    if vm and value is None:
                        value = _parse_float(vm.group(1))
                    zm = re.search(r"(Extreme Fear|Fear|Greed|Extreme Greed)", s, re.I)
                    if zm and zone is None:
                        zone = zm.group(1).title()
            if value is None:
                vm2 = re.search(r"MMI[^0-9]*(\d{1,3}(?:\.\d{1,2})?)", text, re.I)
                if vm2:
                    value = _parse_float(vm2.group(1))
            if zone is None:
                zm2 = re.search(r"(Extreme Fear|Fear|Greed|Extreme Greed)\s*zone", text, re.I)
                if zm2:
                    zone = zm2.group(1).title()
    if zone is None:
        zone = _zone_from_value(value)

    section_text = text
    def _extract_change(period_label: str, key: str) -> None:
        pat = re.compile(
            rf"{re.escape(period_label)}.*?MMI.*?(?:from|at)?\s*(\d{{1,3}}(?:\.\d+)?)\s*(?:to|→)\s*(\d{{1,3}}(?:\.\d+)?)",
            re.I | re.DOTALL,
        )
        m = pat.search(section_text)
        old_val: Optional[float] = None
        new_val: Optional[float] = None
        if m:
            old_val = _parse_float(m.group(1))
            new_val = _parse_float(m.group(2))
        else:
            m2 = re.search(rf"{re.escape(period_label)}.*?(\d{{1,3}}(?:\.\d+)?)[^\d]+(\d{{1,3}}(?:\.\d+)?)", section_text, re.I | re.DOTALL)
            if m2:
                old_val = _parse_float(m2.group(1))
                new_val = _parse_float(m2.group(2))
        if old_val is not None and new_val is not None:
            delta = new_val - old_val
            pct = (delta / old_val * 100.0) if old_val != 0 else 0.0
            changes[key] = {
                "from": round(old_val, 2),
                "to": round(new_val, 2),
                "change": round(delta, 2),
                "change_percent": round(pct, 2),
            }

    if not changes:
        _extract_change("Since yesterday", "yesterday")
        _extract_change("Since last week", "last_week")
        _extract_change("Since last month", "last_month")

    nifty_patterns = [
        (r"Since yesterday.*?NIFTY.*?([+-]?\d+(?:\.\d+)?)%", "yesterday"),
        (r"Since last week.*?NIFTY.*?([+-]?\d+(?:\.\d+)?)%", "week"),
        (r"Since last month.*?NIFTY.*?([+-]?\d+(?:\.\d+)?)%", "month"),
        (r"NIFTY.*?yesterday.*?([+-]?\d+(?:\.\d+)?)%", "yesterday"),
        (r"NIFTY.*?week.*?([+-]?\d+(?:\.\d+)?)%", "week"),
        (r"NIFTY.*?month.*?([+-]?\d+(?:\.\d+)?)%", "month"),
    ]

    if not nifty_returns:
        for pattern, period in nifty_patterns:
            match = re.search(pattern, section_text, re.I)
            if match and period not in nifty_returns:
                nifty_returns[period] = _parse_float(match.group(1))

    return MarketMoodIndex(value, zone, changes, nifty_returns)


# fetch_market_sectors removed; use stock_scraper.market_sector instead.


_CATEGORY_KEYS = [
    ("performance", re.compile(r"(?i)Performance")),
    ("valuation", re.compile(r"(?i)Valuation")),
    ("growth", re.compile(r"(?i)Growth")),
    ("profitability", re.compile(r"(?i)Profitability")),
    ("entry_point", re.compile(r"(?i)Entry\s*point")),
    ("red_flags", re.compile(r"(?i)Red\s*flags?")),
]


## scorecard category extraction now imported from score_scraper.tickertape_scorecard


## sentiment extraction now imported from score_scraper.tickertape_scorecard


## fetch_scorecard now imported from score_scraper.tickertape_scorecard


# ---------------- Orchestrator ----------------

def scrape_tickertape(delay: float = 0.0, session: Optional[requests.Session] = None) -> Dict[str, Any]:
    sess = session or requests.Session()
    out: Dict[str, Any] = {}
    log.info("Fetching Market Mood Index")
    out["market_mood_index"] = fetch_market_mood_index(sess).to_dict()
    time.sleep(delay)
    return out


# ---------------- CLI ----------------

def main(argv: List[str]) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Scrape Tickertape Market Mood Index -> JSON")
    p.add_argument("--indent", type=int, default=2, help="JSON indent")
    p.add_argument("--delay", type=float, default=0.8, help="Sleep seconds between requests")
    args = p.parse_args(argv)
    data = scrape_tickertape(delay=args.delay)
    print(json.dumps(data, indent=args.indent))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
