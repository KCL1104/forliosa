"""市場報告 for signed-in users (contract §14.1, §16): the status (is there anything to read, the unread dot), the
list, the latest of a kind, one report (an older version with ``?version=``) and 「seen」.

Every endpoint needs a signed-in user; there is no public address. A blind-test or trial-mode edition is read by site
admins only (404 for anyone else) — except while the blind test is open to everyone (``MREPORT_TRIAL_AUDIENCE=all``
or the admin page): then every signed-in user reads its A / B / C (``/{id}/trial``, ``/{id}/variants/{label}``) and
votes (``PUT /{id}/vote``, changeable until the reveal). Under ``X-Forliosa-View-As`` the reads answer as the
signed-in viewer (a report holds no user data); 「seen」 and the vote are writes and refused there
(``api.middleware``).
"""

from __future__ import annotations

from typing import Literal

from fastapi import Depends, Query, Response
from sqlalchemy.orm import Session

from forliosa.api.deps import signed_in_user
from forliosa.api.routing import Router
from forliosa.api.schemas_reports import MarketReport, MemberVoteIn, ReportsPage, ReportsStatus, TrialView
from forliosa.db import get_db
from forliosa.models import User
from forliosa.reports import service as svc

router = Router(prefix="/market/reports", tags=["market-reports"])
KindQ = Literal["premarket", "close", "weekly"]
LabelP = Literal["A", "B", "C"]


@router.get("/status", response_model=ReportsStatus, summary="有沒有報告可看、未讀、每種最新一份")
def status(user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    return svc.status(db, user)


@router.get("", response_model=ReportsPage, summary="報告清單（新到舊；週報、盤後、盤前）")
def list_reports(kind: KindQ | None = None, limit: int = Query(20, ge=1, le=50),
                 cursor: str | None = Query(None, max_length=300), user: User = Depends(signed_in_user),
                 db: Session = Depends(get_db)):
    return svc.list_reports(db, user, kind, limit, cursor)


@router.get("/latest", response_model=MarketReport | None, summary="最新一份（kind 省略＝任一種最新的）")
def latest(kind: KindQ | None = None, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    return svc.latest(db, user, kind)


@router.post("/seen", status_code=204, response_class=Response, summary="看過了（未讀小圓點消失）")
def seen(user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    svc.mark_seen(db, user)
    return Response(status_code=204)


@router.get("/{report_id}/trial", response_model=TrialView,
            summary="盲測的一份：A／B／C 哪些能看、我的票、能不能改；揭曉後附上每個版本的設定與票數")
def trial(report_id: str, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    return svc.trial_view(db, user, report_id)


@router.get("/{report_id}/variants/{label}", response_model=MarketReport,
            summary="盲測的一個版本（一般形式：沒有 refs、模型、花費）；還在寫 409 variant_running")
def variant(report_id: str, label: LabelP, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    return svc.member_variant(db, user, report_id, label)


@router.put("/{report_id}/vote", response_model=TrialView,
            summary="盲測投票（每人每份一票，揭曉前可以改；揭曉後 409 trial_revealed）")
def vote(report_id: str, body: MemberVoteIn, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    return svc.member_vote(db, user, report_id, body.preferred)


@router.get("/{report_id}", response_model=MarketReport, summary="一份報告（version 可看舊版）")
def one(report_id: str, version: int | None = Query(None, ge=1), user: User = Depends(signed_in_user),
        db: Session = Depends(get_db)):
    return svc.one(db, user, report_id, version)
