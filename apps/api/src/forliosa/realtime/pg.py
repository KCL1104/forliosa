"""PostgreSQL ``LISTEN`` for the hub: one connection of its own (outside the SQLAlchemy pool), autocommit.

Notifications are delivered in commit order. While the connection is down nothing is queued for us, so after every
reconnect the hub tells every open stream to refetch (``resync``).

A connection that dies without a word (the database moved, a network partition, a proxy that stops forwarding but keeps
the socket open) must not leave the hub "listening" while nothing arrives — the pages would stop polling and miss every
change. So an idle connection is probed with ``SELECT 1`` every ``IDLE_SECONDS``, and a probe without an answer within
``PROBE_TIMEOUT`` counts as a lost connection (close, ``listening = False``, back off, reconnect, ``resync``). The
socket also has TCP keepalives (``KEEPALIVE``) and ``tcp_user_timeout``, so a dead peer fails the socket itself within
about a minute even while the probe's own wait is running.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from forliosa.realtime.events import CHANNEL, decode

if TYPE_CHECKING:
    from forliosa.realtime.hub import Hub

log = logging.getLogger(__name__)

IDLE_SECONDS = 25.0
PROBE_TIMEOUT = 10.0  # seconds for the idle probe's answer; longer: the connection is treated as lost
# libpq: first keepalive after 30 s idle, then every 10 s, dead after 3 unanswered; unacknowledged data for 20 s
# (a query sent into a dead connection) fails the socket too.
KEEPALIVE = {"keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3,
             "tcp_user_timeout": 20_000}
APPLICATION_NAME = "forliosa-realtime"  # how the connection shows in pg_stat_activity
BACKOFF_FIRST = 1.0
BACKOFF_MAX = 30.0


def conninfo(database_url: str) -> str:
    """SQLAlchemy's ``postgresql+psycopg://…`` → the libpq URL psycopg connects with."""
    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://", "postgres://"):
        if database_url.startswith(prefix):
            return "postgresql://" + database_url[len(prefix):]
    return database_url


async def listen(hub: Hub, database_url: str) -> None:
    import psycopg

    delay = BACKOFF_FIRST
    first = True
    while True:
        try:
            conn = await psycopg.AsyncConnection.connect(conninfo(database_url), autocommit=True, connect_timeout=10,
                                                         application_name=APPLICATION_NAME, **KEEPALIVE)
        except Exception as exc:
            hub.listening = False
            log.warning("realtime: LISTEN connection failed (%s); retrying in %.0f s", type(exc).__name__, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, BACKOFF_MAX)
            continue
        try:
            await probe(conn, f"LISTEN {CHANNEL}")
            hub.listening = True
            if not first:
                log.info("realtime: LISTEN reconnected")
                hub.resync_all()  # whatever was committed while we were away is unknown
            first = False
            delay = BACKOFF_FIRST
            while True:
                async for note in conn.notifies(timeout=IDLE_SECONDS):
                    ev = decode(note.payload)
                    if ev is not None:
                        hub.ingest([ev])
                await probe(conn)
        except asyncio.CancelledError:
            await _close(conn)
            raise
        except Exception as exc:
            hub.listening = False
            log.warning("realtime: LISTEN connection lost (%s); reconnecting in %.0f s", type(exc).__name__, delay)
            await _close(conn)
            await asyncio.sleep(delay)
            delay = min(delay * 2, BACKOFF_MAX)


class ProbeTimeout(Exception):
    """The idle probe got no answer in time: the connection is gone even if its socket is still open."""


async def probe(conn, sql: str = "SELECT 1") -> None:
    """Run a statement that must answer within ``PROBE_TIMEOUT`` (psycopg's own cancellation of the abandoned
    statement adds at most about 10 s more before this returns)."""
    try:
        await asyncio.wait_for(conn.execute(sql), timeout=PROBE_TIMEOUT)
    except TimeoutError:
        raise ProbeTimeout from None


async def _close(conn) -> None:
    with contextlib.suppress(Exception):
        await conn.close()
