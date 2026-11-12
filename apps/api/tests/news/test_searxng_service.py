"""SearXNG in the news batch: an unreachable instance, unresponsive engines, pacing and the per-symbol cache,
skipping when GDELT already covers a symbol, merging with GDELT (canonical URLs, redirects dropped) and the AI
fallback counting both. SearXNG answers through ``httpx.MockTransport`` with synthetic fixtures."""

from __future__ import annotations

from datetime import UTC, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.datapolicy import label
from forliosa.models import NewsArticle, NewsFetchState
from forliosa.news import service
from forliosa.news.sources import RawItem, parse_gdelt
from tests.news.conftest import FETCHED_AT, FakeSource, fixture_bytes, make_searx, searx_fixture
from tests.news.test_service import AI_RESULTS, ai_answer

API = "/api/v1"
NOW = FETCHED_AT
EMPTY: dict[str, Any] = {"results": [], "unresponsive_engines": []}


def gdelt_items() -> list[RawItem]:
    return parse_gdelt(fixture_bytes("gdelt_tsmc_taiwan_live_20261112.json"))


def rows(db: Session, symbol: str = "2330.TW", source: str | None = None) -> list[NewsArticle]:
    q = select(NewsArticle).where(NewsArticle.symbol == symbol)
    if source:
        q = q.where(NewsArticle.source == source)
    return list(db.scalars(q.order_by(NewsArticle.published_at.desc())))


def state(db: Session, symbol: str, source: str = "searxng") -> NewsFetchState | None:
    return db.get(NewsFetchState, (source, symbol))


def aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=UTC)


