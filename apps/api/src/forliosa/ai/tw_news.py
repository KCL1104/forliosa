"""``tw_news_search``: LangSearch for one Taiwan stock or the Taiwan market, for the AI (產品負責人 2026-11-17).

The owner decided to use LangSearch wherever it can be (the exception in CLAUDE.md): the chat asks it before Claude's
web search for every kind of Taiwan-stock question, and the stock page's 法人觀點 card (``analyst.from_langsearch``)
and 為什麼漲跌 sentence (``why.from_langsearch``) do too, through :func:`plan` and :func:`fetch` (the requests and
:func:`filter_items`) and :func:`blocks`, with the web search as before when it gives nothing usable. Research and
numbers: the round-2 recommendation (31 + 85 measured requests, a 12-question A/B), summarised in
``apps/api/CONTRACT_NOTES.md`` 「2026-11-17 AI 對話的 tw_news_search」 and 「2026-11-17 法人觀點與為什麼漲跌先查
LangSearch」.

The page text LangSearch returns (``snippet``, capped by ``contents.text.max_characters``: 300, or 600 for the 法人
intent, trimmed here to an excerpt of at most 300) goes to Claude inside that one answer only. It is never written to
the database, a cache or a log, and never sent to the browser: a citation of such a result carries its title line
(``safe_text``: 「媒體，11/10：標題」) instead of the passage, the stored turn has the title line in place of the
excerpt (:func:`scrub_messages`), and a sentence of an answer that copied an excerpt's wording is neither shown nor
stored (``chat.drop_wording_copies``: the editor is first asked to rewrite the marked copies; a restated figure stays).
Only the headline, outlet, date and link persist.

The search query is written here, never by the model, and holds only the company's short name and fixed words
(:func:`plan`); a stock's tier (``forliosa.news.langsearch``: large / mid / small / quiet) sets the news window and
the 法人 queries. Every result goes through the measured filter (:func:`filter_items`): Taiwanese news sites only,
no quote / warrant / forum pages, the stock named in the title (the news matcher), a checked date (from the URL where
it can be read: :func:`article_date`; a search-engine date that looks like a re-indexed old page is "unknown" and
dropped for the 法人, 營收, 配息 and 法說會 intents; a 法人 report with only the engine's date must also pass three
stale-article checks), then an excerpt of the sentences that match the intent.

Requests: ``forliosa.news.langsearch.chat_search`` (the same key, client, gap and refusal handling as the news worker,
with caps of its own, shared by the chat, the card and 為什麼漲跌: ``AI_LANGSEARCH_MAX_REQUESTS_PER_DAY`` /
``AI_LANGSEARCH_MAX_TOKENS_PER_DAY``), at most
``AI_LANGSEARCH_MAX_REQUESTS_PER_TURN`` per chat turn; the same arguments twice in a turn send one. When LangSearch
cannot be asked, or finds nothing, the tool says what to do next (web search, or in 省錢模式 to say there is no data).
"""

from __future__ import annotations

import copy
import itertools
import logging
import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from forliosa.config import Settings
from forliosa.marketdata.base import InstrumentInfo
from forliosa.marketdata.service import MarketData
from forliosa.models import NewsArticle
from forliosa.news import langsearch as ls
from forliosa.news import service
from forliosa.news.normalize import (
    Headline,
    Terms,
    clean_title,
    clean_url,
    dedupe,
    is_blocked,
    is_bot_flash,
    is_relevant,
)
from forliosa.news.outlets import host_of, is_aggregator, is_not_news, is_taiwan_outlet, on_domain, outlet_name
from forliosa.news.sources import RawItem
from forliosa.timeutil import TAIPEI, is_tw_trading_day, last_tw_trading_day, now_utc

log = logging.getLogger(__name__)

# The wall clock and the sleep the gap between requests is waited out with (tests replace them)
_clock: Callable[[], datetime] = now_utc
_sleep: Callable[[float], None] = time.sleep

TOOL_NAME = "tw_news_search"
INTENTS = ("news", "why_move", "analyst_targets", "earnings_call", "revenue", "dividend", "market")
# a date that may be a re-indexed old page is dropped for these (a number of last year read as this year's)
STRICT_INTENTS = frozenset({"analyst_targets", "revenue", "dividend", "earnings_call"})
DEFAULT_DAYS: dict[str, Any] = {"news": {"large": 7, "mid": 14, "small": 30, "quiet": 30}, "why_move": 1,
                                "analyst_targets": 90, "earnings_call": 45, "revenue": 35, "dividend": 60, "market": 0}
MAX_NEWS_DAYS = 30
INTENT_WORD = {"earnings_call": "法說會", "revenue": "營收", "dividend": "配息"}
INTENT_LABEL = {"news": "新聞", "why_move": "漲跌原因", "analyst_targets": "目標價", "earnings_call": "法說會",
                "revenue": "營收", "dividend": "配息", "market": "大盤"}
LIMIT = {"news": 10, "why_move": 10, "market": 10}
DEFAULT_LIMIT = 8
EXCERPT_MAX = 300
ANALYST_FETCH_CHARS = 600  # the 法人 intent reads 600 characters and keeps the 300 that name brokers and targets
GRACE = timedelta(hours=12)  # before the window's first day (datePublished's day boundary)
FUTURE_SLACK = timedelta(minutes=30)
URL_DATE_WINS = timedelta(days=3)  # the URL's date replaces the engine's when they are this far apart
UNKNOWN_SPAN_DAYS = 20  # windows this long are where re-indexed old pages turn up
UNKNOWN_CLUSTER = 4  # engine-dated items on one day: a re-indexing burst
JUNK_EXTRA = ("news.taiwannet.com.tw", "vocus.cc", "cmoney.tw", "poorstock.com", "wantgoo.com", "goodinfo.tw")
WJ_OUTLET = "世界日報（聯合報系轉載）"

