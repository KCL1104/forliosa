"""Actual earnings / monthly-revenue / 法說會 dates from archived official announcements (live fixtures of
2026-11-12) and from the day a company's month or quarter first appears in the official datasets. Legal deadlines
only as a fallback: a coming one labelled ``estimated: true``; a past one shown as published (actual day unknown) only
when we hold the period's data, else left out (2026-11-17)."""

from __future__ import annotations

import copy
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.archive import Archiver, filed_now
from forliosa.marketdata import opendata as od
from forliosa.marketdata.base import BaseProvider, InstrumentInfo, RevenueRow
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import FinancialReport, MarketEvent
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
                                ("4523", "永彰", "TPEX"), ("8924", "大田", "TPEX"), ("2314", "台揚", "TWSE"),
                                ("6016", "康和證", "TPEX"))]


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
    # 2026Q3: the board-approval announcement. 2026Q2's deadline (8/14) has passed and nothing we hold shows the
    # report (no statements of it archived, no shioaji-data here): left out rather than shown as an estimate
    assert [(e["period"], e["date"], e["estimated"]) for e in q3] == [("2026Q3", "2026-11-11", False)]
    # 10 月營收 was already in t187ap05 on the first archive run: published, actual day unknown -> on the deadline,
    # with the numbers, never 「預估」
    rev = [e for e in by_type(quanta, "revenue_release") if e["period"] == "2026-10"]
    assert [(e["date"], e["estimated"], e["title"]) for e in rev] == [("2026-11-10", False, "10 月營收公布")]
    assert rev[0]["detail"] == "10 月營收 353,250,414 千元，年增 104.0%（實際公布日不明，日期是法定期限）"
    assert not any(e["estimated"] for e in quanta if e["date"] < "2026-11-12")
    assert all("預估" not in e["title"] for e in quanta if e["date"] < "2026-11-12")

    conf = client.get(f"{API}/instruments/2901/events").json()
    talks = by_type(conf, "investor_conference")
    assert [(e["date"], e["title"], e["estimated"]) for e in talks] == [
        ("2026-11-23", "公告本公司召開法人說明會", False)]
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


AFTER_Q3 = date(2026, 11, 17)  # the 2026Q3 deadline (11/14) and the 10 月營收 deadline (11/10) have passed
UNKNOWN = "（實際公布日不明，日期是法定期限）"


class Official(BaseProvider):
    """Stands in for shioaji-data's official files: 欣欣 (2901)'s quarterly statements and monthly revenue."""

    name = "shioaji-data"

    def statements(self, symbol):
        if symbol != "2901.TW":
            return None
        return {"periods": ["2026Q2", "2026Q3"], "income_ytd": {"基本每股盈餘（元）": [0.35, -0.12]}}

    def monthly_revenue(self, symbol):
        if symbol != "2901.TW":
            return None
        return [RevenueRow("2026-08", 10234, Decimal("-0.270145"), None, None, None),
                RevenueRow("2026-09", 11017, Decimal("0.0315"), None, None, None)]


@pytest.fixture()
def with_statements(engine, market, monkeypatch):
    """The archive with the statement datasets too (group ``financials``); "today" after the 2026Q3 deadline."""
    with Session(engine) as db:
        Archiver(db, FakeFetcher(), "commercial", now_fn=lambda: NOW).run(["twse", "tpex", "financials"])
    monkeypatch.setattr(stock_svc, "today_taipei", lambda: AFTER_Q3)
    set_market_data(MarketData([Listed(), DemoProvider()], policy="commercial"))
    yield engine
    set_market_data(market)


