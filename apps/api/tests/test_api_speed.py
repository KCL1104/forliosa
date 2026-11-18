"""API speed (2026-11-17): batched archive reads give the same answers as one-by-one reads, the ledger endpoints' SQL
statements no longer grow with the number of holdings, and the caches added for speed stay correct."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, last_notice_run, notices_trusted_since, set_market_data
from forliosa.models import (
    DatasetStatus,
    DividendResolution,
    ExRightsResult,
    FxRate,
    MarketEvent,
    PriceDaily,
)
from forliosa.timeutil import TAIPEI, today_taipei, tw_trading_days

API = "/api/v1"
TW = ["2330.TW", "2317.TW", "2454.TW", "2303.TW", "2308.TW", "2382.TW", "2412.TW", "2881.TW", "2882.TW", "3711.TW",
      "6488.TWO"]
US = ["AAPL", "NVDA", "VOO", "QQQ", "SPY"]
TODAY = today_taipei()
DAYS = tw_trading_days(TODAY - timedelta(days=70), TODAY - timedelta(days=1))


def _bars(symbol: str, days: list[date], source: str, base: float) -> list[PriceDaily]:
    out = []
    for i, d in enumerate(days):
        px = D(str(round(base * (1 + 0.004 * ((i * 7) % 11 - 5)), 2)))
        out.append(PriceDaily(symbol=symbol, date=d, open=px, high=px + 1, low=px - 1, close=px, volume=1000 + i,
                              source=source))
    return out


@pytest.fixture()
def archive(engine, market, monkeypatch):
    """A commercial facade over a small archive: 11 Taiwan stocks and 5 US symbols with ~45 sessions of closes, a yahoo
    backfill before them for two symbols, ex-dividend notices (some coming this week), TPEx's computed amounts, board
    resolutions and USD/TWD rates. US closes are served (US_PRICE_SOURCE=databento)."""
    from forliosa.config import get_settings

    monkeypatch.setenv("US_PRICE_SOURCE", "databento")
    get_settings.cache_clear()
    with Session(engine) as db:
        for n, s in enumerate(TW):
            db.add_all(_bars(s, DAYS, "tpex-openapi" if s.endswith(".TWO") else "twse-openapi", 50 + 40 * n))
        for n, s in enumerate(US):
            db.add_all(_bars(s, [d for d in DAYS if d.weekday() < 5], "databento-equs", 100 + 20 * n))
        for s in ("2330.TW", "2317.TW"):  # the history backfill: charts only
            db.add_all(_bars(s, tw_trading_days(DAYS[0] - timedelta(days=40), DAYS[0] - timedelta(days=1)),
                             "yahoo-history", 30))
        soon = [d for d in tw_trading_days(TODAY + timedelta(days=1), TODAY + timedelta(days=12))]
        for i, s in enumerate(TW[:6]):
            db.add(MarketEvent(key=f"exd-{s}", symbol=s, date=soon[i % len(soon)], type="ex_dividend",
                               title="除息", data={"cash": str(1 + i), "stock_ratio": "0"},
                               source="tpex-openapi" if s.endswith(".TWO") else "twse-openapi"))
            db.add(MarketEvent(key=f"old-{s}", symbol=s, date=DAYS[5], type="ex_dividend", title="除權息",
                               data={"cash": "", "stock_ratio": "0.05"}, source="twse-openapi"))
        db.add(ExRightsResult(symbol="6488.TWO", date=DAYS[5], kind="除息", reference_price=D(400), limit_up=D(440),
                              limit_down=D(360), cash_dividend=D("2.5"), stock_dividend=D(0), source="tpex-openapi"))
        db.add(DividendResolution(symbol="2330.TW", period_start=date(TODAY.year, 1, 1), seq=1,
                                  period_end=date(TODAY.year, 3, 31), dividend_year=TODAY.year,
                                  period=f"{TODAY.year}Q1",
                                  board_date=soon[0] - timedelta(days=60), meeting_date=None, progress="董事會決議",
                                  cash_earnings=D(1), cash_legal_reserve=D(0), cash_capital_surplus=D(0),
                                  stock_earnings=D(0), stock_legal_reserve=D(0), stock_capital_surplus=D(0),
                                  published=soon[0] - timedelta(days=59), source="twse-openapi"))
        for i, d in enumerate(DAYS):
            db.add(FxRate(pair="USDTWD", date=d, rate=D("31.5") + D(i) / 100, source="cbc-opendata"))
        for key in ("twse-openapi/price", "tpex-openapi/price"):
            db.add(DatasetStatus(key=key, data_date=DAYS[-1], rows=1, fetched_at=datetime.now(UTC)))
        db.commit()
    md = MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine), us_prices=True),
                     DemoProvider()], policy="commercial")
    set_market_data(md)
    yield md
    set_market_data(market)


# -- batched reads = one-by-one reads --------------------------------------------------------------------------------
def test_dividends_many_equals_dividends_one_by_one(archive):
    symbols = [*TW, *US, "9999.TW"]
    many = archive.dividends_many(symbols)
    for s in symbols:
        one = archive.dividends(s)
        assert many[s] == one, s
    assert any(a.value for a in many.values())  # the fixture has dividends at all
    sub = archive.dividends_many(["2330.TW", "AAPL"])  # the answer does not depend on the others asked with it
    assert sub["2330.TW"] == many["2330.TW"] and sub["AAPL"] == many["AAPL"]


@pytest.mark.parametrize("backfill", [False, True])
def test_histories_equal_history_one_by_one(archive, backfill, monkeypatch):
    from forliosa.config import get_settings

    monkeypatch.setenv("PRICE_HISTORY_SOURCE", "yahoo")  # the backfill's rows are readable at all (charts)
    get_settings.cache_clear()
    symbols = [*TW, *US, "9999.TW"]
    start, end = DAYS[0] - timedelta(days=60), TODAY
    many = archive.histories(symbols, start, end, backfill=backfill)
    for s in symbols:
        assert many[s] == archive.history(s, start, end, backfill=backfill), s
    yahoo = {c.t for c in many["2330.TW"].candles} - set(DAYS)
    assert bool(yahoo) is backfill  # the backfill's days only for charts
    assert "yahoo-history" in many["2330.TW"].source if backfill else "yahoo-history" not in many["2330.TW"].source


def test_archived_rows_remember_their_sources_per_symbol(archive):
    archive.histories(["2330.TW", "6488.TWO", "AAPL"], DAYS[0], TODAY)
    p = archive.providers[0]
    assert p.sources_for("history", "6488.TWO") == ["tpex-openapi"]
    assert p.sources_for("history", "AAPL") == ["databento-equs"]


# -- the ledger's statements do not grow with its holdings -----------------------------------------------------------
class Statements:
    def __init__(self, engine):
        self.n = 0
        event.listen(engine, "after_cursor_execute", self._count)
        self.engine = engine

    def _count(self, *_a, **_k):
        self.n += 1

    def measure(self, fn) -> int:
        before = self.n
        fn()
        return self.n - before

    def close(self):
        event.remove(self.engine, "after_cursor_execute", self._count)


def _buy(client, account, symbols):
    rows = [{"symbol": s, "type": "buy", "trade_date": DAYS[2].isoformat(), "quantity": 10, "price": 50}
            for s in symbols]
    r = client.post(f"{API}/transactions/batch", json={"account_id": account, "dry_run": False, "rows": rows})
    assert r.status_code == 201, r.text


@pytest.mark.parametrize("path", ["/portfolio/summary", "/portfolio/allocation", "/portfolio/upcoming?days=30",
                                  "/portfolio/performance?range=ALL", "/portfolio/performance?range=1M&benchmark=0050",
                                  "/watchlist", "/ai/suggestions?route=/"])
def test_ledger_statements_do_not_grow_with_holdings(engine, client, archive, path):
    account = client.post(f"{API}/accounts", json={"name": "永豐", "currency": "TWD"}).json()["id"]
    us_account = client.post(f"{API}/accounts", json={"name": "複委託", "currency": "USD"}).json()["id"]
    _buy(client, account, TW[:2])
    for s in TW[:2]:
        client.post(f"{API}/watchlist", json={"symbol": s})
    counter = Statements(engine)
    try:
        client.get(f"{API}{path}")  # caches warm (instrument master, quotes) like a running server
        few = counter.measure(lambda: client.get(f"{API}{path}"))
        _buy(client, account, TW[2:])
        _buy(client, us_account, US)
        for s in [*TW[2:], *US]:
            client.post(f"{API}/watchlist", json={"symbol": s})
        client.get(f"{API}{path}")
        many = counter.measure(lambda: client.get(f"{API}{path}"))
    finally:
        counter.close()
    # 2 -> 16 holdings / watched symbols (11 Taiwan, 5 US): before 2026-11-17 each added symbol cost 3–4 statements
    assert many <= few + 3, (few, many)
    assert many <= 20, many


def _group_board(client) -> str:
    r = client.post(f"{API}/groups", json={"name": "家族投資"})
    assert r.status_code == 201, r.text
    return f"/groups/{r.json()['id']}/leaderboard?period=year"


@pytest.mark.parametrize("path", ["/portfolio/performance?range=ALL", "/portfolio/performance?range=1Y&benchmark=0050",
                                  "leaderboard"])
def test_reference_closes_before_the_archive_do_not_grow_the_statements(engine, client, archive, monkeypatch, path):
    """產品負責人 2026-11-18: a ledger older than the archive is valued before it with the history backfill's closes.
    Bought before the archive's first day, with Yahoo rows for every Taiwan holding: the performance page stays
    within the speed work's numbers above, and the group board adds a constant few statements (the backfill's first
    day and one read of every member's and 0050's rows, ``sharing.Projector.prime``) whatever the number of
    holdings."""
    from forliosa.config import get_settings

    before = tw_trading_days(DAYS[0] - timedelta(days=40), DAYS[0] - timedelta(days=1))
    with Session(engine) as db:
        for n, s in enumerate(TW):
            if s not in ("2330.TW", "2317.TW"):  # (the fixture's two already have them)
                db.add_all(_bars(s, before, "yahoo-history", 50 + 40 * n))
        db.add_all(_bars("0050.TW", before, "yahoo-history", 60))
        db.add_all(_bars("0050.TW", DAYS, "twse-openapi", 62))
        db.commit()
    account = client.post(f"{API}/accounts", json={"name": "永豐", "currency": "TWD"}).json()["id"]
    us_account = client.post(f"{API}/accounts", json={"name": "複委託", "currency": "USD"}).json()["id"]

    def buy(acc: str, symbols: list[str], day: date = before[5]) -> None:
        rows = [{"symbol": s, "type": "buy", "trade_date": day.isoformat(), "quantity": 10, "price": 50}
                for s in symbols]
        r = client.post(f"{API}/transactions/batch", json={"account_id": acc, "dry_run": False, "rows": rows})
        assert r.status_code == 201, r.text

    buy(account, TW[:2])
    url = _group_board(client) if path == "leaderboard" else path
    counts: dict[bool, tuple[int, int]] = {}
    for on in (False, True):
        monkeypatch.setenv("PRICE_HISTORY_SOURCE", "yahoo" if on else "")
        get_settings.cache_clear()
        counter = Statements(engine)
        try:
            client.get(f"{API}{url}")  # caches warm (instrument master, quotes, the archive's start)
            few = counter.measure(lambda: client.get(f"{API}{url}"))
            if not on:
                buy(account, TW[2:])
                buy(us_account, US, DAYS[2])  # (no US closes before the archive: bought after it began)
            client.get(f"{API}{url}")
            many = counter.measure(lambda: client.get(f"{API}{url}"))
        finally:
            counter.close()
        counts[on] = (few, many)
    few, many = counts[True]
    referenced = client.get(f"{API}{url}").json()
    assert referenced["reference_until"] == before[-1].isoformat()  # the backfill was really used
    assert many <= few + 3, counts
    if path == "leaderboard":
        assert many <= counts[False][1] + 3, counts  # the board: a constant few more, not one per holding
    else:
        assert many <= 20, counts


def test_the_board_reads_every_member_s_reference_closes_at_once(engine, app, client, other_client, archive,
                                                                 monkeypatch):
    """2026-11-18 review: the board read each member's backfill rows on its own (2 + one per member, 2330 read once
    per member holding it). Now every member's holdings and the stock benchmark are read together
    (``sharing.Projector.prime``): the backfill reads stay the same from one member to three, and the board stays
    within a constant few statements of the board with the backfill off."""
    from forliosa.config import get_settings
    from tests.api.m5 import SHARE_DEFAULT, join, login, make_group

    before = tw_trading_days(DAYS[0] - timedelta(days=40), DAYS[0] - timedelta(days=1))
    with Session(engine) as db:
        for n, s in enumerate(TW):
            if s not in ("2330.TW", "2317.TW"):  # (the fixture's two already have them)
                db.add_all(_bars(s, before, "yahoo-history", 50 + 40 * n))
        db.add_all(_bars("0050.TW", before, "yahoo-history", 60))
        db.add_all(_bars("0050.TW", DAYS, "twse-openapi", 62))
        db.commit()

    def buy(who, symbols: list[str]) -> None:
        acc = who.post(f"{API}/accounts", json={"name": "永豐", "currency": "TWD"}).json()["id"]
        rows = [{"symbol": s, "type": "buy", "trade_date": before[5].isoformat(), "quantity": 10, "price": 50}
                for s in symbols]
        r = who.post(f"{API}/transactions/batch", json={"account_id": acc, "dry_run": False, "rows": rows})
        assert r.status_code == 201, r.text

    third = login(app, "third@forliosa.local", "老三")
    buy(client, TW[:4])
    buy(other_client, TW[2:6])
    buy(third, ["2330.TW", *TW[6:9]])
    gid = make_group(client)["id"]
    url = f"{API}/groups/{gid}/leaderboard?period=year"

    def measure(on: bool) -> tuple[int, int]:
        monkeypatch.setenv("PRICE_HISTORY_SOURCE", "yahoo" if on else "")
        get_settings.cache_clear()
        backfill: list[str] = []

        def count(_conn, _cursor, statement, parameters, *_a):
            if "yahoo-history" in str(parameters):
                backfill.append(statement)

        client.get(url)  # caches warm (instrument master, quotes, the archive's start)
        counter = Statements(engine)
        event.listen(engine, "before_cursor_execute", count)
        try:
            total = counter.measure(lambda: client.get(url))
        finally:
            event.remove(engine, "before_cursor_execute", count)
            counter.close()
        return total, len(backfill)

    one = measure(True)
    join(client, other_client, gid, SHARE_DEFAULT)
    join(client, third, gid, SHARE_DEFAULT)
    off, three = measure(False), measure(True)
    board = client.get(url).json()
    assert board["reference_until"] == before[-1].isoformat() and len(board["entries"]) == 3
    assert all(e["return_pct"] is not None for e in board["entries"])
    assert three[1] == one[1], (one, three)  # the backfill reads do not grow with the members
    assert three[0] <= off[0] + 3, (off, three)


def test_upcoming_recurring_only_is_the_recurring_part_of_upcoming(client, archive):
    account = client.post(f"{API}/accounts", json={"name": "永豐", "currency": "TWD"}).json()["id"]
    _buy(client, account, TW[:3])
    r = client.post(f"{API}/recurring", json={"account_id": account, "symbol": "2330", "amount": 3000,
                                              "day_of_month": list(range(1, 29))})
    assert r.status_code == 201, r.text
    full = client.get(f"{API}/portfolio/upcoming?days=30").json()
    only = client.get(f"{API}/portfolio/upcoming?days=30&types=recurring").json()
    assert only and only == [u for u in full if u["type"] == "recurring"]
    assert any(u["type"] != "recurring" for u in full)
    assert client.get(f"{API}/portfolio/upcoming?days=999&types=recurring").status_code == 422
    assert client.get(f"{API}/portfolio/upcoming?days=7&types=dividends").status_code == 422
    assert client.get(f"{API}/portfolio/upcoming?days=7&types=recurring&account_id=acc_nope").status_code == 404


def test_transaction_counts(client, archive):
    account = client.post(f"{API}/accounts", json={"name": "永豐", "currency": "TWD"}).json()["id"]
    assert client.get(f"{API}/transactions/counts").json() == {"transactions": 0, "dividends": 0, "by_type": {}}
    _buy(client, account, TW[:3])
    r = client.post(f"{API}/transactions", json={"account_id": account, "symbol": "2330", "type": "cash_dividend",
                                                 "trade_date": DAYS[-1].isoformat(), "amount": 100})
    assert r.status_code == 201, r.text
    counts = client.get(f"{API}/transactions/counts").json()
    listed = client.get(f"{API}/transactions?limit=200").json()["items"]
    assert counts["transactions"] == len(listed)
    assert counts["dividends"] == sum(1 for t in listed if t["type"] in ("cash_dividend", "stock_dividend"))
    assert counts["by_type"]["buy"] == 3


def test_an_import_reads_each_stocks_notices_once(engine, client, archive, monkeypatch):
    calls: list[tuple[str, ...]] = []
    provider = archive.providers[0]
    one, many = provider.dividends, provider.dividends_many
    monkeypatch.setattr(provider, "dividends", lambda s: calls.append((s,)) or one(s))
    monkeypatch.setattr(provider, "dividends_many", lambda syms: calls.append(tuple(syms)) or many(syms))
    account = client.post(f"{API}/accounts", json={"name": "永豐", "currency": "TWD"}).json()["id"]
    rows = [{"symbol": s, "type": "buy", "trade_date": DAYS[2].isoformat(), "quantity": 10, "price": 50}
            for s in TW[:5] * 4]
    r = client.post(f"{API}/transactions/batch", json={"account_id": account, "dry_run": False, "rows": rows})
    assert r.status_code == 201, r.text
    asked = [s for c in calls for s in c]
    assert sorted(asked) == sorted(TW[:5]), calls  # one batch read, nothing asked again by the later checks


# -- weekends and holidays trust the last scheduled archive run ----------------------------------------------------
def _taipei(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=TAIPEI)


@pytest.mark.parametrize(("now", "stored", "trusted"), [
    ("2026-11-21T10:00", "2026-11-20T21:45", True),  # Saturday morning: Friday evening's run
    ("2026-11-22T20:00", "2026-11-20T21:45", True),  # Sunday evening
    ("2026-11-23T08:00", "2026-11-20T21:45", True),  # Monday before the 08:10 run
    ("2026-11-23T08:20", "2026-11-20T21:45", True),  # Monday, the 08:10 run still running
    ("2026-11-23T10:30", "2026-11-20T21:45", False),  # Monday: the 08:10 run never stored anything
    ("2026-11-18T15:00", "2026-11-17T21:45", False),  # a weekday whose 08:10 run was missed: live files as before
    ("2026-11-18T09:30", "2026-11-17T21:45", True),  # the 12-hour rule as before
    ("2026-10-11T12:00", "2026-10-08T21:45", True),  # 2026-10-09/10 closed (國慶 bridge) and the weekend
])
def test_notices_trust_the_last_scheduled_run(now, stored, trusted):
    assert (_taipei(stored) >= notices_trusted_since(_taipei(now))) is trusted


def test_last_notice_run_is_a_trading_days_slot():
    assert last_notice_run(_taipei("2026-11-21T10:00")) == _taipei("2026-11-20T21:40")
    assert last_notice_run(_taipei("2026-11-18T14:39")) == _taipei("2026-11-18T08:10")
    assert last_notice_run(_taipei("2026-11-18T14:40")) == _taipei("2026-11-18T14:40")


# -- the archive's own connection pool ----------------------------------------------------------------------------
def test_the_archive_reads_on_a_pool_of_its_own(engine):
    from forliosa.db import archive_session_factory, session_factory
    from forliosa.marketdata.archive_provider import _default_session

    with _default_session() as db:
        assert db.get_bind() is not engine and db.get_bind().url == engine.url
    assert archive_session_factory() is archive_session_factory()  # one pool, not one per call
    assert session_factory().kw["bind"] is engine


def test_a_pool_timeout_does_not_cool_the_archive_down(engine):
    """A pool timeout leaves the archive off cool-down, but it did not answer: the live notice files are asked in that
    call, even though the archive's notice runs are recent (they would otherwise be skipped as already answered)."""
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    from forliosa.marketdata.base import BaseProvider, DividendEvent

    with Session(engine) as db:
        for key in ("twse-openapi/price", "tpex-openapi/price"):
            db.add(DatasetStatus(key=key, data_date=DAYS[-1], rows=1, fetched_at=datetime.now(UTC)))
        db.commit()
    ex_day = DAYS[-1] + timedelta(days=3)

    class Busy(ArchiveProvider):
        def dividends_many(self, symbols):
            raise PoolTimeout("QueuePool limit of size 5 overflow 10 reached")

        def ex_rights_on(self, symbols, d):
            raise PoolTimeout("QueuePool limit of size 5 overflow 10 reached")

    class Broken(ArchiveProvider):
        def dividends_many(self, symbols):
            raise RuntimeError("database gone")

    class LiveTwse(BaseProvider):  # TWT48U_ALL / TWT84U
        name = "twse_openapi"

        def dividends(self, symbol):
            return [DividendEvent(symbol, ex_day.year, str(ex_day.year), D(5), D(0), ex_day, None)]

        def ex_rights_on(self, symbols, d):
            return {s: (D(95), D(5)) for s in symbols}

    def facade(archive_cls):
        return MarketData([archive_cls("commercial", session_fn=lambda: Session(engine)), LiveTwse()],
                          policy="commercial")

    healthy = facade(ArchiveProvider)  # the archive answered (nothing archived) and its notices are recent
    assert healthy.dividends("2330.TW").value == [] and healthy._provider_map("ex_rights_on", ["2330.TW"], ex_day) == {}
    busy = facade(Busy)
    got = busy.dividends("2330.TW").value
    assert [(e.ex_dividend_date, e.cash_dividend) for e in got] == [(ex_day, D(5))]
    assert busy._provider_map("ex_rights_on", ["2330.TW"], ex_day) == {"2330.TW": (D(95), D(5))}
    assert "archive" not in busy._down_until  # no cool-down: the next call asks the archive again
    broken = facade(Broken)
    assert len(broken.dividends("2330.TW").value) == 1 and "archive" in broken._down_until  # a real failure: as before


