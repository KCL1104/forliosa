"""The brief and the trend chart (owner 2026-11-27: 「有點不知道重點」): the premarket's and the close's highlights
are rows of a printed form — the writer's (為什麼, 貢獻, 籌碼; 隔夜, 為什麼, 排定) and the server's own (位置,
量: computed from the official closes of the archive, never written by a model) — with the TAIEX and its 5- and
10-session averages drawn under them.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from forliosa.ai import market_tools
from forliosa.models import IndexDaily, MarketTurnoverDaily
from forliosa.reports import assemble, pack, prompts, push, validate
from forliosa.reports import marketcalc as mc
from forliosa.timeutil import tw_trading_days
from tests.reports.conftest import FRI, MON, TUE, ts
from tests.reports.helpers import INST_X, cid, close_output, fid, premarket_output, row, s, with_web

TAIEX = "發行量加權股價指數"


# -- the numbers -----------------------------------------------------------------------------------------------------
def test_moving_average_streak_and_unbroken_run():
    days = [date(2026, 11, d) for d in (9, 10, 11, 12, 13)]
    closes = [(d, D(c)) for d, c in zip(days, ("100", "102", "104", "103", "101"), strict=True)]
    assert mc.moving_average(closes, 2) == [(days[1], D("101")), (days[2], D("103")), (days[3], D("103.5")),
                                            (days[4], D("102"))]
    assert mc.moving_average(closes, 5) == [(days[4], D("102"))] and mc.moving_average(closes, 6) == []
    assert mc.streak([c for _d, c in closes]) == -2  # 104 → 103 → 101
    assert mc.streak([D(1), D(2), D(3)]) == 2 and mc.streak([D(3), D(3)]) == 0 and mc.streak([D(3)]) == 0
    assert mc.streak([D(1), D(2), D(2), D(3)]) == 1  # an unchanged day ends the run
    # a missing trading day breaks the run: 11/11 is not there, so only 11/12 and 11/13 follow one another
    assert mc.unbroken_run([days[0], days[1], days[3], days[4]], days[4]) == [days[3], days[4]]
    assert mc.unbroken_run(days, days[4]) == days and mc.unbroken_run(days[:4], days[4]) == []


def _history(db, last: date = date(2026, 11, 12), n: int = 14, skip: date | None = None) -> list[date]:
    """``n`` sessions of TAIEX closes before the conftest's Friday, each 100 points above the next (so the index
    fell every day down to Monday's 41,040.08)."""
    days = tw_trading_days(last - timedelta(days=40), last)[-n:]
    for i, d in enumerate(reversed(days)):
        if d == skip:
            continue
        db.add(IndexDaily(name=TAIEX, date=d, market="TWSE", close=D("43775.12") + 100 * i, change=D("-100"),
                          change_pct=D("0.0023"), source="twse-openapi"))
    db.commit()
    return days


def _facts(pk, metric):
    return [(f["subject"], f["display"]) for f in pk["facts"] if f["metric"] == metric]


def test_position_facts_come_from_consecutive_official_closes(market_db, us_on):
    _history(market_db)
    built = pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16))
    pk = built.pack
    # 5 日線: (41,040.08 + 43,675.12 + 43,775.12 + 43,875.12 + 43,975.12) / 5; 10 日線: those and the five sessions
    # before them (44,075.12 … 44,475.12); the close is under both
    assert _facts(pk, "index_ma") == [("5 日線", "43,268.11"), ("10 日線", "43,771.62")]
    assert _facts(pk, "index_streak") == [("加權指數", "連 15 日下跌")]
    # ten sessions before Monday the index closed at 44,575.12: 41,040.08 / 44,575.12 − 1
    assert _facts(pk, "index_range_pct") == [("加權指數", "▼7.93%")]
    ma = next(f for f in pk["facts"] if f["metric"] == "index_ma")
    assert ma["dataset"] == "rules:averages" and not ma["estimate"] and "5日線" in ma["aliases"]
    # the trend chart: the index and its averages (thin lines, named as the facts are)
    g1 = built.blocks["charts"]["G1"]
    assert [(x["name"], x.get("role")) for x in g1["series"]] == [("加權指數", None), ("5 日線", "average"),
                                                                 ("10 日線", "average")]
    index, ma5, ma10 = (x["points"] for x in g1["series"])
    assert len(ma5) == len(index) - 4 and len(ma10) == len(index) - 9 and ma5[-1]["v"] == 43268.11
    assert g1["notes"] == ["5 日線、10 日線：最近 5、10 個交易日收盤的平均。"]
    assert pack.PACK_VERSION == 2 and "G1" in pk["fixed_charts"]
    # the row the page prints: only what happened, no word of support or resistance
    pay = _build(market_db, "close", MON, built=built)
    position = next(r for r in pay["brief"] if r["key"] == "position")
    assert position["label"] == "位置" and position["origin"] == "rules"
    [sent] = position["paragraph"]["sentences"]
    assert sent["text"] == "連 15 日下跌，收在 5 日線與 10 日線之下，近 10 個交易日 ▼7.93%。" and sent["cites"]
    assert not any(w in sent["text"] for w in ("支撐", "壓力", "反彈", "回檔"))
    assert pay["trend"] == g1


