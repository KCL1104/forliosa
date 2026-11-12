"""analyst views: shared cache of third-party ratings found by AI web search

``ai_analyst_views``: one entry per symbol per Taiwan trading day (``forliosa.ai.analyst``), deleted 24 hours after
it was created. Only the verified items of one answer are kept (no history, no aggregates).

Revision ID: 0009
Revises: 0007
Create Date: 2026-11-12 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import forliosa.db

revision: str = '0009'
down_revision: str | None = '0007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('ai_analyst_views',
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('trading_day', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('items', sa.JSON(), nullable=False),
    sa.Column('notes', sa.JSON(), nullable=False),
    sa.Column('model', sa.String(length=64), nullable=False),
    sa.Column('generation_id', sa.String(length=32), nullable=False),
    sa.Column('requested_by', sa.String(length=32), nullable=True),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('finished_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('expires_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('symbol', 'trading_day')
    )
    with op.batch_alter_table('ai_analyst_views', schema=None) as batch_op:
        batch_op.create_index('ix_ai_analyst_views_expires', ['expires_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('ai_analyst_views', schema=None) as batch_op:
        batch_op.drop_index('ix_ai_analyst_views_expires')
    op.drop_table('ai_analyst_views')
