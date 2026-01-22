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
STARTUP_GRACE_SECONDS = 15
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
            
            # In Docker, we are likely PID 1. If the lock says PID 1, it's from a previous crashed crash run.
            if old_pid == os.getpid():
                print(f"[SLOT_MANAGER] ⚠️ Stale PID lock detected (Self-PID collision {old_pid}), recovering...")
                PID_FILE.unlink()
            else:
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
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)

# In Docker, each container runs exactly one slot_manager
# PID locks are unnecessary and can cause issues on restart
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
    """Atomic write to prevent corruption from concurrent access"""
    import tempfile
    import os
    
    # Write to temp file in same directory (ensures same filesystem for atomic rename)
    temp_fd, temp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp"
    )
    
    try:
        with os.fdopen(temp_fd, 'w') as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())  # Ensure data is written to disk
        
        # Atomic rename (on POSIX systems)
        os.replace(temp_path, path)
    except Exception:
        # Clean up temp file on error
        try:
            os.unlink(temp_path)
        except Exception:
            pass
        raise

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

# Track open log handles for cleanup
_log_handles = {}

def start_runner(slot_id):
    global _log_handles
    print(f"[SLOT_MANAGER] ▶ Starting worker for {slot_id}")
    
    # Read state to get worker module name
    state_file = SLOTS_DIR / slot_id / "slot_state.json"
    state = load_json(state_file, {})
    worker_name = state.get("worker", DEFAULT_SLOT_WORKER)
    
    # Set up logging to worker.log (visible on host via volume mount)
    log_path = SLOTS_DIR / slot_id / "worker.log"
    
    # Close any existing handle for this slot to prevent leaks
    if slot_id in _log_handles:
        try:
            _log_handles[slot_id].close()
        except Exception:
            pass
    
    # Ensure directory exists
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Simple log rotation: If log > 5MB, rotate it
    if log_path.exists() and log_path.stat().st_size > 5 * 1024 * 1024:
        try:
            # Keep one backup
            backup_path = log_path.with_suffix(".log.old")
            if backup_path.exists():
                backup_path.unlink()
            log_path.rename(backup_path)
            print(f"[SLOT_MANAGER] 🔄 Rotated log for {slot_id}")
        except Exception as e:
            print(f"[SLOT_MANAGER] ⚠️ Failed to rotate log for {slot_id}: {e}")
    
    # Open with line buffering for immediate visibility
    f = open(log_path, "a", buffering=1)
    _log_handles[slot_id] = f
    
    # Spawn worker directly (no more runner.py indirection)
    # This simplifies the architecture and makes PIDs clearer
    proc = subprocess.Popen(
        [PYTHON_BIN, "-m", f"core.workers.{worker_name}", str(SLOTS_DIR / slot_id)],
        stdout=f,
        stderr=f,
        start_new_session=True,
        cwd=BASE_DIR
    )
    
    print(f"[SLOT_MANAGER] ✅ Worker PID {proc.pid} started for {slot_id}")
    return proc.pid

