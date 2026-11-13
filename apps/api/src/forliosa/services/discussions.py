"""Discussion threads (docs/api-contract.md 「討論串…」): topics, replies, reactions, reports and site moderation.

* **Scope**: ``public`` (anyone reads, without login) or ``group`` (members only; everyone else gets 404, as in M5).
  Every endpoint acts as the signed-in user themselves, never as a delegation's owner.
* **Authors**: public content shows the author's *public name* only — never the user id, display name, avatar or
  email. Group content shows the display name, user id and avatar, as the group feed does; an author who left the
  group is 「已離開的成員」 without identity. A deleted account leaves its content with ``name: null``.
* **Hidden** (site admins, public content only): a hidden topic is not listed and opens with ``body: null``; a hidden
  reply stays in place with ``body: null``. The author and site admins still get the body.
* **Rate limits** are counted from ``discussion_post_log`` rows (no in-memory state), so they hold across processes
  and deleting a post does not give its slot back. Every number is in the constants below; the clock is injectable
  (:func:`set_clock`).
* The AI never reads any of this: no AI tool queries these tables.
"""

from __future__ import annotations

import base64
import binascii
import math
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from forliosa.api.errors import ApiError, not_found, unprocessable
from forliosa.config import get_settings
from forliosa.ids import new_id
from forliosa.marketdata.base import code_of_symbol
from forliosa.marketdata.service import MarketData
from forliosa.models import (
    DiscussionPostLog,
    DiscussionReaction,
    DiscussionReply,
    DiscussionReport,
    DiscussionSuspension,
    DiscussionTopic,
    DiscussionTopicSymbol,
    Group,
    GroupMember,
    User,
)
from forliosa.services.groups import MANAGERS
from forliosa.services.sharing import LEFT_MEMBER, REACTION_EMOJI
from forliosa.textsafe import name_key, one_line
from forliosa.timeutil import iso_utc, now_utc


# -- limits: every number of this feature ------------------------------------------------------------------
@dataclass(frozen=True)
class RateLimit:
    count: int
    window: timedelta  # rolling


# (scope, kind) -> posts per rolling window, per user.
RATE_LIMITS: dict[tuple[str, str], RateLimit] = {
    ("public", "topic"): RateLimit(5, timedelta(days=1)),
    ("public", "reply"): RateLimit(30, timedelta(hours=1)),
    ("group", "topic"): RateLimit(20, timedelta(days=1)),
    ("group", "reply"): RateLimit(120, timedelta(hours=1)),
}
PUBLIC_POST_GAP = timedelta(seconds=10)  # between any two public posts of one user
POST_LOG_KEEP = max(limit.window for limit in RATE_LIMITS.values())  # older log rows are no longer counted
PUBLIC_NAME_COOLDOWN = timedelta(days=7)  # one public name per 7 days (the first choice counts)
PERMANENT = datetime(9999, 12, 31, tzinfo=UTC)  # ``until`` of a permanent suspension
EXCERPT_CHARS = 120

_clock: Callable[[], datetime] = now_utc


def set_clock(clock: Callable[[], datetime] | None) -> None:
    """Tests: replace the clock behind rate limits, cooldowns, suspensions and timestamps (``None`` restores it)."""
    global _clock
    _clock = clock or now_utc


def now() -> datetime:
    return _clock()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# -- who is looking -------------------------------------------------------------------------------------------
@dataclass
class Viewer:
    user: User | None
    is_admin: bool
    roles: dict[str, str]  # my groups -> my role

    @property
    def user_id(self) -> str | None:
        return self.user.id if self.user is not None else None

    def is_author(self, author_id: str | None) -> bool:
        return author_id is not None and author_id == self.user_id


def is_site_admin(user: User | None) -> bool:
    """``ADMIN_EMAILS`` (case-insensitive). Site admins moderate public content only."""
    if user is None or not user.email:
        return False
    return user.email.strip().lower() in {e.strip().lower() for e in get_settings().admin_emails}


def require_admin(user: User) -> None:
    if not is_site_admin(user):
        raise not_found()


