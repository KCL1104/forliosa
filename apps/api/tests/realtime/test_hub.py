"""The hub alone (``forliosa.realtime.hub``), on a plain asyncio loop: routing, origin echo, replay, limits, the
stream's frames."""

from __future__ import annotations

import asyncio
import contextlib
import json

import pytest

from forliosa.realtime.events import Event, decode, encode, event, split_for_notify
from forliosa.realtime.hub import QUEUE_MAX, Hub, HubConfig, OpaqueIds, Refused


def run(coro):
    return asyncio.run(coro)


def frames(chunk: str) -> list[dict]:
    """SSE text → [{"id", "event", "data"}] (comments skipped)."""
    out = []
    for block in chunk.strip("\n").split("\n\n"):
        f: dict = {}
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            k, _, v = line.partition(": ")
            f[k] = json.loads(v) if k == "data" else v
        if "event" in f:
            out.append(f)
    return out


def pending(conn) -> list[tuple]:
    return [(eid, topic, data) for eid, topic, data in conn.items]


def ev(topic, data=None, to=("all",), **kw) -> Event:
    e = event(topic, data or {}, to)
    for k, v in kw.items():
        setattr(e, k, v)
    return e


def test_routing_by_audience():
    hub = Hub()
    a, _ = hub.register("usr_a", "sa", False, None)
    b, _ = hub.register("usr_b", "sb", False, None)
    admin, _ = hub.register("usr_c", "sc", True, None)
    hub.ingest([ev("ledger", {"account_id": "acc_1"}, ("u:usr_a",)),
                ev("group.members", {"group_id": "g1"}, ("u:usr_a", "u:usr_b")),
                ev("admin.reports", {}, ("admins",)),
                ev("market.overview")])
    assert [t for _i, t, _d in pending(a)] == ["ledger", "group.members", "market.overview"]
    assert [t for _i, t, _d in pending(b)] == ["group.members", "market.overview"]
    assert [t for _i, t, _d in pending(admin)] == ["admin.reports", "market.overview"]
    ids = [i for i, _t, _d in pending(a)]
    assert ids == [hub.eid(1), hub.eid(2), hub.eid(4)]


def test_origin_tab_only_reaches_the_origin_user():
    hub = Hub()
    mine, _ = hub.register("usr_a", "sa", False, None)
    other, _ = hub.register("usr_b", "sb", False, None)
    hub.ingest([ev("group.comments", {"group_id": "g1", "target": "x"}, ("u:usr_a", "u:usr_b"), ou="usr_a",
                   o="t_abcdefgh"),
                ev("group.ledger", {"group_id": "g1"}, ("u:usr_a", "u:usr_b"), ou="usr_a", o="t_abcdefgh",
                   echo=False)])
    assert [d for _i, _t, d in pending(mine)] == [{"group_id": "g1", "target": "x", "o": "t_abcdefgh"},
                                                  {"group_id": "g1"}]
    assert [d for _i, _t, d in pending(other)] == [{"group_id": "g1", "target": "x"}, {"group_id": "g1"}]


def test_replay_after_a_reconnect():
    hub = Hub()
    first, _ = hub.register("usr_a", "sa", False, None)
    hub.ingest([ev("ledger", {}, ("u:usr_a",))])
    last = pending(first)[-1][0]
    hub.unregister(first)
    hub.ingest([ev("ledger", {"account_id": "acc_2"}, ("u:usr_a",)), ev("watchlist", {}, ("u:usr_b",)),
                ev("market.overview")])
    again, mode = hub.register("usr_a", "sa", False, last)
    assert mode == "replayed"
    assert pending(again) == [(None, "ledger", {"account_id": "acc_2"}), (None, "market.overview", {})]
    up_to_date, mode = hub.register("usr_a", "sa", False, hub.position)
    assert mode == "replayed" and pending(up_to_date) == []
    assert hub.register("usr_a", "sa", False, "zzzzzz.1")[1] == "resync"  # another process start
    assert hub.register("usr_a", "sa", False, f"{hub.boot}.x")[1] == "resync"
    assert hub.register("usr_a", "sa", False, None)[1] == "none"


