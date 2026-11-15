"""US end-of-day prices: Databento EQUS.SUMMARY bars stored in ``prices_daily`` (source ``databento-equs``).

產品負責人 2026-11-15 (docs/research/us-market-data.md): US closes come from Databento, an hour after the US close.
Off unless US_PRICE_SOURCE=databento and DATABENTO_API_KEY are set (``Settings.us_prices_enabled``).

Which symbols: every US symbol in a ledger or a watchlist, plus SPY, DIA and ONEQ for the market page's US row
(``MARKET_ETFS``; shown as ETFs, never as the indices they track).

Two jobs (``forliosa.worker``):

* :func:`update` — after each US session: the newest sessions of every symbol whose history is in. Databento posts a
  session's summary some time after the close; the worker asks from an hour after the close (17:00 New York) and then
  hourly until the session is stored. Whether there is anything new is read from ``metadata.get_dataset_range``
  (free); bars are bought only when there is.
* :func:`backfill` — a symbol not seen before gets its whole history from 2024-07-01 (where EQUS.SUMMARY begins) in
  one request per 100 symbols; the worker looks every 10 minutes, so a stock added to a watchlist has its chart
  within minutes. Progress is one ``price_backfill`` row per symbol (shared with the Yahoo backfill, told apart by
  ``source``).

Prices are unadjusted, like the Taiwan archive: the ledger values holdings with the close of the day and the
splits users record. Databento's split and dividend data may not be redistributed, so there is none here.
"""

from __future__ import annotations

import logging
import threading
import time as clock
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy import update as sql_update
from sqlalchemy.orm import Session

from forliosa.archive import tracked_symbols, upsert
from forliosa.marketdata import databento
from forliosa.marketdata.base import ProviderUnavailable
from forliosa.marketdata.http import HttpFetcher, HttpStatusError
from forliosa.models import DatasetStatus, PriceBackfill, PriceDaily
from forliosa.timeutil import TAIPEI, now_utc

log = logging.getLogger(__name__)

SOURCE = "databento-equs"  # prices_daily.source / price_backfill.source (String(32))
STATUS_KEY = f"{SOURCE}/price"  # dataset_status: the newest session stored
MARKET_ETFS = ("SPY", "DIA", "ONEQ")  # the market page's US row: S&P 500, Dow Jones and Nasdaq Composite ETFs
# The performance page's US benchmark option (VOO, apps/web lib/labels.ts BENCHMARK_OPTIONS): fetched whether or not
# anyone holds it, so picking it always has closes (2026-11-15 review)
BENCHMARK_ETFS = ("VOO",)
FIRST_DAY = databento.FIRST_DAY
# Re-read the last few sessions on every update: a late correction to a summary replaces the stored bar.
OVERLAP_DAYS = 5
NOT_FOUND_RETRY = timedelta(days=7)  # a ticker Databento did not know (a new listing?) is asked again a week later
ERROR_RETRY = timedelta(hours=1)
REFUSALS = (401, 402, 403)  # bad key, no credit left, no access: stop until the owner fixes it

_UNSET: Any = object()
_override: Any = _UNSET
_client: HttpFetcher | None = None
_lock = threading.Lock()


def set_http(fetcher: Any) -> None:
    """Tests: the fetcher :func:`http` hands out (``None``: US prices off). ``_UNSET`` restores the default."""
    global _override, _client
    _override, _client = fetcher, None


def http() -> HttpFetcher | None:
    """The Databento fetcher, or ``None`` when US prices are off (or under FORLIOSA_ENV=test without a fake)."""
    if _override is not _UNSET:
        return _override
    from forliosa.config import get_settings

    settings = get_settings()
    if not settings.us_prices_enabled or settings.forliosa_env == "test" or settings.databento_api_key is None:
        return None
    global _client
    with _lock:
        if _client is None:
            _client = databento.fetcher(settings.databento_api_key.get_secret_value().strip())
        return _client


def wanted(db: Session) -> list[str]:
    """Every US symbol to keep: the market page's ETFs, the benchmark option, then the tracked ones."""
    return databento.us_symbols([*MARKET_ETFS, *BENCHMARK_ETFS, *tracked_symbols(db)])


def stored_through(db: Session) -> date | None:
    return db.scalar(select(DatasetStatus.data_date).where(DatasetStatus.key == STATUS_KEY))


def _store(db: Session, bars: list[databento.Bar]) -> int:
    rows = [{"symbol": b.symbol, "date": b.date, "open": b.open, "high": b.high, "low": b.low, "close": b.close,
             "volume": b.volume, "source": SOURCE} for b in bars]
    # Only our own rows are replaced (a corrected summary); nothing else ever writes a US row.
    return upsert(db, PriceDaily, rows, ["symbol", "date"], where=PriceDaily.source == SOURCE)


def _set_status(db: Session, newest: date, rows: int) -> None:
    """The newest session stored; never moves back."""
    stored = stored_through(db)
    if stored is not None and stored > newest:
        return
    upsert(db, DatasetStatus, [{"key": STATUS_KEY, "data_date": newest, "rows": rows,
                                "fetched_at": datetime.now(TAIPEI)}], ["key"])


def _record(db: Session, symbol: str, status: str, first: date | None = None, rows: int = 0) -> None:
    row = db.get(PriceBackfill, symbol)
    if row is None:
        row = PriceBackfill(symbol=symbol, source=SOURCE, status=status, attempts=0)
        db.add(row)
    row.source, row.status, row.first_date, row.rows = SOURCE, status, first, rows
    row.attempts = (row.attempts or 0) + 1
    row.updated_at = now_utc()


