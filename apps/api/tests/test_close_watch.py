"""The worker's close watch: from 13:35 on a trading day until 08:30 the next morning it asks every 15 minutes
whether the exchanges' close datasets have turned to that day, and archives each market once when they have.

Fake clock (the worker's ``now_fn``) and fake HTTP (httpx.MockTransport behind the real HttpFetcher): the two close
datasets are files that are replaced at a set time, served the way the real hosts serve them (ETag, 304, byte ranges).
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal as D

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.archive import (
    CLOSE_DATASETS,
    CLOSE_WATCH_SECONDS,
    ClosePublication,
    close_archived,
    close_watch_day,
    first_data_date,
)
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.http import HttpFetcher, RateLimiter
from forliosa.marketdata.service import MarketData
from forliosa.models import DatasetStatus, MarketHoliday, PriceDaily, User, WatchlistItem
from forliosa.services.instruments import quote_out
from forliosa.timeutil import TAIPEI, is_tw_trading_day, last_tw_trading_day, market_close_dt, today_taipei
from forliosa.worker import Worker

# The trading day being watched and the one before it — recent ones, so the archive's quote window covers them.
DAY = last_tw_trading_day(today_taipei() - timedelta(days=1))
PREVIOUS = last_tw_trading_day(DAY - timedelta(days=1))
NEXT = DAY + timedelta(days=1)
PATHS = {"/v1/exchangeReport/STOCK_DAY_ALL": "TWSE", "/openapi/v1/tpex_mainboard_daily_close_quotes": "TPEX"}
CLOSES = {PREVIOUS: {"2330.TW": "2390.00", "6488.TWO": "445.00"}, DAY: {"2330.TW": "2400.00", "6488.TWO": "450.00"}}


def at(day: date, hh: int, mm: int) -> datetime:
    return datetime.combine(day, time(hh, mm), TAIPEI)


def roc(d: date) -> str:
    return f"{d.year - 1911}{d.month:02d}{d.day:02d}"


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self) -> datetime:
        return self.t


class Exchanges:
    """The two OpenAPI hosts. Each close dataset carries ``PREVIOUS`` until its publication time, then ``DAY``."""

    def __init__(self, clock: Clock, twse: datetime | None, tpex: datetime | None, conditional: bool = True,
                 ranges: bool = True):
        self.clock = clock
        self.published = {"TWSE": twse, "TPEX": tpex}
        self.conditional, self.ranges = conditional, ranges
        self.broken_downloads: set[str] = set()  # markets whose full download fails (the probe still works)
        self.requests: list[tuple[datetime, str, str]] = []  # (when, market, 304 | 206 | 200 | full | failed)
        self.other: list[str] = []  # every other path asked for

    def day_of(self, market: str) -> date:
        when = self.published[market]
        return DAY if when is not None and self.clock.t >= when else PREVIOUS

    def body(self, market: str) -> bytes:
        d = self.day_of(market)
        if market == "TWSE":
            rows = [{"Date": roc(d), "Code": "2330", "Name": "台積電", "TradeVolume": "30000000",
                     "TradeValue": "72000000000", "OpeningPrice": "2385.00", "HighestPrice": "2410.00",
                     "LowestPrice": "2380.00", "ClosingPrice": CLOSES[d]["2330.TW"], "Change": "10.0000",
                     "Transaction": "50000"}]
        else:
            rows = [{"Date": roc(d), "SecuritiesCompanyCode": "6488", "CompanyName": "環球晶",
                     "Close": CLOSES[d]["6488.TWO"], "Change": "+5.00", "Open": "444.00", "High": "452.00",
                     "Low": "443.00", "Average": "448.00", "TradingShares": "1000000",
                     "TransactionAmount": "448000000", "TransactionNumber": "900", "NextReferencePrice": "450.00",
                     "NextLimitUp": "495.00", "NextLimitDown": "405.00"}]
        return json.dumps([*rows, {"padding": "x" * 3000}], ensure_ascii=False, separators=(",", ":")).encode()

    def handler(self, request: httpx.Request) -> httpx.Response:
        market = PATHS.get(request.url.path)
        if market is None:
            self.other.append(request.url.path)
            return httpx.Response(404)
        etag = f'"{market}-{self.day_of(market).isoformat()}"'
        headers = {"ETag": etag, "Last-Modified": f"version of {self.day_of(market).isoformat()}"}

        def answer(kind: str, response: httpx.Response) -> httpx.Response:
            self.requests.append((self.clock.t, market, kind))
            return response

        if self.conditional and request.headers.get("If-None-Match") == etag:
            return answer("304", httpx.Response(304, headers=headers))
        body = self.body(market)
        if "Range" in request.headers:
            if self.ranges:
                last = int(request.headers["Range"].removeprefix("bytes=0-"))
                return answer("206", httpx.Response(206, content=body[:last + 1], headers=headers))
            return answer("200", httpx.Response(200, content=body, headers=headers))
        if market in self.broken_downloads:
            return answer("failed", httpx.Response(503))
        return answer("full", httpx.Response(200, content=body, headers=headers))

    def fetcher(self) -> HttpFetcher:
        client = httpx.Client(transport=httpx.MockTransport(self.handler))
        return HttpFetcher(client=client, limiter=RateLimiter(), retries=0)

    def kinds(self, market: str) -> list[str]:
        return [kind for _when, m, kind in self.requests if m == market]

    def times(self, market: str, kind: str | None = None) -> list[datetime]:
        return [when for when, m, k in self.requests if m == market and (kind is None or k == kind)]


@pytest.fixture()
def md(engine) -> MarketData:
    """Commercial mode: quotes come from the archive only (the demo provider just names instruments)."""
    return MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine)), DemoProvider()],
                      policy="commercial")


@pytest.fixture()
def watched(engine):
    """Someone watches both stocks, so ``after_close_refresh`` has closes to store."""
    with Session(engine) as db:
        db.add(User(id="usr_watch", email="watch@forliosa.local", display_name="看盤的人", preferences={}))
        db.flush()
        db.add_all([WatchlistItem(id="wl_1", user_id="usr_watch", symbol="2330.TW"),
                    WatchlistItem(id="wl_2", user_id="usr_watch", symbol="6488.TWO")])
        db.commit()


class Scenario:
    def __init__(self, md: MarketData, twse: datetime | None, tpex: datetime | None, **exchange):
        self.clock = Clock(at(DAY, 8, 10))
        self.exchanges = Exchanges(self.clock, twse, tpex, **exchange)
        self.md = md
        self.archive_runs: list[tuple[datetime, tuple[str, ...]]] = []
        self.refreshes: list[datetime] = []
        self.worker = self.start_worker()

    def start_worker(self) -> Worker:
        """A new worker process: nothing in memory, the same database."""
        worker = Worker(md=self.md, now_fn=self.clock, fetcher_fn=self.exchanges.fetcher)
        archive, refresh = worker.archive, worker.after_close_refresh

        async def counted_archive(groups: list[str]) -> None:
            self.archive_runs.append((self.clock.t, tuple(groups)))
            await archive(groups)

        async def counted_refresh() -> None:
            self.refreshes.append(self.clock.t)
            await refresh()

        worker.archive, worker.after_close_refresh = counted_archive, counted_refresh  # type: ignore[method-assign]
        self.worker = worker
        return worker

    def morning_archive(self) -> None:
        """The 08:10 run of the watched day: the previous day's closes are stored."""
        asyncio.run(self.worker.archive(["twse", "tpex"]))
        self.archive_runs.clear()
        self.exchanges.requests.clear()

    def run(self, start: datetime, end: datetime) -> None:
        """What the scheduler loop does between ``start`` and ``end`` for the close watch (one look a minute)."""
        job = next(j for j in self.worker.jobs if j.name == "close_watch")

        async def loop() -> None:
            t = start
            while t <= end:
                self.clock.t = t
                if job.due(t, job.last_run):
                    job.last_run = t
                    await job.run()
                t += timedelta(minutes=1)

        asyncio.run(loop())

    def stored(self, engine) -> dict[str, D]:
        with Session(engine) as db:
            return {r.symbol: r.close for r in db.scalars(select(PriceDaily).where(PriceDaily.date == DAY))}

    def status(self, engine) -> dict[str, date | None]:
        with Session(engine) as db:
            rows = db.scalars(select(DatasetStatus).where(DatasetStatus.key.like("%/price")))
            return {row.key: row.data_date for row in rows}


