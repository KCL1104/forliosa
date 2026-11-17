"""LangSearch as a source of Taiwan stocks' headlines (產品負責人 2026-11-17; recommendation §9.7): the request body,
the query and its time range, what is read from an answer, how refusals stop it until 00:00 UTC, the filter in its
measured order, the market topics, the takedown list applied here, the schedule's order and daily caps, tiers, the
degradation ladder, the gap between requests across processes and the logs. No network: LangSearch answers through an
``httpx.MockTransport`` (the autouse ``no_langsearch_network`` refuses everything else). The headlines are public ones
from the experiment of 2026-11-17 (title, link, time), put together into answers here."""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.config import get_settings
from forliosa.marketdata.http import RateLimiter
from forliosa.models import NewsArticle, NewsBlockedDomain, NewsFetchState, NewsTrackedView
from forliosa.news import langsearch as ls
from forliosa.news import service
from forliosa.news.normalize import clean_title, is_bot_flash, make_terms
from forliosa.news.sources import Query, RawItem, SourceBlocked, SourceDown
from forliosa.timeutil import TAIPEI

NOW = datetime(2026, 11, 17, 10, 40, tzinfo=UTC)  # 18:40 Taipei, a Tuesday (trading day)
KEY = "sk-ls-test-9f3a7c21e0"
MIDNIGHT = datetime(2026, 11, 18, tzinfo=UTC)  # the next 00:00 UTC (08:00 Taipei)


# -- helpers ------------------------------------------------------------------------------------------------------
def page(name: str, url: str, published: str | None, **extra: Any) -> dict[str, Any]:
    return {"id": "results.#0", "name": name, "url": url, "displayUrl": url, "datePublished": published, **extra}


def answer(*pages: dict[str, Any], tokens: tuple[int, int] = (5, 30), code: int = 200,
           msg: str | None = None) -> dict[str, Any]:
    return {"code": code, "log_id": "x", "msg": msg, "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1]},
            "data": {"_type": "SearchResponse", "webPages": {"value": list(pages)}}}


Answer = dict[str, Any] | int | Exception | Callable[[httpx.Request], httpx.Response]


class FakeLangSearch:
    """LangSearch behind a mock transport: the scripted answers in turn (the last repeats) — a dict (JSON, 200), an int
    (that status), an exception (raised) or a callable. Every request is recorded."""

    def __init__(self, *answers: Answer) -> None:
        self.answers: list[Answer] = list(answers) or [answer()]
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        a = self.answers[min(len(self.requests) - 1, len(self.answers) - 1)]
        if isinstance(a, Exception):
            raise a
        if isinstance(a, int):
            return httpx.Response(a, headers={"location": "https://langsearch.com/"} if 300 <= a < 400 else None,
                                  content=b"{}")
        if callable(a):
            return a(request)
        return httpx.Response(200, json=a)

    @property
    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]

    @property
    def queries(self) -> list[str]:
        return [b["query"] for b in self.bodies]


class Wall:
    """A wall clock that moves only when something sleeps."""

    def __init__(self, t: datetime = NOW) -> None:
        self.t = t
        self.slept: list[float] = []
        self.sent: list[datetime] = []

    def __call__(self) -> datetime:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += timedelta(seconds=seconds)

    def mono(self) -> float:
        return self.t.timestamp()


def make_client(fake: FakeLangSearch, wall: Wall, interval: float = 1.5, key: str = KEY) -> ls.LangSearchClient:
    """A real client on the mock transport with a limiter of its own (a new process) on the fake clock."""
    limiter = RateLimiter(per_host={ls.HOST: interval})
    limiter._sleep, limiter._clock = wall.sleep, wall.mono

    def handler(request: httpx.Request) -> httpx.Response:
        wall.sent.append(wall.t)
        return fake.handler(request)

    return ls.LangSearchClient(key, interval=interval, limiter=limiter, transport=httpx.MockTransport(handler))


@pytest.fixture()
def lset():
    return get_settings().model_copy(update={"news_enabled": True, "news_langsearch_enabled": True,
                                             "langsearch_api_key": SecretStr(KEY), "news_ai_enabled": False})


def run(db: Session, md, settings, fake: FakeLangSearch, wall: Wall | None = None, now: datetime = NOW, *,
        held: set[str] | frozenset[str] = frozenset(), ranks: dict[str, int] | None = None) -> ls.LangSearchReport:
    wall = wall or Wall(now)
    client = make_client(fake, wall, settings.news_langsearch_interval_seconds)
    return ls.refresh_langsearch(db, md, settings, now, client=client, ranks=lambda: dict(ranks or {}),
                                 held=set(held), clock=wall, sleep=wall.sleep)


def view(db: Session, *symbols: str, at: datetime = NOW) -> None:
    for s in symbols:
        db.merge(NewsTrackedView(symbol=s, last_viewed_at=at))
    db.commit()


def booked(db: Session, symbol: str, tier: str, last_success: datetime | None, set_at: datetime = NOW,
           average: float = 0.0) -> None:
    """A symbol already asked before: its tier row and its last success."""
    ls.write_tier(db, symbol, ls.TierState(tier, average, 0, set_at, last_success is not None), last_success)
    if last_success is not None:
        row = ls._row(db, symbol)
        row.last_success_at = row.last_attempt_at = last_success
        row.last_status = "ok"
        db.commit()


def wide(db: Session) -> NewsFetchState | None:
    return db.get(NewsFetchState, (ls.SOURCE_KEY, service.SOURCE_WIDE))


def aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=UTC)


def q_for(name: str, code: str, since: datetime, until: datetime = NOW, symbol: str | None = None) -> Query:
    return Query(symbol=symbol or f"{code}.TW", code=code, name=name, market="TWSE", english=(),
                 terms=make_terms(name, code, taiwan=True), since=since, until=until)


# -- 1. the body ----------------------------------------------------------------------------------------------------
def test_body_always_caps_contents():
    for fresh in ("oneDay", "oneWeek", "oneMonth", "2026-11-16..2026-11-17"):
        for count in (1, 20, 50, 80):
            body = ls.request_body('"台積電"', fresh, count)
            assert body["contents"] == {"text": {"max_characters": 1}} and body["summary"] is False
            assert "includeDomains" not in body and "excludeDomains" not in body
            assert 1 <= body["count"] <= 50 and body["freshness"] == fresh
    body = ls.request_body('"台積電"', "oneDay", 20)
    body["contents"]["text"]["max_characters"] = 5000  # a caller changing its copy never changes the cap
    assert ls.CONTENTS_CAP == {"text": {"max_characters": 1}}
    for bad in ("noLimit", ""):
        with pytest.raises(ValueError):
            ls.request_body('"台積電"', bad, 20)


# -- 2. the query ---------------------------------------------------------------------------------------------------
def test_stock_query():
    assert ls.stock_query("台積電") == '"台積電"'
    assert ls.stock_query("永冠-KY") == '"永冠"'
    assert ls.stock_query("91APP*-KY") == '"91APP"'
    assert ls.stock_query('台"積"電') == '"台積電"' and ls.stock_query("「鴻海」") == '"鴻海"'
    for bad in ("", "2330", '""'):
        with pytest.raises(ValueError):
            ls.stock_query(bad)


