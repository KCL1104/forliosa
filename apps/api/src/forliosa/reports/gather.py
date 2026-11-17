"""The gathering (contract §8): named media reports of what happened and what is scheduled, found by web search
(Claude Sonnet 5.5 at low effort, the report's allowed domains only, the repo's ``web_search_20260318`` without dynamic
filtering) — one call per topic with a quota the server sets, up to four topics at a time.

Each reply is cut into facts (``[KEY] 〔媒體〕報導，…`` paragraphs with their citations) and every fact is checked
(:func:`verify`): the cited page was among this call's search results, on an allowed domain, published inside the
edition's window (an undated page, or a page dated only by day on the cut-off's own day, is dropped), the citation is
a passage of the article (not a 「相關新聞」 list), every number is in a cited passage, a US / ADR / night-session fact
names its US trading day, no index points, no ratings or target prices. What is kept becomes an X fact for the writer
(its ``quote`` stays on the server side: the API never returns it). When outlets disagree on a number of the same
key, one fixed outlet wins and the others are listed as a disagreement (:data:`OUTLET_PRIORITY`).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from forliosa.ai.analyst import date_from_url, datetime_from_page_age, search_results
from forliosa.ai.market_summary import _norm_url
from forliosa.news.outlets import host_of, on_domain, outlet_name
from forliosa.reports import calls
from forliosa.reports.prompts import GATHER_SYSTEM, LONG_HOLIDAY_EXTRA, TOPICS, key_allowed, topic_brief
from forliosa.reports.validate import INDEX_POINTS, numbers
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
RATING = re.compile(r"目標價|評等|調升至|調降至|買進評等")
US_DATE = re.compile(r"美股\s*(\d{1,2})/(\d{1,2})")
KEY_LINE = re.compile(r"^\s*\[([A-Za-z0-9_.\-]+)\]\s*(.+)$", re.DOTALL)


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


def topics_for(kind: str, pack: dict[str, Any], *, long_holiday: bool = False) -> list[Topic]:
    w = pack.get("web_window") or {}
    window = (str(w.get("from") or ""), str(w.get("to") or ""))
    us = [f"{d[5:7].lstrip('0')}/{d[8:10].lstrip('0')}" for d in (pack.get("dates") or {}).get("us_sessions") or []]
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
                                              us_sessions=us, names=names), keys))
    return out


# -- calling ------------------------------------------------------------------------------------------------------
def request_for(topic: Topic, model: str, effort: str, messages: list[dict[str, Any]], settings: Any = None,
                continuation: bool = False) -> dict[str, Any]:
    return calls.request(model=model, max_tokens=MAX_TOKENS, effort=effort, system=GATHER_SYSTEM, messages=messages,
                         tools=[calls.web_search_tool(topic.quota)], settings=settings, continuation=continuation)


def call_topic(topic: Topic, model: str, effort: str, call: Callable[[dict[str, Any], int | None], tuple[Any, int]],
               settings: Any = None) -> TopicResult:
    """One topic: the first call, then up to three ``pause_turn`` continuations on the same slot (the reply sent back
    as it came). ``call(kw, only)`` runs the request on a key slot and returns ``(CallResult, slot)``."""
    res = TopicResult(topic)
    messages: list[dict[str, Any]] = [{"role": "user", "content": topic.brief}]
    try:
        for i in range(MAX_CONTINUATIONS + 1):
            kw = request_for(topic, model, effort, messages, settings, continuation=i > 0)
            out, slot = call(kw, res.slot)
            res.slot = slot
            res.msgs.append(out.msg)
            res.seconds += out.seconds
            if getattr(out.msg, "stop_reason", None) != "pause_turn":
                break
            messages = [*messages, {"role": "assistant",
                                    "content": [b.to_dict(mode="json") if hasattr(b, "to_dict") else b
                                                for b in out.msg.content]}]
    except Exception as exc:  # one topic failing never stops the others
        res.error = type(exc).__name__
        log.warning("market report gathering: topic %s failed (%s)", topic.name, res.error)
    return res


def run_topics(topics: list[Topic], model: str, effort: str,
               call: Callable[[dict[str, Any], int | None], tuple[Any, int]], settings: Any = None,
               threads: int | None = None) -> list[TopicResult]:
    threads = TOPIC_THREADS if threads is None else threads
    if threads <= 1 or len(topics) <= 1:
        return [call_topic(t, model, effort, call, settings) for t in topics]
    with ThreadPoolExecutor(max_workers=min(threads, len(topics)), thread_name_prefix="mreport-gather") as ex:
        return list(ex.map(lambda t: call_topic(t, model, effort, call, settings), topics))


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
    us_sessions: set[date]
    now: datetime


def _related_headline(cited: str, titles: list[str], own: str) -> bool:
    c = cited.strip()
    if len(c) < 20:
        return True
    lines = [x for x in c.splitlines() if x.strip()]
    if len(lines) >= 3 and all(len(x.strip()) < 30 for x in lines):
        return True
    for t in titles:
        t = t.strip()
        if t and t != own.strip() and len(t) >= 12:
            for i in range(0, len(t) - 11):
                if t[i:i + 12] in c:
                    return True
    return False


def _published(url: str, page_age: str | None, now: datetime) -> datetime | date | None:
    found = datetime_from_page_age(page_age, now)
    if found is not None:
        return found
    return date_from_url(url)


def _us_date_ok(claim: str, w: Window) -> date | None:
    for m in US_DATE.finditer(claim):
        mo, d = int(m.group(1)), int(m.group(2))
        for y in (w.cutoff.year, w.cutoff.year - 1):
            try:
                x = date(y, mo, d)
            except ValueError:
                continue
            if x <= w.cutoff.date() and is_us_trading_day(x):
                return x
    return None


def verify(key: str, claim: str, cites: list[dict[str, Any]], results: dict[str, Any], w: Window,
           allowed: tuple[str, ...]) -> tuple[dict[str, Any] | None, str | None]:
    """A checked fact (without its id) or the reason it was dropped."""
    if not key_allowed(key, allowed):
        return None, "bad_key"
    if not cites:
        return None, "no_citation"
    titles = [r.title for r in results.values()]
    valid: list[tuple[dict[str, Any], Any]] = []
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
        if _related_headline(str(c.get("cited_text") or ""), titles, str(c.get("title") or r.title)):
            reason = reason or "related_headline"
            continue
        valid.append((c, r))
    if not valid:
        return None, reason or "no_citation"
    # freshness: the first valid citation's page
    c0, r0 = valid[0]
    pub = _published(str(c0.get("url")), r0.page_age, w.now)
    if pub is None:
        return None, "time_unknown"
    if isinstance(pub, datetime):
        if not w.start <= pub <= w.end:
            return None, "outside_window"
    elif not pub < w.cutoff.date():
        return None, "outside_window"
    quotes = " ".join(str(c.get("cited_text") or "") for c, _ in valid)
    claim_nums = numbers(claim)
    quote_nums = numbers(quotes)
    if any(not any(abs(n.value - q.value) <= n.tol + 1e-9 for q in quote_nums) for n in claim_nums):
        return None, "number_not_in_quote"
    us_session = None
    if key.startswith(("US.", "ADR.", "NIGHT.")):
        us_session = _us_date_ok(claim, w)
        if us_session is None:
            return None, "no_us_session_date"
    if INDEX_POINTS.search(claim):
        return None, "index_points"
    if RATING.search(claim):
        return None, "rating"
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


def collect(results: list[TopicResult], w: Window) -> Outcome:
    """Parse and check every topic's replies; number the kept facts X001… by topic, in order."""
    facts: list[dict[str, Any]] = []
    topics: list[dict[str, Any]] = []
    for res in results:
        content = [b for m in res.msgs for b in (getattr(m, "content", None) or [])]
        found = {_norm_url(r.url): r for r in search_results(content)}
        dropped: dict[str, int] = {}
        kept: list[dict[str, Any]] = []
        for text, cites in paragraphs(content):
            m = KEY_LINE.match(text)
            if m is None:
                continue
            fact, why = verify(m.group(1), m.group(2).strip(), cites, found, w, res.topic.keys)
            if fact is None:
                dropped[why or "other"] = dropped.get(why or "other", 0) + 1
                continue
            if len(kept) >= MAX_PER_TOPIC:
                dropped["limit"] = dropped.get("limit", 0) + 1
                continue
            fact["topic"] = res.topic.name
            kept.append(fact)
        facts.extend(kept)
        topics.append({"topic": res.topic.name, "quota": res.topic.quota, "results": len(found), "kept": len(kept),
                       "dropped": dropped, "error": res.error, "seconds": round(res.seconds, 1)})
    facts, disagree = disagreements(facts)
    for i, f in enumerate(facts, start=1):
        f["id"] = f"X{i:03d}"
    return Outcome(facts, disagree, topics, results)


def window(pack: dict[str, Any], now: datetime) -> Window:
    w = pack.get("web_window") or {}
    sessions = {date.fromisoformat(d) for d in (pack.get("dates") or {}).get("us_sessions") or []}
    return Window(datetime.fromisoformat(w["from"]).astimezone(TAIPEI),
                  datetime.fromisoformat(w["to"]).astimezone(TAIPEI),
                  datetime.fromisoformat(pack["cutoff"]).astimezone(TAIPEI), sessions, now)


def for_writer(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The X facts as the data pack carries them (quotes included: the writer and the validator need them)."""
    keys = ("id", "topic", "key", "subject", "claim", "outlet", "title", "url", "published_at", "date_only", "numbers",
            "us_session", "quote")
    return [{k: f.get(k) for k in keys} for f in facts]
