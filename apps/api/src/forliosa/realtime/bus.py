"""In-process delivery of committed events (SQLite, tests): the hub of this process subscribes here.

On PostgreSQL every committed event travels through NOTIFY instead (also back to the API process that wrote it), so
nothing is published here. Sinks are called from whatever thread committed; they must be thread-safe and quick (the
hub's sink only schedules work on its event loop).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from forliosa.realtime.events import Event

log = logging.getLogger(__name__)

Sink = Callable[[list[Event]], None]
_sinks: list[Sink] = []
_lock = threading.Lock()


def add_sink(sink: Sink) -> None:
    with _lock:
        if sink not in _sinks:
            _sinks.append(sink)


def remove_sink(sink: Sink) -> None:
    with _lock:
        if sink in _sinks:
            _sinks.remove(sink)


def publish_local(events: list[Event]) -> None:
    if not events:
        return
    with _lock:
        sinks = list(_sinks)
    for sink in sinks:
        try:
            sink(list(events))
        except Exception as exc:  # a sink must never break the write that committed
            log.warning("realtime: a local sink failed (%s)", type(exc).__name__)
