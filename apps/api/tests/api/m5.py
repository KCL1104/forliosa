"""Helpers for the M5 (sharing) API tests."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from forliosa.timeutil import last_tw_trading_day, today_taipei

API = "/api/v1"
SHARE_NONE = {"returns": False, "holdings": False, "amounts": False, "trades": False, "trade_prices": False,
              "push": False}
SHARE_ALL = {k: True for k in SHARE_NONE}
SHARE_DEFAULT = {**SHARE_NONE, "returns": True}


def login(app, email: str, name: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/dev-login", json={"email": email, "display_name": name})
    assert r.status_code == 200, r.text
    return c


def me_id(client: TestClient) -> str:
    return client.get(f"{API}/me").json()["id"]


def make_group(client: TestClient, name: str = "家族投資") -> dict:
    r = client.post(f"{API}/groups", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def invite(client: TestClient, group_id: str, **body) -> dict:
    r = client.post(f"{API}/groups/{group_id}/invites", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def token_of(inv: dict) -> str:
    return inv["url"].rsplit("/invite/", 1)[1]


def join(owner: TestClient, joiner: TestClient, group_id: str, share: dict | None = None) -> dict:
    inv = invite(owner, group_id)
    r = joiner.post(f"{API}/invites/{token_of(inv)}/accept", json={"share": share or SHARE_DEFAULT})
    assert r.status_code == 200, r.text
    return r.json()


def set_share(client: TestClient, group_id: str, **toggles) -> dict:
    r = client.put(f"{API}/groups/{group_id}/share", json={**SHARE_NONE, **toggles})
    assert r.status_code == 200, r.text
    return r.json()


def account(client: TestClient, name: str = "永豐－一般", **kw) -> dict:
    body = {"name": name, "broker": "永豐金證券", "currency": "TWD", "fee_discount": 0.28, **kw}
    r = client.post(f"{API}/accounts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def trade(client: TestClient, account_id: str, symbol: str, side: str, d: date, quantity, price, **kw) -> dict:
    body = {"account_id": account_id, "symbol": symbol, "type": side, "trade_date": d.isoformat(),
            "quantity": quantity, "price": price, **kw}
    r = client.post(f"{API}/transactions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def trading_day(days_ago: int) -> date:
    return last_tw_trading_day(today_taipei() - timedelta(days=days_ago))