def test_past_quarter_with_archived_statements_is_published_not_estimated(client, with_statements):
    with Session(with_statements) as db:  # the first run of the statement datasets: filed before archiving started
        assert db.scalar(select(MarketEvent).where(MarketEvent.type == "earnings")) is None
    delta = by_type(client.get(f"{API}/instruments/2308/events").json(), "earnings")
    assert [(e["period"], e["date"], e["estimated"], e["title"]) for e in delta] == [
        ("2026Q3", "2026-11-14", False, "2026Q3 財報公布")]
    assert delta[0]["detail"] == f"前三季每股盈餘 26.64 元{UNKNOWN}"
    assert delta[0]["sources"][0] == "Forliosa 規則計算"
    assert delta[0]["sources"][1].startswith("臺灣證券交易所〈上市公司綜合損益表〉（")
    gw = by_type(client.get(f"{API}/instruments/6488/events").json(), "earnings")  # TPEx
    assert [(e["date"], e["estimated"], e["detail"]) for e in gw] == [
        ("2026-11-14", False, f"前三季每股盈餘 15 元{UNKNOWN}")]
    assert gw[0]["sources"][1].startswith("證券櫃檯買賣中心〈上櫃公司綜合損益表〉（")


def test_actual_report_release_is_unchanged_by_archived_statements(client, with_statements):
    q3 = by_type(client.get(f"{API}/instruments/2382/events").json(), "earnings")
    assert [(e["period"], e["date"], e["estimated"], e["title"]) for e in q3] == [
        ("2026Q3", "2026-11-11", False, "2026Q3 財報公布")]
    assert q3[0]["detail"] == "公告本公司董事會通過115年第三季財務報告"
    assert q3[0]["sources"][0].startswith("臺灣證券交易所〈上市公司每日重大訊息〉（")


def test_past_deadline_without_evidence_is_left_out_and_coming_ones_stay_estimated(client, with_statements):
    xinxin = client.get(f"{API}/instruments/2901/events").json()
    assert not by_type(xinxin, "earnings")  # 2026Q3's deadline passed and nothing we hold shows the report
    rev = {e["period"]: e for e in by_type(xinxin, "revenue_release")}
    # 8 月、9 月營收 (deadlines 9/10, 10/10): no revenue of those months held -> not listed at all
    assert sorted(rev) == ["2026-10", "2026-11", "2026-12"]
    assert (rev["2026-10"]["date"], rev["2026-10"]["estimated"], rev["2026-10"]["title"]) == (
        "2026-11-10", False, "10 月營收公布")
    assert rev["2026-10"]["detail"] == f"10 月營收 11,445 千元，年增 3.9%{UNKNOWN}"
    for period, deadline in (("2026-11", "2026-12-10"), ("2026-12", "2027-01-10")):  # coming: estimates
        e = rev[period]
        assert (e["date"], e["estimated"], e["title"]) == (deadline, True, f"{int(period[5:])} 月營收公布期限（預估）")
        assert e["detail"] == "還不知道實際公布日；法定期限是每月 10 日前公布上個月營收"
    assert all(not e["estimated"] and "預估" not in e["title"] for e in xinxin if e["date"] < "2026-11-17")


def test_coming_report_deadline_stays_estimated(client, archived):
    """Before the deadline (today 2026-11-12, deadline 11/14) the report is still an estimate, unchanged."""
    q3 = by_type(client.get(f"{API}/instruments/2901/events").json(), "earnings")
    assert [(e["date"], e["estimated"], e["title"], e["detail"]) for e in q3] == [
        ("2026-11-14", True, "2026Q3 財報公布期限（預估）",
         "還不知道實際公布日，先照季報的法定期限顯示（以公司公告為準）")]


