"""Databento EQUS.SUMMARY client (``forliosa.marketdata.databento``): CSV parsing, symbol spelling, batching, the 206
warning for unknown symbols, a 422 for a batch where none resolve, and the end capped at the newest session."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest

from forliosa.marketdata import databento as db
from forliosa.marketdata.http import HttpFetcher, HttpStatusError, RateLimiter

CSV = """ts_event,rtype,publisher_id,instrument_id,open,high,low,close,volume,symbol
2026-11-12T00:00:00.000000000Z,35,90,38,357.810000000,359.368400000,354.410000000,354.880000000,31874978,AAPL
2026-11-13T00:00:00.000000000Z,35,90,38,357.960000000,360.830000000,355.750000000,356.270000000,40027467,AAPL
2026-11-13T00:00:00.000000000Z,35,90,9,592.000000000,593.500000000,588.000000000,592.940000000,4768291,BRK.B
2026-11-13T00:00:00.000000000Z,35,90,77,,,,0.000000000,0,DEAD
"""
RANGE = {"start": "2024-07-01T00:00:00.000000000Z", "end": "2026-11-14T00:00:00.000000000Z",
         "schema": {"ohlcv-1d": {"start": "2024-07-01T00:00:00.000000000Z", "end": "2026-11-14T00:00:00.000000000Z"}}}


def fake(handler) -> HttpFetcher:
    client = httpx.Client(transport=httpx.MockTransport(handler), auth=("db-test", ""))
    return HttpFetcher(client=client, retries=0, extra_allowed=(db.API,), limiter=RateLimiter())


def test_parse_csv_keeps_priced_rows_with_the_session_date():
    bars = db.parse_csv(CSV)
    assert [(b.symbol, b.date, b.close) for b in bars] == [
        ("AAPL", date(2026, 11, 12), Decimal("354.8800")), ("AAPL", date(2026, 11, 13), Decimal("356.2700")),
        ("BRK.B", date(2026, 11, 13), Decimal("592.9400"))]
    assert bars[0].high == Decimal("359.3684") and bars[0].volume == 31874978


def test_us_symbols_skips_taiwan_and_duplicates():
    assert db.us_symbols(["aapl", "2330.TW", "6488.TWO", "AAPL", " brk.b ", "", "BAD SYM"]) == ["AAPL", "BRK.B"]


def test_unresolved_symbols_from_the_warning_header():
    header = '["Warning: The streaming request had one or more symbols which did not resolve: ZZZZQ, ABCD."]'
    assert db.unresolved_from_warning(header) == ["ZZZZQ", "ABCD"]
    assert db.unresolved_from_warning(None) == []


def test_daily_bars_caps_the_end_sends_basic_auth_and_reports_unknown_symbols(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path.endswith("metadata.get_dataset_range"):
            return httpx.Response(200, json=RANGE)
        return httpx.Response(206, text=CSV, headers={
            "X-Warning": '["Warning: The streaming request had one or more symbols which did not resolve: ZZZZQ."]'})

    r = db.daily_bars(fake(handler), ["AAPL", "BRK.B", "ZZZZQ", "2330.TW"], date(2020, 1, 1), date(2026, 11, 30))
    assert len(r.bars) == 3 and r.unresolved == ["ZZZZQ"]
    get = seen[-1]
    assert get.url.params["symbols"] == "AAPL,BRK.B,ZZZZQ"
    assert (get.url.params["start"], get.url.params["end"]) == ("2024-07-01", "2026-11-14")  # first day; end exclusive
    assert (get.url.params["dataset"], get.url.params["schema"]) == ("EQUS.SUMMARY", "ohlcv-1d")
    assert get.headers["authorization"].startswith("Basic ")


def test_a_batch_where_nothing_resolves_is_reported_not_raised():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": {"case": "symbology_invalid_request"}})

    r = db.daily_bars(fake(handler), ["ZZZZQ"], date(2026, 11, 1), date(2026, 11, 13), available=date(2026, 11, 13))
    assert (r.bars, r.unresolved) == ([], ["ZZZZQ"])


@pytest.mark.parametrize("status", [401, 402, 403])
def test_a_refusal_stops(status):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"detail": {"case": "auth"}})

    with pytest.raises(HttpStatusError) as err:
        db.daily_bars(fake(handler), ["AAPL"], date(2026, 11, 1), date(2026, 11, 13), available=date(2026, 11, 13))
    assert err.value.status == status


def test_nothing_is_asked_for_taiwan_only_or_an_empty_range():
    def handler(req: httpx.Request) -> httpx.Response:  # pragma: no cover - must not be called
        raise AssertionError("no request expected")

    assert db.daily_bars(fake(handler), ["2330.TW"], date(2026, 11, 1), date(2026, 11, 13),
                         available=date(2026, 11, 13)).bars == []
    assert db.daily_bars(fake(handler), ["AAPL"], date(2026, 11, 13), date(2026, 11, 1),
                         available=date(2026, 11, 13)).bars == []