def test_archive_start_is_remembered_but_not_its_absence(engine):
    calls = []

    class Counting(ArchiveProvider):
        def first_date(self, symbol=None, backfill=False):
            calls.append(symbol)
            return super().first_date(symbol, backfill)

    md = MarketData([Counting("commercial", session_fn=lambda: Session(engine))], policy="commercial")
    assert md.archive_since() is None and md.archive_since() is None and len(calls) == 2  # nothing archived yet
    with Session(engine) as db:
        db.add_all(_bars("2330.TW", DAYS[3:6], "twse-openapi", 100))
        db.add_all(_bars("2330.TW", DAYS[:3], "yahoo-history", 100))
        db.commit()
    assert md.archive_since() == DAYS[3] and md.archive_since() == DAYS[3] and len(calls) == 3
    direct = ArchiveProvider("commercial", session_fn=lambda: Session(engine)).first_date(None)
    assert direct == DAYS[3]


# -- caches stay correct ----------------------------------------------------------------------------------------------
def test_us_split_detection_is_kept_until_the_series_changes(engine, monkeypatch):
    from forliosa.config import get_settings

    monkeypatch.setenv("US_PRICE_SOURCE", "databento")
    get_settings.cache_clear()
    p = ArchiveProvider("commercial", session_fn=lambda: Session(engine), us_prices=True)
    days = [d for d in DAYS if d.weekday() < 5]
    with Session(engine) as db:
        db.add_all(_bars("NVDA", days[:20], "databento-equs", 100))
        db.commit()
    assert p.corporate_events("NVDA") is None
    with Session(engine) as db:  # a new close: a 10-for-1 split
        prev = db.get(PriceDaily, ("NVDA", days[19])).close
        px = prev / 10
        db.add(PriceDaily(symbol="NVDA", date=days[20], open=px, high=px, low=px, close=px, volume=1_010 * 10,
                          source="databento-equs"))
        db.commit()
    events = p.corporate_events("NVDA")
    assert events and events[0].date == days[20] and events[0].ratio == 10


