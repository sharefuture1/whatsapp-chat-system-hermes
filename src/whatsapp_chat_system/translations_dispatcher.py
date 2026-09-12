from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Sequence

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from .db.models import Message, MessageTranslation, TranslationBatch
from .rewriter import Rewriter
from .translation_hash import source_text_hash

logger = logging.getLogger(__name__)

# SQLite 默认参数上限为 999，批量 IN 查询按此分片以避免 "too many SQL variables"
_DB_QUERY_CHUNK = 500


@dataclass(frozen=True)
class TranslationDispatcherConfig:
    poll_seconds: float = 2.0
    #: 窗口批量调用失败后逐条补齐的并发度。
    #: requests.Session 的连接池本身线程安全，且这些是无 cookie 的独立 POST，
    #: 因此并发不会串味；置为 1 可退回串行。
    max_fallback_concurrency: int = 4
    #: 单个批次的最大尝试次数，超过则标记 failed，避免坏批次无限重试。
    max_attempts: int = 3
    #: 超过该时长仍停留在 running 的批次视为进程崩溃遗留，可被重新领取。
    stale_running_seconds: float = 600.0
    #: 可重试失败的指数退避基数/上限；测试可设 0 立即重试。
    retry_base_seconds: float = 2.0
    retry_max_seconds: float = 60.0
    #: CAS 竞争时一次 run_once 最多重新挑选多少次。
    claim_contention_retries: int = 8


@dataclass(frozen=True)
class _PendingItem:
    """阶段一读取、阶段二翻译所需的最小快照，不持有 ORM 实例。"""

    message_id: str
    account_id: str
    conversation_id: str
    content: str
    text: str
    source_lang: str


@dataclass(frozen=True)
class _BatchPlan:
    batch_id: str
    target_lang: str
    window_size: int
    claim_attempt: int
    items: tuple[_PendingItem, ...]


@dataclass(frozen=True)
class _MessageOutcome:
    message_id: str
    source_lang: str
    translated_text: str | None
    status: str
    error_code: str | None = None
    error_message: str | None = None


