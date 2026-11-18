"""持倉配置（帳本「配置」分段，負責人 2026-11-18）: GET /portfolio/allocation, the user's own limits, ETF classes, US
sectors, unknown US funds, and the summary's numbers being the same ones."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from forliosa.marketdata.base import InstrumentInfo
from forliosa.models import CompanyProfile, FundProfile, SecCompany, SecTicker
from forliosa.services import allocation as alloc
from tests.api.m5 import API, account, join, make_group, me_id, trade, trading_day

VIEW = "X-Forliosa-View-As"


def _close(client, symbol: str, d: date) -> float:
    candles = client.get(f"{API}/instruments/{symbol}/history", params={"range": "1Y"}).json()["candles"]
    return next(c["c"] for c in reversed(candles) if c["t"] <= d.isoformat())


@pytest.fixture()
def ledger(client, engine):
    """Two accounts: Taiwan (2330, 2317, 0050) and US (AAPL, NVDA, VOO); 0050's fund type is archived."""
    with Session(engine) as db:
        db.add(FundProfile(symbol="0050.TW", date=date(2026, 11, 12), source="twse-openapi",
                           values={"fund_type": "國內成分證券指數股票型基金"}))
        db.commit()
    tw = account(client, "永豐－一般")
    us = account(client, "國泰－複委託", currency="USD", fee_discount=1)
    d = trading_day(120)
    for symbol, qty in (("2330.TW", 2000), ("2317.TW", 3000), ("0050.TW", 5000)):
        trade(client, tw["id"], symbol, "buy", d, qty, _close(client, symbol, d))
    for symbol, qty in (("AAPL", 20), ("NVDA", 30), ("VOO", 5)):
        trade(client, us["id"], symbol, "buy", d, qty, _close(client, symbol, d))
    return {"tw": tw["id"], "us": us["id"]}


