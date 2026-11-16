"""Same-day Taiwan closes (forliosa.closes; product owner 2026-11-16).

* TWSE's data.gov.tw download links (the narrow exception in CLAUDE.md): parsed from the real files fetched on
  2026-11-16 15:00 Taipei (tests/marketdata/fixtures/*open_data_live_20261116.csv); only the two exact URLs; polled on
  trading days from 13:45 at most every 10 minutes until the session is in; a refusal stops the day; the date comes
  from the file, never the clock; the next morning's OpenAPI rows replace them.
* shioaji-data's evening release as an interim close, replaced by any official row and never replacing one.
* ``GET /meta/market-status`` ``tw.closes``: the session, stored / latest / interim and the expected window.

Fake clock and fake hosts (httpx.MockTransport behind the real HttpFetcher); nothing reaches the network.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa import closes, market_calendar
from forliosa.archive import Archiver
from forliosa.marketdata import opendata as od
from forliosa.marketdata import twse_opendata as tod
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.base import ProviderUnavailable
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.http import ALLOWED_EXACT_URLS, HttpFetcher, HttpStatusError, RateLimiter, url_allowed
from forliosa.marketdata.service import MarketData
from forliosa.marketdata.twse import parse_stock_day_all
from forliosa.models import DatasetStatus, IndexDaily, Instrument, PriceDaily
from forliosa.timeutil import TAIPEI
from forliosa.worker import Worker

FIX = Path(__file__).parent / "marketdata" / "fixtures"
STOCK_DAY_ALL_CSV = (FIX / "twse_stock_day_all_open_data_live_20261116.csv").read_bytes()
MI_INDEX_CSV = (FIX / "twse_mi_index_open_data_live_20261116.csv").read_bytes()
DAY = date(2026, 11, 16)  # Monday, the session of the real files
PREV = date(2026, 11, 13)  # Friday
TUE = date(2026, 11, 17)
TAIEX = "發行量加權股價指數"
EXCHANGE_KEYS = ("twse-openapi/price", "tpex-openapi/price", "twse-openapi/index")


def at(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), TAIPEI)


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self) -> datetime:
        return self.t


def disposition(name: str, day: date) -> dict[str, str]:
    return {"Content-Type": "text/csv;charset=utf-8",
            "Content-Disposition": f'attachment; filename="{name}_{day:%Y%m%d}.csv"'}


def relabel(raw: bytes, day: date) -> bytes:
    """The real file with another session's date in every row."""
    return raw.replace(b'"1151116"', f'"{day.year - 1911}{day.month:02d}{day.day:02d}"'.encode())


class Twse:
    """www.twse.com.tw: the two files carry ``PREV`` until ``published``, then ``DAY`` (the real 2026-11-16 files)."""

    def __init__(self, clock: Clock, published: datetime | None = at(DAY, 13, 52)):
        self.clock = clock
        self.published = published
        self.refuse: int | None = None  # answer this status instead (403, 307, 429, 503 …)
        self.body: dict[str, tuple[bytes, dict[str, str]]] = {}  # path name -> a fixed answer
        self.requests: list[tuple[datetime, str]] = []

    def day(self) -> date:
        return DAY if self.published is not None and self.clock.t >= self.published else PREV

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((self.clock.t, str(request.url)))
        if self.refuse is not None:
            headers = {"Location": "https://www.twse.com.tw/zh/"} if 300 <= self.refuse < 400 else {}
            return httpx.Response(self.refuse, headers=headers)
        name = request.url.path.rsplit("/", 1)[-1]
        if name in self.body:
            content, headers = self.body[name]
            return httpx.Response(200, content=content, headers=headers)
        raw, file = (STOCK_DAY_ALL_CSV, "STOCK_DAY_ALL") if name == "STOCK_DAY_ALL" else (MI_INDEX_CSV, "MI_INDEX_IND")
        day = self.day()
        return httpx.Response(200, content=relabel(raw, day), headers=disposition(file, day))

    def fetcher(self) -> HttpFetcher:
        return HttpFetcher(client=httpx.Client(transport=httpx.MockTransport(self.handler)), limiter=RateLimiter(),
                           retries=0)

    def times(self) -> list[datetime]:
        return [t for t, _url in self.requests]


@pytest.fixture()
def md(engine) -> MarketData:
    return MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine)), DemoProvider()],
                      policy="commercial")


@pytest.fixture()
def friday_stored(engine):
    """The OpenAPIs' Friday: official closes of PREV for a few stocks of both markets, and the status rows."""
    with Session(engine) as db:
        for sym, close, volume, source in (("2330.TW", "2350", 30000000, "twse-openapi"),
                                           ("2317.TW", "241", 60000000, "twse-openapi"),
                                           ("0050.TW", "102.5", 300000000, "twse-openapi"),
                                           ("6488.TWO", "445", 1000000, "tpex-openapi")):
            db.add(PriceDaily(symbol=sym, date=PREV, open=D(close), high=D(close), low=D(close), close=D(close),
                              volume=volume, source=source))
        db.add(IndexDaily(name=TAIEX, date=PREV, market="TWSE", close=D("43675.12"), source="twse-openapi"))
        for key in EXCHANGE_KEYS:
            db.add(DatasetStatus(key=key, data_date=PREV, rows=1))
        db.commit()


def prices(engine, day: date = DAY) -> dict[str, tuple[D, int | None, str]]:
    with Session(engine) as db:
        return {r.symbol: (r.close, r.volume, r.source)
                for r in db.scalars(select(PriceDaily).where(PriceDaily.date == day))}


def status(engine) -> dict[str, date | None]:
    with Session(engine) as db:
        return {r.key: r.data_date for r in db.scalars(select(DatasetStatus))}


# -- the real files ---------------------------------------------------------------------------------------------------
def test_the_real_stock_day_all_file_parses_into_the_openapi_fields():
    rows = tod.stock_day_all_rows(STOCK_DAY_ALL_CSV)
    assert len(rows) == 12 and set(rows[0]) == set(tod.STOCK_DAY_ALL_COLUMNS.values())
    assert tod.file_date(rows, "Date", 'attachment; filename="STOCK_DAY_ALL_20261116.csv"') == DAY
    quotes = parse_stock_day_all(rows)
    tsmc = quotes["2330.TW"]
    assert (tsmc.price, tsmc.open, tsmc.high, tsmc.low, tsmc.volume, tsmc.trade_date) == (
        D("2215.00"), D("2340.00"), D("2350.00"), D("2215.00"), 50206545, DAY)
    assert tsmc.prev_close == D("2350.0000")  # close − 漲跌價差
    assert quotes["0050.TW"].price == D("96.45") and quotes["00400A.TW"].price == D("11.73")
    # no trade that day: empty prices, so no close is stored
    for code in ("00625K", "00682U", "1538", "020011"):
        assert f"{code}.TW" not in quotes
    # the ETF list reads the same rows (code and short name)
    etfs = {e["code"]: e["name"] for e in od.parse_listed_etfs(rows, "TWSE")}
    assert etfs["0050"] == "元大台灣50" and etfs["006208"] == "富邦台50"


