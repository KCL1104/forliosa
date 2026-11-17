"""Test fixtures: temp SQLite database, offline market data (demo provider only)."""

from __future__ import annotations

import os

os.environ.setdefault("FORLIOSA_ENV", "test")
os.environ.setdefault("MARKET_DATA_PROVIDERS", "demo")
os.environ.setdefault("DEMO_JITTER", "false")
# The machine running the tests may carry deployment settings (a cloud session's environment has the Discord client
# secret and the Telegram bot token): the tests decide these themselves, so whatever is set outside is dropped.
os.environ.pop("DISCORD_CLIENT_ID", None)
os.environ.pop("DISCORD_CLIENT_SECRET", None)
os.environ.pop("DISCORD_REDIRECT_URI", None)
os.environ.pop("TELEGRAM_BOT_TOKEN", None)
os.environ.pop("TELEGRAM_BOT_USERNAME", None)
os.environ.pop("TERMS_VERSION", None)
os.environ.pop("TERMS_EFFECTIVE_DATE", None)
os.environ.pop("TERMS_SUMMARY", None)
os.environ.pop("GOOGLE_CLIENT_ID", None)
os.environ.pop("GOOGLE_CLIENT_SECRET", None)
os.environ.pop("GOOGLE_REDIRECT_URI", None)
os.environ.pop("PRICE_HISTORY_SOURCE", None)
os.environ.pop("ADMIN_EMAILS", None)
os.environ.pop("FRONTEND_URL", None)
os.environ.pop("CORS_ORIGINS", None)
os.environ.pop("COOKIE_DOMAIN", None)
os.environ.pop("SESSION_SECRET", None)
os.environ.pop("NEWS_LANGSEARCH_ENABLED", None)
os.environ.pop("LANGSEARCH_API_KEY", None)
os.environ.pop("AI_LANGSEARCH_ENABLED", None)

import pytest
from fastapi.testclient import TestClient

import forliosa.models  # noqa: F401 - register every table on Base.metadata before create_all
from forliosa.db import Base, make_engine, set_engine
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data


@pytest.fixture(autouse=True)
def no_real_ai_keys():
    """No test may reach the real Claude API (the "why" sentence is on by default): an empty key pool unless a
    test installs fake clients, and every server tool enabled again."""
    from forliosa.ai.keypool import KeyPool, set_key_pool
    from forliosa.ai.tools import reset_excluded_tools

    set_key_pool(KeyPool([]))
    reset_excluded_tools()
    yield
    set_key_pool(None)
    reset_excluded_tools()


@pytest.fixture(autouse=True)
def no_sec_network():
    """No test may reach SEC EDGAR (the sandbox may have SEC_CONTACT_EMAIL set): SEC is disabled unless a test
    installs a fake client with ``forliosa.services.sec.set_sec_client``."""
    from forliosa.services.sec import reset_sec_state, set_sec_client

    reset_sec_state()
    set_sec_client(None)
    yield
    reset_sec_state()


@pytest.fixture(autouse=True)
def no_discord_network():
    """No test may reach discord.com: every Discord request fails unless a test installs a mock transport with
    ``forliosa.services.discord_oauth.set_transport``."""
    import httpx

    from forliosa.services import discord_oauth

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network disabled in tests", request=request)

    discord_oauth.set_transport(httpx.MockTransport(refuse))
    yield
    discord_oauth.set_transport(None)


@pytest.fixture(autouse=True)
def no_searxng_network():
    """No test may reach a SearXNG instance (it is on by default): every SearXNG request fails unless a test
    installs a mock transport with ``forliosa.news.searxng.set_transport``. Pacing gates start fresh."""
    import httpx

    from forliosa.news import searxng

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network disabled in tests", request=request)

    searxng.set_transport(httpx.MockTransport(refuse))
    searxng.reset_gates()
    yield
    searxng.set_transport(None)
    searxng.reset_gates()


