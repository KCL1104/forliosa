"""市場報告: market_report_config.key_state — the reports' own key slot as the worker last saw it

The worker (a separate Railway service) keeps the key pool's slot states in its own memory; the admin page is served
by the API process, whose pool never uses the reports' reserved slot. The worker writes the slot's state here (slot
number, status, note and when it checked; never a key) and the admin overview reads it.

The revision id is ``0025_mreport_key_state`` (not ``0025``): the local branch ``news-tags`` adds ``0024_news_tags``
after ``0023``. After both are merged there are two heads; relink the later-merged one's ``down_revision`` (and its
``Revises:`` line) to the other; the ids stay.

Revision ID: 0025_mreport_key_state
Revises: 0024_market_reports
Create Date: 2026-11-17 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0025_mreport_key_state'
down_revision: str | None = '0024_market_reports'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('market_report_config') as batch:
        batch.add_column(sa.Column('key_state', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('market_report_config') as batch:
        batch.drop_column('key_state')
