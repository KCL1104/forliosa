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
from forliosa.config import Settings
from forliosa.ids import new_id
from forliosa.marketdata.base import InstrumentInfo
from forliosa.marketdata.service import MarketData
from forliosa.models import AiDraft, BrokerAccount, User
from forliosa.models import Transaction as TxnModel
from forliosa.timeutil import iso_taipei, now_utc, today_taipei

log = logging.getLogger(__name__)

MAX_RESULT_CHARS = 14_000
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


@dataclass
class ToolOutcome:
    content: str
    is_error: bool = False
    draft: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    properties: dict[str, Any]
    required: tuple[str, ...]
    handler: Callable[[ToolContext, dict[str, Any]], Any]
    label: Callable[[dict[str, Any]], str]

    def definition(self, eager: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "input_schema": {"type": "object", "properties": self.properties, "required": list(self.required),
                             "additionalProperties": False},
            "strict": True,
        }
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


def resolve_instrument(md: MarketData, text: str) -> InstrumentInfo:
    """``2330`` / ``2330.TW`` / ``台積電`` → instrument; ambiguous names list the candidates."""
    text = (text or "").strip()
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
    return [{"id": a.id, "name": a.name, "broker": a.broker, "currency": a.currency,
             "tracking_mode": a.tracking_mode} for a in _accounts(ctx)]


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
    s = svc.summary(svc.compute_state(ctx.db, ctx.user, ctx.md, account_id), ctx.md)
    alloc = s.get("allocation") or {}
    return {
        **_pick(s, "as_of", "market_value", "cost_basis", "unrealized_pnl", "unrealized_pnl_pct", "realized_pnl",
                "dividend_income", "total_pnl", "total_return_pct", "day_change", "day_change_pct", "is_demo"),
        "allocation": {k: [_pick(i, "label", "value", "weight") for i in (v or [])[:6]]
                       for k, v in alloc.items() if k in ("by_industry", "by_market", "by_type", "by_account")},
        "upcoming_dividends": (s.get("upcoming_dividends") or [])[:6],
        "accounts": _account_list(ctx),
        "currency": "TWD",
    }


