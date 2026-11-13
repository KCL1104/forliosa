"""History backfill (PRICE_HISTORY_SOURCE=yahoo): parsing, what may be stored, who may read it, and removal."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa import history_backfill as hb
from forliosa.config import get_settings
from forliosa.datapolicy import HISTORY_SOURCE, allowed_sources, attributions, label
from forliosa.db import session_factory
from forliosa.marketdata import yahoo_history
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.base import ProviderUnavailable
from forliosa.marketdata.http import HttpStatusError
from forliosa.marketdata.service import MarketData
from forliosa.models import PriceBackfill, PriceDaily
from forliosa.services import coverage, instruments
from forliosa.timeutil import TAIPEI

FIX = Path(__file__).parent.parent / "marketdata" / "fixtures"
CHARTS = {"0050.TW": "yahoo_chart_0050_tw_live_20261113.json", "6488.TWO": "yahoo_chart_6488_two_live_20261113.json"}
TODAY = date(2026, 11, 13)


class FakeYahoo:
    """Serves the trimmed live chart responses; ``refuse`` makes every request answer that status."""

    def __init__(self, refuse: int | None = None, missing: tuple[str, ...] = ()):
        self.refuse, self.missing, self.asked = refuse, missing, []

    def get_json(self, url: str, params=None, headers=None):
        sym = url.rsplit("/", 1)[1]
        self.asked.append(sym)
        if self.refuse:
            raise HttpStatusError(f"HTTP {self.refuse}", self.refuse)
        if sym in self.missing or sym not in CHARTS:
            raise HttpStatusError("HTTP 404", 404)
        return json.loads((FIX / CHARTS[sym]).read_text(encoding="utf-8"))


@pytest.fixture()
def opted_in(monkeypatch):
    monkeypatch.setenv("PRICE_HISTORY_SOURCE", "yahoo")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("PRICE_HISTORY_SOURCE")
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def recheck_over(monkeypatch):
    """The one-off second try (``RECHECK_BEFORE``) is tested on its own; elsewhere a failed symbol stays failed."""
    monkeypatch.setattr(hb, "RECHECK_BEFORE", datetime(2020, 1, 1, tzinfo=TAIPEI))


@pytest.fixture()
def clock(monkeypatch):
    monkeypatch.setattr(hb, "now_taipei", lambda: datetime(2026, 11, 13, 22, 0, tzinfo=TAIPEI))


@pytest.fixture()
def db(engine):
    with session_factory()() as session:
        yield session


def official(db: Session, symbol: str, day: date, close: str, source: str = "twse-openapi") -> None:
    db.add(PriceDaily(symbol=symbol, date=day, open=Decimal(close), high=Decimal(close), low=Decimal(close),
                      close=Decimal(close), volume=1000, source=source))
    db.commit()


def test_parse_chart_dates_prices_and_empty_days():
    doc = json.loads((FIX / CHARTS["6488.TWO"]).read_text(encoding="utf-8"))
    bars = yahoo_history.parse_chart(doc)
    assert [b.date for b in bars][:2] == [date(2021, 11, 15), date(2021, 11, 16)]  # Taipei dates, not UTC
    assert date(2025, 8, 1) not in {b.date for b in bars}  # a day without a close is left out
    last = bars[-1]
    assert (last.date, last.close, last.volume) == (date(2026, 11, 13), Decimal("630.0000"), 8772396)
    # float noise from the source (35.23749923…) is rounded away
    first = yahoo_history.parse_chart(json.loads((FIX / CHARTS["0050.TW"]).read_text(encoding="utf-8")))[0]
    assert first.close == Decimal("35.2375")
    with pytest.raises(ProviderUnavailable):
        yahoo_history.parse_chart({"chart": {"result": None}})


def test_ticker_only_for_taiwan_symbols():
    assert yahoo_history.ticker("2330.TW") == "2330.TW"
    assert yahoo_history.ticker("6488.TWO") == "6488.TWO"
    assert yahoo_history.ticker("AAPL") is None


def test_backfill_stores_only_days_before_the_first_official_close(db, clock):
    official(db, "0050.TW", date(2026, 11, 12), "100.95")
    official(db, "0050.TW", date(2026, 11, 13), "102.50")
    res = hb.run_batch(db, FakeYahoo(), years=5)
    assert (res.asked, res.stored, res.blocked, res.remaining) == (1, 1, False, 0)
    rows = {r.date: r for r in db.scalars(select(PriceDaily).where(PriceDaily.symbol == "0050.TW"))}
    assert rows[date(2026, 11, 11)].source == HISTORY_SOURCE and rows[date(2026, 11, 11)].close == Decimal("103.2")
    assert rows[date(2021, 11, 15)].source == HISTORY_SOURCE
    # official rows stay official; today's bar from the source is never stored
    assert rows[date(2026, 11, 12)].source == "twse-openapi" and rows[date(2026, 11, 13)].source == "twse-openapi"
    assert res.rows == 7 == len([r for r in rows.values() if r.source == HISTORY_SOURCE])
    status = db.get(PriceBackfill, "0050.TW")
    assert (status.status, status.first_date, status.rows) == ("done", date(2021, 11, 15), 7)
    # asked once: a finished symbol is not requested again
    again = FakeYahoo()
    assert hb.run_batch(db, again, years=5).asked == 0 and again.asked == []


def test_backfill_rejects_a_series_that_disagrees_with_the_official_close(db, clock):
    official(db, "0050.TW", date(2026, 11, 12), "403.80")  # e.g. the source rescaled the series
    res = hb.run_batch(db, FakeYahoo(), years=5)
    assert res.stored == 0 and db.get(PriceBackfill, "0050.TW").status == "mismatch"
    assert db.scalar(select(func.count()).select_from(PriceDaily).where(PriceDaily.source == HISTORY_SOURCE)) == 0


def test_backfill_needs_an_official_day_to_compare_with(db, clock):
    official(db, "0050.TW", date(2026, 11, 13), "102.50")  # only today: its bar may still be moving
    res = hb.run_batch(db, FakeYahoo(), years=5)
    assert res.stored == 0 and db.get(PriceBackfill, "0050.TW").status == "no_overlap"
    # asked again only after half a day
    assert hb.pending(db) == []
    later = db.get(PriceBackfill, "0050.TW").updated_at + hb.RETRY_AFTER + timedelta(minutes=1)
    assert hb.pending(db, now=later) == ["0050.TW"]


def test_a_newest_bar_without_a_close_is_checked_by_its_range_and_never_stored(db, monkeypatch):
    """TPEx symbols: for hours after the session the source's newest bar has open, high and low but no close."""
    monkeypatch.setattr(hb, "now_taipei", lambda: datetime(2026, 11, 14, 0, 40, tzinfo=TAIPEI))
    doc = json.loads((FIX / CHARTS["6488.TWO"]).read_text(encoding="utf-8"))
    doc["chart"]["result"][0]["indicators"]["quote"][0]["close"][-1] = None  # 11/13: range 623–658, no close
    bars = yahoo_history.parse_chart(doc)
    assert bars[-1].date == date(2026, 11, 13) and bars[-1].close is None and bars[-1].high == Decimal("658")

    class NoClose(FakeYahoo):
        def get_json(self, url, params=None, headers=None):
            self.asked.append(url.rsplit("/", 1)[1])
            return doc

    official(db, "6488.TWO", date(2026, 11, 13), "630", source="tpex-openapi")  # inside the range
    res = hb.run_batch(db, NoClose(), years=5)
    assert (res.stored, db.get(PriceBackfill, "6488.TWO").status) == (1, "done")
    stored = {r.date: r for r in db.scalars(select(PriceDaily).where(PriceDaily.source == HISTORY_SOURCE))}
    assert date(2026, 11, 12) in stored and date(2026, 11, 13) not in stored and date(2025, 8, 1) not in stored

    official(db, "0050.TW", date(2026, 11, 13), "410")  # far outside 0050's range that day: not the same series
    doc0 = json.loads((FIX / CHARTS["0050.TW"]).read_text(encoding="utf-8"))
    doc0["chart"]["result"][0]["indicators"]["quote"][0]["close"][-1] = None

    class NoClose0(FakeYahoo):
        def get_json(self, url, params=None, headers=None):
            return doc0

    hb.run_batch(db, NoClose0(), years=5, symbols=["0050.TW"])
    assert db.get(PriceBackfill, "0050.TW").status == "mismatch"