def test_related_company_pool_follows_the_archive(engine):
    from forliosa import perfcache
    from forliosa.models import CompanyProfile
    from forliosa.services import related

    md = MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine))], policy="commercial")
    with Session(engine) as db:
        db.add(CompanyProfile(symbol="2330.TW", date=DAYS[-1], industry_code="24", industry="半導體業",
                              shares_outstanding=100, values={"short_name": "台積電"}, source="twse-openapi"))
        db.add(DatasetStatus(key="twse-openapi/company", data_date=DAYS[-1], rows=1, fetched_at=datetime.now(UTC)))
        db.commit()
        assert set(related._company_pool(db, md)) == {"2330.TW"}
        db.add(CompanyProfile(symbol="2303.TW", date=DAYS[-1], industry_code="24", industry="半導體業",
                              shares_outstanding=50, values={"short_name": "聯電"}, source="twse-openapi"))
        db.commit()
        assert set(related._company_pool(db, md)) == {"2330.TW"}  # the archive has not run since: kept
        db.merge(DatasetStatus(key="twse-openapi/company", data_date=DAYS[-1], rows=2,
                               fetched_at=datetime.now(UTC) + timedelta(seconds=1)))
        db.commit()
        assert set(related._company_pool(db, md)) == {"2330.TW", "2303.TW"}  # an archive run: read again
    perfcache.clear_all()


