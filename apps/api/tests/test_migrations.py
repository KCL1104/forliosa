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


def _insert(conn, table: str, values: dict) -> None:
    """Insert a row at whatever revision the database is at: required columns not given get a plain value."""
    from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, Numeric, text

    row = dict(values)
    for col in inspect(conn).get_columns(table):
        if col["name"] in row or col["nullable"] or col.get("default") is not None or col.get("autoincrement") is True:
            continue
        plain = ((Boolean, False), (Integer, 0), (Numeric, 0), (DateTime, "2026-01-05 00:00:00"), (Date, "2026-01-05"),
                 (JSON, "{}"))
        row[col["name"]] = next((v for kind, v in plain if isinstance(col["type"], kind)), "x")
    names = ", ".join(row)
    conn.execute(text(f"INSERT INTO {table} ({names}) VALUES ({', '.join(':' + n for n in row)})"), row)


def test_import_batch_column_keeps_every_row_both_ways(tmp_path):
    """0021 adds ``transactions.import_batch_id`` (indexed) and drops it again with plain ALTER TABLE: no batch copy
    of ``transactions``, so its rows survive the round trip."""
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'batches.db'}"
    command.upgrade(_config(url), "0020")
    engine = make_engine(url)
    try:
        with engine.begin() as conn:
            _insert(conn, "users", {"id": "usr_1", "email": "a@b.c"})
            _insert(conn, "broker_accounts", {"id": "acc_1", "user_id": "usr_1"})
            _insert(conn, "transactions", {"id": "txn_1", "user_id": "usr_1", "account_id": "acc_1", "type": "buy"})
        command.upgrade(_config(url), "0021")
        inspector = inspect(engine)
        assert "import_batch_id" in {c["name"] for c in inspector.get_columns("transactions")}
        assert "ix_transactions_import_batch_id" in {i["name"] for i in inspector.get_indexes("transactions")}
        with engine.begin() as conn:
            assert conn.execute(text("SELECT import_batch_id FROM transactions")).scalar_one() is None
        command.downgrade(_config(url), "0020")
        inspector = inspect(engine)
        assert "import_batch_id" not in {c["name"] for c in inspector.get_columns("transactions")}
        assert "ix_transactions_import_batch_id" not in {i["name"] for i in inspector.get_indexes("transactions")}
        with engine.begin() as conn:
            assert conn.execute(text("SELECT id FROM transactions")).scalars().all() == ["txn_1"]
            assert conn.execute(text("SELECT id FROM broker_accounts")).scalars().all() == ["acc_1"]
    finally:
        engine.dispose()
