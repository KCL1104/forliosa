"""What the market-report endpoints do (contract §14, §16, §17): visibility, the list, one report, the unread dot, and
the admin side — overview, settings, the blind test (variants, votes, reveal), corrections, rebuilding a data
edition, and the three hand-kept tables.

Visibility: a ``public`` edition is read by every signed-in user; an ``admin`` one (blind test, the trial mode, CLI
backfills) by site admins only — anyone else gets 404 「找不到這份報告」. With MARKET_REPORTS_ENABLED off nothing is
available. A member always reads the public form (:func:`assemble.public`: no refs, no dropped text, no quotes); the
admin form with refs and dropped sections only comes from the admin variant endpoint. Before the reveal, the admin API
never names a blind-test variant's model or cost.
"""

from __future__ import annotations

import base64
import binascii
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
    MarketReportVote,
    NyseHoliday,
    UsEarningsDate,
    User,
)
from forliosa.reports import accounting, assemble, calendars, pipeline
from forliosa.reports import settings as rs
from forliosa.reports.schedule import KIND_LABELS, KINDS, md, md_wd
from forliosa.services.discussions import is_site_admin
from forliosa.timeutil import TAIPEI, iso_taipei, now_utc

log = logging.getLogger(__name__)

NOT_FOUND = "找不到這份報告"
KIND_ORDER = {"weekly": 0, "close": 1, "premarket": 2}
UNREAD_WINDOW = timedelta(hours=24)
TIER_LABELS = {"normal": "正常", "medium": "已降為 medium", "sonnet": "已改用 Sonnet", "data_only": "只發資料版"}
MODE_NOTICE = "之後的新報告會對所有登入的人公開，並推播到有開的群組。"


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    from datetime import UTC

    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def enabled(settings: Settings | None = None) -> bool:
    return bool((settings or get_settings()).market_reports_enabled)


def _visibilities(user: User) -> tuple[str, ...]:
    return ("public", "admin") if is_site_admin(user) else ("public",)


def _visible_q(user: User, kind: str | None = None) -> Any:
    q = select(MarketReport).where(MarketReport.visibility.in_(_visibilities(user)),
                                   MarketReport.current_version_id.is_not(None),
                                   MarketReport.state.in_(("data", "ai")))
    if kind:
        q = q.where(MarketReport.kind == kind)
    return q


def _version(db: Session, report: MarketReport, number: int | None = None) -> MarketReportVersion | None:
    if number is None:
        return db.get(MarketReportVersion, report.current_version_id) if report.current_version_id else None
    return db.scalar(select(MarketReportVersion).where(MarketReportVersion.report_id == report.id,
                                                       MarketReportVersion.version == number,
                                                       MarketReportVersion.variant.is_(None)))


def summary(report: MarketReport, v: MarketReportVersion) -> dict[str, Any]:
    p = v.payload or {}
    return {"id": report.id, "kind": report.kind, "kind_label": KIND_LABELS[report.kind],
            "edition_date": report.edition_date.isoformat(),
            "edition_label": assemble.edition_label(report.kind, report.edition_date,
                                                    (report.period_start, report.period_end)),
            "title": p.get("title") or "", "has_ai": bool(p.get("has_ai")),
            "published_at": p.get("published_at") or iso_taipei(_aware(v.created_at) or now_utc()),
            "corrected": bool(p.get("corrections"))}


def _readable(db: Session, user: User, report_id: str) -> MarketReport:
    r = db.get(MarketReport, report_id)
    if r is None or not enabled() or r.visibility not in _visibilities(user) or r.current_version_id is None \
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
        r = db.scalar(_visible_q(user, kind).order_by(MarketReport.edition_date.desc()).limit(1))
        v = _version(db, r) if r else None
        if r is not None and v is not None:
            out.append((r, v))
    return out