def test_shioaji_parsed_files_are_evicted_least_recently_used_first(tmp_path):
    from forliosa.marketdata import shioaji_data
    from forliosa.marketdata.shioaji_data import ShioajiDataProvider

    p = ShioajiDataProvider("https://example.invalid", tmp_path)
    for i in range(shioaji_data.PARSED_MAX):
        p._parsed_put(f"k{i}", i)
    assert p._parsed_get("k0") == 0  # used: now the newest
    p._parsed_put("new", -1)
    assert p._parsed_get("k1") is shioaji_data._MISSING and p._parsed_get("k0") == 0 and p._parsed_get("new") == -1
    assert len(p._parsed) == shioaji_data.PARSED_MAX


def test_an_expired_master_answers_while_it_is_rebuilt_in_the_background():
    import time

    class Catalog(DemoProvider):
        name = "catalog"
        calls = 0

        def instruments(self):
            Catalog.calls += 1
            return super().instruments()

    md = MarketData([Catalog()], policy="commercial")
    first = md.master()
    md._master_until = time.monotonic() - 1  # expired a second ago
    assert md.master() is first  # answered at once, rebuilt behind it
    deadline = time.monotonic() + 5
    while (md._master_refreshing or Catalog.calls < 2) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert Catalog.calls == 2 and md.master() is not first


