"""Test fixtures: temp SQLite database, offline market data (demo provider only)."""

from __future__ import annotations

import os

os.environ.setdefault("FORLIOSA_ENV", "test")
os.environ.setdefault("MARKET_DATA_PROVIDERS", "demo")
os.environ.setdefault("DEMO_JITTER", "false")

import pytest
from fastapi.testclient import TestClient

from forliosa.db import Base, make_engine, set_engine
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data


@pytest.fixture(scope="session")
def market() -> MarketData:
    md = MarketData([DemoProvider()])
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