def test_the_real_mi_index_file_parses_into_the_openapi_fields():
    rows = tod.mi_index_rows(MI_INDEX_CSV)
    assert tod.file_date(rows, "日期", 'attachment; filename="MI_INDEX_IND_20261116.csv"') == DAY
    parsed = {r["name"]: r for r in od.parse_mi_index(rows)}
    taiex = parsed[TAIEX]
    assert (taiex["date"], taiex["close"], taiex["change"], taiex["change_pct"]) == (
        DAY, D("41040.08"), D("-2635.04"), D("-0.0603"))
    assert parsed["食品類指數"]["change"] == D("5.04")  # 「+」
    assert parsed["發行量加權股價報酬指數"]["close"] == D("94901.06")
    assert "臺灣50報酬指數" not in parsed  # the afternoon file has no value for it yet: no date, skipped
    assert len(parsed) == 7


def test_the_data_date_comes_from_the_file_and_must_agree():
    rows = tod.stock_day_all_rows(STOCK_DAY_ALL_CSV)
    assert tod.file_date(rows, "Date") == DAY  # without a file name, the rows alone
    with pytest.raises(ProviderUnavailable, match="檔名日期"):
        tod.file_date(rows, "Date", 'attachment; filename="STOCK_DAY_ALL_20261113.csv"')
    mixed = [*rows[:3], {**rows[3], "Date": "1151113"}]
    with pytest.raises(ProviderUnavailable, match="不一致"):
        tod.file_date(mixed, "Date")
    with pytest.raises(ProviderUnavailable, match="沒有日期"):
        tod.file_date([{**r, "Date": ""} for r in rows], "Date")
    assert tod.disposition_date('attachment; filename="MI_INDEX_IND_20261116.csv"') == DAY
    assert tod.disposition_date("attachment") is None and tod.disposition_date(None) is None


def test_a_changed_file_stores_nothing():
    renamed = STOCK_DAY_ALL_CSV.replace("收盤價".encode(), "收盤".encode(), 1)
    with pytest.raises(ProviderUnavailable, match="收盤價"):
        tod.stock_day_all_rows(renamed)
    with pytest.raises(ProviderUnavailable, match="UTF-8"):
        tod.stock_day_all_rows(STOCK_DAY_ALL_CSV.decode("utf-8").encode("big5", errors="replace"))


# -- the allowlist ----------------------------------------------------------------------------------------------------
def test_only_the_two_exact_twse_urls_are_allowed():
    assert {tod.STOCK_DAY_ALL_URL, tod.MI_INDEX_URL} == ALLOWED_EXACT_URLS
    assert url_allowed(tod.STOCK_DAY_ALL_URL) and url_allowed(tod.MI_INDEX_URL)
    for url in (
        f"{tod.STOCK_DAY_ALL_URL}&date=20261113",  # a date parameter
        "https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=json",
        "https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=open_data&",
        f"{tod.STOCK_DAY_ALL_URL}#x",
        "https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL",
        "https://www.twse.com.tw/exchangeReport/STOCK_DAY_AVG_ALL?response=open_data",
        "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=open_data&type=ALL",
        "https://www.twse.com.tw/exchangeReport/BWIBBU_d?response=open_data",
        "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL?response=open_data",
        "https://www.twse.com.tw/exchangeReport/",
        "https://www.twse.com.tw/zh/",
        "http://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=open_data",
        "https://twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=open_data",
        "https://mis.twse.com.tw/stock/api/getStockInfo.jsp",
        "https://www.tpex.org.tw/web/stock/aftertrading/DAILY_CLOSE_quotes/stk_quote_result.php?l=zh-tw&o=data",
    ):
        assert not url_allowed(url), url
    # params on an exact URL: refused before anything is sent
    asked: list[str] = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: asked.append(str(r.url)) or httpx.Response(200)))
    fetcher = HttpFetcher(client=client, limiter=RateLimiter(), retries=0)
    with pytest.raises(ProviderUnavailable, match="白名單"):
        fetcher.fetch(tod.STOCK_DAY_ALL_URL, params={"date": "20261113"})
    with pytest.raises(ProviderUnavailable, match="白名單"):
        fetcher.fetch("https://www.twse.com.tw/exchangeReport/STOCK_DAY_AVG_ALL?response=open_data")
    assert asked == []


def test_a_redirect_is_a_refusal_and_never_followed():
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(307, headers={"Location": "https://www.twse.com.tw/zh/"})

    fetcher = HttpFetcher(client=httpx.Client(transport=httpx.MockTransport(handler)), limiter=RateLimiter(),
                          retries=0)
    with pytest.raises(HttpStatusError) as err:
        fetcher.fetch(tod.STOCK_DAY_ALL_URL)
    assert err.value.status == 307 and asked == [tod.STOCK_DAY_ALL_URL]


# -- polling (worker job twse_sameday_close) -------------------------------------------------------------------------
class Scene:
    def __init__(self, md: MarketData, twse: Twse, clock: Clock):
        self.md, self.twse, self.clock = md, twse, clock
        self.refreshes: list[datetime] = []
        self.worker = self.start()

    def start(self) -> Worker:
        """A new worker process: nothing in memory, the same database."""
        worker = Worker(md=self.md, now_fn=self.clock, fetcher_fn=self.twse.fetcher, twse_fetcher_fn=self.twse.fetcher)
        refresh = worker.after_close_refresh

        async def counted() -> None:
            self.refreshes.append(self.clock.t)
            await refresh()

        worker.after_close_refresh = counted  # type: ignore[method-assign]
        self.worker = worker
        return worker

    def run(self, start: datetime, end: datetime) -> None:
        job = next(j for j in self.worker.jobs if j.name == "twse_sameday_close")

        async def loop() -> None:
            t = start
            while t <= end:
                self.clock.t = t
                if job.due(t, job.last_run):
                    job.last_run = t
                    await job.run()
                t += timedelta(minutes=1)

        asyncio.run(loop())


