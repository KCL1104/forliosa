"""Shared research behind 「X 今天為什麼漲／跌」 chat answers (產品負責人 2026-11-16).

A why-question took about 19 s and US$0.02–0.05: nearly all of it is the one model call that searches the web two to
four times and thinks about what it found. The research itself is the same for everyone who asks about the same stock
on the same day, so it is kept once (``ai_why_research``) and handed to the next asker's turn.

What is shared — market-level research only, never anyone's holdings, costs, account data, messages or answer text:

* ``facts``: the market-level part of the cold turn's ``get_stock_overview`` result for that symbol (the official
  close and its move, the TAIEX and sector index closes, the gap to the TAIEX, the rule-based anomalies, the English
  name). Tool output, not the model's words.
* ``sources`` (at most 8): what the answer cited (web search, web fetch, the news tool), as url, title, the cited
  passages, outlet, page age and when it was found; then search results the answer did not cite whose title names the
  company (title only: the API returns their text encrypted). Raw ``web_search_result`` blocks are never replayed:
  their ``encrypted_content`` is valid only on the key slot (workspace) that searched.
* ``one_liner``: the stock page's AI sentence (``ai.why``), with its citations among the sources.

Key: (symbol, session, phase). ``intraday`` while that market trades (Taiwan 09:00–13:30, New York 09:30–16:00) —
reused ``AI_RESEARCH_INTRADAY_MINUTES`` (45); ``after_close`` from the close until the next session opens — but one
written before the session's own close was stored (``prices_daily``: the official file, TWSE's same-day file or the
interim evening close) ends when it is, so answers after it use the close. No Redis: one API process, and a primary-key
read of PostgreSQL per why-question is well under the turn's other costs.

Read (``lookup``): a why-question (為什麼／為啥／怎麼了／原因 … with 漲／跌 …) about one stock — named in the message
(code, name, alias, nickname, ticker) or, when the message names none, the stock page's — on this session, not in
深度搜尋. A fresh entry goes into the turn as citable ``search_result`` blocks before the user's text (``blocks``; the
API cites them as ``search_result_location``, which the chat turn already shows like a web citation and the grounding
check counts as cited) and the facts plus a short rule in the turn's system message (``note``): answer from it, search
again only for newer news, a missing price or index move, or (intraday) a missing company reason.

Write (``remember``): after a successful turn of such a question that used web search, best effort (a failure is
logged, never the turn's). A turn that answered from the entry without searching writes nothing, so its time to live
still counts from the research. The stock page's sentence seeds the entry of its session (``seed_from_why``).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from forliosa.config import Settings
from forliosa.marketdata.base import InstrumentInfo, market_of_symbol
from forliosa.marketdata.service import MarketData
from forliosa.models import AiWhyResearch, PriceDaily
from forliosa.timeutil import (
    MARKET_CLOSE,
    MARKET_OPEN,
    NEW_YORK,
    TAIPEI,
    US_CLOSE,
    is_tw_market_open,
    is_tw_trading_day,
    is_us_trading_day,
    last_tw_trading_day,
    last_us_session,
    next_tw_trading_day,
)

log = logging.getLogger(__name__)

INTRADAY, AFTER_CLOSE = "intraday", "after_close"
US_OPEN = time(9, 30)
MAX_SOURCES = 8
MAX_SNIPPETS = 3  # cited passages kept per source
SNIPPET_CHARS = 400
TITLE_CHARS = 200
PURGE_AFTER = timedelta(days=3)  # expired rows are deleted this long after they ended
# The market-level fields of ``get_stock_overview`` kept as facts (not its summary, themes, valuation, dividends, or
# the intraday note, which depends on the time it is read: ``note`` writes its own)
FACT_KEYS = ("symbol", "name", "market", "industry", "english_name", "quote", "market_context", "why_signals")


# -- the key ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Key:
    symbol: str
    market: str  # TWSE | TPEX | US
    session: date  # the market's own date of the session (New York's for a US stock)
    phase: str  # intraday | after_close


def key_for(symbol: str, now: datetime) -> Key:
    """The session a question asked at ``now`` is about: the one trading now (intraday), else the latest one whose
    close has passed (after_close; before the open that is the previous session)."""
    market = market_of_symbol(symbol)
    if market == "US":
        ny = now.astimezone(NEW_YORK)
        if is_us_trading_day(ny.date()) and US_OPEN <= ny.time() < US_CLOSE:
            return Key(symbol, market, ny.date(), INTRADAY)
        return Key(symbol, market, last_us_session(now), AFTER_CLOSE)
    at = now.astimezone(TAIPEI)
    if is_tw_market_open(at):
        return Key(symbol, market, at.date(), INTRADAY)
    d = at.date()
    if not (is_tw_trading_day(d) and at.time() >= MARKET_CLOSE):
        d -= timedelta(days=1)
    return Key(symbol, market, last_tw_trading_day(d), AFTER_CLOSE)


def next_open(key: Key) -> datetime:
    """When the session after ``key.session`` opens."""
    if key.market == "US":
        d = key.session + timedelta(days=1)
        while not is_us_trading_day(d):
            d += timedelta(days=1)
        return datetime.combine(d, US_OPEN, NEW_YORK)
    return datetime.combine(next_tw_trading_day(key.session + timedelta(days=1)), MARKET_OPEN, TAIPEI)


def expires_for(key: Key, now: datetime, settings: Settings) -> datetime:
    if key.phase == INTRADAY:
        return now + timedelta(minutes=settings.ai_research_intraday_minutes)
    return next_open(key)


def close_stored(db: Session, symbol: str, session: date) -> bool:
    """The session's close of ``symbol`` is in ``prices_daily`` (official, TWSE's same-day file or the interim evening
    close)."""
    return db.get(PriceDaily, (symbol, session)) is not None


# -- the question ----------------------------------------------------------------------------------------------
_WHY = re.compile(r"為什麼|為甚麼|為何|為啥|怎麼了|怎麼回事|怎麼會|什麼原因|啥原因|原因|理由|幹嘛|發生什麼|發生了什麼|"
                  r"出了什麼事|啥事")
_MOVE = re.compile(r"漲|跌|崩|噴|飆|挫|殺|拉回|走弱|走強|翻黑|翻紅|大紅|大綠|爆量")
_WHAT_HAPPENED = re.compile(r"怎麼了|怎麼回事|發生什麼|發生了什麼|出了什麼事|啥事")
# Another period than the session (a multi-day move, last week, a month): today's research does not answer it
_N = r"[\d一二兩三四五六七八九十]+"
_OTHER_TIME = re.compile(r"前天|上週|上周|上禮拜|上星期|這週|這周|本週|本周|這禮拜|這星期|這個月|本月|上個月|今年|去年|"
                         r"半年|一年|最近|近期|近日|這陣子|這幾天|這兩天|這幾週|幾個月|幾週|"
                         rf"連(?:續)?(?:漲|跌|紅|黑|殺|噴)?\s*{_N}\s*(?:天|日|根|週|周)|{_N}\s*(?:天|週|周|個月|年)(?:來|以來|內)")
_YESTERDAY = re.compile(r"昨天|昨日")
_DATE = re.compile(r"(?<![\d.])(1[0-2]|0?[1-9])\s*(?:/|月)\s*(3[01]|[12]\d|0?[1-9])(?:\s*[日號])?(?![\d/])")
# Words that make a question about the market or the user's own portfolio, not the stock of the page
_NOT_THE_PAGE = re.compile(r"大盤|加權|指數|台股|美股|股市|市場|類股|族群|產業|整體|持股|組合|帳戶|帳本|我的股票")
_CODE = re.compile(r"(?<![\dA-Za-z.])(\d{4,6}[A-Za-z]?)(?:\.TWO?|\.tw|\.two|-TW)?(?!\d)")
_TICKER = re.compile(r"(?<![A-Za-z0-9.])([A-Za-z]{2,5}(?:\.[A-Za-z])?)(?![A-Za-z0-9])")
_NOT_TICKERS = frozenset({"AI", "ETF", "ETFS", "ADR", "EPS", "KD", "RSI", "MACD", "MA", "USD", "TWD", "TAIEX", "OK",
                          "PE", "PB", "IPO", "CEO", "GDP", "CPI", "FED", "FOMC", "TSE", "OTC", "API", "APP", "NEWS"})
_NUMBER_BEFORE = set("到在收破跌漲站價剩回")
_NUMBER_AFTER = set("元點塊%％張萬億")
_MAX_NAME = 12
_names: tuple[int, int, dict[str, str]] | None = None  # (id, size) of the master it was built from, name -> symbol


def is_why_question(message: str) -> bool:
    """「台達電今天為啥跌這麼多?」「為什麼漲停」「聯發科怎麼了」: a why word with a move word, or 「怎麼了」 alone."""
    return bool((_WHY.search(message) and _MOVE.search(message)) or _WHAT_HAPPENED.search(message))


def fits_session(message: str, key: Key, now: datetime) -> bool:
    """The question is about ``key.session``: no other period, 「昨天」 only before the next session opens (the session
    was yesterday), and a date it names is the session's."""
    if _OTHER_TIME.search(message):
        return False
    if _YESTERDAY.search(message) and not (key.phase == AFTER_CLOSE and key.session < now.astimezone(TAIPEI).date()):
        return False
    return all((int(m.group(1)), int(m.group(2))) == (key.session.month, key.session.day)
               for m in _DATE.finditer(message))


