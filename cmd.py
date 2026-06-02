import os
import re
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(SCRIPT_DIR, "runtime")
CMD_QUEUE_FILE = os.path.join(RUNTIME_DIR, "cmd_queue.txt")
CMD_RESPONSE_FILE = os.path.join(RUNTIME_DIR, "cmd_response.txt")


def ensure_runtime():
    os.makedirs(RUNTIME_DIR, exist_ok=True)


def normalize_command(command):
    raw = (command or "").strip().lower()
    raw = re.sub(r"\s+", " ", raw)

    if not raw:
        return ""

    known = [
        "show mining", "hide mining", "toggle mining",
        "show wallet", "hide wallet", "toggle wallet",
        "show pool", "hide pool", "toggle pool",
        "show gpu", "hide gpu", "toggle gpu",
        "show all", "hide all", "toggle all",
        "telemetry on", "telemetry off",
        "perf on", "perf off",
        "pause mine", "pause miner",
        "stop mine", "stop miner",
        "start mine", "start miner",
        "resume mine",
        "restart mine", "restart miner",
        "wallet link",
        "explorer",
        "wallet",
        "pause",
        "start",
        "resume",
        "restart",
        "status",
        "state",
        "close all",
        "close",
        "stop",
        "exit",
        "clear",
    ]

    if raw in known:
        return raw

    best_pos = None
    best_cmd = None

    for cmd in known:
        pos = raw.find(cmd)
        if pos >= 0 and (best_pos is None or pos < best_pos or (pos == best_pos and len(cmd) > len(best_cmd))):
            best_pos = pos
            best_cmd = cmd

    return best_cmd or raw


def append_command(command):
    ensure_runtime()
    command = normalize_command(command)
    if not command:
        return ""

    with open(CMD_QUEUE_FILE, "a", encoding="utf-8") as f:
        f.write(command + "\n")

    return command


def read_responses():
    ensure_runtime()

    if not os.path.exists(CMD_RESPONSE_FILE):
        return []

    try:
        with open(CMD_RESPONSE_FILE, "r", encoding="utf-8", errors="ignore") as f:
            lines = [line.strip() for line in f if line.strip()]
        open(CMD_RESPONSE_FILE, "w").close()
        return lines
    except Exception:
        return []


def fit_text(value, max_len=52):
    value = str(value)
    if len(value) <= max_len:
        return value
    return value[:max_len - 3] + "..."


def print_console_help():
    print("=" * 56)
    print(" MON-MINER COMMAND CONSOLE")
    print("=" * 56)
    print("Miner     : pause | start | restart | status")
    print("Close     : close")
    print("Telemetry : show gpu | hide gpu | toggle gpu")
    print("            show wallet | hide wallet | show all | hide all")
    print("Wallet    : explorer")
    print("Perf      : perf on | perf off")
    print("Other     : clear")
    print("=" * 56)


def draw(last_message="Ready."):
    os.system("clear")
    print_console_help()

    msg = str(last_message)
    if msg.startswith("http://") or msg.startswith("https://"):
        print("[LINK]")
        if "/wallet/" in msg:
            wallet = msg.split("/wallet/", 1)[1]
            print("Open:")
            print("  https://mineprl.com/wallet/<wallet>")
            print("Wallet:")
            print(f"  {wallet}")
        elif "/address/" in msg:
            wallet = msg.split("/address/", 1)[1].split("?", 1)[0]
            print("Open:")
            print("  https://explorer.pearlresearch.ai/address/<wallet>?network=mainnet")
            print("Wallet:")
            print(f"  {wallet}")
        else:
            print(msg)
    else:
        print(f"[INFO] {fit_text(msg)}")

    print("")


def run():
    ensure_runtime()
    last_message = "Command console only. Logs are shown above."
    draw(last_message)

    while True:
        try:
            command = input("cmd> ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return

        normalized = normalize_command(command)

        if not normalized:
            draw(last_message)
            continue

        if normalized in ("clear", "cls"):
            last_message = "Console cleared."
            draw(last_message)
            continue

        sent = append_command(normalized)

        time.sleep(0.35)
        responses = read_responses()

        if responses:
            last_message = " | ".join(responses[-3:])
        else:
            last_message = f"sent: {sent}"

        draw(last_message)


if __name__ == "__main__":
    run()

