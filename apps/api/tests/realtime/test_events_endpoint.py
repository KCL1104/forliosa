"""``GET /api/v1/events`` end to end. Short streams go through the TestClient (it returns once a stream ends, so
they use a stream lifetime of a fraction of a second); live delivery runs a real uvicorn server on a free port with
the browser side played by httpx, the way two people with the app open would use it."""

from __future__ import annotations

import contextlib
import json
import queue
import socket
import threading
import time
from datetime import date

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from forliosa.config import get_settings
from forliosa.db import get_engine
from tests.api.m5 import API, SHARE_DEFAULT, token_of

COOKIE = "forliosa_session"


def frames(text: str) -> list[dict]:
    out = []
    for block in text.strip("\n").split("\n\n"):
        f: dict = {}
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            k, _, v = line.partition(": ")
            f[k] = json.loads(v) if k == "data" else v
        if "event" in f:
            out.append(f)
    return out


@pytest.fixture()
def short_streams(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "realtime_stream_max_seconds", 0.3)
    monkeypatch.setattr(s, "realtime_heartbeat_seconds", 0.1)
    return s


# -- refusals and the frame format (TestClient) ------------------------------------------------------------------
def test_off_without_a_running_hub(client):
    r = client.get(f"{API}/events")  # no lifespan: no hub in this app
    assert r.status_code == 503 and r.json()["error"]["code"] == "realtime_off"


def test_refusals(app, short_streams):
    with TestClient(app) as c:
        r = c.get(f"{API}/events")
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
        c.cookies.set(COOKIE, "not-a-session")
        assert c.get(f"{API}/events").status_code == 401
        c.cookies.clear()
        assert c.post(f"{API}/auth/dev-login", json={"email": "demo@forliosa.local"}).status_code == 200
        r = c.get(f"{API}/events", headers={"Origin": "https://evil.example"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
        assert c.get(f"{API}/events", headers={"Origin": "http://localhost:5173"}).status_code == 200


def test_hello_heartbeat_and_rotation(app, short_streams):
    with TestClient(app) as c:
        c.post(f"{API}/auth/dev-login", json={"email": "demo@forliosa.local"})
        r = c.get(f"{API}/events", headers={"X-Forliosa-View-As": "dlg_whatever"})  # ignored, not refused
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["cache-control"].startswith("no-cache") and r.headers["x-accel-buffering"] == "no"
        assert r.text.startswith("retry: 5000\n\n") and ": ping" in r.text
        got = frames(r.text)
        hello = got[0]
        assert hello["event"] == "hello" and hello["data"]["replay"] == "none" and "." in hello["id"]
        assert got[-1] == {"event": "bye", "data": {"reason": "rotate"}}
        again = frames(c.get(f"{API}/events", params={"last": hello["id"]}).text)[0]
        assert again["data"]["replay"] == "replayed"
        other = frames(c.get(f"{API}/events", headers={"Last-Event-ID": "zzzzzz.9"}).text)[0]
        assert other["data"]["replay"] == "resync"


def test_connect_rate_limit(app, short_streams, monkeypatch):
    monkeypatch.setattr(short_streams, "realtime_connects_per_minute", 2)
    monkeypatch.setattr(short_streams, "realtime_stream_max_seconds", 0.05)
    with TestClient(app) as c:
        c.post(f"{API}/auth/dev-login", json={"email": "demo@forliosa.local"})
        assert [c.get(f"{API}/events").status_code for _ in range(2)] == [200, 200]
        r = c.get(f"{API}/events")
        assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_streams"
        assert int(r.headers["retry-after"]) >= 1


def test_switched_off(app, monkeypatch):
    monkeypatch.setattr(get_settings(), "realtime_enabled", False)
    with TestClient(app) as c:
        c.post(f"{API}/auth/dev-login", json={"email": "demo@forliosa.local"})
        r = c.get(f"{API}/events")
        assert r.status_code == 503 and r.json()["error"]["code"] == "realtime_off"


# -- live delivery (uvicorn) -------------------------------------------------------------------------------------
@pytest.fixture()
def server(app):
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on",
                            timeout_graceful_shutdown=1)
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(200):
        if srv.started:
            break
        time.sleep(0.02)
    assert srv.started
    port = srv.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(10)


class Browser(httpx.Client):
    token: str


def browser(base: str, email: str, name: str) -> Browser:
    c = Browser(base_url=base, timeout=10)
    r = c.post(f"{API}/auth/dev-login", json={"email": email, "display_name": name})
    assert r.status_code == 200, r.text
    c.token = r.cookies[COOKIE]
    return c


class Stream:
    """An open ``/events`` stream on a raw socket (so that closing it really drops the connection, like a closed
    tab), read by a thread; frames are queued as they arrive."""

    def __init__(self, base: str, token: str, **params):
        self.frames: queue.Queue = queue.Queue()
        self.status: int | None = None
        host, port = base.removeprefix("http://").split(":")
        query = ("?" + "&".join(f"{k}={v}" for k, v in params.items())) if params else ""
        self.sock = socket.create_connection((host, int(port)), timeout=30)
        self.sock.sendall((f"GET {API}/events{query} HTTP/1.1\r\nHost: {host}\r\nAccept: text/event-stream\r\n"
                           f"Cookie: {COOKIE}={token}\r\n\r\n").encode())
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self) -> None:
        raw = b""
        try:
            while b"\r\n\r\n" not in raw:
                raw += self.sock.recv(4096)
            head, raw = raw.split(b"\r\n\r\n", 1)
            self.status = int(head.split(b" ")[1])
            text = ""
            while True:  # chunked transfer encoding
                while b"\r\n" not in raw:
                    raw += self._recv()
                size_line, raw = raw.split(b"\r\n", 1)
                size = int(size_line, 16)
                if size == 0:
                    return
                while len(raw) < size + 2:
                    raw += self._recv()
                text += raw[:size].decode()
                raw = raw[size + 2:]
                while "\n\n" in text:
                    block, text = text.split("\n\n", 1)
                    for f in frames(block + "\n\n"):
                        f["at"] = time.monotonic()
                        self.frames.put(f)
        except Exception:  # closed by the test
            pass

    def _recv(self) -> bytes:
        data = self.sock.recv(4096)
        if not data:
            raise ConnectionError("closed")
        return data

    def next(self, topic: str | None = None, timeout: float = 5.0, live: bool = False) -> dict:
        """The next frame (of ``topic``); ``live``: skip events replayed after ``hello`` (they carry no id)."""
        deadline = time.monotonic() + timeout
        while True:
            f = self.frames.get(timeout=max(0.01, deadline - time.monotonic()))
            if (topic is None or f["event"] == topic) and not (live and "id" not in f):
                return f

    def none(self, topic: str, wait: float = 0.5) -> bool:
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            try:
                f = self.frames.get(timeout=0.05)
            except queue.Empty:
                continue
            if f["event"] == topic:
                return False
        return True

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self.sock.shutdown(socket.SHUT_RDWR)
        self.sock.close()


