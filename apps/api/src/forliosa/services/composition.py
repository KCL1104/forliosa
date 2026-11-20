"""資產組成 (asset-composition prototype; ``docs/proposals/asset-composition.md`` 附錄 B, not yet approved by the
product owner): the ``composition`` block of ``GET /portfolio/performance``.

本金 (``net_invested``) + 賺的／虧的 (``market_value − net_invested``, dividends excluded) = 總資產; dividends are
listed apart. The block adds what the series alone does not say:

* ``dividends``: each day's net cash dividends in the window (TWD, after withholding and 二代健保), booked on the
  close they belong to — the same numbers as ``dividends_by_month``;
* ``estimated``: the spans drawn with estimated buy dates, one per import (:func:`estimated_spans`), never clipped
  to the window;
* ``months``: one row per month (or the real part of one), newest first (:func:`monthly_breakdown`), with
  ``months_estimated`` (months wholly inside the estimated span, left out) and ``months_import_day`` (provisional,
  owner decision 4: months of a buy booked on its import day because no crossing was found, left out).

:func:`monthly_breakdown` is the front end's ``lib/asset-composition.ts`` ``monthlyBreakdown`` line by line, on the
series' own (rounded) numbers and with JavaScript's rounding, so both give the same answer
(``tests/test_composition.py`` checks it against a fixture the front-end function wrote).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from forliosa.models import Transaction
from forliosa.timeutil import last_tw_trading_day, today_taipei, tw_trading_days


@dataclass(frozen=True)
class MonthPoint:
    """One close of the series (``t`` None: the zero before the first record)."""

    t: date | None
    market_value: float
    net_invested: float
    twr_index: float
    benchmark_index: float | None


@dataclass(frozen=True, order=True)
class Span:
    start: date  # 「from」
    until: date

    def holds(self, t: date | None) -> bool:
        return t is not None and self.start <= t <= self.until

    def overlaps(self, start: date, end: date) -> bool:
        return self.start <= end and self.until >= start

    def out(self) -> dict[str, date]:
        return {"from": self.start, "until": self.until}


def in_spans(t: date | None, spans: Sequence[Span]) -> bool:
    return any(s.holds(t) for s in spans)


def js_round(x: float, places: int) -> float:
    """``Math.round(x * 10^places) / 10^places``: halves round up (towards +∞), unlike Python's ``round``."""
    f = 10 ** places
    return math.floor(x * f + 0.5) / f


def _month(t: date) -> str:
    return t.isoformat()[:7]


def _profit(p: MonthPoint) -> float:
    return p.market_value - p.net_invested


@dataclass
class _Group:
    month: str
    est: bool
    first: int
    last: int


@dataclass(frozen=True)
class Breakdown:
    months: list[dict[str, Any]]
    skipped: int  # months_estimated
    skipped_import: int  # months_import_day


def monthly_breakdown(points: Sequence[MonthPoint], base: MonthPoint | None, estimated: Sequence[Span] = (),
                      import_days: Iterable[date] = ()) -> Breakdown:
    """Each month's 本金增減 (``flows``), 損益 (``pnl``, dividends excluded), time-weighted return (``twr``) and the
    benchmark's (``benchmark_twr``), newest first.

    ``points``: the window's closes, oldest first; ``base``: the close before them (``None``: the window starts at the
    first record — counted from zero, and that first month is not compared with the benchmark, which has no close
    before the first day). A month's base is the close before its first close. Closes inside any ``estimated`` span
    are left out: a month wholly inside is skipped (``skipped``), a month partly inside keeps its real days (``whole``
    false; a month a span cuts in the middle is one row per real part).
    ``import_days``: the dates of buys booked on their import day — each one's close (that day or the next) puts its
    month out (``skipped_import``), unless it is the window's base close or earlier."""
    zero = MonthPoint(None, 0.0, 0.0, 1.0, None) if points else None
    import_months: set[str] = set()
    for d in import_days:
        if base is not None and base.t is not None and base.t >= d:
            continue
        hit = next((p for p in points if p.t is not None and p.t >= d), None)
        if hit is not None and hit.t is not None:
            import_months.add(_month(hit.t))
    groups: list[_Group] = []
    for i, p in enumerate(points):
        assert p.t is not None
        month, est = _month(p.t), in_spans(p.t, estimated)
        g = groups[-1] if groups else None
        if g is not None and g.month == month and g.est == est:
            g.last = i
        else:
            groups.append(_Group(month, est, i, i))
    real = {g.month for g in groups if not g.est}
    skipped = len({g.month for g in groups if g.est and g.month not in real})
    skipped_import = sum(1 for m in real if m in import_months)
    months: list[dict[str, Any]] = []
    for g in groups:
        if g.est or g.month in import_months:
            continue
        b = points[g.first - 1] if g.first > 0 else (base or zero)
        if b is None:
            continue
        last = points[g.last]
        starts_at_month = b.t is not None and _month(b.t) < g.month
        nxt = points[g.last + 1] if g.last + 1 < len(points) else None
        ends_at_month = nxt is not None and nxt.t is not None and _month(nxt.t) > g.month
        twr = last.twr_index / b.twr_index - 1 if b.twr_index else None
        bench = (last.benchmark_index / b.benchmark_index - 1
                 if b.benchmark_index and last.benchmark_index is not None else None)
        months.append({
            "month": g.month,
            "from": points[g.first].t,
            "to": last.t,
            "whole": starts_at_month and ends_at_month,
            "flows": js_round(last.net_invested - b.net_invested, 2),
            "pnl": js_round(_profit(last) - _profit(b), 2),
            "twr": None if twr is None else js_round(twr, 6),
            "benchmark_twr": None if bench is None else js_round(bench, 6),
        })
    months.reverse()
    return Breakdown(months, skipped, skipped_import)


def estimated_spans(transactions: Iterable[Transaction], today: date | None = None) -> list[Span]:
    """The days drawn with estimated buy dates (both ends included), oldest first: one span per import (its
    ``imported_on``) — from that import's earliest buy still ``estimated`` to the trading day before the import day
    (Taiwan calendar). Spans that overlap or touch (no trading day between them) are one. Empty without such a buy
    (none imported, or every one picked by the user since). A second import's estimates cover only their own days:
    the real records between two imports stay real."""
    by_import: dict[date, date] = {}
    for t in transactions:
        if t.type == "buy" and t.date_basis == "estimated":
            day = t.imported_on or today or today_taipei()
            by_import[day] = min(by_import.get(day, t.trade_date), t.trade_date)
    spans = sorted(Span(start, until) for imported, start in by_import.items()
                   if (until := last_tw_trading_day(imported - timedelta(days=1))) >= start)
    merged: list[Span] = []
    for s in spans:
        prev = merged[-1] if merged else None
        if prev is not None and (s.start <= prev.until + timedelta(days=1)
                                 or not tw_trading_days(prev.until + timedelta(days=1), s.start - timedelta(days=1))):
            merged[-1] = Span(prev.start, max(prev.until, s.until))
        else:
            merged.append(s)
    return merged


def import_days(transactions: Iterable[Transaction]) -> list[date]:
    """Dates of the buys booked on their import day (``import_day``: no crossing found)."""
    return [t.trade_date for t in transactions if t.type == "buy" and t.date_basis == "import_day"]
