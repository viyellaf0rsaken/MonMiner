#!/usr/bin/env bash

# ==============================================================================
# MONMINER - SETUP / UPDATE CHECK
# ==============================================================================
# This script prepares the project folder:
#   - checks dependencies
#   - prepares runtime folder
#   - selects pool backend
#   - checks required project files
#   - downloads missing project files if MONMINER_UPDATE_URL is set
#   - downloads pearl-miner for PearlHash if user agrees
#   - checks Docker for MinePRL
#   - checks Python syntax
#
# It does NOT start the dashboard. Use start.sh for that.
# ==============================================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$SCRIPT_DIR/runtime"
POOL_BACKEND_FILE="$RUNTIME_DIR/pool_backend.json"

# Optional raw GitHub base URL.
# Example:
#   MONMINER_UPDATE_URL="https://raw.githubusercontent.com/viyellaf0rsaken/MonMiner/main" bash setup.sh
UPDATE_BASE_URL="${MONMINER_UPDATE_URL:-}"

PEARLHASH_MINER_URL="https://pearlhash.xyz/downloads/pearl-miner-v11"

CORE_FILES=(
  "dashboard.py"
  "cmd.py"
  "minerlog.py"
)

PEARLHASH_FILES=(
  "pearlhash_data.py"
)

MINEPRL_FILES=(
  "mineprl_data.py"
)

SELECTED_POOL="pearlhash"
SELECTED_DATA_FILE="pearlhash_data.py"

print_header() {
    echo "============================================================"
    echo " MONMINER - SETUP"
    echo "============================================================"
}

has_cmd() {
    command -v "$1" >/dev/null 2>&1
}

pause_enter() {
    echo ""
    read -rp "Press Enter to continue..."
}

prepare_runtime() {
    mkdir -p "$RUNTIME_DIR"
}

download_file() {
    local url="$1"
    local target="$2"

    if has_cmd curl; then
        curl -fL "$url" -o "$target"
        return $?
    fi

    if has_cmd wget; then
        wget "$url" -O "$target"
        return $?
    fi

    echo "[ERROR] curl or wget is required to download files."
    return 1
}

download_repo_file() {
    local file_name="$1"

    if [ -z "$UPDATE_BASE_URL" ]; then
        return 1
    fi

    local url="${UPDATE_BASE_URL%/}/${file_name}"
    local target="$SCRIPT_DIR/$file_name"

    echo "[INFO] Downloading $file_name"
    download_file "$url" "$target"
}

write_pool_backend() {
    local selected_pool="$1"
    local data_file="$2"

    prepare_runtime

    cat > "$POOL_BACKEND_FILE" <<EOF
{
  "selected_pool": "$selected_pool",
  "data_file": "$data_file"
}
EOF

    SELECTED_POOL="$selected_pool"
    SELECTED_DATA_FILE="$data_file"

    echo "[OK] Selected backend: $selected_pool ($data_file)"
}

select_pool_backend() {
    echo ""
    echo "============================================================"
    echo " Select pool backend"
    echo "============================================================"
    echo "  1) PearlHash"
    echo "  2) MinePRL"
    echo "  3) Custom/Future (not available yet)"
    echo ""

    read -rp "Choose [1-3] (Default: 1): " choice

    case "$choice" in
        2)
            write_pool_backend "mineprl" "mineprl_data.py"
            ;;
        3)
            echo "[WARN] Custom/Future backend is not available yet."
            echo "[INFO] Falling back to PearlHash."
            write_pool_backend "pearlhash" "pearlhash_data.py"
            ;;
        *)
            write_pool_backend "pearlhash" "pearlhash_data.py"
            ;;
    esac
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

