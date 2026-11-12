"""ETF NAV (decision 9): ``etf_navs`` — the daily NAV of listed / OTC ETFs from 金融監督管理委員會證券期貨局
〈證券投資信託基金每日淨值〉 (data.gov.tw 11109, OGDL). The premium / discount is computed on read against the archived
official close of the same day, so nothing else is stored.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-12 22:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import forliosa.db

revision: str = '0012'
down_revision: str | None = '0011'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('etf_navs',
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('nav', forliosa.db.Money(precision=24, scale=8), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('fund_name', sa.String(length=200), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('fetched_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('symbol', 'date')
    )
    with op.batch_alter_table('etf_navs', schema=None) as batch_op:
        batch_op.create_index('ix_etf_navs_date', ['date'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('etf_navs', schema=None) as batch_op:
        batch_op.drop_index('ix_etf_navs_date')
    op.drop_table('etf_navs')
