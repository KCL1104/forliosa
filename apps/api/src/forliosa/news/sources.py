"""Pluggable news sources: each turns a :class:`Query` into raw headlines (title, link, time — nothing else).

* :class:`GdeltSource` — GDELT DOC 2.0 (``api.gdeltproject.org``), the default. Free, "unlimited and unrestricted
  use for any academic, commercial, or governmental use of any kind without fee" with a citation to GDELT.
  Queries are in **English** (GDELT indexes machine translations; 「台積電 sourcelang:chinese」 finds nothing):
  the company's English short name (t187ap03 英文簡稱 / mopsfin ``Symbol``) and its code, ``sourcecountry:taiwan``
  for Taiwan stocks, ``sourcelang:english`` for US stocks. One IP may ask once every 5 s; a 429 stops the source
  (:class:`SourceBlocked`) and the caller backs off.
* :class:`SearxngSource` — a self-hosted SearXNG's JSON API, only when ``NEWS_SEARXNG_URL`` is set (off by
  default). A 429 / 403 or an upstream CAPTCHA / "too many requests" stops it for ``NEWS_SEARXNG_BACKOFF_MINUTES``;
  never another IP, never a disguised client.
* :class:`YahooRssSource` — Yahoo股市 RSS, only under ``DATA_POLICY=personal`` (its terms allow personal,
  non-commercial use only). The item description is read only to name the original outlet (「MoneyDJ新聞」
  「【財訊快報／…」「（中央社記者…」) and is never stored.

The AI web-search fallback lives in :mod:`forliosa.news.ai_search` (it needs the key pool and a budget).
Social images, ``og:description`` and article text are never read or kept.
"""

from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

from forliosa.marketdata.base import ProviderUnavailable
from forliosa.marketdata.http import HttpFetcher, HttpStatusError
from forliosa.news.normalize import Terms

log = logging.getLogger(__name__)

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_MAX_RECORDS = 75
YAHOO_RSS_URL = "https://tw.stock.yahoo.com/rss"
BLOCK_STATUSES = frozenset({403, 429, 451})


class SourceBlocked(ProviderUnavailable):
    """The source refused us (429, 403, a CAPTCHA, "please limit requests"): stop asking it for a while."""


@dataclass(frozen=True)
class Query:
    symbol: str
    code: str
    name: str  # Chinese short name (台積電) or the US company name (NVIDIA)
    market: str  # TWSE | TPEX | US
    english: tuple[str, ...]  # English short names (TSMC); US: the company name
    terms: Terms
    since: datetime  # only headlines newer than this (aware)
    until: datetime  # now (aware)

    @property
    def taiwan(self) -> bool:
        return self.market != "US"


@dataclass(frozen=True)
class RawItem:
    """What a source returned for one article: only the headline, link, time and an outlet / domain hint."""

    title: str
    url: str
    published_at: datetime  # aware
    date_only: bool = False
    outlet: str | None = None  # a source that names the outlet (Yahoo RSS description lead)
    domain: str | None = None  # GDELT's "domain"


class NewsSource(Protocol):
    key: str  # gdelt | searxng | yahoo_rss (news_articles.source)
    label: str  # shown with each headline: GDELT | SearXNG | Yahoo股市

    def supports(self, q: Query) -> bool: ...

    def fetch(self, q: Query) -> list[RawItem]: ...


def _quoted(term: str) -> str:
    term = term.replace('"', "").strip()
    return f'"{term}"' if re.search(r"[\s\-&]", term) else term


# -- GDELT ---------------------------------------------------------------------------------------------------
def gdelt_query(q: Query) -> str:
    """``(TSMC OR 2330) sourcecountry:taiwan`` / ``(NVIDIA OR NVDA) sourcelang:english``. Terms shorter than three
    characters are left out (GDELT rejects them and they match too much)."""
    terms: list[str] = []
    for t in (*q.english, q.code):
        t = " ".join((t or "").split())
        if len(t) >= 3 and t.isascii() and t.casefold() not in (x.casefold().strip('"') for x in terms):
            terms.append(_quoted(t))
    if not terms:
        raise ProviderUnavailable(f"{q.symbol}: no English search term for GDELT")
    body = terms[0] if len(terms) == 1 else "(" + " OR ".join(terms) + ")"
    return f"{body} {'sourcecountry:taiwan' if q.taiwan else 'sourcelang:english'}"


