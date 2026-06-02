import os
import re
import sys
import json
import time
import html
import signal
import subprocess
import urllib.request
import urllib.error
from datetime import datetime

try:
    from performance import apply_performance_mode_noninteractive, restore_performance_mode
except Exception:
    apply_performance_mode_noninteractive = None
    restore_performance_mode = None

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(SCRIPT_DIR, "runtime")

CONFIG_FILE = os.path.join(RUNTIME_DIR, "config.json")
DATA_FILE = os.path.join(RUNTIME_DIR, "current_data.json")
CMD_STATE_FILE = os.path.join(RUNTIME_DIR, "cmd_state.json")
CMD_QUEUE_FILE = os.path.join(RUNTIME_DIR, "cmd_queue.txt")
CMD_RESPONSE_FILE = os.path.join(RUNTIME_DIR, "cmd_response.txt")
MINER_LOG_FILE = os.path.join(RUNTIME_DIR, "miner.log")
SHUTDOWN_FILE = os.path.join(RUNTIME_DIR, "shutdown.flag")

DEFAULT_POOL_HOST = "129.226.55.135:9000"
DEFAULT_MINER_EXEC = "./pearl-miner"

EXPLORER_BASE = "https://explorer.pearlresearch.ai/address"
EXPLORER_NETWORK = "mainnet"
EXPLORER_REFRESH_INTERVAL = 60

miner_process = None
start_time = time.time()
last_explorer_fetch = 0.0

explorer_cache = {
    "confirmed": None,
    "unconfirmed": None,
    "transactions": None,
    "last_updated": None,
    "error": None,
}


def ensure_runtime():
    os.makedirs(RUNTIME_DIR, exist_ok=True)