def _get(client, **params):
    r = client.get(f"{API}/portfolio/allocation", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_every_grouping_adds_up_to_the_ledger_total(client, ledger):
    a = _get(client)
    holdings = client.get(f"{API}/portfolio/holdings").json()
    summary = client.get(f"{API}/portfolio/summary").json()
    total = sum(h["market_value"] for h in holdings)
    assert a["market_value"] == pytest.approx(total, abs=0.05) == summary["market_value"]
    assert set(a["groups"]) == {"holding", "industry", "market", "account", "currency", "type"}
    for name, slices in a["groups"].items():
        assert sum(s["value"] for s in slices) == pytest.approx(a["market_value"], abs=0.01 * len(slices)), name
        assert sum(s["weight"] for s in slices) == pytest.approx(1.0, abs=1e-5), name
        assert [s["value"] for s in slices] == sorted((s["value"] for s in slices), reverse=True), name
        assert sorted(sym for s in slices for sym in s["symbols"]) == sorted(
            sym for h in holdings for sym in [h["symbol"]] * (len(h["account_ids"]) if name == "account" else 1))
    # 每一檔 is the holdings table's market value and weight (same prices, same FX)
    by = {h["symbol"]: h for h in holdings}
    for s in a["groups"]["holding"]:
        assert s["value"] == pytest.approx(by[s["key"]]["market_value"], abs=0.01)
        assert s["weight"] == pytest.approx(by[s["key"]]["weight"], abs=1e-6)
        assert s["label"] == by[s["key"]]["name"] and s["symbols"] == [s["key"]]
        assert s["is_etf"] is (s["key"] in ("0050.TW", "VOO"))
    industry = {s["key"]: s for s in a["groups"]["industry"]}
    assert set(industry) == {"半導體業", "其他電子業", "etf_tw_equity", "us_tech", "us_semis", "etf_foreign_equity"}
    assert industry["us_tech"]["label"] == "美股科技" and industry["us_semis"]["label"] == "美股半導體"
    assert industry["etf_tw_equity"]["label"] == "國內股票型 ETF" and industry["etf_tw_equity"]["is_etf"]
    assert industry["etf_foreign_equity"]["symbols"] == ["VOO"] and not industry["半導體業"]["is_etf"]
    assert {s["label"] for s in a["groups"]["market"]} == {"上市", "美股"}
    assert {s["label"] for s in a["groups"]["currency"]} == {"新台幣", "美元"}
    assert {s["key"]: s["symbols"] for s in a["groups"]["type"]}["etf"] == sorted(
        ["0050.TW", "VOO"], key=lambda sym: -by[sym]["market_value"])
    assert {s["label"] for s in a["groups"]["account"]} == {"永豐－一般", "國泰－複委託"}
    assert a["can_edit_limits"] is True and a["account_id"] is None and a["valued_at_cost"] == []
    # the rate behind the US values is served (the 「美股依匯率 … 換成新台幣」 line), the holdings' own
    assert set(a["fx"]) == {"USD"}
    for h in holdings:
        if h["currency"] == "USD":
            assert h["market_value"] == pytest.approx(h["quantity"] * h["price"] * a["fx"]["USD"], abs=0.05)
    # /portfolio/summary carries the same numbers (the ledger's fact line and the AI panel read it)
    assert summary["concentration"] == a["concentration"]
    for key, g in alloc.SUMMARY_KEYS.items():
        assert summary["allocation"][key] == [{k: s[k] for k in ("key", "label", "value", "weight")}
                                              for s in a["groups"][g]], key


def test_concentration_is_facts_and_leaves_etfs_out_of_industries(client, ledger):
    a = _get(client)
    c = a["concentration"]
    weights = sorted((s["weight"] for s in a["groups"]["holding"]), reverse=True)
    top = a["groups"]["holding"][0]
    assert c["holdings_count"] == 6
    assert c["top_holding"] == {"symbol": top["key"], "name": top["label"], "weight": top["weight"],
                                "is_etf": top["is_etf"]}
    assert c["top3_weight"] == pytest.approx(sum(weights[:3]), abs=1e-5)
    assert c["top5_weight"] == pytest.approx(sum(weights[:5]), abs=1e-5)
    stocks = [s for s in a["groups"]["industry"] if not s["is_etf"] and s["key"] != "unclassified"]
    assert c["top_industry"] == {"key": stocks[0]["key"], "label": stocks[0]["label"], "weight": stocks[0]["weight"]}
    assert c["etf_weight"] == pytest.approx(sum(s["weight"] for s in a["groups"]["industry"] if s["is_etf"]), abs=1e-5)
    # no limit by default, so nothing is flagged
    assert c["limits"] == {"holding": None, "industry": None} and c["over_limits"] == []


def test_account_filter_matches_the_performance_segment(client, ledger):
    whole = _get(client)
    accounts = {s["key"]: s["value"] for s in whole["groups"]["account"]}
    for acc in (ledger["tw"], ledger["us"]):
        one = _get(client, account_id=acc)
        assert one["account_id"] == acc
        summary = client.get(f"{API}/portfolio/summary", params={"account_id": acc}).json()
        holdings = client.get(f"{API}/portfolio/holdings", params={"account_id": acc}).json()
        perf = client.get(f"{API}/portfolio/performance", params={"range": "1Y", "account_id": acc}).json()
        assert one["market_value"] == summary["market_value"]
        assert one["market_value"] == pytest.approx(sum(h["market_value"] for h in holdings), abs=0.05)
        # the series' last close is valued at that day's FX: a US account's differs by the FX move since then
        assert one["market_value"] == pytest.approx(perf["series"][-1]["market_value"],
                                                    rel=1e-3 if acc == ledger["tw"] else 2e-2)
        assert one["market_value"] == pytest.approx(accounts[acc], abs=0.01)
        assert [s["key"] for s in one["groups"]["account"]] == [acc]
        assert {s["key"] for s in one["groups"]["holding"]} == {h["symbol"] for h in holdings}
        assert summary["concentration"] == one["concentration"]
        # a Taiwan-only account has no foreign currency, so no rate to print
        assert one["fx"] == ({} if acc == ledger["tw"] else whole["fx"])
    assert {s["key"] for s in _get(client, account_id=ledger["us"])["groups"]["currency"]} == {"USD"}
    assert client.get(f"{API}/portfolio/allocation", params={"account_id": "acc_nope"}).status_code == 404


def test_empty_ledger(client):
    a = _get(client)
    assert a["market_value"] == 0 and all(v == [] for v in a["groups"].values()) and a["fx"] == {}
    assert a["concentration"] == {"holdings_count": 0, "top_holding": None, "top3_weight": 0.0, "top5_weight": 0.0,
                                  "top_industry": None, "etf_weight": 0.0,
                                  "limits": {"holding": None, "industry": None}, "over_limits": []}


def test_limits_are_the_users_own_and_flag_only_what_is_above_them(client, ledger):
    a = _get(client)
    stocks = [s for s in a["groups"]["holding"] if not s["is_etf"]]
    etfs = [s for s in a["groups"]["holding"] if s["is_etf"]]
    cap = round(stocks[1]["weight"] - 0.001, 4)  # the two largest stocks are above it
    r = client.put(f"{API}/portfolio/allocation/limits", json={"holding": cap, "industry": 0.01})
    assert r.status_code == 200 and r.json() == {"holding": cap, "industry": 0.01}
    c = _get(client)["concentration"]
    assert c["limits"] == {"holding": cap, "industry": 0.01}
    held = [o for o in c["over_limits"] if o["kind"] == "holding"]
    assert [o["key"] for o in held] == [s["key"] for s in stocks if s["weight"] > cap]
    assert len(held) >= 2 and not {o["key"] for o in held} & {s["key"] for s in etfs}  # 個股 only, never an ETF
    assert held[0] == {"kind": "holding", "key": stocks[0]["key"], "label": stocks[0]["label"],
                       "weight": stocks[0]["weight"], "limit": cap}
    industries = [o["key"] for o in c["over_limits"] if o["kind"] == "industry"]
    assert set(industries) == {"半導體業", "其他電子業", "us_tech", "us_semis"}  # ETF classes are not industries
    assert client.get(f"{API}/portfolio/summary").json()["concentration"] == c
    # stored with the other preferences; /me's preferences are unchanged in shape
    me = client.get(f"{API}/me").json()
    assert "allocation_limits" not in me["preferences"]
    assert client.patch(f"{API}/me/preferences", json={"theme": "dark"}).status_code == 200
    assert _get(client)["concentration"]["limits"] == {"holding": cap, "industry": 0.01}  # kept by other changes
    for bad in ({"holding": 0}, {"holding": 1.5}, {"industry": -0.1}, {"holding": 0.3, "stock": 0.2},
                {"holding": "30%"}):
        assert client.put(f"{API}/portfolio/allocation/limits", json=bad).status_code == 422, bad
    # PUT replaces both: the one left out is cleared
    assert client.put(f"{API}/portfolio/allocation/limits", json={"industry": 0.5}).json() == {
        "holding": None, "industry": 0.5}
    assert client.put(f"{API}/portfolio/allocation/limits", json={}).json() == {"holding": None, "industry": None}
    assert _get(client)["concentration"]["over_limits"] == []


def test_view_as_shows_the_owners_allocation_read_only(client, other_client, ledger):
    g = make_group(client)
    join(client, other_client, g["id"])
    assert client.put(f"{API}/portfolio/allocation/limits", json={"holding": 0.2, "industry": None}).status_code == 200
    r = client.post(f"{API}/delegations", json={"viewer_user_id": me_id(other_client), "scope": "accounts",
                                                "account_ids": [ledger["tw"]]})
    assert r.status_code == 201, r.text
    h = {VIEW: r.json()["id"]}
    seen = other_client.get(f"{API}/portfolio/allocation", headers=h)
    assert seen.status_code == 200, seen.text
    a = seen.json()
    assert a["can_edit_limits"] is False
    assert a["concentration"]["limits"] == {"holding": 0.2, "industry": None}  # the owner's
    assert [s["key"] for s in a["groups"]["account"]] == [ledger["tw"]]  # only the delegated account
    assert a["market_value"] == _get(client, account_id=ledger["tw"])["market_value"]
    assert other_client.get(f"{API}/portfolio/allocation", params={"account_id": ledger["us"]},
                            headers=h).status_code == 404
    w = other_client.put(f"{API}/portfolio/allocation/limits", json={"holding": 0.9}, headers=h)
    assert w.status_code == 403 and w.json()["error"]["code"] == "read_only"
    assert _get(client)["concentration"]["limits"] == {"holding": 0.2, "industry": None}
    # without the header the viewer sees their own (empty) ledger and their own (unset) limits
    own = other_client.get(f"{API}/portfolio/allocation").json()
    assert own["groups"]["holding"] == [] and own["can_edit_limits"] is True
    assert own["concentration"]["limits"] == {"holding": None, "industry": None}


# -- classification ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("code", "fund_type", "expected"), [
    ("0050", "國內成分證券指數股票型基金", "etf_tw_equity"),
    ("0056", None, "etf_tw_equity"),  # built-in, no archived profile
    ("00646", "國外成分證券指數股票型基金", "etf_foreign_equity"),
    ("0061", "連結式證券指數股票型基金", "etf_foreign_equity"),
    ("0080", "境外指數股票型基金", "etf_foreign_equity"),
    ("00937B", "國外成分證券指數股票型基金", "etf_bond"),  # a TWSE bond ETF is filed as 國外成分
    ("00679B", None, "etf_bond"),  # OTC: the letter alone
    ("00982D", "國外成分證券主動式交易所交易基金(債券)", "etf_bond"),
    ("00631L", "槓桿/反向指數股票型基金", "etf_leveraged"),
    ("00632R", None, "etf_leveraged"),
    ("00716R", "指數股票型期貨信託基金", "etf_leveraged"),
    ("00635U", "指數股票型期貨信託基金", "etf_futures"),
    ("00981T", "國外成分證券平衡型指數股票型基金", "etf_balanced"),
    ("00981A", "國內成分證券主動式交易所交易基金(股票)", "etf_active"),
    ("00402A", "國外成分證券主動式交易所交易基金(股票)", "etf_active"),
    ("006201", None, "etf_other"),  # an OTC ETF without a letter or a profile: 未分類, not a guess
])
def test_taiwan_etf_classes(code, fund_type, expected):
    assert alloc.tw_etf_class(code, fund_type) == expected


