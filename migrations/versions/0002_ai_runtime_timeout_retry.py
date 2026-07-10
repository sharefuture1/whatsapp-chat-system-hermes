"""add AI runtime timeout and retry settings

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ai_runtime_settings') as batch_op:
        batch_op.add_column(
            sa.Column('timeout_seconds', sa.Integer(), nullable=False, server_default='90')
        )
        batch_op.add_column(
            sa.Column('max_retries', sa.Integer(), nullable=False, server_default='2')
        )
        batch_op.create_check_constraint(
            'ck_ai_runtime_settings_timeout_seconds_positive', 'timeout_seconds > 0'
        )
        batch_op.create_check_constraint(
            'ck_ai_runtime_settings_max_retries_non_negative', 'max_retries >= 0'
        )


def downgrade() -> None:
    with op.batch_alter_table('ai_runtime_settings') as batch_op:
        batch_op.drop_constraint(
            'ck_ai_runtime_settings_max_retries_non_negative', type_='check'
        )
        batch_op.drop_constraint(
            'ck_ai_runtime_settings_timeout_seconds_positive', type_='check'
        )
        batch_op.drop_column('max_retries')
        batch_op.drop_column('timeout_seconds')