def test_past_deadlines_published_per_official_files(client, with_statements, market):
    """shioaji-data's official files (statements, monthly revenue) are evidence too, for months the archive missed."""
    set_market_data(MarketData([Listed(), Official(), DemoProvider()], policy="commercial"))
    xinxin = client.get(f"{API}/instruments/2901/events").json()
    q3 = by_type(xinxin, "earnings")
    assert [(e["date"], e["estimated"], e["title"], e["detail"]) for e in q3] == [
        ("2026-11-14", False, "2026Q3 財報公布", f"前三季每股虧損 0.12 元{UNKNOWN}")]
    assert q3[0]["sources"][1].startswith("永豐金證券 shioaji-data")
    rev = {e["period"]: e for e in by_type(xinxin, "revenue_release") if e["date"] < "2026-11-17"}
    assert {p: (e["date"], e["estimated"], e["title"], e["detail"]) for p, e in rev.items()} == {
        "2026-08": ("2026-09-10", False, "8 月營收公布", f"8 月營收 10,234 千元，年減 27.0%{UNKNOWN}"),
        "2026-09": ("2026-10-10", False, "9 月營收公布", f"9 月營收 11,017 千元，年增 3.2%{UNKNOWN}"),
        # the archived (backlog) row comes first: the same month in the official files is not read
        "2026-10": ("2026-11-10", False, "10 月營收公布", f"10 月營收 11,445 千元，年增 3.9%{UNKNOWN}"),
    }


def test_report_first_seen_after_archiving_started(client, engine, market, monkeypatch):
    """A (company, quarter) that appears in the statement datasets after their first run keeps its first-seen date
    (出表日期) as the release date, like monthly revenue."""

    class Q4(FakeFetcher):
        def get_json(self, url, params=None, headers=None):
            data = super().get_json(url, params, headers)
            if any(k in url for k in ("t187ap06", "t187ap07", "187ap17")):
                data = copy.deepcopy(data)
                for r in data:
                    for k, v in (("季別", "4"), ("Season", "4"), ("出表日期", "1160330"), ("Date", "1160330")):
                        if r.get(k):
                            r[k] = v
            return data

    later = datetime(2027, 3, 30, 21, 40, tzinfo=TAIPEI)
    with Session(engine) as db:
        Archiver(db, FakeFetcher(), "commercial", now_fn=lambda: NOW).run(["twse", "tpex", "financials"])
        Archiver(db, Q4(), "commercial", now_fn=lambda: later).run(["financials"])
        Archiver(db, Q4(), "commercial", now_fn=lambda: later + timedelta(days=2)).run(["financials"])  # no change
        rows = list(db.scalars(select(MarketEvent).where(MarketEvent.type == "earnings")))
        assert sorted((r.symbol, r.data["period"], r.date, r.source) for r in rows) == [
            ("2308.TW", "2026Q4", date(2027, 3, 30), "twse-openapi"),
            ("2382.TW", "2026Q4", date(2027, 3, 30), "twse-openapi"),
            ("6016.TWO", "2026Q4", date(2027, 3, 30), "tpex-openapi"),  # securities firms (t187ap06_O_bd)
            ("6021.TWO", "2026Q4", date(2027, 3, 30), "tpex-openapi"),
            ("6488.TWO", "2026Q4", date(2027, 3, 30), "tpex-openapi")]
    monkeypatch.setattr(stock_svc, "today_taipei", lambda: date(2027, 4, 2))
    set_market_data(MarketData([Listed(), DemoProvider()], policy="commercial"))
    earnings = by_type(client.get(f"{API}/instruments/2308/events").json(), "earnings")
    assert [(e["period"], e["date"], e["estimated"], e["title"], e["detail"]) for e in earnings] == [
        ("2027Q1", "2027-05-15", True, "2027Q1 財報公布期限（預估）",  # the coming deadline: still an estimate
         "還不知道實際公布日，先照季報的法定期限顯示（以公司公告為準）"),
        ("2026Q4", "2027-03-30", False, "2026Q4 財報公布", "全年每股盈餘 26.64 元")]  # first seen, not the 3/31
    sources = earnings[1]["sources"]
    assert len(sources) == 1 and sources[0].startswith("臺灣證券交易所〈上市公司綜合損益表〉")
    set_market_data(market)


STATEMENTS = ("t187ap06", "t187ap07", "187ap17")


def _code(r):
    return r.get("公司代號") or r.get("SecuritiesCompanyCode")


