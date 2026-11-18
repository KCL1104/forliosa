"""The owner's decisions after the second dry run (2026-11-17) and the fixes that needed none:

1. Option A (P0-2 / N1): the close edition keeps a same-day page without a publish time when the numbers of its cited
   passages match that day's official close; a page whose numbers contradict it is still dropped.
2. No stock has a reason: one sentence for the whole section (「個股的漲跌原因未找到報導。」), not one per stock.
3. Option A (N5): no private-life details (an affair, a relationship, health, family), only the business fact.
4. N3: the weekly uses a calendar row or a report once per section (highlights, this week, themes, risks); its risks
   are only what is still ahead or pending; the chips sections hold institutional investors and fund flows only.
5. N4: numbers copied from a report get thousands separators; a headline's clauses are separated with 「，」.
6. N6: the premarket's data headline never names an empty calendar."""

from __future__ import annotations

import copy
from datetime import date, datetime

import pytest

from forliosa.ai.analyst import SearchResult
from forliosa.ai.market_summary import _norm_url
from forliosa.config import Settings
from forliosa.reports import assemble, calls, compliance, gather, pack, prompts, validate
from forliosa.timeutil import TAIPEI
from tests.ai.fake_anthropic import FakeAnthropic
from tests.reports.conftest import MON, TUE, ts
from tests.reports.helpers import INST_X, close_output, fid, gather_reply, json_text, p, s, with_web


@pytest.fixture()
def close_built(market_db, us_on):
    return pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16))


@pytest.fixture()
def close_pack(close_built):
    return with_web(close_built.pack, copy.deepcopy(INST_X))


# -- 1. Option A: a same-day page dated by its numbers ---------------------------------------------------------------
UDN = "https://money.udn.com/money/story/5607/9882230"


def close_window(pk, now=None):
    """The close edition of 11/16 (the conftest market: 加權指數 41,040.08 ▼2,635.04 ▼6.03%, 台積電 1,430 ▼70
    ▼4.67%) searched at 15:45."""
    return gather.window(pk, now or ts(MON, 15, 45))


def check(w, cited, *, page_age="0 days ago", key="STOCK.2330", claim="〔經濟日報〕報導，台積電與大盤同步收黑。"):
    res = {_norm_url(UDN): SearchResult(UDN, "台積電重挫 大盤收黑", page_age)}
    cites = [{"type": "web_search_result_location", "url": UDN, "title": "台積電重挫 大盤收黑", "cited_text": cited}]
    return gather.verify(key, claim, cites, res, w, ("STOCK.",))


def test_the_close_window_carries_the_official_close(close_pack, market_db):
    w = close_window(close_pack)
    assert w.close is not None
    assert w.close.names["台積電"] == "台積電" and w.close.names["大盤"] == "加權指數" and "上市" not in w.close.names
    cash = sorted(round(v, 2) for v, _signed in w.close.values["台積電"]["元"])
    assert cash == [-70.0, 1430.0]  # the close, and its change from the reference price (derived)
    pre = pack.build(market_db, "premarket", TUE, cutoff=ts(TUE, 6, 55), now=ts(TUE, 7)).pack
    assert gather.window(pre, ts(TUE, 6, 30)).close is None


@pytest.mark.parametrize("cited", [
    "國安基金護盤失敗！台積電震盪115元下跌70元，指數收跌2635點。",  # the dry run's headline: 947 for ▼947.97
    "台積電今天收1,430元，跌幅4.67%，加權指數終場下跌6.03%。",
    "加權指數收跌2,635.04點，收在41,040.08點。",
])
def test_a_same_day_page_whose_numbers_match_the_close_is_kept(close_pack, cited):
    fact, why = check(close_window(close_pack), cited)
    assert why is None
    assert fact["published_at"] == "2026-11-16" and fact["date_only"]
    assert fact["dated_by"] == "matched_close_numbers"
    assert "dated_by" not in gather.for_writer([fact])[0]  # diagnostics only, never sent to the writer


@pytest.mark.parametrize("cited", [
    "台積電今天收1,450元，成交量比前一個交易日放大。",  # the close was 1,430
    "台積電上漲70元，加權指數收跌2635點。",  # the change went the other way
    "加權指數收跌950點，台積電下跌70元。",  # one number contradicting is enough
])
def test_a_same_day_page_whose_numbers_contradict_the_close_is_dropped(close_pack, cited):
    assert check(close_window(close_pack), cited) == (None, "contradicts_close")


@pytest.mark.parametrize("cited", [
    "台積電法說會將於下午舉行，市場關注資本支出。",  # no number
    "台積電盤中一度下跌90元，跌破1,400元關卡。",  # the session's swings are not the close
    "台積電ADR下跌4.67%，費半指數重挫6.03%。",  # another market's numbers
    "加權指數收跌逾2,000點，台積電跌近5%。",  # rounded figures: neither a match nor a contradiction
])
def test_a_same_day_page_without_a_closing_number_still_needs_a_publish_time(close_pack, cited):
    assert check(close_window(close_pack), cited) == (None, "no_publish_time")


def test_option_a_is_the_close_edition_s_only(close_pack):
    cited = "台積電下跌70元，加權指數收跌2635點。"
    w = close_window(close_pack)
    no_close = gather.Window(w.start, w.end, w.cutoff, w.us_sessions, w.now)
    assert check(no_close, cited) == (None, "no_publish_time")
    # searched before the session closed (13:30): the numbers cannot be that day's close
    assert check(close_window(close_pack, ts(MON, 12, 0)), cited) == (None, "no_publish_time")
    # a page with its publish time keeps it (and needs no numbers)
    fact, why = check(w, "2026-11-16 14:35 經濟日報／記者王小明／台北即時報導")
    assert why is None and fact["published_at"] == "2026-11-16T14:35:00+08:00" and "dated_by" not in fact


