"""The worker's announcements: market-data runs say what they stored (their Core upserts are invisible to the ORM
capture); the jobs that write users' rows (automatic dividends, briefings, digests) are covered by the capture."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from forliosa import closes, us_prices
from forliosa.archive import JobResult
from forliosa.db import session_factory
from forliosa.ids import new_id
from forliosa.models import DatasetStatus, GroupDigest, PriceDaily, Transaction
from forliosa.timeutil import now_utc
from forliosa.worker import Worker
from tests.api.m5 import account, join, login, make_group, me_id

DAY = date(2026, 11, 17)


@pytest.fixture()
def worker(engine, monkeypatch):
    import forliosa.worker as worker_mod

    monkeypatch.setattr(worker_mod, "load_official_calendar", lambda _db: None)
    class Md:
        policy = "commercial"

    w = Worker(md=Md())  # type: ignore[arg-type]

    async def nothing() -> None:
        return None

    monkeypatch.setattr(w, "auto_dividends", nothing)
    monkeypatch.setattr(w, "after_close_refresh", nothing)
    monkeypatch.setattr(w, "briefings_when_closes_are_in", nothing)
    return w


def archive_returns(monkeypatch, results, stores: dict[str, date] | None = None):
    """``Archiver.run`` returns ``results``; ``stores``: the dataset_status rows the run writes (key → session)."""
    import forliosa.worker as worker_mod

    def run(self, groups):
        for key, day in (stores or {}).items():
            row = self.db.get(DatasetStatus, key) or DatasetStatus(key=key)
            row.data_date = day
            self.db.add(row)
        self.db.commit()
        return results

    monkeypatch.setattr(worker_mod.Archiver, "run", run)


def test_an_archive_run_announces_closes_and_the_market_page(worker, monkeypatch, rt):
    archive_returns(monkeypatch, [JobResult("twse prices", 1300), JobResult("tpex prices", 0),
                                  JobResult("twse indices MI_INDEX", 40), JobResult("tpex valuation", 0, "boom")],
                    stores={"twse-openapi/price": DAY})
    asyncio.run(worker.archive(["twse", "tpex"]))
    assert [(e.topic, e.data, e.to) for e in rt.events] == [
        ("market.closes", {"market": "TWSE", "date": "2026-11-17"}, ("all",)), ("market.overview", {}, ("all",))]


def test_writing_the_same_session_again_announces_no_closes(worker, monkeypatch, rt):
    """The scheduled runs (06:45, 08:10, 14:40, 21:40) mostly write the session already stored again: every open page
    would refetch for nothing (2026-11-17 review). Only the market page hears of the run."""
    archive_returns(monkeypatch, [JobResult("twse prices", 1300)], stores={"twse-openapi/price": DAY})
    asyncio.run(worker.archive(["twse"]))
    rt.clear()
    asyncio.run(worker.archive(["twse"]))  # same session again
    assert rt.topics() == ["market.overview"]
    rt.clear()
    # the same session from the other official route (TWSE's same-day file stored it first): not new either
    archive_returns(monkeypatch, [JobResult("twse prices", 1300)], stores={closes.OFFICIAL_KEYS["TWSE"][1]: DAY})
    asyncio.run(worker.archive(["twse"]))
    assert rt.find("market.closes") == []


def test_a_run_that_stored_nothing_is_silent(worker, monkeypatch, rt):
    archive_returns(monkeypatch, [JobResult("twse prices", 0), JobResult("tdcc distribution", 0)])
    asyncio.run(worker.archive(["twse"]))
    archive_returns(monkeypatch, [JobResult("tdcc distribution", 9000)])
    asyncio.run(worker.archive(["tdcc"]))  # stored, but nothing the market page or the ledger shows
    assert rt.events == []


def test_after_close_refresh_announces_only_new_or_changed_closes(engine, monkeypatch, rt):
    import forliosa.worker as worker_mod
    from forliosa.marketdata.base import QuoteData

    monkeypatch.setattr(worker_mod, "refresh_instruments", lambda db, md: 0)
    monkeypatch.setattr(worker_mod, "tracked_symbols", lambda db: ["2330.TW", "AAPL"])
    price = {"2330.TW": 1000.0}

    class Md:
        policy = "commercial"

        def quotes(self, symbols, use_cache=True):
            return {s: QuoteData(symbol=s, price=price.get(s, 10.0), trade_date=DAY, source="test-provider",
                                 is_demo=False) for s in symbols}

    w = Worker(md=Md())  # type: ignore[arg-type]
    asyncio.run(w.after_close_refresh())
    assert rt.topics() == ["market.closes"]
    rt.clear()
    asyncio.run(w.after_close_refresh())  # the same closes again
    assert rt.events == []
    price["2330.TW"] = 1005.0
    asyncio.run(w.after_close_refresh())
    assert rt.topics() == ["market.closes"]
    rt.clear()
    with session_factory()() as db:  # an official row is never overwritten: a different provider close is no change
        row = db.get(PriceDaily, ("2330.TW", DAY))
        row.source = "twse-openapi"
        db.commit()
    price["2330.TW"] = 990.0
    asyncio.run(w.after_close_refresh())
    assert rt.events == []


def test_the_same_day_twse_file(worker, monkeypatch, rt):
    monkeypatch.setattr(closes.TwseSameDay, "poll",
                        lambda self, db: closes.TwsePoll(day=DAY, found=DAY, prices=1200, indices=3))
    monkeypatch.setattr(worker, "twse_fetcher_fn", lambda: None)
    asyncio.run(worker.twse_sameday_close())
    assert [(e.topic, e.data) for e in rt.events] == [("market.closes", {"market": "TWSE", "date": "2026-11-17"}),
                                                      ("market.overview", {})]
    rt.clear()
    monkeypatch.setattr(closes.TwseSameDay, "poll", lambda self, db: closes.TwsePoll(day=DAY, skipped="too-soon"))
    asyncio.run(worker.twse_sameday_close())
    assert rt.events == []


def test_the_evening_interim_closes(worker, monkeypatch, rt):
    class Evening:
        def __init__(self, *a, **kw):
            pass

        def poll(self, db):
            return closes.EveningPoll(day=DAY, stored={"TWSE": 0, "TPEX": 800})

    monkeypatch.setattr(closes, "EveningCloses", Evening)
    monkeypatch.setattr(worker, "fetcher_fn", lambda: None)
    asyncio.run(worker.evening_closes())
    assert [(e.topic, e.data) for e in rt.events] == [("market.closes", {"market": "TPEX", "date": "2026-11-17"})]


def test_us_closes(worker, monkeypatch, rt):
    monkeypatch.setattr(us_prices, "http", lambda: object())
    monkeypatch.setattr(us_prices, "update", lambda db, f, now=None: us_prices.UpdateResult(
        available=DAY, stored=DAY, symbols=12, rows=12))
    asyncio.run(worker.us_closes())
    assert [(e.topic, e.data) for e in rt.events] == [("market.closes", {"market": "US", "date": "2026-11-17"})]
    rt.clear()
    monkeypatch.setattr(us_prices, "update", lambda db, f, now=None: us_prices.UpdateResult(stored=DAY, skipped=True))
    asyncio.run(worker.us_closes())
    assert rt.events == []


def test_rows_the_worker_writes_reach_their_owners_without_an_origin(client, app, rt):
    """Automatic dividends and digests are written by the worker's own sessions: the ORM capture announces them."""
    b = login(app, "b@forliosa.local", "小明")
    a_id, b_id = me_id(client), me_id(b)
    g = make_group(client)
    join(client, b, g["id"])
    acc = account(client)
    rt.clear()
    with session_factory()() as db:
        db.add(Transaction(id=new_id("txn"), user_id=a_id, account_id=acc["id"], symbol="2330.TW",
                           type="cash_dividend", trade_date=DAY, amount=1000, source="auto"))
        d = GroupDigest(id=new_id("gdg"), group_id=g["id"], week_start=date(2026, 11, 9), week_end=date(2026, 11, 13),
                        status="pending", created_at=now_utc())
        db.add(d)
        db.commit()
        d.status = "ready"
        db.commit()
    ledger = rt.one("ledger", account_id=acc["id"])
    assert ledger.to == (f"u:{a_id}",) and ledger.ou is None and ledger.o is None
    assert {a[2:] for a in rt.one("group.ledger").to} == {a_id, b_id}
    reports = rt.find("group.reports", group_id=g["id"])
    assert reports and all({a[2:] for a in e.to} == {a_id, b_id} for e in reports)
