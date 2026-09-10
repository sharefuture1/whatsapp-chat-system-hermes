"""Outbox 抢占的并发正确性。

原实现用 `SELECT ... FOR UPDATE SKIP LOCKED` 抢占，但 SQLite 会**静默忽略**
FOR UPDATE，多进程部署下同一个 OutboxMessage 会被两个 worker 同时 claim，
导致重复发送。现改为条件 UPDATE（CAS），在 SQLite 与 PostgreSQL 上均原子。
"""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from whatsapp_chat_system.db.base import Base
from whatsapp_chat_system.db.models import (
    Contact,
    Conversation,
    OutboxMessage,
    WhatsAppAccount,
)
from whatsapp_chat_system.outbox import OutboxDispatcher, enqueue_outbox_message


@pytest.fixture()
def factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'outbox.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    # 与生产一致：启用外键与 WAL
    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with session_factory() as session:
        account = WhatsAppAccount(name="WA", session_ref="sessions/wa")
        session.add(account)
        session.flush()
        contact = Contact(account_id=account.id, remote_jid="p@lid", display_name="P")
        session.add(contact)
        session.flush()
        conversation = Conversation(
            account_id=account.id, contact_id=contact.id, remote_jid=contact.remote_jid
        )
        session.add(conversation)
        session.flush()
        for index in range(20):
            enqueue_outbox_message(
                session,
                conversation,
                text=f"message {index}",
                idempotency_key=f"key-{index}",
            )
        session.commit()
    yield session_factory, engine
    engine.dispose()


class _Bridge:
    """记录已成功投递的 outbox id，便于检测重复发送。"""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self._lock = threading.Lock()

    def send(self, **_kwargs):
        with self._lock:
            self.sent.append(_kwargs.get("text", ""))
        return {"message_id": "wa-id"}


def test_claim_is_expressed_as_guarded_update(factory):
    """结构性回归：抢占必须是带 status 守卫的 UPDATE，而非 FOR UPDATE。"""

    session_factory, engine = factory
    captured: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _capture(_conn, _cursor, statement, _params, _ctx, _many):
        captured.append(" ".join(statement.split()))

    dispatcher = OutboxDispatcher(session_factory, _Bridge(), worker_id="worker-a")
    try:
        claimed = dispatcher._claim_batch()
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    assert claimed, "应当抢到待发送的 outbox 行"
    updates = [
        statement
        for statement in captured
        if statement.upper().startswith("UPDATE OUTBOX_MESSAGES")
    ]
    assert updates, "抢占必须通过 UPDATE 完成（SQLite 不支持 FOR UPDATE）"

    # 关键点：守卫必须出现在 WHERE 子句里。
    # 旧实现是逐行 ORM 更新（`WHERE id = ?`），status 只会出现在 SET 子句，
    # 那种写法不具备 CAS 语义。
    guarded = False
    for statement in updates:
        _, _, where_clause = statement.partition(" WHERE ")
        if "status = ?" in where_clause and "id IN (" in where_clause:
            guarded = True
    assert guarded, (
        "抢占 UPDATE 必须在 WHERE 中同时约束 status 与 id 列表以实现 CAS，"
        f"实际 SQL：{updates}"
    )
    assert not any("FOR UPDATE" in statement.upper() for statement in captured), (
        "不应再依赖 FOR UPDATE：SQLite 会静默忽略它"
    )


def test_two_workers_never_claim_the_same_row(factory):
    """并发抢占同一批时，所有权必须互斥。"""

    session_factory, _engine = factory
    bridge_a, bridge_b = _Bridge(), _Bridge()
    dispatcher_a = OutboxDispatcher(
        session_factory, bridge_a, worker_id="worker-a", batch_size=10
    )
    dispatcher_b = OutboxDispatcher(
        session_factory, bridge_b, worker_id="worker-b", batch_size=10
    )

    barrier = threading.Barrier(2)
    results: dict[str, list[str]] = {}
    errors: list[Exception] = []

    def claim(name: str, dispatcher: OutboxDispatcher) -> None:
        try:
            barrier.wait(timeout=10)
            results[name] = dispatcher._claim_batch()
        except Exception as exc:  # noqa: BLE001 - 记录后由断言暴露
            errors.append(exc)

    threads = [
        threading.Thread(target=claim, args=("a", dispatcher_a)),
        threading.Thread(target=claim, args=("b", dispatcher_b)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"抢占过程报错：{errors}"
    claimed_a = results.get("a", [])
    claimed_b = results.get("b", [])
    assert not set(claimed_a) & set(claimed_b), (
        f"同一个 outbox 行被两个 worker 同时抢占：{set(claimed_a) & set(claimed_b)}"
    )


def test_claim_marks_lease_owner_and_increments_attempts(factory):
    session_factory, _engine = factory
    dispatcher = OutboxDispatcher(
        session_factory, _Bridge(), worker_id="worker-a", batch_size=3
    )

    claimed = dispatcher._claim_batch()

    assert len(claimed) == 3
    with session_factory() as session:
        rows = session.scalars(
            select(OutboxMessage).where(OutboxMessage.id.in_(claimed))
        ).all()
    assert all(row.status == "claimed" for row in rows)
    assert all(row.lease_owner == "worker-a" for row in rows)
    assert all(row.lease_expires_at is not None for row in rows)
    assert all(row.attempts == 1 for row in rows)


def test_second_sequential_claim_does_not_reclaim(factory):
    session_factory, _engine = factory
    first = OutboxDispatcher(
        session_factory, _Bridge(), worker_id="worker-a", batch_size=5
    )
    second = OutboxDispatcher(
        session_factory, _Bridge(), worker_id="worker-b", batch_size=5
    )

    claimed_first = first._claim_batch()
    claimed_second = second._claim_batch()

    assert len(claimed_first) == 5
    # 第二个 worker 拿到的是剩余未抢占的行，且不重叠
    assert not set(claimed_first) & set(claimed_second)


def test_claim_returns_empty_when_nothing_pending(factory):
    session_factory, _engine = factory
    dispatcher = OutboxDispatcher(
        session_factory, _Bridge(), worker_id="worker-a", batch_size=100
    )

    assert len(dispatcher._claim_batch()) == 20
    assert dispatcher._claim_batch() == []


def test_expired_lease_is_returned_to_pending(factory):
    from datetime import datetime, timedelta, timezone

    session_factory, _engine = factory
    dispatcher = OutboxDispatcher(
        session_factory, _Bridge(), worker_id="worker-a", batch_size=4
    )
    first = dispatcher._claim_batch()
    assert len(first) == 4

    # 人为把租约改成已过期
    with session_factory() as session:
        for row in session.scalars(
            select(OutboxMessage).where(OutboxMessage.id.in_(first))
        ).all():
            row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        session.commit()

    reclaimed = OutboxDispatcher(
        session_factory, _Bridge(), worker_id="worker-b", batch_size=4
    )._claim_batch()

    assert set(first) <= set(reclaimed), "过期租约应被回收并可被其他 worker 重新抢占"
