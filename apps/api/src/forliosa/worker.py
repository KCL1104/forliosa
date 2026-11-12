"""Background worker: ``uv run python -m forliosa.worker``.

A small asyncio scheduler (no extra dependency) runs these jobs:

* ``after_close_refresh`` — 14:35 and 23:45 Taipei on trading days: refreshes the instrument master
  and writes the latest real closes of tracked symbols into ``prices_daily``.
* ``daily_archive`` — 08:10 (today's reference prices, notices), 14:40 (closes, PER/PBR, events, indices) and
  21:40 (margin, institutional flows, financial statements, company profiles and dividend resolutions, and the
  TAIFEX datasets: futures / options reports, 三大法人, large traders, put/call ratio, FX, margins when changed;
  and group ``cbc``: the central bank's USD/TWD closing rate, published the same afternoon — the first run
  backfills its whole history since 2008) on trading days: ``forliosa.archive`` (official open data only;
  idempotent upserts). The official TWSE calendar is reloaded after each run. TAIFEX books the night session to
  the next trading day, so one evening run covers it (no early-morning job).
* ``weekly_archive`` — Saturday 10:00: TDCC 集保股權分散 (only the latest week is downloadable), TAIFEX final
  settlement prices and SSF / SSO lists, and the stale-endpoint check (twtazu_od, t187ap09_L).
* ``sec_archive`` — every day 07:50 Taipei (after the US close, when the day's 8-Ks and 10-Qs are in): SEC EDGAR
  company facts and filings of every tracked US stock (``forliosa.archive`` group ``sec``; skipped without
  SEC_CONTACT_EMAIL). Requests also refresh a stale company on demand.
* ``auto_dividends`` — after each archive run with the ``twse`` / ``tpex`` groups (08:10 covers today's ex-dates):
  ``forliosa.services.auto_dividends.sync_all_users`` books, corrects or removes automatic dividends.
* ``ai_retention`` — every day 04:20: deletes AI threads, messages and drafts whose last activity is older than
  ``AI_RETENTION_DAYS`` (30; ``forliosa.ai.retention``, also a CLI). Usage records are kept.
* ``ai_analyst_purge`` — every hour at :05: deletes shared analyst views 24 hours after they were created
  (``forliosa.ai.analyst.purge_expired``; reads purge them too, so an expired entry is never shown).
* ``group_push`` — every minute: queues group-channel pushes of trades and sends what is due
  (``forliosa.services.notifications``: 15 minutes after a trade was created, re-checked against the share settings,
  up to 5 attempts with exponential backoff).
* ``telegram_poll`` — every 20 seconds while ``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_BOT_USERNAME`` are set: Telegram
  ``getUpdates`` (``/link`` codes, supergroup migration, the bot being removed; there is no public webhook endpoint).
  It runs in its own loop (``Job.background``): anyone can message the bot, so a flood of messages must not delay
  the other jobs, and a long archive run must not leave ``/link`` codes waiting until they expire.
* ``group_digests`` — Saturday 20:00 Taipei (catch-up until Sunday ends): the weekly AI digest of every group for the
  week Monday–Friday that just ended, sent as one Message Batches request (``forliosa.services.digests``);
  ``group_digest_poll`` (every 5 minutes) collects the results, falls back to normal calls, and queues the pushes.
* ``sharing_retention`` — every day 04:35: finished push rows after 30 days, Telegram link codes a day after they
  expired, digests 26 weeks after their week.

There is no intraday polling: the former MIS job was removed (2026-11-12) because TWSE's website terms
forbid automated downloads from mis.twse.com.tw and real-time / delayed quotes need a paid licence.
``/instruments/{symbol}/intraday`` returns no points until a licensed source is added.

AI jobs pick their API key slot with ``KeyPool.call`` (most headroom first), like the "why" sentence does; a
Message Batches batch stays on the slot (workspace) that created it.
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

from forliosa import logredact
from forliosa.archive import Archiver, default_fetcher, tracked_symbols
from forliosa.config import DEFAULT_SESSION_SECRET, Settings, get_settings
from forliosa.db import get_engine, session_factory
from forliosa.market_calendar import load_official_calendar
from forliosa.marketdata.service import MarketData, get_market_data
from forliosa.models import Instrument, PriceDaily
from forliosa.timeutil import TAIPEI, is_tw_trading_day, now_taipei

log = logging.getLogger("forliosa.worker")

# Archive groups per run (forliosa.archive.JOB_GROUPS).
EVENING_GROUPS = ["twse", "tpex", "companies", "financials", "taifex", "cbc"]
WEEKLY_GROUPS = ["tdcc", "weekly"]
SEC_GROUPS = ["sec"]


@dataclass
class Job:
    name: str
    due: Callable[[datetime, datetime | None], bool]
    run: Callable[[], Awaitable[None]]
    last_run: datetime | None = field(default=None)
    background: bool = False  # its own loop: never holds up the other jobs, and they never hold it up


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


def weekend_evening(at: time):
    """Due once from Saturday ``at`` (Taipei) until Sunday ends — a worker down on Saturday evening catches up."""

    def due(now: datetime, last: datetime | None) -> bool:
        if now.weekday() not in (5, 6):
            return False
        slot = datetime.combine(now.date() - timedelta(days=now.weekday() - 5), at, TAIPEI)
        return now >= slot and (last is None or last < slot)

    return due


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
        from forliosa.services.channels import TelegramPoller

        self.telegram = TelegramPoller()
        self.jobs = [
            Job("after_close_refresh", daily_at(time(14, 35), time(23, 45),
                                                only_if=lambda n: is_tw_trading_day(n.date())),
                self.after_close_refresh),
            Job("daily_archive_morning", daily_at(time(8, 10), only_if=lambda n: is_tw_trading_day(n.date())),
                lambda: self.archive(["twse", "tpex"])),
            Job("daily_archive_close", daily_at(time(14, 40), only_if=lambda n: is_tw_trading_day(n.date())),
                lambda: self.archive(["twse", "tpex"])),
            Job("daily_archive_evening", daily_at(time(21, 40), only_if=lambda n: is_tw_trading_day(n.date())),
                lambda: self.archive(EVENING_GROUPS)),
            Job("weekly_archive", weekly_at(5, time(10, 0)), self.weekly_archive),
            Job("sec_archive", daily_at(time(7, 50)), lambda: self.archive(SEC_GROUPS)),
            Job("ai_retention", daily_at(time(4, 20)), self.ai_retention),
            Job("ai_analyst_purge", daily_at(*(time(h, 5) for h in range(24))), self.ai_analyst_purge),
            Job("group_push", every(60), self.group_push),
            Job("telegram_poll", every(20), self.telegram_poll, background=True),
            Job("group_digests", weekend_evening(time(20, 0)), self.group_digests),
            Job("group_digest_poll", every(300), self.group_digest_poll),
            Job("sharing_retention", daily_at(time(4, 35)), self.sharing_retention),
        ]

    async def archive(self, groups: list[str]) -> None:
        def run() -> list:
            with session_factory()() as db:
                return Archiver(db, default_fetcher(), self.md.policy).run(groups)

        results = await asyncio.to_thread(run)
        with session_factory()() as db:
            load_official_calendar(db)
        failed = [r.name for r in results if r.error]
        log.info("archive %s: %d datasets, %d failed %s", ",".join(groups), len(results), len(failed), failed or "")
        if {"twse", "tpex"} & set(groups):  # ex-dividend notices are refreshed with these groups
            await self.auto_dividends()

    async def auto_dividends(self) -> None:
        from forliosa.services.auto_dividends import sync_all_users

        res = await asyncio.to_thread(sync_all_users, session_factory(), self.md)
        log.info("automatic dividends: %d created, %d updated, %d deleted", res.created, res.updated, res.deleted)

    async def after_close_refresh(self) -> None:
        with session_factory()() as db:
            n_inst = await asyncio.to_thread(refresh_instruments, db, self.md)
            symbols = tracked_symbols(db)
            n_px = await asyncio.to_thread(upsert_closes, db, self.md, symbols) if symbols else 0
        log.info("after close: %d instruments, %d closes stored", n_inst, n_px)

    async def weekly_archive(self) -> None:
        await self.archive(WEEKLY_GROUPS)

    async def ai_retention(self) -> None:
        from forliosa.ai import retention

        await asyncio.to_thread(retention.run)

    async def ai_analyst_purge(self) -> None:
        from forliosa.ai.analyst import purge_expired

        def run() -> int:
            with session_factory()() as db:
                return purge_expired(db)

        n = await asyncio.to_thread(run)
        if n:
            log.info("analyst views: %d expired entries deleted", n)

    async def group_push(self) -> None:
        from forliosa.services import notifications

        def run() -> tuple[int, int]:
            with session_factory()() as db:
                return notifications.enqueue_trades(db), notifications.send_due(db, self.md)

        queued, handled = await asyncio.to_thread(run)
        if queued or handled:
            log.info("group push: %d queued, %d handled", queued, handled)

    async def telegram_poll(self) -> None:
        def run() -> int:
            with session_factory()() as db:
                return self.telegram.poll(db)

        await asyncio.to_thread(run)

    async def group_digests(self) -> None:
        from forliosa.services import digests

        def run() -> int:
            with session_factory()() as db:
                digests.create_week(db, self.md)
                return digests.submit(db)

        await asyncio.to_thread(run)

    async def group_digest_poll(self) -> None:
        from forliosa.services import digests

        def run() -> int:
            with session_factory()() as db:
                digests.submit(db)
                return digests.poll(db)

        n = await asyncio.to_thread(run)
        if n:
            log.info("group digests: %d finished", n)

    async def sharing_retention(self) -> None:
        from forliosa.services import digests, notifications

        def run() -> int:
            with session_factory()() as db:
                return notifications.purge_old(db) + digests.purge_old(db)

        n = await asyncio.to_thread(run)
        if n:
            log.info("sharing retention: %d rows deleted", n)

    def stop(self) -> None:
        self._stop.set()

    @staticmethod
    async def _run_job(job: Job) -> None:
        try:
            await job.run()
        except Exception:  # keep the scheduler alive
            log.exception("job %s failed", job.name)

    async def _wait(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)

    async def _loop(self, jobs: list[Job], tick_seconds: float) -> None:
        """Run the due ``jobs`` one after another, every ``tick_seconds``, until stopped."""
        while not self._stop.is_set():
            now = now_taipei()
            for job in jobs:
                if job.due(now, job.last_run):
                    job.last_run = now
                    await self._run_job(job)
            await self._wait(tick_seconds)

    async def run(self, tick_seconds: float = 20.0) -> None:
        """The scheduled jobs in one loop; each ``background`` job in a loop of its own (jobs run in threads, so the
        loops really run side by side)."""
        log.info("worker started: %s", ", ".join(j.name for j in self.jobs))
        with session_factory()() as db:
            load_official_calendar(db)
        side = [asyncio.create_task(self._loop([j], tick_seconds), name=j.name) for j in self.jobs if j.background]
        await self._loop([j for j in self.jobs if not j.background], tick_seconds)
        await asyncio.gather(*side, return_exceptions=True)
        log.info("worker stopped")


def check_worker_settings(settings: Settings) -> None:
    """Group push decrypts Discord webhooks with a key derived from SESSION_SECRET: in production the worker must have
    the API's secret (with the default one every webhook would look undecryptable and its channel be disabled)."""
    if settings.forliosa_env == "prod" and settings.session_secret == DEFAULT_SESSION_SECRET:
        raise RuntimeError("SESSION_SECRET must be set on the worker too (the same value as the api service)")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logredact.install()  # webhook and bot-token URLs never reach the log
    check_worker_settings(get_settings())
    worker = Worker()
    loop = asyncio.new_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows
            loop.add_signal_handler(sig, worker.stop)
    loop.run_until_complete(worker.run())


if __name__ == "__main__":
    main()
