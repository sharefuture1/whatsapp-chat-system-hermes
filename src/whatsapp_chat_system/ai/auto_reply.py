from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from whatsapp_chat_system.ai.job_repository import AnalysisJobRepository
from whatsapp_chat_system.db.models import Conversation, ContactAIOverride, Message, WhatsAppAccount


@dataclass(frozen=True)
class AutoReplyDecision:
    enabled: bool
    reason: str


def decide_auto_reply(account: WhatsAppAccount, conversation: Conversation, *, contact_enabled: bool | None) -> AutoReplyDecision:
    if not account.enabled:
        return AutoReplyDecision(False, 'account_disabled')
    if account.status != 'online':
        return AutoReplyDecision(False, 'account_offline')
    if account.auto_reply_mode != 'auto':
        return AutoReplyDecision(False, 'account_policy_disabled')
    if conversation.ai_mode != 'auto':
        return AutoReplyDecision(False, 'conversation_policy_disabled')
    if contact_enabled is False:
        return AutoReplyDecision(False, 'contact_policy_disabled')
    return AutoReplyDecision(True, 'enabled')


def enqueue_for_inbound_message(session: Session, account: WhatsAppAccount, conversation: Conversation, message: Message) -> str | None:
    """Create one durable auto-reply analysis job; never call the provider here."""
    if message.direction != 'inbound' or not message.wa_message_id:
        return None
    override = session.scalar(select(ContactAIOverride).where(
        ContactAIOverride.account_id == account.id,
        ContactAIOverride.contact_id == conversation.contact_id,
    )) if conversation.contact_id else None
    decision = decide_auto_reply(account, conversation, contact_enabled=override.auto_reply_enabled if override else None)
    if not decision.enabled:
        return None
    source = json.dumps({'message_id': message.id, 'content': message.content or '', 'policy': account.auto_reply_mode}, sort_keys=True)
    input_hash = hashlib.sha256(source.encode()).hexdigest()
    key = f'auto-reply:{message.wa_message_id}:{account.auto_reply_mode}'
    job = AnalysisJobRepository(session).enqueue(
        account_id=account.id,
        job_type='auto_reply',
        idempotency_key=key,
        input_hash=input_hash,
        contact_id=conversation.contact_id,
        conversation_id=conversation.id,
        priority=10,
        max_attempts=6,
        max_queued_per_account=100,
    )
    return job.id
