"""The site admins' back office (``/admin``): a read-only overview and the news takedown blocklist.

Site admins are ``ADMIN_EMAILS`` (``services.discussions.is_site_admin``); everyone else gets 404 from the routes.
Nothing here returns an email, a user id or key material: user numbers are counts, key slots are the pool's status
(slot number, state, workspace id, this month's estimated cost and calls) and never the key itself.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa import backup, history_backfill, perfcache
from forliosa.ai import store
from forliosa.ai.keypool import get_key_pool
from forliosa.api.errors import ApiError, not_found, unprocessable
from forliosa.config import Settings, get_settings
from forliosa.datapolicy import DATASETS, history_backfill_enabled, label
from forliosa.market_calendar import load_official_calendar
from forliosa.models import DatasetStatus, NewsArticle, NewsBlockedDomain, NewsFetchState, User
from forliosa.news import ai_search as news_ai
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
    # ``purpose``: "market_reports" on the market reports' own slot (``AI_MREPORT_KEY_SLOT``), else null
    keep = ("slot", "configured", "state", "retry_in_seconds", "workspace_id", "month_cost_usd", "month_calls",
            "monthly_budget_usd", "threads", "last_error", "purpose")
    return {"month": store.utc_month_start().strftime("%Y-%m"), "slots": [{k: s.get(k) for k in keep} for s in slots]}


def _dataset_name(key: str) -> tuple[str, str | None]:
    if key == backup.STATUS_KEY:  # the nightly pg_dump: flagged here once backups stop (forliosa.backup)
        return "資料庫備份", "Railway Bucket"
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


# The admin overview counted prices_daily rows of two sources on every load: two full scans of 3M rows, ~0.5 s
# (2026-11-17). The counts are kept 10 minutes (exact, at most 10 minutes old).
_PRICE_ROWS = perfcache.TtlCache("admin.price_rows", ttl=600, maxsize=8)


def cached_price_rows(db: Session, source: str) -> int:
    return _PRICE_ROWS.get_or_compute(source, lambda: history_backfill.price_rows(db, source))


def backfill_summary(db: Session) -> dict[str, Any]:
    counts = history_backfill.summary(db, rows_fn=cached_price_rows)
    return {"enabled": history_backfill_enabled(), "rows": int(counts.get("rows", 0)),
            "pending": int(counts.get("pending", 0)),
            "symbols": {s: int(counts.get(s, 0)) for s in BACKFILL_STATUSES}}


def news_summary(db: Session, now: datetime | None = None, policy: str | None = None) -> dict[str, Any]:
    """The news sources as the worker sees them (``news_fetch_state``): each source on or off, paused after a refusal
    (the source-wide row ``symbol = "*"``), when it last answered a symbol, and how many headlines it stored in the
    last 24 hours. Counts and times only."""
    settings = get_settings()
    now = now or now_utc()
    policy = policy or settings.data_policy
    since = now - timedelta(hours=24)
    stored = dict(db.execute(select(NewsArticle.source, func.count()).where(NewsArticle.fetched_at >= since)
                             .group_by(NewsArticle.source)).all())
    rows = list(db.scalars(select(NewsFetchState)))
    wide = {r.source: r for r in rows if r.symbol == news.SOURCE_WIDE}
    per_symbol = [r for r in rows if r.symbol != news.SOURCE_WIDE and not r.symbol.startswith(news.ENGINE_PREFIX)]
    last_ok: dict[str, datetime] = {}
    for r in per_symbol:
        if r.last_success_at is not None:
            last_ok[r.source] = max(last_ok.get(r.source, r.last_success_at), r.last_success_at)
    attempts = [r.last_attempt_at for r in per_symbol if r.last_attempt_at is not None]
    ai_spent = news_ai.month_spend(db, now)
    ai_on = settings.news_ai_enabled and settings.news_ai_budget_usd > 0
    searxng_on = bool(settings.news_searxng_enabled and settings.searxng_url)
    configured = [("gdelt", settings.news_gdelt_enabled), ("searxng", searxng_on), ("ai_search", ai_on)]
    if policy == "personal":
        configured.append(("yahoo_rss", settings.news_yahoo_rss))
    configured.append(("langsearch", settings.langsearch_on))
    sources = []
    for key, on in configured:
        row = wide.get(key)
        until = _aware(row.backoff_until) if row is not None and row.backoff_until is not None else None
        paused = on and until is not None and until > now
        reason = (row.last_status if row.last_status in ("rate_limited", "blocked", "unreachable") else "blocked") \
            if paused and row is not None else None
        if on and not paused and key == "ai_search" and not news_ai.budget_left(db, settings, now):
            paused, reason = True, "budget"
        sources.append({"key": key, "name": news.SOURCE_INFO[key][0],
                        "state": "off" if not on else "paused" if paused else "ok",
                        "paused_until": iso_taipei(until) if paused and until is not None else None,
                        "reason": reason, "last_success_at": iso_taipei(last_ok[key]) if key in last_ok else None,
                        "new_24h": int(stored.get(key, 0))})
    engines = sorted(
        ({"engine": r.symbol[len(news.ENGINE_PREFIX):], "until": iso_taipei(_aware(r.backoff_until))}
         for r in rows if r.source == "searxng" and r.symbol.startswith(news.ENGINE_PREFIX)
         and r.backoff_until is not None and _aware(r.backoff_until) > now),
        key=lambda e: e["engine"])
    return {"enabled": settings.news_enabled, "refresh_minutes": settings.news_refresh_minutes,
            "last_run_at": iso_taipei(max(attempts)) if attempts else None,
            "new_24h": int(sum(stored.values())), "sources": sources, "paused_engines": engines,
            "ai_month_cost_usd": float(round(ai_spent, 4)), "ai_budget_usd": float(settings.news_ai_budget_usd),
            "langsearch": langsearch_summary(db, now)}


def langsearch_summary(db: Session, now: datetime | None = None) -> dict[str, Any]:
    """LangSearch's UTC day (counts only): requests and tokens against the caps, what stopped it, the degradation
    level, the tiers, and ``warning: "contents_cap_ignored"`` when an answer came back far above the token guard."""
    from forliosa.news import langsearch

    st = langsearch.status(db, now=now)
    until = st.pop("paused_until")
    return {**st, "paused_until": iso_taipei(until) if until is not None else None}


def _aware(dt: datetime) -> datetime:
    """SQLite returns naive datetimes: they are UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def overview(db: Session) -> dict[str, Any]:
    from forliosa import us_prices

    return {"users": users_summary(db), "ai": ai_summary(db), "datasets": datasets_summary(db),
            "history_backfill": backfill_summary(db), "us_prices": us_prices.summary(db, rows_fn=cached_price_rows),
            "news": news_summary(db)}


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
