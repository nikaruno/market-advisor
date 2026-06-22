"""
Equity Screener GUI (standalone).

Two tabs, each reading the output of an independent pipeline:
  - Quality   : data/fundamentals/absolute_scores.csv   (run: bash run_quality.sh)
  - Technical : data/technical/technical_analysis.csv    (run: bash run_technical.sh)

Run the quality pipeline first — it builds the company universe the technical
pipeline then analyzes.

Run: bash run_quality_gui.sh
"""
import streamlit as st
import pandas as pd
import os
from pathlib import Path

# --- Run from the repo root whether launched from repo/ or repo/gui/ ---
if Path.cwd().name == 'gui':
    os.chdir('..')
if not (Path('gui').exists() and Path('src').exists()):
    st.error(f"Wrong directory! Current: {os.getcwd()}")
    st.stop()

st.set_page_config(page_title="Equity Screener", page_icon="\U0001F4C8",
                   layout="wide", initial_sidebar_state="collapsed")

SCORES_PATH = Path("data") / "fundamentals" / "absolute_scores.csv"
TECH_PATH = Path("data") / "technical" / "technical_analysis.csv"
VAL_PATH = Path("data") / "valuation" / "valuation.csv"
PRICES_DIR = Path("data") / "technical" / "prices"

# Quality metric column -> (display label, kind):
#   'pct'   -> stored as a fraction, shown x100 with a % label
#   'ratio' -> shown as-is (e.g. 1.8x), rounded
DISPLAY_METRICS = [
    ("roic_avg",        "ROIC %",             "pct"),
    ("fcf_margin",      "FCF %",              "pct"),
    ("cfo_to_ni",       "Cash Qual (CFO/NI)", "ratio"),
    ("net_debt_ebitda", "Net Debt/EBITDA",    "ratio"),
    ("ebitda_cagr",     "EBITDA Grw %",       "pct"),
    ("revenue_cagr",    "Rev Grw %",          "pct"),
]

RATING_ORDER = ['Strong Buy', 'Buy', 'Neutral', 'Sell', 'Strong Sell']


def quality_indicator(score):
    if pd.isna(score):
        return '\u26AA'
    if score >= 65:
        return '\U0001F7E2'
    if score >= 50:
        return '\U0001F7E1'
    if score >= 35:
        return '\U0001F7E0'
    return '\U0001F534'


def rating_indicator(rating):
    if rating in ('Strong Buy', 'Buy'):
        return '\U0001F7E2'
    if rating == 'Neutral':
        return '\U0001F7E1'
    if rating in ('Sell', 'Strong Sell'):
        return '\U0001F534'
    return '\u26AA'


def format_quality_table(df):
    """Quality columns only, numeric where it matters so sorting works."""
    cols = [c for c in ['ticker', 'category', 'quality_score', 'quality_tier'] if c in df.columns]
    out = df[cols].copy()
    if 'quality_score' in out.columns:
        out['quality_score'] = out['quality_score'].round(1)
    for src, label, kind in DISPLAY_METRICS:
        if src in df.columns:
            out[label] = (df[src] * 100).round(1) if kind == 'pct' else df[src].round(2)
    if 'data_completeness' in df.columns:
        out['Data %'] = df['data_completeness'].round(0)
    rename = {'category': 'Sector', 'quality_score': 'Quality', 'quality_tier': 'Tier'}
    out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
    out.insert(0, '\U0001F3AF', out['Quality'].apply(quality_indicator))
    return out


def format_tech_table(df):
    """Technical columns: rating, vote breakdown, RSI, last close."""
    cols = [c for c in ['ticker', 'category', 'technical_rating', 'technical_score',
                        'ma_buy', 'ma_sell', 'osc_buy', 'osc_sell', 'rsi', 'last_close']
            if c in df.columns]
    out = df[cols].copy()
    if 'technical_score' in out.columns:
        out['technical_score'] = out['technical_score'].round(1)
    rename = {'category': 'Sector', 'technical_rating': 'Rating', 'technical_score': 'Score',
              'ma_buy': 'MA Buy', 'ma_sell': 'MA Sell', 'osc_buy': 'Osc Buy',
              'osc_sell': 'Osc Sell', 'rsi': 'RSI', 'last_close': 'Last'}
    out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
    out.insert(0, '\U0001F4CA', out['Rating'].apply(rating_indicator))
    # Streamlit's grid sorts the displayed text, ignoring categorical order, so
    # prefix each rating with its rank (1=Strong Buy ... 5=Strong Sell). Now a
    # plain text sort on the column matches rank order in both directions.
    if 'Rating' in out.columns:
        rank = {r: i + 1 for i, r in enumerate(RATING_ORDER)}
        out['Rating'] = out['Rating'].map(lambda r: f"{rank.get(r, 9)}. {r}")
    return out


