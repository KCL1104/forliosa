"""When each Taiwan market's close comes in, and getting it in sooner (product owner 2026-11-16).

Measured publication times (2026-11-13/16; the same-day-close research memo):

* TWSE's data.gov.tw download links on www.twse.com.tw (個股日成交資訊 11549, 大盤統計 11555): the session's close
  about 13:50 (TWSE's own statement; seen at 15:00 on 2026-11-16 with today's date in every row).
* shioaji-data's ``v1/tw/market/daily.json`` (both markets, close only): 20:22–23:39 the same evening on 16 of 19
  sessions (10/15–11/13), 00:05–01:29 on the other 3.
* The OpenAPIs (forliosa.archive close watch, every 15 minutes): TPEx per-stock closes about 23:30 the same night,
  TWSE in its nightly batch 05:20–05:28 the next morning.

So, fastest first:

1. :class:`TwseSameDay` (``TWSE_OPENDATA_CLOSE``, default on) — the narrow exception in CLAUDE.md: only the two exact
   URLs (``marketdata/http.py`` ALLOWED_EXACT_URLS), no date parameters, trading days from 13:45 at most every 10
   minutes (the time of the last request is kept in ``dataset_status``, so a restart does not ask sooner), until the
   session is stored; any refusal (a redirect, 403, 429 …) stops it for the day, also kept in ``dataset_status``. The
   data date comes from the file (every row's 日期 and the file name), never the clock. Rows: source
   ``twse-opendata`` — official data, so the ledger's value and performance read it; the OpenAPI replaces it.
2. :class:`EveningCloses` (``SHIOAJI_EVENING_CLOSE``, default on) — from 20:30 every 15 minutes until 02:00, for each
   market whose session is not stored yet: a conditional request for the first bytes of daily.json (its ``as_of`` per
   market), the whole file only once a needed market has turned to the session. Close-only rows, source
   ``shioaji-data``, ``dataset_status`` ``shioaji-data/interim_twse`` / ``…_tpex``: interim — any official row replaces
   them and they never replace one.
3. The OpenAPIs (unchanged): final.

:func:`tw_closes` answers ``GET /meta/market-status`` ``tw.closes``: per market the session whose close is due, whether
it is stored, the newest stored date, whether that is interim, and when the next arrival is expected
(:data:`WINDOWS`, from what is switched on).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.archive import OFFICIAL_CLOSE_SOURCES, Archiver, upsert
from forliosa.datapolicy import Policy
from forliosa.marketdata import twse_opendata as tod
from forliosa.marketdata.base import ProviderUnavailable, code_of_symbol, market_of_symbol
from forliosa.marketdata.http import HttpFetcher, HttpStatusError
from forliosa.marketdata.shioaji_data import parse_daily
from forliosa.models import DatasetStatus, PriceDaily
from forliosa.timeutil import MARKET_CLOSE, TAIPEI, is_tw_trading_day, last_tw_trading_day, now_taipei

log = logging.getLogger("forliosa.closes")

MARKETS = ("TWSE", "TPEX")
# dataset_status rows that say a market's session is stored (official: final or same-day file; interim: shioaji-data)
OFFICIAL_KEYS = {"TWSE": ("twse-openapi/price", tod.PRICE_DATASET), "TPEX": ("tpex-openapi/price",)}
INTERIM_KEYS = {"TWSE": "shioaji-data/interim_twse", "TPEX": "shioaji-data/interim_tpex"}
TWSE_INDEX_KEYS = ("twse-openapi/index", tod.INDEX_DATASET)
TWSE_POLL_KEY = "twse-opendata/poll"  # fetched_at: the last request to www.twse.com.tw; data_date: the date it held
TWSE_REFUSED_KEY = "twse-opendata/refused"  # data_date: the day TWSE refused; rows: the HTTP status
STATUS_KEYS = (*OFFICIAL_KEYS["TWSE"], *OFFICIAL_KEYS["TPEX"], *INTERIM_KEYS.values(), *TWSE_INDEX_KEYS,
               TWSE_POLL_KEY, TWSE_REFUSED_KEY)

TWSE_POLL_FROM = time(13, 45)
# Last request of the day: the file is normally there by ~13:50; later on, the evening release and the next morning's
# OpenAPI cover the session (and nothing keeps knocking on www.twse.com.tw into the night).
TWSE_POLL_UNTIL = time(18, 0)
TWSE_POLL_SECONDS = 10 * 60
EVENING_FROM = time(20, 30)
EVENING_UNTIL = time(2, 0)  # the next calendar day
EVENING_SECONDS = 15 * 60
EVENING_PROBE_BYTES = 512  # daily.json starts with {"as_of":{"tpex":"YYYY-MM-DD","twse":"YYYY-MM-DD"},…
SAME_AS_BEFORE_MIN = 50  # this many traded symbols all equal to the previous session's: a stale file, not stored
_AS_OF = re.compile(rb'"as_of"\s*:\s*\{([^}]*)\}')


@dataclass(frozen=True)
class Window:
    """When a route usually delivers a session's close: ``days`` calendar days after the session, ``start``–``end``
    Taipei (the publication time measured above plus our own polling delay)."""

    route: str  # twse-opendata | shioaji-data | openapi
    days: int
    start: time
    end: time


# Per market, in order. Overlapping windows of routes that are switched on are merged; once a window has passed
# without the close, the next one is the expectation; after the last one nothing is promised (null).
WINDOWS: dict[str, tuple[Window, ...]] = {
    "TWSE": (
        Window("twse-opendata", 0, time(14, 0), time(14, 30)),  # ~13:50, polled every 10 minutes from 13:45
        Window("shioaji-data", 0, time(20, 30), time(23, 45)),  # 16 of 19 releases 20:22–23:39
        Window("shioaji-data", 1, time(0, 0), time(1, 30)),  # the other 3: 00:05–01:29
        Window("openapi", 1, time(5, 20), time(5, 45)),  # nightly batch 05:20–05:28, close watch every 15 minutes
    ),
    "TPEX": (
        Window("shioaji-data", 0, time(20, 30), time(23, 45)),
        Window("openapi", 0, time(23, 15), time(23, 45)),  # about 23:30, close watch every 15 minutes
        Window("shioaji-data", 1, time(0, 0), time(1, 30)),
    ),
    # 加權指數 and the other TWSE indices (tw.closes TWSE ``index``): only TWSE's own files carry them (shioaji-data
    # has no index), so when the afternoon MI_INDEX is refused the next one is the morning batch (2026-11-16 review:
    # STOCK_DAY_ALL came in at 15:46 and MI_INDEX answered 307 three seconds later).
    "TWSE_INDEX": (
        Window("twse-opendata", 0, time(14, 0), time(14, 30)),
        Window("openapi", 1, time(5, 20), time(5, 45)),
    ),
}
# The afternoon window ends at 14:30 although the file is polled until 18:00 (TWSE_POLL_UNTIL): it is normally in by
# ~13:50, and one not in by 14:30 is late or refused — the evening expectation is the honest one; a later afternoon
# arrival simply comes sooner than said (2026-11-16 review, kept on purpose).


def due_session(now: datetime) -> date:
    """The latest trading day whose close (13:30 Taipei) has passed at ``now``: today from 13:30 on a trading day."""
    at = now.astimezone(TAIPEI)
    d = at.date()
    if not (is_tw_trading_day(d) and at.time() >= MARKET_CLOSE):
        d -= timedelta(days=1)
    return last_tw_trading_day(d)


def _status(db: Session, keys: tuple[str, ...] = STATUS_KEYS) -> dict[str, DatasetStatus]:
    return {r.key: r for r in db.scalars(select(DatasetStatus).where(DatasetStatus.key.in_(keys)))}


def _newest(status: dict[str, DatasetStatus], keys: tuple[str, ...] | list[str]) -> date | None:
    return max((d for d in (status[k].data_date if k in status else None for k in keys) if d is not None),
               default=None)


def official_close_dates(db: Session) -> dict[str, date | None]:
    """Newest session with official closes stored, per market (the OpenAPIs, or TWSE's same-day file; never the
    interim evening closes). The daily briefing and the market page's rankings wait for these."""
    status = _status(db, (*OFFICIAL_KEYS["TWSE"], *OFFICIAL_KEYS["TPEX"]))
    return {m: _newest(status, OFFICIAL_KEYS[m]) for m in MARKETS}


