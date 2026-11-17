"""Collect, store and serve the 「新聞報導」 headlines (metadata only).

Refresh (worker job ``news_refresh``, every ``NEWS_REFRESH_MINUTES``; also ``python -m forliosa.news refresh``)
-----------------------------------------------------------------------------------------------------------
* **Which symbols**: tracked ones — in any ledger or watchlist (``archive.tracked_symbols``),
  or viewed in the last ``NEWS_VIEW_DAYS`` days (``news_tracked_views``: symbol + time only, no user ids) — the
  stalest first, at most ``NEWS_MAX_SYMBOLS_PER_RUN``. Shared by everyone.
* **GDELT bulk files first** (:mod:`forliosa.news.gdelt_bulk`, 2026-11-16): the new 15-minute GKG files are read once
  and matched against every tracked Taiwan stock, not only the batch's (Taiwanese sites only, the title naming the
  company), and stored as ``gdelt`` headlines. While they are current, the DOC API is not asked for Taiwan stocks.
  Since 2026-11-17 (option A) the English files are matched against every tracked US stock and the US market too (US
  and UK news outlets only, :mod:`forliosa.news.us_match`); while the English feed is current, the DOC API is not
  asked for US stocks or the US market either.
* **Sources** (:mod:`forliosa.news.sources`): GDELT's DOC API (only while the bulk feed a stock leans on is not
  current: ``translation`` for Taiwan stocks, ``english`` for US stocks and the US market), then our private SearXNG
  (:mod:`forliosa.news.searxng`, on by default), then Yahoo股市 RSS (only under ``DATA_POLICY=personal``). One request
  per symbol per source; the HTTP
  limiter spaces GDELT requests ≥ ``NEWS_GDELT_INTERVAL_SECONDS`` (≥ 5 s). A 429 / block stops that source for the
  run and backs it off (15 min, doubling to 4 h; SearXNG from ``NEWS_SEARXNG_BACKOFF_MINUTES``; ``news_fetch_state``
  row ``symbol = "*"``); an unreachable source (:class:`SourceDown`) is paused the same way from 15 min; three
  errors in a row also stop a source for the run. Never another IP, never a disguised client.
* **SearXNG** is skipped for a symbol asked within ``NEWS_SEARXNG_CACHE_MINUTES`` (60) and for one GDELT already
  covers (≥ ``NEWS_SEARXNG_SKIP_GDELT_ITEMS`` (8) GDELT headlines from the last 24 h); its upstream engines are
  booked one by one (rows ``symbol = "@<engine>"``): a refusing engine is left out of the next queries, every
  engine paused pauses SearXNG (:func:`record_searxng_engines`).
* **AI fallback** (:mod:`forliosa.news.ai_search`): only when GDELT and SearXNG answered for the symbol in the last
  24 h (each one that is answering in this run: a paused or unreachable source does not hold it back — 2026-11-16
  fix) and the free sources together hold fewer than ``NEWS_AI_MIN_ITEMS`` headlines from the last 7 days; it
  searches the last 14 days (30 when nothing is stored from the last 14); once per ``NEWS_AI_INTERVAL_HOURS`` per
  symbol, at most ``AI_MAX_PER_RUN`` per run, while the month's budget lasts.
* **Every headline** goes through :mod:`forliosa.news.normalize`: GDELT spacing removed, outlet / section suffix
  removed, the outlet named from its domain, kept only when the title names the company (Chinese short name,
  code or English short name; Taiwan stocks by the stricter rules of :mod:`forliosa.news.tw_match`, 2026-11-17), never
  from a blocked domain, a search-engine redirect, a page that is not news
  (``outlets.NOT_NEWS_DOMAINS``: quote pages, forums, AI-written pages) or a robot quote flash (鉅亨「盤中速報」),
  newer than the query window; stored once per (symbol, canonical URL: tracking parameters, ``www.`` / ``m.`` /
  AMP variants and ``http`` vs ``https`` folded together). Deleted ``NEWS_RETENTION_DAYS`` after publication.

Read (``GET /instruments/{symbol}/news``)
----------------------------------------
:func:`media_items`: the symbol's stored headlines of the retention window, Yahoo RSS rows only under
``personal``, blocked domains, pages that are not news, robot flashes, Taiwan stocks' headlines tagged as not
finance (:func:`tagged_not_finance`, 2026-11-17) and Taiwan stocks' headlines whose stored title no longer names the
stock by today's matching rule (:class:`ReadMatch`: the wrong matches stored before 2026-11-17, kept in the database)
hidden, de-duplicated (same URL or
near-identical title; the original outlet beats an aggregator copy, a reputable outlet another copy), the newest day
first and within a day the reputable outlets first (:func:`normalize.rank`; the stock page sorts by time itself), at
most ``MEDIA_LIMIT``. :func:`record_view` notes that the symbol was viewed.
"""

from __future__ import annotations

import logging
import time as _time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from forliosa.config import Settings, get_settings
from forliosa.datapolicy import Policy, labels
from forliosa.marketdata.base import InstrumentInfo
from forliosa.marketdata.http import HttpFetcher, RateLimiter
from forliosa.marketdata.service import MarketData
from forliosa.models import (
    CompanyProfile,
    NewsArticle,
    NewsBlockedDomain,
    NewsFetchState,
    NewsTag,
    NewsTagState,
    NewsTrackedView,
)
from forliosa.news import tw_match
from forliosa.news.gdelt_bulk import US_FEED, GdeltBulk, UsTest
from forliosa.news.normalize import (
    Headline,
    Terms,
    clean_title,
    clean_url,
    dedupe,
    is_amp_or_mobile,
    is_blocked,
    is_bot_flash,
    is_relevant,
    make_terms,
    normalize_domain,
    rank,
    url_key,
)
from forliosa.news.outlets import host_of, is_not_news, outlet_name
from forliosa.news.searxng import SearxngSource, engine_refused
from forliosa.news.sources import (
    GdeltSource,
    NewsSource,
    Query,
    RawItem,
    SourceBlocked,
    SourceDown,
    YahooRssSource,
)
from forliosa.news.us_match import market_matches, us_terms
from forliosa.timeutil import iso_taipei, now_utc

log = logging.getLogger(__name__)

