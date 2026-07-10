from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from whatsapp_chat_system.db.base import Base


UUID_LENGTH = 36


def new_uuid() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class AIProfile(TimestampMixin, Base):
    __tablename__ = 'ai_profiles'
    __table_args__ = (
        CheckConstraint('timeout_seconds > 0', name='timeout_seconds_positive'),
        CheckConstraint('max_retries >= 0', name='max_retries_non_negative'),
    )

    id: Mapped[str] = mapped_column(String(UUID_LENGTH), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default='wendingai')
    base_url: Mapped[str] = mapped_column(
        String(2048), nullable=False, default='https://wendingai.future1.us/v1'
    )
    default_model: Mapped[str] = mapped_column(
        String(255), nullable=False, default='gpt-5.3-codex-spark'
    )
    system_prompt: Mapped[str | None] = mapped_column(Text)
    reply_style: Mapped[str | None] = mapped_column(Text)
    temperature: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class WhatsAppAccount(TimestampMixin, Base):
    __tablename__ = 'whatsapp_accounts'
    __table_args__ = (
        CheckConstraint(
            "status IN ('new', 'qr_pending', 'connecting', 'online', 'offline', 'error', 'logged_out')",
            name='status_valid',
        ),
        CheckConstraint(
            "auto_reply_mode IN ('off', 'suggest', 'auto')", name='auto_reply_mode_valid'
        ),
        Index(
            'uq_whatsapp_accounts_one_primary',
            'is_primary',
            unique=True,
            sqlite_where=text('is_primary = 1'),
            postgresql_where=text('is_primary IS TRUE'),
        ),
    )

    id: Mapped[str] = mapped_column(String(UUID_LENGTH), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='new')
    session_ref: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_reply_mode: Mapped[str] = mapped_column(String(16), nullable=False, default='off')
    ai_profile_id: Mapped[str | None] = mapped_column(
        String(UUID_LENGTH), ForeignKey('ai_profiles.id', ondelete='SET NULL')
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(128))
    last_error_message: Mapped[str | None] = mapped_column(Text)


class Contact(TimestampMixin, Base):
    __tablename__ = 'contacts'
    __table_args__ = (
        UniqueConstraint('account_id', 'remote_jid', name='uq_contacts_account_remote_jid'),
        Index('ix_contacts_account_display_name', 'account_id', 'display_name'),
        Index('ix_contacts_account_phone_number', 'account_id', 'phone_number'),
    )

    id: Mapped[str] = mapped_column(String(UUID_LENGTH), primary_key=True, default=new_uuid)
    account_id: Mapped[str] = mapped_column(
        String(UUID_LENGTH),
        ForeignKey('whatsapp_accounts.id', ondelete='CASCADE'),
        nullable=False,
    )
    remote_jid: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(64))
    lid: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255))
    remark: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[Any] | None] = mapped_column(JSON)
    language: Mapped[str | None] = mapped_column(String(32))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column('metadata', JSON)


class Conversation(TimestampMixin, Base):
    __tablename__ = 'conversations'
    __table_args__ = (
        UniqueConstraint(
            'account_id', 'remote_jid', name='uq_conversations_account_remote_jid'
        ),
        CheckConstraint("type IN ('dm', 'group')", name='type_valid'),
        CheckConstraint("ai_mode IN ('off', 'suggest', 'auto')", name='ai_mode_valid'),
        CheckConstraint('unread_count >= 0', name='unread_count_non_negative'),
        Index(
            'ix_conversations_account_archived_last_message',
            'account_id',
            'archived',
            text('last_message_at DESC'),
        ),
        Index(
            'ix_conversations_account_pinned_last_message',
            'account_id',
            'pinned',
            text('last_message_at DESC'),
        ),
        Index('ix_conversations_account_unread', 'account_id', 'unread_count'),
    )

    id: Mapped[str] = mapped_column(String(UUID_LENGTH), primary_key=True, default=new_uuid)
    account_id: Mapped[str] = mapped_column(
        String(UUID_LENGTH),
        ForeignKey('whatsapp_accounts.id', ondelete='CASCADE'),
        nullable=False,
    )
    contact_id: Mapped[str | None] = mapped_column(
        String(UUID_LENGTH), ForeignKey('contacts.id', ondelete='SET NULL')
    )
    remote_jid: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False, default='dm')
    title: Mapped[str | None] = mapped_column(String(255))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_preview: Mapped[str | None] = mapped_column(Text)
    unread_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_operator_id: Mapped[str | None] = mapped_column(String(UUID_LENGTH))
    ai_mode: Mapped[str] = mapped_column(String(16), nullable=False, default='off')


