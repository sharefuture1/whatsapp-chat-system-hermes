from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker

from whatsapp_chat_system.ai.job_repository import (
    AnalysisJobRepository,
    JobLease,
    JobConflict,
    JobScopeViolation,
    _db_time,
    build_postgres_claim_query,
    build_parent_lock_query,
    build_postgres_recovery_query,
    claim_next_committed,
)
from whatsapp_chat_system.db.base import Base
from whatsapp_chat_system.db.models import AnalysisJob, Contact, Conversation, WhatsAppAccount

UTC = timezone.utc


def _engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}", connect_args={"timeout": 5})
    @event.listens_for(engine, "connect")
    def _fk(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    return engine


def _scope(session: Session, suffix="a"):
    account = WhatsAppAccount(name=f"A-{suffix}", session_ref=f"job:{suffix}")
    session.add(account); session.flush()
    contact = Contact(account_id=account.id, remote_jid=f"{suffix}@s.whatsapp.net")
    session.add(contact); session.flush()
    conversation = Conversation(account_id=account.id, contact_id=contact.id,
        remote_jid=contact.remote_jid, type="dm")
    session.add(conversation); session.flush()
    return account, contact, conversation


def _enqueue(repo, account_id, key="k", input_hash="a" * 64, **kwargs):
    return repo.enqueue(account_id, "profile_refresh", key, input_hash, **kwargs)


def test_enqueue_is_scoped_idempotent_atomic_and_session_recovers(tmp_path):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        a1, c1, v1 = _scope(session, "1")
        a2, c2, v2 = _scope(session, "2")
        repo = AnalysisJobRepository(session)
        first = _enqueue(repo, a1.id, contact_id=c1.id, conversation_id=v1.id)
        assert _enqueue(repo, a1.id, contact_id=c1.id, conversation_id=v1.id).id == first.id
        with pytest.raises(JobConflict):
            _enqueue(repo, a1.id, input_hash="b" * 64)
        with pytest.raises(JobScopeViolation):
            _enqueue(repo, a1.id, key="bad-contact", contact_id=c2.id)
        with pytest.raises(JobScopeViolation):
            _enqueue(repo, a1.id, key="bad-conversation", contact_id=c1.id, conversation_id=v2.id)
        with pytest.raises(JobScopeViolation):
            _enqueue(repo, a1.id, key="bad-parent", parent_job_id=_enqueue(repo, a2.id, key="p").id)
        assert repo.get(a1.id, first.id).id == first.id
        session.commit()


def test_claim_order_account_filter_and_two_sessions_cannot_claim_same_job(tmp_path):
    engine = _engine(tmp_path); factory = sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 7, 11, 12, tzinfo=UTC)
    with factory() as setup:
        a1, _, _ = _scope(setup, "1"); a2, _, _ = _scope(setup, "2")
        repo = AnalysisJobRepository(setup)
        low = _enqueue(repo, a1.id, key="low", priority=1, available_at=now - timedelta(minutes=3))
        high_late = _enqueue(repo, a1.id, key="high-late", priority=9, available_at=now - timedelta(minutes=1))
        high_early = _enqueue(repo, a1.id, key="high-early", priority=9, available_at=now - timedelta(minutes=2))
        _enqueue(repo, a1.id, key="future", priority=99, available_at=now + timedelta(seconds=1))
        other = _enqueue(repo, a2.id, key="other", priority=100, available_at=now - timedelta(minutes=5))
        setup.commit()
    with factory() as s1, factory() as s2:
        one = AnalysisJobRepository(s1).claim_next("w1", 30, account_id=a1.id, now=now)
        assert one.id == high_early.id and one.status == "claimed" and one.attempts == 1 and one.version == 2
        s1.commit()
        two = AnalysisJobRepository(s2).claim_next("w2", 30, account_id=a1.id, now=now)
        assert two.id == high_late.id
        s2.commit()
    with factory() as s1, factory() as s2:
        claimed = AnalysisJobRepository(s1).claim_next("w3", 30, account_id=a2.id, now=now)
        s1.commit()
        assert claimed.id == other.id
        assert AnalysisJobRepository(s2).claim_next("w4", 30, account_id=a2.id, now=now) is None


