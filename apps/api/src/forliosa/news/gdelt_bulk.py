"""GDELT's 15-minute bulk files for Taiwan stocks (產品負責人 2026-11-16, decision 7: 照建議), US stocks and the US
market (2026-11-17, option A).

Why
---
The DOC 2.0 API (:class:`forliosa.news.sources.GdeltSource`) is asked once per symbol, at most once every 5 s per IP,
and answers 429 from shared outbound IPs for hours at a time (measured 2026-11-16: 429 on the first request); it also
takes English queries only, against machine translations. GDELT publishes every article it saw in files of 15
minutes (Global Knowledge Graph, GKG 2.1). One download serves every tracked symbol, and the translingual stream keeps
each non-English article's own page title (``V2EXTRASXML`` ``<PAGE_TITLE>``, HTML entities): a Chinese headline is
matched against 台積電 directly.

Feeds (``NEWS_GDELT_BULK_FEEDS``)
--------------------------------
* ``translation`` — index ``lastupdate-translation.txt`` -> ``<YYYYMMDDHHMMSS>.translation.gkg.csv.zip``. Measured
  2026-11-16 (five files, 09:15–20:30 Taipei): 3.8–13.3 MB zipped (42 MB unzipped at the largest), 1.4k–3.5k articles
  per file, about 65 of them from Taiwanese sites (自由時報, 蕃薯藤, 中央社, 三立, 聯合新聞網, 新頭殼, 風傳媒, iThome),
  titles in Chinese. 鉅亨, 經濟日報 (money.udn.com), 工商時報 and MoneyDJ did not appear in those files.
* ``english`` — index ``lastupdate.txt`` -> ``<ts>.gkg.csv.zip``: 1.9–4.5 MB zipped, 700–1,000 articles; Taiwan's
  English sites (Taipei Times, Focus Taiwan) are a handful a day.

Both together are about 1 GB a day of downloads (inbound; no API key, no fee) and about a second of CPU per file. The
worker reads them in its news run (every ``NEWS_REFRESH_MINUTES``): the files published since the last one read, at
most ``NEWS_GDELT_BULK_MAX_FILES`` per feed (older ones are skipped after a long outage and the gap is logged).

Terms and politeness
--------------------
GDELT's data is free for "unlimited and unrestricted use for any academic, commercial, or governmental use of any kind
without fee", with a citation — the same as the DOC API: the rows are stored with source ``gdelt`` and shown with the
same GDELT attribution. The files live in GDELT's public Google Cloud Storage bucket ``data.gdeltproject.org``; the
index links them as ``http://data.gdeltproject.org/gdeltv2/…`` and we read the same objects over HTTPS at
``https://storage.googleapis.com/data.gdeltproject.org/gdeltv2/`` (:data:`BASE_URL`, the only prefix this fetcher may
ask). One request at a time, ≥ 2 s apart, an honest User-Agent, no retry after a refusal: a 403 / 429 pauses that feed
(15 minutes, doubling up to 4 hours), like every other news source. Nothing else on GDELT's sites is fetched, and the
news sites themselves are never fetched.

Matching
--------
* **Taiwan stocks**: only rows from Taiwanese sites (:func:`forliosa.news.outlets.is_taiwan_outlet`: a ``.tw`` host or
  ``TAIWAN_DOMAINS``, standing in for the DOC API's ``sourcecountry:taiwan``), both feeds. A headline must name the
  company in its title (:func:`forliosa.news.normalize.is_relevant`, the rule every source follows; since 2026-11-17
  :mod:`forliosa.news.tw_match`: the code only with stock context, the official name, a short or everyday name only
  with the code, a finance word or a finance page, never inside a longer word or listed name — the page's URL and
  title as published are passed for the finance-page test).
* **US stocks and the US market** (``us``: symbol -> a test of the title and URL, :mod:`forliosa.news.us_match`):
  only the ``english`` feed, only pages of US and UK news outlets (:func:`forliosa.news.outlets.is_us_outlet`,
  standing in for the DOC API's ``(sourcecountry:US OR sourcecountry:UK) sourcelang:english``; the files carry no
  source country). Measured 2026-11-17 (48 files, 12 h, 3.8–7.3 MB each): 905–1,804 articles per file (1,355 on
  average), 23 news pages of those outlets on average (2 in the US night, up to 49).

State: ``news_fetch_state`` rows ``source = "gdelt_bulk"``, ``symbol = "@translation"`` / ``"@english"``;
``last_success_at`` is the time slot of the newest file read (UTC), ``items`` the matches in the last run. Taiwan
stocks lean on the ``translation`` feed (:data:`PRIMARY_FEED`), US stocks and the US market on ``english``
(:data:`US_FEED`): each is current (its DOC API not asked) while its feed's newest file read is within :data:`FRESH`.
"""

