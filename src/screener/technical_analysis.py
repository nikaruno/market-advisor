"""
Technical analysis pipeline (standalone).

Downloads recent daily price history for every company in the universe and
computes a TradingView-style technical rating (Strong Buy ... Strong Sell) from
a vote of moving averages and oscillators. This is the most dynamic pipeline —
prices move every day — so run it whenever you want a fresh read, independently
of the (yearly) quality pipeline.

REQUIRES the quality pipeline to have run first: the universe of companies is
read from data/fundamentals_raw.csv (produced by scrape_fundamentals.py). If
that file is missing, run `bash run_quality.sh` first.

Input  : data/fundamentals_raw.csv                  (universe: ticker + category)
Output : data/technical/prices/<TICKER>.csv         (raw daily OHLCV, its own folder)
         data/technical/technical_analysis.csv      (one rating row per company)

Indicators are computed with pandas/numpy (no extra dependencies). The rating
follows TradingView's summary convention: each moving average and oscillator
votes Buy(+1) / Neutral(0) / Sell(-1); the average vote maps to a label.
"""
import yfinance as yf
import pandas as pd
import numpy as np
from pathlib import Path
import time

UNIVERSE_PATH = Path("data/fundamentals_raw.csv")
TECH_DIR = Path("data/technical")
PRICES_DIR = TECH_DIR / "prices"
OUTPUT_PATH = TECH_DIR / "technical_analysis.csv"

PRICES_DIR.mkdir(parents=True, exist_ok=True)

MA_PERIODS = [10, 20, 50, 100, 200]


# ---------------------------------------------------------------------------
# Indicators (pure functions on a price DataFrame with Open/High/Low/Close)
# ---------------------------------------------------------------------------
def _rsi(close, period=14):
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1 / period, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / period, adjust=False).mean()
    rs = roll_up / roll_down
    return 100 - 100 / (1 + rs)


def _macd(close):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal


def _stochastic_k(high, low, close, period=14):
    low_n = low.rolling(period).min()
    high_n = high.rolling(period).max()
    return 100 * (close - low_n) / (high_n - low_n)


def _cci(high, low, close, period=20):
    tp = (high + low + close) / 3
    sma = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - sma) / (0.015 * mad)


def _williams_r(high, low, close, period=14):
    high_n = high.rolling(period).max()
    low_n = low.rolling(period).min()
    return -100 * (high_n - close) / (high_n - low_n)


def _vote_value(score):
    """Map an average vote in [-1, 1] to a TradingView-style label."""
    if score >= 0.5:
        return "Strong Buy"
    if score >= 0.1:
        return "Buy"
    if score > -0.1:
        return "Neutral"
    if score > -0.5:
        return "Sell"
    return "Strong Sell"


