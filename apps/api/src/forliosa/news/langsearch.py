"""LangSearch web search as a source of Taiwan stocks' headlines (產品負責人 2026-11-17, the exception in CLAUDE.md).

The product owner decided to use LangSearch (``POST https://api.langsearch.com/v1/web-search``) knowing its terms do
not say whether results may be kept and its operator is unknown: only a headline's **title, outlet, time and link**
are stored in ``news_articles`` (source ``langsearch``; deleted after ``NEWS_RETENTION_DAYS`` like every source) —
never the snippet, summary or text, which are not even read. Inside the free daily allowance; a refusal (429, 401 /
403, a redirect) stops it until the next 00:00 UTC (08:00 Taipei), with the same key and client — never another
account, never a disguise. While it is down or paused the other news sources work as before. **US stocks never use
it.** Off by default (``NEWS_LANGSEARCH_ENABLED``): only the production Railway worker turns it on.

Research and numbers: the recommendation of 2026-11-17 (178 measured requests, 1,617 labelled results), summarised in
``apps/api/CONTRACT_NOTES.md`` 「2026-11-17 LangSearch 台股新聞」.

Request (:func:`request_body`)
    ``{"query": '"台積電"', "freshness": "2026-11-16..2026-11-17", "summary": false, "count": 50,
    "contents": {"text": {"max_characters": 1}}}`` — the exchange short name in double quotes (no code, no 「股價」),
    ``contents`` capped at one character (about 40 tokens per request instead of about 7,000: :data:`CONTENTS_CAP`),
    never ``noLimit``, never ``includeDomains`` / ``excludeDomains`` (they shrink the candidate set: 家登 with a
    blacklist kept 1 result; the takedown blocklist is applied here, after the answer), never ``/v1/rerank``.

Filter (:func:`filter_items`, per answer)
    Only ``name``, ``url`` and ``datePublished`` are read (:func:`parse`). Then: a usable link (search redirects
    dropped), not a page that is not news, not taken down, not on ``NEWS_LANGSEARCH_JUNK_DOMAINS``; only Taiwanese
    sites (:func:`forliosa.news.outlets.is_taiwan_outlet`); the title cleaned, robot flashes dropped and the stock named
    by the same rule as every source (:func:`forliosa.news.service.to_headlines`: :mod:`forliosa.news.tw_match`, terms
    from :func:`forliosa.news.service.build_query`); inside the window (its start less :data:`GRACE`, at most 30
    minutes after the request); de-duplicated (the original outlet over a Yahoo / LINE copy). The market topics
    (``^TW``) are kept by :data:`TOPIC_KEYWORDS` instead of a company name.

Schedule (:func:`refresh_langsearch`, worker job ``news_langsearch`` every 10 minutes; Asia/Taipei times)
    * Topics (:data:`TW_MARKET_KEY`): ``NEWS_LANGSEARCH_TOPICS`` on trading days from ``NEWS_LANGSEARCH_TOPICS_AT``
      (16:00), once per UTC day, freshness ``D..D`` (today's UTC date).
    * Tracked Taiwan stocks (held, watched, viewed in the last ``NEWS_VIEW_DAYS``) by tier: large every day, mid
      every 2 days, small every 4, quiet (a small cap with ``NEWS_LANGSEARCH_QUIET_AFTER_EMPTY`` empty runs in a row)
      every 7, from ``NEWS_LANGSEARCH_STOCKS_AFTER`` (18:30); one that missed its day runs from 08:00. Freshness from
      the UTC date of its last success to today (at most 7 days back, or the tier's interval when that is longer: a
      quiet stock's run 7 days later starts on the day of its last success), so no day is left out. A stock never
      asked is a first fill (``oneWeek``; small ``oneMonth``), at most ``NEWS_LANGSEARCH_MAX_FIRST_FILL_PER_DAY`` a
      day, after the others. Nothing older than ``NEWS_RETENTION_DAYS`` is stored (the purge would delete it).
    * Tier: market-cap rank ≤ ``NEWS_LANGSEARCH_LARGE_RANK`` starts large, the rest mid; recomputed weekly from the
      headlines kept per run (an average over about 14 days): ≥ ``LARGE_MIN_AVG`` large, ≥ ``MID_MIN_AVG`` mid, else
      small. Order: topics, held or watched stocks, then large, mid, small; the oldest success first.
    * Nothing runs between 00:00 and 08:00 Taipei (the UTC date is still yesterday's).

Limits (every UTC day; all of it in ``news_fetch_state``, so a restart forgets nothing — no new table)
    * At most ``NEWS_LANGSEARCH_MAX_REQUESTS_PER_DAY`` (250) requests and ``NEWS_LANGSEARCH_MAX_TOKENS_PER_DAY``
      (50,000) tokens. An answer with more than ``NEWS_LANGSEARCH_TOKEN_GUARD`` (1,000) output tokens means the contents
      cap was ignored: stopped for the UTC day, warned in the log and on /admin.
    * HTTP 429, a body ``code`` 429 or a quota message: stopped until the next 00:00 UTC, no retry; 401 / 403 / a
      redirect the same. Two 5xx / timeouts in a row (counted across passes until LangSearch answers again) pause it
      15 minutes from the failure, doubling up to 4 hours. Another 4xx, or a 200 without ``data.webPages.value``,
      skips that query only.
    * Quota on two UTC days in a row: the daily cap becomes 80 % of the requests that went through before the last
      hit and mid / small caps run every 3 / 7 days; three days in a row (or a cap under 30): only the topics and held
      or watched large caps. Each step is cleared after 3 days without a hit (:func:`ladder`).
    * At least ``NEWS_LANGSEARCH_INTERVAL_SECONDS`` (1.5) between two requests, also across processes (the last
      request's time is stored); one pass at a time (a Postgres advisory lock). The manual check (:func:`smoke`)
      keeps every one of these rules: switch, pause, caps, lock, gap; it is counted and a refusal stops the worker.

Rows of ``news_fetch_state`` (source ``langsearch``): the symbol's own row (last attempt and success, kept headlines);
``^TW/<hash>`` per topic; ``*`` the source-wide pause; ``@use:<UTC date>`` the day's usage (``items`` requests,
``failures`` tokens, ``last_attempt_at`` the last request, ``last_success_at`` / ``last_status`` the quota hit or
stop); ``@new:<UTC date>`` (``items``) first fills; ``@tier:<symbol>`` (``last_status`` tier, ``items`` the average
× 100, ``failures`` empty runs in a row, ``last_attempt_at`` when the tier was set); ``@down`` (``failures`` 5xx /
timeouts in a row since LangSearch last answered, ``last_attempt_at`` the last one).

Logs carry the status, latency, result count and tokens only — never a header, the key, the query's answer or its
message.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import logging
import math
import re
import threading
import time as _time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from typing import Any

import httpx
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from forliosa.config import Settings, get_settings
from forliosa.datapolicy import source_clause
from forliosa.marketdata.base import ProviderUnavailable
from forliosa.marketdata.http import RateLimiter
from forliosa.marketdata.service import MarketData
from forliosa.models import CompanyProfile, NewsFetchState, PriceDaily
from forliosa.news import service, tw_match
from forliosa.news.normalize import Headline, clean_url, dedupe, is_blocked, make_terms
from forliosa.news.outlets import host_of, is_not_news, is_taiwan_outlet, on_domain
from forliosa.news.sources import Query, RawItem, SourceBlocked, SourceDown
from forliosa.timeutil import TAIPEI, is_tw_trading_day, now_utc

log = logging.getLogger(__name__)

CONTENTS_CAP: dict[str, Any] = {"text": {"max_characters": 1}}
SOURCE_KEY = "langsearch"  # news_articles.source, news_fetch_state.source (String(16))
TW_MARKET_KEY = "^TW"  # the market topics' headlines (like "^US")
HOST = "api.langsearch.com"
GRACE = timedelta(hours=12)  # window start slack (datePublished's day boundary)
MAX_WINDOW_DAYS = 7
FIRST_FILL_DAYS = {"oneWeek": 7, "oneMonth": 30}
ACTIVE_FROM = dtime(8, 0)  # Taipei: from here the UTC date is Taipei's date
TIER_DAYS = 7  # a tier is recomputed weekly
AVERAGE_DAYS = 14  # the average it is recomputed from spans about this many days
RESTRICT_BELOW = 30  # a daily cap under this many requests restricts the pass
LADDER_HISTORY_DAYS = 30
MAX_ERRORS_IN_A_ROW = 3
TIERS = ("large", "mid", "small", "quiet")
TIER_ORDER = {t: i for i, t in enumerate(TIERS)}
USER_AGENT = "forliosa/0.1 (portfolio tracker; news headline index)"
# Market topics: kept when the title has one of these (measured precision 0.98, recall 0.92)
TOPIC_KEYWORDS = re.compile(r"台股|加權|大盤|外資|法人|投信|自營商|盤|指數|台指|櫃買|千點|\d+點"
                            r"|國安基金|權值|ETF|0050|新台幣|台幣")
_QUOTA_WORDS = ("quota", "limit", "额度", "額度", "余额", "餘額")
_QUOTES = re.compile("[\"'“”„‟＂「」『』]")
USAGE_PREFIX = "@use:"
FIRST_FILL_PREFIX = "@new:"
TIER_PREFIX = "@tier:"
TOPIC_PREFIX = TW_MARKET_KEY + "/"
DOWN_KEY = "@down"  # 5xx / timeouts in a row, across passes
DOWN_IN_A_ROW = 2  # this many pause the source (15 minutes, doubling)
LOCK_KEY = 0x4C53_4E45_5753  # pg_advisory_lock key of the pass ("LSNEWS")


# -- errors -------------------------------------------------------------------------------------------------------
class LangSearchError(ProviderUnavailable):
    """Another 4xx or an unusable answer: this query only (nothing of the answer is in the message)."""


class LangSearchQuota(SourceBlocked):
    """The daily allowance is used up (HTTP 429, body ``code`` 429 or a quota message): stopped until 00:00 UTC."""


class LangSearchContract(SourceBlocked):
    """An answer far above the token guard: the contents cap was ignored. Stopped for the UTC day."""


def next_utc_midnight(now: datetime) -> datetime:
    day = now.astimezone(UTC).date() + timedelta(days=1)
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _utc_day(dt: datetime) -> date:
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC).date()


def _midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


# -- the request --------------------------------------------------------------------------------------------------
def stock_query(short_name: str) -> str:
    """``台積電`` -> ``"台積電"``: the exchange short name without its market suffix (``永冠-KY`` -> ``"永冠"``,
    :func:`forliosa.news.tw_match.core_name`) and without quotes of its own. Never a code."""
    name = " ".join(_QUOTES.sub("", tw_match.core_name((short_name or "").strip())).split())
    if not name or name.isdigit():
        raise ValueError("a stock query needs the company's short name")
    return f'"{name}"'


def freshness(last_success: datetime | None, now: datetime, tier: str, *, first_fill: bool, every: int = 1) -> str:
    """A first fill: ``oneWeek`` (large, mid) or ``oneMonth`` (small, quiet). Otherwise ``YYYY-MM-DD..YYYY-MM-DD`` in
    UTC dates: from the UTC date of the last success (one day before today at the latest; six days before at the
    earliest, or ``every`` days before for a stock asked every ``every`` days, so a quiet stock's run 7 days after
    its last success still starts on that day) to today — a daily run sends ``D-1..D``, which is ``oneDay``."""
    if first_fill or last_success is None:
        return "oneMonth" if tier in ("small", "quiet") else "oneWeek"
    today = _utc_day(now)
    start = min(_utc_day(last_success), today - timedelta(days=1))
    start = max(start, today - timedelta(days=max(MAX_WINDOW_DAYS - 1, every)))
    return f"{start.isoformat()}..{today.isoformat()}"


def topic_freshness(now: datetime) -> str:
    """``D..D`` with D the UTC date of ``now`` (from 08:00 Taipei, Taipei's date)."""
    d = _utc_day(now).isoformat()
    return f"{d}..{d}"


def window_start(fresh: str, now: datetime) -> datetime:
    """Where the freshness window starts (00:00 UTC of its first day); :data:`GRACE` is taken off by the caller."""
    today = _utc_day(now)
    if fresh in FIRST_FILL_DAYS:
        return _midnight(today - timedelta(days=FIRST_FILL_DAYS[fresh]))
    if fresh == "oneDay":
        return _midnight(today - timedelta(days=1))
    return _midnight(date.fromisoformat(fresh.split("..", 1)[0]))


def request_body(query: str, fresh: str, count: int) -> dict[str, Any]:
    """The web-search body: always ``summary: false`` and the one-character contents cap; never ``noLimit``, never
    ``includeDomains`` / ``excludeDomains``."""
    if not fresh or fresh == "noLimit":
        raise ValueError("LangSearch is always asked for a bounded time range")
    return {"query": query, "freshness": fresh, "summary": False, "count": max(1, min(50, int(count))),
            "contents": copy.deepcopy(CONTENTS_CAP)}


# -- the answer ---------------------------------------------------------------------------------------------------
def parse_published(value: object) -> tuple[datetime, bool] | None:
    """``2026-11-10T07:18:38.000Z`` -> aware UTC time; a date alone (``2026-11-10``) -> that day's Taipei midnight,
    date only. ``None`` for anything else."""
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip()
    try:  # a year at the edge of the calendar (0001-01-01T00:00+08:00) overflows on the way to UTC: skipped too
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            d = date.fromisoformat(v)
            day = datetime(d.year, d.month, d.day, tzinfo=TAIPEI)
            day.astimezone(UTC)
            return day, True
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC), False
    except (ValueError, OverflowError):
        return None