def viewer_of(db: Session, user: User | None) -> Viewer:
    roles: dict[str, str] = {}
    if user is not None:
        roles = {gid: role for gid, role in db.execute(
            select(GroupMember.group_id, GroupMember.role).where(GroupMember.user_id == user.id))}
    return Viewer(user, is_site_admin(user), roles)


def _login_required() -> ApiError:
    return ApiError(401, "unauthorized", "請先登入")


# -- public name and suspension (also in GET /me) ------------------------------------------------------------------
def active_suspension(db: Session, user_id: str, at: datetime | None = None) -> DiscussionSuspension | None:
    s = DiscussionSuspension
    return db.scalar(select(s).where(s.user_id == user_id, s.lifted_at.is_(None), s.until > (at or now()))
                     .order_by(s.until.desc()).limit(1))


def me_fields(db: Session, user: User) -> dict[str, Any]:
    suspension = active_suspension(db, user.id)
    return {"public_name": user.public_name, "is_admin": is_site_admin(user),
            "public_posting_suspended_until": iso_utc(suspension.until) if suspension else None}


def set_public_name(db: Session, user: User, name: str) -> None:
    """Choose or change the public name (``name`` is already validated: 2–20 characters, one line, no reserved
    word). Unique by :func:`textsafe.name_key`; one write per ``PUBLIC_NAME_COOLDOWN``. Old posts show the new name."""
    if user.public_name == name:
        return
    at = now()
    if user.public_name_changed_at is not None:
        wait = _aware(user.public_name_changed_at) + PUBLIC_NAME_COOLDOWN - at
        if wait > timedelta(0):
            days = max(1, math.ceil(wait.total_seconds() / 86400))
            raise ApiError(409, "public_name_cooldown", f"公開暱稱 7 天內只能改一次，{days} 天後可以再改",
                           extra={"retry_after_days": days})
    taken = ApiError(409, "public_name_taken", "這個公開暱稱已經有人使用")
    key = name_key(name)
    if db.scalar(select(User.id).where(User.public_name_key == key, User.id != user.id)) is not None:
        raise taken
    user.public_name, user.public_name_key, user.public_name_changed_at = name, key, at
    try:
        db.commit()
    except IntegrityError as exc:  # someone took it between the check and the write
        db.rollback()
        raise taken from exc


# -- posting guards: suspension, public name, rate limits ----------------------------------------------------
def _check_rate(db: Session, user_id: str, scope: str, kind: str, at: datetime) -> None:
    """429 ``rate_limited`` (with ``retry_after_seconds``) when this post would exceed the window of its scope and
    kind, or — public — comes within ``PUBLIC_POST_GAP`` of the user's last public post."""
    log = DiscussionPostLog
    # One user's posts are checked one at a time (a row lock on PostgreSQL; SQLite has one writer anyway).
    db.execute(select(User.id).where(User.id == user_id).with_for_update())
    limit = RATE_LIMITS[(scope, kind)]
    times = [_aware(t) for t in db.scalars(
        select(log.created_at).where(log.user_id == user_id, log.scope == scope, log.kind == kind,
                                     log.created_at > at - limit.window).order_by(log.created_at))]
    wait = timedelta(0)
    if len(times) >= limit.count:  # free again when enough of the oldest posts have left the window
        wait = times[len(times) - limit.count] + limit.window - at
    if scope == "public":
        last = db.scalar(select(log.created_at).where(log.user_id == user_id, log.scope == "public")
                         .order_by(log.created_at.desc()).limit(1))
        if last is not None:
            wait = max(wait, _aware(last) + PUBLIC_POST_GAP - at)
    if wait > timedelta(0):
        seconds = max(1, math.ceil(wait.total_seconds()))
        raise ApiError(429, "rate_limited", f"發言太頻繁，請 {seconds} 秒後再試",
                       extra={"retry_after_seconds": seconds}, headers={"Retry-After": str(seconds)})


def _guard_post(db: Session, user: User, scope: str, kind: str, at: datetime) -> None:
    if scope == "public":
        suspension = active_suspension(db, user.id, at)
        if suspension is not None:
            raise ApiError(403, "posting_suspended", "你的公開發言已被站方暫停",
                           extra={"until": iso_utc(suspension.until)})
        if not user.public_name:
            raise ApiError(409, "public_name_required", "發公開內容前要先設定公開暱稱")
    _check_rate(db, user.id, scope, kind, at)


