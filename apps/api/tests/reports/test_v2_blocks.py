"""Market reports v2 phase 1 (spec 2026-11-18) on the conftest market (made-up numbers): the new blocks' shapes,
when each one is there (the premarket only from the previous session, the 15:40 close without TPEx or TAIFEX), the
period chips and their archive limits, the chained moves of T2_top10 v2, the margin table, the weekly additions, the
duplicates taken out, the writer's instructions and the new fact's check."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from forliosa.datapolicy import label
from forliosa.models import IndexDaily, InstitutionalDaily, MarginDaily, MarketTurnoverDaily, PriceDaily, ReferencePrice
from forliosa.reports import assemble, pack, prompts, timing, validate
from forliosa.reports import blocks as B
from forliosa.reports import marketcalc as mc
from forliosa.timeutil import tw_trading_days
from tests.reports.conftest import FRI, MON, SECTORS_MON, STYLE_MON, TPEX, TUE, TWSE, ts
from tests.reports.helpers import fid, p, s

A1_WORDS = ("強勢", "弱勢", "偏高", "偏低", "資金流向")
NEW_CHARTS = ("G17", "G15", "G2", "G8", "G16", "G2_otc")


def build(db, kind, d, cutoff):
    return pack.build(db, kind, d, cutoff=cutoff, now=cutoff)


def seed_index_day(db, d: date, factor: str, *, taiex: bool = True) -> None:
    """Sector, style and TAIEX closes on an earlier day ``d`` (for the period chips): ``factor`` × Friday's 100."""
    f = D(factor)
    for name in [*(f"{n}類指數" for n in SECTORS_MON), *STYLE_MON]:
        db.add(IndexDaily(name=name, date=d, market="TWSE", close=D("100") * f, change=D("0"), change_pct=D("0"),
                          source="twse-openapi"))
    if taiex:
        db.add(IndexDaily(name=mc.TAIEX, date=d, market="TWSE", close=D("43675.12") * f, change=D("0"),
                          change_pct=D("0"), source="twse-openapi"))


@pytest.fixture()
def otc3(market_db):
    """A third OTC semiconductor (an industry needs three commons to get a bar in G2_otc)."""
    market_db.add_all([
        PriceDaily(symbol="3105.TWO", date=FRI, close=D("100"), volume=1, value=1_000_000, source="tpex-openapi"),
        PriceDaily(symbol="3105.TWO", date=MON, close=D("97"), volume=1, value=1_000_000, source="tpex-openapi"),
    ])
    from forliosa.models import CompanyProfile

    market_db.add(CompanyProfile(symbol="3105.TWO", date=FRI, industry_code="24", industry=None,
                                 shares_outstanding=400_000_000, values={"short_name": "穩懋"}, source="tpex-openapi"))
    market_db.add(InstitutionalDaily(symbol="3105.TWO", date=MON, foreign_net=-300_000, trust_net=0, dealer_net=0,
                                     total_net=-300_000, source="tpex-openapi"))
    market_db.commit()
    return market_db


# -- shared pieces ----------------------------------------------------------------------------------------------------
def test_chart_and_table_extensions_stay_out_of_old_charts():
    old = B.chart("G1", "line", "t", "index", "date")
    assert not {"bench", "fold", "views", "aside_label"} & set(old)
    bar = B.bar("半導體", D("-0.02"), "▼2.00%", "fall")
    assert "aside" not in bar and "group" not in bar
    t = B.table("T", "t", [("a", "A", "left", False)], [])
    assert "tab_group" not in t and "tab_label" not in t
    assert B.table("T", "t", [], [], tab_group="movers", tab_label="漲幅")["tab_label"] == "漲幅"
    assert [B.heat(D(x), "1d") for x in ("0.005", "0.01", "-0.0299", "0.03", "-0.2")] == \
        [None, "rise1", "fall1", "rise2", "fall2"]
    assert [B.heat(D(x), "1w") for x in ("0.019", "-0.02", "0.05")] == [None, "fall1", "rise2"]
    assert [B.heat(D(x), "1m") for x in ("0.039", "0.04", "-0.10")] == [None, "rise1", "fall2"]
    assert B.move_cell(None, "1w") == {"text": "—"}  # never 0
    assert B.move_cell(D("0"), "1d") == {"text": "0.00%", "tone": None}
    assert [B.pp_text(D(x)) for x in ("0.0222", "-0.0066", "0.0004")] == ["+2.2", "−0.7", "0.0"]