def _quota_message(msg: object) -> bool:
    m = str(msg or "").casefold()
    return any(w in m for w in _QUOTA_WORDS)


def body_error(code: object, msg: object, now: datetime, *, has_results: bool = False) -> Exception | None:
    """The error a body ``code`` / ``msg`` stands for, or ``None`` for a usable answer. The message is only looked at
    for quota words, never kept."""
    try:
        c = int(code)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        c = 0
    if c == 429 or (_quota_message(msg) and (c != 200 or not has_results)):
        return LangSearchQuota(f"LangSearch quota (code {c})", until=next_utc_midnight(now))
    if c == 200:
        return None
    if c in (401, 403):
        return SourceBlocked(f"LangSearch refused (code {c})", until=next_utc_midnight(now))
    if c >= 500:
        return SourceDown(f"LangSearch answered code {c}")
    return LangSearchError(f"LangSearch answered code {c}")


def _values(payload: Mapping[str, Any]) -> list[Any] | None:
    """``data.webPages.value``, or ``None`` when the answer has no such list (a real empty answer has ``[]``)."""
    data = payload.get("data")
    pages = data.get("webPages") if isinstance(data, dict) else None
    values = pages.get("value") if isinstance(pages, dict) else None
    return values if isinstance(values, list) else None


def parse(payload: Mapping[str, Any], now: datetime | None = None) -> list[RawItem]:
    """``data.webPages.value[]`` -> raw items (title = ``name``, ``url``, ``datePublished``). No other field is read
    (``snippet``, ``summary``, ``text`` never). Items without a link, a title or a usable date are skipped. A body
    ``code`` other than 200 raises (:func:`body_error`); so does a 200 without a ``data.webPages.value`` list
    (:class:`LangSearchError`: that query only — never booked as an answer without news)."""
    if not isinstance(payload, Mapping):
        raise LangSearchError("LangSearch answered something that is not a JSON object")
    values = _values(payload)
    code = payload.get("code", 200 if values else None)  # an answer with results but without a code is usable
    err = body_error(code, payload.get("msg"), now or now_utc(), has_results=bool(values))
    if err is not None:
        raise err
    if values is None:
        raise LangSearchError("LangSearch answered code 200 without data.webPages.value")
    out: list[RawItem] = []
    for v in values:
        if not isinstance(v, dict):
            continue
        title, url = str(v.get("name") or "").strip(), str(v.get("url") or "").strip()
        when = parse_published(v.get("datePublished"))
        if not title or not url or when is None:
            continue
        out.append(RawItem(title=title, url=url, published_at=when[0], date_only=when[1]))
    return out