# -- the measured rules (round 2, tool v2.1) ----------------------------------------------------------------------
INST = re.compile(
    r"摩根士丹利|大摩|摩根大通|小摩|高盛|美銀|美林|花旗|瑞銀|滙豐|匯豐|野村|麥格理|里昂|大和|瑞穗|伯恩斯坦|Bernstein|Aletheia|"
    r"德意志|德銀|巴克萊|傑富瑞|杰富瑞|Jefferies|星展|法巴|富瑞|Morgan Stanley|JPMorgan|Goldman|Citi|UBS|Nomura|"
    r"Macquarie|CLSA|HSBC|BofA|凱基|元大|富邦|國泰|永豐|統一|群益|兆豐|第一金|華南|台新|玉山|康和|元富|宏遠|日盛|國票|"
    r"福邦|新光|光和|合庫|中信|摩爾|(?:美|日|歐|港|陸|亞)系外資|[一-鿿]{2,3}投顧", re.I)
PRICE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:元|台幣)")
# the sentences an excerpt picks, by intent
FOCUS = {
    "analyst_targets": re.compile(r"目標價|評等|評級|首評|調升|調降|上調|下修|買進|加碼|減碼|中立|優於大盤|"
                                  r"劣於大盤|持有|喊|上看|外資|投顧|分析師|" + INST.pattern, re.I),
    "revenue": re.compile(r"營收|億元|月增|年增|月減|年減|累計|創.{0,4}新高"),
    "dividend": re.compile(r"配息|股利|配發|除息|殖利率|每股|現金"),
    "earnings_call": re.compile(r"法說|展望|毛利率|營益率|指引|財測|第[一二三四1-4]季|下季|明年|資本支出|EPS|每股"),
    "why_move": re.compile(r"跌|漲|股價|賣超|買超|外資|原因|利空|利多|消息|宣布|公告|營收|目標價"),
    "news": re.compile(r"宣布|公告|營收|法說|訂單|擴產|合作|併購|董事會|股利|目標價|外資|億元|今年|明年"),
    "market": re.compile(r"台股|加權|大盤|指數|外資|賣超|買超|點|跌|漲|成交"),
}
QUOTE_PAGE = re.compile(r"/quote/|/stock/\d{4}|/s/\d{4}|histock\.tw/stock|/technical|/chip", re.I)
WARRANT = re.compile(r"[購售]\d{2}|權證|\d{4,6}[A-Z]?\s*期貨|個股期")
SIDEBAR = re.compile(r"・\s*\d+\s*(?:小時|分鐘|天)前|\d+\s*(?:小時|分鐘)前\s*・")  # Yahoo's side column
SIDEBAR2 = re.compile(r"[!！]「|元[!！]|[!！]」|[!！]\s*$")  # FTNN's and Yahoo's lists of other stories
WJ_REPRINT = re.compile(r"worldjournal\.com/wj/story/121347/")  # 世界日報's reprints of 聯合報系 finance news
ANALYST_TITLE = re.compile(r"目標價|評等|評級|首評|降評|升評|喊|上看|看到\d|調升|調降|上調|下修|外資|投顧|券商|"
                           r"大摩|小摩|高盛|美銀|花旗|瑞銀|野村|麥格理|里昂|大和|滙豐|匯豐|摩根|伯恩斯坦|Bernstein")
TARGET_PAT = re.compile(r"目標價[^。！？]{0,14}?\d[\d,]*(?:\.\d+)?\s*元|\d[\d,]*(?:\.\d+)?\s*元[^。！？]{0,4}目標價|"
                        r"(?:喊|上看|看到)\s*\d[\d,]*(?:\.\d+)?\s*元")
TARGET_NUM = re.compile(r"目標價[^。！？；]{0,14}?(\d[\d,]*(?:\.\d+)?)\s*元")
PRICE_MENTION = re.compile(r"(?:股價|收盤|收在|收|跌破|站上|漲至|跌至|最低|最高|來到|報)[^。，,；]{0,6}?"
                           r"(\d[\d,]*(?:\.\d+)?)\s*元")
# a year before this one, not 「2025 年以來」 (v2.1 named 2010–2025; the comparison with this year is what counts)
OLD_YEAR = re.compile(r"(?<!\d)(20\d\d)\s*年(?!\s*(?:以來|起|至今|迄今))")
BOILER = re.compile(r"聽新聞\s*\d+:\d+\s*/\s*\d+:\d+|本文共\s*\d+\s*字|^\s*廣告\s*|\s廣告\s|"
                    r"[（(][^（）()]{0,20}攝[)）]|[（(]\s*(?:資料照|示意圖)[^（）()]{0,30}[)）]|▲[^。]{0,60}[)）]")


# -- the plan -----------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Plan:
    """What to ask LangSearch for one intent: the queries (the short name and fixed words only), the UTC-date window
    and where it starts, the contents cap, how many results go to Claude, and whether an unknown date is dropped."""

    intent: str
    queries: tuple[str, ...]
    freshness: str
    window_start: datetime
    max_chars: int
    limit: int
    days: int
    strict_dates: bool
    short: str | None = None  # the name in the queries (None for the market)


def effective_days(intent: str, tier: str, days: int) -> int:
    """``days`` from the model counts for ``news`` only (1–30); every other intent has its fixed window."""
    if intent == "news":
        if days > 0:
            return max(1, min(MAX_NEWS_DAYS, days))
        return DEFAULT_DAYS["news"].get(tier, DEFAULT_DAYS["news"]["mid"])
    return DEFAULT_DAYS[intent]


def freshness_for(days: int, now: datetime, first: date | None = None) -> tuple[str, datetime]:
    """``D-days..D`` in UTC dates (from 08:00 Taipei, Taipei's date), or ``first..D``; and 00:00 UTC of its first
    day."""
    d = now.astimezone(UTC).date()
    start = first if first is not None else d - timedelta(days=days)
    return f"{start.isoformat()}..{d.isoformat()}", datetime(start.year, start.month, start.day, tzinfo=UTC)


