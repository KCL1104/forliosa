"""The site admins' back office (``/admin``): who may call it, the overview (counts only, never key material or
emails), the news takedown blocklist and the read-only view-as refusal."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.ai.keypool import KeyPool, set_key_pool
from forliosa.config import get_settings
from forliosa.models import AiThread, AiUsage, DatasetStatus, NewsArticle, NewsBlockedDomain, PriceBackfill, PriceDaily
from forliosa.services import admin as admin_service
from forliosa.timeutil import now_utc, today_taipei
from tests.api.conftest import ADMIN_EMAIL
from tests.api.m5 import API, me_id

ADMIN = f"{API}/admin"
BLOCKED = f"{ADMIN}/news/blocked-domains"
KEYS = ("sk-ant-api03-FIRST-SECRET-KEY-VALUE", "sk-ant-api03-SECOND-SECRET-KEY-VALUE")


def error(r) -> str:
    return r.json()["error"]["code"]


def article(symbol: str, url: str, domain: str, n: int) -> NewsArticle:
    return NewsArticle(symbol=symbol, url_key=f"k{n}", url=url, title=f"標題 {n}", outlet=domain, domain=domain,
                       published_at=now_utc(), source="gdelt")


# -- who may call it ----------------------------------------------------------------------------------------------
def test_back_office_is_404_for_everyone_but_site_admins(client, other_client, admin):
    def calls(c):
        return [
            c.get(f"{ADMIN}/overview"),
            c.get(BLOCKED),
            c.post(BLOCKED, json={"domain": "example.com"}),
            c.post(BLOCKED, json={"nonsense": True}),  # 404 before the body is validated
            c.delete(f"{BLOCKED}/example.com"),
        ]

    for c in (client, other_client):
        for r in calls(c):
            assert r.status_code == 404 and error(r) == "not_found", (r.request.method, r.request.url.path, r.text)
    for r in calls(TestClient(client.app)):
        assert r.status_code == 401, (r.request.method, r.request.url.path, r.text)
    # nothing was blocked
    assert admin.get(BLOCKED).json() == []
    assert admin.get(f"{ADMIN}/overview").status_code == 200


# -- overview -------------------------------------------------------------------------------------------------------
@pytest.fixture()
def key_pool():
    pool = KeyPool.from_keys([(1, KEYS[0]), (2, KEYS[1])], client_factory=lambda key: object())
    pool.get(1).workspace_id = "wrkspc_test_one"
    set_key_pool(pool)
    yield pool
    set_key_pool(KeyPool([]))


def test_overview_counts_users_and_never_returns_keys_or_emails(engine, client, other_client, admin, key_pool,
                                                                 monkeypatch):
    monkeypatch.setattr(get_settings(), "price_history_source", "yahoo")
    owner_id = me_id(client)
    today = today_taipei()
    with Session(engine) as db:
        db.add_all([
            AiUsage(user_id=owner_id, feature="chat", model="claude-haiku", key_slot=1, cost_usd=Decimal("0.25")),
            AiUsage(user_id=owner_id, feature="chat", model="claude-haiku", key_slot=1, cost_usd=Decimal("0.5")),
            AiUsage(user_id=None, feature="why", model="claude-haiku", key_slot=2, cost_usd=Decimal("0.1")),
            AiThread(id="thr_admin_1", user_id=owner_id, title="誰拖累了我", model="claude-haiku", key_slot=1),
            DatasetStatus(key="twse-openapi/price", data_date=today, rows=1000),
            DatasetStatus(key="tdcc-opendata/distribution", data_date=today - timedelta(days=30), rows=10),
            DatasetStatus(key="yahoo-history/price", data_date=None, rows=0),
            PriceBackfill(symbol="2330.TW", source="yahoo-history", status="done", rows=2),
            PriceBackfill(symbol="9999.TW", source="yahoo-history", status="not_found", rows=0),
            PriceDaily(symbol="2330.TW", date=date(2021, 1, 4), close=Decimal("530"), source="yahoo-history"),
            PriceDaily(symbol="2330.TW", date=date(2021, 1, 5), close=Decimal("540"), source="yahoo-history"),
        ])
        db.commit()

    r = admin.get(f"{ADMIN}/overview")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["users"] == {"total": 3, "new_7d": 3}  # demo, other, admin
    assert body["ai"]["month"] == now_utc().strftime("%Y-%m")
    slots = {s["slot"]: s for s in body["ai"]["slots"]}
    assert set(slots) == {1, 2, 3}
    assert slots[1] == {"slot": 1, "configured": True, "state": "ok", "retry_in_seconds": None,
                        "workspace_id": "wrkspc_test_one", "month_cost_usd": 0.75, "month_calls": 2,
                        "monthly_budget_usd": None, "threads": 1, "last_error": None}
    assert slots[2]["month_cost_usd"] == 0.1 and slots[2]["month_calls"] == 1 and slots[2]["threads"] == 0
    assert slots[3]["state"] == "not_configured" and slots[3]["configured"] is False
    # the stalest first: no date at all, then the oldest
    assert [d["key"] for d in body["datasets"]] == ["yahoo-history/price", "tdcc-opendata/distribution",
                                                    "twse-openapi/price"]
    stale = body["datasets"][1]
    assert stale["name"] == "集保戶股權分散表" and stale["agency"] == "臺灣集中保管結算所"
    assert stale["stale"] is True and stale["days_behind"] == 30 and stale["fetched_at"].endswith("+08:00")
    fresh = body["datasets"][2]
    assert fresh["stale"] is False and fresh["days_behind"] == 0 and fresh["data_date"] == today.isoformat()
    assert body["datasets"][0]["stale"] is True and body["datasets"][0]["name"].startswith("Yahoo Finance")
    assert body["history_backfill"] == {
        "enabled": True, "rows": 2, "pending": 0,
        "symbols": {"done": 1, "not_found": 1, "mismatch": 0, "no_overlap": 0, "error": 0}}

    text = json.dumps(body, ensure_ascii=False)
    for secret in (*KEYS, "sk-ant", "SECRET"):
        assert secret not in text
    for email in ("demo@forliosa.local", "other@forliosa.local", ADMIN_EMAIL, "@"):
        assert email not in text
    assert owner_id not in text and "usr_" not in text


def test_stale_datasets_are_counted_in_trading_days(engine):
    # Monday 2026-11-16: Friday's data is one trading day behind; last Wednesday's three (Thu, Fri, Mon).
    monday = date(2026, 11, 16)
    with Session(engine) as db:
        db.add_all([DatasetStatus(key="twse-openapi/price", data_date=date(2026, 11, 13), rows=1),
                    DatasetStatus(key="tpex-openapi/price", data_date=date(2026, 11, 12), rows=1),
                    DatasetStatus(key="twse-openapi/margin", data_date=date(2026, 11, 11), rows=1)])
        db.commit()
        rows = {r["key"]: r for r in admin_service.datasets_summary(db, today=monday)}
    assert (rows["twse-openapi/price"]["stale"], rows["twse-openapi/price"]["days_behind"]) == (False, 3)
    assert (rows["tpex-openapi/price"]["stale"], rows["tpex-openapi/price"]["days_behind"]) == (False, 4)
    assert (rows["twse-openapi/margin"]["stale"], rows["twse-openapi/margin"]["days_behind"]) == (True, 5)


# -- news takedown blocklist ---------------------------------------------------------------------------------------
def test_block_and_unblock_round_trip(engine, admin, monkeypatch):
    monkeypatch.setattr(get_settings(), "news_blocked_domains", ["envpress.example"])
    with Session(engine) as db:
        db.add_all([article("2330.TW", "https://money.udn.com/a/1", "money.udn.com", 1),
                     article("2330.TW", "https://udn.com/news/2", "udn.com", 2),
                     article("2317.TW", "https://udn.com/news/3", "udn.com", 3),
                     article("2330.TW", "https://www.cna.com.tw/news/4", "cna.com.tw", 4)])
        db.commit()
    assert admin.get(BLOCKED).json() == [
        {"domain": "envpress.example", "reason": None, "created_at": None, "from_env": True}]

    r = admin.post(BLOCKED, json={"domain": " https://www.UDN.com/news/2 ", "reason": " 11/20 來函要求下架 "})
    assert r.status_code == 201, r.text
    assert r.json() == {"domain": "udn.com", "deleted_headlines": 3}  # subdomains included
    listed = admin.get(BLOCKED).json()
    assert [(b["domain"], b["reason"], b["from_env"]) for b in listed] == [
        ("udn.com", "11/20 來函要求下架", False), ("envpress.example", None, True)]
    assert listed[0]["created_at"].endswith("+08:00")
    with Session(engine) as db:
        assert db.scalars(select(NewsArticle.domain)).all() == ["cna.com.tw"]

    # blocking it again only updates the reason
    r = admin.post(BLOCKED, json={"domain": "udn.com", "reason": "再次來函"})
    assert r.json() == {"domain": "udn.com", "deleted_headlines": 0}
    assert admin.get(BLOCKED).json()[0]["reason"] == "再次來函"

    # set in the environment: listed, not removable here
    r = admin.delete(f"{BLOCKED}/envpress.example")
    assert r.status_code == 409 and error(r) == "set_in_environment"
    assert admin.delete(f"{BLOCKED}/udn.com").status_code == 204
    assert admin.delete(f"{BLOCKED}/udn.com").status_code == 404
    assert [b["domain"] for b in admin.get(BLOCKED).json()] == ["envpress.example"]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(NewsBlockedDomain)) == 0


@pytest.mark.parametrize("domain", ["udn", "", "   ", "udn .com", "https://", "a@b.com", "x" * 301])
def test_block_refuses_what_is_not_a_domain(admin, domain):
    r = admin.post(BLOCKED, json={"domain": domain})
    assert r.status_code == 422 and error(r) == "validation_error", r.text
    assert admin.get(BLOCKED).json() == []


def test_block_reason_is_one_short_line(admin):
    assert admin.post(BLOCKED, json={"domain": "udn.com", "reason": "第一行\n第二行"}).status_code == 422
    assert admin.post(BLOCKED, json={"domain": "udn.com", "reason": "長" * 201}).status_code == 422
    assert admin.post(BLOCKED, json={"domain": "udn.com", "extra": 1}).status_code == 422
    r = admin.post(BLOCKED, json={"domain": "udn.com", "reason": "  "})
    assert r.status_code == 201 and admin.get(BLOCKED).json()[0]["reason"] is None


# -- read-only viewing ------------------------------------------------------------------------------------------
def test_view_as_cannot_use_the_back_office(app, admin, client):
    """An admin viewing someone's ledger read-only: reads are not allow-listed, writes are read_only."""
    from tests.api.m5 import join, make_group

    g = make_group(client)
    join(client, admin, g["id"])
    r = client.post(f"{API}/delegations", json={"viewer_user_id": me_id(admin), "scope": "all"})
    assert r.status_code == 201, r.text
    h = {"X-Forliosa-View-As": r.json()["id"]}
    for path in ("/admin/overview", "/admin/news/blocked-domains"):
        r = admin.get(f"{API}{path}", headers=h)
        assert r.status_code == 403 and error(r) == "view_as_not_allowed", (path, r.text)
    r = admin.post(BLOCKED, json={"domain": "udn.com"}, headers=h)
    assert r.status_code == 403 and error(r) == "read_only"
    admin.post(BLOCKED, json={"domain": "cna.com.tw"})
    r = admin.delete(f"{BLOCKED}/cna.com.tw", headers=h)
    assert r.status_code == 403 and error(r) == "read_only"
    assert [b["domain"] for b in admin.get(BLOCKED).json()] == ["cna.com.tw"]
