#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_SH="$SCRIPT_DIR/setup.sh"
DASHBOARD_PY="$SCRIPT_DIR/dashboard.py"

echo "============================================================"
echo " MONMINER - START"
echo "============================================================"

if [ ! -f "$SETUP_SH" ]; then
    echo "[ERROR] setup.sh not found."
    exit 1
fi

if [ ! -f "$DASHBOARD_PY" ]; then
    echo "[ERROR] dashboard.py not found."
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

echo "[INFO] Starting MonMiner dashboard..."
echo ""

python3 "$DASHBOARD_PY"
