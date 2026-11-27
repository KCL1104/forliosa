"""Fixes from the 2026-11-17 dry run (pack, blocks, sources, labels): charts never show a day after the edition's data
day, one footnote per web page, the limit-move tables say they count their scope, the premarket keeps the previous
session's TPEx index out of the evening data and makes up no event, names without TWSE's 「*」, the attempt's key
slot on the shared pool, and the section label that says 「資料」 when tables or charts are there."""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal as D
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from forliosa.marketdata.base import Candle, HistoryResult, InstrumentInfo
from forliosa.models import AiUsage, CompanyProfile, MarketEvent, PriceDaily
from forliosa.reports import assemble, marketcalc, pack, pipeline, validate
from tests.reports.conftest import FRI, MON, TUE, ts
from tests.reports.helpers import INST_X, close_output, json_text, p, premarket_output, s, with_web
from tests.reports.test_pipeline import env, pk_close, report, runs, script_gather, tick  # noqa: F401 (env: fixture)

THU = date(2026, 11, 12)
TOP5 = ("2330.TW", "2317.TW", "2454.TW", "2308.TW", "2881.TW")


class FakeMd:
    """The few MarketData calls the compare chart makes, over the archive's closes (``end`` honoured like the real
    service: a day after ``end`` never comes back)."""

    policy = "commercial"

    def __init__(self, db: Session):
        self.db = db
        self.ends: list[date] = []

    def instrument(self, symbol: str) -> InstrumentInfo | None:
        code = symbol.split(".")[0]
        return InstrumentInfo(symbol, code, {"2330": "台積電", "2317": "鴻海", "2454": "聯發科", "2308": "台達電",
                                             "2881": "富邦金*"}.get(code, code), "TWSE", "stock", "TWD")

    def history(self, symbol: str, start: date, end: date, backfill: bool = False) -> HistoryResult:
        self.ends.append(end)
        rows = self.db.scalars(select(PriceDaily).where(PriceDaily.symbol == symbol, PriceDaily.date >= start,
                                                        PriceDaily.date <= end).order_by(PriceDaily.date))
        return HistoryResult(symbol, [Candle(r.date, r.close, r.close, r.close, r.close, 0) for r in rows], False,
                             "twse-openapi")

    def backfill_until(self, symbol: str) -> None:
        return None

    def archive_since(self, symbol: str | None = None) -> date:
        return THU

    def corporate_events(self, symbol: str) -> list[Any]:
        return []

    def us_prices_served(self) -> bool:
        return False


@pytest.fixture()
def later_closes(market_db):
    """Thursday 11/12 (so a month line has a start) and Tuesday 11/17 (a close after the premarket's cut-off)."""
    for sym in TOP5:
        market_db.add(PriceDaily(symbol=sym, date=THU, close=D("100"), volume=1, source="twse-openapi"))
        market_db.add(PriceDaily(symbol=sym, date=TUE, close=D("90"), volume=1, source="twse-opendata"))
    market_db.commit()
    return market_db


# -- P1-6: charts stop at the edition's data day ----------------------------------------------------------------------
def test_premarket_g5_stops_at_the_previous_session(later_closes, us_on, monkeypatch):
    import forliosa.ai.charts as charts_mod

    monkeypatch.setattr(charts_mod, "today_taipei", lambda: TUE)
    monkeypatch.setattr(pack, "now_taipei", lambda: ts(TUE, 6, 55))
    md_ = FakeMd(later_closes)
    built = pack.build(later_closes, "premarket", TUE, cutoff=ts(TUE, 6, 55), now=ts(TUE, 6, 55), md_=md_)
    g5 = built.blocks["charts"]["G5"]
    assert g5["title"] == "權值前 5 檔近 3 個交易日比較（至 11/16）"  # three sessions archived: not 「一個月」
    # the dry run's chart 「至 11/16」 ended on 11/17 (台積電 ▼2.03% that day)
    assert {pt["t"] for s_ in g5["series"] for pt in s_["points"]} <= {THU.isoformat(), FRI.isoformat(),
                                                                      MON.isoformat()}
    assert max(md_.ends) == MON  # the closes were read up to the data day, not to today
    assert built.pack["data_through"] == MON.isoformat()
    assert "富邦金" in {s_["name"] for s_ in g5["series"]}  # the 「*」 marker never reaches a chart either


