"""Discussion threads: public / group topics, replies, reactions, reports, public posting suspensions

* ``users.public_name`` (the nickname on public posts), ``public_name_key`` (NFKC + casefold, unique) and
  ``public_name_changed_at`` (one change per 7 days).
* ``discussion_topics`` (scope public | group), ``discussion_topic_symbols`` (tagged instruments),
  ``discussion_replies``, ``discussion_reactions``. The author column is ``ON DELETE SET NULL``: deleting an account
  keeps its content.
* ``discussion_reports`` (public content only, one per reporter per target), ``discussion_suspensions`` (public
  posting only) and ``discussion_post_log`` (one row per post, no content: the posting rate limits count these).

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-13 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import forliosa.db

revision: str = '0013'
down_revision: str | None = '0012'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('public_name', sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column('public_name_key', sa.String(length=400), nullable=True))
        batch_op.add_column(sa.Column('public_name_changed_at', forliosa.db.TZDateTime(timezone=True),
                                      nullable=True))
        batch_op.create_index(batch_op.f('ix_users_public_name_key'), ['public_name_key'], unique=True)

    op.create_table('discussion_topics',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('scope', sa.String(length=8), nullable=False),
    sa.Column('group_id', sa.String(length=32), nullable=True),
    sa.Column('user_id', sa.String(length=32), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=8), nullable=False),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('last_activity_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('discussion_topics', schema=None) as batch_op:
        batch_op.create_index('ix_discussion_topics_group_activity', ['group_id', 'last_activity_at', 'id'],
                              unique=False)
        batch_op.create_index('ix_discussion_topics_scope_activity', ['scope', 'last_activity_at', 'id'],
                              unique=False)
        batch_op.create_index('ix_discussion_topics_scope_created', ['scope', 'created_at', 'id'], unique=False)
        batch_op.create_index(batch_op.f('ix_discussion_topics_user_id'), ['user_id'], unique=False)

    op.create_table('discussion_topic_symbols',
    sa.Column('topic_id', sa.String(length=32), nullable=False),
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['topic_id'], ['discussion_topics.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('topic_id', 'symbol')
    )
    with op.batch_alter_table('discussion_topic_symbols', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_discussion_topic_symbols_symbol'), ['symbol'], unique=False)

    op.create_table('discussion_replies',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('topic_id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=8), nullable=False),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['topic_id'], ['discussion_topics.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('discussion_replies', schema=None) as batch_op:
        batch_op.create_index('ix_discussion_replies_topic', ['topic_id', 'created_at', 'id'], unique=False)
        batch_op.create_index(batch_op.f('ix_discussion_replies_user_id'), ['user_id'], unique=False)

    op.create_table('discussion_reactions',
    sa.Column('target_kind', sa.String(length=8), nullable=False),
    sa.Column('target_id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('emoji', sa.String(length=16), nullable=False),
    sa.Column('topic_id', sa.String(length=32), nullable=False),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['topic_id'], ['discussion_topics.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('target_kind', 'target_id', 'user_id', 'emoji')
    )
    with op.batch_alter_table('discussion_reactions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_discussion_reactions_topic_id'), ['topic_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_discussion_reactions_user_id'), ['user_id'], unique=False)

    op.create_table('discussion_reports',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('target_kind', sa.String(length=8), nullable=False),
    sa.Column('target_id', sa.String(length=32), nullable=False),
    sa.Column('topic_id', sa.String(length=32), nullable=False),
    sa.Column('reporter_id', sa.String(length=32), nullable=True),
    sa.Column('reason', sa.String(length=16), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=8), nullable=False),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('resolved_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['reporter_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['topic_id'], ['discussion_topics.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('target_kind', 'target_id', 'reporter_id', name='uq_discussion_report_reporter')
    )
    with op.batch_alter_table('discussion_reports', schema=None) as batch_op:
        batch_op.create_index('ix_discussion_reports_status', ['status', 'created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_discussion_reports_topic_id'), ['topic_id'], unique=False)

    op.create_table('discussion_suspensions',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('until', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_by', sa.String(length=32), nullable=True),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('lifted_at', forliosa.db.TZDateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('discussion_suspensions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_discussion_suspensions_user_id'), ['user_id'], unique=False)

    op.create_table('discussion_post_log',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('scope', sa.String(length=8), nullable=False),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('discussion_post_log', schema=None) as batch_op:
        batch_op.create_index('ix_discussion_post_log_user', ['user_id', 'created_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('discussion_post_log', schema=None) as batch_op:
        batch_op.drop_index('ix_discussion_post_log_user')
    op.drop_table('discussion_post_log')

    with op.batch_alter_table('discussion_suspensions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_discussion_suspensions_user_id'))
    op.drop_table('discussion_suspensions')

    with op.batch_alter_table('discussion_reports', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_discussion_reports_topic_id'))
        batch_op.drop_index('ix_discussion_reports_status')
    op.drop_table('discussion_reports')

    with op.batch_alter_table('discussion_reactions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_discussion_reactions_user_id'))
        batch_op.drop_index(batch_op.f('ix_discussion_reactions_topic_id'))
    op.drop_table('discussion_reactions')

    with op.batch_alter_table('discussion_replies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_discussion_replies_user_id'))
        batch_op.drop_index('ix_discussion_replies_topic')
    op.drop_table('discussion_replies')

    with op.batch_alter_table('discussion_topic_symbols', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_discussion_topic_symbols_symbol'))
    op.drop_table('discussion_topic_symbols')

    with op.batch_alter_table('discussion_topics', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_discussion_topics_user_id'))
        batch_op.drop_index('ix_discussion_topics_scope_created')
        batch_op.drop_index('ix_discussion_topics_scope_activity')
        batch_op.drop_index('ix_discussion_topics_group_activity')
    op.drop_table('discussion_topics')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_public_name_key'))
        batch_op.drop_column('public_name_changed_at')
        batch_op.drop_column('public_name_key')
        batch_op.drop_column('public_name')
