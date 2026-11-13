"""The market page's AI summary of one Taiwan trading day (``GET /market/overview`` → ``summary``).

One entry per trading day, shared by everyone (table ``ai_market_summary``); nobody's quota is charged. The model
searches the web for that day's closing reports and answers only through ``report_market_summary``: a headline and
three to five points, each naming the search results it rests on. The server then keeps a point only when

* every address it shows is one of the search results the model actually received (no made-up links), and
* at least one of them is dated the trading day or within three days after it (``page_age`` or a date in the
  address) — a report from an earlier day cannot describe this session. Results dated before the day are dropped.

Fewer than two surviving points → nothing is shown (``empty``). The headline's direction is checked against the
official TAIEX change when the archive already has it; a contradicting headline is dropped, the points stay.

When it runs: the worker asks at 15:05, 18:05 and 22:05 on trading days (``Worker.market_summary``), and the first
visit of the market page after the close starts one in the background when the day has none. A failed or empty
answer is asked again later, at most ``MAX_ATTEMPTS`` times a day. Without a key, with web search off or with
``AI_MARKET_SUMMARY_ENABLED=false`` no model call is made and the page simply has no summary.

Cost (Claude Haiku 5.5 list prices, 2026-11-12): up to four searches (US$0.04) plus roughly 40K input tokens —
about US$0.05 a trading day.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.ai import store
from forliosa.ai.analyst import SearchResult, date_from_page_age, date_from_url, search_results
from forliosa.ai.keypool import KeyPool, get_key_pool
from forliosa.ai.pricing import CallUsage
from forliosa.ai.tools import exclude_tool, rejected_tool, server_tools
from forliosa.config import Settings, get_settings
from forliosa.db import session_factory
from forliosa.models import AiMarketSummary
from forliosa.news.outlets import outlet_name
from forliosa.timeutil import TAIPEI, is_tw_trading_day, now_taipei, now_utc

log = logging.getLogger(__name__)

FEATURE = "market_summary"
TOOL_NAME = "report_market_summary"
SESSION_OVER = time(14, 0)  # Taipei: the cash session ends 13:30, closing reports follow within minutes
SEARCH_MAX_USES = 4
MAX_CALLS = 4  # first call + pause_turn continuations + one nudge
MAX_TOKENS = 6000
MIN_POINTS, MAX_POINTS = 2, 5
MAX_HEADLINE_CHARS = 48
MAX_POINT_CHARS = 110
MAX_SOURCES = 3
MAX_TITLE_CHARS = 160
REPORT_WINDOW = timedelta(days=3)  # a Friday session is still written up over the weekend
MAX_ATTEMPTS = 4
RETRY_AFTER = timedelta(minutes=45)
PENDING_TIMEOUT = timedelta(minutes=5)
SHOW_FOR = timedelta(days=5)  # a summary older than this is not shown as "the latest"
EFFORT = "medium"
_WEEKDAYS = "一二三四五六日"

SYSTEM = """你是財經編輯，替 Forliosa 的「市場」頁整理一個交易日的台股收盤重點。Forliosa 只轉述報導，不提供自己的看法。

## 任務
用 web_search 找這個交易日台股收盤的報導，整理成一句標題和 3 到 5 個重點，最後呼叫 report_market_summary。這個工具呼叫是你唯一的輸出。

## 搜尋
- 用繁體中文關鍵字，帶上日期，例如「台股 收盤 11月12日」「加權指數 收盤」「台股 盤後 三大法人」；結果不夠就換關鍵字再搜。
- 採用通訊社與信譽良好的財經媒體（例如中央社、經濟日報、工商時報、鉅亨網）或交易所的公告。不採用論壇、社群貼文、內容農場、影音頻道，也不採用行情頁與盤前預測。
- 你的訓練資料比今天早很多：只根據這次搜尋到、寫的是這個交易日收盤的報導來寫，不要憑記憶補資料。日期更早的報導、還沒收盤時寫的盤中報導都不要用。

