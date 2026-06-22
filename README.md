# US Equity Screener — Quality + Technical

A small, self-contained tool that screens **US-listed, USD-reporting companies**
on three independent dimensions:

- **Quality** — the strength of a company's annual business fundamentals,
  expressed as a multi-metric 0–100 score.
- **Technical** — a TradingView-style price rating (Strong Buy … Strong Sell)
  from a vote of moving averages and oscillators.
- **Valuation** — trailing P/E, P/B, and EV/EBITDA (all TTM / latest-quarter),
  ranked cheapest-first by EV/EBITDA, plus a forward P/E for context.

Each lives in its own **standalone pipeline** with its own data folder and its
own refresh cadence, and the Streamlit GUI shows them in separate tabs. They are
deliberately decoupled: quality is judged on yearly statements (run rarely),
technical on daily prices, valuation on quarterly statements + the live price.

**The quality pipeline builds the company universe, so it must run first.** The
technical and valuation pipelines read that universe to know which tickers to
analyze.

---

## What the quality score measures

Quality is a 0–100 score built from six metrics, weighted as follows:

| Metric | Weight | Definition |
|---|---|---|
| ROIC | 25% | NOPAT ÷ invested capital |
| FCF Margin | 20% | (operating cash flow − capex) ÷ revenue |
| Cash Quality | 15% | operating cash flow ÷ net income |
| Leverage | 15% | net debt ÷ EBITDA *(lower is better)* |
| EBITDA Growth | 15% | EBITDA CAGR over the available years |
| Revenue Growth | 10% | revenue CAGR over the available years |

A few design choices worth knowing:

- **Quality and valuation are kept separate.** A great business at a rich price
  still scores high on quality; price is judged elsewhere.
- **Recent years weighted more.** ROIC, FCF, Cash Quality, and Leverage are
  exponentially-weighted across up to four annual periods (most recent ≈ 46%).
- **Absolute (pool-wide) scoring.** Each metric is converted to a percentile
  rank across the *entire* universe, not within its sector. Consequence:
  changing the universe size (e.g. `companies_per_sector`) recalibrates
  everyone's percentiles, so scores aren't comparable across runs of different
  pool sizes.
- **EBITDA over net income** for the growth metric (less distorted by tax timing
  and one-off items); net income's earnings-quality signal is preserved via
  Cash Quality (CFO ÷ NI).
- **Missing metrics** are handled by redistributing weight across the metrics a
  company does have; extreme outliers are capped at the 5th/95th percentiles.

Companies are placed into tiers by percentile: **Top 25% / Top 50% / Bottom 50%
/ Bottom 25%**.

## What the technical rating measures

The technical rating mirrors TradingView's "Technical Rating" summary. For each
company, ~1 year of daily prices is scored by a set of signals, each voting
**Buy (+1) / Neutral (0) / Sell (−1)**:

- **Moving averages** (price vs. SMA and EMA at 10/20/50/100/200 days): price
  above the average votes Buy, below votes Sell.
- **Oscillators**: RSI(14), MACD vs. signal, Stochastic %K, CCI(20), Williams %R,
  and 10-day Momentum, each with its standard overbought/oversold rule.

The average vote (−1…+1) maps to a label: **Strong Buy ≥ 0.5, Buy ≥ 0.1, Neutral
between ±0.1, Sell ≤ −0.1, Strong Sell ≤ −0.5**. The table also reports a 0–100
`technical_score` (for sorting), the Buy/Sell split for moving averages vs.
oscillators, and the latest RSI. Indicators are computed in pandas/numpy — no
extra dependencies — and only signals that evaluate to a real number vote, so
short price histories still produce a sensible rating.

> Technical signals are momentum/trend indicators, not fundamental judgments —
> read them alongside the quality score, not instead of it.

## What the valuation tab shows

Three trailing ratios, all on a **TTM / most-recent-quarter** basis so they
reflect the latest reported quarter rather than a stale fiscal year-end:

- **EV/EBITDA** = (market cap + latest-quarter debt − latest-quarter cash) ÷ TTM
  EBITDA. **This is the ranking metric** (cheapest first). It captures leverage
  and is less distorted by one-off items than P/E.
- **P/E** = market cap ÷ TTM net income.
- **P/B** = market cap ÷ latest-quarter equity.
- **Forward P/E** — yfinance's analyst forward (next-twelve-month) estimate.
  Display-only and *not* TTM; coverage varies and it moves as analysts revise. A
  forward well below trailing P/E implies expected earnings growth.

Each trailing ratio carries a **basis flag** so its provenance is always visible:
`ttm` means it was summed/taken from the quarterly statements downloaded here;
`info` means it came from yfinance's prepackaged trailing field (still TTM, just
less transparent). A ratio is left blank rather than guessed when neither source
is usable — so pure loss-makers correctly get no P/E or EV/EBITDA.

There is deliberately **no composite "value score."** Averaging valuation ratios
across different scales is fragile, and a pure cheapness ranking is a value-trap
magnet, so the tab simply ranks by EV/EBITDA and shows the rest.

> Cheap *and* high-quality (read the Quality tab next to this one) is the
> interesting combination; cheap alone often means cheap for a reason.

## Why USD-only

The universe is filtered to companies whose **financial statements are reported
in US dollars**. US-listed foreign issuers (ADRs such as TSM, ASML, SAP) trade
in USD but report their statements in their home currency (TWD, EUR, …). Mixing
a USD figure with a non-USD statement figure silently corrupts any ratio — for a
TWD reporter this throws metrics off by ~30×. Filtering on reporting currency
(rather than ticker format or country) removes exactly those names while keeping
USD-reporting foreign issuers like ARM, whose numbers are correct. The filter is
controlled by `usd_only` in `config.json` (default `true`).

