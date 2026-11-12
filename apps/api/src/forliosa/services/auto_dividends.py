"""Automatic dividend booking: Taiwan cash and stock dividends become transactions without user input.

Rules (product owner, 2026-11-12; ``docs/handoff.md`` §3.0, ``docs/api-contract.md`` 股利自動入帳):

* Listed and OTC Taiwan securities only — the ex-dividend notices TWT48U_ALL / tpex_exright_prepost through
  ``MarketData.dividends`` (never demo data). Notices whose amount is zero or not announced are not booked; US
  dividends have no commercially usable source yet and stay manual.
* Shares = the account's holding at the close before the ex-date (``shares_held(before=ex_date)``, automatic
  stock dividends of earlier ex-dates included). Holdings-only accounts: only ex-dates after the snapshot date.
* Booked on the ex-date, so the price drop and the dividend offset on the same day (no fake loss between the
  ex-date and the payment date); a known payment date goes into the note. Future ex-dates are not booked yet.
* Amounts through ``services.transactions.compute``: cash = shares × per share truncated to whole NT$, NHI premium
  with the capital-surplus exclusion; stock dividends via ``stock_dividend_shares`` (fractions paid at par).
* ``source = "auto"``. The user's own records win: a manual / imported / signed-draft dividend of the same kind in
  the same account and symbol, dated from the ex-date up to ``USER_RECORD_WINDOW_DAYS`` later, covers that
  ex-date (each record covers the latest such ex-date, preferring one with the record's per-share amount).
* The user edits an automatic row → it becomes ``auto_edited`` and the sync never touches it again; the user deletes
  one → a skip is kept. Both leave an ``AutoDividendSkip`` so that dividend is never booked again.

``sync_auto_dividends`` recomputes what should exist and adds / updates / deletes ``source="auto"`` rows (a
back-filled buy before an ex-date, a deleted sell, a corrected notice). Triggers: transaction create / update /
delete, holdings snapshot updates, a tracking-mode change, and the worker after each daily archive run.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.api.errors import ApiError, unprocessable
from forliosa.domain.fees import ZERO, stock_dividend_shares
from forliosa.domain.ledger import LedgerError, LedgerTxn, TxnType, replay
from forliosa.ids import new_id
from forliosa.marketdata.base import DividendEvent, market_of_symbol
from forliosa.marketdata.service import MarketData
from forliosa.models import AutoDividendSkip, BrokerAccount, Transaction, User
from forliosa.services.ledger_io import LedgerInput, load_ledger_input
from forliosa.timeutil import now_utc, today_taipei

log = logging.getLogger("forliosa.auto_dividends")

AUTO = "auto"
AUTO_EDITED = "auto_edited"
USER_SOURCES = frozenset({"manual", "import", "ai_draft"})
# A dividend is paid within weeks of its ex-date (annual dividends ≈ 1 month, some up to ~3 months); a user's own
# record dated this many days after an ex-date at most counts as that dividend.
USER_RECORD_WINDOW_DAYS = 120
KIND_TYPE = {"cash": TxnType.CASH_DIVIDEND, "stock": TxnType.STOCK_DIVIDEND}
TYPE_KIND = {t.value: k for k, t in KIND_TYPE.items()}
TW_MARKETS = frozenset({"TWSE", "TPEX"})
PER_SHARE_TOLERANCE = Decimal("0.001")
# Comparing a stored automatic row with the recomputed one.
COMPARED = ("type", "trade_date", "quantity", "price", "amount", "fee", "tax", "health_insurance", "currency",
            "is_day_trade", "note")


@dataclass(frozen=True)
class DividendKey:
    """One dividend of one holding: what an automatic row stands for and what a skip suppresses."""

    account_id: str
    symbol: str
    ex_date: date
    kind: str  # cash | stock


def key_of(t: Transaction) -> DividendKey | None:
    kind = TYPE_KIND.get(t.type)
    if kind is None or not t.symbol:
        return None
    return DividendKey(t.account_id, t.symbol, t.trade_date, kind)


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    accounts: set[str] = field(default_factory=set)  # accounts whose automatic rows changed

    @property
    def changed(self) -> bool:
        return bool(self.created or self.updated or self.deleted)

    def add(self, other: SyncResult) -> None:
        self.created += other.created
        self.updated += other.updated
        self.deleted += other.deleted
        self.accounts |= other.accounts


class AutoDividendConflict(Exception):
    """Re-syncing the automatic dividends would make a consistent ledger inconsistent."""


def is_tw(symbol: str | None) -> bool:
    return bool(symbol) and market_of_symbol(symbol or "") in TW_MARKETS


def ex_dividend_events(md: MarketData, symbol: str) -> list[DividendEvent]:
    """Real (never demo) dated dividend events of a Taiwan symbol with an announced amount, oldest first."""
    if not is_tw(symbol):
        return []
    try:
        answer = md.dividends(symbol)
    except Exception:  # market data is best effort: no automatic rows rather than a failed request
        log.warning("dividends for %s unavailable", symbol, exc_info=True)
        return []
    if answer.is_demo:
        return []
    events = [e for e in answer.value or [] if e.ex_dividend_date is not None
              and (e.cash_dividend > 0 or e.stock_dividend > 0)]
    return sorted(events, key=lambda e: e.ex_dividend_date or date.min)


def _per_share(e: DividendEvent, kind: str) -> Decimal:
    return e.cash_dividend if kind == "cash" else e.stock_dividend


def covered_by_user(rows: Iterable[Transaction], events: list[DividendEvent]) -> set[tuple[date, str]]:
    """(ex_date, kind) pairs the user's own dividend records stand for.

    A record dated ``d`` covers the latest ex-date ``e`` with ``e <= d <= e + USER_RECORD_WINDOW_DAYS`` among the
    events with an amount of that kind — preferring the ex-dates whose per-share amount equals the record's price
    — so quarterly payers (an April payment for the March ex-date, a July payment for the June one) stay apart.
    """
    out: set[tuple[date, str]] = set()
    for t in rows:
        kind = TYPE_KIND.get(t.type)
        if kind is None:
            continue
        window = timedelta(days=USER_RECORD_WINDOW_DAYS)
        candidates = [e for e in events if _per_share(e, kind) > 0 and e.ex_dividend_date is not None
                      and e.ex_dividend_date <= t.trade_date <= e.ex_dividend_date + window]
        if not candidates:
            continue
        if t.price:
            same = [e for e in candidates if abs(_per_share(e, kind) - t.price) <= PER_SHARE_TOLERANCE]
            candidates = same or candidates
        best = max(candidates, key=lambda e: e.ex_dividend_date or date.min)
        assert best.ex_dividend_date is not None
        out.add((best.ex_dividend_date, kind))
    return out


def _fmt_shares(q: Decimal) -> str:
    return f"{q:,.0f}" if q == q.to_integral_value() else f"{q.normalize():,f}"


def _fmt_per_share(p: Decimal) -> str:
    return f"{p.normalize():f}"


def cash_note(shares: Decimal, per_share: Decimal, payment_date: date | None) -> str:
    note = f"除息前一日持有 {_fmt_shares(shares)} 股 × 每股現金股利 {_fmt_per_share(per_share)} 元"
    if payment_date is not None:
        note += f"；發放日 {payment_date.isoformat()}"
    return note


def stock_note(shares: Decimal, per_share: Decimal, new_shares: Decimal, cash: Decimal,
               payment_date: date | None) -> str:
    note = (f"除權前一日持有 {_fmt_shares(shares)} 股 × 每股配股 {_fmt_per_share(per_share)} 元"
            f"（每股面額 10 元）= 配發 {_fmt_shares(new_shares)} 股")
    if cash > 0:
        note += f"，不足一股折付現金 {cash:,.0f} 元"
    if payment_date is not None:
        note += f"；發放日 {payment_date.isoformat()}"
    return note


@dataclass
class _Holding:
    """The ledger of one (account, symbol) without its automatic rows, replayed up to a date on demand."""

    inp: LedgerInput
    account_id: str
    symbol: str
    base: list[LedgerTxn]
    extra: list[LedgerTxn] = field(default_factory=list)  # automatic stock dividends decided so far

    def held_before(self, d: date) -> Decimal:
        txns = [t for t in (*self.base, *self.extra) if t.trade_date < d]
        openings = [o for o in self.inp.openings()
                    if o.account_id == self.account_id and o.symbol == self.symbol and o.as_of < d]
        if not txns and not openings:
            return ZERO
        return replay(txns, self.inp.method, openings).ledger.held(self.account_id, self.symbol)


def _desired_rows(db: Session, user: User, md: MarketData, account: BrokerAccount, symbol: str,
                  inp: LedgerInput, all_txns: list[LedgerTxn], auto_ids: set[str], skips: set[tuple[date, str]],
                  today: date) -> dict[DividendKey, dict[str, Any]]:
    """Column values of every automatic row (account, symbol) should have now."""
    from forliosa.services.transactions import compute

    events = ex_dividend_events(md, symbol)
    if not events:
        return {}
    info = md.instrument(symbol)
    if info is None:
        return {}
    own = [t for t in inp.transactions if t.account_id == account.id and t.symbol == symbol
           and t.source in USER_SOURCES and t.type in TYPE_KIND]
    covered = covered_by_user(own, events)
    as_of = inp.snapshot_as_of.get(account.id)
    holding = _Holding(inp, account.id, symbol,
                       [t for t in all_txns if t.account_id == account.id and t.symbol == symbol
                        and t.id not in auto_ids])
    out: dict[DividendKey, dict[str, Any]] = {}
    for n, e in enumerate(events):
        ex = e.ex_dividend_date
        assert ex is not None
        if ex > today or (as_of is not None and ex <= as_of):
            continue
        shares = holding.held_before(ex)
        if shares <= 0:
            continue
        for kind in ("cash", "stock"):
            per_share = _per_share(e, kind)
            if per_share <= 0 or (ex, kind) in skips or (ex, kind) in covered:
                continue
            key = DividendKey(account.id, symbol, ex, kind)
            if kind == "cash":
                data = {"account_id": account.id, "symbol": symbol, "type": TxnType.CASH_DIVIDEND.value,
                        "trade_date": ex, "quantity": shares, "price": per_share,
                        "note": cash_note(shares, per_share, e.payment_date), "source": AUTO}
                try:
                    values = compute(db, user, data, md).values
                except ApiError as exc:
                    log.warning("automatic cash dividend %s skipped: %s", key, exc.message)
                    continue
                if values["amount"] <= 0:
                    continue
            else:
                new_shares, cash = stock_dividend_shares(shares, per_share)
                if new_shares <= 0 and cash <= 0:
                    continue
                values = {"account_id": account.id, "symbol": symbol, "type": TxnType.STOCK_DIVIDEND.value,
                          "trade_date": ex, "quantity": new_shares, "price": per_share, "amount": cash,
                          "fee": ZERO, "tax": ZERO, "health_insurance": ZERO, "currency": info.currency,
                          "is_day_trade": False, "note": stock_note(shares, per_share, new_shares, cash,
                                                                    e.payment_date),
                          "source": AUTO}
                holding.extra.append(LedgerTxn(
                    id=f"auto-stock-{ex.isoformat()}", account_id=account.id, symbol=symbol,
                    type=TxnType.STOCK_DIVIDEND, trade_date=ex, quantity=new_shares, price=per_share,
                    amount=cash, currency=info.currency, seq=10**9 + n,
                ))
            out[key] = values
    return out


def _differs(row: Transaction, values: dict[str, Any]) -> bool:
    return any(getattr(row, k) != values[k] for k in COMPARED)


def sync_auto_dividends(db: Session, user: User, md: MarketData, account_ids: Iterable[str] | None = None,
                        symbols: Iterable[str | None] | None = None, today: date | None = None) -> SyncResult:
    """Add / update / delete the user's ``source="auto"`` dividend rows to match the rules (no commit).

    ``account_ids`` / ``symbols`` narrow the work to what a change can affect (``None`` = all); symbols outside
    Taiwan are ignored. The caller commits (or rolls back) the session.
    """
    today = today or today_taipei()
    q = select(BrokerAccount).where(BrokerAccount.user_id == user.id)
    if account_ids is not None:
        ids = list(dict.fromkeys(account_ids))
        if not ids:
            return SyncResult()
        q = q.where(BrokerAccount.id.in_(ids))
    accounts = list(db.scalars(q.order_by(BrokerAccount.created_at)))
    only = None if symbols is None else {s for s in symbols if is_tw(s)}
    result = SyncResult()
    if not accounts or only == set():
        return result
    inp = load_ledger_input(db, user, accounts=accounts)
    all_txns = inp.ledger_txns()
    skip_rows = db.scalars(select(AutoDividendSkip).where(AutoDividendSkip.user_id == user.id,
                                                          AutoDividendSkip.account_id.in_([a.id for a in accounts])))
    skips: dict[tuple[str, str], set[tuple[date, str]]] = defaultdict(set)
    for s in skip_rows:
        skips[(s.account_id, s.symbol)].add((s.ex_date, s.kind))
    existing: dict[tuple[str, str], dict[DividendKey, list[Transaction]]] = defaultdict(lambda: defaultdict(list))
    for t in inp.transactions:
        k = key_of(t) if t.source == AUTO else None
        if t.source == AUTO and k is None:  # an automatic row that is not a dividend: never valid
            db.delete(t)
            result.deleted += 1
            result.accounts.add(t.account_id)
            continue
        if k is not None:
            existing[(k.account_id, k.symbol)][k].append(t)
    for account in accounts:
        held_symbols = {t.symbol for t in inp.transactions if t.account_id == account.id and is_tw(t.symbol)}
        held_symbols |= {s.symbol for s in inp.snapshots if s.account_id == account.id and is_tw(s.symbol)}
        for symbol in sorted(s for s in held_symbols if s and (only is None or s in only)):
            auto_ids = {t.id for rows in existing[(account.id, symbol)].values() for t in rows}
            desired = _desired_rows(db, user, md, account, symbol, inp, all_txns, auto_ids,
                                    skips[(account.id, symbol)], today)
            current = existing[(account.id, symbol)]
            for key, values in desired.items():
                rows = current.pop(key, [])
                if rows:
                    row, extra = rows[0], rows[1:]
                    if _differs(row, values):
                        for k, v in values.items():
                            setattr(row, k, v)
                        row.updated_at = now_utc()
                        result.updated += 1
                        result.accounts.add(account.id)
                    for t in extra:
                        db.delete(t)
                        result.deleted += 1
                        result.accounts.add(account.id)
                else:
                    db.add(Transaction(id=new_id("txn"), user_id=user.id, created_at=now_utc(),
                                       updated_at=now_utc(), **values))
                    result.created += 1
                    result.accounts.add(account.id)
            for rows in current.values():
                for t in rows:
                    db.delete(t)
                    result.deleted += 1
                    result.accounts.add(account.id)
            current.clear()
    return result


def ledger_error(db: Session, user: User, account: BrokerAccount) -> str | None:
    """The strict replay's error for ``account``, or None when its books are consistent."""
    inp = load_ledger_input(db, user, accounts=[account])
    try:
        replay(inp.ledger_txns(), inp.method, inp.openings(), strict=True)
    except LedgerError as exc:
        return str(exc)
    return None


