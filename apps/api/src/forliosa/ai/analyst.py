"""Analyst views behind ``GET/POST /instruments/{symbol}/analyst-views``.

Third-party ratings and target prices that brokers / investment banks have already published, found by AI web
search and quoted with their source article and date (product owner, 2026-11-12; ``docs/research/analyst-ratings.md``).
Forliosa never adds its own target price, average, upside, ranking or buy/sell hint: the model's only output is
the ``report_analyst_views`` tool call (``prompts.ANALYST_TOOL``), and only its verified fields are shown.

Cache
-----
One entry per symbol per Taiwan trading day (``ai_analyst_views``; the last trading day on or before today in
Taipei), shared by every user and deleted 24 hours after it was created (expired rows are purged on every read
and by the worker's daily retention job). ``POST`` starts a generation when there is no entry (or the last one is
``unavailable`` and older than ``UNAVAILABLE_RETRY_AFTER``); an entry that is ``pending`` or ``ready`` is returned
without a new charge. A ``pending`` entry older than ``PENDING_TIMEOUT`` (the process died) reads as
``unavailable``. Stocks only: ETFs have no broker ratings, so the API answers 422 ``analyst_views_stocks_only``.

Charging
--------
A generation counts against the user who triggered it: one question toward ``AI_DAILY_MESSAGE_LIMIT`` (a
zero-token ``ai_usage`` row is written when it starts, so the count is immediate) and its tokens toward
``AI_MONTHLY_TOKEN_BUDGET`` (every call is an ``ai_usage`` row with ``feature = "analyst"`` and
``thread_id = generation_id``; see ``store.messages_today`` / ``store.month_usage``).

Generation
----------
Runs off the request thread (``spawn``). One non-streaming ``messages.create`` through ``KeyPool.call`` (slot with
the most headroom; ``pause_turn`` continuations and the one nudge stay on the same slot, whose workspace holds the
server-tool state), with ``web_search`` only — no ``web_fetch``, so nothing is fetched from www.twse.com.tw or
mis.twse.com.tw; rating aggregators are blocked (``AGGREGATOR_HOSTS``) — and the strict client tool
``report_analyst_views`` (its input is also accepted when the list or its items arrive JSON-encoded). A server
tool the API refuses is excluded for the process (``tools.exclude_tool``), like chat. A model that ends with text
gets one nudge; no report, a refusal or ``max_tokens`` → ``unavailable``. An *empty* report while the article
results carry rating headlines (目標價, price target …) is not claimed as "nothing found": also ``unavailable``.

Grounding (``verify``): an item is kept only when its URL is one of the ``web_search_result`` URLs the model
actually received in this generation (compared without scheme, ``www.``, trailing slash, fragment or
percent-encoding; the shown URL and title are the search result's own), the page is an article (not an aggregator
or quote page), and the article date can be read from that result's URL or ``page_age`` metadata (the shown date
is that article date, not the model's). Items older than ``MAX_AGE_DAYS``, without a named institution, with
neither rating nor target price, or with a target price in another currency are dropped. Numbers are passed
through as written — never converted, averaged or compared. Newest first, one per institution, at most
``MAX_ITEMS``.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

import anthropic
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from forliosa.ai import store
from forliosa.ai.keypool import KeyPool, get_key_pool
from forliosa.ai.pricing import CallUsage
from forliosa.ai.prompts import (
    ANALYST_DISCLAIMER,
    ANALYST_NUDGE,
    ANALYST_SYSTEM,
    ANALYST_TOOL,
    ANALYST_TOOL_NAME,
    analyst_question,
)
from forliosa.ai.tools import exclude_tool, rejected_tool, server_tools
from forliosa.api.errors import ApiError, not_found
from forliosa.config import Settings, get_settings
from forliosa.db import session_factory
from forliosa.ids import new_id
from forliosa.marketdata.base import InstrumentInfo
from forliosa.marketdata.service import MarketData
from forliosa.models import AiAnalystViews, User
from forliosa.timeutil import TAIPEI, iso_taipei, last_tw_trading_day, now_utc

log = logging.getLogger(__name__)

MAX_ITEMS = 5
MAX_AGE_DAYS = 90
TTL = timedelta(hours=24)
PENDING_TIMEOUT = timedelta(minutes=5)
UNAVAILABLE_RETRY_AFTER = timedelta(minutes=10)
MAX_CALLS = 4  # first call + pause_turn continuations + one nudge
MAX_TOKENS = 6000
MAX_INSTITUTION_CHARS = 40
MAX_RATING_CHARS = 30
MAX_TITLE_CHARS = 200
GENERIC_INSTITUTIONS = frozenset({  # compared without spaces, case-folded
    "法人", "外資", "外資法人", "外資圈", "投信", "投顧", "券商", "分析師", "市場", "研究機構", "機構", "法人圈",
    "analyst", "analysts", "wallstreet", "thestreet", "brokers", "consensus",
})
# Not articles: rating aggregators (their rating data is their licensed product, docs/research/analyst-ratings.md)
# and quote pages. Blocked in the search tool and dropped by ``verify``.
AGGREGATOR_HOSTS = ("tipranks.com", "marketbeat.com", "stockanalysis.com", "tradingview.com", "goodinfo.tw",
                    "wantgoo.com", "cmoney.tw")
QUOTE_PATHS = {"tw.stock.yahoo.com": "/quote", "finance.yahoo.com": "/quote", "cnyes.com": "/twstock"}
NOTE_OFF = "法人觀點的 AI 網路搜尋目前沒有開啟。"


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    page_age: str | None


@dataclass(frozen=True)
class Dropped:
    candidate: dict[str, Any]
    reason: str  # url_not_in_results | not_article | date_unverified | too_old | future | unnamed | empty | currency
    #              | duplicate


# -- time and cache --------------------------------------------------------------------------------------------
def trading_day(now: datetime) -> date:
    """The cache key: the last Taiwan trading day on or before ``now`` (Taipei)."""
    return last_tw_trading_day(now.astimezone(TAIPEI).date())


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def purge_expired(db: Session, now: datetime | None = None) -> int:
    """Delete entries past ``expires_at`` (24 h after creation). Returns how many were deleted."""
    result = db.execute(delete(AiAnalystViews).where(AiAnalystViews.expires_at <= (now or now_utc())))
    db.commit()
    return result.rowcount or 0


def resolve_stock(md: MarketData, symbol: str) -> InstrumentInfo:
    info = md.instrument(symbol)
    if info is None:
        raise not_found("找不到商品")
    if info.type != "stock":
        raise ApiError(422, "analyst_views_stocks_only", "法人觀點只提供個股；ETF 沒有個別機構的評等與目標價。")
    return info


def _current(db: Session, symbol: str, now: datetime) -> AiAnalystViews | None:
    purge_expired(db, now)
    row = db.get(AiAnalystViews, (symbol, trading_day(now)))
    if row is not None and row.status == "pending" and now - _aware(row.created_at) > PENDING_TIMEOUT:
        log.warning("analyst views for %s: generation %s never finished; marked unavailable", symbol,
                    row.generation_id)
        row.status, row.notes, row.finished_at = "unavailable", [], now
        db.commit()
    return row


def _retry_open(row: AiAnalystViews, now: datetime) -> bool:
    """An ``unavailable`` entry may be searched again ``UNAVAILABLE_RETRY_AFTER`` after it failed."""
    finished = _aware(row.finished_at) or now
    return row.status == "unavailable" and now - finished >= UNAVAILABLE_RETRY_AFTER


def view(row: AiAnalystViews | None, symbol: str) -> dict[str, Any]:
    """The contract shape (``docs/api-contract.md`` 法人觀點)."""
    if row is None:
        return {"status": "none", "symbol": symbol, "as_of": None, "expires_at": None, "items": [],
                "disclaimer": ANALYST_DISCLAIMER, "notes": []}
    ready = row.status == "ready"
    finished = _aware(row.finished_at)
    notes = list(row.notes or [])
    if row.status == "unavailable" and finished:
        notes.append(f"{(finished + UNAVAILABLE_RETRY_AFTER).astimezone(TAIPEI):%H:%M} 之後可以再查一次。")
    return {"status": row.status, "symbol": row.symbol,
            "as_of": iso_taipei(finished) if ready and finished else None,
            "expires_at": iso_taipei(_aware(row.expires_at)), "items": list(row.items or []) if ready else [],
            "disclaimer": ANALYST_DISCLAIMER, "notes": notes}


def read(db: Session, md: MarketData, symbol: str, now: datetime | None = None) -> dict[str, Any]:
    """``GET``: today's shared entry, or ``status: none`` (also once a failed search may be retried, so the page
    offers the search again)."""
    info = resolve_stock(md, symbol)
    now = now or now_utc()
    row = _current(db, info.symbol, now)
    return view(None if row is not None and _retry_open(row, now) else row, info.symbol)


# -- starting a generation -------------------------------------------------------------------------------------
Job = Callable[[], None]


def spawn(job: Job, name: str) -> None:
    """Run a generation off the request thread (tests replace this to run inline)."""
    threading.Thread(target=job, name=name, daemon=True).start()


def request(db: Session, user: User, md: MarketData, symbol: str, *, pool: KeyPool | None = None,
            settings: Settings | None = None, now: datetime | None = None) -> tuple[dict[str, Any], Job | None]:
    """``POST``: today's entry when it is pending / ready (no charge), else start a generation charged to ``user``.
    Returns the response and the job to run in the background (``None`` when nothing was started)."""
    settings = settings or get_settings()
    now = now or now_utc()
    info = resolve_stock(md, symbol)
    row = _current(db, info.symbol, now)
    if row is not None and not _retry_open(row, now):  # pending, ready, or failed moments ago: shared, no charge
        return view(row, info.symbol), None
    if not settings.ai_analyst_enabled or not settings.ai_web_search or not server_tools(settings, fetch=False):
        return {**view(None, info.symbol), "status": "unavailable", "notes": [NOTE_OFF]}, None
    pool = pool or get_key_pool()
    if not pool.available:
        raise ApiError(503, "ai_unavailable", "AI 功能尚未設定（沒有可用的 API 金鑰）")
    if not pool.ranked(store.slot_month_costs(db)):
        raise ApiError(503, "ai_unavailable", "AI 服務暫時無法使用（API 額度已用完），請稍後再試。")
    store.check_quota(db, user, settings)

    day, gen = trading_day(now), new_id("anv")
    fields = {"status": "pending", "items": [], "notes": [], "model": store.model_for("analyst", settings),
              "generation_id": gen, "requested_by": user.id, "created_at": now, "finished_at": None,
              "expires_at": now + TTL}
    try:
        if row is None:
            db.add(AiAnalystViews(symbol=info.symbol, trading_day=day, **fields))
            db.commit()
        else:  # retry after "unavailable": only if nobody else restarted it meanwhile
            claimed = db.execute(update(AiAnalystViews).where(
                AiAnalystViews.symbol == info.symbol, AiAnalystViews.trading_day == day,
                AiAnalystViews.generation_id == row.generation_id).values(**fields)).rowcount
            db.commit()
            if not claimed:
                db.expire_all()
                return view(db.get(AiAnalystViews, (info.symbol, day)), info.symbol), None
    except IntegrityError:  # another request created today's entry first: share it
        db.rollback()
        return view(db.get(AiAnalystViews, (info.symbol, day)), info.symbol), None
    # The search counts as one question right away (its model calls add their tokens later).
    store.record_usage(db, user_id=user.id, thread_id=gen, feature="analyst", model=fields["model"], key_slot=None,
                       usage=CallUsage(), stop_reason="started")
    db.expire_all()
    out = view(db.get(AiAnalystViews, (info.symbol, day)), info.symbol)
    user_id, chosen = user.id, pool

    def job() -> None:
        try:
            with session_factory()() as sdb:
                generate(sdb, md, info, day, gen, chosen, settings, user_id)
        except Exception:  # pragma: no cover - generate() records its own failures
            log.exception("analyst views generation %s for %s failed", gen, info.symbol)

    return out, job


# -- the model call --------------------------------------------------------------------------------------------
def _get(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def search_results(content: list[Any]) -> list[SearchResult]:
    """Every ``web_search_result`` the model received (error results are skipped)."""
    out: list[SearchResult] = []
    for b in content:
        if _get(b, "type") != "web_search_tool_result":
            continue
        results = _get(b, "content")
        if not isinstance(results, list):
            continue
        for r in results:
            url = _get(r, "url")
            if url:
                out.append(SearchResult(str(url), str(_get(r, "title") or ""), _get(r, "page_age")))
    return out


def _json(value: Any) -> Any:
    """A value the model may have sent JSON-encoded (``"[{…}]"`` instead of a list): decoded when it parses."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def reported_items(content: list[Any]) -> list[dict[str, Any]] | None:
    """The ``report_analyst_views`` input (last call wins), or ``None`` when the model did not call it. Tolerates
    the list, or each item, arriving as a JSON string (parsed with ``json.loads``, never by pattern matching)."""
    found: list[dict[str, Any]] | None = None
    for b in content:
        if _get(b, "type") == "tool_use" and _get(b, "name") == ANALYST_TOOL_NAME:
            inp = _json(_get(b, "input"))
            items = _json(inp.get("items")) if isinstance(inp, dict) else None
            if isinstance(items, dict):  # a single item
                items = [items]
            found = [d for d in (_json(i) for i in items) if isinstance(d, dict)] if isinstance(items, list) else []
            if isinstance(items, list) and len(found) < len(items):
                log.warning("analyst views: %d reported items were not objects", len(items) - len(found))
            elif not isinstance(items, list):
                log.warning("analyst views: reported items had an unexpected shape (%s)", type(items).__name__)
    return found


