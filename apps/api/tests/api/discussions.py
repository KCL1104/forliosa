"""Helpers for the discussion API tests: a clock the tests move by hand (rate limits, cooldowns, suspensions)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from forliosa.timeutil import now_utc

API = "/api/v1"
GAP = 11  # seconds: more than the 10-second gap between two public posts
IDENTITY_KEYS = {"user_id", "email", "display_name", "avatar_url"}


class Clock:
    def __init__(self) -> None:
        self.t: datetime = now_utc().replace(microsecond=0)

    def __call__(self) -> datetime:
        return self.t

    def tick(self, **delta: float) -> datetime:
        self.t += timedelta(**delta)
        return self.t


def set_name(client: TestClient, name: str) -> dict:
    r = client.put(f"{API}/users/me/public-name", json={"public_name": name})
    assert r.status_code == 200, r.text
    return r.json()


def post_topic(client: TestClient, clock: Clock, scope: str = "public", **fields: Any) -> dict:
    """A topic, posted ``GAP`` seconds after the previous post."""
    clock.tick(seconds=GAP)
    body = {"scope": scope, "title": "0050 要不要改買 006208？", "body": "想聽聽大家的看法", **fields}
    r = client.post(f"{API}/discussions/topics", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def post_reply(client: TestClient, clock: Clock, topic_id: str, body: str = "我覺得可以") -> dict:
    clock.tick(seconds=GAP)
    r = client.post(f"{API}/discussions/topics/{topic_id}/replies", json={"body": body})
    assert r.status_code == 201, r.text
    return r.json()


def topics(client: TestClient, **params: Any) -> list[dict]:
    r = client.get(f"{API}/discussions/topics", params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def replies(client: TestClient, topic_id: str, **params: Any) -> list[dict]:
    r = client.get(f"{API}/discussions/topics/{topic_id}/replies", params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def error(r) -> str:
    return r.json()["error"]["code"]


def keys_of(value: Any) -> set[str]:
    """Every dict key anywhere in a JSON value."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys_of(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys_of(v)}
    return set()
