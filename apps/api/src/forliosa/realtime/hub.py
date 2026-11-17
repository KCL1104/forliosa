"""The API process's fan-out of committed events to open ``GET /api/v1/events`` streams.

Runs on the server's event loop (everything here is touched from that loop only; other threads use
:meth:`Hub.publish_threadsafe`). Events arrive with concrete audiences (``u:<id>``, ``all``, ``admins``: resolved in the
writing transaction by ``realtime.capture``), so delivery is a lookup, and a replay after a reconnect is exactly as
precise as live delivery.

* Ids: ``<boot>.<16 hex digits>``; ``boot`` changes with every process start. Inside, ``seq`` counts every event in
  arrival (= commit) order, whoever it is for; on the wire it is encrypted with a key of this process start (a keyed
  64-bit permutation, :class:`OpaqueIds`), so the ids one user sees say nothing about how many events other users
  caused, or when (2026-11-17 review).
* Ring buffer: the last ``REALTIME_REPLAY_EVENTS`` events and at most ``REALTIME_REPLAY_SECONDS`` old. A reconnect with
  ``last`` from this boot, still in the buffer and after the last gap, replays what it missed (``hello.replay =
  "replayed"``); otherwise the browser is told to refetch what it shows (``"resync"``). A page's first stream (no
  ``last``) gets the events of the last ``FIRST_REPLAY_SECONDS`` that reach it: the page's first requests may have read
  the database just before a change whose event arrived before the stream was registered.
* Per connection: a bounded queue (overflow → one ``resync``), coalescing of identical events, a heartbeat comment,
  a lifetime (``bye{rotate}``), a session re-check every few minutes (``bye{unauthorized}``).
* Limits: streams per user (the oldest gets ``bye{replaced}``), streams in total (503), connects per user per minute
  (429).
* Shutdown (SIGTERM, a deploy): :meth:`Hub.shutdown` is called from the signal (``api.app``), before uvicorn waits for
  open connections, so every stream ends with ``bye{rotate}`` at once and the graceful wait is only for normal
  requests.
* ``market.closes`` first clears the API's own 30-second quote cache and the market-page movers cache, so the
  browser's refetch already sees the new close.

Logging: counts only. Never payloads, user ids or session keys.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import random
import secrets
import string
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from forliosa.realtime.events import ADMINS, ALL, Event, wire_data

log = logging.getLogger(__name__)

QUEUE_MAX = 256
RECHECK_SECONDS = 300.0  # how often an open stream re-checks its login session
STATS_SECONDS = 600.0
DOWN_GRACE_SECONDS = 60.0  # LISTEN down longer than this: open streams are closed so the pages poll instead
WATCH_SECONDS = 5.0
RETRY_MS = 5000
FIRST_REPLAY_SECONDS = 10.0  # a first stream (no ``last``) gets the events this recent that reach it
SHUTDOWN_RETRY_AFTER = 5  # seconds: a stream asked for while this process shuts down
_B36 = string.digits + string.ascii_lowercase
_MASK32 = 0xFFFFFFFF


class OpaqueIds:
    """Event ids without the global counter in clear: ``seq`` through a 4-round Feistel network on 64 bits whose round
    function is keyed BLAKE2b (a key per process start). Invertible, so a ``last`` id comes back as its ``seq``; an id
    that was never issued decodes to a number that is almost surely out of range (→ ``resync``)."""

    ROUNDS = 4

    def __init__(self, key: bytes | None = None):
        self.key = key or secrets.token_bytes(32)

    def _f(self, i: int, half: int) -> int:
        h = hashlib.blake2b(bytes([i]) + half.to_bytes(4, "big"), key=self.key, digest_size=4).digest()
        return int.from_bytes(h, "big")

    def encode(self, seq: int) -> str:
        left, right = (seq >> 32) & _MASK32, seq & _MASK32
        for i in range(self.ROUNDS):
            left, right = right, left ^ self._f(i, right)
        return f"{(left << 32) | right:016x}"

    def decode(self, token: str) -> int | None:
        if len(token) != 16 or any(c not in "0123456789abcdef" for c in token):
            return None
        n = int(token, 16)
        left, right = n >> 32, n & _MASK32
        for i in reversed(range(self.ROUNDS)):
            left, right = right ^ self._f(i, left), left
        return (left << 32) | right


@dataclass
class HubConfig:
    max_streams_per_user: int = 6
    max_streams: int = 2000
    heartbeat_seconds: float = 20.0
    stream_max_seconds: float = 600.0
    replay_events: int = 4096
    replay_seconds: float = 300.0
    connects_per_minute: int = 30
    recheck_seconds: float = RECHECK_SECONDS
    first_replay_seconds: float = FIRST_REPLAY_SECONDS

    @classmethod
    def from_settings(cls, s: Any) -> HubConfig:
        return cls(max_streams_per_user=s.realtime_max_streams_per_user, max_streams=s.realtime_max_streams,
                   heartbeat_seconds=s.realtime_heartbeat_seconds, stream_max_seconds=s.realtime_stream_max_seconds,
                   replay_events=s.realtime_replay_events, replay_seconds=s.realtime_replay_seconds,
                   connects_per_minute=s.realtime_connects_per_minute)


class Refused(Exception):
    """A stream that may not open now: ``status`` 429 / 503, ``code``, ``retry_after`` seconds."""

    def __init__(self, status: int, code: str, retry_after: int):
        super().__init__(code)
        self.status, self.code, self.retry_after = status, code, retry_after


def sse(eid: str | None, topic: str, data: dict[str, Any]) -> str:
    head = f"id: {eid}\n" if eid else ""
    return f"{head}event: {topic}\ndata: {json.dumps(data, separators=(',', ':'), ensure_ascii=False)}\n\n"


class Conn:
    _next = 0

    def __init__(self, user_id: str, session_key: str, is_admin: bool, opened_at: float, deadline: float):
        Conn._next += 1
        self.id = Conn._next
        self.user_id = user_id
        self.session_key = session_key
        self.is_admin = is_admin
        self.opened_at = opened_at
        self.deadline = deadline
        self.items: deque[tuple[str | None, str, dict[str, Any]]] = deque()
        self.wake = asyncio.Event()
        self.bye: str | None = None
        self.overflow = False

    def push(self, eid: str | None, topic: str, data: dict[str, Any]) -> None:
        if self.bye is not None:
            return
        if len(self.items) >= QUEUE_MAX:  # a stuck reader: forget the backlog, tell it to refetch everything
            self.items.clear()
            self.overflow = True
        else:
            self.items.append((eid, topic, data))
        self.wake.set()

    def close(self, reason: str) -> None:
        if self.bye is None:
            self.bye = reason
            self.wake.set()


class Hub:
    def __init__(self, config: HubConfig | None = None, *, postgres_url: str | None = None,
                 session_check: Callable[[str], bool] | None = None):
        self.config = config or HubConfig()
        self.boot = "".join(secrets.choice(_B36) for _ in range(6))
        self.ids = OpaqueIds()
        self.seq = 0
        self.min_replay = 0  # replays from before a gap (lost notifications) are refused
        self.ring: deque[tuple[int, float, Event | None]] = deque(maxlen=max(1, self.config.replay_events))
        self.conns: set[Conn] = set()
        self.by_user: dict[str, list[Conn]] = {}
        self.connects: dict[str, deque[float]] = {}
        self.loop: asyncio.AbstractEventLoop | None = None
        self.postgres_url = postgres_url
        self.session_check = session_check
        self._listening = postgres_url is None  # SQLite: in-process delivery is always "listening"
        self.down_since: float | None = None if self._listening else time.monotonic()
        self._tasks: list[asyncio.Task] = []
        self.delivered = 0
        self.closing = False  # the process is shutting down: streams end, new ones are refused

    # -- lifecycle ------------------------------------------------------------------------------------------------
    async def start(self) -> None:
        from forliosa.realtime import bus

        self.loop = asyncio.get_running_loop()
        if self.postgres_url:
            from forliosa.realtime.pg import listen

            self._tasks.append(asyncio.create_task(listen(self, self.postgres_url), name="realtime-listen"))
        else:
            bus.add_sink(self.publish_threadsafe)
        self._tasks.append(asyncio.create_task(self._stats(), name="realtime-stats"))
        self._tasks.append(asyncio.create_task(self._watch(), name="realtime-watch"))
        log.info("realtime: hub started (%s)", "postgres listen" if self.postgres_url else "in-process")

    def shutdown(self) -> None:
        """The process is about to stop (SIGTERM): every stream ends now with ``bye{rotate}`` (the browsers reconnect,
        to the new process), and no new one opens. Idempotent; called on the event loop."""
        self.closing = True
        for conn in list(self.conns):
            conn.close("rotate")

    async def stop(self) -> None:
        from forliosa.realtime import bus

        bus.remove_sink(self.publish_threadsafe)
        self.shutdown()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()

    # -- ingest ---------------------------------------------------------------------------------------------------
    def publish_threadsafe(self, events: list[Event]) -> None:
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        with contextlib.suppress(RuntimeError):  # the loop is shutting down
            loop.call_soon_threadsafe(self.ingest, events)

    def ingest(self, events: list[Event]) -> None:
        for ev in events:
            try:
                self._ingest_one(ev)
            except Exception as exc:  # one bad event must not stop the others
                log.warning("realtime: delivering an event failed (%s)", type(exc).__name__)

    def _ingest_one(self, ev: Event) -> None:
        if ev.is_op:
            self._op(ev)
            return
        if ev.topic == "market.closes":
            self._forget_market_caches()
        self.seq += 1
        now = time.monotonic()
        self.ring.append((self.seq, now, ev))
        self._prune(now)
        eid = self.eid(self.seq)
        for conn in self._targets(ev):
            self._deliver(conn, eid, ev)

    def _deliver(self, conn: Conn, eid: str | None, ev: Event) -> None:
        data = wire_data(ev)
        if ev.echo and ev.o and ev.ou == conn.user_id:
            data["o"] = ev.o  # only the origin user learns which of their tabs made the change
        conn.push(eid, ev.topic, data)
        self.delivered += 1

    def _targets(self, ev: Event) -> list[Conn]:
        if ALL in ev.to:
            return list(self.conns)
        out: dict[int, Conn] = {}
        for a in ev.to:
            if a.startswith("u:"):
                for c in self.by_user.get(a[2:], ()):
                    out[c.id] = c
            elif a == ADMINS:
                for c in self.conns:
                    if c.is_admin:
                        out[c.id] = c
        return list(out.values())

    def _op(self, ev: Event) -> None:
        if ev.topic == "_session.gone":
            key = ev.data.get("s")
            for c in [c for c in self.conns if key and c.session_key == key]:
                c.close("unauthorized")
        elif ev.topic == "_user.gone":
            for c in list(self.by_user.get(ev.data.get("u") or "", ())):
                c.close("unauthorized")

    def _prune(self, now: float) -> None:
        horizon = now - self.config.replay_seconds
        while self.ring and self.ring[0][1] < horizon:
            self.ring.popleft()

    def _forget_market_caches(self) -> None:
        try:
            from forliosa.marketdata.service import get_market_data
            from forliosa.services import market_overview

            get_market_data().forget_quotes()
            market_overview.clear_cache()
        except Exception as exc:
            log.warning("realtime: clearing market caches failed (%s)", type(exc).__name__)

    def resync_all(self) -> None:
        """Notifications may have been lost (the listener reconnected): everyone refetches, and no replay may cross
        this point. The resync gets an id so a browser that reconnects later replays from here."""
        self.seq += 1
        self.min_replay = self.seq
        self.ring.append((self.seq, time.monotonic(), None))
        eid = self.eid(self.seq)
        for conn in list(self.conns):
            conn.push(eid, "resync", {})

    @property
    def listening(self) -> bool:
        return self._listening

    @listening.setter
    def listening(self, up: bool) -> None:
        """PostgreSQL LISTEN up or down. While it is down nothing would arrive: new streams are refused (the pages poll)
        and, after :data:`DOWN_GRACE_SECONDS`, open ones are closed too."""
        if up:
            self.down_since = None
        elif self._listening or self.down_since is None:
            self.down_since = time.monotonic()
        self._listening = up

    # -- connections ----------------------------------------------------------------------------------------------
    def admit(self, user_id: str) -> None:
        """Raise :class:`Refused` when a new stream may not open; otherwise count the attempt."""
        if self.closing:
            raise Refused(503, "realtime_busy", SHUTDOWN_RETRY_AFTER)
        if len(self.conns) >= self.config.max_streams:
            raise Refused(503, "realtime_busy", 30)
        if not self._listening:
            raise Refused(503, "realtime_busy", 15)
        now = time.monotonic()
        window = self.connects.setdefault(user_id, deque())
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= self.config.connects_per_minute:
            raise Refused(429, "too_many_streams", max(1, int(window[0] + 60 - now) + 1))
        window.append(now)
        if len(self.connects) > 10_000:  # forget idle users now and then
            for uid in [u for u, w in self.connects.items() if not w or w[-1] <= now - 60]:
                del self.connects[uid]

    def register(self, user_id: str, session_key: str, is_admin: bool, last: str | None) -> tuple[Conn, str]:
        """A new stream at the current position; returns it and the replay mode (``none`` | ``replayed`` | ``resync``).
        A user over the cap loses their oldest stream (``bye{replaced}``)."""
        now = time.monotonic()
        span = self.config.stream_max_seconds
        jitter = min(60.0, span * 0.1)
        conn = Conn(user_id, session_key, is_admin, now, now + span + random.uniform(-jitter, jitter))
        mine = self.by_user.setdefault(user_id, [])
        while len([c for c in mine if c.bye is None]) >= self.config.max_streams_per_user:
            oldest = min((c for c in mine if c.bye is None), key=lambda c: c.opened_at)
            oldest.close("replaced")
        mode = self._replay(conn, last)
        self.conns.add(conn)
        mine.append(conn)
        return conn, mode

    def _replay(self, conn: Conn, last: str | None) -> str:
        if not last:
            return self._replay_recent(conn)
        boot, _, token = last.partition(".")
        after = self.ids.decode(token) if boot == self.boot else None
        if after is None or after > self.seq or after < self.min_replay:
            return "resync"
        if after == self.seq:
            return "replayed"
        if not self.ring or self.ring[0][0] > after + 1:
            return "resync"  # part of what was missed has left the buffer
        missed = [(seq, ev) for seq, _ts, ev in self.ring if seq > after]
        if any(ev is None for _seq, ev in missed):
            return "resync"
        for _seq, ev in missed:
            assert ev is not None
            if self._reaches(ev, conn):
                # without an id: the hello's id (the current position) already covers them
                self._deliver(conn, None, ev)
        return "replayed"

    def _replay_recent(self, conn: Conn) -> str:
        """A page's first stream: the requests that drew the page may have read the database just before a change
        whose event came in before this stream was registered. The events of the last few seconds that reach this
        stream are sent again (usually none; at worst a query is read once more). Mode stays ``none``."""
        horizon = time.monotonic() - self.config.first_replay_seconds
        recent = [ev for _seq, ts, ev in self.ring if ts >= horizon]
        if any(ev is None for ev in recent):
            return "resync"  # notifications may have been lost in that window
        for ev in recent:
            assert ev is not None
            if self._reaches(ev, conn):
                self._deliver(conn, None, ev)
        return "none"

    @staticmethod
    def _reaches(ev: Event, conn: Conn) -> bool:
        return ALL in ev.to or f"u:{conn.user_id}" in ev.to or (ADMINS in ev.to and conn.is_admin)

    def unregister(self, conn: Conn) -> None:
        self.conns.discard(conn)
        mine = self.by_user.get(conn.user_id)
        if mine is not None:
            if conn in mine:
                mine.remove(conn)
            if not mine:
                del self.by_user[conn.user_id]

    def eid(self, seq: int) -> str:
        """The wire id of ``seq`` (opaque: see :class:`OpaqueIds`)."""
        return f"{self.boot}.{self.ids.encode(seq)}"

    @property
    def position(self) -> str:
        return self.eid(self.seq)

    # -- writing a stream ---------------------------------------------------------------------------------------
    async def stream(self, conn: Conn, mode: str, hello_id: str,
                     check: Callable[[], Awaitable[bool]] | None = None) -> AsyncIterator[str]:
        """The body of one ``GET /events`` response."""
        cfg = self.config
        yield f"retry: {RETRY_MS}\n\n" + sse(hello_id, "hello", {
            "v": 1, "boot": self.boot, "heartbeat": int(cfg.heartbeat_seconds), "replay": mode})
        last_write = time.monotonic()
        next_check = time.monotonic() + cfg.recheck_seconds
        while True:
            now = time.monotonic()
            if conn.bye is None and now >= conn.deadline:
                conn.close("rotate")
            if conn.bye is None and check is not None and now >= next_check:
                next_check = now + cfg.recheck_seconds
                if not await check():
                    conn.close("unauthorized")
            chunk = self._drain(conn)
            if chunk:
                yield chunk
                last_write = time.monotonic()
            if conn.bye is not None:
                yield sse(None, "bye", {"reason": conn.bye})
                return
            if time.monotonic() - last_write >= cfg.heartbeat_seconds:
                yield ": ping\n\n"
                last_write = time.monotonic()
            now = time.monotonic()
            wait = min(cfg.heartbeat_seconds - (now - last_write), conn.deadline - now, next_check - now)
            if not conn.items and not conn.overflow:
                conn.wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(conn.wake.wait(), timeout=max(0.01, wait))

    def _drain(self, conn: Conn) -> str:
        if conn.overflow:
            conn.overflow = False
            conn.items.clear()
            return sse(self.position, "resync", {})
        if not conn.items:
            return ""
        items = list(conn.items)
        conn.items.clear()
        # identical events collapse into the last one (ids stay increasing along the chunk)
        last_at: dict[tuple[str, str], int] = {}
        for i, (_eid, topic, data) in enumerate(items):
            last_at[(topic, json.dumps(data, sort_keys=True))] = i
        return "".join(sse(*items[i]) for i in sorted(last_at.values()))

    # -- housekeeping ---------------------------------------------------------------------------------------------
    def check_listener(self, now: float | None = None) -> None:
        if self.down_since is not None and (now or time.monotonic()) - self.down_since >= DOWN_GRACE_SECONDS:
            for conn in list(self.conns):
                conn.close("rotate")

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(WATCH_SECONDS)
            self.check_listener()

    async def _stats(self) -> None:
        while True:
            await asyncio.sleep(STATS_SECONDS)
            log.info("realtime: %d streams of %d users, %d events delivered in the last %d minutes",
                     len(self.conns), len(self.by_user), self.delivered, int(STATS_SECONDS // 60))
            self.delivered = 0