def format_value_table(df):
    """Valuation columns: ranked by EV/EBITDA, with the other ratios shown.
    Forward P/E is an analyst estimate (NTM), not a TTM figure."""
    out = pd.DataFrame()
    if 'value_rank' in df.columns:
        out['#'] = df['value_rank']
    out['ticker'] = df['ticker']
    if 'category' in df.columns:
        out['Sector'] = df['category']
    if 'ev_ebitda' in df.columns:
        out['EV/EBITDA'] = df['ev_ebitda'].round(1)
    if 'pe_ttm' in df.columns:
        out['P/E (TTM)'] = df['pe_ttm'].round(1)
    if 'fwd_pe' in df.columns:
        out['Fwd P/E'] = df['fwd_pe'].round(1)
    if 'pb' in df.columns:
        out['P/B'] = df['pb'].round(1)
    if 'market_cap' in df.columns:
        out['Mkt Cap $B'] = (df['market_cap'] / 1e9).round(1)
    # Provenance of the ranked metric: 'ttm' (from quarterly statements) vs
    # 'info' (yfinance trailing field). Blank when EV/EBITDA is unavailable.
    if 'ev_basis' in df.columns:
        out['EV src'] = df['ev_basis'].fillna('')
    return out


def load_master():
    """Merge the three pipelines into one table keyed by ticker. Quality is the
    base (it defines the universe + sector); technical and valuation are
    left-joined if those pipelines have run. Returns None if no quality data."""
    if not SCORES_PATH.exists():
        return None
    q = pd.read_csv(SCORES_PATH)
    if 'ticker' not in q.columns and q.index.name == 'ticker':
        q = q.reset_index()
    m = q[[c for c in ['ticker', 'category', 'quality_score', 'quality_tier']
           if c in q.columns]].copy()
    if TECH_PATH.exists():
        t = pd.read_csv(TECH_PATH)
        m = m.merge(t[[c for c in ['ticker', 'technical_rating', 'technical_score']
                       if c in t.columns]], on='ticker', how='left')
    if VAL_PATH.exists():
        v = pd.read_csv(VAL_PATH)
        m = m.merge(v[[c for c in ['ticker', 'ev_ebitda', 'fwd_pe', 'market_cap']
                       if c in v.columns]], on='ticker', how='left')
    return m


def format_lookup_table(peers, selected):
    """Sector peer table for the lookup tab: quality, technical, EV/EBITDA,
    forward P/E, market cap. The selected company is marked."""
    peers = peers.sort_values('quality_score', ascending=False) \
        if 'quality_score' in peers.columns else peers
    out = pd.DataFrame()
    out['\u25B6'] = peers['ticker'].apply(lambda t: '\u25B6' if t == selected else '')
    out['Ticker'] = peers['ticker'].values
    if 'quality_score' in peers.columns:
        out['Quality'] = peers['quality_score'].round(1).values
    if 'technical_rating' in peers.columns:
        out['Technical'] = peers['technical_rating'].fillna('\u2014').values
    if 'ev_ebitda' in peers.columns:
        out['EV/EBITDA'] = peers['ev_ebitda'].round(1).values
    if 'fwd_pe' in peers.columns:
        out['Fwd P/E'] = peers['fwd_pe'].round(1).values
    if 'market_cap' in peers.columns:
        out['Mkt Cap $B'] = (peers['market_cap'] / 1e9).round(1).values
    return out


# ============================================================================
# TABS
# ============================================================================
tab_quality, tab_technical, tab_value, tab_lookup = st.tabs(
    ["\U0001F3C6 Quality", "\U0001F4C8 Technical", "\U0001F4B0 Valuation",
     "\U0001F50E Company Lookup"])