def raw_reports(content: list[Any]) -> list[str]:
    """The raw ``report_analyst_views`` inputs (diagnostics for the live smoke)."""
    return [json.dumps(_get(b, "input"), ensure_ascii=False, default=str) for b in content
            if _get(b, "type") == "tool_use" and _get(b, "name") == ANALYST_TOOL_NAME]


_RATING_HEADLINE = re.compile(r"目標價|評等|評級|price target|upgrade|downgrade|overweight|outperform|"
                              r"underweight|underperform", re.IGNORECASE)


def rating_headlines(results: list[SearchResult]) -> int:
    """How many article results have a rating / target-price headline (a sanity check on an empty report)."""
    return sum(1 for r in results if is_article(r.url) and _RATING_HEADLINE.search(r.title or ""))


def _transcript(content: list[Any]) -> list[str]:
    out = []
    for b in content:
        t = _get(b, "type")
        body = _get(b, "thinking") if t == "thinking" else _get(b, "text") if t == "text" else None
        if body and str(body).strip():
            out.append(f"{t}: {str(body).strip()}")
    return out + [f"report: {r}" for r in raw_reports(content)]


def _queries(content: list[Any]) -> list[str]:
    out = []
    for b in content:
        inp = _get(b, "input") if _get(b, "type") == "server_tool_use" else None
        if isinstance(inp, dict) and inp.get("query"):
            out.append(str(inp["query"]))
    return out


