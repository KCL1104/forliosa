"""Create/update/preview transactions: fill in fees and taxes, validate against the ledger.

The statement import writes its rows as one batch (:func:`check_batch`, :func:`create_batch`, :func:`delete_batch`):
all rows or none, one strict replay, one automatic-dividend sync, one commit, and one undo for the whole batch.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.api.errors import ApiError, not_found, unprocessable
from forliosa.domain.fees import (
    ZERO,
    FeeBreakdown,
    dividend_cash_amount,
    fmt_money,
    preview_cash_dividend,
    round_half_up,
    stock_dividend_shares,
    truncate,
)
from forliosa.domain.ledger import SECURITY_TYPES, CostMethod, LedgerError, LedgerTxn, TxnType, replay
from forliosa.ids import new_id
from forliosa.marketdata.service import MarketData
from forliosa.models import BrokerAccount, Transaction, User
from forliosa.services import auto_dividends, sharing
from forliosa.services.ledger_io import LedgerInput, instrument_ref, load_ledger_input, shares_held
from forliosa.timeutil import now_utc, today_taipei

FIELDS = ("account_id", "symbol", "type", "trade_date", "quantity", "price", "amount", "fee", "tax",
          "health_insurance", "currency", "is_day_trade", "note", "source")


@dataclass
class Computed:
    values: dict[str, Any]
    preview: FeeBreakdown


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise unprocessable(message)


def _get_account(db: Session, user: User, account_id: str) -> BrokerAccount:
    acc = db.get(BrokerAccount, account_id)
    if acc is None or acc.user_id != user.id:
        raise ApiError(404, "not_found", "找不到帳戶")
    return acc


# A cash dividend is paid within weeks of its ex-date (TSMC ≈ 1 month); a payment is matched to the latest
# ex-date at most this many days earlier.
DIVIDEND_PAYMENT_WINDOW_DAYS = 120


def capital_surplus_part(md: MarketData, symbol: str, trade_date: date, amount: Decimal,
                         shares: Decimal | None, per_share: Decimal | None) -> Decimal:
    """NT$ of a cash-dividend payment distributed from 資本公積, per the official resolution (t187ap45_L).

    The payment is matched to the latest ex-dividend date on or before ``trade_date`` (within
    ``DIVIDEND_PAYMENT_WINDOW_DAYS``; with ``per_share`` given, only an ex-date with that cash per share).
    0 when nothing matches, the resolution has no capital-surplus part, or the data is unavailable.
    """
    try:
        events = md.dividends(symbol).value or []
    except Exception:  # market data is best effort here: the premium then covers the whole payment
        return ZERO
    tol = Decimal("0.001")
    dated = [e for e in events if e.ex_dividend_date is not None and e.cash_dividend > 0
             and e.ex_dividend_date <= trade_date <= e.ex_dividend_date + timedelta(days=DIVIDEND_PAYMENT_WINDOW_DAYS)
             and (not per_share or abs(e.cash_dividend - per_share) <= tol)]
    if not dated:
        return ZERO
    event = max(dated, key=lambda e: e.ex_dividend_date)
    if not event.cash_sources or event.cash_sources[2] <= 0:
        return ZERO
    surplus_per_share = event.cash_sources[2]
    part = (truncate(shares * surplus_per_share) if shares
            else round_half_up(amount * surplus_per_share / event.cash_dividend))
    return min(part, amount)


def compute(db: Session, user: User, data: dict[str, Any], md: MarketData,
            exclude_txn_id: str | None = None, capital_surplus: Decimal | None = None) -> Computed:
    """Normalize a transaction payload. Buys and sells take the fee and tax the user typed, else 0 — commissions and
    the securities transaction tax are not calculated (product owner 2026-11-14: the price the user enters is the
    cost, like Google Finance; whoever wants exact numbers types them in). Dividends still get the NHI premium and
    US withholding automatically (those are deducted before the money arrives).

    ``capital_surplus``: NT$ of a cash dividend paid from 資本公積 when the caller already knows it (the automatic
    dividend sync); otherwise it is looked up from the official resolution.
    """
    account = _get_account(db, user, data["account_id"])
    t = TxnType(data["type"])
    trade_date: date = data["trade_date"]
    symbol = data.get("symbol")
    info = None
    if t in SECURITY_TYPES:
        _require(bool(symbol), "這個交易類型需要商品代號")
        info = md.instrument(symbol)
        if info is None:
            raise unprocessable(f"找不到商品：{symbol}", code="unknown_symbol")
        symbol = info.symbol
        currency = info.currency
        if data.get("currency") and data["currency"] != currency:
            raise unprocessable(f"{symbol} 以 {currency} 計價，交易幣別必須是 {currency}")
    else:
        if symbol:
            resolved = md.resolve(symbol)
            symbol = resolved or symbol.upper()
        currency = data.get("currency") or account.currency
    ref = instrument_ref(info, symbol)

    qty: Decimal | None = data.get("quantity")
    px: Decimal | None = data.get("price")
    amount: Decimal | None = data.get("amount")
    fee: Decimal | None = data.get("fee")
    tax: Decimal | None = data.get("tax")
    nhi: Decimal | None = data.get("health_insurance")
    day_trade = bool(data.get("is_day_trade"))
    rules: list[str] = []

    def held() -> Decimal:
        inp = load_ledger_input(db, user, accounts=[account])
        return shares_held(inp, account.id, symbol, trade_date, exclude_txn_id)

    def held_for_dividend(kind: str, per_share: Decimal) -> Decimal:
        """Shares entitled to a dividend recorded from its per-share amount: the holding at the close before the
        ex-date this record belongs to (``auto_dividends.match_ex_event``) — not counting that ex-date's own
        automatic rows, which this record replaces — else before the record's date."""
        events = auto_dividends.ex_dividend_events(md, symbol) if symbol else None
        ev = auto_dividends.match_ex_event(events or [], trade_date, kind, per_share)
        before = ev.ex_dividend_date if ev is not None and ev.ex_dividend_date is not None else trade_date
        inp = load_ledger_input(db, user, accounts=[account])
        return shares_held(inp, account.id, symbol, before, exclude_txn_id)

    match t:
        case TxnType.BUY | TxnType.SELL:
            _require(qty is not None and qty > 0, "請輸入股數")
            _require(px is not None and px > 0, "請輸入成交價")
            assert qty is not None and px is not None
            if ref.is_tw:
                _require(qty == qty.to_integral_value(), "台股股數必須是整數（零股以股為單位）")
            # The ledger values buys and sells at quantity × price; a different stored amount made the preview and
            # the holdings disagree (2026-11-14 review)
            gross = qty * px
            amount = gross
            fee = fee if fee is not None else ZERO
            tax = tax if tax is not None else ZERO
            if fee > 0:
                rules.append(f"手續費：自己填的 {fmt_money(fee, currency)}")
            if t is TxnType.SELL and tax > 0:
                rules.append(f"交易稅：自己填的 {fmt_money(tax, currency)}")
            # buys: the ledger adds only the fee to the cost
            net = gross - fee - tax if t is TxnType.SELL else -(gross + fee)
            nhi = ZERO
            preview = FeeBreakdown(gross, fee, tax, ZERO, net, rules)
        case TxnType.CASH_DIVIDEND:
            if amount is None:
                _require(px is not None and px > 0, "請輸入每股現金股利或股利金額")
                assert px is not None
                shares = qty if qty else held_for_dividend("cash", px)
                _require(shares > 0, "除息日前沒有持股，請直接輸入股利金額")
                amount = dividend_cash_amount(shares, px, currency)
                qty = shares
                rules.append(f"股利 = {qty} 股 × {px} 元")
            fee = fee if fee is not None else ZERO
            surplus = ZERO
            if capital_surplus is not None:
                surplus = min(capital_surplus, amount)
            elif nhi is None and ref.is_tw and currency == "TWD" and symbol:
                surplus = capital_surplus_part(md, symbol, trade_date, amount, qty, px)
            auto = preview_cash_dividend(amount, currency, ref, fee, capital_surplus=surplus)
            nhi = nhi if nhi is not None else auto.health_insurance
            tax = tax if tax is not None else auto.tax
            rules += auto.rules
            preview = FeeBreakdown(amount, fee, tax, nhi, amount - nhi - tax - fee, rules)
        case TxnType.STOCK_DIVIDEND:
            if not qty:
                _require(px is not None and px > 0, "請輸入每股配股（元）或配發股數")
                assert px is not None
                shares = held_for_dividend("stock", px)
                _require(shares > 0, "除權日前沒有持股，請直接輸入配發股數")
                qty, cash = stock_dividend_shares(shares, px)
                amount = amount if amount is not None else cash
                rules.append(f"配股：{shares} 股 × {px} 元 ÷ 面額 10 元 = {qty} 股")
                if cash:
                    rules.append(f"不足一股以面額折付現金 {fmt_money(cash)}")
            else:
                rules.append(f"配股：使用者輸入 {qty} 股")
            amount = amount or ZERO
            fee, tax, nhi = fee or ZERO, tax or ZERO, nhi or ZERO
            preview = FeeBreakdown(amount, fee, tax, nhi, amount - fee - tax - nhi, rules)
        case TxnType.SPLIT:
            _require(qty is not None and qty > 0, "請輸入分割比例（每 1 股變成幾股）")
            rules.append(f"分割：每 1 股變成 {qty} 股，總成本不變")
            amount, fee, tax, nhi = ZERO, ZERO, ZERO, ZERO
            preview = FeeBreakdown(ZERO, ZERO, ZERO, ZERO, ZERO, rules)
        case TxnType.CAPITAL_REDUCTION:
            _require(qty is not None and ZERO <= qty < 1, "請輸入減資比例（每 1 股減少幾股，介於 0 與 1）")
            # With a per-share refund the amount follows the shares held (recomputed on every edit, as the ledger
            # does at replay); only a refund given as a total amount is kept as entered (2026-11-14 review)
            if px:
                shares = held()
                amount = truncate(shares * px) if currency == "TWD" else truncate(shares * px, 2)
                rules.append(f"退還股款 = {shares} 股 × {px} 元")
            elif amount is None:
                amount = ZERO
            rules.append(f"減資：每 1 股減少 {qty} 股；退還股款 {fmt_money(amount, currency)} 降低成本")
            fee, tax, nhi = fee or ZERO, tax or ZERO, nhi or ZERO
            preview = FeeBreakdown(amount, fee, tax, nhi, amount - fee - tax, rules)
        case _:
            if t is TxnType.FEE and amount is None:
                amount = fee
            if t is TxnType.TAX and amount is None:
                amount = tax
            _require(amount is not None and amount > 0, "請輸入金額")
            assert amount is not None
            # A standalone fee/tax lives in ``amount``; its own fee/tax field stays 0 (no double count).
            fee = ZERO if t is TxnType.FEE else (fee or ZERO)
            tax = ZERO if t is TxnType.TAX else (tax or ZERO)
            nhi = ZERO
            sign = {TxnType.DEPOSIT: 1, TxnType.INTEREST: 1, TxnType.WITHDRAWAL: -1, TxnType.FEE: -1,
                    TxnType.TAX: -1}[t]
            label = {TxnType.DEPOSIT: "現金存入", TxnType.WITHDRAWAL: "現金提出", TxnType.FEE: "手續費（單獨記錄）",
                     TxnType.TAX: "稅（單獨記錄）", TxnType.INTEREST: "利息"}[t]
            rules.append(label)
            net = sign * amount - (tax if t is TxnType.INTEREST else ZERO)
            preview = FeeBreakdown(amount, fee, tax, ZERO, net, rules)

    values = {
        "account_id": account.id, "symbol": symbol, "type": t.value, "trade_date": trade_date,
        "quantity": qty or ZERO, "price": px or ZERO, "amount": amount or ZERO, "fee": fee or ZERO,
        "tax": tax or ZERO, "health_insurance": nhi or ZERO, "currency": currency, "is_day_trade": day_trade,
        "note": data.get("note") or "", "source": data.get("source") or "manual",
    }
    return Computed(values, preview)


