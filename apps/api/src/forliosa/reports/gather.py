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
pages put one, never the time of a scheduled event) — the close edition's window starts the same morning, so there a
page that writes no publish time is also kept, when searched after the session closed (a rebuild too), if the numbers
its cited passages quote match that day's official close (:func:`close_verdict`, the owner's Option A of 2026-11-17;
one number contradicting the close drops it); the fact's source is the citation that holds its numbers) — the
citation is a passage of the article (not a 「相關新聞」 list), every number is in a fresh cited passage, a US / ADR /
night-session fact names a US trading day the edition covers (:attr:`Window.us_sessions`) and has percentages only, no
index points, no ratings or target prices, no one's view of where the market goes. What is kept becomes an X fact for
the writer (its ``quote`` stays on the server side: the API never returns it). When outlets disagree on a number of
the same key, one fixed outlet wins and the others are listed as a disagreement (:data:`OUTLET_PRIORITY`).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise
from typing import Any
from urllib.parse import urlsplit

from forliosa.ai.analyst import date_from_page_age, date_from_url, datetime_from_page_age, is_article, search_results
from forliosa.ai.market_summary import _norm_url
from forliosa.news.outlets import OUTLETS, host_of, on_domain, outlet_name
from forliosa.reports import calls
from forliosa.reports.marketcalc import SECTOR_NAMES
from forliosa.reports.prompts import CITE_AGAIN, GATHER_SYSTEM, LONG_HOLIDAY_EXTRA, TOPICS, key_allowed, topic_brief
from forliosa.reports.validate import FORECAST, OUTLOOK, POINTS_BANNED, VIEW, index_points, numbers
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
# 記者, 報導, 「台北17日電」, 更新), right after a label (發布時間：) or a byline, at the start of a passage or a
# line, or at the end of a title — and never next to the words of a scheduled event (「台積電訂 2026/11/17 14:00
# 召開法說會」「將於 11/17 13:30 結算」: an old preview names a time of the day it is about).
_OUTLET_WORDS = sorted({w for o in OUTLETS.values() for w in (o.name, *o.aliases) if len(w) >= 2}, key=len,
                       reverse=True)
BYLINE = re.compile(r"(?:記者(?!會)|(?:即時|綜合|特稿|專題)?報導|\d{1,2}日(?:專)?電|(?:最後)?更新|編輯|撰文|撰稿|作者|"
                    r"文\s*[／/]|" + "|".join(re.escape(w) for w in _OUTLET_WORDS) + ")", re.IGNORECASE)
PUBLISH_LABEL = re.compile(r"(?:發布|發佈|發稿|更新|刊出|刊登|出版|上稿)(?:時間|日期)?\s*[:：]?\s*$")
# a byline just before the stamp (「鉅亨網記者王小明 台北 2026/11/17 14:05」): the story may follow the stamp
BYLINE_BEFORE = re.compile(r"記者(?!會)|新聞中心|編譯|\d{1,2}日(?:專)?電|"
                           + "|".join(re.escape(w) for w in _OUTLET_WORDS), re.IGNORECASE)
EVENT_WORDS = re.compile(r"召開|舉行|舉辦|登場|公布|公佈|揭曉|結算|開盤|收盤|開市|收市|休市|將於|將在|訂於|訂在"
                         r"|預計|預定|排定|法說|說明會|記者會|會議|截止|演講|致詞|訂\s*$")
EVENT_AFTER = re.compile(r"^\s*(?:起|開始|前|止|為止|截止)")
_SEPARATORS = " \t\u3000|｜/／-–—·•,，:：()（）[]【】〔〕「」"
_STAMP_SPAN = 12  # characters around a stamp that tell what it is
# Option A (owner 2026-11-17): the close edition dates a same-day page without a publish time by its numbers — the
# official close of the day (never an estimate) and the names a page writes for each subject
CLOSE_METRICS = frozenset({"index_close", "index_change", "index_pct", "otc_close", "otc_change", "otc_pct",
                           "stock_close", "stock_pct"})
CLOSE_EXTRA_NAMES = {"加權指數": ("指數", "加權股價指數", "台股指數"), "櫃買指數": ("上櫃指數",)}
CLOSE_GENERIC_NAMES = frozenset({"上市"})  # 「上市櫃」「上市公司」: not the index
CLOSE_TIME = time(13, 30)  # the TWSE session's close
# another market's names: the closest name before a number being one of these, the number is not judged
CLOSE_BLOCKERS = (*POINTS_BANNED, "ADR", "報酬指數", "美股", "日經", "韓股", "陸股", "港股", "上證", "滬深", "恒生",
                  "恆生", "KOSPI")
