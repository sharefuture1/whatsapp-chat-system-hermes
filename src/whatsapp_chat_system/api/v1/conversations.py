from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Generator
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from whatsapp_chat_system.authz import (
    require_object_account_access,
    restrict_account_id,
    visible_account_ids_for,
)
from whatsapp_chat_system.db.models import (
    Conversation,
    Contact,
    ContactAIOverride,
    Message,
    MessageTranslation,
    TranslationBatch,
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


def _source_text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _fallback_contact_name(remote_jid: str) -> str:
    return "WhatsApp 联系人" if remote_jid.endswith("@lid") else remote_jid


class ConversationReplyRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    mode: str = Field(default="direct", max_length=32)
    idempotency_key: str | None = Field(default=None, max_length=255)
    preview_only: bool = False


class ConversationStateUpdate(BaseModel):
    pinned: bool | None = None
    muted: bool | None = None
    archived: bool | None = None


class AutoReplyUpdate(BaseModel):
    enabled: bool


class TranslateRequest(BaseModel):
    user_id: str = Field(default="", max_length=255)
    content: str = Field(default="", max_length=10000)


class TranslationBatchRequest(BaseModel):
    anchor_message_id: str = Field(..., max_length=36)
    target_lang: str = Field(default="zh-CN", max_length=32)
    window_size: int = Field(default=10, ge=1, le=20)


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
        session: Session,
        platform: str,
        account_id: str,
        visible_account_ids: list[str] | None,
    ) -> list[dict[str, Any]]:
        if platform not in {"all", PLATFORM}:
            return []
        statement = select(WhatsAppAccount).order_by(
            WhatsAppAccount.is_primary.desc(), WhatsAppAccount.created_at.asc()
        )
        if account_id != "all":
            statement = statement.where(WhatsAppAccount.id == account_id)
        if visible_account_ids is not None:
            statement = statement.where(WhatsAppAccount.id.in_(visible_account_ids))
        return [
            _account_payload(account) for account in session.scalars(statement).all()
        ]

    @router.get("/conversations")
    def list_conversations(
        request: Request,
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
        visible_ids = visible_account_ids_for(request.app.state.runtime, request)
        account_id = restrict_account_id(account_id, visible_ids)
        statement = (
            select(Conversation, Contact, WhatsAppAccount, ContactAIOverride)
            .join(WhatsAppAccount, WhatsAppAccount.id == Conversation.account_id)
            .outerjoin(
                Contact,
                and_(
                    Contact.id == Conversation.contact_id,
                    Contact.account_id == Conversation.account_id,
                ),
            )
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
        if visible_ids is not None:
            statement = statement.where(Conversation.account_id.in_(visible_ids))
            count_statement = count_statement.where(
                Conversation.account_id.in_(visible_ids)
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
                )
                or _fallback_contact_name(conversation.remote_jid),
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
            "available_accounts": available_accounts(
                session, platform, account_id, visible_ids
            ),
        }

    @router.get("/contacts")
    def list_contacts(
        request: Request,
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
        visible_ids = visible_account_ids_for(request.app.state.runtime, request)
        account_id = restrict_account_id(account_id, visible_ids)
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
        if visible_ids is not None:
            statement = statement.where(Contact.account_id.in_(visible_ids))
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
                )
                or _fallback_contact_name(contact.remote_jid),
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
            "available_accounts": available_accounts(
                session, platform, account_id, visible_ids
            ),
        }

    @router.post("/contacts/{contact_id}/conversation")
    def ensure_contact_conversation(
        request: Request,
        contact_id: str,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        contact = session.get(Contact, contact_id)
        if contact is None:
            raise HTTPException(status_code=404, detail="Contact not found")
        require_object_account_access(
            request.app.state.runtime,
            request,
            contact.account_id,
            write=True,
            not_found_detail="Contact not found",
        )
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

    @router.patch("/conversations/{conversation_id}/auto-reply")
    def update_auto_reply(
        request: Request,
        conversation_id: str,
        payload: AutoReplyUpdate,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        require_object_account_access(
            request.app.state.runtime,
            request,
            conversation.account_id,
            write=True,
            not_found_detail="Conversation not found",
        )
        account = session.get(WhatsAppAccount, conversation.account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        contact = (
            session.scalar(
                select(Contact).where(
                    Contact.id == conversation.contact_id,
                    Contact.account_id == conversation.account_id,
                )
            )
            if conversation.contact_id
            else None
        )
        if contact is None:
            raise HTTPException(status_code=409, detail="Conversation has no contact")
        override = session.scalar(
            select(ContactAIOverride).where(
                ContactAIOverride.account_id == account.id,
                ContactAIOverride.contact_id == contact.id,
            )
        )
        if override is None:
            override = ContactAIOverride(account_id=account.id, contact_id=contact.id)
            session.add(override)
        override.auto_reply_enabled = payload.enabled
        session.commit()
        return {
            "success": True,
            "conversation_id": conversation.id,
            "contact_id": contact.id,
            "auto_reply_enabled": override.auto_reply_enabled,
            "account_mode": account.auto_reply_mode,
            "account_online": account.status == "online",
        }

    @router.patch("/conversations/{conversation_id}")
    def update_conversation_state(
        request: Request,
        conversation_id: str,
        payload: ConversationStateUpdate,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        require_object_account_access(
            request.app.state.runtime,
            request,
            conversation.account_id,
            write=True,
            not_found_detail="Conversation not found",
        )
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
        request: Request,
        conversation_id: str,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        require_object_account_access(
            request.app.state.runtime,
            request,
            conversation.account_id,
            write=True,
            not_found_detail="Conversation not found",
        )
        conversation.unread_count = 0
        session.commit()
        return {
            "success": True,
            "conversation_id": conversation.id,
            "unread_count": 0,
        }

    @router.delete("/conversations/{conversation_id}")
    def delete_conversation(
        request: Request,
        conversation_id: str,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        require_object_account_access(
            request.app.state.runtime,
            request,
            conversation.account_id,
            write=True,
            not_found_detail="Conversation not found",
        )
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
        request: Request,
        conversation_id: str,
        limit: int = Query(default=80, ge=1, le=200),
        before_occurred_at: datetime | None = Query(default=None),
        before_id: str | None = Query(default=None),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        require_object_account_access(
            request.app.state.runtime,
            request,
            conversation.account_id,
            not_found_detail="Conversation not found",
        )
        if before_id and before_occurred_at is None:
            raise HTTPException(
                status_code=422,
                detail="before_id requires before_occurred_at",
            )
        if before_occurred_at is not None and before_occurred_at.tzinfo is None:
            before_occurred_at = before_occurred_at.replace(tzinfo=timezone.utc)

        sort_time = func.coalesce(Message.occurred_at, Message.created_at)
        statement = select(Message).where(
            Message.conversation_id == conversation.id,
            Message.account_id == conversation.account_id,
        )
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
        translation_rows = (
            session.scalars(
                select(MessageTranslation)
                .where(
                    MessageTranslation.account_id == conversation.account_id,
                    MessageTranslation.conversation_id == conversation.id,
                    MessageTranslation.message_id.in_([message.id for message in rows]),
                    MessageTranslation.target_lang == "zh-CN",
                )
                .order_by(MessageTranslation.updated_at.desc())
            ).all()
            if rows
            else []
        )
        translations_by_message: dict[str, MessageTranslation] = {}
        for item in translation_rows:
            translations_by_message.setdefault(item.message_id, item)
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
                "lang": translation.source_lang
                if (translation := translations_by_message.get(message.id))
                else "Unknown",
                "translated": translation.translated_text
                if translation and translation.status == "completed"
                else None,
                "translation_status": translation.status if translation else None,
                "translation_updated_at": _iso(translation.updated_at)
                if translation
                else None,
                "timestamp": _timestamp(message.occurred_at or message.created_at),
                "occurred_at": _iso(message.occurred_at),
                "created_at": _iso(message.created_at),
            }
            for message in rows
        ]
        total = (
            session.scalar(
                select(func.count(Message.id)).where(
                    Message.conversation_id == conversation.id,
                    Message.account_id == conversation.account_id,
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
        request: Request,
        conversation_id: str,
        payload: ConversationReplyRequest,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        require_object_account_access(
            request.app.state.runtime,
            request,
            conversation.account_id,
            write=True,
            not_found_detail="Conversation not found",
        )
        if payload.preview_only:
            try:
                from whatsapp_chat_system.rewriter import Rewriter

                class _DummyAppPaths:
                    memory_dir: Any

                    def __init__(self, memory_dir: Any) -> None:
                        self.memory_dir = memory_dir

                class _DummyConfig:
                    paths: _DummyAppPaths
                    ai_settings: Any
                    web_settings: dict[str, Any]

                    def __init__(
                        self,
                        memory_dir: Any,
                        ai_settings: Any,
                        web_settings: dict[str, Any],
                    ) -> None:
                        self.paths = _DummyAppPaths(memory_dir)
                        self.ai_settings = ai_settings
                        self.web_settings = web_settings

                runtime = getattr(session.bind, "_standalone_runtime", None)
                if runtime is None:
                    from whatsapp_chat_system.runtime import StandaloneRuntime

                    runtime = StandaloneRuntime.from_env()
                runtime_manager = None
                try:
                    from whatsapp_chat_system.runtime import RuntimeAISettings

                    runtime_manager = RuntimeAISettings(
                        runtime.ai_settings, lambda: session
                    )
                except Exception:
                    runtime_manager = None

                contact = session.scalar(
                    select(Contact).where(
                        Contact.account_id == conversation.account_id,
                        Contact.remote_jid == conversation.remote_jid,
                    )
                )
                override = (
                    session.get(ContactAIOverride, (contact.account_id, contact.id))
                    if contact is not None
                    else None
                )
                reply_overrides = {}
                if override is not None:
                    reply_overrides = {
                        "ai_model": override.model,
                        "custom_system_prompt": override.system_prompt,
                        "reply_style": override.reply_style,
                    }
                web_settings = {
                    "reply": {
                        "smart_max_length": 40,
                        "translate_max_length": 60,
                        "default_reply_style": "",
                        "user_overrides": {conversation.remote_jid: reply_overrides}
                        if reply_overrides
                        else {},
                    },
                    "plugins": runtime.web_settings.get("plugins", {}),
                    "contact_profiles": {
                        conversation.remote_jid: {
                            "remark": contact.remark if contact is not None else None,
                            "notes": contact.notes if contact is not None else None,
                        }
                    }
                    if contact is not None
                    else {},
                }
                config = _DummyConfig(
                    runtime.paths.memory_dir, runtime.ai_settings, web_settings
                )
                rewriter = Rewriter(
                    config,
                    lambda *args, **kwargs: None,
                    runtime_manager=runtime_manager,
                )
                target = {
                    "id": conversation.remote_jid,
                    "name": conversation.title or conversation.remote_jid,
                }
                memory_md = ""
                mode = (payload.mode or "smart").strip() or "smart"
                if mode == "translate":
                    preview_translation = rewriter.translate_to_zh_result(
                        payload.message, "Unknown"
                    )
                    return {
                        "success": True,
                        "preview_only": True,
                        "conversation_id": conversation.id,
                        "message": payload.message,
                        "mode": mode,
                        "rewrite": {
                            "language": preview_translation.language,
                            "message": preview_translation.message,
                            "used_fallback": preview_translation.used_fallback,
                            "error": preview_translation.error,
                            "persona": None,
                        },
                    }
                elif mode == "direct":
                    rewrite = None
                else:
                    rewrite = rewriter.rewrite(
                        target,
                        payload.message,
                        memory_md,
                        reply_overrides=reply_overrides,
                    )
                if rewrite is not None:
                    return {
                        "success": True,
                        "preview_only": True,
                        "conversation_id": conversation.id,
                        "message": payload.message,
                        "mode": mode,
                        "rewrite": {
                            "language": rewrite.language,
                            "message": rewrite.message,
                            "used_fallback": rewrite.used_fallback,
                            "error": rewrite.error,
                            "persona": rewrite.persona,
                        },
                    }
            except Exception:
                pass
            return {
                "success": True,
                "preview_only": True,
                "conversation_id": conversation.id,
                "message": payload.message,
                "mode": "direct",
                "rewrite": {
                    "language": "direct",
                    "message": payload.message,
                    "used_fallback": True,
                },
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
        "/conversations/{conversation_id}/translations",
        tags=["conversations"],
        status_code=202,
        summary="Queue conversation translation batch",
    )
    def queue_translation_batch(
        request: Request,
        conversation_id: str,
        payload: TranslationBatchRequest = Body(...),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        require_object_account_access(
            request.app.state.runtime,
            request,
            conversation.account_id,
            write=True,
            not_found_detail="Conversation not found",
        )
        anchor = session.scalar(
            select(Message).where(
                Message.id == payload.anchor_message_id,
                Message.account_id == conversation.account_id,
                Message.conversation_id == conversation.id,
            )
        )
        if anchor is None:
            raise HTTPException(status_code=404, detail="Anchor message not found")
        rows = session.scalars(
            select(Message)
            .where(
                Message.account_id == conversation.account_id,
                Message.conversation_id == conversation.id,
                func.coalesce(Message.occurred_at, Message.created_at)
                <= func.coalesce(anchor.occurred_at, anchor.created_at),
            )
            .order_by(
                func.coalesce(Message.occurred_at, Message.created_at).desc(),
                Message.id.desc(),
            )
            .limit(payload.window_size)
        ).all()
        rows.reverse()
        queued_message_ids: list[str] = []
        cached_message_ids: list[str] = []
        for message in rows:
            text = message.content or ""
            if not text:
                continue
            lang = _language_hint_for(text)
            if lang == "Chinese":
                cached_message_ids.append(message.id)
                continue
            existing = session.scalar(
                select(MessageTranslation).where(
                    MessageTranslation.message_id == message.id,
                    MessageTranslation.target_lang == payload.target_lang,
                    MessageTranslation.source_text_hash == _source_text_hash(text),
                    MessageTranslation.status == "completed",
                )
            )
            if existing is not None:
                cached_message_ids.append(message.id)
            else:
                queued_message_ids.append(message.id)
        batch = TranslationBatch(
            account_id=conversation.account_id,
            conversation_id=conversation.id,
            anchor_message_id=anchor.id,
            target_lang=payload.target_lang,
            window_size=payload.window_size,
            status="pending",
        )
        session.add(batch)
        session.commit()
        return {
            "batch_id": batch.id,
            "status": "queued",
            "queued_message_ids": queued_message_ids,
            "cached_message_ids": cached_message_ids,
            "target_lang": payload.target_lang,
            "window_size": payload.window_size,
        }

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
        text = body.content

        session = next(get_session())
        try:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None or conversation.deleted_at is not None:
                raise HTTPException(status_code=404, detail="Conversation not found")
            require_object_account_access(
                request.app.state.runtime,
                request,
                conversation.account_id,
                write=True,
                not_found_detail="Conversation not found",
            )
            # The cache namespace is derived from server-owned tenant data. The
            # legacy user_id field remains accepted for wire compatibility but
            # must never select a file path or another contact's cache.
            cache_scope = hashlib.sha256(
                f"{conversation.account_id}:{conversation.remote_jid}".encode("utf-8")
            ).hexdigest()

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
                web_settings: dict[str, Any]

                def __init__(
                    self,
                    memory_dir: Any,
                    ai_settings: Any,
                    web_settings: dict[str, Any],
                ) -> None:
                    self.paths = _DummyAppPaths(memory_dir)
                    self.ai_settings = ai_settings
                    self.web_settings = web_settings

            config = _DummyConfig(
                runtime.paths.memory_dir, runtime.ai_settings, runtime.web_settings
            )
            worker = Rewriter(config, lambda *args, **kwargs: None)
            result = worker.translate_to_zh_result(text, lang)

            if result.message and result.message != text:
                _put_translation(
                    runtime.paths.memory_dir,
                    cache_scope,
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
