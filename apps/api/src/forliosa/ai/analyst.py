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
An empty ``ready`` entry (nothing found: in practice a small cap) is kept for ``EMPTY_KEEP_TRADING_DAYS`` trading
days and stands in for the following days' entries (``kept_empty``), unless a 法說會 or financial-report notice of
that stock was archived after it, or a 法說會 was held since (``new_notice``): then the stock is searched again
(product owner 2026-11-16, decision 5). Only for a stock no search result shows a rating headline of in the last
``COVERED_DAYS``: one that was rated (家登) keeps its empty entry for the day only, since one search may miss what
the next finds.

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
the title, not verifiably older than ``MAX_AGE_DAYS``), while a candidate was dropped only because its URL or date
could not be checked (``UNSURE_DROPS``), when a search failed (``search_errors``: too_many_requests, unavailable…), or
when a search left out the stock's name, code and aliases (``query_terms``: an M31 card was searched as 晶心科), the
entry is ``unavailable`` (retried after 10 minutes).

LangSearch first (產品負責人 2026-11-17, ``AI_LANGSEARCH_ENABLED`` with a key, Taiwan stocks only: ``from_langsearch``):
before the web search, the measured 法人 queries go to LangSearch (``tw_news.plan("analyst_targets")``: a large cap
``"簡稱" 調升目標價`` and ``"簡稱" 調降目標價``, every other ``簡稱 目標價``; 90 days, 600 characters a result), shared
with the chat's daily cap and the key's stop state (``langsearch.chat_search``); the results pass the v2.1 filter with
its date checks (``tw_news.filter_items``: a URL date, or an engine-only date that passes the three stale-article
checks; an unknown date is dropped). Up to ``LS_ARTICLES`` kept articles go, as search results with their excerpt
(at most 300 characters, for this request only), to one cheap extraction call (``AI_MODEL``, low effort, no web
search) that answers with the same ``report_analyst_views``; ``verify`` then keeps an item only when its URL is one of
those articles, dated by that article's checked date, shown with its title. At least ``LS_MIN_NAMED`` named
institutions → the card is ``ready`` from it; anything less (nothing kept, LangSearch stopped or over its cap, the
call failed) → the web search below, unchanged. The card stores only the extracted institution, action, rating,
target price, date, the article's title and link: never an excerpt.

