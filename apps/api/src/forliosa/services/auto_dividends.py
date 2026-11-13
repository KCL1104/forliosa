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
from forliosa.domain.fees import ZERO, stock_dividend_shares, truncate
from forliosa.domain.ledger import LedgerError, LedgerTxn, TxnType, replay
from forliosa.ids import new_id
from forliosa.marketdata.base import DividendEvent, market_of_symbol
from forliosa.marketdata.service import MarketData
from forliosa.models import AutoDividendSkip, BrokerAccount, Transaction, User
from forliosa.services.ledger_io import LedgerInput, load_ledger_input
from forliosa.timeutil import now_utc, today_taipei

# Ex-dividend events by symbol for one sync run (None = unknown: the archive could not be read).
EventCache = dict[str, "list[DividendEvent] | None"]

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


def _archive_provider(md: MarketData) -> Any | None:
    return next((p for p in md.providers if p.name == "archive"), None)


def ex_dividend_events(md: MarketData, symbol: str, cache: EventCache | None = None) -> list[DividendEvent] | None:
    """Archived ex-dividend notices of a Taiwan symbol (TWT48U_ALL / tpex_exright_prepost), oldest first.

    Read from the archive provider directly: it is the only source of past notices, never demo data, and bypasses
    the facade's provider cooldown — a cooldown must not read as "no dividends". Notices whose amount is not
    announced yet are included (``amount_pending``; they matter for matching the user's records) — callers that
    book only use events with an amount. ``None`` = unknown (no archive configured, or reading it failed): the
    caller then leaves existing automatic rows alone. ``[]`` = known: no notices.
    """
    if not is_tw(symbol):
        return []
    if cache is not None and symbol in cache:
        return cache[symbol]
    provider = _archive_provider(md)
    out: list[DividendEvent] | None
    if provider is None:
        out = None
    else:
        try:
            events = provider.dividends(symbol) or []
        except Exception:  # an unreadable archive is "unknown", never "no dividends"
            log.warning("archived dividends for %s unavailable", symbol, exc_info=True)
            events = None
        out = None if events is None else sorted(
            (e for e in events if e.ex_dividend_date is not None and not e.is_demo),
            key=lambda e: e.ex_dividend_date or date.min)
    if cache is not None:
        cache[symbol] = out
    return out


def _per_share(e: DividendEvent, kind: str) -> Decimal:
    return e.cash_dividend if kind == "cash" else e.stock_dividend


def _is_candidate(e: DividendEvent, kind: str) -> bool:
    """A notice a user's record of ``kind`` may stand for: one with an amount of that kind, or a cash notice whose
    amount is not announced yet (so a record of that dividend is not taken for the previous one)."""
    return e.ex_dividend_date is not None and (_per_share(e, kind) > 0 or (kind == "cash" and e.amount_pending))


def match_ex_event(events: Iterable[DividendEvent], d: date, kind: str,
                   per_share: Decimal | None = None) -> DividendEvent | None:
    """The ex-dividend event a dividend record of ``kind`` dated ``d`` belongs to.

    The latest ex-date ``e`` with ``e <= d <= e + USER_RECORD_WINDOW_DAYS`` — preferring ex-dates whose announced
    per-share amount equals ``per_share`` — so quarterly payers (an April payment for the March ex-date, a July
    payment for the June one) stay apart. None when no notice fits.
    """
    window = timedelta(days=USER_RECORD_WINDOW_DAYS)
    candidates = [e for e in events if _is_candidate(e, kind) and e.ex_dividend_date is not None
                  and e.ex_dividend_date <= d <= e.ex_dividend_date + window]
    if not candidates:
        return None
    if per_share:
        same = [e for e in candidates if _per_share(e, kind) > 0
                and abs(_per_share(e, kind) - per_share) <= PER_SHARE_TOLERANCE]
        candidates = same or candidates
    return max(candidates, key=lambda e: e.ex_dividend_date or date.min)


