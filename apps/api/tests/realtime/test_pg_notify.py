"""PostgreSQL NOTIFY / LISTEN, the production path (skipped unless ``FORLIOSA_TEST_PG_URL`` names a throwaway database:
every table in it is dropped and created again).

    initdb -D /tmp/pg -U postgres --auth=trust && pg_ctl -D /tmp/pg -o "-p 55432" start   # as a non-root user
    createdb -h 127.0.0.1 -p 55432 -U postgres rt_test
    FORLIOSA_TEST_PG_URL=postgresql+psycopg://postgres@127.0.0.1:55432/rt_test uv run pytest tests/realtime -k pg
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
import time
from datetime import date

import pytest
import uvicorn
from sqlalchemy import text

from forliosa.config import get_settings
from forliosa.db import Base, make_engine, session_factory, set_engine
from forliosa.ids import new_id
from forliosa.models import BrokerAccount, Transaction, User
from tests.realtime.test_events_endpoint import Stream, browser

PG_URL = os.environ.get("FORLIOSA_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="FORLIOSA_TEST_PG_URL not set (a throwaway PostgreSQL database)")
API = "/api/v1"


@pytest.fixture()
def pg_engine(market):
    eng = make_engine(PG_URL)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    set_engine(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def pg_server(pg_engine):
    from forliosa.api.app import create_app

    app = create_app()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on",
                                        timeout_graceful_shutdown=1))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(300):
        if srv.started:
            break
        time.sleep(0.02)
    assert srv.started
    hub = app.state.realtime_hub
    for _ in range(200):  # the LISTEN connection is up
        if hub.listening:
            break
        time.sleep(0.02)
    assert hub.postgres_url and hub.listening
    yield f"http://127.0.0.1:{srv.servers[0].sockets[0].getsockname()[1]}", hub
    srv.should_exit = True
    thread.join(10)


def worker_write(uid: str, account_id: str, rollback: bool = False) -> None:
    """A write from a session that is not a request, like the worker's automatic dividends."""
    with session_factory()() as db:
        db.add(Transaction(id=new_id("txn"), user_id=uid, account_id=account_id, symbol="2330.TW",
                           type="cash_dividend", trade_date=date(2026, 11, 17), amount=1000, source="auto"))
        if rollback:
            db.flush()
            db.rollback()
        else:
            db.commit()


def test_api_and_worker_writes_reach_the_stream_through_notify(pg_server):
    base, _hub = pg_server
    a = browser(base, "demo@forliosa.local", "示範使用者")
    acc = a.post(f"{API}/accounts", json={"name": "永豐", "broker": "", "currency": "TWD", "fee_discount": 0.28}).json()
    uid = a.get(f"{API}/me").json()["id"]
    stream = Stream(base, a.token)
    try:
        stream.next("hello")
        started = time.monotonic()
        r = a.post(f"{API}/transactions", headers={"X-Forliosa-Tab": "t_pgtab1234"},
                   json={"account_id": acc["id"], "symbol": "2330.TW", "type": "buy", "trade_date": "2025-03-04",
                         "quantity": 1000, "price": 600})
        assert r.status_code == 201, r.text
        got = stream.next("ledger", timeout=2.0, live=True)  # not the account's creation, replayed after hello
        assert got["data"] == {"account_id": acc["id"], "o": "t_pgtab1234"} and got["at"] - started < 2.0
        worker_write(uid, acc["id"], rollback=True)  # a rolled-back write is never announced …
        worker_write(uid, acc["id"])  # … a committed one is, without an origin
        assert stream.next("ledger", timeout=2.0)["data"] == {"account_id": acc["id"]}
        assert stream.none("ledger", wait=0.5)
    finally:
        stream.close()


