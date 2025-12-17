from fastapi import APIRouter, HTTPException
from pathlib import Path
import json
import time

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parents[2]
SLOTS_DIR = BASE_DIR / "slots"


def load_json(path: Path):
    if not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


# -----------------------------------
# OBSERVER — LIST ALL SLOTS (PRIMARY)
# -----------------------------------
@router.get("/")
def list_slots():
    if not SLOTS_DIR.exists():
        return {"slots": []}

    slots = []

    for slot_dir in SLOTS_DIR.iterdir():
        if not slot_dir.is_dir() or slot_dir.name.startswith("."):
            continue

        state = load_json(slot_dir / "slot_state.json")
        heartbeat = load_json(slot_dir / "heartbeat.json")

        if not state:
            continue

        slot = {
            "slot_id": slot_dir.name,
            **state,
            "heartbeat_age": (
                int(time.time() - heartbeat.get("ts"))
                if heartbeat and "ts" in heartbeat
                else None
            ),
        }

        slots.append(slot)

    return {"slots": slots}


# -----------------------------------
# OBSERVER — SINGLE SLOT STATE
# -----------------------------------
@router.get("/{slot_id}/status")
def slot_status(slot_id: str):
    slot_path = SLOTS_DIR / slot_id
    state = load_json(slot_path / "slot_state.json")

    if not state:
        raise HTTPException(status_code=404, detail="Slot not found")

    return {
        "slot_id": slot_id,
        **state
    }


# -----------------------------------
# OBSERVER — HEARTBEAT
# -----------------------------------
@router.get("/{slot_id}/heartbeat")
def slot_heartbeat(slot_id: str):
    heartbeat = load_json(SLOTS_DIR / slot_id / "heartbeat.json")

    if not heartbeat:
        raise HTTPException(status_code=404, detail="No heartbeat")

    return heartbeat


# -----------------------------------
# DEBUG — RAW FILE VIEW
# -----------------------------------
@router.get("/{slot_id}/files")
def slot_files(slot_id: str):
    slot_path = SLOTS_DIR / slot_id
    if not slot_path.exists():
        raise HTTPException(status_code=404, detail="Slot not found")

    return {
        f.name: load_json(f)
        for f in slot_path.glob("*.json")
        if f.is_file()
    }