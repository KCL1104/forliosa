"""Collect realtime events from database writes and send them with the commit.

Every ``Session`` (API requests, the worker, scripts) is watched:

* ``after_flush`` — inserted, changed and deleted rows of the models in :data:`HANDLERS` become events (a row carries
  the ids needed to route it: ``user_id``, ``group_id``, ``account_id`` …). Core statements (bulk ``delete`` /
  ``update``) are not seen here; the services that use them call :func:`emit` with the events themselves.
* ``before_commit`` — the session is flushed, then symbolic audiences (``g:`` members, ``gm:`` managers) and fan-outs
  (a ledger change → the groups the member shares it with and the delegations that cover the account) are resolved
  **in the same transaction**, so the audience is exactly who may see the change once it is committed. On PostgreSQL
  the events are sent with ``pg_notify`` inside the transaction: delivered only if it commits, in commit order, to
  every listening API process (including the one that wrote). On SQLite they wait for ``after_commit`` and go to this
  process's hub (``realtime.bus``).
* ``after_rollback`` — collected events are dropped: a write that did not happen announces nothing.

Nothing here may break a write: a failure while collecting or resolving drops the events and logs the error type
(never ids or values). Origin: ``api.deps`` records the signed-in user and the browser tab (``X-Forliosa-Tab``) on the
request's session (``session.info``); every event of that session carries them (internal fields).
"""

from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Connection, inspect, or_, select, text
from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

from forliosa.realtime import bus
from forliosa.realtime.events import (
    ADMINS,
    ALL,
    CHANNEL,
    Event,
    discussion_audience,
    event,
    group,
    managers,
    split_for_notify,
    user,
)

log = logging.getLogger(__name__)

STATE_KEY = "forliosa_rt"
ORIGIN_KEY = "forliosa_rt_origin"
TAB_RE = re.compile(r"^[A-Za-z0-9_-]{8,32}$")
_installed = False


# -- the per-session collection -----------------------------------------------------------------------------------
class Resolver:
    """A fan-out that needs a query: resolved in ``before_commit`` on the session's connection (Core selects only).
    ``key`` merges several resolvers of the same thing (200 imported rows → one query)."""

    key: tuple

    def merge(self, other: Resolver) -> None:  # pragma: no cover - default: identical
        return None

    def resolve(self, conn: Connection) -> list[Event]:  # pragma: no cover - abstract
        raise NotImplementedError


@dataclass
class _State:
    items: list[Event | Resolver] = field(default_factory=list)
    resolvers: dict[tuple, Resolver] = field(default_factory=dict)
    ready: list[Event] = field(default_factory=list)  # SQLite: resolved, published after the commit

    def add(self, item: Event | Resolver) -> None:
        if isinstance(item, Resolver):
            seen = self.resolvers.get(item.key)
            if seen is not None:
                seen.merge(item)
                return
            self.resolvers[item.key] = item
        self.items.append(item)

    def clear(self) -> None:
        self.items.clear()
        self.resolvers.clear()


def _state(session: Session) -> _State:
    st = session.info.get(STATE_KEY)
    if st is None:
        st = session.info[STATE_KEY] = _State()
    return st


def _enabled() -> bool:
    from forliosa.config import get_settings

    return get_settings().realtime_enabled


def set_origin(session: Session, user_id: str | None, tab: str | None) -> None:
    """Who made the writes of this session (a request): the signed-in user and, when valid, the browser tab id."""
    session.info[ORIGIN_KEY] = (user_id, tab if tab and TAB_RE.match(tab) else None)


def emit(session: Session, *items: Event | Resolver) -> None:
    """Events of a write the ORM cannot see (Core ``delete`` / ``update``), sent with the session's next commit."""
    if not _enabled():
        return
    st = _state(session)
    for item in items:
        st.add(item)