def test_replay_refused_once_events_left_the_buffer_or_after_a_gap():
    hub = Hub(HubConfig(replay_events=2))
    hub.ingest([ev("market.overview")] * 4)
    assert hub.register("usr_a", "sa", False, hub.eid(1))[1] == "resync"
    assert hub.register("usr_a", "sa", False, hub.eid(2))[1] == "replayed"
    hub = Hub()
    hub.ingest([ev("market.overview")])
    before = hub.position
    conn, _ = hub.register("usr_a", "sa", False, None)
    hub.resync_all()  # the listener reconnected: notifications may be lost
    assert pending(conn)[-1][1:] == ("resync", {})
    assert hub.register("usr_a", "sa", False, before)[1] == "resync"
    assert hub.register("usr_a", "sa", False, hub.position)[1] == "replayed"


def test_ids_do_not_reveal_other_users_events():
    """A user sees only the ids of their own events and of their hellos: with a counter in clear, the gap between two
    of them would tell how many events other users caused, and when (2026-11-17 review)."""
    hub = Hub()
    a, _ = hub.register("usr_a", "sa", False, None)
    hello_1 = hub.position
    hub.ingest([ev("ledger", {}, ("u:usr_b",)), ev("ai.usage", {}, ("u:usr_b",))])  # someone else's private events
    hello_2 = hub.position
    hub.ingest([ev("ledger", {}, ("u:usr_a",))])
    boot, _, token = pending(a)[0][0].partition(".")
    assert boot == hub.boot and len(token) == 16 and token != f"{3:016x}"
    assert hello_1.partition(".")[2] != f"{0:016x}" and hello_2.partition(".")[2] != f"{2:016x}"
    tokens = {hub.eid(n).partition(".")[2] for n in range(1000)}
    assert len(tokens) == 1000  # a permutation …
    in_order = [int(hub.eid(n).partition(".")[2], 16) for n in range(1000)]
    assert sorted(in_order) != in_order  # … that does not keep the order
    assert Hub().eid(5) != hub.eid(5)  # a key per process start
    # the ids still work as ``last``
    hub.unregister(a)
    again, mode = hub.register("usr_a", "sa", False, hello_2)
    assert mode == "replayed" and [t for _i, t, _d in pending(again)] == ["ledger"]


def test_opaque_ids_round_trip():
    ids = OpaqueIds(b"k" * 32)
    for n in (0, 1, 2, 4095, 2**32, 2**63 + 17):
        assert ids.decode(ids.encode(n)) == n
    assert ids.decode("not-hex-at-all!!") is None and ids.decode("abc") is None
    hub = Hub()
    hub.ingest([ev("market.overview")])
    assert hub.register("usr_a", "sa", False, f"{hub.boot}.{'0' * 16}")[1] in ("resync", "replayed")
    assert hub.register("usr_a", "sa", False, f"{hub.boot}.{'f' * 16}")[1] == "resync"  # never issued


def test_a_first_stream_gets_the_last_seconds_of_its_events():
    """The page's first requests may have read the database just before a change whose event came in before the
    stream was registered: a stream without ``last`` gets the recent events that reach it (mode stays ``none``)."""
    hub = Hub(HubConfig(first_replay_seconds=10))
    hub.ingest([ev("group.members", {"group_id": "g1"}, ("u:usr_a",)), ev("ledger", {}, ("u:usr_b",)),
                ev("market.overview")])
    conn, mode = hub.register("usr_a", "sa", False, None)
    assert mode == "none"
    assert pending(conn) == [(None, "group.members", {"group_id": "g1"}), (None, "market.overview", {})]
    old = Hub(HubConfig(first_replay_seconds=0))
    old.ingest([ev("market.overview")])
    later, _ = old.register("usr_a", "sa", False, None)
    assert pending(later) == []  # nothing that recent
    gap = Hub()
    gap.resync_all()  # notifications may have been lost a moment ago
    assert gap.register("usr_a", "sa", False, None)[1] == "resync"


def test_shutdown_ends_every_stream_at_once_and_refuses_new_ones():
    async def go():
        hub = Hub(HubConfig(heartbeat_seconds=30, stream_max_seconds=600))
        conn, mode = hub.register("usr_a", "sa", False, None)
        body = hub.stream(conn, mode, hub.position)
        await anext(body)  # hello
        asyncio.get_running_loop().call_later(0.05, hub.shutdown)
        rest = [c async for c in body]
        with pytest.raises(Refused) as exc:
            hub.admit("usr_b")
        return rest, exc.value

    rest, refused = run(asyncio.wait_for(go(), timeout=5))
    assert frames("".join(rest)) == [{"event": "bye", "data": {"reason": "rotate"}}]
    assert (refused.status, refused.code, refused.retry_after) == (503, "realtime_busy", 5)


