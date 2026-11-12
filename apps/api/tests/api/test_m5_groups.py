"""M5 groups: CRUD, roles, leave/remove rules, invites lifecycle, limits, share settings, non-member 404s."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from forliosa.db import session_factory
from forliosa.models import GroupChannel, GroupInvite, GroupMember, GroupShareSetting
from forliosa.timeutil import now_utc
from tests.api.m5 import (
    API,
    SHARE_ALL,
    SHARE_DEFAULT,
    SHARE_NONE,
    invite,
    join,
    login,
    make_group,
    me_id,
    set_share,
    token_of,
)


@pytest.fixture()
def trio(app, client, other_client):
    third = login(app, "third@forliosa.local", "老三")
    g = make_group(client)
    join(client, other_client, g["id"])
    join(client, third, g["id"])
    return g, third


def test_create_get_list_patch_delete(client, other_client):
    for bad in ("", "   ", "x" * 41, "家」\n[重新登入 Forliosa](https://ev.il)", "家\r族", "家\u202e族"):
        r = client.post(f"{API}/groups", json={"name": bad})
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    g = make_group(client, "  家族投資  ")
    assert g["name"] == "家族投資" and g["id"].startswith("grp_") and g["my_role"] == "owner"
    assert g["ranking_enabled"] is True and g["push_targets"] == []
    assert g["my_share"] == SHARE_DEFAULT  # the creator gets the defaults: only returns
    assert [(m["role"], m["is_me"]) for m in g["members"]] == [("owner", True)]
    lst = client.get(f"{API}/groups").json()
    assert [(x["id"], x["member_count"], x["my_role"]) for x in lst] == [(g["id"], 1, "owner")]
    assert lst[0]["latest_activity_at"] is not None and lst[0]["latest_digest_at"] is None
    assert client.patch(f"{API}/groups/{g['id']}", json={"name": "新\n名字"}).status_code == 422
    r = client.patch(f"{API}/groups/{g['id']}", json={"name": "新名字", "ranking_enabled": False})
    assert r.status_code == 200 and r.json()["name"] == "新名字" and r.json()["ranking_enabled"] is False
    assert other_client.get(f"{API}/groups").json() == []
    assert client.delete(f"{API}/groups/{g['id']}").status_code == 204
    assert client.get(f"{API}/groups/{g['id']}").status_code == 404


def test_non_members_get_404_everywhere(client, other_client):
    g = make_group(client)
    gid = g["id"]
    paths = [("get", f"/groups/{gid}"), ("patch", f"/groups/{gid}"), ("delete", f"/groups/{gid}"),
             ("post", f"/groups/{gid}/transfer"), ("patch", f"/groups/{gid}/members/x"),
             ("delete", f"/groups/{gid}/members/x"), ("post", f"/groups/{gid}/invites"),
             ("get", f"/groups/{gid}/invites"), ("delete", f"/groups/{gid}/invites/inv_x"),
             ("get", f"/groups/{gid}/share"), ("put", f"/groups/{gid}/share"),
             ("get", f"/groups/{gid}/leaderboard"), ("get", f"/groups/{gid}/holdings"),
             ("get", f"/groups/{gid}/members/x/shared"), ("get", f"/groups/{gid}/feed"),
             ("get", f"/groups/{gid}/comments?target=leaderboard:2026-01-05"), ("post", f"/groups/{gid}/comments"),
             ("delete", f"/groups/{gid}/comments/gcm_x"), ("put", f"/groups/{gid}/reactions"),
             ("delete", f"/groups/{gid}/reactions?target=leaderboard:2026-01-05&emoji=%F0%9F%91%8D")]
    bodies = {"patch": {"name": "x"}, "post": {"user_id": "x"}, "put": SHARE_NONE}
    unknown = make_group(other_client)["id"]
    for method, path in paths:
        body = bodies.get(method)
        if path.endswith("/comments") and method == "post":
            body = {"target": "leaderboard:2026-01-05", "body": "hi"}
        if path.endswith("/reactions") and method == "put":
            body = {"target": "leaderboard:2026-01-05", "emoji": "👍"}
        if path.endswith("/invites") and method == "post":
            body = {}
        if "/members/" in path and method == "patch":
            body = {"role": "admin"}
        kw = {"json": body} if body is not None else {}
        r = getattr(other_client, method)(f"{API}{path}", **kw)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", (method, path, r.text)
        # Same answer as a group that does not exist.
        r2 = getattr(other_client, method)(f"{API}{path.replace(gid, 'grp_doesnotexist')}", **kw)
        assert r2.status_code == 404 and r2.json() == r.json(), path
    assert unknown


def test_roles_transfer_and_permissions(client, other_client, trio):
    g, third = trio
    gid = g["id"]
    other_id, third_id, owner_id = me_id(other_client), me_id(third), me_id(client)
    # members cannot manage
    assert other_client.patch(f"{API}/groups/{gid}", json={"name": "x"}).status_code == 403
    assert other_client.post(f"{API}/groups/{gid}/invites", json={}).status_code == 403
    assert other_client.get(f"{API}/groups/{gid}/invites").status_code == 403
    assert other_client.delete(f"{API}/groups/{gid}/members/{third_id}").status_code == 403
    assert other_client.patch(f"{API}/groups/{gid}/members/{third_id}", json={"role": "admin"}).status_code == 403
    assert other_client.delete(f"{API}/groups/{gid}").status_code == 403
    # owner promotes an admin
    r = client.patch(f"{API}/groups/{gid}/members/{other_id}", json={"role": "admin"})
    assert r.status_code == 200 and {m["user_id"]: m["role"] for m in r.json()["members"]}[other_id] == "admin"
    assert client.patch(f"{API}/groups/{gid}/members/{owner_id}", json={"role": "member"}).status_code == 422
    assert client.patch(f"{API}/groups/{gid}/members/{other_id}", json={"role": "owner"}).status_code == 422
    # admin: rename and invite yes; ranking, roles, delete no
    assert other_client.patch(f"{API}/groups/{gid}", json={"name": "改名"}).status_code == 200
    r = other_client.patch(f"{API}/groups/{gid}", json={"ranking_enabled": False})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert other_client.patch(f"{API}/groups/{gid}/members/{third_id}", json={"role": "admin"}).status_code == 403
    assert other_client.delete(f"{API}/groups/{gid}").status_code == 403
    assert other_client.post(f"{API}/groups/{gid}/invites", json={}).status_code == 201
    # admin cannot remove the owner or another admin
    assert other_client.delete(f"{API}/groups/{gid}/members/{owner_id}").status_code == 403
    client.patch(f"{API}/groups/{gid}/members/{third_id}", json={"role": "admin"})
    assert other_client.delete(f"{API}/groups/{gid}/members/{third_id}").status_code == 403
    # owner must transfer before leaving
    r = client.delete(f"{API}/groups/{gid}/members/{owner_id}")
    assert r.status_code == 409
    assert client.post(f"{API}/groups/{gid}/transfer", json={"user_id": "usr_nobody"}).status_code == 404
    r = client.post(f"{API}/groups/{gid}/transfer", json={"user_id": other_id})
    assert r.status_code == 200
    roles = {m["user_id"]: m["role"] for m in r.json()["members"]}
    assert roles == {owner_id: "admin", other_id: "owner", third_id: "admin"} and r.json()["my_role"] == "admin"
    assert client.delete(f"{API}/groups/{gid}/members/{owner_id}").status_code == 204  # now it can leave
    assert client.get(f"{API}/groups/{gid}").status_code == 404


def test_removal_revokes_multi_use_invites_and_share_settings_go(client, other_client, trio):
    g, _third = trio
    gid = g["id"]
    multi = invite(client, gid, multi_use=True)
    single = invite(client, gid)
    set_share(other_client, gid, **SHARE_ALL)
    assert client.delete(f"{API}/groups/{gid}/members/{me_id(other_client)}").status_code == 204
    with session_factory()() as db:
        assert db.get(GroupShareSetting, (gid, me_id(other_client))) is None
    ids = [i["id"] for i in client.get(f"{API}/groups/{gid}/invites").json()]
    assert multi["id"] not in ids and single["id"] in ids
    r = other_client.post(f"{API}/invites/{token_of(multi)}/accept", json={"share": SHARE_ALL})
    assert r.status_code == 410 and r.json()["error"]["code"] == "invite_invalid"
    # Rejoining (with the single-use link) chooses the share settings again.
    r = other_client.post(f"{API}/invites/{token_of(single)}/accept", json={"share": SHARE_NONE})
    assert r.status_code == 200 and r.json()["my_share"] == SHARE_NONE


def test_member_leaves(client, other_client):
    g = make_group(client)
    join(client, other_client, g["id"])
    assert other_client.delete(f"{API}/groups/{g['id']}/members/{me_id(other_client)}").status_code == 204
    assert other_client.get(f"{API}/groups/{g['id']}").status_code == 404
    assert [m["is_me"] for m in client.get(f"{API}/groups/{g['id']}").json()["members"]] == [True]


def test_invite_lifecycle(app, client, other_client):
    g = make_group(client)
    gid = g["id"]
    inv = invite(client, gid)
    assert inv["id"].startswith("inv_") and inv["multi_use"] is False and inv["uses"] == 0
    token = token_of(inv)
    assert inv["url"] == f"http://localhost:5173/invite/{token}" and len(token) >= 43  # ≥ 256 bits
    listed = client.get(f"{API}/groups/{gid}/invites").json()
    assert [i["id"] for i in listed] == [inv["id"]] and "url" not in listed[0]
    with session_factory()() as db:
        row = db.get(GroupInvite, inv["id"])
        assert row.token_hash != token and len(row.token_hash) == 64 and token not in row.token_hash
    # preview without login, then as a member
    anon = TestClient(app)
    r = anon.get(f"{API}/invites/{token}")
    assert r.status_code == 200 and r.json() == {"group_name": "家族投資", "inviter_display_name": "示範使用者",
                                                 "status": "valid"}
    assert client.get(f"{API}/invites/{token}").json()["status"] == "member"
    assert anon.get(f"{API}/invites/not-a-token").status_code == 404
    # accept: login and the share choice are required
    assert anon.post(f"{API}/invites/{token}/accept", json={"share": SHARE_DEFAULT}).status_code == 401
    assert other_client.post(f"{API}/invites/{token}/accept", json={}).status_code == 422
    assert other_client.post(f"{API}/invites/{token}/accept",
                             json={"share": {"returns": True}}).status_code == 422  # every toggle confirmed
    r = other_client.post(f"{API}/invites/{token}/accept", json={"share": {**SHARE_NONE, "holdings": True}})
    assert r.status_code == 200 and r.json()["my_role"] == "member"
    assert r.json()["my_share"] == {**SHARE_NONE, "holdings": True}
    # used up
    r = anon.get(f"{API}/invites/{token}")
    assert r.status_code == 410 and r.json()["error"]["code"] == "invite_invalid"
    assert client.get(f"{API}/groups/{gid}/invites").json() == []
    # already a member (multi-use link)
    multi = invite(client, gid, multi_use=True, expires="24h")
    r = other_client.post(f"{API}/invites/{token_of(multi)}/accept", json={"share": SHARE_DEFAULT})
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_member"
    third = login(app, "third@forliosa.local", "老三")
    fourth = login(app, "fourth@forliosa.local", "老四")
    for c in (third, fourth):
        assert c.post(f"{API}/invites/{token_of(multi)}/accept", json={"share": SHARE_DEFAULT}).status_code == 200
    assert client.get(f"{API}/groups/{gid}/invites").json()[0]["uses"] == 2
    # revoked
    assert client.delete(f"{API}/groups/{gid}/invites/{multi['id']}").status_code == 204
    assert anon.get(f"{API}/invites/{token_of(multi)}").status_code == 410
    assert client.delete(f"{API}/groups/{gid}/invites/inv_unknown").status_code == 404
    # expired
    late = invite(client, gid)
    with session_factory()() as db:
        db.get(GroupInvite, late["id"]).expires_at = now_utc() - timedelta(seconds=1)
        db.commit()
    assert anon.get(f"{API}/invites/{token_of(late)}").status_code == 410
    assert client.post(f"{API}/groups/{gid}/invites", json={"expires": "30d"}).status_code == 422


def test_inviter_name_falls_back_to_owner_when_inviter_left(client, other_client):
    g = make_group(client)
    join(client, other_client, g["id"])
    client.patch(f"{API}/groups/{g['id']}/members/{me_id(other_client)}", json={"role": "admin"})
    inv = invite(other_client, g["id"])
    other_client.delete(f"{API}/groups/{g['id']}/members/{me_id(other_client)}")
    assert client.get(f"{API}/invites/{token_of(inv)}").json()["inviter_display_name"] == "示範使用者"


def test_limits(app, client, other_client):
    from forliosa.models import User

    g = make_group(client)
    with session_factory()() as db:
        for i in range(48):
            uid = f"usr_fill{i:02d}"
            db.add(User(id=uid, email=f"f{i}@x.y", display_name=f"f{i}", preferences={}))
            db.flush()
            db.add(GroupMember(group_id=g["id"], user_id=uid, role="member"))
        db.commit()
    join(client, other_client, g["id"])  # the 50th member
    third = login(app, "third@forliosa.local", "老三")
    inv = invite(client, g["id"])
    r = third.post(f"{API}/invites/{token_of(inv)}/accept", json={"share": SHARE_DEFAULT})
    assert r.status_code == 409 and r.json()["error"]["code"] == "limit_reached"
    for i in range(19):
        make_group(third, f"群組{i}")
    assert third.post(f"{API}/groups", json={"name": "第 21 個"}).status_code == 201  # 20th
    r = third.post(f"{API}/groups", json={"name": "第 21 個"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "limit_reached"
    other_group = make_group(other_client, "別的群組")
    r = third.post(f"{API}/invites/{token_of(invite(other_client, other_group['id']))}/accept",
                   json={"share": SHARE_DEFAULT})
    assert r.status_code == 409 and r.json()["error"]["code"] == "limit_reached"


def test_share_settings_and_timestamps(client, other_client):
    g = make_group(client)
    gid = g["id"]
    assert client.get(f"{API}/groups/{gid}/share").json() == SHARE_DEFAULT
    assert client.put(f"{API}/groups/{gid}/share", json={"returns": True}).status_code == 422
    out = set_share(client, gid, trades=True, push=True)
    assert out == {**SHARE_NONE, "trades": True, "push": True}
    with session_factory()() as db:
        s = db.get(GroupShareSetting, (gid, me_id(client)))
        first = (s.trades_enabled_at, s.push_enabled_at)
        assert all(first)
    set_share(client, gid, trades=True, push=True)  # unchanged: timestamps stay
    with session_factory()() as db:
        s = db.get(GroupShareSetting, (gid, me_id(client)))
        assert (s.trades_enabled_at, s.push_enabled_at) == first
    set_share(client, gid)
    set_share(client, gid, trades=True)
    with session_factory()() as db:
        s = db.get(GroupShareSetting, (gid, me_id(client)))
        assert s.trades_enabled_at > first[0]


def test_push_targets_visible_to_every_member(client, other_client):
    g = make_group(client)
    join(client, other_client, g["id"])
    with session_factory()() as db:
        db.add(GroupChannel(group_id=g["id"], kind="telegram", status="active", chat_title="家族投資群",
                            telegram_chat_id=-100123))
        db.add(GroupChannel(group_id=g["id"], kind="discord", status="disabled", disabled_reason="webhook_gone",
                            webhook_encrypted="x", webhook_hint="a1b2"))
        db.commit()
    targets = other_client.get(f"{API}/groups/{g['id']}").json()["push_targets"]
    assert targets == [{"kind": "telegram", "label": "家族投資群"}]  # only active channels; no webhook details


def test_delete_group_removes_everything(client, other_client):
    g = make_group(client)
    join(client, other_client, g["id"])
    invite(client, g["id"])
    client.post(f"{API}/groups/{g['id']}/comments", json={"target": "leaderboard:" + _today(), "body": "hi"})
    assert client.delete(f"{API}/groups/{g['id']}").status_code == 204
    with session_factory()() as db:
        for model in (GroupMember, GroupInvite, GroupShareSetting):
            assert list(db.scalars(select(model))) == []
    assert other_client.get(f"{API}/groups").json() == []


def _today() -> str:
    from forliosa.timeutil import today_taipei

    return today_taipei().isoformat()