def ticks(start: datetime, end: datetime) -> list[datetime]:
    out, t = [], start
    while t <= end:
        out.append(t)
        t += timedelta(seconds=CLOSE_WATCH_SECONDS)
    return out


# -- the window ---------------------------------------------------------------------------------------------------
def test_the_watch_runs_from_1335_on_a_trading_day_until_0830_the_next_morning():
    assert is_tw_trading_day(DAY)
    assert close_watch_day(at(DAY, 13, 34)) is None and close_watch_day(at(DAY, 9, 0)) is None
    assert close_watch_day(at(DAY, 13, 35)) == DAY and close_watch_day(at(DAY, 23, 59)) == DAY
    assert close_watch_day(at(NEXT, 0, 0)) == DAY and close_watch_day(at(NEXT, 8, 29)) == DAY
    assert close_watch_day(at(NEXT, 8, 30)) is None and close_watch_day(at(NEXT, 12, 0)) is None
    # a weekend: nothing on Saturday afternoon or Sunday, Friday's watch ends on Saturday 08:30
    friday = date(2026, 11, 13)
    assert close_watch_day(at(friday, 22, 0)) == friday == close_watch_day(at(date(2026, 11, 14), 5, 0))
    for when in (at(date(2026, 11, 14), 8, 30), at(date(2026, 11, 14), 14, 0), at(date(2026, 11, 15), 3, 0),
                 at(date(2026, 11, 15), 20, 0), at(date(2026, 11, 16), 8, 0)):
        assert close_watch_day(when) is None, when
    assert close_watch_day(at(date(2026, 11, 16), 13, 35)) == date(2026, 11, 16)
    # a holiday in the built-in calendar (2026-10-09, a Friday): not that afternoon, not the next morning
    assert close_watch_day(at(date(2026, 10, 9), 15, 0)) is None
    assert close_watch_day(at(date(2026, 10, 10), 6, 0)) is None
    assert close_watch_day(at(date(2026, 10, 9), 6, 0)) == date(2026, 10, 8)  # Thursday's watch is still running
    # the clock may be in any zone
    assert close_watch_day(at(DAY, 13, 35).astimezone(tz=None)) == DAY


