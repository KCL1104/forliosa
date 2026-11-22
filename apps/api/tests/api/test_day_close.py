"""GET /instruments/{symbol}/close?date=: one day's close for the buy form's 「那天收盤」 hint — the official close from
our own archive (``prices_daily``), never a live request upstream. For a day the archive does not have, the Yahoo
Finance history backfill's close as a *reference* (``reference: true`` + ``note``; product owner 2026-11-17), only
while the backfill is switched on; the archive always wins."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

from forliosa.api.middleware import ViewAsMiddleware
from forliosa.config import get_settings
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import PriceDaily
from forliosa.services.reference_close import REFERENCE_NOTE
from forliosa.timeutil import today_taipei

API = "/api/v1"
OFFICIAL = {"reference": False, "note": None}
REFERENCE = {"reference": True, "note": REFERENCE_NOTE}
DAY = date(2026, 11, 12)  # a Thursday the archive has
YAHOO_DAY = date(2021, 3, 2)  # before the archive began: only the history backfill has it


def close(client, symbol: str, day: date | str):
    return client.get(f"{API}/instruments/{symbol}/close", params={"date": str(day)})


@pytest.fixture()
def archive(engine):
    with Session(engine) as db:
        db.add_all([
            PriceDaily(symbol="2330.TW", date=DAY, open=D(1070), high=D(1090), low=D(1065), close=D(1085),
                       volume=32_105_000, source="twse-openapi"),
            PriceDaily(symbol="6488.TWO", date=DAY, close=D("412.5"), source="tpex-openapi"),
            PriceDaily(symbol="2330.TW", date=YAHOO_DAY, close=D("600.5"), source="yahoo-history"),
            PriceDaily(symbol="2330.TW", date=DAY - timedelta(days=1), close=D(1080), source="finmind"),
        ])
        db.commit()


@pytest.fixture()
def backfill_on(monkeypatch):
    """PRICE_HISTORY_SOURCE=yahoo: the owner has switched the history backfill on (production)."""
    monkeypatch.setenv("PRICE_HISTORY_SOURCE", "yahoo")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("PRICE_HISTORY_SOURCE", raising=False)
    get_settings.cache_clear()


@pytest.fixture()
def no_upstream(monkeypatch, market):
    """Any market-data price read fails: the close must come from the database alone."""
    def boom(*_a, **_k):
        raise AssertionError("no upstream price read expected")

    for name in ("history", "quote", "quotes", "live_quotes"):
        monkeypatch.setattr(market, name, boom)


def test_close_of_an_archived_day(client, archive, no_upstream):
    r = close(client, "2330.TW", DAY)
    assert r.status_code == 200, r.text
    assert r.json() == {"symbol": "2330.TW", "date": "2026-11-12", "close": 1085.0, "currency": "TWD", **OFFICIAL}
    assert close(client, "2330", DAY).json()["symbol"] == "2330.TW"  # a bare code resolves like the other routes
    assert close(client, "6488.TWO", DAY).json()["close"] == 412.5


def test_no_row_for_that_day_is_null(client, archive, no_upstream):
    # a Sunday, a weekday with no row, long before the archive began, today (not archived yet)
    for day in (date(2026, 11, 8), date(2026, 11, 10), date(2019, 1, 2), today_taipei()):
        r = close(client, "2330.TW", day)
        assert r.status_code == 200, r.text
        assert r.json() == {"symbol": "2330.TW", "date": day.isoformat(), "close": None, "currency": "TWD",
                            **OFFICIAL}
    us = close(client, "AAPL", DAY).json()  # no archived closes for US stocks
    assert (us["close"], us["currency"], us["reference"]) == (None, "USD", False)


def test_the_history_backfill_is_read_only_while_switched_on(client, archive, no_upstream):
    # switched off (the default) or never run: the rows are not read, the hint stays empty as before
    r = close(client, "2330.TW", YAHOO_DAY)
    assert r.status_code == 200
    assert r.json() == {"symbol": "2330.TW", "date": YAHOO_DAY.isoformat(), "close": None, "currency": "TWD",
                        **OFFICIAL}


def test_a_day_before_the_archive_gets_the_backfill_close_as_a_reference(client, archive, no_upstream, backfill_on):
    r = close(client, "2330.TW", YAHOO_DAY)
    assert r.status_code == 200, r.text
    assert r.json() == {"symbol": "2330.TW", "date": YAHOO_DAY.isoformat(), "close": 600.5, "currency": "TWD",
                        **REFERENCE}
    assert REFERENCE_NOTE == "非官方資料"  # no vendor name on pages (產品負責人 2026-11-22)
    # the archive wins: an archived day is the official close, never a reference
    assert close(client, "2330.TW", DAY).json() == {"symbol": "2330.TW", "date": "2026-11-12", "close": 1085.0,
                                                     "currency": "TWD", **OFFICIAL}
    # neither has the day (a weekend, a day the backfill has no row for): nothing, as before
    for day in (date(2021, 3, 6), date(2019, 1, 2)):
        assert close(client, "2330.TW", day).json() == {"symbol": "2330.TW", "date": day.isoformat(), "close": None,
                                                         "currency": "TWD", **OFFICIAL}
    # US stocks: the backfill holds none, so nothing changes
    assert close(client, "AAPL", YAHOO_DAY).json()["close"] is None


def test_a_dropped_backfill_leaves_nothing_to_offer(client, archive, engine, backfill_on):
    from forliosa import history_backfill as hb

    assert close(client, "2330.TW", YAHOO_DAY).json()["reference"] is True
    with Session(engine) as db:
        assert hb.drop(db) == 1
    assert close(client, "2330.TW", YAHOO_DAY).json() == {"symbol": "2330.TW", "date": YAHOO_DAY.isoformat(),
                                                          "close": None, "currency": "TWD", **OFFICIAL}
    assert close(client, "2330.TW", DAY).json()["close"] == 1085.0  # official rows stay


def test_a_reference_before_a_known_split_is_the_price_as_traded(client, engine, backfill_on):
    """Yahoo's rows are split-adjusted (0050 before its 2025-06-18 1-to-4 split reads a quarter of what it traded at):
    the splits we know of between the day and the first official close are multiplied back."""
    with Session(engine) as db:
        db.add_all([
            PriceDaily(symbol="0050.TW", date=date(2024, 3, 1), close=D("35.6875"), source="yahoo-history"),
            PriceDaily(symbol="0050.TW", date=date(2025, 7, 1), close=D("50.05"), source="yahoo-history"),
            PriceDaily(symbol="0050.TW", date=DAY, close=D("61.25"), source="twse-openapi"),
        ])
        db.commit()
    before = close(client, "0050.TW", date(2024, 3, 1)).json()
    assert (before["close"], before["reference"]) == (142.75, True)  # 35.6875 × 4, as traded that day
    after = close(client, "0050.TW", date(2025, 7, 1)).json()
    assert (after["close"], after["reference"]) == (50.05, True)  # after the split: as stored
    assert close(client, "0050.TW", DAY).json()["reference"] is False


def test_commercial_policy_leaves_out_non_commercial_rows(client, archive, market):
    day = (DAY - timedelta(days=1)).isoformat()
    assert close(client, "2330.TW", day).json()["close"] == 1080.0  # personal opt-in: FinMind allowed
    set_market_data(MarketData([DemoProvider()], policy="commercial"))
    try:
        assert close(client, "2330.TW", day).json()["close"] is None
        assert close(client, "2330.TW", DAY).json()["close"] == 1085.0
    finally:
        set_market_data(market)


def test_bad_requests(client, archive):
    r = close(client, "2330.TW", today_taipei() + timedelta(days=1))
    assert r.status_code == 422 and r.json()["error"]["message"] == "日期不能晚於今天"
    for bad in ("2026-13-01", "20261112", "yesterday", ""):
        r = close(client, "2330.TW", bad)
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "validation_error"
    assert client.get(f"{API}/instruments/2330.TW/close").status_code == 422  # date is required
    r = close(client, "9999XX", DAY)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_signed_in_only_and_no_user_data(app, client):
    from fastapi.testclient import TestClient

    assert TestClient(app).get(f"{API}/instruments/2330.TW/close", params={"date": "2026-11-12"}).status_code == 401
    # it reads no user data: under read-only viewing the header is ignored, like the other price routes
    assert ViewAsMiddleware(None, API).classify("GET", f"{API}/instruments/2330.TW/close") == "ignore"
