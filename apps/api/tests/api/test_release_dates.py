"""Actual earnings / monthly-revenue / 法說會 dates from archived official announcements (live fixtures of
2026-11-12); legal deadlines only as a fallback, labelled ``estimated: true``."""

from __future__ import annotations

import copy
from datetime import date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.archive import Archiver
from forliosa.marketdata import opendata as od
from forliosa.marketdata.base import BaseProvider, InstrumentInfo
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import MarketEvent
from forliosa.services import announcements as ann
from forliosa.services import stock as stock_svc
from forliosa.timeutil import TAIPEI
from tests.archive.fakes import NOW, FakeFetcher, load

API = "/api/v1"


class Listed(BaseProvider):
    """Instrument master entries for the fixture companies that the built-in catalog does not list."""

    name = "listed"

    def instruments(self):
        return [InstrumentInfo(f"{c}.{'TWO' if m == 'TPEX' else 'TW'}", c, n, m, "stock", "TWD")
                for c, n, m in (("2901", "欣欣", "TWSE"), ("2408", "南亞科", "TWSE"), ("5530", "龍巖", "TPEX"),
                                ("4523", "永彰", "TPEX"), ("8924", "大田", "TPEX"))]


@pytest.fixture()
def archived(engine, market, monkeypatch):
    with Session(engine) as db:
        Archiver(db, FakeFetcher(), "commercial", now_fn=lambda: NOW).run(["twse", "tpex"])
    monkeypatch.setattr(stock_svc, "today_taipei", lambda: date(2026, 11, 12))
    md = MarketData([Listed(), DemoProvider()], policy="personal")
    set_market_data(md)
    yield engine
    set_market_data(market)


def by_type(events, type_):
    return [e for e in events if e["type"] == type_]


def test_parsers_and_classifier_on_live_rows():
    revenue = {r["code"]: r for r in od.parse_monthly_revenue(load("twse_t187ap05_l_live_20261112.json"), "TWSE")}
    assert revenue["2330"]["period"] == "2026-10" and revenue["2330"]["revenue"] == 586890319
    assert revenue["2330"]["published"] == date(2026, 11, 11)
    assert float(revenue["2330"]["yoy_pct"]) == pytest.approx(0.597097576)
    holidays = od.parse_holidays(load("twse_holiday_schedule_live_20261112.json"))
    assert len(holidays) == 27 and sum(not h["is_trading_day"] for h in holidays) == 24
    assert holidays[1] == {"date": date(2026, 1, 2), "name": "國曆新年開始交易日", "description": "國曆新年開始交易。",
                           "is_trading_day": True}

    rows = {(r["code"], r["data"]["time"]): r for r in
            od.parse_material_info(load("twse_t187ap04_l_live_20261112.json"), "TWSE")
            + od.parse_material_info(load("tpex_t187ap04_o_live_20261112.json"), "TPEX")}
    got = {code: ann.classify(r["title"], r["detail"], r["data"], r["date"]) for (code, _), r in rows.items()
           if code != "2382"}
    quanta = next(r for (c, _), r in rows.items() if c == "2382" and "財務報告" in r["title"])
    assert ann.classify(quanta["title"], quanta["detail"], quanta["data"], quanta["date"]) == ann.Release(
        "earnings", date(2026, 11, 11), "2026Q3")  # period from 「115/01/01~115/09/30」
    assert got["2901"] == ann.Release("investor_conference", date(2026, 11, 23), None)  # 事實發生日
    assert got["2408"] == ann.Release("investor_conference", date(2026, 11, 12), None)  # Daiwa conference (第12款)
    assert got["8924"] == ann.Release("investor_conference", date(2026, 11, 20), None)
    assert got["5530"] == ann.Release("revenue_release", date(2026, 11, 10), "2026-10")
    assert got["4523"] is None  # 更正… is never a release date
    assert got["5475"] is None and got["3489"] is None  # 現金增資, 更名


@pytest.mark.parametrize(("title", "period"), [
    ("公告本公司董事會通過115年第三季合併財務報告", "2026Q3"),
    ("公告董事會通過一百一十五年第三季合併財務報告", "2026Q3"),
    ("本公司董事會通過115年第3季合併財報", "2026Q3"),
    ("公告本公司董事會通過115年度第三季合併財務報告案", "2026Q3"),
    ("公告本公司董事會通過115年上半年度合併財務報告", "2026Q2"),
    ("公告本公司114年度合併財務報告業經董事會通過", "2025Q4"),
    ("本公司董事會通過第三季合併財務報告", "2026Q3"),
])
def test_report_period_from_titles(title, period):
    assert ann.report_period(title, "", date(2026, 11, 11)) == period


