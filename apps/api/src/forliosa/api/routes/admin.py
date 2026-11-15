"""The site admins' back office (docs/api-contract.md 「管理後台」): an overview, the news takedown blocklist and the
members granted by hand (``forliosa.plans``; no payments yet).

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
    AdminMember,
    AdminOverview,
    BlockDomainIn,
    BlockDomainOut,
    BlockedDomain,
    MemberGrantIn,
)
from forliosa.db import get_db
from forliosa.models import User
from forliosa.services import admin as svc
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
