import os
import sys
import json
import time
import shlex
import subprocess
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(SCRIPT_DIR, "runtime")

CONFIG_FILE = os.path.join(RUNTIME_DIR, "config.json")
DATA_FILE = os.path.join(RUNTIME_DIR, "current_data.json")
CMD_STATE_FILE = os.path.join(RUNTIME_DIR, "cmd_state.json")
SHUTDOWN_FILE = os.path.join(RUNTIME_DIR, "shutdown.flag")
POOL_PROFILE_FILE = os.path.join(RUNTIME_DIR, "pool_profile.json")
WALLETS_FILE = os.path.join(SCRIPT_DIR, "wallets.json")

DEFAULT_POOL_HOST = "129.226.55.135:9000"


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


def default_cmd_state():
    return {
        "show_gpu": True,
        "show_mining": True,
        "show_pool": True,
        "show_wallet": True,
        "last_response": "Ready.",
    }


def fit_text(value, max_len=76):
    value = str(value)
    if len(value) <= max_len:
        return value
    return value[:max_len - 3] + "..."


def draw_line():
    print("=" * 80)


def clear():
    sys.stdout.write("\033[H")
    sys.stdout.flush()


def clear_to_end():
    sys.stdout.write("\033[J")
    sys.stdout.flush()


def hide_cursor():
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()


def show_cursor():
    sys.stdout.write("\033[?25h")
    sys.stdout.flush()