@pytest.fixture(autouse=True)
def no_langsearch_network():
    """No test may reach LangSearch: every request fails unless a test installs a mock transport with
    ``forliosa.news.langsearch.set_transport`` (or gives the client its own). The shared limiters start fresh, and
    no reply that came after an AI request's deadline is carried into another test."""
    import httpx

    from forliosa.ai import tw_news
    from forliosa.news import langsearch

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network disabled in tests", request=request)

    langsearch.set_transport(httpx.MockTransport(refuse))
    langsearch.reset_limiters()
    langsearch.reset_late()
    tw_news.reset_caches()
    yield
    langsearch.set_transport(None)
    langsearch.reset_limiters()
    langsearch.reset_late()
    tw_news.reset_caches()


@pytest.fixture(autouse=True)
def no_push_network():
    """No test may reach a Discord webhook or the Telegram Bot API: every group-push request fails unless a test
    installs a mock transport with ``forliosa.services.pushers.set_transport``. Each test starts with a closed circuit
    breaker and no webhook set-up attempts counted."""
    import httpx

    from forliosa.services import channels, pushers

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network disabled in tests", request=request)

    pushers.set_transport(httpx.MockTransport(refuse))
    pushers.reset_state()
    channels.reset_state()
    yield
    pushers.set_transport(None)
    pushers.reset_state()
    channels.reset_state()


@pytest.fixture(autouse=True)
def roomy_ai_quota(monkeypatch):
    """The deployment's AI quota is tight (free: 3 questions a day, about US$1 a month; 產品負責人 2026-11-15). Tests
    about other things ask several questions: they run with the earlier roomy numbers. Quota tests set their own with
    ``ai_env``, and ``tests/ai/test_quota_defaults.py`` checks the deployment's defaults. The answer editor is off
    here too (it adds a model call after web search); ``tests/ai/test_answer_editor.py`` turns it on."""
    from forliosa.config import get_settings

    monkeypatch.setenv("AI_DAILY_MESSAGE_LIMIT", "50")
    monkeypatch.setenv("AI_DEEP_SEARCH_COST", "5")
    monkeypatch.setenv("AI_MONTHLY_COST_BUDGET_USD", "0")
    monkeypatch.setenv("AI_MEMBER_DAILY_MESSAGE_LIMIT", "50")
    monkeypatch.setenv("AI_MEMBER_MONTHLY_COST_BUDGET_USD", "0")
    # The briefing is a members' feature (``forliosa.plans``; 深度搜尋 is every account's by default, members only with
    # AI_FREE_DEEP_SEARCH=false); tests about them run as any account. tests/ai/test_plans.py checks the defaults.
    monkeypatch.setenv("AI_FREE_DEEP_SEARCH", "true")
    monkeypatch.setenv("AI_FREE_DAILY_BRIEFING", "true")
    # the answer editor (one more model call after web search) has its own tests: tests/ai/test_answer_editor.py
    monkeypatch.setenv("AI_ANSWER_EDITOR", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def fresh_process_caches():
    """The in-process read caches (``forliosa.perfcache``: related stocks' company pool, admin row counts) start empty
    in every test: each test has its own database."""
    from forliosa import perfcache

    perfcache.clear_all()
    yield
    perfcache.clear_all()


@pytest.fixture(autouse=True)
def builtin_calendar():
    """Tests that archive TWSE's holiday schedule must not leak the official calendar into other tests (nor the NYSE
    holidays a market-report test loads)."""
    from forliosa.timeutil import set_official_holidays, set_us_calendar

    yield
    set_official_holidays([], [])
    set_us_calendar([])


@pytest.fixture(scope="session")
def market() -> MarketData:
    md = MarketData([DemoProvider()], policy="personal")  # offline demo data (explicit opt-in)
    set_market_data(md)
    return md


@pytest.fixture()
def engine(tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(eng)
    set_engine(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def app(engine, market):
    from forliosa.api.app import create_app

    return create_app()


@pytest.fixture()
def client(app) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/v1/auth/dev-login", json={"email": "demo@forliosa.local", "display_name": "示範使用者"})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture()
def other_client(app) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/v1/auth/dev-login", json={"email": "other@forliosa.local", "display_name": "別人"})
    assert r.status_code == 200, r.text
    return c
