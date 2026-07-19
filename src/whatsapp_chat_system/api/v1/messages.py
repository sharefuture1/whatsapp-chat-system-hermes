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
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _upsert_db_translation(
    session: Any,
    message: Message,
    *,
    source_lang: str,
    target_lang: str,
    translated_text: str | None,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> MessageTranslation:
    source_hash = _source_text_hash(message.content or "")
    existing = session.scalar(
        select(MessageTranslation).where(
            MessageTranslation.message_id == message.id,
            MessageTranslation.target_lang == target_lang,
            MessageTranslation.source_text_hash == source_hash,
        )
    )
    row = existing or MessageTranslation(
        account_id=message.account_id,
        conversation_id=message.conversation_id,
        message_id=message.id,
        target_lang=target_lang,
        source_text_hash=source_hash,
    )
    row.source_text = message.content or ""
    row.source_lang = source_lang
    row.translated_text = translated_text
    row.status = status
    row.error_code = error_code
    row.error_message = error_message
    row.provider = "wendingai"
    row.context_window_size = 1
    row.completed_at = datetime.now(timezone.utc) if status == "completed" else None
    if existing is None:
        session.add(row)
    return row


class _RuntimePaths:
    def __init__(self, memory_dir: Any) -> None:
        self.memory_dir = memory_dir


class _RuntimeBackedConfig:
    """把 runtime 的实时设置适配给共享 Rewriter（PERF-003）。

    ai_settings/web_settings 走 property 读 runtime 当前值，保存设置后热生效。
    """

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self.paths = _RuntimePaths(runtime.paths.memory_dir)

    @property
    def ai_settings(self) -> Any:
        return self._runtime.ai_settings

    @property
    def web_settings(self) -> dict[str, Any]:
        return getattr(self._runtime, "web_settings", {}) or {}


def _get_translation_rewriter(request: Request) -> Rewriter:
    """app 级单例：复用 Provider 连接池，禁止每请求新建 Rewriter（PERF-003）。"""
    cached = getattr(request.app.state, "translation_rewriter", None)
    if cached is not None:
        return cached
    runtime = request.app.state.runtime
    worker = Rewriter(
        _RuntimeBackedConfig(runtime),
        lambda *args, **kwargs: None,
        runtime_manager=getattr(request.app.state, "ai_settings_manager", None),
    )
    request.app.state.translation_rewriter = worker
    return worker


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

        # 阶段一：短事务读消息与缓存命中；不在 session 打开期间调用 AI（PERF-006 同族约束）
        with session_factory() as session:
            message = session.get(Message, message_id)
            if message is None:
                raise HTTPException(status_code=404, detail="Message not found")
            source_hash = _source_text_hash(message.content or "")
            existing = session.scalar(
                select(MessageTranslation).where(
                    MessageTranslation.message_id == message.id,
                    MessageTranslation.target_lang == "zh-CN",
                    MessageTranslation.source_text_hash == source_hash,
                    MessageTranslation.status == "completed",
                )
            )
            if existing is not None:
                return {
                    "message_id": message_id,
                    "lang": existing.source_lang or lang,
                    "translated": existing.translated_text,
                    "translation_status": existing.status,
                    "cached": True,
                }
            if lang == "Chinese":
                _upsert_db_translation(
                    session,
                    message,
                    source_lang=lang,
                    target_lang="zh-CN",
                    translated_text=None,
                    status="completed",
                )
                session.commit()
                return {
                    "message_id": message_id,
                    "lang": lang,
                    "translated": None,
                    "translation_status": "completed",
                }

        # 阶段二：无 session 状态下调用 AI（可能长达数十秒）
        worker = _get_translation_rewriter(request)
        result = worker.translate_to_zh_result(text, lang)
        fallback_translation = (result.message or "").strip()
        has_usable_translation = bool(
            fallback_translation and fallback_translation != text.strip()
        )

        # 阶段三：新短事务写回翻译结果
        with session_factory() as session:
            message = session.get(Message, message_id)
            if message is None:
                raise HTTPException(status_code=404, detail="Message not found")
            if result.error and not has_usable_translation:
                _upsert_db_translation(
                    session,
                    message,
                    source_lang=lang,
                    target_lang="zh-CN",
                    translated_text=None,
                    status="failed",
                    error_code="translate_failed",
                    error_message=str(result.error),
                )
                session.commit()
                return {
                    "success": False,
                    "message_id": message_id,
                    "lang": lang,
                    "translated": None,
                    "translation_status": "failed",
                    "fallback_text": result.message or text,
                    "used_fallback": result.used_fallback,
                    "error": result.error,
                }
            _upsert_db_translation(
                session,
                message,
                source_lang=lang,
                target_lang="zh-CN",
                translated_text=fallback_translation or None,
                status="completed",
            )
            session.commit()
            return {
                "message_id": message_id,
                "lang": lang,
                "translated": fallback_translation or None,
                "translation_status": "completed",
                "cached": False,
                "used_fallback": result.used_fallback,
                "provider_warning": result.error if result.used_fallback else None,
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
