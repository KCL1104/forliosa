"""One-sentence AI explanation for ``/instruments/{symbol}/why`` (``AI_WHY_ENABLED``).

Only when the rules already say ``show`` (a real anomaly). The model searches the web (Taiwan location) and
writes one cited zh-TW sentence; the result is cached per symbol per trading day in ``ai_why_cache`` and shared
by every user; a sentence also joins the chat's shared research of that session (``research.seed_from_why``). Any
failure, an answer without citations, or ``NONE`` falls back to the rule template. By default
the sentence is generated in a background thread (the first request returns the rule template right away);
``AI_WHY_BLOCKING=1`` waits for it instead. On by default (``AI_WHY_ENABLED``).

Key slot: the slot with the most headroom (``KeyPool.call`` with this month's per-slot costs); a ``pause_turn``
continuation stays on the slot that started it (its server-tool state belongs to that workspace). Rate-limit
headers are read through ``with_raw_response``. Without a usable ``web_search`` tool (turned off, or refused by
the API) no model call is made.

LangSearch first (產品負責人 2026-11-17, ``AI_LANGSEARCH_ENABLED`` with a key, Taiwan stocks only: ``from_langsearch``):
the stock's news since the day before the trading day goes to LangSearch (``tw_news.plan("why_move")``: ``"簡稱"``,
300 characters a result; the chat's daily cap and the key's stop state, ``langsearch.chat_search``), through the
measured filter (``tw_news.filter_items``), and the kept articles go to the model as citable search results
(「媒體，日期：摘錄」, the excerpt for this request only) with no web search, beside the official TAIEX close of
the trading day when there is one (and the stock's own move): without a search the model cannot look the index up,
so with no close of that day the prompt drops the comparison with the market (``WHY_SYSTEM_TW_NO_INDEX``). A cited
sentence is stored with its
citations' title lines (「媒體，11/16：標題」) as ``cited_text``, never the excerpt, so the page, the cache and the
chat's shared research (``research.seed_from_why``) hold only the outlet, date, title and link. Nothing kept,
LangSearch stopped or over its cap, ``NONE``, no citation, a failed call or a clause of ``WHY_PASTE_CHARS`` characters
pasted from an excerpt → the web search, unchanged.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import anthropic
from sqlalchemy.orm import Session

from forliosa.ai import research, store, tw_news
from forliosa.ai.keypool import KeyPool, get_key_pool
from forliosa.ai.pricing import CallUsage
from forliosa.ai.prompts import WHY_SYSTEM, WHY_SYSTEM_TW, WHY_SYSTEM_TW_NO_INDEX, why_question, why_question_tw
from forliosa.ai.tools import Citable, citable_content, exclude_tool, rejected_tool, server_tools
from forliosa.config import Settings, get_settings
from forliosa.db import session_factory
from forliosa.marketdata.base import InstrumentInfo
from forliosa.marketdata.service import MarketData
from forliosa.models import AiWhyCache
from forliosa.news import langsearch
from forliosa.timeutil import TAIPEI, now_utc, today_taipei

log = logging.getLogger(__name__)

RETRY_FAILED_AFTER = timedelta(minutes=30)
MAX_SENTENCE_CHARS = 120
MAX_CONTINUATIONS = 3
MAX_CITATIONS = 3
# A sentence that repeats this many characters of a LangSearch excerpt word for word shows the page's text: the web
# search writes it instead. Longer than the chat editor's 12 (``chat._MIN_COPY``): in one short sentence the stock's
# name with a figure and a date runs that long without being a paste.
WHY_PASTE_CHARS = 20
_inflight: set[tuple[str, date]] = set()
_inflight_lock = threading.Lock()


def _trading_day(result: dict[str, Any]) -> date:
    # The quote's own session (a US close: the New York date, while its Taipei as_of is the next morning)
    td = result.get("trade_date")
    if isinstance(td, str):
        try:
            return date.fromisoformat(td)
        except ValueError:
            pass
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
    if not settings.ai_why_enabled or not result.get("show") or not server_tools(settings, fetch=False):
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


def _move(pct: float) -> str:
    return "平盤" if abs(pct) < 0.00005 else f"{'漲' if pct > 0 else '跌'} {abs(pct) * 100:.2f}%"


def market_moves(db: Session, md: MarketData, info: InstrumentInfo, day: date) -> tuple[str | None, str | None]:
    """The stock's own move on ``day`` (its quote, when it is of that day) and the TAIEX's official close of ``day``
    (``index_daily``, as the market page and ``get_stock_overview`` read it), as the LangSearch prompt writes them
    (「跌 3.10%（11/17）」, 「跌 2.10%（11/17 收盤）」); None for what is not known. Best effort."""
    from forliosa.services import market_overview as mo
    from forliosa.services.instruments import change_base

    stock = taiex = None
    md_day = f"{day.month}/{day.day}"
    try:
        q = md.quote(info.symbol)
        base = change_base(q) if q is not None else None
        if q is not None and q.trade_date == day and q.price is not None and base:
            stock = f"{_move(float((q.price - base) / base))}（{md_day}）"
        found = mo._index_item("", mo.TAIEX, [r for r in mo._index_rows(db, md, mo.TAIEX) if r.date <= day], "")
        if found is not None and found[0]["date"] == day and found[0]["change_pct"] is not None:
            taiex = f"{_move(float(found[0]['change_pct']))}（{md_day} 收盤）"
    except Exception:  # the sentence is written without them (and without the market comparison)
        log.warning("AI why for %s: the day's moves not read", info.symbol, exc_info=True)
        db.rollback()
    return stock, taiex


def from_langsearch(db: Session, md: MarketData, info: InstrumentInfo, reasons: list[str], day: date, pool: KeyPool,
                    settings: Settings, user_id: str | None = None) -> tuple[str, list[dict[str, Any]]] | None:
    """The sentence and its citations from LangSearch (see the module docstring), or ``None`` for the web search.
    Best effort: never raises. The citations carry the title line as ``cited_text``; nothing of an excerpt is logged,
    stored or returned."""
    from forliosa.ai.chat import copied_spans

    now = now_utc()
    try:
        tier = tw_news.tier_for(db, md, info, settings)
        p = tw_news.plan("why_move", info, tier, 0, now)
    except ValueError:  # a name LangSearch cannot be asked with (digits only)
        return None
    except Exception:
        log.warning("AI why for %s: no LangSearch plan", info.symbol, exc_info=True)
        db.rollback()
        return None
    if p is None:
        return None
    # since the day before the trading day (a Friday move read on Monday), up to today
    first = min(day, now.astimezone(UTC).date()) - timedelta(days=1)
    fresh, start = tw_news.freshness_for(0, now, first)
    p = replace(p, freshness=fresh, window_start=start, days=(now.astimezone(UTC).date() - first).days)
    try:
        found = tw_news.fetch(db, md, settings, p, info, now=now, label="why")
    except langsearch.ChatUnavailable as exc:
        log.info("AI why for %s: LangSearch not asked (%s); web search", info.symbol, exc.reason)
        return None
    except Exception as exc:  # LangSearch is a first try: the web search stays
        log.warning("AI why for %s: LangSearch failed (%s); web search", info.symbol, type(exc).__name__)
        db.rollback()
        return None
    if not found.items:
        log.info("AI why for %s: LangSearch kept nothing (%s); web search", info.symbol, found.status)
        return None
    items = tw_news.blocks(found.items, now.astimezone(TAIPEI).date())
    lines = {it["url"]: it["safe_text"] for it in items}
    titles = {it["url"]: it["title"] for it in items}
    model = store.model_for("why", settings)
    stock, taiex = market_moves(db, md, info, day)
    question = why_question_tw(info.name, info.symbol, info.market, day.isoformat(), reasons, stock=stock, taiex=taiex)
    messages: list[dict[str, Any]] = [{"role": "user", "content": [
        *citable_content(Citable(items)), {"type": "text", "text": question}]}]
    params = {"model": model, "max_tokens": 2048, "system": WHY_SYSTEM_TW if taiex else WHY_SYSTEM_TW_NO_INDEX,
              "output_config": {"effort": settings.ai_effort_why}}
    try:
        raw, slot = pool.call(lambda client: client.messages.with_raw_response.create(messages=messages, **params),
                              costs=store.slot_month_costs(db))
        pool.observe(slot, raw.headers)
        msg = raw.parse()
        store.record_usage(db, user_id=user_id, thread_id=None, feature="why", model=msg.model or model,
                           key_slot=slot, usage=CallUsage.from_sdk(msg.usage), stop_reason=msg.stop_reason)
    except Exception as exc:  # the web search stays (its own call reports its own failure)
        log.warning("AI why for %s: the LangSearch call failed (%s); web search", info.symbol, type(exc).__name__)
        db.rollback()
        return None
    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
    cites: list[dict[str, Any]] = []
    for b in msg.content:
        for c in getattr(b, "citations", None) or []:
            url = getattr(c, "source", None)
            if getattr(c, "type", None) != "search_result_location" or url not in lines \
                    or any(x["url"] == url for x in cites):
                continue
            cites.append({"url": url, "title": titles[url], "cited_text": lines[url]})
    text = " ".join(text.split())
    usable = bool(msg.stop_reason in ("end_turn", "stop_sequence") and text and "NONE" not in text.upper() and cites)
    pasted = usable and any(z - a >= WHY_PASTE_CHARS
                            for a, z in copied_spans(text, [x.excerpt for x in found.items if x.excerpt]))
    if not usable or pasted:
        log.info("AI why for %s: no usable LangSearch sentence (stop=%s, %d citations%s); web search", info.symbol,
                 msg.stop_reason, len(cites), ", pasted" if pasted else "")
        return None
    return text[:MAX_SENTENCE_CHARS], cites[:MAX_CITATIONS]


def generate(db: Session, md: MarketData, result: dict[str, Any], day: date, pool: KeyPool, settings: Settings,
             user_id: str | None = None) -> AiWhyCache:
    """Ask the model for the sentence and store the outcome (ok / empty / failed): from LangSearch first for a
    Taiwan stock (``from_langsearch``), else — and when that gives no usable sentence — with web search, as before."""
    sym = result["symbol"]
    info = md.instrument(sym)
    reasons = [r.get("text", "") for r in result.get("reasons") or []]
    model = store.model_for("why", settings)
    found = from_langsearch(db, md, info, reasons, day, pool, settings, user_id) \
        if info is not None and tw_news.usable_for(settings, info) else None
    if found is not None:
        status, text, cites = "ok", found[0], found[1]
    else:
        status, text, cites = _from_web(db, info, sym, reasons, day, pool, settings, user_id)
    row = db.get(AiWhyCache, (sym, day))
    if row is None:
        row = AiWhyCache(symbol=sym, date=day)
        db.add(row)
    row.status, row.text, row.citations, row.model, row.created_at = status, text, cites, model, now_utc()
    db.commit()
    if status == "ok" and settings.ai_research_cache:  # the sentence and its sources join the chat's shared research
        try:
            research.seed_from_why(db, sym, day, text, cites, now_utc(), settings)
        except Exception:  # the sentence is stored; sharing it with the chat is a nicety
            log.warning("AI why for %s: shared research not seeded", sym, exc_info=True)
            db.rollback()
    return row


def _from_web(db: Session, info: InstrumentInfo | None, sym: str, reasons: list[str], day: date, pool: KeyPool,
              settings: Settings, user_id: str | None) -> tuple[str, str, list[dict[str, Any]]]:
    """The sentence with web search on: ``(status, text, citations)``, status ok / empty / failed."""
    name = info.name if info else sym
    model = store.model_for("why", settings)
    messages: list[dict[str, Any]] = [{"role": "user", "content": why_question(
        name, sym, info.market if info else "", day.isoformat(), reasons)}]
    params = {"model": model, "max_tokens": 2048, "system": WHY_SYSTEM,
              "tools": server_tools(settings, fetch=False, max_uses=3),
              "output_config": {"effort": settings.ai_effort_why}}
    status, text, cites = "failed", "", []
    content: list[Any] = []
    slot: int | None = None

    def ask(m: list[dict[str, Any]]) -> Callable[[Any], Any]:
        return lambda client: client.messages.with_raw_response.create(messages=m, **params)

    try:
        for _ in range(MAX_CONTINUATIONS):
            raw, slot = pool.call(ask(messages), costs=store.slot_month_costs(db) if slot is None else None,
                                  only=slot)
            pool.observe(slot, raw.headers)
            msg = raw.parse()
            store.record_usage(db, user_id=user_id, thread_id=None, feature="why", model=msg.model or model,
                               key_slot=slot, usage=CallUsage.from_sdk(msg.usage), stop_reason=msg.stop_reason)
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
    except Exception as exc:
        if isinstance(exc, anthropic.BadRequestError):
            tool = rejected_tool(str(exc.api_message or exc), params["tools"])
            if tool is not None:  # e.g. web search not allowed here: later calls skip the model (see enhance_why)
                exclude_tool(tool, str(exc.api_message or exc))
        log.exception("AI why generation for %s failed", sym)
        db.rollback()
    return status, text, cites