# the number is the close or the day's change as the page states it (「收跌947點」「終場下殺45元」「收2170元」)
CLOSE_WORDS = re.compile(r"(?<![營回])收(?!入|購|益|錄|到)|終場|尾盤")
# a move written before the number (「下跌4%」「重挫70元」): with 「收」 or ▲▼, the number is judged — it has to match
CLOSE_MOVES = re.compile(r"漲|跌|挫|殺|揚")
# the session's swings, another period or another figure (營收、EPS、市值…): never judged against the close —
# 「較前一交易日下跌70元」 is the day's change, 「前一交易日收1,500元」 is not
CLOSE_INTRADAY = re.compile(r"盤中|一度|最高|最低|高點|低點|開盤|早盤|午盤|盤初|盤前|盤後交易|震盪|振幅|區間"
                            r"|觸及|跌破|突破|站上|失守|跌落|來到|以來|累計|連續|連\d|本週|上週|單週|全週|週[漲跌線]"
                            r"|今年|本月|上月|(?<![較比])前一|(?<![較比])昨|季|去年|同期|年增|年減|月增|月減"
                            r"|營收|獲利|純益|淨利|毛利|營益|EPS|每股|股利|配息|殖利率|市值|占比|佔比|比重|權重|目標價"
                            r"|期貨|夜盤")
# Clauses: a name counts for the numbers of its own clause only (「台積電收跌70元，聯電收跌3元」: 3元 is not
# 台積電's) — they end at 「，」「；」「、」 or at a space between a headline's clauses (「台積電跌70元 聯電跌3元」)
CLOSE_CLAUSE = re.compile(r"[,;、]|(?<=[\u3400-\u9fff%])\s+(?=[\u3400-\u9fff])")
# Names and numbers listed together (「台積電、聯發科分別下跌70元、60元」「台積電與聯發科下跌70元與60元」): not judged
CLOSE_LIST = re.compile(r"分別|各自|依序|依次|各[漲跌收]")
CLOSE_AND = re.compile(r"\s*(?:與|和|及|以及|跟|、)\s*")
# A group of stocks or a sector (「金融股」「半導體類股」「AI 概念股」「電子權值股」): a number after it is the group's,
# never the listed stock's before it
_SECTOR_SHORT = ("金融", "電子", "傳產", "塑化", "生技", "營建", "紡織", "觀光", "面板", "記憶體", "散熱", "網通",
                 "PCB", "IC設計", "AI", "重電", "軍工", "機器人", "伺服器", "蘋概", "高價", "中小型", "權值", "低價",
                 "航運")
CLOSE_GROUPS = re.compile(r"類股|族群|概念股|成分股|權值股|供應鏈|(?:" + "|".join(
    re.escape(x) for x in sorted({*SECTOR_NAMES, *_SECTOR_SHORT}, key=len, reverse=True)) + r")\s*(?:類|股|業)",
    re.IGNORECASE)
# a rounded figure (「收跌逾900點」「跌近5%」「2,100元左右」): neither a match nor a contradiction
CLOSE_APPROX_BEFORE = re.compile(r"(?:逾|近|超過|約|將近|接近|逼近|大約|上看|下看)\s*$")
CLOSE_APPROX_AFTER = re.compile(r"^\s*(?:多|餘|左右|上下|以上|以下|附近|之上|之下)")
_CLOSE_NUM = re.compile(r"(?P<sign>[+\-▲▼])?\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<mult>兆|億|萬)?"
                        r"\s*(?P<unit>%|點|美元|元|家|口|張|倍|則|檔)?")
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
@dataclass(frozen=True)
class CloseData:
    """The official close of the cut-off's day (the close edition's pack, never an estimate): the names a page may
    write for each subject (加權指數、大盤、指數、櫃買、台積電…) and the subject's values by unit — 點 (an index's close
    and change), % (the change), 元 (a stock's close and its change from the reference price, derived from the close
    and the percentage). Each value is ``(value, signed)``: a change carries its direction, a close does not."""
    names: dict[str, str]
    values: dict[str, dict[str, list[tuple[float, bool]]]]


