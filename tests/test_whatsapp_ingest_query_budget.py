"""Webhook 批量写入的查询预算：SELECT 次数不得随条目数线性增长。

原实现对每个 item 单独 SELECT（`_upsert_contacts` / `_upsert_chats`），
`_upsert_message` 内部更是最多 3 次 SELECT，单次 webhook 上限 100 条消息
时会产生约 300 次数据库往返，且全部压在同一个事务里。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from whatsapp_chat_system.db.base import Base
from whatsapp_chat_system.db.models import (
    Contact,
    Conversation,
    Message,
    WhatsAppAccount,
)
from whatsapp_chat_system.events.whatsapp import (
    WhatsAppEventEnvelope,
    WhatsAppEventService,
)


class _QueryCounter:
    """统计指定表上的 SELECT 次数。"""

    _TABLES = ("contacts", "conversations", "messages")

    def __init__(self, engine) -> None:
        self.statements: list[str] = []
        self.enabled = False
        event.listen(engine, "before_cursor_execute", self._on_execute)

    def _on_execute(self, _conn, _cursor, statement, _params, _ctx, _many) -> None:
        if self.enabled:
            self.statements.append(statement)

    def reset(self) -> None:
        self.statements = []

    def selects(self) -> list[str]:
        return [
            statement
            for statement in self.statements
            if statement.lstrip().upper().startswith("SELECT")
            and any(table in statement for table in self._TABLES)
        ]


@pytest.fixture()
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ingest.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        session.add(
            WhatsAppAccount(id="account-a", name="A", session_ref="account:account-a")
        )
        session.commit()
    yield factory, _QueryCounter(engine)
    engine.dispose()


def _history_envelope(count: int, *, sequence: int = 1) -> WhatsAppEventEnvelope:
    """构造 count 条历史消息，分属 count 个不同联系人/会话（最坏情况）。"""

    base = datetime(2026, 7, 10, tzinfo=timezone.utc)
    items = []
    for index in range(count):
        items.append(
            {
                "schema_version": 1,
                "wa_message_id": f"WA-{sequence}-{index}",
                "remote_jid": f"user{index}@s.whatsapp.net",
                "sender_jid": f"user{index}@s.whatsapp.net",
                "participant_jid": None,
                "from_me": False,
                "conversation_type": "dm",
                "message_type": "text",
                "timestamp": (base + timedelta(seconds=index)).isoformat(),
                "text": f"hello {index}",
                "push_name": f"Customer {index}",
                "quoted_wa_message_id": None,
                "media": None,
            }
        )
    return WhatsAppEventEnvelope.model_validate(
        {
            "event_id": f"evt-seq-{sequence}",
            "event_type": "history.messages.upsert",
            "account_id": "account-a",
            "occurred_at": base,
            "sequence": sequence,
            "payload": {"schema_version": 1, "items": items},
        }
    )


def _contacts_envelope(count: int, *, sequence: int = 1) -> WhatsAppEventEnvelope:
    base = datetime(2026, 7, 10, tzinfo=timezone.utc)
    return WhatsAppEventEnvelope.model_validate(
        {
            "event_id": f"evt-contacts-{sequence}",
            "event_type": "contacts.upsert",
            "account_id": "account-a",
            "occurred_at": base,
            "sequence": sequence,
            "payload": {
                "schema_version": 1,
                "items": [
                    {
                        "remote_jid": f"c{index}@s.whatsapp.net",
                        "display_name": f"Contact {index}",
                    }
                    for index in range(count)
                ],
            },
        }
    )


def _chats_envelope(count: int, *, sequence: int = 1) -> WhatsAppEventEnvelope:
    base = datetime(2026, 7, 10, tzinfo=timezone.utc)
    return WhatsAppEventEnvelope.model_validate(
        {
            "event_id": f"evt-chats-{sequence}",
            "event_type": "chats.upsert",
            "account_id": "account-a",
            "occurred_at": base,
            "sequence": sequence,
            "payload": {
                "schema_version": 1,
                "items": [
                    {
                        "remote_jid": f"k{index}@s.whatsapp.net",
                        "conversation_type": "dm",
                        "title": f"Chat {index}",
                    }
                    for index in range(count)
                ],
            },
        }
    )


def _measure(factory, counter, envelope) -> tuple[int, int]:
    """返回 (SELECT 次数, 实际落库的行数)。"""

    counter.reset()
    counter.enabled = True
    try:
        with factory() as session:
            WhatsAppEventService(session).process(envelope)
            session.commit()
    finally:
        counter.enabled = False
    selects = len(counter.selects())
    with factory() as session:
        rows = session.scalar(select(func.count()).select_from(Message))
        rows += session.scalar(select(func.count()).select_from(Contact))
        rows += session.scalar(select(func.count()).select_from(Conversation))
    return selects, rows


def test_history_batch_selects_do_not_scale_with_item_count(factory):
    """40 条历史消息与 5 条的 SELECT 次数应当接近，而不是相差 8 倍。"""

    session_factory, counter = factory

    small_selects, _ = _measure(session_factory, counter, _history_envelope(5, sequence=1))
    large_selects, _ = _measure(
        session_factory, counter, _history_envelope(40, sequence=2)
    )

    # 旧实现为 3N：5 条 15 次、40 条 120 次。新实现为常数级。
    assert large_selects <= small_selects + 3, (
        f"SELECT 次数随条目线性增长：5 条 {small_selects} 次 → 40 条 {large_selects} 次"
    )
    assert large_selects < 15, f"40 条消息仍产生 {large_selects} 次 SELECT"


def test_history_batch_still_persists_everything(factory):
    """降查询次数不能以丢数据为代价。"""

    session_factory, counter = factory
    _measure(session_factory, counter, _history_envelope(12, sequence=1))

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 12
        assert session.scalar(select(func.count()).select_from(Contact)) == 12
        assert session.scalar(select(func.count()).select_from(Conversation)) == 12


def test_contacts_batch_selects_are_constant(factory):
    session_factory, counter = factory

    small_selects, _ = _measure(
        session_factory, counter, _contacts_envelope(5, sequence=1)
    )
    large_selects, _ = _measure(
        session_factory, counter, _contacts_envelope(40, sequence=2)
    )

    assert large_selects <= small_selects + 2, (
        f"联系人批量写入 SELECT 随条目增长：{small_selects} → {large_selects}"
    )


def test_chats_batch_selects_are_constant(factory):
    session_factory, counter = factory

    small_selects, _ = _measure(session_factory, counter, _chats_envelope(5, sequence=1))
    large_selects, _ = _measure(
        session_factory, counter, _chats_envelope(40, sequence=2)
    )

    assert large_selects <= small_selects + 2, (
        f"会话批量写入 SELECT 随条目增长：{small_selects} → {large_selects}"
    )


def test_duplicate_remote_jid_within_one_batch_updates_single_row(factory):
    """同一批次内重复 remote_jid 必须命中同一行（与逐条 SELECT 语义一致）。"""

    session_factory, _counter = factory
    base = datetime(2026, 7, 10, tzinfo=timezone.utc)
    envelope = WhatsAppEventEnvelope.model_validate(
        {
            "event_id": "evt-dup-contact",
            "event_type": "contacts.upsert",
            "account_id": "account-a",
            "occurred_at": base,
            "sequence": 1,
            "payload": {
                "schema_version": 1,
                "items": [
                    {"remote_jid": "dup@s.whatsapp.net", "display_name": "First"},
                    {"remote_jid": "dup@s.whatsapp.net", "phone_number": "+8613800000000"},
                ],
            },
        }
    )

    with session_factory() as session:
        WhatsAppEventService(session).process(envelope)
        session.commit()

    with session_factory() as session:
        contacts = session.scalars(select(Contact)).all()
    assert len(contacts) == 1
    assert contacts[0].display_name == "First"
    assert contacts[0].phone_number == "+8613800000000"


def test_same_message_twice_in_one_batch_does_not_duplicate(factory):
    """同一批次内重复 wa_message_id 只应产生一行（与逐条 SELECT 语义一致）。"""

    session_factory, _counter = factory
    envelope = _history_envelope(3, sequence=1)
    # 把第二条的 wa_message_id 改成与第一条相同
    envelope.payload["items"][1]["wa_message_id"] = envelope.payload["items"][0][
        "wa_message_id"
    ]

    with session_factory() as session:
        WhatsAppEventService(session).process(envelope)
        session.commit()

    with session_factory() as session:
        wa_ids = session.scalars(select(Message.wa_message_id)).all()
    # 3 条 item 里前两条指向同一条消息，因此只落 2 行
    assert len(wa_ids) == 2
    assert len(set(wa_ids)) == 2
