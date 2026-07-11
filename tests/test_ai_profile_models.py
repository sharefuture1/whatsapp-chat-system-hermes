from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from whatsapp_chat_system.db.base import Base
from whatsapp_chat_system.db.models import (
    AnalysisJob,
    Contact,
    Conversation,
    ConversationSegment,
    ConversationSummary,
    MemoryItem,
    ProfileClaim,
    ProfileClaimEvidence,
    ProfileSnapshot,
    WhatsAppAccount,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AI_TABLES = {
    'conversation_segments', 'conversation_summaries', 'profile_claims',
    'profile_claim_evidence', 'profile_snapshots', 'memory_items', 'analysis_jobs',
}


def _config(path: Path) -> Config:
    config = Config(str(PROJECT_ROOT / 'alembic.ini'))
    config.set_main_option('script_location', str(PROJECT_ROOT / 'migrations'))
    config.set_main_option('sqlalchemy.url', f'sqlite:///{path}')
    config.attributes['ignore_database_url_env'] = True
    return config


def _parents(session: Session):
    account = WhatsAppAccount(name='A', session_ref='account:a')
    session.add(account)
    session.flush()
    contact = Contact(account_id=account.id, remote_jid='person@s.whatsapp.net')
    session.add(contact)
    session.flush()
    conversation = Conversation(account_id=account.id, contact_id=contact.id, remote_jid=contact.remote_jid)
    session.add(conversation)
    session.flush()
    return account, contact, conversation


def test_ai_models_are_exported_and_have_account_scope():
    import whatsapp_chat_system.db.models as models

    names = {
        'ConversationSegment', 'ConversationSummary', 'ProfileClaim',
        'ProfileClaimEvidence', 'ProfileSnapshot', 'MemoryItem', 'AnalysisJob',
    }
    assert names <= set(models.__all__)
    for name in names:
        table = getattr(models, name).__table__
        assert table.c.account_id.nullable is False
        assert table.c.account_id.foreign_keys


def test_model_constraints_persist_status_manual_lock_and_reject_invalid_values():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account, contact, conversation = _parents(session)
        segment = ConversationSegment(
            account_id=account.id, contact_id=contact.id, conversation_id=conversation.id,
            start_message_id='m1', end_message_id='m2', start_cursor='1', end_cursor='2',
            analyzer_version='v1', content_hash='hash', status='completed',
        )
        claim = ProfileClaim(
            account_id=account.id, contact_id=contact.id, conversation_id=conversation.id,
            claim_key='language', value_json={'value': 'zh'}, source_type='manual',
            confidence=Decimal('1.0'), status='accepted', sensitivity='normal',
            manual_lock=True, analyzer_version='v1', version=1,
        )
        summary = ConversationSummary(
            account_id=account.id, contact_id=contact.id, conversation_id=conversation.id,
            summary_type='rolling', summary_json={'text': 'summary'}, analyzer_version='v1',
            input_hash='input', status='completed', stale=False, version=1,
        )
        session.add_all([segment, claim, summary])
        session.commit()
        session.expire_all()
        assert session.get(ProfileClaim, claim.id).manual_lock is True
        assert session.get(ConversationSummary, summary.id).status == 'completed'

        session.add(ProfileClaim(
            account_id=account.id, contact_id=contact.id, claim_key='bad', value_json={},
            source_type='manual', confidence=Decimal('1.1'), status='accepted',
            sensitivity='normal', manual_lock=False, analyzer_version='v1', version=1,
        ))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_segment_summary_claim_evidence_and_memory_uniqueness():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account, contact, conversation = _parents(session)
        common = dict(account_id=account.id, contact_id=contact.id, conversation_id=conversation.id)
        session.add_all([
            ConversationSegment(**common, start_message_id='a', end_message_id='b', analyzer_version='v1', content_hash='h', status='completed'),
            ConversationSegment(**common, start_message_id='a', end_message_id='b', analyzer_version='v1', content_hash='h', status='completed'),
        ])
        with pytest.raises(IntegrityError): session.commit()
        session.rollback()

        claim = ProfileClaim(**common, claim_key='name', value_json={'v': 'N'}, source_type='manual', confidence=Decimal('1'), status='accepted', sensitivity='normal', manual_lock=False, analyzer_version='v1', version=1)
        session.add(claim); session.commit()
        session.add_all([
            ProfileClaimEvidence(**common, claim_id=claim.id, evidence_type='manual_note', evidence_id='note-1', excerpt_hash='h'),
            ProfileClaimEvidence(**common, claim_id=claim.id, evidence_type='manual_note', evidence_id='note-1', excerpt_hash='h'),
        ])
        with pytest.raises(IntegrityError): session.commit()
        session.rollback()

        session.add_all([
            MemoryItem(**common, memory_key='preference.food', memory_type='preference', value_json={'v':'rice'}, status='active', importance=Decimal('0.5')),
            MemoryItem(**common, memory_key='preference.food', memory_type='preference', value_json={'v':'rice'}, status='active', importance=Decimal('0.5')),
        ])
        with pytest.raises(IntegrityError): session.commit()


def test_only_one_current_snapshot_and_job_idempotency():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account, contact, conversation = _parents(session)
        common = dict(account_id=account.id, contact_id=contact.id, conversation_id=conversation.id)
        session.add_all([
            ProfileSnapshot(**common, version=1, snapshot_json={}, is_current=True),
            ProfileSnapshot(**common, version=2, snapshot_json={}, is_current=True),
        ])
        with pytest.raises(IntegrityError): session.commit()
        session.rollback()

        session.add_all([
            AnalysisJob(**common, job_type='profile', status='pending', priority=10, attempts=0, max_attempts=3, idempotency_key='same', input_hash='h', progress_total=0, progress_completed=0, progress_failed=0, budget_tokens=100, budget_cost=Decimal('1.25'), version=1),
            AnalysisJob(**common, job_type='profile', status='pending', priority=10, attempts=0, max_attempts=3, idempotency_key='same', input_hash='h', progress_total=0, progress_completed=0, progress_failed=0, budget_tokens=100, budget_cost=Decimal('1.25'), version=1),
        ])
        with pytest.raises(IntegrityError): session.commit()


def test_0004_migration_round_trip_preserves_0003_tables(tmp_path):
    path = tmp_path / 'ai.db'
    config = _config(path)
    command.upgrade(config, '0004')
    engine = create_engine(f'sqlite:///{path}')
    assert AI_TABLES <= set(inspect(engine).get_table_names())
    engine.dispose()

    command.downgrade(config, '0003')
    engine = create_engine(f'sqlite:///{path}')
    tables = set(inspect(engine).get_table_names())
    assert not (AI_TABLES & tables)
    assert {'whatsapp_accounts', 'contacts', 'conversations', 'messages'} <= tables
    engine.dispose()

    command.upgrade(config, '0004')
    engine = create_engine(f'sqlite:///{path}')
    assert AI_TABLES <= set(inspect(engine).get_table_names())
    engine.dispose()