def test_every_fund_type_of_the_live_file_has_a_class():
    """Every 基金類型 of t187ap47_L (the fixture is a live copy) lands in a class other than 未分類."""
    import json
    from pathlib import Path

    from forliosa.marketdata.opendata import parse_fund_profiles

    raw = json.loads((Path(__file__).parents[1] / "archive" / "fixtures"
                      / "twse_t187ap47_l_related_live_20261112.json").read_text())
    rows = parse_fund_profiles(raw)
    assert rows
    for r in rows:
        assert alloc.tw_etf_class(r["code"], r["values"]["fund_type"]) != "etf_other", r


@pytest.mark.parametrize("name", [
    "SPDR GOLD TRUST", "iShares Bitcoin Trust ETF", "ISHARES GOLD TRUST", "United States Oil Fund, LP",
    "United States 12 Month Natural Gas Fund, LP", "ProShares Trust II", "Invesco DB Commodity Index Tracking Fund",
    "Sprott Physical Gold & Silver Trust", "Teucrium Commodity Trust", "Grayscale Ethereum Classic Trust (ETC)",
    "Invesco CurrencyShares Euro Trust", "United States Commodity Index Funds Trust", "WisdomTree Bitcoin Fund",
    "SPDR S&P MIDCAP 400 ETF TRUST", "Direxion Shares ETF Trust",
    # crypto trusts and volatility funds (a review found these read as 美股金融)
    "Grayscale Solana Trust (SOL)", "Grayscale Litecoin Trust (LTC)", "Grayscale Chainlink Trust (LINK)",
    "Grayscale Stellar Lumens Trust (XLM)", "Grayscale Digital Large Cap Fund LLC", "Grayscale Zcash Trust (ZEC)",
    "Grayscale XRP Trust", "Grayscale Bitcoin Cash Trust (BCH)", "Volatility Shares Trust",
])
def test_us_funds_filed_as_companies_are_detected(name):
    assert alloc.looks_like_us_fund(name)


