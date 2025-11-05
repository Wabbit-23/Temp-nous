import os
import json

THEME_FILE = "data/selected_theme.json"

def save_theme(theme_key):
    os.makedirs("data", exist_ok=True)
    with open(THEME_FILE, "w") as f:
        json.dump({"theme": theme_key}, f)

def load_theme():
    try:
        with open(THEME_FILE, "r") as f:
            return json.load(f)["theme"]
    except Exception:
        return None
