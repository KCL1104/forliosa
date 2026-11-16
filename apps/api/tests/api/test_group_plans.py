"""群組加值包 (產品負責人 2026-11-16): member caps by plan (free / boosted / grandfathered, a race on the last seat),
boosts granted by a site admin and attached by the group's owner, what happens on expiry, transfer, account deletion
and group deletion, and that the admin never sees a group's name."""

from __future__ import annotations

import threading
from datetime import timedelta

from sqlalchemy import select

from forliosa.config import get_settings
from forliosa.db import session_factory
from forliosa.models import Group, GroupMember, GroupPass, User
from forliosa.services import group_plans
from forliosa.services import groups as group_svc
from forliosa.timeutil import TAIPEI, now_utc
from tests.api.m5 import API, SHARE_DEFAULT, invite, join, login, make_group, me_id, token_of


def free_cap() -> int:
    return get_settings().group_free_member_cap


def boosted_cap() -> int:
    return get_settings().group_boosted_member_cap


def fill(group_id: str, n: int, tag: str = "f") -> None:
    """``n`` more members, straight into the database."""
    with session_factory()() as db:
        for i in range(n):
            uid = f"usr_{tag}{i:03d}"
            db.add(User(id=uid, email=f"{tag}{i}@x.y", display_name=f"{tag}{i}", preferences={}))
            db.flush()
            db.add(GroupMember(group_id=group_id, user_id=uid, role="member"))
        db.commit()


def count(group_id: str) -> int:
    with session_factory()() as db:
        return group_svc.member_count(db, group_id)


def accept(client, owner, group_id: str):
    return client.post(f"{API}/invites/{token_of(invite(owner, group_id))}/accept", json={"share": SHARE_DEFAULT})


def today_plus(days: int) -> str:
    return (now_utc().astimezone(TAIPEI).date() + timedelta(days=days)).isoformat()


def grant(admin, email: str, days: int = 30, **body):
    return admin.post(f"{API}/admin/group-passes", json={"email": email, "until": today_plus(days), **body})


# -- caps --------------------------------------------------------------------------------------------------------------
def test_a_new_group_is_free_with_the_lower_cap(app, client):
    g = make_group(client)
    assert g["plan"] == {"tier": "free", "until": None, "member_cap": free_cap(), "grandfathered": False,
                         "daily_report": False}
    assert client.get(f"{API}/groups").json()[0]["plan"]["member_cap"] == free_cap()
    fill(g["id"], free_cap() - 2)
    join(client, login(app, "last@x.tw", "最後一位"), g["id"])  # the last seat
    assert count(g["id"]) == free_cap()
    late = login(app, "late@x.tw", "晚到")
    token = token_of(invite(client, g["id"]))
    preview = late.get(f"{API}/invites/{token}").json()  # said before the invitee picks what to share
    assert preview["full"] is True and f"免費群組最多 {free_cap()} 位成員" in preview["full_message"]
    assert client.get(f"{API}/invites/{token}").json()["full"] is False  # a member is not joining
    r = late.post(f"{API}/invites/{token}/accept", json={"share": SHARE_DEFAULT})
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["message"] == preview["full_message"]
    assert err["code"] == "limit_reached"
    assert f"免費群組最多 {free_cap()} 位成員" in err["message"]
    assert f"加值的群組最多 {boosted_cap()} 位" in err["message"]


def test_a_grandfathered_group_keeps_fifty_whatever_its_plan(app, client):
    g = make_group(client)
    with session_factory()() as db:
        db.get(Group, g["id"]).grandfathered_member_cap = 50
        db.commit()
    plan = client.get(f"{API}/groups/{g['id']}").json()["plan"]
    assert plan == {"tier": "free", "until": None, "member_cap": 50, "grandfathered": True, "daily_report": False}
    fill(g["id"], free_cap() + 3)
    assert accept(login(app, "more@x.tw", "又一位"), client, g["id"]).status_code == 200
    fill(g["id"], 50 - count(g["id"]), tag="g")
    r = accept(login(app, "full@x.tw", "滿了"), client, g["id"])
    assert r.status_code == 409 and r.json()["error"]["message"] == "這個群組已經滿了：最多 50 位成員"