def test_a_rebuilt_old_edition_still_draws_g5_up_to_its_own_day(later_closes, monkeypatch):
    """The old guard dropped G5 for any edition older than three days; now the chart is cut at the data day."""
    import forliosa.ai.charts as charts_mod

    monkeypatch.setattr(charts_mod, "today_taipei", lambda: date(2026, 11, 30))
    monkeypatch.setattr(pack, "now_taipei", lambda: ts(date(2026, 11, 30), 10))
    built = pack.build(later_closes, "close", MON, cutoff=ts(MON, 15, 40), now=ts(date(2026, 11, 30), 10),
                       md_=FakeMd(later_closes))
    g5 = built.blocks["charts"]["G5"]
    assert max(pt["t"] for s_ in g5["series"] for pt in s_["points"]) == MON.isoformat()


def test_every_dated_chart_is_cut_at_the_data_day():
    line = {"id": "G1", "kind": "line", "series": [{"name": "加權指數", "points": [
        {"t": "2026-11-13", "v": 1}, {"t": "2026-11-16", "v": 2}, {"t": "2026-11-17", "v": 3}]}]}
    cut = pack.clip_chart(line, MON)
    assert [pt["t"] for pt in cut["series"][0]["points"]] == ["2026-11-13", "2026-11-16"]
    assert line["series"][0]["points"][-1]["t"] == "2026-11-17"  # the input is left alone
    assert pack.clip_chart(line, FRI) is None  # one point left: nothing to draw
    bars = {"id": "G2", "kind": "bars", "series": [], "bars": [{"label": "半導體"}]}
    assert pack.clip_chart(bars, FRI) is bars
    compare = {"id": "G5", "kind": "compare", "series": [
        {"name": "A", "points": [{"t": "2026-11-13", "v": 0}, {"t": "2026-11-16", "v": 0.1}]},
        {"name": "B", "points": [{"t": "2026-11-16", "v": 0}, {"t": "2026-11-17", "v": 0.1}]}]}
    assert pack.clip_chart(compare, MON) is None  # one line left: no comparison


def test_the_extra_g5_of_the_writer_uses_the_pack_s_data_day(later_closes, us_on, monkeypatch):
    import forliosa.ai.charts as charts_mod

    monkeypatch.setattr(charts_mod, "today_taipei", lambda: TUE)
    pk = pack.build(later_closes, "premarket", TUE, cutoff=ts(TUE, 6, 55), now=ts(TUE, 6, 55)).pack
    pk = copy.deepcopy(pk)
    pk["stocks"] = [{"symbol": sym, "lists": ["跌幅前 5"]} for sym in TOP5]
    md_ = FakeMd(later_closes)
    deps = pipeline.Deps(session=lambda: later_closes, pool=None, submit=lambda fn: fn(), clock=lambda: ts(TUE, 7),
                         md=md_)
    out = pipeline._extra_charts("premarket", {"chart_of_day": {"code": "G5", "set": "losers"}}, pk, deps)
    card = out["G5:losers"]
    assert card["title"] == "跌幅前 5 檔近 3 個交易日比較（至 11/16）"
    assert max(pt["t"] for s_ in card["series"] for pt in s_["points"]) == MON.isoformat()


# -- P2-10: one footnote per page ---------------------------------------------------------------------------------
def test_facts_from_one_article_share_one_footnote_and_one_source_line(market_db):
    built = pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16))
    same = dict(INST_X, id="X002", key="TWSE_INST.trust", claim="〔中央社〕報導，投信賣超 179.63 億元。",
                url="https://www.cna.com.tw/news/afe/202611160123.aspx?utm_source=x#top")
    pk = with_web(built.pack, INST_X, same)
    out = close_output(pk)
    out["chips"] = [p(s("〔中央社〕報導，外資賣超 1,234.5 億元。", "X001"),
                      s("〔中央社〕報導，投信賣超 179.63 億元。", "X002"))]
    pk["research"] = [{"id": "W001", "symbol": "2330.TW", "session": MON.isoformat(),
                       "sources": [{"outlet": "中央社", "title": "外資賣超千億", "url": "http://cna.com.tw/news/afe/"
                                    "202611160123.aspx/", "published": None}], "quotes": ["…"]}]
    out["stocks"][0]["para"]["sentences"].append(s("〔中央社〕報導，外資賣超。", "W001"))
    pay = assemble.build(kind="close", report_id="mrp_x", edition_date=MON, period=(MON, MON), next_period=None,
                         version=1, edition="ai", pack=pk, blocks=built.blocks, output=out, published_at=ts(MON, 16),
                         first_published_at=None, as_of=ts(MON, 15, 40), title_origin="ai", highlights_origin="ai")
    pages = [f for f in pay["footnotes"] if f["kind"] in ("web", "research")]
    assert len(pages) == 1  # two X with a tracking parameter and a fragment, and a W on http without www.
    assert [w["url"] for w in pay["sources"]["web"]] == [INST_X["url"]]
    assert pay["sources"]["web"][0]["n"] == pages[0]["n"]
    chips = next(sec for sec in pay["sections"] if sec["key"] == "chips")
    cites = [st["cites"] for b in chips["blocks"] if b["type"] == "text" for pr in b["paragraphs"]
             for st in pr["sentences"]]
    assert cites[0] == cites[1] == [pages[0]["n"]]


