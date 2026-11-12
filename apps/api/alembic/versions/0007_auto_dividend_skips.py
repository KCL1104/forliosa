"""automatic dividend booking: skips for deleted / edited automatic dividends

``transactions.source`` gains ``auto`` (booked by ``forliosa.services.auto_dividends``) and ``auto_edited`` (an
automatic dividend the user edited); the column is already a free-form String(16), so only the skip table is new.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-12 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import forliosa.db

revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('auto_dividend_skips',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('account_id', sa.String(length=32), nullable=False),
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('ex_date', sa.Date(), nullable=False),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('reason', sa.String(length=16), nullable=False),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['broker_accounts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('account_id', 'symbol', 'ex_date', 'kind', name='uq_auto_dividend_skip')
    )
    with op.batch_alter_table('auto_dividend_skips', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_auto_dividend_skips_account_id'), ['account_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_auto_dividend_skips_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('auto_dividend_skips', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_auto_dividend_skips_user_id'))
        batch_op.drop_index(batch_op.f('ix_auto_dividend_skips_account_id'))
    op.drop_table('auto_dividend_skips')
