"""End-to-end API tests against a temp SQLite DB and the offline demo provider."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from forliosa.timeutil import last_tw_trading_day, today_taipei, tw_trading_days

API = "/api/v1"


def make_account(client, **kw):
    body = {"name": "永豐－一般", "broker": "永豐金證券", "currency": "TWD", "fee_discount": 0.28, **kw}
    r = client.post(f"{API}/accounts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def trading_day(days_ago: int) -> date:
    return last_tw_trading_day(today_taipei() - timedelta(days=days_ago))


def add_txn(client, **body):
    r = client.post(f"{API}/transactions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# -- auth & users --------------------------------------------------------------------------------
def test_unauthenticated_requests_use_contract_error_format(app):
    from fastapi.testclient import TestClient

    r = TestClient(app).get(f"{API}/me")
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "unauthorized", "message": "請先登入"}}


def test_dev_login_sets_httponly_cookie_and_me(client):
    me = client.get(f"{API}/me").json()
    assert me["email"] == "demo@forliosa.local"
    assert me["display_name"] == "示範使用者"
    assert me["id"].startswith("usr_")
    assert me["preferences"] == {"color_convention": "tw", "theme": "system", "quantity_unit": "lot",
                                 "privacy_mode": False, "cost_method": "average", "benchmark": "0050.TW"}


def test_cookie_attributes(app):
    from fastapi.testclient import TestClient

    r = TestClient(app).post(f"{API}/auth/dev-login", json={"email": "x@y.z"})
    cookie = r.headers["set-cookie"]
    assert "forliosa_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie


def test_logout(client):
    assert client.post(f"{API}/auth/logout").status_code == 204
    assert client.get(f"{API}/me").status_code == 401


def test_patch_preferences(client):
    r = client.patch(f"{API}/me/preferences", json={"cost_method": "fifo", "benchmark": "006208"})
    assert r.status_code == 200
    prefs = r.json()["preferences"]
    assert prefs["cost_method"] == "fifo" and prefs["benchmark"] == "006208.TW"
    assert client.patch(f"{API}/me/preferences", json={"theme": "neon"}).status_code == 422
    r = client.patch(f"{API}/me/preferences", json={"benchmark": "ZZZZ"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_symbol"


# -- accounts ------------------------------------------------------------------------------------
def test_accounts_crud_and_defaults(client):
    tw = make_account(client)
    assert tw["id"].startswith("acc_")
    assert (tw["fee_rate"], tw["fee_discount"], tw["min_fee"], tw["min_fee_odd_lot"]) == (0.001425, 0.28, 20, 1)
    usd = make_account(client, name="國泰－複委託", broker="國泰證券", currency="USD", fee_discount=1)
    assert usd["fee_rate"] == 0 and usd["min_fee"] == 0
    r = client.patch(f"{API}/accounts/{tw['id']}", json={"name": "永豐－大戶", "min_fee": 1})
    assert r.json()["name"] == "永豐－大戶" and r.json()["min_fee"] == 1
    assert len(client.get(f"{API}/accounts").json()) == 2
    assert client.delete(f"{API}/accounts/{usd['id']}").status_code == 204
    assert [a["id"] for a in client.get(f"{API}/accounts").json()] == [tw["id"]]


def test_accounts_are_scoped_to_user(client, other_client):
    acc = make_account(client)
    assert other_client.get(f"{API}/accounts").json() == []
    r = other_client.patch(f"{API}/accounts/{acc['id']}", json={"name": "hack"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert other_client.delete(f"{API}/accounts/{acc['id']}").status_code == 404
    r = other_client.post(f"{API}/transactions", json={
        "account_id": acc["id"], "symbol": "2330.TW", "type": "buy", "trade_date": "2025-01-02",
        "quantity": 1000, "price": 1000})
    assert r.status_code == 404


# -- transactions --------------------------------------------------------------------------------
def test_buy_auto_fee_and_preview(client):
    acc = make_account(client)
    body = {"account_id": acc["id"], "symbol": "2330", "type": "buy", "trade_date": "2025-03-03",
            "quantity": 1000, "price": 1070}
    p = client.post(f"{API}/transactions/preview", json=body).json()
    # 1,070,000 × 0.1425% × 0.28 = 426.93 -> 426
    assert p == {"gross": 1070000.0, "fee": 426.0, "tax": 0.0, "health_insurance": 0.0, "net_cash": -1070426.0,
                 "rules": ["手續費 0.1425% × 2.8 折，元以下捨去", "證交稅：買進免稅"]}
    t = add_txn(client, **body)
    assert t["symbol"] == "2330.TW" and t["fee"] == 426 and t["amount"] == 1070000 and t["currency"] == "TWD"
    assert t["id"].startswith("txn_")


def test_sell_tax_etf_and_day_trade(client):
    acc = make_account(client)
    add_txn(client, account_id=acc["id"], symbol="00878.TW", type="buy", trade_date="2025-03-03", quantity=2000,
            price=22)
    s = add_txn(client, account_id=acc["id"], symbol="00878.TW", type="sell", trade_date="2025-04-01",
                quantity=2000, price="23.45")
    assert s["tax"] == 46  # 46,900 × 0.1% = 46.9 -> 46
    add_txn(client, account_id=acc["id"], symbol="2317.TW", type="buy", trade_date="2025-05-05", quantity=1000,
            price="240", is_day_trade=True)
    d = add_txn(client, account_id=acc["id"], symbol="2317.TW", type="sell", trade_date="2025-05-05",
                quantity=1000, price="242.5", is_day_trade=True)
    assert d["tax"] == 363  # 242,500 × 0.15% = 363.75 -> 363


def test_odd_lot_minimum_fee(client):
    acc = make_account(client)
    t = add_txn(client, account_id=acc["id"], symbol="2330.TW", type="buy", trade_date="2025-03-03", quantity=3,
                price="10")
    assert t["fee"] == 1  # 30 × 0.1425% × 0.28 = 0.01 -> 0 -> odd-lot minimum NT$1
    r = client.post(f"{API}/transactions", json={
        "account_id": acc["id"], "symbol": "2330.TW", "type": "buy", "trade_date": "2025-03-03",
        "quantity": "1.5", "price": 10})
    assert r.status_code == 422 and "整數" in r.json()["error"]["message"]


def test_cash_dividend_auto_amount_and_nhi(client):
    acc = make_account(client)
    add_txn(client, account_id=acc["id"], symbol="2317.TW", type="buy", trade_date="2025-03-03", quantity=5000,
            price="200")
    # price = per-share dividend; held 5,000 × 5.0 = 25,000 ; NHI 2.11% = 527.5 -> 528
    d = add_txn(client, account_id=acc["id"], symbol="2317.TW", type="cash_dividend", trade_date="2025-07-24",
                price="5.0")
    assert d["amount"] == 25000 and d["quantity"] == 5000 and d["health_insurance"] == 528
    small = client.post(f"{API}/transactions/preview", json={
        "account_id": acc["id"], "symbol": "2317.TW", "type": "cash_dividend", "trade_date": "2025-07-24",
        "amount": 19999}).json()
    assert small["health_insurance"] == 0 and small["net_cash"] == 19999


def test_stock_dividend_computes_shares(client):
    acc = make_account(client)
    add_txn(client, account_id=acc["id"], symbol="6488.TWO", type="buy", trade_date="2025-03-03", quantity=1234,
            price="400")
    sd = add_txn(client, account_id=acc["id"], symbol="6488.TWO", type="stock_dividend", trade_date="2025-06-23",
                 price="0.5")
    # 1,234 × 0.5 / 10 = 61.7 -> 61 shares + NT$7 cash in lieu
    assert sd["quantity"] == 61 and sd["amount"] == 7
    hold = client.get(f"{API}/portfolio/holdings").json()
    assert hold[0]["quantity"] == 1295


def test_oversell_rejected_with_ledger_error(client):
    acc = make_account(client)
    add_txn(client, account_id=acc["id"], symbol="2330.TW", type="buy", trade_date="2025-03-03", quantity=100,
            price=1000)
    r = client.post(f"{API}/transactions", json={
        "account_id": acc["id"], "symbol": "2330.TW", "type": "sell", "trade_date": "2025-03-04",
        "quantity": 200, "price": 1000})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ledger_inconsistent"


def test_delete_buy_that_a_sell_depends_on_is_rejected(client):
    acc = make_account(client)
    b = add_txn(client, account_id=acc["id"], symbol="2330.TW", type="buy", trade_date="2025-03-03", quantity=100,
                price=1000)
    add_txn(client, account_id=acc["id"], symbol="2330.TW", type="sell", trade_date="2025-03-04", quantity=100,
            price=1010)
    assert client.delete(f"{API}/transactions/{b['id']}").status_code == 422


def test_patch_recalculates_fee(client):
    acc = make_account(client)
    t = add_txn(client, account_id=acc["id"], symbol="2330.TW", type="buy", trade_date="2025-03-03",
                quantity=1000, price=1070)
    r = client.patch(f"{API}/transactions/{t['id']}", json={"price": 1000})
    assert r.status_code == 200, r.text
    # 1,000,000 × 0.1425% × 0.28 = 399
    assert r.json()["fee"] == 399 and r.json()["amount"] == 1000000
    r = client.patch(f"{API}/transactions/{t['id']}", json={"fee": 1, "note": "折讓"})
    assert r.json()["fee"] == 1 and r.json()["note"] == "折讓"


def test_list_transactions_pagination_and_filters(client, other_client):
    acc = make_account(client)
    days = tw_trading_days(date(2025, 3, 3), date(2025, 3, 31))[:7]
    for d in days:
        add_txn(client, account_id=acc["id"], symbol="2330.TW", type="buy", trade_date=d.isoformat(),
                quantity=10, price=1000)
    add_txn(client, account_id=acc["id"], type="deposit", trade_date="2025-03-01", amount=100000)
    page1 = client.get(f"{API}/transactions", params={"limit": 3}).json()
    assert len(page1["items"]) == 3 and page1["next_cursor"]
    assert [i["trade_date"] for i in page1["items"]] == [d.isoformat() for d in days[::-1][:3]]
    seen = [i["id"] for i in page1["items"]]
    cursor = page1["next_cursor"]
    while cursor:
        page = client.get(f"{API}/transactions", params={"limit": 3, "cursor": cursor}).json()
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
    assert len(seen) == 8 and len(set(seen)) == 8
    deposits = client.get(f"{API}/transactions", params={"type": "deposit"}).json()["items"]
    assert len(deposits) == 1 and deposits[0]["symbol"] is None
    ranged = client.get(f"{API}/transactions", params={"from": days[2].isoformat(), "to": days[4].isoformat()})
    assert len(ranged.json()["items"]) == 3
    assert other_client.get(f"{API}/transactions").json() == {"items": [], "next_cursor": None}
    first = page1["items"][0]["id"]
    assert other_client.get(f"{API}/transactions/{first}").status_code == 404
    assert other_client.delete(f"{API}/transactions/{first}").status_code == 404


def test_unknown_symbol_and_validation_errors(client):
    acc = make_account(client)
    r = client.post(f"{API}/transactions", json={"account_id": acc["id"], "symbol": "9999XX", "type": "buy",
                                                  "trade_date": "2025-03-03", "quantity": 1, "price": 1})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_symbol"
    r = client.post(f"{API}/transactions", json={"account_id": acc["id"], "type": "teleport",
                                                  "trade_date": "2025-03-03"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


# -- holdings-only accounts -----------------------------------------------------------------------
def test_holdings_snapshot_mode(client):
    txn_acc = make_account(client)
    r = client.put(f"{API}/accounts/{txn_acc['id']}/holdings",
                   json={"as_of": "2026-01-05",
                         "holdings": [{"symbol": "2330.TW", "quantity": 1500, "avg_cost": 612.5}]})
    assert r.status_code == 409
    acc = make_account(client, name="只記持股", tracking_mode="holdings")
    as_of = trading_day(30).isoformat()
    r = client.put(f"{API}/accounts/{acc['id']}/holdings",
                   json={"as_of": as_of, "holdings": [{"symbol": "2330", "quantity": 1500, "avg_cost": 612.5},
                                                      {"symbol": "0050.TW", "quantity": 2000, "avg_cost": 40}]})
    assert r.status_code == 200, r.text
    assert {h["symbol"] for h in r.json()["holdings"]} == {"2330.TW", "0050.TW"}
    hold = {h["symbol"]: h for h in client.get(f"{API}/portfolio/holdings").json()}
    assert hold["2330.TW"]["quantity"] == 1500
    assert hold["2330.TW"]["avg_cost"] == 612.5
    assert hold["2330.TW"]["cost_basis"] == 918750  # 1,500 × 612.5
    perf = client.get(f"{API}/portfolio/performance", params={"range": "ALL"}).json()
    assert perf["start_date"] == as_of
    # tracking starts on as_of: the first day's return is 0 (inflow at market value)
    assert perf["series"][0]["twr_index"] == pytest.approx(1.0)


# -- portfolio -----------------------------------------------------------------------------------
@pytest.fixture()
def seeded(client):
    tw = make_account(client)
    us = make_account(client, name="國泰－複委託", broker="國泰證券", currency="USD", fee_discount=1)
    d1, d2 = trading_day(200), trading_day(100)
    px = {s: client.get(f"{API}/instruments/{s}/history", params={"range": "1Y"}).json()["candles"]
          for s in ("2330.TW", "0050.TW", "AAPL")}
    close = {s: {c["t"]: c["c"] for c in cs} for s, cs in px.items()}
    add_txn(client, account_id=tw["id"], symbol="2330.TW", type="buy", trade_date=d1.isoformat(), quantity=1000,
            price=close["2330.TW"][d1.isoformat()])
    add_txn(client, account_id=tw["id"], symbol="0050.TW", type="buy", trade_date=d1.isoformat(), quantity=3000,
            price=close["0050.TW"][d1.isoformat()])
    add_txn(client, account_id=tw["id"], symbol="2330.TW", type="sell", trade_date=d2.isoformat(), quantity=200,
            price=close["2330.TW"][d2.isoformat()])
    us_day = max(t for t in close["AAPL"] if t <= d1.isoformat())
    add_txn(client, account_id=us["id"], symbol="AAPL", type="buy", trade_date=us_day, quantity=10,
            price=close["AAPL"][us_day])
    return {"tw": tw, "us": us}


def test_portfolio_holdings_and_summary_are_consistent(client, seeded):
    holdings = client.get(f"{API}/portfolio/holdings").json()
    by = {h["symbol"]: h for h in holdings}
    assert set(by) == {"2330.TW", "0050.TW", "AAPL"}
    assert by["2330.TW"]["quantity"] == 800
    for h in holdings:
        assert h["is_demo"] is True
        if h["currency"] == "TWD":
            assert h["market_value"] == pytest.approx(h["quantity"] * h["price"], abs=0.01)
        assert h["unrealized_pnl"] == pytest.approx(h["market_value"] - h["cost_basis"], abs=0.02)
    assert sum(h["weight"] for h in holdings) == pytest.approx(1.0, abs=1e-5)
    s = client.get(f"{API}/portfolio/summary").json()
    assert s["market_value"] == pytest.approx(sum(h["market_value"] for h in holdings), abs=0.05)
    assert s["total_pnl"] == pytest.approx(s["unrealized_pnl"] + s["realized_pnl"] + s["dividend_income"], abs=0.05)
    assert s["is_demo"] is True
    assert {a["key"] for a in s["allocation"]["by_currency"]} == {"TWD", "USD"}
    assert {a["key"] for a in s["allocation"]["by_market"]} == {"TWSE", "US"}
    assert {a["label"] for a in s["allocation"]["by_type"]} == {"股票", "ETF"}
    one = client.get(f"{API}/portfolio/summary", params={"account_id": seeded["us"]["id"]}).json()
    assert [a["key"] for a in one["allocation"]["by_currency"]] == ["USD"]


def test_portfolio_performance_shape(client, seeded):
    p = client.get(f"{API}/portfolio/performance", params={"range": "1Y"}).json()
    assert p["range"] == "1Y" and p["series"]
    assert p["benchmark"]["symbol"] == "0050.TW" and p["benchmark"]["name"] == "元大台灣50"
    assert p["twr"] == pytest.approx(p["series"][-1]["twr_index"] - 1, abs=1e-6)
    assert p["max_drawdown"] <= 0 and p["volatility"] > 0
    assert p["xirr"] is not None
    assert p["realized_by_year"]
    last = p["series"][-1]
    s = client.get(f"{API}/portfolio/summary").json()
    assert last["market_value"] == pytest.approx(s["market_value"], rel=1e-3)
    for r in ("1M", "3M", "6M", "YTD", "ALL"):
        assert client.get(f"{API}/portfolio/performance", params={"range": r}).status_code == 200
    assert client.get(f"{API}/portfolio/performance", params={"range": "2W"}).status_code == 422


def test_empty_portfolio(client):
    s = client.get(f"{API}/portfolio/summary").json()
    assert s["market_value"] == 0 and s["upcoming_dividends"] == []
    assert client.get(f"{API}/portfolio/holdings").json() == []
    p = client.get(f"{API}/portfolio/performance").json()
    assert p["series"] == [] and p["twr"] is None


# -- market --------------------------------------------------------------------------------------
def test_instrument_search_detail_quote(client):
    res = client.get(f"{API}/instruments/search", params={"q": "台積"}).json()
    assert res[0]["symbol"] == "2330.TW" and res[0]["name"] == "台積電"
    assert client.get(f"{API}/instruments/search", params={"q": "00878"}).json()[0]["type"] == "etf"
    assert client.get(f"{API}/instruments/search", params={"q": "蘋果"}).json()[0]["symbol"] == "AAPL"
    d = client.get(f"{API}/instruments/6488").json()
    assert d["symbol"] == "6488.TWO" and d["market"] == "TPEX"
    q = client.get(f"{API}/instruments/2330.TW/quote").json()
    assert q["is_demo"] is True and q["change"] == pytest.approx(q["price"] - q["prev_close"], abs=1e-4)
    batch = client.get(f"{API}/quotes", params={"symbols": "2330.TW,0050.TW,AAPL"}).json()
    assert [b["symbol"] for b in batch] == ["2330.TW", "0050.TW", "AAPL"]
    r = client.get(f"{API}/instruments/NOPE")
    assert r.status_code == 404 and r.json() == {"error": {"code": "not_found", "message": "找不到商品"}}


def test_history_ranges(client):
    for r, n_min in (("5D", 5), ("1M", 15), ("6M", 100), ("YTD", 1), ("1Y", 200), ("5Y", 1000), ("MAX", 1500)):
        h = client.get(f"{API}/instruments/2330.TW/history", params={"range": r}).json()
        assert len(h["candles"]) >= n_min, r
        assert h["interval"] == "1d" and h["is_demo"] is True
    c = h["candles"][-1]
    assert c["l"] <= c["o"] <= c["h"] and c["l"] <= c["c"] <= c["h"]


def test_valuation_dividends_revenue(client):
    v = client.get(f"{API}/instruments/2330.TW/valuation").json()
    assert len(v["per_multiples"]) == 5 and v["per_multiples"] == sorted(v["per_multiples"])
    assert v["current"]["per"] > 0 and 0 <= v["current"]["per_percentile_5y"] <= 1
    pt = v["series"][-1]
    assert pt["per"] == pytest.approx(pt["close"] / pt["eps_ttm"], rel=1e-3)
    etf = client.get(f"{API}/instruments/0050.TW/valuation").json()
    assert etf["per_multiples"] == [] and etf["notes"]
    divs = client.get(f"{API}/instruments/00878.TW/dividends").json()
    assert divs and divs[0]["ex_dividend_date"] >= divs[-1]["ex_dividend_date"]
    assert client.get(f"{API}/instruments/2330.TW/revenue").json() == []  # offline: no shioaji-data


def test_sse_stream_once(client):
    with client.stream("GET", f"{API}/stream/quotes", params={"symbols": "2330.TW,AAPL", "once": True}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert body.count("event: quote") == 2 and '"symbol": "2330.TW"' in body


def test_health_and_openapi(app):
    from fastapi.testclient import TestClient

    c = TestClient(app)
    assert c.get(f"{API}/health").json()["status"] == "ok"
    spec = c.get(f"{API}/openapi.json").json()
    assert "/api/v1/portfolio/performance" in spec["paths"]


def test_nice_multiples():
    from forliosa.services.instruments import nice_multiples

    # 5th–95th percentile 13.36–31.48 -> step 6 from 12
    vals = [13.36] * 5 + [20.0] * 90 + [31.48] * 5
    assert nice_multiples(vals) == [12, 18, 24, 30, 36]
    assert nice_multiples([4.5, 6.0, 9.6] * 10) == [4.5, 6.0, 7.5, 9.0, 10.5]
    assert nice_multiples([1.0]) == []


# -- integration additions (1D/5D, total-return index benchmark, null fields) ---------------------
def test_performance_short_ranges(client, seeded):
    full = client.get(f"{API}/portfolio/performance", params={"range": "ALL"}).json()["series"]
    one = client.get(f"{API}/portfolio/performance", params={"range": "1D"}).json()
    # 1D = previous close -> latest close: two points, the first one is the base (index 1.0)
    assert [p["t"] for p in one["series"]] == [p["t"] for p in full[-2:]]
    assert one["series"][0]["twr_index"] == 1.0 and one["series"][0]["benchmark_index"] == 1.0
    assert one["start_date"] == full[-2]["t"] and one["end_date"] == full[-1]["t"]
    assert one["twr"] == pytest.approx(full[-1]["twr_index"] / full[-2]["twr_index"] - 1, abs=1e-5)
    assert one["xirr"] is None  # annualizing one day is meaningless
    five = client.get(f"{API}/portfolio/performance", params={"range": "5D"}).json()
    # 5D = the last 5 trading days: base close + 5 points
    assert [p["t"] for p in five["series"]] == [p["t"] for p in full[-6:]]
    assert five["series"][0]["twr_index"] == 1.0
    assert five["twr"] == pytest.approx(full[-1]["twr_index"] / full[-6]["twr_index"] - 1, abs=1e-5)
    assert five["benchmark"]["twr"] == pytest.approx(
        full[-1]["benchmark_index"] / full[-6]["benchmark_index"] - 1, abs=1e-5)
    assert five["xirr"] is None and five["max_drawdown"] <= 0


def test_total_return_index_benchmark(client, seeded, market):
    from decimal import Decimal

    from forliosa.marketdata.base import BaseProvider
    from forliosa.marketdata.demo import DemoProvider
    from forliosa.marketdata.service import MarketData, set_market_data
    from forliosa.timeutil import is_tw_trading_day

    class FakeIndexProvider(BaseProvider):
        name = "fake-index"

        def index_history(self, index_id, start, end):
            assert index_id == "TAIEX"
            return [(d, Decimal(20000) * Decimal("1.001") ** i) for i, d in enumerate(tw_trading_days(start, end))]

    # No index data (offline demo provider): the benchmark has a name but no line.
    r = client.patch(f"{API}/me/preferences", json={"benchmark": "taiextr"})
    assert r.status_code == 200 and r.json()["preferences"]["benchmark"] == "^TAIEXTR"
    p = client.get(f"{API}/portfolio/performance", params={"range": "1M"}).json()
    assert p["benchmark"] == {"symbol": "^TAIEXTR", "name": "發行量加權股價報酬指數", "twr": None}
    assert all(pt["benchmark_index"] is None for pt in p["series"])

    set_market_data(MarketData([FakeIndexProvider(), DemoProvider()]))
    try:
        p = client.get(f"{API}/portfolio/performance", params={"range": "5D", "benchmark": "^TAIEXTR"}).json()
        tw_days = sum(1 for pt in p["series"][1:] if is_tw_trading_day(date.fromisoformat(pt["t"])))
        # A total-return index already includes dividends: its daily change is the benchmark return.
        assert p["benchmark"]["twr"] == pytest.approx(1.001 ** tw_days - 1, abs=1e-6)
        assert p["series"][0]["benchmark_index"] == 1.0 and p["is_demo"] is True  # holdings are demo
    finally:
        set_market_data(market)


def test_cash_and_split_transactions_have_null_quantity_and_price(client):
    acc = make_account(client)
    dep = add_txn(client, account_id=acc["id"], type="deposit", trade_date=trading_day(30).isoformat(), amount=500000)
    assert dep["symbol"] is None and dep["quantity"] is None and dep["price"] is None
    add_txn(client, account_id=acc["id"], symbol="0050", type="buy", trade_date=trading_day(30).isoformat(),
            quantity=1000, price=100)
    split = add_txn(client, account_id=acc["id"], symbol="0050", type="split", trade_date=trading_day(10).isoformat(),
                    quantity=4)
    assert split["quantity"] == 4 and split["price"] is None
    page = client.get(f"{API}/transactions", params={"type": "deposit"}).json()
    assert page["items"][0]["quantity"] is None
    assert client.get(f"{API}/instruments/0050.TW/revenue").json() == []  # ETFs have no monthly revenue
