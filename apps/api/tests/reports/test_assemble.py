"""The report JSON (contract §12): the data edition's rule-made title and highlights, the sections in their order,
footnotes merged per dataset and day, the public form without ids, the table version that keeps the AI text."""

from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from forliosa.ai.analyst import datetime_from_page_age
from forliosa.reports import assemble, pack
from forliosa.timeutil import TAIPEI
from tests.reports.conftest import MON, TUE, ts
from tests.reports.helpers import INST_X, close_output, premarket_output, with_web


def build(db, kind, d, output=None, **kw):
    built = pack.build(db, kind, d, cutoff=kw.pop("cutoff", ts(d, 15, 40) if kind == "close" else ts(d, 6, 55)),
                       now=ts(d, 16))
    pk = with_web(built.pack, INST_X) if output else built.pack
    out = output(pk) if output else None
    ed_period = (date.fromisoformat(pk["period"]["start"]), date.fromisoformat(pk["period"]["end"]))
    return assemble.build(kind=kind, report_id="mrp_x", edition_date=d, period=ed_period, next_period=None,
                          version=1, edition="ai" if out else "data", pack=pk, blocks=built.blocks, output=out,
                          published_at=ts(d, 16), first_published_at=None, as_of=built.pack and ts(d, 15, 40),
                          title_origin="ai", highlights_origin="ai", **kw), pk, built


def test_data_edition_close(market_db):
    pay, _pk, _ = build(market_db, "close", MON)
    assert pay["title"] == "盤後重點 11/16（一）：加權指數 ▼6.03%，收 41,040.08 點" and pay["title_origin"] == "rules"
    # the brief's rule-made rows (2026-11-27): 貢獻 and 量 (two sessions in the archive: no average, so no 位置 yet);
    # the highlights are the same paragraphs
    assert [(r["key"], r["label"], r["origin"]) for r in pay["brief"]] == [("drivers", "貢獻", "rules"),
                                                                           ("volume", "量", "rules")]
    texts = [s["text"] for p in pay["highlights"] for s in p["sentences"]]
    # (半導體 is said with its concentration, as the writer's own text must)
    assert texts == ["半導體類約 −1,702 點（估算；主要由台積電構成，約 94%）。",
                     "上市約 2,295 億元（估算），和前一日相近。"]
    assert pay["highlights"] == [r["paragraph"] for r in pay["brief"]] and pay["highlights_origin"] == "rules"
    assert pay["has_ai"] is False and pay["model_line"] is None and pay["disclaimer_line"] == assemble.DISCLAIMER_DATA
    assert all(sec["origin"] == "data" for sec in pay["sections"])
    assert pay["footnotes"] and all(s["cites"] for p in pay["highlights"] for s in p["sentences"])
    # the TAIEX chart sits under the brief; 「今天發生什麼」 had nothing else in a data edition, so it is not there
    assert pay["trend"]["id"] == "G1" and "what_happened" not in [sec["key"] for sec in pay["sections"]]


def test_data_edition_premarket(market_db, us_on):
    pay, _pk, _ = build(market_db, "premarket", TUE)
    assert pay["title"] == "盤前重點 11/17（二）：美股 11/16 收盤與今日行事曆"
    assert [(r["key"], r["label"]) for r in pay["brief"]] == [("overnight", "隔夜"), ("scheduled", "排定"),
                                                               ("position", "位置"), ("chips", "籌碼")]
    assert all(r["origin"] == "rules" for r in pay["brief"])
    texts = [s["text"] for p in pay["highlights"] for s in p["sentences"]]
    assert texts[0].startswith("美股 11/16 SPY ▲0.50%、DIA ▼0.21%")
    assert texts[1] == "鴻海（2317）法說會；市值前 100 中 1 家除權息、1 家法說會。"
    assert texts[2] == "加權指數 11/16 收 41,040.08 點（▼6.03%）。"  # where the previous session closed
    assert texts[3] == "外資台指期淨空 96,787 口，較前一日 ▼6,787 口。"
    assert pay["trend"]["id"] == "G1" and pay["trend"]["series"][0]["points"][-1]["t"] == "2026-11-16"
    keys = [s["key"] for s in pay["sections"]]
    assert keys == ["overnight", "yesterday", "chips"]  # no AI: no watch, no chart of the day
    by = {s["key"]: s for s in pay["sections"]}
    # folded on phones (2026-11-27): the previous close report showed these charts already
    assert by["yesterday"]["title"] == "昨日台股全貌（11/16）" and by["yesterday"]["collapsed_mobile"]
    assert by["yesterday"]["blocks"][0] == {"type": "note", "text": assemble.yesterday_note(_pk)}
    # (G2_otc needs an OTC industry of three commons: this market has none)
    assert [b["chart"]["id"] for b in by["yesterday"]["blocks"][1:]] == ["G17", "G15", "G2", "G8"]
    assert by["chips"]["title"] == "昨日籌碼（晚間公布）" and by["chips"]["collapsed_mobile"]
    assert [(b["type"], (b.get("chart") or b.get("table"))["id"]) for b in by["chips"]["blocks"]] == \
        [("chart", "G7"), ("table", "T7"), ("chart", "G16")]
    assert pay["calendar"]["title"].startswith("今日行事曆")