def notify_now(*events: Event) -> None:
    """Send events outside any request (the worker's market-data jobs): a short transaction of their own."""
    if not events or not _enabled():
        return
    from forliosa.db import session_factory

    try:
        with session_factory()() as db:
            emit(db, *events)
            db.commit()
    except Exception as exc:  # announcing must never fail the job that stored the data
        log.warning("realtime: notify failed (%s)", type(exc).__name__)


# -- reading rows -------------------------------------------------------------------------------------------------
def _v(obj: Any, key: str) -> Any:
    d = inspect(obj).dict
    if key in d:
        return d[key]
    try:
        return getattr(obj, key)
    except Exception:  # an expired attribute of a deleted row: unknown
        return None


def _changed(obj: Any) -> set[str]:
    """Column attributes whose value really changed in this flush (setting the same value is not a change)."""
    st = inspect(obj)
    out: set[str] = set()
    for attr in st.mapper.column_attrs:
        h = st.attrs[attr.key].history
        if (h.added or h.deleted) and list(h.added) != list(h.deleted):
            out.add(attr.key)
    return out


def _old(obj: Any, key: str) -> Any:
    h = inspect(obj).attrs[key].history
    return h.deleted[0] if h.deleted else _v(obj, key)


# -- resolvers ----------------------------------------------------------------------------------------------------
def _models():
    from forliosa import models

    return models


class LedgerFanout(Resolver):
    """A member's ledger changed: ``group.ledger`` to each group that can see the change (never naming the member), and
    ``ledger.viewas`` to each viewer of a delegation whose scope covers a changed account (no account given, e.g. the
    cost method: every viewer).

    A group sees a member's ledger only through what they share (2026-11-17 review: an event the refetch does not
    explain tells the other members *when* the member did something hidden):

    * ``returns`` / ``holdings`` — any change to positions or performance (``positions``), never a note-only edit;
    * ``trades`` — only a change to a transaction the feed shows (:func:`feed_visible`, before or after the change).
    """

    def __init__(self, uid: str, accounts: Iterable[str | None] = (), *, positions: bool = True, feed: bool = True):
        self.uid = uid
        self.accounts = {a for a in accounts if a}
        self.all_accounts = not self.accounts
        self.positions = positions
        self.feed = feed
        self.key = ("ledger", uid)

    def merge(self, other: Resolver) -> None:
        assert isinstance(other, LedgerFanout)
        self.all_accounts = self.all_accounts or other.all_accounts
        self.accounts |= other.accounts
        self.positions = self.positions or other.positions
        self.feed = self.feed or other.feed

    def resolve(self, conn: Connection) -> list[Event]:
        m = _models()
        s = m.GroupShareSetting
        out: list[Event] = []
        if self.positions or self.feed:
            rows = conn.execute(select(s.group_id, s.returns, s.holdings, s.trades)
                                .where(s.user_id == self.uid, or_(s.returns, s.holdings, s.trades)))
            out = [event("group.ledger", {"group_id": g}, group(g), echo=False)
                   for g, returns, holdings, trades in rows
                   if ((returns or holdings) and self.positions) or (trades and self.feed)]
        d, da = m.Delegation, m.DelegationAccount
        for dlg_id, viewer_id, scope in conn.execute(select(d.id, d.viewer_id, d.scope).where(d.owner_id == self.uid)):
            if scope != "all" and not self.all_accounts:
                scoped = set(conn.execute(select(da.account_id).where(da.delegation_id == dlg_id)).scalars())
                if not scoped & self.accounts:
                    continue
            out.append(event("ledger.viewas", {"delegation_id": dlg_id}, user(viewer_id), echo=False))
        return out


# Transaction columns that change neither positions nor performance (what returns / holdings shares show) …
NON_POSITION_COLUMNS = frozenset({"note", "source", "import_batch_id", "created_at", "updated_at"})
# … and the columns a group feed item shows (eligibility itself — side, source, note — is compared separately)
FEED_COLUMNS = frozenset({"symbol", "type", "trade_date", "quantity", "price", "currency"})


