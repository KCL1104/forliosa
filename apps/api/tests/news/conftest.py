"""News test fixtures: fixture files, a fake news source, settings overrides, a fake Messages API key pool.

No test reaches GDELT, SearXNG, Yahoo or Anthropic: sources are fakes and fixtures are trimmed live responses
(2026-11-12).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from forliosa.ai.keypool import KeyPool, set_key_pool
from forliosa.config import Settings, get_settings
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
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
