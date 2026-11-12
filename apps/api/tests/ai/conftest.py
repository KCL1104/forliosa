"""AI test fixtures: a fake Messages API, a key pool of fake clients, AI settings overrides, SSE parsing."""

from __future__ import annotations

import json

import pytest

from forliosa.ai.keypool import KeyPool, set_key_pool
from forliosa.config import get_settings
from tests.ai.fake_anthropic import FakeAnthropic

API = "/api/v1"
KEYS = ["sk-test-key-one", "sk-test-key-two"]


@pytest.fixture()
def fake() -> FakeAnthropic:
    return FakeAnthropic()


@pytest.fixture()
def pool(fake):
    p = KeyPool.from_keys(KEYS, client_factory=fake.client, sleep=lambda _s: None)
    set_key_pool(p)
    yield p
    set_key_pool(None)


@pytest.fixture()
def ai_env(monkeypatch):
    """Override AI settings for one test: ``ai_env(AI_DAILY_MESSAGE_LIMIT=1)``."""

    def apply(**values):
        for k, v in values.items():
            monkeypatch.setenv(k.upper(), str(v))
        get_settings.cache_clear()

    yield apply
    monkeypatch.undo()
    get_settings.cache_clear()


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    events = []
    for chunk in raw.strip().split("\n\n"):
        name, data = None, None
        for line in chunk.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name:
            events.append((name, data))
    return events


def chat(client, message: str, **body) -> tuple[int, list[tuple[str, dict]] | dict]:
    payload = {"message": message, "page": body.pop("page", {"route": "/"}), **body}
    with client.stream("POST", f"{API}/ai/chat", json=payload) as r:
        raw = r.read().decode()
        if r.status_code != 200:
            return r.status_code, json.loads(raw)
        assert r.headers["content-type"].startswith("text/event-stream")
        return r.status_code, parse_sse(raw)


def make_account(client, name="永豐") -> str:
    r = client.post(f"{API}/accounts", json={"name": name, "currency": "TWD", "fee_discount": 0.28})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def buy(client, account_id: str, symbol: str = "2330", quantity: int = 1000, price: float = 600,
        trade_date: str = "2026-01-05") -> dict:
    r = client.post(f"{API}/transactions", json={"account_id": account_id, "symbol": symbol, "type": "buy",
                                                 "trade_date": trade_date, "quantity": quantity, "price": price})
    assert r.status_code == 201, r.text
    return r.json()
