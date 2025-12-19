import os
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
import sys
import signal

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SLOTS_DIR = BASE_DIR / "slots"
RUNNER_PATH = BASE_DIR / "core" / "engine" / "runner.py"

HEARTBEAT_TIMEOUT = 30  # seconds
CHECK_INTERVAL = 3      # seconds
STARTUP_GRACE_SECONDS = 15

PID_FILE = BASE_DIR / "runtime" / "slot_manager.pid"
PID_FILE.parent.mkdir(exist_ok=True)

def acquire_pid_lock():
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text())
            os.kill(old_pid, 0)
            print(f"[SLOT_MANAGER] ❌ Already running (PID {old_pid})")
            sys.exit(1)
        except OSError:
            print("[SLOT_MANAGER] ⚠️ Stale PID lock detected, recovering...")
            PID_FILE.unlink()
    PID_FILE.write_text(str(os.getpid()))
    print(f"[SLOT_MANAGER] 🔒 PID lock acquired ({os.getpid()})")

def release_pid_lock():
    if PID_FILE.exists():
        PID_FILE.unlink()
        print("[SLOT_MANAGER] 🔓 PID lock released")

def handle_shutdown(signum, frame):
    print(f"[SLOT_MANAGER] ⚠️ Shutdown signal received ({signum})")
    release_pid_lock()
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)

acquire_pid_lock()
print("[SLOT_MANAGER] ✅ Slot Manager stabilized and running")

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

def within_startup_grace(state):
    started_at = state.get("started_at")
    if not started_at:
        return False
    try:
        started_ts = datetime.fromisoformat(started_at)
        return (datetime.utcnow() - started_ts) < timedelta(seconds=STARTUP_GRACE_SECONDS)
    except Exception:
        return True

# ---------------- Main Loop ---------------- #

while True:
    try:
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

            # ---------------- TRUTH ENFORCEMENT ---------------- #

            if status == "RUNNING":
                # --- STARTUP GRACE WINDOW ---
                if within_startup_grace(state):
                    save_json(state_file, state)
                    continue

                # --- PID CHECK ---
                if pid and not is_process_running(pid):
                    print(f"[SLOT_MANAGER] ❌ Dead PID detected for {slot_id}, marking STOPPED")
                    state.update({
                        "status": "STOPPED",
                        "pid": None,
                        "busy": False,
                        "last_heartbeat": None,
                        "command": None
                    })
                    save_json(state_file, state)
                    continue

                # --- HEARTBEAT CHECK ---
                if not last_hb:
                    # allow missing heartbeat AFTER grace, but do not kill immediately
                    save_json(state_file, state)
                    continue

                try:
                    last = datetime.fromisoformat(last_hb)
                    if datetime.utcnow() - last > timedelta(seconds=HEARTBEAT_TIMEOUT):
                        print(f"[SLOT_MANAGER] 💀 Heartbeat timeout for {slot_id}")
                        if is_process_running(pid):
                            stop_runner(pid, slot_id)
                        state.update({
                            "status": "STOPPED",
                            "pid": None,
                            "busy": False,
                            "last_heartbeat": None,
                            "command": None
                        })
                        save_json(state_file, state)
                        continue
                except Exception:
                    save_json(state_file, state)
                    continue

            # ---------------- COMMAND HANDLING ---------------- #

            if command == "START":
                if mode == "OBSERVER":
                    print(f"[SLOT_MANAGER] 👁️ Observer mode — cannot start {slot_id}")
                    state["command"] = None
                else:
                    if not is_process_running(pid):
                        state["pid"] = start_runner(slot_id)
                    state.update({
                        "status": "RUNNING",
                        "started_at": utcnow(),
                        "last_heartbeat": None,
                        "busy": True,
                        "command": None
                    })

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


            save_json(state_file, state)

        time.sleep(CHECK_INTERVAL)
    except Exception as e:
        print("[SLOT_MANAGER] 💥 CRASH RECOVERED")
        print(e)
        time.sleep(3)