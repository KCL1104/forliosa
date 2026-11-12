"""Workspace-aware routing of chat turns: sticky key slot per thread, headroom-based choice for new threads,
budget / spend-limit / 401 moves with a plain-text recap, the short sticky wait, no move inside a turn, refused
server tools, rejected thinking blocks, the admin status endpoint and key-safe logs and responses."""

from __future__ import annotations

import json
import logging
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.ai.keypool import KeyPool, set_key_pool
from forliosa.ai.tools import excluded_tools
from forliosa.models import AiMessage, AiThread, AiUsage
from tests.ai.conftest import API, buy, chat, make_account
from tests.ai.fake_anthropic import (
    rate_limit_headers,
    search_citation,
    server_tool_use,
    text,
    thinking,
    tool_use,
    web_search_result,
)

SLOT_KEYS = ["sk-test-slot-one", "sk-test-slot-two", "sk-test-slot-three"]
REPLAY_ONLY = ("thinking", "server_tool_use", "web_search_tool_result", "encrypted_content", "encrypted_index",
               "signature", "citations")


@pytest.fixture()
def slots(fake):
    """Three slots (one per workspace); ``slots.sleeps`` records the waits."""
    sleeps: list[float] = []

    def build(budgets=None):
        p = KeyPool.from_keys(SLOT_KEYS, client_factory=fake.client, sleep=sleeps.append, budgets=budgets or {})
        p.sleeps = sleeps  # type: ignore[attr-defined]
        set_key_pool(p)
        return p

    yield build
    set_key_pool(None)


def key_of(n: int) -> str:
    return SLOT_KEYS[n - 1]


def thread_row(engine, thread_id: str) -> AiThread:
    with Session(engine) as db:
        return db.get(AiThread, thread_id)


def add_cost(engine, slot: int, usd: str) -> None:
    from forliosa.timeutil import now_utc

    with Session(engine) as db:
        db.add(AiUsage(user_id=None, thread_id=None, feature="why", model="claude-haiku-5-5", key_slot=slot,
                       cost_usd=Decimal(usd), created_at=now_utc()))
        db.commit()


def first_turn_with_search(fake) -> None:
    fake.reply(thinking("sig-a"), server_tool_use("srvtoolu_1", "web_search", {"query": "台積電 新聞"}),
               web_search_result("srvtoolu_1", [{"url": "https://www.cna.com.tw/a", "title": "中央社",
                                                 "encrypted_content": "ENC-123"}]),
               text("台積電今天上漲，"),
               text("主因是法說會上調展望。", [search_citation("https://www.cna.com.tw/a", "中央社", "上調全年展望")]),
               usage={"server_tool_use": {"web_search_requests": 1}})


def test_thread_is_sticky_new_threads_take_the_most_headroom(client, slots, fake, engine):
    slots()
    add_cost(engine, 2, "0.50")
    add_cost(engine, 3, "0.90")
    fake.reply(text("一"), headers=rate_limit_headers(10, 100))  # slot 1 answers and reports 10% tokens left
    t1 = chat(client, "第一段")[1][0][1]["id"]
    assert fake.keys_used == [key_of(1)] and thread_row(engine, t1).key_slot == 1
    # a new thread: slot 1 has the least headroom now, slot 2 is cheaper than slot 3
    fake.reply(text("二"))
    t2 = chat(client, "第二段")[1][0][1]["id"]
    assert fake.keys_used[-1] == key_of(2) and thread_row(engine, t2).key_slot == 2
    # follow-ups stay on their thread's slot, whatever the headroom
    fake.reply(text("三")).reply(text("四"))
    chat(client, "繼續一", thread_id=t1)
    chat(client, "繼續二", thread_id=t2)
    assert fake.keys_used[-2:] == [key_of(1), key_of(2)]
    second = fake.requests[2]["body"]["messages"]
    assert [m["role"] for m in second] == ["user", "system", "assistant", "user", "system"]  # no recap
    with Session(engine) as db:
        slots_used = [u.key_slot for u in db.scalars(select(AiUsage).where(AiUsage.feature == "chat")
                                                     .order_by(AiUsage.id))]
    assert slots_used == [1, 2, 1, 2]


