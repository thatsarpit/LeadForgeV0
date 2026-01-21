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

# Load clients from external configuration
def load_clients():
    """Load client configuration from external file or environment.
    
    Checks in order:
    1. Environment variable CLIENTS_CONFIG_PATH
    2. clients.json in current directory
    3. Returns empty list if not found
    """
    config_path = os.getenv("CLIENTS_CONFIG_PATH", "clients.json")
    
    if not os.path.exists(config_path):
        logger.warning(f"Client config not found at {config_path}. Using empty list.")
        logger.info("Create clients.json or set CLIENTS_CONFIG_PATH environment variable.")
        return []
    
    try:
        with open(config_path, 'r') as f:
            clients = json.load(f)
            logger.info(f"Loaded {len(clients)} clients from {config_path}")
            return clients
    except Exception as e:
        logger.error(f"Failed to load clients from {config_path}: {e}")
        return []

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Provision")

def provision():
    """Provision clients with atomic transactions per client."""
    clients = load_clients()
    
    if not clients:
        logger.warning("No clients to provision. Exiting.")
        return
    
    for client in clients:
        email = client["email"]
        slot_id = client["slot_id"]
        name = client["name"]
        
        logger.info(f"Processing {name} ({email})...")
        
        # Use single transaction for all DB operations per client
        db = SessionLocal()
        try:
            with db.begin():
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
                    db.flush()  # Get user.id without committing
                else:
                    logger.info(f"User {email} exists.")

                # 2. Grant Slot Permission
                user_slot = db.scalar(select(UserSlot).where(
                    UserSlot.user_id == user.id, 
                    UserSlot.slot_id == slot_id
                ))
                if not user_slot:
                    logger.info(f"Granting slot {slot_id} to {email}")
                    user_slot = UserSlot(
                        id=uuid.uuid4(),
                        user_id=user.id,
                        slot_id=slot_id,
                        role="owner",
                        created_at=datetime.utcnow()
                    )
                    db.add(user_slot)
                
                # Transaction commits here automatically
            
            # 3. Create Slot Directory (outside transaction)
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
                        "keywords": client.get("keywords", []),
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
            
            logger.info(f"✅ Successfully provisioned {name}")
            
        except Exception as e:
            logger.error(f"Failed to provision {name}: {e}")
            import traceback
            traceback.print_exc()
        finally:
            db.close()
    
    logger.info("✅ All clients provisioned successfully!")

if __name__ == "__main__":
    provision()
