"""Open-data additions through the API under DATA_POLICY=commercial: derivatives (TAIFEX, with the conditional
licence gate), the ^TAIEXTR benchmark from the archive, dividend resolutions, company profiles, official ex-rights
reference prices, USD/TWD from the central bank (TAIFEX FX archived only) and /meta/attributions."""

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
from forliosa.services import instruments
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


def test_dividends_and_events_include_board_resolutions(client, archived, engine, monkeypatch):
    monkeypatch.setattr(instruments, "today_taipei", lambda: NOW.date())
    divs = client.get(f"{API}/instruments/2330/dividends").json()
    resolved = {d["period"]: d for d in divs if d["status"] == "resolved"}
    # resolutions without a notice only while the board date is within 180 days (2-6): 2025Q4 (board 2026-02-10)
    # and 2026Q1 (2026-05-12) went ex before archiving started and would look pending
    assert set(resolved) == {"2026Q2", "2026Q3"}
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


def test_resolution_window_is_180_days_from_the_board_date():
    from forliosa.marketdata.base import DividendEvent

    today = date(2026, 11, 14)

    def ev(**kw) -> DividendEvent:
        return DividendEvent("2330.TW", 2026, "2026Q1", D(5), D(0), kw.pop("ex", None), None, **kw)

    assert instruments.resolution_shown(ev(board_date=date(2026, 5, 18)), today)  # exactly 180 days
    assert not instruments.resolution_shown(ev(board_date=date(2026, 5, 17)), today)
    assert instruments.resolution_shown(ev(meeting_date=date(2026, 6, 1)), today)  # no board date: the AGM date
    assert not instruments.resolution_shown(ev(), today)  # neither date: cannot tell how old it is
    # a notice is always listed, however old its resolution
    assert instruments.resolution_shown(ev(ex=date(2025, 7, 1), board_date=date(2025, 2, 10)), today)


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


CBC_NOTE = "USD/TWD 匯率：中央銀行〈銀行間新臺幣對美元收盤匯率〉（2026），依政府資料開放授權條款第 1 版"


def test_fx_uses_the_central_bank_series_in_every_mode(engine, archived, monkeypatch):
    from forliosa.models import FxRate
    from forliosa.services.ledger_io import FxBook
    from forliosa.services.portfolio import fx_notes

    md = archived
    fx = FxBook.load(md, date(2026, 11, 1), date(2026, 11, 12))
    assert not fx.fixed and fx.source == "cbc-opendata"
    assert fx.rate("USD", date(2026, 11, 11)) == D("32.86") and fx.latest("USD") == D("32.889")
    assert fx.rate("USD", date(2026, 11, 8)) == D("32.768")  # a Sunday: Friday's close
    assert fx_notes(fx, today=date(2026, 11, 12)) == [CBC_NOTE]
    # TAIFEX's reference rate is archived (other pairs too) but never used, whatever the licence setting says
    with Session(engine) as db:
        assert db.get(FxRate, ("CNYTWD", date(2026, 11, 11))).source == "taifex-openapi"
        assert db.get(FxRate, ("USDTWD", date(2026, 11, 11))).source == "cbc-opendata"
    monkeypatch.setattr(get_settings(), "taifex_conditional_confirmed", True)
    assert FxBook.load(md, date(2026, 11, 1), date(2026, 11, 12)).source == "cbc-opendata"
    for policy in ("commercial", "personal"):
        arch = ArchiveProvider(policy, session_fn=lambda: Session(engine), taifex_confirmed=True)
        series = arch.fx_history("USDTWD", date(2026, 11, 1), date(2026, 11, 12))
        assert series[date(2026, 11, 12)] == D("32.889") and arch.sources_for("fx_history", "USDTWD") == [
            "cbc-opendata"]
        assert arch.fx_history("CNYTWD", date(2026, 11, 1), date(2026, 11, 12)) is None
    # the series begins 2008-01-02: an older trade uses that first rate
    old = FxBook.load(md, date(2007, 6, 1), date(2026, 11, 12))
    assert old.rate("USD", date(2007, 6, 1)) == D("32.443")


def test_fx_falls_back_to_the_documented_fixed_rate(engine):
    from forliosa.services.ledger_io import FX_FALLBACK, FxBook
    from forliosa.services.portfolio import FX_MISSING_NOTE, fx_notes

    md = MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine)), DemoProvider()],
                    policy="commercial")
    fx = FxBook.load(md, date(2026, 11, 1), date(2026, 11, 12))
    assert fx.fixed and fx.latest_point() is None and fx_notes(fx) == []  # no US amount converted yet
    assert fx.rate("USD", date(2026, 11, 11)) == FX_FALLBACK == D("31.5")
    assert fx_notes(fx) == [FX_MISSING_NOTE] and "中央銀行" in FX_MISSING_NOTE


