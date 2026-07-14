from __future__ import annotations

import re
from collections.abc import Callable, Generator
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from whatsapp_chat_system.db.models import (
    Contact,
    ContactAIOverride,
    Conversation,
    Message,
    WhatsAppAccount,
)
from whatsapp_chat_system.outbox import enqueue_outbox_message


PLATFORM = "whatsapp"


def _display_name(*values: Any) -> str | None:
    """Return a human name, never a raw WhatsApp JID/LID."""
    for value in values:
        text = str(value or "").strip()
        if not text or "@" in text or text.startswith(("lid:", "jid:")):
            continue
        return text
    return None


def _fallback_contact_name(remote_jid: str) -> str:
    return "WhatsApp 联系人" if remote_jid.endswith("@lid") else remote_jid


class ConversationReplyRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    idempotency_key: str | None = Field(default=None, max_length=255)
    preview_only: bool = False


class ConversationStateUpdate(BaseModel):
    pinned: bool | None = None
    muted: bool | None = None
    archived: bool | None = None


class TranslateRequest(BaseModel):
    user_id: str = Field(default="", max_length=255)
    content: str = Field(default="", max_length=10000)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _timestamp(value: datetime | None) -> float:
    return value.timestamp() if value else 0.0


def _account_payload(account: WhatsAppAccount) -> dict[str, Any]:
    return {
        "id": account.id,
        "name": account.name,
        "platform": PLATFORM,
        "status": account.status,
        "enabled": account.enabled,
        "is_primary": account.is_primary,
        "phone_number": account.phone_number,
    }


