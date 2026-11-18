"""group_channels: four push switches per channel (產品負責人 2026-11-18, option A)

The 頻道 tab had two switches for the same thing: 週報 (the group's weekly digest) next to 市場週報, 日報 (the group's
daily report) next to 盤前重點. Each channel now keeps four: 交易動態 (``notify_trades``), 盤前 (``notify_premarket``:
盤前重點 with 「昨日你的群組」, the group's daily report, in one message), 盤後 (``notify_close``) and 週報
(``notify_weekly``: 市場週報 with the group's weekly digest, in one message, Sunday 18:00).

Data: every opt-in is kept — ``notify_premarket := notify_premarket OR notify_daily`` and
``notify_weekly := notify_weekly OR notify_digest``. ``notify_daily`` / ``notify_digest`` stay in the table
(deprecated, no longer read by the new code; it only ever lowers them, see ``channels._lower_deprecated``).

Downgrade: nothing is dropped and nothing is turned on. The new columns keep their merged values (an OR cannot be split
back); the old ones become ``notify_digest := notify_digest AND notify_weekly`` and
``notify_daily := notify_daily AND notify_premarket`` — for a channel nobody touched since the upgrade that changes
nothing (the OR made the new switch true wherever the old one was), and a 週報 / 盤前 the owner turned off after the
upgrade keeps the old code from sending the group digest / daily report there again.

Revision ID: 0027_channel_four_switches
Revises: 0026_mevents_type_date
Create Date: 2026-11-18 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0027_channel_four_switches'
down_revision: str | None = '0026_mevents_type_date'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

channels = sa.table('group_channels', sa.column('notify_premarket', sa.Boolean), sa.column('notify_daily', sa.Boolean),
                    sa.column('notify_weekly', sa.Boolean), sa.column('notify_digest', sa.Boolean))


def upgrade() -> None:
    op.execute(channels.update().where(channels.c.notify_daily == sa.true()).values(notify_premarket=sa.true()))
    op.execute(channels.update().where(channels.c.notify_digest == sa.true()).values(notify_weekly=sa.true()))


def downgrade() -> None:
    """The old columns lose only what was turned off after the upgrade (an AND never turns anything on)."""
    op.execute(channels.update().where(channels.c.notify_weekly == sa.false()).values(notify_digest=sa.false()))
    op.execute(channels.update().where(channels.c.notify_premarket == sa.false()).values(notify_daily=sa.false()))
