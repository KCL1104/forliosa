"""Watchlist (自選): per user, with quotes and sparklines."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from forliosa.api.deps import current_user
from forliosa.api.schemas import WatchlistEntry, WatchlistIn
from forliosa.db import get_db
from forliosa.marketdata.service import get_market_data
from forliosa.models import User
from forliosa.services import watchlist as svc

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchlistEntry])
def list_watchlist(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.list_items(db, user, get_market_data())


@router.post("", response_model=WatchlistEntry, status_code=201,
             summary="加入自選（已在清單中回 200）")
def add_watchlist(body: WatchlistIn, response: Response, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    item, created = svc.add(db, user, get_market_data(), body.symbol)
    if not created:
        response.status_code = 200
    return item


@router.delete("/{symbol}", status_code=204, response_class=Response)
def remove_watchlist(symbol: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    svc.remove(db, user, get_market_data(), symbol)
    return Response(status_code=204)
