"""Reading the news tags (:mod:`forliosa.news.tagging` writes them): per headline, search, and grouped by topic.

* :func:`tags_for_urls` — the tags of given headline links (``get_news`` adds them to each media headline).
* :func:`search` — our stored headlines filtered by theme, sector, stock and/or keyword over the last N days, newest
  first (the AI tool ``search_news``). A stock matches the headlines stored under it and those tagged with it.
* :func:`by_topic` — headlines of a date range grouped by theme or sector, the busiest group first: for the market
  reports (盤前／盤後／週報) to compare sectors and themes.

Every result passes the same filters as the stock page (:func:`forliosa.news.service.shown`: blocked domains, pages
that are not news, robot flashes, sources the data policy does not serve) and is de-duplicated (same URL or
near-identical title). Near-identical titles take a pairwise comparison (:func:`forliosa.news.normalize.dedupe`), so
it only ever looks at the newest headlines it needs (:func:`_newest`), never at a whole week's group. Only ids of the
current vocabulary are shown; untagged headlines are still found by stock and keyword. Headlines are metadata only
(title, outlet, time, link).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from forliosa.config import Settings, get_settings
from forliosa.marketdata.service import MarketData
from forliosa.models import NewsArticle, NewsTag
from forliosa.news import taxonomy as tx
from forliosa.news.normalize import Headline, dedupe, title_key, url_key
from forliosa.timeutil import iso_taipei, now_utc

MAX_DAYS = 90
SEARCH_LIMIT = 20
MARKET_LABELS = {"^US": "美股大盤"}


@dataclass
class TagSet:
    themes: list[str] = field(default_factory=list)
    sectors: list[str] = field(default_factory=list)
    symbols: list[tuple[str, str | None]] = field(default_factory=list)  # (symbol, relation)

    def view(self, md: MarketData | None = None) -> dict[str, Any]:
        """Labels of the current vocabulary (unknown ids left out); related stocks with their names."""
        out: dict[str, Any] = {
            "themes": [x for x in (tx.theme_label(t) for t in self.themes) if x],
            "sectors": [x for x in (tx.sector_label(s) for s in self.sectors) if x],
        }
        related = []
        for sym, rel in self.symbols:
            info = md.master().get(sym) if md is not None else None
            related.append({"symbol": sym, "name": info.name if info else None, "relation": rel})
        out["related"] = related
        return out

    def note(self, md: MarketData | None = None) -> str:
        """「主題：AI 伺服器、先進封裝；類股：半導體業；相關：3131 弘塑（供應鏈）」, or "" without tags."""
        v = self.view(md)
        parts = []
        if v["themes"]:
            parts.append("主題：" + "、".join(v["themes"]))
        if v["sectors"]:
            parts.append("類股：" + "、".join(v["sectors"]))
        if v["related"]:
            parts.append("相關：" + "、".join(
                f"{_code(r['symbol'])} {r['name'] or ''}".strip()
                + (f"（{tx.RELATION_LABELS[r['relation']]}）" if r["relation"] in ("supply_chain", "peer") else "")
                for r in v["related"]))
        return "；".join(parts)


def _code(symbol: str) -> str:
    return symbol.split(".", 1)[0]


def tags_for(db: Session, keys: Iterable[str]) -> dict[str, TagSet]:
    keys = list(dict.fromkeys(k for k in keys if k))
    out: dict[str, TagSet] = {}
    for i in range(0, len(keys), 500):
        for t in db.scalars(select(NewsTag).where(NewsTag.url_key.in_(keys[i:i + 500]))):
            ts = out.setdefault(t.url_key, TagSet())
            if t.kind == "theme":
                ts.themes.append(t.value)
            elif t.kind == "sector":
                ts.sectors.append(t.value)
            elif t.kind == "symbol":
                ts.symbols.append((t.value, t.relation))
    for ts in out.values():  # stable order: the vocabulary's own order
        ts.themes.sort(key=lambda x: _THEME_ORDER.get(x, 999))
        ts.sectors.sort(key=lambda x: _SECTOR_ORDER.get(x, 999))
    return out


_THEME_ORDER = {t.id: i for i, t in enumerate(tx.THEMES)}
_SECTOR_ORDER = {t.id: i for i, t in enumerate(tx.SECTORS)}


def tags_for_urls(db: Session, urls: Iterable[str]) -> dict[str, TagSet]:
    """url -> its tags (only links that have any)."""
    by_key = {url_key(u): u for u in urls if u}
    return {by_key[k]: ts for k, ts in tags_for(db, by_key).items()}


# -- search ---------------------------------------------------------------------------------------------------
def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


@dataclass
class _Shown:
    """The shown headlines of some article rows: one per URL, with the rows each URL is stored under."""

    heads: dict[str, Headline]  # url_key -> headline (shown ones only)
    groups: dict[str, list[NewsArticle]]  # url_key -> its rows
    key_of: dict[str, str]  # headline url -> url_key


def _shown(db: Session, md: MarketData, rows: Sequence[NewsArticle], settings: Settings) -> _Shown:
    from forliosa.news.service import blocked_domains, shown

    blocked = blocked_domains(db, settings)
    groups: dict[str, list[NewsArticle]] = {}
    for r in rows:
        groups.setdefault(r.url_key, []).append(r)
    heads: dict[str, Headline] = {}
    key_of: dict[str, str] = {}
    for key, group in groups.items():
        r = group[0]
        h = Headline(title=r.title, url=r.url, outlet=r.outlet, domain=r.domain, published_at=_aware(r.published_at),
                     source=r.source, date_only=bool(r.date_only))
        if shown(h, md.policy, blocked):
            heads[key] = h
            key_of[h.url] = key
    return _Shown(heads, groups, key_of)


def _newest(heads: Sequence[Headline], limit: int) -> list[Headline]:
    """The newest ``limit`` stories of ``heads``, newest first, near-identical titles merged. ``dedupe`` compares
    every pair, so it gets only the newest few times ``limit`` headlines, more only when those merge into fewer than
    ``limit`` stories (a story copied many times: its copies merge in a single pass)."""
    ordered = sorted(heads, key=lambda h: h.published_at, reverse=True)
    window = max(limit * 3, 10)
    while True:
        out = dedupe(ordered[:window])
        if len(out) >= limit or window >= len(ordered):
            return out[:limit]
        window *= 2


def _story_count(heads: Iterable[Headline]) -> int:
    """How many stories: one per URL, the same title (title_key) counted once (no pairwise comparison)."""
    seen: set[str] = set()
    n = 0
    for h in heads:
        k = title_key(h.title)
        if not k:
            n += 1
        elif k not in seen:
            seen.add(k)
            n += 1
    return n


def _render(db: Session, md: MarketData, heads: Sequence[Headline], found: _Shown) -> list[dict[str, Any]]:
    """Headlines -> items with the stocks they are stored under and their tags."""
    from forliosa.news.service import SOURCE_INFO

    groups = found.groups
    tags = tags_for(db, (found.key_of[h.url] for h in heads))
    master = md.master()
    out = []
    for h in heads:
        key = found.key_of[h.url]
        ts = tags.get(key, TagSet())
        stored = list(dict.fromkeys(r.symbol for r in groups[key]))
        item: dict[str, Any] = {
            "published_at": iso_taipei(h.published_at), "date_only": h.date_only, "title": h.title,
            "outlet": h.outlet, "url": h.url, "source": SOURCE_INFO.get(h.source, (h.source, h.source))[0],
            "stocks": [{"symbol": s, "name": master[s].name if s in master else None}
                       for s in stored if s not in MARKET_LABELS],
            **ts.view(md),
        }
        markets = [MARKET_LABELS[s] for s in stored if s in MARKET_LABELS]
        if markets:
            item["market"] = markets[0]
        item["tag_note"] = ts.note(md)
        out.append(item)
    return out


def _items(db: Session, md: MarketData, rows: Sequence[NewsArticle], settings: Settings, limit: int
           ) -> list[dict[str, Any]]:
    """Article rows -> the newest ``limit`` stories: shown ones only, de-duplicated, with their tags."""
    found = _shown(db, md, rows, settings)
    return _render(db, md, _newest(list(found.heads.values()), limit), found)


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search(db: Session, md: MarketData, *, theme: str | None = None, sector: str | None = None,
           symbol: str | None = None, keyword: str | None = None, days: int = 7, limit: int = SEARCH_LIMIT,
           now: datetime | None = None, settings: Settings | None = None) -> list[dict[str, Any]]:
    """Stored headlines of the last ``days`` days (1–90; there are none older than NEWS_RETENTION_DAYS) matching every
    filter given, newest first. ``theme`` / ``sector``: ids (:mod:`forliosa.news.taxonomy`); ``symbol``: a catalog
    symbol (stored under it or tagged with it); ``keyword``: part of the title (case-insensitive)."""
    settings = settings or get_settings()
    if not settings.news_enabled:
        return []
    now = now or now_utc()
    days = max(1, min(MAX_DAYS, int(days)))
    q = select(NewsArticle).where(NewsArticle.published_at >= now - timedelta(days=days))
    if theme:
        q = q.where(NewsArticle.url_key.in_(select(NewsTag.url_key).where(NewsTag.kind == "theme",
                                                                         NewsTag.value == theme)))
    if sector:
        q = q.where(NewsArticle.url_key.in_(select(NewsTag.url_key).where(NewsTag.kind == "sector",
                                                                         NewsTag.value == sector)))
    if symbol:
        q = q.where(or_(NewsArticle.symbol == symbol, NewsArticle.url_key.in_(
            select(NewsTag.url_key).where(NewsTag.kind == "symbol", NewsTag.value == symbol))))
    if keyword and keyword.strip():
        pattern = f"%{_escape_like(keyword.strip().casefold())}%"
        q = q.where(func.lower(NewsArticle.title).like(pattern, escape="\\"))
    rows = list(db.scalars(q.order_by(NewsArticle.published_at.desc(), NewsArticle.id).limit(limit * 8)))
    if symbol and rows:  # the other symbols the matching URLs are stored under (for the item's "stocks")
        keys = list({r.url_key for r in rows})
        seen = {(r.symbol, r.url_key) for r in rows}
        rows += [r for r in db.scalars(select(NewsArticle).where(NewsArticle.url_key.in_(keys)))
                 if (r.symbol, r.url_key) not in seen]
        rows.sort(key=lambda r: _aware(r.published_at), reverse=True)
    return _items(db, md, rows, settings, limit)


# -- grouped by topic (market reports) ----------------------------------------------------------------------------
def by_topic(db: Session, md: MarketData, kind: Literal["theme", "sector"], since: datetime, until: datetime, *,
             per_group: int = 5, settings: Settings | None = None) -> list[dict[str, Any]]:
    """Headlines published in ``[since, until)`` grouped by their themes or sectors: ``[{id, label, count, items}]``,
    the most headlines first (then the vocabulary's order); ``count`` is the number of distinct stories (shown; one
    per URL, the same title counted once), ``items`` the newest ``per_group`` of them, near-identical titles merged
    (see :func:`search` for an item's fields). A headline with two themes counts in both. Linear in the number of
    headlines: a week of a busy theme (thousands) takes well under a second."""
    settings = settings or get_settings()
    if not settings.news_enabled:
        return []
    label = tx.theme_label if kind == "theme" else tx.sector_label
    order = _THEME_ORDER if kind == "theme" else _SECTOR_ORDER
    pairs = db.execute(select(NewsTag.value, NewsTag.url_key).join(NewsArticle, NewsArticle.url_key == NewsTag.url_key)
                       .where(NewsTag.kind == kind, NewsArticle.published_at >= since,
                              NewsArticle.published_at < until).distinct()).all()
    keys_by_value: dict[str, set[str]] = {}
    for value, key in pairs:
        if label(value):
            keys_by_value.setdefault(value, set()).add(key)
    if not keys_by_value:
        return []
    all_keys = list({k for ks in keys_by_value.values() for k in ks})
    rows: list[NewsArticle] = []
    for i in range(0, len(all_keys), 500):
        rows += db.scalars(select(NewsArticle).where(NewsArticle.url_key.in_(all_keys[i:i + 500]),
                                                     NewsArticle.published_at >= since,
                                                     NewsArticle.published_at < until))
    found = _shown(db, md, rows, settings)  # once for every group
    out = []
    for value, keys in keys_by_value.items():
        heads = [found.heads[k] for k in keys if k in found.heads]
        if heads:
            out.append({"id": value, "label": label(value), "count": _story_count(heads),
                        "items": _render(db, md, _newest(heads, per_group), found)})
    out.sort(key=lambda g: (-g["count"], order.get(g["id"], 999)))
    return out
