"""Transactions CRUD with cursor pagination, and the fee/tax preview."""

from __future__ import annotations

import base64
import binascii
from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from forliosa.api import serialize as ser
from forliosa.api.deps import current_user
from forliosa.api.errors import not_found, unprocessable
from forliosa.api.schemas import (
    TradePreview,
    Transaction,
    TransactionIn,
    TransactionPage,
    TransactionPatch,
    TxnTypeLiteral,
)
from forliosa.db import get_db
from forliosa.marketdata.service import get_market_data
from forliosa.models import Transaction as TxnModel
from forliosa.models import User
from forliosa.services import transactions as svc
from forliosa.timeutil import iso_taipei

router = APIRouter(prefix="/transactions", tags=["transactions"])


def txn_out(t: TxnModel) -> dict:
    return {
        "id": t.id, "account_id": t.account_id, "symbol": t.symbol, "type": t.type, "trade_date": t.trade_date,
        "quantity": ser.qty(t.quantity), "price": ser.price(t.price), "amount": ser.money(t.amount),
        "fee": ser.money(t.fee), "tax": ser.money(t.tax), "health_insurance": ser.money(t.health_insurance),
        "currency": t.currency, "is_day_trade": t.is_day_trade, "note": t.note, "source": t.source,
        "created_at": iso_taipei(t.created_at),
    }


def _encode_cursor(t: TxnModel) -> str:
    return base64.urlsafe_b64encode(f"{t.trade_date.isoformat()}|{t.id}".encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[date, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        d, i = raw.split("|", 1)
        return date.fromisoformat(d), i
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise unprocessable("分頁游標無效") from exc


def _owned(db: Session, user: User, txn_id: str) -> TxnModel:
    t = db.get(TxnModel, txn_id)
    if t is None or t.user_id != user.id:
        raise not_found("找不到交易")
    return t


@router.get("", response_model=TransactionPage)
def list_transactions(
    account_id: str | None = None,
    symbol: str | None = None,
    type: TxnTypeLiteral | None = None,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = select(TxnModel).where(TxnModel.user_id == user.id)
    if account_id:
        q = q.where(TxnModel.account_id == account_id)
    if symbol:
        q = q.where(TxnModel.symbol == (get_market_data().resolve(symbol) or symbol.upper()))
    if type:
        q = q.where(TxnModel.type == type)
    if from_:
        q = q.where(TxnModel.trade_date >= from_)
    if to:
        q = q.where(TxnModel.trade_date <= to)
    if cursor:
        cd, cid = _decode_cursor(cursor)
        q = q.where(or_(TxnModel.trade_date < cd, and_(TxnModel.trade_date == cd, TxnModel.id < cid)))
    rows = list(db.scalars(q.order_by(TxnModel.trade_date.desc(), TxnModel.id.desc()).limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {"items": [txn_out(t) for t in rows], "next_cursor": _encode_cursor(rows[-1]) if has_more else None}


@router.post("", response_model=Transaction, status_code=201)
def create_transaction(body: TransactionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return txn_out(svc.create(db, user, body.model_dump(), get_market_data()))


@router.post("/preview", response_model=TradePreview, summary="預估手續費與稅")
def preview_transaction(body: TransactionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = svc.compute(db, user, body.model_dump(), get_market_data()).preview
    return {"gross": ser.money(p.gross), "fee": ser.money(p.fee), "tax": ser.money(p.tax),
            "health_insurance": ser.money(p.health_insurance), "net_cash": ser.money(p.net_cash), "rules": p.rules}


@router.get("/{txn_id}", response_model=Transaction)
def get_transaction(txn_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return txn_out(_owned(db, user, txn_id))


@router.patch("/{txn_id}", response_model=Transaction)
def update_transaction(txn_id: str, body: TransactionPatch, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    t = _owned(db, user, txn_id)
    return txn_out(svc.update(db, user, t, body.model_dump(exclude_unset=True), get_market_data()))


@router.delete("/{txn_id}", status_code=204)
def delete_transaction(txn_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    svc.delete(db, user, _owned(db, user, txn_id))
    return Response(status_code=204)
