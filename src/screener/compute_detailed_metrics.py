import pandas as pd
import numpy as np
from pathlib import Path

RAW_DIR = Path("data/fundamentals/raw")
UNIVERSE_PATH = Path("data/fundamentals_raw.csv")
OUTPUT_PATH = Path("data/fundamentals/company_metrics.csv")

MIN_YEARS = 3

def ema_mean(series):
    """Exponential moving average — recent years weighted more heavily.
    With span=n (number of values), alpha = 2/(n+1).
    For 4 years: weights are approximately 10%, 17%, 28%, 46% (oldest→newest).
    Series must be in chronological order (oldest first).
    """
    vals = series.dropna()
    if len(vals) == 0:
        return np.nan
    if len(vals) == 1:
        return vals.iloc[0]
    n = len(vals)
    alpha = 2.0 / (n + 1)
    weights = np.array([(1 - alpha) ** (n - 1 - i) for i in range(n)])
    return np.average(vals.values, weights=weights)

# Key variations for different financial statement line items
CFO_KEYS = ["Total Cash From Operating Activities", "Cash Flow From Continuing Operating Activities", 
            "Net Cash Provided by Operating Activities", "Operating Cash Flow"]
REVENUE_KEYS = ["Total Revenue", "Revenue"]
OP_INCOME_KEYS = ["Operating Income", "Operating Income Or Loss"]
NET_INCOME_KEYS = ["Net Income", "Net Income Common Stockholders"]
EQUITY_KEYS = ["Total Equity Gross Minority Interest", "Stockholders Equity", 
               "Total Stockholder Equity", "Common Stock Equity"]
DEBT_KEYS = ["Total Debt", "Long Term Debt And Capital Lease Obligation", "Total Liabilities Net Minority Interest"]
CASH_KEYS = ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"]
EBITDA_KEYS = ["EBITDA", "Normalized EBITDA"]
INTEREST_KEYS = ["Interest Expense", "Interest Expense Non Operating"]
CAPEX_KEYS = ["Capital Expenditures", "Capital Expenditure"]

def get_row(df, names):
    """Try to find a row in dataframe using multiple possible names."""
    for n in names:
        if n in df.index:
            return df.loc[n]
    return None

def load_statements(ticker):
    """Load financial statements for a ticker.
    Handles safe filenames where dots in a ticker are replaced with
    underscores (e.g., BRK.B → BRK_B_income.csv).
    """
    safe_ticker = ticker.replace('.', '_')
    
    # Try both: original ticker and safe (dot→underscore) version
    for t in [ticker, safe_ticker]:
        income_path = RAW_DIR / f"{t}_income.csv"
        balance_path = RAW_DIR / f"{t}_balance.csv"
        cashflow_path = RAW_DIR / f"{t}_cashflow.csv"
        
        if income_path.exists() and balance_path.exists() and cashflow_path.exists():
            try:
                income = pd.read_csv(income_path, index_col=0)
                balance = pd.read_csv(balance_path, index_col=0)
                cashflow = pd.read_csv(cashflow_path, index_col=0)
                return income, balance, cashflow
            except Exception as e:
                print(f"  [WARN] Error reading files for {ticker}: {e}")
                return None, None, None
    
    print(f"  [WARN] Missing files for {ticker} (tried {ticker} and {safe_ticker})")
    return None, None, None