## 怎麼寫
- headline：一句話（30 個字以內）說這一天大盤怎麼走，例如「加權指數收漲 1.2%，電子股領漲」。指數的收盤與漲跌只能用使用者訊息裡的官方數字；訊息裡沒給就只寫漲跌方向，不寫點數。
- points：3 到 5 點，每點一個完整的句子（60 個字以內），只講一件事，例如大盤與成交金額、帶動或拖累盤勢的類股與權值股、三大法人買賣超、影響盤勢的消息。
- 每點的 urls 列出支持這句話的報導網址，1 到 3 個，逐字使用搜尋結果裡的網址，不可自己組合或修改。
- 只寫報導裡有的事實，數字照報導寫，不換算、不估計。報導之間說法不一致的事不要寫。
- 不預測之後的走勢，不給建議，不寫「值得留意」「可望」「建議」「後市」這類話；不用破折號和分號；不提你自己或搜尋的過程。
- 找不到這個交易日的可靠報導時，headline 給空字串、points 給空清單。"""  # noqa: E501

TOOL: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": ("回報整理好的收盤重點（一句標題與 3 到 5 點，每點附上支持它的搜尋結果網址；"
                    "找不到可靠報導就給空字串與空清單）。這是唯一的輸出方式。"),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {"type": "string", "description": "一句話說這一天大盤怎麼走；沒有可靠報導就給空字串"},
            "points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "一個完整的句子，只講一件事"},
                        "urls": {"type": "array", "items": {"type": "string"},
                                 "description": "支持這句話的搜尋結果網址（逐字，1 到 3 個）"},
                    },
                    "required": ["text", "urls"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["headline", "points"],
        "additionalProperties": False,
    },
}
NUDGE = "請用 report_market_summary 回報；沒有可靠的報導就給空字串與空清單。不要寫其他文字。"
_UP = re.compile(r"收漲|上漲|大漲|勁揚|收紅|收高|反彈")
_DOWN = re.compile(r"收跌|下跌|大跌|重挫|收黑|收低|回檔")

_inflight: set[date] = set()
_inflight_lock = threading.Lock()


@dataclass(frozen=True)
class OfficialIndex:
    """An official close the question may quote (``index_daily``)."""

    name: str
    close: Decimal
    change: Decimal | None
    change_pct: Decimal | None  # fraction


@dataclass
class Outcome:
    status: str  # ok | empty | failed
    headline: str = ""
    points: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)  # why candidate points were left out (diagnostics)
    queries: list[str] = field(default_factory=list)
    results: int = 0
    calls: int = 0
    stop_reason: str | None = None


def summary_day(now: datetime | None = None) -> date:
    """The latest trading day whose session is over at ``now`` (today from 14:00 Taipei on a trading day)."""
    at = (now or now_taipei()).astimezone(TAIPEI)
    d = at.date()
    if not (is_tw_trading_day(d) and at.time() >= SESSION_OVER):
        d -= timedelta(days=1)
        while not is_tw_trading_day(d):
            d -= timedelta(days=1)
    return d


def enabled(settings: Settings, pool: KeyPool | None = None) -> bool:
    """May a summary be generated here? Needs the switch, a key and a usable web search tool."""
    if not getattr(settings, "ai_market_summary_enabled", True) or not server_tools(settings, fetch=False):
        return False
    try:
        return bool((pool or get_key_pool()).available)
    except Exception:  # no pool configured
        return False


def question(day: date, today: date, official: list[OfficialIndex]) -> str:
    lines = [f"交易日：{day.isoformat()}（週{_WEEKDAYS[day.weekday()]}）", f"今天：{today.isoformat()}（台北）"]
    if official:
        parts = []
        for i in official:
            text = f"{i.name}收 {i.close:,.2f} 點"
            if i.change is not None and i.change_pct is not None:
                word = "漲" if i.change > 0 else "跌" if i.change < 0 else "平盤"
                text += (f"，{word} {abs(i.change):,.2f} 點（{abs(i.change_pct) * 100:.2f}%）"
                         if i.change else "，平盤")
            parts.append(text)
        lines.append("官方收盤數字：" + "；".join(parts))
    else:
        lines.append("官方收盤數字：還沒有公布（標題只寫漲跌方向，不寫點數）")
    lines.append("請搜尋這個交易日台股收盤的報導，整理後呼叫 report_market_summary。")
    return "\n".join(lines)


def _get(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def _norm_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    host = (parts.hostname or "").lower().removeprefix("www.")
    return urlunsplit(("https", host, unquote(parts.path).rstrip("/"), unquote(parts.query), ""))


def reported(content: list[Any]) -> dict[str, Any] | None:
    """The ``report_market_summary`` input (the last call wins), or ``None`` when the model did not call it."""
    found = None
    for b in content:
        if _get(b, "type") == "tool_use" and _get(b, "name") == TOOL_NAME:
            inp = _get(b, "input")
            found = inp if isinstance(inp, dict) else {}
    return found


def _queries(content: list[Any]) -> list[str]:
    out = []
    for b in content:
        if _get(b, "type") == "server_tool_use" and _get(b, "name") == "web_search":
            q = (_get(b, "input") or {}).get("query")
            if q:
                out.append(str(q))
    return out


def _one_line(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def verify(report: dict[str, Any], results: list[SearchResult], day: date, today: date,
           official: list[OfficialIndex] | None = None) -> tuple[str, list[dict[str, Any]], list[str]]:
    """(headline, points, dropped reasons). A point survives with the sources that are real search results and not
    dated before ``day``, and only when one of them is dated inside the report window."""
    by_url = {_norm_url(r.url): r for r in results}
    points: list[dict[str, Any]] = []
    dropped: list[str] = []
    seen_text: set[str] = set()
    raw_points = report.get("points")
    for p in raw_points if isinstance(raw_points, list) else []:
        if not isinstance(p, dict):
            dropped.append("not_an_object")
            continue
        text = _one_line(p.get("text"), MAX_POINT_CHARS)
        urls = p.get("urls") if isinstance(p.get("urls"), list) else []
        if not text or text in seen_text:
            dropped.append("empty_or_repeated")
            continue
        sources, dated_in_window, seen = [], False, set()
        for u in urls:
            r = by_url.get(_norm_url(str(u)))
            if r is None or r.url in seen:
                continue
            seen.add(r.url)
            when = date_from_page_age(r.page_age, today) or date_from_url(r.url)
            if when is not None and when < day:
                continue  # written before this session
            if when is not None and when <= day + REPORT_WINDOW:
                dated_in_window = True
            sources.append({"url": r.url, "title": _one_line(r.title, MAX_TITLE_CHARS), "outlet": outlet_name(r.url),
                            "date": when.isoformat() if when else None})
        if not sources:
            dropped.append("no_search_result_source")
            continue
        if not dated_in_window:
            dropped.append("date_unverified")
            continue
        seen_text.add(text)
        points.append({"text": text, "sources": sources[:MAX_SOURCES]})
        if len(points) >= MAX_POINTS:
            break
    headline = _one_line(report.get("headline"), MAX_HEADLINE_CHARS)
    taiex = next((i for i in official or [] if i.change), None)
    if headline and taiex is not None:
        up, down = bool(_UP.search(headline)), bool(_DOWN.search(headline))
        if (up and not down and taiex.change < 0) or (down and not up and taiex.change > 0):
            dropped.append("headline_contradicts_official_change")
            headline = ""
    return headline, points, dropped


def run_model(day: date, today: date, official: list[OfficialIndex], pool: KeyPool, settings: Settings,
              record: Callable[[int, Any], None], costs: Any = None) -> Outcome:
    """Ask the model (web search + ``report_market_summary``), then verify. Raises on API errors."""
    model = store.model_for(FEATURE, settings)
    messages: list[dict[str, Any]] = [{"role": "user", "content": question(day, today, official)}]
    params: dict[str, Any] = {
        "model": model, "max_tokens": MAX_TOKENS, "system": SYSTEM,
        "tools": [*server_tools(settings, fetch=False, max_uses=SEARCH_MAX_USES), TOOL],
        "output_config": {"effort": EFFORT},
    }
    content: list[Any] = []
    slot: int | None = None
    nudged = False
    calls = 0
    report: dict[str, Any] | None = None
    stop: str | None = None

    def ask(m: list[dict[str, Any]]) -> Callable[[Any], Any]:
        return lambda client: client.messages.with_raw_response.create(messages=m, **params)

    while calls < MAX_CALLS:
        try:
            raw, slot = pool.call(ask(messages), costs=costs if slot is None else None, only=slot)
        except anthropic.BadRequestError as exc:
            tool = rejected_tool(str(exc.api_message or exc), params["tools"])
            if tool is not None:  # e.g. web search not allowed here: later calls are skipped (``enabled``)
                exclude_tool(tool, str(exc.api_message or exc))
            raise
        calls += 1
        pool.observe(slot, raw.headers)
        msg = raw.parse()
        record(slot, msg)
        content.extend(msg.content)
        stop = msg.stop_reason
        assistant = {"role": "assistant", "content": [b.to_dict(mode="json") for b in msg.content]}
        if stop == "pause_turn":  # the server resumes from the trailing server_tool_use
            messages = [*messages, assistant]
            continue
        report = reported(msg.content)
        if report is not None or stop not in ("end_turn", "stop_sequence") or nudged:
            break
        nudged = True  # ended with text only: ask once for the tool call
        messages = [*messages, assistant, {"role": "user", "content": NUDGE}]
    results = search_results(content)
    out = Outcome("failed", queries=_queries(content), results=len(results), calls=calls, stop_reason=stop)
    if report is None or stop in ("refusal", "max_tokens"):
        log.warning("market summary %s: no usable report (stop=%s)", day, stop)
        return out
    out.headline, out.points, out.dropped = verify(report, results, day, today, official)
    out.status = "ok" if len(out.points) >= MIN_POINTS else "empty"
    if out.status == "empty":
        out.headline, out.points = "", []
    return out


def official_closes(db: Session, day: date) -> list[OfficialIndex]:
    """The TAIEX and the TPEx index of ``day`` when the archive already has them (they arrive in the evening)."""
    from forliosa.models import IndexDaily

    out = []
    for name, label in (("發行量加權股價指數", "加權指數"), ("櫃買指數", "櫃買指數")):
        r = db.get(IndexDaily, (name, day))
        if r is not None:
            pct = r.change_pct
            if pct is None and r.change is not None and r.close - r.change:
                pct = r.change / (r.close - r.change)
            out.append(OfficialIndex(label, r.close, r.change, pct))
    return out


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=TAIPEI)


def _due(row: AiMarketSummary | None, now: datetime) -> bool:
    """Should a generation be started for this day's row?"""
    if row is None:
        return True
    age = now - _aware(row.created_at)
    if row.status == "ok":
        return False
    if row.status == "pending":
        return age >= PENDING_TIMEOUT and row.attempts < MAX_ATTEMPTS
    return row.attempts < MAX_ATTEMPTS and age >= RETRY_AFTER