# -- 3. the time range ----------------------------------------------------------------------------------------------
def test_freshness():
    d = NOW.date()
    assert ls.freshness(NOW - timedelta(days=1), NOW, "large", first_fill=False) == f"{d - timedelta(days=1)}..{d}"
    assert ls.freshness(NOW - timedelta(days=3), NOW, "mid", first_fill=False) == f"{d - timedelta(days=3)}..{d}"
    assert ls.freshness(NOW - timedelta(days=10), NOW, "small", first_fill=False) == f"{d - timedelta(days=6)}..{d}"
    assert ls.freshness(NOW - timedelta(days=10), NOW, "small", first_fill=False, every=4) \
        == f"{d - timedelta(days=6)}..{d}"
    # every 7 days (quiet, or small on the ladder's first step): from the day of the last success, no gap (review)
    assert ls.freshness(NOW - timedelta(days=7), NOW, "quiet", first_fill=False, every=7) \
        == f"{d - timedelta(days=7)}..{d}"
    assert ls.freshness(NOW - timedelta(days=12), NOW, "quiet", first_fill=False, every=7) \
        == f"{d - timedelta(days=7)}..{d}"
    assert ls.freshness(NOW - timedelta(hours=2), NOW, "large", first_fill=False) == f"{d - timedelta(days=1)}..{d}"
    assert ls.freshness(None, NOW, "large", first_fill=True) == "oneWeek"
    assert ls.freshness(None, NOW, "mid", first_fill=True) == "oneWeek"
    assert ls.freshness(None, NOW, "small", first_fill=True) == "oneMonth"
    assert ls.topic_freshness(NOW) == f"{d}..{d}"
    # the UTC date turns at 08:00 Taipei: 07:59 is still yesterday's, 08:01 today's
    before = datetime(2026, 11, 18, 7, 59, tzinfo=TAIPEI)
    after = datetime(2026, 11, 18, 8, 1, tzinfo=TAIPEI)
    assert ls.topic_freshness(before) == "2026-11-17..2026-11-17"
    assert ls.topic_freshness(after) == "2026-11-18..2026-11-18"
    assert ls.freshness(NOW, after, "large", first_fill=False) == "2026-11-17..2026-11-18"
    # the window the filter checks starts at 00:00 UTC of the first day (the grace is taken off by the caller)
    assert ls.window_start("2026-11-14..2026-11-17", NOW) == datetime(2026, 11, 14, tzinfo=UTC)
    assert ls.window_start("oneWeek", NOW) == datetime(2026, 11, 10, tzinfo=UTC)


# -- 4. reading an answer -------------------------------------------------------------------------------------------
def test_parse_reads_only_title_url_date():
    long = "內文" * 3000
    payload = answer(
        page("台積電抵得住市場恐慌 外媒曝成長型股票首選", "https://ec.ltn.com.tw/article/breakingnews/5635795",
             "2026-11-10T07:18:38.000Z", snippet=long, summary=long, text=long),
        page("沒有日期的頁面", "https://ec.ltn.com.tw/article/breakingnews/1", None, snippet=long),
        page("日期壞掉", "https://ec.ltn.com.tw/article/breakingnews/2", "yesterday"),
        page("", "https://ec.ltn.com.tw/article/breakingnews/3", "2026-11-10T07:18:38Z"),
        page("沒有網址", "", "2026-11-10T07:18:38Z"),
        page("只有日期", "https://udn.com/news/story/7251/1", "2026-11-12"),
    )
    items = ls.parse(payload, NOW)
    assert [i.title for i in items] == ["台積電抵得住市場恐慌 外媒曝成長型股票首選", "只有日期"]
    first = items[0]
    assert first.published_at == datetime(2026, 11, 10, 7, 18, 38, tzinfo=UTC) and not first.date_only
    assert set(vars(first)) == {"title", "url", "published_at", "date_only", "outlet", "domain"}
    assert long not in repr(items)
    assert items[1].date_only and items[1].published_at == datetime(2026, 11, 12, tzinfo=TAIPEI)
    with pytest.raises(ls.LangSearchError):
        ls.parse(answer(code=400, msg="bad parameter"), NOW)
    with pytest.raises(ls.LangSearchQuota):
        ls.parse(answer(code=429), NOW)
    with pytest.raises(SourceDown):
        ls.parse(answer(code=503), NOW)


def test_parse_skips_dates_out_of_range():
    """A datePublished at the edge of the calendar overflows on the way to UTC: that item is skipped, never the
    whole answer (review 2026-11-17)."""
    for bad in ("0001-01-01T00:00:00+08:00", "9999-12-31T23:59:59-05:00"):
        assert ls.parse_published(bad) is None
    items = ls.parse(answer(
        page("台積電法說會 營收創高", "https://money.udn.com/money/story/5612/1", "2026-11-17T05:00:00Z"),
        page("日期超出範圍", "https://money.udn.com/money/story/5612/2", "9999-12-31T23:59:59-05:00"),
        page("日期超出範圍", "https://money.udn.com/money/story/5612/3", "0001-01-01T00:00:00+08:00")), NOW)
    assert [i.title for i in items] == ["台積電法說會 營收創高"]


def test_a_200_without_results_list_is_not_an_empty_answer(engine, commercial_md, lset):
    """``code`` 200 without ``data.webPages.value`` is an unusable answer (that query only), not "no news": the last
    success, the empty runs and the tier stay as they were (review 2026-11-17). A real empty answer has ``[]``."""
    for payload in ({"code": 200, "data": None}, {"code": 200}, {"code": 200, "data": {"webPages": None}},
                    {"code": 200, "data": {}}, {"code": 200, "data": {"webPages": {"value": "x"}}}):
        with pytest.raises(ls.LangSearchError):
            ls.parse(payload, NOW)
    assert ls.parse({"code": 200, "data": {"webPages": {"value": []}}}, NOW) == []
    settings = lset.model_copy(update={"news_langsearch_topics": []})
    last = NOW - timedelta(days=4)
    with Session(engine) as db:
        view(db, "2330.TW")
        booked(db, "2330.TW", "small", last)
        st = ls.read_tier(db, "2330.TW")
        st.empty_runs = 3
        ls.write_tier(db, "2330.TW", st, last)
        rep = run(db, commercial_md, settings, FakeLangSearch({"code": 200, "data": None, "usage": {}}))
        assert rep.requests == 1 and rep.errors == 1 and rep.symbols == 0
        row = db.get(NewsFetchState, ("langsearch", "2330.TW"))
        assert aware(row.last_success_at) == last and row.last_status == "error"
        assert (ls.read_tier(db, "2330.TW").tier, ls.read_tier(db, "2330.TW").empty_runs) == ("small", 3)