def test_the_topic_row_records_the_pages_dated_by_their_numbers(close_pack):
    calls.reset_state()
    fake = FakeAnthropic().reply(*gather_reply("STOCK.2330", "〔經濟日報〕報導，台積電下跌70元。", UDN,
                                               "台積電重挫", "國安基金護盤失敗！台積電下跌70元，指數收跌2635點。",
                                               page_age="0 days ago"))
    client = fake.client("sk-test")
    t = gather.Topic("STOCK_REASONS", 1, "brief", gather.TOPICS["close"]["STOCK_REASONS"][2])
    res = gather.run_topics([t], "claude-sonnet-5-5", "low", lambda kw, only: (calls.create(client, kw), 1),
                            Settings(), threads=1, clock=lambda: ts(MON, 15, 44))
    out = gather.collect(res, close_window(close_pack))
    assert len(out.facts) == 1 and out.facts[0]["dated_by"] == "matched_close_numbers"
    assert out.topics[0]["accepted"] == {"matched_close_numbers": 1} and out.topics[0]["dropped"] == {}


def test_the_close_brief_asks_for_the_closing_numbers_when_there_is_no_time():
    brief = prompts.topic_brief("close", "STOCK_REASONS", window=("2026-11-16T08:00:00+08:00", "x"),
                                edition_label="11/16（一）", us_sessions=[], names=["台積電（2330）"])
    assert "收盤數字" in brief and "不會被採用" not in brief.split("收盤數字")[0]


# -- 2. no stock has a reason: one sentence for the section ---------------------------------------------------------
def two_stocks(pk, reason_ref=None):
    out = close_output(pk)
    second = [s("聯發科（2454）收 1,440.00 元，跌 4.00%。", fid(pk, "stock_close", "聯發科", "today"),
                fid(pk, "stock_pct", "聯發科", "today"))]
    second.append(s("〔中央社〕報導，外資賣超 1,234.5 億元。", reason_ref) if reason_ref
                  else s("未找到報導。", fid(pk, "stock_pct", "聯發科", "today")))
    out["stocks"].append({"symbol": "2454.TW", "para": p(*second)})
    return out


def stock_texts(out):
    return [[x["text"] for x in it["para"]["sentences"]] for it in out["stocks"]]


def test_tidy_takes_the_not_found_sentences_out_when_no_stock_has_a_reason(close_pack):
    out = two_stocks(close_pack)
    out["stocks"][0]["para"]["sentences"][0]["text"] = "台積電（2330）收 1,430.00 元，跌 4.67%，未找到報導。"
    assert validate.stocks_without_reasons(out, "close") == "stocks"
    tidied = validate.tidy(out, "close", close_pack)
    assert stock_texts(tidied) == [["台積電（2330）收 1,430.00 元，跌 4.67%。"],
                                   ["聯發科（2454）收 1,440.00 元，跌 4.00%。"]]
    assert not [x for x in validate.validate(tidied, close_pack, "close") if x.hard and x.key == "stocks"]


def test_with_one_reason_the_others_keep_their_not_found(close_pack):
    out = two_stocks(close_pack, reason_ref="X001")
    assert validate.stocks_without_reasons(out, "close") is None
    assert validate.tidy(out, "close", close_pack)["stocks"][0]["para"]["sentences"][1]["text"] == "未找到報導。"


def stocks_text_block(pay, key="stocks"):
    sec = next(x for x in pay["sections"] if x["key"] == key)
    return [[x["text"] for x in para["sentences"]] for b in sec["blocks"] if b["type"] == "text"
            for para in b["paragraphs"]]


def assemble_close(built, pk, out):
    return assemble.build(kind="close", report_id="mrp_x", edition_date=MON, period=(MON, MON), next_period=None,
                          version=1, edition="ai", pack=pk, blocks=built.blocks, output=out,
                          published_at=ts(MON, 16), first_published_at=None, as_of=ts(MON, 15, 40),
                          title_origin="ai", highlights_origin="ai")


def test_the_page_says_it_once_for_the_section(close_built, close_pack):
    pay = assemble_close(close_built, close_pack, validate.tidy(two_stocks(close_pack), "close", close_pack))
    paras = stocks_text_block(pay)
    assert paras[-1] == [prompts.STOCKS_NOT_FOUND] == ["個股的漲跌原因未找到報導。"]
    assert sum("未找到報導" in t for para in paras for t in para) == 1
    # an output that was never tidied says it once too
    raw = assemble_close(close_built, close_pack, two_stocks(close_pack))
    assert stocks_text_block(raw) == paras
    # the public form: no refs, no id
    assert not assemble.has_id_strings(pay)


def test_with_a_reason_there_is_no_section_sentence(close_built, close_pack):
    pay = assemble_close(close_built, close_pack, validate.tidy(two_stocks(close_pack, "X001"), "close", close_pack))
    assert prompts.STOCKS_NOT_FOUND not in [t for para in stocks_text_block(pay) for t in para]


def test_the_writer_is_told_to_leave_it_to_the_page(close_pack):
    assert prompts.STOCKS_NOT_FOUND in prompts.WRITER_SYSTEM and prompts.STOCKS_NOT_FOUND in prompts.SPEC["close"][
        "sections"]
    no_web = prompts.kind_instructions("close", dict(close_pack, web=[]))
    assert "也不寫「未找到報導」" in no_web and "個股項目的原因寫「未找到報導」" not in no_web


# -- 3. no private life ---------------------------------------------------------------------------------------------
HUANG_X = {**INST_X, "id": "X002", "topic": "TONIGHT", "key": "EVENT.nvda", "subject": None,
           "claim": "〔中央社〕報導，黃仁勳在傳出婚外情報導後辭去輝達執行長職務。", "numbers": [],
           "quote": "黃仁勳在傳出婚外情報導後辭去輝達執行長職務"}