def test_first_data_date_reads_the_first_row():
    assert first_data_date(b'[\n{"Date":"1151113","Code":"00400A","Name":"..."') == date(2026, 11, 13)
    assert first_data_date(b'[{"Date": "20261113", "SecuritiesCompanyCode": "00411A"') == date(2026, 11, 13)
    assert first_data_date(b'[{"Code":"2330"}]') is None and first_data_date(b"") is None
    assert first_data_date(b'[{"Date":"not a date"}]') is None


# -- publication ---------------------------------------------------------------------------------------------------
def test_published_at_2230_is_archived_once_at_the_next_check(engine, md, watched):
    s = Scenario(md, twse=at(DAY, 22, 30), tpex=at(DAY, 22, 30))
    s.morning_archive()
    before = md.quotes(["2330.TW", "6488.TWO"], use_cache=False)
    assert before["2330.TW"].trade_date == PREVIOUS and before["2330.TW"].price == D("2390")
    s.run(at(DAY, 9, 0), at(NEXT, 13, 0))

    checks = ticks(at(DAY, 13, 35), at(DAY, 22, 35))  # every 15 minutes from 13:35; found at 22:35
    for market in ("TWSE", "TPEX"):
        # the first look reads the first kilobyte, every later one is a 304 until the file is replaced
        assert s.exchanges.kinds(market) == ["206", *["304"] * (len(checks) - 2), "206", "full"], market
        assert s.exchanges.times(market) == [*checks, at(DAY, 22, 35)]  # … and nothing afterwards
    assert s.archive_runs == [(at(DAY, 22, 35), ("twse",)), (at(DAY, 22, 35), ("tpex",))]  # once per market
    assert s.refreshes == [at(DAY, 22, 35)]
    assert s.stored(engine) == {"2330.TW": D("2400"), "6488.TWO": D("450")}
    assert s.status(engine) == {"twse-openapi/price": DAY, "tpex-openapi/price": DAY}
    # quotes now carry the day's close, stamped with that day's close time, never real-time
    after = md.quotes(["2330.TW", "6488.TWO"], use_cache=False)
    for symbol, price, previous in (("2330.TW", "2400", "2390"), ("6488.TWO", "450", "445")):
        q = after[symbol]
        assert (q.price, q.prev_close, q.trade_date) == (D(price), D(previous), DAY)
        assert q.as_of == market_close_dt(DAY) and q.is_realtime is False
        out = quote_out(q)
        assert out["as_of"] == f"{DAY.isoformat()}T13:30:00+08:00" and out["is_realtime"] is False


