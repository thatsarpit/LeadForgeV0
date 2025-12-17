import time
import os
from datetime import datetime

SLOT_NAME = "slot_001"

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{SLOT_NAME}] {msg}")

if __name__ == "__main__":
    log("🟢 Runner started")

    try:
        while True:
            log("👁️ Observer heartbeat (no actions)")
            time.sleep(5)
    except KeyboardInterrupt:
        log("🛑 Runner stopped manually")