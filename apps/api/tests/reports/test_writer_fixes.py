"""The writer-side fixes of the 11/17 dry run: the schema the API compiles, sentences about missing data, companies
abroad, a stock item's own numbers, ``time_ref``, one failing sentence taking out only itself, and US times written
with their Taipei time."""

from __future__ import annotations

import copy
import json
from datetime import date
from typing import Any

import pytest

from forliosa.reports import calendars, gather, pack, prompts, validate
from tests.reports.conftest import MON, ts
from tests.reports.helpers import INST_X, TRUST_X, close_output, fid, p, s, with_web


@pytest.fixture()
def close_pack(market_db, us_on):
    return with_web(pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16)).pack)


def codes(out, pk, kind="close", names=()):
    return {x.code for x in validate.validate(out, pk, kind, names) if x.hard}


def problems(out, pk, kind="close", names=()):
    return [(x.path, x.code) for x in validate.validate(out, pk, kind, names) if x.hard]


# -- P0-1: the weekly schema was refused ("The compiled grammar is too large") -----------------------------------
def _resolve(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            assert set(node) == {"$ref"} and node["$ref"].startswith("#/$defs/")
            return _resolve(defs[node["$ref"].split("/")[-1]], defs)
        return {k: _resolve(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_resolve(v, defs) for v in node]
    return node


def _conforms(value: Any, sch: dict[str, Any]) -> bool:
    t = sch.get("type")
    if "enum" in sch and value not in sch["enum"]:
        return False
    if t == "string":
        return isinstance(value, str)
    if t == "array":
        return isinstance(value, list) and all(_conforms(v, sch["items"]) for v in value)
    if t == "object":
        props = sch["properties"]
        return isinstance(value, dict) and set(value) == set(sch["required"]) == set(props) \
            and all(_conforms(value[k], props[k]) for k in props)
    return False


def _objects(node: Any) -> list[dict[str, Any]]:
    out = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            out.append(node)
        for v in node.values():
            out += _objects(v)
    elif isinstance(node, list):
        for v in node:
            out += _objects(v)
    return out


@pytest.mark.parametrize("kind", ["premarket", "close", "weekly"])
def test_the_writer_schema_writes_the_paragraph_once(kind):
    sch = prompts.schema(kind, ["G4", "G5"])
    raw = json.dumps(sch, ensure_ascii=False)
    assert len(raw) < 2600  # weekly was 5.6 KB with every paragraph inline and the API refused it
    assert raw.count('"sentences": {') == 1 and set(sch["$defs"]) >= {"sent", "para"}
    full = _resolve(sch, sch["$defs"])
    assert all(o["additionalProperties"] is False and set(o["required"]) == set(o["properties"])
               for o in _objects(full))
    assert full["properties"]["chart_of_day"]["properties"]["code"]["enum"] == ["G4", "G5", "none"]


def test_a_written_report_still_fits_the_schema(close_pack):
    sch = prompts.schema("close", ["G4"])
    out = close_output(close_pack)
    assert _conforms(out, _resolve(sch, sch["$defs"]))
    bad = copy.deepcopy(out)
    bad["what_happened"][0]["sentences"][0]["extra"] = 1
    assert not _conforms(bad, _resolve(sch, sch["$defs"]))


# -- P1-4: what the edition lacks is never written in the body -----------------------------------------------------
@pytest.mark.parametrize("text", [
    "美股收盤價資料這份未開放，未列美股 ETF 與台積電 ADR 的漲跌。",
    "台指期與夜盤行情授權未確認，這份不列夜盤行情。",
    "上市三大法人沒有開放資料，這裡只引用媒體報導。",
    "CPI 與 PPI 的實際結果，未找到報導。",
    "本份未取得海外消息。",
    "櫃買指數的週漲跌與全週成交金額，資料包內沒有資料。",
    "這次下跌的原因未找到報導。",
    "加權指數收 41,040.08 點，證交所官方數字尚未公布。",
])
def test_sentences_about_missing_data_are_hard_problems(close_pack, text):
    out = close_output(close_pack)
    out["what_happened"][0] = p(s(text, fid(close_pack, "index_close", group="today")))
    assert "internal_gap" in codes(out, close_pack)


def test_the_fixed_not_found_sentences_stay_where_the_spec_asks_for_them(close_pack):
    out = close_output(close_pack)
    assert out["stocks"][0]["para"]["sentences"][1]["text"] == "未找到報導。"
    out["stocks"][0]["para"]["sentences"][1]["text"] = "漲跌原因未找到報導。"
    out["chips"].append(p(s("上市三大法人尚未取得可引用的報導。", "X001")))
    assert "internal_gap" not in codes(out, close_pack)
    elsewhere = close_output(close_pack)
    elsewhere["what_happened"][0] = p(s("上市三大法人尚未取得可引用的報導。", "X001"))
    assert "internal_gap" in codes(elsewhere, close_pack)
    title = close_output(close_pack)
    title["title"] = "加權指數收 41,040.08 點，美股資料這份未開放"
    assert ("title", "internal_gap") in problems(title, close_pack)


def test_the_prompts_send_missing_data_to_the_page(close_pack):
    assert "# 缺的資料不寫進正文" in prompts.WRITER_SYSTEM
    assert "找不到報導就寫「未找到報導」" not in prompts.WRITER_SYSTEM
    pk = dict(close_pack, missing=[{"key": "tx_quotes", "text": "台指期與夜盤行情的授權還沒確認，不列行情。"}])
    text = prompts.kind_instructions("close", pk)
    assert "正文不要寫這些" in text and "照實說" not in text
    msg = prompts.revise_message([{"path": "overnight[0].sentences[0]", "code": "internal_gap", "detail": "這份未"}])
    assert prompts.REVISE_HINTS["internal_gap"] in msg


# -- P1-5: companies abroad are named as the report names them --------------------------------------------------
def test_the_writer_is_told_the_list_is_for_taiwan_stocks():
    assert "名單外的台股公司與代號都不能出現" in prompts.WRITER_SYSTEM
    assert "海外公司" in prompts.WRITER_SYSTEM and "美國 AI 晶片龍頭" in prompts.WRITER_SYSTEM
    assert "名單外的公司與代號都不能出現" not in prompts.WRITER_SYSTEM


def _abroad(market_db, key, claim):
    x = {**INST_X, "id": "X003", "key": key, "subject": None, "outlet": "鉅亨網", "title": "三星財報",
         "claim": f"〔鉅亨網〕報導，{claim}。", "quote": claim, "numbers": []}
    pk = with_web(pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16)).pack,
                  INST_X, TRUST_X, x)
    out = close_output(pk)
    out["chips"].append(p(s(f"〔鉅亨網〕報導，{claim}。", "X003")))
    names = ["三星", "國泰金", "英業達", "廣達", "台積電"]  # Taiwan names: two characters a company abroad shares, longer
    return [x.detail for x in validate.validate(out, pk, "close", names) if x.code == "stock_not_allowed"]


