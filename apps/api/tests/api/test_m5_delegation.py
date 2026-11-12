"""M5 read-only delegations: CRUD, candidates, X-Forliosa-View-As allow-list (default deny), account scoping."""

from __future__ import annotations

import pytest

from tests.api.m5 import API, account, join, login, make_group, me_id, trade, trading_day

VIEW = "X-Forliosa-View-As"


@pytest.fixture()
def family(app, client, other_client):
    """Owner (``client``) with two accounts, viewer (``other_client``) in a shared group, a third stranger."""
    g = make_group(client)
    join(client, other_client, g["id"])
    a1 = account(client, "爸爸－永豐", )
    a2 = account(client, "爸爸－秘密帳戶")
    trade(client, a1["id"], "2330.TW", "buy", trading_day(60), 1000, 500)
    trade(client, a2["id"], "2317.TW", "buy", trading_day(60), 2000, 100, note="私人備註")
    plan = client.post(f"{API}/recurring", json={"account_id": a2["id"], "symbol": "0050.TW", "amount": 3000,
                                                 "day_of_month": [6, 16, 26]})
    assert plan.status_code == 201, plan.text
    stranger = login(app, "stranger@forliosa.local", "陌生人")
    return {"group": g, "a1": a1, "a2": a2, "owner_id": me_id(client), "viewer_id": me_id(other_client),
            "stranger": stranger}


def grant(owner, viewer_id, scope="accounts", account_ids=None):
    r = owner.post(f"{API}/delegations", json={"viewer_user_id": viewer_id, "scope": scope,
                                               "account_ids": account_ids or []})
    assert r.status_code == 201, r.text
    return r.json()


