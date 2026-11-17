"""市場報告: market_reports, market_report_versions / _gathers / _runs / _votes / _config / _reads, nyse_holidays,
macro_calendar, us_earnings, market_turnover_daily; prices_daily.value; group_channels.notify_premarket / _close /
_weekly; notification_outbox.market_report_id

產品負責人 2026-11-17 (「照建議」: 盤前重點、盤後重點、市場週報, one shared report per edition for signed-in users, a
blind test for site admins first; ``forliosa.reports``). ``prices_daily.value`` is each security's 成交金額 (TWSE
TradeValue, TPEx TransactionAmount); ``market_turnover_daily`` is TWSE FMTQIK. The three hand-kept tables (NYSE
holidays, the macro calendar, US earnings dates) link to official pages only. ``notify_weekly`` is on for every
channel, existing ones included; the daily pushes are off.

The revision id is ``0024_market_reports`` rather than ``0024``: the local branch ``news-tags`` adds
``0024_news_tags`` after ``0023`` too (``us-news-bulk`` has no migration). After both are merged there are two heads
and ``tests/test_migrations.py::test_single_head`` fails: relink the later-merged one's ``down_revision`` (and its
``Revises:`` line) to the other; the ids stay.

Revision ID: 0024_market_reports
Revises: 0024_news_tags
Create Date: 2026-11-17 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import forliosa.db

revision: str = '0024_market_reports'
down_revision: str | None = '0024_news_tags'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Plain ADD COLUMN on every database (never a batch copy of an existing table, see 0023)
    op.add_column('prices_daily', sa.Column('value', sa.BigInteger(), nullable=True))
    op.add_column('group_channels', sa.Column('notify_premarket', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('group_channels', sa.Column('notify_close', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('group_channels', sa.Column('notify_weekly', sa.Boolean(), nullable=False, server_default='1'))
    op.add_column('notification_outbox', sa.Column('market_report_id', sa.String(length=32), nullable=True))

    op.create_table('market_reports',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.String(length=12), nullable=False),
    sa.Column('edition_date', sa.Date(), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('next_start', sa.Date(), nullable=True),
    sa.Column('next_end', sa.Date(), nullable=True),
    sa.Column('state', sa.String(length=12), nullable=False),
    sa.Column('visibility', sa.String(length=8), nullable=False),
    sa.Column('trial', sa.Boolean(), nullable=False),
    sa.Column('backfill', sa.Boolean(), nullable=False),
    sa.Column('current_version_id', sa.String(length=32), nullable=True),
    sa.Column('first_published_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('ai_published_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('pushed_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('push_edition', sa.String(length=8), nullable=True),
    sa.Column('closed_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('notes', sa.JSON(), nullable=False),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('updated_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('kind', 'edition_date', name='uq_market_report_edition')
    )
    op.create_index('ix_market_reports_visible', 'market_reports', ['visibility', 'first_published_at'],
                    unique=False)

    op.create_table('market_report_versions',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('report_id', sa.String(length=32), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('variant', sa.String(length=1), nullable=True),
    sa.Column('edition', sa.String(length=12), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('writer', sa.JSON(), nullable=True),
    sa.Column('run_id', sa.String(length=32), nullable=True),
    sa.Column('prompt_version', sa.String(length=32), nullable=False),
    sa.Column('validation', sa.JSON(), nullable=False),
    sa.Column('based_on', sa.String(length=32), nullable=True),
    sa.Column('correction_note', sa.Text(), nullable=True),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['report_id'], ['market_reports.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('report_id', 'version', name='uq_market_report_version')
    )
    op.create_index('ix_market_report_versions_report_id', 'market_report_versions', ['report_id'], unique=False)

    op.create_table('market_report_gathers',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('report_id', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('topics', sa.JSON(), nullable=False),
    sa.Column('facts', sa.JSON(), nullable=False),
    sa.Column('disagreements', sa.JSON(), nullable=False),
    sa.Column('cost_usd', forliosa.db.Money(), nullable=False),
    sa.Column('key_slot', sa.Integer(), nullable=True),
    sa.Column('started_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('finished_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['report_id'], ['market_reports.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_market_report_gathers_report_id', 'market_report_gathers', ['report_id'], unique=False)

    op.create_table('market_report_runs',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('report_id', sa.String(length=32), nullable=False),
    sa.Column('variant', sa.String(length=1), nullable=True),
    sa.Column('purpose', sa.String(length=8), nullable=False),
    sa.Column('attempt', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('step', sa.String(length=12), nullable=False),
    sa.Column('tier', sa.String(length=12), nullable=False),
    sa.Column('writer', sa.JSON(), nullable=False),
    sa.Column('key_slot', sa.Integer(), nullable=True),
    sa.Column('gather_id', sa.String(length=32), nullable=True),
    sa.Column('pack_gz', sa.LargeBinary(), nullable=True),
    sa.Column('calls', sa.JSON(), nullable=False),
    sa.Column('cost_usd', forliosa.db.Money(), nullable=False),
    sa.Column('metrics', sa.JSON(), nullable=False),
    sa.Column('error', sa.String(length=200), nullable=True),
    sa.Column('started_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('heartbeat_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('finished_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['report_id'], ['market_reports.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_market_report_runs_report', 'market_report_runs', ['report_id', 'variant'], unique=False)

    op.create_table('market_report_votes',
    sa.Column('report_id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('preferred', sa.String(length=1), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('updated_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['report_id'], ['market_reports.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('report_id', 'user_id')
    )

    op.create_table('market_report_config',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('mode', sa.String(length=8), nullable=False),
    sa.Column('writers', sa.JSON(), nullable=False),
    sa.Column('trial_started_on', sa.Date(), nullable=True),
    sa.Column('revealed_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('updated_by', sa.String(length=32), nullable=True),
    sa.Column('updated_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )

    op.create_table('market_report_reads',
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('seen_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id')
    )

    op.create_table('nyse_holidays',
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('kind', sa.String(length=12), nullable=False),
    sa.Column('close_time_et', sa.String(length=5), nullable=True),
    sa.Column('source_url', sa.Text(), nullable=False),
    sa.Column('verified_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('updated_by', sa.String(length=32), nullable=True),
    sa.Column('updated_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('date')
    )

    op.create_table('macro_calendar',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('event_date', sa.Date(), nullable=False),
    sa.Column('local_time', sa.String(length=5), nullable=True),
    sa.Column('tz', sa.String(length=32), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('agency', sa.String(length=80), nullable=False),
    sa.Column('official_url', sa.Text(), nullable=False),
    sa.Column('sectors', sa.JSON(), nullable=False),
    sa.Column('note', sa.String(length=200), nullable=False),
    sa.Column('created_by', sa.String(length=32), nullable=True),
    sa.Column('updated_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_macro_calendar_date', 'macro_calendar', ['event_date'], unique=False)

    op.create_table('us_earnings',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('company', sa.String(length=100), nullable=False),
    sa.Column('report_date', sa.Date(), nullable=False),
    sa.Column('timing', sa.String(length=8), nullable=False),
    sa.Column('time_et', sa.String(length=5), nullable=True),
    sa.Column('official_url', sa.Text(), nullable=True),
    sa.Column('sectors', sa.JSON(), nullable=False),
    sa.Column('note', sa.String(length=200), nullable=False),
    sa.Column('verified_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.String(length=32), nullable=True),
    sa.Column('updated_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('symbol', 'report_date', name='uq_us_earnings_symbol_date')
    )
    op.create_index('ix_us_earnings_date', 'us_earnings', ['report_date'], unique=False)

    op.create_table('market_turnover_daily',
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('market', sa.String(length=8), nullable=False),
    sa.Column('trade_volume', sa.BigInteger(), nullable=True),
    sa.Column('trade_value', sa.BigInteger(), nullable=True),
    sa.Column('transactions', sa.BigInteger(), nullable=True),
    sa.Column('taiex', forliosa.db.Money(), nullable=True),
    sa.Column('change', forliosa.db.Money(), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.PrimaryKeyConstraint('date', 'market')
    )


def downgrade() -> None:
    op.drop_table('market_turnover_daily')
    op.drop_index('ix_us_earnings_date', table_name='us_earnings')
    op.drop_table('us_earnings')
    op.drop_index('ix_macro_calendar_date', table_name='macro_calendar')
    op.drop_table('macro_calendar')
    op.drop_table('nyse_holidays')
    op.drop_table('market_report_reads')
    op.drop_table('market_report_config')
    op.drop_table('market_report_votes')
    op.drop_index('ix_market_report_runs_report', table_name='market_report_runs')
    op.drop_table('market_report_runs')
    op.drop_index('ix_market_report_gathers_report_id', table_name='market_report_gathers')
    op.drop_table('market_report_gathers')
    op.drop_index('ix_market_report_versions_report_id', table_name='market_report_versions')
    op.drop_table('market_report_versions')
    op.drop_index('ix_market_reports_visible', table_name='market_reports')
    op.drop_table('market_reports')
    # Plain ALTER TABLE … DROP COLUMN (SQLite 3.35+ too): a batch copy would drop and recreate these tables on
    # SQLite, and with foreign keys on, dropping ``group_channels``' parent rows would cascade (see 0023).
    op.execute(sa.text('ALTER TABLE notification_outbox DROP COLUMN market_report_id'))
    op.execute(sa.text('ALTER TABLE group_channels DROP COLUMN notify_weekly'))
    op.execute(sa.text('ALTER TABLE group_channels DROP COLUMN notify_close'))
    op.execute(sa.text('ALTER TABLE group_channels DROP COLUMN notify_premarket'))
    op.execute(sa.text('ALTER TABLE prices_daily DROP COLUMN value'))