def feed_visible(get: Callable[[str], Any], today: date | None = None) -> bool:
    """Would a transaction with these values appear in a group feed (``services.sharing.feed_items``): a manual or
    signed-draft buy or sell with a symbol, not a converted holding, traded within the feed window."""
    from forliosa.services.sharing import CONVERTED_NOTE, FEED_DAYS, FEED_SIDES, FEED_SOURCES
    from forliosa.timeutil import today_taipei

    day = get("trade_date")
    if not isinstance(day, date):
        return False
    today = today or today_taipei()
    return (get("type") in FEED_SIDES and get("source") in FEED_SOURCES and bool(get("symbol"))
            and get("note") != CONVERTED_NOTE and today - timedelta(days=FEED_DAYS) <= day <= today)


class NameFanout(Resolver):
    """A display name or avatar changed: every group of the user shows it, and so does the other side of each of the
    user's delegations (the view-as banner and the delegation lists name the owner and the viewer)."""

    def __init__(self, uid: str):
        self.uid = uid
        self.key = ("name", uid)

    def resolve(self, conn: Connection) -> list[Event]:
        m = _models()
        gm, d = m.GroupMember, m.Delegation
        out = [event("group.members", {"group_id": g}, group(g), echo=False)
               for g in conn.execute(select(gm.group_id).where(gm.user_id == self.uid)).scalars()]
        others = {o if o != self.uid else v for o, v in conn.execute(
            select(d.owner_id, d.viewer_id).where(or_(d.owner_id == self.uid, d.viewer_id == self.uid)))}
        if others:
            out.append(event("delegations", {}, tuple(f"u:{u}" for u in sorted(others)), echo=False))
        return out


class OwnerDelegations(Resolver):
    """An account was deleted: delegations scoped to it lost it (the rows cascade in the database)."""

    def __init__(self, uid: str):
        self.uid = uid
        self.key = ("owner_dlg", uid)

    def resolve(self, conn: Connection) -> list[Event]:
        d = _models().Delegation
        viewers = list(conn.execute(select(d.viewer_id).where(d.owner_id == self.uid)).scalars())
        if not viewers:
            return []
        return [event("delegations", {}, user(self.uid) + tuple(f"u:{v}" for v in viewers), echo=False)]


class DelegationRef(Resolver):
    """A delegation's account list changed (``delegation_accounts`` rows): its owner and viewer."""

    def __init__(self, delegation_id: str):
        self.delegation_id = delegation_id
        self.key = ("dlg", delegation_id)

    def resolve(self, conn: Connection) -> list[Event]:
        d = _models().Delegation
        row = conn.execute(select(d.owner_id, d.viewer_id).where(d.id == self.delegation_id)).first()
        return [event("delegations", {}, user(row[0]) + user(row[1]))] if row else []


class TopicEvents(Resolver):
    """A reply or a reaction: the topic (and its list, for replies) to whoever may read the topic."""

    def __init__(self, topic_id: str, with_list: bool):
        self.topic_id = topic_id
        self.with_list = with_list
        self.key = ("topic", topic_id)

    def merge(self, other: Resolver) -> None:
        assert isinstance(other, TopicEvents)
        self.with_list = self.with_list or other.with_list

    def resolve(self, conn: Connection) -> list[Event]:
        t = _models().DiscussionTopic
        row = conn.execute(select(t.scope, t.group_id).where(t.id == self.topic_id)).first()
        if row is None:
            return []
        return topic_events(self.topic_id, row[0], row[1], self.with_list)


