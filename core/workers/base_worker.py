# core/workers/base_worker.py

import time
import json
import signal
from pathlib import Path
from datetime import datetime


class BaseWorker:
    """
    BaseWorker
    - Owns lifecycle
    - Owns heartbeat
    - Child workers override tick()
    """

    TICK_INTERVAL = 2
    HEARTBEAT_INTERVAL = 2

    def __init__(self, slot_dir: Path):
        self.slot_dir = slot_dir
        self.state_file = slot_dir / "slot_state.json"

        if not self.state_file.exists():
            raise FileNotFoundError(f"slot_state.json not found in {slot_dir}")

        self.running = True
        self.last_heartbeat_ts = 0
        self._last_metric_ts = time.time()
        self._last_leads_count = 0

        signal.signal(signal.SIGTERM, self._handle_exit)
        signal.signal(signal.SIGINT, self._handle_exit)

    # ---------- State ----------

    def load_state(self):
        return json.loads(self.state_file.read_text())

    def write_state(self, state):
        self.state_file.write_text(json.dumps(state, indent=2))

    def init_metrics(self):
        state = self.load_state()
        metrics = state.get("metrics", {})

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

        changed = False
        for k, v in defaults.items():
            if k not in metrics:
                metrics[k] = v
                changed = True

        if changed:
            state["metrics"] = metrics
            self.write_state(state)

    def update_metrics(self, **updates):
        state = self.load_state()
        metrics = state.get("metrics", {})

        for k, v in updates.items():
            metrics[k] = v

        state["metrics"] = metrics
        state["updated_at"] = datetime.utcnow().isoformat()
        self.write_state(state)

    def record_error(self, error_msg: str):
        state = self.load_state()
        metrics = state.get("metrics", {})

        metrics["errors"] = metrics.get("errors", 0) + 1
        metrics["last_error"] = error_msg

        pages = max(metrics.get("pages_fetched", 1), 1)
        metrics["error_rate"] = round(metrics["errors"] / pages, 3)

        state["metrics"] = metrics
        state["updated_at"] = datetime.utcnow().isoformat()
        self.write_state(state)

    # ---------- Lifecycle ----------

    def startup(self):
        state = self.load_state()
        state.update({
            "status": "RUNNING",
            "busy": True,
            "last_heartbeat": datetime.utcnow().isoformat(),
            "started_at": state.get("started_at") or datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        })
        self.write_state(state)
        self.init_metrics()
        print(f"[WORKER] RUNNING → {self.slot_dir.name}")

    def shutdown(self):
        state = self.load_state()
        state.update({
            "status": "STOPPED",
            "busy": False,
            "updated_at": datetime.utcnow().isoformat(),
        })
        self.write_state(state)
        print(f"[WORKER] STOPPED → {self.slot_dir.name}")

    def _handle_exit(self, *_):
        self.running = False

    def update_throughput(self, state):
        now = time.time()
        metrics = state.get("metrics", {})
        leads = metrics.get("leads_parsed", 0)

        delta_leads = leads - self._last_leads_count
        delta_time = now - self._last_metric_ts

        if delta_leads > 0 and delta_time > 0:
            throughput = round((delta_leads / delta_time) * 60, 2)
            metrics["throughput"] = throughput

            self._last_leads_count = leads
            self._last_metric_ts = now

        state["metrics"] = metrics

    def set_phase(self, phase_name: str):
        now = datetime.utcnow()
        state = self.load_state()
        metrics = state.get("metrics", {})

        last_start = metrics.get("phase_started_at")
        if last_start:
            try:
                elapsed = (now - datetime.fromisoformat(last_start)).total_seconds()
                metrics["phase_duration_sec"] = round(elapsed, 2)
            except Exception:
                pass

        metrics["phase"] = phase_name
        metrics["phase_started_at"] = now.isoformat()
        metrics["last_action"] = phase_name

        state["metrics"] = metrics
        state["updated_at"] = now.isoformat()
        self.write_state(state)

    # ---------- Heartbeat ----------

    def heartbeat(self):
        now = time.time()
        if now - self.last_heartbeat_ts < self.HEARTBEAT_INTERVAL:
            return

        state = self.load_state()

        # update throughput before heartbeat
        self.update_throughput(state)

        state["last_heartbeat"] = datetime.utcnow().isoformat()
        state["updated_at"] = datetime.utcnow().isoformat()
        self.write_state(state)

        self.last_heartbeat_ts = now

    # ---------- Override ----------

    def tick(self):
        pass

    def adaptive_sleep(self, base=2):
        """
        Adaptive cooldown based on error_rate.
        Safe defaults; never sleeps less than base.
        """
        try:
            state = self.load_state()
            error_rate = state.get("metrics", {}).get("error_rate", 0)

            if error_rate < 0.05:
                return base
            elif error_rate < 0.15:
                return 5
            elif error_rate < 0.30:
                return 10
            else:
                return 20
        except Exception:
            return base

    # ---------- Main Loop ----------

    def run(self):
        self.startup()
        try:
            while self.running:
                self.tick()
                self.heartbeat()
                time.sleep(self.adaptive_sleep(self.TICK_INTERVAL))
        finally:
            self.shutdown()