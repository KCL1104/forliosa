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
from forliosa.domain.rounds import Round, holding_rounds
from forliosa.marketdata.base import InstrumentInfo, QuoteData, code_of_symbol, market_of_symbol
from forliosa.marketdata.indices import is_index
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
        base = (q.reference_price if q.reference_price is not None else q.prev_close) if q else None
        if q is None or q.price is None or base is None:
            return ZERO
        return self.quantity * (q.price - base) * self.fx


@dataclass
class PortfolioState:
    inp: LedgerInput
    ledger: Ledger
    rows: list[HoldingRow]
    fx: FxBook
    is_demo: bool
    as_of: datetime
    demo_data_allowed: bool = True  # personal: a holding without a quote is flagged is_demo (valued at cost)


def _info(md: MarketData, symbol: str) -> InstrumentInfo | None:
    return md.instrument(symbol)


@dataclass
class LedgerView:
    """The replayed ledger without quotes (closed rounds, markers)."""

    inp: LedgerInput
    ledger: Ledger
    fx: FxBook


def ledger_view(db: Session, user: User, md: MarketData, account_id: str | None = None) -> LedgerView:
    inp = load_ledger_input(db, user, account_id)
    if account_id and not inp.accounts:
        raise not_found("找不到帳戶")
    fx = FxBook.load(md, inp.first_date or today_taipei())
    return LedgerView(inp, replay(inp.ledger_txns(fx), inp.method, inp.openings(fx)).ledger, fx)


def compute_state(db: Session, user: User, md: MarketData, account_id: str | None = None) -> PortfolioState:
    view = ledger_view(db, user, md, account_id)
    inp, fx, led = view.inp, view.fx, view.ledger

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
        elif md.demo_data_allowed:
            is_demo = True  # valued at cost: not a real price (commercial: price is null, nothing synthetic)
        for pos in led.open_positions():
            if pos.symbol == sym:
                px = row.price if row.price is not None else pos.avg_cost
                row.by_account_value[pos.account_id] = pos.quantity * px * row.fx
    if fx.used_usd and fx.is_demo:
        is_demo = True
    rows = sorted(grouped.values(), key=lambda r: r.market_value, reverse=True)
    as_of = max(as_of_candidates) if as_of_candidates else now_taipei()
    return PortfolioState(inp, led, rows, fx, is_demo, as_of, md.demo_data_allowed)


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
            "is_demo": bool(q.is_demo) if q else state.demo_data_allowed,
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


# -- closed positions (出清紀錄) -------------------------------------------------------------------
def round_out(r: Round, md: MarketData) -> dict[str, Any]:
    """A holding round in TWD (see :mod:`forliosa.domain.rounds` for every field's definition)."""
    from forliosa.datapolicy import labels

    info = md.instrument(r.symbol)
    return {
        "symbol": r.symbol,
        "name": info.name if info else r.symbol,
        "account_id": r.account_id,
        "currency": r.currency,
        "opened_at": r.opened_at,
        "closed_at": r.closed_at,
        "holding_days": r.holding_days,
        "total_bought_qty": ser.qty(r.bought_qty),
        "total_sold_qty": ser.qty(r.sold_qty),
        "cost_basis": ser.money(r.buy_cost),
        "realized_pnl": ser.money(r.realized),
        "realized_pnl_pct": ser.ratio(r.realized_pct),
        "dividends_received": ser.money(r.dividends),
        "fees_and_taxes": ser.money(r.fees_and_taxes),
        "sources": labels(["ledger"]),
    }


def closed_rounds(view: LedgerView | PortfolioState, symbol: str | None = None) -> list[Round]:
    """Closed rounds, most recently closed first (a symbol can have several)."""
    rounds = [r for r in holding_rounds(view.ledger) if r.is_closed and (symbol is None or r.symbol == symbol)]
    rounds.sort(key=lambda r: (r.closed_at, r.opened_at, r.symbol, r.account_id), reverse=True)
    return rounds


def closed_positions(view: LedgerView, md: MarketData) -> list[dict[str, Any]]:
    return [round_out(r, md) for r in closed_rounds(view)]