prepare_files() {
    local failed=0
    local files=()

    files+=("${CORE_FILES[@]}")

    case "$SELECTED_POOL" in
        mineprl)
            files+=("${MINEPRL_FILES[@]}")
            ;;
        pearlhash|*)
            files+=("${PEARLHASH_FILES[@]}")
            ;;
    esac

    for file_name in "${files[@]}"; do
        if [ ! -f "$SCRIPT_DIR/$file_name" ]; then
            echo "[WARN] Missing $file_name"

            if download_repo_file "$file_name"; then
                echo "[OK] Downloaded $file_name"
            else
                echo "[ERROR] Could not prepare $file_name"
                if [ -z "$UPDATE_BASE_URL" ]; then
                    echo "        No MONMINER_UPDATE_URL is set, so setup cannot download missing files."
                fi
                failed=1
            fi
        else
            echo "[OK] $file_name found"
        fi
    done

    return "$failed"
}

download_pearlhash_miner() {
    local miner="$SCRIPT_DIR/pearl-miner"

    echo ""
    echo "PearlHash miner binary is required but not found."
    echo "Download command:"
    echo "  curl $PEARLHASH_MINER_URL -o pearl-miner && chmod +x pearl-miner"
    echo ""

    read -rp "Download pearl-miner now? (y/N): " ans

    if [[ ! "$ans" =~ ^[Yy]$ ]]; then
        echo "[WARN] Skipped pearl-miner download."
        return 1
    fi

    echo "[INFO] Downloading pearl-miner..."

    if download_file "$PEARLHASH_MINER_URL" "$miner"; then
        chmod +x "$miner" 2>/dev/null || true
        echo "[OK] pearl-miner downloaded."
        return 0
    fi

    echo "[ERROR] Failed to download pearl-miner."
    return 1
}

check_pearlhash_runtime() {
    local miner="$SCRIPT_DIR/pearl-miner"

    if [ ! -f "$miner" ]; then
        download_pearlhash_miner || return 1
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

check_mineprl_runtime() {
    if ! has_cmd docker; then
        echo "[ERROR] Docker is required for MinePRL."
        echo "        Install Docker Desktop on Windows or Docker Engine on Linux/WSL."
        return 1
    fi

    echo "[OK] docker found: $(docker --version)"

    if ! docker info >/dev/null 2>&1; then
        echo "[ERROR] Docker is installed but not running or not accessible."
        echo "        Start Docker Desktop or check your Docker permissions."
        return 1
    fi

    echo "[OK] Docker daemon is accessible"

    # This is only a warning because some systems allow --gpus all even if a test image is not present.
    if docker info 2>/dev/null | grep -qi "nvidia"; then
        echo "[OK] Docker appears to expose NVIDIA runtime info"
    else
        echo "[WARN] Could not confirm NVIDIA Docker runtime from docker info."
        echo "       MinePRL may still work, but --gpus all can fail if NVIDIA Container Toolkit is missing."
    fi

    return 0
}

check_selected_runtime() {
    case "$SELECTED_POOL" in
        mineprl)
            check_mineprl_runtime
            ;;
        pearlhash|*)
            check_pearlhash_runtime
            ;;
    esac
}

syntax_check() {
    local failed=0
    local files=()

    files+=("${CORE_FILES[@]}")

    case "$SELECTED_POOL" in
        mineprl)
            files+=("${MINEPRL_FILES[@]}")
            ;;
        pearlhash|*)
            files+=("${PEARLHASH_FILES[@]}")
            ;;
    esac

    for file_name in "${files[@]}"; do
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

show_summary() {
    echo "============================================================"
    echo " Setup summary"
    echo "============================================================"
    echo " Folder : $SCRIPT_DIR"
    echo " Pool   : $SELECTED_POOL"
    echo " Backend: $SELECTED_DATA_FILE"
    echo ""
    echo " Start with:"
    echo "   bash start.sh"
    echo "============================================================"
}

main() {
    print_header

    local ok=0

    check_python || ok=1
    check_tmux || ok=1
    check_nvidia_smi || true

    prepare_runtime
    select_pool_backend

    prepare_files || ok=1
    syntax_check || ok=1
    check_selected_runtime || ok=1

    show_summary

    if [ "$ok" -eq 0 ]; then
        echo "[OK] Setup check passed."
    else
        echo "[ERROR] Setup check failed."
    fi

    exit "$ok"
}

main "$@"

