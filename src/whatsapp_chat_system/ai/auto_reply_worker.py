from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import select

from .ai.job_repository import AnalysisJobRepository, JobLease, claim_next_committed
from .ai.provider import AIProvider, AIProviderError
from .ai.service import AIService
from .db.models import Conversation, Message, WhatsAppAccount
from .outbox import enqueue_outbox_message
from .settings import AISettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AutoReplyWorkerConfig:
    lease_seconds: int = 120
    max_active: int = 4
    poll_seconds: float = 2.0
    context_messages: int = 10


class AutoReplyWorker:
    """Durable AI -> Outbox worker. It never depends on a browser request."""

    def __init__(self, session_factory: Callable, settings_manager: Any, *, worker_id: str | None = None, config: AutoReplyWorkerConfig | None = None, provider_factory: Callable[[AISettings], AIProvider] | None = None) -> None:
        self.session_factory = session_factory
        self.settings_manager = settings_manager
        self.worker_id = worker_id or f"ai-auto-reply-{uuid4()}"
        self.config = config or AutoReplyWorkerConfig()
        self.provider_factory = provider_factory
        self.last_heartbeat: datetime | None = None
        self.last_error: str | None = None
        self.processed = 0
        self.failed = 0

    def _settings(self) -> AISettings:
        return AISettings(
            base_url=self.settings_manager.effective_base_url,
            api_key=self.settings_manager.effective_api_key,
            default_model=self.settings_manager.effective_model,
            timeout_seconds=self.settings_manager.effective_timeout,
            max_retries=self.settings_manager.effective_retries,
        )

    def _provider(self, settings: AISettings) -> AIProvider:
        if self.provider_factory is not None:
            return self.provider_factory(settings)
        from .ai.provider import WendingAIProvider
        return WendingAIProvider(settings)

    def run_once(self) -> bool:
        self.last_heartbeat = datetime.now(timezone.utc)
        lease = claim_next_committed(
            self.session_factory,
            worker_id=self.worker_id,
            lease_seconds=self.config.lease_seconds,
            max_active_global=self.config.max_active,
            max_active_per_account=self.config.max_active,
        )
        if lease is None:
            return False
        try:
            self._process(lease)
            self.processed += 1
        except AIProviderError as exc:
            self.failed += 1
            self.last_error = exc.code
            self._fail(lease, exc.code, retryable=exc.retryable)
        except Exception as exc:  # worker boundary: one job must not kill the loop
            self.failed += 1
            self.last_error = type(exc).__name__
            logger.exception("AI auto reply job failed", extra={"job_id": lease.id})
            self._fail(lease, "auto_reply_worker_error", retryable=True)
        return True

    def _process(self, lease: JobLease) -> None:
        with self.session_factory() as session:
            repo = AnalysisJobRepository(session)
            job = repo.start(lease.account_id, lease.id, self.worker_id, lease.version)
            session.commit()
            source_id = lease.idempotency_key.removeprefix("auto-reply:").rsplit(":", 1)[0]
            message = session.scalar(select(Message).where(
                Message.account_id == lease.account_id,
                Message.wa_message_id == source_id,
            ))
            account = session.get(WhatsAppAccount, lease.account_id)
            conversation = session.get(Conversation, lease.conversation_id) if lease.conversation_id else None
            if not message or not account or not conversation or not account.enabled or account.status != "online" or account.auto_reply_mode != "auto" or conversation.ai_mode != "auto":
                repo.cancel(lease.account_id, lease.id, job.version)
                session.commit()
                return
            recent = list(session.scalars(select(Message).where(
                Message.conversation_id == conversation.id,
            ).order_by(Message.occurred_at.desc(), Message.id.desc()).limit(self.config.context_messages)).all())
            recent.reverse()
            messages = [{"role": "user" if item.direction == "inbound" else "assistant", "content": item.content or ""} for item in recent if item.content]
            messages.append({"role": "system", "content": "Reply concisely in the user's language. Return only the reply text. Do not claim actions you did not take."})
            service = AIService(self._provider(self._settings()), self._settings())
            result = service.chat(messages=messages).result.content.strip()
            if not result:
                raise AIProviderError(code='empty_ai_reply', message='AI returned an empty reply', retryable=True)
            key = f"auto-reply-outbox:{lease.id}"
            enqueue_outbox_message(session, conversation, text=result, idempotency_key=key)
            repo.complete(lease.account_id, lease.id, self.worker_id, job.version, job.input_hash)
            session.commit()

    def _fail(self, lease: JobLease, code: str, *, retryable: bool) -> None:
        with self.session_factory() as session:
            repo = AnalysisJobRepository(session)
            try:
                repo.fail(lease.account_id, lease.id, self.worker_id, lease.version, code, 30 if retryable else 0)
                session.commit()
            except Exception:
                session.rollback()
                logger.exception("Unable to persist AI job failure", extra={"job_id": lease.id})

    def health(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "last_error": self.last_error,
            "processed": self.processed,
            "failed": self.failed,
        }