def covered_by_user(rows: Iterable[Transaction], events: list[DividendEvent]) -> set[tuple[date, str]]:
    """(ex_date, kind) pairs the user's own dividend records stand for (``match_ex_event`` per record)."""
    out: set[tuple[date, str]] = set()
    for t in rows:
        kind = TYPE_KIND.get(t.type)
        if kind is None:
            continue
        e = match_ex_event(events, t.trade_date, kind, t.price or None)
        if e is not None and e.ex_dividend_date is not None:
            out.add((e.ex_dividend_date, kind))
    return out


def _fmt_shares(q: Decimal) -> str:
    return f"{q:,.0f}" if q == q.to_integral_value() else f"{q.normalize():,f}"


def _fmt_per_share(p: Decimal) -> str:
    return f"{p.normalize():f}"


def _paid(payment_date: date) -> str:
    return f"，{payment_date.month:02d}/{payment_date.day:02d} 發放"


def cash_note(shares: Decimal, per_share: Decimal, payment_date: date | None) -> str:
    """「1,500 股 × 每股 5 元，10/09 發放」: the shares are the holding the day before the ex-date (the ledger's
    dividend rules say so once; the note does not repeat it)."""
    note = f"{_fmt_shares(shares)} 股 × 每股 {_fmt_per_share(per_share)} 元"
    if payment_date is not None:
        note += _paid(payment_date)
    return note


def stock_note(shares: Decimal, per_share: Decimal, new_shares: Decimal, cash: Decimal,
               payment_date: date | None) -> str:
    note = (f"{_fmt_shares(shares)} 股 × 每股配股 {_fmt_per_share(per_share)} 元"
            f"（面額 10 元），配發 {_fmt_shares(new_shares)} 股")
    if cash > 0:
        note += f"，不足一股折付現金 {cash:,.0f} 元"
    if payment_date is not None:
        note += _paid(payment_date)
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


@dataclass
class _Plan:
    """What the automatic rows of one (account, symbol) should be.

    ``desired``: rows that must exist with these values. ``keep``: existing rows to leave as they are because their
    values could not be computed this time. ``unknown``: no dividend data at all (archive unreadable, instrument
    unknown) — every existing row is left alone and nothing is added.
    """

    desired: dict[DividendKey, dict[str, Any]] = field(default_factory=dict)
    keep: set[DividendKey] = field(default_factory=set)
    unknown: bool = False


def _plan(db: Session, user: User, md: MarketData, account: BrokerAccount, symbol: str, inp: LedgerInput,
          all_txns: list[LedgerTxn], auto_ids: set[str], skips: set[tuple[date, str]], today: date,
          cache: EventCache | None) -> _Plan:
    """The automatic rows (account, symbol) should have now (see the module rules)."""
    from forliosa.services.transactions import compute

    events = ex_dividend_events(md, symbol, cache)
    if events is None:
        return _Plan(unknown=True)
    if not any(_per_share(e, "cash") > 0 or _per_share(e, "stock") > 0 for e in events):
        return _Plan()
    info = md.instrument(symbol)
    if info is None:
        return _Plan(unknown=True)
    own = [t for t in inp.transactions if t.account_id == account.id and t.symbol == symbol
           and t.source in USER_SOURCES and t.type in TYPE_KIND]
    covered = covered_by_user(own, events)
    as_of = inp.snapshot_as_of.get(account.id)
    holding = _Holding(inp, account.id, symbol,
                       [t for t in all_txns if t.account_id == account.id and t.symbol == symbol
                        and t.id not in auto_ids])
    plan = _Plan()
    for n, e in enumerate(events):
        ex = e.ex_dividend_date
        assert ex is not None
        if ex > today or (as_of is not None and ex <= as_of):
            continue
        if _per_share(e, "cash") <= 0 and _per_share(e, "stock") <= 0:
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
                surplus = (truncate(shares * e.cash_sources[2])
                           if e.cash_sources and e.cash_sources[2] > 0 else ZERO)
                data = {"account_id": account.id, "symbol": symbol, "type": TxnType.CASH_DIVIDEND.value,
                        "trade_date": ex, "quantity": shares, "price": per_share,
                        "note": cash_note(shares, per_share, e.payment_date), "source": AUTO}
                try:
                    values = compute(db, user, data, md, capital_surplus=surplus).values
                except ApiError as exc:
                    log.warning("automatic cash dividend %s not recomputed: %s", key, exc.message)
                    plan.keep.add(key)
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
            plan.desired[key] = values
    return plan


