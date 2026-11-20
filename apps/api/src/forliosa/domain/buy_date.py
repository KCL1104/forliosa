"""Estimated buy date (資產組成原型, ``docs/proposals/asset-composition.md``〈估計買入日的算法〉; not yet approved by
the product owner — using the history backfill for it is the proposal's owner decision 1).

A holdings screenshot (匯入庫存) has the broker's average cost but no buy date. The estimate is the most recent day,
looking back from the import day, on which the price *crossed* that cost:

* the day's low ≤ cost ≤ the day's high (the range, not the close);
* or the cost sits in a gap between the previous day and this one: yesterday's high 600, today's low 620, cost 612 —
  the day the price jumped over it (and the same downwards);
* nothing in the period searched (five years; US stocks from 2024-07-01, where our closes begin): no estimate, and
  the buy keeps the import day, as before.

The bars must be the prices **as traded** (not split-adjusted), or a broker's cost cannot be compared with them
(``services.buy_date.traded_history``). The front end's ``lib/buy-date.ts`` is the same rule (the chart's picker
computes its candidates in the browser); ``tests/domain/test_buy_date.py`` keeps the two in step.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Protocol

SEARCH_YEARS = 5
US_HISTORY_FROM = date(2024, 7, 1)  # the first US close we have (Databento EQUS.SUMMARY)


class Bar(Protocol):
    t: date
    h: Decimal
    l: Decimal  # noqa: E741 - the candle's own field name


def crosses_on(bars: Sequence[Bar], i: int, cost: Decimal) -> bool:
    """Did the price cross ``cost`` on ``bars[i]``: its range holds the cost, or the cost sits in the gap between the
    previous bar and this one (``lib/buy-date.ts`` ``crossesOn``)."""
    if not 0 <= i < len(bars):
        return False
    c = bars[i]
    if c.l <= cost <= c.h:
        return True
    if i == 0:
        return False
    prev = bars[i - 1]
    # a gap up: yesterday's high still under the cost, today's low already over it; a gap down the other way round
    return (prev.h < cost < c.l) or (c.h < cost < prev.l)


def estimate_buy_date(bars: Sequence[Bar], cost: Decimal, until: date, start: date | None = None) -> date | None:
    """The most recent day on or before ``until`` whose bar crossed ``cost`` (``bars`` oldest first); ``None`` when
    none did (``lib/buy-date.ts`` ``estimateBuyDate``). ``start``: bars before it are left out — the first bar from
    it on has no day before it, so a drop onto it (a split, a stock dividend's ex-date) is no gap «over» the cost."""
    if start is not None:
        bars = [b for b in bars if b.t >= start]
    last = -1
    for i, b in enumerate(bars):
        if b.t > until:
            break
        last = i
    for i in range(last, -1, -1):
        if crosses_on(bars, i, cost):
            return bars[i].t
    return None


def search_start(until: date, us: bool) -> date:
    """The first day the estimate looks at: five years before ``until`` (the history backfill's depth); a US stock
    no earlier than :data:`US_HISTORY_FROM`."""
    try:
        start = until.replace(year=until.year - SEARCH_YEARS)
    except ValueError:  # 29 February
        start = until.replace(year=until.year - SEARCH_YEARS, day=28)
    return max(start, US_HISTORY_FROM) if us else start
