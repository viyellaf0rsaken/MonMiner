#!/usr/bin/env bash

# ==============================================================================
# PEARLHASH MONITORED MINER - SETUP / UPDATE CHECK
# ==============================================================================
# This script only prepares the project folder:
#   - checks dependencies
#   - downloads missing project files if UPDATE_BASE_URL is set
#   - checks pearl-miner presence
#   - makes scripts executable
#
# It does NOT start the dashboard. Use start.sh for that.
# ==============================================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Fill this later when the GitHub repo is ready, for example:
# UPDATE_BASE_URL="https://raw.githubusercontent.com/YOUR_NAME/YOUR_REPO/main"
#
# Or run with:
# PEARLHASH_UPDATE_URL="https://raw.githubusercontent.com/YOUR_NAME/YOUR_REPO/main" bash setup.sh
UPDATE_BASE_URL="${PEARLHASH_UPDATE_URL:-}"

REQUIRED_FILES=(
  "dashboard.py"
  "pearlhash_data.py"
  "cmd.py"
  "minerlog.py"
)

OPTIONAL_FILES=(
  "README.md"
)

print_header() {
    echo "============================================================"
    echo " PEARLHASH MONITORED MINER - SETUP"
    echo "============================================================"
}

has_cmd() {
    command -v "$1" >/dev/null 2>&1
}

download_file() {
    local file_name="$1"

    if [ -z "$UPDATE_BASE_URL" ]; then
        return 1
    fi

    local url="${UPDATE_BASE_URL%/}/${file_name}"
    local target="$SCRIPT_DIR/$file_name"

    echo "[INFO] Downloading $file_name"

    if has_cmd curl; then
        curl -fsSL "$url" -o "$target"
        return $?
    fi

    if has_cmd wget; then
        wget -q "$url" -O "$target"
        return $?
    fi

    echo "[ERROR] curl or wget is required to download files."
    return 1
}

check_python() {
    if ! has_cmd python3; then
        echo "[ERROR] python3 is missing."
        echo "        Install it with:"
        echo "        sudo apt update && sudo apt install -y python3"
        return 1
    fi

    echo "[OK] python3 found: $(python3 --version)"
    return 0
}

check_tmux() {
    if ! has_cmd tmux; then
        echo "[WARN] tmux is missing."

        if has_cmd sudo && has_cmd apt; then
            read -rp "Install tmux now? (y/N): " ans
            if [[ "$ans" =~ ^[Yy]$ ]]; then
                sudo apt update && sudo apt install -y tmux
            fi
        fi
    fi

    if has_cmd tmux; then
        echo "[OK] tmux found: $(tmux -V)"
        return 0
    fi

    echo "[ERROR] tmux is required."
    return 1
}

check_downloader() {
    if has_cmd curl || has_cmd wget; then
        return 0
    fi

    if [ -n "$UPDATE_BASE_URL" ]; then
        echo "[ERROR] curl or wget is required because UPDATE_BASE_URL is set."
        return 1
    fi

    return 0
}

check_nvidia_smi() {
    if has_cmd nvidia-smi; then
        echo "[OK] nvidia-smi found in PATH"
        return 0
    fi

    if [ -x "/mnt/c/Windows/System32/nvidia-smi.exe" ]; then
        echo "[OK] nvidia-smi found at /mnt/c/Windows/System32/nvidia-smi.exe"
        return 0
    fi

    echo "[WARN] nvidia-smi not found. GPU stats may show N/A."
    return 0
}

prepare_runtime() {
    mkdir -p "$SCRIPT_DIR/runtime"
}

prepare_project_files() {
    local missing=0

    for file_name in "${REQUIRED_FILES[@]}"; do
        if [ ! -f "$SCRIPT_DIR/$file_name" ]; then
            echo "[WARN] Missing $file_name"

            if download_file "$file_name"; then
                echo "[OK] Downloaded $file_name"
            else
                echo "[ERROR] Could not prepare $file_name"
                missing=1
            fi
        else
            echo "[OK] $file_name found"
        fi
    done

    for file_name in "${OPTIONAL_FILES[@]}"; do
        if [ ! -f "$SCRIPT_DIR/$file_name" ] && [ -n "$UPDATE_BASE_URL" ]; then
            download_file "$file_name" >/dev/null 2>&1 || true
        fi
    done

    return "$missing"
}

check_miner_binary() {
    local miner="$SCRIPT_DIR/pearl-miner"

    if [ ! -f "$miner" ]; then
        echo "[ERROR] pearl-miner not found."
        echo "        Download pearl-miner from the official Pearl release page"
        echo "        and place it next to dashboard.py."
        return 1
    fi

    chmod +x "$miner" 2>/dev/null || true

    if [ ! -x "$miner" ]; then
        echo "[ERROR] pearl-miner exists but is not executable."
        echo "        Try: chmod +x pearl-miner"
        return 1
    fi

    echo "[OK] pearl-miner found"
    return 0
}

syntax_check() {
    local failed=0

    for file_name in "${REQUIRED_FILES[@]}"; do
        if [ -f "$SCRIPT_DIR/$file_name" ]; then
            if python3 -m py_compile "$SCRIPT_DIR/$file_name"; then
                echo "[OK] syntax check: $file_name"
            else
                echo "[ERROR] syntax check failed: $file_name"
                failed=1
            fi
        fi
    done

    return "$failed"
}

main() {
    print_header

    local ok=0

    check_python || ok=1
    check_tmux || ok=1
    check_downloader || ok=1
    check_nvidia_smi || true
    prepare_runtime

    prepare_project_files || ok=1
    syntax_check || ok=1
    check_miner_binary || ok=1

    echo "============================================================"

    if [ "$ok" -eq 0 ]; then
        echo "[OK] Setup check passed."
    else
        echo "[ERROR] Setup check failed."
    fi

    exit "$ok"
}

main "$@"