@dataclass
class Window:
    start: datetime
    end: datetime
    cutoff: datetime
    # the US sessions the edition covers (with or without stored closes); ``None``: unknown (a pack stored before
    # ``web_window.us_sessions`` and without US closes) — any US trading day before the cut-off's day
    us_sessions: set[date] | None
    now: datetime  # when the searches were done (after them): no page found can be newer
    # the close edition: that day's official close (:func:`close_data`), which dates a same-day page whose numbers
    # match it (:func:`close_numbers`); ``None`` for the other kinds
    close: CloseData | None = None


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


# The search engine counts "N days ago" in calendar days of UTC, not of Taipei: searched at 01:00 Taipei on 11/18
# (17:00 UTC on 11/17), the 11/17 close stories were "0 days ago" and the 11/16 ones "1 days ago" (the third dry
# run). Counted back from the Taipei date, every such page came out a day too new from midnight to 08:00 Taipei — a
# rebuild then dropped the whole close day as ``outside_window``, and a premarket searched at 06:15 read "1 days ago"
# (Taipei two days back, 08:00, to the day before, 08:00) as the previous session's day. So the day is counted back
# from the UTC date of the search; "N hours ago" and dates stay as they are.
_DAYS_AGO = re.compile(r"^\s*\d+\s*(?:day|week|month|year)s?\s+ago\s*$", re.IGNORECASE)


def _published(url: str, page_age: str | None, now: datetime) -> datetime | date | None:
    if page_age and _DAYS_AGO.match(page_age):
        return date_from_page_age(page_age, now.astimezone(UTC).date())
    found = datetime_from_page_age(page_age, now)
    if found is not None:
        return found
    return date_from_url(url)


def in_window(pub: datetime | date, w: Window) -> bool:
    """A page dated to the minute inside [start, end]. A page dated by day alone: a day from the window's start to
    the day before the cut-off (a premarket: the previous session's day); or the cut-off's own day when that whole day
    up to the search is inside the window — the page was found by the search, so it is no later than ``w.now``
    (taken when the searches were done): a weekly searched at 16:30 keeps "0 days ago" (a premarket's 06:15 is still
    the day before in UTC: its "0 days ago" is the previous session's day, :func:`_published`), a rebuild after the
    window does not, and a close edition (its window starts that morning) needs a publish time
    (:func:`stamped`) or numbers matching that day's close (:func:`close_verdict`)."""
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


def publish_times(day: date, texts: Iterable[str], titles: Iterable[str] = ()) -> Iterator[datetime]:
    """The publish times on ``day`` a page writes in its cited passages (``texts``) or ``titles`` (:data:`STAMP` where
    :func:`publish_stamp` says it is one)."""
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
            if at.date() == day:
                yield at


def stamped(day: date, texts: Iterable[str], w: Window, titles: Iterable[str] = ()) -> datetime | None:
    """The publish time a page dated only by ``day`` writes (:func:`publish_times`), when it is inside the window and
    no later than the search."""
    return next((at for at in publish_times(day, texts, titles) if w.start <= at <= min(w.end, w.now)), None)


def close_data(pack: dict[str, Any]) -> CloseData | None:
    """The close edition's official close of its own day (:class:`CloseData`); ``None`` for the other kinds or when
    the pack has none."""
    if pack.get("kind") != "close":
        return None
    day = str(pack.get("edition_date") or "")[:10]
    names: dict[str, str] = {}
    values: dict[str, dict[str, list[tuple[float, bool]]]] = {}
    closes: dict[str, float] = {}
    pcts: dict[str, float] = {}
    for f in pack.get("facts") or []:
        metric, v = f.get("metric"), f.get("value")
        if metric not in CLOSE_METRICS or f.get("group") != "today" or f.get("estimate") \
                or str(f.get("date") or "")[:10] != day or not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        subject, unit = str(f.get("subject") or ""), str(f.get("unit") or "")
        if not subject or unit not in ("點", "%", "元"):
            continue
        signed = metric.endswith(("_change", "_pct"))
        values.setdefault(subject, {}).setdefault(unit, []).append((float(v) * (100 if unit == "%" else 1), signed))
        if metric == "stock_close":
            closes[subject] = float(v)
        elif metric == "stock_pct":
            pcts[subject] = float(v)
        for n in (subject, *(f.get("aliases") or []), *CLOSE_EXTRA_NAMES.get(subject, ())):
            n = str(n or "")
            if len(n) >= 2 and not n.isdigit() and n not in CLOSE_GENERIC_NAMES:
                names.setdefault(n, subject)
    for subject, close in closes.items():
        pct = pcts.get(subject)
        if pct is not None and pct > -1:
            values[subject]["元"].append((close * pct / (1 + pct), True))  # 「下跌45元」: close − reference price
    return CloseData(names, values) if values else None


