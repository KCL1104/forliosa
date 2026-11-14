"""Remove the 「只記持股」 (holdings-only) tracking mode: snapshots become dated buys

Product owner, 2026-11-14 (Google Finance style entry: every buy has a date). Every account keeps transactions; the
holdings snapshot and the account's tracking mode go away.

Data conversion, for every broker account with ``tracking_mode = 'holdings'`` that has snapshot rows (the account's
snapshot date = the latest ``as_of`` of its rows):

1. its transactions dated on or before the snapshot date are deleted — the ledger ignored them and the snapshot
   already reflects them, so keeping them would count them twice (an automatic dividend row there goes too; the
   ledger never booked one on or before the snapshot date);
2. each snapshot row becomes one ``buy`` dated its ``as_of``: the snapshot's shares at its average cost, stored the
   way a manual buy from ``POST /transactions`` is (``amount`` = shares × price, no fee / tax / NHI, USD for US
   symbols and TWD otherwise, not a day trade, ``source = 'manual'``), noted 「由「只記持股」轉入」;
3. every account is set to ``transactions``.

Holdings accounts without a snapshot simply become transaction accounts (nothing of theirs was ignored); snapshot rows
of accounts already in transaction mode were never read and are dropped with the table. Then ``holding_snapshots``
and ``broker_accounts.tracking_mode`` are dropped.

The ledger's holdings (shares, cost basis), realized P&L and automatic dividends of a converted account stay the same:
the buy books the shares at the snapshot's cost on its date, and an ex-date on or before it finds no shares the day
before (the holdings mode skipped those ex-dates outright).

**One-way:** the downgrade recreates the column (every account ``transactions``) and an empty ``holding_snapshots``
table; it does not turn the converted buys back into a snapshot or restore the deleted transactions.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-14 12:00:00.000000
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

import forliosa.db
from forliosa.ids import new_id

revision: str = '0018'
down_revision: str | None = '0017'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOTE = '由「只記持股」轉入'

_accounts = sa.table(
    'broker_accounts',
    sa.column('id', sa.String),
    sa.column('user_id', sa.String),
    sa.column('tracking_mode', sa.String),
)
_snapshots = sa.table(
    'holding_snapshots',
    sa.column('account_id', sa.String),
    sa.column('as_of', sa.Date),
    sa.column('symbol', sa.String),
    sa.column('quantity', forliosa.db.Money()),
    sa.column('avg_cost', forliosa.db.Money()),
)
_transactions = sa.table(
    'transactions',
    sa.column('id', sa.String),
    sa.column('user_id', sa.String),
    sa.column('account_id', sa.String),
    sa.column('symbol', sa.String),
    sa.column('type', sa.String),
    sa.column('trade_date', sa.Date),
    sa.column('quantity', forliosa.db.Money()),
    sa.column('price', forliosa.db.Money()),
    sa.column('amount', forliosa.db.Money()),
    sa.column('fee', forliosa.db.Money()),
    sa.column('tax', forliosa.db.Money()),
    sa.column('health_insurance', forliosa.db.Money()),
    sa.column('currency', sa.String),
    sa.column('is_day_trade', sa.Boolean),
    sa.column('note', sa.Text),
    sa.column('source', sa.String),
    sa.column('created_at', forliosa.db.TZDateTime()),
    sa.column('updated_at', forliosa.db.TZDateTime()),
)


def _currency(symbol: str) -> str:
    """What the ledger used for a snapshot row (``market_of_symbol``): Taiwan symbols end in .TW / .TWO."""
    return 'TWD' if symbol.endswith(('.TW', '.TWO')) else 'USD'


def _convert_snapshots(bind) -> None:
    rows = bind.execute(
        sa.select(_accounts.c.id, _accounts.c.user_id, _snapshots.c.as_of, _snapshots.c.symbol,
                  _snapshots.c.quantity, _snapshots.c.avg_cost)
        .select_from(_snapshots.join(_accounts, _accounts.c.id == _snapshots.c.account_id))
        .where(_accounts.c.tracking_mode == 'holdings')
        .order_by(_accounts.c.id, _snapshots.c.symbol)
    ).all()
    by_account: dict[str, list] = defaultdict(list)
    for row in rows:
        by_account[row.id].append(row)
    now = datetime.now(UTC)
    for account_id, snaps in by_account.items():
        cutoff = max(s.as_of for s in snaps)
        bind.execute(sa.delete(_transactions).where(_transactions.c.account_id == account_id,
                                                    _transactions.c.trade_date <= cutoff))
        buys = [{
            'id': new_id('txn'), 'user_id': s.user_id, 'account_id': account_id, 'symbol': s.symbol, 'type': 'buy',
            'trade_date': s.as_of, 'quantity': s.quantity, 'price': s.avg_cost, 'amount': s.quantity * s.avg_cost,
            'fee': 0, 'tax': 0, 'health_insurance': 0, 'currency': _currency(s.symbol), 'is_day_trade': False,
            'note': NOTE, 'source': 'manual', 'created_at': now, 'updated_at': now,
        } for s in snaps]
        bind.execute(sa.insert(_transactions), buys)
    bind.execute(sa.update(_accounts).values(tracking_mode='transactions'))


def upgrade() -> None:
    _convert_snapshots(op.get_bind())

    with op.batch_alter_table('holding_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_holding_snapshots_user_id'))
        batch_op.drop_index(batch_op.f('ix_holding_snapshots_account_id'))
    op.drop_table('holding_snapshots')
    # Not in batch mode: on SQLite a batch drop copies broker_accounts and DROPs the old table, whose implicit DELETE
    # would cascade to every account's transactions (foreign keys are on). SQLite ≥ 3.35 drops the column in place.
    op.drop_column('broker_accounts', 'tracking_mode')


def downgrade() -> None:
    op.add_column('broker_accounts', sa.Column('tracking_mode', sa.String(length=16), nullable=False,
                                               server_default='transactions'))
    op.create_table('holding_snapshots',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('account_id', sa.String(length=32), nullable=False),
    sa.Column('as_of', sa.Date(), nullable=False),
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('quantity', forliosa.db.Money(precision=24, scale=8), nullable=False),
    sa.Column('avg_cost', forliosa.db.Money(precision=24, scale=8), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['broker_accounts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('account_id', 'symbol', name='uq_holding_snapshot_account_symbol')
    )
    with op.batch_alter_table('holding_snapshots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_holding_snapshots_account_id'), ['account_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_holding_snapshots_user_id'), ['user_id'], unique=False)
