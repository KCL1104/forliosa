"""The stock chart's 「比較：加權報酬指數」 asks /instruments/^TAIEXTR/history; it used to 404 (2026-11-14 review)."""
from __future__ import annotations

from decimal import Decimal

from forliosa.marketdata.base import BaseProvider
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.timeutil import tw_trading_days

API = "/api/v1"


def test_index_without_data_answers_with_a_note(client):
    r = client.get(f"{API}/instruments/%5ETAIEXTR/history", params={"range": "1M"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["symbol"], body["candles"]) == ("^TAIEXTR", [])
    assert body["notes"] == ["沒有 發行量加權股價報酬指數 的資料，不能比較"]


def test_index_history_is_served_as_close_only_candles(client, market):
    class FakeIndexProvider(BaseProvider):
        name = "fake-index"

        def index_history(self, index_id, start, end):
            return [(d, Decimal(20000) + i) for i, d in enumerate(tw_trading_days(start, end))]

    set_market_data(MarketData([FakeIndexProvider(), DemoProvider()], policy="personal"))
    try:
        body = client.get(f"{API}/instruments/%5ETAIEXTR/history", params={"range": "1M"}).json()
        assert len(body["candles"]) > 10 and body["notes"] == []
        assert all(c["o"] == c["c"] and c["v"] == 0 for c in body["candles"])
        assert body["candles"][1]["c"] == body["candles"][0]["c"] + 1
        five = client.get(f"{API}/instruments/%5ETAIEXTR/history", params={"range": "5D"}).json()
        assert len(five["candles"]) == 5
    finally:
        set_market_data(market)