@pytest.mark.parametrize("name", [
    "NETFLIX INC", "NORTHERN TRUST CORP", "FEDERAL REALTY INVESTMENT TRUST", "HomeTrust Bancshares, Inc.",
    "GAMCO Natural Resources, Gold & Income Trust", "PIMCO Dynamic Income Fund", "Apple Inc.", "WisdomTree, Inc.",
    "REALTY INCOME CORP", "SOME REALTY TRUST (THE)", "ELECTRON TRUST INC", None, "",
])
def test_companies_are_not_taken_for_funds(name):
    assert not alloc.looks_like_us_fund(name)


@pytest.mark.parametrize(("code", "name", "expected"), [
    ("VOO", "Vanguard S&P 500 ETF", "etf_foreign_equity"),
    ("SMH", "VanEck Semiconductor ETF", "etf_foreign_equity"),
    ("TQQQ", "ProShares UltraPro QQQ", "etf_leveraged"),
    ("SOXL", "Direxion Daily Semiconductor Bull 3X Shares", "etf_leveraged"),
    ("TLT", "iShares 20+ Year Treasury Bond ETF", "etf_bond"),
    ("JPST", "JPMorgan Ultra-Short Income ETF", "etf_other"),  # short-term, not leveraged
    ("GSY", "Invesco Ultra Short Duration ETF", "etf_other"),
    ("TBT", "ProShares UltraShort 20+ Year Treasury", "etf_leveraged"),
    ("SSO", "ProShares Ultra S&P500", "etf_leveraged"),
    ("TKNZ", "T. Rowe Price Active Crypto ETF", "etf_active"),
    ("GLD", "SPDR GOLD TRUST", "etf_other"),
    ("AGQ", "ProShares Trust II", "etf_other"),  # the registrant's name says no more
])
def test_us_etf_classes(code, name, expected):
    assert alloc.us_etf_class(code, name) == expected


