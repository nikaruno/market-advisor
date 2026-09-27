#!/usr/bin/env python3
"""Build the cheap-and-high-quality HTML report.

Selection: the Top-25% quality tier, ranked by EV/EBITDA on *normalized*
TTM EBITDA (Yahoo's "Normalized EBITDA" row, which excludes unusual items
such as gains on securities). The valuation pipeline ranks on reported
EBITDA; the report shows both so the difference stays visible.

Everything numeric comes from data/ (the three pipelines). The written
commentary (news, peer notes, counter-case) comes from a notes JSON authored
alongside the report, so the numbers can be regenerated without touching it.

Output is one self-contained HTML file: inline SVG charts, inline CSS/JS,
no network needed to open it. Print to PDF from the browser if wanted.

Run:  prun python3 scripts/build_report.py \
        --notes reports/2026-09-27-cheap-and-high-quality.notes.json \
        --out   reports/2026-09-27-cheap-and-high-quality.html
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
sys.path.insert(0, str(REPO / "src" / "screener"))
from valuation_analysis import CASH_KEYS, DEBT_KEYS, _latest, _ttm_flow  # noqa: E402


def _rsi(close, period=14):
    # Same definition as technical_analysis._rsi (kept local: importing that
    # module pulls in yfinance and creates data folders as a side effect).
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + up / down)


def _macd(close):
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    return macd, macd.ewm(span=9, adjust=False).mean()


esc = html.escape


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def safe(t: str) -> str:
    return t.replace(".", "_")


def read_stmt(path: Path) -> pd.DataFrame | None:
    return pd.read_csv(path, index_col=0) if path.exists() else None


def row(df: pd.DataFrame | None, keys: list[str]) -> pd.Series:
    """First available statement row as a numeric Series (newest-first)."""
    if df is None:
        return pd.Series(dtype=float)
    for k in keys:
        if k in df.index:
            s = pd.to_numeric(df.loc[k], errors="coerce").dropna()
            if len(s):
                return s
    return pd.Series(dtype=float)


def load_prices(t: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / "technical" / "prices" / f"{safe(t)}.csv", index_col=0)
    df.index = pd.to_datetime(df.index.str[:10])
    return df


def file_date(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def build_table() -> pd.DataFrame:
    scores = pd.read_csv(DATA / "fundamentals" / "absolute_scores.csv").drop_duplicates("ticker")
    val = pd.read_csv(DATA / "valuation" / "valuation.csv").drop(columns=["category"])
    tech = pd.read_csv(DATA / "technical" / "technical_analysis.csv").drop_duplicates("ticker")
    df = scores.merge(val, on="ticker", how="left").merge(
        tech[["ticker", "technical_rating", "technical_score", "rsi", "last_close"]],
        on="ticker", how="left")

    extra = []
    for t in df.ticker:
        qi = read_stmt(DATA / "valuation" / "raw" / f"{safe(t)}_income_q.csv")
        qb = read_stmt(DATA / "valuation" / "raw" / f"{safe(t)}_balance_q.csv")
        rep, nor = _ttm_flow(qi, ["EBITDA"]), _ttm_flow(qi, ["Normalized EBITDA"])
        debt, cash = _latest(qb, DEBT_KEYS), _latest(qb, CASH_KEYS)
        mc = df.loc[df.ticker == t, "market_cap"].iloc[0]
        ev = mc + (0 if pd.isna(debt) else debt) - (0 if pd.isna(cash) else cash) if pd.notna(mc) else np.nan
        rev = row(qi, ["Total Revenue"])
        try:
            px = load_prices(t)["Close"]
            ret_1y = px.iloc[-1] / px.iloc[0] - 1
            from_hi = px.iloc[-1] / px.max() - 1
        except FileNotFoundError:
            ret_1y = from_hi = np.nan
        extra.append({
            "ticker": t,
            "ev": ev,
            "ebitda_ttm_rep": rep,
            "ebitda_ttm_norm": nor,
            "ev_ebitda_norm": ev / nor if nor and nor > 0 and pd.notna(ev) else np.nan,
            "ebitda_gap": (rep - nor) / nor if nor and nor > 0 else np.nan,
            "rev_yoy_q": rev.iloc[0] / rev.iloc[4] - 1 if len(rev) >= 5 and rev.iloc[4] > 0 else np.nan,
            "last_q": rev.index[0] if len(rev) else "",
            "ret_1y": ret_1y,
            "from_high": from_hi,
        })
    return df.merge(pd.DataFrame(extra), on="ticker", how="left")


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def pct(x, signed=False, digits=1):
    if x is None or pd.isna(x):
        return "—"
    return f"{x * 100:+.{digits}f}%" if signed else f"{x * 100:.{digits}f}%"


def num(x, digits=1):
    return "—" if x is None or pd.isna(x) else f"{x:,.{digits}f}"


def money(x):
    if x is None or pd.isna(x):
        return "—"
    a = abs(x)
    if a >= 1e12:
        return f"${x / 1e12:.2f}T"
    if a >= 1e9:
        return f"${x / 1e9:.1f}B"
    return f"${x / 1e6:.0f}M"


def nice_ticks(lo, hi, n=5):
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=10 * mag)
    start = math.floor(lo / step) * step
    ticks, v = [], start
    while v <= hi + step * 0.001:
        ticks.append(round(v, 10))
        v += step
    return ticks


RATING_CLASS = {"Strong Buy": "r-sb", "Buy": "r-b", "Neutral": "r-n", "Sell": "r-s", "Strong Sell": "r-ss"}


def rating_chip(r):
    if not isinstance(r, str):
        return "—"
    return f'<span class="chip {RATING_CLASS.get(r, "")}">{esc(r)}</span>'


# ---------------------------------------------------------------------------
# SVG charts
# ---------------------------------------------------------------------------
W = 760  # viewBox width; charts scale to container width


def price_chart(t: str) -> str:
    """Close + SMA50 + SMA200, with RSI(14) and MACD panels on a shared x."""
    px = load_prices(t)
    c = px["Close"]
    sma50, sma200 = c.rolling(50).mean(), c.rolling(200).mean()
    rsi = _rsi(c)
    macd, sig = _macd(c)
    hist = macd - sig
    n = len(c)
    L, R = 56, 118
    pw = W - L - R
    x = [L + i * pw / (n - 1) for i in range(n)]

    P = (16, 230)     # price panel top/bottom
    Rr = (262, 342)   # RSI panel
    M = (374, 464)    # MACD panel
    H = 492

    def yscale(lo, hi, top, bot):
        return lambda v: bot - (v - lo) / (hi - lo) * (bot - top)

    lo = float(np.nanmin([c.min(), sma50.min(), sma200.min()]))
    hi = float(np.nanmax([c.max(), sma50.max(), sma200.max()]))
    pt = nice_ticks(lo, hi, 5)
    yp = yscale(pt[0], pt[-1], *P)
    yr = yscale(0, 100, *Rr)
    mabs = float(np.nanmax(np.abs(np.concatenate([macd.values, sig.values, hist.values]))))
    mt = nice_ticks(-mabs, mabs, 4)
    ym = yscale(mt[0], mt[-1], *M)

    def path(series, ys):
        pts, out, pen = [], [], False
        for i, v in enumerate(series):
            if pd.isna(v):
                pen = False
                continue
            out.append(f"{'L' if pen else 'M'}{x[i]:.1f},{ys(v):.1f}")
            pen = True
        return "".join(out)

    g = []
    # gridlines + y labels
    for v in pt:
        g.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{yp(v):.1f}" y2="{yp(v):.1f}"/>'
                 f'<text class="tick" x="{L - 6}" y="{yp(v) + 4:.1f}" text-anchor="end">{v:,.0f}</text>')
    for v in (30, 50, 70):
        cls = "grid" if v == 50 else "ref"
        g.append(f'<line class="{cls}" x1="{L}" x2="{W - R}" y1="{yr(v):.1f}" y2="{yr(v):.1f}"/>'
                 f'<text class="tick" x="{L - 6}" y="{yr(v) + 4:.1f}" text-anchor="end">{v}</text>')
    g.append(f'<rect class="band" x="{L}" y="{yr(70):.1f}" width="{pw}" height="{yr(30) - yr(70):.1f}"/>')
    for v in mt:
        g.append(f'<line class="{"base" if v == 0 else "grid"}" x1="{L}" x2="{W - R}" y1="{ym(v):.1f}" y2="{ym(v):.1f}"/>'
                 f'<text class="tick" x="{L - 6}" y="{ym(v) + 4:.1f}" text-anchor="end">{v:g}</text>')
    # month ticks on the bottom axis
    months = c.index.to_series().groupby(c.index.to_period("M")).head(1)
    for d in months.index[1::2]:
        i = c.index.get_loc(d)
        g.append(f'<text class="tick" x="{x[i]:.1f}" y="{H - 8}" text-anchor="middle">{d.strftime("%b %y")}</text>')
    # panel titles
    g.append(f'<text class="ptitle" x="{L}" y="{Rr[0] - 8}">RSI (14) — 70 overbought / 30 oversold</text>')
    g.append(f'<text class="ptitle" x="{L}" y="{M[0] - 8}">MACD (12, 26, 9) — line vs signal, histogram = difference</text>')
    # MACD histogram
    bw = max(pw / n - 0.6, 0.8)
    for i, v in enumerate(hist):
        if pd.isna(v):
            continue
        y0, y1 = ym(0), ym(v)
        cls = "hpos" if v >= 0 else "hneg"
        g.append(f'<rect class="{cls}" x="{x[i] - bw / 2:.1f}" y="{min(y0, y1):.1f}" width="{bw:.1f}" height="{abs(y1 - y0):.1f}"/>')
    # lines
    g.append(f'<path class="ln s3" d="{path(sma200, yp)}"/>')
    g.append(f'<path class="ln s2" d="{path(sma50, yp)}"/>')
    g.append(f'<path class="ln s1" d="{path(c, yp)}"/>')
    g.append(f'<path class="ln s1" d="{path(rsi, yr)}"/>')
    g.append(f'<path class="ln s1" d="{path(macd, ym)}"/>')
    g.append(f'<path class="ln s2" d="{path(sig, ym)}"/>')
    # end labels (selective: last value of each price series)
    def _ext(i, word):
        return f" (1y {word})" if i == n - 1 else f" (near 1y {word})"
    at_ext = (_ext(int(c.values.argmax()), "high") if c.values.argmax() >= n - 5
              else _ext(int(c.values.argmin()), "low") if c.values.argmin() >= n - 5 else "")
    ends = [("Close", c.iloc[-1], "s1"), ("SMA50", sma50.iloc[-1], "s2"), ("SMA200", sma200.iloc[-1], "s3")]
    ends = [e for e in ends if pd.notna(e[1])]
    placed = []
    for name, v, cls in sorted(ends, key=lambda e: -e[1]):
        yy = yp(v)
        for p in placed:
            if abs(yy - p) < 13:
                yy = p + 13
        placed.append(yy)
        g.append(f'<circle class="dot {cls}" cx="{x[-1]:.1f}" cy="{yp(v):.1f}" r="4"/>'
                 f'<text class="elabel" x="{x[-1] + 8:.1f}" y="{yy + 4:.1f}">{name} {v:,.0f}{at_ext if name == "Close" else ""}</text>')
    # 52-week high / low markers; a marker on one of the last bars is folded
    # into the Close end label instead, and edge markers anchor inward
    for i, v, lab, dy in ((int(np.argmax(c.values)), c.max(), "1y high", -8),
                          (int(np.argmin(c.values)), c.min(), "1y low", 16)):
        if i >= n - 5:
            continue
        anchor = "start" if i < n * 0.08 else ("end" if i > n * 0.92 else "middle")
        g.append(f'<text class="anno" x="{x[i]:.1f}" y="{yp(v) + dy:.1f}" text-anchor="{anchor}">{lab} {v:,.0f}</text>')
    def r2(s):
        return [None if pd.isna(v) else round(float(v), 2) for v in s]

    payload = {
        "x": [round(v, 1) for v in x],
        "d": [d.strftime("%Y-%m-%d") for d in c.index],
        "series": [
            {"name": "Close", "cls": "s1", "v": r2(c), "y": [round(yp(v), 1) if pd.notna(v) else None for v in c]},
            {"name": "SMA50", "cls": "s2", "v": r2(sma50), "y": [round(yp(v), 1) if pd.notna(v) else None for v in sma50]},
            {"name": "SMA200", "cls": "s3", "v": r2(sma200), "y": [round(yp(v), 1) if pd.notna(v) else None for v in sma200]},
            {"name": "RSI", "cls": "s1", "v": r2(rsi), "y": [round(yr(v), 1) if pd.notna(v) else None for v in rsi]},
            {"name": "MACD", "cls": "s1", "v": r2(macd), "y": [round(ym(v), 1) if pd.notna(v) else None for v in macd]},
            {"name": "Signal", "cls": "s2", "v": r2(sig), "y": [round(ym(v), 1) if pd.notna(v) else None for v in sig]},
        ],
        "top": P[0], "bot": M[1],
    }
    legend = ('<div class="legend"><span><i class="k s1"></i>Close</span>'
              '<span><i class="k s2"></i>SMA 50</span><span><i class="k s3"></i>SMA 200</span>'
              '<span class="muted">MACD panel: blue = MACD, orange = signal</span></div>')
    return (legend +
            f'<svg class="chart xhair" viewBox="0 0 {W} {H}" role="img" '
            f'aria-label="{esc(t)} daily close with 50 and 200 day moving averages, RSI and MACD, last 12 months">'
            f'{"".join(g)}<line class="cross" y1="{P[0]}" y2="{M[1]}" x1="-10" x2="-10"/>'
            f'<rect class="hit" x="{L}" y="0" width="{pw}" height="{H}"/>'
            f'<script type="application/json">{json.dumps(payload)}</script></svg>')


def bar_chart(title: str, labels: list[str], rev: list[float], ebitda: list[float],
              growth: list[float | None], growth_label: str, note: str = "") -> str:
    """Grouped columns: revenue (slot 1) and normalized EBITDA (slot 2)."""
    Hc, L, R, T, B = 250, 56, 12, 16, 208
    n = len(labels)
    vals = [v for v in rev + ebitda if v is not None and not pd.isna(v)]
    lo = min(0, min(vals))
    ticks = nice_ticks(lo, max(vals), 4)
    ys = lambda v: B - (v - ticks[0]) / (ticks[-1] - ticks[0]) * (B - T)
    band = (W / 2 - L - R) / n  # half-width chart: two sit side by side
    Wc = W / 2
    bw = min(22, band / 2 - 6)
    g = []
    for v in ticks:
        g.append(f'<line class="{"base" if v == 0 else "grid"}" x1="{L}" x2="{Wc - R}" y1="{ys(v):.1f}" y2="{ys(v):.1f}"/>'
                 f'<text class="tick" x="{L - 6}" y="{ys(v) + 4:.1f}" text-anchor="end">{money(v) if v else "0"}</text>')

    def col(cx, v, cls, tip):
        if v is None or pd.isna(v):
            return ""
        y0, y1 = ys(0), ys(v)
        top, h = min(y0, y1), abs(y1 - y0)
        r = min(4, h)
        if v >= 0:  # rounded data-end at top, square at baseline
            d = (f"M{cx - bw / 2:.1f},{y0:.1f}V{top + r:.1f}Q{cx - bw / 2:.1f},{top:.1f} {cx - bw / 2 + r:.1f},{top:.1f}"
                 f"H{cx + bw / 2 - r:.1f}Q{cx + bw / 2:.1f},{top:.1f} {cx + bw / 2:.1f},{top + r:.1f}V{y0:.1f}Z")
        else:
            d = f"M{cx - bw / 2:.1f},{y0:.1f}V{y1:.1f}H{cx + bw / 2:.1f}V{y0:.1f}Z"
        return f'<path class="bar {cls}" d="{d}" tabindex="0" data-tip="{esc(json.dumps(tip))}"/>'

    for i, lab in enumerate(labels):
        cx = L + band * (i + 0.5)
        gtxt = pct(growth[i], signed=True, digits=0) if growth[i] is not None else "—"
        tip = {"t": lab, "rows": [["Revenue", money(rev[i]), "s1"], ["Norm. EBITDA", money(ebitda[i]), "s2"],
                                  [growth_label, gtxt, ""]]}
        g.append(col(cx - bw / 2 - 1, rev[i], "s1", tip))
        g.append(col(cx + bw / 2 + 1, ebitda[i], "s2", tip))
        g.append(f'<text class="tick" x="{cx:.1f}" y="{B + 16}" text-anchor="middle">{esc(lab)}</text>')
        gcls = "tick" if growth[i] is None else ("up" if growth[i] >= 0 else "down")
        g.append(f'<text class="{gcls}" x="{cx:.1f}" y="{B + 32}" text-anchor="middle">{gtxt}</text>')
    g.append(f'<text class="tick" x="{L - 6}" y="{B + 32}" text-anchor="end">{esc(growth_label)}</text>')
    # selective label: latest revenue on its cap
    if rev and rev[-1] is not None:
        cx = L + band * (n - 0.5) - bw / 2 - 1
        g.append(f'<text class="elabel" x="{cx:.1f}" y="{ys(rev[-1]) - 6:.1f}" text-anchor="middle">{money(rev[-1])}</text>')
    return (f'<figure class="half"><figcaption>{esc(title)}</figcaption>'
            f'<svg class="chart" viewBox="0 0 {Wc:.0f} {Hc}" role="img" aria-label="{esc(title)}">{"".join(g)}</svg>'
            + (f'<p class="note">{note}</p>' if note else "") + '</figure>')


def fundamentals_charts(t: str) -> str:
    ai = read_stmt(DATA / "fundamentals" / "raw" / f"{safe(t)}_income.csv")
    qi = read_stmt(DATA / "valuation" / "raw" / f"{safe(t)}_income_q.csv")
    ar, ae = row(ai, ["Total Revenue"]), row(ai, ["Normalized EBITDA", "EBITDA"])
    cols = [c for c in ar.index][:4][::-1]  # oldest -> newest
    labels = [f"FY{c[:4]}" for c in cols]
    rev = [float(ar[c]) for c in cols]
    eb = [float(ae[c]) if c in ae.index else None for c in cols]
    growth = [None] + [rev[i] / rev[i - 1] - 1 for i in range(1, len(rev))]
    annual = bar_chart("Annual revenue & normalized EBITDA", labels, rev, eb, growth, "Rev YoY",
                       f"Fiscal years ending {pd.Timestamp(cols[-1]).strftime('%b')}. Source: quality pipeline (annual statements).")

    qr, qe = row(qi, ["Total Revenue"]), row(qi, ["Normalized EBITDA", "EBITDA"])
    qc = list(qr.index)[:5][::-1]
    qlabels = [pd.Timestamp(c).strftime("%b '%y") for c in qc]
    qrev = [float(qr[c]) for c in qc]
    qeb = [float(qe[c]) if c in qe.index else None for c in qc]
    # YoY needs the same quarter a year earlier; with 5 quarters only the latest has it
    qg = [None] * len(qc)
    if len(qc) == 5:
        qg[-1] = qrev[-1] / qrev[0] - 1
    quarterly = bar_chart("Quarterly revenue & normalized EBITDA", qlabels, qrev, qeb, qg, "Rev YoY",
                          "Quarter-end dates as reported by Yahoo (month-end). YoY shown only where the year-ago quarter is in the data. Source: valuation pipeline.")
    return f'<div class="pair">{annual}{quarterly}</div>'


def overview_scatter(df: pd.DataFrame, picks: list[str]) -> str:
    """Quality score vs normalized EV/EBITDA for the Top-25% tier."""
    d = df[(df.quality_tier == "Top 25%") & df.ev_ebitda_norm.notna()].copy()
    XMAX = 60
    Hc, L, R, T, B = 360, 52, 20, 16, 318
    xs = lambda v: L + min(v, XMAX) / XMAX * (W - L - R)
    yt = nice_ticks(d.quality_score.min() - 2, d.quality_score.max() + 2, 5)
    ys = lambda v: B - (v - yt[0]) / (yt[-1] - yt[0]) * (B - T)
    g = []
    for v in yt:
        g.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{ys(v):.1f}" y2="{ys(v):.1f}"/>'
                 f'<text class="tick" x="{L - 6}" y="{ys(v) + 4:.1f}" text-anchor="end">{v:g}</text>')
    for v in range(0, XMAX + 1, 10):
        g.append(f'<text class="tick" x="{xs(v):.1f}" y="{B + 18}" text-anchor="middle">{v}{"+" if v == XMAX else ""}</text>')
    g.append(f'<text class="tick" x="{(L + W - R) / 2:.0f}" y="{Hc - 6}" text-anchor="middle">EV / normalized TTM EBITDA (cheaper ←)</text>')
    g.append(f'<text class="tick" x="14" y="{(T + B) / 2:.0f}" transform="rotate(-90 14 {(T + B) / 2:.0f})" text-anchor="middle">Quality score</text>')
    for _, r in d.sort_values("ticker").iterrows():
        pick = r.ticker in picks
        tip = {"t": f"{r.ticker} — {r.category}", "rows": [
            ["Quality", num(r.quality_score), ""], ["EV/EBITDA (norm.)", num(r.ev_ebitda_norm), ""],
            ["EV/EBITDA (reported)", num(r.ev_ebitda), ""], ["Technical", str(r.technical_rating), ""]]}
        cx, cy = xs(r.ev_ebitda_norm), ys(r.quality_score)
        g.append(f'<g class="pt" tabindex="0" data-tip="{esc(json.dumps(tip))}">'
                 f'<circle class="hitc" cx="{cx:.1f}" cy="{cy:.1f}" r="12"/>'
                 f'<circle class="dot {"s1" if pick else "other"}" cx="{cx:.1f}" cy="{cy:.1f}" r="{5 if pick else 4}"/></g>')
        if pick or r.ticker in ("GOOG", "NVDA", "APP", "NOW"):
            g.append(f'<text class="{"elabel" if pick else "anno"}" x="{cx + 8:.1f}" y="{cy - 6:.1f}">{esc(r.ticker)}</text>')
    return (f'<svg class="chart" viewBox="0 0 {W} {Hc}" role="img" '
            f'aria-label="Quality score against normalized EV/EBITDA for the top quality tier">{"".join(g)}</svg>')


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
PEER_COLS = [
    ("Quality", lambda r: num(r.quality_score)),
    ("ROIC", lambda r: pct(r.roic_avg, digits=0)),
    ("FCF margin", lambda r: pct(r.fcf_margin, digits=0)),
    ("Rev CAGR", lambda r: pct(r.revenue_cagr, digits=0)),
    ("Last-Q rev YoY", lambda r: pct(r.rev_yoy_q, signed=True, digits=0)),
    ("EV/EBITDA (norm.)", lambda r: num(r.ev_ebitda_norm)),
    ("Fwd P/E", lambda r: num(r.fwd_pe)),
    ("1y return", lambda r: pct(r.ret_1y, signed=True, digits=0)),
    ("Technical", lambda r: rating_chip(r.technical_rating)),
]


def peer_table(df: pd.DataFrame, t: str, peers: list[str]) -> str:
    rows = []
    for tk in [t] + peers:
        m = df[df.ticker == tk]
        if m.empty:
            continue
        r = m.iloc[0]
        cells = "".join(f"<td>{f(r)}</td>" for _, f in PEER_COLS)
        rows.append(f'<tr class="{"self" if tk == t else ""}"><th scope="row">{esc(tk)}</th>{cells}</tr>')
    head = "".join(f"<th>{esc(h)}</th>" for h, _ in PEER_COLS)
    return f'<div class="tw"><table><thead><tr><th></th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
CSS = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;
--up:#006300;--down:#d03b3b;--wash:rgba(42,120,214,.07);--band:rgba(42,120,214,.05);--warnbg:#fdf3e1}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;
--ink:#fff;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;
--up:#0ca30c;--down:#e66767;--wash:rgba(57,135,229,.12);--band:rgba(57,135,229,.08);--warnbg:#2e2616}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--grid:#2c2c2a;
--axis:#383835;--border:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--up:#0ca30c;--down:#e66767;
--wash:rgba(57,135,229,.12);--band:rgba(57,135,229,.08);--warnbg:#2e2616}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:21px;margin:0 0 2px}h3{font-size:15px;margin:22px 0 8px}
.asof{color:var(--ink2);font-size:13px;margin:0 0 18px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;margin:18px 0}
.muted,.note{color:var(--muted);font-size:12.5px}.note{margin:4px 0 0}
.callout{background:var(--warnbg);border-radius:10px;padding:12px 14px;margin:12px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin:14px 0}
.tile{border:1px solid var(--border);border-radius:10px;padding:10px 12px}
.tile b{display:block;font-size:20px;font-weight:600}.tile span{color:var(--ink2);font-size:12px}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media (max-width:720px){.pair{grid-template-columns:1fr}}
figure{margin:0}figcaption{font-weight:600;font-size:13.5px;margin-bottom:4px}
.chart{width:100%;height:auto;display:block;font-size:11px;overflow:visible}
.grid{stroke:var(--grid);stroke-width:1}.base{stroke:var(--axis);stroke-width:1}
.ref{stroke:var(--axis);stroke-width:1}.band{fill:var(--band)}
.tick{fill:var(--muted);font-variant-numeric:tabular-nums}.ptitle{fill:var(--ink2);font-size:11.5px}
.elabel{fill:var(--ink);font-weight:600;font-size:11.5px}.anno{fill:var(--ink2);font-size:10.5px}
.up{fill:var(--up);font-weight:600}.down{fill:var(--down);font-weight:600}
.ln{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.ln.s1{stroke:var(--s1)}.ln.s2{stroke:var(--s2)}.ln.s3{stroke:var(--s3)}
.bar.s1,.dot.s1{fill:var(--s1)}.bar.s2,.dot.s2{fill:var(--s2)}.dot.s3{fill:var(--s3)}
.dot{stroke:var(--surface);stroke-width:2}.dot.other{fill:var(--axis)}
.ghost{fill:none;stroke:var(--muted);stroke-width:1.5}.shift{stroke:var(--muted);stroke-width:1}
.hpos{fill:var(--s1);opacity:.35}.hneg{fill:var(--s2);opacity:.35}
.bar:hover,.bar:focus{opacity:.8;outline:none}.pt:focus{outline:none}.hitc{fill:transparent}
.hit{fill:transparent;cursor:crosshair}.cross{stroke:var(--muted);stroke-width:1;pointer-events:none}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12.5px;color:var(--ink2);margin:6px 0}
.legend span{display:inline-flex;align-items:center;gap:6px}
.k{display:inline-block;width:14px;height:0;border-top:2px solid}.k.s1{border-color:var(--s1)}
.k.s2{border-color:var(--s2)}.k.s3{border-color:var(--s3)}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px}.sw.s1{background:var(--s1)}.sw.s2{background:var(--s2)}
#tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--border);
border-radius:8px;padding:8px 10px;font-size:12px;box-shadow:0 4px 16px rgba(0,0,0,.12);display:none;z-index:9;min-width:140px}
#tip .t{color:var(--ink2);margin-bottom:4px}#tip .r{display:flex;align-items:center;gap:8px}
#tip .r b{margin-left:auto;padding-left:12px;font-variant-numeric:tabular-nums}
.tw{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;border-bottom:1px solid var(--grid);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}thead th{color:var(--ink2);font-weight:600;font-size:12px}
tr.self{background:var(--wash)}tr.self th{font-weight:700}
.chip{font-size:11.5px;padding:1px 8px;border-radius:99px;border:1px solid var(--border)}
.r-sb::before{content:"▲▲ "}.r-b::before{content:"▲ "}.r-n::before{content:"■ "}.r-s::before{content:"▼ "}.r-ss::before{content:"▼▼ "}
.r-sb,.r-b{color:var(--up)}.r-s,.r-ss{color:var(--down)}
.cols3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
@media (max-width:720px){.cols3{grid-template-columns:1fr}}
.cols3>div{border-top:2px solid var(--grid);padding-top:6px}.cols3 h4{margin:0 0 4px;font-size:13px;color:var(--ink2)}
.cols3 ul{margin:0;padding-left:18px}.cols3 li{margin:4px 0}
ul.src{font-size:12.5px;color:var(--ink2);padding-left:18px}
nav a{color:var(--s1);margin-right:12px;font-weight:600;text-decoration:none}
a{color:var(--s1)}
@media print{body{background:#fff}.card{break-inside:avoid-page;border-color:#ddd}#tip{display:none!important}
section.card{break-before:page}}
"""

