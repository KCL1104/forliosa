"""Stock-page archive jobs (2026-11-12, decisions 4, 6, 8): company ↔ company links from 董監事持股餘額明細,
富櫃五十 constituents, TDCC 集保股東戶數, the foreign-holding top 20 and the ESG product text — on trimmed live
fixtures (natural persons' names in the t187ap11 fixtures are replaced by 「自然人NN」)."""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal as D

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.archive import Archiver
from forliosa.marketdata import company_data as cd
from forliosa.models import (
    BoardLink,
    DatasetStatus,
    EsgProductOutput,
    ForeignHoldingTop20,
    HolderCountMonthly,
    IndexConstituent,
)
from forliosa.timeutil import TAIPEI
from tests.archive.fakes import FIX, NOW, FakeFetcher, load

EVENING = datetime(2026, 11, 12, 21, 45, tzinfo=TAIPEI)
MORNING = datetime(2026, 11, 13, 8, 15, tzinfo=TAIPEI)


def run(db, only, now=NOW):
    return Archiver(db, FakeFetcher(), "commercial", now_fn=lambda: now).run(only)


def count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


# -- parsers -------------------------------------------------------------------------------------------------
def _companies() -> dict[str, tuple[str, str]]:
    from forliosa.marketdata import opendata as od

    out = {}
    for name, market in (("twse_t187ap03_l_related_live_20261112.json", "TWSE"),
                         ("tpex_t187ap03_o_related_live_20261112.json", "TPEX")):
        for r in od.parse_company_profiles(load(name), market):
            out[cd.company_name_key(r["values"]["name"])] = (r["code"], market)
    return out


def test_board_links_keep_company_rows_only():
    rows = load("twse_t187ap11_l_live_20261112.json") + load("tpex_t187ap11_o_live_20261112.json")
    links = {(r["code"], r["holder_code"]): r for r in cd.parse_board_links(rows, _companies())}
    assert set(links) == {("3443", "2330"), ("6789", "2330"), ("2258", "2317"), ("2328", "2317"), ("5347", "2330"),
                          ("3374", "2330"), ("6488", "5483")}
    guc = links[("3443", "2330")]
    assert (guc["roles"], guc["period"], guc["data_date"], guc["holder_market"]) == (
        "董事長、董事、大股東", "2026-09", date(2026, 10, 20), "TWSE")
    assert guc["shares"] == 46687859
    assert links[("5347", "2330")]["roles"] == "大股東"
    # natural persons, representatives and unlisted organisations (國發基金, 華創車電) never come out
    text = str(list(links.values()))
    assert "自然人" not in text and "國家發展基金" not in text and "華創" not in text


def test_tdcc_holders_parse_and_dedupe():
    text = (FIX / "tdcc_2-23_live_20261112.csv").read_text(encoding="utf-8-sig")
    rows = cd.parse_tdcc_holders(text)
    assert [r["code"] for r in rows].count("006201") == 1  # the live file lists 006201 twice
    r = next(r for r in rows if r["code"] == "006201")
    assert (r["period"], r["holders"], r["issued_k_shares"]) == ("2026-10", 4914, 24446)


def test_qfii_top20_and_constituents_and_esg():
    top = cd.parse_qfii_top20(load("twse_mi_qfiis_sort_20_live_20261112.json"))
    assert len(top) == 20 and top[0]["code"] == "2923" and top[0]["pct"] == D("0.9953")
    ase = next(r for r in top if r["code"] == "3711")
    assert (ase["rank"], ase["pct"], ase["limit_pct"]) == (12, D("0.7552"), D("1"))
    cons = cd.parse_tpex50_constituents(load("tpex_tpex50_constituents_live_20261112.json"))
    assert len(cons) == 50 and {"3105", "5483"} <= {r["code"] for r in cons}
    assert cons[0]["date"] == date(2026, 11, 12)
    esg = {r["code"]: r for r in cd.parse_esg_products(load("twse_t187ap46_l_14_live_20261112.json"))}
    assert esg["2330"]["text"] == "達1,500萬片十二吋晶圓約當量" and esg["2330"]["year"] == 2025


