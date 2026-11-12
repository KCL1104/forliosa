"""Key slots: discovery (slot = n of CLAUDE_API_KEY_<n>), budgets, headroom-based selection, sticky routing,
failover (429 / 529 / overloaded / 401 / 403 / spend limits), rate-limit headers and key-safe logging."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

import anthropic
import pytest

from forliosa.ai.keypool import (
    DUMMY_KEY,
    KeyPool,
    KeysBusy,
    NoKeyAvailable,
    build_pool,
    classify_failure,
    discover_budgets,
    discover_keys,
    discover_slots,
)
from tests.ai.conftest import KEYS
from tests.ai.fake_anthropic import FakeAnthropic, rate_limit_headers, text

NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)


def test_discover_keys_numbered_any_case_ordered(tmp_path):
    env = {"Claude_API_KEY_2": "k2", "CLAUDE_API_KEY_1": " k1 ", "claude_api_key_10": "k10",
           "CLAUDE_API_KEY_3": "", "ANTHROPIC_API_KEY": "fallback", "OTHER": "x"}
    assert discover_keys(env, dotenv_path=None) == ["k1", "k2", "k10"]
    assert discover_slots(env, dotenv_path=None) == [(1, "k1"), (2, "k2"), (10, "k10")]  # slot = the env number


def test_discover_keys_fallback_and_dedupe(tmp_path):
    assert discover_keys({"ANTHROPIC_API_KEY": "only"}, dotenv_path=None) == ["only"]
    assert discover_slots({"ANTHROPIC_API_KEY": "only"}, dotenv_path=None) == [(0, "only")]
    assert discover_keys({}, dotenv_path=None) == []
    assert discover_keys({"CLAUDE_API_KEY_1": "same", "CLAUDE_API_KEY_2": "same"}, dotenv_path=None) == ["same"]
    assert discover_slots({"CLAUDE_API_KEY_2": "b", "Claude_Api_Key_3": "c"}, dotenv_path=None) == [(2, "b"), (3, "c")]


def test_discover_keys_reads_dotenv_env_wins(tmp_path):
    f = tmp_path / ".env"
    f.write_text("Claude_API_KEY_1=from-file\nCLAUDE_API_KEY_2=file-two\nai_key_2_monthly_budget_usd=7.5\n")
    assert discover_keys({"CLAUDE_API_KEY_2": "from-env"}, dotenv_path=f) == ["from-file", "from-env"]
    assert discover_budgets({}, dotenv_path=f) == {2: Decimal("7.5")}


def test_discover_budgets_any_case_and_invalid(caplog):
    env = {"AI_KEY_1_MONTHLY_BUDGET_USD": "50", "ai_key_3_monthly_budget_usd": " 12.5 ",
           "AI_KEY_2_MONTHLY_BUDGET_USD": "0", "AI_KEY_4_MONTHLY_BUDGET_USD": "lots", "AI_KEY_5_MONTHLY_BUDGET_USD": ""}
    with caplog.at_level(logging.WARNING):
        assert discover_budgets(env, dotenv_path=None) == {1: Decimal(50), 3: Decimal("12.5")}
    assert "AI_KEY_4_MONTHLY_BUDGET_USD" in caplog.text and "lots" not in caplog.text


def test_dummy_key_when_enabled(monkeypatch, ai_env):
    for k in list(__import__("os").environ):
        if k.upper().startswith("CLAUDE_API_KEY_") or k == "ANTHROPIC_API_KEY":
            monkeypatch.delenv(k)
    monkeypatch.chdir(__import__("tempfile").mkdtemp())  # no .env here
    ai_env(AI_DEV_DUMMY_KEY="1")
    pool = build_pool()
    assert pool.size == 1 and pool.available
    assert pool.slots[0].client.api_key == DUMMY_KEY and pool.slots[0].index == 0


def _pool(fake: FakeAnthropic, keys=KEYS, **kw) -> KeyPool:
    return KeyPool.from_keys(keys, client_factory=fake.client, sleep=lambda _s: None, wall=lambda: NOW, **kw)


def _ask(client):
    return client.messages.create(model="claude-haiku-5-5", max_tokens=10, messages=[{"role": "user", "content": "hi"}])


def test_equal_headroom_spreads_requests():
    fake = FakeAnthropic()
    pool = _pool(fake, keys=["a", "b", "c"])
    for _ in range(4):
        fake.reply(text("ok"))
        _msg, _idx = pool.call(_ask)
    assert fake.keys_used == ["a", "b", "c", "a"]  # ties broken by fewest assignments


def test_lowest_month_cost_first_then_headroom():
    fake = FakeAnthropic()
    pool = _pool(fake, keys=["a", "b", "c"])
    fake.reply(text("ok"))
    _msg, idx = pool.call(_ask, costs={1: Decimal("0.5"), 2: Decimal("0.2"), 3: Decimal("0.9")})
    assert idx == 2
    # the rate-limit headers of slot 2 show 10% left: slot 1 (more headroom) wins although it cost more
    pool.observe(2, rate_limit_headers(10, 100))
    assert [s.index for s in pool.ranked({1: Decimal("0.5"), 2: Decimal("0.2"), 3: Decimal("0.9")})] == [1, 3, 2]
    assert pool.headroom(pool.get(2)) == pytest.approx(0.1)


def test_rate_limit_at_zero_cools_until_reset():
    fake = FakeAnthropic()
    now = [1000.0]
    pool = _pool(fake, clock=lambda: now[0])
    pool.observe(1, rate_limit_headers(0, 50, reset="2026-11-12T06:00:30Z", kind="requests"))
    assert pool.state(pool.get(1)) == "cooling" and pool.wait_seconds(pool.get(1)) == pytest.approx(30)
    assert [s.index for s in pool.ranked()] == [2, 1]
    now[0] += 31
    assert pool.state(pool.get(1)) == "ok"


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
    assert pool.state(pool.get(1)) == "cooling" and pool.get(1).last_error.startswith(str(status))
    # key 1 is cooling down: the next two requests skip it
    fake.reply(text("a")).reply(text("b"))
    pool.call(_ask)
    pool.call(_ask)
    assert fake.keys_used[2:] == [KEYS[1], KEYS[1]]
    now[0] += 61  # cooled down: back in use (and preferred: fewer assignments)
    fake.reply(text("c"))
    pool.call(_ask)
    assert fake.keys_used[4] == KEYS[0]


def test_retry_after_is_a_hard_wait():
    fake = FakeAnthropic()
    pool = _pool(fake, clock=lambda: 1000.0)
    fake.error(429, "rate_limit_error", headers={"retry-after": "120"}).reply(text("ok"))
    pool.call(_ask)
    slot = pool.get(1)
    assert pool.wait_seconds(slot) == pytest.approx(120) and slot.cooldown_hard


@pytest.mark.parametrize(("status", "etype"), [(401, "authentication_error"), (403, "permission_error")])
def test_401_403_disable_key_until_restart(status, etype):
    fake = FakeAnthropic()
    pool = _pool(fake)
    fake.error(status, etype).reply(text("ok"))
    pool.call(_ask)
    assert pool.get(1).disabled and not pool.get(2).disabled and pool.state(pool.get(1)) == "disabled"
    for _ in range(3):
        fake.reply(text("ok"))
        pool.call(_ask)
    assert KEYS[0] not in fake.keys_used[2:]


def test_spend_limits_exhaust_the_slot():
    now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)

    def status_error(status, etype, message, code=None):
        fake = FakeAnthropic().error(status, etype, message, code=code)
        with pytest.raises(anthropic.APIStatusError) as info:
            _ask(fake.client("k"))
        return info.value

    cap = classify_failure(status_error(429, "rate_limit_error", "You have reached your API usage limits",
                                        "enforced_spend_limit_reached"), now)
    assert cap.kind == "exhaust" and cap.seconds == (datetime(2026, 12, 1, tzinfo=UTC) - now).total_seconds()
    ws = classify_failure(status_error(400, "invalid_request_error", "You have reached your specified workspace API "
                                       "usage limits. You will regain access on 2026-11-25 at 00:00 UTC."), now)
    assert ws.kind == "exhaust" and ws.seconds == 4.5 * 86400
    assert classify_failure(status_error(402, "billing_error", "billing"), now).kind == "exhaust"
    assert classify_failure(status_error(400, "invalid_request_error", "messages: bad"), now) is None

    fake = FakeAnthropic()
    pool = _pool(fake)
    fake.error(429, "rate_limit_error", "You have reached your API usage limits", code="enforced_spend_limit_reached")
    fake.reply(text("ok"))
    _msg, idx = pool.call(_ask)
    assert idx == 2 and pool.state(pool.get(1)) == "exhausted" and pool.ranked() == [pool.get(2)]


def test_budget_makes_a_slot_unusable():
    pool = KeyPool.from_keys(KEYS, client_factory=FakeAnthropic().client, budgets={1: Decimal(10)})
    costs = {1: Decimal("9.99")}
    assert pool.state(pool.get(1), costs[1]) == "ok" and pool.headroom(pool.get(1), costs[1]) < 0.01
    assert [s.index for s in pool.ranked(costs)] == [2, 1]  # almost no headroom left: last
    costs = {1: Decimal(10)}
    assert pool.state(pool.get(1), costs[1]) == "over_budget" and [s.index for s in pool.ranked(costs)] == [2]
    assert pool.route(1, costs).slot.index == 2  # a thread pinned to slot 1 moves


def test_route_is_sticky_and_waits_briefly():
    now = [1000.0]
    pool = KeyPool.from_keys(["a", "b", "c"], client_factory=FakeAnthropic().client, clock=lambda: now[0])
    costs = {1: Decimal(5), 2: Decimal(0), 3: Decimal(0)}
    assert pool.route(None, costs).slot.index == 2  # a new thread: most headroom / lowest cost
    assert pool.route(1, costs).slot.index == 1  # pinned: stays although slot 2 is cheaper
    pool.get(1).cooldown_until, pool.get(1).cooldown_hard = now[0] + 3, True
    r = pool.route(1, costs, max_wait=5)
    assert r.slot.index == 1 and r.wait == pytest.approx(3)  # recovers within the short wait
    pool.get(1).cooldown_until = now[0] + 30
    assert pool.route(1, costs, max_wait=5).slot.index in (2, 3)  # cooling too long: moves


def test_route_when_everything_is_cooling():
    now = [1000.0]
    pool = KeyPool.from_keys(["solo"], client_factory=FakeAnthropic().client, clock=lambda: now[0])
    slot = pool.get(1)
    slot.cooldown_until, slot.cooldown_hard = now[0] + 60, False
    assert pool.route(1, max_wait=5) == pool.route(None, max_wait=5)  # a guessed cooldown is probed
    assert pool.route(1, max_wait=5).wait == 0
    slot.cooldown_hard = True
    with pytest.raises(KeysBusy):
        pool.route(1, max_wait=5)
    slot.disabled = True
    with pytest.raises(NoKeyAvailable):
        pool.route(1)


def test_call_only_pins_one_slot():
    fake = FakeAnthropic()
    pool = _pool(fake, keys=["a", "b"])
    fake.error(529, "overloaded_error").reply(text("ok"))
    _msg, idx = pool.call(_ask, only=2)
    assert idx == 2 and fake.keys_used == ["b", "b"]  # never another workspace


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


def test_logs_and_status_never_contain_keys(caplog):
    fake = FakeAnthropic()
    pool = _pool(fake, budgets={2: Decimal(20), 3: Decimal(5)})
    fake.error(429, "rate_limit_error", headers={"anthropic-workspace-id": "wrkspc_one"})
    fake.error(401, "authentication_error")
    with caplog.at_level(logging.WARNING, logger="forliosa.ai.keypool"), pytest.raises(anthropic.APIStatusError):
        pool.call(_ask)
    logs = caplog.text
    assert "#1" in logs and "#2" in logs
    assert all(k not in logs for k in KEYS)
    status = pool.status({2: Decimal("1.5")}, {2: 3}, {1: 4})
    assert all(k not in repr(status) for k in KEYS)
    by_slot = {s["slot"]: s for s in status}
    assert sorted(by_slot) == [1, 2, 3]
    assert by_slot[1]["state"] == "cooling" and by_slot[1]["workspace_id"] == "wrkspc_one"
    assert by_slot[1]["threads"] == 4 and by_slot[1]["last_error"] == "429 rate_limit_error"
    assert by_slot[2] | {"retry_in_seconds": None} == {**by_slot[2], "state": "disabled", "month_cost_usd": 1.5,
                                                         "month_calls": 3, "monthly_budget_usd": 20.0,
                                                         "budget_remaining_usd": 18.5, "retry_in_seconds": None}
    assert by_slot[3] == {**by_slot[3], "configured": False, "state": "not_configured", "monthly_budget_usd": 5.0}