# -- P2-11: the limit-move tables count their scope, the strip the whole market ------------------------------------
def test_many_limit_downs_say_they_are_counted_in_the_scope(market_db):
    ed = pack.edition_on("close", MON)
    pk = pack.Pack(market_db, ed, ts(MON, 15, 40), "commercial", False)
    pk.number("F001", {"key": "limits", "label": "漲停／跌停", "value": "6／30 家", "change": None, "tone": None,
                       "date_label": "11/16", "estimate": False, "note": None})
    day = marketcalc.load_day(market_db, "TWSE", MON, ts(MON, 15, 40))
    lists = marketcalc.rule_lists(market_db, day)
    lists.limit_down_many = 17
    pack._close_tables(pk, day, lists, MON, None)
    assert pk.blocks["tables"]["T2_losers"]["title"] == "範圍內跌停 17 家，其中市值最大的 5 檔（11/16）"
    assert pk.blocks["tables"]["T2_gainers"]["title"] == "漲幅前 5（11/16）"
    assert pk.blocks["numbers"][0]["note"] == pack.LIMITS_NOTE


# -- P2-12: a thin premarket -----------------------------------------------------------------------------------------
def test_premarket_tpex_index_is_a_previous_session_number(market_db, us_on):
    built = pack.build(market_db, "premarket", TUE, cutoff=ts(TUE, 6, 55), now=ts(TUE, 7))
    otc = [f for f in built.pack["facts"] if f["metric"] in ("otc_close", "otc_pct")]
    assert otc and {f["group"] for f in otc} == {"prev_session"}
    evening = {f["metric"] for f in built.pack["facts"] if f["group"] == "evening"}
    assert "otc_adv_up" in evening and not evening & {"otc_close", "otc_pct"}
    # so a title or a highlight that leads with it goes back for a revision
    out = premarket_output(built.pack)
    out["title"] = "櫃買指數 11/16 跌 6.80%，美元兌新台幣收 32.886 元"
    found = {(x.path, x.code) for x in validate.validate(out, built.pack, "premarket", ()) if x.hard}
    assert ("title", "repeats_close_report") in found


def test_premarket_watch_takes_real_events_only(market_db, us_on):
    built = pack.build(market_db, "premarket", TUE, cutoff=ts(TUE, 6, 55), now=ts(TUE, 7))
    assert pack.RULE_WATCH in built.pack["rules"] and pack.RULE_WATCH_EMPTY not in built.pack["rules"]
    market_db.execute(delete(MarketEvent))
    market_db.commit()
    thin = pack.build(market_db, "premarket", TUE, cutoff=ts(TUE, 6, 55), now=ts(TUE, 7))
    assert thin.pack["calendar"] == [] and pack.RULE_WATCH_EMPTY in thin.pack["rules"]


