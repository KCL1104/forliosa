"""Daily closing briefing: one per user and trading day

``ai_briefings`` holds the briefing the worker writes for users who switched 每日收盤簡報 on
(``forliosa.ai.briefing``): the facts computed from their ledger and watchlist, the AI's cited notes about the day's
biggest movers, and when the user read it. The switch itself lives in ``users.preferences`` (``daily_briefing``).

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-14 02:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import forliosa.db

revision: str = '0017'
down_revision: str | None = '0016'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('ai_briefings',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('trading_day', sa.Date(), nullable=False),
    sa.Column('facts', sa.JSON(), nullable=False),
    sa.Column('points', sa.JSON(), nullable=False),
    sa.Column('ai_status', sa.String(length=16), nullable=False),
    sa.Column('model', sa.String(length=64), nullable=False),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('read_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'trading_day', name='uq_ai_briefing_user_day')
    )
    with op.batch_alter_table('ai_briefings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_briefings_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('ai_briefings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ai_briefings_user_id'))
    op.drop_table('ai_briefings')
