"""POST /ai/chat: SSE event shapes, the tool loop, request shape (caching, tools, page context), append-only
replay, refusals, pause_turn, max_tokens, key failover inside a stream, quotas and thread endpoints."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.ai.keypool import KeyPool, set_key_pool
from forliosa.models import AiMessage, AiThread, AiUsage
from tests.ai.conftest import API, KEYS, buy, chat, make_account
from tests.ai.fake_anthropic import (
    search_citation,
    server_tool_use,
    text,
    thinking,
    tool_use,
    web_search_result,
)

EVENT_KEYS = {
    "thread": {"id", "title", "created"},
    "text": {"delta"},
    "tool": {"id", "name", "status", "label"},
    "citation": {"url", "title", "cited_text"},
    "draft": {"id", "status", "input", "instrument", "preview", "notes", "account", "transaction_id", "created_at"},
    "error": {"code", "message"},
    "done": {"thread_id", "turn_id", "model", "stop_reason", "usage"},
}
USAGE_KEYS = {"input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
              "web_search_requests", "web_fetch_requests"}


def check_shapes(events):
    assert events[0][0] == "thread"
    assert events[-1][0] == "done"
    for name, data in events:
        assert set(data) == EVENT_KEYS[name], (name, data)
    done = events[-1][1]
    assert set(done["usage"]) == USAGE_KEYS
    assert "key_index" not in json.dumps(events)


def names(events):
    return [n for n, _ in events]


def text_of(events):
    return "".join(d["delta"] for n, d in events if n == "text")


def test_tool_loop_streams_events_and_builds_cached_request(client, pool, fake):
    acc = make_account(client)
    buy(client, acc, "2330", 1000, 600)
    fake.reply(thinking("sig-1"), text("我查一下。"), tool_use("toolu_1", "get_holdings", {}), stop_reason="tool_use",
               usage={"input_tokens": 50, "cache_creation_input_tokens": 3000, "output_tokens": 40})
    fake.reply(text("你持有台積電 1 張。\n僅供參考，非投資建議。"),
               usage={"input_tokens": 80, "cache_read_input_tokens": 3000, "output_tokens": 30})
    status, events = chat(client, "我有哪些持股？", page={"route": "/stock/2330.TW", "symbol": "2330"})
    assert status == 200
    check_shapes(events)
    assert names(events)[:2] == ["thread", "text"]
    tools = [d for n, d in events if n == "tool"]
    assert [(t["name"], t["status"]) for t in tools] == [("get_holdings", "running"), ("get_holdings", "done")]
    assert tools[0]["label"] == "查看持股"
    assert text_of(events) == "我查一下。\n\n你持有台積電 1 張。\n僅供參考，非投資建議。"
    done = events[-1][1]
    assert done["usage"]["input_tokens"] == 130 and done["usage"]["cache_read_input_tokens"] == 3000
    assert done["model"] == "claude-haiku-5-5" and done["stop_reason"] == "end_turn"

    first, second = fake.requests[0]["body"], fake.requests[1]["body"]
    # frozen system prompt with a breakpoint + automatic caching for the conversation tail
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert first["cache_control"] == {"type": "ephemeral"}
    assert first["output_config"] == {"effort": "low"}
    assert first["model"] == "claude-haiku-5-5" and "temperature" not in first and "tool_choice" not in first
    tool_names = [t["name"] for t in first["tools"]]
    assert tool_names[-2:] == ["web_search", "web_fetch"]
    client_tools = [t for t in first["tools"] if "input_schema" in t]
    assert all(t["strict"] is True and t["input_schema"]["additionalProperties"] is False for t in client_tools)
    assert not any("user_id" in t["input_schema"]["properties"] for t in client_tools)
    search = next(t for t in first["tools"] if t["name"] == "web_search")
    assert search["type"] == "web_search_20260318" and search["user_location"]["country"] == "TW"
    assert search["user_location"]["timezone"] == "Asia/Taipei" and search["allowed_callers"] == ["direct"]
    fetch = next(t for t in first["tools"] if t["name"] == "web_fetch")
    assert fetch["type"] == "web_fetch_20260318" and "twse.com.tw" in fetch["allowed_domains"]
    # per-turn context is a system message after the user's message, never in the top-level system prompt
    assert first["messages"][0] == {"role": "user", "content": [{"type": "text", "text": "我有哪些持股？"}]}
    ctx = first["messages"][1]
    assert ctx["role"] == "system" and "2330.TW（台積電）" in ctx["content"] and "隱私模式：關閉" in ctx["content"]
    assert "2330" not in first["system"][0]["text"]
    # the tool result answers the tool_use and carries this user's holding
    result = second["messages"][-1]
    assert result["role"] == "user" and result["content"][0]["tool_use_id"] == "toolu_1"
    payload = json.loads(result["content"][0]["content"])
    assert [h["symbol"] for h in payload["holdings"]] == ["2330.TW"]
    # the assistant turn is replayed exactly as returned (thinking signature included)
    assert second["messages"][2] == {"role": "assistant", "content": [
        {"type": "thinking", "thinking": "", "signature": "sig-1"}, {"type": "text", "text": "我查一下。"},
        {"type": "tool_use", "id": "toolu_1", "name": "get_holdings", "input": {}}]}
    assert first["system"] == second["system"] and first["tools"] == second["tools"]


def test_second_turn_replays_history_append_only(client, pool, fake, engine):
    fake.reply(thinking("sig-a"), server_tool_use("srvtoolu_1", "web_search", {"query": "台積電 今天 新聞"}),
               web_search_result("srvtoolu_1", [{"url": "https://www.cna.com.tw/a", "title": "中央社",
                                                 "encrypted_content": "ENC-123"}]),
               text("台積電今天上漲，", ), text("主因是法說會。",
                                          [search_citation("https://www.cna.com.tw/a", "中央社", "法說會上調")]),
               usage={"server_tool_use": {"web_search_requests": 1}})
    _status, events = chat(client, "台積電今天為什麼漲？", page={"route": "/stock/2330.TW", "symbol": "2330.TW"})
    check_shapes(events)
    tools = [d for n, d in events if n == "tool"]
    assert [(t["name"], t["status"]) for t in tools] == [("web_search", "running"), ("web_search", "done")]
    assert tools[0]["label"] == "搜尋網路：台積電 今天 新聞"
    cites = [d for n, d in events if n == "citation"]
    assert cites == [{"url": "https://www.cna.com.tw/a", "title": "中央社", "cited_text": "法說會上調"}]
    assert events[-1][1]["usage"]["web_search_requests"] == 1
    thread_id = events[0][1]["id"]

    fake.reply(text("好的。"))
    _status, events2 = chat(client, "那 0050 呢？", thread_id=thread_id, page={"route": "/", "symbol": None},
                           privacy=True)
    assert events2[0][1] == {"id": thread_id, "title": "台積電今天為什麼漲？", "created": False}
    msgs1 = fake.requests[0]["body"]["messages"]
    msgs2 = fake.requests[1]["body"]["messages"]
    assistant = msgs2[2]
    assert msgs2[:2] == msgs1[:2]  # the first turn's user + page context, unchanged
    assert assistant["role"] == "assistant"
    result_block = next(b for b in assistant["content"] if b["type"] == "web_search_tool_result")
    assert result_block["content"][0]["encrypted_content"] == "ENC-123"
    cited = next(b for b in assistant["content"] if b.get("citations"))
    assert cited["citations"][0]["encrypted_index"] == "enc-idx"
    assert msgs2[3]["content"][0]["text"] == "那 0050 呢？"
    assert msgs2[4]["role"] == "system" and "隱私模式：開啟" in msgs2[4]["content"]
    assert len(msgs2) == 5

    detail = client.get(f"{API}/ai/threads/{thread_id}").json()
    roles = [(m["role"], m["text"]) for m in detail["messages"]]
    assert roles == [("user", "台積電今天為什麼漲？"), ("ai", "台積電今天上漲，主因是法說會。"),
                     ("user", "那 0050 呢？"), ("ai", "好的。")]
    assert detail["messages"][1]["citations"][0]["url"] == "https://www.cna.com.tw/a"
    assert detail["messages"][1]["tools"] == [{"name": "web_search", "label": "搜尋網路：台積電 今天 新聞"}]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(AiUsage).where(AiUsage.feature == "chat")) == 2


def test_refusal_is_reported_and_dropped_from_context(client, pool, fake):
    fake.reply(text("這個"), stop_reason="refusal", stop_details={"type": "refusal", "category": "cyber",
                                                                  "explanation": None})
    _status, events = chat(client, "教我寫惡意程式")
    check_shapes(events)
    err = next(d for n, d in events if n == "error")
    assert err["code"] == "refusal" and "沒辦法回答" in err["message"]
    assert events[-1][1]["stop_reason"] == "refusal"
    thread_id = events[0][1]["id"]
    fake.reply(text("你好"))
    chat(client, "那今天大盤如何？", thread_id=thread_id)
    msgs = fake.requests[1]["body"]["messages"]
    assert [m["role"] for m in msgs] == ["user", "system"]  # the refused turn is not replayed
    assert msgs[0]["content"][0]["text"] == "那今天大盤如何？"
    detail = client.get(f"{API}/ai/threads/{thread_id}").json()
    assert detail["messages"][1]["error"]["code"] == "refusal" and detail["messages"][1]["text"] == ""


def test_pause_turn_is_resumed_without_extra_message(client, pool, fake):
    fake.reply(server_tool_use("srvtoolu_9", "web_search", {"query": "q"}), stop_reason="pause_turn")
    fake.reply(web_search_result("srvtoolu_9", [{"url": "https://x.tw", "title": "X", "encrypted_content": "E"}]),
               text("完成"))
    _status, events = chat(client, "查一下")
    check_shapes(events)
    second = fake.requests[1]["body"]["messages"]
    assert [m["role"] for m in second] == ["user", "system", "assistant"]
    assert second[-1]["content"][-1]["type"] == "server_tool_use"
    assert text_of(events) == "完成"


def test_max_tokens_with_tool_use_drops_turn(client, pool, fake):
    fake.reply(text("我查"), tool_use("toolu_x", "get_holdings", {}), stop_reason="max_tokens")
    _status, events = chat(client, "持股？")
    err = next(d for n, d in events if n == "error")
    assert err["code"] == "max_tokens"
    assert not [d for n, d in events if n == "tool"]  # the cut-off tool call is never run
    thread_id = events[0][1]["id"]
    fake.reply(text("ok"))
    chat(client, "再問一次", thread_id=thread_id)
    assert len(fake.requests[1]["body"]["messages"]) == 2


def test_tool_errors_are_returned_as_is_error(client, pool, fake):
    fake.reply(tool_use("toolu_e", "get_stock_overview", {"symbol": "不存在的公司XYZ"}), stop_reason="tool_use")
    fake.reply(text("查不到這家公司。"))
    _status, events = chat(client, "XYZ 股價？")
    tools = [d for n, d in events if n == "tool"]
    assert tools[-1]["status"] == "error"
    result = fake.requests[1]["body"]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "找不到商品" in result["content"]


def test_failover_before_first_byte_and_error_after(client, pool, fake):
    fake.error(529, "overloaded_error").reply(text("嗨"))
    _status, events = chat(client, "你好")
    assert text_of(events) == "嗨" and "error" not in names(events)
    assert fake.keys_used == [KEYS[0], KEYS[1]]
    # a failure after text was streamed cannot be retried: error event, then done
    fake.reply(text("部分回答"), fail_after_text=True)
    _status, events = chat(client, "再一次")
    err = next(d for n, d in events if n == "error")
    assert err["code"] == "ai_busy" and names(events)[-1] == "done"
    assert len(fake.requests) == 3


def test_all_keys_busy(client, pool, fake):
    fake.error(429, "rate_limit_error").error(429, "rate_limit_error")
    _status, events = chat(client, "你好")
    check_shapes(events)
    assert [d["code"] for n, d in events if n == "error"] == ["ai_busy"]


def test_no_keys_is_503(client, fake):
    set_key_pool(KeyPool.from_keys([], client_factory=fake.client))
    try:
        r = client.post(f"{API}/ai/chat", json={"message": "hi"})
        assert r.status_code == 503 and r.json()["error"]["code"] == "ai_unavailable"
        assert client.get(f"{API}/ai/usage").json()["available"] is False
    finally:
        set_key_pool(None)


def test_daily_message_limit(client, pool, fake, ai_env):
    ai_env(AI_DAILY_MESSAGE_LIMIT=1)
    fake.reply(text("一"))
    assert chat(client, "第一題")[0] == 200
    status, body = chat(client, "第二題")
    assert status == 429 and body["error"]["code"] == "ai_daily_limit" and "明天" in body["error"]["message"]
    u = client.get(f"{API}/ai/usage").json()
    assert u["messages_today"] == 1 and u["daily_message_limit"] == 1 and u["messages_remaining"] == 0
    assert len(fake.requests) == 1


def test_monthly_token_budget(client, pool, fake, ai_env):
    ai_env(AI_MONTHLY_TOKEN_BUDGET=500)
    fake.reply(text("一"), usage={"input_tokens": 400, "output_tokens": 50, "cache_read_input_tokens": 1000})
    assert chat(client, "第一題")[0] == 200
    u = client.get(f"{API}/ai/usage").json()
    assert u["tokens_month"] == 400 + 50 + 100  # cache reads count one tenth
    assert u["cost_usd_month"] > 0
    status, body = chat(client, "第二題")
    assert status == 429 and body["error"]["code"] == "ai_monthly_budget"


def test_quota_is_per_user(client, other_client, pool, fake, ai_env):
    ai_env(AI_DAILY_MESSAGE_LIMIT=1)
    fake.reply(text("一")).reply(text("二"))
    assert chat(client, "我的")[0] == 200
    assert chat(other_client, "別人的")[0] == 200


def test_thread_endpoints_and_ownership(client, other_client, pool, fake, engine):
    fake.reply(text("一")).reply(text("二"))
    t1 = chat(client, "第一段")[1][0][1]["id"]
    t2 = chat(client, "第二段")[1][0][1]["id"]
    page = client.get(f"{API}/ai/threads").json()
    assert [t["id"] for t in page["items"]] == [t2, t1] and page["next_cursor"] is None
    assert page["items"][0] | {"updated_at": None, "created_at": None} == {
        "id": t2, "title": "第二段", "message_count": 1, "preview": "二", "updated_at": None, "created_at": None}
    page1 = client.get(f"{API}/ai/threads?limit=1").json()
    assert len(page1["items"]) == 1 and page1["next_cursor"]
    page2 = client.get(f"{API}/ai/threads?limit=1&cursor={page1['next_cursor']}").json()
    assert [t["id"] for t in page2["items"]] == [t1]
    # other users can neither read, continue nor delete it
    assert other_client.get(f"{API}/ai/threads/{t1}").status_code == 404
    assert other_client.delete(f"{API}/ai/threads/{t1}").status_code == 404
    assert other_client.get(f"{API}/ai/threads").json()["items"] == []
    status, _body = chat(other_client, "偷看", thread_id=t1)
    assert status == 404
    assert client.delete(f"{API}/ai/threads/{t1}").status_code == 204
    assert client.get(f"{API}/ai/threads/{t1}").status_code == 404
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(AiMessage).where(AiMessage.thread_id == t1)) == 0
        assert db.get(AiThread, t2) is not None


def test_long_thread_must_start_over(client, pool, fake, engine, ai_env):
    ai_env(AI_THREAD_MAX_CONTEXT_TOKENS=1000)
    fake.reply(text("一"), usage={"input_tokens": 900, "output_tokens": 200})
    tid = chat(client, "長對話")[1][0][1]["id"]
    status, body = chat(client, "繼續", thread_id=tid)
    assert status == 409 and body["error"]["code"] == "thread_too_long"


@pytest.mark.parametrize("bad", [{"message": ""}, {"message": "x", "page": {"route": "/", "extra": 1}},
                                 {"message": "x", "user_id": "usr_someone"}])
def test_chat_body_validation(client, pool, bad):
    assert client.post(f"{API}/ai/chat", json=bad).status_code == 422


def test_system_role_fallback_for_models_without_it(client, pool, fake):
    from forliosa.ai import chat as chat_mod

    fake.error(400, "invalid_request_error", "role 'system' is not supported on this model").reply(text("ok"))
    try:
        _status, events = chat(client, "hi")
        assert text_of(events) == "ok" and "error" not in names(events)
        assert [m["role"] for m in fake.requests[0]["body"]["messages"]] == ["user", "system"]
        retried = fake.requests[1]["body"]["messages"]
        assert [m["role"] for m in retried] == ["user", "user"]
        assert retried[1]["content"][0]["text"].startswith("<system-reminder>")
    finally:
        chat_mod._NO_SYSTEM_ROLE.clear()


def test_bad_request_is_an_error_event(client, pool, fake):
    fake.error(400, "invalid_request_error", "messages: something is wrong")
    _status, events = chat(client, "hi")
    check_shapes(events)
    assert [d["code"] for n, d in events if n == "error"] == ["ai_error"]
    assert len(fake.requests) == 1  # a 400 is not retried on another key


def test_one_key_per_turn_round_robin_across_turns(client, pool, fake):
    acc = make_account(client)
    buy(client, acc, "2330", 1000, 600)
    for _ in range(2):
        fake.reply(tool_use("toolu_k", "get_holdings", {}), stop_reason="tool_use").reply(text("好"))
        chat(client, "持股？")
    # both calls of a turn use the same key (prompt cache / thinking stay valid); the next turn rotates
    assert fake.keys_used == [KEYS[0], KEYS[0], KEYS[1], KEYS[1]]