# -- performance --------------------------------------------------------------------------------
PERFORMANCE_RANGES = ("1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "ALL")
# Short ranges counted in trading days. Their series starts with the base close (twr_index 1.0):
# 1D = previous close -> latest close/quote (2 points), 5D = the last 5 trading days (6 points).
TRADING_DAY_RANGES = {"1D": 1, "5D": 5}


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
    bench_symbol = md.resolve_benchmark(benchmark or prefs["benchmark"])
    if bench_symbol is None:
        raise unprocessable(f"找不到基準商品：{benchmark or prefs['benchmark']}", code="unknown_symbol")
    bench_name = md.benchmark_name(bench_symbol)
    bench_is_index = is_index(bench_symbol)

    inp = load_ledger_input(db, user, account_id)
    if account_id and not inp.accounts:
        raise not_found("找不到帳戶")
    inception = inp.first_date
    today = today_taipei()
    empty = {
        "range": range_, "start_date": None, "end_date": None, "twr": None, "xirr": None, "max_drawdown": None,
        "volatility": None,
        "benchmark": {"symbol": bench_symbol, "name": bench_name, "twr": None},
        "series": [], "dividends_by_month": [], "realized_by_year": [], "is_demo": False, "notes": [],
    }
    if inception is None or inception > today:
        return empty

    symbols = sorted({t.symbol for t in inp.effective_transactions() if t.symbol and t.type in (
        "buy", "sell", "stock_dividend", "split", "capital_reduction", "cash_dividend")}
        | {s.symbol for s in inp.snapshots})
    hist_start = inception - timedelta(days=14)
    # one batched quote call warms the cache used by history()
    md.quotes([*symbols] if bench_is_index else [*symbols, bench_symbol])
    histories = {s: md.history(s, hist_start, today) for s in symbols}
    bench_hist = (md.index_history if bench_is_index else md.history)(bench_symbol, hist_start, today)
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

    ei = len(points) - 1
    # Never start before the first day with money in the portfolio.
    first_active = next((i for i, p in enumerate(points) if p.value > 0 or p.inflow > 0), ei)
    days = TRADING_DAY_RANGES.get(range_)
    if days is not None:
        # The window opens on a base close (twr_index 1.0, its own return excluded) and covers the
        # last ``days`` daily returns. A younger portfolio opens on the day before its first money
        # (value 0) or, when there is no such day on the axis, on its first day like the long ranges.
        if ei - days >= first_active:
            si, based = ei - days, True
        elif first_active > 0:
            si, based = first_active - 1, True
        else:
            si, based = 0, False
    else:
        nominal = range_start(range_, end, inception)
        si = next((i for i, p in enumerate(points) if p.t >= nominal), ei)
        si = max(si, first_active)
        based = False

    # Commercial policy: no demo prices. Only days on which every held position has a real close are
    # valued; a window reaching further back starts (as a base close, like 1D/5D) at the first such day.
    notes: list[str] = []
    clipped = False
    if md.policy == "commercial":
        from forliosa.services.coverage import US_NOTE, accumulating_note

        base = max((i for i, p in enumerate(points) if p.unpriced), default=-1) + 1
        if base >= ei:  # fewer than two fully priced closes: nothing honest to show yet
            missing = sorted(points[ei].unpriced)
            us = [m for m in missing if market_of_symbol(m) == "US"]
            if us:
                notes.append(f"{'、'.join(us)}：{US_NOTE}，含美股時無法計算績效")
            if len(us) < len(missing) or not missing:
                notes.append(f"{accumulating_note(md)}；需要持股期間每天的收盤價才能計算績效")
            return {**empty, "notes": notes}
        lumped = inception < axis[0]  # transactions before the first archived day are all booked on it
        if si < base or (lumped and si == 0 and not based):
            si, based, clipped = base, True, True
            notes.append(f"{accumulating_note(md)}；績效從 {points[si].t.isoformat()} 收盤開始計算")
    window = points[si:ei + 1]
    returns = [p.daily_return for p in window]
    if based:
        returns[0] = 0.0
    index = twr_index(returns)
    active_returns = [p.daily_return for i, p in enumerate(window)
                      if (points[si + i - 1].value if si + i > 0 else ZERO) + p.inflow > 0
                      and not (based and i == 0)]

    # Benchmark: total return (dividends reinvested on ex-date), aligned to the same axis. A total
    # return index (^TAIEXTR) already includes dividends: its plain daily change is the return.
    b_closes = _forward_filled(axis, {c.t: c.c for c in bench_hist.candles})
    if bench_is_index:
        b_divs: dict[date, Decimal] = {}
        b_splits: dict[date, Decimal] = {}
    else:
        b_divs = {e.ex_dividend_date: e.cash_dividend for e in md.dividends(bench_symbol).value
                  if e.ex_dividend_date}
        b_splits = {e.date: e.ratio for e in md.corporate_events(bench_symbol) if e.kind == "split"}
    b_returns = benchmark_returns(axis, b_closes.get, lambda d: b_divs.get(d, ZERO),
                                  lambda d: b_splits.get(d, Decimal(1)))
    b_window = b_returns[si:ei + 1]
    if based and b_window:
        b_window[0] = 0.0
    b_index = twr_index(b_window) if b_closes else []
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
    for p in window[1:] if based else window:  # the base day's flows are before the window
        if p.dividends:
            by_month[p.t.strftime("%Y-%m")] += p.dividends
        if p.realized:
            by_year[p.t.year] += p.realized

    # Annualizing one to five days of cash flows is meaningless: no XIRR for the short ranges. A clipped
    # window opens with the base day's market value as the initial investment.
    if days is not None:
        rate = None
    elif clipped:
        rate = xirr(xirr_flows(points, si + 1, ei)) if si < ei else None
    else:
        rate = xirr(xirr_flows(points, si, ei))
    if md.policy == "commercial" and not b_closes:
        notes.append(f"基準 {bench_name} 目前沒有可商用的資料")
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
            "name": bench_name,
            "twr": round(b_index[-1] - 1.0, 6) if b_index else None,
        },
        "series": series,
        "dividends_by_month": [{"month": k, "amount": ser.money(v)} for k, v in sorted(by_month.items())],
        "realized_by_year": [{"year": k, "amount": ser.money(v)} for k, v in sorted(by_year.items())],
        "is_demo": is_demo,
        "notes": notes,
    }