def _log_post(db: Session, user_id: str, scope: str, kind: str, at: datetime) -> None:
    log = DiscussionPostLog
    db.execute(delete(log).where(log.user_id == user_id, log.created_at <= at - POST_LOG_KEEP))
    db.add(log(id=new_id("dpl"), user_id=user_id, scope=scope, kind=kind, created_at=at))


# -- cursors ------------------------------------------------------------------------------------------------
def _encode_cursor(ts: datetime, row_id: str) -> str:
    raw = f"{_aware(ts).astimezone(UTC).isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        ts, row_id = raw.split("|", 1)
        return _aware(datetime.fromisoformat(ts)), row_id
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise unprocessable("分頁游標無效") from exc


# -- access ---------------------------------------------------------------------------------------------------
def _visible_topic(db: Session, viewer: Viewer, topic_id: str) -> DiscussionTopic:
    """The topic if the viewer may see it: public → anyone; group → members. Otherwise 404 (existence is not
    revealed, also not to someone without a session)."""
    topic = db.get(DiscussionTopic, topic_id)
    if topic is None or (topic.scope == "group" and topic.group_id not in viewer.roles):
        raise not_found("找不到這個主題")
    return topic


def _target(db: Session, viewer: Viewer, target: str) -> tuple[str, DiscussionTopic, DiscussionReply | None]:
    """``topic:<id>`` | ``reply:<id>`` → (kind, its topic, the reply); 404 unless the viewer may see it."""
    kind, _, target_id = target.partition(":")
    if kind == "topic":
        return kind, _visible_topic(db, viewer, target_id), None
    reply = db.get(DiscussionReply, target_id) if kind == "reply" else None
    if reply is None:
        raise not_found("找不到這則內容")
    return kind, _visible_topic(db, viewer, reply.topic_id), reply


def _can_delete(viewer: Viewer, topic: DiscussionTopic, author_id: str | None) -> bool:
    """The author; in a group also its owner and admins. Site admins never delete public content (they hide it)."""
    if viewer.user is None:
        return False
    manages = topic.scope == "group" and viewer.roles.get(topic.group_id or "") in MANAGERS
    return viewer.is_author(author_id) or manages


def _can_report(viewer: Viewer, topic: DiscussionTopic, author_id: str | None) -> bool:
    return topic.scope == "public" and viewer.user is not None and not viewer.is_author(author_id)


def _body_for(viewer: Viewer, topic: DiscussionTopic, status: str, author_id: str | None, body: str) -> str | None:
    if status != "hidden" or viewer.is_author(author_id) or (viewer.is_admin and topic.scope == "public"):
        return body
    return None


# -- output -----------------------------------------------------------------------------------------------------
@dataclass
class _Refs:
    users: dict[str, User]
    groups: dict[str, Group]
    members: set[tuple[str, str]]  # (group_id, user_id): authors who are still members


def _refs(db: Session, topics: Iterable[DiscussionTopic], author_ids: Iterable[str | None]) -> _Refs:
    topics = list(topics)
    user_ids = {u for u in author_ids if u} | {t.user_id for t in topics if t.user_id}
    group_ids = {t.group_id for t in topics if t.scope == "group" and t.group_id}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}
    groups = {g.id: g for g in db.scalars(select(Group).where(Group.id.in_(group_ids)))} if group_ids else {}
    members: set[tuple[str, str]] = set()
    if group_ids and user_ids:
        members = {(gid, uid) for gid, uid in db.execute(
            select(GroupMember.group_id, GroupMember.user_id)
            .where(GroupMember.group_id.in_(group_ids), GroupMember.user_id.in_(user_ids)))}
    return _Refs(users, groups, members)


