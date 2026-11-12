"""Wikidata / zh.wikipedia lookups for the 「關於」 description (product owner 2026-11-12, decision 7).

Licences: Wikipedia text is CC BY-SA 4.0 (we show an excerpt **unchanged**, labelled 「節錄」, with links to the
article and the licence; the text is never sent to an AI model); Wikidata is CC0.

Finding the article (:func:`find_article`):

1. ``wbsearchentities`` (language zh-tw) for the company's short name and its full name → candidate items;
2. ``wbgetentities`` (claims, sitelinks zhwiki, zh labels / aliases) for those candidates;
3. the item whose **P414 (stock exchange)** statement is TWSE (Q548621) or TPEx with a **P249 (ticker)**
   qualifier equal to the code (US: NYSE / Nasdaq and the ticker) wins; otherwise an item whose zh label or
   alias is exactly the company's full name (公司名稱). Only items with a zh.wikipedia sitelink count.

Then ``/api/rest_v1/page/summary/{title}`` with ``Accept-Language: zh-tw`` (the zh-tw variant) gives the lead
paragraph and the revision id. :func:`excerpt` cuts it at a sentence end.

Etiquette (https://meta.wikimedia.org/wiki/User-Agent_policy, API etiquette): an honest User-Agent
``Forliosa/1.0`` plus an optional contact from ``WIKIMEDIA_CONTACT`` (never ``SEC_CONTACT_EMAIL``); one request at a
time (a process-wide lock) spaced ≥ 1 s per host; a 429 / 403 stops the lookups (:class:`WikimediaRefused`) and
nothing is retried with another identity or IP.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from forliosa.marketdata.base import ProviderUnavailable
from forliosa.marketdata.http import HttpFetcher, HttpStatusError, RateLimiter

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
ZHWIKI_SUMMARY = "https://zh.wikipedia.org/api/rest_v1/page/summary/"
ZHWIKI_PAGE = "https://zh.wikipedia.org/zh-tw/"
LICENSE = "CC BY-SA 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/deed.zh-hant"
# Wikidata items of the exchanges (P414 values), checked live 2026-11-12: TWSE Q548621 and NYSE Q13677 on Q713418
# (台積電: P414 Q548621 + P249 "2330", P414 Q13677 + P249 "TSM"); TPEx Q5598539 (財團法人中華民國證券櫃檯買賣中心,
# "Taipei Exchange"); Nasdaq Q82059.
EXCHANGES = {"TWSE": ("Q548621",), "TPEX": ("Q5598539",), "US": ("Q13677", "Q82059")}
EXCERPT_CHARS = 260
MAX_FIRST_SENTENCE = 600
SEARCH_LIMIT = 5
_LOCK = threading.Lock()  # one Wikimedia request at a time in this process


class WikimediaRefused(ProviderUnavailable):
    """Wikimedia answered 429 / 403 (rate limit or block): stop all lookups for now."""


def user_agent(contact: str | None) -> str:
    contact = (contact or "").strip()
    return f"Forliosa/1.0 ({contact})" if contact else "Forliosa/1.0"


@dataclass(frozen=True)
class Article:
    title: str
    wikidata_id: str | None
    matched_by: str  # "ticker" | "name"


@dataclass(frozen=True)
class Summary:
    title: str
    text: str  # the excerpt (unchanged text, cut at a sentence end)
    url: str
    revision_id: int | None


def _claims_value(snak: dict[str, Any]) -> Any:
    v = ((snak or {}).get("datavalue") or {}).get("value")
    return v.get("id") if isinstance(v, dict) else v


def _ticker_match(entity: dict[str, Any], code: str, exchanges: Iterable[str]) -> bool:
    wanted = set(exchanges)
    for claim in (entity.get("claims") or {}).get("P414", []):
        if _claims_value(claim.get("mainsnak") or {}) not in wanted:
            continue
        tickers = {str(_claims_value(q)).strip().upper() for q in (claim.get("qualifiers") or {}).get("P249", [])}
        if code.upper() in tickers:
            return True
    return False


def _zh_names(entity: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for lang, label in (entity.get("labels") or {}).items():
        if lang.startswith("zh"):
            names.add(re.sub(r"\s+", "", str(label.get("value") or "")))
    for lang, aliases in (entity.get("aliases") or {}).items():
        if lang.startswith("zh"):
            names |= {re.sub(r"\s+", "", str(a.get("value") or "")) for a in aliases}
    return names


def zhwiki_title(entity: dict[str, Any]) -> str | None:
    return (((entity.get("sitelinks") or {}).get("zhwiki") or {}).get("title")) or None


def find_article(entities: dict[str, Any], code: str, market: str, full_name: str | None) -> Article | None:
    """Pick the article among ``wbgetentities`` results: ticker on the right exchange first, then an exact zh
    label / alias equal to the full company name. Items without a zh.wikipedia article are ignored."""
    items = [(qid, e) for qid, e in (entities or {}).items() if isinstance(e, dict) and zhwiki_title(e)]
    for qid, e in items:
        if _ticker_match(e, code, EXCHANGES.get(market, ())):
            return Article(zhwiki_title(e) or "", qid, "ticker")
    name = re.sub(r"\s+", "", full_name or "")
    if name:
        for qid, e in items:
            if name in _zh_names(e):
                return Article(zhwiki_title(e) or "", qid, "name")
    return None


_SENTENCE = re.compile(r"[^。！？!?]*[。！？!?]+[」』）)]*")


def excerpt(extract: str, limit: int = EXCERPT_CHARS) -> str | None:
    """The lead text cut at a sentence end: whole sentences while they fit in ``limit`` characters (at least the
    first sentence, when it is not absurdly long). The words themselves are not changed."""
    text = re.sub(r"\s*\n+\s*", "", (extract or "").strip())
    sentences = _SENTENCE.findall(text)
    if not sentences:
        return None
    out = ""
    for s in sentences:
        if out and len(out) + len(s) > limit:
            break
        out += s
    if len(out) > MAX_FIRST_SENTENCE:
        return None
    return out.strip() or None


def parse_summary(raw: dict[str, Any]) -> Summary | None:
    """REST ``page/summary`` -> :class:`Summary` (``None`` for disambiguation pages or an empty lead)."""
    if not isinstance(raw, dict) or raw.get("type") not in (None, "standard"):
        return None
    title = str(raw.get("title") or (raw.get("titles") or {}).get("canonical") or "").replace("_", " ").strip()
    text = excerpt(str(raw.get("extract") or ""))
    if not title or not text:
        return None
    try:
        rev = int(raw.get("revision")) if raw.get("revision") is not None else None
    except (TypeError, ValueError):
        rev = None
    return Summary(title=title, text=text, url=article_url(title), revision_id=rev)


def article_url(title: str) -> str:
    return ZHWIKI_PAGE + quote(title.replace(" ", "_"), safe="")


class WikimediaClient:
    """Serial, rate-limited access to the two Wikimedia APIs Forliosa uses."""

    def __init__(self, contact: str | None = None, fetcher: HttpFetcher | None = None):
        self.fetcher = fetcher or HttpFetcher(
            timeout=20.0, retries=0, user_agent=user_agent(contact),
            limiter=RateLimiter(per_host={"wikidata.org": 1.5, "wikipedia.org": 1.5}))

    def _get(self, url: str, params: dict[str, Any] | None = None,
             headers: dict[str, str] | None = None) -> Any:
        with _LOCK:
            try:
                return self.fetcher.get_json(url, params=params, headers=headers)
            except HttpStatusError as exc:
                if exc.status in (403, 429):
                    raise WikimediaRefused(str(exc)) from exc
                if exc.status == 404:
                    return None
                raise

    def search(self, text: str) -> list[str]:
        raw = self._get(WIKIDATA_API, {"action": "wbsearchentities", "search": text, "language": "zh-tw",
                                       "uselang": "zh-tw", "type": "item", "limit": SEARCH_LIMIT, "format": "json"})
        return [str(x.get("id")) for x in (raw or {}).get("search", []) if str(x.get("id", "")).startswith("Q")]

    def entities(self, ids: list[str]) -> dict[str, Any]:
        if not ids:
            return {}
        raw = self._get(WIKIDATA_API, {"action": "wbgetentities", "ids": "|".join(ids[:50]),
                                       "props": "claims|sitelinks|labels|aliases", "languages": "zh-tw|zh-hant|zh|en",
                                       "sitefilter": "zhwiki", "format": "json"})
        return (raw or {}).get("entities") or {}

    def summary(self, title: str) -> dict[str, Any] | None:
        return self._get(ZHWIKI_SUMMARY + quote(title.replace(" ", "_"), safe=""),
                         headers={"Accept-Language": "zh-tw"})

    def lookup(self, code: str, market: str, names: Iterable[str],
               full_name: str | None) -> tuple[Article, Summary] | None:
        """Search → entities → article → summary (at most ``len(names) + 2`` requests, one at a time)."""
        ids: list[str] = []
        for n in dict.fromkeys(x for x in names if x):
            ids += [i for i in self.search(n) if i not in ids]
        article = find_article(self.entities(ids), code, market, full_name)
        if article is None:
            return None
        summary = parse_summary(self.summary(article.title) or {})
        return (article, summary) if summary else None