def _differs(row: Transaction, values: dict[str, Any]) -> bool:
    return any(getattr(row, k) != values[k] for k in COMPARED)


@dataclass
class _Scope:
    """Everything one sync / validation pass needs about a set of accounts."""

    inp: LedgerInput
    all_txns: list[LedgerTxn]
    skips: dict[tuple[str, str], set[tuple[date, str]]]
    existing: dict[tuple[str, str], dict[DividendKey, list[Transaction]]]
    stray: list[Transaction]  # automatic rows that are not dividends: never valid

    def symbols(self, account_id: str, only: set[str] | None) -> list[str]:
        syms = {t.symbol for t in self.inp.transactions if t.account_id == account_id and is_tw(t.symbol)}
        syms |= {s.symbol for s in self.inp.snapshots if s.account_id == account_id and is_tw(s.symbol)}
        return sorted(s for s in syms if s and (only is None or s in only))


def _scope(db: Session, user: User, inp: LedgerInput) -> _Scope:
    ids = [a.id for a in inp.accounts]
    skips: dict[tuple[str, str], set[tuple[date, str]]] = defaultdict(set)
    if ids:
        for s in db.scalars(select(AutoDividendSkip).where(AutoDividendSkip.user_id == user.id,
                                                           AutoDividendSkip.account_id.in_(ids))):
            skips[(s.account_id, s.symbol)].add((s.ex_date, s.kind))
    existing: dict[tuple[str, str], dict[DividendKey, list[Transaction]]] = defaultdict(lambda: defaultdict(list))
    stray = []
    for t in inp.transactions:
        if t.source != AUTO:
            continue
        k = key_of(t)
        if k is None:
            stray.append(t)
        else:
            existing[(k.account_id, k.symbol)][k].append(t)
    return _Scope(inp, inp.ledger_txns(), skips, existing, stray)


def lock_accounts(db: Session, account_ids: Iterable[str]) -> None:
    """Serialize writers of the same accounts (the worker's sync vs a user's change): row locks on PostgreSQL.
    SQLite already serializes writes and has no ``FOR UPDATE`` (SQLAlchemy omits it there)."""
    ids = sorted(set(account_ids))
    if ids and db.get_bind().dialect.name == "postgresql":
        db.execute(select(BrokerAccount.id).where(BrokerAccount.id.in_(ids)).with_for_update())


def sync_auto_dividends(db: Session, user: User, md: MarketData, account_ids: Iterable[str] | None = None,
                        symbols: Iterable[str | None] | None = None, today: date | None = None,
                        cache: EventCache | None = None) -> SyncResult:
    """Add / update / delete the user's ``source="auto"`` dividend rows to match the rules (no commit).

    ``account_ids`` / ``symbols`` narrow the work to what a change can affect (``None`` = all); symbols outside
    Taiwan are ignored. An existing row is only deleted when the dividend data is known and says it should not
    exist; when the data cannot be read the rows stay as they are. The caller commits (or rolls back).
    """
    today = today or today_taipei()
    cache = {} if cache is None else cache
    q = select(BrokerAccount).where(BrokerAccount.user_id == user.id)
    if account_ids is not None:
        ids = list(dict.fromkeys(account_ids))
        if not ids:
            return SyncResult()
        q = q.where(BrokerAccount.id.in_(ids))
    accounts = list(db.scalars(q.order_by(BrokerAccount.created_at)))
    only = None if symbols is None else {s for s in symbols if s and is_tw(s)}
    result = SyncResult()
    if not accounts or only == set():
        return result
    sc = _scope(db, user, load_ledger_input(db, user, accounts=accounts))
    for t in sc.stray:
        db.delete(t)
        result.deleted += 1
        result.accounts.add(t.account_id)
    for account in accounts:
        for symbol in sc.symbols(account.id, only):
            current = sc.existing[(account.id, symbol)]
            auto_ids = {t.id for rows in current.values() for t in rows}
            plan = _plan(db, user, md, account, symbol, sc.inp, sc.all_txns, auto_ids,
                         sc.skips[(account.id, symbol)], today, cache)
            if plan.unknown:
                continue
            for key, values in plan.desired.items():
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
            for key, rows in current.items():
                for t in (rows[1:] if key in plan.keep else rows):
                    db.delete(t)
                    result.deleted += 1
                    result.accounts.add(account.id)
            current.clear()
    return result


