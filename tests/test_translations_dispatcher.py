"""翻译批次调度器的三段式事务契约与窗口/回退行为。

核心回归目标：AI 调用期间绝不持有数据库会话（原实现把最长 90s×retry 的
网络请求放在 `with session_factory()` 事务内，会长期占住连接与行锁）。
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from whatsapp_chat_system.db.base import Base
from whatsapp_chat_system.db.models import (
    Contact,
    Conversation,
    Message,
    MessageTranslation,
    TranslationBatch,
    WhatsAppAccount,
)
from whatsapp_chat_system.translations_dispatcher import (
    TranslationDispatcher,
    TranslationDispatcherConfig,
)


@dataclass
class _FakeResult:
    content: str


@dataclass
class _FakeChatOutcome:
    result: _FakeResult


@dataclass
class _FakeRewrite:
    message: str | None = None
    error: object | None = None
    language: str = "Chinese"


class _SessionTracker:
    """记录当前有多少个数据库会话处于打开状态。

    同时统计「AI 被调用时」的打开会话数——这是本次修复的关键断言。
    """

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory
        self._lock = threading.Lock()
        self.open_count = 0
        self.peak_open = 0
        self.open_sessions_during_ai: list[int] = []
        self.ai_call_count = 0

    @contextmanager
    def __call__(self):
        with self._lock:
            self.open_count += 1
            self.peak_open = max(self.peak_open, self.open_count)
        try:
            with self._factory() as session:
                yield session
        finally:
            with self._lock:
                self.open_count -= 1

    def note_ai_call(self) -> None:
        with self._lock:
            self.ai_call_count += 1
            self.open_sessions_during_ai.append(self.open_count)


class _FakeAIService:
    def __init__(
        self,
        tracker: _SessionTracker,
        *,
        payload: dict | None = None,
        raise_error: Exception | None = None,
    ) -> None:
        self._tracker = tracker
        self._payload = payload
        self._raise = raise_error

    def chat(self, **_kwargs) -> _FakeChatOutcome:
        # AI 首次被调用时记录当前打开的会话数
        self._tracker.note_ai_call()
        if self._raise is not None:
            raise self._raise
        import json

        return _FakeChatOutcome(_FakeResult(json.dumps(self._payload or {"items": []})))


class _FakeWorker:
    def __init__(
        self,
        tracker: _SessionTracker,
        *,
        batch_payload: dict | None = None,
        batch_error: Exception | None = None,
        fallback=None,
    ) -> None:
        self.phrase_dict: dict[str, str] = {}
        self.ai_service = _FakeAIService(
            tracker, payload=batch_payload, raise_error=batch_error
        )
        self._tracker = tracker
        self._fallback = fallback
        self.fallback_calls: list[str] = []
        self._fallback_lock = threading.Lock()

    def _account_model(self):
        return None

    def translate_to_zh_result(self, text: str, source_lang: str) -> _FakeRewrite:
        self._tracker.note_ai_call()
        with self._fallback_lock:
            self.fallback_calls.append(text)
        if self._fallback is not None:
            return self._fallback(text, source_lang)
        return _FakeRewrite(message=f"[zh]{text}")


@pytest.fixture()
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    engine.dispose()


def _seed(factory, texts: list[str]):
    """建立账号/联系人/会话/消息，并返回 (anchor_message_id, message_ids, account_id, conversation_id)。"""

    with factory() as session:
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

        message_ids: list[str] = []
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for index, text in enumerate(texts):
            message = Message(
                account_id=account.id,
                conversation_id=conversation.id,
                contact_id=contact.id,
                wa_message_id=f"wa-{index}",
                direction="inbound",
                status="received",
                content=text,
                message_type="text",
                occurred_at=base + timedelta(seconds=index),
            )
            session.add(message)
            session.flush()
            message_ids.append(message.id)
        session.commit()
        return message_ids[-1], message_ids, account.id, conversation.id


def _make_dispatcher(factory, tracker, worker, **config_kwargs):
    dispatcher = TranslationDispatcher(
        tracker,
        runtime=object(),
        config=TranslationDispatcherConfig(**config_kwargs),
    )
    dispatcher._rewriter = lambda: worker  # type: ignore[method-assign]
    return dispatcher


def _make_batch(
    factory,
    *,
    anchor_id: str,
    account_id: str,
    conversation_id: str,
    target_lang: str = "zh-CN",
    window_size: int = 10,
    status: str = "pending",
    attempt_count: int = 0,
    updated_at: datetime | None = None,
) -> str:
    with factory() as session:
        batch = TranslationBatch(
            account_id=account_id,
            conversation_id=conversation_id,
            anchor_message_id=anchor_id,
            target_lang=target_lang,
            window_size=window_size,
            status=status,
            attempt_count=attempt_count,
        )
        if updated_at is not None:
            batch.updated_at = updated_at
        session.add(batch)
        session.commit()
        return batch.id


def test_ai_is_never_called_while_a_db_session_is_open(factory):
    """回归：AI 调用必须发生在事务之外。"""

    anchor, _messages, account_id, conversation_id = _seed(factory, ["hello", "world"])
    batch_id = _make_batch(
        factory,
        anchor_id=anchor,
        account_id=account_id,
        conversation_id=conversation_id,
    )
    tracker = _SessionTracker(factory)
    worker = _FakeWorker(
        tracker,
        batch_payload={
            "items": [
                {"message_id": anchor, "source_lang": "Latin", "zh": "你好"},
            ]
        },
    )

    dispatcher = _make_dispatcher(factory, tracker, worker)
    assert dispatcher.run_once() is True

    assert tracker.ai_call_count > 0, "AI 应当被调用"
    assert tracker.open_sessions_during_ai == [0] * tracker.ai_call_count, (
        "AI 调用期间不应存在打开的数据库会话，实际序列为 "
        f"{tracker.open_sessions_during_ai}"
    )

    with factory() as session:
        batch = session.get(TranslationBatch, batch_id)
        assert batch.status == "completed"
        assert batch.attempt_count == 1


def test_translations_are_persisted_from_window_result(factory):
    anchor, messages, account_id, conversation_id = _seed(factory, ["hello", "sawadee"])
    _make_batch(
        factory,
        anchor_id=anchor,
        account_id=account_id,
        conversation_id=conversation_id,
    )
    tracker = _SessionTracker(factory)
    worker = _FakeWorker(
        tracker,
        batch_payload={
            "items": [
                {"message_id": messages[0], "source_lang": "Latin", "zh": "你好"},
                {"message_id": messages[1], "source_lang": "Thai", "zh": "你好呀"},
            ]
        },
    )

    assert _make_dispatcher(factory, tracker, worker).run_once() is True

    with factory() as session:
        rows = {
            row.message_id: row
            for row in session.scalars(select(MessageTranslation)).all()
        }
    assert rows[messages[0]].translated_text == "你好"
    assert rows[messages[0]].status == "completed"
    assert rows[messages[0]].provider == "wendingai"
    assert rows[messages[1]].translated_text == "你好呀"
    # 窗口批量调用已覆盖全部条目，不应触发逐条回退
    assert worker.fallback_calls == []


def test_chinese_source_skips_ai_entirely(factory):
    """原文已是中文时直接落库，不浪费 AI 调用。"""

    anchor, messages, account_id, conversation_id = _seed(factory, ["你好世界"])
    _make_batch(
        factory,
        anchor_id=anchor,
        account_id=account_id,
        conversation_id=conversation_id,
    )
    tracker = _SessionTracker(factory)
    worker = _FakeWorker(tracker, batch_payload={"items": []})

    assert _make_dispatcher(factory, tracker, worker).run_once() is True

    assert tracker.ai_call_count == 0
    with factory() as session:
        row = session.scalar(select(MessageTranslation))
    assert row.message_id == messages[0]
    assert row.status == "completed"
    assert row.source_lang == "Chinese"


def test_already_completed_translation_is_not_recomputed(factory):
    anchor, messages, account_id, conversation_id = _seed(factory, ["hello"])
    _make_batch(
        factory,
        anchor_id=anchor,
        account_id=account_id,
        conversation_id=conversation_id,
    )
    tracker = _SessionTracker(factory)

    first_worker = _FakeWorker(
        tracker,
        batch_payload={
            "items": [{"message_id": messages[0], "source_lang": "Latin", "zh": "你好"}]
        },
    )
    assert _make_dispatcher(factory, tracker, first_worker).run_once() is True

    # 第二个批次针对同一条消息，应识别出已完成而不再调用 AI
    _make_batch(
        factory,
        anchor_id=anchor,
        account_id=account_id,
        conversation_id=conversation_id,
    )
    second_worker = _FakeWorker(tracker, batch_payload={"items": []})
    assert _make_dispatcher(factory, tracker, second_worker).run_once() is True

    assert second_worker.fallback_calls == []
    assert tracker.ai_call_count == 1


def test_window_failure_falls_back_per_message(factory):
    anchor, messages, account_id, conversation_id = _seed(
        factory, ["alpha", "beta", "gamma"]
    )
    _make_batch(
        factory,
        anchor_id=anchor,
        account_id=account_id,
        conversation_id=conversation_id,
    )
    tracker = _SessionTracker(factory)
    worker = _FakeWorker(
        tracker,
        batch_error=RuntimeError("window call exploded"),
        fallback=lambda text, lang: _FakeRewrite(message=f"译:{text}"),
    )

    assert _make_dispatcher(factory, tracker, worker).run_once() is True

    assert sorted(worker.fallback_calls) == ["alpha", "beta", "gamma"]
    with factory() as session:
        rows = {
            row.message_id: row
            for row in session.scalars(select(MessageTranslation)).all()
        }
    assert rows[messages[0]].translated_text == "译:alpha"
    assert rows[messages[2]].translated_text == "译:gamma"
    # 回退同样必须在事务外
    assert tracker.open_sessions_during_ai == [0] * tracker.ai_call_count


def test_fallback_runs_concurrently(factory):
    """串行回退改为并发后，总耗时应显著低于逐条累加。"""

    import time

    texts = [f"msg-{i}" for i in range(8)]
    anchor, _messages, account_id, conversation_id = _seed(factory, texts)
    _make_batch(
        factory,
        anchor_id=anchor,
        account_id=account_id,
        conversation_id=conversation_id,
    )
    tracker = _SessionTracker(factory)

    def slow_fallback(text: str, _lang: str) -> _FakeRewrite:
        time.sleep(0.15)
        return _FakeRewrite(message=f"译:{text}")

    worker = _FakeWorker(
        tracker,
        batch_error=RuntimeError("force fallback"),
        fallback=slow_fallback,
    )
    dispatcher = _make_dispatcher(factory, tracker, worker, max_fallback_concurrency=8)

    started = time.monotonic()
    assert dispatcher.run_once() is True
    elapsed = time.monotonic() - started

    assert len(worker.fallback_calls) == 8
    # 串行需要 8 × 0.15s = 1.2s；并发 8 路应远低于此
    assert elapsed < 0.9, f"回退未并发执行，耗时 {elapsed:.2f}s"


def test_fallback_failure_marks_only_that_message_failed(factory):
    anchor, messages, account_id, conversation_id = _seed(factory, ["ok", "boom"])
    _make_batch(
        factory,
        anchor_id=anchor,
        account_id=account_id,
        conversation_id=conversation_id,
    )
    tracker = _SessionTracker(factory)

    def selective(text: str, _lang: str) -> _FakeRewrite:
        if text == "boom":
            return _FakeRewrite(message=None, error="provider down")
        return _FakeRewrite(message=f"译:{text}")

    worker = _FakeWorker(
        tracker, batch_error=RuntimeError("force fallback"), fallback=selective
    )

    assert _make_dispatcher(factory, tracker, worker).run_once() is True

    with factory() as session:
        rows = {
            row.message_id: row
            for row in session.scalars(select(MessageTranslation)).all()
        }
    assert rows[messages[0]].status == "completed"
    assert rows[messages[1]].status == "failed"
    assert rows[messages[1]].error_code == "translate_failed"


def test_fallback_exception_does_not_lose_other_messages(factory):
    """单条回退抛异常时，同批其他消息仍应落库。"""

    anchor, messages, account_id, conversation_id = _seed(factory, ["keep", "explode"])
    _make_batch(
        factory,
        anchor_id=anchor,
        account_id=account_id,
        conversation_id=conversation_id,
    )
    tracker = _SessionTracker(factory)

    def exploding(text: str, _lang: str) -> _FakeRewrite:
        if text == "explode":
            raise RuntimeError("hard failure")
        return _FakeRewrite(message=f"译:{text}")

    worker = _FakeWorker(
        tracker, batch_error=RuntimeError("force fallback"), fallback=exploding
    )

    assert _make_dispatcher(factory, tracker, worker).run_once() is True

    with factory() as session:
        rows = {
            row.message_id: row
            for row in session.scalars(select(MessageTranslation)).all()
        }
    assert rows[messages[0]].status == "completed"


def test_batch_with_missing_anchor_is_marked_dead(factory):
    anchor, _messages, account_id, conversation_id = _seed(factory, ["hello"])
    batch_id = _make_batch(
        factory,
        anchor_id=anchor,
        account_id=account_id,
        conversation_id=conversation_id,
    )
    # 指向一个不存在的锚点，模拟锚点消息被删除后批次悬空
    with factory() as session:
        batch = session.get(TranslationBatch, batch_id)
        batch.anchor_message_id = "00000000-0000-0000-0000-000000000000"
        session.commit()

    tracker = _SessionTracker(factory)
    worker = _FakeWorker(tracker, batch_payload={"items": []})
    dispatcher = _make_dispatcher(factory, tracker, worker)

    # 锚点缺失不应抛异常，也不应调用 AI
    assert dispatcher.run_once() is False

    assert tracker.ai_call_count == 0
    assert dispatcher.failed_batches == 0
    with factory() as session:
        batch = session.get(TranslationBatch, batch_id)
    assert batch.status == "dead"
    assert batch.error_code == "anchor_message_missing"


def test_translation_failure_marks_batch_failed(factory):
    """阶段二抛异常时必须把批次标记为 failed，而不是永远卡在 running。"""

    anchor, _messages, account_id, conversation_id = _seed(factory, ["hello"])
    batch_id = _make_batch(
        factory,
        anchor_id=anchor,
        account_id=account_id,
        conversation_id=conversation_id,
    )
    tracker = _SessionTracker(factory)
    worker = _FakeWorker(tracker, batch_payload={"items": []})
    dispatcher = _make_dispatcher(factory, tracker, worker)

    def explode():
        raise RuntimeError("provider construction failed")

    dispatcher._rewriter = explode  # type: ignore[method-assign]

    assert dispatcher.run_once() is False
    assert dispatcher.failed_batches == 1
    assert dispatcher.last_error == "RuntimeError"
    with factory() as session:
        batch = session.get(TranslationBatch, batch_id)
    assert batch.status == "failed"
    assert batch.error_code == "translation_batch_failed"


def test_stale_running_batch_is_reclaimed(factory):
    """进程崩溃遗留的 running 批次超过阈值后应可被重新领取。"""

    anchor, messages, account_id, conversation_id = _seed(factory, ["hello"])
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    _make_batch(
        factory,
        anchor_id=anchor,
        account_id=account_id,
        conversation_id=conversation_id,
        status="running",
        attempt_count=1,
        updated_at=stale,
    )

    tracker = _SessionTracker(factory)
    worker = _FakeWorker(
        tracker,
        batch_payload={
            "items": [{"message_id": messages[0], "source_lang": "Latin", "zh": "你好"}]
        },
    )
    dispatcher = _make_dispatcher(factory, tracker, worker)

    assert dispatcher.run_once() is True
    assert dispatcher.processed_batches == 1


def test_recent_running_batch_is_not_stolen(factory):
    """仍新鲜的 running 批次属于其他在跑的 worker，不得抢夺。"""

    anchor, _messages, account_id, conversation_id = _seed(factory, ["hello"])
    _make_batch(
        factory,
        anchor_id=anchor,
        account_id=account_id,
        conversation_id=conversation_id,
        status="running",
        attempt_count=1,
        updated_at=datetime.now(timezone.utc),
    )

    tracker = _SessionTracker(factory)
    worker = _FakeWorker(tracker, batch_payload={"items": []})
    dispatcher = _make_dispatcher(factory, tracker, worker)

    assert dispatcher.run_once() is False
    assert tracker.ai_call_count == 0


def test_batch_exceeding_max_attempts_is_skipped(factory):
    anchor, _messages, account_id, conversation_id = _seed(factory, ["hello"])
    _make_batch(
        factory,
        anchor_id=anchor,
        account_id=account_id,
        conversation_id=conversation_id,
        status="pending",
        attempt_count=3,
    )

    tracker = _SessionTracker(factory)
    worker = _FakeWorker(tracker, batch_payload={"items": []})
    dispatcher = _make_dispatcher(factory, tracker, worker, max_attempts=3)

    assert dispatcher.run_once() is False
    assert tracker.ai_call_count == 0


def test_run_once_returns_false_without_pending_batches(factory):
    tracker = _SessionTracker(factory)
    worker = _FakeWorker(tracker, batch_payload={"items": []})
    dispatcher = _make_dispatcher(factory, tracker, worker)

    assert dispatcher.run_once() is False
    assert dispatcher.health()["processed_batches"] == 0
    assert dispatcher.health()["last_heartbeat"] is not None


def test_window_is_limited_by_window_size(factory):
    anchor, _messages, account_id, conversation_id = _seed(
        factory, [f"m{i}" for i in range(6)]
    )
    _make_batch(
        factory,
        anchor_id=anchor,
        account_id=account_id,
        conversation_id=conversation_id,
        window_size=3,
    )
    tracker = _SessionTracker(factory)
    worker = _FakeWorker(
        tracker,
        batch_payload={"items": []},
        fallback=lambda t, _l: _FakeRewrite(message=f"译:{t}"),
    )

    assert _make_dispatcher(factory, tracker, worker).run_once() is True

    # window_size=3 决定只处理锚点前最近 3 条
    assert len(worker.fallback_calls) == 3


def test_peak_open_sessions_stays_at_one(factory):
    """即使并发回退，也不应出现会话泄漏或叠加。"""

    anchor, _messages, account_id, conversation_id = _seed(
        factory, [f"m{i}" for i in range(6)]
    )
    _make_batch(
        factory,
        anchor_id=anchor,
        account_id=account_id,
        conversation_id=conversation_id,
    )
    tracker = _SessionTracker(factory)
    worker = _FakeWorker(
        tracker,
        batch_error=RuntimeError("force fallback"),
        fallback=lambda t, _l: _FakeRewrite(message=f"译:{t}"),
    )

    assert (
        _make_dispatcher(
            factory, tracker, worker, max_fallback_concurrency=6
        ).run_once()
        is True
    )

    assert tracker.peak_open <= 1, f"会话并发打开数异常：{tracker.peak_open}"
