import os
import re
import sys
import json
import time
import signal
import subprocess
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

CONTAINER_NAME = "mineprl"
DOCKER_IMAGE = "mineprl/worker:mineprl_miner_v3"
DOCKER_VOLUME = "mineprl-config:/etc/mineprl"

# MinePRL uses Docker instead of a normal stratum host.
# Keep pool_options empty so dashboard skips region selection.
POOL_PROFILE = {
    "pool_name": "MinePRL",
    "default_pool_host": "mineprl-docker",
    "pool_options": [],
}

miner_process = None
log_process = None
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
    message = str(message or "").strip()
    if not message:
        return

    with open(CMD_RESPONSE_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")


def write_pool_profile():
    ensure_runtime()
    atomic_write_json(POOL_PROFILE_FILE, POOL_PROFILE)


def load_config():
    cfg = read_json(CONFIG_FILE, {})
    cfg.setdefault("pool_name", "MinePRL")
    cfg.setdefault("pool_host", "mineprl-docker")
    cfg.setdefault("wallet", "")
    cfg.setdefault("worker", "A")
    cfg.setdefault("docker_image", DOCKER_IMAGE)
    cfg.setdefault("container_name", CONTAINER_NAME)
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


def has_docker():
    try:
        subprocess.run(
            ["docker", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except Exception:
        return False


def docker_run(args, timeout=15, check=False):
    try:
        return subprocess.run(
            ["docker"] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=check,
        )
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


def container_exists(container_name):
    result = docker_run(["inspect", container_name], timeout=8)
    return bool(result and result.returncode == 0)


def container_status(container_name):
    result = docker_run(
        ["inspect", "-f", "{{.State.Status}}", container_name],
        timeout=8,
    )

    if not result or result.returncode != 0:
        return "missing"

    status = (result.stdout or "").strip()
    return status or "unknown"


def stop_log_follower():
    global log_process

    if log_process and log_process.poll() is None:
        log_process.terminate()
        try:
            log_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            log_process.kill()

    log_process = None


def start_log_follower(container_name):
    global log_process

    stop_log_follower()

    ensure_runtime()

    # Clear old runtime log for this session.
    open(MINER_LOG_FILE, "w").close()

    try:
        log_fh = open(MINER_LOG_FILE, "a", buffering=1)
        log_process = subprocess.Popen(
            ["docker", "logs", "-f", "--tail", "50", container_name],
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except Exception as e:
        append_response(f"Failed to start Docker log follower: {e}")


def start_miner(config):
    if not has_docker():
        append_response("Docker is not installed or not accessible.")
        return False

    wallet = config.get("wallet", "")
    worker = config.get("worker", "A")
    image = config.get("docker_image", DOCKER_IMAGE)
    container_name = config.get("container_name", CONTAINER_NAME)

    if not wallet:
        append_response("No wallet address configured.")
        return False

    status = container_status(container_name)

    if status == "running":
        start_log_follower(container_name)
        return True

    if status in ("created", "exited", "paused", "restarting", "dead"):
        # Recreate container to make sure PRL_ADDRESS / RIG_LABEL changes are applied.
        docker_run(["rm", "-f", container_name], timeout=15)

    cmd = [
        "run",
        "-d",
        "--gpus", "all",
        "--restart", "unless-stopped",
        "--name", container_name,
        "-e", f"PRL_ADDRESS={wallet}",
        "-e", f"RIG_LABEL={worker}",
        "-v", DOCKER_VOLUME,
        image,
    ]

    result = docker_run(cmd, timeout=60)

    if not result or result.returncode != 0:
        err = ""
        if result:
            err = ((result.stderr or "") + " " + (result.stdout or "")).strip()
        append_response(f"Failed to start MinePRL container: {err[:160]}")
        return False

    time.sleep(1)
    start_log_follower(container_name)
    return True


def stop_miner(config=None):
    container_name = CONTAINER_NAME
    if isinstance(config, dict):
        container_name = config.get("container_name", CONTAINER_NAME)

    stop_log_follower()

    if has_docker() and container_exists(container_name):
        docker_run(["stop", container_name], timeout=20)


def restart_miner(config):
    container_name = config.get("container_name", CONTAINER_NAME)
    stop_log_follower()

    if has_docker() and container_exists(container_name):
        docker_run(["rm", "-f", container_name], timeout=20)

    time.sleep(0.5)
    return start_miner(config)


def wallet_url(wallet):
    if not wallet:
        return "N/A"
    return f"https://mineprl.com/wallet/{wallet}"


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


def iter_recent_log_lines(max_lines=300):
    if not os.path.exists(MINER_LOG_FILE):
        return []

    try:
        with open(MINER_LOG_FILE, "r", errors="ignore") as f:
            return f.readlines()[-max_lines:]
    except Exception:
        return []


def parse_hashrate():
    text = "".join(iter_recent_log_lines())

    if not text:
        return None

    patterns = [
        r"Hashrate\s+Total\s*[:=]\s*([\d.]+)\s*(TH/s|GH/s|MH/s)",
        r"Total\s+Hashrate\s*[:=]\s*([\d.]+)\s*(TH/s|GH/s|MH/s)",
        r"Reported\s+Hashrate\s*[:=]\s*([\d.]+)\s*(TH/s|GH/s|MH/s)",
        r"hashrate[_ ]?(?:ths|th_s|thps)?[\"']?\s*[:=]\s*([\d.]+)",
    ]

    values = []

    for pattern in patterns[:3]:
        for value, unit in re.findall(pattern, text, re.IGNORECASE):
            try:
                values.append(to_ths(float(value), unit))
            except Exception:
                pass

    # JSON-ish metrics fallback.
    for match in re.findall(patterns[3], text, re.IGNORECASE):
        try:
            values.append(float(match))
        except Exception:
            pass

    if not values:
        return None

    return round(sum(values[-10:]) / len(values[-10:]), 2)


def parse_json_metrics():
    metrics = {}

    for line in iter_recent_log_lines():
        line = line.strip()
        if not line.startswith("{"):
            continue

        try:
            item = json.loads(line)
        except Exception:
            continue

        if isinstance(item, dict):
            if isinstance(item.get("metrics"), dict):
                metrics.update(item["metrics"])

            # Some loggers put metrics at top-level.
            for key in [
                "accepted_shares",
                "rejected_shares",
                "stale_shares",
                "active_worker_count",
                "hashrate_ths",
                "hashrate",
            ]:
                if key in item:
                    metrics[key] = item[key]

    return metrics


def parse_shares():
    metrics = parse_json_metrics()

    for key in ("accepted_shares", "accepted", "shares_accepted"):
        if key in metrics:
            try:
                return int(metrics[key]), True
            except Exception:
                pass

    text = "".join(iter_recent_log_lines()).lower()
    if not text:
        return 0, False

    patterns = [
        "accepted share",
        "share accepted",
        "accepted:",
        "result accepted",
        "block accepted",
    ]

    for pattern in patterns:
        if pattern in text:
            return sum(1 for line in text.splitlines() if pattern in line), True

    return 0, False


def parse_rejects():
    metrics = parse_json_metrics()
    total = 0

    for key in ("rejected_shares", "stale_shares", "rejects", "stales"):
        try:
            total += int(metrics.get(key, 0) or 0)
        except Exception:
            pass

    if total:
        return total

    text = "".join(iter_recent_log_lines()).lower()
    if not text:
        return 0

    return sum(1 for line in text.splitlines() if "reject" in line or "stale" in line)


def build_wallet_info(config):
    metrics = parse_json_metrics()

    return {
        "confirmed": None,
        "unconfirmed": None,
        "transactions": None,
        "last_updated": datetime.now().strftime("%H:%M:%S"),
        "error": None,
        "pool_url": wallet_url(config.get("wallet", "")),
        "accepted_shares": metrics.get("accepted_shares"),
        "active_workers": metrics.get("active_worker_count"),
    }


def handle_commands(config, state):
    should_close = False

    for raw in read_pending_commands():
        cmd = raw.strip().lower()

        if cmd in ("close", "close all", "stop", "stop all", "exit", "shutdown"):
            append_response("Closing MinePRL dashboard...")
            state["last_response"] = "Closing..."
            should_close = True
            continue

        if cmd in ("pause", "pause mine", "pause miner", "stop mine", "stop miner"):
            stop_miner(config)
            append_response("MinePRL container stopped. Type start to resume.")
            state["last_response"] = "Miner paused."
            continue

        if cmd in ("start", "start mine", "start miner", "resume", "resume mine"):
            if start_miner(config):
                append_response("MinePRL container started.")
                state["last_response"] = "Miner started."
            continue

        if cmd in ("restart", "restart mine", "restart miner"):
            if restart_miner(config):
                append_response("MinePRL container restarted.")
                state["last_response"] = "Miner restarted."
            continue

        if cmd in ("status", "state"):
            container_name = config.get("container_name", CONTAINER_NAME)
            response = (
                f"container={container_name}, status={container_status(container_name)}, "
                f"gpu={state['show_gpu']}, mining={state['show_mining']}, "
                f"pool={state['show_pool']}, wallet={state['show_wallet']}"
            )
            append_response(response)
            state["last_response"] = "Status shown."
            continue

        if cmd in ("explorer", "wallet", "wallet link"):
            append_response(wallet_url(config.get("wallet", "")))
            state["last_response"] = "Wallet link shown."
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
    container_name = config.get("container_name", CONTAINER_NAME)
    status = container_status(container_name)

    hashrate = parse_hashrate()
    shares, shares_detected = parse_shares()
    rejects = parse_rejects()
    gpu = get_gpu()

    efficiency = None
    if gpu["power"] > 0 and hashrate is not None:
        efficiency = round(hashrate / gpu["power"], 3)

    return {
        "pool": config.get("pool_name", "MinePRL"),
        "pool_host": "Docker container",
        "wallet": config.get("wallet", ""),
        "worker": config.get("worker", "A"),
        "explorer_url": wallet_url(config.get("wallet", "")),
        "miner_status": status.upper(),
        "container_name": container_name,
        "docker_image": config.get("docker_image", DOCKER_IMAGE),
        "hashrate_ths": hashrate,
        "accepted_shares": shares,
        "shares_detected": shares_detected,
        "rejected_stale": rejects,
        "session_seconds": int(time.time() - start_time),
        "gpu": gpu,
        "efficiency_thw": efficiency,
        "wallet_info": build_wallet_info(config),
        "updated_at": datetime.now().strftime("%H:%M:%S"),
    }


def cleanup_and_exit(config=None):
    if restore_performance_mode:
        restore_performance_mode()
    stop_miner(config)
    ensure_runtime()
    with open(SHUTDOWN_FILE, "w", encoding="utf-8") as f:
        f.write(str(time.time()))


def run():
    ensure_runtime()
    config = load_config()

    # Force MinePRL backend identity even if config was created by dashboard.
    config["pool_name"] = "MinePRL"
    config["pool_host"] = "mineprl-docker"
    config.setdefault("docker_image", DOCKER_IMAGE)
    config.setdefault("container_name", CONTAINER_NAME)

    state = load_cmd_state()
    save_cmd_state(state)

    if not os.path.exists(MINER_LOG_FILE):
        open(MINER_LOG_FILE, "w").close()

    start_miner(config)

    def handle_signal(signum, frame):
        cleanup_and_exit(config)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while True:
        state = load_cmd_state()
        should_close = handle_commands(config, state)

        atomic_write_json(DATA_FILE, build_data(config))

        if should_close:
            cleanup_and_exit(config)
            return

        time.sleep(1)


if __name__ == "__main__":
    if "--write-profile" in sys.argv:
        write_pool_profile()
        sys.exit(0)

    run()

