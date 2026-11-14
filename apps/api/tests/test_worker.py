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


def test_late_slots_still_run_just_after_midnight():
    """2026-11-14 review: a 23:45 slot reached only after midnight (the loop was busy) was skipped for good."""
    due = daily_at(time(23, 45))
    assert due(tp(2026, 11, 12, 0, 20), tp(2026, 11, 11, 14, 40))
    assert not due(tp(2026, 11, 12, 0, 20), tp(2026, 11, 11, 23, 50))  # already ran for that slot
    assert not due(tp(2026, 11, 12, 3, 0), tp(2026, 11, 11, 14, 40))  # more than 3 hours late: skipped
    # the guard is about the slot's day: Friday 23:45 still runs at 00:20 on Saturday
    trading = daily_at(time(23, 45), only_if=lambda n: n.weekday() < 5)
    assert trading(tp(2026, 11, 14, 0, 20), tp(2026, 11, 13, 14, 40))
    assert not trading(tp(2026, 11, 15, 0, 20), tp(2026, 11, 13, 23, 50))  # Saturday's slot: not a trading day


def test_upsert_closes_never_overwrites_an_official_archive_row(engine):
    """2026-11-14 review: a merged-source quote overwrote the archive's official row, and commercial mode (which only
    serves exact official sources) then lost that day."""

    class Merged(BaseProvider):
        name = "merged"

        def quotes(self, symbols):
            return {s: QuoteData(s, price=D("2400"), prev_close=D("2285"), trade_date=date(2026, 11, 11),
                                 source="twse-openapi+shioaji-data") for s in symbols if s == "2330.TW"}

    with Session(engine) as db:
        db.add(PriceDaily(symbol="2330.TW", date=date(2026, 11, 11), open=D("2330"), high=D("2395"), low=D("2305"),
                          close=D("2395"), volume=33056476, source="twse-openapi"))
        db.commit()
        upsert_closes(db, MarketData([Merged()], policy="personal"), ["2330.TW"])
        db.expire_all()
        row = db.scalars(select(PriceDaily)).one()
        assert (row.source, row.close, row.open) == ("twse-openapi", D("2395"), D("2330"))


def test_evening_and_weekly_runs_include_the_new_groups():
    from forliosa.archive import JOB_GROUPS
    from forliosa.worker import EVENING_GROUPS, MONTHLY_GROUPS, SEC_GROUPS, WEEKLY_GROUPS, Worker

    assert {"taifex", "cbc", "companies", "financials", "nav"} <= set(EVENING_GROUPS)
    # the NAV file only holds each fund's latest NAV: the 08:10 run reads it again for NAVs posted after 21:40
    from forliosa.worker import MORNING_GROUPS

    assert MORNING_GROUPS == ["twse", "tpex", "nav"]
    assert set(WEEKLY_GROUPS) == {"tdcc", "weekly"}
    assert set(EVENING_GROUPS) | set(WEEKLY_GROUPS) | set(SEC_GROUPS) | set(MONTHLY_GROUPS) == set(JOB_GROUPS)
    # SEC EDGAR runs every day (US filings do not follow the Taiwan trading calendar), after the US close
    job = next(j for j in Worker(md=object()).jobs if j.name == "sec_archive")  # type: ignore[arg-type]
    from datetime import datetime

    from forliosa.timeutil import TAIPEI

    saturday = datetime(2026, 11, 14, 7, 55, tzinfo=TAIPEI)
    assert job.due(saturday, None) and not job.due(saturday.replace(hour=7, minute=40), None)


def test_sharing_jobs_and_the_worker_secret_check():
    import pytest

    from forliosa.config import DEFAULT_SESSION_SECRET, Settings
    from forliosa.worker import Worker, check_worker_settings

    names = {j.name for j in Worker(md=object()).jobs}  # type: ignore[arg-type]
    assert {"group_push", "telegram_poll", "group_digests", "group_digest_poll", "sharing_retention"} <= names
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        check_worker_settings(Settings(forliosa_env="prod", session_secret=DEFAULT_SESSION_SECRET))
    check_worker_settings(Settings(forliosa_env="prod", session_secret="x" * 48))
    check_worker_settings(Settings(forliosa_env="dev"))


def test_a_background_job_never_holds_up_the_others(monkeypatch):
    """telegram_poll runs in its own loop: a slow job in the main loop (an archive run) does not keep it waiting, and
    a slow poll (a flood of messages) would not delay the main loop either."""
    import asyncio

    import forliosa.worker as worker_mod
    from forliosa.worker import Job, Worker

    class NoCalendar:
        def __enter__(self):
            return None

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(worker_mod, "session_factory", lambda: NoCalendar)
    monkeypatch.setattr(worker_mod, "load_official_calendar", lambda _db: None)

    async def scenario() -> tuple[int, int]:
        polls = 0
        release = asyncio.Event()

        async def slow() -> None:  # a long job in the main loop
            await release.wait()

        async def poll() -> None:
            nonlocal polls
            polls += 1

        worker = Worker(md=object())  # type: ignore[arg-type]
        always = lambda _now, _last: True  # noqa: E731
        worker.jobs = [Job("slow", always, slow), Job("poll", always, poll, background=True)]
        running = asyncio.create_task(worker.run(tick_seconds=0.01))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if polls >= 3:
                break
        during = polls  # polled again and again while the slow job was still running
        worker.stop()
        release.set()
        await asyncio.wait_for(running, timeout=2)
        return during, polls

    during, _total = asyncio.run(scenario())
    assert during >= 3
    assert next(j for j in Worker(md=object()).jobs if j.name == "telegram_poll").background  # type: ignore[arg-type]

