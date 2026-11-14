"""The instrument list beyond the built-in catalog (product owner 2026-11-14, pending decisions 1-4 and 1-5):

* every Taiwan ETF the official close files name (TWSE STOCK_DAY_ALL, TPEx daily close quotes; 政府資料開放授權), so
  00679B, 00981A … can be searched and opened;
* SEC's company_tickers.json: US, US$, English names only, no quote under ``commercial``; only English queries reach
  them, and they come after Taiwan unless the ticker matches exactly.

A Chinese question must resolve exactly as before. No network: the close files are the trimmed live fixtures plus a
few ETF rows, the tickers come from the trimmed live company_tickers.json plus a few short tickers.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.ai.tools import ToolContext, ToolError, resolve_instrument, search_instruments
from forliosa.archive import Archiver, upsert
from forliosa.datapolicy import label
from forliosa.marketdata import opendata as od
from forliosa.marketdata.archive_provider import LISTING_DAYS, ArchiveProvider
from forliosa.marketdata.base import BaseProvider
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import LISTINGS_RETRY_SECONDS, MASTER_TTL_SECONDS, MarketData, set_market_data
from forliosa.models import Instrument, SecTicker
from forliosa.services import sec as sec_svc
from forliosa.worker import refresh_instruments
from tests.archive.fakes import NOW, FakeFetcher, FakeSecClient, load

API = "/api/v1"


def _twse(code: str, name: str, close: str = "20.00") -> dict:
    return {"Date": "1151111", "Code": code, "Name": name, "TradeVolume": "1000" if close else "0",
            "TradeValue": "20000", "OpeningPrice": close, "HighestPrice": close, "LowestPrice": close,
            "ClosingPrice": close, "Change": "0.0000" if close else "", "Transaction": "1"}


def _tpex(code: str, name: str, close: str = "26.61") -> dict:
    return {"Date": "1151111", "SecuritiesCompanyCode": code, "CompanyName": name, "Close": close, "Change": "0",
            "Open": close, "High": close, "Low": close, "TradingShares": "1000", "TransactionAmount": "26610",
            "TransactionNumber": "1", "NextReferencePrice": close or "", "NextLimitUp": "", "NextLimitDown": ""}


# Rows added to the live close files: active, bond, mid-cap ETFs, a foreign-currency line (00636K: quoted in US$, left
# out), the built-in 00713 under its close-file name, and a bond ETF that did not trade (no close, still listed).
TWSE_EXTRA = [_twse("00981A", "主動統一台股增長", "24.20"), _twse("0051", "元大中型100", "88.00"),
              _twse("00636K", "國泰中國A50+U", "24.10"), _twse("00713", "元大台灣高息低波", "62.30"),
              _twse("00720B", "元大投資級公司債", "")]
TPEX_EXTRA = [_tpex("00679B", "元大美債20年"), _tpex("006201", "元大富櫃50", "34.85"),
              _tpex("00687B", "國泰20年美債", "----")]
# Short tickers that are also common words or abbreviations.
SEC_EXTRA = [("T", 732717, "AT&T INC."), ("AI", 1577526, "C3.ai, Inc."), ("TSLA", 1318605, "Tesla, Inc."),
             ("K", 55067, "Kellanova"), ("UMC", 1033767, "UNITED MICROELECTRONICS CORP")]


class CloseFiles(FakeFetcher):
    def get_json(self, url, params=None, headers=None):
        rows = super().get_json(url, params, headers)
        if url.endswith("/exchangeReport/STOCK_DAY_ALL"):
            return [*rows, *TWSE_EXTRA]
        if url.endswith("/tpex_mainboard_daily_close_quotes"):
            return [*rows, *TPEX_EXTRA]
        return rows


def archive_closes(db: Session) -> None:
    Archiver(db, CloseFiles(), "commercial", now_fn=lambda: NOW).run(["twse", "tpex"])


def load_tickers(db: Session) -> None:
    sec_svc.refresh_tickers(db, FakeSecClient())  # AAPL NVDA MSFT GOOGL BRK-B JPM TSM (live, trimmed)
    now = datetime.now(UTC)
    upsert(db, SecTicker, [{"ticker": t, "cik": cik, "title": title, "fetched_at": now} for t, cik, title in SEC_EXTRA],
           ["ticker"])


def facade(engine, policy: str = "commercial") -> MarketData:
    return MarketData([ArchiveProvider(policy, session_fn=lambda: Session(engine)), DemoProvider()], policy=policy)


@pytest.fixture()
def listed(engine, market):
    """A commercial facade over an archive that has run the close-file jobs and loaded SEC's ticker file."""
    with Session(engine) as db:
        archive_closes(db)
        load_tickers(db)
    md = facade(engine)
    set_market_data(md)
    yield md
    set_market_data(market)


def symbols(items) -> list[str]:
    return [i.symbol for i in items]


