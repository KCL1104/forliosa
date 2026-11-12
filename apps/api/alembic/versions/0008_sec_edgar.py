"""SEC EDGAR cache: ticker -> CIK map, trimmed XBRL company facts, 8-K / 10-Q / 10-K filings

* ``sec_tickers``: www.sec.gov/files/company_tickers.json.
* ``sec_companies``: one row per CIK: trimmed company facts (JSON), cover-page shares, fetch times.
* ``sec_filings``: filing index rows from data.sec.gov/submissions (link only, no document content).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-12 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import forliosa.db

revision: str = '0008'
down_revision: str | None = '0007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('sec_tickers',
    sa.Column('ticker', sa.String(length=20), nullable=False),
    sa.Column('cik', sa.BigInteger(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('fetched_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('ticker')
    )
    with op.batch_alter_table('sec_tickers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sec_tickers_cik'), ['cik'], unique=False)
    op.create_table('sec_companies',
    sa.Column('cik', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('fiscal_year_end', sa.String(length=4), nullable=True),
    sa.Column('facts', sa.JSON(), nullable=False),
    sa.Column('shares_outstanding', sa.BigInteger(), nullable=True),
    sa.Column('shares_as_of', sa.Date(), nullable=True),
    sa.Column('facts_fetched_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('filings_fetched_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.PrimaryKeyConstraint('cik')
    )
    op.create_table('sec_filings',
    sa.Column('cik', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('accession', sa.String(length=24), nullable=False),
    sa.Column('form', sa.String(length=12), nullable=False),
    sa.Column('filing_date', sa.Date(), nullable=False),
    sa.Column('report_date', sa.Date(), nullable=True),
    sa.Column('items', sa.String(length=120), nullable=False),
    sa.Column('primary_document', sa.String(length=200), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('fetched_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('cik', 'accession')
    )
    with op.batch_alter_table('sec_filings', schema=None) as batch_op:
        batch_op.create_index('ix_sec_filings_cik_date', ['cik', 'filing_date'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('sec_filings', schema=None) as batch_op:
        batch_op.drop_index('ix_sec_filings_cik_date')
    op.drop_table('sec_filings')
    op.drop_table('sec_companies')
    with op.batch_alter_table('sec_tickers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sec_tickers_cik'))
    op.drop_table('sec_tickers')