def test_a_missing_session_shortens_the_run_and_the_averages(market_db, us_on):
    _history(market_db, skip=date(2026, 11, 10))  # 11/11, 11/12, 11/13, 11/16 follow one another: four sessions
    built = pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16))
    assert _facts(built.pack, "index_ma") == [] and _facts(built.pack, "index_range_pct") == []
    assert _facts(built.pack, "index_streak") == [("加權指數", "連 3 日下跌")]
    assert [x["name"] for x in built.blocks["charts"]["G1"]["series"]] == ["加權指數"]  # no average to draw
    pay = _build(market_db, "close", MON, built=built)
    [sent] = next(r for r in pay["brief"] if r["key"] == "position")["paragraph"]["sentences"]
    assert sent["text"] == "連 3 日下跌。"


def test_premarket_position_is_the_previous_session_and_the_writer_may_not_use_it(market_db, us_on):
    _history(market_db)
    built = pack.build(market_db, "premarket", TUE, cutoff=ts(TUE, 6, 55), now=ts(TUE, 7))
    pk = built.pack
    assert {f["group"] for f in pk["facts"] if f["metric"].startswith("index_")} == {"prev_session"}
    pay = _build(market_db, "premarket", TUE, built=built)
    [sent] = next(r for r in pay["brief"] if r["key"] == "position")["paragraph"]["sentences"]
    assert sent["text"] == "加權指數 11/16 收 41,040.08 點（▼6.03%），在 5 日線與 10 日線之下。"
    assert pay["trend"]["series"][0]["points"][-1]["t"] == MON.isoformat()  # drawn to the previous session
    # the previous session's numbers are the server's row: a writer's row that cites one is a repeat of the close
    out = premarket_output(pk)
    out["highlights"][0] = row("overnight", s("加權指數 11/16 在 5 日線之下。", fid(pk, "index_ma", "5 日線")))
    assert ("highlights[0].para.sentences[0]", "repeats_close_report") in _hard(out, pk, "premarket")


def test_turnover_is_compared_like_with_like(market_db, us_on):
    # the next morning's pack: the official FMTQIK of the day against the official numbers of the days before
    for d, value in ((FRI, 1_000_000_000_000), (date(2026, 11, 12), 900_000_000_000),
                     (date(2026, 11, 11), 900_000_000_000), (date(2026, 11, 10), 900_000_000_000)):
        market_db.add(MarketTurnoverDaily(date=d, market="TWSE", trade_value=value, source="twse-openapi"))
    market_db.commit()
    built = pack.build(market_db, "close", MON, cutoff=ts(TUE, 6, 40), now=ts(TUE, 7))
    pk = built.pack
    chg = next(f for f in pk["facts"] if f["metric"] == "turnover_change")
    ratio = next(f for f in pk["facts"] if f["metric"] == "turnover_ratio")
    assert (chg["display"], chg["estimate"], chg["dataset"]) == ("少 969 億元", False, "twse-openapi/turnover")
    assert (ratio["subject"], ratio["display"], ratio["estimate"]) == ("5 日均量", "98%", False)
    pay = _build(market_db, "close", MON, built=built)
    [sent] = next(r for r in pay["brief"] if r["key"] == "volume")["paragraph"]["sentences"]
    assert sent["text"] == "上市 9,031 億元，比前一日少 969 億元，是 5 日均量的 98%。"
    # the afternoon's pack has only its own sum: marked as an estimate, and a difference within what the afternoon's
    # file and the next morning's differ by is not written as a number
    early = pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16))
    chg = next(f for f in early.pack["facts"] if f["metric"] == "turnover_change")
    assert chg["estimate"] and chg["display"] == "和前一日相近" and chg["dataset"] == "rules:turnover_sum"
    assert not [f for f in early.pack["facts"] if f["metric"] == "turnover_ratio"]  # four sessions before it: not there
    [sent] = next(r for r in _build(market_db, "close", MON, built=early)["brief"]
                  if r["key"] == "volume")["paragraph"]["sentences"]
    assert sent["text"] == "上市約 2,295 億元（估算），和前一日相近。"


