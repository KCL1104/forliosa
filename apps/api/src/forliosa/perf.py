"""Slow-request log (2026-11-17 API 速度): Railway shows no per-request timings, so the API writes its own.

One ``slow_request`` line (logger ``forliosa.perf``, INFO) for every request slower than ``SLOW_REQUEST_MS`` (default
800; 0 logs every request)::

    slow_request method=GET route=/api/v1/portfolio/summary status=200 ms=1234 ttfb_ms=1230 queries=131 sql_ms=210
    checkouts=70 inflight=14

* ``route`` is the route **template** (``/api/v1/groups/{group_id}/members/{user_id}/shared``), ``unmatched`` without
  one. Never the real path, the query string, a header, a body or any id / symbol value.
* ``ms``: until the last body chunk; ``ttfb_ms``: until the response headers. A server-sent event stream
  (``text/event-stream``: AI chat, quote stream) is judged by ``ttfb_ms`` only — a long stream is not a slow request.
* ``queries`` / ``sql_ms`` / ``checkouts``: SQL statements, their time and pool check-outs of this request, on every
  engine made by :func:`forliosa.db.make_engine` (the request pool and the archive's own pool). Work a request starts on
  a thread of its own (``threading.Thread``: the AI why / analyst generation) is not counted: it does not inherit the
  request's context. The threadpool that runs sync endpoints copies the context, so its queries are counted.
* ``inflight``: requests this process was serving when this one ended (queueing for the GIL or the pool vs one slow
  endpoint).

Every ``SUMMARY_SECONDS`` one ``request_summary`` line per route template seen (count, p50, p95, max), so the
distribution is visible, not only the slow tail. A full garbage collection (generation 2) longer than
``GC_PAUSE_LOG_MS`` writes ``gc_pause gen=2 ms=…`` (process-wide, every request in flight waits for it).
"""

from __future__ import annotations

import gc
import logging
import os
import threading
import time
import weakref
from contextvars import ContextVar
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("forliosa.perf")

DEFAULT_SLOW_MS = 800.0
SUMMARY_SECONDS = 15 * 60
GC_PAUSE_LOG_MS = 100.0


class RequestStats:
    """Counters of one request (a mutable object in a ContextVar: threads that copied the context share it)."""

    __slots__ = ("checkouts", "queries", "sql_ms")

    def __init__(self) -> None:
        self.queries = 0
        self.sql_ms = 0.0
        self.checkouts = 0


_current: ContextVar[RequestStats | None] = ContextVar("forliosa_request_stats", default=None)
_inflight = 0
_inflight_lock = threading.Lock()


def current_stats() -> RequestStats | None:
    return _current.get()


# -- SQL counters ------------------------------------------------------------------------------------------------
_instrumented: weakref.WeakSet = weakref.WeakSet()