def test_start_heartbeat_complete_enforce_owner_version_lease_and_input_hash(tmp_path):
    engine = _engine(tmp_path); now = datetime(2026, 7, 11, 12, tzinfo=UTC)
    with Session(engine) as session:
        account, _, _ = _scope(session); repo = AnalysisJobRepository(session)
        job = _enqueue(repo, account.id)
        job = repo.claim_next("worker", 10, now=now)
        with pytest.raises(JobConflict): repo.start(account.id, job.id, "other", job.version, now=now)
        job = repo.start(account.id, job.id, "worker", job.version, now=now)
        job = repo.heartbeat(account.id, job.id, "worker", job.version, 30, now=now + timedelta(seconds=5))
        heartbeat_version = job.version
        assert job.lease_expires_at.replace(tzinfo=UTC) == now + timedelta(seconds=35)
        with pytest.raises(JobConflict):
            repo.complete(account.id, job.id, "worker", job.version, "b" * 64,
                          progress_total=1, progress_completed=1)
        assert repo.get(account.id, job.id).status == "running"
        done = repo.complete(account.id, job.id, "worker", job.version, "a" * 64,
            progress_total=2, progress_completed=2, progress_failed=0, now=now + timedelta(seconds=6))
        assert done.status == "completed" and done.lease_owner is None and done.version == heartbeat_version + 1
        with pytest.raises(JobConflict): repo.complete(account.id, done.id, "worker", heartbeat_version, "a" * 64)


def test_expired_lease_rejects_worker_and_recovery_invalidates_old_version(tmp_path):
    engine = _engine(tmp_path); now = datetime(2026, 7, 11, 12, tzinfo=UTC)
    with Session(engine) as session:
        account, _, _ = _scope(session); repo = AnalysisJobRepository(session)
        _enqueue(repo, account.id)
        claimed = repo.claim_next("old", 1, now=now)
        old_version = claimed.version
        with pytest.raises(JobConflict): repo.heartbeat(account.id, claimed.id, "old", old_version, 10, now=now + timedelta(seconds=2))
        recovered = repo.recover_expired_leases(now=now + timedelta(seconds=2))
        assert recovered == 1
        current = repo.get(account.id, claimed.id)
        assert current.status == "retry" and current.version == old_version + 1 and current.lease_owner is None
        with pytest.raises(JobConflict): repo.complete(account.id, claimed.id, "old", old_version, "a" * 64)


def test_fail_retries_then_dead_and_max_attempts_are_never_reclaimed(tmp_path):
    engine = _engine(tmp_path); now = datetime(2026, 7, 11, 12, tzinfo=UTC)
    with Session(engine) as session:
        account, _, _ = _scope(session); repo = AnalysisJobRepository(session)
        _enqueue(repo, account.id, max_attempts=2)
        first = repo.claim_next("w", 30, now=now)
        retried = repo.fail(account.id, first.id, "w", first.version, "provider_timeout", 5, now=now)
        assert retried.status == "retry" and retried.available_at.replace(tzinfo=UTC) == now + timedelta(seconds=5)
        assert repo.claim_next("w", 30, now=now + timedelta(seconds=4)) is None
        second = repo.claim_next("w", 30, now=now + timedelta(seconds=5))
        dead = repo.fail(account.id, second.id, "w", second.version, "provider_timeout", 5, now=now + timedelta(seconds=5))
        assert dead.status == "dead" and repo.claim_next("w", 30, now=now + timedelta(days=1)) is None


