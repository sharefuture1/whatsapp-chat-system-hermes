"""Origins cache with TTL and mtime-based invalidation.

Replaces the inline origin-building logic that used to live in
`web_api.py`, `forwarder.py`, and `memory_refresh.py`.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class OriginsCache:
    """In-memory cache for `sessions/sessions.json` → `session_id → origin`.

    Entries are invalidated by TTL or by file mtime change.
    Safe for single-process Python app. The CLI / FastAPI worker count is 1
    by default, so a simple module-level cache is enough.
    """

    def __init__(self, ttl_seconds: int = 30) -> None:
        self.ttl = ttl_seconds
        self._cache: dict[str, Any] | None = None
        self._mtime: float | None = None
        self._loaded_at: float = 0.0

    def load(self, sessions_json: Path) -> dict[str, dict[str, Any]]:
        path = Path(sessions_json)
        mtime = path.stat().st_mtime if path.exists() else None
        now = time.time()
        cache_valid = (
            self._cache is not None
            and self._mtime == mtime
            and (now - self._loaded_at) < self.ttl
        )
        if cache_valid and self._cache is not None:
            return self._cache
        data: dict[str, dict[str, Any]] = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text() or '{}')
            except Exception:
                raw = {}
            for _key, rec in raw.items():
                sid = rec.get('session_id') if isinstance(rec, dict) else None
                if sid:
                    data[sid] = (rec.get('origin') or {}) if isinstance(rec, dict) else {}
        self._cache = data
        self._mtime = mtime
        self._loaded_at = now
        return data

    def invalidate(self) -> None:
        self._cache = None
        self._mtime = None
        self._loaded_at = 0.0
