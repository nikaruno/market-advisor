"""
Absolute Quality Scoring System v3.1
- EMA averaging for ROIC, FCF, Leverage, Cash Quality (recent years weighted more)
- 6 metrics: ROIC, FCF, Cash Quality, Leverage, Revenue Growth, EBITDA Growth
- Removed: interest_coverage, margin_trend, margin_volatility (noisy on 4yr windows)
- EBITDA Growth replaces net-income growth (cleaner of tax/one-time/non-op items)
- Per-row weight redistribution for missing metrics
- Deduplication of tickers appearing in multiple sectors
"""
import pandas as pd
import numpy as np
from pathlib import Path
import json

METRICS_PATH = Path("data/fundamentals/company_metrics.csv")
OUTPUT_PATH = Path("data/fundamentals/absolute_scores.csv")
CONFIG_FILE = Path("config.json")


def load_weights():
    """Load weights from config file or use defaults.
    v3.1: 6 metrics. Removed interest_coverage, margin_trend, margin_volatility.
    """
    defaults = {
        'roic': 0.25,
        'fcf': 0.20,
        'cash_quality': 0.15,
        'leverage': 0.15,
        'revenue_growth': 0.10,
        'ebitda_growth': 0.15,
    }

    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            w = config.get('weights', {})

            # Backward compat: split old 'growth' into revenue + EBITDA growth
            if 'growth' in w and 'revenue_growth' not in w:
                g = w.pop('growth', 0.20)
                w['revenue_growth'] = round(g * 0.5, 2)
                w['ebitda_growth'] = round(g * 0.5, 2)

            # Backward compat: the growth slot used to be net-income growth.
            # Carry the old weight over to the EBITDA-growth slot.
            if 'income_growth' in w and 'ebitda_growth' not in w:
                w['ebitda_growth'] = w.pop('income_growth')
            w.pop('income_growth', None)

            # Remove deprecated keys (their weight is reclaimed by normalization
            # against the 6-metric set below).
            w.pop('interest_coverage', None)
            w.pop('other', None)
            w.pop('margin_trend', None)
            w.pop('margin_volatility', None)

            # Merge with defaults for any missing keys
            for k, v in defaults.items():
                if k not in w:
                    w[k] = v

            return w

    return defaults


def normalize_metric(series, reverse=False):
    """Normalize metric to 0-100 scale using percentile rank."""
    series_clean = series.replace([np.inf, -np.inf], np.nan)
    if reverse:
        scores = (1 - series_clean.rank(pct=True, na_option='keep')) * 100
    else:
        scores = series_clean.rank(pct=True, na_option='keep') * 100
    return scores


def cap_outliers(series, lower_percentile=5, upper_percentile=95):
    """Cap extreme outliers to reduce their impact."""
    series_clean = series.replace([np.inf, -np.inf], np.nan)
    lower_bound = series_clean.quantile(lower_percentile / 100)
    upper_bound = series_clean.quantile(upper_percentile / 100)
    return series_clean.clip(lower=lower_bound, upper=upper_bound)