def routes_on(settings: Any, refused: date | None = None, session: date | None = None) -> set[str]:
    """Routes switched on (the OpenAPIs always are). The same-day TWSE file is off for a session it was refused on."""
    on = {"openapi"}
    if getattr(settings, "twse_opendata_close", True) and not (refused is not None and refused == session):
        on.add("twse-opendata")
    if getattr(settings, "shioaji_evening_close", True):
        on.add("shioaji-data")
    return on


def expected_window(market: str, session: date, now: datetime, routes: set[str]) -> tuple[datetime, datetime] | None:
    """The window the session's close is next expected in: the first (merged) window of a switched-on route that has
    not ended at ``now`` — the current one, or the next after one that passed without the close. ``None`` once every
    window has passed."""
    spans = sorted((datetime.combine(session + timedelta(days=w.days), w.start, TAIPEI),
                    datetime.combine(session + timedelta(days=w.days), w.end, TAIPEI))
                   for w in WINDOWS[market] if w.route in routes)
    merged: list[list[datetime]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    at = now.astimezone(TAIPEI)
    return next(((s, e) for s, e in merged if at < e), None)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(TAIPEI).isoformat(timespec="seconds") if dt is not None else None


def _period(h: int) -> str:
    return ("半夜" if h < 3 else "凌晨" if h < 5 else "清晨" if h < 7 else "早上" if h < 12 else "中午" if h < 13
            else "下午" if h < 18 else "晚上")


def _clock12(t: datetime) -> str:
    return f"{t.hour % 12 or 12}:{t.minute:02d}"


def _when(t: datetime, today: date) -> str:
    p = _period(t.hour)
    if t.date() == today:
        return "今晚" if p == "晚上" else p
    if t.date() == today + timedelta(days=1):
        return "明晚" if p == "晚上" else p if p in ("半夜", "凌晨") else f"明天{p}"
    return f"{t.month}/{t.day} {p}"


def window_text(start: datetime, end: datetime, now: datetime) -> str | None:
    """An expected window in the app's words (apps/web/src/lib/as-of.ts ``expectedWindow``): 「下午 2:00–2:30」
    「今晚 8:30–11:45」「明天清晨 5:20–5:45」; inside the window 「下午 2:30 前」; ``None`` once it has passed. The AI
    page context and tools use it so the model writes the times the way the screen does (12-hour, with the part of
    the day)."""
    at = now.astimezone(TAIPEI)
    start, end, today = start.astimezone(TAIPEI), end.astimezone(TAIPEI), at.date()
    if end < at:
        return None
    if start <= at:
        return f"{_when(end, today)} {_clock12(end)} 前"
    if start.date() == end.date() and _period(start.hour) == _period(end.hour):
        return f"{_when(start, today)} {_clock12(start)}–{_clock12(end)}"
    return f"{_when(start, today)} {_clock12(start)} 到{_when(end, today)} {_clock12(end)}"


def expect_update(text: str) -> str:
    """「預計下午 2:00–2:30 更新」「預計下午 2:30 前更新」: a space between a number and the next word (as on
    screen)."""
    return f"預計{text}{' ' if text[-1:].isdigit() else ''}更新"


def _expected(window: tuple[datetime, datetime] | None) -> dict[str, str | None]:
    return {"expected_from": _iso(window[0]) if window else None, "expected_to": _iso(window[1]) if window else None}


def tw_closes(db: Session, now: datetime | None = None, settings: Any = None) -> list[dict[str, Any]]:
    """``tw.closes`` of ``GET /meta/market-status`` (one small query of ``dataset_status``).

    ``expected_*`` while the session is stored only as the interim evening close (``interim``): the window of the
    official file — the evening release has no ETFs (and no open / high / low / volume), so an ETF of that market still
    waits for it (2026-11-16 review). TWSE's entry also carries ``index`` (加權指數 and the other TWSE indices: same
    fields, from TWSE's own files only)."""
    if settings is None:
        from forliosa.config import get_settings

        settings = get_settings()
    at = (now or now_taipei()).astimezone(TAIPEI)
    session = due_session(at)
    status = _status(db)
    refused = status[TWSE_REFUSED_KEY].data_date if TWSE_REFUSED_KEY in status else None
    routes = routes_on(settings, refused, session)
    out = []
    for market in MARKETS:
        official = _newest(status, OFFICIAL_KEYS[market])
        interim_day = _newest(status, (INTERIM_KEYS[market],))
        latest = max((d for d in (official, interim_day) if d is not None), default=None)
        stored = latest is not None and latest >= session
        interim = interim_day is not None and (official is None or interim_day > official)
        if not stored:
            window = expected_window(market, session, at, routes)
        elif interim:
            window = expected_window(market, session, at, routes - {"shioaji-data"})
        else:
            window = None
        entry: dict[str, Any] = {
            "market": market, "session": session.isoformat(), "stored": stored,
            "latest": latest.isoformat() if latest else None, "interim": interim, **_expected(window),
        }
        entry["index"] = None
        if market == "TWSE":
            index_latest = _newest(status, TWSE_INDEX_KEYS)
            index_stored = index_latest is not None and index_latest >= session
            entry["index"] = {
                "stored": index_stored, "latest": index_latest.isoformat() if index_latest else None,
                **_expected(None if index_stored else expected_window("TWSE_INDEX", session, at, routes)),
            }
        out.append(entry)
    return out


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=TAIPEI)