def _name_index(md: MarketData) -> dict[str, str]:
    """Chinese names, aliases and nicknames of every instrument → symbol (Taiwan first when two share one), built once
    per instrument master."""
    global _names
    master = md.master()
    if _names is not None and _names[:2] == (id(master), len(master)):
        return _names[2]
    from forliosa.ai.tools import NICKNAMES

    found: dict[str, set[str]] = {}
    for sym, info in master.items():
        for n in (info.name, *info.aliases):
            n = (n or "").strip()
            if len(n) >= 2 and not n.isascii():
                found.setdefault(n, set()).add(sym)
    for nick, code in NICKNAMES.items():
        if not nick.isascii() and (sym := md.resolve(code)):
            found.setdefault(nick, set()).add(sym)
    index = {n: min(syms, key=lambda s: (market_of_symbol(s) == "US", s)) for n, syms in found.items()}
    _names = (id(master), len(master), index)
    return index


def symbols_in(md: MarketData, message: str) -> list[str]:
    """The stocks a message names, in order: codes (2308, 2308.TW), tickers (NVDA), and the longest Chinese name,
    alias or nickname at each position (「台達電今天…」 → 2308.TW). Exact names only: no prefix or fuzzy match."""
    out: list[str] = []

    def add(sym: str | None) -> None:
        if sym and sym not in out:
            out.append(sym)

    for m in _CODE.finditer(message):
        # a price or a point count is not a code (「跌到 1240」「跌 1336 點」)
        before, after = message[:m.start()].rstrip()[-1:], message[m.end():].lstrip()[:1]
        if before not in _NUMBER_BEFORE and after not in _NUMBER_AFTER:
            add(md.resolve(m.group(1)))
    for m in _TICKER.finditer(message):
        t = m.group(1).upper()
        if t not in _NOT_TICKERS and (sym := md.resolve(t)) and market_of_symbol(sym) == "US":
            add(sym)
    index = _name_index(md)
    i = 0
    while i < len(message):
        for n in range(min(_MAX_NAME, len(message) - i), 1, -1):
            sym = index.get(message[i:i + n])
            if sym:
                add(sym)
                i += n
                break
        else:
            i += 1
    return out