WINDOW = timedelta(days=7)  # how far back a source is asked, and the AI fallback's count window
OVERLAP = timedelta(hours=1)  # re-ask an hour before the last success (GDELT indexes with a delay)
DATE_ONLY_GRACE = timedelta(days=1)  # a date-only headline (its day's midnight) may start this much before the window
MEDIA_LIMIT = 40
AI_MAX_PER_RUN = 10
MAX_FAILURES_PER_RUN = 3
BACKOFF_START = timedelta(minutes=15)
BACKOFF_MAX = timedelta(hours=4)
VIEW_WRITE_EVERY = timedelta(minutes=10)
GDELT_FRESH = timedelta(hours=24)  # the AI fallback needs a GDELT (and SearXNG) answer this recent
# The AI fallback's search window (2026-11-16, memo §2 item 6): 14 days for a stock with few headlines, 30 days for one
# with none in the last 14 days (small caps often have a story only every few weeks).
AI_WINDOW = timedelta(days=14)
AI_WINDOW_EMPTY = timedelta(days=30)
# After an AI search that found nothing, the next one waits this long (2026-11-16 review: with the GDELT gate fixed,
# a quiet stock was searched every day at about US$0.023, for nothing).
AI_EMPTY_INTERVAL = timedelta(hours=72)
SOURCE_WIDE = "*"
# SearXNG's upstream engines: news_fetch_state rows (source "searxng", symbol "@<engine>").
ENGINE_PREFIX = "@"
ENGINE_BACKOFF_MAX = timedelta(hours=24)
ENGINE_ERRORS_BEFORE_PAUSE = 3  # timeouts / errors in a row before an engine is paused (a refusal pauses at once)
# Sources that cost nothing per request: what they hold decides whether the paid AI fallback runs (LangSearch,
# 2026-11-17: its headlines count too, so a stock it covers is not searched again at the system's cost)
FREE_SOURCES = ("gdelt", "searxng", "yahoo_rss", "langsearch")
# news_articles.source -> (label shown with the headline, attribution key for ``sources``)
SOURCE_INFO: dict[str, tuple[str, str]] = {
    "gdelt": ("GDELT", "gdelt/doc"),
    "ai_search": ("AI 搜尋", "ai-search"),
    "searxng": ("SearXNG", "searxng"),
    "yahoo_rss": ("Yahoo股市", "yahoo-rss/stock"),
    "finmind": ("FinMind", "finmind"),
    "langsearch": ("LangSearch", "langsearch"),  # Taiwan stocks and ^TW only (forliosa.news.langsearch)
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


def tracked(db: Session, settings: Settings, now: datetime, *, limit: bool = True) -> list[str]:
    """Held / watched symbols plus those viewed in the last ``NEWS_VIEW_DAYS`` days, stalest GDELT fetch first; the
    first ``NEWS_MAX_SYMBOLS_PER_RUN`` of them unless ``limit`` is false (the GDELT bulk files are matched against
    every one: a file is read once, so a symbol left out of its batch would never get its matches)."""
    from forliosa.archive import tracked_symbols

    since = now - timedelta(days=settings.news_view_days)
    viewed = db.scalars(select(NewsTrackedView.symbol).where(NewsTrackedView.last_viewed_at >= since))
    symbols = sorted({*tracked_symbols(db), *viewed})
    last = {s.symbol: _aware(s.last_attempt_at) for s in db.scalars(
        select(NewsFetchState).where(NewsFetchState.source == "gdelt"))}
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    symbols.sort(key=lambda s: last.get(s) or epoch)
    return symbols[:settings.news_max_symbols_per_run] if limit else symbols


# -- queries ------------------------------------------------------------------------------------------------
def english_names(db: Session, info: InstrumentInfo, profile_english: str | None = None) -> list[str]:
    """English short names: the archived company profile's 英文簡稱 / ``Symbol`` (「TSMC」「Gudeng」; read here unless
    ``profile_english`` already holds it), then ASCII aliases; US stocks: the company name."""
    out: list[str] = []
    if info.market == "US":
        out.append(info.name)
    else:
        if profile_english is None:
            prof = db.get(CompanyProfile, info.symbol)
            profile_english = str(((prof.values or {}).get("english_short_name") if prof is not None else None) or "")
        if profile_english.strip():
            out.append(" ".join(profile_english.split()))
    out += [a for a in info.aliases if a.isascii()]
    seen: set[str] = set()
    result = []
    for n in out:
        if n.casefold() not in seen and len(n) >= 3:
            seen.add(n.casefold())
            result.append(n)
    return result


_OFFICIAL: list[tuple[object, object, dict[str, tuple[str, ...]]]] = []


def official_forms(db: Session, master: Mapping[str, InstrumentInfo]) -> dict[str, tuple[str, ...]]:
    """symbol -> the forms of its official name (:func:`tw_match.official_forms` of the company profile's 公司名稱:
    統一企業, 台灣大哥大, 台灣大車隊) for every Taiwan stock of ``master`` with a profile; read once per master and
    database (MarketData rebuilds its master at most hourly)."""
    bind = db.get_bind()
    entry = _OFFICIAL[0] if _OFFICIAL else None  # read once: the web process's request threads share the cache
    if entry is not None and entry[0] is master and entry[1] is bind:
        return entry[2]
    out: dict[str, tuple[str, ...]] = {}
    for symbol, values in db.execute(select(CompanyProfile.symbol, CompanyProfile.values)):
        info = master.get(symbol)
        if info is None or info.market == "US":
            continue
        forms = tw_match.official_forms(info.name, str((values or {}).get("name") or ""))
        if forms:
            out[symbol] = forms
    _OFFICIAL[:] = [(master, bind, out)]
    return out


def query_terms(db: Session, info: InstrumentInfo, md: MarketData | None = None,
                english: Sequence[str] | None = None) -> Terms:
    """The title test of one symbol (:func:`build_query`'s; the read-time check :class:`ReadMatch` builds the same).
    A Taiwan stock's terms follow :mod:`forliosa.news.tw_match`; with ``md``, its official name counts (統一企業), the
    other listed and official names that contain its name (聯合再生 for 聯合, 台灣大車隊 for 台灣大) take their
    headlines (the longest name wins) and a short name listed next to another listed name counts (「信驊、創意等」).
    ``english``: its :func:`english_names` when already known."""
    english = english_names(db, info) if english is None else list(english)
    taiwan = info.market != "US"
    # Taiwan: the short forms headlines use (tw_match.ALIASES: 台積, 禾榮); US: the Chinese aliases (輝達)
    extra = list(tw_match.ALIASES.get(info.code, ())) if taiwan else [a for a in info.aliases if not a.isascii()]
    master = md.master() if taiwan and md is not None else None
    official = official_forms(db, master) if master is not None else {}
    longer: tuple[str, ...] = ()
    if master is not None:
        longer = tuple(dict.fromkeys(w for n in (info.name, *extra)
                                     for w in tw_match.longer_in_master(n, master, official)))
    peers = tw_match.names_in_master(master) if master is not None else frozenset()
    forms = (*official.get(info.symbol, ()), *(tw_match.ALIAS_FORMS.get(info.code, ()) if taiwan else ()))
    return make_terms(info.name, info.code, english, extra, taiwan=taiwan, longer=longer, peers=peers, forms=forms)


def build_query(db: Session, info: InstrumentInfo, since: datetime, until: datetime,
                md: MarketData | None = None) -> Query:
    """The query and title test of one symbol (:func:`query_terms`)."""
    english = english_names(db, info)
    return Query(symbol=info.symbol, code=info.code, name=info.name, market=info.market, english=tuple(english),
                 terms=query_terms(db, info, md, english), since=since, until=until)


# -- normalising and storing --------------------------------------------------------------------------------
def to_headlines(items: Iterable[RawItem], q: Query, source: str, blocked: Sequence[str],
                 relevant: UsTest | None = None) -> list[Headline]:
    """Raw items -> normalised, relevant, unblocked headlines inside the query window. Never a page that is not news
    (``outlets.NOT_NEWS_DOMAINS``: quote pages, forums, AI-written pages) or a robot quote flash (``盤中速報``).
    ``relevant`` (title, URL) replaces :func:`is_relevant` (the GDELT bulk files' US stocks and US market:
    :mod:`forliosa.news.us_match`)."""
    out: list[Headline] = []
    for it in items:
        url = clean_url(it.url)
        if url is None or is_blocked(url, blocked) or (it.domain and is_blocked(it.domain, blocked)) \
                or is_not_news(url):
            continue
        host = host_of(url)
        outlet = it.outlet or outlet_name(url, it.domain)
        title = clean_title(it.title, url, outlet)
        published = _aware(it.published_at)
        if not title or is_bot_flash(title):
            continue
        if not (relevant(title, url) if relevant is not None
                else is_relevant(title, q.terms, url=url, raw_title=it.title)):
            continue
        if published > q.until + timedelta(minutes=30):
            continue
        # A date-only item is that day's Taipei midnight: kept while any part of its day is inside the window (one
        # day of grace, as ai_search.select_items), dropped once the whole day is older (「10 天前」).
        if published < q.since - (DATE_ONLY_GRACE if it.date_only else timedelta(0)):
            continue
        out.append(Headline(title=title, url=url, outlet=outlet[:100], domain=(it.domain or host)[:253],
                            published_at=min(published, q.until), source=source, date_only=it.date_only))
    return out


def store(db: Session, symbol: str, headlines: Iterable[Headline], now: datetime | None = None) -> int:
    """Insert new headlines (one per symbol and canonical URL). The canonical page beats an AMP / mobile variant,
    in one batch and across runs: a stored AMP / mobile link is switched to the canonical page's link (``url``,
    ``outlet``, ``domain``) when a later batch finds that page (:func:`_prefer_canonical`). Otherwise an existing
    row is left as it is, so a story GDELT stored first stays GDELT's. Returns how many rows were new."""
    rows = []
    seen: set[str] = set()
    for h in sorted(headlines, key=lambda x: is_amp_or_mobile(x.url)):
        key = url_key(h.url)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"symbol": symbol, "url_key": key, "url": h.url, "title": h.title, "outlet": h.outlet,
                     "domain": h.domain, "published_at": h.published_at, "date_only": h.date_only,
                     "source": h.source, "fetched_at": now or now_utc()})
    if not rows:
        return 0
    _prefer_canonical(db, symbol, rows)
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    before = db.scalar(select(func.count()).select_from(NewsArticle).where(NewsArticle.symbol == symbol)) or 0
    db.execute(insert(NewsArticle).values(rows).on_conflict_do_nothing(index_elements=["symbol", "url_key"]))
    db.commit()
    after = db.scalar(select(func.count()).select_from(NewsArticle).where(NewsArticle.symbol == symbol)) or 0
    return after - before