def atomic_write_json(path, data):
    ensure_runtime()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def append_response(message):
    ensure_runtime()
    message = str(message or "").strip()
    if not message:
        return

    with open(CMD_RESPONSE_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")


def load_config():
    cfg = read_json(CONFIG_FILE, {})
    cfg.setdefault("pool_name", "PearlHash")
    cfg.setdefault("pool_host", DEFAULT_POOL_HOST)
    cfg.setdefault("wallet", "")
    cfg.setdefault("worker", "A")
    cfg.setdefault("miner_exec", DEFAULT_MINER_EXEC)
    return cfg


def default_cmd_state():
    return {
        "show_gpu": True,
        "show_mining": True,
        "show_pool": True,
        "show_wallet": True,
        "last_response": "Ready.",
    }


def load_cmd_state():
    state = read_json(CMD_STATE_FILE, default_cmd_state())
    default = default_cmd_state()
    for key, value in default.items():
        state.setdefault(key, value)
    return state


def save_cmd_state(state):
    atomic_write_json(CMD_STATE_FILE, state)


def read_pending_commands():
    ensure_runtime()
    if not os.path.exists(CMD_QUEUE_FILE):
        return []

    try:
        with open(CMD_QUEUE_FILE, "r", encoding="utf-8", errors="ignore") as f:
            commands = [line.strip() for line in f if line.strip()]
        open(CMD_QUEUE_FILE, "w").close()
        return commands
    except Exception:
        return []


def explorer_url(wallet):
    if not wallet:
        return "N/A"
    return f"{EXPLORER_BASE}/{wallet}?network={EXPLORER_NETWORK}"


def html_to_lines(raw_html):
    text = re.sub(r"<script[\s\S]*?</script>", "\n", raw_html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = html.unescape(text)
    return [line.strip().lstrip("#").strip() for line in text.splitlines() if line.strip()]


def find_prl_value(lines, label):
    label = label.lower()
    for i, line in enumerate(lines):
        if line.lower() == label:
            for candidate in lines[i + 1:i + 8]:
                match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*PRL", candidate, re.IGNORECASE)
                if match:
                    return float(match.group(1))
    return None


def find_transactions(lines):
    for i, line in enumerate(lines):
        if line.lower() == "transactions":
            for candidate in lines[i + 1:i + 8]:
                if re.fullmatch(r"\d+", candidate):
                    return int(candidate)
                match = re.search(r"(\d+)\s+transactions?", candidate, re.IGNORECASE)
                if match:
                    return int(match.group(1))
    return None


def fetch_explorer(wallet):
    url = explorer_url(wallet)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "PearlHash-Monitored-Miner/1.0"},
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot reach Pearl Explorer — {getattr(e, 'reason', e)}")

    lines = html_to_lines(raw)
    confirmed = find_prl_value(lines, "Balance")
    unconfirmed = find_prl_value(lines, "Unconfirmed Balance")
    transactions = find_transactions(lines)

    if confirmed is None and unconfirmed is None and transactions is None:
        raise RuntimeError("Explorer page parsed, but no address data was found")

    return {
        "confirmed": confirmed,
        "unconfirmed": unconfirmed,
        "transactions": transactions,
    }


def maybe_refresh_explorer(wallet):
    global last_explorer_fetch

    if not wallet:
        return explorer_cache

    now = time.time()
    if now - last_explorer_fetch < EXPLORER_REFRESH_INTERVAL:
        return explorer_cache

    last_explorer_fetch = now

    try:
        info = fetch_explorer(wallet)
        explorer_cache["confirmed"] = info.get("confirmed")
        explorer_cache["unconfirmed"] = info.get("unconfirmed")
        explorer_cache["transactions"] = info.get("transactions")
        explorer_cache["last_updated"] = datetime.now().strftime("%H:%M:%S")
        explorer_cache["error"] = None
    except Exception as e:
        explorer_cache["error"] = str(e)[:90]

    return explorer_cache


def get_gpu():
    commands = ["/mnt/c/Windows/System32/nvidia-smi.exe", "nvidia-smi.exe", "nvidia-smi"]

    for cmd in commands:
        try:
            output = subprocess.check_output(
                [
                    cmd,
                    "--query-gpu=name,utilization.gpu,temperature.gpu,power.draw,"
                    "memory.used,memory.total,fan.speed",
                    "--format=csv,noheader,nounits",
                ],
                stderr=subprocess.DEVNULL,
            ).decode().strip()

            parts = [p.strip() for p in output.splitlines()[0].split(",")]
            if len(parts) < 7:
                continue

            return {
                "name": parts[0],
                "load": float(parts[1]),
                "temp": float(parts[2]),
                "power": float(parts[3]),
                "mem_used": parts[4],
                "mem_total": parts[5],
                "fan": parts[6],
            }
        except Exception:
            continue

    return {
        "name": "N/A",
        "load": 0.0,
        "temp": 0.0,
        "power": 0.0,
        "mem_used": "0",
        "mem_total": "0",
        "fan": "0",
    }


def to_ths(value, unit):
    unit = unit.lower()
    if unit == "th/s":
        return value
    if unit == "gh/s":
        return value / 1000
    if unit == "mh/s":
        return value / 1_000_000
    return value


def parse_hashrate():
    if not os.path.exists(MINER_LOG_FILE):
        return None

    try:
        with open(MINER_LOG_FILE, "r", errors="ignore") as f:
            text = "".join(f.readlines()[-200:])
    except Exception:
        return None

    patterns = [
        r"Hashrate\s+Total\s*[:=]\s*([\d.]+)\s*(TH/s|GH/s|MH/s)",
        r"Total\s+Hashrate\s*[:=]\s*([\d.]+)\s*(TH/s|GH/s|MH/s)",
        r"Hashrate\s*[:=]\s*([\d.]+)\s*(TH/s|GH/s|MH/s)",
    ]

    matches = []
    for pattern in patterns:
        matches.extend(re.findall(pattern, text, re.IGNORECASE))

    values = []
    for value, unit in matches[-10:]:
        try:
            values.append(to_ths(float(value), unit))
        except Exception:
            pass

    if not values:
        return None

    return round(sum(values) / len(values), 2)


def parse_shares():
    if not os.path.exists(MINER_LOG_FILE):
        return 0, False

    try:
        with open(MINER_LOG_FILE, "r", errors="ignore") as f:
            content = f.read().lower()
    except Exception:
        return 0, False

    patterns = [
        "accepted share",
        "share accepted",
        "sol:",
        "share submitted",
        "accepted:",
        "yay!!!",
        "result accepted",
        "block accepted",
    ]

    selected = None
    for pattern in patterns:
        if pattern in content:
            selected = pattern
            break

    if not selected:
        return 0, False

    return sum(1 for line in content.splitlines() if selected in line), True


def start_miner(config):
    global miner_process

    if miner_process and miner_process.poll() is None:
        return True

    cmd = [
        config.get("miner_exec", DEFAULT_MINER_EXEC),
        "--host", config.get("pool_host", DEFAULT_POOL_HOST),
        "--user", config.get("wallet", ""),
        "--worker", config.get("worker", "A"),
    ]

    try:
        log_fh = open(MINER_LOG_FILE, "w", buffering=1)
        miner_process = subprocess.Popen(
            cmd,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=SCRIPT_DIR,
        )
        time.sleep(1)
        return True
    except Exception as e:
        append_response(f"Failed to launch miner: {e}")
        return False


def stop_miner():
    global miner_process

    if miner_process and miner_process.poll() is None:
        miner_process.terminate()
        try:
            miner_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            miner_process.kill()


def restart_miner(config):
    stop_miner()
    time.sleep(0.5)
    return start_miner(config)


def handle_commands(config, state):
    should_close = False

    for raw in read_pending_commands():
        cmd = raw.strip().lower()

        if cmd in ("close", "close all", "stop", "stop all", "exit", "shutdown"):
            append_response("Closing miner dashboard...")
            state["last_response"] = "Closing..."
            should_close = True
            continue

        if cmd in ("pause", "pause mine", "pause miner", "stop mine", "stop miner"):
            stop_miner()
            append_response("Miner paused. Type start to resume.")
            state["last_response"] = "Miner paused."
            continue

        if cmd in ("start", "start mine", "start miner", "resume", "resume mine"):
            if start_miner(config):
                append_response("Miner started.")
                state["last_response"] = "Miner started."
            continue

        if cmd in ("restart", "restart mine", "restart miner"):
            if restart_miner(config):
                append_response("Miner restarted.")
                state["last_response"] = "Miner restarted."
            continue

        if cmd in ("status", "state"):
            running = bool(miner_process and miner_process.poll() is None)
            append_response(
                f"running={running}, gpu={state['show_gpu']}, mining={state['show_mining']}, "
                f"pool={state['show_pool']}, wallet={state['show_wallet']}"
            )
            state["last_response"] = "Status shown."
            continue

        if cmd in ("explorer", "wallet", "wallet link"):
            append_response(explorer_url(config.get("wallet", "")))
            state["last_response"] = "Explorer link shown."
            continue

        parts = cmd.split()
        if len(parts) >= 2 and parts[0] in ("show", "hide", "toggle"):
            action = parts[0]
            target = parts[1]

            target_map = {
                "gpu": "show_gpu",
                "gpus": "show_gpu",
                "mining": "show_mining",
                "mine": "show_mining",
                "hashrate": "show_mining",
                "shares": "show_mining",
                "pool": "show_pool",
                "wallet": "show_wallet",
                "balance": "show_wallet",
                "payout": "show_wallet",
            }

            if target in ("all", "telemetry"):
                keys = ["show_gpu", "show_mining", "show_pool", "show_wallet"]
            elif target in target_map:
                keys = [target_map[target]]
            else:
                append_response(f"Unknown telemetry target: {target}")
                state["last_response"] = "Unknown telemetry target."
                continue

            if action == "show":
                for key in keys:
                    state[key] = True
            elif action == "hide":
                for key in keys:
                    state[key] = False
            else:
                if target in ("all", "telemetry"):
                    new_value = not all(state[k] for k in keys)
                    for key in keys:
                        state[key] = new_value
                else:
                    state[keys[0]] = not state[keys[0]]

            append_response(f"Telemetry updated: {cmd}")
            state["last_response"] = "Telemetry updated."
            continue

        if cmd in ("perf on", "performance on"):
            if apply_performance_mode_noninteractive:
                ok, message = apply_performance_mode_noninteractive()
                append_response(message)
                append_response("Smart Cleanup is not included in console mode.")
                state["last_response"] = "Performance Mode enabled." if ok else "Perf unavailable."
            else:
                append_response("Performance Mode module not available.")
                state["last_response"] = "Perf unavailable."
            continue

        if cmd in ("perf off", "performance off"):
            if restore_performance_mode:
                ok, message = restore_performance_mode()
                append_response(message)
                state["last_response"] = "Performance Mode off." if ok else "Perf unavailable."
            else:
                append_response("Performance Mode module not available.")
                state["last_response"] = "Perf unavailable."
            continue

        if cmd == "quit":
            append_response("Use close to stop miner and close dashboard.")
            state["last_response"] = "Use close to exit."
            continue

        append_response(f"Unknown command: {raw}")
        state["last_response"] = "Unknown command."

    save_cmd_state(state)
    return should_close


def build_data(config):
    running = bool(miner_process and miner_process.poll() is None)
    hashrate = parse_hashrate()
    shares, shares_detected = parse_shares()
    gpu = get_gpu()

    efficiency = None
    if gpu["power"] > 0 and hashrate is not None:
        efficiency = round(hashrate / gpu["power"], 3)

    return {
        "pool": config.get("pool_name", "PearlHash"),
        "pool_host": config.get("pool_host", DEFAULT_POOL_HOST),
        "wallet": config.get("wallet", ""),
        "worker": config.get("worker", "A"),
        "explorer_url": explorer_url(config.get("wallet", "")),
        "miner_status": "RUNNING" if running else "STOPPED",
        "hashrate_ths": hashrate,
        "accepted_shares": shares,
        "shares_detected": shares_detected,
        "session_seconds": int(time.time() - start_time),
        "gpu": gpu,
        "efficiency_thw": efficiency,
        "wallet_info": maybe_refresh_explorer(config.get("wallet", "")),
        "updated_at": datetime.now().strftime("%H:%M:%S"),
    }


def cleanup_and_exit():
    if restore_performance_mode:
        restore_performance_mode()
    stop_miner()
    ensure_runtime()
    with open(SHUTDOWN_FILE, "w", encoding="utf-8") as f:
        f.write(str(time.time()))


def run():
    ensure_runtime()
    config = load_config()
    state = load_cmd_state()
    save_cmd_state(state)

    if not os.path.exists(MINER_LOG_FILE):
        open(MINER_LOG_FILE, "w").close()

    start_miner(config)

    def handle_signal(signum, frame):
        cleanup_and_exit()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while True:
        state = load_cmd_state()
        should_close = handle_commands(config, state)

        atomic_write_json(DATA_FILE, build_data(config))

        if should_close:
            cleanup_and_exit()
            return

        time.sleep(1)


if __name__ == "__main__":
    run()