def _author(viewer: Viewer, refs: _Refs, topic: DiscussionTopic, author_id: str | None) -> dict[str, Any]:
    user = refs.users.get(author_id) if author_id else None
    if topic.scope == "public":  # the public name only: no user id, display name, avatar or email
        return {"name": user.public_name if user else None, "is_you": user is not None and viewer.is_author(user.id)}
    if user is None:
        return {"name": None, "is_you": False, "user_id": None, "avatar_url": None}
    if (topic.group_id, user.id) not in refs.members:
        return {"name": LEFT_MEMBER, "is_you": False, "user_id": None, "avatar_url": None}
    return {"name": user.display_name, "is_you": viewer.is_author(user.id), "user_id": user.id,
            "avatar_url": user.avatar_url}


def _symbols_of(db: Session, md: MarketData, topic_ids: list[str]) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = defaultdict(list)
    if not topic_ids:
        return out
    ts = DiscussionTopicSymbol
    for topic_id, symbol in db.execute(select(ts.topic_id, ts.symbol).where(ts.topic_id.in_(topic_ids))
                                       .order_by(ts.topic_id, ts.position, ts.symbol)):
        info = md.instrument(symbol)
        out[topic_id].append({"symbol": symbol, "code": info.code if info else code_of_symbol(symbol),
                              "name": info.name if info else symbol})
    return out


def _reply_counts(db: Session, topic_ids: list[str]) -> dict[str, int]:
    if not topic_ids:
        return {}
    r = DiscussionReply
    return {tid: n for tid, n in db.execute(
        select(r.topic_id, func.count()).where(r.topic_id.in_(topic_ids)).group_by(r.topic_id))}


def _reactions(db: Session, kind: str, ids: list[str], me_id: str | None) -> dict[str, list[dict[str, Any]]]:
    if not ids:
        return {}
    rx = DiscussionReaction
    tally: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for target_id, emoji, user_id in db.execute(
            select(rx.target_id, rx.emoji, rx.user_id).where(rx.target_kind == kind, rx.target_id.in_(ids))):
        cell = tally[target_id][emoji]
        cell[0] += 1
        cell[1] |= me_id is not None and user_id == me_id
    return {tid: [{"emoji": e, "count": cells[e][0], "mine": bool(cells[e][1])} for e in REACTION_EMOJI if e in cells]
            for tid, cells in tally.items()}


def _topic_base(viewer: Viewer, refs: _Refs, topic: DiscussionTopic, symbols: list[dict[str, str]],
                reply_count: int) -> dict[str, Any]:
    group = refs.groups.get(topic.group_id) if topic.scope == "group" and topic.group_id else None
    return {
        "id": topic.id, "scope": topic.scope, "group": {"id": group.id, "name": group.name} if group else None,
        "title": topic.title, "symbols": symbols, "author": _author(viewer, refs, topic, topic.user_id),
        "created_at": iso_utc(topic.created_at), "last_activity_at": iso_utc(topic.last_activity_at),
        "reply_count": reply_count, "status": topic.status, "mine": viewer.is_author(topic.user_id),
    }


def topic_out(db: Session, md: MarketData, viewer: Viewer, topic: DiscussionTopic) -> dict[str, Any]:
    refs = _refs(db, [topic], [])
    return {
        **_topic_base(viewer, refs, topic, _symbols_of(db, md, [topic.id]).get(topic.id, []),
                      _reply_counts(db, [topic.id]).get(topic.id, 0)),
        "body": _body_for(viewer, topic, topic.status, topic.user_id, topic.body),
        "reactions": _reactions(db, "topic", [topic.id], viewer.user_id).get(topic.id, []),
        "can_delete": _can_delete(viewer, topic, topic.user_id),
        "can_report": _can_report(viewer, topic, topic.user_id),
        "can_reply": viewer.user is not None and topic.status == "visible",
    }


def _reply_out(viewer: Viewer, refs: _Refs, topic: DiscussionTopic, reply: DiscussionReply,
               reactions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": reply.id, "topic_id": reply.topic_id,
        "body": _body_for(viewer, topic, reply.status, reply.user_id, reply.body),
        "author": _author(viewer, refs, topic, reply.user_id), "created_at": iso_utc(reply.created_at),
        "status": reply.status, "reactions": reactions, "mine": viewer.is_author(reply.user_id),
        "can_delete": _can_delete(viewer, topic, reply.user_id),
        "can_report": _can_report(viewer, topic, reply.user_id),
    }


