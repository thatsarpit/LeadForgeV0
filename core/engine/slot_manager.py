import os
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SLOTS_DIR = BASE_DIR / "slots"
RUNNER_PATH = BASE_DIR / "core" / "engine" / "runner.py"

HEARTBEAT_TIMEOUT = 15  # seconds
CHECK_INTERVAL = 3      # seconds

print("[SLOT_MANAGER] ✅ Slot Manager started")
print("[SLOT_MANAGER] Watching slots with command + heartbeat enforcement...")

# ---------------- Utilities ---------------- #

def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default.copy()

def save_json(path, data):
    path.write_text(json.dumps(data, indent=2))

def utcnow():
    return datetime.utcnow().isoformat()

def is_process_running(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False

def start_runner(slot_id):
    print(f"[SLOT_MANAGER] ▶ Starting runner for {slot_id}")
    proc = subprocess.Popen(
        ["python3", str(RUNNER_PATH), slot_id],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return proc.pid

def stop_runner(pid, slot_id):
    try:
        os.kill(pid, 9)
        print(f"[SLOT_MANAGER] ⛔ Stopped runner for {slot_id}")
    except Exception:
        pass

# ---------------- Main Loop ---------------- #

while True:
    if not SLOTS_DIR.exists():
        time.sleep(CHECK_INTERVAL)
        continue

    for slot_dir in SLOTS_DIR.iterdir():
        if not slot_dir.is_dir():
            continue
        if slot_dir.name.startswith("."):
            continue

        slot_id = slot_dir.name
        state_file = slot_dir / "slot_state.json"

        # ---- Ensure slot_state.json exists ----
        if not state_file.exists():
            save_json(state_file, {
                "slot_id": slot_id,
                "status": "STOPPED",
                "mode": "OBSERVER",
                "busy": False,
                "pid": None,
                "auto_resume": False,
                "command": None,
                "uptime_seconds": 0,
                "last_heartbeat": None,
                "metrics": {
                    "cpu": 0,
                    "memory": 0,
                    "throughput": 0
                }
            })

        state = load_json(state_file, {})

        pid = state.get("pid")
        status = state.get("status")
        command = state.get("command")
        auto_resume = state.get("auto_resume", False)
        mode = state.get("mode", "OBSERVER")
        last_hb = state.get("last_heartbeat")

        # ---------------- COMMAND HANDLING ---------------- #

        if command == "START":
            if mode == "OBSERVER":
                print(f"[SLOT_MANAGER] 👁️ Observer mode — cannot start {slot_id}")
                state["command"] = None
            else:
                if not is_process_running(pid):
                    state["pid"] = start_runner(slot_id)
                state["status"] = "RUNNING"
                state["command"] = None

        elif command == "PAUSE":
            if is_process_running(pid):
                stop_runner(pid, slot_id)
            state.update({
                "status": "PAUSED",
                "pid": None,
                "command": None
            })

        elif command == "STOP":
            if is_process_running(pid):
                stop_runner(pid, slot_id)
            state.update({
                "status": "STOPPED",
                "pid": None,
                "auto_resume": False,
                "command": None
            })

        # ---------------- HEARTBEAT ENFORCEMENT ---------------- #

        if (
            status == "RUNNING"
            and mode == "ACTIVE"
            and auto_resume
            and last_hb
        ):
            try:
                last = datetime.fromisoformat(last_hb)
                if datetime.utcnow() - last > timedelta(seconds=HEARTBEAT_TIMEOUT):
                    print(f"[SLOT_MANAGER] 💀 Heartbeat missed for {slot_id}")
                    if is_process_running(pid):
                        stop_runner(pid, slot_id)
                    state["pid"] = start_runner(slot_id)
                    state["last_heartbeat"] = utcnow()
            except Exception:
                pass

        save_json(state_file, state)

    time.sleep(CHECK_INTERVAL)