def compute_metrics(ticker, category=None, region=None, tax_rate=0.25,
                    financial_currency=None):
    """Compute fundamental quality metrics for a company."""
    try:
        income, balance, cashflow = load_statements(ticker)
        
        if income is None or balance is None or cashflow is None:
            return None
        
        # Ensure chronological order (oldest to newest)
        income = income.iloc[:, ::-1]
        balance = balance.iloc[:, ::-1]
        cashflow = cashflow.iloc[:, ::-1]

        # Statements are used as reported. This universe is US-listed, so
        # figures are USD; financial_currency is kept for auditability only and
        # no FX conversion is applied.
        currency_used = (financial_currency or "USD").upper().strip() or "USD"
        if currency_used != "USD":
            print(f"  [WARN] {ticker}: statements reported in {currency_used}; "
                  f"used as-is (no conversion)")
        
        # Check available years
        years_available = min(income.shape[1], balance.shape[1], cashflow.shape[1])
        
        if years_available < MIN_YEARS:
            print(f"  [WARN] {ticker}: Only {years_available} years of data available (need {MIN_YEARS})")
            return None
        
        years_to_use = min(years_available, 4)
        print(f"  Using {years_to_use} years of data")
        
        # Extract metrics
        revenue = get_row(income, REVENUE_KEYS)
        op_income = get_row(income, OP_INCOME_KEYS)
        net_income = get_row(income, NET_INCOME_KEYS)
        equity = get_row(balance, EQUITY_KEYS)
        debt = get_row(balance, DEBT_KEYS)
        cash = get_row(balance, CASH_KEYS)
        cfo = get_row(cashflow, CFO_KEYS)
        capex = get_row(cashflow, CAPEX_KEYS)
        ebitda = get_row(income, EBITDA_KEYS)
        interest = get_row(income, INTEREST_KEYS)
        
        # Check for missing critical data
        if any(x is None for x in [revenue, op_income, net_income, equity, cfo, capex]):
            print(f"  [WARN] {ticker}: Missing critical financial data")
            return None
        
        # Get last N years
        revenue = revenue.iloc[-years_to_use:]
        op_income = op_income.iloc[-years_to_use:]
        net_income = net_income.iloc[-years_to_use:]
        equity = equity.iloc[-years_to_use:]
        cfo = cfo.iloc[-years_to_use:]
        capex = capex.iloc[-years_to_use:]
        
        # Optional metrics
        debt = debt.iloc[-years_to_use:] if debt is not None else pd.Series([0]*years_to_use)
        cash = cash.iloc[-years_to_use:] if cash is not None else pd.Series([0]*years_to_use)
        ebitda_is_real = ebitda is not None
        ebitda = ebitda.iloc[-years_to_use:] if ebitda is not None else op_income
        interest = interest.iloc[-years_to_use:] if interest is not None else pd.Series([1]*years_to_use)
        
        # PROFITABILITY
        nopat = op_income * (1 - tax_rate)
        invested_capital = equity + debt - cash
        invested_capital = invested_capital.replace(0, np.nan)
        roic = nopat / invested_capital
        roic_avg = ema_mean(roic)  # EMA: recent years weighted more

        # CASH FLOW
        fcf = cfo - capex.abs()
        fcf_margin = ema_mean(fcf / revenue)  # EMA
        cfo_to_ni = ema_mean(cfo / net_income)  # EMA
        
        # BALANCE SHEET
        net_debt = debt - cash
        net_debt_ebitda = ema_mean(net_debt / ebitda)  # EMA
        # Note: interest_coverage removed — too noisy (NaN when interest=0, 
        # extreme values -246x to +303x, redundant with leverage)
        
        # DURABILITY
        revenue_cagr = (revenue.iloc[-1] / revenue.iloc[0]) ** (1/(years_to_use-1)) - 1
        
        # EBITDA GROWTH (replaces net income growth)
        # EBITDA is far less distorted than net income by tax timing, one-time
        # items, and non-operating income. A deferred-tax benefit or investment
        # income can inflate NI growth while the core business is flat (e.g. GEV
        # post-spin-off), and EBITDA strips that out. Net income still enters
        # the score via Cash Quality (cfo_to_ni), which flags the divergence.
        # Same sign/turnaround handling as the old NI growth: CAGR when both
        # endpoints are positive, capped flags otherwise.
        eb_first = ebitda.iloc[0]
        eb_last = ebitda.iloc[-1]
        if pd.isna(eb_first) or pd.isna(eb_last):
            ebitda_cagr = np.nan
        elif eb_first > 0 and eb_last > 0:
            ebitda_cagr = (eb_last / eb_first) ** (1/(years_to_use-1)) - 1
        elif eb_first < 0 and eb_last > 0:
            # Turned EBITDA-positive — strong operational turnaround
            ebitda_cagr = 1.0  # cap at +100%
        elif eb_first > 0 and eb_last < 0:
            # Slid to negative EBITDA — operations broke
            ebitda_cagr = -1.0  # cap at -100%
        else:
            # Both negative — credit shrinking losses, penalise growing ones
            if abs(eb_last) < abs(eb_first):
                ebitda_cagr = 0.5
            else:
                ebitda_cagr = -0.5
        
        return {
            "ticker": ticker,
            "category": category,
            "region": region or "global",
            "currency": currency_used,
            "financial_currency": currency_used,
            "years_used": years_to_use,
            "roic_avg": roic_avg,
            "fcf_margin": fcf_margin,
            "cfo_to_ni": cfo_to_ni,
            "net_debt_ebitda": net_debt_ebitda,
            "revenue_cagr": revenue_cagr,
            "ebitda_cagr": ebitda_cagr,
            "ebitda_source": "ebitda" if ebitda_is_real else "operating_income",
        }
        
    except Exception as e:
        print(f"  [ERROR] {ticker}: {e}")
        return None

