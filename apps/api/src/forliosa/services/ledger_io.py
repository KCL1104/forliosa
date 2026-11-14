"""Load a user's ledger from the database and convert it to domain objects."""

from __future__ import annotations

import bisect
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.domain.fees import FeeSchedule, InstrumentRef
from forliosa.domain.ledger import CostMethod, LedgerTxn, TxnType, replay
from forliosa.marketdata.base import InstrumentInfo, market_of_symbol
from forliosa.marketdata.service import MarketData
from forliosa.models import BrokerAccount, Transaction, User
from forliosa.services.scope import account_filter
from forliosa.timeutil import today_taipei

DEFAULT_PREFERENCES = {
    "color_convention": "tw",
    "theme": "system",
    "quantity_unit": "lot",
    "privacy_mode": False,
    "cost_method": "average",
    "benchmark": "0050.TW",
    "daily_briefing": False,  # 每日收盤簡報 (forliosa.ai.briefing): the worker writes one only for users who set it
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


FX_FALLBACK = Decimal("31.5")


class FxBook:
    """TWD per unit of currency on a date (last known rate on or before the date; before the series begins, its
    first rate).

    Source: 中央銀行〈銀行間新臺幣對美元收盤匯率〉 from the archive (``fx_rates`` source ``cbc-opendata``, daily since
    2008-01-02, OGDL), any policy. Only when the archive has none: FinMind under a personal opt-in, demo data under
    personal; otherwise the documented fixed fallback 31.5 (``fixed``). TAIFEX 每日外幣參考匯率 is archived but
    never used here.
    """

    def __init__(self, series: dict[date, Decimal] | None = None, is_demo: bool = False, source: str = ""):
        items = sorted((series or {}).items())
        self._dates = [d for d, _ in items]
        self._rates = [r for _, r in items]
        self.is_demo = is_demo
        self.source = source
        self.used_usd = False

    @classmethod
    def load(cls, md: MarketData, start: date, end: date | None = None) -> FxBook:
        series, is_demo, source = md.fx_series_with_source("USDTWD", start - timedelta(days=14),
                                                           end or today_taipei())
        return cls(series, is_demo, source)

    @property
    def fixed(self) -> bool:
        """True when no FX series is available and the fixed 31.5 is used."""
        return not self._dates

    def rate(self, currency: str, d: date) -> Decimal:
        if currency == "TWD":
            return Decimal(1)
        self.used_usd = True
        if not self._dates:
            return FX_FALLBACK  # documented fallback when no FX source is available
        i = bisect.bisect_right(self._dates, d) - 1
        return self._rates[max(i, 0)]

    def latest(self, currency: str) -> Decimal:
        if currency == "TWD":
            return Decimal(1)
        self.used_usd = True
        return self._rates[-1] if self._rates else FX_FALLBACK

    def latest_point(self) -> tuple[date, Decimal] | None:
        """The newest (date, rate) of the series; None when the fixed 31.5 is used."""
        return (self._dates[-1], self._rates[-1]) if self._dates else None


@dataclass
class LedgerInput:
    accounts: list[BrokerAccount]
    transactions: list[Transaction]
    method: CostMethod

    @property
    def first_date(self) -> date | None:
        return min((t.trade_date for t in self.transactions), default=None)

    def ledger_txns(self, fx: FxBook | None = None) -> list[LedgerTxn]:
        txns = sorted(self.transactions, key=lambda t: (t.created_at, t.id))
        return [to_ledger_txn(t, fx, seq) for seq, t in enumerate(txns)]


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
    """``user``'s ledger (one account with ``account_id``). Under read-only viewing the request's view scope limits
    it to the delegated accounts (``services.scope``): an account outside the scope is as if it did not exist."""
    allowed = account_filter(db, user.id)
    if accounts is None:
        q = select(BrokerAccount).where(BrokerAccount.user_id == user.id)
        if account_id:
            q = q.where(BrokerAccount.id == account_id)
        if allowed is not None:
            q = q.where(BrokerAccount.id.in_(sorted(allowed)))
        accounts = list(db.scalars(q.order_by(BrokerAccount.created_at)))
    accounts = [a for a in accounts if allowed is None or a.id in allowed]
    ids = [a.id for a in accounts]
    if not ids:
        return LedgerInput([], [], CostMethod(preferences_of(user)["cost_method"]))
    txns = list(db.scalars(
        select(Transaction).where(Transaction.user_id == user.id, Transaction.account_id.in_(ids))
    ))
    return LedgerInput(accounts, txns, CostMethod(preferences_of(user)["cost_method"]))


def shares_held(inp: LedgerInput, account_id: str, symbol: str, before: date,
                exclude_txn_id: str | None = None) -> Decimal:
    """Shares of ``symbol`` held in ``account_id`` at the close before ``before``."""
    txns = [t for t in inp.ledger_txns() if t.trade_date < before and t.id != exclude_txn_id]
    return replay(txns, inp.method).ledger.held(account_id, symbol)
