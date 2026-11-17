"""Portfolio summary, holdings and performance; counting and clearing every record (清除所有持倉,
``/portfolio/records``)."""

from __future__ import annotations

from datetime import timedelta

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from forliosa.api.deps import current_user
from forliosa.api.errors import unprocessable
from forliosa.api.routes.accounts import get_owned_account
from forliosa.api.routing import Router
from forliosa.api.schemas import (
    ClosedRound,
    Holding,
    Performance,
    PortfolioSummary,
    RecordCounts,
    RecordsCleared,
    UpcomingItem,
)
from forliosa.db import get_db
from forliosa.marketdata.service import get_market_data
from forliosa.models import User
from forliosa.services import portfolio as svc
from forliosa.services import recurring
from forliosa.services import transactions as txn_svc
from forliosa.timeutil import today_taipei

router = Router(prefix="/portfolio", tags=["portfolio"])


@router.get("/summary", response_model=PortfolioSummary)
def portfolio_summary(account_id: str | None = None, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    md = get_market_data()
    return svc.summary(svc.compute_state(db, user, md, account_id), md)


@router.get("/holdings", response_model=list[Holding])
def portfolio_holdings(account_id: str | None = None, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    return svc.holdings(svc.compute_state(db, user, get_market_data(), account_id))


@router.get("/closed", response_model=list[ClosedRound], summary="出清紀錄：已全部賣出的持股回合（最近出清的在前）")
def portfolio_closed(account_id: str | None = None, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    md = get_market_data()
    return svc.closed_positions(svc.ledger_view(db, user, md, account_id), md)


@router.get("/performance", response_model=Performance)
def portfolio_performance(
    range: str = Query("1Y"),
    benchmark: str | None = None,
    account_id: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return svc.performance(db, user, get_market_data(), range.upper(), benchmark, account_id)


@router.get("/upcoming", response_model=list[UpcomingItem], summary="本週事項：持股的除息、股利入帳、定期定額扣款")
def portfolio_upcoming(days: int = Query(7), account_id: str | None = None,
                       types: str | None = Query(None, pattern="^recurring$",
                                                 description="recurring：只回定期定額扣款（不算持股與股利，快很多）"),
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    md = get_market_data()
    if types == "recurring":  # the AI panel on every page only needs today's debits (2026-11-17 API speed)
        return svc.upcoming_recurring(db, user, md, days, account_id)
    state = svc.compute_state(db, user, md, account_id)
    today = today_taipei()
    plans = recurring.upcoming_items(db, user, md, [a.id for a in state.inp.accounts], today,
                                     today + timedelta(days=days)) if 1 <= days <= svc.UPCOMING_MAX_DAYS else []
    return svc.upcoming(state, md, days, plans)


@router.get("/records", response_model=RecordCounts, summary="每個帳戶有幾筆紀錄（清除所有持倉的確認框用）")
def portfolio_records(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Counts only (the records themselves are ``GET /transactions``). Not served while viewing someone's ledger
    (``view_as_not_allowed``): clearing is the owner's own business."""
    res = txn_svc.record_counts(db, user)

    def out(c: txn_svc.RecordCount) -> dict:
        return {"records": c.records, "trades": c.trades, "dividends": c.dividends, "symbols": c.symbols,
                "plans_running": c.plans_running}

    return {**out(res.total), "accounts": [{"account_id": a, **out(c)} for a, c in res.accounts]}


@router.delete("/records", response_model=RecordsCleared,
               summary="清除所有持倉：一個帳戶或全部帳戶的每一筆紀錄（不能復原）")
def clear_records(account_id: str | None = None,
                  all_accounts: bool = Query(default=False, description="全部帳戶（和 account_id 二選一）"),
                  pause_plans: bool = Query(default=False, description="同時暫停範圍裡的定期定額"),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Every record of ``account_id``, or of every account with ``all_accounts=true`` — one of the two, never by
    default: a bare ``DELETE /portfolio/records`` is a 422, not a wipe (``services.transactions.clear_records``).
    404 ``not_found`` when the account is not the user's, 404 ``no_records`` when there is nothing to clear; 403
    ``read_only`` while viewing someone's ledger (``api.middleware``)."""
    if (account_id is None) == (not all_accounts):
        raise unprocessable("要指定一個帳戶，或是全部帳戶", code="scope_required")
    if account_id is not None:
        account_id = get_owned_account(db, user, account_id).id
    res = txn_svc.clear_records(db, user, account_id, pause_plans=pause_plans)
    return {"account_id": res.account_id, "deleted": res.deleted, "symbols": res.symbols,
            "plans_paused": res.plans_paused, "plans_running": res.plans_running}
