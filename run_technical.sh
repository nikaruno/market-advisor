#!/bin/bash
################################################################################
# RUN TECHNICAL PIPELINE (price-based)
#
# Standalone technical pipeline: downloads ~1 year of daily prices for every
# company in the universe and computes a TradingView-style rating. Prices move
# daily, so run this whenever you want a fresh read.
#
# REQUIRES the quality pipeline to have run first (it builds the universe):
#     bash run_quality.sh
################################################################################

export PYTHONPATH="$(pwd)/src/screener:$(pwd):$PYTHONPATH"

echo "=============================================================================="
echo "  Running Technical Pipeline"
echo "=============================================================================="
echo ""

if [ ! -f "data/fundamentals_raw.csv" ]; then
    echo "ERROR: universe not found (data/fundamentals_raw.csv)."
    echo "Run the quality pipeline first:  bash run_quality.sh"
    exit 1
fi

set -e
python3 src/screener/technical_analysis.py

echo ""
echo "Done. Output: data/technical/technical_analysis.csv"
echo "Raw prices:   data/technical/prices/"
echo "View it with: bash run_quality_gui.sh  (Technical tab)"
echo ""
