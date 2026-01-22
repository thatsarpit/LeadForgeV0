import hashlib
import json
import re
import sys
import time
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

        self.state = {
            "phase": "INIT",
            "last_action": None,
            "cooldown_until": 0.0,
            "leads_buffer": [],
            "ticks_since_verify": 0,
            "recent_html": None,
            "recent_payload": None,
            "verified_html": None,
        }
        
        # Validate session at startup
        if not self._validate_session():
            print("[WORKER] ❌ No valid session found - login required")
            state = self.load_state()
            state.update({
                "status": "NEEDS_LOGIN",
                "busy": False,
                "stop_reason": "no_session",
                "stop_detail": "Please complete remote login to authenticate",
            })
            self.write_state(state)
            self.running = False
            return
        
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
            "prefer_api": True,
            "allow_detail_click": False,
            "max_new_per_cycle": 20,
            "max_clicks_per_cycle": 6,
            "max_lead_age_seconds": 0,
            "allow_unknown_age": False,
            "render_wait_ms": 1500,
            "cooldown_seconds": None,
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

    def _validate_session(self) -> bool:
        """
        Validate that we have a valid session to work with.
        Returns False if no cookies or session file is missing/empty.
        """
        cookie_path = self.slot_dir / "session.enc"
        
        # Check if session file exists and has content
        if not cookie_path.exists() or cookie_path.stat().st_size == 0:
            return False
        
        # Check if we actually loaded cookies
        if not self.session.cookies:
            return False
        
        # Look for critical IndiaMART session cookies
        # IndiaMART typically uses cookies like im_auth, im_sid, etc.
        cookie_dict = {c.name: c.value for c in self.session.cookies}
        
        # If we have ANY substantial cookies, consider it valid
        # (More specific validation could check for im_auth specifically)
        if len(cookie_dict) > 0:
            return True
        
        return False

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
        return "logout" in lower or "sign out" in lower

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
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=True,
            args=["--disable-dev-shm-usage", "--no-sandbox"],
            viewport={"width": 1440, "height": 900},
        )
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
            wait_ms = int(self.config.get("render_wait_ms") or 0)
            if wait_ms > 0:
                self._page.wait_for_timeout(wait_ms)
            return self._page.content()
        except Exception as exc:
            self.record_error(str(exc)[:200])
            return None

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

        max_new = max(int(self.config.get("max_new_per_cycle") or 0), 1)
        allow_unknown = bool(self.config.get("allow_unknown_age"))
        max_age = self.config.get("max_lead_age_seconds")
        # 0 or None means "no limit" - use 24 hours as effective max
        max_age = int(max_age) if max_age else 86400

        allowed_countries = set(c.lower() for c in (self.config.get("country") or []))

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

            if age_seconds is None and not allow_unknown:
                continue
            if age_seconds is not None and age_seconds > max_age:
                continue

            # Country Filter (API)
            if allowed_countries:
                msg_country = str(
                    item.get("S_COUNTRY") 
                    or item.get("GLUSR_USR_COUNTRYNAME") 
                    or item.get("SENDER_COUNTRY")
                    or item.get("ISO")
                    or ""
                ).strip().lower()
                
                if msg_country:
                     # Strict matching strategy:
                     # 1. Normalize both sides
                     # 2. Split item country into tokens (words)
                     # 3. Match if any allowed country (normalized) equals a token 
                     #    OR if allowed country is substring of token (for longer matches) 
                     #    BUT treat short codes (<=3 chars) as exact matches only.
                     
                     # Check if ANY allowed country matches this item's country string
                     match_found = False
                     country_tokens = set(re.split(r'\W+', msg_country))
                     
                     for allowed in allowed_countries:
                         allowed = allowed.strip().lower()
                         if not allowed:
                             continue
                             
                         # Strategy:
                         # If allowed is short (<=3), require exact token match (e.g. 'us', 'usa', 'gb')
                         # If allowed is long, allow if it matches a token OR is contained in msg_country
                         
                         if len(allowed) <= 3:
                             if allowed in country_tokens:
                                 match_found = True
                                 break
                         else:
                             # For longer names (e.g. "germany"), match if it appears in the string
                             # boundary check using token set or direct substring if sufficiently long
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

            lead = {
                "lead_id": lead_id or None,
                "title": title[:140] if title else None,
                "detail_url": detail_url,
                "buy_url": buy_url,
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
        max_new = max(int(self.config.get("max_new_per_cycle") or 0), 1)
        allow_unknown = bool(self.config.get("allow_unknown_age"))
        max_age = self.config.get("max_lead_age_seconds")
        # 0 or None means "no limit" - use 24 hours as effective max
        max_age = int(max_age) if max_age else 86400
        
        allowed_countries = [c.lower() for c in (self.config.get("country") or [])]
        
        # BULLETPROOF DOM SCRAPING - Enhanced with deep analysis findings
        js = """
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
          
          // Target .bl_grid parent containers (most stable)
          const leadContainers = document.querySelectorAll('.bl_grid');
          const results = [];
          
          for (const container of leadContainers) {
            if (results.length >= opts.maxNew) break;
            
            // Skip shimmer/skeleton placeholders
            if (container.querySelector('.secshimmer')) continue;
            
            const card = container.querySelector('.lstNw') || container;
            
            // Extract lead ID from hidden input (MOST RELIABLE)
            const ofrIdInput = card.querySelector('input[name="ofrid"]');
            const leadId = ofrIdInput ? ofrIdInput.value : null;
            if (!leadId) continue;  // Skip if no valid lead ID
            
            // Get title from multiple possible selectors
            const titleEl = card.querySelector('h2, .bl_title, .lst_title');
            const title = normalize(titleEl ? titleEl.textContent : '').slice(0, 140);
            if (!title || title.length < 3) continue;
            
            // Extract country/location
            // (Moved down to be after title extraction but before filtering)
            // (Refactored into main flow)
            
            // Extract age from text content
            const ageMatch = (card.textContent || '').match(/(\\d+\\s*(?:sec|s|second|seconds|min|mins|minute|minutes|hr|hrs|hour|hours)|just now)/i);
            const ageSeconds = ageToSeconds(ageMatch ? ageMatch[0] : null);
            
            // PRO FILTER: Configurable age limit (0 means no limit = 86400)
            const limit = opts.maxAge > 0 ? opts.maxAge : 86400;
            if (ageSeconds !== null && ageSeconds > limit) {
              continue;
            }
            
            // Country Filter
            let country = null;
            const countryInput = card.querySelector('input[name^="card_country"]');
            if (countryInput) {
              country = countryInput.value;
            } else {
              const countrySpan = card.querySelector('.coutry_click, .tcont');
              if (countrySpan) country = normalize(countrySpan.textContent);
            }
            
            if (opts.allowedCountries && opts.allowedCountries.length > 0) {
                if (country) {
                    const cLower = country.toLowerCase().trim();
                    const cTokens = cLower.split(/[\W_]+/).filter(Boolean);
                    
                    const match = opts.allowedCountries.some(ac => {
                        const allowed = (ac || '').trim().toLowerCase();
                        if (!allowed) return false;
                        
                        // Strict rules:
                        // 1. If allowed is short (<=3 chars), require EXACT match with a token
                        //    Prevents "in" (India) matching "germany" (contains 'in'?? no) 
                        //    Actually prevents "in" matching "indiana" or similar if we were loose.
                        //    Mainly prevents "us" matching "australia"?? No.
                        //    Prevents "in" matching "india" if "in" is not a separate token.
                        
                        if (allowed.length <= 3) {
                            return cTokens.includes(allowed);
                        }
                        
                        // 2. If allowed is longer, standard "includes" is safer but still risky if word boundary not respected.
                        //    Better: match if allowed appears as a word or is a significant substring.
                        //    Let's use token matching or whole-string containment if it makes sense.
                        //    Actually, simple "includes" is okay for long words like "germany" or "united states".
                        //    But to be safe, let's require word boundaries or direct token match.
                        
                        // Check if 'allowed' appears as a substring in the full country string
                        // BUT check boundaries? 
                        // Let's stick to the prompt: "match by whole-word boundaries... or splitting... tokens"
                        
                        // Option A: token match
                        if (cTokens.includes(allowed)) return true;
                        
                        // Option B: multi-word match (e.g. "united states")
                        // "united states" might be tokens ["united", "states"]
                        // so cLower.includes(allowed) is better for multi-word allowed countries
                        return cLower.includes(allowed);
                    });
                    
                    if (!match) continue;
                }
            }

            // Check for Contact Buyer Now button
            const btnCBN = container.querySelector('.btnCBN');
            const hasBuy = !!btnCBN;
            
            // Extract URL if available
            const linkEl = card.querySelector('a[href]');
            let url = linkEl ? linkEl.getAttribute('href') : '';
            // Normalize URL - handle protocol-relative and relative paths
            if (url) {
              if (url.startsWith('//') && !url.startsWith('///')) {
                url = 'https:' + url;
              } else if (url.startsWith('/') && !url.startsWith('//')) {
                url = location.origin + url;
              }
              // Clean double-domain bug
              url = url.replace(/^(https?:)?\/\/seller\.indiamart\.com\/+seller\.indiamart\.com\//i, 'https://seller.indiamart.com/');
              url = url.replace(/(https?:\/\/seller\.indiamart\.com)\/+seller\.indiamart\.com\//i, '$1/');
            }
            
            results.push({
              lead_id: leadId,
              title,
              url,
              country,
              age_seconds: ageSeconds,
              has_buy: hasBuy
            });
          }
          
          return results;
        }
        """
        try:
            leads = self._page.evaluate(js, {
                "maxNew": max_new,
                "allowUnknown": allow_unknown,
                "maxAge": max_age,
                "allowedCountries": allowed_countries,
            }) or []
            filtered = []
            for lead in leads:
                age = lead.get("age_seconds")
                if age is None and not allow_unknown:
                    continue
                if age is not None and age > max_age:
                    continue
                filtered.append(lead)
            return filtered
        except Exception as exc:
            self.record_error(str(exc)[:200])
            return []

    def _click_buy_leads_in_browser(self, leads: List[Dict[str, str]]) -> List[str]:
        if not self._ensure_browser():
            return []
        max_clicks = int(self.config.get("max_clicks_per_cycle") or 0)
        if max_clicks <= 0:
            return []
        max_age = self.config.get("max_lead_age_seconds")
        max_age = int(max_age) if max_age is not None else 0
        allow_unknown = bool(self.config.get("allow_unknown_age"))
        allowed_countries = [c.lower() for c in (self.config.get("country") or [])]
        
        js = """
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

    def _parse_verified(self, html: str) -> Tuple[set, set]:
        """
        Parse Past Transactions page to find verified leads.
        
        Returns: (verified_ids, verified_contacts)
        - verified_ids: set of lead IDs (if found via patterns)
        - verified_contacts: set of (phone, email) tuples from purchased leads
        
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
        
        # Legacy URL extraction (may not be useful for this page)
        urls = set()
        for match in self.ANCHOR_PATTERN.finditer(html or ""):
            href = match.group(1) or ""
            if not self._looks_like_lead_link(href):
                continue
            urls.add(self._normalize_url(href))
        
        # Store contacts for later matching
        self.state["verified_contacts"] = list(verified_contacts)
        
        print(f"[WORKER] Verification parsed: {len(ids)} IDs, {len(verified_contacts)} contacts")
        
        return ids, urls

    def _click_leads(self, leads: List[Dict[str, str]]) -> int:
        max_clicks = int(self.config.get("max_clicks_per_cycle") or 0)
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
        max_clicks = int(self.config.get("max_clicks_per_cycle") or 0)
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

    def _click_leads_with_browser_navigation(self, leads: List[Dict[str, str]]) -> int:
        """Click buttons using verified DOM pattern: card.closest('.bl_grid').querySelector('.btnCBN')"""
        if not self._ensure_browser():
            return 0
        
        max_clicks = int(self.config.get("max_clicks_per_cycle") or 0)
        if max_clicks <= 0:
            return 0
        
        # Use JavaScript to click buttons - improved with multiple detection strategies
        js = """
        (leadIds) => {
            const clicked = [];
            
            for (const id of leadIds) {
                let btn = null;
                
                // Strategy 1: Find via hidden input with ofrid matching lead ID
                const ofridInput = document.querySelector(`input[name="ofrid"][value="${id}"]`);
                if (ofridInput) {
                    // Found the hidden input, now find parent container and button
                    let container = ofridInput.closest('.bl_grid') || ofridInput.closest('.lstNw');
                    if (container) {
                        btn = container.querySelector('.btnCBN') || 
                              container.querySelector('a[class*="contact"], button[class*="contact"]') ||
                              container.querySelector('a[class*="btn"], button');
                    }
                }
                
                // Strategy 2: Find via anchor with href containing the lead ID
                if (!btn) {
                    const anchor = document.querySelector(`a[href*="${id}"]`);
                    if (anchor) {
                        let el = anchor;
                        // Traverse up the DOM tree (max 6 levels) to find the container
                        for (let i = 0; i < 6 && !btn; i++) {
                            if (!el.parentElement) break;
                            el = el.parentElement;
                            
                            // Strategy 2a: Direct class match (most reliable)
                            btn = el.querySelector('.btnCBN, .btn-contact, [class*="contact"][class*="btn"]');
                            
                            // Strategy 2b: Text match fallback
                            if (!btn) {
                                const candidates = Array.from(el.querySelectorAll('a, button, div[role="button"], span[role="button"]'));
                                btn = candidates.find(b => {
                                    const txt = (b.innerText || "").toLowerCase().trim();
                                    return txt.includes("contact buyer") || txt === "buy now" || txt === "contact" || txt === "buy";
                                });
                            }
                        }
                    }
                }
                
                // Strategy 3: Scan all .bl_grid containers for matching lead
                if (!btn) {
                    const allGrids = document.querySelectorAll('.bl_grid');
                    for (const grid of allGrids) {
                        const html = grid.innerHTML || "";
                        if (html.includes(id)) {
                            btn = grid.querySelector('.btnCBN') || grid.querySelector('a[class*="btn"]');
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
                        console.log('[CLICK] ❌ Click failed:', e);
                    }
                } else {
                    console.log('[CLICK] ❌ Button not found for lead:', id);
                }
            }
            return clicked;
        }
        """
        
        # Extract lead IDs from leads that need clicking
        # Extract lead IDs from leads that need clicking (Skip rejected)
        lead_ids_to_click = [
            lead.get("lead_id") for lead in leads 
            if lead.get("lead_id") and lead.get("status") != "rejected"
        ][:max_clicks]
        
        if not lead_ids_to_click:
            return 0
        
        try:
            clicked_ids = self._page.evaluate(js, lead_ids_to_click) or []
            
            # Mark leads as clicked
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            for lead in leads:
                if lead.get("lead_id") in clicked_ids:
                    lead["status"] = "clicked"
                    lead["clicked_at"] = now
            
            print(f"[WORKER] ✅ Clicked {len(clicked_ids)} leads: {clicked_ids}")
            return len(clicked_ids)
            
        except Exception as exc:
            self.record_error(f"click_js:{str(exc)[:100]}")
            print(f"[WORKER] ❌ Click JS failed: {exc}")
            return 0

    def _apply_verification(self, leads: List[Dict[str, str]], verified_ids: set, verified_urls: set):
        """
        Mark leads as verified using multiple matching strategies:
        1. Match by lead_id (if found in Past Transactions page)
        2. Match by URL (legacy)
        3. Match by phone/email (new - for React SPA compatibility)
        """
        if not leads:
            return
        
        # Get verified contacts from state (set by _parse_verified)
        verified_contacts = set(tuple(c) for c in self.state.get("verified_contacts", []))
        verified_phones = {c[1] for c in verified_contacts if c[0] == "phone"}
        verified_emails = {c[1].lower() for c in verified_contacts if c[0] == "email"}
        
        verified_count = 0
        
        for lead in leads:
            lead_id = str(lead.get("lead_id") or "").strip()
            url = str(lead.get("detail_url") or lead.get("url") or "").strip()
            
            # Get lead's contact info
            lead_phone = str(lead.get("mobile") or lead.get("phone") or "").strip()
            lead_email = str(lead.get("email") or "").strip().lower()
            
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
            
            if is_verified:
                lead["status"] = "verified"
                lead["verified_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                verified_count += 1
        
        if verified_count > 0:
            print(f"[WORKER] Verified {verified_count} leads via matching")

    def _persist_leads(self, leads: List[Dict[str, str]]):
        if not leads:
            return

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        
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
            except Exception as e:
                self.record_error(f"db_save_err: {e}")

        # Update Metrics
        state = self.load_state()
        metrics = state.get("metrics", {})
        metrics["leads_parsed"] = metrics.get("leads_parsed", 0) + len(leads)
        state["metrics"] = metrics
        state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.write_state(state)

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

    def _fetch_recent_phase(self):
        url = self.config.get("recent_url") or self.DEFAULT_RECENT_URL
        self._record_action("fetch_recent", "FETCH_RECENT")
        self._maybe_reload_cookies()
        prefer_api = bool(self.config.get("prefer_api", True))
        payload = None
        if prefer_api:
            payload = self._fetch_recent_payload()
        if payload:
            self.state["recent_payload"] = payload
            self._snapshot_json("recent_payload", payload)
            metrics = self.load_state().get("metrics", {})
            self.update_metrics(pages_fetched=metrics.get("pages_fetched", 0) + 1, phase="PARSE_RECENT")
            self.state["phase"] = "PARSE_RECENT"
            return

        html = self._render_page(url) if self.config.get("use_browser", True) else self._fetch_page(url)
        if not html:
            self._enter_cooldown("fetch_recent_failed")
            return
        if not self._page_logged_in(html):
            self.record_error("login_required")
            self._refresh_cookies_from_browser()
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
                if not leads and html:
                    leads = self._parse_recent_leads(html)
            else:
                leads = self._parse_recent_leads(html or "")
        self.state["recent_html"] = None
        self.state["recent_payload"] = None

        if not leads:
            self._enter_cooldown("no_recent_leads")
            return

        # --- KEYWORD & COUNTRY FILTERING ---
        search_terms = [t.lower().strip() for t in (self.config.get("search_terms") or []) if t.strip()]
        exclude_terms = [t.lower().strip() for t in (self.config.get("exclude_terms") or []) if t.strip()]
        countries = [c.lower().strip() for c in (self.config.get("country") or []) if c.strip()]

        filtered_leads = []
        for lead in leads:
            title = (lead.get("title") or "").lower()
            
            # 1. Exclude Terms (Strict Drop -> Mark Rejected)
            if any(ex in title for ex in exclude_terms):
                lead["status"] = "rejected"
                filtered_leads.append(lead)
                continue
            
            # 2. Search Terms
            # STRATEGY: 0-Second Capture - Disable filters to maximize coverage of fresh drops
            # strict_keyword_filtering = False 

            # 3. Country Filtering
            # STRATEGY: Capture global fresh leads, filter post-capture if needed
            
            filtered_leads.append(lead)

        leads = filtered_leads
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

        if not fresh:
            self._enter_cooldown("no_new_leads")
            return

        self.state["leads_buffer"] = fresh
        self.state["phase"] = "CLICK_LEADS"
        self._record_action("parsed_recent", "CLICK_LEADS", parsed=len(fresh))

    def _click_leads_phase(self):
        leads = self.state.get("leads_buffer", [])
        clicks = 0
        
        # Refresh the recent leads page to ensure DOM is fresh before clicking
        if self.config.get("use_browser", True) and self._ensure_browser():
            try:
                url = self.config.get("recent_url") or self.DEFAULT_RECENT_URL
                self._page.goto(url, wait_until="domcontentloaded")
                self._page.wait_for_timeout(1500)  # Wait for leads to fully render
            except Exception as exc:
                self.record_error(f"refresh_before_click:{str(exc)[:50]}")
        
        # Use browser to navigate and click each lead
        if self.config.get("use_browser", True):
            clicks = self._click_leads_with_browser_navigation(leads)
        else:
            # Fallback to HTTP requests
            clicks = self._purchase_leads(leads)
        
        # LOGIC: Only verify if we actually attempted a purchase (clicks > 0)
        # This preserves speed when no leads are found/clicked.
        if clicks > 0:
            # Force verify soon
            self.state["ticks_since_verify"] = 1000
        else:
            self.state["phase"] = "WRITE_LEADS"
            
        self._record_action("clicked", self.state["phase"], clicked=clicks)

    def _fetch_verified_phase(self):
        url = self.config.get("verified_url") or self.DEFAULT_VERIFIED_URL
        html = None
        
        if self.config.get("use_browser", True) and self._ensure_browser():
            # Use separate tab for verification to preserve main scanning page state
            page = None
            try:
                print(f"[WORKER] Opening verification tab: {url}")
                page = self._context.new_page()
                page.goto(url, wait_until="domcontentloaded")
                # Wait for potential update (User said delay is acceptable/needed)
                page.wait_for_timeout(5000)
                html = page.content()
            except Exception as exc:
                print(f"[WORKER] ❌ Verification Tab Failed: {exc}")
                self.record_error(f"verify_tab_{str(exc)[:50]}")
            finally:
                if page:
                    try:
                        page.close()
                    except Exception:
                        pass
        else:
            html = self._fetch_page(url)

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
        verified_ids, verified_urls = self._parse_verified(html or "")
        self.state["verified_html"] = None
        
        # 1. Update in-memory buffer (legacy, for UI if needed immediately)
        leads = self.state.get("leads_buffer", [])
        self._apply_verification(leads, verified_ids, verified_urls)
        
        # 2. Bulk update DB (The Fix)
        if verified_ids:
             try:
                 mark_leads_as_verified(self.slot_dir.name, verified_ids)
             except Exception as e:
                 self.record_error(f"db_verify_err: {e}")
        
        self.state["phase"] = "WRITE_LEADS"
        self._record_action("verified_parsed", "WRITE_LEADS", verified=len(verified_ids))

    def _write_leads_phase(self):
        leads = self.state.get("leads_buffer", [])
        self._persist_leads(leads)
        self.state["leads_buffer"] = []
        self._enter_cooldown("write_done")

    def _cooldown_phase(self):
        # SKIP COOLDOWN - Go straight back to fetching for consistency
        self.state["phase"] = "FETCH_RECENT"
        self._record_action("skip_cooldown", "FETCH_RECENT")

    # ---------- Tick ---------- #

    def tick(self):
        self._maybe_reload_cookies()
        
        # Periodic verification logic (every ~30s)
        # Only trigger if we are in a "stable" state like FETCH_RECENT
        current_phase = self.state.get("phase")
        ticks = self.state.get("ticks_since_verify", 0)
        
        if current_phase == "FETCH_RECENT" and ticks > 60:
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