@pytest.fixture()
def scene(md, friday_stored) -> Scene:
    clock = Clock(at(DAY, 13, 0))
    return Scene(md, Twse(clock), clock)


def test_the_close_is_stored_the_afternoon_of_the_session_and_then_nothing_is_asked(engine, scene, monkeypatch):
    monkeypatch.setattr("forliosa.marketdata.archive_provider.today_taipei", lambda: DAY)  # the quote window
    scene.run(at(DAY, 13, 0), at(DAY, 23, 59))
    # 13:45: still Friday's file (one request); 13:55: today's — both files; then nothing more
    assert scene.twse.requests == [(at(DAY, 13, 45), tod.STOCK_DAY_ALL_URL), (at(DAY, 13, 55), tod.STOCK_DAY_ALL_URL),
                                   (at(DAY, 13, 55), tod.MI_INDEX_URL)]
    assert scene.refreshes == [at(DAY, 13, 55)]
    stored = prices(engine)
    assert stored["2330.TW"] == (D("2215"), 50206545, "twse-opendata")
    assert stored["0050.TW"] == (D("96.45"), 357525464, "twse-opendata")
    assert "6488.TWO" not in stored  # TPEx is not in this file
    st = status(engine)
    assert (st["twse-opendata/price"], st["twse-opendata/index"]) == (DAY, DAY)
    assert st["twse-openapi/price"] == PREV  # the close watch still waits for the OpenAPI's (final) file
    assert st[closes.TWSE_POLL_KEY] == DAY
    with Session(engine) as db:
        taiex = db.get(IndexDaily, (TAIEX, DAY))
        assert (taiex.close, taiex.change, taiex.source) == (D("41040.08"), D("-2635.04"), "twse-opendata")
        assert db.get(Instrument, "006208.TW").type == "etf"  # the ETF list is kept current from the same file
    # the ledger reads it (official data): the archive's quote is today's close, against Friday's
    q = scene.md.quotes(["2330.TW"], use_cache=False)["2330.TW"]
    assert (q.price, q.prev_close, q.trade_date, q.source) == (D("2215"), D("2350"), DAY, "twse-opendata")


def test_never_more_than_one_request_per_ten_minutes_even_across_restarts(engine, scene):
    scene.twse.published = None  # TWSE is late today
    scene.run(at(DAY, 13, 40), at(DAY, 13, 47))
    scene.start()  # redeployed at 13:48: nothing in memory
    scene.run(at(DAY, 13, 48), at(DAY, 14, 20))
    assert scene.twse.times() == [at(DAY, 13, 45), at(DAY, 13, 55), at(DAY, 14, 5), at(DAY, 14, 15)]
    scene.run(at(DAY, 14, 21), at(DAY + timedelta(days=1), 1, 0))
    times = scene.twse.times()
    assert times[-1] == at(DAY, 23, 55)  # the last look of the day; the next morning's OpenAPI takes over
    assert len(times) == 62  # 13:45 … 23:55, one every 10 minutes
    assert all(b - a >= timedelta(minutes=10) for a, b in itertools.pairwise(times))
    assert prices(engine) == {} and scene.refreshes == []


@pytest.mark.parametrize("refusal", [403, 429, 307, 301])
def test_a_refusal_stops_it_for_the_day(engine, scene, refusal):
    scene.twse.refuse = refusal
    scene.run(at(DAY, 13, 40), at(DAY, 15, 0))
    assert scene.twse.times() == [at(DAY, 13, 45)]
    st = status(engine)
    assert st[closes.TWSE_REFUSED_KEY] == DAY
    scene.start()  # a restart does not forget
    scene.twse.refuse = None
    scene.run(at(DAY, 15, 0), at(DAY, 23, 0))
    assert scene.twse.times() == [at(DAY, 13, 45)] and prices(engine) == {}
    # the next trading day it looks again (the fake still serves Monday's file: not Tuesday's, so nothing stored)
    scene.run(at(TUE, 13, 40), at(TUE, 13, 50))
    assert scene.twse.times()[1:] == [at(TUE, 13, 45)] and prices(engine, TUE) == {}


def test_a_server_error_is_asked_again_ten_minutes_later(engine, scene):
    scene.twse.refuse = 503
    scene.run(at(DAY, 13, 40), at(DAY, 13, 50))
    scene.twse.refuse = None
    scene.run(at(DAY, 13, 51), at(DAY, 14, 30))
    assert scene.twse.times() == [at(DAY, 13, 45), at(DAY, 13, 55), at(DAY, 13, 55)]
    assert closes.TWSE_REFUSED_KEY not in status(engine) and prices(engine)["2330.TW"][2] == "twse-opendata"


def test_nothing_is_asked_outside_trading_day_afternoons(engine, scene):
    for start, end in ((at(DAY, 0, 0), at(DAY, 13, 44)), (at(DAY, 23, 59), at(DAY, 23, 59)),
                       (at(date(2026, 11, 14), 0, 0), at(date(2026, 11, 15), 23, 59)),  # a weekend
                       (at(date(2026, 10, 9), 13, 0), at(date(2026, 10, 9), 19, 0))):  # 國慶日 (built-in holiday)
        scene.run(start, end)
    assert scene.twse.requests == []
    assert closes.twse_poll_day(at(DAY, 13, 45)) == DAY and closes.twse_poll_day(at(DAY, 23, 58)) == DAY
    assert closes.twse_poll_day(at(DAY, 13, 44)) is None and closes.twse_poll_day(at(DAY, 23, 59)) is None
    assert closes.twse_poll_day(at(DAY + timedelta(days=1), 0, 0)) is None


def test_a_worker_started_in_the_evening_still_gets_the_same_day_file(engine, scene):
    """2026-11-16: the worker was redeployed at 18:15 and 21:30, after the old 18:00 cut-off, so the afternoon file was
    never asked for and the listed closes waited for the evening release. Now the first poll after a late start
    fetches it once, and then nothing more is asked that day."""
    scene.run(at(DAY, 21, 30), at(DAY, 23, 59))
    assert scene.twse.times()[0] == at(DAY, 21, 30)
    assert len(scene.twse.times()) <= 2  # STOCK_DAY_ALL (and MI_INDEX once), then stored: no more requests
    assert prices(engine)["2330.TW"][2] == "twse-opendata"


