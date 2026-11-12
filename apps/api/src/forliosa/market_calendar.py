"""Official TWSE market calendar: archived ``market_holidays`` rows -> :mod:`forliosa.timeutil`.

``python -m forliosa.archive run`` stores TWSE's holidaySchedule (current year). Calling
:func:`load_official_calendar` makes every trading-day helper (``next_tw_trading_day`` …) use it for the
years it covers; other years keep the built-in list. It is one small query, so callers that need exact
dates (recurring debits, ``/portfolio/upcoming``) simply call it per request; the worker calls it at
start and after each archive run.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.models import MarketHoliday
from forliosa.timeutil import set_official_holidays

log = logging.getLogger(__name__)


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
