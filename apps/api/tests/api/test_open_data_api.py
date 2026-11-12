"""Open-data additions through the API under DATA_POLICY=commercial: derivatives (TAIFEX, with the conditional
licence gate), the ^TAIEXTR benchmark from the archive, dividend resolutions, company profiles, official ex-rights
reference prices, TAIFEX FX and /meta/attributions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

from forliosa.archive import Archiver
from forliosa.config import get_settings
from forliosa.marketdata.archive_provider import ArchiveProvider
from forliosa.marketdata.demo import DemoProvider
from forliosa.marketdata.service import MarketData, set_market_data
from forliosa.models import MarketEvent, PriceDaily, ReferencePrice, TaifexFuturesDaily
from tests.archive.fakes import NOW, FakeFetcher

API = "/api/v1"
TR_1110, TR_1111 = D("98767.01"), D("102340.20")  # MFI94U / MI_INDEX 發行量加權股價報酬指數


@pytest.fixture()
def archived(engine, market):
    """Every archive group on the 2026-11-12 fixtures, served by a commercial facade."""
    with Session(engine) as db:
        results = Archiver(db, FakeFetcher(), "commercial", now_fn=lambda: NOW).run()
        assert not [r for r in results if r.error and "t187ap0" not in r.name]
    md = MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine)), DemoProvider()],
                    policy="commercial")
    set_market_data(md)
    yield md
    set_market_data(market)


@pytest.fixture()
def confirmed(monkeypatch):
    """The owner set TAIFEX_CONDITIONAL_CONFIRMED=true (TAIFEX confirmed the licence in writing)."""
    monkeypatch.setattr(get_settings(), "taifex_conditional_confirmed", True)


def test_derivatives_overview_hides_conditional_datasets_by_default(client, archived):
    r = client.get(f"{API}/derivatives/overview")
    assert r.status_code == 200, r.text
    ov = r.json()
    assert ov["served"] == {"futures": False, "options_large_traders": False}
    assert ov["futures"] == [] and ov["large_traders"]["TXO"] is None
    assert any("授權待期交所確認" in n for n in ov["notes"])
    # OGDL datasets are served: put/call ratio, 三大法人, futures large traders
    pcr = ov["put_call_ratio"]
    assert (pcr["date"], pcr["oi_ratio"], pcr["volume_ratio"], pcr["oi_ratio_prev"]) == (
        "2026-11-11", 0.6517, 1.0708, 0.6654)
    tx = {x["investor"]: x for x in ov["institutional"]["TX"]}
    assert tx["foreign"]["oi_net"] == -104271 and tx["trust"]["oi_net"] == 101870
    txo = {x["investor"]: x for x in ov["institutional"]["TXO"]}
    assert txo["dealers"]["calls"]["oi_net"] == 8797 and txo["dealers"]["oi_net"] == 12094
    lt = ov["large_traders"]["TX"]
    assert lt["all_months"]["top5_net"] == 97108 - 64796 and lt["all_months"]["top10_net"] == 107422 - 92654
    assert lt["near_month"]["contract_month"] == "202611" and lt["all_months"]["specific"]["top10_net"] == (
        105270 - 92654)
    assert ov["as_of"] == "2026-11-11"
    srcs = " ".join(ov["sources"])
    assert "臺灣期貨交易所〈三大法人-區分各期貨契約-依日期〉" in srcs and "依政府資料開放授權條款第 1 版" in srcs
    assert "期貨每日交易行情" not in srcs


def test_derivatives_overview_with_confirmed_licence(client, archived, confirmed):
    ov = client.get(f"{API}/derivatives/overview").json()
    assert ov["served"] == {"futures": True, "options_large_traders": True}
    fut = {f["code"]: f for f in ov["futures"]}
    assert list(fut) == ["TX", "MTX", "TE", "TF"]
    tx = fut["TX"]
    assert tx["contract_month"] == "202611" and tx["name"] == "臺股期貨"
    assert (tx["regular"]["close"], tx["regular"]["change"], tx["regular"]["settlement_price"],
            tx["regular"]["open_interest"]) == (44091.0, 1445.0, 44136.0, 122326)
    assert (tx["after_hours"]["close"], tx["after_hours"]["change"]) == (42522.0, -124.0)
    assert tx["after_hours"]["settlement_price"] is None
    assert fut["MTX"]["contract_month"] == "202611"  # the weekly 202611W2 is not the near month
    calls = ov["large_traders"]["TXO"]["calls"]
    assert calls["market_oi"] == 88811 and calls["top5_net"] == 38323 - 47118
    assert any("期貨每日交易行情" in s for s in ov["sources"])


def test_futures_history_gate_rollover_and_validation(client, archived, engine, monkeypatch):
    r = client.get(f"{API}/derivatives/futures/TX/history?range=1M").json()
    assert r["series"] == [] and r["sources"] == [] and any("授權" in n for n in r["notes"])
    assert client.get(f"{API}/derivatives/futures/tx!/history").status_code == 422
    assert client.get(f"{API}/derivatives/futures/ZZZ/history").status_code == 404
    assert client.get(f"{API}/derivatives/futures/TX/history?range=2W").status_code == 422
    monkeypatch.setattr(get_settings(), "taifex_conditional_confirmed", True)
    with Session(engine) as db:  # October: on expiry day 202610 is still the near month, the day after 202611
        for d, month, last in ((date(2026, 10, 21), "202610", "41000"), (date(2026, 10, 21), "202611", "41100"),
                               (date(2026, 10, 22), "202611", "41500")):
            db.add(TaifexFuturesDaily(trade_date=d, session="regular", contract="TX", contract_month=month,
                                      last=D(last), source="taifex-openapi"))
        db.commit()
    h = client.get(f"{API}/derivatives/futures/TX/history?range=MAX").json()
    assert [(p["t"], p["contract_month"], p["close"]) for p in h["series"]] == [
        ("2026-10-21", "202610", 41000.0), ("2026-10-22", "202611", 41500.0), ("2026-11-11", "202611", 44091.0)]
    assert h["series"][-1]["after_hours"]["close"] == 42522.0 and h["series"][0]["after_hours"] is None
    assert h["name"] == "臺股期貨" and h["sources"]


def test_taiex_total_return_benchmark_comes_from_the_archive(client, archived, engine):
    with Session(engine) as db:
        db.add(PriceDaily(symbol="2330.TW", date=date(2026, 11, 10), close=D(2285), source="twse-openapi"))
        db.commit()
    acc = client.post(f"{API}/accounts", json={"name": "永豐", "currency": "TWD", "fee_discount": 0.28}).json()["id"]
    r = client.post(f"{API}/transactions", json={"account_id": acc, "symbol": "2330.TW", "type": "buy",
                                                 "trade_date": "2026-11-10", "quantity": 1000, "price": 2285})
    assert r.status_code == 201, r.text
    p = client.get(f"{API}/portfolio/performance?range=ALL&benchmark=^TAIEXTR").json()
    assert p["benchmark"]["symbol"] == "^TAIEXTR" and p["benchmark"]["name"] == "發行量加權股價報酬指數"
    assert p["benchmark"]["twr"] == pytest.approx(float(TR_1111 / TR_1110 - 1), abs=1e-6)
    assert [s["benchmark_index"] for s in p["series"]][-1] == pytest.approx(float(TR_1111 / TR_1110), abs=1e-6)
    assert not any("基準" in n for n in p["notes"])
    otc = client.get(f"{API}/portfolio/performance?range=ALL&benchmark=TPEXTR").json()
    assert otc["benchmark"]["symbol"] == "^TPEXTR" and otc["benchmark"]["twr"] == pytest.approx(
        640.08 / 619.37 - 1, abs=1e-6)


def test_dividends_and_events_include_board_resolutions(client, archived, engine):
    divs = client.get(f"{API}/instruments/2330/dividends").json()
    resolved = {d["period"]: d for d in divs if d["status"] == "resolved"}
    assert set(resolved) == {"2025Q4", "2026Q1", "2026Q2", "2026Q3"}
    q3 = resolved["2026Q3"]
    assert (q3["cash_dividend"], q3["ex_dividend_date"], q3["board_date"], q3["progress"]) == (
        9.0, None, "2026-11-10", "董事會決議")
    assert q3["cash_sources"] == {"earnings": 9.0, "legal_reserve": 0.0, "capital_surplus": 0.0}
    assert q3["sources"] == ["臺灣證券交易所〈上市公司股利分派情形〉（2026），依政府資料開放授權條款第 1 版"] or (
        q3["sources"][0].startswith("臺灣證券交易所〈上市公司股利分派情形〉"))
    assert divs[0]["period"] == "2026Q3"  # sorted by ex-date, else board date, newest first
    events = client.get(f"{API}/instruments/2330/events").json()
    res = [e for e in events if e["type"] == "dividend_resolution"]
    assert any(e["date"] == "2026-11-10" and "現金股利 9 元" in e["detail"] and "除權息日尚未公告" in e["detail"]
               for e in res)
    # once the ex-dividend notice appears, the resolution is attached to it (one record, not two)
    with Session(engine) as db:
        db.add(MarketEvent(key="tsmc-q2", symbol="2330.TW", date=date(2026, 12, 17), type="ex_dividend", title="除息",
                           detail="", data={"cash": "7.00000000", "stock_ratio": None}, source="twse-openapi"))
        db.commit()
    divs = client.get(f"{API}/instruments/2330/dividends").json()
    q2 = [d for d in divs if d["period"] == "2026Q2"]
    assert len(q2) == 1 and q2[0]["status"] == "announced" and q2[0]["ex_dividend_date"] == "2026-12-17"
    assert q2[0]["board_date"] == "2026-08-11" and len(q2[0]["sources"]) == 2


def test_capital_surplus_cash_is_split_out(engine, archived):
    from forliosa.services.stock import resolution_detail

    arch = ArchiveProvider("commercial", session_fn=lambda: Session(engine))
    tcc = arch.dividends("1101.TW")
    assert len(tcc) == 1 and tcc[0].cash_sources == (D(0), D(0), D("0.8")) and tcc[0].cash_dividend == D("0.8")
    text = resolution_detail(tcc[0])
    assert "現金股利 0.8 元（資本公積 0.8 元）" in text and "不屬股利所得" in text and "股東會 2026-05-22" in text


def test_overview_market_cap_from_official_shares(client, archived):
    ov = client.get(f"{API}/instruments/2330/overview").json()
    assert ov["shares_outstanding"] == 25932370067 and ov["listed_date"] == "1994-09-05"
    assert ov["market_cap"] == float(D(25932370067) * D("2395"))
    assert any("〈上市公司基本資料〉" in s for s in ov["sources"])
    detail = client.get(f"{API}/instruments/2330").json()
    assert detail["market_cap"] == ov["market_cap"] and detail["listed_date"] == "1994-09-05"


def test_official_ex_rights_reference_wins(engine, archived):
    with Session(engine) as db:
        db.merge(ReferencePrice(symbol="3680.TWO", date=date(2026, 11, 12), reference_price=D("430"),
                                limit_up=D("473"), limit_down=D("387"), source="tpex-openapi"))
        db.commit()
    arch = ArchiveProvider("commercial", session_fn=lambda: Session(engine))
    ref = arch.reference_prices(["3680.TWO", "2330.TW"], date(2026, 11, 12))
    assert ref["3680.TWO"][:3] == (D("425.50"), D("468.00"), D("383.50"))  # tpex_exright_daily
    assert ref["2330.TW"][0] == D("2395")  # TWT84U as before


def test_taifex_fx_is_gated_by_the_licence_setting(engine, archived, monkeypatch):
    from forliosa.services.ledger_io import FxBook
    from forliosa.services.portfolio import FX_PENDING_NOTE, fx_notes

    md = archived
    fx = FxBook.load(md, date(2026, 11, 1), date(2026, 11, 11))
    assert fx.fixed and fx.rate("USD", date(2026, 11, 11)) == D("31.5")
    assert fx_notes(fx, md) == [FX_PENDING_NOTE]
    monkeypatch.setattr(get_settings(), "taifex_conditional_confirmed", True)
    fx = FxBook.load(md, date(2026, 11, 1), date(2026, 11, 11))
    assert not fx.fixed and fx.rate("USD", date(2026, 11, 11)) == D("32.86") and fx.source == "taifex-openapi"
    assert fx_notes(fx, md) == ["USD/TWD 匯率：臺灣期貨交易所〈每日外幣參考匯率〉（2026），依政府資料開放授權條款第 1 版"]
    personal = ArchiveProvider("personal", session_fn=lambda: Session(engine), taifex_confirmed=False)
    assert personal.fx_history("USDTWD", date(2026, 11, 1), date(2026, 11, 11))  # non-commercial use: served


def test_attributions_list_licence_status_conditional_and_stale(client, archived, monkeypatch):
    meta = client.get(f"{API}/meta/attributions").json()
    served = {d["key"]: d for d in meta["datasets"]}
    pending = {d["key"]: d for d in meta["conditional"]}
    assert meta["taifex_conditional_confirmed"] is False
    assert "taifex-openapi/put_call_ratio" in served and served["taifex-openapi/put_call_ratio"]["license_status"] == (
        "ogdl")
    assert {"taifex-openapi/futures_daily", "taifex-openapi/fx", "taifex-openapi/options_daily",
            "taifex-openapi/large_traders_options"} <= set(pending)
    assert not set(pending) & set(served) and all(not d["served"] for d in pending.values())
    assert all(d["license_status"] == "conditional" and d["note"] for d in pending.values())
    assert served["twse-openapi/index"]["last_updated"] == "2026-11-11"
    assert served["taifex-openapi/put_call_ratio"]["attribution"] == (
        "臺灣期貨交易所〈臺指選擇權Put/Call比〉（2026），依政府資料開放授權條款第 1 版")
    stale = {s["key"]: s for s in meta["stale"]}
    assert stale["twse-openapi/breadth"]["last_updated"] == "2026-06-05"
    assert stale["tpex-openapi/dividend_resolution"]["last_updated"] == "2021-08-04"
    assert stale["taifex-openapi/final_settlement"]["last_updated"] == "2025-12-05"
    monkeypatch.setattr(get_settings(), "taifex_conditional_confirmed", True)
    meta = client.get(f"{API}/meta/attributions").json()
    assert meta["conditional"] == [] and "taifex-openapi/fx" in {d["key"] for d in meta["datasets"]}
