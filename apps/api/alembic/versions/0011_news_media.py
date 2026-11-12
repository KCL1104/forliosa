"""news: media headlines (metadata only), takedown blocklist, viewed symbols, fetch state

``news_articles``: headline, outlet, time and link per symbol (never article text, descriptions or images), kept
30 days; ``news_blocked_domains``: the takedown blocklist; ``news_tracked_views``: symbol + last viewed time only
(no user ids); ``news_fetch_state``: per source / symbol attempts and the source-wide backoff after a 429.

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


def downgrade() -> None:
    op.drop_table('news_fetch_state')
    op.drop_table('news_tracked_views')
    op.drop_table('news_blocked_domains')
    with op.batch_alter_table('news_articles', schema=None) as batch_op:
        batch_op.drop_index('ix_news_articles_published')
        batch_op.drop_index('ix_news_articles_symbol_published')
    op.drop_table('news_articles')