def _close_tokens(sent: str, data: CloseData) -> list[tuple[int, int, str | None]]:
    """The names in ``sent`` as ``(start, end, subject)``; ``None``: a name that is not a listed subject's and stops
    the search for one — another market's (美股指數、台指期、ADR…) or a group of stocks (金融股、半導體類股、概念股:
    :data:`CLOSE_GROUPS`). 「指數」 alone is the TAIEX only where it stands alone (「，指數收跌」), not inside another
    index's name (「費半指數」)."""
    rx = re.compile("|".join(re.escape(n) for n in sorted({*data.names, *CLOSE_BLOCKERS}, key=len, reverse=True)),
                    re.IGNORECASE)
    out: list[tuple[int, int, str | None]] = []
    for m in rx.finditer(sent):
        word = m.group(0)
        subject = data.names.get(word) if word in data.names else None
        if subject is not None and re.match(r"\s*ADR", sent[m.end():], re.IGNORECASE):
            subject = None  # 台積電 ADR is not 台積電
        if word == "指數" and word in data.names:
            if out and out[-1][1] == m.start():
                continue  # 「櫃買指數」「台股指數」: part of the name before it
            if m.start() > 0 and re.match(r"[\w&]", sent[m.start() - 1]):
                subject = None  # 「費半指數」「標普500指數」
        out.append((m.start(), m.end(), subject))
    groups = [(m.start(), m.end(), None) for m in CLOSE_GROUPS.finditer(sent)]
    # a name inside a group's words (「台塑化股價」 holds 塑化股) is the group's: never a subject there
    out = [tk for tk in out if not any(g0 < tk[1] and tk[0] < g1 for g0, g1, _ in groups)]
    return sorted([*out, *groups])


def _close_hit(n: Any, raw: str, values: list[tuple[float, bool]]) -> tuple[bool, bool]:
    """``(value matches, direction agrees)`` of a written number against a subject's values: rounded to the written
    decimals (the validator's tolerance); index points may also be cut off there (「收跌947點」 for ▼947.97, as
    headlines write it) — a percentage or NT$ never (「跌4%」 is not ▼4.67%)."""
    decimals = len(raw.split(".", 1)[1]) if "." in raw else 0
    for v, signed in values:
        a = abs(v)
        cut = int(a * 10 ** decimals + 1e-6) / 10 ** decimals if n.unit == "點" else None
        if abs(n.value - a) <= n.tol + 1e-9 or (cut is not None and abs(n.value - cut) < 1e-9):
            return True, not (signed and n.sign and v != 0 and (1 if v > 0 else -1) != n.sign)
    return False, True


