"""新聞標籤: news_tags, news_tag_state, news_articles.url_key index

產品負責人 2026-11-17 (「入庫時用 Haiku 貼主題與類股標籤」, ``forliosa.news.tagging``): each stored headline URL gets
themes, sectors and related stocks from a fixed vocabulary (``forliosa.news.taxonomy``), so the AI chat
(``search_news``) and the market reports can group and find news by topic. ``news_tags`` holds one row per tag
(queryable by ``(kind, value)``); ``news_tag_state`` one row per URL (status, model, taxonomy version, attempts, the
batch size it may be sent in after an unusable answer).
Both are keyed by ``news_articles.url_key``, which gets its own index for the join. No content beyond the ids.

The revision id is ``0024_news_tags`` rather than ``0024``: other branches made at the same time (events-past-fix,
us-news-bulk) may add their own ``0024`` after ``0023``; distinct ids keep ``alembic`` from confusing the two, and
``tests/test_migrations.py::test_single_head`` says which one to relink after the merge.

Revision ID: 0024_news_tags
Revises: 0023
Create Date: 2026-11-17 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import forliosa.db

revision: str = '0024_news_tags'
down_revision: str | None = '0023'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('news_tags',
    sa.Column('url_key', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('value', sa.String(length=32), nullable=False),
    sa.Column('relation', sa.String(length=16), nullable=True),
    sa.PrimaryKeyConstraint('url_key', 'kind', 'value')
    )
    op.create_index('ix_news_tags_kind_value', 'news_tags', ['kind', 'value'], unique=False)
    op.create_table('news_tag_state',
    sa.Column('url_key', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('model', sa.String(length=64), nullable=False, server_default=''),
    sa.Column('taxonomy_version', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('tagged_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('retry_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('batch_limit', sa.Integer(), nullable=True),
    sa.Column('updated_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('url_key')
    )
    # Plain CREATE INDEX on every database (no batch copy of news_articles)
    op.create_index('ix_news_articles_url_key', 'news_articles', ['url_key'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_news_articles_url_key', table_name='news_articles')
    op.drop_table('news_tag_state')
    op.drop_index('ix_news_tags_kind_value', table_name='news_tags')
    op.drop_table('news_tags')
