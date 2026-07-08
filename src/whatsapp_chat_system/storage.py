from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
import json
import sqlite3
from typing import Any, Iterable


@dataclass(slots=True)
class MessageRow:
    id: int
    session_id: str
    role: str
    content: str
    timestamp: float
    user_id: str = ""
    title: str = ""
    source: str = ""


class EventLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, **kwargs: Any) -> None:
        entry = {"ts": datetime.now(UTC).isoformat(), "event": event, **kwargs}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


class StateDB:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def fetch_admin_messages(self, last_message_id: int, admin_ids: Iterable[str]) -> list[sqlite3.Row]:
        admin_list = sorted(set(admin_ids))
        placeholders = ", ".join("?" for _ in admin_list)
        query = f"""
        SELECT m.id, m.session_id, m.role, m.content, m.timestamp, s.user_id
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE m.id > ?
          AND s.source = 'whatsapp'
          AND s.user_id IN ({placeholders})
          AND m.role = 'user'
        ORDER BY m.id ASC
        """
        with self._connect() as conn:
            return conn.execute(query, (last_message_id, *admin_list)).fetchall()

    def fetch_all_messages(self, last_message_id: int = 0) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT id, session_id, role, content, timestamp FROM messages WHERE id > ? ORDER BY id ASC",
                (last_message_id,),
            ).fetchall()

    def fetch_sessions(self) -> dict[str, dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, user_id, title, started_at, source FROM sessions WHERE source = ?",
                ("whatsapp",),
            ).fetchall()
            return {row["id"]: dict(row) for row in rows}

    def fetch_session_messages(self) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT session_id, role, content, timestamp FROM messages "
                "WHERE session_id IN (SELECT id FROM sessions WHERE source = ?) "
                "ORDER BY timestamp ASC",
                ("whatsapp",),
            ).fetchall()