def validate_ledger(db: Session, user: User, account: BrokerAccount,
                    candidate: Transaction | Sequence[Transaction] | None,
                    remove_id: str | Collection[str] | None = None, md: MarketData | None = None,
                    skip: auto_dividends.DividendKey | None = None) -> None:
    """Replay the account strictly, once, with the candidate (or several: a batch) applied and ``remove_id`` (one id
    or several) taken out; reject inconsistent books.

    With ``md``, the books are checked as they will be after the automatic dividend sync: the touched symbols'
    automatic rows are recomputed in memory first (a sell before an ex-date removes that ex-date's automatic stock
    dividend instead of failing on it). The message says so when only the recomputed dividends break the books.
    ``skip``: an automatic dividend this change deletes or edits (it will be skipped from now on).
    """
    candidates = _as_list(candidate)
    removing = {remove_id} if isinstance(remove_id, str) else set(remove_id or ())
    inp = load_ledger_input(db, user, accounts=[account])
    removed = [t for t in inp.transactions if t.id in removing]
    replaced = removing | {c.id for c in candidates}
    inp.transactions = [t for t in inp.transactions if t.id not in replaced] + candidates
    before: LedgerError | None = None
    try:
        replay(inp.ledger_txns(), inp.method, strict=True)
    except LedgerError as exc:
        before = exc
    if md is None:
        if before is not None:
            raise unprocessable(str(before), code="ledger_inconsistent") from before
        return
    symbols = {t.symbol for t in (*candidates, *removed) if t.symbol}
    if skip is not None:
        symbols.add(skip.symbol)
    after = replace(inp, transactions=auto_dividends.with_recomputed(db, user, md, inp, account, symbols,
                                                                     extra_skips=[skip] if skip else ()))
    try:
        replay(after.ledger_txns(), after.method, strict=True)
    except LedgerError as exc:
        if before is None:
            raise auto_dividends.conflict_error(exc) from exc
        raise unprocessable(str(exc), code="ledger_inconsistent") from exc