def _prefer_canonical(db: Session, symbol: str, rows: list[dict[str, Any]]) -> None:
    """Stored rows of this batch's URL keys whose link is an AMP / mobile variant (``m.udn.com/…``) take the
    canonical link this batch found (``udn.com/…``): url, outlet and domain only — the source that found the story
    first, its title and its time stay. Committed with the insert that follows."""
    canonical = {r["url_key"]: r for r in rows if not is_amp_or_mobile(r["url"])}
    if not canonical:
        return
    stored = db.scalars(select(NewsArticle).where(NewsArticle.symbol == symbol,
                                                  NewsArticle.url_key.in_(list(canonical))))
    for art in stored:
        if is_amp_or_mobile(art.url):
            new = canonical[art.url_key]
            art.url, art.outlet, art.domain = new["url"], new["outlet"], new["domain"]


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


def shown(h: Headline, policy: Policy, blocked: Sequence[str]) -> bool:
    """Served under this data policy, not taken down, news (not a quote page or robot flash stored before
    2026-11-16)."""
    return (_source_served(h.source, policy) and not is_blocked(h.url, blocked)
            and not (h.domain and is_blocked(h.domain, blocked)) and not is_not_news(h.url)
            and not is_bot_flash(h.title))


def tagged_not_finance(url_key: ColumnElement[str], symbol: ColumnElement[str]) -> ColumnElement[bool]:
    """Whether a Taiwan stock's headline was finished by the news tagging (:mod:`forliosa.news.tagging`,
    ``news_tag_state.status = "done"``) without a single theme, sector or related stock: clearly not finance news (a
    sports, entertainment or weather story under a stock whose name it shares: 「大洋洲」 under 大洋). 產品負責人
    2026-11-17: hidden on the stock page, in ``get_news`` and ``search_news`` and not counted by :func:`recent_count`;
    kept in ``news_articles``. A headline not tagged yet is shown (the tagging is not waited for); official
    announcements (公告) are not news_articles rows and are never hidden.

    Only Taiwan stocks' rows (``symbol`` ``.TW`` / ``.TWO``, review of 2026-11-17): a US stock's headlines are matched
    by ticker and company name (:mod:`forliosa.news.us_match`), and a media or consumer company's own story can come
    back without tags (「Netflix commissions new Harlan Coben thriller The Innocent」 under NFLX in the live test: the
    model took it for entertainment), so for them an empty answer says nothing. A correlated ``EXISTS`` (an anti-join
    on both primary keys), used as ``~tagged_not_finance(NewsArticle.url_key, NewsArticle.symbol)`` in a ``WHERE``."""
    return and_(or_(symbol.like("%.TW"), symbol.like("%.TWO")),
                exists().where(NewsTagState.url_key == url_key, NewsTagState.status == "done",
                               ~exists().where(NewsTag.url_key == NewsTagState.url_key)))


