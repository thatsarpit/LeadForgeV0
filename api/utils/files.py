import json
import os

def read_json(path, default=None):
    if not os.path.exists(path):
        return default or {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default or {}