Grounding (``verify``): an item is kept only when its URL is one of the ``web_search_result`` URLs the model
actually received in this generation (compared without scheme, ``www.``, trailing slash, fragment or
percent-encoding; the shown URL and title are the search result's own), the page is an article (not an aggregator,
quote, rating or forecast page: ``is_article``), and the article date can be read from that result's URL or
``page_age`` metadata (the shown date is that article date, not the model's). Items older than ``MAX_AGE_DAYS``,
with neither rating nor target price, or with a target price in another currency are dropped; a target price far
from the last real price (``TARGET_RATIO_MIN``–``TARGET_RATIO_MAX``, ``TARGET_RATIO_MAX_US`` for US stocks, an
internal filter that is never shown) is treated as another currency too. Numbers are passed through as written —
never converted, averaged or compared. Newest first, one per institution (大摩 = 摩根士丹利 = Morgan Stanley; the
shown name is the report's own), at most ``MAX_ITEMS``; items older than ``RECENT_DAYS`` are marked ``old`` (shown
as 舊資料) and come after the newer ones.
An institution the report does not name (``institution_key``: 「美系外資」「外資券商」「Wall Street analysts」) is
dropped, except a foreign broker named only by region (「日系外資」 → 「未具名外資（日系）」, ``unnamed_label``): kept
when at most ``UNNAMED_MAX_AGE_DAYS`` old, marked ``unnamed``, at most ``UNNAMED_MAX``, never folded into a named one
(product owner 2026-11-16, decisions 2–4).
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

import anthropic
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from forliosa.ai import store, tw_news
from forliosa.ai.keypool import KeyPool, get_key_pool
from forliosa.ai.pricing import CallUsage
from forliosa.ai.prompts import (
    ANALYST_DISCLAIMER,
    ANALYST_LS_SYSTEM,
    ANALYST_NUDGE,
    ANALYST_SYSTEM,
    ANALYST_TOOL,
    ANALYST_TOOL_NAME,
    analyst_ls_question,
    analyst_question,
)
from forliosa.ai.tools import (
    SEARCH_BLOCKED_DOMAINS,
    Citable,
    block_search,
    citable_content,
    exclude_tool,
    rejected_tool,
    server_tools,
)
from forliosa.api.errors import ApiError, not_found
from forliosa.config import Settings, get_settings
from forliosa.db import session_factory
from forliosa.ids import new_id
from forliosa.marketdata.base import InstrumentInfo
from forliosa.marketdata.service import MarketData
from forliosa.models import AiAnalystViews, MarketEvent, SecTicker, User
from forliosa.news import langsearch
from forliosa.news.outlets import is_not_news
from forliosa.services.announcements import classify
from forliosa.timeutil import TAIPEI, iso_taipei, last_tw_trading_day, next_tw_trading_day, now_utc

log = logging.getLogger(__name__)

# Product owner 2026-11-16 (the analyst / news memo, decisions 2–5): up to 8 items (2330 had 7 verified, 2 were cut
# at 5); reports up to 180 days old, those older than 90 days labelled 舊資料 and listed after the newer ones; an
# unnamed foreign broker (「日系外資」) shown as 「未具名外資（日系）」, at most 2 and only within 30 days; an empty
# result kept 3 trading days unless a new 法說會 / financial-report notice appears.
MAX_ITEMS = 8
MAX_AGE_DAYS = 180
RECENT_DAYS = 90
UNNAMED_MAX = 2
UNNAMED_MAX_AGE_DAYS = 30
# An unnamed broker with a named one's target price within this many days is that report retold (2026-11-16, 台達電:
# 「美系外資」 維持「建議加碼」 2,300 on 11/10 beside 大摩 「優於大盤」 2,300 on 11/11): left out, not folded into it.
ECHO_DAYS = 7
EMPTY_KEEP_TRADING_DAYS = 3
# An empty result is only kept that long for a stock no result shows a rating headline of in the last year: a stock
# with one (家登, 2026-11-16: a May report, and an empty search where another found UBS's 710) gets a new search on
# the next trading day, since the search results vary (2026-11-16 re-measure: 家登 empty twice, 2 items once).
COVERED_DAYS = 365
NOTICE_LOOKBACK_DAYS = 60  # how far back the material information is read for new_notice
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
# as TWD for 2330.TW is about 0.16 × the TWD price per 1× upside, 2412's 10-share CHT ADR about 0.32 ×). On a
# Taiwan stock the mix-up only shows on the low side; the upper bound was 3 × until a real target after a price fall
# was dropped (2026-11-16: Goldman's NT$4,120 for 2308 at NT$1,240, 3.3 ×). On a US-listed ADR of a Taiwan company
# it shows on the high side (a TWD target reported as USD: CHT at US$40 with NT$145 is 3.6 ×, TSM at US$300 with
# NT$1,750 is 5.8 ×), so US stocks keep 3 × (2026-11-16 review).
TARGET_RATIO_MIN = 0.4
TARGET_RATIO_MAX = 6.0
TARGET_RATIO_MAX_US = 3.0
# Drops that do not show there is nothing to report (a mangled URL, a result without a readable date): when nothing
# is kept and a candidate was dropped for one of these, the entry is ``unavailable`` (retried later), never an
# empty ``ready``.
UNSURE_DROPS = frozenset({"url_not_in_results", "date_unverified"})
# Not articles: rating aggregators (their rating data is their licensed product, docs/research/analyst-ratings.md),
# quote and data pages, AI-written pages, forums. ``AGGREGATOR_HOSTS`` (and subdomains;
# ``tools.SEARCH_BLOCKED_DOMAINS``, shared with chat) are blocked in the search tool and dropped by ``verify``;
# ``QUOTE_PATHS`` (host and subdomains → path prefixes) and the rating-page path words are dropped by ``verify``.
AGGREGATOR_HOSTS = SEARCH_BLOCKED_DOMAINS
QUOTE_PATHS: dict[str, tuple[str, ...]] = {
    "tw.stock.yahoo.com": ("/quote",), "finance.yahoo.com": ("/quote",), "cnyes.com": ("/twstock", "/usstock"),
    "invest.cnyes.com": ("/",), "money.cnn.com": ("/quote",), "wsj.com": ("/market-data",),
    "marketwatch.com": ("/investing/",), "nasdaq.com": ("/market-activity/",), "investing.com": ("/equities/",),
    "pchome.megatime.com.tw": ("/stock",),  # its /news pages are real reprints
}
# Reputable outlets (the memo's §2.5): preferred, never required — a strict allow-list would leave small caps with
# even less. The prompt asks for them first; ``verify`` keeps their article when one institution's report of the
# same day comes from several outlets.
PREFERRED_HOSTS = ("money.udn.com", "ctee.com.tw", "moneydj.com", "cnyes.com", "cna.com.tw", "ltn.com.tw",
                   "reuters.com", "cnbc.com")
# The 法說會 list of 公開資訊觀測站 (法人說明會一覽表): linked, never fetched (decision 6; TWSE's site terms forbid
# automated downloads, and the slides are the company's copyright).
MOPS_CONFERENCE_URL = "https://mops.twse.com.tw/mops/#/web/t100sb07_1"
# A path segment like these is a rating / forecast page, unless the URL carries an article date.
RATING_PAGE_SEGMENTS = frozenset({"quote", "quotes", "analyst-ratings", "analyst-research", "analyst-insights",
                                  "analystestimates", "analyst-estimates", "estimates", "research-ratings", "forecast",
                                  "forecasts", "price-target", "price-targets", "consensus"})
RATING_PAGE_SUFFIXES = ("-consensus-estimates", "-stock-forecast", "-price-target", "-price-targets",
                        "-analyst-ratings", "-analyst-estimates")
NOTE_OFF = "現在查不到法人觀點。"
# LangSearch first (``from_langsearch``): how many kept articles the extraction reads (one excerpt often names several
# brokers: 2026-11-17 Part A, up to 12 in one), how many named institutions make the card (fewer → web search), and the
# extraction call's output cap (12 items of the strict tool) and effort.
LS_ARTICLES = 12
LS_MIN_NAMED = 2
LS_MAX_TOKENS = 6000
LS_EFFORT = "low"
LS_MAX_CALLS = 2  # the call + one nudge


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    page_age: str | None


@dataclass(frozen=True)
class Dropped:
    candidate: dict[str, Any]
    reason: str  # url_not_in_results | not_article | date_unverified | too_old | future | unnamed | unnamed_old
    #              | empty | currency | duplicate | limit  (``currency`` also covers a target outside
    #              TARGET_RATIO_MIN–MAX × the last price; ``limit``: past MAX_ITEMS or UNNAMED_MAX)


@dataclass(frozen=True)
class Hints:
    """What the search can start from (the memo's §2.4): the English short name, the latest 法說會 held (date and
    the broker hosting it) and the company's full name (「円星科技」 for M31), from data Forliosa already has.
    ``brand``: a US company's first word when it names it alone (``us_brand``: 「palantir」)."""
    english: str | None = None
    conference: date | None = None
    host: str | None = None
    full_name: str | None = None
    brand: str | None = None


# -- time and cache --------------------------------------------------------------------------------------------
def trading_day(now: datetime) -> date:
    """The cache key: the last Taiwan trading day on or before ``now`` (Taipei)."""
    return last_tw_trading_day(now.astimezone(TAIPEI).date())


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def purge_expired(db: Session, now: datetime | None = None) -> int:
    """Delete entries past ``expires_at`` (24 h after creation; a kept empty one: ``keep_until``). Returns how many
    were deleted."""
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


def keep_until(day: date) -> datetime:
    """When an empty ``ready`` entry of trading day ``day`` expires: 00:00 Taipei of the trading day
    ``EMPTY_KEEP_TRADING_DAYS`` trading days later (searched on Monday: kept through Wednesday)."""
    d = day
    for _ in range(EMPTY_KEEP_TRADING_DAYS):
        d = next_tw_trading_day(d + timedelta(days=1))
    return datetime.combine(d, time.min, TAIPEI)


def _conferences(db: Session, symbol: str, since: date) -> list[tuple[date, str | None, MarketEvent]]:
    """Archived 法說會 notices (重大訊息 第12款) of ``symbol`` announced on or after ``since``: (conference date, the
    host broker when the company was invited, row)."""
    out = []
    for r in db.scalars(select(MarketEvent).where(MarketEvent.symbol == symbol, MarketEvent.type == "material_info",
                                                  MarketEvent.date >= since)):
        rel = classify(r.title, r.detail, r.data, r.date)
        if rel is not None and rel.kind == "investor_conference":
            out.append((rel.date, conference_host(r.title), r))
    return out


def new_notice(db: Session, symbol: str, since: datetime, today: date) -> bool:
    """A reason to search again after an empty result of ``since``: a 法說會 or financial-report notice of
    ``symbol`` archived after it (and announced no earlier than the day before), or a 法說會 held since (reports
    cluster around both)."""
    since_day = since.astimezone(TAIPEI).date()
    lo = since_day - timedelta(days=NOTICE_LOOKBACK_DAYS)
    for r in db.scalars(select(MarketEvent).where(MarketEvent.symbol == symbol, MarketEvent.type == "material_info",
                                                  MarketEvent.date >= lo)):
        rel = classify(r.title, r.detail, r.data, r.date)
        if rel is None or rel.kind not in ("investor_conference", "earnings"):
            continue
        created = _aware(r.created_at)
        if created is not None and created > since and r.date >= since_day - timedelta(days=1):
            return True
        if rel.kind == "investor_conference" and since_day <= rel.date < today:
            return True
    return False


def kept_empty(db: Session, symbol: str, now: datetime) -> AiAnalystViews | None:
    """The empty ``ready`` entry of an earlier trading day that still stands for today (``keep_until``, no
    ``new_notice`` since it was searched), or ``None``. Read only."""
    row = db.scalars(select(AiAnalystViews).where(
        AiAnalystViews.symbol == symbol, AiAnalystViews.trading_day < trading_day(now),
        AiAnalystViews.status == "ready", AiAnalystViews.expires_at > now,
    ).order_by(AiAnalystViews.trading_day.desc()).limit(1)).first()
    finished = _aware(row.finished_at) if row is not None else None
    if row is None or row.items or finished is None:
        return None
    # only one kept past its day (``keep_until``): an empty result of a stock rated in the last year
    # (``Outcome.covered``) has the usual 24 hours, and the next trading day searches again (2026-11-16 review: it
    # stood in for the next day until 24 hours after it was made)
    if (_aware(row.expires_at) or now) <= finished + TTL:
        return None
    if new_notice(db, symbol, finished, now.astimezone(TAIPEI).date()):
        return None
    return row


_HOST_PATTERNS = (
    # 受邀參加永豐金證券匯立分公司舉辦之法人說明會, 12/16參加康和證券舉辦之線上法說會
    re.compile(r"參加\s*(?:由\s*)?(.+?)\s*所?(?:舉辦|主辦)"),
    re.compile(r"[受應]\s*(?!邀)(.+?)\s*(?:之\s*)?邀請"),  # 受國票綜合證券邀請召開法人說明會, 應凱基證券之邀請
    re.compile(r"受邀參加\s*(.+?)\s*$"),  # 受邀參加Daiwa Investment Conference Singapore 2026
)


def conference_host(title: str) -> str | None:
    """Who hosts a 法說會 the company was invited to, from the notice's title (「永豐金證券匯立分公司」,
    「Daiwa Investment Conference Singapore 2026」); ``None`` for the company's own (「公告本公司召開法人說明會」)."""
    for p in _HOST_PATTERNS:
        m = p.search(title or "")
        if m:
            host = m.group(1).strip(" 「」『』\"'")
            if host and len(host) <= 60 and not re.search(r"說明會|法說|本公司", host):
                return host
    return None


def conference_info(db: Session, info: InstrumentInfo, today: date) -> dict[str, Any] | None:
    """Official 法說會 context for the card (links only, nothing fetched): the latest 法說會 held in the last
    ``MAX_AGE_DAYS`` and the next one within 30 days, from the archived notices, and the link to the MOPS list.
    ``None`` for US stocks."""
    if info.market == "US":
        return None
    found = _conferences(db, info.symbol, today - timedelta(days=MAX_AGE_DAYS))
    held = [c for c in found if today - timedelta(days=MAX_AGE_DAYS) <= c[0] <= today]
    ahead = [c for c in found if today < c[0] <= today + timedelta(days=30)]
    last = max(held, key=lambda c: c[0]) if held else None
    nxt = min(ahead, key=lambda c: c[0]) if ahead else None
    return {"last": {"date": last[0].isoformat(), "host": last[1]} if last else None,
            "next": {"date": nxt[0].isoformat(), "host": nxt[1]} if nxt else None,
            "url": MOPS_CONFERENCE_URL}


def full_name(db: Session, info: InstrumentInfo) -> str | None:
    """The company's name from the archived profile without 「股份有限公司」 (「円星科技」 for M31), when it is not
    the stock's short name."""
    from forliosa.models import CompanyProfile

    if info.market == "US":
        return None
    prof = db.get(CompanyProfile, info.symbol)
    name = str((prof.values or {}).get("name") or "") if prof is not None else ""
    name = re.sub(r"(?:股份)?有限公司$", "", "".join(name.split()))
    return name if name and name != info.name else None


# words that lead rating headlines and searches about other stocks: a US company whose SEC name starts with one is
# not known by it alone (T. Rowe Price is 「PRICE T ROWE GROUP INC」; Jefferies, Raymond James… rate other stocks)
_NOT_A_BRAND = frozenset({
    "price", "target", "stock", "stocks", "market", "news", "hold", "group", "outlook", "first", "analyst", "rating",
    "jefferies", "raymond", "piper", "stifel", "mizuho", "nomura", "truist", "oppenheimer", "wells", "hsbc", "loop",
    "northland", "daiwa", "baird", "kepler", "benchmark", "needham", "wedbush", "cowen", "cantor", "guggenheim",
    "barclays", "goldman", "morgan", "deutsche", "bernstein", "macquarie", "citizens", "susquehanna", "rosenblatt"})


def _first_word(name: str) -> str:
    m = re.match(r"[a-z]+", name.strip().casefold())
    return m.group(0) if m else ""


def us_brand(db: Session, info: InstrumentInfo) -> str | None:
    """A US company's first word, when it names it alone: SEC's 「Palantir Technologies Inc.」 and 「AMAZON COM INC」
    are 「Palantir」 and 「Amazon」 in headlines and searches (2026-11-16 review: 「Palantir analyst price target」 was
    taken for a search about another stock, and the empty result was never a 「查無」). Only a word of 4 or more
    letters that no other SEC company's name starts with (by CIK: 「Taiwan」 is also Taiwan Semiconductor's,
    「Goldman」 Goldman Sachs's, 「Apple」 Apple's for Apple Hospitality REIT) and that is not in ``_NOT_A_BRAND``
    (round 2 of the review: 「Taiwan Semiconductor price target raised」 was taken for a rating of The Taiwan Fund,
    whose empty result then never was 「查無」)."""
    words = _CORPORATE_SUFFIX.sub("", (info.name or "").strip()).casefold().split()
    word = words[0] if info.market == "US" and len(words) > 1 else ""
    if len(word) < 4 or not (word.isascii() and word.isalpha()) or word in _NOT_A_BRAND:
        return None
    rows = db.execute(select(SecTicker.cik, SecTicker.title).where(func.lower(SecTicker.title).like(f"{word}%")))
    return word if len({cik for cik, title in rows if _first_word(title or "") == word}) <= 1 else None


def query_hints(db: Session, info: InstrumentInfo, today: date) -> Hints:
    """``Hints`` for the search: the English short name (``news.service.english_names``), the latest 法說會 held
    in the last 60 days, the company's full name and a US company's brand (``us_brand``). Best effort: missing
    data gives empty hints."""
    from forliosa.news.service import english_names

    try:
        english = next((n for n in english_names(db, info) if n.casefold() != info.name.casefold()), None)
        held = [c for c in _conferences(db, info.symbol, today - timedelta(days=NOTICE_LOOKBACK_DAYS))
                if c[0] <= today] if info.market != "US" else []
        company = full_name(db, info)
        brand = us_brand(db, info)
    except Exception:  # hints only steer the search
        log.warning("analyst views: no query hints for %s", info.symbol, exc_info=True)
        return Hints()
    last = max(held, key=lambda c: c[0]) if held else None
    return Hints(english, last[0] if last else None, last[1] if last else None, company, brand)


def _current(db: Session, symbol: str, now: datetime) -> AiAnalystViews | None:
    purge_expired(db, now)
    row = db.get(AiAnalystViews, (symbol, trading_day(now)))
    if row is None:
        return kept_empty(db, symbol, now)
    if row.status == "pending" and now - _aware(row.created_at) > PENDING_TIMEOUT:
        log.warning("analyst views for %s: generation %s never finished; marked unavailable", symbol,
                    row.generation_id)
        row.status, row.notes, row.finished_at = "unavailable", [], now
        db.commit()
    return row


def _retry_open(row: AiAnalystViews, now: datetime) -> bool:
    """An ``unavailable`` entry may be searched again ``UNAVAILABLE_RETRY_AFTER`` after it failed."""
    finished = _aware(row.finished_at) or now
    return row.status == "unavailable" and now - finished >= UNAVAILABLE_RETRY_AFTER


def _item(item: dict[str, Any]) -> dict[str, Any]:
    """A stored item in the contract shape (entries stored before 2026-11-16 have no ``unnamed`` / ``old``)."""
    return {**item, "unnamed": bool(item.get("unnamed")), "old": bool(item.get("old"))}


def view(row: AiAnalystViews | None, symbol: str, conference: dict[str, Any] | None = None) -> dict[str, Any]:
    """The contract shape (``docs/api-contract.md`` 法人觀點). ``conference``: ``conference_info`` (``None`` when
    not looked up: US stocks and the chat tool)."""
    if row is None:
        return {"status": "none", "symbol": symbol, "as_of": None, "expires_at": None, "items": [],
                "disclaimer": ANALYST_DISCLAIMER, "notes": [], "conference": conference}
    ready = row.status == "ready"
    finished = _aware(row.finished_at)
    notes = list(row.notes or [])
    if row.status == "unavailable" and finished:
        notes.append(f"{(finished + UNAVAILABLE_RETRY_AFTER).astimezone(TAIPEI):%H:%M} 之後可以再查一次。")
    return {"status": row.status, "symbol": row.symbol,
            "as_of": iso_taipei(finished) if ready and finished else None,
            "expires_at": iso_taipei(_aware(row.expires_at)),
            "items": [_item(i) for i in row.items or []] if ready else [],
            "disclaimer": ANALYST_DISCLAIMER, "notes": notes, "conference": conference}


def _conference(db: Session, info: InstrumentInfo, now: datetime) -> dict[str, Any] | None:
    try:
        return conference_info(db, info, now.astimezone(TAIPEI).date())
    except Exception:  # official links are a nicety: never fail the card for them
        log.warning("analyst views: no 法說會 info for %s", info.symbol, exc_info=True)
        db.rollback()
        return None


def read(db: Session, md: MarketData, symbol: str, now: datetime | None = None) -> dict[str, Any]:
    """``GET``: today's shared entry (or a kept empty one, ``kept_empty``), or ``status: none`` (also once a failed
    search may be retried, so the page offers the search again)."""
    info = resolve_stock(md, symbol)
    now = now or now_utc()
    row = _current(db, info.symbol, now)
    return view(None if row is not None and _retry_open(row, now) else row, info.symbol,
                _conference(db, info, now))


def cached(db: Session, symbol: str, now: datetime | None = None) -> dict[str, Any]:
    """Today's shared entry of a resolved stock symbol (or a kept empty one), for the chat tool
    ``get_analyst_views``: like ``read`` but without writing anything (no purge, no generation, no charge), since
    chat tools run side by side on sessions of their own. An expired entry reads as ``none``; a ``pending`` one past
    ``PENDING_TIMEOUT`` as ``unavailable``."""
    now = now or now_utc()
    row = db.get(AiAnalystViews, (symbol, trading_day(now))) or kept_empty(db, symbol, now)
    if row is None or (_aware(row.expires_at) or now) <= now:
        return view(None, symbol)
    out = view(row, symbol)
    if row.status == "pending" and now - _aware(row.created_at) > PENDING_TIMEOUT:
        out["status"] = "unavailable"
    return out


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
    conf = _conference(db, info, now)
    if row is not None and not _retry_open(row, now):  # pending, ready, or failed moments ago: shared, no charge
        return view(row, info.symbol, conf), None
    if not settings.ai_analyst_enabled or not settings.ai_web_search or not server_tools(settings, fetch=False):
        return {**view(None, info.symbol, conf), "status": "unavailable", "notes": [NOTE_OFF]}, None
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
                return view(db.get(AiAnalystViews, (info.symbol, day)), info.symbol, conf), None
    except IntegrityError:  # another request created today's entry first: share it
        db.rollback()
        return view(db.get(AiAnalystViews, (info.symbol, day)), info.symbol, conf), None
    # The search counts as one question right away (its model calls add their tokens later).
    store.record_usage(db, user_id=user.id, thread_id=gen, feature="analyst", model=fields["model"], key_slot=None,
                       usage=CallUsage(), stop_reason="started")
    db.expire_all()
    out = view(db.get(AiAnalystViews, (info.symbol, day)), info.symbol, conf)
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


def search_errors(content: list[Any]) -> list[str]:
    """The error codes of the web searches that failed (``web_search_tool_result_error``: too_many_requests,
    unavailable…), except ``max_uses_exceeded`` (the searches allowed were made)."""
    out = []
    for b in content:
        err = _get(b, "content") if _get(b, "type") == "web_search_tool_result" else None
        if err is not None and not isinstance(err, list) and _get(err, "type") == "web_search_tool_result_error":
            code = str(_get(err, "error_code") or "unknown")
            if code != "max_uses_exceeded":
                out.append(code)
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


def stock_terms(info: InstrumentInfo, brand: str | None = None) -> list[str]:
    """Words that show a headline is about this stock: its name, code, ticker and aliases (台積電, 2330, TSMC;
    NVIDIA, NVDA, 輝達), case-folded, corporate suffixes removed, and ``brand`` (``us_brand``: 「palantir」)."""
    terms: set[str] = {brand} if brand else set()
    for t in (info.name, info.code, info.symbol.split(".")[0], *info.aliases):
        t = _CORPORATE_SUFFIX.sub("", (t or "").strip()).casefold()
        if len(t) >= 2:
            terms.add(t)
    return sorted(terms)


def query_terms(info: InstrumentInfo, hints: Hints) -> list[str]:
    """``stock_terms`` with the hints' English and full names, and the first two characters of a Chinese name
    (「円星」 for 円星科技, 「禾榮」 for 禾榮科): a search that has none of them is not about this stock (2026-11-16:
    all three searches of an M31 card were for 晶心科)."""
    terms = set(stock_terms(info, hints.brand))
    for t in (hints.english, hints.full_name):
        t = _CORPORATE_SUFFIX.sub("", (t or "").strip()).casefold()
        if len(t) >= 2:
            terms.add(t)
    terms |= {t[:2] for t in terms if not t.isascii() and len(t) >= 3}
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


def rating_headlines(results: list[SearchResult], info: InstrumentInfo, today: date,
                     explained: frozenset[str] = frozenset(), max_age_days: int = MAX_AGE_DAYS,
                     brand: str | None = None) -> int:
    """How many article results have a rating / target-price headline about *this* stock (its name, code, ticker
    or alias in the title) that is not verifiably older than ``MAX_AGE_DAYS`` — the check that keeps an empty
    report from being shown as "nothing found". Other stocks' ratings, credit ratings and aggregator pages do
    not count, nor do the articles in ``explained`` (normalized URLs of candidates ``verify`` dropped for what they
    are: an unnamed broker older than 30 days, another currency…). ``max_age_days``: ``COVERED_DAYS`` to tell
    whether anyone rated the stock in the last year. ``brand``: ``Hints.brand``."""
    terms = stock_terms(info, brand)
    oldest = today - timedelta(days=max_age_days)
    n = 0
    for r in results:
        title = r.title or ""
        if not (is_article(r.url) and _RATING_HEADLINE.search(title) and not _CREDIT_RATING.search(title)
                and _mentions(title, terms)) or _norm_url(r.url) in explained:
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
    #                            | search_error | off_target
    covered: bool = False  # empty, but a result has a rating headline of it within COVERED_DAYS: not kept longer
    source: str = "web_search"  # web_search | langsearch (``from_langsearch``)


def search_tools(settings: Settings) -> list[dict[str, Any]]:
    """``web_search`` (no ``web_fetch``) with ``AGGREGATOR_HOSTS`` blocked, unless an allow-list is configured
    (the API takes one or the other)."""
    return block_search(server_tools(settings, fetch=False, max_uses=settings.ai_analyst_search_max_uses))


def run_model(info: InstrumentInfo, today: date, generation_id: str, pool: KeyPool, settings: Settings,
              record: Callable[[int, Any], None], costs: Any = None, thinking_display: str | None = None,
              reference: float | None = None, hints: Hints | None = None) -> Outcome:
    """Ask the model (web search + ``report_analyst_views``), then verify. ``record(slot, message)`` stores the
    usage of every call. Raises on API errors (the caller marks the entry unavailable). ``reference`` is the last
    real price, only for ``verify``'s internal currency check; ``hints`` (``query_hints``) go into the question.
    ``thinking_display`` (``"summarized"``) is only for the live smoke's diagnostics.

    "Nothing found" (``ready`` with no items) is only claimed when nothing points the other way: if no item
    survives while the search results carry a rating headline about this stock (``rating_headlines``), or while a
    candidate was dropped for a reason that does not show there is nothing (``UNSURE_DROPS``: a URL that is not
    one of the results, a result without a readable date), while a search failed (``search_errors``) or while a
    search was for another stock (``query_terms``), the outcome is ``unavailable`` (retried after
    ``UNAVAILABLE_RETRY_AFTER``)."""
    model = store.model_for("analyst", settings)
    since = today - timedelta(days=MAX_AGE_DAYS)
    hints = hints or Hints()
    messages: list[dict[str, Any]] = [{"role": "user", "content": analyst_question(
        info.name, info.symbol, info.market, info.currency, today.isoformat(), since.isoformat(),
        english=hints.english, conference=hints.conference.isoformat() if hints.conference else None,
        host=hints.host, full_name=hints.full_name)}]
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
    covered = False
    if not items:
        explained = frozenset(_norm_url(str(d.candidate.get("url") or "")) for d in dropped
                              if d.reason not in UNSURE_DROPS)
        headlines = rating_headlines(results, info, today, explained, brand=hints.brand)
        unsure = any(d.reason in UNSURE_DROPS for d in dropped)
        terms = query_terms(info, hints)
        off_target = [q for q in queries if not _mentions(q, terms)]
        failed = search_errors(content)
        if headlines or unsure or off_target or failed:
            # Do not claim there are no reports: "unavailable" (retried later) instead of an empty "ready".
            log.warning("analyst views %s for %s: nothing kept of %d candidates (dropped: %s; %d results have "
                        "rating headlines about it; %d searches without its name; failed searches: %s)",
                        generation_id, info.symbol, len(reported), ", ".join(d.reason for d in dropped) or "none",
                        headlines, len(off_target), ", ".join(failed) or "none")
            return Outcome("unavailable", [], dropped, reported, results, usage, calls, queries, stop, transcript,
                           "empty_despite_headlines" if headlines else "unverified" if unsure
                           else "search_error" if failed else "off_target")
        covered = rating_headlines(results, info, today, max_age_days=COVERED_DAYS, brand=hints.brand) > 0
    return Outcome("ready", items, dropped, reported, results, usage, calls, queries, stop, transcript,
                   covered=covered)


def from_langsearch(db: Session, md: MarketData, info: InstrumentInfo, today: date, generation_id: str,
                    pool: KeyPool, settings: Settings, record: Callable[[int, Any], None], costs: Any = None,
                    reference: float | None = None, now: datetime | None = None) -> Outcome | None:
    """The card from LangSearch (see the module docstring), or ``None`` for the web search: LangSearch could not be
    asked (off, stopped, over the AI's daily cap), kept nothing, the extraction call failed or reported nothing, or
    fewer than ``LS_MIN_NAMED`` named institutions survived ``verify``. Best effort: never raises. The excerpts go into
    this one request only; nothing of them is logged or returned (the outcome's results are titles, links and dates)."""
    now = now or now_utc()
    try:
        tier = tw_news.tier_for(db, md, info, settings)
        p = tw_news.plan("analyst_targets", info, tier, 0, now)
    except ValueError:  # a name LangSearch cannot be asked with (digits only)
        p = None
    except Exception:
        log.warning("analyst views %s for %s: no LangSearch plan", generation_id, info.symbol, exc_info=True)
        db.rollback()
        p = None
    if p is None:
        return None
    p = replace(p, limit=LS_ARTICLES)
    try:
        found = tw_news.fetch(db, md, settings, p, info, now=now, label="analyst card")
    except langsearch.ChatUnavailable as exc:
        log.info("analyst views %s for %s: LangSearch not asked (%s); web search", generation_id, info.symbol,
                 exc.reason)
        return None
    except Exception as exc:  # LangSearch is a first try: the web search stays
        log.warning("analyst views %s for %s: LangSearch failed (%s); web search", generation_id, info.symbol,
                    type(exc).__name__)
        db.rollback()
        return None
    if not found.items:
        log.info("analyst views %s for %s: LangSearch kept nothing (%s); web search", generation_id, info.symbol,
                 found.status)
        return None
    results = [SearchResult(x.url, x.title, x.date.astimezone(TAIPEI).date().isoformat()) for x in found.items]
    question = analyst_ls_question(info.name, info.symbol, info.market, today.isoformat())
    messages: list[dict[str, Any]] = [{"role": "user", "content": [
        *citable_content(Citable(tw_news.blocks(found.items, today))), {"type": "text", "text": question}]}]
    params: dict[str, Any] = {"model": settings.ai_model.strip(), "max_tokens": LS_MAX_TOKENS,
                              "system": ANALYST_LS_SYSTEM, "tools": [ANALYST_TOOL],
                              "output_config": {"effort": LS_EFFORT}}
    content: list[Any] = []
    usage = CallUsage()
    slot: int | None = None
    calls = 0
    reported: list[dict[str, Any]] | None = None
    stop: str | None = None

    def ask(m: list[dict[str, Any]]) -> Callable[[Any], Any]:
        return lambda client: client.messages.with_raw_response.create(messages=m, **params)

    try:
        while calls < LS_MAX_CALLS:
            raw, slot = pool.call(ask(messages), costs=costs if slot is None else None, only=slot)
            calls += 1
            pool.observe(slot, raw.headers)
            msg = raw.parse()
            record(slot, msg)
            usage.add(CallUsage.from_sdk(msg.usage))
            content.extend(msg.content)
            stop = msg.stop_reason
            reported = reported_items(msg.content)
            if reported is not None or stop not in ("end_turn", "stop_sequence"):
                break
            # ended with text only: ask once for the tool call
            messages = [*messages, {"role": "assistant", "content": [b.to_dict(mode="json") for b in msg.content]},
                        {"role": "user", "content": ANALYST_NUDGE}]
    except Exception as exc:  # the web search stays (its own call reports its own failure)
        log.warning("analyst views %s for %s: the LangSearch extraction failed (%s); web search", generation_id,
                    info.symbol, type(exc).__name__)
        db.rollback()
        return None
    if reported is None or stop in ("refusal", "max_tokens"):
        log.info("analyst views %s for %s: no LangSearch report (stop=%s); web search", generation_id, info.symbol,
                 stop)
        return None
    items, dropped = verify(reported, results, info, today, reference)
    named = {institution_key(i["institution"]) for i in items if not i["unnamed"]}
    if len(named) < LS_MIN_NAMED:
        log.info("analyst views %s for %s: LangSearch gave %d named institutions of %d articles (dropped: %s); web "
                 "search", generation_id, info.symbol, len(named), len(found.items),
                 ", ".join(d.reason for d in dropped) or "none")
        return None
    return Outcome("ready", items, dropped, reported, results, usage, calls, list(p.queries), stop,
                   _transcript(content), source="langsearch")


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

    now = now_utc()
    today = now.astimezone(TAIPEI).date()
    covered = False
    used: dict[str, Any] = {}  # the extraction model, when the card came from LangSearch
    try:
        reference = reference_price(md, info.symbol)
        outcome = None
        if tw_news.usable_for(settings, info):  # LangSearch first; None: the web search, as before
            outcome = from_langsearch(db, md, info, today, generation_id, pool, settings, record,
                                      store.slot_month_costs(db), reference=reference, now=now)
        if outcome is None:
            outcome = run_model(info, today, generation_id, pool, settings, record, store.slot_month_costs(db),
                                reference=reference, hints=query_hints(db, info, today))
        else:
            used = {"model": settings.ai_model.strip()}
        status, items, notes, covered = outcome.status, outcome.items, [], outcome.covered
        if outcome.dropped:
            log.info("analyst views %s for %s: %s from %s, kept %d, dropped %s", generation_id, info.symbol, status,
                     outcome.source, len(items), ", ".join(d.reason for d in outcome.dropped))
    except Exception:
        log.exception("analyst views generation %s for %s failed", generation_id, info.symbol)
        db.rollback()
        status, items, notes = "unavailable", [], []
    # nothing found (in practice a small cap): kept for EMPTY_KEEP_TRADING_DAYS trading days (``kept_empty``),
    # unless a result shows it was rated in the last year (``Outcome.covered``)
    keep = {"expires_at": keep_until(day)} if status == "ready" and not items and not covered else {}
    db.execute(update(AiAnalystViews).where(
        AiAnalystViews.symbol == info.symbol, AiAnalystViews.trading_day == day,
        AiAnalystViews.generation_id == generation_id).values(
        status=status, items=items, notes=notes, finished_at=now_utc(), **keep, **used))
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
    if is_not_news(url):  # the news side's quote / forum / AI-page paths (money-link's /TWStock, …)
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
    r"金控|龍頭|旗下|老牌|一線|"  # 「金控龍頭旗下投顧」 (live 2026-11-16, 家登): describes a firm, does not name it
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


# A foreign broker named only by its region (「日系外資」「美系券商」「港資券商」), or not at all (「外資」
# 「某外資」「外資券商 A」「外資分析師」), compared like ``_norm_name``. 「券商」「投行」 alone may be domestic:
# not matched.
_UNNAMED_FOREIGN = re.compile(r"(?:某一?家?|一家|另一?家|一位)?"
                              r"(?:(?P<region>[美日歐英德法瑞港陸中韓星亞澳])(?P<kind>系|資))?"
                              r"(?P<noun>外資券商|外資法人|外資機構|外資|外商券商|外商|券商|投資銀行|投行)"
                              r"(?:分析師|研究員)?")


def unnamed_label(name: str) -> str | None:
    """「未具名外資（日系）」 for a foreign broker a report names only by region (「日系外資」「美系券商 C」),
    「未具名外資」 for 「外資」「某外資」「外資券商 A」; ``None`` for anything else (a named institution, 「法人」
    「國內投顧」「分析師」, 「Wall Street analysts」). 「美系外資（摩根士丹利）」 names one: check ``institution_key``
    first."""
    m = _PAREN.match(name.strip())
    for part in (m.group(1), m.group(2)) if m else (name,):
        s = _norm_name(re.sub(r"(?:\s+|(?<=[\u4e00-\u9fff]))[A-Za-z0-9]{1,2}$", "", part.strip()))
        u = _UNNAMED_FOREIGN.fullmatch(s)
        if u is None or (u.group("region") is None and "外" not in u.group("noun")):
            continue
        return f"未具名外資（{u.group('region')}{u.group('kind')}）" if u.group("region") else "未具名外資"
    return None


def _preferred(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    return any(_on_host(host, h) for h in PREFERRED_HOSTS)


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
    contract shape and the dropped candidates. One per institution (aliases folded by ``institution_key``; on one
    day the article of a ``PREFERRED_HOSTS`` outlet first), at most ``MAX_ITEMS``: the named ones of the last
    ``RECENT_DAYS`` first, then at most ``UNNAMED_MAX`` unnamed foreign brokers (``unnamed_label``, at most
    ``UNNAMED_MAX_AGE_DAYS`` old; the same label, rating and target count once; one with a named report's target price
    within ``ECHO_DAYS`` is left out as that report retold), then older named ones (``old``).
    Shown newest first, the old ones last. ``reference`` (the last real price, optional) only drops a target price
    outside ``TARGET_RATIO_MIN``–``TARGET_RATIO_MAX`` times it as another currency; it is never shown or compared in
    the output (``TARGET_RATIO_MAX_US`` for a US stock)."""
    by_url: dict[str, SearchResult] = {}
    for r in results:
        by_url.setdefault(_norm_url(r.url), r)
    oldest = today - timedelta(days=MAX_AGE_DAYS)
    recent = today - timedelta(days=RECENT_DAYS)
    unnamed_since = today - timedelta(days=UNNAMED_MAX_AGE_DAYS)
    ratio_max = TARGET_RATIO_MAX_US if info.market == "US" else TARGET_RATIO_MAX
    named: list[tuple[str, dict[str, Any]]] = []
    unnamed: list[tuple[str, dict[str, Any]]] = []
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
        label = unnamed_label(institution) if institution and key is None else None
        if key is None and label is None:
            dropped.append(Dropped(c, "unnamed"))
            continue
        if label is not None and published < unnamed_since:
            dropped.append(Dropped(c, "unnamed_old"))
            continue
        rating = _text(c.get("rating_text"), MAX_RATING_CHARS)
        target = _price(c.get("target_price"))
        if target is not None and (c.get("currency") != info.currency or (
                reference and not TARGET_RATIO_MIN <= target / reference <= ratio_max)):
            dropped.append(Dropped(c, "currency"))  # e.g. the TSM ADR's USD target listed for 2330.TW
            continue
        if rating is None and target is None:
            dropped.append(Dropped(c, "empty"))
            continue
        action = c.get("action") if c.get("action") in ("調升", "調降", "維持", "首評") else ""
        entry = {"institution": label or institution, "action": action, "rating_text": rating,
                 "target_price": target, "currency": info.currency, "date": published.isoformat(),
                 "source_title": " ".join(result.title.split())[:MAX_TITLE_CHARS] or _norm_url(result.url),
                 "url": result.url, "unnamed": label is not None, "old": published < recent}
        if label is None:
            named.append((key or "", entry))
        else:  # the same story in several outlets counts once; never folded into a named institution
            unnamed.append((f"{label}|{rating}|{target}", entry))

    def one_each(kept: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
        # newest first, a preferred outlet first within a day (stable: else the model's order)
        kept.sort(key=lambda k: (k[1]["date"], _preferred(k[1]["url"])), reverse=True)
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for key, item in kept:
            if key in seen:
                dropped.append(Dropped(item, "duplicate"))
                continue
            seen.add(key)
            out.append(item)
        return out

    named_items, unnamed_items = one_each(named), one_each(unnamed)

    def echoes(u: dict[str, Any]) -> bool:  # the same target as a named report within ECHO_DAYS: most likely it
        d = date.fromisoformat(u["date"])
        return u["target_price"] is not None and any(
            n["target_price"] == u["target_price"] and abs((date.fromisoformat(n["date"]) - d).days) <= ECHO_DAYS
            for n in named_items)

    echoed = [u for u in unnamed_items if echoes(u)]
    dropped.extend(Dropped(u, "duplicate") for u in echoed)
    unnamed_items = [u for u in unnamed_items if u not in echoed]
    fresh = [i for i in named_items if not i["old"]][:MAX_ITEMS]
    room = MAX_ITEMS - len(fresh)
    anonymous = unnamed_items[:min(UNNAMED_MAX, room)]
    older = [i for i in named_items if i["old"]][:room - len(anonymous)]
    shown = {id(i) for i in (*fresh, *anonymous, *older)}
    dropped.extend(Dropped(i, "limit") for i in (*named_items, *unnamed_items) if id(i) not in shown)
    return sorted([*fresh, *anonymous], key=lambda i: i["date"], reverse=True) + older, dropped