def test_events_use_actual_dates_and_label_deadlines_estimated(client, archived):
    quanta = client.get(f"{API}/instruments/2382/events").json()
    q3 = by_type(quanta, "earnings")
    actual = [e for e in q3 if e["period"] == "2026Q3"]
    assert [(e["date"], e["estimated"]) for e in actual] == [("2026-11-11", False)]
    assert all(e["estimated"] for e in q3 if e["period"] != "2026Q3")  # older quarters: deadlines only
    # 10 月營收 was already in t187ap05 on the first archive run: date unknown -> deadline, estimated
    rev = [e for e in by_type(quanta, "revenue_release") if e["period"] == "2026-10"]
    assert [(e["date"], e["estimated"]) for e in rev] == [("2026-11-10", True)]
    assert "353,250,414 千元" in rev[0]["detail"] and "開始存檔前已公布" in rev[0]["detail"]

    conf = client.get(f"{API}/instruments/2901/events").json()
    talks = by_type(conf, "investor_conference")
    assert [(e["date"], e["title"], e["estimated"]) for e in talks] == [("2026-11-23", "公告本公司召開法人說明會", False)]
    assert not by_type(conf, "material_info")
    daiwa = by_type(client.get(f"{API}/instruments/2408/events").json(), "investor_conference")
    assert [e["date"] for e in daiwa] == ["2026-11-12"]

    longyan = client.get(f"{API}/instruments/5530/events").json()
    oct_rev = [e for e in by_type(longyan, "revenue_release") if e["period"] == "2026-10"]
    assert [(e["date"], e["title"], e["estimated"]) for e in oct_rev] == [("2026-11-10", "10 月營收公布", False)]
    correction = client.get(f"{API}/instruments/4523/events").json()
    assert any(e["type"] == "material_info" and e["title"].startswith("更正") for e in correction)


def test_revenue_first_seen_after_archiving_started(client, archived, monkeypatch):
    """Next month: rows that appear after the first run keep their first-seen (出表日期) date."""

    class December(FakeFetcher):
        def get_json(self, url, params=None, headers=None):
            data = super().get_json(url, params, headers)
            if url.endswith("/opendata/t187ap05_L"):
                data = copy.deepcopy(data)
                for r in data:
                    r["資料年月"], r["出表日期"] = "11511", "1151202"
            return data

    later = datetime(2026, 12, 3, 8, 10, tzinfo=TAIPEI)
    with Session(archived) as db:
        Archiver(db, December(), "commercial", now_fn=lambda: later).twse_revenue()
        Archiver(db, December(), "commercial", now_fn=lambda: later.replace(day=4)).twse_revenue()  # no change
        rows = list(db.scalars(select(MarketEvent).where(MarketEvent.symbol == "2330.TW",
                                                         MarketEvent.type == "revenue_release")))
        assert sorted((r.data["period"], r.date, r.data["backlog"]) for r in rows) == [
            ("2026-10", date(2026, 11, 11), True), ("2026-11", date(2026, 12, 2), False)]
    monkeypatch.setattr(stock_svc, "today_taipei", lambda: date(2026, 12, 5))
    ev = client.get(f"{API}/instruments/2330/events").json()
    nov = [e for e in by_type(ev, "revenue_release") if e["period"] == "2026-11"]
    assert [(e["date"], e["estimated"], e["title"]) for e in nov] == [("2026-12-02", False, "11 月營收公布")]
    assert "586,890,319 千元" in nov[0]["detail"]


def test_events_under_both_policies(client, archived, market):
    personal = client.get(f"{API}/instruments/2382/events").json()
    set_market_data(MarketData([Listed(), DemoProvider()], policy="commercial"))
    commercial = client.get(f"{API}/instruments/2382/events").json()
    # official announcements are commercially usable: the same actual dates under both policies
    pick = [(e["type"], e["date"], e["estimated"]) for e in personal if e["type"] in ("earnings", "revenue_release")]
    assert pick == [(e["type"], e["date"], e["estimated"]) for e in commercial
                    if e["type"] in ("earnings", "revenue_release")]
    # but no demo dividends under commercial
    assert any(e["type"] == "ex_dividend" and "示範" in "".join(e["sources"]) for e in personal)
    assert not any("示範" in "".join(e["sources"]) for e in commercial)