def test_the_switch_turns_the_job_off(md, monkeypatch):
    from forliosa.config import get_settings

    monkeypatch.setenv("TWSE_OPENDATA_CLOSE", "false")
    monkeypatch.setenv("SHIOAJI_EVENING_CLOSE", "false")
    get_settings.cache_clear()
    names = {j.name for j in Worker(md=md).jobs}
    assert "twse_sameday_close" not in names and "evening_closes" not in names
    monkeypatch.delenv("TWSE_OPENDATA_CLOSE")
    monkeypatch.delenv("SHIOAJI_EVENING_CLOSE")
    get_settings.cache_clear()
    names = {j.name for j in Worker(md=md).jobs}
    assert {"twse_sameday_close", "evening_closes", "close_watch"} <= names


# -- yesterday's file is never today's -------------------------------------------------------------------------------
def poll(engine, twse: Twse, when: datetime) -> closes.TwsePoll:
    twse.clock.t = when
    with Session(engine) as db:
        return closes.TwseSameDay(twse.fetcher(), now_fn=twse.clock).poll(db)


def test_yesterdays_file_is_not_stored_as_today(engine, friday_stored, monkeypatch):
    twse = Twse(Clock(at(DAY, 13, 45)), published=None)
    res = poll(engine, twse, at(DAY, 13, 45))  # Friday's file, as it is before TWSE publishes
    assert (res.found, res.prices) == (PREV, 0) and prices(engine) == {} and prices(engine, PREV)["2330.TW"][2] == (
        "twse-openapi")  # Friday's official row untouched
    # Friday's rows under today's file name: the name and the rows disagree
    twse.body["STOCK_DAY_ALL"] = (relabel(STOCK_DAY_ALL_CSV, PREV), disposition("STOCK_DAY_ALL", DAY))
    res = poll(engine, twse, at(DAY, 13, 55))
    assert res.prices == 0 and prices(engine) == {}
    # a file dated today whose every close and volume is the stored Friday's: a stale copy, relabelled
    monkeypatch.setattr(closes, "SAME_AS_BEFORE_MIN", 3)
    with Session(engine) as db:
        for q in parse_stock_day_all(tod.stock_day_all_rows(STOCK_DAY_ALL_CSV)).values():
            row = db.get(PriceDaily, (q.symbol, PREV)) or PriceDaily(symbol=q.symbol, date=PREV, source="twse-openapi")
            row.close, row.volume = q.price, q.volume
            db.add(row)
        db.commit()
    twse.body.clear()
    twse.published = at(DAY, 13, 0)
    res = poll(engine, twse, at(DAY, 14, 5))
    assert res.prices == 0 and prices(engine) == {}
    # a file dated after today: never stored
    twse.body["STOCK_DAY_ALL"] = (relabel(STOCK_DAY_ALL_CSV, TUE), disposition("STOCK_DAY_ALL", TUE))
    res = poll(engine, twse, at(DAY, 14, 15))
    assert (res.found, res.prices) == (TUE, 0) and prices(engine) == {} and prices(engine, TUE) == {}


# -- the OpenAPI's file replaces it ----------------------------------------------------------------------------------
class OpenApi:
    """openapi.twse.com.tw the next morning: the session's final file (more volume: after-hours, odd lots)."""

    def __init__(self, rows: list[dict], indices: list[dict]):
        self.rows, self.indices = rows, indices

    def get_json(self, url, params=None, headers=None):
        if url.endswith("/exchangeReport/STOCK_DAY_ALL"):
            return self.rows
        if url.endswith("/exchangeReport/MI_INDEX"):
            return self.indices
        raise AssertionError(url)


def test_the_next_mornings_openapi_file_replaces_the_rows(engine, friday_stored):
    twse = Twse(Clock(at(DAY, 14, 0)), published=at(DAY, 13, 50))
    assert poll(engine, twse, at(DAY, 14, 0)).prices == 8
    final = [{**r, "TradeVolume": str(int(r["TradeVolume"]) + 1000)} if r["Code"] == "2330" else r
             for r in tod.stock_day_all_rows(STOCK_DAY_ALL_CSV)]
    with Session(engine) as db:
        archiver = Archiver(db, OpenApi(final, tod.mi_index_rows(MI_INDEX_CSV)), now_fn=lambda: at(TUE, 5, 30))
        archiver.twse_prices()
        archiver.twse_indices()
        assert db.get(IndexDaily, (TAIEX, DAY)).source == "twse-openapi"
    stored = prices(engine)
    assert stored["2330.TW"] == (D("2215"), 50207545, "twse-openapi")
    assert {source for _c, _v, source in stored.values()} == {"twse-openapi"}  # every row, cleanly
    assert status(engine)["twse-openapi/price"] == DAY
    # and the same-day file never overwrites a final row
    with Session(engine) as db:
        Archiver(db, twse.fetcher()).store_twse_opendata_prices(tod.stock_day_all_rows(STOCK_DAY_ALL_CSV))
    assert prices(engine)["2330.TW"] == (D("2215"), 50207545, "twse-openapi")


# -- shioaji-data's evening release (interim) ------------------------------------------------------------------------
class Shioaji:
    """raw.githubusercontent.com: daily.json carries PREV until ``published``, then DAY (ETag, 304, byte ranges)."""

    PATH = "/Sinotrade/shioaji-data/main/v1/tw/market/daily.json"

    def __init__(self, clock: Clock, published: datetime | None):
        self.clock, self.published = clock, published
        self.requests: list[tuple[datetime, str]] = []

    def day(self) -> date:
        return DAY if self.published is not None and self.clock.t >= self.published else PREV

    def body(self) -> bytes:
        d = self.day().isoformat()
        quotes = {"2330": {"close": 2215.0 if self.day() == DAY else 2350.0, "date": d},
                  "2317": {"close": 218.5, "date": d}, "6488": {"close": 431.5, "date": d},
                  "9999": {"close": 10.0, "date": d},  # a code the archive does not know: never guessed
                  "1101": {"close": 26.45, "date": "2026-11-12"}}  # an older close inside the file
        return json.dumps({"as_of": {"tpex": d, "twse": d}, "quotes": quotes}, separators=(",", ":")).encode()

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == self.PATH, request.url
        etag = f'"{self.day()}"'
        if request.headers.get("If-None-Match") == etag:
            self.requests.append((self.clock.t, "304"))
            return httpx.Response(304, headers={"ETag": etag})
        body = self.body()
        if "Range" in request.headers:
            self.requests.append((self.clock.t, "206"))
            last = int(request.headers["Range"].removeprefix("bytes=0-"))
            return httpx.Response(206, content=body[:last + 1], headers={"ETag": etag})
        self.requests.append((self.clock.t, "full"))
        return httpx.Response(200, content=body, headers={"ETag": etag})

    def fetcher(self) -> HttpFetcher:
        return HttpFetcher(client=httpx.Client(transport=httpx.MockTransport(self.handler)), limiter=RateLimiter(),
                           retries=0)