class ReportVersionFanout(Resolver):
    """A report version rewritten in place (the close report's data edition is rebuilt every 10 minutes until 15:40,
    ``reports.pipeline.build_data``): its readers refetch when it is the version the report serves."""

    def __init__(self, version_id: str, report_id: str):
        self.version_id = version_id
        self.report_id = report_id
        self.key = ("mrv", version_id)

    def resolve(self, conn: Connection) -> list[Event]:
        r = _models().MarketReport
        row = conn.execute(select(r.kind, r.visibility, r.current_version_id, r.first_published_at)
                           .where(r.id == self.report_id)).first()
        if row is None or row.current_version_id != self.version_id:
            return []
        aud = (ALL,) if row.visibility == "public" and row.first_published_at is not None else (ADMINS,)
        return [event("market.reports", {"report_id": self.report_id, "kind": row.kind}, aud)]


def topic_events(topic_id: str, scope: str, group_id: str | None, with_list: bool = True) -> list[Event]:
    aud = discussion_audience(scope, group_id)
    out = [event("discussions.topic", {"topic_id": topic_id}, aud)]
    if with_list:
        out.append(event("discussions.list", {"scope": scope, "group_id": group_id if scope == "group" else None},
                         aud))
    return out


# -- row handlers ---------------------------------------------------------------------------------------------------
Add = Callable[[Event | Resolver], None]
ME_COLUMNS = frozenset({"display_name", "avatar_url", "preferences", "public_name", "terms_version_accepted",
                        "plan", "plan_until"})
REPORT_PUBLIC_COLUMNS = frozenset({"current_version_id", "state", "first_published_at", "ai_published_at",
                                   "visibility"})


def _ledger(obj: Any, kind: str, ch: set[str], add: Add, account_key: str, *, positions: bool, feed: bool) -> None:
    uid = _v(obj, "user_id")
    if not uid:
        return
    accounts = {_v(obj, account_key)}
    if kind == "dirty" and account_key in ch:
        accounts.add(_old(obj, account_key))
    for acc in sorted(a for a in accounts if a):
        add(event("ledger", {"account_id": acc}, user(uid)))
    add(LedgerFanout(uid, accounts, positions=positions, feed=feed))


def _h_transaction(obj, kind, ch, add):
    if kind == "dirty":
        positions = bool(ch - NON_POSITION_COLUMNS)
        before, after = feed_visible(lambda k: _old(obj, k)), feed_visible(lambda k: _v(obj, k))
        feed = before != after or ((before or after) and bool(ch & FEED_COLUMNS))
    else:  # inserted or deleted
        positions = True
        feed = feed_visible(lambda k: _v(obj, k))
    _ledger(obj, kind, ch, add, "account_id", positions=positions, feed=feed)


def _h_account(obj, kind, ch, add):
    # An account's own columns show in no group (its currency can only change while it has no transactions); the
    # route that deletes one announces its transactions itself (they go with a Core delete). Viewers of a delegation
    # see account names: ``ledger.viewas`` still goes out.
    _ledger(obj, kind, ch, add, "id", positions=False, feed=False)
    if kind == "deleted" and _v(obj, "user_id"):
        add(OwnerDelegations(_v(obj, "user_id")))


def _h_user(obj, kind, ch, add):
    if kind != "dirty":
        return
    uid = _v(obj, "id")
    if ch & ME_COLUMNS:
        add(event("me", {}, user(uid)))
    if ch & {"display_name", "avatar_url"}:
        add(NameFanout(uid))
    if "preferences" in ch:
        old, new = _old(obj, "preferences") or {}, _v(obj, "preferences") or {}
        if old.get("cost_method") != new.get("cost_method"):
            add(event("ledger", {}, user(uid)))
            add(LedgerFanout(uid, feed=False))
        if old.get("daily_briefing") != new.get("daily_briefing"):
            add(event("ai.briefings", {}, user(uid)))


def _h_member(obj, kind, ch, add):
    gid, uid = _v(obj, "group_id"), _v(obj, "user_id")
    if kind == "dirty" and "role" not in ch:
        return
    # A leaver is no longer a member when the audience is resolved: their own tabs are told directly.
    extra = user(uid) if kind == "deleted" else ()
    add(event("group.members", {"group_id": gid}, group(gid) + extra))
    if kind in ("new", "deleted"):
        add(event("groups.list", {}, user(uid)))


