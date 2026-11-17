"""The market reports' state machine (contract §5): ``tick(now)`` runs every minute in the worker's background loop.

``tick`` itself only does quick things — make the edition's row, build or refresh the data edition, queue the
gathering and the writing attempts, push when it is time, close, add the table versions. The model calls run in a
module-level thread pool (four workers; each opens its own database session); a run in progress is a
``market_report_runs`` row with ``status=running`` whose ``heartbeat_at`` moves at every step. A row left running
more than 20 minutes (the worker restarted) becomes ``abandoned`` and counts as an attempt.

Per edition (times in :mod:`.schedule`):

1. **Data edition** (``data``): built from the archive alone; the close edition's is rebuilt every 10 minutes until
   15:40 while no AI edition exists (in place: it is one version). A close edition with neither a listed close nor
   the OTC index at 15:00 is ``skipped`` (a typhoon day).
2. **Gathering**: once per edition (the blind test's three variants share it), unless the month's tier is
   ``data_only``, the mode is paused or the reports' own key slot is unusable.
3. **Writing**: one live attempt at a time, at most AI_MREPORT_MAX_ATTEMPTS a day per variant, none after the push
   fallback time. Write → rule checks → compliance read → one revision → drop the failing sections → else the data
   edition. A run past AI_MREPORT_RUN_ALARM_USD makes no further call. A result after the edition closed is
   ``abandoned``.
4. **Push** (mode public, a public edition only): the AI edition at the push time, or as soon as it comes until the
   fallback time, then the data edition (:mod:`.push`).
5. **Close** at 08:40 / 17:30 / 21:00; the close edition gets table versions at 23:45 and 06:40 the next day (AI text
   unchanged, the server's blocks rebuilt from everything stored by then; never pushed).

Blind test (§17): while the mode is ``trial``, from the first edition made, the premarket and close editions of 5
Taiwan trading days and the first weekly are written three times (A / B / C, the settings shuffled per edition) for
the site admins only, within the trial cap (US$45); a variant that would not fit is ``skipped_budget``.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
import zlib
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from forliosa.config import Settings, get_settings
from forliosa.ids import new_id
from forliosa.marketdata.opendata import TPEX_INDEX
from forliosa.models import (
    IndexDaily,
    Instrument,
    MarketReport,
    MarketReportConfig,
    MarketReportGather,
    MarketReportRun,
    MarketReportVersion,
    PriceDaily,
)
from forliosa.reports import accounting, assemble, calls, compliance, gather, push, validate, write
from forliosa.reports import pack as packmod
from forliosa.reports import settings as rs
from forliosa.reports.prompts import PROMPT_VERSION
from forliosa.reports.schedule import Edition, edition_on, md
from forliosa.timeutil import TAIPEI, now_taipei, now_utc, tw_trading_days

log = logging.getLogger(__name__)

STALE = timedelta(minutes=20)
HEARTBEAT_SECONDS = 60.0  # a writing attempt's heartbeat while a model call runs (well inside STALE)
PUSH_GRACE = timedelta(minutes=10)
DATA_REBUILD = timedelta(minutes=10)
TABLES_WINDOW = timedelta(hours=3)
VARIANTS = ("A", "B", "C")
TRIAL_DAILY = (("claude-sonnet-5-5", "high"), ("claude-opus-5-5", "medium"), ("claude-opus-5-5", "high"))
TRIAL_WEEKLY = (("claude-opus-5-5", "medium"), ("claude-opus-5-5", "high"), ("claude-opus-5-5", "xhigh"))
DONE_STATUSES = ("ok", "data_only", "skipped_budget")
MAX_WORKERS = 4

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()
_names: tuple[date, list[str]] | None = None


def executor() -> ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="mreport")
        return _executor


@dataclass
class Deps:
    """What the pipeline needs from outside (tests replace them): sessions, the key pool, market data, how a job runs
    (``submit``: the thread pool; tests run it inline) and the clock of the threads."""

    session: Callable[[], Session]
    pool: Any = None
    md: Any = None
    settings: Settings | None = None
    submit: Callable[[Callable[[], None]], Any] | None = None
    clock: Callable[[], datetime] = now_taipei

    def run(self, fn: Callable[[], None]) -> None:
        if self.submit is not None:
            self.submit(fn)
        else:
            executor().submit(fn)

    @property
    def s(self) -> Settings:
        return self.settings or get_settings()

    def key_pool(self) -> Any:
        if self.pool is None:
            from forliosa.ai.keypool import get_key_pool

            return get_key_pool()
        return self.pool

    def market(self) -> Any:
        if self.md is None:
            from forliosa.marketdata.service import get_market_data

            return get_market_data()
        return self.md


def default_deps() -> Deps:
    from forliosa.db import session_factory

    return Deps(session=lambda: session_factory()())


@dataclass
class TickResult:
    actions: list[str] = field(default_factory=list)

    def add(self, report: MarketReport, what: str) -> None:
        self.actions.append(f"{report.kind} {report.edition_date} {what}")


# -- small helpers -------------------------------------------------------------------------------------------------
def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    from datetime import UTC

    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def instrument_names(db: Session, today: date) -> list[str]:
    """Taiwan instrument names for the validator (cached per day)."""
    global _names
    if _names is not None and _names[0] == today:
        return _names[1]
    names = [n for (n,) in db.execute(select(Instrument.name).where(Instrument.market.in_(("TWSE", "TPEX"))))
             if n]
    _names = (today, names)
    return names


def report_of(db: Session, kind: str, d: date) -> MarketReport | None:
    return db.scalar(select(MarketReport).where(MarketReport.kind == kind, MarketReport.edition_date == d))


def runs_of(db: Session, report_id: str, variant: str | None = None, *, any_variant: bool = False) \
        -> list[MarketReportRun]:
    q = select(MarketReportRun).where(MarketReportRun.report_id == report_id)
    if not any_variant:
        q = q.where(MarketReportRun.variant.is_(None) if variant is None else MarketReportRun.variant == variant)
    return list(db.scalars(q.order_by(MarketReportRun.attempt)))


def gather_of(db: Session, report_id: str) -> MarketReportGather | None:
    return db.scalar(select(MarketReportGather).where(MarketReportGather.report_id == report_id)
                     .order_by(MarketReportGather.started_at.desc()))


def new_version(db: Session, report: MarketReport, *, edition: str, payload: dict[str, Any], now: datetime,
                variant: str | None = None, writer: dict[str, Any] | None = None, run_id: str | None = None,
                validation: dict[str, Any] | None = None, based_on: str | None = None,
                correction_note: str | None = None) -> MarketReportVersion:
    """The next version number (max + 1, retried on a clash with another process)."""
    for _ in range(5):
        n = (db.scalar(select(func.max(MarketReportVersion.version)).where(
            MarketReportVersion.report_id == report.id)) or 0) + 1
        payload = {**payload, "version": n}
        v = MarketReportVersion(id=new_id("mrv"), report_id=report.id, version=n, variant=variant, edition=edition,
                                payload=payload, writer=writer, run_id=run_id, prompt_version=PROMPT_VERSION,
                                validation=validation or {}, based_on=based_on, correction_note=correction_note,
                                created_at=now)
        db.add(v)
        try:
            db.commit()
            return v
        except IntegrityError:
            db.rollback()
    raise RuntimeError("market report: no free version number")


def current(db: Session, report: MarketReport) -> MarketReportVersion | None:
    return db.get(MarketReportVersion, report.current_version_id) if report.current_version_id else None


def _period(report: MarketReport) -> tuple[date, date]:
    return report.period_start, report.period_end


def _next(report: MarketReport) -> tuple[date, date] | None:
    return (report.next_start, report.next_end) if report.next_start and report.next_end else None


# -- the blind test ----------------------------------------------------------------------------------------------
def is_trial_edition(db: Session, cfg: Any, kind: str, d: date, settings: Settings) -> bool:
    if cfg.mode != "trial" or not accounting.trial_fits(db, kind, "high", settings):
        return False
    start = cfg.trial_started_on
    if start is None:
        return True
    if d < start:
        return False
    if kind == "weekly":
        return db.scalar(select(func.count()).select_from(MarketReport).where(
            MarketReport.kind == "weekly", MarketReport.trial.is_(True), MarketReport.edition_date != d)) == 0
    return len(tw_trading_days(start, d)) <= settings.ai_mreport_trial_days


def trial_settings(kind: str) -> tuple[tuple[str, str], ...]:
    return TRIAL_WEEKLY if kind == "weekly" else TRIAL_DAILY


# -- creating the edition -----------------------------------------------------------------------------------------
def make_report(db: Session, ed: Edition, now: datetime, *, visibility: str, trial: bool = False,
                backfill: bool = False) -> MarketReport:
    r = MarketReport(id=new_id("mrp"), kind=ed.kind, edition_date=ed.edition_date, period_start=ed.period[0],
                     period_end=ed.period[1], next_start=ed.next_period[0] if ed.next_period else None,
                     next_end=ed.next_period[1] if ed.next_period else None, state="pending", visibility=visibility,
                     trial=trial, backfill=backfill, notes=[], created_at=now, updated_at=now)
    db.add(r)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = report_of(db, ed.kind, ed.edition_date)
        assert existing is not None
        return existing
    return r


def ensure_report(db: Session, ed: Edition, now: datetime, cfg: Any, settings: Settings) -> MarketReport | None:
    r = report_of(db, ed.kind, ed.edition_date)
    if r is not None:
        return r
    if cfg.mode == "paused":
        return None
    if now < min(ed.gather_at, ed.data_at) or now >= ed.close_at:
        return None
    trial = is_trial_edition(db, cfg, ed.kind, ed.edition_date, settings)
    r = make_report(db, ed, now, visibility="public" if cfg.mode == "public" else "admin", trial=trial)
    if cfg.mode == "trial" and cfg.trial_started_on is None and r.trial:
        cfg.trial_started_on = ed.edition_date
        db.commit()
    log.info("market report %s %s made (%s%s)", ed.kind, ed.edition_date, r.visibility, ", blind test" if r.trial
             else "")
    return r


# -- the data edition ----------------------------------------------------------------------------------------------
def _session_in(db: Session, d: date) -> tuple[bool, bool]:
    """(a listed close of ``d`` is stored, the OTC index of ``d`` is stored)."""
    listed = db.scalar(select(PriceDaily.symbol).where(
        PriceDaily.date == d, PriceDaily.source.in_(("twse-opendata", "twse-openapi")),
        PriceDaily.symbol.like("%.TW")).limit(1)) is not None
    otc = db.scalar(select(IndexDaily.name).where(IndexDaily.name == TPEX_INDEX, IndexDaily.date == d).limit(1)) \
        is not None
    return listed, otc


def data_payload(db: Session, report: MarketReport, ed: Edition, now: datetime, deps: Deps, *, cutoff: datetime,
                 edition: str = "data", status_line: str | None = None, version: int = 0) \
        -> tuple[dict[str, Any], packmod.Built]:
    built = packmod.build(db, report.kind, report.edition_date, cutoff=cutoff, now=now, md_=deps.md)
    payload = assemble.build(kind=report.kind, report_id=report.id, edition_date=report.edition_date,
                             period=_period(report), next_period=_next(report), version=version, edition=edition,
                             pack=built.pack, blocks=built.blocks, output=None, published_at=now,
                             first_published_at=_aware(report.first_published_at) or now, as_of=cutoff,
                             status_line=status_line, notes=built.notes,
                             corrections=_corrections(db, report))
    return payload, built


def _corrections(db: Session, report: MarketReport) -> list[dict[str, str]]:
    cur = current(db, report)
    return list((cur.payload or {}).get("corrections") or []) if cur else []


def ai_expected(db: Session, report: MarketReport, ed: Edition, now: datetime, cfg: Any, settings: Settings,
                deps: Deps | None = None) -> bool:
    """Whether an AI edition may still come (the data edition's status line says so; the push waits for it)."""
    if report.trial or cfg.mode == "paused" or now >= ed.push_fallback_at or report.closed_at is not None:
        return False
    if deps is not None and not Caller(deps.key_pool(), settings).usable:
        return False  # no usable key (the reports' own slot disabled or out of credit): only the data edition
    if accounting.tier(db, report.kind, now, settings) == "data_only":
        return False
    runs = runs_of(db, report.id)
    if any(r.status in ("ok", "data_only") for r in runs):
        return False
    return len([r for r in runs if r.status != "running"]) < settings.ai_mreport_max_attempts


def build_data(db: Session, report: MarketReport, ed: Edition, now: datetime, deps: Deps, cfg: Any,
               res: TickResult) -> None:
    s = deps.s
    if now < ed.data_at:
        return
    cur = current(db, report)
    if report.state in ("ai", "skipped"):
        return
    if cur is not None:
        # only the close edition is refreshed (until its 15:40 cut-off), in place
        if report.kind != "close" or now >= ed.cutoff or cur.edition != "data":
            return
        built_at = datetime.fromisoformat((cur.payload or {}).get("published_at") or now.isoformat())
        if now - built_at < DATA_REBUILD:
            return
        line = assemble.STATUS_WAITING if ai_expected(db, report, ed, now, cfg, s, deps) else None
        payload, built = data_payload(db, report, ed, now, deps, cutoff=min(ed.cutoff, now), status_line=line,
                                      version=cur.version)
        cur.payload, report.notes, report.updated_at = payload, built.notes, now
        db.commit()
        res.add(report, "data refreshed")
        return
    if now >= ed.close_at:
        return
    if report.kind == "close":
        listed, otc = _session_in(db, report.edition_date)
        if not listed and not (otc and ed.skip_check_at and now >= ed.skip_check_at):
            if ed.skip_check_at and now >= ed.skip_check_at and not otc:
                report.state, report.updated_at = "skipped", now
                report.notes = [*(report.notes or []), "no_session"]
                db.commit()
                res.add(report, "skipped (no session data)")
            return
    line = assemble.STATUS_WAITING if ai_expected(db, report, ed, now, cfg, s, deps) else None
    payload, built = data_payload(db, report, ed, now, deps, cutoff=min(ed.cutoff, now), status_line=line)
    v = new_version(db, report, edition="data", payload=payload, now=now)
    report.current_version_id, report.state = v.id, "data"
    report.first_published_at = report.first_published_at or now
    report.notes, report.updated_at = built.notes, now
    db.commit()
    res.add(report, "data edition")


# -- key slots --------------------------------------------------------------------------------------------------
class Caller:
    """One attempt's calls on one key slot: the reports' own slot when configured (never borrowing a shared one),
    else the shared pool's best slot for the first call and that same slot afterwards (thinking blocks belong to
    the workspace that wrote them)."""

    def __init__(self, pool: Any, settings: Settings):
        self.pool, self.settings = pool, settings
        self.reserved = calls.has_reserved_slot(pool)
        self.slot: int | None = calls.report_slot(pool) if self.reserved else None

    @property
    def usable(self) -> bool:
        if self.reserved:
            return self.slot is not None
        return bool(getattr(self.pool, "available", False))

    def _call(self, fn: Callable[[Any], Any], only: int | None) -> tuple[Any, int]:
        target = only if only is not None else self.slot
        if target is not None:
            return self.pool.call(fn, only=target)
        return self.pool.call(fn)

    def stream(self, kw: dict[str, Any]) -> calls.CallResult:
        res, slot = self._call(lambda c: calls.stream(c, kw, timeout=self.settings.ai_mreport_timeout_seconds), None)
        self.slot = slot
        return res

    def create(self, kw: dict[str, Any], timeout: float | None = None, only: int | None = None) \
            -> tuple[calls.CallResult, int]:
        res, slot = self._call(lambda c: calls.create(c, kw, timeout=timeout), only)
        return res, slot

    def check(self, kw: dict[str, Any], attempt: int) -> calls.CallResult:
        """The compliance read: the attempt's slot first; the second try on another usable slot (only the reports'
        own slot when there is one)."""
        if attempt == 1 or self.reserved:
            res, _ = self._call(lambda c: calls.create(c, kw, timeout=120), None)
        else:
            res, _ = self.pool.call(lambda c: calls.create(c, kw, timeout=120))
        return res


# -- gathering -------------------------------------------------------------------------------------------------------
def start_gather(db: Session, report: MarketReport, ed: Edition, now: datetime, deps: Deps, cfg: Any,
                 res: TickResult) -> None:
    s = deps.s
    if cfg.mode == "paused" or now < ed.gather_at or now >= ed.push_fallback_at or report.state == "skipped":
        return
    if gather_of(db, report.id) is not None:
        return
    if report.trial:
        if not accounting.trial_fits(db, report.kind, "high", s):
            return
    elif accounting.tier(db, report.kind, now, s) == "data_only":
        return
    if not Caller(deps.key_pool(), s).usable:
        return
    g = MarketReportGather(id=new_id("mrg"), report_id=report.id, status="running", topics=[], facts=[],
                           disagreements=[], cost_usd=Decimal(0), started_at=now)
    db.add(g)
    db.commit()
    gid, rid = g.id, report.id
    deps.run(lambda: _gather_job(deps, gid, rid))
    res.add(report, "gathering")


def _gather_job(deps: Deps, gather_id: str, report_id: str) -> None:
    with deps.session() as db:
        g = db.get(MarketReportGather, gather_id)
        report = db.get(MarketReport, report_id)
        if g is None or report is None:
            return
        try:
            run_gather(db, g, report, deps)
        except Exception as exc:
            db.rollback()
            g = db.get(MarketReportGather, gather_id)
            if g is not None:
                g.status, g.finished_at = "failed", deps.clock()
                g.topics = [*(g.topics or []), {"error": type(exc).__name__}]
                db.commit()
            log.exception("market report gathering %s failed", gather_id)


def run_gather(db: Session, g: MarketReportGather, report: MarketReport, deps: Deps) -> None:
    s = deps.s
    now = deps.clock()
    ed = edition_on(report.kind, report.edition_date)
    assert ed is not None
    built = packmod.build(db, report.kind, report.edition_date, cutoff=min(ed.cutoff, now), now=now, md_=None)
    topics = gather.topics_for(report.kind, built.pack, long_holiday=ed.long_holiday)
    model, effort = rs.gather_model(s)
    caller = Caller(deps.key_pool(), s)
    feature = accounting.TRIAL_FEATURE if report.trial else "mreport_gather"

    def call(kw: dict[str, Any], only: int | None) -> tuple[Any, int]:
        return caller.create(kw, timeout=gather.TIMEOUT, only=only)

    results = gather.run_topics(topics, model, effort, call, s, clock=deps.clock)
    total = Decimal(0)
    for r in results:
        for msg in r.msgs:
            total += accounting.book_call(db, msg, requested=model, feature=feature, thread_id=g.id,
                                          key_slot=r.slot).cost_usd
    out = gather.collect(results, gather.window(built.pack, deps.clock()))  # each topic: its own last reply
    g.topics, g.facts, g.disagreements = out.topics, out.facts, out.disagreements
    g.cost_usd, g.key_slot = total, next((r.slot for r in results if r.slot), None)
    g.status = "ok" if any(r.error is None for r in results) and results else "failed"
    g.finished_at = deps.clock()
    db.commit()
    log.info("market report gathering %s: %s, %d facts, US$%.3f", g.id, g.status, len(out.facts), total)


# -- writing ---------------------------------------------------------------------------------------------------------
def start_writes(db: Session, report: MarketReport, ed: Edition, now: datetime, deps: Deps, cfg: Any,
                 res: TickResult) -> None:
    s = deps.s
    if cfg.mode == "paused" or now < ed.write_at or now >= ed.push_fallback_at or report.closed_at is not None:
        return
    if report.state in ("pending", "skipped"):
        return  # nothing to write about yet
    g = gather_of(db, report.id)
    if g is not None and g.status == "running" and now < ed.write_latest:
        return
    caller = Caller(deps.key_pool(), s)
    if not caller.usable:
        return
    if not report.trial:
        if report.state == "ai":
            return
        runs = runs_of(db, report.id)
        if any(r.status == "running" for r in runs) or any(r.status in DONE_STATUSES for r in runs):
            return
        if len(runs) >= s.ai_mreport_max_attempts:
            return
        tier = accounting.tier(db, report.kind, now, s)
        writer = rs.apply_tier(rs.chosen_writer(db, report.kind, s), tier)
        if writer is None:
            return
        _queue_run(db, report, deps, variant=None, purpose="live", attempt=len(runs) + 1, writer=writer, tier=tier,
                   gather_id=g.id if g else None, now=now)
        res.add(report, f"writing (attempt {len(runs) + 1}, {writer.model} {writer.effort}, {tier})")
        return
    all_runs = runs_of(db, report.id, any_variant=True)
    if not all_runs:  # the first time: shuffle the three settings onto A / B / C
        order = list(trial_settings(report.kind))
        secrets.SystemRandom().shuffle(order)
        assign = dict(zip(VARIANTS, order, strict=True))
    else:
        assign = {}
        for r in all_runs:
            if r.variant and r.variant not in assign:
                assign[r.variant] = (r.writer.get("model"), r.writer.get("effort"))
    for variant in VARIANTS:
        if variant not in assign:
            continue
        model, effort = assign[variant]
        writer = rs.Writer(model, effort)
        mine = [r for r in all_runs if r.variant == variant]
        if any(r.status == "running" for r in mine) or any(r.status in DONE_STATUSES for r in mine):
            continue
        if len(mine) >= s.ai_mreport_max_attempts:
            continue
        if not accounting.trial_fits(db, report.kind, effort, s):
            db.add(MarketReportRun(id=new_id("mrr"), report_id=report.id, variant=variant, purpose="trial",
                                   attempt=len(mine) + 1, status="skipped_budget", step="done", tier="normal",
                                   writer=writer.as_dict(), calls=[], cost_usd=Decimal(0), metrics={},
                                   started_at=now, heartbeat_at=now, finished_at=now))
            db.commit()
            res.add(report, f"variant {variant} skipped (trial budget)")
            continue
        _queue_run(db, report, deps, variant=variant, purpose="trial", attempt=len(mine) + 1, writer=writer,
                   tier="normal", gather_id=g.id if g else None, now=now)
        res.add(report, f"variant {variant} writing")


def _queue_run(db: Session, report: MarketReport, deps: Deps, *, variant: str | None, purpose: str, attempt: int,
               writer: rs.Writer, tier: str, gather_id: str | None, now: datetime) -> str:
    run = MarketReportRun(id=new_id("mrr"), report_id=report.id, variant=variant, purpose=purpose, attempt=attempt,
                          status="running", step="write", tier=tier, writer=writer.as_dict(), gather_id=gather_id,
                          calls=[], cost_usd=Decimal(0), metrics={}, started_at=now, heartbeat_at=now)
    db.add(run)
    db.commit()
    rid = run.id
    deps.run(lambda: _write_job(deps, rid))
    return rid


@contextmanager
def heartbeat(deps: Deps, run_id: str, every: float | None = None) -> Iterator[None]:
    """While an attempt runs, its heartbeat moves every HEARTBEAT_SECONDS from a thread of its own: one model call can
    stream for many minutes (and be sent again at medium after ``max_tokens``), and a run without a heartbeat for
    STALE is taken for dead. Only a run still ``running`` is touched."""
    stop = threading.Event()
    wait = HEARTBEAT_SECONDS if every is None else every

    def loop() -> None:
        while not stop.wait(wait):
            try:
                with deps.session() as db:
                    db.execute(update(MarketReportRun).where(MarketReportRun.id == run_id,
                                                             MarketReportRun.status == "running")
                               .values(heartbeat_at=deps.clock()))
                    db.commit()
            except Exception:
                log.warning("market report run %s: heartbeat not written", run_id, exc_info=True)

    t = threading.Thread(target=loop, name="mreport-heartbeat", daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join(timeout=5)


def _write_job(deps: Deps, run_id: str) -> None:
    with deps.session() as db:
        run = db.get(MarketReportRun, run_id)
        if run is None or run.status != "running":
            return  # abandoned (or ended) before the job started
        try:
            with heartbeat(deps, run_id):
                attempt(db, run, deps)
        except Exception as exc:
            db.rollback()
            run = db.get(MarketReportRun, run_id)
            if run is not None and run.status == "running":
                run.status, run.error, run.finished_at = "failed", type(exc).__name__[:200], deps.clock()
                db.commit()
            log.exception("market report run %s failed", run_id)


class _Stop(Exception):
    """End the attempt with a status (``data_only``, ``failed``, ``abandoned``) and a short label."""

    def __init__(self, status: str, error: str):
        super().__init__(error)
        self.status, self.error = status, error


@dataclass
class _Run:
    """What one attempt carries between its steps."""

    db: Session
    run: MarketReportRun
    report: MarketReport
    deps: Deps
    feature_write: str
    feature_check: str
    calls_: list[dict[str, Any]] = field(default_factory=list)
    raw: list[dict[str, Any]] = field(default_factory=list)

    def beat(self, step: str) -> None:
        self.run.step, self.run.heartbeat_at = step, self.deps.clock()
        self.run.calls = list(self.calls_)
        self.db.commit()

    def book(self, step: str, model: str, effort: str, msg: Any, seconds: float, feature: str, slot: int | None) \
            -> None:
        booked = accounting.book_call(self.db, msg, requested=model, feature=feature, thread_id=self.run.id,
                                      key_slot=slot)
        if slot is not None and self.run.key_slot is None:
            self.run.key_slot = slot  # the attempt's slot (the shared pool's pick is known after the first reply)
        info = calls.stop_info(msg)
        usage = getattr(msg, "usage", None)
        self.calls_.append({"step": step, "model_requested": model, "served_models": list(booked.by_model),
                            "effort": effort, "stop_reason": info["stop_reason"],
                            "refusal_category": info["refusal_category"], "fallback_used": info["fallback_used"],
                            "usage": {m: u.as_dict() for m, u in booked.by_model.items()},
                            "web_search_requests": accounting.server_tool_searches(usage),
                            "cost_usd": float(booked.cost_usd), "seconds": round(seconds, 1)})
        self.run.cost_usd = Decimal(self.run.cost_usd or 0) + booked.cost_usd
        self.beat(step)

    @property
    def over_alarm(self) -> bool:
        return float(self.run.cost_usd or 0) > self.deps.s.ai_mreport_run_alarm_usd


def attempt(db: Session, run: MarketReportRun, deps: Deps, deadline: bool = True) -> None:
    """One writing attempt from the pack to a published version (or the data edition). ``deadline``: a result after
    the edition closed is dropped (not for an attempt started by hand)."""
    s = deps.s
    report = db.get(MarketReport, run.report_id)
    if report is None:
        return
    ed = edition_on(report.kind, report.edition_date)
    assert ed is not None
    now = deps.clock()
    trial = run.purpose == "trial"
    ctx = _Run(db, run, report, deps, accounting.TRIAL_FEATURE if trial else "mreport_write",
               accounting.TRIAL_FEATURE if trial else "mreport_check")
    writer = rs.Writer(run.writer["model"], run.writer["effort"])
    cutoff = min(ed.cutoff, now)
    built = packmod.build(db, report.kind, report.edition_date, cutoff=cutoff, now=now, md_=deps.md)
    pk = built.pack
    g = db.get(MarketReportGather, run.gather_id) if run.gather_id else None
    if g is not None and g.status == "ok":
        pk["web"] = gather.for_writer(g.facts or [])
        pk["disagreements"] = list(g.disagreements or [])
    run.pack_gz = zlib.compress(json.dumps(pk, ensure_ascii=False, default=str).encode("utf-8"))
    ctx.beat("write")
    caller = Caller(deps.key_pool(), s)
    metrics: dict[str, Any] = {"revised": False, "data_only": False, "dropped_sections": 0, "policy_violations": 0,
                               "subject_mismatches": 0, "inferred_dates": 0, "fallback_used": False,
                               "refusal_category": None}
    try:
        if not caller.usable:
            raise _Stop("data_only", "no_key")
        final, info = _write_and_check(ctx, caller, writer, pk, metrics)
    except _Stop as stop:
        _finish(ctx, stop.status, stop.error, metrics, started=now)
        if stop.status == "data_only":
            _close_line_if_done(db, report, ed, deps)
        return
    # assemble and publish
    ctx.beat("assemble")
    finished = deps.clock()
    db.refresh(report)
    db.refresh(run)
    if run.status != "running":  # taken for dead meanwhile (another attempt may have started): never published
        log.warning("market report run %s was %s before publishing; its result is dropped", run.id, run.status)
        _finish(ctx, "abandoned", "stale", metrics, started=now)
        return
    if deadline and (report.closed_at is not None or finished >= ed.close_at):
        _finish(ctx, "abandoned", "after_close", metrics, started=now)
        return
    extra = _extra_charts(report.kind, final["output"], pk, deps)
    payload = assemble.build(
        kind=report.kind, report_id=report.id, edition_date=report.edition_date, period=_period(report),
        next_period=_next(report), version=0, edition="ai", pack=pk, blocks=built.blocks, output=final["output"],
        published_at=finished, first_published_at=_aware(report.first_published_at) or finished, as_of=cutoff,
        dropped=final["dropped"], title_origin=final["title_origin"], highlights_origin=final["highlights_origin"],
        mentions_anthropic=final["mentions_anthropic"], corrections=_corrections(db, report), notes=built.notes,
        extra_charts=extra, dropped_output=final["draft"])
    v = new_version(db, report, edition="ai", payload=payload, now=finished, variant=run.variant,
                    writer={**writer.as_dict(), "tier": run.tier}, run_id=run.id, validation=info)
    if run.variant is None:
        report.current_version_id, report.state = v.id, "ai"
        report.ai_published_at = finished
        report.first_published_at = report.first_published_at or finished
        report.updated_at = finished
    metrics["on_time"] = finished <= ed.publish_target
    metrics["seconds"] = round((finished - now).total_seconds(), 1)
    _finish(ctx, "ok", None, metrics, started=now)
    log.info("market report %s %s published (%s%s, US$%.3f)", report.kind, report.edition_date, writer.model,
             f", variant {run.variant}" if run.variant else "", float(run.cost_usd or 0))
    if run.variant is None and report.kind == "close" and not report.backfill:
        _write_back(db, report, pk, deps)


def _finish(ctx: _Run, status: str, error: str | None, metrics: dict[str, Any], started: datetime) -> None:
    """The run's end, only while it is still ``running`` (a run abandoned meanwhile keeps that status; its calls and
    cost are written all the same)."""
    run, db = ctx.run, ctx.db
    finished = ctx.deps.clock()
    db.flush()
    metrics.setdefault("seconds", round((finished - started).total_seconds(), 1))
    metrics.setdefault("on_time", False)
    metrics["data_only"] = metrics.get("data_only") or status == "data_only"
    metrics["fallback_used"] = any(c.get("fallback_used") for c in ctx.calls_)
    metrics["cost_usd"] = float(run.cost_usd or 0)
    kept = {"metrics": metrics, "calls": [*ctx.calls_, *({"raw_output": r} for r in ctx.raw)],
            "cost_usd": Decimal(run.cost_usd or 0)}
    rid = run.id
    done = db.execute(update(MarketReportRun).where(MarketReportRun.id == rid, MarketReportRun.status == "running")
                      .values(status=status, error=error, step="done", finished_at=finished, **kept))
    if not done.rowcount:  # type: ignore[attr-defined]
        db.execute(update(MarketReportRun).where(MarketReportRun.id == rid).values(**kept))
        log.warning("market report run %s ended (%s) after it was no longer running", rid, status)
    db.commit()


def _close_line_if_done(db: Session, report: MarketReport, ed: Edition, deps: Deps) -> None:
    """No AI edition will come for this attempt: the data edition says so when no attempt is left."""
    cfg = rs.config(db, deps.s)
    cur = current(db, report)
    if cur is None or cur.edition != "data":
        return
    if not ai_expected(db, report, ed, deps.clock(), cfg, deps.s, deps):
        cur.payload = {**(cur.payload or {}), "status_line": assemble.STATUS_DATA_ONLY}
        db.commit()


def _check(ctx: _Run, caller: Caller, output: dict[str, Any], kind: str) -> list[validate.Problem]:
    """The compliance read; a failure twice ends the attempt with the data edition."""
    model, effort = rs.check_model(ctx.deps.s)
    checked = compliance.check(output, kind, model, effort, caller.check, ctx.deps.s)
    for msg, seconds in checked.msgs:
        ctx.book("check", model, effort, msg, seconds, ctx.feature_check, caller.slot)
    if not checked.ok:
        raise _Stop("data_only", f"check_failed:{checked.error or ''}"[:200])
    return [validate.Problem(i["path"], f"compliance:{i['category']}", i["quote"]) for i in checked.issues]


def _write_and_check(ctx: _Run, caller: Caller, writer: rs.Writer, pk: dict[str, Any],
                     metrics: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    kind = ctx.report.kind
    s = ctx.deps.s
    names = instrument_names(ctx.db, ctx.deps.clock().astimezone(TAIPEI).date())

    def booked(w: write.Written) -> None:
        for step, model, effort, msg, seconds in w.msgs:
            ctx.book(step, model, effort, msg, seconds, ctx.feature_write, caller.slot)
        if w.output is not None:
            ctx.raw.append(w.output)

    draft = write.write(kind, pk, writer, caller.stream, s)
    booked(draft)  # every reply, also when a later call raised
    if draft.exc is not None:
        raise _Stop("failed", draft.error or "write")
    if draft.refusal is not None:
        metrics["refusal_category"] = draft.refusal or None
        raise _Stop("data_only", f"refusal:{draft.refusal}"[:200])
    if draft.output is None:
        raise _Stop("failed", draft.error or "write")
    out = validate.tidy(draft.output, kind, pk)
    first = validate.validate(out, pk, kind, names)
    metrics["subject_mismatches"] = sum(p.code == "number_subject_mismatch" for p in first)
    metrics["inferred_dates"] = sum(p.code in ("date_not_sourced", "weekday_mismatch") for p in first)
    info: dict[str, Any] = {"first": [p.as_dict() for p in first], "revised": [], "dropped": {}, "check_ran": False,
                            "counts": validate.counts(first)}
    hard = [p for p in first if p.hard]
    issues: list[validate.Problem] = []
    if not hard:
        if ctx.over_alarm:
            raise _Stop("data_only", "alarm")
        issues = _check(ctx, caller, out, kind)
        info["check_ran"] = True
    final_out, final_problems, source = out, [*hard, *issues], draft.output
    if hard or issues:
        if ctx.over_alarm:
            log.warning("market report run %s over the alarm", ctx.run.id)
            raise _Stop("data_only", "alarm")
        ctx.beat("revise")
        metrics["revised"] = True
        rev = write.revise(kind, pk, writer, caller.stream, draft, [p.as_dict() for p in [*hard, *issues]], s)
        booked(rev)
        if rev.exc is not None:
            raise _Stop("failed", rev.error or "revise")
        if rev.refusal is not None:
            metrics["refusal_category"] = rev.refusal or None
            raise _Stop("data_only", f"refusal:{rev.refusal}"[:200])
        if rev.output is not None:
            final_out, source = validate.tidy(rev.output, kind, pk), rev.output
        second = validate.validate(final_out, pk, kind, names)
        info["revised"] = [p.as_dict() for p in second]
        dropped = validate.drop(final_out, [p for p in second if p.hard], kind, pk, names)
        if ctx.over_alarm:
            log.warning("market report run %s over the alarm", ctx.run.id)
            raise _Stop("data_only", "alarm")
        ctx.beat("check")
        issues2 = _check(ctx, caller, dropped.output, kind)  # what is left is read once more
        info["check_ran"] = True
        dropped2 = validate.drop(dropped.output, issues2, kind, pk, names)
        info["revised"] += [p.as_dict() for p in issues2]
        sections = {**dropped.sections}
        for k, v in dropped2.sections.items():
            sections.setdefault(k, []).extend(x for x in v if x not in sections.get(k, []))
        title_bad = dropped.title_bad or dropped2.title_bad
        highlights_bad = dropped.highlights_bad or dropped2.highlights_bad
        final_out = dropped2.output
        info["dropped_sentences"] = [*dropped.sentences, *dropped2.sentences]  # taken out alone (paths of each pass)
        final_problems = [*[p for p in second if p.hard], *issues2]
    else:
        sections, title_bad, highlights_bad = {}, False, False
    replaced = {k for k, bad in (("title", title_bad), ("highlights", highlights_bad)) if bad}
    last = validate.validate(final_out, pk, kind, names)
    metrics["policy_violations"] = sum(p.code == "index_points" and p.key not in replaced for p in last)
    metrics["dropped_sections"] = len(sections)
    info["dropped"] = sections
    if validate.ai_sections_left(final_out, kind) < 2 or (title_bad and highlights_bad):
        raise _Stop("data_only", "too_little_left")
    info["mentions_anthropic"] = validate.mentions_anthropic(final_out, kind)
    info["counts_final"] = validate.counts(final_problems)
    return ({"output": final_out, "dropped": sections, "draft": source,
             "title_origin": "rules" if title_bad else "ai", "highlights_origin": "rules" if highlights_bad else "ai",
             "mentions_anthropic": info["mentions_anthropic"]}, info)


def _extra_charts(kind: str, output: dict[str, Any], pk: dict[str, Any], deps: Deps) -> dict[str, Any]:
    """A 今日圖 G5 of another list than the fixed one (gainers / losers): drawn from the archive like the fixed G5."""
    ch = output.get("chart_of_day") if isinstance(output, dict) else None
    if not isinstance(ch, dict) or ch.get("code") != "G5" or ch.get("set") in (None, "none", "top5_weight") \
            or deps.md is None:
        return {}
    want = {"gainers": ("漲幅前 5", "週漲幅前 5", "漲停中市值最大 5 檔"),
            "losers": ("跌幅前 5", "週跌幅前 5", "跌停中市值最大 5 檔")}.get(str(ch.get("set")), ())
    symbols = [s["symbol"] for s in pk.get("stocks") or [] if set(s.get("lists") or []) & set(want)][:5]
    if len(symbols) < 2:
        return {}
    try:  # the pack's data day: never a close after it (contract §13.2, the dry run of 11/17)
        through = date.fromisoformat(str(pk["data_through"]))
    except (KeyError, TypeError, ValueError):
        return {}
    title = {"gainers": "漲幅前 5 檔一個月比較", "losers": "跌幅前 5 檔一個月比較"}[str(ch["set"])]
    try:
        card = packmod.g5_card(deps.md, symbols, f"{title}（至 {md(through)}）", through)
    except Exception:
        return {}
    return {f"G5:{ch['set']}": card} if card is not None else {}


def _write_back(db: Session, report: MarketReport, pk: dict[str, Any], deps: Deps) -> None:
    """§5.6: the verified reports about listed stocks join the shared 「為什麼漲跌」 research of the session."""
    from forliosa.ai.research import remember_report_sources

    by_code = {str(s["code"]): s["symbol"] for s in pk.get("stocks") or []}
    groups: dict[str, list[dict[str, Any]]] = {}
    for x in pk.get("web") or []:
        key = str(x.get("key") or "")
        if not key.startswith("STOCK."):
            continue
        sym = by_code.get(key.split(".", 1)[1])
        if sym:
            groups.setdefault(sym, []).append({"url": x.get("url"), "title": x.get("title"), "outlet": x.get("outlet"),
                                               "snippets": [x.get("quote") or ""], "page_age": x.get("published_at"),
                                               "found_at": None})
    for sym, sources in groups.items():
        try:
            remember_report_sources(db, sym, report.edition_date, sources, deps.clock(), deps.s)
        except Exception:
            db.rollback()
            log.warning("market report %s: shared research of %s not written", report.id, sym)


# -- push, close, tables ------------------------------------------------------------------------------------------
def maybe_push(db: Session, report: MarketReport, ed: Edition, now: datetime, deps: Deps, cfg: Any,
               res: TickResult) -> None:
    if report.pushed_at is not None or now < ed.push_at or not push.may_push(db, report, deps.s):
        return
    if now >= push_deadline(ed):
        return  # too late (the worker was down past the deadline): not pushed at all
    if report.state == "ai":
        edition = "ai"
    elif now >= ed.push_fallback_at or (not ai_expected(db, report, ed, now, cfg, deps.s, deps)
                                        and not _running(db, report)):
        edition = "data"  # the fallback time comes before the close (17:30 / 21:00 are both): it is pushed then
    else:
        return
    n = push.enqueue(db, report, now, deps.s)
    report.pushed_at, report.push_edition, report.updated_at = now, edition, now
    db.commit()
    res.add(report, f"push queued ({edition}, {n} channels)")


def push_deadline(ed: Edition) -> datetime:
    """After this nothing is pushed (the worker was down): the close, but never sooner than PUSH_GRACE after the push
    fallback time (the close and the weekly have their fallback at the close itself)."""
    return max(ed.close_at, ed.push_fallback_at + PUSH_GRACE)


def _running(db: Session, report: MarketReport) -> bool:
    return any(r.status == "running" for r in runs_of(db, report.id, any_variant=True)) or (
        (g := gather_of(db, report.id)) is not None and g.status == "running")


def maybe_close(db: Session, report: MarketReport, ed: Edition, now: datetime, deps: Deps, res: TickResult) -> None:
    if report.closed_at is not None or now < ed.close_at:
        return
    report.closed_at, report.updated_at = now, now
    cur = current(db, report)
    if cur is not None and cur.edition == "data":
        cur.payload = {**(cur.payload or {}), "status_line": assemble.STATUS_DATA_ONLY}
    db.commit()
    res.add(report, "closed")


def maybe_tables(db: Session, report: MarketReport, ed: Edition, now: datetime, deps: Deps,
                 res: TickResult) -> None:
    if report.kind != "close" or report.state in ("pending", "skipped"):
        return
    for at in ed.tables_at:
        if not at <= now < at + TABLES_WINDOW:
            continue
        done = db.scalar(select(MarketReportVersion.id).where(
            MarketReportVersion.report_id == report.id, MarketReportVersion.edition == "tables",
            MarketReportVersion.created_at >= at).limit(1))
        if done:
            continue
        add_tables(db, report, now, deps)
        res.add(report, f"tables {at:%H:%M}")


def add_tables(db: Session, report: MarketReport, now: datetime, deps: Deps) -> MarketReportVersion:
    """A ``tables`` version from everything stored by ``now``: the AI text kept, the server's blocks rebuilt."""
    cur = current(db, report)
    built = packmod.build(db, report.kind, report.edition_date, cutoff=now, now=now, md_=deps.md)
    if cur is not None and cur.edition in ("ai", "tables", "correction") and (cur.payload or {}).get("has_ai"):
        payload = assemble.retable(cur.payload, report.kind, built.pack, built.blocks, version=0, published_at=now,
                                   as_of=now)
    else:
        payload, _ = data_payload(db, report, edition_on(report.kind, report.edition_date), now, deps,  # type: ignore[arg-type]
                                  cutoff=now, edition="tables", status_line=assemble.STATUS_DATA_ONLY)
    v = new_version(db, report, edition="tables", payload=payload, now=now, based_on=cur.id if cur else None,
                    writer=cur.writer if cur else None, run_id=cur.run_id if cur else None)
    report.current_version_id, report.notes, report.updated_at = v.id, built.notes, now
    db.commit()
    return v


def abandon_stale(db: Session, now: datetime) -> int:
    n = 0
    for r in db.scalars(select(MarketReportRun).where(MarketReportRun.status == "running")):
        if (_aware(r.heartbeat_at) or now) < now - STALE:
            r.status, r.error, r.finished_at = "abandoned", "stale", now
            n += 1
    for g in db.scalars(select(MarketReportGather).where(MarketReportGather.status == "running")):
        if (_aware(g.started_at) or now) < now - STALE:
            g.status, g.finished_at = "failed", now
            n += 1
    if n:
        db.commit()
        log.warning("market reports: %d stale runs abandoned", n)
    return n


KEY_STATE_EVERY = timedelta(minutes=5)


def record_key_state(db: Session, cfg: Any, deps: Deps, now: datetime) -> None:
    """The reports' own key slot as this (the worker's) pool sees it, for the admin page (the API process never uses
    the slot): written when it changes, else every KEY_STATE_EVERY. Never the key itself."""
    from forliosa.ai import store

    try:
        pool = deps.key_pool()
        state = calls.slot_state(pool, store.slot_month_costs(db, now) if calls.has_reserved_slot(pool) else None)
    except Exception:
        log.warning("market reports: key state not read", exc_info=True)
        return
    old = dict(cfg.key_state or {})
    checked = old.pop("checked_at", None)
    try:
        fresh = checked is not None and now - datetime.fromisoformat(str(checked)) < KEY_STATE_EVERY
    except ValueError:
        fresh = False
    if old == state and fresh:
        return
    # only this column (``updated_at`` / ``updated_by`` stay the admin's last change)
    db.execute(update(MarketReportConfig).where(MarketReportConfig.id == cfg.id)
               .values(key_state={**state, "checked_at": now.isoformat()}, updated_at=MarketReportConfig.updated_at))
    db.commit()


# -- tick ------------------------------------------------------------------------------------------------------------
def editions(now: datetime) -> list[Edition]:
    """The editions a tick looks at: today's three kinds, and yesterday's close edition (its 06:40 tables)."""
    today = now.astimezone(TAIPEI).date()
    out = []
    for kind, d in (("premarket", today), ("close", today), ("close", today - timedelta(days=1)),
                    ("weekly", today)):
        ed = edition_on(kind, d)
        if ed is not None:
            out.append(ed)
    return out


def tick(now: datetime | None = None, deps: Deps | None = None) -> TickResult:
    deps = deps or default_deps()
    now = (now or now_taipei()).astimezone(TAIPEI)
    res = TickResult()
    from forliosa.market_calendar import load_official_calendar
    from forliosa.reports import calendars

    with deps.session() as db:
        load_official_calendar(db)
        calendars.load_us_calendar(db)
        abandon_stale(db, now)
        cfg = rs.config(db, deps.s)
        record_key_state(db, cfg, deps, now)
        for ed in editions(now):
            report = ensure_report(db, ed, now, cfg, deps.s)
            if report is None or report.backfill:
                continue
            build_data(db, report, ed, now, deps, cfg, res)
            if report.state == "skipped":
                continue
            start_gather(db, report, ed, now, deps, cfg, res)
            start_writes(db, report, ed, now, deps, cfg, res)
            maybe_push(db, report, ed, now, deps, cfg, res)
            maybe_close(db, report, ed, now, deps, res)
            maybe_tables(db, report, ed, now, deps, res)
    if res.actions:
        log.info("market reports: %s", "; ".join(res.actions))
    return res


# -- retention -------------------------------------------------------------------------------------------------------
def purge_old(db: Session, now: datetime | None = None, settings: Settings | None = None) -> int:
    """Editions older than MARKET_REPORT_RETENTION_DAYS (by edition date) with their versions, runs, gatherings and
    votes (foreign keys cascade) and their outbox rows."""
    from sqlalchemy import delete

    from forliosa.models import MarketReportVote, NotificationOutbox

    s = settings or get_settings()
    now = now or now_utc()
    limit = now.astimezone(TAIPEI).date() - timedelta(days=s.market_report_retention_days)
    ids = list(db.scalars(select(MarketReport.id).where(MarketReport.edition_date < limit)))
    if not ids:
        return 0
    db.execute(delete(NotificationOutbox).where(NotificationOutbox.market_report_id.in_(ids)))
    for model in (MarketReportVersion, MarketReportRun, MarketReportGather, MarketReportVote):
        db.execute(delete(model).where(model.report_id.in_(ids)))
    db.execute(delete(MarketReport).where(MarketReport.id.in_(ids)))
    db.commit()
    return len(ids)


# -- the command line: one edition by hand ----------------------------------------------------------------------------
def backfill_data(db: Session, kind: str, d: date, deps: Deps, now: datetime | None = None) -> MarketReport:
    """``python -m forliosa.reports data``: the data edition of ``d`` (a past date: a backfill, admins only, never
    pushed; today: the scheduled edition's own row)."""
    now = (now or deps.clock()).astimezone(TAIPEI)
    ed = edition_on(kind, d)
    if ed is None:
        raise ValueError(f"沒有 {d} 的{kind}")
    report = report_of(db, kind, d)
    past = d < now.date()
    if report is None:
        cfg = rs.config(db, deps.s)
        report = make_report(db, ed, now, visibility="admin" if past or cfg.mode != "public" else "public",
                             backfill=past)
    cutoff = min(ed.cutoff, now)
    payload, built = data_payload(db, report, ed, now, deps, cutoff=cutoff,
                                  status_line=assemble.STATUS_DATA_ONLY if past else None)
    v = new_version(db, report, edition="data", payload=payload, now=now)
    if report.state != "ai":
        report.current_version_id, report.state = v.id, "data"
    report.first_published_at = report.first_published_at or now
    report.notes, report.updated_at = built.notes, now
    db.commit()
    return report


def run_once(db: Session, kind: str, d: date, writer: rs.Writer, deps: Deps, now: datetime | None = None) \
        -> MarketReportRun:
    """``python -m forliosa.reports run``: one full AI attempt now (gathering, writing, checks) for ``d``. A past date
    is a backfill (admins only); the edition's deadline does not apply."""
    now = (now or deps.clock()).astimezone(TAIPEI)
    report = report_of(db, kind, d) or backfill_data(db, kind, d, deps, now)
    if report.current_version_id is None:
        report = backfill_data(db, kind, d, deps, now)
    g = MarketReportGather(id=new_id("mrg"), report_id=report.id, status="running", topics=[], facts=[],
                           disagreements=[], cost_usd=Decimal(0), started_at=now)
    db.add(g)
    db.commit()
    run_gather(db, g, report, deps)
    attempts = len(runs_of(db, report.id))
    run = MarketReportRun(id=new_id("mrr"), report_id=report.id, variant=None, purpose="live", attempt=attempts + 1,
                          status="running", step="write", tier="normal", writer=writer.as_dict(), gather_id=g.id,
                          calls=[], cost_usd=Decimal(0), metrics={}, started_at=now, heartbeat_at=now)
    db.add(run)
    db.commit()
    with heartbeat(deps, run.id):  # the worker's tick would take a long run for dead otherwise
        attempt(db, run, deps, deadline=False)
    return run
