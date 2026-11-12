"""News test fixtures: fixture files, a fake news source, a fake SearXNG, settings overrides, a fake Messages API
key pool.

No test reaches GDELT, SearXNG, Yahoo or Anthropic: sources are fakes, SearXNG answers through an
``httpx.MockTransport`` (the autouse ``no_searxng_network`` refuses everything else), and fixtures are trimmed live
responses (2026-11-12) — except ``searxng_*_synthetic.json``, which are SYNTHETIC: built by hand from SearXNG's
documented JSON format (the sandbox cannot reach the search engines), each marked in its ``_comment`` field.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from forliosa.ai.keypool import KeyPool, set_key_pool
from forliosa.config import Settings, get_settings
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.news import searxng
from forliosa.news.sources import Query, RawItem, SourceBlocked
from tests.ai.fake_anthropic import FakeAnthropic

FIXTURES = Path(__file__).parent / "fixtures"
# The GDELT fixture was fetched at 2026-11-12 10:42 UTC (18:42 Taipei).
FETCHED_AT = datetime(2026, 11, 12, 10, 45, tzinfo=UTC)


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeSource:
    """A scripted news source: ``items[symbol]`` per call, or ``SourceBlocked`` when ``blocked`` is set."""

    def __init__(self, key: str = "gdelt", label: str = "GDELT", items: dict[str, list[RawItem]] | None = None,
                 blocked: bool = False, taiwan_only: bool = False, error: Exception | None = None):
        self.key, self.label = key, label
        self.items = items or {}
        self.blocked = blocked
        self.taiwan_only = taiwan_only
        self.error = error
        self.calls: list[Query] = []

    def supports(self, q: Query) -> bool:
        return q.taiwan or not self.taiwan_only

    def fetch(self, q: Query) -> list[RawItem]:
        self.calls.append(q)
        if self.blocked:
            raise SourceBlocked(f"{self.key} HTTP 429")
        if self.error is not None:
            raise self.error
        return list(self.items.get(q.symbol, []))


@pytest.fixture()
def settings() -> Settings:
    return get_settings().model_copy(update={"news_enabled": True, "news_ai_enabled": True})


@pytest.fixture()
def commercial_md(market):
    md = MarketData([DemoProvider()], policy="commercial")
    set_market_data(md)
    yield md
    set_market_data(market)


@pytest.fixture()
def personal_md(market):
    md = MarketData([DemoProvider()], policy="personal")
    set_market_data(md)
    yield md
    set_market_data(market)


@pytest.fixture()
def fake() -> FakeAnthropic:
    return FakeAnthropic()


@pytest.fixture()
def pool(fake):
    p = KeyPool.from_keys(["sk-test-key-one", "sk-test-key-two"], client_factory=fake.client, sleep=lambda _s: None)
    set_key_pool(p)
    yield p
    set_key_pool(None)


# -- SearXNG ------------------------------------------------------------------------------------------------------
SEARX_URL = "http://searxng.test:8080"
ENGINES = ("bing news", "duckduckgo news", "brave.news")


def searx_fixture(name: str) -> dict[str, Any]:
    """A synthetic SearXNG answer (see the module docstring)."""
    data = json.loads(fixture_bytes(name))
    assert data["_comment"].startswith("SYNTHETIC")
    return data


class FakeClock:
    """Monotonic time that only moves when the gate sleeps (or a test advances it)."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


Answer = dict[str, Any] | int | Exception | Callable[[httpx.Request], httpx.Response]


class FakeSearxng:
    """Our SearXNG behind ``httpx.MockTransport``: ``/healthz`` says OK, ``/search`` answers the scripted answers in
    turn (the last one repeats): a dict (JSON), an int (that HTTP status), an exception (raised, e.g. ConnectError)
    or a callable. Every request is recorded."""

    def __init__(self, *answers: Answer, health: bytes = b"OK") -> None:
        self.answers: list[Answer] = list(answers) or [{"results": [], "unresponsive_engines": []}]
        self.health = health
        self.requests: list[httpx.Request] = []

    @property
    def searches(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == "/search"]

    def params(self, i: int = -1) -> dict[str, str]:
        return dict(self.searches[i].url.params)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/healthz":
            return httpx.Response(200, content=self.health)
        answer = self.answers[min(len(self.searches) - 1, len(self.answers) - 1)]
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, int):
            return httpx.Response(answer, content=b"error")
        if callable(answer):
            return answer(request)
        return httpx.Response(200, json=answer)


def _refuse(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("network disabled in tests", request=request)


@pytest.fixture()
def fake_searx():
    """Install a :class:`FakeSearxng` for every SearXNG request; tests set ``.answers``."""
    fake = FakeSearxng()
    searxng.set_transport(httpx.MockTransport(fake.handler))
    yield fake
    searxng.set_transport(httpx.MockTransport(_refuse))


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


def make_searx(clock: FakeClock, now: datetime = FETCHED_AT, interval: float = 10.0,
               engines: tuple[str, ...] = ENGINES) -> searxng.SearxngSource:
    """A real :class:`SearxngSource` on the (fake) transport, with a fake clock for its pacing gate."""
    return searxng.SearxngSource(SEARX_URL, engines=engines,
                                 gate=searxng.QueryGate(interval, clock=clock, sleep=clock.sleep),
                                 now_fn=lambda: now)
