"""Automatic dividend booking (docs/handoff.md §3.0): Taiwan cash / stock dividends become ``source="auto"``
transactions on the ex-date, from the shares held at the close before it; the user's own records win; edited rows
become ``auto_edited``; deleted rows are never booked again."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.base import DividendEvent
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import AutoDividendSkip, MarketEvent, Transaction
from forliosa.services.auto_dividends import covered_by_user, sync_all_users
from forliosa.timeutil import today_taipei

API = "/api/v1"


@pytest.fixture()
def notices(engine, market):
    """Real (non-demo) ex-dividend notices from the archive; the demo provider only resolves instruments."""
    md = MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine)), DemoProvider()],
                    policy="personal")
    set_market_data(md)

    def add(symbol: str, ex: date, cash: str | None = None, ratio: str | None = None) -> None:
        source = "tpex-openapi" if symbol.endswith(".TWO") else "twse-openapi"
        with Session(engine) as db:
            key = f"ex-{symbol}-{ex.isoformat()}"
            row = db.scalar(select(MarketEvent).where(MarketEvent.key == key))
            if row is None:
                row = MarketEvent(key=key, symbol=symbol, date=ex, type="ex_dividend", title="除權息", detail="",
                                  source=source)
                db.add(row)
            row.data = {"cash": cash, "stock_ratio": ratio}
            db.commit()

    add.md = md  # type: ignore[attr-defined]
    yield add
    set_market_data(market)


def make_account(client, **kw):
    body = {"name": "永豐－一般", "broker": "永豐金證券", "currency": "TWD", "fee_discount": 0.28, **kw}
    r = client.post(f"{API}/accounts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def add_txn(client, **body):
    r = client.post(f"{API}/transactions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def txns(client, account_id: str, **params) -> list[dict]:
    r = client.get(f"{API}/transactions", params={"account_id": account_id, "limit": 200, **params})
    assert r.status_code == 200, r.text
    return r.json()["items"]


def autos(client, account_id: str) -> list[dict]:
    return sorted((t for t in txns(client, account_id) if t["source"] in ("auto", "auto_edited")),
                  key=lambda t: (t["trade_date"], t["type"]))


def buy(client, acc, symbol, d, qty, price="50"):
    return add_txn(client, account_id=acc["id"], symbol=symbol, type="buy", trade_date=d, quantity=qty, price=price)


def sell(client, acc, symbol, d, qty, price="50"):
    return add_txn(client, account_id=acc["id"], symbol=symbol, type="sell", trade_date=d, quantity=qty, price=price)


# -- booking --------------------------------------------------------------------------------------
def test_cash_dividend_booked_on_ex_date_with_nhi(client, notices):
    notices("0056.TW", date(2026, 7, 16), cash="2.00000000")
    acc = make_account(client)
    buy(client, acc, "0056.TW", "2026-05-04", 10000, "38")
    rows = autos(client, acc["id"])
    assert len(rows) == 1
    a = rows[0]
    assert (a["type"], a["trade_date"], a["quantity"], a["price"], a["amount"], a["source"]) == (
        "cash_dividend", "2026-07-16", 10000, 2.0, 20000, "auto")
    assert a["health_insurance"] == 422  # 2.11% of a single payment ≥ NT$20,000
    assert a["note"].startswith("10,000 股 × 每股 2 元")
    # the dividend offsets the ex-date price drop: it is income of the holding, not a deposit
    hold = client.get(f"{API}/portfolio/holdings").json()
    assert hold[0]["symbol"] == "0056.TW"
    summary = client.get(f"{API}/portfolio/summary").json()
    assert summary["dividend_income"] == 20000 - 422  # net of the NHI premium


def test_entitlement_follows_the_close_before_the_ex_date(client, notices):
    ex = date(2026, 7, 16)
    notices("2317.TW", ex, cash="5.00000000")
    a = make_account(client, name="前一天買")
    buy(client, a, "2317.TW", "2026-07-15", 1000, "200")
    b = make_account(client, name="除息日當天買")
    buy(client, b, "2317.TW", "2026-07-16", 1000, "200")
    c = make_account(client, name="除息日當天賣")
    buy(client, c, "2317.TW", "2026-07-01", 1000, "200")
    sell(client, c, "2317.TW", "2026-07-16", 1000, "195")
    d = make_account(client, name="前一天賣")
    buy(client, d, "2317.TW", "2026-07-01", 1000, "200")
    sell(client, d, "2317.TW", "2026-07-15", 1000, "201")
    assert [r["quantity"] for r in autos(client, a["id"])] == [1000]
    assert autos(client, b["id"]) == []
    assert [r["amount"] for r in autos(client, c["id"])] == [5000]
    assert autos(client, d["id"]) == []


def test_odd_lot_cash_is_truncated(client, notices):
    notices("2330.TW", date(2026, 9, 17), cash="5.00000000")
    notices("0056.TW", date(2026, 7, 16), cash="2.50000000")
    acc = make_account(client)
    buy(client, acc, "0056.TW", "2026-06-01", 37, "38")
    rows = autos(client, acc["id"])
    assert [(r["quantity"], r["amount"], r["health_insurance"]) for r in rows] == [(37, 92, 0)]  # 92.5 -> 92


def test_otc_stock_and_cash_dividend_compound(client, notices):
    # 0.05 share per share (= NT$0.5 of par) and NT$3 cash on the same ex-date, then a later cash dividend
    notices("6488.TWO", date(2026, 6, 23), cash="3.00000000", ratio="0.05000000")
    notices("6488.TWO", date(2026, 9, 22), cash="1.00000000")
    acc = make_account(client)
    buy(client, acc, "6488.TWO", "2026-03-03", 1234, "400")
    rows = autos(client, acc["id"])
    by = {(r["trade_date"], r["type"]): r for r in rows}
    cash, stock = by[("2026-06-23", "cash_dividend")], by[("2026-06-23", "stock_dividend")]
    assert (cash["quantity"], cash["amount"]) == (1234, 3702)
    # 1,234 × 0.5 / 10 = 61.7 -> 61 shares + NT$7 in lieu
    assert (stock["quantity"], stock["price"], stock["amount"]) == (61, 0.5, 7)
    assert "配發 61 股" in stock["note"] and "不足一股折付現金 7 元" in stock["note"]
    later = by[("2026-09-22", "cash_dividend")]
    assert later["quantity"] == 1295 and later["amount"] == 1295  # the new shares are entitled too
    hold = client.get(f"{API}/portfolio/holdings").json()
    assert hold[0]["quantity"] == 1295


def test_unannounced_zero_future_and_us_dividends_are_not_booked(client, notices, engine):
    future = today_taipei() + timedelta(days=20)
    notices("2330.TW", date(2026, 6, 11))  # 尚未公告: no amount
    notices("2317.TW", date(2026, 6, 12), cash="0", ratio="0")  # 現金增資除權: nothing to book
    notices("2454.TW", future, cash="25.00000000")
    acc = make_account(client)
    for s in ("2330.TW", "2317.TW", "2454.TW"):
        buy(client, acc, s, "2026-05-04", 100, "100")
    us = make_account(client, name="Firstrade", currency="USD")
    add_txn(client, account_id=us["id"], symbol="AAPL", type="buy", trade_date="2026-05-04", quantity=10,
            price="200")
    assert autos(client, acc["id"]) == [] and autos(client, us["id"]) == []
    # the worker books it once the amount is announced
    notices("2330.TW", date(2026, 6, 11), cash="4.50000000")
    res = sync_all_users(lambda: Session(engine), notices.md)
    assert res.created == 1
    assert [(r["symbol"], r["amount"]) for r in autos(client, acc["id"])] == [("2330.TW", 450)]
    # a corrected notice updates the automatic row
    notices("2330.TW", date(2026, 6, 11), cash="5.00000000")
    assert sync_all_users(lambda: Session(engine), notices.md).updated == 1
    assert [r["amount"] for r in autos(client, acc["id"])] == [500]
    assert sync_all_users(lambda: Session(engine), notices.md).changed is False  # idempotent


def test_demo_dividends_are_never_booked(client):
    acc = make_account(client)
    buy(client, acc, "00878.TW", "2019-01-02", 1000, "15")  # the demo provider has synthetic 00878 dividends
    assert autos(client, acc["id"]) == []


# -- the user's records win ---------------------------------------------------------------------------
def test_manual_dividend_replaces_the_automatic_one(client, notices):
    notices("2330.TW", date(2026, 6, 11), cash="5.00000000")
    acc = make_account(client)
    buy(client, acc, "2330.TW", "2026-05-04", 1000, "1000")
    assert len(autos(client, acc["id"])) == 1
    manual = add_txn(client, account_id=acc["id"], symbol="2330.TW", type="cash_dividend",
                     trade_date="2026-07-09", amount=5000)  # recorded on the payment date
    assert autos(client, acc["id"]) == []
    assert len(txns(client, acc["id"], type="cash_dividend")) == 1
    # deleting the manual record brings the automatic one back
    assert client.delete(f"{API}/transactions/{manual['id']}").status_code == 204
    assert [r["amount"] for r in autos(client, acc["id"])] == [5000]
    # a record more than 120 days after the ex-date is another dividend
    add_txn(client, account_id=acc["id"], symbol="2330.TW", type="cash_dividend", trade_date="2026-10-20",
            amount=5000)
    assert len(autos(client, acc["id"])) == 1


def test_signed_ai_draft_counts_as_the_users_record(client, notices):
    notices("2330.TW", date(2026, 6, 11), cash="5.00000000")
    acc = make_account(client)
    buy(client, acc, "2330.TW", "2026-05-04", 1000, "1000")
    add_txn(client, account_id=acc["id"], symbol="2330.TW", type="cash_dividend", trade_date="2026-06-11",
            price="5", source="ai_draft")
    assert autos(client, acc["id"]) == []


def test_quarterly_records_cover_their_own_ex_dates():
    def ev(d: date, cash: str) -> DividendEvent:
        return DividendEvent("2330.TW", 2026, "Q", D(cash), D(0), d, None)

    events = [ev(date(2026, 3, 17), "4.5"), ev(date(2026, 6, 11), "5"), ev(date(2026, 9, 16), "5")]

    def rec(d: date, price: str = "0") -> Transaction:
        return Transaction(type="cash_dividend", trade_date=d, price=D(price))

    # an April payment covers March; a July payment (also within 120 days of March) covers June
    assert covered_by_user([rec(date(2026, 4, 9)), rec(date(2026, 7, 9))], events) == {
        (date(2026, 3, 17), "cash"), (date(2026, 6, 11), "cash")}
    # a per-share amount picks the matching ex-date
    assert covered_by_user([rec(date(2026, 6, 20), "4.5")], events) == {(date(2026, 3, 17), "cash")}
    assert covered_by_user([rec(date(2026, 3, 16))], events) == set()


# -- edits and deletes --------------------------------------------------------------------------------
def test_edited_automatic_dividend_is_kept_as_the_users_version(client, notices, engine):
    notices("2330.TW", date(2026, 6, 11), cash="5.00000000")
    acc = make_account(client)
    buy(client, acc, "2330.TW", "2026-05-04", 1000, "1000")
    auto = autos(client, acc["id"])[0]
    r = client.patch(f"{API}/transactions/{auto['id']}", json={"health_insurance": 0, "note": "券商實收"})
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "auto_edited" and r.json()["health_insurance"] == 0
    # more shares before the ex-date: the edited row is not overwritten and no second row appears
    buy(client, acc, "2330.TW", "2026-05-05", 1000, "1000")
    rows = autos(client, acc["id"])
    assert [(r["source"], r["quantity"], r["note"]) for r in rows] == [("auto_edited", 1000, "券商實收")]
    assert sync_all_users(lambda: Session(engine), notices.md).changed is False
    with Session(engine) as db:
        skips = list(db.scalars(select(AutoDividendSkip)))
    assert [(s.symbol, s.ex_date, s.kind, s.reason) for s in skips] == [
        ("2330.TW", date(2026, 6, 11), "cash", "edited")]


def test_deleted_automatic_dividend_is_not_booked_again(client, notices, engine):
    notices("2330.TW", date(2026, 6, 11), cash="5.00000000")
    notices("2330.TW", date(2026, 9, 16), cash="5.00000000")
    acc = make_account(client)
    buy(client, acc, "2330.TW", "2026-05-04", 1000, "1000")
    june = next(r for r in autos(client, acc["id"]) if r["trade_date"] == "2026-06-11")
    assert client.delete(f"{API}/transactions/{june['id']}").status_code == 204
    buy(client, acc, "2330.TW", "2026-05-05", 1000, "1000")
    sync_all_users(lambda: Session(engine), notices.md)
    assert [(r["trade_date"], r["quantity"]) for r in autos(client, acc["id"])] == [("2026-09-16", 2000)]


def test_backfilled_and_deleted_trades_resync(client, notices):
    notices("2330.TW", date(2026, 6, 11), cash="5.00000000")
    acc = make_account(client)
    first = buy(client, acc, "2330.TW", "2026-05-04", 1000, "1000")
    buy(client, acc, "2330.TW", "2026-03-02", 500, "900")  # back-filled
    assert [r["quantity"] for r in autos(client, acc["id"])] == [1500]
    s = sell(client, acc, "2330.TW", "2026-06-01", 300, "1050")  # a sell before the ex-date
    assert [r["amount"] for r in autos(client, acc["id"])] == [6000]
    assert client.delete(f"{API}/transactions/{s['id']}").status_code == 204
    assert [r["quantity"] for r in autos(client, acc["id"])] == [1500]
    # moving a buy after the ex-date
    r = client.patch(f"{API}/transactions/{first['id']}", json={"trade_date": "2026-06-12"})
    assert r.status_code == 200, r.text
    assert [r["quantity"] for r in autos(client, acc["id"])] == [500]
    # selling everything before the ex-date removes it
    sell(client, acc, "2330.TW", "2026-06-10", 500, "1050")
    assert autos(client, acc["id"]) == []


def test_resync_that_breaks_the_books_is_refused(client, notices):
    # 2,000 shares get an automatic 200-share stock dividend, and all 2,200 are sold later
    notices("6488.TWO", date(2026, 6, 23), ratio="0.10000000")
    acc = make_account(client)
    buy(client, acc, "6488.TWO", "2026-05-04", 1000, "400")
    b = buy(client, acc, "6488.TWO", "2026-05-05", 1000, "400")
    assert [r["quantity"] for r in autos(client, acc["id"])] == [200]
    sell(client, acc, "6488.TWO", "2026-07-01", 2200, "420")
    # moving a buy after the ex-date halves the dividend, so the later sell would exceed the holding
    r = client.patch(f"{API}/transactions/{b['id']}", json={"trade_date": "2026-06-24"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ledger_inconsistent" and "自動入帳" in r.json()["error"]["message"]
    assert [r["quantity"] for r in autos(client, acc["id"])] == [200]  # nothing changed
    assert next(t for t in txns(client, acc["id"]) if t["id"] == b["id"])["trade_date"] == "2026-05-05"


def test_deleting_the_account_removes_its_skips(client, notices, engine):
    notices("2330.TW", date(2026, 6, 11), cash="5.00000000")
    acc = make_account(client)
    buy(client, acc, "2330.TW", "2026-05-04", 1000, "1000")
    auto = autos(client, acc["id"])[0]
    assert client.delete(f"{API}/transactions/{auto['id']}").status_code == 204
    assert client.delete(f"{API}/accounts/{acc['id']}").status_code == 204
    with Session(engine) as db:
        assert list(db.scalars(select(AutoDividendSkip))) == []


def test_other_users_are_untouched(client, other_client, notices):
    notices("2330.TW", date(2026, 6, 11), cash="5.00000000")
    mine = make_account(client)
    buy(client, mine, "2330.TW", "2026-05-04", 1000, "1000")
    theirs = make_account(other_client)
    buy(other_client, theirs, "2330.TW", "2026-05-04", 2000, "1000")
    assert [r["quantity"] for r in autos(client, mine["id"])] == [1000]
    assert [r["quantity"] for r in autos(other_client, theirs["id"])] == [2000]
    auto = autos(client, mine["id"])[0]
    assert other_client.delete(f"{API}/transactions/{auto['id']}").status_code == 404


# -- review regressions ----------------------------------------------------------------------------
@pytest.mark.parametrize("change", ["sell_before", "delete_buy", "move_buy"])
def test_changes_are_validated_after_the_resync(client, notices, change):
    """A stale automatic stock dividend must not block a change that the re-sync makes consistent."""
    notices("6488.TWO", date(2026, 6, 23), ratio="0.10000000")
    acc = make_account(client)
    b = buy(client, acc, "6488.TWO", "2026-05-04", 1000, "400")
    assert [r["quantity"] for r in autos(client, acc["id"])] == [100]
    if change == "sell_before":
        sell(client, acc, "6488.TWO", "2026-06-10", 1000, "410")
    elif change == "delete_buy":
        assert client.delete(f"{API}/transactions/{b['id']}").status_code == 204
    else:
        r = client.patch(f"{API}/transactions/{b['id']}", json={"trade_date": "2026-06-24"})
        assert r.status_code == 200, r.text
    assert autos(client, acc["id"]) == []


def test_deleting_a_manual_stock_dividend_lets_the_automatic_one_back(client, notices):
    notices("6488.TWO", date(2026, 6, 23), ratio="0.10000000")
    acc = make_account(client)
    buy(client, acc, "6488.TWO", "2026-05-04", 1000, "400")
    manual = add_txn(client, account_id=acc["id"], symbol="6488.TWO", type="stock_dividend",
                     trade_date="2026-07-20", quantity=100)
    assert autos(client, acc["id"]) == []
    sell(client, acc, "6488.TWO", "2026-08-01", 1100, "420")
    assert client.delete(f"{API}/transactions/{manual['id']}").status_code == 204
    assert [r["quantity"] for r in autos(client, acc["id"])] == [100]


def test_per_share_record_on_the_payment_date_uses_the_ex_date_holding(client, notices):
    """Recording a dividend from its per-share amount after the ex-date does not count the automatic stock
    dividend of that same ex-date (which it replaces), nor trades between the ex-date and the record."""
    notices("6488.TWO", date(2026, 6, 23), cash="3.00000000", ratio="0.10000000")
    acc = make_account(client)
    buy(client, acc, "6488.TWO", "2026-05-04", 1000, "400")
    buy(client, acc, "6488.TWO", "2026-07-01", 500, "400")  # after the ex-date: not entitled
    stock = add_txn(client, account_id=acc["id"], symbol="6488.TWO", type="stock_dividend",
                    trade_date="2026-07-20", price="1")
    cash = add_txn(client, account_id=acc["id"], symbol="6488.TWO", type="cash_dividend",
                   trade_date="2026-07-20", price="3")
    assert (stock["quantity"], cash["quantity"], cash["amount"]) == (100, 1000, 3000)
    assert autos(client, acc["id"]) == []
    hold = client.get(f"{API}/portfolio/holdings").json()
    assert hold[0]["quantity"] == 1600


def test_unreadable_archive_keeps_the_automatic_rows(client, notices, engine, monkeypatch):
    notices("2330.TW", date(2026, 6, 11), cash="5.00000000")
    acc = make_account(client)
    b = buy(client, acc, "2330.TW", "2026-05-04", 1000, "1000")
    assert len(autos(client, acc["id"])) == 1
    archive = next(p for p in notices.md.providers if p.name == "archive")

    def broken(symbol):
        raise RuntimeError("archive down")

    monkeypatch.setattr(archive, "dividends", broken)
    r = client.patch(f"{API}/transactions/{b['id']}", json={"note": "改備註"})
    assert r.status_code == 200, r.text
    assert sync_all_users(lambda: Session(engine), notices.md).changed is False
    monkeypatch.undo()
    assert [r["amount"] for r in autos(client, acc["id"])] == [5000]


def test_record_of_an_unannounced_dividend_does_not_cover_the_previous_one(client, notices):
    notices("00878.TW", date(2026, 8, 18), cash="0.40000000")
    notices("00878.TW", date(2026, 10, 20))  # 金額尚未公告
    acc = make_account(client)
    buy(client, acc, "00878.TW", "2026-05-04", 10000, "22")
    assert [r["trade_date"] for r in autos(client, acc["id"])] == ["2026-08-18"]
    add_txn(client, account_id=acc["id"], symbol="00878.TW", type="cash_dividend", trade_date="2026-11-11",
            amount=5000)  # the October dividend
    assert [r["trade_date"] for r in autos(client, acc["id"])] == ["2026-08-18"]


def test_withdrawn_future_notices_are_pruned_from_the_archive(engine):
    from forliosa.archive import Archiver
    from tests.archive.fakes import NOW, FakeFetcher

    today = NOW.date()
    with Session(engine) as db:
        db.add(MarketEvent(key="old-key", symbol="2317.TW", date=today + timedelta(days=5), type="ex_dividend",
                           title="除息", detail="", data={"cash": "5", "stock_ratio": None}, source="twse-openapi"))
        db.add(MarketEvent(key="past-key", symbol="2317.TW", date=today - timedelta(days=5), type="ex_dividend",
                           title="除息", detail="", data={"cash": "5", "stock_ratio": None}, source="twse-openapi"))
        db.commit()
        Archiver(db, FakeFetcher(), "commercial", now_fn=lambda: NOW).run(["twse"])
        keys = {e.key for e in db.scalars(select(MarketEvent).where(MarketEvent.type == "ex_dividend",
                                                                     MarketEvent.symbol == "2317.TW"))}
    assert "old-key" not in keys and "past-key" in keys


def test_seed_stops_synthetic_dividends_where_real_notices_begin(engine, notices):
    from forliosa.seed import DEMO_EMAIL, seed

    notices("2454.TW", date(2026, 7, 13), cash="25.00000000")
    with Session(engine) as db:
        seed(db, notices.md)
        rows = list(db.scalars(select(Transaction).where(Transaction.symbol == "2454.TW",
                                                          Transaction.type == "cash_dividend")))
        assert DEMO_EMAIL
    recent = [(t.trade_date, t.source) for t in rows if t.trade_date >= date(2026, 3, 15)]
    assert recent == [(date(2026, 7, 13), "auto")], recent  # no synthetic 2026-07-09 record next to it