def close_numbers(texts: Iterable[str], data: CloseData) -> tuple[str | None, str]:
    """Option A (owner 2026-11-17): what the numbers of a same-day page's cited passages say about its day.
    ``("matched_close_numbers", …)`` when at least one number of a subject (a stock's change in NT$ or %, an index's
    change in points or %, a close) matches the official close and none contradicts it; ``("contradicts_close",
    "南亞 262.5元")`` when a number written as the day's close or move of a subject (收、終場、漲、跌、挫、▲▼：「南亞
    收262.5元」「收跌950點」「台積電下跌4%」) matches none of its values in that unit, or a matching change goes the
    other way (「台積電上漲45元」 on a day it fell 45) — every judged number has to match; ``(None, "")`` when the
    passages hold no such number. A number belongs to the closest name before it in its own clause
    (:data:`CLOSE_CLAUSE`): when that name is a group of stocks (金融股、半導體類股), another market's (美股、台指期、
    ADR), a subject without that unit (櫃買指數 for 元), or there is none (聯電 is no listed name), the number is not
    judged. Nor is a number of the session's swings (盤中、一度、震盪、跌破…), of another period or figure (上週、營收、
    EPS…), rounded (逾、近、左右) or scaled (億元)."""
    from forliosa.reports.validate import PLAIN_PHRASES, normalize

    matched: list[str] = []
    for text in texts:
        t = normalize(text or "")
        for phrase in PLAIN_PHRASES:  # 東南亞 holds 南亞
            t = t.replace(phrase, "＿" * len(phrase))
        for sent in re.split(r"[。；;！？!?\n]", t):
            tokens = _close_tokens(sent, data)
            breaks = [b.end() for b in CLOSE_CLAUSE.finditer(sent)]
            last = 0
            for n in numbers(sent, INDEX_NAMES_WITH_DIGITS):
                m = _CLOSE_NUM.match(sent, n.start)
                end = m.end() if m else n.start + 1
                raw = m.group("num") if m else ""
                lead_from = last
                last = end
                if n.unit not in ("點", "%", "元") or n.approx or (m and m.group("mult")):
                    continue
                clause = max((b for b in breaks if b <= n.start), default=0)
                before = [tk for tk in tokens if tk[0] >= clause and tk[1] <= n.start]
                if not before:
                    continue  # no name in its clause (「聯電收跌3元」)
                start, stop, subject = before[-1]
                if subject is None or n.unit not in data.values.get(subject, {}):
                    continue  # the closest name is a group's, another market's or has no such number
                if CLOSE_LIST.search(sent[clause:n.start]) \
                        or (len(before) > 1 and CLOSE_AND.fullmatch(sent[before[-2][1]:start])):
                    continue  # 「台積電與聯發科分別下跌70元與60元」: a list of names and numbers
                lead = sent[max(lead_from, stop):n.start]
                if CLOSE_INTRADAY.search(lead) or CLOSE_APPROX_BEFORE.search(lead) \
                        or CLOSE_APPROX_AFTER.match(sent[end:]):
                    continue
                hit, same_way = _close_hit(n, raw, data.values[subject][n.unit])
                said = f"{subject} {sent[n.start:end].strip()}"
                judged = bool(CLOSE_WORDS.search(lead) or CLOSE_MOVES.search(lead)
                              or (m and m.group("sign") in ("▲", "▼")))
                if hit and same_way:
                    matched.append(said)
                elif not same_way or judged:
                    return "contradicts_close", said
    return ("matched_close_numbers", "、".join(dict.fromkeys(matched))) if matched else (None, "")


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
    by_numbers: set[int] = set()  # the fresh citations dated by their numbers (Option A)
    why = "time_unknown"
    for c, r in valid:
        pub = _published(str(c.get("url")), r.page_age, w.now)
        if pub is not None and not isinstance(pub, datetime) and pub == w.cutoff.date() and not in_window(pub, w):
            # the cut-off's own day, dated by day alone: kept with a publish time inside the window, or (the close
            # edition) when its passages quote that day's official close
            u = _norm_url(str(c.get("url")))
            pub = stamped(pub, texts[u], w, page_titles[u]) or pub
            if not isinstance(pub, datetime):
                verdict = close_verdict(pub, texts[u], w, page_titles[u])
                if verdict == "matched_close_numbers":
                    by_numbers.add(len(fresh))
                    fresh.append((c, r, pub))
                    continue
                why = "contradicts_close" if verdict == "contradicts_close" or why == "contradicts_close" \
                    else "no_publish_time"
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
    fact = {"key": key, "subject": next((v for k, v in SUBJECTS.items() if key == k), None), "claim": claim,
            "outlet": outlet_name(url), "title": str(c0.get("title") or r0.title)[:200], "url": url,
            "published_at": pub.isoformat(),
            "date_only": not isinstance(pub, datetime),
            "numbers": [_num_raw(claim, n) for n in claim_nums], "main": _main_raw(key, claim, claim_nums),
            "us_session": us_session.isoformat() if us_session else None, "quote": quotes[:QUOTE_CHARS]}
    if best in by_numbers:
        fact["dated_by"] = "matched_close_numbers"  # diagnostics: no publish time, its numbers are that day's close
    return fact, None


