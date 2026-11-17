"""行事曆 for the market reports: the hand-kept tables (NYSE holidays, macro releases, US earnings dates), the rule-made
events (TAIEX futures and options settlement days) and the archive's announcements, as one list of dated rows.

* ``nyse_holidays`` → :mod:`forliosa.timeutil` (:func:`load_us_calendar`): US sessions skip the closures and an early
  close moves ``us_close_dt``. Loaded at worker start, on every report tick and before an API read (one small query,
  like ``market_calendar.load_official_calendar``).
* ``seeds/*.json`` → the three tables (:func:`seed`; a row someone marked as checked is never overwritten).
* US Eastern times are turned into Taipei times by the program (:func:`to_taipei`, :func:`earnings_label`) — never by a
  model.
* Every hand-kept row links to an official page (:data:`OFFICIAL_CALENDAR_HOSTS` for macro rows); those pages are
  linked, never fetched.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.ids import new_id
from forliosa.models import MacroCalendarEvent, MarketEvent, NyseHoliday, UsEarningsDate
from forliosa.timeutil import NEW_YORK, TAIPEI, is_tw_trading_day, now_utc, set_us_calendar

log = logging.getLogger(__name__)

SEEDS = Path(__file__).resolve().parent / "seeds"
NYSE_URL = "https://www.nyse.com/markets/hours-calendars"
OFFICIAL_CALENDAR_HOSTS = (
    "federalreserve.gov", "bls.gov", "bea.gov", "census.gov", "treasury.gov", "home.treasury.gov", "dol.gov",
    "dgbas.gov.tw", "stat.gov.tw", "ndc.gov.tw", "mof.gov.tw", "moea.gov.tw", "cbc.gov.tw", "ecb.europa.eu",
    "boj.or.jp",
)
OFFICIAL_URL_ERROR = "只能連到官方網站（例如 bls.gov、dgbas.gov.tw）。"
SETTLEMENT_NOTE = "最後結算價是當天收盤前 30 分鐘指數的簡單算術平均"

KIND_LABELS = {
    "settlement": "結算日", "ex_dividend": "除權息", "investor_conference": "法說會", "earnings": "財報",
    "revenue_release": "營收", "shareholder_meeting": "股東會", "attention": "注意股", "disposition": "處置股",
    "material_info": "重大訊息", "macro": "總經數據", "us_earnings": "美股財報", "us_holiday": "美股休市",
}
# Rows folded into one line on phones (contract §7.6.4): fold key -> label (the count follows)
FOLD_LABELS = {"etf_ex": "ETF 除息", "bond_etf_ex": "債券 ETF 除息", "reit_ex": "REIT 除息",
               "invited_conference": "受邀參加法說會", "other_filings": "其他重大訊息"}
FOLD_UNITS = {"etf_ex": "檔", "bond_etf_ex": "檔", "reit_ex": "檔", "invited_conference": "家", "other_filings": "則"}


# -- NYSE holidays -> timeutil -------------------------------------------------------------------------------------
def load_us_calendar(db: Session) -> int:
    """Apply ``nyse_holidays`` to ``timeutil``; returns the number of rows (0 = weekdays only)."""
    try:
        rows = list(db.scalars(select(NyseHoliday)))
    except Exception as exc:  # the table does not exist yet (migrations not run)
        log.warning("NYSE calendar not loaded: %s", type(exc).__name__)
        db.rollback()
        return 0
    closed = [r.date for r in rows if r.kind == "closed"]
    early = {r.date: _hhmm(r.close_time_et) or time(13, 0) for r in rows if r.kind == "early_close"}
    set_us_calendar(closed, early)
    return len(rows)


def _hhmm(raw: str | None) -> time | None:
    if not raw:
        return None
    try:
        hh, mm = raw.split(":")
        return time(int(hh), int(mm))
    except (ValueError, TypeError):
        return None


def nyse_status(db: Session, today: date) -> dict[str, Any]:
    """For the admin page: the next closure or early close, and how many rows nobody has checked yet."""
    rows = sorted(db.scalars(select(NyseHoliday)), key=lambda r: r.date)
    upcoming = next((r for r in rows if r.date >= today), None)
    return {"next": {"date": upcoming.date, "name": upcoming.name, "kind": upcoming.kind} if upcoming else None,
            "unverified": sum(1 for r in rows if r.verified_at is None), "rows": len(rows)}


# -- seeds -----------------------------------------------------------------------------------------------------------
def _seed_rows(name: str) -> list[dict[str, Any]]:
    return list(json.loads((SEEDS / name).read_text(encoding="utf-8")).get("rows") or [])


def seed(db: Session) -> dict[str, int]:
    """Upsert ``seeds/*.json`` into the three hand-kept tables. A row already marked as checked (``verified_at``) is
    left as it is; so is anything a site admin added. Returns rows written per table."""
    now = now_utc()
    written = {"nyse_holidays": 0, "macro_calendar": 0, "us_earnings": 0}
    for r in _seed_rows("nyse_holidays.json"):
        d = date.fromisoformat(r["date"])
        row = db.get(NyseHoliday, d)
        if row is not None and row.verified_at is not None:
            continue
        row = row or NyseHoliday(date=d)
        row.name, row.kind, row.close_time_et = r["name"], r["kind"], r.get("close_time_et")
        row.source_url = r.get("source_url") or NYSE_URL
        row.updated_by, row.updated_at = "seed", now
        db.add(row)
        written["nyse_holidays"] += 1
    for r in _seed_rows("macro_calendar.json"):
        if not official_url_ok(r.get("official_url")):
            log.warning("seed: macro row %s skipped (not an official page)", r.get("title"))
            continue
        exists = db.scalar(select(MacroCalendarEvent).where(
            MacroCalendarEvent.event_date == date.fromisoformat(r["event_date"]),
            MacroCalendarEvent.title == r["title"]))
        if exists is not None:
            continue
        db.add(MacroCalendarEvent(id=new_id("mac"), event_date=date.fromisoformat(r["event_date"]),
                                  local_time=r.get("local_time"), tz=r["tz"], country=r["country"],
                                  title=r["title"], agency=r["agency"], official_url=r["official_url"],
                                  sectors=list(r.get("sectors") or []), note=r.get("note") or "", created_by="seed",
                                  updated_at=now))
        written["macro_calendar"] += 1
    for r in _seed_rows("us_earnings.json"):
        d = date.fromisoformat(r["report_date"])
        row = db.scalar(select(UsEarningsDate).where(UsEarningsDate.symbol == r["symbol"],
                                                     UsEarningsDate.report_date == d))
        if row is not None and row.verified_at is not None:
            continue
        if r.get("official_url") and not earnings_url_ok(r["official_url"]):
            continue
        row = row or UsEarningsDate(id=new_id("use"), symbol=r["symbol"], report_date=d)
        row.company, row.timing, row.time_et = r["company"], r.get("timing") or "unknown", r.get("time_et")
        row.official_url, row.sectors, row.note = r.get("official_url"), list(r.get("sectors") or []), \
            r.get("note") or ""
        row.created_by, row.updated_at = row.created_by or "seed", now
        db.add(row)
        written["us_earnings"] += 1
    db.commit()
    load_us_calendar(db)
    return written


def ensure_seeded(db: Session) -> bool:
    """Seed once when ``nyse_holidays`` is empty (worker start). True when it seeded."""
    try:
        empty = db.scalar(select(NyseHoliday.date).limit(1)) is None
    except Exception:
        db.rollback()
        return False
    if empty:
        seed(db)
    return empty


# -- official links ------------------------------------------------------------------------------------------------
def _host(url: str | None) -> str:
    try:
        return (urlsplit(url or "").hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def official_url_ok(url: str | None) -> bool:
    """https, and the host is an official calendar host or one of its subdomains."""
    if not url or not url.lower().startswith("https://"):
        return False
    host = _host(url)
    return any(host == h or host.endswith("." + h) for h in OFFICIAL_CALENDAR_HOSTS)


def earnings_url_ok(url: str | None) -> bool:
    """A US earnings row's optional link: https and not a quote page, forum or blog (``news.outlets``)."""
    from forliosa.news.outlets import NOT_NEWS_DOMAINS

    if not url:
        return True
    if not url.lower().startswith("https://"):
        return False
    host = _host(url)
    return bool(host) and not any(host == h or host.endswith("." + h) for h in NOT_NEWS_DOMAINS)


# -- rule-made events ----------------------------------------------------------------------------------------------
def settlement_day(year: int, month: int) -> date:
    """TAIEX futures / options monthly final settlement: the third Wednesday, moved to the next Taiwan trading day when
    the market is closed that day."""
    first = date(year, month, 1)
    d = first + timedelta(days=(2 - first.weekday()) % 7 + 14)
    while not is_tw_trading_day(d):
        d += timedelta(days=1)
    return d


def settlement_days(start: date, end: date) -> list[date]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        d = settlement_day(y, m)
        if start <= d <= end:
            out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


# -- time zones ----------------------------------------------------------------------------------------------------
def to_taipei(d: date, local: str | None, tz: str) -> datetime | None:
    """A local date and ``HH:MM`` in ``tz`` -> the Taipei time (``None`` without a time)."""
    t = _hhmm(local)
    if t is None:
        return None
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return datetime.combine(d, t, zone).astimezone(TAIPEI)


def taipei_part(dt: datetime) -> str:
    """清晨 / 上午 / 下午 / 晚上 / 深夜 of a Taipei time."""
    h = dt.astimezone(TAIPEI).hour
    if h < 6:
        return "清晨"
    if h < 12:
        return "上午"
    if h < 18:
        return "下午"
    return "晚上" if h < 23 else "深夜"


# typical US Eastern times when only bmo / amc / during is known (for the Taipei date and part of day)
_TYPICAL_ET = {"bmo": time(7, 0), "amc": time(16, 30), "during": time(12, 0)}
_TIMING_TEXT = {"bmo": "盤前", "amc": "盤後", "during": "盤中"}


def earnings_taipei(report_date: date, timing: str, time_et: str | None) -> datetime | None:
    t = _hhmm(time_et) or _TYPICAL_ET.get(timing)
    return datetime.combine(report_date, t, NEW_YORK).astimezone(TAIPEI) if t else None


def earnings_label(report_date: date, timing: str, time_et: str | None = None) -> str:
    """「美東 11/19 盤後（台北 11/20 清晨）」, 「美東 11/19 盤前（台北 11/19 晚上）」,
    「美東 11/19 16:05（台北 11/20 05:05）」; 「美東 11/19」 when nothing more is known."""
    md = f"{report_date.month}/{report_date.day}"
    tp = earnings_taipei(report_date, timing, time_et)
    if tp is None:
        return f"美東 {md}"
    tmd = f"{tp.month}/{tp.day}"
    if _hhmm(time_et):
        return f"美東 {md} {time_et}（台北 {tmd} {tp:%H:%M}）"
    return f"美東 {md} {_TIMING_TEXT.get(timing, '')}（台北 {tmd} {taipei_part(tp)}）"


# -- one list of dated rows ----------------------------------------------------------------------------------------
@dataclass
class CalEvent:
    date: date  # Taipei date
    title: str
    kind: str
    source: str  # a dataset key, "rules:settlement" or "manual-calendar"
    time_taipei: str | None = None  # "13:30"
    time_label: str | None = None  # what the page shows: "13:30", "台北 21:30", "美東 11/19 盤後（台北 11/20 清晨）"
    symbol: str | None = None
    sectors: list[str] = field(default_factory=list)
    url: str | None = None
    fold: str | None = None  # FOLD_LABELS key
    note: str = ""

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)


def _clock(raw: Any) -> str | None:
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if not 4 <= len(digits) <= 6:
        return None
    digits = digits.zfill(6)
    return f"{digits[:2]}:{digits[2:4]}"


def _served(source: str, kind: str, policy: str) -> bool:
    from forliosa.datapolicy import dataset_served

    return dataset_served(f"{source}/{kind}", policy)  # type: ignore[arg-type]


def events_between(db: Session, start: date, end: date, *, cutoff: datetime, policy: str = "commercial",
                   top100: Iterable[str] = (), names: dict[str, str] | None = None,
                   classes: dict[str, str] | None = None, include_filings: bool = True) -> list[CalEvent]:
    """Every scheduled or announced row from ``start`` to ``end`` (Taipei dates, both included) that existed at
    ``cutoff``: settlement days, ex-dividend dates, investor conferences, shareholder meetings, attention and
    disposition notices, material information (``include_filings``), macro releases, US earnings, NYSE closures.

    ``top100``: symbols among the 100 largest by market cap (their filings are listed one by one; the others fold).
    ``classes``: symbol -> security class (ETF / bond ETF / REIT ex-dividend rows fold by class)."""
    from forliosa.services.announcements import classify
    from forliosa.services.instruments import security_class

    top = set(top100)
    names = names or {}
    classes = classes or {}
    out: list[CalEvent] = []
    for d in settlement_days(start, end):
        out.append(CalEvent(d, f"台指期貨、台指選擇權 {d.month} 月契約最後結算日", "settlement", "rules:settlement",
                            "13:30", "13:30", note=SETTLEMENT_NOTE))
    cutoff_utc = cutoff
    lookback = start - timedelta(days=60)  # investor conferences are announced weeks ahead
    rows = db.scalars(select(MarketEvent).where(
        MarketEvent.type.in_(("ex_dividend", "shareholder_meeting", "attention", "disposition", "material_info")),
        MarketEvent.date <= end, MarketEvent.date >= lookback))
    # stocks, funds, REITs and preferred shares only (no convertible bonds or warrants such as 24552)
    rows = [e for e in rows if (e.created_at is None or _aware(e.created_at) <= cutoff_utc)
            and (e.symbol == "MARKET" or security_class(e.symbol) != "other")]
    missing = sorted({e.symbol for e in rows if e.symbol not in names and e.symbol != "MARKET"})
    if missing:
        from forliosa.reports.marketcalc import names_for

        names = {**names, **names_for(db, missing)}
    for e in rows:
        name = names.get(e.symbol) or e.symbol.split(".")[0]
        who = f"{name}（{e.symbol.split('.')[0]}）" if e.symbol != "MARKET" else ""
        if e.type == "material_info":
            if not _served(e.source, "material_info", policy):
                continue
            rel = classify(e.title, e.detail or "", e.data, e.date)
            if rel is not None and rel.kind == "investor_conference" and start <= rel.date <= end:
                invited = "受邀" in e.title
                out.append(CalEvent(rel.date, f"{who}法說會", "investor_conference", f"{e.source}/material_info",
                                    symbol=e.symbol, url=e.url,
                                    fold="invited_conference" if invited and e.symbol not in top else None))
                continue
            if include_filings and start <= e.date <= end:
                t = _clock((e.data or {}).get("time"))
                out.append(CalEvent(e.date, f"{who}{e.title}"[:120], "material_info", f"{e.source}/material_info",
                                    t, t, symbol=e.symbol, url=e.url,
                                    fold=None if e.symbol in top else "other_filings"))
            continue
        if e.type == "disposition":
            last = e.end_date or e.date
            if last < start or e.date > end or not _served(e.source, "disposition", policy):
                continue
            first = max(e.date, start)
            out.append(CalEvent(first, f"{who}{e.title}（至 {last.month}/{last.day}）", "disposition",
                                f"{e.source}/disposition", symbol=e.symbol))
            continue
        if not start <= e.date <= end:
            continue
        if e.type == "ex_dividend":
            if not _served(e.source, "ex_dividend", policy):
                continue
            cls = classes.get(e.symbol) or security_class(e.symbol, name)
            fold = {"etf": "etf_ex", "bond_etf": "bond_etf_ex", "reit": "reit_ex"}.get(cls)
            out.append(CalEvent(e.date, f"{who}{e.title}", "ex_dividend", f"{e.source}/ex_dividend",
                                symbol=e.symbol, fold=fold))
        elif e.type == "shareholder_meeting" and _served(e.source, "shareholder_meeting", policy):
            out.append(CalEvent(e.date, f"{who}股東會", "shareholder_meeting", f"{e.source}/shareholder_meeting",
                                symbol=e.symbol))
        elif e.type == "attention" and _served(e.source, "attention", policy):
            out.append(CalEvent(e.date, f"{who}列為注意股票", "attention", f"{e.source}/attention", symbol=e.symbol,
                                fold=None if e.symbol in top else "other_filings"))
    # hand-kept tables: Taipei dates (macro by its own time zone, US earnings by bmo / amc)
    for m in db.scalars(select(MacroCalendarEvent).where(MacroCalendarEvent.event_date >= start - timedelta(days=1),
                                                         MacroCalendarEvent.event_date <= end)):
        if _aware(m.updated_at) > cutoff_utc:
            continue
        tp = to_taipei(m.event_date, m.local_time, m.tz)
        day = tp.date() if tp else m.event_date
        if not start <= day <= end:
            continue
        label = f"台北 {tp:%H:%M}" if tp else None
        out.append(CalEvent(day, m.title, "macro", "manual-calendar", f"{tp:%H:%M}" if tp else None, label,
                            sectors=list(m.sectors or []), url=m.official_url, note=m.note or ""))
    for u in db.scalars(select(UsEarningsDate).where(UsEarningsDate.report_date >= start - timedelta(days=1),
                                                     UsEarningsDate.report_date <= end)):
        if _aware(u.updated_at) > cutoff_utc:
            continue
        tp = earnings_taipei(u.report_date, u.timing, u.time_et)
        day = tp.date() if tp else u.report_date
        if not start <= day <= end:
            continue
        out.append(CalEvent(day, f"{u.company}（{u.symbol}）財報", "us_earnings", "manual-calendar",
                            f"{tp:%H:%M}" if tp else None, earnings_label(u.report_date, u.timing, u.time_et),
                            symbol=u.symbol, sectors=list(u.sectors or []), url=u.official_url, note=u.note or ""))
    for h in db.scalars(select(NyseHoliday).where(NyseHoliday.date >= start, NyseHoliday.date <= end)):
        if _aware(h.updated_at) > cutoff_utc:
            continue
        what = "休市" if h.kind == "closed" else f"提早收盤（美東 {h.close_time_et or '13:00'}）"
        out.append(CalEvent(h.date, f"美股 {h.date.month}/{h.date.day} {h.name.split('（')[0]}{what}", "us_holiday",
                            "manual-calendar", url=h.source_url))
    out.sort(key=lambda c: (c.date, c.time_taipei or "99:99", c.fold or "", c.kind, c.title))
    return out


def _aware(dt: datetime) -> datetime:
    from datetime import UTC

    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
