# market-advisor — working agreement

An evolving US-equity screening assistant. Read `docs/agent.md` (what the
assistant does) and `docs/progress.md` (where we are) before starting work.
`README.md` describes the pipelines and the scoring methodology.

## Environment
- devenv Docker container, project at /repo. Internet access is available.
- Python deps live in /repo/.venv. Run ANY python or pipeline command through
  the wrapper: `prun <cmd>` (e.g. `prun python3 scripts/freshness.py`,
  `prun bash run_technical.sh`). Create/update the venv with `pysetup`.
- The Streamlit GUI is published on 127.0.0.1:8501 of my host. Start it only
  when I ask; it blocks the terminal, so run it in the background and tell me
  the URL.
- Never `pip install` into the system python; only into the venv via prun/pysetup.

## Pipelines (details in README.md)
- `run_quality.sh` builds the universe and MUST run before the others.
- `run_technical.sh` (daily prices) and `run_valuation.sh` (quarterly + spot)
  are independent of each other.
- All of them make one network call per company and take minutes. Before
  running any of them: tell me what will be refreshed and why, and wait for my
  go-ahead. Run them in the background and report progress rather than blocking.
- Yahoo throttling shows up as NoneType/empty-data errors: stop, report, and
  suggest retrying later or `prun pip install -U yfinance curl_cffi`. Do not
  silently retry in a loop.

## Data handling rules
- `data/` is generated and git-ignored. Never commit it, never hand-edit it.
- EVERY figure you report carries its as-of date and source pipeline. A number
  without a date is not an answer.
- Start any analysis by checking freshness (`scripts/freshness.py` once it
  exists). If something needed is stale, say so and ask before refreshing.
- Scores are pool-wide percentiles: changing `companies_per_sector` or the USD
  filter recalibrates everyone. Never compare scores across runs with different
  pool sizes without saying so.
- Blank ratios are meaningful (loss-makers, missing data). Never fill them in
  with estimates.

## Analysis and reports
- Reports go to `reports/YYYY-MM-DD-<topic>.md`, with a data-as-of line at the top.
- Separate clearly: what the data says / what it might mean / what is uncertain.
- This is decision support, not investment advice, and I am the one deciding.
  Give the reasoning and the counter-case, not a verdict. Flag when a cheap name
  looks like a value trap, when a sample is too small, or when a metric is being
  distorted.
- For news: use WebFetch/WebSearch, prefer primary sources (company IR, SEC,
  exchange notices) over aggregators, and always cite source + date. If you
  cannot verify something, say so instead of summarising rumour.

## Changing the methodology
- Metric/weight changes affect every past score: propose them in
  `docs/agent.md` (Proposed changes) with rationale and expected effect first,
  and wait for my decision. Never change `config.json` weights on your own.
- Keep pipelines independent; don't add cross-dependencies beyond the universe.

## Workflow
- One task at a time; stop with a short summary when it's done.
- Keep `docs/progress.md` current: what was done, data state, open questions,
  next step. Update it at the end of a task and when I end a session.
- Python: standard library + what's already in requirements.txt; ask before
  adding a dependency. Keep new helper scripts in `scripts/`.