def evening_run(engine, sj: Shioaji, evening: closes.EveningCloses, start: datetime, end: datetime) -> None:
    t = start
    while t <= end:
        sj.clock.t = t
        if closes.evening_day(t) is not None:
            with Session(engine) as db:
                evening.poll(db)
        t += timedelta(minutes=15)


def test_the_evening_release_is_an_interim_close_until_the_official_file(engine, friday_stored):
    clock = Clock(at(DAY, 20, 30))
    sj = Shioaji(clock, published=at(DAY, 22, 41))
    evening = closes.EveningCloses(sj.fetcher(), "https://raw.githubusercontent.com/Sinotrade/shioaji-data/main",
                                   now_fn=clock)
    with Session(engine) as db:  # TWSE's same-day file came in at 14:00
        db.add(DatasetStatus(key="twse-opendata/price", data_date=DAY, rows=1))
        db.add(PriceDaily(symbol="2330.TW", date=DAY, close=D("2215"), volume=50206545, source="twse-opendata"))
        db.commit()
    evening_run(engine, sj, evening, at(DAY, 20, 30), at(TUE, 3, 0))
    # 20:30 the first bytes, 304 until the release, then the first bytes and the file once; TPEx done after that
    kinds = [k for _t, k in sj.requests]
    assert kinds[0] == "206" and kinds[-2:] == ["206", "full"] and set(kinds[1:-2]) == {"304"}
    assert sj.requests[-1][0] == at(DAY, 22, 45)
    stored = prices(engine)
    assert stored["6488.TWO"] == (D("431.5"), None, "shioaji-data")  # interim, close only
    assert stored["2330.TW"] == (D("2215"), 50206545, "twse-opendata")  # TWSE was in: not touched
    assert "2317.TW" not in stored and "9999.TW" not in stored and "9999.TWO" not in stored
    st = status(engine)
    assert st["shioaji-data/interim_tpex"] == DAY and "shioaji-data/interim_twse" not in st
    with Session(engine) as db:
        tpex = next(c for c in closes.tw_closes(db, at(DAY, 22, 50)) if c["market"] == "TPEX")
    assert (tpex["stored"], tpex["latest"], tpex["interim"]) == (True, DAY.isoformat(), True)
    # TPEx's OpenAPI at 23:30 replaces it (every column), and the interim close never replaces an official one
    tpex_row = {"Date": "1151116", "SecuritiesCompanyCode": "6488", "CompanyName": "環球晶", "Close": "431.50",
                "Change": "-13.50", "Open": "440.00", "High": "441.00", "Low": "430.00", "TradingShares": "1500000"}

    class TpexOpenApi:
        def get_json(self, url, params=None, headers=None):
            return [tpex_row] if url.endswith("tpex_mainboard_daily_close_quotes") else []

    with Session(engine) as db:
        Archiver(db, TpexOpenApi()).tpex_prices()
        Archiver(db, sj.fetcher()).store_interim_closes({"6488.TWO": D("1")}, DAY, "shioaji-data/interim_tpex")
    assert prices(engine)["6488.TWO"] == (D("431.50"), 1500000, "tpex-openapi")
    with Session(engine) as db:
        tpex = next(c for c in closes.tw_closes(db, at(DAY, 23, 40)) if c["market"] == "TPEX")
    assert (tpex["stored"], tpex["interim"]) == (True, False)


def test_the_evening_release_fills_twse_too_when_the_same_day_file_did_not_come(engine, friday_stored):
    clock = Clock(at(DAY, 20, 30))
    sj = Shioaji(clock, published=at(DAY, 20, 0))
    evening = closes.EveningCloses(sj.fetcher(), "https://raw.githubusercontent.com/Sinotrade/shioaji-data/main",
                                   now_fn=clock)
    evening_run(engine, sj, evening, at(DAY, 20, 30), at(DAY, 21, 30))
    assert [k for _t, k in sj.requests] == ["206", "full"]  # both markets in at once: nothing asked afterwards
    stored = prices(engine)
    assert stored["2330.TW"] == (D("2215"), None, "shioaji-data") and stored["6488.TWO"][2] == "shioaji-data"
    assert stored["2317.TW"] == (D("218.5"), None, "shioaji-data")
    # nothing outside 20:30–02:00 or on the evening of a non-trading day
    assert closes.evening_day(at(DAY, 20, 29)) is None and closes.evening_day(at(TUE, 2, 0)) is None
    assert closes.evening_day(at(TUE, 1, 59)) == DAY and closes.evening_day(at(date(2026, 11, 14), 21, 0)) is None
    assert closes.evening_day(at(date(2026, 11, 14), 1, 0)) == PREV  # Friday's release after midnight


def test_first_as_of_reads_the_head_of_the_file():
    assert closes.first_as_of(b'{"as_of":{"tpex":"2026-11-13","twse":"2026-11-12"},"quotes":{"1101":') == {
        "TPEX": PREV, "TWSE": date(2026, 11, 12)}
    assert closes.first_as_of(b'{"quotes":{}}') == {} and closes.first_as_of(b'{"as_of":{"twse":"x"}') == {}


# -- GET /meta/market-status: tw.closes ------------------------------------------------------------------------------
STATUS_KEYS = {"twse_openapi_price": "twse-openapi/price", "tpex_openapi_price": "tpex-openapi/price",
               "twse_opendata_price": "twse-opendata/price", "twse_opendata_refused": "twse-opendata/refused",
               "shioaji_data_interim_twse": "shioaji-data/interim_twse",
               "shioaji_data_interim_tpex": "shioaji-data/interim_tpex"}