def test_ai_edition_footnotes_and_public_form(market_db):
    pay, _pk, _ = build(market_db, "close", MON, output=close_output)
    assert pay["has_ai"] and pay["title"] == "加權指數跌 6.03%，收 41,040.08 點"
    # facts of one dataset and day share a footnote; a report gets its own
    labels = [f["label"] for f in pay["footnotes"]]
    assert len(labels) == len(set((f["kind"], f["label"], f["url"]) for f in pay["footnotes"]))
    web = [f for f in pay["footnotes"] if f["kind"] == "web"]
    assert web[0]["outlet"] == "中央社" and web[0]["date_label"] == "11/16 15:32"
    assert pay["sources"]["web"] == [{"n": web[0]["n"], "outlet": "中央社", "title": "外資賣超千億",
                                      "url": INST_X["url"], "published_label": "11/16 15:32"}]
    assert not any(sec["key"] == "chart_of_day" for sec in pay["sections"])  # none picked
    pub = assemble.public(pay)
    import json

    raw = json.dumps(pub, ensure_ascii=False)
    assert not re.search(r"\b[FXCNW]\d{3}\b", raw) and "refs" not in raw and "1,234.5 億元，投信" not in raw
    assert not assemble.has_id_strings(pay)


def test_premarket_ai_sections(market_db, us_on):
    pay, _pk, _ = build(market_db, "premarket", TUE, output=premarket_output)
    keys = [s["key"] for s in pay["sections"]]
    assert keys == ["overnight", "watch", "yesterday", "chips"]
    chips = next(s for s in pay["sections"] if s["key"] == "chips")
    assert chips["blocks"][0]["type"] == "text"  # the evening notes first, then G7, T7, G16
    watch = next(s for s in pay["sections"] if s["key"] == "watch")
    item = watch["blocks"][0]["items"][0]
    assert item["title"] == "鴻海法說會" and item["meta"].startswith("11/17") and "其他電子" in item["meta"]


def test_the_chart_of_day_is_g5_only(market_db):
    """v2: the menus hold G5 (G2 is fixed, G4's breadth is the number strip's); a pick draws the server's chart."""
    built = pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16))
    assert [m["code"] for m in built.pack["charts_menu"]] == ["G5"]
    assert "G4" not in built.blocks["charts"]
    g5 = {"id": "G5", "kind": "compare", "title": "權值前 5 檔一個月比較", "series": []}
    blocks = {**built.blocks, "charts": {**built.blocks["charts"], "G5": g5}}
    out = {"chart_of_day": {"code": "G5", "period": "day", "set": "top5_weight",
                            "caption": {"sentences": [{"text": "權值股一個月比較。", "refs": []}]}}}
    assert assemble.chart_of_day_block("close", out, blocks)["chart"] is g5
    out["chart_of_day"]["code"] = "G4"
    assert assemble.chart_of_day_block("close", out, blocks) is None
    assert assemble.CHART_KEYS == {"premarket": {"G5": "G5"}, "close": {"G5": "G5"}, "weekly": {"G5": "G5"}}


def test_mentions_anthropic_adds_the_line(market_db):
    pay, _, _ = build(market_db, "close", MON, output=close_output, mentions_anthropic=True)
    assert pay["model_line"] == assemble.MODEL_LINE + assemble.MODEL_LINE_MENTION


def test_table_version_keeps_the_ai_text(market_db):
    pay, _pk, _ = build(market_db, "close", MON, output=close_output)
    later = pack.build(market_db, "close", MON, cutoff=ts(date(2026, 11, 17), 6, 40), now=ts(date(2026, 11, 17), 7))
    out = assemble.retable(pay, "close", later.pack, later.blocks, version=3,
                           published_at=ts(date(2026, 11, 17), 6, 40), as_of=ts(date(2026, 11, 17), 6, 40))
    assert out["title"] == pay["title"] and out["highlights"] == pay["highlights"]
    assert out["footnotes"] == pay["footnotes"] and out["version"] == 3 and out["edition"] == "tables"
    texts = lambda p: [b for s in p["sections"] for b in s["blocks"] if b["type"] == "text"]  # noqa: E731
    assert texts(out) == texts(pay)
    turnover = next(n for n in out["numbers"] if n["key"] == "turnover")
    assert turnover["estimate"] is False and turnover["value"] == "9,031 億元"  # FMTQIK replaced the estimate
    assert out["as_of_label"] == "資料截至 11/17 06:40"


@pytest.mark.parametrize("raw,want", [
    ("2026-11-16T15:32:00+08:00", datetime(2026, 11, 16, 15, 32, tzinfo=TAIPEI)),
    ("2026-11-16", date(2026, 11, 16)),
    ("November 16, 2026", date(2026, 11, 16)),
    ("3 hours ago", datetime(2026, 11, 16, 13, 0, tzinfo=TAIPEI)),
    ("2 days ago", date(2026, 11, 14)),
    (None, None),
])
def test_page_age_with_time(raw, want):
    assert datetime_from_page_age(raw, datetime(2026, 11, 16, 16, 0, tzinfo=TAIPEI)) == want
