"""What the market-report endpoints do (contract §14, §16): visibility, the list, one report, the unread dot, and the
admin side — overview, settings, corrections, rebuilding a data edition, and the three hand-kept tables.

Visibility: a ``public`` edition is read by every signed-in user; an ``admin`` one (CLI backfills, a by-hand edition
while paused) by site admins only — anyone else gets 404 「找不到這份報告」. With MARKET_REPORTS_ENABLED off nothing is
available. A member always reads the public form (:func:`assemble.public`: no refs, no dropped text, no quotes).

The blind test (A / B / C, votes, the reveal) was removed (產品負責人 2026-11-18): every edition is written once and
public; its member and admin endpoints are gone (404). The votes, the runs and the other variants' versions of the
editions it wrote stay in the database as history (migration ``0028_remove_blind_test`` made each of those editions
a normal public one).
"""

from __future__ import annotations

import base64
import binascii
import copy
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from forliosa.api.errors import ApiError, not_found, unprocessable
from forliosa.config import Settings, get_settings
from forliosa.ids import new_id
from forliosa.models import (
    MacroCalendarEvent,
    MarketReport,
    MarketReportConfig,
    MarketReportGather,
    MarketReportRead,
    MarketReportRun,
    MarketReportVersion,
    NyseHoliday,
    UsEarningsDate,
    User,
)
from forliosa.reports import accounting, assemble, calendars, pipeline
from forliosa.reports import settings as rs
from forliosa.reports.schedule import KIND_LABELS, KINDS, edition_on, md, md_wd
from forliosa.services.discussions import is_site_admin
from forliosa.timeutil import TAIPEI, iso_taipei, now_utc

log = logging.getLogger(__name__)

NOT_FOUND = "找不到這份報告"
KIND_ORDER = {"weekly": 0, "close": 1, "premarket": 2}
UNREAD_WINDOW = timedelta(hours=24)
MODE_NOTICE = "之後的新報告會對所有登入的人公開，並推播到有開的群組。"


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    from datetime import UTC

    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def enabled(settings: Settings | None = None) -> bool:
    return bool((settings or get_settings()).market_reports_enabled)


def _can_read(db: Session, user: User, r: MarketReport) -> bool:
    """A public edition: everyone; an admin one: site admins."""
    return r.visibility == "public" or is_site_admin(user)


def _visible_q(db: Session, user: User, kind: str | None = None) -> Any:
    if is_site_admin(user):
        seen = MarketReport.visibility.in_(("public", "admin"))
    else:
        seen = MarketReport.visibility == "public"
    q = select(MarketReport).where(seen, MarketReport.current_version_id.is_not(None),
                                   MarketReport.state.in_(("data", "ai")))
    if kind:
        q = q.where(MarketReport.kind == kind)
    return q


def _version(db: Session, report: MarketReport, number: int | None = None) -> MarketReportVersion | None:
    if number is None:
        return db.get(MarketReportVersion, report.current_version_id) if report.current_version_id else None
    # the blind test's other variants are never read (migration 0028 made the kept one a plain version)
    return db.scalar(select(MarketReportVersion).where(MarketReportVersion.report_id == report.id,
                                                       MarketReportVersion.version == number,
                                                       MarketReportVersion.variant.is_(None)))


def summary(report: MarketReport, v: MarketReportVersion) -> dict[str, Any]:
    """``prev_session``: a premarket edition's previous Taiwan session (holidays skipped: the day 「昨日你的群組」 is
    about), else null."""
    p = v.payload or {}
    ed = edition_on(report.kind, report.edition_date) if report.kind == "premarket" else None
    published = p.get("published_at") or iso_taipei(_aware(v.created_at) or now_utc())
    return {"id": report.id, "kind": report.kind, "kind_label": KIND_LABELS[report.kind],
            "prev_session": ed.prev_session.isoformat() if ed is not None and ed.prev_session else None,
            "edition_date": report.edition_date.isoformat(),
            "edition_label": assemble.edition_label(report.kind, report.edition_date,
                                                    (report.period_start, report.period_end)),
            "title": p.get("title") or "", "has_ai": bool(p.get("has_ai")),
            "published_at": published, "corrected": bool(p.get("corrections"))}


