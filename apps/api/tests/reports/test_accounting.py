"""Booking report calls per model that ran (server-side fallbacks), the month and the blind test, budget tiers
(contract §4.2, §4.5)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal as D
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import select

from forliosa.ai import store
from forliosa.ai.pricing import CallUsage, estimate_cost
from forliosa.config import Settings
from forliosa.models import AiUsage
from forliosa.reports import accounting
from forliosa.reports import settings as rs


def it(kind, model, inp, out):
    return NS(type=kind, model=model, input_tokens=inp, output_tokens=out, cache_creation_input_tokens=0,
              cache_read_input_tokens=0)


def msg(usage, model="claude-opus-5-5", content=(), stop="end_turn"):
    return NS(usage=usage, model=model, content=list(content), stop_reason=stop)


def test_fallback_iterations_are_booked_per_model():
    """Opus 5.5 declined after some output, Opus 4.8 answered: two models, each at its own price; the top-level
    usage (only the serving attempt) is not added on top."""
    u = NS(input_tokens=1000, output_tokens=500, cache_creation_input_tokens=0, cache_read_input_tokens=0,
           server_tool_use=NS(web_search_requests=2, web_fetch_requests=0),
           iterations=[it("message", "claude-opus-5-5", 1200, 40),
                       it("fallback_message", "claude-opus-4-8", 1000, 500)])
    m = msg(u, model="claude-opus-4-8", content=[NS(type="fallback")])
    by = accounting.usage_by_model(m, "claude-opus-5-5")
    assert by["claude-opus-5-5"].input_tokens == 1200 and by["claude-opus-5-5"].output_tokens == 40
    assert by["claude-opus-4-8"].output_tokens == 500 and by["claude-opus-4-8"].web_search_requests == 2
    assert accounting.fallback_used(m)
    want = estimate_cost("claude-opus-5-5", by["claude-opus-5-5"]) + estimate_cost("claude-opus-4-8",
                                                                                  by["claude-opus-4-8"])
    assert accounting.cost_of(m, "claude-opus-5-5") == want


def test_an_iteration_without_a_model_is_the_requested_one_and_no_iterations_use_the_top_level():
    u = NS(input_tokens=10, output_tokens=5, cache_creation_input_tokens=0, cache_read_input_tokens=0,
           server_tool_use=None, iterations=[it("message", None, 10, 5), it("compaction", None, 3, 1)])
    assert accounting.usage_by_model(msg(u, model=None), "claude-sonnet-5-5")["claude-sonnet-5-5"].input_tokens == 13
    plain = NS(input_tokens=10, output_tokens=5, cache_creation_input_tokens=0, cache_read_input_tokens=0,
               server_tool_use=NS(web_search_requests=1, web_fetch_requests=0), iterations=None)
    by = accounting.usage_by_model(msg(plain, model="claude-sonnet-5-5"), "claude-sonnet-5-5")
    assert by == {"claude-sonnet-5-5": CallUsage(10, 5, 0, 0, 1, 0)}
    assert not accounting.fallback_used(msg(plain))


def test_book_call_writes_one_row_per_model_and_an_unknown_model_at_the_highest_price(db, caplog):
    u = NS(input_tokens=0, output_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=0,
           server_tool_use=None,
           iterations=[it("message", "claude-opus-5-5", 1000, 100),
                       it("fallback_message", "claude-mystery-9", 1000, 100)])
    with caplog.at_level(logging.ERROR):
        booked = accounting.book_call(db, msg(u, model="claude-mystery-9"), requested="claude-opus-5-5",
                                      feature="mreport_write", thread_id="mrr_1", key_slot=4)
    rows = {r.model: r for r in db.scalars(select(AiUsage))}
    assert set(rows) == {"claude-opus-5-5", "claude-mystery-9"}
    assert all(r.user_id is None and r.thread_id == "mrr_1" and r.key_slot == 4 and r.feature == "mreport_write"
               for r in rows.values())
    fable = estimate_cost("claude-fable-5-2", CallUsage(1000, 100))
    assert rows["claude-mystery-9"].cost_usd == fable  # never priced as Haiku
    assert "unknown model claude-mystery-9 charged at the highest known price" in caplog.text
    assert booked.cost_usd == rows["claude-opus-5-5"].cost_usd + fable
    assert set(booked.as_dict()) == {"cost_usd", "served_models", "usage"}


def add_usage(db, feature, cost, when=None):
    db.add(AiUsage(feature=feature, model="claude-opus-5-5", cost_usd=D(cost),
                   created_at=when or datetime(2026, 11, 10, tzinfo=UTC)))
    db.commit()


NOW = datetime(2026, 11, 17, 4, tzinfo=UTC)


def test_month_spend_counts_live_features_only(db):
    add_usage(db, "mreport_write", "10")
    add_usage(db, "mreport_gather", "2.5")
    add_usage(db, "mreport_trial", "7")
    add_usage(db, "chat", "1")
    add_usage(db, "mreport_check", "3", when=datetime(2026, 10, 20, tzinfo=UTC))  # last month
    assert accounting.month_spend(db, NOW) == D("12.5")
    assert accounting.trial_spend(db) == D("7")
    assert set(accounting.LIVE_FEATURES) | {accounting.TRIAL_FEATURE} <= set(store.FEATURES)
    assert all(len(f) <= 16 for f in store.FEATURES)  # ai_usage.feature is String(16)


@pytest.mark.parametrize(("spent", "tier"), [("0", "normal"), ("55.9", "normal"), ("56", "medium"),
                                             ("71.9", "medium"), ("72", "sonnet"), ("80", "data_only")])
def test_tiers_by_share_of_the_budget(spent, tier):
    assert accounting.tier_of_spend(D(spent), D(80)) == tier
    assert accounting.tier_of_spend(D(0), D(0)) == "data_only"  # a budget of 0: data-only editions


def test_tier_steps_down_while_the_attempt_would_not_fit(db):
    s = Settings(ai_mreport_monthly_budget_usd=80)
    add_usage(db, "mreport_write", "55", when=datetime(2026, 11, 10, tzinfo=UTC))
    # 55 + 2.0 (normal) fits under 80
    assert accounting.tier(db, "close", NOW, s) == "normal"
    add_usage(db, "mreport_write", "24", when=datetime(2026, 11, 11, tzinfo=UTC))  # 79: sonnet by share
    # 79 + 0.9 fits; the weekly's 1.5 does not -> data only
    assert accounting.tier(db, "close", NOW, s) == "sonnet"
    assert accounting.tier(db, "weekly", NOW, s) == "data_only"


def test_trial_cap(db):
    s = Settings(ai_mreport_trial_budget_usd=45)
    add_usage(db, "mreport_trial", "42")
    assert accounting.trial_fits(db, "close", "high", s)  # 42 + 2.0 <= 45
    assert not accounting.trial_fits(db, "weekly", "xhigh", s)  # 42 + 3.5 × 1.4 > 45


def test_writer_resolution_and_tiers(db):
    s = Settings()
    assert rs.default_writer("close", s) == rs.Writer("claude-opus-5-5", "high")
    cfg = rs.config(db, s)
    assert cfg.mode == "trial" and cfg.id == 1
    cfg.writers = {"close": {"model": "claude-sonnet-5-5", "effort": "medium"},
                   "weekly": {"model": "gpt", "effort": "x"}}
    db.commit()
    assert rs.chosen_writer(db, "close", s) == rs.Writer("claude-sonnet-5-5", "medium")
    assert rs.chosen_writer(db, "weekly", s) == rs.default_writer("weekly", s)  # an invalid pick is ignored
    w = rs.Writer("claude-opus-5-5", "xhigh")
    assert rs.apply_tier(w, "normal") == w and rs.apply_tier(w, "medium") == rs.Writer("claude-opus-5-5", "medium")
    assert rs.apply_tier(w, "sonnet") == rs.Writer("claude-sonnet-5-5", "high")
    assert rs.apply_tier(w, "data_only") is None