def test_budget_exhaustion_moves_the_thread_with_a_recap(client, slots, fake, engine):
    slots(budgets={1: Decimal("0.001")})
    first_turn_with_search(fake)
    fake.requests.clear()
    tid = chat(client, "台積電今天為什麼漲？", page={"route": "/stock/2330.TW", "symbol": "2330.TW"})[1][0][1]["id"]
    assert fake.keys_used == [key_of(1)]
    add_cost(engine, 1, "0.002")  # slot 1 is over its monthly budget now
    fake.reply(text("0050 今天持平。"))
    _status, events = chat(client, "那 0050 呢？", thread_id=tid)
    assert [n for n, _ in events][-1] == "done" and "error" not in [n for n, _ in events]
    assert fake.keys_used[-1] == key_of(2)
    messages = fake.requests[-1]["body"]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "system"]
    assert messages[0]["content"] == [{"type": "text", "text": "台積電今天為什麼漲？"}]
    recap_answer = messages[1]["content"][0]["text"]
    assert recap_answer.startswith("台積電今天上漲，主因是法說會上調展望。")
    assert "中央社：https://www.cna.com.tw/a" in recap_answer  # citations survive as plain links
    assert "先前的對話只保留文字" in messages[3]["content"]
    dumped = json.dumps(messages, ensure_ascii=False)
    assert not any(f'"{k}"' in dumped for k in REPLAY_ONLY) and "ENC-123" not in dumped and "sig-a" not in dumped
    row = thread_row(engine, tid)
    assert row.key_slot == 2 and row.context_from_seq > 0
    # the next turn replays the recap and the new turn unchanged on slot 2 (a stable prefix for its cache)
    fake.reply(text("好"))
    chat(client, "謝謝", thread_id=tid)
    replay = fake.requests[-1]["body"]["messages"]
    assert fake.keys_used[-1] == key_of(2) and replay[:5] == [*messages, {"role": "assistant", "content": [
        {"type": "text", "text": "0050 今天持平。"}]}]
    # the history view is unchanged: recap rows are hidden
    detail = client.get(f"{API}/ai/threads/{tid}").json()
    assert [(m["role"], m["text"]) for m in detail["messages"]] == [
        ("user", "台積電今天為什麼漲？"), ("ai", "台積電今天上漲，主因是法說會上調展望。"), ("user", "那 0050 呢？"),
        ("ai", "0050 今天持平。"), ("user", "謝謝"), ("ai", "好")]


def test_rate_limited_slot_fails_over_with_recap_stripping_replay_blocks(client, slots, fake, engine):
    pool = slots()
    first_turn_with_search(fake)
    tid = chat(client, "台積電今天為什麼漲？")[1][0][1]["id"]
    fake.error(429, "rate_limit_error", headers={"retry-after": "120"}).reply(text("好的"))
    _status, events = chat(client, "再說一次", thread_id=tid)
    assert "error" not in [n for n, _ in events]
    failed, moved = fake.requests[-2], fake.requests[-1]
    # the attempt on the pinned slot still carried the original blocks (same workspace) ...
    assert failed["key"] == key_of(1) and "ENC-123" in json.dumps(failed["body"]["messages"])
    # ... the retry in another workspace only plain text
    assert moved["key"] != key_of(1)
    dumped = json.dumps(moved["body"]["messages"], ensure_ascii=False)
    assert not any(f'"{k}"' in dumped for k in REPLAY_ONLY)
    assert pool.state(pool.get(1)) == "cooling" and pool.sleeps == []  # 120 s is longer than the sticky wait
    assert thread_row(engine, tid).key_slot == int(moved["key"] == key_of(3)) + 2


