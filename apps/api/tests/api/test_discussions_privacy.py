"""Discussion privacy: what a public response may contain, who sees group content, hidden content, deleted accounts.

* Public responses never carry a user id, an email, a display name or an avatar — asserted on the serialised JSON of
  every endpoint that returns public content, for every kind of reader (nobody, another user, the author, an admin).
* Group content is 404 for non-members (and for people without a session) on every endpoint.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from forliosa.models import User
from tests.api.discussions import (
    API,
    GAP,
    IDENTITY_KEYS,
    error,
    keys_of,
    post_reply,
    post_topic,
    replies,
    set_name,
    topics,
)
from tests.api.m5 import join, login, make_group, me_id

TOPICS_URL = f"{API}/discussions/topics"
REACTIONS_URL = f"{API}/discussions/reactions"
REPORTS_URL = f"{API}/discussions/reports"
ADMIN_URL = f"{API}/admin/discussions"
AVATAR = "https://cdn.discordapp.example/avatars/1234567890/secret-avatar.png"


def set_avatar(engine, email: str) -> None:
    with Session(engine) as db:
        db.execute(update(User).where(User.email == email).values(avatar_url=AVATAR))
        db.commit()


# -- public responses carry no identity -----------------------------------------------------------------------
def test_public_responses_never_contain_identity(client, other_client, admin, clock, engine):
    """``client`` (示範使用者 / demo@forliosa.local, with an avatar) posts publicly as 阿土伯."""
    set_avatar(engine, "demo@forliosa.local")
    set_avatar(engine, "other@forliosa.local")
    author_id, other_id = me_id(client), me_id(other_client)
    set_name(client, "阿土伯")
    set_name(other_client, "路人甲")
    set_name(admin, "值班的人")
    created = post_topic(client, clock, symbols=["2330"])
    reply = post_reply(client, clock, created["id"], "作者自己的回覆")
    other_reply = post_reply(other_client, clock, created["id"], "路過留言")
    target = f"topic:{created['id']}"
    assert other_client.put(REACTIONS_URL, json={"target": target, "emoji": "👍"}).status_code == 204
    assert other_client.post(REPORTS_URL, json={"target": target, "reason": "spam", "note": "看起來像廣告"}
                             ).status_code == 204
    assert client.post(REPORTS_URL, json={"target": f"reply:{other_reply['id']}", "reason": "abuse"}
                       ).status_code == 204
    suspension = admin.post(f"{ADMIN_URL}/suspensions", json={"target": target, "days": 7, "reason": "洗版"})
    assert suspension.status_code == 201, suspension.text

    anon = TestClient(client.app)
    responses = {"created": created, "reply": reply, "other_reply": other_reply, "suspension": suspension.json()}
    for who, c in (("anon", anon), ("other", other_client), ("author", client), ("admin", admin)):
        responses[f"{who}:list"] = c.get(TOPICS_URL).json()
        responses[f"{who}:list-symbol"] = c.get(TOPICS_URL, params={"symbol": "2330", "sort": "new"}).json()
        responses[f"{who}:detail"] = c.get(f"{TOPICS_URL}/{created['id']}").json()
        responses[f"{who}:replies"] = c.get(f"{TOPICS_URL}/{created['id']}/replies").json()
        if who != "anon":
            responses[f"{who}:all"] = c.get(TOPICS_URL, params={"scope": "all"}).json()
            responses[f"{who}:mine"] = c.get(TOPICS_URL, params={"mine": "true"}).json()
    for status in ("open", "resolved"):
        responses[f"admin:reports:{status}"] = admin.get(f"{ADMIN_URL}/reports", params={"status": status}).json()
    responses["admin:suspensions"] = admin.get(f"{ADMIN_URL}/suspensions").json()
    assert responses["admin:reports:open"]["items"] and responses["admin:suspensions"]

    secrets = [author_id, other_id, me_id(admin), "demo@forliosa.local", "other@forliosa.local",
               "boss@forliosa.local", "示範使用者", "別人", "站長本人", AVATAR, "avatar"]
    for name, body in responses.items():
        assert "error" not in body, (name, body)
        text = json.dumps(body, ensure_ascii=False)
        for secret in secrets:
            assert secret not in text, (name, secret)
        assert not keys_of(body) & IDENTITY_KEYS, (name, keys_of(body) & IDENTITY_KEYS)
    # … and the authors are exactly {"name", "is_you"}
    assert responses["anon:detail"]["author"] == {"name": "阿土伯", "is_you": False}
    assert responses["author:detail"]["author"] == {"name": "阿土伯", "is_you": True}
    assert [r["author"] for r in responses["other:replies"]["items"]] == [
        {"name": "阿土伯", "is_you": False}, {"name": "路人甲", "is_you": True}]
    assert responses["admin:suspensions"][0]["public_name"] == "阿土伯"
    assert {i["author_name"] for i in responses["admin:reports:open"]["items"]} == {"阿土伯", "路人甲"}


def test_the_public_name_is_not_shown_in_groups(client, other_client, clock):
    """The other direction: a group never learns a member's public name."""
    set_name(client, "阿土伯")
    g = make_group(client)
    join(client, other_client, g["id"])
    t = post_topic(client, clock, "group", group_id=g["id"])
    post_reply(client, clock, t["id"])
    bodies = [other_client.get(f"{API}/groups/{g['id']}").json(), other_client.get(f"{TOPICS_URL}/{t['id']}").json(),
              other_client.get(f"{TOPICS_URL}/{t['id']}/replies").json(),
              other_client.get(TOPICS_URL, params={"scope": "group", "group_id": g["id"]}).json(),
              other_client.get(f"{API}/groups/{g['id']}/feed").json()]
    for body in bodies:
        assert "阿土伯" not in json.dumps(body, ensure_ascii=False) and "public_name" not in keys_of(body)