def with_recomputed(db: Session, user: User, md: MarketData, inp: LedgerInput, account: BrokerAccount,
                    symbols: Iterable[str | None], today: date | None = None,
                    extra_skips: Iterable[DividendKey] = ()) -> list[Transaction]:
    """``inp.transactions`` with the automatic rows of (account, symbols) replaced, in memory, by what the sync
    would write for this ledger — to validate a change against the books as they will be after the sync.
    ``extra_skips``: automatic dividends the change itself deletes or edits."""
    today = today or today_taipei()
    only = {s for s in symbols if s and is_tw(s)}
    if not only:
        return list(inp.transactions)
    sc = _scope(db, user, inp)
    for k in extra_skips:
        sc.skips[(k.account_id, k.symbol)].add((k.ex_date, k.kind))
    replaced: set[str] = set()
    added: list[Transaction] = []
    cache: EventCache = {}
    for symbol in sc.symbols(account.id, only):
        current = sc.existing[(account.id, symbol)]
        auto_ids = {t.id for rows in current.values() for t in rows}
        plan = _plan(db, user, md, account, symbol, sc.inp, sc.all_txns, auto_ids,
                     sc.skips[(account.id, symbol)], today, cache)
        if plan.unknown:
            continue
        for key, rows in current.items():
            for i, t in enumerate(rows):
                if not (key in plan.keep and i == 0):
                    replaced.add(t.id)
        for n, values in enumerate(plan.desired.values()):
            added.append(Transaction(id=f"auto-check-{symbol}-{n}", user_id=user.id, created_at=now_utc(),
                                     updated_at=now_utc(), **values))
    return [t for t in inp.transactions if t.id not in replaced] + added


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
                 today: date | None = None, cache: EventCache | None = None) -> SyncResult:
    """Sync one account; raise ``AutoDividendConflict`` when that turns consistent books inconsistent.

    ``assume_consistent``: the caller already validated the books as they will be after the sync
    (``services.transactions.validate_ledger``), so the "before" replay is skipped. Books that were already
    inconsistent are synced anyway.
    """
    before_ok = True if assume_consistent else ledger_error(db, user, account) is None
    result = sync_auto_dividends(db, user, md, account_ids=[account.id], symbols=symbols, today=today, cache=cache)
    if result.changed and before_ok:
        db.flush()
        err = ledger_error(db, user, account)
        if err is not None:
            raise AutoDividendConflict(err)
    return result


def conflict_error(err: object) -> ApiError:
    return unprocessable(f"自動入帳的股利依這筆變更重算後帳目不一致：{err}", code="ledger_inconsistent")


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
    cache: EventCache = {}
    for account_id, syms in by_account.items():
        if syms is not None and not any(is_tw(s) for s in syms):
            continue
        account = db.get(BrokerAccount, account_id)
        if account is None or account.user_id != user.id:
            continue
        try:
            total.add(sync_checked(db, user, md, account, symbols=syms, assume_consistent=assume_consistent,
                                   cache=cache))
        except AutoDividendConflict as exc:
            raise conflict_error(exc) from exc
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

    The archive's notices are read once per symbol for the whole run. An account whose books the sync would make
    inconsistent is left as it was (logged); so is every account when the archive cannot be read.
    """
    total = SyncResult()
    cache: EventCache = {}
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
                    lock_accounts(db, [account.id])
                    db.expire_all()  # nothing pending here: re-read rows a concurrent request may have changed
                    total.add(sync_checked(db, user, md, account, today=today, cache=cache))
                    db.commit()
                except AutoDividendConflict as exc:
                    db.rollback()
                    log.warning("automatic dividends of account %s left unchanged: %s", account.id, exc)
                except Exception:
                    db.rollback()
                    log.exception("automatic dividends of account %s failed", account.id)
    return total
