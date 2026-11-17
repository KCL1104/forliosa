"""The rule checks of the writer's JSON (contract §10.2): a clean draft passes; each mutation trips its own check."""

from __future__ import annotations

import copy

import pytest

from forliosa.reports import pack, validate
from tests.reports.conftest import MON, TUE, ts
from tests.reports.helpers import INST_X, TRUST_X, close_output, fid, p, premarket_output, s, with_web


@pytest.fixture()
def close_pack(market_db, us_on):
    return with_web(pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16)).pack)


@pytest.fixture()
def pre_pack(market_db, us_on):
    return pack.build(market_db, "premarket", TUE, cutoff=ts(TUE, 6, 55), now=ts(TUE, 7)).pack


def hard(out, pk, kind="close", names=()):
    return [(x.path, x.code) for x in validate.validate(out, pk, kind, names) if x.hard]


def codes(out, pk, kind="close", names=()):
    return {x.code for x in validate.validate(out, pk, kind, names) if x.hard}


def test_a_clean_draft_has_no_hard_problem(close_pack, pre_pack):
    assert hard(close_pack and close_output(close_pack), close_pack) == []
    assert hard(premarket_output(pre_pack), pre_pack, "premarket") == []


def with_sentence(out, key, text, *refs, idx=0):
    o = copy.deepcopy(out)
    o[key][idx] = p(s(text, *refs))
    return o


def test_refs(close_pack):
    out = close_output(close_pack)
    assert "bad_ref" in codes(with_sentence(out, "what_happened", "加權指數收 41,040.08 點。", "F999"), close_pack)
    assert "no_refs" in codes(with_sentence(out, "what_happened", "加權指數收 41,040.08 點。"), close_pack)
    unknown = with_sentence(out, "chips", "〔中央社〕報導，外資賣超 1,234.5 億元。", "X009")
    assert "bad_ref" in codes(unknown, close_pack)


def test_numbers_must_come_from_the_refs_and_rounding_is_allowed(close_pack):
    out = close_output(close_pack)
    close = fid(close_pack, "index_close", group="today")
    pct = fid(close_pack, "index_pct", group="today")
    assert "number_unsourced" in codes(with_sentence(out, "what_happened", "加權指數收 41,041.08 點。", close),
                                       close_pack)
    assert codes(with_sentence(out, "what_happened", "加權指數約跌 6.0%。", pct), close_pack) == set()
    # 億 and 兆 are scaled: 46.92 兆元 written as 469,200 億元
    total = fid(close_pack, "mcap_total")
    assert codes(with_sentence(out, "what_happened", "上市總市值約 469,200 億元。", total), close_pack) == set()


def test_subject_must_be_named_next_to_its_number(close_pack):
    out = close_output(close_pack)
    # 外資 and 投信 swapped: 179.63 is 投信's
    swapped = with_sentence(out, "chips", "〔中央社〕報導，外資賣超 179.63 億元、投信賣超 1,234.5 億元。",
                            "X001", "X002")
    assert "number_subject_mismatch" in codes(swapped, close_pack)
    right = with_sentence(out, "chips", "〔中央社〕報導，外資賣超 1,234.5 億元、投信賣超 179.63 億元。", "X001", "X002")
    assert codes(right, close_pack) == set()
    otc = fid(close_pack, "otc_close", group="today")
    assert "number_subject_mismatch" in codes(with_sentence(out, "what_happened", "加權指數收 319.12 點。", otc),
                                              close_pack)


def test_direction(close_pack):
    out = close_output(close_pack)
    pct = fid(close_pack, "index_pct", group="today")
    assert "direction_mismatch" in codes(with_sentence(out, "what_happened", "加權指數漲 6.03%。", pct), close_pack)
    assert "direction_mismatch" in codes(with_sentence(out, "what_happened", "加權指數 ▲6.03%。", pct), close_pack)
    up = fid(close_pack, "adv_down", group="today")
    assert codes(with_sentence(out, "what_happened", "上市普通股下跌 6 家。", up), close_pack) == set()  # counts


def test_dates(close_pack):
    out = close_output(close_pack)
    pct = fid(close_pack, "index_pct", group="today")
    inferred = with_sentence(out, "what_happened", "加權指數 11/16 跌 6.03%，對應 11/10（二）。", pct)
    assert "date_not_sourced" in codes(inferred, close_pack)
    assert "weekday_mismatch" in codes(with_sentence(out, "what_happened", "加權指數 11/16（三）跌 6.03%。", pct),
                                       close_pack)
    assert "weekday_mismatch" in codes(with_sentence(out, "what_happened", "加權指數週五跌 6.03%。", pct), close_pack)
    assert codes(with_sentence(out, "what_happened", "加權指數 11/16（一）跌 6.03%。", pct), close_pack) == set()


