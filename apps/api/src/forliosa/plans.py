"""會員方案: who is a member and what each plan gets (產品負責人 2026-11-15).

Free accounts: ``AI_DAILY_MESSAGE_LIMIT`` questions a day (3) and about ``AI_MONTHLY_COST_BUDGET_USD`` a month (US$1);
no 深度搜尋 and no daily closing briefing. Members: ``AI_MEMBER_DAILY_MESSAGE_LIMIT`` (30), about
``AI_MEMBER_MONTHLY_COST_BUDGET_USD`` (US$3), both features. Over the month's budget either plan keeps asking without
Claude's web search (省錢模式, ``store.month_mode``).

A member is ``users.plan = "member"`` until ``users.plan_until`` (NULL: no end date). Site admins (``ADMIN_EMAILS``)
count as members. There are no payments yet: a site admin grants membership on /admin/members (``grant``).

匯入對帳單 (2026-11-16) does not depend on the tier: ``IMPORT_STATEMENTS`` opens it to nobody, site admins, or everyone
(``Plan.statement_import``; ``GET /me`` → ``plan.statement_import``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.api.errors import ApiError
from forliosa.config import Settings
from forliosa.models import User
from forliosa.services.discussions import is_site_admin
from forliosa.timeutil import TAIPEI, now_utc

FREE, MEMBER = "free", "member"
NOTE_MAX = 200


@dataclass(frozen=True)
class Plan:
    tier: str  # FREE or MEMBER
    until: datetime | None  # when membership ends (None: free, or a member with no end date)
    daily_message_limit: int  # 0: no limit
    monthly_cost_budget_usd: float  # 0: no limit
    monthly_token_budget: int  # 0: no limit
    deep_search: bool
    daily_briefing: bool
    # 匯入對帳單 (2026-11-16): ``IMPORT_STATEMENTS`` off | admins | all, the same for free accounts and members
    statement_import: bool = False

    @property
    def member(self) -> bool:
        return self.tier == MEMBER


def is_member(user: User, now: datetime | None = None) -> bool:
    if is_site_admin(user):
        return True
    return user.plan == MEMBER and (user.plan_until is None or user.plan_until > (now or now_utc()))


def statement_import_open(user: User, settings: Settings) -> bool:
    """``IMPORT_STATEMENTS``: ``all`` opens 匯入對帳單 to every account, ``admins`` to site admins only."""
    mode = settings.import_statements
    return mode == "all" or (mode == "admins" and is_site_admin(user))


def plan_of(user: User, settings: Settings, now: datetime | None = None) -> Plan:
    imports = statement_import_open(user, settings)
    if is_member(user, now):
        return Plan(MEMBER, None if is_site_admin(user) else user.plan_until,
                    settings.ai_member_daily_message_limit, settings.ai_member_monthly_cost_budget_usd,
                    settings.ai_member_monthly_token_budget, True, True, imports)
    return Plan(FREE, None, settings.ai_daily_message_limit, settings.ai_monthly_cost_budget_usd,
                settings.ai_monthly_token_budget, settings.ai_free_deep_search, settings.ai_free_daily_briefing,
                imports)


def last_day(until: datetime | None) -> date | None:
    """The last day (Taipei) of a membership ending at ``until``."""
    return None if until is None else (until.astimezone(TAIPEI) - timedelta(microseconds=1)).date()


def me_fields(user: User, settings: Settings) -> dict[str, Any]:
    p = plan_of(user, settings)
    return {"plan": {"tier": p.tier, "until": d.isoformat() if (d := last_day(p.until)) else None,
                     "deep_search": p.deep_search, "daily_briefing": p.daily_briefing,
                     "statement_import": p.statement_import}}


# -- site admins: grant and revoke ----------------------------------------------------------------------------------
def _row(user: User, now: datetime) -> dict[str, Any]:
    d = last_day(user.plan_until)
    return {"user_id": user.id, "email": user.email, "display_name": user.display_name,
            "until": d.isoformat() if d else None, "note": user.plan_note,
            "active": user.plan_until is None or user.plan_until > now}


def members(db: Session, now: datetime | None = None) -> list[dict[str, Any]]:
    """Every account granted membership (expired ones too, so they can be renewed), active first then by end date."""
    now = now or now_utc()
    rows = [_row(u, now) for u in db.scalars(select(User).where(User.plan == MEMBER))]
    return sorted(rows, key=lambda r: (not r["active"], r["until"] or "9999-12-31", r["email"]))


def grant(db: Session, email: str, until: date | None, note: str | None, now: datetime | None = None) -> dict[str, Any]:
    """Make the account with this email a member through ``until`` (the last day, Taipei; None: no end date). The
    person must have signed in once: there is no account to grant to otherwise (404)."""
    now = now or now_utc()
    user = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    if user is None:
        raise ApiError(404, "user_not_found", "找不到這個 email 的帳號：請對方先登入一次 Forliosa。")
    if until is not None and until < now.astimezone(TAIPEI).date():
        raise ApiError(422, "until_in_past", "到期日不能早於今天。")
    user.plan = MEMBER
    user.plan_until = (None if until is None
                       else datetime.combine(until + timedelta(days=1), time(0), tzinfo=TAIPEI))
    user.plan_note = note
    db.commit()
    return _row(user, now)


def revoke(db: Session, user_id: str) -> None:
    user = db.get(User, user_id)
    if user is None or user.plan != MEMBER:
        raise ApiError(404, "not_found", "這個帳號不是會員。")
    user.plan, user.plan_until, user.plan_note = FREE, None, None
    db.commit()
