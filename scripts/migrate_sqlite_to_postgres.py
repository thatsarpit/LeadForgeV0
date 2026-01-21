#!/usr/bin/env python3
"""
SQLite to Postgres Data Migration Script

Migrates all leads from SQLite (data/leadforge.db) to Postgres.
Run after Alembic migrations have created the leads table in Postgres.

Usage:
    DATABASE_URL=postgresql://... python3 scripts/migrate_sqlite_to_postgres.py
"""
import os
import sys
import json
import logging
from pathlib import Path

# Set environment to use Postgres
os.environ['USE_POSTGRES'] = 'true'

# Add project root to path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.db.database import save_lead_to_db
from sqlalchemy import create_engine, text
import sqlite3

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Paths
SQLITE_DB = BASE_DIR / "data" / "leadforge.db"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if not DATABASE_URL:
    logger.error("DATABASE_URL environment variable not set!")
    sys.exit(1)

if not SQLITE_DB.exists():
    logger.error(f"SQLite database not found at {SQLITE_DB}")
    sys.exit(1)

def migrate_leads():
    """Migrate all leads from SQLite to Postgres"""
    
    logger.info("🚀 Starting SQLite → Postgres Migration")
    logger.info(f"   Source: {SQLITE_DB}")
    logger.info(f"   Target: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'Postgres'}")
    
    # Connect to SQLite
    sqlite_conn = sqlite3.connect(SQLITE_DB)
    sqlite_conn.row_factory = sqlite3.Row
    
    # Get total count
    cursor = sqlite_conn.execute("SELECT COUNT(*) FROM leads")
    total = cursor.fetchone()[0]
    logger.info(f"   Total leads to migrate: {total}")
    
    if total == 0:
        logger.warning("No leads found in SQLite database")
        return
    
    # Connect to Postgres to check table exists
    pg_engine = create_engine(DATABASE_URL)
    with pg_engine.connect() as conn:
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'leads'
            )
        """))
        if not result.scalar():
            logger.error("Leads table does not exist in Postgres! Run Alembic migrations first.")
            sys.exit(1)
    
    # Migrate in batches
    batch_size = 100
    migrated = 0
    errors = 0
    
    cursor = sqlite_conn.execute("SELECT * FROM leads ORDER BY fetched_at")
    
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        
        for row in rows:
            try:
                # Convert SQLite row to dict
                lead_data = dict(row)
                
                # Parse JSON raw_data if needed
                if lead_data.get('raw_data'):
                    try:
                        lead_data['raw_data'] = json.loads(lead_data['raw_data'])
                    except:
                        pass
                
                # Prepare for Postgres
                slot_id = lead_data.get('slot_id')
                if not slot_id:
                    logger.warning(f"Skipping lead {lead_data.get('lead_id')} - no slot_id")
                    continue
                
                # Save to Postgres
                save_lead_to_db(lead_data, slot_id)
                migrated += 1
                
                if migrated % 100 == 0:
                    logger.info(f"   Progress: {migrated}/{total} ({migrated*100//total}%)")
                    
            except Exception as e:
                logger.error(f"Failed to migrate lead {row.get('lead_id')}: {e}")
                errors += 1
    
    sqlite_conn.close()
    
    logger.info(f"✅ Migration Complete!")
    logger.info(f"   Migrated: {migrated}")
    logger.info(f"   Errors: {errors}")
    logger.info(f"   Success Rate: {migrated*100//(migrated+errors) if (migrated+errors) > 0 else 100}%")
    
    if errors > 0:
        logger.warning(f"⚠️  {errors} leads failed to migrate. Check logs above.")

if __name__ == "__main__":
    try:
        migrate_leads()
    except KeyboardInterrupt:
        logger.warning("Migration interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)
