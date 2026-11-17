"""會員方案 (``forliosa.plans``; 產品負責人 2026-11-15, 2026-11-17): members (granted until a day, or with no end date;
site admins count) and free accounts differ only in the daily closing briefing and the AI quota (3 questions a day for
free accounts, 30 for members). Everything else — 深度搜尋 (taking 3 of the account's own questions) and 匯入對帳單
among them — is every account's by default."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa import plans
from forliosa.ai import briefing as br
from forliosa.api.errors import ApiError
from forliosa.config import get_settings
from forliosa.models import User
from forliosa.timeutil import TAIPEI
from tests.ai.conftest import API, chat
from tests.ai.fake_anthropic import text

DEMO = "demo@forliosa.local"


@pytest.fixture(autouse=True)
def plans_on(ai_env, monkeypatch):
    """The deployment's plans: the defaults of AI_FREE_DEEP_SEARCH, AI_FREE_DAILY_BRIEFING and IMPORT_STATEMENTS (the
    shared test fixture opens the briefing to every account), with the deployment's daily limits."""
    for name in ("AI_FREE_DEEP_SEARCH", "AI_FREE_DAILY_BRIEFING", "IMPORT_STATEMENTS"):
        monkeypatch.delenv(name, raising=False)
    ai_env(AI_DAILY_MESSAGE_LIMIT=3, AI_MEMBER_DAILY_MESSAGE_LIMIT=30, AI_DEEP_SEARCH_COST=3)


@pytest.fixture()
def db(engine):
    with Session(engine) as session:
        yield session


def demo(db: Session) -> User:
    return db.scalar(select(User).where(User.email == DEMO))


def usage(client) -> dict:
    return client.get(f"{API}/ai/usage").json()


def test_a_free_account(client, pool, fake):
    """產品負責人 2026-11-17: only the briefing and the quota are members'. A free account has 深度搜尋 (3 of its own 3
    questions) and 匯入對帳單 by default; the briefing is refused."""
    me = client.get(f"{API}/me").json()
    assert me["plan"] == {"tier": "free", "until": None, "deep_search": True, "daily_briefing": False,
                          "statement_import": True}
    u = usage(client)
    assert (u["plan"], u["daily_message_limit"], u["deep_search_cost"], u["deep_search_members_only"]) == (
        "free", 3, 3, False)
    fake.reply(text("整理"))
    assert chat(client, "深入研究台積電", mode="deep")[0] == 200
    u = usage(client)
    assert (u["messages_today"], u["messages_remaining"]) == (3, 0)  # the day's 3 questions, the free quota unchanged
    status, body = chat(client, "再問一題")
    assert status == 429 and body["error"]["code"] == "ai_daily_limit"
    r = client.patch(f"{API}/me/preferences", json={"daily_briefing": True})
    assert r.status_code == 403 and r.json()["error"] == {"code": "members_only", "message": "每日收盤簡報是會員功能。"}
    assert client.patch(f"{API}/me/preferences", json={"daily_briefing": False}).status_code == 200
    assert len(fake.requests) == 1


def test_deep_search_can_be_members_only_again(client, pool, fake, ai_env, db):
    """``AI_FREE_DEEP_SEARCH=false`` (a deployment's switch): the members-only 深度搜尋 of 2026-11-15 to 11-17."""
    ai_env(AI_FREE_DEEP_SEARCH="false")
    assert client.get(f"{API}/me").json()["plan"]["deep_search"] is False
    u = usage(client)
    assert (u["deep_search_cost"], u["deep_search_members_only"]) == (None, True)
    status, body = chat(client, "深入研究台積電", mode="deep")
    assert status == 403 and body["error"]["code"] == "members_only"
    assert fake.requests == []
    plans.grant(db, DEMO, None, None)
    assert (usage(client)["deep_search_cost"], usage(client)["deep_search_members_only"]) == (3, False)


def test_a_member(client, pool, fake, db):
    plans.grant(db, " Demo@Forliosa.local ", date(2099, 12, 31), "轉帳 NT$300")
    me = client.get(f"{API}/me").json()
    assert me["plan"] == {"tier": "member", "until": "2099-12-31", "deep_search": True, "daily_briefing": True,
                          "statement_import": True}
    u = usage(client)
    assert (u["plan"], u["daily_message_limit"], u["deep_search_cost"], u["deep_search_members_only"]) == (
        "member", 30, 3, False)
    assert u["monthly_token_budget"] is None  # members: the US$ budget is the limit
    fake.reply(text("整理"))
    assert chat(client, "深入研究台積電", mode="deep")[0] == 200
    assert usage(client)["messages_today"] == 3
    assert client.patch(f"{API}/me/preferences", json={"daily_briefing": True}).status_code == 200


