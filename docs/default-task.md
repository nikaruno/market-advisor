# Default task — refresh check and latest report

The routine to run when asked for "the usual", "the default task", "a fresh
report", or when starting a session with no more specific instruction.

It has a **confirmation gate in the middle**: step 2 ends by asking, and steps
3–5 do not start until the answer comes back. This is deliberate — CLAUDE.md
requires a go-ahead before any pipeline runs, because each one makes a network
call per company and takes minutes. "Default task" means the sequence is
predetermined, not that it runs unattended.

---

## Step 1 — Check freshness (always, no permission needed)

```bash
prun python3 scripts/freshness.py
```

Read-only. Exit code: `0` all fresh, `1` something stale, `2` something
missing. Cadences come from the table in `docs/agent.md`:

| Dataset | Stale when | Pipeline that refreshes it |
|---|---|---|
| quality (annual statements + universe) | > 90 days | `run_quality.sh` |
| valuation (quarterly + spot price) | > 14 days | `run_valuation.sh` |
| technical (daily prices) | > 3 days | `run_technical.sh` |

If exit code is 0, skip to step 5 — the data is fit and no pipeline needs to run.

## Step 2 — Decide, report, and ask

Work out the smallest set of pipelines that makes the data fit for the question
being asked, then tell the user what will be refreshed and why, and **wait**.

Rules for deciding:

- **Only refresh what is stale.** A stale technical dataset does not justify
  re-running quality.
- **`run_quality.sh` must run first if it runs at all** — it rebuilds the
  universe that the other two read.
- **If quality re-runs, technical and valuation become inconsistent with it**
  (the universe may have gained or lost tickers), so plan to re-run both after
  it. Say so when asking.
- **A stale dataset the question does not touch can stay stale.** Say that
  rather than refreshing it for tidiness.
- **If `companies_per_sector` or `usd_only` is about to change**, flag that
  every score recalibrates and past scores stop being comparable. Never change
  the metric weights (CLAUDE.md).

## Step 3 — Run, after the go-ahead

In dependency order, **one at a time, in the background**:

```bash
prun bash run_quality.sh     > "$LOG/quality.log"   2>&1   # only if quality stale/missing
prun bash run_technical.sh   > "$LOG/technical.log" 2>&1
prun bash run_valuation.sh   > "$LOG/valuation.log" 2>&1
```

Technical and valuation are independent of each other, but run them
sequentially anyway: both hammer the same Yahoo endpoints and running them
together invites throttling. Logs go to the scratchpad, not the repo.

Watch each log for progress and for failure, filtering for stage markers plus
`Traceback|NoneType|not subscriptable|Error|WARN`. Do not pipe raw logs — at
~130 companies the per-ticker warnings flood the channel; count them from the
log afterwards instead.

**On Yahoo throttling** (`NoneType ... not subscriptable`, empty data, or a run
of `curl: (28)` timeouts): stop, report, and suggest retrying later or
`prun pip install -U yfinance curl_cffi`. Never retry silently in a loop.

## Step 4 — Confirm the refresh landed

```bash
prun python3 scripts/freshness.py
```

Then reconcile the counts before trusting them. Rows shrink between stages for
two unrelated reasons, and they should be reported separately:

- **universe rows → unique tickers**: cross-sector overlap (a ticker listed in
  two sectors).
- **metrics rows → scored rows**: deduplication in `absolute_scores.py`, which
  keeps the row with the most data.
- **anything else**: genuine exclusions — too few years of statements (3
  required), or missing critical data. Name the tickers.

## Step 5 — Write the report

Path: `reports/YYYY-MM-DD-<topic>.md`, today's date.

Required at the top: a **data-as-of line per pipeline**, with the time and the
pipeline that produced each figure, plus the pool size. Every figure in the body
carries its as-of date and source — a number without a date is not an answer.

Structure: what the data says / what it might mean / what is uncertain, kept
visibly separate. Give the reasoning and the counter-case, never a verdict —
the user decides. Flag explicitly when a cheap name looks like a value trap,
when a sample is too small to carry a conclusion, or when a metric is distorted.

Standing caveats to carry into any report built on this pool:

- Scores are **pool-wide percentiles** over the current pool only; not
  comparable across runs with different pool sizes.
- The Top-25% quality tier is **sector-skewed** toward software and
  semiconductors, so "high quality" partly means "asset-light and high-ROIC".
- Technical ratings are **momentum, not fundamentals**. A Strong Sell is not a
  quality judgement; a Strong Buy does not validate a valuation.
- **Blank ratios are meaningful** (loss-makers, missing data) and stay blank.
- Forward P/E is analyst-sourced, moves, and is not TTM.

Length: 2–3 pages unless asked otherwise. Cover fewer names properly rather
than listing many thinly.

Note `reports/*.md` is **git-ignored**, so a report is never captured by a
commit — it lives in the working copy only.

## Step 6 — Update `docs/progress.md`

What was done, the data state with timestamps, open questions, next step.

---

## Reference: the full sequence from nothing

For a cold checkout with no `data/` directory, after `pysetup`:

```bash
prun python3 scripts/freshness.py     # all MISSING, exit 2
prun bash run_quality.sh              # builds the universe — must be first
prun bash run_technical.sh
prun bash run_valuation.sh
prun python3 scripts/freshness.py     # expect exit 0
```

At `companies_per_sector: 25` this took roughly 25 minutes end to end on
2026-09-24, and produced 128 scored companies from 133 unique tickers.