def detect(md: MarketData, message: str, page_symbol: str | None,
           now: datetime) -> tuple[Key, InstrumentInfo] | None:
    """The (key, instrument) of a why-question about one stock on the current session, else None. The stock is the
    one the message names; with none named, the page's (unless the message is about the market or the portfolio)."""
    if not is_why_question(message):
        return None
    named = symbols_in(md, message)
    if len(named) > 1:
        return None
    sym = named[0] if named else (page_symbol if page_symbol and not _NOT_THE_PAGE.search(message) else None)
    info = md.instrument(sym) if sym else None
    if info is None or info.market not in ("TWSE", "TPEX", "US"):
        return None
    key = key_for(info.symbol, now)
    return (key, info) if fits_session(message, key, now) else None


# -- reading -----------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Research:
    """A fresh entry, detached from the database session."""

    facts: dict[str, Any] | None
    sources: list[dict[str, Any]]
    one_liner: str | None
    updated_at: datetime
    searches: int


@dataclass
class Lookup:
    key: Key
    info: InstrumentInfo
    entry: Research | None = None  # None: nothing fresh, this turn researches (and ``remember`` stores it)
    hits: list[str] = field(default_factory=list)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=TAIPEI)


def is_fresh(db: Session, row: AiWhyResearch, now: datetime) -> bool:
    if not row.sources or _aware(row.expires_at) <= now:
        return False
    # written after the close but before it was stored: the close is in now, so the research is redone with it
    return not (row.phase == AFTER_CLOSE and not row.close_in and close_stored(db, row.symbol, row.session))


