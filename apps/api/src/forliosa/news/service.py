"""Collect, store and serve the 「新聞報導」 headlines (metadata only).

Refresh (worker job ``news_refresh``, every ``NEWS_REFRESH_MINUTES``; also ``python -m forliosa.news refresh``)
-----------------------------------------------------------------------------------------------------------
* **Which symbols**: tracked ones — in any ledger, holdings snapshot or watchlist (``archive.tracked_symbols``),
  or viewed in the last ``NEWS_VIEW_DAYS`` days (``news_tracked_views``: symbol + time only, no user ids) — the
  stalest first, at most ``NEWS_MAX_SYMBOLS_PER_RUN``. Shared by everyone.
* **Sources** (:mod:`forliosa.news.sources`): GDELT (default), SearXNG (only with ``NEWS_SEARXNG_URL``), Yahoo股市
  RSS (only under ``DATA_POLICY=personal``). One request per symbol per source; the HTTP limiter spaces GDELT
  requests ≥ ``NEWS_GDELT_INTERVAL_SECONDS`` (≥ 5 s). A 429 / block stops that source for the run and backs it off
  (15 min, doubling to 4 h; ``news_fetch_state`` row ``symbol = "*"``); three failures in a row also stop it for the
  run. Never another IP, never a disguised client.
* **AI fallback** (:mod:`forliosa.news.ai_search`): only when GDELT answered for the symbol (or is off) and the
  free sources hold fewer than ``NEWS_AI_MIN_ITEMS`` headlines from the last 7 days; once per
  ``NEWS_AI_INTERVAL_HOURS`` per symbol, at most ``AI_MAX_PER_RUN`` per run, while the month's budget lasts.
* **Every headline** goes through :mod:`forliosa.news.normalize`: GDELT spacing removed, outlet / section suffix
  removed, the outlet named from its domain, kept only when the title names the company (Chinese short name,
  code or English short name), never from a blocked domain, newer than the query window; stored once per
  (symbol, normalised URL). Deleted ``NEWS_RETENTION_DAYS`` after publication.

Read (``GET /instruments/{symbol}/news``)
----------------------------------------
:func:`media_items`: the symbol's stored headlines of the retention window, Yahoo RSS rows only under
``personal``, blocked domains hidden, de-duplicated (same URL or near-identical title; the original outlet beats an
aggregator copy), newest first, at most ``MEDIA_LIMIT``. :func:`record_view` notes that the symbol was viewed.
"""

from __future__ import annotations

import logging
import time as _time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from forliosa.config import Settings, get_settings
from forliosa.datapolicy import Policy, labels
from forliosa.marketdata.base import InstrumentInfo
from forliosa.marketdata.http import HttpFetcher, RateLimiter
from forliosa.marketdata.service import MarketData
from forliosa.models import CompanyProfile, NewsArticle, NewsBlockedDomain, NewsFetchState, NewsTrackedView
from forliosa.news.normalize import (
    Headline,
    clean_title,
    clean_url,
    dedupe,
    is_blocked,
    is_relevant,
    make_terms,
    normalize_domain,
    url_key,
)
from forliosa.news.outlets import host_of, outlet_name
from forliosa.news.sources import (
    GdeltSource,
    NewsSource,
    Query,
    RawItem,
    SearxngSource,
    SourceBlocked,
    YahooRssSource,
)
from forliosa.timeutil import iso_taipei, now_utc

log = logging.getLogger(__name__)

WINDOW = timedelta(days=7)  # how far back a source is asked, and the AI fallback's count window
OVERLAP = timedelta(hours=1)  # re-ask an hour before the last success (GDELT indexes with a delay)
MEDIA_LIMIT = 40
AI_MAX_PER_RUN = 10
MAX_FAILURES_PER_RUN = 3
BACKOFF_START = timedelta(minutes=15)
BACKOFF_MAX = timedelta(hours=4)
VIEW_WRITE_EVERY = timedelta(minutes=10)
GDELT_FRESH = timedelta(hours=24)  # the AI fallback needs a GDELT answer this recent
SOURCE_WIDE = "*"
FREE_SOURCES = ("gdelt", "searxng", "yahoo_rss")
# news_articles.source -> (label shown with the headline, attribution key for ``sources``)
SOURCE_INFO: dict[str, tuple[str, str]] = {
    "gdelt": ("GDELT", "gdelt/doc"),
    "ai_search": ("AI 搜尋", "ai-search"),
    "searxng": ("SearXNG", "searxng"),
    "yahoo_rss": ("Yahoo股市", "yahoo-rss/stock"),
    "finmind": ("FinMind", "finmind"),
}
PERSONAL_ONLY_SOURCES = frozenset({"yahoo_rss", "finmind"})