def _h_share(obj, kind, ch, add):
    if kind == "new":
        return  # chosen with the membership: the member's own event covers it
    gid = _v(obj, "group_id")
    add(event("group.members", {"group_id": gid}, group(gid)))


def _h_group(obj, kind, ch, add):
    if kind == "dirty" and ch & {"name", "ranking_enabled", "grandfathered_member_cap"}:
        gid = _v(obj, "id")
        add(event("group.meta", {"group_id": gid}, group(gid)))
    # deleted: ``services.groups.purge`` announces it (the memberships are gone by the time this would resolve)


def _h_invite(obj, kind, ch, add):
    gid = _v(obj, "group_id")
    add(event("group.invites", {"group_id": gid}, managers(gid)))


def _h_comment(obj, kind, ch, add):
    gid = _v(obj, "group_id")
    add(event("group.comments", {"group_id": gid, "target": _v(obj, "target")}, group(gid)))


def _h_group_report(obj, kind, ch, add):
    if kind == "dirty" and not ch & {"status", "summary", "facts", "finished_at"}:
        return
    gid = _v(obj, "group_id")
    add(event("group.reports", {"group_id": gid}, group(gid)))


def _h_channel(obj, kind, ch, add):
    gid = _v(obj, "group_id")
    # every member sees the 頻道 tab (status, switches, chat title; GET /groups/{id}/channels needs membership only)
    add(event("group.channels", {"group_id": gid}, group(gid)))
    if kind != "dirty" or ch & {"status", "chat_title"}:
        add(event("group.meta", {"group_id": gid}, group(gid)))  # push targets in the group header


def _h_pass(obj, kind, ch, add):
    groups = {_v(obj, "group_id")} | ({_old(obj, "group_id")} if "group_id" in ch else set())
    for gid in sorted(g for g in groups if g):
        add(event("group.meta", {"group_id": gid}, group(gid)))
    payers = {_v(obj, "payer_id")} | ({_old(obj, "payer_id")} if "payer_id" in ch else set())
    for uid in sorted(p for p in payers if p):
        add(event("me", {}, user(uid)))


def _h_delegation(obj, kind, ch, add):
    add(event("delegations", {}, user(_v(obj, "owner_id")) + user(_v(obj, "viewer_id"))))


def _h_delegation_account(obj, kind, ch, add):
    add(DelegationRef(_v(obj, "delegation_id")))


def _user_topic(topic: str, only_new: bool = False):
    def handler(obj, kind, ch, add):
        if only_new and kind != "new":
            return
        uid = _v(obj, "user_id")
        if uid:
            add(event(topic, {}, user(uid)))

    return handler


def _h_market_summary(obj, kind, ch, add):
    if kind == "new" or ch & {"status", "headline", "points"}:
        add(event("market.overview", {}, (ALL,)))


def _h_market_report(obj, kind, ch, add):
    add(event("admin.reports", {}, (ADMINS,)))
    if kind == "dirty" and ch & REPORT_PUBLIC_COLUMNS:
        aud = (ALL,) if _v(obj, "visibility") == "public" else (ADMINS,)
        add(event("market.reports", {"report_id": _v(obj, "id"), "kind": _v(obj, "kind")}, aud))


def _h_admin_reports(obj, kind, ch, add):
    add(event("admin.reports", {}, (ADMINS,)))


def _h_report_version(obj, kind, ch, add):
    add(event("admin.reports", {}, (ADMINS,)))
    if kind == "dirty" and "payload" in ch and _v(obj, "report_id"):
        add(ReportVersionFanout(_v(obj, "id"), _v(obj, "report_id")))


def _h_report_config(obj, kind, ch, add):
    if "mode" in ch:
        add(event("market.reports", {}, (ALL,)))
    if kind != "dirty" or ch - {"key_state", "updated_at", "updated_by"}:
        add(event("admin.reports", {}, (ADMINS,)))