def test_another_process_announces_new_closes(pg_server):
    base, _hub = pg_server
    a = browser(base, "demo@forliosa.local", "示範使用者")
    stream = Stream(base, a.token)
    try:
        stream.next("hello")
        env = {**os.environ, "DATABASE_URL": PG_URL}
        out = subprocess.run([sys.executable, "-m", "forliosa.realtime", "notify", "market.closes", "--market", "TWSE",
                              "--date", "2026-11-17"], env=env, capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr
        assert stream.next("market.closes", timeout=3.0)["data"] == {"market": "TWSE", "date": "2026-11-17"}
    finally:
        stream.close()


def test_a_lost_listen_connection_reconnects_and_tells_everyone_to_refetch(pg_server, pg_engine):
    base, _hub = pg_server
    a = browser(base, "demo@forliosa.local", "示範使用者")
    stream = Stream(base, a.token)
    try:
        stream.next("hello")
        with pg_engine.connect() as conn:
            n = conn.execute(text("SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity "
                                  "WHERE application_name = 'forliosa-realtime'")).scalar()
            assert n == 1
            conn.commit()
        assert stream.next("resync", timeout=10.0)["data"] == {}
        acc = a.post(f"{API}/accounts", json={"name": "二", "broker": "", "currency": "TWD",
                                              "fee_discount": 0.28}).json()
        assert stream.next("ledger", timeout=3.0)["data"]["account_id"] == acc["id"]  # listening again
    finally:
        stream.close()


def test_notify_happens_inside_the_transaction(pg_engine):
    """The payload is sent with the commit, and a large audience is split under Postgres's 8000-byte limit."""
    import psycopg

    from forliosa.realtime import emit, event
    from forliosa.realtime.pg import conninfo

    listener = psycopg.connect(conninfo(PG_URL), autocommit=True)
    listener.execute("LISTEN forliosa_rt_v1")
    with session_factory()() as db:
        db.add(User(id="usr_pg", email="pg@forliosa.local", display_name="pg"))
        db.flush()
        db.add(BrokerAccount(id="acc_pg", user_id="usr_pg", name="x", fee_rate=0, fee_discount=1, min_fee=0,
                             min_fee_odd_lot=0))
        emit(db, event("delegations", {}, tuple(f"u:usr_{i:026d}" for i in range(400))))
        db.commit()
    got = [n.payload for n in listener.notifies(timeout=2.0)]
    listener.close()
    assert any('"t":"ledger"' in p for p in got)
    big = [p for p in got if '"t":"delegations"' in p]
    assert len(big) > 1 and all(len(p.encode()) < 8000 for p in big)
    assert get_settings().realtime_enabled


def test_a_failure_while_announcing_never_fails_the_write(pg_engine, monkeypatch):
    """Resolving runs in a savepoint: a failing statement there is rolled back alone and the write commits."""
    from sqlalchemy import select

    from forliosa.realtime import capture

    def broken(self, conn):
        conn.execute(text("SELECT * FROM no_such_table"))

    monkeypatch.setattr(capture.LedgerFanout, "resolve", broken)
    with session_factory()() as db:
        db.add(User(id="usr_pg2", email="pg2@forliosa.local", display_name="pg"))
        db.flush()
        db.add(BrokerAccount(id="acc_pg2", user_id="usr_pg2", name="x", fee_rate=0, fee_discount=1, min_fee=0,
                             min_fee_odd_lot=0))
        db.commit()
    with session_factory()() as db:
        assert db.scalar(select(BrokerAccount.id).where(BrokerAccount.id == "acc_pg2")) == "acc_pg2"


class FreezingProxy:
    """A TCP proxy to the test database whose existing connections can be frozen: nothing is forwarded any more, but
    both sockets stay open (no FIN, no RST) — a database that moved, a partition, a proxy that stopped forwarding.
    Connections opened after the freeze are forwarded normally."""

    def __init__(self, host: str, port: int):
        import socket as socket_mod

        self.upstream = (host, port)
        self.server = socket_mod.create_server(("127.0.0.1", 0))
        self.port = self.server.getsockname()[1]
        self.pairs: list[dict] = []
        self.lock = threading.Lock()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        import socket as socket_mod

        while True:
            try:
                client, _ = self.server.accept()
            except OSError:
                return
            up = socket_mod.create_connection(self.upstream)
            pair = {"frozen": False, "socks": (client, up)}
            with self.lock:
                self.pairs.append(pair)
            for src, dst in ((client, up), (up, client)):
                threading.Thread(target=self._pump, args=(pair, src, dst), daemon=True).start()

    @staticmethod
    def _pump(pair: dict, src, dst) -> None:
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    return
                while pair["frozen"]:  # swallow nothing, forward nothing: the bytes wait in our buffer
                    time.sleep(0.05)
                dst.sendall(data)
        except OSError:
            return

    def freeze(self) -> int:
        with self.lock:
            for p in self.pairs:
                p["frozen"] = True
            return len(self.pairs)

    def close(self) -> None:
        self.server.close()
        with self.lock:
            for p in self.pairs:
                for s in p["socks"]:
                    with contextlib.suppress(OSError):
                        s.close()


def test_a_frozen_listen_connection_is_replaced(pg_engine, monkeypatch):
    """The LISTEN connection stops answering without closing: the idle probe times out, the hub stops counting as
    listening (new streams 503, the pages poll), reconnects, tells every stream to refetch, and hears NOTIFY again
    (2026-11-17 review: before, it stayed "listening" forever and every notification was lost)."""
    import asyncio
    from urllib.parse import urlsplit

    import psycopg

    from forliosa.realtime import pg
    from forliosa.realtime.hub import Hub, Refused
    from forliosa.realtime.pg import conninfo

    monkeypatch.setattr(pg, "IDLE_SECONDS", 0.5)
    monkeypatch.setattr(pg, "PROBE_TIMEOUT", 1.0)
    parts = urlsplit(conninfo(PG_URL))
    proxy = FreezingProxy(parts.hostname or "127.0.0.1", parts.port or 5432)
    proxied = PG_URL.replace(f"{parts.hostname}:{parts.port}", f"127.0.0.1:{proxy.port}")

    async def go():
        hub = Hub(postgres_url=proxied)
        await hub.start()
        try:
            for _ in range(200):
                if hub.listening:
                    break
                await asyncio.sleep(0.05)
            assert hub.listening
            conn, _ = hub.register("usr_a", "sa", False, None)
            assert proxy.freeze() == 1
            frozen_at = time.monotonic()
            down_after = None
            for _ in range(600):  # 30 s at most
                await asyncio.sleep(0.05)
                if down_after is None and not hub.listening:
                    down_after = time.monotonic() - frozen_at
                    with pytest.raises(Refused):
                        hub.admit("usr_b")  # new streams poll instead
                if down_after is not None and hub.listening:
                    break
            assert down_after is not None, "still 'listening' on a frozen connection"
            assert hub.listening  # reconnected through a fresh connection
            assert [t for _i, t, _d in conn.items][-1] == "resync"
            with psycopg.connect(conninfo(PG_URL), autocommit=True) as direct:
                direct.execute("SELECT pg_notify('forliosa_rt_v1', %s)",
                               ('{"t":"market.overview","a":["all"]}',))
            for _ in range(100):
                if [t for _i, t, _d in conn.items][-1] == "market.overview":
                    break
                await asyncio.sleep(0.05)
            assert [t for _i, t, _d in conn.items][-1] == "market.overview"
            return down_after
        finally:
            await hub.stop()

    try:
        down_after = asyncio.run(go())
    finally:
        proxy.close()
    assert down_after < 20.0  # idle 0.5 s + probe 1 s + psycopg's own cancellation (at most about 10 s)
