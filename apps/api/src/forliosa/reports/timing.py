"""When a dataset's row of a given day could first have been read (Taipei): ``available_at(dataset, data_date)``.

A data pack only takes a row that is in the database **and** whose ``available_at`` is not later than the pack's
cut-off (contract §6.4). In the scheduled runs this changes nothing (a row in the database is already out); it matters
when an edition of a past day is rebuilt from the command line — the 2026-11-16 sample drew FMTQIK's official turnover,
published at 05:22 the next morning, into a 15:55 report.

The times are deliberately late where nobody has measured them (TWSE's margin and foreign top-20 files: the next
morning's batch; ``python -m forliosa.reports probe-dates`` measures them, contract §21).

One equivalence (``EQUIVALENT_EARLIER``): TWSE's OpenAPI closes and indices of day D replace the rows of TWSE's
same-day download files (``twse-opendata``, 14:00 on D, the same official numbers) the next morning. While those
download files are polled (TWSE_OPENDATA_CLOSE), an OpenAPI row of D counts as available at the download's time —
otherwise a close edition rebuilt the next day would have no Taiwan closes at all. The OpenAPI-only datasets (FMTQIK,
MI_5MINS_HIST, the total-return index MFI94U) keep the next morning.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from forliosa.timeutil import TAIPEI, next_tw_trading_day, us_close_dt

log = logging.getLogger(__name__)

MORNING_BATCH = time(5, 45)  # TWSE's OpenAPI batch lands 05:20–05:30 (probe 2026-11-17); a margin of 15 minutes

# dataset -> (rule, time). Rules: "same" = the day itself at that time; "next" = the next Taiwan trading day at that
# time; "us" = the US close of the session plus an hour.
_RULES: dict[str, tuple[str, time | None]] = {
    "twse-opendata/price": ("same", time(14, 0)),
    "twse-opendata/index": ("same", time(14, 0)),
    "twse-openapi/price": ("next", MORNING_BATCH),
    "twse-openapi/index": ("next", MORNING_BATCH),
    "twse-openapi/total_return": ("next", MORNING_BATCH),
    "twse-openapi/turnover": ("next", MORNING_BATCH),
    "twse-openapi/index_ohlc": ("next", MORNING_BATCH),
    "twse-openapi/valuation": ("next", MORNING_BATCH),
    "twse-openapi/reference": ("same", time(8, 10)),  # the day the reference price applies to
    "tpex-openapi/reference": ("same", time(8, 10)),
    "twse-openapi/margin": ("next", MORNING_BATCH),  # conservative until probe-dates has measured the evening file
    "twse-openapi/foreign_top20": ("next", MORNING_BATCH),
    "tpex-openapi/index": ("same", time(14, 30)),
    "tpex-openapi/total_return": ("same", time(14, 30)),
    "tpex-openapi/price": ("same", time(23, 40)),
    "tpex-openapi/institutional": ("same", time(23, 40)),
    "tpex-openapi/margin": ("same", time(23, 40)),
    "taifex-openapi/institutional_general": ("same", time(21, 45)),
    "taifex-openapi/institutional_fut_opt": ("same", time(21, 45)),
    "taifex-openapi/institutional_futures": ("same", time(21, 45)),
    "taifex-openapi/institutional_options": ("same", time(21, 45)),
    "taifex-openapi/institutional_calls_puts": ("same", time(21, 45)),
    "taifex-openapi/put_call_ratio": ("same", time(21, 45)),
    "taifex-openapi/large_traders_futures": ("same", time(21, 45)),
    "taifex-openapi/large_traders_options": ("same", time(21, 45)),
    "cbc-opendata/fx": ("same", time(17, 0)),
    "databento-equs/price": ("us", None),
}
# An OpenAPI row of D stands for the same-day download's row of D (see the module docstring).
EQUIVALENT_EARLIER = {"twse-openapi/price": "twse-opendata/price", "twse-openapi/index": "twse-opendata/index"}
# Rows stamped with their own creation time (announcements, hand-kept tables): ``available_at(key, d, created_at)``.
STAMPED = frozenset({"market_events", "manual-calendar"})


def known(dataset: str) -> bool:
    return dataset in _RULES or dataset in STAMPED or dataset.split("/", 1)[0] in STAMPED


def available_at(dataset: str, data_date: date, stamped: datetime | None = None,
                 opendata_on: bool | None = None) -> datetime:
    """The earliest moment the row of ``data_date`` in ``dataset`` existed. Announcements and hand-kept rows use their
    own ``stamped`` time (``created_at`` / ``updated_at``). An unknown dataset is treated as published the next
    morning (and logged), never as earlier."""
    if dataset.split("/", 1)[0] in STAMPED or dataset in STAMPED:
        if stamped is None:
            raise ValueError(f"{dataset}: the row's own time is needed")
        return stamped.astimezone(TAIPEI)
    if dataset in EQUIVALENT_EARLIER:
        if opendata_on is None:
            from forliosa.datapolicy import twse_opendata_on

            opendata_on = twse_opendata_on()
        if opendata_on:
            return available_at(EQUIVALENT_EARLIER[dataset], data_date)
    rule = _RULES.get(dataset)
    if rule is None:
        log.warning("market reports: no availability rule for %s; taken as the next morning", dataset)
        rule = ("next", MORNING_BATCH)
    kind, at = rule
    if kind == "us":
        return (us_close_dt(data_date) + timedelta(hours=1)).astimezone(TAIPEI)
    day = next_tw_trading_day(data_date + timedelta(days=1)) if kind == "next" else data_date
    return datetime.combine(day, at, TAIPEI)


def usable(dataset: str, data_date: date, cutoff: datetime, stamped: datetime | None = None,
           opendata_on: bool | None = None) -> bool:
    """Whether a row could have been read at ``cutoff``."""
    return available_at(dataset, data_date, stamped, opendata_on) <= cutoff
