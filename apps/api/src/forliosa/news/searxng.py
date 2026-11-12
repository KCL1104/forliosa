"""Our private SearXNG (``deploy/searxng``) as a news source — **on by default** (product owner 2026-11-12, third
round; ``PRODUCT.md`` 「相關新聞」, ``docs/research/news-and-external-sources.md`` §10).

SearXNG is a metasearch engine: it asks upstream search engines (``deploy/searxng/settings.yml`` enables only the
news engines Bing News, DuckDuckGo News and Brave News, which link to the publisher's page) and merges their answers.
Querying those engines automatically breaks their terms; the product owner accepted that risk. It is reachable only
over private networking (Railway ``searxng.railway.internal``, or ``127.0.0.1`` in local development).

Query (:meth:`SearxngSource.params`)
    Taiwan stocks in Chinese — ``台積電 2330`` with ``language=zh-TW``; US stocks with the English short name and the
    code — ``NVIDIA NVDA`` with ``language=en``; always ``categories=news``, ``time_range=week``, ``format=json``,
    ``safesearch=0``. While some engines are paused the request names the others (``engines=bing news,…``) instead of
    ``categories=news``: SearXNG would add every news engine back if ``categories`` were sent too.

Answer (:func:`parse_searxng`)
    Only ``title``, ``url``, the publication time and the engine names are read — never ``content``, thumbnails or
    images. The time is ``publishedDate`` (ISO; a time without an offset is UTC, the container's clock); without it
    a relative age in ``pubdate`` / ``metadata`` (「3 hours ago」「3 小時前」「昨天」; days give a date only); a result
    with neither is skipped. A search-engine redirect (``news.google.com/articles/…``,
    ``bing.com/news/apiclick.aspx``) is dropped, not resolved; an AMP-cache link is unwrapped
    (:mod:`forliosa.news.normalize`). The caller applies the relevance filter, outlet names, the takedown blocklist
    and de-duplication with GDELT, as for every source.

Health
    * The instance: connection refused, DNS, timeout, HTTP 5xx or not JSON -> :class:`SourceDown`; HTTP 403 / 429
      from our own instance (JSON output off, limiter on) -> :class:`SourceBlocked`. The service then pauses the
      whole source (15 minutes doubling to 4 hours / ``NEWS_SEARXNG_BACKOFF_MINUTES``); GDELT and the AI fallback
      continue and nobody sees an error.
    * Each upstream engine (``unresponsive_engines``): a refusal — CAPTCHA, "too many requests", "access denied",
      also when SearXNG reports it as ``Suspended: …`` — pauses that engine (``NEWS_SEARXNG_BACKOFF_MINUTES``,
      doubling up to 24 h); three timeouts / errors in a row pause it for 15 minutes, doubling. Every engine we asked
      failing in one answer pauses SearXNG as a whole. Never another IP, never a proxy, never a different client.
    * Pacing: one query at a time per process (the worker is the only regular caller), at least
      ``NEWS_SEARXNG_INTERVAL_SECONDS`` (10) from the end of one query to the start of the next (:class:`QueryGate`).

``python -m forliosa.news searxng-check "台積電"`` runs one query and prints the results per engine.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from datetime import time as dtime
from typing import Any
from urllib.parse import urlsplit

import httpx

from forliosa.config import DEFAULT_SEARXNG_ENGINES
from forliosa.marketdata.base import ProviderUnavailable
from forliosa.marketdata.http import HttpFetcher, HttpStatusError, RateLimiter
from forliosa.news.normalize import is_search_redirect, unwrap_amp_cache
from forliosa.news.sources import Query, RawItem, SourceBlocked, SourceDown
from forliosa.timeutil import TAIPEI, now_utc

USER_AGENT = "forliosa/0.1 (portfolio tracker; news headline index)"
REFUSAL_STATUSES = frozenset({403, 429, 451})
# Reasons in ``unresponsive_engines`` that mean the upstream engine refused SearXNG (searx/webutils.py
# exception_classname_to_text; settings.yml keeps the interface in English so these stay machine-readable).
_REFUSAL_WORDS = ("captcha", "too many requests", "access denied", "rate limit", "forbidden", "blocked",
                  "驗證碼", "請求過多", "拒絕存取", "存取遭拒")


def engine_refused(reason: str) -> bool:
    """``CAPTCHA``, ``too many requests``, ``access denied`` (also ``Suspended: CAPTCHA``) — not a timeout."""
    r = (reason or "").casefold()
    return any(w in r for w in _REFUSAL_WORDS)


# -- publication time -------------------------------------------------------------------------------------------
_UNITS = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1, "m": 60, "min": 60, "mins": 60, "minute": 60,
          "minutes": 60, "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600, "d": 86400, "day": 86400,
          "days": 86400, "w": 604800, "wk": 604800, "wks": 604800, "week": 604800, "weeks": 604800,
          "秒": 1, "分": 60, "分鐘": 60, "分钟": 60, "小時": 3600, "小时": 3600, "天": 86400, "日": 86400,
          "週": 604800, "周": 604800, "星期": 604800}
_REL_EN = re.compile(r"^(?P<n>\d+|an?|one)\s*(?P<u>[a-z]+)\.?(?:\s+ago)?$", re.IGNORECASE)
_ZH_UNIT = "(?P<u>秒|分鐘|分钟|分|小時|小时|天|日|週|周|星期)"
_REL_ZH_ALONE = re.compile(rf"^(?P<n>\d+)\s*{_ZH_UNIT}\s*前?$")  # the whole part: 「3小時」「3 小時前」
_REL_ZH = re.compile(rf"(?P<n>\d+)\s*{_ZH_UNIT}\s*前")  # inside a longer part: 「經濟日報 3 小時前」
_YESTERDAY = re.compile(r"^(yesterday|昨天|昨日)$", re.IGNORECASE)


def relative_age(text: str) -> tuple[timedelta, bool] | None:
    """「3 hours ago」「3h」「an hour ago」「3 小時前」「昨天」 -> (age, only the day is known). ``None`` otherwise."""
    t = " ".join((text or "").split())
    if not t:
        return None
    if _YESTERDAY.match(t):
        return timedelta(days=1), True
    m = _REL_EN.match(t)
    unit = m.group("u").lower() if m else None
    if m is None or unit not in _UNITS:
        m = _REL_ZH_ALONE.match(t) or _REL_ZH.search(t)
        unit = m.group("u") if m else None
    if m is None or unit is None:
        return None
    raw = m.group("n").lower()
    n = 1 if raw in ("a", "an", "one") else int(raw)
    seconds = _UNITS[unit] * n
    return timedelta(seconds=seconds), seconds >= 86400


def _iso(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)  # SearXNG's container clock is UTC


def published_time(result: dict[str, Any], now: datetime | None) -> tuple[datetime, bool] | None:
    """A result's publication time and whether only its day is known: ``publishedDate``, else ``pubdate`` (ISO or
    a relative age), else a relative age among the ``metadata`` parts (Bing News: 「3 小時前 | 經濟日報」)."""
    value = result.get("publishedDate")
    if isinstance(value, str) and value.strip() and (dt := _iso(value)) is not None:
        return dt, False
    candidates: list[str] = []
    pub = result.get("pubdate")
    if isinstance(pub, str) and pub.strip():
        if (dt := _iso(pub)) is not None:
            return dt, False
        candidates.append(pub)
    meta = result.get("metadata")
    if isinstance(meta, str):
        candidates += re.split(r"\s*[|·•]\s*", meta)
    if now is None:
        return None
    for c in candidates:
        rel = relative_age(c)
        if rel is None:
            continue
        age, day_only = rel
        when = now - age
        if day_only:
            day = when.astimezone(TAIPEI).date()
            return datetime.combine(day, dtime(0, 0), TAIPEI).astimezone(UTC), True
        return when, False
    return None


# -- the answer -------------------------------------------------------------------------------------------------
@dataclass
class SearxngAnswer:
    items: list[RawItem] = field(default_factory=list)
    results: int = 0  # results in the answer (before anything was dropped)
    per_engine: Counter[str] = field(default_factory=Counter)  # a result two engines found counts for both
    unresponsive: list[tuple[str, str]] = field(default_factory=list)  # (engine, reason) as SearXNG reported it
    no_date: int = 0
    redirects: int = 0

    @property
    def refused(self) -> list[str]:
        return [e for e, reason in self.unresponsive if engine_refused(reason)]


def parse_searxng(data: dict[str, Any], now: datetime | None = None) -> SearxngAnswer:
    """SearXNG ``/search?format=json`` (searx/webutils.py ``get_json_response``: ``query``, ``results``,
    ``answers``, ``corrections``, ``infoboxes``, ``suggestions``, ``unresponsive_engines``) -> the headlines and
    what each engine did. ``now`` (when the answer arrived) dates relative ages."""
    ans = SearxngAnswer()
    for row in data.get("unresponsive_engines") or []:
        if isinstance(row, list | tuple) and row:
            ans.unresponsive.append((str(row[0]), str(row[1]) if len(row) > 1 else ""))
        elif isinstance(row, str):
            ans.unresponsive.append((row, ""))
    for r in data.get("results") or []:
        if not isinstance(r, dict):
            continue
        ans.results += 1
        engines = r.get("engines") or ([r["engine"]] if r.get("engine") else [])
        for e in dict.fromkeys(str(x) for x in engines if x):
            ans.per_engine[e] += 1
        title, url = str(r.get("title") or "").strip(), str(r.get("url") or "").strip()
        if not title or not url:
            continue
        url = unwrap_amp_cache(url)
        if is_search_redirect(url):
            ans.redirects += 1
            continue
        when = published_time(r, now)
        if when is None:
            ans.no_date += 1
            continue
        ans.items.append(RawItem(title=title, url=url, published_at=when[0], date_only=when[1]))
    return ans


# -- pacing -----------------------------------------------------------------------------------------------------
class QueryGate:
    """One query at a time; at least ``interval`` seconds from the end of one query to the start of the next."""

    def __init__(self, interval: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.interval = interval
        self._clock, self._sleep = clock, sleep
        self._lock = threading.Lock()
        self._last_end: float | None = None
        self.waited = 0.0

    @contextmanager
    def turn(self) -> Iterator[None]:
        with self._lock:
            if self._last_end is not None:
                wait = self.interval - (self._clock() - self._last_end)
                if wait > 0:
                    self._sleep(wait)
                    self.waited += wait
            try:
                yield
            finally:
                self._last_end = self._clock()


_GATES: dict[str, QueryGate] = {}
_GATES_LOCK = threading.Lock()


def gate_for(base_url: str, interval: float) -> QueryGate:
    """The process-wide gate of one SearXNG instance (shared by every :class:`SearxngSource` for it)."""
    with _GATES_LOCK:
        g = _GATES.get(base_url)
        if g is None:
            g = _GATES[base_url] = QueryGate(interval)
        g.interval = max(g.interval, interval)
        return g


def reset_gates() -> None:
    with _GATES_LOCK:
        _GATES.clear()


# -- HTTP -------------------------------------------------------------------------------------------------------
_transport: httpx.BaseTransport | None = None


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Tests: every SearXNG request goes through this transport (``None``: the network)."""
    global _transport
    _transport = transport


