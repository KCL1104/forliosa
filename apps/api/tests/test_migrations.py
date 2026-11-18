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


def test_mreport_trial_audience_both_ways(tmp_path):
    """0026_mreport_trial_audience (盲測開給所有人, 2026-11-17): the config row gets an empty ``trial_audience``; every
    vote so far was an admin's; a blind-test edition already written gets ``ai_published_at`` from its first variant
    version (one with no variant yet, a public one and one already set are left alone); the downgrade drops the two
    columns again."""
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'trial_audience.db'}"
    command.upgrade(_config(url), "0025_mreport_key_state")
    engine = make_engine(url)
    try:
        with engine.begin() as conn:
            _insert(conn, "users", {"id": "usr_1", "email": "a@b.c"})
            _insert(conn, "market_report_config", {"id": 1, "mode": "trial", "writers": "{}"})
            for rid, d, trial, ai in (("mrp_t", "2026-11-16", True, None), ("mrp_w", "2026-11-17", True, None),
                                      ("mrp_p", "2026-11-18", False, None),
                                      ("mrp_s", "2026-11-19", True, "2026-11-19 07:58:00")):
                _insert(conn, "market_reports", {"id": rid, "kind": "close", "edition_date": d, "trial": trial,
                                                 "ai_published_at": ai})
            for vid, rid, n, variant, at in (("mrv_1", "mrp_t", 1, None, "2026-11-16 06:11:00"),
                                             ("mrv_2", "mrp_t", 2, "B", "2026-11-16 07:52:00"),
                                             ("mrv_3", "mrp_t", 3, "A", "2026-11-16 07:55:00"),
                                             ("mrv_4", "mrp_w", 1, None, "2026-11-17 06:11:00"),
                                             ("mrv_5", "mrp_p", 1, None, "2026-11-18 06:11:00"),
                                             ("mrv_6", "mrp_p", 2, "A", "2026-11-18 07:50:00"),
                                             ("mrv_7", "mrp_s", 1, "A", "2026-11-19 07:50:00")):
                _insert(conn, "market_report_versions", {"id": vid, "report_id": rid, "version": n,
                                                         "variant": variant, "created_at": at})
            _insert(conn, "market_report_votes", {"report_id": "mrp_t", "user_id": "usr_1", "preferred": "A"})
        command.upgrade(_config(url), "0026_mreport_trial_audience")
        with engine.begin() as conn:
            assert conn.execute(text("SELECT mode, trial_audience FROM market_report_config")).one() == ("trial", None)
            assert [bool(v) for v in conn.execute(text("SELECT by_admin FROM market_report_votes")).scalars()] == [True]
            got = dict(conn.execute(text("SELECT id, ai_published_at FROM market_reports")).all())
            assert {k: (str(v)[:19] if v else None) for k, v in got.items()} == {
                "mrp_t": "2026-11-16 07:52:00", "mrp_w": None, "mrp_p": None, "mrp_s": "2026-11-19 07:58:00"}
        command.downgrade(_config(url), "0025_mreport_key_state")
        assert "trial_audience" not in {c["name"] for c in inspect(engine).get_columns("market_report_config")}
        assert "by_admin" not in {c["name"] for c in inspect(engine).get_columns("market_report_votes")}
        with engine.begin() as conn:
            assert conn.execute(text("SELECT preferred FROM market_report_votes")).scalar_one() == "A"
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
        command.downgrade(_config(url), "0026_mreport_trial_audience")
        assert "ix_market_events_type_date" not in {i["name"] for i in inspect(engine).get_indexes("market_events")}
    finally:
        engine.dispose()


