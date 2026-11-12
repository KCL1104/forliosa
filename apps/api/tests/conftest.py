"""Test fixtures: temp SQLite database, offline market data (demo provider only)."""

from __future__ import annotations

import os

os.environ.setdefault("FORLIOSA_ENV", "test")
os.environ.setdefault("MARKET_DATA_PROVIDERS", "demo")
os.environ.setdefault("DEMO_JITTER", "false")

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
def builtin_calendar():
    """Tests that archive TWSE's holiday schedule must not leak the official calendar into other tests."""
    from forliosa.timeutil import set_official_holidays

    yield
    set_official_holidays([], [])


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