def test_a_friend_joins_and_the_open_group_page_hears_it(server):
    """The owner's report (2026-11-17), end to end: B accepts A's invite while A has the app open."""
    a = browser(server, "demo@forliosa.local", "示範使用者")
    b = browser(server, "friend@forliosa.local", "朋友")
    g = a.post(f"{API}/groups", json={"name": "家族投資"}).json()
    inv = a.post(f"{API}/groups/{g['id']}/invites", json={}).json()
    stream = Stream(server, a.token)
    try:
        assert stream.next("hello")["data"]["replay"] == "none"
        started = time.monotonic()
        r = b.post(f"{API}/invites/{token_of(inv)}/accept", json={"share": SHARE_DEFAULT})
        assert r.status_code == 200, r.text
        got = stream.next("group.members", timeout=2.0)
        assert got["data"] == {"group_id": g["id"]}  # no names, no user ids
        assert got["at"] - started < 2.0
    finally:
        stream.close()


def test_my_other_device_and_my_own_tab(server):
    d1 = browser(server, "demo@forliosa.local", "示範使用者")
    d2 = browser(server, "demo@forliosa.local", "示範使用者")  # a second login: another device
    acc = d2.post(f"{API}/accounts", json={"name": "永豐", "broker": "永豐金證券", "currency": "TWD",
                                           "fee_discount": 0.28}).json()
    stream = Stream(server, d1.token)
    try:
        assert stream.next("hello")["data"]["replay"] == "none"
        # a page's first stream gets the last seconds of its events again (without an id): the page's first requests
        # may have read the database just before a change whose event arrived before the stream was registered
        replayed = stream.next("ledger", timeout=2.0)
        assert replayed["data"] == {"account_id": acc["id"]} and "id" not in replayed
        r = d2.post(f"{API}/transactions", headers={"X-Forliosa-Tab": "t_device2tab"},
                    json={"account_id": acc["id"], "symbol": "2330.TW", "type": "buy",
                          "trade_date": date(2025, 3, 4).isoformat(), "quantity": 1000, "price": 600})
        assert r.status_code == 201, r.text
        got = stream.next("ledger", timeout=2.0)
        assert "id" in got
        # the same user: the origin tab is named, so the tab that made the change can skip its own echo
        assert got["data"] == {"account_id": acc["id"], "o": "t_device2tab"}
    finally:
        stream.close()


def test_other_people_never_see_my_tab_or_my_ledger(server):
    a = browser(server, "demo@forliosa.local", "示範使用者")
    b = browser(server, "friend@forliosa.local", "朋友")
    g = a.post(f"{API}/groups", json={"name": "家族投資"}).json()
    inv = a.post(f"{API}/groups/{g['id']}/invites", json={}).json()
    b.post(f"{API}/invites/{token_of(inv)}/accept", json={"share": SHARE_DEFAULT})
    acc = a.post(f"{API}/accounts", json={"name": "永豐", "broker": "", "currency": "TWD",
                                          "fee_discount": 0.28}).json()
    stream = Stream(server, b.token)
    try:
        stream.next("hello")
        a.post(f"{API}/transactions", headers={"X-Forliosa-Tab": "t_secret_tab"},
               json={"account_id": acc["id"], "symbol": "2330.TW", "type": "buy", "trade_date": "2025-03-04",
                     "quantity": 1000, "price": 600})
        got = stream.next("group.ledger", timeout=2.0)
        assert got["data"] == {"group_id": g["id"]}  # A shares returns there; who and what stay unsaid
        assert stream.none("ledger")
    finally:
        stream.close()