@dataclass(frozen=True)
class Reply:
    """One HTTP answer: its status, its JSON object (``None`` when it was not one) and the tokens it reports."""

    status: int
    payload: dict[str, Any] | None
    input_tokens: int = 0
    output_tokens: int = 0
    latency: float = 0.0

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def interpret(reply: Reply, now: datetime, guard: int) -> list[RawItem]:
    """The raw items of a reply, or the error it stands for (see the module docstring)."""
    s = reply.status
    if s == 429:
        raise LangSearchQuota("LangSearch HTTP 429", until=next_utc_midnight(now))
    if 300 <= s < 400 or s in (401, 403):
        raise SourceBlocked(f"LangSearch HTTP {s}", until=next_utc_midnight(now))
    if s >= 500:
        raise SourceDown(f"LangSearch HTTP {s}")
    if s != 200:
        raise LangSearchError(f"LangSearch HTTP {s}")
    if reply.payload is None:
        raise SourceDown("LangSearch answered something that is not JSON")
    if reply.output_tokens > guard:
        raise LangSearchContract(f"LangSearch answer of {reply.output_tokens} output tokens: contents cap ignored",
                                 until=next_utc_midnight(now))
    return parse(reply.payload, now)


# -- the client ---------------------------------------------------------------------------------------------------
_TRANSPORT: list[httpx.BaseTransport | None] = [None]
_LIMITERS: dict[float, RateLimiter] = {}
_LIMITER_LOCK = threading.Lock()


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Tests: every LangSearch request goes through ``transport`` (``None``: the network)."""
    _TRANSPORT[0] = transport


def shared_limiter(interval: float) -> RateLimiter:
    """The process-wide limiter for :data:`HOST` (one per interval)."""
    with _LIMITER_LOCK:
        if interval not in _LIMITERS:
            _LIMITERS[interval] = RateLimiter(per_host={HOST: interval})
        return _LIMITERS[interval]


def reset_limiters() -> None:
    with _LIMITER_LOCK:
        _LIMITERS.clear()


def _int(value: object) -> int:
    try:
        return max(0, int(value))  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 0


class LangSearchClient:
    """POSTs a web-search body with the Bearer key; a redirect is never followed (it is a refusal)."""

    def __init__(self, api_key: str, url: str = "https://api.langsearch.com/v1/web-search", *,
                 timeout: float = 20.0, interval: float = 1.5, limiter: RateLimiter | None = None,
                 transport: httpx.BaseTransport | None = None):
        if not url.startswith(f"https://{HOST}/"):
            raise ValueError("LangSearch requests go to https://api.langsearch.com/ only")
        self.url = url
        self._key = api_key
        self.limiter = limiter or shared_limiter(interval)
        self._http = httpx.Client(timeout=timeout, follow_redirects=False, transport=transport or _TRANSPORT[0],
                                  headers={"User-Agent": USER_AGENT, "Accept": "application/json"})

    @classmethod
    def from_settings(cls, settings: Settings) -> LangSearchClient | None:
        key = settings.langsearch_api_key.get_secret_value().strip() if settings.langsearch_api_key else ""
        if not key:
            return None
        return cls(key, settings.news_langsearch_url, timeout=settings.news_langsearch_timeout_seconds,
                   interval=settings.news_langsearch_interval_seconds)

    def __repr__(self) -> str:  # never the key
        return f"LangSearchClient({self.url!r})"

    def post(self, body: Mapping[str, Any]) -> Reply:
        """One request. A timeout or a connection error raises :class:`SourceDown` (its message names no header)."""
        self.limiter.wait(HOST)
        started = _time.monotonic()
        try:
            resp = self._http.post(self.url, json=dict(body), headers={"Authorization": f"Bearer {self._key}"})
        except httpx.TimeoutException:
            raise SourceDown("LangSearch timed out") from None
        except httpx.HTTPError as exc:
            raise SourceDown(f"LangSearch unreachable ({type(exc).__name__})") from None
        latency = _time.monotonic() - started
        payload: Any = None
        if resp.content:
            try:
                payload = resp.json()
            except ValueError:
                payload = None
        usage = payload.get("usage") if isinstance(payload, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        return Reply(resp.status_code, payload if isinstance(payload, dict) else None,
                     _int(usage.get("input_tokens")), _int(usage.get("output_tokens")), latency)

    def close(self) -> None:
        self._http.close()


class LangSearchSource:
    """The news source (:class:`forliosa.news.sources.NewsSource`'s ``key`` / ``label`` / ``supports``): Taiwan stocks
    and the market topics only — a US stock is never sent. ``fetch`` asks for the stock's quoted short name (or the
    given topic) and returns the raw items or raises the error the answer stands for; ``last`` keeps the last
    :class:`Reply` (its tokens are counted even when it raised)."""

    key = SOURCE_KEY
    label = "LangSearch"

    def __init__(self, client: LangSearchClient, guard: int = 1000, now_fn: Callable[[], datetime] = now_utc):
        self.client, self.guard, self.now_fn = client, guard, now_fn
        self.last: Reply | None = None

    def supports(self, q: Query) -> bool:
        return q.taiwan and (q.symbol == TW_MARKET_KEY or service.is_taiwan_symbol(q.symbol))

    def fetch(self, q: Query, *, fresh: str, count: int, query: str | None = None) -> list[RawItem]:
        if not self.supports(q):
            raise ValueError("LangSearch is asked for Taiwan stocks and the Taiwan market only")
        self.last = None
        body = request_body(query or stock_query(q.name), fresh, count)
        self.last = self.client.post(body)
        return interpret(self.last, self.now_fn(), self.guard)


# -- filtering ----------------------------------------------------------------------------------------------------
def topic_relevant(title: str, url: str) -> bool:
    return bool(TOPIC_KEYWORDS.search(title))


def filter_items(items: Iterable[RawItem], q: Query, blocked: Sequence[str], junk: Sequence[str], *,
                 topic: bool = False, drops: Counter[str] | None = None,
                 keep_from: datetime | None = None) -> list[Headline]:
    """Raw items -> the headlines to store, in the measured order (module docstring): link, not news / taken down /
    junk, Taiwanese site, then :func:`forliosa.news.service.to_headlines` (title, robot flash, the stock's name or —
    for the topics — :data:`TOPIC_KEYWORDS`, the window) and de-duplication. ``keep_from`` (the retention limit)
    drops what :func:`forliosa.news.service.purge` would delete — a date-only item's day of grace included.
    ``drops`` counts what each step left out (counts only)."""
    drops = drops if drops is not None else Counter()
    sites: list[RawItem] = []
    for it in items:
        url = clean_url(it.url)
        if url is None:
            drops["link"] += 1
            continue
        host = host_of(url)
        if is_not_news(url) or is_blocked(url, blocked) or any(on_domain(host, d) for d in junk):
            drops["junk"] += 1
            continue
        if not is_taiwan_outlet(url):
            drops["not_taiwan"] += 1
            continue
        sites.append(it)
    heads = service.to_headlines(sites, q, SOURCE_KEY, blocked, relevant=topic_relevant if topic else None)
    if keep_from is not None:
        heads = [h for h in heads if h.published_at >= keep_from]
    drops["title_or_name_or_time"] += len(sites) - len(heads)
    kept = dedupe(heads)
    drops["duplicate"] += len(heads) - len(kept)
    return kept


# -- persisted state ----------------------------------------------------------------------------------------------
def _row(db: Session, key: str) -> NewsFetchState:
    row = db.get(NewsFetchState, (SOURCE_KEY, key))
    if row is None:
        row = NewsFetchState(source=SOURCE_KEY, symbol=key, last_status="", items=0, failures=0)
        db.add(row)
        db.flush()
    return row


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@dataclass
class DayUsage:
    """One UTC day's usage (row ``@use:<date>``)."""

    day: date
    requests: int = 0
    tokens: int = 0
    last_request_at: datetime | None = None
    stopped: str = ""  # quota | contract | blocked
    stopped_at: datetime | None = None

    @property
    def quota_hit(self) -> bool:
        return self.stopped == "quota"

    @property
    def before_hit(self) -> int:
        """Requests that went through before the quota hit (the refused one is counted in ``requests``)."""
        return max(0, self.requests - 1)