# -- 5. status mapping ----------------------------------------------------------------------------------------------
def test_status_mapping(engine, commercial_md, lset):
    with Session(engine) as db:
        view(db, "2330.TW", "2317.TW")
        # 429: stopped until the next 00:00 UTC after one request, no retry; a restart remembers it
        fake = FakeLangSearch(429)
        rep = run(db, commercial_md, lset, fake)
        assert len(fake.requests) == 1 and rep.stopped == "quota"
        w = wide(db)
        assert w.last_status == "rate_limited" and aware(w.backoff_until) == MIDNIGHT
        assert ls.read_usage(db, NOW.date()).stopped == "quota" and ls.read_usage(db, NOW.date()).requests == 1
        later = run(db, commercial_md, lset, fake, now=NOW + timedelta(hours=3))
        assert later.skipped == "paused" and len(fake.requests) == 1
        nxt = datetime(2026, 11, 18, 8, 5, tzinfo=TAIPEI)  # 00:05 UTC: open again (overdue stocks run from 08:00)
        rep = run(db, commercial_md, lset, FakeLangSearch(), now=nxt)
        assert rep.skipped is None and rep.requests >= 1 and wide(db).backoff_until is None

    for i, (script, why) in enumerate([
            ([answer(code=200, msg="Daily quota exceeded")], "quota"),  # 200 with a quota message
            ([answer(code=429, msg="too many")], "quota"),
            ([403], "blocked"), ([401], "blocked"), ([302], "blocked"),  # a redirect is a refusal, never followed
            ([answer(tokens=(5, 5000))], "contract")]):  # the contents cap was ignored
        fake = FakeLangSearch(*script)
        with Session(engine) as db:
            db.query(NewsFetchState).delete()
            db.commit()
            view(db, "2330.TW", "2317.TW")
            rep = run(db, commercial_md, lset, fake)
            assert (rep.stopped, len(fake.requests)) == (why, 1), (i, rep)
            assert aware(wide(db).backoff_until) == MIDNIGHT
            assert wide(db).last_status == ("rate_limited" if why == "quota" else "blocked")
            st = ls.status(db, lset, NOW)
            assert st["stopped"] == why and st["warning"] == ("contents_cap_ignored" if why == "contract" else None)
            if why == "contract":
                assert st["tokens"] == 5005  # the answer's tokens are counted all the same

    # two 5xx / timeouts in a row: unreachable, paused 15 minutes (doubling) from the second failure, not until midnight
    fake = FakeLangSearch(500, httpx.ReadTimeout("slow"))
    with Session(engine) as db:
        db.query(NewsFetchState).delete()
        db.commit()
        view(db, "2330.TW", "2317.TW", "2454.TW")
        wall = Wall()
        rep = run(db, commercial_md, lset, fake, wall)
        assert rep.stopped == "unreachable" and len(fake.requests) == 2
        w = wide(db)
        assert w.last_status == "unreachable" and aware(w.backoff_until) == wall.t + timedelta(minutes=15)
        # one 5xx then an answer: no pause, the failed one is asked again next time
        db.query(NewsFetchState).delete()
        db.commit()
        fake = FakeLangSearch(503, answer())
        rep = run(db, commercial_md, lset, fake)
        assert rep.stopped is None and rep.requests == 3 + 3 and wide(db) is None  # 3 topics + 3 stocks


def test_outages_in_a_row_are_counted_across_passes(engine, commercial_md, lset):
    """A pass with a single due task: one timeout per pass still makes two in a row, so the source pauses 15 minutes
    and then doubles — not one request every 10 minutes for the rest of the day (review 2026-11-17)."""
    morning = datetime(2026, 11, 17, 10, 0, tzinfo=TAIPEI)  # a trading day before 16:00: no topics yet
    fake = FakeLangSearch(httpx.ReadTimeout("slow"))
    with Session(engine) as db:
        view(db, "2330.TW", at=morning)
        rep = run(db, commercial_md, lset, fake, now=morning)
        assert (rep.requests, rep.stopped, wide(db)) == (1, None, None) and ls.down_in_a_row(db) == 1
        rep = run(db, commercial_md, lset, fake, now=morning + timedelta(minutes=10))
        assert (rep.requests, rep.stopped) == (1, "unreachable")
        assert aware(wide(db).backoff_until) == morning + timedelta(minutes=25)
        assert run(db, commercial_md, lset, fake, now=morning + timedelta(minutes=20)).skipped == "paused"
        # after the pause, still down: one more failure pauses it again, doubled
        rep = run(db, commercial_md, lset, fake, now=morning + timedelta(minutes=30))
        assert (rep.requests, rep.stopped) == (1, "unreachable") and ls.down_in_a_row(db) == 3
        assert aware(wide(db).backoff_until) == morning + timedelta(minutes=60)
        assert len(fake.requests) == 3 and ls.read_usage(db, NOW.date()).requests == 3
        # an answer ends the run of failures and the pause's doubling
        rep = run(db, commercial_md, lset, FakeLangSearch(), now=morning + timedelta(minutes=70))
        assert rep.symbols == 1 and ls.down_in_a_row(db) == 0 and wide(db).backoff_until is None
        # any answer counts, a 4xx too
        ls._note_down(db, NOW)
        ls._book_outcome(db, NOW.date(), NOW, ls.LangSearchError("LangSearch HTTP 422"), 1000)
        assert ls.down_in_a_row(db) == 0


def test_outage_pause_runs_from_the_failure_not_the_pass_start(engine, commercial_md, lset):
    """A long pass (slow answers): the pause after two 5xx starts when they happened, so it has not run out when it
    is written and the next pass, 20 seconds later, is held back (review 2026-11-17)."""
    wall = Wall()

    def slow(request: httpx.Request) -> httpx.Response:
        wall.t += timedelta(minutes=4)
        return httpx.Response(200, json=answer())

    fake = FakeLangSearch(slow, slow, slow, slow, 503)
    with Session(engine) as db:
        view(db, "2330.TW", "2317.TW", "2454.TW")  # 3 topics + 3 stocks
        rep = run(db, commercial_md, lset, fake, wall)
        assert rep.stopped == "unreachable" and len(fake.requests) == 6
        failed_at = wall.t
        assert failed_at > NOW + timedelta(minutes=16)
        until = aware(wide(db).backoff_until)
        assert until == failed_at + timedelta(minutes=15) and until > wall.t
        nxt = run(db, commercial_md, lset, fake, now=wall.t + timedelta(seconds=20))
        assert nxt.skipped == "paused" and len(fake.requests) == 6


def test_another_4xx_skips_that_query_only(engine, commercial_md, lset):
    settings = lset.model_copy(update={"news_langsearch_topics": []})
    fake = FakeLangSearch(422, answer())
    with Session(engine) as db:
        view(db, "2330.TW", "2317.TW")
        rep = run(db, commercial_md, settings, fake)
        assert rep.errors == 1 and rep.stopped is None and len(fake.requests) == 2
        failed = next(s for s in ("2330.TW", "2317.TW") if db.get(NewsFetchState, ("langsearch", s)).last_status ==
                      "error")
        # not asked again the same UTC day; the next day it is
        again = run(db, commercial_md, settings, FakeLangSearch(), now=NOW + timedelta(minutes=30))
        assert again.requests == 0
        fake = FakeLangSearch()
        run(db, commercial_md, settings, fake, now=NOW + timedelta(days=1))
        assert '"' + ("台積電" if failed == "2330.TW" else "鴻海") + '"' in fake.queries


