"""History backfill: daily candles from before our own archive began (PRICE_HISTORY_SOURCE=yahoo).

Product owner, 2026-11-13: the stock page had nothing to draw (the archive of official closes began on 2026-11-12), so
five years of daily candles are loaded once from Yahoo Finance. It is not a licensed source; the decision and its risk
are recorded in PRODUCT.md and docs/research/data-sources-licensing.md. Rules this module keeps:

* rows go to ``prices_daily`` under ``source = "yahoo-history"`` and only for days **before the symbol's first
  official close** — an official row is never replaced and today's unfinished bar is never stored;
* a symbol is stored only when Yahoo agrees with our official close on a day both have — its close within 0.6 %, or,
  where its close is still missing, the official close inside its high–low range (a wrong ticker or a rescaled
  series is dropped);
* HTTP 429 means "slower": the same symbol is asked again after a minute, then after three; a third 429 in a row,
  or a refusal (403, a redirect …), ends the run. It is tried again later with the same honest client — never
  worked around (no browser disguise, no other address);
* ``drop`` removes every row and the bookkeeping, e.g. when licensed history replaces it.

Only chart-like reads ask for these rows (``backfill=True``): Yahoo's prices are split-adjusted, so ledger valuation
and performance keep to official closes.

    uv run python -m forliosa.history_backfill run [--symbols 2330.TW,0050.TW] [--limit 50]
    uv run python -m forliosa.history_backfill status
    uv run python -m forliosa.history_backfill drop
"""

from __future__ import annotations

import argparse
import logging
import time as _time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from forliosa.archive import tracked_symbols, upsert
from forliosa.datapolicy import HISTORY_SOURCE, source_clause
from forliosa.marketdata import yahoo_history
from forliosa.marketdata.base import ProviderUnavailable
from forliosa.marketdata.http import HttpFetcher, HttpStatusError
from forliosa.models import DatasetStatus, PriceBackfill, PriceDaily
from forliosa.timeutil import now_taipei, now_utc

log = logging.getLogger(__name__)

STATUS_KEY = f"{HISTORY_SOURCE}/price"
# Yahoo's close and the official close of the same day must agree within this (rounding only).
MATCH_TOLERANCE = Decimal("0.006")
FINAL = ("done", "not_found", "mismatch")
RETRY_AFTER = timedelta(hours=12)  # no_overlap (e.g. a halted stock) and errors are asked again later
# A symbol whose only try was before this moment and did not end in ``done`` is asked once more (its second try):
# the first production run (2026-11-13 16:22 UTC on) dropped every TPEx symbol whose newest bar had no close yet.
RECHECK_BEFORE = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
MAX_ATTEMPTS = 5
REFUSALS = (401, 402, 403, 405, 407, 429, 451)
RATE_LIMIT_WAITS = (60.0, 180.0)  # seconds before asking the same symbol again after a 429


@dataclass
class BatchResult:
    asked: int = 0
    stored: int = 0  # symbols that got rows
    rows: int = 0
    blocked: bool = False  # the source refused: stop and wait
    remaining: int = 0


def official_first_dates(db: Session) -> dict[str, date]:
    """symbol -> its first close that charts actually serve (where official history begins). Only rows the active
    data policy serves count: leftovers of removed jobs (``twse-mis``, ``twse-web``) or merged worker labels are never
    shown, so counting them would leave a gap before them in the chart (2026-11-14 review)."""
    from forliosa.config import get_settings

    rows = db.execute(select(PriceDaily.symbol, func.min(PriceDaily.date))
                      .where(source_clause(PriceDaily.source, get_settings().data_policy))
                      .group_by(PriceDaily.symbol))
    return {s: d for s, d in rows if s.endswith((".TW", ".TWO"))}


