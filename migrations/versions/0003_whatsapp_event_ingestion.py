"""WhatsApp event identity, ordering and message timestamps.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-10
"""

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return value.isoformat(timespec='microseconds' if value.microsecond else 'seconds').replace(
        '+00:00', 'Z'
    )


def _canonical_hash(row: dict[str, Any]) -> str:
    envelope = {
        'event_id': row['event_id'],
        'event_type': row['event_type'],
        'account_id': row['account_id'],
        'occurred_at': _json_datetime(row['occurred_at']),
        'sequence': 0,
        'payload': row['payload'] or {},
    }
    encoded = json.dumps(
        envelope, sort_keys=True, separators=(',', ':'), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def upgrade() -> None:
    with op.batch_alter_table('whatsapp_accounts') as batch_op:
        batch_op.add_column(sa.Column('last_event_sequence', sa.BigInteger(), nullable=False, server_default='0'))

    with op.batch_alter_table('messages') as batch_op:
        batch_op.add_column(sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('received_at', sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table('whatsapp_events') as batch_op:
        batch_op.drop_constraint('uq_whatsapp_events_event_id', type_='unique')
        batch_op.add_column(sa.Column('sequence', sa.BigInteger(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('payload_hash', sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint(
            'uq_whatsapp_events_account_event_id', ['account_id', 'event_id']
        )
        batch_op.create_index(
            'ix_whatsapp_events_account_sequence', ['account_id', 'sequence'], unique=False
        )

    connection = op.get_bind()
    events = sa.table(
        'whatsapp_events',
        sa.column('id', sa.String()),
        sa.column('event_id', sa.String()),
        sa.column('account_id', sa.String()),
        sa.column('event_type', sa.String()),
        sa.column('occurred_at', sa.DateTime(timezone=True)),
        sa.column('payload', sa.JSON()),
        sa.column('payload_hash', sa.String()),
    )
    for row in connection.execute(sa.select(events)).mappings():
        connection.execute(
            events.update().where(events.c.id == row['id']).values(
                payload_hash=_canonical_hash(dict(row))
            )
        )

    with op.batch_alter_table('whatsapp_events') as batch_op:
        batch_op.alter_column(
            'payload_hash', existing_type=sa.String(length=64), nullable=False
        )


def downgrade() -> None:
    connection = op.get_bind()
    conflict = connection.execute(sa.text("""
        SELECT event_id, COUNT(DISTINCT account_id) AS account_count
        FROM whatsapp_events
        GROUP BY event_id
        HAVING COUNT(DISTINCT account_id) > 1
        ORDER BY event_id
        LIMIT 1
    """)).mappings().first()
    if conflict is not None:
        raise RuntimeError(
            'Cannot downgrade migration 0003: cross-account event_id conflict '
            f"for event_id {conflict['event_id']!r}; resolve duplicates before downgrade"
        )
    with op.batch_alter_table('whatsapp_events') as batch_op:
        batch_op.drop_index('ix_whatsapp_events_account_sequence')
        batch_op.drop_constraint('uq_whatsapp_events_account_event_id', type_='unique')
        batch_op.drop_column('payload_hash')
        batch_op.drop_column('sequence')
        batch_op.create_unique_constraint('uq_whatsapp_events_event_id', ['event_id'])

    with op.batch_alter_table('messages') as batch_op:
        batch_op.drop_column('received_at')
        batch_op.drop_column('occurred_at')

    with op.batch_alter_table('whatsapp_accounts') as batch_op:
        batch_op.drop_column('last_event_sequence')