def close_verdict(day: date, texts: Iterable[str], w: Window, titles: Iterable[str] = ()) -> str | None:
    """Option A for a page dated only by the cut-off's day without a publish time: ``"matched_close_numbers"`` (kept:
    it counts as published after that day's close), ``"contradicts_close"`` or ``None`` (dropped). Only the close
    edition (``w.close``), only for a search made after the session closed (13:30) — the scheduled one (15:40) or a
    rebuild later (a gathering that started late, ``run`` by hand): a page dated by day alone cannot be placed before
    or after the window's end either way, and the owner's decision counts it as published after the close — and only
    for a page that writes no publish time of that day (one outside the window, :func:`stamped` found none inside:
    that time dates it, never its numbers)."""
    if w.close is None or day != w.cutoff.date() or w.now < datetime.combine(day, CLOSE_TIME, TAIPEI):
        return None
    if next(publish_times(day, texts, titles), None) is not None:
        return None
    return close_numbers(texts, w.close)[0]


def _num_raw(text: str, n: Any) -> str:
    from forliosa.reports.validate import normalize

    t = normalize(text)
    m = re.match(r"[\d.]+", t[n.start:].lstrip("+-▲▼ "))
    return m.group(0) if m else ""


_MAIN_NUM = re.compile(r"[+\-▲▼]?\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<mult>兆|億|萬)?\s*(?P<unit>%|元)?")


def _main_raw(key: str, claim: str, nums: list[Any]) -> str | None:
    """The number of ``claim`` a disagreement compares (:func:`disagreements`): the first amount in 億元 for the
    institutional flows and the turnover, the first percentage for the night session and the ADR — not merely the first
    number (the third dry run compared 「今（17）日」's 17 with 「上下振盪1747.39點」 and published 「鉅亨網寫 1747.39
    億元，經濟日報寫 17 億元」). ``None`` without one: that fact is compared with nothing."""
    from forliosa.reports.validate import normalize

    money = key.startswith("TWSE_INST.") or key == "TW.turnover_media"
    t = normalize(claim)
    for n in nums:
        m = _MAIN_NUM.match(t, n.start)
        if m is None:
            continue
        if money and m.group("mult") == "億" and m.group("unit") in ("元", None):
            return m.group("num")
        if not money and m.group("unit") == "%" and not m.group("mult"):
            return m.group("num")
    return None


def _main_number(fact: dict[str, Any]) -> str | None:
    if "main" in fact:
        return fact["main"]
    return fact["numbers"][0] if fact.get("numbers") else None  # a fact kept before 2026-11-18


def _agree(a: str, b: str) -> bool:
    """Two written numbers agree when the more precise one rounds to the other (9,617.95 and 9,618 億元 are one
    turnover; 179.62 and 179.63 are not)."""
    da = len(a.split(".", 1)[1]) if "." in a else 0
    db = len(b.split(".", 1)[1]) if "." in b else 0
    coarse, fine = (a, b) if da <= db else (b, a)
    places = Decimal(1).scaleb(-min(da, db))
    return Decimal(fine).quantize(places, rounding=ROUND_HALF_UP) == Decimal(coarse).quantize(places)


def disagreements(facts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Facts of a numeric key whose main numbers (:func:`_main_raw`) differ beyond rounding (:func:`_agree`): the
    first outlet in :data:`OUTLET_PRIORITY` stays, the others move to the disagreements (never cited)."""
    by_key: dict[str, list[dict[str, Any]]] = {}
    for f in facts:
        if any(f["key"] == k or (k.endswith(".") and f["key"].startswith(k)) for k in NUMERIC_KEYS) \
                and _main_number(f):
            by_key.setdefault(f["key"], []).append(f)
    drop_ids: set[int] = set()
    out: list[dict[str, Any]] = []
    for key, group in by_key.items():
        def rank(f: dict[str, Any]) -> int:
            return OUTLET_PRIORITY.index(f["outlet"]) if f["outlet"] in OUTLET_PRIORITY else len(OUTLET_PRIORITY)

        group = sorted(group, key=rank)
        kept = group[0]
        others = [f for f in group[1:] if not _agree(str(_main_number(f)), str(_main_number(kept)))]
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
        if (n := sum(f.get("dated_by") == "matched_close_numbers" for f in kept)):
            row["accepted"] = {"matched_close_numbers": n}  # same-day pages dated by their numbers (Option A)
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
                  datetime.fromisoformat(pack["cutoff"]).astimezone(TAIPEI), sessions, now, close_data(pack))


def for_writer(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The X facts as the data pack carries them (quotes included: the writer and the validator need them)."""
    keys = ("id", "topic", "key", "subject", "claim", "outlet", "title", "url", "published_at", "date_only", "numbers",
            "us_session", "quote")
    return [{k: f.get(k) for k in keys} for f in facts]