@pytest.mark.parametrize("key,ok", [("CO.samsung", True), ("US.earnings.nvda", True), ("ADR.tsm", True),
                                    ("THEME.memory", False), ("TW.reason", False)])
def test_a_two_character_name_from_a_report_abroad_is_that_company(market_db, us_on, key, ok):
    # 三星 in a Samsung story is Samsung; a theme's report names Taiwan 概念股, so it never vouches for a name
    assert (_abroad(market_db, key, "三星財報 11/16 公布") == []) is ok


@pytest.mark.parametrize("key", ["CO.samsung", "US.earnings.nvda", "THEME.memory", "TW.reason"])
def test_a_longer_off_list_taiwan_name_is_never_the_report_s(market_db, us_on, key):
    assert "國泰金" in _abroad(market_db, key, "三星與國泰金財報 11/16 公布")


def test_a_theme_s_concept_stocks_stay_off_the_text(market_db, us_on):
    found = _abroad(market_db, "THEME.ai_server", "市場關注英業達、廣達等概念股")
    assert "英業達" in found and "廣達" in found


# -- P2-7: a stock item's own numbers need no name ----------------------------------------------------------------
def test_a_number_of_the_items_own_stock_needs_no_name(close_pack):
    out = close_output(close_pack)
    tsmc_value = fid(close_pack, "stock_value", "台積電", "today")
    shown = next(f["display"] for f in close_pack["facts"] if f["id"] == tsmc_value)
    out["stocks"][0]["para"]["sentences"].insert(1, s(f"成交金額 {shown}。", tsmc_value))
    assert "number_subject_mismatch" not in codes(out, close_pack)
    # another stock's number in this item, or a clause that names another subject, still needs its own name
    other = next(f for f in close_pack["facts"] if f["metric"] == "stock_value" and f["subject"] != "台積電")
    out["stocks"][0]["para"]["sentences"][1] = s(f"成交金額 {other['display']}。", other["id"])
    assert "number_subject_mismatch" in codes(out, close_pack)
    out["stocks"][0]["para"]["sentences"][1] = s(f"加權指數成交金額 {shown}。", tsmc_value)
    assert "number_subject_mismatch" in codes(out, close_pack)
    # outside a stock item the name is still needed
    plain = close_output(close_pack)
    plain["what_happened"][0] = p(s(f"成交金額 {shown}。", tsmc_value))
    assert "number_subject_mismatch" in codes(plain, close_pack)