# -- streams give their pooled connection back -------------------------------------------------------------------------
def test_a_quote_stream_returns_its_connection_off_the_event_loop(client, engine, market, monkeypatch):
    """The sign-in check's session goes back to the pool before the stream's first quotes (not when the stream ends),
    and in the thread pool: returning a connection rolls back on the database, a round trip the event loop must not
    wait for."""
    import asyncio

    checked_out, checkins = [], []
    real_quotes = market.live_quotes

    def live_quotes(symbols):
        checked_out.append(engine.pool.checkedout())
        return real_quotes(symbols)

    def on_checkin(_dbapi_conn, _record):
        try:
            asyncio.get_running_loop()
            checkins.append("event loop")
        except RuntimeError:
            checkins.append("worker thread")

    monkeypatch.setattr(market, "live_quotes", live_quotes)
    event.listen(engine, "checkin", on_checkin)
    try:
        with client.stream("GET", f"{API}/stream/quotes", params={"symbols": "2330.TW", "once": "true"}) as r:
            assert r.status_code == 200 and "event: quote" in "".join(r.iter_text())
    finally:
        event.remove(engine, "checkin", on_checkin)
    assert checked_out == [0]
    assert checkins and set(checkins) == {"worker thread"}, checkins


# -- gc.freeze --------------------------------------------------------------------------------------------------------
def test_the_heap_is_frozen_once_at_start_up_not_after_master_rebuilds(monkeypatch):
    import threading
    import time

    from forliosa import perf
    from forliosa.api import app as app_module

    freezes = []
    monkeypatch.setattr(perf, "freeze_heap", lambda: freezes.append(1))
    md = MarketData([DemoProvider()], policy="commercial")
    monkeypatch.setattr(app_module, "get_market_data", lambda: md)
    app_module.warm_up_in_background()
    for t in threading.enumerate():
        if t.name == "warm-up":
            t.join(10)
    assert freezes == [1] and md._master is not None
    md._master_until = time.monotonic() - 1
    md._flight.do("master", md._rebuild_master)  # the hourly rebuild: no freeze while requests are in flight
    assert freezes == [1]


