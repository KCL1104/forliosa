"""AI "why" sentence: only when the rules show, cached per symbol per trading day and shared by all users,
rule template on any failure."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session

from forliosa.ai import why as why_mod
from forliosa.models import AiUsage, AiWhyCache
from forliosa.services import stock as stock_svc
from forliosa.timeutil import now_utc
from tests.ai.conftest import API
from tests.ai.fake_anthropic import search_citation, server_tool_use, text, web_search_result

RULE = {"symbol": "2330.TW", "show": True, "headline": "台積電今天上漲 3.5%", "as_of": "2026-11-12T13:30:00+08:00",
        "reasons": [{"kind": "price_move", "text": "今天上漲 3.5%"}], "sources": ["Forliosa 規則計算"]}
DAY = date(2026, 11, 12)


@pytest.fixture()
def rule_why(monkeypatch):
    calls = []

    def fake_why(db, md, symbol):
        calls.append(symbol)
        return dict(RULE)

    monkeypatch.setattr(stock_svc, "why", fake_why)
    return calls


def answer(fake, sentence="法說會上調全年營收展望，激勵股價上漲。", cited=True):
    blocks = [server_tool_use("srvtoolu_w", "web_search", {"query": "台積電 2026-11-12"}),
              web_search_result("srvtoolu_w", [{"url": "https://www.cna.com.tw/n1", "title": "中央社",
                                                "encrypted_content": "E"}])]
    cites = [search_citation("https://www.cna.com.tw/n1", "中央社", "上調全年營收展望")] if cited else None
    fake.reply(*blocks, text(sentence, cites), usage={"server_tool_use": {"web_search_requests": 1}})


def test_enabled_by_default(monkeypatch):
    from forliosa.config import Settings

    monkeypatch.delenv("AI_WHY_ENABLED", raising=False)
    assert Settings(_env_file=None).ai_why_enabled is True


def test_disabled_makes_no_call(client, pool, fake, rule_why, ai_env):
    ai_env(AI_WHY_ENABLED=0)
    w = client.get(f"{API}/instruments/2330/why").json()
    assert w["ai"] is False and w["headline"] == RULE["headline"] and w["citations"] == []
    assert fake.requests == []


def test_cached_per_symbol_per_day_and_shared(client, other_client, pool, fake, rule_why, ai_env, engine):
    ai_env(AI_WHY_ENABLED=1, AI_WHY_BLOCKING=1)
    answer(fake)
    w = client.get(f"{API}/instruments/2330/why").json()
    assert w["ai"] is True and w["headline"] == "法說會上調全年營收展望，激勵股價上漲。"
    assert w["rule_headline"] == RULE["headline"] and w["reasons"] == RULE["reasons"]
    assert w["citations"] == [{"url": "https://www.cna.com.tw/n1", "title": "中央社", "cited_text": "上調全年營收展望"}]
    req = fake.requests[0]["body"]
    assert "stream" not in req and req["model"] == "claude-haiku-5-5"
    assert [t["name"] for t in req["tools"]] == ["web_search"] and req["tools"][0]["user_location"]["country"] == "TW"
    assert "2026-11-12" in req["messages"][0]["content"]
    # another user, same day: served from the shared cache, no new model call
    w2 = other_client.get(f"{API}/instruments/2330/why").json()
    assert w2["headline"] == w["headline"] and len(fake.requests) == 1
    with Session(engine) as db:
        row = db.get(AiWhyCache, ("2330.TW", DAY))
        assert row.status == "ok"
        usage = db.query(AiUsage).one()
        assert usage.feature == "why" and usage.web_search_requests == 1
    # the shared cache does not count toward the triggering user's monthly budget
    assert client.get(f"{API}/ai/usage").json()["tokens_month"] == 0


@pytest.mark.parametrize("kind", ["error", "none", "no_citation", "refusal"])
def test_falls_back_to_rules(client, pool, fake, rule_why, ai_env, engine, kind):
    ai_env(AI_WHY_ENABLED=1, AI_WHY_BLOCKING=1)
    if kind == "error":
        fake.error(400, "invalid_request_error")
    elif kind == "none":
        answer(fake, "NONE", cited=False)
    elif kind == "no_citation":
        answer(fake, "可能是市場情緒。", cited=False)
    else:
        fake.reply(text(""), stop_reason="refusal")
    w = client.get(f"{API}/instruments/2330/why").json()
    assert w["ai"] is False and w["headline"] == RULE["headline"] and w["citations"] == []
    with Session(engine) as db:
        status = db.get(AiWhyCache, ("2330.TW", DAY)).status
    assert status == ("failed" if kind in ("error", "refusal") else "empty")
    n = len(fake.requests)
    client.get(f"{API}/instruments/2330/why")
    assert len(fake.requests) == n  # cached outcome: no retry storm


def test_failed_is_retried_after_a_while(client, pool, fake, rule_why, ai_env, engine):
    ai_env(AI_WHY_ENABLED=1, AI_WHY_BLOCKING=1)
    with Session(engine) as db:
        db.add(AiWhyCache(symbol="2330.TW", date=DAY, status="failed", created_at=now_utc() - timedelta(hours=1)))
        db.commit()
    answer(fake)
    assert client.get(f"{API}/instruments/2330/why").json()["ai"] is True


def test_not_shown_means_no_call(client, pool, fake, monkeypatch, ai_env):
    ai_env(AI_WHY_ENABLED=1, AI_WHY_BLOCKING=1)
    monkeypatch.setattr(stock_svc, "why", lambda db, md, s: {**RULE, "show": False, "headline": None, "reasons": []})
    w = client.get(f"{API}/instruments/2330/why").json()
    assert w["show"] is False and w["ai"] is False and fake.requests == []


def test_background_mode_returns_rules_then_ai(client, pool, fake, rule_why, ai_env, monkeypatch):
    ai_env(AI_WHY_ENABLED=1)
    started = []
    monkeypatch.setattr(why_mod, "_start_background", lambda *a, **k: started.append(a[1]["symbol"]))
    w = client.get(f"{API}/instruments/2330/why").json()
    assert w["ai"] is False and started == ["2330.TW"]