def _chunked(
    values: Sequence[str], size: int = _DB_QUERY_CHUNK
) -> Iterable[Sequence[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


class TranslationDispatcher:
    """翻译批次调度器。

    严格遵循「短事务读 → 无 session 调 AI → 短事务写」三段式（对齐 PERF-006）：
    AI 调用期间绝不持有数据库会话，避免长事务占住连接与行锁。
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        runtime: Any,
        *,
        runtime_manager: Any = None,
        config: TranslationDispatcherConfig | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.runtime = runtime
        self.runtime_manager = runtime_manager
        self.config = config or TranslationDispatcherConfig()
        self.last_heartbeat: datetime | None = None
        self.last_error: str | None = None
        self.processed_batches = 0
        self.failed_batches = 0
        self._cached_rewriter: Rewriter | None = None

    def run_once(self) -> bool:
        self.last_heartbeat = datetime.now(timezone.utc)

        # 阶段一：短事务——领取批次并收集待翻译快照
        try:
            plan = self._claim_batch()
        except Exception:
            logger.exception("Translation batch claim failed")
            self.last_error = "claim_failed"
            return False
        if plan is None:
            return False

        # 阶段二：无数据库会话状态下调用 AI（最长可达 Provider 超时 × 重试）
        try:
            outcomes = self._translate(plan)
        except Exception as exc:
            self.failed_batches += 1
            self.last_error = type(exc).__name__
            logger.exception(
                "Translation batch failed", extra={"batch_id": plan.batch_id}
            )
            self._mark_failed(plan, exc)
            return False

        # 阶段三：新短事务——落库
        try:
            self._finalize(plan, outcomes)
        except Exception as exc:
            self.failed_batches += 1
            self.last_error = type(exc).__name__
            logger.exception(
                "Translation batch persistence failed",
                extra={"batch_id": plan.batch_id},
            )
            self._mark_failed(plan, exc)
            return False

        if any(outcome.status != "completed" for outcome in outcomes):
            self.failed_batches += 1
            self.last_error = "translation_items_failed"
        else:
            self.last_error = None
        self.processed_batches += 1
        return True

    # ------------------------------------------------------------------ 阶段一

    def _claim_batch(self) -> _BatchPlan | None:
        """以条件 UPDATE 原子领取一个批次并返回本轮快照。

        `attempt_count` 同时作为轻量 claim generation。即使两个进程先后 SELECT
        到同一候选，只有仍保持相同 status/attempt 的一个 UPDATE 能成功。
        """

        retries = max(1, int(self.config.claim_contention_retries))
        for _ in range(retries):
            with self.session_factory() as session:
                batch = self._next_batch(session)
                if batch is None:
                    return None
                batch_id = batch.id
                if not self._claim_candidate(session, batch):
                    session.rollback()
                    continue
                session.commit()
                session.expire_all()
                batch = session.get(TranslationBatch, batch_id)
                if batch is None:
                    return None
                claim_attempt = int(batch.attempt_count or 0)

                try:
                    anchor = session.get(Message, batch.anchor_message_id)
                    if anchor is None:
                        batch.status = "dead"
                        batch.error_code = "anchor_message_missing"
                        batch.error_message = (
                            "Translation anchor message no longer exists"
                        )
                        batch.retry_after = None
                        batch.completed_at = datetime.now(timezone.utc)
                        session.commit()
                        return None

                    rows = session.scalars(
                        select(Message)
                        .where(
                            Message.account_id == batch.account_id,
                            Message.conversation_id == batch.conversation_id,
                            func.coalesce(Message.occurred_at, Message.created_at)
                            <= func.coalesce(anchor.occurred_at, anchor.created_at),
                        )
                        .order_by(
                            func.coalesce(
                                Message.occurred_at, Message.created_at
                            ).desc(),
                            Message.id.desc(),
                        )
                        .limit(batch.window_size)
                    ).all()
                    rows.reverse()

                    plan = self._build_plan(session, batch, rows)
                    # _build_plan may materialize direct/cache translations. Persist
                    # them before the session is closed, then call AI outside it.
                    session.commit()
                    return plan
                except Exception as exc:
                    session.rollback()
                    self._schedule_failure(
                        batch_id,
                        claim_attempt,
                        code="translation_claim_plan_failed",
                        message=str(exc) or type(exc).__name__,
                    )
                    raise
        return None

    def _claim_candidate(
        self,
        session: Session,
        batch: TranslationBatch,
        *,
        now: datetime | None = None,
    ) -> bool:
        """CAS claim helper; exposed privately for deterministic concurrency tests."""

        current = now or datetime.now(timezone.utc)
        expected_status = str(batch.status)
        expected_attempt = int(batch.attempt_count or 0)
        guards = [
            TranslationBatch.id == batch.id,
            TranslationBatch.status == expected_status,
            TranslationBatch.attempt_count == expected_attempt,
            TranslationBatch.attempt_count < self.config.max_attempts,
        ]
        if expected_status in {"pending", "claimed"}:
            guards.append(
                or_(
                    TranslationBatch.retry_after.is_(None),
                    TranslationBatch.retry_after <= current,
                )
            )
        elif expected_status == "running":
            stale_before = current - timedelta(
                seconds=self.config.stale_running_seconds
            )
            guards.append(TranslationBatch.updated_at < stale_before)
        else:
            return False

        result = session.execute(
            update(TranslationBatch)
            .where(*guards)
            .values(
                status="running",
                attempt_count=expected_attempt + 1,
                retry_after=None,
                error_code=None,
                error_message=None,
                completed_at=None,
                updated_at=current,
            )
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount == 1)

    def _next_batch(self, session: Session) -> TranslationBatch | None:
        """挑选可立即尝试的批次；真正所有权由 `_claim_candidate` CAS 决定。"""

        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(seconds=self.config.stale_running_seconds)
        retry_ready = or_(
            TranslationBatch.retry_after.is_(None),
            TranslationBatch.retry_after <= now,
        )
        selectable = or_(
            and_(
                TranslationBatch.status.in_(("pending", "claimed")),
                retry_ready,
            ),
            and_(
                TranslationBatch.status == "running",
                TranslationBatch.updated_at < stale_before,
            ),
        )
        return session.scalar(
            select(TranslationBatch)
            .where(
                selectable,
                TranslationBatch.attempt_count < self.config.max_attempts,
            )
            .order_by(TranslationBatch.created_at.asc(), TranslationBatch.id.asc())
        )

    def _build_plan(
        self,
        session: Session,
        batch: TranslationBatch,
        rows: Sequence[Message],
    ) -> _BatchPlan:
        """把窗口内的消息分成「已完成」「中文直通」与「待翻译」三类。

        已完成的翻译用一次 IN 查询批量取出，替代原先每条消息一次 SELECT。
        """

        candidates: list[tuple[Message, str, str]] = []
        for message in rows:
            text = (message.content or "").strip()
            if not text:
                continue
            candidates.append(
                (message, text, self._source_text_hash(message.content or ""))
            )

        done = self._completed_pairs(
            session, batch.target_lang, [message.id for message, _, _ in candidates]
        )

        unresolved_candidates = [
            (msg, text, shash)
            for msg, text, shash in candidates
            if (msg.id, shash) not in done
        ]

        # 账号内翻译记忆库（按原文哈希查询任一已完成译文）
        global_cache: dict[str, tuple[str, str, str | None]] = {}
        if unresolved_candidates:
            remaining_hashes = list({shash for _, _, shash in unresolved_candidates})
            for chunk in _chunked(remaining_hashes):
                cached_rows = session.execute(
                    select(
                        MessageTranslation.source_text_hash,
                        MessageTranslation.translated_text,
                        MessageTranslation.source_lang,
                        MessageTranslation.model,
                    ).where(
                        MessageTranslation.account_id == batch.account_id,
                        MessageTranslation.source_text_hash.in_(chunk),
                        MessageTranslation.target_lang == batch.target_lang,
                        MessageTranslation.status == "completed",
                        MessageTranslation.translated_text.is_not(None),
                    )
                ).all()
                for row in cached_rows:
                    global_cache[row[0]] = (row[1], row[2], row[3])

        items: list[_PendingItem] = []
        for message, text, source_hash in candidates:
            if (message.id, source_hash) in done:
                continue

            # 1. 全局哈希命中：复用当前账号历史译文，0 次外部 AI 调用
            if source_hash in global_cache:
                cached_trans, cached_lang, _ = global_cache[source_hash]
                self._write_translation(
                    session,
                    message_id=message.id,
                    account_id=message.account_id,
                    conversation_id=message.conversation_id,
                    content=message.content or "",
                    target_lang=batch.target_lang,
                    window_size=batch.window_size,
                    batch_id=batch.id,
                    source_lang=cached_lang or self._language_hint_for(text),
                    translated_text=cached_trans,
                    status="completed",
                )
                continue

            source_lang = self._language_hint_for(text)
            if source_lang == "Chinese":
                # 原文已是中文，无需调用 AI，直接落一条 completed
                self._write_translation(
                    session,
                    message_id=message.id,
                    account_id=message.account_id,
                    conversation_id=message.conversation_id,
                    content=message.content or "",
                    target_lang=batch.target_lang,
                    window_size=batch.window_size,
                    batch_id=batch.id,
                    source_lang=source_lang,
                    translated_text=None,
                    status="completed",
                )
                continue

            # 纯数字、符号、URL 拦截，不送入大模型
            if re.match(r"^https?://\S+$", text, re.IGNORECASE) or (
                re.match(r"^[\d\s\W_]+$", text)
                and not re.search(r"[\u0E80-\u0EFF\u0E00-\u0E7FA-Za-z]", text)
            ):
                self._write_translation(
                    session,
                    message_id=message.id,
                    account_id=message.account_id,
                    conversation_id=message.conversation_id,
                    content=message.content or "",
                    target_lang=batch.target_lang,
                    window_size=batch.window_size,
                    batch_id=batch.id,
                    source_lang=source_lang,
                    translated_text=None,
                    status="completed",
                )
                continue

            items.append(
                _PendingItem(
                    message_id=message.id,
                    account_id=message.account_id,
                    conversation_id=message.conversation_id,
                    content=message.content or "",
                    text=text,
                    source_lang=source_lang,
                )
            )

        return _BatchPlan(
            batch_id=batch.id,
            target_lang=batch.target_lang,
            window_size=batch.window_size,
            claim_attempt=int(batch.attempt_count or 0),
            items=tuple(items),
        )

    @staticmethod
    def _completed_pairs(
        session: Session, target_lang: str, message_ids: Sequence[str]
    ) -> set[tuple[str, str]]:
        if not message_ids:
            return set()
        pairs: set[tuple[str, str]] = set()
        for chunk in _chunked(list(message_ids)):
            rows = session.execute(
                select(
                    MessageTranslation.message_id,
                    MessageTranslation.source_text_hash,
                ).where(
                    MessageTranslation.message_id.in_(chunk),
                    MessageTranslation.target_lang == target_lang,
                    MessageTranslation.status == "completed",
                )
            ).all()
            pairs.update((row[0], row[1]) for row in rows)
        return pairs

    # ------------------------------------------------------------------ 阶段二

    def _translate(self, plan: _BatchPlan) -> list[_MessageOutcome]:
        """在无数据库会话的状态下调用 AI；返回逐条结果。"""

        if not plan.items:
            return []

        worker = self._rewriter()
        window_results = self._translate_window(worker, plan.items)

        outcomes: list[_MessageOutcome] = []
        missing: list[_PendingItem] = []
        for item in plan.items:
            result = window_results.get(item.message_id)
            if result is None:
                missing.append(item)
                continue
            source_lang = str(result.get("source_lang") or item.source_lang)
            if result.get("error"):
                outcomes.append(
                    _MessageOutcome(
                        message_id=item.message_id,
                        source_lang=source_lang,
                        translated_text=None,
                        status="failed",
                        error_code="translate_failed",
                        error_message=str(result["error"]),
                    )
                )
            else:
                outcomes.append(
                    _MessageOutcome(
                        message_id=item.message_id,
                        source_lang=source_lang,
                        translated_text=str(result.get("translated_text") or "")
                        or None,
                        status="completed",
                    )
                )

        if missing:
            outcomes.extend(self._translate_fallback(worker, missing))
        return outcomes

    def _translate_fallback(
        self, worker: Rewriter, items: Sequence[_PendingItem]
    ) -> list[_MessageOutcome]:
        """窗口批量调用未覆盖到的条目逐条补齐。

        原先为纯串行（窗口 20 条即 20 次串行 HTTP），这里按配置并发，
        并对每条结果单独兜底，保证并发下不会因单条异常丢掉整批。
        """

        limit = max(1, int(self.config.max_fallback_concurrency))
        if limit == 1 or len(items) == 1:
            return [self._fallback_one(worker, item) for item in items]

        outcomes: list[_MessageOutcome] = []
        with ThreadPoolExecutor(
            max_workers=min(limit, len(items)),
            thread_name_prefix="translation-fallback",
        ) as pool:
            futures = [pool.submit(self._fallback_one, worker, item) for item in items]
            for future in futures:
                try:
                    outcomes.append(future.result())
                except Exception as exc:  # noqa: BLE001 - 单条失败不应影响整批
                    logger.warning(
                        "Translation fallback task failed", extra={"error": str(exc)}
                    )
        return outcomes

    def _fallback_one(self, worker: Rewriter, item: _PendingItem) -> _MessageOutcome:
        try:
            fallback = worker.translate_to_zh_result(item.text, item.source_lang)
        except Exception as exc:  # noqa: BLE001 - 转为逐条失败结果
            return _MessageOutcome(
                message_id=item.message_id,
                source_lang=item.source_lang,
                translated_text=None,
                status="failed",
                error_code="translate_failed",
                error_message=str(exc),
            )

        fallback_text = (fallback.message or "").strip()
        has_usable_translation = bool(
            fallback_text and fallback_text != item.text.strip()
        )
        if not has_usable_translation:
            return _MessageOutcome(
                message_id=item.message_id,
                source_lang=item.source_lang,
                translated_text=None,
                status="failed",
                error_code="translate_failed",
                error_message="Translation returned no usable result",
            )
        return _MessageOutcome(
            message_id=item.message_id,
            source_lang=item.source_lang,
            translated_text=fallback_text or None,
            status="completed",
        )

    def _translate_window(
        self, worker: Rewriter, pending_items: Sequence[_PendingItem]
    ) -> dict[str, dict[str, Any]]:
        phrase_dict = worker.phrase_dict
        context_block = ""
        if phrase_dict:
            entries = list(phrase_dict.items())[:120]
            dict_section = "\n".join(f'  "{k}" → "{v}"' for k, v in entries)
            context_block = f"# 已知正确翻译\n{dict_section}\n\n"
        payload_items = [
            {
                "message_id": item.message_id,
                "source_lang": item.source_lang,
                "text": item.text,
            }
            for item in pending_items
        ]
        prompt = (
            "你是一个高精度聊天翻译器。请把输入 items 中每条消息翻译成简体中文。\n"
            "要求：\n"
            "1. 保留语气、情感、emoji。\n"
            "2. 不要合并消息，不要漏项。\n"
            "3. 若原文已经是中文，zh 置为空字符串。\n"
            '4. 只输出合法 JSON：{"items":[{"message_id":"...","source_lang":"...","zh":"..."}]}。\n\n'
            + context_block
            + json.dumps({"items": payload_items}, ensure_ascii=False)
        )
        try:
            result = worker.ai_service.chat(
                messages=[
                    {"role": "system", "content": "你只返回合法 JSON，不要输出解释。"},
                    {"role": "user", "content": prompt},
                ],
                account_model=worker._account_model(),
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            parsed = json.loads(result.result.content)
            items = parsed.get("items") or []
            output: dict[str, dict[str, Any]] = {}
            expected = {item.message_id: item.text.strip() for item in pending_items}
            for row in items:
                if not isinstance(row, dict):
                    continue
                message_id = str(row.get("message_id") or "").strip()
                translated = row.get("zh")
                if (
                    message_id not in expected
                    or not isinstance(translated, str)
                    or not translated.strip()
                    or translated.strip() == expected[message_id]
                ):
                    continue
                output[message_id] = {
                    "source_lang": str(row.get("source_lang") or ""),
                    "translated_text": translated.strip(),
                }
            return output
        except Exception as exc:
            logger.warning(
                "Translation window batch call failed; falling back to per-message translate",
                extra={"error": str(exc), "items": len(pending_items)},
            )
            return {}

    # ------------------------------------------------------------------ 阶段三

    def _finalize(self, plan: _BatchPlan, outcomes: Sequence[_MessageOutcome]) -> None:
        """按 claim attempt 写入结果；迟到 Worker 不得覆盖新一轮领取。"""

        by_id = {item.message_id: item for item in plan.items}
        with self.session_factory() as session:
            batch = session.get(TranslationBatch, plan.batch_id)
            if batch is None:
                logger.warning(
                    "Translation batch disappeared before finalize",
                    extra={"batch_id": plan.batch_id},
                )
                return
            if (
                batch.status != "running"
                or int(batch.attempt_count or 0) != plan.claim_attempt
            ):
                logger.info(
                    "Ignoring stale translation worker result",
                    extra={
                        "batch_id": plan.batch_id,
                        "claim_attempt": plan.claim_attempt,
                        "current_attempt": batch.attempt_count,
                        "current_status": batch.status,
                    },
                )
                return

            existing = self._existing_translation_rows(
                session,
                plan.target_lang,
                [
                    (item.message_id, self._source_text_hash(item.content))
                    for item in plan.items
                ],
            )
            touched: dict[str, MessageTranslation] = {}
            for outcome in outcomes:
                item = by_id.get(outcome.message_id)
                if item is None:
                    continue
                row = existing.get(
                    (item.message_id, self._source_text_hash(item.content))
                )
                if row is None:
                    row = MessageTranslation(
                        account_id=item.account_id,
                        conversation_id=item.conversation_id,
                        message_id=item.message_id,
                        target_lang=plan.target_lang,
                        source_text_hash=self._source_text_hash(item.content),
                    )
                    session.add(row)
                self._apply_translation_fields(
                    row,
                    content=item.content,
                    source_lang=outcome.source_lang,
                    translated_text=outcome.translated_text,
                    status=outcome.status,
                    error_code=outcome.error_code,
                    error_message=outcome.error_message,
                    window_size=plan.window_size,
                    batch_id=plan.batch_id,
                )
                touched[outcome.message_id] = row

            failures = sum(outcome.status != "completed" for outcome in outcomes)
            if failures:
                self._apply_failure_state(
                    batch,
                    code="translation_items_failed",
                    message=f"{failures} messages need retry",
                )
                for outcome in outcomes:
                    if outcome.status != "completed":
                        row = touched.get(outcome.message_id)
                        if row is not None:
                            row.retry_after = batch.retry_after
                            if batch.status == "dead":
                                row.status = "dead"
            else:
                batch.status = "completed"
                batch.error_code = None
                batch.error_message = None
                batch.retry_after = None
                batch.completed_at = datetime.now(timezone.utc)
            session.commit()

    @staticmethod
    def _existing_translation_rows(
        session: Session,
        target_lang: str,
        pairs: Sequence[tuple[str, str]],
    ) -> dict[tuple[str, str], MessageTranslation]:
        if not pairs:
            return {}
        message_ids = list({message_id for message_id, _ in pairs})
        found: dict[tuple[str, str], MessageTranslation] = {}
        for chunk in _chunked(message_ids):
            for row in session.scalars(
                select(MessageTranslation).where(
                    MessageTranslation.message_id.in_(chunk),
                    MessageTranslation.target_lang == target_lang,
                )
            ).all():
                found[(row.message_id, row.source_text_hash)] = row
        return found

    @staticmethod
    def _apply_translation_fields(
        row: MessageTranslation,
        *,
        content: str,
        source_lang: str,
        translated_text: str | None,
        status: str,
        error_code: str | None,
        error_message: str | None,
        window_size: int,
        batch_id: str,
    ) -> None:
        row.source_text = content
        row.source_lang = source_lang
        row.translated_text = translated_text
        row.status = status
        row.error_code = error_code
        row.error_message = error_message
        row.provider = "wendingai"
        row.context_window_size = window_size
        row.batch_id = batch_id
        row.retry_after = None
        row.completed_at = datetime.now(timezone.utc) if status == "completed" else None

    def _retry_delay_seconds(self, attempt_count: int) -> float:
        base = max(0.0, float(self.config.retry_base_seconds))
        maximum = max(base, float(self.config.retry_max_seconds))
        if base == 0:
            return 0.0
        return min(maximum, base * (2 ** max(0, attempt_count - 1)))

    def _apply_failure_state(
        self,
        batch: TranslationBatch,
        *,
        code: str,
        message: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        batch.error_code = code
        batch.error_message = message
        if int(batch.attempt_count or 0) >= self.config.max_attempts:
            batch.status = "dead"
            batch.retry_after = None
            batch.completed_at = now
            return
        batch.status = "pending"
        batch.retry_after = now + timedelta(
            seconds=self._retry_delay_seconds(int(batch.attempt_count or 0))
        )
        batch.completed_at = None

    def _schedule_failure(
        self,
        batch_id: str,
        claim_attempt: int,
        *,
        code: str,
        message: str,
    ) -> None:
        with self.session_factory() as session:
            row = session.get(TranslationBatch, batch_id)
            if row is None:
                return
            if row.status != "running" or int(row.attempt_count or 0) != claim_attempt:
                return
            self._apply_failure_state(row, code=code, message=message)
            session.commit()

    def _mark_failed(self, plan: _BatchPlan, exc: Exception) -> None:
        self._schedule_failure(
            plan.batch_id,
            plan.claim_attempt,
            code="translation_batch_failed",
            message=str(exc) or type(exc).__name__,
        )

    # ------------------------------------------------------------------ 辅助

    def _rewriter(self) -> Rewriter:
        # 实例级缓存：批次之间复用 Provider 连接池（PERF-003）
        if self._cached_rewriter is not None:
            return self._cached_rewriter

        class _DummyAppPaths:
            memory_dir: Any

            def __init__(self, memory_dir: Any) -> None:
                self.memory_dir = memory_dir

        class _DummyConfig:
            paths: _DummyAppPaths
            ai_settings: Any

            def __init__(self, memory_dir: Any, ai_settings: Any) -> None:
                self.paths = _DummyAppPaths(memory_dir)
                self.ai_settings = ai_settings

        config = _DummyConfig(self.runtime.paths.memory_dir, self.runtime.ai_settings)
        self._cached_rewriter = Rewriter(
            config, lambda *args, **kwargs: None, runtime_manager=self.runtime_manager
        )
        return self._cached_rewriter

    def _write_translation(
        self,
        session: Session,
        *,
        message_id: str,
        account_id: str,
        conversation_id: str,
        content: str,
        target_lang: str,
        window_size: int,
        batch_id: str,
        source_lang: str,
        translated_text: str | None,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> MessageTranslation:
        source_hash = self._source_text_hash(content)
        row = session.scalar(
            select(MessageTranslation).where(
                MessageTranslation.message_id == message_id,
                MessageTranslation.target_lang == target_lang,
                MessageTranslation.source_text_hash == source_hash,
            )
        )
        if row is None:
            row = MessageTranslation(
                account_id=account_id,
                conversation_id=conversation_id,
                message_id=message_id,
                target_lang=target_lang,
                source_text_hash=source_hash,
            )
            session.add(row)
        self._apply_translation_fields(
            row,
            content=content,
            source_lang=source_lang,
            translated_text=translated_text,
            status=status,
            error_code=error_code,
            error_message=error_message,
            window_size=window_size,
            batch_id=batch_id,
        )
        return row

    @staticmethod
    def _language_hint_for(text: str) -> str:
        if not text:
            return "Unknown"
        if re.search(r"[\u0E80-\u0EFF]", text):
            return "Lao"
        if re.search(r"[\u0E00-\u0E7F]", text):
            return "Thai"
        if re.search(r"[\u4E00-\u9FFF]", text):
            return "Chinese"
        if re.search(r"[A-Za-z]", text):
            return "Latin"
        return "Unknown"

    @staticmethod
    def _source_text_hash(text: str) -> str:
        return source_text_hash(text)

    def health(self) -> dict[str, Any]:
        return {
            "last_heartbeat": self.last_heartbeat.isoformat()
            if self.last_heartbeat
            else None,
            "last_error": self.last_error,
            "processed_batches": self.processed_batches,
            "failed_batches": self.failed_batches,
        }