# -- upcoming (本週事項) ---------------------------------------------------------------------------
UPCOMING_MAX_DAYS = 90


def upcoming(state: PortfolioState, md: MarketData, days: int,
             recurring: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Ex-dividend dates and dividend payments of current holdings in [today, today + days], plus the
    recurring-plan debits (定期定額, built by ``services.recurring.upcoming_items``).

    ``amount_estimate`` = shares held now × cash dividend per share (gross, TWD). For a payment whose
    ex-date already passed, a recorded cash-dividend transaction's amount is used when there is one.
    For a recurring debit it is the plan's amount (money going out).
    """
    from forliosa.datapolicy import labels

    if not 1 <= days <= UPCOMING_MAX_DAYS:
        raise unprocessable(f"days 必須介於 1 與 {UPCOMING_MAX_DAYS} 之間")
    today = today_taipei()
    horizon = today + timedelta(days=days)
    recorded: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
    for t in state.inp.effective_transactions():
        if t.type == "cash_dividend" and t.symbol:
            recorded[(t.symbol, t.trade_date)] += t.amount or ZERO
    out = []
    for r in state.rows:
        ans = md.dividends(r.symbol)
        name = r.info.name if r.info else r.symbol
        sources = labels(["demo"] if ans.is_demo else ans.source.split("+"))
        for ev in ans.value:
            ex, pay = ev.ex_dividend_date, ev.payment_date
            if ex and today <= ex <= horizon:
                amount = r.quantity * ev.cash_dividend * r.fx if ev.cash_dividend else None
                pending = "" if ev.cash_dividend or ev.stock_dividend else "（金額未公告）"
                kind = "權" if ev.stock_dividend and not ev.cash_dividend else "息"
                out.append({"date": ex, "type": "ex_dividend", "symbol": r.symbol, "title": f"{name} 除{kind}{pending}",
                            "amount_estimate": ser.money(amount), "is_demo": ev.is_demo or ans.is_demo,
                            "sources": sources})
            if pay and today <= pay <= horizon and ev.cash_dividend > 0:
                got = recorded.get((r.symbol, ex)) if ex else None
                amount = got * r.fx if got else r.quantity * ev.cash_dividend * r.fx
                out.append({"date": pay, "type": "dividend_payment", "symbol": r.symbol,
                            "title": f"{name} 現金股利入帳", "amount_estimate": ser.money(amount),
                            "is_demo": ev.is_demo or ans.is_demo, "sources": sources})
    out.extend(recurring or [])
    out.sort(key=lambda u: (u["date"], u["type"], u["symbol"] or ""))
    return out
