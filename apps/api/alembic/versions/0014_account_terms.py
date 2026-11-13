"""Account: terms version agreed to, suspension carry-over for deleted accounts

* ``users.terms_version_accepted`` / ``terms_accepted_at``: the version of the terms of service and privacy policy
  (``TERMS_VERSION``) the user agreed to (at sign-up, or ``POST /me/terms-accept``).
* ``discussion_suspension_carryovers``: a public-posting suspension kept after its account was deleted, keyed by a
  keyed hash of the login identity (not reversible to the person), applied again if the same identity re-registers.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-13 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import forliosa.db

revision: str = '0014'
down_revision: str | None = '0013'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('terms_version_accepted', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('terms_accepted_at', forliosa.db.TZDateTime(timezone=True), nullable=True))

    op.create_table('discussion_suspension_carryovers',
    sa.Column('identity_hash', sa.String(length=64), nullable=False),
    sa.Column('until', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('identity_hash')
    )


def downgrade() -> None:
    op.drop_table('discussion_suspension_carryovers')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('terms_accepted_at')
        batch_op.drop_column('terms_version_accepted')