def test_fx_note_says_when_the_series_stopped(archived):
    from forliosa.services.ledger_io import FxBook
    from forliosa.services.portfolio import fx_notes, fx_tool_notes

    fx = FxBook.load(archived, date(2026, 11, 1), date(2026, 11, 12))
    fx.latest("USD")
    assert fx_notes(fx, today=date(2026, 11, 25)) == [CBC_NOTE]  # 13 days: still fine
    stale = [CBC_NOTE, "USD/TWD 匯率只到 2026-11-12（32.889），之後的日子沿用這個匯率"]
    assert fx_notes(fx, today=date(2026, 11, 26)) == stale  # 14 days or more (「比今天早 14 天以上」)
    assert fx_notes(fx, today=date(2026, 11, 27)) == stale
    assert fx_tool_notes(fx, today=date(2026, 11, 12)) == [
        CBC_NOTE, "美股市值以 2026-11-12 的 USD/TWD 32.889 換算成新台幣；成本、已實現損益與股利用各交易日的匯率"]
    assert fx_tool_notes(FxBook(), today=date(2026, 11, 12)) == []  # no US amount: nothing to say


def test_a_stalled_archive_carries_its_last_rate_forward(client, engine, market, monkeypatch):
    """The archive stopped on 2026-10-09 (worker down, or the endpoint renamed its fields): every user values USD
    at that last rate with the stale note, never at the fixed 31.5 with "no archive", whenever they started."""
    import json

    from forliosa.ai.tools import ToolContext, execute
    from forliosa.models import FxRate, User
    from forliosa.services import ledger_io
    from forliosa.services import portfolio as psvc
    from forliosa.services.ledger_io import FxBook
    from forliosa.services.portfolio import FX_MISSING_NOTE, fx_notes

    today = date(2026, 11, 12)
    monkeypatch.setattr(psvc, "today_taipei", lambda: today)
    monkeypatch.setattr(ledger_io, "today_taipei", lambda: today)
    with Session(engine) as db:
        for d, rate, source in ((date(2025, 2, 27), "32.8", "cbc-opendata"),
                                (date(2026, 10, 8), "31.95", "cbc-opendata"),
                                (date(2026, 10, 9), "31.9", "cbc-opendata"),
                                (date(2026, 11, 11), "32.86", "taifex-openapi")):  # archived, never used
            db.add(FxRate(pair="USDTWD", date=d, rate=D(rate), source=source))
        db.commit()
    md = MarketData([ArchiveProvider("commercial", session_fn=lambda: Session(engine)), DemoProvider()],
                    policy="commercial")
    stale = "USD/TWD 匯率只到 2026-10-09（31.9），之後的日子沿用這個匯率"
    # only the newest earlier row is carried into the window, not the whole history
    arch = ArchiveProvider("commercial", session_fn=lambda: Session(engine))
    assert arch.fx_history("USDTWD", date(2026, 11, 3), today) == {date(2026, 10, 9): D("31.9")}
    assert arch.fx_history("USDTWD", date(2025, 3, 1), date(2025, 3, 31)) == {date(2025, 2, 27): D("32.8")}
    assert arch.fx_history("USDTWD", date(2025, 1, 1), date(2025, 1, 31)) is None  # before the series begins
    for first_trade in (date(2025, 3, 1), date(2026, 11, 3), today):
        fx = FxBook.load(md, first_trade)
        assert not fx.fixed and fx.source == "cbc-opendata", first_trade
        assert fx.latest("USD") == D("31.9") and fx.rate("USD", date(2026, 11, 11)) == D("31.9"), first_trade
        assert fx_notes(fx) == [CBC_NOTE, stale], first_trade
    assert FxBook.load(md, date(2025, 3, 1)).rate("USD", date(2025, 3, 3)) == D("32.8")

    set_market_data(md)
    try:
        acc = client.post(f"{API}/accounts", json={"name": "Firstrade", "broker": "Firstrade", "currency": "USD"})
        r = client.post(f"{API}/transactions", json={"account_id": acc.json()["id"], "symbol": "AAPL", "type": "buy",
                                                     "trade_date": "2026-11-03", "quantity": 10, "price": 200})
        assert r.status_code == 201, r.text
        paid = D(str(r.json()["amount"])) + D(str(r.json()["fee"]))
        h = client.get(f"{API}/portfolio/holdings").json()[0]
        assert h["cost_basis"] == pytest.approx(float(paid * D("31.9")), abs=0.01)
        assert h["market_value"] == pytest.approx(float(paid * D("31.9")), abs=0.01)
        pos = client.get(f"{API}/instruments/AAPL/position").json()
        assert pos["market_value"] == h["market_value"]
        with Session(engine) as db:
            me = db.query(User).filter_by(email="demo@forliosa.local").one()
            ctx = ToolContext(db=db, user=me, md=md)
            rate_line = "美股市值以 2026-10-09 的 USD/TWD 31.9 換算成新台幣；成本、已實現損益與股利用各交易日的匯率"
            for tool, args in (("get_holdings", {}), ("get_portfolio_summary", {}),
                               ("get_position", {"symbol": "AAPL"})):
                out = json.loads(execute(ctx, tool, args).content)
                assert out["notes"][-3:] == [CBC_NOTE, stale, rate_line] and FX_MISSING_NOTE not in out["notes"], (
                    tool, out["notes"])
            assert json.loads(execute(ctx, "get_position", {"symbol": "AAPL"}).content)["market_value_twd"] == (
                pos["market_value"])
    finally:
        set_market_data(market)


