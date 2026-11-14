"""Input guards on transactions (2026-11-14 review): no dates outside 1990..today, no nulls for required fields."""
from __future__ import annotations

API = "/api/v1"


def _account(client) -> str:
    r = client.post(f"{API}/accounts", json={"name": "永豐", "currency": "TWD"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _buy(account_id: str, trade_date: str) -> dict:
    return {"account_id": account_id, "symbol": "2330", "type": "buy", "trade_date": trade_date,
            "quantity": 1000, "price": 600}


def test_trade_dates_must_be_between_1990_and_today(client):
    acc = _account(client)
    # a year-1 date used to be accepted and then crash every ledger read with an OverflowError (500)
    early = client.post(f"{API}/transactions", json=_buy(acc, "0001-01-05"))
    assert early.status_code == 422 and "1990" in early.text
    future = client.post(f"{API}/transactions", json=_buy(acc, "2099-01-05"))
    assert future.status_code == 422 and "未來" in future.text
    ok = client.post(f"{API}/transactions", json=_buy(acc, "2024-03-05"))
    assert ok.status_code == 201, ok.text
    assert client.get(f"{API}/portfolio/summary").status_code == 200
    moved = client.patch(f"{API}/transactions/{ok.json()['id']}", json={"trade_date": "2099-01-05"})
    assert moved.status_code == 422


def test_patch_rejects_nulls_for_required_fields(client):
    acc = _account(client)
    t = client.post(f"{API}/transactions", json=_buy(acc, "2024-03-05")).json()
    for field in ("type", "trade_date", "account_id"):
        r = client.patch(f"{API}/transactions/{t['id']}", json={field: None})
        assert r.status_code == 422, (field, r.text)
    # optional numbers may still be cleared
    assert client.patch(f"{API}/transactions/{t['id']}", json={"note": "改了"}).status_code == 200
