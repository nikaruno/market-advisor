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

## Roadmap ideas (not scheduled)
- `scripts/freshness.py`: one-glance data-state table (Phase 1).
- Run history: snapshot key outputs per run so "what changed" is answerable.
- Watchlist of tickers to follow more closely.
- Earnings calendar awareness (refresh valuation after a company reports).
- Sector-relative scoring as an alternative view to pool-wide percentiles.
- Backtest sanity: do high-quality/cheap cohorts behave differently over time?
- Extra sources beyond Yahoo (SEC XBRL for statements, Nasdaq for calendars).
