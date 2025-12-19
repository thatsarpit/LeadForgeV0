import json
import sys
import time
from pathlib import Path
from typing import List, Dict, Optional

import requests
import yaml

from core.workers.base_worker import BaseWorker


class IndiaMartWorker(BaseWorker):
    """
    IndiaMart Worker — Phase 1 real scraper scaffold
    - Maintains existing lifecycle/heartbeat guarantees from BaseWorker
    - Adds sessioned HTTP fetch with timeouts + bounded retries
    - Non-blocking phases: fetch → parse → persist → cooldown
    """

    TICK_INTERVAL = 1.5
    REQUEST_TIMEOUT = (6, 12)  # (connect, read)
    MAX_RETRIES = 2
    MAX_LEADS_PER_PAGE = 25

    def __init__(self, slot_dir: Path):
        super().__init__(slot_dir)

        self.config = self._load_config()
        self.session = self._build_session()

        self.state = {
            "phase": "INIT",
            "last_action": None,
            "error_count": 0,
            "leads_buffer": [],
            "cooldown_until": 0.0,
            "current_term_idx": 0,
            "current_page": 1,
        }

        self.page_html: Optional[str] = None

    # ---------- Config / Session ---------- #

    def _load_config(self) -> dict:
        cfg_file = self.slot_dir / "slot_config.yml"
        defaults = {
            "search_terms": ["pharma exporters"],
            "max_pages_per_term": 1,
            "country": None,
        }

        if not cfg_file.exists() or cfg_file.stat().st_size == 0:
            return defaults

        try:
            data = yaml.safe_load(cfg_file.read_text()) or {}
            if not isinstance(data, dict):
                return defaults
            cfg = defaults.copy()
            cfg.update({k: v for k, v in data.items() if v is not None})
            return cfg
        except Exception:
            return defaults

    def _load_cookies(self) -> Dict[str, str]:
        """
        Best-effort cookie loader; session.enc is expected to be JSON (plain).
        If parsing fails, we continue unauthenticated.
        """
        cookie_path = self.slot_dir / "session.enc"
        if not cookie_path.exists() or cookie_path.stat().st_size == 0:
            return {}

        try:
            cookies = json.loads(cookie_path.read_text())
            if isinstance(cookies, dict):
                return {str(k): str(v) for k, v in cookies.items()}
            if isinstance(cookies, list):
                return {
                    str(c.get("name")): str(c.get("value"))
                    for c in cookies
                    if isinstance(c, dict) and "name" in c and "value" in c
                }
        except Exception:
            pass
        return {}

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

        cookies = self._load_cookies()
        if cookies:
            session.cookies.update(cookies)
        return session

    # ---------- Helpers ---------- #

    def _search_terms(self) -> List[str]:
        terms = self.config.get("search_terms") or []
        return [t for t in terms if isinstance(t, str) and t.strip()]

    def _current_term(self) -> Optional[str]:
        terms = self._search_terms()
        if not terms:
            return None
        idx = self.state.get("current_term_idx", 0)
        if idx >= len(terms):
            return None
        return terms[idx]

    def _build_search_url(self, term: str, page: int) -> str:
        # IndiaMart search endpoint works without auth for discovery.
        return (
            "https://www.indiamart.com/search.mp"
            f"?ss={requests.utils.quote(term)}"
            f"&pg={page}"
        )

    def _record_action(self, action: str, phase: str, **metrics):
        self.state["last_action"] = action
        self.update_metrics(last_action=action, phase=phase, **metrics)

    # ---------- Fetch / Parse / Persist ---------- #

    def _fetch_page(self, url: str) -> Optional[str]:
        last_error = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                resp = self.session.get(url, timeout=self.REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    return resp.text
                last_error = f"HTTP {resp.status_code}"
            except requests.RequestException as exc:
                last_error = str(exc)

            # small backoff to avoid hammering
            time.sleep(min(2 * attempt, 5))

        if last_error:
            self.record_error(last_error[:200])
        return None

    def _parse_leads(self, html: str) -> List[Dict[str, str]]:
        """
        Lightweight, forgiving parser that looks for IndiaMart-ish anchors.
        Avoids external dependencies; tolerates layout changes.
        """
        leads = []
        seen = set()

        for anchor in html.split("<a"):
            if "href" not in anchor:
                continue

            # crude href extraction
            href_part = anchor.split("href", 1)[1]
            quote = "\"" if "\"" in href_part else "'"
            if quote not in href_part:
                continue
            try:
                href = href_part.split(quote, 2)[1]
            except Exception:
                continue

            if not href or href.startswith("#"):
                continue

            if "indiamart" not in href:
                href_full = f"https://www.indiamart.com{href}" if href.startswith("/") else href
            else:
                href_full = href

            if not any(k in href_full for k in ("company", "proddetail", "impcat", "lead")):
                continue

            # crude text extraction: up to closing anchor
            text_part = anchor.split(">", 1)
            if len(text_part) < 2:
                continue
            text = text_part[1].split("</a", 1)[0]
            text = " ".join(text.replace("\n", " ").split()).strip()
            if len(text) < 3:
                continue

            lead_id = href_full.split("?")[0]
            if lead_id in seen:
                continue

            leads.append({
                "title": text[:120],
                "url": href_full,
                "source": "indiamart",
            })
            seen.add(lead_id)

            if len(leads) >= self.MAX_LEADS_PER_PAGE:
                break

        return leads

    def _persist_leads(self, leads: List[Dict[str, str]]):
        if not leads:
            return

        leads_path = self.slot_dir / "leads.jsonl"
        lines = [
            json.dumps({
                **lead,
                "slot_id": self.slot_dir.name,
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            for lead in leads
        ]

        with open(leads_path, "a", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")

        # update metrics after durable write
        state = self.load_state()
        metrics = state.get("metrics", {})
        metrics["leads_parsed"] = metrics.get("leads_parsed", 0) + len(leads)
        state["metrics"] = metrics
        state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.write_state(state)

    # ---------- Phase handlers ---------- #

    def _enter_cooldown(self, reason: str):
        cooldown = self.compute_cooldown()
        self.state["cooldown_until"] = time.time() + cooldown
        self.state["phase"] = "COOLDOWN"
        self._record_action(reason, "COOLDOWN", cooldown=cooldown)

    def compute_cooldown(self):
        metrics = self.load_state().get("metrics", {})
        error_rate = metrics.get("error_rate", 0.0)

        if error_rate < 0.05:
            return 2
        if error_rate < 0.15:
            return 5
        if error_rate < 0.30:
            return 10
        return 20

    def _init_phase(self):
        terms = self._search_terms()
        if not terms:
            self._record_action("no_terms", "COOLDOWN", last_error="No search terms configured")
            self.state["phase"] = "COOLDOWN"
            self.state["cooldown_until"] = time.time() + 15
            return

        self.state["phase"] = "FETCH_PAGE"
        self._record_action("init", "FETCH_PAGE")

    def _fetch_phase(self):
        term = self._current_term()
        if not term:
            # all terms done, rest a bit before retrying from start
            self.state["current_term_idx"] = 0
            self.state["current_page"] = 1
            self._enter_cooldown("cycle_complete")
            return

        url = self._build_search_url(term, self.state["current_page"])
        self._record_action("fetch_page", "FETCH_PAGE", current_term=term, page=self.state["current_page"])
        html = self._fetch_page(url)

        if not html:
            self._enter_cooldown("fetch_failed")
            return

        self.page_html = html
        self.state["phase"] = "PARSE_LEADS"
        self.update_metrics(pages_fetched=self.load_state().get("metrics", {}).get("pages_fetched", 0) + 1,
                            phase="PARSE_LEADS")

    def _parse_phase(self):
        if not self.page_html:
            self._enter_cooldown("missing_page")
            return

        leads = self._parse_leads(self.page_html)
        self.state["leads_buffer"] = leads
        self.page_html = None

        if not leads:
            self._enter_cooldown("no_leads")
            return

        self.state["phase"] = "WRITE_LEADS"
        self._record_action("parsed", "WRITE_LEADS", parsed=len(leads))

    def _write_phase(self):
        leads = self.state.get("leads_buffer", [])
        self._persist_leads(leads)
        self.state["leads_buffer"] = []

        self.state["phase"] = "COOLDOWN"
        self.state["current_page"] += 1

        # cycle pages per term
        max_pages = max(int(self.config.get("max_pages_per_term") or 1), 1)
        if self.state["current_page"] > max_pages:
            self.state["current_term_idx"] += 1
            self.state["current_page"] = 1

        self._enter_cooldown("write_done")

    def _cooldown_phase(self):
        now = time.time()
        until = self.state.get("cooldown_until", 0)
        if now < until:
            # stay idle but keep heartbeat going
            return

        self.state["phase"] = "FETCH_PAGE"
        self._record_action("resume", "FETCH_PAGE")

    # ---------- Tick ---------- #

    def tick(self):
        phase = self.state.get("phase", "INIT")

        try:
            if phase == "INIT":
                self._init_phase()
            elif phase == "FETCH_PAGE":
                self._fetch_phase()
            elif phase == "PARSE_LEADS":
                self._parse_phase()
            elif phase == "WRITE_LEADS":
                self._write_phase()
            elif phase == "COOLDOWN":
                self._cooldown_phase()
            else:
                # unknown phase; reset safely
                self.state["phase"] = "INIT"
                self._record_action("reset", "INIT")
        except Exception as exc:
            self.record_error(str(exc)[:200])
            self._enter_cooldown("unhandled_error")


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m core.workers.indiamart_worker <slot_dir>")
        sys.exit(1)

    slot_dir = Path(sys.argv[1]).resolve()
    worker = IndiaMartWorker(slot_dir)
    worker.run()


if __name__ == "__main__":
    main()