def _as_list(candidate: Transaction | Sequence[Transaction] | None) -> list[Transaction]:
    if candidate is None:
        return []
    return [candidate] if isinstance(candidate, Transaction) else list(candidate)


def _dividend_scope(t: Transaction | dict[str, Any]) -> list[tuple[str, str | None]]:
    """(account, symbol) whose automatic dividends a change to this transaction can affect."""
    get = t.get if isinstance(t, dict) else (lambda k: getattr(t, k))
    symbol, kind = get("symbol"), get("type")
    if not symbol or TxnType(kind) not in SECURITY_TYPES:
        return []
    return [(get("account_id"), symbol)]


def create(db: Session, user: User, data: dict[str, Any], md: MarketData) -> Transaction:
    comp = compute(db, user, data, md)
    txn = Transaction(id=new_id("txn"), user_id=user.id, created_at=now_utc(), updated_at=now_utc(), **comp.values)
    account = _get_account(db, user, txn.account_id)
    auto_dividends.lock_accounts(db, [account.id])
    validate_ledger(db, user, account, txn, md=md)
    db.add(txn)
    auto_dividends.after_user_change(db, user, md, _dividend_scope(txn))
    db.commit()
    return txn


def update(db: Session, user: User, txn: Transaction, patch: dict[str, Any], md: MarketData) -> Transaction:
    data = {f: getattr(txn, f) for f in FIELDS}
    old_scope = _dividend_scope(txn)
    old_feed_keys = sharing.trade_keys([txn])
    # Editing an automatic dividend turns it into the user's own version: the sync never touches it again.
    edited_auto = auto_dividends.key_of(txn) if txn.source == auto_dividends.AUTO else None
    if txn.source == auto_dividends.AUTO:
        patch = {**patch, "source": auto_dividends.AUTO_EDITED}
    # An imported row stays imported: it never reaches group feeds, pushes or digests (``sharing.FEED_SOURCES``).
    if txn.source == IMPORT_SOURCE:
        patch = {k: v for k, v in patch.items() if k != "source"}
    # Auto-calculated fields are recalculated unless explicitly given, when inputs change.
    inputs_changed = any(k in patch for k in ("quantity", "price", "amount", "type", "trade_date", "symbol",
                                              "account_id", "is_day_trade"))
    if inputs_changed:
        for k in ("fee", "tax", "health_insurance"):
            if k not in patch:
                data[k] = None
        if "amount" not in patch and data["type"] in ("buy", "sell", "cash_dividend") and (
                "quantity" in patch or "price" in patch):
            data["amount"] = None
    data.update(patch)
    comp = compute(db, user, data, md, exclude_txn_id=txn.id)
    old_account = _get_account(db, user, txn.account_id)
    new_account = _get_account(db, user, comp.values["account_id"])
    auto_dividends.lock_accounts(db, [old_account.id, new_account.id])
    candidate = Transaction(id=txn.id, user_id=user.id, created_at=txn.created_at, **comp.values)
    validate_ledger(db, user, new_account, candidate, remove_id=txn.id, md=md, skip=edited_auto)
    if old_account.id != new_account.id:
        validate_ledger(db, user, old_account, None, remove_id=txn.id, md=md, skip=edited_auto)
    for k, v in comp.values.items():
        setattr(txn, k, v)
    txn.updated_at = now_utc()
    if edited_auto is not None:
        auto_dividends.remember_skip(db, user, edited_auto, "edited")
    auto_dividends.after_user_change(db, user, md, old_scope + _dividend_scope(txn))
    db.flush()
    sharing.purge_trade_threads(db, user.id, old_feed_keys)  # the old group feed item may have no trade left
    db.commit()
    return txn


