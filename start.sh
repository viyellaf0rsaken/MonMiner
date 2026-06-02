#!/usr/bin/env bash

# ==============================================================================
# PEARLHASH MONITORED MINER - STARTER
# ==============================================================================
# This script:
#   1) runs setup.sh to check/update required files
#   2) starts dashboard.py if everything is ready
# ==============================================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_SH="$SCRIPT_DIR/setup.sh"
DASHBOARD_PY="$SCRIPT_DIR/dashboard.py"

print_header() {
    echo "============================================================"
    echo " PEARLHASH MONITORED MINER - START"
    echo "============================================================"
}

print_header

if [ ! -f "$SETUP_SH" ]; then
    echo "[ERROR] setup.sh not found in:"
    echo "        $SCRIPT_DIR"
    exit 1
fi

chmod +x "$SETUP_SH" 2>/dev/null || true

echo "[INFO] Running setup/update check..."
echo ""

bash "$SETUP_SH"
setup_result=$?

echo ""

if [ "$setup_result" -ne 0 ]; then
    echo "[ERROR] Setup failed. Dashboard will not start."
    exit "$setup_result"
fi

if [ ! -f "$DASHBOARD_PY" ]; then
    echo "[ERROR] dashboard.py not found after setup."
    exit 1
fi

echo "[INFO] Starting PearlHash dashboard..."
echo ""

python3 "$DASHBOARD_PY"