# -- topics -----------------------------------------------------------------------------------------------------
def list_topics(db: Session, md: MarketData, user: User | None, scope: str, group_id: str | None, symbol: str | None,
                mine: bool, sort: str, limit: int, cursor: str | None) -> dict[str, Any]:
    """Visible topics, newest first (``sort`` active: last activity; new: creation). ``public`` needs no session;
    ``group`` (one of my groups), ``all`` (public + every group I am in) and ``mine`` do."""
    if user is None and (scope != "public" or mine):
        raise _login_required()
    viewer = viewer_of(db, user)
    t = DiscussionTopic
    stmt = select(t).where(t.status == "visible")
    if scope == "public":
        stmt = stmt.where(t.scope == "public")
    elif scope == "group":
        if not group_id:
            raise unprocessable("請指定群組")
        if group_id not in viewer.roles:
            raise not_found("找不到群組")
        stmt = stmt.where(t.scope == "group", t.group_id == group_id)
    else:
        stmt = stmt.where(or_(t.scope == "public", and_(t.scope == "group", t.group_id.in_(sorted(viewer.roles)))))
    if symbol and symbol.strip():
        resolved = md.resolve(symbol) or symbol.strip().upper()
        ts = DiscussionTopicSymbol
        stmt = stmt.where(t.id.in_(select(ts.topic_id).where(ts.symbol == resolved)))
    if mine and user is not None:
        stmt = stmt.where(t.user_id == user.id)
    column = t.last_activity_at if sort == "active" else t.created_at
    if cursor:
        before, before_id = _decode_cursor(cursor)
        stmt = stmt.where(or_(column < before, and_(column == before, t.id < before_id)))
    rows = list(db.scalars(stmt.order_by(column.desc(), t.id.desc()).limit(limit + 1)))
    page = rows[:limit]
    ids = [x.id for x in page]
    refs = _refs(db, page, [])
    symbols, counts = _symbols_of(db, md, ids), _reply_counts(db, ids)
    items = [{**_topic_base(viewer, refs, x, symbols.get(x.id, []), counts.get(x.id, 0)),
              "excerpt": one_line(x.body)[:EXCERPT_CHARS]} for x in page]
    last = page[-1] if len(rows) > limit else None
    return {"items": items,
            "next_cursor": _encode_cursor(last.last_activity_at if sort == "active" else last.created_at, last.id)
            if last is not None else None}


def _resolve_symbols(md: MarketData, texts: list[str]) -> list[str]:
    out: list[str] = []
    for text in texts:
        info = md.instrument(text)
        if info is None:
            raise unprocessable(f"找不到商品：{text}", code="unknown_symbol")
        if info.symbol not in out:
            out.append(info.symbol)
    return out


def create_topic(db: Session, md: MarketData, me: User, scope: str, group_id: str | None, title: str, body: str,
                 symbols: list[str]) -> dict[str, Any]:
    viewer = viewer_of(db, me)
    if scope == "group":
        if not group_id:
            raise unprocessable("群組範圍的主題要指定群組")
        if group_id not in viewer.roles:
            raise not_found("找不到群組")
    elif group_id:
        raise unprocessable("公開主題不能指定群組")
    resolved = _resolve_symbols(md, symbols)
    at = now()
    _guard_post(db, me, scope, "topic", at)
    topic = DiscussionTopic(id=new_id("top"), scope=scope, group_id=group_id if scope == "group" else None,
                            user_id=me.id, title=title, body=body, status="visible", created_at=at,
                            last_activity_at=at)
    db.add(topic)
    db.flush()
    db.add_all(DiscussionTopicSymbol(topic_id=topic.id, symbol=s, position=i) for i, s in enumerate(resolved))
    _log_post(db, me.id, scope, "topic", at)
    db.commit()
    return topic_out(db, md, viewer, topic)


