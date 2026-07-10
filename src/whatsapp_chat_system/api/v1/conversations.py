from __future__ import annotations

from collections.abc import Callable, Generator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from whatsapp_chat_system.db.models import Contact, Conversation, Message, WhatsAppAccount


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _timestamp(value: datetime | None) -> float:
    return value.timestamp() if value else 0.0


def create_conversations_router(session_factory: Callable[[], Session]) -> APIRouter:
    router = APIRouter(prefix='/api/v1/conversations', tags=['conversations'])

    def get_session() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    @router.get('')
    def list_conversations(
        account_id: str = Query(default='all'),
        limit: int = Query(default=50, ge=1, le=200),
        query: str = Query(default=''),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        statement = (
            select(Conversation, Contact, WhatsAppAccount)
            .join(WhatsAppAccount, WhatsAppAccount.id == Conversation.account_id)
            .outerjoin(Contact, Contact.id == Conversation.contact_id)
            .where(Conversation.deleted_at.is_(None), Conversation.archived.is_(False))
        )
        if account_id != 'all':
            statement = statement.where(Conversation.account_id == account_id)
        cleaned_query = query.strip()
        if cleaned_query:
            pattern = f'%{cleaned_query}%'
            statement = statement.where(
                Conversation.remote_jid.ilike(pattern)
                | Conversation.title.ilike(pattern)
                | Contact.display_name.ilike(pattern)
                | Contact.remark.ilike(pattern)
            )
        rows = session.execute(
            statement.order_by(
                Conversation.pinned.desc(),
                Conversation.last_message_at.desc(),
                Conversation.id.desc(),
            ).limit(limit)
        ).all()
        items = [
            {
                'conversation_id': conversation.id,
                'account_id': conversation.account_id,
                'account_name': account.name,
                'user_id': conversation.remote_jid,
                'user_name': (
                    (contact.remark if contact else None)
                    or conversation.title
                    or (contact.display_name if contact else None)
                    or conversation.remote_jid
                ),
                'platform': 'whatsapp',
                'last_message': conversation.last_message_preview or '',
                'last_timestamp': _timestamp(conversation.last_message_at),
                'last_message_at': _iso(conversation.last_message_at),
                'unread_count': conversation.unread_count,
                'pinned': conversation.pinned,
                'muted': conversation.muted,
            }
            for conversation, contact, account in rows
        ]
        count_statement = select(func.count(Conversation.id)).where(
            Conversation.deleted_at.is_(None), Conversation.archived.is_(False)
        )
        if account_id != 'all':
            count_statement = count_statement.where(Conversation.account_id == account_id)
        total = session.scalar(count_statement) or 0
        return {
            'items': items,
            'total': total,
            'has_more': total > len(items),
            'account_id': account_id,
        }

    @router.get('/{conversation_id}/messages')
    def conversation_messages(
        conversation_id: str,
        limit: int = Query(default=80, ge=1, le=200),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            raise HTTPException(status_code=404, detail='Conversation not found')
        rows = session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.occurred_at.asc(), Message.created_at.asc(), Message.id.asc())
            .limit(limit)
        ).all()
        messages = [
            {
                'message_id': message.id,
                'platform_message_id': message.wa_message_id,
                'account_id': message.account_id,
                'conversation_id': message.conversation_id,
                'role': 'assistant' if message.direction == 'outbound' else 'user',
                'direction': message.direction,
                'content': message.content or '',
                'message_type': message.message_type,
                'status': message.status,
                'timestamp': _timestamp(message.occurred_at or message.created_at),
                'occurred_at': _iso(message.occurred_at),
                'created_at': _iso(message.created_at),
            }
            for message in rows
        ]
        return {
            'conversation_id': conversation.id,
            'account_id': conversation.account_id,
            'user_id': conversation.remote_jid,
            'messages': messages,
            'total_messages': len(messages),
            'has_more': False,
        }

    return router
