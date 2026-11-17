"""The writing call (contract §9.1) and the compliance read (§11) against the real SDK and a fake Messages API."""

from __future__ import annotations

import json

import pytest

from forliosa.config import Settings
from forliosa.reports import calls, compliance, pack, write
from forliosa.reports.settings import Writer
from tests.ai.fake_anthropic import FakeAnthropic, text, thinking
from tests.reports.conftest import MON, ts
from tests.reports.helpers import close_output, json_text, with_web

OPUS = Writer("claude-opus-5-5", "high")


@pytest.fixture(autouse=True)
def fresh():
    calls.reset_state()
    compliance.reset_state()


@pytest.fixture()
def pk(market_db):
    return with_web(pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16)).pack)


def streamer(fake):
    client = fake.client("sk-test")
    return lambda kw: calls.stream(client, kw, timeout=900)


def test_write_request_shape_and_parse(pk):
    out = close_output(pk)
    fake = FakeAnthropic().reply(json_text(out))
    w = write.write("close", pk, OPUS, streamer(fake), Settings())
    assert w.output == out and w.error is None and w.refusal is None
    body, headers = fake.requests[0]["body"], fake.requests[0]["headers"]
    assert body["stream"] is True and body["model"] == "claude-opus-5-5" and body["max_tokens"] == 64000
    assert body["output_config"]["effort"] == "high" and body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"]["properties"]["chart_of_day"]["properties"]["code"]["enum"] == \
        ["G4", "none"]
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in headers["anthropic-beta"]
    assert "tools" not in body and "thinking" not in body
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"} and "11/16" not in body["system"][0]["text"]
    user = body["messages"][0]["content"]
    assert json.loads(user[0]["text"])["web"][0]["id"] == "X001" and user[1]["cache_control"]
    assert "盤後重點" in user[1]["text"]


def test_max_tokens_is_called_again_at_medium(pk):
    fake = FakeAnthropic().reply(text('{"title": "'), stop_reason="max_tokens").reply(json_text(close_output(pk)))
    w = write.write("close", pk, OPUS, streamer(fake), Settings())
    assert w.output is not None and [m[2] for m in w.msgs] == ["high", "medium"]
    assert fake.requests[1]["body"]["output_config"]["effort"] == "medium"


def test_a_refusal_ends_with_its_category(pk):
    fake = FakeAnthropic().reply(text(""), stop_reason="refusal", stop_details={"type": "refusal", "category": "cyber"})
    w = write.write("close", pk, OPUS, streamer(fake), Settings())
    assert w.output is None and w.refusal == "cyber" and w.error == "refusal"


def test_unparsable_or_off_schema_output_fails(pk):
    fake = FakeAnthropic().reply(text("not json")).reply(text('{"title": "x"}'))
    assert write.write("close", pk, OPUS, streamer(fake), Settings()).error == "parse"
    assert write.write("close", pk, OPUS, streamer(fake), Settings()).error == "schema"


def test_revision_sends_the_reply_back_unchanged(pk):
    out = close_output(pk)
    fake = FakeAnthropic().reply(thinking("sig-1"), json_text(out)).reply(json_text(out))
    draft = write.write("close", pk, OPUS, streamer(fake), Settings())
    rev = write.revise("close", pk, OPUS, streamer(fake), draft,
                       [{"path": "title", "code": "forbidden_word", "detail": "明天"}], Settings())
    assert rev.output == out
    msgs = fake.requests[1]["body"]["messages"]
    assert msgs[1]["role"] == "assistant" and msgs[1]["content"][0] == {"type": "thinking", "thinking": "",
                                                                         "signature": "sig-1"}
    assert msgs[2]["role"] == "user" and "forbidden_word" in msgs[2]["content"]
    assert fake.requests[1]["body"]["output_config"]["effort"] == "high"


# -- compliance ----------------------------------------------------------------------------------------------------
def checker(fake):
    client = fake.client("sk-test")
    return lambda kw, attempt: calls.create(client, kw)


def test_check_request_and_issues(pk):
    out = close_output(pk)
    first = out["what_happened"][0]["sentences"][0]["text"]
    fake = FakeAnthropic().reply(json_text({"issues": [
        {"path": "what_happened[0].sentences[0]", "category": "direction", "quote": first[:6]},
        {"path": "what_happened[9].sentences[0]", "category": "direction", "quote": "模型自己編的"},
        {"path": "what_happened[0].sentences[0]", "category": "made_up", "quote": first[:6]}]}))
    res = compliance.check(out, "close", "claude-haiku-5-5", "low", checker(fake), Settings())
    # an unknown path or category is ignored
    assert res.ok and len(res.issues) == 1 and res.issues[0]["category"] == "direction"
    body = fake.requests[0]["body"]
    assert body["model"] == "claude-haiku-5-5" and body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema" and "thinking" not in body
    assert "fallbacks" not in body
    sent = json.loads(body["messages"][0]["content"])
    assert sent[0] == {"path": "title", "text": out["title"]} and not any("refs" in x for x in sent)
    assert "F001" not in body["messages"][0]["content"]


def test_check_fails_twice(pk):
    fake = FakeAnthropic().error(500, "api_error").error(500, "api_error")
    res = compliance.check(close_output(pk), "close", "claude-haiku-5-5", "low", checker(fake), Settings())
    assert not res.ok and len(fake.requests) == 2


def test_check_without_structured_output(pk):
    fake = FakeAnthropic().error(400, "invalid_request_error", "output_config.format is not supported for this model")
    fake.reply(text('{"issues": []}'))
    res = compliance.check(close_output(pk), "close", "claude-haiku-5-5", "low", checker(fake), Settings())
    assert res.ok and res.issues == []
    body = fake.requests[1]["body"]
    assert "format" not in body["output_config"] and "只輸出一個 JSON" in body["system"]


def test_a_quote_that_is_not_word_for_word_still_counts():
    payload = [{"path": "sectors[0].sentences[0]", "text": "外資連三日買超半導體類股，類股仍有上漲空間。"}]

    def reply(quote: str):
        return FakeAnthropic().reply(json_text({"issues": [
            {"path": "sectors[0].sentences[0]", "category": "direction", "quote": quote}]})).client("k")

    for quote in ("類股仍有上漲空間…", "…類股仍有上漲空間", "類股 仍有上漲空間", "類股仍有上漲空間.", "完全不同的字"):
        msg = reply(quote).beta.messages.create(model="claude-haiku-5-5", max_tokens=10, messages=[])
        [issue] = compliance.parse(msg, payload)
        assert issue["path"] == "sectors[0].sentences[0]" and issue["category"] == "direction"
    msg = reply("類股仍有上漲空間").beta.messages.create(model="claude-haiku-5-5", max_tokens=10, messages=[])
    assert compliance.parse(msg, payload)[0]["quote"] == "類股仍有上漲空間"


def test_item_names_are_read_too(pk):
    out = close_output(pk)
    out["tonight"][0]["event"] = "台積電目標價上看 2,000 元"
    paths = [x["path"] for x in compliance.items(out, "close")]
    assert paths[:2] == ["title", "tonight[0].event"]
