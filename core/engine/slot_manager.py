import os
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime, timedelta, timezone
import sys
import signal

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SLOTS_DIR = BASE_DIR / "slots"
RUNNER_PATH = BASE_DIR / "core" / "engine" / "runner.py"

HEARTBEAT_TIMEOUT = 30  # seconds
CHECK_INTERVAL = 3      # seconds
# Playwright startup (profile load, tunnel latency, cold browser) can exceed 15s.
# Give the worker time to boot and emit its first heartbeat.
STARTUP_GRACE_SECONDS = 60
DEFAULT_SLOT_WORKER = os.getenv("DEFAULT_SLOT_WORKER", "indiamart_worker")
DEFAULT_SLOT_MODE = os.getenv("DEFAULT_SLOT_MODE", "ACTIVE")
VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python"
DEFAULT_PYTHON = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
PYTHON_BIN = os.getenv("PYTHON_BIN", DEFAULT_PYTHON)

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
    global _log_handles
    print(f"[SLOT_MANAGER] ⚠️ Shutdown signal received ({signum})")
    # Close all open log file handles to prevent descriptor leaks
    for slot_id, handle in list(_log_handles.items()):
        try:
            handle.close()
            print(f"[SLOT_MANAGER] 🔒 Closed log handle for {slot_id}")
        except Exception as e:
            print(f"[SLOT_MANAGER] ⚠️ Error closing handle for {slot_id}: {e}")
    _log_handles.clear()
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
    # Atomic write to avoid truncation races with workers reading the file
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)

def utcnow():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', '')

def is_process_running(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False

def _iter_process_table():
    try:
        out = subprocess.check_output(["ps", "-ax", "-o", "pid=,command="], text=True)
    except Exception:
        return
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except Exception:
            continue
        yield pid, parts[1]

def list_slot_worker_pids(slot_id: str):
    slot_path = str((SLOTS_DIR / slot_id).resolve())
    profile_path = str((BASE_DIR / "browser_profiles" / slot_id).resolve())
    pids = []
    for pid, cmd in _iter_process_table() or []:
        if slot_path in cmd and "core.workers." in cmd:
            pids.append(pid)
            continue
        # Sweep stray chromium instances that still hold the slot profile.
        if profile_path in cmd and ("headless_shell" in cmd or "chromium" in cmd or "chrome" in cmd):
            pids.append(pid)
    return sorted(set(pids))

def kill_slot_processes(slot_id: str, sig=signal.SIGTERM):
    for pid in list_slot_worker_pids(slot_id):
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, sig)
        except Exception:
            pass
        try:
            os.kill(pid, sig)
        except Exception:
            pass

# Track open log handles for cleanup
_log_handles = {}

def start_runner(slot_id):
    global _log_handles
    print(f"[SLOT_MANAGER] ▶ Starting runner for {slot_id}")
    log_path = SLOTS_DIR / slot_id / "runner.log"
    
    # Close any existing handle for this slot to prevent leaks
    if slot_id in _log_handles:
        try:
            _log_handles[slot_id].close()
        except Exception:
            pass
    
    # Ensure directory exists
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Open with line buffering for immediate visibility
    f = open(log_path, "a", buffering=1)
    _log_handles[slot_id] = f
    
    proc = subprocess.Popen(
        [PYTHON_BIN, str(RUNNER_PATH), slot_id],
        stdout=f,
        stderr=f,
        start_new_session=True
    )
    return proc.pid