def test_queue_overflow_becomes_one_resync():
    hub = Hub()
    conn, _ = hub.register("usr_a", "sa", False, None)
    hub.ingest([ev("market.overview", {}) for _ in range(QUEUE_MAX + 5)])
    assert conn.overflow
    chunk = hub._drain(conn)
    assert [f["event"] for f in frames(chunk)] == ["resync"]


def test_identical_events_coalesce_keeping_the_last_id():
    hub = Hub()
    conn, _ = hub.register("usr_a", "sa", False, None)
    hub.ingest([ev("market.overview"), ev("ledger", {}, ("u:usr_a",)), ev("market.overview")])
    got = frames(hub._drain(conn))
    assert [(f["id"], f["event"]) for f in got] == [(hub.eid(2), "ledger"), (hub.eid(3), "market.overview")]


def test_limits():
    hub = Hub(HubConfig(max_streams_per_user=2, max_streams=4, connects_per_minute=3))
    a1, _ = hub.register("usr_a", "s1", False, None)
    a2, _ = hub.register("usr_a", "s1", False, None)
    a3, _ = hub.register("usr_a", "s1", False, None)
    assert a1.bye == "replaced" and a2.bye is None and a3.bye is None  # the oldest makes room
    for _ in range(3):
        hub.admit("usr_b")
    with pytest.raises(Refused) as exc:
        hub.admit("usr_b")
    assert (exc.value.status, exc.value.code) == (429, "too_many_streams") and exc.value.retry_after >= 1
    hub.register("usr_c", "s3", False, None)
    with pytest.raises(Refused) as exc:
        hub.admit("usr_d")
    assert (exc.value.status, exc.value.code) == (503, "realtime_busy")


def test_logout_and_account_deletion_close_streams():
    hub = Hub()
    a1, _ = hub.register("usr_a", "key1", False, None)
    a2, _ = hub.register("usr_a", "key2", False, None)
    b, _ = hub.register("usr_b", "key3", False, None)
    hub.ingest([event("_session.gone", {"s": "key1"})])
    assert (a1.bye, a2.bye, b.bye) == ("unauthorized", None, None)
    hub.ingest([event("_user.gone", {"u": "usr_b"})])
    assert b.bye == "unauthorized" and a2.bye is None


def test_market_closes_clear_the_quote_caches(monkeypatch):
    calls = []
    from forliosa.services import market_overview

    class FakeMd:
        def forget_quotes(self):
            calls.append("quotes")

    monkeypatch.setattr("forliosa.marketdata.service.get_market_data", lambda: FakeMd())
    monkeypatch.setattr(market_overview, "clear_cache", lambda: calls.append("movers"))
    Hub().ingest([event("market.closes", {"market": "TWSE"}, ("all",))])
    assert calls == ["quotes", "movers"]


def test_the_stream_says_hello_then_events_then_rotates():
    async def go():
        hub = Hub(HubConfig(heartbeat_seconds=0.05, stream_max_seconds=0.3))
        conn, mode = hub.register("usr_a", "sa", False, None)
        body = hub.stream(conn, mode, hub.position)
        chunks = [await anext(body)]
        hub.ingest([ev("ledger", {"account_id": "acc_1"}, ("u:usr_a",))])
        async for chunk in body:
            chunks.append(chunk)
        return "".join(chunks)

    text = run(go())
    assert text.startswith("retry: 5000\n\n")
    got = frames(text)
    assert got[0]["event"] == "hello" and got[0]["data"]["replay"] == "none" and got[0]["data"]["v"] == 1
    assert got[1]["event"] == "ledger" and got[1]["data"] == {"account_id": "acc_1"}
    assert got[-1] == {"event": "bye", "data": {"reason": "rotate"}}
    assert ": ping" in text  # heartbeats while idle


def test_a_failed_session_check_ends_the_stream():
    async def go():
        hub = Hub(HubConfig(heartbeat_seconds=5, stream_max_seconds=60, recheck_seconds=0.05))
        conn, mode = hub.register("usr_a", "sa", False, None)

        async def check():
            return False

        return [c async for c in hub.stream(conn, mode, hub.position, check)]

    got = frames("".join(run(go())))
    assert got[-1] == {"event": "bye", "data": {"reason": "unauthorized"}}