def generate(db: Session, day: date, pool: KeyPool, settings: Settings, now: datetime | None = None) -> AiMarketSummary:
    """Run one generation for ``day`` and store its outcome (ok | empty | failed)."""
    now = now or now_utc()
    row = db.get(AiMarketSummary, day)
    if row is None:
        row = AiMarketSummary(trading_day=day, status="pending", headline="", points=[], model="", attempts=0)
        db.add(row)
    row.status, row.attempts, row.created_at = "pending", (row.attempts or 0) + 1, now
    db.commit()
    model = store.model_for(FEATURE, settings)

    def record(slot: int, msg: Any) -> None:
        store.record_usage(db, user_id=None, thread_id=None, feature=FEATURE, model=msg.model or model,
                           key_slot=slot, usage=CallUsage.from_sdk(msg.usage), stop_reason=msg.stop_reason)

    try:
        out = run_model(day, now.astimezone(TAIPEI).date(), official_closes(db, day), pool, settings, record,
                        costs=store.slot_month_costs(db))
    except Exception:
        log.exception("market summary for %s failed", day)
        db.rollback()
        out = Outcome("failed")
    row = db.get(AiMarketSummary, day)
    row.status, row.headline, row.points, row.model = out.status, out.headline, out.points, model
    db.commit()
    if out.status != "ok":
        log.info("market summary %s: %s (dropped: %s; %d results, %d calls)", day, out.status,
                 ", ".join(out.dropped) or "none", out.results, out.calls)
    return row


