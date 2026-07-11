from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from whatsapp_chat_system.ai.profile_repository import (
    ProfileRepository,
    RepositoryConflict,
    ScopeViolation,
)
from whatsapp_chat_system.db.base import Base
from whatsapp_chat_system.db.models import (
    Contact,
    Conversation,
    ConversationSummary,
    Message,
    ProfileClaim,
    ProfileClaimEvidence,
    ProfileSnapshot,
    WhatsAppAccount,
)


def _engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'profiles.db'}")

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


def _scope(session: Session, suffix: str = "a") -> tuple[str, str]:
    account = WhatsAppAccount(name=f"Account {suffix}", session_ref=f"account:{suffix}")
    session.add(account)
    session.flush()
    contact = Contact(account_id=account.id, remote_jid=f"{suffix}@s.whatsapp.net")
    session.add(contact)
    session.flush()
    return account.id, contact.id


def _conversation(session: Session, account_id: str, contact_id: str) -> Conversation:
    contact = session.get(Contact, contact_id)
    conversation = Conversation(account_id=account_id, contact_id=contact_id,
        remote_jid=contact.remote_jid, type="dm")
    session.add(conversation)
    session.flush()
    return conversation


def _propose(repo: ProfileRepository, account_id: str, contact_id: str, **overrides):
    values = dict(
        account_id=account_id,
        contact_id=contact_id,
        claim_key="preference.food",
        value_json={"items": ["rice"], "meta": {"b": 2, "a": 1}},
        source_type="model_inference",
        confidence=Decimal("0.8000"),
        analyzer_version="profile-v1",
    )
    values.update(overrides)
    return repo.upsert_proposed_claim(**values)


def test_upsert_is_canonical_json_idempotent_and_attaches_evidence(tmp_path):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        account_id, contact_id = _scope(session)
        repo = ProfileRepository(session)
        conversation = _conversation(session, account_id, contact_id)
        message = Message(account_id=account_id, contact_id=contact_id, conversation_id=conversation.id,
                          direction="inbound", status="received", content="evidence")
        session.add(message); session.flush()
        first = _propose(
            repo,
            account_id,
            contact_id,
            conversation_id=conversation.id,
            evidence={"evidence_type": "message", "evidence_id": message.id, "conversation_id": conversation.id, "excerpt_hash": "h"},
        )
        second = _propose(
            repo,
            account_id,
            contact_id,
            conversation_id=conversation.id,
            value_json={"meta": {"a": 1, "b": 2}, "items": ["rice"]},
            evidence={"evidence_type": "message", "evidence_id": message.id, "conversation_id": conversation.id, "excerpt_hash": "h"},
        )
        assert second.id == first.id
        assert session.scalar(select(func.count(ProfileClaim.id))) == 1
        assert session.scalar(select(func.count(ProfileClaimEvidence.id))) == 1


def test_worker_conflict_creates_next_proposed_without_overwriting_accepted_or_locked(tmp_path):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        account_id, contact_id = _scope(session)
        repo = ProfileRepository(session)
        accepted = _propose(repo, account_id, contact_id)
        accepted = repo.transition_claim(
            account_id, contact_id, accepted.id, expected_version=1,
            status="accepted", manual_lock=True,
        )
        assert accepted.version == 2
        assert accepted.status == "accepted"
        assert accepted.manual_lock is True

        locked_id = accepted.id
        same = _propose(repo, account_id, contact_id)
        assert same.id == locked_id

        conflict = _propose(repo, account_id, contact_id, value_json={"items": ["noodles"]})
        session.refresh(accepted)
        assert conflict.version == 3
        assert conflict.status == "proposed"
        assert accepted.status == "accepted"
        assert accepted.manual_lock is True


def test_transition_uses_cas_and_preserves_immutable_history(tmp_path):
    engine = _engine(tmp_path)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as setup:
        account_id, contact_id = _scope(setup)
        claim = _propose(ProfileRepository(setup), account_id, contact_id)
        setup.commit()
        claim_id = claim.id

    with factory() as first, factory() as stale:
        stale_claim = stale.scalar(select(ProfileClaim).where(ProfileClaim.id == claim_id))
        assert stale_claim is not None and stale_claim.version == 1
        replacement = ProfileRepository(first).transition_claim(
            account_id, contact_id, claim_id, expected_version=1,
            status="accepted", value_json={"items": ["rice", "tea"]}, actor="operator",
        )
        first.commit()
        assert replacement.version == 2

        with pytest.raises(RepositoryConflict):
            ProfileRepository(stale).transition_claim(
                account_id, contact_id, claim_id, expected_version=1, status="rejected"
            )
        stale.rollback()

    with factory() as verify:
        claims = verify.scalars(
            select(ProfileClaim)
            .where(ProfileClaim.account_id == account_id, ProfileClaim.contact_id == contact_id)
            .order_by(ProfileClaim.version)
        ).all()
        assert [(item.version, item.status) for item in claims] == [(1, "superseded"), (2, "accepted")]


