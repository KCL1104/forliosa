"""The gathering (contract §8): named media reports of what happened and what is scheduled, found by web search
(Claude Sonnet 5.5 at low effort, the report's allowed domains only, the repo's ``web_search_20260318`` without dynamic
filtering) — one call per topic with a quota the server sets, up to four topics at a time. A reply whose ``[KEY]``
paragraphs are mostly uncited gets one more turn asking for them again with citations (the better of the two answers
is kept).

Each reply is cut into facts (``[KEY] 〔媒體〕報導，…`` paragraphs with their citations) and every fact is checked
(:func:`verify`): the cited page was among this call's search results, on an allowed domain, a news article (not a
quote, index or data page), published inside the edition's window — every citation on its own (an undated page is
left out; a page dated only by day counts from the window's first day; on the cut-off's own day it is kept only when
the topic's searches ran inside the window and the window covers that whole day up to them, or when the page's
byline, a cited passage or its title gives its publish time inside the window (:func:`stamped`: a time written where
pages put one, never the time of a scheduled event) — the close edition's window starts the same morning; the fact's
source is the citation that holds its numbers) — the citation is a passage of the article (not a 「相關新聞」 list),
every number is in a fresh cited passage, a US / ADR / night-session fact names a US trading day the edition covers
(:attr:`Window.us_sessions`) and has percentages only, no index points, no ratings or target prices, no one's view of
where the market goes. What is kept becomes an X fact for the writer
(its ``quote`` stays on the server side: the API never returns it). When outlets disagree on a number of the same
key, one fixed outlet wins and the others are listed as a disagreement (:data:`OUTLET_PRIORITY`).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from itertools import pairwise
from typing import Any
from urllib.parse import urlsplit

from forliosa.ai.analyst import date_from_url, datetime_from_page_age, is_article, search_results
from forliosa.ai.market_summary import _norm_url
from forliosa.news.outlets import OUTLETS, host_of, on_domain, outlet_name
from forliosa.reports import calls
from forliosa.reports.prompts import CITE_AGAIN, GATHER_SYSTEM, LONG_HOLIDAY_EXTRA, TOPICS, key_allowed, topic_brief
from forliosa.reports.validate import FORECAST, OUTLOOK, VIEW, index_points, numbers
from forliosa.timeutil import TAIPEI, is_us_trading_day

log = logging.getLogger(__name__)

MAX_TOKENS = 8000
TIMEOUT = 300.0
MAX_CONTINUATIONS = 3
MAX_PER_TOPIC = 6
QUOTE_CHARS = 300
TOPIC_THREADS = 4
STOCK_REASON_MAX = 4
OUTLET_PRIORITY = ("中央社", "經濟日報", "工商時報", "鉅亨網", "MoneyDJ", "自由時報", "Focus Taiwan", "CNBC",
                   "Bloomberg")
NUMERIC_KEYS = ("TWSE_INST.", "TW.turnover_media", "NIGHT.tx_pct", "ADR.tsm")
SUBJECTS = {"TWSE_INST.foreign": "外資", "TWSE_INST.trust": "投信", "TWSE_INST.dealer": "自營商",
            "TWSE_INST.total": "三大法人", "NIGHT.tx_pct": "夜盤", "ADR.tsm": "台積電 ADR"}
LABELS = {"TWSE_INST.foreign": "上市外資買賣超", "TWSE_INST.trust": "上市投信買賣超",
          "TWSE_INST.dealer": "上市自營商買賣超", "TWSE_INST.total": "上市三大法人買賣超",
          "TW.turnover_media": "媒體報導的成交金額", "NIGHT.tx_pct": "台指期夜盤漲跌幅", "ADR.tsm": "台積電 ADR 漲跌幅"}
RATING = re.compile(r"目標價|評等|評級|調升至|調降至|調升.{0,8}評|調降.{0,8}評|優於大盤|劣於大盤|中立|加碼評|減碼評"
                    r"|outperform|underperform|overweight|underweight|price target", re.IGNORECASE)
# Keys whose facts may speak of what comes next (scheduled events, themes, company guidance): never with a direction
SCHEDULE_KEYS = ("EVENT.", "THEME.", "RISK.", "US.earnings.", "MACRO.", "CO.")
# Keys whose numbers are percentages only (US indices, the TAIEX futures' night session, the ADR: never points)
PERCENT_KEYS = ("US.", "NIGHT.", "ADR.")
INDEX_NAMES_WITH_DIGITS = ("S&P 500", "標普 500", "標普500", "標準普爾 500", "標準普爾500", "Nasdaq 100",
                           "那斯達克 100", "納斯達克 100", "羅素 2000", "Russell 2000", "道瓊 30")
US_DATE = re.compile(r"美股\s*(\d{1,2})/(\d{1,2})")
KEY_LINE = re.compile(r"^\s*\[([A-Za-z0-9_.\-]+)\]\s*(.+)$", re.DOTALL)
# A reading of the market quoted as if it were a fact (「短線利空出盡」): someone's view, never gathered
JUDGEMENT = re.compile(r"利空出盡|利多出盡|利空鈍化|利多鈍化|賣壓出盡|錯殺")
# Quote, index and data pages of the report's domains that ``analyst.is_article`` does not already know (it covers
# cnyes.com/twstock, invest.cnyes.com, cnbc.com/quotes, bloomberg.com/quote…): their numbers keep changing and their
# page_age is an update time, so they are never a source.
QUOTE_PAGE_PATHS = {"cnyes.com": ("/archive/twstock", "/archive/usstock"), "moneydj.com": ("/z/", "/etf/")}
# A publish time written in a cited passage or a title: 2026-11-17 15:32, 2026/11/17 15:32, 2026年11月17日 15:32,
# 115/11/17 15:32 (ROC year), 11/17 15:32
STAMP = re.compile(r"(?<!\d)(?:(\d{4}|1\d{2})\s*[-/.年]\s*)?(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?[\sT]*"
                   r"(\d{1,2})\s*[:：]\s*(\d{2})(?!\d)")
# A stamp is a publish time only where pages put one (:func:`publish_stamp`): right before the byline (an outlet,
# 記者, 報導, 「台北17日電」, 更新), right after a label (發布時間：), at the start of a passage or a line, or at the end
# of a title — and never next to the words of a scheduled event (「台積電訂 2026/11/17 14:00 召開法說會」「將於 11/17
# 13:30 結算」: an old preview names a time of the day it is about).
_OUTLET_WORDS = sorted({w for o in OUTLETS.values() for w in (o.name, *o.aliases) if len(w) >= 2}, key=len,
                       reverse=True)
BYLINE = re.compile(r"(?:記者(?!會)|(?:即時|綜合|特稿|專題)?報導|\d{1,2}日(?:專)?電|(?:最後)?更新|編輯|撰文|撰稿|作者|"
                    r"文\s*[／/]|" + "|".join(re.escape(w) for w in _OUTLET_WORDS) + ")", re.IGNORECASE)
PUBLISH_LABEL = re.compile(r"(?:發布|發佈|發稿|更新|刊出|刊登|出版|上稿)(?:時間|日期)?\s*[:：]?\s*$")
# a byline just before the stamp (「鉅亨網記者王小明 台北 2026/11/17 14:05」): the story may follow the stamp
BYLINE_BEFORE = re.compile(r"記者(?!會)|新聞中心|編譯|\d{1,2}日(?:專)?電|" + "|".join(re.escape(w) for w in _OUTLET_WORDS),
                           re.IGNORECASE)
EVENT_WORDS = re.compile(r"召開|舉行|舉辦|登場|公布|公佈|揭曉|結算|開盤|收盤|開市|收市|休市|將於|將在|訂於|訂在|預計|預定"
                         r"|排定|法說|說明會|記者會|會議|截止|演講|致詞|訂\s*$")
EVENT_AFTER = re.compile(r"^\s*(?:起|開始|前|止|為止|截止)")
_SEPARATORS = " \t\u3000|｜/／-–—·•,，:：()（）[]【】〔〕「」"
_STAMP_SPAN = 12  # characters around a stamp that tell what it is
# One more turn when at least this share of an answer's [KEY] paragraphs came without a citation
CITE_RETRY_SHARE = 0.5
CITE_RETRY_SEARCHES = 1


@dataclass
class Topic:
    name: str
    quota: int
    brief: str
    keys: tuple[str, ...]


@dataclass
class TopicResult:
    topic: Topic
    msgs: list[Any] = field(default_factory=list)  # every reply (continuations included), for booking
    slot: int | None = None
    error: str | None = None
    seconds: float = 0.0
    answers: list[int] = field(default_factory=lambda: [0])  # where each answer starts in msgs (a 2nd: the retry)
    replied_at: datetime | None = None  # the topic's last reply: none of its pages is newer (its ``Window.now``)


@dataclass
class Outcome:
    facts: list[dict[str, Any]]
    disagreements: list[dict[str, Any]]
    topics: list[dict[str, Any]]
    results: list[TopicResult]


# -- topics -------------------------------------------------------------------------------------------------------
def stock_reason_names(pack: dict[str, Any]) -> list[str]:
    """The listed stocks without a shared-research entry, by the size of their point contribution, then of their
    move (§8.2); at most four, as 「名稱（代號）」."""
    researched = {w["symbol"] for w in pack.get("research") or []}
    facts = {f["id"]: f for f in pack.get("facts") or []}

    def size(st: dict[str, Any]) -> tuple[float, float]:
        c = facts.get(st["facts"].get("contrib") or "", {}).get("value")
        p = facts.get(st["facts"].get("pct") or "", {}).get("value")
        return (-abs(c) if isinstance(c, (int, float)) else 0.0, -abs(p) if isinstance(p, (int, float)) else 0.0)

    cands = [s for s in pack.get("stocks") or [] if s["symbol"] not in researched
             and "對照基準" not in (s.get("lists") or [])]
    return [f"{s['name']}（{s['code']}）" for s in sorted(cands, key=size)[:STOCK_REASON_MAX]]


def us_sessions_of(pack: dict[str, Any]) -> list[str]:
    """The US sessions the edition covers (ISO dates): ``web_window.us_sessions`` is known even when no US close is
    stored; a pack built before it only has the sessions with stored closes (``dates.us_sessions``)."""
    w = pack.get("web_window") or {}
    if "us_sessions" in w:
        return list(w.get("us_sessions") or [])
    return list((pack.get("dates") or {}).get("us_sessions") or [])


def topics_for(kind: str, pack: dict[str, Any], *, long_holiday: bool = False) -> list[Topic]:
    w = pack.get("web_window") or {}
    window = (str(w.get("from") or ""), str(w.get("to") or ""))
    us = [f"{d[5:7].lstrip('0')}/{d[8:10].lstrip('0')}" for d in us_sessions_of(pack)]
    out = []
    for name, (quota, _what, keys) in TOPICS[kind].items():
        names: list[str] | None = None
        if name == "STOCK_REASONS":
            names = stock_reason_names(pack)
            if not names:
                continue
        if name == "SECTORS_WEEK":
            names = [s["name"] for s in pack.get("sectors") or [] if s.get("text_eligible")]
            if not names:
                continue
        q = quota + (LONG_HOLIDAY_EXTRA.get(name, 0) if long_holiday else 0)
        out.append(Topic(name, q, topic_brief(kind, name, window=window, edition_label=str(pack.get("edition_label")),
                                              us_sessions=us, names=names, quota=q), keys))
    return out


# -- calling ------------------------------------------------------------------------------------------------------
def request_for(topic: Topic, model: str, effort: str, messages: list[dict[str, Any]], settings: Any = None,
                continuation: bool = False, searches: int | None = None) -> dict[str, Any]:
    return calls.request(model=model, max_tokens=MAX_TOKENS, effort=effort, system=GATHER_SYSTEM, messages=messages,
                         tools=[calls.web_search_tool(topic.quota if searches is None else searches)],
                         settings=settings, continuation=continuation)


def _sent_back(msg: Any) -> dict[str, Any]:
    return {"role": "assistant", "content": [b.to_dict(mode="json") if hasattr(b, "to_dict") else b
                                             for b in msg.content]}


def citation_counts(content: list[Any]) -> tuple[int, int]:
    """``(cited, uncited)``: the answer's ``[KEY]`` paragraphs with and without a citation."""
    cited = uncited = 0
    for text, cites in paragraphs(content):
        if KEY_LINE.match(text):
            cited, uncited = (cited + 1, uncited) if cites else (cited, uncited + 1)
    return cited, uncited