@pytest.mark.parametrize("text,bad", [
    ("〔中央社〕報導，黃仁勳在傳出婚外情報導後辭去輝達執行長職務。", True),
    ("〔中央社〕報導，黃仁勳因健康因素辭去輝達執行長職務。", True),
    ("〔中央社〕報導，黃仁勳的妻子出面說明。", True),
    ("〔中央社〕報導，黃仁勳辭去輝達執行長職務。", False),
    ("〔中央社〕報導，藥華藥的癌症新藥取得藥證。", False),  # a company's business, not someone's health
])
def test_private_life_is_a_hard_problem(close_pack, text, bad):
    pk = with_web(close_pack, copy.deepcopy(INST_X), copy.deepcopy(HUANG_X))
    out = close_output(pk)
    out["what_happened"].append(p(s(text, "X002")))
    found = [x for x in validate.validate(out, pk, "close") if x.code == "private_life"]
    assert bool(found) is bad
    if bad:
        assert found[0].hard and found[0].path == "what_happened[2].sentences[0]"
        # only that sentence goes
        d = validate.drop(out, found, "close", pk)
        assert len(d.output["what_happened"]) == 2 and not d.sections


def test_a_title_with_private_life_is_replaced(close_pack):
    pk = with_web(close_pack, copy.deepcopy(INST_X), copy.deepcopy(HUANG_X))
    out = close_output(pk)
    out["title"] = "黃仁勳傳婚外情後請辭，加權指數跌 6.03%"
    assert ("title", "private_life") in [(x.path, x.code) for x in validate.validate(out, pk, "close") if x.hard]


def test_the_writer_and_the_compliance_read_know_the_rule(close_pack):
    assert "私生活" in prompts.WRITER_SYSTEM and "辭去輝達執行長" in prompts.WRITER_SYSTEM
    assert "private_life" in prompts.CHECK_CATEGORIES and "private_life" in prompts.CHECK_SYSTEM
    assert "private_life" in prompts.check_schema()["properties"]["issues"]["items"]["properties"]["category"]["enum"]
    assert "辭去執行長" in prompts.revise_message([{"path": "title", "code": "compliance:private_life", "detail": ""}])
    assert "辭去執行長" in prompts.revise_message([{"path": "title", "code": "private_life", "detail": ""}])


def test_the_compliance_read_reports_private_life(close_pack):
    compliance.reset_state()
    calls.reset_state()
    out = close_output(close_pack)
    out["what_happened"].append(p(s("〔中央社〕報導，黃仁勳在傳出婚外情報導後辭去輝達執行長職務。", "X001")))
    fake = FakeAnthropic().reply(json_text({"issues": [
        {"path": "what_happened[2].sentences[0]", "category": "private_life", "quote": "傳出婚外情報導後"}]}))
    client = fake.client("sk-test")
    res = compliance.check(out, "close", "claude-haiku-5-5", "low", lambda kw, attempt: calls.create(client, kw),
                           Settings())
    assert res.ok and res.issues == [{"path": "what_happened[2].sentences[0]", "category": "private_life",
                                      "quote": "傳出婚外情報導後"}]
    sent = fake.requests[0]["body"]
    assert "private_life" in sent["system"]
    assert "private_life" in sent["output_config"]["format"]["schema"]["properties"]["issues"]["items"][
        "properties"]["category"]["enum"]


# -- 4. N3: the weekly's repeats, risks and chips ---------------------------------------------------------------------
SUN = date(2026, 11, 22)
NVDA_X = {**INST_X, "id": "X001", "topic": "THEMES", "key": "THEME.nvda", "subject": None,
          "claim": "〔CNBC〕報導，輝達財報排定在美股 11/25 收盤後公布。", "outlet": "CNBC", "numbers": [],
          "published_at": "2026-11-21T09:00:00+08:00", "quote": "Nvidia reports after the bell on Nov. 25"}
CPI_X = {**INST_X, "id": "X002", "topic": "RISKS", "key": "RISK.cpi", "subject": None,
         "claim": "〔自由時報〕報導，美國 10 月 CPI 月增 0.4%，高於預期的 0.3%。", "outlet": "自由時報",
         "numbers": ["0.4", "0.3"], "published_at": "2026-11-19T21:00:00+08:00",
         "quote": "美國 10 月 CPI 月增 0.4%，高於預期的 0.3%"}
FED_X = {**INST_X, "id": "X003", "topic": "RISKS", "key": "RISK.fed", "subject": None,
         "claim": "〔中央社〕報導，聯準會官員表示 12 月是否降息仍待數據決定。", "numbers": [],
         "published_at": "2026-11-20T21:00:00+08:00", "quote": "聯準會官員表示 12 月是否降息仍待數據決定"}
FAA_X = {**INST_X, "id": "X004", "topic": "RISKS", "key": "RISK.faa", "subject": None, "outlet": "鉅亨網",
         "claim": "〔鉅亨網〕報導，美國聯邦航空總署發布全國性地面停飛令，要求尚未起飛的航班留在機場。", "numbers": [],
         "published_at": "2026-11-20T08:00:00+08:00", "quote": "美國聯邦航空總署發布全國性地面停飛令"}


@pytest.fixture()
def weekly_pack(market_db, us_on):
    pk = pack.build(market_db, "weekly", SUN, cutoff=ts(SUN, 16, 30), now=ts(SUN, 17)).pack
    pk = with_web(pk, *(copy.deepcopy(x) for x in (NVDA_X, CPI_X, FED_X, FAA_X)))
    pk["calendar"].append({"id": "C099", "date": "2026-11-26", "time_taipei": "21:30", "title": "美國 10 月 PCE 公布",
                           "kind": "macro", "symbol": None, "sectors": [], "source": "manual-calendar",
                           "url": "https://www.bea.gov/", "fold": None, "note": None})
    return pk


