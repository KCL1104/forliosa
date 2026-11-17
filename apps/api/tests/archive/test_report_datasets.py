"""The market reports' archive additions (2026-11-17): FMTQIK, MI_5MINS_HIST (OHLC only), TWT85U (altered trading),
each security's 成交金額, and the guard that keeps an evening read of a dateless file from stamping yesterday's
numbers with today's date."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal as D

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.archive import Archiver
from forliosa.marketdata import opendata as od
from forliosa.models import (
    DatasetStatus,
    ForeignHoldingTop20,
    IndexDaily,
    MarginDaily,
    MarketEvent,
    MarketTurnoverDaily,
    PriceDaily,
)
from forliosa.timeutil import TAIPEI
from tests.archive.fakes import NOW, FakeFetcher, load

D11 = date(2026, 11, 11)


def archiver(db: Session, now=NOW) -> Archiver:
    return Archiver(db, FakeFetcher(), "commercial", now_fn=lambda: now)


def test_parsers():
    rows = od.parse_fmtqik(load("twse_fmtqik_live_20261117.json"))
    last = rows[-1]
    assert last["date"] == D11 and last["trade_value"] == 876_295_459_349 and last["taiex"] == D("44257.15")
    assert last["change"] == D("1545.23") and last["transactions"] == 3_928_796
    ohlc = od.parse_mi_5mins_hist(load("twse_mi_5mins_hist_live_20261117.json"))
    assert ohlc[-1] == {"date": D11, "open": D("43135.76"), "high": D("44257.15"), "low": D("42708.05"),
                        "close": D("44257.15")}
    alt = od.parse_twt85u(load("twse_twt85u_live_20261117.json"))
    assert len(alt) == 10 and {"code": "2314", "name": "台揚", "periodic_call_auction": True} in alt
    assert {"code": "1213", "name": "大飲", "periodic_call_auction": False} in alt


def test_turnover_ohlc_and_trade_value_are_archived(engine, market):
    with Session(engine) as db:
        a = archiver(db)
        a.twse_prices()
        a.tpex_prices()
        a.twse_indices()
        assert a.twse_turnover() == 8
        assert a.twse_index_ohlc() == 1  # only 11/11 has a stored TAIEX row
        row = db.get(MarketTurnoverDaily, (D11, "TWSE"))
        assert row.trade_value == 876_295_459_349 and row.source == "twse-openapi"
        taiex = db.get(IndexDaily, ("發行量加權股價指數", D11))
        assert (taiex.open, taiex.high, taiex.low) == (D("43135.76"), D("44257.15"), D("42708.05"))
        assert taiex.close == D("44257.15") and taiex.change == D("1545.23")  # MI_INDEX's own close and change
        assert db.get(IndexDaily, ("發行量加權股價指數", date(2026, 11, 10))) is None  # no row is made up
        assert db.get(DatasetStatus, "twse-openapi/turnover").data_date == D11
        assert db.get(PriceDaily, ("0050.TW", D11)).value == 12_595_528_482
        assert db.get(PriceDaily, ("3680.TWO", D11)).value == 254_223_170


def test_altered_trading_runs_from_first_seen_until_it_leaves(engine, market):
    with Session(engine) as db:
        a = archiver(db)
        a.twse_altered_trading()
        rows = {e.symbol: e for e in db.scalars(select(MarketEvent).where(MarketEvent.type == "altered_trading"))}
        assert len(rows) == 10 and rows["2314.TW"].detail == "分盤集合競價"
        assert rows["1213.TW"].date == NOW.date() and rows["1213.TW"].data["backlog"]  # the first run: start unknown
        a.twse_altered_trading()  # the same list again: nothing new
        assert db.scalar(select(MarketEvent.id).where(MarketEvent.type == "altered_trading").order_by(
            MarketEvent.id.desc())) == max(e.id for e in rows.values())
        # a day later 1213 is no longer listed: its row ends that day
        later = datetime(2026, 11, 13, 10, 0, tzinfo=TAIPEI)
        fetcher = FakeFetcher()
        short = [r for r in load("twse_twt85u_live_20261117.json") if r["Code"] != "1213"]
        fetcher.get_json = lambda url, params=None, headers=None: short  # type: ignore[method-assign]
        Archiver(db, fetcher, "commercial", now_fn=lambda: later).twse_altered_trading()
        db.expire_all()
        ended = db.scalar(select(MarketEvent).where(MarketEvent.symbol == "1213.TW"))
        assert ended.end_date == date(2026, 11, 13)
        # an empty answer lifts nothing
        fetcher.get_json = lambda url, params=None, headers=None: []  # type: ignore[method-assign]
        Archiver(db, fetcher, "commercial", now_fn=lambda: later.replace(day=16)).twse_altered_trading()
        db.expire_all()
        assert db.scalar(select(MarketEvent).where(MarketEvent.symbol == "2314.TW")).end_date is None


def test_an_evening_read_that_still_holds_yesterday_is_not_stamped_today(engine, market):
    """MI_MARGN and MI_QFIIS_sort_20 have no date field. Read in the evening of 11/12 (stamped 11/12), a file whose
    rows equal what is stored for 11/11 is the morning batch's: it is skipped instead of being filed under 11/12."""
    evening = datetime(2026, 11, 12, 21, 40, tzinfo=TAIPEI)
    with Session(engine) as db:
        archiver(db).twse_margin()  # the morning read: stamped 11/11
        assert db.scalar(select(MarginDaily.date).limit(1)) == D11
        a = archiver(db, evening)
        assert a.margin_date() == date(2026, 11, 12)
        assert a.twse_margin() == 0
        assert db.scalar(select(MarginDaily).where(MarginDaily.date == date(2026, 11, 12))) is None
        # a changed file is today's
        changed = [dict(r) for r in load("twse_mi_margn_live_20261112.json")]
        for r in changed:
            for k in r:
                if "融資今日餘額" in k:
                    r[k] = "1"
        fetcher = FakeFetcher()
        fetcher.get_json = lambda url, params=None, headers=None: changed  # type: ignore[method-assign]
        assert Archiver(db, fetcher, "commercial", now_fn=lambda: evening).twse_margin() > 0
        # foreign top 20: stored for 11/11 in the morning, the same list read in the evening is skipped
        morning = datetime(2026, 11, 12, 8, 30, tzinfo=TAIPEI)
        assert archiver(db, morning).twse_foreign_top20() > 0
        assert archiver(db, evening).twse_foreign_top20() == 0
        assert db.scalar(select(ForeignHoldingTop20).where(ForeignHoldingTop20.date == date(2026, 11, 12))) is None
