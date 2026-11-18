"""Realtime × batch 4 (2026-11-17 merge): the write paths that came with batch 4 announce what the realtime branch's
paths announce, a market report reaches its readers, and the speed work's pools and caches get along with the
streams.

* 刪除這檔 / 清除所有持倉 / 匯入庫存「以券商為準」 delete with one bulk ``DELETE`` (``services.transactions.
  delete_records``), which the ORM capture does not see: the same ``ledger`` / ``group.ledger`` / ``ledger.viewas``
  as a row-by-row delete, with the feed rule of a trades-only member; a dry run announces nothing.
* Market reports: a public edition reaches every signed-in user, an admin-only one the site admins (the blind test and
  its events were removed on 2026-11-18).
* Silent by design: LangSearch's news rows (no news source announces anything), the Yahoo reference close (a read).
* Pools: N open streams leave every request-pool and archive-pool connection free (5 + 10 each, the speed work's
  sizes); the slow-request log does not count open realtime streams as requests in flight (other streams it does);
  a resync of every open tab followed by every tab refetching its ledger page at once is served without a pool
  timeout, and so is a burst of 500 simultaneous requests — far more than anyio's 40 threadpool tokens plus the 15
  connections, the condition under which the two waited for each other until the pool timed out (review of the
  merge: a request held its connection between the sign-in dependency, the endpoint and the response's validation;
  ``forliosa.db.release_connection``, ``tests/test_db_release.py``).
* Caches: a close the worker stores is in the very next read after its ``market.closes`` (the 30-second quote cache
  would hide it otherwise); the speed work's caches are keyed on the archive's version or do not hold closes.
"""

from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import event as sa_event
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa import perf, realtime
from forliosa.config import get_settings
from forliosa.db import ARCHIVE_MAX_OVERFLOW, ARCHIVE_POOL_SIZE, archive_session_factory, session_factory
from forliosa.ids import new_id
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import DatasetStatus, GroupDailyReport, NewsArticle, PriceDaily
from forliosa.reports import pipeline
from forliosa.timeutil import now_utc, today_taipei
from tests.api.m5 import API, SHARE_ALL, SHARE_NONE, account, join, login, make_group, me_id, set_share, trade
from tests.realtime.test_events_endpoint import Stream, browser, server  # noqa: F401 - the uvicorn fixture
from tests.test_api_speed import DAYS, TW, _bars


def users_of(ev) -> set[str]:
    return {a[2:] for a in ev.to if a.startswith("u:")}


@pytest.fixture()
def b(app):
    return login(app, "b@forliosa.local", "小明")


def _plan(client, account_id: str, symbol: str = "0050.TW") -> None:
    r = client.post(f"{API}/recurring", json={"account_id": account_id, "symbol": symbol, "amount": 5000,
                                              "day_of_month": [6]})
    assert r.status_code == 201, r.text


# -- the bulk deletes ---------------------------------------------------------------------------------------------
def test_deleting_a_holding_reaches_my_devices_the_group_and_my_viewers(client, b, rt):
    """刪除這檔 (a bulk delete since batch 4): B's devices, the group B shares with, A who views B's account."""
    a_id, b_id = me_id(client), me_id(b)
    g = make_group(client)
    join(client, b, g["id"], share=SHARE_ALL)
    acc, other = account(b, "B 一"), account(b, "B 二")
    r = b.post(f"{API}/delegations", json={"viewer_user_id": a_id, "scope": "accounts", "account_ids": [acc["id"]]})
    assert r.status_code == 201, r.text
    trade(b, acc["id"], "2330.TW", "buy", today_taipei() - timedelta(days=1), 1000, 600)
    trade(b, other["id"], "2330.TW", "buy", today_taipei() - timedelta(days=1), 1000, 600)
    rt.clear()
    r = b.delete(f"{API}/accounts/{acc['id']}/holdings/2330.TW", headers={"X-Forliosa-Tab": "t_btab12345"})
    assert r.status_code == 200, r.text
    ledger = rt.one("ledger")
    assert ledger.data == {"account_id": acc["id"]} and users_of(ledger) == {b_id} and ledger.o == "t_btab12345"
    assert users_of(rt.one("group.ledger", group_id=g["id"])) == {a_id, b_id}
    assert users_of(rt.one("ledger.viewas")) == {a_id}
    rt.clear()  # the other account is outside the delegation's scope: no ledger.viewas
    assert b.delete(f"{API}/accounts/{other['id']}/holdings/2330.TW").status_code == 200
    assert rt.one("ledger").data == {"account_id": other["id"]} and not rt.find("ledger.viewas")


