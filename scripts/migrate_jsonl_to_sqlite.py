import os
import sys
import json
import logging
import sqlite3
import time
from pathlib import Path

# Setup paths
BASE_DIR = Path(os.environ.get("BASE_DIR_ENV") or Path(__file__).resolve().parent.parent)
sys.path.append(str(BASE_DIR))

from core.db.database import save_lead_to_db, init_db, get_connection

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("migration")

SLOTS_DIR = BASE_DIR / "slots"

def migrate_slot(slot_name: str):
    slot_dir = SLOTS_DIR / slot_name
    leads_path = slot_dir / "leads.jsonl"
    
    if not leads_path.exists():
        logger.warning(f"No leads.jsonl found for {slot_name}")
        return

    logger.info(f"Importing {leads_path}...")
    
    count = 0
    errors = 0
    t0 = time.time()
    
    with leads_path.open("r", encoding="utf-8") as f:
        # Use a single connection for bulk insert speed (though save_lead opens its own, 
        # for migration efficiently we should probably batch, but reuse existing logic for safety)
        # To make it fast, we can't reuse save_lead_to_db naively if it opens/closes on every call.
        # Let's write a batch inserter here.
        
        conn = get_connection()
        try:
            with conn:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                        
                    try:
                        lead = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                        
                    lead_id = lead.get("lead_id") or lead.get("id")
                    if not lead_id:
                        # Try to synthesize ID from URL or title?
                        # No, skip unsafe data
                        continue
                        
                    # Fix timestamps
                    fetched_at = lead.get("fetched_at")
                    clicked_at = lead.get("clicked_at")
                    
                    # Prepare row
                    title = lead.get("title")
                    url = lead.get("url") or lead.get("detail_url")
                    country = lead.get("country")
                    status = lead.get("status", "captured")
                    raw_json = json.dumps(lead)
                    
                    conn.execute("""
                        INSERT INTO leads (
                            lead_id, slot_id, title, url, country, status, 
                            fetched_at, clicked_at, raw_data
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(lead_id) DO UPDATE SET
                            status=excluded.status,
                            clicked_at=excluded.clicked_at,
                            raw_data=excluded.raw_data,
                            updated_at=CURRENT_TIMESTAMP
                    """, (
                        lead_id, slot_name, title, url, country, status, 
                        fetched_at, clicked_at, raw_json
                    ))
                    count += 1
                    
                    if count % 1000 == 0:
                        logger.info(f"  Processed {count} records...")
                        
        except Exception as e:
            logger.error(f"Migration failed for {slot_name}: {e}")
            errors += 1
        finally:
            conn.close()
            
    dt = time.time() - t0
    logger.info(f"✅ {slot_name}: Imported {count} leads in {dt:.2f}s")


def main():
    logger.info("🚀 Starting JSONL -> SQLite Migration")
    
    # 1. Init DB
    init_db()
    
    # 2. Find slots
    if not SLOTS_DIR.exists():
        logger.error("Slots directory not found!")
        return
        
    slots = sorted([d.name for d in SLOTS_DIR.iterdir() if d.is_dir() and d.name.startswith("slot")])
    
    for slot in slots:
        migrate_slot(slot)
        
    logger.info("✨ Migration Complete")

if __name__ == "__main__":
    main()
