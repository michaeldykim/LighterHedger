"""Durable intent journal, stop latch and alert outbox."""
import fcntl
import json
import os
import sqlite3
from pathlib import Path


class State:
    def __init__(self, path, identity):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = open(str(path) + ".lock", "a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError("Another bot already uses this account state") from None
        self.db = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
        row = self.db.execute("SELECT body FROM state WHERE id=1").fetchone()
        self.data = json.loads(row[0]) if row else {
            "identity": identity, "watch": None, "stopped": False,
            "paused": None, "established": False, "outbox": [], "telegram_offset": 0,
        }
        if self.data["identity"] != identity:
            self.close()
            raise ValueError("Saved configuration differs. Use the original parameters; do not discard unresolved state.")
        self.save()

    def save(self):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO state VALUES (1, ?)", (json.dumps(self.data),))

    def event(self, text):
        self.data["outbox"].append(text)
        self.save()

    def close(self):
        self.db.close()
        self.lock.close()