# -- group scope ------------------------------------------------------------------------------------------------
def test_group_content_shows_the_member_identity_to_members_only(app, client, other_client, clock, engine):
    set_avatar(engine, "demo@forliosa.local")
    g = make_group(client, "家族投資")
    join(client, other_client, g["id"])
    t = post_topic(client, clock, "group", group_id=g["id"], symbols=["2330"])
    r = post_reply(other_client, clock, t["id"], "群組裡的回覆")
    assert t["scope"] == "group" and t["group"] == {"id": g["id"], "name": "家族投資"}
    assert t["author"] == {"name": "示範使用者", "is_you": True, "user_id": me_id(client), "avatar_url": AVATAR}
    assert r["author"] == {"name": "別人", "is_you": True, "user_id": me_id(other_client), "avatar_url": None}
    seen = other_client.get(f"{TOPICS_URL}/{t['id']}").json()
    assert seen["author"] == {"name": "示範使用者", "is_you": False, "user_id": me_id(client), "avatar_url": AVATAR}
    assert (seen["can_report"], seen["can_delete"], seen["can_reply"]) == (False, False, True)  # no reports in groups
    assert [x["can_report"] for x in replies(client, t["id"])] == [False]
    [listed] = topics(other_client, scope="group", group_id=g["id"])
    assert listed["id"] == t["id"] and listed["group"] == {"id": g["id"], "name": "家族投資"}
    assert topics(client) == [] and topics(TestClient(app)) == []  # not among the public topics
    assert topics(client, symbol="2330") == []

    stranger = login(app, "stranger@forliosa.local", "陌生人")
    set_name(stranger, "陌生的人")
    target, reply_target = f"topic:{t['id']}", f"reply:{r['id']}"
    for who in (stranger, TestClient(app)):
        signed_in = who is stranger
        calls = {
            "list": who.get(TOPICS_URL, params={"scope": "group", "group_id": g["id"]}),
            "detail": who.get(f"{TOPICS_URL}/{t['id']}"),
            "replies": who.get(f"{TOPICS_URL}/{t['id']}/replies"),
            "reply": who.post(f"{TOPICS_URL}/{t['id']}/replies", json={"body": "我不是成員"}),
            "new topic": who.post(TOPICS_URL, json={"scope": "group", "group_id": g["id"], "title": "標題",
                                                    "body": "內文"}),
            "delete topic": who.delete(f"{TOPICS_URL}/{t['id']}"),
            "delete reply": who.delete(f"{API}/discussions/replies/{r['id']}"),
            "react topic": who.put(REACTIONS_URL, json={"target": target, "emoji": "👍"}),
            "react reply": who.put(REACTIONS_URL, json={"target": reply_target, "emoji": "👍"}),
            "unreact": who.delete(REACTIONS_URL, params={"target": target, "emoji": "👍"}),
            "report topic": who.post(REPORTS_URL, json={"target": target, "reason": "spam"}),
            "report reply": who.post(REPORTS_URL, json={"target": reply_target, "reason": "spam"}),
        }
        for name, resp in calls.items():
            # without a session: the two reads by id are 404 (nothing is revealed), everything else needs login
            expected = 404 if signed_in or name in ("detail", "replies") else 401
            assert resp.status_code == expected, (signed_in, name, resp.text)
            assert error(resp) == ("not_found" if expected == 404 else "unauthorized")
            assert "家族投資" not in resp.text and "示範使用者" not in resp.text
    assert topics(stranger, scope="all") == [] and topics(stranger, mine="true") == []
    # nothing changed
    assert client.get(f"{TOPICS_URL}/{t['id']}").json()["reactions"] == []
    assert len(replies(client, t["id"])) == 1