# -- the close: 15:40 and 23:45 ---------------------------------------------------------------------------------------
def test_close_1540_blocks_and_their_order(market_db):
    built = build(market_db, "close", MON, ts(MON, 15, 40))
    charts, tables = built.blocks["charts"], built.blocks["tables"]
    assert {"G17", "G15", "G2", "G8"} <= set(charts)
    # TPEx closes 23:40, TAIFEX 21:45: nothing of theirs at 15:40
    assert not {"G16", "G2_otc"} & set(charts) and not {"T7", "T8", "T5_top10"} & set(tables)
    g17 = charts["G17"]
    assert g17["unit"] == "points" and g17["estimate"] and g17["reference"]["label"] == "官方漲跌"
    assert g17["reference"]["display"].startswith("−2,635.04 點・")
    day = mc.load_day(market_db, "TWSE", MON, ts(MON, 15, 40))
    contribs = mc.sector_contributions(day, D("43675.12"))
    assert abs(sum(c.weight for c in contribs) - 1) < D("1e-9")
    assert abs(sum(c.points for c in contribs) - sum(mc.contributions(day, D("43675.12")).values())) < D("1e-9")
    g15 = charts["G15"]
    assert [b["label"] for b in g15["bars"]] == ["臺灣50", "中型100", "小型股300", "電子工業", "未含電子", "金融保險",
                                                  "臺灣高股息", "櫃買指數"]
    assert g15["bench"]["label"] == "加權 ▼6.03%"
    g2 = charts["G2"]
    assert g2["bench"] == {"value": -0.0603, "label": "加權 ▼6.03%"} and g2["fold"]["keep"] == ["半導體"]
    br = mc.breadth(day)
    ups = sum(int(b["sub"].split("漲 ")[1].split("・")[0]) for b in g2["bars"] if b["sub"])
    downs = sum(int(b["sub"].split("跌 ")[1].split("・")[0]) for b in g2["bars"] if b["sub"])
    # the sectors with an index carry every listed common of theirs (台泥, 富邦金 … included)
    assert ups <= br.up and downs <= br.down and ups + downs > 0
    g8 = charts["G8"]
    assert g8["aside_label"] == "較前一日" and abs(sum(b["value"] for b in g8["bars"]) - 1) < 1e-9
    commons = sum(q.value for q in day.commons() if q.value)
    assert g8["notes"][0].startswith(f"分母是上市普通股的成交金額 {B.yi_text(commons)}")  # no ETF in it
    for b in g8["bars"]:
        if b["sub"] and "占這一類" in b["sub"]:
            assert int(b["sub"].split("占這一類 ")[1].split("%")[0]) > 50
    pay = assemble.build(kind="close", report_id="r", edition_date=MON, period=(MON, MON), next_period=None,
                         version=1, edition="data", pack=built.pack, blocks=built.blocks, output=None,
                         published_at=ts(MON, 16), first_published_at=None, as_of=ts(MON, 15, 40))
    by = {s_["key"]: s_ for s_ in pay["sections"]}
    assert [b["chart"]["id"] for b in by["sectors"]["blocks"]] == ["G17", "G15", "G2", "G8"]
    assert [(b["type"], (b.get("chart") or b.get("table"))["id"]) for b in by["stocks"]["blocks"]] == \
        [("chart", "G3"), ("table", "T2_top10"), ("table", "T2_gainers"), ("table", "T2_losers"),
         ("table", "T2_value")]


def test_close_2345_adds_tpex_by_industry_and_otc_bars(otc3):
    built = build(otc3, "close", MON, ts(MON, 23, 45))
    charts, tables = built.blocks["charts"], built.blocks["tables"]
    g16 = charts["G16"]
    assert g16["unit"] == "yi" and g16["estimate"] and g16["reference"]["label"] == "上櫃三大法人合計（估算）"
    assert [b["label"] for b in g16["bars"]] == ["半導體", "光電"]  # 環球晶 + 世界 − 穩懋; 元太
    assert {b["tone"] for b in g16["bars"]} <= {"ink", "pencil"}
    otc = charts["G2_otc"]
    assert otc["estimate"] and "Forliosa 計算" in otc["title"] and otc["fold"] == {"head": 5, "tail": 5, "keep": []}
    assert [(b["label"], b["sub"]) for b in otc["bars"]] == [("半導體", "3 家")]
    assert otc["reference"] == {"label": "上櫃普通股", "display": "上漲 1・下跌 3・平盤 0 家"}
    assert "T6" not in tables  # the OTC sector table became G2_otc (one drawing of one set of data)
    assert tables["T5_gainers"]["tab_group"] == tables["T5_losers"]["tab_group"] == "otc_movers"
    pay = assemble.build(kind="close", report_id="r", edition_date=MON, period=(MON, MON), next_period=None,
                         version=1, edition="tables", pack=built.pack, blocks=built.blocks, output=None,
                         published_at=ts(MON, 23, 46), first_published_at=None, as_of=ts(MON, 23, 45))
    by = {s_["key"]: s_ for s_ in pay["sections"]}
    assert by["chips"]["blocks"][-1]["chart"]["id"] == "G16"
    assert by["otc"]["blocks"][-1]["chart"]["id"] == "G2_otc"