# -- blocklist ----------------------------------------------------------------------------------------------
def blocked_domains(db: Session, settings: Settings | None = None) -> list[str]:
    """The takedown blocklist: the ``news_blocked_domains`` table plus ``NEWS_BLOCKED_DOMAINS``."""
    settings = settings or get_settings()
    rows = list(db.scalars(select(NewsBlockedDomain.domain)))
    return sorted({*(normalize_domain(d) for d in rows), *(normalize_domain(d) for d in settings.news_blocked_domains)}
                  - {""})


def block_domain(db: Session, domain: str, reason: str | None = None) -> int:
    """Add a domain (subdomains included) and delete its stored headlines. Returns how many were deleted."""
    d = normalize_domain(domain)
    if not d or "." not in d:
        raise ValueError(f"not a domain: {domain!r}")
    row = db.get(NewsBlockedDomain, d)
    if row is None:
        db.add(NewsBlockedDomain(domain=d, reason=reason, created_at=now_utc()))
    elif reason:
        row.reason = reason
    ids = [a.id for a in db.scalars(select(NewsArticle)) if is_blocked(a.url, [d]) or is_blocked(a.domain, [d])]
    if ids:
        db.execute(delete(NewsArticle).where(NewsArticle.id.in_(ids)))
    db.commit()
    return len(ids)


def unblock_domain(db: Session, domain: str) -> bool:
    row = db.get(NewsBlockedDomain, normalize_domain(domain))
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


# -- tracked symbols ----------------------------------------------------------------------------------------
def record_view(db: Session, symbol: str, now: datetime | None = None) -> None:
    """Note that ``symbol``'s news was viewed (symbol and time only). Written at most every 10 minutes."""
    now = now or now_utc()
    row = db.get(NewsTrackedView, symbol)
    if row is not None and row.last_viewed_at and now - _aware(row.last_viewed_at) < VIEW_WRITE_EVERY:
        return
    if row is None:
        db.add(NewsTrackedView(symbol=symbol, last_viewed_at=now))
    else:
        row.last_viewed_at = now
    db.commit()


def tracked(db: Session, settings: Settings, now: datetime) -> list[str]:
    """Held / watched symbols plus those viewed in the last ``NEWS_VIEW_DAYS`` days, stalest GDELT fetch first."""
    from forliosa.archive import tracked_symbols

    since = now - timedelta(days=settings.news_view_days)
    viewed = db.scalars(select(NewsTrackedView.symbol).where(NewsTrackedView.last_viewed_at >= since))
    symbols = sorted({*tracked_symbols(db), *viewed})
    last = {s.symbol: _aware(s.last_attempt_at) for s in db.scalars(
        select(NewsFetchState).where(NewsFetchState.source == "gdelt"))}
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    symbols.sort(key=lambda s: last.get(s) or epoch)
    return symbols[:settings.news_max_symbols_per_run]


# -- queries ------------------------------------------------------------------------------------------------
def english_names(db: Session, info: InstrumentInfo) -> list[str]:
    """English short names: the archived company profile's 英文簡稱 / ``Symbol`` (「TSMC」「Gudeng」), then ASCII
    aliases; US stocks: the company name."""
    out: list[str] = []
    if info.market == "US":
        out.append(info.name)
    else:
        prof = db.get(CompanyProfile, info.symbol)
        value = ((prof.values or {}).get("english_short_name") if prof is not None else None) or ""
        if value.strip():
            out.append(" ".join(value.split()))
    out += [a for a in info.aliases if a.isascii()]
    seen: set[str] = set()
    result = []
    for n in out:
        if n.casefold() not in seen and len(n) >= 3:
            seen.add(n.casefold())
            result.append(n)
    return result


