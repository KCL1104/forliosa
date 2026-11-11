"""Background worker: ``uv run python -m forliosa.worker``.

A small asyncio scheduler (no extra dependency) runs these jobs:

* ``intraday_quotes`` — every 60 s during 09:00–13:30 Asia/Taipei on trading days: polls quotes for
  the union of every user's holdings (batched, rate-limited by the providers) and keeps them warm
  in the MarketData cache. TODO(M2+): publish to Redis so every API replica's SSE stream shares them.
* ``after_close_refresh`` — 14:35 and 23:45 Taipei on trading days: refreshes the instrument master
  and writes the latest real closes into ``prices_daily`` (shioaji-data publishes around 23:15).
* ``weekly_tdcc_archive`` — Saturday 10:00: placeholder; TDCC 集保股權分散 is published weekly
  and only the latest week is downloadable, so it must be archived every week (M2+).

AI jobs (post-market reports, portfolio health checks, group weekly digests) arrive in M4.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from forliosa.db import get_engine, session_factory
from forliosa.marketdata.service import MarketData, get_market_data
from forliosa.models import HoldingSnapshot, Instrument, PriceDaily, Transaction
from forliosa.timeutil import TAIPEI, is_tw_market_open, is_tw_trading_day, now_taipei

log = logging.getLogger("forliosa.worker")


@dataclass
class Job:
    name: str
    due: Callable[[datetime, datetime | None], bool]
    run: Callable[[], Awaitable[None]]
    last_run: datetime | None = field(default=None)


def every(seconds: int, only_if: Callable[[datetime], bool] = lambda _now: True):
    def due(now: datetime, last: datetime | None) -> bool:
        return only_if(now) and (last is None or (now - last).total_seconds() >= seconds)

    return due


def daily_at(*times: time, only_if: Callable[[datetime], bool] = lambda _now: True):
    """Due once after each listed Taipei time of day."""

    def due(now: datetime, last: datetime | None) -> bool:
        if not only_if(now):
            return False
        for t in times:
            slot = datetime.combine(now.date(), t, TAIPEI)
            if now >= slot and (last is None or last < slot) and now - slot < timedelta(hours=3):
                return True
        return False

    return due


def weekly_at(weekday: int, at: time):
    def due(now: datetime, last: datetime | None) -> bool:
        if now.weekday() != weekday:
            return False
        slot = datetime.combine(now.date(), at, TAIPEI)
        return now >= slot and (last is None or last < slot)

    return due


def held_symbols(db: Session) -> list[str]:
    syms = set(db.scalars(select(Transaction.symbol).where(Transaction.symbol.is_not(None)).distinct()))
    syms |= set(db.scalars(select(HoldingSnapshot.symbol).distinct()))
    return sorted(s for s in syms if s)


def upsert_closes(db: Session, md: MarketData, symbols: list[str]) -> int:
    """Store the latest *real* close of each symbol in prices_daily (demo prices are never stored)."""
    quotes = md.quotes(symbols, use_cache=False)
    rows = []
    for sym, q in quotes.items():
        if q.is_demo or q.price is None or q.trade_date is None:
            continue
        rows.append({"symbol": sym, "date": q.trade_date, "open": q.open, "high": q.high, "low": q.low,
                     "close": q.price, "volume": q.volume, "source": q.source[:32]})
    if not rows:
        return 0
    dialect = get_engine().dialect.name
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    stmt = insert(PriceDaily).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "date"],
        set_={k: stmt.excluded[k] for k in ("open", "high", "low", "close", "volume", "source")},
    )
    db.execute(stmt)
    db.commit()
    return len(rows)


def refresh_instruments(db: Session, md: MarketData) -> int:
    master = md.master()
    existing = {i.symbol: i for i in db.scalars(select(Instrument))}
    for sym, info in master.items():
        row = existing.get(sym) or Instrument(symbol=sym)
        row.code, row.name, row.market, row.type = info.code, info.name, info.market, info.type
        row.currency, row.industry = info.currency, info.industry
        db.add(row)
    db.commit()
    return len(master)


class Worker:
    def __init__(self, md: MarketData | None = None):
        self.md = md or get_market_data()
        self._stop = asyncio.Event()
        self.jobs = [
            Job("intraday_quotes", every(60, only_if=is_tw_market_open), self.intraday_quotes),
            Job("after_close_refresh", daily_at(time(14, 35), time(23, 45),
                                                only_if=lambda n: is_tw_trading_day(n.date())),
                self.after_close_refresh),
            Job("weekly_tdcc_archive", weekly_at(5, time(10, 0)), self.weekly_tdcc_archive),
        ]

    async def intraday_quotes(self) -> None:
        with session_factory()() as db:
            symbols = held_symbols(db)
        if symbols:
            quotes = await asyncio.to_thread(self.md.quotes, symbols, False)
            log.info("intraday: %d/%d quotes refreshed", len(quotes), len(symbols))

    async def after_close_refresh(self) -> None:
        with session_factory()() as db:
            n_inst = await asyncio.to_thread(refresh_instruments, db, self.md)
            symbols = held_symbols(db)
            n_px = await asyncio.to_thread(upsert_closes, db, self.md, symbols) if symbols else 0
        log.info("after close: %d instruments, %d closes stored", n_inst, n_px)

    async def weekly_tdcc_archive(self) -> None:
        log.info("TDCC 集保股權分散 archive: not implemented yet (M2+)")

    def stop(self) -> None:
        self._stop.set()

    async def run(self, tick_seconds: float = 20.0) -> None:
        log.info("worker started: %s", ", ".join(j.name for j in self.jobs))
        while not self._stop.is_set():
            now = now_taipei()
            for job in self.jobs:
                if job.due(now, job.last_run):
                    job.last_run = now
                    try:
                        await job.run()
                    except Exception:  # keep the scheduler alive
                        log.exception("job %s failed", job.name)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=tick_seconds)
        log.info("worker stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    worker = Worker()
    loop = asyncio.new_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows
            loop.add_signal_handler(sig, worker.stop)
    loop.run_until_complete(worker.run())


if __name__ == "__main__":
    main()