def test_channel_four_switches_keep_every_opt_in_both_ways(tmp_path):
    """0027_channel_four_switches (頻道只留四個開關, 2026-11-18): ``notify_premarket := notify_premarket OR
    notify_daily`` and ``notify_weekly := notify_weekly OR notify_digest`` for every mix of old values; the old
    columns stay as they were (deprecated, no longer read). The downgrade keeps every row and changes nothing that
    was not touched; a 週報 / 盤前 turned off after the upgrade lowers the old column (old AND new), so the old code
    does not send the group digest / daily report there again — and nothing is ever turned on."""
    from itertools import product

    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'switches.db'}"
    command.upgrade(_config(url), "0026_mevents_type_date")
    engine = make_engine(url)
    cols = ("notify_premarket", "notify_daily", "notify_weekly", "notify_digest")
    mixes = list(product((False, True), repeat=4))  # every combination of the four old values
    try:
        with engine.begin() as conn:
            _insert(conn, "users", {"id": "usr_1", "email": "a@b.c"})
            for i, values in enumerate(mixes):
                _insert(conn, "groups", {"id": f"grp_{i}", "name": f"群組 {i}"})
                for kind in ("discord", "telegram"):
                    _insert(conn, "group_channels", {"group_id": f"grp_{i}", "kind": kind, "status": "active",
                                                     "notify_trades": True, "notify_close": i % 2 == 0,
                                                     **dict(zip(cols, values, strict=True))})
        command.upgrade(_config(url), "0027_channel_four_switches")
        select_all = f"SELECT group_id, kind, notify_close, {', '.join(cols)} FROM group_channels"
        with engine.begin() as conn:
            got = {(r[0], r[1]): tuple(bool(v) for v in r[2:]) for r in conn.execute(text(select_all))}
        assert len(got) == 2 * len(mixes)
        for i, (pre, daily, weekly, digest) in enumerate(mixes):
            for kind in ("discord", "telegram"):
                assert got[(f"grp_{i}", kind)] == (i % 2 == 0, pre or daily, daily, weekly or digest, digest)
        command.downgrade(_config(url), "0026_mevents_type_date")
        assert set(cols) <= {c["name"] for c in inspect(engine).get_columns("group_channels")}
        with engine.begin() as conn:
            after = {(r[0], r[1]): tuple(bool(v) for v in r[2:]) for r in conn.execute(text(select_all))}
        assert after == got  # untouched rows: the merged switches and the old columns stay as they are
        command.upgrade(_config(url), "head")  # and up again
        with engine.begin() as conn:
            again = {(r[0], r[1]): tuple(bool(v) for v in r[2:]) for r in conn.execute(text(select_all))}
        assert again == got
        # after the upgrade the owner turns 週報 off on every discord channel and 盤前 off on every telegram one
        with engine.begin() as conn:
            conn.execute(text("UPDATE group_channels SET notify_weekly = :f WHERE kind = 'discord'"), {"f": False})
            conn.execute(text("UPDATE group_channels SET notify_premarket = :f WHERE kind = 'telegram'"), {"f": False})
        command.downgrade(_config(url), "0026_mevents_type_date")
        with engine.begin() as conn:
            low = {(r[0], r[1]): tuple(bool(v) for v in r[2:]) for r in conn.execute(text(select_all))}
        assert len(low) == 2 * len(mixes)
        for i, (pre, daily, weekly, digest) in enumerate(mixes):
            close = i % 2 == 0
            # discord: 週報 off → notify_digest off; 盤前 (merged) and notify_daily as they were
            assert low[(f"grp_{i}", "discord")] == (close, pre or daily, daily, False, False)
            # telegram: 盤前 off → notify_daily off; 週報 (merged) and notify_digest as they were
            assert low[(f"grp_{i}", "telegram")] == (close, False, False, weekly or digest, digest)
    finally:
        engine.dispose()


