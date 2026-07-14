from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
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
    last_event_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


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
    profile_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


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
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
        UniqueConstraint('account_id', 'event_id', name='uq_whatsapp_events_account_event_id'),
        CheckConstraint("status IN ('received', 'processed', 'failed')", name='status_valid'),
        Index('ix_whatsapp_events_account_status_occurred', 'account_id', 'status', 'occurred_at'),
        Index('ix_whatsapp_events_account_sequence', 'account_id', 'sequence'),
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
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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


class MessageTranslation(TimestampMixin, Base):
    __tablename__ = 'message_translations'
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'running', 'completed', 'failed', 'dead')", name='status_valid'),
        Index('ix_message_translations_conversation_status_updated', 'conversation_id', 'status', 'updated_at'),
        Index('ix_message_translations_account_status_retry', 'account_id', 'status', 'retry_after'),
        UniqueConstraint('message_id', 'target_lang', 'source_text_hash', name='uq_message_translations_message_target_hash'),
    )

    id: Mapped[str] = mapped_column(String(UUID_LENGTH), primary_key=True, default=new_uuid)
    account_id: Mapped[str] = mapped_column(
        String(UUID_LENGTH), ForeignKey('whatsapp_accounts.id', ondelete='CASCADE'), nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(
        String(UUID_LENGTH), ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False
    )
    message_id: Mapped[str] = mapped_column(
        String(UUID_LENGTH), ForeignKey('messages.id', ondelete='CASCADE'), nullable=False
    )
    source_text: Mapped[str | None] = mapped_column(Text)
    source_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_lang: Mapped[str | None] = mapped_column(String(32))
    target_lang: Mapped[str] = mapped_column(String(32), nullable=False, default='zh-CN')
    translated_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='pending')
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(255))
    context_window_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    batch_id: Mapped[str | None] = mapped_column(String(UUID_LENGTH), ForeignKey('translation_batches.id', ondelete='SET NULL'))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TranslationBatch(TimestampMixin, Base):
    __tablename__ = 'translation_batches'
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'claimed', 'running', 'completed', 'failed', 'dead')", name='status_valid'),
        Index('ix_translation_batches_account_status_created', 'account_id', 'status', 'created_at'),
        Index('ix_translation_batches_account_status_retry', 'account_id', 'status', 'retry_after'),
    )

    id: Mapped[str] = mapped_column(String(UUID_LENGTH), primary_key=True, default=new_uuid)
    account_id: Mapped[str] = mapped_column(
        String(UUID_LENGTH), ForeignKey('whatsapp_accounts.id', ondelete='CASCADE'), nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(
        String(UUID_LENGTH), ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False
    )
    anchor_message_id: Mapped[str] = mapped_column(
        String(UUID_LENGTH), ForeignKey('messages.id', ondelete='CASCADE'), nullable=False
    )
    target_lang: Mapped[str] = mapped_column(String(32), nullable=False, default='zh-CN')
    window_size: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='pending')
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str | None] = mapped_column(String(255))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationSegment(TimestampMixin, Base):
    __tablename__ = 'conversation_segments'
    __table_args__ = (
        UniqueConstraint('account_id', 'conversation_id', 'start_message_id', 'end_message_id', 'analyzer_version', 'content_hash', name='uq_conversation_segments_scope_range_analyzer_hash'),
        CheckConstraint("status IN ('pending', 'completed', 'failed', 'stale')", name='conversation_segments_status_valid'),
        Index('ix_conversation_segments_account_conversation_end_cursor', 'account_id', 'conversation_id', text('end_cursor DESC')),
    )
    id: Mapped[str] = mapped_column(String(UUID_LENGTH), primary_key=True, default=new_uuid)
    account_id: Mapped[str] = mapped_column(String(UUID_LENGTH), ForeignKey('whatsapp_accounts.id', ondelete='CASCADE'), nullable=False)
    contact_id: Mapped[str | None] = mapped_column(String(UUID_LENGTH), ForeignKey('contacts.id', ondelete='SET NULL'))
    conversation_id: Mapped[str] = mapped_column(String(UUID_LENGTH), ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False)
    start_message_id: Mapped[str] = mapped_column(String(UUID_LENGTH), ForeignKey('messages.id', ondelete='CASCADE'), nullable=False)
    end_message_id: Mapped[str] = mapped_column(String(UUID_LENGTH), ForeignKey('messages.id', ondelete='CASCADE'), nullable=False)
    start_cursor: Mapped[str | None] = mapped_column(String(255))
    end_cursor: Mapped[str | None] = mapped_column(String(255))
    analyzer_version: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='pending')