def create_conversations_router(
    session_factory: Callable[[], Session], bridge: Any | None = None
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["conversations"])

    def get_session() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def available_accounts(
        session: Session, platform: str, account_id: str
    ) -> list[dict[str, Any]]:
        if platform not in {"all", PLATFORM}:
            return []
        statement = select(WhatsAppAccount).order_by(
            WhatsAppAccount.is_primary.desc(), WhatsAppAccount.created_at.asc()
        )
        if account_id != "all":
            statement = statement.where(WhatsAppAccount.id == account_id)
        return [
            _account_payload(account) for account in session.scalars(statement).all()
        ]

    @router.get("/conversations")
    def list_conversations(
        platform: str = Query(default="all"),
        account_id: str = Query(default="all"),
        limit: int = Query(default=50, ge=1, le=200),
        query: str = Query(default=""),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        if platform not in {"all", PLATFORM}:
            return {
                "items": [],
                "total": 0,
                "has_more": False,
                "platform": platform,
                "account_id": account_id,
                "available_platforms": [PLATFORM],
                "available_accounts": [],
            }
        statement = (
            select(Conversation, Contact, WhatsAppAccount, ContactAIOverride)
            .join(WhatsAppAccount, WhatsAppAccount.id == Conversation.account_id)
            .outerjoin(Contact, Contact.id == Conversation.contact_id)
            .outerjoin(
                ContactAIOverride,
                and_(
                    ContactAIOverride.account_id == Conversation.account_id,
                    ContactAIOverride.contact_id == Conversation.contact_id,
                ),
            )
            .where(Conversation.deleted_at.is_(None), Conversation.archived.is_(False))
        )
        count_statement = select(func.count(Conversation.id)).where(
            Conversation.deleted_at.is_(None), Conversation.archived.is_(False)
        )
        if account_id != "all":
            statement = statement.where(Conversation.account_id == account_id)
            count_statement = count_statement.where(
                Conversation.account_id == account_id
            )
        cleaned_query = query.strip()
        if cleaned_query:
            pattern = f"%{cleaned_query}%"
            search_clause = or_(
                Conversation.remote_jid.ilike(pattern),
                Conversation.title.ilike(pattern),
                Contact.display_name.ilike(pattern),
                Contact.remark.ilike(pattern),
                WhatsAppAccount.name.ilike(pattern),
            )
            statement = statement.where(search_clause)
        rows = session.execute(
            statement.order_by(
                Conversation.pinned.desc(),
                Conversation.last_message_at.desc(),
                Conversation.id.desc(),
            ).limit(limit)
        ).all()
        items = [
            {
                "conversation_id": conversation.id,
                "account_id": conversation.account_id,
                "account_name": account.name,
                "account_label": account.name,
                "user_id": conversation.remote_jid,
                "user_name": _display_name(
                    contact.remark if contact else None,
                    contact.display_name if contact else None,
                    conversation.title,
                ) or _fallback_contact_name(conversation.remote_jid),
                "contact_id": conversation.contact_id,
                "contact_profile": {
                    "remark": contact.remark if contact else None,
                    "notes": contact.notes if contact else None,
                    "tags": (contact.tags or []) if contact else [],
                    "language": contact.language if contact else None,
                },
                "user_override": {
                    "ai_model": override.model if override else None,
                    "custom_system_prompt": override.system_prompt
                    if override
                    else None,
                    "reply_style": override.reply_style if override else None,
                    "auto_reply_enabled": override.auto_reply_enabled
                    if override
                    else None,
                },
                "platform": PLATFORM,
                "last_message": conversation.last_message_preview or "",
                "last_timestamp": _timestamp(conversation.last_message_at),
                "last_message_at": _iso(conversation.last_message_at),
                "unread_count": conversation.unread_count,
                "pinned": conversation.pinned,
                "muted": conversation.muted,
            }
            for conversation, contact, account, override in rows
        ]
        total = session.scalar(count_statement) or 0
        return {
            "items": items,
            "total": total,
            "has_more": total > len(items),
            "platform": platform,
            "account_id": account_id,
            "available_platforms": [PLATFORM],
            "available_accounts": available_accounts(session, platform, account_id),
        }

    @router.get("/contacts")
    def list_contacts(
        platform: str = Query(default="all"),
        account_id: str = Query(default="all"),
        limit: int = Query(default=200, ge=1, le=500),
        query: str = Query(default=""),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        if platform not in {"all", PLATFORM}:
            return {
                "items": [],
                "total": 0,
                "platform": platform,
                "account_id": account_id,
                "available_platforms": [PLATFORM],
                "available_accounts": [],
            }
        statement = (
            select(Contact, WhatsAppAccount, Conversation, ContactAIOverride)
            .join(WhatsAppAccount, WhatsAppAccount.id == Contact.account_id)
            .outerjoin(
                Conversation,
                (Conversation.account_id == Contact.account_id)
                & (Conversation.remote_jid == Contact.remote_jid)
                & Conversation.deleted_at.is_(None),
            )
            .outerjoin(
                ContactAIOverride,
                and_(
                    ContactAIOverride.account_id == Contact.account_id,
                    ContactAIOverride.contact_id == Contact.id,
                ),
            )
        )
        if account_id != "all":
            statement = statement.where(Contact.account_id == account_id)
        cleaned_query = query.strip()
        if cleaned_query:
            pattern = f"%{cleaned_query}%"
            statement = statement.where(
                or_(
                    Contact.remote_jid.ilike(pattern),
                    Contact.display_name.ilike(pattern),
                    Contact.remark.ilike(pattern),
                    Contact.phone_number.ilike(pattern),
                    WhatsAppAccount.name.ilike(pattern),
                )
            )
        rows = session.execute(
            statement.order_by(
                func.coalesce(
                    Contact.remark, Contact.display_name, Contact.remote_jid
                ).asc(),
                Contact.id.asc(),
            ).limit(limit)
        ).all()
        items = [
            {
                "contact_id": contact.id,
                "conversation_id": conversation.id if conversation else None,
                "account_id": contact.account_id,
                "account_name": account.name,
                "platform": PLATFORM,
                "remote_jid": contact.remote_jid,
                "user_id": contact.remote_jid,
                "display_name": contact.display_name,
                "remark": contact.remark,
                "user_name": _display_name(
                    contact.remark,
                    contact.display_name,
                    conversation.title if conversation else None,
                ) or _fallback_contact_name(contact.remote_jid),
                "phone_number": contact.phone_number,
                "avatar_url": contact.avatar_url,
                "tags": contact.tags or [],
                "language": contact.language,
                "notes": contact.notes,
            }
            for contact, account, conversation, override in rows
        ]
        return {
            "items": items,
            "total": len(items),
            "platform": platform,
            "account_id": account_id,
            "available_platforms": [PLATFORM],
            "available_accounts": available_accounts(session, platform, account_id),
        }

    @router.post("/contacts/{contact_id}/conversation")
    def ensure_contact_conversation(
        contact_id: str,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        contact = session.get(Contact, contact_id)
        if contact is None:
            raise HTTPException(status_code=404, detail="Contact not found")
        conversation = session.scalar(
            select(Conversation).where(
                Conversation.account_id == contact.account_id,
                Conversation.remote_jid == contact.remote_jid,
            )
        )
        if conversation is None:
            try:
                with session.begin_nested():
                    conversation = Conversation(
                        account_id=contact.account_id,
                        contact_id=contact.id,
                        remote_jid=contact.remote_jid,
                        title=_display_name(contact.remark, contact.display_name)
                        or _fallback_contact_name(contact.remote_jid),
                    )
                    session.add(conversation)
                    session.flush()
            except IntegrityError:
                conversation = session.scalar(
                    select(Conversation).where(
                        Conversation.account_id == contact.account_id,
                        Conversation.remote_jid == contact.remote_jid,
                    )
                )
                if conversation is None:
                    raise
        conversation.contact_id = contact.id
        conversation.deleted_at = None
        conversation.archived = False
        session.commit()
        return {
            "conversation_id": conversation.id,
            "contact_id": contact.id,
            "account_id": contact.account_id,
            "remote_jid": contact.remote_jid,
            "restored": True,
        }

    @router.patch("/conversations/{conversation_id}")
    def update_conversation_state(
        conversation_id: str,
        payload: ConversationStateUpdate,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(status_code=422, detail="No state changes provided")
        for key, value in changes.items():
            setattr(conversation, key, value)
        session.commit()
        return {
            "success": True,
            "conversation_id": conversation.id,
            "account_id": conversation.account_id,
            "pinned": conversation.pinned,
            "muted": conversation.muted,
            "archived": conversation.archived,
        }

    @router.post("/conversations/{conversation_id}/read")
    def mark_conversation_read(
        conversation_id: str,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conversation.unread_count = 0
        session.commit()
        return {
            "success": True,
            "conversation_id": conversation.id,
            "unread_count": 0,
        }

    @router.delete("/conversations/{conversation_id}")
    def delete_conversation(
        conversation_id: str,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conversation.deleted_at = datetime.now(timezone.utc)
        session.commit()
        return {
            "success": True,
            "conversation_id": conversation.id,
            "account_id": conversation.account_id,
            "deleted_at": _iso(conversation.deleted_at),
        }

    @router.get("/conversations/{conversation_id}/messages")
    def conversation_messages(
        conversation_id: str,
        limit: int = Query(default=80, ge=1, le=200),
        before_occurred_at: datetime | None = Query(default=None),
        before_id: str | None = Query(default=None),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if before_id and before_occurred_at is None:
            raise HTTPException(
                status_code=422,
                detail="before_id requires before_occurred_at",
            )
        if before_occurred_at is not None and before_occurred_at.tzinfo is None:
            before_occurred_at = before_occurred_at.replace(tzinfo=timezone.utc)

        sort_time = func.coalesce(Message.occurred_at, Message.created_at)
        statement = select(Message).where(Message.conversation_id == conversation.id)
        if before_occurred_at is not None:
            cursor_clause = sort_time < before_occurred_at
            if before_id:
                cursor_clause = or_(
                    cursor_clause,
                    and_(sort_time == before_occurred_at, Message.id < before_id),
                )
            statement = statement.where(cursor_clause)

        rows = session.scalars(
            statement.order_by(sort_time.desc(), Message.id.desc()).limit(limit + 1)
        ).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = None
        if has_more and rows:
            oldest = rows[-1]
            next_cursor = {
                "before_occurred_at": _iso(oldest.occurred_at or oldest.created_at),
                "before_id": oldest.id,
            }
        rows.reverse()
        messages = [
            {
                "message_id": message.id,
                "platform_message_id": message.wa_message_id,
                "account_id": message.account_id,
                "conversation_id": message.conversation_id,
                "role": "assistant" if message.direction == "outbound" else "user",
                "direction": message.direction,
                "content": message.content or "",
                "message_type": message.message_type,
                "media_metadata": message.media_metadata or {},
                "status": message.status,
                "pending": message.status in {"queued", "sending"},
                "failed": message.status == "failed",
                "sent": message.status in {"sent", "delivered", "read"},
                "error": message.error_message,
                "retryable": message.status != "failed" or message.retry_count < 6,
                "lang": "Unknown",
                "timestamp": _timestamp(message.occurred_at or message.created_at),
                "occurred_at": _iso(message.occurred_at),
                "created_at": _iso(message.created_at),
            }
            for message in rows
        ]
        total = (
            session.scalar(
                select(func.count(Message.id)).where(
                    Message.conversation_id == conversation.id
                )
            )
            or 0
        )
        return {
            "conversation_id": conversation.id,
            "account_id": conversation.account_id,
            "user_id": conversation.remote_jid,
            "messages": messages,
            "total_messages": total,
            "has_more": has_more,
            "next_cursor": next_cursor,
        }

    @router.post("/conversations/{conversation_id}/reply", status_code=202)
    def reply_to_conversation(
        conversation_id: str,
        payload: ConversationReplyRequest,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if payload.preview_only:
            return {
                "success": True,
                "preview_only": True,
                "conversation_id": conversation.id,
                "message": payload.message,
                "mode": "direct",
                "rewrite": {"language": "direct"},
            }
        idempotency_key = payload.idempotency_key or f"reply:{uuid4()}"
        if not idempotency_key.startswith("reply:"):
            idempotency_key = f"reply:{idempotency_key}"
        try:
            message, outbox, created = enqueue_outbox_message(
                session,
                conversation,
                text=payload.message,
                idempotency_key=idempotency_key,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        session.commit()
        return {
            "success": True,
            "created": created,
            "queued": outbox.status in {"pending", "claimed"},
            "status": message.status,
            "local_message_id": message.id,
            "message_id": message.wa_message_id,
            "outbox_id": outbox.id,
            "account_id": conversation.account_id,
            "conversation_id": conversation.id,
        }

    # ── Translate ──────────────────────────────────────────────────────────────

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

    class _TranslateRequest(BaseModel):
        user_id: str = Field(default="", max_length=255)
        content: str = Field(default="", max_length=10000)

    @router.post(
        "/conversations/{conversation_id}/translate",
        tags=["conversations"],
        summary="Translate a message",
    )
    def translate_message(
        conversation_id: str,
        body: TranslateRequest,
        request: Request,
    ) -> dict[str, Any]:
        """
        Translate a message to Chinese.
        Replaces the legacy POST /api/messages/{message_id}/translate endpoint.
        """
        user_id = body.user_id or "default"
        text = body.content

        session = next(get_session())
        try:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None or conversation.deleted_at is not None:
                raise HTTPException(status_code=404, detail="Conversation not found")

            lang = _language_hint_for(text)
            if lang == "Chinese":
                return {
                    "message_id": str(conversation_id),
                    "lang": lang,
                    "translated": None,
                }

            # Access runtime from app state (set in standalone_api.py)
            runtime = getattr(request.app.state, "runtime", None)
            if runtime is None:
                raise HTTPException(status_code=500, detail="Runtime not available")

            # Build a minimal config-like object for Rewriter
            from whatsapp_chat_system.rewriter import Rewriter

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
            worker = Rewriter(config, lambda *args, **kwargs: None)
            result = worker.translate_to_zh_result(text, lang)

            if result.message and result.message != text:
                _put_translation(
                    runtime.paths.memory_dir,
                    user_id,
                    str(conversation_id),
                    {
                        "source_lang": lang,
                        "source_text": text[:200],
                        "zh": result.message,
                    },
                )

            payload: dict[str, Any] = {
                "message_id": str(conversation_id),
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
        finally:
            session.close()

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

    return router