def test_unusual_lists_what_sets_the_day_apart_the_furthest_first(market_db, us_on):
    _history(market_db)
    pk = pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16)).pack
    whats = [u["what"] for u in pk["unusual"]]
    assert whats[0] == "加權指數連 15 日下跌"  # five times the three sessions that make a run worth a line
    assert "中型100 ▼4.00%，臺灣50 ▼5.80%" in whats
    assert "加權指數下跌 2,635.04 點，其中半導體類約 −1,702 點（估算）" in whats
    assert len(whats) <= pack.UNUSUAL_MAX and all(u["refs"] for u in pk["unusual"])
    assert all(r in {f["id"] for f in pk["facts"]} for u in pk["unusual"] for r in u["refs"])
    # each is a statement of facts: nothing forward-looking, no forbidden word
    for what in whats:
        assert not validate.OUTLOOK.search(what) and not validate.FORECAST.search(what)
        assert not any(w in what for w in prompts.FORBIDDEN_WORDS)
    # the writer reads them with the facts they stand on
    text = prompts.kind_instructions("close", pk)
    assert "# 這一天不一樣的地方" in text and f"- {whats[0]}（" in text
    assert '"unusual"' in prompts.pack_json(pk)
    pre = pack.build(market_db, "premarket", TUE, cutoff=ts(TUE, 6, 55), now=ts(TUE, 7)).pack
    # SMH alone says nothing the gap with SPY did not: one line, not two
    assert [u["what"] for u in pre["unusual"]] == ["SMH 美股 11/16 ▼2.58%，SPY ▲0.50%"]


# -- the writer's rows ---------------------------------------------------------------------------------------------
@pytest.fixture()
def close_pack(market_db, us_on):
    return with_web(pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16)).pack)


@pytest.fixture()
def pre_pack(market_db, us_on):
    return pack.build(market_db, "premarket", TUE, cutoff=ts(TUE, 6, 55), now=ts(TUE, 7)).pack


def _hard(out, pk, kind="close"):
    return [(x.path, x.code) for x in validate.validate(out, pk, kind) if x.hard]


def test_the_schema_asks_for_rows_with_a_field(close_pack):
    for kind, slots in (("close", ["why", "drivers", "chips"]), ("premarket", ["overnight", "why", "scheduled"])):
        rows = prompts.schema(kind, ["G5"])["properties"]["highlights"]["items"]
        assert rows["properties"]["slot"]["enum"] == slots and rows["properties"]["para"] == {"$ref": "#/$defs/para"}
        assert rows["required"] == ["slot", "para"] and prompts.COUNTS[kind]["highlights"] == (1, 3)
        assert set(prompts.BRIEF_SLOTS[kind]) < set(prompts.BRIEF_ORDER[kind])
    # the weekly keeps its 3–5 plain highlights
    assert prompts.schema("weekly", ["G5"])["properties"]["highlights"]["items"] == {"$ref": "#/$defs/para"}
    assert "weekly" not in prompts.BRIEF_SLOTS
    assert _hard(close_output(close_pack), close_pack) == []


def test_a_row_names_one_of_its_kinds_fields_once(close_pack):
    out = close_output(close_pack)
    contrib = fid(close_pack, "stock_contrib", "台積電", "today")
    out["highlights"] = [
        row("drivers", s("台積電（2330）點數貢獻約 −1,616 點（估算）。", contrib)),
        row("position", s("台積電（2330）點數貢獻約 −1,616 點（估算）。", contrib)),  # the server's field
        row("drivers", s("台積電（2330）點數貢獻約 −1,616 點（估算）。", contrib)),  # a second 貢獻
        {"para": {"sentences": [s("台積電（2330）點數貢獻約 −1,616 點（估算）。", contrib)]}},  # no field at all
    ]
    problems = validate.validate(out, close_pack, "close")
    assert [(x.path, x.code) for x in problems if x.code.startswith("slot_")] == [
        ("highlights[1]", "slot_invalid"), ("highlights[2]", "slot_repeated"), ("highlights[3]", "slot_invalid")]
    # each goes alone: the good row stays and the highlights are still the writer's
    d = validate.drop(out, [x for x in problems if x.hard], "close", close_pack)
    assert [r["slot"] for r in d.output["highlights"]] == ["drivers"] and not d.highlights_bad and not d.sections