def _h_topic(obj, kind, ch, add):
    if kind == "dirty" and not ch & {"status", "title", "body", "last_activity_at"}:
        return
    tid, scope, gid = _v(obj, "id"), _v(obj, "scope"), _v(obj, "group_id")
    if kind == "new":
        add(event("discussions.list", {"scope": scope, "group_id": gid if scope == "group" else None},
                  discussion_audience(scope, gid)))
        return
    for e in topic_events(tid, scope, gid):
        add(e)


def _h_reply(obj, kind, ch, add):
    if kind == "dirty" and not ch & {"status", "body"}:
        return
    add(TopicEvents(_v(obj, "topic_id"), with_list=True))


def _h_reaction(obj, kind, ch, add):
    add(TopicEvents(_v(obj, "topic_id"), with_list=False))


def _h_discussion_report(obj, kind, ch, add):
    add(event("admin.discussions", {}, (ADMINS,)))


def _h_suspension(obj, kind, ch, add):
    add(event("admin.discussions", {}, (ADMINS,)))
    add(event("me", {}, user(_v(obj, "user_id"))))  # can_post


HANDLERS: dict[str, Callable[[Any, str, set[str], Add], None]] = {
    "Transaction": _h_transaction,
    "BrokerAccount": _h_account,
    "User": _h_user,
    "RecurringPlan": _user_topic("recurring"),
    "WatchlistItem": _user_topic("watchlist"),
    "Delegation": _h_delegation,
    "DelegationAccount": _h_delegation_account,
    "Group": _h_group,
    "GroupMember": _h_member,
    "GroupShareSetting": _h_share,
    "GroupInvite": _h_invite,
    "GroupComment": _h_comment,
    "GroupReaction": _h_comment,
    "GroupDigest": _h_group_report,
    "GroupDailyReport": _h_group_report,
    "GroupChannel": _h_channel,
    "GroupPass": _h_pass,
    "AiThread": _user_topic("ai.threads"),
    "AiMessage": _user_topic("ai.threads", only_new=True),
    "AiDraft": _user_topic("ai.threads"),
    "AiQuestion": _user_topic("ai.usage", only_new=True),
    "AiUsage": _user_topic("ai.usage", only_new=True),
    "AiBriefing": _user_topic("ai.briefings"),
    "AiMarketSummary": _h_market_summary,
    "MarketReportRead": _user_topic("reports.seen"),
    "MarketReport": _h_market_report,
    "MarketReportVersion": _h_report_version,
    "MarketReportVote": _h_admin_reports,
    "MarketReportConfig": _h_report_config,
    "DiscussionTopic": _h_topic,
    "DiscussionReply": _h_reply,
    "DiscussionReaction": _h_reaction,
    "DiscussionReport": _h_discussion_report,
    "DiscussionSuspension": _h_suspension,
}


# -- session listeners ------------------------------------------------------------------------------------------
def _after_flush(session: Session, _flush_context: Any) -> None:
    if not _enabled():
        return
    try:
        st = _state(session)
        for kind, objs in (("new", session.new), ("dirty", session.dirty), ("deleted", session.deleted)):
            for obj in objs:
                handler = HANDLERS.get(type(obj).__name__)
                if handler is None:
                    continue
                ch = _changed(obj) if kind == "dirty" else set()
                if kind == "dirty" and not ch:
                    continue
                handler(obj, kind, ch, st.add)
    except Exception as exc:
        log.warning("realtime: collecting events failed (%s)", type(exc).__name__)


@contextlib.contextmanager
def _guarded(conn: Connection, postgres: bool) -> Iterator[None]:
    """On PostgreSQL a failed statement aborts the transaction: resolve and notify inside a savepoint so that the
    write itself still commits if announcing it fails."""
    if postgres:
        with conn.begin_nested():
            yield
    else:
        yield