def plan(intent: str, info: InstrumentInfo | None, tier: str, days: int, now: datetime) -> Plan | None:
    """Pure. ``None``: nothing to ask (the 法人 intent of an ETF, or a stock without one). The queries hold only the
    stock's short name (:func:`forliosa.news.langsearch.query_name`: its market suffix and quotes removed; raises
    ``ValueError`` when nothing is left) and fixed words:

    * news / why_move: ``"簡稱"`` (news: 7 / 14 / 30 days by tier, or the model's 1–30; why_move: from the day before
      the last trading day, so a Friday move asked about on Sunday or Monday morning finds Friday's news)
    * analyst_targets: large ``"簡稱" 調升目標價`` and ``"簡稱" 調降目標價``; every other tier ``簡稱 目標價``
      (產品負責人 2026-11-17: small caps try LangSearch first too); 90 days, 600 characters
    * earnings_call / revenue / dividend: ``"簡稱" 法說會`` (45 days) / ``"簡稱" 營收`` (35) / ``"簡稱" 配息`` (60)
    * market: ``台股 盤中`` from 09:00 to 14:00 Taipei, else ``台股 盤後``; today (on a day without trading, since the
      last trading day)"""
    if intent not in INTENTS:
        raise ValueError(f"unknown intent {intent!r}")
    n = effective_days(intent, tier, days)
    limit = LIMIT.get(intent, DEFAULT_LIMIT)
    strict = intent in STRICT_INTENTS
    if intent == "market":
        local = now.astimezone(TAIPEI)
        query = "台股 盤中" if 9 <= local.hour < 14 and is_tw_trading_day(local.date()) else "台股 盤後"
        first = None if is_tw_trading_day(local.date()) else min(last_tw_trading_day(local.date()),
                                                                now.astimezone(UTC).date())
        fresh, start = freshness_for(0, now, first)
        return Plan(intent, (query,), fresh, start, EXCERPT_MAX, limit, n, strict)
    if info is None:
        return None
    short = ls.query_name(info.name)
    fresh, start = freshness_for(n, now)
    if intent == "why_move":  # like ``why.from_langsearch``: the trading day of the UTC date, and the day before
        today = now.astimezone(UTC).date()
        first = last_tw_trading_day(today) - timedelta(days=1)
        fresh, start = freshness_for(0, now, first)
        n = (today - first).days
    if intent == "analyst_targets":
        if info.type != "stock":
            return None
        queries = (f'"{short}" 調升目標價', f'"{short}" 調降目標價') if tier == "large" else (f"{short} 目標價",)
        return Plan(intent, queries, fresh, start, ANALYST_FETCH_CHARS, limit, n, strict, short)
    query = f'"{short}" {INTENT_WORD.get(intent, "")}'.strip()
    return Plan(intent, (query,), fresh, start, EXCERPT_MAX, limit, n, strict, short)


_RANKS: dict[str, Any] = {"at": None, "ranks": {}}
_RANKS_TTL = 3600.0
_RANKS_LOCK = threading.Lock()


def tier_for(db: Session, md: MarketData, info: InstrumentInfo, settings: Settings) -> str:
    """The news worker's stored tier (large / mid / small / quiet); before it has one, market-cap rank ≤
    ``NEWS_LANGSEARCH_LARGE_RANK`` is large, everything else mid (the ranks are kept an hour in this process)."""
    st = ls.read_tier(db, info.symbol)
    if st is not None:
        return st.tier
    with _RANKS_LOCK:
        # read within the hour, even when it found nothing (no profiles or closes yet): not read again per call
        fresh = _RANKS["at"] is not None and time.monotonic() - _RANKS["at"] < _RANKS_TTL
    if not fresh:
        try:
            ranks = ls.market_cap_ranks(db, md)
        except Exception:  # a tier is a nicety: mid when the ranks cannot be read
            log.warning("tw_news_search: market-cap ranks not read", exc_info=True)
            db.rollback()
            ranks = {}
        with _RANKS_LOCK:
            _RANKS.update(at=time.monotonic(), ranks=ranks)
    rank = _RANKS["ranks"].get(info.symbol)
    return "large" if rank is not None and rank <= settings.news_langsearch_large_rank else "mid"


# -- dates --------------------------------------------------------------------------------------------------------
_STORY = (("udn", re.compile(r"^https?://(?:[a-z0-9-]+\.)*udn\.com/(?:news|money)/story/\d+/(\d{6,9})(?:[/?#.]|$)",
                             re.I)),
          ("wj", re.compile(r"^https?://(?:www\.)?worldjournal\.com/wj/story/\d+/(\d{6,9})(?:[/?#.]|$)", re.I)))
CALIB_DAYS = 120
CALIB_MIN_POINTS = 3
CALIB_NEW_END = timedelta(days=2)
CALIB_TTL = 24 * 3600.0


def story_id(url: str) -> tuple[str, int] | None:
    """``("udn", 9880441)`` for udn.com / money.udn.com (one numbering), ``("wj", …)`` for 世界日報 (its own)."""
    for series, pat in _STORY:
        m = pat.match(url or "")
        if m:
            return series, int(m.group(1))
    return None