class ConversationSummary(TimestampMixin, Base):
    __tablename__ = 'conversation_summaries'
    __table_args__ = (
        UniqueConstraint('account_id', 'conversation_id', 'summary_type', 'analyzer_version', 'input_hash', name='uq_conversation_summaries_scope_type_analyzer_input'),
        CheckConstraint("summary_type IN ('segment', 'daily', 'weekly', 'rolling')", name='conversation_summaries_type_valid'),
        CheckConstraint("status IN ('pending', 'completed', 'failed', 'stale', 'superseded')", name='conversation_summaries_status_valid'),
        CheckConstraint('version >= 1', name='conversation_summaries_version_positive'),
        Index('ix_conversation_summaries_account_contact_status_updated', 'account_id', 'contact_id', 'status', text('updated_at DESC')),
    )
    id: Mapped[str] = mapped_column(String(UUID_LENGTH), primary_key=True, default=new_uuid)
    account_id: Mapped[str] = mapped_column(String(UUID_LENGTH), ForeignKey('whatsapp_accounts.id', ondelete='CASCADE'), nullable=False)
    contact_id: Mapped[str | None] = mapped_column(String(UUID_LENGTH), ForeignKey('contacts.id', ondelete='SET NULL'))
    conversation_id: Mapped[str] = mapped_column(String(UUID_LENGTH), ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False)
    segment_id: Mapped[str | None] = mapped_column(String(UUID_LENGTH), ForeignKey('conversation_segments.id', ondelete='SET NULL'))
    summary_type: Mapped[str] = mapped_column(String(32), nullable=False)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    analyzer_version: Mapped[str] = mapped_column(String(128), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='pending')
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_summary_id: Mapped[str | None] = mapped_column(String(UUID_LENGTH), ForeignKey('conversation_summaries.id', ondelete='SET NULL'))
    source_cursor_start: Mapped[str | None] = mapped_column(String(255))
    source_cursor_end: Mapped[str | None] = mapped_column(String(255))


class ProfileClaim(TimestampMixin, Base):
    __tablename__ = 'profile_claims'
    __table_args__ = (
        UniqueConstraint('account_id', 'contact_id', 'claim_key', 'version', name='uq_profile_claims_scope_key_version'),
        CheckConstraint("source_type IN ('explicit_fact', 'observed_pattern', 'model_inference', 'manual')", name='profile_claims_source_type_valid'),
        CheckConstraint("status IN ('proposed', 'accepted', 'rejected', 'superseded', 'expired')", name='profile_claims_status_valid'),
        CheckConstraint("sensitivity IN ('normal', 'private', 'restricted')", name='profile_claims_sensitivity_valid'),
        CheckConstraint('confidence >= 0 AND confidence <= 1', name='profile_claims_confidence_range'),
        CheckConstraint('version >= 1', name='profile_claims_version_positive'),
        Index('ix_profile_claims_account_contact_status_key_updated', 'account_id', 'contact_id', 'status', 'claim_key', text('updated_at DESC')),
    )
    id: Mapped[str] = mapped_column(String(UUID_LENGTH), primary_key=True, default=new_uuid)
    account_id: Mapped[str] = mapped_column(String(UUID_LENGTH), ForeignKey('whatsapp_accounts.id', ondelete='CASCADE'), nullable=False)
    contact_id: Mapped[str] = mapped_column(String(UUID_LENGTH), ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String(UUID_LENGTH), ForeignKey('conversations.id', ondelete='SET NULL'))
    claim_key: Mapped[str] = mapped_column(String(255), nullable=False)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(32), nullable=False, default='normal')
    manual_lock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    analyzer_version: Mapped[str] = mapped_column(String(128), nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str | None] = mapped_column(String(255))


