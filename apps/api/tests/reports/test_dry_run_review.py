"""Review of the 2026-11-17 dry-run fixes: the server's own calendar titles pass the US-time check, a one-digit US hour
is written and read as converted, every watch / tonight item is a real event, the evening notes hold no previous
session's number, a named source may say what it lacks (the edition may not), and a page cited first as shared
research still shows the verified report's footnote."""

from __future__ import annotations

import copy
from datetime import date, datetime

import pytest

from forliosa.models import NyseHoliday
from forliosa.reports import assemble, calendars, pack, prompts, validate
from forliosa.timeutil import TAIPEI
from tests.reports.conftest import MON, TUE, ts
from tests.reports.helpers import INST_X, TRUST_X, close_output, fid, p, premarket_output, s, with_web


@pytest.fixture()
def close_pack(market_db, us_on):
    return with_web(pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16)).pack)


@pytest.fixture()
def pre_pack(market_db, us_on):
    return pack.build(market_db, "premarket", TUE, cutoff=ts(TUE, 6, 55), now=ts(TUE, 7)).pack


def hard(out, pk, kind="close"):
    return [(x.path, x.code) for x in validate.validate(out, pk, kind) if x.hard]


def with_calendar(pk, *rows):
    out = copy.deepcopy(pk)
    out["calendar"] = [*out["calendar"], *({"date": MON.isoformat(), "time_taipei": None, "kind": "us_holiday",
                                            "symbol": None, "sectors": [], "source": "manual-calendar", "url": None,
                                            "fold": None, "note": "", **r} for r in rows)]
    return out


# -- P3: the server's own calendar titles ---------------------------------------------------------------------------
def test_an_early_close_title_carries_its_taipei_time_and_no_time_word():
    assert calendars.nyse_title(date(2026, 11, 27), "感恩節翌日（提早收盤）", "early_close", "13:00") == \
        "美股 11/27 感恩節後一天提早於美東 11/27 13:00（台北 11/28 02:00）收盤"
    assert calendars.nyse_title(date(2026, 12, 24), "聖誕夜（提早收盤）", "early_close", "13:00") == \
        "美股 12/24 聖誕夜提早於美東 12/24 13:00（台北 12/25 02:00）收盤"
    assert calendars.nyse_title(date(2026, 11, 26), "感恩節", "closed", None) == "美股 11/26 感恩節休市"
    # an admin's name that the checks would refuse is left out (the date and the kind say enough)
    assert calendars.nyse_title(date(2026, 11, 27), "週五提早收盤", "early_close", "13:00") == \
        "美股 11/27 提早於美東 11/27 13:00（台北 11/28 02:00）收盤"


def test_the_seeded_early_close_reaches_the_calendar_in_that_form(market_db):
    market_db.add(NyseHoliday(date=MON, name="感恩節翌日（提早收盤）", kind="early_close", close_time_et="13:00",
                              source_url=calendars.NYSE_URL, updated_by="seed",
                              updated_at=datetime(2026, 11, 1, tzinfo=TAIPEI)))
    market_db.commit()
    try:
        [e] = [e for e in calendars.events_between(market_db, MON, MON, cutoff=ts(MON, 15, 40))
               if e.kind == "us_holiday"]
        assert e.title == "美股 11/16 感恩節後一天提早於美東 11/16 13:00（台北 11/17 02:00）收盤"
    finally:
        calendars.set_us_calendar([])
    assert "翌日" not in (calendars.SEEDS / "nyse_holidays.json").read_text(encoding="utf-8")


def test_a_sentence_copying_the_early_close_title_passes(close_pack):
    title = calendars.nyse_title(MON, "感恩節翌日（提早收盤）", "early_close", "13:00")
    pk = with_calendar(close_pack, {"id": "C099", "title": title})
    out = close_output(pk)
    out["tonight"].append({"event": title, "time_ref": "C099", "sectors": [],
                           "para": p(s(f"已排定：{title}。", "C099"))})
    tidy = validate.tidy(out, "close", pk)
    assert tidy["tonight"][1]["event"] == title  # already converted: left as it is
    assert [x for x in hard(tidy, pk) if x[0].startswith("tonight")] == []
    # its text alone is read as converted (not only because the sentence cites the row)
    ctx = validate.context(pk, "close")
    assert validate.us_local_time(ctx, validate.normalize(f"已排定：{title}。")) is None
    # the title of the dry run failed twice: 「美東 13:00」 without a Taipei time, and 「翌日」
    old = "美股 11/16 感恩節翌日提早收盤（美東 13:00）"
    bad = close_output(with_calendar(close_pack, {"id": "C099", "title": old}))
    bad["tonight"].append({"event": "美股提早收盤", "time_ref": "C099", "sectors": [],
                           "para": p(s(f"已排定：{old}。", "X001"))})
    found = hard(bad, with_calendar(close_pack, {"id": "C099", "title": old}))
    assert ("tonight[1].para.sentences[0]", "us_local_time") in found
    assert ("tonight[1].para.sentences[0]", "forbidden_word") in found