def usage_key(day: date) -> str:
    return USAGE_PREFIX + day.isoformat()


def read_usage(db: Session, day: date) -> DayUsage:
    row = db.get(NewsFetchState, (SOURCE_KEY, usage_key(day)))
    if row is None:
        return DayUsage(day)
    return DayUsage(day, row.items or 0, row.failures or 0, _aware(row.last_attempt_at), row.last_status or "",
                    _aware(row.last_success_at))


def _usage_history(db: Session, today: date, days: int = LADDER_HISTORY_DAYS) -> dict[date, DayUsage]:
    first = usage_key(today - timedelta(days=days))
    rows = db.scalars(select(NewsFetchState).where(NewsFetchState.source == SOURCE_KEY,
                                                   NewsFetchState.symbol >= first,
                                                   NewsFetchState.symbol.like(USAGE_PREFIX + "%")))
    out: dict[date, DayUsage] = {}
    for r in rows:
        try:
            d = date.fromisoformat(r.symbol[len(USAGE_PREFIX):])
        except ValueError:
            continue
        out[d] = DayUsage(d, r.items or 0, r.failures or 0, _aware(r.last_attempt_at), r.last_status or "",
                          _aware(r.last_success_at))
    return out


def last_request_at(db: Session) -> datetime | None:
    """When the last LangSearch request was sent, by any process (the newest usage row)."""
    newest = db.scalar(select(func.max(NewsFetchState.last_attempt_at)).where(
        NewsFetchState.source == SOURCE_KEY, NewsFetchState.symbol.like(USAGE_PREFIX + "%")))
    return _aware(newest)


def _count_request(db: Session, day: date, at: datetime, *, first_fill: bool) -> None:
    row = _row(db, usage_key(day))
    row.items = (row.items or 0) + 1
    row.last_attempt_at = at
    if first_fill:
        ff = _row(db, FIRST_FILL_PREFIX + day.isoformat())
        ff.items = (ff.items or 0) + 1
        ff.last_attempt_at = at
    db.commit()


