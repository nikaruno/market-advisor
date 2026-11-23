#!/usr/bin/env python3
"""Build a single-company deep-dive HTML report.

Numbers and charts come from data/ (reusing build_report.py's chart code).
The written analysis comes from a notes JSON produced by
scripts/research_company.py (Claude, web research) — every text field in it is
treated as untrusted and HTML-escaped; only **bold** is rendered.

Scenario arithmetic is done here, not by the model: the notes give a
per-share value and a multiple for each case; implied price and the move vs
the last close are computed from the technical pipeline's price data.

Run:  prun python3 scripts/build_company_report.py --ticker ADBE \
        --notes reports/2026-09-27-ADBE-deep-dive.notes.json \
        --out   reports/2026-09-27-ADBE-deep-dive.html
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_report import (CSS, DATA, JS, W, build_table, esc, file_date,  # noqa: E402
                          fundamentals_charts, load_prices, money, num, pct,
                          peer_table, price_chart, rating_chip)
from freshness import DATASETS, inspect  # noqa: E402


def txt(s) -> str:
    """Escape model-written text; allow **bold** only."""
    if s is None:
        return ""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc(str(s)))


def safe_url(u) -> str:
    u = str(u or "")
    return esc(u) if u.startswith(("https://", "http://")) else "#"


def link(src, url) -> str:
    if not url:
        return esc(src or "")
    return f'<a href="{safe_url(url)}" target="_blank" rel="noopener">{esc(src or url)}</a>'


def segment_chart(segs: list[dict], total_rev: float | None) -> str:
    """Horizontal bars, one series: segment revenue, sorted, value at the tip."""
    segs = [s for s in segs if isinstance(s.get("revenue_usd"), (int, float)) and s["revenue_usd"] > 0]
    if not segs:
        return ""
    segs = sorted(segs, key=lambda s: -s["revenue_usd"])
    L, R, row_h, bh = 190, 150, 30, 16
    Hc = row_h * len(segs) + 10
    vmax = max(s["revenue_usd"] for s in segs)
    denom = sum(s["revenue_usd"] for s in segs)
    g = []
    for i, s in enumerate(segs):
        y = 6 + i * row_h
        w = max(s["revenue_usd"] / vmax * (W - L - R), 2)
        r = min(4, w)
        d = (f"M{L},{y}H{L + w - r:.1f}Q{L + w:.1f},{y} {L + w:.1f},{y + r}"
             f"V{y + bh - r}Q{L + w:.1f},{y + bh} {L + w - r:.1f},{y + bh}H{L}Z")
        share = s["revenue_usd"] / denom
        yoy = s.get("yoy_growth")
        yoy_t = pct(yoy, signed=True, digits=0) if isinstance(yoy, (int, float)) else "—"
        tip = {"t": s.get("name", ""), "rows": [["Revenue", money(s["revenue_usd"]), "s1"],
                                               ["Share of listed segments", pct(share, digits=0), ""],
                                               ["YoY", yoy_t, ""]]}
        name = s.get("name", "")
        name = name if len(name) <= 28 else name[:27] + "…"
        g.append(f'<text class="tick" x="{L - 8}" y="{y + 12}" text-anchor="end" style="fill:var(--ink2)">{esc(name)}</text>'
                 f'<path class="bar s1" d="{d}" tabindex="0" data-tip="{esc(json.dumps(tip))}"/>'
                 f'<text class="elabel" x="{L + w + 6:.1f}" y="{y + 12}">{money(s["revenue_usd"])}</text>'
                 f'<text class="tick" x="{L + w + 64:.1f}" y="{y + 12}">{pct(share, digits=0)} · YoY {yoy_t}</text>')
    note = ""
    if total_rev:
        cover = denom / total_rev
        if not 0.9 <= cover <= 1.1:
            note = (f'<p class="note">Listed segments sum to {money(denom)}, {pct(cover, digits=0)} of the '
                    f'latest annual revenue in the data ({money(total_rev)}) — periods or definitions may differ.</p>')
    return (f'<svg class="chart" viewBox="0 0 {W} {Hc}" role="img" aria-label="Revenue by segment">{"".join(g)}</svg>'
            + note)


def scenario_table(sc: dict, last_close: float) -> str:
    items = sc.get("items") or []
    if not items:
        return ""
    rows = []
    for it in items:
        v, m = it.get("per_share_value"), it.get("multiple")
        ok = isinstance(v, (int, float)) and isinstance(m, (int, float)) and v > 0 and m > 0
        price = v * m if ok else None
        move = price / last_close - 1 if ok else None
        cls = "" if move is None else ("pos" if move >= 0 else "neg")
        rows.append(
            f'<tr><th scope="row">{esc(it.get("name", ""))}</th><td>{num(v, 2) if ok else "—"}</td>'
            f'<td>{num(m) + "×" if ok else "—"}</td><td>{"$" + num(price, 0) if ok else "—"}</td>'
            f'<td><span class="{cls}">{pct(move, signed=True, digits=0)}</span></td>'
            f'<td style="text-align:left;white-space:normal">{txt(it.get("rationale"))}</td></tr>')
    base = sc.get("current_value_per_share")
    cur = (f' At the last close of ${num(last_close, 2)}, the stock trades at '
           f'<b>{num(last_close / base)}×</b> {esc(sc.get("metric_label", ""))}.') if isinstance(base, (int, float)) and base > 0 else ""
    return (f'<p>{txt(sc.get("basis_note"))}{cur}</p>'
            f'<div class="tw"><table><thead><tr><th>Case</th><th>{esc(sc.get("metric_label", "Per share"))}</th>'
            f'<th>Multiple</th><th>Implied price</th><th>vs last close</th><th style="text-align:left">Assumptions</th></tr>'
            f'</thead><tbody>{"".join(rows)}</tbody></table></div>'
            '<p class="note">Illustrative only: implied price = per-share value × multiple, computed by this script. '
            'The inputs are the research agent\'s assumptions, not forecasts, and not advice.</p>')


def build(ticker: str, notes: dict, out: Path, meta: dict | None = None) -> Path:
    df = build_table()
    if ticker not in set(df.ticker):
        raise SystemExit(f"{ticker} is not in the scored universe")
    r = df[df.ticker == ticker].iloc[0]
    px = load_prices(ticker)
    last_close, last_bar = float(px["Close"].iloc[-1]), px.index[-1].strftime("%Y-%m-%d")

    fresh = [inspect(d) for d in DATASETS]
    stale = sorted({x.ds.pipeline for x in fresh if x.verdict != "FRESH"})
    asof = (f'quality scored {file_date(DATA / "fundamentals" / "absolute_scores.csv")} · '
            f'valuation {file_date(DATA / "valuation" / "valuation.csv")} · '
            f'technical {file_date(DATA / "technical" / "technical_analysis.csv")} (last bar {last_bar})')
    stale_html = (f'<div class="callout"><b>Stale data:</b> {esc(", ".join(stale))} — outside the refresh cadence in '
                  f'docs/agent.md. Figures below may be out of date.</div>') if stale else ""

    tiles = [
        (num(r.quality_score), f"Quality score ({esc(r.quality_tier)})"),
        (num(r.ev_ebitda_norm), f"EV/EBITDA norm. (reported {num(r.ev_ebitda)})"),
        (num(r.pe_ttm), "Trailing P/E"),
        (num(r.fwd_pe), "Forward P/E (analyst)"),
        (pct(r.ret_1y, signed=True, digits=0), f"1y price return ({pct(r.from_high, signed=True, digits=0)} from high)"),
        (rating_chip(r.technical_rating), f"Technical · RSI {num(r.rsi)}"),
    ]
    tiles_html = "".join(f'<div class="tile"><b>{v}</b><span>{l}</span></div>' for v, l in tiles)

    def lst(items):
        return "<ul>" + "".join(f"<li>{txt(i)}</li>" for i in (items or [])) + "</ul>"

    biz = notes.get("business", {}) or {}
    ai_rev = pd.read_csv(DATA / "fundamentals" / "raw" / f"{ticker.replace('.', '_')}_income.csv", index_col=0)
    total_rev = pd.to_numeric(ai_rev.loc["Total Revenue"], errors="coerce").dropna()
    total_rev = float(total_rev.iloc[0]) if len(total_rev) else None
    seg_src = biz.get("segments_source") or {}
    segments_html = segment_chart(biz.get("segments") or [], total_rev)
    if segments_html:
        segments_html = (f'<h3>Revenue by segment — {esc(biz.get("segments_period", ""))}</h3>{segments_html}'
                         f'<p class="note">Source: {link(seg_src.get("src"), seg_src.get("url"))} '
                         f'{esc(seg_src.get("date", ""))}. Segment figures are from company filings, not the pipelines.</p>')

    risks = "".join(f'<li><b>{txt(x.get("risk"))}</b> — {txt(x.get("detail"))}'
                    f'{" (" + link(x.get("src"), x.get("url")) + ")" if x.get("url") else ""}</li>'
                    for x in notes.get("risks", []) or [])
    cats = "".join(f'<li><b>{esc(x.get("when", ""))}</b> — {txt(x.get("event"))}: {txt(x.get("detail"))} '
                   f'<span class="muted">[{"confirmed" if x.get("confirmed") else "expected / unconfirmed"}]</span>'
                   f'{" " + link(x.get("src"), x.get("url")) if x.get("url") else ""}</li>'
                   for x in notes.get("catalysts", []) or [])
    news = "".join(f'<li><b>{esc(n.get("date", ""))}</b> — {txt(n.get("text"))} {link(n.get("src"), n.get("url"))}</li>'
                   for n in notes.get("news", []) or [])
    unverified = notes.get("unverified") or []
    corrections = (meta or {}).get("corrections") or []
    peers = [p for p in (notes.get("peers") or []) if p in set(df.ticker) and p != ticker][:6]

    run_info = ""
    if meta:
        run_info = (f'<p class="note">Research run {esc(meta.get("started", ""))}; model {esc(meta.get("model", ""))}; '
                    f'{meta.get("turns", "?")} turns; est. cost ${meta.get("cost_usd", 0):.2f}; '
                    f'fact-check pass: {"on" if meta.get("verified") else "off"}.</p>')
    corr_html = ""
    if corrections:
        corr_html = ('<h3>Corrections made by the fact-check pass</h3><ul class="src">'
                     + "".join(f'<li>{txt(c.get("original"))} → {txt(c.get("corrected"))} '
                               f'<span class="muted">({txt(c.get("reason"))})</span></li>' for c in corrections)
                     + "</ul>")

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(ticker)} Deep Dive</title><style>{CSS}</style></head><body><main>
<h1>{esc(ticker)} — {esc(notes.get("name", ""))}</h1>
<p class="asof"><b>Data as of:</b> {asof}. Research checked {esc(notes.get("research_date", ""))}.
Report built {datetime.now():%Y-%m-%d %H:%M}. Quality percentiles are pool-wide over {int(df.quality_score.notna().sum())}
scored companies. Decision support, not investment advice.</p>
{stale_html}
<div class="card">
<p class="muted" style="margin-top:0">{esc(notes.get("industry", ""))} · market cap {money(r.market_cap)} · universe category: {esc(r.category)}</p>
<p><b>In one paragraph:</b> {txt(notes.get("summary"))}</p>
<div class="tiles">{tiles_html}</div>
{f'<div class="callout">{txt(notes.get("flag"))}</div>' if notes.get("flag") else ""}
</div>

<section class="card" style="break-before:auto"><h2>The business</h2>
<p>{txt(biz.get("summary"))}</p>
{lst(biz.get("key_points"))}
{segments_html}
</section>

<section class="card"><h2>Price and momentum</h2>
<h3>Last 12 months (daily close to {last_bar})</h3>
{price_chart(ticker)}
<p class="note">Hover for values. SMA 200 needs 200 trading days, so it starts partway through the window. Technical signals are
momentum, not a quality judgement. Source: technical pipeline.</p>
<p>{txt(notes.get("technical_note"))}</p>
</section>

<section class="card"><h2>Financials</h2>
<div class="legend"><span><i class="sw s1"></i>Revenue</span><span><i class="sw s2"></i>Normalized EBITDA</span></div>
{fundamentals_charts(ticker)}
<h3>Quality metrics (pool-wide percentile score in brackets)</h3>
<div class="tw"><table><thead><tr><th></th><th>Value</th><th>Score</th></tr></thead><tbody>
<tr><th scope="row">ROIC (EMA)</th><td>{pct(r.roic_avg)}</td><td>{num(r.roic_avg_capped_score, 0)}</td></tr>
<tr><th scope="row">FCF margin (EMA)</th><td>{pct(r.fcf_margin)}</td><td>{num(r.fcf_margin_capped_score, 0)}</td></tr>
<tr><th scope="row">Cash quality (CFO/NI)</th><td>{num(r.cfo_to_ni, 2)}</td><td>{num(r.cfo_to_ni_capped_score, 0)}</td></tr>
<tr><th scope="row">Net debt / EBITDA</th><td>{num(r.net_debt_ebitda, 2)}</td><td>{num(r.net_debt_ebitda_capped_score, 0)}</td></tr>
<tr><th scope="row">EBITDA CAGR</th><td>{pct(r.ebitda_cagr)}</td><td>{num(r.ebitda_cagr_capped_score, 0)}</td></tr>
<tr><th scope="row">Revenue CAGR</th><td>{pct(r.revenue_cagr)}</td><td>{num(r.revenue_cagr_capped_score, 0)}</td></tr>
</tbody></table></div>
<p>{txt(notes.get("financials_note"))}</p>
</section>

<section class="card"><h2>Against its peers</h2>
{peer_table(df, ticker, peers)}
<p class="note">{txt(notes.get("peer_caveat") or "Peers limited to names in the screened universe.")}</p>
<p>{txt(notes.get("peer_note"))}</p>
</section>

<section class="card"><h2>Valuation scenarios</h2>
{scenario_table(notes.get("scenarios") or {}, last_close)}
</section>

<section class="card"><h2>Risks and catalysts</h2>
<h3>Risks</h3><ul>{risks}</ul>
<h3>Catalysts and upcoming events</h3><ul>{cats}</ul>
</section>

<section class="card"><h2>Reading it together</h2>
<div class="cols3">
<div><h4>What the data says</h4>{lst(notes.get("says"))}</div>
<div><h4>What it might mean</h4>{lst(notes.get("means"))}</div>
<div><h4>What is uncertain / counter-case</h4>{lst(notes.get("uncertain"))}</div>
</div>
</section>

<section class="card"><h2>Recent news and filings</h2>
<ul class="src">{news}</ul>
{('<h3>Could not verify</h3>' + lst(unverified)) if unverified else ""}
{corr_html}
{run_info}
</section>
</main><div id="tip" role="tooltip"></div><script>{JS}</script></body></html>"""
    out.write_text(page)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--notes", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    doc = json.loads(a.notes.read_text())
    notes, meta = (doc["notes"], doc.get("meta")) if "notes" in doc else (doc, None)
    out = build(a.ticker.upper(), notes, a.out, meta)
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