# -- the matching rule again when reading (產品負責人 2026-11-17, 「好」) ---------------------------------------------
READ_SCAN_MAX = 1000  # rows of one list looked at, at most, to fill it with rows that still match (~30 µs a row)


def is_taiwan_symbol(symbol: str) -> bool:
    return symbol.endswith((".TW", ".TWO"))


class ReadMatch:
    """Taiwan stocks' stored headlines checked again when they are read: a ``.TW`` / ``.TWO`` row is shown only when
    its stored title still names that row's stock by the rule every source is matched by when storing
    (:func:`is_relevant` with :func:`query_terms`: :mod:`forliosa.news.tw_match`, the catalog's names, official names
    and the longest name first). So the wrong matches stored before the tightened rule went live (up to
    ``NEWS_RETENTION_DAYS`` old: the year in 「2027台海」 under 2027 大成鋼, 「大洋洲」 under 1321 大洋, APEC under
    8261 富鼎) are no longer shown, and words added to the lists later hide the rows they would have kept out; the
    rows stay in ``news_articles`` (deleted on schedule). Used by :func:`media_items` (the stock page's /news and
    ``get_news``), :func:`recent_count` (SearXNG skip, AI fallback), :func:`forliosa.news.tags.search`
    (``search_news``) and :func:`forliosa.news.tags.by_topic` (the market reports).

    * Every source of ``news_articles`` (GDELT bulk files and DOC API, SearXNG, Yahoo RSS, the AI fallback) was stored
      through the same title test, so every row is checked the same way. The AI fallback's rows are no exception: the
      model only picks links, their title is the search result's and it passed :func:`is_relevant` when stored (the
      old rule before 2026-11-17, like everyone's).
    * Only the stored title (cleaned: the published title's section tail, 「| 財經」, is not kept) and the link are
      known now, so a finance page is judged by its link alone. Measured on 6 sets of GDELT bulk files (2026-11-12
      to 17): of 867 matches the rule keeps when storing, 1 fails here (setn.com, finance only by its 「| 財經」
      tail); all 2,289 matches only the old rule made fail.
    * Not checked: US stocks and the US market (their own rule, :mod:`forliosa.news.us_match`), a symbol no longer in
      the catalog (nothing to check it against), FinMind's per-request headlines (``personal`` only, not stored,
      FinMind's own per-stock list) and official announcements (``market_events``, not news rows).

    One per request (or refresh run): each stock's terms are built once (:meth:`prefetch` reads the company profiles
    of many stocks in one query); the official names and the catalog's names are cached per catalog
    (:func:`official_forms`, :func:`tw_match.longer_in_master`)."""

    def __init__(self, db: Session, md: MarketData | None) -> None:
        self.db, self.md = db, md
        self._terms: dict[str, Terms | None] = {}
        self._english: dict[str, str] = {}  # symbol -> the company profile's English short name ("" without one)

    def prefetch(self, symbols: Iterable[str]) -> None:
        """Read the company profiles (English short names) of these Taiwan stocks in one query per 500."""
        todo = [s for s in dict.fromkeys(symbols) if is_taiwan_symbol(s) and s not in self._english]
        for i in range(0, len(todo), 500):
            chunk = todo[i:i + 500]
            got = dict(self.db.execute(select(CompanyProfile.symbol, CompanyProfile.values)
                                       .where(CompanyProfile.symbol.in_(chunk))).all())
            for s in chunk:
                self._english[s] = str((got.get(s) or {}).get("english_short_name") or "")

    def terms(self, symbol: str) -> Terms | None:
        """The stock's title test, ``None`` for a symbol that is not a Taiwan stock in the catalog."""
        if symbol not in self._terms:
            info = self.md.master().get(symbol) if self.md is not None and is_taiwan_symbol(symbol) else None
            if info is None or info.market == "US":
                self._terms[symbol] = None
            else:
                self.prefetch([symbol])
                self._terms[symbol] = query_terms(self.db, info, self.md,
                                                  english_names(self.db, info, self._english.get(symbol, "")))
        return self._terms[symbol]

    def keeps(self, symbol: str, title: str, url: str) -> bool:
        """The row is shown: not a Taiwan stock's, or its title still names that stock."""
        if not is_taiwan_symbol(symbol):
            return True
        terms = self.terms(symbol)
        return terms is None or is_relevant(title, terms, url=url)


def kept_rows(db: Session, query: Any, check: ReadMatch, want: int, *, most: int = READ_SCAN_MAX
              ) -> list[NewsArticle]:
    """The first ``want`` rows of ``query`` (a ``select(NewsArticle)`` with a total order) that ``check`` keeps, read
    in pages of ``want`` until enough are kept, the rows run out or ``most`` rows were looked at (a stock with many
    wrong matches stored before 2026-11-17, 統一 or 全新, still fills its list)."""
    out: list[NewsArticle] = []
    offset = 0
    while len(out) < want and offset < most:
        page = list(db.scalars(query.offset(offset).limit(want)))
        out += [r for r in page if check.keeps(r.symbol, r.title, r.url)]
        if len(page) < want:
            break
        offset += want
    return out[:want]


def item_out(h: Headline) -> dict[str, Any]:
    label, key = SOURCE_INFO.get(h.source, (h.source, h.source))
    return {"published_at": iso_taipei(h.published_at), "title": h.title, "source": label, "outlet": h.outlet,
            "url": h.url, "category": "media", "date_only": h.date_only, "sources": labels([key])}


# -- the US market's headlines (the market page's US row) ------------------------------------------------------------
# US market news, stored under this key (not a symbol: it never resolves to an instrument) and shown on the market page
# (產品負責人 2026-11-15). US and UK English outlets, like US stocks. Since 2026-11-17 (option A) matched in GDELT's
# English bulk files (us_match.market_matches); one DOC API request per refresh only while that feed is not current.
US_MARKET_KEY = "^US"
US_MARKET_TERMS = ("Wall Street", "S&P 500", "Dow Jones", "Nasdaq")
US_MARKET_LIMIT = 6


