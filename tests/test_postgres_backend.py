"""PostgreSQL 集成测试（默认跳过，需显式提供连接串）。

本地开发通常只有 SQLite，因此这里用 opt-in 方式：
在服务器或 CI 上执行

    TEST_DATABASE_URL="postgresql://user:pass@host:5432/testdb" \
        pytest tests/test_postgres_backend.py -v

即可一次性验证：迁移链、索引/约束创建、事件幂等、outbox 抢占、
以及本项目的关键查询在真实 PostgreSQL 上的行为。

注意：测试会 DROP 目标库中的本表，请务必指向专用的测试库。
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from whatsapp_chat_system.db.base import Base
from whatsapp_chat_system.db.models import (
    Contact,
    Conversation,
    Message,
    OutboxMessage,
    WhatsAppAccount,
)
from whatsapp_chat_system.db.url import database_backend, normalize_database_url
from whatsapp_chat_system.events.whatsapp import (
    WhatsAppEventEnvelope,
    WhatsAppEventService,
)
from whatsapp_chat_system.outbox import OutboxDispatcher, enqueue_outbox_message

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="需要设置 TEST_DATABASE_URL 指向一个专用 PostgreSQL 测试库",
)


@pytest.fixture(scope="module")
def engine():
    url = normalize_database_url(TEST_DATABASE_URL)
    assert database_backend(url) == "postgresql", (
        f"TEST_DATABASE_URL 必须指向 PostgreSQL，实际为 {database_backend(url)}"
    )
    engine = create_engine(url, pool_pre_ping=True)
    # 从干净状态开始
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def factory(engine):
    session_factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with session_factory() as session:
        session.execute(text("TRUNCATE whatsapp_accounts CASCADE"))
        session.commit()
    yield session_factory


def test_schema_created_with_expected_tables(engine):
    tables = set(inspect(engine).get_table_names())

    assert "whatsapp_accounts" in tables
    assert "messages" in tables
    assert "message_translations" in tables
    assert "outbox_messages" in tables
    assert "analysis_jobs" in tables


def test_driver_is_psycopg(engine):
    assert engine.dialect.name == "postgresql"
    assert engine.dialect.driver == "psycopg"


def test_foreign_keys_are_enforced(factory):
    """SQLite 需要显式 PRAGMA，PostgreSQL 天然强制外键——这里确认约束真的生效。"""

    from sqlalchemy.exc import IntegrityError

    with factory() as session:
        session.add(
            Contact(
                account_id="00000000-0000-0000-0000-000000000000", remote_jid="x@lid"
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_event_ingest_is_idempotent_on_postgres(factory):
    with factory() as session:
        session.add(
            WhatsAppAccount(id="account-a", name="A", session_ref="account:account-a")
        )
        session.commit()

    envelope = WhatsAppEventEnvelope.model_validate(
        {
            "event_id": "evt-pg-1",
            "event_type": "message.upsert",
            "account_id": "account-a",
            "occurred_at": "2026-07-10T00:00:00Z",
            "sequence": 1,
            "payload": {
                "schema_version": 1,
                "wa_message_id": "WA-PG-1",
                "remote_jid": "8551@s.whatsapp.net",
                "sender_jid": "8551@s.whatsapp.net",
                "participant_jid": None,
                "from_me": False,
                "conversation_type": "dm",
                "message_type": "text",
                "timestamp": "2026-07-10T00:00:00Z",
                "text": "hello from postgres",
                "push_name": "Customer",
                "quoted_wa_message_id": None,
                "media": None,
            },
        }
    )

    with factory() as session:
        first = WhatsAppEventService(session).process(envelope)
        session.commit()
    with factory() as session:
        second = WhatsAppEventService(session).process(envelope)
        session.commit()

    assert first is False
    assert second is True
    with factory() as session:
        assert session.scalar(select(Message).where(Message.wa_message_id == "WA-PG-1"))


class _Bridge:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, **kwargs):
        self.sent.append(kwargs.get("text", ""))
        return {"message_id": "wa-id"}


def test_outbox_claim_cas_works_on_postgres(factory):
    """条件 UPDATE（CAS）抢占在 PostgreSQL 上同样互斥。"""

    with factory() as session:
        account = WhatsAppAccount(name="WA", session_ref="sessions/wa")
        session.add(account)
        session.flush()
        contact = Contact(account_id=account.id, remote_jid="p@lid")
        session.add(contact)
        session.flush()
        conversation = Conversation(
            account_id=account.id, contact_id=contact.id, remote_jid="p@lid"
        )
        session.add(conversation)
        session.flush()
        for index in range(6):
            enqueue_outbox_message(
                session,
                conversation,
                text=f"m{index}",
                idempotency_key=f"pg-key-{index}",
            )
        session.commit()

    first = OutboxDispatcher(factory, _Bridge(), worker_id="w-a", batch_size=3)
    second = OutboxDispatcher(factory, _Bridge(), worker_id="w-b", batch_size=3)

    claimed_a = first._claim_batch()
    claimed_b = second._claim_batch()

    assert len(claimed_a) == 3
    assert not set(claimed_a) & set(claimed_b)
    with factory() as session:
        rows = session.scalars(
            select(OutboxMessage).where(OutboxMessage.id.in_(claimed_a))
        ).all()
    assert all(row.lease_owner == "w-a" for row in rows)
    assert all(row.attempts == 1 for row in rows)


def test_row_level_locking_is_available_on_postgres(factory):
    """确认 PostgreSQL 上 FOR UPDATE 真的可用（与 SQLite 的行为差异）。"""

    with factory() as session:
        session.add(
            WhatsAppAccount(
                id="account-lock", name="L", session_ref="account:account-lock"
            )
        )
        session.commit()

    with factory() as session:
        locked = session.scalars(
            select(WhatsAppAccount)
            .where(WhatsAppAccount.id == "account-lock")
            .with_for_update()
        ).all()
        assert len(locked) == 1
        session.commit()


def test_case_insensitive_search_works(factory):
    """前导通配符搜索在 PostgreSQL 上必须用 ILIKE 语义（SQLAlchemy 已处理）。"""

    with factory() as session:
        account = WhatsAppAccount(name="WA", session_ref="sessions/wa")
        session.add(account)
        session.flush()
        contact = Contact(
            account_id=account.id, remote_jid="p@lid", display_name="Alice"
        )
        session.add(contact)
        session.flush()
        session.add(
            Conversation(
                account_id=account.id,
                contact_id=contact.id,
                remote_jid="p@lid",
                title="Hello World",
            )
        )
        session.commit()

    with factory() as session:
        found = session.scalars(
            select(Conversation).where(Conversation.title.ilike("%hello%"))
        ).all()
    assert len(found) == 1