def test_each_field_stands_on_what_it_is_about(close_pack, pre_pack):
    out = close_output(close_pack)
    pct = fid(close_pack, "index_pct", None, "today")
    out["highlights"] = [
        row("why", s("加權指數跌 6.03%。", pct)),  # a reason needs a report
        row("drivers", s("〔中央社〕報導，外資賣超 1,234.5 億元。", "X001")),  # 貢獻 needs a fact
        row("chips", s("加權指數跌 6.03%。", pct)),  # the listed institutions only from a report
    ]
    assert [(x.path, x.code) for x in validate.validate(out, close_pack, "close") if x.code.startswith("slot_")] == [
        ("highlights[0]", "slot_needs_report"), ("highlights[1]", "slot_needs_fact"),
        ("highlights[2]", "slot_needs_report")]
    d = validate.drop(out, [x for x in validate.validate(out, close_pack, "close") if x.hard], "close", close_pack)
    assert d.output["highlights"] == [] and d.highlights_bad  # no row left: the server's rows stand alone
    # 排定: every sentence is an event of the calendar or a report
    pre = premarket_output(pre_pack)
    pre["highlights"][1] = row("scheduled", s("鴻海（2317）11/17（二）法說會。", cid(pre_pack, "鴻海")),
                               s("SMH 美股 11/16 跌 2.58%。", fid(pre_pack, "us_pct", "SMH", "overnight")))
    assert ("highlights[1]", "slot_not_event") in _hard(pre, pre_pack, "premarket")
    assert _hard(premarket_output(pre_pack), pre_pack, "premarket") == []


def test_the_chips_row_is_held_to_the_chips_rule(close_pack):
    out = close_output(close_pack)
    out["highlights"][1] = row("chips", s("〔中央社〕報導，外資賣超 1,234.5 億元，新台幣貶值。", "X001"))
    assert ("highlights[1].para.sentences[0]", "chips_off_topic") in _hard(out, close_pack)
    # a long row is counted, never dropped for its length
    out = close_output(close_pack)
    out["highlights"][0]["para"]["sentences"] *= 5
    long = [x for x in validate.validate(out, close_pack, "close") if x.code == "too_long"]
    assert [(x.path, x.hard) for x in long] == [("highlights[0].para", False)]


# -- the page --------------------------------------------------------------------------------------------------------
def _build(db, kind, d, output=None, built=None, **kw):
    built = built or pack.build(db, kind, d, cutoff=ts(d, 15, 40) if kind == "close" else ts(d, 6, 55), now=ts(d, 16))
    pk = with_web(built.pack, INST_X) if output else built.pack
    return assemble.build(kind=kind, report_id="mrp_x", edition_date=d, period=(d, d), next_period=None, version=1,
                          edition="ai" if output else "data", pack=pk, blocks=built.blocks,
                          output=output(pk) if output else None, published_at=ts(d, 16), first_published_at=None,
                          as_of=ts(d, 15, 40), title_origin="ai", highlights_origin="ai", **kw)