def test_scope_all_is_public_plus_my_groups_only(app, client, other_client, clock):
    set_name(client, "阿土伯")
    mine_group, their_group = make_group(client, "我的群組"), make_group(other_client, "他們的群組")
    third = login(app, "third@forliosa.local", "第三人")
    join(other_client, third, their_group["id"])
    public = post_topic(client, clock, title="公開的")
    in_mine = post_topic(client, clock, "group", group_id=mine_group["id"], title="我群組的")
    in_theirs = post_topic(other_client, clock, "group", group_id=their_group["id"], title="他們群組的")
    assert [t["id"] for t in topics(client, scope="all")] == [in_mine["id"], public["id"]]
    assert [t["id"] for t in topics(other_client, scope="all")] == [in_theirs["id"], public["id"]]
    assert [t["id"] for t in topics(third, scope="all", sort="new")] == [in_theirs["id"], public["id"]]
    assert [t["id"] for t in topics(client, scope="public")] == [public["id"]]
    # group_id is only used with scope=group: it never widens another scope
    assert [t["id"] for t in topics(client, scope="all", group_id=their_group["id"])] == [in_mine["id"], public["id"]]
    assert [t["id"] for t in topics(client, scope="public", group_id=their_group["id"])] == [public["id"]]
    r = client.get(TOPICS_URL, params={"scope": "group", "group_id": their_group["id"]})
    assert r.status_code == 404 and error(r) == "not_found"
    assert client.get(TOPICS_URL, params={"scope": "group"}).status_code == 422
    assert client.get(TOPICS_URL, params={"scope": "group", "group_id": "grp_nope"}).status_code == 404
    # joining a group opens its topics
    join(other_client, client, their_group["id"])
    assert [t["id"] for t in topics(client, scope="all")] == [in_theirs["id"], in_mine["id"], public["id"]]


def test_group_owner_and_admins_delete_members_cannot(app, client, other_client, clock):
    g = make_group(client)
    join(client, other_client, g["id"])
    third = login(app, "third@forliosa.local", "第三人")
    join(client, third, g["id"])
    t = post_topic(other_client, clock, "group", group_id=g["id"])
    r1 = post_reply(third, clock, t["id"], "第三人的回覆")
    r2 = post_reply(third, clock, t["id"], "第三人的第二則")
    # a plain member cannot delete someone else's
    resp = third.delete(f"{TOPICS_URL}/{t['id']}")
    assert resp.status_code == 403 and error(resp) == "forbidden"
    assert other_client.delete(f"{API}/discussions/replies/{r1['id']}").status_code == 403
    assert [x["can_delete"] for x in replies(other_client, t["id"])] == [False, False]
    assert client.get(f"{TOPICS_URL}/{t['id']}").json()["can_delete"] is True  # the owner
    assert [x["can_delete"] for x in replies(client, t["id"])] == [True, True]
    # an admin can
    role = client.patch(f"{API}/groups/{g['id']}/members/{me_id(third)}", json={"role": "admin"})
    assert role.status_code == 200, role.text
    assert third.get(f"{TOPICS_URL}/{t['id']}").json()["can_delete"] is True
    assert client.delete(f"{API}/discussions/replies/{r1['id']}").status_code == 204  # the owner
    assert third.delete(f"{API}/discussions/replies/{r2['id']}").status_code == 204  # its author
    assert third.delete(f"{TOPICS_URL}/{t['id']}").status_code == 204  # the admin
    assert topics(client, scope="group", group_id=g["id"]) == []


