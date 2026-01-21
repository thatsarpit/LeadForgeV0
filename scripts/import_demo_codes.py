#!/usr/bin/env python3
import argparse
import csv
import sys
from pathlib import Path

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


def load_codes(path: Path) -> list[tuple[str, str]]:
    rows = []
    if not path.exists():
        raise FileNotFoundError(f"Codes file not found: {path}")
    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row:
                continue
            if row[0].strip().startswith("#"):
                continue
            if len(row) < 2:
                continue
            slot_id = row[0].strip()
            code = row[1].strip()
            if slot_id.lower() == "slot" and code.lower() == "code":
                continue
            if not slot_id or not code:
                continue
            rows.append((slot_id, code))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Import demo login codes from CSV")
    parser.add_argument("--file", default="config/demo_codes.csv", help="CSV file with Slot,Code")
    parser.add_argument("--rotate", action="store_true", help="Replace existing codes for slots in file")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    args = parser.parse_args()

    codes_path = (ROOT_DIR / args.file).resolve()
    entries = load_codes(codes_path)

    if not entries:
        print("No demo codes found.")
        return 1

    print(f"Found {len(entries)} codes in {codes_path}")
    if not args.apply:
        print("Dry-run only. Re-run with --apply to write changes.")
        return 0

    db = SessionLocal()
    try:
        for slot_id, code in entries:
            if args.rotate:
                db.execute(delete(DemoCode).where(DemoCode.slot_id == slot_id))

            existing_code = db.get(DemoCode, code)
            if existing_code and existing_code.slot_id != slot_id:
                raise ValueError(f"Code {code} already assigned to {existing_code.slot_id}")

            existing_slot_code = db.scalar(
                select(DemoCode).where(DemoCode.slot_id == slot_id, DemoCode.active.is_(True))
            )
            if existing_slot_code and existing_slot_code.code != code:
                db.delete(existing_slot_code)

            ensure_slot(db, slot_id)
            if existing_code:
                existing_code.active = True
            else:
                db.add(DemoCode(code=code, slot_id=slot_id, active=True))

        db.commit()
    finally:
        db.close()

    print("Import complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