def sync_checked(db: Session, user: User, md: MarketData, account: BrokerAccount,
                 symbols: Iterable[str | None] | None = None, assume_consistent: bool = False,
                 today: date | None = None) -> SyncResult:
    """Sync one account; raise ``AutoDividendConflict`` when that turns consistent books inconsistent.

    ``assume_consistent``: the caller already validated the books (a transaction change passed
    ``validate_ledger``), so the "before" replay is skipped. Books that were already inconsistent are synced anyway.
    """
    before_ok = True if assume_consistent else ledger_error(db, user, account) is None
    result = sync_auto_dividends(db, user, md, account_ids=[account.id], symbols=symbols, today=today)
    if result.changed and before_ok:
        db.flush()
        err = ledger_error(db, user, account)
        if err is not None:
            raise AutoDividendConflict(err)
    return result


def after_user_change(db: Session, user: User, md: MarketData, scopes: Iterable[tuple[str, str | None]],
                      assume_consistent: bool = True) -> SyncResult:
    """Re-sync what a user change can affect: ``scopes`` = (account_id, symbol) pairs (symbol None = whole account).

    Raises a 422 ``ledger_inconsistent`` when the recomputed automatic dividends would make the books inconsistent
    (e.g. a back-filled sell before an ex-date shrinks an automatic stock dividend whose shares were sold later);
    nothing is committed then.
    """
    by_account: dict[str, set[str | None] | None] = {}
    for account_id, symbol in scopes:
        if symbol is None:
            by_account[account_id] = None
        elif account_id not in by_account or by_account[account_id] is not None:
            cur = by_account.get(account_id) or set()
            cur.add(symbol)
            by_account[account_id] = cur
    total = SyncResult()
    for account_id, syms in by_account.items():
        if syms is not None and not any(is_tw(s) for s in syms):
            continue
        account = db.get(BrokerAccount, account_id)
        if account is None or account.user_id != user.id:
            continue
        try:
            total.add(sync_checked(db, user, md, account, symbols=syms, assume_consistent=assume_consistent))
        except AutoDividendConflict as exc:
            raise unprocessable(f"自動入帳的股利依這筆變更重算後帳目不一致：{exc}",
                                code="ledger_inconsistent") from exc
    return total


