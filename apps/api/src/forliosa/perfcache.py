"""Small in-process caches of read paths (2026-11-17 API 速度) and the switch that empties them all.

The API runs one process; each cache here keeps a few derived values for a short time and is keyed so that the data
they come from changing makes a new key (``archive_version``: any archive run, the worker included, writes
``dataset_status``). Tests and the benchmark start from :func:`clear_all`. Caches on a ``MarketData`` instance (quotes,
the instrument master, the archive's start, the notices status) go with that instance instead.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Hashable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

_MISSING = object()


class TtlCache:
    """``key -> value`` for ``ttl`` seconds, at most ``maxsize`` entries (the oldest go first)."""

    def __init__(self, name: str, ttl: float, maxsize: int = 256):
        self.name = name
        self.ttl = ttl
        self.maxsize = maxsize
        self._lock = threading.Lock()
        self._items: dict[Hashable, tuple[float, Any]] = {}
        _registry.append(self)

    def get(self, key: Hashable) -> Any:
        with self._lock:
            hit = self._items.get(key)
            if hit is None:
                return _MISSING
            if time.monotonic() >= hit[0]:
                del self._items[key]
                return _MISSING
            return hit[1]

    def put(self, key: Hashable, value: Any) -> None:
        with self._lock:
            self._items.pop(key, None)
            while len(self._items) >= self.maxsize:
                self._items.pop(next(iter(self._items)))
            self._items[key] = (time.monotonic() + self.ttl, value)

    def get_or_compute(self, key: Hashable, compute: Callable[[], Any]) -> Any:
        value = self.get(key)
        if value is _MISSING:
            value = compute()
            self.put(key, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


_registry: list[TtlCache] = []


def clear_all() -> None:
    for cache in _registry:
        cache.clear()


def archive_version(db: Session) -> tuple:
    """Changes whenever the archive stores something: every archive job (official closes, the same-day and evening
    closes, US closes, company profiles …) upserts its ``dataset_status`` row with the time it ran."""
    from forliosa.models import DatasetStatus

    newest, rows = db.execute(select(func.max(DatasetStatus.fetched_at), func.count()).select_from(DatasetStatus)).one()
    return (newest, rows)