def market_query(since: datetime, until: datetime) -> Query:
    return Query(symbol=US_MARKET_KEY, code="", name="美股", market="US", english=US_MARKET_TERMS,
                 terms=make_terms("", "", US_MARKET_TERMS), since=since, until=until)


def market_items(db: Session, md: MarketData, *, settings: Settings | None = None, now: datetime | None = None,
                 limit: int = US_MARKET_LIMIT) -> list[dict[str, Any]]:
    """The newest US market headlines (metadata only, links to the outlets), blocked domains left out."""
    settings = settings or get_settings()
    if not settings.news_enabled:
        return []
    now = now or now_utc()
    blocked = blocked_domains(db, settings)
    rows = db.scalars(select(NewsArticle).where(NewsArticle.symbol == US_MARKET_KEY,
                                                NewsArticle.published_at >= now - timedelta(days=3))
                      .order_by(NewsArticle.published_at.desc()).limit(limit * 4))
    heads = [Headline(title=r.title, url=r.url, outlet=r.outlet, domain=r.domain, published_at=_aware(r.published_at),
                      source=r.source, date_only=bool(r.date_only)) for r in rows]
    heads = [h for h in heads if shown(h, md.policy, blocked)]
    return [item_out(h) for h in dedupe(heads)[:limit]]


def _refresh_market(db: Session, src: NewsSource, now: datetime, report: RefreshReport,
                    blocked: Sequence[str], settings: Settings) -> bool:
    """One GDELT DOC API request for US market news (only while the English bulk feed is not current). False when
    GDELT refused (paused like any other refusal)."""
    st = _state(db, src.key, US_MARKET_KEY)
    since = max(now - WINDOW, _aware(st.last_success_at) - OVERLAP) if st.last_success_at else now - WINDOW
    q = market_query(since, now)
    st.last_attempt_at = now
    report.fetched[src.key] = report.fetched.get(src.key, 0) + 1
    try:
        raw = src.fetch(q)
    except (SourceBlocked, SourceDown) as exc:
        down = isinstance(exc, SourceDown)
        st.last_status = "unreachable" if down else "blocked"
        db.commit()
        _mark_blocked(db, src.key, now, str(exc), BACKOFF_START if down else backoff_start(src.key, settings),
                      status="unreachable" if down else "rate_limited", until=getattr(exc, "until", None))
        return False
    except Exception as exc:  # a bad answer: try again next run
        report.errors += 1
        st.last_status, st.failures = "error", (st.failures or 0) + 1
        db.commit()
        log.warning("news gdelt for the US market failed: %s", str(exc)[:200])
        return True
    heads = to_headlines(raw, q, src.key, blocked)
    report.stored += store(db, US_MARKET_KEY, heads, now)
    st = _state(db, src.key, US_MARKET_KEY)
    st.last_success_at, st.last_status, st.items, st.failures = now, "ok" if heads else "empty", len(heads), 0
    db.commit()
    _mark_open(db, src.key, now)
    return True


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
    query = (select(NewsArticle).where(NewsArticle.symbol == info.symbol, NewsArticle.published_at >= since,
                                       ~tagged_not_finance(NewsArticle.url_key, NewsArticle.symbol))
             .order_by(NewsArticle.published_at.desc(), NewsArticle.id.desc()))
    rows = kept_rows(db, query, ReadMatch(db, md), limit * 4)
    heads = [Headline(title=r.title, url=r.url, outlet=r.outlet, domain=r.domain, published_at=_aware(r.published_at),
                      source=r.source, date_only=bool(r.date_only)) for r in rows]
    heads += list(extra)
    heads = [h for h in heads if shown(h, md.policy, blocked)]
    return [item_out(h) for h in rank(dedupe(heads))[:limit]]


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


def backoff_until(failures: int, now: datetime, start: timedelta = BACKOFF_START,
                  cap: timedelta = BACKOFF_MAX) -> datetime:
    """``start`` after the first refusal, doubling each time, at most ``cap`` (or ``start`` when longer)."""
    return now + min(start * (2 ** min(max(failures - 1, 0), 16)), max(cap, start))


def backoff_start(source: str, settings: Settings) -> timedelta:
    """SearXNG waits ``NEWS_SEARXNG_BACKOFF_MINUTES`` (120) after a refusal; the other sources 15 minutes."""
    if source == "searxng":
        return timedelta(minutes=settings.news_searxng_backoff_minutes)
    return BACKOFF_START


def news_fetcher(settings: Settings) -> HttpFetcher:
    """The HTTP client for GDELT and Yahoo RSS: an honest User-Agent, GDELT spaced ≥ 5 s, Yahoo ≥ 3 s, one retry
    after a dropped connection (never after a refusal). SearXNG has its own (:func:`searxng.searxng_fetcher`)."""
    per_host = {"gdeltproject.org": settings.news_gdelt_interval_seconds, "tw.stock.yahoo.com": 3.0}
    return HttpFetcher(timeout=30.0, limiter=RateLimiter(per_host=per_host), retries=1, backoff=10.0,
                       user_agent="forliosa/0.1 (portfolio tracker; news headline index)")


def searxng_source(settings: Settings) -> SearxngSource | None:
    """Our private SearXNG (on by default; ``None`` when NEWS_SEARXNG_ENABLED=false or NEWS_SEARXNG_URL is empty)."""
    url = settings.searxng_url
    if not url:
        return None
    return SearxngSource(url, engines=settings.news_searxng_engines,
                         interval=settings.news_searxng_interval_seconds,
                         timeout=settings.news_searxng_timeout_seconds)


def default_sources(settings: Settings, policy: Policy, fetcher: HttpFetcher | None = None) -> list[NewsSource]:
    """GDELT (unless NEWS_GDELT_ENABLED=false), SearXNG (on by default), Yahoo股市 RSS (only under
    DATA_POLICY=personal). GDELT first: SearXNG is skipped for a symbol GDELT already covers well."""
    fetcher = fetcher or news_fetcher(settings)
    out: list[NewsSource] = []
    if settings.news_gdelt_enabled:
        out.append(GdeltSource(fetcher))
    if (searx := searxng_source(settings)) is not None:
        out.append(searx)
    if policy == "personal" and settings.news_yahoo_rss:
        out.append(YahooRssSource(fetcher))
    return out


def gdelt_bulk_source(settings: Settings) -> GdeltBulk | None:
    """GDELT's 15-minute bulk files for Taiwan stocks, US stocks and the US market (on unless NEWS_GDELT_ENABLED or
    NEWS_GDELT_BULK is false)."""
    if not (settings.news_gdelt_enabled and settings.news_gdelt_bulk and settings.news_gdelt_bulk_feeds):
        return None
    return GdeltBulk(feeds=settings.news_gdelt_bulk_feeds, max_files=settings.news_gdelt_bulk_max_files)


