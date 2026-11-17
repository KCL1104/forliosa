"""行事曆 (contract §7.6): settlement days, NYSE holidays in ``timeutil``, Eastern → Taipei times, folding, official
links only, the seeds."""

from __future__ import annotations

import logging
from datetime import date, datetime, time

from sqlalchemy import select

from forliosa.models import MacroCalendarEvent, NyseHoliday, UsEarningsDate
from forliosa.reports import blocks, calendars
from forliosa.timeutil import (
    TAIPEI,
    is_us_trading_day,
    last_us_session,
    set_official_holidays,
    set_us_calendar,
    us_close_dt,
)
from tests.reports.conftest import MON, TUE, ts


def test_settlement_is_the_third_wednesday_moved_past_a_closure():
    assert calendars.settlement_day(2026, 11) == date(2026, 11, 18)
    set_official_holidays([date(2026, 11, 18)], [2026])
    try:
        assert calendars.settlement_day(2026, 11) == date(2026, 11, 19)
    finally:
        set_official_holidays([], [])
    assert calendars.settlement_days(date(2026, 11, 1), date(2026, 12, 31)) == [date(2026, 11, 18),
                                                                                date(2026, 12, 16)]


def test_eastern_to_taipei_in_winter_and_summer():
    assert calendars.to_taipei(date(2026, 11, 20), "08:30", "America/New_York") == ts(date(2026, 11, 20), 21, 30)
    assert calendars.to_taipei(date(2026, 7, 15), "08:30", "America/New_York") == ts(date(2026, 7, 15), 20, 30)
    assert calendars.to_taipei(date(2026, 11, 20), None, "America/New_York") is None
    assert calendars.earnings_label(date(2026, 11, 19), "amc") == "美東 11/19 盤後（台北 11/20 清晨）"
    assert calendars.earnings_label(date(2026, 11, 19), "bmo") == "美東 11/19 盤前（台北 11/19 晚上）"
    assert calendars.earnings_label(date(2026, 11, 19), "amc", "16:05") == "美東 11/19 16:05（台北 11/20 05:05）"
    assert calendars.earnings_label(date(2026, 11, 19), "unknown") == "美東 11/19"


def test_nyse_holidays_reach_timeutil(db):
    calendars.seed(db)
    try:
        assert not is_us_trading_day(date(2026, 11, 26))
        assert us_close_dt(date(2026, 11, 27)).time() == time(13, 0)
        # Friday 11/27 05:00 Taipei: Wednesday 11/25 is the latest session (Thursday was closed)
        assert last_us_session(datetime(2026, 11, 27, 5, 30, tzinfo=TAIPEI)) == date(2026, 11, 25)
        assert last_us_session(datetime(2026, 11, 28, 3, 30, tzinfo=TAIPEI)) == date(2026, 11, 27)  # the early close
    finally:
        set_us_calendar([])


def test_seed_is_idempotent_and_keeps_checked_rows(db):
    first = calendars.seed(db)
    assert first["nyse_holidays"] == 15 and first["macro_calendar"] == 0 and first["us_earnings"] == 0
    row = db.get(NyseHoliday, date(2026, 11, 26))
    assert row.verified_at is None and row.source_url == calendars.NYSE_URL
    row.name, row.verified_at = "感恩節（已核對）", datetime(2026, 11, 18, 1, tzinfo=TAIPEI)
    db.commit()
    again = calendars.seed(db)
    assert again["nyse_holidays"] == 14  # the checked row is left alone
    assert db.get(NyseHoliday, date(2026, 11, 26)).name == "感恩節（已核對）"
    assert calendars.nyse_status(db, date(2026, 11, 17))["unverified"] == 14
    set_us_calendar([])


def test_the_worker_seeds_an_empty_table_once(db):
    assert calendars.ensure_seeded(db) is True
    assert calendars.ensure_seeded(db) is False  # rows exist: left to the admins
    assert calendars.load_us_calendar(db) == 15
    set_us_calendar([])


