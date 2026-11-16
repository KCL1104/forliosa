"""群組加值包與群組 AI 日報: group_passes, group_daily_reports, groups.grandfathered_member_cap, …

產品負責人 2026-11-16 (群組訂閱 memo, all 14 recommendations): a free group takes up to 15 members, a boosted one 50.
Every group that exists now keeps 50 (``groups.grandfathered_member_cap = 50``, set here); groups made later get NULL.
``group_passes``: boosts a site admin grants by hand (no payments yet), attached to one group by its owner.
``group_daily_reports``: the daily AI report of boosted groups (facts by user id, filtered on read; 30 days).
``group_channels.notify_daily`` (off) and ``notification_outbox.daily_report_id`` carry its pushes.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-16 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import forliosa.db

revision: str = '0023'
down_revision: str | None = '0022'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Plain ADD COLUMN on every database (never a batch copy of ``groups`` or the outbox, see ``downgrade``)
    op.add_column('groups', sa.Column('grandfathered_member_cap', sa.Integer(), nullable=True))
    op.execute(sa.text('UPDATE groups SET grandfathered_member_cap = 50'))
    op.add_column('group_channels', sa.Column('notify_daily', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('notification_outbox', sa.Column('daily_report_id', sa.String(length=32), nullable=True))

    op.create_table('group_passes',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('payer_id', sa.String(length=32), nullable=True),
    sa.Column('group_id', sa.String(length=32), nullable=True),
    sa.Column('until', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('note', sa.String(length=200), nullable=True),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('attached_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('updated_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['payer_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_group_passes_group_id', 'group_passes', ['group_id'], unique=False)
    op.create_index('ix_group_passes_payer_id', 'group_passes', ['payer_id'], unique=False)

    op.create_table('group_daily_reports',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('group_id', sa.String(length=32), nullable=False),
    sa.Column('trading_day', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('facts', sa.JSON(), nullable=False),
    sa.Column('sources', sa.JSON(), nullable=False),
    sa.Column('model', sa.String(length=64), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('error', sa.String(length=200), nullable=True),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('finished_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('group_id', 'trading_day', name='uq_group_daily_day')
    )
    op.create_index('ix_group_daily_reports_group_id', 'group_daily_reports', ['group_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_group_daily_reports_group_id', table_name='group_daily_reports')
    op.drop_table('group_daily_reports')
    op.drop_index('ix_group_passes_payer_id', table_name='group_passes')
    op.drop_index('ix_group_passes_group_id', table_name='group_passes')
    op.drop_table('group_passes')
    # Plain ALTER TABLE … DROP COLUMN (SQLite 3.35+ too): batch mode would copy and drop these tables on SQLite, and
    # with foreign keys on, dropping ``groups`` deletes every row that cascades from a group.
    op.execute(sa.text('ALTER TABLE notification_outbox DROP COLUMN daily_report_id'))
    op.execute(sa.text('ALTER TABLE group_channels DROP COLUMN notify_daily'))
    op.execute(sa.text('ALTER TABLE groups DROP COLUMN grandfathered_member_cap'))