def test_published_at_0400_the_next_morning(engine, md, watched):
    s = Scenario(md, twse=at(NEXT, 4, 0), tpex=at(NEXT, 4, 0))
    s.morning_archive()
    s.run(at(DAY, 13, 0), at(NEXT, 13, 0))
    checks = ticks(at(DAY, 13, 35), at(NEXT, 4, 5))
    assert checks[-1] == at(NEXT, 4, 5)
    for market in ("TWSE", "TPEX"):
        assert s.exchanges.kinds(market) == ["206", *["304"] * (len(checks) - 2), "206", "full"]
        assert s.exchanges.times(market)[-1] == at(NEXT, 4, 5)
    assert s.archive_runs == [(at(NEXT, 4, 5), ("twse",)), (at(NEXT, 4, 5), ("tpex",))]
    assert s.stored(engine) == {"2330.TW": D("2400"), "6488.TWO": D("450")}


def test_never_published_stops_at_0830_without_downloading_anything(engine, md, watched):
    s = Scenario(md, twse=None, tpex=None)
    s.morning_archive()
    s.run(at(DAY, 13, 0), at(NEXT, 13, 30))
    checks = ticks(at(DAY, 13, 35), at(NEXT, 8, 29))
    assert (checks[0], checks[-1], len(checks)) == (at(DAY, 13, 35), at(NEXT, 8, 20), 76)
    for market in ("TWSE", "TPEX"):
        assert s.exchanges.times(market) == checks
        assert s.exchanges.kinds(market) == ["206", *["304"] * 75]  # 75 empty answers, one kilobyte, no download
    assert s.archive_runs == [] and s.refreshes == [] and s.stored(engine) == {}
    assert s.status(engine) == {"twse-openapi/price": PREVIOUS, "tpex-openapi/price": PREVIOUS}


def test_one_market_early_the_other_late(engine, md, watched):
    s = Scenario(md, twse=at(NEXT, 5, 20), tpex=at(DAY, 23, 30))
    s.morning_archive()
    s.run(at(DAY, 13, 0), at(NEXT, 13, 0))
    assert s.archive_runs == [(at(DAY, 23, 35), ("tpex",)), (at(NEXT, 5, 20), ("twse",))]
    assert s.refreshes == [at(DAY, 23, 35), at(NEXT, 5, 20)]
    # TPEx is not asked again once its day is in; TWSE goes on until its own
    assert s.exchanges.times("TPEX")[-1] == at(DAY, 23, 35) and s.exchanges.kinds("TPEX").count("full") == 1
    assert s.exchanges.times("TWSE") == [*ticks(at(DAY, 13, 35), at(NEXT, 5, 20)), at(NEXT, 5, 20)]
    assert s.exchanges.kinds("TWSE").count("full") == 1
    assert s.stored(engine) == {"2330.TW": D("2400"), "6488.TWO": D("450")}
    with Session(engine) as db:  # between the two, only TPEx was in
        tpex, twse = (next(d for d in CLOSE_DATASETS if d.market == m) for m in ("TPEX", "TWSE"))
        assert close_archived(db, tpex, DAY) and close_archived(db, twse, DAY)
        assert not close_archived(db, tpex, NEXT)


def test_restart_in_between_neither_repeats_nor_forgets(engine, md, watched):
    s = Scenario(md, twse=at(NEXT, 4, 0), tpex=at(DAY, 23, 30))
    s.morning_archive()
    s.run(at(DAY, 13, 0), at(DAY, 23, 40))
    assert s.archive_runs == [(at(DAY, 23, 35), ("tpex",))]
    seen_before = len(s.exchanges.requests)

    s.start_worker()  # the worker is redeployed at 23:50: nothing in memory
    s.run(at(DAY, 23, 50), at(NEXT, 13, 0))
    after = s.exchanges.requests[seen_before:]
    assert [m for _when, m, _kind in after if m == "TPEX"] == []  # stored data says TPEx is done
    twse = [(when, kind) for when, m, kind in after if m == "TWSE"]
    assert twse[0] == (at(DAY, 23, 50), "206")  # no validators in memory: the first kilobyte again, not a download
    assert [kind for _when, kind in twse[1:-2]] == ["304"] * (len(twse) - 3)
    assert twse[-2:] == [(at(NEXT, 4, 5), "206"), (at(NEXT, 4, 5), "full")]
    assert s.archive_runs == [(at(DAY, 23, 35), ("tpex",)), (at(NEXT, 4, 5), ("twse",))]

    s.start_worker()  # and once more after everything is in: nothing left to do
    seen_before = len(s.exchanges.requests)
    s.run(at(NEXT, 4, 10), at(NEXT, 13, 0))
    assert len(s.exchanges.requests) == seen_before and len(s.archive_runs) == 2