def _readable(db: Session, user: User, report_id: str) -> MarketReport:
    r = db.get(MarketReport, report_id)
    if r is None or not enabled() or not _can_read(db, user, r) or r.current_version_id is None \
            or r.state not in ("data", "ai"):
        raise not_found(NOT_FOUND)
    return r


def _payload(report: MarketReport, v: MarketReportVersion) -> dict[str, Any]:
    out = assemble.public(v.payload or {})
    out["first_published_at"] = iso_taipei(_aware(report.first_published_at) or _aware(v.created_at) or now_utc())
    return out


# -- members ---------------------------------------------------------------------------------------------------
def latest_by_kind(db: Session, user: User) -> list[tuple[MarketReport, MarketReportVersion]]:
    out = []
    for kind in KINDS:
        r = db.scalar(_visible_q(db, user, kind).order_by(MarketReport.edition_date.desc()).limit(1))
        v = _version(db, r) if r else None
        if r is not None and v is not None:
            out.append((r, v))
    return out


def unread(db: Session, user: User, now: datetime | None = None) -> bool:
    """The newest visible edition came after the user last looked."""
    now = now or now_utc()
    q = _visible_q(db, user).where(MarketReport.first_published_at.is_not(None))
    newest = db.scalar(q.order_by(MarketReport.first_published_at.desc()).limit(1))
    published = _aware(newest.first_published_at) if newest is not None else None
    if published is None:
        return False
    seen = db.get(MarketReportRead, user.id)
    if seen is None:
        return published is not None and published > now - UNREAD_WINDOW
    return published is not None and published > (_aware(seen.seen_at) or now)


def status(db: Session, user: User, now: datetime | None = None) -> dict[str, Any]:
    admin = is_site_admin(user)
    if not enabled():
        return {"available": False, "mode": None, "unread": False, "latest": []}
    latest = latest_by_kind(db, user)
    return {"available": bool(latest), "mode": rs.mode(db) if admin else None,
            "unread": unread(db, user, now) if latest else False,
            "latest": [summary(r, v) for r, v in latest]}


def _cursor(r: MarketReport) -> str:
    return base64.urlsafe_b64encode(f"{r.edition_date.isoformat()}|{KIND_ORDER[r.kind]}|{r.id}".encode()) \
        .decode().rstrip("=")


def list_reports(db: Session, user: User, kind: str | None, limit: int, cursor: str | None) -> dict[str, Any]:
    if not enabled():
        return {"items": [], "next_cursor": None}
    rows = list(db.scalars(_visible_q(db, user, kind).order_by(MarketReport.edition_date.desc())))
    rows.sort(key=lambda r: (-r.edition_date.toordinal(), KIND_ORDER[r.kind], [-ord(c) for c in r.id]))
    if cursor:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
            d, k, rid = raw.split("|", 2)
            key = (-date.fromisoformat(d).toordinal(), int(k), [-ord(c) for c in rid])
        except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
            raise unprocessable("分頁游標不正確，重新整理後再試。") from exc
        rows = [r for r in rows if (-r.edition_date.toordinal(), KIND_ORDER[r.kind], [-ord(c) for c in r.id]) > key]
    page = rows[:limit]
    items = []
    for r in page:
        v = _version(db, r)
        if v is not None:
            items.append(summary(r, v))
    return {"items": items, "next_cursor": _cursor(page[-1]) if len(rows) > limit and page else None}


def latest(db: Session, user: User, kind: str | None) -> dict[str, Any] | None:
    if not enabled():
        return None
    q = _visible_q(db, user, kind).order_by(MarketReport.first_published_at.desc() if kind is None
                                            else MarketReport.edition_date.desc())
    r = db.scalar(q.limit(1))
    v = _version(db, r) if r else None
    return _payload(r, v) if r is not None and v is not None else None