def test_all_claim_and_evidence_access_is_scope_bound(tmp_path):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        account_a, contact_a = _scope(session, "a")
        account_b, contact_b = _scope(session, "b")
        claim = _propose(ProfileRepository(session), account_a, contact_a)

        with pytest.raises(ScopeViolation):
            ProfileRepository(session).add_evidence(
                account_b, contact_b, claim.id,
                evidence_type="message", evidence_id="cross-scope",
            )
        with pytest.raises(ScopeViolation):
            ProfileRepository(session).transition_claim(
                account_b, contact_b, claim.id, expected_version=1, status="accepted"
            )
        assert ProfileRepository(session).get_current_snapshot(account_b, contact_b) is None


def test_add_evidence_is_idempotent_and_rejects_empty_id(tmp_path):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        account_id, contact_id = _scope(session)
        repo = ProfileRepository(session)
        claim = _propose(repo, account_id, contact_id)
        conversation = _conversation(session, account_id, contact_id)
        summary = ConversationSummary(account_id=account_id, contact_id=contact_id,
            conversation_id=conversation.id, summary_type="rolling", summary_json={},
            analyzer_version="v1", input_hash="summary-1", status="completed", stale=False, version=1)
        session.add(summary); session.flush()
        first = repo.add_evidence(
            account_id, contact_id, claim.id,
            evidence_type="summary", evidence_id=summary.id, conversation_id=conversation.id, excerpt_hash="abc",
        )
        second = repo.add_evidence(
            account_id, contact_id, claim.id,
            evidence_type="summary", evidence_id=summary.id, conversation_id=conversation.id, excerpt_hash="changed",
        )
        assert second.id == first.id
        assert second.excerpt_hash == "abc"
        with pytest.raises(ValueError):
            repo.add_evidence(
                account_id, contact_id, claim.id,
                evidence_type="summary", evidence_id="  ",
            )


def test_snapshot_uses_latest_accepted_unexpired_claim_per_key_and_stable_key_order(tmp_path):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        account_id, contact_id = _scope(session)
        now = datetime.now(timezone.utc)
        session.add_all([
            ProfileClaim(account_id=account_id, contact_id=contact_id, claim_key="zeta", value_json={"v": 1}, source_type="manual", confidence=1, status="accepted", sensitivity="normal", manual_lock=False, analyzer_version="manual", version=1),
            ProfileClaim(account_id=account_id, contact_id=contact_id, claim_key="zeta", value_json={"v": 2}, source_type="manual", confidence=1, status="accepted", sensitivity="normal", manual_lock=False, analyzer_version="manual", version=2),
            ProfileClaim(account_id=account_id, contact_id=contact_id, claim_key="alpha", value_json={"v": "expired"}, source_type="manual", confidence=1, status="accepted", sensitivity="normal", manual_lock=False, analyzer_version="manual", valid_until=now - timedelta(seconds=1), version=1),
            ProfileClaim(account_id=account_id, contact_id=contact_id, claim_key="beta", value_json={"v": "future"}, source_type="manual", confidence=1, status="accepted", sensitivity="normal", manual_lock=False, analyzer_version="manual", valid_from=now + timedelta(days=1), version=1),
            ProfileClaim(account_id=account_id, contact_id=contact_id, claim_key="gamma", value_json={"v": "no"}, source_type="manual", confidence=1, status="rejected", sensitivity="normal", manual_lock=False, analyzer_version="manual", version=1),
        ])
        session.flush()
        repo = ProfileRepository(session)
        snapshot = repo.rebuild_snapshot(account_id, contact_id, expected_current_version=None)
        assert list(snapshot.snapshot_json) == ["zeta"]
        assert snapshot.snapshot_json == {"zeta": {"v": 2}}
        assert snapshot.is_current is True
        assert repo.get_current_snapshot(account_id, contact_id).id == snapshot.id


