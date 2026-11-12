"""Create/update/preview transactions: fill in fees and taxes, validate against the ledger."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from forliosa.api.errors import ApiError, unprocessable
from forliosa.domain.fees import (
    ZERO,
    FeeBreakdown,
    commission,
    dividend_cash_amount,
    fmt_money,
    preview_cash_dividend,
    round_half_up,
    stock_dividend_shares,
    transaction_tax,
    truncate,
)
from forliosa.domain.ledger import SECURITY_TYPES, LedgerError, TxnType, replay
from forliosa.ids import new_id
from forliosa.marketdata.service import MarketData
from forliosa.models import BrokerAccount, Transaction, User
from forliosa.services import auto_dividends
from forliosa.services.ledger_io import fee_schedule, instrument_ref, load_ledger_input, shares_held
from forliosa.timeutil import now_utc

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
    """Normalize a transaction payload; auto-calculate fee, tax and NHI premium when omitted.

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
            gross = amount if amount is not None else qty * px
            amount = gross
            if fee is None:
                fee, fee_rules = commission(gross, qty, fee_schedule(account), ref)
                rules += fee_rules
            else:
                rules.append(f"手續費：使用者輸入 {fmt_money(fee, currency)}")
            if t is TxnType.SELL:
                if tax is None:
                    tax, tax_rules = transaction_tax(gross, ref, trade_date, day_trade)
                    rules += tax_rules
                else:
                    rules.append(f"證交稅：使用者輸入 {fmt_money(tax, currency)}")
                net = gross - fee - tax
            else:
                tax = tax if tax is not None else ZERO
                rules.append("證交稅：買進免稅" if ref.is_tw else "美股無證交稅")
                net = -(gross + fee)
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
            if amount is None:
                if px:
                    shares = held()
                    amount = truncate(shares * px) if currency == "TWD" else truncate(shares * px, 2)
                    rules.append(f"退還股款 = {shares} 股 × {px} 元")
                else:
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


def validate_ledger(db: Session, user: User, account: BrokerAccount, candidate: Transaction | None,
                    remove_id: str | None = None, md: MarketData | None = None,
                    skip: auto_dividends.DividendKey | None = None) -> None:
    """Replay the account strictly with the candidate applied; reject inconsistent books.

    With ``md``, the books are checked as they will be after the automatic dividend sync: the touched symbols'
    automatic rows are recomputed in memory first (a sell before an ex-date removes that ex-date's automatic stock
    dividend instead of failing on it). The message says so when only the recomputed dividends break the books.
    ``skip``: an automatic dividend this change deletes or edits (it will be skipped from now on).
    """
    inp = load_ledger_input(db, user, accounts=[account])
    removed = next((t for t in inp.transactions if t.id == remove_id), None) if remove_id else None
    inp.transactions = [t for t in inp.transactions if t.id not in (remove_id, candidate.id if candidate else None)]
    if candidate is not None:
        inp.transactions.append(candidate)
    before: LedgerError | None = None
    try:
        replay(inp.ledger_txns(), inp.method, inp.openings(), strict=True)
    except LedgerError as exc:
        before = exc
    if md is None:
        if before is not None:
            raise unprocessable(str(before), code="ledger_inconsistent") from before
        return
    symbols = {t.symbol for t in (candidate, removed) if t is not None and t.symbol}
    if skip is not None:
        symbols.add(skip.symbol)
    after = replace(inp, transactions=auto_dividends.with_recomputed(db, user, md, inp, account, symbols,
                                                                     extra_skips=[skip] if skip else ()))
    try:
        replay(after.ledger_txns(), after.method, after.openings(), strict=True)
    except LedgerError as exc:
        if before is None:
            raise auto_dividends.conflict_error(exc) from exc
        raise unprocessable(str(exc), code="ledger_inconsistent") from exc


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
    # Editing an automatic dividend turns it into the user's own version: the sync never touches it again.
    edited_auto = auto_dividends.key_of(txn) if txn.source == auto_dividends.AUTO else None
    if txn.source == auto_dividends.AUTO:
        patch = {**patch, "source": auto_dividends.AUTO_EDITED}
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
    db.commit()
    return txn


def delete(db: Session, user: User, txn: Transaction, md: MarketData) -> None:
    """Delete a transaction. Deleting an automatic dividend keeps a skip so the sync never books it again."""
    account = _get_account(db, user, txn.account_id)
    auto_dividends.lock_accounts(db, [account.id])
    auto_key = auto_dividends.key_of(txn) if txn.source == auto_dividends.AUTO else None
    validate_ledger(db, user, account, None, remove_id=txn.id, md=md, skip=auto_key)
    scope = _dividend_scope(txn)
    db.delete(txn)
    if auto_key is not None:
        auto_dividends.remember_skip(db, user, auto_key, "deleted")
    auto_dividends.after_user_change(db, user, md, scope)
    db.commit()