def test_official_links_only():
    assert calendars.official_url_ok("https://www.bls.gov/schedule/news_release/cpi.htm")
    assert calendars.official_url_ok("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm")
    assert calendars.official_url_ok("https://www.dgbas.gov.tw/News.aspx")
    assert not calendars.official_url_ok("https://www.investing.com/economic-calendar/")
    assert not calendars.official_url_ok("http://www.bls.gov/")
    assert not calendars.official_url_ok("https://bls.gov.example.com/")
    assert calendars.earnings_url_ok("https://investor.nvidia.com/events")
    assert not calendars.earnings_url_ok("https://www.marketbeat.com/earnings/")
    assert calendars.earnings_url_ok(None)


def test_events_fold_etf_reit_invited_and_small_filings(market_db, caplog):
    market_db.add(MacroCalendarEvent(id="mac_1", event_date=date(2026, 11, 16), local_time="08:30",
                                     tz="America/New_York", country="US", title="美國 10 月零售銷售", agency="Census",
                                     official_url="https://www.census.gov/retail/", sectors=[],
                                     updated_at=datetime(2026, 11, 10, tzinfo=TAIPEI)))
    market_db.add(UsEarningsDate(id="use_1", symbol="NVDA", company="NVIDIA", report_date=date(2026, 11, 16),
                                 timing="amc", sectors=["半導體"], updated_at=datetime(2026, 11, 10, tzinfo=TAIPEI)))
    market_db.commit()
    with caplog.at_level(logging.WARNING):
        events = calendars.events_between(market_db, MON, TUE, cutoff=ts(TUE, 6, 55), top100=["2330.TW"])
    kinds = {(e.date, e.kind) for e in events}
    assert (TUE, "investor_conference") in kinds and (MON, "macro") in kinds and (TUE, "us_earnings") in kinds
    macro = next(e for e in events if e.kind == "macro")
    assert macro.time_label == "台北 21:30" and macro.url.startswith("https://www.census.gov/")
    nvda = next(e for e in events if e.kind == "us_earnings")
    assert nvda.time_label == "美東 11/16 盤後（台北 11/17 清晨）" and nvda.sectors == ["半導體"]
    ex = {e.symbol: e.fold for e in events if e.kind == "ex_dividend"}
    assert ex == {"0050.TW": "etf_ex", "01007T.TW": "reit_ex", "2881.TW": None}
    conf = next(e for e in events if e.kind == "investor_conference")
    assert conf.title == "鴻海（2317）法說會" and conf.fold == "invited_conference"
    assert not any(e.symbol == "24552.TWO" for e in events)  # not a listed stock or fund code
    filings = [e for e in events if e.kind == "material_info"]
    assert {e.symbol for e in filings} == {"2330.TW", "2317.TW"}
    assert next(e for e in filings if e.symbol == "2317.TW").fold == "other_filings"
    # the block folds them into one line each
    block = blocks.calendar_block(events, title="今日行事曆")
    tue = next(g for g in block["groups"] if g["date"] == "2026-11-17")
    assert {f["label"] for f in tue["folded"]} >= {"ETF 除息 1 檔", "REIT 除息 1 檔", "受邀參加法說會 1 家"}
    assert any(r["href"] == "/stock/2881.TW" for r in tue["rows"])


def test_rows_added_after_the_cutoff_are_not_listed(market_db):
    market_db.add(MacroCalendarEvent(id="mac_late", event_date=date(2026, 11, 16), local_time="10:00",
                                     tz="America/New_York", country="US", title="很晚才加的", agency="BLS",
                                     official_url="https://www.bls.gov/", sectors=[],
                                     updated_at=datetime(2026, 11, 17, 3, tzinfo=TAIPEI)))
    market_db.commit()
    events = calendars.events_between(market_db, MON, MON, cutoff=ts(MON, 15, 40))
    assert not any(e.title == "很晚才加的" for e in events)
    assert not any(e.title.endswith("晚上的公告") for e in events)  # filed 17:30, after the cut-off
    assert market_db.scalar(select(MacroCalendarEvent.id).where(MacroCalendarEvent.id == "mac_late"))