def test_first_tries_that_failed_before_the_fix_are_asked_once_more(db, clock, monkeypatch):
    official(db, "0050.TW", date(2026, 11, 12), "403.80")
    hb.run_batch(db, FakeYahoo(), years=5)
    assert db.get(PriceBackfill, "0050.TW").status == "mismatch"
    monkeypatch.setattr(hb, "RECHECK_BEFORE", hb.now_utc() + timedelta(hours=1))
    assert hb.pending(db) == ["0050.TW"]  # its only try was before the fix
    hb.run_batch(db, FakeYahoo(), years=5)
    assert db.get(PriceBackfill, "0050.TW").attempts == 2 and hb.pending(db) == []  # asked once more, not for ever


def test_unknown_symbol_is_final_and_a_refusal_stops_the_run(db, clock):
    official(db, "0050.TW", date(2026, 11, 12), "100.95")
    official(db, "9999.TW", date(2026, 11, 12), "10")
    res = hb.run_batch(db, FakeYahoo(missing=("9999.TW",)), years=5)
    assert (res.asked, res.stored) == (2, 1) and db.get(PriceBackfill, "9999.TW").status == "not_found"

    official(db, "6488.TWO", date(2026, 11, 12), "622", source="tpex-openapi")
    refused, waits = FakeYahoo(refuse=403), []
    res = hb.run_batch(db, refused, years=5, sleep=waits.append)
    assert res.blocked and res.asked == 0 and refused.asked == ["6488.TWO"] and waits == []
    assert db.get(PriceBackfill, "6488.TWO") is None  # nothing recorded: it is asked again later
    assert hb.pending(db) == ["6488.TWO"]


