"""每日收盤簡報: one briefing per user and trading day, only for users who switched it on (off by default).

Product owner, 2026-11-14 (after looking at Google Finance's "tasks"): one fixed kind of scheduled work instead of
free-form tasks — after the close, a short briefing built from the user's own holdings and watchlist.

A briefing has two parts:

* **facts** — computed by rules from the ledger, never by a model: the portfolio's value and the day's change, the
  holdings that rose and fell the most, watchlist symbols that moved ``WATCH_MOVE_PCT`` or more, and the week's
  ex-dividend dates, dividend payments and recurring-plan debits (the same services as the ledger page; official
  closes only — the history backfill's rows are never read).
* **points** — at most three AI notes about the one or two biggest movers, each resting on search results. One model
  call with web search (``SEARCH_MAX_USES``) that may answer only through ``report_briefing_points``; the points are
  verified exactly like the market page's summary (``market_summary.verify``: every address is a search result the
  model received, at least one report dated the trading day or just after). The model is told the names, codes,
  closes and percentage moves of those symbols — public market data — and nothing about quantities, costs or values.

The facts always stand on their own: without a key, with web search off, when the user is out of quota or when no
point survives the check, the briefing is written with facts only.

When: the worker (``Worker.daily_briefings``) looks at 22:20, 23:50, 06:10 and 08:20 Taipei. A briefing is written for
the latest finished session once both exchanges' official closes of that day are archived, once per user and day.
Briefings older than ``KEEP_DAYS`` are deleted on every run.

Quota: the model call is recorded under the user (``ai_usage.feature = "briefing"``), so it counts as one of the
day's questions and its tokens count toward the month; a user at either limit gets the facts only.

Cost (Claude Haiku 5.5 list prices, 2026-11-12): up to three searches (US$0.03) plus roughly 25K input tokens —
about US$0.03–0.05 per user and trading day, nothing for users who left it off.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import anthropic
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from forliosa.ai import market_summary, store
from forliosa.ai.analyst import search_results
from forliosa.ai.keypool import KeyPool, get_key_pool
from forliosa.ai.pricing import CallUsage
from forliosa.ai.tools import exclude_tool, rejected_tool, server_tools
from forliosa.api.errors import ApiError, not_found
from forliosa.config import Settings, get_settings
from forliosa.ids import new_id
from forliosa.marketdata.base import market_of_symbol
from forliosa.marketdata.service import MarketData
from forliosa.models import AiBriefing, DatasetStatus, User, WatchlistItem
from forliosa.services.ledger_io import preferences_of
from forliosa.timeutil import TAIPEI, iso_taipei, now_utc, today_taipei, tw_trading_days

log = logging.getLogger(__name__)

FEATURE = "briefing"
TOOL_NAME = "report_briefing_points"
PRICE_STATUS_KEYS = ("twse-openapi/price", "tpex-openapi/price")
MAX_AGE_DAYS = 4  # a session older than this is not briefed any more (e.g. after a long outage)
KEEP_DAYS = 30
SHOW_SESSIONS = 2  # ``latest`` shows a briefing until two trading days have passed
MOVERS = 2  # holdings listed on each side (rose / fell the most)
WATCH_MOVE_PCT = Decimal("0.03")
WATCH_MAX = 3
UPCOMING_DAYS = 7
UPCOMING_MAX = 5
AI_MOVERS = 2  # symbols the model is asked about
AI_MOVE_MIN_PCT = Decimal("0.015")  # a smaller move is not worth a search
SEARCH_MAX_USES = 3
MAX_CALLS = 4
MAX_TOKENS = 4000
MAX_POINTS = 3
EFFORT = "medium"
_WEEKDAYS = "一二三四五六日"

SYSTEM = """你是財經編輯，替 Forliosa 使用者的每日收盤簡報補上報導重點。Forliosa 只轉述報導，不提供自己的看法。

## 任務
使用者訊息會列出一到兩檔今天漲跌較大的股票或 ETF（名稱、代號、官方收盤價與漲跌幅）。用 web_search 找這個交易日和它們有關的報導，整理成最多 3 點，最後呼叫 report_briefing_points。這個工具呼叫是你唯一的輸出。

## 搜尋
- 用繁體中文關鍵字，帶上名稱與日期，例如「台積電 11月12日 股價」「聯發科 法說 11月」；結果不夠就換關鍵字再搜。
- 採用通訊社與信譽良好的財經媒體（例如中央社、經濟日報、工商時報、鉅亨網）或公司與交易所的公告。不採用論壇、社群貼文、內容農場、影音頻道，也不採用行情頁與目標價彙整頁。
- 你的訓練資料比今天早很多：只根據這次搜尋到、寫的是這個交易日的報導來寫，不要憑記憶補資料。日期更早的報導不要用。

