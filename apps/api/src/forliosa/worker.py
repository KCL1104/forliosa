"""Background worker: ``uv run python -m forliosa.worker``.

A small asyncio scheduler (no extra dependency) runs these jobs:

* ``after_close_refresh`` — 14:35 and 23:45 Taipei on trading days: refreshes the instrument master
  and writes the latest real closes of tracked symbols into ``prices_daily``.
* ``close_watch`` — on a trading day from 13:35 Taipei until 08:30 the next morning, every 15 minutes: the
  exchanges publish the day's closing prices at no fixed time (observed: late evening to early morning), so the worker
  asks each exchange's close dataset — a conditional request for its first kilobyte, 304 while unchanged — whether it
  has turned to that day. When one has, that market's archive group runs once (closes, PER/PBR, notices, automatic
  dividends) followed by ``after_close_refresh``. A market whose day is stored is not asked again; "stored" is read
  from ``dataset_status`` (``…/price``), so a restart neither repeats nor forgets anything, and a scheduled run that
  got there first counts too. Nothing is asked on a non-trading day or between 08:30 and 13:35.
* ``daily_archive`` — 08:10 (today's reference prices, notices), 14:40 (closes, PER/PBR, events, indices) and
  21:40 (margin, institutional flows, financial statements, company profiles and dividend resolutions, and the
  TAIFEX datasets: futures / options reports, 三大法人, large traders, put/call ratio, FX, margins when changed;
  and group ``cbc``: the central bank's USD/TWD closing rate, published the same afternoon — the first run
  backfills its whole history since 2008; and group ``nav``: the ETF NAVs of 證券期貨局's 證券投資信託基金每日淨值,
  published around 20:20 — the 08:10 run fetches the file again for NAVs posted after 21:40, since it only ever
  holds the latest NAV) on trading days: ``forliosa.archive`` (official open data only;
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
* ``session_purge`` — every day 04:50: deletes login sessions that have expired (``api.deps.purge_expired_sessions``).
  Requests already refuse an expired session; nothing else removes its row.
* ``news_refresh`` — every ``NEWS_REFRESH_MINUTES`` (45): media headlines for the tracked symbols (held,
  watched, or viewed in the last 3 days), one GDELT request per symbol spaced ≥ 5 s, backing off after a 429; AI
  web search fills gaps within the monthly budget; headlines older than 30 days are deleted
  (``forliosa.news.service.refresh``; also ``python -m forliosa.news refresh``). Metadata only.

* ``company_refresh`` — every hour at :35: the 「關於」 description of tracked symbols (``forliosa.services.company``):
  a zh.wikipedia excerpt found through Wikidata (one request at a time, monthly per company, paused 6 h after a 429),
  else an AI description from official facts (only when the facts changed).
* ``monthly_archive`` — the 10th and the 25th at 10:20: 董監事持股餘額明細 (company ↔ company links), TDCC 集保股東
  戶數 (2-22 / 2-23) and the ESG product text (archive group ``monthly``).

* ``market_summary`` — trading days 15:05, 18:05 and 22:05: the market page's shared AI summary of the session that
  just closed (``forliosa.ai.market_summary``; a finished day is not asked again, a failed or empty one at most four
  times). No model call without a key, with web search off or with ``AI_MARKET_SUMMARY_ENABLED=false``.
* ``daily_briefings`` — every day 22:20, 23:50, 06:10 and 08:20 (off with ``AI_DAILY_BRIEFING_ENABLED=false``): the
  每日收盤簡報 of users who switched it on (``forliosa.ai.briefing``) — once the official closes of the latest finished
  session are archived for both exchanges, one briefing per user and day (rule-computed facts plus, with a key and
  quota left, a few cited AI notes); briefings older than 30 days are deleted. The exchanges publish between the
  evening and the early morning, so the later slots catch what the earlier ones had to leave.
* ``price_backfill`` — only with PRICE_HISTORY_SOURCE=yahoo, in a loop of its own: every 10 minutes one batch of
  the history backfill (``forliosa.history_backfill``: five years of daily candles before our archive began, per
  symbol, held and watched symbols first) until every symbol has been asked once, then one look a day. A refusal
  from the source ends the batch and the next try waits 30 minutes, doubling up to 6 hours.

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
from forliosa.archive import (
    CLOSE_DATASETS,
    CLOSE_WATCH_SECONDS,
    Archiver,
    ClosePublication,
    close_archived,
    close_watch_day,
    default_fetcher,
    tracked_symbols,
)
from forliosa.config import DEFAULT_SESSION_SECRET, Settings, get_settings
from forliosa.datapolicy import allowed_sources
from forliosa.db import get_engine, session_factory
from forliosa.market_calendar import load_official_calendar
from forliosa.marketdata.base import ProviderUnavailable
from forliosa.marketdata.http import HttpFetcher
from forliosa.marketdata.service import LISTING_DATASETS, MarketData, get_market_data
from forliosa.models import Instrument, PriceDaily
from forliosa.timeutil import TAIPEI, is_tw_trading_day, now_taipei

log = logging.getLogger("forliosa.worker")

# Archive groups per run (forliosa.archive.JOB_GROUPS).
EVENING_GROUPS = ["twse", "tpex", "companies", "financials", "taifex", "cbc", "nav"]
# 08:10: today's reference prices and notices, plus a second look at the NAV file (it only holds the latest NAV of each
# fund, so one posted after the 21:40 run would otherwise be lost when the next evening's file replaces it).
MORNING_GROUPS = ["twse", "tpex", "nav"]
PRICE_BACKFILL_SECONDS = 600
PRICE_BACKFILL_REFUSED_SECONDS = 1800
WEEKLY_GROUPS = ["tdcc", "weekly"]
MONTHLY_GROUPS = ["monthly"]
MONTHLY_DAYS = (10, 25)
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
        # Yesterday's slots count too (still within the 3-hour window): a 23:45 slot the loop reached only after
        # midnight (a long news batch held it) used to be skipped for good, because the slot was built from today's
        # date (2026-11-14 review). ``only_if`` is asked about the slot, so a trading-day guard is about its day.
        for day in (now.date() - timedelta(days=1), now.date()):
            for t in times:
                slot = datetime.combine(day, t, TAIPEI)
                if now >= slot and (last is None or last < slot) and now - slot < timedelta(hours=3) and only_if(slot):
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
    # Never overwrite a row the archive wrote from an official source: a provider-chain quote can carry a merged label
    # ("twse-openapi+shioaji-data") that commercial mode does not serve, which hid that day from history and quotes,
    # and a close-only quote wiped open/high/low/volume (2026-11-14 review).
    official = allowed_sources("commercial")
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "date"],
        set_={k: stmt.excluded[k] for k in ("open", "high", "low", "close", "volume", "source")},
        where=PriceDaily.source.not_in(official),
    )
    db.execute(stmt)
    db.commit()
    return len(rows)


def refresh_instruments(db: Session, md: MarketData) -> int:
    """Cache the providers' instrument lists in ``instruments``. The archive's own listings are not written back: its
    ETF rows are already there (the price jobs keep them current) and SEC's tickers stay in ``sec_tickers``."""
    master = md.master()
    existing = {i.symbol: i for i in db.scalars(select(Instrument))}
    for sym, info in master.items():
        if info.source in LISTING_DATASETS:
            continue
        row = existing.get(sym) or Instrument(symbol=sym)
        row.code, row.name, row.market, row.type = info.code, info.name, info.market, info.type
        row.currency, row.industry = info.currency, info.industry
        db.add(row)
    db.commit()
    return len(master)


