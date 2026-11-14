"""GET /instruments/{symbol}/close?date=: one day's official close for the buy form's 「那天收盤」 hint — from our own
archive (``prices_daily``) only: never the Yahoo Finance history backfill (charts only, never the ledger) and never a
live request upstream."""

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
from forliosa.timeutil import today_taipei

API = "/api/v1"
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
def no_upstream(monkeypatch, market):
    """Any market-data price read fails: the close must come from the database alone."""
    def boom(*_a, **_k):
        raise AssertionError("no upstream price read expected")

    for name in ("history", "quote", "quotes", "live_quotes"):
        monkeypatch.setattr(market, name, boom)


def test_close_of_an_archived_day(client, archive, no_upstream):
    r = close(client, "2330.TW", DAY)
    assert r.status_code == 200, r.text
    assert r.json() == {"symbol": "2330.TW", "date": "2026-11-12", "close": 1085.0, "currency": "TWD"}
    assert close(client, "2330", DAY).json()["symbol"] == "2330.TW"  # a bare code resolves like the other routes
    assert close(client, "6488.TWO", DAY).json()["close"] == 412.5


def test_no_row_for_that_day_is_null(client, archive, no_upstream):
    # a Sunday, a weekday with no row, long before the archive began, today (not archived yet)
    for day in (date(2026, 11, 8), date(2026, 11, 10), date(2019, 1, 2), today_taipei()):
        r = close(client, "2330.TW", day)
        assert r.status_code == 200, r.text
        assert r.json() == {"symbol": "2330.TW", "date": day.isoformat(), "close": None, "currency": "TWD"}
    us = close(client, "AAPL", DAY).json()  # no archived closes for US stocks
    assert (us["close"], us["currency"]) == (None, "USD")


@pytest.mark.parametrize("opted_in", [False, True])
def test_the_history_backfill_is_never_read(client, archive, monkeypatch, opted_in):
    # Yahoo's rows are for charts only (product owner 2026-11-13), even where the owner switched the backfill on
    if opted_in:
        monkeypatch.setenv("PRICE_HISTORY_SOURCE", "yahoo")
    get_settings.cache_clear()
    try:
        r = close(client, "2330.TW", YAHOO_DAY)
        assert r.status_code == 200
        assert r.json() == {"symbol": "2330.TW", "date": YAHOO_DAY.isoformat(), "close": None, "currency": "TWD"}
    finally:
        monkeypatch.delenv("PRICE_HISTORY_SOURCE", raising=False)
        get_settings.cache_clear()


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
