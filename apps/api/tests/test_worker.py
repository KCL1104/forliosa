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
    from forliosa.worker import EVENING_GROUPS, SEC_GROUPS, WEEKLY_GROUPS, Worker

    assert {"taifex", "cbc", "companies", "financials"} <= set(EVENING_GROUPS)
    assert set(WEEKLY_GROUPS) == {"tdcc", "weekly"}
    assert set(EVENING_GROUPS) | set(WEEKLY_GROUPS) | set(SEC_GROUPS) == set(JOB_GROUPS)
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