def weekly_output(pk):
    wk = fid(pk, "week_pct", "加權指數", "week")
    return {
        "title": "加權指數週跌 6.03%，輝達財報排定 11/25 公布",
        "summary": p(s("加權指數週跌 6.03%。", wk), s("〔CNBC〕報導市場關注輝達財報。", "X001")),
        "highlights": [p(s("加權指數週跌 6.03%。", wk)), p(s("已排定：輝達財報在美股 11/25 收盤後公布。", "X001")),
                       p(s("〔中央社〕報導市場關注聯準會 12 月的利率決定。", "X003"))],
        "market_week": [p(s("加權指數週跌 6.03%。", wk))],
        "sectors_week": [], "stocks_week": [],
        "chips_week": [p(s("外資台指期淨未平倉週變化 ▼6,787 口。",
                           fid(pk, "futures_oi_change", "外資台指期", "week")))],
        "global_week": [p(s("美元兌新台幣週變化 ▲0.048。", fid(pk, "fx_change", "美元兌新台幣", "week")))],
        "last_week_review": [],
        "themes": [
            {"theme": "輝達財報", "why": p(s("〔CNBC〕報導市場關注輝達財報。", "X001")),
             "events": p(s("已排定：輝達財報在美股 11/25 收盤後公布。", "X001")), "sectors": ["半導體"],
             "relation": p()},
            {"theme": "美國通膨", "why": p(s("〔中央社〕報導市場關注聯準會 12 月的利率決定。", "X003")),
             "events": p(s("已排定：美國 10 月 PCE 在 11/26（四）21:30 公布。", "C099")), "sectors": [],
             "relation": p()},
        ],
        "risks": [p(s("〔中央社〕報導市場關注聯準會 12 月的利率決定。", "X003")),
                  p(s("已排定：美國 10 月 PCE 在 11/26（四）21:30 公布。", "C099"))],
        "chart_of_day": {"code": "none", "period": "none", "set": "none", "caption": p()},
    }


def weekly_problems(out, pk, code):
    return [x.path for x in validate.validate(out, pk, "weekly") if x.code == code and x.hard]


def test_the_weekly_output_without_repeats_passes_these_checks(weekly_pack):
    out = weekly_output(weekly_pack)
    for code in ("repeated_fact", "risk_not_ahead", "chips_off_topic"):
        assert weekly_problems(out, weekly_pack, code) == []


def test_a_fact_repeated_in_one_section_is_a_problem_after_its_first_use(weekly_pack):
    out = weekly_output(weekly_pack)
    # the dry run: 「已排定：輝達財報…」 in the highlights, this week and three themes
    out["themes"][1]["events"] = p(s("已排定：輝達財報在美股 11/25 收盤後公布。", "X001"))
    out["highlights"].append(p(s("已排定：輝達財報在美股 11/25 收盤後公布。", "X001")))
    out["summary"]["sentences"].append(s("已排定：輝達財報在美股 11/25 收盤後公布。", "X001"))
    found = weekly_problems(out, weekly_pack, "repeated_fact")
    assert found == ["highlights[3].sentences[0]", "summary.sentences[2]", "themes[1].events.sentences[0]"]
    # once per section is fine: X001 is in the summary, the highlights and the first theme once each
    d = validate.drop(out, [x for x in validate.validate(out, weekly_pack, "weekly") if x.code == "repeated_fact"],
                      "weekly", weekly_pack)
    assert len(d.output["themes"]) == 2 and d.output["themes"][1]["events"]["sentences"] == []
    assert len(d.output["highlights"]) == 3 and len(d.output["summary"]["sentences"]) == 2


@pytest.mark.parametrize("ref,text", [
    ("X002", "〔自由時報〕報導市場關注美國 10 月 CPI 月增 0.4%，高於預期的 0.3%。"),  # already published
    ("X004", "〔鉅亨網〕報導市場關注美國聯邦航空總署的全國性地面停飛令。"),  # already ordered
])
def test_a_risk_that_already_happened_goes_alone(weekly_pack, ref, text):
    out = weekly_output(weekly_pack)
    out["risks"].append(p(s(text, ref)))
    assert weekly_problems(out, weekly_pack, "risk_not_ahead") == ["risks[2]"]
    d = validate.drop(out, [x for x in validate.validate(out, weekly_pack, "weekly") if x.hard], "weekly",
                      weekly_pack)
    assert len(d.output["risks"]) == 2 and "risks" not in d.sections and d.items_dropped["risks"] == [2]


def test_a_risk_with_a_calendar_row_of_the_reviewed_week_is_not_ahead(weekly_pack):
    out = weekly_output(weekly_pack)
    settle = next(c["id"] for c in weekly_pack["calendar"] if c["kind"] == "settlement")  # 11/18, in the week
    out["risks"][1] = p(s("已排定：台指期貨、台指選擇權 11 月契約在 11/18（三）最後結算。", settle))
    assert weekly_problems(out, weekly_pack, "risk_not_ahead") == ["risks[1]"]


@pytest.mark.parametrize("text,ref", [
    ("美元兌新台幣週變化 ▲0.048。", ("fx_change", "美元兌新台幣")),
    ("台指選擇權 P/C 未平倉比 53.79%。", ("pc_ratio_oi", "P/C 比")),
    ("已排定：台指期貨、台指選擇權 11 月契約在 11/18（三）最後結算。", None),
])
def test_the_chips_hold_institutional_investors_and_fund_flows_only(weekly_pack, text, ref):
    out = weekly_output(weekly_pack)
    rid = fid(weekly_pack, ref[0], ref[1], "week") if ref else next(
        c["id"] for c in weekly_pack["calendar"] if c["kind"] == "settlement")
    out["chips_week"].append(p(s(text, rid)))
    assert weekly_problems(out, weekly_pack, "chips_off_topic") == ["chips_week[1].sentences[0]"]


