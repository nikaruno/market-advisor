# The assistant role

market-advisor is not a finished tool; it is an evolving screening assistant.
The pipelines produce data; the assistant turns it into answers.

## Responsibilities

1. **Data freshness.** Know what data exists, how old it is, and whether it is
   fit for the question being asked. Refresh cadence (starting point, adjust
   as we learn):
   | Dataset | Typical cadence | Stale when |
   |---|---|---|
   | quality (annual statements + universe) | quarterly | > 90 days |
   | valuation (quarterly + spot price) | weekly, or after earnings | > 14 days |
   | technical (daily prices) | on demand | > 3 days |
   Report staleness before analysing; refresh only after asking.

2. **Analysis and reports.** Ranked tables, cross-pipeline views (cheap AND
   high quality), what changed since the last run, why a company moved, sector
   comparisons. Written to `reports/`, with data-as-of dates.

3. **Company context.** For a name under discussion: recent news, earnings
   dates and results, notable filings — from primary sources, cited and dated.
   Kept short, and separate from the quantitative view.

4. **Methodology improvements.** Suggest better/additional metrics, spot
   distortions in the existing ones, propose weight changes — always as a
   proposal with rationale and expected effect, never applied unilaterally.

## Working notes
- Percentile scores are pool-wide: cross-run comparisons need the same pool size.
- Technical signals are momentum, not fundamentals; never present them as a
  quality judgement.
- Forward P/E is analyst-sourced and moves; label it as such.
- ADR/foreign issuers: only USD reporters are in the universe by design.

## Proposed changes (pending my decision)
_(Claude appends proposals here: what, why, expected effect, how to verify.)_

### P1 — Rank valuation on Normalized EBITDA (2026-09-27, pending)
- **What:** in `valuation_analysis.py`, change `EBITDA_KEYS` from
  `["EBITDA", "Normalized EBITDA"]` to `["Normalized EBITDA", "EBITDA"]`, and
  add a column with the reported-basis EV/EBITDA plus a flag when the two
  differ by >10%.
- **Why:** Yahoo's reported EBITDA includes unusual items, mostly gains on
  equity securities. On 2026-09-26 data, 9 of 117 companies have reported TTM
  EBITDA >10% above normalized. GOOG: $327B reported vs $178B normalized
  (~$149B of securities gains), so its EV/EBITDA shows 12.9 when the operating
  figure is 23.8. CRM: 13.6 vs 17.3; Salesforce's own Q2 FY27 release
  attributes $2.43 of its $4.29 GAAP EPS to strategic-investment gains.
- **Expected effect:** GOOG drops from #3 to #10 among Top-25% quality names;
  META enters the top 5. Names with one-off *charges* get slightly cheaper
  (INTU 10.9 → 10.4). There is no effect on quality scores.
- **Related, not included:** the quality pipeline's EBITDA CAGR has the same
  issue (GOOG annual EBITDA $180.7B vs $156.5B normalized), and P/E is on
  reported net income, which carries the same gains. Both are worth a separate
  decision.
- **How to verify:** re-run `run_valuation.sh` and compare against
  `reports/2026-09-27-cheap-and-high-quality.html`, which already computes
  both bases side by side.

### P2 — Subtract short-term investments in EV (2026-09-27, pending)
- **What:** in `valuation_analysis.py`, reorder `CASH_KEYS` so that
  "Cash Cash Equivalents And Short Term Investments" comes before
  "Cash And Cash Equivalents".
- **Why:** EV currently subtracts cash only, so short-term investments count
  as if they were operating value. On 2026-09-26 data, 35 companies hold more
  than $1B that is left out: GOOG $187B, META $75B, MSFT $56B, NVDA $40B,
  AAPL $23B. Found when the ADBE deep-dive read "EV − market cap" as $2.4B of
  net debt; with short-term investments included it is $1.1B.
- **Expected effect:** lower EV/EBITDA for cash-rich names, with the largest
  moves among mega-caps. The top-5 ranking could shift (META would get
  cheaper). The 2026-09-27 report's normalized EV/EBITDA has the same issue.
  This is independent of P1, but best decided together because both change
  the ranking.
- **How to verify:** re-run `run_valuation.sh`, then diff `valuation.csv`
  EV/EBITDA before and after for the 35 names.

## Roadmap ideas (not scheduled)
- `scripts/freshness.py`: one-glance data-state table (Phase 1).
- Run history: snapshot key outputs per run so "what changed" is answerable.
- Watchlist of tickers to follow more closely.
- Earnings calendar awareness (refresh valuation after a company reports).
- Sector-relative scoring as an alternative view to pool-wide percentiles.
- Backtest sanity: do high-quality/cheap cohorts behave differently over time?
- Extra sources beyond Yahoo (SEC XBRL for statements, Nasdaq for calendars).