def test_expired_login_sessions_are_purged_daily(engine):
    import asyncio
    from datetime import timedelta

    from forliosa.models import User, UserSession
    from forliosa.timeutil import now_utc
    from forliosa.worker import Worker

    worker = Worker(md=object())  # type: ignore[arg-type]
    job = next(j for j in worker.jobs if j.name == "session_purge")
    assert job.due(tp(2026, 11, 14, 4, 55), None)  # every day, weekends included
    assert not job.due(tp(2026, 11, 14, 4, 40), None)
    assert not job.due(tp(2026, 11, 14, 5, 15), tp(2026, 11, 14, 4, 55))  # once a day
    now = now_utc()
    with Session(engine) as db:
        db.add(User(id="usr_1", email="a@example.com", display_name="A"))
        db.add_all([UserSession(id="expired", user_id="usr_1", expires_at=now - timedelta(seconds=1)),
                    UserSession(id="long-gone", user_id="usr_1", expires_at=now - timedelta(days=40)),
                    UserSession(id="valid", user_id="usr_1", expires_at=now + timedelta(days=1))])
        db.commit()
    asyncio.run(job.run())
    with Session(engine) as db:
        assert [s.id for s in db.scalars(select(UserSession))] == ["valid"]
    asyncio.run(job.run())  # nothing left to delete: still fine
    with Session(engine) as db:
        assert db.get(UserSession, "valid") is not None and db.get(User, "usr_1") is not None


def test_monthly_archive_and_company_refresh_schedule():
    from datetime import datetime

    from forliosa.timeutil import TAIPEI
    from forliosa.worker import Worker

    jobs = {j.name: j for j in Worker(md=object()).jobs}  # type: ignore[arg-type]
    monthly = jobs["monthly_archive"]
    assert monthly.due(datetime(2026, 11, 25, 10, 30, tzinfo=TAIPEI), None)
    assert not monthly.due(datetime(2026, 11, 24, 10, 30, tzinfo=TAIPEI), None)
    company = jobs["company_refresh"]
    assert company.due(datetime(2026, 11, 12, 13, 36, tzinfo=TAIPEI), None)


def test_daily_briefings_job_runs_evening_and_morning_and_follows_the_master_switch(monkeypatch):
    from datetime import datetime

    from forliosa.config import get_settings
    from forliosa.timeutil import TAIPEI
    from forliosa.worker import Worker

    job = next(j for j in Worker(md=object()).jobs if j.name == "daily_briefings")  # type: ignore[arg-type]
    at = lambda *a: datetime(*a, tzinfo=TAIPEI)  # noqa: E731
    assert job.due(at(2026, 11, 12, 22, 21), None) and not job.due(at(2026, 11, 12, 22, 10), None)
    # the exchanges publish between the evening and the early morning: later slots catch up, also on a Saturday
    assert job.due(at(2026, 11, 12, 23, 51), at(2026, 11, 12, 22, 21))
    assert job.due(at(2026, 11, 13, 6, 11), at(2026, 11, 12, 23, 51))
    assert job.due(at(2026, 11, 14, 8, 21), at(2026, 11, 14, 6, 11))
    assert not job.due(at(2026, 11, 14, 9, 0), at(2026, 11, 14, 8, 21))
    monkeypatch.setenv("AI_DAILY_BRIEFING_ENABLED", "false")
    get_settings.cache_clear()
    try:
        assert "daily_briefings" not in {j.name for j in Worker(md=object()).jobs}  # type: ignore[arg-type]
    finally:
        monkeypatch.delenv("AI_DAILY_BRIEFING_ENABLED")
        get_settings.cache_clear()


def test_daily_briefings_job_writes_through_the_worker(engine, market, monkeypatch):
    import asyncio
    from datetime import datetime

    from forliosa.ai import briefing
    from forliosa.timeutil import TAIPEI
    from forliosa.worker import Worker

    seen = {}

    def fake_run(db, md, now=None, **_kw):
        seen["now"], seen["md"] = now, md
        return briefing.RunResult(day=now.date(), written=2, with_points=1, purged=0)

    monkeypatch.setattr(briefing, "run", fake_run)
    clock = datetime(2026, 11, 12, 22, 20, tzinfo=TAIPEI)
    worker = Worker(md=market, now_fn=lambda: clock)
    asyncio.run(worker.daily_briefings())
    assert seen == {"now": clock, "md": market}
