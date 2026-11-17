"""Editions and their times (contract §5.2): trading days only for the daily ones, Sundays for the weekly, the US
sessions a 盤前重點 covers (all of them after a long holiday), the review and next weeks, labels."""

from __future__ import annotations

from datetime import date

from forliosa.reports.schedule import edition_for, edition_on
from forliosa.timeutil import set_official_holidays, set_us_calendar
from tests.reports.conftest import ts


def test_daily_editions_only_on_trading_days():
    assert edition_on("premarket", date(2026, 11, 14)) is None  # Saturday
    assert edition_on("close", date(2026, 12, 25)) is None  # a TWSE holiday (built-in list)
    assert edition_on("weekly", date(2026, 11, 16)) is None  # not a Sunday
    assert edition_for("close", ts(date(2026, 11, 16), 9)).edition_date == date(2026, 11, 16)


def test_premarket_times_and_us_sessions():
    ed = edition_on("premarket", date(2026, 11, 17))
    assert ed.prev_session == date(2026, 11, 16) and ed.us_sessions == (date(2026, 11, 16),)
    assert (ed.gather_at, ed.data_at, ed.write_at, ed.write_latest) == (
        ts(date(2026, 11, 17), 6, 15), ts(date(2026, 11, 17), 6, 55), ts(date(2026, 11, 17), 7),
        ts(date(2026, 11, 17), 7, 5))
    assert (ed.push_at, ed.push_fallback_at, ed.close_at) == (
        ts(date(2026, 11, 17), 7, 30), ts(date(2026, 11, 17), 8, 15), ts(date(2026, 11, 17), 8, 40))
    assert ed.web_from == ts(date(2026, 11, 16), 13, 30) and ed.label == "11/17（二）"
    monday = edition_on("premarket", date(2026, 11, 16))
    assert monday.us_sessions == (date(2026, 11, 13),) and not monday.long_holiday


def test_premarket_after_a_long_holiday_covers_every_us_session_and_skips_us_holidays():
    set_official_holidays([date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 25), date(2026, 12, 25)], [2026])
    set_us_calendar([date(2026, 11, 26)])
    try:
        ed = edition_on("premarket", date(2026, 11, 26))  # Taiwan closed Monday to Wednesday
        assert ed.prev_session == date(2026, 11, 20) and ed.long_holiday
        assert ed.us_sessions == (date(2026, 11, 20), date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 25))
        friday = edition_on("premarket", date(2026, 11, 27))  # the US was closed on Thanksgiving
        assert friday.prev_session == date(2026, 11, 26) and friday.us_sessions == () and not friday.long_holiday
    finally:
        set_official_holidays([], [])


def test_close_times_and_tables():
    ed = edition_on("close", date(2026, 11, 16))
    assert ed.data_at == ts(date(2026, 11, 16), 14, 10) and ed.cutoff == ts(date(2026, 11, 16), 15, 40)
    assert ed.publish_target == ts(date(2026, 11, 16), 15, 55) and ed.push_at == ts(date(2026, 11, 16), 16)
    assert ed.close_at == ts(date(2026, 11, 16), 17, 30) and ed.skip_check_at == ts(date(2026, 11, 16), 15)
    assert ed.tables_at == (ts(date(2026, 11, 16), 23, 45), ts(date(2026, 11, 17), 6, 40))
    assert ed.web_from == ts(date(2026, 11, 16), 8) and ed.web_to == ts(date(2026, 11, 16), 15, 50)


def test_weekly_reviews_monday_to_friday_and_lists_the_next_week():
    ed = edition_on("weekly", date(2026, 11, 22))
    assert ed.period == (date(2026, 11, 16), date(2026, 11, 20))
    assert ed.next_period == (date(2026, 11, 23), date(2026, 11, 27))
    assert ed.push_at == ts(date(2026, 11, 22), 18) and ed.close_at == ts(date(2026, 11, 22), 21)
    assert ed.label == "11/16–11/20 回顧" and ed.kind_label == "市場週報"
    assert len(ed.us_sessions) == 5