def remember_skip(db: Session, user: User, key: DividendKey, reason: str) -> None:
    """Never book ``key`` automatically again (the user deleted or edited that automatic row)."""
    exists = db.scalar(select(AutoDividendSkip).where(
        AutoDividendSkip.account_id == key.account_id, AutoDividendSkip.symbol == key.symbol,
        AutoDividendSkip.ex_date == key.ex_date, AutoDividendSkip.kind == key.kind))
    if exists is None:
        db.add(AutoDividendSkip(id=new_id("ads"), user_id=user.id, account_id=key.account_id, symbol=key.symbol,
                                ex_date=key.ex_date, kind=key.kind, reason=reason, created_at=now_utc()))


def sync_all_users(session_fn: Callable[[], Session], md: MarketData, today: date | None = None) -> SyncResult:
    """Worker entry point: sync every account of every user, one commit per account.

    An account whose books the sync would make inconsistent is left as it was (logged).
    """
    total = SyncResult()
    with session_fn() as db:
        user_ids = list(db.scalars(select(User.id)))
    for uid in user_ids:
        with session_fn() as db:
            user = db.get(User, uid)
            if user is None:
                continue
            accounts = list(db.scalars(select(BrokerAccount).where(BrokerAccount.user_id == uid)))
            for account in accounts:
                try:
                    total.add(sync_checked(db, user, md, account, today=today))
                    db.commit()
                except AutoDividendConflict as exc:
                    db.rollback()
                    log.warning("automatic dividends of account %s left unchanged: %s", account.id, exc)
                except Exception:
                    db.rollback()
                    log.exception("automatic dividends of account %s failed", account.id)
    return total
