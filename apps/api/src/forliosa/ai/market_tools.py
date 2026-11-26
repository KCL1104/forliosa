"""The chat's market-wide tools and its follow-up questions (產品負責人 2026-11-26).

「明天可以關注哪些個股？」 was answered with a refusal: the chat had tools for one stock and for the user's own ledger,
nothing about the whole market. These read what the market page and the market reports already keep:

* ``get_market_calendar`` — scheduled events of a date range (``reports.calendars.events_between``: ex-dividend
  dates, investor conferences, shareholder meetings, disposition, settlement days, macro releases, US earnings, NYSE
  closures). The user's own holdings and watchlist come first and are marked; the 100 largest companies by market cap
  and the market-wide rows are listed; the rest are counted by kind with a few names (largest first).
* ``get_market_overview`` — the latest session: both indices, advancers and decliners, sector moves, the market page's
  rankings (``services.market_overview.snapshot``) and the stocks at the limit up / down (both exchanges).
* ``get_market_report`` — the newest published 盤前重點／盤後重點／市場週報: each news page the report cites becomes a
  citable search result holding the report's sentences that cite it, so the answer links the original article.
* ``get_watchlist`` — the user's watchlist with the latest official close.
* ``suggest_follow_ups`` — 2–3 questions shown under the answer (``FOLLOW_UPS``); the chat ends the turn when it is the
  only tool left, without another model call (``forliosa.ai.chat``).

All of them are read-only and use no web search. The stocks they name are picked by stated rules (yours, market cap,
the day's rankings), never by a model's view.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from forliosa.ai.tools import Citable, ToolContext, ToolError
from forliosa.models import MarketEvent, WatchlistItem
from forliosa.reports import calendars as cal
from forliosa.reports import marketcalc as mc
from forliosa.timeutil import TAIPEI, next_tw_trading_day, now_utc

log = logging.getLogger(__name__)

CALENDAR_MAX_DAYS = 14
CALENDAR_MAX_LISTED = 40
CALENDAR_MAX_ONE_KIND = 80  # a question about one kind (「這週有哪些法說會」「最近哪些要除息」) lists them all
TOP_RANK = 100  # the reports' 「市值前 100 名」 (``marketcalc.EVENT_RANK``)
OTHER_EXAMPLES = 5
MOVERS_N = 10
SECTORS_N = 5
LIMIT_N = 10
REPORT_KINDS = ("latest", "premarket", "close", "weekly")
REPORT_SENTENCES_MAX = 40
FOLLOW_UPS_MAX = 3
FOLLOW_UP_CHARS = (4, 40)
# A follow-up the user would ask us to decide for them: never offered (the content line of PRODUCT.md)
_ADVICE = re.compile(r"該不該(?:買|賣|加碼|減碼|出場|進場)|要不要(?:買|賣|加碼|減碼|出場|進場)|可以(?:買|進場|加碼)|"
                     r"值得(?:買|投資)|明牌|推薦(?:哪|幾|一)|會漲到|會跌到|何時(?:買|賣)|什麼時候(?:買|賣)")
_URL = re.compile(r"https?://|www\.", re.I)

_DAYS_TTL = 30 * 60  # seconds: a session's closes are final the next morning; ranks and counts barely move
_days_lock = threading.Lock()
_days_cache: dict[tuple[str, date, str], tuple[float, mc.Day]] = {}


def clear_cache() -> None:
    with _days_lock:
        _days_cache.clear()


# -- shared ------------------------------------------------------------------------------------------------------
def _latest_day(ctx: ToolContext, market: str, now: datetime) -> mc.Day | None:
    """``market``'s newest session with official closes (cached per session for ``_DAYS_TTL``)."""
    policy = ctx.md.policy
    today = now.astimezone(TAIPEI).date()
    for d in reversed(mc.session_dates(ctx.db, market, today, now, policy, limit=3)):
        key = (market, d, policy)
        with _days_lock:
            hit = _days_cache.get(key)
        if hit is not None and time.monotonic() - hit[0] < _DAYS_TTL:
            return hit[1]
        loaded = mc.load_day(ctx.db, market, d, now, policy)
        if loaded is None:
            continue
        with _days_lock:
            for k in [k for k in _days_cache if k[0] == market]:
                del _days_cache[k]
            _days_cache[key] = (time.monotonic(), loaded)
        return loaded
    return None


