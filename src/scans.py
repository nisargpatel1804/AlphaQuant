"""Comprehensive logic layer that evaluates the 107 fundamental scans with Smart Filters."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

NUMBER_OF_QUARTERS_IN_YEAR = 4
MIN_SERIES_LENGTH = 3

# --- SMART FILTER CONFIGURATION ---

# Industries that do not have physical inventory
NON_INVENTORY_SECTORS = {
    "Stockbroking & Allied", "Banks", "Finance", "NBFC", "IT - Software",
    "IT - Services", "Insurance", "Asset Management", "Ratings", "Exchange",
    "Other Bank", "Housing Finance Company", "Private Bank", "Public Bank"
}

NON_INVENTORY_KEYWORDS = {
    "bank", "banking", "nbfc", "finance", "financial", "broker", "broking",
    "stockbroker", "stockbroking", "exchange", "asset management", "insurance",
    "rating", "ratings", "lending", "fintech", "credit", "housing finance",
    "microfinance", "it services", "software"
}

# Industries where Debt/Leverage/EBITDA scans are misleading
# Banks borrow money (Deposits) to lend, so High Debt is normal.
# They also don't report standard EBITDA.
FINANCIAL_SECTORS = {
    "Banks", "Finance", "NBFC", "Housing Finance", "Microfinance",
    "Other Bank", "Housing Finance Company", "Private Bank", "Public Bank",
    "Stockbroking & Allied", "Asset Management", "Insurance"
}

FINANCIAL_KEYWORDS = {
    "bank", "banking", "nbfc", "finance", "financial", "lending",
    "microfinance", "stockbroking", "brokerage", "broker", "exchange",
    "asset management", "insurance", "credit", "finserv", "fintech"
}


def _tokenize_industry(value: Optional[str]) -> List[str]:
    if not value:
        return []
    raw_tokens = re.findall(r"[a-z0-9]+", value.lower())
    tokens: List[str] = []
    for token in raw_tokens:
        if not token:
            continue
        tokens.append(token)
        if token.endswith("ies") and len(token) > 3:
            tokens.append(token[:-3] + "y")
        elif token.endswith("s") and len(token) > 3:
            tokens.append(token[:-1])
    return list(dict.fromkeys(tokens))


def _industry_matches(industry_tokens: List[str], candidates: Iterable[str]) -> bool:
    if not industry_tokens:
        return False
    token_set = set(industry_tokens)
    for candidate in candidates:
        cand_tokens = _tokenize_industry(candidate)
        if not cand_tokens:
            continue
        if set(cand_tokens).issubset(token_set):
            return True
    return False

# List of scans to strictly SKIP for Financial Sectors
FINANCIAL_SKIP_SCANS = {
    # EBITDA metrics (Banks don't have standard EBITDA)
    "scan_high_ebitda_margin", "scan_consistently_high_ebitda_margin",
    "scan_qtr_ebitda_growth_yoy", "scan_highest_qtr_ebitda", 
    "scan_highest_ann_ebitda", "scan_increasing_ev_ebitda", 
    "scan_decreasing_ev_ebitda", 
    
    # Solvency (Debt is raw material for banks)
    "scan_no_leverage", "scan_low_leverage", "scan_mod_leverage", 
    "scan_high_leverage", "scan_high_interest_coverage", 
    "scan_mod_interest_coverage", "scan_low_interest_coverage",
    "scan_high_current_ratio", "scan_mod_current_ratio", 
    "scan_low_current_ratio",
    "scan_consistently_increasing_leverage", "scan_consistently_decreasing_leverage",

    # ROCE (Banks use ROE/ROA, ROCE is less relevant)
    "scan_high_roce", "scan_improved_roce", "scan_consistently_high_roce",
    
    # Working Capital (Concepts differ for banks)
    "scan_increasing_debtor_days", "scan_decreasing_debtor_days",
    "scan_increasing_payable_days", "scan_decreasing_payable_days",
    "scan_increasing_inventory_days", "scan_decreasing_inventory_days",
    "scan_increasing_working_cap_days", "scan_decreasing_working_cap_days"
}

@dataclass(frozen=True)
class ScanDefinition:
    name: str
    label: str
    category: str


def _build_scan_definitions() -> Tuple[ScanDefinition, ...]:
    profitability = [
        ("scan_high_roe", "High ROE (> 15%)"),
        ("scan_high_roce", "High ROCE (> 15%)"),
        ("scan_improved_roe", "Improved ROE YoY"),
        ("scan_improved_roce", "Improved ROCE YoY"),
        ("scan_qtr_net_profit_growth_yoy", "Quarterly Net Profit Growth YoY"),
        ("scan_qtr_ebitda_growth_yoy", "Quarterly EBITDA Growth YoY"),
        ("scan_highest_qtr_net_profit", "Highest Quarterly Net Profit"),
        ("scan_highest_qtr_ebitda", "Highest Quarterly EBITDA"),
        ("scan_highest_ann_net_profit", "Highest Annual Net Profit"),
        ("scan_highest_ann_ebitda", "Highest Annual EBITDA"),
        ("scan_turnaround_yoy", "Turnaround Net Profit YoY"),
        ("scan_consistent_inc_qtr_eps", "Consistently Increasing Quarterly EPS"),
        ("scan_consistent_dec_qtr_eps", "Consistently Decreasing Quarterly EPS"),
        ("scan_consistent_inc_ann_eps", "Consistently Increasing Annual EPS"),
        ("scan_consistent_dec_ann_eps", "Consistently Decreasing Annual EPS"),
        ("scan_high_ebitda_margin", "High EBITDA Margin (>20%)"),
        ("scan_consistently_high_ebitda_margin", "Consistently High EBITDA Margin"),
        ("scan_high_pat_margin", "High PAT Margin (>10%)"),
        ("scan_consistently_high_pat_margin", "Consistently High PAT Margin"),
        ("scan_consistently_high_roe", "Consistently High ROE (>15%)"),
        ("scan_consistently_high_roce", "Consistently High ROCE (>15%)"),
    ]

    turnover = [
        ("scan_high_qtr_sales_growth", "High Quarterly Sales Growth (>15%)"),
        ("scan_high_ann_sales_growth", "High Annual Sales Growth (>15%)"),
        ("scan_consistent_sales_growth", "Consistently Growing Annual Sales"),
        ("scan_increasing_qtr_sales", "Increasing Quarterly Sales (3 Qtrs)"),
        ("scan_highest_qtr_sales", "Highest Quarterly Sales"),
        ("scan_highest_ann_sales", "Highest Annual Sales"),
    ]

    solvency = [
        ("scan_no_leverage", "No Leverage (Debt=0)"),
        ("scan_low_leverage", "Low Leverage (<0.5x)"),
        ("scan_mod_leverage", "Moderate Leverage (0.5-1.0x)"),
        ("scan_high_leverage", "High Leverage (>1.0x)"),
        ("scan_high_interest_coverage", "High Interest Coverage (>4x)"),
        ("scan_mod_interest_coverage", "Moderate Interest Coverage (2-4x)"),
        ("scan_low_interest_coverage", "Low Interest Coverage (<2x)"),
        ("scan_high_current_ratio", "High Current Ratio (>2x)"),
        ("scan_mod_current_ratio", "Moderate Current Ratio (1.5-2x)"),
        ("scan_low_current_ratio", "Low Current Ratio (<1.5x)"),
        ("scan_consistently_increasing_leverage", "Consistently Increasing Leverage"),
        ("scan_consistently_decreasing_leverage", "Consistently Decreasing Leverage"),
    ]

    cash_flow = [
        ("scan_increasing_cfo", "Increasing CFO YoY"),
        ("scan_consistent_positive_cfo", "Positive CFO for 3 Years"),
        ("scan_growing_cfo", "Growing CFO (3 Years)"),
        ("scan_positive_fcf", "Positive Free Cash Flow"),
        ("scan_increasing_fcf", "Increasing Free Cash Flow"),
        ("scan_consistent_positive_fcf", "Positive Free Cash Flow (3 Years)"),
        ("scan_consistently_declining_fcf", "Consistently Declining FCF"),
        ("scan_highest_ann_cfo", "Highest Annual CFO"),
    ]

    valuation = [
        ("scan_very_high_pe", "Very High PE (>50)"),
        ("scan_high_pe", "High PE (20-50)"),
        ("scan_moderate_pe", "Moderate PE (10-20)"),
        ("scan_low_pe", "Low PE (<10)"),
        ("scan_pe_above_industry", "PE Above Industry"),
        ("scan_pe_below_industry", "PE Below Industry"),
        ("scan_high_peg", "High PEG (>1.5)"),
        ("scan_low_peg", "Low PEG (<1.0)"),
        ("scan_price_above_book", "Price Above Book Value"),
        ("scan_price_below_book", "Price Below Book Value"),
        ("scan_increasing_ev_ebitda", "Increasing EV/EBITDA"),
        ("scan_decreasing_ev_ebitda", "Decreasing EV/EBITDA"),
        ("scan_high_ev_sales", "High EV/Sales (>3x)"),
        ("scan_moderate_ev_sales", "Moderate EV/Sales (1-3x)"),
        ("scan_low_ev_sales", "Low EV/Sales (<1x)"),
    ]

    dividends = [
        ("scan_consistent_dividends", "Consistent Dividend Payout (5 Years)"),
        ("scan_positive_dividend_yield", "Positive Dividend Yield"),
        ("scan_high_dividend_payout", "High Dividend Payout (>30%)"),
    ]

    efficiency = [
        ("scan_increasing_debtor_days", "Increasing Debtor Days"),
        ("scan_decreasing_debtor_days", "Decreasing Debtor Days"),
        ("scan_increasing_payable_days", "Increasing Payable Days"),
        ("scan_decreasing_payable_days", "Decreasing Payable Days"),
        ("scan_increasing_inventory_days", "Increasing Inventory Days"),
        ("scan_decreasing_inventory_days", "Decreasing Inventory Days"),
        ("scan_increasing_working_cap_days", "Increasing Working Capital Days"),
        ("scan_decreasing_working_cap_days", "Decreasing Working Capital Days"),
        ("scan_high_gfa_increase", "High Fixed Asset Increase (>10%)"),
        ("scan_high_gfa_increase_three_year", "Fixed Asset CAGR >10% (3Y)"),
    ]

    shareholding = [
        ("scan_share_fii_increase", "FII Buying QoQ"),
        ("scan_share_fii_decrease", "FII Selling QoQ"),
        ("scan_share_dii_increase", "DII Buying QoQ"),
        ("scan_share_dii_decrease", "DII Selling QoQ"),
        ("scan_share_promoter_increase", "Promoter Buying QoQ"),
        ("scan_share_promoter_decrease", "Promoter Selling QoQ"),
        ("scan_share_public_increase", "Public Buying QoQ"),
        ("scan_share_public_decrease", "Public Selling QoQ"),
        ("scan_share_fii_consistent_increase", "Consistent FII Buying (3 Qtrs)"),
        ("scan_share_dii_consistent_increase", "Consistent DII Buying (3 Qtrs)"),
        ("scan_share_promoter_consistent_increase", "Consistent Promoter Buying (3 Qtrs)"),
        ("scan_share_public_consistent_increase", "Consistent Public Buying (3 Qtrs)"),
        ("scan_share_promoter_very_high", "Very High Promoter Holding (>75%)"),
        ("scan_share_promoter_high", "High Promoter Holding (50-75%)"),
        ("scan_share_promoter_low", "Low Promoter Holding (<50%)"),
        ("scan_share_shareholders_increase", "Rising Shareholder Count QoQ"),
        ("scan_share_shareholders_decrease", "Falling Shareholder Count QoQ"),
        ("scan_share_shareholders_consistent_increase", "Consistently Rising Shareholder Count"),
        ("scan_share_public_high", "High Public Holding (>20%)"),
        ("scan_share_public_low", "Low Public Holding (<10%)"),
    ]

    pledge = [
        ("scan_pledge_increase", "Increasing Promoter Pledge"),
        ("scan_pledge_decrease", "Decreasing Promoter Pledge"),
        ("scan_pledge_zero", "Zero Pledge"),
        ("scan_pledge_low", "Low Pledge (<20%)"),
        ("scan_pledge_moderate", "Moderate Pledge (20-40%)"),
        ("scan_pledge_high", "High Pledge (>40%)"),
    ]

    categories = [
        ("Profitability", profitability),
        ("Turnover", turnover),
        ("Solvency", solvency),
        ("Cash Flow", cash_flow),
        ("Valuation", valuation),
        ("Dividends", dividends),
        ("Efficiency", efficiency),
        ("Shareholding", shareholding),
        ("Pledge", pledge),
    ]

    definitions: List[ScanDefinition] = []
    for category, items in categories:
        for name, label in items:
            definitions.append(ScanDefinition(name, label, category))
    return tuple(definitions)


class FundamentalScans:
    """Evaluate the 107 fundamental scans for a stock's Supabase record."""

    METADATA_FIELDS = (
        "market_cap", "current_price", "stock_pe", "book_value",
        "dividend_yield", "roce", "roe", "face_value",
        "high_price", "low_price", "pledge_data_missing",
        "industry_pe", "industry",
    )

    SCANS = _build_scan_definitions()

    def __init__(self, data: Dict[str, Any]):
        # Ensure data is a dictionary
        if not isinstance(data, dict):
            data = {}

        self.data = data
        # Core datasets must be available before metadata so derived metrics (ROE/ROCE)
        # can safely reference them during _build_metadata.
        self.quarterly = self.data.get("quarterly_results") or {}
        self.annual = self.data.get("profit_loss_annual") or {}
        self.balance_sheet = self.data.get("balance_sheet") or {}
        self.cash_flow = self.data.get("cash_flow") or {}
        self.ratios = self.data.get("ratios") or {}
        shareholding = self.data.get("shareholding") or {}
        self.shareholding_q = shareholding.get("quarterly") or {}
        self.shareholding_y = shareholding.get("yearly") or {}
        self._period_cache: Dict[int, List[str]] = {}
        self._current_value: Optional[float] = None
        self.metadata = self._build_metadata()

        # Industry context for Smart Filters
        self.industry = self.metadata.get("industry", "Unknown")
        self.archetype = self.industry  # For now, archetype is the industry
        self._industry_tokens = _tokenize_industry(self.industry)
        self._industry_text = (self.industry or "").lower()
        self.is_financial = _industry_matches(self._industry_tokens, FINANCIAL_SECTORS) or any(
            keyword in self._industry_text for keyword in FINANCIAL_KEYWORDS
        )
        self.is_non_inventory = self.is_financial or _industry_matches(self._industry_tokens, NON_INVENTORY_SECTORS) or any(
            keyword in self._industry_text for keyword in NON_INVENTORY_KEYWORDS
        )

    # ------------------------------------------------------------------
    # Helper utilities
    # ------------------------------------------------------------------
    def _build_metadata(self) -> Dict[str, Any]:
        base = dict(self.data.get("metadata") or {})
        for field in self.METADATA_FIELDS:
            # Fallback: check root data if not in metadata block
            if field not in base and field in self.data:
                base[field] = self.data[field]
        
        # Compute ROE and ROCE if missing
        if base.get("roe") is None:
            base["roe"] = self._compute_roe()
        if base.get("roce") is None:
            base["roce"] = self._compute_roce()
        
        return base

    def _record_value(self, value: Optional[float]) -> None:
        self._current_value = value

    def _get_sorted_periods(self, data_dict: Dict[str, Any]) -> List[str]:
        cache_key = id(data_dict)
        if cache_key in self._period_cache:
            return self._period_cache[cache_key]
        parsed: List[Tuple[datetime, str]] = []
        for key in data_dict.keys():
            dt = self._parse_period_key(key)
            if dt is None: continue
            parsed.append((dt, key))
        parsed.sort(key=lambda item: item[0], reverse=True)
        ordered = [item[1] for item in parsed]
        self._period_cache[cache_key] = ordered
        return ordered

    @staticmethod
    def _parse_period_key(key: str) -> Optional[datetime]:
        if not key: return None
        if key.strip().upper() == "TTM": return datetime.max
        for fmt in ("%b %Y", "%b %y", "%B %Y"):
            try: return datetime.strptime(key, fmt)
            except ValueError: continue
        return None

    def _get_value(self, dataset: Dict[str, Any], index: int, metric: str) -> Optional[float]:
        periods = self._get_sorted_periods(dataset)
        if index >= len(periods): return None
        return dataset.get(periods[index], {}).get(metric)

    def _get_series(self, dataset: Dict[str, Any], metric: str, limit: Optional[int] = None) -> List[Optional[float]]:
        periods = self._get_sorted_periods(dataset)
        if limit is not None: periods = periods[:limit]
        return [dataset.get(p, {}).get(metric) for p in periods]

    def _has_metric_history(self, dataset: Dict[str, Any], metric: str, min_count: int) -> bool:
        count = 0
        for period in self._get_sorted_periods(dataset):
            value = dataset.get(period, {}).get(metric)
            if value is not None:
                count += 1
                if count >= min_count:
                    return True
        return False

    @staticmethod
    def _safe_growth(current: Optional[float], previous: Optional[float]) -> Optional[float]:
        if current is None or previous is None: return None
        if previous == 0: return 999.0 if current > 0 else (-999.0 if current < 0 else 0.0)
        try: return (current - previous) / abs(previous) * 100
        except ZeroDivisionError: return None

    @staticmethod
    def _check_consistency(values: Iterable[Optional[float]], *, increasing: bool) -> Optional[bool]:
        cleaned = [v for v in values if v is not None]
        if len(cleaned) < MIN_SERIES_LENGTH: return None
        pairs = list(zip(cleaned[:-1], cleaned[1:]))
        if not pairs: return None
        return all(curr > prev for prev, curr in pairs) if increasing else all(curr < prev for prev, curr in pairs)

    @staticmethod
    def _safe_divide(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
        if numerator is None or denominator is None: return None
        if denominator == 0: return 0.0
        try: return numerator / denominator
        except ZeroDivisionError: return None

    def _is_loss_making(self) -> bool:
        """Check if the company is loss-making based on latest fiscal year net profit (excluding TTM)."""
        # Get sorted periods and skip TTM if it's the first one
        periods = self._get_sorted_periods(self.annual)
        if not periods:
            return False
        
        # Use first non-TTM period for loss-making determination
        idx = 0
        if periods[0].strip().upper() == "TTM" and len(periods) > 1:
            idx = 1
        
        np = self._get_value(self.annual, idx, "net_profit")
        return np is not None and np < 0

    def _compute_roe(self) -> Optional[float]:
        """Compute ROE dynamically from latest data."""
        np = self._get_value(self.annual, 0, "net_profit")
        eq = self._get_value(self.balance_sheet, 0, "equity_capital")
        res = self._get_value(self.balance_sheet, 0, "reserves")
        den = None if eq is None or res is None else eq + res
        roe = self._safe_divide(np, den)
        return roe * 100 if roe is not None else None

    def _compute_roce(self) -> Optional[float]:
        """Compute ROCE dynamically from latest data."""
        # ROCE = EBIT / Capital Employed
        # Capital Employed = Total Assets - Current Liabilities
        ebit = self._get_value(self.quarterly, 0, "operating_profit")  # or annual
        if ebit is None:
            ebit = self._get_value(self.annual, 0, "operating_profit")
        ta = self._get_value(self.balance_sheet, 0, "total_assets")
        cl = self._get_value(self.balance_sheet, 0, "current_liabilities")
        ce = self._safe_divide(ta - cl, 1) if ta is not None and cl is not None else None
        roce = self._safe_divide(ebit, ce)
        return roce * 100 if roce is not None else None

    def _same_quarter_last_year(self, metric: str) -> Tuple[Optional[float], Optional[float]]:
        periods = self._get_sorted_periods(self.quarterly)
        if len(periods) <= NUMBER_OF_QUARTERS_IN_YEAR: return None, None
        return self.quarterly.get(periods[0], {}).get(metric), self.quarterly.get(periods[NUMBER_OF_QUARTERS_IN_YEAR], {}).get(metric)

    def _highest_vs_history(self, dataset: Dict[str, Any], metric: str) -> Optional[bool]:
        periods = self._get_sorted_periods(dataset)
        if len(periods) < 2: return None
        latest = dataset.get(periods[0], {}).get(metric)
        history = [dataset.get(p, {}).get(metric) for p in periods[1:]]
        history = [v for v in history if v is not None]
        if latest is None or not history: return None
        return latest > max(history)

    def _annual_margin_series(self, metric: str, threshold: float, *, greater: bool = True) -> Optional[bool]:
        values = self._get_series(self.annual, metric, MIN_SERIES_LENGTH)
        valid = [v for v in values if v is not None]
        if len(valid) < MIN_SERIES_LENGTH: return None
        comp = (lambda v: v > threshold) if greater else (lambda v: v < threshold)
        return all(comp(v) for v in valid[:MIN_SERIES_LENGTH])

    def _annual_pat_margin(self, index: int = 0) -> Optional[float]:
        ratio = self._safe_divide(self._get_value(self.annual, index, "net_profit"), self._get_value(self.annual, index, "sales"))
        return None if ratio is None else ratio * 100

    def _annual_opm(self, index: int = 0) -> Optional[float]:
        return self._get_value(self.annual, index, "opm_percent")

    def _roe_series(self) -> List[float]:
        series = []
        for p in self._get_sorted_periods(self.annual):
            np = self.annual.get(p, {}).get("net_profit")
            eq = self.balance_sheet.get(p, {}).get("equity_capital")
            res = self.balance_sheet.get(p, {}).get("reserves")
            den = None if eq is None or res is None else eq + res
            roe = self._safe_divide(np, den)
            if roe is not None: series.append(roe * 100)
        return series

    def _roce_series(self) -> List[float]:
        return [v for _, v in self._series_from_ratio("roce_percent")]

    def _series_from_ratio(self, metric: str) -> List[Tuple[str, float]]:
        return [(p, self.ratios.get(p, {}).get(metric)) for p in self._get_sorted_periods(self.ratios) if self.ratios.get(p, {}).get(metric) is not None]

    def _leverage(self, index: int = 0) -> Optional[float]:
        b, e, r = self._get_value(self.balance_sheet, index, "borrowings"), self._get_value(self.balance_sheet, index, "equity_capital"), self._get_value(self.balance_sheet, index, "reserves")
        if b == 0: return 0.0
        if b is None: return None
        return self._safe_divide(b, (e + r) if e is not None and r is not None else None)

    def _interest_coverage(self) -> Optional[float]:
        op, int_exp = self._get_value(self.quarterly, 0, "operating_profit"), self._get_value(self.quarterly, 0, "interest")
        if op is None: return None
        if int_exp == 0 or int_exp is None: return 9999.0 if op > 0 else None
        return self._safe_divide(op, int_exp)

    def _current_ratio(self) -> Optional[float]:
        periods = self._get_sorted_periods(self.balance_sheet)
        for period in periods:
            bs = self.balance_sheet[period]
            ca = bs.get("current_assets")
            cl = bs.get("current_liabilities")
            
            # Calculate Current Assets if missing
            # Formula: CA = Total Assets - Fixed Assets - CWIP - Investments
            if ca is None:
                ta = bs.get("total_assets")
                fa = bs.get("fixed_assets")
                cwip = bs.get("cwip") or 0
                investments = bs.get("investments") or 0
                if ta is not None and fa is not None:
                    ca = ta - fa - cwip - investments
            
            # Calculate Current Liabilities if missing
            # Formula: CL = Total Liabilities - Equity - Reserves - Long-term Borrowings
            if cl is None:
                tl = bs.get("total_liabilities")
                equity = bs.get("equity_capital") or 0
                reserves = bs.get("reserves") or 0
                # Try long_term_borrowings first, fallback to borrowings (assuming it's long-term)
                lt_borrowings = bs.get("long_term_borrowings") or bs.get("borrowings") or 0
                if tl is not None:
                    cl = tl - equity - reserves - lt_borrowings
                    # Ensure CL is non-negative (accounting sanity check)
                    if cl is not None and cl < 0:
                        cl = None
            
            # Return ratio if both components are available
            if ca is not None and cl is not None:
                return self._safe_divide(ca, cl)
        
        return None

    def _cfo_series(self) -> List[Tuple[str, float]]:
        return [(p, self.cash_flow.get(p, {}).get("cash_from_operating")) for p in self._get_sorted_periods(self.cash_flow) if self.cash_flow.get(p, {}).get("cash_from_operating") is not None]

    def _fcf(self, index: int = 0) -> Optional[float]:
        cfo, capex = self._get_value(self.cash_flow, index, "cash_from_operating"), self._get_value(self.cash_flow, index, "cash_from_investing")
        return (cfo - abs(capex)) if cfo is not None and capex is not None else None

    def _ev(self) -> Optional[float]:
        mc = self.metadata.get("market_cap")
        if mc is None: return None
        b = self._get_value(self.balance_sheet, 0, "borrowings") or 0
        c = (self._get_value(self.balance_sheet, 0, "cash_equivalents") or self._get_value(self.balance_sheet, 0, "cash_and_cash_equivalents") or 0)
        return mc + b - c

    def _ev_ebitda(self, index: int = 0) -> Optional[float]:
        return self._safe_divide(self._ev(), self._get_value(self.annual, index, "operating_profit"))

    def _ev_sales(self, index: int = 0) -> Optional[float]:
        return self._safe_divide(self._ev(), self._get_value(self.annual, index, "sales"))

    def _peg(self) -> Optional[float]:
        # PEG = PE / Growth Rate
        # We allow negative PEG (negative growth) to properly categorize it as 'Failed' (bad metric) rather than 'Pending' (missing data).
        pe = self.metadata.get("stock_pe")
        g = self._safe_growth(self._get_value(self.annual, 0, "net_profit"), self._get_value(self.annual, 1, "net_profit"))
        
        if pe is None or g is None: return None
        if g == 0: return None # Avoid division by zero
        
        return pe / g

    def _dividend_series(self) -> List[float]:
        return [self.annual.get(p, {}).get("dividend_payout_percent") for p in self._get_sorted_periods(self.annual) if self.annual.get(p, {}).get("dividend_payout_percent") is not None]

    def _has_required_data(self, scan_name: str) -> bool:
        """Check if sufficient data exists to run a scan. Return False to skip the scan."""
        # Dividend scans
        if scan_name == "scan_consistent_dividends":
            return len(self._dividend_series()) >= 5
        if scan_name == "scan_high_dividend_payout":
            return len(self._dividend_series()) >= MIN_SERIES_LENGTH
        
        # EPS consistency scans
        if scan_name in {"scan_consistent_inc_ann_eps", "scan_consistent_dec_ann_eps"}:
            return self._has_metric_history(self.annual, "eps", MIN_SERIES_LENGTH)
        if scan_name in {"scan_consistent_inc_qtr_eps", "scan_consistent_dec_qtr_eps"}:
            return self._has_metric_history(self.quarterly, "eps", MIN_SERIES_LENGTH)
        
        # Book value scans
        if scan_name in {"scan_price_above_book", "scan_price_below_book"}:
            return self.metadata.get("book_value") is not None and self.metadata.get("current_price") is not None
        
        # ROE scans requiring historical data
        if scan_name == "scan_improved_roe":
            roe_series = self._roe_series()
            return len(roe_series) >= 2
        if scan_name == "scan_consistently_high_roe":
            roe_series = self._roe_series()
            return len(roe_series) >= MIN_SERIES_LENGTH
        
        # ROCE scans requiring historical data
        if scan_name in {"scan_improved_roce", "scan_consistently_high_roce"}:
            roce_series = self._roce_series()
            required = 2 if "improved" in scan_name else MIN_SERIES_LENGTH
            return len(roce_series) >= required
        
        # Profitability "highest" scans (need 2+ periods to compare)
        if scan_name in {"scan_highest_qtr_net_profit", "scan_highest_qtr_ebitda"}:
            periods = self._get_sorted_periods(self.quarterly)
            return len(periods) >= 2
        if scan_name in {"scan_highest_ann_net_profit", "scan_highest_ann_ebitda"}:
            periods = self._get_sorted_periods(self.annual)
            return len(periods) >= 2
        
        # Margin consistency scans (need MIN_SERIES_LENGTH periods)
        if scan_name == "scan_consistently_high_ebitda_margin":
            values = self._get_series(self.annual, "opm_percent", MIN_SERIES_LENGTH)
            return len([v for v in values if v is not None]) >= MIN_SERIES_LENGTH
        if scan_name == "scan_consistently_high_pat_margin":
            # Check if we can compute PAT margin for MIN_SERIES_LENGTH periods
            periods = self._get_sorted_periods(self.annual)
            return len(periods) >= MIN_SERIES_LENGTH and all(
                self.annual.get(p, {}).get("net_profit") is not None and
                self.annual.get(p, {}).get("sales") is not None
                for p in periods[:MIN_SERIES_LENGTH]
            )
        
        # Sales growth scans
        if scan_name == "scan_consistent_sales_growth":
            periods = self._get_sorted_periods(self.annual)
            # Need 4 periods to check 3 growth transitions
            return len(periods) >= 4 and all(
                self.annual.get(p, {}).get("sales") is not None 
                for p in periods[:4]
            )
        if scan_name in {"scan_highest_qtr_sales"}:
            periods = self._get_sorted_periods(self.quarterly)
            return len(periods) >= 2
        if scan_name in {"scan_highest_ann_sales"}:
            periods = self._get_sorted_periods(self.annual)
            return len(periods) >= 2
        if scan_name == "scan_high_ann_sales_growth":
            periods = self._get_sorted_periods(self.annual)
            return len(periods) >= 2 and all(
                self.annual.get(p, {}).get("sales") is not None
                for p in periods[:2]
            )
        
        # Cash flow scans
        if scan_name in {"scan_increasing_cfo"}:
            cfo_series = self._cfo_series()
            return len(cfo_series) >= 2
        if scan_name in {"scan_consistent_positive_cfo", "scan_growing_cfo"}:
            cfo_series = self._cfo_series()
            return len(cfo_series) >= MIN_SERIES_LENGTH
        if scan_name == "scan_increasing_fcf":
            periods = self._get_sorted_periods(self.cash_flow)
            return len(periods) >= 2 and all(
                self.cash_flow.get(p, {}).get("cash_from_operating") is not None and
                self.cash_flow.get(p, {}).get("cash_from_investing") is not None
                for p in periods[:2]
            )
        if scan_name in {"scan_consistent_positive_fcf", "scan_consistently_declining_fcf"}:
            # Check if we have CFO and investing cash flow for MIN_SERIES_LENGTH periods
            periods = self._get_sorted_periods(self.cash_flow)
            return len(periods) >= MIN_SERIES_LENGTH and all(
                self.cash_flow.get(p, {}).get("cash_from_operating") is not None and
                self.cash_flow.get(p, {}).get("cash_from_investing") is not None
                for p in periods[:MIN_SERIES_LENGTH]
            )
        if scan_name == "scan_highest_ann_cfo":
            periods = self._get_sorted_periods(self.cash_flow)
            return len(periods) >= 2
        
        # Solvency/Leverage scans requiring historical data
        if scan_name in {"scan_consistently_increasing_leverage", "scan_consistently_decreasing_leverage"}:
            # Need to be able to calculate leverage for MIN_SERIES_LENGTH periods
            periods = self._get_sorted_periods(self.balance_sheet)
            return len(periods) >= MIN_SERIES_LENGTH
        
        # Valuation scans requiring historical comparison
        if scan_name in {"scan_increasing_ev_ebitda", "scan_decreasing_ev_ebitda"}:
            # Need 2 periods to compare EV/EBITDA
            periods_annual = self._get_sorted_periods(self.annual)
            periods_bs = self._get_sorted_periods(self.balance_sheet)
            return len(periods_annual) >= 2 and len(periods_bs) >= 2
        
        if scan_name in {"scan_high_peg", "scan_low_peg"}:
            # PEG requires PE and EPS growth - need multiple periods for EPS
            if self.metadata.get("stock_pe") is None:
                return False
            periods = self._get_sorted_periods(self.annual)
            return len(periods) >= 2 and all(
                self.annual.get(p, {}).get("eps") is not None
                for p in periods[:2]
            )
        
        # Efficiency/Fixed Asset scans
        if scan_name == "scan_high_gfa_increase":
            periods = self._get_sorted_periods(self.balance_sheet)
            return len(periods) >= 2 and all(
                self.balance_sheet.get(p, {}).get("fixed_assets") is not None
                for p in periods[:2]
            )
        if scan_name == "scan_high_gfa_increase_three_year":
            periods = self._get_sorted_periods(self.balance_sheet)
            return len(periods) >= MIN_SERIES_LENGTH and all(
                self.balance_sheet.get(p, {}).get("fixed_assets") is not None
                for p in periods[:MIN_SERIES_LENGTH]
            )

        
        # Ratio/Efficiency scans requiring historical data
        ratio_scans = {
            "scan_increasing_debtor_days", "scan_decreasing_debtor_days",
            "scan_increasing_payable_days", "scan_decreasing_payable_days",
            "scan_increasing_inventory_days", "scan_decreasing_inventory_days",
            "scan_increasing_working_cap_days", "scan_decreasing_working_cap_days"
        }
        if scan_name in ratio_scans:
            # Extract the metric name from scan name
            metric_map = {
                "debtor": "debtor_days",
                "payable": "payable_days",
                "inventory": "inventory_days",
                "working_cap": "working_capital_days"
            }
            metric = None
            for key, value in metric_map.items():
                if key in scan_name:
                    metric = value
                    break
            if metric:
                periods = self._get_sorted_periods(self.ratios)
                return len(periods) >= MIN_SERIES_LENGTH and all(
                    self.ratios.get(p, {}).get(metric) is not None
                    for p in periods[:MIN_SERIES_LENGTH]
                )
        
        return True

    def _ratio_trend(self, field: str, *, increasing: bool) -> Optional[bool]:
        vals = [v if v is not None else 0.0 for v in self._get_series(self.ratios, field, MIN_SERIES_LENGTH)]
        self._record_value(vals[0] if vals else None)
        if len(vals) < MIN_SERIES_LENGTH: return None
        chron = list(reversed(vals))
        pairs = list(zip(chron[:-1], chron[1:]))
        return all(curr > prev for prev, curr in pairs) if increasing else all(curr <= prev for prev, curr in pairs)

    def _shareholding_delta(self, field: str, *, increasing: bool) -> Optional[bool]:
        periods = self._get_sorted_periods(self.shareholding_q)
        if len(periods) < 2:
            self._record_value(None)
            return False
        curr_period = self.shareholding_q.get(periods[0], {})
        prev_period = self.shareholding_q.get(periods[1], {})
        curr = curr_period.get(field)
        prev = prev_period.get(field)
        if field == "promoters":
            if curr is None and curr_period.get("public") is not None:
                curr = 0.0
            if prev is None and prev_period.get("public") is not None:
                prev = 0.0
        if curr is None or prev is None:
            self._record_value(None)
            return False
        delta = curr - prev
        self._record_value(delta)
        return delta > 0 if increasing else delta < 0

    def _shareholding_consistency(self, field: str) -> Optional[bool]:
        periods = self._get_sorted_periods(self.shareholding_q)
        periods = periods[:MIN_SERIES_LENGTH]
        vals: List[Optional[float]] = []
        for period in periods:
            section = self.shareholding_q.get(period, {})
            val = section.get(field)
            if val is None and field == "promoters" and section.get("public") is not None:
                val = 0.0
            vals.append(val)
        self._record_value(vals[0] if vals else None)
        cleaned = [v for v in vals if v is not None]
        if len(cleaned) < MIN_SERIES_LENGTH:
            return False
        return self._check_consistency(reversed(vals), increasing=True)

    def _shareholding_level(self, field: str, threshold_low: float, threshold_high: Optional[float] = None) -> Optional[bool]:
        val = self._get_value(self.shareholding_q, 0, field)
        if val is None and field == "promoters" and self._get_value(self.shareholding_q, 0, "public") is not None: val = 0.0
        self._record_value(val)
        if val is None: return None
        return val > threshold_low if threshold_high is None else (threshold_low <= val < threshold_high) if threshold_low > 0 else val < threshold_high

    def _shareholder_count_delta(self, increasing: bool) -> Optional[bool]:
        periods = self._get_sorted_periods(self.shareholding_q)
        if len(periods) < 2:
            self._record_value(None)
            return False
        curr, prev = self.shareholding_q.get(periods[0], {}).get("no_of_shareholders"), self.shareholding_q.get(periods[1], {}).get("no_of_shareholders")
        if curr is None or prev is None:
            self._record_value(None)
            return False
        delta = curr - prev
        self._record_value(delta)
        return delta > 0 if increasing else delta < 0

    def _pledge_values(self) -> Tuple[Optional[float], Optional[float]]:
        if self._get_value(self.shareholding_q, 0, "promoters") == 0: return 0.0, 0.0
        if self._get_value(self.shareholding_q, 0, "promoters") is None and self._get_value(self.shareholding_q, 0, "public") is not None: return 0.0, 0.0
        periods = self._get_sorted_periods(self.shareholding_q)
        if not periods: return None, None
        return self.shareholding_q.get(periods[0], {}).get("pledged_percent"), self.shareholding_q.get(periods[1], {}).get("pledged_percent") if len(periods) > 1 else None

    # ------------------------------------------------------------------
    # Profitability scans
    # ------------------------------------------------------------------
    def scan_high_roe(self) -> Optional[bool]:
        value = self.metadata.get("roe")
        if value is None:
            value = self._compute_roe()
        self._record_value(value)
        return None if value is None else value > 15

    def scan_high_roce(self) -> Optional[bool]:
        value = self.metadata.get("roce")
        if value is None:
            value = self._compute_roce()
        self._record_value(value)
        return None if value is None else value > 15

    def scan_improved_roe(self) -> Optional[bool]:
        series = self._roe_series()
        if len(series) < 2:
            return None
        self._record_value(series[0])
        return series[0] > series[1]

    def scan_improved_roce(self) -> Optional[bool]:
        series = self._roce_series()
        if len(series) < 2:
            return None
        self._record_value(series[0])
        return series[0] > series[1]

    def scan_qtr_net_profit_growth_yoy(self) -> Optional[bool]:
        latest, previous = self._same_quarter_last_year("net_profit")
        self._record_value(latest)
        if latest is None or previous is None:
            return None
        return latest > previous

    def scan_qtr_ebitda_growth_yoy(self) -> Optional[bool]:
        latest, previous = self._same_quarter_last_year("operating_profit")
        self._record_value(latest)
        if latest is None or previous is None:
            return None
        return latest > previous

    def scan_highest_qtr_net_profit(self) -> Optional[bool]:
        result = self._highest_vs_history(self.quarterly, "net_profit")
        self._record_value(self._get_value(self.quarterly, 0, "net_profit"))
        return result

    def scan_highest_qtr_ebitda(self) -> Optional[bool]:
        result = self._highest_vs_history(self.quarterly, "operating_profit")
        self._record_value(self._get_value(self.quarterly, 0, "operating_profit"))
        return result

    def scan_highest_ann_net_profit(self) -> Optional[bool]:
        result = self._highest_vs_history(self.annual, "net_profit")
        self._record_value(self._get_value(self.annual, 0, "net_profit"))
        return result

    def scan_highest_ann_ebitda(self) -> Optional[bool]:
        result = self._highest_vs_history(self.annual, "operating_profit")
        self._record_value(self._get_value(self.annual, 0, "operating_profit"))
        return result

    def scan_turnaround_yoy(self) -> Optional[bool]:
        latest, previous = self._same_quarter_last_year("net_profit")
        self._record_value(latest)
        if latest is None or previous is None:
            return None
        return latest > 0 and previous < 0

    def scan_consistent_inc_qtr_eps(self) -> Optional[bool]:
        values = self._get_series(self.quarterly, "eps", MIN_SERIES_LENGTH)
        self._record_value(values[0] if values else None)
        non_none_values = [v for v in values if v is not None]
        if non_none_values and any(v < 0 for v in non_none_values):
            return False
        return self._check_consistency(reversed(values), increasing=True)

    def scan_consistent_dec_qtr_eps(self) -> Optional[bool]:
        values = self._get_series(self.quarterly, "eps", MIN_SERIES_LENGTH)
        self._record_value(values[0] if values else None)
        non_none_values = [v for v in values if v is not None]
        if non_none_values and any(v < 0 for v in non_none_values):
            return False
        return self._check_consistency(reversed(values), increasing=False)

    def scan_consistent_inc_ann_eps(self) -> Optional[bool]:
        values = self._get_series(self.annual, "eps", MIN_SERIES_LENGTH)
        self._record_value(values[0] if values else None)
        non_none_values = [v for v in values if v is not None]
        if non_none_values and any(v < 0 for v in non_none_values):
            return False
        return self._check_consistency(reversed(values), increasing=True)

    def scan_consistent_dec_ann_eps(self) -> Optional[bool]:
        values = self._get_series(self.annual, "eps", MIN_SERIES_LENGTH)
        self._record_value(values[0] if values else None)
        non_none_values = [v for v in values if v is not None]
        if non_none_values and any(v < 0 for v in non_none_values):
            return False
        return self._check_consistency(reversed(values), increasing=False)

    def scan_high_ebitda_margin(self) -> Optional[bool]:
        value = self._annual_opm(0)
        self._record_value(value)
        return None if value is None else value > 20

    def scan_consistently_high_ebitda_margin(self) -> Optional[bool]:
        result = self._annual_margin_series("opm_percent", 20, greater=True)
        self._record_value(self._annual_opm(0))
        return result

    def scan_high_pat_margin(self) -> Optional[bool]:
        value = self._annual_pat_margin(0)
        self._record_value(value)
        return None if value is None else value > 10

    def scan_consistently_high_pat_margin(self) -> Optional[bool]:
        values = [self._annual_pat_margin(i) for i in range(MIN_SERIES_LENGTH)]
        if len([v for v in values if v is not None]) < MIN_SERIES_LENGTH:
            self._record_value(values[0] if values else None)
            return None
        self._record_value(values[0])
        return all(v is not None and v > 10 for v in values)

    def scan_consistently_high_roe(self) -> Optional[bool]:
        series = self._roe_series()
        if len(series) < MIN_SERIES_LENGTH:
            self._record_value(series[0] if series else None)
            return None
        self._record_value(series[0])
        return all(value > 15 for value in series[:MIN_SERIES_LENGTH])

    def scan_consistently_high_roce(self) -> Optional[bool]:
        series = self._roce_series()
        if len(series) < MIN_SERIES_LENGTH:
            self._record_value(series[0] if series else None)
            return None
        self._record_value(series[0])
        return all(value > 15 for value in series[:MIN_SERIES_LENGTH])

    # ------------------------------------------------------------------
    # Turnover scans
    # ------------------------------------------------------------------
    def scan_high_qtr_sales_growth(self) -> Optional[bool]:
        latest, previous = self._same_quarter_last_year("sales")
        self._record_value(latest)
        if latest is None or previous is None:
            return None
        growth = self._safe_growth(latest, previous)
        return None if growth is None else growth > 15

    def scan_high_ann_sales_growth(self) -> Optional[bool]:
        latest = self._get_value(self.annual, 0, "sales")
        previous = self._get_value(self.annual, 1, "sales")
        self._record_value(latest)
        growth = self._safe_growth(latest, previous)
        return None if growth is None else growth > 15

    def scan_consistent_sales_growth(self) -> Optional[bool]:
        values = self._get_series(self.annual, "sales", MIN_SERIES_LENGTH + 1)
        if len([v for v in values if v is not None]) < MIN_SERIES_LENGTH + 1:
            self._record_value(values[0] if values else None)
            return None
        for idx in range(MIN_SERIES_LENGTH):
            growth = self._safe_growth(values[idx], values[idx + 1])
            if growth is None or growth <= 0:
                self._record_value(values[0])
                return False
        self._record_value(values[0])
        return True

    def scan_increasing_qtr_sales(self) -> Optional[bool]:
        values = self._get_series(self.quarterly, "sales", MIN_SERIES_LENGTH)
        self._record_value(values[0] if values else None)
        return self._check_consistency(reversed(values), increasing=True)

    def scan_highest_qtr_sales(self) -> Optional[bool]:
        result = self._highest_vs_history(self.quarterly, "sales")
        self._record_value(self._get_value(self.quarterly, 0, "sales"))
        return result

    def scan_highest_ann_sales(self) -> Optional[bool]:
        result = self._highest_vs_history(self.annual, "sales")
        self._record_value(self._get_value(self.annual, 0, "sales"))
        return result

    # ------------------------------------------------------------------
    # Solvency scans
    # ------------------------------------------------------------------
    def scan_no_leverage(self) -> Optional[bool]:
        value = self._leverage(0)
        self._record_value(value)
        return None if value is None else value == 0

    def scan_low_leverage(self) -> Optional[bool]:
        value = self._leverage(0)
        self._record_value(value)
        if value is None:
            return None
        return value > 0 and value < 0.5

    def scan_mod_leverage(self) -> Optional[bool]:
        value = self._leverage(0)
        self._record_value(value)
        return None if value is None else 0.5 <= value < 1.0

    def scan_high_leverage(self) -> Optional[bool]:
        value = self._leverage(0)
        self._record_value(value)
        return None if value is None else value >= 1.0

    def scan_high_interest_coverage(self) -> Optional[bool]:
        value = self._interest_coverage()
        display_val = value if value != float('inf') else None
        self._record_value(display_val)
        return None if value is None else value > 4

    def scan_mod_interest_coverage(self) -> Optional[bool]:
        value = self._interest_coverage()
        display_val = value if value != float('inf') else None
        self._record_value(display_val)
        if value is None or value == float('inf'):
            return None
        return 2 <= value <= 4

    def scan_low_interest_coverage(self) -> Optional[bool]:
        value = self._interest_coverage()
        display_val = value if value != float('inf') else None
        self._record_value(display_val)
        return None if value is None else value < 2

    def scan_high_current_ratio(self) -> Optional[bool]:
        value = self._current_ratio()
        self._record_value(value)
        return None if value is None else value > 2

    def scan_mod_current_ratio(self) -> Optional[bool]:
        value = self._current_ratio()
        self._record_value(value)
        if value is None:
            return None
        return 1.5 <= value <= 2

    def scan_low_current_ratio(self) -> Optional[bool]:
        value = self._current_ratio()
        self._record_value(value)
        return None if value is None else value < 1.5

    def scan_consistently_increasing_leverage(self) -> Optional[bool]:
        values = [self._leverage(i) for i in range(MIN_SERIES_LENGTH)]
        self._record_value(values[0] if values else None)
        return self._check_consistency(reversed(values), increasing=True)

    def scan_consistently_decreasing_leverage(self) -> Optional[bool]:
        values = [self._leverage(i) for i in range(MIN_SERIES_LENGTH)]
        self._record_value(values[0] if values else None)
        return self._check_consistency(reversed(values), increasing=False)

    # ------------------------------------------------------------------
    # Cash Flow scans
    # ------------------------------------------------------------------
    def scan_increasing_cfo(self) -> Optional[bool]:
        cfo = self._cfo_series()
        if len(cfo) < 2:
            self._record_value(cfo[0][1] if cfo else None)
            return None
        self._record_value(cfo[0][1])
        return cfo[0][1] > cfo[1][1]

    def scan_consistent_positive_cfo(self) -> Optional[bool]:
        cfo = self._cfo_series()
        if len(cfo) < MIN_SERIES_LENGTH:
            self._record_value(cfo[0][1] if cfo else None)
            return None
        self._record_value(cfo[0][1])
        return all(value > 0 for _, value in cfo[:MIN_SERIES_LENGTH])

    def scan_growing_cfo(self) -> Optional[bool]:
        values = [value for _, value in self._cfo_series()[:MIN_SERIES_LENGTH]]
        self._record_value(values[0] if values else None)
        return self._check_consistency(reversed(values), increasing=True)

    def scan_positive_fcf(self) -> Optional[bool]:
        value = self._fcf(0)
        self._record_value(value)
        return None if value is None else value > 0

    def scan_increasing_fcf(self) -> Optional[bool]:
        current = self._fcf(0)
        previous = self._fcf(1)
        self._record_value(current)
        if current is None or previous is None:
            return None
        return current > previous

    def scan_consistent_positive_fcf(self) -> Optional[bool]:
        values = [self._fcf(i) for i in range(MIN_SERIES_LENGTH)]
        self._record_value(values[0] if values else None)
        if any(v is None for v in values):
            return None
        return all(v > 0 for v in values)

    def scan_consistently_declining_fcf(self) -> Optional[bool]:
        values = [self._fcf(i) for i in range(MIN_SERIES_LENGTH)]
        self._record_value(values[0] if values else None)
        return self._check_consistency(reversed(values), increasing=False)

    def scan_highest_ann_cfo(self) -> Optional[bool]:
        result = self._highest_vs_history(self.cash_flow, "cash_from_operating")
        self._record_value(self._get_value(self.cash_flow, 0, "cash_from_operating"))
        return result

    # ------------------------------------------------------------------
    # Valuation scans
    # ------------------------------------------------------------------
    def scan_very_high_pe(self) -> Optional[bool]:
        pe = self.metadata.get("stock_pe")
        self._record_value(pe)
        if pe is None or pe < 0:
            return None
        return pe > 50

    def scan_high_pe(self) -> Optional[bool]:
        pe = self.metadata.get("stock_pe")
        self._record_value(pe)
        if pe is None or pe < 0:
            return None
        return 20 < pe <= 50

    def scan_moderate_pe(self) -> Optional[bool]:
        pe = self.metadata.get("stock_pe")
        self._record_value(pe)
        if pe is None or pe < 0:
            return None
        return 10 <= pe <= 20

    def scan_low_pe(self) -> Optional[bool]:
        pe = self.metadata.get("stock_pe")
        self._record_value(pe)
        if pe is None or pe < 0:
            return None
        return pe < 10

    def scan_pe_above_industry(self) -> Optional[bool]:
        pe = self.metadata.get("stock_pe")
        industry = self.metadata.get("industry_pe")
        self._record_value(pe)
        if pe is None or industry is None or pe < 0 or industry < 0:
            return None
        return pe > industry

    def scan_pe_below_industry(self) -> Optional[bool]:
        pe = self.metadata.get("stock_pe")
        industry = self.metadata.get("industry_pe")
        self._record_value(pe)
        if pe is None or industry is None or pe < 0 or industry < 0:
            return None
        return pe < industry

    def scan_high_peg(self) -> Optional[bool]:
        peg = self._peg()
        self._record_value(peg)
        return None if peg is None else peg > 1.5

    def scan_low_peg(self) -> Optional[bool]:
        peg = self._peg()
        self._record_value(peg)
        # PEG < 1 is good, but negative PEG (negative growth) is usually invalid/bad
        if peg is None: return None
        return 0 < peg < 1.0

    def scan_price_above_book(self) -> Optional[bool]:
        price = self.metadata.get("current_price")
        book_value = self.metadata.get("book_value")
        self._record_value(price)
        if price is None or book_value is None:
            return None
        return price > book_value

    def scan_price_below_book(self) -> Optional[bool]:
        price = self.metadata.get("current_price")
        book_value = self.metadata.get("book_value")
        self._record_value(price)
        if price is None or book_value is None:
            return None
        return price < book_value

    def scan_increasing_ev_ebitda(self) -> Optional[bool]:
        current = self._ev_ebitda(0)
        previous = self._ev_ebitda(1)
        self._record_value(current)
        if current is None or previous is None:
            return None
        return current > previous

    def scan_decreasing_ev_ebitda(self) -> Optional[bool]:
        current = self._ev_ebitda(0)
        previous = self._ev_ebitda(1)
        self._record_value(current)
        if current is None or previous is None:
            return None
        return current < previous

    def scan_high_ev_sales(self) -> Optional[bool]:
        value = self._ev_sales(0)
        self._record_value(value)
        return None if value is None else value > 3

    def scan_moderate_ev_sales(self) -> Optional[bool]:
        value = self._ev_sales(0)
        self._record_value(value)
        if value is None:
            return None
        return 1 <= value <= 3

    def scan_low_ev_sales(self) -> Optional[bool]:
        value = self._ev_sales(0)
        self._record_value(value)
        return None if value is None else value < 1

    # ------------------------------------------------------------------
    # Dividend scans
    # ------------------------------------------------------------------
    def scan_consistent_dividends(self) -> Optional[bool]:
        series = self._dividend_series()
        if len(series) < 5:
            self._record_value(series[0] if series else None)
            if not series:
                return False
            return None
        self._record_value(series[0])
        return all(value > 0 for value in series[:5])

    def scan_positive_dividend_yield(self) -> Optional[bool]:
        value = self.metadata.get("dividend_yield")
        self._record_value(value)
        if value == 0:
            return False
        return None if value is None else value > 0

    def scan_high_dividend_payout(self) -> Optional[bool]:
        series = self._dividend_series()
        if len(series) < MIN_SERIES_LENGTH:
            self._record_value(series[0] if series else None)
            if not series:
                return False
            return None
        self._record_value(series[0])
        return all(value > 30 for value in series[:MIN_SERIES_LENGTH])

    # ------------------------------------------------------------------
    # Efficiency scans
    # ------------------------------------------------------------------
    def scan_increasing_debtor_days(self) -> Optional[bool]:
        return self._ratio_trend("debtor_days", increasing=True)

    def scan_decreasing_debtor_days(self) -> Optional[bool]:
        return self._ratio_trend("debtor_days", increasing=False)

    def scan_increasing_payable_days(self) -> Optional[bool]:
        return self._ratio_trend("days_payable", increasing=True)

    def scan_decreasing_payable_days(self) -> Optional[bool]:
        return self._ratio_trend("days_payable", increasing=False)

    def scan_increasing_inventory_days(self) -> Optional[bool]:
        return self._ratio_trend("inventory_days", increasing=True)

    def scan_decreasing_inventory_days(self) -> Optional[bool]:
        return self._ratio_trend("inventory_days", increasing=False)

    def scan_increasing_working_cap_days(self) -> Optional[bool]:
        return self._ratio_trend("working_capital_days", increasing=True)

    def scan_decreasing_working_cap_days(self) -> Optional[bool]:
        return self._ratio_trend("working_capital_days", increasing=False)

    def scan_high_gfa_increase(self) -> Optional[bool]:
        latest = self._get_value(self.balance_sheet, 0, "fixed_assets")
        previous = self._get_value(self.balance_sheet, 1, "fixed_assets")
        growth = self._safe_growth(latest, previous)
        self._record_value(growth)
        return None if growth is None else growth > 10

    def scan_high_gfa_increase_three_year(self) -> Optional[bool]:
        values = [self._get_value(self.balance_sheet, i, "fixed_assets") for i in range(MIN_SERIES_LENGTH)]
        if any(v is None or v <= 0 for v in values):
            self._record_value(values[0] if values else None)
            return None
        cagr = (values[0] / values[-1]) ** (1 / (MIN_SERIES_LENGTH - 1)) - 1
        cagr_percent = cagr * 100
        self._record_value(cagr_percent)
        return cagr_percent > 10

    # ------------------------------------------------------------------
    # Shareholding scans
    # ------------------------------------------------------------------
    def scan_share_fii_increase(self) -> Optional[bool]:
        return self._shareholding_delta("fiis", increasing=True)

    def scan_share_fii_decrease(self) -> Optional[bool]:
        return self._shareholding_delta("fiis", increasing=False)

    def scan_share_dii_increase(self) -> Optional[bool]:
        return self._shareholding_delta("diis", increasing=True)

    def scan_share_dii_decrease(self) -> Optional[bool]:
        return self._shareholding_delta("diis", increasing=False)

    def scan_share_promoter_increase(self) -> Optional[bool]:
        return self._shareholding_delta("promoters", increasing=True)

    def scan_share_promoter_decrease(self) -> Optional[bool]:
        return self._shareholding_delta("promoters", increasing=False)

    def scan_share_public_increase(self) -> Optional[bool]:
        return self._shareholding_delta("public", increasing=True)

    def scan_share_public_decrease(self) -> Optional[bool]:
        return self._shareholding_delta("public", increasing=False)

    def scan_share_fii_consistent_increase(self) -> Optional[bool]:
        return self._shareholding_consistency("fiis")

    def scan_share_dii_consistent_increase(self) -> Optional[bool]:
        return self._shareholding_consistency("diis")

    def scan_share_promoter_consistent_increase(self) -> Optional[bool]:
        return self._shareholding_consistency("promoters")

    def scan_share_public_consistent_increase(self) -> Optional[bool]:
        return self._shareholding_consistency("public")



    def scan_share_promoter_very_high(self) -> Optional[bool]:
        latest = self._get_value(self.shareholding_q, 0, "promoters")
        if latest is None and self._get_value(self.shareholding_q, 0, "public") is not None:
            latest = 0.0
        self._record_value(latest)
        if latest is None:
            return None
        return latest > 75

    def scan_share_promoter_high(self) -> Optional[bool]:
        latest = self._get_value(self.shareholding_q, 0, "promoters")
        if latest is None and self._get_value(self.shareholding_q, 0, "public") is not None:
            latest = 0.0
        self._record_value(latest)
        if latest is None:
            return None
        return 50 <= latest <= 75

    def scan_share_promoter_low(self) -> Optional[bool]:
        latest = self._get_value(self.shareholding_q, 0, "promoters")
        if latest is None and self._get_value(self.shareholding_q, 0, "public") is not None:
            latest = 0.0
        self._record_value(latest)
        if latest is None:
            return None
        return latest < 50

    def scan_share_shareholders_increase(self) -> Optional[bool]:
        return self._shareholder_count_delta(True)

    def scan_share_shareholders_decrease(self) -> Optional[bool]:
        return self._shareholder_count_delta(False)

    def scan_share_shareholders_consistent_increase(self) -> Optional[bool]:
        values = self._get_series(self.shareholding_q, "no_of_shareholders", MIN_SERIES_LENGTH)
        self._record_value(values[0] if values else None)
        cleaned = [v for v in values if v is not None]
        if len(cleaned) < MIN_SERIES_LENGTH:
            return False
        return self._check_consistency(reversed(values), increasing=True)

    def scan_share_public_high(self) -> Optional[bool]:
        return self._shareholding_level("public", 20)

    def scan_share_public_low(self) -> Optional[bool]:
        latest = self._get_value(self.shareholding_q, 0, "public")
        self._record_value(latest)
        if latest is None:
            return None
        return latest < 10

    # ------------------------------------------------------------------
    # Pledge scans
    # ------------------------------------------------------------------
    def scan_pledge_increase(self) -> Optional[bool]:
        latest, previous = self._pledge_values()
        self._record_value(latest)
        if latest is None and previous is None:
            return None
        if latest is None or previous is None:
            return None
        return latest > previous

    def scan_pledge_decrease(self) -> Optional[bool]:
        latest, previous = self._pledge_values()
        self._record_value(latest)
        if latest is None and previous is None:
            return None
        if latest is None or previous is None:
            return None
        return latest < previous

    def scan_pledge_zero(self) -> Optional[bool]:
        latest, _ = self._pledge_values()
        self._record_value(latest)
        if latest is None:
            return None
        return latest == 0

    def scan_pledge_low(self) -> Optional[bool]:
        latest, _ = self._pledge_values()
        self._record_value(latest)
        if latest is None:
            return None
        return latest > 0 and latest < 20

    def scan_pledge_moderate(self) -> Optional[bool]:
        latest, _ = self._pledge_values()
        self._record_value(latest)
        if latest is None:
            return None
        return 20 <= latest <= 40

    def scan_pledge_high(self) -> Optional[bool]:
        latest, _ = self._pledge_values()
        self._record_value(latest)
        if latest is None:
            return None
        return latest > 40

    # ------------------------------------------------------------------
    # Public API (Updated run_scans)
    # ------------------------------------------------------------------
    def run_scans(self) -> Dict[str, List[Dict[str, Any]]]:
        summary = {"passed": [], "failed": [], "pending": [], "skipped": []}
        
        # Determine which scans are unusual for this industry (for flagging, not skipping)
        unusual_scans = set()

        # Mark inventory-related scans as unusual for non-inventory sectors
        if self.is_non_inventory:
            unusual_scans.update([
                "scan_increasing_inventory_days", 
                "scan_decreasing_inventory_days"
            ])
            
        # Mark financial-specific scans as unusual for financial sectors
        if self.is_financial:
            unusual_scans.update(FINANCIAL_SKIP_SCANS)

        for definition in self.SCANS:
            payload: Dict[str, Any] = {
                "name": definition.name,
                "label": definition.label,
                "category": definition.category,
            }

            # 1. Smart Filter: Skip valuation scans for loss-making companies with undefined PE
            if definition.category == "Valuation" and self.metadata.get("stock_pe") is None and self._is_loss_making():
                payload["reason"] = "loss-making-undefined-pe"
                summary["skipped"].append(payload)
                continue

            # 2. Check if data is actually available
            if not self._has_required_data(definition.name):
                payload["reason"] = "insufficient-data"
                summary["skipped"].append(payload)
                continue

            # 3. Skip scans that are industry-irrelevant (instead of just flagging)
            if definition.name in unusual_scans:
                payload["reason"] = "industry-irrelevant"
                summary["skipped"].append(payload)
                continue

            method = getattr(self, definition.name)
            self._current_value = None
            try:
                outcome = method()
            except Exception:
                outcome = None
            
            if self._current_value is not None:
                payload["value"] = self._current_value

            if outcome is True:
                summary["passed"].append(payload)
            elif outcome is False:
                summary["failed"].append(payload)
            else:
                summary["pending"].append(payload)
        return summary