def delete(db: Session, user: User, txn: Transaction, md: MarketData) -> None:
    """Delete a transaction. Deleting an automatic dividend keeps a skip so the sync never books it again."""
    account = _get_account(db, user, txn.account_id)
    auto_dividends.lock_accounts(db, [account.id])
    auto_key = auto_dividends.key_of(txn) if txn.source == auto_dividends.AUTO else None
    validate_ledger(db, user, account, None, remove_id=txn.id, md=md, skip=auto_key)
    scope = _dividend_scope(txn)
    feed_keys = sharing.trade_keys([txn])
    db.delete(txn)
    if auto_key is not None:
        auto_dividends.remember_skip(db, user, auto_key, "deleted")
    auto_dividends.after_user_change(db, user, md, scope)
    db.flush()
    sharing.purge_trade_threads(db, user.id, feed_keys)  # its group feed item (and comments) go with the last trade
    db.commit()


# -- batches: the statement import (產品負責人 2026-11-16) -------------------------------------------------------------
IMPORT_SOURCE = "import"
BATCH_MAX_ROWS = 200
BATCH_TYPES = (TxnType.BUY.value, TxnType.SELL.value)  # dividends are booked automatically; nothing else is imported
_BATCH_FIELDS = ("account_id", "symbol", "type", "trade_date", "quantity", "price", "amount", "fee", "tax",
                 "health_insurance", "currency", "is_day_trade", "note")
