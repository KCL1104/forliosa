"""DATA_POLICY=commercial (the default): never demo data; short archives give empty series with a note."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

from forliosa.archive import Archiver
from forliosa.config import Settings
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import PriceDaily, RecurringPlan, Transaction, User
from forliosa.seed import DEMO_EMAIL, seed
from forliosa.timeutil import last_tw_trading_day, today_taipei, tw_trading_days
from tests.archive.fakes import NOW, FakeFetcher

API = "/api/v1"


def test_default_policy_is_commercial(monkeypatch):
    monkeypatch.delenv("DATA_POLICY", raising=False)
    assert Settings(_env_file=None).data_policy == "commercial"
    assert MarketData([DemoProvider()]).policy == "commercial"
    assert ArchiveProvider().policy == "commercial"


@pytest.fixture()
def commercial(engine, market):
    """Commercial facade over the archive (live fixtures: one trading day, 2026-11-11) and the catalog."""
    with Session(engine) as db:
        Archiver(db, FakeFetcher(), "commercial", now_fn=lambda: NOW).run(["twse", "tpex"])
    md = MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine)), DemoProvider()],
                    policy="commercial")
    set_market_data(md)
    yield md
    set_market_data(market)


def make_account(client):
    r = client.post(f"{API}/accounts", json={"name": "永豐", "currency": "TWD", "fee_discount": 0.28})
    return r.json()["id"]


def test_history_and_valuation_never_fall_back_to_demo(client, commercial):
    h = client.get(f"{API}/instruments/2330/history?range=1M").json()
    assert [(c["t"], c["c"]) for c in h["candles"]] == [("2026-11-11", 2395.0)]  # real, but short
    assert h["is_demo"] is False and h["notes"] == ["資料累積中：自 2026-11-11 起存檔"]
    assert not any("示範" in s for s in h["sources"])
    us = client.get(f"{API}/instruments/AAPL/history?range=1M").json()
    assert us["candles"] == [] and us["notes"] == ["美股目前沒有可商用的行情來源，不提供價格資料"]
    v = client.get(f"{API}/instruments/2330/valuation?range=1Y").json()
    assert v["is_demo"] is False and "資料累積中：自 2026-11-11 起存檔" in v["notes"]
    assert len(v["series"]) <= 1
    assert client.get(f"{API}/instruments/AAPL/quote").status_code == 404  # no quote rather than a demo one
    assert client.get(f"{API}/instruments/2330/dividends").json() == []  # no demo dividend history
    detail = client.get(f"{API}/instruments/AAPL").json()
    assert detail["is_demo"] is False  # the catalog still names the instrument


def test_personal_mode_is_unchanged(client):
    h = client.get(f"{API}/instruments/2330/history?range=1M").json()
    assert h["is_demo"] is True and len(h["candles"]) > 15 and h["notes"] == []


def test_performance_waits_for_the_archive(client, commercial):
    acc = make_account(client)
    buy = last_tw_trading_day(today_taipei() - timedelta(days=60)).isoformat()
    r = client.post(f"{API}/transactions", json={"account_id": acc, "symbol": "2330.TW", "type": "buy",
                                                 "trade_date": buy, "quantity": 1000, "price": 1000})
    assert r.status_code == 201, r.text
    p = client.get(f"{API}/portfolio/performance?range=1Y").json()
    assert p["series"] == [] and p["twr"] is None and p["is_demo"] is False
    assert p["notes"] and p["notes"][0].startswith("資料累積中：自 2026-11-11 起存檔")
    holdings = client.get(f"{API}/portfolio/holdings").json()
    assert holdings[0]["is_demo"] is False and holdings[0]["price"] == 2395.0  # archived close
    summary = client.get(f"{API}/portfolio/summary").json()
    assert summary["is_demo"] is False and summary["upcoming_dividends"] == []


def test_performance_starts_at_the_first_fully_archived_close(client, engine, market):
    today = today_taipei()
    days = tw_trading_days(today - timedelta(days=25), today - timedelta(days=1))[-10:]
    with Session(engine) as db:
        db.add_all([PriceDaily(symbol="2330.TW", date=d, close=D(1000 + 10 * i), source="twse-openapi")
                    for i, d in enumerate(days)])
        db.commit()
    md = MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine)), DemoProvider()],
                    policy="commercial")
    set_market_data(md)
    try:
        acc = make_account(client)
        buy = last_tw_trading_day(today - timedelta(days=60)).isoformat()
        client.post(f"{API}/transactions", json={"account_id": acc, "symbol": "2330.TW", "type": "buy",
                                                 "trade_date": buy, "quantity": 1000, "price": 1000})
        p = client.get(f"{API}/portfolio/performance?range=3M").json()
        # the window opens on the first archived close as a base (twr_index 1.0), not on the buy date
        assert p["start_date"] == days[0].isoformat() and p["series"][0]["twr_index"] == 1.0
        assert p["series"][0]["market_value"] == 1_000_000.0
        # nine +10 closes: 1000 -> 1090
        assert p["twr"] == pytest.approx(1090 / 1000 - 1, abs=1e-6)
        assert any(n.startswith("資料累積中") and "績效從" in n for n in p["notes"])
        assert any("基準" in n for n in p["notes"])  # 0050 has no archive rows here
        five = client.get(f"{API}/portfolio/performance?range=5D").json()
        assert len(five["series"]) == 6 and not any(n.startswith("資料累積中") for n in five["notes"])
    finally:
        set_market_data(market)


def test_seed_works_under_commercial(engine, client, commercial):
    with Session(engine) as db:
        result = seed(db, commercial)
        user = db.query(User).filter_by(email=DEMO_EMAIL).one()
        plan = db.query(RecurringPlan).filter_by(user_id=user.id).one()
        assert (plan.symbol, plan.amount, plan.days_of_month) == ("0050.TW", D(5000), [6, 19])
        assert db.query(Transaction).filter_by(user_id=user.id).count() == result["transactions"] > 30
    assert result["policy"] == "commercial"
    # the API serves the seeded ledger with real archived closes or nothing — never demo prices
    r = client.post(f"{API}/auth/dev-login", json={"email": DEMO_EMAIL})
    assert r.status_code == 200
    holdings = client.get(f"{API}/portfolio/holdings").json()
    assert holdings and not any(h["is_demo"] for h in holdings)
    us = [h for h in holdings if h["market"] == "US"]
    assert us and all(h["price"] is None for h in us)
    perf = client.get(f"{API}/portfolio/performance?range=1Y").json()
    assert perf["series"] == [] and perf["notes"]
    upcoming = client.get(f"{API}/portfolio/upcoming?days=31").json()
    assert [i["symbol"] for i in upcoming if i["type"] == "recurring"] == ["0050.TW", "0050.TW"]
    assert date.fromisoformat(upcoming[0]["date"]) >= today_taipei()