# -- 6. the filter --------------------------------------------------------------------------------------------------
EXPERIMENT = [  # (stock, its code, the answer's item) — public headlines of the 2026-11-17 experiment
    ("台達電", "2308", page("台達電跌勢不止!千元大關岌岌可危 股民欲哭無淚",
                            "https://ec.ltn.com.tw/article/breakingnews/5643723", "2026-11-17T07:06:00.000Z")),
    ("家登", "3680", page("Una casa accogliente si riconosce da 4 dettagli che cambiano tutto",
                          "https://www.tuttogreen.it/casa-accogliente-4-dettagli-che-cambiano-tutto",
                          "2026-11-17T09:33:19.000Z")),
    ("台積電", "2330", page("台積電澄清聲明背後 是戰略轉型還是市場傳聞的壓力測試",
                            "https://www.tainan-estate-et.com.tw/%E5%B7%A5%E6%A5%AD%E8%B3%87%E8%A8%8A/x",
                            "2026-11-17T08:15:39.000Z")),
    ("長榮", "2603", page("【哩程升等攻略】長榮、華航、星宇升等vs兌換每哩價值大公開!豪經升商務1.18元",
                          "https://pokem.tw/mileage-upgrade-tactics", "2026-11-17T08:33:01.000Z")),
    ("家登", "3680", page("家將藝術節神氣登場 聯合出巡為民祈福",
                          "https://tw.news.yahoo.com/%E5%AE%B6%E5%B0%87-073600626.html", "2026-11-16T10:49:00.000Z")),
    ("華城", "1519", page("南韓華城市長揭AI、航太雙引擎 製造業重鎮轉型未來科技樞紐", "https://lifenews.com.tw/612946",
                          "2026-11-16T14:37:35.000Z")),
    ("訊聯", "1784", page("影/鹿港1784千帆館落成啟用 潮間帶童趣樂園同步開放",
                          "https://hoomedia.com.tw/2026/11/10/179985", "2026-11-16T10:48:28.000Z")),
    ("長榮", "2603", page("長榮大學33週年校慶感恩禮拜 期許長榮33智創新局共榮永續",
                          "https://n.yam.com/Article/20261117551240", "2026-11-17T03:25:25.000Z")),
    ("華城", "1519", page("盤中速報 - 電機機械股價指數類股表現疲軟,跌幅2.77%,總成交額0.96億",
                          "https://news.cnyes.com/news/id/6664642", "2026-11-17T01:04:22.000Z")),
]


def test_filter_pipeline():
    since = datetime(2026, 11, 16, tzinfo=UTC) - ls.GRACE
    junk = get_settings().news_langsearch_junk_domains
    kept: dict[str, list[str]] = {}
    drops: Counter[str] = Counter()
    for name, code, item in EXPERIMENT:
        raw = ls.parse(answer(item), NOW)
        heads = ls.filter_items(raw, q_for(name, code, since), [], junk, drops=drops)
        kept.setdefault(name, []).extend(h.title for h in heads)
    assert kept["台達電"] == ["台達電跌勢不止!千元大關岌岌可危 股民欲哭無淚"]
    assert all(not v for k, v in kept.items() if k != "台達電")
    # where each was dropped: the Italian page is not a Taiwanese site, the two junk sites are on the list, the robot
    # flash and the four pages that do not name the stock fall at the title test
    assert drops == Counter({"not_taiwan": 1, "junk": 2, "title_or_name_or_time": 5})
    assert is_bot_flash(clean_title(EXPERIMENT[8][2]["name"], EXPERIMENT[8][2]["url"]))
    # a udn story and its Yahoo股市 copy: one headline, the udn one
    week = datetime(2026, 11, 10, tzinfo=UTC) - ls.GRACE
    pair = ls.parse(answer(
        page("智邦前3季每股賺58.09元 寫同期新高",
             "https://tw.stock.yahoo.com/news/%E6%99%BA%E9%82%A6-133509393.html", "2026-11-12T13:35:09.000Z"),
        page("智邦前3季每股賺58.09元 寫同期新高", "https://money.udn.com/money/story/5710/9875406",
             "2026-11-12T13:50:54.000Z")), NOW)
    drops = Counter()
    heads = ls.filter_items(pair, q_for("智邦", "2345", week), [], junk, drops=drops)
    assert [(h.outlet, h.url) for h in heads] == [("經濟日報", "https://money.udn.com/money/story/5710/9875406")]
    assert heads[0].source == "langsearch" and drops["duplicate"] == 1
    # outside the window (older than its start less the grace, or more than 30 minutes after the request): dropped
    late = ls.parse(answer(
        page("台達電法說會 營收創高", "https://ec.ltn.com.tw/article/breakingnews/1", "2026-11-15T10:00:00Z"),
        page("台達電法說會 營收再創高", "https://ec.ltn.com.tw/article/breakingnews/2", "2026-11-17T11:30:00Z")), NOW)
    assert ls.filter_items(late, q_for("台達電", "2308", since), [], junk) == []


# -- 7. the market topics -------------------------------------------------------------------------------------------
def test_topic_filter(monkeypatch):
    def no_name_test(*_a, **_k):
        raise AssertionError("the topics are not matched by a company name")

    monkeypatch.setattr(service, "is_relevant", no_name_test)
    since = datetime(2026, 11, 17, tzinfo=UTC) - ls.GRACE
    q = ls._topic_query(NOW, since)
    raw = ls.parse(answer(
        page("台股收盤大漲300點 台積電領軍", "https://money.udn.com/money/story/5607/1", "2026-11-17T06:00:00Z"),
        page("加權指數站回月線 外資回補", "https://www.cna.com.tw/news/afe/202611170001.aspx", "2026-11-17T06:10:00Z"),
        page("晚間跌破2萬8千點?專家這樣看", "https://news.cnyes.com/news/id/1", "2026-11-17T07:00:00Z"),
        page("颱風動態最新 週末天氣轉涼", "https://www.cna.com.tw/news/ahel/202611170002.aspx", "2026-11-17T05:00:00Z"),
    ), NOW)
    heads = ls.filter_items(raw, q, [], [], topic=True)
    assert sorted(h.title for h in heads) == sorted(["台股收盤大漲300點 台積電領軍", "加權指數站回月線 外資回補",
                                                    "晚間跌破2萬8千點?專家這樣看"])
    assert ls.topic_relevant("台股 盤後", "") and not ls.topic_relevant("颱風動態", "")