def main():
    """Process all companies in the universe and compute quality metrics."""
    
    print("="*80)
    print("COMPUTING COMPANY QUALITY METRICS")
    print(f"(Using {MIN_YEARS}-4 years of data)")
    print("="*80)
    
    if not UNIVERSE_PATH.exists():
        print(f"[ERROR] Universe file not found at {UNIVERSE_PATH}")
        return
    
    universe_df = pd.read_csv(UNIVERSE_PATH)
    print(f"\nProcessing {len(universe_df)} companies...")
    
    rows = []
    success_count = 0
    fail_count = 0
    
    # Load sectors.json for region info if available
    sectors_regions = {}
    sectors_path = Path("sectors.json")
    if sectors_path.exists():
        import json
        with open(sectors_path, 'r') as f:
            sectors_data = json.load(f)
        for key, info in sectors_data.get("sectors", {}).items():
            region = info.get("region", "global")
            sectors_regions[key] = region
    
    for idx, row in universe_df.iterrows():
        ticker = row['ticker']
        category = row.get('category', None)
        
        # Determine region + financial currency from meta (try both the raw
        # ticker and the dot→underscore safe filename), then sectors.json.
        region = "global"
        financial_currency = None
        import json
        meta = None
        for mt in [ticker, ticker.replace('.', '_')]:
            meta_path = RAW_DIR / f"{mt}_meta.json"
            if meta_path.exists():
                with open(meta_path, 'r') as f:
                    meta = json.load(f)
                break
        if meta is not None:
            region = meta.get("region", "global")
            financial_currency = meta.get("financial_currency")
        elif category and category in sectors_regions:
            region = sectors_regions[category]
        
        print(f"\n[{idx+1}/{len(universe_df)}] Computing metrics for {ticker} "
              f"({category}, {region}, ccy={financial_currency or '?'})...")
        
        metrics = compute_metrics(ticker, category, region=region,
                                  financial_currency=financial_currency)
        
        if metrics:
            rows.append(metrics)
            success_count += 1
            print(f"  ✓ Success")
        else:
            fail_count += 1
            print(f"  ✗ Failed")
    
    if rows:
        df = pd.DataFrame(rows)
        
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(OUTPUT_PATH, index=False)
        
        print("\n" + "="*80)
        print("METRICS SUMMARY")
        print("="*80)
        print(f"\nTotal processed: {len(universe_df)}")
        print(f"Successful: {success_count}")
        print(f"Failed: {fail_count}")
        print(f"\nMetrics saved to: {OUTPUT_PATH}")
        
        print("\n" + "="*80)
        print("YEARS OF DATA USED")
        print("="*80)
        print(df['years_used'].value_counts().sort_index())
        
        print("\n" + "="*80)
        print("TOP 10 COMPANIES BY AVERAGE ROIC")
        print("="*80)
        top_roic = df.nlargest(10, 'roic_avg')[['ticker', 'category', 'years_used', 'roic_avg', 'fcf_margin', 'revenue_cagr']]
        print(top_roic.to_string(index=False))
        
        if 'category' in df.columns:
            print("\n" + "="*80)
            print("AVERAGE ROIC BY CATEGORY")
            print("="*80)
            category_stats = df.groupby('category').agg({
                'roic_avg': 'mean',
                'fcf_margin': 'mean',
                'revenue_cagr': 'mean',
                'years_used': 'mean'
            }).round(4)
            print(category_stats)
        
        return df
    else:
        print("\n[ERROR] No metrics computed successfully!")
        return None

if __name__ == "__main__":
    df = main()