_BATCH_NUMBERS = ("quantity", "price", "amount", "fee", "tax", "health_insurance")
_EARLIEST_TRADE_DATE = date(1990, 1, 1)  # as ``api.schemas.TransactionIn`` checks it
_SIDE = {"buy": "買進", "sell": "賣出"}


@dataclass
class BatchCheck:
    """What :func:`check_batch` found.

    ``flags[i]`` belongs to the request's ``rows[i]``: ``{code, message, severity}`` dicts, severity ``error`` (the
    batch cannot be written with this row in it) or ``warning`` (shown; the row can still be imported).
    ``problems``: errors no row can be blamed for (the books were already inconsistent), same shape.
    ``candidates[i]``: ``rows[i]`` computed and not saved (None when the row has an error of its own); ``ordered``:
    the candidates in the order they are booked — by date, buys before sells, then the request's order.
    """

    account: BrokerAccount
    flags: list[list[dict[str, str]]]
    problems: list[dict[str, str]] = field(default_factory=list)
    candidates: list[Transaction | None] = field(default_factory=list)
    ordered: list[Transaction] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems and not any(f["severity"] == "error" for row in self.flags for f in row)

    def errors(self) -> list[dict[str, Any]]:
        """Every error as ``{index, code, message}``; ``index`` is None for a problem of the whole batch."""
        out: list[dict[str, Any]] = [{"index": i, "code": f["code"], "message": f["message"]}
                                     for i, row in enumerate(self.flags) for f in row if f["severity"] == "error"]
        return out + [{"index": None, "code": p["code"], "message": p["message"]} for p in self.problems]


@dataclass
class BatchResult:
    batch_id: str
    created: list[Transaction]  # in the order of the request's rows
    auto_dividends_added: int  # automatic dividend rows the import made the sync book (a back-filled buy)


def _flag(code: str, message: str, severity: str = "error") -> dict[str, str]:
    return {"code": code, "message": message, "severity": severity}


def _num(value: Decimal) -> str:
    """1,000 / 0.5 / 1,030.25: a quantity or price written the way people write it."""
    return f"{value.normalize():,f}"


def _day(d: date) -> str:
    """11/3 in the current year, 2025/11/3 otherwise."""
    return f"{d.month}/{d.day}" if d.year == today_taipei().year else f"{d.year}/{d.month}/{d.day}"