def pending(db: Session, now: datetime | None = None) -> list[str]:
    """Symbols still to ask, the ones people hold or watch first."""
    now = now or now_utc()
    firsts = official_first_dates(db)
    seen = {r.symbol: r for r in db.scalars(select(PriceBackfill))}
    todo = []
    for sym in firsts:
        r = seen.get(sym)
        if r is None or (r.status != "done" and r.attempts <= 1 and r.updated_at < RECHECK_BEFORE) or (
                r.status not in FINAL and r.attempts < MAX_ATTEMPTS and now - r.updated_at >= RETRY_AFTER):
            todo.append(sym)
    tracked = set(tracked_symbols(db))
    return sorted(todo, key=lambda s: (s not in tracked, s))


def _record(db: Session, symbol: str, status: str, first: date | None = None, rows: int = 0) -> None:
    row = db.get(PriceBackfill, symbol)
    if row is None:
        row = PriceBackfill(symbol=symbol, source=HISTORY_SOURCE, status=status, attempts=0)
        db.add(row)
    row.status, row.first_date, row.rows = status, first, rows
    row.attempts = (row.attempts or 0) + 1
    row.updated_at = now_utc()
    db.commit()


def agrees(bar: yahoo_history.Bar, official_close: Decimal) -> bool:
    """Does the source's bar describe the same instrument and price scale as our official close of that day? Its
    close within the tolerance; or, while its close is still missing, the official close inside its range."""
    if bar.close is not None:
        return abs(bar.close - official_close) / official_close <= MATCH_TOLERANCE
    if bar.low is None or bar.high is None:
        return False
    return bar.low * (1 - MATCH_TOLERANCE) <= official_close <= bar.high * (1 + MATCH_TOLERANCE)


def backfill_symbol(db: Session, http: HttpFetcher, symbol: str, first_official: date, years: int) -> tuple[str, int]:
    """Ask the source for ``symbol`` and store the days before ``first_official``. Returns (status, rows stored).
    Raises ``HttpStatusError`` when the source refuses (the caller stops the run)."""
    today = now_taipei().date()
    start = today - timedelta(days=366 * years)
    try:
        bars = yahoo_history.daily_bars(http, symbol, start, today)
    except HttpStatusError as exc:
        if exc.status == 404:
            _record(db, symbol, "not_found")
            return "not_found", 0
        raise
    except ProviderUnavailable as exc:
        log.warning("history backfill %s: %s", symbol, exc)
        _record(db, symbol, "error")
        return "error", 0
    if not bars:
        log.info("history backfill %s: the source has no bars", symbol)
        _record(db, symbol, "not_found")
        return "not_found", 0
    by_day = {b.date: b for b in bars}
    official = dict(db.execute(select(PriceDaily.date, PriceDaily.close).where(
        PriceDaily.symbol == symbol, PriceDaily.source != HISTORY_SOURCE, PriceDaily.date.in_(list(by_day)))).all())
    # Today's bar can still be moving: it is no evidence either way.
    overlap = [(by_day[d], c) for d, c in sorted(official.items()) if d < today and c]
    if not overlap:
        log.info("history backfill %s: no day to compare with (official %s, source ends %s)", symbol,
                 first_official, bars[-1].date)
        _record(db, symbol, "no_overlap")
        return "no_overlap", 0
    for bar, theirs in overlap:
        if not agrees(bar, theirs):
            log.info("history backfill %s: mismatch on %s — source close %s (range %s–%s), official %s", symbol,
                     bar.date, bar.close, bar.low, bar.high, theirs)
            _record(db, symbol, "mismatch")
            return "mismatch", 0
    rows = [{"symbol": symbol, "date": b.date, "open": b.open, "high": b.high, "low": b.low, "close": b.close,
             "volume": b.volume, "source": HISTORY_SOURCE}
            for b in bars if b.date < first_official and b.close is not None]
    n = upsert(db, PriceDaily, rows, ["symbol", "date"], ())  # never replaces an existing row
    _record(db, symbol, "done", rows[0]["date"] if rows else None, n)
    return "done", n