def test_address_city_and_website_rules():
    assert cd.hq_from_address("(104)台北市中山區松江路111號12樓", "TWSE") == "台北市"
    assert cd.hq_from_address("高雄巿前金區中正四路170號", "TWSE") == "高雄市"  # 巿 (U+5DFF) typo
    assert cd.hq_from_address("(30078)新竹科學園區新竹市篤行路6-8號3樓", "TWSE") == "新竹科學園區"
    assert cd.hq_from_address("新竹市科學工業園區力行路", "TWSE") == "新竹科學園區"
    assert cd.hq_from_address("北市後港街六十六號", "TWSE") is None  # abbreviated: not certain
    assert cd.hq_from_address("Suite 102, Cannon Place, Grand Cayman", "TWSE") is None
    assert cd.hq_from_address("6F, No.23, Siyuan Rd.Xinzhuang Dist., New Taipei City, Taiwan", "TPEX") == "新北市"
    assert cd.hq_from_address("Sec. 3, Minsheng E. Rd.,Songshan Dist.Taipei City 105, Taiwan", "TPEX") == "台北市"
    assert cd.hq_from_address("No.160, Sec. 1, Ping-Tung Rd., Ping-Jen City, Taoyuan Hsien", "TPEX") is None
    assert cd.hq_from_address("Science-Based Industrial Park Hsinchu, Taiwan", "TPEX") == "新竹科學園區"
    assert cd.hq_from_address("12F, 105, Sec. 2, Tun-Hwa S. Rd.Taipei Taiwan", "TPEX") is None  # bare "Taipei"
    assert cd.registration_country("KY 開曼群島            ") == "開曼群島"
    assert [cd.clean_website(x) for x in ("www.acc.com.tw ", "Http://www.jeilin.com.tw", "http：//www.feii.com.tw",
                                          "https://www.tccgroupholdings.com/tw/", "－", "abc")] == [
        "https://www.acc.com.tw", "https://www.jeilin.com.tw", "https://www.feii.com.tw",
        "https://www.tccgroupholdings.com/tw/", None, None]
    assert cd.clean_name("勤業眾信&#63895;合會計師事務所") == "勤業眾信聯合會計師事務所"


# -- jobs ----------------------------------------------------------------------------------------------------
def test_monthly_group_archives_links_holders_and_esg(engine, caplog):
    caplog.set_level(logging.DEBUG)
    with Session(engine) as db:
        assert not [r for r in run(db, ["companies"]) if r.error]
        results = run(db, ["monthly"])
        assert not [r for r in results if r.error], [r for r in results if r.error]
        links = {(x.symbol, x.holder_symbol): x for x in db.scalars(select(BoardLink))}
        # holders must be archived companies (the default profile fixtures hold 2317 and 2330, not 5483)
        assert set(links) == {("3443.TW", "2330.TW"), ("6789.TW", "2330.TW"), ("2258.TW", "2317.TW"),
                              ("2328.TW", "2317.TW"), ("5347.TWO", "2330.TW"), ("3374.TWO", "2330.TW")}
        assert links[("2328.TW", "2317.TW")].roles == "大股東" and links[("2328.TW", "2317.TW")].period == "2026-09"
        assert db.get(HolderCountMonthly, ("0050.TW", "2026-10")).holders == 3741557
        assert db.get(HolderCountMonthly, ("006201.TWO", "2026-10")).holders == 4914
        assert db.get(EsgProductOutput, "6488.TWO").text.startswith("1.半導體晶片產品")
        assert db.get(DatasetStatus, "twse-openapi/board").data_date == date(2026, 10, 20)
        before = {m.__tablename__: count(db, m) for m in (BoardLink, HolderCountMonthly, EsgProductOutput)}
        run(db, ["monthly"])
        assert {m.__tablename__: count(db, m) for m in (BoardLink, HolderCountMonthly, EsgProductOutput)} == before
    # nothing about natural persons reaches the log either
    assert "自然人" not in caplog.text


def test_monthly_links_wait_for_company_profiles(engine):
    with Session(engine) as db:
        results = {r.name: r for r in run(db, ["monthly"])}
        assert "公司基本資料尚未存檔" in (results["twse board links t187ap11_L"].error or "")
        assert results["tdcc holders 2-22/2-23"].error is None


def test_foreign_top20_is_stamped_by_run_time(engine):
    with Session(engine) as db:
        run(db, ["twse"])  # 10:00: ambiguous, skipped
        assert count(db, ForeignHoldingTop20) == 0
        run(db, ["twse"], now=EVENING)
        ase = db.get(ForeignHoldingTop20, (date(2026, 11, 12), "3711.TW"))
        assert (ase.rank, ase.pct, ase.shares) == (12, D("0.7552"), 3389410793)
        run(db, ["twse"], now=MORNING)  # the next morning: still 11-12's list
        assert count(db, ForeignHoldingTop20) == 20
        assert db.get(DatasetStatus, "twse-openapi/foreign_top20").data_date == date(2026, 11, 12)


def test_tpex50_constituents_daily(engine):
    with Session(engine) as db:
        run(db, ["tpex"])
        rows = list(db.scalars(select(IndexConstituent)))
        assert len(rows) == 50 and {r.index_code for r in rows} == {"TPEX50"}
        assert db.get(IndexConstituent, ("TPEX50", date(2026, 11, 12), "3105.TWO")) is not None
