"""Create/update/preview transactions: fill in fees and taxes, validate against the ledger.

The statement import writes its rows as one batch (:func:`check_batch`, :func:`create_batch`, :func:`delete_batch`):
all rows or none, one strict replay, one automatic-dividend sync, one commit, and one undo for the whole batch. The
holdings import (匯入庫存) writes through :func:`write_batch` too, after deleting the records of the stocks it replaces
(:func:`delete_records`, the step 刪除這檔 and 清除所有持倉 share) in the same transaction.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa import realtime
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
from forliosa.models import AutoDividendSkip, BrokerAccount, RecurringPlan, Transaction, User
from forliosa.services import auto_dividends, recurring, sharing
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


@auto_dividends.shared_events
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


PICKED = "picked"
_BASIS_FIELDS = ("date_basis", "estimated_date", "imported_on")


def _picked_patch(txn: Transaction, patch: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """資產組成原型 (``docs/proposals/asset-composition.md`` 附錄 B): ``patch`` without ``date_basis``, and whether the
    user hinted ``picked``. A date-only change of a 匯入庫存 buy (``date_basis`` not null) keeps the row's fee and tax
    as they are (the other fields are untouched; a normal row's date change still re-derives them when not sent, as
    before). What the change does to the basis is :func:`_basis_after`'s, once the row is computed."""
    hint = patch.get("date_basis")
    patch = {k: v for k, v in patch.items() if k != "date_basis"}
    if txn.date_basis is None:
        return patch, False
    new_date = patch.get("trade_date", txn.trade_date)
    if set(patch) <= {"trade_date"} and new_date != txn.trade_date:
        patch = {"fee": txn.fee, "tax": txn.tax, "health_insurance": txn.health_insurance, **patch}
    return patch, hint == PICKED


def _basis_after(txn: Transaction, values: dict[str, Any], date_sent: bool, hinted: bool,
                 md: MarketData) -> dict[str, Any]:
    """資產組成原型: the basis columns a 匯入庫存 buy (``date_basis`` not null) gets from an edit computed as
    ``values``.

    * No longer a buy, or another stock: an ordinary row (the three columns cleared) — its estimate and import day
      were the old stock's buy's, and a sell must not be held to an import day.
    * Still that buy: a date later than ``imported_on`` is refused (422 ``after_import_day``); a changed date earlier
      than the share-count limit — the latest split, capital reduction or stock dividend on or before the import day
      (``services.buy_date.share_changes``) — too (422 ``before_share_change``: the broker's shares already include
      it, the ledger would book it again). Any change of the date, or ``date_basis: "picked"``, makes it ``picked``.
      Price and quantity edits leave the basis alone.
    A normal row: nothing."""
    if txn.date_basis is None:
        return {}
    if values["type"] != TxnType.BUY.value or values["symbol"] != txn.symbol:
        return dict.fromkeys(_BASIS_FIELDS)
    new_date: date = values["trade_date"]
    if date_sent and txn.imported_on is not None and new_date > txn.imported_on:
        raise unprocessable(f"買進日期不能晚於匯入那天（{txn.imported_on.strftime('%Y/%m/%d')}）",
                            code="after_import_day")
    if new_date != txn.trade_date and txn.symbol:
        from forliosa.services import buy_date

        limit = buy_date.share_changes(md, [txn.symbol], txn.imported_on or today_taipei()).get(txn.symbol)
        if limit is not None and new_date < limit.date:
            raise unprocessable(buy_date.before_change_message(limit), code=buy_date.BEFORE_SHARE_CHANGE)
    return {"date_basis": PICKED} if new_date != txn.trade_date or hinted else {}


