"""定期定額 (recurring purchase plans): CRUD and a signable draft for one debit."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from forliosa.api.deps import current_user
from forliosa.api.schemas import RecurringDraft, RecurringPlanIn, RecurringPlanOut, RecurringPlanPatch
from forliosa.db import get_db
from forliosa.marketdata.service import get_market_data
from forliosa.models import User
from forliosa.services import recurring as svc

router = APIRouter(prefix="/recurring", tags=["recurring"])

# Explicit null clears only end_date; null on any other field means "unchanged".
_NULLABLE = frozenset({"end_date"})


@router.get("", response_model=list[RecurringPlanOut])
def list_plans(account_id: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.list_plans(db, user, get_market_data(), account_id)


@router.post("", response_model=RecurringPlanOut, status_code=201)
def create_plan(body: RecurringPlanIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.create(db, user, get_market_data(), body.model_dump())


@router.get("/{plan_id}", response_model=RecurringPlanOut)
def get_plan(plan_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.plan_out(svc.owned(db, user, plan_id), get_market_data())


@router.patch("/{plan_id}", response_model=RecurringPlanOut)
def update_plan(plan_id: str, body: RecurringPlanPatch, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    patch = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None or k in _NULLABLE}
    return svc.update(db, user, get_market_data(), svc.owned(db, user, plan_id), patch)


@router.delete("/{plan_id}", status_code=204, response_class=Response)
def delete_plan(plan_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    svc.delete(db, svc.owned(db, user, plan_id))
    return Response(status_code=204)


@router.post("/{plan_id}/draft", response_model=RecurringDraft,
             summary="下一次扣款的交易草稿（不會建立交易；使用者確認後再 POST /transactions）")
def draft(plan_id: str, on: date | None = Query(default=None, alias="date", description="扣款日（預設下一次）"),
          user: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.draft(db, user, get_market_data(), svc.owned(db, user, plan_id), on)
