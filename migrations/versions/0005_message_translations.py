"""message_translations

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-14 20:45:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'translation_batches',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('account_id', sa.String(length=36), nullable=False),
        sa.Column('conversation_id', sa.String(length=36), nullable=False),
        sa.Column('anchor_message_id', sa.String(length=36), nullable=False),
        sa.Column('target_lang', sa.String(length=32), nullable=False),
        sa.Column('window_size', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('retry_after', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_code', sa.String(length=128), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('requested_by', sa.String(length=255), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'claimed', 'running', 'completed', 'failed', 'dead')", name='ck_translation_batches_status_valid'),
        sa.ForeignKeyConstraint(['account_id'], ['whatsapp_accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['anchor_message_id'], ['messages.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_translation_batches_account_status_created', 'translation_batches', ['account_id', 'status', 'created_at'], unique=False)
    op.create_index('ix_translation_batches_account_status_retry', 'translation_batches', ['account_id', 'status', 'retry_after'], unique=False)

    op.create_table(
        'message_translations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('account_id', sa.String(length=36), nullable=False),
        sa.Column('conversation_id', sa.String(length=36), nullable=False),
        sa.Column('message_id', sa.String(length=36), nullable=False),
        sa.Column('source_text', sa.Text(), nullable=True),
        sa.Column('source_text_hash', sa.String(length=64), nullable=False),
        sa.Column('source_lang', sa.String(length=32), nullable=True),
        sa.Column('target_lang', sa.String(length=32), nullable=False),
        sa.Column('translated_text', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('error_code', sa.String(length=128), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_after', sa.DateTime(timezone=True), nullable=True),
        sa.Column('provider', sa.String(length=64), nullable=True),
        sa.Column('model', sa.String(length=255), nullable=True),
        sa.Column('context_window_size', sa.Integer(), nullable=False),
        sa.Column('batch_id', sa.String(length=36), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed', 'dead')", name='ck_message_translations_status_valid'),
        sa.ForeignKeyConstraint(['account_id'], ['whatsapp_accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['batch_id'], ['translation_batches.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_id', 'target_lang', 'source_text_hash', name='uq_message_translations_message_target_hash'),
    )
    op.create_index('ix_message_translations_conversation_status_updated', 'message_translations', ['conversation_id', 'status', 'updated_at'], unique=False)
    op.create_index('ix_message_translations_account_status_retry', 'message_translations', ['account_id', 'status', 'retry_after'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_message_translations_account_status_retry', table_name='message_translations')
    op.drop_index('ix_message_translations_conversation_status_updated', table_name='message_translations')
    op.drop_table('message_translations')
    op.drop_index('ix_translation_batches_account_status_retry', table_name='translation_batches')
    op.drop_index('ix_translation_batches_account_status_created', table_name='translation_batches')
    op.drop_table('translation_batches')