def test_topics_run_on_trading_days_from_16_00_once_per_utc_day(engine, commercial_md, lset):
    fake = FakeLangSearch(answer(
        page("台股收盤大漲300點 外資買超", "https://money.udn.com/money/story/5607/1", "2026-11-17T06:00:00Z")))
    afternoon = datetime(2026, 11, 17, 16, 5, tzinfo=TAIPEI)
    with Session(engine) as db:
        assert run(db, commercial_md, lset, fake, now=afternoon - timedelta(minutes=10)).requests == 0  # 15:55
        rep = run(db, commercial_md, lset, fake, now=afternoon)
        assert rep.topics == 3 and fake.queries == ["台股 盤後", "外資 買賣超", "台股 大盤"]
        assert {b["freshness"] for b in fake.bodies} == {"2026-11-17..2026-11-17"}
        assert {b["count"] for b in fake.bodies} == {20}
        rows = db.scalars(select(NewsArticle).where(NewsArticle.symbol == "^TW")).all()
        assert [(r.title, r.source) for r in rows] == [("台股收盤大漲300點 外資買超", "langsearch")]
        assert run(db, commercial_md, lset, fake, now=afternoon + timedelta(hours=2)).requests == 0  # done today
        saturday = datetime(2026, 11, 21, 16, 5, tzinfo=TAIPEI)
        assert run(db, commercial_md, lset, fake, now=saturday).topics == 0


# -- 8. the takedown list -------------------------------------------------------------------------------------------
def test_blocklist_applied_locally(engine, commercial_md, lset):
    settings = lset.model_copy(update={"news_langsearch_topics": [], "news_blocked_domains": ["ltn.com.tw"]})
    fake = FakeLangSearch(answer(
        page("台積電法說會 營收創高", "https://ec.ltn.com.tw/article/breakingnews/7", "2026-11-17T05:00:00Z"),
        page("台積電法說會 營收創高 外資喊買", "https://money.udn.com/money/story/5612/7", "2026-11-17T05:10:00Z")))
    with Session(engine) as db:
        db.add(NewsBlockedDomain(domain="udn.com", reason="下架", created_at=NOW))
        view(db, "2330.TW")
        rep = run(db, commercial_md, settings, fake)
        assert rep.requests == 1 and rep.kept == 0 and rep.drops["junk"] == 2
        raw = fake.requests[0].content.decode()
        assert "udn" not in raw and "ltn" not in raw and "Domains" not in raw
        assert db.scalars(select(NewsArticle)).all() == []


# -- 9. the schedule ------------------------------------------------------------------------------------------------
def test_scheduler_priority_and_caps(engine, commercial_md, lset):
    settings = lset.model_copy(update={"news_langsearch_topics": ["台股 盤後"],
                                       "news_langsearch_max_requests_per_day": 5})
    day = timedelta(days=1)
    with Session(engine) as db:
        view(db, "2330.TW", "2317.TW", "2454.TW", "2303.TW", "2308.TW", "2412.TW", "NVDA")
        booked(db, "2412.TW", "mid", NOW - 2 * day)  # watched: before every tier
        booked(db, "2330.TW", "large", NOW - day)
        booked(db, "2303.TW", "large", NOW - 3 * day)  # missed two days: the oldest large first
        booked(db, "2317.TW", "mid", NOW - 2 * day)
        booked(db, "2454.TW", "small", NOW - 4 * day)
        booked(db, "2308.TW", "mid", NOW - day)  # not due (every 2 days)
        fake = FakeLangSearch()
        rep = run(db, commercial_md, settings, fake, held={"2412.TW"})
        assert fake.queries == ["台股 盤後", '"中華電"', '"聯電"', '"台積電"', '"鴻海"']  # topics, held, large, mid
        assert rep.stopped == "requests_cap" and rep.requests == 5
        assert fake.bodies[2]["freshness"] == "2026-11-14..2026-11-17" and fake.bodies[2]["count"] == 50
        assert fake.bodies[4]["count"] == 20
        assert not any("NVIDIA" in q for q in fake.queries)  # US stocks never
        # the next day starts with what was left (the small cap, from its own last success) after the daily ones
        fake = FakeLangSearch()
        rep = run(db, commercial_md, settings, fake, now=NOW + day, held={"2412.TW"})
        assert fake.queries == ["台股 盤後", '"聯電"', '"台積電"', '"台達電"', '"聯發科"']
        assert fake.bodies[4]["freshness"] == "2026-11-13..2026-11-18"
        # before 18:30 only a stock that missed its day runs (not the daily ones); the topics wait for 16:00
        fake = FakeLangSearch()
        morning = datetime(2026, 11, 20, 9, 0, tzinfo=TAIPEI)
        run(db, commercial_md, settings, fake, now=morning, held={"2412.TW"})
        assert '"台積電"' in fake.queries and "台股 盤後" not in fake.queries
        assert fake.bodies[fake.queries.index('"台積電"')]["freshness"] == "2026-11-18..2026-11-20"
        # nothing between 00:00 and 08:00 Taipei
        assert run(db, commercial_md, settings, fake, now=datetime(2026, 11, 21, 7, 30, tzinfo=TAIPEI)).skipped \
            == "night"


def test_first_fills_tokens_cap_and_initial_tiers(engine, commercial_md, lset):
    settings = lset.model_copy(update={"news_langsearch_topics": [], "news_langsearch_max_first_fill_per_day": 2,
                                       "news_langsearch_large_rank": 1})
    with Session(engine) as db:
        view(db, "2330.TW", "2317.TW", "2454.TW")
        fake = FakeLangSearch()
        rep = run(db, commercial_md, settings, fake, ranks={"2330.TW": 1, "2317.TW": 2})
        assert rep.first_fills == 2 and fake.queries == ['"台積電"', '"鴻海"']  # large first, then by rank
        assert [b["freshness"] for b in fake.bodies] == ["oneWeek", "oneWeek"]
        assert [b["count"] for b in fake.bodies] == [50, 20]
        assert ls.read_tier(db, "2330.TW").tier == "large" and ls.read_tier(db, "2454.TW").tier == "mid"
        assert ls.first_fills_on(db, NOW.date()) == 2
        assert run(db, commercial_md, settings, FakeLangSearch()).requests == 0  # the day's first fills are used
        # the token cap stops a pass too
        tight = settings.model_copy(update={"news_langsearch_max_tokens_per_day": 30,
                                            "news_langsearch_max_first_fill_per_day": 10})
        fake = FakeLangSearch()
        rep = run(db, commercial_md, tight, fake, now=NOW + timedelta(days=1))
        assert rep.stopped == "tokens_cap" and len(fake.requests) == 1


def test_nothing_older_than_the_retention_is_stored(engine, commercial_md, lset):
    """A small cap's first fill asks for a month (``oneMonth``, less the grace): what the purge would delete at
    once — older than NEWS_RETENTION_DAYS, a date-only one's day of grace included — is never stored (review)."""
    settings = lset.model_copy(update={"news_langsearch_topics": []})
    keep_from = NOW - timedelta(days=settings.news_retention_days)  # 2026-10-18 10:40 UTC
    fake = FakeLangSearch(answer(
        page("台積電法說會 營收創高", "https://money.udn.com/money/story/5612/31", "2026-10-18T05:00:00Z"),
        page("台積電董事會通過資本預算", "https://money.udn.com/money/story/5612/32", "2026-10-18"),
        page("台積電赴美設廠進度曝光", "https://money.udn.com/money/story/5612/33", "2026-10-20T05:00:00Z")))
    with Session(engine) as db:
        view(db, "2330.TW")
        booked(db, "2330.TW", "small", None)
        rep = run(db, commercial_md, settings, fake)
        assert fake.bodies[0]["freshness"] == "oneMonth"
        assert (rep.first_fills, rep.kept, rep.stored) == (1, 1, 1)
        rows = db.scalars(select(NewsArticle).where(NewsArticle.symbol == "2330.TW")).all()
        assert [r.title for r in rows] == ["台積電赴美設廠進度曝光"]
        assert all(aware(r.published_at) >= keep_from for r in rows)
        assert service.purge(db, settings, NOW) == 0  # nothing for the purge to take back


