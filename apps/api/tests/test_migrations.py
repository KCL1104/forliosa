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


def test_group_passes_grandfather_existing_groups_and_keep_rows_both_ways(tmp_path):
    """0023 (群組加值包): every group that exists at the upgrade keeps 50 members (``grandfathered_member_cap``);
    groups, members and channels survive the round trip (plain ALTER TABLE, no batch copy of ``groups``)."""
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'passes.db'}"
    command.upgrade(_config(url), "0022")
    engine = make_engine(url)
    try:
        with engine.begin() as conn:
            _insert(conn, "users", {"id": "usr_1", "email": "a@b.c"})
            _insert(conn, "groups", {"id": "grp_old", "name": "大學同學"})
            _insert(conn, "group_members", {"group_id": "grp_old", "user_id": "usr_1", "role": "owner"})
            _insert(conn, "group_channels", {"group_id": "grp_old", "kind": "discord", "status": "active"})
        command.upgrade(_config(url), "0023")
        with engine.begin() as conn:
            assert conn.execute(text("SELECT grandfathered_member_cap FROM groups")).scalar_one() == 50
            assert conn.execute(text("SELECT notify_daily FROM group_channels")).scalar_one() in (0, False)
            _insert(conn, "groups", {"id": "grp_new", "name": "新群組"})  # made after the change: no 50
            assert conn.execute(text("SELECT grandfathered_member_cap FROM groups WHERE id = 'grp_new'")).scalar_one() \
                is None
        assert {"group_passes", "group_daily_reports"} <= set(inspect(engine).get_table_names())
        command.downgrade(_config(url), "0022")
        inspector = inspect(engine)
        assert "grandfathered_member_cap" not in {c["name"] for c in inspector.get_columns("groups")}
        assert "group_passes" not in inspector.get_table_names()
        with engine.begin() as conn:
            assert sorted(conn.execute(text("SELECT id FROM groups")).scalars().all()) == ["grp_new", "grp_old"]
            assert conn.execute(text("SELECT user_id FROM group_members")).scalars().all() == ["usr_1"]
            assert conn.execute(text("SELECT kind FROM group_channels")).scalars().all() == ["discord"]
    finally:
        engine.dispose()


def test_news_tags_tables_and_url_key_index_both_ways(tmp_path):
    """0024_news_tags (新聞標籤, 2026-11-17): ``news_tags`` (queryable by kind and value) and ``news_tag_state``, plus
    an index on ``news_articles.url_key`` (plain CREATE INDEX: stored headlines survive both ways)."""
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'tags.db'}"
    command.upgrade(_config(url), "0023")
    engine = make_engine(url)
    try:
        with engine.begin() as conn:
            _insert(conn, "news_articles", {"symbol": "2330.TW", "url_key": "k1", "url": "https://x.tw/1",
                                            "title": "台積電新聞", "outlet": "X", "domain": "x.tw", "source": "gdelt"})
        command.upgrade(_config(url), "0024_news_tags")
        inspector = inspect(engine)
        assert {"news_tags", "news_tag_state"} <= set(inspector.get_table_names())
        assert "ix_news_tags_kind_value" in {i["name"] for i in inspector.get_indexes("news_tags")}
        assert "ix_news_articles_url_key" in {i["name"] for i in inspector.get_indexes("news_articles")}
        assert "batch_limit" in {c["name"] for c in inspector.get_columns("news_tag_state")}
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO news_tags (url_key, kind, value) VALUES ('k1', 'theme', 'ai_server')"))
            _insert(conn, "news_tag_state", {"url_key": "k1", "status": "done"})
            assert tuple(conn.execute(text(
                "SELECT attempts, taxonomy_version, batch_limit FROM news_tag_state")).one()) == (0, 0, None)
            assert conn.execute(text(
                "SELECT a.title FROM news_tags t JOIN news_articles a ON a.url_key = t.url_key "
                "WHERE t.kind = 'theme' AND t.value = 'ai_server'")).scalars().all() == ["台積電新聞"]
        command.downgrade(_config(url), "0023")
        inspector = inspect(engine)
        assert not {"news_tags", "news_tag_state"} & set(inspector.get_table_names())
        assert "ix_news_articles_url_key" not in {i["name"] for i in inspector.get_indexes("news_articles")}
        with engine.begin() as conn:
            assert conn.execute(text("SELECT title FROM news_articles")).scalars().all() == ["台積電新聞"]
    finally:
        engine.dispose()