def test_the_futures_positions_of_foreign_investors_stay_in_the_chips(weekly_pack):
    out = weekly_output(weekly_pack)
    out["chips_week"][0] = p(s("外資台指期淨未平倉比前一週減少 6,787 口。",
                               fid(weekly_pack, "futures_oi_change", "外資台指期", "week")))
    assert weekly_problems(out, weekly_pack, "chips_off_topic") == []


def test_the_close_chips_too(close_pack):
    out = close_output(close_pack)
    out["chips"].append(p(s("〔中央社〕報導，新台幣兌美元匯率貶值。", "X001")))
    assert ("chips[1].sentences[0]", "chips_off_topic") in [
        (x.path, x.code) for x in validate.validate(out, close_pack, "close") if x.hard]


def test_the_weekly_spec_moves_the_exchange_rate_and_keeps_risks_ahead():
    weekly = prompts.SPEC["weekly"]["sections"]
    chips = next(line for line in weekly.splitlines() if line.startswith("- chips_week"))
    assert "不寫匯率" in chips and "P/C 比、上櫃" not in chips
    assert "美元兌新台幣" in next(line for line in weekly.splitlines() if line.startswith("- global_week"))
    assert "還沒發生或還沒有結果" in weekly and "不同主題不要用同一個 C 或 X" in weekly
    assert "每一段最多用一次" in prompts.WRITER_SYSTEM
    for code in ("repeated_fact", "risk_not_ahead", "chips_off_topic"):
        assert code in prompts.REVISE_HINTS
    assert "還沒發生或還沒有結果" in prompts.TOPICS["weekly"]["RISKS"][1]


# -- 5. N4: the house format of numbers and headlines ---------------------------------------------------------------
@pytest.mark.parametrize("raw,house", [
    ("加權指數收在 43675.12 點，較上週上漲 3973.48 點。", "加權指數收在 43,675.12 點，較上週上漲 3,973.48 點。"),
    ("今年以來日均成交金額為 9997.16 億元。", "今年以來日均成交金額為 9,997.16 億元。"),
    ("外資賣超 1234 張，成交 1,354.7 億元。", "外資賣超 1,234 張，成交 1,354.7 億元。"),
    ("台積電（2330）收 1430 元。", "台積電（2330）收 1,430 元。"),
    ("2026 年 11/17 13:30 羅素 2000 跌 1.2%，S&P 500 ETF 漲 0.5%。",
     "2026 年 11/17 13:30 羅素 2000 跌 1.2%，S&P 500 ETF 漲 0.5%。"),
    ("元大台灣50（0050）收 57 元；2330 股價。", "元大台灣50（0050）收 57 元；2330 股價。"),
])
def test_numbers_copied_from_a_report_take_thousands_separators(raw, house):
    assert validate.house_numbers(raw, ["2330"]) == house


def test_tidy_writes_the_house_format(close_pack):
    out = close_output(close_pack)
    out["title"] = "加權指數收41040.08點 外資賣超1234.5億元"
    out["chips"][0]["sentences"][0]["text"] = "〔中央社〕報導，外資賣超 1234.5 億元。"
    tidied = validate.tidy(out, "close", close_pack)
    assert tidied["title"] == "加權指數收41,040.08點，外資賣超1,234.5億元"
    assert tidied["chips"][0]["sentences"][0]["text"] == "〔中央社〕報導，外資賣超 1,234.5 億元。"
    # the numbers still match their sources
    assert not [x for x in validate.validate(tidied, close_pack, "close")
                if x.hard and x.code in ("number_unsourced", "unit_mismatch")]


def test_headline_clauses_are_separated_with_a_comma():
    assert validate.headline_clauses("加權指數週漲3,973.48點 黃仁勳請辭輝達執行長") == \
        "加權指數週漲3,973.48點，黃仁勳請辭輝達執行長"
    assert validate.headline_clauses("外資賣超　台積電跌 4.67%") == "外資賣超，台積電跌 4.67%"
    # a space next to a number, a code or a Latin name stays
    for kept in ("加權指數 ▼6.03%，收 41,040.08 點", "台積電 ADR 美股 11/16 跌 1.00%", "SMH 美股 11/16 跌 2.58%"):
        assert validate.headline_clauses(kept) == kept
    assert "子句之間用全形逗號「，」分開" in prompts.WRITER_SYSTEM and "千分位" in prompts.WRITER_SYSTEM


# -- 6. N6: the premarket's data headline ---------------------------------------------------------------------------
def test_the_premarket_data_headline_never_names_an_empty_calendar(market_db, us_on):
    pk = pack.build(market_db, "premarket", TUE, cutoff=ts(TUE, 6, 55), now=ts(TUE, 7)).pack
    assert assemble.data_title("premarket", pk) == "盤前重點 11/17（二）：美股 11/16 收盤與今日行事曆"
    empty = dict(pk, calendar=[])
    assert assemble.data_title("premarket", empty) == "盤前重點 11/17（二）：美股 11/16 收盤"
    no_us = dict(empty, dates={**pk["dates"], "us_sessions": []})
    # the dry run's case: v2's 「昨日台股全貌」 is there whenever the previous session is
    assert assemble.data_title("premarket", no_us) == "盤前重點 11/17（二）：昨日台股全貌"
    evening_only = dict(no_us, facts=[f for f in pk["facts"] if f.get("group") != "prev_session"])
    assert assemble.data_title("premarket", evening_only) == "盤前重點 11/17（二）：昨日籌碼"
    nothing = dict(no_us, facts=[f for f in pk["facts"] if f.get("group") != "evening"])
    assert "行事曆" not in assemble.data_title("premarket", nothing)
    calendar_only = dict(no_us, calendar=pk["calendar"])
    assert assemble.data_title("premarket", calendar_only) == "盤前重點 11/17（二）：今日行事曆"