def test_movers_are_three_tabs_and_top10_has_no_contribution_column(market_db):
    built = build(market_db, "close", MON, ts(MON, 15, 40))
    tables = built.blocks["tables"]
    assert [(tables[t]["tab_group"], tables[t]["tab_label"]) for t in ("T2_gainers", "T2_losers", "T2_value")] == \
        [("movers", "漲幅"), ("movers", "跌幅"), ("movers", "成交值")]
    top = tables["T2_top10"]
    assert [c["key"] for c in top["columns"]] == ["stock", "d1", "w1", "m1"]
    assert top["rows"][0]["cells"]["stock"]["text"] == "加權指數" and top["rows"][0]["href"] is None
    tsmc = top["rows"][1]["cells"]
    assert tsmc["d1"] == {"text": "▼4.67%", "tone": "fall", "heat": "fall2"}
    assert tsmc["w1"] == {"text": "—"} and "11/13" in top["note"]  # the archive starts on Friday here


# -- the premarket: the previous session only ------------------------------------------------------------------------
def test_premarket_uses_the_previous_session_only(otc3):
    # Tuesday's closes exist (14:00 Tuesday) but the premarket's cut-off is 06:55 Tuesday
    for code in TWSE:
        otc3.add(PriceDaily(symbol=f"{code}.TW", date=TUE, close=D("1"), volume=1, value=1, source="twse-opendata"))
    otc3.add(IndexDaily(name="半導體類指數", date=TUE, market="TWSE", close=D("1"), change=D("-99"),
                        change_pct=D("0.99"), source="twse-opendata"))
    otc3.commit()
    built = build(otc3, "premarket", TUE, ts(TUE, 6, 55))
    charts = built.blocks["charts"]
    for cid in ("G17", "G15", "G2", "G8", "G16", "G2_otc"):
        assert "11/16" in charts[cid]["title"], cid
    assert charts["G2"]["reference"]["label"] == "上市普通股" and "漲停" in charts["G2"]["reference"]["display"]
    assert "T_evening" not in built.blocks["tables"] and "T7" in built.blocks["tables"]
    assert built.pack["fixed_charts"] == ["G17", "G15", "G2", "G2_otc", "G8", "G7", "G16"]  # US prices off: no G6
    assert [m["code"] for m in built.pack["charts_menu"]] == ["G5"]
    assert {f["group"] for f in built.pack["facts"] if f["metric"] == "sector_contrib_est"} == {"prev_session"}


def test_premarket_data_edition_has_the_yesterday_section(market_db, us_on):
    built = build(market_db, "premarket", TUE, ts(TUE, 6, 55))
    pay = assemble.build(kind="premarket", report_id="r", edition_date=TUE, period=(TUE, TUE), next_period=None,
                         version=1, edition="data", pack=built.pack, blocks=built.blocks, output=None,
                         published_at=ts(TUE, 7), first_published_at=None, as_of=ts(TUE, 6, 55))
    by = {s_["key"]: s_ for s_ in pay["sections"]}
    ids = [b["chart"]["id"] for b in by["yesterday"]["blocks"] if b["type"] == "chart"]
    assert {"G17", "G15", "G2"} <= set(ids)
    assert "charts" not in by and "evening" not in by  # the one-chart section and the evening table are gone
    assert by["chips"]["blocks"][0]["chart"]["id"] == "G7"


def test_close_data_edition_has_g17_g15_g2_g8(market_db):
    built = build(market_db, "close", MON, ts(MON, 15, 40))
    pay = assemble.build(kind="close", report_id="r", edition_date=MON, period=(MON, MON), next_period=None,
                         version=1, edition="data", pack=built.pack, blocks=built.blocks, output=None,
                         published_at=ts(MON, 16), first_published_at=None, as_of=ts(MON, 15, 40))
    ids = [b["chart"]["id"] for s_ in pay["sections"] for b in s_["blocks"] if b["type"] == "chart"]
    assert {"G17", "G15", "G2", "G8"} <= set(ids) and "G4" not in ids


# -- G2 period chips --------------------------------------------------------------------------------------------------
def test_g2_has_no_chips_while_the_archive_is_two_days(market_db):
    assert "views" not in build(market_db, "close", MON, ts(MON, 15, 40)).blocks["charts"]["G2"]