@dataclass(frozen=True)
class UdnCalibration:
    """udn's and 世界日報's story numbers grow with time: a story's date is read from its number between dated
    points of our own (stored headlines of those sites whose time did not come from LangSearch, one median number per
    day). Only inside the calibrated range (and up to two days after its newest point); a series needs three points."""

    series: dict[str, tuple[tuple[int, date], ...]] = field(default_factory=dict)

    @classmethod
    def from_points(cls, points: Iterable[tuple[str, int, date]]) -> UdnCalibration:
        by_day: dict[tuple[str, date], list[int]] = {}
        for series, sid, day in points:
            by_day.setdefault((series, day), []).append(sid)
        out: dict[str, list[tuple[int, date]]] = {}
        for (series, day), ids in sorted(by_day.items(), key=lambda x: (x[0][0], x[0][1])):
            ids.sort()
            median = ids[len(ids) // 2]
            pts = out.setdefault(series, [])
            if pts and median <= pts[-1][0]:  # numbers must grow with the days: an outlier day is left out
                continue
            pts.append((median, day))
        return cls({s: tuple(p) for s, p in out.items() if len(p) >= CALIB_MIN_POINTS})

    def date_of(self, url: str) -> date | None:
        found = story_id(url)
        if found is None:
            return None
        pts = self.series.get(found[0])
        if not pts:
            return None
        sid = found[1]
        if sid < pts[0][0]:
            return None
        for (a, da), (b, db) in itertools.pairwise(pts):
            if a <= sid <= b:
                return da + timedelta(days=round((sid - a) / (b - a) * (db - da).days)) if b > a else da
        (a, da), (b, db) = pts[0], pts[-1]
        per_day = (b - a) / max(1, (db - da).days)
        d = db + timedelta(days=round((sid - b) / per_day)) if per_day > 0 else None
        return d if d is not None and d <= db + CALIB_NEW_END else None


_CALIB: dict[str, Any] = {"at": None, "value": None}
_CALIB_LOCK = threading.Lock()


def reset_caches() -> None:
    """Tests (and a restart): the udn calibration and the market-cap ranks are read again."""
    with _CALIB_LOCK:
        _CALIB.update(at=None, value=None)
    with _RANKS_LOCK:
        _RANKS.update(at=None, ranks={})


def calibration(db: Session, now: datetime | None = None) -> UdnCalibration:
    """The calibration from the stored headlines of the last :data:`CALIB_DAYS` days (titles, links and times only),
    kept a day in this process."""
    with _CALIB_LOCK:
        if _CALIB["at"] is not None and time.monotonic() - _CALIB["at"] < CALIB_TTL:
            return _CALIB["value"]
    now = now or now_utc()
    points: list[tuple[str, int, date]] = []
    try:
        rows = db.execute(select(NewsArticle.url, NewsArticle.published_at).where(
            NewsArticle.source != ls.SOURCE_KEY, NewsArticle.published_at >= now - timedelta(days=CALIB_DAYS),
            or_(NewsArticle.domain == "udn.com", NewsArticle.domain.like("%.udn.com"),
                NewsArticle.domain == "worldjournal.com", NewsArticle.domain.like("%.worldjournal.com"))))
        for url, published in rows:
            found = story_id(url)
            if found is not None and published is not None:
                at = published if published.tzinfo else published.replace(tzinfo=UTC)
                points.append((found[0], found[1], at.astimezone(TAIPEI).date()))
    except Exception:  # without it, udn's dates are the engine's
        log.warning("tw_news_search: udn calibration not read", exc_info=True)
        db.rollback()
    value = UdnCalibration.from_points(points)
    with _CALIB_LOCK:
        _CALIB.update(at=time.monotonic(), value=value)
    return value


def article_date(url: str, published: datetime | None,
                 calib: UdnCalibration | None = None) -> tuple[datetime | None, str]:
    """``(date, "url" | "engine")``. The URL's date (written in it: ``analyst.date_from_url``; else read from a udn /
    世界日報 story number: :class:`UdnCalibration`), as 00:00 Taipei of that day, wins when it is three days or more
    from the search engine's; closer than that the engine's is kept (it has the time), still checked by the URL."""
    from forliosa.ai.analyst import date_from_url

    d = date_from_url(url) or (calib.date_of(url) if calib is not None else None)
    if d is None:
        return published, "engine"
    at = datetime(d.year, d.month, d.day, tzinfo=TAIPEI)
    if published is None or abs(at - published) >= URL_DATE_WINS:
        return at, "url"
    return published, "url"


# -- excerpts -----------------------------------------------------------------------------------------------------
def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?；])|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]


