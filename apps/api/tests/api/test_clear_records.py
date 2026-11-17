"""``GET``／``DELETE /portfolio/records`` (清除所有持倉；產品負責人 2026-11-17：「也要有清除所有持倉的功能」):
every record of one account, or of every account, goes in one transaction — the same rules as 刪除這檔 for each
stock — while the accounts, the watchlist, other users and plans outside the scope stay; 定期定額 are only paused
when asked, and no automatic dividend comes back."""

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
from forliosa.models import AutoDividendSkip, GroupComment, GroupReaction, MarketEvent, RecurringPlan, Transaction
from forliosa.services.auto_dividends import sync_all_users
from forliosa.timeutil import now_utc
from tests.api.m5 import API, account, join, make_group, me_id, set_share, trade, trading_day

VIEW = "X-Forliosa-View-As"


@pytest.fixture()
def notices(engine, market):
    """Real (non-demo) ex-dividend notices in the archive, as ``test_delete_holding`` sets them up."""
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


def clear(client, account_id: str | None = None, **params):
    if account_id is not None:
        params["account_id"] = account_id
    return client.delete(f"{API}/portfolio/records", params=params)


def counts(client) -> dict:
    r = client.get(f"{API}/portfolio/records")
    assert r.status_code == 200, r.text
    return r.json()


