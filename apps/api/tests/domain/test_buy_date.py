"""Estimated buy date (資產組成原型, ``domain.buy_date``): the same rule as the front end's ``lib/buy-date.ts`` — the
cases of ``lib/__tests__/buy-date.test.ts`` here too, and the answers ``estimateBuyDate`` wrote into
``tests/fixtures/buy_date_parity.json`` (160 random series and costs, gaps included)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D
from pathlib import Path

from forliosa.domain.buy_date import US_HISTORY_FROM, crosses_on, estimate_buy_date, search_start

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "buy_date_parity.json"


@dataclass(frozen=True)
class K:
    t: date
    l: D  # noqa: E741
    h: D


def k(t: str, lo: float, hi: float) -> K:
    return K(date.fromisoformat(t), D(str(lo)), D(str(hi)))


def test_the_range_not_the_close_decides():
    bars = [k("2026-01-05", 600, 620)]
    assert crosses_on(bars, 0, D(612)) and crosses_on(bars, 0, D(600)) and crosses_on(bars, 0, D(620))
    assert not crosses_on(bars, 0, D(621))
    assert not crosses_on(bars, 3, D(612)) and not crosses_on(bars, -1, D(612))


def test_a_gap_over_the_cost_counts_on_the_day_it_jumps():
    up = [k("2026-01-05", 590, 600), k("2026-01-06", 620, 630)]
    assert not crosses_on(up, 0, D(612)) and crosses_on(up, 1, D(612))
    down = [k("2026-01-05", 620, 630), k("2026-01-06", 590, 600)]
    assert crosses_on(down, 1, D(612))
    assert not crosses_on(up, 0, D(625))  # the first bar has no day before it
    # touching the previous day's high is the previous day's own crossing, not a gap
    assert not crosses_on([k("2026-01-05", 590, 612), k("2026-01-06", 620, 630)], 1, D(612))


def test_the_most_recent_crossing_on_or_before_the_import_day():
    bars = [k("2025-03-03", 600, 615), k("2025-03-04", 620, 640), k("2025-08-14", 605, 618), k("2025-08-15", 630, 650),
            k("2025-12-02", 600, 620)]
    assert estimate_buy_date(bars, D(612), date(2025, 12, 1)) == date(2025, 8, 14)
    assert estimate_buy_date(bars, D(612), date(2025, 12, 2)) == date(2025, 12, 2)
    assert estimate_buy_date(bars, D(612), date(2025, 8, 13)) == date(2025, 3, 3)
    assert estimate_buy_date(bars, D(488), date(2025, 12, 1)) is None  # below every low: no estimate
    assert estimate_buy_date([], D(612), date(2025, 12, 1)) is None
    assert estimate_buy_date(bars, D(612), date(2025, 1, 1)) is None  # nothing on or before the day


def test_the_search_goes_back_five_years_and_us_stocks_to_2024_07_01():
    assert search_start(date(2026, 11, 19), us=False) == date(2021, 11, 19)
    assert search_start(date(2026, 11, 19), us=True) == US_HISTORY_FROM
    assert search_start(date(2028, 2, 29), us=False) == date(2023, 2, 28)
    assert search_start(date(2031, 8, 1), us=True) == date(2026, 8, 1)


def test_the_same_answers_as_the_front_end():
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    series = [[K(date.fromisoformat(b["t"]), D(str(b["l"])), D(str(b["h"]))) for b in s] for s in doc["series"]]
    found = 0
    limited = 0
    for case in doc["cases"]:
        start = date.fromisoformat(case["from"]) if case.get("from") else None
        got = estimate_buy_date(series[case["series"]], D(str(case["cost"])), date.fromisoformat(case["until"]), start)
        assert (got.isoformat() if got else None) == case["expected"], case
        found += got is not None
        limited += start is not None
    assert 40 < found < len(doc["cases"])
    assert limited > 20  # the share-count limit's cases (``from``) are in it


def test_the_search_starts_at_the_share_count_limit_and_its_gap_is_no_crossing():
    """``start``: the first day an imported buy may have (the latest split / reduction / stock dividend). Bars before
    it are left out, so the drop onto it is no gap «over» the cost."""
    bars = [k("2025-06-16", 180, 190), k("2025-06-17", 185, 192), k("2025-06-18", 46, 48), k("2025-06-19", 47, 50)]
    assert estimate_buy_date(bars, D(100), date(2025, 6, 19)) == date(2025, 6, 18)  # the rule alone: the split day
    assert estimate_buy_date(bars, D(100), date(2025, 6, 19), start=date(2025, 6, 18)) is None
    assert estimate_buy_date(bars, D(186), date(2025, 6, 19), start=date(2025, 6, 18)) is None
    assert estimate_buy_date(bars, D(186), date(2025, 6, 19)) == date(2025, 6, 17)
    assert estimate_buy_date(bars, D(47), date(2025, 6, 19), start=date(2025, 6, 18)) == date(2025, 6, 19)
    # the limit day itself is allowed
    assert estimate_buy_date(bars, D("46.5"), date(2025, 6, 18), start=date(2025, 6, 18)) == date(2025, 6, 18)
    # the import day before the first bar: nothing
    assert estimate_buy_date(bars, D(186), date(2025, 6, 1)) is None