@dataclass
class Outcome:
    status: str  # ready | unavailable
    items: list[dict[str, Any]]
    dropped: list[Dropped]
    candidates: list[dict[str, Any]]
    results: list[SearchResult]
    usage: CallUsage
    calls: int
    queries: list[str]  # what the model searched for (diagnostics: the live smoke prints it)
    stop_reason: str | None
    transcript: list[str]  # thinking summaries (when requested), stray text and the raw report (diagnostics)


def search_tools(settings: Settings) -> list[dict[str, Any]]:
    """``web_search`` (no ``web_fetch``) with rating aggregators blocked, unless an allow-list is configured
    (the API takes one or the other)."""
    tools = server_tools(settings, fetch=False, max_uses=settings.ai_analyst_search_max_uses)
    for t in tools:
        if t.get("name") == "web_search" and "allowed_domains" not in t:
            t["blocked_domains"] = list(AGGREGATOR_HOSTS)
    return tools


def run_model(info: InstrumentInfo, today: date, generation_id: str, pool: KeyPool, settings: Settings,
              record: Callable[[int, Any], None], costs: Any = None, thinking_display: str | None = None) -> Outcome:
    """Ask the model (web search + ``report_analyst_views``), then verify. ``record(slot, message)`` stores the
    usage of every call. Raises on API errors (the caller marks the entry unavailable). ``thinking_display``
    (``"summarized"``) is only for the live smoke's diagnostics."""
    model = store.model_for("analyst", settings)
    since = today - timedelta(days=MAX_AGE_DAYS)
    messages: list[dict[str, Any]] = [{"role": "user", "content": analyst_question(
        info.name, info.symbol, info.market, info.currency, today.isoformat(), since.isoformat())}]
    params: dict[str, Any] = {
        "model": model, "max_tokens": MAX_TOKENS, "system": ANALYST_SYSTEM,
        "tools": [*search_tools(settings), ANALYST_TOOL],
        "output_config": {"effort": settings.ai_effort_analyst},
    }
    if thinking_display:
        params["thinking"] = {"type": "adaptive", "display": thinking_display}
    content: list[Any] = []
    usage = CallUsage()
    slot: int | None = None
    nudged = False
    calls = 0
    reported: list[dict[str, Any]] | None = None
    stop: str | None = None

    def ask(m: list[dict[str, Any]]) -> Callable[[Any], Any]:
        return lambda client: client.messages.with_raw_response.create(messages=m, **params)

    while calls < MAX_CALLS:
        try:
            raw, slot = pool.call(ask(messages), costs=costs if slot is None else None, only=slot)
        except anthropic.BadRequestError as exc:
            tool = rejected_tool(str(exc.api_message or exc), params["tools"])
            if tool is not None:  # e.g. web search not allowed here: later requests answer "unavailable" at once
                exclude_tool(tool, str(exc.api_message or exc))
            raise
        calls += 1
        pool.observe(slot, raw.headers)
        msg = raw.parse()
        record(slot, msg)
        usage.add(CallUsage.from_sdk(msg.usage))
        content.extend(msg.content)
        stop = msg.stop_reason
        assistant = {"role": "assistant", "content": [b.to_dict(mode="json") for b in msg.content]}
        if stop == "pause_turn":  # the server resumes from the trailing server_tool_use
            messages = [*messages, assistant]
            continue
        reported = reported_items(msg.content)
        if reported is not None or stop not in ("end_turn", "stop_sequence") or nudged:
            break
        nudged = True  # ended with text only: ask once for the tool call
        messages = [*messages, assistant, {"role": "user", "content": ANALYST_NUDGE}]
    results = search_results(content)
    if reported == [] and rating_headlines(results):
        # "Nothing found" while the results the model read carry rating headlines: do not claim there are no
        # reports — answer "unavailable" (retried later) instead of an empty "ready".
        log.warning("analyst views %s for %s: empty report although %d results have rating headlines",
                    generation_id, info.symbol, rating_headlines(results))
        reported = None
    if reported is None or stop in ("refusal", "max_tokens"):
        log.warning("analyst views %s for %s: no usable report (stop=%s)", generation_id, info.symbol, stop)
        return Outcome("unavailable", [], [], reported or [], results, usage, calls, _queries(content), stop,
                       _transcript(content))
    items, dropped = verify(reported, results, info, today)
    return Outcome("ready", items, dropped, reported, results, usage, calls, _queries(content), stop,
                   _transcript(content))


