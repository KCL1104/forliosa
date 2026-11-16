"""The site admins' back office (docs/api-contract.md 「管理後台」): an overview, the news takedown blocklist and the
members and 群組加值包 granted by hand (``forliosa.plans``, ``services.group_plans``; no payments yet).

Guarded like the discussion moderation endpoints (``routes.discussions.admin_router``): signed in (401), and a site
admin (``ADMIN_EMAILS``) or 404 — before the body is validated, so the path reveals nothing. Every endpoint acts as
the signed-in admin. Under ``X-Forliosa-View-As`` none of these paths is allow-listed (``api.middleware``): reads are
403 ``view_as_not_allowed`` and writes 403 ``read_only``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Response
from sqlalchemy.orm import Session

from forliosa import plans
from forliosa.api.deps import signed_in_user
from forliosa.api.schemas_admin import (
    AdminGroupPass,
    AdminMember,
    AdminOverview,
    BlockDomainIn,
    BlockDomainOut,
    BlockedDomain,
    GroupPassGrantIn,
    GroupPassPatch,
    MemberGrantIn,
)
from forliosa.db import get_db
from forliosa.models import User
from forliosa.services import admin as svc
from forliosa.services import group_plans
from forliosa.services.discussions import require_admin


def site_admin(user: User = Depends(signed_in_user)) -> User:
    require_admin(user)
    return user


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(site_admin)])


@router.get("/overview", response_model=AdminOverview,
            summary="總覽：使用者人數、AI 金鑰槽的本月用量（不含金鑰）、各資料集的最新資料日期、歷史日線回補")
def overview(db: Session = Depends(get_db)):
    return svc.overview(db)


@router.get("/news/blocked-domains", response_model=list[BlockedDomain], summary="新聞下架的封鎖清單")
def blocked_domains(db: Session = Depends(get_db)):
    return svc.blocked_list(db)


@router.post("/news/blocked-domains", response_model=BlockDomainOut, status_code=201,
             summary="封鎖一個網域（含子網域），並刪掉已存的標題")
def block_domain(body: BlockDomainIn, db: Session = Depends(get_db)):
    return svc.block(db, body.domain, body.reason)


@router.delete("/news/blocked-domains/{domain}", status_code=204, response_class=Response,
               summary="解除封鎖（設定在 NEWS_BLOCKED_DOMAINS 的不能解除：409）")
def unblock_domain(domain: str = Path(max_length=300), db: Session = Depends(get_db)):
    svc.unblock(db, domain)
    return Response(status_code=204)


@router.get("/members", response_model=list[AdminMember], summary="會員（站方手動開通的；過期的也列出，方便續期）")
def list_members(db: Session = Depends(get_db)):
    return plans.members(db)


@router.put("/members", response_model=AdminMember,
            summary="開通或續期會員（用 email 找帳號；對方要先登入過一次，否則 404）")
def grant_member(body: MemberGrantIn, db: Session = Depends(get_db)):
    return plans.grant(db, body.email, body.until, body.note)


@router.delete("/members/{user_id}", status_code=204, response_class=Response, summary="取消會員（改回免費）")
def revoke_member(user_id: str = Path(max_length=32), db: Session = Depends(get_db)):
    plans.revoke(db, user_id)
    return Response(status_code=204)


# -- 群組加值包 (no payments yet: granted by hand; the admin never sees a group's name or content) ------------------
@router.get("/group-passes", response_model=list[AdminGroupPass],
            summary="群組加值包（站方手動開通的；到期的也列出，方便延長）")
def list_group_passes(db: Session = Depends(get_db)):
    return group_plans.admin_list(db)


@router.post("/group-passes", response_model=AdminGroupPass, status_code=201,
             summary="開通群組加值包（用付款人的 email；給 group_id 就直接用在那個群組，付款人必須是擁有者）")
def grant_group_pass(body: GroupPassGrantIn, db: Session = Depends(get_db)):
    return group_plans.admin_grant(db, body.email, body.until, body.note, body.group_id)


@router.patch("/group-passes/{pass_id}", response_model=AdminGroupPass, summary="延長（或縮短）、改備註")
def patch_group_pass(body: GroupPassPatch, pass_id: str = Path(max_length=32), db: Session = Depends(get_db)):
    return group_plans.admin_update(db, pass_id, body.model_dump(exclude_unset=True))


@router.delete("/group-passes/{pass_id}", status_code=204, response_class=Response,
               summary="取消群組加值包（群組回到免費的上限；不會移除任何成員）")
def revoke_group_pass(pass_id: str = Path(max_length=32), db: Session = Depends(get_db)):
    group_plans.admin_revoke(db, pass_id)
    return Response(status_code=204)
