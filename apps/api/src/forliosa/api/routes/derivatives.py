"""Futures market (TAIFEX OpenAPI archive): overview and near-month futures history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from forliosa.api.deps import current_user
from forliosa.api.schemas import DerivativesOverview, FuturesHistory
from forliosa.db import get_db
from forliosa.marketdata.service import get_market_data
from forliosa.models import User
from forliosa.services import derivatives as svc

router = APIRouter(prefix="/derivatives", tags=["derivatives"])


@router.get("/overview", response_model=DerivativesOverview,
            summary="期貨盤勢：台指期等近月行情（含夜盤）、Put/Call 比、三大法人與大額交易人未平倉")
def overview(_user: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.overview(db, get_market_data())


@router.get("/futures/{code}/history", response_model=FuturesHistory,
            summary="期貨近月連續日線（一般＋夜盤）；range：1M、3M、6M、1Y、MAX")
def futures_history(code: str, range: str = Query("3M"), _user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    return svc.futures_history(db, get_market_data(), code, range.upper())
