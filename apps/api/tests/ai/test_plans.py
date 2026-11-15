"""會員方案 (``forliosa.plans``; 產品負責人 2026-11-15): free accounts get 3 questions a day and no 深度搜尋 or daily
briefing; members (granted until a day, or with no end date; site admins count) get 30, 深度搜尋 and the briefing."""

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
def plans_on(ai_env):
    """The deployment's plans (the shared test fixture opens 深度搜尋 and the briefing to every account)."""
    ai_env(AI_FREE_DEEP_SEARCH="false", AI_FREE_DAILY_BRIEFING="false", AI_DAILY_MESSAGE_LIMIT=3,
           AI_MEMBER_DAILY_MESSAGE_LIMIT=30, AI_DEEP_SEARCH_COST=3)


@pytest.fixture()
def db(engine):
    with Session(engine) as session:
        yield session


def demo(db: Session) -> User:
    return db.scalar(select(User).where(User.email == DEMO))


def usage(client) -> dict:
    return client.get(f"{API}/ai/usage").json()


def test_a_free_account(client, pool, fake):
    me = client.get(f"{API}/me").json()
    assert me["plan"] == {"tier": "free", "until": None, "deep_search": False, "daily_briefing": False}
    u = usage(client)
    assert (u["plan"], u["daily_message_limit"], u["deep_search_cost"], u["deep_search_members_only"]) == (
        "free", 3, None, True)
    status, body = chat(client, "深入研究台積電", mode="deep")
    assert status == 403 and body["error"]["code"] == "members_only"
    r = client.patch(f"{API}/me/preferences", json={"daily_briefing": True})
    assert r.status_code == 403 and r.json()["error"]["message"] == "每日收盤簡報是會員功能。"
    assert client.patch(f"{API}/me/preferences", json={"daily_briefing": False}).status_code == 200
    assert fake.requests == []


def test_a_member(client, pool, fake, db):
    plans.grant(db, " Demo@Forliosa.local ", date(2099, 12, 31), "轉帳 NT$300")
    me = client.get(f"{API}/me").json()
    assert me["plan"] == {"tier": "member", "until": "2099-12-31", "deep_search": True, "daily_briefing": True}
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
    assert (plan.tier, plan.until, plan.deep_search, plan.daily_briefing) == ("member", None, True, True)
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
