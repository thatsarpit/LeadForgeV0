from fastapi import FastAPI, HTTPException
from pathlib import Path
import json
import datetime
import os

BASE_DIR = Path(__file__).resolve().parents[2]
SLOTS_DIR = BASE_DIR / "slots"

app = FastAPI(
    title="LeadForge Control Plane",
    version="0.1.0"
)

def load_slot_state(slot_id: str):
    slot_path = SLOTS_DIR / slot_id / "slot_state.json"
    if not slot_path.exists():
        raise HTTPException(status_code=404, detail="Slot not found")
    return json.loads(slot_path.read_text())

def save_slot_state(slot_id: str, data: dict):
    slot_path = SLOTS_DIR / slot_id / "slot_state.json"
    slot_path.write_text(json.dumps(data, indent=2))

def write_command(slot_id: str, command: str):
    cmd_dir = SLOTS_DIR / slot_id / "commands"
    cmd_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.utcnow().timestamp()
    cmd_file = cmd_dir / f"{ts}_{command}.cmd"
    cmd_file.write_text(command)

@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "LeadForge API",
        "time": datetime.datetime.utcnow().isoformat()
    }

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/slots")
def list_slots():
    slots = []
    if not SLOTS_DIR.exists():
        return slots

    for slot_dir in SLOTS_DIR.iterdir():
        if slot_dir.is_dir():
            if slot_dir.name.startswith("_"):
                continue
            try:
                state = load_slot_state(slot_dir.name)
                slots.append({
                    "slot_id": slot_dir.name,
                    "enabled": state.get("enabled"),
                    "status": state.get("status")
                })
            except Exception:
                continue
    return slots

@app.get("/slots/{slot_id}")
def get_slot(slot_id: str):
    return load_slot_state(slot_id)

@app.post("/slots/{slot_id}/enable")
def enable_slot(slot_id: str):
    state = load_slot_state(slot_id)
    state["enabled"] = True
    state["status"] = "READY"
    save_slot_state(slot_id, state)
    write_command(slot_id, "ENABLE")
    return {"ok": True, "slot": slot_id, "action": "enabled"}

@app.post("/slots/{slot_id}/disable")
def disable_slot(slot_id: str):
    state = load_slot_state(slot_id)
    state["enabled"] = False
    state["status"] = "DISABLED"
    save_slot_state(slot_id, state)
    write_command(slot_id, "DISABLE")
    return {"ok": True, "slot": slot_id, "action": "disabled"}

@app.post("/slots/{slot_id}/observer")
def observer_mode(slot_id: str):
    state = load_slot_state(slot_id)
    state["enabled"] = False
    state["status"] = "OBSERVER"
    save_slot_state(slot_id, state)
    write_command(slot_id, "OBSERVER")
    return {"ok": True, "slot": slot_id, "mode": "observer"}
