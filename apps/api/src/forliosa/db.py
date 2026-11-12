"""SQLAlchemy engine/session setup and portable column types."""

from __future__ import annotations

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


def make_engine(url: str) -> Engine:
    # hide_parameters: a failed statement's message (logged by the worker, the archive and the API error handler)
    # must not carry the bound values — company_profiles holds 董事長／總經理 (kept without history), the ledger
    # holds users' trades.
    kwargs: dict = {"pool_pre_ping": True, "hide_parameters": True}
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
    return engine


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
        _SessionLocal = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def set_engine(engine: Engine) -> None:
    """Used by tests to point the app at a temporary database."""
    global _engine, _SessionLocal
    _engine = engine
    _SessionLocal = sessionmaker(engine, expire_on_commit=False)


def session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Iterator[Session]:
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()
