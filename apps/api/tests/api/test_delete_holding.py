"""``DELETE /accounts/{account_id}/holdings/{symbol}`` (產品負責人 2026-11-17：「還要有刪除股票的功能」): every
record of one stock in one account goes — buys, sells, dividends (automatic ones included) — nothing is booked,
other accounts, stocks and users are untouched, 定期定額 are only paused when asked, and no automatic dividend comes
back."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import forliosa.services.recurring as recurring_svc
import forliosa.services.transactions as txn_svc
from forliosa.ids import new_id
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import AutoDividendSkip, GroupComment, MarketEvent, RecurringPlan, Transaction
from forliosa.services.auto_dividends import sync_all_users
from forliosa.timeutil import now_utc
from tests.api.m5 import API, account, join, make_group, me_id, set_share, trade, trading_day

VIEW = "X-Forliosa-View-As"


@pytest.fixture()
def notices(engine, market):
    """Real (non-demo) ex-dividend notices in the archive, as ``test_auto_dividends`` sets them up."""
    md = MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine)), DemoProvider()],
                    policy="personal")
    set_market_data(md)

    def add(symbol: str, ex: date, cash: str) -> None:
        with Session(engine) as db:
            db.add(MarketEvent(key=f"ex-{symbol}-{ex.isoformat()}", symbol=symbol, date=ex, type="ex_dividend",
                               title="除權息", detail="", source="twse-openapi",
                               data={"cash": cash, "stock_ratio": None}))
            db.commit()

    add.md = md  # type: ignore[attr-defined]
    yield add
    set_market_data(market)


def remove(client, account_id: str, symbol: str, **params):
    return client.delete(f"{API}/accounts/{account_id}/holdings/{symbol}", params=params)


def txns(client, account_id: str) -> list[dict]:
    r = client.get(f"{API}/transactions", params={"account_id": account_id, "limit": 200})
    assert r.status_code == 200, r.text
    return r.json()["items"]


def held(client) -> dict[str, float]:
    return {h["symbol"]: h["quantity"] for h in client.get(f"{API}/portfolio/holdings").json()}


def plan(client, account_id: str, symbol: str, **kw) -> dict:
    r = client.post(f"{API}/recurring", json={"account_id": account_id, "symbol": symbol, "amount": 5000,
                                              "day_of_month": [6], **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_every_record_of_the_stock_in_that_account_goes(client):
    acc = account(client)
    other = account(client, "國泰－一般")
    trade(client, acc["id"], "2330.TW", "buy", date(2025, 3, 3), 1000, 1000)
    trade(client, acc["id"], "2330.TW", "buy", date(2025, 4, 1), 500, 950, fee=20)
    trade(client, acc["id"], "2330.TW", "sell", date(2025, 5, 2), 300, 1010)
    r = client.post(f"{API}/transactions", json={"account_id": acc["id"], "symbol": "2330.TW", "type": "cash_dividend",
                                                 "trade_date": "2025-07-10", "amount": 5000})
    assert r.status_code == 201, r.text
    keep = trade(client, acc["id"], "0050.TW", "buy", date(2025, 3, 3), 2000, 150)
    elsewhere = trade(client, other["id"], "2330.TW", "buy", date(2025, 3, 3), 100, 1000)

    r = remove(client, acc["id"], "2330")  # the code alone resolves like the records' filter
    assert r.status_code == 200, r.text
    assert r.json() == {"account_id": acc["id"], "symbol": "2330.TW", "deleted": 4, "plans_paused": 0,
                        "plans_running": 0}
    assert [t["id"] for t in txns(client, acc["id"])] == [keep["id"]]
    assert [t["id"] for t in txns(client, other["id"])] == [elsewhere["id"]]
    # nothing was booked (not a sell): the stock is as if never recorded in that account
    assert held(client) == {"0050.TW": 2000, "2330.TW": 100}
    closed = client.get(f"{API}/portfolio/closed").json()
    assert [(c["account_id"], c["symbol"]) for c in closed] == []
    r = remove(client, acc["id"], "2330.TW")
    assert r.status_code == 404
    # its own code: the web reads it as "already deleted" (another tab or device); 「找不到帳戶」 stays ``not_found``
    assert r.json()["error"] == {"code": "no_records", "message": "這個帳戶沒有這一檔的紀錄"}


def test_only_your_own_account_and_records(client, other_client):
    mine = account(client)
    theirs = account(other_client)
    trade(client, mine["id"], "2330.TW", "buy", date(2025, 3, 3), 1000, 1000)
    trade(other_client, theirs["id"], "2330.TW", "buy", date(2025, 3, 3), 2000, 1000)
    r = remove(client, theirs["id"], "2330.TW")
    assert r.status_code == 404 and r.json()["error"] == {"code": "not_found", "message": "找不到帳戶"}
    assert remove(client, "acc_nope", "2330.TW").status_code == 404
    assert remove(client, mine["id"], "2330.TW").json()["deleted"] == 1
    assert held(other_client) == {"2330.TW": 2000}
    assert len(txns(other_client, theirs["id"])) == 1


def test_read_only_viewing_cannot_delete(client, other_client):
    g = make_group(client)
    join(client, other_client, g["id"])
    acc = account(client)
    trade(client, acc["id"], "2330.TW", "buy", date(2025, 3, 3), 1000, 1000)
    r = client.post(f"{API}/delegations", json={"viewer_user_id": me_id(other_client), "scope": "all"})
    assert r.status_code == 201, r.text
    r = other_client.delete(f"{API}/accounts/{acc['id']}/holdings/2330.TW", headers={VIEW: r.json()["id"]},
                            params={"pause_plans": "true"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "read_only"
    assert held(client) == {"2330.TW": 1000}


def test_recurring_plans_are_paused_only_when_asked(client):
    acc = account(client)
    other = account(client, "國泰－一般")
    p = plan(client, acc["id"], "0050.TW")
    other_stock = plan(client, acc["id"], "0056.TW")
    other_account = plan(client, other["id"], "0050.TW")
    trade(client, acc["id"], "0050.TW", "buy", date(2025, 3, 3), 1000, 150)

    r = remove(client, acc["id"], "0050.TW")
    assert r.status_code == 200, r.text
    assert (r.json()["deleted"], r.json()["plans_paused"], r.json()["plans_running"]) == (1, 0, 1)
    active = {x["id"]: x["active"] for x in client.get(f"{API}/recurring").json()}
    assert active == {p["id"]: True, other_stock["id"]: True, other_account["id"]: True}

    trade(client, acc["id"], "0050.TW", "buy", date(2025, 3, 3), 1000, 150)
    r = remove(client, acc["id"], "0050.TW", pause_plans="true")
    assert (r.json()["deleted"], r.json()["plans_paused"], r.json()["plans_running"]) == (1, 1, 0)
    active = {x["id"]: x["active"] for x in client.get(f"{API}/recurring").json()}
    # paused, not deleted: it can be resumed in 設定
    assert active == {p["id"]: False, other_stock["id"]: True, other_account["id"]: True}


def test_paused_or_ended_plans_are_not_counted(client):
    acc = account(client)
    plan(client, acc["id"], "0050.TW", active=False)
    plan(client, acc["id"], "0050.TW", start_date="2024-01-01", end_date="2024-12-31")
    trade(client, acc["id"], "0050.TW", "buy", date(2025, 3, 3), 1000, 150)
    r = remove(client, acc["id"], "0050.TW", pause_plans="true")
    assert (r.json()["plans_paused"], r.json()["plans_running"]) == (0, 0)


def test_automatic_dividends_go_and_do_not_come_back(client, notices, engine):
    notices("2330.TW", date(2026, 6, 11), cash="5.00000000")
    notices("2317.TW", date(2026, 7, 16), cash="5.00000000")
    acc = account(client)
    trade(client, acc["id"], "2330.TW", "buy", date(2026, 5, 4), 1000, 1000)
    trade(client, acc["id"], "2317.TW", "buy", date(2026, 5, 4), 1000, 200)
    auto = next(t for t in txns(client, acc["id"]) if t["source"] == "auto" and t["symbol"] == "2330.TW")
    # an edited automatic dividend leaves a skip behind
    r = client.patch(f"{API}/transactions/{auto['id']}", json={"note": "券商實收"})
    assert r.status_code == 200 and r.json()["source"] == "auto_edited"

    r = remove(client, acc["id"], "2330.TW")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 2  # the buy and the (edited) dividend
    assert {t["symbol"] for t in txns(client, acc["id"])} == {"2317.TW"}
    with Session(engine) as db:
        assert list(db.scalars(select(AutoDividendSkip))) == []
    # the daily sync books nothing for a stock with no record left; the other stock keeps its dividend
    assert sync_all_users(lambda: Session(engine), notices.md).changed is False
    assert sorted((t["symbol"], t["type"], t["source"]) for t in txns(client, acc["id"])) == [
        ("2317.TW", "buy", "manual"), ("2317.TW", "cash_dividend", "auto")]
    # recorded again later, the dividend is booked afresh (the old skip went with the records)
    trade(client, acc["id"], "2330.TW", "buy", date(2026, 5, 4), 2000, 1000)
    again = [t for t in txns(client, acc["id"]) if t["symbol"] == "2330.TW" and t["type"] == "cash_dividend"]
    assert [(t["source"], t["quantity"]) for t in again] == [("auto", 2000)]


def test_books_that_were_already_inconsistent_can_be_cleaned(client, engine):
    """A wrong import can leave a stock's books inconsistent (an older row written before today's checks): deleting
    that stock — or another one — is not refused by the replay."""
    acc = account(client)
    trade(client, acc["id"], "0050.TW", "buy", date(2025, 3, 3), 1000, 150)
    with Session(engine) as db:
        user_id = db.scalar(select(Transaction.user_id))
        db.add(Transaction(id=new_id("txn"), user_id=user_id, account_id=acc["id"], symbol="2330.TW", type="sell",
                           trade_date=date(2025, 3, 4), quantity=500, price=1000, amount=500000, currency="TWD",
                           created_at=now_utc(), updated_at=now_utc()))
        db.commit()
    # the books are refused for any ordinary change now
    r = client.post(f"{API}/transactions", json={"account_id": acc["id"], "symbol": "0050.TW", "type": "buy",
                                                 "trade_date": "2025-03-05", "quantity": 1, "price": 150})
    assert r.status_code == 422 and r.json()["error"]["code"] == "ledger_inconsistent"
    assert remove(client, acc["id"], "0050.TW").json()["deleted"] == 1
    assert remove(client, acc["id"], "2330.TW").json()["deleted"] == 1
    assert txns(client, acc["id"]) == []


def test_group_feed_threads_of_the_deleted_trades_go(client, other_client, engine):
    """As with a single delete: a group feed item no record backs any more loses its comments."""
    g = make_group(client)
    join(client, other_client, g["id"])
    set_share(other_client, g["id"], trades=True, trade_prices=True)
    acc = account(other_client)
    trade(other_client, acc["id"], "2330.TW", "buy", trading_day(3), 1000, 1000)
    feed = client.get(f"{API}/groups/{g['id']}/feed").json()["items"]
    item = next(i for i in feed if i["type"] == "trade")
    r = client.post(f"{API}/groups/{g['id']}/comments", json={"target": f"trade:{item['id']}", "body": "買得好"})
    assert r.status_code == 201, r.text
    assert remove(other_client, acc["id"], "2330.TW").status_code == 200
    with Session(engine) as db:
        assert list(db.scalars(select(GroupComment))) == []
    assert [i for i in client.get(f"{API}/groups/{g['id']}/feed").json()["items"] if i["type"] == "trade"] == []


def test_pausing_keeps_the_plan_for_resuming(client, engine):
    """Pausing changes only ``active`` (and ``updated_at``): the plan's amount, days and dates stay for 恢復."""
    acc = account(client)
    p = plan(client, acc["id"], "0050.TW", note="薪轉")
    trade(client, acc["id"], "0050.TW", "buy", date(2025, 3, 3), 1000, 150)
    assert remove(client, acc["id"], "0050.TW", pause_plans="true").status_code == 200
    with Session(engine) as db:
        row = db.get(RecurringPlan, p["id"])
        assert (row.active, row.amount, row.days_of_month, row.note) == (False, 5000, [6], "薪轉")