@auto_dividends.shared_events
def update(db: Session, user: User, txn: Transaction, patch: dict[str, Any], md: MarketData) -> Transaction:
    patch, hinted = _picked_patch(txn, patch)
    date_sent = "trade_date" in patch
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
    basis = _basis_after(txn, comp.values, date_sent, hinted, md)
    old_account = _get_account(db, user, txn.account_id)
    new_account = _get_account(db, user, comp.values["account_id"])
    auto_dividends.lock_accounts(db, [old_account.id, new_account.id])
    candidate = Transaction(id=txn.id, user_id=user.id, created_at=txn.created_at, **comp.values)
    validate_ledger(db, user, new_account, candidate, remove_id=txn.id, md=md, skip=edited_auto)
    if old_account.id != new_account.id:
        validate_ledger(db, user, old_account, None, remove_id=txn.id, md=md, skip=edited_auto)
    for k, v in {**comp.values, **basis}.items():
        setattr(txn, k, v)
    txn.updated_at = now_utc()
    if edited_auto is not None:
        auto_dividends.remember_skip(db, user, edited_auto, "edited")
    auto_dividends.after_user_change(db, user, md, old_scope + _dividend_scope(txn))
    db.flush()
    sharing.purge_trade_threads(db, user.id, old_feed_keys)  # the old group feed item may have no trade left
    db.commit()
    return txn


@auto_dividends.shared_events
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
            flags[i].append(_flag("duplicate", f"{_day(t.trade_date)} 已記過一樣的", "warning"))
        elif full in seen:
            flags[i].append(_flag("duplicate", "這次匯入裡同一天有一樣的", "warning"))
        elif key in same_shares:
            message = f"{_day(t.trade_date)} 已記過同股數的{_SIDE[t.type]}・價格 {_num(same_shares[key])}"
            flags[i].append(_flag("possible_duplicate", message, "warning"))
        seen.add(full)


@dataclass(frozen=True)
class _Refused:
    """A booking the strict replay refuses (it stops at the first one; a non-strict replay clamps it and goes on)."""

    txn: LedgerTxn | None  # None: the replay itself failed
    place: int  # its place in the replay
    held: Decimal  # shares held just before it
    message: str  # in the ledger's own words


def _stock(md: MarketData | None, symbol: str | None) -> str:
    """鴻海 (the instrument's name), else the short code (2317, AAPL)."""
    info = md.instrument(symbol) if md is not None and symbol else None
    return info.name if info is not None else (symbol or "").removesuffix(".TWO").removesuffix(".TW")


def _refused(txns: list[Transaction], method: CostMethod, md: MarketData | None = None
             ) -> tuple[list[_Refused], dict[str, int]]:
    """Every booking of ``txns`` that a strict replay would refuse, and each transaction's place in the replay.
    Messages read like the batch's own: 「11/10 賣出鴻海 3,580 股，超過當時持有的 0 股」."""
    ltx = LedgerInput([], txns, method).ledger_txns()
    places = {t.id: n for n, t in enumerate(sorted(ltx, key=LedgerTxn.sort_key))}
    try:
        trail = replay(ltx, method).ledger.trail
    except LedgerError as exc:
        return [_Refused(None, -1, ZERO, str(exc))], places
    out = []
    for e in trail:  # the two conditions ``Ledger._problem`` is called on
        t = e.txn
        day = _day(t.trade_date)
        if t.type is TxnType.SELL and t.quantity > e.before:
            message = f"{day} 賣出{_stock(md, t.symbol)} {_num(t.quantity)} 股，超過當時持有的 {_num(e.before)} 股"
            out.append(_Refused(t, places[t.id], e.before, message))
        elif t.type is TxnType.STOCK_DIVIDEND and e.before <= 0 < t.quantity:
            out.append(_Refused(t, places[t.id], e.before, f"{day} {_stock(md, t.symbol)} 配股時沒有持股"))
    return out, places


def _flag_ledger(db: Session, user: User, md: MarketData, account: BrokerAccount, inp: LedgerInput,
                 batch: list[Transaction], index_of: dict[str, int], flags: list[list[dict[str, str]]]
                 ) -> list[dict[str, str]]:
    """Flag what the books refuse with the batch in them, as they will be after the automatic dividend sync (what
    ``validate_ledger`` with ``md`` checks): a batch sell beyond the shares held then (``oversell``), or a later row
    of the account the batch breaks (``ledger_inconsistent`` on the batch's last sell of that stock before it).
    Returns the problems no batch row can be blamed for."""
    after = auto_dividends.with_recomputed(db, user, md, inp, account, {t.symbol for t in batch})
    refused, places = _refused(after, inp.method, md)
    if not refused:
        return []
    dividends_only = not _refused(inp.transactions, inp.method)[0]
    lead = "匯入後股利重算・帳目對不起來" if dividends_only else "匯入後帳目對不起來"
    problems: list[dict[str, str]] = []
    for r in refused:
        t = r.txn
        if t is not None and t.id in index_of:
            message = f"賣出 {_num(t.quantity)} 股・當時只有 {_num(r.held)} 股"
            flags[index_of[t.id]].append(_flag("oversell", message))
            continue
        blame = None if t is None else max(
            (c for c in batch if c.type == TxnType.SELL.value and c.account_id == t.account_id
             and c.symbol == t.symbol and places[c.id] < r.place), key=lambda c: places[c.id], default=None)
        flag = _flag("ledger_inconsistent", f"{lead}・{r.message}")
        if blame is None:
            problems.append(flag)
        elif flag not in flags[index_of[blame.id]]:
            flags[index_of[blame.id]].append(flag)
    return problems