def compute_rating(df):
    """Compute a technical rating from an OHLC(V) price DataFrame (oldest->newest).

    Returns a dict of rating fields, or None if there isn't enough data.
    Only indicators that evaluate to a real number vote, so short histories
    (where e.g. the 200-day average is undefined) still produce a sensible
    rating from whatever is available.
    """
    if df is None or len(df) < 20:
        return None
    close, high, low = df["Close"], df["High"], df["Low"]
    last = close.iloc[-1]
    if pd.isna(last):
        return None

    def vote(buy, sell):
        return 1 if buy else (-1 if sell else 0)

    # --- Moving averages: price above = buy, below = sell ---
    ma_votes = []
    for n in MA_PERIODS:
        for ma in (close.rolling(n).mean().iloc[-1],
                   close.ewm(span=n, adjust=False).mean().iloc[-1]):
            if pd.notna(ma):
                ma_votes.append(vote(last > ma, last < ma))

    # --- Oscillators ---
    osc_votes = []
    rsi = _rsi(close).iloc[-1]
    if pd.notna(rsi):
        osc_votes.append(vote(rsi < 30, rsi > 70))
    macd, signal = _macd(close)
    if pd.notna(macd.iloc[-1]) and pd.notna(signal.iloc[-1]):
        osc_votes.append(vote(macd.iloc[-1] > signal.iloc[-1], macd.iloc[-1] < signal.iloc[-1]))
    k = _stochastic_k(high, low, close).iloc[-1]
    if pd.notna(k):
        osc_votes.append(vote(k < 20, k > 80))
    cci = _cci(high, low, close).iloc[-1]
    if pd.notna(cci):
        osc_votes.append(vote(cci < -100, cci > 100))
    wr = _williams_r(high, low, close).iloc[-1]
    if pd.notna(wr):
        osc_votes.append(vote(wr < -80, wr > -20))
    mom = (close - close.shift(10)).iloc[-1]
    if pd.notna(mom):
        osc_votes.append(vote(mom > 0, mom < 0))

    all_votes = ma_votes + osc_votes
    if not all_votes:
        return None

    ma_buy = sum(1 for v in ma_votes if v > 0)
    ma_sell = sum(1 for v in ma_votes if v < 0)
    osc_buy = sum(1 for v in osc_votes if v > 0)
    osc_sell = sum(1 for v in osc_votes if v < 0)

    score = sum(all_votes) / len(all_votes)            # -1 .. 1
    return {
        "technical_rating": _vote_value(score),
        "technical_score": round((score + 1) * 50, 1),  # 0 .. 100 (for sorting)
        "ma_buy": ma_buy,
        "ma_sell": ma_sell,
        "osc_buy": osc_buy,
        "osc_sell": osc_sell,
        "rsi": round(float(rsi), 1) if pd.notna(rsi) else np.nan,
        "last_close": round(float(last), 2),
    }


# ---------------------------------------------------------------------------
# Download + analyze
# ---------------------------------------------------------------------------
def analyze_ticker(ticker, category=None, period="1y"):
    safe = ticker.replace(".", "_")
    try:
        df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
        if df is None or df.empty:
            print(f"  [WARN] No price data for {ticker}")
            return None
        df.to_csv(PRICES_DIR / f"{safe}.csv")  # raw data, in its own folder

        rating = compute_rating(df)
        if rating is None:
            print(f"  [WARN] Not enough data to rate {ticker}")
            return None
        rating["ticker"] = ticker
        rating["category"] = category
        print(f"  \u2713 {ticker}: {rating['technical_rating']} ({rating['technical_score']})")
        return rating
    except Exception as e:
        print(f"  \u2717 {ticker} failed: {e}")
        return None


def main():
    print("=" * 80)
    print("TECHNICAL ANALYSIS")
    print("=" * 80)

    if not UNIVERSE_PATH.exists():
        print(f"[ERROR] Universe not found at {UNIVERSE_PATH}.")
        print("Run the quality pipeline first:  bash run_quality.sh")
        return

    universe = pd.read_csv(UNIVERSE_PATH)
    # De-duplicate tickers that appear in more than one sector.
    universe = universe.drop_duplicates(subset="ticker", keep="first")
    print(f"\nAnalyzing {len(universe)} companies...\n")

    rows = []
    for idx, row in universe.iterrows():
        ticker = row["ticker"]
        category = row.get("category")
        print(f"[{idx+1}/{len(universe)}] {ticker} ({category})...")
        result = analyze_ticker(ticker, category=category)
        if result:
            rows.append(result)
        time.sleep(0.4)  # be gentle with Yahoo

    if not rows:
        print("\n[ERROR] No technical ratings produced.")
        return

    cols = ["ticker", "category", "technical_rating", "technical_score",
            "ma_buy", "ma_sell", "osc_buy", "osc_sell", "rsi", "last_close"]
    df = pd.DataFrame(rows)[cols]
    df = df.sort_values("technical_score", ascending=False)
    df.to_csv(OUTPUT_PATH, index=False)

    print("\n" + "=" * 80)
    print("TECHNICAL SUMMARY")
    print("=" * 80)
    print(f"Rated: {len(df)} companies")
    print(df["technical_rating"].value_counts().to_string())
    print(f"\nRaw prices: {PRICES_DIR}/")
    print(f"Ratings:    {OUTPUT_PATH}")
    print("=" * 80)


if __name__ == "__main__":
    main()