def test_recover_limit_dead_normalization_cancel_scope_and_terminal_conflict(tmp_path):
    engine = _engine(tmp_path); now = datetime(2026, 7, 11, 12, tzinfo=UTC)
    with Session(engine) as session:
        a1, _, _ = _scope(session, "1"); a2, _, _ = _scope(session, "2")
        repo = AnalysisJobRepository(session)
        j1 = _enqueue(repo, a1.id, key="one", max_attempts=1)
        j2 = _enqueue(repo, a1.id, key="two", max_attempts=1)
        c1 = repo.claim_next("w", 1, account_id=a1.id, now=now)
        c2 = repo.claim_next("w", 1, account_id=a1.id, now=now)
        assert repo.recover_expired_leases(now=now + timedelta(seconds=2), limit=1) == 1
        statuses = [repo.get(a1.id, j.id).status for j in (j1, j2)]
        assert statuses.count("dead") == 1 and statuses.count("claimed") == 1
        pending = _enqueue(repo, a1.id, key="cancel")
        with pytest.raises(JobScopeViolation): repo.cancel(a2.id, pending.id, pending.version)
        cancelled = repo.cancel(a1.id, pending.id, pending.version)
        assert cancelled.status == "cancelled"
        with pytest.raises(JobConflict): repo.cancel(a1.id, cancelled.id, cancelled.version)


def test_postgres_claim_query_compiles_skip_locked():
    now = datetime.now(UTC)
    sql = str(build_postgres_claim_query(None, now, 100, "2.5", 7).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).upper()
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "BUDGET_TOKENS" in sql and "BUDGET_COST" in sql
    assert "COUNT" in sql and "CLAIMED" in sql and "RUNNING" in sql
    assert "NOT" in sql and "EXISTS" in sql and "PARENT" in sql
    assert _db_time(now, "postgresql").tzinfo is UTC
    assert _db_time(now, "sqlite").tzinfo is None


def test_postgres_recovery_query_compiles_skip_locked_and_scope():
    sql = str(build_postgres_recovery_query(datetime.now(UTC), 10, "account").compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).upper()
    assert "FOR UPDATE SKIP LOCKED" in sql and "ACCOUNT_ID" in sql and "LIMIT 10" in sql


def test_validation_idempotency_backpressure_and_progress(tmp_path):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        account, contact, conversation = _scope(session); repo = AnalysisJobRepository(session)
        for kwargs in ({"input_hash": "x"}, {"job_type": ""}, {"priority": -1},
                       {"budget_tokens": -1}, {"progress_total": 1, "progress_completed": 2}):
            args = dict(account_id=account.id, job_type="profile_refresh", idempotency_key="x",
                        input_hash="a" * 64); args.update(kwargs)
            with pytest.raises(ValueError): repo.enqueue(**args)
        job = _enqueue(repo, account.id, contact_id=contact.id, conversation_id=conversation.id,
                       priority=2, budget_tokens=10)
        with pytest.raises(JobConflict):
            repo.enqueue(account.id, "other", "k", "a" * 64, contact_id=contact.id,
                         conversation_id=conversation.id, priority=2, budget_tokens=10)
        with pytest.raises(JobConflict):
            _enqueue(repo, account.id, key="second", max_queued_per_account=1)
        assert job.status == "pending"


def test_parent_cancel_propagates_only_unstarted_and_rejects_worker_result(tmp_path):
    engine = _engine(tmp_path); now = datetime(2026, 7, 11, 12, tzinfo=UTC)
    with Session(engine) as session:
        account, _, _ = _scope(session); repo = AnalysisJobRepository(session)
        parent = _enqueue(repo, account.id, key="parent", priority=10)
        pending = _enqueue(repo, account.id, key="pending", parent_job_id=parent.id)
        running = _enqueue(repo, account.id, key="running", parent_job_id=parent.id, priority=20)
        running = repo.claim_next("w", 30, account_id=account.id, now=now)
        assert running.id != parent.id
        repo.cancel(account.id, parent.id, parent.version)
        assert repo.get(account.id, pending.id).status == "cancelled"
        assert repo.get(account.id, running.id).status == "claimed"
        with pytest.raises(JobConflict):
            repo.start(account.id, running.id, "w", running.version, now=now)


