"""The signed-in user's own account: export of their data, account deletion, the terms version they agreed to.

Contract: docs/api-contract.md 「帳號：匯出資料、刪除帳號、條款版本」. Everything here acts on the signed-in person
themselves, never on a delegation's owner.

* :func:`export_user` — one JSON-serialisable object with only this account's data. No other member's content, no
  market data, no secrets (sessions, channel webhooks, Telegram link codes), no reports or suspensions.
* :func:`delete_user` — removes the account in one transaction. Posts the user wrote in groups and discussions stay,
  with no author (the columns are ``ON DELETE SET NULL``); AI usage rows stay as counts with no user. Groups the user
  owns go to the earliest admin, else the earliest other member, else are deleted with their content. A public-posting
  suspension still running is carried over by a keyed hash of the login identity (:func:`identity_hash`), so deleting
  and re-registering does not lift it.
* :func:`terms_fields` / :func:`accept_terms` — ``TERMS_VERSION``.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections import deque
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, inspect, or_, select
from sqlalchemy.orm import Session

from forliosa.api.errors import ApiError
from forliosa.config import get_settings
from forliosa.ids import new_id
from forliosa.models import (
    AiBriefing,
    AiDraft,
    AiMessage,
    AiThread,
    AutoDividendSkip,
    BrokerAccount,
    Delegation,
    DelegationAccount,
    DiscussionPostLog,
    DiscussionReaction,
    DiscussionReply,
    DiscussionReport,
    DiscussionSuspension,
    DiscussionSuspensionCarryover,
    DiscussionTopic,
    DiscussionTopicSymbol,
    Group,
    GroupComment,
    GroupMember,
    GroupReaction,
    GroupShareSetting,
    HoldingSnapshot,
    NotificationOutbox,
    RecurringPlan,
    TelegramLinkCode,
    Transaction,
    User,
    UserIdentity,
    UserSession,
    WatchlistItem,
)
from forliosa.services import discussions, groups
from forliosa.services.ledger_io import preferences_of
from forliosa.textsafe import one_line
from forliosa.timeutil import iso_utc, now_utc

EXPORT_FORMAT_VERSION = 1
DELETE_CONFIRMATION = "刪除我的帳號"
EXPORT_LIMIT = 5  # exports per user per rolling hour
TERMS_SUMMARY_MAX = 120  # the one sentence shown with a terms update
EXPORT_WINDOW_SECONDS = 3600.0

# Export rate limit: in this process's memory (the API runs as one replica; a restart resets it — it only keeps a
# stuck client from building the export in a loop).
_export_times: dict[str, deque[float]] = {}
_export_lock = threading.Lock()


# -- export ----------------------------------------------------------------------------------------------------------
def _plain(value: Any) -> Any:
    """A column value as JSON: money and quantities as exact decimal strings, times in UTC (``Z``)."""
    if isinstance(value, Decimal):
        return format(value.normalize(), "f") if value != 0 else "0"
    if isinstance(value, datetime):
        return iso_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _row(obj: Any, *, drop: tuple[str, ...] = ("user_id",)) -> dict[str, Any]:
    """Every column of a row (the ledger as stored), minus ``drop``."""
    return {attr.key: _plain(getattr(obj, attr.key)) for attr in inspect(obj).mapper.column_attrs
            if attr.key not in drop}


def _rows(db: Session, model: Any, user_id: str, *order: Any, drop: tuple[str, ...] = ("user_id",)) -> list[dict]:
    return [_row(o, drop=drop) for o in db.scalars(select(model).where(model.user_id == user_id).order_by(*order))]


def check_export_rate(user_id: str) -> None:
    """At most ``EXPORT_LIMIT`` exports per user per hour → 429 ``rate_limited`` with ``retry_after_seconds``."""
    now = time.monotonic()
    with _export_lock:
        times = _export_times.setdefault(user_id, deque())
        while times and now - times[0] >= EXPORT_WINDOW_SECONDS:
            times.popleft()
        if len(times) >= EXPORT_LIMIT:
            wait = max(1, int(EXPORT_WINDOW_SECONDS - (now - times[0])) + 1)
            raise ApiError(429, "rate_limited", "匯出太頻繁，請稍後再試",
                           extra={"retry_after_seconds": wait}, headers={"Retry-After": str(wait)})
        times.append(now)


def reset_export_rate() -> None:
    """For tests."""
    with _export_lock:
        _export_times.clear()


def export_user(db: Session, user: User) -> dict[str, Any]:
    uid = user.id
    names = dict(db.execute(select(User.id, User.display_name)).all())  # display names of the other party only

    threads = []
    for t in db.scalars(select(AiThread).where(AiThread.user_id == uid).order_by(AiThread.created_at, AiThread.id)):
        messages = db.scalars(select(AiMessage).where(AiMessage.thread_id == t.id, AiMessage.user_id == uid)
                              .order_by(AiMessage.seq))
        threads.append({**_row(t, drop=("user_id", "key_slot", "context_tokens", "context_from_seq")),
                        "messages": [_row(m, drop=("user_id", "thread_id", "in_context")) for m in messages]})

    memberships = []
    for m, g in db.execute(select(GroupMember, Group).join(Group, Group.id == GroupMember.group_id)
                           .where(GroupMember.user_id == uid).order_by(GroupMember.joined_at, Group.id)).all():
        share = db.get(GroupShareSetting, (g.id, uid))
        memberships.append({"group_id": g.id, "name": g.name, "role": m.role, "joined_at": iso_utc(m.joined_at),
                            "share": _row(share, drop=("user_id", "group_id")) if share else None})

    def delegation(d: Delegation, other: str) -> dict[str, Any]:
        accounts = db.scalars(select(DelegationAccount.account_id).where(DelegationAccount.delegation_id == d.id))
        return {"id": d.id, "scope": d.scope, "created_at": iso_utc(d.created_at), "updated_at": iso_utc(d.updated_at),
                "other_display_name": names.get(other), "account_ids": sorted(accounts)}

    given = [delegation(d, d.viewer_id) for d in
             db.scalars(select(Delegation).where(Delegation.owner_id == uid).order_by(Delegation.created_at))]
    # Delegations other people gave me: who and when — not which of their accounts (that is their data).
    received = [{k: v for k, v in delegation(d, d.owner_id).items() if k != "account_ids"} for d in
                db.scalars(select(Delegation).where(Delegation.viewer_id == uid).order_by(Delegation.created_at))]

    topics = []
    for t in db.scalars(select(DiscussionTopic).where(DiscussionTopic.user_id == uid)
                        .order_by(DiscussionTopic.created_at, DiscussionTopic.id)):
        symbols = db.scalars(select(DiscussionTopicSymbol.symbol).where(DiscussionTopicSymbol.topic_id == t.id)
                             .order_by(DiscussionTopicSymbol.position))
        topics.append({**_row(t), "symbols": list(symbols)})

    return {
        "exported_at": iso_utc(now_utc()),
        "format_version": EXPORT_FORMAT_VERSION,
        "profile": {
            "id": user.id, "email": user.email, "display_name": user.display_name, "avatar_url": user.avatar_url,
            "public_name": user.public_name, "preferences": preferences_of(user),
            "created_at": iso_utc(user.created_at),
            "terms_version_accepted": user.terms_version_accepted,
            "terms_accepted_at": iso_utc(user.terms_accepted_at) if user.terms_accepted_at else None,
        },
        "accounts": _rows(db, BrokerAccount, uid, BrokerAccount.created_at),
        "transactions": _rows(db, Transaction, uid, Transaction.trade_date, Transaction.created_at, Transaction.id),
        "holding_snapshots": _rows(db, HoldingSnapshot, uid, HoldingSnapshot.as_of),
        "recurring_plans": _rows(db, RecurringPlan, uid, RecurringPlan.created_at),
        "watchlist": _rows(db, WatchlistItem, uid, WatchlistItem.created_at),
        "auto_dividend_skips": _rows(db, AutoDividendSkip, uid, AutoDividendSkip.created_at),
        "ai": {"threads": threads, "drafts": _rows(db, AiDraft, uid, AiDraft.created_at),
               "briefings": _rows(db, AiBriefing, uid, AiBriefing.trading_day)},
        "groups": memberships,
        "group_comments": _rows(db, GroupComment, uid, GroupComment.created_at),
        "group_reactions": _rows(db, GroupReaction, uid, GroupReaction.created_at),
        "delegations": {"given": given, "received": received},
        "discussions": {
            "topics": topics,
            "replies": _rows(db, DiscussionReply, uid, DiscussionReply.created_at),
            "reactions": _rows(db, DiscussionReaction, uid, DiscussionReaction.created_at),
        },
    }


# -- terms -----------------------------------------------------------------------------------------------------------
def terms_fields(user: User) -> dict[str, Any]:
    """The version this user agreed to, the current one, and — for the notice shown when they differ — the day the
    current version takes effect and one sentence saying what changed (both optional, operator-set)."""
    settings = get_settings()
    tracked = settings.terms_version is not None
    return {"terms_version_accepted": user.terms_version_accepted,
            "terms_version_current": settings.terms_version,
            "terms_effective_date": settings.terms_effective_date.isoformat()
            if tracked and settings.terms_effective_date else None,
            "terms_summary": one_line(settings.terms_summary)[:TERMS_SUMMARY_MAX] or None
            if tracked and settings.terms_summary else None}


def record_terms_at_signup(user: User, at: datetime | None = None) -> None:
    """A new account agrees to the current version by signing up (the sign-in page says so)."""
    current = get_settings().terms_version
    if current:
        user.terms_version_accepted = current
        user.terms_accepted_at = at or now_utc()


def accept_terms(db: Session, user: User, version: str) -> None:
    current = get_settings().terms_version
    if not current or version != current:
        raise ApiError(409, "terms_version_mismatch", "條款版本已經更新，請重新整理後再確認")
    user.terms_version_accepted = current
    user.terms_accepted_at = now_utc()
    db.commit()


# -- suspension carry-over -------------------------------------------------------------------------------------------
def identity_hash(provider: str, subject: str) -> str:
    """Keyed hash of a login identity (``discord`` / ``google`` + the provider's account id, or ``email`` + the
    verified e-mail): the same account gives the same value, and the value cannot be turned back into the id or the
    e-mail without ``SESSION_SECRET``."""
    key = get_settings().session_secret.encode()
    return hmac.new(key, f"suspension-carryover:{provider}:{subject}".encode(), hashlib.sha256).hexdigest()


def _carry_suspension(db: Session, user: User, now: datetime) -> None:
    suspension = discussions.active_suspension(db, user.id, now)
    if suspension is None:
        return
    # Every way this person can come back: each linked login, and the e-mail (an account deleted with only a Discord
    # login must not shed its suspension by registering again through Google with the same e-mail).
    keys = [identity_hash(i.provider, i.subject)
            for i in db.scalars(select(UserIdentity).where(UserIdentity.user_id == user.id))]
    if user.email:
        keys.append(identity_hash("email", user.email.strip().lower()))
    for key in dict.fromkeys(keys):
        row = db.get(DiscussionSuspensionCarryover, key)
        if row is None:
            db.add(DiscussionSuspensionCarryover(identity_hash=key, until=suspension.until, reason=suspension.reason,
                                                 created_at=now))
        else:
            row.until, row.reason = max(_aware(row.until), _aware(suspension.until)), suspension.reason


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def apply_carried_suspension(db: Session, user: User, provider: str, subject: str, now: datetime | None = None) -> None:
    """Called when an account is created for a login identity (no commit): a suspension carried over from a deleted
    account of the same identity continues on the new one. Expired carry-overs are removed."""
    now = now or now_utc()
    db.execute(delete(DiscussionSuspensionCarryover).where(DiscussionSuspensionCarryover.until <= now))
    keys = [identity_hash(provider, subject)]
    if user.email:
        keys.append(identity_hash("email", user.email.strip().lower()))
    rows = [r for r in (db.get(DiscussionSuspensionCarryover, k) for k in keys)
            if r is not None and _aware(r.until) > now]
    if not rows:
        return
    longest = max(rows, key=lambda r: _aware(r.until))
    db.add(DiscussionSuspension(id=new_id("sus"), user_id=user.id, until=longest.until, reason=longest.reason,
                                created_by=None, created_at=now))
    for r in rows:
        db.delete(r)


# -- delete ----------------------------------------------------------------------------------------------------------
def _hand_over_groups(db: Session, user: User) -> None:
    """Groups this user owns: to the earliest admin, else the earliest other member, else deleted with their content."""
    owned = db.scalars(select(GroupMember).where(GroupMember.user_id == user.id, GroupMember.role == "owner")).all()
    for mine in owned:
        others = db.scalars(select(GroupMember).where(GroupMember.group_id == mine.group_id,
                                                      GroupMember.user_id != user.id)
                            .order_by(GroupMember.joined_at, GroupMember.user_id)).all()
        heir = next((m for m in others if m.role == "admin"), others[0] if others else None)
        if heir is None:
            group = db.get(Group, mine.group_id)
            if group is not None:
                groups.purge(db, group)
        else:
            heir.role = "owner"
    db.flush()


def delete_user(db: Session, user: User) -> None:
    """Delete the account and everything that is only the user's; one transaction (the caller's session), committed
    here. Anything raised rolls the whole deletion back."""
    uid = user.id
    now = now_utc()
    try:
        _carry_suspension(db, user, now)
        _hand_over_groups(db, user)
        # The user's own rows, children first (explicit, so it does not depend on each database's cascade order).
        db.execute(delete(DiscussionReport).where(DiscussionReport.reporter_id == uid))  # reports I filed
        for model in (DiscussionReaction, DiscussionPostLog, DiscussionSuspension, GroupReaction, GroupShareSetting,
                      GroupMember, NotificationOutbox):
            db.execute(delete(model).where(model.user_id == uid))
        db.execute(delete(TelegramLinkCode).where(TelegramLinkCode.created_by == uid))
        mine = select(Delegation.id).where(or_(Delegation.owner_id == uid, Delegation.viewer_id == uid))
        db.execute(delete(DelegationAccount).where(DelegationAccount.delegation_id.in_(mine)))
        db.execute(delete(Delegation).where(or_(Delegation.owner_id == uid, Delegation.viewer_id == uid)))
        for model in (AiBriefing, AiDraft, AiMessage, AiThread, AutoDividendSkip, HoldingSnapshot, RecurringPlan,
                      Transaction, WatchlistItem, BrokerAccount, UserSession, UserIdentity):
            db.execute(delete(model).where(model.user_id == uid))
        # What is left pointing at the user is kept without an author (ON DELETE SET NULL): group comments, discussion
        # topics and replies, AI usage counts, who created an invite / configured a channel / suspended someone.
        db.execute(delete(User).where(User.id == uid))
        db.commit()
    except Exception:
        db.rollback()
        raise
