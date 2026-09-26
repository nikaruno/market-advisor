# Progress

## Current state
Phase 1 done: `scripts/freshness.py`. Project moved to a second PC on
2026-09-26: fresh venv, all three pipelines re-run from scratch at
`companies_per_sector: 25`, GUI verified. The 2026-09-24 report did not carry
over (reports are git-ignored) and needs regenerating if wanted here.

`scripts/freshness.py` inspects `data/` for all three pipelines (8 datasets) and
prints file count, row count, newest/oldest timestamps, age in days, and a
FRESH/STALE/MISSING verdict against the `docs/agent.md` cadences. Stdlib only;
handles a missing `data/`. Exit 0 fresh / 1 stale / 2 missing. `--data-dir`
retargets it. Run: `prun python3 scripts/freshness.py`.

## Environment findings
- Installed **yfinance 1.7.0** (requirements.txt says `>=0.2.40`). The API the
  pipelines use is unchanged and works. requirements.txt NOT modified.
- The pool-5 run hit 9 curl (28) timeouts; the pool-25 and valuation runs hit
  zero. Transient, not a rate-limit wall. Different signature from the
  documented NoneType/empty-data throttling.

## Data state (all as of 2026-09-26, second PC)
- **quality** FRESH, scored 11:58. 158 universe rows / 134 unique /
  **129 scored** (was 157/133/128 on 2026-09-24): one extra name from the
  re-scrape, so **scores are not strictly comparable to the 09-24 run**.
  126 complete, 3 partial. Same 5 dropped (SPCX, HONA, BETA, FRMI, UPST).
  Tiers 33/32/32/32. A divide-by-zero RuntimeWarning fires on NEE in the
  revenue-CAGR line, but its stored revenue_cagr is finite (9.4%); harmless
  but worth a look.
- **valuation** FRESH, computed 12:02. 134 rows, 120 with EV/EBITDA,
  267 quarterly files, no warnings. Median EV/EBITDA 20.2; cheapest EQNR 2.69.
- **technical** FRESH, rated 12:00. 134/134 companies, last bar 2026-09-25
  (Fri close). Split: 42 Strong Buy / 21 Buy / 13 Neutral / 16 Sell /
  42 Strong Sell.
- No throttling or timeouts on any run. Logs in `log/*-2026-09-26.log`.
- GUI: all four tabs render headless (AppTest) with no exceptions; served on
  :8501. Streamlit 1.64 warns `use_container_width` is deprecated (6 uses in
  `gui/quality_app.py`) — works for now, should migrate to `width=`.

### Previous data state (first PC, 2026-09-24)
Quality 157/133/128 scored; valuation 133 rows; technical 133 rated,
41/24/10/16/42.

## Reports
- `reports/2026-09-24-cheap-and-high-quality.md` — the 33 Top-25% quality names
  ranked by EV/EBITDA, ten cheapest covered with intro + counter-case.
  Regenerated 13:26 with technical ratings folded in. Key finding: cheapness
  and momentum are inversely aligned — the 3 cheapest (ADBE, INTU, GOOG) are
  all Sell/Strong Sell, while 4 of the 5 most expensive are Strong Buy.
  ADBE and INTU are below all 10 moving averages.

## Git state (as of 2026-09-26)
`c7de309` and `029dd27` are on `main` (the feature branch was merged).
- `reports/2026-09-24-cheap-and-high-quality.md` — **git-ignored**
  (`.gitignore` has `reports/*.md`), so reports live only in the working copy.
`data/` is git-ignored by design and is not part of any commit.

## Next step
Open. All three pipelines are fresh on the second PC; nothing is blocked.

## Open questions
- Refresh cadences in docs/agent.md are a first guess; tune with experience.
- **The Top-25% quality tier has zero energy/utilities names** (13 software,
  9 semis, 6 electronics, 4 AI, 1 industrial). Pool-wide percentile scoring
  favours asset-light high-ROIC businesses. Sector-relative scoring (already a
  roadmap idea) would address this; worth deciding whether that's wanted.
- SOUN scores 77.5 on quality but has no EV/EBITDA or P/E (negative EBITDA and
  earnings). Small, fast-growing names may be over-rewarded by percentile
  ranking of growth CAGRs off a small base — same concern applies to APP
  (104% EBITDA CAGR, 876 employees). Possible methodology proposal.
- CRM: 8% ROIC against a 70.2 quality score, cash quality 5.31. Worth checking
  whether the score leans on cash-flow metrics GAAP earnings don't support.
- Scores are pool-wide percentiles over these 128 names; not comparable to the
  earlier 22-name run, and they shift whenever the pool changes.
- Age in freshness.py is file mtime (when the pipeline wrote), not the as-of
  date of the market data inside.