JS = """
(function(){
const tip=document.getElementById('tip');
function show(e,t,rows){tip.replaceChildren();const h=document.createElement('div');h.className='t';h.textContent=t;tip.append(h);
 for(const [n,v,c] of rows){const r=document.createElement('div');r.className='r';if(c){const k=document.createElement('i');
 k.className='k '+c;r.append(k);}const s=document.createElement('span');s.textContent=n;const b=document.createElement('b');
 b.textContent=v;r.append(s,b);tip.append(r);}tip.style.display='block';place(e);}
function place(e){const pad=14;let x=e.clientX+pad,y=e.clientY+pad;const w=tip.offsetWidth,h=tip.offsetHeight;
 if(x+w>innerWidth-8)x=e.clientX-w-pad;if(y+h>innerHeight-8)y=e.clientY-h-pad;tip.style.left=x+'px';tip.style.top=y+'px';}
function hide(){tip.style.display='none';}
document.querySelectorAll('[data-tip]').forEach(el=>{const d=JSON.parse(el.getAttribute('data-tip'));
 const on=e=>show(e.clientX!==undefined?e:{clientX:el.getBoundingClientRect().right,clientY:el.getBoundingClientRect().top},d.t,d.rows);
 el.addEventListener('pointermove',on);el.addEventListener('focus',on);el.addEventListener('pointerleave',hide);el.addEventListener('blur',hide);});
document.querySelectorAll('svg.xhair').forEach(svg=>{const P=JSON.parse(svg.querySelector('script').textContent);
 const cross=svg.querySelector('.cross'),hit=svg.querySelector('.hit');
 hit.addEventListener('pointermove',e=>{const pt=svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;
  const sx=pt.matrixTransform(svg.getScreenCTM().inverse()).x;let lo=0,hi=P.x.length-1;
  while(hi-lo>1){const m=(lo+hi)>>1;if(P.x[m]<sx)lo=m;else hi=m;}const i=(sx-P.x[lo]<P.x[hi]-sx)?lo:hi;
  cross.setAttribute('x1',P.x[i]);cross.setAttribute('x2',P.x[i]);
  show(e,P.d[i],P.series.map(s=>[s.name,s.v[i]==null?'—':s.v[i].toLocaleString(undefined,{maximumFractionDigits:2}),s.cls]));});
 hit.addEventListener('pointerleave',()=>{cross.setAttribute('x1',-10);cross.setAttribute('x2',-10);hide();});});
})();
"""


