"""Per-user watchlist (自選) with quotes and a sparkline."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.api import serialize as ser
from forliosa.api.errors import ApiError, not_found, unprocessable
from forliosa.datapolicy import labels, tagged
from forliosa.ids import new_id
from forliosa.marketdata.base import HistoryResult, market_of_symbol
from forliosa.marketdata.service import MarketData
from forliosa.models import User, WatchlistItem
from forliosa.services.instruments import chart_candles, quote_out
from forliosa.timeutil import today_taipei

MAX_ITEMS = 200
SPARKLINE_DAYS = 20


def _items(db: Session, user: User) -> list[WatchlistItem]:
    return list(db.scalars(select(WatchlistItem).where(WatchlistItem.user_id == user.id)
                           .order_by(WatchlistItem.created_at, WatchlistItem.id)))


def _sparkline_histories(md: MarketData, symbols: list[str]) -> dict[str, HistoryResult]:
    """The sparklines' daily candles of every symbol in one batch (one archive query, not one per item)."""
    today = today_taipei()
    return md.histories(symbols, today - timedelta(days=45), today, backfill=True)


def _sparkline(md: MarketData, symbol: str, h: HistoryResult | None = None,
               events: list | None = None) -> tuple[list[dict], str, list[str]]:
    """The last 20 daily closes (there is no licensed intraday source, so never minute points)."""
    if h is None:
        h = _sparkline_histories(md, [symbol])[symbol]
    candles = chart_candles(md, symbol, h.candles, events)[-SPARKLINE_DAYS:]  # a US split: no cliff
    return [{"t": c.t.isoformat(), "price": ser.price(c.c)} for c in candles], "1d", tagged(h.source, "price")


def item_out(db: Session, md: MarketData, symbol: str, quotes: dict, history: HistoryResult | None = None,
             events: list | None = None) -> dict[str, Any]:
    info = md.instrument(symbol)
    q = quotes.get(symbol)
    spark, interval, spark_sources = _sparkline(md, symbol, history, events)
    return {
        "symbol": symbol,
        "name": info.name if info else symbol,
        "quote": quote_out(q) if q else None,
        "sparkline": spark,
        "sparkline_interval": interval,
        "sources": labels([*(tagged(q.source, "price") if q else []), *spark_sources]),
        "is_demo": bool(q.is_demo) if q else md.demo_data_allowed,
    }


def list_items(db: Session, user: User, md: MarketData) -> list[dict[str, Any]]:
    items = _items(db, user)
    if not items:
        return []
    symbols = [i.symbol for i in items]
    quotes = md.quotes(symbols)
    histories = _sparkline_histories(md, symbols)
    us = [s for s in symbols if market_of_symbol(s) == "US" and histories[s].candles]
    splits = md.corporate_events_many(us) if us else {}  # a US split folded into the sparkline (one batch)
    return [item_out(db, md, i.symbol, quotes, histories[i.symbol], splits.get(i.symbol)) for i in items]


def add(db: Session, user: User, md: MarketData, text: str) -> tuple[dict[str, Any], bool]:
    symbol = md.resolve(text)
    if symbol is None:
        raise unprocessable(f"找不到商品：{text}", code="unknown_symbol")
    existing = db.scalar(select(WatchlistItem).where(WatchlistItem.user_id == user.id,
                                                     WatchlistItem.symbol == symbol))
    created = existing is None
    if created:
        if len(_items(db, user)) >= MAX_ITEMS:
            raise ApiError(409, "conflict", f"自選最多 {MAX_ITEMS} 檔")
        db.add(WatchlistItem(id=new_id("wl"), user_id=user.id, symbol=symbol))
        db.commit()
    return item_out(db, md, symbol, md.quotes([symbol])), created


def remove(db: Session, user: User, md: MarketData, text: str) -> None:
    symbol = md.resolve(text) or text.strip().upper()
    item = db.scalar(select(WatchlistItem).where(WatchlistItem.user_id == user.id, WatchlistItem.symbol == symbol))
    if item is None:
        raise not_found("自選清單沒有這檔")
    db.delete(item)
    db.commit()


def watched_symbols(db: Session) -> list[str]:
    return sorted(set(db.scalars(select(WatchlistItem.symbol).distinct())))
