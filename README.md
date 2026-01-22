# AlphaQuant

AlphaQuant is a modular equity analytics suite for Indian markets (Nifty 500) that combines fundamentals, technicals, price scans, volume/delivery, F&O, strike options, candlestick patterns, and sector analytics into a unified Streamlit dashboard and CLI pipelines.

## Features
- Fundamentals engine with 8-category scoring and signals
- Technicals engine with 214 scans across indicators and pivots
- Price scan engine with 117 scans across breakouts, ranges, RS, VWAP, and behavior
- Volume & delivery scans across daily/weekly/monthly horizons
- Futures & options scans for OI, long/short build-up, and PCR (with safe fallbacks)
- Strike option chain scans for key support/resistance and active strikes
- Candlestick pattern scanner (24 patterns)
- Sector utilities: backtester, peers scraper, and seasonality scraper

## Project Structure
- app.py — Streamlit dashboard entry point
- scans/ — All analysis modules (fundamentals, technicals, price, etc.)
- source/ — Static datasets and scraper outputs used by modules
- RESULTS/ — Local output folder for scan results (gitignored)

## Quick Start
1. Create a virtual environment
2. Install dependencies: pip install -r requirements.txt
3. Run the dashboard: streamlit run app.py

## CLI Examples
- Fundamentals: python scans/fundamentals/main.py --ticker RELIANCE
- Technicals: python scans/technicals/main.py --ticker RELIANCE
- Price Scans: python scans/pricescan/main.py --ticker RELIANCE
- Volume/Delivery: python scans/volumedelivery/main.py --ticker RELIANCE
- F&O: python scans/futureoptions/main.py --ticker RELIANCE
- Strike Options: python scans/strikeoptions/main.py --ticker RELIANCE
- Candlestick: python scans/candlestick/main.py --ticker RELIANCE
- Sector Backtester (Streamlit): streamlit run scans/sector/backtester.py
- Peers Scraper: python scans/sector/peers_screener.py RELIANCE
- Seasonality: python scans/sector/seasonality.py --symbols RELIANCE

## Data Sources
- Screener.in for fundamentals and industry PE
- yfinance for OHLCV data
- Moneycontrol for sector/industry analysis and seasonality
- Tickertape for Market Mood Index

## Notes
- Results are written to RESULTS/ (ignored by git).
- Some F&O and option-chain fields may be unavailable from free sources; the pipeline handles this gracefully.