def test_publish_from_another_thread():
    async def go():
        hub = Hub()
        await hub.start()
        try:
            conn, _ = hub.register("usr_a", "sa", False, None)
            await asyncio.to_thread(hub.publish_threadsafe, [ev("market.overview")])
            for _ in range(50):
                if conn.items:
                    break
                await asyncio.sleep(0.01)
            return pending(conn)
        finally:
            await hub.stop()

    assert [t for _i, t, _d in run(go())] == ["market.overview"]


def test_notify_encoding_round_trip_and_split():
    e = Event("group.members", {"group_id": "g1"}, tuple(f"u:usr_{i:026d}" for i in range(400)), False, "usr_a",
              "t_abcdefgh")
    back = decode(encode(e))
    assert back == e
    parts = split_for_notify(e)
    assert len(parts) > 1 and all(len(p.encode()) <= 7000 for p in parts)
    assert sorted(a for p in parts for a in decode(p).to) == sorted(e.to)
    assert decode('{"t": "no.such"}') is None and decode("not json") is None


def test_while_listen_is_down_pages_poll_instead():
    import time

    from forliosa.realtime.hub import DOWN_GRACE_SECONDS

    hub = Hub(postgres_url="postgresql://example/db")  # not connected yet
    with pytest.raises(Refused) as exc:
        hub.admit("usr_a")
    assert (exc.value.status, exc.value.code, exc.value.retry_after) == (503, "realtime_busy", 15)
    hub.listening = True
    hub.admit("usr_a")
    conn, _ = hub.register("usr_a", "sa", False, None)
    hub.listening = False  # lost: a short outage keeps the streams …
    hub.check_listener()
    assert conn.bye is None
    hub.check_listener(time.monotonic() + DOWN_GRACE_SECONDS + 1)  # … a long one sends them to polling
    assert conn.bye == "rotate"
    hub.listening = True
    assert hub.down_since is None


def test_a_silent_listen_connection_counts_as_lost(monkeypatch):
    """A LISTEN connection that stops answering without closing (a proxy that stops forwarding, a partition): the idle
    probe times out, the hub stops counting as listening (new streams are refused, the pages poll), and the listener
    reconnects and tells everyone to refetch (2026-11-17 review)."""
    import psycopg

    from forliosa.realtime import pg

    monkeypatch.setattr(pg, "IDLE_SECONDS", 0.02)
    monkeypatch.setattr(pg, "PROBE_TIMEOUT", 0.05)
    monkeypatch.setattr(pg, "BACKOFF_FIRST", 0.01)
    connects: list[dict] = []
    probes = {"n": 0}

    class Frozen:
        """The first connection answers LISTEN and one probe, then never again; later ones are healthy."""

        def __init__(self, healthy: bool):
            self.healthy = healthy
            self.closed = False

        async def execute(self, sql):
            if sql == "SELECT 1":
                probes["n"] += 1
                if not self.healthy and probes["n"] > 1:
                    await asyncio.Event().wait()  # no answer, ever
            return None

        def notifies(self, timeout):
            async def gen():
                await asyncio.sleep(timeout)
                return
                yield  # pragma: no cover - an async generator without notifications

            return gen()

        async def close(self):
            self.closed = True

    async def connect(conninfo, **kw):
        connects.append(kw)
        return Frozen(healthy=len(connects) > 1)

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", staticmethod(connect))

    async def go():
        hub = Hub(postgres_url="postgresql://example/db")
        conn, _ = hub.register("usr_a", "sa", False, None)
        seen_down = False
        task = asyncio.create_task(pg.listen(hub, "postgresql://example/db"))
        try:
            for _ in range(400):
                await asyncio.sleep(0.005)
                seen_down = seen_down or (len(connects) == 1 and probes["n"] > 1 and not hub.listening)
                if len(connects) >= 2 and hub.listening and any(t == "resync" for _i, t, _d in conn.items):
                    break
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        return hub, conn, seen_down

    hub, conn, seen_down = run(go())
    assert seen_down  # the frozen connection stopped counting as listening …
    assert len(connects) >= 2 and hub.listening  # … and was replaced
    assert [t for _i, t, _d in pending(conn)][-1] == "resync"
    kw = connects[0]
    assert kw["keepalives"] == 1 and kw["keepalives_interval"] == 10 and kw["keepalives_count"] == 3
    assert kw["tcp_user_timeout"] == 20_000
