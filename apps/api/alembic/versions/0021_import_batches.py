"""匯入對帳單: transactions.import_batch_id

The statement import (產品負責人 2026-11-16) writes all of its rows in one ``POST /transactions/batch`` and stamps
them with the batch id, so ``DELETE /transactions/batches/{id}`` can undo the whole import. NULL for every other row
(every existing row). No table of imports and no stored files: the statement is read and thrown away.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-16 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0021'
down_revision: str | None = '0020'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Plain ADD COLUMN and CREATE INDEX on every database (never a batch copy of ``transactions``, see ``downgrade``)
    op.add_column('transactions', sa.Column('import_batch_id', sa.String(length=32), nullable=True))
    op.create_index('ix_transactions_import_batch_id', 'transactions', ['import_batch_id'], unique=False)


def downgrade() -> None:
    # The index first: SQLite cannot drop an indexed column. Then a plain ALTER TABLE … DROP COLUMN (SQLite 3.35+ too):
    # batch mode would copy and drop ``transactions`` on SQLite.
    op.drop_index('ix_transactions_import_batch_id', table_name='transactions')
    op.execute(sa.text('ALTER TABLE transactions DROP COLUMN import_batch_id'))