def _sent(db: Session, day: date, at: datetime) -> None:
    row = _row(db, usage_key(day))
    row.last_attempt_at = at
    db.commit()


def _count_tokens(db: Session, day: date, tokens: int) -> None:
    if tokens:
        row = _row(db, usage_key(day))
        row.failures = (row.failures or 0) + tokens
        db.commit()


def _mark_day(db: Session, day: date, status: str, at: datetime) -> None:
    row = _row(db, usage_key(day))
    row.last_status, row.last_success_at = status, at
    db.commit()


def _note_down(db: Session, at: datetime) -> int:
    """One more 5xx / timeout in a row (kept across passes); returns how many in a row now."""
    row = _row(db, DOWN_KEY)
    row.failures = (row.failures or 0) + 1
    row.last_attempt_at, row.last_status = at, "unreachable"
    db.commit()
    return row.failures


def _note_answered(db: Session) -> None:
    """LangSearch answered (anything but a 5xx / timeout): the run of failures is over."""
    row = db.get(NewsFetchState, (SOURCE_KEY, DOWN_KEY))
    if row is not None and row.failures:
        row.failures, row.last_status = 0, "ok"
        db.commit()


def down_in_a_row(db: Session) -> int:
    row = db.get(NewsFetchState, (SOURCE_KEY, DOWN_KEY))
    return row.failures or 0 if row is not None else 0


def _wait_gap(db: Session, interval: float, clock: Callable[[], datetime], sleep: Callable[[float], None]) -> None:
    """Wait out the gap since the last request of any process (the limiter keeps it within this one)."""
    last = last_request_at(db)
    wait = interval - (clock() - last).total_seconds() if last is not None else 0.0
    if wait > 0:
        sleep(min(wait, interval))


def first_fills_on(db: Session, day: date) -> int:
    row = db.get(NewsFetchState, (SOURCE_KEY, FIRST_FILL_PREFIX + day.isoformat()))
    return row.items or 0 if row is not None else 0


def purge_bookkeeping(db: Session, today: date, keep_days: int = LADDER_HISTORY_DAYS + 5) -> int:
    """Delete usage and first-fill rows older than ``keep_days``."""
    cut = (today - timedelta(days=keep_days)).isoformat()
    n = 0
    for prefix in (USAGE_PREFIX, FIRST_FILL_PREFIX):
        n += db.execute(delete(NewsFetchState).where(
            NewsFetchState.source == SOURCE_KEY, NewsFetchState.symbol.like(prefix + "%"),
            NewsFetchState.symbol < prefix + cut)).rowcount or 0
    db.commit()
    return n


# -- the degradation ladder ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Ladder:
    """0: normal. 1: quota on 2 UTC days in a row — ``cap`` = 80 % of the requests before the last hit, mid caps every
    3 days, small every 7. 2: quota on 3 days in a row or a cap under :data:`RESTRICT_BELOW` — only the topics and
    held or watched large caps. A step is cleared after 3 days without a hit."""

    level: int = 0
    cap: int | None = None


def ladder(history: Mapping[date, DayUsage], today: date, days: int = LADDER_HISTORY_DAYS) -> Ladder:
    """The ladder for ``today`` from the days before it (a day without a row had no hit). The cap and the "cap under
    :data:`RESTRICT_BELOW`" test come from the current run of hits only: once the ladder is back at 0 the old cap is
    gone, and a single hit later changes nothing."""
    level, cap, hits, clean = 0, None, 0, 0
    for i in range(days, 0, -1):
        u = history.get(today - timedelta(days=i))
        if u is not None and u.quota_hit:
            hits, clean = hits + 1, 0
            if hits >= 2:
                cap = math.floor(0.8 * u.before_hit)
                level = max(level, 1)
                if hits >= 3 or cap < RESTRICT_BELOW:
                    level = 2
            continue
        hits = 0
        if level:
            clean += 1
            if clean >= 3:
                level, clean = level - 1, 0
                if not level:
                    cap = None
    return Ladder(level, cap if level else None)


def day_cap(db: Session, settings: Settings, today: date) -> tuple[Ladder, int]:
    """The ladder and the UTC day's request cap (``NEWS_LANGSEARCH_MAX_REQUESTS_PER_DAY``, lower on the ladder)."""
    lad = ladder(_usage_history(db, today), today)
    cap = settings.news_langsearch_max_requests_per_day
    return lad, cap if lad.cap is None else min(cap, lad.cap)


def every_days(settings: Settings, level: int = 0) -> dict[str, int]:
    days = dict(settings.news_langsearch_every_days)
    if level >= 1:
        days["mid"] = max(days["mid"], 3)
        days["small"] = max(days["small"], 7)
    return days


# -- tiers --------------------------------------------------------------------------------------------------------
@dataclass
class TierState:
    tier: str
    average: float = 0.0
    empty_runs: int = 0
    set_at: datetime | None = None  # when the tier was last (re)computed
    runs: bool = False  # a run has been counted


def tier_for(average: float, empty_runs: int, settings: Settings) -> str:
    """Large, mid or small by the average headlines kept per run; a small cap with
    ``NEWS_LANGSEARCH_QUIET_AFTER_EMPTY`` empty runs in a row is quiet."""
    if average >= settings.news_langsearch_large_min_avg:
        return "large"
    if average >= settings.news_langsearch_mid_min_avg:
        return "mid"
    return "quiet" if empty_runs >= settings.news_langsearch_quiet_after_empty else "small"


def after_run(state: TierState, kept: int, now: datetime, settings: Settings) -> TierState:
    """Book one successful run that kept ``kept`` headlines: the average moves towards it (an exponential average over
    the runs of about :data:`AVERAGE_DAYS` days at the tier's interval — no history table), empty runs are counted, a
    small cap goes quiet after ``QUIET_AFTER_EMPTY`` empty runs and a quiet one back to small with its first headline;
    once a week the tier is recomputed from the average (:func:`tier_for`)."""
    runs = AVERAGE_DAYS / max(1, settings.news_langsearch_every_days.get(state.tier, 1))  # runs in ~14 days
    weight = min(1.0, 2 / (runs + 1))  # an exponential average spanning about that many runs
    average = float(kept) if not state.runs else state.average + (kept - state.average) * weight
    empty = 0 if kept else state.empty_runs + 1
    tier, set_at = state.tier, state.set_at
    if set_at is None or now - set_at >= timedelta(days=TIER_DAYS):
        tier, set_at = tier_for(average, empty, settings), now
    elif tier == "quiet" and kept:
        tier = "small"
    elif tier == "small" and empty >= settings.news_langsearch_quiet_after_empty:
        tier = "quiet"
    return TierState(tier, average, empty, set_at, True)