def _batch_row(raw: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str] | None]:
    """A row's transaction fields as ``compute`` takes them, or the row's error. Takes what
    ``TransactionBatchRow.model_dump()`` gives, and ISO dates or numbers as strings from other callers; other keys
    (an importer's ``row_id``, ``raw`` …) are ignored."""
    data = {k: raw.get(k) for k in _BATCH_FIELDS}
    if isinstance(data["trade_date"], str):
        try:
            data["trade_date"] = date.fromisoformat(data["trade_date"])
        except ValueError:
            return data, _flag("invalid_row", "日期看不懂。")
    if not isinstance(data["trade_date"], date):
        return data, _flag("invalid_row", "沒有日期。")
    for k in _BATCH_NUMBERS:
        v = data[k]
        if v is None or v == "":
            data[k] = None
            continue
        try:
            d = v if isinstance(v, Decimal) else Decimal(str(v))
        except (InvalidOperation, ValueError):
            return data, _flag("invalid_row", "數字看不懂。")
        if not d.is_finite() or isinstance(v, bool):
            return data, _flag("invalid_row", "數字看不懂。")
        if d < 0:
            return data, _flag("invalid_row", "數字不能是負的。")
        data[k] = d
    if isinstance(data["symbol"], str):
        data["symbol"] = data["symbol"].strip() or None
    data["is_day_trade"] = bool(data["is_day_trade"])
    data["note"] = str(data["note"] or "")
    return data, None


def _row_error(data: dict[str, Any], account: BrokerAccount, today: date) -> dict[str, str] | None:
    if data["type"] not in BATCH_TYPES:
        return _flag("unsupported_type", "匯入只收買進和賣出。")
    if data["account_id"] not in (None, account.id):
        return _flag("account_mismatch", "這一列的帳戶和這次匯入的帳戶不同。")
    if data["trade_date"] < _EARLIEST_TRADE_DATE:
        return _flag("bad_date", "日期太早（1990 年以前）。")
    if data["trade_date"] > today:
        return _flag("bad_date", "日期不能在未來。")
    return None


def _trade_key(t: Transaction) -> tuple[Any, ...]:
    return t.trade_date, t.symbol, t.type, Decimal(t.quantity).normalize()


def _flag_duplicates(existing: Sequence[Transaction], candidates: Sequence[Transaction | None],
                     flags: list[list[dict[str, str]]]) -> None:
    """``duplicate``: the same date, symbol, side, shares and price as a row already in the account, or as another row
    of the batch; ``possible_duplicate``: the same but for the price (e.g. a sell recorded at that day's close)."""
    same: set[tuple[Any, ...]] = set()
    same_shares: dict[tuple[Any, ...], Decimal] = {}
    for t in existing:
        if t.type in BATCH_TYPES and t.symbol and t.source != auto_dividends.AUTO:
            same.add((*_trade_key(t), Decimal(t.price).normalize()))
            same_shares.setdefault(_trade_key(t), Decimal(t.price))
    seen: set[tuple[Any, ...]] = set()
    for i, t in enumerate(candidates):
        if t is None:
            continue
        key = _trade_key(t)
        full = (*key, Decimal(t.price).normalize())
        if full in same:
            flags[i].append(_flag("duplicate", f"{_day(t.trade_date)} 已經記過一筆一樣的。", "warning"))
        elif full in seen:
            flags[i].append(_flag("duplicate", "這次匯入裡，同一天有另一筆一樣的。", "warning"))
        elif key in same_shares:
            message = f"{_day(t.trade_date)} 已經記過一筆同樣股數的{_SIDE[t.type]}，價格 {_num(same_shares[key])}。"
            flags[i].append(_flag("possible_duplicate", message, "warning"))
        seen.add(full)


@dataclass(frozen=True)
class _Refused:
    """A booking the strict replay refuses (it stops at the first one; a non-strict replay clamps it and goes on)."""

    txn: LedgerTxn | None  # None: the replay itself failed
    place: int  # its place in the replay
    held: Decimal  # shares held just before it
    message: str  # in the ledger's own words


