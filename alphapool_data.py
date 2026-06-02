import os, re, sys, json, time, signal, subprocess
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
POOL_PROFILE_FILE = os.path.join(RUNTIME_DIR, "pool_profile.json")

DEFAULT_POOL_HOST = "stratum+tcp://us2.alphapool.tech:5566"
DEFAULT_MINER_EXEC = "./alpha-miner"
DEFAULT_PASSWORD = "x;d=65536"

POOL_PROFILE = {
    "pool_name": "AlphaPool",
    "default_pool_host": DEFAULT_POOL_HOST,
    "pool_options": [
        {
            "name": "US East",
            "host": "stratum+tcp://us1.alphapool.tech:5566",
            "description": "N. America East",
        },
        {
            "name": "US West",
            "host": "stratum+tcp://us2.alphapool.tech:5566",
            "description": "N. America West",
        },
        {
            "name": "EU 1",
            "host": "stratum+tcp://eu1.alphapool.tech:5566",
            "description": "Europe",
        },
        {
            "name": "EU 2",
            "host": "stratum+tcp://eu2.alphapool.tech:5566",
            "description": "Europe",
        },
        {
            "name": "Russia",
            "host": "stratum+tcp://ru1.alphapool.tech:5566",
            "description": "Russia / Eurasia",
        },
        {
            "name": "Asia SG",
            "host": "stratum+tcp://sg1.alphapool.tech:5566",
            "description": "Asia / Singapore",
        },
    ],
    "coming_soon_options": [
        {
            "name": "India",
            "description": "Coming soon",
        },
    ],
}