def needs_citations(content: list[Any]) -> bool:
    """At least :data:`CITE_RETRY_SHARE` of the answer's ``[KEY]`` paragraphs came without a citation (they would all
    be dropped)."""
    cited, uncited = citation_counts(content)
    return uncited > 0 and uncited >= CITE_RETRY_SHARE * (cited + uncited)


def _now() -> datetime:
    return datetime.now(TAIPEI)


def call_topic(topic: Topic, model: str, effort: str, call: Callable[[dict[str, Any], int | None], tuple[Any, int]],
               settings: Any = None, clock: Callable[[], datetime] = _now) -> TopicResult:
    """One topic: the first call, then up to three ``pause_turn`` continuations on the same slot (the reply sent back
    as it came). An answer whose ``[KEY]`` paragraphs are mostly uncited (:func:`needs_citations`) gets one more turn
    (:data:`prompts.CITE_AGAIN`, at most :data:`CITE_RETRY_SEARCHES` new search); :func:`collect` keeps the better of
    the two answers. ``call(kw, only)`` runs the request on a key slot and returns ``(CallResult, slot)``; ``clock``
    stamps every reply (``replied_at``: what :func:`collect` takes as the time of this topic's searches)."""
    res = TopicResult(topic)
    messages: list[dict[str, Any]] = [{"role": "user", "content": topic.brief}]
    try:
        for retry in (False, True):
            for i in range(MAX_CONTINUATIONS + 1):
                kw = request_for(topic, model, effort, messages, settings, continuation=i > 0,
                                 searches=CITE_RETRY_SEARCHES if retry else None)
                out, slot = call(kw, res.slot)
                res.slot = slot
                res.msgs.append(out.msg)
                res.replied_at = clock()
                res.seconds += out.seconds
                if getattr(out.msg, "stop_reason", None) != "pause_turn":
                    break
                messages = [*messages, _sent_back(out.msg)]
            answer = [b for m in res.msgs[res.answers[-1]:] for b in (getattr(m, "content", None) or [])]
            if retry or getattr(res.msgs[-1], "stop_reason", None) == "pause_turn" or not needs_citations(answer):
                break
            res.answers.append(len(res.msgs))
            messages = [*messages, _sent_back(res.msgs[-1]), {"role": "user", "content": CITE_AGAIN}]
    except Exception as exc:  # one topic failing never stops the others
        if len(res.answers) > 1:  # the retry failed: the first answer stands
            log.warning("market report gathering: topic %s, asking again for citations failed (%s)", topic.name,
                        type(exc).__name__)
            return res
        res.error = type(exc).__name__
        log.warning("market report gathering: topic %s failed (%s)", topic.name, res.error)
    return res