@auto_dividends.shared_events
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
    auto_dividends.prefetch_events(md, (t.symbol for t in ordered))  # one read for every stock of the batch
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


@auto_dividends.shared_events
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
    return write_batch(db, user, check, md)


def write_batch(db: Session, user: User, check: BatchCheck, md: MarketData,
                also_sync: Sequence[tuple[str, str | None]] = (),
                purge_feed_keys: Sequence[sharing.TradeKey] = ()) -> BatchResult:
    """Write a batch :func:`check_batch` passed (``check.ok``; the account locked by the caller): a new
    ``import_batch_id`` (``imp_…``), one strict replay with every row (``validate_ledger`` with ``md``), the rows
    added, the automatic dividends re-synced once for every stock they touch (and ``also_sync``: stocks whose records
    the caller deleted in this transaction), the group-feed threads of ``purge_feed_keys`` purged when no row backs
    them any more, and one commit."""
    batch_id = new_id("imp")
    for t in check.ordered:
        t.import_batch_id = batch_id
    validate_ledger(db, user, check.account, check.ordered, md=md)
    db.add_all(check.ordered)
    scopes = list(dict.fromkeys([*(s for t in check.ordered for s in _dividend_scope(t)), *also_sync]))
    synced = auto_dividends.after_user_change(db, user, md, scopes)
    if purge_feed_keys:
        db.flush()
        sharing.purge_trade_threads(db, user.id, purge_feed_keys)
    db.commit()
    return BatchResult(batch_id, [t for t in check.candidates if t is not None], synced.created)


def _first_refusal(db: Session, user: User, account: BrokerAccount, removing: Sequence[Transaction],
                   md: MarketData) -> str | None:
    """The first booking the account's books refuse without ``removing`` (as ``validate_ledger`` with ``md`` replays
    them), in the batch's words; None when there is none to name."""
    gone = {t.id for t in removing}
    inp = load_ledger_input(db, user, accounts=[account])
    inp.transactions = [t for t in inp.transactions if t.id not in gone]
    after = auto_dividends.with_recomputed(db, user, md, inp, account, {t.symbol for t in removing if t.symbol})
    refused = _refused(after, inp.method, md)[0]
    return refused[0].message if refused and refused[0].txn is not None else None


