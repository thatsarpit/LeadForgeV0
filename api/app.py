from collections import deque
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import json
import os
import signal
import subprocess
import time
import urllib.parse
import uuid

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
import jwt
import requests
from dotenv import load_dotenv
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from typing import Optional
import yaml

from api.db import SessionLocal, get_db
from api.models import DemoCode, Slot, User, UserEmail, UserSlot
from api.utils.email import send_bulk_email

load_dotenv()

app = FastAPI(title="Engyne API", version="1.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://app.engyne.space",
        "https://api.engyne.space",
        "http://engyne.test:5173",
        "http://engyne.local:5173",
    ],
    allow_origin_regex="http://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
SLOTS_DIR = BASE_DIR / "slots"
ENGINE_DIR = BASE_DIR / "core" / "engine"

AUTH_SECRET = os.getenv("AUTH_SECRET", "engyne_dev_secret")
AUTH_ALGO = "HS256"
TOKEN_TTL_HOURS = int(os.getenv("TOKEN_TTL_HOURS", "24"))
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "thatsarpitg@gmail.com").strip().lower()

GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_OAUTH_REDIRECT_BASE = os.getenv("GOOGLE_OAUTH_REDIRECT_BASE", "")
GOOGLE_OAUTH_ALLOWED_DOMAINS = os.getenv("GOOGLE_OAUTH_ALLOWED_DOMAINS", "")
GOOGLE_OAUTH_ALLOWED_REDIRECTS = os.getenv("GOOGLE_OAUTH_ALLOWED_REDIRECTS", "")
GOOGLE_OAUTH_AUTO_PROVISION = os.getenv("GOOGLE_OAUTH_AUTO_PROVISION", "false").lower() in (
    "1",
    "true",
    "yes",
)
DEMO_LOGIN_ENABLED = os.getenv("DEMO_LOGIN_ENABLED", "false").lower() in ("1", "true", "yes")
DEMO_LOGIN_DOMAIN = os.getenv("DEMO_LOGIN_DOMAIN", "demo.local").strip() or "demo.local"
NODE_ID = os.getenv("NODE_ID", "local").strip() or "local"
NODE_NAME = os.getenv("NODE_NAME", "Local Node").strip() or "Local Node"
DEFAULT_SLOT_WORKER = os.getenv("DEFAULT_SLOT_WORKER", "indiamart_worker")
DEFAULT_SLOT_MODE = os.getenv("DEFAULT_SLOT_MODE", "ACTIVE")
NODES_CONFIG_PATH = BASE_DIR / "config" / "nodes.yml"
REMOTE_LOGIN_ENABLED = os.getenv("REMOTE_LOGIN_ENABLED", "false").lower() in ("1", "true", "yes")
REMOTE_LOGIN_TIMEOUT_MINUTES = int(os.getenv("REMOTE_LOGIN_TIMEOUT_MINUTES", "15"))
REMOTE_LOGIN_PUBLIC_BASE = os.getenv("REMOTE_LOGIN_PUBLIC_BASE", "").strip().rstrip("/")
REMOTE_LOGIN_VIEWPORT_WIDTH = int(os.getenv("REMOTE_LOGIN_VIEWPORT_WIDTH", "1280"))
REMOTE_LOGIN_VIEWPORT_HEIGHT = int(os.getenv("REMOTE_LOGIN_VIEWPORT_HEIGHT", "800"))

SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or 587)
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", "").strip()
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Engyne").strip()
SMTP_UPDATES_FROM = os.getenv("SMTP_UPDATES_FROM", "").strip() or SMTP_FROM
SMTP_UPDATES_FROM_NAME = os.getenv("SMTP_UPDATES_FROM_NAME", "").strip() or SMTP_FROM_NAME
INVITE_BASE_URL = os.getenv("INVITE_BASE_URL", "https://app.engyne.space").strip() or "https://app.engyne.space"
WAHA_BASE_URL = os.getenv("WAHA_BASE_URL", "").strip().rstrip("/")


# ---------- Utilities ----------


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save_json(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2))


def load_yaml(path: Path, default=None):
    try:
        data = yaml.safe_load(path.read_text())
        if data is None:
            return default
        return data
    except Exception:
        return default


def save_yaml(path: Path, data: dict):
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def slot_path(slot_id: str) -> Path:
    return SLOTS_DIR / slot_id


def require_slot_dir(slot_id: str) -> Path:
    slot_dir = slot_path(slot_id)
    if not slot_dir.exists():
        raise HTTPException(status_code=404, detail="Slot not found")
    return slot_dir


def load_slot_state(slot_id: str) -> dict:
    slot_dir = require_slot_dir(slot_id)
    state = load_json(slot_dir / "slot_state.json", None)
    if not state:
        state = load_json(slot_dir / "state.json", {})
    if not isinstance(state, dict):
        state = {}
    state.setdefault("slot_id", slot_id)
    return state


def load_slot_config(slot_id: str) -> dict:
    slot_dir = require_slot_dir(slot_id)
    config = load_yaml(slot_dir / "slot_config.yml", {}) or {}
    if not isinstance(config, dict):
        config = {}
    return config


def save_slot_config(slot_id: str, config: dict):
    slot_dir = require_slot_dir(slot_id)
    save_yaml(slot_dir / "slot_config.yml", config)


def read_leads(slot_id: str, limit: int = 200) -> list[dict]:
    slot_dir = require_slot_dir(slot_id)
    leads_path = slot_dir / "leads.jsonl"
    if not leads_path.exists():
        return []
    limit = max(1, min(int(limit), 5000))
    queue: deque[str] = deque(maxlen=limit)
    with leads_path.open() as handle:
        for line in handle:
            line = line.strip()
            if line:
                queue.append(line)
    leads = []
    for line in queue:
        try:
            leads.append(json.loads(line))
        except Exception:
            continue
    return leads


# ---------- Remote Login ----------


class RemoteLoginSession:
    def __init__(self, session_id: str, slot_id: str, owner_id: str, target_url: str):
        self.session_id = session_id
        self.slot_id = slot_id
        self.owner_id = owner_id
        self.target_url = target_url
        self.created_at = datetime.utcnow()
        self.expires_at = self.created_at + timedelta(minutes=REMOTE_LOGIN_TIMEOUT_MINUTES)
        self.status = "starting"
        self.error = None
        self.context = None
        self.page = None
        self.cdp = None
        self.viewers = set()
        self.viewport = {
            "width": REMOTE_LOGIN_VIEWPORT_WIDTH,
            "height": REMOTE_LOGIN_VIEWPORT_HEIGHT,
        }
        self._closed = False
        self._start_lock = asyncio.Lock()

    def is_expired(self) -> bool:
        return datetime.utcnow() >= self.expires_at

    def snapshot(self, base: str) -> dict:
        return {
            "session_id": self.session_id,
            "slot_id": self.slot_id,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at.isoformat() + "Z",
            "expires_at": self.expires_at.isoformat() + "Z",
            "viewport": self.viewport,
            "api_base": base,
            "ws_url": _remote_login_ws_url(base, self.session_id),
        }

    async def start(self):
        async with self._start_lock:
            if self.context or self._closed:
                return
            try:
                playwright = await _get_playwright()
                profile_dir = BASE_DIR / "browser_profiles" / self.slot_id
                profile_dir.mkdir(parents=True, exist_ok=True)
                self.context = await playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    headless=True,
                    viewport=self.viewport,
                    args=["--disable-dev-shm-usage", "--no-sandbox"],
                )
                self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
                await self.page.goto(self.target_url, wait_until="domcontentloaded", timeout=60000)
                self.cdp = await self.context.new_cdp_session(self.page)

                def _on_frame(params):
                    asyncio.create_task(self._handle_frame(params))

                self.cdp.on("Page.screencastFrame", _on_frame)
                await self.cdp.send(
                    "Page.startScreencast",
                    {
                        "format": "jpeg",
                        "quality": 70,
                        "maxWidth": self.viewport["width"],
                        "maxHeight": self.viewport["height"],
                        "everyNthFrame": 1,
                    },
                )
                self.status = "active"
            except Exception as exc:
                print(f"DEBUG: RemoteLoginSession start failed: {exc}")
                import traceback
                traceback.print_exc()
                self.status = "error"
                self.error = str(exc)[:200]

    async def _handle_frame(self, params: dict):
        if not self.cdp or self._closed:
            return
        session_id = params.get("sessionId")
        if session_id:
            try:
                await self.cdp.send("Page.screencastFrameAck", {"sessionId": session_id})
            except Exception:
                return
        data = params.get("data")
        if not data:
            return
        payload = {"type": "frame", "data": data, "timestamp": time.time()}
        for ws in list(self.viewers):
            try:
                await ws.send_json(payload)
            except Exception:
                self.viewers.discard(ws)

    async def handle_input(self, message: dict):
        if not self.page or self._closed:
            return
        msg_type = message.get("type")
        try:
            if msg_type == "mouse":
                event = message.get("event")
                x = float(message.get("x", 0))
                y = float(message.get("y", 0))
                button = message.get("button", "left")
                if event == "move":
                    await self.page.mouse.move(x, y)
                elif event == "down":
                    await self.page.mouse.down(button=button)
                elif event == "up":
                    await self.page.mouse.up(button=button)
                elif event == "click":
                    await self.page.mouse.click(x, y, button=button)
                elif event == "wheel":
                    await self.page.mouse.wheel(float(message.get("dx", 0)), float(message.get("dy", 0)))
            elif msg_type == "key":
                action = message.get("action")
                key = message.get("key")
                text = message.get("text")
                if action == "type" and text:
                    await self.page.keyboard.type(text)
                elif action == "press" and key:
                    await self.page.keyboard.press(key)
        except Exception:
            return

    async def finish(self):
        if not self.context or self._closed:
            return
        try:
            cookies = await self.context.cookies()
            filtered = [
                c
                for c in cookies
                if "indiamart" in (c.get("domain") or "") or "indiamart" in (c.get("name") or "")
            ]
            slot_dir = slot_path(self.slot_id)
            session_file = slot_dir / "session.enc"
            session_file.write_text(json.dumps(filtered or cookies, indent=2))
            self.status = "finished"
        except Exception as exc:
            self.status = "error"
            self.error = str(exc)[:200]
        finally:
            await self.close()

    async def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass


