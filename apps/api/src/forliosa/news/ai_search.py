"""AI web-search fallback for the 「新聞報導」 list (product owner 2026-11-12, decision 1).

Used by the news worker only for a symbol whose free sources gave fewer than ``NEWS_AI_MIN_ITEMS`` (3) headlines
in the last 7 days, at most once per ``NEWS_AI_INTERVAL_HOURS`` per symbol, and only while this (UTC) month's
``feature = "news"`` spend in ``ai_usage`` is below ``NEWS_AI_BUDGET_USD`` (US$30; the system pays, ``user_id`` is
NULL). One non-streaming ``messages.create`` through ``KeyPool.call`` with ``web_search`` only (no ``web_fetch``:
nothing is read from news sites or www.twse.com.tw) and the strict client tool ``report_news`` whose only output is
a list of URLs. **The model only selects**: each kept item's title, link and date come from the
``web_search_result`` block with that URL (compared like :func:`forliosa.ai.analyst._norm_url`); a URL that is not
one of the results, a quote / rating page (``analyst.is_article``) or a result without a readable date is dropped.
The caller then applies the same relevance filter, blocklist and de-duplication as every other source.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.ai import store
from forliosa.ai.analyst import (
    SearchResult,
    _get,
    _json,
    _norm_url,
    date_from_page_age,
    date_from_url,
    is_article,
    search_results,
)
from forliosa.ai.keypool import KeyPool
from forliosa.ai.pricing import CallUsage
from forliosa.ai.prompts import NEWS_NUDGE, NEWS_SYSTEM, NEWS_TOOL, NEWS_TOOL_NAME, news_question
from forliosa.ai.tools import exclude_tool, rejected_tool, server_tools
from forliosa.config import Settings
from forliosa.ids import new_id
from forliosa.models import AiUsage
from forliosa.news.sources import Query, RawItem
from forliosa.timeutil import TAIPEI

log = logging.getLogger(__name__)

FEATURE = "news"
MAX_CALLS = 3  # first call + a pause_turn continuation or one nudge
MAX_TOKENS = 3000
SEARCH_MAX_USES = 2
MAX_URLS = 10
# Upper estimate of one search (2 web searches = US$0.02 plus tokens): a search starts only when this much budget
# is left, so the month never ends far above the cap.
RESERVE_USD = Decimal("0.05")
# Never offered as news: quote / forum / aggregator pages and the exchange websites.
SEARCH_BLOCKED = ["goodinfo.tw", "wantgoo.com", "cmoney.tw", "pchome.com.tw", "tradingview.com", "investing.com",
                  "stockanalysis.com", "marketbeat.com", "tipranks.com", "www.twse.com.tw", "mis.twse.com.tw",
                  "mops.twse.com.tw", "ptt.cc", "dcard.tw", "youtube.com", "facebook.com"]


def month_spend(db: Session, now: datetime) -> Decimal:
    """This UTC month's estimated cost of ``feature = "news"`` calls (Anthropic bills by UTC month)."""
    start = store.utc_month_start(now)
    costs = db.scalars(select(AiUsage.cost_usd).where(AiUsage.feature == FEATURE, AiUsage.created_at >= start))
    return sum((Decimal(c or 0) for c in costs), Decimal(0))  # summed exactly (SQLite stores Money as text)


def budget_left(db: Session, settings: Settings, now: datetime) -> bool:
    budget = Decimal(str(settings.news_ai_budget_usd))
    return budget > 0 and month_spend(db, now) + RESERVE_USD <= budget


def search_tools(settings: Settings, blocked: list[str]) -> list[dict[str, Any]]:
    tools = server_tools(settings, fetch=False, max_uses=SEARCH_MAX_USES)
    for t in tools:
        if t.get("name") == "web_search" and "allowed_domains" not in t:
            t["blocked_domains"] = list(dict.fromkeys([*SEARCH_BLOCKED, *blocked]))[:100]
    return tools


def reported_urls(content: list[Any]) -> list[str] | None:
    """The ``report_news`` input (last call wins), or ``None`` when the model did not call it."""
    found: list[str] | None = None
    for b in content:
        if _get(b, "type") == "tool_use" and _get(b, "name") == NEWS_TOOL_NAME:
            inp = _json(_get(b, "input"))
            urls = _json(inp.get("urls")) if isinstance(inp, dict) else None
            found = [str(u) for u in urls if isinstance(u, str)] if isinstance(urls, list) else []
    return found