def company_section(df, t, note, rank):
    r = df[df.ticker == t].iloc[0]
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
        return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"

    news = "".join(
        f'<li><b>{esc(n["date"])}</b> — {n["text"]} '
        f'<a href="{esc(n["url"])}" target="_blank" rel="noopener">{esc(n["src"])}</a></li>'
        for n in note.get("news", []))
    peers = note.get("peers", [])
    return f"""
<section class="card" id="{esc(t)}">
<h2>{rank}. {esc(t)} — {esc(note.get("name", ""))}</h2>
<p class="muted">{esc(note.get("industry", ""))} · market cap {money(r.market_cap)} · universe category: {esc(r.category)}</p>
<div class="tiles">{tiles_html}</div>
{f'<div class="callout">{note["flag"]}</div>' if note.get("flag") else ""}
<h3>Price, last 12 months (daily close to {load_prices(t).index[-1]:%Y-%m-%d})</h3>
{price_chart(t)}
<p class="note">Hover for values. SMA 200 needs 200 trading days, so it starts partway through the window.
Technical signals are momentum, not a quality judgement. Source: technical pipeline.</p>
<h3>Revenue &amp; EBITDA</h3>
<div class="legend"><span><i class="sw s1"></i>Revenue</span><span><i class="sw s2"></i>Normalized EBITDA</span></div>
{fundamentals_charts(t)}
<h3>Against its peers</h3>
{peer_table(df, t, peers)}
<p class="note">{note.get("peer_caveat", "Peers limited to names in the screened universe.")}</p>
<p>{note.get("peer_note", "")}</p>
<div class="cols3">
<div><h4>What the data says</h4>{lst(note.get("says", []))}</div>
<div><h4>What it might mean</h4>{lst(note.get("means", []))}</div>
<div><h4>What is uncertain / counter-case</h4>{lst(note.get("uncertain", []))}</div>
</div>
<h3>Recent company news (primary sources where possible)</h3>
<ul class="src">{news}</ul>
</section>"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--notes", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--top", type=int, default=5)
    a = ap.parse_args()
    notes = json.loads(a.notes.read_text())

    df = build_table()
    tier = df[df.quality_tier == "Top 25%"]
    picks = tier.dropna(subset=["ev_ebitda_norm"]).sort_values("ev_ebitda_norm").ticker.head(a.top).tolist()
    rep_picks = tier.dropna(subset=["ev_ebitda"]).sort_values("ev_ebitda").ticker.head(a.top).tolist()
    missing = [t for t in picks if t not in notes["companies"]]
    if missing:
        sys.exit(f"notes JSON has no entry for: {', '.join(missing)}")

    asof = {
        "quality": file_date(DATA / "fundamentals" / "absolute_scores.csv"),
        "valuation": file_date(DATA / "valuation" / "valuation.csv"),
        "technical": file_date(DATA / "technical" / "technical_analysis.csv"),
        "last_bar": load_prices(picks[0]).index[-1].strftime("%Y-%m-%d"),
    }

    # summary table
    srows = []
    for i, t in enumerate(picks, 1):
        r = df[df.ticker == t].iloc[0]
        srows.append(
            f'<tr><th scope="row"><a href="#{esc(t)}">{i}. {esc(t)}</a></th><td>{num(r.quality_score)}</td>'
            f'<td>{num(r.ev_ebitda_norm)}</td><td>{num(r.ev_ebitda)}</td><td>{num(r.pe_ttm)}</td><td>{num(r.fwd_pe)}</td>'
            f'<td>{pct(r.rev_yoy_q, signed=True, digits=0)}</td><td>{pct(r.ret_1y, signed=True, digits=0)}</td>'
            f'<td>{rating_chip(r.technical_rating)}</td></tr>')
    summary = ('<div class="tw"><table><thead><tr><th></th><th>Quality</th><th>EV/EBITDA norm.</th><th>EV/EBITDA reported</th>'
               '<th>P/E</th><th>Fwd P/E</th><th>Last-Q rev YoY</th><th>1y return</th><th>Technical</th></tr></thead>'
               f'<tbody>{"".join(srows)}</tbody></table></div>')

    dropped = [t for t in rep_picks if t not in picks]
    drows = []
    for t in dropped:
        r = df[df.ticker == t].iloc[0]
        drows.append(f"<li><b>{esc(t)}</b>: reported EV/EBITDA {num(r.ev_ebitda)} → normalized {num(r.ev_ebitda_norm)} "
                     f"(reported TTM EBITDA {money(r.ebitda_ttm_rep)} vs normalized {money(r.ebitda_ttm_norm)}, "
                     f"{pct(r.ebitda_gap, digits=0)} higher).</li>")
    n_dist = int((df.ebitda_gap > 0.10).sum())
    n_all = int(df.ebitda_gap.notna().sum())

    sections = "".join(company_section(df, t, notes["companies"][t], i) for i, t in enumerate(picks, 1))
    nav = "".join(f'<a href="#{esc(t)}">{esc(t)}</a>' for t in picks)
    n_scored = int(df.quality_score.notna().sum())
    n_tier = len(tier)

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cheap and High Quality</title><style>{CSS}</style></head><body><main>
<h1>Cheap and high quality — top {a.top}</h1>
<p class="asof"><b>Data as of:</b> quality scored {asof["quality"]} · valuation computed {asof["valuation"]} ·
technical rated {asof["technical"]} (last price bar {asof["last_bar"]}). Report built {datetime.now():%Y-%m-%d %H:%M}.
News checked {esc(notes.get("news_checked", ""))}. Pool: {n_scored} scored companies at companies_per_sector 25 —
percentile scores are pool-wide and not comparable to runs with a different pool.</p>
<nav>{nav}</nav>

<div class="card">
<h3 style="margin-top:0">How the five were picked</h3>
<p>Start from the {n_tier} companies in the <b>Top-25% quality tier</b>, then rank by <b>EV / normalized TTM EBITDA</b>, cheapest
first. This is decision support, not investment advice: it lists where cheapness and quality overlap in the data, with the
counter-case for each name.</p>
{summary}
<div class="callout"><b>Metric distortion found — ranking changed because of it.</b> The valuation pipeline ranks on
<i>reported</i> EBITDA, which includes gains on securities. {n_dist} of {n_all} companies in the universe have reported TTM
EBITDA more than 10% above normalized. Ranked the pipeline's way, the top {a.top} would have included:
<ul>{"".join(drows) or "<li>no difference</li>"}</ul>{notes.get("distortion_note", "")}</div>
</div>

<div class="card">
<h3 style="margin-top:0">Where the top-quality tier sits on price</h3>
<p class="muted">Each dot is one Top-25% quality company; blue = the five covered here. Positions use normalized EBITDA; the callout above lists the names
that move most versus reported. EV/EBITDA above 60 is pinned to the right edge. Hover a dot for values.</p>
{overview_scatter(df, picks)}
{notes.get("overview_note", "")}
</div>

{sections}

<div class="card"><h3 style="margin-top:0">Method notes</h3>{notes.get("method_notes", "")}</div>
</main><div id="tip" role="tooltip"></div><script>{JS}</script></body></html>"""
    a.out.write_text(page)
    print(f"wrote {a.out}  ({a.out.stat().st_size / 1024:.0f} KB)  picks: {', '.join(picks)}  "
          f"(reported-basis picks: {', '.join(rep_picks)})")


if __name__ == "__main__":
    main()
