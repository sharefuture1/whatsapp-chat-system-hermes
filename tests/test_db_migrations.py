from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_TABLES = {
    'whatsapp_accounts',
    'contacts',
    'conversations',
    'messages',
    'ai_profiles',
    'ai_runtime_settings',
    'contact_ai_overrides',
    'whatsapp_events',
    'outbox_messages',
    'message_translations',
    'translation_batches',
    'conversation_segments',
    'conversation_summaries',
    'profile_claims',
    'profile_claim_evidence',
    'profile_snapshots',
    'memory_items',
    'analysis_jobs',
}
EXPECTED_COLUMNS = {
    'whatsapp_accounts': {
        'id', 'name', 'phone_number', 'status', 'session_ref', 'is_primary', 'enabled',
        'auto_reply_mode', 'ai_profile_id', 'last_seen_at', 'last_error_code',
        'last_error_message', 'last_event_sequence', 'created_at', 'updated_at',
    },
    'contacts': {
        'id', 'account_id', 'remote_jid', 'phone_number', 'lid', 'display_name', 'remark',
        'notes', 'tags', 'language', 'avatar_url', 'metadata', 'profile_revision', 'created_at', 'updated_at',
    },
    'conversations': {
        'id', 'account_id', 'contact_id', 'remote_jid', 'type', 'title', 'last_message_at',
        'last_message_preview', 'unread_count', 'pinned', 'muted', 'archived', 'deleted_at',
        'assigned_operator_id', 'ai_mode', 'created_at', 'updated_at',
    },
    'messages': {
        'id', 'account_id', 'conversation_id', 'contact_id', 'wa_message_id', 'direction',
        'sender_jid', 'message_type', 'content', 'media_metadata', 'quoted_message_id', 'status',
        'error_code', 'error_message', 'retry_count', 'created_at', 'sent_at', 'delivered_at',
        'read_at', 'occurred_at', 'received_at',
    },
    'ai_profiles': {
        'id', 'name', 'provider', 'base_url', 'default_model', 'system_prompt', 'reply_style',
        'temperature', 'timeout_seconds', 'max_retries', 'enabled', 'created_at', 'updated_at',
    },
    'ai_runtime_settings': {
        'id', 'provider', 'base_url', 'default_model', 'api_key_ciphertext', 'api_key_hint',
        'timeout_seconds', 'max_retries', 'updated_by', 'created_at', 'updated_at',
    },
    'contact_ai_overrides': {
        'account_id', 'contact_id', 'model', 'system_prompt', 'reply_style', 'language',
        'auto_reply_enabled',
    },
    'whatsapp_events': {
        'id', 'event_id', 'account_id', 'event_type', 'occurred_at', 'payload', 'processed_at',
        'status', 'error', 'sequence', 'payload_hash',
    },
    'outbox_messages': {
        'id', 'message_id', 'account_id', 'idempotency_key', 'status', 'attempts', 'available_at',
        'lease_owner', 'lease_expires_at', 'last_error', 'created_at', 'updated_at',
    },
    'message_translations': {
        'id', 'account_id', 'conversation_id', 'message_id', 'source_text', 'source_text_hash', 'source_lang',
        'target_lang', 'translated_text', 'status', 'error_code', 'error_message', 'retry_after', 'provider',
        'model', 'context_window_size', 'batch_id', 'completed_at', 'created_at', 'updated_at',
    },
    'translation_batches': {
        'id', 'account_id', 'conversation_id', 'anchor_message_id', 'target_lang', 'window_size', 'status',
        'attempt_count', 'retry_after', 'error_code', 'error_message', 'requested_by', 'completed_at', 'created_at', 'updated_at',
    },
}


def _alembic_config(database_path: Path) -> Config:
    config = Config(str(PROJECT_ROOT / 'alembic.ini'))
    config.set_main_option('script_location', str(PROJECT_ROOT / 'migrations'))
    config.set_main_option('sqlalchemy.url', f'sqlite:///{database_path}')
    config.attributes['ignore_database_url_env'] = True
    return config


def _unique_column_sets(inspector, table_name: str) -> set[tuple[str, ...]]:
    constraints = {
        tuple(item['column_names'])
        for item in inspector.get_unique_constraints(table_name)
    }
    constraints.update(
        tuple(item['column_names'])
        for item in inspector.get_indexes(table_name)
        if item.get('unique')
    )
    return constraints


def _index_column_sets(inspector, table_name: str) -> set[tuple[str, ...]]:
    return {tuple(item['column_names']) for item in inspector.get_indexes(table_name)}