def test_remove_blind_test_makes_every_blind_test_edition_public_both_ways(tmp_path):
    """0028_remove_blind_test (產品負責人 2026-11-18: 「盲測的部分就直接拔掉吧」): the mode ``trial`` becomes
    ``public``; every blind-test edition becomes a normal public one whose current version is the variant written
    with the default writer (Opus 5.5 at high), else A, else the alphabetically first label (each its newest
    version), made a plain version (``variant`` null); ``state = ai`` and ``ai_published_at`` from that version. An
    edition still open (not pushed, not closed) takes only the default writer's variant, else keeps its data edition
    (the normal pipeline writes it); an edition whose current is already a plain AI version keeps it. An edition with
    no variant keeps its data edition; a normal edition is untouched; votes, runs and the other variants stay. The
    downgrade changes no data; a second upgrade finds nothing left to do; ``paused`` stays paused."""
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'remove_trial.db'}"
    command.upgrade(_config(url), "0027_channel_four_switches")
    engine = make_engine(url)
    opus_high, opus_med, sonnet = ('{"model": "claude-opus-5-5", "effort": "high", "tier": "normal"}',
                                   '{"model": "claude-opus-5-5", "effort": "medium", "tier": "normal"}',
                                   '{"model": "claude-sonnet-5-5", "effort": "high", "tier": "normal"}')
    try:
        with engine.begin() as conn:
            _insert(conn, "users", {"id": "usr_1", "email": "a@b.c"})
            _insert(conn, "market_report_config", {"id": 1, "mode": "trial", "writers": "{}"})
            # (id, kind, date, trial, visibility, state, current, pushed, closed): pushed or closed = a past edition
            for rid, kind, d, trial, vis, state, cur, pushed, closed in (
                    ("mrp_pre", "premarket", "2026-11-18", True, "admin", "data", "mrv_p1", True, False),  # takes B
                    ("mrp_cl17", "close", "2026-11-17", True, "admin", "data", "mrv_c5", True, True),  # no opus high: A
                    ("mrp_cl18", "close", "2026-11-18", True, "admin", "data", "mrv_d1", False, False),  # open, none
                    ("mrp_bc", "premarket", "2026-11-17", True, "admin", "data", "mrv_e1", False, True),  # B and C: B
                    ("mrp_pub", "close", "2026-11-16", False, "public", "ai", "mrv_f2", True, True),  # a normal one
                    # still open (a late deploy): only the default writer's variant is taken, else the data edition
                    ("mrp_open", "close", "2026-11-19", True, "admin", "data", "mrv_g1", False, False),  # A, C: data
                    ("mrp_openb", "close", "2026-11-20", True, "admin", "data", "mrv_h1", False, False),  # B: opus high
                    # a worker on the new code wrote a live version before the api migrated: it stays current
                    ("mrp_live", "close", "2026-11-23", True, "admin", "ai", "mrv_i3", False, False)):
                _insert(conn, "market_reports", {"id": rid, "kind": kind, "edition_date": d, "period_start": d,
                                                 "period_end": d, "trial": trial, "visibility": vis, "state": state,
                                                 "current_version_id": cur, "first_published_at": f"{d} 06:55:00",
                                                 "ai_published_at": f"{d} 07:40:00" if trial else None,
                                                 "pushed_at": f"{d} 07:45:00" if pushed else None,
                                                 "push_edition": ("trial" if trial else "ai") if pushed else None,
                                                 "closed_at": f"{d} 21:00:00" if closed else None,
                                                 "notes": "[]"})
            for vid, rid, n, variant, edition, writer, at in (
                    ("mrv_p1", "mrp_pre", 1, None, "data", None, "2026-11-18 06:55:00"),
                    ("mrv_p2", "mrp_pre", 2, "A", "ai", sonnet, "2026-11-18 07:10:00"),
                    ("mrv_p3", "mrp_pre", 3, "B", "ai", opus_high, "2026-11-18 07:22:00"),
                    ("mrv_p4", "mrp_pre", 4, "C", "ai", opus_med, "2026-11-18 07:15:00"),
                    ("mrv_c1", "mrp_cl17", 1, None, "data", None, "2026-11-17 14:10:00"),
                    ("mrv_c2", "mrp_cl17", 2, "A", "ai", sonnet, "2026-11-17 15:58:00"),
                    ("mrv_c3", "mrp_cl17", 3, "C", "ai", opus_med, "2026-11-17 16:01:00"),
                    ("mrv_c4", "mrp_cl17", 4, "A", "ai", sonnet, "2026-11-17 16:20:00"),  # A again: the newest
                    ("mrv_c5", "mrp_cl17", 5, None, "tables", None, "2026-11-17 23:45:00"),
                    ("mrv_d1", "mrp_cl18", 1, None, "data", None, "2026-11-18 14:10:00"),
                    ("mrv_e1", "mrp_bc", 1, None, "data", None, "2026-11-17 06:55:00"),
                    ("mrv_e2", "mrp_bc", 2, "C", "ai", opus_med, "2026-11-17 07:12:00"),
                    ("mrv_e3", "mrp_bc", 3, "B", "ai", sonnet, "2026-11-17 07:14:00"),
                    ("mrv_f1", "mrp_pub", 1, None, "data", None, "2026-11-16 14:10:00"),
                    ("mrv_f2", "mrp_pub", 2, None, "ai", opus_high, "2026-11-16 15:55:00"),
                    ("mrv_g1", "mrp_open", 1, None, "data", None, "2026-11-19 14:10:00"),
                    ("mrv_g2", "mrp_open", 2, "A", "ai", sonnet, "2026-11-19 15:47:00"),
                    ("mrv_g3", "mrp_open", 3, "C", "ai", opus_med, "2026-11-19 15:49:00"),
                    ("mrv_h1", "mrp_openb", 1, None, "data", None, "2026-11-20 14:10:00"),
                    ("mrv_h2", "mrp_openb", 2, "A", "ai", sonnet, "2026-11-20 15:47:00"),
                    ("mrv_h3", "mrp_openb", 3, "B", "ai", opus_high, "2026-11-20 15:51:00"),
                    ("mrv_i1", "mrp_live", 1, None, "data", None, "2026-11-23 14:10:00"),
                    ("mrv_i2", "mrp_live", 2, "B", "ai", opus_high, "2026-11-23 15:50:00"),
                    ("mrv_i3", "mrp_live", 3, None, "ai", opus_high, "2026-11-23 15:56:00")):
                _insert(conn, "market_report_versions", {"id": vid, "report_id": rid, "version": n, "variant": variant,
                                                         "edition": edition, "writer": writer, "payload": "{}",
                                                         "validation": "{}", "created_at": at})
            _insert(conn, "market_report_votes", {"report_id": "mrp_pre", "user_id": "usr_1", "preferred": "A"})
            _insert(conn, "market_report_runs", {"id": "mrr_p3", "report_id": "mrp_pre", "variant": "B",
                                                 "purpose": "trial", "writer": opus_high, "calls": "[]",
                                                 "metrics": "{}"})
        cols = ("id", "trial", "visibility", "state", "current_version_id", "ai_published_at", "pushed_at",
                "push_edition")
        select_reports = f"SELECT {', '.join(cols)} FROM market_reports ORDER BY id"

        def reports(conn) -> dict[str, tuple]:
            return {r[0]: (bool(r[1]), r[2], r[3], r[4], str(r[5])[:19] if r[5] else None, r[6] is not None, r[7])
                    for r in conn.execute(text(select_reports))}

        def labels(conn) -> dict[str, str | None]:
            return dict(conn.execute(text("SELECT id, variant FROM market_report_versions")).all())

        command.upgrade(_config(url), "0028_remove_blind_test")
        with engine.begin() as conn:
            assert conn.execute(text("SELECT mode FROM market_report_config")).scalar_one() == "public"
            got = reports(conn)
            assert got == {
                "mrp_pre": (False, "public", "ai", "mrv_p3", "2026-11-18 07:22:00", True, "trial"),
                "mrp_cl17": (False, "public", "ai", "mrv_c4", "2026-11-17 16:20:00", True, "trial"),
                "mrp_cl18": (False, "public", "data", "mrv_d1", "2026-11-18 07:40:00", False, None),
                "mrp_bc": (False, "public", "ai", "mrv_e3", "2026-11-17 07:14:00", False, None),
                "mrp_pub": (False, "public", "ai", "mrv_f2", None, True, "ai"),
                "mrp_open": (False, "public", "data", "mrv_g1", "2026-11-19 07:40:00", False, None),
                "mrp_openb": (False, "public", "ai", "mrv_h3", "2026-11-20 15:51:00", False, None),
                "mrp_live": (False, "public", "ai", "mrv_i3", "2026-11-23 07:40:00", False, None)}
            vs = labels(conn)
            assert all(vs[v] is None for v in ("mrv_p3", "mrv_c4", "mrv_e3", "mrv_h3", "mrv_i3"))  # kept: plain
            assert (vs["mrv_p2"], vs["mrv_p4"], vs["mrv_c2"], vs["mrv_c3"], vs["mrv_e2"]) == ("A", "C", "A", "C", "C")
            assert (vs["mrv_g2"], vs["mrv_g3"], vs["mrv_h2"], vs["mrv_i2"]) == ("A", "C", "A", "B")  # not taken
            assert conn.execute(text("SELECT preferred FROM market_report_votes")).scalar_one() == "A"
            assert conn.execute(text("SELECT variant, purpose FROM market_report_runs")).one() == ("B", "trial")
        command.downgrade(_config(url), "0027_channel_four_switches")
        with engine.begin() as conn:
            assert reports(conn) == got and labels(conn) == vs  # no data change
            assert conn.execute(text("SELECT mode FROM market_report_config")).scalar_one() == "public"
            conn.execute(text("UPDATE market_report_config SET mode = 'paused'"))
        command.upgrade(_config(url), "head")
        with engine.begin() as conn:
            assert reports(conn) == got and labels(conn) == vs  # nothing left to do
            assert conn.execute(text("SELECT mode FROM market_report_config")).scalar_one() == "paused"
    finally:
        engine.dispose()