def test_classify_reads_the_archived_profiles(engine):
    def tw(sym, name, type_="stock", industry=None, market="TWSE"):
        return InstrumentInfo(sym, sym.split(".")[0], name, market, type_, "TWD", industry)

    def us(sym, name, type_="stock"):
        return InstrumentInfo(sym, sym, name, "US", type_, "USD", None, source="sec-edgar")

    with Session(engine) as db:
        db.add_all([
            FundProfile(symbol="00646.TW", date=date(2026, 11, 12), source="twse-openapi",
                        values={"fund_type": "國外成分證券指數股票型基金"}),
            CompanyProfile(symbol="1216.TW", date=date(2026, 11, 12), industry_code="02", industry="食品工業",
                           source="twse-openapi", values={}),
            SecTicker(ticker="ABBV", cik=1551152, title="AbbVie Inc."),
            SecCompany(cik=1551152, name="AbbVie Inc.", profile={"sic": "2834"}),
            SecTicker(ticker="BRK-B", cik=1067983, title="BERKSHIRE HATHAWAY INC"),
            SecCompany(cik=1067983, name="BERKSHIRE HATHAWAY INC", profile={"sic": "6331"}),
            SecTicker(ticker="GLD", cik=1222333, title="SPDR GOLD TRUST"),
            SecCompany(cik=1222333, name="SPDR GOLD TRUST", profile={"sic": "6221"}),  # a fund, not 美股金融
            # a commodity / crypto pool whose name says nothing: SIC 6221 makes it a fund, never 美股金融
            SecTicker(ticker="EZBC", cik=1992870, title="Franklin Templeton Holdings Trust"),
            SecCompany(cik=1992870, name="Franklin Templeton Holdings Trust", profile={"sic": "6221"}),
            SecTicker(ticker="UVIX", cik=1884021, title="Volatility Shares Trust"),
            SecCompany(cik=1884021, name="Volatility Shares Trust", profile={"sic": "6221"}),
            SecTicker(ticker="LTCN", cik=1732406, title="Grayscale Litecoin Trust (LTC)"),
            SecCompany(cik=1732406, name="Grayscale Litecoin Trust (LTC)", profile={"sic": "6221"}),
        ])
        db.commit()
        infos = {
            "2330.TW": tw("2330.TW", "台積電", industry="半導體業"),
            "1216.TW": tw("1216.TW", "統一"),  # no industry in the catalog: the company profile's
            "9999.TW": None,  # no longer listed, nothing archived
            "00900.TW": None,  # an ETF code the catalog no longer lists
            "0050.TW": tw("0050.TW", "元大台灣50", "etf", "ETF"),
            "00646.TW": tw("00646.TW", "元大S&P500", "etf", "ETF"),
            "00679B.TWO": tw("00679B.TWO", "元大美債20年", "etf", "ETF", market="TPEX"),
            "AAPL": us("AAPL", "Apple", "stock"),  # the news vocabulary's own list
            "ABBV": us("ABBV", "AbbVie Inc."),  # SIC 2834
            "BRK.B": InstrumentInfo("BRK.B", "BRK.B", "BERKSHIRE HATHAWAY INC", "US", "stock", "USD"),
            "ZZZZ": us("ZZZZ", "Never Fetched Corp"),  # no SIC yet
            "GLD": us("GLD", "SPDR GOLD TRUST"),
            "VOO": us("VOO", "Vanguard S&P 500 ETF", "etf"),
            "EZBC": us("EZBC", "Franklin Templeton Holdings Trust"),
            "UVIX": us("UVIX", "Volatility Shares Trust"),
            "LTCN": us("LTCN", "Grayscale Litecoin Trust (LTC)"),
        }
        k = alloc.classify(db, "personal", infos)
        lean = alloc.classify(None, "personal", infos)  # no database: the catalog alone
    got = {s: (c.type, c.industry, c.label) for s, c in k.items()}
    assert got == {
        "2330.TW": ("stock", "半導體業", "半導體業"),
        "1216.TW": ("stock", "食品工業", "食品工業"),
        "9999.TW": ("stock", "unclassified", "未分類"),
        "00900.TW": ("etf", "etf_other", "ETF（未分類）"),
        "0050.TW": ("etf", "etf_tw_equity", "國內股票型 ETF"),
        "00646.TW": ("etf", "etf_foreign_equity", "海外股票型 ETF"),
        "00679B.TWO": ("etf", "etf_bond", "債券 ETF"),
        "AAPL": ("stock", "us_tech", "美股科技"),
        "ABBV": ("stock", "us_health", "美股醫療保健"),
        "BRK.B": ("stock", "us_financials", "美股金融"),
        "ZZZZ": ("stock", "unclassified", "未分類"),
        "GLD": ("etf", "etf_other", "ETF（未分類）"),
        "VOO": ("etf", "etf_foreign_equity", "海外股票型 ETF"),
        "EZBC": ("etf", "etf_other", "ETF（未分類）"),
        "UVIX": ("etf", "etf_other", "ETF（未分類）"),
        "LTCN": ("etf", "etf_other", "ETF（未分類）"),
    }
    assert lean["1216.TW"].industry == "unclassified" and lean["ABBV"].industry == "unclassified"
    assert lean["00646.TW"].industry == "etf_other" and lean["GLD"].industry == "etf_other"
    # types never depend on the archive, except a fund only its SIC 6221 tells (then 未分類 without it, never 美股金融)
    assert {s for s, c in lean.items() if c.type != k[s].type} == {"EZBC"}
    assert (lean["EZBC"].type, lean["EZBC"].industry) == ("stock", "unclassified")


