"""Load a user's ledger from the database and convert it to domain objects."""

from __future__ import annotations

import bisect
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.domain.fees import FeeSchedule, InstrumentRef
from forliosa.domain.ledger import CostMethod, LedgerTxn, OpeningPosition, TxnType, replay
from forliosa.marketdata.base import InstrumentInfo, market_of_symbol
from forliosa.marketdata.service import MarketData
from forliosa.models import BrokerAccount, HoldingSnapshot, Transaction, User
from forliosa.timeutil import today_taipei

DEFAULT_PREFERENCES = {
    "color_convention": "tw",
    "theme": "system",
    "quantity_unit": "lot",
    "privacy_mode": False,
    "cost_method": "average",
    "benchmark": "0050.TW",
}


def preferences_of(user: User) -> dict:
    return {**DEFAULT_PREFERENCES, **(user.preferences or {})}


def fee_schedule(account: BrokerAccount) -> FeeSchedule:
    return FeeSchedule(
        fee_rate=account.fee_rate, fee_discount=account.fee_discount, min_fee=account.min_fee,
        min_fee_odd_lot=account.min_fee_odd_lot,
    )


def instrument_ref(info: InstrumentInfo | None, symbol: str | None = None) -> InstrumentRef:
    if info is not None:
        return InstrumentRef(info.code, info.market, info.type)
    sym = symbol or ""
    return InstrumentRef(sym.split(".")[0], market_of_symbol(sym), None)


class FxBook:
    """TWD per unit of currency on a date (last known rate on or before the date)."""

    def __init__(self, series: dict[date, Decimal] | None = None, is_demo: bool = False):
        items = sorted((series or {}).items())
        self._dates = [d for d, _ in items]
        self._rates = [r for _, r in items]
        self.is_demo = is_demo
        self.used_usd = False

    @classmethod
    def load(cls, md: MarketData, start: date, end: date | None = None) -> FxBook:
        series, is_demo = md.fx_series("USDTWD", start - timedelta(days=14), end or today_taipei())
        return cls(series, is_demo)

    def rate(self, currency: str, d: date) -> Decimal:
        if currency == "TWD":
            return Decimal(1)
        self.used_usd = True
        if not self._dates:
            return Decimal("31.5")  # documented fallback when no FX source is configured
        i = bisect.bisect_right(self._dates, d) - 1
        return self._rates[max(i, 0)]

    def latest(self, currency: str) -> Decimal:
        if currency == "TWD":
            return Decimal(1)
        self.used_usd = True
        return self._rates[-1] if self._rates else Decimal("31.5")


@dataclass
class LedgerInput:
    accounts: list[BrokerAccount]
    transactions: list[Transaction]
    snapshots: list[HoldingSnapshot]
    method: CostMethod
    snapshot_as_of: dict[str, date] = field(default_factory=dict)

    @property
    def first_date(self) -> date | None:
        dates = [t.trade_date for t in self.effective_transactions()] + [s.as_of for s in self.snapshots]
        return min(dates) if dates else None

    def effective_transactions(self) -> list[Transaction]:
        """Holdings-mode accounts: only transactions after the snapshot date count."""
        out = []
        for t in self.transactions:
            as_of = self.snapshot_as_of.get(t.account_id)
            if as_of is not None and t.trade_date <= as_of:
                continue
            out.append(t)
        return out

    def ledger_txns(self, fx: FxBook | None = None) -> list[LedgerTxn]:
        txns = sorted(self.effective_transactions(), key=lambda t: (t.created_at, t.id))
        return [to_ledger_txn(t, fx, seq) for seq, t in enumerate(txns)]

    def openings(self, fx: FxBook | None = None) -> list[OpeningPosition]:
        cur = {a.id: a for a in self.accounts}
        out = []
        for s in self.snapshots:
            currency = "USD" if market_of_symbol(s.symbol) == "US" else "TWD"
            rate = fx.rate(currency, s.as_of) if fx else Decimal(1)
            if s.account_id in cur:
                out.append(OpeningPosition(s.account_id, s.symbol, s.as_of, s.quantity, s.avg_cost, currency, rate))
        return out


def to_ledger_txn(t: Transaction, fx: FxBook | None, seq: int = 0) -> LedgerTxn:
    return LedgerTxn(
        id=t.id, account_id=t.account_id, symbol=t.symbol, type=TxnType(t.type), trade_date=t.trade_date,
        quantity=t.quantity or Decimal(0), price=t.price or Decimal(0), amount=t.amount or Decimal(0),
        fee=t.fee or Decimal(0), tax=t.tax or Decimal(0), health_insurance=t.health_insurance or Decimal(0),
        currency=t.currency, is_day_trade=bool(t.is_day_trade),
        fx_rate=fx.rate(t.currency, t.trade_date) if fx else Decimal(1), seq=seq,
    )


def load_ledger_input(db: Session, user: User, account_id: str | None = None,
                      accounts: Iterable[BrokerAccount] | None = None) -> LedgerInput:
    if accounts is None:
        q = select(BrokerAccount).where(BrokerAccount.user_id == user.id)
        if account_id:
            q = q.where(BrokerAccount.id == account_id)
        accounts = list(db.scalars(q.order_by(BrokerAccount.created_at)))
    accounts = list(accounts)
    ids = [a.id for a in accounts]
    if not ids:
        return LedgerInput([], [], [], CostMethod(preferences_of(user)["cost_method"]))
    txns = list(db.scalars(
        select(Transaction).where(Transaction.user_id == user.id, Transaction.account_id.in_(ids))
    ))
    holdings_ids = [a.id for a in accounts if a.tracking_mode == "holdings"]
    snaps: list[HoldingSnapshot] = []
    if holdings_ids:
        snaps = list(db.scalars(
            select(HoldingSnapshot).where(HoldingSnapshot.user_id == user.id,
                                          HoldingSnapshot.account_id.in_(holdings_ids))
        ))
    as_of: dict[str, date] = {}
    for s in snaps:
        as_of[s.account_id] = max(as_of.get(s.account_id, s.as_of), s.as_of)
    return LedgerInput(accounts, txns, snaps, CostMethod(preferences_of(user)["cost_method"]), as_of)


def shares_held(inp: LedgerInput, account_id: str, symbol: str, before: date,
                exclude_txn_id: str | None = None) -> Decimal:
    """Shares of ``symbol`` held in ``account_id`` at the close before ``before``."""
    txns = [t for t in inp.ledger_txns() if t.trade_date < before and t.id != exclude_txn_id]
    openings = [o for o in inp.openings() if o.as_of < before]
    led = replay(txns, inp.method, openings).ledger
    return led.held(account_id, symbol)