def test_two_people_cannot_both_take_the_last_seat(app, client, monkeypatch):
    """Both accept a multi-use link at once while one seat is left: the second waits for the first's write and then
    counts the members again — exactly one gets in."""
    g = make_group(client)
    fill(g["id"], free_cap() - 2)
    token = token_of(invite(client, g["id"], multi_use=True))
    users = []
    for i in range(2):
        login(app, f"racer{i}@x.tw", f"搶位{i}")
        with session_factory()() as db:
            users.append(db.scalar(select(User.id).where(User.email == f"racer{i}@x.tw")))
    real_count = group_svc.member_count
    entered = threading.Event()

    def slow_count(db, group_id):  # the first one holds the seat a moment after counting
        n = real_count(db, group_id)
        if not entered.is_set():
            entered.set()
            threading.Event().wait(0.4)
        return n

    monkeypatch.setattr(group_svc, "member_count", slow_count)
    results: dict[int, object] = {}

    def run(i: int) -> None:
        with session_factory()() as db:
            me = db.get(User, users[i])
            try:
                group_svc.accept_invite(db, token, me, dict(SHARE_DEFAULT))
                results[i] = "ok"
            except Exception as exc:  # the loser's 409
                results[i] = getattr(exc, "code", type(exc).__name__)

    first = threading.Thread(target=run, args=(0,))
    first.start()
    assert entered.wait(5)
    second = threading.Thread(target=run, args=(1,))
    second.start()
    first.join(10)
    second.join(10)
    assert sorted(map(str, results.values())) == ["limit_reached", "ok"]
    assert count(g["id"]) == free_cap()