def _refused(txns: list[Transaction], method: CostMethod) -> tuple[list[_Refused], dict[str, int]]:
    """Every booking of ``txns`` that a strict replay would refuse, and each transaction's place in the replay."""
    ltx = LedgerInput([], txns, method).ledger_txns()
    places = {t.id: n for n, t in enumerate(sorted(ltx, key=LedgerTxn.sort_key))}
    try:
        trail = replay(ltx, method).ledger.trail
    except LedgerError as exc:
        return [_Refused(None, -1, ZERO, str(exc))], places
    out = []
    for e in trail:  # the two conditions ``Ledger._problem`` is called on
        t = e.txn
        day = t.trade_date.isoformat()
        if t.type is TxnType.SELL and t.quantity > e.before:
            message = f"{day} 賣出 {t.symbol} {_num(t.quantity)} 股，超過當時持有的 {_num(e.before)} 股"
            out.append(_Refused(t, places[t.id], e.before, message))
        elif t.type is TxnType.STOCK_DIVIDEND and e.before <= 0 < t.quantity:
            out.append(_Refused(t, places[t.id], e.before, f"{day} {t.symbol} 配股時沒有持股"))
    return out, places


def _flag_ledger(db: Session, user: User, md: MarketData, account: BrokerAccount, inp: LedgerInput,
                 batch: list[Transaction], index_of: dict[str, int], flags: list[list[dict[str, str]]]
                 ) -> list[dict[str, str]]:
    """Flag what the books refuse with the batch in them, as they will be after the automatic dividend sync (what
    ``validate_ledger`` with ``md`` checks): a batch sell beyond the shares held then (``oversell``), or a later row
    of the account the batch breaks (``ledger_inconsistent`` on the batch's last sell of that stock before it).
    Returns the problems no batch row can be blamed for."""
    after = auto_dividends.with_recomputed(db, user, md, inp, account, {t.symbol for t in batch})
    refused, places = _refused(after, inp.method)
    if not refused:
        return []
    dividends_only = not _refused(inp.transactions, inp.method)[0]
    lead = "匯入以後，自動入帳的股利重算，帳目對不起來" if dividends_only else "匯入以後帳目對不起來"
    problems: list[dict[str, str]] = []
    for r in refused:
        t = r.txn
        if t is not None and t.id in index_of:
            message = f"賣出 {_num(t.quantity)} 股，超過當時持有的 {_num(r.held)} 股。"
            flags[index_of[t.id]].append(_flag("oversell", message))
            continue
        blame = None if t is None else max(
            (c for c in batch if c.type == TxnType.SELL.value and c.account_id == t.account_id
             and c.symbol == t.symbol and places[c.id] < r.place), key=lambda c: places[c.id], default=None)
        flag = _flag("ledger_inconsistent", f"{lead}：{r.message}。")
        if blame is None:
            problems.append(flag)
        elif flag not in flags[index_of[blame.id]]:
            flags[index_of[blame.id]].append(flag)
    return problems


def check_batch(db: Session, user: User, account_id: str, rows: Sequence[Mapping[str, Any]],
                md: MarketData) -> BatchCheck:
    """Check importing ``rows`` into ``account_id`` without writing anything (``POST /transactions/batch`` with
    ``dry_run``; the statement importer flags its candidate rows with it too).

    ``rows``: buys and sells shaped like ``TransactionIn`` without ``source`` (keys it does not use are ignored).
    Every row is computed like a single create and gets error flags for what would refuse it — its own fields
    (``invalid_row``, ``unsupported_type``, ``account_mismatch``, ``bad_date``, ``compute``'s ``unknown_symbol`` /
    ``validation_error``) and the books (``oversell``, ``ledger_inconsistent``: one replay of the account with every
    computable row booked by date, buys before sells, and the automatic dividends recomputed) — and warnings for
    rows that look recorded already (``duplicate``, ``possible_duplicate``). 404 when the account is not the user's.
    """
    account = _get_account(db, user, account_id)
    today = today_taipei()
    flags: list[list[dict[str, str]]] = [[] for _ in rows]
    candidates: list[Transaction | None] = [None] * len(rows)
    for i, raw in enumerate(rows):
        data, bad = _batch_row(raw)
        bad = bad or _row_error(data, account, today)
        if bad is None:
            try:
                comp = compute(db, user, {**data, "account_id": account.id, "source": IMPORT_SOURCE}, md)
            except ApiError as exc:
                bad = _flag(exc.code, exc.message)
            else:
                candidates[i] = Transaction(user_id=user.id, **comp.values)
        if bad is not None:
            flags[i].append(bad)
    # Booked by date, buys before sells, then in the request's order: the ledger books a day's buys and sells in the
    # order they were entered (``created_at``), so each row is entered a microsecond after the one before it.
    ordered = sorted((t for t in candidates if t is not None),
                     key=lambda t: (t.trade_date, t.type != TxnType.BUY.value))  # stable: then the request's order
    start = now_utc()
    for n, t in enumerate(ordered):
        t.id = new_id("txn")
        t.created_at = t.updated_at = start + timedelta(microseconds=n)
    check = BatchCheck(account, flags, candidates=candidates, ordered=ordered)
    if not ordered:
        return check
    inp = load_ledger_input(db, user, accounts=[account])
    _flag_duplicates(inp.transactions, candidates, flags)
    inp.transactions = [*inp.transactions, *ordered]
    check.problems = _flag_ledger(db, user, md, account, inp, ordered, {t.id: i for i, t in enumerate(candidates)
                                                                        if t is not None}, flags)
    return check


