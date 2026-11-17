"""Prices (2026-11-17 list) and the rule that an unknown model is never priced as a cheaper one."""

from __future__ import annotations

import logging
from decimal import Decimal as D

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.ai import pricing, store
from forliosa.ai.pricing import CallUsage, UnknownModelPrice, charge, estimate_cost, price_of
from forliosa.models import AiUsage

MTOK = CallUsage(input_tokens=1_000_000, output_tokens=1_000_000, cache_read_input_tokens=1_000_000)


@pytest.mark.parametrize(("model", "inp", "out", "read"), [
    ("claude-opus-5-5", "4", "20", "0.20"), ("claude-opus-5", "5", "25", "0.50"),
    ("claude-opus-4-8", "5", "25", "0.50"),
    ("claude-sonnet-5-5", "2", "10", "0.10"), ("claude-sonnet-5", "2", "10", "0.20"),
    ("claude-haiku-5-5", "0.10", "0.50", "0.01"), ("claude-fable-5-2", "8", "40", "0.20")])
def test_price_list(model, inp, out, read):
    p = price_of(model)
    assert (p.input, p.output, p.input * p.cache_read_mult) == (D(inp), D(out), D(read))


def test_haiku_long_prompts_and_cache_writes():
    long = CallUsage(input_tokens=150_000, output_tokens=1_000_000)
    assert estimate_cost("claude-haiku-5-5", long) == D("0.075") + D("2.50")
    writes = CallUsage(cache_creation_input_tokens=1_000_000)
    assert estimate_cost("claude-opus-5-5", writes) == D("5")  # 1.25 × input
    assert estimate_cost("claude-opus-5-5", CallUsage(web_search_requests=3)) == D("0.03")


def test_unknown_models_raise_and_are_charged_at_the_highest_price(caplog):
    with pytest.raises(UnknownModelPrice):
        price_of("claude-opus-9")
    assert not hasattr(pricing, "DEFAULT_PRICE")
    assert pricing.MAX_PRICE_MODEL == "claude-fable-5-2"
    with caplog.at_level(logging.ERROR):
        assert charge("claude-opus-9", MTOK) == estimate_cost("claude-fable-5-2", MTOK)
    assert "unknown model claude-opus-9 charged at the highest known price" in caplog.text
    assert charge("claude-haiku-5-5", MTOK) == estimate_cost("claude-haiku-5-5", MTOK)


def test_usage_records_never_price_an_unknown_model_as_haiku(engine):
    with Session(engine) as db:
        store.record_usage(db, user_id=None, thread_id=None, feature="chat", model="claude-new-model",
                           key_slot=1, usage=MTOK, stop_reason="end_turn")
        row = db.scalar(select(AiUsage))
        assert row.cost_usd == estimate_cost("claude-fable-5-2", MTOK)
        assert row.cost_usd > 10 * estimate_cost("claude-haiku-5-5", MTOK)  # Haiku would undercount it
