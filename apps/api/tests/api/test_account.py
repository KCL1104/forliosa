"""The signed-in user's own account: data export, account deletion, the terms version they agreed to
(docs/api-contract.md 「帳號：匯出資料、刪除帳號、條款版本」)."""

from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa import models
from forliosa.config import get_settings
from forliosa.services import account as account_service
from forliosa.services import discord_oauth
from tests.api.discussions import GAP, error, post_reply, post_topic, replies, set_name
from tests.api.m5 import API, SHARE_ALL, account, join, login, make_group, me_id, trade, trading_day
from tests.api.test_m5_auth import FakeDiscord, callback, start

ADMIN_URL = f"{API}/admin/discussions"
CONFIRM = {"confirm": "刪除我的帳號"}


@pytest.fixture(autouse=True)
def fresh_export_rate():
    account_service.reset_export_rate()
    yield
    account_service.reset_export_rate()


def delete_me(client: TestClient, body: dict | None = None) -> httpx.Response:
    return client.request("DELETE", f"{API}/me", json=CONFIRM if body is None else body)


def grant_all(owner: TestClient, viewer: TestClient) -> httpx.Response:
    return owner.post(f"{API}/delegations", json={"viewer_user_id": me_id(viewer), "scope": "all", "account_ids": []})


def count(engine, model, *where) -> int:
    with Session(engine) as db:
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


def seed_ledger(client: TestClient) -> dict:
    acct = account(client)
    trade(client, acct["id"], "2330.TW", "buy", trading_day(5), 1000, 1000)
    trade(client, acct["id"], "0050.TW", "buy", trading_day(3), 500, 190.5)
    assert client.post(f"{API}/watchlist", json={"symbol": "2454.TW"}).status_code in (200, 201)
    return acct


# -- export --------------------------------------------------------------------------------------------------------
def test_export_is_a_json_attachment_with_only_my_own_data(client, other_client, clock):
    acct = seed_ledger(client)
    other_acct = account(other_client, "別人的帳戶")
    trade(other_client, other_acct["id"], "2317.TW", "buy", trading_day(4), 2000, 180)
    group = make_group(client)
    join(client, other_client, group["id"], SHARE_ALL)
    set_name(client, "阿土伯")
    set_name(other_client, "路人甲")
    mine = post_topic(client, clock, title="我的主題", body="我的內文", symbols=["2330.TW"])
    theirs = post_topic(other_client, clock, title="別人的主題", body="別人的內文")
    post_reply(client, clock, theirs["id"], "我的回覆")
    post_reply(other_client, clock, mine["id"], "別人的回覆")

    r = client.get(f"{API}/me/export")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    assert r.headers["content-disposition"].startswith('attachment; filename="forliosa-export-')
    assert r.headers["content-disposition"].endswith('.json"')
    assert r.headers["cache-control"] == "no-store"
    data = r.json()
    assert data["format_version"] == 1 and data["exported_at"].endswith("Z")
    assert set(data) == {"exported_at", "format_version", "profile", "accounts", "transactions", "recurring_plans",
                         "watchlist", "auto_dividend_skips", "ai", "groups", "group_comments", "group_reactions",
                         "delegations", "discussions"}
    assert data["profile"]["email"] == "demo@forliosa.local" and data["profile"]["public_name"] == "阿土伯"
    assert data["profile"]["display_name"] == "示範使用者" and "preferences" in data["profile"]
    assert [a["id"] for a in data["accounts"]] == [acct["id"]]
    assert sorted(t["symbol"] for t in data["transactions"]) == ["0050.TW", "2330.TW"]
    # exact decimals as stored, not floats
    assert {t["symbol"]: t["price"] for t in data["transactions"]} == {"2330.TW": "1000", "0050.TW": "190.5"}
    assert [w["symbol"] for w in data["watchlist"]] == ["2454.TW"]
    assert [g["name"] for g in data["groups"]] == ["家族投資"] and data["groups"][0]["role"] == "owner"
    assert data["groups"][0]["share"] is not None
    assert [t["title"] for t in data["discussions"]["topics"]] == ["我的主題"]
    assert data["discussions"]["topics"][0]["symbols"] == ["2330.TW"]
    assert [x["body"] for x in data["discussions"]["replies"]] == ["我的回覆"]
    # nothing of the other person, and nothing that identifies sessions or internal keys
    text = json.dumps(data, ensure_ascii=False)
    for leaked in ("別人的帳戶", "2317.TW", "別人的主題", "別人的內文", "別人的回覆", "路人甲", "other@forliosa.local",
                   "public_name_key", "key_slot", "token"):
        assert leaked not in text, leaked