def _as_company(row, code, name, published, period=None):
    """A copy of a fixture row (statements or monthly revenue) for another company, with its 出表日期 (and 資料年月)."""
    r = copy.deepcopy(row)
    r["公司代號"], r["公司名稱"], r["出表日期"] = code, name, published
    if period is not None:
        r["資料年月"] = period
    return r


class Edited(FakeFetcher):
    """The fixtures with rows added (``add``: URL suffix -> rows) or companies dropped (``drop``: URL suffix ->
    codes), the statement datasets moved to another quarter (``season``, ``published``: 季別 and 出表日期), and
    datasets failing (``fail``: URL suffixes)."""

    def __init__(self, add=None, drop=None, season=None, published=None, fail=()):
        super().__init__()
        self.add, self.drop, self.season, self.published, self.fail = add or {}, drop or {}, season, published, fail

    def get_json(self, url, params=None, headers=None):
        if any(url.endswith(f) for f in self.fail):
            raise RuntimeError("HTTP 307")
        data = copy.deepcopy(super().get_json(url, params, headers))
        data += [copy.deepcopy(r) for suffix, rows in self.add.items() if url.endswith(suffix) for r in rows]
        data = [r for r in data if not any(url.endswith(s) and _code(r) in c for s, c in self.drop.items())]
        if self.season and any(k in url for k in STATEMENTS):
            for r in data:
                for k, v in (("季別", self.season), ("Season", self.season), ("出表日期", self.published),
                             ("Date", self.published)):
                    if r.get(k):
                        r[k] = v
        return data


def test_new_listing_brings_no_first_seen_report_date(client, engine, market, monkeypatch):
    """2026-11-17 review: a company that joins the statement datasets after their first run (a new listing that filed
    while on 興櫃) brings a quarter filed before we saw it. Its listing day is not the release date: the events show
    the quarter published on the deadline, actual day unknown; its next quarter gets a first-seen date."""
    xinxin = _as_company(load("twse_t187ap06_l_ci_live_20261112.json")[0], "2901", "欣欣", "1151204")
    listed = datetime(2026, 12, 4, 21, 40, tzinfo=TAIPEI)
    with Session(engine) as db:
        Archiver(db, FakeFetcher(), "commercial", now_fn=lambda: NOW).run(["twse", "tpex", "financials"])
        Archiver(db, Edited(add={"/opendata/t187ap06_L_ci": [xinxin]}), "commercial",
                 now_fn=lambda: listed).run(["financials"])
        assert db.scalar(select(FinancialReport.period).where(FinancialReport.symbol == "2901.TW")) == "2026Q3"
        assert db.scalar(select(MarketEvent).where(MarketEvent.type == "earnings")) is None
    monkeypatch.setattr(stock_svc, "today_taipei", lambda: date(2026, 12, 7))
    set_market_data(MarketData([Listed(), DemoProvider()], policy="commercial"))
    q3 = by_type(client.get(f"{API}/instruments/2901/events").json(), "earnings")
    assert [(e["period"], e["date"], e["estimated"], e["title"], e["detail"]) for e in q3] == [
        ("2026Q3", "2026-11-14", False, "2026Q3 財報公布", f"前三季每股盈餘 26.64 元{UNKNOWN}")]
    set_market_data(market)

    xinxin_q4 = {**xinxin, "季別": "4", "出表日期": "1160330"}
    with Session(engine) as db:
        Archiver(db, Edited(add={"/opendata/t187ap06_L_ci": [xinxin_q4]}, season="4", published="1160330"),
                 "commercial", now_fn=lambda: datetime(2027, 3, 30, 21, 40, tzinfo=TAIPEI)).run(["financials"])
        rows = db.scalars(select(MarketEvent).where(MarketEvent.type == "earnings", MarketEvent.symbol == "2901.TW"))
        assert [(r.data["period"], r.date) for r in rows] == [("2026Q4", date(2027, 3, 30))]