def test_window_dates_are_taipei(close_pack):
    w = close_window(close_pack)
    assert w.cutoff == datetime(2026, 11, 16, 15, 40, tzinfo=TAIPEI)


# -- review of these fixes (2026-11-17) -------------------------------------------------------------------------------
# 1. Option A: a number after a sector or a stock off the list is never charged to the listed stock before it
@pytest.mark.parametrize("cited", [
    "加權指數收跌2635點，台積電收跌70元，金融股收漲0.5%。",
    "台積電收跌70元，半導體類股收跌3%，賣壓集中在權值股。",
    "台股今天重挫，台積電收跌70元，聯電收跌3元，廣達收跌10元，電子股全面走弱。",
    "台積電收跌70元 聯電收跌3元 電子股全面走弱",  # a headline's clauses separated by a space
    "台積電收跌70元，櫃買指數與聯電收跌3元。",  # the closest name (櫃買指數) has no 元: the number is not judged
    "台積電帶動半導體類股收跌3%，台積電收1,430元。",  # a sector word in the same clause stops the search
])
def test_a_sector_or_a_stock_off_the_list_does_not_contradict_a_listed_stock(close_pack, cited):
    fact, why = check(close_window(close_pack), cited)
    assert why is None and fact["dated_by"] == "matched_close_numbers"


def test_a_number_of_another_clause_is_not_charged_to_a_listed_stock(close_pack):
    data = close_window(close_pack).close
    assert gather.close_numbers(["台積電收跌70元，半導體類股收跌3%。"], data) == \
        ("matched_close_numbers", "台積電 70元")
    # 聯電's 4% is not 台積電's; 台積電's own 1% (▼4.67%) contradicts the close
    assert gather.close_numbers(["台積電上漲1%，聯電下跌4%。"], data) == ("contradicts_close", "台積電 1%")
    assert gather.close_numbers(["台積電收跌70元，聯電下跌4%。"], data) == ("matched_close_numbers", "台積電 70元")
    # names and numbers listed together are not judged one by one (聯發科 ▼60 元)
    assert gather.close_numbers(["台積電、聯發科分別收跌70元、60元。"], data) == (None, "")
    assert gather.close_numbers(["台積電與聯發科下跌70元與60元。"], data) == (None, "")
    assert gather.close_numbers(["台積電拖累加權指數收跌2,635點。"], data)[0] == "matched_close_numbers"
    # another figure is not judged; a comparison with the session before is the day's change
    assert gather.close_numbers(["台積電10月營收年增20%，第3季獲利大漲40%。"], data) == (None, "")
    assert gather.close_numbers(["台積電前一交易日收1,500元。"], data) == (None, "")
    assert gather.close_numbers(["台積電較前一交易日下跌70元。"], data)[0] == "matched_close_numbers"


# 2. cutting decimals off is for index points only; every judged number has to match
def test_cutting_off_decimals_is_for_index_points_only():
    data = gather.CloseData({"加權指數": "加權指數", "指數": "加權指數", "台積電": "台積電"},
                            {"加權指數": {"點": [(-947.97, True)]},
                             "台積電": {"%": [(-4.67, True)], "元": [(2170.0, False), (-45.0, True)]}})
    assert gather.close_numbers(["國安基金護盤失敗，指數收跌947點。"], data)[0] == "matched_close_numbers"
    assert gather.close_numbers(["台積電下跌4%。"], data) == ("contradicts_close", "台積電 4%")
    assert gather.close_numbers(["台積電下跌4.6%。"], data)[0] == "contradicts_close"
    assert gather.close_numbers(["台積電下跌5%，收2,170元。"], data)[0] == "matched_close_numbers"  # rounded


@pytest.mark.parametrize("cited", [
    "台股今天重挫，台積電下跌4%，拖累加權指數下跌1,200點，電子股全面走弱，賣壓沉重。",  # a story of the session
    "台積電下跌70元，加權指數下跌1,200點。",  # one number that does not match is enough, without 「收」
    "台股今天賣壓沉重，權值股全面走弱，台積電下跌4%。",
])
def test_a_judged_number_that_does_not_match_keeps_the_page_out(close_pack, cited):
    assert check(close_window(close_pack), cited) == (None, "contradicts_close")


# 3. Option A is for a search after the session closed — the scheduled one or a rebuild (a gathering that started
# late, ``run`` by hand: the third dry run rebuilt 11/17 after midnight); a page that writes its publish time is dated
# by it
@pytest.mark.parametrize("at", [ts(MON, 15, 50), ts(MON, 16, 5), ts(MON, 21, 0), ts(TUE, 0, 15)])
def test_option_a_holds_for_a_search_after_the_close_a_rebuild_too(close_pack, at):
    cited = "台積電下跌70元，加權指數收跌2635點。"
    fact, why = check(close_window(close_pack, at), cited, page_age="2026-11-16")
    assert why is None and fact["dated_by"] == "matched_close_numbers" and fact["published_at"] == "2026-11-16"


def test_a_rebuild_still_dates_a_page_by_the_publish_time_it_writes(close_pack):
    cited = "2026-11-16 18:05 經濟日報／記者王小明／台北即時報導 台積電下跌70元，加權指數收跌2635點。"
    assert check(close_window(close_pack, ts(MON, 21, 0)), cited, page_age="2026-11-16") == (None, "no_publish_time")
    # its numbers contradicting the close keep it out in a rebuild as well
    wrong = "台積電下跌45元，加權指數收跌947點。"
    assert check(close_window(close_pack, ts(TUE, 0, 15)), wrong, page_age="2026-11-16") == (None, "contradicts_close")