def test_a_failed_archive_run_is_tried_again_at_the_next_check(engine, md, watched):
    s = Scenario(md, twse=at(DAY, 22, 30), tpex=None)
    s.morning_archive()
    s.exchanges.broken_downloads.add("TWSE")
    s.run(at(DAY, 22, 20), at(DAY, 22, 40))
    assert s.exchanges.kinds("TWSE") == ["206", "206", "failed"] and s.stored(engine) == {}
    s.run(at(DAY, 22, 41), at(DAY, 22, 55))  # 22:50: the file is unchanged (304) and still not stored
    assert s.exchanges.kinds("TWSE") == ["206", "206", "failed", "304", "failed"]
    s.exchanges.broken_downloads.clear()
    s.run(at(DAY, 22, 56), at(NEXT, 9, 0))
    assert s.exchanges.kinds("TWSE") == ["206", "206", "failed", "304", "failed", "304", "full"]
    assert [when for when, groups in s.archive_runs if groups == ("twse",)] == [
        at(DAY, 22, 35), at(DAY, 22, 50), at(DAY, 23, 5)]
    assert s.stored(engine) == {"2330.TW": D("2400")}


def test_a_scheduled_run_that_stored_the_day_ends_the_watch(engine, md, watched):
    s = Scenario(md, twse=at(DAY, 21, 30), tpex=at(DAY, 21, 30))
    s.morning_archive()
    s.run(at(DAY, 13, 0), at(DAY, 21, 34))
    s.clock.t = at(DAY, 21, 34)
    asyncio.run(s.worker.archive(["twse", "tpex"]))  # e.g. the evening archive run got there first
    seen = len(s.exchanges.requests)
    runs = len(s.archive_runs)
    s.run(at(DAY, 21, 35), at(NEXT, 13, 0))
    assert len(s.exchanges.requests) == seen and len(s.archive_runs) == runs and s.refreshes == []
    assert s.stored(engine) == {"2330.TW": D("2400"), "6488.TWO": D("450")}


def test_hosts_without_conditional_requests_or_ranges_cost_one_request_per_check(engine, md, watched):
    s = Scenario(md, twse=at(DAY, 15, 0), tpex=at(DAY, 15, 0), conditional=False, ranges=False)
    s.morning_archive()
    s.run(at(DAY, 13, 0), at(NEXT, 13, 0))
    checks = ticks(at(DAY, 13, 35), at(DAY, 15, 5))
    for market in ("TWSE", "TPEX"):
        assert s.exchanges.kinds(market) == [*["200"] * len(checks), "full"]
        assert s.exchanges.times(market, "200") == checks
    assert s.archive_runs == [(at(DAY, 15, 5), ("twse",)), (at(DAY, 15, 5), ("tpex",))]


def test_an_unreachable_exchange_is_asked_again_and_does_not_stop_the_other(engine, md, watched):
    s = Scenario(md, twse=at(DAY, 14, 0), tpex=at(DAY, 14, 0))
    s.morning_archive()
    handler = s.exchanges.handler

    def twse_down(request: httpx.Request) -> httpx.Response:
        if request.url.host == "openapi.twse.com.tw" and s.clock.t < at(DAY, 14, 30):
            raise httpx.ConnectError("connection reset", request=request)
        return handler(request)

    s.exchanges.handler = twse_down  # type: ignore[method-assign]
    s.run(at(DAY, 13, 0), at(DAY, 15, 0))
    assert s.archive_runs == [(at(DAY, 14, 5), ("tpex",)), (at(DAY, 14, 35), ("twse",))]
    assert s.stored(engine) == {"2330.TW": D("2400"), "6488.TWO": D("450")}


