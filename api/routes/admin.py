from fastapi import APIRouter, HTTPException
from pathlib import Path
import json
import subprocess
import os
import signal
from datetime import datetime

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parents[2]
SLOTS_DIR = BASE_DIR / "slots"
PYTHON_BIN = "python3"

# -----------------------------
# Helpers
# -----------------------------
def slot_path(slot_id: str) -> Path:
    return SLOTS_DIR / slot_id

def load_json(path: Path):
    if not path.exists():
        return None
    with open(path, "r") as f:
        return json.load(f)

def save_json(path: Path, data: dict):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

# -----------------------------
# ADMIN: START SLOT
# -----------------------------
@router.post("/slots/{slot_id}/start")
def start_slot(slot_id: str):
    spath = slot_path(slot_id)
    state_file = spath / "slot_state.json"

    if not spath.exists():
        raise HTTPException(404, "Slot not found")

    state = load_json(state_file) or {}
    if state.get("status") == "RUNNING":
        return {"status": "already_running"}

    proc = subprocess.Popen(
        [PYTHON_BIN, str(BASE_DIR / "core/engine/runner.py"), slot_id],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    state.update({
        "status": "RUNNING",
        "pid": proc.pid,
        "last_heartbeat": datetime.utcnow().isoformat(),
        "auto_resume": state.get("auto_resume", True)
    })

    save_json(state_file, state)

    return {"status": "started", "pid": proc.pid}

# -----------------------------
# ADMIN: STOP SLOT
# -----------------------------
@router.post("/slots/{slot_id}/stop")
def stop_slot(slot_id: str):
    spath = slot_path(slot_id)
    state_file = spath / "slot_state.json"

    state = load_json(state_file)
    if not state:
        raise HTTPException(404, "Slot state missing")

    pid = state.get("pid")
    if pid:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass

    state["status"] = "STOPPED"
    state["pid"] = None
    save_json(state_file, state)

    return {"status": "stopped"}

# -----------------------------
# ADMIN: RESTART SLOT
# -----------------------------
@router.post("/slots/{slot_id}/restart")
def restart_slot(slot_id: str):
    stop_slot(slot_id)
    return start_slot(slot_id)

# -----------------------------
# ADMIN: TOGGLE AUTO RESUME
# -----------------------------
@router.post("/slots/{slot_id}/auto-resume/{enabled}")
def set_auto_resume(slot_id: str, enabled: bool):
    state_file = slot_path(slot_id) / "slot_state.json"
    state = load_json(state_file)

    if not state:
        raise HTTPException(404, "Slot state missing")

    state["auto_resume"] = enabled
    save_json(state_file, state)

    return {"auto_resume": enabled}