def test_429_waits_and_asks_again_then_gives_up(db, clock):
    official(db, "6488.TWO", date(2026, 11, 12), "622", source="tpex-openapi")
    limited, waits = FakeYahoo(refuse=429), []
    res = hb.run_batch(db, limited, years=5, sleep=waits.append)
    assert res.blocked and res.asked == 0
    assert limited.asked == ["6488.TWO"] * 3 and waits == list(hb.RATE_LIMIT_WAITS)

    class OnceLimited(FakeYahoo):
        def get_json(self, url, params=None, headers=None):
            self.refuse = 429 if not self.asked else None
            return super().get_json(url, params, headers)

    flaky, waits = OnceLimited(), []
    res = hb.run_batch(db, flaky, years=5, sleep=waits.append)
    assert (res.asked, res.stored, res.blocked) == (1, 1, False) and waits == [hb.RATE_LIMIT_WAITS[0]]


def test_held_symbols_are_asked_first_and_the_limit_is_kept(db, clock, monkeypatch):
    for sym in ("0050.TW", "6488.TWO"):
        official(db, sym, date(2026, 11, 12), "100.95" if sym == "0050.TW" else "622")
    monkeypatch.setattr(hb, "tracked_symbols", lambda _db: ["6488.TWO"])
    assert hb.pending(db) == ["6488.TWO", "0050.TW"]
    fake = FakeYahoo()
    res = hb.run_batch(db, fake, years=5, limit=1)
    assert fake.asked == ["6488.TWO"] and res.remaining == 1


def _md(policy: str = "commercial") -> MarketData:
    return MarketData([ArchiveProvider(policy, lambda: session_factory()())], policy=policy)


