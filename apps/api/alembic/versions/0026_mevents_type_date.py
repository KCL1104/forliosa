"""market_events: index (type, date) — the market page's 重大訊息 and a stock's exchange news filter by type and date

Both queries scanned the whole table (2026-11-17 API speed review: 1.4 ms today, ~100k rows in a year). A plain
``CREATE INDEX``: the table is small, the write lock is momentary.

The revision id is ``0026_mevents_type_date`` (not ``0026``): another branch may add its own ``0026_*`` after
``0025_mreport_key_state``. After both are merged there are two heads; relink the later-merged one's
``down_revision`` (and its ``Revises:`` line) to the other; the ids stay. Merged into the deploy branch after
``0026_mreport_trial_audience`` (盲測開給所有人), so it now follows that one.

Revision ID: 0026_mevents_type_date
Revises: 0026_mreport_trial_audience
Create Date: 2026-11-17 23:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = '0026_mevents_type_date'
down_revision: str | None = '0026_mreport_trial_audience'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index('ix_market_events_type_date', 'market_events', ['type', 'date'])


def downgrade() -> None:
    op.drop_index('ix_market_events_type_date', table_name='market_events')
