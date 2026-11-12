"""Key discovery, round robin, failover (429 / 529 / overloaded / 401) and key-safe logging."""

from __future__ import annotations

import logging

import anthropic
import pytest

from forliosa.ai.keypool import DUMMY_KEY, KeyPool, NoKeyAvailable, build_pool, discover_keys
from tests.ai.conftest import KEYS
from tests.ai.fake_anthropic import FakeAnthropic, text


def test_discover_keys_numbered_any_case_ordered(tmp_path):
    env = {"Claude_API_KEY_2": "k2", "CLAUDE_API_KEY_1": " k1 ", "claude_api_key_10": "k10",
           "CLAUDE_API_KEY_3": "", "ANTHROPIC_API_KEY": "fallback", "OTHER": "x"}
    assert discover_keys(env, dotenv_path=None) == ["k1", "k2", "k10"]


def test_discover_keys_fallback_and_dedupe(tmp_path):
    assert discover_keys({"ANTHROPIC_API_KEY": "only"}, dotenv_path=None) == ["only"]
    assert discover_keys({}, dotenv_path=None) == []
    assert discover_keys({"CLAUDE_API_KEY_1": "same", "CLAUDE_API_KEY_2": "same"}, dotenv_path=None) == ["same"]


def test_discover_keys_reads_dotenv_env_wins(tmp_path):
    f = tmp_path / ".env"
    f.write_text("Claude_API_KEY_1=from-file\nCLAUDE_API_KEY_2=file-two\n")
    assert discover_keys({"CLAUDE_API_KEY_2": "from-env"}, dotenv_path=f) == ["from-file", "from-env"]


def test_dummy_key_when_enabled(monkeypatch, ai_env):
    for k in list(__import__("os").environ):
        if k.upper().startswith("CLAUDE_API_KEY_") or k == "ANTHROPIC_API_KEY":
            monkeypatch.delenv(k)
    monkeypatch.chdir(__import__("tempfile").mkdtemp())  # no .env here
    ai_env(AI_DEV_DUMMY_KEY="1")
    pool = build_pool()
    assert pool.size == 1 and pool.available
    assert pool.slots[0].client.api_key == DUMMY_KEY


def _pool(fake: FakeAnthropic, keys=KEYS, **kw) -> KeyPool:
    return KeyPool.from_keys(keys, client_factory=fake.client, sleep=lambda _s: None, **kw)


def _ask(client):
    return client.messages.create(model="claude-haiku-5-5", max_tokens=10, messages=[{"role": "user", "content": "hi"}])


def test_round_robin_per_request():
    fake = FakeAnthropic()
    pool = _pool(fake, keys=["a", "b", "c"])
    for _ in range(4):
        fake.reply(text("ok"))
        _msg, _idx = pool.call(_ask)
    assert fake.keys_used == ["a", "b", "c", "a"]


@pytest.mark.parametrize(("status", "etype"), [(429, "rate_limit_error"), (529, "overloaded_error"),
                                               (500, "api_error")])
def test_failover_and_cooldown(status, etype):
    fake = FakeAnthropic()
    now = [1000.0]
    pool = _pool(fake, clock=lambda: now[0], cooldown_seconds=60)
    fake.error(status, etype).reply(text("ok"))
    msg, idx = pool.call(_ask)
    assert msg.content[0].text == "ok" and idx == 2
    assert fake.keys_used == [KEYS[0], KEYS[1]]
    # key 1 is cooling down: the next request (which would start at key 2 anyway) and the one after both skip it
    fake.reply(text("a")).reply(text("b"))
    pool.call(_ask)
    pool.call(_ask)
    assert fake.keys_used[2:] == [KEYS[1], KEYS[1]]
    now[0] += 61  # cooled down: back in rotation
    fake.reply(text("c")).reply(text("d"))
    pool.call(_ask)
    pool.call(_ask)
    assert set(fake.keys_used[4:]) == {KEYS[0], KEYS[1]}


def test_401_disables_key_until_restart():
    fake = FakeAnthropic()
    pool = _pool(fake)
    fake.error(401, "authentication_error").reply(text("ok"))
    pool.call(_ask)
    assert pool.slots[0].disabled and not pool.slots[1].disabled
    for _ in range(3):
        fake.reply(text("ok"))
        pool.call(_ask)
    assert KEYS[0] not in fake.keys_used[2:]


def test_all_keys_rejected_raises_and_pool_unavailable():
    fake = FakeAnthropic()
    pool = _pool(fake)
    fake.error(401, "authentication_error").error(401, "authentication_error")
    with pytest.raises(anthropic.AuthenticationError):
        pool.call(_ask)
    assert not pool.available
    with pytest.raises(NoKeyAvailable):
        pool.call(_ask)


def test_non_failover_error_is_raised_immediately():
    fake = FakeAnthropic()
    pool = _pool(fake)
    fake.error(400, "invalid_request_error")
    with pytest.raises(anthropic.BadRequestError):
        pool.call(_ask)
    assert len(fake.requests) == 1


def test_single_key_retries_once():
    fake = FakeAnthropic()
    pool = _pool(fake, keys=["solo"])
    fake.error(529, "overloaded_error").reply(text("ok"))
    _msg, idx = pool.call(_ask)
    assert idx == 1 and fake.keys_used == ["solo", "solo"]


def test_logs_key_index_never_the_key(caplog):
    fake = FakeAnthropic()
    pool = _pool(fake)
    fake.error(429, "rate_limit_error").error(401, "authentication_error")
    with caplog.at_level(logging.WARNING, logger="forliosa.ai.keypool"), pytest.raises(anthropic.APIStatusError):
        pool.call(_ask)
    logs = caplog.text
    assert "#1" in logs and "#2" in logs
    assert all(k not in logs for k in KEYS)