def test_the_stream_holds_no_database_connection(server):
    a = browser(server, "demo@forliosa.local", "示範使用者")
    streams = [Stream(server, a.token) for _ in range(3)]
    try:
        for s in streams:
            s.next("hello")
        time.sleep(0.2)
        assert get_engine().pool.checkedout() == 0
    finally:
        for s in streams:
            s.close()


def test_logout_closes_my_stream(server):
    a = browser(server, "demo@forliosa.local", "示範使用者")
    stream = Stream(server, a.token)
    try:
        stream.next("hello")
        assert a.post(f"{API}/auth/logout").status_code == 204
        assert stream.next("bye", timeout=2.0)["data"] == {"reason": "unauthorized"}
    finally:
        stream.close()


def test_a_seventh_tab_replaces_the_oldest(server):
    a = browser(server, "demo@forliosa.local", "示範使用者")
    streams = [Stream(server, a.token) for _ in range(6)]
    try:
        for s in streams:
            s.next("hello")
        seventh = Stream(server, a.token)
        streams.append(seventh)
        seventh.next("hello")
        assert streams[0].next("bye", timeout=2.0)["data"] == {"reason": "replaced"}
    finally:
        for s in streams:
            s.close()



def test_a_browser_that_leaves_is_forgotten(server, app):
    a = browser(server, "demo@forliosa.local", "示範使用者")
    stream = Stream(server, a.token)
    stream.next("hello")
    hub = app.state.realtime_hub
    assert len(hub.conns) == 1
    stream.close()
    for _ in range(100):
        if not hub.conns:
            break
        time.sleep(0.02)
    assert not hub.conns and not hub.by_user


def test_a_cross_origin_page_can_read_how_long_to_wait(app, monkeypatch):
    """The web app reads the API from another origin (forliosa.trade → api.forliosa.trade): Retry-After must be exposed
    to it, and the JSON says it too (2026-11-17 review: the kill switch's 10 minutes collapsed to 30 s)."""
    monkeypatch.setattr(get_settings(), "realtime_enabled", False)
    with TestClient(app) as c:
        c.post(f"{API}/auth/dev-login", json={"email": "demo@forliosa.local"})
        r = c.get(f"{API}/events", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 503 and r.headers["retry-after"] == "600"
    assert "retry-after" in r.headers["access-control-expose-headers"].lower()
    assert r.json()["error"] | {"message": None} == {"code": "realtime_off", "retry_after_seconds": 600,
                                                     "message": None}


def test_the_tab_header_passes_cors(client):
    r = client.options(f"{API}/transactions", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-forliosa-tab"})
    assert r.status_code == 200
    assert "x-forliosa-tab" in r.headers["access-control-allow-headers"].lower()


def test_sigterm_ends_every_stream_with_a_bye_at_once(tmp_path):
    """A deploy: uvicorn gets SIGTERM, waits up to --timeout-graceful-shutdown for open connections and only then runs
    the lifespan shutdown. The streams must end when the signal arrives (``bye{rotate}``), not be cut after the grace
    period with an error (2026-11-17 review). The real CLI, in a process of its own (signals need the main thread)."""
    import os
    import signal
    import subprocess
    import sys

    from forliosa.db import Base, make_engine

    url = f"sqlite:///{tmp_path / 'rt.db'}"
    eng = make_engine(url)
    Base.metadata.create_all(eng)
    eng.dispose()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {**os.environ, "DATABASE_URL": url}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "forliosa.main:app", "--host", "127.0.0.1", "--port",
                             str(port), "--timeout-graceful-shutdown", "8"],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}"
    stream = None
    try:
        for _ in range(300):
            with contextlib.suppress(httpx.HTTPError):
                if httpx.get(f"{base}{API}/health", timeout=1).status_code == 200:
                    break
            time.sleep(0.05)
        a = browser(base, "demo@forliosa.local", "示範使用者")
        stream = Stream(base, a.token)
        stream.next("hello", timeout=5)
        sent = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        bye = stream.next("bye", timeout=3)
        assert bye["data"] == {"reason": "rotate"} and bye["at"] - sent < 1.0
        proc.wait(timeout=5)
        assert time.monotonic() - sent < 4.0  # not the 8-second grace period
        log = proc.stdout.read() if proc.stdout else ""
        assert "timeout graceful shutdown exceeded" not in log and "Exception in ASGI application" not in log
    finally:
        if stream is not None:
            stream.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait(5)
