"""US closes from Databento (``forliosa.us_prices``; 產品負責人 2026-11-15): the backfill and the daily update against a
fake Databento, serving them (quotes stamped 16:00 New York, history, notes, has_quote), a US holding valued at the
close × the central bank rate, the market page's US row, Taiwan-only day lookups, and the worker's hourly schedule."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa import us_prices
from forliosa.config import get_settings
from forliosa.marketdata import databento
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.http import HttpFetcher, RateLimiter
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import DatasetStatus, PriceBackfill, PriceDaily, WatchlistItem
from forliosa.services import market_overview
from forliosa.services.coverage import series_notes
from forliosa.timeutil import iso_taipei, last_us_session

API = "/api/v1"
HEADER = "ts_event,rtype,publisher_id,instrument_id,open,high,low,close,volume,symbol\n"


def bar(day: str, symbol: str, close: str) -> str:
    return f"{day}T00:00:00.000000000Z,35,90,1,{close},{close},{close},{close},1000,{symbol}\n"


class FakeDatabento:
    """``metadata.get_dataset_range`` answers ``end`` (exclusive); ``timeseries.get_range`` answers the bars of the
    requested symbols inside the requested range (Databento spelling, e.g. BRK.B)."""

    def __init__(self, end: str, bars: dict[str, list[tuple[str, str]]]):
        self.end, self.bars = end, bars
        self.calls: list[httpx.Request] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        if req.url.path.endswith("metadata.get_dataset_range"):
            return httpx.Response(200, json={"schema": {"ohlcv-1d": {"start": "2024-07-01T00:00:00Z",
                                                                       "end": f"{self.end}T00:00:00Z"}}})
        p = req.url.params
        syms = p["symbols"].split(",")
        known = [s for s in syms if s in self.bars]
        if not known:
            return httpx.Response(422, json={"detail": {"case": "symbology_invalid_request"}})
        body = HEADER + "".join(bar(d, s, c) for s in known for d, c in self.bars[s] if p["start"] <= d < p["end"])
        unknown = [s for s in syms if s not in self.bars]
        headers = {"X-Warning": f'["Warning: ... symbols which did not resolve: {", ".join(unknown)}."]'} \
            if unknown else {}
        return httpx.Response(206 if unknown else 200, text=body, headers=headers)

    def fetcher(self) -> HttpFetcher:
        client = httpx.Client(transport=httpx.MockTransport(self.handler), auth=("db-test", ""))
        return HttpFetcher(client=client, retries=0, extra_allowed=(databento.API,), limiter=RateLimiter())

    def ranges(self) -> list[httpx.Request]:
        return [c for c in self.calls if c.url.path.endswith("timeseries.get_range")]


@pytest.fixture()
def db(engine):
    with Session(engine) as s:
        yield s


def watch(db: Session, *symbols: str) -> None:
    from forliosa.models import User

    db.add(User(id="usr_w", email="w@example.com", display_name="w", preferences={}))
    for i, s in enumerate(symbols):
        db.add(WatchlistItem(id=f"wl_{i}", user_id="usr_w", symbol=s))
    db.commit()


def closes(db: Session, symbol: str) -> list[tuple[date, D]]:
    return [(r.date, r.close) for r in db.scalars(select(PriceDaily).where(PriceDaily.symbol == symbol)
                                                  .order_by(PriceDaily.date))]


# -- backfill and the daily update ------------------------------------------------------------------------------
def test_backfill_then_update_store_unadjusted_closes_in_our_spelling(db):
    watch(db, "AAPL", "BRK-B", "ZZZZQ", "2330.TW")
    fake = FakeDatabento("2026-11-13", {
        "AAPL": [("2024-07-01", "216.75"), ("2026-11-11", "355.63"), ("2026-11-12", "354.88"),
                 ("2026-11-13", "356.27")],
        "BRK.B": [("2026-11-12", "589.83")],
        "SPY": [("2026-11-12", "757.12")], "DIA": [("2026-11-12", "470.00")], "ONEQ": [("2026-11-12", "88.10")]})
    assert us_prices.pending(db) == ["SPY", "DIA", "ONEQ", "AAPL", "BRK-B", "ZZZZQ"]  # the market ETFs first

    res = us_prices.backfill(db, fake.fetcher())
    assert (res.asked, res.stored, res.not_found, res.remaining) == (6, 5, ["ZZZZQ"], 0)
    get = fake.ranges()[0]
    assert get.url.params["symbols"] == "SPY,DIA,ONEQ,AAPL,BRK.B,ZZZZQ"  # Databento spelling on the wire
    # Databento has through 11/12 (its range end 11/13 is exclusive): the request asks up to 11/13, exclusive
    assert get.url.params["start"] == "2024-07-01" and get.url.params["end"] == "2026-11-13"
    assert closes(db, "BRK-B") == [(date(2026, 11, 12), D("589.8300"))]  # our spelling in the archive
    assert [d for d, _ in closes(db, "AAPL")] == [date(2024, 7, 1), date(2026, 11, 11), date(2026, 11, 12)]
    assert {r.source for r in db.scalars(select(PriceDaily))} == {"databento-equs"}
    rows = {r.symbol: r for r in db.scalars(select(PriceBackfill))}
    assert (rows["AAPL"].status, rows["AAPL"].first_date, rows["ZZZZQ"].status) == ("done", date(2024, 7, 1),
                                                                                  "not_found")
    assert us_prices.stored_through(db) == date(2026, 11, 12)

    # nothing new at Databento: only the free range call, no data bought
    n = len(fake.calls)
    assert us_prices.update(db, fake.fetcher()).skipped and len(fake.calls) == n + 1

    # the next session appears: the done symbols get it (re-reading the last few sessions)
    fake.end = "2026-11-14"
    res = us_prices.update(db, fake.fetcher())
    assert (res.stored, res.skipped) == (date(2026, 11, 13), False)
    assert "ZZZZQ" not in fake.ranges()[-1].url.params["symbols"]
    assert closes(db, "AAPL")[-1] == (date(2026, 11, 13), D("356.2700"))
    assert us_prices.stored_through(db) == date(2026, 11, 13)


def test_a_refusal_blocks_the_backfill_and_nothing_is_marked(db):
    watch(db, "AAPL")

    def refuse(req: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"detail": {"case": "insufficient_credit"}})

    client = httpx.Client(transport=httpx.MockTransport(refuse), auth=("db-test", ""))
    fetcher = HttpFetcher(client=client, retries=0, extra_allowed=(databento.API,), limiter=RateLimiter())
    res = us_prices.backfill(db, fetcher)
    assert res.blocked and res.asked == 0
    assert db.scalar(select(PriceBackfill)) is None  # asked again once the owner fixed the key or the credit


def test_the_yahoo_backfill_cli_never_touches_the_us_progress(db):
    from forliosa import history_backfill as hb

    db.add(PriceBackfill(symbol="AAPL", source="databento-equs", status="done", attempts=1))
    db.add(PriceDaily(symbol="AAPL", date=date(2026, 11, 13), close=D("356.27"), source="databento-equs"))
    db.commit()
    hb.drop(db)
    assert db.get(PriceBackfill, "AAPL") is not None and closes(db, "AAPL")
    assert "done" not in hb.summary(db)


# -- serving ----------------------------------------------------------------------------------------------------
@pytest.fixture()
def us_md(engine, monkeypatch):
    # US_PRICE_SOURCE=databento: the data policy reads and credits the rows (the provider flag decides per facade)
    monkeypatch.setattr(get_settings(), "us_price_source", "databento")
    with Session(engine) as s:
        for d, c in (("2026-11-12", "354.88"), ("2026-11-13", "356.27")):
            s.add(PriceDaily(symbol="AAPL", date=date.fromisoformat(d), close=D(c), source="databento-equs"))
        s.add(PriceDaily(symbol="2330.TW", date=date(2026, 11, 13), close=D("1085"), source="twse-openapi"))
        s.commit()

    def make(on: bool) -> MarketData:
        return MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine), us_prices=on),
                           DemoProvider()], policy="commercial")
    return make


def test_us_closes_are_served_only_when_switched_on(us_md):
    on, off = us_md(True), us_md(False)
    q = on.quote("AAPL")
    assert (q.price, q.prev_close, q.trade_date, q.is_demo) == (D("356.2700"), D("354.8800"), date(2026, 11, 13), False)
    assert iso_taipei(q.as_of) == "2026-11-14T05:00:00+08:00"  # 16:00 New York (standard time) = 05:00 Taipei
    info = on.instrument("AAPL")
    assert on.has_quote(info) and not off.has_quote(info)
    assert on.history("AAPL", date(2026, 11, 1), date(2026, 11, 13)).candles[-1].c == D("356.2700")
    assert off.history("AAPL", date(2026, 11, 1), date(2026, 11, 13)).candles == []
    # a range before the first close says where the closes begin, not 「美股沒有報價」
    assert series_notes(on, "AAPL", date(2021, 11, 13), date(2026, 11, 12)) == ["資料從 2026/11/12 開始"]
    assert series_notes(off, "AAPL", date(2021, 11, 13), None) == ["美股沒有報價"]
    from forliosa.datapolicy import allowed_sources

    assert "databento-equs" in allowed_sources("commercial")
    # the Taiwan archive's start is not moved by US rows; a US symbol without rows has no start
    assert on.archive_since() == date(2026, 11, 13) and on.archive_since("MSFT") is None


def test_a_us_holding_is_valued_at_the_close_and_the_rate(client, engine, us_md, monkeypatch):
    from forliosa.marketdata.cbc import PAIR
    from forliosa.marketdata.cbc import SOURCE as CBC
    from forliosa.models import FxRate

    with Session(engine) as s:
        s.add(FxRate(pair=PAIR, date=date(2026, 11, 13), rate=D("32.889"), source=CBC))
        s.add(FxRate(pair=PAIR, date=date(2026, 11, 3), rate=D("32.76"), source=CBC))
        s.commit()
    md = us_md(True)
    set_market_data(md)
    monkeypatch.setattr(get_settings(), "us_price_source", "databento")
    r = client.post(f"{API}/accounts", json={"name": "Firstrade", "broker": "Firstrade", "currency": "USD"})
    r = client.post(f"{API}/transactions", json={"account_id": r.json()["id"], "symbol": "AAPL", "type": "buy",
                                                 "trade_date": "2026-11-03", "quantity": 10, "price": 200})
    assert r.status_code == 201, r.text
    h = client.get(f"{API}/portfolio/holdings").json()[0]
    assert (h["price"], h["prev_close"], h["price_date"]) == (356.27, 354.88, "2026-11-13")
    assert h["market_value"] == pytest.approx(10 * 356.27 * 32.889, abs=0.01)
    quote = client.get(f"{API}/instruments/AAPL/quote").json()
    assert (quote["trade_date"], quote["as_of"]) == ("2026-11-13", "2026-11-14T05:00:00+08:00")


# -- market page ------------------------------------------------------------------------------------------------
def test_market_page_us_row_and_taiwan_only_day_lookups(client, engine, monkeypatch):
    market_overview.clear_cache()
    monkeypatch.setattr(get_settings(), "us_price_source", "databento")
    with Session(engine) as s:
        for sym, rows in {"SPY": [("2026-11-12", "757.12"), ("2026-11-13", "754.37")],
                          "DIA": [("2026-11-13", "470.00")],
                          "AAPL": [("2026-11-10", "350.00")]}.items():  # 11/10: a US-only date between Taiwan days
            for d, c in rows:
                s.add(PriceDaily(symbol=sym, date=date.fromisoformat(d), close=D(c), source="databento-equs"))
        for d, c in (("2026-11-09", "1000"), ("2026-11-11", "1010")):
            s.add(PriceDaily(symbol="2330.TW", date=date.fromisoformat(d), close=D(c), volume=5000,
                             source="twse-openapi"))
        s.commit()
    md = MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine), us_prices=True),
                     DemoProvider()], policy="commercial")
    set_market_data(md)
    o = client.get(f"{API}/market/overview").json()
    us = o["us"]
    assert us["date"] == "2026-11-13" and [i["symbol"] for i in us["items"]] == ["SPY", "DIA"]
    spy = us["items"][0]
    assert (spy["name"], spy["tracks"], spy["unit"], spy["value"]) == ("SPDR S&P 500 ETF Trust", "S&P 500", "美元",
                                                                       754.37)
    assert spy["change"] == pytest.approx(-2.75) and len(spy["sparkline"]) == 2
    assert any("Databento" in s for s in o["sources"])
    assert o["movers"]["date"] == "2026-11-11" and o["movers"]["prev_date"] == "2026-11-09"  # not the US-only 11/10
    assert o["as_of"] != "2026-11-13"  # the US date does not become the page's (Taiwan) date

    set_market_data(MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine), us_prices=False),
                                DemoProvider()], policy="commercial"))
    market_overview.clear_cache()
    assert client.get(f"{API}/market/overview").json()["us"] is None


# -- the worker's schedule --------------------------------------------------------------------------------------
def test_us_closes_are_asked_an_hour_after_the_close_then_hourly(monkeypatch):
    from forliosa.worker import Worker

    monkeypatch.setattr(get_settings(), "us_price_source", "databento")
    monkeypatch.setattr(get_settings(), "databento_api_key", SecretStr("db-test"))
    w = Worker(md=object())  # type: ignore[arg-type]
    names = {j.name: j for j in w.jobs}
    assert names["us_closes"].background and names["us_backfill"].background
    due = names["us_closes"].due
    # Friday 2026-11-13: the close is 16:00 New York = 05:00 Saturday Taipei; first ask at 06:00 Taipei
    assert not due(datetime(2026, 11, 13, 21, 59, tzinfo=UTC), None)  # 05:59 Taipei
    assert due(datetime(2026, 11, 13, 22, 0, tzinfo=UTC), None)  # 06:00 Taipei
    first = datetime(2026, 11, 13, 22, 0, tzinfo=UTC)
    assert not due(datetime(2026, 11, 13, 22, 30, tzinfo=UTC), first)  # hourly
    assert due(datetime(2026, 11, 13, 23, 0, tzinfo=UTC), first)
    w._us_stored = date(2026, 11, 13)  # stored: nothing more until the next session
    assert not due(datetime(2026, 11, 14, 3, 0, tzinfo=UTC), first)
    w._us_stored = None
    assert not due(datetime(2026, 11, 14, 19, 0, tzinfo=UTC), first)  # given up 20 hours later
    # summer time: 16:00 New York = 04:00 Taipei, so the first ask is 05:00 Taipei
    assert last_us_session(datetime(2026, 7, 9, 20, 59, tzinfo=UTC), after=__import__("datetime").timedelta(hours=1)) \
        == date(2026, 7, 8)
    assert last_us_session(datetime(2026, 7, 9, 21, 0, tzinfo=UTC), after=__import__("datetime").timedelta(hours=1)) \
        == date(2026, 7, 9)


def test_off_without_the_switch_or_the_key(monkeypatch):
    from forliosa.worker import Worker

    monkeypatch.setattr(get_settings(), "us_price_source", "databento")
    monkeypatch.setattr(get_settings(), "databento_api_key", None)
    assert "us_closes" not in {j.name for j in Worker(md=object()).jobs}  # type: ignore[arg-type]
    assert get_settings().us_prices_served and not get_settings().us_prices_enabled
    us_prices.set_http(us_prices._UNSET)
    assert us_prices.http() is None
    assert DatasetStatus  # imported for the status key's table


def test_switched_off_the_rows_are_neither_read_nor_credited(engine, monkeypatch):
    from forliosa.datapolicy import allowed_sources, attributions

    monkeypatch.setattr(get_settings(), "us_price_source", "")
    assert "databento-equs" not in allowed_sources("commercial")
    assert not [d for d in attributions("commercial")["datasets"] if d["key"].startswith("databento-equs")]
    monkeypatch.setattr(get_settings(), "us_price_source", "databento")
    assert [d["key"] for d in attributions("commercial")["datasets"] if d["key"].startswith("databento")] == [
        "databento-equs/price"]


# -- splits (unadjusted closes) ---------------------------------------------------------------------------------
def test_splits_are_found_from_the_open_and_folded_into_charts_only():
    from forliosa.marketdata.archive_provider import detect_splits
    from forliosa.marketdata.base import Candle, CorporateEvent
    from forliosa.services.instruments import split_adjusted

    d = date
    rows = [(d(2024, 7, 11), D("1700"), D("1720.0")), (d(2024, 7, 12), D("1715"), D("1710.0")),
            (d(2024, 7, 15), D("171.5"), D("168.0")),  # AVGO-like 10-for-1: opens at a tenth of the close
            (d(2024, 7, 16), D("168"), D("84.5")),  # a 50 % crash during the day: not a split (the open did not gap)
            (d(2024, 7, 17), D("42.9"), D("43.0"))]  # opens near half of 84.5 but 1.5 % off: not taken for 2-for-1
    assert detect_splits(rows) == [(d(2024, 7, 15), D(10))]
    assert detect_splits([(d(2025, 1, 2), D("2"), D("2.0")), (d(2025, 1, 3), D("40.2"), D("39.0"))]) == [
        (d(2025, 1, 3), D(1) / 20)]  # 1-for-20 reverse split

    candles = [Candle(d(2024, 7, 12), D("1715"), D("1720"), D("1700"), D("1710"), 100),
               Candle(d(2024, 7, 15), D("171.5"), D("172"), D("166"), D("168"), 1000)]
    adj, notes = split_adjusted(candles, [CorporateEvent("AVGO", d(2024, 7, 15), "split", D(10))])
    assert (adj[0].c, adj[0].v, adj[1].c) == (D("171"), 1000, D("168"))
    assert notes == ["2024/07/15 股票分割（1 股拆成 10 股），之前的價格已經換算"]


# -- review fixes (2026-11-15) ----------------------------------------------------------------------------------
def test_a_backfill_does_not_make_the_update_skip_the_other_symbols(db):
    watch(db, "AAPL")
    fake = FakeDatabento("2026-11-13", {
        "AAPL": [("2026-11-11", "355.63"), ("2026-11-12", "354.88"), ("2026-11-13", "356.27")],
        "SPY": [("2026-11-12", "757.12"), ("2026-11-13", "754.37")], "DIA": [("2026-11-12", "470")],
        "ONEQ": [("2026-11-12", "88")], "NVDA": [("2026-11-12", "190"), ("2026-11-13", "191")]})
    us_prices.backfill(db, fake.fetcher())
    assert us_prices.stored_through(db) == date(2026, 11, 12)
    fake.end = "2026-11-14"  # Databento posts 11/13 …
    from forliosa.models import WatchlistItem as W

    db.add(W(id="wl_new", user_id="usr_w", symbol="NVDA"))  # … and someone adds NVDA before the hourly update
    db.commit()
    assert us_prices.backfill(db, fake.fetcher()).stored == 1
    assert us_prices.stored_through(db) == date(2026, 11, 12)  # the backfill does not move the progress
    res = us_prices.update(db, fake.fetcher())
    assert not res.skipped and res.stored == date(2026, 11, 13)
    assert closes(db, "AAPL")[-1][0] == date(2026, 11, 13) and closes(db, "SPY")[-1][0] == date(2026, 11, 13)


def test_a_symbol_tracked_again_gets_the_sessions_it_missed(db):
    watch(db, "TSLA")
    days = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10",
            "2026-11-11", "2026-11-12", "2026-11-13"]
    fake = FakeDatabento("2026-11-04", {s: [(d, "100") for d in days] for s in ("TSLA", "SPY", "DIA", "ONEQ")})
    us_prices.backfill(db, fake.fetcher())
    item = db.scalar(select(WatchlistItem).where(WatchlistItem.symbol == "TSLA"))
    db.delete(item)
    db.commit()
    for end in ("2026-11-10", "2026-11-14"):  # nobody tracks TSLA while the sessions go on
        fake.end = end
        us_prices.update(db, fake.fetcher())
    assert db.get(PriceBackfill, "TSLA").status == "untracked"
    db.add(WatchlistItem(id="wl_back", user_id="usr_w", symbol="TSLA"))
    db.commit()
    assert us_prices.pending(db) == ["TSLA"]
    us_prices.backfill(db, fake.fetcher())
    assert [d.isoformat() for d, _ in closes(db, "TSLA")] == days  # no gap


def test_a_split_day_quote_is_measured_from_the_converted_close(engine, monkeypatch):
    monkeypatch.setattr(get_settings(), "us_price_source", "databento")
    from forliosa.timeutil import today_taipei

    t = today_taipei()  # the archive quote reads the last three weeks
    with Session(engine) as s:
        for back, o, c in ((3, "1700", "1720"), (2, "1715", "1710"), (1, "171.5", "168")):  # 1 share → 10 on the last
            s.add(PriceDaily(symbol="AVGO", date=t - timedelta(days=back), open=D(o), close=D(c),
                             source="databento-equs"))
        s.commit()
    md = MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine), us_prices=True),
                     DemoProvider()], policy="commercial")
    from forliosa.services.instruments import quote_out

    q = md.quotes(["AVGO"])["AVGO"]
    assert (q.prev_close, q.reference_price) == (D("1710.0000"), D("171.0000"))
    out = quote_out(q)
    assert out["change_pct"] == pytest.approx(168 / 171 - 1, abs=1e-4)  # −1.75 %, not −90 %


def test_a_bad_key_on_the_first_request_pauses_the_backfill(db):
    watch(db, "AAPL")

    def refuse(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": {"case": "auth_invalid"}})

    client = httpx.Client(transport=httpx.MockTransport(refuse), auth=("db-test", ""))
    fetcher = HttpFetcher(client=client, retries=0, extra_allowed=(databento.API,), limiter=RateLimiter())
    res = us_prices.backfill(db, fetcher)
    assert res.blocked and res.asked == 0 and db.scalar(select(PriceBackfill)) is None


def test_a_gap_in_the_rows_is_not_taken_for_a_split():
    from forliosa.marketdata.archive_provider import detect_splits

    rows = [(date(2026, 9, 1), D("30"), D("30")), (date(2026, 11, 2), D("10"), D("10.1"))]  # two months apart
    assert detect_splits(rows) == []
    reverse = [(date(2025, 1, 2), D("2"), D("2.0")), (date(2025, 1, 3), D("12.1"), D("12.0"))]  # 1-for-6
    from forliosa.marketdata.base import Candle
    from forliosa.services.instruments import split_adjusted

    (d, r), = detect_splits(reverse)
    _, notes = split_adjusted([Candle(date(2025, 1, 2), D(2), D(2), D(2), D(2), 300),
                               Candle(date(2025, 1, 3), D(12), D(12), D(12), D(12), 50)],
                              [type("E", (), {"date": d, "kind": "split", "ratio": r})()])
    assert notes == ["2025/01/03 股票分割（6 股合成 1 股），之前的價格已經換算"]


def test_the_why_line_names_a_split_and_the_52_weeks_are_converted(engine, monkeypatch):
    from forliosa.services import stock
    from forliosa.timeutil import today_taipei

    monkeypatch.setattr(get_settings(), "us_price_source", "databento")
    t = today_taipei()
    with Session(engine) as s:
        for back, o, c in ((3, "1700", "1720"), (2, "1715", "1710"), (1, "171.5", "168")):
            s.add(PriceDaily(symbol="NVDA", date=t - timedelta(days=back), open=D(o), high=D(o), low=D(c), close=D(c),
                             volume=1000, source="databento-equs"))
        s.commit()
    md = MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine), us_prices=True),
                     DemoProvider()], policy="commercial")
    with Session(engine) as db:
        w = stock.why(db, md, "NVDA")
        o = stock.overview(db, md, "NVDA")
    split = [r for r in w["reasons"] if r["kind"] == "split"]
    assert split and "1 股拆成 10 股" in split[0]["text"] and "171.00" in split[0]["text"]
    assert not [r for r in w["reasons"] if r["kind"] == "ex_dividend"]
    assert o["high_52w"] == pytest.approx(171.5)  # 1715 before the split, in today's shares (not 1715)