def txns(client, account_id: str | None = None) -> list[dict]:
    params = {"limit": 200} | ({"account_id": account_id} if account_id else {})
    r = client.get(f"{API}/transactions", params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def held(client) -> dict[str, float]:
    return {h["symbol"]: h["quantity"] for h in client.get(f"{API}/portfolio/holdings").json()}


def plan(client, account_id: str, symbol: str, **kw) -> dict:
    r = client.post(f"{API}/recurring", json={"account_id": account_id, "symbol": symbol, "amount": 5000,
                                              "day_of_month": [6], **kw})
    assert r.status_code == 201, r.text
    return r.json()


def book(client, account_id: str, **body) -> dict:
    r = client.post(f"{API}/transactions", json={"account_id": account_id, **body})
    assert r.status_code == 201, r.text
    return r.json()


def test_one_account_is_cleared_and_the_rest_stays(client):
    acc = account(client)
    other = account(client, "國泰－一般")
    trade(client, acc["id"], "2330.TW", "buy", date(2025, 3, 3), 1000, 1000)
    trade(client, acc["id"], "2330.TW", "sell", date(2025, 5, 2), 300, 1010)
    trade(client, acc["id"], "0050.TW", "buy", date(2025, 3, 3), 2000, 150)
    book(client, acc["id"], symbol="2330.TW", type="cash_dividend", trade_date="2025-07-10", amount=5000)
    book(client, acc["id"], type="deposit", trade_date="2025-03-01", amount=100000)  # a cash row with no symbol
    keep = trade(client, other["id"], "2330.TW", "buy", date(2025, 3, 3), 100, 1000)
    assert client.post(f"{API}/watchlist", json={"symbol": "2454.TW"}).status_code in (200, 201)

    r = clear(client, acc["id"])
    assert r.status_code == 200, r.text
    assert r.json() == {"account_id": acc["id"], "deleted": 5, "symbols": 2, "plans_paused": 0, "plans_running": 0}
    assert txns(client, acc["id"]) == []
    assert [t["id"] for t in txns(client, other["id"])] == [keep["id"]]
    # nothing was booked (not a sell): the account is as if nothing had been recorded in it
    assert held(client) == {"2330.TW": 100}
    assert client.get(f"{API}/portfolio/closed").json() == []
    # the accounts and the watchlist stay
    assert [a["id"] for a in client.get(f"{API}/accounts").json()] == [acc["id"], other["id"]]
    assert [w["symbol"] for w in client.get(f"{API}/watchlist").json()] == ["2454.TW"]
    # cleared again: nothing left there (another tab or device did it) — its own code, as for 刪除這檔
    r = clear(client, acc["id"])
    assert r.status_code == 404
    assert r.json()["error"] == {"code": "no_records", "message": "這個帳戶沒有任何紀錄", "plans_paused": 0,
                                 "plans_running": 0}


def test_all_accounts_are_cleared(client):
    acc = account(client)
    usd = account(client, "國泰－複委託", broker="國泰證券", currency="USD", fee_discount=1)
    empty = account(client, "富邦－一般")
    trade(client, acc["id"], "2330.TW", "buy", date(2025, 3, 3), 1000, 1000)
    trade(client, acc["id"], "0050.TW", "buy", date(2025, 3, 3), 2000, 150)
    trade(client, usd["id"], "NVDA", "buy", date(2025, 3, 3), 10, 120)
    trade(client, usd["id"], "2330.TW", "buy", date(2025, 3, 3), 10, 1000)
    assert client.post(f"{API}/watchlist", json={"symbol": "2454.TW"}).status_code in (200, 201)

    r = clear(client, all_accounts="true")
    assert r.status_code == 200, r.text
    # the same stock in two accounts counts once
    assert r.json() == {"account_id": None, "deleted": 4, "symbols": 3, "plans_paused": 0, "plans_running": 0}
    assert txns(client) == [] and held(client) == {}
    assert [a["id"] for a in client.get(f"{API}/accounts").json()] == [acc["id"], usd["id"], empty["id"]]
    assert [w["symbol"] for w in client.get(f"{API}/watchlist").json()] == ["2454.TW"]
    r = clear(client, all_accounts="true")
    assert r.status_code == 404
    assert r.json()["error"] == {"code": "no_records", "message": "沒有任何紀錄", "plans_paused": 0, "plans_running": 0}


def test_the_scope_is_never_implied(client):
    """A bare DELETE is a 422, not a wipe of everything; so is naming both scopes."""
    acc = account(client)
    trade(client, acc["id"], "2330.TW", "buy", date(2025, 3, 3), 1000, 1000)
    for r in (clear(client), clear(client, all_accounts="false"), clear(client, acc["id"], all_accounts="true")):
        assert r.status_code == 422 and r.json()["error"]["code"] == "scope_required", r.text
    assert len(txns(client)) == 1


def test_other_users_are_untouched(client, other_client):
    mine = account(client)
    theirs = account(other_client)
    trade(client, mine["id"], "2330.TW", "buy", date(2025, 3, 3), 1000, 1000)
    trade(other_client, theirs["id"], "2330.TW", "buy", date(2025, 3, 3), 2000, 1000)
    plan(other_client, theirs["id"], "0050.TW")
    r = clear(client, theirs["id"])
    assert r.status_code == 404 and r.json()["error"] == {"code": "not_found", "message": "找不到帳戶"}
    assert clear(client, "acc_nope").status_code == 404
    r = clear(client, all_accounts="true", pause_plans="true")
    assert (r.json()["deleted"], r.json()["plans_paused"]) == (1, 0)
    assert held(other_client) == {"2330.TW": 2000}
    assert [p["active"] for p in other_client.get(f"{API}/recurring").json()] == [True]
    assert counts(other_client)["records"] == 1


def test_counts_per_account(client, other_client):
    acc = account(client)
    other = account(client, "國泰－一般")
    empty = account(client, "富邦－一般")
    trade(client, acc["id"], "2330.TW", "buy", date(2025, 3, 3), 1000, 1000)
    trade(client, acc["id"], "2330.TW", "sell", date(2025, 5, 2), 300, 1010)
    book(client, acc["id"], symbol="2330.TW", type="cash_dividend", trade_date="2025-07-10", amount=5000)
    book(client, acc["id"], type="deposit", trade_date="2025-03-01", amount=100000)
    trade(client, other["id"], "2330.TW", "buy", date(2025, 3, 3), 100, 1000)
    trade(client, other["id"], "0050.TW", "buy", date(2025, 3, 3), 100, 150)
    plan(client, other["id"], "0050.TW")
    plan(client, other["id"], "0056.TW", active=False)  # paused: not counted
    trade(other_client, account(other_client)["id"], "2330.TW", "buy", date(2025, 3, 3), 1, 1000)

    c = counts(client)
    assert {k: c[k] for k in ("records", "trades", "dividends", "symbols", "plans_running")} == {
        "records": 6, "trades": 4, "dividends": 1, "symbols": 2, "plans_running": 1}
    assert c["accounts"] == [
        {"account_id": acc["id"], "records": 4, "trades": 2, "dividends": 1, "symbols": 1, "plans_running": 0},
        {"account_id": other["id"], "records": 2, "trades": 2, "dividends": 0, "symbols": 2, "plans_running": 1},
        {"account_id": empty["id"], "records": 0, "trades": 0, "dividends": 0, "symbols": 0, "plans_running": 0},
    ]
    # an account with no record: nothing to clear
    r = clear(client, empty["id"])
    assert r.status_code == 404 and r.json()["error"]["code"] == "no_records"


def test_read_only_viewing_cannot_clear_or_count(client, other_client):
    g = make_group(client)
    join(client, other_client, g["id"])
    acc = account(client)
    trade(client, acc["id"], "2330.TW", "buy", date(2025, 3, 3), 1000, 1000)
    r = client.post(f"{API}/delegations", json={"viewer_user_id": me_id(other_client), "scope": "all"})
    assert r.status_code == 201, r.text
    headers = {VIEW: r.json()["id"]}
    for params in ({"all_accounts": "true"}, {"account_id": acc["id"]}):
        r = other_client.delete(f"{API}/portfolio/records", headers=headers, params=params)
        assert r.status_code == 403 and r.json()["error"]["code"] == "read_only"
    r = other_client.get(f"{API}/portfolio/records", headers=headers)
    assert r.status_code == 403 and r.json()["error"]["code"] == "view_as_not_allowed"
    assert held(client) == {"2330.TW": 1000}


def test_plans_are_paused_only_in_the_scope_and_only_when_asked(client):
    acc = account(client)
    other = account(client, "國泰－一般")
    a1 = plan(client, acc["id"], "0050.TW")
    a2 = plan(client, acc["id"], "0056.TW", note="薪轉")  # no record of it yet: still in the account, still paused
    b1 = plan(client, other["id"], "0050.TW")
    trade(client, acc["id"], "0050.TW", "buy", date(2025, 3, 3), 1000, 150)
    trade(client, other["id"], "0050.TW", "buy", date(2025, 3, 3), 1000, 150)

    r = clear(client, acc["id"])
    assert (r.json()["plans_paused"], r.json()["plans_running"]) == (0, 2)
    assert {x["id"]: x["active"] for x in client.get(f"{API}/recurring").json()} == {
        a1["id"]: True, a2["id"]: True, b1["id"]: True}

    trade(client, acc["id"], "0050.TW", "buy", date(2025, 3, 3), 1000, 150)
    r = clear(client, acc["id"], pause_plans="true")
    assert (r.json()["plans_paused"], r.json()["plans_running"]) == (2, 0)
    # paused, not deleted (設定 can resume them, with their amount, days and note); the other account's plan runs on
    assert {x["id"]: x["active"] for x in client.get(f"{API}/recurring").json()} == {
        a1["id"]: False, a2["id"]: False, b1["id"]: True}
    assert [x["note"] for x in client.get(f"{API}/recurring").json() if x["id"] == a2["id"]] == ["薪轉"]

    r = clear(client, all_accounts="true", pause_plans="true")
    assert (r.json()["deleted"], r.json()["plans_paused"], r.json()["plans_running"]) == (1, 1, 0)
    assert all(not x["active"] for x in client.get(f"{API}/recurring").json())


def test_a_plan_with_no_debit_left_is_not_counted(client, monkeypatch):
    """The same 「還在進行」 as 刪除這檔 (``planStatus === "active"``): a plan ending before its next debit day is
    neither paused nor counted as running."""
    today = date(2026, 11, 17)
    for mod in (txn_svc, recurring_svc):
        monkeypatch.setattr(mod, "today_taipei", lambda: today)
    acc = account(client)
    done = plan(client, acc["id"], "0050.TW", start_date="2026-01-01", end_date="2026-11-30")  # next 6th: 12/6
    going = plan(client, acc["id"], "0050.TW", start_date="2026-01-01", end_date="2026-12-31")
    trade(client, acc["id"], "0050.TW", "buy", date(2025, 3, 3), 1000, 150)
    assert counts(client)["plans_running"] == 1
    r = clear(client, acc["id"], pause_plans="true")
    assert (r.json()["plans_paused"], r.json()["plans_running"]) == (1, 0)
    assert {x["id"]: x["active"] for x in client.get(f"{API}/recurring").json()} == {
        done["id"]: True, going["id"]: False}


def test_automatic_dividends_do_not_come_back(client, notices, engine):
    notices("2330.TW", date(2026, 6, 11), cash="5.00000000")
    notices("2317.TW", date(2026, 7, 16), cash="5.00000000")
    acc = account(client)
    other = account(client, "國泰－一般")
    trade(client, acc["id"], "2330.TW", "buy", date(2026, 5, 4), 1000, 1000)
    trade(client, other["id"], "2317.TW", "buy", date(2026, 5, 4), 1000, 200)
    auto = next(t for t in txns(client, acc["id"]) if t["source"] == "auto")
    # a deleted automatic dividend leaves a skip behind
    assert client.delete(f"{API}/transactions/{auto['id']}").status_code == 204
    with Session(engine) as db:
        assert len(list(db.scalars(select(AutoDividendSkip)))) == 1

    r = clear(client, acc["id"])
    assert r.status_code == 200 and r.json()["deleted"] == 1
    with Session(engine) as db:
        assert list(db.scalars(select(AutoDividendSkip))) == []
    # the daily sync books nothing in the cleared account; the other account keeps its dividend
    assert sync_all_users(lambda: Session(engine), notices.md).changed is False
    assert txns(client, acc["id"]) == []
    assert sorted((t["symbol"], t["type"], t["source"]) for t in txns(client, other["id"])) == [
        ("2317.TW", "buy", "manual"), ("2317.TW", "cash_dividend", "auto")]
    # recorded again later, the dividend is booked afresh (the old skip went with the records)
    trade(client, acc["id"], "2330.TW", "buy", date(2026, 5, 4), 2000, 1000)
    again = [t for t in txns(client, acc["id"]) if t["type"] == "cash_dividend"]
    assert [(t["source"], t["quantity"]) for t in again] == [("auto", 2000)]

    r = clear(client, all_accounts="true")
    assert r.status_code == 200 and r.json()["deleted"] == 4
    assert sync_all_users(lambda: Session(engine), notices.md).changed is False
    assert txns(client) == []


def test_books_that_were_already_inconsistent_can_be_cleared(client, engine):
    acc = account(client)
    trade(client, acc["id"], "0050.TW", "buy", date(2025, 3, 3), 1000, 150)
    with Session(engine) as db:
        user_id = db.scalar(select(Transaction.user_id))
        db.add(Transaction(id=new_id("txn"), user_id=user_id, account_id=acc["id"], symbol="2330.TW", type="sell",
                           trade_date=date(2025, 3, 4), quantity=500, price=1000, amount=500000, currency="TWD",
                           created_at=now_utc(), updated_at=now_utc()))
        db.commit()
    r = client.post(f"{API}/transactions", json={"account_id": acc["id"], "symbol": "0050.TW", "type": "buy",
                                                 "trade_date": "2025-03-05", "quantity": 1, "price": 150})
    assert r.status_code == 422 and r.json()["error"]["code"] == "ledger_inconsistent"
    assert clear(client, acc["id"]).json()["deleted"] == 2
    assert txns(client, acc["id"]) == []


def test_group_feed_threads_go_unless_another_account_backs_them(client, other_client, engine):
    """As with single deletes: a feed item no record backs any more loses its comments and reactions; one that the
    member's other account still backs (a buy of the same stock the same day) keeps them."""
    g = make_group(client)
    join(client, other_client, g["id"])
    set_share(other_client, g["id"], trades=True, trade_prices=True)
    acc = account(other_client)
    second = account(other_client, "國泰－一般")
    trade(other_client, acc["id"], "2330.TW", "buy", trading_day(3), 1000, 1000)
    trade(other_client, acc["id"], "0050.TW", "buy", trading_day(3), 1000, 150)
    trade(other_client, second["id"], "0050.TW", "buy", trading_day(3), 10, 150)
    feed = [i for i in client.get(f"{API}/groups/{g['id']}/feed").json()["items"] if i["type"] == "trade"]
    assert len(feed) == 2
    for item in feed:
        r = client.post(f"{API}/groups/{g['id']}/comments", json={"target": f"trade:{item['id']}", "body": "買得好"})
        assert r.status_code == 201, r.text
        r = client.put(f"{API}/groups/{g['id']}/reactions", json={"target": f"trade:{item['id']}", "emoji": "👍"})
        assert r.status_code in (200, 201), r.text

    assert clear(other_client, acc["id"]).status_code == 200
    left = [i for i in client.get(f"{API}/groups/{g['id']}/feed").json()["items"] if i["type"] == "trade"]
    assert len(left) == 1  # 0050 is still backed by the second account
    with Session(engine) as db:
        assert [c.target for c in db.scalars(select(GroupComment))] == [f"trade:{left[0]['id']}"]
        assert [x.target for x in db.scalars(select(GroupReaction))] == [f"trade:{left[0]['id']}"]

    assert clear(other_client, all_accounts="true").status_code == 200
    with Session(engine) as db:
        assert list(db.scalars(select(GroupComment))) == [] and list(db.scalars(select(GroupReaction))) == []


def test_pausing_keeps_the_plan_for_resuming(client, engine):
    acc = account(client)
    p = plan(client, acc["id"], "0050.TW", note="薪轉")
    trade(client, acc["id"], "0050.TW", "buy", date(2025, 3, 3), 1000, 150)
    assert clear(client, acc["id"], pause_plans="true").status_code == 200
    with Session(engine) as db:
        row = db.get(RecurringPlan, p["id"])
        assert (row.active, row.amount, row.days_of_month, row.note) == (False, 5000, [6], "薪轉")


def test_nothing_left_to_clear_still_pauses_the_plans_when_asked(client):
    """Cleared in another tab without pausing, then cleared again here with 「同時暫停」 checked: the 404
    ``no_records`` (nothing to delete) still pauses the plans in the scope, as asked, and says so — only those in the
    scope, and a 404 without ``pause_plans`` changes nothing."""
    acc = account(client)
    other = account(client, "國泰－一般")
    a1 = plan(client, acc["id"], "0050.TW")
    a2 = plan(client, acc["id"], "0056.TW")
    b1 = plan(client, other["id"], "0050.TW")
    trade(client, acc["id"], "0050.TW", "buy", date(2025, 3, 3), 1000, 150)
    assert clear(client, acc["id"]).json()["plans_running"] == 2

    r = clear(client, acc["id"])  # not asked to pause: nothing changes, the 404 says what still runs
    assert r.status_code == 404
    assert r.json()["error"] == {"code": "no_records", "message": "這個帳戶沒有任何紀錄", "plans_paused": 0,
                                 "plans_running": 2}
    assert all(x["active"] for x in client.get(f"{API}/recurring").json())

    r = clear(client, acc["id"], pause_plans="true")
    assert r.status_code == 404
    assert r.json()["error"] == {"code": "no_records", "message": "這個帳戶沒有任何紀錄", "plans_paused": 2,
                                 "plans_running": 0}
    assert {x["id"]: x["active"] for x in client.get(f"{API}/recurring").json()} == {
        a1["id"]: False, a2["id"]: False, b1["id"]: True}

    # every account: the other account's plan is paused the same way (no record anywhere)
    r = clear(client, all_accounts="true", pause_plans="true")
    assert r.status_code == 404
    assert (r.json()["error"]["plans_paused"], r.json()["error"]["plans_running"]) == (1, 0)
    assert not any(x["active"] for x in client.get(f"{API}/recurring").json())
