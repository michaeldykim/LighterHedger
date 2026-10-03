"""Durable intent journal, stop latch and alert outbox."""
import fcntl
import json
import os
import sqlite3
from pathlib import Path


class State:
    def __init__(self, path, identity, *, allow_strike_change=False, discord_enabled=False):
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
            "paused": None, "established": False, "outbox": [],
        }
        saved = self.data["identity"]
        pending = self.data.get("strike_change")
        changed = {key for key in saved.keys() | identity.keys() if saved.get(key) != identity.get(key)}
        if pending and (not allow_strike_change or pending["identity"] != identity):
            self.close()
            raise ValueError("A strike change is pending. Restart with its requested strike and --live --resume")
        if changed and (changed != {"strike"} or not allow_strike_change):
            self.close()
            raise ValueError("Saved configuration differs. Only strike changes are supported with --live --resume; "
                             "keep all other parameters unchanged and preserve saved state.")
        if changed and not pending:
            self.data["strike_change"] = {"identity": dict(identity), "cancel_requested": False}
        self.discord_enabled = discord_enabled
        # Legacy alerts remain Telegram-only; never copy the existing outbox.
        self.data.setdefault("discord_outbox", [])
        self.data.pop("telegram_offset", None)
        self.save()

    def save(self):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO state VALUES (1, ?)", (json.dumps(self.data),))

    def event(self, text):
        self.data["outbox"].append(text)
        if self.discord_enabled:
            text = text[:4000]  # Match Telegram's existing message cap.
            self.data["discord_outbox"].extend(
                text[start:start + 2000] for start in range(0, len(text), 2000))
        self.save()

    def close(self):
        self.db.close()
        self.lock.close()