# -- P2-8: time_ref takes a calendar id or nothing -----------------------------------------------------------------
def test_tidy_puts_the_cited_calendar_id_in_a_time_ref(close_pack):
    out = close_output(close_pack)
    c = out["tonight"][0]["time_ref"]
    out["tonight"][0]["time_ref"] = "11/17（二）13:30"
    assert validate.tidy(out, "close", close_pack)["tonight"][0]["time_ref"] == c
    assert validate.tidy(out, "close")["tonight"][0]["time_ref"] == c  # without the pack: any C id it cites
    out["tonight"][0]["para"]["sentences"][0]["refs"] = ["X001"]
    assert validate.tidy(out, "close", close_pack)["tonight"][0]["time_ref"] == ""
    unknown = close_output(close_pack)
    unknown["tonight"][0]["time_ref"] = "C999"
    assert validate.tidy(unknown, "close", close_pack)["tonight"][0]["time_ref"] == c


def test_a_bad_time_ref_says_what_it_takes(close_pack):
    out = close_output(close_pack)
    out["tonight"][0]["time_ref"] = "11/17（二）13:30"
    [bad] = [x for x in validate.validate(out, close_pack, "close") if x.path == "tonight[0].time_ref"]
    assert "只能填 C 編號或空字串" in bad.detail
    msg = prompts.revise_message([bad.as_dict()])
    assert "time_ref 只能填 C 編號（例如 C001）或空字串" in msg


# -- P2-9: one failing sentence goes alone -------------------------------------------------------------------------
def test_a_compliance_issue_takes_out_its_sentence_only(close_pack):
    out = close_output(close_pack)
    keep = s("〔中央社〕報導，外資賣超 1,234.5 億元。", "X001")
    out["chips"] = [p(keep, s("〔中央社〕報導，外資短線利空出盡。", "X001"))]
    issue = validate.Problem("chips[0].sentences[1]", "compliance:direction", "短線利空出盡")
    d = validate.drop(out, [issue], "close", close_pack)
    assert d.output["chips"] == [p(keep)] and d.sections == {}
    assert d.sentences == [{"path": "chips[0].sentences[1]", "codes": ["compliance:direction"],
                            "text": "〔中央社〕報導，外資短線利空出盡。"}]
    assert d.output["what_happened"] == out["what_happened"]  # the rest stands
    # without the pack nothing could check what is left: the section goes as before
    assert "chips" in validate.drop(out, [issue], "close").sections


def test_what_is_left_is_checked_again(close_pack):
    out = close_output(close_pack)
    semi = fid(close_pack, "sector_pct", "半導體", "today")
    conc = fid(close_pack, "sector_concentration", "半導體")
    out["sectors"] = [p(s("半導體類指數跌 4.50%。", semi), s("半導體類主要由台積電構成，約 94%。", conc))]
    assert codes(out, close_pack) == set()
    # the sentence with the concentration goes: the other one now lacks it and goes too, and the section is empty
    issue = validate.Problem("sectors[0].sentences[1]", "compliance:direction", "x")
    d = validate.drop(out, [issue], "close", close_pack)
    assert d.output["sectors"] == [] and "sectors" in d.sections
    assert [x["path"] for x in d.sentences] == ["sectors[0].sentences[1]", "sectors[0].sentences[0]"]
    assert codes(d.output, close_pack) == set()