def read_tier(db: Session, symbol: str) -> TierState | None:
    row = db.get(NewsFetchState, (SOURCE_KEY, TIER_PREFIX + symbol))
    if row is None or row.last_status not in TIER_ORDER:
        return None
    return TierState(row.last_status, (row.items or 0) / 100, row.failures or 0, _aware(row.last_attempt_at),
                     row.last_success_at is not None)


def write_tier(db: Session, symbol: str, st: TierState, now: datetime | None = None) -> None:
    row = _row(db, TIER_PREFIX + symbol)
    row.last_status, row.items, row.failures = st.tier, round(st.average * 100), st.empty_runs
    row.last_attempt_at = st.set_at
    if st.runs:
        row.last_success_at = now or row.last_success_at or now_utc()
    db.commit()


def market_cap_ranks(db: Session, md: MarketData) -> dict[str, int]:
    """Taiwan stocks by market cap (issued shares × the latest archived close of the last 14 days): symbol -> rank,
    1 the largest. Empty without company profiles or closes."""
    shares = {s: n for s, n in db.execute(select(CompanyProfile.symbol, CompanyProfile.shares_outstanding).where(
        source_clause(CompanyProfile.source, md.policy), CompanyProfile.shares_outstanding.is_not(None))) if n}
    if not shares:
        return {}
    clause = source_clause(PriceDaily.source, md.policy)
    taiwan = or_(PriceDaily.symbol.like("%.TW"), PriceDaily.symbol.like("%.TWO"))
    latest = db.scalar(select(func.max(PriceDaily.date)).where(clause, taiwan))
    if latest is None:
        return {}
    closes: dict[str, Any] = {}
    for sym, close in db.execute(select(PriceDaily.symbol, PriceDaily.close).where(
            clause, taiwan, PriceDaily.date >= latest - timedelta(days=14)).order_by(PriceDaily.date)):
        closes[sym] = close
    caps = {s: n * closes[s] for s, n in shares.items() if closes.get(s)}
    return {s: i for i, s in enumerate(sorted(caps, key=lambda s: (-caps[s], s)), start=1)}


# -- one pass -----------------------------------------------------------------------------------------------------
@dataclass
class Task:
    key: str  # news_fetch_state symbol: the stock, or ^TW/<hash> for a topic
    store_as: str  # news_articles.symbol
    query: str
    fresh: str
    count: int
    tier: str | None = None
    first_fill: bool = False
    held: bool = False
    topic: bool = False
    info: Any = None  # InstrumentInfo of a stock


@dataclass
class LangSearchReport:
    skipped: str | None = None  # off | no_key | night | busy | paused (the pass did not run)
    level: int = 0
    cap: int = 0
    requests: int = 0
    tokens: int = 0
    topics: int = 0
    symbols: int = 0
    first_fills: int = 0
    kept: int = 0
    stored: int = 0
    errors: int = 0
    # requests_cap | tokens_cap | quota | contract | blocked | unreachable | errors | deadline
    stopped: str | None = None
    drops: Counter[str] = field(default_factory=Counter)


def topic_key(topic: str) -> str:
    return TOPIC_PREFIX + hashlib.sha1(topic.encode("utf-8")).hexdigest()[:8]


def _topic_query(now: datetime, since: datetime) -> Query:
    return Query(symbol=TW_MARKET_KEY, code="", name="台股", market="TWSE", english=(), terms=make_terms("", ""),
                 since=since, until=now)


def _attempted_today_with_error(row: NewsFetchState | None, today: date) -> bool:
    return bool(row is not None and row.last_status == "error" and row.last_attempt_at is not None
                and _utc_day(row.last_attempt_at) == today)


def plan(db: Session, md: MarketData, settings: Settings, now: datetime, lad: Ladder, *,
         ranks: Callable[[], Mapping[str, int]] | None = None, held: set[str] | None = None) -> list[Task]:
    """What this pass may ask, in order: the topics when due, the stocks that are due (held or watched first, then
    large, mid, small; the oldest success first), then first fills. The caps are applied while it runs."""
    from forliosa.archive import tracked_symbols

    local = now.astimezone(TAIPEI)
    today = _utc_day(now)
    tasks: list[Task] = []
    if is_tw_trading_day(local.date()) and local.time() >= settings.news_langsearch_topics_at:
        for topic in settings.news_langsearch_topics:
            key = topic_key(topic)
            row = db.get(NewsFetchState, (SOURCE_KEY, key))
            done = row is not None and row.last_success_at is not None and _utc_day(row.last_success_at) == today
            if done or _attempted_today_with_error(row, today):
                continue
            tasks.append(Task(key, TW_MARKET_KEY, topic, topic_freshness(now), settings.news_langsearch_count,
                              topic=True))
    held = set(tracked_symbols(db)) if held is None else held
    days = every_days(settings, lad.level)
    after = local.time() >= settings.news_langsearch_stocks_after
    rank_map: Mapping[str, int] | None = None
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    daily: list[tuple[tuple[Any, ...], Task]] = []
    first: list[tuple[tuple[Any, ...], Task]] = []
    for sym in service.tracked(db, settings, now, limit=False):
        if not service.is_taiwan_symbol(sym):
            continue
        info = md.instrument(sym)
        if info is None or info.market == "US":
            continue
        try:
            query = stock_query(info.name)
        except ValueError:
            continue
        st = read_tier(db, sym)
        if st is None:
            if rank_map is None:
                rank_map = (ranks or (lambda: market_cap_ranks(db, md)))()
            rank = rank_map.get(sym)
            large = rank is not None and rank <= settings.news_langsearch_large_rank
            st = TierState("large" if large else "mid", set_at=now)
            write_tier(db, sym, st)
        if lad.level >= 2 and not (sym in held and st.tier == "large"):
            continue
        row = db.get(NewsFetchState, (SOURCE_KEY, sym))
        if _attempted_today_with_error(row, today):
            continue
        last = _aware(row.last_success_at) if row is not None else None
        every = days.get(st.tier, 1)
        count = settings.news_langsearch_count_large if st.tier == "large" else settings.news_langsearch_count
        task = Task(sym, sym, query, freshness(last, now, st.tier, first_fill=last is None, every=every), count,
                    st.tier, first_fill=last is None, held=sym in held, info=info)
        if last is None:
            first.append(((0 if task.held else 1, TIER_ORDER[st.tier], sym), task))
            continue
        since = (today - _utc_day(last)).days
        if since >= every and (after or since > every):
            group = (0, 0) if task.held else (1, TIER_ORDER[st.tier])
            daily.append(((*group, last or epoch, sym), task))
    tasks += [t for _, t in sorted(daily, key=lambda x: x[0])]
    tasks += [t for _, t in sorted(first, key=lambda x: x[0])]
    return tasks


