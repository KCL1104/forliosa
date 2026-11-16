"""The deployment's AI quota (產品負責人 2026-11-15): free accounts 3 questions a day and about US$1 a month, members
30 a day and about US$8 (2026-11-16; US$3 before); over the month's budget questions go on without web search (省錢模式)
up to twice the budget for free accounts, 1.25 times for members (2026-11-16)."""

from __future__ import annotations

from forliosa.ai import store
from forliosa.config import Settings
from tests.ai.conftest import API, chat
from tests.ai.fake_anthropic import text

DEFAULTS = ("AI_DAILY_MESSAGE_LIMIT", "AI_DEEP_SEARCH_COST", "AI_MONTHLY_COST_BUDGET_USD",
            "AI_MEMBER_DAILY_MESSAGE_LIMIT", "AI_MEMBER_MONTHLY_COST_BUDGET_USD", "AI_FREE_DEEP_SEARCH",
            "AI_FREE_DAILY_BRIEFING", "AI_ECONOMY_CAP_MULTIPLIER", "AI_MEMBER_ECONOMY_CAP_MULTIPLIER")


def test_the_defaults(monkeypatch):
    for name in DEFAULTS:
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert (s.ai_daily_message_limit, s.ai_monthly_cost_budget_usd, s.ai_monthly_token_budget) == (3, 1.0, 3_000_000)
    assert (s.ai_member_daily_message_limit, s.ai_member_monthly_cost_budget_usd,
            s.ai_member_monthly_token_budget) == (30, 8.0, 0)
    assert (s.ai_free_deep_search, s.ai_free_daily_briefing) == (False, False)
    assert (s.ai_deep_search_cost, s.ai_economy_cap_multiplier, s.ai_member_economy_cap_multiplier) == (3, 2.0, 1.25)
    assert store.deep_search_cost(s) == 3


def test_a_deep_search_never_costs_more_than_a_day(client, pool, fake, ai_env):
    ai_env(AI_DAILY_MESSAGE_LIMIT=3, AI_DEEP_SEARCH_COST=5)
    usage = lambda: client.get(f"{API}/ai/usage").json()  # noqa: E731
    assert usage()["deep_search_cost"] == 3
    fake.reply(text("整理"))
    assert chat(client, "研究台積電", mode="deep")[0] == 200
    u = usage()
    assert (u["messages_today"], u["messages_remaining"]) == (3, 0)
    status, body = chat(client, "再問一題")
    assert status == 429 and body["error"]["code"] == "ai_daily_limit"


def tool_names(body: dict) -> set[str]:
    return {t["name"] for t in body["tools"]}


def test_the_monthly_dollar_budget_then_economy_mode(client, pool, fake, ai_env):
    """A turn starts normally while its typical cost still fits: an ordinary question needs US$0.05 left, a 深度搜尋
    US$0.15. Below that, questions run without web search (省錢模式) until twice the budget is spent."""
    ai_env(AI_MONTHLY_COST_BUDGET_USD=2)
    fake.reply(text("一"), usage={"input_tokens": 200_000, "output_tokens": 2_000})
    assert chat(client, "第一題")[0] == 200
    assert {"web_search", "web_fetch"} <= tool_names(fake.requests[-1]["body"])
    usage = lambda: client.get(f"{API}/ai/usage").json()  # noqa: E731
    u = usage()
    spent = u["cost_usd_month"]
    assert spent > 0 and u["monthly_cost_budget_usd"] == 2
    assert (u["economy"], u["month_budget_reached"]) == (False, False)

    ai_env(AI_MONTHLY_COST_BUDGET_USD=round(spent + 0.10, 4))  # enough for an ordinary question, not a deep search
    status, body = chat(client, "研究一下", mode="deep")
    assert status == 429
    assert body["error"]["message"] == "這個月的 AI 用量剩不多，深度搜尋要等下個月；一般提問還可以問。"
    assert usage()["economy"] is False

    ai_env(AI_MONTHLY_COST_BUDGET_USD=round(spent + 0.02, 4))  # less than an ordinary question left: 省錢模式
    u = usage()
    assert (u["economy"], u["month_budget_reached"], u["deep_search_cost"]) == (True, False, None)
    fake.reply(text("二"))
    status, events = chat(client, "第二題")
    assert status == 200 and events[-1][0] == "done"
    body = fake.requests[-1]["body"]
    assert not tool_names(body) & {"web_search", "web_fetch"} and "get_news" in tool_names(body)
    context = next(m["content"] for m in body["messages"] if m["role"] == "system")
    assert "這個月的網路搜尋額度用完了" in context
    status, body = chat(client, "研究一下", mode="deep")
    assert status == 429 and "深度搜尋要等下個月 1 日" in body["error"]["message"]

    ai_env(AI_ECONOMY_CAP_MULTIPLIER=1)  # no 省錢模式: stop at the budget
    status, body = chat(client, "第三題")
    assert status == 429 and body["error"]["code"] == "ai_monthly_budget" and "下個月" in body["error"]["message"]
    assert usage()["month_budget_reached"] is True
    assert len(fake.requests) == 2  # the refused turns never reached the model


def test_economy_mode_stops_at_twice_the_budget(client, pool, fake, ai_env):
    fake.reply(text("一"), usage={"input_tokens": 200_000, "output_tokens": 2_000})
    assert chat(client, "第一題")[0] == 200
    spent = client.get(f"{API}/ai/usage").json()["cost_usd_month"]
    ai_env(AI_MONTHLY_COST_BUDGET_USD=round(spent / 2, 6))  # spent = twice the budget
    u = client.get(f"{API}/ai/usage").json()
    assert (u["economy"], u["month_budget_reached"]) == (False, True)
    status, body = chat(client, "第二題")
    assert status == 429 and body["error"]["message"] == "這個月的 AI 用量已達上限，下個月 1 日會重新計算。"