def test_a_cited_calendar_title_is_the_server_s_own_words(close_pack):
    pk = with_calendar(close_pack, {"id": "C098", "title": "FOMC 會議紀錄（美東 14:00）", "time_taipei": "03:00"})
    out = close_output(pk)
    out["tonight"][0]["para"] = p(s("已排定：FOMC 會議紀錄（美東 14:00）。", "C098"))
    assert not any(code == "us_local_time" for _path, code in hard(out, pk))
    out["tonight"][0]["para"] = p(s("已排定：FOMC 會議紀錄（美東 14:00）。", "X001"))  # not the row's words now
    assert ("tonight[0].para.sentences[0]", "us_local_time") in hard(out, pk)


def test_a_one_digit_us_hour_is_written_and_read_as_converted():
    assert calendars.earnings_label(date(2026, 11, 19), "bmo", "9:30") == "美東 11/19 09:30（台北 11/19 22:30）"
    assert calendars.converted_spans("美東 11/19 9:30（台北 11/19 22:30）", date(2026, 11, 19))
    assert calendars.converted_spans("美東 11/19 09:30（台北 11/19 22:30）", date(2026, 11, 19))
    assert not calendars.converted_spans("美東 11/19 9:30（台北 11/19 21:30）", date(2026, 11, 19))  # wrong time


# -- P2-12: watch and tonight hold real events; the evening notes hold the evening's data -------------------------
def test_a_watch_item_without_a_calendar_or_report_event_goes_alone(pre_pack):
    out = premarket_output(pre_pack)
    up = fid(pre_pack, "otc_adv_up", group="evening")
    out["watch"].append({"event": "台股 11/17（二）開盤", "time_ref": "", "sectors": [],
                         "para": p(s("這件事和電子類股的關係是上櫃普通股 11/16 上漲 1 家。", up))})
    probs = validate.validate(out, pre_pack, "premarket")
    assert [(x.path, x.code, x.hard) for x in probs if x.code == "item_not_event"] == \
        [("watch[2]", "item_not_event", True)]
    d = validate.drop(out, [x for x in probs if x.hard], "premarket", pre_pack)
    assert d.items_dropped == {"watch": [2]} and len(d.output["watch"]) == 2 and "watch" not in d.sections
    # without the pack the item still goes alone, never the section
    d = validate.drop(out, [validate.Problem("watch[2]", "item_not_event")], "premarket")
    assert d.items_dropped == {"watch": [2]} and len(d.output["watch"]) == 2 and d.sections == {}
    assert "item_not_event" in prompts.REVISE_HINTS


def test_an_item_on_a_report_or_the_calendar_is_an_event(close_pack):
    out = close_output(close_pack)
    assert not any(code == "item_not_event" for _path, code in hard(out, close_pack))  # time_ref: a C
    out["tonight"][0] = {"event": "外資動向", "time_ref": "", "sectors": [],
                         "para": p(s("〔中央社〕報導市場關注外資賣超 1,234.5 億元後的動向。", "X001"))}
    assert not any(code == "item_not_event" for _path, code in hard(out, close_pack))
    out["tonight"][0]["para"] = p(s("這件事和半導體類股的關係是加權指數收 41,040.08 點。",
                                    fid(close_pack, "index_close", group="today")))
    assert ("tonight[0]", "item_not_event") in hard(out, close_pack)