# -- P3 ------------------------------------------------------------------------------------------------------------
def test_names_lose_the_twse_star(market_db):
    market_db.add(CompanyProfile(symbol="2327.TW", date=FRI, industry_code="28", shares_outstanding=2_000_000_000,
                                 values={"short_name": "國巨*"}, source="twse-openapi"))
    market_db.add(CompanyProfile(symbol="4763.TW", date=FRI, industry_code="21", shares_outstanding=100_000_000,
                                 values={"short_name": "材料*-KY"}, source="twse-openapi"))
    for sym, close in (("2327.TW", ("300", "330")), ("4763.TW", ("500", "510"))):
        market_db.add(PriceDaily(symbol=sym, date=FRI, close=D(close[0]), volume=1, value=10**9,
                                 source="twse-openapi"))
        market_db.add(PriceDaily(symbol=sym, date=MON, close=D(close[1]), volume=1, value=10**9,
                                 source="twse-opendata"))
    market_db.commit()
    assert marketcalc.names_for(market_db, ["2327.TW", "4763.TW"]) == {"2327.TW": "國巨", "4763.TW": "材料-KY"}
    built = pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16))
    text = repr(built.pack) + repr(built.blocks)
    assert "國巨（2327）" in text and "*" not in text


def test_section_labels_say_data_where_the_server_s_tables_or_charts_are(market_db, us_on):
    built = pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16))
    pk = with_web(built.pack, INST_X)
    pay = assemble.build(kind="close", report_id="mrp_x", edition_date=MON, period=(MON, MON), next_period=None,
                         version=1, edition="ai", pack=pk, blocks=built.blocks, output=close_output(pk),
                         published_at=ts(MON, 16), first_published_at=None, as_of=ts(MON, 15, 40),
                         title_origin="ai", highlights_origin="ai")
    by = {sec["key"]: sec for sec in pay["sections"]}
    # AI text under the server's chart or tables: still an AI section, labelled as data
    assert by["stocks"]["origin"] == "ai" and by["stocks"]["origin_label"] == "資料"
    # 「今天發生什麼」 is AI text alone since the TAIEX chart moved under the brief (2026-11-27)
    assert by["what_happened"]["origin"] == "ai" and by["what_happened"]["origin_label"] == "AI 依資料與報導整理"
    assert pay["trend"]["id"] == "G1"
    # AI text alone
    assert by["chips"]["origin_label"] == "AI 依資料與報導整理"
    pre = pack.build(market_db, "premarket", TUE, cutoff=ts(TUE, 6, 55), now=ts(TUE, 7))
    ppk = with_web(pre.pack, INST_X)
    ppay = assemble.build(kind="premarket", report_id="mrp_y", edition_date=TUE, period=(TUE, TUE),
                          next_period=None, version=1, edition="ai", pack=ppk, blocks=pre.blocks,
                          output=premarket_output(ppk), published_at=ts(TUE, 7), first_published_at=None,
                          as_of=ts(TUE, 6, 55), title_origin="ai", highlights_origin="ai")
    pby = {sec["key"]: sec for sec in ppay["sections"]}
    assert pby["chips"]["origin"] == "ai" and pby["chips"]["origin_label"] == "資料"
    assert pby["yesterday"]["origin"] == "data" and pby["yesterday"]["origin_label"] == "資料"
    assert pby["watch"]["origin_label"] == "AI 依資料與報導整理"
    # a table version keeps the label right
    again = assemble.retable(pay, "close", built.pack, built.blocks, version=2, published_at=ts(MON, 23, 46),
                             as_of=ts(MON, 23, 46))
    labels = {sec["key"]: sec["origin_label"] for sec in again["sections"]}
    assert labels["stocks"] == "資料" and labels["what_happened"] == "AI 依資料與報導整理"
    # the brief stays as it was written (its footnote numbers are the version's own); the trend chart is redrawn
    assert again["brief"] == pay["brief"] and again["highlights"] == pay["highlights"] and again["trend"]["id"] == "G1"


def test_the_attempt_records_its_key_slot_on_the_shared_pool(env):  # noqa: F811 (the imported fixture)
    """No reserved slot: the pool picks one at the first call; the run keeps it, like its ai_usage rows."""
    fake = env["fake"]
    tick(env, ts(MON, 14, 11))
    script_gather(fake)
    tick(env, ts(MON, 15, 41))
    fake.reply(json_text(close_output(with_web(pk_close(env))))).reply(json_text({"issues": []}))
    tick(env, ts(MON, 15, 51))
    [run] = runs(env, report(env).id)
    assert run.status == "ok" and run.key_slot == 1
    with Session(env["engine"]) as db:
        assert {u.key_slot for u in db.scalars(select(AiUsage).where(AiUsage.thread_id == run.id))} == {1}


