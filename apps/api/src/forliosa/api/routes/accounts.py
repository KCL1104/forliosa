"""Broker accounts CRUD and the holdings-only snapshot."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from forliosa.api import serialize as ser
from forliosa.api.deps import current_user
from forliosa.api.errors import ApiError, not_found, unprocessable
from forliosa.api.schemas import Account, AccountIn, AccountPatch, HoldingsSnapshot, HoldingsSnapshotIn
from forliosa.db import get_db
from forliosa.domain.fees import COMMISSION_RATE, DEFAULT_MIN_FEE
from forliosa.ids import new_id
from forliosa.marketdata.service import get_market_data
from forliosa.models import AutoDividendSkip, BrokerAccount, HoldingSnapshot, Transaction, User
from forliosa.services import auto_dividends, scope, sharing
from forliosa.timeutil import iso_taipei

router = APIRouter(prefix="/accounts", tags=["accounts"])


def account_out(a: BrokerAccount) -> dict:
    return {
        "id": a.id, "name": a.name, "broker": a.broker, "currency": a.currency,
        "fee_rate": ser.ratio(a.fee_rate), "fee_discount": ser.ratio(a.fee_discount),
        "min_fee": ser.money(a.min_fee), "min_fee_odd_lot": ser.money(a.min_fee_odd_lot),
        "tracking_mode": a.tracking_mode, "created_at": iso_taipei(a.created_at),
    }


def get_owned_account(db: Session, user: User, account_id: str) -> BrokerAccount:
    acc = db.get(BrokerAccount, account_id)
    if acc is None or acc.user_id != user.id or not scope.account_visible(db, user.id, acc.id):
        raise not_found("找不到帳戶")
    return acc


@router.get("", response_model=list[Account])
def list_accounts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(BrokerAccount).where(BrokerAccount.id.in_(scope.account_ids(db, user.id)))
                      .order_by(BrokerAccount.created_at, BrokerAccount.id))
    return [account_out(a) for a in rows]


@router.post("", response_model=Account, status_code=201)
def create_account(body: AccountIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    usd = body.currency == "USD"
    # TW defaults: 0.1425%, NT$20 minimum; USD (複委託) defaults: no fee unless configured.
    fee_rate = body.fee_rate if body.fee_rate is not None else (Decimal(0) if usd else COMMISSION_RATE)
    min_fee = body.min_fee if body.min_fee is not None else (Decimal(0) if usd else DEFAULT_MIN_FEE)
    min_odd = body.min_fee_odd_lot if body.min_fee_odd_lot is not None else (Decimal(0) if usd else Decimal(1))
    acc = BrokerAccount(
        id=new_id("acc"), user_id=user.id, name=body.name.strip(), broker=body.broker.strip(),
        currency=body.currency, fee_rate=fee_rate, fee_discount=body.fee_discount, min_fee=min_fee,
        min_fee_odd_lot=min_odd, tracking_mode=body.tracking_mode,
    )
    db.add(acc)
    db.commit()
    return account_out(acc)


@router.patch("/{account_id}", response_model=Account)
def update_account(account_id: str, body: AccountPatch, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    acc = get_owned_account(db, user, account_id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "currency" in changes and changes["currency"] != acc.currency:
        n = db.scalar(select(func.count()).select_from(Transaction).where(Transaction.account_id == acc.id))
        if n:
            raise ApiError(409, "conflict", "帳戶已有交易紀錄，不能變更幣別")
    mode_changed = "tracking_mode" in changes and changes["tracking_mode"] != acc.tracking_mode
    for k, v in changes.items():
        setattr(acc, k, v.strip() if isinstance(v, str) and k in ("name", "broker") else v)
    if mode_changed:  # holdings-only accounts book dividends only after the snapshot date
        db.flush()
        auto_dividends.after_user_change(db, user, get_market_data(), [(acc.id, None)], assume_consistent=False)
    db.commit()
    return account_out(acc)


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    acc = get_owned_account(db, user, account_id)
    keys = sharing.trade_keys(db.scalars(select(Transaction).where(Transaction.account_id == acc.id,
                                                                   Transaction.user_id == user.id)))
    db.execute(delete(Transaction).where(Transaction.account_id == acc.id, Transaction.user_id == user.id))
    sharing.purge_trade_threads(db, user.id, keys)  # a group feed item goes with its last transaction
    db.execute(delete(HoldingSnapshot).where(HoldingSnapshot.account_id == acc.id))
    db.execute(delete(AutoDividendSkip).where(AutoDividendSkip.account_id == acc.id))
    db.delete(acc)
    db.commit()
    return Response(status_code=204)


def _snapshot_out(account_id: str, rows: list[HoldingSnapshot]) -> dict:
    return {
        "account_id": account_id,
        "as_of": max((r.as_of for r in rows), default=None),
        "holdings": [{"symbol": r.symbol, "quantity": ser.qty(r.quantity), "avg_cost": ser.price(r.avg_cost)}
                     for r in sorted(rows, key=lambda r: r.symbol)],
    }


@router.get("/{account_id}/holdings", response_model=HoldingsSnapshot, summary="目前的持股快照（只記持股模式）")
def get_holdings_snapshot(account_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    acc = get_owned_account(db, user, account_id)
    rows = list(db.scalars(select(HoldingSnapshot).where(HoldingSnapshot.account_id == acc.id)))
    return _snapshot_out(acc.id, rows)


@router.put("/{account_id}/holdings", response_model=HoldingsSnapshot, summary="以快照覆蓋持股（只記持股模式）")
def put_holdings_snapshot(account_id: str, body: HoldingsSnapshotIn, user: User = Depends(current_user),
                          db: Session = Depends(get_db)):
    acc = get_owned_account(db, user, account_id)
    if acc.tracking_mode != "holdings":
        raise ApiError(409, "conflict", "這個帳戶是逐筆交易模式；請先把追蹤模式改為「只記持股」")
    md = get_market_data()
    resolved: dict[str, HoldingSnapshot] = {}
    for h in body.holdings:
        info = md.instrument(h.symbol)
        if info is None:
            raise unprocessable(f"找不到商品：{h.symbol}", code="unknown_symbol")
        if info.market != "US" and h.quantity != h.quantity.to_integral_value():
            raise unprocessable(f"{info.symbol} 台股股數必須是整數")
        if info.symbol in resolved:
            raise unprocessable(f"{info.symbol} 重複出現")
        resolved[info.symbol] = HoldingSnapshot(
            id=new_id("hld"), user_id=user.id, account_id=acc.id, as_of=body.as_of, symbol=info.symbol,
            quantity=h.quantity, avg_cost=h.avg_cost,
        )
    db.execute(delete(HoldingSnapshot).where(HoldingSnapshot.account_id == acc.id))
    db.add_all(resolved.values())
    db.flush()
    auto_dividends.after_user_change(db, user, md, [(acc.id, None)], assume_consistent=False)
    db.commit()
    return _snapshot_out(acc.id, list(resolved.values()))