# -- 1-4: every Taiwan ETF ------------------------------------------------------------------------------------------
def test_close_files_name_every_etf_quoted_in_nt_dollars():
    twse = od.parse_listed_etfs([*load("twse_stock_day_all_live_20261112.json"), *TWSE_EXTRA,
                                 {"Code": " 0056 ", "Name": " 元大 高股息 "}, {"Code": "00900", "Name": ""}], "TWSE")
    assert [(e["code"], e["name"]) for e in twse] == [
        ("00400A", "主動國泰動能高息"), ("0050", "元大台灣50"), ("0051", "元大中型100"), ("0056", "元大 高股息"),
        ("00713", "元大台灣高息低波"), ("00720B", "元大投資級公司債"), ("00878", "國泰永續高股息"),
        ("00981A", "主動統一台股增長")]  # stocks, the US$ line 00636K and a row without a name are left out
    tpex = od.parse_listed_etfs([*load("tpex_daily_close_quotes_live_20261112.json"), *TPEX_EXTRA], "TPEX")
    assert [e["code"] for e in tpex] == ["006201", "00679B", "00687B"]
    assert od.is_listed_etf_code("00632R") and od.is_listed_etf_code("00635U") and not od.is_listed_etf_code("2330")


def test_price_jobs_keep_the_etf_rows_current(engine):
    with Session(engine) as db:
        archive_closes(db)
        rows = {r.symbol: r for r in db.scalars(select(Instrument))}
        assert sorted(rows) == ["00400A.TW", "0050.TW", "0051.TW", "006201.TWO", "00679B.TWO", "00687B.TWO",
                                "00713.TW", "00720B.TW", "00878.TW", "00981A.TW"]
        bond = rows["00679B.TWO"]
        assert (bond.code, bond.name, bond.market, bond.type, bond.currency, bond.industry) == (
            "00679B", "元大美債20年", "TPEX", "etf", "TWD", "ETF")
        first = bond.updated_at
        archive_closes(db)  # idempotent; the timestamp says when a close file last named it
        assert db.scalar(select(func.count()).select_from(Instrument)) == 10
        db.expire_all()
        assert db.get(Instrument, "00679B.TWO").updated_at >= first


def test_every_etf_can_be_searched_and_opened(client, listed):
    hits = client.get(f"{API}/instruments/search", params={"q": "00679b"}).json()
    assert hits[0] == {"symbol": "00679B.TWO", "code": "00679B", "name": "元大美債20年", "market": "TPEX",
                       "type": "etf", "currency": "TWD", "industry": "ETF", "has_quote": True}
    assert client.get(f"{API}/instruments/search", params={"q": "主動統一"}).json()[0]["symbol"] == "00981A.TW"
    detail = client.get(f"{API}/instruments/00679B").json()
    assert detail["symbol"] == "00679B.TWO" and detail["type"] == "etf" and detail["is_demo"] is False
    assert detail["data_sources"] == [label("tpex-openapi/price")]
    assert client.get(f"{API}/instruments/00981A.TW").json()["data_sources"] == [label("twse-openapi/price")]
    assert client.get(f"{API}/instruments/00636K").status_code == 404  # the US$ line is not listed
    # the archived close is its quote; the stock page's overview opens
    assert client.get(f"{API}/instruments/00981A/quote").json()["price"] == 24.2
    assert client.get(f"{API}/instruments/00679B.TWO/overview").status_code == 200


def test_built_in_etfs_keep_their_names_and_rank_first(listed):
    md = listed
    assert md.search("0050")[0].symbol == "0050.TW"
    info = md.instrument("0050")
    assert info.source == "built-in" and info.aliases == ("台灣50",)
    assert md.instrument("00713").source == "built-in"  # the close file names it too: the built-in entry wins
    assert md.search("台灣50")[0].symbol == "0050.TW"
    assert md.search("高股息")[0].symbol == "0056.TW"
    # a code prefix: shorter codes first, the built-in ETFs before the close files' ones of the same length
    found = symbols(md.search("00", 30))
    assert found[:3] == ["0050.TW", "0056.TW", "0051.TW"]
    assert found.index("00878.TW") < found.index("00400A.TW") and found.index("006208.TW") < found.index("006201.TWO")
    assert md.resolve("00679b") == "00679B.TWO" and md.resolve("00981A.tw") == "00981A.TW"


def test_an_etf_no_close_file_has_named_for_a_year_drops_out(engine, market):
    with Session(engine) as db:
        archive_closes(db)
        newest = db.scalar(select(func.max(Instrument.updated_at)))
        old = newest - timedelta(days=LISTING_DAYS + 1)
        db.add(Instrument(symbol="00888.TW", code="00888", name="已下市的ETF", market="TWSE", type="etf",
                          currency="TWD", industry="ETF", updated_at=old))
        db.commit()
    md = facade(engine)
    assert md.instrument("00888") is None and md.instrument("00981A") is not None


