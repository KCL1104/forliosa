from datetime import date, datetime, time
from decimal import Decimal as D

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.marketdata.base import BaseProvider, QuoteData
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData
from forliosa.models import Instrument, PriceDaily
from forliosa.timeutil import TAIPEI
from forliosa.worker import daily_at, every, refresh_instruments, upsert_closes, weekly_at


def tp(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=TAIPEI)


def test_schedule_predicates():
    due = daily_at(time(14, 35))
    assert not due(tp(2026, 11, 11, 14, 0), None)
    assert due(tp(2026, 11, 11, 14, 40), None)
    assert not due(tp(2026, 11, 11, 14, 50), tp(2026, 11, 11, 14, 40))  # already ran for this slot
    assert due(tp(2026, 11, 12, 14, 36), tp(2026, 11, 11, 14, 40))
    ev = every(60)
    assert ev(tp(2026, 11, 11, 10, 0), None) and ev(tp(2026, 11, 11, 10, 0), tp(2026, 11, 11, 9, 59))
    assert not ev(tp(2026, 11, 11, 10, 0), datetime(2026, 11, 11, 9, 59, 30, tzinfo=TAIPEI))
    wk = weekly_at(5, time(10, 0))
    assert wk(tp(2026, 11, 14, 10, 5), None) and not wk(tp(2026, 11, 13, 10, 5), None)


class FakeReal(BaseProvider):
    name = "fake"

    def quotes(self, symbols):
        return {s: QuoteData(s, price=D("2395"), prev_close=D("2285"), open=D("2330"), high=D("2395"),
                             low=D("2305"), volume=33056476, trade_date=date(2026, 11, 11), source="fake")
                for s in symbols if s == "2330.TW"}


def test_upsert_closes_stores_only_real_prices(engine):
    md = MarketData([FakeReal(), DemoProvider()], policy="personal")
    with Session(engine) as db:
        assert upsert_closes(db, md, ["2330.TW", "AAPL"]) == 1  # AAPL is demo-only: not stored
        assert upsert_closes(db, md, ["2330.TW"]) == 1  # idempotent upsert
        rows = list(db.scalars(select(PriceDaily)))
        assert [(r.symbol, r.date, r.close) for r in rows] == [("2330.TW", date(2026, 11, 11), D("2395"))]
        assert refresh_instruments(db, md) > 10
        assert db.get(Instrument, "0050.TW").name == "元大台灣50"


def test_evening_and_weekly_runs_include_the_new_groups():
    from forliosa.archive import JOB_GROUPS
    from forliosa.worker import EVENING_GROUPS, WEEKLY_GROUPS

    assert {"taifex", "cbc", "companies", "financials"} <= set(EVENING_GROUPS)
    assert set(WEEKLY_GROUPS) == {"tdcc", "weekly"}
    assert set(EVENING_GROUPS) | set(WEEKLY_GROUPS) == set(JOB_GROUPS)
