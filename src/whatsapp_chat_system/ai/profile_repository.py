from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from whatsapp_chat_system.db.models import (
    Contact, Conversation, ConversationSummary, Message, ProfileClaim,
    ProfileClaimEvidence, ProfileSnapshot,
)


class RepositoryConflict(RuntimeError):
    """The caller used stale state or lost a concurrent uniqueness race."""


class ScopeViolation(LookupError):
    """An object is outside the supplied account/contact/conversation scope."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ProfileRepository:
    def __init__(self, session: Session):
        self.session = session

    def _scope(self, account_id: str, contact_id: str, conversation_id: str | None = None) -> Contact:
        contact = self.session.scalar(select(Contact).where(
            Contact.id == contact_id, Contact.account_id == account_id
        ).execution_options(populate_existing=True))
        if contact is None:
            raise ScopeViolation("contact is outside the supplied scope")
        if conversation_id is not None:
            conversation = self.session.scalar(select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.account_id == account_id,
                Conversation.contact_id == contact_id,
            ))
            if conversation is None:
                raise ScopeViolation("conversation is outside the supplied scope")
        return contact

    def _increment_revision(self, account_id: str, contact_id: str, expected: int) -> int:
        result = self.session.execute(update(Contact).where(
            Contact.id == contact_id, Contact.account_id == account_id,
            Contact.profile_revision == expected,
        ).values(profile_revision=expected + 1))
        if result.rowcount != 1:
            raise RepositoryConflict("profile revision changed concurrently")
        return expected + 1

    def _validate_evidence_scope(self, account_id: str, contact_id: str,
        claim: ProfileClaim, evidence_type: str, evidence_id: str,
        conversation_id: str | None = None) -> None:
        if not evidence_id or not evidence_id.strip():
            raise ValueError("evidence_id must not be empty")
        self._scope(account_id, contact_id, conversation_id)
        if claim.conversation_id is not None:
            self._scope(account_id, contact_id, claim.conversation_id)
            if conversation_id != claim.conversation_id:
                raise ScopeViolation("evidence conversation does not match claim conversation")
        if evidence_type == "message":
            source = self.session.scalar(select(Message.id).where(Message.id == evidence_id,
                Message.account_id == account_id, Message.contact_id == contact_id,
                Message.conversation_id == conversation_id))
            if source is None:
                raise ScopeViolation("message evidence is outside scope")
        elif evidence_type == "summary":
            source = self.session.scalar(select(ConversationSummary.id).where(
                ConversationSummary.id == evidence_id, ConversationSummary.account_id == account_id,
                ConversationSummary.contact_id == contact_id,
                ConversationSummary.conversation_id == conversation_id))
            if source is None:
                raise ScopeViolation("summary evidence is outside scope")

    def _build_evidence(self, account_id: str, contact_id: str, claim: ProfileClaim,
        evidence_type: str, evidence_id: str, conversation_id: str | None = None,
        excerpt_hash: str | None = None) -> ProfileClaimEvidence:
        self._validate_evidence_scope(account_id, contact_id, claim, evidence_type,
            evidence_id, conversation_id)
        return ProfileClaimEvidence(account_id=account_id, contact_id=contact_id,
            conversation_id=conversation_id, claim_id=claim.id, evidence_type=evidence_type,
            evidence_id=evidence_id, excerpt_hash=excerpt_hash)

    def upsert_proposed_claim(self, account_id: str, contact_id: str, claim_key: str,
        value_json: dict[str, Any], source_type: str, confidence: Any,
        analyzer_version: str, conversation_id: str | None = None,
        sensitivity: str = "normal", created_by: str = "worker",
        evidence: dict[str, Any] | None = None) -> ProfileClaim:
        contact = self._scope(account_id, contact_id, conversation_id)
        target = _canonical(value_json)
        claims = self.session.scalars(select(ProfileClaim).where(
            ProfileClaim.account_id == account_id, ProfileClaim.contact_id == contact_id,
            ProfileClaim.claim_key == claim_key,
        ).order_by(ProfileClaim.version.desc())).all()
        for claim in claims:
            if _canonical(claim.value_json) == target and (
                claim.analyzer_version == analyzer_version or claim.status == "accepted" or claim.manual_lock
            ):
                if evidence is not None:
                    self.add_evidence(account_id, contact_id, claim.id, **evidence)
                return claim
        claim = ProfileClaim(account_id=account_id, contact_id=contact_id,
            conversation_id=conversation_id, claim_key=claim_key, value_json=value_json,
            source_type=source_type, confidence=confidence, status="proposed",
            sensitivity=sensitivity, manual_lock=False, analyzer_version=analyzer_version,
            version=(claims[0].version + 1) if claims else 1, created_by=created_by)
        evidence_item = None
        try:
            with self.session.begin_nested():
                self.session.add(claim)
                self.session.flush()
                self._increment_revision(account_id, contact_id, contact.profile_revision)
                if evidence is not None:
                    evidence_item = self._build_evidence(
                        account_id, contact_id, claim, **evidence)
                    self.session.add(evidence_item)
                    self.session.flush()
        except IntegrityError:
            winner = self.session.scalar(select(ProfileClaim).where(
                ProfileClaim.account_id == account_id, ProfileClaim.contact_id == contact_id,
                ProfileClaim.claim_key == claim_key, ProfileClaim.version == claim.version))
            if winner is not None and _canonical(winner.value_json) == target:
                if evidence is not None:
                    self.add_evidence(account_id, contact_id, winner.id, **evidence)
                return winner
            raise RepositoryConflict("claim version was concurrently created")
        return claim

    def add_evidence(self, account_id: str, contact_id: str, claim_id: str,
        evidence_type: str, evidence_id: str, conversation_id: str | None = None,
        excerpt_hash: str | None = None) -> ProfileClaimEvidence:
        claim = self.session.scalar(select(ProfileClaim).where(ProfileClaim.id == claim_id,
            ProfileClaim.account_id == account_id, ProfileClaim.contact_id == contact_id))
        if claim is None:
            raise ScopeViolation("claim is outside the supplied scope")
        self._validate_evidence_scope(account_id, contact_id, claim, evidence_type,
            evidence_id, conversation_id)
        existing = self.session.scalar(select(ProfileClaimEvidence).where(
            ProfileClaimEvidence.account_id == account_id,
            ProfileClaimEvidence.claim_id == claim_id,
            ProfileClaimEvidence.evidence_type == evidence_type,
            ProfileClaimEvidence.evidence_id == evidence_id))
        if existing is not None: return existing
        item = ProfileClaimEvidence(account_id=account_id, contact_id=contact_id,
            conversation_id=conversation_id, claim_id=claim_id, evidence_type=evidence_type,
            evidence_id=evidence_id, excerpt_hash=excerpt_hash)
        try:
            with self.session.begin_nested():
                self.session.add(item); self.session.flush()
        except IntegrityError:
            winner = self.session.scalar(select(ProfileClaimEvidence).where(
                ProfileClaimEvidence.account_id == account_id,
                ProfileClaimEvidence.claim_id == claim_id,
                ProfileClaimEvidence.evidence_type == evidence_type,
                ProfileClaimEvidence.evidence_id == evidence_id))
            if winner is not None: return winner
            raise RepositoryConflict("evidence was concurrently attached")
        return item

    def transition_claim(self, account_id: str, contact_id: str, claim_id: str,
        expected_version: int, status: str | None = None,
        value_json: dict[str, Any] | None = None, manual_lock: bool | None = None,
        actor: str = "operator") -> ProfileClaim:
        contact = self._scope(account_id, contact_id)
        old = self.session.scalar(select(ProfileClaim).where(ProfileClaim.id == claim_id,
            ProfileClaim.account_id == account_id, ProfileClaim.contact_id == contact_id
        ).execution_options(populate_existing=True))
        if old is None: raise ScopeViolation("claim is outside the supplied scope")
        if old.conversation_id is not None:
            self._scope(account_id, contact_id, old.conversation_id)
        if old.version != expected_version or old.status == "superseded":
            raise RepositoryConflict("claim version is stale")
        if actor == "worker" and old.manual_lock:
            raise RepositoryConflict("worker cannot transition a manually locked claim")
        replacement = ProfileClaim(account_id=account_id, contact_id=contact_id,
            conversation_id=old.conversation_id, claim_key=old.claim_key,
            value_json=old.value_json if value_json is None else value_json,
            source_type="manual" if actor != "worker" and value_json is not None else old.source_type,
            confidence=old.confidence, status=old.status if status is None else status,
            sensitivity=old.sensitivity,
            manual_lock=old.manual_lock if manual_lock is None else manual_lock,
            analyzer_version=old.analyzer_version, valid_from=old.valid_from,
            valid_until=old.valid_until, version=expected_version + 1, created_by=actor)
        try:
            with self.session.begin_nested():
                result = self.session.execute(update(ProfileClaim).where(ProfileClaim.id == claim_id,
                    ProfileClaim.account_id == account_id, ProfileClaim.contact_id == contact_id,
                    ProfileClaim.version == expected_version, ProfileClaim.status == old.status
                ).values(status="superseded"))
                if result.rowcount != 1: raise RepositoryConflict("claim changed concurrently")
                self.session.add(replacement)
                self.session.flush()
                self._increment_revision(account_id, contact_id, contact.profile_revision)
        except IntegrityError as exc:
            raise RepositoryConflict("claim version was concurrently created") from exc
        return replacement

    def rebuild_snapshot(self, account_id: str, contact_id: str,
        expected_current_version: int | None = None,
        expected_profile_revision: int | None = None) -> ProfileSnapshot:
        contact = self._scope(account_id, contact_id)
        if expected_profile_revision is None: expected_profile_revision = contact.profile_revision
        if contact.profile_revision != expected_profile_revision:
            raise RepositoryConflict("profile revision is stale")
        current = self.session.execute(select(ProfileSnapshot).where(
            ProfileSnapshot.account_id == account_id, ProfileSnapshot.contact_id == contact_id,
            ProfileSnapshot.is_current.is_(True)).execution_options(populate_existing=True)).scalar_one_or_none()
        if (current.version if current else None) != expected_current_version:
            raise RepositoryConflict("snapshot version is stale")
        now = datetime.now(timezone.utc)
        claims = self.session.scalars(select(ProfileClaim).where(
            ProfileClaim.account_id == account_id, ProfileClaim.contact_id == contact_id,
            ProfileClaim.status == "accepted", ProfileClaim.sensitivity != "restricted",
            or_(ProfileClaim.valid_from.is_(None), ProfileClaim.valid_from <= now),
            or_(ProfileClaim.valid_until.is_(None), ProfileClaim.valid_until > now),
        ).order_by(ProfileClaim.claim_key, ProfileClaim.manual_lock.desc(), ProfileClaim.version.desc())).all()
        selected: dict[str, ProfileClaim] = {}
        for claim in claims: selected.setdefault(claim.claim_key, claim)
        snapshot = ProfileSnapshot(account_id=account_id, contact_id=contact_id,
            version=(expected_current_version or 0) + 1,
            snapshot_json={k: selected[k].value_json for k in sorted(selected)}, is_current=True,
            source_claim_cursor=str(max((c.version for c in selected.values()), default=0)),
            source_claim_versions={k: {"claim_id": selected[k].id, "version": selected[k].version} for k in sorted(selected)},
            source_profile_revision=expected_profile_revision)
        try:
            with self.session.begin_nested():
                revision_cas = self.session.execute(update(Contact).where(
                    Contact.id == contact_id, Contact.account_id == account_id,
                    Contact.profile_revision == expected_profile_revision,
                ).values(profile_revision=Contact.profile_revision))
                if revision_cas.rowcount != 1:
                    raise RepositoryConflict("profile changed during snapshot rebuild")
                if current is not None:
                    result = self.session.execute(update(ProfileSnapshot).where(
                        ProfileSnapshot.id == current.id,
                        ProfileSnapshot.version == expected_current_version,
                        ProfileSnapshot.is_current.is_(True),
                    ).values(is_current=False))
                    if result.rowcount != 1:
                        raise RepositoryConflict("snapshot changed concurrently")
                self.session.add(snapshot)
                self.session.flush()
        except IntegrityError as exc:
            raise RepositoryConflict("snapshot was concurrently rebuilt") from exc
        return snapshot

    def get_current_snapshot(self, account_id: str, contact_id: str) -> ProfileSnapshot | None:
        self._scope(account_id, contact_id)
        return self.session.execute(select(ProfileSnapshot).where(
            ProfileSnapshot.account_id == account_id, ProfileSnapshot.contact_id == contact_id,
            ProfileSnapshot.is_current.is_(True)).execution_options(populate_existing=True)).scalar_one_or_none()
