"""When each edition happens: pure functions of the date and the clock (Taipei), no database.

An :class:`Edition` carries the edition date, the period it covers, the US sessions it reports, and every time the
pipeline acts on (contract §5.2):

* 盤前重點 (``premarket``) on Taiwan trading day D: gather 06:15, data 06:55, write 07:00 (at the latest 07:05), push
  07:30 (or when the AI edition comes, until 08:15; then the data edition), closed 08:40. It reports the US sessions
  since the previous Taiwan session (``us_sessions``: after a long holiday, every one of them).
* 盤後重點 (``close``) on trading day D: data 14:10 (rebuilt every 10 minutes until 15:40; skipped at 15:00 when
  no close is in), gather 15:40, write 15:50, push 16:00 (until 17:30), closed 17:30, tables 23:45 and 06:40 the
  next day.
* 市場週報 (``weekly``) on Sunday S: data and gather 16:30, write 16:50, push 18:00 (until 21:00), closed 21:00. It
  reviews Monday S−6 to Friday S−2 and lists Monday S+1 to Friday S+5.

Times are Taipei; ``cutoff`` is the data cut-off of the AI edition (what ``timing.available_at`` is checked
against); the data edition built earlier uses its own build time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from forliosa.timeutil import (
    TAIPEI,
    is_tw_trading_day,
    last_tw_trading_day,
    market_close_dt,
    us_trading_days,
)

KINDS = ("premarket", "close", "weekly")
KIND_LABELS = {"premarket": "盤前重點", "close": "盤後重點", "weekly": "市場週報"}
WEEKDAYS = "一二三四五六日"
# A first premarket after this many weekday closures in a row gets more searches (contract §5.2, §8.2)
LONG_HOLIDAY_WEEKDAYS = 3


def at(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm), TAIPEI)


def md(d: date) -> str:
    """``11/18``."""
    return f"{d.month}/{d.day}"


def md_wd(d: date) -> str:
    """``11/18（三）``."""
    return f"{d.month}/{d.day}（{WEEKDAYS[d.weekday()]}）"


def span(start: date, end: date) -> str:
    """``11/16–11/20``."""
    return f"{md(start)}–{md(end)}"


@dataclass(frozen=True)
class Edition:
    kind: str
    edition_date: date
    period: tuple[date, date]
    next_period: tuple[date, date] | None
    prev_session: date | None  # premarket: the Taiwan session before D (its evening data, its close report)
    us_sessions: tuple[date, ...]  # US sessions the edition reports (premarket: since the previous Taiwan session)
    long_holiday: bool  # premarket after ≥3 weekday closures: more searches
    gather_at: datetime
    data_at: datetime
    write_at: datetime
    write_latest: datetime  # start writing by then even if the gathering is still running
    cutoff: datetime
    publish_target: datetime
    push_at: datetime
    push_fallback_at: datetime  # no AI edition by then: push the data edition
    close_at: datetime  # AI results finishing later are dropped
    web_from: datetime
    web_to: datetime
    tables_at: tuple[datetime, ...] = field(default_factory=tuple)  # close: 23:45 and 06:40 the next day
    skip_check_at: datetime | None = None  # close: no session data by then = no edition (a typhoon day)

    @property
    def label(self) -> str:
        """``11/18（三）``; a weekly ``11/16–11/20 回顧``."""
        if self.kind == "weekly":
            return f"{span(*self.period)} 回顧"
        return md_wd(self.edition_date)

    @property
    def kind_label(self) -> str:
        return KIND_LABELS[self.kind]


def _weekday_closures(prev: date, d: date) -> int:
    """Weekdays strictly between two Taiwan sessions (holidays, a typhoon day)."""
    n, x = 0, prev + timedelta(days=1)
    while x < d:
        n += x.weekday() < 5
        x += timedelta(days=1)
    return n


def edition_on(kind: str, d: date) -> Edition | None:
    """The edition of ``kind`` dated ``d``: ``None`` when there is none (a day the Taiwan market is closed for the
    daily ones; any day but Sunday for the weekly)."""
    if kind not in KINDS:
        raise ValueError(f"unknown report kind {kind!r}")
    if kind == "weekly":
        if d.weekday() != 6:
            return None
        start, end = d - timedelta(days=6), d - timedelta(days=2)
        nxt = (d + timedelta(days=1), d + timedelta(days=5))
        return Edition(kind, d, (start, end), nxt, None, tuple(us_trading_days(start, end)), False,
                       gather_at=at(d, 16, 30), data_at=at(d, 16, 30), write_at=at(d, 16, 50),
                       write_latest=at(d, 16, 50), cutoff=at(d, 16, 30), publish_target=at(d, 18),
                       push_at=at(d, 18), push_fallback_at=at(d, 21), close_at=at(d, 21),
                       web_from=at(d - timedelta(days=8), 0), web_to=at(d, 16, 50))
    if not is_tw_trading_day(d):
        return None
    if kind == "premarket":
        prev = last_tw_trading_day(d - timedelta(days=1))
        sessions = tuple(us_trading_days(prev, d - timedelta(days=1)))
        return Edition(kind, d, (d, d), None, prev, sessions,
                       _weekday_closures(prev, d) >= LONG_HOLIDAY_WEEKDAYS,
                       gather_at=at(d, 6, 15), data_at=at(d, 6, 55), write_at=at(d, 7), write_latest=at(d, 7, 5),
                       cutoff=at(d, 6, 55), publish_target=at(d, 7, 25), push_at=at(d, 7, 30),
                       push_fallback_at=at(d, 8, 15), close_at=at(d, 8, 40),
                       web_from=market_close_dt(prev), web_to=at(d, 7))
    return Edition(kind, d, (d, d), None, last_tw_trading_day(d - timedelta(days=1)), (), False,
                   gather_at=at(d, 15, 40), data_at=at(d, 14, 10), write_at=at(d, 15, 50),
                   write_latest=at(d, 15, 50), cutoff=at(d, 15, 40), publish_target=at(d, 15, 55),
                   push_at=at(d, 16), push_fallback_at=at(d, 17, 30), close_at=at(d, 17, 30),
                   web_from=at(d, 8), web_to=at(d, 15, 50),
                   tables_at=(at(d, 23, 45), at(d + timedelta(days=1), 6, 40)),
                   skip_check_at=at(d, 15))


def edition_for(kind: str, now: datetime) -> Edition | None:
    """Today's edition of ``kind`` (Taipei date of ``now``), or ``None`` when there is none today. The close edition's
    06:40 table run belongs to yesterday's edition: callers that need it ask :func:`edition_on` for that date."""
    return edition_on(kind, now.astimezone(TAIPEI).date())
