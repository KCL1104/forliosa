"""``POST /transactions/batch`` and ``DELETE /transactions/batches/{id}`` (the statement import, 產品負責人 2026-11-16):
every row or none, booked by date with buys before sells in one strict replay, per-row errors and warnings without
writing (``dry_run``), ``source="import"`` with one batch id, and one undo for the whole batch."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from forliosa.db import session_factory
from forliosa.ids import new_id
from forliosa.models import Transaction
from forliosa.timeutil import now_utc
from tests.api.m5 import API, account, join, make_group, me_id, trade

VIEW = "X-Forliosa-View-As"


def row(symbol: str, side: str, d: str, quantity, price, **kw) -> dict:
    return {"symbol": symbol, "type": side, "trade_date": d, "quantity": quantity, "price": price, **kw}


def batch(client, account_id: str, rows: list[dict], dry_run: bool = False, **headers):
    body = {"account_id": account_id, "origin": "import", "dry_run": dry_run, "rows": rows}
    return client.post(f"{API}/transactions/batch", json=body, headers=headers)


def imported(client, account_id: str, rows: list[dict]) -> dict:
    r = batch(client, account_id, rows)
    assert r.status_code == 201, r.text
    return r.json()


def txns(client, account_id: str) -> list[dict]:
    r = client.get(f"{API}/transactions", params={"account_id": account_id, "limit": 200})
    assert r.status_code == 200, r.text
    return r.json()["items"]


def flags_of(out: dict) -> dict[int, list[tuple[str, str]]]:
    return {r["index"]: [(f["code"], f["severity"]) for f in r["flags"]] for r in out["rows"]}


def test_batch_writes_every_row_as_one_import(client):
    acc = account(client)
    rows = [row("2330", "sell", "2025-03-04", 500, 1010, fee=144, tax=1515),  # listed before the buy it needs
            row("2330.TW", "buy", "2025-03-04", 1000, 1000, fee=1425),
            row("0050.TW", "buy", "2025-03-05", 2000, "150.5", account_id=acc["id"])]
    out = imported(client, acc["id"], rows)
    assert out["dry_run"] is False and out["batch_id"].startswith("imp_") and out["auto_dividends_added"] == 0
    items = {t["id"]: t for t in txns(client, acc["id"])}
    assert set(items) == set(out["created"]) and len(out["created"]) == 3
    assert [(items[i]["symbol"], items[i]["type"]) for i in out["created"]] == [  # in the request's order
        ("2330.TW", "sell"), ("2330.TW", "buy"), ("0050.TW", "buy")]
    assert all(t["source"] == "import" and t["import_batch_id"] == out["batch_id"] for t in items.values())
    sell = items[out["created"][0]]
    assert (sell["amount"], sell["fee"], sell["tax"], sell["note"]) == (505000, 144, 1515, "")
    holdings = {h["symbol"]: h["quantity"] for h in client.get(f"{API}/portfolio/holdings").json()}
    assert holdings == {"2330.TW": 500, "0050.TW": 2000}
    # the buy is entered before the sell of the same day, so the ledger books it first
    with session_factory()() as db:
        created = {t.id: t.created_at for t in db.scalars(select(Transaction))}
    assert created[out["created"][1]] < created[out["created"][0]]
    manual = trade(client, acc["id"], "2330.TW", "buy", date(2025, 4, 1), 100, 1000)
    assert manual["import_batch_id"] is None and manual["source"] == "manual"


def test_any_bad_row_rejects_the_whole_batch(client):
    acc = account(client)
    other = account(client, "第二個帳戶")
    rows = [row("2330.TW", "buy", "2025-03-03", 1000, 1000),
            row("2330.TW", "sell", "2025-03-05", 2000, 1010),
            row("ZZZZ", "buy", "2025-03-03", 1000, 10),
            {"symbol": "2330.TW", "type": "cash_dividend", "trade_date": "2025-07-10", "amount": 5000},
            row("2330.TW", "buy", "2099-01-02", 1, 1000),
            row("2330.TW", "buy", "2025-03-03", 1, 1000, account_id=other["id"]),
            row("2330.TW", "buy", "2025-03-03", "1.5", 1000),
            row("2330.TW", "buy", "1989-12-29", 1, 10)]
    r = batch(client, acc["id"], rows)
    assert r.status_code == 422, r.text
    err = r.json()["error"]
    assert err["code"] == "batch_rejected" and err["message"] == "有 7 筆不能匯入，整批都沒有寫入。"
    assert [(e["index"], e["code"]) for e in err["rows"]] == [
        (1, "oversell"), (2, "unknown_symbol"), (3, "unsupported_type"), (4, "bad_date"), (5, "account_mismatch"),
        (6, "validation_error"), (7, "bad_date")]
    assert err["rows"][0]["message"] == "賣出 2,000 股，超過當時持有的 1,000 股。"
    assert err["rows"][2]["message"] == "匯入只收買進和賣出。"
    assert err["rows"][3]["message"] == "日期不能在未來。"
    assert txns(client, acc["id"]) == [] and txns(client, other["id"]) == []


def test_dry_run_flags_rows_without_writing(client):
    acc = account(client)
    trade(client, acc["id"], "2330.TW", "buy", date(2025, 3, 3), 1000, 1000)
    trade(client, acc["id"], "2330.TW", "sell", date(2025, 3, 10), 500, 1050)  # e.g. recorded at that day's close
    rows = [row("2330.TW", "buy", "2025-03-03", 1000, "1000.00"),
            row("2330", "sell", "2025-03-10", 500, 1046),
            row("2317.TW", "buy", "2025-03-04", 1000, 100),
            row("2317.TW", "buy", "2025-03-04", 1000, 100),
            row("2317.TW", "sell", "2025-03-05", 3000, 105),
            row("ZZZZ", "buy", "2025-03-04", 1, 1)]
    r = batch(client, acc["id"], rows, dry_run=True)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["dry_run"] is True and out["ok"] is False and out["problems"] == []
    assert flags_of(out) == {0: [("duplicate", "warning")], 1: [("possible_duplicate", "warning")], 2: [],
                             3: [("duplicate", "warning")], 4: [("oversell", "error")],
                             5: [("unknown_symbol", "error")]}
    messages = {r["index"]: [f["message"] for f in r["flags"]] for r in out["rows"]}
    assert messages[0] == ["2025/3/3 已經記過一筆一樣的。"]
    assert messages[1] == ["2025/3/10 已經記過一筆同樣股數的賣出，價格 1,050。"]
    assert messages[3] == ["這次匯入裡，同一天有另一筆一樣的。"]
    assert messages[4] == ["賣出 3,000 股，超過當時持有的 2,000 股。"]
    assert len(txns(client, acc["id"])) == 2  # nothing written
    # warnings alone do not stop the import
    ok = batch(client, acc["id"], rows[2:4], dry_run=True).json()
    assert ok["ok"] is True and flags_of(ok) == {0: [], 1: [("duplicate", "warning")]}
    assert len(imported(client, acc["id"], rows[2:4])["created"]) == 2


def test_batch_sell_that_breaks_a_later_sell_is_blamed(client):
    acc = account(client)
    trade(client, acc["id"], "2330.TW", "buy", date(2025, 3, 3), 1000, 1000)
    trade(client, acc["id"], "2330.TW", "sell", date(2025, 3, 20), 1000, 1050)
    rows = [row("2330.TW", "buy", "2025-03-04", 200, 1000), row("2330.TW", "sell", "2025-03-10", 300, 1020)]
    r = batch(client, acc["id"], rows)
    assert r.status_code == 422, r.text
    message = "匯入以後帳目對不起來：2025/3/20 賣出台積電 1,000 股，超過當時持有的 900 股。"
    assert r.json()["error"]["rows"] == [{"index": 1, "code": "ledger_inconsistent", "message": message}]
    assert len(txns(client, acc["id"])) == 2


def test_books_already_inconsistent_are_a_problem_of_the_whole_batch(client):
    acc = account(client)
    with session_factory()() as db:  # a sell of shares never bought (written past the checks)
        db.add(Transaction(id=new_id("txn"), user_id=me_id(client), account_id=acc["id"], symbol="2317.TW",
                           type="sell", trade_date=date(2025, 3, 3), quantity=Decimal(100), price=Decimal(100),
                           amount=Decimal(10000), source="manual", created_at=now_utc(), updated_at=now_utc()))
        db.commit()
    rows = [row("2330.TW", "buy", "2025-03-04", 1000, 1000)]
    out = batch(client, acc["id"], rows, dry_run=True).json()
    assert out["ok"] is False and flags_of(out) == {0: []}
    problem = "匯入以後帳目對不起來：2025/3/3 賣出鴻海 100 股，超過當時持有的 0 股。"
    assert out["problems"] == [{"code": "ledger_inconsistent", "message": problem}]
    r = batch(client, acc["id"], rows)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["message"] == "帳目對不起來，整批都沒有寫入。"
    assert err["rows"] == [{"index": None, "code": "ledger_inconsistent", "message": problem}]


def test_undo_deletes_the_whole_batch(client):
    acc = account(client)
    out = imported(client, acc["id"], [row("2330.TW", "buy", "2025-03-03", 1000, 1000),
                                       row("2330.TW", "sell", "2025-03-05", 400, 1010),
                                       row("0050.TW", "buy", "2025-03-05", 100, 150)])
    manual = trade(client, acc["id"], "2330.TW", "buy", date(2025, 4, 1), 100, 1000)
    # deleting the rows one by one fails on the buy the sell depends on; the batch goes at once
    r = client.delete(f"{API}/transactions/batches/{out['batch_id']}")
    assert r.status_code == 200, r.text
    assert r.json() == {"batch_id": out["batch_id"], "deleted": 3}
    assert [t["id"] for t in txns(client, acc["id"])] == [manual["id"]]
    r = client.delete(f"{API}/transactions/batches/{out['batch_id']}")
    assert r.status_code == 404 and r.json()["error"] == {"code": "not_found", "message": "找不到這次匯入"}


def test_undo_is_refused_while_later_rows_depend_on_it(client):
    acc = account(client)
    out = imported(client, acc["id"], [row("2330.TW", "buy", "2025-03-03", 1000, 1000)])
    sell = trade(client, acc["id"], "2330.TW", "sell", date(2025, 3, 10), 600, 1050)
    r = client.delete(f"{API}/transactions/batches/{out['batch_id']}")
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "ledger_inconsistent"
    assert err["message"] == ("之後的交易用到這次匯入的股數，不能整批復原："
                              "2025/3/10 賣出台積電 600 股，超過當時持有的 0 股。")
    assert len(txns(client, acc["id"])) == 2
    assert client.delete(f"{API}/transactions/{sell['id']}").status_code == 204
    assert client.delete(f"{API}/transactions/batches/{out['batch_id']}").status_code == 200
    assert txns(client, acc["id"]) == []


def test_imported_rows_stay_imported_when_edited(client):
    acc = account(client)
    out = imported(client, acc["id"], [row("2330.TW", "buy", "2025-03-03", 1000, 1000)])
    r = client.patch(f"{API}/transactions/{out['created'][0]}", json={"source": "manual", "price": 1005})
    assert r.status_code == 200, r.text
    assert (r.json()["source"], r.json()["price"], r.json()["import_batch_id"]) == ("import", 1005, out["batch_id"])


def test_only_your_own_accounts_and_batches(client, other_client):
    mine = account(client)
    theirs = account(other_client)
    out = imported(other_client, theirs["id"], [row("2330.TW", "buy", "2025-03-03", 1000, 1000)])
    for dry_run in (True, False):
        r = batch(client, theirs["id"], [row("2330.TW", "buy", "2025-03-03", 1, 1)], dry_run=dry_run)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert client.delete(f"{API}/transactions/batches/{out['batch_id']}").status_code == 404
    assert len(txns(other_client, theirs["id"])) == 1 and txns(client, mine["id"]) == []


def test_request_limits(client):
    acc = account(client)
    one = row("2330.TW", "buy", "2025-03-03", 1, 1000)
    for body in ({"account_id": acc["id"], "rows": []},
                 {"account_id": acc["id"], "rows": [one] * 201},
                 {"account_id": acc["id"], "rows": [{**one, "source": "import"}]},
                 {"account_id": acc["id"], "origin": "csv", "rows": [one]},
                 {"account_id": acc["id"], "rows": [{**one, "quantity": -1}]}):
        r = client.post(f"{API}/transactions/batch", json=body)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error", r.text
    assert txns(client, acc["id"]) == []


def test_read_only_viewing_cannot_import_or_undo(client, other_client):
    g = make_group(client)
    join(client, other_client, g["id"])
    acc = account(client)
    out = imported(client, acc["id"], [row("2330.TW", "buy", "2025-03-03", 1000, 1000)])
    r = client.post(f"{API}/delegations", json={"viewer_user_id": me_id(other_client), "scope": "all"})
    assert r.status_code == 201, r.text
    h = {VIEW: r.json()["id"]}
    for dry_run in (True, False):
        r = batch(other_client, acc["id"], [row("2330.TW", "buy", "2025-03-04", 1, 1000)], dry_run=dry_run, **h)
        assert r.status_code == 403 and r.json()["error"]["code"] == "read_only", r.text
    r = other_client.delete(f"{API}/transactions/batches/{out['batch_id']}", headers=h)
    assert r.status_code == 403 and r.json()["error"]["code"] == "read_only"
    # the viewer sees the imported rows like any other
    seen = other_client.get(f"{API}/transactions", headers=h).json()["items"]
    assert [(t["source"], t["import_batch_id"]) for t in seen] == [("import", out["batch_id"])]
    assert len(txns(client, acc["id"])) == 1


def test_schema_and_service_agree_on_the_row_limit():
    from forliosa.api import schemas
    from forliosa.services import transactions

    assert schemas.BATCH_MAX_ROWS == transactions.BATCH_MAX_ROWS == 200
