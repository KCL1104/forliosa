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
import re
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
    if (t := _hhmm(time_et)) is not None:  # 「9:30」 written as 09:30, the form :data:`CONVERTED` reads
        return f"美東 {md} {t:%H:%M}（台北 {tmd} {tp:%H:%M}）"
    return f"美東 {md} {_TIMING_TEXT.get(timing, '')}（台北 {tmd} {taipei_part(tp)}）"


# -- US local times in the AI text -> Taipei (the program converts, never the model) ------------------------------
# The writer is told to write a US-only time as 「美東 11/18 14:00」; :func:`us_times_to_taipei` also takes the forms a
# report's wording leads to (「11/18 美國時間下午 2:00」「美東時間 11/18 下午 2 點半」) and writes
# 「美東 11/18 14:00（台北 11/19 03:00）」, the form of :func:`earnings_label`.
# 「美國」 alone names the country (「美國 CPI 11/18 21:30」 can be a Taipei time from the calendar): only with 時間
_US_ZONE = r"(?:(?:美東|美國東部|紐約)(?:時間)?|美國時間)"
_US_MD = r"(?P<mo>\d{1,2})/(?P<d>\d{1,2})(?:\s*[（(][一二三四五六日][)）])?"
_US_CLOCK = (r"(?P<part>上午|下午|晚上|晚間|凌晨|清晨|早上|中午)?\s*(?P<h>\d{1,2})\s*"
             r"(?:[:：]\s*(?P<m>\d{2})|點\s*(?:(?P<m2>\d{1,2})\s*分|(?P<half>半))?)"
             r"(?!\d)(?!\s*[（(]\s*台北)(?P<trail>[ \t]*)")
_US_TIMES = (re.compile(_US_ZONE + r"\s*" + _US_MD + r"\s*" + _US_CLOCK),
             re.compile(_US_MD + r"\s*" + _US_ZONE + r"\s*" + _US_CLOCK))
# a US local time with a clock (any form) — what is left of one after the conversion is a problem for the validator
US_LOCAL_TIME = re.compile(_US_ZONE + r"[^，。；,;]{0,14}?(?<![\d/])\d{1,2}\s*(?:[:：]\s*\d{2}|點)")
CONVERTED = re.compile(r"美東\s*(\d{1,2})/(\d{1,2})\s*(\d{1,2}):(\d{2})\s*[（(]\s*台北\s*(\d{1,2})/(\d{1,2})\s*"
                       r"(\d{1,2}):(\d{2})\s*[)）]")


def _near_year(month: int, day: int, ref: date) -> date | None:
    best = None
    for y in (ref.year - 1, ref.year, ref.year + 1):
        try:
            d = date(y, month, day)
        except ValueError:
            continue
        if best is None or abs((d - ref).days) < abs((best - ref).days):
            best = d
    return best


def _us_clock(m: re.Match[str]) -> tuple[int, int] | None:
    h, part = int(m.group("h")), m.group("part") or ""
    mm = int(m.group("m") or m.group("m2") or (30 if m.group("half") else 0))
    if part in ("下午", "晚上", "晚間") and h < 12:
        h += 12
    elif part in ("上午", "凌晨", "清晨", "早上") and h == 12:
        h = 0
    elif part == "中午" and h < 11:
        h += 12
    return (h, mm) if 0 <= h <= 23 and 0 <= mm <= 59 else None


def us_time_to_taipei(us_day: date, hh: int, mm: int) -> datetime:
    return datetime.combine(us_day, time(hh, mm), NEW_YORK).astimezone(TAIPEI)


def us_times_to_taipei(text: str, ref: date) -> str:
    """Every US local time with a date in ``text`` written as 「美東 11/18 14:00（台北 11/19 03:00）」 (``ref``: the
    edition date, for the year). Text that already has the Taipei time, or a US time without a date, is left as it
    is."""
    def sub(m: re.Match[str]) -> str:
        day = _near_year(int(m.group("mo")), int(m.group("d")), ref)
        clock = _us_clock(m)
        if day is None or clock is None:
            return m.group(0)
        tp = us_time_to_taipei(day, *clock)
        end = m.group("trail") if m.end() < len(m.string) and m.string[m.end()].isascii() else ""
        return f"美東 {day.month}/{day.day} {clock[0]:02d}:{clock[1]:02d}（台北 {tp.month}/{tp.day} {tp:%H:%M}）{end}"

    for rx in _US_TIMES:
        text = rx.sub(sub, text)
    return text


def converted_spans(text: str, ref: date) -> list[tuple[int, int, int, int]]:
    """The 「美東 M/D HH:MM（台北 M/D HH:MM）」 passages of ``text`` whose Taipei part is the exact conversion of the US
    part: (start, end, start of the Taipei part, end of the Taipei part)."""
    out = []
    for m in CONVERTED.finditer(text):
        mo, d, hh, mi, tmo, td, thh, tmi = (int(x) for x in m.groups())
        day = _near_year(mo, d, ref)
        if day is None or hh > 23 or mi > 59:
            continue
        tp = us_time_to_taipei(day, hh, mi)
        if (tp.month, tp.day, tp.hour, tp.minute) == (tmo, td, thh, tmi):
            out.append((m.start(), m.end(), m.start(5), m.end(8)))
    return out


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
        out.append(CalEvent(h.date, nyse_title(h.date, h.name, h.kind, h.close_time_et), "us_holiday",
                            "manual-calendar", url=h.source_url))
    out.sort(key=lambda c: (c.date, c.time_taipei or "99:99", c.fold or "", c.kind, c.title))
    return out


# A holiday name the writer copies is checked like its own words: no time word (「感恩節翌日」 reads 「感恩節後一天」)
_NAME_TIME_WORDS = {"翌日": "後一天", "次日": "後一天", "隔日": "後一天", "隔天": "後一天"}


def _holiday_name(name: str) -> str:
    from forliosa.reports.prompts import FORBIDDEN_WORDS, TIME_WORDS

    out = name.split("（")[0].strip()
    for word, plain in _NAME_TIME_WORDS.items():
        out = out.replace(word, plain)
    if any(w in out for w in (*TIME_WORDS, *FORBIDDEN_WORDS)) or re.search(r"(?:週|周|星期|禮拜)[一二三四五六日天]", out):
        return ""  # an admin's name that would fail the checks: the date and the kind say enough
    return out


def nyse_title(d: date, name: str, kind: str, close_time_et: str | None) -> str:
    """The calendar title of a NYSE closure or early close. An early close carries its time the way the AI text
    must write a US time: 「美股 11/27 感恩節後一天提早於美東 11/27 13:00（台北 11/28 02:00）收盤」 (the validator
    reads it as converted, so a sentence copying the title passes)."""
    md = f"{d.month}/{d.day}"
    plain = _holiday_name(name or "")
    if kind == "closed":
        return f"美股 {md} {plain}休市"
    t = _hhmm(close_time_et) or time(13, 0)
    tp = us_time_to_taipei(d, t.hour, t.minute)
    return f"美股 {md} {plain}提早於美東 {md} {t:%H:%M}（台北 {tp.month}/{tp.day} {tp:%H:%M}）收盤"


def _aware(dt: datetime) -> datetime:
    from datetime import UTC

    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
