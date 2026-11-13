"""The market page: indices, the day's shared AI summary, sector moves, rankings, material information."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from forliosa.api.deps import current_user
from forliosa.api.schemas import MarketOverview
from forliosa.db import get_db
from forliosa.marketdata.service import get_market_data
from forliosa.models import User
from forliosa.services import market_overview as svc

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/overview", response_model=MarketOverview,
            summary="市場：指數、當日 AI 收盤整理、類股漲跌、漲跌與成交量排行、重大訊息（都是收盤後的官方資料）")
def overview(_user: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.overview(db, get_market_data())
