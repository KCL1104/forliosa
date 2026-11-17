"""Guard: the Yahoo Finance history backfill (``yahoo-history``) is a chart and *reference* source only.

Product owner 2026-11-13 / 2026-11-17: its closes may draw charts and serve as the buy form's and the statement
import's reference close for days the archive lacks — never the ledger. With the backfill switched on and rows for
every day before the archive (at absurd prices, so any leak shows), the ledger's market value, P&L, performance and
the recurring plan's debit price still come from the official closes alone."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

from forliosa.config import get_settings
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import PriceDaily
from forliosa.services import recurring as rec
from forliosa.timeutil import last_tw_trading_day, today_taipei, tw_trading_days

API = "/api/v1"
YAHOO_PRICE = D(1)  # nobody's 2330 traded at NT$1: a number that cannot hide in a sum


@pytest.fixture()
def setup(client, engine, market, monkeypatch):
    monkeypatch.setenv("PRICE_HISTORY_SOURCE", "yahoo")
    get_settings.cache_clear()
    today = today_taipei()
    official = tw_trading_days(today - timedelta(days=25), today - timedelta(days=1))[-10:]
    yahoo = tw_trading_days(today - timedelta(days=120), official[0] - timedelta(days=1))
    with Session(engine) as db:
        db.add_all([PriceDaily(symbol="2330.TW", date=d, close=D(1000 + 10 * i), source="twse-openapi")
                    for i, d in enumerate(official)])
        db.add_all([PriceDaily(symbol="2330.TW", date=d, open=YAHOO_PRICE, high=YAHOO_PRICE, low=YAHOO_PRICE,
                               close=YAHOO_PRICE, volume=1, source="yahoo-history") for d in yahoo])
        db.commit()
    md = MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine)), DemoProvider()],
                    policy="commercial")
    set_market_data(md)
    acc = client.post(f"{API}/accounts", json={"name": "永豐", "currency": "TWD", "fee_discount": 0.28}).json()["id"]
    buy = last_tw_trading_day(today - timedelta(days=60))
    r = client.post(f"{API}/transactions", json={"account_id": acc, "symbol": "2330.TW", "type": "buy",
                                                 "trade_date": buy.isoformat(), "quantity": 1000, "price": 1000})
    assert r.status_code == 201, r.text
    yield {"md": md, "official": official, "yahoo": yahoo, "buy": buy}
    set_market_data(market)
    get_settings.cache_clear()


def test_the_rows_are_live_for_charts_and_the_reference_close(client, setup):
    # the guard below means something only if the rows are there and switched on
    ref = client.get(f"{API}/instruments/2330.TW/close", params={"date": setup["buy"].isoformat()}).json()
    assert (ref["close"], ref["reference"]) == (1.0, True)
    chart = client.get(f"{API}/instruments/2330.TW/history?range=6M").json()
    assert chart["candles"][0]["t"] == setup["yahoo"][0].isoformat()


def test_ledger_value_pnl_and_performance_ignore_the_backfill(client, setup):
    last = 1000 + 10 * (len(setup["official"]) - 1)
    holdings = client.get(f"{API}/portfolio/holdings").json()
    assert holdings[0]["price"] == float(last) and holdings[0]["market_value"] == 1000.0 * last
    p = client.get(f"{API}/portfolio/performance?range=6M").json()
    # starts on the first official close: no day of the backfill, no NT$1 market value anywhere
    assert p["start_date"] == setup["official"][0].isoformat()
    assert [pt["t"] for pt in p["series"]] == [d.isoformat() for d in setup["official"]]
    assert all(pt["market_value"] >= 1_000_000 for pt in p["series"])
    summary = client.get(f"{API}/portfolio/summary").json()
    assert summary["market_value"] == pytest.approx(1000.0 * last, rel=1e-6)
    assert summary["unrealized_pnl"] == pytest.approx(1000.0 * last - summary["cost_basis"], rel=1e-6)
    assert summary["unrealized_pnl"] > 0  # bought at 1,000, valued at the official close: a gain, never a 99.9 % loss


def test_recurring_debit_price_ignores_the_backfill(setup):
    md = setup["md"]
    assert rec.close_on(md, "2330.TW", setup["yahoo"][-1]) is None
    assert rec.close_on(md, "2330.TW", setup["official"][0])[0] == D(1000)