def instrument_engine(engine: Any) -> None:
    """Count statements, their time and pool check-outs into the running request's stats (no-op outside one)."""
    from sqlalchemy import event

    if engine in _instrumented:
        return
    _instrumented.add(engine)

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        if _current.get() is not None:
            conn.info.setdefault("forliosa_perf_t", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        stats = _current.get()
        if stats is None:
            return
        started = conn.info.get("forliosa_perf_t")
        stats.queries += 1
        if started:
            stats.sql_ms += (time.perf_counter() - started.pop()) * 1000

    @event.listens_for(engine, "handle_error")
    def _error(ctx):  # a failed statement never reaches after_cursor_execute: drop its start time
        conn = ctx.connection
        if conn is not None and conn.info.get("forliosa_perf_t"):
            conn.info["forliosa_perf_t"].pop()

    @event.listens_for(engine.pool, "checkout")
    def _checkout(dbapi_conn, record, proxy):
        stats = _current.get()
        if stats is not None:
            stats.checkouts += 1


# -- the middleware ----------------------------------------------------------------------------------------------
def slow_threshold_ms() -> float:
    raw = os.environ.get("SLOW_REQUEST_MS", "").strip()
    try:
        return float(raw) if raw else DEFAULT_SLOW_MS
    except ValueError:
        return DEFAULT_SLOW_MS


def route_template(scope: Scope, prefix: str = "") -> str:
    """The matched route's template; a router included under ``prefix`` keeps its own path on the route object, so
    the prefix is put back when the request's path has it."""
    route = scope.get("route")
    path = getattr(route, "path_format", None) or getattr(route, "path", None)
    if not isinstance(path, str) or not path:
        return "unmatched"
    if prefix and not path.startswith(prefix) and str(scope.get("path", "")).startswith(prefix):
        path = prefix + path
    return path


class _Summary:
    """Per route template: durations since the last summary line (bounded: templates are a fixed set)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.since = time.monotonic()
        self.by_route: dict[str, list[float]] = {}

    def add(self, key: str, ms: float) -> None:
        with self.lock:
            self.by_route.setdefault(key, []).append(ms)
            if time.monotonic() - self.since < SUMMARY_SECONDS:
                return
            rows, self.by_route, self.since = self.by_route, {}, time.monotonic()
        for k, xs in sorted(rows.items()):
            xs.sort()
            log.info("request_summary %s count=%d p50=%.0f p95=%.0f max=%.0f", k, len(xs), _pct(xs, 0.5),
                     _pct(xs, 0.95), xs[-1])


def _pct(xs: list[float], p: float) -> float:
    k = (len(xs) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


class SlowRequestMiddleware:
    """Pure ASGI (no ``BaseHTTPMiddleware``: server-sent events stream through untouched); outermost, so CORS and the
    other middleware's time is in ``ms``."""

    def __init__(self, app: ASGIApp, threshold_ms: float | None = None, prefix: str = ""):
        self.app = app
        self.threshold_ms = slow_threshold_ms() if threshold_ms is None else threshold_ms
        self.prefix = prefix
        self.summary = _Summary()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        global _inflight
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        stats = RequestStats()
        token = _current.set(stats)
        started = time.perf_counter()
        meta: dict[str, Any] = {"status": 0, "ttfb": None, "sse": False}

        async def send_timed(message: Message) -> None:
            if message["type"] == "http.response.start":
                meta["status"] = message.get("status", 0)
                meta["ttfb"] = time.perf_counter()
                ctype = next((v for k, v in message.get("headers", []) if k.lower() == b"content-type"), b"")
                meta["sse"] = ctype.startswith(b"text/event-stream")
            await send(message)

        with _inflight_lock:
            _inflight += 1
        try:
            await self.app(scope, receive, send_timed)
        finally:
            with _inflight_lock:
                _inflight -= 1
                inflight = _inflight + 1  # this request included
            _current.reset(token)
            ended = time.perf_counter()
            ms = (ended - started) * 1000
            ttfb_ms = ((meta["ttfb"] or ended) - started) * 1000
            judged = ttfb_ms if meta["sse"] else ms
            key = f"method={scope.get('method', '?')} route={route_template(scope, self.prefix)}"
            self.summary.add(key, judged)
            if judged >= self.threshold_ms:
                log.info("slow_request %s status=%s ms=%.0f ttfb_ms=%.0f queries=%d sql_ms=%.0f checkouts=%d "
                         "inflight=%d", key, meta["status"], ms, ttfb_ms, stats.queries, stats.sql_ms,
                         stats.checkouts, inflight)


# -- garbage collector pauses -------------------------------------------------------------------------------------
_gc_installed = False
_gc_started: dict[int, float] = {}


def _gc_callback(phase: str, info: dict[str, Any]) -> None:
    if info.get("generation") != 2:
        return
    tid = threading.get_ident()
    if phase == "start":
        _gc_started[tid] = time.perf_counter()
        return
    t0 = _gc_started.pop(tid, None)
    if t0 is None:
        return
    ms = (time.perf_counter() - t0) * 1000
    if ms >= GC_PAUSE_LOG_MS:
        log.info("gc_pause gen=2 ms=%.0f collected=%s", ms, info.get("collected"))


def install_gc_log() -> None:
    global _gc_installed
    if not _gc_installed:
        gc.callbacks.append(_gc_callback)
        _gc_installed = True


def freeze_heap() -> None:
    """Move every object alive now (imports, the app, the instrument master) out of the collector's reach: a full
    collection then scans only what requests allocate (2026-11-17: 250–490 ms pauses with ~390k long-lived objects,
    16–80 ms frozen). Collected first, so no cyclic garbage is frozen; frozen objects are still freed by reference
    counting, but a frozen object that later joins a reference cycle (a request in flight at this moment) is never
    collected. So the API calls this once, at start-up (``api.app.warm_up_in_background``); an earlier freeze is undone
    first, so calling it again never keeps what the previous one pinned."""
    gc.unfreeze()
    gc.collect()
    gc.freeze()