# -- when nothing may be asked ------------------------------------------------------------------------------------
def test_nothing_is_asked_outside_the_window_or_on_a_non_trading_day(engine, md, watched):
    s = Scenario(md, twse=at(DAY, 14, 0), tpex=at(DAY, 14, 0))
    job = next(j for j in s.worker.jobs if j.name == "close_watch")
    saturday, sunday, holiday = date(2026, 11, 14), date(2026, 11, 15), date(2026, 10, 9)
    for when in (at(DAY, 9, 0), at(DAY, 13, 34), at(NEXT, 8, 30), at(NEXT, 13, 0), at(saturday, 8, 30),
                 at(saturday, 15, 0), at(sunday, 2, 0), at(sunday, 22, 0), at(holiday, 14, 0), at(holiday, 23, 0)):
        if when.date() == NEXT and is_tw_trading_day(NEXT) and when.time() >= time(13, 35):
            continue
        s.clock.t = when
        assert not job.due(when, None), when
        asyncio.run(s.worker.close_watch())  # even when called directly
    assert s.exchanges.requests == [] and s.exchanges.other == [] and s.archive_runs == []
    assert job.due(at(DAY, 13, 35), None) and job.due(at(NEXT, 8, 29), at(NEXT, 8, 10))
    assert not job.due(at(DAY, 13, 49), at(DAY, 13, 35))  # at most once every 15 minutes
    assert job.due(at(DAY, 13, 50), at(DAY, 13, 35))


def test_an_official_closure_is_not_watched(engine, md, watched):
    """A closure only the official schedule knows (the worker reloads it after every archive run)."""
    from forliosa.market_calendar import load_official_calendar

    s = Scenario(md, twse=at(DAY, 14, 0), tpex=at(DAY, 14, 0))
    with Session(engine) as db:
        db.add(MarketHoliday(date=DAY, name="颱風停止交易", description="", is_trading_day=False,
                             source="twse-openapi"))
        db.commit()
        load_official_calendar(db)
    s.run(at(DAY, 13, 0), at(NEXT, 8, 40))
    assert s.exchanges.requests == [] and s.archive_runs == []


# -- the pieces -------------------------------------------------------------------------------------------------------
def test_close_publication_remembers_validators_only_as_an_optimisation(md):
    clock = Clock(at(DAY, 14, 0))
    exchanges = Exchanges(clock, twse=at(DAY, 22, 0), tpex=None)
    twse = next(d for d in CLOSE_DATASETS if d.market == "TWSE")
    publication = ClosePublication(exchanges.fetcher())
    assert publication.data_date(twse) == PREVIOUS and publication.data_date(twse) == PREVIOUS
    clock.t = at(DAY, 22, 0)
    assert publication.data_date(twse) == DAY and publication.data_date(twse) == DAY
    assert exchanges.kinds("TWSE") == ["206", "304", "206", "304"]
    assert ClosePublication(exchanges.fetcher()).data_date(twse) == DAY  # a new process: asks afresh, same answer
    assert exchanges.kinds("TWSE")[-1] == "206"


def test_the_scheduled_jobs_are_all_still_there(md):
    """The close watch is an addition: the fixed-time runs keep their slots (they also carry everything else the
    archive groups hold — notices, margin, indices — and are the safety net when the watch window is missed)."""
    jobs = {j.name: j for j in Worker(md=md).jobs}
    assert {"close_watch", "after_close_refresh", "daily_archive_morning", "daily_archive_close",
            "daily_archive_evening"} <= set(jobs)
    for name, hh, mm in (("after_close_refresh", 14, 35), ("after_close_refresh", 23, 45),
                         ("daily_archive_morning", 8, 10), ("daily_archive_close", 14, 40),
                         ("daily_archive_evening", 21, 40)):
        assert jobs[name].due(at(DAY, hh, mm), None) and not jobs[name].due(at(DAY, hh, mm - 5), None), name
    assert CLOSE_WATCH_SECONDS == 15 * 60


def test_the_price_status_never_moves_back(engine, md):
    """A stale copy of the file (CDN) fetched after the day is stored must not make the day look missing."""
    s = Scenario(md, twse=at(DAY, 14, 0), tpex=at(DAY, 14, 0))
    s.clock.t = at(DAY, 14, 5)
    asyncio.run(s.worker.archive(["twse", "tpex"]))
    assert s.status(engine) == {"twse-openapi/price": DAY, "tpex-openapi/price": DAY}
    s.exchanges.published = {"TWSE": None, "TPEX": None}  # an older copy is served again
    asyncio.run(s.worker.archive(["twse", "tpex"]))
    assert s.status(engine) == {"twse-openapi/price": DAY, "tpex-openapi/price": DAY}
    s.run(at(DAY, 14, 6), at(NEXT, 9, 0))
    assert len(s.archive_runs) == 2  # the watch did not start again