class ProfileClaimEvidence(Base):
    __tablename__ = 'profile_claim_evidence'
    __table_args__ = (
        UniqueConstraint('account_id', 'claim_id', 'evidence_type', 'evidence_id', name='uq_profile_claim_evidence_scope_claim_type_evidence'),
        CheckConstraint("evidence_type IN ('message', 'summary', 'manual_note')", name='profile_claim_evidence_type_valid'),
        Index('ix_profile_claim_evidence_account_contact_claim', 'account_id', 'contact_id', 'claim_id'),
    )
    id: Mapped[str] = mapped_column(String(UUID_LENGTH), primary_key=True, default=new_uuid)
    account_id: Mapped[str] = mapped_column(String(UUID_LENGTH), ForeignKey('whatsapp_accounts.id', ondelete='CASCADE'), nullable=False)
    contact_id: Mapped[str] = mapped_column(String(UUID_LENGTH), ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String(UUID_LENGTH), ForeignKey('conversations.id', ondelete='SET NULL'))
    claim_id: Mapped[str] = mapped_column(String(UUID_LENGTH), ForeignKey('profile_claims.id', ondelete='CASCADE'), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String(255), nullable=False)
    excerpt_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class ProfileSnapshot(Base):
    __tablename__ = 'profile_snapshots'
    __table_args__ = (
        UniqueConstraint('account_id', 'contact_id', 'version', name='uq_profile_snapshots_scope_version'),
        CheckConstraint('version >= 1', name='profile_snapshots_version_positive'),
        Index('uq_profile_snapshots_one_current', 'account_id', 'contact_id', unique=True, sqlite_where=text('is_current = 1'), postgresql_where=text('is_current IS TRUE')),
        Index('ix_profile_snapshots_account_contact_current', 'account_id', 'contact_id', 'is_current'),
    )
    id: Mapped[str] = mapped_column(String(UUID_LENGTH), primary_key=True, default=new_uuid)
    account_id: Mapped[str] = mapped_column(String(UUID_LENGTH), ForeignKey('whatsapp_accounts.id', ondelete='CASCADE'), nullable=False)
    contact_id: Mapped[str] = mapped_column(String(UUID_LENGTH), ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String(UUID_LENGTH), ForeignKey('conversations.id', ondelete='SET NULL'))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_claim_cursor: Mapped[str | None] = mapped_column(String(255))
    source_claim_versions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    source_profile_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class MemoryItem(TimestampMixin, Base):
    __tablename__ = 'memory_items'
    __table_args__ = (
        UniqueConstraint('account_id', 'contact_id', 'memory_key', name='uq_memory_items_scope_key'),
        CheckConstraint("status IN ('active', 'rejected', 'expired', 'deleted')", name='memory_items_status_valid'),
        CheckConstraint('importance >= 0 AND importance <= 1', name='memory_items_importance_range'),
        Index('ix_memory_items_account_contact_status_updated', 'account_id', 'contact_id', 'status', text('updated_at DESC')),
        Index('ix_memory_items_account_contact_status_expires', 'account_id', 'contact_id', 'status', 'expires_at'),
    )
    id: Mapped[str] = mapped_column(String(UUID_LENGTH), primary_key=True, default=new_uuid)
    account_id: Mapped[str] = mapped_column(String(UUID_LENGTH), ForeignKey('whatsapp_accounts.id', ondelete='CASCADE'), nullable=False)
    contact_id: Mapped[str] = mapped_column(String(UUID_LENGTH), ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String(UUID_LENGTH), ForeignKey('conversations.id', ondelete='SET NULL'))
    memory_key: Mapped[str] = mapped_column(String(255), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(64), nullable=False)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    search_text: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list[Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='active')
    importance: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal('0.5'))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding_ref: Mapped[str | None] = mapped_column(String(255))
    source_claim_id: Mapped[str | None] = mapped_column(String(UUID_LENGTH), ForeignKey('profile_claims.id', ondelete='SET NULL'))


class AnalysisJob(TimestampMixin, Base):
    __tablename__ = 'analysis_jobs'
    __table_args__ = (
        UniqueConstraint('account_id', 'idempotency_key', name='uq_analysis_jobs_scope_idempotency'),
        CheckConstraint("status IN ('pending', 'claimed', 'running', 'retry', 'completed', 'failed', 'dead', 'cancelled')", name='analysis_jobs_status_valid'),
        CheckConstraint('attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts', name='analysis_jobs_attempts_valid'),
        CheckConstraint('priority >= 0', name='analysis_jobs_priority_non_negative'),
        CheckConstraint('progress_total >= 0 AND progress_completed >= 0 AND progress_failed >= 0', name='analysis_jobs_progress_non_negative'),
        CheckConstraint('budget_tokens >= 0 AND budget_cost >= 0', name='analysis_jobs_budget_non_negative'),
        CheckConstraint('version >= 1', name='analysis_jobs_version_positive'),
        Index('ix_analysis_jobs_account_status_priority_available_created', 'account_id', 'status', text('priority DESC'), 'available_at', 'created_at'),
        Index('ix_analysis_jobs_parent_status', 'parent_job_id', 'status'),
        Index('ix_analysis_jobs_status_lease_expires', 'status', 'lease_expires_at'),
    )
    id: Mapped[str] = mapped_column(String(UUID_LENGTH), primary_key=True, default=new_uuid)
    account_id: Mapped[str] = mapped_column(String(UUID_LENGTH), ForeignKey('whatsapp_accounts.id', ondelete='CASCADE'), nullable=False)
    contact_id: Mapped[str | None] = mapped_column(String(UUID_LENGTH), ForeignKey('contacts.id', ondelete='SET NULL'))
    conversation_id: Mapped[str | None] = mapped_column(String(UUID_LENGTH), ForeignKey('conversations.id', ondelete='SET NULL'))
    parent_job_id: Mapped[str | None] = mapped_column(String(UUID_LENGTH), ForeignKey('analysis_jobs.id', ondelete='CASCADE'))
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='pending')
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    budget_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    budget_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal('0'))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


__all__ = [
    'AIProfile',
    'AIRuntimeSetting',
    'AnalysisJob',
    'Contact',
    'ContactAIOverride',
    'Conversation',
    'ConversationSegment',
    'ConversationSummary',
    'MemoryItem',
    'Message',
    'OutboxMessage',
    'ProfileClaim',
    'ProfileClaimEvidence',
    'ProfileSnapshot',
    'WhatsAppAccount',
    'WhatsAppEvent',
]
