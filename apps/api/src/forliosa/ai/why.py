"""One-sentence AI explanation for ``/instruments/{symbol}/why`` (``AI_WHY_ENABLED``).

Only when the rules already say ``show`` (a real anomaly). The model searches the web (Taiwan location) and
writes one cited zh-TW sentence; the result is cached per symbol per trading day in ``ai_why_cache`` and shared
by every user. Any failure, an answer without citations, or ``NONE`` falls back to the rule template. By default
the sentence is generated in a background thread (the first request returns the rule template right away);
``AI_WHY_BLOCKING=1`` waits for it instead.
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from forliosa.ai import store
from forliosa.ai.keypool import KeyPool, get_key_pool
from forliosa.ai.pricing import CallUsage
from forliosa.ai.prompts import WHY_SYSTEM, why_question
from forliosa.ai.tools import server_tools
from forliosa.config import Settings, get_settings
from forliosa.db import session_factory
from forliosa.marketdata.service import MarketData
from forliosa.models import AiWhyCache
from forliosa.timeutil import TAIPEI, now_utc, today_taipei

log = logging.getLogger(__name__)

RETRY_FAILED_AFTER = timedelta(minutes=30)
MAX_SENTENCE_CHARS = 120
MAX_CONTINUATIONS = 3
_inflight: set[tuple[str, date]] = set()
_inflight_lock = threading.Lock()


def _trading_day(result: dict[str, Any]) -> date:
    as_of = result.get("as_of")
    if isinstance(as_of, str):
        try:
            return datetime.fromisoformat(as_of).astimezone(TAIPEI).date()
        except ValueError:
            pass
    return today_taipei()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=TAIPEI)


def _apply(out: dict[str, Any], row: AiWhyCache | None) -> dict[str, Any]:
    if row is not None and row.status == "ok" and row.text:
        return {**out, "headline": row.text, "ai": True, "citations": row.citations or []}
    return out


def enhance_why(db: Session, md: MarketData, result: dict[str, Any], user_id: str | None = None,
                pool: KeyPool | None = None, settings: Settings | None = None) -> dict[str, Any]:
    """``result`` is the rule-based ``why``; returns it with ``ai``, ``citations`` and ``rule_headline`` added
    (``headline`` replaced by the AI sentence when one is cached)."""
    settings = settings or get_settings()
    out = {**result, "ai": False, "citations": [], "rule_headline": result.get("headline")}
    if not settings.ai_why_enabled or not result.get("show"):
        return out
    try:
        pool = pool or get_key_pool()
        if not pool.available:
            return out
        sym, day = result["symbol"], _trading_day(result)
        row = db.get(AiWhyCache, (sym, day))
        if row is not None and (row.status != "failed" or now_utc() - _aware(row.created_at) < RETRY_FAILED_AFTER):
            return _apply(out, row)
        if settings.ai_why_blocking:
            generate(db, md, result, day, pool, settings, user_id)
            return _apply(out, db.get(AiWhyCache, (sym, day)))
        _start_background(md, result, day, pool, settings, user_id)
    except Exception:  # the rule template is always a valid answer
        log.exception("AI why for %s failed", result.get("symbol"))
        db.rollback()
    return out


def _start_background(md: MarketData, result: dict[str, Any], day: date, pool: KeyPool, settings: Settings,
                      user_id: str | None) -> None:
    key = (result["symbol"], day)
    with _inflight_lock:
        if key in _inflight:
            return
        _inflight.add(key)

    def work() -> None:
        try:
            with session_factory()() as db:
                generate(db, md, result, day, pool, settings, user_id)
        except Exception:  # pragma: no cover - logged; the next request retries after RETRY_FAILED_AFTER
            log.exception("background AI why for %s failed", key[0])
        finally:
            with _inflight_lock:
                _inflight.discard(key)

    threading.Thread(target=work, name=f"ai-why-{key[0]}", daemon=True).start()


def _citations(content: list[Any]) -> list[dict[str, Any]]:
    out, seen = [], set()
    for b in content:
        for c in getattr(b, "citations", None) or []:
            if getattr(c, "type", None) != "web_search_result_location" or c.url in seen:
                continue
            seen.add(c.url)
            out.append({"url": c.url, "title": c.title, "cited_text": c.cited_text})
    return out[:3]


def generate(db: Session, md: MarketData, result: dict[str, Any], day: date, pool: KeyPool, settings: Settings,
             user_id: str | None = None) -> AiWhyCache:
    """Ask the model (web search on) for the sentence and store the outcome (ok / empty / failed)."""
    sym = result["symbol"]
    info = md.instrument(sym)
    name = info.name if info else sym
    reasons = [r.get("text", "") for r in result.get("reasons") or []]
    model = store.model_for("why", settings)
    messages: list[dict[str, Any]] = [{"role": "user", "content": why_question(
        name, sym, info.market if info else "", day.isoformat(), reasons)}]
    params = {"model": model, "max_tokens": 2048, "system": WHY_SYSTEM,
              "tools": server_tools(settings, fetch=False, max_uses=3),
              "output_config": {"effort": settings.ai_effort_why}}
    status, text, cites = "failed", "", []
    content: list[Any] = []
    try:
        for _ in range(MAX_CONTINUATIONS):
            msg, key_index = pool.call(lambda c, m=messages: c.messages.create(messages=m, **params))
            store.record_usage(db, user_id=user_id, thread_id=None, feature="why", model=msg.model or model,
                               key_index=key_index, usage=CallUsage.from_sdk(msg.usage), stop_reason=msg.stop_reason)
            content.extend(msg.content)
            if msg.stop_reason != "pause_turn":
                break
            messages = [*messages, {"role": "assistant", "content": [b.to_dict(mode="json") for b in msg.content]}]
        if msg.stop_reason in ("end_turn", "stop_sequence"):
            text = "".join(b.text for b in content if getattr(b, "type", None) == "text").strip()
            cites = _citations(content)
            if not text or "NONE" in text.upper() or not cites:
                status, text = "empty", ""
            else:
                status = "ok"
                text = " ".join(text.split())[:MAX_SENTENCE_CHARS]
    except Exception:
        log.exception("AI why generation for %s failed", sym)
        db.rollback()
    row = db.get(AiWhyCache, (sym, day))
    if row is None:
        row = AiWhyCache(symbol=sym, date=day)
        db.add(row)
    row.status, row.text, row.citations, row.model, row.created_at = status, text, cites, model, now_utc()
    db.commit()
    return row