_LOCAL_LOCK = threading.Lock()


@contextlib.contextmanager
def pass_lock(db: Session) -> Iterator[bool]:
    """One pass at a time: in this process (a lock) and across processes on Postgres (``pg_try_advisory_lock`` on a
    connection of its own, released when the pass ends). Yields whether the pass may run."""
    if not _LOCAL_LOCK.acquire(blocking=False):
        yield False
        return
    try:
        bind = db.get_bind()
        engine = bind.engine if isinstance(bind, Connection) else bind
        if engine.dialect.name != "postgresql":
            yield True
            return
        with engine.connect() as conn:
            got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar())
            conn.commit()
            try:
                yield got
            finally:
                if got:
                    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
                    conn.commit()
    finally:
        _LOCAL_LOCK.release()


def refresh_langsearch(db: Session, md: MarketData, settings: Settings | None = None, now: datetime | None = None,
                       *, client: LangSearchClient | None = None, ranks: Callable[[], Mapping[str, int]] | None = None,
                       held: set[str] | None = None, clock: Callable[[], datetime] = now_utc,
                       sleep: Callable[[float], None] = _time.sleep,
                       deadline_seconds: float | None = None) -> LangSearchReport:
    """One pass (module docstring). ``client`` / ``ranks`` / ``held`` / ``clock`` / ``sleep`` are for tests;
    ``clock`` is the wall clock: of the gap between requests (stored, so it holds across processes) and of when a
    pause starts (a long pass's outage pauses 15 minutes from the failure, not from the pass's start)."""
    settings = settings or get_settings()
    rep = LangSearchReport()
    if not (settings.news_enabled and settings.news_langsearch_enabled):
        rep.skipped = "off"
        return rep
    now = now or now_utc()
    if now.astimezone(TAIPEI).time() < ACTIVE_FROM:
        rep.skipped = "night"
        return rep
    own_client = client is None
    if client is None:
        client = LangSearchClient.from_settings(settings)
        if client is None:
            rep.skipped = "no_key"
            return rep
    try:
        with pass_lock(db) as got:
            if not got:
                rep.skipped = "busy"
                return rep
            if not service._source_open(db, SOURCE_KEY, now):
                rep.skipped = "paused"
                return rep
            _run_pass(db, md, settings, now, client, rep, ranks=ranks, held=held, clock=clock, sleep=sleep,
                      deadline_seconds=deadline_seconds)
    finally:
        if own_client:
            client.close()
    if rep.requests or rep.stopped:
        log.info("LangSearch pass: %d requests (%d tokens), %d topics, %d stocks (%d first fills), %d headlines kept, "
                 "%d new, ladder %d, cap %d%s; dropped %s", rep.requests, rep.tokens, rep.topics, rep.symbols,
                 rep.first_fills, rep.kept, rep.stored, rep.level, rep.cap,
                 f", stopped: {rep.stopped}" if rep.stopped else "", dict(rep.drops))
    return rep


def _run_pass(db: Session, md: MarketData, settings: Settings, now: datetime, client: LangSearchClient,
              rep: LangSearchReport, *, ranks: Callable[[], Mapping[str, int]] | None, held: set[str] | None,
              clock: Callable[[], datetime], sleep: Callable[[float], None], deadline_seconds: float | None) -> None:
    started = _time.monotonic()
    today = _utc_day(now)
    purge_bookkeeping(db, today)
    lad, rep.cap = day_cap(db, settings, today)
    rep.level = lad.level
    tasks = plan(db, md, settings, now, lad, ranks=ranks, held=held)
    if not tasks:
        return
    blocked = service.blocked_domains(db, settings)
    junk = [d.lower().removeprefix("www.") for d in settings.news_langsearch_junk_domains]
    guard = settings.news_langsearch_token_guard
    source = LangSearchSource(client, guard, now_fn=clock)
    interval = settings.news_langsearch_interval_seconds
    keep_from = now - timedelta(days=settings.news_retention_days)  # older rows are purged: never stored
    first_fills = first_fills_on(db, today)
    errors = 0
    paced = False
    for task in tasks:
        if deadline_seconds is not None and _time.monotonic() - started > deadline_seconds:
            rep.stopped = "deadline"
            break
        usage = read_usage(db, today)
        if usage.requests >= rep.cap:
            rep.stopped = "requests_cap"
            break
        if usage.tokens >= settings.news_langsearch_max_tokens_per_day:
            rep.stopped = "tokens_cap"
            break
        if task.first_fill and first_fills >= settings.news_langsearch_max_first_fill_per_day:
            continue
        if not paced:
            _wait_gap(db, interval, clock, sleep)
            paced = True
        fresh = task.fresh
        since = max(window_start(fresh, now) - GRACE, keep_from)
        q = _topic_query(now, since) if task.topic else service.build_query(db, task.info, since, now, md)
        row = _row(db, task.key)
        row.last_attempt_at = now
        _count_request(db, today, clock(), first_fill=task.first_fill)  # counted before it is sent
        rep.requests += 1
        if task.first_fill:
            first_fills += 1
        err: Exception | None = None
        raw: list[RawItem] = []
        try:
            raw = source.fetch(q, query=task.query, fresh=fresh, count=task.count)
        except Exception as exc:
            err = exc
        _sent(db, today, clock())  # after the limiter's wait: the next process measures its gap from here
        reply = source.last
        if reply is not None:
            _count_tokens(db, today, reply.tokens)
            rep.tokens += reply.tokens
            log.info("LangSearch %s: HTTP %d in %.1f s, %d results, %d+%d tokens", task.query if task.topic
                     else task.store_as, reply.status, reply.latency, len(_values(reply.payload or {}) or []),
                     reply.input_tokens, reply.output_tokens)
        why = _book_outcome(db, today, clock(), err, guard)  # the wall clock: a pause runs from the failure
        if isinstance(err, SourceDown):
            row.last_status = "unreachable"
            db.commit()
            if why:
                rep.stopped = why
                break
            continue
        if why:
            row.last_status = "blocked"
            db.commit()
            rep.stopped = why
            break
        if err is not None:  # another 4xx, an unusable answer: this query only
            errors += 1
            rep.errors += 1
            row.last_status, row.failures = "error", (row.failures or 0) + 1
            db.commit()
            log.warning("LangSearch for %s failed: %s", task.query if task.topic else task.store_as, str(err)[:160])
            if errors >= MAX_ERRORS_IN_A_ROW:
                rep.stopped = "errors"
                break
            continue
        errors = 0
        heads = filter_items(raw, q, blocked, junk, topic=task.topic, drops=rep.drops, keep_from=keep_from)
        rep.kept += len(heads)
        rep.stored += service.store(db, task.store_as, heads, now)
        row = _row(db, task.key)
        row.last_success_at, row.last_status, row.items, row.failures = now, "ok" if heads else "empty", len(heads), 0
        db.commit()
        service._mark_open(db, SOURCE_KEY, clock())
        if task.topic:
            rep.topics += 1
            continue
        rep.symbols += 1
        rep.first_fills += int(task.first_fill)
        st = read_tier(db, task.key) or TierState(task.tier or "mid", set_at=now)
        write_tier(db, task.key, after_run(st, len(heads), now, settings), now)


