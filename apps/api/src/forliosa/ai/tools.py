"""Tools the model can call.

Client tools wrap our services. Every handler gets a ``ToolContext`` whose ``user`` is the signed-in user,
injected server-side: no schema has a user id, and every query goes through services that filter by
``user.id``. Results are compact JSON (the model pays for every token), with ``as_of`` / ``is_demo`` /
``sources`` kept so answers can name the data time and the demo-data caveat.

``draft_transaction`` never writes a transaction: it runs the same fee/tax computation as
``POST /transactions/preview``, checks the ledger stays consistent, and stores a pending ``AiDraft``. The
user signs it in the UI, which then calls ``POST /transactions`` with ``source: "ai_draft"``.

Server tools (``web_search``, ``web_fetch``) run on Anthropic's side; ``server_tools()`` builds them. A server
tool the API refuses (a 400 that names its ``type`` and says it is not allowed / supported / enabled, e.g.
"Requests sent from a sandbox with restricted network access are not allowed to use tool web_fetch_20260318")
is excluded for the rest of the process (``exclude_tool``); the request is retried once without it.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.api import serialize as ser
from forliosa.api.errors import ApiError
from forliosa.config import Settings, get_settings
from forliosa.ids import new_id
from forliosa.marketdata.base import InstrumentInfo
from forliosa.marketdata.service import MarketData
from forliosa.models import AiDraft, BrokerAccount, User
from forliosa.models import Transaction as TxnModel
from forliosa.news import taxonomy as news_taxonomy
from forliosa.news.outlets import NOT_NEWS_DOMAINS
from forliosa.timeutil import (
    TAIPEI,
    is_tw_market_open,
    is_tw_trading_day,
    iso_taipei,
    last_tw_trading_day,
    now_taipei,
    now_utc,
    today_taipei,
)

log = logging.getLogger(__name__)

MAX_RESULT_CHARS = 14_000
FOLLOW_UPS_TOOL = "suggest_follow_ups"
TXN_TYPES_FOR_DRAFT = ["buy", "sell", "cash_dividend", "stock_dividend", "deposit", "withdrawal", "fee", "tax",
                       "interest"]
TXN_TYPE_LABELS = {"buy": "買進", "sell": "賣出", "cash_dividend": "現金股利", "stock_dividend": "股票股利",
                   "split": "分割", "capital_reduction": "減資", "deposit": "存入", "withdrawal": "提出",
                   "fee": "費用", "tax": "稅", "interest": "利息"}
SECURITY_DRAFT_TYPES = {"buy", "sell", "cash_dividend", "stock_dividend"}

# Official sources for web_fetch ("official" in AI_WEB_FETCH_ALLOWED_DOMAINS) and an opt-in list of reputable
# Taiwanese finance news for web_search ("recommended" in AI_WEB_SEARCH_ALLOWED_DOMAINS).
OFFICIAL_DOMAINS = ["twse.com.tw", "tpex.org.tw", "tdcc.com.tw", "taifex.com.tw", "fsc.gov.tw", "sfb.gov.tw",
                    "cbc.gov.tw", "stat.gov.tw", "dgbas.gov.tw", "mof.gov.tw", "moea.gov.tw", "ndc.gov.tw"]
RECOMMENDED_NEWS_DOMAINS = [*OFFICIAL_DOMAINS, "cna.com.tw", "money.udn.com", "ctee.com.tw", "cnyes.com",
                            "moneydj.com", "businesstoday.com.tw", "wealth.com.tw", "technews.tw",
                            "digitimes.com.tw", "reuters.com", "bloomberg.com"]
USER_LOCATION = {"type": "approximate", "city": "Taipei", "region": "Taiwan", "country": "TW",
                 "timezone": "Asia/Taipei"}
# web_fetch never reads the TWSE website or MIS (their terms forbid automated downloads without written consent);
# web_search results are not affected. The API takes allowed_domains OR blocked_domains, and a domain covers its
# subdomains, so an allow-list entry that covers a blocked host is narrowed to the hosts we may read.
FETCH_BLOCKED_DOMAINS = ["www.twse.com.tw", "mis.twse.com.tw"]
_FETCH_NARROWED = {"twse.com.tw": ["openapi.twse.com.tw"]}
# Not news, for any question about a stock: quote and data pages, AI-written pages, forums and blogs
# (``news.outlets.NOT_NEWS_DOMAINS``, the list the news side stores nothing from) and rating aggregators (their rating
# data is their licensed product, docs/research/analyst-ratings.md). Blocked in the web_search of chat and of the 法人
# 觀點 card (``block_search``; the 2026-11-16 memo: chat answered 禾榮科's ratings from a CMoney forum post and an
# AI-written CMoney page). A domain covers its subdomains: cmoney.tw also blocks its forum and its AI Q&A
# (aigc-note.cmoney.tw), fugle.tw its blog's AI 法說會 summaries. News outlets are never on it.
RATING_AGGREGATORS = (
    "tipranks.com", "marketbeat.com", "stockanalysis.com", "tradingview.com", "wallstreetzen.com", "fintel.io",
    "public.com", "simplywall.st", "alphaspread.com", "valueinvesting.io", "tickernerd.com", "chartmill.com",
)
# Rating sites that also publish news (Benzinga's newswire, Zacks' and MarketScreener's articles: often the source of
# "why did X move" for a US stock): blocked for the card only (2026-11-16 review).
RATING_NEWS_SITES = ("benzinga.com", "zacks.com", "marketscreener.com")
# Chat's list: the same for every turn (a tool list that changes between turns invalidates the prompt cache and the
# replayed thinking), so it is fixed, not chosen by the question.
CHAT_BLOCKED_DOMAINS = tuple(dict.fromkeys((*RATING_AGGREGATORS, *NOT_NEWS_DOMAINS, "wearn.com",
                                            "ytdf.yuanta.com.tw")))
SEARCH_BLOCKED_DOMAINS = tuple(dict.fromkeys((*RATING_NEWS_SITES, *CHAT_BLOCKED_DOMAINS)))  # the card's
_REJECTED_HINT = re.compile(r"not (?:be )?(?:allowed|supported|enabled|available|permitted)|unsupported|disabled|"
                            r"does not support|do not support|cannot use|can't use", re.IGNORECASE)
_excluded: dict[str, dict[str, Any]] = {}  # server tool type -> {type, name, reason, at}
_excluded_lock = threading.Lock()


class ToolError(Exception):
    """Returned to the model as an ``is_error`` tool result (message in zh-TW)."""


@dataclass
class ToolContext:
    db: Session
    user: User
    md: MarketData
    thread_id: str | None = None
    drafts: list[dict[str, Any]] = field(default_factory=list)  # draft cards created during this turn
    charts: list[dict[str, Any]] = field(default_factory=list)  # chart cards drawn during this turn
    # drafts already made this turn, by their exact content: the same draft again is not a second card (2026-11-15
    # AI test: the model re-sent one sell three times when it could not see how to change its date)
    drafted: dict[str, dict[str, Any]] = field(default_factory=dict)
    message: str = ""  # the user's message this turn: a day it names fills a draft's omitted trade_date
    economy: bool = False  # 省錢模式: no web search this turn (notes never point to it)
    # tw_news_search's use this turn (``forliosa.ai.tw_news.TwNewsTurn``: requests, the per-turn cap, results by
    # arguments); None when the tool is not offered. One object shared by the tools that run side by side.
    tw_news: Any = None
    # suggest_follow_ups: the questions shown under this turn's answer (the last call wins)
    follow_ups: list[str] = field(default_factory=list)


@dataclass
class Citable:
    """A tool result the model can cite (產品負責人 2026-11-15: answers link the news they use): one ``search_result``
    block per item (source = the item's URL), so a sentence built on it carries a ``search_result_location`` citation
    and the answer lists it under 「出處」 with its outlet. The API takes a tool result made only of search results
    (no text block beside them), so what the model needs to know about them is in the tool's description."""

    # {url, title, outlet, text, note?, safe_text?, private?}; note: a second text block (the news tags). A
    # ``private`` item's text (a LangSearch excerpt) reaches the model in this turn only: citations, the stored turn and
    # the shared research carry its ``safe_text`` (the title line) instead (``forliosa.ai.tw_news``)
    items: list[dict[str, Any]]


@dataclass
class ToolOutcome:
    content: str | list[dict[str, Any]]
    is_error: bool = False
    draft: dict[str, Any] | None = None
    chart: dict[str, Any] | None = None
    outlets: dict[str, str] = field(default_factory=dict)  # url -> outlet of the citable items (出處 shows the outlet)
    redact: dict[str, str] = field(default_factory=dict)  # url -> title line of the private items (tw_news_search)
    private_texts: list[str] = field(default_factory=list)  # their texts: this turn's paste check only, never stored
    follow_ups: list[str] | None = None  # suggest_follow_ups: the questions it kept


def citable_content(result: Citable) -> list[dict[str, Any]]:
    """One ``search_result`` per item; an item's ``note`` (the news tags of ``get_news`` / ``search_news``) is a second
    text block, so the headline block a sentence cites stays the headline."""
    return [{"type": "search_result", "source": it["url"], "title": it["title"][:300],
             "content": [{"type": "text", "text": it["text"][:1000]},
                         *([{"type": "text", "text": it["note"][:400]}] if it.get("note") else [])],
             "citations": {"enabled": True}}
            for it in result.items]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    properties: dict[str, Any]
    required: tuple[str, ...]
    handler: Callable[[ToolContext, dict[str, Any]], Any]
    label: Callable[[dict[str, Any]], str]
    # required in the schema but "" means "not given" (strict schemas allow at most 24 optional parameters in all, so a
    # tool with several filters takes them as required strings: search_news)
    blank_ok: tuple[str, ...] = ()
    # The API takes at most 20 strict tools in a request: a tool past those is not strict and checks its own arguments
    # (tw_news_search; 2026-11-17: a 21st strict tool was answered with a 400)
    strict: bool = True

    def definition(self, eager: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "input_schema": {"type": "object", "properties": self.properties, "required": list(self.required),
                             "additionalProperties": False},
        }
        if self.strict:
            d["strict"] = True
        if eager:
            d["eager_input_streaming"] = True
        return d


# -- helpers ---------------------------------------------------------------------------------------------
def _json_default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, datetime):
        return iso_taipei(o)
    if isinstance(o, date):
        return o.isoformat()
    return str(o)


def dump(obj: Any) -> str:
    text = json.dumps(obj, ensure_ascii=False, default=_json_default, separators=(",", ":"))
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + '…（資料過長已截斷）'
    return text


def _pick(d: dict[str, Any] | None, *keys: str) -> dict[str, Any]:
    if not d:
        return {}
    return {k: d.get(k) for k in keys if k in d}


# Common nicknames investors type (2026-11-15 AI test: 「台雞電」 was read as 台汽電). Only well-established ones that
# point at a single stock; anything vaguer goes through the normal search.
NICKNAMES = {"台雞電": "2330", "台GG": "2330", "GG": "2330", "護國神山": "2330", "神山": "2330", "積積": "2330",
             "發哥": "2454", "海公公": "2317", "鴻海公公": "2317"}


def resolve_instrument(md: MarketData, text: str) -> InstrumentInfo:
    """``2330`` / ``2330.TW`` / ``台積電`` / a common nickname (``台雞電``) → instrument; ambiguous names list the
    candidates."""
    text = (text or "").strip()
    text = NICKNAMES.get(text, NICKNAMES.get(text.upper(), text))
    if not text:
        raise ToolError("請提供股票代號或名稱")
    info = md.instrument(text)
    if info is not None:
        return info
    found = md.search(text, 6)
    exact = [i for i in found if i.name == text or text in i.aliases]
    if len(exact) == 1:
        return exact[0]
    if len(found) == 1:
        return found[0]
    if found:
        cands = "、".join(f"{i.name}（{i.symbol}）" for i in found[:5])
        raise ToolError(f"「{text}」對應到多檔商品：{cands}；請用代號再試一次")
    raise ToolError(f"找不到商品「{text}」")


def _accounts(ctx: ToolContext) -> list[BrokerAccount]:
    return list(ctx.db.scalars(select(BrokerAccount).where(BrokerAccount.user_id == ctx.user.id)
                               .order_by(BrokerAccount.created_at)))


def _account_list(ctx: ToolContext) -> list[dict[str, Any]]:
    return [{"id": a.id, "name": a.name, "broker": a.broker, "currency": a.currency} for a in _accounts(ctx)]


def _own_account_id(ctx: ToolContext, account_id: str | None) -> str | None:
    if not account_id:
        return None
    acc = ctx.db.get(BrokerAccount, account_id)
    if acc is None or acc.user_id != ctx.user.id:
        raise ToolError("找不到這個帳戶")
    return acc.id


def _sample(rows: list[Any], n: int) -> list[Any]:
    """At most ``n`` evenly spaced rows, always keeping the last one."""
    if len(rows) <= n:
        return rows
    step = (len(rows) - 1) / (n - 1)
    idx = sorted({round(i * step) for i in range(n)} | {len(rows) - 1})
    return [rows[i] for i in idx]


