"""HttpFetcher.probe: "has this file changed?" with a conditional request for its first bytes — same allow-list
and per-host interval as every other request (fake HTTP: httpx.MockTransport)."""

from __future__ import annotations

import httpx
import pytest

from forliosa.archive import CLOSE_DATASETS
from forliosa.marketdata.base import ProviderUnavailable
from forliosa.marketdata.http import DEFAULT_LIMITER, HttpFetcher, HttpStatusError, RateLimiter, url_allowed

URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
BODY = b'[{"Date":"1151113","Code":"2330","ClosingPrice":"2400.00"},' + b'{"Code":"0050"},' * 400 + b"{}]"
ETAG, MODIFIED = '"6af62dad-4e8c7"', "Thu, 12 Nov 2026 21:20:45 GMT"


def fetcher(handler, **kw) -> tuple[HttpFetcher, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(record), headers={"User-Agent": "test"})
    kw.setdefault("limiter", RateLimiter())
    kw.setdefault("retries", 0)
    return HttpFetcher(client=client, **kw), seen


def file_server(request: httpx.Request) -> httpx.Response:
    """A static file as both OpenAPI hosts serve it: validators, conditional requests, byte ranges."""
    headers = {"ETag": ETAG, "Last-Modified": MODIFIED}
    if request.headers.get("If-None-Match") == ETAG or request.headers.get("If-Modified-Since") == MODIFIED:
        return httpx.Response(304, headers=headers)
    if "Range" in request.headers:
        last = int(request.headers["Range"].removeprefix("bytes=0-"))
        return httpx.Response(206, content=BODY[:last + 1], headers=headers)
    return httpx.Response(200, content=BODY, headers=headers)


def test_first_probe_reads_only_the_first_bytes():
    f, seen = fetcher(file_server)
    probe = f.probe(URL, first_bytes=64)
    assert (probe.status, probe.changed, probe.head) == (206, True, BODY[:64])
    assert (probe.etag, probe.last_modified) == (ETAG, MODIFIED)
    [request] = seen
    assert request.method == "GET" and str(request.url) == URL
    assert request.headers["Range"] == "bytes=0-63" and request.headers["Accept-Encoding"] == "identity"
    assert "If-None-Match" not in request.headers and "If-Modified-Since" not in request.headers


def test_unchanged_file_is_a_304_with_no_body():
    f, seen = fetcher(file_server)
    first = f.probe(URL)
    again = f.probe(URL, etag=first.etag, last_modified=first.last_modified)
    assert (again.status, again.changed, again.head) == (304, False, b"")
    assert (again.etag, again.last_modified) == (ETAG, MODIFIED)  # still the validators to send next time
    assert seen[1].headers["If-None-Match"] == ETAG and seen[1].headers["If-Modified-Since"] == MODIFIED
    assert seen[1].headers["Range"] == "bytes=0-1023"
    only_modified = f.probe(URL, last_modified=MODIFIED)  # a host with no ETag
    assert only_modified.status == 304 and "If-None-Match" not in seen[2].headers


def test_a_304_without_validators_keeps_the_ones_sent():
    f, _ = fetcher(lambda _request: httpx.Response(304))
    probe = f.probe(URL, etag=ETAG, last_modified=MODIFIED)
    assert (probe.changed, probe.etag, probe.last_modified) == (False, ETAG, MODIFIED)


def test_a_host_that_ignores_range_costs_one_normal_request_and_only_the_head_is_kept():
    f, seen = fetcher(lambda _request: httpx.Response(200, content=BODY, headers={"ETag": ETAG}))
    probe = f.probe(URL, etag='"older"', first_bytes=100)
    assert (probe.status, probe.changed, probe.head) == (200, True, BODY[:100])
    assert (probe.etag, probe.last_modified) == (ETAG, None)
    assert len(seen) == 1


@pytest.mark.parametrize("url", [
    "https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL",  # the TWSE website
    "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL",
    "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_2330.tw",  # MIS
    "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes",  # the TPEx website (only /openapi/ is allowed)
    "http://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",  # not https
])
def test_probe_refuses_anything_outside_the_allow_list(url):
    f, seen = fetcher(file_server)
    with pytest.raises(ProviderUnavailable, match="白名單"):
        f.probe(url)
    assert seen == []


def test_the_close_datasets_are_the_open_data_files_the_archive_already_downloads():
    hosts = {d.market: httpx.URL(d.url) for d in CLOSE_DATASETS}
    assert {m: (u.host, u.path) for m, u in hosts.items()} == {
        "TWSE": ("openapi.twse.com.tw", "/v1/exchangeReport/STOCK_DAY_ALL"),
        "TPEX": ("www.tpex.org.tw", "/openapi/v1/tpex_mainboard_daily_close_quotes")}
    assert all(url_allowed(d.url) for d in CLOSE_DATASETS)
    assert not any("mis." in d.url or "www.twse.com.tw" in d.url for d in CLOSE_DATASETS)


def test_probe_waits_for_the_host_interval_like_every_other_request():
    """The probe and a normal download share one budget per host: never closer together than the host's interval."""
    limiter = RateLimiter(per_host={"twse.com.tw": 3.0, "tpex.org.tw": 2.0})
    now, slept = [1000.0], []
    limiter._clock = lambda: now[0]

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    limiter._sleep = sleep
    f, seen = fetcher(file_server, limiter=limiter)
    f.probe(URL)
    f.probe(URL, etag=ETAG)
    assert slept == [3.0]
    f.get_bytes("https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL")  # a download right after a probe
    assert slept == [3.0, 3.0]
    now[0] += 10
    f.probe(URL, etag=ETAG)  # long enough since the last request: no wait
    f.probe("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes")  # another host: its own budget
    assert slept == [3.0, 3.0] and len(seen) == 5
    # the production limiter has both exchanges' intervals
    assert DEFAULT_LIMITER.interval_for("openapi.twse.com.tw") == 3.0
    assert DEFAULT_LIMITER.interval_for("www.tpex.org.tw") == 2.0


def test_refusals_and_failures():
    for status in (403, 404, 429, 302):
        f, seen = fetcher(lambda _request, status=status: httpx.Response(status), retries=2, backoff=0)
        with pytest.raises(HttpStatusError) as refused:
            f.probe(URL)
        assert refused.value.status == status and len(seen) == 1  # a refusal is not retried

    f, seen = fetcher(lambda _request: httpx.Response(503), retries=2, backoff=0)
    with pytest.raises(ProviderUnavailable):
        f.probe(URL)
    assert len(seen) == 3

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection reset", request=request)

    f, seen = fetcher(broken, retries=1, backoff=0)
    with pytest.raises(ProviderUnavailable, match="無法連線"):
        f.probe(URL)
    assert len(seen) == 2