def excerpt_of(text: str, intent: str, short: str | None, limit: int = EXCERPT_MAX) -> str:
    """The sentences that match the intent (the name counts too; for the 法人 intent a broker with a price most),
    in their original order, at most ``limit`` characters — never the whole passage as it was."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return ""
    focus = FOCUS.get(intent, FOCUS["news"])
    scored = []
    for i, s in enumerate(sentences(text)):
        score = len(focus.findall(s)) + (2 if short and short in s else 0)
        if intent == "analyst_targets" and PRICE.search(s) and INST.search(s):
            score += 4
        scored.append((score, i, s))
    picked: list[tuple[int, str]] = []
    size = 0
    for score, i, s in sorted(scored, key=lambda x: (-x[0], x[1])):
        if score <= 0 and picked:
            break
        if size + len(s) > limit:
            if not picked:
                picked.append((i, s[:limit]))
                size = limit
            continue
        picked.append((i, s))
        size += len(s)
    return "".join(s for _, s in sorted(picked))[:limit]


def clean_text(text: str, title: str) -> str:
    """Page noise out (「聽新聞 0:00 / 1:23」「本文共 627 字」「廣告」「（記者…攝）」) and a leading copy of the
    title."""
    t = re.sub(r"\s+", " ", text or "").strip()
    if len(t) <= 1:
        return ""
    t = BOILER.sub(" ", t).strip()
    dense = re.sub(r"\s+", "", title)
    if len(dense) >= 8 and re.sub(r"\s+", "", t).startswith(dense):
        n = 0
        for i, c in enumerate(t):
            if not c.isspace():
                n += 1
            if n == len(dense):
                t = t[i + 1:]
                break
    return re.sub(r"\s+", " ", t).strip()


def yahoo_text_ok(host: str, title: str, text: str) -> bool:
    """Yahoo's text is often its side column of other stories: kept only when it carries the title and no list of
    「N 小時前」."""
    if "yahoo.com" not in host:
        return True
    if SIDEBAR.search(text):
        return False
    t = re.sub(r"\s+", "", title)[:12]
    dense = re.sub(r"\s+", "", text)
    return bool(t) and (t[:6] in dense or t[-6:] in dense)


# -- the filter ---------------------------------------------------------------------------------------------------
@dataclass
class Item:
    """One kept article: what Claude gets (the excerpt in memory only) and what may persist (title, outlet, date,
    link)."""

    title: str
    url: str
    outlet: str
    host: str
    date: datetime
    date_src: str  # url | engine
    unknown_date: bool = False
    excerpt: str = field(default="", repr=False)


def junk_domains(settings: Settings) -> tuple[str, ...]:
    return tuple(dict.fromkeys(d.lower().removeprefix("www.")
                               for d in (*settings.news_langsearch_junk_domains, *JUNK_EXTRA)))


def _price(x: str) -> float:
    return float(x.replace(",", ""))


def filter_items(items: Sequence[RawItem], p: Plan, *, terms: Terms | None, code: str | None, close: float | None,
                 now: datetime, stats: Counter[str], calib: UdnCalibration | None = None,
                 blocked: Sequence[str] = (), junk: Sequence[str] = JUNK_EXTRA) -> list[Item]:
    """One answer's raw items -> the kept articles, in the measured order (each drop counted in ``stats``):

    1. a usable link; not a page that is not news, not taken down, not junk;
    2. a Taiwanese site (the 法人 intent also keeps 世界日報's reprints of 聯合報系; other 世界日報 pages go);
    3. a cleaned title, not a robot flash; 4. not a quote page, not a warrant / futures title;
    5. the market: a market word in the title; a stock: named in the title (the news matcher), or for the 法人 intent
       one sentence of the text naming it (short name or code) with a target price, on a site that is not an
       aggregator;
    6. a date (:func:`article_date`) inside the window (its start less 12 hours, at most 30 minutes ahead); in a
       window of 20 days or more an engine-only date on the window's first day, or shared by 4 engine-dated items,
       is unknown: dropped for the strict intents, marked for the others;
    7. the excerpt (:func:`excerpt_of` of :func:`clean_text`; none — title only — for Yahoo's side column or FTNN's
       lists);
    8. the 法人 intent keeps an item whose title names the stock and a broker / target word, or whose excerpt has a
       target price; an engine-dated strict item is dropped when a price it mentions is under half or over twice
       ``close``, a 法人 one when all its targets are under half ``close`` or it names an earlier year (any of the
       years it names, 「2025 年以來」 aside)."""
    intent, short = p.intent, p.short or ""
    analyst = intent == "analyst_targets"
    found: list[tuple[Item, str]] = []
    for it in items:
        url = clean_url(it.url)
        if url is None:
            stats["link"] += 1
            continue
        host = host_of(url)
        reprint = analyst and bool(WJ_REPRINT.search(url))
        if is_not_news(url) or is_blocked(url, blocked) or any(
                on_domain(host, d) for d in junk if not (reprint and d == "worldjournal.com")):
            stats["junk"] += 1
            continue
        if (not is_taiwan_outlet(url) and not reprint) or (on_domain(host, "worldjournal.com") and not reprint):
            stats["not_taiwan"] += 1
            continue
        outlet = WJ_OUTLET if reprint else outlet_name(url)
        title = clean_title(it.title, url, outlet)
        if not title or is_bot_flash(title):
            stats["title"] += 1
            continue
        if QUOTE_PAGE.search(url) or WARRANT.search(title):
            stats["quote_page"] += 1
            continue
        text = getattr(it, "text", "") or ""  # ``langsearch.TextItem``: the AI's requests only
        if intent == "market":
            about = bool(ls.TOPIC_KEYWORDS.search(title))
        else:
            about = terms is not None and is_relevant(title, terms, url=url, raw_title=it.title)
            if not about and analyst and text and not is_aggregator(url):
                about = any(((short and short in s) or (code and code in s)) and TARGET_PAT.search(s)
                            for s in sentences(text))
        if not about:
            stats["not_about"] += 1
            continue
        when, src = article_date(url, it.published_at, calib)
        if when is None:
            stats["no_date"] += 1
            continue
        found.append((Item(title, url, outlet, host, when, src), text))
    span = (now - p.window_start).days
    engine_days = Counter(x.date.astimezone(UTC).date() for x, _ in found if x.date_src == "engine")
    kept: list[Item] = []
    for x, text in found:
        day = x.date.astimezone(UTC).date()
        unknown = x.date_src == "engine" and span >= UNKNOWN_SPAN_DAYS and (
            day == p.window_start.date() or engine_days[day] >= UNKNOWN_CLUSTER)
        if x.date < p.window_start - GRACE or x.date > now + FUTURE_SLACK:
            stats["out_of_window"] += 1
            continue
        if unknown and p.strict_dates:
            stats["date_unknown"] += 1
            continue
        x.unknown_date = unknown
        clean = clean_text(text, x.title)
        excerpt = ""
        if clean and yahoo_text_ok(x.host, x.title, text) and len(SIDEBAR2.findall(clean)) < 2:
            excerpt = excerpt_of(clean, intent, short)
        elif len(text) > 1:
            stats["side_text"] += 1  # title only (not a drop)
        if analyst and not (ANALYST_TITLE.search(x.title) and ((short and short in x.title)
                                                               or (code and code in x.title))) \
                and not TARGET_PAT.search(excerpt):
            stats["no_analyst_content"] += 1
            continue
        if p.strict_dates and x.date_src == "engine" and close and excerpt:
            prices = [v for v in (_price(m) for m in PRICE_MENTION.findall(excerpt)) if v > 0]
            if prices and any(v < 0.5 * close or v > 2.0 * close for v in prices):
                stats["stale_price"] += 1
                continue
            targets = [_price(m) for m in TARGET_NUM.findall(excerpt)]
            if analyst and targets and all(t < 0.5 * close for t in targets):
                stats["stale_target"] += 1
                continue
        # every year it names: a broker's note names next year's forecast first, a stale one its own year after
        if analyst and x.date_src == "engine" and excerpt and any(
                int(y) <= now.year - 1 for y in OLD_YEAR.findall(excerpt)):
            stats["old_year"] += 1
            continue
        x.excerpt = excerpt
        kept.append(x)
    return kept


def dedupe_items(items: Iterable[Item]) -> list[Item]:
    """One item per story (``normalize.dedupe``: the original outlet over a Yahoo / LINE copy), newest first."""
    items = list(items)
    by_url: dict[str, Item] = {}
    for x in items:
        by_url.setdefault(x.url, x)
    heads = [Headline(title=x.title, url=x.url, outlet=x.outlet, domain=x.host, published_at=x.date,
                      source=ls.SOURCE_KEY) for x in by_url.values()]
    return [by_url[h.url] for h in dedupe(heads)]


# -- asking (the chat tool, the 法人觀點 card, 為什麼漲跌) -----------------------------------------------------------
def usable_for(settings: Settings, info: InstrumentInfo | None) -> bool:
    """LangSearch may be asked about ``info``: ``AI_LANGSEARCH_ENABLED`` with a key, and a Taiwan-listed instrument
    (everything else keeps its own path, exactly as before)."""
    return bool(settings.ai_langsearch_on and info is not None and info.market in ("TWSE", "TPEX")
                and service.is_taiwan_symbol(info.symbol))


@dataclass
class Found:
    """What one plan brought back: the kept articles (their excerpts in memory only) and counts for the log."""

    plan: Plan
    items: list[Item]
    answers: int = 0  # replies booked (a request that was not sent is not one)
    requests: int = 0
    tokens: int = 0
    results: int = 0
    stopped: str | None = None  # the key or the AI's day stopped part-way (``langsearch.ChatUnavailable`` reasons)
    failed: bool = False  # every reply failed

    @property
    def status(self) -> str:
        return "ok" if self.items else "error" if self.failed else "none"


def fetch(db: Session, md: MarketData, settings: Settings, p: Plan, info: InstrumentInfo | None, *,
          now: datetime, queries: Sequence[str] | None = None, label: str = TOOL_NAME) -> Found:
    """Ask LangSearch the plan's queries (or ``queries``, a part of them) through
    :func:`forliosa.news.langsearch.chat_search` — the AI's daily caps and the key's stop state, shared by the chat,
    the 法人觀點 card and 為什麼漲跌 — and keep what passes :func:`filter_items`, one per story, newest first, at most
    ``p.limit``. Raises ``langsearch.ChatUnavailable`` when nothing may be sent. Logs counts only (``label`` says
    who asked): never a title, an excerpt or a key."""
    from forliosa.ai import analyst

    started = time.monotonic()
    close = analyst.reference_price(md, info.symbol) if info is not None and p.strict_dates else None
    batch = ls.chat_search(db, settings, list(queries if queries is not None else p.queries), p.freshness,
                           max_characters=p.max_chars, clock=_clock, sleep=_sleep)
    terms = service.query_terms(db, info, md) if info is not None else None
    calib = calibration(db, now)
    blocked = service.blocked_domains(db, settings)
    junk = junk_domains(settings)
    stats: Counter[str] = Counter()
    kept: list[Item] = []
    for a in batch.answers:
        kept += filter_items(a.items, p, terms=terms, code=info.code if info is not None else None, close=close,
                             now=now, stats=stats, calib=calib, blocked=blocked, junk=junk)
    found = Found(p, dedupe_items(kept)[:p.limit], len(batch.answers), batch.requests, batch.tokens,
                  sum(len(a.items) for a in batch.answers), batch.stopped,
                  bool(batch.stopped) or all(a.error for a in batch.answers))
    log.info("%s %s %s: %d requests, %d tokens, %d results, %d kept, %s in %.1f s; dropped %s", label, p.intent,
             info.symbol if info is not None else "^TW", found.requests, found.tokens, found.results,
             len(found.items), found.status if not found.stopped else f"{found.status} (stopped: {found.stopped})",
             time.monotonic() - started, dict(stats))
    return found


# -- what Claude gets -----------------------------------------------------------------------------------------------
def _md(when: datetime, today: date) -> str:
    d = when.astimezone(TAIPEI).date()
    return f"{d.month}/{d.day}" if d.year == today.year else f"{d.year}/{d.month}/{d.day}"


def blocks(items: Sequence[Item], today: date) -> list[dict[str, Any]]:
    """The items of a ``Citable`` (``forliosa.ai.tools``), one search result per article: ``text`` 「媒體，11/10：
    摘錄」 (「，日期依搜尋引擎」 after an engine-only date; an unknown one has no date at all, 「媒體，日期未確認：」:
    its day is the window's first or a re-indexing burst's, so the model must not write it; 「（只有標題）」 without an
    excerpt), ``safe_text`` the title line 「媒體，11/10：標題」 (「媒體，日期未確認：標題」; what a citation, the
    stored turn and the shared research carry instead), ``private``. No 「[n]」 numbering (the model copied
    「（[4-1]）」 into answers)."""
    out = []
    for x in items:
        when = "日期未確認" if x.unknown_date else _md(x.date, today)
        suffix = "" if x.date_src == "url" or x.unknown_date else "，日期依搜尋引擎"
        out.append({"url": x.url, "title": x.title[:300], "outlet": x.outlet,
                    "text": f"{x.outlet}，{when}{suffix}：{x.excerpt or '（只有標題）'}",
                    "safe_text": f"{x.outlet}，{when}：{x.title}"[:400], "private": True})
    return out


def excerpt_texts(private_texts: Iterable[str]) -> list[str]:
    """The excerpts of :func:`blocks` texts (「媒體，11/10：摘錄」 → 「摘錄」): what a copy is looked for in — the
    outlet and date before them are the title line's too."""
    return [t.split("：", 1)[1] if "：" in t else t for t in private_texts]


def _dense(text: Any) -> str:
    return "".join(text.split()) if isinstance(text, str) else ""


def scrub_messages(messages: list[dict[str, Any]], redact: dict[str, str],
                   private_texts: Sequence[str] = ()) -> list[dict[str, Any]]:
    """A copy of a turn's messages for storing and sharing, with the LangSearch excerpts replaced by their title lines
    (``redact``: url -> title line):

    * a ``search_result`` of a ``tw_news_search`` tool result (its ``tool_use_id`` is one of the turn's calls of the
      tool) whose ``source`` is in ``redact`` gets the title line as its only text (``title``, ``source`` and
      ``citations`` stay) — another tool's result with the same link (``get_news`` holds LangSearch's headlines too)
      stays as it was;
    * a ``search_result_location`` citation to such a link gets the title line as ``cited_text`` and covers that one
      block, unless what it cites is the other tool's text under that link;
    * the model's own text loses the sentences that copied an excerpt's wording (``private_texts``;
      ``chat.copied_sentences``, looked for across the message's text blocks: the rule the answer shown and stored as
      ``ai_messages.text`` follows too), never a sentence that only restates figures;

    every other block stays as it was."""
    if not redact:
        return messages
    from forliosa.ai.chat import copied_sentences

    excerpts = excerpt_texts(private_texts)
    out = copy.deepcopy(messages)
    calls = {b.get("id") for m in out if m.get("role") == "assistant" and isinstance(m.get("content"), list)
             for b in m["content"]
             if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == TOOL_NAME}
    # what the turn's other search results (get_news, the shared research) say under a link the tool returned too
    other: dict[str, str] = {}
    for m in out:
        if m.get("role") != "user" or not isinstance(m.get("content"), list):
            continue
        for b in m["content"]:
            if not isinstance(b, dict) or (b.get("type") == "tool_result" and b.get("tool_use_id") in calls):
                continue
            found = b.get("content") if b.get("type") == "tool_result" else [b]
            for r in found if isinstance(found, list) else []:
                if isinstance(r, dict) and r.get("type") == "search_result" and r.get("source") in redact:
                    other[r["source"]] = other.get(r["source"], "") + "".join(
                        _dense(t.get("text")) for t in r.get("content") or [] if isinstance(t, dict))
    for m in out:
        content = m.get("content")
        if not isinstance(content, list):
            continue
        if m.get("role") == "user":
            for b in content:
                if (isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in calls
                        and isinstance(b.get("content"), list)):
                    for r in b["content"]:
                        if isinstance(r, dict) and r.get("type") == "search_result" and r.get("source") in redact:
                            r["content"] = [{"type": "text", "text": redact[r["source"]]}]
            continue
        if m.get("role") != "assistant":
            continue
        texts = [b for b in content
                 if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)]
        if excerpts and texts:
            spans = copied_sentences("".join(b["text"] for b in texts), excerpts)
            at = 0
            for b in texts:
                lo, hi = at, at + len(b["text"])
                at = hi
                left = b["text"]
                for a, z in reversed([(max(a, lo) - lo, min(z, hi) - lo) for a, z in spans if a < hi and z > lo]):
                    left = left[:a] + left[z:]
                if left != b["text"]:
                    b["text"] = left if left.strip() else "（略）"
        for b in texts:
            for c in b.get("citations") or []:
                if not (isinstance(c, dict) and c.get("type") == "search_result_location"
                        and c.get("source") in redact):
                    continue
                cited = _dense(c.get("cited_text"))
                if cited and cited in other.get(c["source"], ""):  # it cites the other tool's text, no excerpt
                    continue
                c.update(cited_text=redact[c["source"]], start_block_index=0, end_block_index=1)
    return out