def test_the_evening_notes_take_no_previous_session_number(pre_pack):
    out = premarket_output(pre_pack)
    otc = next(f for f in pre_pack["facts"] if f["metric"] == "otc_close" and f["group"] == "prev_session")
    out["evening_notes"].append(p(s(f"櫃買指數 11/16 收 {otc['display']} 點。", otc["id"])))
    assert ("evening_notes[1].sentences[0]", "repeats_close_report") in hard(out, pre_pack, "premarket")
    assert not any(path.startswith("evening_notes[0]") for path, _code in hard(out, pre_pack, "premarket"))
    spec = prompts.SPEC["premarket"]["sections"]
    notes = next(line for line in spec.splitlines() if line.startswith("- evening_notes"))
    assert "上櫃漲跌家數" in notes and "櫃買、" not in notes
    assert "group=prev_session" in spec.split("- evening_notes", 1)[1].split("- watch", 1)[0]


# -- internal_gap: what a named source says it lacks is a fact ------------------------------------------------------
CO_X = {**INST_X, "id": "X003", "key": "CO.tsmc", "subject": None, "outlet": "鉅亨網", "title": "美國新廠",
        "claim": "〔鉅亨網〕報導，台積電官方尚未公布美國新廠的投資金額。",
        "quote": "台積電官方尚未公布美國新廠的投資金額，主管機關表示尚無相關資料可提供。", "numbers": []}


@pytest.mark.parametrize("text", ["〔鉅亨網〕報導，台積電官方尚未公布美國新廠的投資金額。",
                                  "〔鉅亨網〕報導，主管機關表示尚無相關資料可提供。"])
def test_a_named_source_may_say_what_it_lacks(market_db, us_on, text):
    pk = with_web(pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16)).pack,
                  INST_X, TRUST_X, CO_X)
    out = close_output(pk)
    out["what_happened"].append(p(s(text, "X003")))
    assert ("what_happened[2].sentences[0]", "internal_gap") not in hard(out, pk)
    out["what_happened"][2] = p(s(text, "X001"))  # a report that says nothing of the kind: the edition's words
    assert ("what_happened[2].sentences[0]", "internal_gap") in hard(out, pk)
    # the edition's own voice is a gap whatever the sentence cites
    out["what_happened"][2] = p(s("〔鉅亨網〕報導，台積電官方尚未公布投資金額，這份未列細項。", "X003"))
    assert ("what_happened[2].sentences[0]", "internal_gap") in hard(out, pk)


@pytest.mark.parametrize("text,gap", [
    ("英國（大不列顛）央行維持利率不變", None),
    ("該檔 ETF 未列於 MSCI 名單", None),
    ("證交所開放資料顯示外資賣超", None),
    ("上市三大法人沒有開放資料", "沒有開放"),
    ("台指期與夜盤行情這份不列", "這份不"),
    ("夜盤行情不列", "不列"),
])
def test_ordinary_words_are_not_internal_gaps(text, gap):
    assert validate.gap_phrase("what_happened", validate.normalize(text)) == gap


# -- footnotes: a page cited as shared research before its verified report -----------------------------------------
def test_a_page_cited_as_research_first_keeps_the_report_s_footnote(market_db):
    built = pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16))
    pk = with_web(built.pack, INST_X)
    pk["research"] = [{"id": "W001", "symbol": "2330.TW", "session": MON.isoformat(),
                       "sources": [{"outlet": "中央社", "title": "共用研究的標題",
                                    "url": "https://cna.com.tw/news/afe/202611160123.aspx?utm_source=x",
                                    "published": None}], "quotes": ["…"]}]
    out = close_output(pk)
    out["stocks"][0]["para"]["sentences"].append(s("〔中央社〕報導，外資賣超。", "W001"))  # stocks come before chips
    pay = assemble.build(kind="close", report_id="mrp_x", edition_date=MON, period=(MON, MON), next_period=None,
                         version=1, edition="ai", pack=pk, blocks=built.blocks, output=out, published_at=ts(MON, 16),
                         first_published_at=None, as_of=ts(MON, 15, 40), title_origin="ai", highlights_origin="ai")
    [page] = [f for f in pay["footnotes"] if f["kind"] in ("web", "research")]
    assert page["kind"] == "web" and page["url"] == INST_X["url"] and page["label"] == INST_X["title"]
    assert page["date_label"] == "11/16 15:32"
    assert pay["sources"]["web"] == [{"n": page["n"], "outlet": "中央社", "title": INST_X["title"],
                                      "url": INST_X["url"], "published_label": "11/16 15:32"}]