def lookup(db: Session, md: MarketData, message: str, page_symbol: str | None, now: datetime) -> Lookup | None:
    """The why-question's key and, when there is one, the fresh entry (its ``hits`` counted)."""
    found = detect(md, message, page_symbol, now)
    if found is None:
        return None
    key, info = found
    row = db.get(AiWhyResearch, (key.symbol, key.session, key.phase))
    if row is None or not is_fresh(db, row, now):
        return Lookup(key, info)
    entry = Research(facts=row.facts, sources=list(row.sources or []), one_liner=row.one_liner,
                     updated_at=_aware(row.updated_at), searches=row.searches or 0)
    db.execute(update(AiWhyResearch).where(AiWhyResearch.symbol == key.symbol, AiWhyResearch.session == key.session,
                                           AiWhyResearch.phase == key.phase)
               .values(hits=AiWhyResearch.hits + 1))
    db.commit()
    return Lookup(key, info, entry)


def _host(url: str) -> str:
    return (urlsplit(url).hostname or url).removeprefix("www.")


def blocks(entry: Research) -> list[dict[str, Any]]:
    """The sources as citable ``search_result`` blocks (citations on, as every search result of a request with web
    search must be), each cited passage a block of its own (a citation covers whole blocks)."""
    return [{"type": "search_result", "source": s["url"], "title": s.get("title") or _host(s["url"]),
             "content": [{"type": "text", "text": t} for t in (s.get("snippets") or [s.get("title") or s["url"]])],
             "citations": {"enabled": True}}
            for s in entry.sources]


def outlets(entry: Research) -> dict[str, str]:
    return {s["url"]: s["outlet"] for s in entry.sources if s.get("outlet")}


def _md(d: date | str) -> str:
    d = date.fromisoformat(str(d)[:10])
    return f"{d.month}/{d.day}"


def label(entry: Research) -> str:
    """The turn's step in the AI panel (a ``tool`` event)."""
    return f"沿用 {entry.updated_at.astimezone(TAIPEI):%H:%M} 查好的資料"


def _num(x: Any) -> str:
    return f"{float(x):,.2f}".rstrip("0").rstrip(".")


def _facts_lines(found: Lookup) -> list[str]:
    """The official numbers: all of them when they are the session's own close; otherwise only the latest close (to
    measure the session's move from), said to be older. 2026-11-16 live check: the previous day's index move and
    anomalies beside today's searched numbers made the model deliberate longer and once compare the wrong days."""
    facts = (found.entry.facts if found.entry else None) or {}
    quote = facts.get("quote") or {}
    td, session = quote.get("trade_date"), found.key.session
    if td and str(td) >= session.isoformat():
        keep = {k: facts[k] for k in ("quote", "market_context", "why_signals") if k in facts}
        return ["  官方收盤數字（get_stock_overview，不用引用）："
                + json.dumps(keep, ensure_ascii=False, separators=(",", ":"))]
    lines = []
    s = _md(session)
    if td and quote.get("price") is not None:
        price = f"US${_num(quote['price'])}" if found.info.currency == "USD" else f"{_num(quote['price'])} 元"
        lines.append(f"  最新的官方收盤是 {_md(td)} 的 {price}（不是 {s} 的）。")
    if found.key.phase == INTRADAY:
        lines.append(f"  盤中：{s} 這一檔與大盤漲跌多少看搜尋結果，寫出來源的時間。")
    else:
        where = "（官方收盤價什麼時候更新照「台股收盤價」那一行寫）" if found.key.market != "US" else ""
        lines.append(f"  {s} 的官方收盤價還沒進來：{s} 漲跌多少看搜尋結果並寫出來源的時間{where}。")
    return lines


