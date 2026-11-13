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
gets one nudge; no report, a refusal or ``max_tokens`` → ``unavailable``. "Nothing found" (``ready`` with no
items) is only claimed when nothing points the other way: when no item survives ``verify`` while the article
results carry a rating headline about *this* stock (目標價, price target … with its name, code, ticker or alias in
the title, not verifiably older than ``MAX_AGE_DAYS``), or while a candidate was dropped only because its URL or
date could not be checked (``UNSURE_DROPS``), the entry is ``unavailable`` (retried after 10 minutes).

Grounding (``verify``): an item is kept only when its URL is one of the ``web_search_result`` URLs the model
actually received in this generation (compared without scheme, ``www.``, trailing slash, fragment or
percent-encoding; the shown URL and title are the search result's own), the page is an article (not an aggregator,
quote, rating or forecast page: ``is_article``), and the article date can be read from that result's URL or
``page_age`` metadata (the shown date is that article date, not the model's). Items older than ``MAX_AGE_DAYS``,
without a named institution (「美系外資」「外資券商」「Wall Street analysts」 are not names: ``institution_key``),
with neither rating nor target price, or with a target price in another currency are dropped; a target price far
from the last real price (``TARGET_RATIO_MIN``–``TARGET_RATIO_MAX``, an internal filter that is never shown) is
treated as another currency too. Numbers are passed through as written — never converted, averaged or compared.
Newest first, one per institution (大摩 = 摩根士丹利 = Morgan Stanley; the shown name is the report's own), at most
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
MAX_TOKENS = 12000  # live 2026-11-12: up to 4,608 output tokens (thinking + 8 candidates)
MAX_INSTITUTION_CHARS = 40
MAX_RATING_CHARS = 30
MAX_TITLE_CHARS = 200
# Internal plausibility filter for a target price (never shown, never used for any figure): a target outside
# this multiple of the last real price is most likely another currency (e.g. the TSM ADR's USD target reported
# as TWD for 2330.TW is about 0.16 × the TWD price per 1× upside, 2412's 10-share CHT ADR about 0.32 ×).
TARGET_RATIO_MIN = 0.4
TARGET_RATIO_MAX = 3.0
# Drops that do not show there is nothing to report (a mangled URL, a result without a readable date): when nothing
# is kept and a candidate was dropped for one of these, the entry is ``unavailable`` (retried later), never an
# empty ``ready``.
UNSURE_DROPS = frozenset({"url_not_in_results", "date_unverified"})
# Not articles: rating aggregators (their rating data is their licensed product, docs/research/analyst-ratings.md)
# and quote pages. ``AGGREGATOR_HOSTS`` (and subdomains) are blocked in the search tool and dropped by ``verify``;
# ``QUOTE_PATHS`` (host and subdomains → path prefixes) and the rating-page path words are dropped by ``verify``.
AGGREGATOR_HOSTS = ("tipranks.com", "marketbeat.com", "stockanalysis.com", "tradingview.com", "goodinfo.tw",
                    "wantgoo.com", "cmoney.tw", "benzinga.com", "zacks.com", "wallstreetzen.com", "fintel.io",
                    "public.com", "marketscreener.com", "simplywall.st", "alphaspread.com", "valueinvesting.io",
                    "tickernerd.com", "chartmill.com")
QUOTE_PATHS: dict[str, tuple[str, ...]] = {
    "tw.stock.yahoo.com": ("/quote",), "finance.yahoo.com": ("/quote",), "cnyes.com": ("/twstock", "/usstock"),
    "invest.cnyes.com": ("/",), "money.cnn.com": ("/quote",), "wsj.com": ("/market-data",),
    "marketwatch.com": ("/investing/",), "nasdaq.com": ("/market-activity/",), "investing.com": ("/equities/",),
}
# A path segment like these is a rating / forecast page, unless the URL carries an article date.
RATING_PAGE_SEGMENTS = frozenset({"quote", "quotes", "analyst-ratings", "analyst-research", "analyst-insights",
                                  "analystestimates", "analyst-estimates", "estimates", "research-ratings", "forecast",
                                  "forecasts", "price-target", "price-targets", "consensus"})
RATING_PAGE_SUFFIXES = ("-consensus-estimates", "-stock-forecast", "-price-target", "-price-targets",
                        "-analyst-ratings", "-analyst-estimates")
NOTE_OFF = "現在查不到法人觀點。"


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    page_age: str | None


@dataclass(frozen=True)
class Dropped:
    candidate: dict[str, Any]
    reason: str  # url_not_in_results | not_article | date_unverified | too_old | future | unnamed | empty | currency
    #              | duplicate  (``currency`` also covers a target outside TARGET_RATIO_MIN–MAX × the last price)


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
        raise ApiError(503, "ai_unavailable", "AI 暫時不能用。")
    if not pool.ranked(store.slot_month_costs(db)):
        raise ApiError(503, "ai_unavailable", "AI 暫時不能用，晚一點再試。")
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


_RATING_HEADLINE = re.compile(
    r"目標價|評等|評級|price targets?|target price|\b(?:upgrade|downgrade)[sd]\b|\b(?:overweight|outperform|"
    r"underweight|underperform)\b|analyst ratings?", re.IGNORECASE)
_CREDIT_RATING = re.compile(r"信評|信用評|credit rating", re.IGNORECASE)
_CORPORATE_SUFFIX = re.compile(r"[\s,]+(?:corporation|corp|incorporated|inc|co|company|ltd|limited|plc|holdings|"
                               r"group|class [a-z])\.?$", re.IGNORECASE)


def stock_terms(info: InstrumentInfo) -> list[str]:
    """Words that show a headline is about this stock: its name, code, ticker and aliases (台積電, 2330, TSMC;
    NVIDIA, NVDA, 輝達), case-folded, corporate suffixes removed."""
    terms: set[str] = set()
    for t in (info.name, info.code, info.symbol.split(".")[0], *info.aliases):
        t = _CORPORATE_SUFFIX.sub("", (t or "").strip()).casefold()
        if len(t) >= 2:
            terms.add(t)
    return sorted(terms)


def _mentions(title: str, terms: list[str]) -> bool:
    text = title.casefold()
    for t in terms:
        if t.isascii():  # NVDA, TSMC, 2330: a whole word (not part of "TSMCs" or "23301")
            if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", text):
                return True
        elif t in text:
            return True
    return False


def rating_headlines(results: list[SearchResult], info: InstrumentInfo, today: date) -> int:
    """How many article results have a rating / target-price headline about *this* stock (its name, code, ticker
    or alias in the title) that is not verifiably older than ``MAX_AGE_DAYS`` — the check that keeps an empty
    report from being shown as "nothing found". Other stocks' ratings, credit ratings and aggregator pages do
    not count."""
    terms = stock_terms(info)
    oldest = today - timedelta(days=MAX_AGE_DAYS)
    n = 0
    for r in results:
        title = r.title or ""
        if not (is_article(r.url) and _RATING_HEADLINE.search(title) and not _CREDIT_RATING.search(title)
                and _mentions(title, terms)):
            continue
        published = date_from_url(r.url) or date_from_page_age(r.page_age, today)
        if published is None or published >= oldest:
            n += 1
    return n


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
    reason: str | None = None  # why it is unavailable: no_report | stopped | empty_despite_headlines | unverified


def search_tools(settings: Settings) -> list[dict[str, Any]]:
    """``web_search`` (no ``web_fetch``) with rating aggregators blocked, unless an allow-list is configured
    (the API takes one or the other)."""
    tools = server_tools(settings, fetch=False, max_uses=settings.ai_analyst_search_max_uses)
    for t in tools:
        if t.get("name") == "web_search" and "allowed_domains" not in t:
            t["blocked_domains"] = list(AGGREGATOR_HOSTS)
    return tools


def run_model(info: InstrumentInfo, today: date, generation_id: str, pool: KeyPool, settings: Settings,
              record: Callable[[int, Any], None], costs: Any = None, thinking_display: str | None = None,
              reference: float | None = None) -> Outcome:
    """Ask the model (web search + ``report_analyst_views``), then verify. ``record(slot, message)`` stores the
    usage of every call. Raises on API errors (the caller marks the entry unavailable). ``reference`` is the last
    real price, only for ``verify``'s internal currency check. ``thinking_display`` (``"summarized"``) is only for
    the live smoke's diagnostics.

    "Nothing found" (``ready`` with no items) is only claimed when nothing points the other way: if no item
    survives while the search results carry a rating headline about this stock (``rating_headlines``), or while a
    candidate was dropped for a reason that does not show there is nothing (``UNSURE_DROPS``: a URL that is not
    one of the results, a result without a readable date), the outcome is ``unavailable`` (retried after
    ``UNAVAILABLE_RETRY_AFTER``)."""
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
    queries, transcript = _queries(content), _transcript(content)
    if reported is None or stop in ("refusal", "max_tokens"):
        log.warning("analyst views %s for %s: no usable report (stop=%s)", generation_id, info.symbol, stop)
        return Outcome("unavailable", [], [], reported or [], results, usage, calls, queries, stop, transcript,
                       "no_report" if reported is None else "stopped")
    items, dropped = verify(reported, results, info, today, reference)
    if not items:
        headlines = rating_headlines(results, info, today)
        unsure = any(d.reason in UNSURE_DROPS for d in dropped)
        if headlines or unsure:
            # Do not claim there are no reports: "unavailable" (retried later) instead of an empty "ready".
            log.warning("analyst views %s for %s: nothing kept of %d candidates (dropped: %s; %d results have "
                        "rating headlines about it)", generation_id, info.symbol, len(reported),
                        ", ".join(d.reason for d in dropped) or "none", headlines)
            return Outcome("unavailable", [], dropped, reported, results, usage, calls, queries, stop, transcript,
                           "empty_despite_headlines" if headlines else "unverified")
    return Outcome("ready", items, dropped, reported, results, usage, calls, queries, stop, transcript)


def reference_price(md: MarketData, symbol: str) -> float | None:
    """The last real price (never a demo quote), only for ``verify``'s internal currency check; ``None`` when
    there is none (the check is then skipped)."""
    try:
        q = md.quote(symbol)
    except Exception:  # market data trouble must not fail the generation
        log.warning("analyst views: no quote for %s", symbol, exc_info=True)
        return None
    if q is None or q.is_demo:
        return None
    price = q.price or q.prev_close
    return float(price) if price and price > 0 else None


def generate(db: Session, md: MarketData, info: InstrumentInfo, day: date, generation_id: str, pool: KeyPool,
             settings: Settings, user_id: str | None) -> AiAnalystViews | None:
    """Run one generation and store its outcome on today's entry (unless a newer generation replaced it)."""
    model = store.model_for("analyst", settings)

    def record(slot: int, msg: Any) -> None:
        store.record_usage(db, user_id=user_id, thread_id=generation_id, feature="analyst", model=msg.model or model,
                           key_slot=slot, usage=CallUsage.from_sdk(msg.usage), stop_reason=msg.stop_reason)

    today = now_utc().astimezone(TAIPEI).date()
    try:
        outcome = run_model(info, today, generation_id, pool, settings, record, store.slot_month_costs(db),
                            reference=reference_price(md, info.symbol))
        status, items, notes = outcome.status, outcome.items, []
        if outcome.dropped:
            log.info("analyst views %s for %s: %s, kept %d, dropped %s", generation_id, info.symbol, status,
                     len(items), ", ".join(d.reason for d in outcome.dropped))
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
# ``/2026/11/10/``, ``2026-11-10``, ``2026_11_10``: the day must end there (``/2026/09/284512/`` is an id, not
# 2026-09-28). Unseparated ``20261110…`` (CNA ``202611050123``, 工商時報 ``20261104700053``) has a sequence number
# right after the day.
_URL_DATE = re.compile(r"(?<!\d)(20\d{2})([-/_.])(0?[1-9]|1[0-2])\2(0?[1-9]|[12]\d|3[01])(?!\d)")
_URL_DATE_COMPACT = re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])")
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
        d = _date(m.group(1), m.group(3), m.group(4))
        if d is not None:
            return d
    for m in _URL_DATE_COMPACT.finditer(path):
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