def test_only_charts_read_the_backfill_and_only_when_switched_on(db, clock, opted_in):
    official(db, "0050.TW", date(2026, 11, 12), "100.95")
    hb.run_batch(db, FakeYahoo(), years=5)
    md = _md()
    start, end = date(2021, 11, 1), date(2026, 11, 12)
    # ledger valuation, performance, recurring plans: official closes only
    assert [c.t for c in md.history("0050.TW", start, end).candles] == [date(2026, 11, 12)]
    assert md.archive_since("0050.TW") == date(2026, 11, 12)
    # charts
    chart = md.history("0050.TW", start, end, backfill=True)
    assert chart.candles[0].t == date(2021, 11, 15) and len(chart.candles) == 8
    assert set(chart.source.split("+")) == {HISTORY_SOURCE, "twse-openapi"}
    assert md.backfill_until("0050.TW") == date(2026, 11, 11)
    notes = coverage.series_notes(md, "0050.TW", date(2021, 11, 14), date(2021, 11, 15), backfill=True)
    assert notes == ["2026/11/11 以前的日線來自 Yahoo Finance，不是官方資料；股票分割前的價格已經換算"]
    # a series that starts later than asked says where it starts, then names the source
    short = coverage.series_notes(md, "0050.TW", date(2016, 11, 14), date(2021, 11, 15), backfill=True)
    assert short[0] == "資料從 2021/11/15 開始" and len(short) == 2
    assert HISTORY_SOURCE in allowed_sources("commercial", backfill=True)
    assert HISTORY_SOURCE not in allowed_sources("commercial")
    assert label(HISTORY_SOURCE) == "Yahoo Finance（歷史日線，非官方資料）"
    listed = [d for d in attributions("commercial")["datasets"] if d["key"] == HISTORY_SOURCE]
    assert listed and listed[0]["commercial"] is False and listed[0]["license_status"] == "non_commercial"


def test_switched_off_nothing_reads_the_rows(db, clock):
    official(db, "0050.TW", date(2026, 11, 12), "100.95")
    hb.run_batch(db, FakeYahoo(), years=5)  # rows exist (e.g. the switch was turned off afterwards)
    get_settings.cache_clear()
    for policy in ("commercial", "personal"):
        md = _md(policy)
        chart = md.history("0050.TW", date(2021, 11, 1), date(2026, 11, 12), backfill=True)
        assert [c.t for c in chart.candles] == [date(2026, 11, 12)]
        assert md.backfill_until("0050.TW") is None
    assert HISTORY_SOURCE not in allowed_sources("commercial", backfill=True)
    assert all(d["key"] != HISTORY_SOURCE for d in attributions("commercial")["datasets"])


def test_history_endpoint_shows_the_backfill_with_its_note(db, clock, opted_in, monkeypatch):
    official(db, "0050.TW", date(2026, 11, 12), "100.95")
    hb.run_batch(db, FakeYahoo(), years=5)
    md = _md()
    monkeypatch.setattr(instruments, "today_taipei", lambda: date(2026, 11, 13))
    monkeypatch.setattr(instruments, "require_instrument",
                        lambda _md, s: type("I", (), {"symbol": "0050.TW", "market": "TWSE"})())
    out = instruments.history(md, "0050.TW", "5Y")
    assert out["candles"][0]["t"] == date(2021, 11, 15) and out["candles"][-1]["t"] == date(2026, 11, 12)
    assert any("Yahoo Finance" in s for s in out["sources"])
    assert out["notes"] == ["2026/11/11 以前的日線來自 Yahoo Finance，不是官方資料；股票分割前的價格已經換算"]


def test_drop_removes_every_backfilled_row_and_keeps_official_ones(db, clock):
    official(db, "0050.TW", date(2026, 11, 12), "100.95")
    hb.run_batch(db, FakeYahoo(), years=5)
    assert hb.summary(db)["rows"] == 7
    assert hb.drop(db) == 7
    left = list(db.scalars(select(PriceDaily)))
    assert [(r.date, r.source) for r in left] == [(date(2026, 11, 12), "twse-openapi")]
    assert db.scalar(select(func.count()).select_from(PriceBackfill)) == 0
    assert hb.pending(db) == ["0050.TW"]
