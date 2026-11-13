"""Official TWSE market calendar: archived ``market_holidays`` rows -> :mod:`forliosa.timeutil`.

``python -m forliosa.archive run`` stores TWSE's holidaySchedule (current year). Calling
:func:`load_official_calendar` makes every trading-day helper (``next_tw_trading_day`` …) use it for the
years it covers; other years keep the built-in list. It is one small query, so callers that need exact
dates (recurring debits, ``/portfolio/upcoming``) simply call it per request; the worker calls it at
start and after each archive run.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.models import MarketHoliday
from forliosa.timeutil import (
    MARKET_CLOSE,
    MARKET_OPEN,
    TAIPEI,
    is_tw_market_open,
    is_tw_trading_day,
    now_taipei,
    set_official_holidays,
)

log = logging.getLogger(__name__)

_clock: Callable[[], datetime] = now_taipei


def set_clock(clock: Callable[[], datetime] | None) -> None:
    """Tests: replace the clock behind :func:`market_status` (``None`` restores the real one)."""
    global _clock
    _clock = clock or now_taipei


def market_status(db: Session, now: datetime | None = None) -> dict[str, Any]:
    """``GET /meta/market-status``: is the Taiwan market in session right now? No user data.

    ``is_trading_day`` follows the official calendar (reloaded here: one small query); ``is_open`` is a trading day
    from 09:00 up to, not including, 13:30 Taipei. Prices are never real-time (there is no licensed intraday
    source): the frontend uses this to say whether the close it shows is "today's, not out yet" or simply the latest.
    """
    load_official_calendar(db)
    at = (now or _clock()).astimezone(TAIPEI)
    return {"tw": {"date": at.date().isoformat(), "is_trading_day": is_tw_trading_day(at.date()),
                   "is_open": is_tw_market_open(at), "open": MARKET_OPEN.strftime("%H:%M"),
                   "close": MARKET_CLOSE.strftime("%H:%M")}}


def load_official_calendar(db: Session) -> int:
    """Apply the archived schedule; returns the number of closed weekdays loaded (0 = built-in list)."""
    try:
        rows = db.execute(select(MarketHoliday.date, MarketHoliday.is_trading_day)).all()
    except Exception as exc:  # e.g. the table does not exist yet (migrations not run)
        log.warning("market calendar not loaded: %s", exc)
        db.rollback()
        return 0
    closed = [d for d, trading in rows if not trading and d.weekday() < 5]
    set_official_holidays(closed, {d.year for d, _ in rows})
    return len(closed)