def write_status(engine, **dates: date) -> None:
    """dataset_status rows, e.g. ``twse_opendata_price=DAY`` -> key ``twse-opendata/price``."""
    with Session(engine) as db:
        for name, d in dates.items():
            key = STATUS_KEYS[name]
            row = db.get(DatasetStatus, key) or DatasetStatus(key=key, rows=0)
            row.data_date = d
            db.add(row)
        db.commit()


def closes_at(engine, when: datetime, settings=None) -> dict[str, dict]:
    with Session(engine) as db:
        return {c["market"]: c for c in closes.tw_closes(db, when, settings or ON)}


ON = SimpleNamespace(twse_opendata_close=True, shioaji_evening_close=True)


def window(c: dict) -> tuple[str | None, str | None]:
    return c["expected_from"], c["expected_to"]


def iso(day: date, hh: int, mm: int = 0) -> str:
    return at(day, hh, mm).isoformat(timespec="seconds")


@pytest.fixture()
def friday_in(engine):
    write_status(engine, twse_openapi_price=PREV, tpex_openapi_price=PREV)


def test_1405_listed_close_expected_this_afternoon_otc_tonight(engine, friday_in):
    c = closes_at(engine, at(DAY, 14, 5))
    assert c["TWSE"] == {"market": "TWSE", "session": "2026-11-16", "stored": False, "latest": "2026-11-13",
                         "interim": False, "expected_from": iso(DAY, 14, 0), "expected_to": iso(DAY, 14, 30),
                         "index": {"stored": False, "latest": None, "expected_from": iso(DAY, 14, 0),
                                   "expected_to": iso(DAY, 14, 30)}}
    assert c["TPEX"] == {"market": "TPEX", "session": "2026-11-16", "stored": False, "latest": "2026-11-13",
                         "interim": False, "expected_from": iso(DAY, 20, 30), "expected_to": iso(DAY, 23, 45),
                         "index": None}
    # 13:30–14:00: the same windows (the session is due from 13:30)
    assert window(closes_at(engine, at(DAY, 13, 31))["TWSE"]) == (iso(DAY, 14, 0), iso(DAY, 14, 30))


def test_1440_after_the_listed_close_came_in(engine, friday_in):
    write_status(engine, twse_opendata_price=DAY)
    c = closes_at(engine, at(DAY, 14, 40))
    assert (c["TWSE"]["stored"], c["TWSE"]["latest"], c["TWSE"]["interim"], window(c["TWSE"])) == (
        True, "2026-11-16", False, (None, None))
    assert window(c["TPEX"]) == (iso(DAY, 20, 30), iso(DAY, 23, 45))


def test_1440_listed_close_late_the_evening_window_is_next(engine, friday_in):
    assert window(closes_at(engine, at(DAY, 14, 40))["TWSE"]) == (iso(DAY, 20, 30), iso(DAY, 23, 45))
    # refused today: the afternoon window is not promised at all
    write_status(engine, twse_opendata_refused=DAY)
    assert window(closes_at(engine, at(DAY, 14, 5))["TWSE"]) == (iso(DAY, 20, 30), iso(DAY, 23, 45))


def test_2100_interim_otc_close(engine, friday_in):
    c = closes_at(engine, at(DAY, 21, 0))
    assert window(c["TPEX"]) == (iso(DAY, 20, 30), iso(DAY, 23, 45))
    write_status(engine, twse_opendata_price=DAY, shioaji_data_interim_tpex=DAY)
    c = closes_at(engine, at(DAY, 21, 0))
    # stored as the interim close, which has no ETFs: the official file's window is still given (2026-11-16 review)
    assert (c["TPEX"]["stored"], c["TPEX"]["latest"], c["TPEX"]["interim"], window(c["TPEX"])) == (
        True, "2026-11-16", True, (iso(DAY, 23, 15), iso(DAY, 23, 45)))
    assert (c["TWSE"]["stored"], c["TWSE"]["interim"]) == (True, False)
    write_status(engine, tpex_openapi_price=DAY)  # 23:30: the official file
    assert closes_at(engine, at(DAY, 23, 40))["TPEX"]["interim"] is False


def test_after_midnight_the_session_is_still_awaited(engine, friday_in):
    c = closes_at(engine, at(DAY, 23, 50))
    assert window(c["TWSE"]) == window(c["TPEX"]) == (iso(TUE, 0, 0), iso(TUE, 1, 30))
    c = closes_at(engine, at(TUE, 0, 30))
    assert (c["TWSE"]["session"], c["TWSE"]["stored"]) == ("2026-11-16", False)  # not "today's" any more, still due
    assert window(c["TWSE"]) == (iso(TUE, 0, 0), iso(TUE, 1, 30))
    c = closes_at(engine, at(TUE, 2, 0))
    assert window(c["TWSE"]) == (iso(TUE, 5, 20), iso(TUE, 5, 45))  # the OpenAPI's nightly batch
    assert window(c["TPEX"]) == (None, None)  # every measured window has passed: nothing is promised
    write_status(engine, tpex_openapi_price=DAY)
    assert closes_at(engine, at(TUE, 0, 30))["TPEX"]["stored"] is True


def test_0600_both_in(engine, friday_in):
    write_status(engine, twse_openapi_price=DAY, tpex_openapi_price=DAY)
    c = closes_at(engine, at(TUE, 6, 0))
    for m in ("TWSE", "TPEX"):
        assert (c[m]["session"], c[m]["stored"], c[m]["latest"], window(c[m])) == (
            "2026-11-16", True, "2026-11-16", (None, None))
    # 06:00 with TWSE still missing: past its last window
    write_status(engine, twse_openapi_price=PREV)
    assert window(closes_at(engine, at(TUE, 6, 0))["TWSE"]) == (None, None)
    # Tuesday before the close: Monday is still the session
    assert closes_at(engine, at(TUE, 13, 29))["TWSE"]["session"] == "2026-11-16"


def test_weekend(engine):
    write_status(engine, twse_openapi_price=PREV, tpex_openapi_price=PREV)
    for when in (at(date(2026, 11, 14), 12, 0), at(date(2026, 11, 15), 22, 0), at(DAY, 9, 0)):
        c = closes_at(engine, when)
        for m in ("TWSE", "TPEX"):
            assert (c[m]["session"], c[m]["stored"], window(c[m])) == ("2026-11-13", True, (None, None)), when
    # Friday's listed close not in on Saturday 01:00: the late evening window, then Saturday's batch
    write_status(engine, twse_openapi_price=date(2026, 11, 12))
    c = closes_at(engine, at(date(2026, 11, 14), 1, 0))
    assert window(c["TWSE"]) == (iso(date(2026, 11, 14), 0, 0), iso(date(2026, 11, 14), 1, 30))
    c = closes_at(engine, at(date(2026, 11, 14), 3, 0))
    assert window(c["TWSE"]) == (iso(date(2026, 11, 14), 5, 20), iso(date(2026, 11, 14), 5, 45))


