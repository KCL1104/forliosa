"""每日收盤簡報: the signed-in user's own briefings (``forliosa.ai.briefing``).

The worker writes them; these endpoints only read them and record that one was read. The switch is the
``daily_briefing`` preference (``PATCH /me/preferences``). Not served in view-as mode (the middleware refuses every
``/ai`` path there): a briefing is about the viewer's own ledger, not the one being looked at.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from forliosa.ai import briefing
from forliosa.api.deps import current_user
from forliosa.api.schemas import Briefing
from forliosa.db import get_db
from forliosa.models import User

router = APIRouter(prefix="/ai/briefings", tags=["ai"])


@router.get("/latest", response_model=Briefing | None,
            summary="最新一則收盤簡報（過了兩個交易日就不算最新，回 null；沒開或還沒產生也是 null）")
def latest(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return briefing.latest(db, user)


@router.get("", response_model=list[Briefing], summary="最近的收盤簡報（新的在前；保留 30 天）")
def recent(limit: int = Query(14, ge=1, le=30), user: User = Depends(current_user), db: Session = Depends(get_db)):
    return briefing.recent(db, user, limit)


@router.post("/{briefing_id}/read", status_code=204, response_class=Response, summary="標示這則簡報看過了")
def read(briefing_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    briefing.mark_read(db, user, briefing_id)
    return Response(status_code=204)