def compute_absolute_scores(df):
    """Compute absolute quality scores comparing all companies together."""
    df = df.copy()

    weights = load_weights()
    print(f"\nUsing weights: {weights}")

    # Verify weights sum to ~1.0
    weight_sum = sum(weights.values())
    if abs(weight_sum - 1.0) > 0.01:
        print(f"  [WARN] Weights sum to {weight_sum:.3f}, normalizing to 1.0")
        weights = {k: v / weight_sum for k, v in weights.items()}

    print("\nComputing absolute quality scores (v3.1 — EMA + 6 metrics)...")

    # Cap extreme outliers
    metrics_to_cap = ['roic_avg', 'fcf_margin', 'cfo_to_ni', 'revenue_cagr',
                      'net_debt_ebitda', 'ebitda_cagr']
    for metric in metrics_to_cap:
        if metric in df.columns:
            df[f'{metric}_capped'] = cap_outliers(df[metric])

    # Define all metrics with weight keys and direction
    all_metrics = [
        ('roic_avg_capped',          'roic',              False, 'ROIC (EMA)'),
        ('fcf_margin_capped',        'fcf',               False, 'FCF Margin (EMA)'),
        ('cfo_to_ni_capped',         'cash_quality',      False, 'Cash Quality (EMA)'),
        ('revenue_cagr_capped',      'revenue_growth',    False, 'Revenue Growth'),
        ('ebitda_cagr_capped',       'ebitda_growth',     False, 'EBITDA Growth'),
        ('net_debt_ebitda_capped',   'leverage',          True,  'Leverage (EMA, inv)'),
    ]

    # Normalize each metric to 0-100 percentile scale
    score_columns = []
    for col, weight_key, reverse, label in all_metrics:
        w = weights.get(weight_key, 0)
        if col in df.columns and w > 0:
            normalized = normalize_metric(df[col], reverse=reverse)
            score_col = f'{col}_score'
            df[score_col] = normalized
            score_columns.append((score_col, weight_key))
            direction = " (inverse)" if reverse else ""
            print(f"  {label:30s} {w:5.0%} weight{direction}")
        elif w > 0:
            print(f"  {label:30s} {w:5.0%} weight — COLUMN MISSING: {col}")

    # Compute quality score with per-row weight redistribution for NaN values
    def compute_row_score(row):
        available_weight = 0.0
        weighted_sum = 0.0
        for score_col, weight_key in score_columns:
            w = weights.get(weight_key, 0)
            val = row.get(score_col, np.nan)
            if pd.notna(val) and w > 0:
                available_weight += w
                weighted_sum += val * w
        if available_weight > 0:
            return weighted_sum / available_weight * sum(weights[wk] for _, wk in score_columns)
        return np.nan

    df['quality_score'] = df.apply(compute_row_score, axis=1)

    # Track data completeness
    n_metrics = len(score_columns)
    df['metrics_available'] = df[[sc for sc, _ in score_columns]].notna().sum(axis=1)
    df['data_completeness'] = (df['metrics_available'] / n_metrics * 100).round(0)

    n_complete = (df['metrics_available'] == n_metrics).sum()
    n_partial = ((df['metrics_available'] < n_metrics) & (df['metrics_available'] > 0)).sum()
    print(f"\n  Data completeness: {n_complete} complete, {n_partial} partial")

    # Regional percentiles
    if 'region' in df.columns:
        df['quality_percentile_regional'] = df.groupby('region')['quality_score'].rank(pct=True) * 100
    df['quality_percentile'] = df['quality_score'].rank(pct=True) * 100

    # Assign tiers
    pctl_col = 'quality_percentile_regional' if 'quality_percentile_regional' in df.columns else 'quality_percentile'

    def assign_tier(percentile):
        if pd.isna(percentile):
            return 'Unknown'
        if percentile >= 75:
            return 'Top 25%'
        elif percentile >= 50:
            return 'Top 50%'
        elif percentile >= 25:
            return 'Bottom 50%'
        else:
            return 'Bottom 25%'

    df['quality_tier'] = df[pctl_col].apply(assign_tier)

    return df


def main():
    """Main function to run scoring process."""
    print("Computing absolute quality scores (v3)...")

    if not METRICS_PATH.exists():
        print(f"Error: {METRICS_PATH} not found")
        return False

    df = pd.read_csv(METRICS_PATH, index_col=0)
    print(f"Loaded {len(df)} rows")

    # Deduplicate tickers in multiple sectors — keep row with most data
    metric_cols = ['roic_avg', 'fcf_margin', 'cfo_to_ni', 'net_debt_ebitda',
                   'revenue_cagr', 'ebitda_cagr']
    existing_cols = [c for c in metric_cols if c in df.columns]
    df['_n_valid'] = df[existing_cols].notna().sum(axis=1)
    before = len(df)
    df = df.sort_values('_n_valid', ascending=False)
    df = df[~df.index.duplicated(keep='first')]
    df = df.drop(columns=['_n_valid'])
    after = len(df)
    if before > after:
        print(f"Deduplicated: {before} → {after} unique tickers")

    if 'region' in df.columns:
        print(f"Regions: {df['region'].value_counts().to_dict()}")

    df_scored = compute_absolute_scores(df)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df_scored.to_csv(OUTPUT_PATH)
    print(f"\nResults saved to {OUTPUT_PATH}")

    df_display = df_scored.reset_index()
    if 'ticker' in df_display.columns:
        top_10 = df_display.nlargest(10, 'quality_score')[['ticker', 'quality_score', 'quality_tier']]
    else:
        top_10 = df_scored.nlargest(10, 'quality_score')[['quality_score', 'quality_tier']]
    print(f"\nTop 10:")
    print(top_10.to_string())

    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