def test_g2_since_chip_until_a_week_is_archived(market_db):
    seed_index_day(market_db, date(2026, 11, 12), "0.98")
    market_db.commit()
    g2 = build(market_db, "close", MON, ts(MON, 15, 40)).blocks["charts"]["G2"]
    assert [(v["key"], v["label"]) for v in g2["views"]] == [("1d", "1 日"), ("since", "11/12 起")]
    since = g2["views"][1]
    # each chip sorts by its own period and has its own baseline (the TAIEX over the same days)
    assert [b["value"] for b in since["bars"]] == sorted((b["value"] for b in since["bars"]), reverse=True)
    assert since["bench"]["label"].startswith("加權 ▼") and since["notes"][0].startswith("虛線是加權指數同一期間")
    assert g2["views"][0]["bars"] == g2["bars"]


def test_g2_week_and_month_chips_once_the_archive_reaches(market_db):
    assert mc.sessions_back(MON, 5) == date(2026, 11, 9) and mc.month_base(MON) == date(2026, 10, 16)
    seed_index_day(market_db, date(2026, 11, 9), "0.97")
    market_db.commit()
    keys = [v["key"] for v in build(market_db, "close", MON, ts(MON, 15, 40)).blocks["charts"]["G2"]["views"]]
    assert keys == ["1d", "1w"]  # a week back is archived (no 「since」: it would start the same day); no month
    seed_index_day(market_db, date(2026, 10, 16), "0.95")
    market_db.commit()
    keys = [v["key"] for v in build(market_db, "close", MON, ts(MON, 15, 40)).blocks["charts"]["G2"]["views"]]
    assert keys == ["1d", "1w", "1m"]
    assert mc.archive_ready(date(2026, 11, 12)) == (date(2026, 11, 19), date(2026, 12, 12))


# -- T2_top10 v2: the chained moves -----------------------------------------------------------------------------------
def test_chained_moves_use_the_reference_price_on_an_ex_rights_day(market_db):
    thu = date(2026, 11, 12)
    market_db.add(PriceDaily(symbol="2881.TW", date=thu, close=D("100"), volume=1, source="twse-openapi"))
    market_db.commit()
    # conftest: 富邦金 Fri 90 → Mon 91 with Monday's reference price 90; make Friday → Monday an ex-dividend of 4
    ref = market_db.get(ReferencePrice, ("2881.TW", MON))
    ref.reference_price = D("86")
    market_db.commit()
    got = mc.chained_returns(market_db, ["2881.TW", "2330.TW"], MON, ts(MON, 15, 40),
                             {"w": thu, "short": date(2026, 11, 2)})
    # Thu 100 → Fri 90 (−10%), Fri ex-dividend: 86 → Mon 91 (+5.81%): not a fall from 90 to 91 minus the dividend
    assert round(got["2881.TW"]["w"], 6) == round(D("0.9") * D("91") / D("86") - 1, 6)
    assert got["2881.TW"]["short"] is None  # the archive does not reach 11/2: never 0
    assert got["2330.TW"]["w"] is None  # no close on Thursday


# -- T10 margin -------------------------------------------------------------------------------------------------------
@pytest.fixture()
def margin(market_db):
    rows = {"2330.TW": (10_000, 12_000), "2317.TW": (50_000, 49_000), "2454.TW": (5_000, 5_100),
            "2455.TW": (1_000, 9_000), "4743.TW": (100, 5_000), "6488.TWO": (3_000, 2_000)}
    for sym, (fri, mon) in rows.items():
        src = "tpex-openapi" if sym.endswith(".TWO") else "twse-openapi"
        market_db.add(MarginDaily(symbol=sym, date=FRI, margin_balance=fri, short_balance=0, margin_limit=0,
                                  source=src))
        market_db.add(MarginDaily(symbol=sym, date=MON, margin_balance=mon, short_balance=0, margin_limit=0,
                                  source=src))
    market_db.commit()
    return market_db


