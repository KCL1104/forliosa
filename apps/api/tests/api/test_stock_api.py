"""Stock page, watchlist and upcoming endpoints (temp SQLite, demo prices, archive from live fixtures)."""

from __future__ import annotations

import copy
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

from forliosa.archive import Archiver
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.base import BaseProvider, Candle, QuoteData
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import InstitutionalDaily, MarketEvent, PriceDaily
from forliosa.services import stock as stock_svc
from forliosa.timeutil import last_tw_trading_day, today_taipei
from tests.archive.fakes import NOW, FakeFetcher, load

API = "/api/v1"
TODAY = date(2026, 11, 12)


def make_account(client):
    r = client.post(f"{API}/accounts", json={"name": "永豐", "currency": "TWD", "fee_discount": 0.28})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def add_txn(client, **body):
    r = client.post(f"{API}/transactions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def day(days_ago: int) -> str:
    return last_tw_trading_day(today_taipei() - timedelta(days=days_ago)).isoformat()


@pytest.fixture()
def archived(engine, market):
    with Session(engine) as db:
        Archiver(db, FakeFetcher(), "personal", now_fn=lambda: NOW).run()
    return engine


@pytest.fixture()
def frozen_today(monkeypatch):
    """Archive fixtures are dated 2026-11-06…12; pin the stock service's "today" to 2026-11-12."""
    monkeypatch.setattr(stock_svc, "today_taipei", lambda: TODAY)
    return TODAY


@pytest.fixture()
def use_market(market):
    def use(md: MarketData) -> MarketData:
        set_market_data(md)
        return md

    yield use
    set_market_data(market)


# -- overview / position -------------------------------------------------------------------------------
def test_overview_fields(client, market, archived):
    with Session(archived) as db:
        db.add(MarketEvent(key="t-disp", symbol="2330.TW", date=today_taipei() - timedelta(days=1),
                           end_date=today_taipei() + timedelta(days=3), type="disposition",
                           title="處置股票（第一次處置）", detail="", data={}, source="twse-openapi"))
        db.commit()
    r = client.get(f"{API}/instruments/2330/overview")
    assert r.status_code == 200, r.text
    o = r.json()
    q = client.get(f"{API}/instruments/2330/quote").json()
    assert o["reference_price"] == q["reference_price"] and o["limit_up"] == q["limit_up"]
    assert o["low_52w"] <= o["high_52w"] and o["avg_volume_3m"] > 0 and o["eps_ttm"] > 0
    assert o["status"]["disposition"] is True and "處置期間" in o["status"]["note"]
    assert o["is_demo"] is True and any("示範" in s for s in o["sources"])
    etf = client.get(f"{API}/instruments/0050/overview").json()
    assert etf["eps_ttm"] is None and etf["dividend_yield"] is not None
    assert client.get(f"{API}/instruments/ZZZZ/overview").status_code == 404


def test_position_from_ledger(client, other_client):
    acc = make_account(client)
    add_txn(client, account_id=acc, symbol="2330.TW", type="buy", trade_date=day(200), quantity=2000, price=1000)
    add_txn(client, account_id=acc, symbol="2330.TW", type="sell", trade_date=day(100), quantity=1000, price=1500)
    add_txn(client, account_id=acc, symbol="2330.TW", type="cash_dividend", trade_date=day(50), price=5)
    p = client.get(f"{API}/instruments/2330.TW/position").json()
    assert p["quantity"] == 1000 and p["currency"] == "TWD"
    # sold 1000 @ 1500: proceeds − fee − tax − cost of 1000 shares (incl. buy fee) > 0
    assert p["realized_pnl"] > 400_000
    assert p["dividends_received"] == 5000.0  # 1000 shares × 5, below the NT$20,000 NHI threshold
    assert [m["type"] for m in p["markers"]] == ["buy", "sell", "dividend"]
    assert p["markers"][0]["quantity"] == 2000 and p["markers"][0]["price"] == 1000
    assert p["unrealized_pnl"] == pytest.approx(p["market_value"] - p["cost_basis"], abs=0.01)
    assert "帳本紀錄" in p["sources"]
    # not held -> null; other users never see it
    assert client.get(f"{API}/instruments/2317/position").json() is None
    assert other_client.get(f"{API}/instruments/2330/position").json() is None


# -- chips / financials / events / news --------------------------------------------------------------------
def test_chips_from_archive(client, archived, frozen_today):
    r = client.get(f"{API}/instruments/6488/chips?range=1M")
    assert r.status_code == 200, r.text
    c = r.json()
    inst = c["institutional"][-1]
    assert inst == {"t": "2026-11-11", "foreign": 1265.318, "trust": -405.182, "dealer": 442.393, "total": 1302.529}
    assert c["margin"][-1] == {"t": "2026-11-11", "margin_balance": 9653, "short_balance": 195}
    assert c["foreign_holding_pct"][-1] == {"t": "2026-11-11", "pct": 0.2949}
    assert c["major_holders"]["as_of"] == "2026-11-06"
    levels = c["major_holders"]["buckets"]
    assert [b["level"] for b in levels] == list(range(1, 16)) and levels[-1]["label"] == "1,000 張以上"
    # attribution: agency〈dataset〉(year), licence
    assert any(s.startswith("證券櫃檯買賣中心〈上櫃股票三大法人買賣明細資訊〉（")
               and s.endswith("依政府資料開放授權條款第 1 版") for s in c["sources"])
    assert any(s.startswith("證券櫃檯買賣中心〈上櫃僑外資及陸資持股比例排行表〉") for s in c["sources"])
    assert any(s.startswith("臺灣集中保管結算所〈集保戶股權分散表〉") for s in c["sources"])
    twse = client.get(f"{API}/instruments/2330/chips?range=1M").json()
    # TWSE publishes no per-stock institutional OpenAPI dataset; its website may not be scraped (any mode)
    assert twse["institutional"] == [] and twse["foreign_holding_pct"] == [] and twse["notes"]
    assert twse["margin"][-1]["margin_balance"] == 32523  # MI_MARGN is OpenAPI
    assert not any(s.endswith("（非商用）") for s in twse["sources"])
    assert client.get(f"{API}/instruments/2330/chips?range=2W").status_code == 422
    assert client.get(f"{API}/instruments/AAPL/chips").json()["major_holders"] is None


class Statements(BaseProvider):
    """Real shioaji-data statements for 6488, optionally cut before 2026Q3."""

    name = "shioaji-data"

    def __init__(self, drop_last: bool = False):
        st = copy.deepcopy(load("shioaji_financials_6488_live_20261112.json")["statements"])
        if drop_last:
            st["periods"] = st["periods"][:-1]
            for sec in ("income_quarter", "income_ytd", "balance", "cash_flow_quarter"):
                st[sec] = {k: v[:-1] for k, v in st[sec].items()}
        self.st = st

    def statements(self, symbol):
        return self.st if symbol == "6488.TWO" else None


def test_financials_quarterly_and_annual(client, use_market):
    use_market(MarketData([Statements(), DemoProvider()], policy="personal"))
    f = client.get(f"{API}/instruments/6488/financials?period=quarterly").json()
    assert f["periods"][-1] == "2026Q3" and len(f["periods"]) == 7
    assert f["income"]["revenue"][-1] == 14870753 and f["income"]["eps"][-1] == 3.13
    assert all(len(v) == len(f["periods"]) for g in ("income", "balance", "cashflow", "margins") for v in f[g].values())
    ops, inv = f["cashflow"]["operating"][-1], f["cashflow"]["investing"][-1]
    assert f["cashflow"]["free_cash_flow"][-1] == pytest.approx(ops + inv)
    assert 0 < f["margins"]["gross"][-1] < 1
    a = client.get(f"{API}/instruments/6488/financials?period=annual").json()
    assert a["periods"] == ["2025"]  # 2026 has only three quarters
    assert a["income"]["revenue"] == [15594522 + 16007909 + 14493434 + 14502073]
    assert client.get(f"{API}/instruments/0050/financials").json()["periods"] == []
    assert client.get(f"{API}/instruments/6488/financials?period=monthly").status_code == 422


def test_financials_latest_quarter_from_archive_is_derived_from_ytd(client, archived, use_market):
    use_market(MarketData([Statements(drop_last=True), DemoProvider()], policy="personal"))
    f = client.get(f"{API}/instruments/6488/financials").json()
    assert f["periods"][-1] == "2026Q3"
    # OpenAPI 2026Q3 YTD 44,069,861 − shioaji 2026Q2 YTD 29,199,108 = 14,870,753
    assert f["income"]["revenue"][-1] == 14870753
    assert f["income"]["eps"][-1] == pytest.approx(15.0 - (3.97 + 7.9))
    assert f["cashflow"]["operating"][-1] is None  # the OpenAPI has no cash-flow statement
    assert any("櫃檯買賣中心" in s for s in f["sources"])


def test_events(client, archived, frozen_today):
    acc = make_account(client)
    add_txn(client, account_id=acc, symbol="6488.TWO", type="buy", trade_date=day(30), quantity=1000, price=600)
    ev = client.get(f"{API}/instruments/6488/events").json()
    types = {e["type"] for e in ev}
    assert {"ex_dividend", "shareholder_meeting", "earnings", "revenue_release"} <= types
    meeting = next(e for e in ev if e["type"] == "shareholder_meeting" and e["date"] == "2026-12-21")
    assert meeting["title"] == "股東臨時會"
    dates = [e["date"] for e in ev]
    assert dates == sorted(dates, reverse=True)
    mine = client.get(f"{API}/instruments/6488/events?mine=true").json()
    assert mine and all(e["mine"] for e in mine)
    quanta = client.get(f"{API}/instruments/2382/events").json()
    # the board-approval announcement is the actual 2026Q3 report date (no estimated deadline for it)
    q3 = [e for e in quanta if e["type"] == "earnings" and e["period"] == "2026Q3"]
    assert [(e["date"], e["estimated"], e["title"]) for e in q3] == [("2026-11-11", False, "2026Q3 財報公布")]
    assert "財務報告" in q3[0]["detail"] and not any(e["type"] == "material_info" and "財務報告" in e["title"]
                                                    for e in quanta)


def test_news_degrades_without_finmind(client):
    assert client.get(f"{API}/instruments/2330/news").json() == []  # no FinMind provider configured


def test_news_from_finmind_is_labelled_non_commercial(client, use_market):
    class FakeFinMind(BaseProvider):
        name = "finmind"

        def news(self, symbol):
            return [{"published_at": "2026-11-11 08:30:00", "title": "台積電法說會", "source": "鉅亨網",
                     "url": "https://news.cnyes.com/news/id/1"}]

    use_market(MarketData([FakeFinMind(), DemoProvider()], policy="personal"))
    n = client.get(f"{API}/instruments/2330/news").json()
    # media headlines name the outlet in ``outlet`` and how they were found in ``source``
    assert n == [{"published_at": "2026-11-11T08:30:00+08:00", "title": "台積電法說會", "source": "FinMind",
                  "outlet": "鉅亨網", "url": "https://news.cnyes.com/news/id/1", "category": "media",
                  "date_only": False, "sources": ["FinMind（非商用）"]}]
    use_market(MarketData([FakeFinMind(), DemoProvider()], policy="commercial"))
    assert client.get(f"{API}/instruments/2330/news").json() == []


def test_unlicensed_archive_rows_are_never_served(client, archived, engine, frozen_today, use_market):
    """Rows the old worker took from the TWSE website (twse-web) or MIS stay hidden under both policies."""
    with Session(engine) as db:
        db.add(InstitutionalDaily(symbol="2330.TW", date=date(2026, 11, 11), foreign_net=1, trust_net=2,
                                  dealer_net=3, total_net=6, source="twse-web"))
        db.add(PriceDaily(symbol="2330.TW", date=date(2026, 11, 10), close=D(2285), source="twse-mis+shioaji-data"))
        db.commit()
    for policy in ("personal", "commercial"):
        use_market(MarketData([ArchiveProvider(policy, session_fn=lambda: Session(engine)), DemoProvider()],
                              policy=policy))
        assert client.get(f"{API}/instruments/2330/chips?range=1M").json()["institutional"] == []
        candles = client.get(f"{API}/instruments/2330/history?range=1M").json()["candles"]
        assert not any(c["t"] == "2026-11-10" and c["c"] == 2285.0 for c in candles), policy
    tpex = client.get(f"{API}/instruments/6488/chips?range=1M").json()
    assert tpex["institutional"]  # TPEx OpenAPI publishes them (commercial)


def test_listed_stocks_never_show_institutional_flows(client, archived, engine, frozen_today, use_market):
    """Owner decision 2026-11-12: no per-stock 三大法人 / 外資持股 for TWSE-listed stocks in any mode — not from
    FinMind (personal), not from rows already in the archive; margin and TDCC still show."""
    from forliosa.models import ForeignHoldingDaily

    with Session(engine) as db:
        db.add(InstitutionalDaily(symbol="2330.TW", date=date(2026, 11, 10), foreign_net=1000, trust_net=2000,
                                  dealer_net=3000, total_net=6000, source="finmind"))
        db.add(ForeignHoldingDaily(symbol="2330.TW", date=date(2026, 11, 10), pct=D("0.72"), source="finmind"))
        db.commit()

    calls: list[tuple[str, tuple[str, ...]]] = []

    class FakeFinMind(BaseProvider):
        name = "finmind"

        def chips(self, symbol, start, datasets=("institutional", "margin", "foreign")):
            calls.append((symbol, tuple(datasets)))
            row = {"date": date(2026, 11, 11)}
            return {"institutional": [{**row, "foreign_net": 1, "trust_net": 2, "dealer_net": 3, "total_net": 6}],
                    "margin": [{**row, "margin_balance": 1, "short_balance": 2}], "foreign": [{**row, "pct": D("0.7")}]}

    use_market(MarketData([FakeFinMind(), ArchiveProvider("personal", session_fn=lambda: Session(engine)),
                           DemoProvider()], policy="personal"))
    c = client.get(f"{API}/instruments/2330/chips?range=1M").json()
    assert c["institutional"] == [] and c["foreign_holding_pct"] == []
    assert c["notes"] == [stock_svc.LISTED_CHIPS_NOTE]
    # only margin is requested from FinMind for a listed stock (no 三大法人／外資持股 downloads)
    assert calls == [("2330.TW", ("margin",))] and c["margin"] and c["major_holders"] is not None
    assert not any("三大法人" in s or "持股比例" in s for s in c["sources"])
    # TPEx stocks keep the TPEx OpenAPI rows
    tpex = client.get(f"{API}/instruments/6488/chips?range=1M").json()
    assert tpex["institutional"] and tpex["foreign_holding_pct"] and stock_svc.LISTED_CHIPS_NOTE not in tpex["notes"]
    assert calls[1:] == [("6488.TWO", ("institutional", "margin", "foreign"))]


# -- intraday ---------------------------------------------------------------------------------------------
def test_intraday_has_no_points_without_a_licensed_source(client):
    client.post(f"{API}/watchlist", json={"symbol": "2330"})
    r = client.get(f"{API}/instruments/2330/intraday").json()
    assert r["points"] == [] and r["sources"] == [] and "沒有盤中走勢" in r["notes"][0]
    assert r["reference_price"] is not None
    us = client.get(f"{API}/instruments/AAPL/intraday").json()
    assert us["points"] == [] and us["notes"] == ["美股沒有盤中走勢資料"]
    spark = next(w for w in client.get(f"{API}/watchlist").json() if w["symbol"] == "2330.TW")
    assert spark["sparkline_interval"] == "1d"


# -- why ----------------------------------------------------------------------------------------------------
class WhyQuotes(BaseProvider):
    name = "fake"

    def __init__(self, q: QuoteData, volume: int = 1_000_000):
        self.q, self.volume = q, volume

    def quotes(self, symbols):
        return {self.q.symbol: self.q}

    def history(self, symbol, start, end):
        d, out = end - timedelta(days=40), []
        while d < self.q.trade_date:
            if d.weekday() < 5:
                out.append(Candle(d, D(100), D(101), D(99), D(100), self.volume))
            d += timedelta(days=1)
        return out


def why_for(engine, q: QuoteData, today: date = TODAY) -> list[dict]:
    md = MarketData([WhyQuotes(q), DemoProvider()], policy="personal")
    info = md.instrument(q.symbol)
    fresh = md.quote(q.symbol)
    with Session(engine) as db:
        return stock_svc.why_reasons(db, md, info, fresh, today)


def quote(price: str, prev: str = "100", volume: int = 1_000_000, **kw) -> QuoteData:
    return QuoteData("2330.TW", price=D(price), prev_close=D(prev), open=D(prev), high=D(price), low=D(prev),
                     volume=volume, trade_date=TODAY, source="fake", **kw)


def test_why_rules(engine, market):
    assert why_for(engine, quote("101")) == []  # +1 %: nothing unusual
    assert why_for(engine, quote("103.5")) == [{"kind": "price_move", "text": "今天上漲 3.5%"}]
    assert why_for(engine, quote("96.5"))[0]["text"] == "今天下跌 3.5%"
    assert [r["kind"] for r in why_for(engine, quote("110"))] == ["limit_up"]  # 100 × 1.1 = 110 (tick 0.5)
    assert [r["kind"] for r in why_for(engine, quote("90"))] == ["limit_down"]
    vol = why_for(engine, quote("100.5", volume=2_500_000))
    assert vol == [{"kind": "volume", "text": "成交量是 20 日均量的 2.5 倍"}]
    assert why_for(engine, quote("100.5", volume=1_900_000)) == []
    later = why_for(engine, quote("104"), today=TODAY + timedelta(days=3))
    assert later[0]["text"] == "11/12 上漲 4.0%"


def test_why_ex_dividend_day_is_not_a_drop(engine, market):
    class ExDay(WhyQuotes):
        def ex_rights_on(self, symbols, d):
            return {"2330.TW": (D(5), D(0))}

    md = MarketData([ExDay(quote("95.5", prev="100")), DemoProvider()], policy="personal")
    q = md.quote("2330.TW")
    assert q.reference_price == D(95)  # 100 − 5
    with Session(engine) as db:
        reasons = stock_svc.why_reasons(db, md, md.instrument("2330.TW"), q, TODAY)
    # −4.5 % vs the previous close, but +0.5 % vs the reference price: only the ex-dividend reason
    assert [r["kind"] for r in reasons] == ["ex_dividend"]
    assert "參考價 95" in reasons[0]["text"]


def test_why_status_and_announcements(engine, market):
    with Session(engine) as db:
        db.add_all([
            MarketEvent(key="a", symbol="2330.TW", date=TODAY, type="attention", title="列為注意股票", detail="",
                        data={}, source="twse-openapi"),
            MarketEvent(key="m", symbol="2330.TW", date=TODAY, type="material_info",
                        title="公告本公司董事會通過115年第三季合併財務報告", detail="", data={}, source="twse-openapi"),
        ])
        db.commit()
    kinds = [r["kind"] for r in why_for(engine, quote("100.5"))]
    assert kinds == ["attention", "earnings"]


def test_why_endpoint(client):
    r = client.get(f"{API}/instruments/2330/why")
    assert r.status_code == 200
    w = r.json()
    assert set(w) == {"symbol", "show", "headline", "reasons", "as_of", "sources",
                      "ai", "citations", "rule_headline"}  # AI (M4) fields are additive
    assert w["show"] == bool(w["reasons"]) and (w["headline"] is None) == (not w["reasons"])


# -- watchlist & upcoming ---------------------------------------------------------------------------------
def test_watchlist_crud_and_isolation(client, other_client):
    assert client.get(f"{API}/watchlist").json() == []
    r = client.post(f"{API}/watchlist", json={"symbol": "2382"})
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["symbol"] == "2382.TW" and item["quote"]["symbol"] == "2382.TW"
    assert item["sparkline"] and item["sparkline_interval"] == "1d"  # no intraday points: daily closes
    assert client.post(f"{API}/watchlist", json={"symbol": "2382.TW"}).status_code == 200  # idempotent
    client.post(f"{API}/watchlist", json={"symbol": "2308"})
    assert [w["symbol"] for w in client.get(f"{API}/watchlist").json()] == ["2382.TW", "2308.TW"]
    assert other_client.get(f"{API}/watchlist").json() == []
    assert other_client.delete(f"{API}/watchlist/2382").status_code == 404
    assert client.delete(f"{API}/watchlist/2382").status_code == 204
    assert client.delete(f"{API}/watchlist/2382").status_code == 404
    r = client.post(f"{API}/watchlist", json={"symbol": "ZZZZ"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_symbol"


def test_portfolio_upcoming(client, market):
    acc = make_account(client)
    for sym in ("00878.TW", "0056.TW", "00919.TW"):
        add_txn(client, account_id=acc, symbol=sym, type="buy", trade_date=day(30), quantity=1000, price=30)
    items = client.get(f"{API}/portfolio/upcoming?days=90").json()
    assert items, "quarterly ETFs always have an ex-date within 90 days"
    today = today_taipei()
    for it in items:
        assert today <= date.fromisoformat(it["date"]) <= today + timedelta(days=90)
        assert it["type"] in ("ex_dividend", "dividend_payment")
        ev = next(e for e in market.dividends(it["symbol"]).value
                  if it["date"] in (str(e.ex_dividend_date), str(e.payment_date)))
        assert it["amount_estimate"] == pytest.approx(float(1000 * ev.cash_dividend), abs=0.01)
    assert [i["date"] for i in items] == sorted(i["date"] for i in items)
    week = client.get(f"{API}/portfolio/upcoming").json()
    assert all(date.fromisoformat(i["date"]) <= today + timedelta(days=7) for i in week)
    assert client.get(f"{API}/portfolio/upcoming?days=0").status_code == 422


def test_quote_has_reference_and_sources(client):
    q = client.get(f"{API}/instruments/2330/quote").json()
    assert {"reference_price", "limit_up", "limit_down", "sources"} <= set(q)
    assert q["change"] == pytest.approx(q["price"] - q["reference_price"], abs=1e-4)
    assert client.get(f"{API}/instruments/2330/history?range=1M").json()["sources"] == ["示範資料（模擬）"]
