import time
import sys
import os
import signal
from datetime import datetime

# -------- CONFIG --------
HEARTBEAT_SECONDS = 3
SLOT_NAME = os.path.basename(os.path.dirname(__file__))
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
LOG_DIR = os.path.join(BASE_DIR, "logs", SLOT_NAME)
LOG_FILE = os.path.join(LOG_DIR, "runner.log")

os.makedirs(LOG_DIR, exist_ok=True)

RUNNING = True


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{SLOT_NAME}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def shutdown_handler(signum, frame):
    global RUNNING
    log(f"🛑 Shutdown signal received ({signum}). Cleaning up…")
    RUNNING = False


signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)


def main():
    log("🧠 Slot runner booting")
    log(f"📂 Base dir: {BASE_DIR}")
    log("🔐 Observer mode: ENABLED")
    log("⏳ Waiting for dashboard / account login…")

    counter = 0

    while RUNNING:
        counter += 1
        log(f"💓 Heartbeat #{counter} — slot alive and healthy")
        time.sleep(HEARTBEAT_SECONDS)

    log("✅ Slot runner exited cleanly")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"❌ FATAL ERROR: {e}")
        sys.exit(1)