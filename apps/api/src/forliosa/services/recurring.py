"""定期定額 (recurring purchase plans): CRUD, debit schedule and a signable transaction draft.

* A plan buys ``amount`` NT$ of a Taiwan stock or ETF on each day in ``days_of_month`` (1–28, e.g. 6 and
  19, or 6/16/26). When the day is not a trading day the debit moves to the **next trading day**, using
  TWSE's official holiday schedule when it is archived (``forliosa.market_calendar``), else the built-in list.
* Plans never create transactions. ``draft`` returns a ``/transactions/preview``-style draft for one debit:
  the trade date is the debit day; shares = floor(amount ÷ close) (odd lots included) and the account's
  commission on top. The close is **the debit day's own close** when the debit day is already past (a missed
  debit recorded later), else the latest close; a past day without a real close (demo candles never count)
  falls back to the latest close and says so in the rules. The frontend shows it as an AI draft the user
  signs, then posts ``transaction`` to ``POST /transactions``.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.api import serialize as ser
from forliosa.api.errors import ApiError, not_found, unprocessable
from forliosa.datapolicy import labels, tagged
from forliosa.ids import new_id
from forliosa.market_calendar import load_official_calendar
from forliosa.marketdata.service import MarketData
from forliosa.models import BrokerAccount, RecurringPlan, User
from forliosa.services.scope import account_filter
from forliosa.timeutil import (
    has_official_calendar,
    iso_taipei,
    last_tw_trading_day,
    next_tw_trading_day,
    now_utc,
    today_taipei,
)

MAX_PLANS = 100
NEXT_DATE_HORIZON_DAYS = 400


# -- schedule --------------------------------------------------------------------------------------------
def debit_dates(plan: RecurringPlan, lo: date, hi: date) -> list[tuple[date, date]]:
    """(scheduled day, debit day) pairs whose debit day is in [lo, hi], in date order.

    A scheduled day counts when it is within [start_date, end_date]; its debit is the next trading day on or
    after it (so a debit can fall a few days after ``end_date``).
    """
    out: list[tuple[date, date]] = []
    y, m = (lo - timedelta(days=20)).year, (lo - timedelta(days=20)).month  # holidays push debits forward
    while date(y, m, 1) <= hi:
        for day in sorted(plan.days_of_month or []):
            scheduled = date(y, m, day)
            if scheduled < plan.start_date or (plan.end_date is not None and scheduled > plan.end_date):
                continue
            debit = next_tw_trading_day(scheduled)
            if lo <= debit <= hi:
                out.append((scheduled, debit))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return sorted(out, key=lambda p: (p[1], p[0]))


def next_debit(plan: RecurringPlan, on_or_after: date) -> tuple[date, date] | None:
    if not plan.active:
        return None
    dates = debit_dates(plan, on_or_after, on_or_after + timedelta(days=NEXT_DATE_HORIZON_DAYS))
    return dates[0] if dates else None


def calendar_source(d: date) -> str:
    return "twse-openapi/calendar" if has_official_calendar(d.year) else "rules"


# -- CRUD ------------------------------------------------------------------------------------------------
def _account(db: Session, user: User, account_id: str) -> BrokerAccount:
    acc = db.get(BrokerAccount, account_id)
    if acc is None or acc.user_id != user.id:
        raise not_found("找不到帳戶")
    if acc.currency != "TWD":
        raise unprocessable("定期定額金額以新台幣計，帳戶幣別必須是 TWD")
    return acc


def _symbol(md: MarketData, text: str) -> str:
    info = md.instrument(text)
    if info is None:
        raise unprocessable(f"找不到商品：{text}", code="unknown_symbol")
    if info.market == "US":
        raise unprocessable("定期定額只支援台股與 ETF")
    return info.symbol


def owned(db: Session, user: User, plan_id: str) -> RecurringPlan:
    plan = db.get(RecurringPlan, plan_id)
    if plan is None or plan.user_id != user.id:
        raise not_found("找不到定期定額計畫")
    return plan


def plans_of(db: Session, user: User, account_ids: list[str] | None = None) -> list[RecurringPlan]:
    stmt = select(RecurringPlan).where(RecurringPlan.user_id == user.id)
    if account_ids is not None:
        stmt = stmt.where(RecurringPlan.account_id.in_(account_ids))
    allowed = account_filter(db, user.id)  # read-only viewing: only the delegated accounts' plans
    if allowed is not None:
        stmt = stmt.where(RecurringPlan.account_id.in_(sorted(allowed)))
    return list(db.scalars(stmt.order_by(RecurringPlan.created_at, RecurringPlan.id)))


def plan_out(plan: RecurringPlan, md: MarketData, today: date | None = None) -> dict[str, Any]:
    info = md.instrument(plan.symbol)
    nxt = next_debit(plan, today or today_taipei())
    return {
        "id": plan.id, "account_id": plan.account_id, "symbol": plan.symbol,
        "name": info.name if info else plan.symbol,
        "amount": ser.money(plan.amount), "day_of_month": sorted(plan.days_of_month or []),
        "start_date": plan.start_date, "end_date": plan.end_date, "active": plan.active, "note": plan.note,
        "next_date": nxt[1] if nxt else None,
        "created_at": iso_taipei(plan.created_at), "updated_at": iso_taipei(plan.updated_at),
    }


def _validate_dates(start: date, end: date | None) -> None:
    if end is not None and end < start:
        raise unprocessable("結束日不能早於開始日")


def _whole_dollars(amount: Decimal) -> Decimal:
    if amount != amount.to_integral_value():
        raise unprocessable("定期定額金額必須是整數元")
    return amount


def list_plans(db: Session, user: User, md: MarketData, account_id: str | None = None) -> list[dict[str, Any]]:
    load_official_calendar(db)
    return [plan_out(p, md) for p in plans_of(db, user, [account_id] if account_id else None)]


def create(db: Session, user: User, md: MarketData, body: dict[str, Any]) -> dict[str, Any]:
    acc = _account(db, user, body["account_id"])
    symbol = _symbol(md, body["symbol"])
    start = body.get("start_date") or today_taipei()
    _validate_dates(start, body.get("end_date"))
    if len(plans_of(db, user)) >= MAX_PLANS:
        raise ApiError(409, "conflict", f"定期定額計畫最多 {MAX_PLANS} 個")
    now = now_utc()
    plan = RecurringPlan(id=new_id("rcp"), user_id=user.id, account_id=acc.id, symbol=symbol,
                         amount=_whole_dollars(body["amount"]), days_of_month=body["day_of_month"],
                         start_date=start, end_date=body.get("end_date"), active=body.get("active", True),
                         note=body.get("note") or "", created_at=now, updated_at=now)
    db.add(plan)
    db.commit()
    load_official_calendar(db)
    return plan_out(plan, md)


def update(db: Session, user: User, md: MarketData, plan: RecurringPlan, patch: dict[str, Any]) -> dict[str, Any]:
    if "account_id" in patch:
        plan.account_id = _account(db, user, patch["account_id"]).id
    if "symbol" in patch:
        plan.symbol = _symbol(md, patch["symbol"])
    if "amount" in patch:
        plan.amount = _whole_dollars(patch["amount"])
    if "day_of_month" in patch:
        plan.days_of_month = patch["day_of_month"]
    for k in ("start_date", "end_date", "active", "note"):
        if k in patch:
            setattr(plan, k, patch[k] if k != "note" else (patch[k] or ""))
    _validate_dates(plan.start_date, plan.end_date)
    plan.updated_at = now_utc()
    db.commit()
    load_official_calendar(db)
    return plan_out(plan, md)


def delete(db: Session, plan: RecurringPlan) -> None:
    db.delete(plan)
    db.commit()


# -- upcoming --------------------------------------------------------------------------------------------
def upcoming_items(db: Session, user: User, md: MarketData, account_ids: list[str], lo: date,
                   hi: date) -> list[dict[str, Any]]:
    """``/portfolio/upcoming`` rows (type ``recurring``) for active plans of the given accounts."""
    load_official_calendar(db)
    out = []
    for plan in plans_of(db, user, account_ids):
        if not plan.active:
            continue
        info = md.instrument(plan.symbol)
        name = info.name if info else plan.symbol
        for scheduled, debit in debit_dates(plan, lo, hi):
            moved = "" if scheduled == debit else f"（{scheduled.month}/{scheduled.day} 非交易日，順延）"
            out.append({"date": debit, "type": "recurring", "symbol": plan.symbol,
                        "title": f"{name} 定期定額 NT${plan.amount:,.0f}{moved}",
                        "amount_estimate": ser.money(plan.amount), "is_demo": False,
                        "sources": labels(["ledger", calendar_source(debit)]),
                        "plan_id": plan.id, "account_id": plan.account_id, "scheduled_date": scheduled})
    return out


# -- draft -----------------------------------------------------------------------------------------------
def last_close(md: MarketData, symbol: str) -> tuple[Decimal, date, Any] | None:
    """The latest closing price: during the session that is the previous close, not the live price."""
    q = md.quote(symbol)
    if q is not None and q.price is not None and q.trade_date is not None:
        if not q.is_realtime:
            return q.price, q.trade_date, q
        if q.prev_close is not None:
            return q.prev_close, last_tw_trading_day(q.trade_date - timedelta(days=1)), q
    today = today_taipei()
    h = md.history(symbol, today - timedelta(days=14), today)
    if h.candles:
        c = h.candles[-1]
        return c.c, c.t, None
    return None


def close_on(md: MarketData, symbol: str, day: date) -> tuple[Decimal, str] | None:
    """That trading day's own real close (price, source), or None when no real source has it.

    Demo candles never count: under ``personal`` the facade answers a one-day range with synthetic data whenever
    no real source has that day (e.g. a young archive), and that must not pass as the debit day's close; the
    draft then falls back to the latest close and says so."""
    h = md.history(symbol, day, day)
    if h.is_demo:
        return None
    for c in h.candles:
        if c.t == day and c.c is not None and c.c > 0:
            return c.c, h.source
    return None


def draft(db: Session, user: User, md: MarketData, plan: RecurringPlan, on: date | None = None) -> dict[str, Any]:
    from forliosa.services import transactions as txn_svc

    load_official_calendar(db)
    today = today_taipei()
    if on is None:
        nxt = next_debit(plan, today)
        if nxt is None:
            raise ApiError(409, "conflict", "這個計畫沒有下一次扣款（已停用或已結束）")
        scheduled, debit = nxt
    else:
        scheduled, debit = on, next_tw_trading_day(on)
    # A past debit (recorded later) is priced at that day's own close; today's or a future one at the latest close.
    price_rules: list[str] = []
    price_sources: list[str] = []
    is_demo = False
    same_day = close_on(md, plan.symbol, debit) if debit < today else None
    if same_day is not None:
        price, src = same_day
        price_date = debit
        price_sources = tagged(src, "price")
    else:
        found = last_close(md, plan.symbol)
        if found is None:
            raise unprocessable(f"沒有 {plan.symbol} 的收盤價，估不出股數", code="no_price")
        price, price_date, q = found
        if q is not None:
            is_demo = bool(q.is_demo)
            price_sources = tagged(q.source, "price")
        if debit < today and price_date != debit:
            price_rules.append(f"沒有 {debit.month}/{debit.day} 的收盤價，改用最近收盤價"
                               f"（{price_date.month}/{price_date.day}）估算，請照對帳單修改")
    if price <= 0:
        raise unprocessable(f"沒有 {plan.symbol} 的收盤價，估不出股數", code="no_price")
    shares = (plan.amount / price).to_integral_value(rounding=ROUND_FLOOR)
    if shares < 1:
        raise unprocessable(f"NT${plan.amount:,.0f} 不足買 1 股（收盤價 {price.normalize():f}）",
                            code="amount_too_small")
    info = md.instrument(plan.symbol)
    name = info.name if info else plan.symbol
    body = {"account_id": plan.account_id, "symbol": plan.symbol, "type": "buy", "trade_date": debit,
            "quantity": shares, "price": price, "amount": None, "fee": None, "tax": None,
            "health_insurance": None, "currency": None, "is_day_trade": False,
            "note": f"定期定額 NT${plan.amount:,.0f}（{debit.month}/{debit.day}）", "source": "ai_draft"}
    preview = txn_svc.compute(db, user, body, md).preview
    lot = "零股" if shares < 1000 else ("整張" if shares % 1000 == 0 else "整張＋零股")
    rules = [f"股數 = floor(NT${plan.amount:,.0f} ÷ 收盤價 {price.normalize():f}"
             f"（{price_date.month}/{price_date.day}）) = {shares} 股（{lot}）", *price_rules,
             "手續費另計，不從定期定額金額扣除", *preview.rules]
    if scheduled != debit:
        rules.insert(0, f"扣款日 {scheduled.month}/{scheduled.day} 不是交易日，順延到 {debit.month}/{debit.day}")
    return {
        "plan_id": plan.id,
        "scheduled_date": scheduled,
        "date": debit,
        "name": name,
        "amount": ser.money(plan.amount),
        "price_as_of": price_date,
        "transaction": {"account_id": plan.account_id, "symbol": plan.symbol, "type": "buy", "trade_date": debit,
                        "quantity": ser.qty(shares), "price": ser.price(price), "note": body["note"],
                        "source": "ai_draft"},
        "preview": {"gross": ser.money(preview.gross), "fee": ser.money(preview.fee), "tax": ser.money(preview.tax),
                    "health_insurance": ser.money(preview.health_insurance),
                    "net_cash": ser.money(preview.net_cash), "rules": rules},
        "is_demo": is_demo,
        "sources": labels(["ledger", calendar_source(debit), *price_sources]),
    }
