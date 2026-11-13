"""Instruments, quotes, history, valuation, revenue, dividends and the SSE quote stream."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from forliosa.api.deps import current_user
from forliosa.api.errors import not_found, unprocessable
from forliosa.api.schemas import (
    DividendRecord,
    History,
    Instrument,
    InstrumentDetail,
    MonthlyRevenue,
    Quote,
    Valuation,
)
from forliosa.config import get_settings
from forliosa.marketdata.service import get_market_data
from forliosa.models import User
from forliosa.services import instruments as svc

router = APIRouter(tags=["market"])

MAX_SYMBOLS = 100


def _symbols(raw: str) -> list[str]:
    md = get_market_data()
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise unprocessable("請提供商品代號")
    if len(parts) > MAX_SYMBOLS:
        raise unprocessable(f"一次最多 {MAX_SYMBOLS} 檔")
    out = []
    for p in parts:
        sym = md.resolve(p)
        if sym is not None:
            out.append(sym)
    return list(dict.fromkeys(out))


@router.get("/instruments/search", response_model=list[Instrument])
def search(q: str = Query(min_length=1, max_length=50), _user: User = Depends(current_user)):
    return [svc.instrument_out(i) for i in get_market_data().search(q, 20)]


@router.get("/instruments/{symbol}", response_model=InstrumentDetail)
def instrument_detail(symbol: str, _user: User = Depends(current_user)):
    return svc.detail(get_market_data(), symbol)


@router.get("/instruments/{symbol}/quote", response_model=Quote)
def instrument_quote(symbol: str, _user: User = Depends(current_user)):
    md = get_market_data()
    info = svc.require_instrument(md, symbol)
    q = md.quote(info.symbol)
    if q is None:
        raise not_found("沒有報價")
    return svc.quote_out(q)


@router.get("/quotes", response_model=list[Quote])
def batch_quotes(symbols: str = Query(max_length=2000), _user: User = Depends(current_user)):
    md = get_market_data()
    syms = _symbols(symbols)
    quotes = md.quotes(syms)
    return [svc.quote_out(quotes[s]) for s in syms if s in quotes]


@router.get("/instruments/{symbol}/history", response_model=History)
def instrument_history(symbol: str, range: str = Query("1M"), _user: User = Depends(current_user)):
    return svc.history(get_market_data(), symbol, range.upper())


@router.get("/instruments/{symbol}/valuation", response_model=Valuation)
def instrument_valuation(symbol: str, range: str = Query("5Y"), _user: User = Depends(current_user)):
    return svc.valuation(get_market_data(), symbol, range.upper())


@router.get("/instruments/{symbol}/revenue", response_model=list[MonthlyRevenue])
def instrument_revenue(symbol: str, _user: User = Depends(current_user)):
    return svc.revenue(get_market_data(), symbol)


@router.get("/instruments/{symbol}/dividends", response_model=list[DividendRecord])
def instrument_dividends(symbol: str, _user: User = Depends(current_user)):
    return svc.dividends(get_market_data(), symbol)


@router.get("/stream/quotes", summary="SSE：每隔幾秒推送報價（事件名 quote）",
            response_class=StreamingResponse)
async def stream_quotes(request: Request, symbols: str = Query(max_length=2000),
                        interval: float | None = Query(default=None, ge=1, le=60),
                        once: bool = Query(default=False, description="送出一輪後結束（測試用）"),
                        _user: User = Depends(current_user)):
    syms = _symbols(symbols)
    md = get_market_data()
    every = interval or get_settings().stream_interval_seconds

    async def events():
        yield f"retry: {int(every * 1000)}\n\n"
        while True:
            quotes = await run_in_threadpool(md.live_quotes, syms)
            for s in syms:
                q = quotes.get(s)
                if q is not None:
                    data = json.dumps(svc.quote_out(q), ensure_ascii=False)
                    yield f"event: quote\ndata: {data}\n\n"
            if once or await request.is_disconnected():
                break
            await asyncio.sleep(every)
            if await request.is_disconnected():
                break

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
