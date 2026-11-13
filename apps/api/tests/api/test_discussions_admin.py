"""Discussion moderation: reports of public content, site admins (ADMIN_EMAILS), hide / unhide / dismiss, and public
posting suspensions."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from forliosa.config import Settings, get_settings
from tests.api.discussions import API, GAP, error, post_reply, post_topic, set_name, topics
from tests.api.m5 import login, make_group

TOPICS_URL = f"{API}/discussions/topics"
REPORTS_URL = f"{API}/discussions/reports"
ADMIN_URL = f"{API}/admin/discussions"
PERMANENT = "9999-12-31T00:00:00Z"


def reports(admin, **params) -> list[dict]:
    r = admin.get(f"{ADMIN_URL}/reports", params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


# -- who is a site admin ------------------------------------------------------------------------------------------
def test_admin_emails_setting_is_a_case_insensitive_comma_separated_list(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", " Boss@Forliosa.Local , second@example.com,, ")
    assert Settings(_env_file=None).admin_emails == ["boss@forliosa.local", "second@example.com"]
    monkeypatch.delenv("ADMIN_EMAILS")
    assert Settings(_env_file=None).admin_emails == []


def test_is_admin_in_me(client, admin, monkeypatch):
    assert admin.get(f"{API}/users/me").json()["is_admin"] is True
    assert client.get(f"{API}/users/me").json()["is_admin"] is False
    monkeypatch.setattr(get_settings(), "admin_emails", ["BOSS@forliosa.local"])  # compared without case
    assert admin.get(f"{API}/me").json()["is_admin"] is True
    monkeypatch.setattr(get_settings(), "admin_emails", [])
    assert admin.get(f"{API}/me").json()["is_admin"] is False


def test_admin_endpoints_are_404_for_everyone_else(client, other_client, admin, clock):
    set_name(other_client, "路人甲")
    t = post_topic(other_client, clock)
    target = f"topic:{t['id']}"
    suspension = admin.post(f"{ADMIN_URL}/suspensions", json={"target": target, "days": 1}).json()

    def calls(c):
        return [
            c.get(f"{ADMIN_URL}/reports"),
            c.get(f"{ADMIN_URL}/reports", params={"status": "nonsense"}),
            c.post(f"{ADMIN_URL}/moderation", json={"target": target, "action": "hide"}),
            c.post(f"{ADMIN_URL}/moderation", json={"nonsense": True}),
            c.get(f"{ADMIN_URL}/suspensions"),
            c.post(f"{ADMIN_URL}/suspensions", json={"target": target, "days": None}),
            c.delete(f"{ADMIN_URL}/suspensions/{suspension['id']}"),
            c.get(f"{API}/admin"),
            c.get(f"{API}/admin/users"),
        ]

    for c in (client, other_client):  # signed in, not an admin: 404 before anything else (also before validation)
        for r in calls(c):
            assert r.status_code == 404 and error(r) == "not_found", (r.request.method, r.request.url.path, r.text)
    for r in calls(TestClient(client.app))[:7]:
        assert r.status_code == 401
    # nothing happened
    assert other_client.get(f"{TOPICS_URL}/{t['id']}").json()["status"] == "visible"
    assert [s["id"] for s in admin.get(f"{ADMIN_URL}/suspensions").json()] == [suspension["id"]]
    assert other_client.get(f"{API}/users/me").json()["public_posting_suspended_until"] != PERMANENT


# -- reports -------------------------------------------------------------------------------------------------------
def test_reports_one_per_user_per_target_and_not_on_own_content(app, client, other_client, admin, clock):
    set_name(client, "阿土伯")
    set_name(other_client, "路人甲")
    third = login(app, "third@forliosa.local", "第三人")  # reporting needs no public name
    t = post_topic(client, clock, title="明牌報給你", body="加 LINE 群組\n保證獲利")
    r = post_reply(other_client, clock, t["id"], "回覆內文")
    topic_target, reply_target = f"topic:{t['id']}", f"reply:{r['id']}"
    # own content
    for c, target in ((client, topic_target), (other_client, reply_target)):
        resp = c.post(REPORTS_URL, json={"target": target, "reason": "spam"})
        assert resp.status_code == 422 and error(resp) == "validation_error"
    # bad input
    for body in ({"target": topic_target, "reason": "boring"}, {"target": topic_target},
                 {"target": f"chart_comment:{t['id']}", "reason": "spam"}, {"target": "topic", "reason": "spam"},
                 {"target": topic_target, "reason": "spam", "note": "字" * 301},
                 {"target": topic_target, "reason": "spam", "note": "零寬\u200b"}):
        assert other_client.post(REPORTS_URL, json=body).status_code == 422, body
    assert other_client.post(REPORTS_URL, json={"target": "topic:top_nope", "reason": "spam"}).status_code == 404
    assert other_client.post(REPORTS_URL, json={"target": "reply:rep_nope", "reason": "spam"}).status_code == 404
    assert reports(admin) == []

    resp = other_client.post(REPORTS_URL, json={"target": topic_target, "reason": "solicitation", "note": " 拉群組 "})
    assert resp.status_code == 204 and resp.content == b""
    for _ in range(2):  # again, also with another reason: still one report
        assert other_client.post(REPORTS_URL, json={"target": topic_target, "reason": "spam"}).status_code == 204
    clock.tick(minutes=5)
    assert third.post(REPORTS_URL, json={"target": topic_target, "reason": "spam", "note": ""}).status_code == 204
    clock.tick(minutes=1)
    assert third.post(REPORTS_URL, json={"target": reply_target, "reason": "other"}).status_code == 204

    [reply_item, topic_item] = reports(admin)  # the most recently reported first
    assert set(topic_item) == {"target", "kind", "excerpt", "author_name", "topic_id", "report_count", "reasons",
                               "notes", "first_reported_at", "status", "hidden"}
    assert topic_item["target"] == topic_target and topic_item["kind"] == "topic" and topic_item["topic_id"] == t["id"]
    assert topic_item["excerpt"] == "明牌報給你｜加 LINE 群組 保證獲利" and topic_item["author_name"] == "阿土伯"
    assert topic_item["report_count"] == 2 and topic_item["reasons"] == {"solicitation": 1, "spam": 1}
    assert topic_item["notes"] == ["拉群組"] and topic_item["status"] == "open" and topic_item["hidden"] is False
    assert topic_item["first_reported_at"].endswith("Z") and topic_item["first_reported_at"] < reply_item[
        "first_reported_at"]
    assert reply_item["target"] == reply_target and reply_item["kind"] == "reply" and reply_item["topic_id"] == t["id"]
    assert reply_item["excerpt"] == "回覆內文" and reply_item["author_name"] == "路人甲"
    assert reply_item["report_count"] == 1 and reply_item["reasons"] == {"other": 1} and reply_item["notes"] == []
    assert reports(admin, status="resolved") == []
    # paging
    page = admin.get(f"{ADMIN_URL}/reports", params={"limit": 1}).json()
    assert [i["target"] for i in page["items"]] == [reply_target] and page["next_cursor"]
    rest = admin.get(f"{ADMIN_URL}/reports", params={"limit": 1, "cursor": page["next_cursor"]}).json()
    assert [i["target"] for i in rest["items"]] == [topic_target] and rest["next_cursor"] is None
    assert admin.get(f"{ADMIN_URL}/reports", params={"status": "closed"}).status_code == 422
    # the people involved cannot tell who reported
    detail = client.get(f"{TOPICS_URL}/{t['id']}").json()
    assert "report" not in "".join(k for k in detail if k != "can_report")


def test_hide_dismiss_and_unhide(app, client, other_client, admin, clock):
    set_name(client, "阿土伯")
    set_name(other_client, "路人甲")
    a = post_topic(client, clock, title="A")
    b = post_topic(client, clock, title="B")
    reply = post_reply(client, clock, b["id"], "回覆")
    for target in (f"topic:{a['id']}", f"topic:{b['id']}", f"reply:{reply['id']}"):
        assert other_client.post(REPORTS_URL, json={"target": target, "reason": "abuse"}).status_code == 204
    # dismiss: resolved, not hidden
    resp = admin.post(f"{ADMIN_URL}/moderation", json={"target": f"topic:{a['id']}", "action": "dismiss"})
    assert resp.status_code == 204 and resp.content == b""
    # hide: resolved and hidden
    assert admin.post(f"{ADMIN_URL}/moderation", json={"target": f"reply:{reply['id']}", "action": "hide"}
                      ).status_code == 204
    assert [i["target"] for i in reports(admin)] == [f"topic:{b['id']}"]
    resolved = {i["target"]: i for i in reports(admin, status="resolved")}
    assert set(resolved) == {f"topic:{a['id']}", f"reply:{reply['id']}"}
    assert resolved[f"topic:{a['id']}"]["hidden"] is False and resolved[f"topic:{a['id']}"]["status"] == "resolved"
    assert resolved[f"reply:{reply['id']}"]["hidden"] is True
    assert other_client.get(f"{TOPICS_URL}/{a['id']}").json()["status"] == "visible"
    # a new report opens a dismissed target again
    third = login(app, "third@forliosa.local", "第三人")
    assert third.post(REPORTS_URL, json={"target": f"topic:{a['id']}", "reason": "spam"}).status_code == 204
    again = {i["target"]: i for i in reports(admin)}[f"topic:{a['id']}"]
    assert again["report_count"] == 2 and again["status"] == "open" and again["reasons"] == {"abuse": 1, "spam": 1}
    # hiding without any report works too; unhide brings it back and leaves the reports resolved
    c = post_topic(client, clock, title="C")
    assert admin.post(f"{ADMIN_URL}/moderation", json={"target": f"topic:{c['id']}", "action": "hide"}
                      ).status_code == 204
    assert [t["title"] for t in topics(other_client, sort="new")] == ["B", "A"]
    assert admin.post(f"{ADMIN_URL}/moderation", json={"target": f"reply:{reply['id']}", "action": "unhide"}
                      ).status_code == 204
    assert {i["target"]: i for i in reports(admin, status="resolved")}[f"reply:{reply['id']}"]["hidden"] is False
    # bad input
    for body in ({"target": f"topic:{a['id']}", "action": "delete"}, {"target": "topic", "action": "hide"},
                 {"action": "hide"}):
        assert admin.post(f"{ADMIN_URL}/moderation", json=body).status_code == 422
    for target in ("topic:top_nope", "reply:rep_nope"):
        assert admin.post(f"{ADMIN_URL}/moderation", json={"target": target, "action": "hide"}).status_code == 404


# -- suspensions --------------------------------------------------------------------------------------------------
def test_suspension_blocks_public_posting_only(client, other_client, admin, clock):
    set_name(client, "阿土伯")
    set_name(other_client, "路人甲")
    g = make_group(client)
    t = post_topic(client, clock)
    theirs = post_topic(other_client, clock)
    r = post_reply(client, clock, theirs["id"])
    created = admin.post(f"{ADMIN_URL}/suspensions", json={"target": f"reply:{r['id']}", "days": 7, "reason": "洗版"})
    assert created.status_code == 201, created.text
    s = created.json()
    assert set(s) == {"id", "public_name", "until", "reason", "created_at"}
    assert s["id"].startswith("sus_") and s["public_name"] == "阿土伯" and s["reason"] == "洗版"
    assert s["created_at"] == clock.t.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert s["until"] == (clock.t + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert admin.get(f"{ADMIN_URL}/suspensions").json() == [s]
    assert client.get(f"{API}/users/me").json()["public_posting_suspended_until"] == s["until"]
    assert other_client.get(f"{API}/users/me").json()["public_posting_suspended_until"] is None

    clock.tick(seconds=GAP)
    for resp in (client.post(TOPICS_URL, json={"scope": "public", "title": "標題", "body": "內文"}),
                 client.post(f"{TOPICS_URL}/{theirs['id']}/replies", json={"body": "回覆"})):
        assert resp.status_code == 403 and error(resp) == "posting_suspended", resp.text
        assert resp.json()["error"]["until"] == s["until"]
    # everything else still works: group posts, reading, reactions, reports, deleting own content
    group_topic = post_topic(client, clock, "group", group_id=g["id"])
    post_reply(client, clock, group_topic["id"])
    assert client.put(f"{API}/discussions/reactions", json={"target": f"topic:{theirs['id']}", "emoji": "👍"}
                      ).status_code == 204
    assert client.post(REPORTS_URL, json={"target": f"topic:{theirs['id']}", "reason": "other"}).status_code == 204
    assert client.delete(f"{API}/discussions/replies/{r['id']}").status_code == 204
    assert client.get(f"{TOPICS_URL}/{t['id']}").json()["can_reply"] is True
    # it ends by itself
    clock.tick(days=7)
    assert admin.get(f"{ADMIN_URL}/suspensions").json() == []
    assert client.get(f"{API}/users/me").json()["public_posting_suspended_until"] is None
    assert client.post(TOPICS_URL, json={"scope": "public", "title": "標題", "body": "內文"}).status_code == 201


def test_permanent_suspension_replace_and_lift(client, other_client, admin, clock):
    set_name(client, "阿土伯")
    t = post_topic(client, clock)
    target = f"topic:{t['id']}"
    first = admin.post(f"{ADMIN_URL}/suspensions", json={"target": target, "days": 1}).json()
    forever = admin.post(f"{ADMIN_URL}/suspensions", json={"target": target, "days": None})
    assert forever.status_code == 201 and forever.json()["until"] == PERMANENT and forever.json()["reason"] is None
    assert forever.json()["id"] == first["id"]  # one suspension in force per person
    assert [s["until"] for s in admin.get(f"{ADMIN_URL}/suspensions").json()] == [PERMANENT]
    assert client.get(f"{API}/users/me").json()["public_posting_suspended_until"] == PERMANENT
    clock.tick(days=3650)
    resp = client.post(TOPICS_URL, json={"scope": "public", "title": "標題", "body": "內文"})
    assert resp.status_code == 403 and resp.json()["error"]["until"] == PERMANENT
    # lift
    resp = admin.delete(f"{ADMIN_URL}/suspensions/{first['id']}")
    assert resp.status_code == 204 and resp.content == b""
    assert admin.delete(f"{ADMIN_URL}/suspensions/{first['id']}").status_code == 204  # again: nothing to do
    assert admin.delete(f"{ADMIN_URL}/suspensions/sus_nope").status_code == 404
    assert admin.get(f"{ADMIN_URL}/suspensions").json() == []
    assert client.get(f"{API}/users/me").json()["public_posting_suspended_until"] is None
    assert client.post(TOPICS_URL, json={"scope": "public", "title": "標題", "body": "內文"}).status_code == 201
    # bad input: days must be 1, 7, 30 or an explicit null
    for body in ({"target": target, "days": 2}, {"target": target}, {"target": target, "days": "7"},
                 {"target": "user:usr_x", "days": 1}, {"target": target, "days": 1, "reason": "字" * 301}):
        assert admin.post(f"{ADMIN_URL}/suspensions", json=body).status_code == 422, body
    assert admin.post(f"{ADMIN_URL}/suspensions", json={"target": "topic:top_nope", "days": 1}).status_code == 404


def test_cannot_suspend_a_deleted_account(client, admin, clock, engine):
    from sqlalchemy import delete
    from sqlalchemy.orm import Session

    from forliosa.models import User

    set_name(client, "阿土伯")
    t = post_topic(client, clock)
    with Session(engine) as db:
        db.execute(delete(User).where(User.email == "demo@forliosa.local"))
        db.commit()
    resp = admin.post(f"{ADMIN_URL}/suspensions", json={"target": f"topic:{t['id']}", "days": 7})
    assert resp.status_code == 422 and error(resp) == "validation_error"
    # the content can still be hidden
    assert admin.post(f"{ADMIN_URL}/moderation", json={"target": f"topic:{t['id']}", "action": "hide"}
                      ).status_code == 204
