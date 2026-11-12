"""One-to-one read-only access (docs/api-contract.md 「分享（M5）」→「授權唯讀查看」).

A user may grant read-only access only to someone who shares at least one group with them. The grant is not revoked
automatically when they stop sharing a group (it is a one-to-one decision); the owner can revoke it at any time, and
the viewer can remove it. Viewing itself (``X-Forliosa-View-As``) is resolved in ``services.sharing.enter_view_as``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, aliased

from forliosa.api.errors import ApiError, not_found, unprocessable
from forliosa.ids import new_id
from forliosa.models import BrokerAccount, Delegation, DelegationAccount, GroupMember, User
from forliosa.services.sharing import identity
from forliosa.timeutil import iso_taipei, now_utc


def co_members(db: Session, me_id: str) -> list[str]:
    """Users who share at least one group with ``me_id`` (``me_id`` excluded)."""
    mine = aliased(GroupMember)
    other = aliased(GroupMember)
    rows = db.scalars(select(other.user_id).join(mine, mine.group_id == other.group_id)
                      .where(mine.user_id == me_id, other.user_id != me_id).distinct())
    return list(rows)


def _accounts(db: Session, dlg: Delegation) -> list[BrokerAccount]:
    q = select(BrokerAccount).where(BrokerAccount.user_id == dlg.owner_id)
    if dlg.scope != "all":
        q = q.join(DelegationAccount, DelegationAccount.account_id == BrokerAccount.id).where(
            DelegationAccount.delegation_id == dlg.id)
    return list(db.scalars(q.order_by(BrokerAccount.created_at, BrokerAccount.id)))


def delegation_out(db: Session, dlg: Delegation) -> dict[str, Any]:
    owner, viewer = db.get(User, dlg.owner_id), db.get(User, dlg.viewer_id)
    assert owner is not None and viewer is not None
    return {"id": dlg.id, "owner": identity(owner), "viewer": identity(viewer), "scope": dlg.scope,
            "accounts": [{"id": a.id, "name": a.name} for a in _accounts(db, dlg)],
            "created_at": iso_taipei(dlg.created_at)}


def list_all(db: Session, me: User) -> dict[str, list[dict[str, Any]]]:
    def rows(col):
        return [delegation_out(db, d) for d in db.scalars(select(Delegation).where(col == me.id)
                                                         .order_by(Delegation.created_at, Delegation.id))]

    return {"granted": rows(Delegation.owner_id), "received": rows(Delegation.viewer_id)}


def candidates(db: Session, me: User) -> list[dict[str, Any]]:
    ids = co_members(db, me.id)
    if not ids:
        return []
    granted = {d.viewer_id: d.id for d in db.scalars(select(Delegation).where(Delegation.owner_id == me.id))}
    users = db.scalars(select(User).where(User.id.in_(ids)).order_by(User.display_name, User.id))
    return [{**identity(u), "delegation_id": granted.get(u.id)} for u in users]


def _account_ids(db: Session, me: User, scope: str, account_ids: list[str] | None) -> list[str]:
    if scope == "all":
        if account_ids:
            raise unprocessable("授權全部帳戶時不要指定 account_ids")
        return []
    ids = list(dict.fromkeys(account_ids or []))
    if not ids:
        raise unprocessable("請至少選一個帳戶")
    owned = set(db.scalars(select(BrokerAccount.id).where(BrokerAccount.user_id == me.id,
                                                          BrokerAccount.id.in_(ids))))
    if owned != set(ids):
        raise unprocessable("只能授權自己的帳戶")
    return ids


def _owned_or_404(db: Session, me: User, delegation_id: str, viewer_may: bool = False) -> Delegation:
    dlg = db.get(Delegation, delegation_id)
    if dlg is None or (dlg.owner_id != me.id and not (viewer_may and dlg.viewer_id == me.id)):
        if dlg is not None and dlg.viewer_id == me.id:
            raise ApiError(403, "forbidden", "只有授權者可以修改授權範圍")
        raise not_found("找不到授權")
    return dlg


def create(db: Session, me: User, viewer_user_id: str, scope: str, account_ids: list[str] | None) -> Delegation:
    if viewer_user_id == me.id or viewer_user_id not in co_members(db, me.id):
        raise not_found("找不到這位成員（只能授權給同群組的成員）")
    if db.scalar(select(Delegation).where(Delegation.owner_id == me.id, Delegation.viewer_id == viewer_user_id)):
        raise ApiError(409, "already_member", "已經授權給這位成員；請改用修改範圍")
    ids = _account_ids(db, me, scope, account_ids)
    now = now_utc()
    dlg = Delegation(id=new_id("dlg"), owner_id=me.id, viewer_id=viewer_user_id, scope=scope, created_at=now,
                     updated_at=now)
    db.add(dlg)
    db.flush()
    db.add_all(DelegationAccount(delegation_id=dlg.id, account_id=a) for a in ids)
    db.commit()
    return dlg


def update(db: Session, me: User, delegation_id: str, scope: str, account_ids: list[str] | None) -> Delegation:
    dlg = _owned_or_404(db, me, delegation_id)
    ids = _account_ids(db, me, scope, account_ids)
    dlg.scope = scope
    dlg.updated_at = now_utc()
    db.execute(delete(DelegationAccount).where(DelegationAccount.delegation_id == dlg.id))
    db.add_all(DelegationAccount(delegation_id=dlg.id, account_id=a) for a in ids)
    db.commit()
    return dlg


def remove(db: Session, me: User, delegation_id: str) -> None:
    """The owner revokes, or the viewer removes it; effective immediately."""
    dlg = _owned_or_404(db, me, delegation_id, viewer_may=True)
    db.execute(delete(DelegationAccount).where(DelegationAccount.delegation_id == dlg.id))
    db.delete(dlg)
    db.commit()