def get_topic(db: Session, md: MarketData, user: User | None, topic_id: str) -> dict[str, Any]:
    viewer = viewer_of(db, user)
    return topic_out(db, md, viewer, _visible_topic(db, viewer, topic_id))


def _purge_topics(db: Session, topic_ids: list[str]) -> None:
    """Topics with their replies, reactions, reports and tags (no commit)."""
    if not topic_ids:
        return
    for model in (DiscussionReaction, DiscussionReport, DiscussionReply, DiscussionTopicSymbol):
        db.execute(delete(model).where(model.topic_id.in_(topic_ids)))
    db.execute(delete(DiscussionTopic).where(DiscussionTopic.id.in_(topic_ids)))


def purge_group(db: Session, group_id: str) -> None:
    """Everything discussed in a group that is being deleted (no commit)."""
    _purge_topics(db, list(db.scalars(select(DiscussionTopic.id).where(DiscussionTopic.group_id == group_id))))


def delete_topic(db: Session, me: User, topic_id: str) -> None:
    viewer = viewer_of(db, me)
    topic = _visible_topic(db, viewer, topic_id)
    if not _can_delete(viewer, topic, topic.user_id):
        raise ApiError(403, "forbidden", "只有作者或群組管理員可以刪除主題")
    _purge_topics(db, [topic.id])
    db.commit()


# -- replies ----------------------------------------------------------------------------------------------------
def list_replies(db: Session, user: User | None, topic_id: str, limit: int, cursor: str | None) -> dict[str, Any]:
    """Oldest first. A hidden reply stays in its place with ``body: null``."""
    viewer = viewer_of(db, user)
    topic = _visible_topic(db, viewer, topic_id)
    r = DiscussionReply
    stmt = select(r).where(r.topic_id == topic.id)
    if cursor:
        after, after_id = _decode_cursor(cursor)
        stmt = stmt.where(or_(r.created_at > after, and_(r.created_at == after, r.id > after_id)))
    rows = list(db.scalars(stmt.order_by(r.created_at, r.id).limit(limit + 1)))
    page = rows[:limit]
    refs = _refs(db, [topic], [x.user_id for x in page])
    reactions = _reactions(db, "reply", [x.id for x in page], viewer.user_id)
    return {"items": [_reply_out(viewer, refs, topic, x, reactions.get(x.id, [])) for x in page],
            "next_cursor": _encode_cursor(page[-1].created_at, page[-1].id) if len(rows) > limit else None}


def create_reply(db: Session, me: User, topic_id: str, body: str) -> dict[str, Any]:
    viewer = viewer_of(db, me)
    topic = _visible_topic(db, viewer, topic_id)
    if topic.status == "hidden":
        raise ApiError(409, "topic_hidden", "這個主題已被站方隱藏，不能回覆")
    at = now()
    _guard_post(db, me, topic.scope, "reply", at)
    reply = DiscussionReply(id=new_id("rep"), topic_id=topic.id, user_id=me.id, body=body, status="visible",
                            created_at=at)
    db.add(reply)
    if _aware(topic.last_activity_at) < at:
        topic.last_activity_at = at
    _log_post(db, me.id, topic.scope, "reply", at)
    db.commit()
    return _reply_out(viewer, _refs(db, [topic], [me.id]), topic, reply, [])


def delete_reply(db: Session, me: User, reply_id: str) -> None:
    viewer = viewer_of(db, me)
    _kind, topic, reply = _target(db, viewer, f"reply:{reply_id}")
    assert reply is not None
    if not _can_delete(viewer, topic, reply.user_id):
        raise ApiError(403, "forbidden", "只有作者或群組管理員可以刪除回覆")
    for model in (DiscussionReaction, DiscussionReport):
        db.execute(delete(model).where(model.target_kind == "reply", model.target_id == reply.id))
    db.delete(reply)
    db.flush()
    newest = db.scalar(select(func.max(DiscussionReply.created_at)).where(DiscussionReply.topic_id == topic.id))
    topic.last_activity_at = max(_aware(newest), _aware(topic.created_at)) if newest else topic.created_at
    db.commit()


