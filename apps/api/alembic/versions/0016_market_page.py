"""Market page: the shared AI summary of a trading day, and an index for one day's closes

* ``ai_market_summary``: one row per Taiwan trading day (``forliosa.ai.market_summary``) — headline, points and the
  search results each point cites; shared by every user.
* ``ix_prices_daily_date``: the market page ranks every symbol of the latest day; ``prices_daily``'s primary key
  starts with the symbol, so a day's rows get their own index.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-13 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import forliosa.db

revision: str = '0016'
down_revision: str | None = '0015'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('ai_market_summary',
    sa.Column('trading_day', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('headline', sa.Text(), nullable=False),
    sa.Column('points', sa.JSON(), nullable=False),
    sa.Column('model', sa.String(length=64), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('trading_day')
    )
    with op.batch_alter_table('prices_daily', schema=None) as batch_op:
        batch_op.create_index('ix_prices_daily_date', ['date'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('prices_daily', schema=None) as batch_op:
        batch_op.drop_index('ix_prices_daily_date')
    op.drop_table('ai_market_summary')