def get_holdings(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.services import portfolio as svc

    account_id = _own_account_id(ctx, args.get("account_id"))
    state = svc.compute_state(ctx.db, ctx.user, ctx.md, account_id)
    rows = svc.holdings(state)
    keys = ("symbol", "name", "type", "industry", "currency", "quantity", "avg_cost", "cost_basis", "price",
            "prev_close", "market_value", "day_change", "day_change_pct", "unrealized_pnl", "unrealized_pnl_pct",
            "weight", "is_demo")
    return {"as_of": iso_taipei(state.as_of), "count": len(rows), "holdings": [_pick(h, *keys) for h in rows],
            "notes": ["金額為新台幣；avg_cost、price 為原幣；quantity 為股數（1 張 = 1000 股）"]}


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
    from forliosa.services import instruments as instr
    from forliosa.services import stock as svc

    info = resolve_instrument(ctx.md, args["symbol"])
    sym = info.symbol
    q = ctx.md.quote(sym)
    detail = instr.detail(ctx.md, sym)
    summary = detail.get("summary")
    ov = svc.overview(ctx.db, ctx.md, sym)
    divs = instr.dividends(ctx.md, sym)[:4]
    return {
        **instr.instrument_out(info),
        "summary": summary[:240] if isinstance(summary, str) else None,
        "themes": detail.get("themes") or [],
        "quote": _pick(instr.quote_out(q), "price", "prev_close", "reference_price", "change", "change_pct",
                       "volume", "as_of", "is_realtime", "is_demo") if q is not None else None,
        "overview": {k: v for k, v in ov.items() if k not in ("symbol", "sources")},
        "recent_dividends": divs,
        "sources": ov.get("sources", []),
    }


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

    revenue = instr.revenue(ctx.md, info.symbol)[-6:] if info.type == "stock" else []
    return {
        "symbol": info.symbol, "name": info.name, "period": args["period"], "periods": periods[cut:],
        "income": tail(f.get("income")), "balance": tail(f.get("balance")), "cashflow": tail(f.get("cashflow")),
        "margins": tail(f.get("margins")),
        "monthly_revenue_last_6": revenue,
        "units": "金額單位新台幣千元；margins 為比率", "notes": f.get("notes") or [], "sources": f.get("sources"),
    }


def get_events(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.services import stock as svc

    info = resolve_instrument(ctx.md, args["symbol"])
    evs = svc.events(ctx.db, ctx.md, ctx.user, info.symbol, bool(args.get("mine_only")))
    today = today_taipei()
    upcoming = [e for e in evs if e["date"] >= today][-10:]
    past = [e for e in evs if e["date"] < today][:10]
    keys = ("date", "type", "title", "detail", "url", "mine", "amount_estimate")
    return {"symbol": info.symbol, "name": info.name, "today": today,
            "upcoming": [_pick(e, *keys) for e in upcoming], "recent": [_pick(e, *keys) for e in past]}


def get_news(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.services import stock as svc

    info = resolve_instrument(ctx.md, args["symbol"])
    items = svc.news(ctx.db, ctx.md, info.symbol)[:12]
    out: dict[str, Any] = {"symbol": info.symbol, "name": info.name,
                           "headlines": [_pick(n, "published_at", "title", "source", "url") for n in items]}
    if not items:
        out["note"] = "最近沒有公告標題；媒體新聞請改用 web_search"
    return out


def get_position(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.services import stock as svc

    info = resolve_instrument(ctx.md, args["symbol"])
    pos = svc.position(ctx.db, ctx.md, ctx.user, info.symbol)
    if pos is None:
        return {"symbol": info.symbol, "name": info.name, "held": False,
                "note": "目前沒有持有這檔；過去的交易可用 get_transactions 查詢"}
    markers = pos.get("markers") or []
    return {"symbol": info.symbol, "name": info.name, "held": True,
            **{k: v for k, v in pos.items() if k not in ("markers", "symbol", "sources")},
            "trades_count": len(markers), "recent_trades": markers[-10:],
            "notes": ["金額為新台幣；avg_cost 為原幣；quantity 為股數"]}


def search_instruments(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from forliosa.services import instruments as instr

    found = ctx.md.search(args["query"], 10)
    return {"results": [instr.instrument_out(i) for i in found]}


# -- draft_transaction -----------------------------------------------------------------------------------
def _fmt_qty(q: Decimal) -> str:
    q = q.normalize()
    if q >= 1000 and q % 1000 == 0:
        return f"{int(q / 1000)} 張（{int(q):,} 股）"
    return f"{q:,f} 股"


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
    txn_svc.validate_ledger(ctx.db, ctx.user, account, candidate)  # raises ledger_inconsistent; never added
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
    return {
        "status": "pending_signature",
        "draft_id": draft.id,
        "summary": f"{trade_date.isoformat()} {label} {what}{qty_txt}{px_txt}，帳戶「{account.name}」",
        "preview": preview,
        "notes": notes,
        "instruction": "草稿已顯示在畫面上，尚未寫入帳本；請使用者確認簽名後才會生效。",
    }


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
_SYMBOL = {"type": "string", "description": "Stock code, symbol or name, e.g. 2330, 2330.TW, 0050, 台積電, AAPL"}
_ACCOUNT = {"type": "string", "description": "Optional broker account id (from get_portfolio_summary.accounts); "
                                             "omit for all accounts"}


def _sym_label(prefix: str, suffix: str = "") -> Callable[[dict[str, Any]], str]:
    return lambda a: f"{prefix}{(a.get('symbol') or '').upper()}{suffix}"


TOOLS: list[ToolSpec] = sorted([
    ToolSpec("get_portfolio_summary",
             "The signed-in user's portfolio totals: market value, cost, unrealized/realized P&L, dividends, today's "
             "change, allocation by industry/market/type/account, upcoming dividends, and the list of accounts. Call "
             "this for questions about overall performance, how much they made today, allocation or concentration.",
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
             "attention/disposition status and recent dividends. Call this first for any question about a "
             "specific stock's price or basic data.",
             {"symbol": _SYMBOL}, ("symbol",), get_stock_overview, _sym_label("查看 ", " 關鍵數據")),
    ToolSpec("get_stock_history",
             "Daily price history of a stock over a range: start/end close, % change, high/low with dates, average "
             "volume and up to 30 sampled closes. Call this for questions about trends or performance over time.",
             {"symbol": _SYMBOL, "range": {"type": "string", "enum": HISTORY_RANGE_CHOICES}},
             ("symbol", "range"), get_stock_history, _sym_label("查看 ", " 走勢")),
    ToolSpec("get_valuation",
             "Valuation of a stock: current P/E, P/B, dividend yield, P/E percentile over 5 years, P/E range and the "
             "multiples used by the P/E river chart, plus the last 12 monthly points. Call this for questions about "
             "whether a stock is expensive or cheap, or where a price sits on the P/E river chart.",
             {"symbol": _SYMBOL}, ("symbol",), get_valuation, _sym_label("查看 ", " 估值")),
    ToolSpec("get_chips",
             "Chip data of a Taiwan stock: net buy/sell of foreign investors, investment trusts and dealers (lots), "
             "margin/short balances, foreign holding % and TDCC shareholder distribution. Call this for questions "
             "about institutional flows, 法人, 融資融券 or 大戶.",
             {"symbol": _SYMBOL, "range": {"type": "string", "enum": ["1M", "3M", "6M", "1Y"]}},
             ("symbol", "range"), get_chips, _sym_label("查看 ", " 籌碼")),
    ToolSpec("get_financials",
             "Financial statements of a Taiwan stock (last 8 quarters or years): revenue, gross/operating/net income, "
             "EPS, margins, balance sheet and cash flow, plus the last 6 months of monthly revenue with YoY. Call "
             "this for questions about earnings, revenue growth or margins.",
             {"symbol": _SYMBOL, "period": {"type": "string", "enum": ["quarterly", "annual"]}},
             ("symbol", "period"), get_financials, _sym_label("查看 ", " 財報")),
    ToolSpec("get_events",
             "Dated events of a stock: ex-dividend and payment dates, earnings and revenue deadlines, material "
             "announcements, attention/disposition, shareholder meetings. Call this for questions about when "
             "something happens or what was announced.",
             {"symbol": _SYMBOL, "mine_only": {"type": "boolean",
                                               "description": "true = only events relevant to the user's holdings"}},
             ("symbol", "mine_only"), get_events, _sym_label("查看 ", " 事件")),
    ToolSpec("get_news",
             "Recent official announcement headlines for a Taiwan stock (company material information and exchange "
             "news: title, source, link). Media coverage is not included: search the web for it when the "
             "question needs recent news about the company.",
             {"symbol": _SYMBOL}, ("symbol",), get_news, _sym_label("查看 ", " 新聞")),
    ToolSpec("get_position",
             "The user's own position in one stock: shares, average cost, cost basis, market value, unrealized and "
             "realized P&L, dividends received, today's change, the next dividend estimate and recent trades. Call "
             "this whenever the user asks about 'my' shares, cost or profit in a specific stock.",
             {"symbol": _SYMBOL}, ("symbol",), get_position, _sym_label("查看我的 ", " 部位")),
    ToolSpec("search_instruments",
             "Find Taiwan or US stocks/ETFs by code or (partial) Chinese/English name. Call this when the user names "
             "a company you cannot map to a code with certainty.",
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
              "trade_date": {"type": "string", "format": "date", "description": "Optional, default today"},
              "quantity": {"type": "number", "description": "Optional shares (1 張 = 1000)"},
              "price": {"type": "number", "description": "Optional price per share (or dividend per share)"},
              "amount": {"type": "number", "description": "Optional total amount (cash types, dividends)"},
              "is_day_trade": {"type": "boolean", "description": "Optional, 當沖"},
              "note": {"type": "string", "description": "Optional short note"}},
             ("type", "symbol"), draft_transaction, lambda a: "準備交易草稿"),
], key=lambda t: t.name)
TOOLS_BY_NAME = {t.name: t for t in TOOLS}


def client_tool_definitions(settings: Settings) -> list[dict[str, Any]]:
    return [t.definition(eager=settings.ai_eager_tool_streaming) for t in TOOLS]


def _domains(values: list[str], defaults: dict[str, list[str]]) -> list[str]:
    out: list[str] = []
    for v in values:
        out.extend(defaults.get(v, [v]))
    return list(dict.fromkeys(d for d in out if d))


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
            fetch_tool["allowed_domains"] = allowed
        tools.append(fetch_tool)
    with _excluded_lock:
        return [t for t in tools if t["type"] not in _excluded]


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
    missing = [k for k in spec.required if args.get(k) in (None, "") and k != "symbol"]
    if unknown or missing:
        parts = [f"不認得的參數 {', '.join(sorted(unknown))}"] if unknown else []
        parts += [f"缺少 {', '.join(missing)}"] if missing else []
        return ToolOutcome("參數不正確：" + "；".join(parts), is_error=True)
    drafts_before = len(ctx.drafts)
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
    return ToolOutcome(dump(result), draft=draft)
