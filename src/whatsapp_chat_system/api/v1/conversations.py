from __future__ import annotations

from collections.abc import Callable, Generator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from whatsapp_chat_system.db.models import (
    Contact,
    Conversation,
    Message,
    WhatsAppAccount,
)


PLATFORM = "whatsapp"


class ConversationReplyRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)


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
            select(Conversation, Contact, WhatsAppAccount)
            .join(WhatsAppAccount, WhatsAppAccount.id == Conversation.account_id)
            .outerjoin(Contact, Contact.id == Conversation.contact_id)
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
                "user_name": (
                    (contact.remark if contact else None)
                    or (contact.display_name if contact else None)
                    or conversation.title
                    or conversation.remote_jid
                ),
                "platform": PLATFORM,
                "last_message": conversation.last_message_preview or "",
                "last_timestamp": _timestamp(conversation.last_message_at),
                "last_message_at": _iso(conversation.last_message_at),
                "unread_count": conversation.unread_count,
                "pinned": conversation.pinned,
                "muted": conversation.muted,
            }
            for conversation, contact, account in rows
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
            select(Contact, WhatsAppAccount, Conversation)
            .join(WhatsAppAccount, WhatsAppAccount.id == Contact.account_id)
            .outerjoin(
                Conversation,
                (Conversation.account_id == Contact.account_id)
                & (Conversation.remote_jid == Contact.remote_jid)
                & Conversation.deleted_at.is_(None),
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
                "user_name": contact.remark
                or contact.display_name
                or contact.remote_jid,
                "phone_number": contact.phone_number,
                "avatar_url": contact.avatar_url,
                "tags": contact.tags or [],
                "language": contact.language,
                "notes": contact.notes,
            }
            for contact, account, conversation in rows
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
                        title=contact.remark or contact.display_name,
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

    @router.delete("/conversations/{conversation_id}")
    def delete_conversation(
        conversation_id: str,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conversation.deleted_at = datetime.utcnow()
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
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        rows = session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(
                Message.occurred_at.desc(), Message.created_at.desc(), Message.id.desc()
            )
            .limit(limit)
        ).all()
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
                "status": message.status,
                "lang": "Unknown",
                "timestamp": _timestamp(message.occurred_at or message.created_at),
                "occurred_at": _iso(message.occurred_at),
                "created_at": _iso(message.created_at),
            }
            for message in rows
        ]
        return {
            "conversation_id": conversation.id,
            "account_id": conversation.account_id,
            "user_id": conversation.remote_jid,
            "messages": messages,
            "total_messages": len(messages),
            "has_more": False,
        }

    @router.post("/conversations/{conversation_id}/reply")
    def reply_to_conversation(
        conversation_id: str,
        payload: ConversationReplyRequest,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        if bridge is None:
            raise HTTPException(status_code=503, detail="WhatsApp bridge unavailable")
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        sent = bridge.send(
            conversation.account_id,
            chat_id=conversation.remote_jid,
            text=payload.message,
        )
        now = datetime.utcnow()
        message = Message(
            account_id=conversation.account_id,
            conversation_id=conversation.id,
            contact_id=conversation.contact_id,
            wa_message_id=sent["message_id"],
            direction="outbound",
            sender_jid=None,
            message_type="text",
            content=payload.message,
            status="sent",
            occurred_at=now,
            sent_at=now,
        )
        session.add(message)
        conversation.last_message_preview = payload.message
        conversation.last_message_at = now
        session.commit()
        return {
            "success": True,
            "local_message_id": message.id,
            "message_id": message.wa_message_id,
            "account_id": conversation.account_id,
            "conversation_id": conversation.id,
        }

    return router