def _mark(db: Session, key: str, data_date: date | None, rows: int, at: datetime) -> None:
    upsert(db, DatasetStatus, [{"key": key, "data_date": data_date, "rows": rows, "fetched_at": at}], ["key"])


# -- 1. TWSE's same-day download files --------------------------------------------------------------------------------
def twse_poll_day(now: datetime) -> date | None:
    """The session the same-day TWSE file is polled for at ``now``: today, on a trading day from 13:45 to 18:00."""
    at = now.astimezone(TAIPEI)
    if is_tw_trading_day(at.date()) and TWSE_POLL_FROM <= at.time() < TWSE_POLL_UNTIL:
        return at.date()
    return None


def twse_fetcher() -> HttpFetcher:
    """No retries: one request per URL per poll, at most every 10 minutes (the 3 s TWSE interval still applies)."""
    return HttpFetcher(timeout=30, retries=0)


@dataclass
class TwsePoll:
    day: date | None = None  # the session polled for
    asked: int = 0  # requests sent to www.twse.com.tw
    found: date | None = None  # the date the price file carried
    prices: int = 0  # rows stored
    indices: int = 0
    refused: int | None = None  # the HTTP status that stopped the day
    skipped: str | None = None  # why nothing was asked: off-hours | refused | stored | too-soon