def generate(db: Session, md: MarketData, info: InstrumentInfo, day: date, generation_id: str, pool: KeyPool,
             settings: Settings, user_id: str | None) -> AiAnalystViews | None:
    """Run one generation and store its outcome on today's entry (unless a newer generation replaced it)."""
    model = store.model_for("analyst", settings)

    def record(slot: int, msg: Any) -> None:
        store.record_usage(db, user_id=user_id, thread_id=generation_id, feature="analyst", model=msg.model or model,
                           key_slot=slot, usage=CallUsage.from_sdk(msg.usage), stop_reason=msg.stop_reason)

    today = now_utc().astimezone(TAIPEI).date()
    try:
        outcome = run_model(info, today, generation_id, pool, settings, record, store.slot_month_costs(db))
        status, items, notes = outcome.status, outcome.items, []
        if outcome.dropped:
            log.info("analyst views %s for %s: kept %d, dropped %s", generation_id, info.symbol, len(items),
                     ", ".join(d.reason for d in outcome.dropped))
    except Exception:
        log.exception("analyst views generation %s for %s failed", generation_id, info.symbol)
        db.rollback()
        status, items, notes = "unavailable", [], []
    db.execute(update(AiAnalystViews).where(
        AiAnalystViews.symbol == info.symbol, AiAnalystViews.trading_day == day,
        AiAnalystViews.generation_id == generation_id).values(
        status=status, items=items, notes=notes, finished_at=now_utc()))
    db.commit()
    return db.get(AiAnalystViews, (info.symbol, day))


