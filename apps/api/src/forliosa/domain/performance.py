"""Portfolio performance: daily value series, TWR, XIRR, drawdown, volatility, benchmark.

Definitions follow ``docs/api-contract.md`` ("績效計算定義"):

* ``V_t``  — market value of all holdings at the close of day t, in TWD (cash excluded).
* ``I_t``  — inflow, assumed before the open: buy cost including commission. A holdings-only
  snapshot enters as an inflow at its market value on its ``as_of`` date, so tracking starts
  that day (it has no history before it).
* ``O_t``  — outflow, assumed after the close: sell proceeds net of commission and tax, cash
  dividends net of the NHI premium / withholding, returned capital from a capital reduction.
* ``r_t = (V_t + O_t) / (V_{t-1} + I_t) - 1`` and ``r_t = 0`` when the denominator is 0.
* TWR ``= ∏(1 + r_t) - 1``.

Prices are unadjusted closes; dividends come only from transactions, so nothing is counted twice.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from forliosa.domain.fees import ZERO
from forliosa.domain.ledger import CostMethod, Ledger, LedgerTxn, OpeningPosition

PriceFn = Callable[[str, date], Decimal | None]
FxFn = Callable[[str, date], Decimal]

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class SeriesPoint:
    t: date
    value: Decimal  # V_t (TWD)
    inflow: Decimal  # I_t (TWD)
    outflow: Decimal  # O_t (TWD)
    net_invested: Decimal  # cumulative I_t minus sell/returned-capital proceeds (TWD)
    daily_return: float  # r_t
    dividends: Decimal  # net cash dividends received on t (TWD), part of O_t
    realized: Decimal  # realized P&L booked on t (TWD)


@dataclass
class Simulation:
    points: list[SeriesPoint]
    ledger: Ledger


def daily_return(v_prev: Decimal, v_t: Decimal, inflow: Decimal, outflow: Decimal) -> float:
    """``r_t = (V_t + O_t) / (V_{t-1} + I_t) - 1``; 0 when the denominator is 0."""
    denom = v_prev + inflow
    if denom == 0:
        return 0.0
    return float((v_t + outflow) / denom) - 1.0


def simulate(
    txns: Sequence[LedgerTxn],
    axis: Sequence[date],
    price_fn: PriceFn,
    fx_fn: FxFn,
    method: CostMethod = CostMethod.AVERAGE,
    openings: Sequence[OpeningPosition] = (),
) -> Simulation:
    """Replay the ledger day by day over ``axis`` (sorted trading days) and value it each close.

    Transactions dated on a non-trading day are booked on the next trading day in ``axis``.
    Transactions before ``axis[0]`` are booked on ``axis[0]``; after ``axis[-1]`` are ignored.
    When a price is missing the last trade price is used, then the average cost.
    """
    ledger = Ledger(method)
    txns_sorted = sorted(txns, key=LedgerTxn.sort_key)
    opens_sorted = sorted(openings, key=lambda o: o.as_of)
    ti = oi = 0
    last_trade_price: dict[str, Decimal] = {}
    points: list[SeriesPoint] = []
    v_prev = ZERO
    net_invested = ZERO
    n_income = n_realized = 0

    for d in axis:
        day: list[LedgerTxn] = []
        while ti < len(txns_sorted) and txns_sorted[ti].trade_date <= d:
            t = txns_sorted[ti]
            day.append(t)
            if t.symbol and t.price > 0 and t.type.value in ("buy", "sell"):
                last_trade_price[t.symbol] = t.price
            ti += 1
        opening_inflow = ZERO
        while oi < len(opens_sorted) and opens_sorted[oi].as_of <= d:
            op = opens_sorted[oi]
            ledger.open(op)
            px = price_fn(op.symbol, d)
            unit = px if px is not None else op.avg_cost
            opening_inflow += op.quantity * unit * fx_fn(op.currency, d)
            oi += 1
        flows = ledger.apply_day(day)
        inflow = flows.inflow + opening_inflow

        value = ZERO
        for pos in ledger.positions.values():
            qty = pos.quantity
            if qty <= 0:
                continue
            px = price_fn(pos.symbol, d)
            if px is None:
                px = last_trade_price.get(pos.symbol, pos.avg_cost)
            value += qty * px * fx_fn(pos.currency, d)

        dividends = sum((e.net_twd for e in ledger.income[n_income:]), ZERO)
        realized = sum((e.pnl_twd for e in ledger.realized[n_realized:]), ZERO)
        n_income, n_realized = len(ledger.income), len(ledger.realized)

        net_invested += inflow - flows.sell_proceeds
        r = daily_return(v_prev, value, inflow, flows.outflow)
        points.append(SeriesPoint(d, value, inflow, flows.outflow, net_invested, r, dividends, realized))
        v_prev = value
    return Simulation(points, ledger)


def twr(returns: Sequence[float]) -> float:
    acc = 1.0
    for r in returns:
        acc *= 1.0 + r
    return acc - 1.0


def twr_index(returns: Sequence[float]) -> list[float]:
    """Cumulative index; the value at t includes r_t (so it starts at 1 + r_first)."""
    out: list[float] = []
    acc = 1.0
    for r in returns:
        acc *= 1.0 + r
        out.append(acc)
    return out


def max_drawdown(index: Sequence[float]) -> float:
    """Most negative peak-to-trough change of the index (0 if it never falls)."""
    peak = 1.0  # the index is relative to 1.0 before the first day
    worst = 0.0
    for v in index:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1.0)
    return worst


def annualized_volatility(returns: Sequence[float]) -> float | None:
    """Sample standard deviation of daily returns × √252; None with fewer than 2 returns."""
    n = len(returns)
    if n < 2:
        return None
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    return math.sqrt(var) * math.sqrt(TRADING_DAYS_PER_YEAR)


def _xnpv(rate: float, flows: Sequence[tuple[date, float]]) -> float:
    d0 = flows[0][0]
    return sum(cf / (1.0 + rate) ** ((d - d0).days / 365.0) for d, cf in flows)


def _dxnpv(rate: float, flows: Sequence[tuple[date, float]]) -> float:
    d0 = flows[0][0]
    total = 0.0
    for d, cf in flows:
        y = (d - d0).days / 365.0
        total -= y * cf / (1.0 + rate) ** (y + 1.0)
    return total


def xirr(flows: Sequence[tuple[date, float]], guess: float = 0.1) -> float | None:
    """Annualized internal rate of return of dated cash flows (Excel XIRR, actual/365).

    Investor perspective: money paid in is negative, money received (and the terminal value)
    positive. Newton–Raphson first; if it does not converge, bisection on a bracketing interval.
    Returns None when there is no sign change (no solution).
    """
    flows = sorted(((d, float(cf)) for d, cf in flows if cf != 0), key=lambda x: x[0])
    if len(flows) < 2:
        return None
    if not (any(cf > 0 for _, cf in flows) and any(cf < 0 for _, cf in flows)):
        return None
    if flows[0][0] == flows[-1][0]:
        return None

    rate = guess
    for _ in range(100):
        try:
            f = _xnpv(rate, flows)
            df = _dxnpv(rate, flows)
        except (OverflowError, ZeroDivisionError):
            break
        if df == 0 or not math.isfinite(f) or not math.isfinite(df):
            break
        new = rate - f / df
        if new <= -1.0 or not math.isfinite(new):
            break
        if abs(new - rate) < 1e-10:
            if abs(_xnpv(new, flows)) < 1e-6 * max(1.0, max(abs(cf) for _, cf in flows)):
                return new
            break
        rate = new

    # Bisection fallback: find a bracket in (-0.999999, hi].
    lo, hi = -0.999999, 1.0

    def npv(r: float) -> float:
        try:
            return _xnpv(r, flows)
        except (OverflowError, ZeroDivisionError):
            return math.copysign(math.inf, flows[0][1])

    f_lo = npv(lo)
    f_hi = npv(hi)
    while f_lo * f_hi > 0 and hi < 1e6:
        hi *= 2.0
        f_hi = npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(300):
        mid = (lo + hi) / 2.0
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9 or (hi - lo) < 1e-12:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def xirr_flows(points: Sequence[SeriesPoint], start: int, end: int,
               opening_date: date | None = None) -> list[tuple[date, float]]:
    """Investor-perspective flows for ``points[start..end]`` (inclusive).

    Opening value ``V_{start-1}`` is paid in (negative) on the previous day, each day's inflow is
    negative, each day's outflow positive, and the terminal value ``V_end`` positive.
    """
    flows: list[tuple[date, float]] = []
    if start > 0 and points[start - 1].value > 0:
        flows.append((opening_date or points[start - 1].t, -float(points[start - 1].value)))
    for p in points[start:end + 1]:
        if p.inflow:
            flows.append((p.t, -float(p.inflow)))
        if p.outflow:
            flows.append((p.t, float(p.outflow)))
    if points[end].value:
        flows.append((points[end].t, float(points[end].value)))
    return flows


def benchmark_returns(
    axis: Sequence[date],
    close_fn: Callable[[date], Decimal | None],
    dividend_on: Callable[[date], Decimal] | None = None,
    split_on: Callable[[date], Decimal] | None = None,
) -> list[float]:
    """Total-return daily returns of a benchmark: ``(P_t × split + D_t) / P_{t-1} - 1``.

    Cash dividends are counted on their ex-date (reinvested), splits keep the index continuous.
    The first day's return is 0 (no previous close inside the axis).
    """
    out: list[float] = []
    prev: Decimal | None = None
    for d in axis:
        px = close_fn(d)
        if px is None or prev is None or prev == 0:
            out.append(0.0)
        else:
            ratio = split_on(d) if split_on else Decimal(1)
            div = dividend_on(d) if dividend_on else ZERO
            out.append(float((px * ratio + div) / prev) - 1.0)
        if px is not None:
            prev = px
    return out