class RemoteLoginManager:
    def __init__(self):
        self.sessions = {}
        self.slot_index = {}
        self.lock = asyncio.Lock()
        self._cleanup_task = None

    async def get_or_create(self, slot_id: str, owner_id: str, target_url: str):
        async with self.lock:
            session_id = self.slot_index.get(slot_id)
            session = self.sessions.get(session_id) if session_id else None
            if session and not session.is_expired() and session.status != "error":
                return session
            if session:
                await session.close()
            session_id = uuid.uuid4().hex
            session = RemoteLoginSession(session_id, slot_id, owner_id, target_url)
            self.sessions[session_id] = session
            self.slot_index[slot_id] = session_id
            asyncio.create_task(session.start())
            return session

    def get(self, session_id: str):
        session = self.sessions.get(session_id)
        if not session or session.is_expired():
            return None
        return session

    async def finish(self, session_id: str):
        async with self.lock:
            session = self.sessions.pop(session_id, None)
            self.slot_index = {k: v for k, v in self.slot_index.items() if v != session_id}
        if session:
            await session.finish()
        return session

    async def cleanup_expired(self):
        async with self.lock:
            expired = [sid for sid, sess in self.sessions.items() if sess.is_expired()]
        for sid in expired:
            session = self.sessions.pop(sid, None)
            if not session:
                continue
            self.slot_index = {k: v for k, v in self.slot_index.items() if v != sid}
            await session.close()

    def start_cleanup_loop(self):
        if self._cleanup_task:
            return

        async def _loop():
            while True:
                await asyncio.sleep(20)
                await self.cleanup_expired()

        self._cleanup_task = asyncio.create_task(_loop())


REMOTE_LOGIN_MANAGER = RemoteLoginManager()


def load_nodes_config() -> list[dict]:
    if not NODES_CONFIG_PATH.exists():
        return []
    raw = load_yaml(NODES_CONFIG_PATH, []) or []
    if not isinstance(raw, list):
        return []
    nodes = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        node_id = str(entry.get("node_id") or "").strip()
        if not node_id:
            continue
        node_name = str(entry.get("node_name") or node_id).strip() or node_id
        base_url = str(entry.get("base_url") or "").strip().rstrip("/")
        token = str(entry.get("token") or "").strip()
        nodes.append(
            {
                "node_id": node_id,
                "node_name": node_name,
                "base_url": base_url,
                "token": token,
            }
        )
    return nodes


def issue_admin_token(db: Session) -> str:
    user = find_user_by_email(db, ADMIN_EMAIL)
    if not user:
        _ensure_admin_user(db)
        user = find_user_by_email(db, ADMIN_EMAIL)
    if not user:
        raise HTTPException(status_code=500, detail="Admin user missing")
    return _issue_token(user)


def node_auth_headers(node: dict, db: Session) -> dict:
    token = node.get("token") or ""
    if not token:
        token = issue_admin_token(db)
    return {"Authorization": f"Bearer {token}"}


def node_request_json(
    node: dict,
    db: Session,
    method: str,
    path: str,
    payload: Optional[dict] = None,
    params: Optional[dict] = None,
    stream: bool = False,
):
    base_url = node.get("base_url") or ""
    if not base_url:
        raise HTTPException(status_code=502, detail="Node missing base_url")
    url = f"{base_url}{path}"
    headers = {"Content-Type": "application/json"}
    headers.update(node_auth_headers(node, db))
    try:
        res = requests.request(
            method,
            url,
            headers=headers,
            params=params,
            json=payload,
            timeout=12,
            stream=stream,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Node request failed: {exc}") from exc
    if not res.ok:
        detail = res.text or f"Node error {res.status_code}"
        raise HTTPException(status_code=res.status_code, detail=detail)
    if stream:
        return res
    if not res.content:
        return {}
    try:
        return res.json()
    except Exception:
        return {}


def resolve_node(node_id: str) -> dict:
    if node_id in ("local", "node_local", NODE_ID):
        return {"node_id": NODE_ID, "node_name": NODE_NAME, "base_url": ""}
    for node in load_nodes_config():
        if node.get("node_id") == node_id:
            return node
    raise HTTPException(status_code=404, detail="Node not found")


REMOTE_LOGIN_TARGETS = {
    "indiamart": "https://seller.indiamart.com/",
}

_playwright = None


async def _get_playwright():
    global _playwright
    if _playwright is not None:
        return _playwright
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Remote login requires Playwright installed on this node",
        ) from exc
    _playwright = await async_playwright().start()
    return _playwright


def _remote_login_base(request: Request) -> str:
    if REMOTE_LOGIN_PUBLIC_BASE:
        return REMOTE_LOGIN_PUBLIC_BASE
    return str(request.base_url).rstrip("/")


def _remote_login_ws_url(base: str, session_id: str) -> str:
    ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
    return f"{ws_base}/remote-login/ws/{session_id}"


def normalize_email(email: Optional[str]) -> str:
    return str(email or "").strip().lower()


def normalize_slot_id(slot_id: Optional[str]) -> str:
    value = str(slot_id or "").strip()
    if not value:
        return ""
    if "::" in value:
        value = value.split("::")[-1]
    return value


def is_hidden_slot(slot_id: Optional[str]) -> bool:
    value = normalize_slot_id(slot_id)
    return not value or value.startswith("_")


def normalize_allowed_slots(raw) -> list[str]:
    slots = []
    for entry in raw or []:
        slot_id = normalize_slot_id(entry)
        if slot_id and slot_id not in slots:
            slots.append(slot_id)
    return slots


def _waha_base(config: dict) -> str:
    base = (config.get("whatsapp_waha_url") or WAHA_BASE_URL or "").strip()
    return base.rstrip("/")


def _waha_session(config: dict, slot_id: str) -> str:
    session = (config.get("whatsapp_waha_session") or slot_id or "").strip()
    return session or slot_id


def _waha_request(base: str, method: str, path: str, payload: Optional[dict] = None):
    if not base:
        raise HTTPException(status_code=400, detail="WAHA base URL is not configured")
    url = f"{base}{path}"
    try:
        res = requests.request(method, url, json=payload, timeout=12)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"WAHA request failed: {exc}") from exc
    if not res.ok:
        detail = res.text or f"WAHA error {res.status_code}"
        raise HTTPException(status_code=res.status_code, detail=detail)
    if not res.content:
        return {}
    try:
        return res.json()
    except Exception:
        return res.text


def _google_allowed_domains():
    raw = GOOGLE_OAUTH_ALLOWED_DOMAINS or ""
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def _allowed_google_redirects():
    raw = GOOGLE_OAUTH_ALLOWED_REDIRECTS or ""
    return [r.strip() for r in raw.split(",") if r.strip()]


