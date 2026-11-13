"""``GET /market/overview``: indices, sectors, rankings and material information from official archive rows only;
honest empties; the history backfill's rows are never ranked."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from forliosa.models import (
    AiMarketSummary,
    DatasetStatus,
    FxRate,
    IndexDaily,
    MarketEvent,
    PriceDaily,
    ReferencePrice,
)
from forliosa.services import market_overview as svc

API = "/api/v1"
D11, D12 = date(2026, 11, 11), date(2026, 11, 12)


@pytest.fixture(autouse=True)
def fresh_cache():
    svc.clear_cache()
    yield
    svc.clear_cache()


def price(db: Session, symbol: str, day: date, close: str, volume: int = 1000, source: str | None = None) -> None:
    source = source or ("tpex-openapi" if symbol.endswith(".TWO") else "twse-openapi")
    db.add(PriceDaily(symbol=symbol, date=day, close=D(close), volume=volume, source=source))


def index(db: Session, name: str, day: date, close: str, change: str | None, pct: str | None,
          market: str = "TWSE") -> None:
    db.add(IndexDaily(name=name, date=day, market=market, close=D(close), change=D(change) if change else None,
                      change_pct=D(pct) if pct else None,
                      source="twse-openapi" if market == "TWSE" else "tpex-openapi"))


def get(client) -> dict:
    r = client.get(f"{API}/market/overview")
    assert r.status_code == 200, r.text
    return r.json()


def seed(db: Session) -> None:
    index(db, "發行量加權股價指數", D11, "27000.00", "100.00", "0.0037")
    index(db, "發行量加權股價指數", D12, "27270.00", "270.00", "0.01")
    index(db, "櫃買指數", D11, "300.00", None, None, market="TPEX")
    index(db, "櫃買指數", D12, "297.00", "-3.00", None, market="TPEX")  # the percentage is computed
    index(db, "半導體類指數", D12, "900.00", "18.00", "0.0204")
    index(db, "水泥類指數", D12, "150.00", "-1.50", "0.0099")  # published unsigned: the sign comes from the change
    index(db, "半導體類報酬指數", D12, "1900.00", "38.00", "0.0204")  # a total-return twin is not a sector row
    index(db, "未含金融指數", D12, "23000.00", "200.00", "0.0088")
    index(db, "機電類指數", D12, "500.00", "5.00", "0.0101")  # an old composite of sectors listed on their own
    db.add_all([FxRate(pair="USDTWD", date=D11, rate=D("31.500"), source="cbc-opendata"),
                FxRate(pair="USDTWD", date=D12, rate=D("31.437"), source="cbc-opendata")])
    for sym, before, after, vol in (("2330.TW", "1000", "1050", 30_000_000), ("2317.TW", "200", "196", 50_000_000),
                                    ("6488.TWO", "600", "618", 9_000_000), ("1101.TW", "40", "40", 20_000_000)):
        price(db, sym, D11, before, vol)
        price(db, sym, D12, after, vol)
    # not common stocks: an ETF, a preferred share
    for sym in ("0050.TW", "2881A.TW"):
        price(db, sym, D11, "100", 99_000_000)
        price(db, sym, D12, "109", 99_000_000)
    # ex-dividend: the official reference price of the day is the base, not the previous close
    price(db, "2412.TW", D11, "130", 5_000_000)
    price(db, "2412.TW", D12, "126", 5_000_000)
    db.add(ReferencePrice(symbol="2412.TW", date=D12, reference_price=D("125"), limit_up=D("137.5"),
                          limit_down=D("112.5"), source="twse-openapi"))
    db.add_all([DatasetStatus(key="twse-openapi/price", data_date=D12, rows=5),
                DatasetStatus(key="tpex-openapi/price", data_date=D12, rows=1)])
    for i, (sym, title, at) in enumerate((("2330.TW", "董事會決議股利分派", "173005"),
                                          ("2317.TW", "公告本公司取得機器設備", "92005"),  # 09:20, no leading zero
                                          ("6488.TWO", "澄清媒體報導", "183000"))):
        db.add(MarketEvent(key=f"material-{i}", symbol=sym, date=D12, type="material_info", title=title,
                           detail="", data={"time": at}, source="tpex-openapi" if sym.endswith(".TWO")
                           else "twse-openapi"))
    db.add(MarketEvent(key="material-old", symbol="2330.TW", date=D11, type="material_info", title="昨天的",
                       detail="", data={"time": "170000"}, source="twse-openapi"))
    db.add(MarketEvent(key="notice-1", symbol="2317.TW", date=D12, type="attention", title="注意股票",
                       detail="", data={}, source="twse-openapi"))
    db.commit()


def test_needs_a_login(app):
    assert TestClient(app).get(f"{API}/market/overview").status_code == 401


def test_empty_archive_answers_with_empty_blocks(client):
    o = get(client)
    assert o["indices"] == [] and o["sectors"] is None and o["movers"] is None and o["announcements"] is None
    assert o["summary"] is None and o["as_of"] is None and o["is_demo"] is False
    assert o["notes"] == ["還沒有資料"] and o["sources"] == []


def test_indices_sectors_rankings_and_announcements(client, engine):
    with Session(engine) as db:
        seed(db)
    o = get(client)
    assert o["as_of"] == "2026-11-12" and o["notes"] == []

    by_key = {i["key"]: i for i in o["indices"]}
    assert list(by_key) == ["taiex", "tpex", "usdtwd"]  # no futures row: none archived
    taiex = by_key["taiex"]
    assert (taiex["name"], taiex["value"], taiex["change"], taiex["change_pct"], taiex["date"], taiex["unit"]) == (
        "加權指數", 27270.0, 270.0, 0.01, "2026-11-12", "點")
    assert taiex["sparkline"] == [{"t": "2026-11-11", "v": 27000.0}, {"t": "2026-11-12", "v": 27270.0}]
    assert (by_key["tpex"]["change"], by_key["tpex"]["change_pct"]) == (-3.0, -0.01)
    fx = by_key["usdtwd"]
    assert (fx["value"], fx["change"], fx["unit"]) == (31.437, -0.063, "元") and fx["change_pct"] == -0.002

    sectors = o["sectors"]
    assert sectors["date"] == "2026-11-12"
    assert [(s["name"], s["change_pct"]) for s in sectors["items"]] == [("半導體", 0.0204), ("水泥", -0.0099)]

    m = o["movers"]
    assert (m["date"], m["prev_date"], m["count"]) == ("2026-11-12", "2026-11-11", 5)
    assert [(x["code"], x["change_pct"]) for x in m["gainers"]] == [("2330", 0.05), ("6488", 0.03), ("2412", 0.008)]
    assert [(x["code"], x["change_pct"]) for x in m["losers"]] == [("2317", -0.02)]
    assert [x["code"] for x in m["volume"]] == ["2317", "2330", "1101", "6488", "2412"]  # ETFs are not ranked
    top = m["gainers"][0]
    assert (top["symbol"], top["name"], top["market"], top["close"], top["change"], top["volume"]) == (
        "2330.TW", "台積電", "TWSE", 1050.0, 50.0, 30_000_000)
    assert m["gainers"][1]["market"] == "TPEX"

    a = o["announcements"]
    assert (a["date"], a["total"]) == ("2026-11-12", 3)
    assert [(x["code"], x["time"], x["title"]) for x in a["items"]] == [
        ("6488", "18:30", "澄清媒體報導"), ("2330", "17:30", "董事會決議股利分派"),
        ("2317", "09:20", "公告本公司取得機器設備")]
    assert a["items"][1]["name"] == "台積電" and a["items"][1]["url"] is None

    assert any("發行量加權股價指數" in s or "每日收盤行情" in s or "臺灣證券交易所" in s for s in o["sources"])
    assert any("中央銀行" in s for s in o["sources"])
    assert any("重大訊息" in s for s in o["sources"])


def test_ranks_the_latest_day_both_exchanges_have_published(client, engine):
    """TWSE has posted 11/13, TPEx not yet: the ranking stays on 11/12 instead of ranking half a market."""
    with Session(engine) as db:
        seed(db)
        price(db, "2330.TW", date(2026, 11, 13), "1100", 40_000_000)
        db.get(DatasetStatus, "twse-openapi/price").data_date = date(2026, 11, 13)
        db.commit()
    m = get(client)["movers"]
    assert m["date"] == "2026-11-12" and m["gainers"][0]["close"] == 1050.0


def test_backfilled_history_is_never_ranked(client, engine):
    """Rows of the history backfill (split-adjusted, not official) are neither a day to rank nor a base price."""
    with Session(engine) as db:
        price(db, "2330.TW", D12, "1050", 30_000_000)
        price(db, "2330.TW", D11, "500", 30_000_000, source="yahoo-history")
        price(db, "2317.TW", D11, "200", 1000, source="yahoo-history")
        db.commit()
    o = get(client)
    assert o["movers"] is None  # one official day only: nothing to measure a change from


def test_moves_beyond_the_daily_limit_are_left_out(client, engine):
    with Session(engine) as db:
        seed(db)
        price(db, "3008.TW", D11, "2000", 1_000_000)
        price(db, "3008.TW", D12, "500", 1_000_000)  # e.g. a split: not a 75 % fall
        db.commit()
    assert "3008" not in [x["code"] for x in get(client)["movers"]["losers"]]


def test_summary_is_the_latest_finished_one(client, engine, monkeypatch):
    from forliosa.ai import market_summary

    monkeypatch.setattr(market_summary, "summary_day", lambda now=None: D12)
    with Session(engine) as db:
        seed(db)
        db.add(AiMarketSummary(trading_day=D12, status="ok", headline="加權指數收漲 1%，半導體領漲", model="m",
                               attempts=1, points=[
                                   {"text": "加權指數收在 27,270 點。", "sources": [
                                       {"url": "https://www.cna.com.tw/news/afe/202611120300.aspx",
                                        "title": "台股收盤上漲", "outlet": "中央社", "date": "2026-11-12"}]},
                                   {"text": "半導體類股領漲。", "sources": [
                                       {"url": "https://money.udn.com/money/story/5607/1", "title": "半導體領軍",
                                        "outlet": "經濟日報", "date": None}]}]))
        db.add(AiMarketSummary(trading_day=D11, status="empty", headline="", points=[], model="m", attempts=1))
        db.commit()
    s = get(client)["summary"]
    assert s["date"] == "2026-11-12" and s["headline"] == "加權指數收漲 1%，半導體領漲"
    assert [p["text"] for p in s["points"]] == ["加權指數收在 27,270 點。", "半導體類股領漲。"]
    assert s["points"][0]["sources"] == [{"url": "https://www.cna.com.tw/news/afe/202611120300.aspx",
                                          "title": "台股收盤上漲", "outlet": "中央社"}]


def test_readable_while_viewing_someone_elses_assets():
    """No user data: the view-as header is ignored instead of refused."""
    from forliosa.api.middleware import ViewAsMiddleware

    assert ViewAsMiddleware(None, API).classify("GET", f"{API}/market/overview") == "ignore"