def test_freezing_again_releases_what_the_last_freeze_pinned():
    """An object alive at a freeze that later joins a reference cycle is never collected while frozen; a later
    ``freeze_heap`` unfreezes first, so the cycle is collected then instead of being frozen again."""
    import gc
    import weakref

    from forliosa import perf

    class Node:
        other: object = None

    try:
        in_flight = Node()
        perf.freeze_heap()
        late = Node()
        in_flight.other, late.other = late, in_flight
        ref = weakref.ref(in_flight)
        del in_flight, late
        gc.collect()
        assert ref() is not None  # frozen: the collector skips it
        perf.freeze_heap()
        assert ref() is None
    finally:
        gc.unfreeze()


# -- the slow-request log, compression -------------------------------------------------------------------------------
def test_slow_request_log_names_the_route_template_only(client, archive, caplog, monkeypatch):
    from forliosa import perf

    monkeypatch.setattr(perf, "DEFAULT_SLOW_MS", 0.0)
    monkeypatch.setenv("SLOW_REQUEST_MS", "0")
    from fastapi.testclient import TestClient

    from forliosa.api.app import create_app

    c = TestClient(create_app())
    c.cookies = client.cookies
    with caplog.at_level(logging.INFO, logger="forliosa.perf"):
        r = c.get(f"{API}/instruments/2330.TW/history", params={"range": "1M"})
        assert r.status_code == 200
        c.get(f"{API}/no/such/path?secret=1")
    lines = [rec.getMessage() for rec in caplog.records if rec.getMessage().startswith("slow_request")]
    assert any("route=/api/v1/instruments/{symbol}/history status=200" in x for x in lines), lines
    assert any("route=unmatched status=404" in x for x in lines), lines
    text = "\n".join(lines)
    assert "2330" not in text and "range" not in text and "secret" not in text
    hist = next(x for x in lines if "{symbol}/history" in x)
    assert int(hist.split("queries=")[1].split()[0]) > 0


