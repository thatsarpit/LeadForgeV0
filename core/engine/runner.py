import sys
import time
import json
from pathlib import Path
from datetime import datetime

# ----------------------------
# Runner bootstrap
# ----------------------------

if len(sys.argv) < 2:
    print("[RUNNER] ❌ slot_id missing")
    sys.exit(1)

slot_id = sys.argv[1]

BASE = Path(__file__).resolve().parents[2]
SLOT_DIR = BASE / "slots" / slot_id

STATE_FILE = SLOT_DIR / "slot_state.json"
COMMAND_FILE = SLOT_DIR / "command.json"

print(f"[RUNNER] 🚀 Runner started for {slot_id}")

# ----------------------------
# Helpers
# ----------------------------

def load_json(path: Path, default: dict):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception as e:
        print(f"[RUNNER] ⚠️ Failed reading {path.name}: {e}")
        return default


def save_json(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2))


# ----------------------------
# Main loop
# ----------------------------

start_time = time.time()

while True:
    state = load_json(STATE_FILE, {})
    command = load_json(COMMAND_FILE, {})

    # Hard stop if state missing or stopped
    if not state or state.get("status") != "RUNNING":
        print("[RUNNER] 🛑 Slot not running, exiting")
        break

    observer = command.get("observer", True)

    # ----------------------------
    # Update core state
    # ----------------------------

    state["last_heartbeat"] = datetime.utcnow().isoformat()
    state["uptime_seconds"] = int(time.time() - start_time)
    state["busy"] = False

    # ----------------------------
    # Metrics (mock for now)
    # ----------------------------

    metrics = state.get("metrics", {})
    metrics["cpu"] = metrics.get("cpu", 20)
    metrics["memory"] = metrics.get("memory", 512)
    metrics["throughput"] = metrics.get("throughput", 0)

    state["metrics"] = metrics

    # ----------------------------
    # Observer vs Active
    # ----------------------------

    if observer:
        state["mode"] = "OBSERVER"
        print("[RUNNER] 👁 Observer mode — no actions executed")
    else:
        state["mode"] = "ACTIVE"
        # Placeholder for real bot logic
        print("[RUNNER] ⚙️ Active mode — processing workload")
        state["busy"] = True
        metrics["throughput"] += 1

    # ----------------------------
    # Persist state
    # ----------------------------

    save_json(STATE_FILE, state)
    print("[RUNNER] 💓 State + heartbeat updated")

    time.sleep(2)