def test_items_and_highlights(close_pack):
    out = close_output(close_pack)
    # a stock item's first sentence names the stock: the item goes with it
    d = validate.drop(out, [validate.Problem("stocks[0].para.sentences[0]", "compliance:direction", "x")],
                      "close", close_pack)
    assert d.output["stocks"] == [] and d.items_dropped == {"stocks": [0]}
    # its later sentence goes alone
    d = validate.drop(out, [validate.Problem("stocks[0].para.sentences[1]", "compliance:direction", "x")],
                      "close", close_pack)
    assert len(d.output["stocks"][0]["para"]["sentences"]) == 1 and not d.items_dropped
    # an item's name takes its item
    d = validate.drop(out, [validate.Problem("tonight[0].event", "compliance:direction", "x")], "close", close_pack)
    assert d.output["tonight"] == [] and "tonight" in d.sections
    # highlights fail only below their minimum (3 for the close)
    d = validate.drop(out, [validate.Problem("highlights[2].sentences[0]", "compliance:direction", "x")], "close",
                      close_pack)
    assert d.highlights_bad and not d.sections


def test_the_market_turning_words_are_filtered_and_forbidden(close_pack):
    assert gather.VIEW is validate.VIEW  # the gathering drops a report's claim on these words
    assert validate.VIEW.search("〔工商時報〕報導，短線利空出盡") and validate.VIEW.search("利多出盡")
    out = close_output(close_pack)
    out["chips"] = [p(s("〔中央社〕報導，外資賣超 1,234.5 億元，短線利空出盡。", "X001"))]
    assert "forbidden_word" in codes(out, close_pack)


# -- P3: a US time is shown with its Taipei time -------------------------------------------------------------------
def test_us_times_get_their_taipei_time():
    day = date(2026, 11, 15)
    assert calendars.us_times_to_taipei("已排定：11/18 美國時間下午 2:00 公布 FOMC 會議紀錄。", day) == \
        "已排定：美東 11/18 14:00（台北 11/19 03:00）公布 FOMC 會議紀錄。"
    assert calendars.us_times_to_taipei("已排定：美東時間 11/18（三）下午 2 點半公布。", day) == \
        "已排定：美東 11/18 14:30（台北 11/19 03:30）公布。"
    assert calendars.us_times_to_taipei("美東 7/1 16:00 財報", day).startswith("美東 7/1 16:00（台北 7/2 04:00）")
    done = "美東 11/18 14:00（台北 11/19 03:00）"
    assert calendars.us_times_to_taipei(done, day) == done  # once only
    for plain in ("美國 10 月 CPI 在 11/10 公布", "美股 11/17 收盤", "美國時間下午 2:00 公布",
                  "已排定：美國 CPI 11/18 21:30 公布"):
        assert calendars.us_times_to_taipei(plain, day) == plain
    # 「美國」 alone names the country: a Taipei time from the calendar after it is not a US local time
    assert calendars.US_LOCAL_TIME.search("已排定：美國 CPI 11/18 21:30 公布") is None
    assert calendars.US_LOCAL_TIME.search("美國時間下午 2:00 公布") is not None
    assert "美東 11/18 14:00" in prompts.WRITER_SYSTEM


def test_the_validator_takes_the_converted_taipei_date_and_nothing_else(close_pack):
    fomc = {**INST_X, "id": "X003", "key": "EVENT.fomc", "subject": None, "outlet": "CNBC", "title": "Fed minutes",
            "claim": "〔CNBC〕報導，Fed 會議紀錄在美東 11/17 下午 2 點公布。", "quote": "Fed 會議紀錄在 11/17 公布",
            "numbers": []}
    pk = with_web(close_pack, INST_X, TRUST_X, fomc)
    out = close_output(pk)
    out["tonight"][0]["para"] = p(s("已排定：11/17 美國時間下午 2:00 公布 FOMC 會議紀錄。", "X003"))
    assert "us_local_time" in codes(out, pk)  # as the writer wrote it
    tidy = validate.tidy(out, "close", pk)
    assert tidy["tonight"][0]["para"]["sentences"][0]["text"] == \
        "已排定：美東 11/17 14:00（台北 11/18 03:00）公布 FOMC 會議紀錄。"
    assert codes(tidy, pk) == set()  # 11/18 is the conversion of a sourced US time
    forged = copy.deepcopy(tidy)
    forged["tonight"][0]["para"]["sentences"][0]["text"] = "已排定：美東 11/17 14:00（台北 11/20 03:00）公布會議紀錄。"
    assert "date_not_sourced" in codes(forged, pk)