def test_a_plan_with_no_debit_left_is_not_counted(client, monkeypatch):
    """「還在進行」 is the web's ``planStatus === "active"``: active, end date not passed, and a next debit day
    (``next_date``). A plan ending before its next debit day offers nothing more, so the response does not say it
    will draft the stock again — and the dialog offers no 「同時暫停」 for it either."""
    today = date(2026, 11, 17)
    for mod in (txn_svc, recurring_svc):
        monkeypatch.setattr(mod, "today_taipei", lambda: today)
    acc = account(client)
    done = plan(client, acc["id"], "0050.TW", start_date="2026-01-01", end_date="2026-11-30")  # next 6th: 12/6
    going = plan(client, acc["id"], "0050.TW", start_date="2026-01-01", end_date="2026-12-31")
    by_id = {p["id"]: p for p in client.get(f"{API}/recurring").json()}
    assert by_id[done["id"]]["next_date"] is None and by_id[going["id"]]["next_date"] is not None
    trade(client, acc["id"], "0050.TW", "buy", date(2025, 3, 3), 1000, 150)
    r = remove(client, acc["id"], "0050.TW")
    assert (r.json()["plans_paused"], r.json()["plans_running"]) == (0, 1)
    trade(client, acc["id"], "0050.TW", "buy", date(2025, 3, 3), 1000, 150)
    r = remove(client, acc["id"], "0050.TW", pause_plans="true")
    assert (r.json()["plans_paused"], r.json()["plans_running"]) == (1, 0)
    active = {x["id"]: x["active"] for x in client.get(f"{API}/recurring").json()}
    assert active == {done["id"]: True, going["id"]: False}  # only the one with a debit ahead was paused


