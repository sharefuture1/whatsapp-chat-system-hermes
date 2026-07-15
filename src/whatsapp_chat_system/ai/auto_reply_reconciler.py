from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, aliased

from .auto_reply import enqueue_for_inbound_message
from ..db.models import Conversation, Message, WhatsAppAccount


@dataclass(frozen=True)
class AutoReplyReconcilerConfig:
    lookback_hours: int = 72
    batch_size: int = 20


class AutoReplyReconciler:
    def __init__(self, session_factory: Callable[[], Session], *, config: AutoReplyReconcilerConfig | None = None) -> None:
        self.session_factory = session_factory
        self.config = config or AutoReplyReconcilerConfig()
        self.last_heartbeat: datetime | None = None
        self.last_error: str | None = None
        self.enqueued = 0
        self.scanned = 0

    def run_once(self) -> bool:
        self.last_heartbeat = datetime.now(timezone.utc)
        cutoff = self.last_heartbeat - timedelta(hours=self.config.lookback_hours)
        with self.session_factory() as session:
            inbound = aliased(Message)
            outbound = aliased(Message)
            candidates = session.execute(
                select(inbound, Conversation, WhatsAppAccount)
                .join(Conversation, Conversation.id == inbound.conversation_id)
                .join(WhatsAppAccount, WhatsAppAccount.id == inbound.account_id)
                .where(
                    inbound.direction == 'inbound',
                    inbound.message_type == 'text',
                    func.trim(func.coalesce(inbound.content, '')) != '',
                    func.coalesce(inbound.occurred_at, inbound.created_at) >= cutoff,
                    ~exists(select(outbound.id).where(
                        outbound.conversation_id == inbound.conversation_id,
                        outbound.direction == 'outbound',
                        func.coalesce(outbound.occurred_at, outbound.created_at) > func.coalesce(inbound.occurred_at, inbound.created_at),
                    )),
                )
                .order_by(func.coalesce(inbound.occurred_at, inbound.created_at).asc())
                .limit(self.config.batch_size)
            ).all()
            if not candidates:
                return False
            created = 0
            for message, conversation, account in candidates:
                self.scanned += 1
                job_id = enqueue_for_inbound_message(session, account, conversation, message)
                if job_id:
                    created += 1
            session.commit()
            self.enqueued += created
            return created > 0

    def health(self) -> dict[str, Any]:
        return {
            'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            'last_error': self.last_error,
            'enqueued': self.enqueued,
            'scanned': self.scanned,
            'lookback_hours': self.config.lookback_hours,
        }
