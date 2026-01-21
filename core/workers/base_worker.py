# core/workers/base_worker.py

import json
import re
import signal
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import yaml


class BaseWorker:
    """
    BaseWorker
    - Owns lifecycle
    - Owns heartbeat
    - Child workers override tick()
    """

    TICK_INTERVAL = 2
    HEARTBEAT_INTERVAL = 2
    CONFIG_REFRESH_SECONDS = 5

    DAY_ALIASES = {
        "mon": 0,
        "monday": 0,
        "tue": 1,
        "tues": 1,
        "tuesday": 1,
        "wed": 2,
        "weds": 2,
        "wednesday": 2,
        "thu": 3,
        "thur": 3,
        "thurs": 3,
        "thursday": 3,
        "fri": 4,
        "friday": 4,
        "sat": 5,
        "saturday": 5,
        "sun": 6,
        "sunday": 6,
    }

    def __init__(self, slot_dir: Path):
        self.slot_dir = slot_dir
        self.state_file = slot_dir / "slot_state.json"

        if not self.state_file.exists():
            raise FileNotFoundError(f"slot_state.json not found in {slot_dir}")

        self.running = True
        self.last_heartbeat_ts = 0
        self._last_metric_ts = time.time()
        self._last_leads_count = 0
        self._config_cache = {}
        self._config_cache_ts = 0.0
        self._stop_requested = False

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
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.write_state(state)

    def record_error(self, error_msg: str):
        state = self.load_state()
        metrics = state.get("metrics", {})

        metrics["errors"] = metrics.get("errors", 0) + 1
        metrics["last_error"] = error_msg

        pages = max(metrics.get("pages_fetched", 1), 1)
        metrics["error_rate"] = round(metrics["errors"] / pages, 3)

        state["metrics"] = metrics
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.write_state(state)

    # ---------- Client limits ----------

    def _load_slot_config(self) -> dict:
        now = time.time()
        if self._config_cache_ts and (now - self._config_cache_ts) < self.CONFIG_REFRESH_SECONDS:
            return self._config_cache or {}

        path = self.slot_dir / "slot_config.yml"
        data = {}
        if path.exists():
            try:
                loaded = yaml.safe_load(path.read_text()) or {}
                if isinstance(loaded, dict):
                    data = loaded
            except Exception:
                data = {}

        self._config_cache = data
        self._config_cache_ts = now
        return data

    def _parse_iso(self, value):
        if not value:
            return None
        try:
            cleaned = str(value).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(cleaned)
            if parsed.tzinfo:
                return parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except Exception:
            return None

    def _normalize_days(self, value):
        if not value:
            return None

        if isinstance(value, list):
            tokens = value
        else:
            tokens = re.split(r"[,\s]+", str(value))

        days = set()
        for token in tokens:
            key = str(token).strip().lower()
            if not key:
                continue
            mapped = self.DAY_ALIASES.get(key)
            if mapped is not None:
                days.add(mapped)

        return days or None

    def _parse_minutes(self, value):
        if not value:
            return None
        try:
            parts = str(value).strip().split(":")
            if len(parts) < 2:
                return None
            hour = int(parts[0])
            minute = int(parts[1])
            if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                return None
            return hour * 60 + minute
        except Exception:
            return None

    def _schedule_allows_run(self, schedule) -> bool:
        if not schedule or not isinstance(schedule, dict):
            return True
        if schedule.get("enabled") is False:
            return True

        tz_name = str(schedule.get("timezone") or "").strip()
        now = datetime.now()
        if tz_name:
            try:
                now = datetime.now(ZoneInfo(tz_name))
            except Exception:
                now = datetime.now()
        allowed_days = self._normalize_days(schedule.get("days"))
        if allowed_days and now.weekday() not in allowed_days:
            return False

        start = self._parse_minutes(schedule.get("window_start"))
        end = self._parse_minutes(schedule.get("window_end"))
        if start is None or end is None or start == end:
            return True

        current = now.hour * 60 + now.minute
        if start < end:
            return start <= current < end
        return current >= start or current < end

    def _request_stop(self, reason: str, detail=None):
        if self._stop_requested:
            return
        state = self.load_state()
        state["stop_reason"] = reason
        if detail:
            state["stop_detail"] = detail
        state["last_command"] = "AUTO_STOP"
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.write_state(state)
        self._stop_requested = True
        self.running = False

    def _enforce_limits(self) -> bool:
        try:
            config = self._load_slot_config()
            if not config:
                return False

            schedule = config.get("client_schedule")
            if not self._schedule_allows_run(schedule):
                self._request_stop("outside_schedule", "Outside configured run window")
                return True

            max_minutes = int(config.get("max_run_minutes") or 0)
            if max_minutes > 0:
                state = self.load_state()
                started_at = state.get("run_started_at") or state.get("started_at")
                started_ts = self._parse_iso(started_at)
                if started_ts:
                    elapsed_min = (datetime.now(timezone.utc) - started_ts).total_seconds() / 60.0
                    if elapsed_min >= max_minutes:
                        self._request_stop("max_runtime_reached", f"{int(elapsed_min)} minutes")
                        return True

            max_clicks = int(config.get("max_clicks_per_run") or 0)
            if max_clicks > 0:
                state = self.load_state()
                metrics = state.get("metrics", {})
                total_leads = int(metrics.get("leads_parsed") or 0)
                baseline = int(state.get("run_leads_start") or 0)
                leads_this_run = max(0, total_leads - baseline)
                if leads_this_run >= max_clicks:
                    self._request_stop("lead_target_reached", f"{leads_this_run} leads")
                    return True
        except Exception:
            return False

        return False

    # ---------- Lifecycle ----------

    def startup(self):
        state = self.load_state()
        metrics = state.get("metrics", {})
        run_leads_start = int(metrics.get("leads_parsed") or 0)
        run_started_at = datetime.now(timezone.utc).isoformat()
        state.update({
            "status": "RUNNING",
            "busy": True,
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            "started_at": state.get("started_at") or run_started_at,
            "run_started_at": run_started_at,
            "run_leads_start": run_leads_start,
            "stop_reason": None,
            "stop_detail": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        self.write_state(state)
        self.init_metrics()
        print(f"[WORKER] RUNNING → {self.slot_dir.name}")

    def shutdown(self):
        state = self.load_state()
        state.update({
            "status": "STOPPED",
            "busy": False,
            "stopped_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
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
        now = datetime.now(timezone.utc)
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

        state["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
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
                if self._enforce_limits():
                    break
                self.tick()
                self.heartbeat()
                time.sleep(self.adaptive_sleep(self.TICK_INTERVAL))
        finally:
            self.shutdown()
