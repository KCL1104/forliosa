"""Request-scoped account scope for read-only viewing (``X-Forliosa-View-As``).

When a viewer reads a delegated ledger, ``api.deps.current_user`` resolves the delegation and stores a
:class:`ViewScope` on the request's database session (``Session.info``). Every place that loads a user's accounts
consults it, so the owner's ledger is computed **as if the owner had only the delegated accounts**:

* :func:`forliosa.services.ledger_io.load_ledger_input` (summary, holdings, allocation incl. ``by_account``,
  performance, closed rounds, upcoming incl. recurring plans, position, position history, events ``mine``)
* ``GET /accounts`` and ``/transactions`` (through :func:`account_ids`)

The scope only narrows the owner's own data (``owner_id``); it never widens anything. The same session also refuses
every write while the scope is active (:func:`guard_writes`: ORM flushes and bulk DML), so no write — an
automatic-dividend sync included — can run under view-as even if a read path tried one. The only exception is the
shared SEC EDGAR cache, which ``/instruments/{symbol}/events`` refreshes on demand for US stocks (no user data).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from forliosa.models import BrokerAccount

_KEY = "forliosa.view_scope"


@dataclass(frozen=True)
class ViewScope:
    delegation_id: str
    owner_id: str
    viewer_id: str
    account_ids: frozenset[str] | None  # None = every account of the owner (scope "all", later accounts included)


def set_view_scope(db: Session, scope: ViewScope) -> None:
    db.info[_KEY] = scope
    guard_writes(db)


def view_scope(db: Session) -> ViewScope | None:
    return db.info.get(_KEY)


def account_filter(db: Session, user_id: str) -> frozenset[str] | None:
    """The account ids ``user_id``'s data is limited to on this request, or None (no limit)."""
    scope = view_scope(db)
    if scope is None or scope.owner_id != user_id:
        return None
    return scope.account_ids


def account_ids(db: Session, user_id: str) -> list[str]:
    """Ids of ``user_id``'s accounts visible on this request (all of them unless a view scope narrows them)."""
    q = select(BrokerAccount.id).where(BrokerAccount.user_id == user_id)
    allowed = account_filter(db, user_id)
    if allowed is not None:
        q = q.where(BrokerAccount.id.in_(sorted(allowed)))
    return list(db.scalars(q))


def account_visible(db: Session, user_id: str, account_id: str) -> bool:
    allowed = account_filter(db, user_id)
    return allowed is None or account_id in allowed


# Shared market-data caches that an allow-listed read may refresh on demand (SEC EDGAR filings behind
# ``/instruments/{symbol}/events``). They hold no user data; every other table is refused under view-as.
SHARED_CACHE_TABLES = frozenset({"sec_tickers", "sec_companies", "sec_filings"})


def _refuse() -> None:
    from forliosa.api.errors import ApiError

    raise ApiError(403, "read_only", "唯讀查看模式不能修改資料")


def _deny_flush(session: Session, _ctx, _instances) -> None:
    for obj in (*session.new, *session.dirty, *session.deleted):
        if getattr(getattr(obj, "__table__", None), "name", None) not in SHARED_CACHE_TABLES:
            _refuse()


def _deny_dml(state) -> None:
    """Bulk ``insert`` / ``update`` / ``delete`` statements do not flush: check their target table too."""
    if state.is_insert or state.is_update or state.is_delete:
        table = getattr(state.statement, "table", None)
        if getattr(table, "name", None) not in SHARED_CACHE_TABLES:
            _refuse()


def guard_writes(db: Session) -> None:
    if not event.contains(db, "before_flush", _deny_flush):
        event.listen(db, "before_flush", _deny_flush)
    if not event.contains(db, "do_orm_execute", _deny_dml):
        event.listen(db, "do_orm_execute", _deny_dml)
