"""Ledger replay: transactions -> positions per (account, symbol), realized P&L and income.

Conventions
-----------
* Quantities are shares (``Decimal``; Taiwan trades are whole shares, odd lots allowed).
* A position's cost includes buy commissions. It is tracked in the trade currency and, in
  parallel, in TWD at each transaction's FX rate (``fx_rate`` = TWD per 1 unit of currency).
* Realized P&L on a sell = (gross - fee - tax) - cost of the shares sold.
* Two cost methods: moving average (``average``, the Taiwan broker default) and ``fifo``.
* Day-trade sells (``is_day_trade``) are matched first against the same day's buys of that account and symbol
  (whether or not the buy itself was flagged: the entry form only flags sells), so the day-trade result does not
  disturb the average cost of the inventory (both methods).
* Within one trade date, events apply in this order: dividends and corporate actions (they
  belong to holders at the previous close), then buys and ordinary sells in the order they were entered (a sell
  then a re-buy keeps the old average cost; 2026-11-14 review), then day-trade sells, then cash-only items.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from forliosa.domain.fees import ONE, ZERO, stock_dividend_shares, truncate


class TxnType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    CASH_DIVIDEND = "cash_dividend"
    STOCK_DIVIDEND = "stock_dividend"
    SPLIT = "split"
    CAPITAL_REDUCTION = "capital_reduction"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    FEE = "fee"
    TAX = "tax"
    INTEREST = "interest"


SECURITY_TYPES = frozenset(
    {TxnType.BUY, TxnType.SELL, TxnType.CASH_DIVIDEND, TxnType.STOCK_DIVIDEND, TxnType.SPLIT,
     TxnType.CAPITAL_REDUCTION}
)
CASH_TYPES = frozenset({TxnType.DEPOSIT, TxnType.WITHDRAWAL, TxnType.FEE, TxnType.TAX, TxnType.INTEREST})

_DAY_ORDER = {
    TxnType.CASH_DIVIDEND: 0,
    TxnType.STOCK_DIVIDEND: 0,
    TxnType.SPLIT: 0,
    TxnType.CAPITAL_REDUCTION: 0,
    TxnType.DEPOSIT: 1,
    TxnType.BUY: 2,
    TxnType.SELL: 2,  # same rank as buys: the entry order decides (see the module docstring)
    TxnType.FEE: 4,
    TxnType.TAX: 4,
    TxnType.INTEREST: 4,
    TxnType.WITHDRAWAL: 5,
}
_DAY_TRADE_SELL = 3


class CostMethod(StrEnum):
    AVERAGE = "average"
    FIFO = "fifo"


class LedgerError(ValueError):
    """Raised in strict mode when transactions are inconsistent (e.g. selling more than held)."""


@dataclass(frozen=True)
class LedgerTxn:
    id: str
    account_id: str
    symbol: str | None
    type: TxnType
    trade_date: date
    quantity: Decimal = ZERO
    price: Decimal = ZERO
    amount: Decimal = ZERO
    fee: Decimal = ZERO
    tax: Decimal = ZERO
    health_insurance: Decimal = ZERO
    currency: str = "TWD"
    is_day_trade: bool = False
    fx_rate: Decimal = ONE  # TWD per 1 unit of ``currency`` on ``trade_date``
    seq: int = 0  # tie-breaker within a day (creation order)

    def sort_key(self) -> tuple:
        rank = _DAY_ORDER[self.type]
        if self.type is TxnType.SELL and self.is_day_trade:
            rank = _DAY_TRADE_SELL  # after the day's buys it is paired with
        return (self.trade_date, rank, self.seq, self.id)


@dataclass
class Lot:
    quantity: Decimal
    cost: Decimal  # total, trade currency
    cost_twd: Decimal  # total, TWD
    acquired: date
    day_trade: bool = False


@dataclass
class Position:
    account_id: str
    symbol: str
    currency: str
    method: CostMethod
    lots: list[Lot] = field(default_factory=list)

    @property
    def quantity(self) -> Decimal:
        return sum((lot.quantity for lot in self.lots), ZERO)

    @property
    def cost(self) -> Decimal:
        return sum((lot.cost for lot in self.lots), ZERO)

    @property
    def cost_twd(self) -> Decimal:
        return sum((lot.cost_twd for lot in self.lots), ZERO)

    @property
    def avg_cost(self) -> Decimal:
        q = self.quantity
        return self.cost / q if q else ZERO

    # -- mutations ---------------------------------------------------------------------------
    def add(self, lot: Lot) -> None:
        if self.method is CostMethod.AVERAGE and not lot.day_trade:
            pool = self._pool()
            if pool is None:
                self.lots.insert(0, lot)
            else:
                pool.quantity += lot.quantity
                pool.cost += lot.cost
                pool.cost_twd += lot.cost_twd
                pool.acquired = min(pool.acquired, lot.acquired)
        else:
            self.lots.append(lot)

    def _pool(self) -> Lot | None:
        for lot in self.lots:
            if not lot.day_trade and lot.quantity > 0:
                return lot
        return None

    def remove(self, quantity: Decimal, on: date, day_trade: bool) -> tuple[Decimal, Decimal]:
        """Remove ``quantity`` shares; return (cost, cost_twd) of the shares removed."""
        order: list[Lot] = []
        if day_trade:
            order.extend(lot for lot in self.lots if lot.day_trade and lot.acquired == on)
        seen = {id(lot) for lot in order}
        order.extend(lot for lot in self.lots if id(lot) not in seen)
        remaining = quantity
        cost = ZERO
        cost_twd = ZERO
        for lot in order:
            if remaining <= 0:
                break
            take = min(lot.quantity, remaining)
            if take == lot.quantity:
                c, ct = lot.cost, lot.cost_twd
            else:
                c = lot.cost * take / lot.quantity
                ct = lot.cost_twd * take / lot.quantity
            lot.quantity -= take
            lot.cost -= c
            lot.cost_twd -= ct
            cost += c
            cost_twd += ct
            remaining -= take
        self.lots = [lot for lot in self.lots if lot.quantity > 0]
        return cost, cost_twd

    def rescale(self, new_total: Decimal) -> None:
        """Change the share count to ``new_total`` proportionally across lots; cost unchanged."""
        old_total = self.quantity
        if old_total <= 0:
            return
        acc = ZERO
        for i, lot in enumerate(self.lots):
            if i == len(self.lots) - 1:
                lot.quantity = new_total - acc  # keep the total exact
            else:
                lot.quantity = lot.quantity * new_total / old_total
                acc += lot.quantity

    def reduce_cost(self, amount: Decimal, amount_twd: Decimal) -> tuple[Decimal, Decimal]:
        """Reduce cost basis by returned capital; return the excess (realized gain) if any."""
        cost, cost_twd = self.cost, self.cost_twd
        take = min(amount, cost)
        take_twd = min(amount_twd, cost_twd)
        for lot in self.lots:
            if cost > 0:
                lot.cost -= take * lot.cost / cost
            if cost_twd > 0:
                lot.cost_twd -= take_twd * lot.cost_twd / cost_twd
        return amount - take, amount_twd - take_twd

    def end_of_day(self) -> None:
        """Unsold day-trade buys become ordinary inventory at the end of the day."""
        day_lots = [lot for lot in self.lots if lot.day_trade]
        if not day_lots:
            return
        self.lots = [lot for lot in self.lots if not lot.day_trade]
        for lot in day_lots:
            lot.day_trade = False
            self.add(lot)


@dataclass(frozen=True)
class RealizedEvent:
    trade_date: date
    account_id: str
    symbol: str | None
    txn_id: str
    kind: str  # "trade" | "capital_return" | "adjustment"
    quantity: Decimal
    proceeds: Decimal  # trade currency, net of fee and tax
    cost: Decimal
    pnl: Decimal  # trade currency
    pnl_twd: Decimal
    currency: str


@dataclass(frozen=True)
class IncomeEvent:
    trade_date: date
    account_id: str
    symbol: str | None
    txn_id: str
    kind: str  # "dividend"
    gross: Decimal
    health_insurance: Decimal
    tax: Decimal
    fee: Decimal
    net: Decimal  # trade currency
    net_twd: Decimal
    currency: str


@dataclass
class DayFlows:
    """Portfolio flows of one day in TWD, as defined by the performance contract."""

    inflow: Decimal = ZERO  # I_t: buy cost incl. fee
    outflow: Decimal = ZERO  # O_t: sell net proceeds + net cash dividends + returned capital
    sell_proceeds: Decimal = ZERO  # part of outflow coming from sells / returned capital


@dataclass(frozen=True)
class TrailEntry:
    """One booking that touched a (account, symbol) position, in the order the ledger applied it.

    ``before`` / ``after`` are the share counts around the booking, so a round (0 → >0 → 0) can be read off the
    trail.
    """

    account_id: str
    symbol: str
    trade_date: date
    before: Decimal
    after: Decimal
    txn: LedgerTxn


@dataclass(frozen=True)
class EffectiveTxn:
    """What the ledger actually booked for a transaction (e.g. computed 配股 shares)."""

    txn_id: str
    quantity: Decimal
    cash: Decimal


class Ledger:
    """Incremental ledger. Feed transactions in chronological order via :meth:`apply_day`."""

    def __init__(self, method: CostMethod = CostMethod.AVERAGE, strict: bool = False):
        self.method = CostMethod(method)
        self.strict = strict
        self.positions: dict[tuple[str, str], Position] = {}
        self.realized: list[RealizedEvent] = []
        self.income: list[IncomeEvent] = []
        self.cash: dict[tuple[str, str], Decimal] = {}
        self.warnings: list[str] = []
        self.effective: dict[str, EffectiveTxn] = {}
        self.trail: list[TrailEntry] = []
        self._day_trading: set[tuple[str, str | None]] = set()

    # -- helpers -----------------------------------------------------------------------------
    def position(self, account_id: str, symbol: str, currency: str) -> Position:
        key = (account_id, symbol)
        pos = self.positions.get(key)
        if pos is None:
            pos = Position(account_id, symbol, currency, self.method)
            self.positions[key] = pos
        return pos

    def held(self, account_id: str, symbol: str) -> Decimal:
        pos = self.positions.get((account_id, symbol))
        return pos.quantity if pos else ZERO

    def open_positions(self) -> list[Position]:
        return [p for p in self.positions.values() if p.quantity > 0]

    def _cash(self, account_id: str, currency: str, delta: Decimal) -> None:
        key = (account_id, currency)
        self.cash[key] = self.cash.get(key, ZERO) + delta

    def _problem(self, message: str) -> None:
        if self.strict:
            raise LedgerError(message)
        self.warnings.append(message)

    def _close_out(self, pos: Position, t: LedgerTxn, held: Decimal) -> None:
        """A capital reduction or reverse split that leaves no shares: the cost still on the books is a realized
        loss, and the empty lots go (a later buy used to be merged into them; 2026-11-14 review)."""
        if held <= 0 or pos.quantity > 0:
            return
        cost, cost_twd = pos.cost, pos.cost_twd
        pos.lots = []
        if cost:
            self.realized.append(RealizedEvent(
                t.trade_date, t.account_id, t.symbol, t.id, "trade", ZERO, ZERO, cost, -cost, -cost_twd, t.currency,
            ))

    # -- application -------------------------------------------------------------------------
    def apply_day(self, txns: Iterable[LedgerTxn]) -> DayFlows:
        """Apply all transactions of a single date (any order; sorted here)."""
        flows = DayFlows()
        touched: set[tuple[str, str]] = set()
        ordered = sorted(txns, key=LedgerTxn.sort_key)
        # Buys on a day the same account sells that symbol as a day trade are kept apart (day-trade lots) so the
        # day-trade sell pairs with them; whatever is left joins the inventory at the end of the day.
        self._day_trading = {(t.account_id, t.symbol) for t in ordered if t.type is TxnType.SELL and t.is_day_trade}
        for t in ordered:
            before = self.held(t.account_id, t.symbol) if t.symbol else ZERO
            self._apply(t, flows)
            if t.symbol:
                touched.add((t.account_id, t.symbol))
                self.trail.append(TrailEntry(t.account_id, t.symbol, t.trade_date, before,
                                             self.held(t.account_id, t.symbol), t))
        for key in touched:
            pos = self.positions.get(key)
            if pos:
                pos.end_of_day()
        return flows

    def _apply(self, t: LedgerTxn, flows: DayFlows) -> None:
        fx = t.fx_rate
        match t.type:
            case TxnType.BUY:
                if not t.symbol:
                    raise LedgerError(f"交易 {t.id} 缺少商品代號")
                gross = t.quantity * t.price
                cost = gross + t.fee
                pos = self.position(t.account_id, t.symbol, t.currency)
                day_trade = t.is_day_trade or (t.account_id, t.symbol) in self._day_trading
                pos.add(Lot(t.quantity, cost, cost * fx, t.trade_date, day_trade=day_trade))
                self._cash(t.account_id, t.currency, -cost)
                flows.inflow += cost * fx
                self.effective[t.id] = EffectiveTxn(t.id, t.quantity, -cost)
            case TxnType.SELL:
                if not t.symbol:
                    raise LedgerError(f"交易 {t.id} 缺少商品代號")
                pos = self.position(t.account_id, t.symbol, t.currency)
                qty = t.quantity
                if qty > pos.quantity:
                    self._problem(
                        f"{t.trade_date.isoformat()} 賣出 {t.symbol} {qty} 股，超過當時持有的 {pos.quantity} 股"
                    )
                    qty = pos.quantity
                gross = t.quantity * t.price
                proceeds = gross - t.fee - t.tax
                cost, cost_twd = pos.remove(qty, t.trade_date, t.is_day_trade)
                # Non-strict mode clamps an oversell: book only the covered part of the proceeds.
                proceeds_booked = proceeds * qty / t.quantity if qty < t.quantity else proceeds
                pnl = proceeds_booked - cost
                self.realized.append(RealizedEvent(
                    t.trade_date, t.account_id, t.symbol, t.id, "trade", qty, proceeds_booked, cost, pnl,
                    proceeds_booked * fx - cost_twd, t.currency,
                ))
                self._cash(t.account_id, t.currency, proceeds)
                flows.outflow += proceeds * fx
                flows.sell_proceeds += proceeds * fx
                self.effective[t.id] = EffectiveTxn(t.id, qty, proceeds)
            case TxnType.CASH_DIVIDEND:
                net = t.amount - t.health_insurance - t.tax - t.fee
                self.income.append(IncomeEvent(
                    t.trade_date, t.account_id, t.symbol, t.id, "dividend", t.amount, t.health_insurance,
                    t.tax, t.fee, net, net * fx, t.currency,
                ))
                self._cash(t.account_id, t.currency, net)
                flows.outflow += net * fx
                self.effective[t.id] = EffectiveTxn(t.id, t.quantity, net)
            case TxnType.STOCK_DIVIDEND:
                if not t.symbol:
                    raise LedgerError(f"交易 {t.id} 缺少商品代號")
                pos = self.position(t.account_id, t.symbol, t.currency)
                held = pos.quantity
                if t.quantity > 0:
                    new_shares, cash = t.quantity, t.amount
                else:
                    new_shares, cash = stock_dividend_shares(held, t.price)
                    if t.amount > 0:
                        cash = t.amount
                if held <= 0 and new_shares > 0:
                    self._problem(f"{t.trade_date.isoformat()} {t.symbol} 配股時沒有持股")
                    # Book the shares at zero cost so the position still matches the broker.
                    pos.add(Lot(new_shares, ZERO, ZERO, t.trade_date))
                elif new_shares > 0:
                    pos.rescale(held + new_shares)
                if cash > 0:
                    # Fractional shares paid in cash at par count as dividend income.
                    self.income.append(IncomeEvent(
                        t.trade_date, t.account_id, t.symbol, t.id, "dividend", cash, ZERO, ZERO, ZERO, cash,
                        cash * fx, t.currency,
                    ))
                    self._cash(t.account_id, t.currency, cash)
                    flows.outflow += cash * fx
                self.effective[t.id] = EffectiveTxn(t.id, new_shares, cash)
            case TxnType.SPLIT:
                if not t.symbol:
                    raise LedgerError(f"交易 {t.id} 缺少商品代號")
                if t.quantity <= 0:
                    raise LedgerError(f"交易 {t.id} 分割比例必須大於 0")
                pos = self.position(t.account_id, t.symbol, t.currency)
                held = pos.quantity
                # Taiwan issues no fractional shares; US brokers keep them (2.5 AAPL × 3 = 7.5)
                new_total = held * t.quantity if t.currency == "USD" else truncate(held * t.quantity)
                pos.rescale(new_total)
                self._close_out(pos, t, held)
                self.effective[t.id] = EffectiveTxn(t.id, new_total - held, ZERO)
            case TxnType.CAPITAL_REDUCTION:
                if not t.symbol:
                    raise LedgerError(f"交易 {t.id} 缺少商品代號")
                if not (ZERO <= t.quantity < ONE):
                    raise LedgerError(f"交易 {t.id} 減資比例必須介於 0 與 1 之間")
                pos = self.position(t.account_id, t.symbol, t.currency)
                held = pos.quantity
                new_total = truncate(held * (ONE - t.quantity))
                # The refund per share applies to the shares held at replay time (an earlier buy entered later
                # changes it); the stored amount is only used when no per-share refund was given.
                if t.price > 0:
                    cash = truncate(held * t.price) if t.currency == "TWD" else truncate(held * t.price, 2)
                else:
                    cash = t.amount
                pos.rescale(new_total)
                if cash > 0:
                    excess, excess_twd = pos.reduce_cost(cash, cash * fx)
                    if excess > 0:
                        self.realized.append(RealizedEvent(
                            t.trade_date, t.account_id, t.symbol, t.id, "capital_return", ZERO, excess, ZERO,
                            excess, excess_twd, t.currency,
                        ))
                    self._cash(t.account_id, t.currency, cash)
                    flows.outflow += cash * fx
                    flows.sell_proceeds += cash * fx
                self._close_out(pos, t, held)
                self.effective[t.id] = EffectiveTxn(t.id, new_total - held, cash)
            case TxnType.DEPOSIT:
                self._cash(t.account_id, t.currency, t.amount)
            case TxnType.WITHDRAWAL:
                self._cash(t.account_id, t.currency, -t.amount)
            case TxnType.INTEREST:
                net = t.amount - t.tax - t.fee
                self._cash(t.account_id, t.currency, net)
                self.realized.append(RealizedEvent(
                    t.trade_date, t.account_id, t.symbol, t.id, "adjustment", ZERO, net, ZERO, net, net * fx,
                    t.currency,
                ))
            case TxnType.FEE | TxnType.TAX:
                cost = t.amount if t.amount else (t.fee if t.type is TxnType.FEE else t.tax)
                self._cash(t.account_id, t.currency, -cost)
                self.realized.append(RealizedEvent(
                    t.trade_date, t.account_id, t.symbol, t.id, "adjustment", ZERO, -cost, ZERO, -cost,
                    -cost * fx, t.currency,
                ))


@dataclass
class LedgerResult:
    ledger: Ledger
    flows_by_date: dict[date, DayFlows]


def replay(
    txns: Iterable[LedgerTxn],
    method: CostMethod = CostMethod.AVERAGE,
    strict: bool = False,
) -> LedgerResult:
    """Replay all transactions in date order."""
    ledger = Ledger(method, strict=strict)
    by_date: dict[date, list[LedgerTxn]] = {}
    for t in txns:
        by_date.setdefault(t.trade_date, []).append(t)
    flows = {d: ledger.apply_day(by_date[d]) for d in sorted(by_date)}
    return LedgerResult(ledger, flows)