# -- boosts: grant, attach, extend, revoke -----------------------------------------------------------------------------
def test_admin_grants_and_the_owner_attaches(app, client, admin):
    g = make_group(client, "大學同學")
    member = login(app, "m@x.tw", "阿哲")
    join(client, member, g["id"])
    r = grant(admin, "DEMO@forliosa.local ", note="綠界 #A123")
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["email"] == "demo@forliosa.local" and p["group_id"] is None and p["active"] and p["note"] == "綠界 #A123"
    assert p["until"] == today_plus(30)

    mine = client.get(f"{API}/me/group-passes").json()
    assert mine == [{"id": p["id"], "until": today_plus(30), "active": True, "attached": False, "group": None}]
    assert member.get(f"{API}/me/group-passes").json() == []
    r = member.put(f"{API}/groups/{g['id']}/plan", json={"pass_id": p["id"]})
    assert r.status_code == 403  # only the owner
    r = client.put(f"{API}/groups/{g['id']}/plan", json={"pass_id": "gps_nope"})
    assert r.status_code == 404
    r = client.put(f"{API}/groups/{g['id']}/plan", json={"pass_id": p["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["plan"] == {"tier": "boosted", "until": today_plus(30), "member_cap": boosted_cap(),
                                "grandfathered": False, "daily_report": True}
    assert member.get(f"{API}/groups/{g['id']}").json()["plan"]["tier"] == "boosted"  # every member sees it
    mine = client.get(f"{API}/me/group-passes").json()[0]
    assert mine["attached"] and mine["group"] == {"id": g["id"], "name": "大學同學", "my_role": "owner"}

    listed = admin.get(f"{API}/admin/group-passes")
    assert listed.status_code == 200
    assert listed.json()[0]["group_id"] == g["id"] and listed.json()[0]["attached_at"]
    assert "大學同學" not in listed.text and "阿哲" not in listed.text  # never the group's name or members

    fill(g["id"], free_cap())  # past the free cap: a boosted group takes them
    assert accept(login(app, "x@x.tw", "又來"), client, g["id"]).status_code == 200


def test_admin_grant_checks(app, client, admin):
    g = make_group(client)
    other = login(app, "o@x.tw", "別人")
    theirs = make_group(other, "別人的群組")
    assert grant(admin, "nobody@x.tw").json()["error"]["code"] == "user_not_found"
    r = admin.post(f"{API}/admin/group-passes", json={"email": "demo@forliosa.local", "until": today_plus(-1)})
    assert r.status_code == 422 and r.json()["error"]["code"] == "until_in_past"
    for far in ("9999-12-31", today_plus(365 * 5 + 2)):  # a typo, not a 500 (end_of would overflow)
        r = admin.post(f"{API}/admin/group-passes", json={"email": "demo@forliosa.local", "until": far})
        assert r.status_code == 422 and r.json()["error"]["code"] == "until_too_far"
    r = grant(admin, "demo@forliosa.local", group_id=theirs["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_group_owner"
    assert grant(admin, "demo@forliosa.local", group_id="grp_missing").json()["error"]["code"] == "group_not_found"
    r = grant(admin, "demo@forliosa.local", group_id=g["id"])  # by group id: attached at once
    assert r.status_code == 201 and r.json()["group_id"] == g["id"]
    assert client.get(f"{API}/groups/{g['id']}").json()["plan"]["tier"] == "boosted"
    assert client.get(f"{API}/admin/group-passes").status_code == 404  # not a site admin
    assert client.post(f"{API}/admin/group-passes", json={"email": "demo@forliosa.local",
                                                          "until": today_plus(3)}).status_code == 404


def test_extend_revoke_and_expiry_never_remove_anyone(app, client, admin):
    g = make_group(client)
    p = grant(admin, "demo@forliosa.local", days=10, group_id=g["id"]).json()
    r = admin.patch(f"{API}/admin/group-passes/{p['id']}", json={"until": today_plus(400), "note": "年繳"})
    assert r.status_code == 200 and r.json()["until"] == today_plus(400) and r.json()["note"] == "年繳"
    assert client.get(f"{API}/groups/{g['id']}").json()["plan"]["until"] == today_plus(400)
    fill(g["id"], free_cap() + 4)  # 1 + cap + 4 members while boosted
    members = count(g["id"])

    with session_factory()() as db:  # the boost ends
        db.get(GroupPass, p["id"]).until = now_utc() - timedelta(minutes=1)
        db.commit()
    plan = client.get(f"{API}/groups/{g['id']}").json()["plan"]
    assert plan["tier"] == "free" and plan["member_cap"] == free_cap() and not plan["daily_report"]
    assert count(g["id"]) == members  # nobody removed
    r = accept(login(app, "new@x.tw", "新人"), client, g["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "limit_reached"
    row = admin.get(f"{API}/admin/group-passes").json()[0]
    assert row["active"] is False  # still listed, so it can be extended
    r = client.put(f"{API}/groups/{g['id']}/plan", json={"pass_id": p["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "pass_expired"

    assert admin.patch(f"{API}/admin/group-passes/{p['id']}", json={"until": today_plus(5)}).status_code == 200
    assert client.get(f"{API}/groups/{g['id']}").json()["plan"]["tier"] == "boosted"
    assert admin.delete(f"{API}/admin/group-passes/{p['id']}").status_code == 204
    assert client.get(f"{API}/groups/{g['id']}").json()["plan"]["tier"] == "free"
    assert count(g["id"]) == members
    # the record stays (payer, dates, note, group: the books and refunds), listed as ended; stopping again is a no-op
    [row] = [r for r in admin.get(f"{API}/admin/group-passes").json() if r["id"] == p["id"]]
    assert row["active"] is False and row["group_id"] == g["id"] and row["email"] == "demo@forliosa.local"
    assert admin.delete(f"{API}/admin/group-passes/{p['id']}").status_code == 204
    assert admin.delete(f"{API}/admin/group-passes/gps_nope").status_code == 404


def test_transfer_and_account_deletion_keep_the_boost(app, client, admin):
    g = make_group(client)
    heir = login(app, "heir@x.tw", "接手的人")
    join(client, heir, g["id"])
    p = grant(admin, "demo@forliosa.local", group_id=g["id"]).json()
    r = client.post(f"{API}/groups/{g['id']}/transfer", json={"user_id": me_id(heir)})
    assert r.status_code == 200 and r.json()["plan"]["tier"] == "boosted"
    # the payer is no longer the owner: they cannot move the boost away from the group they handed over
    other = make_group(client, "另一個")
    r = client.put(f"{API}/groups/{other['id']}/plan", json={"pass_id": p["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "pass_in_use"

    r = client.request("DELETE", f"{API}/me", json={"confirm": "刪除我的帳號"})
    assert r.status_code == 204, r.text
    assert heir.get(f"{API}/groups/{g['id']}").json()["plan"]["tier"] == "boosted"
    row = admin.get(f"{API}/admin/group-passes").json()[0]
    assert row["payer_user_id"] is None and row["email"] is None and row["group_id"] == g["id"]


def test_a_deleted_group_hands_the_boost_back_and_it_can_move(app, client, admin):
    a = make_group(client, "甲")
    b = make_group(client, "乙")
    p = grant(admin, "demo@forliosa.local", group_id=a["id"]).json()
    r = client.put(f"{API}/groups/{b['id']}/plan", json={"pass_id": p["id"]})  # I own both: it moves
    assert r.status_code == 200 and r.json()["plan"]["tier"] == "boosted"
    assert client.get(f"{API}/groups/{a['id']}").json()["plan"]["tier"] == "free"
    assert client.delete(f"{API}/groups/{b['id']}").status_code == 204
    mine = client.get(f"{API}/me/group-passes").json()
    assert mine[0]["attached"] is False and mine[0]["group"] is None
    assert client.put(f"{API}/groups/{a['id']}/plan", json={"pass_id": p["id"]}).status_code == 200


def test_plan_helpers():
    """The last day / end conversions and the boosted set by moment."""
    from datetime import date, datetime

    end = group_plans.end_of(date(2026, 12, 31))
    assert end == datetime(2027, 1, 1, tzinfo=TAIPEI) and group_plans.last_day(end) == date(2026, 12, 31)