def one(db: Session, user: User, report_id: str, version: int | None = None) -> dict[str, Any]:
    r = _readable(db, user, report_id)
    v = _version(db, r, version)
    if v is None:
        raise not_found("找不到這一版")
    return _payload(r, v)


def mark_seen(db: Session, user: User, now: datetime | None = None) -> None:
    now = now or now_utc()
    row = db.get(MarketReportRead, user.id)
    if row is None:
        db.add(MarketReportRead(user_id=user.id, seen_at=now))
    else:
        row.seen_at = now
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


# -- admin: overview and settings --------------------------------------------------------------------------------
# The shapes below are the web app's (``apps/web/src/api/types.ts``: AdminReportsOverview, ReportsConfigResult,
# ReportValidation): the contract (§14.2) only said what each answer holds.
KEY_STALE = timedelta(minutes=15)
KEY_STALE_NOTE = "背景工作超過 15 分鐘沒有回報，狀態可能不是最新的。"


def _run_row(db: Session, r: MarketReportRun, report: MarketReport | None) -> dict[str, Any]:
    """One recent attempt. ``variant`` / ``purpose``: the blind test's runs (``trial``, A / B / C) before it was removed
    on 2026-11-18 — history only; every new run is ``live`` with no variant."""
    problems = 0
    v = db.scalar(select(MarketReportVersion).where(MarketReportVersion.run_id == r.id).limit(1))
    if v is not None:
        problems = len((v.validation or {}).get("first") or [])
    seconds = (_aware(r.finished_at) - _aware(r.started_at)).total_seconds() if r.finished_at and r.started_at \
        else None
    stops = [c.get("stop_reason") for c in r.calls or [] if "stop_reason" in c]
    return {"id": r.id, "report_id": r.report_id, "kind": report.kind if report else None,
            "edition_date": report.edition_date.isoformat() if report else None,
            "edition_label": assemble.edition_label(report.kind, report.edition_date,
                                                    (report.period_start, report.period_end)) if report else "",
            "variant": r.variant, "purpose": r.purpose, "attempt": r.attempt, "status": r.status, "step": r.step,
            "tier": r.tier, "model": (r.writer or {}).get("model"), "effort": (r.writer or {}).get("effort"),
            "cost_usd": float(r.cost_usd or 0),
            "seconds": round(seconds, 1) if seconds is not None else None,
            "stop_reason": stops[-1] if stops else None,
            "fallback_used": any(c.get("fallback_used") for c in r.calls or []),
            "problems": problems, "error": r.error,
            "started_at": iso_taipei(_aware(r.started_at)) if r.started_at else None}


def manual_status(db: Session, today: date) -> dict[str, Any]:
    nyse = calendars.nyse_status(db, today)
    nxt = db.scalar(select(NyseHoliday).where(NyseHoliday.date >= today).order_by(NyseHoliday.date).limit(1))
    horizon = today + timedelta(days=14)
    macro = len(list(db.scalars(select(MacroCalendarEvent.id).where(MacroCalendarEvent.event_date >= today,
                                                                     MacroCalendarEvent.event_date <= horizon))))
    earn = len(list(db.scalars(select(UsEarningsDate.id).where(UsEarningsDate.report_date >= today,
                                                               UsEarningsDate.report_date <= horizon))))
    return {"nyse_rows": nyse.get("rows", 0), "nyse_unverified": nyse.get("unverified", 0),
            "nyse_next": {"date": nxt.date.isoformat(), "name": nxt.name, "kind": nxt.kind} if nxt else None,
            "macro_next_14d": macro, "earnings_next_14d": earn}


def writers_view(db: Session, cfg: MarketReportConfig, settings: Settings, now: datetime) \
        -> dict[str, dict[str, Any] | None]:
    """Per kind: the writer in use (``source``: picked in the back office or the env default). ``effective`` /
    ``tier``: after the budget tier."""
    out: dict[str, dict[str, Any] | None] = {}
    for kind in KINDS:
        tier = accounting.tier(db, kind, now, settings)
        chosen = rs.chosen_writer(db, kind, settings)
        effective = rs.apply_tier(chosen, tier)
        picked = rs.Writer.parse((cfg.writers or {}).get(kind)) is not None
        out[kind] = {**chosen.as_dict(), "source": "admin" if picked else "default",
                     "effective": None if effective is None else effective.as_dict(), "tier": tier}
    return out