def test_company_moving_from_tpex_to_twse_brings_no_first_seen_report_date(engine):
    """2026-11-17 review: 6488's 2026Q3 is held under 6488.TWO; when it moves to TWSE the quarter shows up in
    t187ap06_L under a new symbol (and event key). Not a release: the quarters are compared by company code across
    both markets. The next quarter, first seen in the TWSE files, is one."""
    moved = _as_company(load("twse_t187ap06_l_ci_live_20261112.json")[0], "6488", "環球晶", "1151204")
    gone = {"/mopsfin_t187ap06_O_ci": {"6488"}, "/mopsfin_187ap17_O": {"6488"}}
    with Session(engine) as db:
        Archiver(db, FakeFetcher(), "commercial", now_fn=lambda: NOW).run(["twse", "tpex", "financials"])
        Archiver(db, Edited(add={"/opendata/t187ap06_L_ci": [moved]}, drop=gone), "commercial",
                 now_fn=lambda: datetime(2026, 12, 4, 21, 40, tzinfo=TAIPEI)).run(["financials"])
        assert db.scalar(select(FinancialReport.period).where(FinancialReport.symbol == "6488.TW")) == "2026Q3"
        assert db.scalar(select(MarketEvent).where(MarketEvent.type == "earnings")) is None
        Archiver(db, Edited(add={"/opendata/t187ap06_L_ci": [moved]}, drop=gone, season="4", published="1160330"),
                 "commercial", now_fn=lambda: datetime(2027, 3, 30, 21, 40, tzinfo=TAIPEI)).run(["financials"])
        rows = db.scalars(select(MarketEvent).where(MarketEvent.type == "earnings",
                                                    MarketEvent.symbol.in_(["6488.TW", "6488.TWO"])))
        assert [(r.symbol, r.data["period"], r.date) for r in rows] == [("6488.TW", "2026Q4", date(2027, 3, 30))]


def test_dataset_failing_on_the_first_run_brings_no_first_seen_report_dates(client, engine, market, monkeypatch):
    """2026-11-17 review: the securities firms' dataset (t187ap06_O_bd, the only one holding 6016 and 6021) fails on
    the first run and works the next day. Their 2026Q3, filed before archiving started, is not dated that day."""
    with Session(engine) as db:
        Archiver(db, Edited(fail=("/mopsfin_t187ap06_O_bd",)), "commercial", now_fn=lambda: NOW).run(
            ["twse", "tpex", "financials"])
        assert db.scalar(select(FinancialReport).where(FinancialReport.symbol == "6016.TWO")) is None
        Archiver(db, FakeFetcher(), "commercial",
                 now_fn=lambda: datetime(2026, 11, 13, 21, 40, tzinfo=TAIPEI)).run(["financials"])
        assert db.scalar(select(FinancialReport.period).where(FinancialReport.symbol == "6016.TWO")) == "2026Q3"
        assert db.scalar(select(MarketEvent).where(MarketEvent.type == "earnings")) is None
    monkeypatch.setattr(stock_svc, "today_taipei", lambda: AFTER_Q3)
    set_market_data(MarketData([Listed(), DemoProvider()], policy="commercial"))
    q3 = by_type(client.get(f"{API}/instruments/6016/events").json(), "earnings")
    assert [(e["period"], e["date"], e["estimated"], e["title"]) for e in q3] == [
        ("2026Q3", "2026-11-14", False, "2026Q3 財報公布")]
    assert q3[0]["detail"].endswith(UNKNOWN)
    set_market_data(market)


