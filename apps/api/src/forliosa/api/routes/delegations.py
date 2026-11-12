"""Read-only delegations (授權唯讀查看): grant, change, revoke; candidates are members of a shared group."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from forliosa.api.deps import signed_in_user
from forliosa.api.schemas_sharing import (
    DelegationCandidate,
    DelegationIn,
    DelegationOut,
    DelegationPatch,
    Delegations,
)
from forliosa.db import get_db
from forliosa.models import User
from forliosa.services import delegations as svc

router = APIRouter(prefix="/delegations", tags=["delegations"])


@router.get("", response_model=Delegations, summary="我授權給別人的（granted）與別人授權給我的（received）")
def list_delegations(user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    return svc.list_all(db, user)


@router.get("/candidates", response_model=list[DelegationCandidate], summary="可以授權的人：和我同群組的成員")
def candidates(user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    return svc.candidates(db, user)


@router.post("", response_model=DelegationOut, status_code=201)
def create(body: DelegationIn, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    return svc.delegation_out(db, svc.create(db, user, body.viewer_user_id, body.scope, body.account_ids))


@router.patch("/{delegation_id}", response_model=DelegationOut, summary="授權者修改範圍")
def update(delegation_id: str, body: DelegationPatch, user: User = Depends(signed_in_user),
           db: Session = Depends(get_db)):
    return svc.delegation_out(db, svc.update(db, user, delegation_id, body.scope, body.account_ids))


@router.delete("/{delegation_id}", status_code=204, response_class=Response,
               summary="授權者撤銷，或被授權者自己移除（立即生效）")
def remove(delegation_id: str, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    svc.remove(db, user, delegation_id)
    return Response(status_code=204)
