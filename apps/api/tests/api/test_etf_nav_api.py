"""ETF NAV and premium / discount in ``GET /instruments/{symbol}/overview`` and the AI ``get_stock_overview`` tool:
close ÷ NAV − 1 on the same date only, official archived closes only, history from the archive start."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

from forliosa.models import EtfNav, PriceDaily, User
from forliosa.services import etf_nav as svc

API = "/api/v1"
NAV_ATTRIBUTION = "金融監督管理委員會證券期貨局〈證券投資信託基金每日淨值〉（2026），依政府資料開放授權條款第 1 版"
TWSE_PRICE = "臺灣證券交易所〈上市個股日成交資訊〉（2026），依政府資料開放授權條款第 1 版"


def weekdays(end: date, n: int) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def add(db: Session, symbol: str, navs: dict[date, str], closes: dict[date, str], source: str = "twse-openapi"):
    for d, v in navs.items():
        db.add(EtfNav(symbol=symbol, date=d, nav=D(v), currency="TWD", fund_name="元大台灣卓越50基金",
                      source="sfb-opendata"))
    for d, v in closes.items():
        db.add(PriceDaily(symbol=symbol, date=d, close=D(v), source=source))
    db.commit()


def ov(client, symbol: str) -> dict:
    r = client.get(f"{API}/instruments/{symbol}/overview")
    assert r.status_code == 200, r.text
    return r.json()


def test_same_day_premium_with_a_full_history(client, engine):
    days = weekdays(date(2026, 11, 12), 25)
    with Session(engine) as db:
        add(db, "0050.TW", {d: "100.00" for d in days}, {d: "100.50" for d in days[:-1]} | {days[-1]: "101.47"})
    o = ov(client, "0050.TW")
    n = o["etf_nav"]
    assert (n["nav"], n["nav_date"], n["close"], n["close_date"]) == (100.0, "2026-11-12", 101.47, "2026-11-12")
    assert (n["premium_pct"], n["premium_date"]) == (0.0147, "2026-11-12")
    assert len(n["history"]) == 25 and n["history"][0] == {"t": days[0].isoformat(), "nav": 100.0, "close": 100.5,
                                                            "premium_pct": 0.005}
    assert n["history_start"] == days[0].isoformat() and n["notes"] == []  # ≥ 20 points: no 「資料從…開始」 note
    assert n["history_missing"] == []  # every trading day in the span has a point
    assert n["sources"] == [NAV_ATTRIBUTION, TWSE_PRICE] and NAV_ATTRIBUTION in o["sources"]
    assert (n["currency"], n["fund_name"]) == ("TWD", "元大台灣卓越50基金")


def test_dates_differ_compute_on_the_newest_matching_day(client, engine):
    """An overseas ETF's NAV is the previous business day's and the newest close is today's: the premium uses the
    close of the NAV's day; both latest dates are returned."""
    with Session(engine) as db:
        add(db, "0056.TW", {date(2026, 11, 10): "52.00", date(2026, 11, 11): "52.20"},
            {date(2026, 11, 10): "52.26", date(2026, 11, 11): "52.10", date(2026, 11, 12): "53.15"})
    n = ov(client, "0056.TW")["etf_nav"]
    assert (n["nav_date"], n["close_date"], n["close"]) == ("2026-11-11", "2026-11-12", 53.15)
    assert n["premium_date"] == "2026-11-11"
    assert n["premium_pct"] == pytest.approx(52.10 / 52.20 - 1, abs=1e-6) and n["premium_pct"] < 0  # 折價
    assert n["history"][-1] == {"t": "2026-11-11", "nav": 52.2, "close": 52.1, "premium_pct": n["premium_pct"]}
    assert n["notes"] == ["淨值資料從 2026/11/10 開始"]  # 2 points < 20


def test_no_same_day_pair_no_premium_and_never_a_demo_or_finmind_close(client, engine):
    with Session(engine) as db:
        # TWSE's close file still holds yesterday when the evening NAV arrives
        add(db, "006208.TW", {date(2026, 11, 12): "231.48"}, {date(2026, 11, 11): "236.60"})
        # a demo or FinMind close of the NAV's day must not be used
        add(db, "006208.TW", {}, {date(2026, 11, 12): "999"}, source="demo")
    n = ov(client, "006208.TW")["etf_nav"]
    assert (n["nav"], n["nav_date"], n["close"], n["close_date"]) == (231.48, "2026-11-12", 236.6, "2026-11-11")
    assert n["premium_pct"] is None and n["premium_date"] is None and n["history"] == [] and n["history_missing"] == []
    assert n["notes"] == [svc.NO_MATCH_NOTE, "淨值資料從 2026/11/12 開始"]
    # the 11/11 close is shown, so its dataset is attributed even though no date pairs up
    assert n["sources"] == [NAV_ATTRIBUTION, TWSE_PRICE]


