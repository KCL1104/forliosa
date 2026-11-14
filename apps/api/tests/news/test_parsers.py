"""Source parsers on trimmed live responses (2026-11-12) and the queries we send; no network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from forliosa.marketdata.base import ProviderUnavailable
from forliosa.marketdata.http import HttpFetcher, HttpStatusError, url_allowed
from forliosa.news.normalize import make_terms
from forliosa.news.sources import (
    GdeltSource,
    Query,
    RawItem,
    SourceBlocked,
    YahooRssSource,
    gdelt_query,
    parse_gdelt,
    parse_yahoo_rss,
    yahoo_outlet,
)
from tests.news.conftest import FETCHED_AT, fixture_bytes

NOW = FETCHED_AT


def query(code="2330", name="台積電", market="TWSE", english=("TSMC",), symbol=None) -> Query:
    return Query(symbol or f"{code}.TW", code, name, market, tuple(english), make_terms(name, code, english),
                 NOW - timedelta(days=7), NOW)


# -- GDELT ---------------------------------------------------------------------------------------------------
def test_gdelt_artlist_fixture():
    items = parse_gdelt(fixture_bytes("gdelt_tsmc_taiwan_live_20261112.json"))
    assert len(items) == 17
    first = items[0]
    assert first.url == "https://www.cna.com.tw:443/postwrite/chi/449796"  # port removed later (clean_url)
    assert first.published_at == datetime(2026, 11, 12, 7, 0, tzinfo=UTC)  # seendate 20261112T070000Z
    assert first.domain == "cna.com.tw"
    # only title, link, time and the domain hint are read: no image, no mobile link, no description
    assert set(RawItem.__dataclass_fields__) == {"title", "url", "published_at", "date_only", "outlet", "domain"}
    assert all("socialimage" not in repr(i) and "imgcdn" not in repr(i) for i in items)


def test_gdelt_errors_and_empty_answers():
    with pytest.raises(SourceBlocked):  # the 429 body (GDELT sometimes sends it with HTTP 200)
        parse_gdelt(fixture_bytes("gdelt_rate_limited_live_20261112.txt"))
    assert parse_gdelt(b"{}") == []  # no results
    with pytest.raises(ProviderUnavailable) as exc:
        parse_gdelt(b"The specified phrase is too short.")
    assert not isinstance(exc.value, SourceBlocked)
    # bad rows are skipped, not fatal
    assert parse_gdelt({"articles": [{"title": "x"}, {"url": "https://a.tw/1", "title": "t", "seendate": "bad"}]}) == []


def test_gdelt_query_is_english_with_the_country_or_language_filter():
    assert gdelt_query(query()) == "(TSMC OR 2330) sourcecountry:taiwan"
    assert gdelt_query(query("2317", "鴻海", english=("HON HAI",))) == '("HON HAI" OR 2317) sourcecountry:taiwan'
    assert gdelt_query(query("1538", "正峰", english=("JF",))) == "1538 sourcecountry:taiwan"  # too short
    # an everyday word would fill the 75 records with other news: the code finds the stock's own articles
    assert gdelt_query(query("3105", "穩懋", english=("WIN",), symbol="3105.TWO", market="TPEX")) == \
        "3105 sourcecountry:taiwan"
    assert gdelt_query(query("2308", "台達電", english=("DELTA",))) == "2308 sourcecountry:taiwan"
    # US stocks: English, from US and UK outlets only (FIPS codes in an OR group; checked live 2026-11-14)
    us = query("NVDA", "NVIDIA", "US", ("NVIDIA",), symbol="NVDA")
    assert gdelt_query(us) == "(NVIDIA OR NVDA) (sourcecountry:US OR sourcecountry:UK) sourcelang:english"


def test_us_news_comes_from_us_and_uk_outlets_only():
    """The 2026-11-12 answer to ``sourcelang:english`` alone was mostly reprints from India, Australia, Singapore…;
    the 2026-11-14 answer to the US/UK query has only those two. A US query also drops any other country GDELT
    names in ``sourcecountry`` (a second check); a Taiwan query is not filtered by country here."""
    us = query("NVDA", "NVIDIA", "US", ("NVIDIA",), symbol="NVDA")
    f = RecordingFetcher(fixture_bytes("gdelt_nvda_us_uk_live_20261114.json"))
    items = GdeltSource(f).fetch(us)
    assert f.calls[0][1]["query"] == "(NVIDIA OR NVDA) (sourcecountry:US OR sourcecountry:UK) sourcelang:english"
    assert len(items) == 8 and {i.domain for i in items} >= {"theguardian.com", "bostonglobe.com"}
    # the old, unfiltered answer: only its US and UK rows would survive
    old = fixture_bytes("gdelt_nvda_english_live_20261112.json")
    kept = GdeltSource(RecordingFetcher(old)).fetch(us)
    assert len(parse_gdelt(old)) == 16 and len(kept) == 4  # India, Australia, China, Singapore… dropped
    assert not {i.domain for i in kept} & {"businesstimes.com.sg"}
    assert parse_gdelt({"articles": [{"title": "t", "url": "https://x.com/1", "seendate": "20261112T070000Z"}]},
                       frozenset({"United States"}))  # no sourcecountry field: kept
    tw = GdeltSource(RecordingFetcher(fixture_bytes("gdelt_tsmc_taiwan_live_20261112.json"))).fetch(query())
    assert len(tw) == 17


class RecordingFetcher(HttpFetcher):
    def __init__(self, payload: bytes = b"{}", status: int | None = None):
        self.payload, self.status = payload, status
        self.calls: list[tuple[str, dict]] = []

    def get_bytes(self, url, params=None, headers=None):
        self.calls.append((url, dict(params or {})))
        if self.status:
            raise HttpStatusError(f"HTTP {self.status}", self.status)
        return self.payload

    def get_json(self, url, params=None, headers=None):
        import json

        return json.loads(self.get_bytes(url, params, headers))


def test_gdelt_source_request_and_refusals():
    f = RecordingFetcher(fixture_bytes("gdelt_tsmc_taiwan_live_20261112.json"))
    items = GdeltSource(f).fetch(query())
    assert len(items) == 17
    url, params = f.calls[0]
    assert url == "https://api.gdeltproject.org/api/v2/doc/doc" and url_allowed(url)
    assert params["mode"] == "artlist" and params["format"] == "json" and params["sort"] == "datedesc"
    assert params["startdatetime"] == "20261105104500" and params["enddatetime"] == "20261112104500"
    for status in (429, 403):
        with pytest.raises(SourceBlocked):
            GdeltSource(RecordingFetcher(status=status)).fetch(query())
    with pytest.raises(HttpStatusError):  # 404 is not a block
        GdeltSource(RecordingFetcher(status=404)).fetch(query())


# -- Yahoo股市 RSS ----------------------------------------------------------------------------------------------
def test_yahoo_rss_fixture_names_the_original_outlet():
    items = parse_yahoo_rss(fixture_bytes("yahoo_rss_2330_live_20261112.xml"))
    assert len(items) == 8
    by_title = {i.title: i for i in items}
    assert by_title["員工個資外洩？台積電：無證據顯示系統遭入侵"].outlet == "MoneyDJ"
    assert by_title["統一期貨：指數開高走低重挫，玻纖布、CCL及金融股逆勢抗跌"].outlet == "財訊快報"
    assert items[0].outlet is None  # 「財經中心／…」 names no outlet: shown as Yahoo股市
    assert items[0].published_at == datetime(2026, 11, 12, 10, 44, 39, tzinfo=UTC)
    assert all(i.url.startswith("https://tw.stock.yahoo.com/news/") for i in items)
    assert yahoo_outlet("（中央社記者何秀玲台北") == "中央社" and yahoo_outlet(None) is None


def test_yahoo_rss_source_is_taiwan_only_and_allowlisted():
    f = RecordingFetcher(fixture_bytes("yahoo_rss_2330_live_20261112.xml"))
    src = YahooRssSource(f)
    assert src.supports(query()) and not src.supports(query("NVDA", "NVIDIA", "US", ("NVIDIA",), symbol="NVDA"))
    assert len(src.fetch(query())) == 8
    url, params = f.calls[0]
    assert url_allowed(url) and params == {"s": "2330"}
    with pytest.raises(SourceBlocked):
        YahooRssSource(RecordingFetcher(status=429)).fetch(query())
    with pytest.raises(ProviderUnavailable):
        parse_yahoo_rss(b"<html>not rss")


# -- allowlist ---------------------------------------------------------------------------------------------------
def test_fetcher_allowlist_for_news():
    assert url_allowed("https://api.gdeltproject.org/api/v2/doc/doc")
    assert url_allowed("https://tw.stock.yahoo.com/rss")
    assert not url_allowed("https://news.cnyes.com/news/id/1")  # news sites are never fetched
    assert not url_allowed("https://www.twse.com.tw/zh/news/newsList.html")
    f = HttpFetcher(extra_allowed=("https://searx.example.org/search",))
    try:
        with pytest.raises(ProviderUnavailable):
            f.get_bytes("https://searx.example.org/other")  # rejected before any request
    finally:
        f.client.close()