def note(found: Lookup) -> str:
    """The rule and the facts, for the turn's system message (beside the page context)."""
    entry = found.entry
    assert entry is not None
    info, key = found.info, found.key
    when = "盤中" if key.phase == INTRADAY else "收盤後"
    at = entry.updated_at.astimezone(TAIPEI)
    again = "使用者要更新的消息、研究裡缺這一檔或大盤今天的漲跌"
    if key.phase == INTRADAY:
        again += "，或研究裡沒有這家公司自己的原因"
    lines = [
        f"- 今天的共用研究：{info.name}（{info.symbol}）{_md(key.session)}{when}為什麼漲跌，{at:%H:%M} 有人問過、"
        f"已經查好（全站共用，和這位使用者的資料無關）。使用者訊息前面附了 {len(entry.sources)} 筆可引用的搜尋結果"
        + ("，下面是數字。" if entry.facts else "。"),
        "  1. 直接用這些資料回答並引用那些搜尋結果，照「為什麼漲跌」的寫法："
        "先寫這一檔和加權指數各漲跌多少，再寫公司自己的原因；研究裡沒有公司自己的消息就照實說找不到。",
        f"  2. 不用再呼叫 {'get_stock_overview、' if entry.facts else ''}get_news 或 web_search；只有{again}時，才再用"
        " web_search 找。問題的其他部分（持股、技術面、記帳）照平常用工具。",
    ]
    lines += _facts_lines(found)
    if entry.one_liner:
        lines.append(f"  個股頁的 AI 一句話（出處在搜尋結果裡）：{entry.one_liner}")
    listed = []
    for i, s in enumerate(entry.sources, 1):
        bits = [s.get("outlet") or _host(s["url"])]
        if s.get("page_age"):
            bits.append(f"頁面時間 {s['page_age']}")
        if s.get("found_at"):
            bits.append(f"{_md(s['found_at'])} {s['found_at'][11:16]} 找到")
        if not s.get("snippets"):
            bits.append("只有標題")
        listed.append(f"{i}. {s.get('title') or _host(s['url'])}（{'，'.join(bits)}）")
    lines.append("  搜尋結果依序是：" + "；".join(listed))
    return "\n".join(lines)


# -- writing -----------------------------------------------------------------------------------------------------
def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