def _mcap_ranks(days: list[mc.Day | None]) -> dict[str, int]:
    """Commons of both markets by market cap, largest first (0 = largest)."""
    pool = [q for d in days if d is not None for q in d.commons() if q.mcap is not None]
    return {q.symbol: i for i, q in enumerate(sorted(pool, key=lambda q: (-q.mcap, q.symbol)))}


def _mine(ctx: ToolContext) -> dict[str, str]:
    """symbol -> 「持有」 or 「觀察」 (a held stock on the watchlist is 持有)."""
    from forliosa.services import portfolio as svc

    out = {s: "觀察" for s in ctx.db.scalars(select(WatchlistItem.symbol).where(WatchlistItem.user_id == ctx.user.id))}
    try:
        state = svc.compute_state(ctx.db, ctx.user, ctx.md)
        for h in svc.holdings(state):
            if h.get("symbol"):
                out[h["symbol"]] = "持有"
    except Exception:  # the ledger could not be computed: the market rows still help
        ctx.db.rollback()
        log.warning("get_market_calendar: holdings unavailable", exc_info=True)
    return out


def _date_arg(args: dict[str, Any], key: str) -> date | None:
    raw = str(args.get(key) or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        raise ToolError(f"{key} 要寫成 YYYY-MM-DD，例如 2026-11-27；不指定就給空字串") from None


def _code(symbol: str | None) -> str | None:
    return symbol.split(".")[0] if symbol and symbol != "MARKET" else None


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def pct(x: Any) -> str | None:
    """0.0251 → 「+2.51%」, −0.012 → 「−1.20%」: written out, so the model never reads a fraction as a percentage
    (QA 2026-11-26: TAIEX ▲2.5% came back as 「漲 0.03%」 from 0.025)."""
    if x is None:
        return None
    v = float(x) * 100
    return f"{'+' if v > 0 else '−' if v < 0 else ''}{abs(v):.2f}%"


# -- get_market_calendar -----------------------------------------------------------------------------------------
def _kind_arg(args: dict[str, Any]) -> str | None:
    """「法說會」 or ``investor_conference`` (either the label or the key); None for every kind."""
    raw = str(args.get("kind") or "").strip()
    if not raw:
        return None
    by_label = {v: k for k, v in cal.KIND_LABELS.items()}
    aliases = {"除息": "ex_dividend", "除權": "ex_dividend", "處置": "disposition", "注意": "attention"}
    kind = raw if raw in cal.KIND_LABELS else by_label.get(raw) or aliases.get(raw)
    if kind is None:
        raise ToolError(f"kind 可以是 {'、'.join(cal.KIND_LABELS.values())}，或空字串（全部）")
    return kind


def _dividends(ctx: ToolContext, start: date, end: date) -> dict[tuple[str, date], dict[str, Any]]:
    """(symbol, ex date) -> the official row's cash dividend per share and stock ratio (``market_events.data``)."""
    rows = ctx.db.execute(select(MarketEvent.symbol, MarketEvent.date, MarketEvent.data).where(
        MarketEvent.type == "ex_dividend", MarketEvent.date >= start, MarketEvent.date <= end))
    return {(sym, d): data or {} for sym, d, data in rows}


def _amount(data: dict[str, Any] | None) -> str | None:
    """「每股現金 0.33 元」「每股現金 4 元、每千股配 50 股」; 「金額還沒公告」 when the row has no amount yet."""
    if data is None:
        return None
    parts = []
    for key, fmt in (("cash", "每股現金 {} 元"), ("stock_ratio", "每千股配 {} 股")):
        raw = data.get(key)
        try:
            value = float(raw) if raw not in (None, "") else 0.0
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            shown = value * 1000 if key == "stock_ratio" else value  # the ratio is shares per share (×10 = 元)
            parts.append(fmt.format(f"{shown:,.4f}".rstrip("0").rstrip(".")))
    return "、".join(parts) or "金額還沒公告"


def _event_out(e: cal.CalEvent, yours: str | None, amounts: dict[tuple[str, date], dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"date": e.date.isoformat(), "kind": e.kind_label, "title": e.title}
    if e.kind == "ex_dividend" and (amount := _amount(amounts.get((e.symbol or "", e.date)))):
        out["amount"] = amount
    if e.time_label:
        out["time"] = e.time_label
    if code := _code(e.symbol):
        out["code"] = code
    if yours:
        out["yours"] = yours
    if e.sectors:
        out["sectors"] = list(e.sectors)
    if e.note:
        out["note"] = e.note
    return out


def market_calendar(ctx: ToolContext, args: dict[str, Any]) -> Any:
    now = now_utc()
    today = now.astimezone(TAIPEI).date()
    nxt = next_tw_trading_day(today + timedelta(days=1))
    start = _date_arg(args, "date_from") or nxt
    end = _date_arg(args, "date_to") or start
    if end < start:
        start, end = end, start
    notes: list[str] = []
    if (end - start).days >= CALENDAR_MAX_DAYS:
        end = start + timedelta(days=CALENDAR_MAX_DAYS - 1)
        notes.append(f"一次最多查 {CALENDAR_MAX_DAYS} 天：只查到 {_md(end)}")
    kind = _kind_arg(args)
    events = cal.events_between(ctx.db, start, end, cutoff=now, policy=ctx.md.policy, include_filings=False)
    if kind is not None:
        events = [e for e in events if e.kind == kind]
    mine = _mine(ctx)
    ranks = _mcap_ranks([_latest_day(ctx, "TWSE", now), _latest_day(ctx, "TPEX", now)])
    far = 10**9  # not ranked (no close, an ETF): after every ranked company, never among the largest

    def rank(e: cal.CalEvent) -> int:
        return ranks.get(e.symbol or "", far)

    # what is listed one by one: yours, the market-wide rows (no company, or a US company of the hand-kept table),
    # then the largest companies, up to CALENDAR_MAX_LISTED in all
    yours = [e for e in events if e.symbol in mine]
    wide = [e for e in events if e.symbol in (None, "MARKET") or e.kind in ("us_earnings", "us_holiday", "macro")]
    picked = {id(e) for e in yours + wide}
    room = max(0, (CALENDAR_MAX_ONE_KIND if kind else CALENDAR_MAX_LISTED) - len(picked))
    if kind is not None:  # one kind: every company, largest first, up to the cap
        big = sorted((e for e in events if id(e) not in picked), key=rank)[:room]
        picked |= {id(e) for e in big}
    else:
        big = sorted((e for e in events if id(e) not in picked and rank(e) < TOP_RANK), key=rank)[:room]
        picked |= {id(e) for e in big}
    listed = [e for e in events if id(e) in picked]
    rest: dict[str, list[cal.CalEvent]] = defaultdict(list)
    for e in events:
        if id(e) not in picked:
            rest[e.kind_label].append(e)
    others = []
    for label, rows in rest.items():
        names = []
        for e in sorted(rows, key=rank):
            name = e.title.split("（")[0] if "（" in e.title else e.title
            if name not in names:
                names.append(name)
            if len(names) >= OTHER_EXAMPLES:
                break
        others.append({"kind": label, "count": len(rows), "examples": names})
    amounts = _dividends(ctx, start, end) if any(e.kind == "ex_dividend" for e in listed) else {}
    out: dict[str, Any] = {
        "from": start.isoformat(), "to": end.isoformat(), "next_tw_trading_day": nxt.isoformat(),
        "events": [_event_out(e, mine.get(e.symbol or ""), amounts) for e in listed],
        "others": others,
        "rules": ((f"只查{cal.KIND_LABELS[kind]}：全部列出（最多 {CALENDAR_MAX_ONE_KIND} 筆，你的先列，其他依市值）"
                   if kind else
                   "列出的是：你持有或在觀察清單裡的（yours）、全市場的事件（結算日、總經數據、美股財報與休市），"
                   f"以及市值前 {TOP_RANK} 名的公司；其他公司只算件數，examples 是其中市值較大的幾家。"
                   "問某一種事件（法說會、除權息…）時用 kind 再查一次就會全部列出")
                  + "；除權息的 amount 是官方公告的每股股利"),
    }
    if not events:
        notes.append(f"{_md(start)}" + (f"–{_md(end)}" if end != start else "") + " 沒有已排定的事件")
    if notes:
        out["notes"] = notes
    return out


# -- get_market_overview -----------------------------------------------------------------------------------------
def _quote_row(q: mc.Quote) -> dict[str, Any]:
    return {"code": q.code, "name": q.name, "close": float(q.close), "change": pct(q.pct)}


def _breadth(day: mc.Day | None) -> dict[str, Any] | None:
    if day is None:
        return None
    b = mc.breadth(day)
    return {"date": day.day.isoformat(), "up": b.up, "flat": b.flat, "down": b.down, "limit_up": b.limit_up,
            "limit_down": b.limit_down}


def _limits(days: list[mc.Day | None], side: int) -> list[dict[str, Any]]:
    hit = [q for d in days if d is not None for q in d.commons() if q.limit_hit() == side]
    hit.sort(key=lambda q: (-(q.value or 0), q.symbol))
    return [_quote_row(q) for q in hit[:LIMIT_N]]


def _mover(row: dict[str, Any]) -> dict[str, Any]:
    vol = row.get("volume")
    return {"code": row["code"], "name": row["name"], "close": row["close"], "change": pct(row["change_pct"]),
            "volume_lots": round(vol / 1000) if vol else None}


def market_overview(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.services import market_overview as mo

    now = now_utc()
    snap = mo.snapshot(ctx.db, ctx.md)
    twse, tpex = _latest_day(ctx, "TWSE", now), _latest_day(ctx, "TPEX", now)
    movers = snap.get("movers")
    sectors = (snap.get("sectors") or {}).get("items") or []
    out: dict[str, Any] = {
        "indices": [{"name": i["name"], "close": i["value"], "change": pct(i["change_pct"]), "date": i["date"]}
                    for i in snap.get("indices") or [] if i.get("key") in ("taiex", "tpex", "tx", "usdtwd")],
        "breadth": {k: v for k, v in (("上市", _breadth(twse)), ("上櫃", _breadth(tpex))) if v},
        "sectors_date": (snap.get("sectors") or {}).get("date"),
        "sectors_best": [{"name": s["name"], "change": pct(s["change_pct"])} for s in sectors[:SECTORS_N]],
        "sectors_worst": [{"name": s["name"], "change": pct(s["change_pct"])} for s in sectors[::-1][:SECTORS_N]],
        "rankings_date": movers["date"] if movers else None,
        "gainers": [_mover(r) for r in (movers or {}).get("gainers", [])[:MOVERS_N]],
        "losers": [_mover(r) for r in (movers or {}).get("losers", [])[:MOVERS_N]],
        "most_traded": [_mover(r) for r in (movers or {}).get("volume", [])[:MOVERS_N]],
        "limit_up_top_by_value": _limits([twse, tpex], 1),
        "limit_down_top_by_value": _limits([twse, tpex], -1),
        "units": ("change 是漲跌幅（已經是百分比，照寫），從當天的參考價算；volume_lots 是成交張數；"
                  "類股是上市的類股指數；排行只算普通股（上市與上櫃一起）。"
                  f"limit_up_top_by_value／limit_down_top_by_value 只是漲停／跌停股裡成交值最大的 {LIMIT_N} 檔，"
                  "漲停、跌停的家數看 breadth 的 limit_up、limit_down"),
    }
    if not movers and not out["indices"]:
        out["notes"] = ["目前沒有最近一個交易日的收盤資料"]
    return out


# -- get_market_report -------------------------------------------------------------------------------------------
def _report_sentences(payload: dict[str, Any]):
    """(text, footnote numbers) of every sentence: the highlights, then each section's text and item blocks (an item's
    title, the event or theme it is about, goes before its first sentence)."""
    for p in payload.get("highlights") or []:
        for s in p.get("sentences") or []:
            yield s.get("text") or "", s.get("cites") or []
    for sec in payload.get("sections") or []:
        for b in sec.get("blocks") or []:
            if b.get("type") == "text":
                for p in b.get("paragraphs") or []:
                    for s in p.get("sentences") or []:
                        yield s.get("text") or "", s.get("cites") or []
            elif b.get("type") == "items":
                for it in b.get("items") or []:
                    head = f"{it['title']}：" if it.get("title") else ""
                    for p in it.get("paragraphs") or []:
                        for i, s in enumerate(p.get("sentences") or []):
                            yield (head if i == 0 else "") + (s.get("text") or ""), s.get("cites") or []


def market_report(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.reports import service as rs

    kind = str(args.get("kind") or "latest").strip() or "latest"
    if kind not in REPORT_KINDS:
        raise ToolError(f"kind 只能是 {'、'.join(REPORT_KINDS)}")
    if not rs.enabled():
        return {"status": "none", "note": "目前沒有市場報告"}
    payload = rs.latest(ctx.db, ctx.user, None if kind == "latest" else kind)
    if payload is None:
        return {"status": "none", "note": "目前沒有已發布的市場報告"}
    head = f"{payload.get('edition_label') or ''}{payload.get('kind_label') or ''}".strip()
    sentences = [(t, c) for t, c in _report_sentences(payload) if t]
    items = []
    for fn in payload.get("footnotes") or []:
        if fn.get("kind") != "web" or not str(fn.get("url") or "").startswith("http"):
            continue
        said = "".join(t for t, cites in sentences if fn["n"] in cites)
        if said:
            when = f"，{fn['date_label']}" if fn.get("date_label") else ""
            outlet = fn.get("outlet") or ""
            items.append({"url": fn["url"], "title": str(fn.get("label") or head)[:300], "outlet": outlet,
                          "text": f"{head}（引用{outlet or '報導'}{when}）：{said}"})
    if items:
        return Citable(items)
    return {"status": "ready", "report": head, "published_at": payload.get("published_at"),
            "title": payload.get("title"), "sentences": [t for t, _ in sentences][:REPORT_SENTENCES_MAX],
            "note": "這份報告只有官方資料，沒有引用報導"}


# -- get_watchlist -----------------------------------------------------------------------------------------------
def watchlist(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.services.instruments import quote_out

    symbols = list(ctx.db.scalars(select(WatchlistItem.symbol).where(WatchlistItem.user_id == ctx.user.id)
                                  .order_by(WatchlistItem.created_at, WatchlistItem.id)))
    if not symbols:
        return {"count": 0, "items": [], "note": "觀察清單是空的"}
    quotes = ctx.md.quotes(symbols)
    items = []
    for s in symbols:
        info = ctx.md.instrument(s)
        row: dict[str, Any] = {"symbol": s, "name": info.name if info else s,
                               "market": info.market if info else None}
        q = quotes.get(s)
        if q is not None and q.price is not None:
            out = quote_out(q)
            row.update({"close": out["price"], "change": pct(out["change_pct"]),
                        "date": out["trade_date"] or (out["as_of"] or "")[:10] or None, "is_demo": out["is_demo"]})
        else:
            row["has_quote"] = False
        items.append(row)
    return {"count": len(items), "items": items,
            "units": "close 是最近的官方收盤（美股是美元）；change 是那天的漲跌幅（已經是百分比，照寫）"}


# -- get_performance ---------------------------------------------------------------------------------------------
PERFORMANCE_RANGES = ("MTD", "1M", "3M", "6M", "YTD", "1Y", "ALL")
RANGE_WORDS = {"MTD": "這個月", "1M": "近 1 個月", "3M": "近 3 個月", "6M": "近 6 個月", "YTD": "今年以來",
               "1Y": "近 1 年", "ALL": "開始記帳以來"}


def performance(ctx: ToolContext, args: dict[str, Any]) -> Any:
    """The ledger's return over a period (``services.portfolio.performance``, the 績效 page's numbers): the
    time-weighted return against the user's benchmark, and the amounts the app shows — 賺的 is the change of
    ``market_value − net_invested`` (dividends apart), with the dividends and the realized gains of the window."""
    from forliosa.services import portfolio as svc

    range_ = str(args.get("range") or "YTD").strip().upper() or "YTD"
    if range_ not in PERFORMANCE_RANGES:
        raise ToolError(f"range 只能是 {'、'.join(PERFORMANCE_RANGES)}")
    perf = svc.performance(ctx.db, ctx.user, ctx.md, range_, None, None)
    series = perf.get("series") or []
    if not series:
        return {"range": RANGE_WORDS[range_], "status": "none", "notes": perf.get("notes") or ["帳本還沒有交易"]}
    first, last = series[0], series[-1]

    def gain(p: dict[str, Any]) -> float:
        return float(p["market_value"] or 0) - float(p["net_invested"] or 0)

    dividends = sum(float(m["amount"] or 0) for m in perf.get("dividends_by_month") or [])
    realized = sum(float(y["amount"] or 0) for y in perf.get("realized_by_year") or [])
    bench = perf.get("benchmark") or {}
    return {
        "range": RANGE_WORDS[range_], "from": first["t"], "to": last["t"],
        "return": pct(perf.get("twr")), "benchmark": bench.get("name"), "benchmark_return": pct(bench.get("twr")),
        "max_drawdown": pct(perf.get("max_drawdown")),
        "gain_twd": round(gain(last) - gain(first)),
        "dividends_twd": round(dividends), "realized_twd": round(realized),
        "market_value_twd": {"from": first["market_value"], "to": last["market_value"]},
        "units": ("return 是這段期間的時間加權報酬率（不受加碼、減碼影響），benchmark_return 是同期的基準；"
                  "gain_twd 是這段期間賺的（市值減本金的變化，含還沒賣的漲跌與已實現損益，不含股利），"
                  "dividends_twd 是期間入帳的股利，realized_twd 是期間賣出的已實現損益（已經算在 gain_twd 裡）；"
                  "金額是新台幣"),
        "notes": perf.get("notes") or [],
        "is_demo": perf.get("is_demo", False),
    }


# -- suggest_follow_ups ------------------------------------------------------------------------------------------
def clean_follow_ups(raw: Any) -> list[str]:
    """At most ``FOLLOW_UPS_MAX`` distinct questions of ``FOLLOW_UP_CHARS`` characters, without links or a request to
    decide a trade for the user (「該不該買」「明牌」)."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    lo, hi = FOLLOW_UP_CHARS
    for q in raw:
        if not isinstance(q, str):
            continue
        q = re.sub(r"\s+", " ", q).strip().strip("「」\"'").strip()
        if not lo <= len(q) <= hi or _URL.search(q) or _ADVICE.search(q) or q in out:
            continue
        out.append(q)
        if len(out) >= FOLLOW_UPS_MAX:
            break
    return out


def suggest_follow_ups(ctx: ToolContext, args: dict[str, Any]) -> Any:
    questions = clean_follow_ups(args.get("questions"))
    if not questions:
        raise ToolError("questions 要是 2–3 個簡短的問題（每個 4–40 字，不問該不該買賣）")
    ctx.follow_ups[:] = questions
    return "已顯示在回答下方。不要再寫任何文字。"
