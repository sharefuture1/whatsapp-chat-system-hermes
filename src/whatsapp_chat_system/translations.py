"""Per-user message translation cache.

On-disk layout:
  user-memory-md/{safe_name}__{user_id}.translations.json

Schema:
  {
    "version": 1,
    "items": {
        "<message_id>": {
            "source_lang": "Lao",
            "source_text": "...",
            "zh": "...",
            "updated_at": 123.45
        }
    }
  }
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def translations_path(memory_dir: Path, user_id: str) -> Path:
    return memory_dir / f".translations__{user_id}.json"


def load_translations(memory_dir: Path, user_id: str) -> dict[str, Any]:
    path = translations_path(memory_dir, user_id)
    if not path.exists():
        return {"version": 1, "items": {}}
    try:
        data = json.loads(path.read_text() or "{}")
    except Exception:
        return {"version": 1, "items": {}}
    if not isinstance(data, dict):
        return {"version": 1, "items": {}}
    data.setdefault("version", 1)
    data.setdefault("items", {})
    if not isinstance(data.get("items"), dict):
        data["items"] = {}
    return data


def save_translations(memory_dir: Path, user_id: str, payload: dict[str, Any]) -> None:
    memory_dir.mkdir(parents=True, exist_ok=True)
    path = translations_path(memory_dir, user_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    tmp.replace(path)


def get_translation(memory_dir: Path, user_id: str, message_id: int) -> dict[str, Any] | None:
    data = load_translations(memory_dir, user_id)
    return data.get("items", {}).get(str(message_id))


def put_translation(memory_dir: Path, user_id: str, message_id: int, payload: dict[str, Any]) -> None:
    with _LOCK:
        data = load_translations(memory_dir, user_id)
        items = data.setdefault("items", {})
        items[str(message_id)] = {**payload, "updated_at": time.time()}
        save_translations(memory_dir, user_id, data)


def bulk_put(memory_dir: Path, user_id: str, entries: dict[str, dict[str, Any]]) -> None:
    if not entries:
        return
    with _LOCK:
        data = load_translations(memory_dir, user_id)
        items = data.setdefault("items", {})
        now = time.time()
        for mid, payload in entries.items():
            items[str(mid)] = {**payload, "updated_at": now}
        save_translations(memory_dir, user_id, data)


def load_many(memory_dir: Path, user_id: str, message_ids: list[int]) -> dict[str, dict[str, Any]]:
    if not message_ids:
        return {}
    data = load_translations(memory_dir, user_id)
    items = data.get("items", {})
    return {str(mid): items.get(str(mid)) for mid in message_ids if str(mid) in items}
