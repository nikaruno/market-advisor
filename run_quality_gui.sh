#!/bin/bash
################################################################################
# RUN QUALITY GUI (single Quality tab)
################################################################################

export PYTHONPATH="$(pwd)/src/screener:$(pwd):$PYTHONPATH"
export PATH="$HOME/.local/bin:$PATH"

echo "=============================================================================="
echo "  Starting Quality Analysis GUI  ->  http://localhost:8501"
echo "  Press Ctrl+C to stop"
echo "=============================================================================="
echo ""

if command -v streamlit &> /dev/null; then
    streamlit run gui/quality_app.py --server.port=8501 --server.address=localhost
elif [ -f "$HOME/.local/bin/streamlit" ]; then
    "$HOME/.local/bin/streamlit" run gui/quality_app.py --server.port=8501 --server.address=localhost
else
    python3 -m streamlit run gui/quality_app.py --server.port=8501 --server.address=localhost
fi
