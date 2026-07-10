from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
import json
import sqlite3
import time
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
    """SQLite access layer for the operations console.

    Keep expensive filtering/pagination inside SQLite. The previous API path
    loaded every message into Python for dashboard, conversations, search, and
    detail views. That works for tiny databases but becomes progressively slow
    and also makes it easy for the frontend to think messages are missing.
    """

    PUBLIC_ROLES = ("user", "assistant")

    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _public_message_filter(include_internal: bool = False) -> str:
        if include_internal:
            return ""
        return """
          AND m.role IN ('user', 'assistant')
          AND NOT (
            m.role = 'assistant'
            AND (
              TRIM(COALESCE(m.content, '')) LIKE '📚 %'
              OR TRIM(COALESCE(m.content, '')) LIKE '📨 %'
              OR TRIM(COALESCE(m.content, '')) LIKE '🧠 %'
              OR TRIM(COALESCE(m.content, '')) LIKE 'skill_view:%'
              OR TRIM(COALESCE(m.content, '')) LIKE 'send_message:%'
              OR TRIM(COALESCE(m.content, '')) LIKE 'memory:%'
              OR TRIM(COALESCE(m.content, '')) LIKE '%\nskill_view:%'
              OR TRIM(COALESCE(m.content, '')) LIKE '%\nsend_message:%'
              OR TRIM(COALESCE(m.content, '')) LIKE '%\nmemory:%'
            )
          )
        """


    def fetch_admin_messages(self, last_message_id: int, admin_ids: Iterable[str]) -> list[sqlite3.Row]:
        admin_list = sorted(set(admin_ids))
        if not admin_list:
            return []
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
                "SELECT id, user_id, title, started_at, source FROM sessions"
            ).fetchall()
            return {row["id"]: dict(row) for row in rows}

    def fetch_session_messages(self) -> list[sqlite3.Row]:
        """Legacy full scan used by offline jobs.

        New web endpoints should prefer SQL-level methods below.
        """
        with self._connect() as conn:
            return conn.execute(
                "SELECT id AS message_id, session_id, role, content, timestamp FROM messages "
                "WHERE session_id IN (SELECT id FROM sessions) "
                "ORDER BY timestamp ASC"
            ).fetchall()

    def fetch_conversation_summaries(self, admin_ids: Iterable[str]) -> list[sqlite3.Row]:
        admin_list = sorted(set(str(x) for x in admin_ids if str(x)))
        admin_filter = ""
        params: list[Any] = []
        if admin_list:
            placeholders = ", ".join("?" for _ in admin_list)
            admin_filter = f"AND COALESCE(s.user_id, '') NOT IN ({placeholders})"
            params.extend(admin_list)
        query = f"""
        WITH public_messages AS (
          SELECT
            m.id AS message_id,
            m.session_id,
            m.role,
            COALESCE(m.content, '') AS content,
            m.timestamp,
            s.user_id,
            s.title,
            s.source
          FROM messages m
          JOIN sessions s ON s.id = m.session_id
          WHERE 1 = 1
            {self._public_message_filter(False)}
            {admin_filter}
        ), ranked AS (
          SELECT
            *,
            ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY timestamp DESC, message_id DESC) AS rn
          FROM public_messages
          WHERE COALESCE(user_id, '') <> ''
        )
        SELECT
          user_id,
          MAX(title) AS title,
          MAX(source) AS source,
          COUNT(*) AS message_count,
          SUM(CASE WHEN role = 'user' THEN 1 ELSE 0 END) AS user_message_count,
          SUM(CASE WHEN role = 'assistant' THEN 1 ELSE 0 END) AS assistant_message_count,
          MAX(timestamp) AS last_timestamp,
          MAX(CASE WHEN rn = 1 THEN content ELSE NULL END) AS last_message,
          GROUP_CONCAT(DISTINCT session_id) AS session_ids
        FROM ranked
        GROUP BY user_id
        ORDER BY last_timestamp DESC
        """
        with self._connect() as conn:
            return conn.execute(query, params).fetchall()

    def fetch_user_messages(
        self,
        user_id: str,
        limit: int,
        offset: int = 0,
        include_internal: bool = False,
    ) -> list[sqlite3.Row]:
        roles_clause = self._public_message_filter(include_internal)
        query = f"""
        SELECT
          m.id AS message_id,
          m.session_id,
          m.role,
          COALESCE(m.content, '') AS content,
          m.timestamp,
          m.platform_message_id
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE s.user_id = ?
          {roles_clause}
        ORDER BY m.timestamp DESC, m.id DESC
        LIMIT ? OFFSET ?
        """
        with self._connect() as conn:
            return conn.execute(query, (user_id, limit, offset)).fetchall()

    def count_user_messages(self, user_id: str, include_internal: bool = False) -> int:
        roles_clause = self._public_message_filter(include_internal)
        query = f"""
        SELECT COUNT(*)
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE s.user_id = ?
          {roles_clause}
        """
        with self._connect() as conn:
            return int(conn.execute(query, (user_id,)).fetchone()[0])

    def append_assistant_message(
        self,
        user_id: str,
        content: str,
        *,
        platform_message_id: str | None = None,
        timestamp: float | None = None,
    ) -> int:
        """Persist an operator reply in the active public conversation.

        The web UI reads exclusively from ``state.db``. Direct Bridge sends do
        not pass through the Hermes conversation loop, so they must be written
        here after WhatsApp confirms the send; otherwise the optimistic bubble
        disappears on refresh and the page looks unsynchronised.
        """
        clean_content = str(content or '').strip()
        if not clean_content:
            raise ValueError('message content is required')
        with self._connect() as conn:
            session = conn.execute(
                """
                SELECT id
                FROM sessions
                WHERE user_id = ? AND COALESCE(archived, 0) = 0
                ORDER BY COALESCE(ended_at, 0) ASC, started_at DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
            if session is None:
                raise ValueError('target_not_found')
            cursor = conn.execute(
                """
                INSERT INTO messages(
                    session_id, role, content, timestamp, platform_message_id,
                    observed, active
                ) VALUES (?, 'assistant', ?, ?, ?, 1, 1)
                """,
                (
                    str(session['id']),
                    clean_content,
                    float(timestamp if timestamp is not None else time.time()),
                    platform_message_id or None,
                ),
            )
            conn.execute(
                'UPDATE sessions SET message_count = COALESCE(message_count, 0) + 1 WHERE id = ?',
                (str(session['id']),),
            )
            conn.commit()
            row_id = cursor.lastrowid
            if row_id is None:
                raise RuntimeError('message insert did not return an id')
            return int(row_id)

    def fetch_user_messages_after(
        self,
        user_id: str,
        after_id: int,
        limit: int = 100,
        include_internal: bool = False,
    ) -> list[sqlite3.Row]:
        roles_clause = self._public_message_filter(include_internal)
        query = f"""
        SELECT
          m.id AS message_id,
          m.session_id,
          m.role,
          COALESCE(m.content, '') AS content,
          m.timestamp,
          m.platform_message_id
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE s.user_id = ?
          AND m.id > ?
          {roles_clause}
        ORDER BY m.id ASC
        LIMIT ?
        """
        with self._connect() as conn:
            return conn.execute(query, (user_id, after_id, limit)).fetchall()


    def count_user_hidden_messages(self, user_id: str, hidden_ids: Iterable[int]) -> int:
        ids = [int(x) for x in hidden_ids if str(x).isdigit() or isinstance(x, int)]
        if not ids:
            return 0
        placeholders = ", ".join("?" for _ in ids)
        query = f"""
        SELECT COUNT(*)
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE s.user_id = ?
          AND m.id IN ({placeholders})
          {self._public_message_filter(False)}
        """
        with self._connect() as conn:
            return int(conn.execute(query, (user_id, *ids)).fetchone()[0])

    def search_messages(self, query_text: str, limit: int, admin_ids: Iterable[str]) -> list[sqlite3.Row]:
        needle = f"%{query_text.lower()}%"
        admin_list = sorted(set(str(x) for x in admin_ids if str(x)))
        admin_filter = ""
        params: list[Any] = [needle]
        if admin_list:
            placeholders = ", ".join("?" for _ in admin_list)
            admin_filter = f"AND COALESCE(s.user_id, '') NOT IN ({placeholders})"
            params.extend(admin_list)
        params.append(limit)
        query = f"""
        SELECT
          m.id AS message_id,
          m.session_id,
          m.role,
          COALESCE(m.content, '') AS content,
          m.timestamp,
          s.user_id,
          s.title,
          s.source
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE 1 = 1
          {self._public_message_filter(False)}
          AND LOWER(COALESCE(m.content, '')) LIKE ?
          AND COALESCE(s.user_id, '') <> ''
          {admin_filter}
        ORDER BY m.timestamp DESC, m.id DESC
        LIMIT ?
        """
        with self._connect() as conn:
            return conn.execute(query, params).fetchall()