def test_export_needs_a_session_and_ignores_view_as(client, other_client, app):
    assert TestClient(app).get(f"{API}/me/export").status_code == 401
    seed_ledger(client)
    group = make_group(client)
    join(client, other_client, group["id"])
    d = grant_all(client, other_client)
    assert d.status_code == 201, d.text
    # Looking at someone else's ledger, the export is still my own (empty) data — never the owner's.
    r = other_client.get(f"{API}/me/export", headers={"X-Forliosa-View-As": d.json()["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["profile"]["email"] == "other@forliosa.local" and r.json()["transactions"] == []
    # what the other person gave me is listed without their account ids
    assert r.json()["delegations"]["received"] == [
        {k: v for k, v in r.json()["delegations"]["received"][0].items() if k != "account_ids"}]
    assert r.json()["delegations"]["received"][0]["other_display_name"] == "示範使用者"
    assert client.get(f"{API}/me/export").json()["delegations"]["given"][0]["other_display_name"] == "別人"


def test_export_is_limited_to_five_an_hour_per_user(client, other_client):
    for _ in range(5):
        assert client.get(f"{API}/me/export").status_code == 200
    r = client.get(f"{API}/me/export")
    assert r.status_code == 429 and error(r) == "rate_limited", r.text
    wait = r.json()["error"]["retry_after_seconds"]
    assert 1 <= wait <= 3601 and r.headers["retry-after"] == str(wait)
    assert other_client.get(f"{API}/me/export").status_code == 200  # per user


# -- delete --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("body", [{}, {"confirm": ""}, {"confirm": "刪除"}, {"confirm": "刪除我的帳號 "},
                                  {"confirm": "delete my account"}])
def test_delete_needs_the_exact_confirmation(client, body):
    r = delete_me(client, body)
    assert r.status_code == 422 and error(r) == "validation_error", r.text
    assert client.get(f"{API}/me").status_code == 200


def test_delete_needs_a_session_and_is_refused_while_viewing_someone_else(client, other_client, app):
    assert delete_me(TestClient(app)).status_code == 401
    group = make_group(client)
    join(client, other_client, group["id"])
    d = grant_all(client, other_client).json()
    r = other_client.request("DELETE", f"{API}/me", json=CONFIRM, headers={"X-Forliosa-View-As": d["id"]})
    assert r.status_code == 403 and error(r) == "read_only", r.text
    assert client.get(f"{API}/me").status_code == 200 and other_client.get(f"{API}/me").status_code == 200


def test_delete_removes_my_data_signs_me_out_and_keeps_my_posts_without_an_author(client, other_client, engine, clock):
    uid = me_id(client)
    seed_ledger(client)
    group = make_group(other_client, "別人的群組")
    join(other_client, client, group["id"], SHARE_ALL)
    assert grant_all(client, other_client).status_code == 201
    set_name(client, "阿土伯")
    set_name(other_client, "路人甲")
    topic = post_topic(client, clock, title="留下來的主題", body="內文")
    theirs = post_topic(other_client, clock)
    post_reply(client, clock, theirs["id"], "留下來的回覆")
    assert client.put(f"{API}/discussions/reactions", json={"target": f"topic:{theirs['id']}", "emoji": "👍"}
                      ).status_code == 204
    clock.tick(seconds=GAP)
    assert client.post(f"{API}/discussions/reports", json={"target": f"topic:{theirs['id']}", "reason": "spam"}
                       ).status_code in (200, 201, 204)
    assert count(engine, models.DiscussionReport) == 1

    r = delete_me(client)
    assert r.status_code == 204 and r.content == b"", r.text
    assert "forliosa_session=" in r.headers.get("set-cookie", "")  # cleared
    assert client.get(f"{API}/me").status_code == 401

    for model in (models.BrokerAccount, models.Transaction, models.WatchlistItem, models.UserSession,
                  models.UserIdentity, models.GroupMember, models.GroupShareSetting, models.DiscussionReaction,
                  models.DiscussionPostLog):
        assert count(engine, model, model.user_id == uid) == 0, model.__name__
    assert count(engine, models.User, models.User.id == uid) == 0
    assert count(engine, models.Delegation) == 0
    assert count(engine, models.DiscussionReport) == 0  # the report I filed is gone
    # my posts stay, with no author
    assert count(engine, models.DiscussionTopic, models.DiscussionTopic.id == topic["id"]) == 1
    assert count(engine, models.DiscussionTopic, models.DiscussionTopic.user_id == uid) == 0
    seen = other_client.get(f"{API}/discussions/topics/{topic['id']}").json()
    assert seen["title"] == "留下來的主題" and seen["author"]["name"] is None
    reply = next(x for x in replies(other_client, theirs["id"]) if x["body"] == "留下來的回覆")
    assert reply["author"]["name"] is None
    # the other person's group and data are untouched; I am no longer a member
    g = other_client.get(f"{API}/groups/{group['id']}").json()
    assert [m["display_name"] for m in g["members"]] == ["別人"]
    # the same e-mail can sign up again and starts empty
    again = login(client.app, "demo@forliosa.local", "示範使用者")
    assert me_id(again) != uid and again.get(f"{API}/accounts").json() == []


def test_owned_groups_go_to_the_earliest_admin_then_the_earliest_member_or_are_deleted(app, engine):
    owner = login(app, "owner@forliosa.local", "擁有者")
    first = login(app, "first@forliosa.local", "先加入的成員")
    admin = login(app, "admin@forliosa.local", "後加入的管理員")
    with_admin = make_group(owner, "有管理員的群組")
    join(owner, first, with_admin["id"])
    join(owner, admin, with_admin["id"])
    r = owner.patch(f"{API}/groups/{with_admin['id']}/members/{me_id(admin)}", json={"role": "admin"})
    assert r.status_code in (200, 204), r.text
    members_only = make_group(owner, "只有成員的群組")
    join(owner, admin, members_only["id"])
    join(owner, first, members_only["id"])
    alone = make_group(owner, "只有我的群組")

    assert delete_me(owner).status_code == 204

    def roles(group_id: str) -> dict[str, str]:
        with Session(engine) as db:
            rows = db.execute(select(models.User.display_name, models.GroupMember.role)
                              .join(models.GroupMember, models.GroupMember.user_id == models.User.id)
                              .where(models.GroupMember.group_id == group_id)).all()
            return dict(rows)

    # the admin, not the member who joined first
    assert roles(with_admin["id"]) == {"先加入的成員": "member", "後加入的管理員": "owner"}
    assert roles(members_only["id"]) == {"後加入的管理員": "owner", "先加入的成員": "member"}  # the earliest member
    assert count(engine, models.Group, models.Group.id == alone["id"]) == 0
    for model in (models.GroupMember, models.GroupComment, models.GroupShareSetting):
        assert count(engine, model, model.group_id == alone["id"]) == 0


def test_a_failed_delete_changes_nothing(client, engine, monkeypatch):
    uid = me_id(client)
    seed_ledger(client)
    make_group(client)

    def boom(db, user):
        raise RuntimeError("database went away")

    monkeypatch.setattr(account_service, "_hand_over_groups", boom)
    with pytest.raises(RuntimeError):
        delete_me(client)
    assert count(engine, models.User, models.User.id == uid) == 1
    assert count(engine, models.Transaction, models.Transaction.user_id == uid) == 2
    assert count(engine, models.GroupMember, models.GroupMember.user_id == uid) == 1
    monkeypatch.undo()
    assert client.get(f"{API}/me").status_code == 200


# -- a suspension outlives the account ----------------------------------------------------------------------------
@pytest.fixture()
def discord_app(monkeypatch, engine, market):
    env = {"DISCORD_CLIENT_ID": "cid-123", "DISCORD_CLIENT_SECRET": "secret-xyz",
           "DISCORD_REDIRECT_URI": "http://testserver/api/v1/auth/discord/callback",
           "FRONTEND_URL": "http://localhost:5173", "ADMIN_EMAILS": "boss@forliosa.local"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    from forliosa.api.app import create_app

    yield create_app()
    monkeypatch.undo()
    get_settings.cache_clear()


def discord_login(app, fake: FakeDiscord) -> TestClient:
    discord_oauth.set_transport(httpx.MockTransport(fake))
    c = TestClient(app)
    state, _ = start(c, "/")
    assert callback(c, state).status_code == 302
    assert c.get(f"{API}/me").status_code == 200
    return c


def test_deleting_the_account_does_not_lift_a_public_posting_suspension(discord_app, engine, clock):
    papa = FakeDiscord()
    user = discord_login(discord_app, papa)
    admin = login(discord_app, "boss@forliosa.local", "站長本人")
    set_name(user, "洗版的人")
    topic = post_topic(user, clock)
    s = admin.post(f"{ADMIN_URL}/suspensions", json={"target": f"topic:{topic['id']}", "days": 7, "reason": "洗版"})
    assert s.status_code == 201, s.text
    until = s.json()["until"]

    assert delete_me(user).status_code == 204
    with Session(engine) as db:
        rows = db.scalars(select(models.DiscussionSuspensionCarryover)).all()
        # one keyed hash per way back in: the Discord login and the e-mail (so another provider with the same
        # e-mail does not shed the suspension; tests/api/test_google_auth.py)
        assert len(rows) == 2 and all(len(r.identity_hash) == 64 for r in rows)
        stored = json.dumps([[r.identity_hash, r.reason] for r in rows], ensure_ascii=False)
        assert papa.profile["id"] not in stored and "papa" not in stored.lower()  # not the id, name or e-mail
        assert db.scalar(select(func.count()).select_from(models.DiscussionSuspension)) == 0

    # the same Discord account registers again: a new account, still suspended until the same time
    again = discord_login(discord_app, papa)
    assert again.get(f"{API}/users/me").json()["public_posting_suspended_until"] == until
    assert count(engine, models.DiscussionSuspensionCarryover) == 0
    set_name(again, "換個名字")
    clock.tick(seconds=GAP)
    r = again.post(f"{API}/discussions/topics", json={"scope": "public", "title": "標題", "body": "內文"})
    assert r.status_code == 403 and error(r) == "posting_suspended", r.text

    # someone else's Discord account is not affected
    mama = FakeDiscord({"id": "222", "username": "mama", "global_name": "媽媽", "avatar": None,
                        "email": "mama@example.com", "verified": True})
    other = discord_login(discord_app, mama)
    assert other.get(f"{API}/users/me").json()["public_posting_suspended_until"] is None


def test_an_expired_carried_suspension_is_dropped(discord_app, engine, clock):
    papa = FakeDiscord()
    user = discord_login(discord_app, papa)
    admin = login(discord_app, "boss@forliosa.local", "站長本人")
    set_name(user, "洗版的人")
    topic = post_topic(user, clock)
    assert admin.post(f"{ADMIN_URL}/suspensions", json={"target": f"topic:{topic['id']}", "days": 1}).status_code == 201
    assert delete_me(user).status_code == 204
    with Session(engine) as db:
        for row in db.scalars(select(models.DiscussionSuspensionCarryover)):
            row.until = row.created_at - timedelta(days=1)  # it has run out by the time they come back
        db.commit()
    again = discord_login(discord_app, papa)
    assert again.get(f"{API}/users/me").json()["public_posting_suspended_until"] is None
    assert count(engine, models.DiscussionSuspensionCarryover) == 0


def test_no_carry_over_without_an_active_suspension(discord_app, engine):
    user = discord_login(discord_app, FakeDiscord())
    assert delete_me(user).status_code == 204
    assert count(engine, models.DiscussionSuspensionCarryover) == 0


# -- terms version -------------------------------------------------------------------------------------------------
def test_terms_fields_are_null_when_versions_are_not_tracked(client):
    me = client.get(f"{API}/me").json()
    assert me["terms_version_accepted"] is None and me["terms_version_current"] is None
    r = client.post(f"{API}/me/terms-accept", json={"version": "2026-11-13"})
    assert r.status_code == 409 and error(r) == "terms_version_mismatch", r.text


def test_new_accounts_record_the_current_version_and_older_accounts_acknowledge_it(app, client, monkeypatch, engine):
    monkeypatch.setattr(get_settings(), "terms_version", "2026-11-13")
    old = client.get(f"{API}/me").json()  # created before the version existed
    assert old["terms_version_accepted"] is None and old["terms_version_current"] == "2026-11-13"
    new = login(app, "new@forliosa.local", "新來的")
    assert new.get(f"{API}/me").json()["terms_version_accepted"] == "2026-11-13"
    assert count(engine, models.User, models.User.terms_accepted_at.is_not(None)) == 1

    wrong = client.post(f"{API}/me/terms-accept", json={"version": "2026-01-01"})
    assert wrong.status_code == 409 and error(wrong) == "terms_version_mismatch", wrong.text
    assert client.post(f"{API}/me/terms-accept", json={}).status_code == 422
    ok = client.post(f"{API}/me/terms-accept", json={"version": "2026-11-13"})
    assert ok.status_code == 200 and ok.json()["terms_version_accepted"] == "2026-11-13", ok.text

    # the terms change: everyone is asked again, including the account that signed up under the previous version
    monkeypatch.setattr(get_settings(), "terms_version", "2027-01-01")
    for c in (client, new):
        me = c.get(f"{API}/me").json()
        assert me["terms_version_accepted"] == "2026-11-13" and me["terms_version_current"] == "2027-01-01"
    assert TestClient(app).post(f"{API}/me/terms-accept", json={"version": "2027-01-01"}).status_code == 401


def test_terms_notice_carries_the_effective_date_and_a_summary_when_set(client, monkeypatch):
    from datetime import date

    settings = get_settings()
    # ignored while versions are not tracked
    monkeypatch.setattr(settings, "terms_effective_date", date(2026, 12, 1))
    monkeypatch.setattr(settings, "terms_summary", "新增匯出資料的說明")
    me = client.get(f"{API}/me").json()
    assert me["terms_effective_date"] is None and me["terms_summary"] is None
    monkeypatch.setattr(settings, "terms_version", "2026-12-01")
    me = client.get(f"{API}/me").json()
    assert me["terms_effective_date"] == "2026-12-01" and me["terms_summary"] == "新增匯出資料的說明"
    # one line, bounded; both are optional
    monkeypatch.setattr(settings, "terms_summary", "第一行\n第二行" + "字" * 300)
    summary = client.get(f"{API}/me").json()["terms_summary"]
    assert "\n" not in summary and len(summary) <= 120
    monkeypatch.setattr(settings, "terms_effective_date", None)
    monkeypatch.setattr(settings, "terms_summary", None)
    me = client.get(f"{API}/me").json()
    assert me["terms_version_current"] == "2026-12-01" and me["terms_effective_date"] is None
    assert me["terms_summary"] is None


def test_terms_accept_is_refused_while_viewing_someone_else(client, other_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "terms_version", "2026-11-13")
    group = make_group(client)
    join(client, other_client, group["id"])
    d = grant_all(client, other_client).json()
    r = other_client.post(f"{API}/me/terms-accept", json={"version": "2026-11-13"},
                          headers={"X-Forliosa-View-As": d["id"]})
    assert r.status_code == 403 and error(r) == "read_only", r.text
