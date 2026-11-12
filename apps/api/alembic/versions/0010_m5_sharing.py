"""M5 sharing: Discord login, read-only delegations, family groups (one revision for all of M5)

* ``users.avatar_url`` and ``user_identities`` (Discord id -> user; provider tokens are never stored).
* ``delegations`` / ``delegation_accounts`` (one-to-one read-only access; an account leaves the scope when deleted).
* ``groups``, ``group_members`` (owner / admin / member), ``group_share_settings`` (per member per group; deleted
  with the membership), ``group_invites`` (SHA-256 of the token only), ``group_comments``, ``group_reactions``.
* Used by the second half of M5: ``group_digests`` (weekly AI digest), ``group_channels`` (Discord webhook encrypted
  at rest, Telegram chat), ``notification_outbox`` (pending pushes), ``telegram_link_codes`` (SHA-256 only).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-12 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import forliosa.db

revision: str = '0010'
down_revision: str | None = '0009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('groups',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('ranking_enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('updated_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('delegations',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('owner_id', sa.String(length=32), nullable=False),
    sa.Column('viewer_id', sa.String(length=32), nullable=False),
    sa.Column('scope', sa.String(length=8), nullable=False),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('updated_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['viewer_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'viewer_id', name='uq_delegation_owner_viewer')
    )
    with op.batch_alter_table('delegations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_delegations_owner_id'), ['owner_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_delegations_viewer_id'), ['viewer_id'], unique=False)

    op.create_table('group_channels',
    sa.Column('group_id', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('disabled_reason', sa.String(length=32), nullable=True),
    sa.Column('webhook_encrypted', sa.Text(), nullable=True),
    sa.Column('webhook_hint', sa.String(length=8), nullable=True),
    sa.Column('telegram_chat_id', sa.BigInteger(), nullable=True),
    sa.Column('chat_title', sa.String(length=255), nullable=True),
    sa.Column('notify_trades', sa.Boolean(), nullable=False),
    sa.Column('notify_digest', sa.Boolean(), nullable=False),
    sa.Column('configured_by', sa.String(length=32), nullable=True),
    sa.Column('configured_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('updated_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['configured_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('group_id', 'kind')
    )
    op.create_table('group_comments',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('group_id', sa.String(length=32), nullable=False),
    sa.Column('target', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('group_comments', schema=None) as batch_op:
        batch_op.create_index('ix_group_comments_target', ['group_id', 'target', 'created_at'], unique=False)

    op.create_table('group_digests',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('group_id', sa.String(length=32), nullable=False),
    sa.Column('week_start', sa.Date(), nullable=False),
    sa.Column('week_end', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('facts', sa.JSON(), nullable=False),
    sa.Column('sources', sa.JSON(), nullable=False),
    sa.Column('batch_id', sa.String(length=100), nullable=True),
    sa.Column('model', sa.String(length=64), nullable=False),
    sa.Column('error', sa.String(length=200), nullable=True),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('finished_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('group_id', 'week_start', name='uq_group_digest_week')
    )
    with op.batch_alter_table('group_digests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_group_digests_group_id'), ['group_id'], unique=False)

    op.create_table('group_invites',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('group_id', sa.String(length=32), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_by', sa.String(length=32), nullable=True),
    sa.Column('multi_use', sa.Boolean(), nullable=False),
    sa.Column('uses', sa.Integer(), nullable=False),
    sa.Column('expires_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    with op.batch_alter_table('group_invites', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_group_invites_group_id'), ['group_id'], unique=False)

    op.create_table('group_members',
    sa.Column('group_id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('role', sa.String(length=8), nullable=False),
    sa.Column('joined_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('group_id', 'user_id')
    )
    with op.batch_alter_table('group_members', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_group_members_user_id'), ['user_id'], unique=False)

    op.create_table('group_reactions',
    sa.Column('group_id', sa.String(length=32), nullable=False),
    sa.Column('target', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('emoji', sa.String(length=16), nullable=False),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('group_id', 'target', 'user_id', 'emoji')
    )
    op.create_table('telegram_link_codes',
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('group_id', sa.String(length=32), nullable=False),
    sa.Column('created_by', sa.String(length=32), nullable=False),
    sa.Column('expires_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('used_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('code_hash')
    )
    with op.batch_alter_table('telegram_link_codes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_telegram_link_codes_group_id'), ['group_id'], unique=False)

    op.create_table('user_identities',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('provider', sa.String(length=16), nullable=False),
    sa.Column('subject', sa.String(length=64), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('last_login_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider', 'subject', name='uq_user_identity_subject'),
    sa.UniqueConstraint('user_id', 'provider', name='uq_user_identity_user_provider')
    )
    with op.batch_alter_table('user_identities', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_identities_user_id'), ['user_id'], unique=False)

    op.create_table('delegation_accounts',
    sa.Column('delegation_id', sa.String(length=32), nullable=False),
    sa.Column('account_id', sa.String(length=32), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['broker_accounts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['delegation_id'], ['delegations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('delegation_id', 'account_id')
    )
    with op.batch_alter_table('delegation_accounts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_delegation_accounts_account_id'), ['account_id'], unique=False)

    op.create_table('group_share_settings',
    sa.Column('group_id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('returns', sa.Boolean(), nullable=False),
    sa.Column('holdings', sa.Boolean(), nullable=False),
    sa.Column('amounts', sa.Boolean(), nullable=False),
    sa.Column('trades', sa.Boolean(), nullable=False),
    sa.Column('trade_prices', sa.Boolean(), nullable=False),
    sa.Column('push', sa.Boolean(), nullable=False),
    sa.Column('trades_enabled_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('push_enabled_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.Column('updated_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['group_id', 'user_id'], ['group_members.group_id', 'group_members.user_id'], name='fk_group_share_member', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('group_id', 'user_id')
    )
    op.create_table('notification_outbox',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('group_id', sa.String(length=32), nullable=False),
    sa.Column('channel_kind', sa.String(length=10), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('dedupe_key', sa.String(length=160), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=True),
    sa.Column('transaction_id', sa.String(length=32), nullable=True),
    sa.Column('digest_id', sa.String(length=32), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('not_before', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('last_error', sa.String(length=200), nullable=True),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('sent_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['digest_id'], ['group_digests.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dedupe_key')
    )
    with op.batch_alter_table('notification_outbox', schema=None) as batch_op:
        batch_op.create_index('ix_notification_outbox_due', ['status', 'not_before'], unique=False)
        batch_op.create_index(batch_op.f('ix_notification_outbox_group_id'), ['group_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_notification_outbox_transaction_id'), ['transaction_id'], unique=False)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('avatar_url', sa.String(length=500), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('avatar_url')

    with op.batch_alter_table('notification_outbox', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notification_outbox_transaction_id'))
        batch_op.drop_index(batch_op.f('ix_notification_outbox_group_id'))
        batch_op.drop_index('ix_notification_outbox_due')

    op.drop_table('notification_outbox')
    op.drop_table('group_share_settings')
    with op.batch_alter_table('delegation_accounts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_delegation_accounts_account_id'))

    op.drop_table('delegation_accounts')
    with op.batch_alter_table('user_identities', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_identities_user_id'))

    op.drop_table('user_identities')
    with op.batch_alter_table('telegram_link_codes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_telegram_link_codes_group_id'))

    op.drop_table('telegram_link_codes')
    op.drop_table('group_reactions')
    with op.batch_alter_table('group_members', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_group_members_user_id'))

    op.drop_table('group_members')
    with op.batch_alter_table('group_invites', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_group_invites_group_id'))

    op.drop_table('group_invites')
    with op.batch_alter_table('group_digests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_group_digests_group_id'))

    op.drop_table('group_digests')
    with op.batch_alter_table('group_comments', schema=None) as batch_op:
        batch_op.drop_index('ix_group_comments_target')

    op.drop_table('group_comments')
    op.drop_table('group_channels')
    with op.batch_alter_table('delegations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_delegations_viewer_id'))
        batch_op.drop_index(batch_op.f('ix_delegations_owner_id'))

    op.drop_table('delegations')
    op.drop_table('groups')
