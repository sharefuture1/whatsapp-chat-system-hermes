"""Message-level v1 API: per-message translate."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from whatsapp_chat_system.db.models import Message, MessageTranslation
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


def _source_text_hash(text: str) -> str:
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


def _upsert_db_translation(session: Any, message: Message, *, source_lang: str, target_lang: str, translated_text: str | None, status: str, error_code: str | None = None, error_message: str | None = None) -> MessageTranslation:
    source_hash = _source_text_hash(message.content or '')
    existing = session.scalar(select(MessageTranslation).where(
        MessageTranslation.message_id == message.id,
        MessageTranslation.target_lang == target_lang,
        MessageTranslation.source_text_hash == source_hash,
    ))
    row = existing or MessageTranslation(
        account_id=message.account_id,
        conversation_id=message.conversation_id,
        message_id=message.id,
        target_lang=target_lang,
        source_text_hash=source_hash,
    )
    row.source_text = message.content or ''
    row.source_lang = source_lang
    row.translated_text = translated_text
    row.status = status
    row.error_code = error_code
    row.error_message = error_message
    row.provider = 'wendingai'
    row.context_window_size = 1
    row.completed_at = datetime.now(timezone.utc) if status == 'completed' else None
    if existing is None:
        session.add(row)
    return row


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
        Current phase writes database translation truth even while the provider path is still synchronous.
        """
        text = body.content
        lang = _language_hint_for(text)
        runtime = getattr(request.app.state, "runtime", None)
        session_factory = getattr(request.app.state, "session_factory", None)
        if runtime is None or session_factory is None:
            raise HTTPException(status_code=500, detail="Runtime not available")

        with session_factory() as session:
            message = session.get(Message, message_id)
            if message is None:
                raise HTTPException(status_code=404, detail="Message not found")
            source_hash = _source_text_hash(message.content or '')
            existing = session.scalar(select(MessageTranslation).where(
                MessageTranslation.message_id == message.id,
                MessageTranslation.target_lang == 'zh-CN',
                MessageTranslation.source_text_hash == source_hash,
                MessageTranslation.status == 'completed',
            ))
            if existing is not None:
                return {
                    "message_id": message_id,
                    "lang": existing.source_lang or lang,
                    "translated": existing.translated_text,
                    "translation_status": existing.status,
                    "cached": True,
                }
            if lang == "Chinese":
                _upsert_db_translation(session, message, source_lang=lang, target_lang='zh-CN', translated_text=None, status='completed')
                session.commit()
                return {"message_id": message_id, "lang": lang, "translated": None, "translation_status": 'completed'}

            class _DummyAppPaths:
                memory_dir: Any
                def __init__(self, memory_dir: Any) -> None:
                    self.memory_dir = memory_dir

            class _DummyConfig:
                paths: _DummyAppPaths
                ai_settings: Any
                web_settings: dict[str, Any]
                def __init__(self, memory_dir: Any, ai_settings: Any, web_settings: dict[str, Any]) -> None:
                    self.paths = _DummyAppPaths(memory_dir)
                    self.ai_settings = ai_settings
                    self.web_settings = web_settings

            config = _DummyConfig(runtime.paths.memory_dir, runtime.ai_settings, runtime.web_settings)
            worker = Rewriter(
                config,
                lambda *args, **kwargs: None,
                runtime_manager=getattr(request.app.state, "ai_settings_manager", None),
            )
            result = worker.translate_to_zh_result(text, lang)
            if result.error:
                _upsert_db_translation(session, message, source_lang=lang, target_lang='zh-CN', translated_text=None, status='failed', error_code='translate_failed', error_message=result.error)
                session.commit()
                return {
                    "success": False,
                    "message_id": message_id,
                    "lang": lang,
                    "translated": None,
                    "translation_status": 'failed',
                    "fallback_text": result.message or text,
                    "used_fallback": result.used_fallback,
                    "error": result.error,
                }
            _upsert_db_translation(session, message, source_lang=lang, target_lang='zh-CN', translated_text=result.message or None, status='completed')
            session.commit()
            return {
                "message_id": message_id,
                "lang": lang,
                "translated": result.message or None,
                "translation_status": 'completed',
                "cached": False,
            }


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