def test_alembic_upgrade_creates_nine_core_tables_columns_and_foreign_keys(tmp_path):
    database_path = tmp_path / 'schema.db'
    config = _alembic_config(database_path)

    command.upgrade(config, 'head')

    engine = create_engine(f'sqlite:///{database_path}')
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == CORE_TABLES | {'alembic_version'}
        for table_name, expected_columns in EXPECTED_COLUMNS.items():
            assert {column['name'] for column in inspector.get_columns(table_name)} == expected_columns

        expected_foreign_keys = {
            'whatsapp_accounts': {('ai_profile_id', 'ai_profiles', 'id')},
            'contacts': {('account_id', 'whatsapp_accounts', 'id')},
            'conversations': {
                ('account_id', 'whatsapp_accounts', 'id'),
                ('contact_id', 'contacts', 'id'),
            },
            'messages': {
                ('account_id', 'whatsapp_accounts', 'id'),
                ('conversation_id', 'conversations', 'id'),
                ('contact_id', 'contacts', 'id'),
                ('quoted_message_id', 'messages', 'id'),
            },
            'contact_ai_overrides': {
                ('account_id', 'whatsapp_accounts', 'id'),
                ('contact_id', 'contacts', 'id'),
            },
            'whatsapp_events': {('account_id', 'whatsapp_accounts', 'id')},
            'outbox_messages': {
                ('message_id', 'messages', 'id'),
                ('account_id', 'whatsapp_accounts', 'id'),
            },
            'message_translations': {
                ('account_id', 'whatsapp_accounts', 'id'),
                ('conversation_id', 'conversations', 'id'),
                ('message_id', 'messages', 'id'),
                ('batch_id', 'translation_batches', 'id'),
            },
            'translation_batches': {
                ('account_id', 'whatsapp_accounts', 'id'),
                ('conversation_id', 'conversations', 'id'),
                ('anchor_message_id', 'messages', 'id'),
            },
        }
        for table_name, expected in expected_foreign_keys.items():
            actual = {
                (fk['constrained_columns'][0], fk['referred_table'], fk['referred_columns'][0])
                for fk in inspector.get_foreign_keys(table_name)
            }
            assert actual == expected
    finally:
        engine.dispose()


def test_core_unique_constraints_partial_message_idempotency_and_indexes(tmp_path):
    database_path = tmp_path / 'constraints.db'
    config = _alembic_config(database_path)
    command.upgrade(config, 'head')

    engine = create_engine(f'sqlite:///{database_path}')
    try:
        inspector = inspect(engine)
        assert ('account_id', 'remote_jid') in _unique_column_sets(inspector, 'contacts')
        assert ('account_id', 'remote_jid') in _unique_column_sets(inspector, 'conversations')
        assert ('account_id', 'wa_message_id') in _unique_column_sets(inspector, 'messages')
        assert ('account_id', 'event_id') in _unique_column_sets(inspector, 'whatsapp_events')
        assert ('account_id', 'sequence') in _index_column_sets(inspector, 'whatsapp_events')
        assert ('message_id',) in _unique_column_sets(inspector, 'outbox_messages')
        assert ('idempotency_key',) in _unique_column_sets(inspector, 'outbox_messages')
        assert ('message_id', 'target_lang', 'source_text_hash') in _unique_column_sets(inspector, 'message_translations')

        assert {
            ('account_id', 'archived', 'last_message_at'),
            ('account_id', 'pinned', 'last_message_at'),
            ('account_id', 'unread_count'),
        } <= _index_column_sets(inspector, 'conversations')
        assert {
            ('conversation_id', 'created_at', 'id'),
            ('account_id', 'status', 'created_at'),
        } <= _index_column_sets(inspector, 'messages')
        assert {
            ('status', 'available_at'),
            ('account_id', 'status', 'available_at'),
        } <= _index_column_sets(inspector, 'outbox_messages')

        message_indexes = {item['name']: item for item in inspector.get_indexes('messages')}
        idempotency_index = message_indexes['uq_messages_account_wa_message_id_not_null']
        assert bool(idempotency_index['unique']) is True
        assert 'wa_message_id IS NOT NULL' in str(
            idempotency_index['dialect_options']['sqlite_where']
        )
    finally:
        engine.dispose()


def test_message_idempotency_index_compiles_for_sqlite_and_postgresql():
    from whatsapp_chat_system.db.models import Message

    index = next(
        item for item in Message.__table__.indexes
        if item.name == 'uq_messages_account_wa_message_id_not_null'
    )
    assert index.dialect_options['sqlite']['where'] is not None
    assert index.dialect_options['postgresql']['where'] is not None

    postgres_sql = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert 'UNIQUE INDEX' in postgres_sql
    assert 'WHERE wa_message_id IS NOT NULL' in postgres_sql


