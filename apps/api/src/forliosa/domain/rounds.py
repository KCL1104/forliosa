"""Holding rounds: a position's life from 0 shares → more than 0 → back to 0 (per account and symbol).

A fully sold symbol leaves the holdings but its rounds remain as history (the owner's decision of
2026-11-12). Rounds are read off the ledger's trail, so every rule of the ledger (average cost or FIFO,
day trades, stock dividends, splits, capital reductions, holdings snapshots) applies unchanged.

Per round, in TWD at each transaction's FX rate:

* ``bought_qty`` — shares bought (and opening snapshot shares); ``sold_qty`` — shares sold. They can
  differ when stock dividends, splits or capital reductions changed the share count in between.
* ``buy_cost`` — buy price × shares + buy commission (snapshots: shares × average cost).
* ``realized`` — the ledger's realized P&L of the round's sells and capital returns (net of commission and
  transaction tax, minus the cost of the shares sold), plus standalone fee / tax rows on the symbol.
* ``dividends`` — net cash dividends (after the NHI premium / withholding) and cash in lieu of fractional
  shares. A dividend booked while the position is 0 (paid after the shares were sold) belongs to the
  latest round of that account and symbol.
* ``fees_and_taxes`` — buy and sell commissions, transaction tax, standalone fee / tax rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from forliosa.domain.fees import ZERO
from forliosa.domain.ledger import Ledger, TrailEntry, TxnType


@dataclass
class Round:
    account_id: str
    symbol: str
    currency: str
    opened_at: date
    closed_at: date | None = None
    bought_qty: Decimal = ZERO
    sold_qty: Decimal = ZERO
    buy_cost: Decimal = ZERO
    realized: Decimal = ZERO
    dividends: Decimal = ZERO
    fees_and_taxes: Decimal = ZERO
    txn_ids: list[str] = field(default_factory=list)

    @property
    def is_closed(self) -> bool:
        return self.closed_at is not None

    @property
    def holding_days(self) -> int | None:
        return (self.closed_at - self.opened_at).days if self.closed_at else None

    @property
    def realized_pct(self) -> Decimal | None:
        return self.realized / self.buy_cost if self.buy_cost else None


def holding_rounds(ledger: Ledger) -> list[Round]:
    """Every round in the ledger (closed ones and the open one, if any), in booking order."""
    realized: dict[str, Decimal] = {}
    for e in ledger.realized:
        realized[e.txn_id] = realized.get(e.txn_id, ZERO) + e.pnl_twd
    income: dict[str, Decimal] = {}
    for e in ledger.income:
        income[e.txn_id] = income.get(e.txn_id, ZERO) + e.net_twd

    out: list[Round] = []
    current: dict[tuple[str, str], Round] = {}
    latest: dict[tuple[str, str], Round] = {}
    for entry in ledger.trail:
        key = (entry.account_id, entry.symbol)
        rnd = current.get(key)
        if rnd is None and entry.after > 0:
            currency = entry.txn.currency if entry.txn else (entry.opening.currency if entry.opening else "TWD")
            rnd = Round(entry.account_id, entry.symbol, currency, entry.trade_date)
            current[key] = rnd
            latest[key] = rnd
            out.append(rnd)
        target = rnd or latest.get(key)  # flat: a dividend paid after selling goes to the last round
        if target is not None:
            _book(target, entry, realized, income)
        if rnd is not None and entry.after <= 0:
            rnd.closed_at = entry.trade_date
            del current[key]
    return out


def _book(rnd: Round, entry: TrailEntry, realized: dict[str, Decimal], income: dict[str, Decimal]) -> None:
    if entry.opening is not None:
        op = entry.opening
        rnd.bought_qty += op.quantity
        rnd.buy_cost += op.quantity * op.avg_cost * op.fx_rate
        return
    t = entry.txn
    if t is None:
        return
    fx = t.fx_rate
    rnd.txn_ids.append(t.id)
    match t.type:
        case TxnType.BUY:
            rnd.bought_qty += t.quantity
            rnd.buy_cost += (t.quantity * t.price + t.fee) * fx
            rnd.fees_and_taxes += t.fee * fx
        case TxnType.SELL:
            rnd.sold_qty += entry.before - entry.after
            rnd.fees_and_taxes += (t.fee + t.tax) * fx
        case TxnType.FEE | TxnType.TAX:
            amount = t.amount if t.amount else (t.fee if t.type is TxnType.FEE else t.tax)
            rnd.fees_and_taxes += amount * fx
    rnd.realized += realized.get(t.id, ZERO)
    rnd.dividends += income.get(t.id, ZERO)