def stop_runner(pid, slot_id, timeout=5):
    """Attempt graceful stop (process + group), then force kill."""
    if not pid:
        return
    # Try to stop the whole process group first (worker + browser children)
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
    except Exception:
        pass
    # Also try direct PID signal
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        pass
    # If pid is a runner, kill its children too
    try:
        subprocess.run(["pkill", "-TERM", "-P", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    # Also sweep any orphaned workers/browsers still running for this slot.
    kill_slot_processes(slot_id, sig=signal.SIGTERM)
    # If runner PID differs from worker PID in state, stop that group too.
    try:
        state_file = SLOTS_DIR / slot_id / "slot_state.json"
        state = load_json(state_file, {})
        worker_pid = state.get("pid")
        if worker_pid and worker_pid != pid:
            try:
                os.killpg(os.getpgid(worker_pid), signal.SIGTERM)
            except Exception:
                pass
            try:
                os.kill(worker_pid, signal.SIGTERM)
            except Exception:
                pass
    except Exception:
        pass
    waited = 0
    while waited < timeout:
        if not is_process_running(pid):
            print(f"[SLOT_MANAGER] ⛔ Stopped runner for {slot_id}")
            return
        time.sleep(0.5)
        waited += 0.5
    # Force kill process group and pid
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGKILL)
    except Exception:
        pass
    try:
        os.kill(pid, signal.SIGKILL)
        print(f"[SLOT_MANAGER] ⛔ Force-killed runner for {slot_id}")
    except Exception:
        pass
    try:
        subprocess.run(["pkill", "-KILL", "-P", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    kill_slot_processes(slot_id, sig=signal.SIGKILL)
    # Force kill worker pid if it diverged
    try:
        state_file = SLOTS_DIR / slot_id / "slot_state.json"
        state = load_json(state_file, {})
        worker_pid = state.get("pid")
        if worker_pid and worker_pid != pid:
            try:
                os.killpg(os.getpgid(worker_pid), signal.SIGKILL)
            except Exception:
                pass
            try:
                os.kill(worker_pid, signal.SIGKILL)
            except Exception:
                pass
    except Exception:
        pass

def within_startup_grace(state):
    started_at = state.get("started_at")
    if not started_at:
        return False
    try:
        started_ts = datetime.fromisoformat(started_at)
        # Make timezone-aware if needed
        if started_ts.tzinfo is None:
            started_ts = started_ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - started_ts) < timedelta(seconds=STARTUP_GRACE_SECONDS)
    except Exception:
        return True

def ensure_state_defaults(state, slot_id):
    changed = False
    if not state.get("slot_id"):
        state["slot_id"] = slot_id
        changed = True
    if not state.get("worker"):
        state["worker"] = DEFAULT_SLOT_WORKER
        changed = True
    if not state.get("mode"):
        state["mode"] = DEFAULT_SLOT_MODE
        changed = True
    if "status" not in state:
        state["status"] = "STOPPED"
        changed = True
    if "busy" not in state:
        state["busy"] = False
        changed = True
    if "pid" not in state:
        state["pid"] = None
        changed = True
    if "auto_resume" not in state:
        state["auto_resume"] = False
        changed = True
    if "command" not in state:
        state["command"] = None
        changed = True
    if "uptime_seconds" not in state:
        state["uptime_seconds"] = 0
        changed = True
    if "last_heartbeat" not in state:
        state["last_heartbeat"] = None
        changed = True
    metrics = state.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
        changed = True
    if "last_exit_code" not in state:
        state["last_exit_code"] = None
    defaults = {
        "cpu": 0,
        "memory": 0,
        "throughput": 0,
        "pages_fetched": 0,
        "leads_parsed": 0,
        "errors": 0,
        "last_error": None,
        "error_rate": 0,
        "last_action": "BOOT",
        "phase": "BOOT",
        "phase_started_at": None,
        "phase_duration_sec": 0,
    }
    for key, value in defaults.items():
        if key not in metrics:
            metrics[key] = value
            changed = True
    state["metrics"] = metrics
    return changed

# ---------------- Main Loop ---------------- #

while True:
    try:
        if not SLOTS_DIR.exists():
            time.sleep(CHECK_INTERVAL)
            continue

        for slot_dir in SLOTS_DIR.iterdir():
            if not slot_dir.is_dir():
                continue
            if slot_dir.name.startswith(".") or slot_dir.name.startswith("_"):
                continue

            slot_id = slot_dir.name
            state_file = slot_dir / "slot_state.json"

            # ---- Ensure slot_state.json exists ----
            if not state_file.exists():
                save_json(state_file, {
                    "slot_id": slot_id,
                    "status": "STOPPED",
                    "mode": DEFAULT_SLOT_MODE,
                    "worker": DEFAULT_SLOT_WORKER,
                    "busy": False,
                    "pid": None,
                    "auto_resume": False,
                    "command": None,
                    "uptime_seconds": 0,
                    "last_heartbeat": None,
                    "metrics": {
                        "cpu": 0,
                        "memory": 0,
                        "throughput": 0,
                        "pages_fetched": 0,
                        "leads_parsed": 0,
                        "errors": 0,
                        "last_error": None,
                        "error_rate": 0,
                        "last_action": "BOOT",
                        "phase": "BOOT",
                        "phase_started_at": None,
                        "phase_duration_sec": 0
                    }
                })

            state = load_json(state_file, {})
            if ensure_state_defaults(state, slot_id):
                save_json(state_file, state)

            pid = state.get("pid")
            status = state.get("status")
            command = state.get("command")
            auto_resume = state.get("auto_resume", False)
            mode = state.get("mode", "OBSERVER")
            last_hb = state.get("last_heartbeat")

            # ---------------- TRUTH ENFORCEMENT ---------------- #

            # If slot is stopped/paused/dead, ensure no stray runner is still alive.
            if status in ("STOPPED", "PAUSED", "DEAD"):
                # Always sweep any orphaned workers/browsers even if pid is missing.
                # This prevents slow-start + heartbeat timeouts due to locked profiles.
                kill_slot_processes(slot_id, sig=signal.SIGTERM)
                kill_slot_processes(slot_id, sig=signal.SIGKILL)
                if pid:
                    if is_process_running(pid):
                        print(f"[SLOT_MANAGER] 🧹 {slot_id} is {status} but PID {pid} is alive — stopping stray process")
                        stop_runner(pid, slot_id)
                    # Always clear stale pid + heartbeat for non-running states
                    state.update({
                        "pid": None,
                        "busy": False,
                        "last_heartbeat": None,
                    })
                    save_json(state_file, state)
                # Continue to command handling (may restart)

            if status in ("RUNNING", "STARTING", "STOPPING"):
                # --- STARTUP GRACE WINDOW ---
                if within_startup_grace(state):
                    save_json(state_file, state)
                    continue

                # --- PID CHECK ---
                # If command is START or status is STARTING, we are about to start it
                if command == "START" or status == "STARTING":
                    pass
                elif not pid or not is_process_running(pid):
                    print(f"[SLOT_MANAGER] ❌ Dead/Missing PID for {slot_id} in {status}, marking STOPPED")
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
                # (Same logic as before)
                if not last_hb:
                    # allow missing heartbeat AFTER grace? strictness check
                    if status == "RUNNING":
                        # If running and NO heartbeat after grace -> Mark as DEAD and stop process
                        print(f"[SLOT_MANAGER] 💀 No heartbeat for running slot {slot_id}, stopping")
                        if is_process_running(pid):
                            stop_runner(pid, slot_id)
                        state.update({
                            "status": "DEAD",
                            "busy": False,
                            "pid": None,
                            "stop_reason": "no_heartbeat",
                            "stopped_at": utcnow()
                        })
                        save_json(state_file, state)
                        continue
                    # For STARTING/STOPPING without heartbeat, allow command handling to proceed

                if last_hb:
                    try:
                        last = datetime.fromisoformat(last_hb)
                        # Make timezone-aware if needed
                        if last.tzinfo is None:
                            last = last.replace(tzinfo=timezone.utc)
                        if datetime.now(timezone.utc) - last > timedelta(seconds=HEARTBEAT_TIMEOUT):
                            print(f"[SLOT_MANAGER] 💀 Heartbeat timeout for {slot_id}")
                            if is_process_running(pid):
                                stop_runner(pid, slot_id)
                            state.update({
                                "status": "DEAD",
                                "pid": None,
                                "busy": False,
                                "last_heartbeat": None,
                                "stop_reason": "heartbeat_timeout",
                                "stopped_at": utcnow(),
                                "command": None
                            })
                            save_json(state_file, state)
                            continue
                    except Exception:
                        save_json(state_file, state)
                        continue

            # ---------------- COMMAND HANDLING ---------------- #

            # Treat STARTING state (without PID) as implicit START command
            # This fixes cases where API sets status but not command
            force_start = (status == "STARTING" and not is_process_running(pid))
            
            if command == "START" or force_start:
                if mode == "OBSERVER":
                    print(f"[SLOT_MANAGER] 👁️ Observer mode — cannot start {slot_id}")
                    state["command"] = None
                else:
                    # Ensure a clean slate before starting (avoid profile locks / orphan workers).
                    if pid and is_process_running(pid):
                        stop_runner(pid, slot_id)
                    kill_slot_processes(slot_id, sig=signal.SIGTERM)
                    kill_slot_processes(slot_id, sig=signal.SIGKILL)
                    if not is_process_running(pid):
                        state["pid"] = start_runner(slot_id)
                    state.update({
                        "status": "RUNNING",
                        "started_at": utcnow(),
                        # Seed heartbeat so we don't immediately mark DEAD while Playwright boots.
                        "last_heartbeat": utcnow(),
                        "busy": True,
                        "command": None
                    })

            elif command == "PAUSE":
                if is_process_running(pid):
                    stop_runner(pid, slot_id)
                state.update({
                    "status": "PAUSED",
                    "pid": None,
                    "busy": False,
                    "last_heartbeat": None,
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