class TwseSameDay:
    """One poll of the two download links (see the module docstring)."""

    def __init__(self, fetcher: HttpFetcher, policy: Policy = "commercial", now_fn=now_taipei):
        self.fetcher = fetcher
        self.policy = policy
        self.now_fn = now_fn

    def poll(self, db: Session) -> TwsePoll:
        now = self.now_fn().astimezone(TAIPEI)
        day = twse_poll_day(now)
        res = TwsePoll(day=day)
        if day is None:
            res.skipped = "off-hours"
            return res
        status = _status(db)
        if TWSE_REFUSED_KEY in status and status[TWSE_REFUSED_KEY].data_date == day:
            res.skipped = "refused"
            return res
        prices_in = (_newest(status, OFFICIAL_KEYS["TWSE"]) or date.min) >= day
        index_in = (_newest(status, TWSE_INDEX_KEYS) or date.min) >= day
        if prices_in and index_in:
            res.skipped = "stored"
            return res
        last = _aware(status[TWSE_POLL_KEY].fetched_at) if TWSE_POLL_KEY in status else None
        if last is not None and now - last < timedelta(seconds=TWSE_POLL_SECONDS):
            res.skipped = "too-soon"
            return res
        # The time of the request is written before it is sent: a crash or restart mid-request still counts as one.
        _mark(db, TWSE_POLL_KEY, status[TWSE_POLL_KEY].data_date if TWSE_POLL_KEY in status else None, 0, now)
        archiver = Archiver(db, self.fetcher, self.policy, now_fn=self.now_fn)
        try:
            if not prices_in:
                rows, found = self._download(tod.STOCK_DAY_ALL_URL, tod.stock_day_all_rows, "Date", res)
                res.found = found
                _mark(db, TWSE_POLL_KEY, found, len(rows), now)
                if found != day:
                    if found > day:
                        log.warning("twse same-day file: dated %s on %s, not stored", found, day)
                    return res  # not published yet: the next poll asks again
                self._check_not_previous(db, rows, day, _newest(status, OFFICIAL_KEYS["TWSE"]))
                res.prices = archiver.store_twse_opendata_prices(rows)
                log.info("twse same-day file: %d closes of %s stored", res.prices, day)
            if not index_in:
                rows, found = self._download(tod.MI_INDEX_URL, tod.mi_index_rows, "日期", res)
                if found == day:
                    res.indices = archiver.store_twse_opendata_indices(rows)
                    log.info("twse same-day file: %d index closes of %s stored", res.indices, day)
        except HttpStatusError as exc:
            # a redirect, 403, 429 … — or a block page sent with 200 (tod.blocked): stop for the day
            res.refused = exc.status
            _mark(db, TWSE_REFUSED_KEY, day, exc.status, now)
            log.warning("twse same-day file: %s (X-Cache %s); no more requests to www.twse.com.tw today", exc,
                        exc.headers.get("x-cache") if exc.headers is not None else None)
        except ProviderUnavailable as exc:  # unreachable, a 5xx, a changed format: the next poll tries again
            db.rollback()
            log.warning("twse same-day file not stored: %s", exc)
        return res

    def _download(self, url: str, parse, date_key: str, res: TwsePoll) -> tuple[list[dict[str, Any]], date]:
        res.asked += 1
        raw, headers = self.fetcher.fetch(url, headers=tod.ACCEPT_CSV)
        # kept in the log to see how often the CDN serves the file and how often the origin refuses (2026-11-16: a 307
        # came with X-Cache EXPIRED, the 200s with HIT)
        log.info("twse same-day file %s: HTTP 200, X-Cache %s", url.rsplit("/", 1)[-1], headers.get("x-cache"))
        if tod.blocked(raw, headers.get("content-type")):
            raise HttpStatusError(f"www.twse.com.tw 回了網頁（{headers.get('content-type')}），不是 CSV：當成被擋", 200,
                                  headers)
        rows = parse(raw)
        return rows, tod.file_date(rows, date_key, headers.get("content-disposition"))

    @staticmethod
    def _check_not_previous(db: Session, rows: list[dict[str, Any]], day: date, previous: date | None) -> None:
        """A file whose every traded close equals the previous stored session's is that session relabelled (a stale
        copy), not ``day``: raise, store nothing. (No real session leaves 50+ traded stocks all unchanged.) Closes only:
        the stored previous session has the next morning's final volume, which an afternoon copy may lack."""
        from forliosa.marketdata.twse import parse_stock_day_all

        if previous is None or previous >= day:
            return
        quotes = {s: q.price for s, q in parse_stock_day_all(rows).items() if q.volume}
        if len(quotes) < SAME_AS_BEFORE_MIN:
            return
        before = dict(db.execute(select(PriceDaily.symbol, PriceDaily.close)
                                 .where(PriceDaily.date == previous, PriceDaily.symbol.in_(list(quotes))))
                      .tuples().all())
        common = [s for s in quotes if s in before]
        if len(common) >= SAME_AS_BEFORE_MIN and all(quotes[s] == before[s] for s in common):
            raise ProviderUnavailable(f"證交所下載檔標示 {day}，但收盤價和 {previous} 完全相同")


