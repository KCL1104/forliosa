"""History backfill: which symbols have been asked for their daily candles before the archive began

``price_backfill`` holds one row per symbol the backfill (``forliosa.history_backfill``, PRICE_HISTORY_SOURCE) has
requested: the outcome, the first date it stored and how many rows. The candles themselves go to ``prices_daily``
with their own ``source`` key.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-13 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import forliosa.db

revision: str = '0015'
down_revision: str | None = '0014'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('price_backfill',
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('first_date', sa.Date(), nullable=True),
    sa.Column('rows', sa.Integer(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('updated_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('symbol')
    )


def downgrade() -> None:
    op.drop_table('price_backfill')
