"""The news batch, storage, retention, the takedown blocklist, the AI fallback's budget and the /news read path."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.datapolicy import attributions, dataset_served, label
from forliosa.models import AiUsage, NewsArticle, NewsBlockedDomain, NewsFetchState, NewsTrackedView, WatchlistItem
from forliosa.news import __main__ as cli
from forliosa.news import service
from forliosa.news.ai_search import RESERVE_USD, month_spend
from forliosa.news.sources import GdeltSource, RawItem, SearxngSource, YahooRssSource, parse_gdelt
from forliosa.timeutil import now_utc
from tests.ai.fake_anthropic import server_tool_use, tool_use
from tests.news.conftest import FETCHED_AT, FakeSource, fixture_bytes

API = "/api/v1"
NOW = FETCHED_AT


def gdelt_items() -> list[RawItem]:
    return parse_gdelt(fixture_bytes("gdelt_tsmc_taiwan_live_20261112.json"))


def stored(db: Session, symbol: str = "2330.TW") -> list[NewsArticle]:
    return list(db.scalars(select(NewsArticle).where(NewsArticle.symbol == symbol)
                           .order_by(NewsArticle.published_at.desc())))


# -- sources on / off -------------------------------------------------------------------------------------------
def test_only_gdelt_is_on_by_default(settings):
    srcs = service.default_sources(settings, "commercial")
    assert [type(s) for s in srcs] == [GdeltSource]  # SearXNG off, Yahoo RSS off (commercial)
    personal = service.default_sources(settings, "personal")
    assert [type(s) for s in personal] == [GdeltSource, YahooRssSource]  # Yahoo only under DATA_POLICY=personal
    with_searx = service.default_sources(settings.model_copy(update={"news_searxng_url": "https://searx.example.org"}),
                                         "commercial")
    assert [type(s) for s in with_searx] == [GdeltSource, SearxngSource]
    off = settings.model_copy(update={"news_gdelt_enabled": False, "news_yahoo_rss": False})
    assert service.default_sources(off, "personal") == []
    assert settings.news_ai_budget_usd == 30.0 and settings.news_searxng_url is None


def test_news_fetcher_spaces_gdelt_and_allows_only_the_configured_searxng(settings):
    f = service.news_fetcher(settings.model_copy(update={"news_searxng_url": "https://searx.example.org"}))
    try:
        assert f.limiter.interval_for("api.gdeltproject.org") >= 5.0
        assert f.limiter.interval_for("searx.example.org") >= 3.0
        assert f.extra_allowed == ("https://searx.example.org/search",)
        assert "Mozilla" not in f.client.headers["User-Agent"]  # an honest client name
    finally:
        f.client.close()


# -- the batch ---------------------------------------------------------------------------------------------------
def test_refresh_stores_normalised_relevant_headlines_once(engine, commercial_md, settings):
    src = FakeSource(items={"2330.TW": gdelt_items()})
    with Session(engine) as db:
        rep = service.refresh(db, commercial_md, settings=settings, sources=[src], ai=None, symbols=["2330.TW"],
                              now_fn=lambda: NOW)
        assert rep.symbols == 1 and rep.fetched == {"gdelt": 1} and rep.stored == 13
        rows = stored(db)
        assert len(rows) == 13 and rows[0].title == "台積電CPO霸主地位穩了？法人看好2027年EPS估達151元"
        assert rows[0].outlet == "新頭殼" and rows[0].source == "gdelt" and not rows[0].date_only
        # metadata only: no column could hold article text, a description or an image
        assert set(NewsArticle.__table__.columns.keys()) == {
            "id", "symbol", "url_key", "url", "title", "outlet", "domain", "published_at", "date_only", "source",
            "fetched_at"}
        q = src.calls[0]
        assert q.english == ("TSMC",) and q.since == NOW - timedelta(days=7)  # the master's alias
        st = db.get(NewsFetchState, ("gdelt", "2330.TW"))
        assert st.last_status == "ok" and st.items == 13 and st.last_success_at is not None
        # second run: asks only since the last success (minus an hour) and stores nothing twice
        later = NOW + timedelta(minutes=45)
        rep2 = service.refresh(db, commercial_md, settings=settings, sources=[src], ai=None, symbols=["2330.TW"],
                               now_fn=lambda: later)
        assert rep2.stored == 0 and len(stored(db)) == 13
        assert src.calls[1].since == NOW - timedelta(hours=1)


def test_english_short_name_comes_from_the_company_profile(engine, commercial_md):
    from forliosa.models import CompanyProfile

    with Session(engine) as db:
        db.add(CompanyProfile(symbol="2330.TW", date=NOW.date(), values={"english_short_name": "TSMC"},
                              source="twse-openapi"))
        db.commit()
        q = service.build_query(db, commercial_md.instrument("2330.TW"), NOW - timedelta(days=7), NOW)
        assert q.english == ("TSMC",) and "TSMC" in q.terms.names and q.terms.codes == ("2330",)


def test_rate_limit_stops_the_source_and_backs_off(engine, commercial_md, settings):
    blocked = FakeSource(blocked=True)
    with Session(engine) as db:
        rep = service.refresh(db, commercial_md, settings=settings, sources=[blocked], ai=None,
                              symbols=["2330.TW", "2454.TW", "0050.TW"], now_fn=lambda: NOW)
        assert len(blocked.calls) == 1  # no further GDELT request in this run
        assert rep.blocked_sources == ["gdelt"]
        wide = db.get(NewsFetchState, ("gdelt", service.SOURCE_WIDE))
        assert wide.failures == 1 and wide.backoff_until.replace(tzinfo=UTC) == NOW + timedelta(minutes=15)
        # inside the backoff: not asked at all
        service.refresh(db, commercial_md, settings=settings, sources=[blocked], ai=None, symbols=["2330.TW"],
                        now_fn=lambda: NOW + timedelta(minutes=10))
        assert len(blocked.calls) == 1
        # after it: asked again; a second refusal doubles the wait
        service.refresh(db, commercial_md, settings=settings, sources=[blocked], ai=None, symbols=["2330.TW"],
                        now_fn=lambda: NOW + timedelta(minutes=20))
        wide = db.get(NewsFetchState, ("gdelt", service.SOURCE_WIDE))
        assert len(blocked.calls) == 2 and wide.failures == 2
        assert wide.backoff_until.replace(tzinfo=UTC) == NOW + timedelta(minutes=20 + 30)
        # recovery resets the backoff
        ok = FakeSource(items={"2330.TW": gdelt_items()})
        service.refresh(db, commercial_md, settings=settings, sources=[ok], ai=None, symbols=["2330.TW"],
                        now_fn=lambda: NOW + timedelta(hours=2))
        wide = db.get(NewsFetchState, ("gdelt", service.SOURCE_WIDE))
        assert wide.failures == 0 and wide.backoff_until is None


def test_searxng_backs_off_longer(engine, commercial_md, settings):
    searx = FakeSource(key="searxng", label="SearXNG", blocked=True)
    with Session(engine) as db:
        service.refresh(db, commercial_md, settings=settings, sources=[searx], ai=None, symbols=["2330.TW"],
                        now_fn=lambda: NOW)
        wide = db.get(NewsFetchState, ("searxng", service.SOURCE_WIDE))
        assert wide.backoff_until.replace(tzinfo=UTC) == NOW + timedelta(minutes=settings.news_searxng_backoff_minutes)


def test_repeated_errors_skip_the_source_for_the_run(engine, commercial_md, settings):
    broken = FakeSource(error=ConnectionError("reset by peer"))
    with Session(engine) as db:
        rep = service.refresh(db, commercial_md, settings=settings, sources=[broken], ai=None,
                              symbols=["2330.TW", "2454.TW", "0050.TW", "2317.TW", "2303.TW"], now_fn=lambda: NOW)
        assert len(broken.calls) == service.MAX_FAILURES_PER_RUN and rep.errors == 3
        assert db.get(NewsFetchState, ("gdelt", "2330.TW")).last_status == "error"


def test_tracked_symbols_held_watched_or_recently_viewed(engine, client, settings):
    assert client.post(f"{API}/watchlist", json={"symbol": "0050"}).status_code in (200, 201)
    with Session(engine) as db:
        assert db.scalars(select(WatchlistItem.symbol)).all() == ["0050.TW"]
        db.add(NewsTrackedView(symbol="2454.TW", last_viewed_at=NOW - timedelta(days=1)))
        db.add(NewsTrackedView(symbol="2317.TW", last_viewed_at=NOW - timedelta(days=5)))  # too long ago
        db.commit()
        syms = service.tracked(db, settings, NOW)
        assert "2454.TW" in syms and "0050.TW" in syms and "2317.TW" not in syms


def test_blocklist_hides_deletes_and_stops_storing(engine, commercial_md, settings, monkeypatch):
    src = FakeSource(items={"2330.TW": gdelt_items()})
    with Session(engine) as db:
        service.refresh(db, commercial_md, settings=settings, sources=[src], ai=None, symbols=["2330.TW"],
                        now_fn=lambda: NOW)
        assert any(r.domain.endswith("ltn.com.tw") for r in stored(db))
        assert service.block_domain(db, "ltn.com.tw", "2026-11-20 來函要求下架") == 2  # news. and ec. subdomains
        assert not any("ltn.com.tw" in r.url for r in stored(db))
        assert db.get(NewsBlockedDomain, "ltn.com.tw").reason == "2026-11-20 來函要求下架"
        service.refresh(db, commercial_md, settings=settings, sources=[src], ai=None, symbols=["2330.TW"],
                        now_fn=lambda: NOW + timedelta(hours=1))
        assert not any("ltn.com.tw" in r.url for r in stored(db))  # never stored again
        # the environment list hides too (rows stay until the domain is blocked in the table)
        env = settings.model_copy(update={"news_blocked_domains": ["udn.com"]})
        items = service.media_items(db, commercial_md, commercial_md.instrument("2330"), settings=env, now=NOW)
        assert items and not any("udn.com" in i["url"] for i in items)
        assert service.unblock_domain(db, "ltn.com.tw") and not service.unblock_domain(db, "ltn.com.tw")


def test_blocklist_cli(engine, commercial_md, settings, capsys):
    with Session(engine) as db:
        service.refresh(db, commercial_md, settings=settings, sources=[FakeSource(items={"2330.TW": gdelt_items()})],
                        ai=None, symbols=["2330.TW"], now_fn=lambda: NOW)
    assert cli.main(["block", "https://www.setn.com/", "--reason", "來函"]) == 0
    assert "已封鎖" in capsys.readouterr().out
    assert cli.main(["blocked"]) == 0
    assert "setn.com（來函）" in capsys.readouterr().out
    with Session(engine) as db:
        assert not any("setn.com" in r.url for r in stored(db))
    assert cli.main(["unblock", "setn.com"]) == 0 and "已移除" in capsys.readouterr().out


def test_retention_deletes_old_headlines(engine, settings):
    with Session(engine) as db:
        service.store(db, "2330.TW", [
            service.Headline("台積電舊聞", "https://udn.com/old", "聯合新聞網", "udn.com", NOW - timedelta(days=31),
                             "gdelt"),
            service.Headline("台積電新聞", "https://udn.com/new", "聯合新聞網", "udn.com", NOW - timedelta(days=2),
                             "gdelt")], NOW)
        assert service.purge(db, settings, NOW) == 1
        assert [r.title for r in stored(db)] == ["台積電新聞"]


# -- AI fallback --------------------------------------------------------------------------------------------------
def ai_answer(fake, results: list[tuple[str, str, str | None]], urls: list[str]) -> None:
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "台積電 新聞"}),
               {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1",
                "content": [{"type": "web_search_result", "url": u, "title": t, "page_age": a,
                             "encrypted_content": "E"} for u, t, a in results]},
               tool_use("toolu_n", "report_news", {"urls": urls}),
               stop_reason="tool_use", usage={"server_tool_use": {"web_search_requests": 1}})


AI_RESULTS = [
    ("https://money.udn.com/money/story/5612/9100001", "台積電熊本二廠將導入3奈米 | 經濟日報",
     "2026-11-12T08:30:00+08:00"),
    ("https://www.cna.com.tw/news/afe/202611110123.aspx", "台積電美國廠進度超前 | 產經 | 中央社 CNA",
     "November 11, 2026"),
    ("https://tw.stock.yahoo.com/quote/2330.TW", "台積電(2330) 走勢圖 - Yahoo股市", None),  # a quote page
    ("https://www.ctee.com.tw/news/20261101700001", "台積電上月舊聞", "2026-11-01"),  # outside 7 days
]


def test_ai_fills_gaps_only_from_search_results(engine, commercial_md, settings, pool, fake):
    gdelt = FakeSource(items={"2330.TW": gdelt_items()[:3]})  # only 1 relevant headline in 7 days
    ai_answer(fake, AI_RESULTS, [u for u, _, _ in AI_RESULTS] + ["https://made-up.example.com/台積電"])
    with Session(engine) as db:
        rep = service.refresh(db, commercial_md, settings=settings, sources=[gdelt], symbols=["2330.TW"],
                              now_fn=lambda: NOW)
        assert rep.ai_searches == 1 and len(fake.requests) == 1
        body = fake.requests[0]["body"]
        tools = {t["name"]: t for t in body["tools"]}
        assert set(tools) == {"web_search", "report_news"}  # no web_fetch: no site is read
        assert "www.twse.com.tw" in tools["web_search"]["blocked_domains"]
        ai_rows = [r for r in stored(db) if r.source == "ai_search"]
        # titles, links and dates are the search results' own; the made-up URL, the quote page and the old article
        # are dropped
        assert sorted((r.title, r.outlet, r.date_only) for r in ai_rows) == [
            ("台積電熊本二廠將導入3奈米", "經濟日報", False), ("台積電美國廠進度超前", "中央社", True)]
        usage = list(db.scalars(select(AiUsage)))
        assert len(usage) == 1 and usage[0].feature == "news" and usage[0].user_id is None
        assert usage[0].web_search_requests == 1 and usage[0].cost_usd > 0
        # not again within NEWS_AI_INTERVAL_HOURS
        rep2 = service.refresh(db, commercial_md, settings=settings, sources=[gdelt], symbols=["2330.TW"],
                               now_fn=lambda: NOW + timedelta(hours=1))
        assert rep2.ai_searches == 0 and len(fake.requests) == 1


def test_ai_is_not_used_when_gdelt_has_enough_or_did_not_answer(engine, commercial_md, settings, pool, fake):
    with Session(engine) as db:
        enough = FakeSource(items={"2330.TW": gdelt_items()})
        rep = service.refresh(db, commercial_md, settings=settings, sources=[enough], symbols=["2330.TW"],
                              now_fn=lambda: NOW)
        assert rep.ai_searches == 0
        failing = FakeSource(blocked=True)  # GDELT did not answer for 2454: no AI search instead of it
        rep = service.refresh(db, commercial_md, settings=settings, sources=[failing], symbols=["2454.TW"],
                              now_fn=lambda: NOW)
        assert rep.ai_searches == 0 and fake.requests == []
        off = settings.model_copy(update={"news_ai_enabled": False})
        empty = FakeSource(items={})
        rep = service.refresh(db, commercial_md, settings=off, sources=[empty], symbols=["2303.TW"],
                              now_fn=lambda: NOW + timedelta(hours=5))
        assert rep.ai_searches == 0 and fake.requests == []


def test_monthly_budget_caps_the_ai_search(engine, commercial_md, settings, pool, fake):
    with Session(engine) as db:
        db.add(AiUsage(user_id=None, thread_id="nws_old", feature="news", model="claude-haiku-5-5", key_slot=1,
                       cost_usd=Decimal("29.96"), created_at=NOW - timedelta(days=3)))
        db.add(AiUsage(user_id=None, thread_id="nws_last_month", feature="news", model="claude-haiku-5-5",
                       key_slot=1, cost_usd=Decimal("50"), created_at=datetime(2026, 10, 31, 12, tzinfo=UTC)))
        db.add(AiUsage(user_id=None, thread_id="chat", feature="chat", model="claude-haiku-5-5", key_slot=1,
                       cost_usd=Decimal("5"), created_at=NOW - timedelta(days=1)))
        db.commit()
        assert month_spend(db, NOW) == Decimal("29.96")  # this UTC month, feature "news" only
        rep = service.refresh(db, commercial_md, settings=settings, sources=[FakeSource(items={})],
                              symbols=["2330.TW"], now_fn=lambda: NOW)
        assert rep.ai_searches == 0 and rep.ai_skipped == "budget" and fake.requests == []
        # a larger cap leaves room for one more search (each needs RESERVE_USD of headroom)
        roomy = settings.model_copy(update={"news_ai_budget_usd": float(Decimal("29.96") + RESERVE_USD)})
        ai_answer(fake, AI_RESULTS[:1], [AI_RESULTS[0][0]])
        rep = service.refresh(db, commercial_md, settings=roomy, sources=[FakeSource(items={})], symbols=["2330.TW"],
                              now_fn=lambda: NOW + timedelta(hours=1))
        assert rep.ai_searches == 1


def test_ai_unavailable_without_keys(engine, commercial_md, settings):
    with Session(engine) as db:  # the autouse fixture installs an empty key pool
        rep = service.refresh(db, commercial_md, settings=settings, sources=[FakeSource(items={})],
                              symbols=["2330.TW"], now_fn=lambda: NOW)
        assert rep.ai_searches == 0 and rep.ai_skipped == "unavailable"
        # ai=None: no AI fallback in this run at all (nothing is checked)
        rep = service.refresh(db, commercial_md, settings=settings, sources=[FakeSource(items={})], ai=None,
                              symbols=["2454.TW"], now_fn=lambda: NOW)
        assert rep.ai_searches == 0 and rep.ai_skipped is None


# -- the read path -----------------------------------------------------------------------------------------------
def test_news_endpoint_lists_media_after_announcements(client, engine, commercial_md):
    now = now_utc()
    with Session(engine) as db:
        service.store(db, "2330.TW", [
            service.Headline("台積電CPO霸主地位穩了？", "https://newtalk.tw/news/view/2026-11-12/1", "新頭殼",
                             "newtalk.tw", now - timedelta(hours=3), "gdelt"),
            service.Headline("台積電美國廠進度超前", "https://www.cna.com.tw/news/afe/1.aspx", "中央社", "cna.com.tw",
                             now - timedelta(days=1), "ai_search", date_only=True),
            service.Headline("台積電 Yahoo 轉載", "https://tw.stock.yahoo.com/news/1", "MoneyDJ", "tw.stock.yahoo.com",
                             now - timedelta(hours=1), "yahoo_rss"),
        ], now)
    r = client.get(f"{API}/instruments/2330/news")
    assert r.status_code == 200
    media = [n for n in r.json() if n["category"] == "media"]
    assert media[0] == {
        "published_at": media[0]["published_at"], "title": "台積電CPO霸主地位穩了？", "source": "GDELT",
        "outlet": "新頭殼", "url": "https://newtalk.tw/news/view/2026-11-12/1", "category": "media",
        "date_only": False, "sources": [label("gdelt/doc")]}
    assert "gdeltproject.org" in media[0]["sources"][0]
    assert media[1]["source"] == "AI 搜尋" and media[1]["date_only"] is True
    assert not any(n["source"] == "Yahoo股市" for n in media)  # Yahoo RSS rows: personal only
    with Session(engine) as db:  # the view is noted: symbol and time only
        view = db.get(NewsTrackedView, "2330.TW")
        assert view is not None and set(NewsTrackedView.__table__.columns.keys()) == {"symbol", "last_viewed_at"}


def test_yahoo_rss_rows_are_shown_only_under_personal(client, engine, personal_md):
    now = now_utc()
    with Session(engine) as db:
        service.store(db, "2330.TW", [service.Headline(
            "員工個資外洩？台積電：無證據顯示系統遭入侵", "https://tw.stock.yahoo.com/news/a-1.html", "MoneyDJ",
            "tw.stock.yahoo.com", now - timedelta(hours=1), "yahoo_rss")], now)
    media = [n for n in client.get(f"{API}/instruments/2330/news").json() if n["category"] == "media"]
    assert [(n["source"], n["outlet"]) for n in media] == [("Yahoo股市", "MoneyDJ")]
    assert media[0]["sources"][0].endswith("（非商用）")


def test_us_stocks_get_media_only(client, engine, commercial_md):
    now = now_utc()
    with Session(engine) as db:
        service.store(db, "NVDA", [service.Headline("Why NVDA fell today", "https://www.reuters.com/x", "Reuters",
                                                    "reuters.com", now - timedelta(hours=2), "gdelt")], now)
    n = client.get(f"{API}/instruments/NVDA/news").json()
    assert [(x["category"], x["outlet"]) for x in n] == [("media", "Reuters")]


# -- attribution and worker --------------------------------------------------------------------------------------
def test_attributions_name_gdelt_and_keep_yahoo_personal_only():
    com = attributions("commercial", confirmed=True)
    keys = {d["key"]: d for d in com["datasets"]}
    assert keys["gdelt/doc"]["commercial"] is True and "gdeltproject.org" in keys["gdelt/doc"]["attribution"]
    assert "yahoo-rss/stock" not in keys and not any(d["key"] == "yahoo-rss/stock" for d in com["conditional"])
    assert any("Yahoo股市 RSS" in s for s in com["not_used"]) and any("GDELT" in s for s in com["notice"])
    per = {d["key"]: d for d in attributions("personal", confirmed=True)["datasets"]}
    yahoo = per["yahoo-rss/stock"]
    assert yahoo["commercial"] is False and yahoo["attribution"].endswith("（非商用）")
    assert not dataset_served("yahoo-rss/stock", "commercial") and dataset_served("yahoo-rss/stock", "personal")
    assert dataset_served("gdelt/doc", "commercial")


def test_worker_runs_the_news_job(settings):
    from forliosa.worker import Worker

    job = next(j for j in Worker(md=object()).jobs if j.name == "news_refresh")  # type: ignore[arg-type]
    assert job.due(NOW, None) and not job.due(NOW, NOW - timedelta(minutes=30))
    assert job.due(NOW, NOW - timedelta(minutes=settings.news_refresh_minutes))