def test_a_long_stream_is_not_a_slow_request(client, archive, caplog, monkeypatch):
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse
    from fastapi.testclient import TestClient

    from forliosa.perf import SlowRequestMiddleware

    app = FastAPI()

    @app.get("/s")
    def stream():
        import time

        def gen():
            yield "data: a\n\n"
            time.sleep(0.3)
            yield "data: b\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    app.add_middleware(SlowRequestMiddleware, threshold_ms=200)
    with caplog.at_level(logging.INFO, logger="forliosa.perf"):
        assert TestClient(app).get("/s").status_code == 200
    assert not [r for r in caplog.records if r.getMessage().startswith("slow_request")]


def test_json_is_gzipped_and_streams_are_not(client, archive):
    for s in TW:
        client.post(f"{API}/watchlist", json={"symbol": s})
    r = client.get(f"{API}/watchlist", headers={"accept-encoding": "gzip"})
    assert r.status_code == 200 and r.headers.get("content-encoding") == "gzip" and len(r.json()) == len(TW)
    s = client.get(f"{API}/stream/quotes", params={"symbols": "2330.TW", "once": "true"},
                   headers={"accept-encoding": "gzip"})
    assert s.status_code == 200 and "content-encoding" not in s.headers


# -- the write paths merged after the speed work (刪除這檔, 清除所有持倉, 匯入庫存, 匯入對帳單) -----------------------
# The speed work keeps no ledger across requests: every summary / holdings / upcoming / performance / counts read
# replays the stored rows. Its only write-side cache is the request's ex-dividend notices (``auto_dividends.
# shared_events``), dropped by ``lock_accounts``. These tests read the ledger first (everything a running server would
# have warm), write through each newer path, and read again: the answer is the new state, every time.
def _ledger(client) -> dict:
    holdings = client.get(f"{API}/portfolio/holdings").json()
    summary = client.get(f"{API}/portfolio/summary").json()
    upcoming = client.get(f"{API}/portfolio/upcoming?days=30").json()
    recurring = client.get(f"{API}/portfolio/upcoming?days=30&types=recurring").json()
    counts = client.get(f"{API}/transactions/counts").json()
    series = client.get(f"{API}/portfolio/performance?range=ALL").json().get("series") or []
    held = {h["symbol"]: h["quantity"] for h in holdings}
    value = sum(h["market_value"] or 0 for h in holdings)
    # the summary is the same ledger as the holdings: a stale one would disagree
    assert summary["market_value"] == pytest.approx(value, abs=0.01), (summary["market_value"], value)
    return {"held": held, "value": value, "records": counts["transactions"],
            "ex_dividends": {u["symbol"] for u in upcoming if u["type"] == "ex_dividend"},
            "debits": {u["symbol"] for u in recurring}, "last_value": series[-1]["market_value"] if series else 0}


def _positions(client, account: str, rows: list[dict], day: date | None = None) -> dict:
    """匯入庫存's write: one buy per row on ``day`` (default today, Taipei: after every stored ex-dividend notice)."""
    r = client.post(f"{API}/imports/positions/commit",
                    json={"account_id": account, "rows": rows, **({"trade_date": day.isoformat()} if day else {})})
    assert r.status_code == 201, r.text
    return r.json()


