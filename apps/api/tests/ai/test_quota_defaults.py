"""The deployment's AI quota (產品負責人 2026-11-15): 3 questions a day until there are subscription plans, about
US$2 per user per month, a 深度搜尋 uses the whole day."""

from __future__ import annotations

from forliosa.ai import store
from forliosa.config import Settings
from tests.ai.conftest import API, chat
from tests.ai.fake_anthropic import text


def test_the_defaults(monkeypatch):
    for name in ("AI_DAILY_MESSAGE_LIMIT", "AI_DEEP_SEARCH_COST", "AI_MONTHLY_COST_BUDGET_USD"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert (s.ai_daily_message_limit, s.ai_monthly_cost_budget_usd, s.ai_deep_search_cost) == (3, 2.0, 3)
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


def test_the_monthly_dollar_budget(client, pool, fake, ai_env):
    """A turn starts only while its typical cost still fits: an ordinary question needs US$0.03 left, a 深度搜尋
    US$0.15. The usage endpoint says when the month is used up."""
    ai_env(AI_MONTHLY_COST_BUDGET_USD=2)
    fake.reply(text("一"), usage={"input_tokens": 200_000, "output_tokens": 2_000})
    assert chat(client, "第一題")[0] == 200
    usage = lambda: client.get(f"{API}/ai/usage").json()  # noqa: E731
    u = usage()
    spent = u["cost_usd_month"]
    assert spent > 0 and u["monthly_cost_budget_usd"] == 2 and u["month_budget_reached"] is False

    ai_env(AI_MONTHLY_COST_BUDGET_USD=round(spent + 0.02, 4))  # less than an ordinary question left
    status, body = chat(client, "第二題")
    assert status == 429 and body["error"]["code"] == "ai_monthly_budget" and "下個月" in body["error"]["message"]
    assert usage()["month_budget_reached"] is True

    ai_env(AI_MONTHLY_COST_BUDGET_USD=round(spent + 0.10, 4))  # enough for an ordinary question, not a deep search
    status, body = chat(client, "研究一下", mode="deep")
    assert status == 429
    assert body["error"]["message"] == "這個月的 AI 用量剩不多，深度搜尋要等下個月；一般提問還可以問。"
    assert usage()["month_budget_reached"] is False
    fake.reply(text("二"))
    assert chat(client, "一般的")[0] == 200
    assert len(fake.requests) == 2  # the refused turns never reached the model