def build_query(db: Session, info: InstrumentInfo, since: datetime, until: datetime) -> Query:
    english = english_names(db, info)
    extra = [a for a in info.aliases if not a.isascii()] if info.market == "US" else []
    terms = make_terms(info.name, info.code, english, extra)
    return Query(symbol=info.symbol, code=info.code, name=info.name, market=info.market, english=tuple(english),
                 terms=terms, since=since, until=until)


# -- normalising and storing --------------------------------------------------------------------------------
def to_headlines(items: Iterable[RawItem], q: Query, source: str, blocked: Sequence[str]) -> list[Headline]:
    """Raw items -> normalised, relevant, unblocked headlines inside the query window."""
    out: list[Headline] = []
    for it in items:
        url = clean_url(it.url)
        if url is None or is_blocked(url, blocked) or (it.domain and is_blocked(it.domain, blocked)):
            continue
        host = host_of(url)
        outlet = it.outlet or outlet_name(url, it.domain)
        title = clean_title(it.title, url, outlet)
        published = _aware(it.published_at)
        if not title or not is_relevant(title, q.terms):
            continue
        if published > q.until + timedelta(minutes=30):
            continue
        if published < q.since and not it.date_only:
            continue
        out.append(Headline(title=title, url=url, outlet=outlet[:100], domain=(it.domain or host)[:253],
                            published_at=min(published, q.until), source=source, date_only=it.date_only))
    return out


def store(db: Session, symbol: str, headlines: Iterable[Headline], now: datetime | None = None) -> int:
    """Insert new headlines (one per symbol and normalised URL; an existing row is left as it is). Returns how
    many rows were new."""
    rows = []
    seen: set[str] = set()
    for h in headlines:
        key = url_key(h.url)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"symbol": symbol, "url_key": key, "url": h.url, "title": h.title, "outlet": h.outlet,
                     "domain": h.domain, "published_at": h.published_at, "date_only": h.date_only,
                     "source": h.source, "fetched_at": now or now_utc()})
    if not rows:
        return 0
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    before = db.scalar(select(func.count()).select_from(NewsArticle).where(NewsArticle.symbol == symbol)) or 0
    db.execute(insert(NewsArticle).values(rows).on_conflict_do_nothing(index_elements=["symbol", "url_key"]))
    db.commit()
    after = db.scalar(select(func.count()).select_from(NewsArticle).where(NewsArticle.symbol == symbol)) or 0
    return after - before


def purge(db: Session, settings: Settings | None = None, now: datetime | None = None) -> int:
    """Delete headlines older than ``NEWS_RETENTION_DAYS`` and views older than the tracking window."""
    settings = settings or get_settings()
    now = now or now_utc()
    n = db.execute(delete(NewsArticle).where(
        NewsArticle.published_at < now - timedelta(days=settings.news_retention_days))).rowcount or 0
    db.execute(delete(NewsTrackedView).where(
        NewsTrackedView.last_viewed_at < now - timedelta(days=max(settings.news_view_days, 1) * 10)))
    db.commit()
    return n


# -- reading ------------------------------------------------------------------------------------------------
def _source_served(source: str, policy: Policy) -> bool:
    return policy == "personal" or source not in PERSONAL_ONLY_SOURCES


def item_out(h: Headline) -> dict[str, Any]:
    label, key = SOURCE_INFO.get(h.source, (h.source, h.source))
    return {"published_at": iso_taipei(h.published_at), "title": h.title, "source": label, "outlet": h.outlet,
            "url": h.url, "category": "media", "date_only": h.date_only, "sources": labels([key])}