def test_clearing_follows_the_feed_rule_of_a_trades_only_member(client, b, rt):
    """A member who shares only trades: the group hears of 清除所有持倉 only if a trade the feed showed went."""
    a_id, b_id = me_id(client), me_id(b)
    g = make_group(client)
    join(client, b, g["id"], share=SHARE_NONE)
    set_share(b, g["id"], trades=True)
    acc = account(b)
    trade(b, acc["id"], "2330.TW", "buy", date(2025, 3, 4), 1000, 600)  # older than the feed window
    rt.clear()
    assert b.delete(f"{API}/portfolio/records", params={"account_id": acc["id"]}).status_code == 200
    assert rt.one("ledger").data == {"account_id": acc["id"]} and not rt.find("group.ledger")
    trade(b, acc["id"], "2330.TW", "buy", today_taipei() - timedelta(days=1), 1000, 600)  # the feed shows it
    rt.clear()
    assert b.delete(f"{API}/portfolio/records", params={"account_id": acc["id"]}).status_code == 200
    assert users_of(rt.one("group.ledger", group_id=g["id"])) == {a_id, b_id}


def test_nothing_to_clear_still_announces_the_paused_plans(client, rt):
    acc = account(client)
    _plan(client, acc["id"])
    rt.clear()
    r = client.delete(f"{API}/portfolio/records", params={"all_accounts": "true", "pause_plans": "true"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "no_records"
    assert rt.topics() == ["recurring"]


def test_a_positions_dry_run_announces_nothing(client, rt):
    acc = account(client)
    trade(client, acc["id"], "2330.TW", "buy", date(2025, 3, 4), 1000, 600)
    rt.clear()
    r = client.post(f"{API}/imports/positions/commit", json={
        "account_id": acc["id"], "dry_run": True, "rows": [{"symbol": "2330", "quantity": 2000, "price": 590,
                                                             "replace": True}]})
    assert r.status_code == 200 and r.json()["replaced"][0]["deleted"] == 1, r.text
    assert rt.events == []  # the replace's bulk delete was rolled back, its events with it


def test_a_statement_import_and_its_undo(client, rt):
    """匯入對帳單 writes through the batch route (ORM rows): one ledger event per account, the undo likewise."""
    acc = account(client)
    rows = [{"symbol": s, "type": "buy", "trade_date": "2025-03-04", "quantity": 1000, "price": 100}
            for s in ("2330", "2317", "0050")]
    rt.clear()
    r = client.post(f"{API}/transactions/batch", json={"account_id": acc["id"], "origin": "import",
                                                         "dry_run": False, "rows": rows})
    assert r.status_code == 201, r.text
    assert [e.data for e in rt.find("ledger")] == [{"account_id": acc["id"]}]
    rt.clear()
    assert client.delete(f"{API}/transactions/batches/{r.json()['batch_id']}").status_code in (200, 204)
    assert [e.data for e in rt.find("ledger")] == [{"account_id": acc["id"]}]


# -- market reports: one public edition (the blind test was removed on 2026-11-18) -------------------------------
def test_a_public_edition_reaches_everyone_and_an_admin_only_one_the_admins(client, app, monkeypatch, rt):
    from tests.reports.conftest import seed_market

    monkeypatch.setattr(get_settings(), "market_reports_enabled", True)
    with session_factory()() as db:
        seed_market(db)
        from forliosa.models import MarketReport

        for kind, visibility in (("close", "public"), ("premarket", "admin")):
            ed = pipeline.edition_on(kind, date(2026, 11, 16))
            r = pipeline.make_report(db, ed, now_utc(), visibility=visibility)
            rt.clear()
            v = pipeline.new_version(db, r, edition="ai", payload={"title": "x"}, now=now_utc())
            r = db.get(MarketReport, r.id)
            r.current_version_id, r.state, r.first_published_at = v.id, "ai", now_utc()
            db.commit()
            ev = rt.one("market.reports")
            assert ev.to == (("all",) if visibility == "public" else ("admins",))
            assert ev.data == {"report_id": r.id, "kind": kind}


# -- silent by design ---------------------------------------------------------------------------------------------
def test_langsearch_news_rows_announce_nothing(engine, market, rt):
    """LangSearch's ingestion stores headlines like every other news source: no realtime event (stock pages read news
    on their own schedule; contract 「即時更新」)."""
    from tests.news.test_langsearch import FakeLangSearch, answer, page, run, view

    md = MarketData([DemoProvider()], policy="commercial")
    set_market_data(md)
    try:
        settings = get_settings().model_copy(update={
            "news_enabled": True, "news_langsearch_enabled": True, "news_ai_enabled": False,
            "langsearch_api_key": SecretStr("sk-ls-test-9f3a7c21e0"), "news_langsearch_topics": []})
        fake = FakeLangSearch(answer(
            page("台積電法說會 營收創高 外資喊買", "https://money.udn.com/money/story/5612/9", "2026-11-17T05:10:00Z")))
        with Session(engine) as db:
            view(db, "2330.TW")
            rt.clear()
            rep = run(db, md, settings, fake)
            assert rep.stored == 1 and db.scalars(select(NewsArticle)).all()
    finally:
        set_market_data(market)
    assert rt.events == []


def test_the_reference_close_is_a_read(client, rt):
    rt.clear()
    r = client.get(f"{API}/instruments/2330/close", params={"date": (today_taipei() - timedelta(days=400)).isoformat()})
    assert r.status_code == 200, r.text
    assert rt.events == []


def test_group_daily_reports_reach_the_members(client, b, rt):
    g = make_group(client)
    join(client, b, g["id"])
    with session_factory()() as db:
        rep = GroupDailyReport(id=new_id("gdr"), group_id=g["id"], trading_day=today_taipei(), status="pending")
        db.add(rep)
        db.commit()
        rt.clear()
        rep.status, rep.summary, rep.finished_at = "ready", "今天…", now_utc()
        db.commit()
    assert users_of(rt.one("group.reports", group_id=g["id"])) == {me_id(client), me_id(b)}


# -- the speed work's pools ---------------------------------------------------------------------------------------
def _pools(engine):
    archive = archive_session_factory().kw["bind"]
    assert archive is not engine and archive.url == engine.url
    return engine.pool, archive.pool


def test_open_streams_leave_every_pooled_connection_free(server, engine):  # noqa: F811
    """20 open streams (more than either pool's 5 + 10): no connection of the request pool or the archive's pool is
    held, all 15 of the request pool can be taken at once, and requests are served while the streams stay open."""
    main, arch = _pools(engine)
    assert (main.size(), main._max_overflow) == (5, 10)  # SQLAlchemy's default, the API's request pool
    assert (arch.size(), arch._max_overflow) == (ARCHIVE_POOL_SIZE, ARCHIVE_MAX_OVERFLOW) == (5, 10)
    users = [browser(server, f"u{i}@forliosa.local", f"使用者{i}") for i in range(4)]
    streams = [Stream(server, u.token) for u in users for _ in range(5)]  # 5 per user: under the cap of 6
    try:
        for s in streams:
            s.next("hello")
        time.sleep(0.2)
        assert main.checkedout() == 0 and arch.checkedout() == 0
        assert perf.inflight() == 0  # the slow-request log does not count open streams as requests in flight
        timeout, main._timeout = main._timeout, 2.0
        try:
            held = [engine.connect() for _ in range(main.size() + main._max_overflow)]
            for c in held:
                c.exec_driver_sql("SELECT 1")
            for c in held:
                c.close()
        finally:
            main._timeout = timeout
        with ThreadPoolExecutor(15) as ex:
            codes = list(ex.map(lambda u: u.get(f"{API}/portfolio/summary").status_code, users * 4))
        assert codes == [200] * 16
        acc = users[0].post(f"{API}/accounts", json={"name": "新", "currency": "TWD"}).json()
        assert streams[0].next("ledger", timeout=2.0)["data"]["account_id"] == acc["id"]  # still live
    finally:
        for s in streams:
            s.close()


LEDGER_PAGE = ["/me", "/portfolio/summary", "/portfolio/holdings", "/portfolio/performance?range=1M",
               "/portfolio/upcoming?days=7", "/portfolio/upcoming?days=7&types=recurring", "/transactions/counts",
               "/accounts", "/watchlist", "/meta/market-status", "/market/reports/status", "/groups", "/delegations"]


@pytest.fixture()
def archived(engine, market, monkeypatch):
    """The commercial facade reading a small archive through the archive's own pool (as in production)."""
    monkeypatch.setenv("US_PRICE_SOURCE", "databento")
    get_settings.cache_clear()
    with Session(engine) as db:
        for n, s in enumerate(TW):
            db.add_all(_bars(s, DAYS, "tpex-openapi" if s.endswith(".TWO") else "twse-openapi", 50 + 40 * n))
        for key in ("twse-openapi/price", "tpex-openapi/price"):
            db.add(DatasetStatus(key=key, data_date=DAYS[-1], rows=1, fetched_at=datetime.now(UTC)))
        db.commit()
    md = MarketData([ArchiveProvider("commercial", us_prices=True), DemoProvider()], policy="commercial")
    set_market_data(md)
    yield md
    set_market_data(market)
    get_settings.cache_clear()


def test_a_resync_storm_is_served_without_a_pool_timeout(server, engine, archived, app, caplog):  # noqa: F811
    """Every open tab is told to refetch (a deploy, a LISTEN reconnect) and refetches its whole ledger page; the
    browsers spread it over 0–3 s (``RESYNC_SPREAD_MS``), here every tab fires all its requests at once inside that
    window. The request pool (5 + 10, pool timeout lowered to 10 s to make a wait visible) and the archive's pool
    serve all of it: no error, no pool timeout, no request near the timeout."""
    main, arch = _pools(engine)
    users = [browser(server, f"s{i}@forliosa.local", f"使用者{i}") for i in range(4)]
    for u in users:
        acc = u.post(f"{API}/accounts", json={"name": "永豐", "currency": "TWD"}).json()["id"]
        rows = [{"symbol": s, "type": "buy", "trade_date": DAYS[2].isoformat(), "quantity": 10, "price": 50}
                for s in TW]
        assert u.post(f"{API}/transactions/batch", json={"account_id": acc, "dry_run": False, "rows": rows}) \
            .status_code == 201
        u.post(f"{API}/watchlist", json={"symbol": "2330"})
    tabs = [(u, Stream(server, u.token)) for u in users for _ in range(3)]  # 12 tabs
    peak = {"main": 0, "archive": 0}
    lock = threading.Lock()

    def watch(pool_name, pool):
        def on_checkout(*_a):
            with lock:
                peak[pool_name] = max(peak[pool_name], pool.checkedout())
        return on_checkout

    hooks = [(main, watch("main", main)), (arch, watch("archive", arch))]
    for pool, fn in hooks:
        sa_event.listen(pool, "checkout", fn)
    timeout, main._timeout = main._timeout, 10.0
    rnd = random.Random(7)
    try:
        for _u, s in tabs:
            s.next("hello")
        hub = app.state.realtime_hub
        hub.loop.call_soon_threadsafe(hub.resync_all)

        def tab(i: int) -> list[tuple[int, float]]:
            u, s = tabs[i]
            s.next("resync", timeout=5.0)
            time.sleep(rnd.random() * 3.0)
            with httpx.Client(base_url=server, cookies={"forliosa_session": u.token}, timeout=30) as c, \
                    ThreadPoolExecutor(len(LEDGER_PAGE)) as ex:
                def get(path):
                    t = time.monotonic()
                    return c.get(f"{API}{path}").status_code, time.monotonic() - t
                return list(ex.map(get, LEDGER_PAGE))

        started = time.monotonic()
        with caplog.at_level(logging.WARNING), ThreadPoolExecutor(len(tabs)) as ex:
            results = [r for rs in ex.map(tab, range(len(tabs))) for r in rs]
        elapsed = time.monotonic() - started
    finally:
        main._timeout = timeout
        for pool, fn in hooks:
            sa_event.remove(pool, "checkout", fn)
        for _u, s in tabs:
            s.close()
    codes = [c for c, _ in results]
    slowest = max(t for _, t in results)
    print(f"resync storm: {len(results)} requests from {len(tabs)} tabs in {elapsed:.1f} s, slowest {slowest:.2f} s, "
          f"peak pooled connections request {peak['main']}/15 archive {peak['archive']}/15")
    assert codes == [200] * len(tabs) * len(LEDGER_PAGE), sorted(set(codes))
    assert slowest < 10.0  # nobody waited for the pool timeout
    assert not [r for r in caplog.records if "no free database connection" in r.getMessage()
                or "QueuePool limit" in r.getMessage()]


def _tokens(app) -> int:
    """anyio's threadpool tokens in the server's event loop (sync dependencies, endpoints and response validation)."""
    async def read() -> int:
        import anyio.to_thread

        return int(anyio.to_thread.current_default_thread_limiter().total_tokens)

    return asyncio.run_coroutine_threadsafe(read(), app.state.realtime_hub.loop).result(5)


BURST_PATHS = ["/accounts", "/me", "/portfolio/summary", "/watchlist", "/transactions/counts"]


def test_a_burst_beyond_threadpool_tokens_plus_connections_is_served(server, engine, app, caplog):  # noqa: F811
    """500 sync requests at the same moment: far more than anyio's 40 tokens plus the request pool's 15 connections.
    Before the fix, a request kept its pooled connection while it waited for a token between its threadpool calls
    (sign-in dependency → endpoint → response validation), so the 40 tokens went to requests waiting for a connection
    and the 15 connections to requests waiting for a token: every such burst ended in 500 ``QueuePool limit … timed
    out`` (4 of 4 runs at 240 requests; with the sign-in dependencies fixed alone, 3 of 5 runs at 500). Now each
    threadpool call gives the connection back before it returns: all 200, nobody near the (lowered) pool timeout."""
    main = engine.pool
    assert _tokens(app) == 40 and (main.size(), main._max_overflow) == (5, 10)
    users = [browser(server, f"burst{i}@forliosa.local", f"使用者{i}") for i in range(4)]
    for u in users:
        assert u.post(f"{API}/accounts", json={"name": "永豐", "currency": "TWD"}).status_code == 201
    n = 500
    barrier = threading.Barrier(n)

    def one(i: int) -> tuple[int | str, float]:
        u = users[i % len(users)]
        with httpx.Client(base_url=server, cookies={"forliosa_session": u.token}, timeout=60) as c:
            barrier.wait()
            t = time.monotonic()
            try:
                return c.get(f"{API}{BURST_PATHS[i % len(BURST_PATHS)]}").status_code, time.monotonic() - t
            except httpx.HTTPError as exc:
                return type(exc).__name__, time.monotonic() - t

    timeout, main._timeout = main._timeout, 8.0
    try:
        started = time.monotonic()
        with caplog.at_level(logging.WARNING), ThreadPoolExecutor(n) as ex:
            results = list(ex.map(one, range(n)))
        elapsed = time.monotonic() - started
    finally:
        main._timeout = timeout
    codes = [c for c, _ in results]
    slowest = max(t for _, t in results)
    print(f"burst: {n} simultaneous requests in {elapsed:.1f} s, slowest {slowest:.2f} s")
    assert codes == [200] * n, sorted(set(map(str, codes)))
    assert slowest < 8.0
    assert not [r for r in caplog.records if "QueuePool limit" in r.getMessage()]
    assert main.checkedout() == 0


def test_only_the_realtime_stream_leaves_the_in_flight_count():
    """The slow-request log's ``inflight``: an open ``/events`` stream stops counting once its headers are sent; an
    AI chat or a quote stream is real work (a threadpool thread, Claude calls, writes) and counts until it ends."""
    from types import SimpleNamespace

    async def scenario(route: str) -> tuple[int, int]:
        streaming, finish = asyncio.Event(), asyncio.Event()

        async def endpoint(scope, receive, send):
            scope["route"] = SimpleNamespace(path=route)  # what the router puts in the scope
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"text/event-stream; charset=utf-8")]})
            await send({"type": "http.response.body", "body": b"data: x\n\n", "more_body": True})
            streaming.set()
            await finish.wait()
            await send({"type": "http.response.body", "body": b"", "more_body": False})

        async def receive():
            await asyncio.sleep(3600)

        async def send(_message):
            return None

        mw = perf.SlowRequestMiddleware(endpoint, threshold_ms=1e9, prefix="/api/v1")
        before = perf.inflight()
        task = asyncio.create_task(mw({"type": "http", "method": "GET", "path": f"/api/v1{route}"}, receive, send))
        await streaming.wait()
        during = perf.inflight() - before
        finish.set()
        await task
        return during, perf.inflight() - before

    assert asyncio.run(scenario("/events")) == (0, 0)
    assert asyncio.run(scenario("/ai/chat")) == (1, 0)
    assert asyncio.run(scenario("/stream/quotes")) == (1, 0)