def test_revenue_of_a_company_new_to_the_archive_is_backlog(archived):
    """2026-11-17 review: a company we hold no month of (禾榮科 listing on 11/20) and one whose October is held under
    the other market (6488 moving from TPEx to TWSE) bring a month filed before we saw them: stored as backlog (shown
    on the deadline, actual day unknown), not dated the day they joined t187ap05_L. Their next month is dated."""
    base = load("twse_t187ap05_l_live_20261112.json")[0]
    oct_ = [_as_company(base, "7799", "禾榮科", "1151120", "11510"),
            _as_company(base, "6488", "環球晶", "1151120", "11510")]
    nov = [{**r, "資料年月": "11511", "出表日期": "1151202"} for r in oct_]
    with Session(archived) as db:
        Archiver(db, Edited(add={"/opendata/t187ap05_L": oct_}), "commercial",
                 now_fn=lambda: datetime(2026, 11, 20, 8, 10, tzinfo=TAIPEI)).twse_revenue()
        Archiver(db, Edited(add={"/opendata/t187ap05_L": nov}), "commercial",
                 now_fn=lambda: datetime(2026, 12, 3, 8, 10, tzinfo=TAIPEI)).twse_revenue()
        rows = db.scalars(select(MarketEvent).where(MarketEvent.type == "revenue_release",
                                                    MarketEvent.symbol.in_(["7799.TW", "6488.TW", "6488.TWO"])))
        assert sorted((r.symbol, r.data["period"], r.date, r.data["backlog"]) for r in rows) == [
            ("6488.TW", "2026-10", date(2026, 11, 20), True),
            ("6488.TW", "2026-11", date(2026, 12, 2), False),
            ("6488.TWO", "2026-10", date(2026, 11, 11), True),
            ("7799.TW", "2026-10", date(2026, 11, 20), True),
            ("7799.TW", "2026-11", date(2026, 12, 2), False)]


def test_old_revenue_text_is_rebuilt_from_the_numbers(client, archived, monkeypatch):
    """2026-11-17 review: rows archived before the change say 「年增 -27.0%」 for a fall; the events rebuild the text
    from the stored numbers so that it reads like the newer rows (「年減 27.0%」), for a backlog row and a dated one."""
    with Session(archived) as db:
        row = db.scalar(select(MarketEvent).where(MarketEvent.symbol == "2901.TW",
                                                  MarketEvent.type == "revenue_release"))
        row.detail, row.data = "10 月營收 11,445 千元，年增 -27.0%", {**row.data, "yoy_pct": "-0.270145"}
        db.add(MarketEvent(key="n" * 40, symbol="2901.TW", date=date(2026, 12, 2), type="revenue_release",
                           title="11 月營收公布", detail="11 月營收 11,017 千元，年增 -5.1%", url=None,
                           data={"period": "2026-11", "revenue": 11017, "yoy_pct": "-0.0512", "mom_pct": None,
                                 "backlog": False}, source="twse-openapi"))
        db.add(MarketEvent(key="o" * 40, symbol="2901.TW", date=date(2026, 10, 9), type="revenue_release",
                           title="9 月營收公布", detail="9 月營收", url=None,  # no numbers: the stored text
                           data={"period": "2026-09", "revenue": None, "yoy_pct": None, "backlog": False},
                           source="twse-openapi"))
        db.commit()
    monkeypatch.setattr(stock_svc, "today_taipei", lambda: date(2026, 12, 5))
    rev = {e["period"]: e["detail"] for e in by_type(client.get(f"{API}/instruments/2901/events").json(),
                                                     "revenue_release")}
    assert rev["2026-10"] == f"10 月營收 11,445 千元，年減 27.0%{UNKNOWN}"
    assert rev["2026-11"] == "11 月營收 11,017 千元，年減 5.1%"
    assert rev["2026-09"] == "9 月營收"


def test_release_texts():
    assert od.revenue_text(10, 1977, Decimal("0.422302")) == "10 月營收 1,977 千元，年增 42.2%"
    assert od.revenue_text(9, 1105, Decimal("-0.270145")) == "9 月營收 1,105 千元，年減 27.0%"
    assert od.revenue_text(9, None, None) == "9 月營收"
    assert od.eps_text("2026Q3", "-1.78") == "前三季每股虧損 1.78 元"
    assert od.eps_text("2026Q2", 3.5) == "上半年每股盈餘 3.5 元"
    assert od.eps_text("2026Q1", "15.00") == "第一季每股盈餘 15 元"
    assert od.eps_text("2025Q4", "26.64") == "全年每股盈餘 26.64 元"
    assert od.eps_text("2026Q3", None) is None and od.eps_text("2026Q3", "--") is None