def test_windows_follow_what_is_switched_on(engine, friday_in):
    no_sameday = SimpleNamespace(twse_opendata_close=False, shioaji_evening_close=True)
    assert window(closes_at(engine, at(DAY, 14, 5), no_sameday)["TWSE"]) == (iso(DAY, 20, 30), iso(DAY, 23, 45))
    official_only = SimpleNamespace(twse_opendata_close=False, shioaji_evening_close=False)
    c = closes_at(engine, at(DAY, 14, 5), official_only)
    assert window(c["TWSE"]) == (iso(TUE, 5, 20), iso(TUE, 5, 45))
    assert window(c["TPEX"]) == (iso(DAY, 23, 15), iso(DAY, 23, 45))


def test_no_archive_yet(engine):
    c = closes_at(engine, at(DAY, 14, 5))
    assert (c["TWSE"]["stored"], c["TWSE"]["latest"], c["TWSE"]["interim"]) == (False, None, False)


def test_the_endpoint(app, engine):
    write_status(engine, twse_openapi_price=PREV, tpex_openapi_price=PREV, twse_opendata_price=DAY)
    market_calendar.set_clock(lambda: at(DAY, 14, 40))
    try:
        body = TestClient(app).get("/api/v1/meta/market-status").json()
    finally:
        market_calendar.set_clock(None)
    assert body["tw"]["closes"] == [
        {"market": "TWSE", "session": "2026-11-16", "stored": True, "latest": "2026-11-16", "interim": False,
         "expected_from": None, "expected_to": None,
         # the indices' file not in (e.g. MI_INDEX refused after STOCK_DAY_ALL came in): the next morning's batch
         "index": {"stored": False, "latest": None, "expected_from": "2026-11-17T05:20:00+08:00",
                   "expected_to": "2026-11-17T05:45:00+08:00"}},
        {"market": "TPEX", "session": "2026-11-16", "stored": False, "latest": "2026-11-13", "interim": False,
         "expected_from": "2026-11-16T20:30:00+08:00", "expected_to": "2026-11-16T23:45:00+08:00", "index": None},
    ]


# -- who waits for official closes ----------------------------------------------------------------------------------
def test_the_briefing_and_the_rankings_count_the_same_day_file_but_not_interim_closes(engine, friday_in):
    from forliosa.ai.briefing import briefing_day

    with Session(engine) as db:
        assert briefing_day(db, at(DAY, 23, 0)) is None
    write_status(engine, twse_opendata_price=DAY, shioaji_data_interim_tpex=DAY)
    with Session(engine) as db:
        assert briefing_day(db, at(DAY, 23, 0)) is None  # TPEx only interim
        assert closes.official_close_dates(db) == {"TWSE": DAY, "TPEX": PREV}
    write_status(engine, tpex_openapi_price=DAY)
    with Session(engine) as db:
        assert briefing_day(db, at(DAY, 23, 40)) == DAY  # about 23:35 instead of 06:10 the next morning


# -- 2026-11-16 review ------------------------------------------------------------------------------------------------
BLOCK_PAGE = (b"<html><head><title>Request Rejected</title></head><body>The requested URL was rejected.</body></html>")


@pytest.mark.parametrize("content_type", ["text/html", "text/csv;charset=utf-8"])
def test_a_block_page_sent_with_200_is_a_refusal(engine, scene, content_type):
    """A WAF page with HTTP 200 (F5 style) is not a changed format to retry every 10 minutes: stop for the day."""
    scene.twse.body["STOCK_DAY_ALL"] = (BLOCK_PAGE, {"Content-Type": content_type})
    scene.run(at(DAY, 13, 40), at(DAY, 18, 0))
    assert scene.twse.times() == [at(DAY, 13, 45)]
    st = status(engine)
    assert st[closes.TWSE_REFUSED_KEY] == DAY and prices(engine) == {}
    assert tod.blocked(b"  <!DOCTYPE html>", None) and not tod.blocked(STOCK_DAY_ALL_CSV, "text/csv;charset=utf-8")


def test_a_relabelled_afternoon_file_is_stale_even_when_the_stored_volumes_are_final(engine, friday_stored,
                                                                                       monkeypatch):
    """Friday's row was replaced by the OpenAPI's final file (more volume: after-hours, odd lots); Friday's afternoon
    file relabelled as Monday still has every close equal: not stored."""
    monkeypatch.setattr(closes, "SAME_AS_BEFORE_MIN", 3)
    with Session(engine) as db:
        for q in parse_stock_day_all(tod.stock_day_all_rows(STOCK_DAY_ALL_CSV)).values():
            row = db.get(PriceDaily, (q.symbol, PREV)) or PriceDaily(symbol=q.symbol, date=PREV, source="twse-openapi")
            row.close, row.volume = q.price, (q.volume or 0) + 1000
            db.add(row)
        db.commit()
    twse = Twse(Clock(at(DAY, 14, 5)), published=at(DAY, 13, 0))
    assert poll(engine, twse, at(DAY, 14, 5)).prices == 0 and prices(engine) == {}


def test_the_listed_indices_have_their_own_expectation(engine, friday_in):
    """15:46 on 2026-11-16: STOCK_DAY_ALL came in, MI_INDEX answered 307 three seconds later — 加權指數 then waits for
    the next morning's batch (shioaji-data has no index), and tw.closes says so."""
    write_status(engine, twse_opendata_price=DAY, twse_opendata_refused=DAY)
    c = closes_at(engine, at(DAY, 15, 50))
    assert (c["TWSE"]["stored"], window(c["TWSE"])) == (True, (None, None))
    assert c["TWSE"]["index"] == {"stored": False, "latest": None, "expected_from": iso(TUE, 5, 20),
                                  "expected_to": iso(TUE, 5, 45)}
    with Session(engine) as db:
        db.add(DatasetStatus(key="twse-opendata/index", data_date=DAY, rows=1))
        db.commit()
    assert closes_at(engine, at(DAY, 15, 50))["TWSE"]["index"] == {"stored": True, "latest": "2026-11-16",
                                                                   "expected_from": None, "expected_to": None}
    assert closes_at(engine, at(DAY, 15, 50))["TPEX"]["index"] is None


