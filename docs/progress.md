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

## Data state (as of 2026-10-19)
- **quality** FRESH, not refreshed — still 2026-09-24 13:01, 25.0 days old
  against a 90-day cadence. Next due ~2026-12-23.
- **technical** FRESH, rated 2026-10-19 11:58, **133 of 133**. Last week's five
  timeouts (RKLB, ESLT, ASTS, WWD, GSAT) all recovered, so the partial-coverage
  gap noted on 10-12 is closed and daily prices now show newest = oldest.
- **valuation** FRESH but not refreshed — still 2026-10-12 06:26, 7.2 days old
  against a 14-day cadence.
- Universe tape deteriorated sharply: Strong Sell 24 → 43, Strong Buy 43 → 20
  (133 rated). 20 of the 33 top-quartile names now rate Sell or Strong Sell.

## Previous data state (2026-10-12)
- **quality** FRESH but **not refreshed today** — still the 2026-09-24 13:01
  run, 17.7 days old against a 90-day cadence. Next due ~2026-12-23.
- **technical** FRESH, rated 2026-10-12 06:18, **128 of 133**. Five timed out
  (`curl: (28)`): RKLB, ESLT, ASTS, WWD, GSAT — all defense/space, none in the
  Top 25%. Their stale 2026-09-24 price files remain on disk, so the daily-prices
  row shows newest 10-12 / oldest 09-24. The FRESH verdict reads the newest file
  and so slightly overstates coverage — a real limitation of the script worth
  considering (an `--oldest` or per-dataset coverage check would catch it).
- **valuation** FRESH, computed 2026-10-12 06:26. 133 rows, no failures.
- Universe-wide technical split moved from 41/24/10/16/42 (SB/B/N/S/SS) on
  09-24 to 43/22/6/33/24 on 10-12: Strong Sell fell from 42 to 24.

## Previous data state (2026-09-24)
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
- `reports/2026-10-19-cheap-and-high-quality.md` — momentum update; only
  technical was refreshed, so the EV/EBITDA ranking is identical to 10-12.
  **Key finding: the technical ratings whipsaw at weekly sampling.** GOOG has
  printed a different rating at all three readings (Sell → Strong Buy → Strong
  Sell) on under 1% cumulative price movement; GRMN went Strong Buy → Sell →
  Strong Buy. The mechanism is the MA vote: when price sits near its averages a
  small move flips several of the ten votes at once. This supersedes the 09-24
  "cheapness and momentum are inversely aligned" finding, which should not have
  been framed as a finding on one sample.
- `reports/2026-10-12-cheap-and-high-quality.md` — today's run of the default
  task. Same ten cheapest top-quartile names as 09-24, reordered.
  **Key finding: the 09-24 "cheapness and momentum are inversely aligned"
  pattern did not hold.** GOOG went Sell → Strong Buy, ADBE/INTU recovered off
  their lows, GRMN and QCOM fell out of Strong Buy. 18 days is too short to call
  either state a regime; the earlier pattern was a clean snapshot, not a
  structural relationship. Two prior flags resolved: QCOM's momentum/fundamental
  divergence closed downward (−11%, Strong Buy → Sell), META's RSI 77 normalised
  to 57 on a −3.4% move. Both are single observations, not a validated method.
- `reports/2026-09-24-cheap-and-high-quality.md` — the 33 Top-25% quality names
  ranked by EV/EBITDA, ten cheapest covered with intro + counter-case.
  Regenerated 13:26 with technical ratings folded in. Key finding: cheapness
  and momentum are inversely aligned — the 3 cheapest (ADBE, INTU, GOOG) are
  all Sell/Strong Sell, while 4 of the 5 most expensive are Strong Buy.
  ADBE and INTU are below all 10 moving averages.

## Git state (as of 2026-10-19)
`main` is at `6dbe8ad`, two commits ahead of its upstream (not pushed).
`docs/progress.md` is uncommitted. Reports are git-ignored (`reports/*.md`)
and live only in the working copy, so commit messages reference findings git
does not contain.
- `reports/2026-09-24-cheap-and-high-quality.md` — **git-ignored**
  (`.gitignore` has `reports/*.md`), so reports live only in the working copy.
`data/` is git-ignored by design and is not part of any commit.

## Next step
Open. All three pipelines fresh; nothing is blocked. The default-task routine is
in `docs/default-task.md` and was executed end to end on 2026-10-12.

## Open questions
- **Valuation cadence vs. the EV/EBITDA ranking (needs a decision).** The
  14-day valuation cadence was set for quarterly-statement staleness, but half
  of EV/EBITDA is a spot market cap that goes stale as fast as the technical
  data. On 10-19 the report ranked on week-old multiples while momentum was
  current; INTU had moved +7.4%, ADP +6.7%, GRMN +6.1% since the snapshot. For
  reports that rank on a price-derived metric, valuation and technical should
  arguably refresh together. Raised, not changed — belongs in docs/agent.md.
- **Momentum sampling interval (possible methodology proposal).** Weekly
  readings of the technical rating are dominated by noise; a longer interval or
  a persistence filter would be needed before the label carries information.
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
