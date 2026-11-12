"""ai key slots (sticky per thread, per-slot usage) and retention indexes

* ``ai_threads.key_slot``: the API key slot (workspace) a thread is pinned to; never the key.
* ``ai_threads.context_from_seq``: after a move to another slot, replay starts at the recap messages.
* ``ai_usage.key_index`` → ``key_slot`` (the n of ``CLAUDE_API_KEY_<n>``), indexed with ``created_at`` for the
  per-slot monthly cost.
* ``updated_at`` indexes on ``ai_threads`` / ``ai_drafts`` for the 30-day retention purge.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-12 06:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('ai_threads', schema=None) as batch_op:
        batch_op.add_column(sa.Column('key_slot', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('context_from_seq', sa.Integer(), nullable=False, server_default='0'))
        batch_op.create_index('ix_ai_threads_updated', ['updated_at'], unique=False)

    with op.batch_alter_table('ai_usage', schema=None) as batch_op:
        batch_op.alter_column('key_index', new_column_name='key_slot', existing_type=sa.Integer(),
                              existing_nullable=True)
    with op.batch_alter_table('ai_usage', schema=None) as batch_op:  # a separate batch: the column is renamed now
        batch_op.create_index('ix_ai_usage_slot_created', ['key_slot', 'created_at'], unique=False)

    with op.batch_alter_table('ai_drafts', schema=None) as batch_op:
        batch_op.create_index('ix_ai_drafts_updated', ['updated_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('ai_drafts', schema=None) as batch_op:
        batch_op.drop_index('ix_ai_drafts_updated')

    with op.batch_alter_table('ai_usage', schema=None) as batch_op:
        batch_op.drop_index('ix_ai_usage_slot_created')
    with op.batch_alter_table('ai_usage', schema=None) as batch_op:
        batch_op.alter_column('key_slot', new_column_name='key_index', existing_type=sa.Integer(),
                              existing_nullable=True)

    with op.batch_alter_table('ai_threads', schema=None) as batch_op:
        batch_op.drop_index('ix_ai_threads_updated')
        batch_op.drop_column('context_from_seq')
        batch_op.drop_column('key_slot')