def searxng_fetcher(base_url: str, timeout: float = 20.0) -> HttpFetcher:
    """Only ``<base>/search`` and ``<base>/healthz`` of the configured instance; an honest client name; no retry
    (an unreachable instance is paused, not hammered); a redirect is a refusal (never followed)."""
    base = base_url.rstrip("/")
    client = httpx.Client(timeout=httpx.Timeout(timeout, connect=5.0), follow_redirects=False, transport=_transport,
                          headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    return HttpFetcher(client=client, limiter=RateLimiter(), retries=0, extra_allowed=(f"{base}/search",
                                                                                         f"{base}/healthz"))


def display_url(base_url: str) -> str:
    """``scheme://host[:port]`` without any user name or password (for logs and the CLI)."""
    try:
        parts = urlsplit(base_url)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return "(invalid URL)"
    return f"{parts.scheme}://{host}{port}"


def query_text(q: Query) -> str:
    """``台積電 2330``; US: ``NVIDIA NVDA`` (the English short name, then the code)."""
    if q.taiwan:
        return f"{q.name} {q.code}"
    english = next((e for e in (*q.english, q.name) if e and e.casefold() != q.code.casefold()), "")
    return f"{english} {q.code}".strip()


class SearxngSource:
    key = "searxng"
    label = "SearXNG"

    def __init__(self, base_url: str, fetcher: HttpFetcher | None = None, *,
                 engines: Sequence[str] = DEFAULT_SEARXNG_ENGINES, interval: float = 10.0, timeout: float = 20.0,
                 gate: QueryGate | None = None, now_fn: Callable[[], datetime] = now_utc):
        self.base_url = base_url.rstrip("/")
        self.fetcher = fetcher or searxng_fetcher(self.base_url, timeout)
        self.engines = tuple(engines)
        self.gate = gate or gate_for(self.base_url, interval)
        self.now_fn = now_fn
        self.paused: frozenset[str] = frozenset()  # engines not to ask (set by the service before each query)
        self.last: SearxngAnswer | None = None  # the last answer, also when fetch raised (engine bookkeeping)
        self.last_asked: tuple[str, ...] = ()

    def supports(self, q: Query) -> bool:
        return True

    def active_engines(self) -> list[str]:
        return [e for e in self.engines if e not in self.paused]

    def params(self, q: Query) -> dict[str, Any]:
        out: dict[str, Any] = {"q": query_text(q), "format": "json", "language": "zh-TW" if q.taiwan else "en",
                               "time_range": "week", "safesearch": 0, "pageno": 1}
        if self.paused:
            out["engines"] = ",".join(self.active_engines())
        else:
            out["categories"] = "news"
        return out

    def search(self, params: dict[str, Any]) -> SearxngAnswer:
        """One ``/search`` request through the gate. Raises :class:`SourceDown` / :class:`SourceBlocked`."""
        try:
            with self.gate.turn():
                raw = self.fetcher.get_bytes(f"{self.base_url}/search", params=params)
        except HttpStatusError as exc:
            if exc.status in REFUSAL_STATUSES:
                raise SourceBlocked(f"SearXNG HTTP {exc.status} (limiter on or JSON output off?)") from exc
            raise SourceDown(f"SearXNG HTTP {exc.status}") from exc
        except ProviderUnavailable as exc:
            raise SourceDown(f"SearXNG at {display_url(self.base_url)} unreachable") from exc
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise SourceDown("SearXNG did not answer JSON") from exc
        if not isinstance(data, dict):
            raise SourceDown("SearXNG answered an unexpected shape")
        return parse_searxng(data, self.now_fn())

    def fetch(self, q: Query) -> list[RawItem]:
        self.last, self.last_asked = None, ()
        asked = self.active_engines()
        if self.engines and not asked:
            raise SourceBlocked("every SearXNG engine is paused")
        self.last_asked = tuple(asked)
        ans = self.search(self.params(q))
        self.last = ans
        failed = {e for e, _ in ans.unresponsive}
        considered = set(asked) or failed  # no engine list configured: the engines SearXNG reported
        if considered and considered <= failed and not ans.results:
            reasons = "; ".join(f"{e}: {r}" for e, r in ans.unresponsive)[:200]
            if all(engine_refused(r) for e, r in ans.unresponsive if e in considered):
                raise SourceBlocked("every SearXNG engine refused: " + reasons)
            raise SourceDown("every SearXNG engine failed: " + reasons)
        return ans.items

    def health(self) -> tuple[bool, str]:
        """``/healthz`` answers ``OK``."""
        try:
            raw = self.fetcher.get_bytes(f"{self.base_url}/healthz")
        except HttpStatusError as exc:
            return False, f"HTTP {exc.status}"
        except ProviderUnavailable:
            return False, "無法連線"
        ok = raw.strip() == b"OK"
        return ok, "OK" if ok else "回應不是 OK"