# ----------------------------------------------------------------------------
# QUALITY
# ----------------------------------------------------------------------------
with tab_quality:
    st.header("\U0001F3C6 Quality Analysis")
    st.caption("Annual fundamental quality score and its components "
               "(US / USD-reporting companies only).")

    if not SCORES_PATH.exists():
        st.info("\u2139\ufe0f No quality data yet. Run `bash run_quality.sh` to scrape, "
                "download annual statements, and score the universe.")
    else:
        df = pd.read_csv(SCORES_PATH)
        if 'ticker' not in df.columns and df.index.name == 'ticker':
            df = df.reset_index()
        if 'quality_score' in df.columns:
            df = df[df['quality_score'].notna()]

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Companies", len(df))
        with c2:
            st.metric("Avg Quality", f"{df['quality_score'].mean():.1f}" if len(df) else "\u2014")
        with c3:
            if len(df):
                top = df.nlargest(1, 'quality_score').iloc[0]
                st.metric("Top Score", f"{top['quality_score']:.1f}", help=str(top['ticker']))
            else:
                st.metric("Top Score", "\u2014")
        with c4:
            n_complete = int((df.get('data_completeness', pd.Series(dtype=float)) >= 100).sum())
            st.metric("Full Data", f"{n_complete}/{len(df)}")

        st.divider()

        max_n = max(5, len(df))
        default_n = min(20, max_n)
        top_n = st.slider("Companies to display", 5, max_n, default_n,
                          key="q_top") if max_n > 5 else max_n
        st.dataframe(format_quality_table(df.nlargest(top_n, 'quality_score')),
                     use_container_width=True, hide_index=True)

        if 'category' in df.columns:
            with st.expander("\U0001F396\ufe0f Best in Each Sector"):
                best = []
                for cat in sorted(df['category'].dropna().unique()):
                    b = df[df['category'] == cat].nlargest(1, 'quality_score').iloc[0]
                    best.append({'Sector': cat, 'Company': b['ticker'],
                                 'Quality': round(b['quality_score'], 1),
                                 'Tier': b.get('quality_tier', '')})
                st.dataframe(pd.DataFrame(best), use_container_width=True, hide_index=True)

# ----------------------------------------------------------------------------
# TECHNICAL
# ----------------------------------------------------------------------------
with tab_technical:
    st.header("\U0001F4C8 Technical Analysis")
    st.caption("TradingView-style rating from a vote of moving averages and "
               "oscillators on ~1 year of daily prices.")

    if not TECH_PATH.exists():
        st.info("\u2139\ufe0f No technical data yet. Run `bash run_technical.sh` "
                "(run the quality pipeline first to build the universe).")
    else:
        tdf = pd.read_csv(TECH_PATH)

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Companies", len(tdf))
        with c2:
            buys = int(tdf['technical_rating'].isin(['Strong Buy', 'Buy']).sum())
            st.metric("Buy / Strong Buy", buys)
        with c3:
            sells = int(tdf['technical_rating'].isin(['Strong Sell', 'Sell']).sum())
            st.metric("Sell / Strong Sell", sells)
        with c4:
            st.metric("Neutral", int((tdf['technical_rating'] == 'Neutral').sum()))

        st.divider()

        max_n = max(5, len(tdf))
        default_n = min(20, max_n)
        top_n = st.slider("Companies to display", 5, max_n, default_n,
                          key="t_top") if max_n > 5 else max_n
        st.dataframe(format_tech_table(tdf.nlargest(top_n, 'technical_score')),
                     use_container_width=True, hide_index=True)

        if 'category' in tdf.columns:
            with st.expander("\U0001F396\ufe0f Strongest in Each Sector"):
                best = []
                for cat in sorted(tdf['category'].dropna().unique()):
                    b = tdf[tdf['category'] == cat].nlargest(1, 'technical_score').iloc[0]
                    best.append({'Sector': cat, 'Company': b['ticker'],
                                 'Rating': b['technical_rating'],
                                 'Score': round(b['technical_score'], 1)})
                st.dataframe(pd.DataFrame(best), use_container_width=True, hide_index=True)