def _on_host(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def is_article(url: str) -> bool:
    """False for rating aggregators (``AGGREGATOR_HOSTS``), quote pages (``QUOTE_PATHS``, subdomains included) and
    rating / forecast pages (a path segment such as ``/analyst-ratings``, ``/price-target``, ``/consensus``, or
    ``…-consensus-estimates``, unless the URL carries an article date). Such pages keep changing, so their
    ``page_age`` is an update time, not the date a broker published a rating."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = parts.path.lower()
    if any(_on_host(host, h) for h in AGGREGATOR_HOSTS):
        return False
    if any(_on_host(host, h) and path.startswith(prefixes) for h, prefixes in QUOTE_PATHS.items()):
        return False
    if date_from_url(url) is not None:
        return True
    segments = [seg for seg in path.split("/") if seg]
    return not any(seg in RATING_PAGE_SEGMENTS or seg.endswith(RATING_PAGE_SUFFIXES) for seg in segments)


# -- institutions ----------------------------------------------------------------------------------------------
# Names are compared without spaces or punctuation, case-folded. A name made only of these words is not a named
# institution: 「外資」「美系外資」「歐系券商」「某外資」「外資券商 A」「國內投顧」「Wall Street analysts」…
_GENERIC_QUALIFIERS = (
    r"某一?家?|一家|一位|另一?家|多家|數家|部分|其他|知名|大型|國際|主要|海外|境外|外商|本土|國內|台灣|臺灣|"
    r"[中陸港日歐美英德法瑞韓星台]資|[\u4e00-\u9fff]{1,2}系|"
    r"an?|the|some|several|many|one|other|top|major|leading|unnamed|anonymous|us|foreign|global|international|"
    r"wallstreet|sellside")
_GENERIC_NOUNS = (
    r"外資券商|外資法人|外資圈|外資|外商券商|證券商|券商|投顧|投信|法人圈|法人|分析師|研究員|研究機構|研調機構|投資機構|機構|"
    r"投資銀行|投行|研究單位|市場共識|市場|共識|"
    r"analysts?|brokers?|brokerages?|investmentbanks?|banks?|researchfirms?|firms?|strategists?|"
    r"analystconsensus|consensus|thestreet|investors?|institutions?|market")
_GENERIC_NAME = re.compile(rf"(?:{_GENERIC_QUALIFIERS})*(?:{_GENERIC_NOUNS})?")
# Trailing words that do not change which institution it is (「大摩分析師」, 凱基投顧 = 凱基證券, BofA Global Research).
_NAME_SUFFIXES = ("證券投資顧問", "證券投顧", "研究團隊", "資本市場", "分析師", "研究部", "證券", "投顧", "集團",
                  "控股", "資本", "globalresearch", "globalmarkets", "capitalmarkets", "researchteam", "securities",
                  "strategists", "strategist", "analysts", "analyst", "research", "holdings", "group", "inc", "llc",
                  "capital", "plc", "ltd", "co")
# Common names of the same institution (Taiwanese media mix them): compared after the suffixes are removed.
_ALIASES = {alias: key for key, names in {
    "morganstanley": ("大摩", "摩根士丹利", "摩根史坦利", "台灣摩根士丹利", "morganstanley"),
    "jpmorgan": ("小摩", "摩根大通", "jpmorgan", "jpmorganchase", "jpm"),
    "bofa": ("美銀", "美國銀行", "美林", "美銀美林", "bofa", "bofaglobal", "bankofamerica", "merrilllynch",
             "bofamerrilllynch", "bankofamericamerrilllynch"),
    "goldmansachs": ("高盛", "goldman", "goldmansachs"),
    "citi": ("花旗", "花旗環球", "citi", "citigroup", "citiglobal"),
    "ubs": ("瑞銀", "ubs"),
    "nomura": ("野村", "nomura"),
    "macquarie": ("麥格理", "macquarie"),
    "hsbc": ("匯豐", "滙豐", "hsbc"),
    "deutschebank": ("德銀", "德意志", "德意志銀行", "deutschebank", "deutsche"),
    "barclays": ("巴克萊", "barclays"),
    "jefferies": ("傑富瑞", "杰富瑞", "jefferies"),
    "bernstein": ("伯恩斯坦", "bernstein"),
    "mizuho": ("瑞穗", "mizuho"),
    "daiwa": ("大和", "daiwa"),
    "clsa": ("里昂", "中信里昂", "clsa"),
}.items() for alias in names}


def _norm_name(name: str) -> str:
    return re.sub(r"[\s.,&'’·・()（）\-]+", "", name).casefold()


_PAREN = re.compile(r"^(.*?)\s*[(（]\s*(.+?)\s*[)）]\s*$")


def institution_key(name: str) -> str | None:
    """The key that identifies an institution (aliases folded: 大摩 = 摩根士丹利 = Morgan Stanley), or ``None`` when
    the name does not name one (「美系外資」「外資券商 A」「Wall Street analysts」). 「花旗（Citi）」 is keyed by the
    name before the parentheses, or by the one inside when the first is generic (「美系外資（摩根士丹利）」). Only for
    checks and de-duplication: the shown name is the report's own wording."""
    m = _PAREN.match(name.strip())
    if m:
        return next((k for k in (_name_key(m.group(1)), _name_key(m.group(2))) if k), None)
    return _name_key(name)


def _name_key(name: str) -> str | None:
    s = re.sub(r"(?:\s+|(?<=[\u4e00-\u9fff]))[A-Za-z0-9]{1,2}$", "", name.strip())  # 「美系外資 C」「外資券商A」
    s = _norm_name(s)
    stripped = True
    while stripped:
        stripped = False
        for suffix in _NAME_SUFFIXES:
            if s.endswith(suffix) and len(s) > len(suffix):
                s, stripped = s.removesuffix(suffix), True
                break
    if not s or _GENERIC_NAME.fullmatch(s):
        return None
    return _ALIASES.get(s, s)


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
           today: date, reference: float | None = None) -> tuple[list[dict[str, Any]], list[Dropped]]:
    """Keep the candidates that the search results support (see the module docstring). Returns the items in the
    contract shape (newest first, one per institution — aliases folded by ``institution_key`` — at most
    ``MAX_ITEMS``) and the dropped candidates. ``reference`` (the last real price, optional) only drops a target
    price outside ``TARGET_RATIO_MIN``–``TARGET_RATIO_MAX`` times it as another currency; it is never shown or
    compared in the output."""
    by_url: dict[str, SearchResult] = {}
    for r in results:
        by_url.setdefault(_norm_url(r.url), r)
    oldest = today - timedelta(days=MAX_AGE_DAYS)
    kept: list[tuple[str, dict[str, Any]]] = []
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
        key = institution_key(institution) if institution else None
        if institution is None or key is None:
            dropped.append(Dropped(c, "unnamed"))
            continue
        rating = _text(c.get("rating_text"), MAX_RATING_CHARS)
        target = _price(c.get("target_price"))
        if target is not None and (c.get("currency") != info.currency or (
                reference and not TARGET_RATIO_MIN <= target / reference <= TARGET_RATIO_MAX)):
            dropped.append(Dropped(c, "currency"))  # e.g. the TSM ADR's USD target listed for 2330.TW
            continue
        if rating is None and target is None:
            dropped.append(Dropped(c, "empty"))
            continue
        action = c.get("action") if c.get("action") in ("調升", "調降", "維持", "首評") else ""
        kept.append((key, {"institution": institution, "action": action, "rating_text": rating,
                           "target_price": target, "currency": info.currency, "date": published.isoformat(),
                           "source_title": " ".join(result.title.split())[:MAX_TITLE_CHARS] or _norm_url(result.url),
                           "url": result.url}))
    kept.sort(key=lambda k: k[1]["date"], reverse=True)  # stable: the model's order within a day
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key, item in kept:
        if key in seen:
            dropped.append(Dropped(item, "duplicate"))
            continue
        seen.add(key)
        items.append(item)
    return items[:MAX_ITEMS], dropped