@pytest.mark.parametrize("stamp", ["2026-11-16 07:30", "2026-11-16 15:49", "2026-11-16 18:05"])
def test_a_page_that_writes_its_publish_time_outside_the_window_is_not_dated_by_its_numbers(close_pack, stamp):
    cited = f"{stamp} 經濟日報／記者王小明／台北即時報導 台積電下跌70元，加權指數收跌2635點。"
    assert check(close_window(close_pack), cited) == (None, "no_publish_time")


# 4. the house format never touches a year or a word that starts like a unit
@pytest.mark.parametrize("raw", [
    "2027元旦連假前", "2026 人形機器人展", "2026筆電出貨", "1111人力銀行", "2026.11營收", "2026家電展",
    "2026人工智慧", "2026元月", "2026元宇宙", "2026萬聖節", "2026兆豐盃", "2026張忠謀講座", "2026口罩",
])
def test_house_numbers_leaves_a_year_or_a_word_alone(raw):
    assert validate.house_numbers(raw) == raw


@pytest.mark.parametrize("raw,house", [
    ("成交 2050 億元。", "成交 2,050 億元。"),
    ("上漲 1234 家，下跌 1111 家。", "上漲 1,234 家，下跌 1,111 家。"),
    ("某類指數收 2026.11 點。", "某類指數收 2,026.11 點。"),
    ("外資賣超 12345 張", "外資賣超 12,345 張"),
    ("就醫 12345 人次", "就醫 12,345 人次"),
])
def test_house_numbers_still_formats_counts_and_amounts(raw, house):
    assert validate.house_numbers(raw) == house


def test_tidy_keeps_a_year_in_an_event_name(close_pack):
    out = close_output(close_pack)
    out["tonight"][0]["event"] = "2026人形機器人展開幕"
    out["tonight"][0]["para"]["sentences"][0]["text"] = "已排定：2026人形機器人展 11/17（二）開幕。"
    tidied = validate.tidy(out, "close", close_pack)
    assert tidied["tonight"][0]["event"] == "2026人形機器人展開幕"
    assert tidied["tonight"][0]["para"]["sentences"][0]["text"] == "已排定：2026人形機器人展 11/17（二）開幕。"


# 5. a drop that leaves no stock with a reason: the clause form is said once too
def test_after_a_drop_the_page_still_says_it_once(close_built, close_pack):
    out = two_stocks(close_pack)
    out["stocks"][0]["para"]["sentences"][1] = s("〔中央社〕報導，外資賣超 1,234.5 億元。", "X001")
    out["stocks"][1]["para"]["sentences"] = [s("聯發科（2454）收 1,440.00 元，跌 4.00%，未找到報導。",
                                               fid(close_pack, "stock_close", "聯發科", "today"),
                                               fid(close_pack, "stock_pct", "聯發科", "today"))]
    tidied = validate.tidy(out, "close", close_pack)  # one stock has a reason: the clause stays
    assert tidied["stocks"][1]["para"]["sentences"][0]["text"].endswith("，未找到報導。")
    d = validate.drop(tidied, [validate.Problem("stocks[0].para.sentences[1]", "number_unsourced")], "close",
                      close_pack)
    assert [x["text"] for x in d.output["stocks"][0]["para"]["sentences"]] == \
        ["台積電（2330）收 1,430.00 元，跌 4.67%。"]
    paras = stocks_text_block(assemble_close(close_built, close_pack, d.output))
    assert paras == [["台積電（2330）收 1,430.00 元，跌 4.67%。"], ["聯發科（2454）收 1,440.00 元，跌 4.00%。"],
                     [prompts.STOCKS_NOT_FOUND]]


# 6. the weekly's risks: what already happened by the edition (its Saturday too) is not ahead
@pytest.mark.parametrize("text,ahead", [
    ("〔鉅亨網〕報導市場關注美國聯邦航空總署在美股 11/20 收盤後（台北 11/21 清晨）發布的全國性地面停飛令。", False),
    ("〔鉅亨網〕報導市場關注美國聯邦航空總署在 11/22 發布的全國性地面停飛令。", False),  # the edition's own day
    ("〔鉅亨網〕報導市場關注美國聯邦航空總署在 11/23 是否延長全國性地面停飛令。", True),
])
def test_a_risk_dated_after_the_week_but_by_the_edition_is_not_ahead(weekly_pack, text, ahead):
    out = weekly_output(weekly_pack)
    out["risks"].append(p(s(text, "X004")))
    assert weekly_problems(out, weekly_pack, "risk_not_ahead") == ([] if ahead else ["risks[2]"])


@pytest.mark.parametrize("day,at,ahead", [("2026-11-21", "21:30", False), ("2026-11-22", "10:00", False),
                                          ("2026-11-22", "20:00", True), ("2026-11-23", "", True)])
def test_a_calendar_row_is_ahead_only_after_the_weekly_s_cutoff(weekly_pack, day, at, ahead):
    weekly_pack["calendar"].append({**weekly_pack["calendar"][-1], "id": "C098", "date": day, "time_taipei": at,
                                    "title": "美國經濟數據公布"})
    out = weekly_output(weekly_pack)
    out["risks"].append(p(s("已排定：美國經濟數據公布。", "C098")))
    assert weekly_problems(out, weekly_pack, "risk_not_ahead") == ([] if ahead else ["risks[2]"])