## 怎麼寫
- points：最多 3 點，每點一個完整的句子（60 個字以內），開頭寫出是哪一檔，只講報導裡和這一天漲跌有關的一件事，例如公司的公告、法說內容、產業消息、法人買賣。
- 收盤價與漲跌幅只能用使用者訊息裡的官方數字；報導裡的其他數字照報導寫，不換算、不估計。
- 每點的 urls 列出支持這句話的報導網址，1 到 3 個，逐字使用搜尋結果裡的網址，不可自己組合或修改。
- 找不到可靠報導的那一檔就不要寫；不要用大盤的一般說法湊數。
- 不預測之後的走勢，不給建議，不寫「值得留意」「可望」「建議」「後市」這類話；不用破折號和分號；不提你自己或搜尋的過程。
- 都找不到時 points 給空清單。"""  # noqa: E501

TOOL: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": ("回報整理好的報導重點（最多 3 點，每點附上支持它的搜尋結果網址；找不到可靠報導就給空清單）。"
                    "這是唯一的輸出方式。"),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "一個完整的句子，開頭寫出是哪一檔，只講一件事"},
                        "urls": {"type": "array", "items": {"type": "string"},
                                 "description": "支持這句話的搜尋結果網址（逐字，1 到 3 個）"},
                    },
                    "required": ["text", "urls"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["points"],
        "additionalProperties": False,
    },
}
NUDGE = "請用 report_briefing_points 回報；沒有可靠的報導就給空清單。不要寫其他文字。"


@dataclass
class RunResult:
    day: date | None = None
    written: int = 0  # briefings created in this run
    with_points: int = 0  # of those, with at least one AI point
    purged: int = 0


# -- which day ------------------------------------------------------------------------------------------------------
def briefing_day(db: Session, now: datetime | None = None) -> date | None:
    """The latest finished session whose official closes are archived for every exchange we archive, or ``None``
    while they are still awaited (the exchanges publish between the evening and the next early morning). Without
    any archive at all (demo data) the latest finished session is used as it is."""
    day = market_summary.summary_day(now)
    today = (now or now_utc()).astimezone(TAIPEI).date()
    if (today - day).days > MAX_AGE_DAYS:
        return None
    archived = [d for d in db.scalars(select(DatasetStatus.data_date).where(DatasetStatus.key.in_(PRICE_STATUS_KEYS)))
                if d is not None]
    if archived and min(archived) < day:
        return None
    return day


def opted_in(user: User) -> bool:
    return preferences_of(user).get("daily_briefing") is True


# -- facts (rules only) ---------------------------------------------------------------------------------------------
def _mover(h: dict[str, Any]) -> dict[str, Any]:
    return {"symbol": h["symbol"], "code": h["code"], "name": h["name"], "market": h["market"], "type": h["type"],
            "close": h["price"], "change_pct": h["day_change_pct"], "day_change": h["day_change"]}


def build_facts(db: Session, user: User, md: MarketData, day: date) -> dict[str, Any] | None:
    """The rule-computed part, or ``None`` when the user has neither holdings nor a watchlist (nothing to brief)."""
    from forliosa.services import instruments as instr
    from forliosa.services import portfolio as svc
    from forliosa.services import recurring

    state = svc.compute_state(db, user, md)
    holdings = svc.holdings(state)
    watched = list(db.scalars(select(WatchlistItem.symbol).where(WatchlistItem.user_id == user.id)
                              .order_by(WatchlistItem.created_at, WatchlistItem.id)))
    if not holdings and not watched:
        return None
    summary = svc.summary(state, md)
    priced = [h for h in holdings if h["price"] is not None and h["day_change_pct"] is not None]
    gainers = sorted((h for h in priced if h["day_change_pct"] > 0), key=lambda h: h["day_change_pct"], reverse=True)
    losers = sorted((h for h in priced if h["day_change_pct"] < 0), key=lambda h: h["day_change_pct"])

    held = {h["symbol"] for h in holdings}
    quotes = md.quotes([s for s in watched if s not in held]) if watched else {}
    watch = []
    for sym in watched:
        q = quotes.get(sym)
        if q is None:
            continue
        out = instr.quote_out(q)
        pct = out["change_pct"]
        if pct is None or abs(Decimal(str(pct))) < WATCH_MOVE_PCT:
            continue
        info = md.instrument(sym)
        watch.append({"symbol": sym, "code": info.code if info else sym.split(".")[0],
                      "name": info.name if info else sym, "market": info.market if info else market_of_symbol(sym),
                      "type": info.type if info else "stock", "close": out["price"], "change_pct": pct})
    watch.sort(key=lambda w: abs(w["change_pct"]), reverse=True)

    today = today_taipei()  # the same window ``svc.upcoming`` uses: the week from the day the briefing is written
    plans = recurring.upcoming_items(db, user, md, [a.id for a in state.inp.accounts], today,
                                     today + timedelta(days=UPCOMING_DAYS))
    upcoming = [{"date": u["date"].isoformat() if isinstance(u["date"], date) else str(u["date"]), "type": u["type"],
                 "symbol": u["symbol"], "title": u["title"], "amount_estimate": u["amount_estimate"]}
                for u in svc.upcoming(state, md, UPCOMING_DAYS, plans)]

    return {
        "market_value": summary["market_value"],
        "day_change": summary["day_change"],
        "day_change_pct": summary["day_change_pct"],
        "holdings": len(holdings),
        "unpriced": len(holdings) - len([h for h in holdings if h["price"] is not None]),
        "gainers": [_mover(h) for h in gainers[:MOVERS]],
        "losers": [_mover(h) for h in losers[:MOVERS]],
        "watchlist": watch[:WATCH_MAX],
        "upcoming": upcoming[:UPCOMING_MAX],
        "is_demo": bool(summary["is_demo"]) or any(h["is_demo"] for h in holdings),
    }


def ai_subjects(facts: dict[str, Any]) -> list[dict[str, Any]]:
    """The one or two symbols worth a search: the biggest moves among the holdings, else on the watchlist."""
    pool = [*facts["gainers"], *facts["losers"]] or facts["watchlist"]
    big = [m for m in pool if m.get("change_pct") is not None and abs(Decimal(str(m["change_pct"]))) >= AI_MOVE_MIN_PCT
           and m["market"] != "US"]
    return sorted(big, key=lambda m: abs(m["change_pct"]), reverse=True)[:AI_MOVERS]


# -- the AI's points ------------------------------------------------------------------------------------------------
def enabled(settings: Settings, pool: KeyPool | None = None) -> bool:
    """May the AI part be asked for here? Needs a key and a usable web search tool."""
    if not server_tools(settings, fetch=False):
        return False
    try:
        return bool((pool or get_key_pool()).available)
    except Exception:  # no pool configured
        return False


def within_quota(db: Session, user: User, settings: Settings, now: datetime | None = None) -> bool:
    try:
        store.check_quota(db, user, settings, now)
    except ApiError:
        return False
    return True


def question(day: date, today: date, subjects: list[dict[str, Any]]) -> str:
    lines = [f"交易日：{day.isoformat()}（週{_WEEKDAYS[day.weekday()]}）", f"今天：{today.isoformat()}（台北）",
             "今天漲跌較大的："]
    for m in subjects:
        pct = Decimal(str(m["change_pct"])) * 100
        word = "漲" if pct > 0 else "跌"
        kind = "ETF" if m.get("type") == "etf" else "股票"
        lines.append(f"- {m['name']}（{m['code']}，{kind}）收 {m['close']}，{word} {abs(pct):.2f}%")
    lines.append("請搜尋這個交易日和它們有關的報導，整理後呼叫 report_briefing_points。")
    return "\n".join(lines)


def _get(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def reported(content: list[Any]) -> dict[str, Any] | None:
    found = None
    for b in content:
        if _get(b, "type") == "tool_use" and _get(b, "name") == TOOL_NAME:
            inp = _get(b, "input")
            found = inp if isinstance(inp, dict) else {}
    return found


def run_model(day: date, today: date, subjects: list[dict[str, Any]], pool: KeyPool, settings: Settings,
              record: Callable[[int, Any], None], costs: Any = None) -> tuple[str, list[dict[str, Any]]]:
    """Ask the model, then verify. Returns (``ok`` | ``empty`` | ``failed``, points). Raises on API errors."""
    model = store.model_for(FEATURE, settings)
    messages: list[dict[str, Any]] = [{"role": "user", "content": question(day, today, subjects)}]
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
            if tool is not None:  # e.g. web search not allowed here: later briefings keep to the facts
                exclude_tool(tool, str(exc.api_message or exc))
            raise
        calls += 1
        pool.observe(slot, raw.headers)
        msg = raw.parse()
        record(slot, msg)
        content.extend(msg.content)
        stop = msg.stop_reason
        assistant = {"role": "assistant", "content": [b.to_dict(mode="json") for b in msg.content]}
        if stop == "pause_turn":
            messages = [*messages, assistant]
            continue
        report = reported(msg.content)
        if report is not None or stop not in ("end_turn", "stop_sequence") or nudged:
            break
        nudged = True
        messages = [*messages, assistant, {"role": "user", "content": NUDGE}]
    if report is None or stop in ("refusal", "max_tokens"):
        return "failed", []
    _headline, points, dropped = market_summary.verify({"headline": "", "points": report.get("points")},
                                                       search_results(content), day, today)
    points = [{"text": p["text"], "sources": [{"url": s["url"], "title": s.get("title") or "",
                                               "outlet": s.get("outlet") or ""} for s in p["sources"]]}
              for p in points[:MAX_POINTS]]
    if not points and dropped:
        log.info("briefing %s: no point survived (%s)", day, ", ".join(dropped))
    return ("ok" if points else "empty"), points


# -- one user, all users --------------------------------------------------------------------------------------------
def generate_for_user(db: Session, user: User, md: MarketData, day: date, pool: KeyPool | None, settings: Settings,
                      now: datetime | None = None) -> AiBriefing | None:
    """Write ``user``'s briefing of ``day`` unless it exists or there is nothing to brief. The facts are stored even
    when the AI part is skipped or fails."""
    now = now or now_utc()
    if db.scalar(select(AiBriefing.id).where(AiBriefing.user_id == user.id, AiBriefing.trading_day == day)):
        return None
    facts = build_facts(db, user, md, day)
    if facts is None:
        return None
    briefing_id = new_id("brf")
    status, points, model = "none", [], ""
    subjects = ai_subjects(facts)
    if subjects and pool is not None and enabled(settings, pool) and within_quota(db, user, settings, now):
        model = store.model_for(FEATURE, settings)
        user_id = user.id

        def record(slot: int, msg: Any) -> None:
            # thread_id = the briefing: its calls count as one question of the day (``store.messages_today``)
            store.record_usage(db, user_id=user_id, thread_id=briefing_id, feature=FEATURE,
                               model=msg.model or model, key_slot=slot, usage=CallUsage.from_sdk(msg.usage),
                               stop_reason=msg.stop_reason)

        try:
            status, points = run_model(day, now.astimezone(TAIPEI).date(), subjects, pool, settings, record,
                                       costs=store.slot_month_costs(db))
        except Exception:
            log.exception("briefing points for one user failed (%s)", day)
            db.rollback()
            status, points = "failed", []
    row = AiBriefing(id=briefing_id, user_id=user.id, trading_day=day, facts=facts, points=points, ai_status=status,
                     model=model, created_at=now)
    db.add(row)
    db.commit()
    return row


def purge(db: Session, now: datetime | None = None, days: int = KEEP_DAYS) -> int:
    cutoff = (now or now_utc()).astimezone(TAIPEI).date() - timedelta(days=days)
    n = db.execute(delete(AiBriefing).where(AiBriefing.trading_day < cutoff)).rowcount or 0
    db.commit()
    return n


def run(db: Session, md: MarketData, now: datetime | None = None, pool: KeyPool | None = None,
        settings: Settings | None = None) -> RunResult:
    """The worker's call: old briefings out, then one briefing for every user who switched it on and has none for the
    latest archived session."""
    settings = settings or get_settings()
    out = RunResult(purged=purge(db, now))
    if not settings.ai_daily_briefing_enabled:
        return out
    out.day = day = briefing_day(db, now)
    if day is None:
        return out
    if pool is None:
        try:
            pool = get_key_pool()
        except Exception:  # no keys configured: facts only
            pool = None
    for user in list(db.scalars(select(User).order_by(User.created_at, User.id))):
        if not opted_in(user):
            continue
        try:
            row = generate_for_user(db, user, md, day, pool, settings, now)
        except Exception:
            log.exception("briefing for one user failed (%s)", day)
            db.rollback()
            continue
        if row is not None:
            out.written += 1
            out.with_points += bool(row.points)
    return out


# -- reading --------------------------------------------------------------------------------------------------------
def view(row: AiBriefing) -> dict[str, Any]:
    return {"id": row.id, "date": row.trading_day, "created_at": iso_taipei(row.created_at),
            "read": row.read_at is not None, "facts": row.facts or {}, "points": row.points or []}


def latest(db: Session, user: User, now: datetime | None = None) -> dict[str, Any] | None:
    """The newest briefing while it is still current: until ``SHOW_SESSIONS`` trading days have passed since its day."""
    row = db.scalar(select(AiBriefing).where(AiBriefing.user_id == user.id)
                    .order_by(AiBriefing.trading_day.desc()).limit(1))
    if row is None:
        return None
    last = market_summary.summary_day(now)
    if len(tw_trading_days(row.trading_day + timedelta(days=1), last)) >= SHOW_SESSIONS:
        return None
    return view(row)


def recent(db: Session, user: User, limit: int = 14) -> list[dict[str, Any]]:
    rows = db.scalars(select(AiBriefing).where(AiBriefing.user_id == user.id)
                      .order_by(AiBriefing.trading_day.desc()).limit(limit))
    return [view(r) for r in rows]


def mark_read(db: Session, user: User, briefing_id: str, now: datetime | None = None) -> None:
    row = db.get(AiBriefing, briefing_id)
    if row is None or row.user_id != user.id:
        raise not_found("找不到這則簡報")
    if row.read_at is None:
        row.read_at = now or now_utc()
        db.commit()
