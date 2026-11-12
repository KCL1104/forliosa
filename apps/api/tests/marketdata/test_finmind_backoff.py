"""FinMind quota handling: back off, keep serving the disk cache, never hide cached real data."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from forliosa.marketdata.base import ProviderUnavailable
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.finmind import BACKOFF_QUOTA_SECONDS, FinMindProvider, extract_rows
from forliosa.marketdata.http import DiskCache
from forliosa.marketdata.service import MarketData

FIX = Path(__file__).parent / "fixtures"


class QuotaExhaustedFetcher:
    def __init__(self):
        self.calls: list[str] = []

    def get_json(self, url, params=None, headers=None):
        self.calls.append(params["dataset"])
        raise ProviderUnavailable("api.finmindtrade.com 回應 HTTP 402")


@pytest.fixture()
def provider(tmp_path):
    rows = extract_rows(json.loads((FIX / "finmind_price_live.json").read_text()))
    stock_id = rows[0]["stock_id"]
    # A stale (TTL expired) cached copy of the daily prices; nothing cached for other datasets.
    DiskCache(tmp_path / "finmind").write("TaiwanStockPrice", f"{stock_id}-2018-01-01",
                                          json.dumps({"fetched_at": 0, "rows": rows}).encode())
    fetcher = QuotaExhaustedFetcher()
    p = FinMindProvider(fetcher=fetcher, cache_dir=tmp_path)
    clock = [1_000_000.0]
    p._clock = lambda: clock[0]
    return p, fetcher, clock, f"{stock_id}.TW"


def test_quota_error_starts_a_backoff_that_serves_cached_rows_without_requests(provider):
    p, fetcher, clock, symbol = provider
    with pytest.raises(ProviderUnavailable):
        p.monthly_revenue(symbol)
    assert fetcher.calls == ["TaiwanStockMonthRevenue"] and p.backing_off()
    assert p.history(symbol, date(2000, 1, 1), date(2100, 1, 1))  # stale cache, no request
    with pytest.raises(ProviderUnavailable):
        p.dividends(symbol)  # not cached: fails fast without a request
    assert fetcher.calls == ["TaiwanStockMonthRevenue"]
    clock[0] += BACKOFF_QUOTA_SECONDS + 1
    assert not p.backing_off()


def test_facade_keeps_answering_from_the_finmind_cache_after_a_quota_error(provider):
    p, fetcher, _, symbol = provider
    md = MarketData([p, DemoProvider()], policy="personal")
    md.monthly_revenue(symbol)  # FinMind 402 -> the demo provider answers instead
    h = md.history(symbol, date(2000, 1, 1), date(2100, 1, 1))
    assert h.source == "finmind" and h.is_demo is False and h.candles
    assert {s["name"]: s["available"] for s in md.status()}["finmind"] is False  # backing off: cache only
    assert fetcher.calls == ["TaiwanStockMonthRevenue"]