def test_short_retry_after_waits_on_the_pinned_slot(client, slots, fake, engine):
    pool = slots()
    fake.reply(text("一"))
    tid = chat(client, "第一題")[1][0][1]["id"]
    fake.error(429, "rate_limit_error", headers={"retry-after": "2"}).reply(text("二"))
    chat(client, "第二題", thread_id=tid)
    assert fake.keys_used[-2:] == [key_of(1), key_of(1)] and pool.sleeps == [pytest.approx(2.0, abs=0.1)]
    assert thread_row(engine, tid).context_from_seq == 0  # no recap


def test_401_disables_the_slot_and_moves_the_thread(client, slots, fake, engine, caplog):
    pool = slots()
    fake.reply(text("一"))
    tid = chat(client, "第一題")[1][0][1]["id"]
    fake.error(401, "authentication_error", "invalid x-api-key").reply(text("二"))
    with caplog.at_level(logging.INFO):
        _status, events = chat(client, "第二題", thread_id=tid)
    assert "error" not in [n for n, _ in events]
    assert pool.get(1).disabled and thread_row(engine, tid).key_slot in (2, 3)
    assert [m["role"] for m in fake.requests[-1]["body"]["messages"]] == ["user", "assistant", "user", "system"]
    for _ in range(3):
        fake.reply(text("x"))
        chat(client, "新的一段")
    assert key_of(1) not in fake.keys_used[-3:]
    assert "#1" in caplog.text and not any(k in caplog.text for k in SLOT_KEYS)


def test_no_move_inside_a_turn(client, slots, fake, ai_env):
    acc = make_account(client)
    buy(client, acc, "2330", 1000, 600)
    slots()
    fake.reply(tool_use("toolu_1", "get_holdings", {}), stop_reason="tool_use")
    fake.error(529, "overloaded_error").error(529, "overloaded_error")
    _status, events = chat(client, "持股？")
    assert [d["code"] for n, d in events if n == "error"] == ["ai_busy"]
    assert fake.keys_used == [key_of(1)] * 3  # the turn's tool round belongs to slot 1: one retry there, no move