def test_snapshot_rebuild_cas_rejects_stale_session_and_keeps_one_current(tmp_path):
    engine = _engine(tmp_path)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as setup:
        account_id, contact_id = _scope(setup)
        repo = ProfileRepository(setup)
        claim = _propose(repo, account_id, contact_id)
        repo.transition_claim(account_id, contact_id, claim.id, 1, status="accepted")
        repo.rebuild_snapshot(account_id, contact_id, expected_current_version=None)
        setup.commit()

    with factory() as winner, factory() as stale:
        assert ProfileRepository(stale).get_current_snapshot(account_id, contact_id).version == 1
        second = ProfileRepository(winner).rebuild_snapshot(
            account_id, contact_id, expected_current_version=1
        )
        winner.commit()
        assert second.version == 2

        with pytest.raises(RepositoryConflict):
            ProfileRepository(stale).rebuild_snapshot(
                account_id, contact_id, expected_current_version=1
            )
        stale.rollback()

    with factory() as verify:
        current = verify.scalars(select(ProfileSnapshot).where(
            ProfileSnapshot.account_id == account_id,
            ProfileSnapshot.contact_id == contact_id,
            ProfileSnapshot.is_current.is_(True),
        )).all()
        assert len(current) == 1
        assert current[0].version == 2


def test_worker_cannot_transition_any_manually_locked_claim(tmp_path):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        account_id, contact_id = _scope(session)
        repo = ProfileRepository(session)
        claim = _propose(repo, account_id, contact_id)
        locked = repo.transition_claim(account_id, contact_id, claim.id, 1,
            status="proposed", manual_lock=True, actor="operator")
        with pytest.raises(RepositoryConflict):
            repo.transition_claim(account_id, contact_id, locked.id, locked.version,
                status="accepted", actor="worker")
        assert session.scalar(select(Contact.id).where(Contact.id == contact_id)) == contact_id


def test_conversation_bound_claim_enforces_transition_and_evidence_scope(tmp_path):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        account_id, contact_id = _scope(session)
        other_account, other_contact = _scope(session, "other")
        conversation = _conversation(session, account_id, contact_id)
        other_conversation = Conversation(account_id=account_id, contact_id=contact_id,
            remote_jid="alternate@s.whatsapp.net", type="dm")
        session.add(other_conversation)
        session.flush()
        claim = _propose(ProfileRepository(session), account_id, contact_id,
            conversation_id=conversation.id)
        session.commit()
        claim_id = claim.id
        conversation_id = conversation.id
        other_conversation_id = other_conversation.id

    with Session(engine) as session:
        session.execute(update(Conversation).where(Conversation.id == conversation_id).values(
            account_id=other_account, contact_id=other_contact))
        with pytest.raises(ScopeViolation):
            ProfileRepository(session).transition_claim(
                account_id, contact_id, claim_id, 1, status="accepted")
        session.rollback()

    with Session(engine) as session:
        with pytest.raises(ScopeViolation):
            ProfileRepository(session).add_evidence(account_id, contact_id, claim_id,
                evidence_type="manual_note", evidence_id="note-1",
                conversation_id=other_conversation_id)