def batch_rejected(check: BatchCheck) -> ApiError:
    """422 ``batch_rejected`` with ``rows: [{index, code, message}]`` (index None: the whole batch)."""
    rows = check.errors()
    n = len({e["index"] for e in rows if e["index"] is not None})
    message = f"有 {n} 筆不能匯入，整批都沒有寫入。" if n else "帳目對不起來，整批都沒有寫入。"
    return ApiError(422, "batch_rejected", message, extra={"rows": rows})


def create_batch(db: Session, user: User, account_id: str, rows: Sequence[Mapping[str, Any]],
                 md: MarketData) -> BatchResult:
    """Write ``rows`` into ``account_id`` as one import: every row or none.

    The rows are checked as :func:`check_batch` does (any error → 422 ``batch_rejected`` with every row's errors),
    then the account is replayed strictly once with all of them (``validate_ledger`` with ``md``), they are added with
    ``source="import"`` and a new ``import_batch_id``, the automatic dividends are re-synced once for every stock they
    touch, and everything is committed at once.
    """
    if not rows:
        raise unprocessable("沒有要匯入的交易")
    if len(rows) > BATCH_MAX_ROWS:
        raise unprocessable(f"一次最多匯入 {BATCH_MAX_ROWS} 筆")
    account = _get_account(db, user, account_id)
    auto_dividends.lock_accounts(db, [account.id])
    check = check_batch(db, user, account.id, rows, md)
    if not check.ok:
        raise batch_rejected(check)
    batch_id = new_id("imp")
    for t in check.ordered:
        t.import_batch_id = batch_id
    validate_ledger(db, user, account, check.ordered, md=md)
    db.add_all(check.ordered)
    scopes = list(dict.fromkeys(s for t in check.ordered for s in _dividend_scope(t)))
    synced = auto_dividends.after_user_change(db, user, md, scopes)
    db.commit()
    return BatchResult(batch_id, [t for t in check.candidates if t is not None], synced.created)


def delete_batch(db: Session, user: User, batch_id: str, md: MarketData) -> int:
    """Undo an import: delete every row of the batch that is still there, after one replay of the account without
    them (an account each, should rows have been moved to another account since). 422 ``ledger_inconsistent`` when
    later rows depend on the batch (a sell recorded afterwards); 404 when no row of the batch is left. Returns how
    many rows were deleted."""
    in_batch = (Transaction.user_id == user.id, Transaction.import_batch_id == batch_id)
    account_ids = sorted(set(db.scalars(select(Transaction.account_id).where(*in_batch))))
    if not account_ids:
        raise not_found("找不到這次匯入")
    auto_dividends.lock_accounts(db, account_ids)
    rows = list(db.scalars(select(Transaction).where(*in_batch)))
    for account_id in account_ids:
        account = _get_account(db, user, account_id)
        try:
            validate_ledger(db, user, account, None, remove_id={t.id for t in rows if t.account_id == account_id},
                            md=md)
        except ApiError as exc:
            if exc.code != "ledger_inconsistent":
                raise
            raise unprocessable(f"之後的交易用到這次匯入的股數，不能整批復原：{exc.message}",
                                code="ledger_inconsistent") from exc
    scopes = list(dict.fromkeys(s for t in rows for s in _dividend_scope(t)))
    feed_keys = sharing.trade_keys(rows)
    for t in rows:
        db.delete(t)
    auto_dividends.after_user_change(db, user, md, scopes)
    db.flush()
    sharing.purge_trade_threads(db, user.id, feed_keys)
    db.commit()
    return len(rows)