# -- the tool -------------------------------------------------------------------------------------------------------
@dataclass
class TwNewsTurn:
    """One chat turn's use of the tool, shared by the tools that run side by side: requests sent (the empty-result
    retry aside) against ``AI_LANGSEARCH_MAX_REQUESTS_PER_TURN``, tokens, each call's outcome (``intent:status``) and
    the results by arguments (the same call twice sends one request). In memory only, for this turn."""

    settings: Settings
    max_requests: int = 3
    requests: int = 0
    tokens: int = 0
    calls: list[str] = field(default_factory=list)
    _memo: dict[tuple[str, str, int], Any] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def for_settings(cls, settings: Settings) -> TwNewsTurn:
        return cls(settings, settings.ai_langsearch_max_requests_per_turn)

    def reserve(self, n: int) -> int:
        with self._lock:
            k = max(0, min(n, self.max_requests - self.requests))
            self.requests += k
            return k

    def release(self, n: int) -> None:
        if n > 0:
            with self._lock:
                self.requests = max(0, self.requests - n)

    def done(self, key: tuple[str, str, int], intent: str, status: str, result: Any, tokens: int = 0) -> Any:
        with self._lock:
            self._memo[key] = result
            self.calls.append(f"{intent}:{status}")
            self.tokens += tokens
        return result

    def memo(self, key: tuple[str, str, int]) -> Any:
        with self._lock:
            return self._memo.get(key)