def stop_runner(pid, slot_id):
    """
    Gracefully stop worker process.
    Try SIGTERM first, then SIGKILL if needed.
    """
    if not pid:
        return
    
    try:
        # Try graceful shutdown first (SIGTERM)
        os.kill(pid, signal.SIGTERM)
        print(f"[SLOT_MANAGER] 🛑 Sent SIGTERM to worker {slot_id} (PID {pid})")
        
        # Wait up to 3 seconds for graceful shutdown
        for i in range(30):  # 30 * 0.1s = 3 seconds
            try:
                os.kill(pid, 0)  # Check if process still exists
                time.sleep(0.1)
            except OSError:
                # Process is dead - graceful shutdown succeeded
                print(f"[SLOT_MANAGER] ✅ Worker {slot_id} stopped gracefully")
                return
        
        # Still alive after 3 seconds - force kill
        print(f"[SLOT_MANAGER] ⚠️ Worker {slot_id} did not stop gracefully, force killing...")
        os.kill(pid, signal.SIGKILL)
        print(f"[SLOT_MANAGER] ⛔ Force-killed worker {slot_id}")
    except ProcessLookupError:
        # Process already dead
        print(f"[SLOT_MANAGER] ℹ️ Worker {slot_id} already stopped")
    except PermissionError as e:
        print(f"[SLOT_MANAGER] ❌ Permission denied stopping worker {slot_id}: {e}")
    except Exception as e:
        print(f"[SLOT_MANAGER] ⚠️ Error stopping worker {slot_id}: {e}")

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

            # ---------------- COMMAND HANDLING (MUST BE FIRST!) ---------------- #
            # Process START/STOP commands BEFORE grace period checks
            # Otherwise slots get stuck in STARTING state
            
            command = state.get("command")
            
            # Handle START command immediately
            if command == "START":
                if mode == "OBSERVER":
                    print(f"[SLOT_MANAGER] 👁️ Observer mode — cannot start {slot_id}")
                    state["command"] = None
                    save_json(state_file, state)
                    continue
                else:
                    if not is_process_running(pid):
                        print(f"[SLOT_MANAGER] ▶ Starting worker for {slot_id} (via START command)")
                        state["pid"] = start_runner(slot_id)
                        state.update({
                            "status": "RUNNING",
                            "started_at": utcnow(),
                            "last_heartbeat": None,
                            "busy": True,
                            "command": None
                        })
                        save_json(state_file, state)
                        continue
            
            # Handle STOP command immediately
            elif command == "STOP":
                if is_process_running(pid):
                    stop_runner(pid, slot_id)
                state.update({
                    "status": "STOPPED",
                    "pid": None,
                    "busy": False,
                    "command": None,
                    "started_at": None,  # Clear temporal fields
                    "last_heartbeat": None,
                })
                save_json(state_file, state)
                continue
            
            # Handle PAUSE command immediately
            elif command == "PAUSE":
                if is_process_running(pid):
                    stop_runner(pid, slot_id)
                state.update({
                    "status": "PAUSED",
                    "pid": None,
                    "command": None
                })
                save_json(state_file, state)
                continue

            # NOW check grace period for existing processes
            if status in ("RUNNING", "STARTING", "STOPPING"):
                # --- STARTUP GRACE WINDOW ---
                if within_startup_grace(state):
                    save_json(state_file, state)
                    continue

                # --- PID CHECK ---
                # If status is STARTING but no command (legacy/race), try to start
                if status == "STARTING" and not is_process_running(pid):
                    print(f"[SLOT_MANAGER] ⚠️ UNEXPECTED: Implicit start for {slot_id} (no START command!)")
                    print(f"[SLOT_MANAGER] This may indicate a race condition or API bug (report if recurring)")
                    state["pid"] = start_runner(slot_id)
                    state.update({
                        "status": "RUNNING",
                        "started_at": utcnow(),
                        "last_heartbeat": None,
                        "busy": True,
                        "command": None
                    })
                    save_json(state_file, state)
                    continue
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
                        # If running and NO heartbeat after grace -> Mark as DEAD
                        print(f"[SLOT_MANAGER] 💀 No heartbeat for running slot {slot_id}, marking DEAD")
                        state.update({
                            "status": "DEAD",
                            "busy": False,
                            "stop_reason": "no_heartbeat",
                            "stopped_at": utcnow()
                        })
                    save_json(state_file, state)
                    continue

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
                            "status": "STOPPED",
                            "pid": None,
                            "busy": False,
                            "last_heartbeat": None,
                            "command": None
                        })
                        save_json(state_file, state)
                        continue
                except Exception as e:
                    print(f"[SLOT_MANAGER] ⚠️ Heartbeat parse error for {slot_id}: {e}")
                    save_json(state_file, state)
                    continue


            save_json(state_file, state)


        time.sleep(CHECK_INTERVAL)
    except Exception as e:
        print("[SLOT_MANAGER] 💥 CRASH RECOVERED")
        print(e)
        time.sleep(3)