def slot_status(db: Session, cfg: MarketReportConfig, now: datetime) -> dict[str, Any]:
    """The reports' own key slot as the worker last saw it (``cfg.key_state``: the worker is another process, and only
    its pool uses the slot); before the worker has written it, this process's view."""
    from forliosa.ai import store
    from forliosa.ai.keypool import get_key_pool
    from forliosa.reports.calls import slot_state

    seen = cfg.key_state or None
    if not seen:
        return slot_state(get_key_pool(), store.slot_month_costs(db, now))
    out = {"slot": seen.get("slot"), "status": seen.get("status") or "ok", "note": seen.get("note")}
    try:
        checked = datetime.fromisoformat(str(seen.get("checked_at")))
    except ValueError:
        checked = None
    if checked is None or now - checked > KEY_STALE:
        out["note"] = " ".join(x for x in (out["note"], KEY_STALE_NOTE) if x)
    return out


def overview(db: Session, now: datetime | None = None, settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    now = now or now_utc()
    cfg = rs.config(db, s)
    runs = list(db.scalars(select(MarketReportRun).order_by(MarketReportRun.started_at.desc()).limit(20)))
    reports = {r.id: r for r in db.scalars(select(MarketReport).where(
        MarketReport.id.in_([r.report_id for r in runs])))} if runs else {}
    month = accounting.month_spend(db, now)
    budget = Decimal(str(s.ai_mreport_monthly_budget_usd))
    local = now.astimezone(TAIPEI)
    return {
        "enabled": enabled(s), "mode": rs.mode_of(cfg.mode),
        "writers": writers_view(db, cfg, s, now),
        "month": {"label": f"{local.year} 年 {local.month} 月", "spend_usd": round(float(month), 2),
                  "budget_usd": float(s.ai_mreport_monthly_budget_usd),
                  "tier": accounting.tier_of_spend(month, budget)},
        "key": slot_status(db, cfg, now),
        "runs": [_run_row(db, r, reports.get(r.report_id)) for r in runs],
        "manual": manual_status(db, local.date()),
    }


def put_config(db: Session, user: User, body: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    """Answers the overview (it has ``mode`` and ``writers``) plus ``notice`` when switching to public."""
    s = settings or get_settings()
    cfg = rs.config(db, s)
    notice = None
    mode = body.get("mode")
    if mode is not None:
        if mode not in rs.MODES:
            raise unprocessable("模式只能是 public 或 paused。", details={"field": "mode"})
        if mode == "public" and rs.mode_of(cfg.mode) != "public":
            notice = MODE_NOTICE
        cfg.mode = mode
    if "writers" in body and body["writers"] is not None:
        writers = dict(cfg.writers or {})
        for kind, w in body["writers"].items():
            if kind not in KINDS:
                raise unprocessable("報告種類只能是 premarket、close 或 weekly。", details={"field": "writers"})
            if w is None:
                writers[kind] = None
                continue
            if w.get("model") not in rs.WRITER_MODELS or w.get("effort") not in rs.ADMIN_EFFORTS:
                raise unprocessable("撰寫模型只能選 Opus 5.5 或 Sonnet 5.5，思考程度 low 到 xhigh。",
                                    details={"field": f"writers.{kind}"})
            writers[kind] = {"model": w["model"], "effort": w["effort"]}
        cfg.writers = writers
    cfg.updated_by, cfg.updated_at = user.id, now_utc()
    db.commit()
    log.info("market reports: settings changed by %s (mode %s)", user.id, cfg.mode)
    return {**overview(db, settings=s), "notice": notice}


# -- admin: corrections and rebuilding ----------------------------------------------------------------------------
HEAD_KEYS = ("title", "highlights")  # a correction may also put the rule-made title / highlights back


def _run_pack(db: Session, v: MarketReportVersion) -> dict[str, Any] | None:
    """The data pack the version's attempt wrote from (``market_report_runs.pack_gz``)."""
    import json
    import zlib

    run = db.get(MarketReportRun, v.run_id) if v.run_id else None
    if run is None or not run.pack_gz:
        return None
    try:
        return json.loads(zlib.decompress(run.pack_gz).decode("utf-8"))
    except (zlib.error, ValueError):
        return None


def correction(db: Session, user: User, report_id: str, note: str, drop_sections: list[str]) -> dict[str, Any]:
    r = db.get(MarketReport, report_id)
    cur = pipeline.current(db, r) if r else None
    if r is None or cur is None:
        raise not_found(NOT_FOUND)
    note = " ".join((note or "").split())
    if not 1 <= len(note) <= 200:
        raise unprocessable("更正說明要 1 到 200 字。", details={"field": "note"})
    now = now_utc()
    payload = copy.deepcopy(dict(cur.payload or {}))
    keys = set(drop_sections or [])
    known = {sec["key"] for sec in payload.get("sections") or []} | set(HEAD_KEYS)
    if keys - known:
        raise unprocessable(f"沒有這個段落：{'、'.join(sorted(keys - known))}。", details={"field": "drop_sections"})
    sections = []
    for sec in payload.get("sections") or []:
        if sec["key"] in keys and not sec.get("dropped"):
            sec = {**sec, "dropped": {"reasons": ["更正"]}}
        sections.append(sec)
    payload["sections"] = sections
    heads = [k for k in HEAD_KEYS if k in keys and payload.get(f"{k}_origin") == "ai"]
    if heads:  # the AI title / highlights go back to the rule-made ones (from the attempt's own data pack)
        pk = _run_pack(db, cur)
        if pk is None:
            raise ApiError(409, "no_pack", "這一版沒有留下資料包，標題和重點沒辦法換回規則寫的版本。")
        if "title" in heads:
            payload["title"], payload["title_origin"] = assemble.data_title(r.kind, pk), "rules"
        if "highlights" in heads:
            # an edition with the brief keeps its fields: the writer's rows go, the server's own stay or stand in. The
            # weekly, an edition published before the brief (its pack has none of the brief's facts) and one whose pack
            # gives the server no row at all get the plain rule-made points instead
            rows = assemble.brief_rows(r.kind, pk) if payload.get("brief") else []
            if "brief" in payload:
                payload["brief"] = rows or None
            payload["highlights"] = [row["paragraph"] for row in rows] if rows \
                else assemble.data_highlights(r.kind, pk, brief=False)
            payload["highlights_origin"] = "rules"
        assemble.number_footnotes(payload, pk)
    assemble.refresh_ai_lines(payload)
    # ``note`` is the note alone: the page writes 「已更正（11/18 09:10）：…」 from ``at``
    payload["corrections"] = [*(payload.get("corrections") or []), {"at": iso_taipei(now), "note": note}]
    payload["edition"] = "correction"
    v = pipeline.new_version(db, r, edition="correction", payload=payload, now=now, writer=cur.writer,
                             run_id=cur.run_id, validation=cur.validation, based_on=cur.id, correction_note=note)
    r.current_version_id, r.updated_at = v.id, now
    db.commit()
    log.info("market report %s corrected by %s (version %d)", r.id, user.id, v.version)
    return _payload(r, v)


def rebuild_data(db: Session, kind: str, edition_date: date) -> dict[str, Any]:
    if kind not in KINDS:
        raise unprocessable("報告種類只能是 premarket、close 或 weekly。", details={"field": "kind"})
    deps = pipeline.default_deps()
    try:
        report = pipeline.backfill_data(db, kind, edition_date, deps)
    except ValueError as exc:
        raise unprocessable(f"{edition_date.isoformat()} 沒有這一種報告（休市日或不是週日）。",
                            details={"field": "edition_date"}) from exc
    v = pipeline.current(db, report)
    return summary(report, v) if v else {"id": report.id}


# -- admin: the hand-kept tables ------------------------------------------------------------------------------------
def _nyse_row(h: NyseHoliday) -> dict[str, Any]:
    return {"date": h.date.isoformat(), "date_label": md_wd(h.date), "name": h.name, "kind": h.kind,
            "close_time_et": h.close_time_et, "source_url": h.source_url, "verified": h.verified_at is not None,
            "verified_at": iso_taipei(_aware(h.verified_at)) if h.verified_at else None}


def nyse_list(db: Session) -> list[dict[str, Any]]:
    return [_nyse_row(h) for h in db.scalars(select(NyseHoliday).order_by(NyseHoliday.date))]


def nyse_url_ok(url: str) -> bool:
    """An https page on nyse.com or one of its subdomains (the host, not a substring of the address)."""
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    return parts.scheme == "https" and not parts.username and (host == "nyse.com" or host.endswith(".nyse.com"))


def nyse_put(db: Session, user: User, d: date, body: dict[str, Any]) -> dict[str, Any]:
    kind = body.get("kind")
    if kind not in ("closed", "early_close"):
        raise unprocessable("類型只能是休市（closed）或提早收盤（early_close）。", details={"field": "kind"})
    close = body.get("close_time_et")
    if kind == "early_close" and not (close and calendars._hhmm(close)):
        raise unprocessable("提早收盤要填美東收盤時間，例如 13:00。", details={"field": "close_time_et"})
    url = str(body.get("source_url") or "")
    if not nyse_url_ok(url):
        raise unprocessable("來源要是 NYSE 官方頁面（https://www.nyse.com/…）。", details={"field": "source_url"})
    now = now_utc()
    h = db.get(NyseHoliday, d)
    if h is None:
        h = NyseHoliday(date=d)
        db.add(h)
    h.name, h.kind = str(body.get("name") or "")[:80] or "休市", kind
    h.close_time_et = f"{calendars._hhmm(close):%H:%M}" if kind == "early_close" else None  # 「9:30」 -> 09:30
    h.source_url, h.updated_by, h.updated_at = url, user.id, now
    h.verified_at = now if body.get("verified") else None
    db.commit()
    calendars.load_us_calendar(db)
    return _nyse_row(h)


def nyse_delete(db: Session, d: date) -> None:
    db.execute(delete(NyseHoliday).where(NyseHoliday.date == d))
    db.commit()
    calendars.load_us_calendar(db)


def _macro_row(m: MacroCalendarEvent) -> dict[str, Any]:
    tp = calendars.to_taipei(m.event_date, m.local_time, m.tz)
    return {"id": m.id, "event_date": m.event_date.isoformat(), "local_time": m.local_time, "tz": m.tz,
            "country": m.country, "title": m.title, "agency": m.agency, "official_url": m.official_url,
            "sectors": list(m.sectors or []), "note": m.note or "",
            "taipei_label": f"台北 {md(tp.date())} {tp:%H:%M}" if tp else None}


def macro_list(db: Session, start: date | None, end: date | None) -> list[dict[str, Any]]:
    q = select(MacroCalendarEvent)
    if start:
        q = q.where(MacroCalendarEvent.event_date >= start)
    if end:
        q = q.where(MacroCalendarEvent.event_date <= end)
    return [_macro_row(m) for m in db.scalars(q.order_by(MacroCalendarEvent.event_date, MacroCalendarEvent.id))]


def _sectors(raw: Any) -> list[str]:
    from forliosa.reports.marketcalc import SECTOR_NAMES

    out = [str(x) for x in raw or []]
    bad = [x for x in out if x not in SECTOR_NAMES]
    if bad:
        raise unprocessable(f"相關類股要是 32 類之一：{'、'.join(bad)} 不在名單。", details={"field": "sectors"})
    return out


def macro_add(db: Session, user: User, body: dict[str, Any]) -> dict[str, Any]:
    if not calendars.official_url_ok(body.get("official_url")):
        raise unprocessable(calendars.OFFICIAL_URL_ERROR, details={"field": "official_url"})
    local = body.get("local_time")
    if local and not calendars._hhmm(local):
        raise unprocessable("時間要寫成 HH:MM，例如 08:30。", details={"field": "local_time"})
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(str(body.get("tz") or ""))
    except Exception as exc:
        raise unprocessable("時區不正確，例如 America/New_York。", details={"field": "tz"}) from exc
    m = MacroCalendarEvent(id=new_id("mac"), event_date=body["event_date"], local_time=local or None, tz=body["tz"],
                           country=str(body.get("country") or "")[:2].upper(), title=str(body["title"])[:120],
                           agency=str(body.get("agency") or "")[:80], official_url=body["official_url"],
                           sectors=_sectors(body.get("sectors")), note=str(body.get("note") or "")[:200],
                           created_by=user.id, updated_at=now_utc())
    db.add(m)
    db.commit()
    return _macro_row(m)


def macro_delete(db: Session, mid: str) -> None:
    db.execute(delete(MacroCalendarEvent).where(MacroCalendarEvent.id == mid))
    db.commit()


def _earn_row(u: UsEarningsDate) -> dict[str, Any]:
    return {"id": u.id, "symbol": u.symbol, "company": u.company, "report_date": u.report_date.isoformat(),
            "timing": u.timing, "time_et": u.time_et, "official_url": u.official_url,
            "sectors": list(u.sectors or []), "note": u.note or "",
            "taipei_label": calendars.earnings_label(u.report_date, u.timing, u.time_et)}


def earnings_list(db: Session, start: date | None, end: date | None) -> list[dict[str, Any]]:
    q = select(UsEarningsDate)
    if start:
        q = q.where(UsEarningsDate.report_date >= start)
    if end:
        q = q.where(UsEarningsDate.report_date <= end)
    return [_earn_row(u) for u in db.scalars(q.order_by(UsEarningsDate.report_date, UsEarningsDate.symbol))]


def earnings_add(db: Session, user: User, body: dict[str, Any]) -> dict[str, Any]:
    url = body.get("official_url")
    if url and not calendars.earnings_url_ok(url):
        raise unprocessable("財報連結要是 https 的公司或官方頁面，不能是新聞或論壇。",
                            details={"field": "official_url"})
    if body.get("timing") not in ("bmo", "amc", "during", "unknown"):
        raise unprocessable("公布時段只能是盤前、盤後、盤中或不明。", details={"field": "timing"})
    t = body.get("time_et")
    if t and not calendars._hhmm(t):
        raise unprocessable("時間要寫成 HH:MM，例如 16:05。", details={"field": "time_et"})
    t = f"{calendars._hhmm(t):%H:%M}" if t else None  # 「9:30」 is stored as 09:30
    sym = str(body["symbol"]).strip().upper()[:20]
    existing = db.scalar(select(UsEarningsDate).where(UsEarningsDate.symbol == sym,
                                                      UsEarningsDate.report_date == body["report_date"]))
    if existing is not None:
        raise ApiError(409, "conflict", f"{sym} 在 {body['report_date']} 已經有一列，先刪掉再新增。")
    u = UsEarningsDate(id=new_id("use"), symbol=sym, company=str(body["company"])[:100],
                       report_date=body["report_date"], timing=body["timing"], time_et=t or None,
                       official_url=url or None, sectors=_sectors(body.get("sectors")),
                       note=str(body.get("note") or "")[:200], created_by=user.id, updated_at=now_utc())
    db.add(u)
    db.commit()
    return _earn_row(u)


def earnings_delete(db: Session, eid: str) -> None:
    db.execute(delete(UsEarningsDate).where(UsEarningsDate.id == eid))
    db.commit()


def gathers_of(db: Session, report_id: str) -> list[MarketReportGather]:
    return list(db.scalars(select(MarketReportGather).where(MarketReportGather.report_id == report_id)))