def test_a_look_alike_symbol_in_the_same_account_stays(client, engine):
    """Exact match on the stored symbol: 2330.TW does not take 2330R.TW (or any prefix match) with it."""
    acc = account(client)
    trade(client, acc["id"], "2330.TW", "buy", date(2025, 3, 3), 1000, 1000)
    with Session(engine) as db:
        user_id = db.scalar(select(Transaction.user_id))
        for sym in ("2330R.TW", "2330"):
            db.add(Transaction(id=new_id("txn"), user_id=user_id, account_id=acc["id"], symbol=sym, type="buy",
                               trade_date=date(2025, 3, 4), quantity=1000, price=10, amount=10000, currency="TWD",
                               created_at=now_utc(), updated_at=now_utc()))
        db.commit()
    r = remove(client, acc["id"], "2330")
    assert r.status_code == 200 and (r.json()["symbol"], r.json()["deleted"]) == ("2330.TW", 1)
    with Session(engine) as db:
        left = sorted(db.scalars(select(Transaction.symbol).where(Transaction.account_id == acc["id"])))
    assert left == ["2330", "2330R.TW"]


def test_a_us_stock_goes_too(client):
    """US holdings are outside the automatic dividends (``is_tw`` false): the whole stock still goes."""
    usd = account(client, "國泰－複委託", broker="國泰證券", currency="USD", fee_discount=1)
    twd = account(client)
    trade(client, usd["id"], "NVDA", "buy", date(2025, 3, 3), 10, 120)
    trade(client, usd["id"], "NVDA", "buy", date(2025, 4, 1), 5, 100)
    trade(client, usd["id"], "NVDA", "sell", date(2025, 5, 2), 3, 130)
    keep = trade(client, twd["id"], "2330.TW", "buy", date(2025, 3, 3), 1000, 1000)
    r = remove(client, usd["id"], "nvda")
    assert r.status_code == 200, r.text
    assert (r.json()["symbol"], r.json()["deleted"]) == ("NVDA", 3)
    assert txns(client, usd["id"]) == []
    assert [t["id"] for t in txns(client, twd["id"])] == [keep["id"]]
    assert held(client) == {"2330.TW": 1000}


def test_cash_rows_tagged_with_the_stock_are_counted_and_deleted(client):
    """A fee or tax row carrying the stock's symbol is one of its records (listed under it, so deleted with it);
    an untagged cash row of the account stays."""
    acc = account(client)
    trade(client, acc["id"], "2330.TW", "buy", date(2025, 3, 3), 1000, 1000)
    for body in ({"type": "fee", "symbol": "2330", "amount": 20}, {"type": "tax", "symbol": "2330.TW", "amount": 15},
                 {"type": "fee", "amount": 50}):
        r = client.post(f"{API}/transactions", json={"account_id": acc["id"], "trade_date": "2025-03-10", **body})
        assert r.status_code == 201, r.text
    listed = client.get(f"{API}/transactions", params={"account_id": acc["id"], "symbol": "2330"}).json()["items"]
    assert len(listed) == 3  # what the records under the stock show is what goes
    r = remove(client, acc["id"], "2330.TW")
    assert r.json()["deleted"] == 3
    assert [(t["type"], t["symbol"]) for t in txns(client, acc["id"])] == [("fee", None)]