@dataclass
class UpdateResult:
    available: date | None = None  # the newest session Databento has
    stored: date | None = None  # the newest session we have after this run
    symbols: int = 0
    rows: int = 0
    skipped: bool = False  # nothing new at Databento: no data was bought


def update(db: Session, fetcher: HttpFetcher, now: datetime | None = None) -> UpdateResult:
    """The sessions after the newest one stored, for every symbol whose history is in. Raises ``HttpStatusError`` on
    a refusal."""
    available = databento.last_available_day(fetcher)
    have = stored_through(db)
    out = UpdateResult(available=available, stored=have)
    done = set(db.scalars(select(PriceBackfill.symbol).where(PriceBackfill.source == SOURCE,
                                                             PriceBackfill.status == "done")))
    tracked = wanted(db)
    syms = [s for s in tracked if s in done]
    # Nobody holds or watches it any more: it stops being updated, and if it comes back it is backfilled again,
    # so the sessions it missed are filled (2026-11-15 review: a permanent gap otherwise)
    gone = done - set(tracked)
    if gone:
        db.execute(sql_update(PriceBackfill).where(PriceBackfill.source == SOURCE, PriceBackfill.symbol.in_(gone))
                   .values(status="untracked"))
        db.commit()
    if (have is not None and have >= available) or not syms:
        out.skipped = True
        return out
    start = (have - timedelta(days=OVERLAP_DAYS)) if have else available - timedelta(days=OVERLAP_DAYS)
    res = databento.daily_bars(fetcher, syms, start, available, available=available)
    out.rows = _store(db, res.bars)
    out.symbols = len({b.symbol for b in res.bars})
    if res.bars:
        newest = max(b.date for b in res.bars)
        _set_status(db, newest, out.rows)
        out.stored = max(newest, have) if have else newest
    return out


def pending(db: Session, now: datetime | None = None) -> list[str]:
    """Symbols whose history has not been asked for yet (or is due another try)."""
    now = now or now_utc()
    seen = {r.symbol: r for r in db.scalars(select(PriceBackfill).where(PriceBackfill.source == SOURCE))}
    todo = []
    for sym in wanted(db):
        r = seen.get(sym)
        if (r is None or r.status == "untracked" or (r.status == "not_found" and now - r.updated_at >= NOT_FOUND_RETRY)
                or (r.status == "error" and now - r.updated_at >= ERROR_RETRY)):
            todo.append(sym)
    return todo


@dataclass
class BackfillResult:
    asked: int = 0
    stored: int = 0  # symbols that got bars
    rows: int = 0
    not_found: list[str] = field(default_factory=list)
    remaining: int = 0
    blocked: bool = False  # Databento refused (bad key, no credit): stop asking for a while


def backfill(db: Session, fetcher: HttpFetcher, deadline_seconds: float | None = None,
             now: datetime | None = None) -> BackfillResult:
    """History from 2024-07-01 for every pending symbol, 100 symbols per request."""
    todo = pending(db, now)
    out = BackfillResult(remaining=len(todo))
    if not todo:
        return out
    started = clock.monotonic()
    try:
        available = databento.last_available_day(fetcher)
    except HttpStatusError as exc:
        out.blocked = exc.status in REFUSALS
        if not out.blocked:
            raise
        log.warning("US price backfill: Databento refused (%s)", exc.status)
        return out
    for i in range(0, len(todo), databento.BATCH):
        if deadline_seconds is not None and clock.monotonic() - started > deadline_seconds:
            break
        part = todo[i:i + databento.BATCH]
        try:
            res = databento.daily_bars(fetcher, part, FIRST_DAY, available, available=available)
        except HttpStatusError as exc:
            if exc.status in REFUSALS:
                out.blocked = True
                log.warning("US price backfill: Databento refused (%s)", exc.status)
                break
            for s in part:
                _record(db, s, "error")
            db.commit()
            out.asked += len(part)
            continue
        except ProviderUnavailable as exc:  # timeout, a cut connection: asked again in an hour, not every run
            log.warning("US price backfill: a batch failed (%s)", exc)
            for s in part:
                _record(db, s, "error")
            db.commit()
            out.asked += len(part)
            continue
        out.asked += len(part)
        out.rows += _store(db, res.bars)
        by_symbol: dict[str, list[date]] = {}
        for b in res.bars:
            by_symbol.setdefault(b.symbol, []).append(b.date)
        for s in part:
            days = by_symbol.get(s)
            if days:
                _record(db, s, "done", min(days), len(days))
                out.stored += 1
            else:
                _record(db, s, "not_found")
                out.not_found.append(s)
        db.commit()
        # The progress (``stored_through``) is the daily update's: a backfill that got the newest session for a new
        # symbol must not make the next update skip every other symbol's (2026-11-15 review). Only the very first
        # run sets it, so the update has a start.
        if res.bars and stored_through(db) is None:
            _set_status(db, max(b.date for b in res.bars), out.rows)
    out.remaining = len(pending(db, now))
    return out


def summary(db: Session) -> dict[str, Any]:
    """For the admin overview: whether it is on, rows stored, symbols by status, the newest session."""
    from forliosa.config import get_settings

    counts = dict(db.execute(select(PriceBackfill.status, func.count()).where(PriceBackfill.source == SOURCE)
                             .group_by(PriceBackfill.status)).all())
    rows = db.scalar(select(func.count()).select_from(PriceDaily).where(PriceDaily.source == SOURCE)) or 0
    have = stored_through(db)
    return {"enabled": get_settings().us_prices_served, "rows": rows, "pending": len(pending(db)),
            "first_day": FIRST_DAY.isoformat(), "stored_through": have.isoformat() if have else None,
            "symbols": {k: int(counts.get(k, 0)) for k in ("done", "untracked", "not_found", "error")}}