def _no_web(economy: bool, then: str) -> str:
    """The next step: ``then`` (a web search), or in 省錢模式 (no web search) to say there is no data."""
    return "這一題沒有網路搜尋：照實說目前沒有這項資料" if economy else then


def error_note(economy: bool, what: str = "tw_news_search 暫時不能用") -> str:
    return f"{what}；{_no_web(economy, '改用 web_search')}"


def none_note(intent: str, short: str | None, days: int, economy: bool) -> str:
    """What to say when nothing was found: the 法人 intent may search the web twice (then 「目前沒有機構評等與目標價的
    資料」); why_move points to the next step of 為什麼漲跌 (intent news, 30 days, then one web search for 外電); every
    other intent must not ask again with other words."""
    what = {"analyst_targets": "機構評等或目標價的報導", "market": "今天的台股盤勢報導"}.get(intent, "相關報導")
    span = "今天" if days == 0 else f"近 {days} 天"
    note = f"{span}台灣新聞網站沒有找到{short + '的' if short else ''}{what}。"
    if intent == "why_move":  # the prompt's next step: the company's news of the last month, then the web for 外電
        then = "再用 tw_news_search（intent news，days 30）看最近一個月公司的事"
        return note + then + ("；這一題沒有網路搜尋，其他的照實說查不到。" if economy
                              else "；外電用 web_search 搜一次。")
    if economy:
        if intent == "analyst_targets":
            return note + "這一題沒有網路搜尋：回答目前沒有機構評等與目標價的資料。"
        return note + "不要換關鍵字再查一次 tw_news_search；這一題沒有網路搜尋：照實說目前沒有這項資料。"
    if intent == "analyst_targets":
        return note + ("照「機構評等與目標價」的方式改用 web_search 找（最多兩次）；"
                       "還是沒有就回答目前沒有機構評等與目標價的資料。")
    return note + "不要換關鍵字再查一次 tw_news_search；需要時用 web_search 搜一次。"


