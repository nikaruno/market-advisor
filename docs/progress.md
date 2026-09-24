# Progress

## Current state
Phase 1 done: `scripts/freshness.py`. Quality and valuation pipelines have both
run at `companies_per_sector: 25`. First report written.

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

## Data state (all as of 2026-09-24)
- **quality** FRESH, scored 13:01. `companies_per_sector: 25` → 157 universe
  rows / 133 unique / **128 scored**. 125 of 128 at 100% metric completeness.
  Dropped: SPCX, HONA, BETA (2 yrs, need 3), FRMI (1 yr), UPST (missing data).
  157→133 is cross-sector overlap; 151→128 at scoring is pure dedup.
- **valuation** FRESH, computed 13:14. 133 rows, 265 quarterly files, no warnings.
- **technical** FRESH, rated 13:24. 133/133 companies, 133 price files, no
  warnings. Universe-wide split: 41 Strong Buy / 24 Buy / 10 Neutral /
  16 Sell / 42 Strong Sell.
- `freshness.py` reports all three pipelines FRESH for the first time (exit 0).

## Reports
- `reports/2026-09-24-cheap-and-high-quality.md` — the 33 Top-25% quality names
  ranked by EV/EBITDA, ten cheapest covered with intro + counter-case.
  Regenerated 13:26 with technical ratings folded in. Key finding: cheapness
  and momentum are inversely aligned — the 3 cheapest (ADBE, INTU, GOOG) are
  all Sell/Strong Sell, while 4 of the 5 most expensive are Strong Buy.
  ADBE and INTU are below all 10 moving averages.

## Git state (as of 2026-09-24)
Committed as `c7de309` on branch `freshness-script-and-first-runs` (branched
from `main`, not merged): `scripts/freshness.py`, `config.json` (pool 25),
`docs/progress.md`. Uncommitted since that commit:
- `docs/progress.md` — this file, updated after the technical run.
- `reports/2026-09-24-cheap-and-high-quality.md` — **git-ignored**
  (`.gitignore` has `reports/*.md`), so reports live only in the working copy.
`data/` is git-ignored by design and is not part of any commit.

## Next step
Open. All three pipelines are fresh; nothing is blocked.

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