@auto_dividends.shared_events
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
        removing = [t for t in rows if t.account_id == account_id]
        try:
            validate_ledger(db, user, account, None, remove_id={t.id for t in removing}, md=md)
        except ApiError as exc:
            if exc.code != "ledger_inconsistent":
                raise
            detail = _first_refusal(db, user, account, removing, md) or exc.message
            raise unprocessable(f"之後的交易用到這次匯入的股數，不能整批復原：{detail.rstrip('。')}。",
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


# -- deleting records: one stock in one account, or whole accounts -----------------------------------------------
@dataclass
class DeletedRecords:
    count: int = 0  # rows deleted, every type (the automatic dividends included)
    symbols: int = 0  # distinct stocks among them
    feed_keys: list[sharing.TradeKey] = field(default_factory=list)  # for ``sharing.purge_trade_threads(_bulk)``


def delete_records(db: Session, user: User, account_ids: Collection[str],
                   symbol: str | None = None) -> DeletedRecords:
    """Delete the user's records in ``account_ids`` — all of them, or only ``symbol``'s (the stored symbol, e.g.
    ``2330.TW``: what ``GET /transactions?account_id=&symbol=`` lists): buys, sells, dividends (automatic ones
    included), splits, capital reductions and cash rows (with ``symbol``, only those tagged with the stock) — and the
    automatic-dividend skips of the same scope (they describe edits to those rows: recorded again later, the dividends
    are booked afresh). One bulk ``DELETE`` (pending group pushes go with the rows: ON DELETE CASCADE), flushed, **not
    committed**. With no record in the scope nothing is deleted, the skips included, and the counts are 0. Every
    statement filters on the user, so another user's account deletes nothing.

    The one low-level step of 刪除這檔 (:func:`delete_holding`), 清除所有持倉 (:func:`clear_records`) and 匯入庫存's
    「以券商為準」 (``services.positions_import.commit``). The caller checks the accounts are the user's and locks them
    first (``auto_dividends.lock_accounts``), then — in the same transaction as whatever else it writes — pauses
    定期定額 if asked, re-syncs the automatic dividends where rows remain or are added, purges the group-feed threads
    of the returned ``feed_keys`` and commits (or rolls back: a dry run). No ledger check: a strict replay only checks
    a stock against its own rows, so removing all of a stock's rows cannot make another one inconsistent."""
    ids = list(account_ids)
    if not ids:
        return DeletedRecords()
    txn_scope = [Transaction.user_id == user.id, Transaction.account_id.in_(ids)]
    skip_scope = [AutoDividendSkip.user_id == user.id, AutoDividendSkip.account_id.in_(ids)]
    if symbol is not None:
        txn_scope.append(Transaction.symbol == symbol)
        skip_scope.append(AutoDividendSkip.symbol == symbol)
    # only the columns the counts, the feed keys and the realtime fan-out need (an account can hold thousands of rows)
    rows = db.execute(select(Transaction.account_id, Transaction.trade_date, Transaction.symbol, Transaction.type,
                             Transaction.source, Transaction.note).where(*txn_scope)).all()
    if not rows:
        return DeletedRecords()
    _announce_deleted(db, user, rows)
    db.execute(sql_delete(Transaction).where(*txn_scope))
    db.execute(sql_delete(AutoDividendSkip).where(*skip_scope))
    db.flush()
    return DeletedRecords(len(rows), len({r.symbol for r in rows if r.symbol}), sharing.trade_keys(rows))


def _announce_deleted(db: Session, user: User, rows: Sequence[Any]) -> None:
    """Realtime (2026-11-17 merge): the bulk ``DELETE`` is not seen by the ORM capture, so the same events a row-by-row
    delete gives are emitted here — ``ledger{account_id}`` for each account that lost rows (the user's devices) and
    the fan-out: groups that see positions (any row) or the feed (a row the feed showed), viewers whose delegation
    covers those accounts. Sent with the commit; a rollback (a dry run) drops them."""
    accounts = sorted({r.account_id for r in rows})
    realtime.emit(db, *(realtime.event("ledger", {"account_id": a}, realtime.user(user.id)) for a in accounts),
                  realtime.LedgerFanout(user.id, accounts, positions=True,
                                        feed=any(realtime.feed_visible(lambda k, r=r: getattr(r, k)) for r in rows)))


# -- a whole stock out of one account (產品負責人 2026-11-17：「還要有刪除股票的功能」) --------------------------------
@dataclass
class HoldingDeleted:
    account_id: str
    symbol: str
    deleted: int  # records deleted: every type, the automatic dividends included
    plans_paused: int  # 定期定額 of this stock in this account paused by this request (``pause_plans``)
    plans_running: int  # those still running afterwards: they would offer this stock again at the next debit


def holding_symbol(md: MarketData, text: str) -> str:
    """The stored symbol ``text`` names, resolved the way ``GET /transactions?symbol=`` filters (2330 → 2330.TW), so
    the records listed for a stock are exactly the ones its deletion removes."""
    return md.resolve(text) or text.upper()


def _running(plan: RecurringPlan, today: date) -> bool:
    """Still has a debit ahead: active, not past its end date, and ``recurring.next_debit`` finds one (the
    ``next_date`` of ``GET /recurring``). The web's ``planStatus(...) === "active"`` is the same test, so the
    confirmation's 「同時暫停」 and the response's ``plans_running`` agree — a plan whose end date comes before its
    next debit day offers nothing more and is not counted."""
    if plan.end_date is not None and plan.end_date < today:
        return False
    return recurring.next_debit(plan, today) is not None


# Decorated like every other write of the books, for one consistent pattern only: its single re-sync of one stock
# reads that stock's notices at most once with or without it (none, in fact: no row of the stock is left to book a
# dividend from). No test can tell it is here; 匯入庫存's (``positions_import.commit``) is the one that saves reads.
@auto_dividends.shared_events
def delete_holding(db: Session, user: User, account_id: str, symbol: str, md: MarketData,
                   pause_plans: bool = False) -> HoldingDeleted:
    """Delete every record of ``symbol`` in one account (:func:`delete_records`): buys, sells, dividends (automatic
    ones included), splits, capital reductions and any cash row tagged with the stock — what
    ``GET /transactions?account_id=&symbol=`` lists. Unlike 全部賣出 nothing is booked: the stock is as if it had
    never been recorded there.

    * No ledger check: the strict replay only checks a stock against its own rows (oversell, a stock dividend without
      shares), so removing all of one stock's rows cannot make another one inconsistent — and books that were already
      inconsistent (a wrong import) are exactly what this is for.
    * The automatic-dividend skips of the stock in this account go with its records (they describe edits to those
      rows; recorded again later, the dividends are booked afresh — as deleting the account does). With no row left
      the sync has nothing to book the stock from, so no automatic dividend comes back.
    * 定期定額 of the stock in this account are only paused with ``pause_plans`` (``active = false``, undone in 設定);
      otherwise the response says how many still run. Other accounts, other stocks, the watchlist and other users are
      not touched. 404 ``not_found`` when the account is not the user's, 404 ``no_records`` when it holds no record
      of the stock (nothing changed).
    """
    account = _get_account(db, user, account_id)
    auto_dividends.lock_accounts(db, [account.id])
    gone = delete_records(db, user, [account.id], symbol)
    if not gone.count:
        # its own code (not ``not_found``): the web reads it as "already gone" (deleted in another tab or device) and
        # refreshes, while 「找不到帳戶」 and an unknown route stay errors
        raise ApiError(404, "no_records", "這個帳戶沒有這一檔的紀錄")
    today = today_taipei()
    plans = [p for p in db.scalars(select(RecurringPlan).where(
        RecurringPlan.user_id == user.id, RecurringPlan.account_id == account.id, RecurringPlan.symbol == symbol))
        if _running(p, today)]
    paused = 0
    if pause_plans:
        for p in plans:
            p.active = False
            p.updated_at = now_utc()
            paused += 1
    auto_dividends.after_user_change(db, user, md, [(account.id, symbol)])
    db.flush()
    sharing.purge_trade_threads(db, user.id, gone.feed_keys)  # their group feed items (and comments) go with them
    db.commit()
    return HoldingDeleted(account.id, symbol, gone.count, paused, len(plans) - paused)


# -- 清除所有持倉: every record of one account, or of every account (產品負責人 2026-11-17) ------------------------
TRADE_TYPES = frozenset({TxnType.BUY, TxnType.SELL})
DIVIDEND_TYPES = frozenset({TxnType.CASH_DIVIDEND, TxnType.STOCK_DIVIDEND})


@dataclass
class RecordCount:
    records: int = 0  # every type: buys, sells, dividends (automatic ones included), splits, deposits…
    trades: int = 0  # buys and sells
    dividends: int = 0  # cash and stock dividends
    symbols: int = 0  # distinct stocks in those records (the same stock in two accounts counts once)
    plans_running: int = 0  # 定期定額 with a debit ahead (``_running``)


@dataclass
class RecordCounts:
    total: RecordCount
    accounts: list[tuple[str, RecordCount]]  # every account of the user, in the order of ``GET /accounts``


def record_counts(db: Session, user: User) -> RecordCounts:
    """What 清除所有持倉 would delete, per account and in total (``GET /portfolio/records``): one grouped count over
    the user's transactions, and the 定期定額 still running (the same test as ``delete_holding``)."""
    account_ids = list(db.scalars(select(BrokerAccount.id).where(BrokerAccount.user_id == user.id)
                                  .order_by(BrokerAccount.created_at, BrokerAccount.id)))
    per: dict[str, RecordCount] = {a: RecordCount() for a in account_ids}
    symbols: dict[str, set[str]] = {a: set() for a in account_ids}
    rows = db.execute(select(Transaction.account_id, Transaction.type, Transaction.symbol, func.count())
                      .where(Transaction.user_id == user.id)
                      .group_by(Transaction.account_id, Transaction.type, Transaction.symbol))
    for account_id, kind, symbol, n in rows:
        c = per.get(account_id)
        if c is None:
            continue
        c.records += n
        c.trades += n if kind in TRADE_TYPES else 0
        c.dividends += n if kind in DIVIDEND_TYPES else 0
        if symbol:
            symbols[account_id].add(symbol)
    today = today_taipei()
    for p in db.scalars(select(RecurringPlan).where(RecurringPlan.user_id == user.id)):
        if p.account_id in per and _running(p, today):
            per[p.account_id].plans_running += 1
    total = RecordCount()
    for a in account_ids:
        c = per[a]
        c.symbols = len(symbols[a])
        total.records += c.records
        total.trades += c.trades
        total.dividends += c.dividends
        total.plans_running += c.plans_running
    total.symbols = len(set().union(*symbols.values())) if symbols else 0
    return RecordCounts(total, [(a, per[a]) for a in account_ids])


@dataclass
class RecordsCleared:
    account_id: str | None  # None: every account
    deleted: int
    symbols: int
    plans_paused: int
    plans_running: int


def clear_records(db: Session, user: User, account_id: str | None, pause_plans: bool = False) -> RecordsCleared:
    """清除所有持倉: delete every record of one account (``account_id``) or of every account of the user (None), in one
    transaction — buys, sells, dividends (automatic ones included), splits, capital reductions and the cash rows
    (deposits, fees…), whether or not they carry a symbol. Like ``delete_holding`` for each stock, and nothing is
    booked: the accounts stay, empty, as if nothing had ever been recorded in them.

    * The same rules as ``delete_holding``: no ledger check (books that were already inconsistent are what this is
      for); the automatic-dividend skips of those accounts go too (recorded again later, the dividends are booked
      afresh), and with no row left the sync has nothing to book from, so no automatic dividend comes back (no
      ``after_user_change`` needed); group feed items and their comments and reactions go with the trades
      (``sharing.purge_trade_threads_bulk``: one query, not one per feed item); the deletion itself is
      :func:`delete_records` with no symbol (cash rows included); 定期定額 in the scope are only paused
      with ``pause_plans`` (``active = false``, never deleted), otherwise ``plans_running`` says how many still run.
    * Kept: the accounts themselves, the watchlist, groups and share settings, delegations, AI conversations,
      preferences, other users. 404 ``not_found`` when the account is not the user's; 404 ``no_records`` when the
      scope holds no record (already cleared in another tab or device). The pause still happens then: the records
      the user asked to clear are gone either way, and the plans they asked to pause should not keep proposing
      drafts — so ``pause_plans`` is honoured and committed before the 404, whose error carries ``plans_paused``
      and ``plans_running`` like the 200.
    """
    if account_id is None:
        ids = list(db.scalars(select(BrokerAccount.id).where(BrokerAccount.user_id == user.id)))
    else:
        ids = [_get_account(db, user, account_id).id]
    auto_dividends.lock_accounts(db, ids)
    today = today_taipei()
    plans = [p for p in db.scalars(select(RecurringPlan).where(
        RecurringPlan.user_id == user.id, RecurringPlan.account_id.in_(ids))) if _running(p, today)] if ids else []
    paused = 0
    if pause_plans:
        for p in plans:
            p.active = False
            p.updated_at = now_utc()
            paused += 1
    gone = delete_records(db, user, ids)  # every record of the scope, symbol or not; nothing when there is none
    if not gone.count:
        if paused:
            db.commit()
        raise ApiError(404, "no_records", "這個帳戶沒有任何紀錄" if account_id else "沒有任何紀錄",
                       extra={"plans_paused": paused, "plans_running": len(plans) - paused})
    sharing.purge_trade_threads_bulk(db, user.id, gone.feed_keys)
    db.commit()
    return RecordsCleared(account_id, gone.count, gone.symbols, paused, len(plans) - paused)
