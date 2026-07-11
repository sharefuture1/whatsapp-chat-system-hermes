from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import Callable

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from whatsapp_chat_system.db.models import AnalysisJob, Contact, Conversation, WhatsAppAccount


class JobConflict(RuntimeError):
    """任务状态、版本、所有者、幂等输入或负载保护发生冲突。"""


class JobScopeViolation(LookupError):
    """任务或关联对象不属于给定账号范围。"""


@dataclass(frozen=True)
class JobLease:
    id: str
    account_id: str
    contact_id: str | None
    conversation_id: str | None
    parent_job_id: str | None
    job_type: str
    input_hash: str
    status: str
    version: int
    lease_owner: str
    lease_expires_at: datetime
    attempts: int
    max_attempts: int
    budget_tokens: int
    budget_cost: Decimal


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _db_time(value: datetime, dialect: str) -> datetime:
    """PostgreSQL 保留 UTC aware；SQLite 以 UTC naive 适配其驱动。"""
    value = _utc(value)
    return value.replace(tzinfo=None) if dialect == "sqlite" else value


def _aware(value: datetime | None) -> datetime | None:
    return None if value is None else _utc(value)


def _text(name: str, value: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be non-empty and <= {maximum} characters")
    return value


def _integer(name: str, value: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _hash(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise ValueError("input_hash must be a canonical immutable payload SHA-256 hex digest")
    return value.lower()


def _money(value: Decimal | int | str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("budget_cost must be a finite non-negative decimal") from exc
    if not result.is_finite() or result < 0 or result > Decimal("1000000000"):
        raise ValueError("budget_cost must be between 0 and 1000000000")
    return result


def _progress(total: int, completed: int, failed: int) -> None:
    for name, value in (("progress_total", total), ("progress_completed", completed), ("progress_failed", failed)):
        _integer(name, value, 0, 2_147_483_647)
    if completed + failed > total:
        raise ValueError("progress completed + failed cannot exceed total")


def build_postgres_claim_query(account_id: str | None, now: datetime,
        max_job_budget_tokens: int | None = None,
        max_job_budget_cost: Decimal | int | str | None = None,
        max_active_per_account: int | None = None) -> Select:
    parent = AnalysisJob.__table__.alias("parent")
    active_job = AnalysisJob.__table__.alias("active_job")
    query = select(AnalysisJob).where(
        AnalysisJob.status.in_(("pending", "retry")), AnalysisJob.available_at <= _utc(now),
        AnalysisJob.attempts < AnalysisJob.max_attempts,
        or_(AnalysisJob.parent_job_id.is_(None), ~select(parent.c.id).where(
            parent.c.id == AnalysisJob.parent_job_id,
            parent.c.status.in_(("completed", "failed", "dead", "cancelled"))).exists()))
    if account_id is not None:
        query = query.where(AnalysisJob.account_id == account_id)
    if max_job_budget_tokens is not None:
        query = query.where(or_(AnalysisJob.budget_tokens == 0,
                                AnalysisJob.budget_tokens <= max_job_budget_tokens))
    if max_job_budget_cost is not None:
        query = query.where(or_(AnalysisJob.budget_cost == 0,
                                AnalysisJob.budget_cost <= _money(max_job_budget_cost)))
    if max_active_per_account is not None:
        query = query.where(select(func.count()).select_from(active_job).where(
            active_job.c.account_id == AnalysisJob.account_id,
            active_job.c.status.in_(("claimed", "running"))).scalar_subquery() < max_active_per_account)
    return query.order_by(AnalysisJob.priority.desc(), AnalysisJob.available_at.asc(),
                          AnalysisJob.created_at.asc()).limit(1).with_for_update(skip_locked=True)


def build_parent_lock_query(parent_job_id: str, account_id: str) -> Select:
    return select(AnalysisJob).where(AnalysisJob.id == parent_job_id,
        AnalysisJob.account_id == account_id).with_for_update()


def build_postgres_recovery_query(now: datetime, limit: int,
                                  account_id: str | None = None) -> Select:
    query = select(AnalysisJob).where(
        AnalysisJob.status.in_(("claimed", "running")),
        AnalysisJob.lease_expires_at <= _utc(now))
    if account_id is not None:
        query = query.where(AnalysisJob.account_id == account_id)
    return query.order_by(AnalysisJob.lease_expires_at, AnalysisJob.created_at).limit(
        limit).with_for_update(skip_locked=True)


class AnalysisJobRepository:
    def __init__(self, session: Session):
        self.session = session

    @property
    def dialect(self) -> str:
        return self.session.get_bind().dialect.name

    def _time(self, value: datetime | None = None) -> datetime:
        return _db_time(_utc(value), self.dialect)

    def _account(self, account_id: str) -> None:
        _text("account_id", account_id, 36)
        if self.session.scalar(select(WhatsAppAccount.id).where(WhatsAppAccount.id == account_id)) is None:
            raise JobScopeViolation("account is outside scope")

    def _job(self, job_id: str, account_id: str | None = None) -> AnalysisJob:
        query = select(AnalysisJob).where(AnalysisJob.id == job_id)
        if account_id is not None:
            query = query.where(AnalysisJob.account_id == account_id)
        job = self.session.scalar(query.execution_options(populate_existing=True))
        if job is None:
            raise JobScopeViolation("job is outside scope")
        return job

    def _validate_scope(self, account_id: str, contact_id: str | None,
                        conversation_id: str | None, parent_job_id: str | None) -> None:
        self._account(account_id)
        if contact_id is not None and self.session.scalar(select(Contact.id).where(
                Contact.id == contact_id, Contact.account_id == account_id)) is None:
            raise JobScopeViolation("contact is outside scope")
        if conversation_id is not None:
            query = select(Conversation.id).where(Conversation.id == conversation_id,
                                                   Conversation.account_id == account_id)
            if contact_id is not None:
                query = query.where(Conversation.contact_id == contact_id)
            if self.session.scalar(query) is None:
                raise JobScopeViolation("conversation is outside scope")
        if parent_job_id is not None:
            parent = self.session.scalar(build_parent_lock_query(parent_job_id, account_id))
            if parent is None:
                raise JobScopeViolation("parent job is outside scope")
            if parent.status not in ("pending", "retry", "claimed", "running"):
                raise JobConflict("parent job no longer accepts children")

    @staticmethod
    def _same_request(job: AnalysisJob, *, input_hash: str, job_type: str,
                      contact_id: str | None, conversation_id: str | None,
                      parent_job_id: str | None, priority: int, budget_tokens: int,
                      budget_cost: Decimal) -> bool:
        return (job.input_hash == input_hash and job.job_type == job_type and
                job.contact_id == contact_id and job.conversation_id == conversation_id and
                job.parent_job_id == parent_job_id and job.priority == priority and
                job.budget_tokens == budget_tokens and Decimal(job.budget_cost) == budget_cost)

    def enqueue(self, account_id: str, job_type: str, idempotency_key: str, input_hash: str,
                contact_id: str | None = None, conversation_id: str | None = None,
                parent_job_id: str | None = None, priority: int = 0,
                available_at: datetime | None = None, max_attempts: int = 3,
                budget_tokens: int = 0, budget_cost: Decimal | int | str = 0,
                progress_total: int = 0, progress_completed: int = 0,
                progress_failed: int = 0, max_queued_per_account: int | None = None) -> AnalysisJob:
        job_type = _text("job_type", job_type, 64)
        idempotency_key = _text("idempotency_key", idempotency_key, 255)
        input_hash = _hash(input_hash)
        priority = _integer("priority", priority, 0, 2_147_483_647)
        max_attempts = _integer("max_attempts", max_attempts, 1, 1000)
        budget_tokens = _integer("budget_tokens", budget_tokens, 0, 10**12)
        budget_cost = _money(budget_cost)
        _progress(progress_total, progress_completed, progress_failed)
        if max_queued_per_account is not None:
            _integer("max_queued_per_account", max_queued_per_account, 1, 1_000_000)
        self._validate_scope(account_id, contact_id, conversation_id, parent_job_id)
        fields = dict(input_hash=input_hash, job_type=job_type, contact_id=contact_id,
                      conversation_id=conversation_id, parent_job_id=parent_job_id,
                      priority=priority, budget_tokens=budget_tokens, budget_cost=budget_cost)
        existing = self.session.scalar(select(AnalysisJob).where(
            AnalysisJob.account_id == account_id,
            AnalysisJob.idempotency_key == idempotency_key).execution_options(populate_existing=True))
        if existing is not None:
            if not self._same_request(existing, **fields):
                raise JobConflict("idempotency key identifies a different immutable request")
            return existing
        job = AnalysisJob(account_id=account_id,
            idempotency_key=idempotency_key, available_at=self._time(available_at),
            max_attempts=max_attempts, progress_total=progress_total,
            progress_completed=progress_completed, progress_failed=progress_failed, **fields)
        try:
            with self.session.begin_nested():
                if max_queued_per_account is not None:
                    count = self.session.scalar(select(func.count()).select_from(AnalysisJob).where(
                        AnalysisJob.account_id == account_id,
                        AnalysisJob.status.in_(("pending", "retry", "claimed", "running")))) or 0
                    if count >= max_queued_per_account:
                        raise JobConflict("account queue backpressure limit reached")
                self.session.add(job); self.session.flush()
        except IntegrityError as exc:
            winner = self.session.scalar(select(AnalysisJob).where(
                AnalysisJob.account_id == account_id,
                AnalysisJob.idempotency_key == idempotency_key).execution_options(populate_existing=True))
            if winner is not None and self._same_request(winner, **fields):
                return winner
            raise JobConflict("idempotency key was concurrently used for another request") from exc
        return job

    def claim_next(self, worker_id: str, lease_seconds: int, account_id: str | None = None,
                   now: datetime | None = None, max_claim_attempts: int = 8,
                   max_active_global: int | None = 1000,
                   max_active_per_account: int | None = 100,
                   max_job_budget_tokens: int | None = None,
                   max_job_budget_cost: Decimal | int | str | None = None) -> AnalysisJob | None:
        """Transaction-scoped internal claim；调用方必须立即 commit，AI worker 应用 committed wrapper。"""
        worker_id = _text("worker_id", worker_id, 255)
        lease_seconds = _integer("lease_seconds", lease_seconds, 1, 3600)
        max_claim_attempts = _integer("max_claim_attempts", max_claim_attempts, 1, 100)
        for name, value in (("max_active_global", max_active_global),
                            ("max_active_per_account", max_active_per_account)):
            if value is not None: _integer(name, value, 1, 1_000_000)
        if max_job_budget_tokens is not None:
            _integer("max_job_budget_tokens", max_job_budget_tokens, 0, 10**12)
        if max_job_budget_cost is not None: max_job_budget_cost = _money(max_job_budget_cost)
        moment = self._time(now); expires = self._time(_utc(now) + timedelta(seconds=lease_seconds))
        active = ("claimed", "running")
        with self.session.begin_nested():
            if max_active_global is not None:
                count = self.session.scalar(select(func.count()).select_from(AnalysisJob).where(
                    AnalysisJob.status.in_(active))) or 0
                if count >= max_active_global: return None
            if account_id is not None and max_active_per_account is not None:
                count = self.session.scalar(select(func.count()).select_from(AnalysisJob).where(
                    AnalysisJob.account_id == account_id, AnalysisJob.status.in_(active))) or 0
                if count >= max_active_per_account: return None
            parent = AnalysisJob.__table__.alias("parent_claim")
            for _ in range(max_claim_attempts):
                if self.dialect == "postgresql":
                    candidate = self.session.scalar(build_postgres_claim_query(
                        account_id, _utc(now), max_job_budget_tokens, max_job_budget_cost,
                        max_active_per_account))
                    candidate_id = None if candidate is None else candidate.id
                else:
                    parent = AnalysisJob.__table__.alias("parent")
                    active_job = AnalysisJob.__table__.alias("active_job")
                    query = select(AnalysisJob.id).where(
                        AnalysisJob.status.in_(("pending", "retry")),
                        AnalysisJob.available_at <= moment,
                        AnalysisJob.attempts < AnalysisJob.max_attempts,
                        or_(AnalysisJob.parent_job_id.is_(None), select(parent.c.id).where(
                            parent.c.id == AnalysisJob.parent_job_id,
                            parent.c.status.in_(("pending", "retry", "claimed", "running"))).exists()))
                    if account_id is not None: query = query.where(AnalysisJob.account_id == account_id)
                    if max_job_budget_tokens is not None: query = query.where(or_(
                        AnalysisJob.budget_tokens == 0, AnalysisJob.budget_tokens <= max_job_budget_tokens))
                    if max_job_budget_cost is not None: query = query.where(or_(
                        AnalysisJob.budget_cost == 0, AnalysisJob.budget_cost <= max_job_budget_cost))
                    if max_active_per_account is not None: query = query.where(
                        select(func.count()).select_from(active_job).where(
                            active_job.c.account_id == AnalysisJob.account_id,
                            active_job.c.status.in_(active)).scalar_subquery() < max_active_per_account)
                    candidate_id = self.session.scalar(query.order_by(
                        AnalysisJob.priority.desc(), AnalysisJob.available_at.asc(),
                        AnalysisJob.created_at.asc()).limit(1))
                if candidate_id is None: return None
                result = self.session.execute(update(AnalysisJob).where(
                    AnalysisJob.id == candidate_id, AnalysisJob.status.in_(("pending", "retry")),
                    AnalysisJob.available_at <= moment,
                    AnalysisJob.attempts < AnalysisJob.max_attempts,
                    or_(AnalysisJob.parent_job_id.is_(None), select(parent.c.id).where(
                        parent.c.id == AnalysisJob.parent_job_id,
                        parent.c.status.in_(("pending", "retry", "claimed", "running"))).exists())).values(
                    status="claimed", lease_owner=worker_id, lease_expires_at=expires,
                    attempts=AnalysisJob.attempts + 1, version=AnalysisJob.version + 1,
                    updated_at=moment))
                if result.rowcount == 1: return self._job(candidate_id)
        return None

    def _lease_cas(self, account_id: str, job_id: str, worker_id: str, expected_version: int,
                   statuses: tuple[str, ...], now: datetime, values: dict,
                   input_hash: str | None = None) -> AnalysisJob:
        worker_id = _text("worker_id", worker_id, 255)
        expected_version = _integer("expected_version", expected_version, 1, 2_147_483_647)
        moment = self._time(now)
        parent = AnalysisJob.__table__.alias("parent")
        conditions = [AnalysisJob.id == job_id, AnalysisJob.account_id == account_id,
            AnalysisJob.lease_owner == worker_id, AnalysisJob.version == expected_version,
            AnalysisJob.status.in_(statuses), AnalysisJob.lease_expires_at > moment,
            or_(AnalysisJob.parent_job_id.is_(None), ~select(parent.c.id).where(
                parent.c.id == AnalysisJob.parent_job_id,
                parent.c.status == "cancelled").exists())]
        if input_hash is not None: conditions.append(AnalysisJob.input_hash == _hash(input_hash))
        with self.session.begin_nested():
            job = self._job(job_id, account_id)
            if job.parent_job_id is not None:
                parent_job = self.session.scalar(build_parent_lock_query(job.parent_job_id, account_id))
                if parent_job is None or parent_job.status not in ("pending", "retry", "claimed", "running"):
                    raise JobConflict("parent job is cancelled or terminal")
            result = self.session.execute(update(AnalysisJob).where(*conditions).values(
                **values, version=expected_version + 1, updated_at=moment))
            if result.rowcount != 1: raise JobConflict("job lease, account, parent or version is stale")
        return self._job(job_id, account_id)

    def start(self, account_id: str, job_id: str, worker_id: str, expected_version: int,
              now: datetime | None = None) -> AnalysisJob:
        return self._lease_cas(account_id, job_id, worker_id, expected_version,
                               ("claimed",), _utc(now), {"status": "running"})

    def heartbeat(self, account_id: str, job_id: str, worker_id: str, expected_version: int,
                  lease_seconds: int, now: datetime | None = None) -> AnalysisJob:
        lease_seconds = _integer("lease_seconds", lease_seconds, 1, 3600); moment = _utc(now)
        return self._lease_cas(account_id, job_id, worker_id, expected_version,
            ("claimed", "running"), moment,
            {"lease_expires_at": self._time(moment + timedelta(seconds=lease_seconds))})

    def complete(self, account_id: str, job_id: str, worker_id: str, expected_version: int,
                 input_hash: str, progress_total: int | None = None,
                 progress_completed: int | None = None, progress_failed: int | None = None,
                 now: datetime | None = None) -> AnalysisJob:
        job = self._job(job_id, account_id)
        total = job.progress_total if progress_total is None else progress_total
        completed = job.progress_completed if progress_completed is None else progress_completed
        failed = job.progress_failed if progress_failed is None else progress_failed
        _progress(total, completed, failed)
        return self._lease_cas(account_id, job_id, worker_id, expected_version,
            ("claimed", "running"), _utc(now), {"status": "completed", "lease_owner": None,
            "lease_expires_at": None, "progress_total": total,
            "progress_completed": completed, "progress_failed": failed}, input_hash=input_hash)

    def fail(self, account_id: str, job_id: str, worker_id: str, expected_version: int,
             error_code: str, retry_delay_seconds: int, now: datetime | None = None) -> AnalysisJob:
        _text("error_code", error_code, 128)
        retry_delay_seconds = _integer("retry_delay_seconds", retry_delay_seconds, 0, 86400)
        job = self._job(job_id, account_id); moment = _utc(now); retry = job.attempts < job.max_attempts
        values = {"status": "retry" if retry else "dead", "lease_owner": None,
                  "lease_expires_at": None}
        if retry: values["available_at"] = self._time(moment + timedelta(seconds=retry_delay_seconds))
        return self._lease_cas(account_id, job_id, worker_id, expected_version,
                               ("claimed", "running"), moment, values)

    def cancel(self, account_id: str, job_id: str, expected_version: int) -> AnalysisJob:
        """cancelled 表示结果将被拒绝；不保证中断已开始的外部调用或强抢子任务 lease。"""
        moment = self._time()
        with self.session.begin_nested():
            if self.session.scalar(build_parent_lock_query(job_id, account_id)) is None:
                raise JobScopeViolation("job is outside scope")
            result = self.session.execute(update(AnalysisJob).where(
                AnalysisJob.id == job_id, AnalysisJob.account_id == account_id,
                AnalysisJob.version == expected_version,
                AnalysisJob.status.in_(("pending", "retry", "claimed", "running"))).values(
                status="cancelled", lease_owner=None, lease_expires_at=None,
                version=expected_version + 1, updated_at=moment))
            if result.rowcount != 1: raise JobConflict("job cannot be cancelled")
            self.session.execute(update(AnalysisJob).where(
                AnalysisJob.parent_job_id == job_id, AnalysisJob.account_id == account_id,
                AnalysisJob.status.in_(("pending", "retry"))).values(
                status="cancelled", version=AnalysisJob.version + 1, updated_at=moment))
        return self._job(job_id, account_id)

    def recover_expired_leases(self, now: datetime | None = None, limit: int = 100,
                               account_id: str | None = None) -> int:
        limit = _integer("limit", limit, 1, 1000); moment = self._time(now)
        with self.session.begin_nested():
            if self.dialect == "postgresql":
                jobs = list(self.session.scalars(build_postgres_recovery_query(_utc(now), limit, account_id)))
            else:
                query = select(AnalysisJob).where(AnalysisJob.status.in_(("claimed", "running")),
                    AnalysisJob.lease_expires_at <= moment)
                if account_id is not None: query = query.where(AnalysisJob.account_id == account_id)
                jobs = list(self.session.scalars(query.order_by(
                    AnalysisJob.lease_expires_at, AnalysisJob.created_at).limit(limit)))
            recovered = 0
            parent_ids = {job.parent_job_id for job in jobs if job.parent_job_id is not None}
            parent_statuses = dict(self.session.execute(select(AnalysisJob.id, AnalysisJob.status).where(
                AnalysisJob.id.in_(parent_ids))).all() if parent_ids else [])
            for job in jobs:
                parent_cancelled = (job.parent_job_id is not None and
                                    parent_statuses.get(job.parent_job_id) == "cancelled")
                result = self.session.execute(update(AnalysisJob).where(
                    AnalysisJob.id == job.id, AnalysisJob.account_id == job.account_id,
                    AnalysisJob.version == job.version,
                    AnalysisJob.status.in_(("claimed", "running")),
                    AnalysisJob.lease_expires_at <= moment).values(
                    status="cancelled" if parent_cancelled else (
                        "retry" if job.attempts < job.max_attempts else "dead"),
                    available_at=moment, lease_owner=None, lease_expires_at=None,
                    version=job.version + 1, updated_at=moment))
                recovered += result.rowcount
        return recovered

    def get(self, account_id: str, job_id: str) -> AnalysisJob:
        return self._job(job_id, account_id)


def claim_next_committed(session_factory: Callable[[], Session], *args, **kwargs) -> JobLease | None:
    """AI worker 的公开短事务入口：claim、commit、复制不可变 lease DTO 并关闭 Session。"""
    with session_factory() as session:
        job = AnalysisJobRepository(session).claim_next(*args, **kwargs)
        if job is None:
            session.commit(); return None
        session.flush()
        lease = JobLease(id=job.id, account_id=job.account_id, contact_id=job.contact_id,
            conversation_id=job.conversation_id, parent_job_id=job.parent_job_id,
            job_type=job.job_type, input_hash=job.input_hash, status=job.status,
            version=job.version, lease_owner=job.lease_owner,
            lease_expires_at=_aware(job.lease_expires_at), attempts=job.attempts,
            max_attempts=job.max_attempts, budget_tokens=job.budget_tokens,
            budget_cost=Decimal(job.budget_cost))
        session.commit()
        return lease


__all__ = ["AnalysisJobRepository", "JobConflict", "JobLease", "JobScopeViolation",
           "build_postgres_claim_query", "build_parent_lock_query", "build_postgres_recovery_query",
           "claim_next_committed", "_db_time"]
