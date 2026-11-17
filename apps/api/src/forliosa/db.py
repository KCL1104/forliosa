"""SQLAlchemy engine/session setup and portable column types."""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import DateTime, Dialect, Engine, Numeric, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from forliosa.config import get_settings


class Money(TypeDecorator[Decimal]):
    """Exact decimal column: NUMERIC(24, 8) on PostgreSQL, TEXT on SQLite (which has no decimal)."""

    impl = Numeric(24, 8)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(40))
        return dialect.type_descriptor(Numeric(24, 8, asdecimal=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        d = Decimal(value)
        if dialect.name == "sqlite":
            return format(d.normalize(), "f") if d != 0 else "0"
        return d

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(str(value))


class TZDateTime(TypeDecorator[datetime]):
    """Timezone-aware timestamps everywhere (SQLite drops the offset, so values are stored in UTC)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def make_engine(url: str, **options) -> Engine:
    # hide_parameters: a failed statement's message (logged by the worker, the archive and the API error handler)
    # must not carry the bound values — company_profiles holds 董事長／總經理 (kept without history), the ledger
    # holds users' trades.
    kwargs: dict = {"pool_pre_ping": True, "hide_parameters": True, **options}
    if url.startswith("sqlite"):
        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    from forliosa.perf import instrument_engine

    instrument_engine(engine)  # the slow-request log's per-request SQL counters (no-op outside a request)
    return engine


def _watch_writes() -> None:
    """Realtime updates: every session's writes are announced with its commit (``forliosa.realtime.capture``); a
    session's own writes are noted for :func:`release_connection`."""
    from forliosa.realtime import capture

    capture.install()
    _track_writes()


# -- a request's connection between two threadpool calls ----------------------------------------------------------
# A sync request runs in several threadpool calls (the sign-in dependency, the endpoint, the response's validation),
# each taking one of anyio's 40 tokens. A session that read keeps its pooled connection until its transaction ends, so
# a request used to hold one between those calls, waiting for a token without one. Under a burst (2026-11-17, a deploy's
# resync: every open tab refetching at once) the 40 tokens all went to requests waiting for a connection while the 15
# connections sat with requests waiting for a token, until the pool timed out (500 ``QueuePool limit``). The sign-in
# dependencies (``api.deps``) and every sync endpoint (``api.routing.Router``) therefore end a read-only transaction
# before they return; the next query takes a connection again (``pool_pre_ping``: one ``SELECT 1`` more per request).
WROTE_KEY = "forliosa.wrote"
_writes_tracked = False


def _note_flush(session: Session, _ctx) -> None:
    session.info[WROTE_KEY] = True


def _note_statement(state) -> None:
    if not state.is_select:  # Core insert / update / delete, text(): anything but a SELECT counts as a write
        state.session.info[WROTE_KEY] = True


def _forget_writes(session: Session, transaction) -> None:
    if transaction.parent is None:
        session.info.pop(WROTE_KEY, None)


def _track_writes() -> None:
    global _writes_tracked
    if _writes_tracked:
        return
    event.listen(Session, "after_flush", _note_flush)
    event.listen(Session, "do_orm_execute", _note_statement)
    event.listen(Session, "after_transaction_end", _forget_writes)
    _writes_tracked = True


def release_connection(db: Session) -> bool:
    """End ``db``'s transaction when it has only read, so its pooled connection goes back to the pool; the loaded
    objects stay usable (``expire_on_commit=False``) and the next query takes a connection again. Left alone (and
    False): no transaction, a savepoint open, unflushed changes, a write this transaction made and did not commit
    (a dry run rolls back itself; anything else is rolled back by ``close()`` as before), realtime events waiting for
    a commit, or a session that would expire its objects on commit. Never raises: a broken transaction is reported by
    the next query or rolled back by ``close()``."""
    if not db.in_transaction() or db.in_nested_transaction() or db.expire_on_commit:
        return False
    if db.new or db.dirty or db.deleted or db.info.get(WROTE_KEY):
        return False
    from forliosa.realtime import capture

    if capture.has_pending(db):
        return False
    try:
        db.commit()
    except Exception:  # pragma: no cover - e.g. a transaction that already failed: close() rolls it back
        logging.getLogger(__name__).debug("release_connection: commit failed", exc_info=True)
        return False
    return True


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
        _SessionLocal = sessionmaker(_engine, expire_on_commit=False)
        _watch_writes()
    return _engine


def set_engine(engine: Engine) -> None:
    """Used by tests to point the app at a temporary database."""
    global _engine, _SessionLocal
    _engine = engine
    _SessionLocal = sessionmaker(engine, expire_on_commit=False)
    _drop_archive_engine()
    _watch_writes()


def session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


# -- the market-data archive's own pool ---------------------------------------------------------------------------
# A request holds one pooled connection while its endpoint runs (until the 2026-11-17 merge review: from its first
# query, the sign-in check, to its response; see ``release_connection`` above); the archive's reads
# (``marketdata.archive_provider``) open sessions of their own. On one pool, 15 requests that each held a connection and
# waited for a second one waited for each other until the 30 s pool timeout (2026-11-17: three ledger pages at once,
# 3 of 3 runs). The archive therefore reads through a pool of its own on the same database: an archive session never
# waits for another connection while it holds one, so that pool always drains.
ARCHIVE_POOL_SIZE = 5
ARCHIVE_MAX_OVERFLOW = 10
_archive_engine: Engine | None = None
_archive_for: Engine | None = None
_ArchiveSession: sessionmaker[Session] | None = None
_archive_lock = threading.Lock()


def _drop_archive_engine() -> None:
    global _archive_engine, _archive_for, _ArchiveSession
    with _archive_lock:
        old = _archive_engine
        _archive_engine = _archive_for = _ArchiveSession = None
    if old is not None:
        old.dispose()


def archive_session_factory() -> sessionmaker[Session]:
    """Sessions for the archive's reads, on a pool of their own (see above), following whatever engine the app uses
    (``set_engine`` in tests). An in-memory SQLite database cannot be opened twice: it shares the app's engine."""
    global _archive_engine, _archive_for, _ArchiveSession
    main = get_engine()
    with _archive_lock:
        if _ArchiveSession is not None and _archive_for is main:
            return _ArchiveSession
        url = main.url
        if url.get_backend_name() == "sqlite" and url.database in (None, "", ":memory:"):
            engine = main
        else:
            engine = make_engine(url.render_as_string(hide_password=False), pool_size=ARCHIVE_POOL_SIZE,
                                 max_overflow=ARCHIVE_MAX_OVERFLOW)
        old = _archive_engine if _archive_engine is not main else None
        _archive_engine, _archive_for = engine, main
        _ArchiveSession = sessionmaker(engine, expire_on_commit=False)
        factory = _ArchiveSession
    if old is not None and old is not engine:
        old.dispose()
    return factory


def get_db() -> Iterator[Session]:
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()
