"""AI daily limit counts questions in their own table; wider ai_usage.stop_reason

``ai_questions``: one row per question a user asks (``cost`` = how many of the daily limit it counts as). The daily
limit used to count the user's rows in ``ai_messages``, which go with the conversation, so deleting conversations
gave the day's questions back. Rows hold no content and are purged with the AI retention window. Questions asked
before this revision are not copied over: the count starts afresh on the day it is deployed.

``ai_usage.stop_reason`` grows from 24 to 40 characters: the model API's ``model_context_window_exceeded`` (30)
did not fit on PostgreSQL. SQLite does not enforce the length, so only PostgreSQL alters the column.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-14 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import forliosa.db

revision: str = '0019'
down_revision: str | None = '0018'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('ai_questions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('cost', sa.Integer(), nullable=False),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ai_questions_user_created', 'ai_questions', ['user_id', 'created_at'], unique=False)
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column('ai_usage', 'stop_reason', existing_type=sa.String(length=24), type_=sa.String(length=40),
                        existing_nullable=True)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("UPDATE ai_usage SET stop_reason = left(stop_reason, 24) WHERE length(stop_reason) > 24")
        op.alter_column('ai_usage', 'stop_reason', existing_type=sa.String(length=40), type_=sa.String(length=24),
                        existing_nullable=True)
    op.drop_index('ix_ai_questions_user_created', table_name='ai_questions')
    op.drop_table('ai_questions')
