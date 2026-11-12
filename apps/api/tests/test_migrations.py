"""The Alembic history is a single line: one head, and every migration upgrades and downgrades on SQLite.

Two branches that each add a migration on the same parent (e.g. ``0008_sec_edgar`` and ``0009_ai_analyst_views``,
both after ``0007``) merge into two heads, and ``alembic upgrade head`` then fails with "Multiple head revisions".
``test_single_head`` makes that fail loudly after the merge: relink the later migration's ``down_revision`` to the
other head (and its ``Revises:`` docstring line), or add a merge revision.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from forliosa.db import Base, make_engine

API_ROOT = Path(__file__).resolve().parents[1]


def _config(url: str | None = None) -> Config:
    # No ini file: alembic/env.py would otherwise reconfigure logging for the rest of the test session.
    cfg = Config()
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    if url:
        cfg.attributes["database_url"] = url
    return cfg


def test_single_head():
    heads = ScriptDirectory.from_config(_config()).get_heads()
    assert len(heads) == 1, (
        f"Alembic has {len(heads)} heads ({', '.join(sorted(heads))}): relink the later migration's down_revision "
        "to the other head, or add a merge revision")


def test_upgrade_creates_every_table_and_downgrade_removes_them(tmp_path):
    url = f"sqlite:///{tmp_path / 'migrations.db'}"
    command.upgrade(_config(url), "head")
    engine = make_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert set(Base.metadata.tables) <= tables  # every model has its migration
        command.downgrade(_config(url), "base")
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) <= {"alembic_version"}
    finally:
        engine.dispose()
