import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime, timezone
import logging

logger = logging.getLogger("leadforge.db")

# Dynamic DB path based on env or default relative to this file
BASE_DIR = Path(os.environ.get("BASE_DIR_ENV") or Path(__file__).resolve().parent.parent.parent)
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "leadforge.db"

def get_db_path() -> Path:
    """Ensure data directory exists and return DB path."""
    if not DATA_DIR.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DB_PATH

def get_connection():
    """Get a configured SQLite connection."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for concurrency
    conn.execute("PRAGMA journal_mode=WAL;")
    # Set a busy timeout to wait for locks (5 seconds)
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn

def init_db():
    """Initialize the database schema."""
    conn = get_connection()
    try:
        with conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS leads (
                    lead_id TEXT PRIMARY KEY,
                    slot_id TEXT NOT NULL,
                    title TEXT,
                    url TEXT,
                    country TEXT,
                    status TEXT,
                    fetched_at DATETIME,
                    clicked_at DATETIME,
                    verified_at DATETIME,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    raw_data JSON
                );
                
                -- Index for per-slot pagination and sorting
                CREATE INDEX IF NOT EXISTS idx_leads_slot_fetched 
                ON leads(slot_id, fetched_at DESC);
                
                -- Index for global or per-slot status filtering
                CREATE INDEX IF NOT EXISTS idx_leads_status 
                ON leads(status);
            """)
        logger.info(f"Database initialized at {DB_PATH}")
    finally:
        conn.close()

def save_lead_to_db(lead_data: dict, slot_id: str):
    """
    Insert or update a lead in the database.
    If lead exists, update fields (especially status/clicked_at).
    """
    conn = get_connection()
    try:
        lead_id = lead_data.get("lead_id") or lead_data.get("id")
        if not lead_id:
            logger.error("Cannot save lead without ID")
            return

        # Prepare core fields
        title = lead_data.get("title")
        url = lead_data.get("url") or lead_data.get("detail_url")
        country = lead_data.get("country")
        status = lead_data.get("status", "captured")
        
        # Parse timestamps ensuring UTC
        fetched_at = lead_data.get("fetched_at")
        clicked_at = lead_data.get("clicked_at")

        # Serialize raw data
        raw_json = json.dumps(lead_data)

        with conn:
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
                lead_id, slot_id, title, url, country, status, 
                fetched_at, clicked_at, raw_json
            ))
    except Exception as e:
        logger.error(f"Failed to save lead {lead_data.get('lead_id')}: {e}")
        raise
    finally:
        conn.close()

def get_slot_lead_ids(slot_id: str, limit: int = 5000) -> set:
    """
    Get a set of lead_ids for a specific slot to avoid duplicates.
    """
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT lead_id FROM leads WHERE slot_id = ? ORDER BY fetched_at DESC LIMIT ?", 
            (slot_id, limit)
        )
        return {row["lead_id"] for row in cursor}
    except Exception as e:
        logger.error(f"Failed to fetch existing keys: {e}")
        return set()
    finally:
        conn.close()


def mark_leads_as_verified(slot_id: str, verified_ids: set, verified_at: str = None):
    """
    Mark a set of leads as verified in the DB.
    """
    if not verified_ids:
        return

    verified_at = verified_at or datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        # Convert set to list for query
        ids_list = list(verified_ids)
        # Create placeholders based on size
        placeholders = ",".join("?" * len(ids_list))
        
        query = f"""
            UPDATE leads 
            SET status = 'verified', verified_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE slot_id = ? AND lead_id IN ({placeholders})
        """
        
        conn.execute(query, [verified_at, slot_id] + ids_list)
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to mark leads verified: {e}")
    finally:
        conn.close()

