"""
Unified database module supporting both SQLite (legacy) and Postgres (production).

Strategy:
- SQLite: Used for local development and as fallback
- Postgres: Production deployment via SQLAlchemy ORM
- Automatic fallback: If Postgres unavailable, use SQLite
"""
import os
import json
import logging
from typing import Optional, Set
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("leadforge.db")

# Environment detection
USE_POSTGRES = os.getenv("USE_POSTGRES", "false").lower() in ("true", "1", "yes")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if USE_POSTGRES and DATABASE_URL:
    # Postgres mode (production)
    from sqlalchemy import create_engine, select, update
    from sqlalchemy.orm import sessionmaker
    from api.models import Lead
    
    engine = create_engine(
        DATABASE_URL, 
        pool_pre_ping=True,      # Test connections before using
        pool_size=10,             # Base pool size
        max_overflow=20,          # Max additional connections
        pool_timeout=30,          # Fail fast if pool exhausted (30s)
        pool_recycle=3600,        # Recycle connections every hour to prevent stale connections
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    
    logger.info(f"Using Postgres for leads database")
    
    def get_connection():
        """Get Postgres session (SQLAlchemy)"""
        return SessionLocal()
    
    def init_db():
        """Initialize Postgres schema via Alembic"""
        # Alembic handles this in production
        logger.info("Postgres schema managed by Alembic migrations")
    
    def save_lead_to_db(lead_data: dict, slot_id: str):
        """Save lead to Postgres"""
        session = SessionLocal()
        try:
            lead_id = lead_data.get("lead_id") or lead_data.get("id")
            if not lead_id:
                logger.error("Cannot save lead without ID")
                return
            
            # Check if exists
            existing = session.query(Lead).filter(Lead.lead_id == lead_id).first()
            
            if existing:
                # Update
                existing.title = lead_data.get("title")
                existing.url = lead_data.get("url") or lead_data.get("detail_url")
                existing.country = lead_data.get("country")
                existing.status = lead_data.get("status", "captured")
                existing.clicked_at = lead_data.get("clicked_at")
                existing.verified_at = lead_data.get("verified_at")
                existing.raw_data = lead_data
            else:
                # Insert
                new_lead = Lead(
                    lead_id=lead_id,
                    slot_id=slot_id,
                    title=lead_data.get("title"),
                    url=lead_data.get("url") or lead_data.get("detail_url"),
                    country=lead_data.get("country"),
                    status=lead_data.get("status", "captured"),
                    fetched_at=lead_data.get("fetched_at"),
                    clicked_at=lead_data.get("clicked_at"),
                    verified_at=lead_data.get("verified_at"),
                    raw_data=lead_data
                )
                session.add(new_lead)
            
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save lead {lead_data.get('lead_id')}: {e}")
            raise
        finally:
            session.close()
    
    def get_slot_lead_ids(slot_id: str, limit: int = 5000) -> Set[str]:
        """Get existing lead IDs for deduplication"""
        session = SessionLocal()
        try:
            stmt = select(Lead.lead_id).where(Lead.slot_id == slot_id).order_by(Lead.fetched_at.desc()).limit(limit)
            results = session.execute(stmt).scalars().all()
            return set(results)
        except Exception as e:
            logger.error(f"Failed to fetch existing keys: {e}")
            return set()
        finally:
            session.close()
    
    def mark_leads_as_verified(slot_id: str, verified_ids: Set[str], verified_at: Optional[str] = None):
        """Bulk update verified status"""
        if not verified_ids:
            return
        
        verified_at_dt = verified_at or datetime.now(timezone.utc).isoformat()
        session = SessionLocal()
        try:
            stmt = (
                update(Lead)
                .where(Lead.slot_id == slot_id, Lead.lead_id.in_(list(verified_ids)))
                .values(status="verified", verified_at=verified_at_dt)
            )
            session.execute(stmt)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to mark leads verified: {e}")
        finally:
            session.close()

else:
    # SQLite mode (development/fallback)
    import sqlite3
    
    BASE_DIR = Path(os.environ.get("BASE_DIR_ENV") or Path(__file__).resolve().parent.parent.parent)
    DATA_DIR = BASE_DIR / "data"
    DB_PATH = DATA_DIR / "leadforge.db"
    
    logger.info(f"Using SQLite for leads database at {DB_PATH}")
    
    def get_db_path() -> Path:
        if not DATA_DIR.exists():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
        return DB_PATH
    
    def get_connection():
        """Get SQLite connection"""
        db_path = get_db_path()
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn
    
    def init_db():
        """Initialize SQLite schema"""
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
                    
                    CREATE INDEX IF NOT EXISTS idx_leads_slot_fetched 
                    ON leads(slot_id, fetched_at DESC);
                    
                    CREATE INDEX IF NOT EXISTS idx_leads_status 
                    ON leads(status);
                """)
            logger.info(f"SQLite database initialized at {DB_PATH}")
        finally:
            conn.close()
    
    def save_lead_to_db(lead_data: dict, slot_id: str):
        """Save lead to SQLite"""
        conn = get_connection()
        try:
            lead_id = lead_data.get("lead_id") or lead_data.get("id")
            if not lead_id:
                logger.error("Cannot save lead without ID")
                return

            title = lead_data.get("title")
            url = lead_data.get("url") or lead_data.get("detail_url")
            country = lead_data.get("country")
            status = lead_data.get("status", "captured")
            fetched_at = lead_data.get("fetched_at")
            clicked_at = lead_data.get("clicked_at")
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
    
    def get_slot_lead_ids(slot_id: str, limit: int = 5000) -> Set[str]:
        """Get existing lead IDs"""
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
    
    def mark_leads_as_verified(slot_id: str, verified_ids: Set[str], verified_at: Optional[str] = None):
        """Bulk update verified status"""
        if not verified_ids:
            return

        verified_at = verified_at or datetime.now(timezone.utc).isoformat()
        conn = get_connection()
        try:
            ids_list = list(verified_ids)
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