def test_quiet_stock_window_starts_on_its_last_success(engine, commercial_md, lset):
    """A stock asked every 7 days (quiet, or small on the ladder's first step) asks from the UTC date of its last
    success, so the evening after it is not lost (review 2026-11-17)."""
    settings = lset.model_copy(update={"news_langsearch_topics": []})
    last = datetime(2026, 11, 10, 10, 35, tzinfo=UTC)  # 18:35 Taipei a week ago
    after_it = page("台積電盤後法說會 營收創高", "https://money.udn.com/money/story/5612/41", "2026-11-10T11:30:00Z")
    with Session(engine) as db:
        view(db, "2330.TW")
        booked(db, "2330.TW", "quiet", last)
        fake = FakeLangSearch(answer(after_it))
        rep = run(db, commercial_md, settings, fake)
        assert fake.bodies[0]["freshness"] == "2026-11-10..2026-11-17" and rep.stored == 1


def test_headlines_flow_into_the_stock_page_tagging_and_ai_count(engine, client, commercial_md, lset, monkeypatch):
    settings = lset.model_copy(update={"news_langsearch_topics": []})
    fake = FakeLangSearch(answer(
        page("台積電法說會 營收創高 外資喊買", "https://money.udn.com/money/story/5612/9", "2026-11-17T05:10:00Z"),
        page("台積10月營收飆 月增14%創高", "https://ec.ltn.com.tw/article/breakingnews/9", "2026-11-17T05:20:00Z"),
        page("台積電", "https://www.wantgoo.com/stock/2330", "2026-11-17T05:00:00Z")))  # a quote page
    with Session(engine) as db:
        view(db, "2330.TW")
        rep = run(db, commercial_md, settings, fake)
        assert (rep.kept, rep.stored) == (2, 2)
        rows = db.scalars(select(NewsArticle).where(NewsArticle.symbol == "2330.TW")).all()
        assert {r.source for r in rows} == {"langsearch"} and {r.outlet for r in rows} == {"經濟日報", "自由時報"}
        assert set(NewsArticle.__table__.columns.keys()) == {"id", "symbol", "url_key", "url", "title", "outlet",
                                                              "domain", "published_at", "date_only", "source",
                                                              "fetched_at"}
        from forliosa.news import tagging

        items, _ = tagging.pending(db, commercial_md, get_settings(), NOW, 50)
        assert len(items) == 2  # waiting for the tagging job like any other row
        assert service.recent_free_count(db, "2330.TW", NOW) == 2  # free: they hold the paid AI fallback back
    # the page reads the last NEWS_RETENTION_DAYS from the clock: pinned to the run's day, so this test does not
    # start failing 30 days after 2026-11-17 (review)
    monkeypatch.setattr(service, "now_utc", lambda: NOW + timedelta(minutes=5))
    r = client.get("/api/v1/instruments/2330/news")
    media = [n for n in r.json() if n["category"] == "media"]
    assert {n["source"] for n in media} == {"LangSearch"} and len(media) == 2


# -- 10. tiers ------------------------------------------------------------------------------------------------------
def test_tiering():
    s = get_settings()
    assert ls.tier_for(6, 0, s) == "large" and ls.tier_for(2, 0, s) == "mid" and ls.tier_for(0.5, 0, s) == "small"
    assert ls.tier_for(0.5, 4, s) == "quiet" and ls.tier_for(0, 3, s) == "small"
    # a small cap with 4 empty runs goes quiet; one headline brings it back to small
    st = ls.TierState("small", 0.4, 0, NOW, True)
    t = NOW
    for _ in range(4):
        t += timedelta(days=1)
        st = ls.after_run(st, 0, t, s)
    assert (st.tier, st.empty_runs) == ("quiet", 4)
    st = ls.after_run(st, 1, t + timedelta(days=1), s)
    assert (st.tier, st.empty_runs) == ("small", 0)
    # weekly: recomputed from the average (about two weeks of runs)
    st = ls.TierState("mid", 0.0, 0, NOW - timedelta(days=8), False)
    assert ls.after_run(st, 6, NOW, s).tier == "large"  # first run: the average is that run
    st = ls.TierState("large", 6.0, 0, NOW, True)
    for i in range(1, 15):
        st = ls.after_run(st, 0, NOW + timedelta(days=i), s)
    assert st.tier == "quiet" and st.average < 1.0  # a large cap that stopped finding anything: every 7 days
    st = ls.TierState("mid", 2.0, 0, NOW, True)
    assert ls.after_run(st, 2, NOW + timedelta(days=2), s).tier == "mid"


def test_tier_rows_are_booked_after_each_run(engine, commercial_md, lset):
    settings = lset.model_copy(update={"news_langsearch_topics": []})
    titles = ["台積電法說會 營收創高", "台積電赴美設廠進度曝光", "外資調升台積電目標價", "台積電2奈米量產時程",
              "台積電董事會通過資本預算", "台積電ADR夜盤大漲"]
    hits = answer(*(page(t, f"https://money.udn.com/money/story/5612/{i}", "2026-11-17T05:00:00Z")
                    for i, t in enumerate(titles)))
    with Session(engine) as db:
        view(db, "2330.TW")
        booked(db, "2330.TW", "mid", NOW - timedelta(days=2), set_at=NOW - timedelta(days=8), average=4.8)
        run(db, commercial_md, settings, FakeLangSearch(hits))
        st = ls.read_tier(db, "2330.TW")
        assert st.tier == "large" and st.set_at == NOW and st.average > 0