def test_transition_insert_conflict_rolls_back_old_state_and_session_remains_usable(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        account_id, contact_id = _scope(session)
        repo = ProfileRepository(session)
        claim = _propose(repo, account_id, contact_id)
        original_flush = session.flush
        injected = False

        def conflicting_flush(*args, **kwargs):
            nonlocal injected
            pending = next((item for item in session.new
                if isinstance(item, ProfileClaim) and item.version == 2), None)
            if pending is not None and not injected:
                injected = True
                session.add(ProfileClaim(account_id=account_id, contact_id=contact_id,
                    claim_key=pending.claim_key, value_json={"preexisting": True},
                    source_type="manual", confidence=1, status="proposed",
                    sensitivity="normal", manual_lock=False, analyzer_version="manual", version=2))
            return original_flush(*args, **kwargs)

        monkeypatch.setattr(session, "flush", conflicting_flush)
        with pytest.raises(RepositoryConflict):
            repo.transition_claim(account_id, contact_id, claim.id, 1, status="accepted")
        session.commit()
        assert session.get(ProfileClaim, claim.id).status == "proposed"
        assert session.scalar(select(Contact.id).where(Contact.id == contact_id)) == contact_id


def test_snapshot_insert_conflict_rolls_back_current_and_session_remains_usable(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        account_id, contact_id = _scope(session)
        repo = ProfileRepository(session)
        first = repo.rebuild_snapshot(account_id, contact_id, expected_current_version=None)
        original_flush = session.flush
        injected = False

        def conflicting_flush(*args, **kwargs):
            nonlocal injected
            pending = next((item for item in session.new
                if isinstance(item, ProfileSnapshot) and item.version == 2), None)
            if pending is not None and not injected:
                injected = True
                session.add(ProfileSnapshot(account_id=account_id, contact_id=contact_id,
                    version=2, snapshot_json={}, is_current=False,
                    source_claim_versions={}, source_profile_revision=0))
            return original_flush(*args, **kwargs)

        monkeypatch.setattr(session, "flush", conflicting_flush)
        with pytest.raises(RepositoryConflict):
            repo.rebuild_snapshot(account_id, contact_id, expected_current_version=1)
        session.commit()
        session.refresh(first)
        assert first.is_current is True
        assert session.scalar(select(Contact.id).where(Contact.id == contact_id)) == contact_id


def test_upsert_revision_conflict_removes_new_claim_and_winner_keeps_evidence(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        account_id, contact_id = _scope(session)
        repo = ProfileRepository(session)
        original_increment = repo._increment_revision
        monkeypatch.setattr(repo, "_increment_revision",
            lambda *args, **kwargs: (_ for _ in ()).throw(RepositoryConflict("forced revision conflict")))
        with pytest.raises(RepositoryConflict):
            _propose(repo, account_id, contact_id)
        session.commit()
        assert session.scalar(select(func.count(ProfileClaim.id))) == 0
        assert session.scalar(select(Contact.id).where(Contact.id == contact_id)) == contact_id

        monkeypatch.setattr(repo, "_increment_revision", original_increment)
        conversation = _conversation(session, account_id, contact_id)
        message = Message(account_id=account_id, contact_id=contact_id,
            conversation_id=conversation.id, direction="inbound", status="received",
            content="winner evidence")
        session.add(message); session.flush()
        winner = _propose(repo, account_id, contact_id, conversation_id=conversation.id)
        same = _propose(repo, account_id, contact_id, conversation_id=conversation.id, evidence={
            "evidence_type": "message", "evidence_id": message.id,
            "conversation_id": conversation.id})
        assert same.id == winner.id
        assert session.scalar(select(func.count(ProfileClaimEvidence.id))) == 1


@pytest.mark.parametrize("evidence_type", ["message", "summary"])
def test_new_claim_with_invalid_evidence_is_atomic_after_outer_commit(tmp_path, evidence_type):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        account_id, contact_id = _scope(session)
        conversation = _conversation(session, account_id, contact_id)
        session.commit()

        with pytest.raises(ScopeViolation):
            _propose(ProfileRepository(session), account_id, contact_id,
                conversation_id=conversation.id, evidence={
                    "evidence_type": evidence_type,
                    "evidence_id": "missing-evidence",
                    "conversation_id": conversation.id,
                })
        session.commit()

        assert session.scalar(select(func.count(ProfileClaim.id))) == 0
        assert session.scalar(select(func.count(ProfileClaimEvidence.id))) == 0
        assert session.get(Contact, contact_id).profile_revision == 0


def test_new_claim_with_mismatched_evidence_scope_is_atomic_after_outer_commit(tmp_path):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        account_id, contact_id = _scope(session)
        claim_conversation = _conversation(session, account_id, contact_id)
        other_conversation = Conversation(account_id=account_id, contact_id=contact_id,
            remote_jid="other@s.whatsapp.net", type="dm")
        session.add(other_conversation)
        session.flush()
        message = Message(account_id=account_id, contact_id=contact_id,
            conversation_id=other_conversation.id, direction="inbound", status="received",
            content="wrong conversation")
        session.add(message)
        session.commit()

        with pytest.raises(ScopeViolation):
            _propose(ProfileRepository(session), account_id, contact_id,
                conversation_id=claim_conversation.id, evidence={
                    "evidence_type": "message",
                    "evidence_id": message.id,
                    "conversation_id": other_conversation.id,
                })
        session.commit()

        assert session.scalar(select(func.count(ProfileClaim.id))) == 0
        assert session.scalar(select(func.count(ProfileClaimEvidence.id))) == 0
        assert session.get(Contact, contact_id).profile_revision == 0