def load_pool_profile():
    # Ask the selected pool data backend to write its profile first.
    # If this fails, dashboard falls back to a simple custom-host setup.
    backend = os.path.join(SCRIPT_DIR, "pearlhash_data.py")
    try:
        subprocess.run(
            ["python3", backend, "--write-profile"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass

    default = {
        "pool_name": "PearlHash",
        "default_pool_host": DEFAULT_POOL_HOST,
        "pool_options": [],
    }

    return read_json(POOL_PROFILE_FILE, default)


def choose_pool_host(profile):
    pool_name = profile.get("pool_name", "Pool")
    default_host = profile.get("default_pool_host", DEFAULT_POOL_HOST)
    options = profile.get("pool_options") or []

    print("\n[STEP 1] Pool host")

    if options:
        print(f"  {pool_name} provides multiple pool endpoints:")
        for idx, item in enumerate(options, start=1):
            name = item.get("name", f"Option {idx}")
            host = item.get("host", "")
            desc = item.get("description", "")
            extra = f" - {desc}" if desc else ""
            print(f"  ({idx}) {name:<10}: {host}{extra}")

        print("  (C) Custom host")
        choice = input(f"\nChoose pool option [1-{len(options)}] (Default: 1): ").strip().lower()

        if choice in ("c", "custom"):
            custom = input(f"-> Custom pool host [{default_host}]: ").strip()
            return custom or default_host

        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(options):
                return options[idx - 1].get("host") or default_host

        return options[0].get("host") or default_host

    print("  This pool has no region selection.")
    print("  Press Enter to use default, or paste a custom host.")
    return input(f"-> Pool host [{default_host}]: ").strip() or default_host


def load_wallets():
    data = read_json(WALLETS_FILE, [])

    # Backward compatibility if someone manually writes {"wallets": [...]}
    if isinstance(data, dict):
        data = data.get("wallets", [])

    if not isinstance(data, list):
        return []

    cleaned = []
    seen = set()

    for item in data:
        if not isinstance(item, dict):
            continue

        address = str(item.get("address", "")).strip()
        name = str(item.get("name", "")).strip() or "Unnamed"

        if not address or address in seen:
            continue

        cleaned.append({"name": name, "address": address})
        seen.add(address)

    return cleaned


def save_wallets(wallets):
    atomic_write_json(WALLETS_FILE, wallets)


def short_wallet(address):
    if len(address) > 36:
        return address[:20] + "..." + address[-10:]
    return address


def choose_wallet():
    wallets = load_wallets()

    print("\n[STEP 2] Wallet address")

    if wallets:
        print("  Saved wallets:")
        for idx, item in enumerate(wallets, start=1):
            print(f"  ({idx}) {item['name']:<18}: {short_wallet(item['address'])}")

        print("  (N) New wallet")
        choice = input("\nChoose wallet number or N for new wallet: ").strip().lower()

        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(wallets):
                return wallets[idx - 1]["address"]

        if choice not in ("n", "new", ""):
            print("  Invalid selection. Creating a new wallet entry.")

    while True:
        wallet = input("-> Paste Pearl wallet address: ").strip()
        if wallet:
            break
        print("   [ERROR] Wallet address cannot be empty.")

    save_choice = input("-> Save this wallet for later? (y/N): ").strip().lower()
    if save_choice == "y":
        default_name = f"Wallet {len(wallets) + 1}"
        name = input(f"-> Wallet name [{default_name}]: ").strip() or default_name

        # Update existing entry if address already exists.
        updated = False
        for item in wallets:
            if item["address"] == wallet:
                item["name"] = name
                updated = True
                break

        if not updated:
            wallets.append({"name": name, "address": wallet})

        save_wallets(wallets)
        print("  [OK] Wallet saved.")

    return wallet


def run_setup():
    ensure_runtime()
    os.system("clear")

    print("=" * 80)
    print(" PEARLHASH MONITORED MINER - INITIAL SETUP")
    print("=" * 80)

    profile = load_pool_profile()
    pool_host = choose_pool_host(profile)
    wallet = choose_wallet()

    print("\n[STEP 3] Worker name")
    worker = input("-> Worker name [A]: ").strip() or "A"

    config = {
        "pool_name": profile.get("pool_name", "PearlHash"),
        "pool_host": pool_host,
        "wallet": wallet,
        "worker": worker,
        "miner_exec": "./pearl-miner",
    }

    atomic_write_json(CONFIG_FILE, config)
    atomic_write_json(CMD_STATE_FILE, default_cmd_state())

    if os.path.exists(SHUTDOWN_FILE):
        os.remove(SHUTDOWN_FILE)

    print("\n" + "=" * 80)
    print("[INFO] Configuration ready:")
    print(f"  Pool   : {pool_host}")
    print(f"  Worker : {worker}")
    print(f"  Wallet : {short_wallet(wallet)}")
    print("=" * 80)
    time.sleep(1)


def is_inside_tmux():
    return bool(os.environ.get("TMUX"))


def launch_tmux():
    if is_inside_tmux():
        return

    run_setup()

    data_script = shlex.quote(os.path.join(SCRIPT_DIR, "pearlhash_data.py"))
    ui_script = shlex.quote(os.path.join(SCRIPT_DIR, "dashboard.py"))
    log_script = shlex.quote(os.path.join(SCRIPT_DIR, "minerlog.py"))
    console_script = shlex.quote(os.path.join(SCRIPT_DIR, "cmd.py"))

    # Run the data backend in the background, then keep the visible pane as UI.
    # This avoids creating a useless extra tmux pane for pearlhash_data.py.
    master_cmd = f"python3 {data_script} & python3 {ui_script} --ui"
    log_cmd = f"python3 {log_script}"
    console_cmd = f"python3 {console_script}"

    session_name = f"pearlhash_{int(time.time())}"

    try:
        subprocess.run(["tmux", "new-session", "-d", "-s", session_name, master_cmd], check=True)
        subprocess.run(["tmux", "set-option", "-t", session_name, "status", "off"], check=False)

        # Right side: live miner log.
        subprocess.run(["tmux", "split-window", "-h", "-t", session_name, log_cmd], check=True)

        # Bottom-right: command console.
        subprocess.run(["tmux", "split-window", "-v", "-t", f"{session_name}:0.1", console_cmd], check=True)

        # Give dashboard more width and keep command console compact.
        subprocess.run(["tmux", "resize-pane", "-R", "-t", f"{session_name}:0.0", "18"], check=False)
        subprocess.run(["tmux", "resize-pane", "-D", "-t", f"{session_name}:0.2", "8"], check=False)

        subprocess.run(["tmux", "attach-session", "-t", session_name], check=True)
    except subprocess.CalledProcessError as e:
        print(f"[FATAL ERROR] Failed to launch tmux environment: {e}")
        sys.exit(1)

    sys.exit(0)


def format_session(seconds):
    seconds = int(seconds or 0)
    return f"{seconds//3600:02d}h {(seconds%3600)//60:02d}m {seconds%60:02d}s"


def display_gpu(data):
    gpu = data.get("gpu", {})
    print("GPU DEVICE STATUS")
    draw_line()
    print(f"Model          : {gpu.get('name', 'N/A')}")
    print(f"GPU Load       : {gpu.get('load', 0):>6}%")
    print(f"Temperature    : {gpu.get('temp', 0):>6} °C")
    print(f"Power Draw     : {gpu.get('power', 0):>6} W")
    print(f"VRAM Usage     : {gpu.get('mem_used', '0')} / {gpu.get('mem_total', '0')} MB")
    print(f"Fan Speed      : {gpu.get('fan', '0'):>6}%")

    eff = data.get("efficiency_thw")
    print(f"Efficiency     : {eff:>6} TH/W" if eff is not None else "Efficiency     :     -- TH/W")
    draw_line()


def display_mining(data):
    print("MINING PERFORMANCE")
    draw_line()

    hashrate = data.get("hashrate_ths")
    print(f"Current Hashrate : {hashrate} TH/s" if hashrate is not None else "Current Hashrate : -- TH/s")

    if data.get("shares_detected"):
        print(f"Accepted Shares  : {data.get('accepted_shares', 0):>6} shares")

    print(f"Session Duration : {format_session(data.get('session_seconds', 0))}")
    draw_line()


def display_pool(data):
    print("MINING POOL CONNECTION")
    draw_line()
    print(f"Pool           : {data.get('pool', 'PearlHash')}")
    print(f"Host Address   : {data.get('pool_host', '--')}")
    print(f"Worker         : {data.get('worker', '--')}")
    print(f"Miner Status   : {data.get('miner_status', 'UNKNOWN')}")
    draw_line()


def display_wallet(data):
    print("PAYOUT / WALLET INFO")
    draw_line()

    wallet = data.get("wallet", "")
    addr_display = wallet[:20] + "..." + wallet[-10:] if len(wallet) > 36 else wallet

    print(f"Address        : {addr_display}")
    print("Explorer       : type explorer in console")
    print("Mode           : Explorer on-chain balance")

    wallet_info = data.get("wallet_info", {})
    confirmed = wallet_info.get("confirmed")
    unconfirmed = wallet_info.get("unconfirmed")
    transactions = wallet_info.get("transactions")
    last_updated = wallet_info.get("last_updated")
    error = wallet_info.get("error")

    print(f"Confirmed      : {confirmed:>20.8f} PRL" if confirmed is not None else "Confirmed      : --")

    if unconfirmed is not None:
        print(f"Unconfirmed    : {unconfirmed:>20.8f} PRL")

    if transactions is not None:
        print(f"Transactions   : {transactions}")

    if last_updated:
        print(f"Last Updated   : {last_updated}")

    if error:
        print(f"[WARN] Explorer: {fit_text(error, 60)}")

    draw_line()


def run_ui():
    hide_cursor()

    try:
        while True:
            if os.path.exists(SHUTDOWN_FILE):
                show_cursor()
                subprocess.Popen(["tmux", "kill-server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return

            data = read_json(DATA_FILE, {})
            state = read_json(CMD_STATE_FILE, default_cmd_state())

            clear()

            print("PEARLHASH AUTOMATED ONE-CLICK MONITOR")
            print("SYSTEM TIME:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            draw_line()

            if state.get("show_gpu", True):
                display_gpu(data)
            if state.get("show_mining", True):
                display_mining(data)
            if state.get("show_pool", True):
                display_pool(data)
            if state.get("show_wallet", True):
                display_wallet(data)

            clear_to_end()
            time.sleep(1)

    finally:
        show_cursor()


if __name__ == "__main__":
    if "--ui" in sys.argv:
        run_ui()
    else:
        try:
            subprocess.run(["tmux", "-V"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except Exception:
            print("[ERROR] tmux is required. Run: sudo apt install tmux")
            sys.exit(1)

        launch_tmux()