# -- reactions ------------------------------------------------------------------------------------------------
def put_reaction(db: Session, me: User, target: str, emoji: str) -> None:
    kind, topic, reply = _target(db, viewer_of(db, me), target)
    target_id = reply.id if reply is not None else topic.id
    if db.get(DiscussionReaction, (kind, target_id, me.id, emoji)) is not None:
        return
    db.add(DiscussionReaction(target_kind=kind, target_id=target_id, user_id=me.id, emoji=emoji, topic_id=topic.id,
                              created_at=now()))
    try:
        db.commit()
    except IntegrityError:  # the same reaction arrived twice at once: it counts once
        db.rollback()


def delete_reaction(db: Session, me: User, target: str, emoji: str) -> None:
    kind, topic, reply = _target(db, viewer_of(db, me), target)
    rx = DiscussionReaction
    db.execute(delete(rx).where(rx.target_kind == kind, rx.target_id == (reply.id if reply is not None else topic.id),
                                rx.user_id == me.id, rx.emoji == emoji))
    db.commit()


# -- reports (public content only) ----------------------------------------------------------------------------
def report(db: Session, me: User, target: str, reason: str, note: str | None) -> None:
    """One report per user per target (a repeat is ignored). Group content cannot be reported (its group's admins
    delete it; site admins never see it), nor can one's own content."""
    kind, topic, reply = _target(db, viewer_of(db, me), target)
    if topic.scope != "public":
        raise unprocessable("群組裡的內容不能檢舉，請找群組管理員處理")
    content = reply if reply is not None else topic
    if content.user_id == me.id:
        raise unprocessable("不能檢舉自己的內容")
    rp = DiscussionReport
    if db.scalar(select(rp.id).where(rp.target_kind == kind, rp.target_id == content.id,
                                     rp.reporter_id == me.id)) is not None:
        return
    db.add(rp(id=new_id("rpt"), target_kind=kind, target_id=content.id, topic_id=topic.id, reporter_id=me.id,
              reason=reason, note=note, status="open", created_at=now()))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


# -- site admin: reports, hide / unhide, suspensions (public content only; no email or user id leaves) -------
def _public_target(db: Session, target: str) -> tuple[str, DiscussionTopic, DiscussionReply | None]:
    """A piece of *public* content; group content does not exist for site admins (404)."""
    kind, _, target_id = target.partition(":")
    reply = db.get(DiscussionReply, target_id) if kind == "reply" else None
    topic_id = reply.topic_id if reply is not None else (target_id if kind == "topic" else None)
    topic = db.get(DiscussionTopic, topic_id) if topic_id else None
    if topic is None or topic.scope != "public":
        raise not_found("找不到這則內容")
    return kind, topic, reply


