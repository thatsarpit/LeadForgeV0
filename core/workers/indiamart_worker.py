import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
import yaml
from requests.cookies import RequestsCookieJar

from core.workers.base_worker import BaseWorker
from core.db.database import init_db, save_lead_to_db, get_slot_lead_ids, mark_leads_as_verified


class IndiaMartWorker(BaseWorker):
    """
    IndiaMart Seller Portal worker
    - Polls recent leads page for new items
    - Opens lead detail links to mark "clicked"
    - Cross-checks purchased leads page to mark "verified"
    """

    TICK_INTERVAL = 0.5  # 500ms - auto-corrected for stability (250ms caused crashes)
    REQUEST_TIMEOUT = (6, 14)  # (connect, read)
    MAX_RETRIES = 2

    BASE_DIR = Path(__file__).resolve().parents[2]
    DEFAULT_RECENT_URL = "https://seller.indiamart.com/bltxn/?pref=recent"
    DEFAULT_VERIFIED_URL = "https://seller.indiamart.com/blproduct/mypurchasedbl?disp=D"
    DEFAULT_RECENT_API_URL = "https://seller.indiamart.com/bltxn/default/BringFirstFoldOfBLOnRelevant/"

    ID_PATTERNS = [
        re.compile(r"blid=([0-9]+)", re.IGNORECASE),
        re.compile(r"bl_id=([0-9]+)", re.IGNORECASE),
        re.compile(r"rfq_id=([0-9]+)", re.IGNORECASE),
        re.compile(r"leadid=([0-9]+)", re.IGNORECASE),
        re.compile(r"lead_id=([0-9]+)", re.IGNORECASE),
        re.compile(r"enqid=([0-9]+)", re.IGNORECASE),
        re.compile(r"enquiryid=([0-9]+)", re.IGNORECASE),
        re.compile(r"inquiryid=([0-9]+)", re.IGNORECASE),
        re.compile(r"/bl/([0-9]+)", re.IGNORECASE),
        re.compile(r"/lead/([0-9]+)", re.IGNORECASE),
    ]

    DATA_ID_PATTERN = re.compile(
        r"data-[a-z0-9_-]*(?:bl|lead|rfq|enq)[a-z0-9_-]*=[\"']([0-9]+)[\"']",
        re.IGNORECASE,
    )
    
    # Patterns for Past Transactions page (phone/email for matching)
    PHONE_PATTERN = re.compile(r"\+(\d[\d\-\s]{7,15}\d)", re.IGNORECASE)
    EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+", re.IGNORECASE)

    ANCHOR_PATTERN = re.compile(
        r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )

    def __init__(self, slot_dir: Path):
        super().__init__(slot_dir)

        self.config = self._load_config()
        self.session = self._build_session()
        self._playwright = None
        self._context = None
        self._page = None
        self._playwright_missing = False
        self._cookie_mtime = 0.0
        self._quality_level = 70
        self._recent_ready = False
        self._last_recent_nav = 0.0
        self._recent_frame = None

        self.state = {
            "phase": "INIT",
            "last_action": None,
            "cooldown_until": 0.0,
            "leads_buffer": [],
            "rejected_buffer": [],
            "ticks_since_verify": 0,
            "recent_html": None,
            "recent_payload": None,
            "verified_html": None,
        }
        
        # Initialize DB on startup
        try:
            init_db()
        except Exception as e:
            self.record_error(f"db_init_err: {e}")

    # ---------- Config / Session ---------- #

    def _load_config(self) -> dict:
        cfg_file = self.slot_dir / "slot_config.yml"
        defaults = {
            "recent_url": self.DEFAULT_RECENT_URL,
            "recent_api_url": self.DEFAULT_RECENT_API_URL,
            "verified_url": self.DEFAULT_VERIFIED_URL,
            "use_browser": True,
            "prefer_api": False,
            "headless": False,
            "allow_detail_click": False,
            "max_new_per_cycle": 20,
            "max_verified_leads_per_cycle": 6,
            "max_lead_age_seconds": 30,
            "allow_unknown_age": False,
            "zero_second_only": False,
            "require_mobile_available": False,
            "require_mobile_verified": False,
            "require_email_available": False,
            "require_email_verified": False,
            "require_whatsapp_available": False,
            "render_wait_ms": 1500,
            "recent_wait_ms": 1200,
            "recent_refresh_seconds": 2,
            "recent_wait_networkidle": False,
            "top_card_only": False,
            "top_card_count": 1,
            "pagination_pages": 1,
            "pagination_wait_ms": 1500,
            "verify_after_click_seconds": 10,
            "verify_render_wait_ms": 5000,
            "cooldown_seconds": None,
            "periodic_verify": False,
            "debug_snapshot": False,
        }

        if not cfg_file.exists() or cfg_file.stat().st_size == 0:
            return defaults

        try:
            data = yaml.safe_load(cfg_file.read_text()) or {}
            if not isinstance(data, dict):
                return defaults
            cfg = defaults.copy()
            cfg.update({k: v for k, v in data.items() if v is not None})
            # Headful sessions should always use the DOM path for consistency.
            if cfg.get("headless") is False:
                cfg["prefer_api"] = False
            return cfg
        except Exception:
            return defaults

    def _load_cookies(self) -> Dict[str, str]:
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

    def _load_cookie_list(self) -> List[dict]:
        cookie_path = self.slot_dir / "session.enc"
        if not cookie_path.exists() or cookie_path.stat().st_size == 0:
            return []
        try:
            cookies = json.loads(cookie_path.read_text())
            if isinstance(cookies, list):
                return [c for c in cookies if isinstance(c, dict)]
        except Exception:
            pass
        return []

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
            "Referer": "https://seller.indiamart.com/",
        })

        cookie_list = self._load_cookie_list()
        if cookie_list:
            self._apply_cookie_list_to_session(session, cookie_list)
            return session

        cookies = self._load_cookies()
        if cookies:
            session.cookies.update(cookies)
        return session

    def _apply_cookie_list_to_session(self, session: requests.Session, cookies: List[dict]) -> bool:
        if not cookies:
            return False
        jar = RequestsCookieJar()
        for cookie in cookies:
            if not isinstance(cookie, dict):
                continue
            name = cookie.get("name")
            value = cookie.get("value")
            if not name:
                continue
            params = {}
            domain = cookie.get("domain")
            path = cookie.get("path")
            if domain:
                params["domain"] = domain
            if path:
                params["path"] = path
            if "secure" in cookie:
                params["secure"] = bool(cookie.get("secure"))
            expires = cookie.get("expires")
            if isinstance(expires, (int, float)) and expires > 0:
                params["expires"] = int(expires)
            http_only = cookie.get("httpOnly")
            if http_only is not None:
                params["rest"] = {"HttpOnly": bool(http_only)}
            jar.set(name, str(value or ""), **params)
        session.cookies.clear()
        session.cookies.update(jar)
        return True

    def _maybe_reload_cookies(self):
        cookie_path = self.slot_dir / "session.enc"
        if not cookie_path.exists():
            return
        mtime = cookie_path.stat().st_mtime
        if mtime <= self._cookie_mtime:
            return
        cookie_list = self._load_cookie_list()
        if cookie_list:
            if self._apply_cookie_list_to_session(self.session, cookie_list):
                self._cookie_mtime = mtime

    def _refresh_cookies_from_browser(self) -> bool:
        if not self._ensure_browser():
            return False
        try:
            try:
                target = self.config.get("recent_url") or self.DEFAULT_RECENT_URL
                self._page.goto(target, wait_until="domcontentloaded")
                if not self._page_logged_in(self._page.content()):
                    return False
            except Exception:
                return False
            cookies = self._context.cookies()
            filtered = [
                c
                for c in cookies
                if "indiamart" in (c.get("domain") or "") or "indiamart" in (c.get("name") or "")
            ]
            payload = filtered or cookies
            if not payload:
                return False
            session_file = self.slot_dir / "session.enc"
            session_file.write_text(json.dumps(payload, indent=2))
            self._apply_cookie_list_to_session(self.session, payload)
            self._cookie_mtime = session_file.stat().st_mtime
            return True
        except Exception as exc:
            self.record_error(str(exc)[:200])
            return False

    # ---------- Helpers ---------- #

    def _record_action(self, action: str, phase: str, **metrics):
        self.state["last_action"] = action
        self.update_metrics(last_action=action, phase=phase, **metrics)

    def _strip_tags(self, text: str) -> str:
        cleaned = re.sub(r"<[^>]+>", " ", text or "")
        return " ".join(cleaned.replace("\n", " ").split()).strip()

    def _normalize_url(self, url: str) -> str:
        if not url:
            return ""
        # Clean double-domain bug: //seller.indiamart.com//seller.indiamart.com/...
        url = re.sub(r"^(https?:)?//seller\.indiamart\.com//", "https://seller.indiamart.com/", url)
        # Also handle case where it appears mid-URL
        url = re.sub(r"(https?://seller\.indiamart\.com)/+seller\.indiamart\.com/", r"\1/", url)
        if url.startswith("//"):
            return f"https:{url}"
        if url.startswith("http"):
            return url
        return requests.compat.urljoin(self.DEFAULT_RECENT_URL, url)

    def _extract_id_from_url(self, url: str) -> Optional[str]:
        if not url:
            return None
        for pattern in self.ID_PATTERNS:
            match = pattern.search(url)
            if match:
                return match.group(1)
        return None

    def _extract_ids(self, html: str) -> List[str]:
        found = []
        seen = set()
        if not html:
            return found

        for pattern in self.ID_PATTERNS:
            for match in pattern.findall(html):
                if match and match not in seen:
                    seen.add(match)
                    found.append(match)

        for match in self.DATA_ID_PATTERN.findall(html):
            if match and match not in seen:
                seen.add(match)
                found.append(match)

        return found

    def _looks_like_lead_link(self, href: str) -> bool:
        if not href:
            return False
        token = href.lower()
        return any(k in token for k in ("bltxn", "lead", "blproduct", "enq", "rfq", "blid"))

    def _lead_key(self, lead: Dict[str, str]) -> str:
        lead_id = str(lead.get("lead_id") or "").strip()
        if lead_id:
            return f"id:{lead_id}"
        url = str(lead.get("url") or lead.get("detail_url") or "").strip()
        if url:
            return f"url:{url.split('?')[0]}"
        title = str(lead.get("title") or lead.get("company") or "").strip().lower()
        if title:
            return f"title:{title}"
        digest = hashlib.sha1(json.dumps(lead, sort_keys=True).encode("utf-8")).hexdigest()
        return f"hash:{digest}"

    def _load_existing_keys(self, max_lines: int = 5000) -> set:
        """
        Load existing lead IDs from SQLite to avoid duplicates.
        Returns a set of 'id:XYZ' or equivalent keys.
        """
        try:
            # We limit to last 5000 to keep memory low, but enough to avoid recent dupes
            lead_ids = get_slot_lead_ids(self.slot_dir.name, limit=max_lines)
            return {f"id:{lid}" for lid in lead_ids if lid}
        except Exception:
            return set()

    def _snapshot_html(self, name: str, html: str):
        if not self.config.get("debug_snapshot"):
            return
        if not html:
            return
        path = self.slot_dir / f"{name}.html"
        try:
            path.write_text(html[:200000])
        except Exception:
            pass

    def _page_logged_in(self, html: str) -> bool:
        if not html:
            return False
        lower = html.lower()
        markers_in = ["logout", "sign out", "past transactions", "buyleads", "bltxn"]
        markers_out = ["free registration", "start selling", "sell on indiamart", "sign in", "register"]
        logged_in = any(m in lower for m in markers_in)
        logged_out = any(m in lower for m in markers_out)
        return logged_in and not logged_out

    def _parse_age_seconds(self, value: Optional[str]) -> Optional[int]:
        if not value:
            return None
        text = str(value).strip().lower()
        if not text:
            return None
        if "just now" in text or text == "0 sec" or text == "0 secs":
            return 0
        match = re.search(r"(\\d+)\\s*(sec|s|second|seconds|min|mins|minute|minutes|hr|hrs|hour|hours|day|days)", text)
        if not match:
            return None
        amount = int(match.group(1))
        unit = match.group(2)
        if unit.startswith("s"):
            return amount
        if unit.startswith("min"):
            return amount * 60
        if unit.startswith("h"):
            return amount * 3600
        if unit.startswith("d"):
            return amount * 86400
        return None

    def _parse_member_months(self, value: Optional[str]) -> int:
        """
        Convert loose 'member since' strings into an approximate month count.
        Accepts inputs like '12 months', 'Member since Jan-2023', '2022-07', etc.
        Falls back to 0 if the string can't be parsed.
        """
        if not value:
            return 0
        text = str(value).strip()
        if not text:
            return 0

        # 1) Explicit month counts (e.g., "18 months")
        # Accept "month", "months", "mon", "mons"
        m = re.search(r"(\d+)\s*(?:months?|mons?)\b", text, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass

        # 2) Strip common prefixes and punctuation for date parsing
        cleaned = re.sub(r"member\\s+since[:\\s]*", "", text, flags=re.IGNORECASE)
        cleaned = cleaned.replace("since", "").strip(" ,.-")

        # 3) Try a handful of date formats (month/year granularity)
        candidates = [
            "%b %Y", "%B %Y", "%b-%Y", "%B-%Y",
            "%Y-%m-%d", "%Y-%m", "%Y/%m/%d", "%Y/%m",
            "%d-%b-%Y", "%d-%B-%Y",
        ]
        for fmt in candidates:
            try:
                dt = datetime.strptime(cleaned, fmt)
                dt = dt.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                months = (now.year - dt.year) * 12 + (now.month - dt.month)
                return max(months, 0)
            except Exception:
                continue

        # 4) As a last resort, if the string is just a year
        year_match = re.match(r"^(20\\d{2}|19\\d{2})$", cleaned)
        if year_match:
            year = int(year_match.group(1))
            now = datetime.now(timezone.utc)
            months = (now.year - year) * 12
            return max(months, 0)

        return 0

    def _extract_urls_from_item(self, item: dict) -> Tuple[Optional[str], Optional[str]]:
        if not isinstance(item, dict):
            return None, None
        buy_url = None
        detail_url = None
        for key, value in item.items():
            if not isinstance(value, str):
                continue
            val = value.strip()
            if not val:
                continue
            if not (val.startswith("/") or val.startswith("http")):
                continue
            token = key.lower()
            if "buy" in token or "purchase" in token:
                buy_url = self._normalize_url(val)
            elif "detail" in token or "view" in token or "lead" in token or "bl" in token:
                detail_url = self._normalize_url(val)
        return buy_url, detail_url

    def _snapshot_json(self, name: str, payload: dict):
        if not self.config.get("debug_snapshot"):
            return
        path = self.slot_dir / f"{name}.json"
        try:
            path.write_text(json.dumps(payload, indent=2)[:200000])
        except Exception:
            pass

    # ---------- Fetch / Parse ---------- #

    def _ensure_browser(self) -> bool:
        if self._playwright_missing:
            return False
        if self._context and self._page:
            return True
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            self._playwright_missing = True
            self.record_error("playwright_missing")
            return False

        self._playwright = sync_playwright().start()
        profile_dir = self.BASE_DIR / "browser_profiles" / self.slot_dir.name
        profile_dir.mkdir(parents=True, exist_ok=True)
        headless = bool(self.config.get("headless", True))
        user_agent = self.config.get("user_agent") or (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--start-maximized",
            ],
            viewport={"width": 1440, "height": 900},
            user_agent=user_agent,
            locale="en-US",
        )
        try:
            self._context.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
                """
            )
        except Exception:
            pass
        cookies = self._load_cookie_list()
        if cookies:
            try:
                self._context.add_cookies(cookies)
            except Exception:
                pass
        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()
        self._page.set_default_timeout(12000)
        return True

    def _close_browser(self):
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._context = None
        self._page = None
        self._playwright = None

    def _render_page(self, url: str) -> Optional[str]:
        if not self._ensure_browser():
            return None
        try:
            self._page.goto(url, wait_until="domcontentloaded")
            if self.config.get("top_card_only"):
                try:
                    self._page.wait_for_selector("#list1, .bl_grid", timeout=2500)
                except Exception:
                    pass
            try:
                self._page.wait_for_load_state("networkidle", timeout=2500)
            except Exception:
                pass
            wait_ms = int(self.config.get("render_wait_ms") or 0)
            if self.config.get("top_card_only"):
                wait_ms = max(wait_ms, 2000)
            if wait_ms > 0:
                self._page.wait_for_timeout(wait_ms)
            return self._page.content()
        except Exception as exc:
            self.record_error(str(exc)[:200])
            return None

    def _is_recent_url(self, url: str) -> bool:
        """
        Treat the IndiaMart redirect shell (`#succ_url=...`) as equivalent to the
        actual Recent page so we don't thrash reloads or mis-detect state.
        """
        if not url:
            return False
        target = self.config.get("recent_url") or self.DEFAULT_RECENT_URL
        base = target.split("?", 1)[0]
        if url.startswith(target) or url.startswith(base):
            return True
        if "succ_url=" in url:
            return True
        return False

    def _maybe_follow_succ_url(self):
        """
        If the current page is the seller shell with a #succ_url hash, decode and
        navigate to the intended destination once to reach the real Recent DOM.
        """
        try:
            url = self._page.url
            if "succ_url=" not in url:
                return
            succ = url.split("succ_url=", 1)[1]
            if succ.startswith("aHR0"):
                import base64
                try:
                    decoded = base64.b64decode(succ.split("#",1)[0]).decode("utf-8")
                    self._page.goto(decoded, wait_until="domcontentloaded")
                    self._last_recent_nav = time.time()
                    self._recent_ready = False
                    self._recent_frame = None
                except Exception:
                    pass
        except Exception:
            pass

    def _get_recent_frame(self):
        if not self._ensure_browser():
            return None
        if self._recent_frame:
            try:
                if not self._recent_frame.is_detached() and self._recent_frame.query_selector("#list1, .bl_grid"):
                    return self._recent_frame
            except Exception:
                self._recent_frame = None
        try:
            for frame in self._page.frames:
                try:
                    if frame.query_selector("#list1, .bl_grid"):
                        self._recent_frame = frame
                        return frame
                except Exception:
                    continue
        except Exception:
            return None
        return None

    def _wait_for_recent_dom(self, timeout_ms: int) -> Optional[object]:
        deadline = time.time() + max(timeout_ms, 1000) / 1000.0
        while time.time() < deadline:
            frame = self._get_recent_frame()
            if frame:
                return frame
            time.sleep(0.2)
        return None

    def _record_recent_missing(self):
        try:
            page_url = self._page.url
            page_title = self._page.title()
            snippet = ""
            try:
                snippet = self._page.evaluate(
                    "() => (document.body && document.body.innerText || '').slice(0,200)"
                ) or ""
            except Exception:
                pass
            self.record_error(f"top_card_missing:{page_url}:{page_title}:{snippet}")
            try:
                self._page.screenshot(
                    path=str(self.slot_dir / "top_card_missing.png"), full_page=True
                )
            except Exception:
                pass
        except Exception:
            self.record_error("top_card_missing")

    def _ensure_recent_page(self) -> bool:
        if not self._ensure_browser():
            return False
        url = self.config.get("recent_url") or self.DEFAULT_RECENT_URL
        now = time.time()
        refresh_every = int(self.config.get("recent_refresh_seconds") or 0)

        if not self._is_recent_url(self._page.url):
            try:
                self._page.goto(url, wait_until="domcontentloaded")
            except Exception as exc:
                self.record_error(f"recent_goto:{str(exc)[:80]}")
                return False
            self._last_recent_nav = now
            self._recent_ready = False
            self._recent_frame = None
            self._maybe_follow_succ_url()
        elif refresh_every and (now - self._last_recent_nav) > refresh_every:
            try:
                self._page.goto(url, wait_until="domcontentloaded")
                self._last_recent_nav = now
                self._recent_ready = False
                self._recent_frame = None
                self._maybe_follow_succ_url()
            except Exception:
                pass

        if self._recent_ready:
            frame = self._get_recent_frame()
            if frame:
                return True
            self._recent_ready = False

        if bool(self.config.get("recent_wait_networkidle", False)):
            try:
                self._page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                pass

        wait_ms = int(self.config.get("recent_wait_ms") or 8000)
        frame = self._wait_for_recent_dom(wait_ms)
        if not frame:
            try:
                self._page.evaluate(
                    """
                    () => {
                      const candidates = Array.from(document.querySelectorAll('a,button'));
                      const recent = candidates.find(el => (el.innerText || '').trim().toLowerCase() === 'recent');
                      if (recent) recent.click();
                    }
                    """
                )
                self._page.wait_for_timeout(800)
            except Exception:
                pass
            frame = self._wait_for_recent_dom(3000)

        if frame:
            self._recent_ready = True
            self._recent_frame = frame
            return True

        self._record_recent_missing()
        return False

    def _fetch_verified_html(self, wait_ms: Optional[int] = None) -> Optional[str]:
        url = self.config.get("verified_url") or self.DEFAULT_VERIFIED_URL
        html = None
        if self.config.get("use_browser", True) and self._ensure_browser():
            # In headful mode, prefer HTTP to avoid flashing a visible verified tab.
            if self.config.get("headless") is False:
                html = self._fetch_page(url)
                if html and self._page_logged_in(html):
                    return html
                # Refresh cookies from the browser and retry HTTP once.
                if self._refresh_cookies_from_browser():
                    html = self._fetch_page(url)
                    if html:
                        return html
                return None
            page = None
            try:
                page = self._context.new_page()
                page.goto(url, wait_until="domcontentloaded")
                delay_ms = int(wait_ms if wait_ms is not None else (self.config.get("verify_render_wait_ms") or 0))
                if delay_ms > 0:
                    page.wait_for_timeout(delay_ms)
                html = page.content()
            except Exception as exc:
                self.record_error(f"verify_tab_{str(exc)[:50]}")
            finally:
                if page:
                    try:
                        page.close()
                    except Exception:
                        pass
        else:
            html = self._fetch_page(url)
        return html

    def _paginate_recent_page(self):
        if not self._ensure_browser():
            return
        pages = int(self.config.get("pagination_pages") or 1)
        if pages <= 1:
            return
        wait_ms = int(self.config.get("pagination_wait_ms") or self.config.get("render_wait_ms") or 1500)
        click_next_js = """
        () => {
          const selectors = [
            'a[rel=\"next\"]',
            '.pagination a.next',
            '.pagination .next a',
            'a.next',
            'button.next',
            'a[title=\"Next\"]',
            'button[title=\"Next\"]'
          ];
          for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (el) {
              el.click();
              return true;
            }
          }
          const candidates = Array.from(document.querySelectorAll('a,button'));
          const byText = candidates.find(el => {
            const t = (el.textContent || '').trim().toLowerCase();
            return t === 'next' || t === '>' || t === '»' || t === '›';
          });
          if (byText) {
            byText.click();
            return true;
          }
          return false;
        }
        """
        for _ in range(pages - 1):
            clicked = False
            try:
                clicked = bool(self._page.evaluate(click_next_js))
            except Exception:
                clicked = False
            if clicked:
                self._page.wait_for_timeout(wait_ms)
                continue
            try:
                self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                self._page.wait_for_timeout(wait_ms)
            except Exception:
                break

    def _fetch_recent_payload(self) -> Optional[dict]:
        url = self.config.get("recent_api_url") or self.DEFAULT_RECENT_API_URL
        headers = {
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
        }
        try:
            resp = self.session.get(url, headers=headers, timeout=self.REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            self.record_error(str(exc)[:200])
            return None
        if resp.status_code != 200:
            self.record_error(f"recent_api_http_{resp.status_code}")
            return None
        try:
            return resp.json()
        except Exception:
            text = (resp.text or "").lower()
            if "login" in text or "sign in" in text:
                self.record_error("login_required")
                self._refresh_cookies_from_browser()
            return None

    def _parse_recent_payload(self, payload: dict) -> List[Dict[str, str]]:
        if not isinstance(payload, dict):
            return []
        items = payload.get("DisplayList") or payload.get("displayList")
        if not items and isinstance(payload.get("data"), dict):
            items = payload["data"].get("DisplayList") or payload["data"].get("displayList")
        if not isinstance(items, list):
            return []

        top_only = bool(self.config.get("top_card_only"))
        top_count = int(self.config.get("top_card_count") or 1)
        top_only = bool(self.config.get("top_card_only"))
        top_count = int(self.config.get("top_card_count") or 1)
        max_new = max(int(self.config.get("max_new_per_cycle") or 0), 1)
        if top_only:
            max_new = max(top_count, 1)
        if top_only:
            max_new = max(top_count, 1)
        allow_unknown = bool(self.config.get("allow_unknown_age"))
        zero_only = bool(self.config.get("zero_second_only"))
        max_age = self.config.get("max_lead_age_seconds")
        # 0 or None means "no limit" - use 24 hours as effective max
        max_age = int(max_age) if max_age else 86400
        search_terms = [t.lower().strip() for t in (self.config.get("search_terms") or []) if t.strip()]
        exclude_terms = [t.lower().strip() for t in (self.config.get("exclude_terms") or []) if t.strip()]
        min_member_months = int(self.config.get("min_member_months") or 0)
        max_age_hours = int(self.config.get("max_age_hours") or 0)

        raw_countries = (self.config.get("country") or []) + (self.config.get("client_regions") or [])
        allowed_countries = set(c.lower() for c in raw_countries)

        leads: List[Dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            lead_id = str(
                item.get("ETO_OFR_ID")
                or item.get("BL_ID")
                or item.get("bl_id")
                or item.get("lead_id")
                or item.get("id")
                or ""
            ).strip()

            title = str(
                item.get("ETO_OFR_TITLE")
                or item.get("ETO_OFR_NAME")
                or item.get("PRODUCT_NAME")
                or item.get("SUBJECT")
                or item.get("ENQ_SUBJECT")
                or ""
            ).strip()

            age_label = item.get("BLDATETIME") or item.get("BLDateTime") or item.get("BL_DATE_TIME")
            age_seconds = self._parse_age_seconds(age_label)

            if zero_only:
                if age_seconds != 0:
                    continue
            else:
                if age_seconds is None and not allow_unknown:
                    continue
                if age_seconds is not None and age_seconds > max_age:
                    continue

            msg_country = str(
                item.get("S_COUNTRY") 
                or item.get("GLUSR_USR_COUNTRYNAME") 
                or item.get("SENDER_COUNTRY")
                or ""
            ).strip().lower()
            msg_country_code = str(item.get("ISO") or "").strip().lower()

            # Country Filter (API)
            if allowed_countries:
                if msg_country:
                    match_found = False
                    country_tokens = set(re.split(r"\W+", msg_country))

                    for allowed in allowed_countries:
                        allowed = allowed.strip().lower()
                        if not allowed:
                            continue

                        if msg_country_code and allowed == msg_country_code:
                            match_found = True
                            break

                        if len(allowed) <= 3:
                            if allowed in country_tokens:
                                match_found = True
                                break
                        else:
                            if allowed in msg_country:
                                match_found = True
                                break

                    if not match_found:
                        continue

            
            purchase_status = str(item.get("PURCHASE_STATUS") or item.get("purchase_status") or "").strip()
            buy_url, detail_url = self._extract_urls_from_item(item)
            
            # Fallback: construct URLs from lead_id if not extracted
            if not buy_url and not detail_url and lead_id:
                detail_url = f"https://seller.indiamart.com/bltxn/default/bl/{lead_id}/"
                buy_url = detail_url

            title_lower = title.lower()
            if exclude_terms and any(ex in title_lower for ex in exclude_terms):
                continue
            if search_terms and not any(term in title_lower for term in search_terms):
                continue

            # Quality filters
            member_since = item.get("MBSINCE") or item.get("mbsince") or ""
            months = self._parse_member_months(member_since)
            if min_member_months and (months is None or months < min_member_months):
                continue
            if max_age_hours and age_seconds is not None and age_seconds > max_age_hours * 3600:
                continue

            lead = {
                "lead_id": lead_id or None,
                "title": title[:140] if title else None,
                "detail_url": detail_url,
                "buy_url": buy_url,
                "country": msg_country.title() if msg_country else None,
                "country_code": msg_country_code.upper() if msg_country_code else None,
                "source": "indiamart_seller",
                "status": "captured",
                "age_label": age_label,
                "age_seconds": age_seconds,
                "purchase_status": purchase_status or None,
            }

            leads.append({k: v for k, v in lead.items() if v is not None})
            if len(leads) >= max_new:
                break

        return leads

    def _collect_dom_leads(self) -> List[Dict[str, str]]:
        if not self._ensure_browser():
            return []
        top_only = bool(self.config.get("top_card_only"))
        top_count = int(self.config.get("top_card_count") or 1)
        max_new = max(int(self.config.get("max_new_per_cycle") or 0), 1)
        if top_only:
            max_new = max(top_count, 1)
        else:
            self._paginate_recent_page()

        frame = self._get_recent_frame()
        if not frame and top_only:
            if not self._ensure_recent_page():
                return []
            frame = self._get_recent_frame()
        if not frame:
            return []
        allow_unknown = bool(self.config.get("allow_unknown_age"))
        zero_only = bool(self.config.get("zero_second_only"))
        require_mobile = bool(self.config.get("require_mobile_available"))
        require_mobile_verified = bool(self.config.get("require_mobile_verified"))
        require_email_available = bool(self.config.get("require_email_available"))
        require_email = bool(self.config.get("require_email_verified"))
        require_whatsapp = bool(self.config.get("require_whatsapp_available"))
        max_age = self.config.get("max_lead_age_seconds")
        # 0 or None means "no limit" - use 24 hours as effective max
        max_age = int(max_age) if max_age else 86400
        
        raw_countries = (self.config.get("country") or []) + (self.config.get("client_regions") or [])
        allowed_countries = [c.lower() for c in raw_countries]
        
        # BULLETPROOF DOM SCRAPING - Enhanced with deep analysis findings
        js = """
        (opts) => {
          const normalize = (text) => (text || '').replace(/\\s+/g, ' ').trim();
          const clean = (val) => {
            const v = normalize(val);
            if (!v) return null;
            if (v.toLowerCase() === 'null') return null;
            return v;
          };
          const pickValue = (selectors, root) => {
            for (const sel of selectors) {
              const el = root.querySelector(sel);
              if (!el) continue;
              const val = el.value !== undefined ? el.value : el.getAttribute('value');
              const cleaned = clean(val);
              if (cleaned) return cleaned;
            }
            return null;
          };
          const pickText = (selectors, root) => {
            for (const sel of selectors) {
              const el = root.querySelector(sel);
              if (!el) continue;
              const cleaned = clean(el.textContent || el.innerText || '');
              if (cleaned) return cleaned;
            }
            return null;
          };
          const ageToSeconds = (text) => {
            if (!text) return null;
            const t = text.toLowerCase();
            if (t.includes('just now')) return 0;
            const m = t.match(/(\\d+)\\s*(sec|s|second|seconds|min|mins|minute|minutes|hr|hrs|hour|hours)/);
            if (!m) return null;
            const val = parseInt(m[1], 10);
            const unit = m[2];
            if (unit.startsWith('s')) return val;
            if (unit.startsWith('min')) return val * 60;
            if (unit.startsWith('h')) return val * 3600;
            return null;
          };
          const extractOrderDetails = (card) => {
            const details = {};
            const rows = card.querySelectorAll('.lstNwLftBtmCnt tr');
            rows.forEach((row) => {
              const cells = row.querySelectorAll('td');
              if (!cells || cells.length < 2) return;
              const label = normalize(cells[0].textContent || '').replace(/:$/, '');
              let value = normalize(cells[1].textContent || '');
              value = value.replace(/^:\\s*/, '');
              if (label && value) details[label] = value;
            });
            return details;
          };
          const findLeadHref = (card) => {
            const anchors = Array.from(card.querySelectorAll('a[href]'));
            const leadAnchor = anchors.find(a => {
              const href = (a.getAttribute('href') || '').toLowerCase();
              return href.includes('/bl/') || href.includes('bltxn') || href.includes('lead');
            });
            return leadAnchor ? leadAnchor.getAttribute('href') : '';
          };
          
          // Target .bl_grid parent containers (most stable)
          let leadContainers = Array.from(document.querySelectorAll('.bl_grid, #bl_listing .bl_grid'));
          const listOne = document.querySelector('#list1');
          if (opts.topOnly) {
            if (listOne) {
              leadContainers = [listOne];
            } else {
              leadContainers = leadContainers.slice(0, opts.topCount || 1);
            }
          }
          const results = [];
          
          for (const container of leadContainers) {
            if (results.length >= opts.maxNew) break;
            
            // Skip shimmer/skeleton placeholders
            if (container.querySelector('.secshimmer')) continue;
            
            const card = container.querySelector('.lstNw') || container;
            const containerId = (container.getAttribute('id') || '').toLowerCase();
            const topRankMatch = containerId.match(/^list(\\d+)/);
            const topRank = topRankMatch ? parseInt(topRankMatch[1], 10) : null;
            const isTop = containerId === 'list1' || topRank === 1 || (opts.topOnly && results.length === 0);
            
            // Extract lead ID from hidden input (MOST RELIABLE)
            let leadId = pickValue(['input[name="ofrid"]', 'input[id^="ofrid"]'], card);
            // Fallbacks: data attributes or href patterns
            if (!leadId) {
              const dataAttrs = ['data-blid','data-bl_id','data-leadid','data-lead_id','data-rfq_id','data-enqid','data-enquiryid','data-inquiryid'];
              for (const attr of dataAttrs) {
                const val = card.getAttribute(attr) || container.getAttribute(attr);
                if (val) { leadId = clean(val); break; }
              }
            }
            if (!leadId) {
              const href = (findLeadHref(card) || '').toLowerCase();
              let m = href.match(/(?:blid|bl_id|leadid|lead_id|rfq_id|enqid|enquiryid|inquiryid)=(\\d+)/i);
              if (!m) {
                const digits = href.match(/(\\d{4,})/);
                if (digits) m = digits;
              }
              if (m) leadId = m[1];
            }
            
            // Get title from multiple possible selectors
            const titleInput = pickValue(['input[name="ofrtitle"]', 'input[id^="ofrtitle"]'], card);
            const titleEl = card.querySelector('h2, .bl_title, .lst_title') || container.querySelector('h2');
            const title = clean(titleInput || (titleEl ? titleEl.textContent : ''))?.slice(0, 140) || null;
            if (!title || title.length < 3) continue;
            
            // Extract country/location
            // (Moved down to be after title extraction but before filtering)
            // (Refactored into main flow)
            
            // Extract age from text content
            const ageLabel = pickText(['.lstNwLftLoc strong', '.lstNwLftLoc span', '.lstNwLftLoc p strong', '.lstNwLftLoc', 'p > strong'], card);
            const ageMatch = (ageLabel || card.textContent || '').match(/(\\d+\\s*(?:sec|s|second|seconds|min|mins|minute|minutes|hr|hrs|hour|hours)|just now)/i);
            const ageSeconds = ageToSeconds(ageMatch ? ageMatch[0] : null);
            
            // Note: age filtering is done in Python so we can log rejections
            
            // Country Filter
            let country = null;
            let countryCode = null;
            const countryInput = card.querySelector('input[name^="card_country"], input[id^="card_country_"]');
            if (countryInput) {
              country = clean(countryInput.value) || clean(countryInput.getAttribute('value'));
              countryCode = clean(countryInput.getAttribute('data-val'));
            }
            if (!country) {
              const countrySpan = card.querySelector('.coutry_click, .tcont') || container.querySelector('.coutry_click, .tcont');
              if (countrySpan) country = normalize(countrySpan.textContent);
            }
            if (!countryCode) {
              countryCode = pickValue(['input[name="flag_iso"]', 'input[id^="flag_iso"]'], card);
            }
            
            // Country filtering is handled in Python (for rejection logging)

            // Check for Contact Buyer Now button
            const btnCBN = container.querySelector('.btnCBN') ||
                           container.querySelector('.Slid_CTA span, .Slid_CTA button, .Slid_CTA a') ||
                           Array.from(container.querySelectorAll('a,button,span,div[role="button"]')).find(el => {
                             const t = (el.innerText || el.textContent || '').toLowerCase();
                             return t.includes('contact buyer') || t.includes('contact') || t.includes('buy now');
                           });
            const hasBuy = !!btnCBN;
            
            // Extract URL if available
            let url = findLeadHref(card);
            // Normalize URL - handle protocol-relative and relative paths
            if (url) {
              if (url.startsWith('//') && !url.startsWith('///')) {
                url = 'https:' + url;
              } else if (url.startsWith('/') && !url.startsWith('//')) {
                url = location.origin + url;
              }
              // Clean double-domain bug
              url = url.replace(/^(https?:)?\\/\\/seller\\.indiamart\\.com\\/+seller\\.indiamart\\.com\\//i, 'https://seller.indiamart.com/');
              url = url.replace(/(https?:\\/\\/seller\\.indiamart\\.com)\\/+seller\\.indiamart\\.com\\//i, '$1/');
            }
            
            const city = pickValue(['input[id^="card_city_"]', 'input[name^="card_city"]'], card);
            const state = pickValue(['input[id^="card_state_"]', 'input[name^="card_state"]'], card);
            const mcatName = pickValue(['input[name="mcatname"]', 'input[id^="mcatname"]'], card) || pickText(['.Mcat_buylead'], card);
            const parentMcat = pickValue(['input[name="parent_mcatname"]', 'input[id^="parent_mcatname"]'], card);
            const memberSince = pickText(['.lstNwRgtBD .SLC_f13', '.SLC_f13'], card) || pickText(['.lstNwRgtBD .SLC_f13', '.SLC_f13'], container);
            const buyerDetailsEl = card.querySelector('.lstNwRgtBD');
            const buyerDetailsText = clean(buyerDetailsEl ? buyerDetailsEl.innerText : '');
            const availabilityText = (buyerDetailsText || '').toLowerCase();
            // Fallback text-based detection (less reliable than tooltips)
            let mobileAvailable = availabilityText.includes('mobile number is available') || availabilityText.includes('mobile number available');
            let mobileVerified = availabilityText.includes('mobile number is verified') || availabilityText.includes('phone number is verified');
            let emailAvailable = availabilityText.includes('email id is available') || availabilityText.includes('email available');
            let emailVerified = availabilityText.includes('email id is verified') || availabilityText.includes('email verified');
            let whatsappAvailable = availabilityText.includes('whatsapp available');

            // Tooltip/icon-based detection (reliable): IndiaMart uses `.tooltip_vfr` nodes.
            // These exist in DOM without hover and are the source of the UI hover text.
            const iconRoot = buyerDetailsEl || card;
            const tipNodes = iconRoot ? Array.from(iconRoot.querySelectorAll('.tooltip_vfr')) : [];
            const tips = tipNodes
              .map(n => clean(n.textContent || n.innerText || ''))
              .filter(Boolean)
              .map(t => t.toLowerCase());
            const has = (needle) => tips.some(t => t.includes(needle));
            const hasPair = (a, b) => tips.some(t => t.includes(a) && t.includes(b));

            if (has('whatsapp')) whatsappAvailable = true;
            if (has('email')) emailAvailable = true;
            if (hasPair('email', 'verified')) emailVerified = true;
            if (has('mobile') || has('phone')) mobileAvailable = true;
            if (hasPair('mobile', 'verified') || hasPair('phone', 'verified')) mobileVerified = true;

            // If verified, it implies available.
            if (emailVerified) emailAvailable = true;
            if (mobileVerified) mobileAvailable = true;
            
            // Mobile/email filtering handled in Python (for rejection logging)
            const orderDetailsText = clean((card.querySelector('.lstNwLftBtmCnt') || {}).innerText || '');
            const orderDetails = extractOrderDetails(card);
            const rawText = normalize(card.innerText || card.textContent || '');
            const phoneMatch = rawText.match(/\\+?\\d[\\d\\s-]{7,}\\d/);
            const emailMatch = rawText.match(/[\\w.+-]+@[\\w-]+\\.[\\w.-]+/);
            const mobile = phoneMatch ? phoneMatch[0] : null;
            const email = emailMatch ? emailMatch[0].toLowerCase() : null;
            
            results.push({
              lead_id: leadId,
              title,
              url,
              detail_url: url,
              country,
              country_code: countryCode,
              city,
              state,
              mcat_name: mcatName,
              parent_mcat_name: parentMcat,
              member_since: memberSince,
              buyer_details_text: buyerDetailsText,
              order_details_text: orderDetailsText,
              order_details: Object.keys(orderDetails).length ? orderDetails : null,
              mobile_available: mobileAvailable,
              mobile_verified: mobileVerified,
              email_available: emailAvailable,
              email_verified: emailVerified,
              whatsapp_available: whatsappAvailable,
              mobile,
              email,
              age_label: ageLabel,
              age_seconds: ageSeconds,
              has_buy: hasBuy,
              top_card: isTop,
              top_rank: topRank
            });
          }
          
          return results;
        }
        """
        try:
            leads = frame.evaluate(js, {
                "maxNew": max_new,
                "allowUnknown": allow_unknown,
                "zeroOnly": zero_only,
                "maxAge": max_age,
                "allowedCountries": allowed_countries,
                "requireMobile": require_mobile,
                "requireEmail": require_email,
                "topOnly": top_only,
                "topCount": top_count,
            }) or []
            for lead in leads:
                lead_id = lead.get("lead_id")
                detail_url = lead.get("detail_url") or lead.get("url")
                if lead_id and not detail_url:
                    detail_url = f"https://seller.indiamart.com/bltxn/default/bl/{lead_id}/"
                    lead["detail_url"] = detail_url
                if detail_url and not lead.get("url"):
                    lead["url"] = detail_url
                if detail_url and not lead.get("buy_url"):
                    lead["buy_url"] = detail_url
            return leads
        except Exception as exc:
            self.record_error(str(exc)[:200])
            return []

    def _click_buy_leads_in_browser(self, leads: List[Dict[str, str]]) -> List[str]:
        if not self._ensure_browser():
            return []
        max_clicks = int(
            self.config.get("max_verified_leads_per_cycle")
            or self.config.get("max_clicks_per_cycle")
            or 0
        )
        if max_clicks <= 0:
            return []
        max_age = self.config.get("max_lead_age_seconds")
        max_age = int(max_age) if max_age is not None else 0
        allow_unknown = bool(self.config.get("allow_unknown_age"))
        allowed_countries = [c.lower() for c in (self.config.get("country") or [])]
        
        js = r"""
        (opts) => {
          const normalize = (text) => (text || '').replace(/\\s+/g, ' ').trim();
          const ageToSeconds = (text) => {
            if (!text) return null;
            const t = text.toLowerCase();
            if (t.includes('just now')) return 0;
            const m = t.match(/(\\d+)\\s*(sec|s|second|seconds|min|mins|minute|minutes|hr|hrs|hour|hours)/);
            if (!m) return null;
            const val = parseInt(m[1], 10);
            const unit = m[2];
            if (unit.startsWith('s')) return val;
            if (unit.startsWith('min')) return val * 60;
            if (unit.startsWith('h')) return val * 3600;
            return null;
          };
          const extractLeadId = (html) => {
            const patterns = [
              /blid=(\\d+)/i,
              /bl_id=(\\d+)/i,
              /leadid=(\\d+)/i,
              /lead_id=(\\d+)/i,
              /rfq_id=(\\d+)/i,
              /enqid=(\\d+)/i,
              /enquiryid=(\\d+)/i,
              /inquiryid=(\\d+)/i,
              /\\/bl\\/(\\d+)/i,
              /\\/lead\\/(\\d+)/i
            ];
            for (const p of patterns) {
              const m = html.match(p);
              if (m) return m[1];
            }
            return null;
          };
          const candidates = new Set();
          document.querySelectorAll('[data-blid],[data-bl_id],[data-leadid],[data-lead_id],[data-rfq_id],[data-enqid],[data-enquiryid],[data-inquiryid]').forEach(el => {
            candidates.add(el.closest('li, tr, div') || el);
          });
          document.querySelectorAll('a,button').forEach(el => {
            const text = normalize(el.textContent || '');
            if (/buy/i.test(text)) {
              candidates.add(el.closest('li, tr, div') || el);
            }
          });
          const clicked = [];
          let clicks = 0;
          for (const card of candidates) {
            if (clicks >= opts.maxClicks) break;
            const html = card.innerHTML || '';
            const leadId = extractLeadId(html);
            const ageMatch = (card.textContent || '').match(/(\\d+\\s*(?:sec|s|second|seconds|min|mins|minute|minutes|hr|hrs|hour|hours)|just now)/i);
            const ageSeconds = ageToSeconds(ageMatch ? ageMatch[0] : null);
            if (ageSeconds === null && !opts.allowUnknown) continue;
            if (ageSeconds !== null && ageSeconds > opts.maxAge) continue;
            // Broader selector in case it's not a standard button
            const candidates = Array.from(card.querySelectorAll('a,button,input[type="button"],input[type="submit"],div[role="button"],span[role="button"]'));
            const buyEl = candidates.find(el => {
              const text = (el.textContent || el.value || '').trim();
              return /(buy|contact|purchase|view|get)/i.test(text) || /contact buyer now/i.test(text);
            });
            if (!buyEl) continue;

            // Country Filter (Clicking)
            if (opts.allowedCountries && opts.allowedCountries.length > 0) {
                let country = null;
                const countryInput = card.querySelector('input[name^="card_country"]');
                if (countryInput) {
                  country = countryInput.value;
                } else {
                  const countrySpan = card.querySelector('.coutry_click, .tcont');
                  if (countrySpan) country = normalize(countrySpan.textContent);
                }
                
                if (country) {
                    const cLower = country.toLowerCase();
                    const match = opts.allowedCountries.some(ac => cLower === ac || cLower.includes(ac) || ac.includes(cLower));
                    if (!match) continue;
                }
            }

            try {
              buyEl.scrollIntoView({block: 'center'});
              buyEl.click();
              clicks += 1;
              clicked.push(leadId || (buyEl.getAttribute('href') || ''));
            } catch (err) {
              continue;
            }
          }
          return clicked;
        }
        """
        try:
            return self._page.evaluate(js, {
                "maxClicks": max_clicks,
                "maxAge": max_age,
                "allowUnknown": allow_unknown,
                "allowedCountries": allowed_countries,
            }) or []
        except Exception as exc:
            self.record_error(str(exc)[:200])
            return []

    def _fetch_page(self, url: str) -> Optional[str]:
        last_error = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                resp = self.session.get(url, timeout=self.REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    self.update_metrics(last_error=None)
                    return resp.text
                last_error = f"HTTP {resp.status_code}"
            except requests.RequestException as exc:
                last_error = str(exc)

            time.sleep(min(2 * attempt, 6))

        if last_error:
            self.record_error(last_error[:200])
        return None

    def _parse_recent_leads(self, html: str) -> List[Dict[str, str]]:
        leads = []
        seen = set()
        max_new = max(int(self.config.get("max_new_per_cycle") or 0), 1)

        for match in self.ANCHOR_PATTERN.finditer(html or ""):
            href = match.group(1) or ""
            if not self._looks_like_lead_link(href):
                continue
            title = self._strip_tags(match.group(2))
            if not title:
                continue

            lead_id = self._extract_id_from_url(href)
            if not lead_id:
                data_match = self.DATA_ID_PATTERN.search(match.group(0))
                lead_id = data_match.group(1) if data_match else None

            url = self._normalize_url(href)
            key = lead_id or url
            if key in seen:
                continue
            seen.add(key)

            leads.append({
                "lead_id": lead_id,
                "title": title[:140],
                "url": url,
                "detail_url": url,
                "source": "indiamart_seller",
                "status": "captured",
            })

            if len(leads) >= max_new:
                break

        if leads:
            return leads

        for lead_id in self._extract_ids(html or "")[:max_new]:
            leads.append({
                "lead_id": lead_id,
                "title": f"Lead {lead_id}",
                "source": "indiamart_seller",
                "status": "captured",
            })
        return leads

    def _parse_verified(self, html: str) -> Tuple[set, set, set]:
        """
        Parse Past Transactions page to find verified leads.
        
        Returns: (verified_ids, verified_contacts, verified_titles)
        - verified_ids: set of lead IDs (if found via patterns)
        - verified_contacts: set of (phone, email) tuples from purchased leads
        - verified_titles: set of purchased lead titles (fallback match)
        
        Strategy: Past Transactions page is a React SPA that doesn't expose
        lead IDs in DOM. We extract buyer phone/email for matching instead.
        """
        # Try standard ID patterns first (may catch some)
        ids = set(self._extract_ids(html or ""))
        
        # Also extract phone/email from ConLead_cont cards for matching
        verified_contacts = set()
        
        # Parse ConLead_cont sections for buyer details
        # Pattern: each card contains Mobile: xxx and Email: xxx
        for phone_match in self.PHONE_PATTERN.finditer(html or ""):
            phone = phone_match.group(0).strip()
            if phone and len(phone) > 8:
                verified_contacts.add(("phone", phone))
        
        for email_match in self.EMAIL_PATTERN.finditer(html or ""):
            email = email_match.group(0).strip().lower()
            if email and "@" in email and "." in email:
                verified_contacts.add(("email", email))

        # Extract titles from purchased lead cards
        verified_titles = set()
        for match in re.finditer(r'<span[^>]*class="[^"]*SLC_f20[^"]*SLC_fwb[^"]*"[^>]*>(.*?)</span>', html or "", re.IGNORECASE | re.DOTALL):
            title = self._strip_tags(match.group(1))
            if title:
                verified_titles.add(title.strip())
        
        # Legacy URL extraction (may not be useful for this page)
        urls = set()
        for match in self.ANCHOR_PATTERN.finditer(html or ""):
            href = match.group(1) or ""
            if not self._looks_like_lead_link(href):
                continue
            urls.add(self._normalize_url(href))
        
        # Store contacts for later matching
        self.state["verified_contacts"] = list(verified_contacts)
        self.state["verified_titles"] = list(verified_titles)
        
        print(f"[WORKER] Verification parsed: {len(ids)} IDs, {len(verified_contacts)} contacts, {len(verified_titles)} titles")
        
        return ids, urls, verified_titles

    def _click_leads(self, leads: List[Dict[str, str]]) -> int:
        max_clicks = int(
            self.config.get("max_verified_leads_per_cycle")
            or self.config.get("max_clicks_per_cycle")
            or 0
        )
        if max_clicks <= 0:
            return 0

        clicks = 0
        for lead in leads:
            if clicks >= max_clicks:
                break
            url = lead.get("detail_url") or lead.get("url")
            if not url:
                continue
            try:
                resp = self.session.get(url, timeout=self.REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    lead["status"] = "clicked"
                    lead["clicked_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    clicks += 1
                else:
                    self.record_error(f"click_http_{resp.status_code}")
            except requests.RequestException as exc:
                self.record_error(str(exc)[:200])
            time.sleep(0.4)
        return clicks

    def _purchase_leads(self, leads: List[Dict[str, str]]) -> int:
        max_clicks = int(
            self.config.get("max_verified_leads_per_cycle")
            or self.config.get("max_clicks_per_cycle")
            or 0
        )
        if max_clicks <= 0:
            return 0

        clicks = 0
        allow_detail = bool(self.config.get("allow_detail_click", False))
        for lead in leads:
            if lead.get("status") == "rejected":
                continue
            if clicks >= max_clicks:
                break
            target = lead.get("buy_url")
            if not target and allow_detail:
                target = lead.get("detail_url") or lead.get("url")
            if not target:
                continue
            try:
                resp = self.session.get(target, timeout=self.REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    lead["status"] = "clicked"
                    lead["clicked_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    lead["buy_attempt_url"] = target
                    lead["buy_attempt_status"] = resp.status_code
                    clicks += 1
                else:
                    lead["buy_attempt_url"] = target
                    lead["buy_attempt_status"] = resp.status_code
                    self.record_error(f"buy_http_{resp.status_code}")
            except requests.RequestException as exc:
                self.record_error(str(exc)[:200])
            time.sleep(0.4)
        return clicks

    def _click_leads_with_browser_navigation(self, leads: List[Dict[str, str]]) -> List[str]:
        """Click buttons using verified DOM pattern: card.closest('.bl_grid').querySelector('.btnCBN')"""
        if not self._ensure_browser():
            return []
        
        max_clicks = int(
            self.config.get("max_verified_leads_per_cycle")
            or self.config.get("max_clicks_per_cycle")
            or 0
        )
        if max_clicks <= 0:
            return []
        
        # Use JavaScript to click buttons - improved with multiple detection strategies
        js = """
        (opts) => {
            const leadIds = opts.leadIds || [];
            const maxClicks = opts.maxClicks || leadIds.length;
            const clicked = [];
            const missed = [];
            const topLeadId = opts.topLeadId || null;

            const textMatch = (el) => {
              const txt = (el.innerText || el.textContent || el.value || '').toLowerCase().trim();
              return txt.includes('contact buyer now') || txt.includes('contact buyer') || txt.includes('contact') || txt.includes('buy now') || txt === 'buy' || txt.includes('i am interested');
            };

            const findButton = (container) => {
              if (!container) return null;
              return container.querySelector('.Slid_CTA .btnCBN') ||
                     container.querySelector('.btnCBN') ||
                     container.querySelector('a[class*="contact"], button[class*="contact"]') ||
                     container.querySelector('a[class*="btn"], button') ||
                     Array.from(container.querySelectorAll('a, button, input[type="button"], input[type="submit"], div[role="button"], span[role="button"]')).find(textMatch) ||
                     null;
            };

            for (const id of leadIds) {
                if (clicked.length >= maxClicks) break;
                let btn = null;
                let container = null;

                // Strategy 1: Find via hidden input with ofrid matching lead ID
                const ofridInput = document.querySelector(`input[name="ofrid"][value="${id}"], input[id^="ofrid"][value="${id}"]`);
                if (ofridInput) {
                    container = ofridInput.closest('.bl_grid') || ofridInput.closest('.lstNw');
                    btn = findButton(container);
                }

                // Strategy 1b: Find via data-* attributes
                if (!btn) {
                    container = document.querySelector(`[data-blid="${id}"],[data-bl_id="${id}"],[data-leadid="${id}"],[data-lead_id="${id}"],[data-rfq_id="${id}"],[data-enqid="${id}"],[data-enquiryid="${id}"],[data-inquiryid="${id}"]`);
                    if (container) {
                        container = container.closest('.bl_grid') || container;
                        btn = findButton(container);
                    }
                }

                // Strategy 2: Find via anchor with href containing the lead ID
                if (!btn) {
                    const anchor = document.querySelector(`a[href*="${id}"]`);
                    if (anchor) {
                        let el = anchor;
                        for (let i = 0; i < 6 && !btn; i++) {
                            if (!el.parentElement) break;
                            el = el.parentElement;
                            btn = findButton(el);
                        }
                    }
                }

                // Strategy 3: Scan all .bl_grid containers for matching lead
                if (!btn) {
                    const allGrids = document.querySelectorAll('.bl_grid');
                    for (const grid of allGrids) {
                        const html = grid.innerHTML || "";
                        if (html.includes(id)) {
                            btn = findButton(grid);
                            if (btn) break;
                        }
                    }
                }

                if (btn) {
                    try {
                        btn.scrollIntoView({block: 'center', behavior: 'instant'});
                        btn.click();
                        clicked.push(id);
                        console.log('[CLICK] ✅ Successfully clicked lead:', id);
                    } catch (e) {
                        missed.push(id);
                        console.log('[CLICK] ❌ Click failed:', e);
                    }
                } else {
                    missed.push(id);
                    console.log('[CLICK] ❌ Button not found for lead:', id);
                }
            }
            // If top card is the accepted lead but has no usable ID, click it directly
            if (topLeadId && clicked.length < maxClicks) {
                const topContainer = document.querySelector('#list1') || document.querySelector('.bl_grid');
                const btn = findButton(topContainer) ||
                            document.querySelector('#list1 .Slid_CTA span') ||
                            document.querySelector('#list1 .Slid_CTA button') ||
                            document.querySelector('#list1 .Slid_CTA a');
                if (btn) {
                    try {
                        btn.scrollIntoView({block: 'center', behavior: 'instant'});
                        btn.click();
                        clicked.push(topLeadId);
                        console.log('[CLICK] ✅ Top card clicked:', topLeadId);
                    } catch (e) {
                        missed.push(topLeadId);
                        console.log('[CLICK] ❌ Top card click failed:', e);
                    }
                } else {
                    missed.push(topLeadId);
                    console.log('[CLICK] ❌ Top card button not found');
                }
            }
            return {clicked, missed};
        }
        """
        
        # Extract lead IDs from leads that need clicking
        # Extract lead IDs from leads that need clicking (Skip rejected)
        lead_ids_to_click = [
            lead.get("lead_id") for lead in leads
            if lead.get("lead_id")
            and not lead.get("lead_id_synthetic")
            and lead.get("status") != "rejected"
        ][:max_clicks]
        top_lead = next((l for l in leads if l.get("top_card") and l.get("status") != "rejected"), None)
        top_lead_id = None
        if top_lead and (top_lead.get("lead_id_synthetic") or not top_lead.get("lead_id")):
            top_lead_id = top_lead.get("lead_id") or "top_card"
        if not lead_ids_to_click and not top_lead_id:
            return []
        
        try:
            frame = self._get_recent_frame() if self.config.get("top_card_only") else None
            target = frame or self._page
            result = target.evaluate(js, {
                "leadIds": lead_ids_to_click,
                "maxClicks": max_clicks,
                "topLeadId": top_lead_id,
            }) or {}
            if isinstance(result, list):
                clicked_ids = result
                missed_ids = []
            else:
                clicked_ids = result.get("clicked") or []
                missed_ids = result.get("missed") or []
            
            # Mark leads as clicked
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            for lead in leads:
                if lead.get("lead_id") in clicked_ids:
                    lead["status"] = "clicked"
                    lead["clicked_at"] = now
                elif top_lead_id and lead.get("top_card") and lead.get("lead_id") == top_lead_id:
                    lead["status"] = "clicked"
                    lead["clicked_at"] = now
            
            print(f"[WORKER] ✅ Clicked {len(clicked_ids)} leads: {clicked_ids}")
            if missed_ids:
                self.record_error(f"click_missed:{len(missed_ids)}")
            return clicked_ids
            
        except Exception as exc:
            self.record_error(f"click_js:{str(exc)[:100]}")
            print(f"[WORKER] ❌ Click JS failed: {exc}")
            return []

    def _verify_clicked_leads(self, leads: List[Dict[str, str]], clicked_ids: List[str]) -> set:
        if not clicked_ids:
            return set()
        verify_delay = int(self.config.get("verify_after_click_seconds") or 0)
        verify_wait_ms = int(self.config.get("verify_render_wait_ms") or 0)
        verified_total = set()

        if verify_delay > 0:
            time.sleep(verify_delay)

        html = self._fetch_verified_html(wait_ms=verify_wait_ms)
        if not html:
            return verified_total
        if not self._page_logged_in(html):
            self.record_error("login_required")
            self._refresh_cookies_from_browser()

        verified_ids, verified_urls, verified_titles = self._parse_verified(html or "")
        newly_verified = self._apply_verification(
            leads,
            verified_ids,
            verified_urls,
            verified_titles,
            only_lead_ids=set(clicked_ids),
        )
        if newly_verified:
            verified_total.update(newly_verified)
            try:
                mark_leads_as_verified(self.slot_dir.name, newly_verified)
            except Exception as e:
                self.record_error(f"db_verify_err: {e}")

        return verified_total

    def _apply_verification(
        self,
        leads: List[Dict[str, str]],
        verified_ids: set,
        verified_urls: set,
        verified_titles: Optional[set] = None,
        only_lead_ids: Optional[set] = None,
    ) -> set:
        """
        Mark leads as verified using multiple matching strategies:
        1. Match by lead_id (if found in Past Transactions page)
        2. Match by URL (legacy)
        3. Match by phone/email (new - for React SPA compatibility)
        """
        if not leads:
            return set()
        
        # Get verified contacts from state (set by _parse_verified)
        verified_contacts = set(tuple(c) for c in self.state.get("verified_contacts", []))
        verified_phones = {c[1] for c in verified_contacts if c[0] == "phone"}
        verified_emails = {c[1].lower() for c in verified_contacts if c[0] == "email"}
        verified_titles_norm = set()
        if verified_titles:
            for title in verified_titles:
                normalized = re.sub(r"[^a-z0-9]+", " ", str(title).lower()).strip()
                if normalized:
                    verified_titles_norm.add(normalized)
        
        verified_count = 0
        verified_lead_ids = set()
        
        for lead in leads:
            lead_id = str(lead.get("lead_id") or "").strip()
            if only_lead_ids and lead_id not in only_lead_ids:
                continue
            url = str(lead.get("detail_url") or lead.get("url") or "").strip()
            
            # Get lead's contact info
            lead_phone = str(lead.get("mobile") or lead.get("phone") or "").strip()
            lead_email = str(lead.get("email") or "").strip().lower()
            lead_title = str(lead.get("title") or "").strip().lower()
            lead_title_norm = re.sub(r"[^a-z0-9]+", " ", lead_title).strip()
            
            is_verified = False
            
            # Strategy 1: Match by lead_id
            if lead_id and lead_id in verified_ids:
                is_verified = True
            
            # Strategy 2: Match by URL
            elif url and url in verified_urls:
                is_verified = True
            
            # Strategy 3: Match by phone (10-digit match for accuracy)
            elif lead_phone and len(lead_phone) > 6:
                for vp in verified_phones:
                    # Strip all non-digits and compare last 10 digits
                    clean_lead = ''.join(c for c in lead_phone if c.isdigit())
                    clean_verified = ''.join(c for c in vp if c.isdigit())
                    if len(clean_lead) >= 10 and len(clean_verified) >= 10:
                        if clean_lead[-10:] == clean_verified[-10:]:
                            is_verified = True
                            break
            
            # Strategy 4: Match by email
            elif lead_email and lead_email in verified_emails:
                is_verified = True
            
            # Strategy 5: Match by title (fallback)
            elif lead_title_norm and verified_titles_norm:
                for vt in verified_titles_norm:
                    if lead_title_norm == vt:
                        is_verified = True
                        break
                    if len(lead_title_norm) >= 8 and (lead_title_norm in vt or vt in lead_title_norm):
                        is_verified = True
                        break
            
            if is_verified:
                lead["status"] = "verified"
                lead["verified_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                verified_count += 1
                if lead_id:
                    verified_lead_ids.add(lead_id)
        
        if verified_count > 0:
            print(f"[WORKER] Verified {verified_count} leads via matching")
        return verified_lead_ids

    def _persist_leads(self, leads: List[Dict[str, str]]):
        if not leads:
            return

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        
        saved_count = 0
        # Save to SQLite
        for lead in leads:
            lead_key = self._lead_key(lead)
            # Skip leads without ID to avoid primary key constraint errors
            if not lead.get("lead_id"):
                 continue

            payload = {
                **lead,
                "lead_key": lead_key,
                "slot_id": self.slot_dir.name,
                "fetched_at": lead.get("fetched_at") or now,
            }
            try:
                save_lead_to_db(payload, self.slot_dir.name)
                saved_count += 1
            except Exception as e:
                self.record_error(f"db_save_err: {e}")

        # Keep DB persistence separate from "leads_parsed" metrics.
        # "leads_parsed" is updated in _parse_recent_phase based on unique, qualifying leads.
        if saved_count:
            try:
                state = self.load_state()
                state["updated_at"] = now
                self.write_state(state)
            except Exception:
                pass

    # ---------- Phase handlers ---------- #

    def adaptive_sleep(self, base=0.1):
        """Override: Always use minimal sleep for speed (100ms)"""
        return 0.1  # Always fast, no adaptive slowdown

    def _enter_cooldown(self, reason: str):
        configured = self.config.get("cooldown_seconds")
        cooldown = configured if isinstance(configured, (int, float)) and configured >= 0 else self.compute_cooldown()
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
        self.state["phase"] = "FETCH_RECENT"
        self._record_action("init", "FETCH_RECENT")
        # Quick login probe to update slot_state for UI
        try:
            status = self._probe_login_status()
            state = self.load_state()
            state["login_status"] = status.get("status")
            state["login_checked_at"] = status.get("checked_at")
            self.write_state(state)
        except Exception:
            pass

    def _probe_login_status(self) -> dict:
        url = self.config.get("recent_url") or self.DEFAULT_RECENT_URL
        session = self.session or self._build_session()
        try:
            resp = session.get(url, timeout=(4, 10))
        except Exception as exc:
            return {"status": "unknown", "reason": str(exc)[:80], "checked_at": None}
        html = (resp.text or "").lower()
        markers_in = ["bl_listing", "contact buyer now", "past transactions", "buyleads"]
        markers_out = ["free registration", "start selling", "sell on indiamart", "sign in"]
        logged_in = any(m in html for m in markers_in)
        logged_out = any(m in html for m in markers_out)
        status = "unknown"
        if logged_in and not logged_out:
            status = "logged_in"
        elif logged_out and not logged_in:
            status = "logged_out"
        return {"status": status, "checked_at": datetime.now(timezone.utc).isoformat()}

    def _fetch_recent_phase(self):
        url = self.config.get("recent_url") or self.DEFAULT_RECENT_URL
        self._record_action("fetch_recent", "FETCH_RECENT")
        self.config = self._load_config()
        self._quality_level = int(self.config.get("quality_level") or 70)
        self._maybe_reload_cookies()
        prefer_api = bool(self.config.get("prefer_api", False))
        if (
            self.config.get("require_mobile_available")
            or self.config.get("require_mobile_verified")
            or self.config.get("require_email_available")
            or self.config.get("require_email_verified")
            or self.config.get("require_whatsapp_available")
        ):
            prefer_api = False
        payload = None
        if prefer_api:
            print("[WORKER] Recent fetch mode: API")
            payload = self._fetch_recent_payload()
        if payload:
            self.state["recent_payload"] = payload
            self._snapshot_json("recent_payload", payload)
            metrics = self.load_state().get("metrics", {})
            self.update_metrics(pages_fetched=metrics.get("pages_fetched", 0) + 1, phase="PARSE_RECENT")
            self.state["phase"] = "PARSE_RECENT"
            return
        # Force DOM path when prefer_api is false
        self.state["recent_payload"] = None
        print("[WORKER] Recent fetch mode: DOM")

        use_browser = self.config.get("use_browser", True)
        if use_browser and self.config.get("top_card_only"):
            if not self._ensure_recent_page():
                self._enter_cooldown("top_card_missing")
                return
            self.state["recent_html"] = None
            metrics = self.load_state().get("metrics", {})
            self.update_metrics(pages_fetched=metrics.get("pages_fetched", 0) + 1, phase="PARSE_RECENT")
            self.state["phase"] = "PARSE_RECENT"
            return

        html = self._render_page(url) if use_browser else self._fetch_page(url)
        if not html:
            self._enter_cooldown("fetch_recent_failed")
            return
        if not self._page_logged_in(html):
            self.record_error("login_required")
            self._refresh_cookies_from_browser()
        if self.config.get("top_card_only"):
            if 'id="list1"' not in html and "id='list1'" not in html and "list1" not in html:
                # Try forcing the Recent tab and re-check
                try:
                    self._page.evaluate(
                        """
                        () => {
                          const candidates = Array.from(document.querySelectorAll('a,button'));
                          const recent = candidates.find(el => (el.innerText || '').trim().toLowerCase() === 'recent');
                          if (recent) recent.click();
                        }
                        """
                    )
                    self._page.wait_for_timeout(800)
                    html = self._page.content()
                except Exception:
                    pass
                if 'id="list1"' not in html and "id='list1'" not in html and "list1" not in html:
                    try:
                        page_url = self._page.url
                        page_title = self._page.title()
                        snippet = ""
                        try:
                            snippet = self._page.evaluate("() => (document.body && document.body.innerText || '').slice(0,200)") or ""
                        except Exception:
                            pass
                        self.record_error(f"top_card_missing:{page_url}:{page_title}:{snippet}")
                        try:
                            self._page.screenshot(path=str(self.slot_dir / "top_card_missing.png"), full_page=True)
                        except Exception:
                            pass
                    except Exception:
                        self.record_error("top_card_missing")
        self.state["recent_html"] = html
        self._snapshot_html("recent_snapshot", html)
        metrics = self.load_state().get("metrics", {})
        self.update_metrics(pages_fetched=metrics.get("pages_fetched", 0) + 1, phase="PARSE_RECENT")
        self.state["phase"] = "PARSE_RECENT"

    def _parse_recent_phase(self):
        payload = self.state.get("recent_payload")
        html = self.state.get("recent_html")
        leads: List[Dict[str, str]] = []
        if payload is not None:
            leads = self._parse_recent_payload(payload)
        else:
            if self.config.get("use_browser", True):
                leads = self._collect_dom_leads()
                top_only = bool(self.config.get("top_card_only"))
                if not leads and html and not top_only:
                    leads = self._parse_recent_leads(html)
            else:
                leads = self._parse_recent_leads(html or "")
        self.state["recent_html"] = None
        self.state["recent_payload"] = None

        if not leads:
            self._enter_cooldown("no_recent_leads")
            return
        raw_count = len(leads)

        # Ensure every lead has a stable ID for logging/persistence
        for lead in leads:
            if lead.get("lead_id"):
                continue
            basis = {
                "title": lead.get("title") or "",
                "country": lead.get("country") or "",
                "age_seconds": lead.get("age_seconds"),
                "detail_url": lead.get("detail_url") or lead.get("url") or "",
                "buyer_details_text": lead.get("buyer_details_text") or "",
                "order_details_text": lead.get("order_details_text") or "",
            }
            digest = hashlib.sha1(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()
            lead["lead_id"] = f"hash:{digest[:16]}"
            lead["lead_id_synthetic"] = True

        # Track top-card changes for guaranteed observation
        top_lead = next((l for l in leads if l.get("top_card") or l.get("top_rank") == 1), None)
        if top_lead:
            try:
                state = self.load_state()
                last_top = state.get("last_top_lead_id")
                current_top = top_lead.get("lead_id")
                if current_top and current_top != last_top:
                    state["last_top_lead_id"] = current_top
                    state["last_top_seen_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    state["last_top_title"] = top_lead.get("title")
                    state["last_top_country"] = top_lead.get("country")
                    self.write_state(state)
                    print(f"[WORKER] Top lead changed: {current_top} | {top_lead.get('title')}")
            except Exception:
                pass

        # --- KEYWORD & COUNTRY FILTERING ---
        search_terms = [t.lower().strip() for t in (self.config.get("search_terms") or []) if t.strip()]
        exclude_terms = [t.lower().strip() for t in (self.config.get("exclude_terms") or []) if t.strip()]
        countries = [c.lower().strip() for c in (self.config.get("country") or []) if c.strip()]
        require_mobile = bool(self.config.get("require_mobile_available"))
        require_mobile_verified = bool(self.config.get("require_mobile_verified"))
        require_email_available = bool(self.config.get("require_email_available"))
        require_whatsapp = bool(self.config.get("require_whatsapp_available"))
        require_email = bool(self.config.get("require_email_verified"))
        zero_only = bool(self.config.get("zero_second_only"))
        max_age = self.config.get("max_lead_age_seconds")
        max_age = int(max_age) if max_age else 86400
        allow_unknown = bool(self.config.get("allow_unknown_age"))
        min_member_months = int(self.config.get("min_member_months") or 0)
        max_age_hours = int(self.config.get("max_age_hours") or 0)

        filtered_leads = []
        rejected_leads = self.state.get("rejected_buffer", [])
        for lead in leads:
            title = (lead.get("title") or "").lower()
            age_seconds = lead.get("age_seconds")
            
            # 1. Exclude Terms (Strict Drop -> Mark Rejected)
            if any(ex in title for ex in exclude_terms):
                lead["status"] = "rejected"
                filtered_leads.append(lead)
                continue
            
            if zero_only:
                if age_seconds != 0:
                    lead["status"] = "rejected"
                    lead["rejected_reason"] = "age_not_zero"
                    rejected_leads.append(lead)
                    continue
            else:
                if age_seconds is None and not allow_unknown:
                    lead["status"] = "rejected"
                    lead["rejected_reason"] = "age_unknown"
                    rejected_leads.append(lead)
                    continue
                if age_seconds is not None and age_seconds > max_age:
                    lead["status"] = "rejected"
                    lead["rejected_reason"] = "age_too_old"
                    rejected_leads.append(lead)
                    continue

            if require_mobile and not (lead.get("mobile_available") or lead.get("mobile_verified")):
                lead["status"] = "rejected"
                lead["rejected_reason"] = "mobile_missing"
                rejected_leads.append(lead)
                continue
            if require_mobile_verified and not lead.get("mobile_verified"):
                lead["status"] = "rejected"
                lead["rejected_reason"] = "mobile_unverified"
                rejected_leads.append(lead)
                continue
            if require_email_available and not (lead.get("email_available") or lead.get("email_verified")):
                lead["status"] = "rejected"
                lead["rejected_reason"] = "email_missing"
                rejected_leads.append(lead)
                continue
            if require_email and not lead.get("email_verified"):
                lead["status"] = "rejected"
                lead["rejected_reason"] = "email_unverified"
                rejected_leads.append(lead)
                continue
            if require_whatsapp and not lead.get("whatsapp_available"):
                lead["status"] = "rejected"
                lead["rejected_reason"] = "whatsapp_missing"
                rejected_leads.append(lead)
                continue

            # Country filter (DOM path)
            if countries:
                c_lower = (lead.get("country") or "").lower().strip()
                c_tokens = set(re.split(r"\\W+", c_lower)) if c_lower else set()
                c_code = (lead.get("country_code") or "").lower().strip()
                match_found = False
                for allowed in countries:
                    allowed = (allowed or "").strip().lower()
                    if not allowed:
                        continue
                    if c_code and allowed == c_code:
                        match_found = True
                        break
                    if len(allowed) <= 3:
                        if allowed in c_tokens:
                            match_found = True
                            break
                    else:
                        if c_lower and allowed in c_lower:
                            match_found = True
                            break
                if not match_found:
                    lead["status"] = "rejected"
                    lead["rejected_reason"] = "country_not_allowed"
                    rejected_leads.append(lead)
                    continue

            # Quality filters (member age / max age hours)
            if min_member_months:
                months = self._parse_member_months(lead.get("member_since") or "")
                if months is None:
                    lead["status"] = "rejected"
                    lead["rejected_reason"] = "member_unknown"
                    rejected_leads.append(lead)
                    continue
                if months < min_member_months:
                    lead["status"] = "rejected"
                    lead["rejected_reason"] = "member_too_new"
                    rejected_leads.append(lead)
                    continue
            if max_age_hours and age_seconds is not None and age_seconds > max_age_hours * 3600:
                lead["status"] = "rejected"
                lead["rejected_reason"] = "age_too_old"
                rejected_leads.append(lead)
                continue
            
            # 2. Search Terms
            if exclude_terms and any(ex in title for ex in exclude_terms):
                lead["status"] = "rejected"
                lead["rejected_reason"] = lead.get("rejected_reason") or "keyword_excluded"
                rejected_leads.append(lead)
                continue
            if search_terms and not any(term in title for term in search_terms):
                lead["status"] = "rejected"
                lead["rejected_reason"] = lead.get("rejected_reason") or "keyword_miss"
                rejected_leads.append(lead)
                continue
            
            filtered_leads.append(lead)

        leads = filtered_leads
        filtered_count = len(leads)
        rejected_count = len(rejected_leads) if rejected_leads else 0
        try:
            state = self.load_state()
            state["last_capture_counts"] = {
                "raw": raw_count,
                "filtered": filtered_count,
                "rejected": rejected_count,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            self.write_state(state)
        except Exception:
            pass
        print(f"[WORKER] Lead scan: raw={raw_count} filtered={filtered_count} rejected={rejected_count}")
        if rejected_leads:
            # Track rejections in metrics
            self.bump_metrics(rejected_total=len(rejected_leads))
            # Keep them for persistence as rejected records
            self.state["rejected_buffer"] = rejected_leads
        # -----------------------------------

        existing = self._load_existing_keys()
        fresh = []
        for lead in leads:
            key = self._lead_key(lead)
            if key in existing:
                continue
            lead["lead_key"] = key
            fresh.append(lead)
            existing.add(key)

        if fresh:
            # Count only unique, qualifying leads discovered this cycle.
            self.bump_metrics(leads_parsed=len(fresh))

        if not fresh:
            if rejected_leads:
                # Persist rejected leads even when nothing qualifies for clicks
                self.state["leads_buffer"] = []
                self.state["phase"] = "WRITE_LEADS"
                self._record_action("rejected_only", "WRITE_LEADS", rejected=len(rejected_leads))
                return
            self._enter_cooldown("no_new_leads")
            return

        self.state["leads_buffer"] = fresh
        self.state["rejected_buffer"] = []
        self.state["phase"] = "CLICK_LEADS"
        self._record_action("parsed_recent", "CLICK_LEADS", parsed=len(fresh))

    def _click_leads_phase(self):
        leads = self.state.get("leads_buffer", [])
        clicked_ids: List[str] = []
        verified_ids = set()
        
        # Refresh the recent leads page to ensure DOM is fresh before clicking
        if self.config.get("use_browser", True) and self._ensure_browser():
            try:
                self._ensure_recent_page()
            except Exception as exc:
                self.record_error(f"refresh_before_click:{str(exc)[:50]}")
        
        # Use browser to navigate and click each lead
        if self.config.get("use_browser", True):
            clicked_ids = self._click_leads_with_browser_navigation(leads)
            if clicked_ids:
                verified_ids = self._verify_clicked_leads(leads, clicked_ids)
                # Increment cumulative counters
                self.bump_metrics(
                    clicked_total=len(clicked_ids),
                    verified_total=len(verified_ids),
                )
        else:
            # Fallback to HTTP requests
            self._purchase_leads(leads)

        self.state["ticks_since_verify"] = 0
        self.state["phase"] = "WRITE_LEADS"
        self._record_action("clicked", self.state["phase"], clicked=len(clicked_ids), verified=len(verified_ids))

    def _fetch_verified_phase(self):
        html = self._fetch_verified_html()

        if not html:
            self.state["verified_html"] = None
            self.state["phase"] = "WRITE_LEADS"
            self._record_action("verify_skip", "WRITE_LEADS")
            return

        if not self._page_logged_in(html):
            self.record_error("login_required")
        
        self.state["verified_html"] = html
        self._snapshot_html("verified_snapshot", html)
        self.state["phase"] = "PARSE_VERIFIED"
        self._record_action("fetch_verified", "PARSE_VERIFIED")

    def _parse_verified_phase(self):
        html = self.state.get("verified_html")
        verified_ids, verified_urls, verified_titles = self._parse_verified(html or "")
        self.state["verified_html"] = None
        
        # 1. Update in-memory buffer (legacy, for UI if needed immediately)
        leads = self.state.get("leads_buffer", [])
        verified_lead_ids = self._apply_verification(leads, verified_ids, verified_urls, verified_titles)
        
        # 2. Bulk update DB (The Fix)
        if verified_lead_ids:
             try:
                 mark_leads_as_verified(self.slot_dir.name, verified_lead_ids)
             except Exception as e:
                 self.record_error(f"db_verify_err: {e}")
        
        self.state["phase"] = "WRITE_LEADS"
        self._record_action("verified_parsed", "WRITE_LEADS", verified=len(verified_lead_ids))

    def _write_leads_phase(self):
        leads = self.state.get("leads_buffer", []) + self.state.get("rejected_buffer", [])
        self._persist_leads(leads)
        self.state["leads_buffer"] = []
        self.state["rejected_buffer"] = []
        self._enter_cooldown("write_done")

    def _cooldown_phase(self):
        # SKIP COOLDOWN - Go straight back to fetching for consistency
        self.state["phase"] = "FETCH_RECENT"
        self._record_action("skip_cooldown", "FETCH_RECENT")

    # ---------- Tick ---------- #

    def tick(self):
        # Hot-reload slot config (cached defaults)
        self.config = self._load_config()
        self._maybe_reload_cookies()
        
        # Periodic verification is optional; by default we only verify after clicks.
        if self.config.get("periodic_verify"):
            # Periodic verification logic (every ~30s)
            # Only trigger if we are in a "stable" state like FETCH_RECENT
            current_phase = self.state.get("phase")
            ticks = self.state.get("ticks_since_verify", 0)
            metrics = self.load_state().get("metrics", {})
            clicked_baseline = self.load_state().get("run_clicked_start", 0)
            clicked_total = metrics.get("clicked_total", 0)
            has_new_clicks = clicked_total > clicked_baseline

            # Only trigger periodic verify if we have any clicks beyond the run baseline
            if current_phase == "FETCH_RECENT" and ticks > 60 and has_new_clicks:
                self.state["phase"] = "FETCH_VERIFIED"
                self.state["ticks_since_verify"] = 0
                self._record_action("periodic_verify", "FETCH_VERIFIED")
            else:
                self.state["ticks_since_verify"] = ticks + 1

        phase = self.state.get("phase", "INIT")
        try:
            if phase == "INIT":
                self._init_phase()
            elif phase == "FETCH_RECENT":
                self._fetch_recent_phase()
            elif phase == "PARSE_RECENT":
                self._parse_recent_phase()
            elif phase == "CLICK_LEADS":
                self._click_leads_phase()
            elif phase == "FETCH_VERIFIED":
                self._fetch_verified_phase()
            elif phase == "PARSE_VERIFIED":
                self._parse_verified_phase()
            elif phase == "WRITE_LEADS":
                self._write_leads_phase()
            elif phase == "COOLDOWN":
                self._cooldown_phase()
            else:
                self.state["phase"] = "INIT"
                self._record_action("reset", "INIT")
        except Exception as exc:
            self.record_error(str(exc)[:200])
            self._enter_cooldown("unhandled_error")

    def shutdown(self):
        self._close_browser()
        super().shutdown()


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m core.workers.indiamart_worker <slot_dir>")
        sys.exit(1)

    slot_dir = Path(sys.argv[1]).resolve()
    worker = IndiaMartWorker(slot_dir)
    worker.run()


if __name__ == "__main__":
    main()