@dataclass
class RefreshReport:
    symbols: int = 0
    fetched: dict[str, int] = field(default_factory=dict)  # source -> requests made (gdelt_bulk: files read)
    stored: int = 0
    bulk_rows: int = 0  # Taiwanese headlines in the GDELT bulk files read
    bulk_us_rows: int = 0  # pages of US and UK outlets in the English bulk files read
    bulk_ok: bool = False  # the bulk files are current: the DOC API is not asked for Taiwan stocks
    bulk_us_ok: bool = False  # the English bulk feed is current: the DOC API is not asked for US stocks / the market
    blocked_sources: list[str] = field(default_factory=list)
    ai_searches: int = 0
    ai_skipped: str | None = None  # why the AI fallback did not run at all (budget, off, no keys)
    errors: int = 0
    skipped: dict[str, int] = field(default_factory=dict)  # searxng_cache | searxng_gdelt -> symbols not asked
    paused_engines: list[str] = field(default_factory=list)  # SearXNG upstream engines paused in this run


AiFactory = Callable[[Session], Any]  # returns an object with ``run(q, now, blocked, record)`` or None


def _source_open(db: Session, source: str, now: datetime) -> bool:
    row = db.get(NewsFetchState, (source, SOURCE_WIDE))
    return row is None or row.backoff_until is None or _aware(row.backoff_until) <= now


def _mark_blocked(db: Session, source: str, now: datetime, reason: str,
                  start: timedelta = BACKOFF_START, *, status: str = "rate_limited",
                  until: datetime | None = None) -> None:
    """Pause a whole source: ``until`` when known, else ``start`` doubling with each failure in a row."""
    row = _state(db, source, SOURCE_WIDE)
    row.failures = (row.failures or 0) + 1
    row.last_attempt_at, row.last_status = now, status
    row.backoff_until = until if until is not None and until > now else backoff_until(row.failures, now, start)
    db.commit()
    what = "is unreachable" if status == "unreachable" else "refused"
    log.warning("news source %s %s (%s); not asked again before %s", source, what, reason[:160],
                iso_taipei(row.backoff_until))


# -- SearXNG's upstream engines ------------------------------------------------------------------------------
def engine_state_key(engine: str) -> str:
    """``news_fetch_state.symbol`` of one SearXNG engine: ``@bing news`` (at most 20 characters)."""
    return (ENGINE_PREFIX + " ".join(engine.split()))[:20]


def searxng_paused(db: Session, engines: Iterable[str], now: datetime) -> dict[str, datetime]:
    """The configured engines that are paused now -> until when."""
    keys = {engine_state_key(e): e for e in engines}
    if not keys:
        return {}
    rows = db.scalars(select(NewsFetchState).where(NewsFetchState.source == "searxng",
                                                   NewsFetchState.symbol.in_(list(keys))))
    return {keys[r.symbol]: _aware(r.backoff_until) for r in rows
            if r.backoff_until is not None and _aware(r.backoff_until) > now}


def record_searxng_engines(db: Session, src: SearxngSource, now: datetime, settings: Settings) -> list[str]:
    """Book what each engine did in the last answer: answered -> reset; refused (CAPTCHA, too many requests,
    access denied) -> paused ``NEWS_SEARXNG_BACKOFF_MINUTES`` doubling up to 24 h; a timeout or another error ->
    paused 15 minutes (doubling) after three in a row. Returns the engines paused now."""
    ans = src.last
    if ans is None:
        return []
    reasons = dict(ans.unresponsive)
    paused: list[str] = []
    for engine in dict.fromkeys([*src.last_asked, *reasons]):
        row = _state(db, "searxng", engine_state_key(engine))
        row.last_attempt_at = now
        reason = reasons.get(engine)
        if reason is None:
            row.failures, row.backoff_until, row.last_status, row.last_success_at = 0, None, "ok", now
            row.items = ans.per_engine.get(engine, 0)
            continue
        row.failures = (row.failures or 0) + 1
        if engine_refused(reason):
            row.last_status = "refused"
            row.backoff_until = backoff_until(row.failures, now,
                                              timedelta(minutes=settings.news_searxng_backoff_minutes),
                                              cap=ENGINE_BACKOFF_MAX)
        else:
            row.last_status = "error"
            if row.failures >= ENGINE_ERRORS_BEFORE_PAUSE:
                row.backoff_until = backoff_until(row.failures - ENGINE_ERRORS_BEFORE_PAUSE + 1, now,
                                                  BACKOFF_START, cap=BACKOFF_MAX)
        if row.backoff_until is not None and _aware(row.backoff_until) > now:
            paused.append(engine)
            log.warning("SearXNG engine %s: %s; not asked again before %s", engine, reason[:80],
                        iso_taipei(row.backoff_until))
    db.commit()
    return paused


def _searxng_skip(db: Session, src: SearxngSource, symbol: str, now: datetime, settings: Settings,
                  gdelt_on: bool, check: ReadMatch | None = None) -> str | None:
    """Why SearXNG is not asked for this symbol now: it answered within NEWS_SEARXNG_CACHE_MINUTES (that answer is
    stored; a query that failed caches nothing — the source-wide pause paces those), or GDELT already holds
    NEWS_SEARXNG_SKIP_GDELT_ITEMS headlines from the last 24 hours."""
    st = db.get(NewsFetchState, ("searxng", symbol))
    if st is not None and st.last_success_at is not None and \
            now - _aware(st.last_success_at) < timedelta(minutes=settings.news_searxng_cache_minutes):
        return "searxng_cache"
    if gdelt_on and recent_count(db, symbol, now - GDELT_FRESH, ("gdelt",), check=check) \
            >= settings.news_searxng_skip_gdelt_items:
        return "searxng_gdelt"
    return None


def _mark_open(db: Session, source: str, now: datetime) -> None:
    row = db.get(NewsFetchState, (source, SOURCE_WIDE))
    if row is not None and (row.failures or row.backoff_until):
        row.failures, row.backoff_until, row.last_status, row.last_success_at = 0, None, "ok", now
        db.commit()