def admin_reports(db: Session, status: str, limit: int, cursor: str | None) -> dict[str, Any]:
    """Reports grouped by target, the most recently reported first. ``open``: targets with an unhandled report;
    ``resolved``: targets whose reports were all handled (hidden or dismissed)."""
    rp = DiscussionReport
    open_count = func.sum(case((rp.status == "open", 1), else_=0))
    first, last = func.min(rp.created_at), func.max(rp.created_at)
    stmt = (select(rp.target_kind, rp.target_id, func.count(), open_count, first, last)
            .group_by(rp.target_kind, rp.target_id)
            .having(open_count > 0 if status == "open" else open_count == 0))
    if cursor:
        before, before_id = _decode_cursor(cursor)
        stmt = stmt.having(or_(last < before, and_(last == before, rp.target_id < before_id)))
    rows = db.execute(stmt.order_by(last.desc(), rp.target_id.desc()).limit(limit + 1)).all()
    page = rows[:limit]
    topic_ids = [tid for kind, tid, *_ in page if kind == "topic"]
    reply_ids = [tid for kind, tid, *_ in page if kind == "reply"]
    replies = ({r.id: r for r in db.scalars(select(DiscussionReply).where(DiscussionReply.id.in_(reply_ids)))}
               if reply_ids else {})
    topic_ids += [r.topic_id for r in replies.values()]
    topics = ({t.id: t for t in db.scalars(select(DiscussionTopic).where(DiscussionTopic.id.in_(topic_ids)))}
              if topic_ids else {})
    authors = {c.user_id for c in (*topics.values(), *replies.values()) if c.user_id}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(authors)))} if authors else {}
    reasons: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    notes: dict[str, list[str]] = defaultdict(list)
    ids = [tid for _kind, tid, *_ in page]
    if ids:
        for target_id, reason, note in db.execute(
                select(rp.target_id, rp.reason, rp.note).where(rp.target_id.in_(ids)).order_by(rp.created_at, rp.id)):
            reasons[target_id][reason] += 1
            if note:
                notes[target_id].append(note)
    items = []
    for kind, target_id, total, open_n, first_at, _last_at in page:
        reply = replies.get(target_id) if kind == "reply" else None
        topic = topics.get(reply.topic_id if reply is not None else target_id) if (kind == "topic" or reply) else None
        if topic is None or topic.scope != "public":  # reports go with their content; never group content
            continue
        content = reply if reply is not None else topic
        author = users.get(content.user_id) if content.user_id else None
        text = reply.body if reply is not None else f"{topic.title}｜{topic.body}"
        items.append({
            "target": f"{kind}:{target_id}", "kind": kind, "excerpt": one_line(text)[:EXCERPT_CHARS],
            "author_name": author.public_name if author else None, "topic_id": topic.id, "report_count": total,
            "reasons": dict(reasons[target_id]), "notes": notes[target_id], "first_reported_at": iso_utc(first_at),
            "status": "open" if open_n else "resolved", "hidden": content.status == "hidden",
        })
    return {"items": items,
            "next_cursor": _encode_cursor(page[-1][5], page[-1][1]) if len(rows) > limit else None}


def moderate(db: Session, target: str, action: str) -> None:
    """``hide``: hidden, its open reports resolved. ``unhide``: visible again. ``dismiss``: reports resolved only."""
    kind, topic, reply = _public_target(db, target)
    content = reply if reply is not None else topic
    if action == "hide":
        content.status = "hidden"
    elif action == "unhide":
        content.status = "visible"
    if action in ("hide", "dismiss"):
        rp = DiscussionReport
        db.execute(update(rp).where(rp.target_kind == kind, rp.target_id == content.id, rp.status == "open")
                   .values(status="resolved", resolved_at=now()))
    db.commit()


def _suspension_out(s: DiscussionSuspension, user: User | None) -> dict[str, Any]:
    return {"id": s.id, "public_name": user.public_name if user else None, "until": iso_utc(s.until),
            "reason": s.reason, "created_at": iso_utc(s.created_at)}


def list_suspensions(db: Session) -> list[dict[str, Any]]:
    """Suspensions in force now (not lifted, not expired), newest first."""
    s = DiscussionSuspension
    rows = db.execute(select(s, User).join(User, User.id == s.user_id)
                      .where(s.lifted_at.is_(None), s.until > now()).order_by(s.created_at.desc(), s.id.desc())).all()
    return [_suspension_out(row, user) for row, user in rows]


def create_suspension(db: Session, admin: User, target: str, days: int | None, reason: str | None) -> dict[str, Any]:
    """Suspend the public posting of the author of ``target`` for ``days`` (``None``: permanently). The author is
    named by a piece of their public content, never by id or email. Replaces a suspension already in force."""
    _kind, topic, reply = _public_target(db, target)
    author_id = (reply if reply is not None else topic).user_id
    author = db.get(User, author_id) if author_id else None
    if author is None:
        raise unprocessable("這則內容的作者帳號已刪除")
    at = now()
    s = active_suspension(db, author.id, at)
    if s is None:
        s = DiscussionSuspension(id=new_id("sus"), user_id=author.id, created_at=at)
        db.add(s)
    s.until = PERMANENT if days is None else at + timedelta(days=days)
    s.reason, s.created_by = reason, admin.id
    db.commit()
    return _suspension_out(s, author)


def lift_suspension(db: Session, suspension_id: str) -> None:
    s = db.get(DiscussionSuspension, suspension_id)
    if s is None:
        raise not_found("找不到這筆停權")
    if s.lifted_at is None:
        s.lifted_at = now()
        db.commit()
