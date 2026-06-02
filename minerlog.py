import os
import time
import subprocess
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(SCRIPT_DIR, "runtime")
MINER_LOG_FILE = os.path.join(RUNTIME_DIR, "miner.log")


def ensure_runtime():
    os.makedirs(RUNTIME_DIR, exist_ok=True)


def run():
    ensure_runtime()
    os.system("clear")

    print("=" * 56)
    print(" MON-MINER LOG")
    print("=" * 56)
    print("[INFO] Log pane only. Use the bottom-right console pane for commands.")
    print("")

    if not os.path.exists(MINER_LOG_FILE):
        open(MINER_LOG_FILE, "w").close()

    try:
        process = subprocess.Popen(
            ["tail", "-n", "40", "-f", MINER_LOG_FILE],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

        while True:
            line = process.stdout.readline()
            if not line:
                if process.poll() is not None:
                    return
                time.sleep(0.1)
                continue

            lower = line.lower()
            if any(k in lower for k in [
                "accepted", "share", "sol:", "block", "job",
                "found", "submit", "result", "reject", "stale",
                "hashrate", "loaded new job", "received new job",
            ]):
                print(f"{datetime.now().strftime('[%H:%M:%S]')} {line.strip()}")

    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    run()
