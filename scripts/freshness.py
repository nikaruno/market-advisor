#!/usr/bin/env python3
"""One-glance data-state table for the three pipelines.

Inspects data/ and reports, per dataset: file count, row count (single-file
datasets), newest/oldest file timestamps, age in days, and a verdict against
the refresh cadences in docs/agent.md:

    quality    stale when > 90 days
    valuation  stale when > 14 days
    technical  stale when >  3 days

Works when data/ does not exist yet (everything reports MISSING).
Stdlib only. Run via the wrapper: prun python3 scripts/freshness.py
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"

# Cadences from docs/agent.md ("Stale when"), in days.
STALE_AFTER = {"quality": 90, "valuation": 14, "technical": 3}


@dataclass
class Dataset:
    """A named piece of pipeline output: one file, or a glob of many."""

    pipeline: str
    name: str
    path: str                 # relative to data/
    pattern: str | None = None  # set => `path` is a directory of matching files
    rows: bool = False          # count CSV data rows (single-file datasets)


DATASETS: list[Dataset] = [
    # QUALITY — builds the universe, must run first.
    Dataset("quality", "universe", "fundamentals_raw.csv", rows=True),
    Dataset("quality", "annual statements", "fundamentals/raw", pattern="*.csv"),
    Dataset("quality", "company metrics", "fundamentals/company_metrics.csv", rows=True),
    Dataset("quality", "quality scores", "fundamentals/absolute_scores.csv", rows=True),
    # TECHNICAL — daily prices.
    Dataset("technical", "daily prices", "technical/prices", pattern="*.csv"),
    Dataset("technical", "technical ratings", "technical/technical_analysis.csv", rows=True),
    # VALUATION — quarterly statements + spot price.
    Dataset("valuation", "quarterly statements", "valuation/raw", pattern="*.csv"),
    Dataset("valuation", "valuation ratios", "valuation/valuation.csv", rows=True),
]


@dataclass
class Result:
    ds: Dataset
    files: int = 0
    rows: int | None = None
    newest: float | None = None
    oldest: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def age_days(self) -> float | None:
        if self.newest is None:
            return None
        return (datetime.now(timezone.utc).timestamp() - self.newest) / 86400.0

    @property
    def verdict(self) -> str:
        if self.files == 0:
            return "MISSING"
        age = self.age_days
        if age is None:
            return "MISSING"
        return "STALE" if age > STALE_AFTER[self.ds.pipeline] else "FRESH"


def count_rows(path: Path) -> int | None:
    """Data rows in a CSV (total lines minus the header)."""
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            n = sum(1 for _ in fh)
    except OSError:
        return None
    return max(n - 1, 0)


def inspect(ds: Dataset) -> Result:
    res = Result(ds)
    target = DATA / ds.path

    if ds.pattern:
        if not target.is_dir():
            return res
        files = sorted(p for p in target.glob(ds.pattern) if p.is_file())
    else:
        files = [target] if target.is_file() else []

    if not files:
        return res

    mtimes = []
    for p in files:
        try:
            mtimes.append(p.stat().st_mtime)
        except OSError:
            res.notes.append(f"unreadable: {p.name}")
    if not mtimes:
        return res

    res.files = len(mtimes)
    res.newest = max(mtimes)
    res.oldest = min(mtimes)

    if ds.rows:
        res.rows = count_rows(files[0])
        if res.rows == 0:
            res.notes.append("no data rows")

    return res


def fmt_ts(ts: float | None) -> str:
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def fmt_age(age: float | None) -> str:
    if age is None:
        return "—"
    return f"{age:.1f}"


def render(results: list[Result]) -> str:
    headers = ["Pipeline", "Dataset", "Files", "Rows", "Newest", "Oldest", "Age (d)", "Verdict"]
    rows: list[list[str]] = []
    for r in results:
        rows.append([
            r.ds.pipeline,
            r.ds.name,
            str(r.files) if r.files else "—",
            "—" if r.rows is None else str(r.rows),
            fmt_ts(r.newest),
            fmt_ts(r.oldest),
            fmt_age(r.age_days),
            r.verdict,
        ])

    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(headers)]
    sep = "-+-".join("-" * w for w in widths)
    out = [
        " | ".join(h.ljust(w) for h, w in zip(headers, widths)),
        sep,
    ]
    prev = None
    for r, row in zip(results, rows):
        if prev is not None and r.ds.pipeline != prev:
            out.append(sep)
        prev = r.ds.pipeline
        out.append(" | ".join(c.ljust(w) for c, w in zip(row, widths)))
    return "\n".join(out)


def main() -> int:
    global DATA

    ap = argparse.ArgumentParser(description="Report the freshness of the pipeline data.")
    ap.add_argument("--data-dir", default=str(DATA), help="override the data/ directory")
    args = ap.parse_args()
    DATA = Path(args.data_dir).resolve()

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"Data freshness as of {now} (local)  —  {DATA}")
    print(
        "Cadence (docs/agent.md): "
        + ", ".join(f"{k} > {v}d = STALE" for k, v in STALE_AFTER.items())
    )
    print()

    if not DATA.exists():
        print("data/ does not exist — no pipeline has been run in this checkout.")
        print()

    results = [inspect(ds) for ds in DATASETS]
    print(render(results))

    notes = [(r.ds.name, n) for r in results for n in r.notes]
    if notes:
        print()
        for name, n in notes:
            print(f"note: {name}: {n}")

    print()
    missing = {r.ds.pipeline for r in results if r.verdict == "MISSING"}
    stale = {r.ds.pipeline for r in results if r.verdict == "STALE"}
    if missing:
        line = "MISSING: " + ", ".join(sorted(missing))
        if "quality" in missing:
            line += "  — run_quality.sh builds the universe and must run first."
        print(line)
    if stale:
        print("STALE:   " + ", ".join(sorted(stale)))
    if not missing and not stale:
        print("All datasets are within their refresh cadence.")

    # Exit code: 0 all fresh, 1 something stale, 2 something missing.
    return 2 if missing else (1 if stale else 0)


if __name__ == "__main__":
    sys.exit(main())