# -- 11. the degradation ladder -------------------------------------------------------------------------------------
def test_degradation_ladder(engine, commercial_md, lset):
    today = date(2026, 11, 17)

    def hits(*days_ago: int, requests: int = 101) -> dict[date, ls.DayUsage]:
        return {today - timedelta(days=n): ls.DayUsage(today - timedelta(days=n), requests, 0, None, "quota")
                for n in days_ago}

    assert ls.ladder(hits(1), today) == ls.Ladder(0, None)
    assert ls.ladder(hits(1, 2), today) == ls.Ladder(1, 80)  # 80 % of the 100 that went through before the hit
    assert ls.ladder(hits(1, 2, 3), today) == ls.Ladder(2, 80)
    assert ls.ladder(hits(1, 2, requests=30), today).level == 2  # a cap under 30 restricts too
    assert ls.ladder(hits(3, 4), today) == ls.Ladder(1, 80)  # two clean days: not cleared yet
    assert ls.ladder(hits(4, 5), today) == ls.Ladder(0, None)  # three clean days clear the step
    assert ls.ladder(hits(5, 6, 7), today).level == 1  # level 2 steps down one level per 3 clean days
    assert ls.ladder(hits(8, 9, 10), today).level == 0
    # back at 0, the old cap is gone: a single hit later is just a hit (review 2026-11-17)
    old = hits(20, 19, requests=30)  # cap floor(0.8 × 29) = 23, under 30: level 2 back then
    assert ls.ladder(old, today) == ls.Ladder(0, None)
    assert ls.ladder({**old, **hits(1)}, today) == ls.Ladder(0, None)
    assert ls.ladder({**old, **hits(10, 9)}, today) == ls.Ladder(0, None)  # a pair, cleared after 6 clean days
    assert ls.ladder({**hits(10, 9, 8, requests=30), **hits(1)}, today) == ls.Ladder(0, None)
    assert ls.ladder({**old, **hits(2, 1)}, today) == ls.Ladder(1, 80)  # a new pair: its own cap
    s = get_settings()
    assert ls.every_days(s, 1) == {"large": 1, "mid": 3, "small": 7, "quiet": 7}
    assert ls.every_days(s, 0) == {"large": 1, "mid": 2, "small": 4, "quiet": 7}

    # in a pass: quota yesterday and the day before -> cap 80 % and mid every 3 days
    with Session(engine) as db:
        for n in (1, 2):
            d = today - timedelta(days=n)
            row = ls._row(db, ls.usage_key(d))
            row.items, row.last_status, row.last_success_at = 101, "quota", NOW - timedelta(days=n)
        db.commit()
        view(db, "2330.TW", "2317.TW", "2454.TW")
        booked(db, "2317.TW", "mid", NOW - timedelta(days=2))
        fake = FakeLangSearch()
        rep = run(db, commercial_md, lset, fake, held={"2454.TW"})
        assert (rep.level, rep.cap) == (1, 80)
        assert '"鴻海"' not in fake.queries  # mid: every 3 days now
        # a third day: only the topics and held or watched large caps
        row = ls._row(db, ls.usage_key(today - timedelta(days=3)))
        row.items, row.last_status = 101, "quota"
        db.commit()
        db.query(NewsFetchState).filter(NewsFetchState.symbol.like("^TW/%")).delete(synchronize_session=False)
        booked(db, "2454.TW", "large", NOW - timedelta(days=1))
        booked(db, "2330.TW", "large", NOW - timedelta(days=1))
        db.commit()
        fake = FakeLangSearch()
        rep = run(db, commercial_md, lset, fake, held={"2454.TW"})
        assert rep.level == 2 and fake.queries == ["台股 盤後", "外資 買賣超", "台股 大盤", '"聯發科"']


# -- 12. the gap between requests -----------------------------------------------------------------------------------
def test_interval_across_processes(engine, commercial_md, lset):
    settings = lset.model_copy(update={"news_langsearch_topics": []})
    wall = Wall()
    with Session(engine) as db:
        view(db, "2330.TW", "2317.TW")
        run(db, commercial_md, settings, FakeLangSearch(), wall)
        assert len(wall.sent) == 2 and (wall.sent[1] - wall.sent[0]).total_seconds() >= 1.5  # in one process
        # a second process (a new limiter) half a second later, with a new stock to ask: it waits out the gap
        view(db, "2454.TW")
        wall.t += timedelta(seconds=0.5)
        run(db, commercial_md, settings, FakeLangSearch(), wall, now=wall.t)
        assert len(wall.sent) == 3 and (wall.sent[2] - wall.sent[1]).total_seconds() >= 1.5
        assert ls.last_request_at(db) == wall.sent[2]


# -- 13. logs -------------------------------------------------------------------------------------------------------
def test_no_secrets_in_logs(engine, commercial_md, lset, caplog):
    caplog.set_level(logging.DEBUG)
    long = "內文全文" * 100
    fake = FakeLangSearch(answer(page("台積電法說會 營收創高", "https://money.udn.com/money/story/5612/1",
                                      "2026-11-17T05:00:00Z", snippet=long, summary=long)),
                          answer(code=400, msg="secret-looking message"), 403)
    with Session(engine) as db:
        view(db, "2330.TW", "2317.TW")
        run(db, commercial_md, lset, fake)
    assert fake.requests and all(r.headers["authorization"] == f"Bearer {KEY}" for r in fake.requests)
    text = caplog.text
    assert KEY not in text and "Authorization" not in text and "authorization" not in text.lower()
    assert long[:20] not in text and "secret-looking" not in text
    assert "LangSearch" in text  # the status lines are there
    client = ls.LangSearchClient(KEY)
    assert KEY not in repr(client) and KEY not in repr(vars(ls.LangSearchSource(client)))


# -- the rest -------------------------------------------------------------------------------------------------------
def test_source_supports_taiwan_only_and_off_switches(engine, commercial_md, lset):
    src = ls.LangSearchSource(make_client(FakeLangSearch(), Wall()))
    since = NOW - timedelta(days=1)
    assert src.supports(q_for("台積電", "2330", since))
    assert src.supports(ls._topic_query(NOW, since))
    us = Query(symbol="NVDA", code="NVDA", name="NVIDIA", market="US", english=("NVIDIA",),
               terms=make_terms("NVIDIA", "NVDA", ["NVIDIA"]), since=since, until=NOW)
    assert not src.supports(us)
    with pytest.raises(ValueError):
        src.fetch(us, fresh="oneDay", count=20)
    with Session(engine) as db:
        view(db, "2330.TW")
        off = lset.model_copy(update={"news_langsearch_enabled": False})
        assert run(db, commercial_md, off, FakeLangSearch()).skipped == "off"
        no_key = lset.model_copy(update={"langsearch_api_key": None})
        assert ls.refresh_langsearch(db, commercial_md, no_key, NOW).skipped == "no_key"
        assert not no_key.langsearch_on and lset.langsearch_on


def test_bookkeeping_rows_stay_out_of_the_admin_and_are_purged(engine, commercial_md, lset):
    with Session(engine) as db:
        old = ls._row(db, ls.usage_key(date(2026, 9, 1)))
        old.items = 3
        db.commit()
        view(db, "2330.TW")
        run(db, commercial_md, lset, FakeLangSearch())
        assert db.get(NewsFetchState, ("langsearch", ls.usage_key(date(2026, 9, 1)))) is None
        from forliosa.services.admin import news_summary

        news = news_summary(db, NOW)
        by = {s["key"]: s for s in news["sources"]}
        assert by["langsearch"]["name"] == "LangSearch" and news["langsearch"]["requests"] == 4