def test_candidates_and_create_rules(client, other_client, family):
    cands = client.get(f"{API}/delegations/candidates").json()
    assert cands == [{"user_id": family["viewer_id"], "display_name": "別人", "avatar_url": None,
                      "delegation_id": None}]
    stranger_id = me_id(family["stranger"])
    for body, status in (
        ({"viewer_user_id": stranger_id, "scope": "all"}, 404),  # not in a shared group
        ({"viewer_user_id": family["owner_id"], "scope": "all"}, 404),  # yourself
        ({"viewer_user_id": family["viewer_id"], "scope": "accounts"}, 422),  # no accounts chosen
        ({"viewer_user_id": family["viewer_id"], "scope": "accounts", "account_ids": ["acc_nope"]}, 422),
        ({"viewer_user_id": family["viewer_id"], "scope": "all", "account_ids": [family["a1"]["id"]]}, 422),
        ({"viewer_user_id": family["viewer_id"], "scope": "everything"}, 422),
    ):
        r = client.post(f"{API}/delegations", json=body)
        assert r.status_code == status, (body, r.text)
    other_acc = account(other_client, "別人的帳戶")
    r = client.post(f"{API}/delegations", json={"viewer_user_id": family["viewer_id"], "scope": "accounts",
                                                "account_ids": [other_acc["id"]]})
    assert r.status_code == 422  # only your own accounts
    dlg = grant(client, family["viewer_id"], account_ids=[family["a1"]["id"]])
    assert dlg["id"].startswith("dlg_") and dlg["scope"] == "accounts"
    assert dlg["owner"] == {"user_id": family["owner_id"], "display_name": "示範使用者", "avatar_url": None}
    assert dlg["accounts"] == [{"id": family["a1"]["id"], "name": "爸爸－永豐"}]
    r = client.post(f"{API}/delegations", json={"viewer_user_id": family["viewer_id"], "scope": "all"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_member"
    assert client.get(f"{API}/delegations/candidates").json()[0]["delegation_id"] == dlg["id"]
    lists = client.get(f"{API}/delegations").json()
    assert [d["id"] for d in lists["granted"]] == [dlg["id"]] and lists["received"] == []
    assert [d["id"] for d in other_client.get(f"{API}/delegations").json()["received"]] == [dlg["id"]]


def test_view_as_reads_only_the_delegated_accounts(client, other_client, family):
    dlg = grant(client, family["viewer_id"], account_ids=[family["a1"]["id"]])
    h = {VIEW: dlg["id"]}
    a1, a2 = family["a1"]["id"], family["a2"]["id"]

    accounts = other_client.get(f"{API}/accounts", headers=h).json()
    assert [a["id"] for a in accounts] == [a1]
    assert other_client.get(f"{API}/accounts/{a2}/holdings", headers=h).status_code == 404
    summary = other_client.get(f"{API}/portfolio/summary", headers=h).json()
    assert [x["key"] for x in summary["allocation"]["by_account"]] == [a1]
    holdings = other_client.get(f"{API}/portfolio/holdings", headers=h).json()
    assert [x["symbol"] for x in holdings] == ["2330.TW"] and holdings[0]["account_ids"] == [a1]
    txns = other_client.get(f"{API}/transactions", headers=h).json()["items"]
    assert {t["account_id"] for t in txns} == {a1}
    secret_txn = client.get(f"{API}/transactions", params={"account_id": a2}).json()["items"][0]
    assert other_client.get(f"{API}/transactions/{secret_txn['id']}", headers=h).status_code == 404
    assert other_client.get(f"{API}/transactions", params={"account_id": a2}, headers=h).status_code == 404
    for path in ("/portfolio/summary", "/portfolio/holdings", "/portfolio/closed", "/portfolio/performance"):
        assert other_client.get(f"{API}{path}", params={"account_id": a2}, headers=h).status_code == 404, path
    perf = other_client.get(f"{API}/portfolio/performance", params={"range": "MTD"}, headers=h)
    assert perf.status_code == 200
    upcoming = other_client.get(f"{API}/portfolio/upcoming", params={"days": 60}, headers=h).json()
    assert not any(u["type"] == "recurring" for u in upcoming)  # the plan is on the other account
    assert any(u["type"] == "recurring" for u in client.get(f"{API}/portfolio/upcoming",
                                                                  params={"days": 60}).json())
    assert other_client.get(f"{API}/instruments/2317.TW/position", headers=h).json() is None
    assert other_client.get(f"{API}/instruments/2330.TW/position", headers=h).json()["quantity"] == 1000
    hist = other_client.get(f"{API}/instruments/2317.TW/position/history", headers=h).json()
    assert hist["markers"] == []
    events = other_client.get(f"{API}/instruments/2317.TW/events", params={"mine": True}, headers=h).json()
    assert events == []
    # Display preferences stay the viewer's own: GET /me ignores the header.
    assert other_client.get(f"{API}/me", headers=h).json()["id"] == family["viewer_id"]
    assert other_client.get(f"{API}/instruments/2330.TW/quote", headers=h).status_code == 200
    # Without the header the viewer sees their own (empty) ledger.
    assert other_client.get(f"{API}/accounts").json() == []
    assert "私人備註" not in str(other_client.get(f"{API}/transactions", headers=h).json())


def test_view_as_scope_all_includes_later_accounts_and_owner_preferences(client, other_client, family):
    client.patch(f"{API}/me/preferences", json={"cost_method": "fifo", "benchmark": "^TAIEXTR"})
    dlg = grant(client, family["viewer_id"], scope="all")
    h = {VIEW: dlg["id"]}
    later = account(client, "之後新增的帳戶")
    ids = {a["id"] for a in other_client.get(f"{API}/accounts", headers=h).json()}
    assert ids == {family["a1"]["id"], family["a2"]["id"], later["id"]}
    perf = other_client.get(f"{API}/portfolio/performance", params={"range": "1M"}, headers=h).json()
    assert perf["benchmark"]["symbol"] == "^TAIEXTR"  # the owner's benchmark
    r = client.patch(f"{API}/delegations/{dlg['id']}", json={"scope": "accounts",
                                                              "account_ids": [family["a2"]["id"]]})
    assert r.status_code == 200 and [a["id"] for a in r.json()["accounts"]] == [family["a2"]["id"]]
    assert [a["id"] for a in other_client.get(f"{API}/accounts", headers=h).json()] == [family["a2"]["id"]]
    # Deleting the account removes it from the scope (and the viewer sees nothing).
    assert client.delete(f"{API}/accounts/{family['a2']['id']}").status_code == 204
    assert other_client.get(f"{API}/accounts", headers=h).json() == []
    assert client.get(f"{API}/delegations").json()["granted"][0]["accounts"] == []
    assert other_client.get(f"{API}/portfolio/holdings", headers=h).json() == []


def test_view_as_is_default_deny(client, other_client, family):
    dlg = grant(client, family["viewer_id"], scope="all")
    h = {VIEW: dlg["id"]}
    writes = [
        ("post", "/transactions", {"account_id": family["a1"]["id"], "symbol": "2330.TW", "type": "buy",
                                   "trade_date": "2026-01-05", "quantity": 1, "price": 1}),
        ("patch", f"/accounts/{family['a1']['id']}", {"name": "x"}),
        ("delete", f"/accounts/{family['a1']['id']}", None),
        ("patch", "/me/preferences", {"theme": "dark"}),
        ("patch", "/me", {"display_name": "x"}),
        ("post", "/auth/logout", None),
        ("post", "/watchlist", {"symbol": "2330.TW"}),
        ("put", f"/accounts/{family['a1']['id']}/holdings", {"as_of": "2026-01-05", "holdings": []}),
    ]
    for method, path, body in writes:
        r = getattr(other_client, method)(f"{API}{path}", headers=h, **({"json": body} if body else {}))
        assert r.status_code == 403 and r.json()["error"]["code"] == "read_only", (path, r.text)
    for path in ("/watchlist", "/recurring", "/ai/threads", "/ai/usage", "/ai/drafts", "/groups", "/delegations",
                 f"/groups/{family['group']['id']}", "/instruments/2330.TW/analyst-views", "/nope",
                 "/ai/suggestions"):
        r = other_client.get(f"{API}{path}", headers=h)
        assert r.status_code == 403 and r.json()["error"]["code"] == "view_as_not_allowed", (path, r.text)
    # Nothing was written.
    assert len(client.get(f"{API}/transactions").json()["items"]) == 2
    assert client.get(f"{API}/accounts").json()[0]["name"] == "爸爸－永豐"


def test_revoked_unknown_or_foreign_delegation(client, other_client, family):
    dlg = grant(client, family["viewer_id"], scope="all")
    stranger = family["stranger"]
    for c, header in ((other_client, "dlg_unknown"), (stranger, dlg["id"]), (client, dlg["id"])):
        r = c.get(f"{API}/portfolio/summary", headers={VIEW: header})
        assert r.status_code == 403 and r.json()["error"]["code"] == "delegation_revoked"
    # The viewer may not change the scope, but may remove the delegation.
    r = other_client.patch(f"{API}/delegations/{dlg['id']}", json={"scope": "all"})
    assert r.status_code == 403
    assert stranger.delete(f"{API}/delegations/{dlg['id']}").status_code == 404
    assert other_client.delete(f"{API}/delegations/{dlg['id']}").status_code == 204
    r = other_client.get(f"{API}/accounts", headers={VIEW: dlg["id"]})
    assert r.status_code == 403 and r.json()["error"]["code"] == "delegation_revoked"
    # The owner revokes: immediately effective.
    dlg = grant(client, family["viewer_id"], scope="all")
    assert other_client.get(f"{API}/accounts", headers={VIEW: dlg["id"]}).status_code == 200
    assert client.delete(f"{API}/delegations/{dlg['id']}").status_code == 204
    assert other_client.get(f"{API}/accounts", headers={VIEW: dlg["id"]}).status_code == 403


def test_delegation_survives_leaving_the_group(client, other_client, family):
    dlg = grant(client, family["viewer_id"], scope="all")
    gid = family["group"]["id"]
    assert other_client.delete(f"{API}/groups/{gid}/members/{family['viewer_id']}").status_code == 204
    assert other_client.get(f"{API}/accounts", headers={VIEW: dlg["id"]}).status_code == 200
    assert client.get(f"{API}/delegations/candidates").json() == []
    r = client.post(f"{API}/delegations", json={"viewer_user_id": family["viewer_id"], "scope": "all"})
    assert r.status_code == 404  # no longer a candidate for a new grant, but the existing grant stays
    assert [d["id"] for d in client.get(f"{API}/delegations").json()["granted"]] == [dlg["id"]]


def test_view_scope_refuses_every_write_on_the_session(engine, client, other_client, family):
    """Defense in depth: even a read path that tried to write (e.g. a dividend sync) cannot under view-as."""
    from sqlalchemy import delete, update

    from forliosa.api.errors import ApiError
    from forliosa.db import session_factory
    from forliosa.models import BrokerAccount, SecTicker, Transaction, User
    from forliosa.services import sharing

    dlg = grant(client, family["viewer_id"], scope="all")
    with session_factory()() as db:
        viewer = db.get(User, family["viewer_id"])
        owner = sharing.enter_view_as(db, viewer, dlg["id"])
        assert owner.id == family["owner_id"]
        acc = db.get(BrokerAccount, family["a1"]["id"])
        acc.name = "hacked"
        with pytest.raises(ApiError) as exc:
            db.commit()
        assert exc.value.code == "read_only"
        db.rollback()
        with pytest.raises(ApiError):  # bulk statements do not flush: refused too
            db.execute(delete(Transaction).where(Transaction.user_id == owner.id))
        with pytest.raises(ApiError):
            db.execute(update(BrokerAccount).values(name="x"))
        db.rollback()
        db.add(SecTicker(ticker="ZZZZ", cik=1, title="shared cache"))  # shared market-data cache: allowed
        db.commit()
    assert client.get(f"{API}/accounts").json()[0]["name"] == "爸爸－永豐"
    assert len(client.get(f"{API}/transactions").json()["items"]) == 2
