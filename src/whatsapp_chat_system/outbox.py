"""Transactional outbound message queue shared by reply, schedule, and broadcast APIs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from whatsapp_chat_system.bridge.client import BridgeError
from whatsapp_chat_system.db.models import Conversation, Message, OutboxMessage
from whatsapp_chat_system.db.session import session_scope

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue_outbox_message(
    session: Session,
    conversation: Conversation,
    *,
    text: str,
    available_at: datetime | None = None,
    idempotency_key: str | None = None,
) -> tuple[Message, OutboxMessage, bool]:
    """Create one durable outbound message and outbox row in the caller transaction.

    Returns ``(message, outbox, created)``. Reusing an idempotency key returns the
    original pair and never inserts a second logical message.
    """

    cleaned_text = text.strip()
    if not cleaned_text:
        raise ValueError("message text must not be empty")
    cleaned_key = (idempotency_key or f"outbox:{uuid4()}").strip()
    if not cleaned_key or len(cleaned_key) > 255:
        raise ValueError("invalid idempotency key")

    existing = session.scalar(
        select(OutboxMessage).where(OutboxMessage.idempotency_key == cleaned_key)
    )
    if existing is not None:
        message = session.get(Message, existing.message_id)
        if message is None:
            raise RuntimeError("outbox references a missing message")
        if message.conversation_id != conversation.id:
            raise ValueError("idempotency key belongs to another conversation")
        return message, existing, False

    message = Message(
        account_id=conversation.account_id,
        conversation_id=conversation.id,
        contact_id=conversation.contact_id,
        direction="outbound",
        sender_jid=None,
        message_type="text",
        content=cleaned_text,
        status="queued",
    )
    session.add(message)
    session.flush()

    outbox = OutboxMessage(
        message_id=message.id,
        account_id=conversation.account_id,
        idempotency_key=cleaned_key,
        status="pending",
        available_at=available_at or utc_now(),
    )
    session.add(outbox)
    session.flush()
    return message, outbox, True


class OutboxDispatcher:
    """Claim, send, retry, and finalize durable outbound messages."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        bridge: Any,
        *,
        worker_id: str | None = None,
        batch_size: int = 20,
        lease_seconds: int = 45,
        max_attempts: int = 6,
    ) -> None:
        self.session_factory = session_factory
        self.bridge = bridge
        self.worker_id = worker_id or f"outbox-{uuid4()}"
        self.batch_size = max(1, min(batch_size, 100))
        self.lease_seconds = max(10, min(lease_seconds, 600))
        self.max_attempts = max(1, min(max_attempts, 20))

    def run_once(self) -> int:
        claimed = self._claim_batch()
        for outbox_id in claimed:
            self._deliver(outbox_id)
        return len(claimed)

    def _claim_batch(self) -> list[str]:
        now = utc_now()
        claimed_ids: list[str] = []
        with session_scope(self.session_factory) as session:
            expired = session.scalars(
                select(OutboxMessage).where(
                    OutboxMessage.status == "claimed",
                    OutboxMessage.lease_expires_at.is_not(None),
                    OutboxMessage.lease_expires_at <= now,
                )
            ).all()
            for item in expired:
                item.status = "pending"
                item.lease_owner = None
                item.lease_expires_at = None

            statement = (
                select(OutboxMessage)
                .where(
                    OutboxMessage.status == "pending",
                    OutboxMessage.available_at <= now,
                    or_(
                        OutboxMessage.lease_expires_at.is_(None),
                        OutboxMessage.lease_expires_at <= now,
                    ),
                )
                .order_by(OutboxMessage.available_at.asc(), OutboxMessage.id.asc())
                .limit(self.batch_size)
                .with_for_update(skip_locked=True)
            )
            for item in session.scalars(statement).all():
                item.status = "claimed"
                item.attempts += 1
                item.lease_owner = self.worker_id
                item.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
                claimed_ids.append(item.id)
        return claimed_ids

    def _deliver(self, outbox_id: str) -> None:
        with self.session_factory() as session:
            outbox = session.get(OutboxMessage, outbox_id)
            if (
                outbox is None
                or outbox.status != "claimed"
                or outbox.lease_owner != self.worker_id
            ):
                return
            message = session.get(Message, outbox.message_id)
            conversation = (
                session.get(Conversation, message.conversation_id) if message else None
            )
            if message is None or conversation is None or conversation.deleted_at is not None:
                self._finalize_failure(
                    outbox_id,
                    code="invalid_outbox_reference",
                    message="Outbound message or conversation no longer exists",
                    retryable=False,
                )
                return
            account_id = message.account_id
            chat_id = conversation.remote_jid
            text = message.content or ""
            idempotency_key = outbox.idempotency_key

        try:
            sent = self.bridge.send(
                account_id,
                chat_id=chat_id,
                text=text,
                idempotency_key=idempotency_key,
            )
            platform_message_id = str(sent.get("message_id") or "").strip()
            if not platform_message_id:
                raise BridgeError(
                    "missing_message_id",
                    "Bridge response did not include a message ID",
                    retryable=True,
                )
        except BridgeError as exc:
            self._finalize_failure(
                outbox_id,
                code=exc.code,
                message=exc.message,
                retryable=exc.retryable,
            )
            return
        except Exception as exc:  # pragma: no cover - defensive worker boundary
            logger.exception("Unexpected outbox delivery failure", extra={"outbox_id": outbox_id})
            self._finalize_failure(
                outbox_id,
                code="outbox_delivery_error",
                message=str(exc) or "Unexpected outbox delivery error",
                retryable=True,
            )
            return

        now = utc_now()
        with session_scope(self.session_factory) as session:
            outbox = session.get(OutboxMessage, outbox_id)
            if outbox is None or outbox.status != "claimed":
                return
            message = session.get(Message, outbox.message_id)
            if message is None:
                outbox.status = "dead"
                outbox.last_error = "message missing after send"
                outbox.lease_owner = None
                outbox.lease_expires_at = None
                return
            conversation = session.get(Conversation, message.conversation_id)
            message.wa_message_id = platform_message_id
            message.status = "sent"
            message.sent_at = now
            message.occurred_at = now
            message.error_code = None
            message.error_message = None
            outbox.status = "completed"
            outbox.last_error = None
            outbox.lease_owner = None
            outbox.lease_expires_at = None
            if conversation is not None:
                conversation.last_message_preview = message.content or ""
                conversation.last_message_at = now

    def _finalize_failure(
        self,
        outbox_id: str,
        *,
        code: str,
        message: str,
        retryable: bool,
    ) -> None:
        now = utc_now()
        with session_scope(self.session_factory) as session:
            outbox = session.get(OutboxMessage, outbox_id)
            if outbox is None or outbox.status != "claimed":
                return
            outbound = session.get(Message, outbox.message_id)
            terminal = not retryable or outbox.attempts >= self.max_attempts
            outbox.status = "dead" if terminal else "pending"
            outbox.available_at = now + timedelta(seconds=self._retry_delay(outbox.attempts))
            outbox.last_error = f"{code}: {message}"[:4000]
            outbox.lease_owner = None
            outbox.lease_expires_at = None
            if outbound is not None:
                outbound.retry_count = outbox.attempts
                outbound.error_code = code
                outbound.error_message = message[:4000]
                outbound.status = "failed" if terminal else "queued"

    @staticmethod
    def _retry_delay(attempts: int) -> int:
        return min(300, 2 ** min(max(attempts, 1), 8))