def run_topics(topics: list[Topic], model: str, effort: str,
               call: Callable[[dict[str, Any], int | None], tuple[Any, int]], settings: Any = None,
               threads: int | None = None, clock: Callable[[], datetime] = _now) -> list[TopicResult]:
    threads = TOPIC_THREADS if threads is None else threads
    if threads <= 1 or len(topics) <= 1:
        return [call_topic(t, model, effort, call, settings, clock) for t in topics]
    with ThreadPoolExecutor(max_workers=min(threads, len(topics)), thread_name_prefix="mreport-gather") as ex:
        return list(ex.map(lambda t: call_topic(t, model, effort, call, settings, clock), topics))


# -- parsing ------------------------------------------------------------------------------------------------------
def _get(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def paragraphs(content: list[Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    """The reply's text cut into paragraphs (blank lines), each with the citations of its cited blocks."""
    out: list[tuple[str, list[dict[str, Any]]]] = []
    text, cites = "", []

    def close() -> None:
        nonlocal text, cites
        if text.strip():
            out.append((text.strip(), cites))
        text, cites = "", []

    for b in content:
        if _get(b, "type") != "text":
            continue
        t = str(_get(b, "text") or "")
        cs = [c if isinstance(c, dict) else c.to_dict(mode="json") if hasattr(c, "to_dict") else dict(c)
              for c in (_get(b, "citations") or [])]
        if cs:
            text += t
            cites.extend(c for c in cs if c.get("type") == "web_search_result_location")
            continue
        parts = re.split(r"\n\s*\n", t)
        for i, part in enumerate(parts):
            if i > 0:
                close()
            text += part
    close()
    return out


# -- verification (§8.5) ------------------------------------------------------------------------------------------
@dataclass
class Window:
    start: datetime
    end: datetime
    cutoff: datetime
    # the US sessions the edition covers (with or without stored closes); ``None``: unknown (a pack stored before
    # ``web_window.us_sessions`` and without US closes) — any US trading day before the cut-off's day
    us_sessions: set[date] | None
    now: datetime  # when the searches were done (after them): no page found can be newer


def _related_reason(cited: str, titles: list[str], own: str) -> str | None:
    """Why a cited passage is not the article's own text: ``"list"`` (a 「相關新聞」 list), ``"other_title"`` (it holds
    another result's title), ``"short"`` (under 20 characters); ``None`` when it is."""
    c = cited.strip()
    lines = [x for x in c.splitlines() if x.strip()]
    if len(lines) >= 3 and all(len(x.strip()) < 30 for x in lines):
        return "list"
    for t in titles:
        t = t.strip()
        if t and t != own.strip() and len(t) >= 12:
            for i in range(0, len(t) - 11):
                if t[i:i + 12] in c:
                    return "other_title"
    return "short" if len(c) < 20 else None


def _related_headline(cited: str, titles: list[str], own: str) -> bool:
    return _related_reason(cited, titles, own) is not None


def _published(url: str, page_age: str | None, now: datetime) -> datetime | date | None:
    found = datetime_from_page_age(page_age, now)
    if found is not None:
        return found
    return date_from_url(url)


def in_window(pub: datetime | date, w: Window) -> bool:
    """A page dated to the minute inside [start, end]. A page dated by day alone: a day from the window's start to
    the day before the cut-off (a premarket: the previous session's day); or the cut-off's own day when that whole day
    up to the search is inside the window — the page was found by the search, so it is no later than ``w.now``
    (taken when the searches were done): a premarket searched at 06:15 or a weekly at 16:30 keeps "0 days ago", a
    rebuild after the window does not, and a close edition (its window starts that morning) needs a publish time
    (:func:`stamped`)."""
    if isinstance(pub, datetime):
        return w.start <= pub <= w.end
    if w.start.date() <= pub < w.cutoff.date():
        return True
    return pub == w.cutoff.date() and w.start <= datetime.combine(pub, time(0), TAIPEI) <= w.now <= w.end


def publish_stamp(text: str, m: re.Match[str], *, title: bool = False) -> bool:
    """The stamp ``m`` of ``text`` sits where a page writes its publish time (before the byline, :data:`BYLINE`;
    after a label, :data:`PUBLISH_LABEL`; after the byline, :data:`BYLINE_BEFORE`; at the start of the passage or of a
    line; at the end of a title) and no scheduled event's words are next to it (:data:`EVENT_WORDS`):
    「2026/11/17 14:35 中央社記者…電」 is a publish time, 「台積電訂 2026/11/17 14:00 召開法說會」 and 「將於 11/17
    13:30 結算」 are not."""
    before = re.split(r"[。；！？!?\n]", text[:m.start()])[-1][-_STAMP_SPAN:]
    after = re.split(r"[。；！？!?\n]", text[m.end():])[0][:_STAMP_SPAN]
    if EVENT_WORDS.search(before):
        return False
    rest = after.lstrip(_SEPARATORS)
    if BYLINE.match(rest) or PUBLISH_LABEL.search(before):
        return True  # the byline follows (or a label comes before): what comes after it is the story
    lead = not before.strip(_SEPARATORS) or (title and not rest.strip(_SEPARATORS)) or BYLINE_BEFORE.search(before)
    return bool(lead) and not EVENT_WORDS.search(after) and not EVENT_AFTER.match(after)


def stamped(day: date, texts: Iterable[str], w: Window, titles: Iterable[str] = ()) -> datetime | None:
    """The publish time a page dated only by ``day`` writes in its cited passages (``texts``) or ``titles``
    (:data:`STAMP` where :func:`publish_stamp` says it is one), when it is on that day, inside the window and no later
    than the search."""
    for t, is_title in [*((x, False) for x in texts), *((x, True) for x in titles)]:
        for m in STAMP.finditer(t or ""):
            if not publish_stamp(t or "", m, title=is_title):
                continue
            y, mo, d, hh, mm = m.groups()
            year = day.year if y is None else int(y) + (1911 if len(y) == 3 else 0)
            try:
                at = datetime(year, int(mo), int(d), int(hh), int(mm), tzinfo=TAIPEI)
            except ValueError:
                continue
            if at.date() == day and w.start <= at <= min(w.end, w.now):
                return at
    return None


def quote_page(url: str) -> bool:
    """A quote, index, ranking or data page (``analyst.is_article`` plus :data:`QUOTE_PAGE_PATHS`), not a report."""
    if not is_article(url):
        return True
    try:
        path = urlsplit(url).path.lower()
    except ValueError:
        return False
    host = host_of(url)
    return any(on_domain(host, h) and path.startswith(prefixes) for h, prefixes in QUOTE_PAGE_PATHS.items())


def _us_date_ok(claim: str, w: Window, scheduled: bool = False) -> date | None:
    """The US trading day the claim names (「美股 11/16」): one that ended before the cut-off's day (a premarket at
    06:55 on 11/17 reports the 11/16 session, never 「美股 11/17」) and that the edition covers
    (``w.us_sessions``: a premarket's overnight sessions, a weekly's week; every US date the claim names must be one —
    「美股 11/13」 in the premarket of 11/17 is an older session's story). A scheduled US earnings date may be any
    trading day up to the cut-off's own day (tonight)."""
    found = None
    for m in US_DATE.finditer(claim):
        mo, d = int(m.group(1)), int(m.group(2))
        try:  # the latest such date up to the cut-off's day (12/31 in a January edition is last year's)
            x = date(w.cutoff.year, mo, d)
            if x > w.cutoff.date():
                x = date(w.cutoff.year - 1, mo, d)
        except ValueError:
            continue
        ok = (x <= w.cutoff.date() if scheduled else x < w.cutoff.date()) and is_us_trading_day(x)
        if not scheduled and w.us_sessions is not None and is_us_trading_day(x) and x not in w.us_sessions:
            return None  # a session the edition does not cover
        if ok and found is None:
            found = x
    return found


def verify(key: str, claim: str, cites: list[dict[str, Any]], results: dict[str, Any], w: Window,
           allowed: tuple[str, ...]) -> tuple[dict[str, Any] | None, str | None]:
    """A checked fact (without its id) or the reason it was dropped."""
    if not key_allowed(key, allowed):
        return None, "bad_key"
    if not cites:
        return None, "no_citation"
    titles = [r.title for r in results.values()]
    valid: list[tuple[dict[str, Any], Any]] = []
    short: list[dict[str, Any]] = []
    reason = None
    for c in cites:
        url = str(c.get("url") or "")
        r = results.get(_norm_url(url))
        if r is None:
            reason = reason or "url_not_in_results"
            continue
        host = host_of(url)
        if not any(on_domain(host, d) for d in calls.REPORT_SEARCH_DOMAINS):
            reason = reason or "domain"
            continue
        if quote_page(url):
            reason = reason or "quote_page"
            continue
        why_not = _related_reason(str(c.get("cited_text") or ""), titles, str(c.get("title") or r.title))
        if why_not is not None:
            reason = reason or "related_headline"
            if why_not == "short":
                short.append(c)  # never a source, but a bare dateline (「2026/11/17 14:35」) still dates its page
            continue
        valid.append((c, r))
    if not valid:
        return None, reason or "no_citation"
    # freshness: every citation's own page (one outside the window, or of unknown time, is left out)
    texts: dict[str, list[str]] = {}
    page_titles: dict[str, list[str]] = {}
    for c, r in valid:
        u = _norm_url(str(c.get("url")))
        texts.setdefault(u, []).append(str(c.get("cited_text") or ""))
        page_titles.setdefault(u, [r.title]).append(str(c.get("title") or ""))
    for c in short:
        if (u := _norm_url(str(c.get("url")))) in texts:
            texts[u].append(str(c.get("cited_text") or ""))
    fresh: list[tuple[dict[str, Any], Any, datetime | date]] = []
    why = "time_unknown"
    for c, r in valid:
        pub = _published(str(c.get("url")), r.page_age, w.now)
        if pub is not None and not isinstance(pub, datetime) and pub == w.cutoff.date() and not in_window(pub, w):
            # the cut-off's own day, dated by day alone: kept only with a publish time inside the window
            u = _norm_url(str(c.get("url")))
            pub = stamped(pub, texts[u], w, page_titles[u]) or pub
            if not isinstance(pub, datetime):
                why = "no_publish_time"
                continue
        if pub is not None and in_window(pub, w):
            fresh.append((c, r, pub))
        elif pub is not None and why == "time_unknown":
            why = "outside_window"
    if not fresh:
        return None, why
    claim_nums = numbers(claim, INDEX_NAMES_WITH_DIGITS)
    quote_nums = [numbers(str(c.get("cited_text") or ""), INDEX_NAMES_WITH_DIGITS) for c, _, _ in fresh]

    def found(n: Any, qs: list[Any]) -> bool:
        return any(abs(n.value - q.value) <= n.tol + 1e-9 for q in qs)

    if any(not any(found(n, qs) for qs in quote_nums) for n in claim_nums):
        return None, "number_not_in_quote"
    us_session = None
    if key.startswith(("US.", "ADR.", "NIGHT.")):
        us_session = _us_date_ok(claim, w, scheduled=key.startswith("US.earnings."))
        if us_session is None:
            return None, "no_us_session_date"
    if index_points(claim) is not None:
        return None, "index_points"
    if key.startswith(PERCENT_KEYS) and not key.startswith("US.earnings.") \
            and any(n.unit != "%" for n in claim_nums):
        return None, "index_points"  # US indices, the night session and the ADR: percentages only
    if RATING.search(claim):
        return None, "rating"
    if VIEW.search(claim) or JUDGEMENT.search(claim) \
            or (OUTLOOK.search(claim) and (not key.startswith(SCHEDULE_KEYS) or FORECAST.search(claim))):
        return None, "outlook"  # someone's view of where the market or a stock goes is not a fact to quote
    # the source: the citation holding the claim's numbers (the first fresh one when it has none)
    best = max(range(len(fresh)), key=lambda i: (sum(found(n, quote_nums[i]) for n in claim_nums), -i))
    c0, r0, pub = fresh[best]
    quotes = " ".join([str(c0.get("cited_text") or ""),
                       *(str(c.get("cited_text") or "") for i, (c, _, _) in enumerate(fresh) if i != best)])
    url = str(c0.get("url"))
    return {"key": key, "subject": next((v for k, v in SUBJECTS.items() if key == k), None), "claim": claim,
            "outlet": outlet_name(url), "title": str(c0.get("title") or r0.title)[:200], "url": url,
            "published_at": pub.isoformat(),
            "date_only": not isinstance(pub, datetime),
            "numbers": [_num_raw(claim, n) for n in claim_nums], "us_session": us_session.isoformat() if us_session
            else None, "quote": quotes[:QUOTE_CHARS]}, None


def _num_raw(text: str, n: Any) -> str:
    from forliosa.reports.validate import normalize

    t = normalize(text)
    m = re.match(r"[\d.]+", t[n.start:].lstrip("+-▲▼ "))
    return m.group(0) if m else ""


def _main_number(fact: dict[str, Any]) -> str | None:
    return fact["numbers"][0] if fact.get("numbers") else None


def disagreements(facts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Facts of a numeric key whose main numbers differ: the first outlet in :data:`OUTLET_PRIORITY` stays, the others
    move to the disagreements (never cited)."""
    by_key: dict[str, list[dict[str, Any]]] = {}
    for f in facts:
        if any(f["key"] == k or (k.endswith(".") and f["key"].startswith(k)) for k in NUMERIC_KEYS) \
                and _main_number(f):
            by_key.setdefault(f["key"], []).append(f)
    drop_ids: set[int] = set()
    out: list[dict[str, Any]] = []
    for key, group in by_key.items():
        if len({_main_number(f) for f in group}) < 2:
            continue

        def rank(f: dict[str, Any]) -> int:
            return OUTLET_PRIORITY.index(f["outlet"]) if f["outlet"] in OUTLET_PRIORITY else len(OUTLET_PRIORITY)

        group = sorted(group, key=rank)
        kept = group[0]
        others = [f for f in group[1:] if _main_number(f) != _main_number(kept)]
        if not others:
            continue
        drop_ids |= {id(f) for f in others}
        unit = "億元" if key.startswith("TWSE_INST.") or key == "TW.turnover_media" else "%"
        text = "；".join(f"{f['outlet']}寫 {_main_number(f)} {unit}" for f in others)
        out.append({"key": key, "label": LABELS.get(key, key),
                    "kept": {"outlet": kept["outlet"], "value": f"{_main_number(kept)} {unit}"},
                    "others": [{"outlet": f["outlet"], "value": f"{_main_number(f)} {unit}"} for f in others],
                    "text": f"{text}，{kept['outlet']}寫 {_main_number(kept)} {unit}；本報告以{kept['outlet']}為準。"})
    return [f for f in facts if id(f) not in drop_ids], out


def _check_answer(content: list[Any], found: dict[str, Any], w: Window, topic: Topic) \
        -> tuple[list[dict[str, Any]], dict[str, int]]:
    dropped: dict[str, int] = {}
    kept: list[dict[str, Any]] = []
    for text, cites in paragraphs(content):
        m = KEY_LINE.match(text)
        if m is None:
            continue
        fact, why = verify(m.group(1), m.group(2).strip(), cites, found, w, topic.keys)
        if fact is None:
            dropped[why or "other"] = dropped.get(why or "other", 0) + 1
            continue
        if len(kept) >= MAX_PER_TOPIC:
            dropped["limit"] = dropped.get("limit", 0) + 1
            continue
        fact["topic"] = topic.name
        kept.append(fact)
    return kept, dropped


def collect(results: list[TopicResult], w: Window) -> Outcome:
    """Parse and check every topic's replies; number the kept facts X001… by topic, in order. A topic asked again
    for citations keeps the answer with more facts (on a tie the later one, when it wrote any [KEY] paragraph); the
    searches of both answers count. Each topic is checked against the time of its own last reply (``replied_at``,
    never later than ``w.now``): a slow topic does not make the others' same-day pages look searched too late."""
    facts: list[dict[str, Any]] = []
    topics: list[dict[str, Any]] = []
    for res in results:
        tw = replace(w, now=min(w.now, res.replied_at)) if res.replied_at is not None else w
        content = [b for m in res.msgs for b in (getattr(m, "content", None) or [])]
        found = {_norm_url(r.url): r for r in search_results(content)}
        bounds = [*res.answers, len(res.msgs)]
        kept: list[dict[str, Any]] = []
        dropped: dict[str, int] = {}
        for a, b in pairwise(bounds):
            answer = [x for m in res.msgs[a:b] for x in (getattr(m, "content", None) or [])]
            k, d = _check_answer(answer, found, tw, res.topic)
            if a == 0 or len(k) > len(kept) or (len(k) == len(kept) and (k or d)):
                kept, dropped = k, d
        facts.extend(kept)
        row = {"topic": res.topic.name, "quota": res.topic.quota, "results": len(found), "kept": len(kept),
               "dropped": dropped, "error": res.error, "seconds": round(res.seconds, 1)}
        if len(res.answers) > 1:
            row["asked_again"] = True  # the first answer was mostly uncited (call_topic)
        topics.append(row)
    facts, disagree = disagreements(facts)
    for i, f in enumerate(facts, start=1):
        f["id"] = f"X{i:03d}"
    return Outcome(facts, disagree, topics, results)


def window(pack: dict[str, Any], now: datetime) -> Window:
    """The pack's window; ``now``: when the searches were done (:func:`collect` narrows it to each topic's own)."""
    w = pack.get("web_window") or {}
    listed = us_sessions_of(pack)
    # an edition with no US session (the day after a US holiday) says so; only a pack stored before the field and
    # without US closes leaves them unknown
    sessions = {date.fromisoformat(d) for d in listed} if listed or "us_sessions" in w else None
    return Window(datetime.fromisoformat(w["from"]).astimezone(TAIPEI),
                  datetime.fromisoformat(w["to"]).astimezone(TAIPEI),
                  datetime.fromisoformat(pack["cutoff"]).astimezone(TAIPEI), sessions, now)


def for_writer(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The X facts as the data pack carries them (quotes included: the writer and the validator need them)."""
    keys = ("id", "topic", "key", "subject", "claim", "outlet", "title", "url", "published_at", "date_only", "numbers",
            "us_session", "quote")
    return [{k: f.get(k) for k in keys} for f in facts]