@pytest.mark.parametrize("word", ["明天", "本週", "目標價", "支撐", "看好", "值得關注", "加碼"])
def test_forbidden_and_time_words(close_pack, word):
    pct = fid(close_pack, "index_pct", group="today")
    out = with_sentence(close_output(close_pack), "what_happened", f"加權指數跌 6.03%，{word}。", pct)
    assert "forbidden_word" in codes(out, close_pack)


def test_style_words_are_counted_not_hard(close_pack):
    pct = fid(close_pack, "index_pct", group="today")
    out = with_sentence(close_output(close_pack), "what_happened", "此外，加權指數跌 6.03%！", pct)
    probs = validate.validate(out, close_pack, "close")
    assert any(x.code == "style_word" and not x.hard for x in probs) and codes(out, close_pack) == set()


def test_stocks_only_from_the_list(close_pack):
    pct = fid(close_pack, "index_pct", group="today")
    out = close_output(close_pack)
    assert "stock_not_allowed" in codes(with_sentence(out, "what_happened", "國巨（2327）跌 6.03%。", pct), close_pack)
    names = ["國泰金", "台積電"]
    assert "stock_not_allowed" in codes(with_sentence(out, "what_happened", "國泰金跌 6.03%。", pct), close_pack,
                                        names=names)
    assert codes(with_sentence(out, "what_happened", "加權指數跌 6.03%。", pct), close_pack, names=names) == set()


def test_sectors(close_pack):
    out = close_output(close_pack)
    semi = fid(close_pack, "sector_pct", "半導體", "today")
    glass = fid(close_pack, "sector_pct", "玻璃陶瓷", "today")
    assert "sector_not_allowed" in codes(with_sentence(out, "sectors", "玻璃陶瓷類跌 9.50%。", glass), close_pack)
    # 半導體 without its concentration in the same paragraph
    assert "sector_not_allowed" in codes(with_sentence(out, "sectors", "半導體類跌 4.50%。", semi), close_pack)


def test_fund_flow_and_move_of_a_stock_in_one_sentence(close_pack):
    pct = fid(close_pack, "stock_pct", "台積電", "today")
    out = with_sentence(close_output(close_pack), "chips", "〔中央社〕報導，外資賣超 1,234.5 億元，台積電跌 4.67%。",
                        "X001", pct)
    assert "flow_and_move" in codes(out, close_pack)


def test_a_cause_needs_a_report(close_pack):
    pct = fid(close_pack, "index_pct", group="today")
    out = with_sentence(close_output(close_pack), "what_happened", "加權指數受美股影響跌 6.03%。", pct)
    assert "cause_without_source" in codes(out, close_pack)
    ok = with_sentence(close_output(close_pack), "what_happened", "〔中央社〕報導，外資賣超 1,234.5 億元，主因是賣壓。",
                       "X001")
    assert "cause_without_source" not in codes(ok, close_pack)


def test_outlook_takes_one_of_three_shapes(close_pack):
    out = close_output(close_pack)
    pct = fid(close_pack, "index_pct", group="today")
    assert "outlook_pattern" in codes(with_sentence(out, "what_happened", "加權指數跌 6.03%，後續可能反彈。", pct),
                                      close_pack)
    ok = with_sentence(out, "what_happened", "〔中央社〕報導市場關注外資賣超 1,234.5 億元後的動向。", "X001")
    assert "outlook_pattern" not in codes(ok, close_pack)
    # tonight's items: every sentence must be one of the shapes
    bad = copy.deepcopy(out)
    bad["tonight"][0]["para"] = p(s("鴻海（2317）法說會在 11/17（二）。", bad["tonight"][0]["time_ref"]))
    assert "outlook_pattern" in codes(bad, close_pack)
    rel = copy.deepcopy(out)
    rel["tonight"][0]["para"] = p(s("這件事和其他電子類股的關係是鴻海（2317）屬於其他電子業。",
                                    rel["tonight"][0]["time_ref"]))
    assert "outlook_pattern" not in codes(rel, close_pack)