class Message(Base):
    __tablename__ = 'messages'
    __table_args__ = (
        CheckConstraint("direction IN ('inbound', 'outbound')", name='direction_valid'),
        CheckConstraint(
            "message_type IN ('text', 'image', 'audio', 'video', 'document', 'system')",
            name='message_type_valid',
        ),
        CheckConstraint(
            "status IN ('received', 'queued', 'sending', 'sent', 'delivered', 'read', 'failed')",
            name='status_valid',
        ),
        CheckConstraint('retry_count >= 0', name='retry_count_non_negative'),
        Index(
            'uq_messages_account_wa_message_id_not_null',
            'account_id',
            'wa_message_id',
            unique=True,
            sqlite_where=text('wa_message_id IS NOT NULL'),
            postgresql_where=text('wa_message_id IS NOT NULL'),
        ),
        Index(
            'ix_messages_conversation_created_id',
            'conversation_id',
            text('created_at DESC'),
            text('id DESC'),
        ),
        Index('ix_messages_account_status_created', 'account_id', 'status', 'created_at'),
    )

    id: Mapped[str] = mapped_column(String(UUID_LENGTH), primary_key=True, default=new_uuid)
    account_id: Mapped[str] = mapped_column(
        String(UUID_LENGTH),
        ForeignKey('whatsapp_accounts.id', ondelete='CASCADE'),
        nullable=False,
    )
    conversation_id: Mapped[str] = mapped_column(
        String(UUID_LENGTH),
        ForeignKey('conversations.id', ondelete='CASCADE'),
        nullable=False,
    )
    contact_id: Mapped[str | None] = mapped_column(
        String(UUID_LENGTH), ForeignKey('contacts.id', ondelete='SET NULL')
    )
    wa_message_id: Mapped[str | None] = mapped_column(String(255))
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_jid: Mapped[str | None] = mapped_column(String(255))
    message_type: Mapped[str] = mapped_column(String(32), nullable=False, default='text')
    content: Mapped[str | None] = mapped_column(Text)
    media_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    quoted_message_id: Mapped[str | None] = mapped_column(
        String(UUID_LENGTH), ForeignKey('messages.id', ondelete='SET NULL')
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIRuntimeSetting(TimestampMixin, Base):
    __tablename__ = 'ai_runtime_settings'
    __table_args__ = (
        CheckConstraint('timeout_seconds > 0', name='timeout_seconds_positive'),
        CheckConstraint('max_retries >= 0', name='max_retries_non_negative'),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default='global')
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default='wendingai')
    base_url: Mapped[str] = mapped_column(
        String(2048), nullable=False, default='https://wendingai.future1.us/v1'
    )
    default_model: Mapped[str] = mapped_column(
        String(255), nullable=False, default='gpt-5.3-codex-spark'
    )
    api_key_ciphertext: Mapped[str | None] = mapped_column(Text)
    api_key_hint: Mapped[str | None] = mapped_column(String(64))
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    updated_by: Mapped[str | None] = mapped_column(String(255))


class ContactAIOverride(Base):
    __tablename__ = 'contact_ai_overrides'

    account_id: Mapped[str] = mapped_column(
        String(UUID_LENGTH),
        ForeignKey('whatsapp_accounts.id', ondelete='CASCADE'),
        primary_key=True,
    )
    contact_id: Mapped[str] = mapped_column(
        String(UUID_LENGTH), ForeignKey('contacts.id', ondelete='CASCADE'), primary_key=True
    )
    model: Mapped[str | None] = mapped_column(String(255))
    system_prompt: Mapped[str | None] = mapped_column(Text)
    reply_style: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(32))
    auto_reply_enabled: Mapped[bool | None] = mapped_column(Boolean)


class WhatsAppEvent(Base):
    __tablename__ = 'whatsapp_events'
    __table_args__ = (
        UniqueConstraint('event_id', name='uq_whatsapp_events_event_id'),
        CheckConstraint("status IN ('received', 'processed', 'failed')", name='status_valid'),
        Index('ix_whatsapp_events_account_status_occurred', 'account_id', 'status', 'occurred_at'),
    )

    id: Mapped[str] = mapped_column(String(UUID_LENGTH), primary_key=True, default=new_uuid)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    account_id: Mapped[str] = mapped_column(
        String(UUID_LENGTH),
        ForeignKey('whatsapp_accounts.id', ondelete='CASCADE'),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='received')
    error: Mapped[str | None] = mapped_column(Text)


class OutboxMessage(TimestampMixin, Base):
    __tablename__ = 'outbox_messages'
    __table_args__ = (
        UniqueConstraint('message_id', name='uq_outbox_messages_message_id'),
        UniqueConstraint('idempotency_key', name='uq_outbox_messages_idempotency_key'),
        CheckConstraint(
            "status IN ('pending', 'claimed', 'completed', 'failed', 'dead')",
            name='status_valid',
        ),
        CheckConstraint('attempts >= 0', name='attempts_non_negative'),
        Index('ix_outbox_messages_status_available', 'status', 'available_at'),
        Index(
            'ix_outbox_messages_account_status_available',
            'account_id',
            'status',
            'available_at',
        ),
        Index('ix_outbox_messages_lease_expires', 'lease_expires_at'),
    )

    id: Mapped[str] = mapped_column(String(UUID_LENGTH), primary_key=True, default=new_uuid)
    message_id: Mapped[str] = mapped_column(
        String(UUID_LENGTH), ForeignKey('messages.id', ondelete='CASCADE'), nullable=False
    )
    account_id: Mapped[str] = mapped_column(
        String(UUID_LENGTH),
        ForeignKey('whatsapp_accounts.id', ondelete='CASCADE'),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='pending')
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


__all__ = [
    'AIProfile',
    'AIRuntimeSetting',
    'Contact',
    'ContactAIOverride',
    'Conversation',
    'Message',
    'OutboxMessage',
    'WhatsAppAccount',
    'WhatsAppEvent',
]