def test_t10_margin_changes_in_scope_without_moves(margin):
    built = build(margin, "premarket", TUE, ts(TUE, 6, 55))
    up, down = built.blocks["tables"]["T10_up"], built.blocks["tables"]["T10_down"]
    assert [c["key"] for c in up["columns"]] == ["stock", "balance", "change"] and "漲跌" not in json.dumps(
        up["columns"], ensure_ascii=False)
    assert (up["tab_group"], up["tab_label"], down["tab_label"]) == ("margin", "增加", "減少")
    # 全新 (disposition) and 合一-創 (innovation board) are out of scope, however much their margin grew
    assert [r["cells"]["stock"]["text"] for r in up["rows"]] == ["台積電（2330）", "聯發科（2454）"]
    assert up["rows"][0]["cells"]["change"]["text"] == "+2,000" and up["rows"][0]["cells"]["balance"]["text"] == \
        "12,000"
    # ordered by lots × close: 環球晶 −1,000 × 380 before 鴻海 −1,000 × 210
    assert [r["cells"]["stock"]["text"] for r in down["rows"]] == ["環球晶（6488）", "鴻海（2317）"]
    assert "上市與上櫃" in up["rule"]
    pay = assemble.build(kind="premarket", report_id="r", edition_date=TUE, period=(TUE, TUE), next_period=None,
                         version=1, edition="data", pack=built.pack, blocks=built.blocks, output=None,
                         published_at=ts(TUE, 7), first_published_at=None, as_of=ts(TUE, 6, 55))
    chips = next(s_ for s_ in pay["sections"] if s_["key"] == "chips")
    assert [b["table"]["id"] for b in chips["blocks"] if b["type"] == "table"][-2:] == ["T10_up", "T10_down"]


def test_t10_waits_for_the_twse_morning_file(margin):
    # at 05:00 Tuesday TWSE's margin file of Monday is not out (05:45): only TPEx's
    built = build(margin, "premarket", TUE, ts(TUE, 5, 0))
    up = built.blocks["tables"].get("T10_down")
    assert up is not None and [r["cells"]["stock"]["text"] for r in up["rows"]] == ["環球晶（6488）"]
    assert up["rule"].startswith("範圍：上櫃，")


# -- the weekly -------------------------------------------------------------------------------------------------------
@pytest.fixture()
def full_week(margin):
    """Tuesday to Friday of the week of the 16th: each session 1% below the one before (listed, TPEx, indices)."""
    db = margin
    days = tw_trading_days(TUE, date(2026, 11, 20))
    prev = MON
    for i, d in enumerate(days, start=1):
        f = D("0.99") ** i
        for code, (_n, _ind, _sh, _fri, mon, value) in TWSE.items():
            db.add(PriceDaily(symbol=f"{code}.TW", date=d, close=(D(mon) * f).quantize(D("0.01")), volume=1,
                              value=value, source="twse-opendata"))
        for code, (_n, _ind, _sh, _fri, mon, value) in TPEX.items():
            db.add(PriceDaily(symbol=f"{code}.TWO", date=d, close=(D(mon) * f).quantize(D("0.01")), volume=1,
                              value=value, source="tpex-openapi"))
            db.add(InstitutionalDaily(symbol=f"{code}.TWO", date=d, foreign_net=100_000, trust_net=0, dealer_net=0,
                                      total_net=100_000, source="tpex-openapi"))
        for name, pct in SECTORS_MON.items():
            db.add(IndexDaily(name=f"{name}類指數", date=d, market="TWSE", close=D("100") * (1 + D(pct)) * f,
                              change=None, change_pct=None, source="twse-opendata"))
        for name, pct in STYLE_MON.items():
            db.add(IndexDaily(name=name, date=d, market="TWSE", close=D("100") * (1 + D(pct)) * f, change=None,
                              change_pct=None, source="twse-opendata"))
        db.add(IndexDaily(name=mc.TAIEX, date=d, market="TWSE", close=D("41040.08") * f, change=None, change_pct=None,
                          source="twse-opendata"))
        db.add(IndexDaily(name="發行量加權股價報酬指數", date=d, market="TWSE", close=D("94901.06") * f, change=None,
                          change_pct=None, source="twse-opendata"))
        db.add(IndexDaily(name="櫃買指數", date=d, market="TPEX", close=D("319.12") * f, change=None, change_pct=None,
                          source="tpex-openapi"))
        prev = d
    for sym, bal in (("2330.TW", 15_000), ("2317.TW", 40_000), ("6488.TWO", 2_500)):
        src = "tpex-openapi" if sym.endswith(".TWO") else "twse-openapi"
        db.add(MarginDaily(symbol=sym, date=prev, margin_balance=bal, short_balance=0, margin_limit=0, source=src))
    db.commit()
    return db


