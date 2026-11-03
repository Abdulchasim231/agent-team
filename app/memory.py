"""Conversation memory in SQLite: sessions with the chief, plus each turn's team activity."""

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    events TEXT,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Memory:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    def create_session(self, title: str) -> str:
        sid = uuid.uuid4().hex[:12]
        self.db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (sid, title[:80], _now()))
        self.db.commit()
        return sid

    def session_exists(self, sid: str) -> bool:
        return self.db.execute("SELECT 1 FROM sessions WHERE id = ?", (sid,)).fetchone() is not None

    def list_sessions(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def add_message(self, sid: str, role: str, content: str, events: list | None = None) -> None:
        self.db.execute(
            "INSERT INTO messages (session_id, role, content, events, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (sid, role, content, json.dumps(events) if events else None, _now()),
        )
        self.db.commit()

    def messages(self, sid: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT role, content, events, created_at FROM messages"
            " WHERE session_id = ? ORDER BY id", (sid,)
        ).fetchall()
        return [
            {**dict(r), "events": json.loads(r["events"]) if r["events"] else []} for r in rows
        ]

    def history(self, sid: str, limit: int = 20) -> list[dict]:
        """Recent turns in chat-completions format, for the chief's context."""
        return [{"role": m["role"], "content": m["content"]} for m in self.messages(sid)[-limit:]]

    def delete_session(self, sid: str) -> None:
        self.db.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        self.db.commit()