# -- the speed work's caches --------------------------------------------------------------------------------------
def test_a_stored_close_is_in_the_next_read_after_its_event(server, engine, archived, app):  # noqa: F811
    """The worker stores a newer close and announces it: the API's 30-second quote cache (which would hide it: shown
    first) is dropped when the event arrives, so the browser's refetch right after it sees the close. The speed
    work's caches do not hold closes: the archive's start only moves with an older close, the related-stocks pool and
    the admin counts are keyed on the archive's version or are not read by a ledger page."""
    a = browser(server, "demo@forliosa.local", "示範使用者")
    acc = a.post(f"{API}/accounts", json={"name": "永豐", "currency": "TWD"}).json()["id"]
    assert a.post(f"{API}/transactions", json={"account_id": acc, "symbol": "2330.TW", "type": "buy",
                                               "trade_date": DAYS[2].isoformat(), "quantity": 1000,
                                               "price": 50}).status_code == 201
    before = a.get(f"{API}/portfolio/summary").json()["market_value"]
    since = archived.archive_since()  # the archive's start: cached for an hour (the speed work)
    assert since == DAYS[0]
    new_day = DAYS[-1] + timedelta(days=1)
    with session_factory()() as db:  # the worker's write (its own session, no request)
        db.add(PriceDaily(symbol="2330.TW", date=new_day, open=D(999), high=D(999), low=D(999), close=D(999),
                          volume=1, source="twse-openapi"))
        row = db.get(DatasetStatus, "twse-openapi/price")
        row.data_date, row.fetched_at = new_day, datetime.now(UTC)
        db.commit()
    assert a.get(f"{API}/portfolio/summary").json()["market_value"] == before  # the quote cache: still the old close
    stream = Stream(server, a.token)
    try:
        stream.next("hello")
        t0 = time.monotonic()
        realtime.notify_now(realtime.event("market.closes", {"market": "TWSE", "date": new_day.isoformat()},
                                           (realtime.ALL,)))
        stream.next("market.closes", timeout=2.0, live=True)
        fresh = a.get(f"{API}/portfolio/summary").json()["market_value"]
        took = time.monotonic() - t0
    finally:
        stream.close()
    assert fresh == pytest.approx(999 * 1000) and took < 2.0, (fresh, took)
    quote = a.get(f"{API}/instruments/2330/quote").json()
    assert quote["price"] == pytest.approx(999) and quote["trade_date"] == new_day.isoformat()
    assert archived.archive_since() == since  # a newer close does not move the start: the cache is right to keep it