# -- 2. shioaji-data's evening release (interim) ----------------------------------------------------------------------
def evening_day(now: datetime) -> date | None:
    """The session the evening release is awaited for: today from 20:30 on a trading day, and until 02:00 after it."""
    at = now.astimezone(TAIPEI)
    if at.time() >= EVENING_FROM:
        return at.date() if is_tw_trading_day(at.date()) else None
    if at.time() < EVENING_UNTIL:
        yesterday = at.date() - timedelta(days=1)
        return yesterday if is_tw_trading_day(yesterday) else None
    return None


def first_as_of(head: bytes) -> dict[str, date]:
    """``{"as_of":{"tpex":"2026-11-13","twse":"2026-11-13"},…`` -> ``{"TPEX": …, "TWSE": …}`` (what parses)."""
    found = _AS_OF.search(head)
    if not found:
        return {}
    try:
        raw = json.loads(b"{" + found.group(1) + b"}")
    except ValueError:
        return {}
    out = {}
    for key, value in raw.items() if isinstance(raw, dict) else ():
        try:
            out[str(key).upper()] = date.fromisoformat(str(value))
        except ValueError:
            continue
    return out


@dataclass
class EveningPoll:
    day: date | None = None
    asked: int = 0
    stored: dict[str, int] | None = None  # market -> rows stored
    skipped: str | None = None


