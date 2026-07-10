from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from whatsapp_chat_system.db.models import (
    Contact,
    Conversation,
    Message,
    WhatsAppAccount,
    WhatsAppEvent,
    utc_now,
)


EventType = Literal[
    'account.qr', 'account.connecting', 'account.connected', 'account.disconnected',
    'account.logged_out', 'account.error', 'message.upsert', 'message.sent',
    'message.delivered', 'message.read', 'message.failed',
]


class WhatsAppEventEnvelope(BaseModel):
    model_config = ConfigDict(extra='forbid')

    event_id: str = Field(min_length=1, max_length=255)
    event_type: EventType
    account_id: str = Field(min_length=1, max_length=36)
    occurred_at: datetime
    sequence: int = Field(ge=0)
    payload: dict[str, Any]


class MessageUpsertPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')

    schema_version: Literal[1]
    wa_message_id: str = Field(min_length=1, max_length=255)
    remote_jid: str = Field(min_length=1, max_length=255)
    sender_jid: str | None = None
    participant_jid: str | None = None
    from_me: bool
    conversation_type: Literal['dm', 'group']
    message_type: Literal['text', 'image', 'audio', 'video', 'document', 'system']
    timestamp: datetime
    text: str | None = None
    push_name: str | None = None
    quoted_wa_message_id: str | None = None
    media: dict[str, Any] | None = None


class ReceiptPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')

    wa_message_id: str = Field(min_length=1, max_length=255)
    timestamp: datetime
    error_code: str | None = None
    error_message: str | None = None


class EventProcessingError(Exception):
    code = 'event_processing_error'
    retryable = False
    status_code = 400


class EventConflictError(EventProcessingError):
    code = 'event_identity_conflict'
    status_code = 409


class AccountNotFoundError(EventProcessingError):
    code = 'account_not_found'
    retryable = True
    status_code = 404


class MessageNotFoundError(EventProcessingError):
    code = 'message_not_found'
    retryable = True
    status_code = 409


def canonical_hash(envelope: WhatsAppEventEnvelope) -> str:
    body = envelope.model_dump(mode='json')
    encoded = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _safe_payload(envelope: WhatsAppEventEnvelope) -> dict[str, Any]:
    payload = envelope.payload
    if envelope.event_type != 'account.qr':
        return payload
    return {
        key: value for key, value in payload.items()
        if key.lower() not in {'qr', 'qr_data', 'qr_data_url', 'raw_qr'}
    }


