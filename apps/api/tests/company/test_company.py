"""「關於〈公司〉」 (decisions 6, 7) and the listed-stock foreign top 20 (decision 8).

* Facts from t187ap03 (董事長／總經理 as published) — never in AI tool outputs or prompts.
* The description: a zh.wikipedia excerpt found through Wikidata (ticker on TWSE first, else the exact full name),
  unchanged and cut at a sentence end; else an AI description from official facts only, cached by a facts hash.
* Wikimedia etiquette: one client, an honest User-Agent (``WIKIMEDIA_CONTACT``, never SEC's address), a 429
  pauses the lookups.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.ai.tools import ToolContext, execute
from forliosa.config import get_settings
from forliosa.marketdata import wikimedia as wm
from forliosa.models import AiUsage, CompanyDescription, User
from forliosa.services import company as company_svc
from tests.ai.fake_anthropic import text
from tests.company.conftest import FakeWikimediaFetcher, load

API = "/api/v1"
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)
TSMC_EXCERPT = ("台灣積體電路製造，簡稱台積電、TSMC，與旗下子公司合稱台積電集團，"
                "是臺灣一家專注於半導體晶片製造的高科技跨國企業，總部位於新竹科學園區，近年市值穩居全球前十大企業，也是全球最領先的半導體晶片製造商。"
                "台積電開創了專業積體電路製造服務 商業模式，只為客戶製造晶片，不設計、生產或銷售自有品牌的半導體產品，"
                "以確保不與客戶競爭；此一模式也促成了全球無廠IC設計產業的興起。")


@pytest.fixture(autouse=True)
def _no_pause():
    company_svc.reset_pause()
    yield
    company_svc.reset_pause()


@pytest.fixture()
def settings():
    return get_settings().model_copy(update={"company_descriptions_enabled": True, "company_ai_enabled": True,
                                             "wikimedia_contact": None})


def wiki(fetcher=None, contact=None):
    return wm.WikimediaClient(contact, fetcher=fetcher or FakeWikimediaFetcher())


# -- Wikimedia parsing ---------------------------------------------------------------------------------------
def test_article_by_ticker_then_exact_full_name():
    ents = load("wikidata_entities_tsmc_globalwafers_live_20261112.json")["entities"]
    tsmc = wm.find_article(ents, "2330", "TWSE", "台灣積體電路製造股份有限公司")
    assert (tsmc.title, tsmc.wikidata_id, tsmc.matched_by) == ("台積電", "Q713418", "ticker")
    # 環球晶's item has no P414 statement: matched by its exact full name (a zh-tw alias)
    gw = wm.find_article(ents, "6488", "TPEX", "環球晶圓股份有限公司")
    assert (gw.title, gw.matched_by) == ("環球晶圓", "name")
    assert wm.find_article(ents, "9999", "TWSE", "不存在股份有限公司") is None
    # TSMC's NYSE ticker matches a US lookup of TSM
    assert wm.find_article(ents, "TSM", "US", None).title == "台積電"
    # the exchange items: TWSE from TSMC's P414, TPEx from a live search (財團法人中華民國證券櫃檯買賣中心)
    tpex = load("wikidata_search_tpex_live_20261112.json")["search"][0]
    assert wm.EXCHANGES["TPEX"] == (tpex["id"],) and wm.EXCHANGES["TWSE"] == ("Q548621",)


def test_excerpt_is_cut_at_a_sentence_end_and_unchanged():
    s = wm.parse_summary(load("zhwiki_summary_tsmc_live_20261112.json"))
    assert s.text == TSMC_EXCERPT and s.revision_id == 95542651
    assert s.url == "https://zh.wikipedia.org/zh-tw/%E5%8F%B0%E7%A9%8D%E9%9B%BB"
    assert wm.excerpt("第一句。第二句很長" + "長" * 300 + "。", limit=50) == "第一句。"
    assert wm.excerpt("沒有句號的開頭") is None
    assert wm.parse_summary({"type": "disambiguation", "title": "X", "extract": "甲。"}) is None


def test_user_agent_uses_its_own_contact_only(monkeypatch):
    assert wm.user_agent(None) == "Forliosa/1.0"
    assert wm.user_agent("ops@example.org") == "Forliosa/1.0 (ops@example.org)"
    monkeypatch.setenv("SEC_CONTACT_EMAIL", "sec-only@example.org")
    client = wm.WikimediaClient(get_settings().wikimedia_contact)
    assert "sec-only" not in client.fetcher.client.headers["User-Agent"]


# -- refresh -------------------------------------------------------------------------------------------------
def test_refresh_wikipedia_then_ai_for_companies_without_an_article(engine, stock_archive, settings, fake, pool):
    fetcher = FakeWikimediaFetcher()
    fake.reply(text("家登精密工業是一家半導體業公司，2008 年成立、在櫃買中心上櫃，總部位於新北市。"
                    "最近一個月營收約 7 億元。"))
    with Session(engine) as db:
        rep = company_svc.refresh(db, stock_archive, settings=settings, client=wiki(fetcher),
                                  ai=company_svc.AiWriter(pool, settings), symbols=["2330.TW", "3680.TWO"],
                                  now_fn=lambda: NOW)
        assert (rep.symbols, rep.wiki_lookups, rep.wiki_found, rep.ai_written) == (2, 2, 1, 1), rep
        tsmc = db.get(CompanyDescription, "2330.TW")
        assert (tsmc.kind, tsmc.title, tsmc.revision_id, tsmc.wikidata_id) == ("wikipedia", "台積電", 95542651,
                                                                               "Q713418")
        assert tsmc.text == TSMC_EXCERPT
        # 家登: no Wikidata item at all -> an AI description from the official facts
        gudeng = db.get(CompanyDescription, "3680.TWO")
        assert gudeng.kind == "ai" and gudeng.text.startswith("家登精密工業") and gudeng.facts_key
        usage = list(db.scalars(select(AiUsage)))
        assert [(u.feature, u.user_id) for u in usage] == [("company", None)]
    # one request at a time, in order; Accept-Language zh-tw for the variant
    summary_calls = [c for c in fetcher.calls if "zh.wikipedia.org" in c[0]]
    assert summary_calls and all(c[2] == {"Accept-Language": "zh-tw"} for c in summary_calls)
    # the AI prompt carries official facts only: no chairman / president, no Wikipedia text
    body = json.dumps(fake.requests[0]["body"], ensure_ascii=False)
    assert "實收資本額" in body and "產業別" in body and "上櫃" in body
    for name in ("邱銘乾", "林添瑞", "董事長", "總經理"):
        assert name not in body
    assert "台灣積體電路製造，簡稱" not in body


def test_ai_description_is_cached_until_the_facts_change(engine, stock_archive, settings, fake, pool):
    fake.reply(text("家登精密工業是一家半導體業公司，總部位於新北市，在櫃買中心上櫃。"))
    with Session(engine) as db:
        args = {"settings": settings, "client": wiki(), "ai": company_svc.AiWriter(pool, settings),
                "symbols": ["3680.TWO"]}
        company_svc.refresh(db, stock_archive, now_fn=lambda: NOW, **args)
        assert len(fake.requests) == 1
        company_svc.refresh(db, stock_archive, now_fn=lambda: NOW + timedelta(hours=1), **args)
        assert len(fake.requests) == 1  # same facts: no new call
        from forliosa.models import CompanyProfile

        prof = db.get(CompanyProfile, "3680.TWO")
        prof.values = {**prof.values, "paid_in_capital": prof.values["paid_in_capital"] * 2}
        db.commit()
        fake.reply(text("家登精密工業是一家半導體業公司，總部位於新北市，實收資本額約 20 億元。"))
        company_svc.refresh(db, stock_archive, now_fn=lambda: NOW + timedelta(hours=2), **args)
        assert len(fake.requests) == 2
        assert "20 億元" in db.get(CompanyDescription, "3680.TWO").text


def test_ai_text_naming_a_person_is_rejected(engine, stock_archive, settings, fake, pool):
    from forliosa.models import CompanyProfile

    with Session(engine) as db:
        chairman = db.get(CompanyProfile, "3680.TWO").values["chairman"]
        fake.reply(text(f"家登精密工業由{chairman}領導，是一家半導體業公司。"))
        company_svc.refresh(db, stock_archive, settings=settings, client=wiki(),
                            ai=company_svc.AiWriter(pool, settings), symbols=["3680.TWO"], now_fn=lambda: NOW)
        assert db.get(CompanyDescription, "3680.TWO").kind == "none"


def test_ai_text_naming_a_person_without_the_published_title_is_rejected(engine, stock_archive, settings, fake,
                                                                         pool):
    """「總裁: 魏哲家」 as published: the model writing only 「魏哲家」 is still caught (review 2026-11-12)."""
    from forliosa.models import CompanyProfile

    assert company_svc.person_names("總裁: 魏哲家", "董事長：劉德音、魏哲家") == ["魏哲家", "劉德音"]
    assert company_svc.person_names("Chairman: John Smith", "林 添瑞") == [
        "John Smith", "JohnSmith", "John", "Smith", "林 添瑞", "林添瑞", "添瑞"]
    assert company_svc.person_names(None, "", "－") == []
    with Session(engine) as db:
        prof = db.get(CompanyProfile, "3680.TWO")
        prof.values = {**prof.values, "president": "總經理: 王小明"}
        db.commit()
        fake.reply(text("家登精密工業由王小明領導，是一家半導體業公司，總部位於新北市。"))
        company_svc.refresh(db, stock_archive, settings=settings, client=wiki(),
                            ai=company_svc.AiWriter(pool, settings), symbols=["3680.TWO"], now_fn=lambda: NOW)
        assert db.get(CompanyDescription, "3680.TWO").kind == "none"


def test_refused_ai_replies_back_off_and_count_against_the_run(engine, stock_archive, settings, fake, pool):
    """A reply that is refused (here: too long) is not requested again every hour: the same facts wait 24 h, then
    48 h …; every call counts against COMPANY_AI_PER_RUN, refused or not (review 2026-11-12)."""
    too_long = "家登精密工業是一家半導體業公司，" * 12
    for _ in range(3):  # exactly the three calls expected below
        fake.reply(text(too_long))
    args = {"settings": settings, "client": wiki(), "ai": company_svc.AiWriter(pool, settings),
            "symbols": ["3680.TWO"]}
    with Session(engine) as db:
        for h in range(4):  # four hourly runs: one call
            rep = company_svc.refresh(db, stock_archive, now_fn=lambda h=h: NOW + timedelta(hours=h), **args)
        assert len(fake.requests) == 1 and rep.ai_backing_off == 1 and rep.ai_calls == 0
        row = db.get(CompanyDescription, "3680.TWO")
        assert (row.kind, row.ai_failures) == ("none", 1) and row.ai_failed_key
        company_svc.refresh(db, stock_archive, now_fn=lambda: NOW + timedelta(hours=24), **args)
        assert len(fake.requests) == 2 and db.get(CompanyDescription, "3680.TWO").ai_failures == 2
        company_svc.refresh(db, stock_archive, now_fn=lambda: NOW + timedelta(hours=24 + 47), **args)
        assert len(fake.requests) == 2  # the second failure waits 48 h
        company_svc.refresh(db, stock_archive, now_fn=lambda: NOW + timedelta(hours=24 + 48), **args)
        assert len(fake.requests) == 3
        # new facts are tried at once
        from forliosa.models import CompanyProfile

        prof = db.get(CompanyProfile, "3680.TWO")
        prof.values = {**prof.values, "paid_in_capital": prof.values["paid_in_capital"] * 2}
        db.commit()
        fake.reply(text("家登精密工業是一家半導體業公司，總部位於新北市，實收資本額約 20 億元。"))
        company_svc.refresh(db, stock_archive, now_fn=lambda: NOW + timedelta(hours=73), **args)
        row = db.get(CompanyDescription, "3680.TWO")
        assert (row.kind, row.ai_failures, row.ai_failed_key) == ("ai", 0, None)
    # the per-run cap counts calls, not successes: two symbols, a cap of one, a refused reply -> one call
    capped = settings.model_copy(update={"company_ai_per_run": 1})
    fake.reply(text(too_long))
    with Session(engine) as db:
        before = len(fake.requests)
        rep = company_svc.refresh(db, stock_archive, settings=capped, client=wiki(),
                                  ai=company_svc.AiWriter(pool, capped), symbols=["6488.TWO", "5347.TWO"],
                                  now_fn=lambda: NOW + timedelta(days=10))
        assert rep.ai_calls == 1 and len(fake.requests) == before + 1


def test_api_errors_back_off_too(engine, stock_archive, settings):
    class Failing:
        calls = 0

        def write(self, db, facts):
            Failing.calls += 1
            raise RuntimeError("overloaded")

    with Session(engine) as db:
        for h in range(3):
            company_svc.refresh(db, stock_archive, settings=settings, client=wiki(), ai=Failing(),
                                symbols=["3680.TWO"], now_fn=lambda h=h: NOW + timedelta(hours=h))
        assert Failing.calls == 1 and db.get(CompanyDescription, "3680.TWO").ai_failures == 1


def test_ai_description_lists_every_dataset_its_facts_came_from(client, engine, stock_archive, settings, fake,
                                                                pool):
    """環球晶 has no zh.wikipedia article: its AI description used the ESG product text and the monthly revenue, so
    「來源」 names those datasets too, not only 公司基本資料 (review 2026-11-12)."""
    fake.reply(text("環球晶圓是一家半導體業公司，總部位於新竹科學園區，主要產品為半導體晶片。"))
    with Session(engine) as db:
        company_svc.refresh(db, stock_archive, settings=settings, client=wiki(),
                            ai=company_svc.AiWriter(pool, settings), symbols=["6488.TWO"], now_fn=lambda: NOW)
        row = db.get(CompanyDescription, "6488.TWO")
        assert row.kind == "ai"
        assert row.sources == ["tpex-openapi/company", "tpex-openapi/revenue", "tpex-openapi/esg_products"]
    body = json.dumps(fake.requests[0]["body"], ensure_ascii=False)
    assert "ESG" in body and "最近月營收" in body
    c = client.get(f"{API}/instruments/6488.TWO/company").json()
    assert c["description"]["kind"] == "ai"
    srcs = " ".join(c["sources"])
    assert "〈上櫃股票基本資料〉" in srcs and "〈上櫃公司每月營業收入彙總表〉" in srcs
    assert "〈上櫃公司企業ESG資訊揭露彙總資料-產品品質與安全〉" in srcs
    assert len(c["sources"]) == len(set(c["sources"]))


def test_wikimedia_429_pauses_the_lookups(engine, stock_archive, settings):
    refusing = FakeWikimediaFetcher(refuse=True)
    with Session(engine) as db:
        rep = company_svc.refresh(db, stock_archive, settings=settings, client=wiki(refusing), ai=None,
                                  symbols=["2330.TW", "6488.TWO"], now_fn=lambda: NOW)
        assert rep.paused and len(refusing.calls) == 1  # stopped at the first refusal
        rep = company_svc.refresh(db, stock_archive, settings=settings, client=wiki(refusing), ai=None,
                                  symbols=["2330.TW"], now_fn=lambda: NOW + timedelta(hours=1))
        assert rep.wiki_lookups == 0 and len(refusing.calls) == 1  # paused for 6 hours
        assert db.get(CompanyDescription, "2330.TW") is None


# -- API -----------------------------------------------------------------------------------------------------
def test_company_endpoint_facts_and_wikipedia_excerpt(client, engine, stock_archive, settings):
    with Session(engine) as db:
        company_svc.refresh(db, stock_archive, settings=settings, client=wiki(), ai=None, symbols=["2330.TW"],
                            now_fn=lambda: NOW)
    r = client.get(f"{API}/instruments/2330.TW/company")
    assert r.status_code == 200, r.text
    c = r.json()
    assert (c["name"], c["short_name"], c["industry"], c["listing"], c["listed_date"]) == (
        "台灣積體電路製造股份有限公司", "台積電", "半導體業", "上市", "1994-09-05")
    assert (c["incorporated"], c["years_since_incorporation"]) == ("1987-02-21", 39)
    assert (c["hq"], c["website"], c["paid_in_capital"]) == ("新竹科學園區", "https://www.tsmc.com", 259323700670)
    assert (c["chairman"], c["president"]) == ("魏哲家", "總裁: 魏哲家")
    assert (c["auditor"], c["transfer_agent"]) == ("勤業眾信聯合會計師事務所", "中國信託商業銀行 代理部")
    assert c["data_date"] and "〈上市公司基本資料〉" in " ".join(c["sources"])
    d = c["description"]
    assert (d["kind"], d["label"], d["license"], d["source"]) == ("wikipedia", "節錄", "CC BY-SA 4.0", "維基百科")
    assert d["text"] == TSMC_EXCERPT and d["url"].startswith("https://zh.wikipedia.org/zh-tw/")
    assert "維基百科〈中文維基百科條目（開頭節錄）〉" in " ".join(c["sources"])


def test_company_endpoint_ky_registration_and_etf_and_us(client, stock_archive, engine):
    from forliosa.models import CompanyProfile

    with Session(engine) as db:
        gw = db.get(CompanyProfile, "6488.TWO")
        gw.values = {**gw.values, "registered_in": "開曼群島"}
        db.commit()
    c = client.get(f"{API}/instruments/6488.TWO/company").json()
    assert (c["hq"], c["registered_in"], c["listing"]) == (None, "開曼群島", "上櫃")
    etf = client.get(f"{API}/instruments/0050.TW/company").json()
    assert etf["fund"]["index_name"] == "臺灣50指數" and etf["chairman"] is None and etf["description"] is None
    us = client.get(f"{API}/instruments/AAPL/company").json()
    assert us["notes"] == ["SEC 公司資料尚未取得"] and us["hq"] is None


def test_us_company_facts_from_sec_submissions(client, stock_archive, engine):
    from forliosa.marketdata import sec
    from forliosa.models import SecCompany, SecTicker
    from tests.archive.fakes import load as load_archive

    meta, _ = sec.parse_submissions(load_archive("sec_submissions_aapl_live_20261112.json"))
    with Session(engine) as db:
        db.add(SecTicker(ticker="AAPL", cik=320193, title="Apple Inc."))
        db.add(SecCompany(cik=320193, name="Apple Inc.", fiscal_year_end="0926", profile=meta["profile"],
                          filings_fetched_at=NOW))
        db.commit()
    c = client.get(f"{API}/instruments/AAPL/company").json()
    assert (c["industry"], c["hq"], c["exchanges"], c["fiscal_year_end"]) == (
        "Electronic Computers", "Cupertino, CA", ["Nasdaq"], "09-26")
    assert c["former_names"][1] == {"name": "APPLE COMPUTER INC", "from": "1994-01-26", "to": "2007-01-04"}
    assert "EDGAR 公司申報清單" in " ".join(c["sources"])


def test_ai_tools_never_return_the_officers_names(client, engine, stock_archive):
    with Session(engine) as db:
        me = db.scalar(select(User).where(User.email == "demo@forliosa.local"))
        ctx = ToolContext(db=db, user=me, md=stock_archive)
        for name, args in (("get_stock_overview", {"symbol": "2330"}), ("get_news", {"symbol": "2330"}),
                           ("get_chips", {"symbol": "2330", "range": "1M"}),
                           ("get_events", {"symbol": "2330", "mine_only": False})):
            out = execute(ctx, name, args)
            assert "魏哲家" not in out.content, name


# -- foreign holding top 20 (listed stocks) ---------------------------------------------------------------------
def test_listed_stock_in_the_top20_shows_its_foreign_holding(client, stock_archive):
    ase = client.get(f"{API}/instruments/3711.TW/chips?range=1M").json()
    assert ase["foreign_top20"] == {"as_of": "2026-11-12", "rank": 12, "pct": 0.7552, "limit_pct": 1.0}
    assert ase["foreign_holding_pct"] == [{"t": "2026-11-12", "pct": 0.7552}]
    assert ase["institutional"] == []  # still no per-stock 三大法人 for listed stocks
    assert any("前 20 名" in n for n in ase["notes"])
    assert "外資及陸資持股前20名彙總表" in " ".join(ase["sources"])
    tsmc = client.get(f"{API}/instruments/2330.TW/chips?range=1M").json()
    assert tsmc["foreign_top20"] is None and tsmc["foreign_holding_pct"] == []
    assert any("前 20 名" in n for n in tsmc["notes"])


def test_listed_stock_in_the_top20_keeps_the_institutional_reason(client, stock_archive):
    """On the list: why there are no 三大法人 (the paid TWSE product) and the top-20 note, each once."""
    from forliosa.services import stock as stock_svc

    ase = client.get(f"{API}/instruments/3711.TW/chips?range=1M").json()
    assert ase["notes"] == [stock_svc.LISTED_INST_NOTE, stock_svc.TOP20_NOTE]
    assert ase["notes"][0] == "上市股票沒有逐檔三大法人資料"


def test_listed_stock_that_dropped_off_the_top20_has_no_foreign_series(client, stock_archive, engine):
    """In the list two days ago, not on the latest list: no stale pct next to 「不在名單上」 (contract: empty series
    plus the reason)."""
    from forliosa.models import ForeignHoldingTop20
    from forliosa.services import stock as stock_svc

    with Session(engine) as db:
        db.add(ForeignHoldingTop20(date=date(2026, 11, 10), symbol="2330.TW", rank=20, pct=D("0.7210"),
                                   shares=1, source="twse-openapi"))
        db.commit()
    tsmc = client.get(f"{API}/instruments/2330.TW/chips?range=1M").json()
    assert tsmc["foreign_top20"] is None and tsmc["foreign_holding_pct"] == []
    assert tsmc["notes"] == [stock_svc.LISTED_CHIPS_NOTE]
    assert "外資及陸資持股前20名彙總表" not in " ".join(tsmc["sources"])