def test_a_6221_fund_is_not_a_stock_for_concentration(engine):
    """A crypto trust filed under SIC 6221 is left out of 最大產業 and the 單一個股上限 like any ETF."""
    from types import SimpleNamespace

    with Session(engine) as db:
        db.add_all([SecTicker(ticker="EZBC", cik=1992870, title="Franklin Templeton Holdings Trust"),
                    SecCompany(cik=1992870, name="Franklin Templeton Holdings Trust", profile={"sic": "6221"})])
        db.commit()
        infos = {
            "EZBC": InstrumentInfo("EZBC", "EZBC", "Franklin Templeton Holdings Trust", "US", "stock", "USD", None),
            "AAPL": InstrumentInfo("AAPL", "AAPL", "Apple", "US", "stock", "USD", None),
        }
        k = alloc.classify(db, "personal", infos)
    rows = [SimpleNamespace(symbol="EZBC", market_value=Decimal(700), info=infos["EZBC"]),
            SimpleNamespace(symbol="AAPL", market_value=Decimal(300), info=infos["AAPL"])]
    c = alloc.concentration(rows, k, Decimal(1000), {"holding": 0.3, "industry": 0.3})
    assert c["top_holding"]["symbol"] == "EZBC" and c["top_holding"]["is_etf"] is True
    assert c["top_industry"] == {"key": "us_tech", "label": "美股科技", "weight": 0.3}
    assert c["etf_weight"] == 0.7 and c["over_limits"] == []  # 30% is not above 30%; the trust is no 個股


