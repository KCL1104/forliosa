"""Stock page endpoints: overview, intraday, chips, financials, events, news, position, why."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from forliosa.ai.schemas import AIWhy
from forliosa.ai.why import enhance_why
from forliosa.api.deps import current_user
from forliosa.api.schemas import (
    Chips,
    Financials,
    Intraday,
    NewsItem,
    Overview,
    Position,
    PositionHistory,
    StockEvent,
)
from forliosa.db import get_db
from forliosa.marketdata.service import get_market_data
from forliosa.models import User
from forliosa.services import stock as svc

router = APIRouter(prefix="/instruments/{symbol}", tags=["stock"])


@router.get("/overview", response_model=Overview, summary="關鍵數據：開高低、參考價、漲跌停、本益比、52 週…")
def overview(symbol: str, _user: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.overview(db, get_market_data(), symbol)


@router.get("/intraday", response_model=Intraday, summary="今日分時（目前沒有授權的盤中來源：points 一律為空）")
def intraday(symbol: str, _user: User = Depends(current_user)):
    return svc.intraday(get_market_data(), symbol)


@router.get("/chips", response_model=Chips, summary="籌碼：三大法人、融資融券、外資持股、集保大戶")
def chips(symbol: str, range: str = Query("3M"), _user: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.chips(db, get_market_data(), symbol, range.upper())


@router.get("/financials", response_model=Financials, summary="財務報表（季／年）")
def financials(symbol: str, period: str = Query("quarterly"), _user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    return svc.financials(db, get_market_data(), symbol, period.lower())


@router.get("/events", response_model=list[StockEvent], summary="事件：除權息、財報、重大訊息、注意／處置…")
def events(symbol: str, mine: bool = Query(False), user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    return svc.events(db, get_market_data(), user, symbol, mine)


@router.get("/news", response_model=list[NewsItem], summary="公告：重大訊息與證交所新聞（官方開放資料，標題＋連結）")
def news(symbol: str, _user: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.news(db, get_market_data(), symbol)


@router.get("/position", response_model=Position | None, summary="我的部位（未持有回 null）")
def position(symbol: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.position(db, get_market_data(), user, symbol)


@router.get("/position/history", response_model=PositionHistory,
            summary="我的交易歷史：已出清的回合與所有買賣點（未持有也會回傳）")
def position_history(symbol: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.position_history(db, get_market_data(), user, symbol)


@router.get("/why", response_model=AIWhy, summary="為什麼漲跌（規則判斷，只在異常時 show=true；可選 AI 一句話）")
def why(symbol: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    md = get_market_data()
    return enhance_why(db, md, svc.why(db, md, symbol), user_id=user.id)
