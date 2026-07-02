"""
db.py - lightweight JSON-file "database" for tracking cinema session
seat availability over time.

Structure of sessions_db.json:
{
  "0011-46088": {
    "last_checked": "2026-07-02T14:00:00.123456",
    "seats_available": 119,
    "is_sold_out": false,
    "title": "Backrooms",
    "show_time": "2026-07-02T19:50:00.000Z",
    "history": [
      {"checked_at": "2026-07-02T13:00:00.123456", "seats_available": 122},
      {"checked_at": "2026-07-02T14:00:00.123456", "seats_available": 119}
    ]
  },
  ...
}
"""

import json
import os
from datetime import datetime

DB_PATH = "sessions_db.json"


def load_db(path: str = DB_PATH) -> dict:
    """Load the db file, creating an empty one if it doesn't exist yet."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_db(db: dict, path: str = DB_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def update_session(db: dict, filtered_session: dict, path: str = DB_PATH) -> dict:
    """
    Update the db with a freshly filtered session dict (output of filter_session()).
    Returns the change info: {"seats_before": int|None, "seats_after": int, "changed": bool}
    """
    session_id = filtered_session["session_id"]
    now = datetime.utcnow().isoformat()

    seats_now = filtered_session["seats_available"]
    entry = db.get(session_id)
    seats_before = entry["seats_available"] if entry else None

    if entry is None:
        entry = {
            "last_checked": now,
            "seats_available": seats_now,
            "is_sold_out": filtered_session["is_sold_out"],
            "title": filtered_session["film"]["title"],
            "show_time": filtered_session["show_time"],
            "history": [],
        }
    entry["last_checked"] = now
    entry["seats_available"] = seats_now
    entry["is_sold_out"] = filtered_session["is_sold_out"]
    entry["history"].append({"checked_at": now, "seats_available": seats_now})
    # keep history from growing forever
    entry["history"] = entry["history"][-100:]

    db[session_id] = entry
    save_db(db, path)

    return {
        "seats_before": seats_before,
        "seats_after": seats_now,
        "changed": seats_before is not None and seats_before != seats_now,
    }