def test_exact_expiry_rejected_and_recoverable(tmp_path):
    engine = _engine(tmp_path); now = datetime(2026, 7, 11, 12, tzinfo=UTC)
    with Session(engine) as session:
        account, _, _ = _scope(session); repo = AnalysisJobRepository(session)
        _enqueue(repo, account.id); job = repo.claim_next("w", 1, now=now)
        with pytest.raises(JobConflict):
            repo.start(account.id, job.id, "w", job.version, now=now + timedelta(seconds=1))
        assert repo.recover_expired_leases(now + timedelta(seconds=1), account_id=account.id) == 1


def test_committed_claim_wrapper_is_immediately_visible(tmp_path):
    engine = _engine(tmp_path); factory = sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 7, 11, 12, tzinfo=UTC)
    with factory() as session:
        account, _, _ = _scope(session); _enqueue(AnalysisJobRepository(session), account.id); session.commit()
    lease = claim_next_committed(factory, "worker", 30, account_id=account.id, now=now)
    assert isinstance(lease, JobLease) and lease.status == "claimed"
    with factory() as observer:
        assert observer.get(AnalysisJob, lease.id).status == "claimed"


def test_global_claim_skips_accounts_at_active_limit_and_returns_none_when_all_full(tmp_path):
    engine = _engine(tmp_path); now = datetime(2026, 7, 11, 12, tzinfo=UTC)
    with Session(engine) as session:
        full, _, _ = _scope(session, "full"); free, _, _ = _scope(session, "free")
        repo = AnalysisJobRepository(session)
        _enqueue(repo, full.id, key="active", priority=100)
        active = repo.claim_next("busy", 30, account_id=full.id, now=now)
        _enqueue(repo, full.id, key="blocked", priority=99)
        candidate = _enqueue(repo, free.id, key="candidate", priority=1)
        claimed = repo.claim_next("global", 30, now=now, max_active_per_account=1)
        assert claimed.id == candidate.id
        _enqueue(repo, free.id, key="blocked-too", priority=0)
        assert repo.claim_next("global-2", 30, now=now, max_active_per_account=1) is None
        assert repo.get(full.id, active.id).status == "claimed"


def test_cancelled_parent_blocks_enqueue_and_recovery_cancels_leased_child(tmp_path):
    engine = _engine(tmp_path); now = datetime(2026, 7, 11, 12, tzinfo=UTC)
    with Session(engine) as session:
        account, _, _ = _scope(session); repo = AnalysisJobRepository(session)
        parent = _enqueue(repo, account.id, key="parent", priority=100)
        leased = _enqueue(repo, account.id, key="leased", parent_job_id=parent.id, priority=200)
        leased = repo.claim_next("w", 1, account_id=account.id, now=now)
        repo.cancel(account.id, parent.id, parent.version)
        with pytest.raises(JobConflict):
            _enqueue(repo, account.id, key="late", parent_job_id=parent.id)
        assert repo.recover_expired_leases(now + timedelta(seconds=2)) == 1
        assert repo.get(account.id, leased.id).status == "cancelled"
        assert repo.claim_next("again", 30, account_id=account.id,
                               now=now + timedelta(seconds=3)) is None


def test_claim_excludes_children_of_terminal_parent(tmp_path):
    engine = _engine(tmp_path); now = datetime(2026, 7, 11, 12, tzinfo=UTC)
    with Session(engine) as session:
        account, _, _ = _scope(session); repo = AnalysisJobRepository(session)
        parent = _enqueue(repo, account.id, key="parent", priority=100)
        child = _enqueue(repo, account.id, key="child", parent_job_id=parent.id, priority=200)
        parent.status = "completed"; session.flush()
        assert repo.claim_next("w", 30, account_id=account.id, now=now) is None
        assert repo.get(account.id, child.id).status == "pending"


def test_parent_lock_query_compiles_for_update():
    sql = str(build_parent_lock_query("parent-id", "account-id").compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).upper()
    assert "FOR UPDATE" in sql and "PARENT-ID" in sql and "ACCOUNT-ID" in sql
