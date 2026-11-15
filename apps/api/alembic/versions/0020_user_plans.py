"""會員方案: users.plan, plan_until, plan_note

``plan``: "free" (every existing account) or "member"; ``plan_until``: when membership ends (NULL: no end date);
``plan_note``: the site admin's own note. Members are granted on /admin/members until payments exist.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-15 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import forliosa.db

revision: str = '0020'
down_revision: str | None = '0019'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Plain ADD COLUMN on every database (never a batch copy of ``users``, see ``downgrade``)
    op.add_column('users', sa.Column('plan', sa.String(length=16), nullable=False, server_default='free'))
    op.add_column('users', sa.Column('plan_until', forliosa.db.TZDateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('plan_note', sa.String(length=200), nullable=True))


def downgrade() -> None:
    # Plain ALTER TABLE … DROP COLUMN (SQLite 3.35+ too): batch mode would copy and drop ``users`` on SQLite, and with
    # foreign keys on, dropping it deletes every row that cascades from a user (accounts, transactions …).
    for column in ('plan_note', 'plan_until', 'plan'):
        op.execute(sa.text(f'ALTER TABLE users DROP COLUMN {column}'))
