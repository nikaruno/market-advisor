"""
Annual fundamentals downloader (standalone).

Downloads ONLY the annual financial statements (income, balance sheet, cash
flow) plus a small meta file for each company in the USD-filtered universe.
Annual statements change at most once a year, so this script is meant to be
run infrequently (e.g. after fiscal year-ends) — independently of the
quarterly/valuation and technical pipelines, which refresh on their own
cadence.

Input  : data/fundamentals_raw.csv        (universe from scrape_fundamentals.py)
Output : data/fundamentals/raw/{TICKER}_income.csv
         data/fundamentals/raw/{TICKER}_balance.csv
         data/fundamentals/raw/{TICKER}_cashflow.csv
         data/fundamentals/raw/{TICKER}_meta.json

This feeds the quality pipeline only (compute_detailed_metrics -> absolute_scores).
It deliberately does NOT download quarterly statements; that belongs to the
separate valuation pipeline.
"""
import yfinance as yf
import pandas as pd
import json
from pathlib import Path
import time

RAW_DIR = Path("data/fundamentals/raw")
UNIVERSE_PATH = Path("data/fundamentals_raw.csv")

RAW_DIR.mkdir(parents=True, exist_ok=True)


def download_company(ticker: str, category: str = None, region: str = None):
    """Download annual financial statements for a single company."""
    # Sanitize ticker for filename (replace dots with underscores)
    safe_ticker = ticker.replace('.', '_')
    print(f"Downloading {ticker} (file prefix: {safe_ticker})...")

    try:
        tk = yf.Ticker(ticker)

        income = tk.financials
        balance = tk.balance_sheet
        cashflow = tk.cashflow
        info = tk.info

        if not income.empty:
            income.to_csv(RAW_DIR / f"{safe_ticker}_income.csv")
        else:
            print(f"  [WARN] No income statement for {ticker}")

        if not balance.empty:
            balance.to_csv(RAW_DIR / f"{safe_ticker}_balance.csv")
        else:
            print(f"  [WARN] No balance sheet for {ticker}")

        if not cashflow.empty:
            cashflow.to_csv(RAW_DIR / f"{safe_ticker}_cashflow.csv")
        else:
            print(f"  [WARN] No cashflow statement for {ticker}")

        meta = {
            "ticker": ticker,
            "safe_ticker": safe_ticker,
            "category": category,
            "region": region or "global",
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "market_cap": info.get("marketCap"),
            "currency": info.get("currency"),
            "financial_currency": info.get("financialCurrency"),
            "country": info.get("country"),
            "company_name": info.get("longName"),
            "exchange": info.get("exchange"),
        }

        with open(RAW_DIR / f"{safe_ticker}_meta.json", "w") as f:
            json.dump(meta, f, indent=2)

        print(f"  \u2713 Successfully downloaded {ticker}")
        return True

    except Exception as e:
        print(f"  \u2717 Failed for {ticker}: {e}")
        return False


def main():
    """Download annual financial statements for all companies in the universe."""
    print("=" * 80)
    print("DOWNLOADING ANNUAL FINANCIAL STATEMENTS")
    print("=" * 80)

    if not UNIVERSE_PATH.exists():
        print(f"[ERROR] Universe file not found at {UNIVERSE_PATH}")
        print("Please run the fundamentals scraping script first.")
        return

    universe_df = pd.read_csv(UNIVERSE_PATH)

    print(f"\nFound {len(universe_df)} companies in universe")
    if 'category' in universe_df.columns:
        print(f"Categories: {universe_df['category'].unique().tolist()}")

    success_count = 0
    fail_count = 0

    for idx, row in universe_df.iterrows():
        ticker = row['ticker']
        category = row.get('category', None)
        region = row.get('region', 'global')

        print(f"\n[{idx+1}/{len(universe_df)}] Processing {ticker} ({category}, region={region})...")

        success = download_company(ticker, category, region=region)

        if success:
            success_count += 1
        else:
            fail_count += 1

        time.sleep(0.5)  # Be nice to the API

    print("\n" + "=" * 80)
    print("DOWNLOAD SUMMARY (ANNUAL)")
    print("=" * 80)
    print(f"Total companies: {len(universe_df)}")
    print(f"Successful: {success_count}")
    print(f"Failed: {fail_count}")
    print(f"\nData saved to: {RAW_DIR}")
    print("=" * 80)


if __name__ == "__main__":
    main()
