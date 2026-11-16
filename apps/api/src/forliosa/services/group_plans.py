"""群組加值包 (產品負責人 2026-11-16, the group subscription memo, decisions 3, 8, 9 and 13): which groups are boosted,
how many members each group takes, and what site admins and group owners do with boosts. No payments yet: a site admin
grants a boost by hand and the owner tries it out on their own groups.

* **Member caps**: a free group takes ``GROUP_FREE_MEMBER_CAP`` (15) members, a boosted one
  ``GROUP_BOOSTED_MEMBER_CAP`` (50). A group made before the change keeps ``groups.grandfathered_member_cap`` (50,
  set by migration 0023) whatever its plan. More than 50 is not offered. The cap only stops new members
  (``groups.accept_invite``, 409 ``limit_reached`` naming the cap): nobody is ever removed, also when a boost ends.
* **Boosts** (``GroupPass``): granted to a payer, by email, through ``until`` (the last day, Taipei). The payer — the
  owner of the group — attaches it to a group they own (``PUT /groups/{id}/plan``), or the admin attaches it directly
  with the group's id. A group is boosted while a pass attached to it has not ended; it stays boosted through
  ``until`` when the owner hands the group over or the payer deletes their account. A deleted group hands its pass
  back to the payer, unattached.
* **What a boost gives**: the 50-member cap and the 群組 AI 日報 (``services.group_daily``). When it ends, the daily
  report stops and earlier reports stay readable. The weekly digest and every member's own AI quota are the same for
  every group.
* **Privacy**: the admin's list shows the payer's email and display name, the dates, the note and the group's id —
  never the group's name, its members or anything in it (privacy policy §4.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.api.errors import ApiError, not_found
from forliosa.config import Settings, get_settings
from forliosa.ids import new_id
from forliosa.models import Group, GroupMember, GroupPass, User
from forliosa.timeutil import TAIPEI, iso_taipei, now_utc

FREE, BOOSTED = "free", "boosted"
NOTE_MAX = 200


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def end_of(last_day: date) -> datetime:
    """``until`` of a boost whose last day is ``last_day``: 00:00 Taipei the day after."""
    return datetime.combine(last_day + timedelta(days=1), time(0), TAIPEI)


def last_day(until: datetime | None) -> date | None:
    return None if until is None else (_aware(until).astimezone(TAIPEI) - timedelta(microseconds=1)).date()


def is_active(p: GroupPass, now: datetime) -> bool:
    return _aware(p.until) > now


# -- a group's plan ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class GroupPlan:
    tier: str  # FREE or BOOSTED
    until: datetime | None  # the end of the boost that lasts longest (None: free)
    member_cap: int
    grandfathered: bool  # made before the change: keeps 50 members whatever its plan

    @property
    def boosted(self) -> bool:
        return self.tier == BOOSTED


def plan_of(db: Session, group: Group, settings: Settings | None = None, now: datetime | None = None) -> GroupPlan:
    settings = settings or get_settings()
    now = now or now_utc()
    live = [u for u in (_aware(x) for x in db.scalars(select(GroupPass.until).where(GroupPass.group_id == group.id)))
            if u > now]
    boosted = bool(live)
    cap = settings.group_boosted_member_cap if boosted else settings.group_free_member_cap
    legacy = group.grandfathered_member_cap or 0
    return GroupPlan(BOOSTED if boosted else FREE, max(live) if live else None, max(cap, legacy), legacy > 0)


def plan_out(plan: GroupPlan) -> dict[str, Any]:
    d = last_day(plan.until)
    return {"tier": plan.tier, "until": d.isoformat() if d else None, "member_cap": plan.member_cap,
            "grandfathered": plan.grandfathered, "daily_report": plan.boosted}


def boosting_passes(db: Session, *moments: datetime) -> dict[str, list[str]]:
    """``{group id: [pass ids]}`` of passes on a group that had not ended at any of these moments (the daily report:
    the session's close, now)."""
    out: dict[str, list[str]] = {}
    for pid, gid, until in db.execute(select(GroupPass.id, GroupPass.group_id, GroupPass.until)
                                      .where(GroupPass.group_id.is_not(None)).order_by(GroupPass.id)):
        if any(_aware(until) > t for t in moments):
            out.setdefault(gid, []).append(pid)
    return out


def boosted_group_ids(db: Session, *moments: datetime) -> set[str]:
    """Groups with a pass that had not ended at any of these moments."""
    return set(boosting_passes(db, *moments))


def full_message(plan: GroupPlan, settings: Settings | None = None) -> str:
    """The 409 of a join refused at the cap: says what the cap is (and what boosting would give a free group)."""
    settings = settings or get_settings()
    if plan.member_cap < settings.group_boosted_member_cap and not plan.boosted:
        return (f"這個群組已經滿了：免費群組最多 {plan.member_cap} 位成員"
                f"（加值的群組最多 {settings.group_boosted_member_cap} 位）")
    return f"這個群組已經滿了：最多 {plan.member_cap} 位成員"


# -- site admins: grant, extend, revoke --------------------------------------------------------------------------------
def _admin_row(p: GroupPass, payer: User | None, now: datetime) -> dict[str, Any]:
    d = last_day(p.until)
    return {"id": p.id, "payer_user_id": p.payer_id, "email": payer.email if payer else None,
            "display_name": payer.display_name if payer else None, "until": d.isoformat() if d else None,
            "note": p.note, "active": is_active(p, now), "group_id": p.group_id,
            "attached_at": iso_taipei(p.attached_at) if p.attached_at else None,
            "created_at": iso_taipei(p.created_at)}


def admin_list(db: Session, now: datetime | None = None) -> list[dict[str, Any]]:
    """Every pass (ended ones too, so they can be extended): active first, then by last day."""
    now = now or now_utc()
    rows = db.execute(select(GroupPass, User).outerjoin(User, User.id == GroupPass.payer_id)).all()
    out = [_admin_row(p, u, now) for p, u in rows]
    return sorted(out, key=lambda r: (not r["active"], r["until"] or "", r["email"] or "", r["id"]))


MAX_YEARS = 5  # a last day further away is a typo (and 9999-12-31 would overflow end_of)


def _check_until(until: date, now: datetime) -> None:
    today = now.astimezone(TAIPEI).date()
    if until < today:
        raise ApiError(422, "until_in_past", "到期日不能早於今天。")
    if until > today + timedelta(days=365 * MAX_YEARS):
        raise ApiError(422, "until_too_far", f"到期日最多是 {MAX_YEARS} 年後。")


def _owned_group(db: Session, group_id: str, user_id: str) -> Group:
    group = db.get(Group, group_id)
    if group is None:
        raise ApiError(404, "group_not_found", "找不到這個群組編號。")
    m = db.get(GroupMember, (group_id, user_id))
    if m is None or m.role != "owner":
        raise ApiError(409, "not_group_owner", "這個帳號不是這個群組的擁有者：加值只能用在付款人自己擁有的群組。")
    return group


def admin_grant(db: Session, email: str, until: date, note: str | None, group_id: str | None = None,
                now: datetime | None = None) -> dict[str, Any]:
    """A new boost for the account with this email (it must have signed in once: 404 otherwise) through ``until``.
    With ``group_id`` it is attached to that group at once (the payer must own it); without, the payer picks the group
    in the group's settings."""
    now = now or now_utc()
    payer = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    if payer is None:
        raise ApiError(404, "user_not_found", "找不到這個 email 的帳號：請對方先登入一次 Forliosa。")
    _check_until(until, now)
    if group_id is not None:
        _owned_group(db, group_id, payer.id)
    p = GroupPass(id=new_id("gps"), payer_id=payer.id, group_id=group_id, until=end_of(until), note=note,
                  source="manual", attached_at=now if group_id else None, created_at=now, updated_at=now)
    db.add(p)
    db.commit()
    return _admin_row(p, payer, now)


def admin_update(db: Session, pass_id: str, changes: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Extend (or shorten) a boost, or change its note. A new last day must not be before today."""
    now = now or now_utc()
    p = db.get(GroupPass, pass_id)
    if p is None:
        raise not_found("找不到這個群組加值。")
    if changes.get("until") is not None:
        _check_until(changes["until"], now)
        p.until = end_of(changes["until"])
    if "note" in changes:
        p.note = changes["note"]
    p.updated_at = now
    db.commit()
    return _admin_row(p, db.get(User, p.payer_id) if p.payer_id else None, now)


def admin_revoke(db: Session, pass_id: str, now: datetime | None = None) -> None:
    """End a boost at once (the group falls back to its free cap; nobody is removed). The record stays — payer, dates,
    note and group, for the books and refunds (privacy policy §7) — listed as ended; it can be extended again."""
    now = now or now_utc()
    p = db.get(GroupPass, pass_id)
    if p is None:
        raise not_found("找不到這個群組加值。")
    if is_active(p, now):
        p.until, p.updated_at = now, now
    db.commit()


# -- the payer and the group's owner ----------------------------------------------------------------------------------
def my_passes(db: Session, me: User, now: datetime | None = None) -> list[dict[str, Any]]:
    """The boosts this account was granted, active first, then by last day. The group's name only while I am a member
    of it."""
    now = now or now_utc()
    out = []
    for p in db.scalars(select(GroupPass).where(GroupPass.payer_id == me.id)):
        group = None
        if p.group_id is not None:
            m = db.get(GroupMember, (p.group_id, me.id))
            g = db.get(Group, p.group_id) if m is not None else None
            if g is not None:
                group = {"id": g.id, "name": g.name, "my_role": m.role}
        d = last_day(p.until)
        out.append({"id": p.id, "until": d.isoformat() if d else None, "active": is_active(p, now),
                    "attached": p.group_id is not None, "group": group})
    out.sort(key=lambda r: (not r["active"], r["until"] or ""))
    return out


def attach(db: Session, group: Group, m: GroupMember, pass_id: str, now: datetime | None = None) -> None:
    """The owner puts one of their own boosts on this group. A boost already on another group moves only while its
    payer still owns that group (a group that was handed over keeps its boost until it ends)."""
    now = now or now_utc()
    if m.role != "owner":
        raise ApiError(403, "forbidden", "只有擁有者可以替群組加值")
    p = db.get(GroupPass, pass_id)
    if p is None or p.payer_id != m.user_id:
        raise not_found("找不到這個群組加值")
    if not is_active(p, now):
        raise ApiError(409, "pass_expired", "這個群組加值已經到期")
    if p.group_id == group.id:
        return
    if p.group_id is not None:
        old = db.get(GroupMember, (p.group_id, m.user_id))
        if old is None or old.role != "owner":
            raise ApiError(409, "pass_in_use", "這個群組加值用在另一個群組，而你已經不是那個群組的擁有者")
    p.group_id, p.attached_at, p.updated_at = group.id, now, now
    db.commit()