---

## Project structure

```
.
├── README.md
├── requirements.txt
├── config.json              # companies_per_sector, usd_only, weights, active_sectors
├── sectors.json             # sector name -> companiesmarketcap.com URL (USA scraped)
├── run_quality.sh           # runs the full annual quality pipeline (steps 1–4)
├── run_technical.sh         # runs the technical pipeline (needs quality first)
├── run_valuation.sh         # runs the valuation pipeline (needs quality first)
├── run_quality_gui.sh       # launches the GUI (Quality + Technical + Valuation + Company Lookup)
├── src/screener/
│   ├── scrape_fundamentals.py      # 1. build the USD-only universe
│   ├── download_annual.py          # 2. download annual statements
│   ├── compute_detailed_metrics.py # 3. compute the six quality metrics
│   ├── absolute_scores.py          # 4. percentile-rank into a 0–100 quality score
│   ├── technical_analysis.py       # technical: download prices + rate
│   └── valuation_analysis.py       # valuation: download quarterly + TTM ratios
└── gui/
    └── quality_app.py              # Streamlit: Quality + Technical + Valuation + Company Lookup
```

### Pipeline data flow

```
QUALITY (run first — builds the universe):
  scrape_fundamentals.py   → data/fundamentals_raw.csv                 (universe, USD-filtered)
  download_annual.py       → data/fundamentals/raw/<TICKER>_*.csv      (income / balance / cashflow + meta)
  compute_detailed_metrics → data/fundamentals/company_metrics.csv     (six metrics per company)
  absolute_scores.py       → data/fundamentals/absolute_scores.csv     (quality score + tiers)  ← Quality tab

TECHNICAL (run anytime after quality):
  technical_analysis.py    → data/technical/prices/<TICKER>.csv        (raw daily OHLCV)
                           → data/technical/technical_analysis.csv     (rating per company)      ← Technical tab

VALUATION (run anytime after quality):
  valuation_analysis.py    → data/valuation/raw/<TICKER>_*_q.csv       (raw quarterly statements)
                           → data/valuation/valuation.csv              (TTM ratios + EV/EBITDA rank)  ← Valuation tab
```

The `data/` folder is generated by the pipelines and is git-ignored. Each
pipeline writes to its own subfolder (`fundamentals/`, `technical/`, `valuation/`).

---

## Setup & run

Requires **Python 3.10+** and internet access (Yahoo Finance + companiesmarketcap.com).

**1) Install dependencies** (one-time). A virtual environment keeps things isolated:

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

On Windows (PowerShell), activate with `.venv\Scripts\Activate.ps1` instead of `source`.

**2) Build the quality data and score the universe.** This scrapes the sector
lists, downloads annual statements, computes the metrics, and writes the scores.
**Run this first** — it builds the company universe everything else depends on.
It makes one network call per company, so expect a few minutes:

```bash
bash run_quality.sh
```

**3) (Optional) Run the technical analysis.** Downloads ~1 year of daily prices
for the same universe and computes the rating. Re-run this whenever you want a
fresh price read — independently of the quality pipeline:

```bash
bash run_technical.sh
```

**4) (Optional) Run the valuation analysis.** Downloads quarterly statements +
spot market cap and computes the TTM ratios, ranked by EV/EBITDA. Also
independent of the others:

```bash
bash run_valuation.sh
```

**5) View the results** in your browser at <http://localhost:8501>:

```bash
bash run_quality_gui.sh
```

The GUI has four tabs. **Quality** shows the ranked fundamental table (score,
tier, ROIC, FCF, Cash Quality, Leverage, EBITDA/Revenue growth, data
completeness). **Technical** shows the price rating per company (rating, score,
MA/oscillator vote split, RSI, last close). **Valuation** shows the trailing
ratios ranked cheapest-first by EV/EBITDA (with P/E, forward P/E, P/B, market
cap, and the EV/EBITDA basis flag). **Company Lookup** lets you pick a single
company to see its price history and how it stacks up against its sector peers —
quality score, technical rating, EV/EBITDA, forward P/E, and market cap side by
side (the cross-pipeline view). Each tab works on its own; if you haven't run a
pipeline yet, its tab just prompts you to.

> You only need step 1 (install) once per machine. Re-run step 2 for fresh annual
> data, steps 3–4 for fresh prices/ratios; step 5 can be left running and
> refreshed in the browser.

---

## Configuration

**`config.json`**

| Key | Meaning |
|---|---|
| `companies_per_sector` | How many top companies to scrape per sector (default `10`; raise for a larger universe). |
| `usd_only` | If `true`, drop companies that don't report in USD (recommended). |
| `weights` | The six metric weights (must roughly sum to 1.0; auto-normalized if not). |
| `active_sectors` | Informational list of the sectors in use. |

**`sectors.json`** maps each sector to its exact companiesmarketcap.com page URL.
To add a sector, add an entry with the exact page URL under a `url` key — the
site's slugs are inconsistent, so copy the URL from a browser rather than
guessing it.

---

## Notes & gotchas

- **Run cadence.** Annual statements update roughly once a year per company, so
  there's little reason to re-run the pipeline more often than quarterly.
- **Yahoo rate limits.** A `NoneType ... not subscriptable` or empty-data error
  usually means Yahoo throttled you (common during long runs) or `yfinance` is
  out of date. Wait a bit, or `pip install -U yfinance curl_cffi`.
- **Pool-wide scoring.** Because scores are percentile ranks across the whole
  universe, changing `companies_per_sector` or the USD filter will shift every
  company's score on the next run. That's expected, not a bug.
- **Tickers with dots** (e.g. `BRK.B`) are stored on disk with the dot replaced
  by an underscore; the code resolves both forms automatically.
