import os
import yaml
import copy
from pathlib import Path

BASE_DIR = Path("/Users/thatsarpit/Documents/LeadForgeV0")
SLOTS_DIR = BASE_DIR / "slots"
SOURCE_SLOT = "slot01"
TARGET_SLOTS = [f"slot{i:02d}" for i in range(2, 11)]

def load_yaml(path):
    if not path.exists():
        return None
    with open(path, "r") as f:
        return yaml.safe_load(f)

def save_yaml(path, data):
    with open(path, "w") as f:
        yaml.dump(data, f, sort_keys=False, default_flow_style=False)

def main():
    print(f"🔄 Standardizing Slot Configs...")
    print(f"📂 Base Dir: {BASE_DIR}")
    
    # 1. Load Source Config
    source_path = SLOTS_DIR / SOURCE_SLOT / "slot_config.yml"
    if not source_path.exists():
        print(f"❌ Source config not found: {source_path}")
        return
    
    source_config = load_yaml(source_path)
    if not source_config:
        print(f"❌ Failed to load source config")
        return
        
    print(f"✅ Loaded template from {SOURCE_SLOT}")
    print(f"   - Search Terms: {len(source_config.get('search_terms', []))}")
    print(f"   - Countries: {len(source_config.get('country', []))}")
    print(f"   - Max Lead Age: {source_config.get('max_lead_age_seconds')}")

    # 2. Iterate Targets
    for slot_name in TARGET_SLOTS:
        target_dir = SLOTS_DIR / slot_name
        if not target_dir.exists():
            print(f"⚠️  Skipping {slot_name}: Directory not found")
            continue
            
        target_path = target_dir / "slot_config.yml"
        
        # Read existing to get unique ID
        existing_config = load_yaml(target_path)
        
        # Determine strict ID preservation
        # Default to slot name if missing
        current_waha_session = slot_name 
        
        if existing_config and "whatsapp_waha_session" in existing_config:
            # If the existing session is 'slot01' (the template default), 
            # we should OVERWRITE it with the actual slot name to ensure uniqueness.
            # Only keep it if it's something custom (e.g. 'custom_session_id').
            old_session = existing_config["whatsapp_waha_session"]
            if old_session == "slot01":
                current_waha_session = slot_name
            else:
                current_waha_session = old_session
        else:
             # If missing, default to slot name
             current_waha_session = slot_name
            
        # Create new config from template
        new_config = copy.deepcopy(source_config)
        
        # Restore unique ID
        new_config["whatsapp_waha_session"] = current_waha_session
        
        # Write
        save_yaml(target_path, new_config)
        print(f"✅ Updated {slot_name} (waha_session: {current_waha_session})")

    print("\n✨ Standardization Complete!")

if __name__ == "__main__":
    main()