def resolve(conn: Connection, items: list[Event | Resolver], origin: tuple[str | None, str | None] | None
            ) -> list[Event]:
    """Expand resolvers, turn symbolic audiences into users, merge duplicates (in first-seen order)."""
    members: dict[tuple[str, bool], list[str]] = {}

    def users_of(gid: str, managers_only: bool) -> list[str]:
        key = (gid, managers_only)
        if key not in members:
            gm = _models().GroupMember
            q = select(gm.user_id).where(gm.group_id == gid)
            if managers_only:
                q = q.where(gm.role.in_(("owner", "admin")))
            members[key] = list(conn.execute(q.order_by(gm.user_id)).scalars())
        return members[key]

    expanded: list[Event] = []
    for item in items:
        expanded.extend(item.resolve(conn) if isinstance(item, Resolver) else [item])
    merged: dict[tuple, Event] = {}
    ou, o = origin or (None, None)
    for ev in expanded:
        to: list[str] = []
        for a in ev.to:
            if a.startswith("g:"):
                to.extend(f"u:{u}" for u in users_of(a[2:], False))
            elif a.startswith("gm:"):
                to.extend(f"u:{u}" for u in users_of(a[3:], True))
            else:
                to.append(a)
        if not to and not ev.is_op:
            continue
        ev = Event(ev.topic, ev.data, (ALL,) if ALL in to else tuple(dict.fromkeys(to)), ev.echo).with_origin(ou, o)
        seen = merged.get(ev.merge_key())
        if seen is None:
            merged[ev.merge_key()] = ev
        elif ALL not in seen.to:
            seen.to = (ALL,) if ALL in ev.to else tuple(dict.fromkeys(seen.to + ev.to))
    return list(merged.values())


def _before_commit(session: Session) -> None:
    if not _enabled() or session.in_nested_transaction():
        return
    st = session.info.get(STATE_KEY)
    if st is None and not session.new and not session.dirty and not session.deleted:
        return
    session.flush()  # the commit's own flush comes after this hook: collect its rows now
    st = session.info.get(STATE_KEY)
    if st is None or not st.items:
        return
    items = list(st.items)
    st.clear()
    try:
        conn = session.connection()
        postgres = conn.dialect.name == "postgresql"
        with _guarded(conn, postgres):
            events = resolve(conn, items, session.info.get(ORIGIN_KEY))
            if postgres:
                payloads = [p for ev in events for p in split_for_notify(ev)]
                if payloads:
                    conn.execute(text("SELECT pg_notify(:channel, p) FROM unnest(CAST(:payloads AS text[])) AS p"),
                                 {"channel": CHANNEL, "payloads": payloads})
            else:
                st.ready.extend(events)
    except Exception as exc:
        log.warning("realtime: resolving events failed (%s)", type(exc).__name__)


def _after_commit(session: Session) -> None:
    st = session.info.get(STATE_KEY)
    if st is None or not st.ready:
        return
    ready = list(st.ready)
    st.ready.clear()
    bus.publish_local(ready)


def _after_rollback(session: Session) -> None:
    st = session.info.get(STATE_KEY)
    if st is not None:
        st.clear()
        st.ready.clear()


def _after_transaction_end(session: Session, transaction: Any) -> None:
    """A transaction that ended without a commit (``close()``, a failed commit) leaves nothing for the next one."""
    if transaction.parent is None:
        _after_rollback(session)


def install() -> None:
    """Watch every ``Session`` (idempotent; ``forliosa.db`` calls it when the session factory is made)."""
    global _installed
    if _installed:
        return
    sa_event.listen(Session, "after_flush", _after_flush)
    sa_event.listen(Session, "before_commit", _before_commit)
    sa_event.listen(Session, "after_commit", _after_commit)
    sa_event.listen(Session, "after_rollback", _after_rollback)
    sa_event.listen(Session, "after_transaction_end", _after_transaction_end)
    _installed = True