def recent_count(db: Session, symbol: str, since: datetime, sources: Sequence[str] | None = None, *,
                 check: ReadMatch | None = None) -> int:
    """Stored headlines of ``symbol`` published since ``since`` (from ``sources``, else any), not counting rows the
    reading side hides (quote pages, forums, robot flashes stored before 2026-11-16: ``is_not_news``,
    ``is_bot_flash``; Taiwan stocks' headlines tagged as not finance: :func:`tagged_not_finance`; with ``check``,
    Taiwan stocks' rows whose title no longer matches: :class:`ReadMatch`), so that they do not hold the AI fallback
    back. :func:`refresh` always passes ``check``."""
    q = select(NewsArticle.url, NewsArticle.title).where(
        NewsArticle.symbol == symbol, NewsArticle.published_at >= since,
        ~tagged_not_finance(NewsArticle.url_key, NewsArticle.symbol))
    if sources is not None:
        q = q.where(NewsArticle.source.in_(list(sources)))
    return sum(1 for url, title in db.execute(q) if not is_not_news(url) and not is_bot_flash(title)
               and (check is None or check.keeps(symbol, title, url)))


def recent_free_count(db: Session, symbol: str, now: datetime, *, check: ReadMatch | None = None) -> int:
    """Headlines from the free sources (GDELT, SearXNG, Yahoo RSS) in the last 7 days."""
    return recent_count(db, symbol, now - WINDOW, FREE_SOURCES, check=check)


def ai_window(db: Session, symbol: str, now: datetime, *, check: ReadMatch | None = None) -> timedelta:
    """How far back the AI fallback searches: 14 days, or 30 when nothing at all is stored from the last 14 days."""
    return AI_WINDOW if recent_count(db, symbol, now - AI_WINDOW, check=check) else AI_WINDOW_EMPTY


def _book_bulk(db: Session, symbols: Iterable[str], covered: datetime, found: dict[str, int]) -> None:
    """Book each symbol's ``gdelt`` row as answered up to ``covered`` (never moved back)."""
    for sym in symbols:
        st = _state(db, "gdelt", sym)
        before = _aware(st.last_success_at) if st.last_success_at else None
        st.last_success_at, st.failures = max(covered, before) if before else covered, 0
        st.items = found.get(sym, 0)
        st.last_status = "ok" if st.items else "empty"
    db.commit()