def result_time(r: SearchResult, now: datetime) -> tuple[datetime, bool] | None:
    """When the result was published: ``page_age`` with a time (aware or Taipei) -> exact; a date only (URL
    ``/2026/11/10/`` or ``page_age`` 「November 10, 2026」) -> that date, ``date_only``. ``None`` when unknown."""
    age = (r.page_age or "").strip()
    if age and "T" in age:
        try:
            dt = datetime.fromisoformat(age.replace("Z", "+00:00"))
            return (dt if dt.tzinfo else dt.replace(tzinfo=TAIPEI)).astimezone(UTC), False
        except ValueError:
            pass
    today = now.astimezone(TAIPEI).date()
    d: date | None = date_from_url(r.url) or date_from_page_age(r.page_age, today)
    if d is None:
        return None
    return datetime.combine(d, time(0, 0), TAIPEI).astimezone(UTC), True


def select_items(urls: list[str], results: list[SearchResult], q: Query, now: datetime) -> list[RawItem]:
    """The reported URLs that are search results, articles, and dated inside the query window."""
    by_url: dict[str, SearchResult] = {}
    for r in results:
        by_url.setdefault(_norm_url(r.url), r)
    out: list[RawItem] = []
    seen: set[str] = set()
    for u in urls[:MAX_URLS]:
        r = by_url.get(_norm_url(u))
        if r is None or _norm_url(r.url) in seen or not is_article(r.url) or not r.title.strip():
            continue
        when = result_time(r, now)
        if when is None:
            continue
        published, date_only = when
        if published > now + timedelta(days=1) or published < q.since - (timedelta(days=1) if date_only else
                                                                           timedelta(0)):
            continue
        seen.add(_norm_url(r.url))
        out.append(RawItem(title=r.title, url=r.url, published_at=min(published, now), date_only=date_only))
    return out


class AiSearch:
    """One gap-filling search for one symbol. ``record(slot, message)`` stores each call's usage."""

    key = "ai_search"
    label = "AI 搜尋"

    def __init__(self, pool: KeyPool, settings: Settings, costs: Any = None):
        self.pool = pool
        self.settings = settings
        self.costs = costs

    def run(self, q: Query, now: datetime, blocked: list[str], record: Callable[[int, Any], None]) -> list[RawItem]:
        settings = self.settings
        model = store.model_for(FEATURE, settings)
        today = now.astimezone(TAIPEI).date()
        messages: list[dict[str, Any]] = [{"role": "user", "content": news_question(
            q.name, q.code, q.english[0] if q.english else None, q.market, today.isoformat(),
            q.since.astimezone(TAIPEI).date().isoformat())}]
        params: dict[str, Any] = {"model": model, "max_tokens": MAX_TOKENS, "system": NEWS_SYSTEM,
                                  "tools": [*search_tools(settings, blocked), NEWS_TOOL]}
        if not any(t.get("name") == "web_search" for t in params["tools"]):
            return []
        content: list[Any] = []
        slot: int | None = None
        nudged = False
        urls: list[str] | None = None

        def ask(m: list[dict[str, Any]]) -> Callable[[Any], Any]:
            return lambda client: client.messages.with_raw_response.create(messages=m, **params)

        for _ in range(MAX_CALLS):
            try:
                raw, slot = self.pool.call(ask(messages), costs=self.costs if slot is None else None, only=slot)
            except anthropic.BadRequestError as exc:
                tool = rejected_tool(str(exc.api_message or exc), params["tools"])
                if tool is not None:
                    exclude_tool(tool, str(exc.api_message or exc))
                raise
            self.pool.observe(slot, raw.headers)
            msg = raw.parse()
            record(slot, msg)
            content.extend(msg.content)
            assistant = {"role": "assistant", "content": [b.to_dict(mode="json") for b in msg.content]}
            if msg.stop_reason == "pause_turn":
                messages = [*messages, assistant]
                continue
            urls = reported_urls(msg.content)
            if urls is not None or msg.stop_reason not in ("end_turn", "stop_sequence") or nudged:
                break
            nudged = True
            messages = [*messages, assistant, {"role": "user", "content": NEWS_NUDGE}]
        if not urls:
            return []
        return select_items(urls, search_results(content), q, now)


def new_generation_id() -> str:
    return new_id("nws")


def recorder(db: Session, generation_id: str, settings: Settings) -> Callable[[int, Any], None]:
    """Usage rows for a system-paid news search: ``user_id`` NULL, ``feature = "news"``."""
    model = store.model_for(FEATURE, settings)

    def record(slot: int, msg: Any) -> None:
        store.record_usage(db, user_id=None, thread_id=generation_id, feature=FEATURE, model=msg.model or model,
                           key_slot=slot, usage=CallUsage.from_sdk(msg.usage), stop_reason=msg.stop_reason)

    return record
