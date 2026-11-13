"""GET /meta/market-status: is the Taiwan market in session (official calendar, 09:00–13:30 Taipei)? No session."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from forliosa import market_calendar
from forliosa.models import MarketHoliday
from forliosa.timeutil import TAIPEI

URL = "/api/v1/meta/market-status"
FRIDAY = (2026, 11, 13)  # a trading day
SATURDAY = (2026, 11, 14)
NATIONAL_DAY_HOLIDAY = (2026, 10, 9)  # closed in the built-in calendar


@pytest.fixture()
def at():
    """Set the clock of the endpoint (Taipei time unless a tzinfo is given)."""

    def set_clock(*args: int, tz=TAIPEI) -> None:
        market_calendar.set_clock(lambda: datetime(*args, tzinfo=tz))

    yield set_clock
    market_calendar.set_clock(None)


def status(app) -> dict:
    r = TestClient(app).get(URL)  # no session
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"tw"} and set(body["tw"]) == {"date", "is_trading_day", "is_open", "open", "close"}
    assert (body["tw"]["open"], body["tw"]["close"]) == ("09:00", "13:30")
    return body["tw"]


@pytest.mark.parametrize(("clock", "is_open"), [
    ((8, 59, 59), False),  # before the open
    ((9, 0, 0), True),  # the open
    ((11, 0, 0), True),  # during the session
    ((13, 29, 59, 999999), True),
    ((13, 30, 0), False),  # exactly 13:30: the session has closed
    ((13, 30, 0, 1), False),
    ((14, 40, 0), False),  # after the close
    ((23, 59, 59), False),
    ((0, 0, 0), False),
])
def test_trading_day(app, at, clock, is_open):
    at(*FRIDAY, *clock)
    assert status(app) == {"date": "2026-11-13", "is_trading_day": True, "is_open": is_open, "open": "09:00",
                           "close": "13:30"}


@pytest.mark.parametrize("day", [SATURDAY, (2026, 11, 15), NATIONAL_DAY_HOLIDAY])
def test_weekend_and_holiday_are_closed_all_day(app, at, day):
    for clock in ((8, 0), (9, 0), (11, 0), (13, 30), (20, 0)):
        at(*day, *clock)
        tw = status(app)
        assert tw["date"] == date(*day).isoformat()
        assert (tw["is_trading_day"], tw["is_open"]) == (False, False), (day, clock)


def test_official_calendar_decides(app, at, engine):
    """An official closure that the built-in list does not know (a typhoon day), and a built-in holiday the official
    schedule of that year does not list."""
    at(2026, 11, 12, 10, 0)
    assert status(app)["is_open"] is True
    with Session(engine) as db:
        db.add(MarketHoliday(date=date(2026, 11, 12), name="颱風停止交易", description="", is_trading_day=False,
                             source="twse-openapi"))
        db.add(MarketHoliday(date=date(2026, 1, 2), name="國曆新年開始交易日", description="", is_trading_day=True,
                             source="twse-openapi"))
        db.commit()
    tw = status(app)
    assert (tw["date"], tw["is_trading_day"], tw["is_open"]) == ("2026-11-12", False, False)
    at(2026, 1, 2, 10, 0)  # a trading-day marker is not a closure
    assert status(app)["is_open"] is True
    at(*NATIONAL_DAY_HOLIDAY, 10, 0)  # the official schedule of 2026 replaces the built-in list of that year
    assert status(app)["is_trading_day"] is True
    at(*SATURDAY, 10, 0)
    assert status(app)["is_trading_day"] is False


def test_the_date_and_the_session_are_taipei_time(app, at):
    at(2026, 11, 13, 1, 0, tz=UTC)  # 09:00 in Taipei
    assert status(app) == {"date": "2026-11-13", "is_trading_day": True, "is_open": True, "open": "09:00",
                           "close": "13:30"}
    at(2026, 11, 12, 16, 30, tz=UTC)  # already 00:30 on the 13th in Taipei
    assert (status(app)["date"], status(app)["is_open"]) == ("2026-11-13", False)
    at(2026, 11, 13, 5, 30, tz=UTC)  # 13:30 in Taipei
    assert status(app)["is_open"] is False


def test_no_session_no_user_data_and_view_as_is_ignored(app, client, at):
    at(*FRIDAY, 10, 0)
    anonymous = TestClient(app).get(URL)
    signed_in = client.get(URL)
    under_view_as = client.get(URL, headers={"X-Forliosa-View-As": "dlg_whatever"})
    assert anonymous.status_code == signed_in.status_code == under_view_as.status_code == 200
    assert anonymous.json() == signed_in.json() == under_view_as.json()
    assert "set-cookie" not in anonymous.headers
