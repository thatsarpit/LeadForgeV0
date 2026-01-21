#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path
import shutil
from typing import Optional

import yaml
from sqlalchemy import delete, select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from api.db import SessionLocal  # noqa: E402
from api.models import Slot, User, UserEmail, UserSlot  # noqa: E402


def normalize_email(email: Optional[str]) -> str:
    return str(email or "").strip().lower()


def parse_allowed_slots(raw) -> list[str]:
    slots = []
    for entry in raw or []:
        val = str(entry).strip()
        if not val:
            continue
        if "::" in val:
            val = val.split("::")[-1]
        slots.append(val)
    return list(dict.fromkeys(slots))


def load_email_list(path: Optional[str]) -> set[str]:
    if not path:
        return set()
    data = Path(path).read_text().splitlines()
    return {normalize_email(line) for line in data if normalize_email(line)}


def load_users(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"users file not found: {path}")
    data = yaml.safe_load(path.read_text()) or []
    if not isinstance(data, list):
        raise ValueError("users file must be a list")
    return data


def ensure_slot(db, slot_id: str):
    if not slot_id:
        return
    if db.get(Slot, slot_id):
        return
    db.add(Slot(id=slot_id))


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy users.yml into Postgres")
    parser.add_argument("--users", default="config/users.yml", help="Path to users.yml")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    parser.add_argument("--reset", action="store_true", help="Delete existing users/slots before import")
    parser.add_argument("--update-existing", action="store_true", help="Update users if they already exist")
    parser.add_argument("--allowlist", help="Path to newline-separated email allowlist")
    parser.add_argument("--denylist", help="Path to newline-separated email denylist")
    parser.add_argument(
        "--seed-allowlist",
        action="store_true",
        help="Create allowlist users even if missing from users.yml",
    )
    parser.add_argument("--prune-slots", action="store_true", help="Delete slot dirs for skipped users")
    parser.add_argument("--slots-dir", default="slots", help="Slots directory (default: slots)")
    args = parser.parse_args()

    users_path = ROOT_DIR / args.users
    slots_dir = (ROOT_DIR / args.slots_dir).resolve()

    allowlist = load_email_list(args.allowlist)
    denylist = load_email_list(args.denylist)

    raw_users = load_users(users_path)

    kept = []
    skipped = []
    kept_slots = set()
    skipped_slots = set()

    for entry in raw_users:
        username = normalize_email(entry.get("username"))
        google_email = normalize_email(entry.get("google_email"))
        aliases = [normalize_email(e) for e in (entry.get("google_emails") or [])]
        aliases = [a for a in aliases if a and a != google_email and a != username]

        primary = google_email or username
        if not primary or "@" not in primary:
            slots = parse_allowed_slots(entry.get("allowed_slots") or [])
            skipped.append((primary or "<missing>", "missing_email", slots))
            skipped_slots.update(slots)
            continue
        if allowlist and primary not in allowlist:
            slots = parse_allowed_slots(entry.get("allowed_slots") or [])
            skipped.append((primary, "not_in_allowlist", slots))
            skipped_slots.update(slots)
            continue
        if denylist and primary in denylist:
            slots = parse_allowed_slots(entry.get("allowed_slots") or [])
            skipped.append((primary, "in_denylist", slots))
            skipped_slots.update(slots)
            continue

        slots = parse_allowed_slots(entry.get("allowed_slots") or [])
        kept.append(
            {
                "email": primary,
                "role": (entry.get("role") or "client").strip(),
                "disabled": bool(entry.get("disabled", False)),
                "aliases": list(dict.fromkeys([a for a in aliases if a and a != primary])),
                "slots": slots,
            }
        )
        kept_slots.update(slots)

    if args.seed_allowlist and allowlist:
        existing_emails = {item["email"] for item in kept}
        for email in sorted(allowlist):
            if email in existing_emails:
                continue
            kept.append(
                {
                    "email": email,
                    "role": "client",
                    "disabled": False,
                    "aliases": [],
                    "slots": [],
                }
            )

    slots_to_prune = sorted(skipped_slots - kept_slots)

    print("Migration preview")
    print(f"- users kept: {len(kept)}")
    print(f"- users skipped: {len(skipped)}")
    if skipped:
        sample = ", ".join([f"{email} ({reason})" for email, reason, _ in skipped[:5]])
        print(f"- skipped sample: {sample}")
    if slots_to_prune:
        print(f"- slots to prune: {len(slots_to_prune)}")

    if not args.apply:
        print("Dry-run only. Re-run with --apply to write changes.")
        return 0

    db = SessionLocal()
    try:
        if args.reset:
            db.execute(delete(UserSlot))
            db.execute(delete(UserEmail))
            db.execute(delete(User))
            db.execute(delete(Slot))
            db.commit()

        for item in kept:
            email = item["email"]
            role = item["role"] if item["role"] in ("admin", "client") else "client"
            disabled = item["disabled"]
            slots = item["slots"]

            user = db.scalar(select(User).where(User.email == email))
            if user:
                if not args.update_existing:
                    continue
                user.role = role
                user.disabled = disabled
            else:
                user = User(email=email, role=role, disabled=disabled)
                db.add(user)
                db.flush()

            db.execute(delete(UserSlot).where(UserSlot.user_id == user.id))
            for slot_id in slots:
                ensure_slot(db, slot_id)
                db.add(UserSlot(user_id=user.id, slot_id=slot_id))

            for alias in item["aliases"]:
                existing_alias = db.scalar(select(UserEmail).where(UserEmail.email == alias))
                if existing_alias:
                    continue
                db.add(UserEmail(user_id=user.id, email=alias, is_primary=False))

        db.commit()
    finally:
        db.close()

    if args.prune_slots and slots_to_prune:
        for slot_id in slots_to_prune:
            slot_dir = slots_dir / slot_id
            if slot_dir.exists() and slot_dir.is_dir():
                shutil.rmtree(slot_dir)
        print(f"Pruned {len(slots_to_prune)} slot directories.")

    print("Migration complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
