"""GDELT's 15-minute bulk files (decision 7, 2026-11-16): parsing, the per-feed progress, refusals, matching only
Taiwanese sites, and the refresh using them for Taiwan stocks with the DOC API as the fallback.

The fixtures are trimmed live files of 2026-11-16 (GKG 2.1: the identifying columns and ``<PAGE_TITLE>`` kept, the
heavy analysis columns emptied, every row moved to the 06:15 UTC slot) and the two live ``lastupdate`` indexes."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.config import Settings
from forliosa.marketdata.http import HttpStatusError, ProviderUnavailable
from forliosa.models import NewsArticle, NewsFetchState
from forliosa.news import gdelt_bulk as gb
from forliosa.news import service
from forliosa.news.outlets import is_not_news, is_reputable, is_taiwan_outlet
from tests.news.conftest import FakeSource, fixture_bytes

SLOT = datetime(2026, 11, 16, 6, 15, tzinfo=UTC)
NOW = SLOT + timedelta(minutes=25)  # GDELT publishes a file a few minutes after its slot
TRANSLATION = fixture_bytes("gdelt_gkg_translation_live_20261116.csv.zip")
ENGLISH = fixture_bytes("gdelt_gkg_english_live_20261116.csv.zip")


def index(slot: datetime, feed: str = "translation") -> bytes:
    suffix = gb.FEEDS[feed][1]
    return (f"13251333 3c3a35b7 http://data.gdeltproject.org/gdeltv2/{gb.slot_name(slot)}"
            f"{suffix.replace('.gkg.csv.zip', '.export.CSV.zip')}\n"
            f"13251333 3c3a35b7 http://data.gdeltproject.org/gdeltv2/{gb.slot_name(slot)}{suffix}\n").encode()


def gkg_zip(*rows: tuple[str, str, str, str]) -> bytes:
    """A GKG file of (slot, domain, url, title) rows (27 tab-separated columns)."""
    lines = []
    for slot, domain, url, title in rows:
        cols = ["r1", slot, "1", domain, url] + [""] * 20 + ["", f"<PAGE_TITLE>{title}</PAGE_TITLE>"]
        lines.append("\t".join(cols))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("x.gkg.csv", "\n".join(lines) + "\n")
    return buf.getvalue()


class FakeFetcher:
    """URL -> bytes, an exception, or missing (404). Every request is recorded."""

    def __init__(self, answers: dict[str, bytes | Exception] | None = None):
        self.answers = answers or {}
        self.urls: list[str] = []

    def get_bytes(self, url: str, params=None, headers=None) -> bytes:
        self.urls.append(url)
        assert url.startswith(gb.BASE_URL)
        a = self.answers.get(url)
        if a is None:
            raise HttpStatusError("storage.googleapis.com 回應 HTTP 404", 404)
        if isinstance(a, Exception):
            raise a
        return a


def url(slot: datetime, feed: str = "translation") -> str:
    return f"{gb.BASE_URL}{gb.slot_name(slot)}{gb.FEEDS[feed][1]}"


def index_url(feed: str = "translation") -> str:
    return gb.BASE_URL + gb.FEEDS[feed][0]


def build(db: Session, md, *syms: str):
    return {md.instrument(s).symbol: service.build_query(db, md.instrument(s), NOW - timedelta(days=7), NOW)
            for s in syms}


# -- parsing --------------------------------------------------------------------------------------------------
def test_index_files_name_the_newest_gkg_file():
    assert gb.parse_index(fixture_bytes("gdelt_lastupdate_live_20261116.txt").decode()) == \
        datetime(2026, 11, 16, 12, 45, tzinfo=UTC)
    assert gb.parse_index(fixture_bytes("gdelt_lastupdate_translation_live_20261116.txt").decode()) == \
        datetime(2026, 11, 16, 12, 30, tzinfo=UTC)
    assert gb.parse_index("<html>error</html>") is None


def test_rows_from_taiwanese_sites_with_their_chinese_titles():
    rows = list(gb.gkg_rows(TRANSLATION))
    domains = {r.domain for r in rows}
    # 中華網, 財經網 (China) and 東森美洲 (ettvamerica.com, US) are left out; .tw hosts and udn / setn stay
    assert domains == {"udn.com", "ltn.com.tw", "cna.com.tw", "setn.com"}
    titles = [r.title for r in rows]
    assert "崇越科技美國布局再擴大 擬設波夕據點就近服務美光" in titles  # entities decoded, spaces collapsed
    assert all(r.seen == SLOT and r.url.startswith("https://") for r in rows)
    assert {r.domain for r in gb.gkg_rows(ENGLISH)} == {"setn.com", "taipeitimes.com"}
    everything = list(gb.gkg_rows(TRANSLATION, keep_domain=lambda d: True))
    assert len(everything) == 12


def test_match_names_the_company_in_the_title(engine, commercial_md):
    with Session(engine) as db:
        qs = build(db, commercial_md, "2330", "2317", "2308", "NVDA")
    found = gb.match(gb.gkg_rows(TRANSLATION), qs)
    assert sorted(found) == ["2317.TW", "2330.TW"]
    assert [i.title for i in found["2330.TW"]] == [
        "國安基金在哪？台股重挫2635點創收盤第三大跌點 台積電收低135元 | 股市要聞 | 股市",
        "台股收盤／台積電重摔135元！台股崩2635點史上第2慘 資安概念力抗綠海 | 財經",
    ]  # 東森美洲's 「台積電開黑、台達電一度跌停」 is not from a Taiwanese site
    assert [i.domain for i in found["2317.TW"]] == ["ltn.com.tw"]
    english = gb.match(gb.gkg_rows(gkg_zip(
        ("20261116061500", "taipeitimes.com", "https://www.taipeitimes.com/News/biz/archives/2026/11/16/1",
         "TSMC shares slide as foreign investors sell"),
        ("20261116061500", "taipeitimes.com", "https://www.taipeitimes.com/News/biz/archives/2026/11/16/2",
         "Mekong delta floods and the tsmc of it all"))), qs)
    assert [i.title for i in english["2330.TW"]] == ["TSMC shares slide as foreign investors sell"]
    assert set(english) == {"2330.TW"}  # 「delta」「tsmc」 in lower case are not the company (case rules)


def test_outlet_lists():
    assert is_taiwan_outlet("https://ec.ltn.com.tw/article/1") and is_taiwan_outlet("udn.com")
    assert is_taiwan_outlet("https://tw.stock.yahoo.com/news/x") and not is_taiwan_outlet("finance.yahoo.com")
    assert not is_taiwan_outlet("ettvamerica.com") and not is_taiwan_outlet("ifeng.com")
    assert is_reputable("https://money.udn.com/money/story/1") and not is_reputable("https://udn.com/news/story/1")
    assert is_reputable("https://www.reuters.com/x") and is_reputable("https://ec.ltn.com.tw/x")
    for junk in ("https://aigc-note.cmoney.tw/answer/1", "https://www.cmoney.tw/forum/article/185082146",
                 "https://cmnews.com.tw/article/cmoneyairesearcher-1", "https://blog.fugle.tw/post/earnings-call-7799",
                 "https://histock.tw/stock/7799", "https://pchome.megatime.com.tw/stock/sid7799.html",
                 "https://blog.udn.com/kuopaiyen/192871169"):
        assert is_not_news(junk), junk
    assert not is_not_news("https://pchome.megatime.com.tw/news/cat1/20261116/1.html")
    assert not is_not_news("https://money.udn.com/money/story/5607/1")


# -- reading the feeds ----------------------------------------------------------------------------------------
def test_run_reads_the_new_files_and_remembers_where_it_stopped(engine, commercial_md):
    f = FakeFetcher({index_url(): index(SLOT), url(SLOT): TRANSLATION, url(SLOT - gb.SLOT): gkg_zip()})
    bulk = gb.GdeltBulk(feeds=["translation"], max_files=3, fetcher=f)  # type: ignore[arg-type]
    with Session(engine) as db:
        qs = build(db, commercial_md, "2330", "2317")
        res = bulk.run(db, qs, NOW)
        # the first run reads the newest max_files slots: 05:45 (missing: 404), 06:00, 06:15
        assert f.urls == [index_url(), url(SLOT - 2 * gb.SLOT), url(SLOT - gb.SLOT), url(SLOT)]
        assert res.files == 2 and res.rows == 8 and len(res.items["2330.TW"]) == 2 and not res.errors
        st = db.get(NewsFetchState, ("gdelt_bulk", "@translation"))
        assert st.last_success_at.replace(tzinfo=UTC) == SLOT and st.items == 3 and st.last_status == "ok"
        assert bulk.healthy(db, NOW) and not bulk.healthy(db, SLOT + gb.FRESH + timedelta(minutes=1))
        # next run: only what is new
        f.answers[index_url()] = index(SLOT + gb.SLOT)
        f.answers[url(SLOT + gb.SLOT)] = gkg_zip()
        f.urls.clear()
        res = bulk.run(db, qs, NOW + gb.SLOT)
        assert f.urls == [index_url(), url(SLOT + gb.SLOT)] and res.files == 1
        # after a long outage: at most max_files, the older slots are skipped
        later = SLOT + timedelta(hours=6)
        f.answers[index_url()] = index(later)
        f.urls.clear()
        res = bulk.run(db, qs, later + timedelta(minutes=20))
        assert len(f.urls) == 4 and res.skipped_slots == 20  # 06:45 … 11:30; read 11:45, 12:00, 12:15


def test_a_refusal_pauses_the_feed_and_a_bad_file_is_skipped(engine, commercial_md):
    f = FakeFetcher({index_url(): HttpStatusError("storage.googleapis.com 回應 HTTP 429", 429),
                     index_url("english"): index(SLOT, "english"), url(SLOT, "english"): b"not a zip"})
    bulk = gb.GdeltBulk(feeds=["translation", "english"], max_files=1, fetcher=f)  # type: ignore[arg-type]
    with Session(engine) as db:
        qs = build(db, commercial_md, "2330")
        res = bulk.run(db, qs, NOW)
        assert res.paused == ["translation"] and res.errors == 1 and res.files == 1
        st = db.get(NewsFetchState, ("gdelt_bulk", "@translation"))
        assert st.backoff_until.replace(tzinfo=UTC) == NOW + timedelta(minutes=15) and st.failures == 1
        # the unreadable English file is not asked again; the paused feed is not asked inside its pause
        en = db.get(NewsFetchState, ("gdelt_bulk", "@english"))
        assert en.last_success_at.replace(tzinfo=UTC) == SLOT
        assert not bulk.healthy(db, NOW)  # the primary feed (translation) never read a file
        f.urls.clear()
        bulk.run(db, qs, NOW + timedelta(minutes=10))
        assert f.urls == [index_url("english")]
    down = FakeFetcher({index_url(): ProviderUnavailable("無法連線 storage.googleapis.com")})
    with Session(engine) as db:
        res = gb.GdeltBulk(feeds=["translation"], fetcher=down).run(  # type: ignore[arg-type]
            db, build(db, commercial_md, "2330"), NOW + timedelta(hours=1))
        assert res.paused == ["translation"]


def test_the_fetcher_may_only_read_the_bulk_files():
    f = gb.bulk_fetcher()
    try:
        assert f.extra_allowed == (gb.BASE_URL,) and "Mozilla" not in f.client.headers["User-Agent"]
        assert f.limiter.interval_for("storage.googleapis.com") >= 2.0
        with pytest.raises(ProviderUnavailable):
            f.get_bytes("https://storage.googleapis.com/some-other-bucket/x")
    finally:
        f.client.close()


# -- the refresh ----------------------------------------------------------------------------------------------
def test_refresh_uses_the_bulk_files_for_taiwan_stocks_and_the_doc_api_for_the_rest(engine, commercial_md, settings):
    f = FakeFetcher({index_url(): index(SLOT), url(SLOT): TRANSLATION})
    bulk = gb.GdeltBulk(feeds=["translation"], max_files=1, fetcher=f)  # type: ignore[arg-type]
    doc = FakeSource(items={})
    with Session(engine) as db:
        rep = service.refresh(db, commercial_md, settings=settings, sources=[doc], ai=None, bulk=bulk,
                              symbols=["2330.TW", "2317.TW", "NVDA"], now_fn=lambda: NOW)
        assert rep.bulk_ok and rep.fetched == {"gdelt_bulk": 1, "gdelt": 1} and rep.bulk_rows == 8
        assert [q.symbol for q in doc.calls] == ["NVDA"]  # the DOC API only for the US stock
        assert rep.skipped == {"gdelt_bulk": 2}
        rows = list(db.scalars(select(NewsArticle).where(NewsArticle.symbol == "2330.TW")))
        assert sorted(r.title for r in rows) == [
            "台股收盤／台積電重摔135元！台股崩2635點史上第2慘 資安概念力抗綠海",
            "國安基金在哪？台股重挫2635點創收盤第三大跌點 台積電收低135元 | 股市要聞"]  # outlet / section tails cut
        assert all(r.source == "gdelt" and r.published_at.replace(tzinfo=UTC) == SLOT for r in rows)
        st = db.get(NewsFetchState, ("gdelt", "2330.TW"))  # booked as answered up to the file's end: the AI gate
        assert st.last_success_at.replace(tzinfo=UTC) == SLOT + gb.SLOT  # reads it
        assert st.items == 2 and st.last_status == "ok"
        assert st.last_attempt_at.replace(tzinfo=UTC) == NOW  # the rotation still turns
        # the files stop (GDELT's bucket refuses); runs while the last file is still current read nothing new
        f.answers[index_url()] = HttpStatusError("storage.googleapis.com 回應 HTTP 403", 403)
        for k in (1, 2):
            t = NOW + timedelta(minutes=45 * k)
            rep = service.refresh(db, commercial_md, settings=settings, sources=[doc], ai=None, bulk=bulk,
                                  symbols=["2330.TW"], now_fn=lambda t=t: t)
            assert rep.bulk_ok and [q.symbol for q in doc.calls] == ["NVDA"]
        # once they are older than FRESH the DOC API is the fallback, from where the bulk files left it (2026-11-16
        # review: it started from the last run's time, 40 minutes of news later)
        later = SLOT + gb.FRESH + timedelta(minutes=30)
        rep = service.refresh(db, commercial_md, settings=settings, sources=[doc], ai=None, bulk=bulk,
                              symbols=["2330.TW"], now_fn=lambda: later)
        assert not rep.bulk_ok and "gdelt_bulk:translation" in rep.blocked_sources
        assert doc.calls[-1].symbol == "2330.TW"
        assert doc.calls[-1].since == SLOT + gb.SLOT - service.OVERLAP


def test_the_bulk_files_are_matched_for_every_tracked_stock_not_only_the_batch(engine, commercial_md, settings):
    """2026-11-16 review: a file is read once, so a stock outside the run's batch (NEWS_MAX_SYMBOLS_PER_RUN) lost its
    matches for good."""
    settings = settings.model_copy(update={"news_max_symbols_per_run": 1, "news_us_market": False})
    f = FakeFetcher({index_url(): index(SLOT), url(SLOT): TRANSLATION})
    bulk = gb.GdeltBulk(feeds=["translation"], max_files=1, fetcher=f)  # type: ignore[arg-type]
    with Session(engine) as db:
        for sym in ("2317.TW", "2330.TW"):
            service.record_view(db, sym, NOW)
        rep = service.refresh(db, commercial_md, settings=settings, sources=[FakeSource(items={})], ai=None,
                              bulk=bulk, now_fn=lambda: NOW)
        assert rep.symbols == 1 and rep.bulk_ok  # the batch is one stock
        assert db.scalar(select(NewsArticle).where(NewsArticle.symbol == "2330.TW")) is not None


def test_bulk_is_on_by_default_only_for_the_worker(settings: Settings):
    assert isinstance(service.gdelt_bulk_source(settings), gb.GdeltBulk)
    assert service.gdelt_bulk_source(settings).feeds == ("translation", "english")
    assert service.gdelt_bulk_source(settings.model_copy(update={"news_gdelt_bulk": False})) is None
    assert service.gdelt_bulk_source(settings.model_copy(update={"news_gdelt_enabled": False})) is None
    with pytest.raises(ValueError):
        Settings(news_gdelt_bulk_feeds="translation,klingon")
    assert Settings(news_gdelt_bulk_feeds="Translation").news_gdelt_bulk_feeds == ["translation"]
