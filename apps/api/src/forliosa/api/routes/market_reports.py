"""市場報告 for signed-in users (contract §14.1, §16): the status (is there anything to read, the unread dot), the
list, the latest of a kind, one report (an older version with ``?version=``) and 「seen」.

Every endpoint needs a signed-in user; there is no public address. Every edition is public (an admin-only one — a CLI
backfill — is read by site admins only, 404 for anyone else). The blind test's ``/{id}/trial``,
``/{id}/variants/{label}`` and ``PUT /{id}/vote`` were removed with it (產品負責人 2026-11-18): 404. Under
``X-Forliosa-View-As`` the reads answer as the signed-in viewer (a report holds no user data); 「seen」 is a write and
refused there (``api.middleware``).
"""

from __future__ import annotations

from typing import Literal

from fastapi import Depends, Query, Response
from sqlalchemy.orm import Session

from forliosa.api.deps import signed_in_user
from forliosa.api.routing import Router
from forliosa.api.schemas_reports import MarketReport, ReportsPage, ReportsStatus
from forliosa.db import get_db
from forliosa.models import User
from forliosa.reports import service as svc

router = Router(prefix="/market/reports", tags=["market-reports"])
KindQ = Literal["premarket", "close", "weekly"]


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


@router.get("/{report_id}", response_model=MarketReport, summary="一份報告（version 可看舊版）")
def one(report_id: str, version: int | None = Query(None, ge=1), user: User = Depends(signed_in_user),
        db: Session = Depends(get_db)):
    return svc.one(db, user, report_id, version)
