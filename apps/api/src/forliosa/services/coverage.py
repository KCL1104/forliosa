"""「資料累積中」notes: there is no official per-stock history API, so real series only exist from the day
our archive started. Under ``DATA_POLICY=commercial`` there is no demo data either: endpoints return what
is real (possibly nothing) and say so in ``notes`` instead of filling the gap with synthetic data.
"""

from __future__ import annotations

from datetime import date, timedelta

from forliosa.marketdata.base import market_of_symbol
from forliosa.marketdata.service import MarketData
from forliosa.timeutil import next_tw_trading_day

# A series "covers" its range when its first point is within this many days of the first trading day.
COVERAGE_GRACE_DAYS = 5
US_NOTE = "美股沒有報價"


NO_DATA_NOTE = "還沒有資料"


def ymd(d: date) -> str:
    """Dates inside user-facing notes: 2026/06/01 (the same format the pages use for ranges)."""
    return d.strftime("%Y/%m/%d")


def since_note(since: date | None) -> str:
    """Where a series starts. Notes say the fact (when the data begins), not how it is stored or licensed —
    the reasons live on the 資料來源與授權 page (product owner, 2026-11-13)."""
    return f"資料從 {ymd(since)} 開始" if since else NO_DATA_NOTE


def accumulating_note(md: MarketData, symbol: str | None = None) -> str:
    return since_note(md.archive_since(symbol))


def covers(first: date | None, start: date) -> bool:
    return first is not None and first <= next_tw_trading_day(start) + timedelta(days=COVERAGE_GRACE_DAYS)


def series_notes(md: MarketData, symbol: str, start: date, first: date | None) -> list[str]:
    """Notes for a daily series of ``symbol`` requested from ``start`` whose first point is ``first``.

    Personal mode fills an *empty* series with demo data (which covers the range, so no note); a short real
    series (the archive alone, FinMind being off by default) gets the same note in both modes.
    """
    if covers(first, start):
        return []
    if market_of_symbol(symbol) == "US" and md.policy == "commercial":
        return [US_NOTE]
    return [accumulating_note(md, symbol)]
