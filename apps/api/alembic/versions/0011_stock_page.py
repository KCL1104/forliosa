"""stock page: news headlines (metadata only), related stocks, company facts and description, foreign top 20

News (decisions 1–2): ``news_articles`` — headline, outlet, time and link per symbol (never article text,
descriptions or images), kept 30 days; ``news_blocked_domains`` — the takedown blocklist; ``news_tracked_views`` —
symbol + last viewed time only (no user ids); ``news_fetch_state`` — per source / symbol attempts and the source-wide
backoff after a 429.

Related stocks, company facts, description, foreign holding (decisions 4, 6, 7, 8): ``board_links`` (company ↔
company from 董監事持股餘額明細; no natural persons), ``index_constituents`` (富櫃五十), ``holder_counts_monthly``
(TDCC 集保股東戶數), ``foreign_holding_top20`` (TWSE MI_QFIIS_sort_20), ``esg_product_output`` (ESG 產品類別),
``company_descriptions`` (zh.wikipedia excerpt or AI description) and ``sec_companies.profile`` (SEC facts).

Written on ``0009`` (another branch adds ``0010``); the integrator re-chains it so there is one head —
``tests/test_migrations.py`` fails while there are two.

Revision ID: 0011
Revises: 0009
Create Date: 2026-11-12 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import forliosa.db

revision: str = '0011'
down_revision: str | None = '0009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('news_articles',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('url_key', sa.String(length=64), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('outlet', sa.String(length=100), nullable=False),
    sa.Column('domain', sa.String(length=253), nullable=False),
    sa.Column('published_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('date_only', sa.Boolean(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('fetched_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('symbol', 'url_key', name='uq_news_articles_symbol_url')
    )
    with op.batch_alter_table('news_articles', schema=None) as batch_op:
        batch_op.create_index('ix_news_articles_symbol_published', ['symbol', 'published_at'], unique=False)
        batch_op.create_index('ix_news_articles_published', ['published_at'], unique=False)

    op.create_table('news_blocked_domains',
    sa.Column('domain', sa.String(length=253), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('domain')
    )
    op.create_table('news_tracked_views',
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('last_viewed_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('symbol')
    )
    op.create_table('news_fetch_state',
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('last_attempt_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('last_success_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('last_status', sa.String(length=24), nullable=False),
    sa.Column('items', sa.Integer(), nullable=False),
    sa.Column('failures', sa.Integer(), nullable=False),
    sa.Column('backoff_until', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('source', 'symbol')
    )


    op.create_table('board_links',
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('holder_symbol', sa.String(length=20), nullable=False),
    sa.Column('period', sa.String(length=7), nullable=False),
    sa.Column('roles', sa.String(length=100), nullable=False),
    sa.Column('shares', sa.BigInteger(), nullable=True),
    sa.Column('data_date', sa.Date(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('fetched_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('symbol', 'holder_symbol', 'period')
    )
    with op.batch_alter_table('board_links', schema=None) as batch_op:
        batch_op.create_index('ix_board_links_holder', ['holder_symbol', 'period'], unique=False)

    op.create_table('index_constituents',
    sa.Column('index_code', sa.String(length=16), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.PrimaryKeyConstraint('index_code', 'date', 'symbol')
    )
    op.create_table('holder_counts_monthly',
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('period', sa.String(length=7), nullable=False),
    sa.Column('holders', sa.BigInteger(), nullable=False),
    sa.Column('custody_k_shares', sa.BigInteger(), nullable=True),
    sa.Column('issued_k_shares', sa.BigInteger(), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.PrimaryKeyConstraint('symbol', 'period')
    )
    op.create_table('foreign_holding_top20',
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=False),
    sa.Column('pct', forliosa.db.Money(precision=24, scale=8), nullable=False),
    sa.Column('shares', sa.BigInteger(), nullable=True),
    sa.Column('issued_shares', sa.BigInteger(), nullable=True),
    sa.Column('available_pct', forliosa.db.Money(precision=24, scale=8), nullable=True),
    sa.Column('limit_pct', forliosa.db.Money(precision=24, scale=8), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.PrimaryKeyConstraint('date', 'symbol')
    )
    op.create_table('esg_product_output',
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('data_date', sa.Date(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.PrimaryKeyConstraint('symbol')
    )
    op.create_table('company_descriptions',
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('kind', sa.String(length=12), nullable=False),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('title', sa.String(length=300), nullable=True),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('revision_id', sa.BigInteger(), nullable=True),
    sa.Column('wikidata_id', sa.String(length=20), nullable=True),
    sa.Column('facts_key', sa.String(length=64), nullable=True),
    sa.Column('model', sa.String(length=64), nullable=True),
    sa.Column('sources', sa.JSON(), nullable=True),
    sa.Column('ai_failed_key', sa.String(length=64), nullable=True),
    sa.Column('ai_failures', sa.Integer(), server_default='0', nullable=False),
    sa.Column('ai_attempted_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('checked_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('updated_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('symbol')
    )
    with op.batch_alter_table('sec_companies', schema=None) as batch_op:
        batch_op.add_column(sa.Column('profile', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('sec_companies', schema=None) as batch_op:
        batch_op.drop_column('profile')
    op.drop_table('company_descriptions')
    op.drop_table('esg_product_output')
    op.drop_table('foreign_holding_top20')
    op.drop_table('holder_counts_monthly')
    op.drop_table('index_constituents')
    with op.batch_alter_table('board_links', schema=None) as batch_op:
        batch_op.drop_index('ix_board_links_holder')
    op.drop_table('board_links')
    op.drop_table('news_fetch_state')
    op.drop_table('news_tracked_views')
    op.drop_table('news_blocked_domains')
    with op.batch_alter_table('news_articles', schema=None) as batch_op:
        batch_op.drop_index('ix_news_articles_published')
        batch_op.drop_index('ix_news_articles_symbol_published')
    op.drop_table('news_articles')