def test_us_holdings_are_valued_with_the_central_bank_rate(client, archived, engine):
    import json

    from forliosa.ai.tools import ToolContext, execute
    from forliosa.models import User

    r = client.post(f"{API}/accounts", json={"name": "Firstrade", "broker": "Firstrade", "currency": "USD"})
    assert r.status_code == 201, r.text
    r = client.post(f"{API}/transactions", json={"account_id": r.json()["id"], "symbol": "AAPL", "type": "buy",
                                                 "trade_date": "2026-11-03", "quantity": 10, "price": 200})
    assert r.status_code == 201, r.text
    paid = D(str(r.json()["amount"])) + D(str(r.json()["fee"]))
    h = client.get(f"{API}/portfolio/holdings").json()[0]
    # cost at the trade date's closing rate (2026-11-03: 32.76); no US quote under commercial, so the market
    # value is the cost in USD at the newest rate (2026-11-12: 32.889)
    assert h["cost_basis"] == pytest.approx(float(paid * D("32.76")), abs=0.01)
    assert h["market_value"] == pytest.approx(float(paid * D("32.889")), abs=0.01)
    pos = client.get(f"{API}/instruments/AAPL/position").json()
    assert CBC_NOTE.removeprefix("USD/TWD 匯率：") in pos["sources"]
    with Session(engine) as db:
        me = db.query(User).filter_by(email="demo@forliosa.local").one()
        ctx = ToolContext(db=db, user=me, md=archived)
        rate_line = "美股市值以 2026-11-12 的 USD/TWD 32.889 換算成新台幣；成本、已實現損益與股利用各交易日的匯率"
        for tool, args in (("get_holdings", {}), ("get_portfolio_summary", {}), ("get_position", {"symbol": "AAPL"})):
            notes = json.loads(execute(ctx, tool, args).content)["notes"]
            assert CBC_NOTE in notes and rate_line in notes, (tool, notes)


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
    cbc = served["cbc-opendata/fx"]
    assert cbc["attribution"] == "中央銀行〈銀行間新臺幣對美元收盤匯率〉（2026），依政府資料開放授權條款第 1 版"
    assert (cbc["agency"], cbc["license_status"], cbc["license_basis"], cbc["commercial"], cbc["last_updated"]) == (
        "中央銀行", "ogdl", "data.gov.tw 7232", True, "2026-11-12")
    assert cbc["url"] == "https://cpx.cbc.gov.tw/api/OpenData/FTDOpenData_Day"
    assert "只存檔" in pending["taifex-openapi/fx"]["used_for"]
    stale = {s["key"]: s for s in meta["stale"]}
    assert stale["twse-openapi/breadth"]["last_updated"] == "2026-06-05"
    assert stale["tpex-openapi/dividend_resolution"]["last_updated"] == "2021-08-04"
    assert stale["taifex-openapi/final_settlement"]["last_updated"] == "2025-12-05"
    monkeypatch.setattr(get_settings(), "taifex_conditional_confirmed", True)
    meta = client.get(f"{API}/meta/attributions").json()
    assert meta["conditional"] == [] and "taifex-openapi/fx" in {d["key"] for d in meta["datasets"]}
