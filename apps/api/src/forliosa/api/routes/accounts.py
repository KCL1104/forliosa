"""Broker accounts CRUD.

「只記持股」 (holdings-only tracking with a snapshot) was removed on 2026-11-14 (product owner: every buy has a date;
migration ``0018`` turned each snapshot into dated buys). A request that still carries ``tracking_mode`` is accepted
when it says ``transactions`` and refused with 422 when it says ``holdings``.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from forliosa.api import serialize as ser
from forliosa.api.deps import current_user
from forliosa.api.errors import ApiError, not_found, unprocessable
from forliosa.api.schemas import Account, AccountIn, AccountPatch
from forliosa.db import get_db
from forliosa.domain.fees import COMMISSION_RATE, DEFAULT_MIN_FEE
from forliosa.ids import new_id
from forliosa.models import AutoDividendSkip, BrokerAccount, Transaction, User
from forliosa.services import scope, sharing
from forliosa.timeutil import iso_taipei

router = APIRouter(prefix="/accounts", tags=["accounts"])

HOLDINGS_MODE_REMOVED = "「只記持股」已經取消，每一筆買進都要記日期。"


def account_out(a: BrokerAccount) -> dict:
    return {
        "id": a.id, "name": a.name, "broker": a.broker, "currency": a.currency,
        "fee_rate": ser.ratio(a.fee_rate), "fee_discount": ser.ratio(a.fee_discount),
        "min_fee": ser.money(a.min_fee), "min_fee_odd_lot": ser.money(a.min_fee_odd_lot),
        "created_at": iso_taipei(a.created_at),
    }


def _refuse_holdings_mode(body: AccountIn | AccountPatch) -> None:
    if body.tracking_mode == "holdings":
        raise unprocessable(HOLDINGS_MODE_REMOVED, code="tracking_mode_removed",
                            details=[{"field": "tracking_mode", "message": HOLDINGS_MODE_REMOVED}])


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
    _refuse_holdings_mode(body)
    usd = body.currency == "USD"
    # TW defaults: 0.1425%, NT$20 minimum; USD (複委託) defaults: no fee unless configured.
    fee_rate = body.fee_rate if body.fee_rate is not None else (Decimal(0) if usd else COMMISSION_RATE)
    min_fee = body.min_fee if body.min_fee is not None else (Decimal(0) if usd else DEFAULT_MIN_FEE)
    min_odd = body.min_fee_odd_lot if body.min_fee_odd_lot is not None else (Decimal(0) if usd else Decimal(1))
    acc = BrokerAccount(
        id=new_id("acc"), user_id=user.id, name=body.name.strip(), broker=body.broker.strip(),
        currency=body.currency, fee_rate=fee_rate, fee_discount=body.fee_discount, min_fee=min_fee,
        min_fee_odd_lot=min_odd,
    )
    db.add(acc)
    db.commit()
    return account_out(acc)


@router.patch("/{account_id}", response_model=Account)
def update_account(account_id: str, body: AccountPatch, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    acc = get_owned_account(db, user, account_id)
    _refuse_holdings_mode(body)
    changes = body.model_dump(exclude_unset=True, exclude_none=True, exclude={"tracking_mode"})
    if "currency" in changes and changes["currency"] != acc.currency:
        n = db.scalar(select(func.count()).select_from(Transaction).where(Transaction.account_id == acc.id))
        if n:
            raise ApiError(409, "conflict", "帳戶已有交易紀錄，不能變更幣別")
    for k, v in changes.items():
        setattr(acc, k, v.strip() if isinstance(v, str) and k in ("name", "broker") else v)
    db.commit()
    return account_out(acc)


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    acc = get_owned_account(db, user, account_id)
    keys = sharing.trade_keys(db.scalars(select(Transaction).where(Transaction.account_id == acc.id,
                                                                   Transaction.user_id == user.id)))
    db.execute(delete(Transaction).where(Transaction.account_id == acc.id, Transaction.user_id == user.id))
    sharing.purge_trade_threads(db, user.id, keys)  # a group feed item goes with its last transaction
    db.execute(delete(AutoDividendSkip).where(AutoDividendSkip.account_id == acc.id))
    db.delete(acc)
    db.commit()
    return Response(status_code=204)
