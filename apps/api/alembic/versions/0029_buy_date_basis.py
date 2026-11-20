"""資產組成原型: transactions.date_basis, estimated_date, imported_on

The asset-composition prototype (``docs/proposals/asset-composition.md``, not yet approved by the product owner)
estimates the buy date of a holding imported from a broker screenshot (匯入庫存): the most recent day its price
crossed the broker's average cost. Each such buy says how its date came about:

* ``date_basis``: ``estimated`` | ``picked`` (the user chose the day on the chart) | ``import_day`` (no crossing in
  five years: the import day, as before); NULL for every other row (every existing row);
* ``estimated_date``: the day the estimate found (kept after the user picks another); NULL for ``import_day``;
* ``imported_on``: the day of the import (the estimate looks back from it; a picked day may not be later).

Downgrade: the three columns are dropped (plain ``ALTER TABLE … DROP COLUMN``; SQLite 3.35+ too, never a batch copy
of ``transactions``); the buys keep their dates.

Revision ID: 0029_buy_date_basis
Revises: 0028_remove_blind_test
Create Date: 2026-11-19 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0029_buy_date_basis'
down_revision: str | None = '0028_remove_blind_test'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('transactions', sa.Column('date_basis', sa.String(length=16), nullable=True))
    op.add_column('transactions', sa.Column('estimated_date', sa.Date(), nullable=True))
    op.add_column('transactions', sa.Column('imported_on', sa.Date(), nullable=True))


def downgrade() -> None:
    for column in ('imported_on', 'estimated_date', 'date_basis'):
        op.execute(sa.text(f'ALTER TABLE transactions DROP COLUMN {column}'))