def media_items(db: Session, md: MarketData, info: InstrumentInfo, *, settings: Settings | None = None,
                now: datetime | None = None, extra: Iterable[Headline] = (), limit: int = MEDIA_LIMIT
                ) -> list[dict[str, Any]]:
    """The symbol's media headlines for ``/news`` (see the module docstring). ``extra`` adds headlines from a
    per-request source (FinMind under ``personal``) before de-duplication."""
    settings = settings or get_settings()
    if not settings.news_enabled:
        return []
    now = now or now_utc()
    since = now - timedelta(days=settings.news_retention_days)
    blocked = blocked_domains(db, settings)
    rows = db.scalars(select(NewsArticle).where(NewsArticle.symbol == info.symbol, NewsArticle.published_at >= since)
                      .order_by(NewsArticle.published_at.desc()).limit(limit * 4))
    heads = [Headline(title=r.title, url=r.url, outlet=r.outlet, domain=r.domain, published_at=_aware(r.published_at),
                      source=r.source, date_only=bool(r.date_only)) for r in rows]
    heads += list(extra)
    heads = [h for h in heads if _source_served(h.source, md.policy) and not is_blocked(h.url, blocked)
             and not (h.domain and is_blocked(h.domain, blocked))]
    return [item_out(h) for h in dedupe(heads)[:limit]]


