# backend/scans/eod_fetcher.py

"""
AlphaQuant Institutional EOD Market Scanner
Consolidated engine utilizing the official NSE UDiFF Archives.
- Downloads UDiFF CM and FO Bhavcopies.
- Downloads MTO.DAT for official EOD Delivery Data.
- Employs a robust Fuzzy Column Mapper to prevent KeyErrors on ISO tags.
- Uses a Local File Buffer for yfinance to strictly prevent rate limiting.
- Extracts Delivery %, Options Max Pain, PCR, and Futures Build-up.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import yfinance as yf

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("EODMarketScanner")

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output" / "data"
SOURCE_DIR = BASE_DIR / "source"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
NIFTY_500_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
INDEX_CACHE_FILE = OUTPUT_DIR / "index_price_cache.json"

# ==============================================================================
# UTILITY HELPERS
# ==============================================================================
def safe_round(val: Any, decimals: int = 2) -> Optional[float]:
    if val is None or pd.isna(val) or np.isinf(val): return None
    try: return round(float(val), decimals)
    except (ValueError, TypeError): return None

def parse_nse_numeric(val: Any) -> float:
    if pd.isna(val): return 0.0
    if isinstance(val, str):
        val = val.strip().replace(',', '')
        if val in ('', '-'): return 0.0
    try: return float(val)
    except ValueError: return 0.0

def get_nifty_tickers() -> List[str]:
    fallback = SOURCE_DIR / "ind_nifty500list.csv"
    if fallback.exists():
        with open(fallback, "r", encoding="utf-8") as f:
            return [row["Symbol"].strip().upper() for row in csv.DictReader(f) if row.get("Symbol")]
    return []

# ==============================================================================
# DATA FETCHER ENGINE (UDiFF + MTO Delivery + YF Buffer)
# ==============================================================================
class EODDataFetcher:
    
    @classmethod
    def fetch_market_data(cls) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], Dict[str, dict], Optional[datetime]]:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)',
            'Accept': '*/*'
        }
        
        session = requests.Session()
        session.headers.update(headers)
        
        delivery_dict = {}

        for i in range(0, 15):
            dt = datetime.now() - timedelta(days=i)
            if dt.weekday() >= 5: continue # Skip weekends
                
            date_str_udiff = dt.strftime("%Y%m%d")
            date_str_mto = dt.strftime("%d%m%Y")
            
            cm_url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date_str_udiff}_F_0000.csv.zip"
            fo_url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{date_str_udiff}_F_0000.csv.zip"
            mto_url = f"https://nsearchives.nseindia.com/archives/equities/mto/MTO_{date_str_mto}.DAT"
            
            try:
                # 1. Fetch UDiFF Cash Market
                cm_res = session.get(cm_url, timeout=15)
                if cm_res.status_code == 200:
                    
                    # 2. Fetch UDiFF F&O 
                    fo_res = session.get(fo_url, timeout=15)
                    if fo_res.status_code == 200:
                        
                        logger.info(f"Successfully downloaded UDiFF FO and CM Bhavcopies for {dt.strftime('%Y-%m-%d')}")
                        
                        # 3. Fetch MTO Delivery Data
                        mto_res = session.get(mto_url, timeout=10)
                        if mto_res.status_code == 200:
                            lines = mto_res.text.splitlines()
                            for line in lines[4:]: # Skip NSE MTO headers
                                parts = line.split(',')
                                if len(parts) >= 6:
                                    ticker = parts[2].strip()
                                    del_qty = parse_nse_numeric(parts[5])
                                    del_pct = parse_nse_numeric(parts[6])
                                    delivery_dict[ticker] = {'qty': del_qty, 'pct': del_pct}
                            logger.info("Successfully fetched MTO Delivery Data.")

                        cm_df = pd.DataFrame()
                        with zipfile.ZipFile(io.BytesIO(cm_res.content)) as z:
                            for filename in z.namelist():
                                if filename.endswith(".csv"):
                                    with z.open(filename) as f: cm_df = pd.read_csv(f, low_memory=False)
                                    break
                                        
                        fo_df = pd.DataFrame()
                        with zipfile.ZipFile(io.BytesIO(fo_res.content)) as z:
                            for filename in z.namelist():
                                if filename.endswith(".csv"):
                                    with z.open(filename) as f: fo_df = pd.read_csv(f, low_memory=False)
                                    break
                        
                        # --------------------------------------------------
                        # ROBUST FUZZY COLUMN MAPPING LAYER
                        # --------------------------------------------------
                        cm_mappings = {
                            'SYMBOL': ['TckrSymb', 'SYMBOL', 'Symbol'],
                            'SERIES': ['SctySrs', 'SERIES', 'Series'],
                            'CLOSE_PRICE': ['ClsPric', 'CLOSE_PRICE', 'Close'],
                            'PREV_CLOSE': ['PrvsClsgPric', 'PREV_CLOSE', 'PrevClose']
                        }
                        
                        fo_mappings = {
                            'SYMBOL': ['TckrSymb', 'SYMBOL', 'Symbol'],
                            'EXPIRY_DT': ['XpryDt', 'EXPIRY_DT', 'ExpiryDate'],
                            'STRIKE_PR': ['StrkPric', 'STRIKE_PR', 'StrikePrice'],
                            'OPTION_TYP': ['OptnTp', 'OPTION_TYP', 'OptionType'],
                            'OPEN_INT': ['OpnIntrst', 'OPEN_INT', 'OpenInterest'],
                            'CHG_IN_OI': ['ChngInOpnIntrst', 'ChgInOpnIntrst', 'ChgOpnIntrst', 'CHG_IN_OI', 'ChangeInOI'],
                            'CONTRACTS': ['TotTradgVol', 'TradgVol', 'CONTRACTS', 'Volume']
                        }

                        # Apply CM mappings
                        for target, possibilities in cm_mappings.items():
                            for col in cm_df.columns:
                                if col.strip().lower() in [p.lower() for p in possibilities]:
                                    cm_df.rename(columns={col: target}, inplace=True)
                                    break
                            if target not in cm_df.columns:
                                cm_df[target] = 0.0 if target not in ['SYMBOL', 'SERIES'] else ''

                        # Apply FO mappings
                        for target, possibilities in fo_mappings.items():
                            for col in fo_df.columns:
                                if col.strip().lower() in [p.lower() for p in possibilities]:
                                    fo_df.rename(columns={col: target}, inplace=True)
                                    break
                            if target not in fo_df.columns:
                                fo_df[target] = 0.0 if target not in ['SYMBOL', 'OPTION_TYP', 'EXPIRY_DT'] else ''

                        cm_df.columns = cm_df.columns.str.upper()
                        fo_df.columns = fo_df.columns.str.upper()
                        
                        return fo_df, cm_df, delivery_dict, dt
                
            except Exception as e:
                logger.debug(f"Network error on {date_str_udiff}: {e}")
            
            time.sleep(0.5)
            
        logger.error("Could not find recent NSE UDiFF files in the last 15 days.")
        return None, None, {}, None

    @classmethod
    def fetch_index_price_changes(cls, tickers: List[str]) -> Dict[str, float]:
        """Fetches index returns using a Local JSON Buffer to strictly prevent IP Rate Limiting."""
        yf_tickers = []
        if "NIFTY" in tickers: yf_tickers.append("^NSEI")
        if "BANKNIFTY" in tickers: yf_tickers.append("^NSEBANK")
        
        if not yf_tickers: return {}

        # 1. Check Local Buffer Cache
        if INDEX_CACHE_FILE.exists():
            try:
                with open(INDEX_CACHE_FILE, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                
                last_updated = datetime.fromisoformat(cache_data.get("timestamp", "2000-01-01T00:00:00"))
                # If cache is less than 6 hours old, use it to bypass yfinance completely
                if datetime.now() - last_updated < timedelta(hours=6):
                    logger.info("Loaded Index prices from local buffer (Preventing Rate Limit).")
                    return cache_data.get("prices", {})
            except Exception as e:
                logger.debug(f"Cache read error: {e}")

        # 2. Fetch if Buffer is stale or missing
        price_changes = {}
        try:
            # Short sleep to respect rate limits if we are fetching
            time.sleep(1) 
            df = yf.download(yf_tickers, period="5d", interval="1d", progress=False, threads=False)
            if not df.empty:
                close_df = df['Close'] if 'Close' in df.columns else df['Adj Close']
                returns_df = close_df.pct_change() * 100
                latest_returns = returns_df.iloc[-1].to_dict()
                
                for k, v in latest_returns.items():
                    if pd.isna(v): continue
                    symbol = "NIFTY" if k == "^NSEI" else "BANKNIFTY" if k == "^NSEBANK" else k
                    price_changes[symbol] = safe_round(v)
            
            # 3. Write to Local Buffer Cache
            with open(INDEX_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "timestamp": datetime.now().isoformat(),
                    "prices": price_changes
                }, f, indent=4)
                
        except Exception as e:
            logger.error(f"Error fetching index price changes: {e}")
            
        return price_changes

# ==============================================================================
# EOD MARKET SCANNER
# ==============================================================================
class EODMarketScanner:
    def __init__(self, fo_df: pd.DataFrame, cm_df: pd.DataFrame, delivery_dict: Dict[str, dict], trade_date: datetime, index_returns: Dict[str, float]):
        self.fo_df = fo_df
        self.cm_df = cm_df
        self.delivery_dict = delivery_dict
        self.trade_date = trade_date.strftime('%Y-%m-%d')
        self.index_returns = index_returns

    def scan_stock(self, ticker: str) -> Optional[Dict[str, Any]]:
        cm_payload = {}
        price_change_pct = 0.0
        
        # 1. Delivery & Cash Market
        deliv_qty = self.delivery_dict.get(ticker, {}).get("qty", 0)
        deliv_per = self.delivery_dict.get(ticker, {}).get("pct", 0.0)
        
        if 'SYMBOL' in self.cm_df.columns:
            df_cm_ticker = self.cm_df[(self.cm_df['SYMBOL'].astype(str).str.strip() == ticker)]
            if not df_cm_ticker.empty:
                if 'SERIES' in df_cm_ticker.columns and not df_cm_ticker[df_cm_ticker['SERIES'].astype(str).str.strip() == 'EQ'].empty:
                    row = df_cm_ticker[df_cm_ticker['SERIES'].astype(str).str.strip() == 'EQ'].iloc[0]
                else:
                    row = df_cm_ticker.iloc[0]
                    
                close_pr = parse_nse_numeric(row.get('CLOSE_PRICE'))
                prev_pr = parse_nse_numeric(row.get('PREV_CLOSE'))
                if prev_pr > 0: price_change_pct = ((close_pr - prev_pr) / prev_pr) * 100
                    
                cm_payload = {
                    "close_price": safe_round(close_pr),
                    "price_change_pct": safe_round(price_change_pct),
                    "delivery_quantity": int(deliv_qty),
                    "delivery_percentage": safe_round(deliv_per)
                }

        if not cm_payload and ticker in self.index_returns:
            price_change_pct = self.index_returns[ticker]

        # 2. Futures & Options
        df_fo_ticker = pd.DataFrame()
        if 'SYMBOL' in self.fo_df.columns:
            df_fo_ticker = self.fo_df[self.fo_df['SYMBOL'].astype(str).str.strip() == ticker].copy()
            
        if df_fo_ticker.empty and not cm_payload: return None

        fut_payload = {}
        opt_payload = {}

        if not df_fo_ticker.empty and 'STRIKE_PR' in df_fo_ticker.columns:
            df_fo_ticker['STRIKE_PR'] = pd.to_numeric(df_fo_ticker['STRIKE_PR'], errors='coerce').fillna(0.0)
            
            df_fut = df_fo_ticker[df_fo_ticker['STRIKE_PR'] <= 0.0]
            df_opt = df_fo_ticker[df_fo_ticker['STRIKE_PR'] > 0.0].copy()
            
            if not df_fut.empty:
                total_oi = float(df_fut['OPEN_INT'].sum())
                chg_in_oi = float(df_fut['CHG_IN_OI'].sum())
                chg_in_oi_pct = (chg_in_oi / (total_oi - chg_in_oi)) * 100 if total_oi != chg_in_oi else 0.0

                build_up = "Neutral"
                if price_change_pct > 0 and chg_in_oi > 0: build_up = "Long Build-Up"
                elif price_change_pct < 0 and chg_in_oi > 0: build_up = "Short Build-Up"
                elif price_change_pct > 0 and chg_in_oi < 0: build_up = "Short Covering"
                elif price_change_pct < 0 and chg_in_oi < 0: build_up = "Long Unwinding"

                fut_payload = {
                    "total_oi": total_oi,
                    "chg_in_oi": chg_in_oi,
                    "chg_in_oi_pct": safe_round(chg_in_oi_pct),
                    "build_up_status": build_up
                }

            if not df_opt.empty:
                df_opt['EXPIRY_DT'] = pd.to_datetime(df_opt['EXPIRY_DT'], errors='coerce')
                df_opt = df_opt.dropna(subset=['EXPIRY_DT'])
                if not df_opt.empty:
                    near_expiry = df_opt['EXPIRY_DT'].min()
                    df_near = df_opt[df_opt['EXPIRY_DT'] == near_expiry].copy()

                    df_near['OPTION_TYP'] = df_near['OPTION_TYP'].astype(str).str.upper()
                    df_near['IS_CE'] = df_near['OPTION_TYP'].str.contains('C')
                    df_near['IS_PE'] = df_near['OPTION_TYP'].str.contains('P')

                    pe_oi = df_near[df_near['IS_PE']]['OPEN_INT'].sum()
                    ce_oi = df_near[df_near['IS_CE']]['OPEN_INT'].sum()
                    pcr_oi = pe_oi / ce_oi if ce_oi > 0 else 0.0

                    pe_vol = df_near[df_near['IS_PE']]['CONTRACTS'].sum()
                    ce_vol = df_near[df_near['IS_CE']]['CONTRACTS'].sum()
                    pcr_vol = pe_vol / ce_vol if ce_vol > 0 else 0.0

                    res_strike_ce, supp_strike_pe = {}, {}
                    df_ce = df_near[df_near['IS_CE']]
                    if not df_ce.empty:
                        row = df_ce.loc[df_ce['OPEN_INT'].idxmax()]
                        res_strike_ce = {"strike": float(row['STRIKE_PR']), "oi": float(row['OPEN_INT']), "chg_in_oi": float(row['CHG_IN_OI'])}
                    
                    df_pe = df_near[df_near['IS_PE']]
                    if not df_pe.empty:
                        row = df_pe.loc[df_pe['OPEN_INT'].idxmax()]
                        supp_strike_pe = {"strike": float(row['STRIKE_PR']), "oi": float(row['OPEN_INT']), "chg_in_oi": float(row['CHG_IN_OI'])}

                    high_add_ce, high_add_pe = {}, {}
                    if not df_ce.empty and df_ce['CHG_IN_OI'].max() > 0:
                        row = df_ce.loc[df_ce['CHG_IN_OI'].idxmax()]
                        high_add_ce = {"strike": float(row['STRIKE_PR']), "chg_in_oi": float(row['CHG_IN_OI'])}
                    
                    if not df_pe.empty and df_pe['CHG_IN_OI'].max() > 0:
                        row = df_pe.loc[df_pe['CHG_IN_OI'].idxmax()]
                        high_add_pe = {"strike": float(row['STRIKE_PR']), "chg_in_oi": float(row['CHG_IN_OI'])}

                    strikes = df_near['STRIKE_PR'].unique()
                    max_pain_val, max_pain_strike = float('inf'), None

                    for strike in strikes:
                        pain_ce = np.where(df_near['IS_CE'], df_near['OPEN_INT'] * np.maximum(0, strike - df_near['STRIKE_PR']), 0)
                        pain_pe = np.where(df_near['IS_PE'], df_near['OPEN_INT'] * np.maximum(0, df_near['STRIKE_PR'] - strike), 0)
                        total_pain = np.sum(pain_ce) + np.sum(pain_pe)
                        if total_pain < max_pain_val:
                            max_pain_val = total_pain
                            max_pain_strike = float(strike)

                    opt_payload = {
                        "near_expiry_date": near_expiry.strftime('%Y-%m-%d'),
                        "pcr_oi": safe_round(pcr_oi),
                        "pcr_vol": safe_round(pcr_vol),
                        "max_pain_strike": max_pain_strike,
                        "resistance_strike_ce": res_strike_ce,
                        "support_strike_pe": supp_strike_pe,
                        "highest_call_addition": high_add_ce,
                        "highest_put_addition": high_add_pe
                    }

        return {
            "ticker": ticker,
            "timestamp": datetime.now().isoformat(),
            "trade_date": self.trade_date,
            "cash_market_data": cm_payload,
            "futures_data": fut_payload,
            "options_data": opt_payload
        }

# ==============================================================================
# MAIN BATCH ORCHESTRATOR
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="AlphaQuant EOD Market Scanner")
    parser.add_argument("--ticker", type=str, help="Ticker symbol to scan")
    parser.add_argument("--limit", type=int, help="Limit total tickers processed")
    args = parser.parse_args()

    tickers = [args.ticker.upper()] if args.ticker else get_nifty_tickers()
    if "NIFTY" not in tickers: tickers.append("NIFTY")
    if "BANKNIFTY" not in tickers: tickers.append("BANKNIFTY")
    if args.limit: tickers = tickers[:args.limit]

    logger.info("Fetching Master EOD Bhavcopy (F&O) and Cash Market (Delivery) files via UDiFF...")
    
    fo_df, cm_df, delivery_dict, trade_date = EODDataFetcher.fetch_market_data()
    
    if fo_df is None or cm_df is None:
        logger.error("Failed to acquire core NSE files. Halting execution.")
        return

    index_returns = EODDataFetcher.fetch_index_price_changes(tickers)
    scanner = EODMarketScanner(fo_df, cm_df, delivery_dict, trade_date, index_returns)

    logger.info(f"Starting rapid processing for {len(tickers)} assets...")
    processed_count = 0
    for t in tickers:
        payload = scanner.scan_stock(t)
        if payload:
            out_file = OUTPUT_DIR / f"{t}_eod_data.json"
            try:
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=4)
                processed_count += 1
            except Exception as e: logger.error(f"Failed to write output file for {t}: {e}")
                
    logger.info(f"EOD Market scan complete. Verified data saved for {processed_count} assets.")

if __name__ == "__main__":
    main()