def test_alembic_upgrade_downgrade_base_upgrade_round_trip(tmp_path):
    database_path = tmp_path / 'round-trip.db'
    config = _alembic_config(database_path)

    command.upgrade(config, 'head')
    command.downgrade(config, 'base')

    engine = create_engine(f'sqlite:///{database_path}')
    try:
        assert inspect(engine).get_table_names() == ['alembic_version']
    finally:
        engine.dispose()

    command.upgrade(config, 'head')
    engine = create_engine(f'sqlite:///{database_path}')
    try:
        assert set(inspect(engine).get_table_names()) == CORE_TABLES | {'alembic_version'}
    finally:
        engine.dispose()


def test_importing_models_and_migration_environment_does_not_create_tables(tmp_path):
    database_path = tmp_path / 'must-not-exist.db'
    env = os.environ.copy()
    env['DATABASE_URL'] = f'sqlite:///{database_path}'

    subprocess.run(
        [
            sys.executable,
            '-c',
            'import whatsapp_chat_system.db.models; import whatsapp_chat_system.db',
        ],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
    )

    assert not database_path.exists()


def test_required_non_null_and_composite_primary_key_metadata():
    from whatsapp_chat_system.db.models import (
        ContactAIOverride,
        Message,
        OutboxMessage,
        WhatsAppEvent,
    )

    assert Message.__table__.c.account_id.nullable is False
    assert Message.__table__.c.conversation_id.nullable is False
    assert WhatsAppEvent.__table__.c.event_id.nullable is False
    assert OutboxMessage.__table__.c.idempotency_key.nullable is False
    assert {column.name for column in ContactAIOverride.__table__.primary_key.columns} == {
        'account_id', 'contact_id',
    }


def test_0003_backfills_old_event_hash_as_same_canonical_envelope(tmp_path):
    from whatsapp_chat_system.events.whatsapp import WhatsAppEventEnvelope, canonical_hash

    database_path = tmp_path / 'old-event.db'
    config = _alembic_config(database_path)
    command.upgrade(config, '0002')
    engine = create_engine(f'sqlite:///{database_path}')
    payload = {'state': 'online'}
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO whatsapp_accounts
              (id, name, status, session_ref, is_primary, enabled, auto_reply_mode, created_at, updated_at)
            VALUES
              ('account-a', 'A', 'online', 'account:account-a', 1, 1, 'off',
               '2026-07-10 00:00:00.000000', '2026-07-10 00:00:00.000000')
        """))
        connection.execute(text("""
            INSERT INTO whatsapp_events
              (id, event_id, account_id, event_type, occurred_at, payload, status)
            VALUES
              ('old-row', 'old-event', 'account-a', 'account.connected',
               '2026-07-10 00:00:00.000000', :payload, 'processed')
        """), {'payload': '{"state":"online"}'})
    engine.dispose()

    command.upgrade(config, '0003')
    engine = create_engine(f'sqlite:///{database_path}')
    with engine.connect() as connection:
        stored = connection.execute(text(
            "SELECT sequence, payload_hash FROM whatsapp_events WHERE id='old-row'"
        )).one()
    engine.dispose()
    envelope = WhatsAppEventEnvelope.model_validate({
        'event_id': 'old-event', 'event_type': 'account.connected', 'account_id': 'account-a',
        'occurred_at': '2026-07-10T00:00:00Z', 'sequence': 0, 'payload': payload,
    })
    assert stored.sequence == 0
    assert stored.payload_hash == canonical_hash(envelope)


def test_0003_downgrade_aborts_clearly_on_cross_account_event_id_conflict(tmp_path):
    database_path = tmp_path / 'downgrade-conflict.db'
    config = _alembic_config(database_path)
    command.upgrade(config, '0003')
    engine = create_engine(f'sqlite:///{database_path}')
    with engine.begin() as connection:
        for account_id in ('account-a', 'account-b'):
            connection.execute(text("""
                INSERT INTO whatsapp_accounts
                  (id, name, status, session_ref, is_primary, enabled, auto_reply_mode,
                   last_event_sequence, created_at, updated_at)
                VALUES
                  (:id, :id, 'offline', :ref, 0, 1, 'off', 0,
                   '2026-07-10 00:00:00', '2026-07-10 00:00:00')
            """), {'id': account_id, 'ref': f'account:{account_id}'})
            connection.execute(text("""
                INSERT INTO whatsapp_events
                  (id, event_id, account_id, event_type, occurred_at, payload, status,
                   sequence, payload_hash)
                VALUES
                  (:id, 'shared-event', :account_id, 'account.disconnected',
                   '2026-07-10 00:00:00', '{}', 'processed', 1, :payload_hash)
            """), {
                'id': f'event-{account_id}',
                'account_id': account_id,
                'payload_hash': account_id.ljust(64, '0'),
            })
    engine.dispose()

    with pytest.raises(RuntimeError, match='cross-account.*event_id.*shared-event'):
        command.downgrade(config, '0002')