def validate(args: dict[str, Any]) -> tuple[str, int, str]:
    """The arguments of the non-strict tool, checked here: ``intent`` one of :data:`INTENTS`, ``days`` an integer
    (a numeric string or a whole float is taken; missing is 0), ``symbol`` a string of at most 40 characters."""
    from forliosa.ai.tools import ToolError

    intent = args.get("intent")
    if not isinstance(intent, str) or intent not in INTENTS:
        raise ToolError(f"intent 只能是 {'、'.join(INTENTS)}")
    raw = args.get("days")
    if raw is None or raw == "":
        days = 0
    elif isinstance(raw, bool):
        raise ToolError("days 必須是整數（0 用預設值）")
    elif isinstance(raw, int):
        days = raw
    elif (isinstance(raw, float) and raw.is_integer()) or (isinstance(raw, str)
                                                            and re.fullmatch(r"\s*-?\d{1,3}\s*", raw)):
        days = int(raw)
    else:
        raise ToolError("days 必須是整數（0 用預設值）")
    symbol = args.get("symbol", "")
    if symbol is None:
        symbol = ""
    if not isinstance(symbol, str):
        raise ToolError("symbol 必須是字串（台股代號或名稱；大盤填 \"\"）")
    if len(symbol) > 40:
        raise ToolError("symbol 太長：填台股代號或名稱")
    return intent, days, symbol.strip()


def tw_news_search(ctx: Any, args: dict[str, Any]) -> Any:
    """The tool (``forliosa.ai.tools``: not strict, so the arguments are checked here). A ``Citable`` of the kept
    articles, or ``{"status": "none" | "error", "note": …}`` saying what to do next."""
    from forliosa.ai.tools import Citable, resolve_instrument

    intent, days, symbol = validate(args)
    turn: TwNewsTurn | None = getattr(ctx, "tw_news", None)
    economy = bool(getattr(ctx, "economy", False))
    if turn is None or not turn.settings.ai_langsearch_on:
        return {"status": "error", "note": error_note(economy)}
    settings = turn.settings
    now = _clock()
    info = None
    if intent != "market":
        info = resolve_instrument(ctx.md, symbol)
        if info.market not in ("TWSE", "TPEX") or not service.is_taiwan_symbol(info.symbol):
            return {"status": "error", "note": error_note(economy, "tw_news_search 只查台股；美股與海外消息"
                                                          + ("不能查" if economy else "用 web_search"))}
    tier = tier_for(ctx.db, ctx.md, info, settings) if info is not None else "large"
    try:
        p = plan(intent, info, tier, days, now)
    except ValueError:  # a name LangSearch cannot be asked with (digits only)
        p = None
    if p is None:
        if info is not None and info.type != "stock":
            return {"status": "none", "note": "ETF 沒有個別機構的評等與目標價"}
        return {"status": "none", "note": none_note(intent, info.name if info else None, 0, economy)}
    key = (info.symbol if info is not None else "^TW", intent, p.days)
    if (hit := turn.memo(key)) is not None:
        return hit
    allowed = turn.reserve(len(p.queries))
    if not allowed:
        return {"status": "error", "note": error_note(economy, f"這一題已經查過 {turn.max_requests} 次台灣新聞")}
    try:
        found = fetch(ctx.db, ctx.md, settings, p, info, now=now, queries=p.queries[:allowed])
    except ls.ChatUnavailable as exc:
        turn.release(allowed)
        log.info("tw_news_search %s %s: not asked (%s)", intent, key[0], exc.reason)
        return turn.done(key, intent, f"error:{exc.reason}", {"status": "error", "note": error_note(economy)})
    turn.release(allowed - found.answers)
    status = found.status
    if status == "error":
        return turn.done(key, intent, status, {"status": "error", "note": error_note(economy)}, found.tokens)
    if status == "none":
        return turn.done(key, intent, status, {"status": "none", "note": none_note(intent, p.short, p.days, economy)},
                         found.tokens)
    return turn.done(key, intent, status, Citable(blocks(found.items, now.astimezone(TAIPEI).date())), found.tokens)
