"""2026-11-16 (「台達電今天為啥跌這麼多?」 took 17–20 s): with the stock page and an AI turn loading at once, the same
files were downloaded 3–5 times, and every host waited behind TWSE's 3 s interval because the limiter slept while
holding its lock. One download per file at a time now, and a wait for one host no longer blocks the others."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import httpx

from forliosa.marketdata import http
from forliosa.marketdata.base import BaseProvider, InstrumentInfo, ProviderUnavailable, tw_symbol
from forliosa.marketdata.http import RateLimiter, SingleFlight, sha256_hex
from forliosa.marketdata.service import MarketData
from forliosa.marketdata.shioaji_data import MANIFEST_STALE_SECONDS, MANIFEST_TTL_SECONDS, ShioajiDataProvider
from forliosa.marketdata.tpex import TpexOpenApiProvider
from forliosa.marketdata.twse import TwseOpenApiProvider

TWSE, TPEX, GITHUB = "openapi.twse.com.tw", "www.tpex.org.tw", "raw.githubusercontent.com"


def run_threads(n: int, fn) -> tuple[list[Any], list[BaseException]]:
    """``fn()`` in ``n`` threads started together; their results and exceptions."""
    results: list[Any] = []
    errors: list[BaseException] = []
    lock = threading.Lock()
    barrier = threading.Barrier(n)

    def target() -> None:
        barrier.wait()
        try:
            value = fn()
        except BaseException as exc:  # collected for the test
            with lock:
                errors.append(exc)
        else:
            with lock:
                results.append(value)

    threads = [threading.Thread(target=target) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not any(t.is_alive() for t in threads), "a caller never returned (deadlock)"
    return results, errors


class SlowFetcher:
    """Answers after ``delay`` seconds, so concurrent callers overlap; counts requests per URL."""

    def __init__(self, answers: dict[str, Any], delay: float = 0.2, fail: bool = False):
        self.answers, self.delay, self.fail = answers, delay, fail
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def _answer(self, url: str) -> Any:
        with self._lock:
            self.calls.append(url)
        time.sleep(self.delay)
        if self.fail:
            raise ProviderUnavailable(f"{url} 503")
        return next(v for k, v in self.answers.items() if url.endswith(k))

    def get_json(self, url: str, params=None, headers=None) -> Any:
        return self._answer(url)

    def get_bytes(self, url: str, params=None, headers=None) -> bytes:
        value = self._answer(url)
        return value if isinstance(value, bytes) else json.dumps(value).encode()


# -- the limiter ---------------------------------------------------------------------------------
def test_limiter_reserves_each_hosts_slots_interval_apart():
    limiter = RateLimiter(per_host={"twse.com.tw": 3.0, "tpex.org.tw": 2.0})
    limiter._clock = lambda: 100.0  # nobody's sleep has ended yet: every caller takes the next free slot
    slept: list[float] = []
    limiter._sleep = slept.append
    assert [limiter.wait(TWSE) for _ in range(3)] == [0.0, 3.0, 6.0]
    assert [limiter.wait(TPEX) for _ in range(2)] == [0.0, 2.0]  # each host keeps its own budget
    assert limiter.wait(GITHUB) == limiter.wait(GITHUB) == 0.0  # no interval configured
    assert slept == [3.0, 6.0, 2.0]


def test_limiter_turn_past_a_deadline_is_not_taken():
    """``wait_until``: a turn that would start at or after the deadline is not reserved (2026-11-17 review: an AI
    LangSearch request past its deadline held the next one up for an interval it never used)."""
    limiter = RateLimiter(per_host={"twse.com.tw": 3.0})
    limiter._clock = lambda: 100.0
    slept: list[float] = []
    limiter._sleep = slept.append
    assert limiter.wait_until(TWSE, 101.0) == 0.0  # 100: now
    assert limiter.wait_until(TWSE, 103.0) is None  # the next turn, 103, is not before 103: not taken
    assert limiter.wait_until(TWSE, 104.0) == 3.0  # ... so it is still free
    assert limiter.wait(TWSE) == 6.0
    assert slept == [3.0, 6.0]


def test_limiter_spacing_from_many_threads_is_exactly_the_interval():
    limiter = RateLimiter(per_host={"twse.com.tw": 3.0})
    limiter._clock = lambda: 0.0
    limiter._sleep = lambda seconds: None
    results, errors = run_threads(8, lambda: limiter.wait(TWSE))
    assert not errors
    assert sorted(results) == [3.0 * i for i in range(8)]  # every slot once, 3 s apart, none shared


def test_a_wait_for_one_host_does_not_hold_up_another_host():
    limiter = RateLimiter(per_host={"twse.com.tw": 3.0})
    in_sleep, release = threading.Event(), threading.Event()

    def sleep(seconds: float) -> None:  # a TWSE wait that lasts until the test lets it go
        in_sleep.set()
        release.wait(5)

    limiter._sleep = sleep
    limiter.wait(TWSE)
    waiting = threading.Thread(target=limiter.wait, args=(TWSE,))
    waiting.start()
    assert in_sleep.wait(5)
    other = threading.Thread(target=limiter.wait, args=(GITHUB,))
    other.start()
    other.join(timeout=1)
    assert not other.is_alive(), "GitHub waited behind the TWSE sleep"
    assert waiting.is_alive()  # still sleeping: the TWSE interval is kept
    release.set()
    waiting.join(timeout=5)


def test_a_slow_download_is_logged_with_its_wait_for_the_host_interval(monkeypatch, caplog):
    limiter = RateLimiter(per_host={"twse.com.tw": 3.0})
    limiter._clock = lambda: 0.0
    limiter._sleep = lambda seconds: None
    fetcher = http.HttpFetcher(limiter=limiter, retries=0,
                               client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))))
    url = "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL"
    with caplog.at_level(logging.INFO, logger="forliosa.marketdata.http"):
        fetcher.get_bytes(url)
        assert "slow fetch" not in caplog.text  # quick: nothing logged
        monkeypatch.setattr(http, "SLOW_FETCH_SECONDS", 0.0)
        fetcher.get_bytes(url)
    assert "slow fetch openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL" in caplog.text
    assert "3.00 s of it waiting for the host interval, 1 attempt(s)" in caplog.text


# -- single flight ---------------------------------------------------------------------------------
def test_concurrent_callers_share_one_call():
    flight, calls = SingleFlight(), []

    def fn() -> str:
        calls.append(1)
        time.sleep(0.2)
        return "data"

    results, errors = run_threads(6, lambda: flight.do("k", fn))
    assert results == ["data"] * 6 and not errors and len(calls) == 1
    assert flight.do("k", fn) == "data" and len(calls) == 2  # nothing is kept once the call is over


def test_an_error_reaches_every_waiter_and_is_not_kept():
    flight, calls = SingleFlight(), []

    def fn() -> str:
        calls.append(1)
        time.sleep(0.2)
        raise ProviderUnavailable("twse 503")

    results, errors = run_threads(5, lambda: flight.do("k", fn))
    assert not results and len(errors) == 5 and len(calls) == 1
    assert all(isinstance(e, ProviderUnavailable) for e in errors)
    assert flight.do("k", lambda: "again") == "again"  # the next caller tries again


def test_a_call_that_asks_for_its_own_key_runs_it_instead_of_waiting_for_itself():
    flight = SingleFlight()
    results, errors = run_threads(1, lambda: flight.do("k", lambda: flight.do("k", lambda: "inner") + "+outer"))
    assert results == ["inner+outer"] and not errors


# -- providers -------------------------------------------------------------------------------------
TWT48U = [{"Date": "1151120", "Code": "2308", "Name": "台達電", "Exdividend": "息", "StockDividendRatio": "",
           "CashDividend": "5.0"}]


def test_twse_downloads_a_file_once_for_concurrent_callers():
    fetcher = SlowFetcher({"/exchangeReport/TWT48U_ALL": TWT48U})
    provider = TwseOpenApiProvider(fetcher)  # type: ignore[arg-type]
    results, errors = run_threads(5, lambda: provider.dividends("2308.TW"))
    assert not errors and len(fetcher.calls) == 1
    assert all(r == results[0] and r[0].cash_dividend == 5 for r in results)
    provider.ex_rights_on(["2308.TW"], results[0][0].ex_dividend_date)  # cached for CACHE_SECONDS
    assert len(fetcher.calls) == 1


def test_twse_failure_reaches_every_caller_and_is_not_cached():
    fetcher = SlowFetcher({"/exchangeReport/TWT48U_ALL": TWT48U}, fail=True)
    provider = TwseOpenApiProvider(fetcher)  # type: ignore[arg-type]
    results, errors = run_threads(4, lambda: provider.dividends("2308.TW"))
    assert not results and len(errors) == 4 and len(fetcher.calls) == 1
    fetcher.fail = False
    assert provider.dividends("2308.TW")[0].cash_dividend == 5 and len(fetcher.calls) == 2


def test_tpex_downloads_each_file_once_for_concurrent_callers():
    rows = [{"Date": "1151113", "SecuritiesCompanyCode": "6488", "CompanyName": "環球晶", "Close": "400.0",
             "Change": "-5.0", "Open": "405", "High": "406", "Low": "399", "TradingShares": "1000"}]
    fetcher = SlowFetcher({"/tpex_mainboard_quotes": rows, "/tpex_exright_prepost": []})
    provider = TpexOpenApiProvider(fetcher)  # type: ignore[arg-type]
    sym = tw_symbol("6488", "TPEX")
    results, errors = run_threads(4, lambda: provider.quotes([sym]))
    assert not errors and len(fetcher.calls) == 1 and all(r[sym].price == 400 for r in results)
    day = results[0][sym].trade_date
    results, errors = run_threads(4, lambda: provider.ex_rights_on([sym], day))
    assert not errors and results == [{}] * 4 and len(fetcher.calls) == 2


def shioaji(tmp_path, fetcher) -> ShioajiDataProvider:
    return ShioajiDataProvider("https://raw.githubusercontent.com/Sinotrade/shioaji-data/main", tmp_path, fetcher)


COMPANY = json.dumps({"code": "2308", "name": "台達電"}).encode()
MANIFEST = {"release_id": "r1", "companies": {"2308": {"path": "v1/tw/companies/json/2308.json",
                                                      "sha256": sha256_hex(COMPANY)}}}


def test_shioaji_downloads_the_manifest_and_a_file_once_for_concurrent_callers(tmp_path):
    fetcher = SlowFetcher({"/v1/manifest.json": MANIFEST, "/2308.json": COMPANY})
    provider = shioaji(tmp_path, fetcher)
    results, errors = run_threads(5, lambda: provider._company("2308"))
    assert not errors and all(r == {"code": "2308", "name": "台達電"} for r in results)
    assert sorted(u.rsplit("/", 1)[-1] for u in fetcher.calls) == ["2308.json", "manifest.json"]


def test_shioaji_manifest_is_served_stale_while_one_background_download_replaces_it(tmp_path):
    fetcher = SlowFetcher({"/v1/manifest.json": MANIFEST}, delay=0.3)
    provider = shioaji(tmp_path, fetcher)
    assert provider.manifest()["release_id"] == "r1" and len(fetcher.calls) == 1
    fetcher.answers = {"/v1/manifest.json": {**MANIFEST, "release_id": "r2"}}
    provider._manifest_at -= MANIFEST_TTL_SECONDS + 1
    results, errors = run_threads(4, provider.manifest)  # past the TTL: nobody waits for the download
    assert not errors and [r["release_id"] for r in results] == ["r1"] * 4
    deadline = time.monotonic() + 5
    while provider.manifest()["release_id"] != "r2" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert provider.manifest()["release_id"] == "r2" and len(fetcher.calls) == 2  # one refresh for all of them
    fetcher.answers = {"/v1/manifest.json": {**MANIFEST, "release_id": "r3"}}
    provider._manifest_at -= MANIFEST_STALE_SECONDS + 1
    assert provider.manifest()["release_id"] == "r3"  # older than a day: the request waits for the new one


def test_shioaji_failed_background_refresh_keeps_the_old_manifest(tmp_path, caplog):
    fetcher = SlowFetcher({"/v1/manifest.json": MANIFEST}, delay=0.0)
    provider = shioaji(tmp_path, fetcher)
    provider.manifest()
    (tmp_path / "shioaji-data" / "meta" / "manifest.json").unlink()  # no disk copy to fall back on either
    fetcher.fail = True
    provider._manifest_at -= MANIFEST_TTL_SECONDS + 1
    assert provider.manifest()["release_id"] == "r1"
    deadline = time.monotonic() + 5
    while provider._refreshing and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not provider._refreshing and "manifest refresh failed" in caplog.text
    assert provider.manifest()["release_id"] == "r1"


class SlowCatalog(BaseProvider):
    name = "catalog"

    def __init__(self) -> None:
        self.calls = 0

    def instruments(self) -> list[InstrumentInfo]:
        self.calls += 1
        time.sleep(0.2)
        return [InstrumentInfo("2308.TW", "2308", "台達電", "TWSE", "stock", "TWD")]


def test_master_is_rebuilt_once_for_concurrent_requests(caplog):
    catalog = SlowCatalog()
    md = MarketData([catalog], policy="commercial")
    with caplog.at_level("INFO", logger="forliosa.marketdata.service"):
        results, errors = run_threads(5, lambda: md.resolve("2308"))
    assert results == ["2308.TW"] * 5 and not errors and catalog.calls == 1
    assert caplog.text.count("instrument master rebuilt: 1 instruments in") == 1  # its time, for slow requests
    md._master_until = 0.0  # expired: the next request rebuilds it again
    assert md.instrument("2308").name == "台達電" and catalog.calls == 2
