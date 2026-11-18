"""Data packs (contract §6): ids, the data policy and the reports' own exclusions, the fixed missing items, the
official-index fallback, the premarket's evening and overnight data, the weekly's week, the blocks."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal as D

import pytest

from forliosa.config import get_settings
from forliosa.models import IndexDaily, MarketReport, MarketReportVersion, PriceDaily, TaifexFuturesDaily
from forliosa.reports import pack
from tests.reports.conftest import FRI, MON, TUE, ts

LATER = ts(date(2026, 11, 30), 10)  # "now" for rebuilds of past editions


def build(db, kind, d, cutoff=None, **kw):
    return pack.build(db, kind, d, cutoff=cutoff, policy="commercial", now=LATER, **kw)


def test_close_pack_ids_facts_and_blocks(market_db):
    built = build(market_db, "close", MON)
    pk = built.pack
    ids = [f["id"] for f in pk["facts"]]
    assert ids == [f"F{i:03d}" for i in range(1, len(ids) + 1)]  # sequential and unique
    assert pk["cutoff"] == "2026-11-16T15:40:00+08:00" and pk["publish_target"] == "2026-11-16T15:55:00+08:00"
    facts = {f["metric"]: f for f in pk["facts"] if f["group"] == "today"}
    assert facts["index_close"]["display"] == "41,040.08" and facts["index_close"]["subject"] == "加權指數"
    assert facts["index_pct"]["display"] == "▼6.03%" and facts["index_pct"]["value"] == pytest.approx(-0.0603)
    assert facts["index_close"]["dataset"] == "twse-opendata/index"
    assert facts["limit_down"]["display"] == "1 家"
    assert {m["key"] for m in pk["missing"]} >= set(pack.FIXED_MISSING)
    # stocks: the union of the rule lists, each with its facts; the comparison ETF
    by = {s["code"]: s for s in pk["stocks"]}
    assert "市值前 10" in by["2330"]["lists"] and set(by["2330"]["facts"]) == {"close", "pct", "contrib", "mcap",
                                                                              "value"}
    assert by["0050"]["lists"] == ["對照基準"]
    assert not any(x.startswith("漲幅") for x in by.get("4743", {}).get("lists", []))  # innovation board: not ranked
    contrib = next(f for f in pk["facts"] if f["id"] == by["2330"]["facts"]["contrib"])
    assert contrib["estimate"] and contrib["display"].endswith(" 點") and contrib["dataset"] == "rules:contribution"
    # sectors: 32-type list without composites, concentration noted
    names = {s["name"] for s in pk["sectors"]}
    assert "電子工業" not in names and "機電" not in names
    semi = next(s for s in pk["sectors"] if s["name"] == "半導體")
    assert semi["text_eligible"] and semi["concentration_fact"]
    # blocks
    charts = built.blocks["charts"]
    assert set(charts) >= {"G1", "G2", "G3", "G17", "G15", "G8"} and "G4" not in charts
    assert charts["G1"]["kind"] == "line" and charts["G1"]["since"] == "11/13 起"
    assert charts["G3"]["estimate"] and charts["G3"]["bars"][-1]["label"] == "其餘合計"
    assert charts["G3"]["reference"]["display"] == "−2,635.04 點"
    assert charts["G2"]["bars"][0]["value"] > charts["G2"]["bars"][-1]["value"]
    assert {"T2_top10", "T2_gainers", "T2_losers", "T2_value"} <= set(built.blocks["tables"])
    assert "創新板" in built.blocks["tables"]["T2_gainers"]["rule"]
    assert built.pack["fixed_charts"] == ["G1", "G17", "G15", "G2", "G8", "G3"]
    assert [m["code"] for m in built.pack["charts_menu"]] == ["G5"]
    assert [n["key"] for n in built.blocks["numbers"]][:3] == ["taiex", "tr", "otc"]
    assert set(pk["strip"]) <= set(ids)
    # filings after 14:00 of the 100 largest that existed at the cut-off
    assert [f["symbol"] for f in pk["filings"]] == ["2330.TW"]


def test_no_company_profile_field_but_the_short_name_enters_a_pack(market_db):
    text = json.dumps(build(market_db, "close", MON).pack, ensure_ascii=False)
    assert "不該出現的名字" not in text


def test_official_index_missing_uses_our_estimate_and_says_so(market_db):
    for row in market_db.query(IndexDaily).filter(IndexDaily.name == "發行量加權股價指數", IndexDaily.date == MON):
        market_db.delete(row)
    market_db.commit()
    built = build(market_db, "close", MON)
    assert "official_index_missing" in built.notes
    metrics = {f["metric"] for f in built.pack["facts"]}
    assert "index_close" not in metrics and "mcap_change_est" in metrics
    assert "G1" not in built.blocks["charts"] and built.blocks["notes"]["G1"] == "官方加權指數尚未取得"
    assert any(m["key"] == "official_index" for m in built.pack["missing"])


def test_conditional_taifex_quotes_and_the_yahoo_backfill_never_enter(market_db, monkeypatch):
    monkeypatch.setenv("TAIFEX_CONDITIONAL_CONFIRMED", "true")
    monkeypatch.setenv("PRICE_HISTORY_SOURCE", "yahoo")
    get_settings.cache_clear()
    market_db.add(TaifexFuturesDaily(trade_date=MON, session="regular", contract="TX", contract_month="202611",
                                     last=D("40885"), source="taifex-openapi"))
    market_db.add(PriceDaily(symbol="2603.TW", date=MON, close=D("200"), source="yahoo-history"))
    market_db.commit()
    try:
        built = build(market_db, "close", MON)
        datasets = {f["dataset"] for f in built.pack["facts"]}
        assert not any(d.startswith(("taifex-openapi/futures", "taifex-openapi/options", "yahoo")) for d in datasets)
        assert "2603" not in {s["code"] for s in built.pack["stocks"]}
        p = pack.Pack(market_db, built and pack.edition_on("close", MON), ts(MON, 15, 40), "commercial", False)
        assert not p.ok("taifex-openapi/futures_daily") and not p.ok("taifex-openapi/options_daily")
        assert not p.ok("yahoo-history/price") and p.ok("twse-openapi/price")
    finally:
        get_settings.cache_clear()


def test_premarket_overnight_evening_and_previous_session(market_db, us_on):
    # the previous close edition's title and highlights are passed on (not to be repeated)
    market_db.add(MarketReport(id="mrp_1", kind="close", edition_date=MON, period_start=MON, period_end=MON,
                               state="ai", visibility="public", current_version_id="mrv_1", notes=[]))
    market_db.add(MarketReportVersion(id="mrv_1", report_id="mrp_1", version=1, edition="ai",
                                      payload={"title": "加權指數重挫", "highlights": [{"sentences": [
                                          {"text": "加權指數 ▼6.03%", "refs": ["F003"]}]}]}))
    market_db.commit()
    built = build(market_db, "premarket", TUE)
    pk = built.pack
    groups = {}
    for f in pk["facts"]:
        groups.setdefault(f["group"], []).append(f)
    spy = next(f for f in groups["overnight"] if f["subject"] == "SPY" and f["metric"] == "us_pct")
    assert spy["label"] == "SPY 美股 11/16 收盤漲跌幅" and spy["display"] == "▲0.50%" and spy["date"] == "2026-11-16"
    assert any(f["subject"] == "台積電 ADR" for f in groups["overnight"])
    ev = {f["metric"]: f for f in groups["evening"]}
    assert ev["futures_oi_net"]["display"] == "淨空 96,787 口" and ev["futures_oi_change"]["display"] == "▼6,787 口"
    assert ev["pc_ratio_oi"]["display"] == "53.79%" and ev["fx_close"]["display"] == "32.886"
    assert ev["otc_inst_total"]["estimate"] and ev["otc_inst_total"]["display"].startswith("買超")
    assert {f["metric"] for f in groups["prev_session"]} >= {"index_close", "index_pct", "sector_pct"}
    assert pk["dates"]["us_sessions"] == ["2026-11-16"] and pk["dates"]["prev_session"] == ["2026-11-16"]
    assert pk["already_reported"] == [{"kind": "close", "edition_date": "2026-11-16", "title": "加權指數重挫",
                                      "highlights": ["加權指數 ▼6.03%"]}]
    assert set(built.blocks["charts"]) >= {"G6", "G7", "G17", "G15", "G2", "G8", "G16"}
    # G2_otc needs an industry of three OTC commons (this market has two and one)
    assert pk["fixed_charts"] == ["G6", "G17", "G15", "G2", "G8", "G7", "G16"]
    assert [m["code"] for m in pk["charts_menu"]] == ["G5"] and "G2_prev" not in built.blocks["charts"]
    g6 = built.blocks["charts"]["G6"]
    assert [b["label"] for b in g6["bars"]] == ["SPY", "DIA", "ONEQ", "SMH", "台積電 ADR"]
    assert "不是指數點數" in g6["notes"][0]
    g7 = built.blocks["charts"]["G7"]
    assert g7["kind"] == "columns" and g7["series"][1]["hidden"]
    assert "T_evening" not in built.blocks["tables"] and built.blocks["tables"]["T7"]["rows"]
    keys = [n["key"] for n in built.blocks["numbers"]]
    assert keys[:2] == ["spy", "dia"] and "tx_oi" in keys and "usdtwd" in keys
    # today's calendar: the ex-dividend rows and the settlement day are in, folded where they should be
    cal = built.blocks["calendar"]
    assert cal["title"] == "今日行事曆（11/17（二））"
    assert {c["kind"] for c in pk["calendar"]} >= {"ex_dividend", "investor_conference"}
    # nothing pretends to be an index level
    assert not re.search(r"(道瓊|那斯達克|費半|S&P)\S*\s*\d{1,3}(,\d{3})+", json.dumps(pk, ensure_ascii=False))


def test_us_closes_only_while_databento_is_served(market_db):
    built = build(market_db, "premarket", TUE)
    assert not any(f["dataset"].startswith("databento") for f in built.pack["facts"])
    assert "G6" not in built.blocks["charts"] and any(m["key"] == "us_prices" for m in built.pack["missing"])


def test_weekly_pack_for_the_week_of_the_16th(market_db, us_on):
    built = build(market_db, "weekly", date(2026, 11, 22))
    pk = built.pack
    assert pk["period"] == {"start": "2026-11-16", "end": "2026-11-20"}
    assert pk["next_period"] == {"start": "2026-11-23", "end": "2026-11-27"}
    week = {f["metric"]: f for f in pk["facts"] if f["group"] == "week" and f["subject"] == "加權指數"}
    assert week["week_pct"]["display"] == "▼6.03%" and week["week_points"]["display"] == "▼2,635.04"
    assert "2026-11-23" in pk["dates"]["next_period"]
    sectors = {s["name"]: s for s in pk["sectors"]}
    assert sectors["半導體"]["text_eligible"]
    t3 = built.blocks["tables"]["T3"]
    assert [r["cells"]["name"]["text"] for r in t3["rows"]] == [
        "加權指數", "報酬指數", "櫃買指數", "臺灣50", "中型100", "小型股300", "電子工業", "未含電子", "金融保險"]
    # the archive starts 11/13 here: 「近 1 月」 is 「11/13 起」 until 12/13
    assert [c["label"] for c in t3["columns"]] == ["指數", "1 週", "11/13 起"]
    assert t3["note"] == "近 1 月 12/13 起才有；在那之前是存檔起的漲跌"
    assert "G3" in built.blocks["charts"] and "G6" in built.blocks["charts"]
    us = next(f for f in pk["facts"] if f["subject"] == "SPY" and f["metric"] == "us_pct")
    assert us["label"] == "SPY 美股 11/16–11/16 漲跌幅" and us["display"] == "▲0.50%"
    # G17 needs every session's estimate (only Monday is archived), G8 every session's value, G16 every TPEx day
    assert pk["fixed_charts"] == ["G1", "G2", "G3", "G7", "G6"]
    # the week's turnover needs every session: only Monday is archived here, so there is no total
    assert not any(f["metric"] in ("turnover", "turnover_est") for f in pk["facts"])


def test_a_closed_week_gives_a_short_weekly(market_db):
    built = build(market_db, "weekly", date(2026, 11, 8))  # nothing archived for 11/2–11/6
    assert "week_not_archived" in built.notes
    # only the charts the page has (no US closes here, so not even G6)
    assert built.pack["fixed_charts"] == [] and built.blocks["calendar"]["title"] == "下週行事曆 11/9–11/13"


def test_no_edition_on_a_closed_day(market_db):
    with pytest.raises(ValueError):
        build(market_db, "close", date(2026, 11, 14))
    assert FRI < MON