def test_all_slots_over_budget_is_503(client, slots, fake, engine):
    slots(budgets={1: Decimal(1), 2: Decimal(1), 3: Decimal(1)})
    for n in (1, 2, 3):
        add_cost(engine, n, "1.5")
    r = client.post(f"{API}/ai/chat", json={"message": "hi"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_unavailable"
    assert client.get(f"{API}/ai/usage").json()["available"] is False and fake.requests == []


def test_admin_keys_status_without_secrets(client, slots, fake, engine):
    slots(budgets={2: Decimal("20")})
    fake.reply(text("一"), headers={**rate_limit_headers(90, 100), "anthropic-workspace-id": "wrkspc_a"})
    chat(client, "第一題")
    body = client.get(f"{API}/ai/admin/keys").json()
    assert not any(k in json.dumps(body) for k in SLOT_KEYS)
    by_slot = {s["slot"]: s for s in body["slots"]}
    assert sorted(by_slot) == [1, 2, 3]
    one = by_slot[1]
    assert one["configured"] and one["state"] == "ok" and one["workspace_id"] == "wrkspc_a" and one["threads"] == 1
    assert one["month_calls"] == 1 and one["month_cost_usd"] >= 0 and one["headroom"] == pytest.approx(0.9)
    assert one["rate_limits"] == {"tokens": {"remaining": 90, "limit": 100}}
    assert by_slot[2]["monthly_budget_usd"] == 20.0 and by_slot[2]["budget_remaining_usd"] == 20.0
    assert body["server_tools"] == ["web_search_20260318", "web_fetch_20260318"] and body["excluded_tools"] == []


def test_admin_keys_hidden_in_prod_unless_listed(engine, market, monkeypatch):
    from fastapi.testclient import TestClient

    from forliosa.api.app import create_app
    from forliosa.config import get_settings
    from tests.api.test_deploy_config import APP_ORIGIN, SECRET, _login

    for k, v in {"FORLIOSA_ENV": "prod", "SESSION_SECRET": SECRET, "CORS_ORIGINS": APP_ORIGIN,
                 "FRONTEND_URL": APP_ORIGIN}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    try:
        _, token = _login()
        c = TestClient(create_app(), base_url="https://api.example.com")
        headers = {"Origin": APP_ORIGIN, "Cookie": f"forliosa_session={token}"}
        r = c.get(f"{API}/ai/admin/keys", headers=headers)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
        monkeypatch.setenv("AI_ADMIN_EMAILS", "someone@example.com, Prod@Example.com")
        get_settings.cache_clear()
        assert c.get(f"{API}/ai/admin/keys", headers=headers).status_code == 200
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


SANDBOX_400 = ("Requests sent from a sandbox with restricted network access are not allowed to use tool "
               "web_fetch_20260318")


def test_refused_server_tool_is_dropped_and_remembered(client, pool, fake, caplog):
    fake.error(400, "invalid_request_error", SANDBOX_400).reply(text("好"))
    with caplog.at_level(logging.WARNING):
        _status, events = chat(client, "台積電今天有什麼新聞？")
    assert "error" not in [n for n, _ in events]
    first, retry = (r["body"] for r in fake.requests)
    assert [t["name"] for t in first["tools"]][-2:] == ["web_search", "web_fetch"]
    assert "web_fetch" not in [t["name"] for t in retry["tools"]] and retry["tools"][-1]["name"] == "web_search"
    assert fake.keys_used[0] == fake.keys_used[1]  # same slot: not a key problem
    # remembered for the process: the next turn never sends it, and the warning is logged once
    fake.reply(text("再一次"))
    chat(client, "那聯發科呢？")
    assert "web_fetch" not in [t["name"] for t in fake.requests[-1]["body"]["tools"]]
    assert caplog.text.count("web_fetch_20260318 refused") == 1
    assert [t["type"] for t in excluded_tools()] == ["web_fetch_20260318"]
    body = client.get(f"{API}/ai/admin/keys").json()
    assert body["excluded_tools"][0]["reason"] == SANDBOX_400 and body["server_tools"] == ["web_search_20260318"]


def test_refused_web_search_by_name(client, pool, fake):
    fake.error(400, "invalid_request_error", "web search is not enabled for this organization").reply(text("好"))
    chat(client, "今天美股如何？")
    assert [t["name"] for t in fake.requests[1]["body"]["tools"]][-1] == "web_fetch"
    assert [t["type"] for t in excluded_tools()] == ["web_search_20260318"]


def test_other_400s_do_not_drop_tools(client, pool, fake):
    fake.error(400, "invalid_request_error", "tools.15.web_fetch_20260318.max_uses: must be at least 1")
    _status, events = chat(client, "今天美股如何？")
    assert [d["code"] for n, d in events if n == "error"] == ["ai_error"] and excluded_tools() == []


def test_rejected_thinking_blocks_continue_from_a_recap(client, pool, fake, engine):
    fake.reply(thinking("sig-1"), text("一"))
    tid = chat(client, "第一題")[1][0][1]["id"]
    fake.error(400, "invalid_request_error", "messages.1.content.0: Invalid `signature` in `thinking` block. The "
                                             "block is bound to a different conversation.").reply(text("二"))
    _status, events = chat(client, "第二題", thread_id=tid)
    assert "error" not in [n for n, _ in events]
    retry = fake.requests[-1]
    assert retry["key"] == fake.requests[-2]["key"]  # same slot
    assert [m["role"] for m in retry["body"]["messages"]] == ["user", "assistant", "user", "system"]
    assert "sig-1" not in json.dumps(retry["body"]["messages"])
    assert thread_row(engine, tid).context_from_seq > 0
    with Session(engine) as db:
        assert db.scalar(select(AiMessage).where(AiMessage.thread_id == tid, AiMessage.meta["recap"].as_boolean()
                                                 .is_(True)).limit(1)) is not None
