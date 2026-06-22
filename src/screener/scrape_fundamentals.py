import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import time
import re
import json
from pathlib import Path

# ============================================================================
# DEFAULT CATEGORIES (fallback if sectors.json missing or has no URLs)
# ============================================================================
CATEGORIES = {
    "electricity": "https://companiesmarketcap.com/electricity/largest-electricity-companies-by-market-cap/",
    "semiconductors": "https://companiesmarketcap.com/semiconductors/largest-semiconductor-companies-by-market-cap/",
    "software": "https://companiesmarketcap.com/software/largest-software-companies-by-market-cap/",
    "energy": "https://companiesmarketcap.com/energy/largest-companies-by-market-cap/",
    "defense": "https://companiesmarketcap.com/aerospace/largest-companies-by-market-cap/",
    "electronics": "https://companiesmarketcap.com/electronics/largest-electronic-manufacturing-by-market-cap/",
    "ai": "https://companiesmarketcap.com/artificial-intelligence/largest-ai-companies-by-marketcap/"
}

# ============================================================================
# SECTORS CONFIG LOADER
# ============================================================================

def load_sectors_config():
    """Load sectors from sectors.json, falling back to default CATEGORIES."""
    sectors_file = Path("sectors.json")
    if sectors_file.exists():
        with open(sectors_file, 'r') as f:
            return json.load(f)
    
    # Build default config from CATEGORIES (all scraped, global region)
    default = {"sectors": {}}
    for key, url in CATEGORIES.items():
        default["sectors"][key] = {
            "name": key.replace("-", " ").title(),
            "enabled": True,
            "type": "scraped",
            "url": url,
            "region": "global"
        }
    return default

# ============================================================================
# TICKER VALIDATION
# ============================================================================

def extract_ticker_from_text(text):
    """Extract ticker symbol from text like 'NVIDIANVDA' or 'Alphabet (Google)GOOG'"""
    if not text:
        return None
    
    text = text.strip()
    match = re.search(r'([A-Z][A-Z0-9.]*?)$', text)
    if match:
        ticker = match.group(1)
        if len(ticker) <= 6 and not ticker.endswith('.'):
            return ticker
    
    if text.isupper() and len(text) <= 6:
        return text
    
    return None

def is_usa_ticker(ticker):
    """Check if a ticker is likely a USA ticker based on format."""
    if not ticker:
        return False
    
    ticker = ticker.strip()
    
    if re.match(r'^[A-Z]{1,5}$', ticker):
        return True
    
    if '.' in ticker:
        return False
    if len(ticker) > 5:
        return False
    
    return False

def is_valid_ticker(ticker):
    """Check if ticker is valid (USA or other known exchange)."""
    if not ticker:
        return False
    
    ticker = ticker.strip()
    
    # USA ticker: 1-5 uppercase letters
    if re.match(r'^[A-Z]{1,5}$', ticker):
        return True
    
    # Other exchange suffixes (future-proofing): .L (London), .DE (Germany), etc.
    if re.match(r'^[A-Z0-9]{1,6}\.[A-Z]{1,3}$', ticker):
        return True
    
    return False

# ============================================================================
# WEB SCRAPING (for "scraped" type sectors)
# ============================================================================