class WhatsAppEventService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def process(self, envelope: WhatsAppEventEnvelope) -> bool:
        payload_hash = canonical_hash(envelope)
        existing = self.session.scalar(select(WhatsAppEvent).where(
            WhatsAppEvent.account_id == envelope.account_id,
            WhatsAppEvent.event_id == envelope.event_id,
        ))
        if existing is not None:
            if existing.payload_hash != payload_hash:
                raise EventConflictError('event identity already exists with different payload')
            return True

        account = self.session.get(WhatsAppAccount, envelope.account_id)
        if account is None:
            raise AccountNotFoundError(envelope.account_id)

        event = WhatsAppEvent(
            event_id=envelope.event_id,
            account_id=envelope.account_id,
            event_type=envelope.event_type,
            occurred_at=envelope.occurred_at,
            sequence=envelope.sequence,
            payload=_safe_payload(envelope),
            payload_hash=payload_hash,
            status='received',
        )
        self.session.add(event)

        if envelope.event_type == 'message.upsert':
            self._upsert_message(account, MessageUpsertPayload.model_validate(envelope.payload))
        elif envelope.event_type.startswith('message.'):
            self._apply_receipt(account, envelope.event_type, ReceiptPayload.model_validate(envelope.payload))
        else:
            self._apply_account_status(account, envelope)

        event.status = 'processed'
        event.processed_at = utc_now()
        return False

    def _upsert_message(self, account: WhatsAppAccount, payload: MessageUpsertPayload) -> None:
        contact = self.session.scalar(select(Contact).where(
            Contact.account_id == account.id, Contact.remote_jid == payload.remote_jid
        ))
        if contact is None:
            contact = Contact(
                account_id=account.id,
                remote_jid=payload.remote_jid,
                display_name=payload.push_name,
            )
            self.session.add(contact)
            self.session.flush()
        elif payload.push_name:
            contact.display_name = payload.push_name

        conversation = self.session.scalar(select(Conversation).where(
            Conversation.account_id == account.id,
            Conversation.remote_jid == payload.remote_jid,
        ))
        if conversation is None:
            conversation = Conversation(
                account_id=account.id,
                contact_id=contact.id,
                remote_jid=payload.remote_jid,
                type=payload.conversation_type,
                title=payload.push_name,
            )
            self.session.add(conversation)
            self.session.flush()
        elif conversation.account_id != account.id:
            raise EventProcessingError('cross-account conversation reference')
        else:
            conversation.contact_id = contact.id

        message = self.session.scalar(select(Message).where(
            Message.account_id == account.id,
            Message.wa_message_id == payload.wa_message_id,
        ))
        is_new = message is None
        if message is None:
            message = Message(
                account_id=account.id,
                conversation_id=conversation.id,
                contact_id=contact.id,
                wa_message_id=payload.wa_message_id,
                direction='outbound' if payload.from_me else 'inbound',
                status='sent' if payload.from_me else 'received',
                received_at=utc_now(),
            )
            self.session.add(message)
        elif message.account_id != account.id:
            raise EventProcessingError('cross-account message reference')

        message.conversation_id = conversation.id
        message.contact_id = contact.id
        message.direction = 'outbound' if payload.from_me else 'inbound'
        message.sender_jid = payload.participant_jid or payload.sender_jid
        message.message_type = payload.message_type
        message.content = payload.text
        message.media_metadata = payload.media
        occurred_at = _naive_utc(payload.timestamp)
        message.occurred_at = occurred_at

        if is_new and not payload.from_me:
            conversation.unread_count += 1
        if conversation.last_message_at is None or occurred_at >= conversation.last_message_at:
            conversation.last_message_at = occurred_at
            conversation.last_message_preview = payload.text or f'[{payload.message_type}]'
            if payload.push_name:
                conversation.title = payload.push_name

    def _apply_account_status(
        self, account: WhatsAppAccount, envelope: WhatsAppEventEnvelope
    ) -> None:
        if envelope.sequence <= account.last_event_sequence:
            return
        statuses = {
            'account.qr': 'qr_pending',
            'account.connecting': 'connecting',
            'account.connected': 'online',
            'account.disconnected': 'offline',
            'account.logged_out': 'logged_out',
            'account.error': 'error',
        }
        account.status = statuses[envelope.event_type]
        account.last_event_sequence = envelope.sequence
        if envelope.event_type == 'account.connected':
            account.phone_number = envelope.payload.get('phone_number')
            account.last_seen_at = envelope.occurred_at
            account.last_error_code = None
            account.last_error_message = None
        elif envelope.event_type == 'account.error':
            account.last_error_code = envelope.payload.get('code')
            account.last_error_message = envelope.payload.get('message')

    def _apply_receipt(
        self, account: WhatsAppAccount, event_type: str, payload: ReceiptPayload
    ) -> None:
        message = self.session.scalar(select(Message).where(
            Message.account_id == account.id,
            Message.wa_message_id == payload.wa_message_id,
        ))
        if message is None:
            raise MessageNotFoundError(payload.wa_message_id)

        rank = {'sent': 1, 'delivered': 2, 'read': 3}
        target = event_type.removeprefix('message.')
        current_rank = rank.get(message.status, 0)
        if target == 'failed':
            if current_rank == 0:
                message.status = 'failed'
                message.error_code = payload.error_code
                message.error_message = payload.error_message
            return
        if rank[target] < current_rank:
            return
        message.status = target
        message.error_code = None
        message.error_message = None
        if target == 'sent':
            message.sent_at = payload.timestamp
        elif target == 'delivered':
            message.delivered_at = payload.timestamp
        elif target == 'read':
            message.read_at = payload.timestamp
