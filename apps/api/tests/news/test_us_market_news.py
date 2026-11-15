"""US market headlines for the market page (產品負責人 2026-11-15): one GDELT request per refresh under the key "^US",
English US / UK outlets, the market words as the relevance test, served by ``market_items`` and in the overview."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.models import NewsArticle, NewsBlockedDomain
from forliosa.news import service
from forliosa.news.sources import RawItem, gdelt_query
from tests.news.conftest import FETCHED_AT, FakeSource


def item(title: str, url: str, hours: int = 2) -> RawItem:
    return RawItem(title=title, url=url, published_at=FETCHED_AT - timedelta(hours=hours), domain=url.split("/")[2])


def test_the_market_query_reads_like_a_us_query():
    q = service.market_query(FETCHED_AT - timedelta(days=7), FETCHED_AT)
    assert gdelt_query(q) == ('("Wall Street" OR "S&P 500" OR "Dow Jones" OR Nasdaq) '
                              '(sourcecountry:US OR sourcecountry:UK) sourcelang:english')
    assert q.symbol == service.US_MARKET_KEY and not q.taiwan


def test_one_request_per_run_stored_under_the_market_key(engine, commercial_md, settings):
    gdelt = FakeSource(items={service.US_MARKET_KEY: [
        item("Wall Street closes higher as Nasdaq leads tech rally", "https://www.reuters.com/markets/us/a"),
        item("Recipe: the best apple pie", "https://www.example.com/pie"),  # names no market word: left out
        item("S&P 500 slips after Fed minutes", "https://www.cnbc.com/2026/11/12/b.html", hours=5)]})
    with Session(engine) as db:
        db.add(NewsBlockedDomain(domain="cnbc.com", reason="測試"))
        db.commit()
        rep = service.refresh(db, commercial_md, settings=settings, sources=[gdelt], ai=None,
                              now_fn=lambda: FETCHED_AT)
        assert [q.symbol for q in gdelt.calls].count(service.US_MARKET_KEY) == 1
        rows = list(db.scalars(select(NewsArticle).where(NewsArticle.symbol == service.US_MARKET_KEY)))
        assert [r.title for r in rows] == ["Wall Street closes higher as Nasdaq leads tech rally"]  # blocked: cnbc
        items = service.market_items(db, commercial_md, settings=settings, now=FETCHED_AT)
        assert [i["title"] for i in items] == ["Wall Street closes higher as Nasdaq leads tech rally"]
        assert items[0]["url"].startswith("https://www.reuters.com/")
    assert rep.fetched["gdelt"] >= 1


def test_a_test_or_cli_list_of_symbols_asks_no_market_news(engine, commercial_md, settings):
    gdelt = FakeSource()
    with Session(engine) as db:
        service.refresh(db, commercial_md, settings=settings, sources=[gdelt], ai=None, symbols=[],
                        now_fn=lambda: FETCHED_AT)
    assert gdelt.calls == []
    off = settings.model_copy(update={"news_us_market": False})
    with Session(engine) as db:
        service.refresh(db, commercial_md, settings=off, sources=[gdelt], ai=None, now_fn=lambda: FETCHED_AT)
    assert service.US_MARKET_KEY not in [q.symbol for q in gdelt.calls]


def test_a_refusal_on_the_market_query_pauses_gdelt_for_the_run(engine, commercial_md, settings):
    gdelt = FakeSource(blocked=True)
    with Session(engine) as db:
        rep = service.refresh(db, commercial_md, settings=settings, sources=[gdelt], ai=None,
                              now_fn=lambda: FETCHED_AT)
    assert len(gdelt.calls) == 1 and "gdelt" in rep.blocked_sources
