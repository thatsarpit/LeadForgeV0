#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
import shutil
import sys

import yaml


def load_users(path: Path):
    if not path.exists():
        return []
    try:
        return yaml.safe_load(path.read_text()) or []
    except Exception:
        return []


def save_users(path: Path, users):
    path.write_text(yaml.safe_dump(users, sort_keys=False))


def is_email_identity(user: dict) -> bool:
    username = str(user.get("username") or "").strip()
    if "@" in username:
        return True
    google_email = str(user.get("google_email") or "").strip()
    if google_email:
        return True
    google_emails = user.get("google_emails") or []
    return any(str(e or "").strip() for e in google_emails)


def normalize_slot_id(entry: str) -> str:
    raw = str(entry or "").strip()
    if not raw:
        return ""
    if "::" in raw:
        return raw.split("::", 1)[1].strip()
    return raw


def main():
    parser = argparse.ArgumentParser(description="Remove non-email test clients and their slots.")
    parser.add_argument("--users", default="config/users.yml", help="Path to users.yml")
    parser.add_argument("--slots", default="slots", help="Slots directory")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    args = parser.parse_args()

    users_path = Path(args.users)
    slots_dir = Path(args.slots)

    users = load_users(users_path)
    if not users:
        print(f"No users found in {users_path}.")
        return 0

    keep = []
    removed = []
    for user in users:
        role = str(user.get("role") or "").strip().lower()
        if role == "admin" or is_email_identity(user):
            keep.append(user)
        else:
            removed.append(user)

    keep_slot_ids = set()
    for user in keep:
        for entry in (user.get("allowed_slots") or []):
            slot_id = normalize_slot_id(entry)
            if slot_id:
                keep_slot_ids.add(slot_id)

    removed_slot_ids = set()
    for user in removed:
        for entry in (user.get("allowed_slots") or []):
            slot_id = normalize_slot_id(entry)
            if slot_id and slot_id not in keep_slot_ids:
                removed_slot_ids.add(slot_id)

    if not removed and not removed_slot_ids:
        print("No test clients or slots to remove.")
        return 0

    print("Dry-run summary:" if not args.apply else "Applied changes:")
    print(f"- Users kept: {len(keep)}")
    print(f"- Users removed: {len(removed)}")
    if removed:
        for user in removed:
            print(f"  - {user.get('username')}")
    print(f"- Slots to remove: {len(removed_slot_ids)}")
    for slot_id in sorted(removed_slot_ids):
        print(f"  - {slot_id}")

    if not args.apply:
        print("Run with --apply to write changes and remove slot directories.")
        return 0

    save_users(users_path, keep)

    if slots_dir.exists():
        for slot_id in removed_slot_ids:
            target = slots_dir / slot_id
            if target.exists() and target.is_dir():
                shutil.rmtree(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