def view(row: AiMarketSummary | None) -> dict[str, Any] | None:
    if row is None or row.status != "ok" or not row.points:
        return None
    return {"date": row.trading_day, "headline": row.headline or None,
            "points": [{"text": p["text"],
                        "sources": [{"url": s["url"], "title": s.get("title") or "", "outlet": s.get("outlet") or ""}
                                    for s in p.get("sources") or []]}
                       for p in row.points]}


def latest(db: Session, now: datetime | None = None) -> dict[str, Any] | None:
    """The newest finished summary, if it is recent enough to stand on the page."""
    day = summary_day(now)
    row = db.scalar(select(AiMarketSummary).where(AiMarketSummary.status == "ok",
                                                  AiMarketSummary.trading_day <= day,
                                                  AiMarketSummary.trading_day >= day - SHOW_FOR)
                    .order_by(AiMarketSummary.trading_day.desc()).limit(1))
    return view(row)


def spawn(job: Callable[[], None], name: str) -> None:
    threading.Thread(target=job, name=name, daemon=True).start()


def ensure(db: Session, now: datetime | None = None, pool: KeyPool | None = None,
           settings: Settings | None = None) -> None:
    """Start a background generation for the latest finished session when it has no summary yet (page visits).
    Never raises: the page is complete without a summary."""
    try:
        settings = settings or get_settings()
        if not enabled(settings, pool):
            return
        pool = pool or get_key_pool()
        day = summary_day(now)
        if not _due(db.get(AiMarketSummary, day), now or now_utc()):
            return
        with _inflight_lock:
            if day in _inflight:
                return
            _inflight.add(day)

        def work() -> None:
            try:
                with session_factory()() as session:
                    generate(session, day, pool, settings)
            except Exception:  # pragma: no cover - logged; asked again after RETRY_AFTER
                log.exception("background market summary for %s failed", day)
            finally:
                with _inflight_lock:
                    _inflight.discard(day)

        spawn(work, f"ai-market-summary-{day}")
    except Exception:
        log.exception("market summary could not be started")
        db.rollback()


def refresh(db: Session, now: datetime | None = None, pool: KeyPool | None = None,
            settings: Settings | None = None) -> AiMarketSummary | None:
    """The worker's call: generate the latest finished session's summary now when it is due."""
    settings = settings or get_settings()
    if not enabled(settings, pool):
        return None
    day = summary_day(now)
    if not _due(db.get(AiMarketSummary, day), now or now_utc()):
        return None
    return generate(db, day, pool or get_key_pool(), settings, now)