def scrape_top_companies(url, top_n=10, usa_only=True, debug=False):
    """Scrape top N companies from companiesmarketcap.com category page."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        table = soup.find('table')
        if not table:
            print(f"[WARN] No table found at {url}")
            return []
        
        tickers = []
        rows = table.find_all('tr')[1:]  # Skip header
        
        if debug:
            print(f"  [DEBUG] Found {len(rows)} rows in table")
        
        collected_count = 0
        for idx, row in enumerate(rows):
            cells = row.find_all('td')
            
            if debug and idx < 3:
                print(f"  [DEBUG] Row {idx}: {len(cells)} cells")
            
            if len(cells) >= 3:
                ticker_cell = cells[2]
                
                code_elem = ticker_cell.find('div', class_='company-code')
                if code_elem:
                    ticker = code_elem.get_text(strip=True)
                else:
                    full_text = ticker_cell.get_text(strip=True)
                    ticker = extract_ticker_from_text(full_text)
                
                if debug and idx < 3:
                    print(f"    Extracted ticker: {ticker}")
                
                if ticker and ticker not in ['n/a', 'N/A', '-', '']:
                    ticker = ticker.strip()
                    
                    if usa_only:
                        if is_usa_ticker(ticker):
                            tickers.append(ticker)
                            collected_count += 1
                            if debug:
                                print(f"    ✓ USA ticker: {ticker}")
                        else:
                            if debug and idx < 10:
                                print(f"    ✗ Non-USA ticker skipped: {ticker}")
                    else:
                        tickers.append(ticker)
                        collected_count += 1
                    
                    if collected_count >= top_n:
                        break
        
        return tickers
    
    except Exception as e:
        print(f"[ERROR] Failed to scrape {url}: {e}")
        import traceback
        traceback.print_exc()
        return []

def get_all_tickers(categories_dict, top_n=10, usa_only=True, debug=False):
    """Scrape tickers from all categories (legacy function for backward compat)."""
    all_tickers = {}
    
    for category, url in categories_dict.items():
        print(f"Scraping {category} {'(USA only)' if usa_only else ''}...")
        tickers = scrape_top_companies(url, top_n, usa_only=usa_only, debug=debug)
        all_tickers[category] = tickers
        print(f"  Found {len(tickers)} tickers: {tickers}")
        time.sleep(1)
    
    return all_tickers

# ============================================================================
# FUNDAMENTALS FETCHING
# ============================================================================

def extract_equity(bs):
    """Extract equity from balance sheet."""
    for key in [
        "Common Stock Equity",
        "Total Stockholder Equity",
        "Total Equity Gross Minority Interest",
    ]:
        if key in bs.index:
            return bs.loc[key].iloc[0], key
    return None, None

def fetch_fundamentals(tickers, category=None, region=None, usd_only=True):
    """Fetch fundamental data for given tickers.

    When usd_only is True, companies whose financial statements are NOT
    reported in USD are dropped here, before they ever enter the universe.
    This is the real "US company" gate: the ticker-format filter upstream
    only checks the symbol shape, so US-listed foreign issuers (ADRs such as
    TSM/ASML/SAP that trade in USD but report in TWD/EUR) pass it and then
    poison the valuation ratios — a USD market cap divided by native-currency
    statement figures. Filtering on financialCurrency removes exactly those
    names while keeping USD-reporting foreign issuers like ARM, whose ratios
    are correct. financialCurrency isn't known until .info is fetched, which
    is why the filter lives here rather than at scrape time.
    """
    rows = []
    skipped = []
    for t in tickers:
        try:
            print(f"  Fetching {t}...")
            tk = yf.Ticker(t)
            info = tk.info

            fin_ccy = (info.get("financialCurrency") or "").upper().strip()
            # Drop only when we positively know the reporting currency and it
            # isn't USD. A missing/blank value is left in (treated as unknown
            # rather than non-USD) to avoid false drops on transient .info gaps.
            if usd_only and fin_ccy and fin_ccy != "USD":
                skipped.append((t, fin_ccy))
                print(f"  [SKIP] {t}: reports in {fin_ccy}, not USD — excluded")
                continue

            bs = tk.balance_sheet
            
            equity, equity_source = None, None
            if not bs.empty:
                equity, equity_source = extract_equity(bs)
            
            rows.append({
                "ticker": t,
                "category": category,
                "region": region or "global",
                "company_name": info.get("longName"),
                "country": info.get("country"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "market_cap": info.get("marketCap"),
                "revenue": info.get("totalRevenue"),
                "net_income": info.get("netIncomeToCommon"),
                "fcf": info.get("freeCashflow"),
                "equity": equity,
                "equity_source": equity_source,
                "debt": info.get("totalDebt"),
                "ebit": info.get("ebitda"),
                "currency": info.get("currency"),
                "financial_currency": info.get("financialCurrency"),
            })
            time.sleep(0.5)
            
        except Exception as e:
            print(f"[WARN] {t} failed: {e}")
    
    if skipped:
        print(f"  [INFO] Excluded {len(skipped)} non-USD reporter(s): "
              + ", ".join(f"{t} ({c})" for t, c in skipped))
    return pd.DataFrame(rows)

# ============================================================================
# HYBRID TICKER COLLECTION (scraped + manual)
# ============================================================================

def collect_all_tickers(sectors_config, top_n=10, usa_only=True, debug=False):
    """
    Collect tickers from all enabled sectors.
    Supports both 'scraped' sectors (web scraping) and 'manual' sectors (ticker lists).
    
    For 'manual' type sectors, companies_per_sector (top_n) is IGNORED — 
    all tickers in the list are always used.
    """
    all_tickers = {}
    
    for sector_key, sector_info in sectors_config.get("sectors", {}).items():
        if not sector_info.get("enabled", True):
            if debug:
                print(f"  [SKIP] {sector_key}: disabled")
            continue
        
        sector_type = sector_info.get("type", "scraped")
        sector_name = sector_info.get("name", sector_key)
        region = sector_info.get("region", "global")
        
        if sector_type == "scraped":
            # Use URL from sectors.json, or fall back to CATEGORIES
            url = sector_info.get("url", CATEGORIES.get(sector_key))
            if not url:
                print(f"[WARN] No URL found for scraped sector '{sector_key}', skipping")
                continue
            
            print(f"Scraping {sector_name} ({sector_key}) {'(USA only)' if usa_only else ''}...")
            tickers = scrape_top_companies(url, top_n, usa_only=usa_only, debug=debug)
            print(f"  Found {len(tickers)} tickers: {tickers}")
            time.sleep(1)
        
        elif sector_type == "manual":
            # Use manual ticker list — ignore companies_per_sector
            raw_tickers = sector_info.get("tickers", [])
            tickers = [t for t in raw_tickers if is_valid_ticker(t)]
            
            if len(tickers) != len(raw_tickers):
                invalid = set(raw_tickers) - set(tickers)
                print(f"[WARN] Invalid tickers skipped in {sector_key}: {invalid}")
            
            print(f"Manual sector {sector_name} ({sector_key}): {len(tickers)} tickers: {tickers}")
        
        else:
            print(f"[WARN] Unknown sector type '{sector_type}' for {sector_key}, skipping")
            continue
        
        all_tickers[sector_key] = {
            "tickers": tickers,
            "region": region,
            "name": sector_name,
            "type": sector_type
        }
    
    return all_tickers

# ============================================================================
# MAIN
# ============================================================================

def main(debug=False):
    # Load config to get companies_per_sector
    config_file = Path("config.json")
    usd_only = True
    if config_file.exists():
        with open(config_file, 'r') as f:
            config = json.load(f)
            top_n = config.get("companies_per_sector", 10)
            usd_only = config.get("usd_only", True)
    else:
        top_n = 10
    
    # Load sectors configuration
    sectors_config = load_sectors_config()
    
    # Count sector types
    enabled_sectors = {k: v for k, v in sectors_config["sectors"].items() if v.get("enabled", True)}
    scraped_count = sum(1 for v in enabled_sectors.values() if v.get("type", "scraped") == "scraped")
    manual_count = sum(1 for v in enabled_sectors.values() if v.get("type") == "manual")
    
    print("="*80)
    print(f"SCRAPING TOP {top_n} COMPANIES PER SCRAPED SECTOR")
    print(f"Enabled sectors: {len(enabled_sectors)} ({scraped_count} scraped, {manual_count} manual)")
    print(f"USD-only filter: {'ON (non-USD reporters excluded)' if usd_only else 'OFF'}")
    print("="*80)
    
    # Collect tickers using hybrid approach
    all_tickers = collect_all_tickers(sectors_config, top_n=top_n, usa_only=True, debug=debug)
    
    # Summary
    unique_tickers = set()
    for sector_key, sector_data in all_tickers.items():
        for ticker in sector_data["tickers"]:
            unique_tickers.add(ticker)
    
    print(f"\n{'='*80}")
    print(f"Total unique tickers found: {len(unique_tickers)}")
    print(f"{'='*80}\n")
    
    # Fetch fundamentals for all tickers
    all_data = []
    
    for sector_key, sector_data in all_tickers.items():
        tickers = sector_data["tickers"]
        region = sector_data["region"]
        
        if tickers:
            print(f"\nFetching fundamentals for {sector_data['name']} ({len(tickers)} companies, region={region})...")
            df_category = fetch_fundamentals(tickers, category=sector_key, region=region, usd_only=usd_only)
            all_data.append(df_category)
    
    if all_data:
        df_all = pd.concat(all_data, ignore_index=True)
        
        # Use relative path for output
        output_dir = Path("data")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "fundamentals_raw.csv"
        df_all.to_csv(output_path, index=False)
        
        print(f"\n{'='*80}")
        print("DATA SUMMARY")
        print("="*80)
        print(f"\nTotal companies fetched: {len(df_all)}")
        print(f"\nBreakdown by category:")
        print(df_all['category'].value_counts())
        
        if 'region' in df_all.columns:
            print(f"\nBreakdown by region:")
            print(df_all['region'].value_counts())
        
        if 'country' in df_all.columns:
            print(f"\nBreakdown by country (from yfinance):")
            print(df_all['country'].value_counts())
        
        print(f"\n{'='*80}")
        print("SAMPLE DATA")
        print("="*80)
        print(df_all[["ticker", "company_name", "country", "category", "region", "market_cap"]].head(20))
        
        print(f"\n{'='*80}")
        print(f"Data saved to: {output_path}")
        print("="*80)
        
        return df_all
    else:
        print("[ERROR] No data collected!")
        return None

if __name__ == "__main__":
    df = main(debug=False)
