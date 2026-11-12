"""Time helpers: Asia/Taipei trading dates and a small Taiwan market holiday calendar."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(13, 30)

# TWSE market holidays (weekdays only) — a best-effort list reconstructed from the yearly holiday
# rules (observed-day shifts included); 2027 is an estimate. For every year present in the archived
# official schedule (OpenAPI /holidaySchedule/holidaySchedule → ``market_holidays``, loaded with
# :func:`set_official_holidays` by ``forliosa.calendar``) the official list replaces this one.
# Only used for calendars, schedules and demo data, never for money math.
_TW_HOLIDAYS: frozenset[date] = frozenset(
    date.fromisoformat(s)
    for s in [
        # 2023
        "2023-01-02", "2023-01-18", "2023-01-19", "2023-01-20", "2023-01-23", "2023-01-24", "2023-01-25",
        "2023-01-26", "2023-01-27", "2023-02-27", "2023-02-28", "2023-04-03", "2023-04-04", "2023-04-05",
        "2023-05-01", "2023-06-22", "2023-06-23", "2023-09-29", "2023-10-09", "2023-10-10",
        # 2024
        "2024-01-01", "2024-02-06", "2024-02-07", "2024-02-08", "2024-02-09", "2024-02-12", "2024-02-13",
        "2024-02-14", "2024-02-28", "2024-04-04", "2024-04-05", "2024-05-01", "2024-06-10", "2024-07-24",
        "2024-07-25", "2024-09-17", "2024-10-02", "2024-10-03", "2024-10-10", "2024-10-31",
        # 2025
        "2025-01-01", "2025-01-23", "2025-01-24", "2025-01-27", "2025-01-28", "2025-01-29", "2025-01-30",
        "2025-01-31", "2025-02-28", "2025-04-03", "2025-04-04", "2025-05-01", "2025-05-30", "2025-10-06",
        "2025-10-10",
        # 2026
        "2026-01-01", "2026-02-12", "2026-02-13", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19",
        "2026-02-20", "2026-02-27", "2026-04-03", "2026-04-06", "2026-05-01", "2026-06-19", "2026-09-25",
        "2026-09-28", "2026-10-09", "2026-10-26", "2026-12-25",
        # 2027 (estimate)
        "2027-01-01", "2027-02-04", "2027-02-05", "2027-02-08", "2027-02-09", "2027-02-10", "2027-02-11",
        "2027-03-01", "2027-04-05", "2027-04-06", "2027-05-01", "2027-06-09", "2027-09-15", "2027-09-28",
        "2027-10-11", "2027-10-25", "2027-12-24",
    ]
)


def now_utc() -> datetime:
    return datetime.now(UTC)


def now_taipei() -> datetime:
    return datetime.now(TAIPEI)


def today_taipei() -> date:
    return now_taipei().date()


# year -> official closed weekdays (TWSE holidaySchedule); years not present use _TW_HOLIDAYS
_OFFICIAL_HOLIDAYS: dict[int, frozenset[date]] = {}


def set_official_holidays(closed: Iterable[date], years: Iterable[int]) -> None:
    """Use the exchange's published closures for ``years`` (an empty ``years`` restores the built-in list)."""
    global _OFFICIAL_HOLIDAYS
    by_year: dict[int, set[date]] = {y: set() for y in years}
    for d in closed:
        if d.year in by_year:
            by_year[d.year].add(d)
    new = {y: frozenset(v) for y, v in by_year.items()}
    if new != _OFFICIAL_HOLIDAYS:
        _OFFICIAL_HOLIDAYS = new
        _tw_days.cache_clear()


def has_official_calendar(year: int) -> bool:
    return year in _OFFICIAL_HOLIDAYS


def is_tw_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    return d not in _OFFICIAL_HOLIDAYS.get(d.year, _TW_HOLIDAYS)


def is_us_trading_day(d: date) -> bool:
    return d.weekday() < 5


@lru_cache(maxsize=64)
def _tw_days(start: date, end: date) -> tuple[date, ...]:
    out = []
    d = start
    while d <= end:
        if is_tw_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return tuple(out)


def tw_trading_days(start: date, end: date) -> list[date]:
    return list(_tw_days(start, end))


def last_tw_trading_day(on_or_before: date) -> date:
    d = on_or_before
    while not is_tw_trading_day(d):
        d -= timedelta(days=1)
    return d


def next_tw_trading_day(on_or_after: date) -> date:
    d = on_or_after
    while not is_tw_trading_day(d):
        d += timedelta(days=1)
    return d


def market_close_dt(d: date) -> datetime:
    return datetime.combine(d, MARKET_CLOSE, TAIPEI)


def is_tw_market_open(at: datetime | None = None) -> bool:
    at = (at or now_taipei()).astimezone(TAIPEI)
    return is_tw_trading_day(at.date()) and MARKET_OPEN <= at.time() <= MARKET_CLOSE


def iso_taipei(dt: datetime) -> str:
    """ISO 8601 with +08:00 offset, second precision."""
    return dt.astimezone(TAIPEI).isoformat(timespec="seconds")
