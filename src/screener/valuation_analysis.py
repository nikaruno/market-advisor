"""
Valuation pipeline (standalone).

Computes trailing valuation ratios for every company in the universe and ranks
them by EV/EBITDA (cheapest first). All trailing ratios are on a TTM /
most-recent-quarter basis, so they reflect the latest reported quarter rather
than a stale fiscal year-end:

  - EV/EBITDA = (market cap + latest-quarter debt - latest-quarter cash) / TTM EBITDA   <- ranked on this
  - P/E       = market cap / TTM net income
  - P/B       = market cap / latest-quarter equity
  - Fwd P/E   = yfinance forward P/E (analyst NTM estimate; display only, NOT TTM)

Every trailing ratio carries a *_basis flag so its provenance is always visible:
  'ttm'  = summed/taken from the quarterly statements downloaded here
  'info' = yfinance's prepackaged trailing field (still TTM, less transparent)
A ratio is left blank rather than guessed when neither source is usable.

REQUIRES the quality pipeline to have run first (it builds the USD-only
universe). Prices/fundamentals move every quarter, so run this on its own
cadence, independently of the yearly quality pipeline.

Input  : data/fundamentals_raw.csv                 (universe: ticker + category)
Output : data/valuation/raw/<TICKER>_income_q.csv  (raw quarterly statements, own folder)
         data/valuation/raw/<TICKER>_balance_q.csv
         data/valuation/valuation.csv               (ratios + ranking + basis flags)
"""
import yfinance as yf
import pandas as pd
import numpy as np
from pathlib import Path
import time

UNIVERSE_PATH = Path("data/fundamentals_raw.csv")
VAL_DIR = Path("data/valuation")
RAW_DIR = VAL_DIR / "raw"
OUTPUT_PATH = VAL_DIR / "valuation.csv"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# Canonical statement row-keys (match the quality pipeline's parsing).
NET_INCOME_KEYS = ["Net Income", "Net Income Common Stockholders"]
EBITDA_KEYS = ["EBITDA", "Normalized EBITDA"]
EQUITY_KEYS = ["Total Equity Gross Minority Interest", "Stockholders Equity",
               "Total Stockholder Equity", "Common Stock Equity"]
DEBT_KEYS = ["Total Debt", "Long Term Debt And Capital Lease Obligation"]
CASH_KEYS = ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"]

PE_CAP, PB_CAP, EV_CAP = 999.0, 99.0, 999.0


def _ttm_flow(df, keys, min_quarters=4):
    """TTM sum of a flow row from a quarterly statement (newest-first columns).
    Returns NaN unless >= min_quarters are present — a partial sum would
    understate the annual flow and distort the ratio."""
    if df is None:
        return np.nan
    for k in keys:
        if k in df.index:
            v = pd.to_numeric(df.loc[k], errors="coerce").dropna()
            if len(v) >= min_quarters:
                return float(v.iloc[:min_quarters].sum())
    return np.nan


def _latest(df, keys):
    """Most recent quarter value of a stock row (equity, debt, cash)."""
    if df is None:
        return np.nan
    for k in keys:
        if k in df.index:
            v = pd.to_numeric(df.loc[k], errors="coerce").dropna()
            if len(v) > 0:
                return float(v.iloc[0])
    return np.nan


def _pos(x):
    return x is not None and not pd.isna(x) and x > 0


def compute_valuation(ticker, info, q_income, q_balance):
    """Compute the trailing ratios for one company. market cap is spot (USD);
    flow items are TTM, stock items most-recent-quarter, each with a fallback to
    yfinance's trailing .info fields. Returns a dict (or None if no market cap)."""
    mc = info.get("marketCap")
    if not _pos(mc):
        return None
    out = {"ticker": ticker, "market_cap": mc}

    # --- P/E (TTM net income) ---
    ni = _ttm_flow(q_income, NET_INCOME_KEYS)
    pe_basis = "ttm"
    if pd.isna(ni):
        ni, pe_basis = info.get("netIncomeToCommon"), "info"
    if _pos(ni):
        out["pe_ttm"] = round(min(mc / ni, PE_CAP), 2)
        out["pe_basis"] = pe_basis
    else:
        out["pe_ttm"], out["pe_basis"] = np.nan, ""

    # --- Forward P/E (analyst NTM estimate; display only) ---
    fpe = info.get("forwardPE")
    out["fwd_pe"] = round(min(float(fpe), PE_CAP), 2) if _pos(fpe) else np.nan

    # --- P/B (latest-quarter equity) ---
    eq = _latest(q_balance, EQUITY_KEYS)
    if _pos(eq):
        out["pb"], out["pb_basis"] = round(min(mc / eq, PB_CAP), 2), "ttm"
    else:
        pb_info = info.get("priceToBook")
        if _pos(pb_info):
            out["pb"], out["pb_basis"] = round(min(float(pb_info), PB_CAP), 2), "info"
        else:
            out["pb"], out["pb_basis"] = np.nan, ""

    # --- EV/EBITDA (TTM EBITDA + latest-quarter debt/cash) ---
    ebitda = _ttm_flow(q_income, EBITDA_KEYS)
    ev_basis = "ttm"
    if pd.isna(ebitda):
        ebitda, ev_basis = info.get("ebitda"), "info"
    if _pos(ebitda):
        debt = _latest(q_balance, DEBT_KEYS)
        cash = _latest(q_balance, CASH_KEYS)
        if pd.isna(debt):
            debt = info.get("totalDebt")
        if pd.isna(cash):
            cash = info.get("totalCash")
        debt = 0.0 if (debt is None or pd.isna(debt)) else float(debt)
        cash = 0.0 if (cash is None or pd.isna(cash)) else float(cash)
        ev = mc + debt - cash
        if ev > 0:
            out["ev_ebitda"], out["ev_basis"] = round(min(ev / ebitda, EV_CAP), 2), ev_basis
        else:
            out["ev_ebitda"], out["ev_basis"] = np.nan, ""
    else:
        # last resort: yfinance's own EV/EBITDA
        ee = info.get("enterpriseToEbitda")
        if _pos(ee):
            out["ev_ebitda"], out["ev_basis"] = round(min(float(ee), EV_CAP), 2), "info"
        else:
            out["ev_ebitda"], out["ev_basis"] = np.nan, ""

    return out


