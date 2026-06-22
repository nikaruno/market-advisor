#!/bin/bash
################################################################################
# RUN QUALITY PIPELINE (annual data only)
#
# Standalone annual pipeline: scrape the USD-only universe, download annual
# statements, compute quality metrics, and score. Run this infrequently
# (e.g. after fiscal year-ends).
################################################################################

export PYTHONPATH="$(pwd)/src/screener:$(pwd):$PYTHONPATH"

echo "=============================================================================="
echo "  Running Quality Pipeline (annual only)"
echo "=============================================================================="
echo ""

set -e

echo "[1/4] Scraping universe (USD-only)..."
python3 src/screener/scrape_fundamentals.py

echo ""
echo "[2/4] Downloading annual statements..."
python3 src/screener/download_annual.py

echo ""
echo "[3/4] Computing quality metrics..."
python3 src/screener/compute_detailed_metrics.py

echo ""
echo "[4/4] Scoring (absolute quality)..."
python3 src/screener/absolute_scores.py

echo ""
echo "Done. Output: data/fundamentals/absolute_scores.csv"
echo "View it with: bash run_quality_gui.sh"
echo ""