# -- refreshing ---------------------------------------------------------------------------------------------
def _aware(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime(1970, 1, 1, tzinfo=UTC)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _state(db: Session, source: str, symbol: str) -> NewsFetchState:
    row = db.get(NewsFetchState, (source, symbol))
    if row is None:
        row = NewsFetchState(source=source, symbol=symbol, last_status="", items=0, failures=0)
        db.add(row)
    return row


def backoff_until(failures: int, now: datetime, start: timedelta = BACKOFF_START) -> datetime:
    """``start`` after the first refusal, doubling each time, at most ``BACKOFF_MAX`` (or ``start`` when longer)."""
    return now + min(start * (2 ** max(failures - 1, 0)), max(BACKOFF_MAX, start))


def backoff_start(source: str, settings: Settings) -> timedelta:
    """SearXNG waits ``NEWS_SEARXNG_BACKOFF_MINUTES`` (120) after a refusal; the other sources 15 minutes."""
    if source == "searxng":
        return timedelta(minutes=settings.news_searxng_backoff_minutes)
    return BACKOFF_START


def news_fetcher(settings: Settings) -> HttpFetcher:
    """The HTTP client for news sources: an honest User-Agent, GDELT spaced ≥ 5 s, SearXNG and Yahoo spaced too,
    one retry after a dropped connection (never after a refusal)."""
    per_host = {"gdeltproject.org": settings.news_gdelt_interval_seconds, "tw.stock.yahoo.com": 3.0}
    extra: tuple[str, ...] = ()
    if settings.news_searxng_url:
        per_host[host_of(settings.news_searxng_url)] = settings.news_searxng_interval_seconds
        extra = (settings.news_searxng_url.rstrip("/") + "/search",)
    return HttpFetcher(timeout=30.0, limiter=RateLimiter(per_host=per_host), retries=1, backoff=10.0,
                       user_agent="forliosa/0.1 (portfolio tracker; news headline index)", extra_allowed=extra)


def default_sources(settings: Settings, policy: Policy, fetcher: HttpFetcher | None = None) -> list[NewsSource]:
    """GDELT (unless NEWS_GDELT_ENABLED=false), SearXNG (only with NEWS_SEARXNG_URL), Yahoo股市 RSS (only under
    DATA_POLICY=personal)."""
    fetcher = fetcher or news_fetcher(settings)
    out: list[NewsSource] = []
    if settings.news_gdelt_enabled:
        out.append(GdeltSource(fetcher))
    if settings.news_searxng_url:
        out.append(SearxngSource(settings.news_searxng_url, fetcher))
    if policy == "personal" and settings.news_yahoo_rss:
        out.append(YahooRssSource(fetcher))
    return out


@dataclass
class RefreshReport:
    symbols: int = 0
    fetched: dict[str, int] = field(default_factory=dict)  # source -> requests made
    stored: int = 0
    blocked_sources: list[str] = field(default_factory=list)
    ai_searches: int = 0
    ai_skipped: str | None = None  # why the AI fallback did not run at all (budget, off, no keys)
    errors: int = 0


AiFactory = Callable[[Session], Any]  # returns an object with ``run(q, now, blocked, record)`` or None


def _source_open(db: Session, source: str, now: datetime) -> bool:
    row = db.get(NewsFetchState, (source, SOURCE_WIDE))
    return row is None or row.backoff_until is None or _aware(row.backoff_until) <= now


def _mark_blocked(db: Session, source: str, now: datetime, reason: str,
                  start: timedelta = BACKOFF_START) -> None:
    row = _state(db, source, SOURCE_WIDE)
    row.failures = (row.failures or 0) + 1
    row.last_attempt_at, row.last_status = now, "rate_limited"
    row.backoff_until = backoff_until(row.failures, now, start)
    db.commit()
    log.warning("news source %s refused (%s); not asked again before %s", source, reason[:120],
                iso_taipei(row.backoff_until))


def _mark_open(db: Session, source: str, now: datetime) -> None:
    row = db.get(NewsFetchState, (source, SOURCE_WIDE))
    if row is not None and (row.failures or row.backoff_until):
        row.failures, row.backoff_until, row.last_status, row.last_success_at = 0, None, "ok", now
        db.commit()


def recent_free_count(db: Session, symbol: str, now: datetime) -> int:
    return db.scalar(select(func.count()).select_from(NewsArticle).where(
        NewsArticle.symbol == symbol, NewsArticle.source.in_(FREE_SOURCES),
        NewsArticle.published_at >= now - WINDOW)) or 0


def default_ai(settings: Settings) -> AiFactory:
    """The AI fallback when it may run now: on, web search on, keys configured and not exhausted."""

    def make(db: Session) -> Any:
        from forliosa.ai import store as ai_store
        from forliosa.ai.keypool import get_key_pool
        from forliosa.news.ai_search import AiSearch

        pool = get_key_pool()
        costs = ai_store.slot_month_costs(db)
        if not pool.available or not pool.ranked(costs):
            return None
        return AiSearch(pool, settings, costs)

    return make


def refresh(db: Session, md: MarketData, *, settings: Settings | None = None, sources: list[NewsSource] | None = None,
            ai: AiFactory | str | None = "default", symbols: list[str] | None = None,
            now_fn: Callable[[], datetime] = now_utc, deadline_seconds: float | None = None) -> RefreshReport:
    """One batch over the tracked symbols (see the module docstring). ``sources`` / ``ai`` / ``symbols`` are for
    tests and the CLI; by default they follow the settings and ``DATA_POLICY``. ``ai=None`` turns the AI fallback
    off for this run; ``"default"`` uses the key pool when ``NEWS_AI_ENABLED`` and ``AI_WEB_SEARCH`` allow it."""
    from forliosa.news import ai_search

    settings = settings or get_settings()
    report = RefreshReport()
    if not settings.news_enabled:
        return report
    started = _time.monotonic()
    now = now_fn()
    purge(db, settings, now)
    sources = default_sources(settings, md.policy) if sources is None else sources
    if not settings.news_ai_enabled or (ai == "default" and not settings.ai_web_search):
        ai = None
    elif ai == "default":
        ai = default_ai(settings)
    symbols = tracked(db, settings, now) if symbols is None else symbols
    blocked = blocked_domains(db, settings)
    open_sources = [s for s in sources if _source_open(db, s.key, now)]
    report.blocked_sources = [s.key for s in sources if s not in open_sources]
    failures: dict[str, int] = {}
    ai_runner: Any = None
    ai_checked = False
    for sym in symbols:
        if deadline_seconds is not None and _time.monotonic() - started > deadline_seconds:
            log.info("news refresh: time is up after %d symbols", report.symbols)
            break
        info = md.instrument(sym)
        if info is None:
            continue
        report.symbols += 1
        now = now_fn()
        base = build_query(db, info, now - WINDOW, now)
        for src in list(open_sources):
            if not src.supports(base):
                continue
            st = _state(db, src.key, info.symbol)
            since = max(now - WINDOW, _aware(st.last_success_at) - OVERLAP) if st.last_success_at else now - WINDOW
            q = replace(base, since=since)
            st.last_attempt_at = now
            report.fetched[src.key] = report.fetched.get(src.key, 0) + 1
            try:
                raw = src.fetch(q)
            except SourceBlocked as exc:
                st.last_status = "blocked"
                db.commit()
                _mark_blocked(db, src.key, now, str(exc), backoff_start(src.key, settings))
                open_sources.remove(src)
                report.blocked_sources.append(src.key)
                continue
            except Exception as exc:  # network trouble, a bad query: this symbol only
                report.errors += 1
                st.last_status, st.failures = "error", (st.failures or 0) + 1
                db.commit()
                failures[src.key] = failures.get(src.key, 0) + 1
                log.warning("news %s for %s failed: %s", src.key, info.symbol, str(exc)[:200])
                if failures[src.key] >= MAX_FAILURES_PER_RUN:
                    log.warning("news source %s failed %d times in a row; skipped for this run", src.key,
                                failures[src.key])
                    open_sources.remove(src)
                continue
            failures[src.key] = 0
            heads = to_headlines(raw, q, src.key, blocked)
            new = store(db, info.symbol, heads, now)
            report.stored += new
            st = _state(db, src.key, info.symbol)
            st.last_success_at, st.last_status, st.items, st.failures = now, "ok" if heads else "empty", len(heads), 0
            db.commit()
            _mark_open(db, src.key, now)
        # -- AI fallback --------------------------------------------------------------------------------
        if ai is None or report.ai_searches >= AI_MAX_PER_RUN:
            continue
        if not _ai_due(db, settings, info.symbol, now, gdelt_on=any(s.key == "gdelt" for s in sources)):
            continue
        if not ai_search.budget_left(db, settings, now):
            report.ai_skipped = "budget"
            ai = None
            log.info("news AI search: this month's budget (US$%s) is used up", settings.news_ai_budget_usd)
            continue
        if not ai_checked:
            ai_runner, ai_checked = ai(db), True
            if ai_runner is None:
                report.ai_skipped = "unavailable"
                ai = None
                continue
        st = _state(db, "ai_search", info.symbol)
        st.last_attempt_at = now
        db.commit()
        q = base
        gen = ai_search.new_generation_id()
        report.ai_searches += 1
        try:
            raw = ai_runner.run(q, now, blocked, ai_search.recorder(db, gen, settings))
        except Exception as exc:  # the API refused or failed; the usage of calls that ran is already recorded
            db.rollback()
            report.errors += 1
            st = _state(db, "ai_search", info.symbol)
            st.last_status, st.failures = "error", (st.failures or 0) + 1
            db.commit()
            log.warning("news AI search for %s failed: %s", info.symbol, str(exc)[:200])
            continue
        heads = to_headlines(raw, q, "ai_search", blocked)
        report.stored += store(db, info.symbol, heads, now)
        st = _state(db, "ai_search", info.symbol)
        st.last_success_at, st.last_status, st.items, st.failures = now, "ok" if heads else "empty", len(heads), 0
        db.commit()
    log.info("news refresh: %d symbols, requests %s, %d new headlines, %d AI searches%s", report.symbols,
             report.fetched, report.stored, report.ai_searches,
             f", blocked {report.blocked_sources}" if report.blocked_sources else "")
    return report


def _ai_due(db: Session, settings: Settings, symbol: str, now: datetime, *, gdelt_on: bool) -> bool:
    """Fewer than NEWS_AI_MIN_ITEMS free headlines in 7 days, GDELT answered recently (when it is on), and no AI
    search for this symbol in the last NEWS_AI_INTERVAL_HOURS."""
    if gdelt_on:
        g = db.get(NewsFetchState, ("gdelt", symbol))
        if g is None or g.last_success_at is None or now - _aware(g.last_success_at) > GDELT_FRESH:
            return False
    if recent_free_count(db, symbol, now) >= settings.news_ai_min_items:
        return False
    st = db.get(NewsFetchState, ("ai_search", symbol))
    return not (st is not None and st.last_attempt_at is not None
                and now - _aware(st.last_attempt_at) < timedelta(hours=settings.news_ai_interval_hours))
