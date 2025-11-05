import os
import json

DATA_DIR = os.path.join("data")
RECENT_PATH = os.path.join(DATA_DIR, "recent_files.json")
STARRED_PATH = os.path.join(DATA_DIR, "starred_files.json")
MAX_RECENT = 10

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# Recent files
def add_recent(path):
    files = load_json(RECENT_PATH)
    if path in files:
        files.remove(path)
    files.insert(0, path)
    files = files[:MAX_RECENT]
    save_json(RECENT_PATH, files)

def get_recent():
    return load_json(RECENT_PATH)

# Starred files
def add_starred(path):
    files = load_json(STARRED_PATH)
    if path not in files:
        files.append(path)
        save_json(STARRED_PATH, files)

def remove_starred(path):
    files = load_json(STARRED_PATH)
    if path in files:
        files.remove(path)
        save_json(STARRED_PATH, files)

def is_starred(path):
    return path in load_json(STARRED_PATH)

def get_starred():
    return load_json(STARRED_PATH)