def _normalize_google_redirect(candidate: Optional[str]):
    allowed = _allowed_google_redirects()
    candidate = (candidate or "").strip()
    fallback = (GOOGLE_OAUTH_REDIRECT_BASE or "").strip()

    def ok(url: str) -> bool:
        if not url:
            return False
        if not allowed:
            return True
        return any(url.startswith(prefix) for prefix in allowed)

    if candidate and ok(candidate):
        return candidate
    if fallback and ok(fallback):
        return fallback
    return allowed[0] if allowed else None


def _append_fragment(url: str, params: dict) -> str:
    if not url:
        return url
    parts = urllib.parse.urlsplit(url)
    fragment = dict(urllib.parse.parse_qsl(parts.fragment))
    for key, value in params.items():
        if value is None:
            continue
        fragment[key] = value
    new_fragment = urllib.parse.urlencode(fragment)
    return urllib.parse.urlunsplit(parts._replace(fragment=new_fragment))


def _append_query(url: str, params: dict) -> str:
    if not url:
        return url
    parts = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parts.query))
    for key, value in params.items():
        if value is None:
            continue
        query[str(key)] = str(value)
    new_query = urllib.parse.urlencode(query)
    return urllib.parse.urlunsplit(parts._replace(query=new_query))


def _verify_google_id_token(id_token: str):
    try:
        res = requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": id_token},
            timeout=6,
        )
        if res.status_code != 200:
            return None
        data = res.json()
        if data.get("aud") != GOOGLE_OAUTH_CLIENT_ID:
            return None
        if data.get("email_verified") not in ("true", True):
            return None
        return data
    except Exception:
        return None


def _google_oauth_ready() -> bool:
    return bool(GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET)


def _issue_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "exp": datetime.utcnow() + timedelta(hours=TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, AUTH_SECRET, algorithm=AUTH_ALGO)


def _fetch_alias_emails(db: Session, user_id: uuid.UUID) -> list[str]:
    rows = db.execute(select(UserEmail.email).where(UserEmail.user_id == user_id)).all()
    return [row[0] for row in rows]


def _fetch_allowed_slots(db: Session, user_id: uuid.UUID) -> list[str]:
    rows = db.execute(select(UserSlot.slot_id).where(UserSlot.user_id == user_id)).all()
    return [row[0] for row in rows]


def _fetch_all_client_emails(db: Session) -> list[str]:
    users = db.execute(select(User).where(User.role == "client", User.disabled == False)).scalars().all()
    emails = set()
    for user in users:
        if user.email:
            emails.add(user.email)
        for alias in _fetch_alias_emails(db, user.id):
            if alias:
                emails.add(alias)
    return sorted(emails)


def _resolve_notification_recipients(db: Session, payload: dict) -> list[str]:
    raw = payload.get("recipients")
    if isinstance(raw, list) and raw:
        cleaned = []
        for entry in raw:
            email = normalize_email(entry)
            if email and email not in cleaned:
                cleaned.append(email)
        return cleaned
    return _fetch_all_client_emails(db)


def _invite_email_content(recipient: str) -> tuple[str, str, str]:
    login_url = INVITE_BASE_URL
    subject = "You're invited to Engyne"
    text = (
        "You're invited to access Engyne.\n\n"
        f"Sign in with your invited Google account: {recipient}\n"
        f"Login link: {login_url}\n\n"
        "If you need help, reply to this email and our team will assist."
    )
    html = (
        "<p>You're invited to access <strong>Engyne</strong>.</p>"
        f"<p>Sign in with your invited Google account: <strong>{recipient}</strong></p>"
        f"<p><a href=\"{login_url}\">Open Engyne</a></p>"
        "<p>If you need help, reply to this email and our team will assist.</p>"
    )
    return subject, text, html


def _send_invite_email(recipients: list[str]):
    if not SMTP_HOST or not SMTP_FROM:
        raise HTTPException(status_code=400, detail="SMTP is not configured")
    sent = []
    failed = []
    for recipient in recipients:
        subject, text, html = _invite_email_content(recipient)
        result = send_bulk_email(
            SMTP_HOST,
            SMTP_PORT,
            SMTP_USERNAME,
            SMTP_PASSWORD,
            SMTP_FROM,
            SMTP_FROM_NAME,
            [recipient],
            subject,
            text,
            html,
        )
        sent.extend(result.get("sent") or [])
        failed.extend(result.get("failed") or [])
    return {"sent": sent, "failed": failed}


def sanitize_user(db: Session, user: User) -> dict:
    return {
        "id": str(user.id),
        "username": user.email,
        "role": user.role,
        "allowed_slots": normalize_allowed_slots(_fetch_allowed_slots(db, user.id)),
        "disabled": bool(user.disabled),
        "onboarding_complete": bool(user.onboarding_complete),
        "google_email": user.email,
        "google_emails": _fetch_alias_emails(db, user.id),
    }


def find_user_by_email(db: Session, email: Optional[str]) -> Optional[User]:
    email = normalize_email(email)
    if not email:
        return None
    user = db.scalar(select(User).where(User.email == email))
    if user:
        return user
    return db.scalar(select(User).join(UserEmail).where(UserEmail.email == email))


def _ensure_slot(db: Session, slot_id: str):
    slot_id = str(slot_id).strip()
    if not slot_id:
        return
    if db.get(Slot, slot_id):
        return
    db.add(Slot(id=slot_id))


def _set_user_slots(db: Session, user: User, allowed_slots: list[str]):
    db.execute(delete(UserSlot).where(UserSlot.user_id == user.id))
    cleaned = normalize_allowed_slots(allowed_slots)
    for slot_id in cleaned:
        _ensure_slot(db, slot_id)
        db.add(UserSlot(user_id=user.id, slot_id=slot_id))


def _sync_slots_from_disk(db: Session):
    if not SLOTS_DIR.exists():
        return
    for slot_dir in SLOTS_DIR.iterdir():
        if not slot_dir.is_dir() or slot_dir.name.startswith("."):
            continue
        _ensure_slot(db, slot_dir.name)
    db.commit()


def _auto_provision_google_user(db: Session, email: str) -> Optional[User]:
    if not GOOGLE_OAUTH_AUTO_PROVISION:
        return None
    email = normalize_email(email)
    if not email:
        return None
    existing = find_user_by_email(db, email)
    if existing:
        return existing
    user = User(email=email, role="client", disabled=False)
    db.add(user)
    db.flush()
    db.commit()
    return user


def _demo_user_email(slot_id: str) -> str:
    return f"demo+{slot_id}@{DEMO_LOGIN_DOMAIN}"


def _get_or_create_demo_user(db: Session, slot_id: str) -> User:
    email = _demo_user_email(slot_id)
    user = find_user_by_email(db, email)
    if user:
        user.role = "client"
        user.disabled = False
        return user
    user = User(email=email, role="client", disabled=False)
    db.add(user)
    db.flush()
    return user


def ensure_allowed_slot(user: dict, slot_id: str):
    if user.get("role") == "admin":
        return True
    allowed = set(normalize_allowed_slots(user.get("allowed_slots") or []))
    if normalize_slot_id(slot_id) in allowed:
        return True
    raise HTTPException(status_code=403, detail="Slot not allowed")


def require_admin(user: dict):
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


def require_admin_or_allowed(user: dict, slot_id: str):
    if user.get("role") != "admin":
        ensure_allowed_slot(user, slot_id)


def _ensure_admin_user(db: Session):
    if not ADMIN_EMAIL:
        return
    user = find_user_by_email(db, ADMIN_EMAIL)
    if user:
        if user.role != "admin":
            user.role = "admin"
        if user.disabled:
            user.disabled = False
        db.commit()
        return
    admin = User(email=ADMIN_EMAIL, role="admin", disabled=False)
    db.add(admin)
    db.commit()


@app.on_event("startup")
async def startup():
    db = SessionLocal()
    try:
        _ensure_admin_user(db)
        _sync_slots_from_disk(db)
    finally:
        db.close()
    if REMOTE_LOGIN_ENABLED:
        REMOTE_LOGIN_MANAGER.start_cleanup_loop()


@app.on_event("shutdown")
async def shutdown():
    global _playwright
    if _playwright:
        await _playwright.stop()
        _playwright = None


# ---------- Health ----------


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat() + "Z"}


# ---------- Auth ----------


@app.post("/auth/login")
@app.post("/api/auth/login")
def login_disabled():
    raise HTTPException(status_code=403, detail="Google login only")


def get_current_user(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1]
    return _user_from_token(token, db)


