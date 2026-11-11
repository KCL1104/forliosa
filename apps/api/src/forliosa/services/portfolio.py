"""Portfolio holdings, summary and performance for a user (optionally one account)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from forliosa.api import serialize as ser
from forliosa.api.errors import not_found, unprocessable
from forliosa.domain.fees import ZERO
from forliosa.domain.ledger import Ledger, replay
from forliosa.domain.performance import (
    annualized_volatility,
    benchmark_returns,
    max_drawdown,
    simulate,
    twr_index,
    xirr,
    xirr_flows,
)
from forliosa.marketdata.base import InstrumentInfo, QuoteData, code_of_symbol, market_of_symbol
from forliosa.marketdata.service import MarketData
from forliosa.models import User
from forliosa.services.ledger_io import FxBook, LedgerInput, load_ledger_input, preferences_of
from forliosa.timeutil import iso_taipei, last_tw_trading_day, now_taipei, today_taipei, tw_trading_days

MARKET_LABELS = {"TWSE": "上市", "TPEX": "上櫃", "US": "美股"}
CURRENCY_LABELS = {"TWD": "新台幣", "USD": "美元"}
TYPE_LABELS = {"stock": "股票", "etf": "ETF"}
UPCOMING_DAYS = 60


@dataclass
class HoldingRow:
    symbol: str
    info: InstrumentInfo | None
    quantity: Decimal
    cost: Decimal  # trade currency
    cost_twd: Decimal
    currency: str
    account_ids: list[str]
    quote: QuoteData | None = None
    fx: Decimal = Decimal(1)
    by_account_value: dict[str, Decimal] = field(default_factory=dict)

    @property
    def price(self) -> Decimal | None:
        return self.quote.price if self.quote else None

    @property
    def market_value(self) -> Decimal:
        px = self.price if self.price is not None else (self.cost / self.quantity if self.quantity else ZERO)
        return self.quantity * px * self.fx

    @property
    def day_change(self) -> Decimal:
        q = self.quote
        if q is None or q.price is None or q.prev_close is None:
            return ZERO
        return self.quantity * (q.price - q.prev_close) * self.fx


@dataclass
class PortfolioState:
    inp: LedgerInput
    ledger: Ledger
    rows: list[HoldingRow]
    fx: FxBook
    is_demo: bool
    as_of: datetime


def _info(md: MarketData, symbol: str) -> InstrumentInfo | None:
    return md.instrument(symbol)


def compute_state(db: Session, user: User, md: MarketData, account_id: str | None = None) -> PortfolioState:
    inp = load_ledger_input(db, user, account_id)
    if account_id and not inp.accounts:
        raise not_found("找不到帳戶")
    start = inp.first_date or today_taipei()
    fx = FxBook.load(md, start)
    led = replay(inp.ledger_txns(fx), inp.method, inp.openings(fx)).ledger

    grouped: dict[str, HoldingRow] = {}
    for pos in led.open_positions():
        row = grouped.get(pos.symbol)
        if row is None:
            row = HoldingRow(pos.symbol, _info(md, pos.symbol), ZERO, ZERO, ZERO, pos.currency, [])
            grouped[pos.symbol] = row
        row.quantity += pos.quantity
        row.cost += pos.cost
        row.cost_twd += pos.cost_twd
        row.account_ids.append(pos.account_id)
    quotes = md.quotes(list(grouped)) if grouped else {}
    is_demo = False
    as_of_candidates: list[datetime] = []
    for sym, row in grouped.items():
        row.quote = quotes.get(sym)
        row.fx = fx.latest(row.currency)
        if row.quote is not None:
            is_demo |= row.quote.is_demo
            if row.quote.as_of:
                as_of_candidates.append(row.quote.as_of)
        else:
            is_demo = True  # valued at cost: not a real price
        for pos in led.open_positions():
            if pos.symbol == sym:
                px = row.price if row.price is not None else pos.avg_cost
                row.by_account_value[pos.account_id] = pos.quantity * px * row.fx
    if fx.used_usd and fx.is_demo:
        is_demo = True
    rows = sorted(grouped.values(), key=lambda r: r.market_value, reverse=True)
    as_of = max(as_of_candidates) if as_of_candidates else now_taipei()
    return PortfolioState(inp, led, rows, fx, is_demo, as_of)


def holdings(state: PortfolioState) -> list[dict[str, Any]]:
    total = sum((r.market_value for r in state.rows), ZERO)
    out = []
    for r in state.rows:
        info = r.info
        mv = r.market_value
        unreal = mv - r.cost_twd
        dc = r.day_change
        q = r.quote
        out.append({
            "symbol": r.symbol,
            "code": info.code if info else code_of_symbol(r.symbol),
            "name": info.name if info else r.symbol,
            "market": info.market if info else market_of_symbol(r.symbol),
            "type": info.type if info else "stock",
            "currency": r.currency,
            "industry": info.industry if info else None,
            "quantity": ser.qty(r.quantity),
            "avg_cost": ser.price(r.cost / r.quantity) if r.quantity else 0.0,
            "cost_basis": ser.money(r.cost_twd),
            "price": ser.price(r.price),
            "prev_close": ser.price(q.prev_close) if q else None,
            "market_value": ser.money(mv),
            "day_change": ser.money(dc),
            "day_change_pct": ser.ratio(dc / (mv - dc)) if mv - dc else None,
            "unrealized_pnl": ser.money(unreal),
            "unrealized_pnl_pct": ser.ratio(unreal / r.cost_twd) if r.cost_twd else None,
            "weight": ser.ratio(mv / total) if total else 0.0,
            "account_ids": sorted(set(r.account_ids)),
            "is_demo": bool(q.is_demo) if q else True,
        })
    return out


def _allocation(groups: dict[str, Decimal], labels: dict[str, str] | None, total: Decimal) -> list[dict]:
    items = sorted(groups.items(), key=lambda kv: kv[1], reverse=True)
    return [
        {"key": k, "label": (labels or {}).get(k, k), "value": ser.money(v),
         "weight": ser.ratio(v / total) if total else 0.0}
        for k, v in items
    ]


def summary(state: PortfolioState, md: MarketData) -> dict[str, Any]:
    rows = state.rows
    mv = sum((r.market_value for r in rows), ZERO)
    cost = sum((r.cost_twd for r in rows), ZERO)
    unreal = mv - cost
    realized = sum((e.pnl_twd for e in state.ledger.realized), ZERO)
    dividends = sum((e.net_twd for e in state.ledger.income), ZERO)
    total_pnl = unreal + realized + dividends
    day = sum((r.day_change for r in rows), ZERO)

    by_market: dict[str, Decimal] = defaultdict(Decimal)
    by_industry: dict[str, Decimal] = defaultdict(Decimal)
    by_currency: dict[str, Decimal] = defaultdict(Decimal)
    by_type: dict[str, Decimal] = defaultdict(Decimal)
    by_account: dict[str, Decimal] = defaultdict(Decimal)
    for r in rows:
        v = r.market_value
        info = r.info
        by_market[info.market if info else market_of_symbol(r.symbol)] += v
        by_industry[(info.industry if info else None) or "其他"] += v
        by_currency[r.currency] += v
        by_type[info.type if info else "stock"] += v
        for acc, av in r.by_account_value.items():
            by_account[acc] += av
    account_names = {a.id: a.name for a in state.inp.accounts}

    upcoming = []
    today = today_taipei()
    horizon = today + timedelta(days=UPCOMING_DAYS)
    is_demo = state.is_demo
    for r in rows:
        ans = md.dividends(r.symbol)
        for ev in ans.value:
            if ev.ex_dividend_date and today < ev.ex_dividend_date <= horizon and ev.cash_dividend > 0:
                upcoming.append({
                    "symbol": r.symbol,
                    "name": r.info.name if r.info else r.symbol,
                    "ex_dividend_date": ev.ex_dividend_date,
                    "cash_dividend": ser.price(ev.cash_dividend),
                    "estimated_amount": ser.money(r.quantity * ev.cash_dividend * r.fx),
                })
                is_demo |= ev.is_demo or ans.is_demo
    upcoming.sort(key=lambda u: u["ex_dividend_date"])

    return {
        "as_of": iso_taipei(state.as_of),
        "market_value": ser.money(mv),
        "cost_basis": ser.money(cost),
        "unrealized_pnl": ser.money(unreal),
        "unrealized_pnl_pct": ser.ratio(unreal / cost) if cost else None,
        "realized_pnl": ser.money(realized),
        "dividend_income": ser.money(dividends),
        "total_pnl": ser.money(total_pnl),
        "total_return_pct": ser.ratio(total_pnl / cost) if cost else None,
        "day_change": ser.money(day),
        "day_change_pct": ser.ratio(day / (mv - day)) if mv - day else None,
        "allocation": {
            "by_market": _allocation(by_market, MARKET_LABELS, mv),
            "by_industry": _allocation(by_industry, None, mv),
            "by_currency": _allocation(by_currency, CURRENCY_LABELS, mv),
            "by_type": _allocation(by_type, TYPE_LABELS, mv),
            "by_account": _allocation(by_account, account_names, mv),
        },
        "upcoming_dividends": upcoming,
        "is_demo": is_demo,
    }


# -- performance --------------------------------------------------------------------------------
PERFORMANCE_RANGES = ("1M", "3M", "6M", "YTD", "1Y", "ALL")


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    raise ValueError(d)


def range_start(range_: str, end: date, inception: date) -> date:
    match range_:
        case "5D":
            return end - timedelta(days=7)
        case "1M":
            return add_months(end, -1)
        case "3M":
            return add_months(end, -3)
        case "6M":
            return add_months(end, -6)
        case "YTD":
            return date(end.year, 1, 1)
        case "1Y":
            return add_months(end, -12)
        case "3Y":
            return add_months(end, -36)
        case "5Y":
            return add_months(end, -60)
        case "10Y":
            return add_months(end, -120)
        case "ALL" | "MAX":
            return inception
    raise unprocessable(f"不支援的區間：{range_}")


def _forward_filled(axis: list[date], closes: dict[date, Decimal]) -> dict[date, Decimal]:
    out: dict[date, Decimal] = {}
    known = sorted(closes)
    j = 0
    last: Decimal | None = None
    for d in axis:
        while j < len(known) and known[j] <= d:
            last = closes[known[j]]
            j += 1
        if last is not None:
            out[d] = last
    return out


def performance(db: Session, user: User, md: MarketData, range_: str, benchmark: str | None,
                account_id: str | None) -> dict[str, Any]:
    if range_ not in PERFORMANCE_RANGES:
        raise unprocessable(f"不支援的區間：{range_}（可用 {'、'.join(PERFORMANCE_RANGES)}）")
    prefs = preferences_of(user)
    bench_symbol = md.resolve(benchmark or prefs["benchmark"])
    if bench_symbol is None:
        raise unprocessable(f"找不到基準商品：{benchmark or prefs['benchmark']}", code="unknown_symbol")
    bench_info = md.instrument(bench_symbol)

    inp = load_ledger_input(db, user, account_id)
    if account_id and not inp.accounts:
        raise not_found("找不到帳戶")
    inception = inp.first_date
    today = today_taipei()
    empty = {
        "range": range_, "start_date": None, "end_date": None, "twr": None, "xirr": None, "max_drawdown": None,
        "volatility": None,
        "benchmark": {"symbol": bench_symbol, "name": bench_info.name if bench_info else bench_symbol, "twr": None},
        "series": [], "dividends_by_month": [], "realized_by_year": [], "is_demo": False,
    }
    if inception is None or inception > today:
        return empty

    symbols = sorted({t.symbol for t in inp.effective_transactions() if t.symbol and t.type in (
        "buy", "sell", "stock_dividend", "split", "capital_reduction", "cash_dividend")}
        | {s.symbol for s in inp.snapshots})
    hist_start = inception - timedelta(days=14)
    md.quotes([*symbols, bench_symbol])  # one batched quote call warms the cache used by history()
    histories = {s: md.history(s, hist_start, today) for s in symbols}
    bench_hist = md.history(bench_symbol, hist_start, today)
    is_demo = any(h.is_demo for h in histories.values())

    last_close_day = max((h.candles[-1].t for h in histories.values() if h.candles), default=None)
    end = min(today, last_close_day) if last_close_day else last_tw_trading_day(today)
    # Date axis = days on which any held instrument actually traded (from the price data itself),
    # so exchange holidays need no calendar; fall back to the built-in TW calendar without data.
    axis = sorted({c.t for h in histories.values() for c in h.candles if inception <= c.t <= end})
    if not axis:
        axis = tw_trading_days(inception, end)
    if not axis:
        return empty

    prices = {s: _forward_filled(axis, {c.t: c.c for c in h.candles}) for s, h in histories.items()}
    fx = FxBook.load(md, inception, end)

    def price_fn(symbol: str, d: date) -> Decimal | None:
        return prices.get(symbol, {}).get(d)

    def fx_fn(currency: str, d: date) -> Decimal:
        return fx.rate(currency, d)

    sim = simulate(inp.ledger_txns(fx), axis, price_fn, fx_fn, inp.method, inp.openings(fx))
    if fx.used_usd and fx.is_demo:
        is_demo = True
    points = sim.points

    nominal = range_start(range_, end, inception)
    si = next((i for i, p in enumerate(points) if p.t >= nominal), len(points) - 1)
    # Never start before the first day with money in the portfolio.
    first_active = next((i for i, p in enumerate(points) if p.value > 0 or p.inflow > 0), si)
    si = max(si, first_active)
    ei = len(points) - 1
    window = points[si:ei + 1]
    returns = [p.daily_return for p in window]
    index = twr_index(returns)
    active_returns = [p.daily_return for i, p in enumerate(window)
                      if (points[si + i - 1].value if si + i > 0 else ZERO) + p.inflow > 0]

    # Benchmark: total return (dividends reinvested on ex-date), aligned to the same axis.
    b_closes = _forward_filled(axis, {c.t: c.c for c in bench_hist.candles})
    b_divs = {e.ex_dividend_date: e.cash_dividend for e in md.dividends(bench_symbol).value if e.ex_dividend_date}
    b_splits = {e.date: e.ratio for e in md.corporate_events(bench_symbol) if e.kind == "split"}
    b_returns = benchmark_returns(axis, b_closes.get, lambda d: b_divs.get(d, ZERO),
                                  lambda d: b_splits.get(d, Decimal(1)))
    b_index = twr_index(b_returns[si:ei + 1]) if b_closes else []
    is_demo |= bench_hist.is_demo

    series = [
        {
            "t": p.t,
            "market_value": ser.money(p.value),
            "net_invested": ser.money(p.net_invested),
            "twr_index": round(index[i], 6),
            "benchmark_index": round(b_index[i], 6) if b_index else None,
        }
        for i, p in enumerate(window)
    ]

    by_month: dict[str, Decimal] = defaultdict(Decimal)
    by_year: dict[int, Decimal] = defaultdict(Decimal)
    for p in window:
        if p.dividends:
            by_month[p.t.strftime("%Y-%m")] += p.dividends
        if p.realized:
            by_year[p.t.year] += p.realized

    rate = xirr(xirr_flows(points, si, ei))
    vol = annualized_volatility(active_returns)
    return {
        "range": range_,
        "start_date": window[0].t,
        "end_date": window[-1].t,
        "twr": round(index[-1] - 1.0, 6) if index else None,
        "xirr": round(rate, 6) if rate is not None else None,
        "max_drawdown": round(max_drawdown(index), 6) if index else None,
        "volatility": round(vol, 6) if vol is not None else None,
        "benchmark": {
            "symbol": bench_symbol,
            "name": bench_info.name if bench_info else bench_symbol,
            "twr": round(b_index[-1] - 1.0, 6) if b_index else None,
        },
        "series": series,
        "dividends_by_month": [{"month": k, "amount": ser.money(v)} for k, v in sorted(by_month.items())],
        "realized_by_year": [{"year": k, "amount": ser.money(v)} for k, v in sorted(by_year.items())],
        "is_demo": is_demo,
    }