def test_the_brief_is_in_the_pages_order_with_the_servers_rows_between_the_writers(market_db, us_on):
    pay = _build(market_db, "close", MON, close_output)
    assert [(r["key"], r["label"], r["origin"]) for r in pay["brief"]] == [
        ("drivers", "貢獻", "ai"), ("volume", "量", "rules"), ("chips", "籌碼", "ai")]
    assert pay["highlights_origin"] == "ai" and pay["has_ai"]
    # the highlights are the same paragraphs with the same footnote numbers, from 1 in the page's order
    assert pay["highlights"] == [r["paragraph"] for r in pay["brief"]]
    cites = [n for r in pay["brief"] for sent in r["paragraph"]["sentences"] for n in sent["cites"]]
    assert cites[0] == 1 and cites == sorted(cites)
    # members get no refs and no id string, in the brief either
    public = assemble.public(pay)
    assert all("refs" not in sent for r in public["brief"] for sent in r["paragraph"]["sentences"])
    assert not assemble.has_id_strings(pay)
    # the API's response model passes both on (it drops what it does not know)
    from forliosa.api.schemas_reports import MarketReport as Response

    sent_out = Response.model_validate(public).model_dump()
    assert [(r["key"], r["label"], r["origin"]) for r in sent_out["brief"]] == [
        ("drivers", "貢獻", "ai"), ("volume", "量", "rules"), ("chips", "籌碼", "ai")]
    assert sent_out["brief"][0]["paragraph"]["sentences"][0]["cites"] == [1] and sent_out["trend"]["id"] == "G1"
    # the weekly has neither a brief nor a trend chart
    weekly = _build(market_db, "weekly", date(2026, 11, 22))
    assert weekly["brief"] is None and weekly["trend"] is None


def test_the_scheduled_row_does_not_repeat_its_fields_name(market_db, us_on):
    def output(pk):
        out = premarket_output(pk)
        out["highlights"][1] = row("scheduled", s("已排定：鴻海（2317）11/17（二）法說會。", cid(pk, "鴻海")))
        return out

    pay = _build(market_db, "premarket", TUE, output)
    assert [(r["key"], r["origin"]) for r in pay["brief"]] == [("overnight", "ai"), ("scheduled", "ai"),
                                                               ("position", "rules"), ("chips", "rules")]
    [sent] = next(r for r in pay["brief"] if r["key"] == "scheduled")["paragraph"]["sentences"]
    assert sent["text"] == "鴻海（2317）11/17（二）法說會。"
    # 「昨日台股全貌」 is folded on phones: the previous close report showed these charts already
    assert next(sec for sec in pay["sections"] if sec["key"] == "yesterday")["collapsed_mobile"] is True


def test_rows_the_checks_took_out_fall_back_to_the_servers(market_db, us_on):
    # the highlights failed as a whole (``highlights_origin`` rules): the server's rows, as in the data edition
    built = pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16))
    pk = with_web(built.pack, INST_X)
    pay = assemble.build(kind="close", report_id="mrp_x", edition_date=MON, period=(MON, MON), next_period=None,
                         version=1, edition="ai", pack=pk, blocks=built.blocks, output=close_output(pk),
                         published_at=ts(MON, 16), first_published_at=None, as_of=ts(MON, 15, 40), title_origin="ai",
                         highlights_origin="rules")
    assert [(r["key"], r["origin"]) for r in pay["brief"]] == [("drivers", "rules"), ("volume", "rules")]
    assert pay["highlights_origin"] == "rules" and pay["has_ai"]  # the sections are still the writer's
    assert assemble.data_highlights("close", pk) == [r["paragraph"] for r in assemble.brief_rows("close", pk)]


def test_renumbering_a_stored_payload_keeps_the_brief_and_the_highlights_together(market_db, us_on):
    import json

    built = pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16))
    pk = with_web(built.pack, INST_X)
    stored = json.loads(json.dumps(_build(market_db, "close", MON, close_output, built=built)))  # as the table keeps it
    stored["brief"] = [r for r in stored["brief"] if r["origin"] == "rules"]  # a correction took the writer's rows
    assemble.number_footnotes(stored, pk)
    assert stored["highlights"] == [r["paragraph"] for r in stored["brief"]]
    assert [sent["cites"] for r in stored["brief"] for sent in r["paragraph"]["sentences"]] == [[1]]


def test_pushes_and_the_chat_tool_read_the_rows_with_their_fields(market_db, us_on):
    pay = _build(market_db, "close", MON, close_output)
    lines = push.highlight_lines(pay, "discord")
    rows = ["貢獻：台積電（2330）點數貢獻約 −1,616 點（估算）。", "量：上市約 2,295 億元（估算），和前一日相近。",
            "籌碼：〔中央社〕報導，外資賣超 1,234.5 億元。"]
    assert lines == [*rows[:2], rows[2] + "（出處見全文）"]
    assert [text for text, _cites in market_tools._report_sentences(pay)][:3] == rows
    # a version from before the brief: its plain highlights, as before
    old = {**pay, "brief": None}
    assert push.highlight_lines(old, "discord")[0] == "台積電（2330）點數貢獻約 −1,616 點（估算）。"