def _book_outcome(db: Session, today: date, at: datetime, err: Exception | None, guard: int) -> str | None:
    """What one request's outcome means for the whole source — the worker's pass and the manual check alike. A
    5xx / timeout is one more in a row (:func:`_note_down`, kept across passes): :data:`DOWN_IN_A_ROW` in a row pause
    the source 15 minutes from ``at``, doubling up to 4 hours (``unreachable``). Anything else is an answer and ends
    that run; a refusal — the contents cap ignored, the quota, 401 / 403 / a redirect — stops the source until the
    next 00:00 UTC and the day's row says why (``contract`` / ``quota`` / ``blocked``). ``None``: nothing to stop
    for."""
    if isinstance(err, SourceDown):
        if _note_down(db, at) >= DOWN_IN_A_ROW:
            service._mark_blocked(db, SOURCE_KEY, at, str(err), service.BACKOFF_START, status="unreachable")
            return "unreachable"
        return None
    _note_answered(db)
    if not isinstance(err, SourceBlocked):
        return None
    # SourceBlocked itself: 401 / 403 / a redirect
    why = "contract" if isinstance(err, LangSearchContract) else "quota" if isinstance(err, LangSearchQuota) \
        else "blocked"
    if why == "contract":
        log.warning("LangSearch: an answer of more than %d output tokens — the contents cap was ignored; stopped "
                    "until 00:00 UTC", guard)
    _mark_day(db, today, why, at)
    service._mark_blocked(db, SOURCE_KEY, at, str(err), status="rate_limited" if why == "quota" else "blocked",
                          until=err.until or next_utc_midnight(at))
    return why


# -- the manual check ---------------------------------------------------------------------------------------------
SMOKE_QUERY = "台積電"
SMOKE_COUNT = 20


@dataclass
class SmokeResult:
    skipped: str | None = None  # off | no_key | busy | paused | requests_cap | tokens_cap (nothing was sent)
    paused_until: datetime | None = None
    reply: Reply | None = None
    items: int = 0
    error: str | None = None  # why the one request failed (no part of the answer)
    stopped: str | None = None  # quota | contract | blocked | unreachable: booked, the worker stops too

    @property
    def passed(self) -> bool:
        return (self.reply is not None and self.error is None and self.items == SMOKE_COUNT
                and self.reply.tokens < 200)


def smoke(db: Session, settings: Settings, client: LangSearchClient, *, clock: Callable[[], datetime] = now_utc,
          sleep: Callable[[float], None] = _time.sleep) -> SmokeResult:
    """One request (「"台積電"」, ``oneDay``, count 20) under the worker's rules: nothing while switched off, paused (a
    refusal or an outage) or past the UTC day's caps; one pass at a time (:func:`pass_lock`); the gap to the last
    request of any process waited out; counted in the day's usage (requests, tokens, the time sent); and its outcome
    booked like a pass's (:func:`_book_outcome`): a refusal stops the worker until 00:00 UTC too."""
    res = SmokeResult()
    if not (settings.news_enabled and settings.news_langsearch_enabled):
        res.skipped = "off"
        return res
    with pass_lock(db) as got:
        if not got:
            res.skipped = "busy"
            return res
        now = clock()
        today = _utc_day(now)
        if not service._source_open(db, SOURCE_KEY, now):
            wide = db.get(NewsFetchState, (SOURCE_KEY, service.SOURCE_WIDE))
            res.skipped, res.paused_until = "paused", _aware(wide.backoff_until) if wide is not None else None
            return res
        usage = read_usage(db, today)
        _, cap = day_cap(db, settings, today)
        if usage.requests >= cap:
            res.skipped = "requests_cap"
            return res
        if usage.tokens >= settings.news_langsearch_max_tokens_per_day:
            res.skipped = "tokens_cap"
            return res
        _wait_gap(db, settings.news_langsearch_interval_seconds, clock, sleep)
        body = request_body(stock_query(SMOKE_QUERY), "oneDay", SMOKE_COUNT)
        _count_request(db, today, clock(), first_fill=False)
        err: Exception | None = None
        try:
            res.reply = client.post(body)
            res.items = len(interpret(res.reply, clock(), settings.news_langsearch_token_guard))
        except Exception as exc:
            err = exc
            res.error = str(exc)[:160]
        _sent(db, today, clock())
        if res.reply is not None:
            _count_tokens(db, today, res.reply.tokens)
        res.stopped = _book_outcome(db, today, clock(), err, settings.news_langsearch_token_guard)
        if err is None:
            service._mark_open(db, SOURCE_KEY, clock())
    return res


# -- status (CLI, /admin) -----------------------------------------------------------------------------------------
def status(db: Session, settings: Settings | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Today's usage, the ladder, the pause and the tiers (counts only)."""
    settings = settings or get_settings()
    now = now or now_utc()
    today = _utc_day(now)
    usage = read_usage(db, today)
    lad, cap = day_cap(db, settings, today)
    wide = db.get(NewsFetchState, (SOURCE_KEY, service.SOURCE_WIDE))
    until = _aware(wide.backoff_until) if wide is not None else None
    tiers = Counter(r.last_status for r in db.scalars(select(NewsFetchState).where(
        NewsFetchState.source == SOURCE_KEY, NewsFetchState.symbol.like(TIER_PREFIX + "%"))))
    return {
        "enabled": settings.news_langsearch_enabled, "configured": settings.langsearch_on, "day_utc": today.isoformat(),
        "requests": usage.requests, "request_cap": cap, "tokens": usage.tokens,
        "token_cap": settings.news_langsearch_max_tokens_per_day, "first_fills": first_fills_on(db, today),
        "stopped": usage.stopped or None, "level": lad.level,
        "paused_until": until if until is not None and until > now else None,
        "warning": "contents_cap_ignored" if usage.stopped == "contract" else None,
        "tiers": {t: tiers.get(t, 0) for t in TIERS},
    }
