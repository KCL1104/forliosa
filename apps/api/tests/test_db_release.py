"""A request gives its pooled connection back between FastAPI's threadpool calls (2026-11-17, the resync burst).

* ``forliosa.db.release_connection`` ends a read-only transaction and keeps the loaded objects; it leaves alone a
  session with unflushed changes, a write it did not commit, realtime events waiting for a commit, a savepoint, or a
  session that expires on commit.
* The sign-in dependencies (``api.deps``) and every sync endpoint (``api.routing.Router``) call it: while the endpoint
  starts and while FastAPI validates the response, the request holds no pooled connection.
* Every route of the app is added by ``Router`` (a new module with a plain ``APIRouter`` fails here).
"""

from __future__ import annotations

from fastapi import Depends
from fastapi.routing import APIRoute
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from forliosa import realtime
from forliosa.api import deps
from forliosa.api.routing import RELEASES, Router, plain_sync
from forliosa.db import get_db, release_connection, session_factory
from forliosa.models import BrokerAccount, User
from tests.api.m5 import API, account


def _me(engine) -> str:
    with Session(engine) as db:
        return db.scalars(select(User.id).where(User.email == "demo@forliosa.local")).one()


# -- release_connection -------------------------------------------------------------------------------------------
def test_a_read_only_transaction_gives_its_connection_back_and_keeps_its_objects(client, engine):
    uid = _me(engine)
    db = session_factory()()
    try:
        user = db.get(User, uid)
        assert engine.pool.checkedout() == 1 and db.in_transaction()
        assert release_connection(db) is True
        assert engine.pool.checkedout() == 0 and not db.in_transaction()
        assert user.display_name == "示範使用者" and engine.pool.checkedout() == 0  # still loaded: no query
        assert db.scalars(select(User).where(User.id == uid)).one() is user
        assert engine.pool.checkedout() == 1  # the next query took a connection again
        assert release_connection(db) is True
        assert release_connection(db) is False  # nothing open
    finally:
        db.close()


def test_uncommitted_writes_are_left_to_close(client, engine):
    uid = _me(engine)
    db = session_factory()()
    try:
        user = db.get(User, uid)
        user.display_name = "改了"
        assert release_connection(db) is False  # unflushed change
        db.flush()
        assert release_connection(db) is False  # flushed, not committed
        db.rollback()
        db.execute(update(User).where(User.id == uid).values(display_name="Core 改的"))
        assert release_connection(db) is False and engine.pool.checkedout() == 1  # a Core write, not committed
        db.commit()
        db.get(User, uid)
        assert release_connection(db) is True  # the next transaction only read
    finally:
        db.close()
    with Session(engine) as check:
        assert check.get(User, uid).display_name == "Core 改的"


def test_pending_events_a_savepoint_and_expiring_sessions_are_left_alone(client, engine):
    uid = _me(engine)
    db = session_factory()()
    try:
        db.get(User, uid)
        realtime.emit(db, realtime.event("watchlist", {}, (f"u:{uid}",)))
        assert release_connection(db) is False  # the writer decides whether its events go out
        db.rollback()
        db.get(User, uid)
        nested = db.begin_nested()
        assert release_connection(db) is False
        nested.rollback()
        assert release_connection(db) is True
    finally:
        db.close()
    expiring = sessionmaker(engine, expire_on_commit=True)()
    try:
        expiring.get(User, uid)
        assert release_connection(expiring) is False  # a commit would expire what the response still reads
    finally:
        expiring.close()


# -- the routes ---------------------------------------------------------------------------------------------------
def _routes(routes):
    for r in routes:
        if isinstance(r, APIRoute):
            yield r
        elif hasattr(r, "original_router"):  # FastAPI's included router
            yield from _routes(r.original_router.routes)


def test_every_sync_route_gives_its_connection_back(app):
    routes = list(_routes(app.routes))
    sync = [r for r in routes if plain_sync(r.endpoint)]
    assert len(sync) > 150
    missing = sorted(f"{sorted(r.methods)[0]} {r.path}" for r in sync if not getattr(r.endpoint, RELEASES, False))
    assert missing == []


def test_no_connection_is_held_when_the_endpoint_starts_or_the_response_is_validated(client, engine, monkeypatch):
    """One request through the real app: after the sign-in check (its own threadpool call) and after the endpoint
    (FastAPI validates the response in another), the request pool has nothing checked out."""
    import fastapi.routing

    account(client)
    seen: dict[str, list[int]] = {"endpoint": [], "validate": []}
    probe = Router()

    @probe.get("/probe-release", response_model=list[str])
    def probe_release(user: User = Depends(deps.current_user), db: Session = Depends(get_db)):
        seen["endpoint"].append(engine.pool.checkedout())
        return list(db.scalars(select(BrokerAccount.name).where(BrokerAccount.user_id == user.id)))

    client.app.include_router(probe, prefix=API)
    real = fastapi.routing.serialize_response

    async def watching(**kwargs):
        seen["validate"].append(engine.pool.checkedout())
        return await real(**kwargs)

    monkeypatch.setattr(fastapi.routing, "serialize_response", watching)
    r = client.get(f"{API}/probe-release")
    assert r.status_code == 200 and len(r.json()) == 1, r.text
    assert seen == {"endpoint": [0], "validate": [0]}
    seen["validate"].clear()
    r = client.get(f"{API}/accounts")  # a real route: the same
    assert r.status_code == 200 and seen["validate"] == [0], seen
    assert engine.pool.checkedout() == 0
