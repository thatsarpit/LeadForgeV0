from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import json
import os
import signal
import subprocess
from datetime import datetime

app = FastAPI(title="LeadForge API", version="1.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
SLOTS_DIR = BASE_DIR / "slots"
ENGINE_DIR = BASE_DIR / "core" / "engine"


# ---------- Utilities ----------

def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save_json(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2))


def slot_path(slot_id: str) -> Path:
    return SLOTS_DIR / slot_id


# ---------- Health ----------

@app.get("/health")
def health():
    return {
        "status": "ok",
        "time": datetime.utcnow().isoformat() + "Z"
    }


# ---------- Slot Read ----------

@app.get("/slots")
@app.get("/api/slots")
def get_slots():
    slots = []

    if not SLOTS_DIR.exists():
        return {"slots": []}

    for slot_dir in SLOTS_DIR.iterdir():
        if not slot_dir.is_dir():
            continue
        if slot_dir.name.startswith("."):
            continue

        state_file = slot_dir / "slot_state.json"
        if not state_file.exists():
            continue

        state = load_json(state_file, {})
        if state:
            state["slot_id"] = slot_dir.name
            slots.append(state)

    return {"slots": slots}


# ---------- Slot Commands ----------

@app.post("/slots/{slot_id}/start")
@app.post("/api/slots/{slot_id}/start")
def start_slot(slot_id: str):
    slot_dir = slot_path(slot_id)
    state_file = slot_dir / "slot_state.json"

    if not slot_dir.exists():
        raise HTTPException(status_code=404, detail="Slot not found")

    state = load_json(state_file, {})
    if state.get("status") == "RUNNING":
        return {"status": "already_running"}

    process = subprocess.Popen(
        ["python3", str(ENGINE_DIR / "runner.py"), slot_id],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )

    state.update({
        "status": "RUNNING",
        "pid": process.pid,
        "last_command": "START",
        "updated_at": datetime.utcnow().isoformat() + "Z"
    })

    save_json(state_file, state)
    return {"status": "started", "pid": process.pid}


@app.post("/slots/{slot_id}/stop")
@app.post("/api/slots/{slot_id}/stop")
def stop_slot(slot_id: str):
    slot_dir = slot_path(slot_id)
    state_file = slot_dir / "slot_state.json"

    if not slot_dir.exists():
        raise HTTPException(status_code=404, detail="Slot not found")

    state = load_json(state_file, {})
    pid = state.get("pid")

    if not pid:
        return {"status": "not_running"}

    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        pass

    state.update({
        "status": "STOPPED",
        "pid": None,
        "last_command": "STOP",
        "updated_at": datetime.utcnow().isoformat() + "Z"
    })

    save_json(state_file, state)
    return {"status": "stopped"}


@app.post("/slots/{slot_id}/restart")
@app.post("/api/slots/{slot_id}/restart")
def restart_slot(slot_id: str):
    stop_slot(slot_id)
    return start_slot(slot_id)