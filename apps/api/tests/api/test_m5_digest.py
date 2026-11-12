"""M5 weekly AI digest: facts from the sharing projection (stored by user, filtered on read), anonymous model input,
Message Batches with a fallback to normal calls, usage charged to nobody, digest comments and pushes. The Messages and
Batches APIs are faked behind the real SDK (no network)."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta

import anthropic
import httpx2
import pytest
from sqlalchemy import select

from forliosa.ai.keypool import KeyPool
from forliosa.db import session_factory
from forliosa.models import AiUsage, GroupComment, GroupDigest
from forliosa.services import digests, notifications
from forliosa.timeutil import TAIPEI, now_utc, today_taipei, tw_trading_days
from forliosa.worker import weekend_evening
from tests.api.m5 import (
    API,
    SHARE_ALL,
    SHARE_NONE,
    account,
    join,
    login,
    make_group,
    me_id,
    set_share,
    trade,
    trading_day,
)
from tests.api.push_fake import WEBHOOK, PushFake

SUMMARY = "本週群組整體小幅上漲，多數成員和大盤表現接近，共同持股集中在半導體。"


class FakeClaude:
    """Messages + Message Batches endpoints of the real SDK, scripted."""

    def __init__(self, summary: str = SUMMARY, batches: bool = True, item: str = "succeeded", ended: bool = True):
        self.summary, self.batches_ok, self.item, self.ended = summary, batches, item, ended
        self.requests: list[tuple[str, str, dict | None]] = []
        self.batches: dict[str, list[dict]] = {}

    def message(self, model: str) -> dict:
        return {"id": "msg_fake", "type": "message", "role": "assistant", "model": model,
                "content": [{"type": "text", "text": self.summary}], "stop_reason": "end_turn",
                "stop_sequence": None, "usage": {"input_tokens": 400, "output_tokens": 80,
                                                 "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}

    def batch(self, bid: str) -> dict:
        n = len(self.batches[bid])
        ended = self.ended
        return {"id": bid, "type": "message_batch", "processing_status": "ended" if ended else "in_progress",
                "request_counts": {"processing": 0 if ended else n, "succeeded": n if ended else 0, "errored": 0,
                                   "canceled": 0, "expired": 0},
                "created_at": "2026-11-14T12:00:00Z", "expires_at": "2026-11-15T12:00:00Z",
                "ended_at": "2026-11-14T12:05:00Z" if ended else None, "archived_at": None,
                "cancel_initiated_at": None,
                "results_url": f"https://api.anthropic.com/v1/messages/batches/{bid}/results" if ended else None}

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        self.requests.append((request.method, path, body))
        if path == "/v1/messages/batches" and request.method == "POST":
            if not self.batches_ok:
                return httpx2.Response(404, json={"type": "error", "error": {"type": "not_found_error",
                                                                              "message": "Not found"}})
            bid = f"msgbatch_{len(self.batches) + 1:02d}"
            self.batches[bid] = body["requests"]
            return httpx2.Response(200, json=self.batch(bid))
        if m := re.fullmatch(r"/v1/messages/batches/([^/]+)/results", path):
            lines = []
            for req in self.batches[m.group(1)]:
                if self.item == "succeeded":
                    result = {"type": "succeeded", "message": self.message(req["params"]["model"])}
                elif self.item == "errored":
                    result = {"type": "errored", "error": {"type": "error", "error": {"type": "api_error",
                                                                                      "message": "boom"}}}
                else:
                    result = {"type": self.item}
                lines.append(json.dumps({"custom_id": req["custom_id"], "result": result}))
            return httpx2.Response(200, content="\n".join(lines).encode(),
                                   headers={"content-type": "application/binary"})
        if m := re.fullmatch(r"/v1/messages/batches/([^/]+)", path):
            return httpx2.Response(200, json=self.batch(m.group(1)))
        if path == "/v1/messages" and request.method == "POST":
            return httpx2.Response(200, json=self.message(body["model"]))
        return httpx2.Response(404, json={"type": "error", "error": {"type": "not_found_error", "message": "?"}})

    def client(self, key: str) -> anthropic.Anthropic:
        return anthropic.Anthropic(api_key=key, max_retries=0, http_client=anthropic.DefaultHttpxClient(
            transport=httpx2.MockTransport(self.handler)))

    def pool(self) -> KeyPool:
        return KeyPool.from_keys([(2, "sk-test-digest")], client_factory=self.client, sleep=lambda _s: None)

    @property
    def prompts(self) -> list[str]:
        out = []
        for method, path, body in self.requests:
            if method == "POST" and path == "/v1/messages/batches":
                out += [r["params"]["messages"][0]["content"] for r in body["requests"]]
            elif method == "POST" and path == "/v1/messages":
                out.append(body["messages"][0]["content"])
        return out


def last_saturday() -> date:
    """The latest Saturday on or before today whose Monday–Friday had a Taiwan trading day."""
    d = today_taipei()
    d -= timedelta(days=(d.weekday() - 5) % 7)
    while not tw_trading_days(d - timedelta(days=5), d - timedelta(days=1)):
        d -= timedelta(days=7)
    return d


def at_saturday_evening(sat: date) -> datetime:
    return datetime.combine(sat, time(20, 0), TAIPEI)


@pytest.fixture()
def family(app, client):
    """Owner 示範使用者 (returns + holdings), 小明 (everything, pushes), 小華 (returns + trades)."""
    g = make_group(client)
    b = login(app, "b@x.tw", "小明")
    c = login(app, "c@x.tw", "小華")
    join(client, b, g["id"], SHARE_ALL)
    join(client, c, g["id"], {**SHARE_NONE, "returns": True, "trades": True})
    set_share(client, g["id"], returns=True, holdings=True)
    sat = last_saturday()
    in_week = tw_trading_days(sat - timedelta(days=5), sat - timedelta(days=1))[0]
    before = trading_day(40)
    a_acc, b_acc, c_acc = account(client), account(b), account(c)
    trade(client, a_acc["id"], "2330", "buy", before, 1000, 500)
    trade(b, b_acc["id"], "2330", "buy", before, 1000, 500)
    trade(b, b_acc["id"], "2317", "buy", in_week, 1000, 100)
    trade(c, c_acc["id"], "2317", "buy", before, 1000, 100)
    trade(c, c_acc["id"], "2317", "buy", in_week, 1000, 100)
    trade(client, a_acc["id"], "2330", "buy", in_week, 100, 500)  # the owner does not share trades
    return {"g": g, "a": client, "b": b, "c": c, "sat": sat,
            "ids": {"a": me_id(client), "b": me_id(b), "c": me_id(c)}}


def create(market, sat: date) -> list[GroupDigest]:
    with session_factory()() as db:
        out = digests.create_week(db, market, today=sat, now=at_saturday_evening(sat))
        for d in out:
            db.expunge(d)
        return out


def digest_row(did: str) -> GroupDigest:
    with session_factory()() as db:
        d = db.get(GroupDigest, did)
        db.expunge(d)
        return d


def run_ai(fake: FakeClaude, sat: date, pool: KeyPool | None = None) -> KeyPool:
    pool = pool or fake.pool()
    now = at_saturday_evening(sat)
    with session_factory()() as db:
        digests.submit(db, pool=pool, now=now)
        digests.poll(db, pool=pool, now=now + timedelta(minutes=5))
    return pool


def test_facts_come_from_the_projection(family, market):
    [d] = create(market, family["sat"])
    ids = family["ids"]
    assert d.status == "pending" and d.week_start == family["sat"] - timedelta(days=5)
    assert d.week_end == family["sat"] - timedelta(days=1)
    facts = d.facts
    assert [r["user_id"] for r in facts["returns"]] == [ids["a"], ids["b"], ids["c"]]
    assert all(r["week_return_pct"] is None or abs(r["week_return_pct"]) < 1 for r in facts["returns"])
    assert sorted(h["user_id"] for h in facts["holdings"]) == sorted([ids["a"], ids["b"]])
    assert {t["user_id"]: t["count"] for t in facts["trades"]} == {ids["b"]: 1, ids["c"]: 1}
    assert [b["symbol"] for b in facts["benchmarks"]] == ["^TAIEXTR", "0050.TW"]
    blob = json.dumps(facts, ensure_ascii=False)
    for secret in ("示範使用者", "小明", "小華", "永豐", "quantity", "price"):
        assert secret not in blob
    assert create(market, family["sat"]) == []  # one per group and week


def test_skips_weeks_without_trading_and_small_groups(app, client, market):
    g = make_group(client)
    b = login(app, "b@x.tw", "小明")
    join(client, b, g["id"], {**SHARE_NONE, "holdings": True})  # only one member shares returns
    assert create(market, last_saturday()) == []
    join(client, login(app, "c@x.tw", "小華"), g["id"])  # default share: returns on → two now
    assert create(market, date(2026, 2, 21)) == []  # 2026-02-16..20: Lunar New Year, no trading day
    assert len(create(market, last_saturday())) == 1


def test_batch_summary_with_anonymous_input_and_free_usage(family, market):
    [d] = create(market, family["sat"])
    fake = FakeClaude()
    pool = run_ai(fake, family["sat"])
    [prompt] = fake.prompts
    for name in ("示範使用者", "小明", "小華", "家族投資", *family["ids"].values()):
        assert name not in prompt
    assert "成員 A" in prompt and "成員 C" in prompt and "成員 D" not in prompt
    assert "台積電（2 人）" in prompt and "本週買賣筆數（只算有分享交易動態的成員）：2" in prompt
    assert [p for m, p, _ in fake.requests if m == "POST"] == ["/v1/messages/batches"]  # no normal call
    req = fake.batches["msgbatch_01"][0]
    assert req["custom_id"] == d.id and "不給任何買進、賣出" in req["params"]["system"]
    row = digest_row(d.id)
    assert row.status == "ready" and row.summary == SUMMARY and row.batch_id == "2:msgbatch_01"
    with session_factory()() as db:
        [u] = db.scalars(select(AiUsage)).all()
        assert u.feature == "group_digest" and u.user_id is None and u.thread_id == d.id and u.key_slot == 2
        assert float(u.cost_usd) == pytest.approx((400 * 0.10 + 80 * 0.50) / 1e6 / 2)
    assert not pool.slots[0].disabled
    usage = family["b"].get(f"{API}/ai/usage").json()
    assert usage["tokens_month"] == 0


def test_falls_back_to_a_normal_call_without_batches(family, market):
    [d] = create(market, family["sat"])
    fake = FakeClaude(batches=False)
    pool = run_ai(fake, family["sat"])
    assert [p for m, p, _ in fake.requests if m == "POST"] == ["/v1/messages/batches", "/v1/messages"]
    assert digest_row(d.id).status == "ready"
    assert not pool.slots[0].disabled  # a refused batches endpoint does not disable the key


@pytest.mark.parametrize("item", ["errored", "expired"])
def test_failed_batch_items_get_one_normal_call(family, market, item):
    [d] = create(market, family["sat"])
    fake = FakeClaude(item=item)
    run_ai(fake, family["sat"])
    assert digest_row(d.id).status == "ready"
    assert [p for m, p, _ in fake.requests if m == "POST"] == ["/v1/messages/batches", "/v1/messages"]


def test_unfinished_batch_waits(family, market):
    [d] = create(market, family["sat"])
    fake = FakeClaude(ended=False)
    run_ai(fake, family["sat"])
    assert digest_row(d.id).status == "pending"


def test_a_summary_naming_members_or_targets_is_dropped(family, market):
    [d] = create(market, family["sat"])
    run_ai(FakeClaude(summary="成員 A 本週表現最好，目標價看 1200 元。"), family["sat"])
    row = digest_row(d.id)
    assert row.status == "failed" and row.summary == "" and row.error == "rejected"


def test_no_keys_marks_failed_but_keeps_facts(family, market):
    [d] = create(market, family["sat"])
    with session_factory()() as db:
        digests.submit(db, pool=KeyPool([]), now=at_saturday_evening(family["sat"]))
    row = digest_row(d.id)
    assert row.status == "failed" and row.error == "ai_unavailable" and row.facts["returns"]


def test_reading_filters_by_current_settings_and_paginates(family, market):
    g, a, b, c = family["g"], family["a"], family["b"], family["c"]
    sat = family["sat"]
    [old] = create(market, sat - timedelta(days=7)) or [None]
    with session_factory()() as db:  # the older week's model call failed
        digests.submit(db, pool=KeyPool([]), now=at_saturday_evening(sat))
    [d] = create(market, sat)
    run_ai(FakeClaude(), sat)
    r = b.get(f"{API}/groups/{g['id']}/digests")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items[0]["id"] == d.id and items[0]["status"] == "ready" and items[0]["summary"] == SUMMARY
    facts = items[0]["facts"]
    assert [x["display_name"] for x in facts["returns"]] == ["示範使用者", "小明", "小華"]
    assert facts["common_holdings"] == [{"symbol": "2330.TW", "name": "台積電", "holder_count": 2}]
    assert facts["trades_count"] == 2
    assert items[0]["disclaimer"].startswith("AI 分析僅供參考")
    if old is not None:
        assert items[1]["id"] == old.id and items[1]["status"] == "failed" and items[1]["summary"] == ""
        assert items[1]["comment_count"] == 0 and items[1]["facts"]["returns"]
        page = b.get(f"{API}/groups/{g['id']}/digests?limit=1").json()
        assert len(page["items"]) == 1 and page["next_cursor"]
        nxt = b.get(f"{API}/groups/{g['id']}/digests?limit=1&cursor={page['next_cursor']}").json()
        assert nxt["items"][0]["id"] == old.id and nxt["next_cursor"] is None
        # a failed digest is not a comment target
        r = b.post(f"{API}/groups/{g['id']}/comments", json={"target": f"digest:{old.id}", "body": "?"})
        assert r.status_code == 404

    r = b.post(f"{API}/groups/{g['id']}/comments", json={"target": f"digest:{d.id}", "body": "不錯"})
    assert r.status_code == 201, r.text
    assert b.put(f"{API}/groups/{g['id']}/reactions", json={"target": f"digest:{d.id}", "emoji": "🎉"}).status_code \
        == 200
    top = c.get(f"{API}/groups/{g['id']}/digests").json()["items"][0]
    assert top["comment_count"] == 1 and top["reactions"] == [{"emoji": "🎉", "count": 1, "mine": False}]

    set_share(c, g["id"])  # 小華 turns everything off: gone from returns and from the trade count
    facts = a.get(f"{API}/groups/{g['id']}/digests").json()["items"][0]["facts"]
    assert [x["display_name"] for x in facts["returns"]] == ["示範使用者", "小明"] and facts["trades_count"] == 1
    me = family["ids"]["b"]
    assert b.delete(f"{API}/groups/{g['id']}/members/{me}").status_code == 204  # 小明 leaves
    facts = a.get(f"{API}/groups/{g['id']}/digests").json()["items"][0]["facts"]
    assert [x["display_name"] for x in facts["returns"]] == ["示範使用者"]
    assert facts["common_holdings"] == [] and facts["trades_count"] == 0
    assert b.get(f"{API}/groups/{g['id']}/digests").status_code == 404


def test_digest_push_only_shows_members_who_push(family, market):
    g, a = family["g"], family["a"]
    fake = PushFake().install()
    assert a.put(f"{API}/groups/{g['id']}/channels/discord", json={"webhook_url": WEBHOOK}).status_code == 200
    assert len(create(market, family["sat"])) == 1
    run_ai(FakeClaude(), family["sat"])
    with session_factory()() as db:
        notifications.send_due(db, market, now=now_utc())
    text = fake.discord[-1].body["content"]
    assert "週報" in text and "小明" in text
    assert "示範使用者" not in text and "小華" not in text
    assert SUMMARY not in text  # 示範使用者 and 小華 contributed but do not push
    assert "台積電" not in text  # only one pushing member shares holdings: nothing is common
    assert "本週交易動態：1 筆" in text


def test_digest_push_includes_the_summary_when_everyone_pushes(family, market):
    g, a, c = family["g"], family["a"], family["c"]
    fake = PushFake().install()
    assert a.put(f"{API}/groups/{g['id']}/channels/discord", json={"webhook_url": WEBHOOK}).status_code == 200
    set_share(a, g["id"], returns=True, holdings=True, push=True)
    set_share(c, g["id"], returns=True, trades=True, push=True)
    create(market, family["sat"])
    run_ai(FakeClaude(), family["sat"])
    with session_factory()() as db:
        notifications.send_due(db, market, now=now_utc())
    text = fake.discord[-1].body["content"]
    assert SUMMARY in text and "台積電（2 人）" in text and "AI 分析僅供參考" in text
    assert all(n in text for n in ("示範使用者", "小明", "小華"))


def test_retention(family, market):
    g, b = family["g"], family["b"]
    [d] = create(market, family["sat"])
    run_ai(FakeClaude(), family["sat"])
    b.post(f"{API}/groups/{g['id']}/comments", json={"target": f"digest:{d.id}", "body": "讚"})
    with session_factory()() as db:
        assert digests.purge_old(db, today=d.week_start + timedelta(weeks=26)) == 0
        assert digests.purge_old(db, today=d.week_start + timedelta(weeks=26, days=1)) == 1
        assert db.scalars(select(GroupComment)).all() == []


def test_weekend_evening_schedule():
    due = weekend_evening(time(20, 0))
    sat = date(2026, 11, 14)
    at = lambda d, h, m=0: datetime.combine(d, time(h, m), TAIPEI)  # noqa: E731
    assert not due(at(sat, 19, 59), None)
    assert due(at(sat, 20, 0), None)
    assert not due(at(sat, 21), at(sat, 20, 0))
    assert due(at(sat + timedelta(days=1), 9), None)  # catch-up on Sunday
    assert not due(at(sat + timedelta(days=1), 9), at(sat, 20, 1))
    assert not due(at(sat + timedelta(days=2), 9), None)  # Monday: too late
    assert not due(at(sat - timedelta(days=1), 21), None)