def test_worker_runs_langsearch_only_when_switched_on(monkeypatch):
    from forliosa.worker import Worker

    monkeypatch.setenv("NEWS_LANGSEARCH_ENABLED", "false")
    get_settings.cache_clear()
    assert "news_langsearch" not in {j.name for j in Worker(md=object()).jobs}  # type: ignore[arg-type]
    monkeypatch.setenv("NEWS_LANGSEARCH_ENABLED", "true")
    get_settings.cache_clear()
    jobs = {j.name: j for j in Worker(md=object()).jobs}  # type: ignore[arg-type]
    assert jobs["news_langsearch"].background
    get_settings.cache_clear()


def test_smoke_prints_counts_only(engine, lset, capsys):
    from forliosa.news.__main__ import langsearch_smoke

    items = [page(f"台積電新聞{i}", f"https://money.udn.com/money/story/1/{i}", "2026-11-17T05:00:00Z",
                  snippet="內文") for i in range(20)]
    fake = FakeLangSearch(answer(*items, tokens=(5, 40)))
    wall = Wall()
    assert langsearch_smoke(make_client(fake, wall), lset, clock=wall, sleep=wall.sleep) == 0
    out = capsys.readouterr().out
    assert "20 筆" in out and "通過" in out and "台積電新聞" not in out and KEY not in out
    assert fake.bodies[0] == {"query": '"台積電"', "freshness": "oneDay", "summary": False, "count": 20,
                              "contents": {"text": {"max_characters": 1}}}
    with Session(engine) as db:  # counted like any request; no headline stored
        usage = ls.read_usage(db, NOW.date())
        assert (usage.requests, usage.tokens, usage.last_request_at) == (1, 45, NOW)
        assert db.scalars(select(NewsArticle)).all() == []


def test_smoke_keeps_the_workers_rules(engine, commercial_md, lset, capsys):
    """The manual check sends nothing while switched off, paused or past the day's caps, or while a pass runs; it
    waits out the gap to the last request of any process; and a refusal stops the worker too (review 2026-11-17)."""
    from forliosa.news.__main__ import langsearch_smoke

    def smoke(fake: FakeLangSearch, settings=lset, wall: Wall | None = None) -> int:
        wall = wall or Wall()
        return langsearch_smoke(make_client(fake, wall), settings, clock=wall, sleep=wall.sleep)

    # switched off (a key is set): nothing sent, nothing written
    fake = FakeLangSearch()
    assert smoke(fake, lset.model_copy(update={"news_langsearch_enabled": False})) == 1 and not fake.requests
    assert "已關閉" in capsys.readouterr().out
    with Session(engine) as db:
        assert db.scalars(select(NewsFetchState)).all() == []
    # 429: booked as the worker's would be — stopped until 00:00 UTC, the day's row says quota, the request counted
    fake = FakeLangSearch(429)
    assert smoke(fake) == 1 and len(fake.requests) == 1
    out = capsys.readouterr().out
    assert "429" in out and "00:00 UTC" in out
    with Session(engine) as db:
        w = wide(db)
        assert w.last_status == "rate_limited" and aware(w.backoff_until) == MIDNIGHT
        usage = ls.read_usage(db, NOW.date())
        assert (usage.stopped, usage.requests) == ("quota", 1)
        view(db, "2330.TW")
        assert run(db, commercial_md, lset, FakeLangSearch(), now=NOW + timedelta(minutes=5)).skipped == "paused"
    # paused: a second smoke sends nothing and says until when
    fake = FakeLangSearch()
    assert smoke(fake) == 1 and not fake.requests
    assert "暫停到 2026-11-18T08:00:00+08:00" in capsys.readouterr().out
    # 403 the same: the worker stops too
    with Session(engine) as db:
        db.query(NewsFetchState).delete()
        db.commit()
    assert smoke(FakeLangSearch(403)) == 1
    with Session(engine) as db:
        assert wide(db).last_status == "blocked" and aware(wide(db).backoff_until) == MIDNIGHT
    # past the day's request cap or token cap: nothing sent
    with Session(engine) as db:
        db.query(NewsFetchState).delete()
        row = ls._row(db, ls.usage_key(NOW.date()))
        row.items, row.failures = 5, 10
        db.commit()
    fake = FakeLangSearch()
    assert smoke(fake, lset.model_copy(update={"news_langsearch_max_requests_per_day": 5})) == 1
    assert smoke(fake, lset.model_copy(update={"news_langsearch_max_tokens_per_day": 10})) == 1
    assert not fake.requests and "上限" in capsys.readouterr().out
    # a pass is running (its lock is held): nothing sent
    with ls._LOCAL_LOCK:
        assert smoke(fake) == 1 and not fake.requests
    assert "worker 正在跑" in capsys.readouterr().out
    # the worker's last request 0.5 s ago (another process): the smoke waits out the gap, then counts its request
    with Session(engine) as db:
        db.query(NewsFetchState).delete()
        ls._sent(db, NOW.date(), NOW - timedelta(seconds=0.5))
    wall = Wall()
    fake = FakeLangSearch(answer(tokens=(5, 30)))
    smoke(fake, wall=wall)
    assert wall.sent == [NOW + timedelta(seconds=1)] and wall.slept == [pytest.approx(1.0)]
    with Session(engine) as db:
        usage = ls.read_usage(db, NOW.date())
        assert (usage.requests, usage.tokens, usage.last_request_at) == (1, 35, wall.sent[0])
    # two outages in a row (the smoke's and the worker's) pause the source like two in one pass
    with Session(engine) as db:
        db.query(NewsFetchState).delete()
        db.commit()
    assert smoke(FakeLangSearch(503)) == 1
    with Session(engine) as db:
        assert wide(db) is None and ls.down_in_a_row(db) == 1
        rep = run(db, commercial_md, lset.model_copy(update={"news_langsearch_topics": []}), FakeLangSearch(502),
                  now=NOW + timedelta(minutes=1))
        assert rep.stopped == "unreachable" and rep.requests == 1 and wide(db).last_status == "unreachable"


def test_unexpected_payloads():
    assert ls.interpret(ls.Reply(200, {"data": {"webPages": {"value": [
        page("台積電", "https://money.udn.com/money/story/1/1", "2026-11-17T05:00:00Z")]}}}), NOW, 1000)
    with pytest.raises(SourceDown):
        ls.interpret(ls.Reply(200, None), NOW, 1000)
    with pytest.raises(SourceBlocked):
        ls.interpret(ls.Reply(307, None), NOW, 1000)
    with pytest.raises(ls.LangSearchError):
        ls.interpret(ls.Reply(404, {}), NOW, 1000)
    assert ls.parse_published("2026-11-17T13:00:00+08:00") == (datetime(2026, 11, 17, 5, tzinfo=UTC), False)
    assert ls.parse_published("2026-11-17T05:00:00") == (datetime(2026, 11, 17, 5, tzinfo=UTC), False)
    assert ls.parse_published(None) is None and ls.parse_published("2026-13-45") is None
    with pytest.raises(ValueError):
        ls.LangSearchClient(KEY, "https://evil.example.com/v1/web-search")
    item = RawItem(title="x", url="https://a.tw/1", published_at=NOW)
    assert ls.filter_items([item], q_for("台積電", "2330", NOW - timedelta(days=1)), [], []) == []