def test_weekly_sectors_chips_and_stocks(full_week, us_on):
    built = build(full_week, "weekly", date(2026, 11, 22), ts(date(2026, 11, 22), 16, 30))
    charts, tables = built.blocks["charts"], built.blocks["tables"]
    g17 = charts["G17"]
    assert "週點數貢獻" in g17["title"] and g17["reference"]["label"] == "官方漲跌"
    assert any("類股週" in (b["sub"] or "") for b in g17["bars"])
    t3 = tables["T3"]
    assert len(t3["rows"]) == 9 and "多期間" not in t3["title"]  # the 32 sectors are G2's chips now
    g2 = charts["G2"]
    assert g2["bench"]["label"].startswith("加權 ▼") and g2["bars"][0]["sub"].startswith("漲 ")
    g8 = charts["G8"]
    assert "11/16–11/20" in g8["title"] and g8["notes"][0].startswith("分母是上市普通股的全週成交金額")
    assert "aside_label" not in g8  # the week before is not fully archived: no change column
    assert "週" in charts["G16"]["title"] and charts["G16"]["reference"]["display"].startswith("買超")
    t9 = tables["T9"]
    assert [r["cells"]["item"]["text"] for r in t9["rows"]] == ["外資及陸資台指期淨未平倉", "台指選擇權 P/C 未平倉比",
                                                              "上櫃三大法人（估算金額）"]
    # TAIFEX has nothing after Monday here: the week's last (Monday) against the last before it (Friday)
    assert t9["rows"][0]["cells"]["item"]["sub"] == "11/16" and t9["rows"][0]["cells"]["change"]["text"] == "-6,787 口"
    assert [c["label"] for c in t9["columns"]] == ["項目", "本週收", "週變化"]  # not 「週末」 (a weekend)
    assert all("tone" not in c for r in t9["rows"] for c in r["cells"].values())  # lots and amounts are ink
    subs = [b["sub"] or "" for b in g8["bars"]]
    assert any("・週 ▼" in x for x in subs) and not any("週▼" in x or "週▲" in x for x in subs)
    up = tables["T10_up"]
    assert up["title"].startswith("融資週增加前 5") and up["columns"][2]["label"] == "週增減（張）"
    # TWSE's Friday file comes Monday morning: the listed side ends on its newest file of the week (Monday's here)
    # (全新's disposition ended 11/17: in scope on 11/20; 合一-創 never)
    assert [r["cells"]["stock"]["text"] for r in up["rows"]] == ["台積電（2330）", "全新（2455）", "聯發科（2454）"]
    assert "上市到 11/16" in up["rule"] and "上櫃到" not in up["rule"]
    otc = next(r for r in tables["T10_down"]["rows"] if r["cells"]["stock"]["text"] == "環球晶（6488）")
    assert otc["cells"]["change"]["text"] == "−500"  # 3,000 on 11/13 → 2,500 on 11/20
    top = tables["T2_top10"]
    assert [c["label"] for c in top["columns"]] == ["股票", "週漲跌", "近 1 月"]
    assert top["rule"].endswith("；底色只分兩階（週漲跌：2%、5%；近 1 月：4%、10%）")
    tsmc = top["rows"][1]["cells"]
    # Friday 1,500 → Monday 1,430 (from Monday's reference price) → each day 1% lower, rounded to the cent: 1,373.65
    assert tsmc["w1"] == {"text": "▼8.42%", "tone": "fall", "heat": "fall2"} and tsmc["m1"] == {"text": "—"}
    value = tables["T2_value"]
    assert value["tab_label"] == "週成交值" and value["columns"][-1]["label"] == "週成交金額"
    assert value["rows"][0]["cells"]["stock"]["text"] == "台積電（2330）"
    assert built.pack["fixed_charts"] == ["G1", "G17", "G2", "G8", "G3", "G16", "G7", "G6"]
    assert "G5" not in built.pack["fixed_charts"]
    pay = assemble.build(kind="weekly", report_id="r", edition_date=date(2026, 11, 22),
                         period=(MON, date(2026, 11, 20)), next_period=None, version=1, edition="data",
                         pack=built.pack, blocks=built.blocks, output=None, published_at=ts(date(2026, 11, 22), 17),
                         first_published_at=None, as_of=ts(date(2026, 11, 22), 16, 30))
    by = {s_["key"]: s_ for s_ in pay["sections"]}
    assert "returns" not in by and by["sectors_week"]["title"] == "類股一週與大方向"
    assert [(b["type"], (b.get("chart") or b.get("table"))["id"]) for b in by["sectors_week"]["blocks"]] == \
        [("chart", "G17"), ("table", "T3"), ("chart", "G2"), ("chart", "G8")]
    assert [(b["type"], (b.get("chart") or b.get("table"))["id"]) for b in by["chips_week"]["blocks"]] == \
        [("chart", "G7"), ("table", "T9"), ("chart", "G16"), ("table", "T10_up"), ("table", "T10_down")]


