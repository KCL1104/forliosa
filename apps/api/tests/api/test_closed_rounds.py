"""Closed positions (出清紀錄): GET /portfolio/closed and GET /instruments/{symbol}/position/history.

Account: fee 0.1425 % × 0.28 discount, minimum NT$20 (floor to the dollar); stock tax 0.3 % (floor).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from forliosa.timeutil import last_tw_trading_day, today_taipei

API = "/api/v1"


def day(days_ago: int) -> str:
    return last_tw_trading_day(today_taipei() - timedelta(days=days_ago)).isoformat()


def make_account(client, name="永豐"):
    r = client.post(f"{API}/accounts", json={"name": name, "currency": "TWD", "fee_discount": 0.28})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def add(client, **body):
    r = client.post(f"{API}/transactions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def rounds(client):
    """2330: buy 2000 → sell 1000 → dividend → sell 1000 (closed) → buy 1000 again (still open)."""
    acc = make_account(client)
    d1, d2, d3, d4, d5 = day(300), day(200), day(150), day(100), day(50)
    b1 = add(client, account_id=acc, symbol="2330.TW", type="buy", trade_date=d1, quantity=2000, price=100)
    s1 = add(client, account_id=acc, symbol="2330.TW", type="sell", trade_date=d2, quantity=1000, price=110)
    dv = add(client, account_id=acc, symbol="2330.TW", type="cash_dividend", trade_date=d3, price=5)
    s2 = add(client, account_id=acc, symbol="2330.TW", type="sell", trade_date=d4, quantity=1000, price=120)
    b2 = add(client, account_id=acc, symbol="2330.TW", type="buy", trade_date=d5, quantity=1000, price=90)
    # hand-checked fees and taxes
    assert (b1["fee"], s1["fee"], s1["tax"], s2["fee"], s2["tax"], b2["fee"]) == (79, 43, 330, 47, 360, 35)
    assert dv["amount"] == 5000 and dv["health_insurance"] == 0  # 1000 × 5, below the NT$20,000 threshold
    return {"account": acc, "dates": (d1, d2, d3, d4, d5)}


def test_closed_round_numbers_are_hand_checked(client, rounds):
    d1, _, _, d4, _ = rounds["dates"]
    closed = client.get(f"{API}/portfolio/closed").json()
    assert len(closed) == 1  # the second round (bought again) is still open
    r = closed[0]
    # buy 2000 @ 100: 200,000 + fee floor(200,000 × 0.1425 % × 0.28 = 79.8) = 79 → cost 200,079
    # sell 1000 @ 110: 110,000 − fee 43 − tax 330 = 109,627; cost of 1000 = 100,039.5 → +9,587.5
    # sell 1000 @ 120: 120,000 − fee 47 − tax 360 = 119,593; cost of 1000 = 100,039.5 → +19,553.5
    assert r == {
        "symbol": "2330.TW", "name": r["name"], "account_id": rounds["account"], "currency": "TWD",
        "opened_at": d1, "closed_at": d4,
        "holding_days": (date.fromisoformat(d4) - date.fromisoformat(d1)).days,
        "total_bought_qty": 2000, "total_sold_qty": 2000,
        "cost_basis": 200079.0,
        "realized_pnl": 29141.0,  # 9,587.5 + 19,553.5
        "realized_pnl_pct": round(29141 / 200079, 6),  # 0.145647
        "dividends_received": 5000.0,
        "fees_and_taxes": 859.0,  # 79 + 43 + 330 + 47 + 360
        "sources": ["帳本紀錄"],
    }
    assert r["realized_pnl_pct"] == 0.145647


def test_reopened_symbol_is_held_and_closed_one_is_not(client, rounds):
    holdings = client.get(f"{API}/portfolio/holdings").json()
    assert [(h["symbol"], h["quantity"]) for h in holdings] == [("2330.TW", 1000)]
    assert holdings[0]["cost_basis"] == 90035.0  # only the open round: 90,000 + 35
    pos = client.get(f"{API}/instruments/2330/position").json()
    assert pos["quantity"] == 1000 and len(pos["markers"]) == 5

    hist = client.get(f"{API}/instruments/2330/position/history").json()
    assert [r["closed_at"] for r in hist["rounds"]] == [rounds["dates"][3]]
    assert [m["type"] for m in hist["markers"]] == ["buy", "sell", "dividend", "sell", "buy"]
    assert all(m["account_id"] == rounds["account"] for m in hist["markers"])
    assert hist["markers"][3] == {"date": rounds["dates"][3], "type": "sell", "quantity": 1000, "price": 120.0,
                                  "amount": 120000.0, "account_id": rounds["account"]}


def test_fully_sold_symbol_is_history_not_holding(client, other_client):
    acc = make_account(client)
    add(client, account_id=acc, symbol="2317.TW", type="buy", trade_date=day(120), quantity=1000, price=200)
    add(client, account_id=acc, symbol="2317.TW", type="sell", trade_date=day(60), quantity=1000, price=210)
    # dividend recorded on the payment date, after the shares were sold: it belongs to that round
    add(client, account_id=acc, symbol="2317.TW", type="cash_dividend", trade_date=day(30), amount=5500)
    assert client.get(f"{API}/portfolio/holdings").json() == []
    assert client.get(f"{API}/instruments/2317/position").json() is None
    hist = client.get(f"{API}/instruments/2317.TW/position/history").json()
    assert len(hist["rounds"]) == 1 and hist["rounds"][0]["dividends_received"] == 5500.0
    # buy 200,000 + fee 79 = 200,079; sell 210,000 − fee floor(83.79) 83 − tax 630 = 209,287 → +9,208
    assert hist["rounds"][0]["realized_pnl"] == 9208.0 and hist["rounds"][0]["fees_and_taxes"] == 792.0
    assert [m["type"] for m in hist["markers"]] == ["buy", "sell", "dividend"]
    # never traded: empty history (not 404); other users see nothing
    assert client.get(f"{API}/instruments/2454/position/history").json()["rounds"] == []
    assert other_client.get(f"{API}/portfolio/closed").json() == []
    assert other_client.get(f"{API}/instruments/2317/position/history").json()["markers"] == []
    assert client.get(f"{API}/instruments/ZZZZ/position/history").status_code == 404


def test_closed_rounds_per_account_and_day_trade(client):
    a = make_account(client, "甲")
    b = make_account(client, "乙")
    add(client, account_id=a, symbol="0050.TW", type="buy", trade_date=day(90), quantity=1000, price=100)
    add(client, account_id=b, symbol="0050.TW", type="buy", trade_date=day(80), quantity=500, price=100)
    add(client, account_id=a, symbol="0050.TW", type="sell", trade_date=day(40), quantity=1000, price=101)
    # a day trade from zero is a round that opens and closes on the same day
    t = day(20)
    add(client, account_id=b, symbol="2330.TW", type="buy", trade_date=t, quantity=1000, price=100, is_day_trade=True)
    add(client, account_id=b, symbol="2330.TW", type="sell", trade_date=t, quantity=1000, price=101, is_day_trade=True)
    closed = client.get(f"{API}/portfolio/closed").json()
    assert [(r["symbol"], r["account_id"], r["holding_days"]) for r in closed] == [
        ("2330.TW", b, 0), ("0050.TW", a, (date.fromisoformat(day(40)) - date.fromisoformat(day(90))).days)]
    # ETF tax 0.1 %: 101,000 − fee floor(40.30) 40 − tax 101 = 100,859; cost 100,000 + 39 → +820
    assert closed[1]["realized_pnl"] == 820.0
    # day-trade tax 0.15 %: 101,000 − 40 − 151 = 100,809; cost 100,039 → +770
    assert closed[0]["realized_pnl"] == 770.0
    only_b = client.get(f"{API}/portfolio/closed", params={"account_id": b}).json()
    assert [r["symbol"] for r in only_b] == ["2330.TW"]
    held = client.get(f"{API}/portfolio/holdings").json()
    assert [(h["symbol"], h["quantity"]) for h in held] == [("0050.TW", 500)]
    assert client.get(f"{API}/portfolio/closed", params={"account_id": "acc_nope"}).status_code == 404
