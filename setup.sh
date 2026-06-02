#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$SCRIPT_DIR/runtime"
POOL_BACKEND_FILE="$RUNTIME_DIR/pool_backend.json"

UPDATE_BASE_URL="${MONMINER_UPDATE_URL:-}"

PEARLHASH_MINER_URL="https://pearlhash.xyz/downloads/pearl-miner-v11"
ALPHAPOOL_MINER_URL="https://pearl.alphapool.tech/downloads/alpha-miner"

CORE_FILES=("dashboard.py" "cmd.py" "minerlog.py" "performance.py")
PEARLHASH_FILES=("pearlhash_data.py")
MINEPRL_FILES=("mineprl_data.py")
ALPHAPOOL_FILES=("alphapool_data.py")

SELECTED_POOL="pearlhash"
SELECTED_DATA_FILE="pearlhash_data.py"

has_cmd() { command -v "$1" >/dev/null 2>&1; }

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
    [ -z "$UPDATE_BASE_URL" ] && return 1
    download_file "${UPDATE_BASE_URL%/}/${file_name}" "$SCRIPT_DIR/$file_name"
}

prepare_runtime() { mkdir -p "$RUNTIME_DIR"; }

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
    echo "  3) AlphaPool"
    echo "  4) Custom/Future (not available yet)"
    echo ""
    read -rp "Choose [1-4] (Default: 1): " choice
    case "$choice" in
        2) write_pool_backend "mineprl" "mineprl_data.py" ;;
        3) write_pool_backend "alphapool" "alphapool_data.py" ;;
        4) echo "[WARN] Custom/Future backend is not available yet."; write_pool_backend "pearlhash" "pearlhash_data.py" ;;
        *) write_pool_backend "pearlhash" "pearlhash_data.py" ;;
    esac
}

check_python() {
    if ! has_cmd python3; then
        echo "[ERROR] python3 is missing."
        echo "        sudo apt update && sudo apt install -y python3"
        return 1
    fi
    echo "[OK] python3 found: $(python3 --version)"
}

check_tmux() {
    if ! has_cmd tmux; then
        echo "[WARN] tmux is missing."
        if has_cmd sudo && has_cmd apt; then
            read -rp "Install tmux now? (y/N): " ans
            [[ "$ans" =~ ^[Yy]$ ]] && sudo apt update && sudo apt install -y tmux
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
}

prepare_files() {
    local failed=0
    local files=("${CORE_FILES[@]}")
    case "$SELECTED_POOL" in
        mineprl) files+=("${MINEPRL_FILES[@]}") ;;
        alphapool) files+=("${ALPHAPOOL_FILES[@]}") ;;
        *) files+=("${PEARLHASH_FILES[@]}") ;;
    esac
    for f in "${files[@]}"; do
        if [ ! -f "$SCRIPT_DIR/$f" ]; then
            echo "[WARN] Missing $f"
            if download_repo_file "$f"; then
                echo "[OK] Downloaded $f"
            else
                echo "[ERROR] Could not prepare $f"
                failed=1
            fi
        else
            echo "[OK] $f found"
        fi
    done
    return "$failed"
}

download_pearlhash_miner() {
    read -rp "Download pearl-miner now? (y/N): " ans
    [[ ! "$ans" =~ ^[Yy]$ ]] && return 1
    download_file "$PEARLHASH_MINER_URL" "$SCRIPT_DIR/pearl-miner" && chmod +x "$SCRIPT_DIR/pearl-miner"
}

download_alphapool_miner() {
    read -rp "Download alpha-miner now? (y/N): " ans
    [[ ! "$ans" =~ ^[Yy]$ ]] && return 1
    download_file "$ALPHAPOOL_MINER_URL" "$SCRIPT_DIR/alpha-miner" && chmod +x "$SCRIPT_DIR/alpha-miner"
}

check_pearlhash_runtime() {
    local m="$SCRIPT_DIR/pearl-miner"
    [ ! -f "$m" ] && download_pearlhash_miner || true
    chmod +x "$m" 2>/dev/null || true
    [ -x "$m" ] && echo "[OK] pearl-miner found" && return 0
    echo "[ERROR] pearl-miner missing or not executable."
    return 1
}

check_alphapool_runtime() {
    local m="$SCRIPT_DIR/alpha-miner"
    [ ! -f "$m" ] && download_alphapool_miner || true
    chmod +x "$m" 2>/dev/null || true
    [ -x "$m" ] && echo "[OK] alpha-miner found" && return 0
    echo "[ERROR] alpha-miner missing or not executable."
    return 1
}

check_mineprl_runtime() {
    if ! has_cmd docker; then echo "[ERROR] Docker is required for MinePRL."; return 1; fi
    echo "[OK] docker found: $(docker --version)"
    docker info >/dev/null 2>&1 && echo "[OK] Docker daemon is accessible" && return 0
    echo "[ERROR] Docker is installed but not running or not accessible."
    return 1
}

check_selected_runtime() {
    case "$SELECTED_POOL" in
        mineprl) check_mineprl_runtime ;;
        alphapool) check_alphapool_runtime ;;
        *) check_pearlhash_runtime ;;
    esac
}

syntax_check() {
    local failed=0
    local files=("${CORE_FILES[@]}")
    case "$SELECTED_POOL" in
        mineprl) files+=("${MINEPRL_FILES[@]}") ;;
        alphapool) files+=("${ALPHAPOOL_FILES[@]}") ;;
        *) files+=("${PEARLHASH_FILES[@]}") ;;
    esac
    for f in "${files[@]}"; do
        if [ -f "$SCRIPT_DIR/$f" ]; then
            python3 -m py_compile "$SCRIPT_DIR/$f" && echo "[OK] syntax check: $f" || { echo "[ERROR] syntax check failed: $f"; failed=1; }
        fi
    done
    return "$failed"
}

main() {
    echo "============================================================"
    echo " MONMINER - SETUP"
    echo "============================================================"
    local ok=0
    check_python || ok=1
    check_tmux || ok=1
    check_nvidia_smi || true
    prepare_runtime
    select_pool_backend
    prepare_files || ok=1
    syntax_check || ok=1
    check_selected_runtime || ok=1
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
    [ "$ok" -eq 0 ] && echo "[OK] Setup check passed." || echo "[ERROR] Setup check failed."
    exit "$ok"
}

main "$@"