def test_an_interim_market_still_gives_the_official_window(engine, friday_in):
    """The evening release has no ETFs: while a market is stored only as interim, an ETF of it still waits for the
    official file, so its window is given (the frontend shows it for a holding older than the session)."""
    write_status(engine, shioaji_data_interim_twse=DAY, shioaji_data_interim_tpex=DAY, twse_opendata_refused=DAY)
    c = closes_at(engine, at(DAY, 22, 0))
    assert (c["TWSE"]["stored"], c["TWSE"]["interim"], window(c["TWSE"])) == (True, True, (iso(TUE, 5, 20),
                                                                                          iso(TUE, 5, 45)))
    assert (c["TPEX"]["stored"], c["TPEX"]["interim"], window(c["TPEX"])) == (True, True, (iso(DAY, 23, 15),
                                                                                          iso(DAY, 23, 45)))
    assert window(closes_at(engine, at(TUE, 0, 30))["TPEX"]) == (None, None)  # its window has passed
    write_status(engine, tpex_openapi_price=DAY)
    assert window(closes_at(engine, at(DAY, 23, 40))["TPEX"]) == (None, None)  # official: nothing more expected


def test_interim_rows_the_official_file_has_no_close_for_are_dropped(engine, friday_stored):
    """A security in the evening release that did not trade (the official file has no close for it) keeps no
    stand-in row once the official file is in; the other market's interim rows stay."""
    with Session(engine) as db:
        archiver = Archiver(db, None)
        archiver.store_interim_closes({"6488.TWO": D("431.5"), "3105.TWO": D("100")}, DAY, "shioaji-data/interim_tpex")
        archiver.store_interim_closes({"2317.TW": D("218.5")}, DAY, "shioaji-data/interim_twse")
    tpex_row = {"Date": "1151116", "SecuritiesCompanyCode": "6488", "CompanyName": "環球晶", "Close": "431.50",
                "Change": "-13.50", "Open": "440.00", "High": "441.00", "Low": "430.00", "TradingShares": "1500000"}

    class TpexOpenApi:
        def get_json(self, url, params=None, headers=None):
            return [tpex_row] if url.endswith("tpex_mainboard_daily_close_quotes") else []

    with Session(engine) as db:
        Archiver(db, TpexOpenApi()).tpex_prices()
    stored = prices(engine)
    assert stored["6488.TWO"] == (D("431.50"), 1500000, "tpex-openapi") and "3105.TWO" not in stored
    assert stored["2317.TW"] == (D("218.5"), None, "shioaji-data")  # TWSE's official file is not in yet


def test_the_archives_interim_quote_is_not_filled_from_the_live_close_files(engine):
    """Close-only by nature: the live providers' files are an older session until the official one is archived, so
    asking them downloaded a whole close file for nothing."""
    from forliosa.marketdata.base import BaseProvider

    with Session(engine) as db:
        for sym, src in (("6488.TWO", "tpex-openapi"), ("2330.TW", "twse-openapi")):
            db.add(PriceDaily(symbol=sym, date=PREV, open=D("1"), high=D("1"), low=D("1"), close=D("1"), volume=1,
                              source=src))
        db.add(PriceDaily(symbol="6488.TWO", date=DAY, close=D("2"), source="shioaji-data"))
        db.add(PriceDaily(symbol="2330.TW", date=DAY, open=D("2"), high=D("2"), low=D("2"), close=D("2"), volume=5,
                          source="twse-opendata"))
        db.commit()
    asked = []

    class Live(BaseProvider):
        is_demo = False

        def __init__(self, name):
            self.name = name

        def quotes(self, symbols):
            asked.append((self.name, tuple(symbols)))
            return {}

    md = MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine)), Live("tpex_openapi"),
                     Live("shioaji_data")], policy="commercial")
    import forliosa.marketdata.archive_provider as ap

    ap_today = ap.today_taipei
    ap.today_taipei = lambda: DAY
    try:
        q = md.quotes(["6488.TWO", "2330.TW"], use_cache=False)
    finally:
        ap.today_taipei = ap_today
    assert asked == []
    assert (q["6488.TWO"].price, q["6488.TWO"].trade_date, q["6488.TWO"].open) == (D("2"), DAY, None)


def test_the_attributions_follow_the_switch(monkeypatch):
    from forliosa.config import get_settings
    from forliosa.datapolicy import attributions

    keys = {d["key"] for d in attributions("commercial")["datasets"]}
    assert {"twse-opendata/price", "twse-opendata/index"} <= keys
    monkeypatch.setenv("TWSE_OPENDATA_CLOSE", "false")
    get_settings.cache_clear()
    try:
        body = attributions("commercial")
        assert not any(d["key"].startswith("twse-opendata/") for d in body["datasets"])
        assert "兩個網址" not in body["not_used"][0]
    finally:
        monkeypatch.delenv("TWSE_OPENDATA_CLOSE")
        get_settings.cache_clear()


@pytest.mark.parametrize(("now", "start", "end", "text"), [
    (at(DAY, 13, 40), at(DAY, 14, 0), at(DAY, 14, 30), "下午 2:00–2:30"),
    (at(DAY, 14, 5), at(DAY, 14, 0), at(DAY, 14, 30), "下午 2:30 前"),
    (at(DAY, 15, 0), at(DAY, 20, 30), at(DAY, 23, 45), "今晚 8:30–11:45"),
    (at(DAY, 15, 0), at(TUE, 5, 20), at(TUE, 5, 45), "明天清晨 5:20–5:45"),
    (at(DAY, 23, 50), at(TUE, 0, 0), at(TUE, 1, 30), "半夜 12:00–1:30"),
    (at(TUE, 2, 0), at(TUE, 5, 20), at(TUE, 5, 45), "清晨 5:20–5:45"),
    (at(DAY, 15, 0), at(DAY, 23, 15), at(TUE, 1, 30), "今晚 11:15 到半夜 1:30"),
    (at(TUE, 6, 0), at(TUE, 5, 20), at(TUE, 5, 45), None),
])
def test_window_text_writes_times_like_the_screen(now, start, end, text):
    assert closes.window_text(start, end, now) == text
    if text:
        assert closes.expect_update(text) in (f"預計{text} 更新", f"預計{text}更新")