def unread(db: Session, user: User, now: datetime | None = None) -> bool:
    now = now or now_utc()
    newest = db.scalar(_visible_q(user).where(MarketReport.first_published_at.is_not(None))
                       .order_by(MarketReport.first_published_at.desc()).limit(1))
    if newest is None:
        return False
    published = _aware(newest.first_published_at)
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
    rows = list(db.scalars(_visible_q(user, kind).order_by(MarketReport.edition_date.desc())))
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
    q = _visible_q(user, kind).order_by(MarketReport.first_published_at.desc() if kind is None
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
def _revealed(cfg: MarketReportConfig) -> bool:
    return cfg.revealed_at is not None


def trial_progress(db: Session, settings: Settings) -> dict[str, Any]:
    reports = list(db.scalars(select(MarketReport).where(MarketReport.trial.is_(True))))
    daily = [r for r in reports if r.kind != "weekly"]
    weekly = [r for r in reports if r.kind == "weekly"]
    days = sorted({r.edition_date for r in daily})
    return {"daily_done": sum(1 for r in daily if r.closed_at is not None or r.state == "skipped"),
            "daily_total": settings.ai_mreport_trial_days * 2,
            "trading_days": len(days), "trading_days_total": settings.ai_mreport_trial_days,
            "weekly_done": sum(1 for r in weekly if r.closed_at is not None), "weekly_total": 1}


def _run_row(db: Session, r: MarketReportRun, report: MarketReport | None, revealed: bool) -> dict[str, Any]:
    hide = r.purpose == "trial" and not revealed
    problems = 0
    v = db.scalar(select(MarketReportVersion).where(MarketReportVersion.run_id == r.id).limit(1))
    if v is not None:
        problems = len((v.validation or {}).get("first") or [])
    seconds = (_aware(r.finished_at) - _aware(r.started_at)).total_seconds() if r.finished_at and r.started_at \
        else None
    stops = [c.get("stop_reason") for c in r.calls or [] if "stop_reason" in c]
    return {"id": r.id, "report_id": r.report_id, "kind": report.kind if report else None,
            "edition_date": report.edition_date.isoformat() if report else None, "variant": r.variant,
            "purpose": r.purpose, "attempt": r.attempt, "status": r.status, "step": r.step,
            "tier": None if hide else r.tier, "model": None if hide else (r.writer or {}).get("model"),
            "effort": None if hide else (r.writer or {}).get("effort"),
            "cost_usd": None if hide else float(r.cost_usd or 0),
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
            "macro_next_14_days": macro, "earnings_next_14_days": earn}


def writers_view(db: Session, cfg: MarketReportConfig, settings: Settings, now: datetime) -> list[dict[str, Any]]:
    out = []
    in_trial = cfg.mode == "trial" and not _revealed(cfg)
    for kind in KINDS:
        tier = accounting.tier(db, kind, now, settings)
        chosen = rs.chosen_writer(db, kind, settings)
        effective = rs.apply_tier(chosen, tier)
        out.append({"kind": kind, "kind_label": KIND_LABELS[kind], "trial": in_trial,
                    "writer": None if in_trial else chosen.as_dict(),
                    "picked": rs.Writer.parse((cfg.writers or {}).get(kind)) is not None,
                    "effective": None if in_trial or effective is None else effective.as_dict(),
                    "tier": tier, "tier_label": TIER_LABELS[tier]})
    return out


def slot_status(settings: Settings) -> dict[str, Any]:
    from forliosa.ai.keypool import get_key_pool
    from forliosa.reports.calls import report_slot

    pool = get_key_pool()
    reserved = sorted(getattr(pool, "reserved", ()) or ())
    if not reserved:
        return {"slot": None, "state": "shared", "text": "沒有專用金鑰，報告和會員共用金鑰池。"}
    n = reserved[0]
    slot = pool.get(n)
    state = pool.state(slot) if slot is not None else "not_configured"
    usable = report_slot(pool) is not None
    return {"slot": n, "state": state, "text": f"市場報告專用 #{n}" + ("" if usable else "（目前不能用，只發資料版）")}


def overview(db: Session, now: datetime | None = None, settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    now = now or now_utc()
    cfg = rs.config(db, s)
    revealed = _revealed(cfg)
    runs = list(db.scalars(select(MarketReportRun).order_by(MarketReportRun.started_at.desc()).limit(20)))
    reports = {r.id: r for r in db.scalars(select(MarketReport).where(
        MarketReport.id.in_([r.report_id for r in runs])))} if runs else {}
    month = accounting.month_spend(db, now)
    return {
        "enabled": enabled(s), "mode": cfg.mode, "revealed_at": iso_taipei(_aware(cfg.revealed_at))
        if cfg.revealed_at else None,
        "trial_started_on": cfg.trial_started_on.isoformat() if cfg.trial_started_on else None,
        "writers": writers_view(db, cfg, s, now),
        "month": {"spent_usd": float(month), "budget_usd": s.ai_mreport_monthly_budget_usd,
                  "tier": accounting.tier_of_spend(month, Decimal(str(s.ai_mreport_monthly_budget_usd))),
                  "tier_label": TIER_LABELS[accounting.tier_of_spend(
                      month, Decimal(str(s.ai_mreport_monthly_budget_usd)))]},
        "trial": {"spent_usd": float(accounting.trial_spend(db)), "budget_usd": s.ai_mreport_trial_budget_usd,
                  **trial_progress(db, s)},
        "runs": [_run_row(db, r, reports.get(r.report_id), revealed) for r in runs],
        "manual": manual_status(db, now.astimezone(TAIPEI).date()),
        "key_slot": slot_status(s),
    }


def put_config(db: Session, user: User, body: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    cfg = rs.config(db, s)
    notice = None
    mode = body.get("mode")
    if mode is not None:
        if mode not in rs.MODES:
            raise unprocessable("模式只能是 trial、public 或 paused。", details={"field": "mode"})
        if mode == "public" and cfg.mode != "public":
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


# -- admin: the blind test ---------------------------------------------------------------------------------------
def _variant_version(db: Session, report_id: str, label: str) -> MarketReportVersion | None:
    return db.scalar(select(MarketReportVersion).where(MarketReportVersion.report_id == report_id,
                                                       MarketReportVersion.variant == label)
                     .order_by(MarketReportVersion.version.desc()).limit(1))


def _public_metrics(m: dict[str, Any], revealed: bool) -> dict[str, Any]:
    keep = {k: v for k, v in (m or {}).items() if k not in ("cost_usd",)}
    if revealed:
        keep["cost_usd"] = (m or {}).get("cost_usd")
    return keep


def trial_list(db: Session, user: User) -> list[dict[str, Any]]:
    cfg = rs.config(db)
    revealed = _revealed(cfg)
    out = []
    for r in db.scalars(select(MarketReport).where(MarketReport.trial.is_(True))
                        .order_by(MarketReport.edition_date.desc(), MarketReport.kind)):
        vote = db.get(MarketReportVote, (r.id, user.id))
        variants = []
        for label in pipeline.VARIANTS:
            runs = [x for x in pipeline.runs_of(db, r.id, label)]
            if not runs:
                continue
            last = runs[-1]
            v = _variant_version(db, r.id, label)
            row = {"label": label, "status": last.status, "attempts": len(runs),
                   "finished_at": iso_taipei(_aware(last.finished_at)) if last.finished_at else None,
                   "on_time": bool((last.metrics or {}).get("on_time")), "published": v is not None,
                   "problems": len((v.validation or {}).get("first") or []) if v else None,
                   "metrics": _public_metrics(last.metrics or {}, revealed)}
            if revealed:
                row["writer"] = last.writer
            variants.append(row)
        out.append({"report_id": r.id, "kind": r.kind, "kind_label": KIND_LABELS[r.kind],
                    "edition_date": r.edition_date.isoformat(),
                    "edition_label": assemble.edition_label(r.kind, r.edition_date, (r.period_start, r.period_end)),
                    "closed": r.closed_at is not None, "variants": variants,
                    "my_vote": {"preferred": vote.preferred, "note": vote.note} if vote else None})
    return out


def variant(db: Session, report_id: str, label: str) -> dict[str, Any]:
    r = db.get(MarketReport, report_id)
    v = _variant_version(db, report_id, label) if r else None
    if r is None or v is None:
        raise not_found("這個版本還沒有產生")
    cfg = rs.config(db)
    out = dict(v.payload or {})
    out["variant"] = label
    val = v.validation or {}
    out["validation"] = {"first": val.get("first") or [], "revised": val.get("revised") or [],
                         "dropped": val.get("dropped") or {}, "check_ran": bool(val.get("check_ran")),
                         "counts": val.get("counts") or {}}
    if _revealed(cfg):
        out["writer"] = v.writer
    return out


def vote(db: Session, user: User, report_id: str, preferred: str, note: str) -> dict[str, Any]:
    r = db.get(MarketReport, report_id)
    if r is None or not r.trial:
        raise not_found(NOT_FOUND)
    if preferred not in pipeline.VARIANTS:
        raise unprocessable("只能選 A、B 或 C。", details={"field": "preferred"})
    row = db.get(MarketReportVote, (report_id, user.id))
    now = now_utc()
    if row is None:
        db.add(MarketReportVote(report_id=report_id, user_id=user.id, preferred=preferred, note=note or "",
                                created_at=now, updated_at=now))
    else:
        row.preferred, row.note, row.updated_at = preferred, note or "", now
    db.commit()
    return {"report_id": report_id, "preferred": preferred, "note": note or ""}


PASS = {"policy_violations": 0, "per_report_mismatch": 1, "dropped_avg": 1.0, "on_time": 0.8}


def reveal(db: Session, user: User, force: bool = False, settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    cfg = rs.config(db, s)
    prog = trial_progress(db, s)
    done = prog["daily_done"] >= prog["daily_total"] and prog["weekly_done"] >= prog["weekly_total"]
    if not done and not force:
        raise ApiError(409, "trial_not_done",
                       f"盲測還沒做完（{prog['daily_done']}/{prog['daily_total']} 份日報、"
                       f"週報 {prog['weekly_done']}/{prog['weekly_total']}）。")
    reports = {r.id: r for r in db.scalars(select(MarketReport).where(MarketReport.trial.is_(True)))}
    votes = list(db.scalars(select(MarketReportVote).where(MarketReportVote.report_id.in_(list(reports)))))
    groups: dict[tuple[str, str, str], list[MarketReportRun]] = {}
    for run in db.scalars(select(MarketReportRun).where(MarketReportRun.report_id.in_(list(reports)),
                                                        MarketReportRun.purpose == "trial")):
        report = reports[run.report_id]
        kind = "weekly" if report.kind == "weekly" else "daily"
        groups.setdefault((kind, run.writer.get("model", ""), run.writer.get("effort", "")), []).append(run)
    rows = []
    for (kind, model, effort), runs in sorted(groups.items()):
        final = {}
        for run in runs:  # the last attempt of each edition and variant
            final[(run.report_id, run.variant)] = run
        runs = list(final.values())
        ms = [r.metrics or {} for r in runs if r.status != "skipped_budget"]
        n = len(ms) or 1
        mine = {(r.report_id, r.variant) for r in runs}
        vote_count = sum(1 for v in votes if (v.report_id, v.preferred) in mine)
        row = {"kind": kind, "model": model, "effort": effort, "editions": len(ms), "votes": vote_count,
               "policy_violations": sum(int(m.get("policy_violations") or 0) for m in ms),
               "subject_mismatches": sum(int(m.get("subject_mismatches") or 0) for m in ms),
               "inferred_dates": sum(int(m.get("inferred_dates") or 0) for m in ms),
               "dropped_sections_avg": round(sum(int(m.get("dropped_sections") or 0) for m in ms) / n, 2),
               "on_time_rate": round(sum(1 for m in ms if m.get("on_time")) / n, 2),
               "data_only": sum(1 for m in ms if m.get("data_only")),
               "cost_avg_usd": round(sum(float(m.get("cost_usd") or 0) for m in ms) / n, 3),
               "seconds_avg": round(sum(float(m.get("seconds") or 0) for m in ms) / n, 1),
               "fallbacks": sum(1 for m in ms if m.get("fallback_used"))}
        row["passes"] = bool(ms) and row["policy_violations"] == 0 and all(
            int(m.get("subject_mismatches") or 0) + int(m.get("inferred_dates") or 0) <= PASS["per_report_mismatch"]
            for m in ms) and row["dropped_sections_avg"] <= PASS["dropped_avg"] \
            and row["on_time_rate"] >= PASS["on_time"] and row["data_only"] == 0
        rows.append(row)
    suggestion = {}
    for kind in ("daily", "weekly"):
        passing = [r for r in rows if r["kind"] == kind and r["passes"]]
        if passing:
            best = min(passing, key=lambda r: r["cost_avg_usd"])
            suggestion[kind] = {"model": best["model"], "effort": best["effort"]}
        else:
            suggestion[kind] = None
    if cfg.revealed_at is None:
        cfg.revealed_at, cfg.updated_by = now_utc(), user.id
        db.commit()
    return {"revealed_at": iso_taipei(_aware(cfg.revealed_at)), "complete": done, "rows": rows,
            "suggestion": suggestion,
            "note": "建議：每種報告挑過關的設定裡平均花費最低的；票數列在旁邊。"
                    "選好後在「撰寫設定」存下，再把模式切到對全站公開。"}


# -- admin: corrections and rebuilding ----------------------------------------------------------------------------
def correction(db: Session, user: User, report_id: str, note: str, drop_sections: list[str]) -> dict[str, Any]:
    r = db.get(MarketReport, report_id)
    cur = pipeline.current(db, r) if r else None
    if r is None or cur is None:
        raise not_found(NOT_FOUND)
    note = " ".join((note or "").split())
    if not 1 <= len(note) <= 200:
        raise unprocessable("更正說明要 1 到 200 字。", details={"field": "note"})
    now = now_utc()
    payload = dict(cur.payload or {})
    keys = set(drop_sections or [])
    sections = []
    for sec in payload.get("sections") or []:
        if sec["key"] in keys and not sec.get("dropped"):
            sec = {**sec, "dropped": {"reasons": ["更正"]}}
        sections.append(sec)
    payload["sections"] = sections
    t = now.astimezone(TAIPEI)
    line = f"已更正（{t.month}/{t.day} {t:%H:%M}）：{note}"
    payload["corrections"] = [*(payload.get("corrections") or []), {"at": iso_taipei(now), "note": line}]
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


def nyse_put(db: Session, user: User, d: date, body: dict[str, Any]) -> dict[str, Any]:
    kind = body.get("kind")
    if kind not in ("closed", "early_close"):
        raise unprocessable("類型只能是休市（closed）或提早收盤（early_close）。", details={"field": "kind"})
    close = body.get("close_time_et")
    if kind == "early_close" and not (close and calendars._hhmm(close)):
        raise unprocessable("提早收盤要填美東收盤時間，例如 13:00。", details={"field": "close_time_et"})
    url = str(body.get("source_url") or "")
    if not url.startswith("https://") or "nyse.com" not in url:
        raise unprocessable("來源要是 NYSE 官方頁面（https://www.nyse.com/…）。", details={"field": "source_url"})
    now = now_utc()
    h = db.get(NyseHoliday, d)
    if h is None:
        h = NyseHoliday(date=d)
        db.add(h)
    h.name, h.kind = str(body.get("name") or "")[:80] or "休市", kind
    h.close_time_et = close if kind == "early_close" else None
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