# -- A1 and the writer ------------------------------------------------------------------------------------------------
def test_no_new_chart_reads_as_a_signal(otc3, us_on):
    for kind, d, cut in (("close", MON, ts(MON, 23, 45)), ("premarket", TUE, ts(TUE, 6, 55))):
        charts = build(otc3, kind, d, cut).blocks["charts"]
        for cid in NEW_CHARTS:
            if cid in charts:
                text = json.dumps(charts[cid], ensure_ascii=False)
                assert not any(w in text for w in A1_WORDS), cid
                assert "資金" not in charts[cid]["title"]


def test_the_writer_is_told_what_the_page_draws(market_db, us_on):
    pk = build(market_db, "close", MON, ts(MON, 15, 40)).pack
    text = prompts.kind_instructions("close", pk)
    assert "G17 各類股點數貢獻（估算）" in text and "G15 規模與風格指數" in text and "引用 F" in text
    assert "sector_contrib_est" in prompts.SPEC["close"]["sections"]
    pre = prompts.SPEC["premarket"]["sections"]
    assert "昨日籌碼" in pre and "昨日台股全貌" in pre and "不要重述" in pre
    assert "類股一週與大方向" in prompts.SPEC["weekly"]["sections"]
    assert prompts.PROMPT_VERSION == "mr-2026-11-18a"


def test_a_sector_contribution_sentence_is_checked(market_db):
    pk = build(market_db, "close", MON, ts(MON, 15, 40)).pack
    f = next(x for x in pk["facts"] if x["metric"] == "sector_contrib_est" and x["subject"] == "半導體")
    conc = fid(pk, "sector_concentration", "半導體")
    pts = f["display"].removeprefix("−")
    out = {"sectors": [p(s(f"半導體類點數貢獻約 −{pts}（估算），主要由台積電構成，約 94%。", f["id"], conc))]}
    found = {x.code for x in validate.validate(out, pk, "close", ()) if x.hard and x.path.startswith("sectors")}
    assert not found & {"number_unsourced", "direction_mismatch", "sector_not_allowed", "index_points"}
    out = {"sectors": [p(s(f"半導體類點數貢獻約 +{pts}（估算），主要由台積電構成，約 94%。", f["id"], conc))]}
    assert "direction_mismatch" in {x.code for x in validate.validate(out, pk, "close", ())}


def test_new_datasets_have_an_availability_rule():
    for ds in ("tpex-openapi/valuation", "tpex-openapi/foreign_holding", "taifex-openapi/fx", "twse-openapi/company"):
        assert timing.known(ds)
        assert timing.available_at(ds, MON) == ts(TUE, 5, 45)
    assert timing.available_at("twse-openapi/margin", MON) == ts(TUE, 5, 45)
    assert timing.available_at("tpex-openapi/margin", MON) == ts(MON, 23, 40)
    assert MON + timedelta(days=1) == TUE


# -- review fixes (2026-11-18) ----------------------------------------------------------------------------------------
def test_a_session_missing_from_the_archive_is_a_dash_not_a_skipped_move(market_db):
    """Closes and reference prices come from different jobs: Monday's reference price is Friday's close even when
    Friday's close never reached the archive. Chaining only the archived days would drop Friday's move (a confident
    0.00% where the real move is +10%)."""
    thu = date(2026, 11, 12)
    market_db.add(PriceDaily(symbol="2881.TW", date=thu, close=D("100"), volume=1, source="twse-openapi"))
    market_db.query(PriceDaily).filter_by(symbol="2881.TW", date=FRI).delete()
    market_db.commit()
    got = mc.chained_returns(market_db, ["2881.TW"], MON, ts(MON, 15, 40), {"w": thu, "d": FRI})
    assert got["2881.TW"] == {"w": None, "d": None}
    # an index's move needs its base close itself: never an earlier one under a 「近 1 週」 label
    pts = [mc.IndexPoint(mc.TAIEX, date(2026, 11, 5), D("100"), None, None, ""),
           mc.IndexPoint(mc.TAIEX, MON, D("110"), None, None, "")]
    assert mc.index_move(pts, MON, date(2026, 11, 9)) is None
    assert mc.index_move(pts, MON, date(2026, 11, 5)) == D("0.1")


def test_top10_says_which_session_the_archive_misses(market_db):
    wed = date(2026, 11, 11)  # archived; Thursday 11/12 is not (for any stock)
    for code, (_n, _ind, _sh, fri, _mon, value) in TWSE.items():
        market_db.add(PriceDaily(symbol=f"{code}.TW", date=wed, close=D(fri), volume=1, value=value,
                                 source="twse-openapi"))
    market_db.commit()
    top = build(market_db, "close", MON, ts(MON, 15, 40)).blocks["tables"]["T2_top10"]
    assert all(r["cells"]["w1"] == {"text": "—"} for r in top["rows"][1:])
    assert "存檔缺 11/12 的收盤，跨過這一天的格子不算（「—」）。" in top["note"]


