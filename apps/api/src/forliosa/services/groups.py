"""Family groups: membership, roles, invites, share settings, comments and reactions (docs/api-contract.md
「分享（M5）」→「親友群組」). Everything a member sees of other members' data goes through ``services.sharing``.

Existence and permissions: a non-member gets 404 ``not_found`` from every group endpoint (whether the group exists is
not revealed); a member without the role gets 403 ``forbidden``.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from forliosa.api.errors import ApiError, not_found, unprocessable
from forliosa.config import get_settings
from forliosa.crypto import random_token, token_hash
from forliosa.ids import new_id
from forliosa.marketdata.service import MarketData
from forliosa.models import (
    Group,
    GroupChannel,
    GroupComment,
    GroupDigest,
    GroupInvite,
    GroupMember,
    GroupReaction,
    GroupShareSetting,
    NotificationOutbox,
    TelegramLinkCode,
    User,
)
from forliosa.services import sharing
from forliosa.services.sharing import Member
from forliosa.timeutil import TAIPEI, iso_taipei, now_utc

MAX_MEMBERS = 50
MAX_GROUPS = 20
INVITE_TTL = {"24h": timedelta(hours=24), "7d": timedelta(days=7)}
ROLES = ("owner", "admin", "member")
MANAGERS = ("owner", "admin")
CHANNEL_LABELS = {"discord": "Discord 頻道", "telegram": "Telegram 群組"}


def forbidden(message: str = "沒有權限") -> ApiError:
    return ApiError(403, "forbidden", message)


def limit_reached(message: str) -> ApiError:
    return ApiError(409, "limit_reached", message)


# -- access ----------------------------------------------------------------------------------------------------
def require_member(db: Session, group_id: str, user: User) -> tuple[Group, GroupMember]:
    m = db.get(GroupMember, (group_id, user.id))
    g = db.get(Group, group_id) if m is not None else None
    if m is None or g is None:
        raise not_found("找不到群組")
    return g, m


def require_role(m: GroupMember, roles: tuple[str, ...], message: str = "沒有權限") -> None:
    if m.role not in roles:
        raise forbidden(message)


def group_count(db: Session, user_id: str) -> int:
    return db.scalar(select(func.count()).select_from(GroupMember).where(GroupMember.user_id == user_id)) or 0


def member_count(db: Session, group_id: str) -> int:
    return db.scalar(select(func.count()).select_from(GroupMember).where(GroupMember.group_id == group_id)) or 0


# -- outputs ---------------------------------------------------------------------------------------------------
def push_targets(db: Session, group_id: str) -> list[dict[str, str]]:
    """Where this group pushes (active channels only): every member sees it."""
    out = []
    for ch in db.scalars(select(GroupChannel).where(GroupChannel.group_id == group_id, GroupChannel.status == "active")
                         .order_by(GroupChannel.kind)):
        label = (ch.chat_title or CHANNEL_LABELS["telegram"]) if ch.kind == "telegram" else CHANNEL_LABELS["discord"]
        out.append({"kind": ch.kind, "label": label})
    return out


def group_out(db: Session, group: Group, me: User) -> dict[str, Any]:
    members = sharing.members_of(db, group.id)
    mine = next(m for m in members if m.user_id == me.id)
    return {
        "id": group.id, "name": group.name, "my_role": mine.role, "ranking_enabled": bool(group.ranking_enabled),
        "created_at": iso_taipei(group.created_at),
        "members": [{**sharing.identity(m.user), "role": m.role, "joined_at": iso_taipei(m.joined_at),
                     "is_me": m.user_id == me.id} for m in members],
        "my_share": sharing.share_out(mine.share),
        "push_targets": push_targets(db, group.id),
    }


def summary_out(db: Session, md: MarketData, group: Group, me: User) -> dict[str, Any]:
    members = sharing.members_of(db, group.id)
    mine = next(m for m in members if m.user_id == me.id)
    activity = sharing.latest_activity(db, md, group, members)
    digest = db.scalar(select(func.max(GroupDigest.created_at)).where(GroupDigest.group_id == group.id,
                                                                     GroupDigest.status == "ready"))
    return {"id": group.id, "name": group.name, "my_role": mine.role, "member_count": len(members),
            "ranking_enabled": bool(group.ranking_enabled),
            "latest_activity_at": iso_taipei(activity) if activity else None,
            "latest_digest_at": iso_taipei(digest) if digest else None}


def my_groups(db: Session, md: MarketData, me: User) -> list[dict[str, Any]]:
    groups = db.execute(select(Group).join(GroupMember, GroupMember.group_id == Group.id)
                        .where(GroupMember.user_id == me.id).order_by(GroupMember.joined_at, Group.id)).scalars()
    return [summary_out(db, md, g, me) for g in groups]


# -- groups ----------------------------------------------------------------------------------------------------
def _add_member(db: Session, group_id: str, user_id: str, role: str, share: dict[str, bool]) -> None:
    now = now_utc()
    db.add(GroupMember(group_id=group_id, user_id=user_id, role=role, joined_at=now))
    db.flush()
    db.add(GroupShareSetting(group_id=group_id, user_id=user_id, **share,
                             trades_enabled_at=now if share["trades"] else None,
                             push_enabled_at=now if share["push"] else None, updated_at=now))


def create_group(db: Session, me: User, name: str) -> Group:
    if group_count(db, me.id) >= MAX_GROUPS:
        raise limit_reached(f"每人最多加入 {MAX_GROUPS} 個群組")
    g = Group(id=new_id("grp"), name=name, ranking_enabled=True, created_at=now_utc())
    db.add(g)
    db.flush()
    _add_member(db, g.id, me.id, "owner", dict(sharing.DEFAULT_SHARE))
    db.commit()
    return g


def update_group(db: Session, group: Group, m: GroupMember, changes: dict[str, Any]) -> None:
    require_role(m, MANAGERS, "只有擁有者或管理員可以修改群組")
    if "ranking_enabled" in changes and m.role != "owner":
        raise forbidden("只有擁有者可以開關排行")
    if "name" in changes:
        group.name = changes["name"]
    if "ranking_enabled" in changes:
        group.ranking_enabled = bool(changes["ranking_enabled"])
    group.updated_at = now_utc()
    db.commit()


def purge(db: Session, group: Group) -> None:
    """The group with everything in it: discussions, comments, reactions, invites, channels, digests, share settings
    and memberships (no commit, no permission check: ``delete_group`` and account deletion call it)."""
    from forliosa.services import discussions  # imported here: discussions imports this module

    discussions.purge_group(db, group.id)  # the group's topics with their replies, reactions and tags
    for model in (GroupComment, GroupReaction, GroupInvite, NotificationOutbox, TelegramLinkCode, GroupChannel,
                  GroupDigest, GroupShareSetting):
        db.execute(delete(model).where(model.group_id == group.id))
    db.execute(delete(GroupMember).where(GroupMember.group_id == group.id))
    db.delete(group)


def delete_group(db: Session, group: Group, m: GroupMember) -> None:
    require_role(m, ("owner",), "只有擁有者可以刪除群組")
    purge(db, group)
    db.commit()


def transfer(db: Session, group: Group, m: GroupMember, user_id: str) -> None:
    require_role(m, ("owner",), "只有擁有者可以轉移群組")
    if user_id == m.user_id:
        raise unprocessable("你已經是擁有者")
    target = db.get(GroupMember, (group.id, user_id))
    if target is None:
        raise not_found("找不到這位成員")
    target.role = "owner"
    m.role = "admin"
    db.commit()


def set_role(db: Session, group: Group, m: GroupMember, user_id: str, role: str) -> None:
    require_role(m, ("owner",), "只有擁有者可以變更角色")
    target = db.get(GroupMember, (group.id, user_id))
    if target is None:
        raise not_found("找不到這位成員")
    if target.role == "owner":
        raise unprocessable("不能變更擁有者的角色；請改用轉移擁有者")
    target.role = role
    db.commit()


def remove_member(db: Session, group: Group, m: GroupMember, user_id: str) -> None:
    """Leave (``user_id`` = me) or remove someone. The owner must transfer before leaving; an admin cannot remove the
    owner or another admin. Removing someone revokes every multi-use invite of the group. Share settings go with the
    membership (re-chosen on rejoin); comments stay (shown as 「已離開的成員」)."""
    if user_id == m.user_id:
        if m.role == "owner":
            raise ApiError(409, "conflict", "擁有者要先把群組轉移給其他成員才能離開")
        target = m
    else:
        require_role(m, MANAGERS, "只有擁有者或管理員可以移除成員")
        target = db.get(GroupMember, (group.id, user_id))
        if target is None:
            raise not_found("找不到這位成員")
        if target.role == "owner" or (m.role == "admin" and target.role == "admin"):
            raise forbidden("管理員不能移除擁有者或其他管理員")
        db.execute(update(GroupInvite).where(GroupInvite.group_id == group.id, GroupInvite.multi_use.is_(True),
                                             GroupInvite.revoked_at.is_(None)).values(revoked_at=now_utc()))
    db.execute(delete(GroupShareSetting).where(GroupShareSetting.group_id == group.id,
                                               GroupShareSetting.user_id == target.user_id))
    db.delete(target)
    db.commit()


# -- share settings ------------------------------------------------------------------------------------------------
def put_share(db: Session, group: Group, m: GroupMember, share: dict[str, bool]) -> dict[str, bool]:
    s = db.get(GroupShareSetting, (group.id, m.user_id))
    now = now_utc()
    if s is None:  # pragma: no cover - created with the membership
        s = GroupShareSetting(group_id=group.id, user_id=m.user_id)
        db.add(s)
    if share["trades"] and not s.trades:
        s.trades_enabled_at = now
    if share["push"] and not s.push:
        s.push_enabled_at = now
    for k in sharing.SHARE_KEYS:
        setattr(s, k, bool(share[k]))
    s.updated_at = now
    db.commit()
    return sharing.share_out(s)


# -- invites ----------------------------------------------------------------------------------------------------
def _aware(dt: datetime) -> datetime:
    from datetime import UTC

    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def invite_valid(inv: GroupInvite, now: datetime | None = None) -> bool:
    now = now or now_utc()
    return inv.revoked_at is None and _aware(inv.expires_at) > now and (inv.multi_use or inv.uses == 0)


def invite_out(inv: GroupInvite, url: str | None = None) -> dict[str, Any]:
    out = {"id": inv.id, "expires_at": iso_taipei(inv.expires_at), "multi_use": bool(inv.multi_use),
           "uses": inv.uses, "created_at": iso_taipei(inv.created_at)}
    if url is not None:
        out["url"] = url
    return out


def create_invite(db: Session, group: Group, m: GroupMember, expires: str, multi_use: bool) -> dict[str, Any]:
    require_role(m, MANAGERS, "只有擁有者或管理員可以建立邀請")
    token = random_token(32)  # 256 bits; only its SHA-256 is stored
    now = now_utc()
    inv = GroupInvite(id=new_id("inv"), group_id=group.id, token_hash=token_hash(token), created_by=m.user_id,
                      multi_use=multi_use, uses=0, expires_at=now + INVITE_TTL[expires], created_at=now)
    db.add(inv)
    db.commit()
    return invite_out(inv, f"{get_settings().frontend_base}/invite/{token}")


def list_invites(db: Session, group: Group, m: GroupMember) -> list[dict[str, Any]]:
    require_role(m, MANAGERS, "只有擁有者或管理員可以查看邀請")
    now = now_utc()
    rows = db.scalars(select(GroupInvite).where(GroupInvite.group_id == group.id)
                      .order_by(GroupInvite.created_at.desc(), GroupInvite.id))
    return [invite_out(i) for i in rows if invite_valid(i, now)]


def revoke_invite(db: Session, group: Group, m: GroupMember, invite_id: str) -> None:
    require_role(m, MANAGERS, "只有擁有者或管理員可以撤回邀請")
    inv = db.get(GroupInvite, invite_id)
    if inv is None or inv.group_id != group.id:
        raise not_found("找不到邀請")
    if inv.revoked_at is None:
        inv.revoked_at = now_utc()
    db.commit()


def _invite_by_token(db: Session, token: str) -> GroupInvite:
    inv = db.scalar(select(GroupInvite).where(GroupInvite.token_hash == token_hash(token))) if token else None
    if inv is None:
        raise not_found("找不到邀請")
    if not invite_valid(inv):
        raise ApiError(410, "invite_invalid", "這個邀請連結已過期、已撤回或已使用")
    return inv


def preview_invite(db: Session, token: str, me: User | None) -> dict[str, Any]:
    inv = _invite_by_token(db, token)
    group = db.get(Group, inv.group_id)
    if group is None:  # pragma: no cover - invites are deleted with the group
        raise not_found("找不到邀請")
    inviter = db.get(GroupMember, (group.id, inv.created_by)) if inv.created_by else None
    if inviter is None:  # the inviter left: name the current owner instead
        inviter = db.scalar(select(GroupMember).where(GroupMember.group_id == group.id, GroupMember.role == "owner"))
    inviter_user = db.get(User, inviter.user_id) if inviter is not None else None
    is_member = me is not None and db.get(GroupMember, (group.id, me.id)) is not None
    out: dict[str, Any] = {"group_name": group.name,
                           "inviter_display_name": inviter_user.display_name if inviter_user else None,
                           "status": "member" if is_member else "valid"}
    if is_member:  # only a signed-in member learns the group id (the invite page links straight to the group)
        out["group_id"] = group.id
    return out


def accept_invite(db: Session, token: str, me: User, share: dict[str, bool]) -> Group:
    inv = _invite_by_token(db, token)
    group = db.get(Group, inv.group_id)
    if group is None:  # pragma: no cover
        raise not_found("找不到邀請")
    if db.get(GroupMember, (group.id, me.id)) is not None:
        raise ApiError(409, "already_member", "你已經是這個群組的成員")
    if member_count(db, group.id) >= MAX_MEMBERS:
        raise limit_reached(f"每個群組最多 {MAX_MEMBERS} 位成員")
    if group_count(db, me.id) >= MAX_GROUPS:
        raise limit_reached(f"每人最多加入 {MAX_GROUPS} 個群組")
    # Count the use atomically: two people accepting a single-use link at once → only one wins.
    cond = [GroupInvite.id == inv.id, GroupInvite.revoked_at.is_(None), GroupInvite.expires_at > now_utc()]
    if not inv.multi_use:
        cond.append(GroupInvite.uses == 0)
    res = db.execute(update(GroupInvite).where(*cond).values(uses=GroupInvite.uses + 1)
                     .execution_options(synchronize_session=False))
    if not res.rowcount:
        db.rollback()
        raise ApiError(410, "invite_invalid", "這個邀請連結已過期、已撤回或已使用")
    _add_member(db, group.id, me.id, "member", share)
    db.commit()
    return group


# -- comments and reactions -------------------------------------------------------------------------------------
def _require_target(db: Session, md: MarketData, group: Group, members: list[Member], target: str) -> None:
    if not sharing.target_visible(db, md, group, members, target):
        raise not_found("找不到討論對象")


def comment_out(c: GroupComment, members: dict[str, Member], me: GroupMember,
                users: dict[str, User]) -> dict[str, Any]:
    author = members.get(c.user_id) if c.user_id else None
    if author is not None:
        uid, name, avatar = author.user_id, author.user.display_name, author.user.avatar_url
    else:
        uid, avatar = None, None
        name = sharing.LEFT_MEMBER if c.user_id and c.user_id in users else sharing.DELETED_ACCOUNT
    return {"id": c.id, "target": c.target, "user_id": uid, "display_name": name, "avatar_url": avatar,
            "body": c.body, "created_at": iso_taipei(c.created_at),
            "can_delete": c.user_id == me.user_id or me.role in MANAGERS}


def _comment_cursor(c: GroupComment) -> str:
    raw = f"{c.created_at.astimezone(TAIPEI).isoformat()}|{c.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def list_comments(db: Session, md: MarketData, group: Group, me: GroupMember, target: str, limit: int,
                  cursor: str | None) -> dict[str, Any]:
    members = sharing.members_of(db, group.id)
    _require_target(db, md, group, members, target)
    q = select(GroupComment).where(GroupComment.group_id == group.id, GroupComment.target == target)
    if cursor:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
            created, cid = raw.split("|", 1)
            after = datetime.fromisoformat(created)
        except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
            raise unprocessable("分頁游標無效") from exc
        q = q.where((GroupComment.created_at > after) | ((GroupComment.created_at == after) & (GroupComment.id > cid)))
    rows = list(db.scalars(q.order_by(GroupComment.created_at, GroupComment.id).limit(limit + 1)))
    page = rows[:limit]
    by_id = {m.user_id: m for m in members}
    authors = {c.user_id for c in page if c.user_id and c.user_id not in by_id}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(authors)))} if authors else {}
    return {"items": [comment_out(c, by_id, me, users) for c in page],
            "next_cursor": _comment_cursor(page[-1]) if len(rows) > limit else None}


def add_comment(db: Session, md: MarketData, group: Group, me: GroupMember, target: str, body: str) -> dict[str, Any]:
    members = sharing.members_of(db, group.id)
    _require_target(db, md, group, members, target)
    c = GroupComment(id=new_id("gcm"), group_id=group.id, target=target, user_id=me.user_id, body=body,
                     created_at=now_utc())
    db.add(c)
    db.commit()
    return comment_out(c, {m.user_id: m for m in members}, me, {})


def delete_comment(db: Session, md: MarketData, group: Group, me: GroupMember, comment_id: str) -> None:
    c = db.get(GroupComment, comment_id)
    if c is None or c.group_id != group.id:
        raise not_found("找不到留言")
    _require_target(db, md, group, sharing.members_of(db, group.id), c.target)
    if c.user_id != me.user_id and me.role not in MANAGERS:
        raise forbidden("只有留言者或管理員可以刪除留言")
    db.delete(c)
    db.commit()


def put_reaction(db: Session, md: MarketData, group: Group, me: GroupMember, target: str,
                 emoji: str) -> dict[str, Any]:
    _require_target(db, md, group, sharing.members_of(db, group.id), target)
    if db.get(GroupReaction, (group.id, target, me.user_id, emoji)) is None:
        db.add(GroupReaction(group_id=group.id, target=target, user_id=me.user_id, emoji=emoji, created_at=now_utc()))
        db.commit()
    return {"target": target, "reactions": sharing.reactions_for(db, group.id, target, me.user_id)}


def delete_reaction(db: Session, md: MarketData, group: Group, me: GroupMember, target: str,
                    emoji: str) -> dict[str, Any]:
    _require_target(db, md, group, sharing.members_of(db, group.id), target)
    db.execute(delete(GroupReaction).where(GroupReaction.group_id == group.id, GroupReaction.target == target,
                                           GroupReaction.user_id == me.user_id, GroupReaction.emoji == emoji))
    db.commit()
    return {"target": target, "reactions": sharing.reactions_for(db, group.id, target, me.user_id)}


# -- views of other members (through the projection) ------------------------------------------------------------
def member_or_404(members: list[Member], user_id: str) -> Member:
    m = next((m for m in members if m.user_id == user_id), None)
    if m is None:
        raise not_found("找不到這位成員")
    return m