miner_process = None
start_time = time.time()


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
    msg = str(message or "").strip()
    if msg:
        with open(CMD_RESPONSE_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")


def write_pool_profile():
    atomic_write_json(POOL_PROFILE_FILE, POOL_PROFILE)


def load_config():
    cfg = read_json(CONFIG_FILE, {})

    # Force backend-specific values. dashboard.py writes a generic config, so
    # AlphaPool must not inherit PearlHash's ./pearl-miner value.
    cfg["pool_name"] = "AlphaPool"
    cfg["miner_exec"] = DEFAULT_MINER_EXEC
    cfg.setdefault("pool_host", DEFAULT_POOL_HOST)
    cfg.setdefault("wallet", "")
    cfg.setdefault("worker", "A")
    cfg.setdefault("password", DEFAULT_PASSWORD)
    return cfg


def default_cmd_state():
    return {"show_gpu": True, "show_mining": True, "show_pool": True, "show_wallet": True, "last_response": "Ready."}


def load_cmd_state():
    state = read_json(CMD_STATE_FILE, default_cmd_state())
    for k, v in default_cmd_state().items():
        state.setdefault(k, v)
    return state


def save_cmd_state(state):
    atomic_write_json(CMD_STATE_FILE, state)


def read_pending_commands():
    ensure_runtime()
    if not os.path.exists(CMD_QUEUE_FILE):
        return []
    try:
        with open(CMD_QUEUE_FILE, "r", encoding="utf-8", errors="ignore") as f:
            cmds = [x.strip() for x in f if x.strip()]
        open(CMD_QUEUE_FILE, "w").close()
        return cmds
    except Exception:
        return []


def wallet_url(wallet):
    return "N/A" if not wallet else f"https://pearl.alphapool.tech/#miner/{wallet}"


def get_gpu():
    for cmd in ["/mnt/c/Windows/System32/nvidia-smi.exe", "nvidia-smi.exe", "nvidia-smi"]:
        try:
            out = subprocess.check_output(
                [cmd, "--query-gpu=name,utilization.gpu,temperature.gpu,power.draw,memory.used,memory.total,fan.speed",
                 "--format=csv,noheader,nounits"],
                stderr=subprocess.DEVNULL,
            ).decode().strip()
            p = [x.strip() for x in out.splitlines()[0].split(",")]
            if len(p) >= 7:
                return {"name": p[0], "load": float(p[1]), "temp": float(p[2]), "power": float(p[3]),
                        "mem_used": p[4], "mem_total": p[5], "fan": p[6]}
        except Exception:
            pass
    return {"name": "N/A", "load": 0.0, "temp": 0.0, "power": 0.0, "mem_used": "0", "mem_total": "0", "fan": "0"}


def to_ths(value, unit):
    unit = unit.lower()
    if unit == "th/s": return value
    if unit == "gh/s": return value / 1000
    if unit == "mh/s": return value / 1_000_000
    if unit == "h/s": return value / 1_000_000_000_000
    return value


def recent_log_text(max_lines=400):
    if not os.path.exists(MINER_LOG_FILE):
        return ""
    try:
        with open(MINER_LOG_FILE, "r", errors="ignore") as f:
            return "".join(f.readlines()[-max_lines:])
    except Exception:
        return ""


def parse_hashrate():
    text = recent_log_text()
    if not text:
        return None

    patterns = [
        r"hashrate_th_s\s*=\s*([\d.]+)",
        r"hashrate_ths\s*=\s*([\d.]+)",
        r"hashrate_th/s\s*=\s*([\d.]+)",
        r"Hashrate\s+Total\s*[:=]\s*([\d.]+)\s*(TH/s|GH/s|MH/s|H/s)",
        r"Total\s+Hashrate\s*[:=]\s*([\d.]+)\s*(TH/s|GH/s|MH/s|H/s)",
        r"Hashrate\s*[:=]\s*([\d.]+)\s*(TH/s|GH/s|MH/s|H/s)",
        r"speed\s*[:=]\s*([\d.]+)\s*(TH/s|GH/s|MH/s|H/s)",
    ]

    values = []

    # AlphaPool direct TH/s fields.
    for pattern in patterns[:3]:
        for value in re.findall(pattern, text, re.IGNORECASE):
            try:
                v = float(value)
                if v > 0:
                    values.append(v)
            except Exception:
                pass

    # Generic hashrate fields with units.
    for pattern in patterns[3:]:
        for value, unit in re.findall(pattern, text, re.IGNORECASE):
            try:
                v = to_ths(float(value), unit)
                if v > 0:
                    values.append(v)
            except Exception:
                pass

    return round(sum(values[-10:]) / len(values[-10:]), 2) if values else None


def parse_shares():
    text = recent_log_text().lower()
    if not text:
        return 0, False
    submitted = sum(1 for line in text.splitlines() if "component=share" in line and "submitted" in line)
    if submitted:
        return submitted, True
    for pat in ["accepted share", "share accepted", "accepted", "result accepted"]:
        if pat in text:
            return sum(1 for line in text.splitlines() if pat in line), True
    return 0, False


def parse_rejects():
    text = recent_log_text().lower()
    return sum(1 for line in text.splitlines() if "reject" in line or "stale" in line) if text else 0


def start_miner(config):
    global miner_process
    if miner_process and miner_process.poll() is None:
        return True

    wallet = config.get("wallet", "").strip()
    worker = config.get("worker", "A").strip() or "A"
    if not wallet:
        append_response("No wallet address configured.")
        return False

    cmd = [
        config.get("miner_exec", DEFAULT_MINER_EXEC),
        "--pool", config.get("pool_host", DEFAULT_POOL_HOST),
        "--address", wallet,
        "--worker", worker,
        "--password", config.get("password", DEFAULT_PASSWORD),
    ]

    try:
        miner_exec = cmd[0]
        if not os.path.exists(os.path.join(SCRIPT_DIR, miner_exec.replace("./", "", 1))):
            append_response(f"AlphaPool miner not found: {miner_exec}")
            append_response("Run setup.sh again and allow alpha-miner download.")
            return False

        log_fh = open(MINER_LOG_FILE, "w", buffering=1)
        miner_process = subprocess.Popen(cmd, stdout=log_fh, stderr=subprocess.STDOUT, text=True, bufsize=1, cwd=SCRIPT_DIR)
        time.sleep(1)
        return True
    except Exception as e:
        append_response(f"Failed to launch AlphaPool miner: {e}")
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
            append_response("Closing AlphaPool dashboard...")
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
            append_response(f"running={running}, gpu={state['show_gpu']}, mining={state['show_mining']}, pool={state['show_pool']}, wallet={state['show_wallet']}")
            state["last_response"] = "Status shown."
            continue

        if cmd in ("explorer", "wallet", "wallet link"):
            append_response(wallet_url(config.get("wallet", "")))
            state["last_response"] = "Wallet link shown."
            continue

        parts = cmd.split()
        if len(parts) >= 2 and parts[0] in ("show", "hide", "toggle"):
            action, target = parts[0], parts[1]
            mp = {"gpu": "show_gpu", "gpus": "show_gpu", "mining": "show_mining", "mine": "show_mining",
                  "hashrate": "show_mining", "shares": "show_mining", "pool": "show_pool",
                  "wallet": "show_wallet", "balance": "show_wallet", "payout": "show_wallet"}
            if target in ("all", "telemetry"):
                keys = ["show_gpu", "show_mining", "show_pool", "show_wallet"]
            elif target in mp:
                keys = [mp[target]]
            else:
                append_response(f"Unknown telemetry target: {target}")
                state["last_response"] = "Unknown telemetry target."
                continue

            if action == "show":
                for k in keys: state[k] = True
            elif action == "hide":
                for k in keys: state[k] = False
            else:
                if target in ("all", "telemetry"):
                    new_value = not all(state[k] for k in keys)
                    for k in keys: state[k] = new_value
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
    rejects = parse_rejects()
    gpu = get_gpu()
    efficiency = round(hashrate / gpu["power"], 3) if gpu["power"] > 0 and hashrate is not None else None
    return {
        "pool": "AlphaPool",
        "pool_host": config.get("pool_host", DEFAULT_POOL_HOST),
        "wallet": config.get("wallet", ""),
        "worker": config.get("worker", "A"),
        "explorer_url": wallet_url(config.get("wallet", "")),
        "miner_status": "RUNNING" if running else "STOPPED",
        "hashrate_ths": hashrate,
        "accepted_shares": shares,
        "shares_detected": shares_detected,
        "rejected_stale": rejects,
        "session_seconds": int(time.time() - start_time),
        "gpu": gpu,
        "efficiency_thw": efficiency,
        "wallet_info": {"confirmed": None, "unconfirmed": None, "transactions": None, "last_updated": datetime.now().strftime("%H:%M:%S"), "error": None, "pool_url": wallet_url(config.get("wallet", ""))},
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
    config["pool_name"] = "AlphaPool"
    config["miner_exec"] = DEFAULT_MINER_EXEC
    config.setdefault("pool_host", DEFAULT_POOL_HOST)
    config.setdefault("password", DEFAULT_PASSWORD)

    if config.get("performance_mode") and apply_performance_mode_noninteractive:
        apply_performance_mode_noninteractive()

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
    if "--write-profile" in sys.argv:
        write_pool_profile()
        sys.exit(0)
    run()

