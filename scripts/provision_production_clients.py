import sys
import os
import uuid
import json
import logging
from pathlib import Path
from datetime import datetime

# Setup paths
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from sqlalchemy import select
from api.db import SessionLocal
from api.models import User, UserSlot, UserEmail, Slot

# Clients to provision
CLIENTS = [
    {
        "name": "Voyd Media",
        "email": "voydmediamarketing@gmail.com", # Corrected from gmai.com
        "slot_id": "slot01",
        "keywords": ["marketing", "advertising"]
    },
    {
        "name": "Gratitude Enterprise",
        "email": "gratitude.entp@gmail.com",
        "slot_id": "slot02",
        "keywords": ["enterprise", "services"]
    },
    {
        "name": "Trinity Medex",
        "email": "trinity.medex@gmail.com",
        "slot_id": "slot03",
        "keywords": ["medex", "medical"]
    }
]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Provision")

def provision():
    db = SessionLocal()
    try:
        for client in CLIENTS:
            email = client["email"]
            slot_id = client["slot_id"]
            name = client["name"]
            
            logger.info(f"Processing {name} ({email})...")

            # 1. Create/Get User
            user = db.scalar(select(User).where(User.email == email))
            if not user:
                logger.info(f"Creating user {email}")
                user = User(
                    id=uuid.uuid4(),
                    email=email,
                    role="client",
                    disabled=False,
                    onboarding_complete=True,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(user)
                db.commit()
            else:
                logger.info(f"User {email} exists.")

            # 2a. Ensure Slot Exists
            slot = db.scalar(select(Slot).where(Slot.id == slot_id))
            if not slot:
                logger.info(f"Creating slot {slot_id}")
                slot = Slot(id=slot_id, label=name, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
                db.add(slot)
                db.commit()

            # 2b. Grant Slot Permission
            user_slot = db.scalar(select(UserSlot).where(UserSlot.user_id == user.id, UserSlot.slot_id == slot_id))
            if not user_slot:
                logger.info(f"Granting slot {slot_id} to {email}")
                user_slot = UserSlot(
                    user_id=user.id,
                    slot_id=slot_id,
                    created_at=datetime.utcnow()
                )
                db.add(user_slot)
                db.commit()

            # 3. Create Slot Directory
            slot_dir = BASE_DIR / "slots" / slot_id
            slot_dir.mkdir(parents=True, exist_ok=True)
            
            # 4. Create slot_state.json if missing
            state_path = slot_dir / "slot_state.json"
            if not state_path.exists():
                logger.info(f"Creating default state for {slot_id}")
                state = {
                    "slot_id": slot_id,
                    "status": "STOPPED",
                    "mode": "ACTIVE",
                    "worker_type": "indiamart_worker",
                    "config": {
                        "keywords": client["keywords"],
                        "min_budget": 0,
                        "location_filter": "Pan India"
                    },
                    "last_updated": datetime.utcnow().isoformat()
                }
                state_path.write_text(json.dumps(state, indent=2))
            
            # 5. Create config.json (legacy support)
            config_path = slot_dir / "config.json"
            if not config_path.exists():
                config_path.write_text(json.dumps({
                    "slot_id": slot_id,
                    "refresh_min": 5,
                    "refresh_max": 20
                }, indent=2))
        
        logger.info("✅ All clients provisioned successfully!")

    except Exception as e:
        logger.error(f"Failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    provision()