# ----------------------------------------------------------------------------
# VALUATION
# ----------------------------------------------------------------------------
with tab_value:
    st.header("\U0001F4B0 Valuation")
    st.caption("Trailing valuation ratios (TTM / latest quarter), ranked cheapest-"
               "first by EV/EBITDA. Forward P/E is an analyst NTM estimate, not TTM.")

    if not VAL_PATH.exists():
        st.info("\u2139\ufe0f No valuation data yet. Run `bash run_valuation.sh` "
                "(run the quality pipeline first to build the universe).")
    else:
        vdf = pd.read_csv(VAL_PATH)
        rated = vdf[vdf['ev_ebitda'].notna()] if 'ev_ebitda' in vdf.columns else vdf

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Companies", len(vdf))
        with c2:
            st.metric("With EV/EBITDA", len(rated))
        with c3:
            if len(rated):
                cheapest = rated.nsmallest(1, 'ev_ebitda').iloc[0]
                st.metric("Cheapest EV/EBITDA", f"{cheapest['ev_ebitda']:.1f}",
                          help=str(cheapest['ticker']))
            else:
                st.metric("Cheapest EV/EBITDA", "\u2014")
        with c4:
            st.metric("Median EV/EBITDA",
                      f"{rated['ev_ebitda'].median():.1f}" if len(rated) else "\u2014")

        st.divider()

        # Already sorted cheapest-first by the pipeline; keep that as default.
        max_n = max(5, len(vdf))
        default_n = min(20, max_n)
        top_n = st.slider("Companies to display", 5, max_n, default_n,
                          key="v_top") if max_n > 5 else max_n
        st.dataframe(format_value_table(vdf.head(top_n)),
                     use_container_width=True, hide_index=True)
        st.caption("Lower EV/EBITDA = cheaper on an enterprise basis. Read this "
                   "alongside the Quality tab — cheap *and* high-quality is the "
                   "interesting combination; cheap alone is often a value trap. "
                   "**EV src**: `ttm` = summed from quarterly statements, `info` = "
                   "yfinance trailing field (still TTM).")

# ----------------------------------------------------------------------------
# COMPANY LOOKUP
# ----------------------------------------------------------------------------
with tab_lookup:
    st.header("\U0001F50E Company Lookup")
    st.caption("Pick a company to see its price history and how it stacks up "
               "against its sector peers across all three pipelines.")

    master = load_master()
    if master is None or master.empty:
        st.info("\u2139\ufe0f No data yet. Run `bash run_quality.sh` first "
                "(then technical/valuation for the full picture).")
    else:
        tickers = sorted(master['ticker'].dropna().unique())
        selected = st.selectbox("Company", tickers, key="lookup_ticker")
        row = master[master['ticker'] == selected].iloc[0]
        sector = row.get('category', '\u2014')
        st.markdown(f"**{selected}** &nbsp;·&nbsp; sector: *{sector}*")

        # --- Key metrics for the selected company ---
        m1, m2, m3, m4, m5 = st.columns(5)
        with m1:
            qs = row.get('quality_score')
            st.metric("Quality", f"{qs:.1f}" if pd.notna(qs) else "\u2014")
        with m2:
            st.metric("Technical", row.get('technical_rating')
                      if pd.notna(row.get('technical_rating')) else "\u2014")
        with m3:
            ev = row.get('ev_ebitda')
            st.metric("EV/EBITDA", f"{ev:.1f}" if pd.notna(ev) else "\u2014")
        with m4:
            fp = row.get('fwd_pe')
            st.metric("Fwd P/E", f"{fp:.1f}" if pd.notna(fp) else "\u2014")
        with m5:
            mc = row.get('market_cap')
            st.metric("Mkt Cap", f"${mc/1e9:.1f}B" if pd.notna(mc) else "\u2014")

        # --- Price history (from the technical pipeline's saved prices) ---
        st.subheader("Price")
        price_file = PRICES_DIR / f"{selected.replace('.', '_')}.csv"
        if price_file.exists():
            try:
                px = pd.read_csv(price_file, index_col=0, parse_dates=True)
                if 'Close' in px.columns and len(px):
                    st.line_chart(px['Close'], height=320)
                else:
                    st.info("Price file has no Close column.")
            except Exception as e:
                st.info(f"Could not read price history: {e}")
        else:
            st.info("\u2139\ufe0f No price history yet — run `bash run_technical.sh`.")

        # --- The company within its sector ---
        st.subheader(f"Within sector: {sector}")
        if 'category' in master.columns:
            peers = master[master['category'] == sector]
            st.dataframe(format_lookup_table(peers, selected),
                         use_container_width=True, hide_index=True)
        else:
            st.info("No sector information available.")
