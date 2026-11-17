"""The request shape of the report calls against the real SDK (anthropic 2.8.0) and a fake Messages API: server-side
fallbacks, effort, structured output, streaming, the repo's web search without dynamic filtering, no thinking, no
prefill; the 400 fallback path; refusals; the reports' own key slot."""

from __future__ import annotations

from decimal import Decimal

import pytest

from forliosa.ai.keypool import KeyPool, reserved_slots
from forliosa.config import Settings
from forliosa.reports import calls
from tests.ai.fake_anthropic import FakeAnthropic, text

SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"],
          "additionalProperties": False}


@pytest.fixture(autouse=True)
def fresh():
    calls.reset_state()
    yield
    calls.reset_state()


def test_gathering_request_uses_the_repo_web_search_direct_only_with_fallbacks():
    fake = FakeAnthropic().reply(text("[US.market] 〔CNBC〕報導，…"))
    client = fake.client("sk-test")
    kw = calls.request(model="claude-sonnet-5-5", max_tokens=8000, effort="low", system="找已經發生的事",
                       messages=[{"role": "user", "content": "brief"}], tools=[calls.web_search_tool(2)],
                       settings=Settings())
    res = calls.create(client, kw, timeout=300)
    body, headers = fake.requests[0]["body"], fake.requests[0]["headers"]
    tool = body["tools"][0]
    assert tool["type"] == "web_search_20260318" and tool["allowed_callers"] == ["direct"] and tool["max_uses"] == 2
    assert not set(tool["allowed_domains"]) & set(calls.EXCLUDED_SEARCH_DOMAINS)
    assert "blocked_domains" not in tool and "cnbc.com" in tool["allowed_domains"]
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in headers["anthropic-beta"]
    assert body["output_config"] == {"effort": "low"} and "thinking" not in body and "tool_choice" not in body
    assert calls.text_of(res.msg).startswith("[US.market]") and res.seconds >= 0


def test_writing_streams_structured_json_and_checks_have_no_fallbacks():
    fake = FakeAnthropic().reply(text('{"title": "盤後重點"}')).reply(text('{"issues": []}'))
    client = fake.client("sk-test")
    kw = calls.request(model="claude-opus-5-5", max_tokens=64000, effort="high",
                       system=[{"type": "text", "text": "規則", "cache_control": {"type": "ephemeral"}}],
                       messages=[{"role": "user", "content": [{"type": "text", "text": "{}"}]}], schema=SCHEMA,
                       settings=Settings())
    res = calls.stream(client, kw, timeout=900)
    body = fake.requests[0]["body"]
    assert body["stream"] is True and body["model"] == "claude-opus-5-5" and body["max_tokens"] == 64000
    assert body["output_config"] == {"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}}
    assert body["fallbacks"] == "default" and "tools" not in body and "thinking" not in body
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert calls.text_of(res.msg) == '{"title": "盤後重點"}'
    check = calls.request(model="claude-haiku-5-5", max_tokens=4000, effort="low", system="判讀",
                          messages=[{"role": "user", "content": "[]"}], schema=SCHEMA, settings=Settings())
    calls.create(client, check)
    body, headers = fake.requests[1]["body"], fake.requests[1]["headers"]
    assert "fallbacks" not in body and "server-side-fallback" not in headers.get("anthropic-beta", "")
    # switched off by the setting
    assert calls.fallback_params("claude-opus-5-5", Settings(ai_mreport_fallbacks=False)) == {}


def test_no_prefill():
    with pytest.raises(ValueError):
        calls.request(model="claude-opus-5-5", max_tokens=10, effort="high",
                      messages=[{"role": "user", "content": "x"}, {"role": "assistant", "content": "{"}])


def test_a_400_on_fallbacks_with_structured_output_is_sent_again_without_them(caplog):
    fake = FakeAnthropic().error(400, "invalid_request_error", "fallbacks cannot be combined with output_config.format")
    fake.reply(text('{"title": "x"}')).reply(text('{"title": "y"}'))
    client = fake.client("sk-test")
    kw = calls.request(model="claude-opus-5-5", max_tokens=100, effort="high",
                       messages=[{"role": "user", "content": "x"}], schema=SCHEMA, settings=Settings())
    res = calls.stream(client, kw)
    assert res.fallbacks_dropped and "fallbacks" in fake.requests[0]["body"]
    assert "fallbacks" not in fake.requests[1]["body"]
    assert "server-side-fallback" not in fake.requests[1]["headers"].get("anthropic-beta", "")
    assert "refused fallbacks" in caplog.text
    # later structured requests of that model skip them; other 400s are raised as they are
    again = calls.request(model="claude-opus-5-5", max_tokens=100, effort="high",
                          messages=[{"role": "user", "content": "x"}], schema=SCHEMA, settings=Settings())
    assert "fallbacks" not in again


def test_other_bad_requests_are_not_retried():
    import anthropic

    fake = FakeAnthropic().error(400, "invalid_request_error", "max_tokens: too large")
    kw = calls.request(model="claude-opus-5-5", max_tokens=100, effort="high",
                       messages=[{"role": "user", "content": "x"}], settings=Settings())
    with pytest.raises(anthropic.BadRequestError):
        calls.create(fake.client("sk-test"), kw)
    assert len(fake.requests) == 1


def test_stop_info_reads_a_refusal():
    fake = FakeAnthropic().reply(stop_reason="refusal", stop_details={"type": "refusal", "category": "cyber",
                                                                      "explanation": "x"})
    kw = calls.request(model="claude-opus-5-5", max_tokens=100, effort="high",
                       messages=[{"role": "user", "content": "x"}], settings=Settings())
    info = calls.stop_info(calls.stream(fake.client("sk-test"), kw).msg)  # the fake sends stop_details when streaming
    assert info["stop_reason"] == "refusal" and info["refusal_category"] == "cyber" and not info["fallback_used"]


def test_the_reports_slot_is_reserved_only_with_other_keys():
    s = Settings()
    assert reserved_slots(s, [1, 2, 3, 4]) == frozenset({4})
    assert reserved_slots(s, [1, 2, 3]) == frozenset()
    assert reserved_slots(s, [4]) == frozenset()  # the only key keeps serving the members
    assert reserved_slots(Settings(ai_mreport_key_slot=None), [1, 4]) == frozenset()
    fake = FakeAnthropic()
    pool = KeyPool.from_keys([(1, "k1"), (4, "k4")], client_factory=fake.client, reserved=frozenset({4}),
                             sleep=lambda _s: None)
    assert calls.report_slot(pool) == 4 and calls.has_reserved_slot(pool)
    assert [s.index for s in pool.ranked()] == [1]
    pool.get(4).disabled = True
    assert calls.report_slot(pool) is None  # the data edition, never a shared slot
    shared = KeyPool.from_keys([(1, "k1")], client_factory=fake.client)
    assert calls.report_slot(shared) is None and not calls.has_reserved_slot(shared)
    assert pool.status({4: Decimal(1)})[-1]["purpose"] == "market_reports"