def test_membership_ends_after_its_last_day(db, client):
    user = demo(db)
    user.plan, user.plan_until = plans.MEMBER, datetime(2026, 12, 1, tzinfo=TAIPEI)  # last day 11/30
    db.commit()
    assert plans.last_day(user.plan_until) == date(2026, 11, 30)
    assert plans.is_member(user, datetime(2026, 11, 30, 15, 59, tzinfo=UTC))  # 11/30 23:59 Taipei
    assert not plans.is_member(user, datetime(2026, 11, 30, 16, 0, tzinfo=UTC))
    user.plan_until = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    assert client.get(f"{API}/me").json()["plan"]["tier"] == "free"
    assert usage(client)["daily_message_limit"] == 3


def test_site_admins_count_as_members(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_emails", [DEMO])
    plan = plans.plan_of(demo(db), get_settings())
    assert (plan.tier, plan.until, plan.deep_search, plan.daily_briefing, plan.statement_import) == (
        "member", None, True, True, True)
    assert client.get(f"{API}/me").json()["plan"]["tier"] == "member"


def test_grant_needs_an_account_and_a_day_not_in_the_past(db, client):
    with pytest.raises(ApiError) as missing:
        plans.grant(db, "nobody@example.com", None, None)
    assert missing.value.status == 404
    with pytest.raises(ApiError) as past:
        plans.grant(db, DEMO, date(2020, 1, 1), None)
    assert past.value.status == 422
    row = plans.grant(db, DEMO, None, None)
    assert (row["until"], row["active"]) == (None, True)
    plans.revoke(db, row["user_id"])
    assert demo(db).plan == "free"


def test_only_members_get_the_daily_briefing(client, db):
    user = demo(db)
    user.preferences = {**(user.preferences or {}), "daily_briefing": True}
    db.commit()
    assert not br.wanted(user, get_settings())  # switched on before plans existed: no briefing for a free account
    plans.grant(db, DEMO, None, None)
    assert br.wanted(demo(db), get_settings())


def test_analyst_views_wait_for_next_month_in_economy_mode(client, pool, fake, ai_env):
    fake.reply(text("一"), usage={"input_tokens": 200_000, "output_tokens": 2_000})
    assert chat(client, "第一題")[0] == 200
    spent = usage(client)["cost_usd_month"]
    ai_env(AI_MONTHLY_COST_BUDGET_USD=round(spent + 0.01, 4))
    assert usage(client)["economy"] is True
    r = client.post(f"{API}/instruments/2330/analyst-views")
    assert r.status_code == 429 and r.json()["error"]["code"] == "ai_monthly_budget"


def test_members_stop_economy_mode_sooner(db, client, ai_env, monkeypatch):
    """產品負責人 2026-11-16: members about US$8 a month (US$3 before) and 省錢模式 only up to 1.25 times that (about
    US$10; AI_MEMBER_ECONOMY_CAP_MULTIPLIER); free accounts keep US$1 and twice the budget
    (AI_ECONOMY_CAP_MULTIPLIER)."""
    from decimal import Decimal

    from forliosa.ai import store

    for name in ("AI_MONTHLY_COST_BUDGET_USD", "AI_MEMBER_MONTHLY_COST_BUDGET_USD", "AI_ECONOMY_CAP_MULTIPLIER",
                 "AI_MEMBER_ECONOMY_CAP_MULTIPLIER"):
        monkeypatch.delenv(name, raising=False)
    ai_env()  # the defaults
    spent = {"usd": Decimal(0)}
    monkeypatch.setattr(store, "month_usage", lambda db, user, now=None: (0, spent["usd"]))

    def mode(usd: str) -> str:
        spent["usd"] = Decimal(usd)
        return store.month_mode(db, demo(db), get_settings())

    plan = plans.plan_of(demo(db), get_settings())
    assert (plan.tier, plan.monthly_cost_budget_usd, plan.economy_cap_multiplier) == ("free", 1.0, 2.0)
    assert [mode(u) for u in ("0.90", "0.99", "1.95", "1.995")] == ["normal", "economy", "economy", "stopped"]

    plans.grant(db, DEMO, None, None)
    plan = plans.plan_of(demo(db), get_settings())
    assert (plan.tier, plan.monthly_cost_budget_usd, plan.economy_cap_multiplier) == ("member", 8.0, 1.25)
    assert [mode(u) for u in ("7.90", "7.99", "9.95", "9.995", "12")] == [
        "normal", "economy", "economy", "stopped", "stopped"]
    ai_env(AI_MEMBER_ECONOMY_CAP_MULTIPLIER=1)  # no 省錢模式 for members: stop at the budget
    assert mode("7.99") == "stopped"