# -- 1-5: SEC's US tickers ------------------------------------------------------------------------------------------
def test_sec_tickers_join_the_list_in_english_without_a_quote(client, listed):
    md = listed
    msft = md.instrument("msft")
    assert (msft.symbol, msft.name, msft.market, msft.type, msft.currency, msft.industry, msft.aliases) == (
        "MSFT", "MICROSOFT CORP", "US", "stock", "USD", None, ())
    aapl = md.instrument("AAPL")  # the built-in entry keeps its Chinese alias
    assert aapl.name == "Apple" and "蘋果" in aapl.aliases and md.search("蘋果")[0].symbol == "AAPL"
    assert md.resolve("brk.b") == "BRK-B" and md.search("BRK.B")[0].symbol == "BRK-B"
    hit = client.get(f"{API}/instruments/search", params={"q": "microsoft"}).json()[0]
    assert hit["symbol"] == "MSFT" and hit["has_quote"] is False
    detail = client.get(f"{API}/instruments/MSFT").json()
    assert detail["name"] == "MICROSOFT CORP" and detail["has_quote"] is False and detail["is_demo"] is False
    assert detail["data_sources"] == [label("sec-edgar/tickers")] and detail["summary"] is None
    # the stock page renders: no quote, no chart, honest notes; financials wait for SEC (disabled in tests)
    assert client.get(f"{API}/instruments/MSFT/quote").status_code == 404
    history = client.get(f"{API}/instruments/MSFT/history?range=1M").json()
    assert history["candles"] == [] and history["notes"] == ["美股沒有報價"]
    for path in ("overview", "events", "financials", "company", "related", "position", "dividends"):
        assert client.get(f"{API}/instruments/MSFT/{path}").status_code == 200, path
    assert client.get(f"{API}/instruments/2330.TW").json()["has_quote"] is True


def test_personal_mode_marks_us_quotes_as_available(engine, market):
    with Session(engine) as db:
        load_tickers(db)
    md = facade(engine, "personal")
    assert md.has_quote(md.instrument("MSFT")) is True  # demo prices, labelled as such


def test_only_english_queries_reach_sec_and_after_taiwan(listed):
    md = listed
    sec_only = {"MSFT", "GOOGL", "BRK-B", "JPM", "TSM", "T", "AI", "TSLA", "K", "UMC"}
    for q in ("台積", "鴻海", "2330", "0050", "00", "2", "微軟", "高股息"):
        assert not sec_only & set(symbols(md.search(q, 50))), q
    # an exact ticker comes first, even a one-letter one
    for q in ("T", "ai", "MSFT", "TSM", "UMC"):
        assert md.search(q)[0].symbol == q.upper(), q
    assert md.search("UMC")[1].symbol == "2303.TW"  # 聯電's English alias right after the ticker
    # anything weaker than an exact ticker comes after the Taiwan matches: TSMC (2330's alias) before TSM, TSLA
    assert symbols(md.search("TS")) == ["2330.TW", "TSM", "TSLA"]
    assert md.resolve("2330") == "2330.TW" and md.resolve("T") == "T"


def test_chinese_questions_resolve_as_before(listed, engine):
    md = listed
    with Session(engine) as db:
        ctx = ToolContext(db=db, user=None, md=md)  # type: ignore[arg-type]
        for text, sym in (("2330", "2330.TW"), ("台積電", "2330.TW"), ("鴻海", "2317.TW"), ("0050", "0050.TW"),
                          ("元大台灣50", "0050.TW"), ("00679B", "00679B.TWO"), ("NVDA", "NVDA"), ("輝達", "NVDA")):
            assert resolve_instrument(md, text).symbol == sym, text
        for q in ("台積", "鴻海", "台積電和鴻海"):
            assert all(r["market"] != "US" for r in search_instruments(ctx, {"query": q})["results"]), q
        with pytest.raises(ToolError, match="找不到商品"):
            resolve_instrument(md, "微軟")  # no Chinese name for SEC's companies: never a guess


def test_search_reads_no_database_after_the_master_is_built(engine, market):
    with Session(engine) as db:
        archive_closes(db)
        load_tickers(db)
    archive = ArchiveProvider("commercial", session_fn=lambda: Session(engine))
    md = MarketData([archive, DemoProvider()], policy="commercial")
    assert len(md.master()) > 30

    def no_db():
        raise AssertionError("a search must not read the database")

    archive.session_fn = no_db
    assert md.search("MSFT")[0].symbol == "MSFT" and md.search("00679B")[0].symbol == "00679B.TWO"
    assert md.resolve("tsla") == "TSLA" and md.instrument("00981A").name == "主動統一台股增長"


class BrokenListings(BaseProvider):
    name = "broken"

    def listings(self):
        raise RuntimeError("database down")


def test_missing_listings_are_tried_again_soon(market):
    md = MarketData([BrokenListings(), DemoProvider()], policy="commercial")
    assert md.instrument("0050") is not None  # the built-in catalog still answers
    assert md._master_until - time.monotonic() <= LISTINGS_RETRY_SECONDS
    ok = MarketData([DemoProvider()], policy="commercial")
    ok.master()
    assert ok._master_until - time.monotonic() > MASTER_TTL_SECONDS - 60


def test_the_worker_does_not_copy_listings_into_the_cache(listed, engine):
    with Session(engine) as db:
        refresh_instruments(db, listed)
        assert db.get(Instrument, "MSFT") is None and db.get(Instrument, "AAPL") is not None
        assert db.get(Instrument, "00679B.TWO").name == "元大美債20年"
        assert db.get(Instrument, "0050.TW").name == "元大台灣50"