def test_limits_of_ignores_anything_out_of_range():
    from forliosa.models import User

    u = User(id="usr_x", email="x@x", display_name="x", preferences={"allocation_limits": {
        "holding": 0.3, "industry": 7}})
    assert alloc.limits_of(u) == {"holding": 0.3, "industry": None}
    u.preferences = {"allocation_limits": "30%"}
    assert alloc.limits_of(u) == {"holding": None, "industry": None}
    assert alloc.limits_of(None) == {"holding": None, "industry": None}


# -- the AI panel's 「會不會太集中」 ---------------------------------------------------------------------------------
def _conc(top=0.1, top3=0.2, industry=0.1, limits=None, over=()):
    return {"concentration": {"top_holding": {"weight": top}, "top3_weight": top3,
                              "top_industry": {"weight": industry} if industry is not None else None,
                              "limits": limits or {"holding": None, "industry": None}, "over_limits": list(over)}}


def test_concentration_question_uses_the_users_limits_when_set():
    from forliosa.ai.suggestions import concentrated

    h = [{"weight": 0.5}]
    assert not concentrated(h, _conc())
    assert concentrated(h, _conc(top=0.15)) and concentrated(h, _conc(top3=0.45))
    assert concentrated(h, _conc(industry=0.4))
    # the user's own limits replace the panel's cues: only what is above them counts
    assert not concentrated(h, _conc(top=0.6, top3=0.9, industry=0.8, limits={"holding": 0.7, "industry": None}))
    assert concentrated(h, _conc(limits={"holding": 0.05, "industry": None},
                                 over=[{"kind": "holding", "key": "2330.TW"}]))
    # an old summary without concentration: the holdings' weights
    assert concentrated([{"weight": 0.2}, {"weight": 0.1}], {}) and not concentrated([{"weight": 0.1}] * 10, None)


def test_ai_summary_tool_has_the_same_concentration(client, ledger, engine):
    import json

    from forliosa.ai.tools import ToolContext, execute
    from forliosa.marketdata.service import get_market_data
    from forliosa.models import User

    client.put(f"{API}/portfolio/allocation/limits", json={"holding": 0.05, "industry": None})
    with Session(engine) as db:
        me = db.query(User).filter(User.email == "demo@forliosa.local").one()
        out = execute(ToolContext(db=db, user=me, md=get_market_data()), "get_portfolio_summary", {})
    tool = json.loads(out.content)
    assert tool["concentration"] == _get(client)["concentration"]
    assert tool["concentration"]["over_limits"]