def test_filed_now():
    """Only a period newer than every period held of the company (either market) is dated by its first appearance."""
    held = {"2330": {"2026Q2", "2026Q3"}, "6488": {"2026-09", "2026-10"}}
    assert filed_now(held, "2330", "2026Q4") and filed_now(held, "6488", "2026-11")
    assert not filed_now(held, "2330", "2026Q3")  # held already (another statement, or under the other market)
    assert not filed_now(held, "2330", "2026Q1")  # older than what we hold
    assert not filed_now(held, "2901", "2026Q3")  # nothing held: a new listing or a dataset that failed at first


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


def test_news_are_official_announcements(client, archived, market):
    news = client.get(f"{API}/instruments/2382/news").json()
    # 廣達's three 重大訊息 of 2026-11-11, newest first, labelled 公告 with the dataset attribution
    assert [n["published_at"] for n in news] == ["2026-11-11T15:15:02+08:00", "2026-11-11T14:43:45+08:00",
                                                 "2026-11-11T14:42:33+08:00"]
    assert news[-1]["title"] == "公告本公司董事會通過115年第三季財務報告"
    assert all(n["source"] == "公告" and n["category"] == "material_info" for n in news)
    assert all(n["url"].startswith("https://mops.twse.com.tw/") for n in news)
    assert news[0]["sources"][0].startswith("臺灣證券交易所〈上市公司每日重大訊息〉（")
    # 證交所新聞 naming the company code (台揚 2314): linked to the official page, never fetched
    taiyang = client.get(f"{API}/instruments/2314/news").json()
    assert {n["category"] for n in taiyang} == {"exchange_news"}
    assert all(n["url"].startswith("https://www.twse.com.tw/zh/about/news/") for n in taiyang)
    assert any("終止上市" in n["title"] for n in taiyang)
    assert taiyang[0]["sources"][0].startswith("臺灣證券交易所〈證交所新聞〉（")
    set_market_data(MarketData([Listed(), DemoProvider()], policy="commercial"))
    assert client.get(f"{API}/instruments/2382/news").json() == news  # official data: same under commercial
    assert client.get(f"{API}/instruments/AAPL/news").json() == []


def test_meta_attributions_is_public(app):
    from fastapi.testclient import TestClient

    r = TestClient(app).get(f"{API}/meta/attributions")
    assert r.status_code == 200
    body = r.json()
    assert body["policy"] in ("personal", "commercial") and "https://data.gov.tw/license" in body["notice"][1]
    d = next(x for x in body["datasets"] if x["key"] == "twse-openapi/valuation")
    assert d["agency"] == "臺灣證券交易所" and d["dataset"] == "上市個股日本益比、殖利率及股價淨值比"
    assert d["attribution"].endswith("依政府資料開放授權條款第 1 版") and d["url"].startswith("https://openapi.twse")
    assert any("基本市況報導" in x for x in body["not_used"])


def test_gregorian_years_in_titles_are_not_read_as_roc_1937():
    """2026-11-14 review: 「2026年10月」 used to match the "026" inside "2026" as ROC year 26 (= 1937)."""
    from datetime import date

    from forliosa.services.announcements import report_period, revenue_period

    assert report_period("公告本公司2026年第三季合併財務報告", "", date(2026, 11, 10)) == "2026Q3"
    assert revenue_period("公告本公司2026年10月合併營收") == "2026-10"
    assert report_period("公告本公司115年第三季合併財務報告", "", date(2026, 11, 10)) == "2026Q3"
    assert revenue_period("本公司一百一十五年十月份營收") == "2026-10"
