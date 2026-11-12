"""定期定額: CRUD, debit schedule on the official TWSE calendar, /portfolio/upcoming and the draft."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

from forliosa.archive import Archiver
from forliosa.market_calendar import load_official_calendar
from forliosa.marketdata.base import BaseProvider, QuoteData
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import MarketHoliday, RecurringPlan
from forliosa.services import recurring as rec
from forliosa.timeutil import has_official_calendar, is_tw_trading_day, next_tw_trading_day, set_official_holidays
from tests.archive.fakes import NOW, FakeFetcher

API = "/api/v1"


def make_account(client, currency="TWD"):
    r = client.post(f"{API}/accounts", json={"name": "永豐", "currency": currency, "fee_discount": 0.28})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture()
def calendar(engine, market):
    """TWSE holidaySchedule (2026) archived from the live fixture and applied."""
    with Session(engine) as db:
        results = Archiver(db, FakeFetcher(), "commercial", now_fn=lambda: NOW).run(["twse"])
        assert not [r for r in results if r.error and "holidays" in r.name]
        load_official_calendar(db)
    return engine


def freeze(monkeypatch, d: date) -> None:
    import forliosa.api.routes.portfolio as portfolio_routes
    import forliosa.services.portfolio as portfolio_svc

    for mod in (rec, portfolio_routes, portfolio_svc):
        monkeypatch.setattr(mod, "today_taipei", lambda: d)


# -- calendar ---------------------------------------------------------------------------------------------
def test_holiday_schedule_is_archived_and_replaces_the_builtin_list(calendar):
    with Session(calendar) as db:
        assert db.get(MarketHoliday, date(2026, 1, 2)).is_trading_day is True  # 「國曆新年開始交易日」
        settlement = db.get(MarketHoliday, date(2026, 2, 12))
        assert settlement.name == "市場無交易，僅辦理結算交割作業" and settlement.is_trading_day is False
        assert "<br>" not in db.get(MarketHoliday, date(2026, 2, 17)).description
    assert has_official_calendar(2026) and not has_official_calendar(2027)
    assert not is_tw_trading_day(date(2026, 2, 12)) and is_tw_trading_day(date(2026, 2, 11))
    # Lunar New Year: 2/12–2/13 settlement only, 2/16–2/20 holidays -> first session 2/23
    assert next_tw_trading_day(date(2026, 2, 12)) == date(2026, 2, 23)


def test_official_calendar_overrides_only_its_years():
    assert not is_tw_trading_day(date(2027, 2, 4))  # built-in estimate for 2027
    set_official_holidays([date(2027, 2, 8)], [2027])  # pretend TWSE published a different 2027
    assert is_tw_trading_day(date(2027, 2, 4)) and not is_tw_trading_day(date(2027, 2, 8))
    assert not is_tw_trading_day(date(2026, 2, 16))  # 2026 still uses the built-in list
    set_official_holidays([], [])
    assert not is_tw_trading_day(date(2027, 2, 4))


def test_debit_dates_move_to_the_next_trading_day(calendar):
    plan = RecurringPlan(days_of_month=[6, 19], start_date=date(2026, 1, 1), end_date=None, active=True)
    feb = rec.debit_dates(plan, date(2026, 2, 1), date(2026, 2, 28))
    # 2/6 is a Friday; 2/19 is in the Lunar New Year closure -> Monday 2/23
    assert feb == [(date(2026, 2, 6), date(2026, 2, 6)), (date(2026, 2, 19), date(2026, 2, 23))]
    dec = rec.debit_dates(plan, date(2026, 12, 1), date(2026, 12, 31))
    # 12/6 Sunday -> 12/7; 12/19 Saturday -> 12/21
    assert dec == [(date(2026, 12, 6), date(2026, 12, 7)), (date(2026, 12, 19), date(2026, 12, 21))]
    # a scheduled day just before the window whose debit moves into it is included
    assert rec.debit_dates(plan, date(2026, 2, 20), date(2026, 2, 23)) == [(date(2026, 2, 19), date(2026, 2, 23))]
    ended = RecurringPlan(days_of_month=[6, 19], start_date=date(2026, 12, 10), end_date=date(2026, 12, 20),
                          active=True)
    assert rec.debit_dates(ended, date(2026, 12, 1), date(2027, 1, 31)) == [(date(2026, 12, 19), date(2026, 12, 21))]


# -- CRUD ------------------------------------------------------------------------------------------------
def test_recurring_crud_validation_and_isolation(client, other_client):
    acc = make_account(client)
    r = client.post(f"{API}/recurring", json={"account_id": acc, "symbol": "0050", "amount": 5000,
                                              "day_of_month": [19, 6, 6], "start_date": "2026-01-01"})
    assert r.status_code == 201, r.text
    plan = r.json()
    assert (plan["symbol"], plan["amount"], plan["day_of_month"], plan["active"]) == ("0050.TW", 5000.0, [6, 19], True)
    assert plan["end_date"] is None and plan["next_date"] is not None and plan["name"]
    pid = plan["id"]
    assert [p["id"] for p in client.get(f"{API}/recurring").json()] == [pid]
    assert client.get(f"{API}/recurring", params={"account_id": "acc_x"}).json() == []

    r = client.patch(f"{API}/recurring/{pid}", json={"amount": 3000, "day_of_month": 16, "end_date": "2027-12-31",
                                                      "note": "改成每月 16 日"})
    assert r.status_code == 200, r.text
    assert (r.json()["amount"], r.json()["day_of_month"], r.json()["end_date"]) == (3000.0, [16], "2027-12-31")
    r = client.patch(f"{API}/recurring/{pid}", json={"end_date": None, "active": False})
    assert (r.json()["end_date"], r.json()["active"], r.json()["next_date"]) == (None, False, None)
    assert client.get(f"{API}/recurring/{pid}").json()["note"] == "改成每月 16 日"

    def bad(body, code="validation_error", status=422):
        res = client.post(f"{API}/recurring", json={"account_id": acc, "symbol": "0050", "amount": 5000,
                                                    "day_of_month": 6, **body})
        assert res.status_code == status, (body, res.text)
        assert res.json()["error"]["code"] == code

    bad({"day_of_month": 29})
    bad({"day_of_month": []})
    bad({"amount": 0})
    bad({"amount": 1000.5})
    bad({"symbol": "ZZZZ"}, "unknown_symbol")
    bad({"symbol": "AAPL"})
    bad({"start_date": "2026-05-01", "end_date": "2026-04-01"})
    bad({"account_id": make_account(client, "USD")})
    bad({"account_id": "acc_nope"}, "not_found", 404)
    other_acc = make_account(other_client)
    bad({"account_id": other_acc}, "not_found", 404)

    assert other_client.get(f"{API}/recurring").json() == []
    assert other_client.get(f"{API}/recurring/{pid}").status_code == 404
    assert other_client.patch(f"{API}/recurring/{pid}", json={"amount": 1}).status_code == 404
    assert other_client.delete(f"{API}/recurring/{pid}").status_code == 404
    assert client.delete(f"{API}/recurring/{pid}").status_code == 204
    assert client.get(f"{API}/recurring/{pid}").status_code == 404


# -- upcoming --------------------------------------------------------------------------------------------
def test_upcoming_includes_recurring_debits(client, calendar, monkeypatch):
    freeze(monkeypatch, date(2026, 2, 10))
    acc = make_account(client)
    other = make_account(client)
    body = {"account_id": acc, "symbol": "0050", "amount": 5000, "day_of_month": [6, 19], "start_date": "2026-01-01"}
    pid = client.post(f"{API}/recurring", json=body).json()["id"]
    client.post(f"{API}/recurring", json={**body, "account_id": other, "active": False})  # inactive: never listed
    week = client.get(f"{API}/portfolio/upcoming?days=7").json()
    assert week == []  # 2/10 → 2/17: the 2/19 debit moves to 2/23
    items = client.get(f"{API}/portfolio/upcoming?days=14").json()
    assert len(items) == 1
    it = items[0]
    assert (it["date"], it["scheduled_date"], it["type"], it["symbol"], it["amount_estimate"]) == (
        "2026-02-23", "2026-02-19", "recurring", "0050.TW", 5000.0)
    assert it["plan_id"] == pid and it["account_id"] == acc and it["is_demo"] is False
    assert "定期定額 NT$5,000" in it["title"] and "2/19 非交易日，順延" in it["title"]
    assert any("臺灣證券交易所" in s for s in it["sources"]) and "本系統帳本" in it["sources"]
    month = client.get(f"{API}/portfolio/upcoming?days=30").json()
    assert [i["date"] for i in month] == ["2026-02-23", "2026-03-06"]
    assert client.get(f"{API}/portfolio/upcoming?days=30", params={"account_id": other}).json() == []


# -- draft -----------------------------------------------------------------------------------------------
class FixedClose(BaseProvider):
    name = "fake-close"

    def quotes(self, symbols):
        return {s: QuoteData(s, price=D("52.4"), prev_close=D("52"), trade_date=date(2026, 11, 11), source="fake")
                for s in symbols if s == "0050.TW"}


@pytest.fixture()
def close_52_4(market):
    set_market_data(MarketData([FixedClose(), DemoProvider()], policy="personal"))
    yield
    set_market_data(market)


def test_draft_estimates_odd_lot_shares_and_fee(client, calendar, close_52_4, monkeypatch):
    freeze(monkeypatch, date(2026, 11, 12))
    acc = make_account(client)
    pid = client.post(f"{API}/recurring", json={"account_id": acc, "symbol": "0050", "amount": 5000,
                                                "day_of_month": [6, 19], "start_date": "2026-01-01"}).json()["id"]
    r = client.post(f"{API}/recurring/{pid}/draft")
    assert r.status_code == 200, r.text
    d = r.json()
    # next debit: 11/19 (Thursday). floor(5,000 ÷ 52.4 = 95.42) = 95 shares (odd lot);
    # gross 95 × 52.4 = 4,978; fee floor(4,978 × 0.1425 % × 0.28 = 1.99) = 1 (odd-lot minimum NT$1)
    assert (d["date"], d["scheduled_date"], d["price_as_of"], d["amount"]) == (
        "2026-11-19", "2026-11-19", "2026-11-11", 5000.0)
    assert d["transaction"] == {"account_id": acc, "symbol": "0050.TW", "type": "buy", "trade_date": "2026-11-19",
                                "quantity": 95, "price": 52.4, "note": "定期定額 NT$5,000（11/19）",
                                "source": "ai_draft"}
    p = d["preview"]
    assert (p["gross"], p["fee"], p["tax"], p["net_cash"]) == (4978.0, 1.0, 0.0, -4979.0)
    assert p["rules"][0].startswith("股數 = floor(NT$5,000 ÷ 收盤價 52.4（11/11）) = 95 股（零股）")
    # a scheduled day on a weekend: 12/19 (Saturday) -> 12/21
    moved = client.post(f"{API}/recurring/{pid}/draft", params={"date": "2026-12-19"}).json()
    assert moved["date"] == "2026-12-21" and "順延到 12/21" in moved["preview"]["rules"][0]
    # the draft creates nothing; signing it is a normal POST /transactions
    assert client.get(f"{API}/transactions").json()["items"] == []
    t = client.post(f"{API}/transactions", json=d["transaction"])
    assert t.status_code == 201, t.text
    assert (t.json()["source"], t.json()["fee"], t.json()["quantity"]) == ("ai_draft", 1.0, 95)

    small = client.post(f"{API}/recurring", json={"account_id": acc, "symbol": "0050", "amount": 50,
                                                  "day_of_month": 6}).json()["id"]
    r = client.post(f"{API}/recurring/{small}/draft")
    assert r.status_code == 422 and r.json()["error"]["code"] == "amount_too_small"
    client.patch(f"{API}/recurring/{pid}", json={"active": False})
    assert client.post(f"{API}/recurring/{pid}/draft").status_code == 409


def test_draft_without_a_close_under_commercial(client, market):
    set_market_data(MarketData([DemoProvider()], policy="commercial"))
    try:
        acc = make_account(client)
        pid = client.post(f"{API}/recurring", json={"account_id": acc, "symbol": "0050", "amount": 5000,
                                                    "day_of_month": 6}).json()["id"]
        r = client.post(f"{API}/recurring/{pid}/draft")
        assert r.status_code == 422 and r.json()["error"]["code"] == "no_price"  # never a demo price
    finally:
        set_market_data(market)