class Worker:
    def __init__(self, md: MarketData | None = None, now_fn: Callable[[], datetime] = now_taipei,
                 fetcher_fn: Callable[[], HttpFetcher] = default_fetcher):
        self.md = md or get_market_data()
        self.now_fn = now_fn  # the clock of the archive runs and the close watch (tests inject one)
        self.fetcher_fn = fetcher_fn  # the HTTP client of the archive runs and the close watch
        self._close_publication: ClosePublication | None = None
        self._stop = asyncio.Event()
        from forliosa.services.channels import TelegramPoller

        self.telegram = TelegramPoller()
        self.jobs = [
            Job("after_close_refresh", daily_at(time(14, 35), time(23, 45),
                                                only_if=lambda n: is_tw_trading_day(n.date())),
                self.after_close_refresh),
            Job("close_watch", every(CLOSE_WATCH_SECONDS, only_if=lambda n: close_watch_day(n) is not None),
                self.close_watch),
            Job("daily_archive_morning", daily_at(time(8, 10), only_if=lambda n: is_tw_trading_day(n.date())),
                lambda: self.archive(MORNING_GROUPS)),
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
            Job("session_purge", daily_at(time(4, 50)), self.session_purge),
            Job("monthly_archive", daily_at(time(10, 20), only_if=lambda n: n.day in MONTHLY_DAYS),
                lambda: self.archive(MONTHLY_GROUPS)),
        ]
        settings = get_settings()
        if settings.news_enabled:
            self.jobs.append(Job("news_refresh", every(settings.news_refresh_minutes * 60), self.news_refresh))
        if settings.company_descriptions_enabled:
            self.jobs.append(Job("company_refresh", daily_at(*(time(h, 35) for h in range(24))), self.company_refresh))
        # History backfill (PRICE_HISTORY_SOURCE=yahoo): its own loop, a batch every 10 minutes until every symbol
        # has been asked once; then one look a day for newly listed symbols.
        self._backfill_wait_until: datetime | None = None
        self._backfill_refusals = 0
        # Market page: the shared AI summary of the session that just closed (no model call without a key).
        if settings.ai_daily_briefing_enabled:
            self.jobs.append(Job("daily_briefings", daily_at(time(22, 20), time(23, 50), time(6, 10), time(8, 20)),
                                 self.daily_briefings))
        if settings.ai_market_summary_enabled:
            self.jobs.append(Job("market_summary", daily_at(time(15, 5), time(18, 5), time(22, 5),
                                                             only_if=lambda n: is_tw_trading_day(n.date())),
                                 self.market_summary))
        if settings.price_history_source == "yahoo":
            self.jobs.append(Job("price_backfill", every(PRICE_BACKFILL_SECONDS), self.price_backfill,
                                 background=True))

    async def archive(self, groups: list[str]) -> None:
        def run() -> list:
            with session_factory()() as db:
                return Archiver(db, self.fetcher_fn(), self.md.policy, now_fn=self.now_fn).run(groups)

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

    async def close_watch(self) -> None:
        """One check of the close watch (see the module docstring). Whether a market still has to be asked is read
        from the database every time; the only thing kept in memory is the validators that make the next request a
        304. A market that cannot be reached is simply asked again at the next check."""
        day = close_watch_day(self.now_fn())
        if day is None:
            return

        def waiting() -> list:
            with session_factory()() as db:
                return [d for d in CLOSE_DATASETS if not close_archived(db, d, day)]

        if self._close_publication is None:
            self._close_publication = ClosePublication(self.fetcher_fn())
        refreshed = False
        for dataset in await asyncio.to_thread(waiting):
            try:
                published = await asyncio.to_thread(self._close_publication.data_date, dataset)
            except ProviderUnavailable as exc:
                log.warning("close watch: %s not checked: %s", dataset.market, exc)
                continue
            if published is None or published < day:
                continue
            log.info("close watch: %s has published the closes of %s", dataset.market, day)
            await self.archive([dataset.group])
            refreshed = True
        if refreshed:
            await self.after_close_refresh()

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

    async def session_purge(self) -> None:
        from forliosa.api.deps import purge_expired_sessions

        def run() -> int:
            with session_factory()() as db:
                return purge_expired_sessions(db)

        n = await asyncio.to_thread(run)
        if n:
            log.info("sessions: %d expired login sessions deleted", n)

    async def news_refresh(self) -> None:
        from forliosa.news.service import refresh

        def run():
            with session_factory()() as db:
                # A batch never holds the scheduler for longer than the refresh interval.
                return refresh(db, self.md, deadline_seconds=get_settings().news_refresh_minutes * 60 * 0.8)

        await asyncio.to_thread(run)

    async def price_backfill(self) -> None:
        """One batch of the history backfill. A refusal from the source ends the batch; the next try waits 30
        minutes, doubling up to 6 hours — the same client, never a workaround."""
        from forliosa import history_backfill as hb
        from forliosa.marketdata import yahoo_history

        now = self.now_fn()
        if self._backfill_wait_until is not None and now < self._backfill_wait_until:
            return
        years = get_settings().price_history_years

        def run():
            with session_factory()() as db:
                return hb.run_batch(db, yahoo_history.fetcher(), years,
                                    deadline_seconds=PRICE_BACKFILL_SECONDS * 0.8)

        res = await asyncio.to_thread(run)
        if res.blocked:
            self._backfill_refusals += 1
            wait = min(PRICE_BACKFILL_REFUSED_SECONDS * 2 ** (self._backfill_refusals - 1), 6 * 3600)
            self._backfill_wait_until = now + timedelta(seconds=wait)
        else:
            self._backfill_refusals = 0
            self._backfill_wait_until = now + timedelta(days=1) if res.remaining <= 0 else None
        if res.asked or res.blocked:
            log.info("price backfill: asked %d symbols, stored %d (%d rows), %d left%s", res.asked, res.stored,
                     res.rows, res.remaining, "; the source refused, waiting" if res.blocked else "")

    async def daily_briefings(self) -> None:
        from forliosa.ai import briefing

        def run():
            with session_factory()() as db:
                return briefing.run(db, self.md, now=self.now_fn())

        res = await asyncio.to_thread(run)
        if res.written or res.purged:
            log.info("daily briefings %s: %d written (%d with AI notes), %d old ones deleted", res.day, res.written,
                     res.with_points, res.purged)

    async def market_summary(self) -> None:
        from forliosa.ai import market_summary

        def run():
            with session_factory()() as db:
                return market_summary.refresh(db)

        row = await asyncio.to_thread(run)
        if row is not None:
            log.info("market summary %s: %s", row.trading_day, row.status)

    async def company_refresh(self) -> None:
        from forliosa.services.company import refresh

        def run():
            with session_factory()() as db:
                return refresh(db, self.md)

        await asyncio.to_thread(run)

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