def test_top10_names_the_taiex_files_and_its_tint_steps(market_db):
    top = build(market_db, "close", MON, ts(MON, 15, 40)).blocks["tables"]["T2_top10"]
    assert label("twse-opendata/index") in top["source_labels"]  # the TAIEX row's 1-day move (MI_INDEX)
    assert top["rule"].endswith("；底色只分兩階（1 日：1%、3%；近 1 週：2%、5%；近 1 月：4%、10%）")


def test_g2_period_chips_carry_their_own_title_and_the_taiex_file(market_db):
    seed_index_day(market_db, date(2026, 11, 12), "0.98", taiex=False)
    # the TAIEX of 11/12 only in FMTQIK (the index archive starts later): the chip's dashed line is measured on it
    market_db.add(MarketTurnoverDaily(date=date(2026, 11, 12), market="TWSE", trade_value=1, taiex=D("42000"),
                                      source="twse-openapi"))
    market_db.commit()
    g2 = build(market_db, "close", MON, ts(MON, 15, 40)).blocks["charts"]["G2"]
    assert [v["title"] for v in g2["views"]] == ["上市類股指數漲跌（11/16）", "上市類股指數漲跌（11/12 收盤至 11/16）"]
    assert g2["views"][1]["bench"]["value"] == pytest.approx(41040.08 / 42000 - 1)
    assert label("twse-openapi/turnover") in g2["sources"]


def test_lots_and_institutional_amounts_are_ink(otc3):
    """Red and green only for price moves: the futures' lots and TPEx institutions' amounts are ink, as G7 and G16
    beside them."""
    for kind, d, cut in (("close", MON, ts(MON, 23, 45)), ("premarket", TUE, ts(TUE, 6, 55))):
        tables = build(otc3, kind, d, cut).blocks["tables"]
        for tid in ("T7", "T8", "T8_buy", "T8_sell"):
            if tid in tables:
                assert all("tone" not in c for r in tables[tid]["rows"] for c in r["cells"].values()), (kind, tid)
        assert "T7" in tables
    assert "T8" in build(otc3, "close", MON, ts(MON, 23, 45)).blocks["tables"]


def test_g15_note_is_for_the_reader(market_db):
    g15 = build(market_db, "close", MON, ts(MON, 15, 40)).blocks["charts"]["G15"]
    assert g15["notes"] == ["虛線是加權指數的漲跌；電子工業是電子類股的合計。"]


def test_an_unmarked_point_contribution_is_a_hard_problem(market_db):
    pk = build(market_db, "close", MON, ts(MON, 15, 40)).pack
    f = next(x for x in pk["facts"] if x["metric"] == "sector_contrib_est" and x["subject"] == "半導體")
    conc = fid(pk, "sector_concentration", "半導體")
    pts = f["display"].removeprefix("−")

    def codes(text: str) -> set[str]:
        out = {"sectors": [p(s(text, f["id"], conc))]}
        return {x.code for x in validate.validate(out, pk, "close", ()) if x.hard and x.path.startswith("sectors")}

    assert "estimate_unmarked" in codes(f"半導體類對加權指數的點數貢獻 −{pts}，主要由台積電構成，約 94%。")
    assert "estimate_unmarked" not in codes(f"半導體類點數貢獻約 −{pts}，主要由台積電構成，約 94%。")
    assert "estimate_unmarked" not in codes(f"半導體類點數貢獻 −{pts}（估算），主要由台積電構成，約 94%。")
    # a stock's contribution too (the close's stock items)
    tsmc = fid(pk, "stock_contrib", "台積電")
    disp = next(x for x in pk["facts"] if x["id"] == tsmc)["display"].removeprefix("−")
    out = {"highlights": [p(s(f"台積電（2330）點數貢獻 −{disp}。", tsmc))]}
    assert "estimate_unmarked" in {x.code for x in validate.validate(out, pk, "close", ())}
    assert "estimate_unmarked" in prompts.REVISE_HINTS


def test_weekly_ai_text_comes_first_in_every_section(full_week, us_on):
    built = build(full_week, "weekly", date(2026, 11, 22), ts(date(2026, 11, 22), 16, 30))
    para = p(s("示範句。", "F001"))
    out = {"sectors_week": [para], "stocks_week": [{"symbol": "2330.TW", "para": para}], "chips_week": [para],
           "global_week": [para]}
    for key in ("sectors_week", "stocks_week", "chips_week", "global_week"):
        blocks = [b for b in assemble._blocks_for("weekly", key, built.pack, built.blocks, out, None) if b]
        assert blocks[0]["type"] == "text" and len(blocks) > 1, key
