"""The back office's 「市場報告」 (contract §14.2): status and spending, the mode and the writer per kind, corrections,
rebuilding a data edition, and the three hand-kept tables (NYSE closures, the macro calendar, US earnings dates).
The blind test's endpoints (``/market-reports/trial``, ``/trial/reveal``, ``/{id}/variants/{label}``,
``/{id}/vote``) were removed with it (產品負責人 2026-11-18): 404.

Guarded like ``routes.admin``: signed in (401) and a site admin (``ADMIN_EMAILS``) or 404 — before the body is
validated. Never under ``X-Forliosa-View-As`` (403).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import Depends, Path, Query, Response
from sqlalchemy.orm import Session

from forliosa.api.routes.admin import site_admin
from forliosa.api.routing import Router
from forliosa.api.schemas_reports import (
    CorrectionIn,
    EarningsIn,
    MacroIn,
    MarketReport,
    NyseIn,
    RebuildIn,
    ReportsConfigIn,
)
from forliosa.db import get_db
from forliosa.models import User
from forliosa.reports import service as svc

router = Router(prefix="/admin", tags=["admin"], dependencies=[Depends(site_admin)])


@router.get("/market-reports/overview",
            summary="市場報告：模式、撰寫設定、花費與層級、最近的產生紀錄、手動表")
def overview(db: Session = Depends(get_db)) -> dict[str, Any]:
    return svc.overview(db)


@router.put("/market-reports/config", summary="切換模式或存下每種報告的撰寫設定")
def put_config(body: ReportsConfigIn, user: User = Depends(site_admin), db: Session = Depends(get_db)) \
        -> dict[str, Any]:
    raw = body.model_dump(exclude_unset=True)
    if body.writers is not None:
        raw["writers"] = {k: (v.model_dump() if v is not None else None)
                          for k, v in body.writers if k in body.writers.model_fields_set}
    return svc.put_config(db, user, raw)


@router.post("/market-reports/rebuild-data", summary="重建資料版（不呼叫 AI）")
def rebuild(body: RebuildIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    return svc.rebuild_data(db, body.kind, body.edition_date)


@router.post("/market-reports/{report_id}/corrections", response_model=MarketReport,
             summary="更正：新增一版（標示已更正，不推播）")
def correction(report_id: str, body: CorrectionIn, user: User = Depends(site_admin), db: Session = Depends(get_db)):
    return svc.correction(db, user, report_id, body.note, body.drop_sections)


# -- the hand-kept tables ----------------------------------------------------------------------------------------
@router.get("/market-calendar/nyse", summary="美股休市與提早收盤表")
def nyse_list(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return svc.nyse_list(db)


@router.put("/market-calendar/nyse/{day}", summary="新增或修改一列（verified：已到 NYSE 官方頁核對）")
def nyse_put(body: NyseIn, day: date = Path(...), user: User = Depends(site_admin), db: Session = Depends(get_db)) \
        -> dict[str, Any]:
    return svc.nyse_put(db, user, day, body.model_dump())


@router.delete("/market-calendar/nyse/{day}", status_code=204, response_class=Response, summary="刪除一列")
def nyse_delete(day: date = Path(...), db: Session = Depends(get_db)):
    svc.nyse_delete(db, day)
    return Response(status_code=204)


@router.get("/market-calendar/macro", summary="總經行事曆（只連官方頁面）")
def macro_list(start: date | None = Query(None, alias="from"), end: date | None = Query(None, alias="to"),
               db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return svc.macro_list(db, start, end)


@router.post("/market-calendar/macro", status_code=201, summary="新增總經行事曆一列")
def macro_add(body: MacroIn, user: User = Depends(site_admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    return svc.macro_add(db, user, body.model_dump())


@router.delete("/market-calendar/macro/{mid}", status_code=204, response_class=Response, summary="刪除一列")
def macro_delete(mid: str, db: Session = Depends(get_db)):
    svc.macro_delete(db, mid)
    return Response(status_code=204)


@router.get("/market-calendar/us-earnings", summary="美股財報日")
def earnings_list(start: date | None = Query(None, alias="from"), end: date | None = Query(None, alias="to"),
                  db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return svc.earnings_list(db, start, end)


@router.post("/market-calendar/us-earnings", status_code=201, summary="新增美股財報日一列")
def earnings_add(body: EarningsIn, user: User = Depends(site_admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    return svc.earnings_add(db, user, body.model_dump())


@router.delete("/market-calendar/us-earnings/{eid}", status_code=204, response_class=Response, summary="刪除一列")
def earnings_delete(eid: str, db: Session = Depends(get_db)):
    svc.earnings_delete(db, eid)
    return Response(status_code=204)
