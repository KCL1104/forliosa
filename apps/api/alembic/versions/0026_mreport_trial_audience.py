"""市場報告: the blind test open to every signed-in user (產品負責人 2026-11-17)

* ``market_report_config.trial_audience`` (admins | all, null = ``MREPORT_TRIAL_AUDIENCE``): who reads and votes on
  the blind-test editions; the admin page can switch it.
* ``market_report_votes.by_admin``: the voter was a site admin (the admin page shows admins' and members' votes
  apart). Every vote cast before this revision was an admin's (only admins could vote), so they are marked true.
* ``market_reports.ai_published_at`` of a blind-test edition: the time its first variant was ready (the members'
  unread dot and list time count from it). Before this revision nothing set it for a blind-test edition, so the
  editions already written get their first variant version's time.

Revision ID: 0026_mreport_trial_audience
Revises: 0025_mreport_key_state
Create Date: 2026-11-17 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0026_mreport_trial_audience'
down_revision: str | None = '0025_mreport_key_state'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('market_report_config') as batch:
        batch.add_column(sa.Column('trial_audience', sa.String(length=8), nullable=True))
    with op.batch_alter_table('market_report_votes') as batch:
        batch.add_column(sa.Column('by_admin', sa.Boolean(), nullable=False, server_default='0'))
    op.execute(sa.text('UPDATE market_report_votes SET by_admin = :yes').bindparams(yes=True))
    op.execute(sa.text(
        'UPDATE market_reports SET ai_published_at = ('
        ' SELECT MIN(v.created_at) FROM market_report_versions v'
        ' WHERE v.report_id = market_reports.id AND v.variant IS NOT NULL)'
        ' WHERE trial = :yes AND ai_published_at IS NULL').bindparams(yes=True))


def downgrade() -> None:
    with op.batch_alter_table('market_report_votes') as batch:
        batch.drop_column('by_admin')
    with op.batch_alter_table('market_report_config') as batch:
        batch.drop_column('trial_audience')
