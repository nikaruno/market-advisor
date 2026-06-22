#!/bin/bash
################################################################################
# RUN VALUATION PIPELINE (TTM ratios, ranked by EV/EBITDA)
#
# Standalone valuation pipeline: downloads quarterly statements + spot market cap
# for every company in the universe and computes P/E, P/B, EV/EBITDA on a TTM /
# latest-quarter basis (plus forward P/E for display). Ranks by EV/EBITDA.
#
# REQUIRES the quality pipeline to have run first (it builds the universe):
#     bash run_quality.sh
################################################################################

export PYTHONPATH="$(pwd)/src/screener:$(pwd):$PYTHONPATH"

echo "=============================================================================="
echo "  Running Valuation Pipeline"
echo "=============================================================================="
echo ""

if [ ! -f "data/fundamentals_raw.csv" ]; then
    echo "ERROR: universe not found (data/fundamentals_raw.csv)."
    echo "Run the quality pipeline first:  bash run_quality.sh"
    exit 1
fi

set -e
python3 src/screener/valuation_analysis.py

echo ""
echo "Done. Output: data/valuation/valuation.csv"
echo "Raw quarterly statements: data/valuation/raw/"
echo "View it with: bash run_quality_gui.sh  (Valuation tab)"
echo ""
