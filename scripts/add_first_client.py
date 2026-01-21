import sys
import os
from pathlib import Path

# Add root to python path to allow importing 'api'
sys.path.append(str(Path(__file__).parent.parent))

from api.db import SessionLocal
from api.models import User, UserSlot, Slot
from sqlalchemy import select, delete

def run():
    print("Connecting to DB...")
    db = SessionLocal()
    try:
        email = "bbcvh95@gmail.com"
        slot_id = "slot01"
        
        # 1. Ensure User
        print(f"Checking user {email}...")
        user = db.scalar(select(User).where(User.email == email))
        if not user:
            print(f"Creating new user: {email}")
            user = User(email=email, role="client", disabled=False)
            db.add(user)
            db.flush()
        else:
            print(f"User already exists: {user.id}")
            
        # 2. Ensure Slot in DB
        if not db.get(Slot, slot_id):
            print(f"Registering slot {slot_id} in DB")
            db.add(Slot(id=slot_id))
        
        # 3. Create Slot Directory
        slot_dir = Path("slots") / slot_id
        if not slot_dir.exists():
            print(f"Creating directory: {slot_dir}")
            slot_dir.mkdir(parents=True, exist_ok=True)
        
        # 4. Assign Slot to User
        print(f"Assigning {slot_id} to {email}...")
        # Remove old assignments
        db.execute(delete(UserSlot).where(UserSlot.user_id == user.id))
        # Add new assignment
        db.add(UserSlot(user_id=user.id, slot_id=slot_id))
        
        db.commit()
        print("✅ SUCCESS: Client added and slot assigned.")
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    run()