def analyze_ticker(ticker, category=None):
    safe = ticker.replace(".", "_")
    try:
        tk = yf.Ticker(ticker)
        info = tk.info
        q_income = tk.quarterly_financials
        q_balance = tk.quarterly_balance_sheet

        # Save raw quarterly statements to the valuation folder.
        if q_income is not None and not q_income.empty:
            q_income.to_csv(RAW_DIR / f"{safe}_income_q.csv")
        if q_balance is not None and not q_balance.empty:
            q_balance.to_csv(RAW_DIR / f"{safe}_balance_q.csv")

        result = compute_valuation(ticker, info, q_income, q_balance)
        if result is None:
            print(f"  [WARN] No market cap for {ticker}")
            return None
        result["category"] = category
        ev = result.get("ev_ebitda")
        print(f"  \u2713 {ticker}: EV/EBITDA={ev if pd.notna(ev) else 'n/a'} "
              f"P/E={result.get('pe_ttm')} ({result.get('ev_basis') or '-'})")
        return result
    except Exception as e:
        print(f"  \u2717 {ticker} failed: {e}")
        return None


def main():
    print("=" * 80)
    print("VALUATION ANALYSIS (TTM, ranked by EV/EBITDA)")
    print("=" * 80)

    if not UNIVERSE_PATH.exists():
        print(f"[ERROR] Universe not found at {UNIVERSE_PATH}.")
        print("Run the quality pipeline first:  bash run_quality.sh")
        return

    universe = pd.read_csv(UNIVERSE_PATH).drop_duplicates(subset="ticker", keep="first")
    print(f"\nAnalyzing {len(universe)} companies...\n")

    rows = []
    for idx, row in universe.iterrows():
        ticker = row["ticker"]
        category = row.get("category")
        print(f"[{idx+1}/{len(universe)}] {ticker} ({category})...")
        r = analyze_ticker(ticker, category=category)
        if r:
            rows.append(r)
        time.sleep(0.4)

    if not rows:
        print("\n[ERROR] No valuation rows produced.")
        return

    cols = ["ticker", "category", "market_cap", "ev_ebitda", "ev_basis",
            "pe_ttm", "pe_basis", "fwd_pe", "pb", "pb_basis"]
    df = pd.DataFrame(rows).reindex(columns=cols)

    # Rank by EV/EBITDA ascending (cheapest = rank 1); names without a valid
    # EV/EBITDA sort to the bottom and get no rank.
    df = df.sort_values("ev_ebitda", ascending=True, na_position="last").reset_index(drop=True)
    df.insert(0, "value_rank", df["ev_ebitda"].rank(method="min", ascending=True).astype("Int64"))
    df.to_csv(OUTPUT_PATH, index=False)

    rated = df["ev_ebitda"].notna().sum()
    print("\n" + "=" * 80)
    print("VALUATION SUMMARY")
    print("=" * 80)
    print(f"Companies: {len(df)}  |  with EV/EBITDA: {rated}")
    if rated:
        print(f"Cheapest:  {df.iloc[0]['ticker']} @ EV/EBITDA {df.iloc[0]['ev_ebitda']}")
        print(f"Median EV/EBITDA: {df['ev_ebitda'].median():.1f}")
    print(f"\nRaw quarterly statements: {RAW_DIR}/")
    print(f"Ratings: {OUTPUT_PATH}")
    print("=" * 80)


if __name__ == "__main__":
    main()