def test_position_numbers_are_never_a_reason(pre_pack):
    out = premarket_output(pre_pack)
    pc = fid(pre_pack, "pc_ratio_oi")
    c = out["watch"][0]["time_ref"]
    out["watch"][0]["para"] = p(s("已排定：鴻海（2317）11/17（二）法說會，P/C 比 53.79%。", c, pc))
    assert "options_as_reason" in codes(out, pre_pack, "premarket")


def test_premarket_headline_does_not_repeat_the_previous_session(pre_pack):
    out = premarket_output(pre_pack)
    prev = fid(pre_pack, "index_pct", group="prev_session")
    out["highlights"][0] = p(s("加權指數 11/16 跌 6.03%。", prev))
    assert "repeats_close_report" in codes(out, pre_pack, "premarket")
    out2 = premarket_output(pre_pack)
    out2["title"] = "加權指數 11/16 跌 6.03%，今天看美股"
    assert {"repeats_close_report", "forbidden_word"} <= codes(out2, pre_pack, "premarket")


def test_index_points(close_pack):
    out = with_sentence(close_output(close_pack), "chips", "〔中央社〕報導，費半指數收 6,123.45 點。", "X001")
    assert "index_points" in codes(out, close_pack)


def test_chart_of_day_must_be_on_the_menu(close_pack):
    out = close_output(close_pack)
    out["chart_of_day"]["code"] = "G2"
    assert "chart_invalid" in codes(out, close_pack)


def test_stock_items(close_pack):
    out = close_output(close_pack)
    out["stocks"].append({"symbol": "2327.TW", "para": p(s("國巨（2327）跌 1%。", "F001"))})
    out["stocks"][0]["para"]["sentences"][0]["text"] = "收 1,430.00 元，台積電（2330）跌 4.67%。"
    probs = [x for x in validate.validate(out, close_pack, "close") if x.code == "stock_item_mismatch"]
    assert {x.path for x in probs} == {"stocks[0]", "stocks[1]"}
    dropped = validate.drop(out, probs, "close")
    assert dropped.output["stocks"] == [] and dropped.sections == {}  # items only, not the section


def test_counts_lengths_and_unknown_sectors_are_soft(close_pack):
    out = close_output(close_pack)
    out["highlights"] = out["highlights"] * 2
    out["tonight"][0]["sectors"] = ["其他電子", "AI 伺服器"]
    probs = validate.validate(out, close_pack, "close")
    soft = {x.code for x in probs if not x.hard}
    assert {"count_out_of_range", "sector_unknown"} <= soft
    tidy = validate.tidy(out, "close")
    assert len(tidy["highlights"]) == 3 and tidy["tonight"][0]["sectors"] == ["其他電子"]


def test_repeating_the_strip_is_counted(close_pack):
    out = close_output(close_pack)
    probs = validate.validate(out, close_pack, "close")
    assert any(x.code == "repeats_strip" for x in probs)  # the first highlight cites three strip numbers


def test_drop_sections_and_what_is_left(close_pack):
    out = close_output(close_pack)
    pct = fid(close_pack, "index_pct", group="today")
    out["what_happened"][0] = p(s("加權指數跌 6.03%，明天可能反彈。", pct))
    out["title"] = "明天的台股"
    probs = [x for x in validate.validate(out, close_pack, "close") if x.hard]
    d = validate.drop(out, probs, "close")
    assert "what_happened" in d.sections and d.output["what_happened"] == [] and d.title_bad
    assert not d.highlights_bad
    assert validate.ai_sections_left(d.output, "close") >= 2


def test_mentions_anthropic(close_pack):
    out = with_sentence(close_output(close_pack), "chips", "〔中央社〕報導，Anthropic 外資賣超 1,234.5 億元。", "X001")
    assert validate.mentions_anthropic(out, "close")
    assert not validate.mentions_anthropic(close_output(close_pack), "close")


def test_number_extraction():
    nums = validate.numbers("加權指數 11/16 收 41,040.08 點，▼2,635.04 點；成交 1.2 兆元；台積電（2330）前 10 大 3 檔")
    assert [round(n.value, 2) for n in nums] == [41040.08, 2635.04, 1.2e12]
    assert nums[1].sign == -1 and nums[0].sign == 0
    assert validate.numbers("漲停 3 家、跌停 1 家")[1].sign == 0  # 跌停 is not a direction
    assert INST_X["subject"] == "外資" and TRUST_X["subject"] == "投信"