from __future__ import annotations

import html
import io
import logging
import re
import zipfile
import zlib
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from forliosa.marketdata.http import HttpFetcher, HttpStatusError, RateLimiter
from forliosa.models import NewsFetchState
from forliosa.news.normalize import clean_title, is_relevant
from forliosa.news.outlets import is_taiwan_outlet, is_us_outlet, outlet_name, us_outlet_site
from forliosa.news.sources import BLOCK_STATUSES, Query, RawItem

log = logging.getLogger(__name__)

SOURCE = "gdelt_bulk"
BASE_URL = "https://storage.googleapis.com/data.gdeltproject.org/gdeltv2/"
# feed -> (index file, data file suffix)
FEEDS: dict[str, tuple[str, str]] = {
    "translation": ("lastupdate-translation.txt", ".translation.gkg.csv.zip"),
    "english": ("lastupdate.txt", ".gkg.csv.zip"),
}
PRIMARY_FEED = "translation"  # nearly every Taiwanese headline is in it
US_FEED = "english"  # US stocks and the US market: English pages only
SLOT = timedelta(minutes=15)
FRESH = timedelta(hours=2)  # the bulk files stand in for the DOC API while the newest file read is this recent
INTERVAL_SECONDS = 2.0
MAX_BYTES = 64 * 1024 * 1024  # a zipped file larger than this is not read (the largest seen: 13 MB)
BACKOFF_START = timedelta(minutes=15)
BACKOFF_MAX = timedelta(hours=4)
GKG_COLUMNS = 27
_TITLE = re.compile(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", re.S)
_DATA_NAME = re.compile(r"/(\d{14})\.(?:translation\.)?gkg\.csv\.zip\s*$")
USER_AGENT = "forliosa/0.1 (portfolio tracker; news headline index; GDELT bulk files)"
UsTest = Callable[[str, str], bool]  # (cleaned title, URL) -> the headline is about this US stock / the US market


def bulk_fetcher() -> HttpFetcher:
    """Only :data:`BASE_URL`; one request every 2 s; one retry after a dropped connection, never after a refusal."""
    return HttpFetcher(timeout=90.0, limiter=RateLimiter(per_host={"storage.googleapis.com": INTERVAL_SECONDS}),
                       retries=1, backoff=10.0, user_agent=USER_AGENT, extra_allowed=(BASE_URL,))


def slot_name(slot: datetime) -> str:
    return slot.astimezone(UTC).strftime("%Y%m%d%H%M%S")


def parse_slot(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_index(text: str) -> datetime | None:
    """The time slot of the GKG file a ``lastupdate*.txt`` index names (``<size> <md5> <url>`` lines)."""
    for line in text.splitlines():
        m = _DATA_NAME.search(line)
        if m:
            return parse_slot(m.group(1))
    return None


@dataclass(frozen=True)
class GkgRow:
    seen: datetime  # the file's time slot (UTC): when GDELT saw the article
    domain: str
    url: str
    title: str  # the page title as published (entities decoded)


def gkg_rows(data: bytes, keep_domain=is_taiwan_outlet) -> Iterator[GkgRow]:
    """The rows of a zipped GKG 2.1 file whose site ``keep_domain`` accepts and that have a page title. Columns
    (tab-separated): 1 DATE, 3 SourceCommonName (the site's domain), 4 DocumentIdentifier (the URL), 26 the XML extras
    holding ``<PAGE_TITLE>``. Streamed: the unzipped file (up to ~45 MB) is never held whole."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise ValueError("no CSV in the GDELT zip")
        with z.open(names[0]) as raw:
            for line in io.TextIOWrapper(raw, encoding="utf-8", errors="replace"):
                head = line.split("\t", 5)
                if len(head) < 6:
                    continue
                domain = head[3].strip().lower()
                if not domain or not keep_domain(domain):
                    continue
                cols = line.rstrip("\r\n").split("\t")
                if len(cols) < GKG_COLUMNS:
                    continue
                seen = parse_slot(cols[1])
                url = cols[4].strip()
                m = _TITLE.search(cols[26])
                title = " ".join(html.unescape(m.group(1)).split()) if m else ""
                if seen is None or not url.startswith(("http://", "https://")) or not title:
                    continue
                yield GkgRow(seen=seen, domain=domain, url=url, title=title)


def taiwan_or_us_site(domain: str) -> bool:
    return is_taiwan_outlet(domain) or us_outlet_site(domain)


def match(rows: Iterable[GkgRow], queries: Mapping[str, Query],
          us: Mapping[str, UsTest] | None = None) -> dict[str, list[RawItem]]:
    """symbol -> the rows whose cleaned title names that company: Taiwanese sites' rows against the Taiwan stocks of
    ``queries`` (cheap substring test first, then :func:`is_relevant`), US and UK outlets' pages against ``us``."""
    prepared = [(sym, q.terms, [n.casefold() for n in (*q.terms.names, *q.terms.forms)], q.terms.codes)
                for sym, q in queries.items() if q.taiwan]
    out: dict[str, list[RawItem]] = {}
    for row in rows:
        title = clean_title(row.title, row.url, outlet_name(row.url, row.domain))
        if is_taiwan_outlet(row.domain):
            low = title.casefold()
            for sym, terms, names, codes in prepared:
                if not (any(n in low for n in names) or any(c in title for c in codes)):
                    continue
                if is_relevant(title, terms, url=row.url, raw_title=row.title):
                    out.setdefault(sym, []).append(
                        RawItem(title=row.title, url=row.url, published_at=row.seen, domain=row.domain))
        elif us and is_us_outlet(row.url):
            for sym, test in us.items():
                if test(title, row.url):
                    out.setdefault(sym, []).append(
                        RawItem(title=row.title, url=row.url, published_at=row.seen, domain=row.domain))
    return out


@dataclass
class BulkResult:
    items: dict[str, list[RawItem]] = field(default_factory=dict)
    files: int = 0
    bytes: int = 0
    rows: int = 0  # rows from Taiwanese sites with a title
    us_rows: int = 0  # pages of US and UK news outlets with a title (english feed, when US stocks are matched)
    skipped_slots: int = 0  # files left out after a long outage
    paused: list[str] = field(default_factory=list)
    errors: int = 0


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _state(db: Session, feed: str) -> NewsFetchState:
    key = "@" + feed
    row = db.get(NewsFetchState, (SOURCE, key))
    if row is None:
        row = NewsFetchState(source=SOURCE, symbol=key, last_status="", items=0, failures=0)
        db.add(row)
    return row


class GdeltBulk:
    """Reads the new GKG files of each feed and matches their Taiwanese headlines to the given symbols."""

    key = SOURCE

    def __init__(self, feeds: Iterable[str] = ("translation", "english"), max_files: int = 8,
                 fetcher: HttpFetcher | None = None):
        self.feeds = tuple(f for f in feeds if f in FEEDS)
        self.max_files = max(1, max_files)
        self.fetcher = fetcher or bulk_fetcher()

    def _lead(self, feed: str | None) -> list[str]:
        if feed is not None:
            return [feed] if feed in self.feeds else []
        return [PRIMARY_FEED] if PRIMARY_FEED in self.feeds else list(self.feeds)

    def healthy(self, db: Session, now: datetime, feed: str | None = None) -> bool:
        """``feed`` (default: the primary feed, else any configured feed) has a file read within :data:`FRESH`; a
        feed that is not configured never has (US stocks: ``healthy(db, now, US_FEED)``)."""
        for f in self._lead(feed):
            row = db.get(NewsFetchState, (SOURCE, "@" + f))
            done = _aware(row.last_success_at) if row is not None else None
            if done is not None and now - done <= FRESH:
                return True
        return False

    def covered_until(self, db: Session, feed: str | None = None) -> datetime | None:
        """Up to when the bulk files were read: the end of ``feed``'s newest file read (default: the primary feed's,
        else any configured feed's), or ``None``."""
        done = [d for f in self._lead(feed) if (row := db.get(NewsFetchState, (SOURCE, "@" + f))) is not None
                and (d := _aware(row.last_success_at)) is not None]
        return max(done) + SLOT if done else None

    def slots(self, last: datetime | None, latest: datetime) -> tuple[list[datetime], int]:
        """The slots to read after ``last`` up to ``latest`` (at most ``max_files``, the newest), and how many older
        ones are skipped."""
        first = latest - SLOT * (self.max_files - 1)
        start = first if last is None else last + SLOT
        skipped = 0
        if start < first:
            skipped = int((first - start) / SLOT)
            start = first
        out = []
        t = start
        while t <= latest:
            out.append(t)
            t += SLOT
        return out, skipped

    def _pause(self, db: Session, st: NewsFetchState, now: datetime, status: str, reason: str) -> None:
        st.failures = (st.failures or 0) + 1
        st.last_status = status
        st.backoff_until = now + min(BACKOFF_START * (2 ** min(st.failures - 1, 16)), BACKOFF_MAX)
        db.commit()
        log.warning("GDELT bulk feed %s %s (%s); not asked again before %s", st.symbol[1:],
                    "is unreachable" if status == "unreachable" else "refused", reason[:160],
                    st.backoff_until.isoformat())

    def run(self, db: Session, queries: Mapping[str, Query], now: datetime,
            keep: Callable[[dict[str, list[RawItem]]], None] | None = None,
            us: Mapping[str, UsTest] | None = None) -> BulkResult:
        """Read the new files of each feed and match them against ``queries`` (Taiwan stocks) and ``us`` (US stocks
        and the US market: the ``english`` feed only). A feed is read only when something is matched in it: the
        ``translation`` feed for Taiwan stocks, ``english`` for either (one download serves both). ``keep`` gets each
        file's matches before the file is booked as read (its slot written to ``last_success_at``), so they are stored
        by then: a run cut off between the two reads the file again (2026-11-16 review: the matches were stored only
        after the whole run, and a worker stopped meanwhile lost the files already booked)."""
        res = BulkResult()
        taiwan = any(q.taiwan for q in queries.values())
        for feed in self.feeds:
            feed_us = us if feed == US_FEED and us else None
            if not (taiwan or feed_us):
                continue
            keep_site = taiwan_or_us_site if feed_us else is_taiwan_outlet
            index_name, suffix = FEEDS[feed]
            st = _state(db, feed)
            until = _aware(st.backoff_until)
            if until is not None and until > now:
                res.paused.append(feed)
                continue
            st.last_attempt_at = now
            db.commit()
            try:
                latest = parse_index(self.fetcher.get_bytes(BASE_URL + index_name).decode("utf-8", "replace"))
            except HttpStatusError as exc:
                if exc.status in BLOCK_STATUSES:
                    self._pause(db, st, now, "rate_limited", str(exc))
                    res.paused.append(feed)
                else:
                    res.errors += 1
                    st.last_status, st.failures = "error", (st.failures or 0) + 1
                    db.commit()
                continue
            except Exception as exc:  # unreachable: pause like any source that is down
                self._pause(db, st, now, "unreachable", str(exc))
                res.paused.append(feed)
                continue
            if latest is None:
                res.errors += 1
                st.last_status, st.failures = "error", (st.failures or 0) + 1
                db.commit()
                log.warning("GDELT bulk feed %s: the index names no GKG file", feed)
                continue
            slots, skipped = self.slots(_aware(st.last_success_at), latest)
            res.skipped_slots += skipped
            if skipped:
                log.warning("GDELT bulk feed %s: %d files (%s of news) skipped after a pause", feed, skipped,
                            skipped * SLOT)
            matched = 0
            for slot in slots:
                url = f"{BASE_URL}{slot_name(slot)}{suffix}"
                try:
                    data = self.fetcher.get_bytes(url)
                except HttpStatusError as exc:
                    if exc.status == 404:  # GDELT skipped this slot now and then: nothing to read
                        st.last_success_at = slot
                        db.commit()
                        continue
                    if exc.status in BLOCK_STATUSES:
                        self._pause(db, st, now, "rate_limited", str(exc))
                        res.paused.append(feed)
                    else:
                        res.errors += 1
                    break
                except Exception as exc:  # a dropped download: the next run tries this slot again
                    res.errors += 1
                    log.warning("GDELT bulk %s: %s", url.rsplit("/", 1)[-1], str(exc)[:200])
                    break
                res.files += 1
                res.bytes += len(data)
                try:
                    if len(data) > MAX_BYTES:
                        raise ValueError(f"{len(data)} bytes")
                    rows = list(gkg_rows(data, keep_site))
                except (zipfile.BadZipFile, zlib.error, EOFError, ValueError, OSError) as exc:  # skipped, not retried
                    res.errors += 1
                    log.warning("GDELT bulk %s not readable: %s", url.rsplit("/", 1)[-1], str(exc)[:200])
                    rows = []
                res.rows += sum(1 for r in rows if is_taiwan_outlet(r.domain))
                res.us_rows += sum(1 for r in rows if feed_us and is_us_outlet(r.url))
                found = match(rows, queries, feed_us)
                if keep is not None:
                    keep(found)
                for sym, items in found.items():
                    res.items.setdefault(sym, []).extend(items)
                    matched += len(items)
                st.last_success_at = slot
                st.failures, st.backoff_until, st.last_status = 0, None, "ok"
                db.commit()
            st.items = matched
            db.commit()
        return res