# -- grounding -------------------------------------------------------------------------------------------------
_URL_DATE = re.compile(r"(?<!\d)(20\d{2})[-/_.]?(0[1-9]|1[0-2])[-/_.]?(0[1-9]|[12]\d|3[01])")
_RELATIVE = re.compile(r"(\d+)\s*(minute|hour|day|week|month|year)s?\s+ago", re.IGNORECASE)
_CJK_DATE = re.compile(r"(20\d{2})\s*[年/.-]\s*(\d{1,2})\s*[月/.-]\s*(\d{1,2})")
_PAGE_AGE_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y")


def _date(y: str | int, m: str | int, d: str | int) -> date | None:
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def date_from_url(url: str) -> date | None:
    """A publication date written in the URL path (``/2026/11/10/``, ``/20261110…``, ``2026-11-10``)."""
    path = urlsplit(url).path
    for m in _URL_DATE.finditer(path):
        d = _date(*m.groups())
        if d is not None:
            return d
    return None


def date_from_page_age(page_age: str | None, today: date) -> date | None:
    """The search result's ``page_age``: ISO date / datetime, ``November 10, 2026``, ``2026年11月10日`` or
    ``3 days ago`` (relative to ``today``)."""
    s = (page_age or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(TAIPEI).date() if dt.tzinfo else dt.date()
    except ValueError:
        pass
    m = _CJK_DATE.search(s)
    if m:
        return _date(*m.groups())
    for fmt in _PAGE_AGE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    m = _RELATIVE.search(s)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        days = {"minute": 0, "hour": 0, "day": n, "week": 7 * n, "month": 30 * n, "year": 365 * n}[unit]
        return today - timedelta(days=days)
    return None


def _norm_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    host = (parts.hostname or "").lower().removeprefix("www.")
    return urlunsplit(("https", host, unquote(parts.path).rstrip("/"), unquote(parts.query), ""))


def is_article(url: str) -> bool:
    """False for rating aggregators and quote pages (``AGGREGATOR_HOSTS``, ``QUOTE_PATHS``)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    if any(host == h or host.endswith("." + h) for h in AGGREGATOR_HOSTS):
        return False
    prefix = QUOTE_PATHS.get(host)
    return not (prefix and parts.path.lower().startswith(prefix))


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", "", name).casefold()


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    s = " ".join(value.split())
    return s if s and len(s) <= limit else None


def _price(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    v = float(value)
    return v if math.isfinite(v) and v > 0 else None


def verify(candidates: list[dict[str, Any]], results: list[SearchResult], info: InstrumentInfo,
           today: date) -> tuple[list[dict[str, Any]], list[Dropped]]:
    """Keep the candidates that the search results support (see the module docstring). Returns the items in the
    contract shape (newest first, one per institution, at most ``MAX_ITEMS``) and the dropped candidates."""
    by_url: dict[str, SearchResult] = {}
    for r in results:
        by_url.setdefault(_norm_url(r.url), r)
    oldest = today - timedelta(days=MAX_AGE_DAYS)
    kept: list[dict[str, Any]] = []
    dropped: list[Dropped] = []
    for c in candidates:
        result = by_url.get(_norm_url(str(c.get("url") or "")))
        if result is None:
            dropped.append(Dropped(c, "url_not_in_results"))
            continue
        if not is_article(result.url):
            dropped.append(Dropped(c, "not_article"))
            continue
        published = date_from_url(result.url) or date_from_page_age(result.page_age, today)
        if published is None:
            dropped.append(Dropped(c, "date_unverified"))
            continue
        if published > today + timedelta(days=1):
            dropped.append(Dropped(c, "future"))
            continue
        if published < oldest:
            dropped.append(Dropped(c, "too_old"))
            continue
        institution = _text(c.get("institution"), MAX_INSTITUTION_CHARS)
        if institution is None or _norm_name(institution) in GENERIC_INSTITUTIONS:
            dropped.append(Dropped(c, "unnamed"))
            continue
        rating = _text(c.get("rating_text"), MAX_RATING_CHARS)
        target = _price(c.get("target_price"))
        if target is not None and c.get("currency") != info.currency:
            dropped.append(Dropped(c, "currency"))  # e.g. the TSM ADR's USD target listed for 2330.TW
            continue
        if rating is None and target is None:
            dropped.append(Dropped(c, "empty"))
            continue
        action = c.get("action") if c.get("action") in ("調升", "調降", "維持", "首評") else ""
        kept.append({"institution": institution, "action": action, "rating_text": rating, "target_price": target,
                     "currency": info.currency, "date": published.isoformat(),
                     "source_title": " ".join(result.title.split())[:MAX_TITLE_CHARS] or _norm_url(result.url),
                     "url": result.url})
    kept.sort(key=lambda i: i["date"], reverse=True)  # stable: the model's order within a day
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in kept:
        key = _norm_name(item["institution"])
        if key in seen:
            dropped.append(Dropped(item, "duplicate"))
            continue
        seen.add(key)
        items.append(item)
    return items[:MAX_ITEMS], dropped

