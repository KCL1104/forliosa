"""Shared research behind 「X 今天為什麼漲／跌」 chat answers

``ai_why_research`` (``forliosa.ai.research``, 產品負責人 2026-11-16): one row per symbol, trading session and phase
(``intraday`` / ``after_close``) holding the market-level facts and the cited sources of a why-answer, so the next
asker of the same stock and day gets an answer from it instead of searching again. No user column: nothing personal is
stored. Rows past ``expires_at`` are simply not used and are deleted a few days later.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-16 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import forliosa.db

revision: str = '0022'
down_revision: str | None = '0021'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('ai_why_research',
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('session', sa.Date(), nullable=False),
    sa.Column('phase', sa.String(length=12), nullable=False),
    sa.Column('market', sa.String(length=8), nullable=False),
    sa.Column('facts', sa.JSON(), nullable=True),
    sa.Column('sources', sa.JSON(), nullable=False),
    sa.Column('one_liner', sa.Text(), nullable=True),
    sa.Column('close_in', sa.Boolean(), nullable=False),
    sa.Column('searches', sa.Integer(), nullable=False),
    sa.Column('hits', sa.Integer(), nullable=False),
    sa.Column('created_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('updated_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.Column('expires_at', forliosa.db.TZDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('symbol', 'session', 'phase')
    )
    op.create_index('ix_ai_why_research_expires', 'ai_why_research', ['expires_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_ai_why_research_expires', table_name='ai_why_research')
    op.drop_table('ai_why_research')
