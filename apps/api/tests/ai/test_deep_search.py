"""深度搜尋 (``POST /ai/chat`` with ``mode: "deep"``): the request it builds, what it counts as, how the turn is
remembered, and that an ordinary turn is unchanged."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.ai.prompts import CHAT_SYSTEM, DEEP_SEARCH_NOTE, page_context
from forliosa.config import get_settings
from forliosa.models import AiMessage
from forliosa.timeutil import TAIPEI
from tests.ai.conftest import API, chat
from tests.ai.fake_anthropic import server_tool_use, text, web_search_result


def search_tool(body: dict) -> dict:
    return next(t for t in body["tools"] if t.get("name") == "web_search")


def context_of(body: dict) -> str:
    return next(m["content"] for m in body["messages"] if m["role"] == "system")


def test_deep_turn_raises_the_search_limit_and_puts_the_instructions_in_the_page_context(client, pool, fake):
    fake.reply(text("整理好了"))
    status, events = chat(client, "深入研究台積電的先進製程", mode="deep")
    assert status == 200 and events[-1][0] == "done"
    body = fake.requests[0]["body"]
    assert search_tool(body)["max_uses"] == get_settings().ai_deep_search_max_uses == 12
    ctx = context_of(body)
    assert DEEP_SEARCH_NOTE in ctx and ctx.startswith("頁面情境")
    # the frozen prompt only points at the page context; the rules themselves are not copied into it
    assert body["system"][0]["text"] == CHAT_SYSTEM
    assert "頁面情境寫「深度搜尋」的那一題" in CHAT_SYSTEM and "最多 8 點" not in CHAT_SYSTEM
    # every other tool is the one an ordinary turn sends
    fake.reply(text("一般"))
    chat(client, "台積電今天怎麼樣")
    plain = fake.requests[1]["body"]
    assert search_tool(plain)["max_uses"] == get_settings().ai_web_search_max_uses == 3
    strip = lambda tools: [{k: v for k, v in t.items() if k != "max_uses"} for t in tools]  # noqa: E731
    assert strip(body["tools"]) == strip(plain["tools"])
    assert "深度搜尋" not in context_of(plain)


def test_the_note_says_how_to_research_and_how_to_write_it_up():
    ctx = page_context(datetime(2026, 11, 13, 10, 0, tzinfo=TAIPEI), "/stock/2330.TW", "2330.TW", "台積電", False,
                       deep=True)
    for part in ("公司公告與財報", "法說會", "競爭對手", "風險", "分幾輪用 web_search", "兩邊都寫出來", "兩三句結論",
                 "最多 8 點", "最多 3 個短標題", "不給買賣建議與目標價"):
        assert part in ctx
    assert "**" not in DEEP_SEARCH_NOTE and "#" not in DEEP_SEARCH_NOTE  # the UI shows plain text
    assert "深度搜尋" not in page_context(datetime(2026, 11, 13, 10, 0, tzinfo=TAIPEI), "/", None, None, False)


def test_a_deep_search_counts_as_five_questions(client, pool, fake, ai_env):
    ai_env(AI_DAILY_MESSAGE_LIMIT=7)
    usage = lambda: client.get(f"{API}/ai/usage").json()  # noqa: E731
    assert usage()["deep_search_cost"] == 5
    fake.reply(text("整理"))
    assert chat(client, "研究鴻海", mode="deep")[0] == 200
    u = usage()
    assert (u["messages_today"], u["messages_remaining"]) == (5, 2)
    # two questions are left: an ordinary one still fits, another deep search does not start
    status, body = chat(client, "再研究一次", mode="deep")
    assert status == 429 and body["error"]["code"] == "ai_daily_limit"
    assert body["error"]["message"] == "今天還剩 2 題，深度搜尋一次要 5 題。"
    assert (body["error"]["remaining"], body["error"]["cost"]) == (2, 5)
    assert len(fake.requests) == 1  # nothing was sent to the model
    fake.reply(text("一")).reply(text("二"))
    assert chat(client, "一般的問題")[0] == 200
    assert chat(client, "再一題")[0] == 200
    status, body = chat(client, "滿了")
    assert status == 429 and "明天" in body["error"]["message"]
    assert usage()["messages_remaining"] == 0


def test_the_cost_is_a_setting(client, pool, fake, ai_env):
    ai_env(AI_DEEP_SEARCH_COST=3, AI_DEEP_SEARCH_MAX_USES=6)
    fake.reply(text("整理"))
    assert chat(client, "研究聯發科", mode="deep")[0] == 200
    assert search_tool(fake.requests[0]["body"])["max_uses"] == 6
    u = client.get(f"{API}/ai/usage").json()
    assert (u["deep_search_cost"], u["messages_today"]) == (3, 3)


def test_a_deep_search_that_never_reached_the_model_counts_as_one(client, pool, fake):
    fake.error(400, "invalid_request_error", "scripted failure")
    status, events = chat(client, "研究台達電", mode="deep")
    assert status == 200 and any(n == "error" for n, _ in events)
    assert client.get(f"{API}/ai/usage").json()["messages_today"] == 1
    # declined before any model call (not about investing): also one
    status, events = chat(client, "幫我寫一個 Python 的快速排序", mode="deep")
    assert status == 200 and len(fake.requests) == 1
    assert client.get(f"{API}/ai/usage").json()["messages_today"] == 2


def test_the_thread_remembers_which_question_was_a_deep_search(client, pool, fake, engine):
    fake.reply(text("整理")).reply(text("一般的回答"))
    _s, events = chat(client, "研究台積電", mode="deep")
    thread_id = events[0][1]["id"]
    chat(client, "那鴻海呢", thread_id=thread_id)
    detail = client.get(f"{API}/ai/threads/{thread_id}").json()
    users = [m for m in detail["messages"] if m["role"] == "user"]
    assert [m["mode"] for m in users] == ["deep", None]
    assert all(m.get("mode") is None for m in detail["messages"] if m["role"] == "ai")
    with Session(engine) as db:
        rows = list(db.scalars(select(AiMessage).where(AiMessage.is_user_input.is_(True)).order_by(AiMessage.seq)))
    assert rows[0].meta == {"mode": "deep", "cost": 5} and rows[1].meta == {}
    # the second turn replays the first one with its own (deep) page context, and is itself an ordinary turn
    second = fake.requests[1]["body"]
    contexts = [m["content"] for m in second["messages"] if m["role"] == "system"]
    assert DEEP_SEARCH_NOTE in contexts[0] and "深度搜尋" not in contexts[1]


def test_a_deep_turn_may_loop_longer(client, pool, fake, ai_env):
    ai_env(AI_MAX_TOOL_ROUNDS=2, AI_DEEP_MAX_TOOL_ROUNDS=4)
    for i in range(3):  # three resumed server-tool turns, then the answer: four calls
        fake.reply(server_tool_use(f"srvtoolu_{i}", "web_search", {"query": f"q{i}"}), stop_reason="pause_turn")
    fake.reply(web_search_result("srvtoolu_2", [{"url": "https://x.tw", "title": "X", "encrypted_content": "E"}]),
               text("完成"))
    _s, events = chat(client, "研究廣達", mode="deep")
    assert "".join(d["delta"] for n, d in events if n == "text") == "完成" and len(fake.requests) == 4
    assert not any(n == "error" for n, _ in events)
    # the same script as an ordinary turn runs out of rounds
    for i in range(3):
        fake.reply(server_tool_use(f"srvtoolu_b{i}", "web_search", {"query": f"q{i}"}), stop_reason="pause_turn")
    _s, events = chat(client, "廣達怎麼樣")
    assert [d["code"] for n, d in events if n == "error"] == ["too_many_steps"]


def test_no_web_search_no_deep_search(client, pool, fake, ai_env):
    ai_env(AI_WEB_SEARCH="false")
    assert client.get(f"{API}/ai/usage").json()["deep_search_cost"] is None
    status, body = chat(client, "研究台積電", mode="deep")
    assert status == 503 and body["error"]["code"] == "ai_unavailable" and "深度搜尋" in body["error"]["message"]
    assert fake.requests == []


def test_mode_is_validated(client, pool, fake):
    status, _body = chat(client, "研究台積電", mode="turbo")
    assert status == 422
