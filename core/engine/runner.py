# core/engine/runner.py

import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime
import os
import time


BASE_DIR = Path(__file__).resolve().parents[2]
SLOTS_DIR = BASE_DIR / "slots"


def load_state(path: Path) -> dict:
    return json.loads(path.read_text())


def write_state(path: Path, updates: dict):
    state = load_state(path)
    state.update(updates)
    path.write_text(json.dumps(state, indent=2))


def main():
    if len(sys.argv) != 2:
        print("Usage: runner.py <slot_id|slot_path>")
        sys.exit(1)

    arg = Path(sys.argv[1])

    if arg.is_dir():
        slot_dir = arg.resolve()
        slot_id = slot_dir.name
    else:
        slot_id = arg.name
        slot_dir = (SLOTS_DIR / slot_id).resolve()

    state_file = slot_dir / "slot_state.json"

    print(f"[RUNNER] 🚀 Booting runner for {slot_id}")
    print(f"[RUNNER] Slot dir: {slot_dir}")

    if not state_file.exists():
        raise FileNotFoundError(f"slot_state.json not found at {state_file}")

    state = load_state(state_file)
    worker_name = state.get("worker")

    if not worker_name:
        raise RuntimeError("No worker defined in slot_state.json")

    now = datetime.utcnow().isoformat()

    # IMPORTANT: heartbeat immediately to survive SlotManager
    write_state(state_file, {
        "status": "STARTING",
        "busy": True,
        "last_heartbeat": now,
        "updated_at": now,
        "pid": None,
    })

    module_path = f"core.workers.{worker_name}"
    print(f"[RUNNER] ▶ Launching worker module {module_path}")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(BASE_DIR)

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            module_path,
            str(slot_dir),
        ],
        cwd=BASE_DIR,
        env=env,
        start_new_session=True,
    )

    write_state(state_file, {
        "pid": proc.pid,
        "updated_at": datetime.utcnow().isoformat(),
    })

    print(f"[RUNNER] ✅ Worker PID {proc.pid} started")

    try:
        while True:
            if proc.poll() is not None:
                print("[RUNNER] ❌ Worker exited")
                write_state(state_file, {
                    "pid": None,
                    "updated_at": datetime.utcnow().isoformat(),
                })
                break
            time.sleep(2)
    except KeyboardInterrupt:
        print("[RUNNER] ⛔ Runner interrupted")
    finally:
        pass


if __name__ == "__main__":
    main()