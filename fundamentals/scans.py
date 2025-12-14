"""
Comprehensive logic layer that evaluates fundamental scans with tiered classification.
Classifies metrics into High, Moderate, Low, or Pending instead of simple Pass/Fail.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

NUMBER_OF_QUARTERS_IN_YEAR = 4
MIN_SERIES_LENGTH = 3

@dataclass(frozen=True)
class ScanDefinition:
    name: str
    label: str
    category: str

def _build_scan_definitions() -> Tuple[ScanDefinition, ...]:
    # We consolidate multiple boolean checks into single categorical checks where possible
    
    profitability = [
        ("check_roe_status", "ROE Status"),
        ("check_roce_status", "ROCE Status"),
        ("check_net_profit_growth_qtr", "Quarterly Profit Growth"),
        ("check_ebitda_margin_trend", "EBITDA Margin Trend"),
        ("check_pat_margin_status", "PAT Margin Status"),
        ("check_earnings_consistency", "Earnings Consistency"),
    ]

    turnover = [
        ("check_sales_growth_qtr", "Quarterly Sales Growth"),
        ("check_sales_growth_ann", "Annual Sales Growth"),
        ("check_sales_consistency", "Sales Consistency"),
    ]

    solvency = [
        ("check_leverage_status", "Debt-to-Equity Status"),
        ("check_interest_coverage", "Interest Coverage Ratio"),
        ("check_current_ratio", "Current Ratio Status"),
        ("check_leverage_trend", "Leverage Trend"),
    ]

    cash_flow = [
        ("check_cfo_status", "Operating Cash Flow Status"),
        ("check_fcf_status", "Free Cash Flow Status"),
        ("check_cfo_consistency", "CFO Consistency"),
    ]

    valuation = [
        ("check_pe_valuation", "P/E Valuation"),
        ("check_relative_pe", "P/E vs Industry"),
        ("check_peg_valuation", "PEG Valuation"),
        ("check_price_to_book", "Price to Book Value"),
        ("check_ev_ebitda_trend", "EV/EBITDA Trend"),
    ]

    dividends = [
        ("check_dividend_yield", "Dividend Yield Status"),
        ("check_dividend_consistency", "Dividend Consistency"),
    ]

    efficiency = [
        ("check_working_capital_trend", "Working Capital Cycle"),
        ("check_fixed_asset_turnover", "Fixed Asset Efficiency"), # Proxy via Capex growth
    ]

    shareholding = [
        ("check_promoter_holding", "Promoter Holding Status"),
        ("check_institutional_trend", "Institutional (FII+DII) Trend"),
        ("check_pledge_status", "Promoter Pledge Status"),
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
    ]

    definitions: List[ScanDefinition] = []
    for category, items in categories:
        for name, label in items:
            definitions.append(ScanDefinition(name, label, category))
    return tuple(definitions)


class FundamentalScans:
    """
    Evaluates fundamental metrics and returns a classification:
    - High / Good
    - Moderate / Average
    - Low / Poor
    - Pending (Insufficient Data)
    """

    METADATA_FIELDS = (
        "market_cap", "current_price", "stock_pe", "book_value",
        "dividend_yield", "roce", "roe", "face_value",
        "high_price", "low_price", "pledge_data_missing",
        "industry_pe", "industry",
    )

    SCANS = _build_scan_definitions()

    def __init__(self, data: Dict[str, Any]):
        if not isinstance(data, dict):
            data = {}

        self.data = data
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
        self.industry = self.metadata.get("industry", "Unknown")
        
        # Archetype logic can be added here based on results if needed
        self.archetype = "Generic"

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def _build_metadata(self) -> Dict[str, Any]:
        base = dict(self.data.get("metadata") or {})
        for field in self.METADATA_FIELDS:
            if field not in base and field in self.data:
                base[field] = self.data[field]
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

    @staticmethod
    def _safe_divide(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
        if numerator is None or denominator is None: return None
        if denominator == 0: return 0.0
        try: return numerator / denominator
        except ZeroDivisionError: return None

    @staticmethod
    def _safe_growth(current: Optional[float], previous: Optional[float]) -> Optional[float]:
        if current is None or previous is None: return None
        if previous == 0: return 100.0 if current > 0 else (-100.0 if current < 0 else 0.0)
        return ((current - previous) / abs(previous)) * 100

    # --- Computed Metrics ---
    def _compute_roe(self) -> Optional[float]:
        np = self._get_value(self.annual, 0, "net_profit")
        eq = self._get_value(self.balance_sheet, 0, "equity_capital")
        res = self._get_value(self.balance_sheet, 0, "reserves")
        den = None if eq is None or res is None else eq + res
        roe = self._safe_divide(np, den)
        return roe * 100 if roe is not None else None

    def _compute_roce(self) -> Optional[float]:
        ebit = self._get_value(self.quarterly, 0, "operating_profit") # Proxy using OP
        if ebit is None: ebit = self._get_value(self.annual, 0, "operating_profit")
        ta = self._get_value(self.balance_sheet, 0, "total_assets")
        cl = self._get_value(self.balance_sheet, 0, "current_liabilities")
        ce = self._safe_divide(ta - cl, 1) if ta is not None and cl is not None else None
        roce = self._safe_divide(ebit, ce)
        return roce * 100 if roce is not None else None

    def _leverage_ratio(self) -> Optional[float]:
        b = self._get_value(self.balance_sheet, 0, "borrowings")
        e = self._get_value(self.balance_sheet, 0, "equity_capital")
        r = self._get_value(self.balance_sheet, 0, "reserves")
        if b is None: return None
        equity = (e or 0) + (r or 0)
        return self._safe_divide(b, equity)

    # ------------------------------------------------------------------
    # Profitability Logic
    # ------------------------------------------------------------------
    def check_roe_status(self) -> str:
        roe = self.metadata.get("roe")
        self._record_value(roe)
        if roe is None: return "Pending"
        if roe >= 20: return "High"
        if roe >= 12: return "Moderate"
        return "Low"

    def check_roce_status(self) -> str:
        roce = self.metadata.get("roce")
        self._record_value(roce)
        if roce is None: return "Pending"
        if roce >= 20: return "High"
        if roce >= 12: return "Moderate"
        return "Low"

    def check_net_profit_growth_qtr(self) -> str:
        periods = self._get_sorted_periods(self.quarterly)
        if len(periods) <= 4: return "Pending" # Need same qtr last year
        
        curr = self._get_value(self.quarterly, 0, "net_profit")
        prev = self._get_value(self.quarterly, 4, "net_profit") # YoY Quarter
        growth = self._safe_growth(curr, prev)
        self._record_value(growth)
        
        if growth is None: return "Pending"
        if growth >= 20: return "High Growth"
        if growth >= 5: return "Moderate Growth"
        if growth >= 0: return "Flat"
        return "Negative"

    def check_ebitda_margin_trend(self) -> str:
        # Check annual trend
        m1 = self._get_value(self.annual, 0, "opm_percent")
        m2 = self._get_value(self.annual, 1, "opm_percent")
        self._record_value(m1)
        if m1 is None or m2 is None: return "Pending"
        
        if m1 > 20: return "High Margin"
        if m1 > 10: return "Moderate Margin"
        return "Low Margin"

    def check_pat_margin_status(self) -> str:
        sales = self._get_value(self.annual, 0, "sales")
        pat = self._get_value(self.annual, 0, "net_profit")
        if sales is None or pat is None: return "Pending"
        margin = self._safe_divide(pat, sales) * 100
        self._record_value(margin)
        
        if margin >= 15: return "High"
        if margin >= 8: return "Moderate"
        return "Low"

    def check_earnings_consistency(self) -> str:
        # Check if EPS has grown last 3 years
        eps_series = self._get_series(self.annual, "eps", 3)
        if len(eps_series) < 3 or any(e is None for e in eps_series):
            return "Pending"
        
        self._record_value(eps_series[0])
        # Series is newest first. So [0] > [1] > [2]
        if eps_series[0] > eps_series[1] > eps_series[2]:
            return "Consistent Growth"
        if eps_series[0] > eps_series[1]:
            return "Growth"
        return "Inconsistent"

    # ------------------------------------------------------------------
    # Turnover
    # ------------------------------------------------------------------
    def check_sales_growth_qtr(self) -> str:
        curr = self._get_value(self.quarterly, 0, "sales")
        prev = self._get_value(self.quarterly, 4, "sales")
        growth = self._safe_growth(curr, prev)
        self._record_value(growth)
        
        if growth is None: return "Pending"
        if growth >= 15: return "High"
        if growth >= 5: return "Moderate"
        return "Low"

    def check_sales_growth_ann(self) -> str:
        curr = self._get_value(self.annual, 0, "sales")
        prev = self._get_value(self.annual, 1, "sales")
        growth = self._safe_growth(curr, prev)
        self._record_value(growth)
        
        if growth is None: return "Pending"
        if growth >= 15: return "High"
        if growth >= 5: return "Moderate"
        return "Low"

    def check_sales_consistency(self) -> str:
        sales = self._get_series(self.annual, "sales", 3)
        if len(sales) < 3 or any(s is None for s in sales): return "Pending"
        self._record_value(sales[0])
        
        if sales[0] > sales[1] > sales[2]: return "Consistent Growth"
        if sales[0] > sales[1]: return "Growth"
        return "Inconsistent"

    # ------------------------------------------------------------------
    # Solvency
    # ------------------------------------------------------------------
    def check_leverage_status(self) -> str:
        de = self._leverage_ratio()
        self._record_value(de)
        if de is None: return "Pending"
        
        # Lower is better
        if de == 0: return "Debt Free"
        if de < 0.5: return "Low Debt"
        if de <= 1.0: return "Moderate Debt"
        return "High Debt"

    def check_interest_coverage(self) -> str:
        icr = self._safe_divide(self._get_value(self.quarterly, 0, "operating_profit"), self._get_value(self.quarterly, 0, "interest"))
        self._record_value(icr)
        if icr is None: return "Pending"
        
        if icr > 6: return "High Coverage"
        if icr > 3: return "Moderate"
        return "Low Coverage"

    def check_current_ratio(self) -> str:
        ca = self._get_value(self.balance_sheet, 0, "current_assets")
        cl = self._get_value(self.balance_sheet, 0, "current_liabilities")
        cr = self._safe_divide(ca, cl)
        self._record_value(cr)
        if cr is None: return "Pending"
        
        if cr > 2.0: return "Strong Liquidity"
        if cr >= 1.2: return "Adequate"
        return "Tight Liquidity"

    def check_leverage_trend(self) -> str:
        curr = self._leverage_ratio()
        # Hack to calculate prev leverage (index 1)
        b = self._get_value(self.balance_sheet, 1, "borrowings")
        e = self._get_value(self.balance_sheet, 1, "equity_capital")
        r = self._get_value(self.balance_sheet, 1, "reserves")
        prev = self._safe_divide(b, (e or 0) + (r or 0)) if b is not None else None
        
        if curr is None or prev is None: return "Pending"
        self._record_value(curr)
        
        if curr < prev: return "Improving (Reducing)"
        if curr > prev: return "Worsening (Increasing)"
        return "Stable"

    # ------------------------------------------------------------------
    # Cash Flow
    # ------------------------------------------------------------------
    def check_cfo_status(self) -> str:
        cfo = self._get_value(self.cash_flow, 0, "cash_from_operating")
        self._record_value(cfo)
        if cfo is None: return "Pending"
        if cfo > 0: return "Positive"
        return "Negative"

    def check_fcf_status(self) -> str:
        cfo = self._get_value(self.cash_flow, 0, "cash_from_operating")
        capex = self._get_value(self.cash_flow, 0, "cash_from_investing") # Proxy
        if cfo is None or capex is None: return "Pending"
        fcf = cfo - abs(capex)
        self._record_value(fcf)
        if fcf > 0: return "Positive Free Cash"
        return "Negative Free Cash"

    def check_cfo_consistency(self) -> str:
        cfos = self._get_series(self.cash_flow, "cash_from_operating", 3)
        if len(cfos) < 3 or any(c is None for c in cfos): return "Pending"
        if all(c > 0 for c in cfos): return "Consistent Positive"
        return "Volatile"

    # ------------------------------------------------------------------
    # Valuation
    # ------------------------------------------------------------------
    def check_pe_valuation(self) -> str:
        pe = self.metadata.get("stock_pe")
        self._record_value(pe)
        if pe is None: return "Pending"
        
        # General market rules
        if pe < 15: return "Undervalued (Low PE)"
        if pe < 30: return "Fair Value"
        if pe < 50: return "Premium Valuation"
        return "Expensive"

    def check_relative_pe(self) -> str:
        pe = self.metadata.get("stock_pe")
        ind_pe = self.metadata.get("industry_pe")
        if pe is None or ind_pe is None: return "Pending"
        self._record_value(pe)
        
        if pe < ind_pe * 0.8: return "Cheaper than Industry"
        if pe > ind_pe * 1.2: return "Premium to Industry"
        return "In Line with Industry"

    def check_peg_valuation(self) -> str:
        pe = self.metadata.get("stock_pe")
        # Profit growth
        np0 = self._get_value(self.annual, 0, "net_profit")
        np1 = self._get_value(self.annual, 1, "net_profit")
        g = self._safe_growth(np0, np1)
        
        if pe is None or g is None or g <= 0: return "Pending"
        peg = pe / g
        self._record_value(peg)
        
        if peg < 1: return "Undervalued (PEG < 1)"
        if peg < 2: return "Fair Value"
        return "Expensive (PEG > 2)"

    def check_price_to_book(self) -> str:
        pb = self._safe_divide(self.metadata.get("current_price"), self.metadata.get("book_value"))
        self._record_value(pb)
        if pb is None: return "Pending"
        
        if pb < 1: return "Below Book Value"
        if pb < 3: return "Reasonable"
        return "Premium"

    def check_ev_ebitda_trend(self) -> str:
        # Too complex to calc trend reliably without EV history. Returning placeholder.
        return "Pending"

    # ------------------------------------------------------------------
    # Dividends
    # ------------------------------------------------------------------
    def check_dividend_yield(self) -> str:
        dy = self.metadata.get("dividend_yield")
        self._record_value(dy)
        if dy is None or dy == 0: return "No Dividend"
        if dy > 3: return "High Yield"
        if dy > 1: return "Moderate Yield"
        return "Low Yield"

    def check_dividend_consistency(self) -> str:
        divs = self._get_series(self.annual, "dividend_payout_percent", 3)
        if not divs: return "No History"
        # If paying for 3 years
        count = sum(1 for d in divs if d is not None and d > 0)
        if count >= 3: return "Consistent Payer"
        if count > 0: return "Occasional Payer"
        return "Non-Payer"

    # ------------------------------------------------------------------
    # Efficiency
    # ------------------------------------------------------------------
    def check_working_capital_trend(self) -> str:
        wc0 = self._get_value(self.ratios, 0, "working_capital_days")
        wc1 = self._get_value(self.ratios, 1, "working_capital_days")
        self._record_value(wc0)
        if wc0 is None or wc1 is None: return "Pending"
        
        if wc0 < wc1: return "Improving (Shortening)"
        if wc0 > wc1: return "Worsening (Lengthening)"
        return "Stable"

    def check_fixed_asset_turnover(self) -> str:
        # Proxy: Is Fixed Asset increasing?
        fa0 = self._get_value(self.balance_sheet, 0, "fixed_assets")
        fa1 = self._get_value(self.balance_sheet, 1, "fixed_assets")
        self._record_value(fa0)
        if fa0 is None or fa1 is None: return "Pending"
        
        if fa0 > fa1: return "Expanding Capacity"
        return "Stable Capacity"

    # ------------------------------------------------------------------
    # Shareholding
    # ------------------------------------------------------------------
    def check_promoter_holding(self) -> str:
        ph = self._get_value(self.shareholding_q, 0, "promoters")
        self._record_value(ph)
        if ph is None: return "Pending"
        
        if ph > 60: return "High Skin in Game"
        if ph > 40: return "Moderate"
        return "Low Promoter Holding"

    def check_institutional_trend(self) -> str:
        fii0 = self._get_value(self.shareholding_q, 0, "fiis") or 0
        dii0 = self._get_value(self.shareholding_q, 0, "diis") or 0
        total0 = fii0 + dii0
        
        fii1 = self._get_value(self.shareholding_q, 1, "fiis") or 0
        dii1 = self._get_value(self.shareholding_q, 1, "diis") or 0
        total1 = fii1 + dii1
        
        self._record_value(total0)
        if total0 == 0 and total1 == 0: return "No Institutional Holding"
        
        if total0 > total1: return "Accumulating"
        if total0 < total1: return "Distributing"
        return "Stable"

    def check_pledge_status(self) -> str:
        pledge = self._get_value(self.shareholding_q, 0, "pledged_percent")
        self._record_value(pledge)
        if pledge is None or pledge == 0: return "Clean (No Pledge)"
        if pledge < 10: return "Low Pledge"
        if pledge < 25: return "Moderate Pledge"
        return "High Pledge Risk"

    # ------------------------------------------------------------------
    # Public Execution
    # ------------------------------------------------------------------
    def run_scans(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Executes all defined checks. 
        Returns a dictionary grouping results by their classification (High, Moderate, Low, Pending).
        """
        results: Dict[str, List[Dict[str, Any]]] = {
            "High": [],
            "Moderate": [],
            "Low": [],
            "Pending": [],
            "Info": [] # For non-rankable statuses like "Consistent Payer"
        }
        
        for definition in self.SCANS:
            method = getattr(self, definition.name)
            self._current_value = None
            try:
                result_text = method()
            except Exception:
                result_text = "Pending"
            
            payload = {
                "label": definition.label,
                "category": definition.category,
                "status": result_text,
                "value": self._current_value
            }

            # Map the detailed string result to a simplified bucket for the dashboard summary
            # We map specific keywords to the 4 main buckets
            text_lower = result_text.lower()
            
            bucket = "Info"
            if "high" in text_lower or "strong" in text_lower or "improving" in text_lower or "consistent" in text_lower or "positive" in text_lower or "undervalued" in text_lower or "clean" in text_lower or "free" in text_lower:
                if "risk" not in text_lower and "expensive" not in text_lower and "debt" not in text_lower:
                     bucket = "High"
                elif "debt" in text_lower and "high" in text_lower:
                     bucket = "Low" # High Debt is Bad
                elif "pledge" in text_lower and "high" in text_lower:
                     bucket = "Low" # High Pledge is Bad

            if "moderate" in text_lower or "fair" in text_lower or "adequate" in text_lower or "stable" in text_lower:
                bucket = "Moderate"
                
            if "low" in text_lower or "weak" in text_lower or "worsening" in text_lower or "negative" in text_lower or "inconsistent" in text_lower or "expensive" in text_lower:
                if "low debt" in text_lower or "low pledge" in text_lower or "low pe" in text_lower:
                    bucket = "High" # Low Debt/Pledge/PE is Good
                else:
                    bucket = "Low"

            if "pending" in text_lower:
                bucket = "Pending"

            if bucket not in results:
                results[bucket] = []
            results[bucket].append(payload)

        return results