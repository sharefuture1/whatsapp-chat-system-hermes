"""Message-level v1 API: per-message translate."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from whatsapp_chat_system.rewriter import Rewriter


def _language_hint_for(text: str) -> str:
    if not text:
        return "Unknown"
    if re.search(r"[\u0E80-\u0EFF]", text):
        return "Lao"
    if re.search(r"[\u0E00-\u0E7F]", text):
        return "Thai"
    if re.search(r"[\u4E00-\u9FFF]", text):
        return "Chinese"
    if re.search(r"[A-Za-z]", text):
        return "Latin"
    return "Unknown"


class TranslateRequest(BaseModel):
    user_id: str = Field(default="", max_length=255)
    content: str = Field(default="", max_length=10000)


def create_messages_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1/messages", tags=["messages"])

    @router.post("/{message_id}/translate", summary="Translate a message")
    def translate_message(
        message_id: str,
        body: TranslateRequest,
        request: Request,
    ) -> dict[str, Any]:
        """
        Translate a message by its ID.
        Replaces the legacy POST /api/messages/{message_id}/translate endpoint.
        """
        user_id = body.user_id or "default"
        text = body.content

        lang = _language_hint_for(text)
        if lang == "Chinese":
            return {"message_id": message_id, "lang": lang, "translated": None}

        # Access runtime from app state (set in standalone_api.py)
        runtime = getattr(request.app.state, "runtime", None)
        if runtime is None:
            raise HTTPException(status_code=500, detail="Runtime not available")

        # Build a minimal config-like object for Rewriter
        class _DummyAppPaths:
            memory_dir: Any

            def __init__(self, memory_dir: Any) -> None:
                self.memory_dir = memory_dir

        class _DummyConfig:
            paths: _DummyAppPaths
            ai_settings: Any

            def __init__(self, memory_dir: Any, ai_settings: Any) -> None:
                self.paths = _DummyAppPaths(memory_dir)
                self.ai_settings = ai_settings

        config = _DummyConfig(runtime.paths.memory_dir, runtime.ai_settings)
        # Pass the standalone runtime manager so provider uses live DB credentials.
        worker = Rewriter(
            config,
            lambda *args, **kwargs: None,
            runtime_manager=getattr(request.app.state, "ai_settings_manager", None),
        )
        result = worker.translate_to_zh_result(text, lang)

        if result.message and result.message != text:
            _put_translation(
                runtime.paths.memory_dir,
                user_id,
                message_id,
                {
                    "source_lang": lang,
                    "source_text": text[:200],
                    "zh": result.message,
                },
            )

        payload: dict[str, Any] = {
            "message_id": message_id,
            "lang": lang,
            "translated": result.message or None,
        }
        if result.error:
            return {
                "success": False,
                **payload,
                "translated": None,
                "fallback_text": result.message or text,
                "used_fallback": result.used_fallback,
                "error": result.error,
            }
        return payload

    return router


def _put_translation(
    memory_dir: Any, user_id: str, message_id: str, entry: dict[str, Any]
) -> None:
    import json
    from pathlib import Path

    td = Path(memory_dir) / f"translations__{user_id}.json"
    try:
        data: dict[str, Any] = {}
        if td.exists():
            data = json.loads(td.read_text())
        data[str(message_id)] = entry
        td.write_text(json.dumps(data, ensure_ascii=False))
    except Exception:
        pass
