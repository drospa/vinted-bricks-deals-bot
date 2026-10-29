"""Run state (last listing id seen, listings already reported, Telegram offset, last schedule slot).
Stored in DATA_DIR, which the workflow keeps on the `data` branch."""
import json
import os

from .config import STATE_FILE

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)
