"""Market reports v2 (2026-11-18) against the real archive of 2026-11-17: the spec's numbers as golden values.

``fixtures/dry_1117.json.gz`` holds the rows of the dry-run snapshot (11/17 17:41 Taipei) the new blocks read: TWSE
closes of 11/16 (OpenAPI) and 11/17 (open_data), TPEx closes and institutional net shares of 11/17, company profiles
(industry, issued shares, short name), the sector, size and style indices of 11/16–11/17, and the altered-trading and
disposition rows (official open data under 政府資料開放授權條款第 1 版; four-digit codes, and every TPEx security with
institutional rows). The snapshot has no TWSE reference prices (TWT84U answered 307), no TPEx close of 11/16 (so no
TPEx moves) and one margin day (no T10).
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import insert

from forliosa.models import CompanyProfile, IndexDaily, InstitutionalDaily, MarketEvent, PriceDaily
from forliosa.reports import assemble, pack
from forliosa.reports import marketcalc as mc
from tests.reports.conftest import ts

FIXTURE = Path(__file__).parent / "fixtures" / "dry_1117.json.gz"
D16, D17, D18 = date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 18)
A1_WORDS = ("強勢", "弱勢", "偏高", "偏低", "資金流向")


def _d(x: str | None) -> date | None:
    return date.fromisoformat(x[:10]) if x else None


@pytest.fixture()
def dry(db):
    data = json.loads(gzip.decompress(FIXTURE.read_bytes()))
    db.execute(insert(CompanyProfile), [
        {"symbol": sym, "date": D17, "industry_code": ind, "industry": None, "shares_outstanding": shares,
         "values": {"short_name": short} if short else {},
         "source": "tpex-openapi" if sym.endswith(".TWO") else "twse-openapi"}
        for sym, (ind, shares, short) in data["profiles"].items()])
    db.execute(insert(PriceDaily), [
        {"symbol": s, "date": _d(d), "close": Decimal(cl), "volume": vol, "value": val, "source": so}
        for s, d, cl, vol, val, so in data["prices"]])
    db.execute(insert(IndexDaily), [
        {"name": n, "date": _d(d), "market": m, "close": Decimal(cl), "change": Decimal(ch) if ch else None,
         "change_pct": Decimal(pc) if pc else None, "source": so} for n, d, m, cl, ch, pc, so in data["indices"]])
    db.execute(insert(InstitutionalDaily), [
        {"symbol": s, "date": D17, "foreign_net": f, "trust_net": t, "dealer_net": dl, "total_net": tot,
         "source": "tpex-openapi"} for s, f, t, dl, tot in data["institutional"]])
    for k, s, d, e, t, ti, da, so, ca in data["events"]:
        created = datetime.fromisoformat(ca) if ca else datetime(2026, 11, 1, tzinfo=UTC)
        db.add(MarketEvent(key=k, symbol=s, date=_d(d), end_date=_d(e), type=t, title=ti, data=da, source=so,
                           created_at=created if created.tzinfo else created.replace(tzinfo=UTC)))
    db.commit()
    return db


@pytest.fixture()
def close17(dry):
    return pack.build(dry, "close", D17, cutoff=ts(D17, 15, 40), now=ts(D17, 16))


def bars(chart):
    return {b["label"]: b for b in chart["bars"]}


# -- G17: sector point contributions --------------------------------------------------------------------------------
def test_g17_sector_points_add_up_to_the_official_change(dry, close17):
    day = mc.load_day(dry, "TWSE", D17, ts(D17, 15, 40))
    contribs = mc.sector_contributions(day, Decimal("41040.08"))
    assert len(contribs) == 32 and mc.UNMAPPED not in {c.name for c in contribs}
    total = sum(c.points for c in contribs)
    assert abs(total - Decimal("-947.97")) / Decimal("947.97") < Decimal("0.005")  # −947.8 against −947.97
    assert abs(sum(c.weight for c in contribs) - 1) < Decimal("1e-9")
    g17 = close17.blocks["charts"]["G17"]
    b = bars(g17)
    assert b["半導體"]["display"] == "−494 點" and b["半導體"]["sub"] == "權重約 55.8%・類股 ▼2.16%"
    assert b["電子零組件"]["display"] == "−244 點" and b["電腦及週邊設備"]["display"] == "−67 點"
    # the drags first on a falling day (5 at most), then the lifts (only those that moved it ±0.5 point or more)
    assert [x["label"] for x in g17["bars"][:3]] == ["半導體", "電子零組件", "電腦及週邊設備"]
    assert all(x["value"] > 0 for x in g17["bars"][5:-1]) and g17["bars"][-1]["tone"] == "pencil"
    assert g17["reference"] == {"label": "官方漲跌", "display": "−947.97 點・32 類估算加總 −948 點"}
    assert g17["estimate"] is True


def test_g17_facts_open_the_three_best_and_worst_to_the_text(close17):
    facts = [f for f in close17.pack["facts"] if f["metric"] == "sector_contrib_est"]
    assert {f["subject"]: f["display"] for f in facts if f["value"] < 0} == {
        "半導體": "−494 點", "電子零組件": "−244 點", "電腦及週邊設備": "−67 點"}
    assert all(f["estimate"] and f["dataset"] == "rules:contribution" for f in facts)
    sectors = {s["name"]: s for s in close17.pack["sectors"]}
    assert sectors["電子零組件"]["text_eligible"] and sectors["電腦及週邊設備"]["text_eligible"]
    assert not sectors["食品"]["text_eligible"]  # one company holds more than half: never in the text


# -- G15: size and style ----------------------------------------------------------------------------------------------
def test_g15_size_and_style(close17):
    g15 = close17.blocks["charts"]["G15"]
    assert {b["label"]: b["display"] for b in g15["bars"]} == {
        "臺灣50": "▼2.25%", "中型100": "▼2.13%", "小型股300": "▼1.87%", "電子工業": "▼2.71%", "未含電子": "▼0.90%",
        "金融保險": "▼0.35%", "臺灣高股息": "▼1.32%", "櫃買指數": "▼3.92%"}
    assert [b["group"] for b in g15["bars"]] == ["大小型股"] * 3 + ["電子與非電子"] * 3 + ["高股息與上櫃"] * 2
    assert g15["bench"] == {"value": -0.0231, "label": "加權 ▼2.31%"}


# -- G2 v2 ------------------------------------------------------------------------------------------------------------
def test_g2_baseline_breadth_and_fold(close17):
    g2 = close17.blocks["charts"]["G2"]
    assert g2["bench"] == {"value": -0.0231, "label": "加權 ▼2.31%"}
    assert g2["notes"][0] == "虛線是加權指數同一期間的漲跌：24 類高於加權指數、8 類低於。"
    b = bars(g2)
    assert b["電子零組件"]["display"] == "▼6.90%" and b["電子零組件"]["sub"].startswith("漲 7・跌 95")
    ups = sum(int(x["sub"].split("漲 ")[1].split("・")[0]) for x in g2["bars"])
    downs = sum(int(x["sub"].split("跌 ")[1].split("・")[0]) for x in g2["bars"])
    assert (ups, downs) == (234, 789)  # the market's breadth of 11/17
    # folded on phones: the 5 best, 半導體 and the 5 worst stay
    assert g2["fold"] == {"head": 5, "tail": 5, "keep": ["半導體"]}
    # the snapshot has two days of sector indices: no week, no month, no 「since」 (it would be the day itself)
    assert "views" not in g2
    assert "reference" not in g2  # the close's breadth is the number strip's


# -- G8: turnover share -----------------------------------------------------------------------------------------------
def test_g8_turnover_share(close17):
    g8 = close17.blocks["charts"]["G8"]
    b = bars(g8)
    assert (b["半導體"]["display"], b["半導體"]["aside"]) == ("40.9%", "+2.2")
    assert (b["電子零組件"]["display"], b["電子零組件"]["aside"]) == ("21.8%", "+1.0")
    assert abs(sum(x["value"] for x in g8["bars"]) - 1) < 1e-9 and len(g8["bars"]) == 9
    assert g8["aside_label"] == "較前一日" and all(x["tone"] in ("ink", "pencil") for x in g8["bars"])
    assert g8["notes"][0] == "分母是上市普通股的成交金額 8,694 億元（前一日 7,517 億元），不含 ETF 等。"
    assert b["塑膠"]["sub"] == "成交值最大：南亞 327 億元，占這一類 82%・▼4.56%"
    assert b["半導體"]["sub"] == "成交值最大：台積電 1,355 億元・▼2.03%"  # 38%: not said


# -- T2_top10 v2 on the snapshot --------------------------------------------------------------------------------------
def test_top10_direction_table(close17):
    t = close17.blocks["tables"]["T2_top10"]
    assert [c["key"] for c in t["columns"]] == ["stock", "d1", "w1", "m1"]
    taiex, tsmc = t["rows"][0]["cells"], t["rows"][1]["cells"]
    assert taiex["stock"] == {"text": "加權指數", "sub": "40,092.11"}
    assert taiex["d1"] == {"text": "▼2.31%", "tone": "fall", "heat": "fall1"}
    assert tsmc["stock"]["text"] == "台積電（2330）" and tsmc["d1"]["text"] == "▼2.03%"
    assert tsmc["w1"] == {"text": "—"} and tsmc["m1"] == {"text": "—"}  # the archive is too short: never 0
    assert "contrib" not in {c["key"] for c in t["columns"]}


# -- the premarket of 11/18: 昨日台股全貌 and 昨日籌碼 -------------------------------------------------------------
def test_premarket_1118_yesterday_and_chips(dry):
    built = pack.build(dry, "premarket", D18, cutoff=ts(D18, 6, 55), now=ts(D18, 7))
    charts = built.blocks["charts"]
    assert {"G17", "G15", "G2", "G8", "G16"} <= set(charts)
    assert charts["G2"]["reference"] == {"label": "上市普通股",
                                         "display": "上漲 234・下跌 789・平盤 61 家；漲停 6・跌停 30 家"}
    g16 = charts["G16"]
    b = bars(g16)
    assert (b["通信網路"]["display"], b["半導體"]["display"], b["電子零組件"]["display"]) == \
        ("+19.9 億元", "+13.8 億元", "−10.0 億元")
    assert g16["reference"] == {"label": "上櫃三大法人合計（估算）", "display": "買超 50.3 億元"}
    assert [x["value"] for x in g16["bars"]] == sorted((x["value"] for x in g16["bars"]), reverse=True)
    assert {x["tone"] for x in g16["bars"]} == {"ink", "pencil"}  # an institutional flow, not a move
    assert "G2_otc" not in charts  # no TPEx close of 11/16 in the snapshot: no OTC moves
    pay = assemble.build(kind="premarket", report_id="r", edition_date=D18, period=(D18, D18), next_period=None,
                         version=1, edition="data", pack=built.pack, blocks=built.blocks, output=None,
                         published_at=ts(D18, 7), first_published_at=None, as_of=ts(D18, 6, 55))
    by = {s["key"]: s for s in pay["sections"]}
    assert by["yesterday"]["title"] == "昨日台股全貌（11/17）"
    assert [b["chart"]["id"] for b in by["yesterday"]["blocks"] if b["type"] == "chart"] == ["G17", "G15", "G2", "G8"]
    assert [b["chart"]["id"] for b in by["chips"]["blocks"] if b["type"] == "chart"] == ["G16"]


def test_no_new_chart_note_reads_as_a_signal(close17, dry):
    pre = pack.build(dry, "premarket", D18, cutoff=ts(D18, 6, 55), now=ts(D18, 7))
    for built in (close17, pre):
        for c in built.blocks["charts"].values():
            text = json.dumps([c.get("notes"), c.get("title"), [b.get("sub") for b in c.get("bars") or []]],
                              ensure_ascii=False)
            assert not any(w in text for w in A1_WORDS), c["id"]


# -- what the page gets: the v2 fields pass the API's response model (real-data check 11/18) -------------------------
def test_the_api_response_keeps_heat_cells_tab_groups_and_the_bar_extras(close17):
    """The real-data check of 11/18 found the 11/17 data edition rendered with no heat cells and four tables at once
    on a phone: ``GET /market/reports/{id}`` validates through ``MarketReport``, whose ``Cell`` and ``TableSpec``
    dropped ``heat``, ``tab_group`` and ``tab_label`` (charts are a free dict, so their v2 keys came through)."""
    from forliosa.api.schemas_reports import MarketReport

    pay = assemble.build(kind="close", report_id="r", edition_date=D17, period=(D17, D17), next_period=None,
                         version=1, edition="data", pack=close17.pack, blocks=close17.blocks, output=None,
                         published_at=ts(D17, 16), first_published_at=None, as_of=ts(D17, 15, 40))
    out = MarketReport.model_validate(pay).model_dump(mode="json")
    blocks = [b for s in out["sections"] for b in s["blocks"]]
    tables = {b["table"]["id"]: b["table"] for b in blocks if b["type"] == "table"}
    charts = {b["chart"]["id"]: b["chart"] for b in blocks if b["type"] == "chart"}
    top10 = tables["T2_top10"]["rows"]
    assert top10[0]["cells"]["d1"]["heat"] == "fall1"  # 加權指數 ▼2.31%
    assert top10[4]["cells"]["d1"]["heat"] == "fall2"  # 台達電 ▼5.80%
    assert top10[1]["cells"]["w1"]["heat"] is None  # 「—」: no tint
    assert [(tables[t]["tab_group"], tables[t]["tab_label"]) for t in ("T2_gainers", "T2_losers", "T2_value")] == \
        [("movers", "漲幅"), ("movers", "跌幅"), ("movers", "成交值")]
    assert tables["T2_top10"]["tab_group"] is None
    assert charts["G2"]["bench"] == {"value": -0.0231, "label": "加權 ▼2.31%"}
    assert charts["G2"]["fold"]["keep"] == ["半導體"]
    assert charts["G8"]["aside_label"] == "較前一日" and charts["G8"]["bars"][0]["aside"] == "+2.2"
    assert charts["G15"]["bars"][0]["group"] == "大小型股"
