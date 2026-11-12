"""Portfolio summary, holdings and performance."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from forliosa.api.deps import current_user
from forliosa.api.schemas import Holding, Performance, PortfolioSummary, UpcomingItem
from forliosa.db import get_db
from forliosa.marketdata.service import get_market_data
from forliosa.models import User
from forliosa.services import portfolio as svc

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


@router.get("/performance", response_model=Performance)
def portfolio_performance(
    range: str = Query("1Y"),
    benchmark: str | None = None,
    account_id: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return svc.performance(db, user, get_market_data(), range.upper(), benchmark, account_id)


@router.get("/upcoming", response_model=list[UpcomingItem], summary="本週事項：持股的除息、股利入帳")
def portfolio_upcoming(days: int = Query(7), account_id: str | None = None, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    md = get_market_data()
    return svc.upcoming(svc.compute_state(db, user, md, account_id), md, days)
