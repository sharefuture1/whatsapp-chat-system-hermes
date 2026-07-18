"""PERF-006：AutoReplyWorker 不得在持有 DB session 期间调用 AI Provider。"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine

from whatsapp_chat_system.ai.auto_reply_reconciler import AutoReplyReconciler
from whatsapp_chat_system.ai.auto_reply_worker import AutoReplyWorker
from whatsapp_chat_system.ai.provider import AIResult
from whatsapp_chat_system.db import Base, create_session_factory
from whatsapp_chat_system.db.models import (
    AnalysisJob,
    Contact,
    Conversation,
    Message,
    OutboxMessage,
    WhatsAppAccount,
)


def _id() -> str:
    return str(uuid4())


class _SettingsManager:
    effective_base_url = "https://unit.test/v1"
    effective_api_key = "unit-test-secret"
    effective_model = "test-model"
    effective_timeout = 5
    effective_retries = 0


class _FakeProvider:
    def __init__(self, on_chat):
        self.on_chat = on_chat

    def chat(self, *, model, messages, response_format=None, temperature=None):
        content = self.on_chat()
        return AIResult(
            content=content,
            model=model,
            request_id=None,
            usage={},
            latency_ms=1,
        )


def _seed_auto_reply_job(factory):
    now = datetime.now(timezone.utc)
    with factory() as session:
        account = WhatsAppAccount(
            id=_id(),
            name="acct",
            status="online",
            session_ref="account:test",
            enabled=True,
            auto_reply_mode="auto",
        )
        contact = Contact(id=_id(), account_id=account.id, remote_jid="123@lid")
        conversation = Conversation(
            id=_id(),
            account_id=account.id,
            contact_id=contact.id,
            remote_jid="123@lid",
            ai_mode="auto",
        )
        inbound = Message(
            id=_id(),
            account_id=account.id,
            conversation_id=conversation.id,
            contact_id=contact.id,
            wa_message_id="wamid-1",
            direction="inbound",
            message_type="text",
            content="你好",
            status="received",
            occurred_at=now - timedelta(minutes=5),
        )
        session.add_all([account, contact, conversation, inbound])
        session.commit()
        ids = (account.id, conversation.id)
    assert AutoReplyReconciler(factory).run_once() is True
    return ids


def _tracking_factory(factory, counter):
    def make():
        session = factory()
        counter["open"] += 1
        original_close = session.close
        closed = {"done": False}

        def close():
            if not closed["done"]:
                closed["done"] = True
                counter["open"] -= 1
            original_close()

        session.close = close
        return session

    return make


def test_worker_holds_no_session_during_ai_call(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    _seed_auto_reply_job(factory)

    counter = {"open": 0, "during_ai": None}

    def on_chat():
        counter["during_ai"] = counter["open"]
        return "好的，请稍等"

    worker = AutoReplyWorker(
        _tracking_factory(factory, counter),
        _SettingsManager(),
        provider_factory=lambda settings: _FakeProvider(on_chat),
    )
    assert worker.run_once() is True

    assert counter["during_ai"] == 0, "AI 调用期间不得持有任何打开的 DB session"
    with factory() as session:
        outbox = session.query(OutboxMessage).all()
        assert len(outbox) == 1
        job = session.query(AnalysisJob).one()
        assert job.status == "completed"


def test_worker_cancels_when_human_replied_during_ai_call(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'worker-race.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    account_id, conversation_id = _seed_auto_reply_job(factory)

    def on_chat():
        # AI 慢响应期间，客服人工回复了这条消息
        with factory() as session:
            session.add(
                Message(
                    id=_id(),
                    account_id=account_id,
                    conversation_id=conversation_id,
                    wa_message_id="wamid-human",
                    direction="outbound",
                    message_type="text",
                    content="人工已回复",
                    status="sent",
                    occurred_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
        return "AI 的迟到回复"

    worker = AutoReplyWorker(
        factory,
        _SettingsManager(),
        provider_factory=lambda settings: _FakeProvider(on_chat),
    )
    assert worker.run_once() is True

    with factory() as session:
        assert session.query(OutboxMessage).count() == 0, "人工已回复时不得入 Outbox"
        job = session.query(AnalysisJob).one()
        assert job.status == "cancelled"