def test_leaving_a_group_hides_it_and_keeps_what_was_posted(client, other_client, clock, engine):
    set_avatar(engine, "other@forliosa.local")
    g = make_group(client)
    join(client, other_client, g["id"])
    t = post_topic(other_client, clock, "group", group_id=g["id"], title="離開前發的")
    r = post_reply(other_client, clock, t["id"], "離開前回的")
    assert other_client.delete(f"{API}/groups/{g['id']}/members/{me_id(other_client)}").status_code == 204
    # gone for the one who left — also their own posts
    assert other_client.get(f"{TOPICS_URL}/{t['id']}").status_code == 404
    assert other_client.get(f"{TOPICS_URL}/{t['id']}/replies").status_code == 404
    assert other_client.delete(f"{TOPICS_URL}/{t['id']}").status_code == 404
    assert other_client.delete(f"{API}/discussions/replies/{r['id']}").status_code == 404
    assert topics(other_client, scope="all") == [] and topics(other_client, mine="true") == []
    # still there for the group, without the identity of someone who is no longer a member
    left = {"name": "已離開的成員", "is_you": False, "user_id": None, "avatar_url": None}
    assert client.get(f"{TOPICS_URL}/{t['id']}").json()["author"] == left
    assert [x["author"] for x in replies(client, t["id"])] == [left]
    assert [x["author"] for x in topics(client, scope="all")] == [left]


def test_group_content_cannot_be_reported_or_moderated(client, other_client, admin, clock):
    g = make_group(client)
    join(client, other_client, g["id"])
    t = post_topic(client, clock, "group", group_id=g["id"])
    r = post_reply(client, clock, t["id"])
    for target in (f"topic:{t['id']}", f"reply:{r['id']}"):
        resp = other_client.post(REPORTS_URL, json={"target": target, "reason": "abuse"})
        assert resp.status_code == 422 and error(resp) == "validation_error"
        # site admins do not see group content at all
        for action in ("hide", "unhide", "dismiss"):
            resp = admin.post(f"{ADMIN_URL}/moderation", json={"target": target, "action": action})
            assert resp.status_code == 404, (target, action)
        resp = admin.post(f"{ADMIN_URL}/suspensions", json={"target": target, "days": 1})
        assert resp.status_code == 404
    assert admin.get(f"{TOPICS_URL}/{t['id']}").status_code == 404
    assert admin.get(f"{ADMIN_URL}/reports").json()["items"] == []
    assert client.get(f"{TOPICS_URL}/{t['id']}").json()["status"] == "visible"


def test_deleting_a_group_deletes_its_discussions(client, other_client, clock, engine):
    from forliosa import models as m

    set_name(client, "阿土伯")
    g = make_group(client)
    join(client, other_client, g["id"])
    public = post_topic(client, clock)
    t = post_topic(client, clock, "group", group_id=g["id"], symbols=["0050"])
    r = post_reply(other_client, clock, t["id"])
    assert other_client.put(REACTIONS_URL, json={"target": f"reply:{r['id']}", "emoji": "🎉"}).status_code == 204
    assert client.delete(f"{API}/groups/{g['id']}").status_code == 204
    assert client.get(f"{TOPICS_URL}/{t['id']}").status_code == 404
    with Session(engine) as db:
        assert list(db.scalars(select(m.DiscussionTopic.id))) == [public["id"]]
        for model in (m.DiscussionReply, m.DiscussionReaction, m.DiscussionTopicSymbol):
            assert list(db.scalars(select(model))) == []


# -- hidden content -----------------------------------------------------------------------------------------------
def test_hidden_topic_is_unlisted_and_opens_without_its_body(client, other_client, admin, clock):
    set_name(client, "阿土伯")
    set_name(other_client, "路人甲")
    t = post_topic(client, clock, body="會被隱藏的內文", symbols=["2330"])
    post_reply(other_client, clock, t["id"], "隱藏前的回覆")
    target = f"topic:{t['id']}"
    assert admin.post(f"{ADMIN_URL}/moderation", json={"target": target, "action": "hide"}).status_code == 204
    anon = TestClient(client.app)
    for c in (anon, other_client, client, admin):
        assert topics(c) == [] and topics(c, symbol="2330", sort="new") == []
    assert topics(client, mine="true") == [] and topics(client, scope="all") == []
    for c in (anon, other_client):
        detail = c.get(f"{TOPICS_URL}/{t['id']}").json()
        assert detail["status"] == "hidden" and detail["body"] is None and detail["can_reply"] is False
        assert "會被隱藏的內文" not in json.dumps(detail, ensure_ascii=False)
    for c in (client, admin):  # the author and site admins still get the body
        detail = c.get(f"{TOPICS_URL}/{t['id']}").json()
        assert detail["status"] == "hidden" and detail["body"] == "會被隱藏的內文"
    assert [x["body"] for x in replies(anon, t["id"])] == ["隱藏前的回覆"]  # replies stay readable
    clock.tick(seconds=GAP)
    for c in (other_client, client):
        r = c.post(f"{TOPICS_URL}/{t['id']}/replies", json={"body": "還能回嗎"})
        assert r.status_code == 409 and error(r) == "topic_hidden", r.text
    assert client.get(f"{TOPICS_URL}/{t['id']}").json()["can_delete"] is True  # the author may still delete it
    assert admin.post(f"{ADMIN_URL}/moderation", json={"target": target, "action": "unhide"}).status_code == 204
    assert [x["id"] for x in topics(anon)] == [t["id"]]
    assert anon.get(f"{TOPICS_URL}/{t['id']}").json()["body"] == "會被隱藏的內文"
    assert other_client.post(f"{TOPICS_URL}/{t['id']}/replies", json={"body": "又能回了"}).status_code == 201