def _user_from_token(token: str, db: Session) -> dict:
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        payload = jwt.decode(token, AUTH_SECRET, algorithms=[AUTH_ALGO])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        user_uuid = uuid.UUID(user_id)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.get(User, user_uuid)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.disabled:
        raise HTTPException(status_code=403, detail="User disabled")

    return {
        "sub": str(user.id),
        "username": user.email,
        "role": user.role,
        "allowed_slots": normalize_allowed_slots(_fetch_allowed_slots(db, user.id)),
        "google_email": user.email,
        "onboarding_complete": bool(user.onboarding_complete),
        "google_emails": _fetch_alias_emails(db, user.id),
    }


@app.get("/auth/me")
@app.get("/api/auth/me")
def me(user=Depends(get_current_user)):
    return {"user": user}


@app.post("/auth/onboarding")
@app.post("/api/auth/onboarding")
def update_onboarding(
    body: dict = Body(default=None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payload = body or {}
    desired = payload.get("complete")
    if desired is None:
        desired = payload.get("onboarding_complete")
    if desired is None:
        desired = True

    target = db.get(User, uuid.UUID(user.get("sub")))
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.onboarding_complete = bool(desired)
    db.commit()
    db.refresh(target)
    return {"onboarding_complete": bool(target.onboarding_complete)}


@app.get("/auth/google/start")
@app.get("/api/auth/google/start")
def google_start(redirect: Optional[str] = None):
    if not _google_oauth_ready():
        raise HTTPException(status_code=503, detail="Google OAuth not configured")

    redirect_url = _normalize_google_redirect(redirect)
    if not redirect_url:
        raise HTTPException(status_code=400, detail="Missing redirect")

    state = jwt.encode(
        {
            "redirect": redirect_url,
            "exp": datetime.utcnow() + timedelta(minutes=10),
            "nonce": uuid.uuid4().hex,
        },
        AUTH_SECRET,
        algorithm=AUTH_ALGO,
    )

    params = {
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": f"{GOOGLE_OAUTH_REDIRECT_BASE}/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return RedirectResponse(auth_url)


@app.get("/auth/google/callback")
@app.get("/api/auth/google/callback")
def google_callback(code: Optional[str] = None, state: Optional[str] = None, db: Session = Depends(get_db)):
    if not _google_oauth_ready():
        raise HTTPException(status_code=503, detail="Google OAuth not configured")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code")

    try:
        state_data = jwt.decode(state, AUTH_SECRET, algorithms=[AUTH_ALGO])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid state")

    redirect_url = _normalize_google_redirect(state_data.get("redirect"))
    if not redirect_url:
        raise HTTPException(status_code=400, detail="Invalid redirect")
    redirect_url = _append_query(redirect_url, {"ts": int(time.time())})

    token_res = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
            "redirect_uri": f"{GOOGLE_OAUTH_REDIRECT_BASE}/auth/google/callback",
            "grant_type": "authorization_code",
        },
        timeout=10,
    )

    if token_res.status_code != 200:
        return RedirectResponse(_append_fragment(redirect_url, {"error": "google_oauth_failed"}))

    token_data = token_res.json()
    id_token = token_data.get("id_token")
    if not id_token:
        return RedirectResponse(_append_fragment(redirect_url, {"error": "google_token_missing"}))

    id_info = _verify_google_id_token(id_token)
    if not id_info:
        return RedirectResponse(_append_fragment(redirect_url, {"error": "google_token_invalid"}))

    email = normalize_email(id_info.get("email"))
    if not email:
        return RedirectResponse(_append_fragment(redirect_url, {"error": "google_email_missing"}))

    allowed_domains = _google_allowed_domains()
    if allowed_domains:
        domain = email.split("@")[-1]
        if domain not in allowed_domains:
            return RedirectResponse(_append_fragment(redirect_url, {"error": "google_domain_blocked"}))

    user = find_user_by_email(db, email)
    if not user:
        user = _auto_provision_google_user(db, email)
    if not user:
        return RedirectResponse(_append_fragment(redirect_url, {"error": "google_user_not_found"}))

    if user.email != email:
        existing = db.scalar(select(UserEmail).where(UserEmail.email == email))
        if not existing:
            db.add(UserEmail(user_id=user.id, email=email, is_primary=False))
    user.last_login_at = datetime.utcnow()
    db.commit()

    token = _issue_token(user)
    print(f"DEBUG: Issued token for {email}: {token[:15]}...")
    return RedirectResponse(_append_fragment(redirect_url, {"token": token, "provider": "google"}))


@app.post("/auth/demo")
@app.post("/api/auth/demo")
def demo_login(body: dict, db: Session = Depends(get_db)):
    if not DEMO_LOGIN_ENABLED:
        raise HTTPException(status_code=403, detail="Demo login disabled")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid body")

    code = str(body.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Code required")

    demo_code = db.scalar(select(DemoCode).where(DemoCode.code == code, DemoCode.active.is_(True)))
    if not demo_code:
        raise HTTPException(status_code=401, detail="Invalid code")

    slot_id = demo_code.slot_id
    _ensure_slot(db, slot_id)
    user = _get_or_create_demo_user(db, slot_id)
    _set_user_slots(db, user, [slot_id])

    demo_code.use_count = (demo_code.use_count or 0) + 1
    demo_code.last_used_at = datetime.utcnow()
    db.commit()

    token = _issue_token(user)
    return {"token": token, "provider": "demo"}


# ---------- Admin: users ----------


@app.get("/admin/users")
@app.get("/api/admin/users")
def list_users(user=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user)
    users = db.execute(select(User).order_by(User.email)).scalars().all()
    return {"users": [sanitize_user(db, u) for u in users]}


@app.post("/admin/users")
@app.post("/api/admin/users")
def create_user(body: dict, user=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user)
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid body")

    email = normalize_email(body.get("email") or body.get("username"))
    role = (body.get("role") or "client").strip()
    allowed_slots = body.get("allowed_slots") or []
    aliases = body.get("google_emails") or []
    send_invite = bool(body.get("send_invite", False))

    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email required")
    if role not in ("admin", "client"):
        raise HTTPException(status_code=400, detail="Invalid role")
    if not isinstance(allowed_slots, list):
        raise HTTPException(status_code=400, detail="allowed_slots must be a list")
    if not isinstance(aliases, list):
        raise HTTPException(status_code=400, detail="google_emails must be a list")

    if find_user_by_email(db, email):
        raise HTTPException(status_code=409, detail="User already exists")

    new_user = User(email=email, role=role, disabled=bool(body.get("disabled", False)))
    db.add(new_user)
    db.flush()

    cleaned_aliases = [normalize_email(a) for a in aliases if normalize_email(a) and normalize_email(a) != email]
    for alias in dict.fromkeys(cleaned_aliases):
        db.add(UserEmail(user_id=new_user.id, email=alias, is_primary=False))

    _set_user_slots(db, new_user, allowed_slots)
    db.commit()
    invite_status = None
    if send_invite:
        invite_status = _send_invite_email([email])
    return {"user": sanitize_user(db, new_user), "invite": invite_status}


@app.post("/admin/users/{username}/slots")
@app.post("/api/admin/users/{username}/slots")
def update_user_slots(username: str, body: dict, user=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user)
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid body")
    allowed_slots = body.get("allowed_slots") or []
    if not isinstance(allowed_slots, list):
        raise HTTPException(status_code=400, detail="allowed_slots must be a list")

    target = find_user_by_email(db, username)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    _set_user_slots(db, target, allowed_slots)
    db.commit()
    return {"user": sanitize_user(db, target)}


@app.post("/admin/users/{username}/status")
@app.post("/api/admin/users/{username}/status")
def set_user_status(username: str, body: dict, user=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user)
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid body")
    disabled = bool(body.get("disabled", False))

    target = find_user_by_email(db, username)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.disabled = disabled
    db.commit()
    return {"user": sanitize_user(db, target)}


@app.delete("/admin/users/{username}")
@app.delete("/api/admin/users/{username}")
def delete_user(username: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    require_admin(user)
    target = find_user_by_email(db, username)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(target)
    db.commit()
    return {"deleted": True}


@app.post("/admin/invites")
@app.post("/api/admin/invites")
def send_invites(body: dict = Body(default=None), user=Depends(get_current_user)):
    require_admin(user)
    payload = body or {}
    recipients = []
    email = normalize_email(payload.get("email"))
    if email:
        recipients.append(email)
    raw = payload.get("recipients")
    if isinstance(raw, list):
        for entry in raw:
            normalized = normalize_email(entry)
            if normalized and normalized not in recipients:
                recipients.append(normalized)
    if not recipients:
        raise HTTPException(status_code=400, detail="Recipients required")
    return _send_invite_email(recipients)


@app.post("/admin/notifications/maintenance")
@app.post("/api/admin/notifications/maintenance")
def send_maintenance_notice(
    body: dict = Body(default=None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin(user)
    payload = body or {}
    subject = str(payload.get("subject") or "Engyne maintenance notice").strip()
    message = str(payload.get("message") or payload.get("body") or "").strip()
    html = payload.get("html")
    if not message:
        raise HTTPException(status_code=400, detail="Message required")
    if not SMTP_HOST or not SMTP_FROM:
        raise HTTPException(status_code=400, detail="SMTP is not configured")
    recipients = _resolve_notification_recipients(db, payload)
    if not recipients:
        raise HTTPException(status_code=400, detail="No recipients available")
    result = send_bulk_email(
        SMTP_HOST,
        SMTP_PORT,
        SMTP_USERNAME,
        SMTP_PASSWORD,
        SMTP_UPDATES_FROM,
        SMTP_UPDATES_FROM_NAME,
        recipients,
        subject,
        message,
        html if isinstance(html, str) else None,
    )
    return {"sent": len(result["sent"]), "failed": result["failed"]}


@app.post("/admin/notifications/update")
@app.post("/api/admin/notifications/update")
def send_update_notice(
    body: dict = Body(default=None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin(user)
    payload = body or {}
    subject = str(payload.get("subject") or "Engyne product update").strip()
    message = str(payload.get("message") or payload.get("body") or "").strip()
    html = payload.get("html")
    if not message:
        raise HTTPException(status_code=400, detail="Message required")
    if not SMTP_HOST or not SMTP_FROM:
        raise HTTPException(status_code=400, detail="SMTP is not configured")
    recipients = _resolve_notification_recipients(db, payload)
    if not recipients:
        raise HTTPException(status_code=400, detail="No recipients available")
    result = send_bulk_email(
        SMTP_HOST,
        SMTP_PORT,
        SMTP_USERNAME,
        SMTP_PASSWORD,
        SMTP_UPDATES_FROM,
        SMTP_UPDATES_FROM_NAME,
        recipients,
        subject,
        message,
        html if isinstance(html, str) else None,
    )
    return {"sent": len(result["sent"]), "failed": result["failed"]}


# ---------- Slots ----------


def _local_slots_for_user(user: dict) -> list[dict]:
    slots = []
    allowed = set(normalize_allowed_slots(user.get("allowed_slots") or []))

    if not SLOTS_DIR.exists():
        return []

    for slot_dir in SLOTS_DIR.iterdir():
        if not slot_dir.is_dir() or slot_dir.name.startswith("."):
            continue
        if is_hidden_slot(slot_dir.name):
            continue

        slot_id = slot_dir.name
        if user.get("role") != "admin" and slot_id not in allowed:
            continue

        state = load_json(slot_dir / "slot_state.json", None)
        if not state:
            state = load_json(slot_dir / "state.json", {})
        if state:
            state["slot_id"] = slot_id
            state["node_id"] = NODE_ID
            state["node_name"] = NODE_NAME
            state["slot_key"] = state.get("slot_key") or f"{NODE_ID}::{slot_id}"
            slots.append(state)

    return slots


@app.get("/slots")
@app.get("/api/slots")
def get_slots(user=Depends(get_current_user), db: Session = Depends(get_db)):
    nodes = load_nodes_config()
    if not nodes:
        return {"slots": _local_slots_for_user(user)}

    allowed = set(normalize_allowed_slots(user.get("allowed_slots") or []))
    slots = []
    errors = []

    for node in nodes:
        node_id = node.get("node_id") or ""
        node_name = node.get("node_name") or node_id or "node"
        base_url = node.get("base_url") or ""
        try:
            if base_url:
                data = node_request_json(node, db, "GET", "/slots")
                node_slots = data.get("slots") if isinstance(data, dict) else []
            else:
                node_slots = _local_slots_for_user(user)
        except HTTPException as exc:
            errors.append({"node_id": node_id, "detail": exc.detail})
            node_slots = []

        for slot in node_slots or []:
            slot_id = slot.get("slot_id") or slot.get("id") or ""
            if is_hidden_slot(slot_id):
                continue
            if user.get("role") != "admin" and slot_id not in allowed:
                continue
            slot["node_id"] = node_id
            slot["node_name"] = node_name
            if slot_id:
                slot["slot_id"] = slot_id
                slot["slot_key"] = slot.get("slot_key") or f"{node_id}::{slot_id}"
            slots.append(slot)

    return {"slots": slots, "errors": errors}


@app.get("/slots/{slot_id}/status")
@app.get("/api/slots/{slot_id}/status")
def get_slot_status(slot_id: str, user=Depends(get_current_user)):
    ensure_allowed_slot(user, slot_id)
    state = load_slot_state(slot_id)
    state["node_id"] = NODE_ID
    state["node_name"] = NODE_NAME
    return state


@app.get("/slots/{slot_id}/metrics")
@app.get("/api/slots/{slot_id}/metrics")
def get_slot_metrics(slot_id: str, user=Depends(get_current_user)):
    ensure_allowed_slot(user, slot_id)
    state = load_slot_state(slot_id)
    metrics = state.get("metrics") or {}
    if not isinstance(metrics, dict):
        metrics = {}
    return metrics


@app.get("/slots/{slot_id}/leads")
@app.get("/api/slots/{slot_id}/leads")
def get_slot_leads(slot_id: str, limit: int = 200, user=Depends(get_current_user)):
    ensure_allowed_slot(user, slot_id)
    return {"leads": read_leads(slot_id, limit)}


@app.get("/slots/{slot_id}/leads/download")
@app.get("/api/slots/{slot_id}/leads/download")
def download_slot_leads(slot_id: str, user=Depends(get_current_user)):
    ensure_allowed_slot(user, slot_id)
    slot_dir = require_slot_dir(slot_id)
    leads_path = slot_dir / "leads.jsonl"
    if not leads_path.exists():
        raise HTTPException(status_code=404, detail="No leads found")
    filename = f"{slot_id}_leads.jsonl"
    return FileResponse(leads_path, filename=filename, media_type="text/plain")


@app.get("/slots/{slot_id}/quality")
@app.get("/api/slots/{slot_id}/quality")
def get_slot_quality(slot_id: str, user=Depends(get_current_user)):
    ensure_allowed_slot(user, slot_id)
    config = load_slot_config(slot_id)
    return {
        "quality_level": int(config.get("quality_level") or 70),
        "min_member_months": int(config.get("min_member_months") or 0),
        "max_age_hours": int(config.get("max_age_hours") or 48),
    }


@app.post("/slots/{slot_id}/quality")
@app.post("/api/slots/{slot_id}/quality")
def update_slot_quality(
    slot_id: str,
    body: dict = Body(default=None),
    user=Depends(get_current_user),
):
    ensure_allowed_slot(user, slot_id)
    config = load_slot_config(slot_id)
    payload = body or {}
    if "quality_level" in payload:
        config["quality_level"] = int(payload.get("quality_level") or 0)
    save_slot_config(slot_id, config)
    return {
        "quality_level": int(config.get("quality_level") or 70),
        "min_member_months": int(config.get("min_member_months") or 0),
        "max_age_hours": int(config.get("max_age_hours") or 48),
    }


@app.get("/slots/{slot_id}/client-limits")
@app.get("/api/slots/{slot_id}/client-limits")
def get_slot_client_limits(slot_id: str, user=Depends(get_current_user)):
    ensure_allowed_slot(user, slot_id)
    config = load_slot_config(slot_id)
    return {
        "max_clicks_per_run": int(config.get("max_clicks_per_run") or 0),
        "max_run_minutes": int(config.get("max_run_minutes") or 0),
    }


@app.post("/slots/{slot_id}/client-limits")
@app.post("/api/slots/{slot_id}/client-limits")
def update_slot_client_limits(
    slot_id: str,
    body: dict = Body(default=None),
    user=Depends(get_current_user),
):
    ensure_allowed_slot(user, slot_id)
    payload = body or {}
    config = load_slot_config(slot_id)
    if "max_clicks_per_run" in payload:
        config["max_clicks_per_run"] = int(payload.get("max_clicks_per_run") or 0)
    if "max_run_minutes" in payload:
        config["max_run_minutes"] = int(payload.get("max_run_minutes") or 0)
    save_slot_config(slot_id, config)
    return {
        "max_clicks_per_run": int(config.get("max_clicks_per_run") or 0),
        "max_run_minutes": int(config.get("max_run_minutes") or 0),
    }


@app.get("/slots/{slot_id}/login-mode")
@app.get("/api/slots/{slot_id}/login-mode")
def get_slot_login_mode(slot_id: str, user=Depends(get_current_user)):
    ensure_allowed_slot(user, slot_id)
    config = load_slot_config(slot_id)
    return {"login_mode": bool(config.get("login_mode", False))}


@app.post("/slots/{slot_id}/login-mode")
@app.post("/api/slots/{slot_id}/login-mode")
def update_slot_login_mode(
    slot_id: str,
    body: dict = Body(default=None),
    user=Depends(get_current_user),
):
    ensure_allowed_slot(user, slot_id)
    payload = body or {}
    config = load_slot_config(slot_id)
    config["login_mode"] = bool(payload.get("login_mode", False))
    save_slot_config(slot_id, config)
    return {"login_mode": bool(config.get("login_mode", False))}


@app.post("/slots/{slot_id}/login-request")
@app.post("/api/slots/{slot_id}/login-request")
def request_slot_login(
    slot_id: str,
    body: dict = Body(default=None),
    user=Depends(get_current_user),
):
    ensure_allowed_slot(user, slot_id)
    slot_dir = require_slot_dir(slot_id)
    commands_dir = slot_dir / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    payload = body or {}
    note = payload.get("note")
    save_json(
        commands_dir / "login_request.json",
        {"note": note, "requested_at": datetime.utcnow().isoformat() + "Z"},
    )
    return {"requested": True}


@app.get("/slots/{slot_id}/headless")
@app.get("/api/slots/{slot_id}/headless")
def get_slot_headless(slot_id: str, user=Depends(get_current_user)):
    ensure_allowed_slot(user, slot_id)
    config = load_slot_config(slot_id)
    return {"headless": bool(config.get("headless", False))}


@app.post("/slots/{slot_id}/headless")
@app.post("/api/slots/{slot_id}/headless")
def update_slot_headless(
    slot_id: str,
    body: dict = Body(default=None),
    user=Depends(get_current_user),
):
    ensure_allowed_slot(user, slot_id)
    payload = body or {}
    config = load_slot_config(slot_id)
    config["headless"] = bool(payload.get("headless", False))
    save_slot_config(slot_id, config)
    return {"headless": bool(config.get("headless", False))}


@app.post("/slots/{slot_id}/display-name")
@app.post("/api/slots/{slot_id}/display-name")
def update_slot_display_name(
    slot_id: str,
    body: dict = Body(default=None),
    user=Depends(get_current_user),
):
    ensure_allowed_slot(user, slot_id)
    payload = body or {}
    display_name = str(payload.get("display_name") or "").strip()
    config = load_slot_config(slot_id)
    if display_name:
        config["display_name"] = display_name
    elif "display_name" in config:
        config.pop("display_name")
    save_slot_config(slot_id, config)
    return {"display_name": config.get("display_name") or ""}


@app.get("/slots/{slot_id}/config")
@app.get("/api/slots/{slot_id}/config")
def get_slot_config(slot_id: str, user=Depends(get_current_user)):
    ensure_allowed_slot(user, slot_id)
    return {"config": load_slot_config(slot_id)}


@app.post("/slots/{slot_id}/config")
@app.post("/api/slots/{slot_id}/config")
def update_slot_config(
    slot_id: str,
    body: dict = Body(default=None),
    user=Depends(get_current_user),
):
    ensure_allowed_slot(user, slot_id)
    payload = body or {}
    incoming = payload.get("config")
    if not isinstance(incoming, dict):
        incoming = {}
    config = load_slot_config(slot_id)
    config.update(incoming)
    save_slot_config(slot_id, config)
    return {"config": config}


@app.get("/slots/{slot_id}/whatsapp/status")
@app.get("/api/slots/{slot_id}/whatsapp/status")
def get_whatsapp_status(slot_id: str, user=Depends(get_current_user)):
    ensure_allowed_slot(user, slot_id)
    config = load_slot_config(slot_id)
    base = _waha_base(config)
    session = _waha_session(config, slot_id)
    data = _waha_request(base, "GET", f"/api/sessions/{session}")
    return {"session": session, "status": data}


@app.post("/slots/{slot_id}/whatsapp/connect")
@app.post("/api/slots/{slot_id}/whatsapp/connect")
def connect_whatsapp(slot_id: str, user=Depends(get_current_user)):
    ensure_allowed_slot(user, slot_id)
    config = load_slot_config(slot_id)
    base = _waha_base(config)
    session = _waha_session(config, slot_id)
    webhook_url = (config.get("whatsapp_waha_webhook_url") or "").strip()

    try:
        data = _waha_request(base, "GET", f"/api/sessions/{session}")
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        payload = {"name": session, "start": True}
        if webhook_url:
            payload["config"] = {"webhookUrl": webhook_url}
        data = _waha_request(base, "POST", "/api/sessions", payload=payload)
        return {"session": session, "status": data}

    try:
        _waha_request(base, "POST", f"/api/sessions/{session}/start")
    except HTTPException:
        pass
    return {"session": session, "status": data}


@app.post("/slots/{slot_id}/whatsapp/disconnect")
@app.post("/api/slots/{slot_id}/whatsapp/disconnect")
def disconnect_whatsapp(slot_id: str, user=Depends(get_current_user)):
    ensure_allowed_slot(user, slot_id)
    config = load_slot_config(slot_id)
    base = _waha_base(config)
    session = _waha_session(config, slot_id)
    try:
        return {"session": session, "status": _waha_request(base, "POST", f"/api/sessions/{session}/logout")}
    except HTTPException:
        return {"session": session, "status": _waha_request(base, "POST", f"/api/sessions/{session}/stop")}


@app.get("/slots/{slot_id}/whatsapp/qr")
@app.get("/api/slots/{slot_id}/whatsapp/qr")
def get_whatsapp_qr(slot_id: str, user=Depends(get_current_user)):
    ensure_allowed_slot(user, slot_id)
    config = load_slot_config(slot_id)
    base = _waha_base(config)
    session = _waha_session(config, slot_id)
    data = _waha_request(base, "GET", f"/api/sessions/{session}/qr")
    if isinstance(data, dict):
        qr = data.get("qr") or data.get("qrCode") or data.get("data")
    else:
        qr = data
    return {"session": session, "qr": qr}


@app.post("/slots/{slot_id}/pause")
@app.post("/api/slots/{slot_id}/pause")
def pause_slot(slot_id: str, user=Depends(get_current_user)):
    ensure_allowed_slot(user, slot_id)
    stop_slot(slot_id, user)
    state = load_slot_state(slot_id)
    state["status"] = "STOPPED"
    state["last_command"] = "PAUSE"
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    save_json(slot_path(slot_id) / "slot_state.json", state)
    return {"status": "paused"}


@app.post("/slots/{slot_id}/dry-run/{mode}")
@app.post("/api/slots/{slot_id}/dry-run/{mode}")
def set_dry_run(slot_id: str, mode: str, user=Depends(get_current_user)):
    ensure_allowed_slot(user, slot_id)
    flag = str(mode).lower() in ("1", "true", "yes", "on")
    config = load_slot_config(slot_id)
    config["dry_run"] = flag
    save_slot_config(slot_id, config)
    return {"dry_run": flag}


@app.post("/slots/{slot_id}/remote-login/start")
@app.post("/api/slots/{slot_id}/remote-login/start")
async def start_remote_login(
    slot_id: str,
    request: Request,
    body: dict = Body(default=None),
    user=Depends(get_current_user),
):
    ensure_allowed_slot(user, slot_id)
    if not REMOTE_LOGIN_ENABLED:
        raise HTTPException(status_code=501, detail="Remote login not enabled on this node")
    require_slot_dir(slot_id)
    payload = body or {}
    target = str(payload.get("target") or "indiamart").strip().lower() or "indiamart"
    target_url = REMOTE_LOGIN_TARGETS.get(target)
    if not target_url:
        raise HTTPException(status_code=400, detail="Unsupported login target")

    session = await REMOTE_LOGIN_MANAGER.get_or_create(slot_id, user.get("sub"), target_url)
    base = _remote_login_base(request)
    data = session.snapshot(base)
    data["node_id"] = NODE_ID
    data["node_name"] = NODE_NAME
    return data


@app.get("/remote-login/sessions/{session_id}")
@app.get("/api/remote-login/sessions/{session_id}")
async def get_remote_login_session(
    session_id: str,
    request: Request,
    user=Depends(get_current_user),
):
    if not REMOTE_LOGIN_ENABLED:
        raise HTTPException(status_code=501, detail="Remote login not enabled on this node")
    session = REMOTE_LOGIN_MANAGER.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    ensure_allowed_slot(user, session.slot_id)
    base = _remote_login_base(request)
    return session.snapshot(base)


@app.post("/remote-login/sessions/{session_id}/finish")
@app.post("/api/remote-login/sessions/{session_id}/finish")
async def finish_remote_login_session(
    session_id: str,
    user=Depends(get_current_user),
):
    if not REMOTE_LOGIN_ENABLED:
        raise HTTPException(status_code=501, detail="Remote login not enabled on this node")
    session = REMOTE_LOGIN_MANAGER.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    ensure_allowed_slot(user, session.slot_id)
    await REMOTE_LOGIN_MANAGER.finish(session_id)
    return {"finished": True}


@app.post("/slots/{slot_id}/start")
@app.post("/api/slots/{slot_id}/start")
def start_slot(slot_id: str, user=Depends(get_current_user)):
    ensure_allowed_slot(user, slot_id)
    slot_dir = slot_path(slot_id)
    state_file = slot_dir / "slot_state.json"

    if not slot_dir.exists():
        raise HTTPException(status_code=404, detail="Slot not found")

    state = load_json(state_file, {})
    if state.get("status") == "RUNNING":
        return {"status": "already_running"}

    if not state.get("slot_id"):
        state["slot_id"] = slot_id
    if not state.get("worker"):
        state["worker"] = DEFAULT_SLOT_WORKER
    if not state.get("mode"):
        state["mode"] = DEFAULT_SLOT_MODE

    process = subprocess.Popen(
        ["python3", str(ENGINE_DIR / "runner.py"), slot_id],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    state.update(
        {
            "status": "RUNNING",
            "pid": process.pid,
            "last_command": "START",
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
    )

    save_json(state_file, state)
    return {"status": "started", "pid": process.pid}


@app.post("/slots/{slot_id}/stop")
@app.post("/api/slots/{slot_id}/stop")
def stop_slot(slot_id: str, user=Depends(get_current_user)):
    ensure_allowed_slot(user, slot_id)
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

    state.update(
        {
            "status": "STOPPED",
            "pid": None,
            "last_command": "STOP",
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
    )

    save_json(state_file, state)
    return {"status": "stopped"}


@app.post("/slots/{slot_id}/restart")
@app.post("/api/slots/{slot_id}/restart")
def restart_slot(slot_id: str, user=Depends(get_current_user)):
    ensure_allowed_slot(user, slot_id)
    stop_slot(slot_id, user)
    return start_slot(slot_id, user)


# ---------- Cluster Slots ----------


@app.get("/cluster/slots")
@app.get("/api/cluster/slots")
def get_cluster_slots(user=Depends(get_current_user), db: Session = Depends(get_db)):
    if user.get("role") != "admin":
        return get_slots(user, db)
    nodes = load_nodes_config()
    if not nodes:
        return get_slots(user)

    slots = []
    errors = []

    for node in nodes:
        node_id = node.get("node_id") or ""
        node_name = node.get("node_name") or node_id or "node"
        base_url = node.get("base_url") or ""
        try:
            if base_url:
                data = node_request_json(node, db, "GET", "/slots")
                node_slots = data.get("slots") if isinstance(data, dict) else []
            else:
                node_slots = get_slots(user).get("slots", [])
        except HTTPException as exc:
            errors.append({"node_id": node_id, "detail": exc.detail})
            node_slots = [
                {
                    "slot_id": f"{node_id}::unreachable",
                    "node_id": node_id,
                    "node_name": node_name,
                    "status": "ERROR",
                    "mode": "OFFLINE",
                }
            ]

        for slot in node_slots or []:
            slot_id = slot.get("slot_id") or slot.get("id") or ""
            slot["node_id"] = node_id
            slot["node_name"] = node_name
            if slot_id:
                slot["slot_id"] = slot_id
                slot["slot_key"] = slot.get("slot_key") or f"{node_id}::{slot_id}"
            slots.append(slot)

    return {"slots": slots, "errors": errors}


@app.get("/cluster/slots/{node_id}/{slot_id}/status")
@app.get("/api/cluster/slots/{node_id}/{slot_id}/status")
def get_cluster_slot_status(
    node_id: str,
    slot_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return get_slot_status(slot_id, user)
    return node_request_json(node, db, "GET", f"/slots/{slot_id}/status")


@app.get("/cluster/slots/{node_id}/{slot_id}/metrics")
@app.get("/api/cluster/slots/{node_id}/{slot_id}/metrics")
def get_cluster_slot_metrics(
    node_id: str,
    slot_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return get_slot_metrics(slot_id, user)
    return node_request_json(node, db, "GET", f"/slots/{slot_id}/metrics")


@app.get("/cluster/slots/{node_id}/{slot_id}/leads")
@app.get("/api/cluster/slots/{node_id}/{slot_id}/leads")
def get_cluster_slot_leads(
    node_id: str,
    slot_id: str,
    limit: int = 200,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return get_slot_leads(slot_id, limit, user)
    return node_request_json(node, db, "GET", f"/slots/{slot_id}/leads", params={"limit": limit})


@app.get("/cluster/slots/{node_id}/{slot_id}/leads/download")
@app.get("/api/cluster/slots/{node_id}/{slot_id}/leads/download")
def download_cluster_slot_leads(
    node_id: str,
    slot_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return download_slot_leads(slot_id, user)
    res = node_request_json(node, db, "GET", f"/slots/{slot_id}/leads/download", stream=True)
    filename = f"{slot_id}_leads.jsonl"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    media_type = res.headers.get("content-type", "text/plain")
    return StreamingResponse(res.iter_content(chunk_size=8192), media_type=media_type, headers=headers)


@app.get("/cluster/slots/{node_id}/{slot_id}/quality")
@app.get("/api/cluster/slots/{node_id}/{slot_id}/quality")
def get_cluster_slot_quality(
    node_id: str,
    slot_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return get_slot_quality(slot_id, user)
    return node_request_json(node, db, "GET", f"/slots/{slot_id}/quality")


@app.post("/cluster/slots/{node_id}/{slot_id}/quality")
@app.post("/api/cluster/slots/{node_id}/{slot_id}/quality")
def update_cluster_slot_quality(
    node_id: str,
    slot_id: str,
    body: dict = Body(default=None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return update_slot_quality(slot_id, body, user)
    return node_request_json(node, db, "POST", f"/slots/{slot_id}/quality", payload=body or {})


@app.get("/cluster/slots/{node_id}/{slot_id}/client-limits")
@app.get("/api/cluster/slots/{node_id}/{slot_id}/client-limits")
def get_cluster_client_limits(
    node_id: str,
    slot_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return get_slot_client_limits(slot_id, user)
    return node_request_json(node, db, "GET", f"/slots/{slot_id}/client-limits")


@app.post("/cluster/slots/{node_id}/{slot_id}/client-limits")
@app.post("/api/cluster/slots/{node_id}/{slot_id}/client-limits")
def update_cluster_client_limits(
    node_id: str,
    slot_id: str,
    body: dict = Body(default=None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return update_slot_client_limits(slot_id, body, user)
    return node_request_json(node, db, "POST", f"/slots/{slot_id}/client-limits", payload=body or {})


@app.get("/cluster/slots/{node_id}/{slot_id}/login-mode")
@app.get("/api/cluster/slots/{node_id}/{slot_id}/login-mode")
def get_cluster_login_mode(
    node_id: str,
    slot_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return get_slot_login_mode(slot_id, user)
    return node_request_json(node, db, "GET", f"/slots/{slot_id}/login-mode")


@app.post("/cluster/slots/{node_id}/{slot_id}/login-mode")
@app.post("/api/cluster/slots/{node_id}/{slot_id}/login-mode")
def update_cluster_login_mode(
    node_id: str,
    slot_id: str,
    body: dict = Body(default=None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return update_slot_login_mode(slot_id, body, user)
    return node_request_json(node, db, "POST", f"/slots/{slot_id}/login-mode", payload=body or {})


@app.post("/cluster/slots/{node_id}/{slot_id}/login-request")
@app.post("/api/cluster/slots/{node_id}/{slot_id}/login-request")
def request_cluster_login(
    node_id: str,
    slot_id: str,
    body: dict = Body(default=None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return request_slot_login(slot_id, body, user)
    return node_request_json(node, db, "POST", f"/slots/{slot_id}/login-request", payload=body or {})


@app.get("/cluster/slots/{node_id}/{slot_id}/headless")
@app.get("/api/cluster/slots/{node_id}/{slot_id}/headless")
def get_cluster_headless(
    node_id: str,
    slot_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return get_slot_headless(slot_id, user)
    return node_request_json(node, db, "GET", f"/slots/{slot_id}/headless")


@app.post("/cluster/slots/{node_id}/{slot_id}/headless")
@app.post("/api/cluster/slots/{node_id}/{slot_id}/headless")
def update_cluster_headless(
    node_id: str,
    slot_id: str,
    body: dict = Body(default=None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return update_slot_headless(slot_id, body, user)
    return node_request_json(node, db, "POST", f"/slots/{slot_id}/headless", payload=body or {})


@app.post("/cluster/slots/{node_id}/{slot_id}/display-name")
@app.post("/api/cluster/slots/{node_id}/{slot_id}/display-name")
def update_cluster_display_name(
    node_id: str,
    slot_id: str,
    body: dict = Body(default=None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return update_slot_display_name(slot_id, body, user)
    return node_request_json(node, db, "POST", f"/slots/{slot_id}/display-name", payload=body or {})


@app.get("/cluster/slots/{node_id}/{slot_id}/config")
@app.get("/api/cluster/slots/{node_id}/{slot_id}/config")
def get_cluster_config(
    node_id: str,
    slot_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return get_slot_config(slot_id, user)
    return node_request_json(node, db, "GET", f"/slots/{slot_id}/config")


@app.post("/cluster/slots/{node_id}/{slot_id}/config")
@app.post("/api/cluster/slots/{node_id}/{slot_id}/config")
def update_cluster_config(
    node_id: str,
    slot_id: str,
    body: dict = Body(default=None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return update_slot_config(slot_id, body, user)
    return node_request_json(node, db, "POST", f"/slots/{slot_id}/config", payload=body or {})


@app.get("/cluster/slots/{node_id}/{slot_id}/whatsapp/status")
@app.get("/api/cluster/slots/{node_id}/{slot_id}/whatsapp/status")
def get_cluster_whatsapp_status(
    node_id: str,
    slot_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return get_whatsapp_status(slot_id, user)
    return node_request_json(node, db, "GET", f"/slots/{slot_id}/whatsapp/status")


@app.post("/cluster/slots/{node_id}/{slot_id}/whatsapp/connect")
@app.post("/api/cluster/slots/{node_id}/{slot_id}/whatsapp/connect")
def connect_cluster_whatsapp(
    node_id: str,
    slot_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return connect_whatsapp(slot_id, user)
    return node_request_json(node, db, "POST", f"/slots/{slot_id}/whatsapp/connect")


@app.post("/cluster/slots/{node_id}/{slot_id}/whatsapp/disconnect")
@app.post("/api/cluster/slots/{node_id}/{slot_id}/whatsapp/disconnect")
def disconnect_cluster_whatsapp(
    node_id: str,
    slot_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return disconnect_whatsapp(slot_id, user)
    return node_request_json(node, db, "POST", f"/slots/{slot_id}/whatsapp/disconnect")


@app.get("/cluster/slots/{node_id}/{slot_id}/whatsapp/qr")
@app.get("/api/cluster/slots/{node_id}/{slot_id}/whatsapp/qr")
def get_cluster_whatsapp_qr(
    node_id: str,
    slot_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return get_whatsapp_qr(slot_id, user)
    return node_request_json(node, db, "GET", f"/slots/{slot_id}/whatsapp/qr")


@app.post("/cluster/slots/{node_id}/{slot_id}/pause")
@app.post("/api/cluster/slots/{node_id}/{slot_id}/pause")
def pause_cluster_slot(
    node_id: str,
    slot_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return pause_slot(slot_id, user)
    return node_request_json(node, db, "POST", f"/slots/{slot_id}/pause")


@app.post("/cluster/slots/{node_id}/{slot_id}/dry-run/{mode}")
@app.post("/api/cluster/slots/{node_id}/{slot_id}/dry-run/{mode}")
def dry_run_cluster_slot(
    node_id: str,
    slot_id: str,
    mode: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return set_dry_run(slot_id, mode, user)
    return node_request_json(node, db, "POST", f"/slots/{slot_id}/dry-run/{mode}")


@app.post("/cluster/slots/{node_id}/{slot_id}/remote-login/start")
@app.post("/api/cluster/slots/{node_id}/{slot_id}/remote-login/start")
async def start_cluster_remote_login(
    node_id: str,
    slot_id: str,
    request: Request,
    body: dict = Body(default=None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.get("role") != "admin":
        ensure_allowed_slot(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return await start_remote_login(slot_id, request, body, user)
    return node_request_json(node, db, "POST", f"/slots/{slot_id}/remote-login/start", payload=body or {})


@app.get("/cluster/remote-login/{node_id}/{session_id}")
@app.get("/api/cluster/remote-login/{node_id}/{session_id}")
def get_cluster_remote_login_session(
    node_id: str,
    session_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin(user)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        if not REMOTE_LOGIN_ENABLED:
            raise HTTPException(status_code=501, detail="Remote login not enabled on this node")
        session = REMOTE_LOGIN_MANAGER.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        base = REMOTE_LOGIN_PUBLIC_BASE or "http://127.0.0.1:8001"
        data = session.snapshot(base)
        data["node_id"] = NODE_ID
        data["node_name"] = NODE_NAME
        return data
    return node_request_json(node, db, "GET", f"/remote-login/sessions/{session_id}")


@app.post("/cluster/remote-login/{node_id}/{session_id}/finish")
@app.post("/api/cluster/remote-login/{node_id}/{session_id}/finish")
async def finish_cluster_remote_login_session(
    node_id: str,
    session_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin(user)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        await REMOTE_LOGIN_MANAGER.finish(session_id)
        return {"finished": True}
    return node_request_json(node, db, "POST", f"/remote-login/sessions/{session_id}/finish")


@app.post("/cluster/slots/{node_id}/{slot_id}/start")
@app.post("/api/cluster/slots/{node_id}/{slot_id}/start")
def start_cluster_slot(
    node_id: str,
    slot_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return start_slot(slot_id, user)
    return node_request_json(node, db, "POST", f"/slots/{slot_id}/start")


@app.post("/cluster/slots/{node_id}/{slot_id}/stop")
@app.post("/api/cluster/slots/{node_id}/{slot_id}/stop")
def stop_cluster_slot(
    node_id: str,
    slot_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return stop_slot(slot_id, user)
    return node_request_json(node, db, "POST", f"/slots/{slot_id}/stop")


@app.post("/cluster/slots/{node_id}/{slot_id}/restart")
@app.post("/api/cluster/slots/{node_id}/{slot_id}/restart")
def restart_cluster_slot(
    node_id: str,
    slot_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_or_allowed(user, slot_id)
    node = resolve_node(node_id)
    if not node.get("base_url"):
        return restart_slot(slot_id, user)
    return node_request_json(node, db, "POST", f"/slots/{slot_id}/restart")


@app.websocket("/remote-login/ws/{session_id}")
async def remote_login_ws(websocket: WebSocket, session_id: str, token: str = Query(default=None)):
    print(f"DEBUG: WebSocket connection attempt: {session_id}")
    if not REMOTE_LOGIN_ENABLED:
        print("DEBUG: Remote Login Disabled")
        await websocket.close(code=1008, reason="Remote login disabled")
        return
    db = SessionLocal()
    try:
        try:
            user = _user_from_token(token, db)
        except HTTPException as exc:
            await websocket.close(code=1008, reason=exc.detail)
            return

        session = REMOTE_LOGIN_MANAGER.get(session_id)
        if not session:
            await websocket.close(code=1008, reason="Session not found")
            return

        try:
            ensure_allowed_slot(user, session.slot_id)
        except HTTPException as exc:
            await websocket.close(code=1008, reason=exc.detail)
            return

        await websocket.accept()
        session.viewers.add(websocket)
        await websocket.send_json({"type": "status", "status": session.status, "expires_at": session.expires_at.isoformat() + "Z"})

        while True:
            message = await websocket.receive_json()
            await session.handle_input(message)
    except WebSocketDisconnect:
        pass
    finally:
        session.viewers.discard(websocket)
        db.close()