def test_etf_without_nav_and_stocks_without_the_block(client, engine):
    n = ov(client, "00919.TW")["etf_nav"]  # nothing archived yet
    assert n["nav"] is None and n["notes"] == [svc.NO_ARCHIVE_NOTE] and n["sources"] == []
    with Session(engine) as db:
        add(db, "0050.TW", {date(2026, 11, 12): "101.04"}, {})
        add(db, "00919.TW", {}, {date(2026, 11, 12): "22.64"})  # an archived close, but no NAV for this ETF
    n = ov(client, "00919.TW")["etf_nav"]  # the dataset is archived, this ETF is not in it
    assert n["nav"] is None and n["notes"] == [svc.NOT_IN_DATASET_NOTE]
    # no NAV: every number is null (the close too, as the contract says) and nothing to attribute
    assert all(n[k] is None for k in ("nav_date", "currency", "fund_name", "close", "close_date", "premium_pct",
                                      "premium_date", "history_start"))
    assert (n["history"], n["history_missing"], n["sources"]) == ([], [], [])
    assert ov(client, "2330.TW")["etf_nav"] is None
    assert ov(client, "VOO")["etf_nav"] is None


def test_history_is_capped_and_oldest_first(engine):
    from forliosa.marketdata.base import InstrumentInfo

    days = weekdays(date(2026, 11, 12), 70)
    with Session(engine) as db:
        add(db, "0050.TW", {d: "100" for d in days}, {d: "99.8" for d in days})
        info = InstrumentInfo("0050.TW", "0050", "元大台灣50", "TWSE", "etf", "TWD", "ETF")
        n = svc.etf_nav(db, info)
    assert len(n["history"]) == svc.HISTORY_POINTS == 60
    assert n["history"][0]["t"] == days[10] and n["history"][-1]["t"] == days[-1]
    assert n["premium_pct"] == -0.002 and n["history_start"] == days[0]


def test_archive_gaps_are_listed_as_missing_trading_days(client, engine):
    """The worker was down 11/2–11/6 (11/4 has a NAV but no close): the points skip five trading days, and the gap is
    listed instead of hidden. 10/26 has no row either, but it is a market holiday, so it is not missing."""
    from forliosa.ai.tools import _etf_nav_for_ai

    gap = [date(2026, 11, d) for d in (2, 3, 4, 5, 6)]
    days = [d for d in weekdays(date(2026, 11, 12), 40) if d not in gap and d != date(2026, 10, 26)]
    with Session(engine) as db:
        add(db, "0050.TW", {d: "100" for d in days} | {date(2026, 11, 4): "100"}, {d: "100.1" for d in days})
    n = ov(client, "0050.TW")["etf_nav"]
    assert len(n["history"]) == len(days) and n["history"][0]["t"] == days[0].isoformat()
    assert n["history_missing"] == [d.isoformat() for d in gap]
    r = _etf_nav_for_ai(n)["history_range"]
    assert (r["points"], r["missing_trading_days"], r["from"], r["to"]) == (
        len(days), 5, days[0].isoformat(), "2026-11-12")


def test_ai_overview_tool_gets_a_trimmed_block_with_the_same_date_rule(client, engine):
    from forliosa.ai.tools import ToolContext, execute
    from forliosa.marketdata.service import get_market_data

    days = weekdays(date(2026, 11, 12), 30)
    with Session(engine) as db:
        add(db, "0050.TW", {d: "100" for d in days},
            {d: ("100.6" if i == 3 else "99.9" if i == 7 else "100.2") for i, d in enumerate(days)})
        me = db.query(User).filter_by(email="demo@forliosa.local").one()
        out = json.loads(execute(ToolContext(db=db, user=me, md=get_market_data()), "get_stock_overview",
                                 {"symbol": "0050"}).content)
    n = out["etf_nav"]
    assert "etf_nav" not in out["overview"]
    assert (n["nav"], n["premium_pct"], n["premium_date"]) == (100.0, 0.002, "2026-11-12")
    assert len(n["recent"]) == 10 and n["recent"][-1]["t"] == "2026-11-12"
    r = n["history_range"]
    assert (r["points"], r["max"], r["min"]) == (30, {"t": days[3].isoformat(), "premium_pct": 0.006},
                                                 {"t": days[7].isoformat(), "premium_pct": -0.001})
    assert (r["from"], r["to"]) == (days[0].isoformat(), "2026-11-12") and "days" not in r
    assert "same date" in n["note"] or "premium_date only" in n["note"]
    assert "tracking error" in n["note"]
    assert NAV_ATTRIBUTION in out["sources"]


def test_attributions_list_the_nav_dataset(client, engine):
    meta = client.get(f"{API}/meta/attributions").json()
    ds = {d["key"]: d for d in meta["datasets"]}["sfb-opendata/nav"]
    assert ds["attribution"] == NAV_ATTRIBUTION
    assert (ds["agency"], ds["license_status"], ds["license_basis"], ds["commercial"]) == (
        "金融監督管理委員會證券期貨局", "ogdl", "data.gov.tw 11109", True)
    assert ds["url"] == "https://www.sitca.org.tw/MemberK0000/F/03/nav.csv"
