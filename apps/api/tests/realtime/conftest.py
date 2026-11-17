"""Fixtures of the realtime tests: a collector of the events this process commits (SQLite: ``realtime.bus``)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from forliosa.realtime import bus
from forliosa.realtime.events import Event


@dataclass
class Collected:
    events: list[Event] = field(default_factory=list)

    def __call__(self, events: list[Event]) -> None:
        self.events.extend(events)

    def clear(self) -> None:
        self.events.clear()

    def topics(self) -> list[str]:
        return [e.topic for e in self.events]

    def find(self, topic: str, **data) -> list[Event]:
        return [e for e in self.events if e.topic == topic and all(e.data.get(k) == v for k, v in data.items())]

    def one(self, topic: str, **data) -> Event:
        found = self.find(topic, **data)
        assert len(found) == 1, (topic, data, [(e.topic, e.data, e.to) for e in self.events])
        return found[0]

    def reaching(self, uid: str) -> list[Event]:
        return [e for e in self.events if f"u:{uid}" in e.to or "all" in e.to]


@pytest.fixture()
def rt():
    c = Collected()
    bus.add_sink(c)
    yield c
    bus.remove_sink(c)