def run_batch(db: Session, http: HttpFetcher, years: int = 5, limit: int | None = None,
              deadline_seconds: float | None = None, symbols: list[str] | None = None,
              clock: Callable[[], float] = _time.monotonic,
              sleep: Callable[[float], None] = _time.sleep) -> BatchResult:
    """Ask for the next symbols until ``limit`` or the deadline is reached, or the source refuses."""
    firsts = official_first_dates(db)
    todo = [s for s in (symbols if symbols is not None else pending(db)) if s in firsts]
    out = BatchResult(remaining=len(todo))
    started = clock()
    for sym in todo:
        if (limit is not None and out.asked >= limit) or (
                deadline_seconds is not None and clock() - started >= deadline_seconds):
            break
        waits = iter(RATE_LIMIT_WAITS)
        while True:
            try:
                status, n = backfill_symbol(db, http, sym, firsts[sym], years)
            except HttpStatusError as exc:
                wait = next(waits, None) if exc.status == 429 else None
                if wait is not None:
                    log.info("history backfill: HTTP 429 at %s, asking again in %.0f s", sym, wait)
                    sleep(wait)
                    continue
                if exc.status in REFUSALS or 300 <= exc.status < 400:
                    log.warning("history backfill stopped at %s: the source answered HTTP %s", sym, exc.status)
                    out.blocked = True
                    break
                log.warning("history backfill %s: %s", sym, exc)
                _record(db, sym, "error")
                status, n = "error", 0
            break
        if out.blocked:
            break
        out.asked += 1
        out.remaining -= 1
        if status == "done":
            out.stored += 1
            out.rows += n
    if out.rows:
        newest = db.scalar(select(func.max(PriceDaily.date)).where(PriceDaily.source == HISTORY_SOURCE))
        total = db.scalar(select(func.count()).select_from(PriceDaily).where(PriceDaily.source == HISTORY_SOURCE)) or 0
        upsert(db, DatasetStatus, [{"key": STATUS_KEY, "data_date": newest, "rows": total, "fetched_at": now_utc()}],
               ["key"])
    return out


def summary(db: Session) -> dict[str, int]:
    counts = dict(db.execute(select(PriceBackfill.status, func.count()).group_by(PriceBackfill.status)).all())
    counts["rows"] = db.scalar(select(func.count()).select_from(PriceDaily)
                               .where(PriceDaily.source == HISTORY_SOURCE)) or 0
    counts["pending"] = len(pending(db))
    return counts


def drop(db: Session) -> int:
    """Delete every backfilled candle and the bookkeeping. Official rows are untouched."""
    n = db.execute(delete(PriceDaily).where(PriceDaily.source == HISTORY_SOURCE)).rowcount or 0
    db.execute(delete(PriceBackfill))
    db.execute(delete(DatasetStatus).where(DatasetStatus.key == STATUS_KEY))
    db.commit()
    return n


def main(argv: list[str] | None = None) -> None:
    from forliosa.config import get_settings
    from forliosa.db import session_factory

    parser = argparse.ArgumentParser(description="歷史日線回補（PRICE_HISTORY_SOURCE=yahoo；非官方資料，可整批刪除）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="回補還沒問過的代號")
    run_p.add_argument("--symbols", default="", help="逗號分隔；預設為所有有官方收盤價的代號")
    run_p.add_argument("--limit", type=int, default=None)
    sub.add_parser("status", help="各狀態的代號數與已存的筆數")
    sub.add_parser("drop", help="刪除所有回補的日線")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    with session_factory()() as db:
        if args.cmd == "status":
            print(summary(db))
        elif args.cmd == "drop":
            print(f"已刪除 {drop(db)} 筆")
        elif settings.price_history_source != "yahoo":
            print("PRICE_HISTORY_SOURCE 沒有設成 yahoo：不回補")
        else:
            syms = [s.strip() for s in args.symbols.split(",") if s.strip()] or None
            res = run_batch(db, yahoo_history.fetcher(), settings.price_history_years, args.limit, symbols=syms)
            print(f"問了 {res.asked} 檔，存了 {res.stored} 檔共 {res.rows} 筆，還有 {res.remaining} 檔"
                  + ("；來源拒絕回應，已停止" if res.blocked else ""))


if __name__ == "__main__":
    main()