def _gdelt_time(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%d%H%M%S")


def parse_gdelt_seendate(value: str) -> datetime | None:
    """``20261112T070000Z`` (UTC) -> aware datetime."""
    try:
        return datetime.strptime(value.strip(), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except (ValueError, AttributeError):
        return None


def parse_gdelt(payload: bytes | str | dict[str, Any]) -> list[RawItem]:
    """An ArtList JSON response -> raw items. GDELT answers errors as plain text with HTTP 200 (「Please limit
    requests to one every 5 seconds…」 is a block; 「The specified phrase is too short」 a bad query); an empty
    result is ``{}``. ``socialimage`` and ``url_mobile`` are ignored."""
    if isinstance(payload, dict):
        data: Any = payload
    else:
        text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else payload
        stripped = text.strip()
        if not stripped.startswith("{"):
            if "limit requests" in stripped.lower():
                raise SourceBlocked("GDELT: " + stripped[:120])
            raise ProviderUnavailable("GDELT: " + (stripped[:200] or "empty response"))
        try:
            data = json.loads(stripped, strict=False)
        except ValueError as exc:
            raise ProviderUnavailable("GDELT returned malformed JSON") from exc
    out: list[RawItem] = []
    for a in data.get("articles") or []:
        if not isinstance(a, dict):
            continue
        title, url = str(a.get("title") or "").strip(), str(a.get("url") or "").strip()
        seen = parse_gdelt_seendate(str(a.get("seendate") or ""))
        if not title or not url or seen is None:
            continue
        out.append(RawItem(title=title, url=url, published_at=seen, domain=str(a.get("domain") or "") or None))
    return out


class GdeltSource:
    key = "gdelt"
    label = "GDELT"

    def __init__(self, fetcher: HttpFetcher):
        self.fetcher = fetcher

    def supports(self, q: Query) -> bool:
        return True

    def params(self, q: Query) -> dict[str, Any]:
        return {"query": gdelt_query(q), "mode": "artlist", "format": "json", "maxrecords": GDELT_MAX_RECORDS,
                "sort": "datedesc", "startdatetime": _gdelt_time(q.since), "enddatetime": _gdelt_time(q.until)}

    def fetch(self, q: Query) -> list[RawItem]:
        try:
            raw = self.fetcher.get_bytes(GDELT_URL, params=self.params(q))
        except HttpStatusError as exc:
            if exc.status in BLOCK_STATUSES:
                raise SourceBlocked(f"GDELT HTTP {exc.status}") from exc
            raise
        return parse_gdelt(raw)


# -- SearXNG -------------------------------------------------------------------------------------------------
_BLOCK_WORDS = ("captcha", "too many requests", "access denied", "suspended", "blocked", "rate limit")


def parse_searxng(data: dict[str, Any]) -> list[RawItem]:
    """SearXNG ``/search?format=json`` -> raw items (``title``, ``url``, ``publishedDate``; ``content`` and
    ``img_src`` are ignored). A result without a date is skipped (the list shows when it was published). An
    upstream engine that answered with a CAPTCHA or "too many requests" blocks the source."""
    reasons = [str(r[1] if isinstance(r, list | tuple) and len(r) > 1 else r).lower()
               for r in data.get("unresponsive_engines") or []]
    if any(w in r for r in reasons for w in _BLOCK_WORDS):
        raise SourceBlocked("SearXNG upstream refused: " + "; ".join(reasons)[:200])
    out: list[RawItem] = []
    for r in data.get("results") or []:
        if not isinstance(r, dict):
            continue
        title, url, published = str(r.get("title") or "").strip(), str(r.get("url") or "").strip(), None
        value = r.get("publishedDate") or r.get("pubdate")
        if isinstance(value, str) and value.strip():
            try:
                published = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError:
                published = None
        if not title or not url or published is None:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        out.append(RawItem(title=title, url=url, published_at=published))
    return out


class SearxngSource:
    key = "searxng"
    label = "SearXNG"

    def __init__(self, base_url: str, fetcher: HttpFetcher):
        self.base_url = base_url.rstrip("/")
        self.fetcher = fetcher

    def supports(self, q: Query) -> bool:
        return True

    def params(self, q: Query) -> dict[str, Any]:
        if q.taiwan:
            return {"q": f"{q.name} {q.code}", "format": "json", "categories": "news", "time_range": "week",
                    "language": "zh-TW", "safesearch": 0}
        return {"q": f"{q.english[0] if q.english else q.name} {q.code} stock", "format": "json",
                "categories": "news", "time_range": "week", "language": "en", "safesearch": 0}

    def fetch(self, q: Query) -> list[RawItem]:
        try:
            data = self.fetcher.get_json(f"{self.base_url}/search", params=self.params(q))
        except HttpStatusError as exc:
            if exc.status in BLOCK_STATUSES or exc.status == 503:
                raise SourceBlocked(f"SearXNG HTTP {exc.status}") from exc
            raise
        if not isinstance(data, dict):
            raise ProviderUnavailable("SearXNG returned an unexpected shape")
        return parse_searxng(data)


# -- Yahoo股市 RSS (personal only) ----------------------------------------------------------------------------
# Leads of Yahoo股市 RSS descriptions that name the original outlet (live feed of 2026-11-12). Only the outlet name
# is taken; the description itself is never stored or shown.
_YAHOO_OUTLET_LEADS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^\s*MoneyDJ"), "MoneyDJ"),
    (re.compile(r"^\s*[【\[]\s*財訊快報"), "財訊快報"),
    (re.compile(r"^\s*[（(]\s*中央社"), "中央社"),
    (re.compile(r"^\s*[【\[]\s*非凡新聞"), "非凡新聞"),
    (re.compile(r"^\s*[（(【\[]?\s*鉅亨"), "鉅亨網"),
    (re.compile(r"^\s*[（(【\[]?\s*時報資訊"), "時報資訊"),
    (re.compile(r"^\s*[（(【\[]?\s*精實新聞"), "精實新聞"),
    (re.compile(r"^\s*[（(【\[]?\s*中時新聞網"), "中時新聞網"),
    (re.compile(r"^\s*[（(【\[]?\s*工商時報"), "工商時報"),
    (re.compile(r"^\s*[（(【\[]?\s*經濟日報"), "經濟日報"),
    (re.compile(r"^\s*公開資訊觀測站重大訊息"), "公開資訊觀測站"),
)


def yahoo_outlet(description: str | None) -> str | None:
    lead = (description or "")[:40]
    for pattern, name in _YAHOO_OUTLET_LEADS:
        if pattern.search(lead):
            return name
    return None


def parse_yahoo_rss(payload: bytes | str) -> list[RawItem]:
    """Yahoo股市 RSS 2.0 -> raw items (title, link, pubDate; the outlet named by the description's lead)."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ProviderUnavailable("Yahoo股市 RSS is not valid XML") from exc
    out: list[RawItem] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        try:
            published = parsedate_to_datetime((item.findtext("pubDate") or "").strip())
        except (TypeError, ValueError):
            continue
        if not title or not url or published is None:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        out.append(RawItem(title=title, url=url, published_at=published,
                           outlet=yahoo_outlet(item.findtext("description"))))
    return out


class YahooRssSource:
    key = "yahoo_rss"
    label = "Yahoo股市"

    def __init__(self, fetcher: HttpFetcher):
        self.fetcher = fetcher

    def supports(self, q: Query) -> bool:
        return q.taiwan

    def fetch(self, q: Query) -> list[RawItem]:
        # Live 2026-11-12: ?s=<code> answers the 「最新新聞」 channel, so the relevance filter is what keeps only
        # this company's headlines.
        try:
            raw = self.fetcher.get_bytes(YAHOO_RSS_URL, params={"s": q.code},
                                         headers={"Accept": "application/rss+xml, application/xml"})
        except HttpStatusError as exc:
            if exc.status in BLOCK_STATUSES:
                raise SourceBlocked(f"Yahoo股市 RSS HTTP {exc.status}") from exc
            raise
        return parse_yahoo_rss(raw)
