"""The site admins' back office (``/admin``): a read-only overview and the news takedown blocklist.

Site admins are ``ADMIN_EMAILS`` (``services.discussions.is_site_admin``); everyone else gets 404 from the routes.
Nothing here returns an email, a user id or key material: user numbers are counts, key slots are the pool's status
(slot number, state, workspace id, this month's estimated cost and calls) and never the key itself.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa import history_backfill
from forliosa.ai import store
from forliosa.ai.keypool import get_key_pool
from forliosa.api.errors import ApiError, not_found, unprocessable
from forliosa.config import Settings, get_settings
from forliosa.datapolicy import DATASETS, history_backfill_enabled, label
from forliosa.market_calendar import load_official_calendar
from forliosa.models import DatasetStatus, NewsBlockedDomain, User
from forliosa.news import service as news
from forliosa.news.normalize import normalize_domain
from forliosa.timeutil import iso_taipei, now_utc, today_taipei, tw_trading_days

NEW_USER_DAYS = 7
# A dataset whose newest data is this many trading days behind today is marked stale (「已經 N 天沒有新資料」).
STALE_TRADING_DAYS = 3
BACKFILL_STATUSES = ("done", "not_found", "mismatch", "no_overlap", "error")
REASON_MAX = 200
# One host name: labels without spaces, slashes or colons, at least one dot (``udn.com``, ``money.udn.com``).
_DOMAIN_RE = re.compile(r"^[^\s./:@]+(\.[^\s./:@]+)+$")


# -- overview -----------------------------------------------------------------------------------------------
def users_summary(db: Session, now: datetime | None = None) -> dict[str, int]:
    """Counts only. Sessions keep no last-seen time, so there is no "active users" number."""
    since = (now or now_utc()) - timedelta(days=NEW_USER_DAYS)
    total = db.scalar(select(func.count()).select_from(User)) or 0
    new = db.scalar(select(func.count()).select_from(User).where(User.created_at >= since)) or 0
    return {"total": int(total), "new_7d": int(new)}


def ai_summary(db: Session) -> dict[str, Any]:
    """This UTC month per key slot (the pool's budgets follow Anthropic's billing month). Fields are picked one by
    one from the pool's status, so nothing else it may carry can reach the response."""
    costs, calls = store.slot_month_usage(db)
    slots = get_key_pool().status(costs, calls, store.slot_thread_counts(db))
    keep = ("slot", "configured", "state", "retry_in_seconds", "workspace_id", "month_cost_usd", "month_calls",
            "monthly_budget_usd", "threads", "last_error")
    return {"month": store.utc_month_start().strftime("%Y-%m"), "slots": [{k: s.get(k) for k in keep} for s in slots]}


def _dataset_name(key: str) -> tuple[str, str | None]:
    ds = DATASETS.get(key)
    if ds is not None:
        return ds.title, ds.agency
    return label(key), None


def datasets_summary(db: Session, today: date | None = None) -> list[dict[str, Any]]:
    """Every ``dataset_status`` row, the stalest first. ``stale``: the newest data is at least
    :data:`STALE_TRADING_DAYS` trading days behind today (official calendar when archived); ``days_behind`` is
    calendar days, for the sentence 「已經 N 天沒有新資料」."""
    load_official_calendar(db)
    today = today or today_taipei()
    out = []
    for row in db.scalars(select(DatasetStatus)):
        name, agency = _dataset_name(row.key)
        d = row.data_date
        behind = (today - d).days if d else None
        missed = len(tw_trading_days(d + timedelta(days=1), today)) if d and d < today else 0
        out.append({"key": row.key, "name": name, "agency": agency,
                    "data_date": d.isoformat() if d else None,
                    "fetched_at": iso_taipei(row.fetched_at) if row.fetched_at else None,
                    "days_behind": behind, "stale": d is None or missed >= STALE_TRADING_DAYS})
    # Stalest first: no date at all, then the oldest data date; ties by key.
    out.sort(key=lambda r: (r["data_date"] is not None, r["data_date"] or "", r["key"]))
    return out


def backfill_summary(db: Session) -> dict[str, Any]:
    counts = history_backfill.summary(db)
    return {"enabled": history_backfill_enabled(), "rows": int(counts.get("rows", 0)),
            "pending": int(counts.get("pending", 0)),
            "symbols": {s: int(counts.get(s, 0)) for s in BACKFILL_STATUSES}}


def overview(db: Session) -> dict[str, Any]:
    return {"users": users_summary(db), "ai": ai_summary(db), "datasets": datasets_summary(db),
            "history_backfill": backfill_summary(db)}


# -- news takedown blocklist --------------------------------------------------------------------------------
def env_blocked(settings: Settings | None = None) -> set[str]:
    settings = settings or get_settings()
    return {d for d in (normalize_domain(x) for x in settings.news_blocked_domains) if d}


def blocked_list(db: Session) -> list[dict[str, Any]]:
    """The stored entries (newest first), then the ones set in ``NEWS_BLOCKED_DOMAINS`` that are not stored."""
    env = env_blocked()
    rows = sorted(db.scalars(select(NewsBlockedDomain)),
                  key=lambda r: (r.created_at.timestamp() if r.created_at else 0.0, r.domain), reverse=True)
    out = [{"domain": r.domain, "reason": r.reason, "created_at": iso_taipei(r.created_at) if r.created_at else None,
            "from_env": r.domain in env} for r in rows]
    stored = {r.domain for r in rows}
    out += [{"domain": d, "reason": None, "created_at": None, "from_env": True} for d in sorted(env - stored)]
    return out


def clean_domain(raw: str) -> str:
    d = normalize_domain(raw)
    if not _DOMAIN_RE.match(d) or len(d) > 253:
        raise unprocessable("請輸入網域，例如 example.com。")
    return d


def block(db: Session, raw: str, reason: str | None) -> dict[str, Any]:
    d = clean_domain(raw)
    deleted = news.block_domain(db, d, reason)
    return {"domain": d, "deleted_headlines": deleted}


def unblock(db: Session, raw: str) -> None:
    d = normalize_domain(raw)
    if d in env_blocked():
        raise ApiError(409, "set_in_environment", "這個網域寫在伺服器設定裡，這裡不能解除。")
    if not news.unblock_domain(db, d):
        raise not_found("封鎖清單裡沒有這個網域")