def per_engine(reasons: dict[str, str], results: list[dict] | None = None):
    """An answer in which only the engines this request asked for report their reasons (as SearXNG does)."""

    def answer(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        asked = params["engines"].split(",") if "engines" in params else list(reasons)
        return httpx.Response(200, json={"results": results or [], "unresponsive_engines": [
            [e, r] for e, r in reasons.items() if e in asked]})

    return answer


def run(db, md, settings, sources, symbols, now=NOW, ai=None):
    return service.refresh(db, md, settings=settings, sources=sources, ai=ai, symbols=symbols, now_fn=lambda: now)


# -- an unreachable instance ---------------------------------------------------------------------------------------
def test_unreachable_instance_pauses_searxng_and_the_rest_continues(engine, client, commercial_md, settings,
                                                                     fake_searx, clock):
    fake_searx.answers = [httpx.ConnectError("Name or service not known"), searx_fixture(
        "searxng_tsmc_zh_tw_synthetic.json")]
    gdelt = FakeSource(items={"2330.TW": gdelt_items()[:4]})
    symbols = ["2330.TW", "2454.TW", "0050.TW"]
    with Session(engine) as db:
        rep = run(db, commercial_md, settings, [gdelt, make_searx(clock)], symbols)
        assert len(fake_searx.searches) == 1 and len(gdelt.calls) == 3  # asked once, GDELT went on
        assert rep.blocked_sources == ["searxng"] and rep.errors == 0
        wide = state(db, service.SOURCE_WIDE)
        assert wide.last_status == "unreachable" and aware(wide.backoff_until) == NOW + timedelta(minutes=15)
        assert len(rows(db, source="gdelt")) == 1
        # inside the pause: not asked at all
        run(db, commercial_md, settings, [gdelt, make_searx(clock, NOW + timedelta(minutes=10))], ["2317.TW"],
            NOW + timedelta(minutes=10))
        assert len(fake_searx.searches) == 1
        # after it: asked again; an answer reopens the source
        later = NOW + timedelta(minutes=20)
        rep = run(db, commercial_md, settings, [gdelt, make_searx(clock, later)], ["2330.TW"], later)
        assert len(fake_searx.searches) == 2 and rep.blocked_sources == []
        wide = state(db, service.SOURCE_WIDE)
        assert wide.failures == 0 and wide.backoff_until is None
    # nobody sees an error: /news answers from what is stored
    r = client.get(f"{API}/instruments/2330/news")
    assert r.status_code == 200 and any(n["category"] == "media" for n in r.json())


def test_every_engine_down_pauses_searxng(engine, commercial_md, settings, fake_searx, clock):
    fake_searx.answers = [searx_fixture("searxng_all_down_synthetic.json")]
    with Session(engine) as db:
        rep = run(db, commercial_md, settings, [FakeSource(items={}), make_searx(clock)], ["2330.TW", "2454.TW"])
        assert len(fake_searx.searches) == 1 and rep.blocked_sources == ["searxng"]
        assert state(db, service.SOURCE_WIDE).last_status == "unreachable"
        for e in ("bing news", "brave.news", "duckduckgo news"):  # booked one by one, not paused after one error
            st = state(db, service.engine_state_key(e))
            assert st.last_status == "error" and st.failures == 1 and st.backoff_until is None


# -- unresponsive engines ------------------------------------------------------------------------------------------
def test_a_refusing_engine_is_paused_and_left_out(engine, commercial_md, settings, fake_searx, clock):
    fake_searx.answers = [per_engine({"bing news": "Suspended: CAPTCHA", "brave.news": "timeout"})]
    with Session(engine) as db:
        rep = run(db, commercial_md, settings, [FakeSource(items={}), make_searx(clock)], ["2454.TW", "0050.TW"])
        assert rep.paused_engines == ["bing news"] and rep.blocked_sources == []
        bing = state(db, "@bing news")
        assert bing.last_status == "refused" and aware(bing.backoff_until) == NOW + timedelta(minutes=120)
        assert state(db, "@brave.news").failures == 2 and state(db, "@brave.news").backoff_until is None
        assert state(db, "@duckduckgo news").last_status == "ok"
        first, second = fake_searx.params(0), fake_searx.params(1)
        assert first["categories"] == "news" and "engines" not in first
        assert second["engines"] == "duckduckgo news,brave.news" and "categories" not in second
        # a third timeout in a row pauses brave too (15 minutes)
        rep = run(db, commercial_md, settings, [FakeSource(items={}), make_searx(clock)], ["2317.TW"])
        brave = state(db, "@brave.news")
        assert brave.failures == 3 and aware(brave.backoff_until) == NOW + timedelta(minutes=15)
        assert rep.paused_engines == ["brave.news"]


def test_every_engine_paused_pauses_searxng_until_the_first_returns(engine, commercial_md, settings, fake_searx,
                                                                      clock):
    fake_searx.answers = [searx_fixture("searxng_all_refused_synthetic.json")]
    with Session(engine) as db:
        rep = run(db, commercial_md, settings, [FakeSource(items={}), make_searx(clock)], ["2454.TW", "0050.TW"])
        assert len(fake_searx.searches) == 1 and rep.blocked_sources == ["searxng"]
        assert sorted(rep.paused_engines) == ["bing news", "brave.news", "duckduckgo news"]
        assert aware(state(db, service.SOURCE_WIDE).backoff_until) == NOW + timedelta(minutes=120)
        # SearXNG is closed while every engine is paused; when they are due again it is asked again
        later = NOW + timedelta(minutes=121)
        fake_searx.answers = [EMPTY]
        rep = run(db, commercial_md, settings, [FakeSource(items={}), make_searx(clock, later)], ["2317.TW"], later)
        assert len(fake_searx.searches) == 2 and rep.blocked_sources == []
        assert state(db, "@bing news").last_status == "ok"


def test_paused_engines_from_an_earlier_run_close_the_source(engine, commercial_md, settings, fake_searx, clock):
    with Session(engine) as db:
        for e in ("bing news", "duckduckgo news", "brave.news"):
            db.add(NewsFetchState(source="searxng", symbol=service.engine_state_key(e), last_status="refused", items=0,
                                  failures=1, backoff_until=NOW + timedelta(minutes=30 + len(e))))
        db.commit()
        rep = run(db, commercial_md, settings, [FakeSource(items={}), make_searx(clock)], ["2330.TW"])
        assert fake_searx.searches == [] and rep.blocked_sources == ["searxng"]
        # until the first engine is due again (bing news: 30 + 9 minutes)
        assert aware(state(db, service.SOURCE_WIDE).backoff_until) == NOW + timedelta(minutes=30 + len("bing news"))


# -- pacing and the per-symbol cache -------------------------------------------------------------------------------
def test_ten_seconds_between_queries_and_an_hour_per_symbol(engine, commercial_md, settings, fake_searx, clock):
    fake_searx.answers = [EMPTY]
    symbols = ["2330.TW", "2454.TW", "0050.TW"]
    with Session(engine) as db:
        rep = run(db, commercial_md, settings, [FakeSource(items={}), make_searx(clock)], symbols)
        assert rep.fetched["searxng"] == 3 and clock.sleeps == [10.0, 10.0]  # one at a time, ≥ 10 s apart
        half = NOW + timedelta(minutes=30)
        rep = run(db, commercial_md, settings, [FakeSource(items={}), make_searx(clock, half)], symbols, half)
        assert "searxng" not in rep.fetched and rep.skipped == {"searxng_cache": 3}
        assert len(fake_searx.searches) == 3
        later = NOW + timedelta(minutes=61)
        rep = run(db, commercial_md, settings, [FakeSource(items={}), make_searx(clock, later)], symbols, later)
        assert rep.fetched["searxng"] == 3 and len(fake_searx.searches) == 6


def test_skipped_when_gdelt_already_has_enough(engine, commercial_md, settings, fake_searx, clock):
    many = [RawItem(f"台積電新聞第{i}則", f"https://udn.com/news/story/1/{i}", NOW - timedelta(hours=i))
            for i in range(1, 9)]
    few = [RawItem("聯發科法說會", "https://udn.com/news/story/2/1", NOW - timedelta(hours=1))]
    gdelt = FakeSource(items={"2330.TW": many, "2454.TW": few})
    fake_searx.answers = [EMPTY]
    with Session(engine) as db:
        rep = run(db, commercial_md, settings, [gdelt, make_searx(clock)], ["2330.TW", "2454.TW"])
        assert rep.skipped == {"searxng_gdelt": 1} and rep.fetched == {"gdelt": 2, "searxng": 1}
        assert [p["q"] for p in (fake_searx.params(i) for i in range(len(fake_searx.searches)))] == ["聯發科 2454"]
        # off when GDELT is off: SearXNG is then asked for every symbol
        rep = run(db, commercial_md, settings.model_copy(update={"news_searxng_cache_minutes": 30}),
                  [make_searx(clock, NOW + timedelta(hours=1))], ["2330.TW"], NOW + timedelta(hours=1))
        assert rep.fetched == {"searxng": 1}


# -- merging with GDELT --------------------------------------------------------------------------------------------
def test_merged_with_gdelt_canonical_urls_and_no_redirects(engine, client, commercial_md, settings, fake_searx, clock):
    fake_searx.answers = [searx_fixture("searxng_tsmc_zh_tw_synthetic.json")]
    gdelt = FakeSource(items={"2330.TW": gdelt_items()})
    with Session(engine) as db:
        rep = run(db, commercial_md, settings, [gdelt, make_searx(clock)], ["2330.TW"])
        assert rep.fetched == {"gdelt": 1, "searxng": 1} and rep.stored == 13 + 4
        searx = {r.url: r for r in rows(db, source="searxng")}
        assert sorted(searx) == [
            "https://money.udn.com/money/story/5612/9100001",  # fbclid removed
            "https://news.cnyes.com/news/id/6200001",
            "https://www.cna.com.tw/news/afe/202611120200.aspx",  # the canonical page, not the AMP copy
            "https://www.setn.com/News.aspx?NewsID=1937500",  # not the m. copy with utm_*
        ]
        assert {r.outlet for r in searx.values()} == {"經濟日報", "鉅亨網", "中央社", "三立"}
        assert searx["https://www.setn.com/News.aspx?NewsID=1937500"].title == "台積電先進封裝擴產 CoWoS月產能再增"
        assert searx["https://news.cnyes.com/news/id/6200001"].date_only
        everything = rows(db)
        # the CNA story GDELT already had (https, :443) is not stored again from SearXNG's http + utm_* link
        cna = [r for r in everything if "202611120132" in r.url]
        assert len(cna) == 1 and cna[0].source == "gdelt"
        assert not any(x in r.url for r in everything for x in ("utm_", "fbclid", "bing.com", "news.google.com"))
        assert not any("聯發科" in r.title or "股東會紀念品" in r.title or "上月營收" in r.title for r in everything)
    media = [n for n in client.get(f"{API}/instruments/2330/news").json() if n["category"] == "media"]
    from_searx = [n for n in media if n["source"] == "SearXNG"]
    assert len(from_searx) == 4 and from_searx[0]["sources"] == [label("searxng")]
    assert len({n["url"] for n in media}) == len(media)


def test_us_stocks_are_asked_in_english(engine, commercial_md, settings, fake_searx, clock):
    fake_searx.answers = [searx_fixture("searxng_nvda_en_synthetic.json")]
    with Session(engine) as db:
        run(db, commercial_md, settings, [FakeSource(items={}), make_searx(clock)], ["NVDA"])
        p = fake_searx.params()
        assert p["q"] == "NVIDIA NVDA" and p["language"] == "en"
        got = {r.url: r for r in rows(db, "NVDA")}
        # the AMP-cache link is unwrapped to CNBC's own page; "Apple leads the Dow" is not about NVIDIA
        assert "https://www.cnbc.com/amp/2026/11/12/nvidia-stock-moves.html" in got
        assert not any("ampproject" in u or "marketwatch" in u for u in got)
        assert {r.outlet for r in got.values()} >= {"Reuters", "Yahoo Finance"}
    items = service.media_items(db, commercial_md, commercial_md.instrument("NVDA"), settings=settings, now=NOW)
    outlets = [i["outlet"] for i in items]
    assert "Reuters" in outlets and "Yahoo Finance" not in outlets  # the aggregator copy loses to the original


# -- the AI fallback counts GDELT and SearXNG together --------------------------------------------------------------
def test_no_ai_search_when_gdelt_and_searxng_together_have_three(engine, commercial_md, settings, pool, fake,
                                                                  fake_searx, clock):
    fake_searx.answers = [searx_fixture("searxng_tsmc_zh_tw_synthetic.json")]
    gdelt = FakeSource(items={"2330.TW": gdelt_items()[:4]})  # 1 relevant headline from GDELT alone
    with Session(engine) as db:
        rep = run(db, commercial_md, settings, [gdelt, make_searx(clock)], ["2330.TW"], ai="default")
        assert rep.ai_searches == 0 and fake.requests == []
        assert service.recent_free_count(db, "2330.TW", NOW) == 1 + 5  # GDELT 1, SearXNG 5 (incl. the CNA story)


def test_ai_search_when_both_have_too_few(engine, commercial_md, settings, pool, fake, fake_searx, clock):
    fake_searx.answers = [EMPTY]  # SearXNG answered: nothing
    ai_answer(fake, AI_RESULTS, [AI_RESULTS[0][0]])
    with Session(engine) as db:
        rep = run(db, commercial_md, settings, [FakeSource(items={"2330.TW": gdelt_items()[:4]}), make_searx(clock)],
                  ["2330.TW"], ai="default")
        assert rep.ai_searches == 1 and len(fake.requests) == 1


def test_a_paused_searxng_does_not_hold_the_ai_back(engine, commercial_md, settings, pool, fake, clock):
    ai_answer(fake, AI_RESULTS, [AI_RESULTS[0][0]])
    with Session(engine) as db:  # the autouse transport refuses: SearXNG is unreachable and paused
        rep = run(db, commercial_md, settings, [FakeSource(items={"2330.TW": gdelt_items()[:4]}), make_searx(clock)],
                  ["2330.TW"], ai="default")
        assert rep.blocked_sources == ["searxng"] and rep.ai_searches == 1


def test_searxng_not_yet_answered_holds_the_ai_back(engine, commercial_md, settings, pool, fake):
    with Session(engine) as db:
        db.add(NewsFetchState(source="gdelt", symbol="2330.TW", last_success_at=NOW, last_status="ok", items=0,
                              failures=0))
        db.commit()
        assert not service._ai_due(db, settings, "2330.TW", NOW, gdelt_on=True, searxng_on=True)
        assert service._ai_due(db, settings, "2330.TW", NOW, gdelt_on=True, searxng_on=False)
