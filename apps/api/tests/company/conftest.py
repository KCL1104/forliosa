"""Stock-page fixtures: an archive built from the trimmed live open-data fixtures (company profiles, 董監事持股餘額明細,
富櫃五十, TDCC 2-22 / 2-23, fund profiles, foreign top 20) plus a month of synthetic closes for the related-stocks
universe, served by a commercial facade; and a fake Wikimedia fetcher over trimmed live Wikidata / zh.wikipedia
answers (2026-11-12). No test reaches the network."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import unquote

import pytest
from sqlalchemy.orm import Session

from forliosa.archive import Archiver, upsert
from forliosa.marketdata import opendata as od
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.base import BaseProvider, InstrumentInfo, tw_symbol
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.http import HttpStatusError
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import CompanyProfile, FundProfile, PriceDaily
from forliosa.timeutil import TAIPEI
from tests.archive.fakes import FakeFetcher
from tests.archive.fakes import load as load_archive

FIX = Path(__file__).parent / "fixtures"
EVENING = datetime(2026, 11, 12, 21, 45, tzinfo=TAIPEI)
LAST = date(2026, 11, 11)
# Rounded closes (NT$) for the universe: market caps decide the peers (shares from the live t187ap03 rows).
CLOSES = {
    "2330.TW": 1450, "2454.TW": 1400, "3711.TW": 200, "2303.TW": 45, "3443.TW": 2000, "6770.TW": 30,
    "6789.TW": 300, "2317.TW": 230, "2258.TW": 60, "2328.TW": 40, "2354.TW": 120, "2308.TW": 1000, "1101.TW": 25,
    "3105.TWO": 150, "3374.TWO": 150, "5347.TWO": 100, "5483.TWO": 120, "6488.TWO": 400,
    "0050.TW": 60, "006208.TW": 140, "0056.TW": 36, "00878.TW": 21, "00919.TW": 22, "00692.TW": 50,
    "006203.TW": 100, "006201.TWO": 35,
}


def load(name: str) -> Any:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _closes(db: Session) -> None:
    rows = []
    for sym, close in CLOSES.items():
        for i in range(25):
            d = LAST - timedelta(days=24 - i)
            if d.weekday() >= 5:
                continue
            c = D(close) * (D(1) + D(i - 24) / D(400))  # a gentle month-long rise
            rows.append({"symbol": sym, "date": d, "open": c, "high": c, "low": c, "close": c, "volume": 1000,
                         "source": "tpex-openapi" if sym.endswith(".TWO") else "twse-openapi"})
    upsert(db, PriceDaily, rows, ["symbol", "date"])


# Instruments the demo catalog does not name (the production master comes from shioaji-data / the OpenAPIs).
UNIVERSE = {"3443.TW": "創意", "6770.TW": "力積電", "6789.TW": "采鈺", "2258.TW": "鴻華先進-創", "2328.TW": "廣宇",
            "2354.TW": "鴻準", "1101.TW": "台泥", "3105.TWO": "穩懋", "3374.TWO": "精材", "5347.TWO": "世界",
            "5483.TWO": "中美晶", "3680.TWO": "家登", "006201.TWO": "元大富櫃50", "00692.TW": "富邦公司治理",
            "006203.TW": "元大MSCI台灣", "00631L.TW": "元大台灣50正2"}


class UniverseProvider(BaseProvider):
    name = "universe"

    def instruments(self) -> list[InstrumentInfo]:
        return [InstrumentInfo(symbol=s, code=s.split(".")[0], name=n, market="TPEX" if s.endswith(".TWO") else "TWSE",
                               type="etf" if s.startswith("00") else "stock", currency="TWD")
                for s, n in UNIVERSE.items()]


@pytest.fixture()
def stock_archive(engine, market):
    """The archive after the twse / tpex / companies / monthly groups, the related universe and closes."""
    with Session(engine) as db:
        results = Archiver(db, FakeFetcher(), "commercial", now_fn=lambda: EVENING).run(
            ["companies", "twse", "tpex", "monthly"])
        assert not [r for r in results if r.error and "t187ap0" not in r.name], [r for r in results if r.error]
        now = datetime.now(TAIPEI)
        for fixture, market_ in (("twse_t187ap03_l_related_live_20261112.json", "TWSE"),
                                 ("tpex_t187ap03_o_related_live_20261112.json", "TPEX")):
            prof = [{"symbol": tw_symbol(r["code"], market_), "date": r["date"], "industry_code": r["industry_code"],
                     "industry": r["industry"], "listed_date": r["listed_date"],
                     "shares_outstanding": r["shares_outstanding"], "values": r["values"],
                     "source": "tpex-openapi" if market_ == "TPEX" else "twse-openapi", "fetched_at": now}
                    for r in od.parse_company_profiles(load_archive(fixture), market_)]
            upsert(db, CompanyProfile, prof, ["symbol"])
        funds = [{"symbol": tw_symbol(r["code"], "TWSE"), "date": r["date"], "values": r["values"],
                  "source": "twse-openapi", "fetched_at": now}
                 for r in od.parse_fund_profiles(load_archive("twse_t187ap47_l_related_live_20261112.json"))]
        upsert(db, FundProfile, funds, ["symbol"])
        # the monthly links again, now that the whole universe (5483 中美晶 …) is archived
        Archiver(db, FakeFetcher(), "commercial", now_fn=lambda: EVENING).run(["monthly"])
        _closes(db)
    md = MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine)), UniverseProvider(),
                     DemoProvider()], policy="commercial")
    set_market_data(md)
    yield md
    set_market_data(market)


class FakeWikimediaFetcher:
    """Answers like www.wikidata.org/w/api.php and zh.wikipedia.org's REST summary (trimmed live fixtures).

    ``refuse``: every request answers HTTP 429 (Wikimedia's rate limit)."""

    SEARCH: ClassVar[dict[str, str]] = {"台積電": "wikidata_search_tsmc_live_20261112.json",
                                        "台灣積體電路製造股份有限公司": "wikidata_search_tsmc_live_20261112.json",
                                        "環球晶": "wikidata_search_globalwafers_live_20261112.json",
                                        "環球晶圓股份有限公司": "wikidata_search_globalwafers_live_20261112.json"}
    SUMMARY: ClassVar[dict[str, str]] = {"台積電": "zhwiki_summary_tsmc_live_20261112.json"}

    def __init__(self, refuse: bool = False):
        self.refuse = refuse
        self.calls: list[tuple[str, dict, dict]] = []

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None) -> Any:
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        if self.refuse:
            raise HttpStatusError("www.wikidata.org 回應 HTTP 429", 429)
        if url.startswith("https://www.wikidata.org/w/api.php"):
            p = params or {}
            if p.get("action") == "wbsearchentities":
                return load(self.SEARCH.get(p["search"], "wikidata_search_gudeng_live_20261112.json"))
            if p.get("action") == "wbgetentities":
                ids = set(p["ids"].split("|"))
                ents = load("wikidata_entities_tsmc_globalwafers_live_20261112.json")["entities"]
                return {"entities": {q: e for q, e in ents.items() if q in ids}, "success": 1}
        if url.startswith("https://zh.wikipedia.org/api/rest_v1/page/summary/"):
            title = unquote(url.rsplit("/", 1)[1])
            if title in self.SUMMARY:
                return load(self.SUMMARY[title])
            raise HttpStatusError("zh.wikipedia.org 回應 HTTP 404", 404)
        raise AssertionError(f"unexpected URL {url}")


@pytest.fixture()
def fake():
    from tests.ai.fake_anthropic import FakeAnthropic

    return FakeAnthropic()


@pytest.fixture()
def pool(fake):
    from forliosa.ai.keypool import KeyPool, set_key_pool

    p = KeyPool.from_keys(["sk-test-key-one", "sk-test-key-two"], client_factory=fake.client, sleep=lambda _s: None)
    set_key_pool(p)
    yield p
    set_key_pool(None)