def _web(messages: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    """How many web searches the turn ran, and every result they returned (url, title, page age)."""
    searches, results = 0, []
    for m in messages:
        if m.get("role") != "assistant" or not isinstance(m.get("content"), list):
            continue
        for b in m["content"]:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "server_tool_use" and b.get("name") == "web_search":
                searches += 1
            elif b.get("type") == "web_search_tool_result" and isinstance(b.get("content"), list):
                results += [{"url": r.get("url"), "title": _clean(r.get("title")), "page_age": r.get("page_age")}
                            for r in b["content"] if isinstance(r, dict) and r.get("type") == "web_search_result"
                            and str(r.get("url") or "").startswith("http")]
    return searches, results


def facts_from(messages: list[dict[str, Any]], symbol: str) -> dict[str, Any] | None:
    """The market-level fields of this turn's last ``get_stock_overview`` result for ``symbol``."""
    ids = {b.get("id") for m in messages if m.get("role") == "assistant" and isinstance(m.get("content"), list)
           for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_use"
           and b.get("name") == "get_stock_overview"}
    out = None
    for m in messages:
        if m.get("role") != "user" or not isinstance(m.get("content"), list):
            continue
        for b in m["content"]:
            if not (isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in ids
                    and not b.get("is_error") and isinstance(b.get("content"), str)):
                continue
            try:
                data = json.loads(b["content"])
            except ValueError:  # cut at the tool's length limit
                continue
            if isinstance(data, dict) and data.get("symbol") == symbol:
                out = {k: data[k] for k in FACT_KEYS if data.get(k) not in (None, [], {}, "")}
    return out


_INDEX_WORDS = {
    "TW": re.compile(r"加權|大盤|台股|集中市場|櫃買|指數|TAIEX", re.IGNORECASE),
    "US": re.compile(r"S&P|Nasdaq|Dow|標普|那斯達克|道瓊|美股|大盤|指數", re.IGNORECASE),
}


def _mentions(text: str, names: list[str]) -> bool:
    low = text.lower()
    return any(n and n.lower() in low for n in names)


def sources_from(citations: list[dict[str, Any]], results: list[dict[str, Any]], outlets_by_url: dict[str, str],
                 info: InstrumentInfo, facts: dict[str, Any] | None, now: datetime) -> list[dict[str, Any]]:
    """What the answer cited (passages kept, company and index sources first), then search results whose title names
    the company. Only http(s) sources; never anything of the user's."""
    names = [info.name, info.code, *(a for a in info.aliases if len(a) >= 2)]
    if facts and facts.get("english_name"):
        names.append(str(facts["english_name"]))
    index_words = _INDEX_WORDS["US" if info.market == "US" else "TW"]
    ages = {r["url"]: r.get("page_age") for r in results}
    found_at = now.astimezone(TAIPEI).isoformat(timespec="minutes")
    cited: dict[str, dict[str, Any]] = {}
    for c in citations:
        url = str(c.get("url") or "")
        if not url.startswith("http"):
            continue
        s = cited.setdefault(url, {"url": url, "title": _clean(c.get("title"))[:TITLE_CHARS], "snippets": [],
                                   "outlet": c.get("outlet") or outlets_by_url.get(url), "page_age": ages.get(url),
                                   "found_at": found_at})
        text = _clean(c.get("cited_text"))[:SNIPPET_CHARS]
        if text and text not in s["snippets"] and len(s["snippets"]) < MAX_SNIPPETS:
            s["snippets"].append(text)

    def rank(s: dict[str, Any]) -> int:
        body = " ".join([s["title"], *s["snippets"]])
        return 0 if _mentions(body, names) else 1 if index_words.search(body) else 2

    out = sorted(cited.values(), key=rank)
    # Uncited results whose title names the company (or, when nothing cited covers the index, the market): news of
    # the day first, quote pages and forums never. 2026-11-16 live check: 「盤中速報 - 台達電(2308)股價殺至跌停」 was
    # the 25th result; taken in search order, the entry held two copies of a 13-day-old story instead.
    need_index = not any(rank(s) == 1 for s in out)
    titles = {s["title"] for s in out}
    extra = []
    for i, r in enumerate(results):
        title = r["title"]
        if r["url"] in cited or not title or title in titles or _NOT_NEWS.search(r["url"]) \
                or _NOT_NEWS.search(title):
            continue
        company = _mentions(title, names)
        if not (company or (need_index and index_words.search(title))):
            continue
        titles.add(title)
        age = _age_days(r.get("page_age"), now)
        extra.append(((not company, age > 1, age, not _MOVE.search(title), i), r))
    for _, r in sorted(extra, key=lambda x: x[0]):
        out.append({"url": r["url"], "title": r["title"][:TITLE_CHARS], "snippets": [], "outlet": None,
                    "page_age": r.get("page_age"), "found_at": found_at})
    return out[:MAX_SOURCES]


# Quote pages, charts and forums: not news (their titles say nothing about why)
_NOT_NEWS = re.compile(r"/forum|/quote|google\.com/finance|/INDEX/|/stock/\d+/?$|討論|走勢圖|股價與新聞|行情",
                       re.IGNORECASE)
_AGE = re.compile(r"(\d+)\s*(minute|hour|day|week|month|year)s?\s+ago", re.IGNORECASE)
_AGE_DAYS = {"minute": 1 / 1440, "hour": 1 / 24, "day": 1, "week": 7, "month": 30, "year": 365}


def _age_days(page_age: Any, now: datetime) -> float:
    """「3 hours ago」「2 days ago」「November 16, 2026」 → days before ``now`` (999 when unknown)."""
    text = str(page_age or "").strip()
    if m := _AGE.search(text):
        return int(m.group(1)) * _AGE_DAYS[m.group(2).lower()]
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return float((now.astimezone(TAIPEI).date() - datetime.strptime(text, fmt).date()).days)
        except ValueError:
            continue
    return 999.0


def _merge(first: list[dict[str, Any]], then: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out, seen = [], set()
    for s in [*first, *then]:
        if isinstance(s, dict) and s.get("url") and s["url"] not in seen:
            seen.add(s["url"])
            out.append(s)
    return out[:MAX_SOURCES]


def _upsert(db: Session, key: Key, now: datetime, settings: Settings, *, sources: list[dict[str, Any]],
            facts: dict[str, Any] | None = None, one_liner: str | None = None, searches: int = 0,
            research: bool = True) -> AiWhyResearch:
    """``research``: new research done now (a chat turn): its sources go first and the entry counts from now. A seed
    (the stock page's sentence) only adds to an existing entry, after its sources."""
    for attempt in (1, 2):
        try:
            row = db.get(AiWhyResearch, (key.symbol, key.session, key.phase))
            new = row is None  # a new entry counts from now either way
            if row is None:
                row = AiWhyResearch(symbol=key.symbol, session=key.session, phase=key.phase, market=key.market,
                                    sources=[], searches=0, hits=0, close_in=False, created_at=now, updated_at=now,
                                    expires_at=expires_for(key, now, settings))
                db.add(row)
            row.sources = _merge(sources, list(row.sources or [])) if research \
                else _merge(list(row.sources or []), sources)
            if facts:
                row.facts = facts
            if one_liner:
                row.one_liner = one_liner
            if research or new:
                row.searches = (row.searches or 0) + searches
                row.close_in = close_stored(db, key.symbol, key.session)
                row.updated_at = now
                row.expires_at = expires_for(key, now, settings)
            db.execute(delete(AiWhyResearch).where(AiWhyResearch.expires_at < now - PURGE_AFTER))
            db.commit()
            return row
        except IntegrityError:  # another turn stored the same key meanwhile: merge into its row
            db.rollback()
            if attempt == 2:
                raise
    raise AssertionError("unreachable")  # pragma: no cover


def remember(db: Session, found: Lookup, messages: list[dict[str, Any]], citations: list[dict[str, Any]],
             outlets_by_url: dict[str, str], now: datetime, settings: Settings) -> AiWhyResearch | None:
    """Store what this turn's web search found for the stock (nothing when it did not search or found nothing)."""
    searches, results = _web(messages)
    if not searches:
        return None
    facts = facts_from(messages, found.key.symbol)
    sources = sources_from(citations, results, outlets_by_url, found.info, facts, now)
    if not sources:
        return None
    row = _upsert(db, found.key, now, settings, sources=sources, facts=facts, searches=searches)
    log.info("AI why research stored: %s %s %s (%d sources, %d searches)", found.key.symbol, found.key.session,
             found.key.phase, len(row.sources or []), searches)
    return row


def seed_from_why(db: Session, symbol: str, day: date, text: str, citations: list[dict[str, Any]], now: datetime,
                  settings: Settings) -> AiWhyResearch | None:
    """The stock page's sentence for ``day`` (``ai.why``, with its citations) joins that session's after-close entry
    while it can still be used."""
    key = Key(symbol, market_of_symbol(symbol), day, AFTER_CLOSE)
    if not text or not citations or next_open(key) <= now:
        return None
    found_at = now.astimezone(TAIPEI).isoformat(timespec="minutes")
    sources = [{"url": c["url"], "title": _clean(c.get("title"))[:TITLE_CHARS],
                "snippets": [t] if (t := _clean(c.get("cited_text"))[:SNIPPET_CHARS]) else [], "outlet": None,
                "page_age": None, "found_at": found_at}
               for c in citations if str(c.get("url") or "").startswith("http")]
    if not sources:
        return None
    return _upsert(db, key, now, settings, sources=sources, one_liner=text, research=False)
