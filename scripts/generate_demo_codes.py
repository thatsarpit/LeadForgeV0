#!/usr/bin/env python3
import argparse
import secrets
import sys
from pathlib import Path
from typing import Optional

from sqlalchemy import delete, select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from api.db import SessionLocal  # noqa: E402
from api.models import DemoCode, Slot  # noqa: E402


def ensure_slot(db, slot_id: str):
    if not slot_id:
        return
    if db.get(Slot, slot_id):
        return
    db.add(Slot(id=slot_id))


def generate_code(prefix: str, length: int, existing: set[str]) -> str:
    length = max(6, length)
    while True:
        code = secrets.token_hex(length // 2).upper()
        value = f"{prefix}{code}"
        if value not in existing:
            existing.add(value)
            return value


def parse_slots(arg: Optional[str], prefix: str, start: int, count: int) -> list[str]:
    if arg:
        return [s.strip() for s in arg.split(",") if s.strip()]
    return [f"{prefix}{i:03d}" for i in range(start, start + count)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate demo login codes")
    parser.add_argument("--slots", help="Comma-separated slot IDs (e.g. slot_001,slot_002)")
    parser.add_argument("--prefix", default="slot_", help="Slot prefix when using --start/--count")
    parser.add_argument("--start", type=int, default=1, help="Start index for slot generation")
    parser.add_argument("--count", type=int, default=10, help="Number of slots to generate")
    parser.add_argument("--code-prefix", default="DEMO-", help="Prefix for generated codes")
    parser.add_argument("--code-length", type=int, default=8, help="Length of random code part")
    parser.add_argument("--rotate", action="store_true", help="Replace existing codes for slots")
    args = parser.parse_args()

    slots = parse_slots(args.slots, args.prefix, args.start, args.count)
    if not slots:
        print("No slots provided.")
        return 1

    db = SessionLocal()
    try:
        existing_codes = set(db.execute(select(DemoCode.code)).scalars().all())
        results = []

        for slot_id in slots:
            if args.rotate:
                db.execute(delete(DemoCode).where(DemoCode.slot_id == slot_id))

            existing = db.scalar(
                select(DemoCode).where(DemoCode.slot_id == slot_id, DemoCode.active.is_(True))
            )
            if existing:
                results.append((slot_id, existing.code))
                continue

            ensure_slot(db, slot_id)
            code = generate_code(args.code_prefix, args.code_length, existing_codes)
            db.add(DemoCode(code=code, slot_id=slot_id, active=True))
            results.append((slot_id, code))

        db.commit()
    finally:
        db.close()

    print("Slot,Code")
    for slot_id, code in results:
        print(f"{slot_id},{code}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