def test_market_reports_tables_and_columns_both_ways(tmp_path):
    """0024_market_reports (市場報告, 2026-11-17): the report tables, the three hand-kept tables and FMTQIK's table
    appear; existing channels get the weekly push on and the daily ones off; prices keep their rows; the downgrade
    removes the
    tables and columns again (plain ALTER TABLE, no batch copy)."""
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'reports.db'}"
    command.upgrade(_config(url), "0023")
    engine = make_engine(url)
    new_tables = {"market_reports", "market_report_versions", "market_report_gathers", "market_report_runs",
                  "market_report_votes", "market_report_config", "market_report_reads", "nyse_holidays",
                  "macro_calendar", "us_earnings", "market_turnover_daily"}
    try:
        with engine.begin() as conn:
            _insert(conn, "users", {"id": "usr_1", "email": "a@b.c"})
            _insert(conn, "groups", {"id": "grp_1", "name": "大學同學"})
            _insert(conn, "group_channels", {"group_id": "grp_1", "kind": "discord", "status": "active"})
            _insert(conn, "prices_daily", {"symbol": "2330.TW", "date": "2026-11-16", "close": "1430",
                                           "source": "twse-openapi"})
        command.upgrade(_config(url), "0024_market_reports")
        inspector = inspect(engine)
        assert new_tables <= set(inspector.get_table_names())
        assert "value" in {c["name"] for c in inspector.get_columns("prices_daily")}
        assert "market_report_id" in {c["name"] for c in inspector.get_columns("notification_outbox")}
        with engine.begin() as conn:
            row = conn.execute(text("SELECT notify_premarket, notify_close, notify_weekly FROM group_channels")).one()
            assert [bool(v) for v in row] == [False, False, True]
            assert conn.execute(text("SELECT value FROM prices_daily")).scalar_one() is None
        command.downgrade(_config(url), "0023")
        inspector = inspect(engine)
        assert not new_tables & set(inspector.get_table_names())
        assert "value" not in {c["name"] for c in inspector.get_columns("prices_daily")}
        assert not {"notify_premarket", "notify_close", "notify_weekly"} & {
            c["name"] for c in inspector.get_columns("group_channels")}
        with engine.begin() as conn:
            assert conn.execute(text("SELECT kind FROM group_channels")).scalars().all() == ["discord"]
            assert conn.execute(text("SELECT symbol FROM prices_daily")).scalars().all() == ["2330.TW"]
    finally:
        engine.dispose()


def test_market_report_key_state_both_ways(tmp_path):
    """0025_mreport_key_state (市場報告審查, 2026-11-17): the config row keeps its mode and writers, gets an empty
    ``key_state`` (the worker writes it), and loses it again on the downgrade."""
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'key_state.db'}"
    command.upgrade(_config(url), "0024_market_reports")
    engine = make_engine(url)
    try:
        with engine.begin() as conn:
            _insert(conn, "market_report_config", {"id": 1, "mode": "trial", "writers": "{}"})
        command.upgrade(_config(url), "0025_mreport_key_state")
        assert "key_state" in {c["name"] for c in inspect(engine).get_columns("market_report_config")}
        with engine.begin() as conn:
            assert conn.execute(text("SELECT mode, key_state FROM market_report_config")).one() == ("trial", None)
        command.downgrade(_config(url), "0024_market_reports")
        assert "key_state" not in {c["name"] for c in inspect(engine).get_columns("market_report_config")}
        with engine.begin() as conn:
            assert conn.execute(text("SELECT mode FROM market_report_config")).scalar_one() == "trial"
    finally:
        engine.dispose()


def test_market_events_type_date_index_both_ways(tmp_path):
    """0026_mevents_type_date (API 速度, 2026-11-17): the (type, date) index the market page's 重大訊息 reads by, gone
    again on the downgrade; the model declares the same index."""
    url = f"sqlite:///{tmp_path / 'mevents.db'}"
    command.upgrade(_config(url), "0026_mevents_type_date")
    engine = make_engine(url)
    try:
        indexes = {i["name"]: i["column_names"] for i in inspect(engine).get_indexes("market_events")}
        assert indexes["ix_market_events_type_date"] == ["type", "date"]
        declared = {i.name: [c.name for c in i.columns] for i in Base.metadata.tables["market_events"].indexes}
        assert declared["ix_market_events_type_date"] == ["type", "date"]
        command.downgrade(_config(url), "0025_mreport_key_state")
        assert "ix_market_events_type_date" not in {i["name"] for i in inspect(engine).get_indexes("market_events")}
    finally:
        engine.dispose()