# 7. a company's business or the economy is not someone's private life
@pytest.mark.parametrize("text,bad", [
    ("〔中央社〕報導，康霈減重新藥收案對象為罹患肥胖症的患者。", False),
    ("〔中央社〕報導，國泰金住院醫療險理賠金額增加。", False),
    ("〔中央社〕報導，健保就醫人次創新高。", False),
    ("〔中央社〕報導，少子化與結婚率下滑。", False),
    ("〔中央社〕報導，開刀房設備需求增加。", False),
    ("〔中央社〕報導，配偶扣除額調高。", False),
    ("〔中央社〕報導，子女教育費特別扣除額調高。", False),
    ("〔中央社〕報導，公司財務健康狀況良好。", False),
    ("〔中央社〕報導，鴻海董事長住院治療。", True),
    ("〔中央社〕報導，黃仁勳宣布結婚。", True),
    ("〔中央社〕報導，黃仁勳罹患重病。", True),
    ("〔中央社〕報導，黃仁勳與配偶出席。", True),
])
def test_private_life_needs_a_person_s_private_matter(close_pack, text, bad):
    assert (validate.private_life(text) is not None) is bad
    pk = with_web(close_pack, copy.deepcopy(INST_X), copy.deepcopy(HUANG_X))
    out = close_output(pk)
    out["what_happened"].append(p(s(text, "X002")))
    assert bool([x for x in validate.validate(out, pk, "close") if x.code == "private_life"]) is bad


def test_the_compliance_read_is_told_what_is_not_private_life():
    assert "住院醫療險" in prompts.CHECK_SYSTEM and "結婚率" in prompts.CHECK_SYSTEM


# -- the third dry run (11/18 01:00 Taipei): the search engine counts "N days ago" in UTC days -----------------------
# At 17:00 UTC on 11/17 the 11/17 close stories were "0 days ago" and the 11/16 ones "1 days ago": counted back from
# the Taipei date (already 11/18), every close story came out as 11/18 and the rebuild kept nothing (outside_window).
@pytest.mark.parametrize("at", [ts(TUE, 0, 15), ts(TUE, 1, 0), ts(TUE, 7, 59)])
def test_a_rebuild_after_midnight_dates_0_days_ago_by_the_utc_day(close_pack, at):
    cited = "台積電下跌70元，加權指數收跌2635點。"
    fact, why = check(close_window(close_pack, at), cited, page_age="0 days ago")
    assert why is None and fact["published_at"] == "2026-11-16" and fact["dated_by"] == "matched_close_numbers"
    # "1 days ago" is the day before (11/15 in UTC): outside the close window
    assert check(close_window(close_pack, at), cited, page_age="1 days ago") == (None, "outside_window")


def test_the_scheduled_close_reads_relative_days_as_before(close_pack):
    # 15:45 Taipei is 07:45 UTC, the same day: "0 days ago" is the cut-off's own day
    cited = "台積電下跌70元，加權指數收跌2635點。"
    fact, why = check(close_window(close_pack), cited, page_age="0 days ago")
    assert why is None and fact["published_at"] == "2026-11-16"
    # from 08:00 Taipei the UTC day is the Taipei day again: a page of 11/17 is no longer the close of 11/16
    assert check(close_window(close_pack, ts(TUE, 8, 0)), cited, page_age="0 days ago") == (None, "outside_window")
    # "3 hours ago" keeps its time
    fact, why = check(close_window(close_pack), cited, page_age="3 hours ago")
    assert why is None and fact["published_at"] == "2026-11-16T12:45:00+08:00" and "dated_by" not in fact


# The disagreement compared each claim's first number: 「台股今（17）日…成交量9,618億元」 (17) against 「台股今上下振盪
# 1747.39點…成交值9617.95億元」 (1747.39), and the page would have said 「鉅亨網寫 1747.39 億元，經濟日報寫 17 億元」.
UDN_TURNOVER = "〔聯合新聞網〕報導，台股今（17）日收盤下跌947.97點、跌幅2.31%，終場以40,092.11點作收，成交量9,618億元。"
CNYES_TURNOVER = ("〔鉅亨網〕報導，台股今上下振盪1747.39點，終場守住4萬點，收40092.11點、跌947.97點，"
                  "成交值9617.95億元，台積電收2170元跌45元。")


def turnover_fact(outlet, claim, key="TW.turnover_media"):
    nums = validate.numbers(claim, gather.INDEX_NAMES_WITH_DIGITS)
    return {"key": key, "outlet": outlet, "claim": claim, "numbers": [gather._num_raw(claim, n) for n in nums],
            "main": gather._main_raw(key, claim, nums)}


def test_a_disagreement_compares_the_amounts_not_the_first_numbers():
    udn, cnyes = turnover_fact("經濟日報", UDN_TURNOVER), turnover_fact("鉅亨網", CNYES_TURNOVER)
    assert (udn["main"], cnyes["main"]) == ("9618", "9617.95")
    kept, disagree = gather.disagreements([udn, cnyes])
    assert disagree == [] and len(kept) == 2  # 9,617.95 rounds to 9,618: the same turnover
    other = turnover_fact("鉅亨網", CNYES_TURNOVER.replace("9617.95", "9517.95"))
    kept, [d] = gather.disagreements([udn, other])
    assert d["text"] == "鉅亨網寫 9517.95 億元，經濟日報寫 9618 億元；本報告以經濟日報為準。"


def test_a_fact_without_an_amount_is_compared_with_nothing():
    # 「台股今（17）日收盤下跌947.97點」: no amount in 億元 (nor a percentage for the ADR)
    no_amount = turnover_fact("經濟日報", "〔聯合新聞網〕報導，台股今（17）日收盤下跌947.97點。")
    assert no_amount["main"] is None
    kept, disagree = gather.disagreements([no_amount, turnover_fact("鉅亨網", CNYES_TURNOVER)])
    assert disagree == [] and len(kept) == 2
    adr = turnover_fact("中央社", "〔中央社〕報導，美股 11/16 台積電 ADR 收 301.2 美元、跌 6.34%。", key="ADR.tsm")
    assert adr["main"] == "6.34"


@pytest.mark.parametrize("a,b,same", [("9618", "9617.95", True), ("9618", "9618.6", False),
                                      ("179.62", "179.63", False), ("380.9", "380.94", True), ("547", "547.25", True)])
def test_numbers_agree_within_rounding(a, b, same):
    assert gather._agree(a, b) is same and gather._agree(b, a) is same
