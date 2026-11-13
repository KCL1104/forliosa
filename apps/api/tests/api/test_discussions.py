"""Discussion threads: public name, topics, replies, reactions, content rules, rate limits, view-as, no AI access."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from forliosa.services import discussions as svc
from tests.api.discussions import API, GAP, error, post_reply, post_topic, replies, set_name, topics
from tests.api.m5 import login, make_group

NAME_URL = f"{API}/users/me/public-name"
TOPICS_URL = f"{API}/discussions/topics"
REACTIONS_URL = f"{API}/discussions/reactions"
# Characters that show nothing but are not "format" characters: they pass the display-name rule.
HANGUL_FILLER, ZWJ, BRAILLE_BLANK, VARIATION_SELECTOR = chr(0x3164), chr(0x200D), chr(0x2800), chr(0xFE0F)


# -- GET /users/me and the public name --------------------------------------------------------------------------
def test_me_has_the_discussion_fields_on_both_paths(client):
    for path in ("/me", "/users/me"):
        me = client.get(f"{API}{path}").json()
        assert me["public_name"] is None and me["is_admin"] is False
        assert me["public_posting_suspended_until"] is None
    set_name(client, "  阿土伯 ")
    assert client.get(f"{API}/users/me").json()["public_name"] == "阿土伯"  # trimmed
    assert client.get(f"{API}/me").json()["public_name"] == "阿土伯"
    assert TestClient(client.app).get(f"{API}/users/me").status_code == 401
    assert TestClient(client.app).put(NAME_URL, json={"public_name": "路人甲"}).status_code == 401


@pytest.mark.parametrize("name", ["一", "x", "   ", " \u3000 ", "超" * 21, "兩行\n名字", "有\tTab", "零寬\u200b字元",
                                  "反轉\u202e文字"])
def test_public_name_must_be_two_to_twenty_visible_characters_on_one_line(client, name):
    r = client.put(NAME_URL, json={"public_name": name})
    assert r.status_code == 422 and error(r) == "validation_error", r.text
    assert client.get(f"{API}/users/me").json()["public_name"] is None


@pytest.mark.parametrize("name", ["forliosa", "Forliosa 粉絲", "官方", "官方帳號", "小管理員", "站方公告", "Admin",
                                  "superADMIN1", "ＡＤＭＩＮ", "System", "s y s t e m", "ｓｙｓｔｅｍ通知"])
def test_public_name_may_not_contain_a_reserved_word(client, name):
    r = client.put(NAME_URL, json={"public_name": name})
    assert r.status_code == 422 and error(r) == "validation_error", r.text


@pytest.mark.parametrize("name", [HANGUL_FILLER * 2, ZWJ * 3, BRAILLE_BLANK * 4, "阿" + HANGUL_FILLER,
                                  "阿" + ZWJ + VARIATION_SELECTOR, "ad" + ZWJ + "min", "官" + HANGUL_FILLER + "方"])
def test_public_name_must_show_two_characters_and_cannot_hide_a_reserved_word(client, name):
    r = client.put(NAME_URL, json={"public_name": name})
    assert r.status_code == 422 and error(r) == "validation_error", r.text


def test_public_name_is_unique_ignoring_case_and_width(client, other_client):
    set_name(client, "Abc王")
    for clash in ("Abc王", "abc王", "ABC王", "ａｂｃ王", "Ａbc王", "Abc王" + HANGUL_FILLER, "Abc" + ZWJ + "王",
                  "Abc王" + VARIATION_SELECTOR, "A" + BRAILLE_BLANK + "bc王"):  # look-alikes are the same name
        r = other_client.put(NAME_URL, json={"public_name": clash})
        assert r.status_code == 409 and error(r) == "public_name_taken", (clash, r.text)
    assert set_name(other_client, "Abc王2")["public_name"] == "Abc王2"


def test_public_name_changes_once_per_seven_days(client, clock):
    set_name(client, "阿土柏")
    assert set_name(client, "阿土柏")["public_name"] == "阿土柏"  # the same name again is not a change
    # The first choice does not start the cooldown: a typo can be fixed once right away; that change starts it.
    assert set_name(client, "阿土伯")["public_name"] == "阿土伯"
    r = client.put(NAME_URL, json={"public_name": "阿土伯二號"})
    assert r.status_code == 409 and error(r) == "public_name_cooldown", r.text
    assert r.json()["error"]["retry_after_days"] == 7
    clock.tick(days=6, hours=1)
    r = client.put(NAME_URL, json={"public_name": "阿土伯二號"})
    assert r.status_code == 409 and r.json()["error"]["retry_after_days"] == 1
    clock.tick(hours=23)
    assert set_name(client, "阿土伯二號")["public_name"] == "阿土伯二號"
    assert client.put(NAME_URL, json={"public_name": "阿土伯三號"}).status_code == 409
    # the old name is free again for someone else
    assert set_name(login(client.app, "third@forliosa.local", "第三人"), "阿土伯")["public_name"] == "阿土伯"


def test_old_posts_show_the_new_public_name(client, other_client, clock):
    set_name(client, "阿土伯")
    t = post_topic(client, clock)
    r = post_reply(client, clock, t["id"])
    clock.tick(days=8)
    set_name(client, "土伯改名了")
    assert other_client.get(f"{TOPICS_URL}/{t['id']}").json()["author"] == {"name": "土伯改名了", "is_you": False}
    assert replies(other_client, t["id"])[0]["author"] == {"name": "土伯改名了", "is_you": False}
    assert r["author"] == {"name": "阿土伯", "is_you": True}


def test_public_posts_need_a_public_name_and_group_posts_do_not(client, other_client, clock):
    r = client.post(TOPICS_URL, json={"scope": "public", "title": "標題", "body": "內文"})
    assert r.status_code == 409 and error(r) == "public_name_required", r.text
    set_name(other_client, "路人甲")
    t = post_topic(other_client, clock)
    r = client.post(f"{TOPICS_URL}/{t['id']}/replies", json={"body": "回覆"})
    assert r.status_code == 409 and error(r) == "public_name_required"
    g = make_group(client)
    gt = post_topic(client, clock, "group", group_id=g["id"])  # the display name is used in groups
    assert gt["author"]["name"] == "示範使用者"
    assert post_reply(client, clock, gt["id"])["author"]["name"] == "示範使用者"


# -- topics -----------------------------------------------------------------------------------------------------
def test_public_topic_shape_and_reading_without_login(client, other_client, clock):
    set_name(client, "阿土伯")
    created = post_topic(client, clock, body="第一行\n第二行", symbols=["0050", "006208.TW"])
    assert set(created) == {"id", "scope", "group", "title", "symbols", "author", "created_at", "last_activity_at",
                            "reply_count", "status", "mine", "body", "reactions", "can_delete", "can_report",
                            "can_reply"}
    assert created["id"].startswith("top_") and created["scope"] == "public" and created["group"] is None
    assert created["symbols"] == [{"symbol": "0050.TW", "code": "0050", "name": "元大台灣50"},
                                  {"symbol": "006208.TW", "code": "006208", "name": "富邦台50"}]
    assert created["author"] == {"name": "阿土伯", "is_you": True}
    assert created["created_at"].endswith("Z") and created["created_at"] == created["last_activity_at"]
    assert (created["reply_count"], created["status"], created["mine"]) == (0, "visible", True)
    assert (created["can_delete"], created["can_report"], created["can_reply"]) == (True, False, True)
    assert created["body"] == "第一行\n第二行" and created["reactions"] == []

    anon = TestClient(client.app)
    [summary] = topics(anon)
    assert set(summary) == {"id", "scope", "group", "title", "excerpt", "symbols", "author", "created_at",
                            "last_activity_at", "reply_count", "status", "mine"}
    assert summary["excerpt"] == "第一行 第二行" and summary["mine"] is False
    assert summary["author"] == {"name": "阿土伯", "is_you": False}
    detail = anon.get(f"{TOPICS_URL}/{created['id']}").json()
    assert (detail["mine"], detail["can_delete"], detail["can_report"], detail["can_reply"]) == (False,) * 4
    assert replies(anon, created["id"]) == []
    # someone else who is signed in can report and reply, not delete
    theirs = other_client.get(f"{TOPICS_URL}/{created['id']}").json()
    assert (theirs["mine"], theirs["can_delete"], theirs["can_report"], theirs["can_reply"]) == (
        False, False, True, True)
    assert anon.get(f"{TOPICS_URL}/top_nope").status_code == 404


def test_everything_but_reading_public_topics_needs_a_session(client, clock):
    set_name(client, "阿土伯")
    t = post_topic(client, clock)
    anon = TestClient(client.app)
    for params in ({"scope": "group", "group_id": "grp_x"}, {"scope": "all"}, {"mine": "true"}):
        r = anon.get(TOPICS_URL, params=params)
        assert r.status_code == 401 and error(r) == "unauthorized", (params, r.text)
    target = f"topic:{t['id']}"
    calls = [
        anon.post(TOPICS_URL, json={"scope": "public", "title": "標題", "body": "內文"}),
        anon.post(f"{TOPICS_URL}/{t['id']}/replies", json={"body": "回覆"}),
        anon.delete(f"{TOPICS_URL}/{t['id']}"),
        anon.delete(f"{API}/discussions/replies/rep_x"),
        anon.put(REACTIONS_URL, json={"target": target, "emoji": "👍"}),
        anon.delete(REACTIONS_URL, params={"target": target, "emoji": "👍"}),
        anon.post(f"{API}/discussions/reports", json={"target": target, "reason": "spam"}),
    ]
    assert [r.status_code for r in calls] == [401] * len(calls)
    # a stale cookie reads public topics like no cookie at all
    anon.cookies.set("forliosa_session", "not-a-session")
    assert [x["id"] for x in topics(anon)] == [t["id"]]


@pytest.mark.parametrize("fields", [
    {"title": ""}, {"title": "   "}, {"title": "題" * 81}, {"title": "兩行\n標題"}, {"title": "零寬\u200b"},
    {"body": ""}, {"body": " \n \n"}, {"body": "文" * 5001}, {"body": "有\tTab"}, {"body": "反轉\u202e"},
    {"title": ZWJ}, {"body": BRAILLE_BLANK * 3 + "\n" + HANGUL_FILLER},
    {"body": "行分隔\u2028符"}, {"symbols": ["2330", "2317", "0050", "0056", "00878", "006208"]},
    {"scope": "everyone"}, {"scope": "public", "group_id": "grp_x"}, {"scope": "group"}, {"unknown": 1},
])
def test_topic_input_is_validated(client, clock, fields):
    set_name(client, "阿土伯")
    clock.tick(seconds=GAP)
    r = client.post(TOPICS_URL, json={"scope": "public", "title": "標題", "body": "內文", **fields})
    assert r.status_code == 422 and error(r) == "validation_error", r.text
    assert topics(client) == []


def test_topic_text_is_normalised_and_symbols_must_exist(client, clock):
    set_name(client, "阿土伯")
    t = post_topic(client, clock, title="  標題前後空白  ",
                   body="\r\n第一行  \r\n\r\n\r\n\r\n\r\n第二行\u3000\r第三行\n\n", symbols=["2330", "2330.TW", "2330"])
    assert t["title"] == "標題前後空白"
    assert t["body"] == "第一行\n\n\n第二行\n第三行"  # CRLF/CR → LF, at most two empty lines, no trailing blanks
    assert [s["symbol"] for s in t["symbols"]] == ["2330.TW"]
    assert post_topic(client, clock, title="題" * 80, body="文" * 5000)["title"] == "題" * 80
    clock.tick(seconds=GAP)
    r = client.post(TOPICS_URL, json={"scope": "public", "title": "標題", "body": "內文", "symbols": ["ZZZZ"]})
    assert r.status_code == 422 and error(r) == "unknown_symbol"
    # indices are not instruments: they cannot be tagged
    r = client.post(TOPICS_URL, json={"scope": "public", "title": "標題", "body": "內文", "symbols": ["^TAIEX"]})
    assert r.status_code == 422 and error(r) == "unknown_symbol"


def test_topic_lists_sort_filter_and_page(client, other_client, clock):
    set_name(client, "阿土伯")
    set_name(other_client, "路人甲")
    a = post_topic(client, clock, title="A", symbols=["2330"])
    b = post_topic(other_client, clock, title="B", body="長" * 300, symbols=["0050", "2330"])
    c = post_topic(client, clock, title="C")
    assert [t["title"] for t in topics(client)] == ["C", "B", "A"]  # default: last activity
    post_reply(other_client, clock, a["id"])
    assert [t["title"] for t in topics(client, sort="active")] == ["A", "C", "B"]
    assert [t["title"] for t in topics(client, sort="new")] == ["C", "B", "A"]
    listed = {t["title"]: t for t in topics(client)}
    assert listed["A"]["reply_count"] == 1 and listed["A"]["last_activity_at"] > listed["A"]["created_at"]
    assert listed["B"]["excerpt"] == "長" * 120
    # filters
    assert [t["title"] for t in topics(client, symbol="2330")] == ["A", "B"]
    assert [t["title"] for t in topics(client, symbol="0050.tw")] == ["B"]
    assert topics(client, symbol="9999") == []
    assert [t["title"] for t in topics(client, mine="true", sort="new")] == ["C", "A"]
    assert [t["title"] for t in topics(other_client, mine="true")] == ["B"]
    assert [t["mine"] for t in topics(other_client, sort="new")] == [False, True, False]
    # paging: every topic once, in order
    seen, cursor = [], None
    for _ in range(3):
        page = client.get(TOPICS_URL, params={"limit": 1, "sort": "new", **({"cursor": cursor} if cursor else {})})
        seen += [t["id"] for t in page.json()["items"]]
        cursor = page.json()["next_cursor"]
    assert seen == [c["id"], b["id"], a["id"]] and cursor is None
    assert client.get(TOPICS_URL, params={"cursor": "###"}).status_code == 422
    assert client.get(TOPICS_URL, params={"sort": "hot"}).status_code == 422
    assert client.get(TOPICS_URL, params={"limit": 101}).status_code == 422


def test_topics_with_the_same_timestamp_page_without_gaps_or_duplicates(client, clock):
    g = make_group(client)
    ids = [post_topic(client, Frozen(clock), "group", group_id=g["id"], title=f"T{i}")["id"] for i in range(5)]
    for sort in ("active", "new"):
        seen, cursor = [], None
        while True:
            params = {"scope": "group", "group_id": g["id"], "limit": 2, "sort": sort}
            page = client.get(TOPICS_URL, params={**params, **({"cursor": cursor} if cursor else {})}).json()
            seen += [t["id"] for t in page["items"]]
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert seen == sorted(ids, reverse=True), sort


class Frozen:
    """A clock wrapper whose ``tick`` does nothing: posts land on the same instant (groups have no 10-second gap)."""

    def __init__(self, clock):
        self.clock = clock

    def tick(self, **_delta):
        return self.clock.t


# -- replies ----------------------------------------------------------------------------------------------------
def test_replies_are_listed_oldest_first_and_paged(client, other_client, clock):
    set_name(client, "阿土伯")
    set_name(other_client, "路人甲")
    t = post_topic(client, clock)
    first = post_reply(other_client, clock, t["id"], "第一則\r\n第二行")
    assert set(first) == {"id", "topic_id", "body", "author", "created_at", "status", "reactions", "mine",
                          "can_delete", "can_report"}
    assert first["id"].startswith("rep_") and first["topic_id"] == t["id"] and first["body"] == "第一則\n第二行"
    assert first["author"] == {"name": "路人甲", "is_you": True}
    assert (first["mine"], first["can_delete"], first["can_report"], first["status"]) == (True, True, False, "visible")
    post_reply(client, clock, t["id"], "第二則")
    post_reply(other_client, clock, t["id"], "第三則")
    assert [r["body"] for r in replies(client, t["id"])] == ["第一則\n第二行", "第二則", "第三則"]
    mine = replies(client, t["id"])
    assert [(r["mine"], r["can_delete"], r["can_report"]) for r in mine] == [
        (False, False, True), (True, True, False), (False, False, True)]
    page = client.get(f"{TOPICS_URL}/{t['id']}/replies", params={"limit": 2}).json()
    assert [r["body"] for r in page["items"]] == ["第一則\n第二行", "第二則"] and page["next_cursor"]
    rest = client.get(f"{TOPICS_URL}/{t['id']}/replies", params={"limit": 2, "cursor": page["next_cursor"]}).json()
    assert [r["body"] for r in rest["items"]] == ["第三則"] and rest["next_cursor"] is None
    detail = client.get(f"{TOPICS_URL}/{t['id']}").json()
    assert detail["reply_count"] == 3 and detail["last_activity_at"] == rest["items"][0]["created_at"]
    for body in ("", "  \n ", "文" * 2001, "有\tTab", "零寬\u200b"):
        clock.tick(seconds=GAP)
        r = client.post(f"{TOPICS_URL}/{t['id']}/replies", json={"body": body})
        assert r.status_code == 422, body
    assert client.post(f"{TOPICS_URL}/top_nope/replies", json={"body": "回覆"}).status_code == 404
    assert client.get(f"{TOPICS_URL}/top_nope/replies").status_code == 404


def test_replies_with_the_same_timestamp_page_in_a_stable_order(client, clock):
    g = make_group(client)
    t = post_topic(client, clock, "group", group_id=g["id"])
    ids = [post_reply(client, Frozen(clock), t["id"], f"R{i}")["id"] for i in range(5)]
    seen, cursor = [], None
    while True:
        page = client.get(f"{TOPICS_URL}/{t['id']}/replies",
                          params={"limit": 2, **({"cursor": cursor} if cursor else {})}).json()
        seen += [r["id"] for r in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == sorted(ids)


def test_only_the_author_deletes_public_content(client, other_client, admin, clock):
    set_name(client, "阿土伯")
    set_name(other_client, "路人甲")
    set_name(admin, "值班的人")
    t = post_topic(client, clock)
    r1 = post_reply(other_client, clock, t["id"], "別人的回覆")
    r2 = post_reply(client, clock, t["id"], "我的回覆")
    # not the author — not even a site admin (they hide, never delete)
    for c in (other_client, admin):
        r = c.delete(f"{TOPICS_URL}/{t['id']}")
        assert r.status_code == 403 and error(r) == "forbidden"
        assert c.delete(f"{API}/discussions/replies/{r2['id']}").status_code == 403
    assert client.delete(f"{API}/discussions/replies/{r1['id']}").status_code == 403  # the topic's author neither
    assert client.delete(f"{API}/discussions/replies/{r2['id']}").status_code == 204
    assert client.delete(f"{API}/discussions/replies/{r2['id']}").status_code == 404
    detail = client.get(f"{TOPICS_URL}/{t['id']}").json()
    assert detail["reply_count"] == 1 and detail["last_activity_at"] == r1["created_at"]
    assert other_client.delete(f"{API}/discussions/replies/{r1['id']}").status_code == 204
    detail = client.get(f"{TOPICS_URL}/{t['id']}").json()
    assert detail["reply_count"] == 0 and detail["last_activity_at"] == detail["created_at"]


def test_deleting_a_topic_removes_its_replies_reactions_and_reports(client, other_client, clock, engine):
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from forliosa import models as m

    set_name(client, "阿土伯")
    set_name(other_client, "路人甲")
    keep = post_topic(other_client, clock, title="留下來的")
    t = post_topic(client, clock, symbols=["2330"])
    r = post_reply(other_client, clock, t["id"])
    for target in (f"topic:{t['id']}", f"reply:{r['id']}", f"topic:{keep['id']}"):
        assert other_client.put(REACTIONS_URL, json={"target": target, "emoji": "🔥"}).status_code == 204
    assert other_client.post(f"{API}/discussions/reports",
                             json={"target": f"topic:{t['id']}", "reason": "spam"}).status_code == 204
    assert client.post(f"{API}/discussions/reports",
                       json={"target": f"reply:{r['id']}", "reason": "abuse"}).status_code == 204
    assert client.delete(f"{TOPICS_URL}/{t['id']}").status_code == 204
    assert client.get(f"{TOPICS_URL}/{t['id']}").status_code == 404
    assert client.get(f"{TOPICS_URL}/{t['id']}/replies").status_code == 404
    assert [x["id"] for x in topics(client)] == [keep["id"]]
    with Session(engine) as db:
        counts = {model.__tablename__: db.scalar(select(func.count()).select_from(model))
                  for model in (m.DiscussionTopic, m.DiscussionReply, m.DiscussionReaction, m.DiscussionReport,
                                m.DiscussionTopicSymbol)}
    assert counts == {"discussion_topics": 1, "discussion_replies": 0, "discussion_reactions": 1,
                      "discussion_reports": 0, "discussion_topic_symbols": 0}


# -- reactions --------------------------------------------------------------------------------------------------
def test_reactions_count_once_per_person_and_emoji(client, other_client, clock):
    set_name(client, "阿土伯")
    t = post_topic(client, clock)
    r = post_reply(client, clock, t["id"])
    topic_target, reply_target = f"topic:{t['id']}", f"reply:{r['id']}"
    for _ in range(2):  # repeating does not count twice
        resp = client.put(REACTIONS_URL, json={"target": topic_target, "emoji": "👍"})
        assert resp.status_code == 204 and resp.content == b""
    assert other_client.put(REACTIONS_URL, json={"target": topic_target, "emoji": "👍"}).status_code == 204
    assert other_client.put(REACTIONS_URL, json={"target": topic_target, "emoji": "👀"}).status_code == 204
    assert other_client.put(REACTIONS_URL, json={"target": reply_target, "emoji": "🎉"}).status_code == 204
    assert client.get(f"{TOPICS_URL}/{t['id']}").json()["reactions"] == [
        {"emoji": "👍", "count": 2, "mine": True}, {"emoji": "👀", "count": 1, "mine": False}]
    assert replies(other_client, t["id"])[0]["reactions"] == [{"emoji": "🎉", "count": 1, "mine": True}]
    anon = TestClient(client.app)
    assert anon.get(f"{TOPICS_URL}/{t['id']}").json()["reactions"] == [
        {"emoji": "👍", "count": 2, "mine": False}, {"emoji": "👀", "count": 1, "mine": False}]
    # take mine back; someone else's stays
    assert client.delete(REACTIONS_URL, params={"target": topic_target, "emoji": "👍"}).status_code == 204
    assert client.delete(REACTIONS_URL, params={"target": topic_target, "emoji": "👀"}).status_code == 204  # not mine
    assert client.get(f"{TOPICS_URL}/{t['id']}").json()["reactions"] == [
        {"emoji": "👍", "count": 1, "mine": False}, {"emoji": "👀", "count": 1, "mine": False}]
    # bad input
    assert client.put(REACTIONS_URL, json={"target": topic_target, "emoji": "💩"}).status_code == 422
    assert client.put(REACTIONS_URL, json={"target": f"chart_comment:{t['id']}", "emoji": "👍"}).status_code == 422
    assert client.put(REACTIONS_URL, json={"target": "topic:top_nope", "emoji": "👍"}).status_code == 404
    assert client.put(REACTIONS_URL, json={"target": "reply:rep_nope", "emoji": "👍"}).status_code == 404
    assert client.delete(REACTIONS_URL, params={"target": "topic:top_nope", "emoji": "👍"}).status_code == 404
    assert client.delete(REACTIONS_URL, params={"target": topic_target, "emoji": "💩"}).status_code == 422


# -- rate limits (counted from stored rows; the clock is injected) ----------------------------------------------
def rate_limited(r) -> int:
    assert r.status_code == 429 and error(r) == "rate_limited", r.text
    seconds = r.json()["error"]["retry_after_seconds"]
    assert r.headers["retry-after"] == str(seconds)
    return seconds


def test_two_public_posts_are_at_least_ten_seconds_apart(client, other_client, clock):
    set_name(client, "阿土伯")
    set_name(other_client, "路人甲")
    t = post_topic(client, clock)
    body = {"scope": "public", "title": "標題", "body": "內文"}
    assert rate_limited(client.post(TOPICS_URL, json=body)) == 10
    assert rate_limited(client.post(f"{TOPICS_URL}/{t['id']}/replies", json={"body": "回覆"})) == 10  # any public post
    clock.tick(seconds=4)
    assert rate_limited(client.post(TOPICS_URL, json=body)) == 6
    # other people are not held back, and my group posts are not either
    assert other_client.post(f"{TOPICS_URL}/{t['id']}/replies", json={"body": "回覆"}).status_code == 201
    g = make_group(client)
    group_body = {"scope": "group", "group_id": g["id"], "title": "群組", "body": "內文"}
    assert client.post(TOPICS_URL, json=group_body).status_code == 201
    assert client.post(TOPICS_URL, json=group_body).status_code == 201
    clock.tick(seconds=6)
    assert client.post(TOPICS_URL, json=body).status_code == 201  # a group post did not restart the gap


def test_public_topics_are_limited_to_five_a_day(client, clock):
    set_name(client, "阿土伯")
    made = [post_topic(client, clock, title=f"T{i}") for i in range(5)]
    first_at = clock.t - timedelta(seconds=GAP * 4)
    clock.tick(seconds=GAP)
    body = {"scope": "public", "title": "第六則", "body": "內文"}
    wait = rate_limited(client.post(TOPICS_URL, json=body))
    assert wait == int((first_at + timedelta(days=1) - clock.t).total_seconds()) == 86400 - GAP * 5
    # deleting a topic does not give the slot back
    assert client.delete(f"{TOPICS_URL}/{made[0]['id']}").status_code == 204
    assert rate_limited(client.post(TOPICS_URL, json=body)) == wait
    # replies have their own allowance
    assert client.post(f"{TOPICS_URL}/{made[1]['id']}/replies", json={"body": "回覆"}).status_code == 201
    clock.tick(seconds=wait - 1)
    assert rate_limited(client.post(TOPICS_URL, json=body)) == 1
    clock.tick(seconds=1)
    assert client.post(TOPICS_URL, json=body).status_code == 201
    assert rate_limited(client.post(TOPICS_URL, json=body)) == GAP  # the next slot frees when the second one ages out


def test_public_replies_are_limited_to_thirty_an_hour(client, clock):
    set_name(client, "阿土伯")
    t = post_topic(client, clock)
    for i in range(30):
        post_reply(client, clock, t["id"], f"回覆 {i}")
    clock.tick(seconds=GAP)
    url = f"{TOPICS_URL}/{t['id']}/replies"
    assert rate_limited(client.post(url, json={"body": "第 31 則"})) == 3600 - GAP * 30
    clock.tick(seconds=3600 - GAP * 30)
    assert client.post(url, json={"body": "第 31 則"}).status_code == 201


def test_group_limits_are_wider_and_have_no_gap(client, clock):
    g = make_group(client)
    body = {"scope": "group", "group_id": g["id"], "title": "群組主題", "body": "內文"}
    for _ in range(20):
        assert client.post(TOPICS_URL, json=body).status_code == 201  # no gap between group posts
    assert rate_limited(client.post(TOPICS_URL, json=body)) == 86400
    [t, *_] = topics(client, scope="group", group_id=g["id"])
    url = f"{TOPICS_URL}/{t['id']}/replies"
    for i in range(120):
        assert client.post(url, json={"body": f"回覆 {i}"}).status_code == 201
    assert rate_limited(client.post(url, json={"body": "第 121 則"})) == 3600
    clock.tick(hours=1)
    assert client.post(url, json={"body": "第 121 則"}).status_code == 201
    assert rate_limited(client.post(TOPICS_URL, json=body)) == 86400 - 3600
    # group posts do not use up the public allowance
    set_name(client, "阿土伯")
    assert client.post(TOPICS_URL, json={"scope": "public", "title": "公開", "body": "內文"}).status_code == 201


def test_limits_are_the_documented_ones():
    assert {k: (v.count, int(v.window.total_seconds())) for k, v in svc.RATE_LIMITS.items()} == {
        ("public", "topic"): (5, 86400), ("public", "reply"): (30, 3600),
        ("group", "topic"): (20, 86400), ("group", "reply"): (120, 3600)}
    assert timedelta(seconds=10) == svc.PUBLIC_POST_GAP and timedelta(days=7) == svc.PUBLIC_NAME_COOLDOWN


def test_old_post_log_rows_are_pruned(client, clock, engine):
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from forliosa.models import DiscussionPostLog

    set_name(client, "阿土伯")
    post_topic(client, clock)
    post_topic(client, clock)
    clock.tick(days=1, seconds=1)
    post_topic(client, clock)
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(DiscussionPostLog)) == 1


# -- read-only viewing and AI ---------------------------------------------------------------------------------------
def test_view_as_never_changes_who_discusses(client, other_client, clock):
    """Under X-Forliosa-View-As the reads answer as the signed-in viewer; writes stay refused (read_only)."""
    from tests.api.m5 import join, me_id

    g = make_group(client)
    join(client, other_client, g["id"])
    r = client.post(f"{API}/delegations", json={"viewer_user_id": me_id(other_client), "scope": "all"})
    assert r.status_code == 201, r.text
    header = {"X-Forliosa-View-As": r.json()["id"]}
    set_name(client, "阿土伯")
    set_name(other_client, "路人甲")
    mine = post_topic(other_client, clock, title="看的人發的")
    theirs = post_topic(client, clock, title="被看的人發的")
    listed = other_client.get(TOPICS_URL, params={"mine": "true"}, headers=header).json()["items"]
    assert [t["id"] for t in listed] == [mine["id"]]  # the viewer's own, not the owner's
    detail = other_client.get(f"{TOPICS_URL}/{theirs['id']}", headers=header).json()
    assert detail["mine"] is False and detail["author"] == {"name": "阿土伯", "is_you": False}
    assert other_client.get(f"{TOPICS_URL}/{theirs['id']}/replies", headers=header).status_code == 200
    assert other_client.get(f"{API}/users/me", headers=header).json()["public_name"] == "路人甲"
    clock.tick(seconds=GAP)
    r = other_client.post(f"{TOPICS_URL}/{theirs['id']}/replies", json={"body": "回覆"}, headers=header)
    assert r.status_code == 403 and error(r) == "read_only"
    r = other_client.put(NAME_URL, json={"public_name": "換名字"}, headers=header)
    assert r.status_code == 403 and error(r) == "read_only"
    r = other_client.get(f"{API}/admin/discussions/reports", headers=header)
    assert r.status_code == 403 and error(r) == "view_as_not_allowed"


def test_ai_tools_do_not_read_discussions():
    from pathlib import Path

    import forliosa.ai as ai
    from forliosa.ai.tools import TOOLS

    assert not [t.name for t in TOOLS if "discuss" in t.name.lower() or "topic" in t.name.lower()]
    for path in Path(ai.__file__).parent.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "Discussion" not in source and "services.discussions" not in source, path.name
        assert "services import discussions" not in source, path.name