def _refresh_bulk(db: Session, md: MarketData, bulk: GdeltBulk, symbols: Sequence[str], now: datetime,
                  report: RefreshReport, blocked: Sequence[str], *, market: bool = False) -> tuple[bool, bool]:
    """Read GDELT's new bulk files once for every tracked stock (not only the batch's: ``tracked(limit=False)``) —
    Taiwan stocks in both feeds, US stocks (and with ``market`` the US market, key ``^US``) in the English feed — and
    store the matches as GDELT headlines, each file's before it is booked as read (``GdeltBulk.run``'s ``keep``). While
    a stock's feed is current (Taiwan: ``translation``; US and the market: ``english``), its ``gdelt`` row is booked
    as answered up to the end of that feed's newest file read (``last_success_at``, never moved back: the AI
    fallback's gate and the DOC API fallback's window read it, so once the files stop the DOC API starts an hour
    before what they covered; ``last_attempt_at`` stays the rotation's, set when the batch reaches the stock).
    Returns whether the Taiwan feed and the English feed are current."""
    queries: dict[str, Query] = {}
    us_queries: dict[str, Query] = {}
    us_tests: dict[str, UsTest] = {}
    for sym in symbols:
        info = md.instrument(sym)
        if info is None:
            continue
        q = build_query(db, info, now - WINDOW, now, md)
        if info.market != "US":
            queries[info.symbol] = q
        else:
            us_queries[info.symbol] = q
            us_tests[info.symbol] = us_terms(db, info).matches
    if market:
        us_queries[US_MARKET_KEY] = market_query(now - WINDOW, now)
        us_tests[US_MARKET_KEY] = market_matches
    if not queries and not us_tests:
        return False, False
    found: dict[str, int] = {}

    def keep(matches: dict[str, list[RawItem]]) -> None:  # each file's matches, stored before it is booked as read
        for sym, items in matches.items():
            if sym in queries:
                heads = to_headlines(items, queries[sym], "gdelt", blocked)
            else:
                heads = to_headlines(items, us_queries[sym], "gdelt", blocked, relevant=us_tests[sym])
            found[sym] = found.get(sym, 0) + len(heads)
            report.stored += store(db, sym, heads, now)

    res = bulk.run(db, queries, now, keep, us=us_tests)
    report.fetched[bulk.key] = report.fetched.get(bulk.key, 0) + res.files
    report.bulk_rows += res.rows
    report.bulk_us_rows += res.us_rows
    report.errors += res.errors
    report.blocked_sources += [f"{bulk.key}:{f}" for f in res.paused]
    ok = bool(queries) and bulk.healthy(db, now)
    if ok:
        _book_bulk(db, queries, min(now, bulk.covered_until(db) or now), found)
    us_ok = bool(us_tests) and bulk.healthy(db, now, US_FEED)
    if us_ok:
        _book_bulk(db, us_tests, min(now, bulk.covered_until(db, US_FEED) or now), found)
    return ok, us_ok


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
            now_fn: Callable[[], datetime] = now_utc, deadline_seconds: float | None = None,
            bulk: GdeltBulk | str | None = "default") -> RefreshReport:
    """One batch over the tracked symbols (see the module docstring). ``sources`` / ``ai`` / ``symbols`` / ``bulk``
    are for tests and the CLI; by default they follow the settings and ``DATA_POLICY``. ``ai=None`` turns the AI
    fallback off for this run; ``"default"`` uses the key pool when ``NEWS_AI_ENABLED`` and ``AI_WEB_SEARCH`` allow
    it. ``bulk="default"`` reads GDELT's bulk files only when ``sources`` is not given (tests pass their sources)."""
    from forliosa.news import ai_search

    settings = settings or get_settings()
    report = RefreshReport()
    if not settings.news_enabled:
        return report
    started = _time.monotonic()
    now = now_fn()
    purge(db, settings, now)
    if bulk == "default":
        bulk = gdelt_bulk_source(settings) if sources is None else None
    sources = default_sources(settings, md.policy) if sources is None else sources
    if not settings.news_ai_enabled or (ai == "default" and not settings.ai_web_search):
        ai = None
    elif ai == "default":
        ai = default_ai(settings)
    market_run = symbols is None and settings.news_us_market  # the worker's and the CLI's run, not a test's list
    # the bulk files are matched against every tracked stock, also on a run for given symbols (the CLI's --symbol):
    # a file is read once (2026-11-16 review: `refresh --symbol 2317` read them for 2317 alone)
    every = tracked(db, settings, now, limit=False) if symbols is None or isinstance(bulk, GdeltBulk) else []
    every = every if symbols is None else list(dict.fromkeys([*every, *symbols]))
    symbols = every[:settings.news_max_symbols_per_run] if symbols is None else symbols
    blocked = blocked_domains(db, settings)
    open_sources = [s for s in sources if _source_open(db, s.key, now)]
    report.blocked_sources = [s.key for s in sources if s not in open_sources]
    if isinstance(bulk, GdeltBulk):
        # the US market's headlines are matched whenever the files are read (also on a CLI run for given symbols: a
        # file is read once), the DOC API's market request below only on the worker's run
        report.bulk_ok, report.bulk_us_ok = _refresh_bulk(db, md, bulk, every, now, report, blocked,
                                                          market=settings.news_us_market)
    gdelt = next((s for s in open_sources if s.key == "gdelt"), None)
    if market_run and gdelt is not None and not report.bulk_us_ok \
            and not _refresh_market(db, gdelt, now, report, blocked, settings):
        open_sources.remove(gdelt)
        report.blocked_sources.append(gdelt.key)
    gdelt_on = any(s.key == "gdelt" for s in sources)
    check = ReadMatch(db, md)  # what the reading side shows counts (rows stored before 2026-11-17 checked again)
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
        base = build_query(db, info, now - WINDOW, now, md)
        for src in list(open_sources):
            if not src.supports(base):
                continue
            if src.key == "gdelt" and _bulk_covers(report, base):  # the bulk files covered it
                report.skipped["gdelt_bulk"] = report.skipped.get("gdelt_bulk", 0) + 1
                _state(db, "gdelt", info.symbol).last_attempt_at = now  # keeps the stalest-first rotation turning
                db.commit()
                continue
            searx = src if isinstance(src, SearxngSource) else None
            if searx is not None:
                why = _searxng_skip(db, searx, info.symbol, now, settings, gdelt_on, check)
                if why is not None:
                    report.skipped[why] = report.skipped.get(why, 0) + 1
                    continue
                paused = searxng_paused(db, searx.engines, now)
                searx.paused = frozenset(paused)
                if searx.engines and not searx.active_engines():  # every engine paused: the source as a whole
                    _mark_blocked(db, src.key, now, "every engine is paused", status="blocked",
                                  until=min(paused.values()))
                    open_sources.remove(src)
                    report.blocked_sources.append(src.key)
                    continue
            st = _state(db, src.key, info.symbol)
            since = max(now - WINDOW, _aware(st.last_success_at) - OVERLAP) if st.last_success_at else now - WINDOW
            if searx is not None:  # not incremental: SearXNG is always asked for the week (time_range=week)
                since = now - WINDOW
            q = replace(base, since=since)
            st.last_attempt_at = now
            report.fetched[src.key] = report.fetched.get(src.key, 0) + 1
            try:
                raw = src.fetch(q)
            except (SourceBlocked, SourceDown) as exc:
                down = isinstance(exc, SourceDown)
                st.last_status = "unreachable" if down else "blocked"
                db.commit()
                if searx is not None:
                    report.paused_engines += record_searxng_engines(db, searx, now, settings)
                _mark_blocked(db, src.key, now, str(exc), BACKOFF_START if down else backoff_start(src.key, settings),
                              status="unreachable" if down else "rate_limited", until=getattr(exc, "until", None))
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
            if searx is not None:
                report.paused_engines += record_searxng_engines(db, searx, now, settings)
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
        # A paused or unreachable source does not hold the AI back (2026-11-16: GDELT's DOC API is paused after a 429
        # most of the day, and the AI step waited for it): only the sources answering in this run must have answered.
        gdelt_answering = _bulk_covers(report, base) or any(s.key == "gdelt" for s in open_sources)
        if not _ai_due(db, settings, info.symbol, now, gdelt_on=gdelt_answering,
                       searxng_on=any(s.key == "searxng" for s in open_sources), check=check):
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
        q = replace(base, since=now - ai_window(db, info.symbol, now, check=check))
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
    log.info("news refresh: %d symbols, requests %s, %d new headlines, %d AI searches%s%s%s%s", report.symbols,
             report.fetched, report.stored, report.ai_searches,
             f", GDELT bulk {'current' if report.bulk_ok else 'not current'} ({report.bulk_rows} Taiwanese rows), "
             f"English feed {'current' if report.bulk_us_ok else 'not current'} ({report.bulk_us_rows} US/UK pages)"
             if "gdelt_bulk" in report.fetched or report.bulk_ok or report.bulk_us_ok else "",
             f", skipped {report.skipped}" if report.skipped else "",
             f", paused {report.blocked_sources}" if report.blocked_sources else "",
             f", paused SearXNG engines {report.paused_engines}" if report.paused_engines else "")
    return report


def _bulk_covers(report: RefreshReport, q: Query) -> bool:
    """The bulk feed this stock leans on is current (Taiwan: ``translation``; US: ``english``): no DOC API request."""
    return report.bulk_ok if q.taiwan else report.bulk_us_ok


def _ai_due(db: Session, settings: Settings, symbol: str, now: datetime, *, gdelt_on: bool,
            searxng_on: bool = False, check: ReadMatch | None = None) -> bool:
    """GDELT and SearXNG together hold fewer than NEWS_AI_MIN_ITEMS headlines from the last 7 days, each of them
    answered for this symbol in the last 24 hours while it is answering in this run (GDELT: its bulk files are current
    or its DOC API is not paused; SearXNG: on and not paused — a paused source does not hold the AI back), and no AI
    search for this symbol in the last NEWS_AI_INTERVAL_HOURS (``AI_EMPTY_INTERVAL`` after one that found
    nothing)."""
    for source, on in (("gdelt", gdelt_on), ("searxng", searxng_on)):
        if not on:
            continue
        g = db.get(NewsFetchState, (source, symbol))
        if g is None or g.last_success_at is None or now - _aware(g.last_success_at) > GDELT_FRESH:
            return False
    if recent_free_count(db, symbol, now, check=check) >= settings.news_ai_min_items:
        return False
    st = db.get(NewsFetchState, ("ai_search", symbol))
    if st is None or st.last_attempt_at is None:
        return True
    wait = timedelta(hours=settings.news_ai_interval_hours)
    if st.last_status == "empty":  # found nothing even 30 days back (M31, 訊聯): not every day
        wait = max(wait, AI_EMPTY_INTERVAL)
    return now - _aware(st.last_attempt_at) >= wait