def test_reads_after_each_newer_write_are_fresh(client, archive):
    a = client.post(f"{API}/accounts", json={"name": "永豐", "currency": "TWD"}).json()["id"]
    b = client.post(f"{API}/accounts", json={"name": "國泰", "currency": "TWD"}).json()["id"]
    empty = _ledger(client)
    assert empty["held"] == {} and empty["records"] == 0

    # 匯入對帳單 (the statement import writes through POST /transactions/batch)
    _buy(client, a, TW[:3])
    r = client.post(f"{API}/recurring", json={"account_id": a, "symbol": TW[0], "amount": 3000,
                                              "day_of_month": list(range(1, 29))})
    assert r.status_code == 201, r.text
    now = _ledger(client)
    assert now["held"] == dict.fromkeys(TW[:3], 10) and now["value"] > 0 and now["last_value"] > 0
    assert now["ex_dividends"] == set(TW[:3]) and now["debits"] == {TW[0]} and now["records"] >= 3

    # 匯入庫存 into the other account: a new stock
    _positions(client, b, [{"symbol": TW[3], "quantity": 2000, "price": 60}])
    before, now = now, _ledger(client)
    assert now["held"] == {**before["held"], TW[3]: 2000} and now["value"] > before["value"]
    assert now["ex_dividends"] == set(TW[:4]) and now["records"] > before["records"]

    # 匯入庫存 「以券商為準」: the stock's records in that account replaced
    res = _positions(client, a, [{"symbol": TW[1], "quantity": 300, "price": 55, "replace": True}])
    assert res["replaced"][0]["symbol"] == TW[1] and res["replaced"][0]["deleted"] >= 1
    before, now = now, _ledger(client)
    assert now["held"] == {**before["held"], TW[1]: 300} and now["value"] != before["value"]

    # 刪除這檔
    r = client.delete(f"{API}/accounts/{a}/holdings/{TW[2]}")
    assert r.status_code == 200, r.text
    before, now = now, _ledger(client)
    assert now["held"] == {s: q for s, q in before["held"].items() if s != TW[2]}
    assert TW[2] not in now["ex_dividends"] and now["records"] < before["records"]

    # 清除所有持倉, one account, pausing its 定期定額: the recurring-only 本週事項 (AI panel) follows
    r = client.delete(f"{API}/portfolio/records", params={"account_id": a, "pause_plans": "true"})
    assert r.status_code == 200 and r.json()["plans_paused"] == 1, r.text
    before, now = now, _ledger(client)
    assert now["held"] == {TW[3]: 2000} and now["debits"] == set() and now["ex_dividends"] == {TW[3]}

    # 清除所有持倉, every account
    r = client.delete(f"{API}/portfolio/records", params={"all_accounts": "true"})
    assert r.status_code == 200, r.text
    now = _ledger(client)
    assert now["held"] == {} and now["value"] == 0 and now["records"] == 0 and now["ex_dividends"] == set()


def _notice_reads(archive, monkeypatch) -> list[str]:
    """Every symbol whose ex-dividend notices the archive is asked for from now on."""
    asked: list[str] = []
    provider = archive.providers[0]
    one, many = provider.dividends, provider.dividends_many
    monkeypatch.setattr(provider, "dividends", lambda s: asked.append(s) or one(s))
    monkeypatch.setattr(provider, "dividends_many", lambda syms: asked.extend(syms) or many(syms))
    return asked


def test_a_positions_import_reads_each_stocks_notices_once(client, archive, monkeypatch):
    """Like the statement import (``test_an_import_reads_each_stocks_notices_once``): the check, the strict replay and
    the re-sync of 匯入庫存 share one read per stock, replaced stocks included."""
    account = client.post(f"{API}/accounts", json={"name": "永豐", "currency": "TWD"}).json()["id"]
    _buy(client, account, TW[:2])
    asked = _notice_reads(archive, monkeypatch)
    res = _positions(client, account, [{"symbol": s, "quantity": 1000, "price": 50, "replace": s in TW[:2]}
                                       for s in TW[:5]], DAYS[2])  # before a stock dividend: the sync books it
    assert [x["symbol"] for x in res["replaced"]] == sorted(TW[:2])
    assert sorted(asked) == sorted(TW[:5]), asked


def test_deleting_a_holding_reads_its_stocks_notices_at_most_once(client, archive, monkeypatch):
    """刪除這檔 re-syncs one stock of one account once, under ``after_user_change``'s own cache: at most one read of
    that stock's notices, and none of the account's other stocks. That holds with or without its ``shared_events``
    decorator (kept for a consistent pattern), so this test bounds the reads; it does not detect the decorator — only
    ``test_a_positions_import_reads_each_stocks_notices_once`` fails when 匯入庫存's is removed (25 reads, not 5)."""
    account = client.post(f"{API}/accounts", json={"name": "永豐", "currency": "TWD"}).json()["id"]
    _buy(client, account, TW[:3])
    asked = _notice_reads(archive, monkeypatch)
    assert client.delete(f"{API}/accounts/{account}/holdings/{TW[0]}").status_code == 200
    assert set(asked) <= {TW[0]} and len(asked) <= 1, asked