class EveningCloses:
    """shioaji-data's evening release as an interim close. The validators of the version last seen are kept in memory
    only to make the next probe a 304; what is stored is read from ``dataset_status`` every time."""

    PATH = "v1/tw/market/daily.json"

    def __init__(self, fetcher: HttpFetcher, base_url: str, policy: Policy = "commercial", now_fn=now_taipei):
        self.fetcher = fetcher
        self.url = f"{base_url.rstrip('/')}/{self.PATH}"
        self.policy = policy
        self.now_fn = now_fn
        self._seen: tuple[str | None, str | None, dict[str, date]] | None = None

    def poll(self, db: Session) -> EveningPoll:
        now = self.now_fn().astimezone(TAIPEI)
        day = evening_day(now)
        res = EveningPoll(day=day)
        if day is None:
            res.skipped = "off-hours"
            return res
        status = _status(db)
        needed = [m for m in MARKETS
                  if (_newest(status, (*OFFICIAL_KEYS[m], INTERIM_KEYS[m])) or date.min) < day]
        if not needed:
            res.skipped = "stored"
            return res
        etag, modified, known = self._seen or (None, None, {})
        res.asked += 1
        probe = self.fetcher.probe(self.url, etag=etag, last_modified=modified, first_bytes=EVENING_PROBE_BYTES)
        as_of = known if not probe.changed and known else first_as_of(probe.head)
        self._seen = (probe.etag, probe.last_modified, as_of) if as_of else None
        if not as_of:
            log.warning("evening closes: no as_of in the first bytes of %s", self.url)
        ready = [m for m in needed if as_of.get(m) == day]
        if not ready:
            return res
        res.asked += 1
        doc = json.loads(self.fetcher.get_bytes(self.url))
        parsed = parse_daily(doc)
        symbols = self._symbols(db, day)
        archiver = Archiver(db, self.fetcher, self.policy, now_fn=self.now_fn)
        res.stored = {}
        for market in ready:
            closes: dict[str, Decimal] = {}
            for code, q in parsed.items():
                sym = symbols.get(code)
                if sym is not None and market_of_symbol(sym) == market and q["date"] == day:
                    closes[sym] = q["close"]
            if closes:
                res.stored[market] = archiver.store_interim_closes(closes, day, INTERIM_KEYS[market])
                log.info("evening closes: %d interim %s closes of %s stored", res.stored[market], market, day)
        return res

    @staticmethod
    def _symbols(db: Session, day: date) -> dict[str, str]:
        """Code -> symbol of every Taiwan security with an official close in the three weeks before ``day``: its
        suffix says the market (daily.json does not), and an unknown code is never guessed."""
        out: dict[str, str] = {}
        for sym in db.scalars(select(PriceDaily.symbol).where(
                PriceDaily.date < day, PriceDaily.date >= day - timedelta(days=21),
                PriceDaily.source.in_(OFFICIAL_CLOSE_SOURCES)).distinct()):
            if market_of_symbol(sym) in MARKETS:
                out.setdefault(code_of_symbol(sym), sym)
        return out