# -- portfolio tools -------------------------------------------------------------------------------------
def get_portfolio_summary(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.services import portfolio as svc

    account_id = _own_account_id(ctx, args.get("account_id"))
    state = svc.compute_state(ctx.db, ctx.user, ctx.md, account_id)
    s = svc.summary(state, ctx.md)
    alloc = s.get("allocation") or {}
    out = {
        **_pick(s, "as_of", "market_value", "cost_basis", "unrealized_pnl", "unrealized_pnl_pct", "realized_pnl",
                "dividend_income", "total_pnl", "total_return_pct", "day_change", "day_change_pct", "is_demo"),
        "allocation": {k: [_pick(i, "label", "value", "weight") for i in (v or [])[:6]]
                       for k, v in alloc.items() if k in ("by_industry", "by_market", "by_type", "by_account")},
        # 集中度 (the 配置 segment's numbers): the user's own limits and what is above them; null limits = none set
        "concentration": s.get("concentration"),
        "upcoming_dividends": (s.get("upcoming_dividends") or [])[:6],
        "accounts": _account_list(ctx),
        "currency": "TWD",
    }
    if fx := svc.fx_tool_notes(state.fx):
        out["notes"] = fx
    return out


# Field names carry their currency so the model cannot mistake a TWD total for USD (seen in the live smoke test:
# a US holding's TWD cost read back as "美元"): *_twd = 新台幣, *_native = the instrument's own currency.
_TWD_FIELDS = ("cost_basis", "market_value", "day_change", "unrealized_pnl", "realized_pnl", "dividends_received")
_NATIVE_FIELDS = ("avg_cost", "price", "prev_close")
_MARKET_LABEL = {"TWSE": "台股", "TPEX": "台股", "US": "美股"}


def _currency_named(row: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in row.items():
        if k in _TWD_FIELDS:
            out[f"{k}_twd"] = v
        elif k in _NATIVE_FIELDS:
            out[f"{k}_native"] = v
        else:
            out[k] = v
    return out


def get_holdings(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from collections import Counter

    from forliosa.services import portfolio as svc

    account_id = _own_account_id(ctx, args.get("account_id"))
    state = svc.compute_state(ctx.db, ctx.user, ctx.md, account_id)
    rows = svc.holdings(state)
    keys = ("symbol", "name", "type", "industry", "market", "currency", "quantity", "avg_cost", "cost_basis",
            "price", "prev_close", "market_value", "day_change", "day_change_pct", "unrealized_pnl",
            "unrealized_pnl_pct", "weight", "is_demo")
    by_market = Counter(_MARKET_LABEL.get(h.get("market") or "", "其他") for h in rows)
    holdings = []
    for h in rows:
        row = _currency_named(_pick(h, *keys))
        row["has_quote"] = h.get("price") is not None
        if h.get("price_date"):
            row["price_date"] = h["price_date"]
        holdings.append(row)
    return {"as_of": iso_taipei(state.as_of), "count": len(rows), "count_by_market": dict(by_market),
            "holdings": holdings,
            "notes": ["*_twd 欄位是新台幣（美股也已換算成新台幣）；*_native 欄位是該商品的原幣（見 currency）；"
                      "quantity 為股數（1 張 = 1000 股）；has_quote 為 false 表示沒有報價，不要推測漲跌；"
                      "美股的 price_native 是美元、紐約交易日的收盤（price_date）",
                      *svc.fx_tool_notes(state.fx)]}


def get_transactions(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.api.routes.transactions import txn_out

    q = select(TxnModel).where(TxnModel.user_id == ctx.user.id)
    account_id = _own_account_id(ctx, args.get("account_id"))
    if account_id:
        q = q.where(TxnModel.account_id == account_id)
    if args.get("symbol"):
        info = resolve_instrument(ctx.md, args["symbol"])
        q = q.where(TxnModel.symbol == info.symbol)
    if args.get("type"):
        q = q.where(TxnModel.type == args["type"])
    for key, op in (("date_from", "ge"), ("date_to", "le")):
        if args.get(key):
            try:
                d = date.fromisoformat(args[key])
            except ValueError as exc:
                raise ToolError(f"{key} 必須是 YYYY-MM-DD") from exc
            q = q.where(TxnModel.trade_date >= d if op == "ge" else TxnModel.trade_date <= d)
    limit = max(1, min(int(args.get("limit") or 20), 50))
    rows = list(ctx.db.scalars(q.order_by(TxnModel.trade_date.desc(), TxnModel.id.desc()).limit(limit + 1)))
    names = {a.id: a.name for a in _accounts(ctx)}
    out = []
    for t in rows[:limit]:
        d = txn_out(t)
        info = ctx.md.instrument(t.symbol) if t.symbol else None
        out.append({**_pick(d, "trade_date", "symbol", "type", "quantity", "price", "amount", "fee", "tax",
                            "health_insurance", "currency", "note", "source"),
                    "name": info.name if info else None, "account": names.get(t.account_id)})
    return {"count": len(out), "has_more": len(rows) > limit, "transactions": out}


def get_upcoming(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.services import portfolio as svc
    from forliosa.services import recurring

    days = max(1, min(int(args.get("days") or 7), 90))
    state = svc.compute_state(ctx.db, ctx.user, ctx.md)
    today = today_taipei()
    plans = recurring.upcoming_items(ctx.db, ctx.user, ctx.md, [a.id for a in state.inp.accounts], today,
                                     today + timedelta(days=days))
    items = svc.upcoming(state, ctx.md, days, plans)
    return {"from": today, "days": days,
            "items": [_pick(i, "date", "type", "symbol", "title", "amount_estimate", "is_demo") for i in items[:30]]}


# -- stock tools -----------------------------------------------------------------------------------------
def get_stock_overview(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.news.service import english_names
    from forliosa.services import instruments as instr
    from forliosa.services import stock as svc

    info = resolve_instrument(ctx.md, args["symbol"])
    sym = info.symbol
    now = now_taipei()
    q = ctx.md.quote(sym)
    detail = instr.detail(ctx.md, sym)
    summary = detail.get("summary")
    ov = svc.overview(ctx.db, ctx.md, sym)
    divs = instr.dividends(ctx.md, sym)[:4]
    div_sources = [x for d in divs for x in d.get("sources") or []]
    divs = [_pick(d, "year", "period", "cash_dividend", "stock_dividend", "ex_dividend_date", "payment_date",
                  "status", "progress", "board_date", "cash_sources", "is_demo") for d in divs]
    quote = _pick(instr.quote_out(q), "price", "prev_close", "reference_price", "change", "change_pct",
                  "volume", "as_of", "trade_date", "is_realtime", "is_demo") if q is not None else None
    if quote is not None and quote.get("change_pct") is not None:
        from forliosa.ai.market_tools import pct

        # QA 2026-11-26: the TAIEX's 0.025 was written 「漲 0.03%」 beside this stock's move; both come written out
        quote["pct_text"] = pct(quote["change_pct"])
    english = english_names(ctx.db, info)
    market = _market_context(ctx, info, quote)
    note = _intraday_note(info, q, now, _market_close(ctx, info, now))
    return {
        **instr.instrument_out(info, ctx.md),
        "english_name": english[0] if english else None,  # the foreign-news search (「為什麼漲跌」 step 3)
        "summary": summary[:240] if isinstance(summary, str) else None,
        "themes": detail.get("themes") or [],
        "quote": quote,
        **({"market_context": market} if market else {}),
        "why_signals": ([r["text"] for r in svc.why_reasons(ctx.db, ctx.md, info, q, now.date())]
                        if q is not None and q.price is not None else []),
        **({"intraday_note": note} if note else {}),
        "overview": {k: v for k, v in ov.items() if k not in ("symbol", "sources", "etf_nav")},
        **({"etf_nav": _etf_nav_for_ai(ov["etf_nav"])} if ov.get("etf_nav") else {}),
        "recent_dividends": divs,
        "sources": list(dict.fromkeys([*ov.get("sources", []), *div_sources])),
    }


# 「台達電今天為啥跌這麼多?」 (2026-11-16) got market-wide reasons only: nothing told the model how far the stock
# moved against the market. get_stock_overview now carries the latest official index closes beside the stock's,
# the rule-based anomalies (``why_reasons``) and, while today's close is not out, a note saying so.
MARKET_CONTEXT_NOTE = ("官方收盤（收盤後公布，不是即時）；pct_text 是寫好的漲跌幅，回答照抄它（change_pct 是同一個"
                       "數字的分數，0.025＝2.5%，不要自己換算）；vs_taiex_pct_points＝這一檔的漲跌幅減加權指數的漲跌幅"
                       "（百分點，只在兩者是同一天時才有）")


def _industry_index_name(industry: str | None) -> str | None:
    """The TWSE sector index of an industry: 電子零組件業 → 電子零組件類指數, 水泥工業 → 水泥類指數, 紡織纖維 →
    紡織纖維類指數 (``index_daily`` has no row for an industry without one, e.g. 電子商務)."""
    if not industry:
        return None
    for suffix in ("工業", "業"):
        if industry.endswith(suffix) and len(industry) > len(suffix):
            return industry.removesuffix(suffix) + "類指數"
    return industry + "類指數"


def _index_close(ctx: ToolContext, name: str) -> dict[str, Any] | None:
    """The latest official close of one index as the market page shows it (``index_daily``)."""
    from forliosa.services import market_overview as mo

    found = mo._index_item("", name, mo._index_rows(ctx.db, ctx.md, name), "")
    if found is None:
        return None
    from forliosa.ai.market_tools import pct

    item = found[0]
    return {"name": name, "date": item["date"], "close": item["value"], "change_pct": item["change_pct"],
            "pct_text": pct(item["change_pct"])}


def _market_context(ctx: ToolContext, info: InstrumentInfo, quote: dict[str, Any] | None) -> dict[str, Any] | None:
    """Taiwan stocks: the TAIEX and the stock's sector index (TPEx: the 櫃買指數), with the gap to the TAIEX in
    percentage points when the stock's close is of the same day."""
    from forliosa.services import market_overview as mo

    if info.market not in ("TWSE", "TPEX") or (taiex := _index_close(ctx, mo.TAIEX)) is None:
        return None
    out: dict[str, Any] = {"taiex": taiex}
    if info.market == "TPEX":
        if (tpex := _index_close(ctx, mo.TPEX_INDEX)) is not None:
            out["tpex_index"] = tpex
    elif (name := _industry_index_name(info.industry)) and (sector := _index_close(ctx, name)) is not None:
        out["industry_index"] = sector
    pct = quote.get("change_pct") if quote else None
    day = quote.get("trade_date") if quote else None
    if pct is not None and taiex["change_pct"] is not None and day == str(taiex["date"]):
        out["vs_taiex_pct_points"] = round((pct - taiex["change_pct"]) * 100, 2)
    out["note"] = MARKET_CONTEXT_NOTE
    if day and day != str(taiex["date"]):
        # Every trading evening the stock's close is archived (from 13:35) hours before MI_INDEX's TAIEX of the
        # same session (after the 21:40 run): said outright, or the model pairs today's move with Friday's index
        out["dates_differ"] = (f"加權指數是 {_md(taiex['date'])} 的收盤，這一檔是 {_md(day)} 的收盤，不是同一天，"
                               f"不能拿來比較；{_md(day)} 加權指數漲跌多少要用 web_search 找並寫出時間")
    return out


def _market_close(ctx: ToolContext, info: InstrumentInfo, now: datetime) -> dict[str, Any] | None:
    """This market's entry of ``forliosa.closes.tw_closes`` (when its close is expected); best effort."""
    if info.market not in ("TWSE", "TPEX"):
        return None
    from forliosa.closes import tw_closes

    try:
        return next((c for c in tw_closes(ctx.db, now) if c["market"] == info.market), None)
    except Exception as exc:  # never fail the tool over the expected time
        log.warning("get_stock_overview: closes not read: %s", exc)
        ctx.db.rollback()
        return None


def _interim_close(ctx: ToolContext, symbol: str, day: date) -> bool:
    """``symbol``'s stored close of ``day`` is the interim evening close (close only; forliosa.closes)."""
    from forliosa.archive import INTERIM_CLOSE_SOURCE
    from forliosa.models import PriceDaily

    if getattr(ctx, "db", None) is None:
        return False
    try:
        return ctx.db.scalar(select(PriceDaily.source).where(PriceDaily.symbol == symbol,
                                                            PriceDaily.date == day)) == INTERIM_CLOSE_SOURCE
    except Exception as exc:  # best effort: never fail the tool over it
        log.warning("get_technicals: interim close not checked: %s", exc)
        ctx.db.rollback()
        return False


def _md(day: Any) -> str:
    """「11/13」 from a date or its ISO string."""
    d = date.fromisoformat(str(day)[:10])
    return f"{d.month}/{d.day}"


def _intraday_note(info: InstrumentInfo, q: Any, now: datetime, close: dict[str, Any] | None = None) -> str | None:
    """While the quote is older than the session it should show: during the session (盤中), or after the close until
    that session's close is stored — also after midnight, when the session is no longer "today". ``close`` is this
    market's entry of ``forliosa.closes.tw_closes``: its expected window is passed on. The prompt's intraday protocol
    starts from this note."""
    from forliosa.closes import due_session

    if info.market not in ("TWSE", "TPEX") or q is None or q.trade_date is None:
        return None
    now = now.astimezone(TAIPEI)
    today = now.date()
    if is_tw_market_open(now):
        session, when = today, "盤中"
    else:
        session = due_session(now)
        when = ("今天已收盤，但今天的官方收盤價還沒公布" if session == today
                else f"{_md(session)} 的官方收盤價還沒公布")
    if q.trade_date >= session:
        return None
    label = "今天" if session == today else _md(session)
    expected = ""
    # stored only as the interim evening close (no ETFs in it): the window is the official file's (forliosa.closes)
    waiting = close and (not close.get("stored") or close.get("interim"))
    if waiting and close.get("expected_from") and close.get("expected_to"):
        from forliosa.closes import expect_update, window_text

        start, end = (datetime.fromisoformat(close[k]) for k in ("expected_from", "expected_to"))
        if text := window_text(start, end, now):
            expected = f"這個市場的官方收盤價{expect_update(text)}（畫面上也這樣寫）。"
    day = f"{q.trade_date.month}/{q.trade_date.day}"
    # only for a question about the price or the move (2026-11-16: a news-and-ratings question got the close, the
    # TAIEX and 「今天的收盤價尚未公布」 because this note asked for them unconditionally)
    return (f"{when}：quote、market_context 與 why_signals 都是 {day} 的官方收盤資料，不是{label}的。{expected}"
            f"使用者問{label}的價格或漲跌時，{label}這一檔與加權指數漲跌多少要用 web_search 找可引用的來源並寫出時間；"
            "只問消息、評等或財報時不用寫股價，也不用說收盤價還沒公布")


ETF_NAV_AI_NOTE = ("premium_pct = close ÷ NAV − 1 on premium_date only (the newest date with both an official close "
                   "and a NAV; never mix dates). Positive = 溢價 (trading above NAV), negative = 折價. Say the date. "
                   "history_range.points counts days that have both, not trading days: say the from–to dates, and "
                   "missing_trading_days are archive gaps in between. "
                   "There is no tracking error: the index's daily data has no open licence.")


def _etf_nav_for_ai(block: dict[str, Any]) -> dict[str, Any]:
    """The overview's ``etf_nav`` for the model: the latest values, the range of the archived history and its last
    10 points (the page draws up to 60). ``points`` counts days with data, not trading days: archive gaps inside
    ``from``–``to`` are counted in ``missing_trading_days``."""
    hist = block.get("history") or []
    out = {k: block.get(k) for k in ("nav", "nav_date", "currency", "close", "close_date", "premium_pct",
                                     "premium_date", "history_start", "notes")}
    if hist:
        lo = min(hist, key=lambda p: p["premium_pct"])
        hi = max(hist, key=lambda p: p["premium_pct"])
        out["history_range"] = {"points": len(hist), "from": hist[0]["t"], "to": hist[-1]["t"],
                                "missing_trading_days": len(block.get("history_missing") or []),
                                "min": {"t": lo["t"], "premium_pct": lo["premium_pct"]},
                                "max": {"t": hi["t"], "premium_pct": hi["premium_pct"]}}
        out["recent"] = hist[-10:]
    out["note"] = ETF_NAV_AI_NOTE
    return out


HISTORY_RANGE_CHOICES = ["5D", "1M", "6M", "YTD", "1Y", "5Y"]


def get_stock_history(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.services import instruments as instr

    info = resolve_instrument(ctx.md, args["symbol"])
    h = instr.history(ctx.md, info.symbol, args["range"])
    candles = h["candles"]
    stats: dict[str, Any] = {}
    if candles:
        first, last = candles[0], candles[-1]
        hi = max(candles, key=lambda c: c["h"] if c["h"] is not None else c["c"])
        lo = min(candles, key=lambda c: c["l"] if c["l"] is not None else c["c"])
        stats = {
            "start": {"t": first["t"], "close": first["c"]}, "end": {"t": last["t"], "close": last["c"]},
            "change_pct": round((last["c"] - first["c"]) / first["c"], 4) if first["c"] else None,
            "high": {"t": hi["t"], "price": hi["h"]}, "low": {"t": lo["t"], "price": lo["l"]},
            "avg_volume": int(sum(c["v"] or 0 for c in candles) / len(candles)),
            "days": len(candles),
        }
    return {"symbol": info.symbol, "name": info.name, "range": args["range"], "stats": stats,
            "closes": [{"t": c["t"], "c": c["c"]} for c in _sample(candles, 30)],
            "is_demo": h.get("is_demo"), "sources": h.get("sources"), "notes": h.get("notes") or []}


# -- technical analysis -----------------------------------------------------------------------------------
# A provisional price further than this from the latest close is outside the ±10 % daily limit of Taiwan stocks and
# ETFs (the margin covers tick rounding): a typo or the wrong stock rather than a price.
PROVISIONAL_LIMIT = 0.105
TECHNICALS_MAX_BARS = 500  # two years of daily bars: every indicator has settled long before
PRICE_SOURCE_LABELS = {"user": "你提供的價格", "web": "網路來源報導的價格"}
TECHNICALS_UNITS = ("價格是未還原權息的原始價（除權息日會有缺口）；*_pct、percent_b、bandwidth 為分數"
                    "（0.0123＝1.23%）；ratio_prev5／ratio_prev20＝最新成交量 ÷ 前 5／20 日均量（量比）；"
                    "成交量單位為股；RSI、K、D 介於 0 到 100；events 是最近 10 個交易日發生的事實，不是買賣建議")
PROVISIONAL_CAVEAT = ("不是官方報價，也不是即時報價：把這個價格暫時當成 {day} 的收盤價算出來的結果，"
                      "盤中還會變動，收盤後以官方收盤價為準")


def _sessions_between(after: date, upto: date) -> int:
    """Taiwan trading days after ``after`` up to and including ``upto``."""
    count, d = 0, after + timedelta(days=1)
    while d <= upto:
        count += is_tw_trading_day(d)
        d += timedelta(days=1)
    return count


def _plain(x: float) -> str:
    """1085.0 → "1085", 52.40 → "52.4"."""
    return f"{x:.4f}".rstrip("0").rstrip(".")


def _provisional_block(info: InstrumentInfo, bars: list[Any], ex_dates: list[date], price: float, source: str,
                       price_time: str | None, notes: list[str]) -> dict[str, Any] | None:
    """The indicators with ``price`` as a stand-in bar for the trading day that has no official close yet, or
    ``None`` (and a note) when there is no such day. A price outside the daily limit is a ``ToolError``."""
    from forliosa.domain import technicals as ta

    last = bars[-1]
    if info.market not in ("TWSE", "TPEX"):
        notes.append("暫定價只支援台股與台股 ETF，沒有使用提供的價格")
        return None
    day = last_tw_trading_day(today_taipei())
    if day <= last.t:
        notes.append(f"{last.t.isoformat()} 的官方收盤價已經有了（{_plain(last.c)}），"
                     f"沒有使用提供的價格 {_plain(price)}")
        return None
    sessions = _sessions_between(last.t, day)
    ex_days = [d for d in ex_dates if last.t < d <= day]
    move = price / last.c - 1
    if ex_days:
        # the reference price of an ex-dividend day is below the previous close: the limit cannot be checked from it
        notes.append(f"{ex_days[-1].isoformat()} 是除權息日：與前一個收盤價的差距含除權息的影響，沒有做漲跌幅檢查")
    elif not (1 - PROVISIONAL_LIMIT) ** sessions <= 1 + move <= (1 + PROVISIONAL_LIMIT) ** sessions:
        raise ToolError(
            f"價格 {_plain(price)} 和{info.name}（{info.symbol}）最近的收盤價 {_plain(last.c)}"
            f"（{last.t.isoformat()}）相差 {move:+.1%}，超出台股單日漲跌幅限制（10%），很可能是價格打錯或不是這一檔。"
            "沒有計算；請向使用者確認價格與股票後再試，不要自行修改價格")
    if sessions > 1:
        notes.append(f"存檔的最新收盤是 {last.t.isoformat()}，到 {day.isoformat()} 之間還有 {sessions - 1} 個交易日"
                     "沒有資料，暫定價的指標可能失真")
    block = ta.analyze([*bars, ta.Bar(t=day, c=price, o=price, h=price, l=price)], provisional=True)
    block.pop("close")
    events = block.pop("events")
    return {"official": False, "price": price, "price_source": source,
            "price_label": PRICE_SOURCE_LABELS[source], "price_time": price_time or "未提供",
            "caveat": PROVISIONAL_CAVEAT.format(day=day.isoformat()), **block,
            "events_if_closed_at_price": events}


def get_technicals(ctx: ToolContext, args: dict[str, Any]) -> Any:
    """Technical indicators from the archived daily closes (``domain.technicals``), and — with a price the user
    stated or the model found in a cited web source — the same indicators with that price as a stand-in for the
    day that has not closed. Never fetches a quote: the only prices are the archive's and the one passed in."""
    from forliosa.domain import technicals as ta
    from forliosa.services import instruments as instr

    info = resolve_instrument(ctx.md, args["symbol"])
    price, source = args.get("price"), args.get("price_source")
    if price is not None:
        if isinstance(price, bool) or not isinstance(price, int | float) or not math.isfinite(price) or price <= 0:
            raise ToolError("price 必須是大於 0 的數字；沒有確定的價格就不要傳 price")
        if source not in PRICE_SOURCE_LABELS:
            raise ToolError("有 price 時必須說明來源：price_source 填 user（使用者在對話中提供）"
                            "或 web（有引用來源的網路資料）")
    h = instr.history(ctx.md, info.symbol, "5Y")
    bars = [ta.Bar(t=c["t"], c=c["c"], o=c["o"], h=c["h"], l=c["l"], v=c["v"])
            for c in h["candles"] if c["c"] is not None][-TECHNICALS_MAX_BARS:]
    notes: list[str] = list(h.get("notes") or [])
    if bars and _interim_close(ctx, info.symbol, bars[-1].t):
        # the evening's interim close (forliosa.closes): the chart draws it with open = high = low = close and no
        # volume; here they are unknown, so no opening gap, gap or volume ratio is made up from it (2026-11-16 review)
        bars[-1] = ta.Bar(t=bars[-1].t, c=bars[-1].c)
        notes.append(f"{bars[-1].t.isoformat()} 是晚上先進來的收盤價，只有收盤價：沒有開盤、最高、最低價與成交量"
                     "（不提供跳空與量比），官方的完整資料稍後補上")
    out: dict[str, Any] = {"symbol": info.symbol, "name": info.name, "currency": info.currency}
    if not bars:
        out["as_of_close"] = None
        if not notes:
            notes.append("目前沒有這檔的日線資料，無法計算技術指標")
        if price is not None:
            notes.append("沒有收盤資料可以接續，沒有使用提供的價格")
    else:
        # demo bars (personal mode) are not anybody's official close; ``is_demo`` below says so as well
        out["as_of_close"] = {"official": not h.get("is_demo"), **ta.analyze(bars)}
        ex_dates = sorted({d["ex_dividend_date"] for d in instr.dividends(ctx.md, info.symbol)
                           if d.get("ex_dividend_date")})
        window = bars[-max(ta.RANGE_PERIODS):]
        if ex := [d for d in ex_dates if window[0].t <= d <= window[-1].t]:
            days = "、".join(d.isoformat() for d in ex[-4:])
            notes.append(f"近 {len(window)} 個交易日內的除權息日：{days}；價格未還原，當天的缺口與跨過那天的均線、"
                         "指標都含除權息的影響")
        if price is not None:
            time_text = str(args.get("price_time") or "").strip()[:80] or None
            block = _provisional_block(info, bars, ex_dates, float(price), source, time_text, notes)
            if block is not None:
                out["with_provisional_price"] = block
    return {**out, "units": TECHNICALS_UNITS, "notes": notes, "sources": h.get("sources"),
            "is_demo": h.get("is_demo")}


def get_valuation(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.services import instruments as instr

    info = resolve_instrument(ctx.md, args["symbol"])
    v = instr.valuation(ctx.md, info.symbol, "5Y")
    series = v.get("series") or []
    monthly: dict[str, dict] = {}
    for p in series:
        monthly[str(p["t"])[:7]] = p
    pts = list(monthly.values())[-12:]
    per_vals = [p["per"] for p in series if p.get("per") is not None]
    return {
        "symbol": info.symbol, "name": info.name, "current": v.get("current"),
        "per_range_5y": {"min": min(per_vals), "max": max(per_vals)} if per_vals else None,
        "per_multiples": v.get("per_multiples"), "pbr_multiples": v.get("pbr_multiples"),
        "latest": series[-1] if series else None,
        "monthly_last_12": [_pick(p, "t", "close", "eps_ttm", "per", "pbr", "dividend_yield") for p in pts],
        "notes": v.get("notes") or [], "is_demo": v.get("is_demo"), "sources": v.get("sources"),
    }


def get_chips(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.services import stock as svc

    info = resolve_instrument(ctx.md, args["symbol"])
    c = svc.chips(ctx.db, ctx.md, info.symbol, args["range"])
    inst = c.get("institutional") or []
    totals = {k: round(sum((r.get(k) or 0) for r in inst), 1) for k in ("foreign", "trust", "dealer", "total")}
    fh = c.get("foreign_holding_pct") or []
    mh = c.get("major_holders")
    return {
        "symbol": info.symbol, "name": info.name, "range": args["range"],
        "institutional_net_lots_total": totals if inst else None,
        "institutional_last_10_days": inst[-10:],
        "margin_last_5_days": (c.get("margin") or [])[-5:],
        "foreign_holding_pct": {"first": fh[0], "last": fh[-1]} if fh else None,
        "major_holders": {"as_of": mh.get("as_of"),
                          "buckets": [_pick(b, "label", "level", "holders", "pct") for b in mh.get("buckets", [])]}
        if mh else None,
        "units": "法人與融資券單位為張；pct 為比率",
        "notes": c.get("notes") or [], "sources": c.get("sources"),
    }


def get_financials(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.services import instruments as instr
    from forliosa.services import stock as svc

    info = resolve_instrument(ctx.md, args["symbol"])
    f = svc.financials(ctx.db, ctx.md, info.symbol, args["period"])
    periods = f.get("periods") or []
    keep = 8
    cut = max(0, len(periods) - keep)

    def tail(group: dict[str, list] | None) -> dict[str, list]:
        return {k: v[cut:] for k, v in (group or {}).items()}

    us = f.get("currency") == "USD"
    revenue = instr.revenue(ctx.md, info.symbol)[-6:] if info.type == "stock" and not us else []
    out = {
        "symbol": info.symbol, "name": info.name, "period": args["period"], "periods": periods[cut:],
        "income": tail(f.get("income")), "balance": tail(f.get("balance")), "cashflow": tail(f.get("cashflow")),
        "margins": tail(f.get("margins")),
        "units": ("金額單位美元；EPS 為稀釋每股盈餘（美元）；periods 是公司會計年度（FY2026Q1 = 會計年度 2026 第一季，"
                  "period_ends 是各期最後一天）；margins 為比率") if us else "金額單位新台幣千元；margins 為比率",
        "notes": f.get("notes") or [], "sources": f.get("sources"),
    }
    if us:
        out["period_ends"] = (f.get("period_ends") or [])[cut:]
        shares = f.get("shares")
        # diluted_average lines up with periods: cut it the same way (outstanding is one cover-page figure)
        out["shares"] = {**shares, "diluted_average": (shares.get("diluted_average") or [])[cut:]} if shares else None
        out["as_of"] = f.get("as_of")
    else:
        out["monthly_revenue_last_6"] = revenue
    return out


def get_events(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.services import stock as svc

    info = resolve_instrument(ctx.md, args["symbol"])
    evs = svc.events(ctx.db, ctx.md, ctx.user, info.symbol, bool(args.get("mine_only")))
    today = today_taipei()
    upcoming = [e for e in evs if e["date"] >= today][-10:]
    past = [e for e in evs if e["date"] < today][:10]
    keys = ("date", "type", "form", "title", "detail", "url", "mine", "amount_estimate")
    return {"symbol": info.symbol, "name": info.name, "today": today,
            "upcoming": [_pick(e, *keys) for e in upcoming], "recent": [_pick(e, *keys) for e in past]}


NEWS_TOOL_MAX = 12
NEWS_RECENT = timedelta(hours=48)
NEWS_OLD_NOTICE = timedelta(days=14)
NEWS_OLD_NOTICE_MAX = 4


def _published(n: dict[str, Any]) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(n.get("published_at") or ""))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=TAIPEI)


def news_for_ai(items: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """The stock page's list (90 days of 公告 first, then media) reordered for a question about today. 2026-11-16:
    a stock with a dozen 公告 left no room for the morning's media headline in the 12 the tool returns. Everything
    of the last 48 hours comes first, newest first; then the 公告 (at most 4 of those older than 14 days); then the
    older media headlines."""
    recent, notices, media = [], [], []
    old_notices = 0
    for n in items:
        at = _published(n)
        if at is not None and now - at <= NEWS_RECENT:
            recent.append((at, n))
        elif n.get("category") == "media":
            media.append(n)
        elif at is None or now - at > NEWS_OLD_NOTICE:
            old_notices += 1
            if old_notices <= NEWS_OLD_NOTICE_MAX:
                notices.append(n)
        else:
            notices.append(n)
    recent.sort(key=lambda x: x[0], reverse=True)
    return [*(n for _, n in recent), *notices, *media][:NEWS_TOOL_MAX]


def _news_time(n: dict[str, Any], today: date) -> str:
    """「今天 11/16 09:12」「昨天 11/15 21:40」「11/13 14:05」; no time for a date-only headline or a 公告 without
    one (stored at 00:00), so this morning's story is not mistaken for Friday's."""
    at = _published(n)
    if at is None:
        return ""
    at = at.astimezone(TAIPEI)
    rel = {today: "今天 ", today - timedelta(days=1): "昨天 "}.get(at.date(), "")
    clock = "" if n.get("date_only") or (at.hour, at.minute) == (0, 0) else f" {at:%H:%M}"
    return f"{rel}{at.month}/{at.day}{clock}"


def _news_tags(ctx: ToolContext, items: list[dict[str, Any]]) -> dict[str, Any]:
    """url -> the media headline's tags (:mod:`forliosa.news.tags`; 公告 have none)."""
    from forliosa.news.tags import tags_for_urls

    return tags_for_urls(ctx.db, [str(n["url"]) for n in items if n.get("category") == "media" and n.get("url")])


def get_news(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.services import stock as svc

    info = resolve_instrument(ctx.md, args["symbol"])
    now = now_utc()
    today = now.astimezone(TAIPEI).date()
    items = news_for_ai(svc.news(ctx.db, ctx.md, info.symbol), now)
    tags = _news_tags(ctx, items)
    linked = [n for n in items if str(n.get("url") or "").startswith("http") and n.get("title")]
    if not linked:  # nothing to cite: the headlines (if any) as data
        out: dict[str, Any] = {
            "symbol": info.symbol, "name": info.name,
            "headlines": [{**_pick(n, "published_at", "title", "category", "outlet", "source"),
                           **({k: v for k, v in tags[n["url"]].view().items() if k != "related" and v}
                              if n.get("url") in tags else {})} for n in items],
            "sources": list(dict.fromkeys(x for n in items for x in n.get("sources") or [])),
        }
        if not items:
            out["note"] = ("最近沒有公告或媒體標題；台股的新聞報導用 tw_news_search（intent news）找"
                           if ctx.tw_news is not None and info.market != "US"
                           else "最近沒有公告或媒體標題；需要新聞時請改用 web_search")
        return out

    def outlet(n: dict[str, Any]) -> str:
        if n.get("category") == "media":
            return n.get("outlet") or ""
        return "公開資訊觀測站" if n.get("category") == "material_info" else "臺灣證券交易所"

    def kind(n: dict[str, Any]) -> str:
        """What the item starts with: the media outlet, or what kind of 公告 it is. Not the website of a 公告: the model
        copied 「公開資訊觀測站，11/10 15:02：」 into its answers (2026-11-16, 禾榮科: 3 of 5; 出處 still shows it)."""
        if n.get("category") == "media":
            return outlet(n)
        return "公司公告" if n.get("category") == "material_info" else "交易所公告"

    return Citable([{"url": n["url"], "title": n["title"], "outlet": outlet(n),
                     "text": "，".join(x for x in (kind(n), _news_time(n, today)) if x) + f"：{n['title']}",
                     "note": tags[n["url"]].note(ctx.md) if n["url"] in tags else ""}
                    for n in linked])


SEARCH_NEWS_MAX = 15
SEARCH_NEWS_DEFAULT_DAYS = 7


def search_news(ctx: ToolContext, args: dict[str, Any]) -> Any:
    """Our stored media headlines by theme, sector, stock and/or keyword (``forliosa.news.tags.search``)."""
    from forliosa.news import taxonomy as tx
    from forliosa.news.tags import search

    theme_text, sector_text = (args.get("theme") or "").strip(), (args.get("sector") or "").strip()
    theme = tx.theme_id(theme_text) if theme_text else None
    if theme_text and theme is None:
        raise ToolError(f"沒有「{theme_text}」這個主題；可用的主題：{'、'.join(t.label for t in tx.THEMES)}")
    sector = tx.sector_id(sector_text) if sector_text else None
    if sector_text and sector is None:
        raise ToolError(f"沒有「{sector_text}」這個類股；可用的類股：{'、'.join(t.label for t in tx.SECTORS)}")
    info = resolve_instrument(ctx.md, args["symbol"]) if (args.get("symbol") or "").strip() else None
    keyword = (args.get("keyword") or "").strip()[:40]
    try:
        days = int(args.get("days") or SEARCH_NEWS_DEFAULT_DAYS)
    except (TypeError, ValueError):
        days = SEARCH_NEWS_DEFAULT_DAYS
    days = max(1, min(90, days))
    settings = get_settings()
    now = now_utc()
    today = now.astimezone(TAIPEI).date()
    found = search(ctx.db, ctx.md, theme=theme, sector=sector, symbol=info.symbol if info else None,
                   keyword=keyword or None, days=days, limit=SEARCH_NEWS_MAX, now=now, settings=settings)
    if not found:
        filters = {k: v for k, v in (("theme", tx.theme_label(theme) if theme else None),
                                     ("sector", tx.sector_label(sector) if sector else None),
                                     ("symbol", info.symbol if info else None), ("keyword", keyword or None)) if v}
        kept = settings.news_retention_days
        return {"filters": filters, "days": days, "headlines": [],
                "note": "站內存的新聞標題裡沒有符合的" + (f"（新聞標題只保留 {kept} 天）" if days > kept else "")
                + "；需要時改用 web_search"}
    return Citable([{"url": n["url"], "title": n["title"], "outlet": n["outlet"],
                     "text": "，".join(x for x in (n["outlet"], _news_time(n, today)) if x) + f"：{n['title']}",
                     "note": "；".join(x for x in (
                         "歸在：" + "、".join(f"{s['symbol'].split('.')[0]} {s['name'] or ''}".strip()
                                            for s in n["stocks"]) if n["stocks"] else n.get("market", ""),
                         n["tag_note"]) if x)}
                    for n in found])


# 「禾榮科 機構給出的評級與目標價為何?」 (2026-11-16) was answered from web search alone (a forum post, an AI-written
# page) while the stock page's 法人觀點 card had its own verified list: the card's current entry, read only. The
# chat answers from it (decision 1 of the 2026-11-16 memo): its items, or "no data" when the card looked recently and
# found none; it searches the web only when the card has not looked (or could not).
_ANALYST_SEARCH = "用 web_search 找新聞報導裡機構最新的評等與目標價"
_ANALYST_NOTES = {"none": f"個股頁的法人觀點今天還沒有人查；{_ANALYST_SEARCH}",
                  "pending": f"個股頁的法人觀點還在整理；{_ANALYST_SEARCH}",
                  "unavailable": f"個股頁的法人觀點這次沒有查到；{_ANALYST_SEARCH}"}
_UNNAMED_LABEL = re.compile(r"^未具名外資(?:（(.+?)）)?$")
_ANALYST_WHEN = {"none": "個股頁的法人觀點今天還沒有人查", "pending": "個股頁的法人觀點還在整理",
                 "unavailable": "個股頁的法人觀點這次沒有查到"}


def _analyst_note(ctx: ToolContext, info: InstrumentInfo, status: str) -> str:
    """Where to look when the card has nothing yet: a Taiwan stock with tw_news_search offered asks it first (the
    round-2 A/B's wording), then the web — or, in 省錢模式, says there is no data; otherwise the web, as before."""
    if ctx.tw_news is None or info.market == "US":
        return _ANALYST_NOTES.get(status, _ANALYST_NOTES["none"])
    then = ("這一題沒有網路搜尋，回答目前沒有機構評等與目標價的資料" if ctx.economy
            else "再用 web_search 找新聞報導裡機構最新的評等與目標價")
    return (f"{_ANALYST_WHEN.get(status, _ANALYST_WHEN['none'])}；台股先用 tw_news_search（intent analyst_targets）找，"
            f"它回 status none 時，{then}")


def _price_text(x: float) -> str:
    """1300.0 → "1,300", 52.40 → "52.4"."""
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def _analyst_line(item: dict[str, Any], today: date) -> str:
    """「元富投顧，10/2，維持，評等「買進」，目標價 700 元」 (the year only when it is not this year). An unnamed
    foreign broker (the card's 「未具名外資（日系）」) reads 「一家日系外資」, the way the answer should write it;
    an item the card labels 舊資料 (older than ``analyst.RECENT_DAYS``) ends with 「較舊的報導」, so it goes last."""
    d = date.fromisoformat(str(item["date"])[:10])
    who = str(item["institution"])
    if item.get("unnamed") and (m := _UNNAMED_LABEL.match(who)):
        who = f"一家{m.group(1) or ''}外資"
    parts = [who, f"{d.month}/{d.day}" if d.year == today.year else f"{d.year}/{d.month}/{d.day}"]
    if item.get("action"):
        parts.append(item["action"])
    if item.get("rating_text"):
        parts.append(f"評等「{item['rating_text']}」")
    if item.get("target_price") is not None:
        price = _price_text(float(item["target_price"]))
        parts.append(f"目標價 US${price}" if item.get("currency") == "USD" else f"目標價 {price} 元")
    if item.get("old"):
        parts.append("較舊的報導")
    return "，".join(parts)


def get_analyst_views(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.ai import analyst

    info = resolve_instrument(ctx.md, args["symbol"])
    if info.type != "stock":
        return {"symbol": info.symbol, "name": info.name, "status": "none",
                "note": "ETF 沒有個別機構的評等與目標價"}
    views = analyst.cached(ctx.db, info.symbol, now_utc())
    items = [it for it in views["items"] if str(it.get("url") or "").startswith("http")] \
        if views["status"] == "ready" else []
    if not items:
        note = _analyst_note(ctx, info, views["status"])
        if views["status"] == "ready":  # looked recently and found none: the chat says so, like the card
            asked = datetime.fromisoformat(views["as_of"]) if views.get("as_of") else None
            when = f"{asked.month}/{asked.day} " if asked else ""
            note = (f"個股頁的法人觀點 {when}查過新聞報導，沒有機構的評等或目標價：回答「目前沒有機構評等與目標價的"
                    "資料」，不用再搜尋")
        return {"symbol": info.symbol, "name": info.name, "status": views["status"], "note": note}
    today = today_taipei()
    return Citable([{"url": it["url"], "title": it.get("source_title") or info.name, "outlet": "",
                     "text": _analyst_line(it, today)} for it in items])


TW_NEWS_TOOL = "tw_news_search"
_TW_NEWS_WORDS = {"news": "新聞", "why_move": "漲跌原因", "analyst_targets": "目標價", "earnings_call": "法說會",
                  "revenue": "營收", "dividend": "配息"}


def tw_news_search(ctx: ToolContext, args: dict[str, Any]) -> Any:
    """LangSearch for one Taiwan stock or the Taiwan market (``forliosa.ai.tw_news``)."""
    from forliosa.ai import tw_news

    return tw_news.tw_news_search(ctx, args)


def _tw_news_label(a: dict[str, Any]) -> str:
    intent = a.get("intent")
    if intent == "market":
        return "搜尋台灣新聞：大盤"
    sym = str(a.get("symbol") or "").strip().upper()[:20]
    return " ".join(x for x in (f"搜尋台灣新聞：{sym}", _TW_NEWS_WORDS.get(str(intent), "新聞")) if x)


def get_position(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.services import stock as svc
    from forliosa.services.portfolio import compute_state, fx_tool_notes

    info = resolve_instrument(ctx.md, args["symbol"])
    state = compute_state(ctx.db, ctx.user, ctx.md)
    pos = svc.position(ctx.db, ctx.md, ctx.user, info.symbol, state)
    if pos is None:
        return {"symbol": info.symbol, "name": info.name, "held": False,
                "note": "目前沒有持有這檔；過去的交易可用 get_transactions 查詢"}
    markers = pos.get("markers") or []
    notes = ["*_twd 欄位是新台幣；*_native 欄位是該商品的原幣（見 currency）；quantity 為股數；"
             "recent_trades 的 price、amount 為原幣"]
    if pos.get("currency", "TWD") != "TWD":
        notes.extend(fx_tool_notes(state.fx))  # the same book that valued the position above
    return {"symbol": info.symbol, "name": info.name, "held": True,
            **_currency_named({k: v for k, v in pos.items() if k not in ("markers", "symbol", "sources")}),
            "trades_count": len(markers), "recent_trades": markers[-10:], "notes": notes}


def get_related_stocks(ctx: ToolContext, args: dict[str, Any]) -> Any:
    """The stock page's 相關股票 row without its sparklines: who to look at when the stock itself has no news."""
    from forliosa.services import related as svc

    info = resolve_instrument(ctx.md, args["symbol"])
    r = svc.related(ctx.db, ctx.md, ctx.user, info.symbol)
    return {"symbol": info.symbol, "name": info.name, "industry": info.industry,
            "related": [_pick(i, "symbol", "name", "reason_label", "close", "change_pct", "as_of", "is_index",
                              "is_demo") for i in r["items"]],
            "units": "close 是最新的官方收盤價（as_of 是日期），不是今天的即時價；change_pct 為分數",
            "notes": r["notes"], "sources": r["sources"]}


def draw_chart(ctx: ToolContext, args: dict[str, Any]) -> Any:
    """Draws one chart card from server-side data (``charts``); the model never supplies a data point."""
    from forliosa.ai import charts

    try:
        out = charts.draw(ctx.db, ctx.md, ctx.user, resolve_instrument, args, len(ctx.charts))
    except charts.ChartError as exc:
        raise ToolError(str(exc)) from exc
    if out["card"] is not None:
        ctx.charts.append(out["card"])
    return out["result"]


def search_instruments(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.services import instruments as instr

    query = (args["query"] or "").strip()
    nick = NICKNAMES.get(query, NICKNAMES.get(query.upper()))
    found = ctx.md.search(nick or query, 10)
    out: dict[str, Any] = {"results": [instr.instrument_out(i, ctx.md) for i in found]}
    if nick:
        out["note"] = f"「{query}」是 {nick} 的俗稱"
    return out


# -- draft_transaction -----------------------------------------------------------------------------------
def _fmt_qty(q: Decimal) -> str:
    q = q.normalize()
    if q >= 1000 and q % 1000 == 0:
        return f"{int(q / 1000)} 張（{int(q):,} 股）"
    return f"{q:,f} 股"


_WEEKDAY = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_REL_DAY = {"今天": 0, "今日": 0, "昨天": 1, "昨日": 1, "前天": 2, "大前天": 3}
_MONTH_DAY = re.compile(r"(?<![\d/.])(1[0-2]|0?[1-9])\s*(?:/|月)\s*(3[01]|[12]\d|0?[1-9])(?:\s*日|號)?(?![\d/.%])")


def day_in_message(message: str, today: date) -> tuple[date, str] | None:
    """The one trade day a message names (昨天, 前天, 上週五, 週三, 11/12, 11月12日) → (date, the words); None when it
    names none or several. 2026-11-15 AI test: the model left trade_date out for 「昨天賣了…」 even when told to fill
    it, so the draft tool reads the day itself."""
    found: list[tuple[date, str]] = []
    for m in re.finditer(r"大前天|前天|昨天|昨日|今天|今日", message):
        found.append((today - timedelta(days=_REL_DAY[m.group(0)]), m.group(0)))
    for m in re.finditer(r"(上上|上)?(?:週|周|星期|禮拜)([一二三四五六日天])", message):
        weeks = {"上上": 2, "上": 1}.get(m.group(1) or "", 0)
        monday = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks)
        d = monday + timedelta(days=_WEEKDAY[m.group(2)])
        if weeks or d <= today:
            found.append((d, m.group(0)))
    for m in _MONTH_DAY.finditer(message):
        try:
            d = date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            continue
        found.append((d if d <= today else d.replace(year=today.year - 1), m.group(0)))
    days = {d for d, _ in found}
    return found[0] if len(days) == 1 else None


def draft_transaction(ctx: ToolContext, args: dict[str, Any]) -> Any:
    """Preview + pending draft. Never inserts a ``transactions`` row."""
    from forliosa.api.schemas import TransactionIn
    from forliosa.services import recurring
    from forliosa.services import transactions as txn_svc

    ttype = args["type"]
    notes: list[str] = []
    info: InstrumentInfo | None = None
    symbol_text = (args.get("symbol") or "").strip()
    if ttype in SECURITY_DRAFT_TYPES:
        info = resolve_instrument(ctx.md, symbol_text)
    accounts = _accounts(ctx)
    if not accounts:
        raise ToolError("使用者還沒有券商帳戶；請先到帳本建立帳戶，再來記帳")
    account: BrokerAccount | None = None
    if args.get("account_id"):
        account = next((a for a in accounts if a.id == args["account_id"]), None)
        if account is None:
            raise ToolError("找不到這個帳戶")
    elif len(accounts) == 1:
        account = accounts[0]
    elif ttype == "sell" and info is not None:
        from forliosa.services import portfolio as psvc

        led = psvc.ledger_view(ctx.db, ctx.user, ctx.md).ledger
        holding = [a for a in accounts if led.held(a.id, info.symbol) > 0]
        if len(holding) == 1:
            account = holding[0]
            notes.append(f"只有「{account.name}」持有這檔，記在這個帳戶")
    if account is None:
        return {"status": "need_account", "message": "使用者有多個帳戶，請問要記在哪一個帳戶？",
                "accounts": _account_list(ctx)}

    trade_date = today_taipei()
    if args.get("trade_date"):
        try:
            trade_date = date.fromisoformat(args["trade_date"])
        except ValueError as exc:
            raise ToolError("trade_date 必須是 YYYY-MM-DD") from exc
    elif (named := day_in_message(ctx.message, today_taipei())) is not None:
        trade_date = named[0]
        notes.append(f"日期依使用者說的「{named[1]}」記為 {trade_date.isoformat()}")
    if trade_date > today_taipei():
        raise ToolError("交易日期不能晚於今天")

    def dec(key: str) -> Decimal | None:
        v = args.get(key)
        return None if v is None else Decimal(str(v))

    quantity, price, amount = dec("quantity"), dec("price"), dec("amount")
    if ttype in ("buy", "sell"):
        if quantity is None and amount is not None and price is not None and price > 0:
            quantity = (amount / price).to_integral_value(rounding=ROUND_FLOOR)
            amount = None
            notes.append(f"股數 = 金額 ÷ 價格，取整數為 {quantity} 股")
        if quantity is None or quantity <= 0:
            raise ToolError("請問要買賣幾股或幾張？")
        if price is None:
            found = recurring.last_close(ctx.md, info.symbol) if info else None
            if found is None:
                raise ToolError("沒有提供成交價，也查不到最近收盤價；請問成交價是多少？")
            price, price_date, _q = found
            notes.append(f"沒有寫價格，以 {price_date.month}/{price_date.day} 收盤價 {price.normalize():f} 估算，"
                         "確認前請改成實際成交價")
    body: dict[str, Any] = {
        "account_id": account.id, "symbol": info.symbol if info else (symbol_text or None), "type": ttype,
        "trade_date": trade_date, "quantity": quantity, "price": price, "amount": amount,
        "is_day_trade": bool(args.get("is_day_trade")), "note": (args.get("note") or "")[:200],
        "source": "ai_draft",
    }
    try:
        valid = TransactionIn.model_validate(body).model_dump()
    except ValidationError as exc:
        raise ToolError("草稿欄位不正確：" + "；".join(e.get("msg", "") for e in exc.errors())) from exc
    comp = txn_svc.compute(ctx.db, ctx.user, valid, ctx.md)
    candidate = TxnModel(id=new_id("txn"), user_id=ctx.user.id, created_at=now_utc(), updated_at=now_utc(),
                         **comp.values)
    txn_svc.validate_ledger(ctx.db, ctx.user, account, candidate, md=ctx.md)  # raises ledger_inconsistent
    if candidate in ctx.db:  # pragma: no cover - defensive: the candidate must never reach the session
        ctx.db.expunge(candidate)

    v = comp.values
    p = comp.preview
    preview = {"gross": ser.money(p.gross), "fee": ser.money(p.fee), "tax": ser.money(p.tax),
               "health_insurance": ser.money(p.health_insurance), "net_cash": ser.money(p.net_cash),
               "rules": list(p.rules)}
    no_qty = ttype in ("deposit", "withdrawal", "fee", "tax", "interest")
    tx_input = {
        "account_id": account.id, "symbol": v["symbol"], "type": ttype, "trade_date": trade_date.isoformat(),
        "quantity": None if no_qty else ser.qty(v["quantity"]),
        "price": None if no_qty or not v["price"] else ser.price(v["price"]),
        "amount": ser.money(v["amount"]) if (amount is not None or ttype not in ("buy", "sell")) else None,
        "currency": v["currency"], "is_day_trade": v["is_day_trade"], "note": v["note"], "source": "ai_draft",
    }
    instrument = ({"symbol": info.symbol, "code": info.code, "name": info.name, "market": info.market,
                   "currency": info.currency} if info else None)
    key = json.dumps(tx_input, sort_keys=True, default=str)
    if key in ctx.drafted:
        return {**ctx.drafted[key], "status": "already_drafted",
                "instruction": "這一筆草稿剛才已經建立，畫面上已經有它的草稿卡，不要再建立一次。日期或其他欄位不對時，"
                               "用改過的參數再呼叫一次（例如 trade_date 填 YYYY-MM-DD）。"}
    draft = AiDraft(id=new_id("drf"), user_id=ctx.user.id, thread_id=ctx.thread_id, status="pending",
                    payload=tx_input, preview=preview, instrument=instrument, notes=notes)
    ctx.db.add(draft)
    ctx.db.commit()
    card = draft_card(draft, account)
    ctx.drafts.append(card)
    label = TXN_TYPE_LABELS.get(ttype, ttype)
    what = f"{info.name}（{info.symbol}）" if info else ""
    qty_txt = f" {_fmt_qty(v['quantity'])}" if ttype in ("buy", "sell") else ""
    px_txt = f" @ {v['price'].normalize():f}" if ttype in ("buy", "sell") else ""
    out = {
        "status": "pending_signature",
        "draft_id": draft.id,
        "summary": f"{trade_date.isoformat()} {label} {what}{qty_txt}{px_txt}，帳戶「{account.name}」",
        "preview": preview,
        "notes": notes,
        "instruction": "草稿已顯示在畫面上，尚未寫入帳本；請使用者確認簽名後才會生效。",
    }
    ctx.drafted[key] = {"draft_id": draft.id, "summary": out["summary"]}
    return out


def draft_card(draft: AiDraft, account: BrokerAccount | None) -> dict[str, Any]:
    """The ``draft`` SSE event / API shape the frontend's draft card renders."""
    return {
        "id": draft.id, "status": draft.status, "input": draft.payload, "instrument": draft.instrument,
        "preview": draft.preview, "notes": draft.notes,
        "account": {"id": account.id, "name": account.name} if account else None,
        "transaction_id": draft.transaction_id,
        "created_at": iso_taipei(draft.created_at or now_utc()),
    }


# -- registry --------------------------------------------------------------------------------------------
# -- market-wide tools and the follow-up questions (forliosa.ai.market_tools; 產品負責人 2026-11-26) ----------------
def get_market_calendar(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.ai import market_tools

    return market_tools.market_calendar(ctx, args)


def get_market_overview(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.ai import market_tools

    return market_tools.market_overview(ctx, args)


def get_market_trend(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.ai import market_tools

    return market_tools.market_trend(ctx, args)


def get_market_report(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.ai import market_tools

    return market_tools.market_report(ctx, args)


def get_watchlist(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.ai import market_tools

    return market_tools.watchlist(ctx, args)


def get_performance(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.ai import market_tools

    return market_tools.performance(ctx, args)


def suggest_follow_ups(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.ai import market_tools

    return market_tools.suggest_follow_ups(ctx, args)


_REPORT_LABELS = {"premarket": "查看盤前重點", "close": "查看盤後重點", "weekly": "查看市場週報"}


_SYMBOL = {"type": "string", "description": "Stock code, symbol or name, e.g. 2330, 2330.TW, 0050, 台積電, AAPL"}
_ACCOUNT = {"type": "string", "description": "Optional broker account id (from get_portfolio_summary.accounts); "
                                             "omit for all accounts"}


def get_derivatives_overview(ctx: ToolContext, args: dict[str, Any]) -> Any:
    """Read-only market-wide futures context (no user data): the same payload as ``GET /derivatives/overview``,
    trimmed. Parts whose TAIFEX licence is still conditional are empty and explained in ``notes``."""
    from forliosa.services import derivatives as svc

    ov = svc.overview(ctx.db, ctx.md)
    return {
        "as_of": ov["as_of"],
        "futures": ov["futures"],
        "put_call_ratio": ov["put_call_ratio"],
        "institutional": {k: [{x: v for x, v in row.items() if x != "investor_name"} for row in rows]
                          for k, rows in ov["institutional"].items()},
        "large_traders": ov["large_traders"],
        "units": "口數＝契約數；value_k＝新台幣千元；ratio 為分數（0.6517＝65.17%）",
        "notes": ov["notes"],
        "sources": ov["sources"],
    }


_CHART_KINDS = ["price", "compare", "revenue", "eps", "performance"]  # = charts.KINDS (imported lazily there)
_CHART_RANGES = ["1M", "3M", "6M", "YTD", "1Y", "5Y"]  # = charts.RANGES
_CHART_LABELS = {"price": "畫收盤走勢", "compare": "畫漲跌幅比較", "revenue": "畫月營收", "eps": "畫每季 EPS",
                 "performance": "畫我的報酬率"}


def _sym_label(prefix: str, suffix: str = "") -> Callable[[dict[str, Any]], str]:
    return lambda a: f"{prefix}{(a.get('symbol') or '').upper()}{suffix}"


# search_news: the vocabulary of the news tags (forliosa.news.taxonomy), fixed per deployment (the tool list is part of
# the cached prefix)
_NEWS_THEMES = [t.label for t in news_taxonomy.THEMES]
_NEWS_SECTORS = [t.label for t in news_taxonomy.SECTORS]


def _search_news_label(a: dict[str, Any]) -> str:
    what = "、".join(str(x) for x in (a.get("theme"), a.get("sector"), (a.get("symbol") or "").upper() or None,
                                     a.get("keyword")) if x)
    return f"搜尋新聞「{what}」" if what else "搜尋新聞"


TOOLS: list[ToolSpec] = sorted([
    ToolSpec("get_portfolio_summary",
             "The signed-in user's portfolio totals: market value, cost, unrealized/realized P&L, dividends, today's "
             "change, allocation by industry/market/type/account (ETFs by class, never looked through), "
             "concentration (largest holding, top 3 / top 5, largest industry, the limits the user set themselves "
             "and what is above them), upcoming dividends, and the list of accounts. Call this for questions about "
             "overall performance, how much they made today, allocation or concentration. Concentration is facts: "
             "name a limit only as the user's own (「超過你設定的 30%」), never suggest trades.",
             {"account_id": _ACCOUNT}, (), get_portfolio_summary, lambda a: "查看投資組合"),
    ToolSpec("get_holdings",
             "The user's current holdings, one row per stock: shares, average cost, price, market value, today's "
             "change, unrealized P&L and weight. Call this for questions about what they hold, which stock "
             "gained/lost most today, or before comparing positions.",
             {"account_id": _ACCOUNT}, (), get_holdings, lambda a: "查看持股"),
    ToolSpec("get_transactions",
             "The user's recorded transactions, newest first, optionally filtered by stock, type and date range. Call "
             "this for questions about past trades, when they bought or sold, or dividends received.",
             {"account_id": _ACCOUNT,
              "symbol": {"type": "string", "description": "Optional stock code or name"},
              "type": {"type": "string", "enum": ["buy", "sell", "cash_dividend", "stock_dividend", "split",
                                                  "capital_reduction", "deposit", "withdrawal", "fee", "tax",
                                                  "interest"], "description": "Optional transaction type"},
              "date_from": {"type": "string", "format": "date", "description": "Optional, inclusive"},
              "date_to": {"type": "string", "format": "date", "description": "Optional, inclusive"},
              "limit": {"type": "integer", "description": "Optional, default 20, at most 50"}},
             (), get_transactions, lambda a: "查詢交易紀錄"),
    ToolSpec("get_upcoming",
             "Upcoming events for the user's holdings within N days: ex-dividend dates, dividend payments (with "
             "estimated amounts) and recurring-investment debits. Call this for questions about the coming days or "
             "how much dividend they will receive soon.",
             {"days": {"type": "integer", "description": "Days ahead, 1-90 (use 7 for 'this week', 31 for "
                                                         "'next month')"}},
             ("days",), get_upcoming, lambda a: "查看接下來的事項"),
    ToolSpec("get_stock_overview",
             "Key data for one stock or ETF: name, industry, latest quote (price, change vs reference price, volume), "
             "open/high/low, limit up/down, P/E, P/B, dividend yield, EPS (TTM), 52-week range, market cap, "
             "attention/disposition status and recent dividends; for Taiwan ETFs also the NAV (淨值) with its date and "
             "the after-close premium/discount (折溢價) vs NAV on the same date. Also english_name (for searching "
             "foreign news), market_context (the latest official close of the TAIEX and the stock's sector index, "
             "and vs_taiex_pct_points, or dates_differ when the index's close is of another day), why_signals "
             "(rule-based anomalies of the latest session) and intraday_note "
             "(today's close is not out yet). Call this first for any question about a specific stock's price, why "
             "it moved or basic data, or an ETF's NAV or premium/discount.",
             {"symbol": _SYMBOL}, ("symbol",), get_stock_overview, _sym_label("查看 ", " 關鍵數據")),
    ToolSpec("get_stock_history",
             "Daily price history of a stock over a range: start/end close, % change, high/low with dates, average "
             "volume and up to 30 sampled closes. Call this for questions about trends or performance over time.",
             {"symbol": _SYMBOL, "range": {"type": "string", "enum": HISTORY_RANGE_CHOICES}},
             ("symbol", "range"), get_stock_history, _sym_label("查看 ", " 走勢")),
    ToolSpec("get_technicals",
             "Technical indicators of one stock or ETF, computed from archived daily closes (unadjusted prices): "
             "moving averages 5/10/20/60/120/240 with bias (乖離率), RSI(14), KD(9,3,3), MACD(12,26,9), Bollinger "
             "bands, volume ratio (量比), 20/60-day high and low, up/down streak, and dated facts of the last 10 "
             "trading days (MA and KD crosses, MACD histogram turns, closes outside the bands, new highs/lows). "
             "Call this for any technical-analysis question (技術面, 均線, KD, RSI, MACD, 布林通道, 支撐壓力, "
             "黃金交叉, 型態). as_of_close is the latest official close. Pass price only for a current price the "
             "user stated in the conversation (price_source user) or one you found in a citable public web source "
             "(price_source web); the result then adds with_provisional_price: the same indicators as if the day "
             "closed at that price, which is not an official or real-time quote. Never pass a guessed or "
             "remembered price.",
             {"symbol": _SYMBOL,
              "price": {"type": "number", "description": "Optional current price per share, only from the user's "
                                                         "message or a cited web source"},
              "price_source": {"type": "string", "enum": ["user", "web"],
                               "description": "Required with price: user = the user stated it, web = found in a "
                                              "cited web source"},
              "price_time": {"type": "string", "description": "Optional, with price: when that price was seen, "
                                                              "e.g. 11/13 10:42, or the source's own wording"}},
             ("symbol",), get_technicals, _sym_label("計算 ", " 的技術指標")),
    ToolSpec("get_valuation",
             "Valuation of a stock: current P/E, P/B, dividend yield, P/E percentile over 5 years, P/E range and the "
             "multiples used by the P/E river chart, plus the last 12 monthly points. Call this for questions about "
             "whether a stock is expensive or cheap, or where a price sits on the P/E river chart.",
             {"symbol": _SYMBOL}, ("symbol",), get_valuation, _sym_label("查看 ", " 估值")),
    ToolSpec("get_chips",
             "Chip data of a Taiwan stock: net buy/sell of foreign investors, investment trusts and dealers (lots), "
             "margin/short balances, foreign holding % and TDCC shareholder distribution. Call this for questions "
             "about institutional flows, 法人, 融資融券 or 大戶. TWSE-listed (上市) stocks have no per-stock "
             "institutional flows or foreign holding here (TPEx 上櫃 stocks do): for their 外資／法人 activity, search "
             "the web for recent news and cite each source with its date.",
             {"symbol": _SYMBOL, "range": {"type": "string", "enum": ["1M", "3M", "6M", "1Y"]}},
             ("symbol", "range"), get_chips, _sym_label("查看 ", " 籌碼")),
    ToolSpec("get_financials",
             "Financial statements of a stock (last 8 quarters or years): revenue, gross/operating/net income, "
             "EPS, margins, balance sheet and cash flow. Taiwan stocks: TWD thousands, plus the last 6 months of "
             "monthly revenue with YoY. US stocks: SEC EDGAR filings (10-Q / 10-K) in USD, labelled by the "
             "company's fiscal year (FY2026Q1), with diluted EPS and shares. Call this for questions about "
             "earnings, revenue growth or margins.",
             {"symbol": _SYMBOL, "period": {"type": "string", "enum": ["quarterly", "annual"]}},
             ("symbol", "period"), get_financials, _sym_label("查看 ", " 財報")),
    ToolSpec("get_events",
             "Dated events of a stock: ex-dividend and payment dates, earnings and revenue deadlines, material "
             "announcements, attention/disposition, shareholder meetings; for US stocks the SEC filings (8-K with "
             "its items, 10-Q, 10-K) with sec.gov links. Call this for questions about when something happens or "
             "what was announced or filed.",
             {"symbol": _SYMBOL, "mine_only": {"type": "boolean",
                                               "description": "true = only events relevant to the user's holdings"}},
             ("symbol", "mine_only"), get_events, _sym_label("查看 ", " 事件")),
    ToolSpec("get_news",
             "Recent headlines for a stock: official announcements of a Taiwan stock (company material information "
             "and exchange news) and media headlines (the original title, outlet, time and link, found via The "
             "GDELT Project and similar indexes; titles only, no article text). The last 48 hours come first, "
             "newest first; each item starts with its outlet (公司公告 or 交易所公告 for an announcement) and "
             "今天/昨天 or the date, with the time when known. Headlines with a link come back as "
             "search results: cite the one a sentence relies on and the app lists its link under the answer; do not "
             "name the outlet or the website (公開資訊觀測站) in the sentence, do not copy that opening "
             "(「公司公告，11/10 15:02：」) or the title, write it in your own words (「11/10 公告…」). A media "
             "headline may carry a second line of tags (主題、類股、相關 stocks) given by a classifier from the "
             "title alone: use them to group or pick headlines, never as facts, and do not copy them. Search the "
             "web when the question needs more than these headlines.",
             {"symbol": _SYMBOL}, ("symbol",), get_news, _sym_label("查看 ", " 新聞")),
    ToolSpec("search_news",
             "Search the media headlines Forliosa stored (Taiwan and US stocks and the US market; title, outlet, time "
             "and link only, kept 30 days) by theme, sector, stock and/or keyword, newest first, up to 15. Each "
             "headline was tagged from its title by a classifier: 主題 (theme), 類股 (sector: Taiwan's official "
             "industry or a US sector) and related stocks; a stock filter also finds headlines stored under it. Call "
             "this for news about a theme, industry or sector (「AI 伺服器最近有什麼消息」「航運股新聞」"
             "「這週關稅的新聞」), to find other news that mentions a stock, or before writing about a sector's or "
             "theme's week. Results come back as search results like get_news (cite the one a sentence relies on; "
             "tags are hints, not facts); none found means search the web if needed. Untagged headlines are found "
             "only by stock or keyword.",
             {"theme": {"type": "string", "enum": ["", *_NEWS_THEMES], "description": "A theme, or \"\" for any"},
              "sector": {"type": "string", "enum": ["", *_NEWS_SECTORS],
                         "description": "A Taiwan industry (半導體業) or a US sector (美股半導體), or \"\" for any"},
              "symbol": {"type": "string", "description": "Stock code or name (2330, NVDA), or \"\" for any"},
              "keyword": {"type": "string", "description": "A word the headline must contain (CoWoS), or \"\""},
              "days": {"type": "integer", "description": "How many days back, 1-90; 7 unless the user names a period"}},
             ("theme", "sector", "symbol", "keyword", "days"), search_news, _search_news_label,
             blank_ok=("theme", "sector", "symbol", "keyword", "days")),
    ToolSpec("get_analyst_views",
             "Third-party ratings and target prices of one stock, as the stock page's 法人觀點 card collected them "
             "(read-only: nothing is searched here): each item is one broker or investment bank's rating and/or "
             "target price from a news article, with its date and link, newest first; an unnamed foreign broker "
             "reads 「一家日系外資」 (write it so, never guess the firm), and an item ending 「較舊的報導」 is older "
             "news that comes last. Items come back as search results: cite the one a sentence relies on, write the "
             "rating in the source's own words and never add an average, an upside or your own target. Status "
             "ready with no items means the card looked recently and found none: say there is no data and do not "
             "search. Only when the card has not looked or could not (status none, pending or unavailable) search "
             "the web for news articles instead. Call this first when the user asks about a stock's ratings, "
             "target prices or what brokers think of it.",
             {"symbol": _SYMBOL}, ("symbol",), get_analyst_views, _sym_label("查看 ", " 法人觀點")),
    ToolSpec(TW_NEWS_TOOL,
             "Search Taiwan news sites for one Taiwan-listed stock (or, with intent market, today's Taiwan market "
             "wrap). Returns up to 10 recent articles as search results: title, outlet, a checked report date and a "
             "short excerpt (at most 300 characters) of the part of the article that matches the intent. The server "
             "writes the search query itself (the company's short name plus the intent's words) and keeps only "
             "Taiwan news outlets; it drops quote, warrant and forum pages and articles not about this company, and "
             "checks each date against the URL where it can (an item marked 日期依搜尋引擎 has only the search "
             "engine's date; one marked 日期未確認 has no reliable date: write no date for it and do not present it "
             "as recent). Intents: news (latest company news), why_move (the company's news since the day before the "
             "last trading day, for why a stock moved), analyst_targets (brokers' ratings and target prices of the "
             "last 90 days), earnings_call (法說會 and guidance), revenue (how the media read the monthly revenue), "
             "dividend (dividend decisions), market (no symbol: today's Taiwan market wrap). days: only for intent "
             "news, 1-30; 0 uses the default. Cite the item a sentence relies on and write its facts in your own words "
             "(never copy the excerpt or the title); give each fact the item's date. For analyst_targets: one "
             "excerpt may list several brokers, write one line per broker; keep only each broker's newest report; a "
             "broker named only by region (美系外資) is 一家美系外資; leave out 本土投顧, 國內投顧 and 法人 without "
             "a firm name; when a newer report says brokers cut targets without numbers, do not present an older "
             "number as the latest; a figure the excerpt dates to an earlier year is not current; unless the user "
             "asked about one broker, list every broker the results name (one line each, newest first), not only the "
             "newest. Official figures (closing prices, monthly revenue, EPS, dividends, announcements) come from "
             "the other tools; use this for what the media reported and how the market read it. Taiwan stocks only: "
             "US stocks, foreign news and macro use web_search. Call it once per intent; status none means nothing "
             "was found: do not retry it with other words, follow its note.",
             {"symbol": {"type": "string",
                         "description": "Taiwan stock code or name, e.g. 2330, 台積電; \"\" for intent market"},
              "intent": {"type": "string", "enum": ["news", "why_move", "analyst_targets", "earnings_call", "revenue",
                                                    "dividend", "market"]},
              "days": {"type": "integer", "description": "Only for intent news: days back, 1-30; 0 for the default"}},
             ("symbol", "intent", "days"), tw_news_search, _tw_news_label, blank_ok=("days",), strict=False),
    # Past the 20 strict tools a request may carry: not strict, the handlers check their own arguments
    ToolSpec("get_market_calendar",
             "Market-wide scheduled events of a date range (Taipei dates): ex-dividend dates, investor conferences "
             "(法說會), shareholder meetings, disposition (處置) periods, TAIEX futures/options settlement days, macro "
             "releases (US and Taiwan), US earnings of a hand-kept list of large companies and NYSE closures. Events "
             "of the user's own holdings and watchlist come first, marked yours (持有/觀察); market-wide rows and the "
             "100 largest companies by market cap are listed; the rest are counted by kind in others, with a few of "
             "the largest names. date_from and date_to are YYYY-MM-DD, \"\" for the next Taiwan trading day; at most "
             "14 days. kind narrows to one kind and then lists every company of it (largest first, up to 80): use it "
             "when the question is about one kind (這週有哪些法說會、最近哪些股票除息). Ex-dividend rows carry amount "
             "(the official cash dividend per share, or 金額還沒公告). Call this for 明天/這週/下週 questions (what "
             "is scheduled, 看點, 要注意什麼), together with get_market_overview.",
             {"date_from": {"type": "string", "description": "YYYY-MM-DD, or \"\" for the next Taiwan trading day"},
              "date_to": {"type": "string", "description": "YYYY-MM-DD, or \"\" for the same day as date_from"},
              "kind": {"type": "string", "enum": ["", "除權息", "法說會", "股東會", "處置股", "注意股", "結算日",
                                                  "總經數據", "美股財報", "美股休市"],
                       "description": "One kind of event, or \"\" for every kind"}},
             ("date_from", "date_to"), get_market_calendar,
             lambda a: f"查看{a.get('kind') or ''}行事曆", blank_ok=("date_from", "date_to"), strict=False),
    ToolSpec("get_market_overview",
             "The latest Taiwan session of the whole market from official closes (the market page): TAIEX and the "
             "OTC index, advancers/decliners and limit up/down counts per exchange, the best and worst sectors, the "
             "10 biggest gainers, losers and most traded common stocks, and the stocks closing at the limit up or "
             "down (largest value first). Every list is a stated rule, not a pick. Call this for how the market did, "
             "which sectors or stocks moved most, and for 明天/這週 questions (with get_market_calendar).",
             {}, (), get_market_overview, lambda a: "查看市場概況", strict=False),
    ToolSpec("get_market_trend",
             "The Taiwan market's trend over the last sessions, from the official archive only: the TAIEX (close, its "
             "move over the last 5 / 10 / 20 sessions, on which side of its 5- / 10- / 20-session averages it "
             "closed, a run of rises or falls), the OTC index and the size indices (臺灣50, 中型100, 小型股300) over "
             "the same sessions, the official listed turnover against its 5-session average, and the listed sectors "
             "ranked by their move over the last 5 sessions: the 6 strongest and the 6 weakest, each with its 1-day "
             "and multi-session moves, the gap to the TAIEX, whether it also ranks so over the longer period and "
             "whether one stock dominates it; the strongest sectors come with their 3 largest stocks by market cap "
             "(a stated rule, not a pick). A period the archive does not reach yet is left out and named in notes: "
             "never work it out yourself. Call this for 趨勢, 盤勢, 哪些類股強或弱, 可以關注什麼方向或類股, 下週可以"
             "買什麼, 現在能不能進場, together with get_market_overview and get_market_calendar.",
             {}, (), get_market_trend, lambda a: "查看市場趨勢", strict=False),
    ToolSpec("get_market_report",
             "The newest published Forliosa market report (shared by everyone; kind: latest, premarket = 盤前重點 "
             "07:30, close = 盤後重點 16:00, weekly = 市場週報 Sunday). Each news article the report cites comes back "
             "as a search result holding the report's own sentences that cite it (its first words name the edition, "
             "for example 「11/26（四）盤後重點」): cite the one a sentence relies on and write it in your own words. "
             "Check the edition's date: an older edition is background, not today's news. A report without news "
             "comes back as its sentences (official data only). Call this for what the market is watching, the "
             "themes of the day or week, and 明天/這週 questions.",
             {"kind": {"type": "string", "enum": ["latest", "premarket", "close", "weekly"]}},
             ("kind",), get_market_report, lambda a: _REPORT_LABELS.get(a.get("kind") or "", "查看市場報告"),
             strict=False),
    ToolSpec("get_performance",
             "The user's own return over a period, the 績效 page's numbers: the time-weighted return against their "
             "benchmark, the max drawdown, and the amounts (TWD): how much they made in the period (the change of "
             "market value minus capital, dividends apart), the dividends received and the realized gains in it. "
             "range: MTD (this month), 1M, 3M, 6M, YTD (this year), 1Y, ALL. Call this for 今年賺多少、這個月績效、"
             "報酬率多少、有沒有贏大盤.",
             {"range": {"type": "string", "enum": ["MTD", "1M", "3M", "6M", "YTD", "1Y", "ALL"]}},
             ("range",), get_performance, lambda a: "查看績效", strict=False),
    ToolSpec("get_watchlist",
             "The user's own watchlist (觀察清單): each symbol with its name, latest official close, change and its "
             "date. Call this when the user asks about their watchlist, or with get_holdings for what to look at "
             "among their own stocks.",
             {}, (), get_watchlist, lambda a: "查看觀察清單", strict=False),
    ToolSpec(FOLLOW_UPS_TOOL,
             "Show 3-5 short follow-up questions under your answer, which the user can tap to ask next. Call it once, "
             "as the very last thing, after your answer is written, alone (no other tool in the same step); write "
             "nothing after it. Each question is in Traditional Chinese, 4-40 characters, written as the user would "
             "ask it, about the stocks, events or themes of your answer, answerable with your tools (news, why a "
             "stock moved, financials, valuation, technicals, ratings, the calendar, the user's own holdings); never "
             "a question asking you to decide a trade (該不該買、可以加碼嗎), to predict a price, or one already "
             "answered.",
             {"questions": {"type": "array", "items": {"type": "string"},
                            "description": "3-5 questions, e.g. [\"台積電法說會通常會公布什麼？\", "
                                           "\"台達電這次配多少股利？\"]"}},
             ("questions",), suggest_follow_ups, lambda a: "準備接著問的問題", strict=False),
    ToolSpec("get_position",
             "The user's own position in one stock: shares, average cost, cost basis, market value, unrealized and "
             "realized P&L, dividends received, today's change, the next dividend estimate and recent trades. Call "
             "this whenever the user asks about 'my' shares, cost or profit in a specific stock.",
             {"symbol": _SYMBOL}, ("symbol",), get_position, _sym_label("查看我的 ", " 部位")),
    ToolSpec("get_derivatives_overview",
             "Market-wide Taiwan futures context from TAIFEX open data (read-only, no user data): TX/MTX/TE/TF "
             "near-month futures incl. the night session (only when licensed), the TAIEX options put/call ratio, net "
             "open interest of foreign investors, investment trusts and dealers in TX and TXO (calls/puts), and the "
             "large traders' top-5/top-10 net positions. Call this for questions about 台指期, 夜盤, 外資期貨未平倉, "
             "籌碼 of the whole market or Put/Call.",
             {}, (), get_derivatives_overview, lambda a: "查看期貨盤勢"),
    ToolSpec("get_related_stocks",
             "Stocks related to one Taiwan stock or ETF: its benchmark, affiliates and same-industry peers, each "
             "with the latest official close and its date (not today's live price). Call this when the stock itself "
             "has no citable news or price for today and you need to know which related stocks, industry or index "
             "to search the web for, or when the user asks about peers.",
             {"symbol": _SYMBOL}, ("symbol",), get_related_stocks, _sym_label("查看 ", " 的相關股票")),
    ToolSpec("draw_chart",
             "Draw ONE chart card in the app from server-side data; you choose what to draw, never the numbers. "
             "kind: price = daily closes of one symbol; compare = % change of 2-5 symbols from their first common "
             "day; revenue = monthly revenue (last 24 months) of 1-5 Taiwan stocks; eps = quarterly EPS (last 8 "
             "quarters) of 1-5 stocks; performance = the user's own time-weighted return vs a benchmark (symbols "
             "empty, or one symbol to use as the benchmark). range applies to price, compare and performance. Call "
             "this when the user asks for a chart or to compare trends over time. Returns each line's first/last "
             "value, change, high and low, plus notes; status no_data means nothing was drawn.",
             {"kind": {"type": "string", "enum": _CHART_KINDS},
              "symbols": {"type": "array", "items": {"type": "string"},
                          "description": "Codes or names, e.g. [\"2330\", \"2317\"]; [] for performance with "
                                         "the user's default benchmark"},
              "range": {"type": "string", "enum": _CHART_RANGES,
                        "description": "Ignored by revenue and eps (pass 1Y)"}},
             ("kind", "symbols", "range"), draw_chart, lambda a: _CHART_LABELS.get(a.get("kind"), "畫圖")),
    ToolSpec("search_instruments",
             "Find Taiwan or US stocks/ETFs by code or (partial) Chinese/English name. Call this when the user names "
             "a company you cannot map to a code with certainty. Most US companies only have their English name, so "
             "search them in English. US prices are daily closes of the New York session; has_quote false means "
             "there is no price: never guess one.",
             {"query": {"type": "string", "description": "Code or name, e.g. 台積, 0056, NVDA"}},
             ("query",), search_instruments, lambda a: f"搜尋商品「{a.get('query', '')}」"),
    ToolSpec("draft_transaction",
             "Prepare a DRAFT transaction for the user to sign; it is NOT recorded until the user confirms it in the "
             "app. Call this whenever the user asks to record/log a trade, dividend, deposit or withdrawal, e.g. "
             "「買 0050 2 張 52.4」. quantity is in shares (1 張 = 1000 shares). Returns the fee/tax preview and a "
             "draft id, or the account list when the user must choose an account.",
             {"type": {"type": "string", "enum": TXN_TYPES_FOR_DRAFT},
              "symbol": {"type": "string", "description": "Stock code or name; empty string for cash-only types"},
              "account_id": {"type": "string", "description": "Optional; omit to use the only account"},
              "trade_date": {"type": "string", "format": "date",
                             "description": "YYYY-MM-DD. When the user names a day (昨天, 前天, 上週五, "
                                            "11/12) convert it to a date using today's date in the page context and "
                                            "fill this in; omit only when no day is mentioned (today)"},
              "quantity": {"type": "number", "description": "Optional shares (1 張 = 1000)"},
              "price": {"type": "number", "description": "Optional price per share (or dividend per share)"},
              "amount": {"type": "number", "description": "Optional total amount (cash types, dividends)"},
              "is_day_trade": {"type": "boolean", "description": "Optional, 當沖"},
              "note": {"type": "string", "description": "Optional short note"}},
             ("type", "symbol"), draft_transaction, lambda a: "準備交易草稿"),
], key=lambda t: t.name)
TOOLS_BY_NAME = {t.name: t for t in TOOLS}


def tw_news_offered(settings: Settings, *, economy: bool = False, deep: bool = False) -> bool:
    """tw_news_search is in the tool list: AI_LANGSEARCH_ENABLED with a key, not in 深度搜尋 (left as it was), and
    in 省錢模式 only with AI_LANGSEARCH_IN_ECONOMY. The same answer for every turn of a kind (the cached prefix)."""
    return settings.ai_langsearch_on and not deep and (not economy or settings.ai_langsearch_in_economy)


def client_tool_definitions(settings: Settings, *, economy: bool = False, deep: bool = False) -> list[dict[str, Any]]:
    """The client tools, sorted by name (a deterministic list: part of the cached prefix); tw_news_search only when
    offered (``tw_news_offered``)."""
    tw = tw_news_offered(settings, economy=economy, deep=deep)
    return [t.definition(eager=settings.ai_eager_tool_streaming) for t in TOOLS if t.name != TW_NEWS_TOOL or tw]


def _domains(values: list[str], defaults: dict[str, list[str]]) -> list[str]:
    out: list[str] = []
    for v in values:
        out.extend(defaults.get(v, [v]))
    return list(dict.fromkeys(d for d in out if d))


def _fetch_allowed(domains: list[str]) -> list[str]:
    """``allowed_domains`` for web_fetch without the blocked hosts: a blocked host itself is dropped, a parent
    domain of one (``twse.com.tw``) is replaced by the hosts we may read (``openapi.twse.com.tw``)."""
    out: list[str] = []
    for d in domains:
        if d in FETCH_BLOCKED_DOMAINS:
            continue
        if any(b.endswith(f".{d}") for b in FETCH_BLOCKED_DOMAINS):
            out.extend(_FETCH_NARROWED.get(d, []))
            continue
        out.append(d)
    return list(dict.fromkeys(out))


def server_tools(settings: Settings, *, fetch: bool = True, max_uses: int | None = None) -> list[dict[str, Any]]:
    """web_search / web_fetch (versions 20260318). Direct calls (no dynamic filtering) unless
    ``AI_WEB_DYNAMIC_FILTERING`` — lower latency and eligible for zero data retention."""
    tools: list[dict[str, Any]] = []
    callers = {} if settings.ai_web_dynamic_filtering else {"allowed_callers": ["direct"]}
    if settings.ai_web_search:
        search: dict[str, Any] = {"type": "web_search_20260318", "name": "web_search",
                                  "max_uses": max_uses or settings.ai_web_search_max_uses,
                                  "user_location": USER_LOCATION, **callers}
        allowed = _domains(settings.ai_web_search_allowed_domains,
                           {"recommended": RECOMMENDED_NEWS_DOMAINS, "official": OFFICIAL_DOMAINS})
        if allowed:
            search["allowed_domains"] = allowed
        tools.append(search)
    if settings.ai_web_fetch and fetch:
        fetch_tool: dict[str, Any] = {"type": "web_fetch_20260318", "name": "web_fetch", "max_uses": 2,
                                      "max_content_tokens": 8000, "citations": {"enabled": True}, **callers}
        allowed = _domains(settings.ai_web_fetch_allowed_domains,
                           {"official": OFFICIAL_DOMAINS, "recommended": RECOMMENDED_NEWS_DOMAINS})
        if allowed and "*" not in allowed:
            narrowed = _fetch_allowed(allowed)
            if narrowed:
                fetch_tool["allowed_domains"] = narrowed
                tools.append(fetch_tool)
            # every configured domain was a blocked host: no fetch rather than an unrestricted one
        else:
            fetch_tool["blocked_domains"] = list(FETCH_BLOCKED_DOMAINS)
            tools.append(fetch_tool)
    with _excluded_lock:
        return [t for t in tools if t["type"] not in _excluded]


def block_search(tools: list[dict[str, Any]], domains: tuple[str, ...] = SEARCH_BLOCKED_DOMAINS
                 ) -> list[dict[str, Any]]:
    """``web_search`` with ``domains`` blocked (``SEARCH_BLOCKED_DOMAINS`` for the 法人觀點 card,
    ``CHAT_BLOCKED_DOMAINS`` for chat), unless an allow-list is configured: the API takes ``allowed_domains`` or
    ``blocked_domains``, not both. Changes ``tools`` in place."""
    for t in tools:
        if t.get("name") == "web_search" and "allowed_domains" not in t:
            t["blocked_domains"] = list(domains)
    return tools


# -- server tools the API refuses ------------------------------------------------------------------------------
def rejected_tool(message: str | None, tools: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The server tool a 400 message says is not allowed / supported / enabled: matched by its ``type`` string
    (``web_fetch_20260318``), else by its name (``web_fetch`` or "web fetch"). Client tools are never matched."""
    text = message or ""
    if not _REJECTED_HINT.search(text):
        return None
    server = [t for t in tools if isinstance(t.get("type"), str) and "input_schema" not in t]
    for t in server:
        if t["type"] in text:
            return t
    lowered = text.lower()
    for t in server:
        name = str(t.get("name") or "")
        if name and (name in lowered or name.replace("_", " ") in lowered):
            return t
    return None


def exclude_tool(tool: dict[str, Any], reason: str) -> bool:
    """Leave this server tool out of every later request of this process. True the first time (log once)."""
    with _excluded_lock:
        if tool["type"] in _excluded:
            return False
        _excluded[tool["type"]] = {"type": tool["type"], "name": tool.get("name"), "reason": (reason or "")[:300],
                                   "at": iso_taipei(now_utc())}
    log.warning("AI server tool %s refused by the API (%s); left out for the rest of this process",
                tool["type"], (reason or "")[:300])
    return True


def excluded_tools() -> list[dict[str, Any]]:
    with _excluded_lock:
        return [dict(v) for v in _excluded.values()]


def reset_excluded_tools() -> None:
    """Tests (and a restart) start with every configured tool again."""
    with _excluded_lock:
        _excluded.clear()


def tool_label(name: str, args: dict[str, Any] | None) -> str:
    spec = TOOLS_BY_NAME.get(name)
    if spec is not None:
        try:
            return spec.label(args or {})
        except Exception:  # pragma: no cover - labels are cosmetic
            return name
    if name == "web_search":
        q = (args or {}).get("query")
        return f"搜尋網路：{q}" if q else "搜尋網路"
    if name == "web_fetch":
        url = (args or {}).get("url") or ""
        host = url.split("/")[2] if url.count("/") >= 2 else url
        return f"讀取 {host}" if host else "讀取網頁"
    return name


def execute(ctx: ToolContext, name: str, args: Any) -> ToolOutcome:
    """Run one client tool. Errors become ``is_error`` results the model can recover from."""
    spec = TOOLS_BY_NAME.get(name)
    if spec is None:
        return ToolOutcome(f"未知的工具：{name}", is_error=True)
    if not isinstance(args, dict):
        return ToolOutcome(json.dumps({"INVALID_JSON": json.dumps(args, ensure_ascii=False)}, ensure_ascii=False),
                           is_error=True)
    unknown = set(args) - set(spec.properties)
    missing = [k for k in spec.required if args.get(k) in (None, "") and k != "symbol" and k not in spec.blank_ok]
    if unknown or missing:
        parts = [f"不認得的參數 {', '.join(sorted(unknown))}"] if unknown else []
        parts += [f"缺少 {', '.join(missing)}"] if missing else []
        return ToolOutcome("參數不正確：" + "；".join(parts), is_error=True)
    drafts_before = len(ctx.drafts)
    charts_before = len(ctx.charts)
    try:
        result = spec.handler(ctx, args)
    except ToolError as exc:
        ctx.db.rollback()
        return ToolOutcome(str(exc), is_error=True)
    except ApiError as exc:
        ctx.db.rollback()
        return ToolOutcome(exc.message, is_error=True)
    except Exception:
        ctx.db.rollback()
        log.exception("AI tool %s failed", name)
        return ToolOutcome("這項資料暫時查不到（系統錯誤），請改用其他方式回答或告訴使用者稍後再試", is_error=True)
    draft = ctx.drafts[-1] if len(ctx.drafts) > drafts_before else None
    chart = ctx.charts[-1] if len(ctx.charts) > charts_before else None
    if isinstance(result, Citable):
        outlets = {it["url"]: it["outlet"] for it in result.items if it.get("outlet")}
        private = [it for it in result.items if it.get("private")]
        return ToolOutcome(citable_content(result), draft=draft, chart=chart, outlets=outlets,
                           redact={it["url"]: it["safe_text"] for it in private},
                           private_texts=[it["text"] for it in private])
    if name == FOLLOW_UPS_TOOL:  # a plain sentence for the model; the questions go to the screen
        return ToolOutcome(str(result), follow_ups=list(ctx.follow_ups))
    return ToolOutcome(dump(result), draft=draft, chart=chart)
