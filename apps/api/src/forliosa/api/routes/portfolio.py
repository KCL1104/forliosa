"""Portfolio summary, holdings and performance."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from forliosa.api.deps import current_user
from forliosa.api.schemas import ClosedRound, Holding, Performance, PortfolioSummary, UpcomingItem
from forliosa.db import get_db
from forliosa.marketdata.service import get_market_data
from forliosa.models import User
from forliosa.services import portfolio as svc
from forliosa.services import recurring
from forliosa.timeutil import today_taipei

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/summary", response_model=PortfolioSummary)
def portfolio_summary(account_id: str | None = None, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    md = get_market_data()
    return svc.summary(svc.compute_state(db, user, md, account_id), md)


@router.get("/holdings", response_model=list[Holding])
def portfolio_holdings(account_id: str | None = None, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    return svc.holdings(svc.compute_state(db, user, get_market_data(), account_id))


@router.get("/closed", response_model=list[ClosedRound], summary="出清紀錄：已全部賣出的持股回合（最近出清的在前）")
def portfolio_closed(account_id: str | None = None, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    md = get_market_data()
    return svc.closed_positions(svc.ledger_view(db, user, md, account_id), md)


@router.get("/performance", response_model=Performance)
def portfolio_performance(
    range: str = Query("1Y"),
    benchmark: str | None = None,
    account_id: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return svc.performance(db, user, get_market_data(), range.upper(), benchmark, account_id)


@router.get("/upcoming", response_model=list[UpcomingItem], summary="本週事項：持股的除息、股利入帳、定期定額扣款")
def portfolio_upcoming(days: int = Query(7), account_id: str | None = None, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    md = get_market_data()
    state = svc.compute_state(db, user, md, account_id)
    today = today_taipei()
    plans = recurring.upcoming_items(db, user, md, [a.id for a in state.inp.accounts], today,
                                     today + timedelta(days=days)) if 1 <= days <= svc.UPCOMING_MAX_DAYS else []
    return svc.upcoming(state, md, days, plans)