def test_hidden_reply_stays_in_place_without_its_body(client, other_client, admin, clock):
    set_name(client, "阿土伯")
    set_name(other_client, "路人甲")
    t = post_topic(client, clock)
    post_reply(client, clock, t["id"], "第一則")
    hidden = post_reply(other_client, clock, t["id"], "會被隱藏的回覆")
    post_reply(client, clock, t["id"], "第三則")
    target = f"reply:{hidden['id']}"
    assert admin.post(f"{ADMIN_URL}/moderation", json={"target": target, "action": "hide"}).status_code == 204
    for c in (TestClient(client.app), client):
        listed = replies(c, t["id"])
        assert [(x["body"], x["status"]) for x in listed] == [("第一則", "visible"), (None, "hidden"),
                                                             ("第三則", "visible")]
        assert listed[1]["author"]["name"] == "路人甲"
    for c in (other_client, admin):
        assert [x["body"] for x in replies(c, t["id"])] == ["第一則", "會被隱藏的回覆", "第三則"]
    detail = client.get(f"{TOPICS_URL}/{t['id']}").json()
    assert detail["reply_count"] == 3 and detail["status"] == "visible"
    assert other_client.post(f"{TOPICS_URL}/{t['id']}/replies", json={"body": "主題沒被隱藏"}).status_code == 201


# -- deleted accounts -----------------------------------------------------------------------------------------------
def test_deleting_an_account_keeps_its_content_without_an_author(client, other_client, clock, engine):
    set_name(client, "阿土伯")
    set_name(other_client, "路人甲")
    g = make_group(other_client)
    join(other_client, client, g["id"])
    public = post_topic(client, clock, title="公開主題")
    public_reply = post_reply(client, clock, public["id"], "公開回覆")
    grouped = post_topic(client, clock, "group", group_id=g["id"], title="群組主題")
    group_reply = post_reply(client, clock, grouped["id"], "群組回覆")
    assert client.put(REACTIONS_URL, json={"target": f"topic:{public['id']}", "emoji": "👍"}).status_code == 204
    with Session(engine) as db:  # there is no endpoint yet: the row goes, the database keeps the content
        db.execute(delete(User).where(User.email == "demo@forliosa.local"))
        db.commit()
    assert client.get(f"{API}/users/me").status_code == 401
    detail = other_client.get(f"{TOPICS_URL}/{public['id']}").json()
    assert detail["author"] == {"name": None, "is_you": False} and detail["body"] == "想聽聽大家的看法"
    assert detail["reactions"] == [] and detail["can_report"] is True
    [r] = replies(other_client, public["id"])
    assert r["id"] == public_reply["id"] and r["author"] == {"name": None, "is_you": False} and r["body"] == "公開回覆"
    gone = {"name": None, "is_you": False, "user_id": None, "avatar_url": None}
    assert other_client.get(f"{TOPICS_URL}/{grouped['id']}").json()["author"] == gone
    [gr] = replies(other_client, grouped["id"])
    assert gr["id"] == group_reply["id"] and gr["author"] == gone
    assert [t["author"] for t in topics(other_client, scope="all", sort="new")] == [gone, {"name": None,
                                                                                         "is_you": False}]
    # the name is free again
    assert set_name(login(client.app, "new@forliosa.local", "新來的"), "阿土伯")["public_name"] == "阿土伯"
