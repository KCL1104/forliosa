"""Review fixes of the checks (2026-11-17): units next to numbers, index points of any size and distance, the AI's
headings checked like the title, the only approved 「〔媒體〕報導市場關注…」 shape without a direction, more time words,
two-character names off the list; the gathering's freshness per citation and for pages dated by day, percentages only
for US / night / ADR facts, no one's forecast; the shared research one source per W; the turnover list's scope; a
data edition's full disclaimer; the NYSE table's host check."""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from forliosa.ai.analyst import SearchResult
from forliosa.ai.market_summary import _norm_url
from forliosa.models import AiWhyResearch
from forliosa.reports import assemble, gather, pack, service, validate
from forliosa.reports import marketcalc as mc
from tests.reports.conftest import MON, TUE, ts
from tests.reports.helpers import close_output, fid, p, premarket_output, s, with_web


@pytest.fixture()
def close_pack(market_db, us_on):
    return with_web(pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16)).pack)


@pytest.fixture()
def pre_pack(market_db, us_on):
    return pack.build(market_db, "premarket", TUE, cutoff=ts(TUE, 6, 55), now=ts(TUE, 7)).pack


def codes(out, pk, kind="close", names=()):
    return {x.code for x in validate.validate(out, pk, kind, names) if x.hard}


def with_sentence(out, key, text, *refs, idx=0):
    o = copy.deepcopy(out)
    o[key][idx] = p(s(text, *refs))
    return o


# -- units ---------------------------------------------------------------------------------------------------------
def test_a_percentage_written_as_dollars_or_points_is_caught(close_pack):
    out = close_output(close_pack)
    stock_pct = fid(close_pack, "stock_pct", "台積電", "today")
    index_pct = fid(close_pack, "index_pct", group="today")
    index_change = fid(close_pack, "index_change", group="today")
    assert "unit_mismatch" in codes(with_sentence(out, "what_happened", "台積電（2330）下跌 4.67 元。", stock_pct),
                                    close_pack)
    assert "unit_mismatch" in codes(with_sentence(out, "what_happened", "加權指數下跌 6.03 點。", index_pct),
                                    close_pack)
    assert "unit_mismatch" in codes(with_sentence(out, "what_happened", "加權指數下跌 2,635.04%。", index_change),
                                    close_pack)
    assert codes(with_sentence(out, "what_happened", "加權指數下跌 6.03%。", index_pct), close_pack) == set()
    assert validate.unit_ok("元", "億元") and validate.unit_ok("", "%") and validate.unit_ok("檔", "家")
    assert not validate.unit_ok("點", "%")


# -- index points --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "美股道瓊工業指數 11/16 下跌 456 點", "台指期夜盤 11/16 下跌 85 點", "費半指數跌 123.45 點",
    "道瓊工業指數 11/16 收 44,123.45 點", "〔中央社〕報導，美股 11/16 道瓊工業平均指數終場下跌 456.78 點。",
    "納斯達克指數下跌 1,234.5 點", "那指下跌 1,234 點", "標準普爾 500 指數收 6,812 點", "費半下跌 98.5 點",
    "道瓊跌 1.2%，跌 456 點",
])
def test_index_points_of_any_size_and_distance(text):
    assert validate.index_points(text) is not None


@pytest.mark.parametrize("text", [
    "加權指數收 41,040.08 點，台指期夜盤跌 0.3%。", "台指期夜盤跌 0.3%，加權指數收 41,040.08 點。",
    "費半跌 2%，台積電（2330）點數貢獻約 −1,616 點（估算）。", "櫃買指數 11/16 收 319.12 點。",
    "美股 11/13 標普 500 漲 0.4%。",
])
def test_taiwan_points_are_not_index_points(text):
    assert validate.index_points(text) is None


def test_night_and_us_facts_take_percentages_only():
    w = gather.Window(ts(MON, 13, 30), ts(TUE, 7), ts(TUE, 6, 55), {MON}, ts(TUE, 6, 56))  # covers 美股 11/16
    url = "https://news.cnyes.com/news/id/6000001"
    res = {_norm_url(url): SearchResult(url, "夜盤收低", "2026-11-16T23:30:00+08:00")}
    cite = [{"type": "web_search_result_location", "url": url, "title": "夜盤收低",
             "cited_text": "台指期夜盤 11/16 下跌 85 點，跌幅 0.3%，成交量放大，市場關注美股走勢與科技股。"}]
    claim = "〔鉅亨〕報導，美股 11/16 台指期夜盤下跌 85 點，跌幅 0.3%。"
    fact, why = gather.verify("NIGHT.tx_pct", claim, cite, res, w, ("NIGHT.tx_pct",))
    assert fact is None and why == "index_points"
    fact, why = gather.verify("NIGHT.tx_pct", "〔鉅亨〕報導，美股 11/16 台指期夜盤跌幅 0.3%。", cite, res, w,
                              ("NIGHT.tx_pct",))
    assert why is None and fact["numbers"] == ["0.3"]


# -- the AI's headings ---------------------------------------------------------------------------------------------
def test_item_names_are_checked_like_the_title(pre_pack, close_pack):
    out = premarket_output(pre_pack)
    out["watch"][0]["event"] = "台積電目標價上看 2,000 元，明天看好"
    found = {(x.path, x.code) for x in validate.validate(out, pre_pack, "premarket") if x.hard}
    assert {("watch[0].event", "forbidden_word"), ("watch[0].event", "number_unsourced")} <= found
    d = validate.drop(out, [x for x in validate.validate(out, pre_pack, "premarket") if x.hard], "premarket")
    assert "watch" in d.sections
    out = close_output(close_pack)
    out["tonight"][0]["event"] = "Claude 道瓊 45,000 點"
    assert "index_points" in codes(out, close_pack) and validate.mentions_anthropic(out, "close")
    assert codes(premarket_output(pre_pack), pre_pack, "premarket") == set()  # the clean ones still pass


@pytest.mark.parametrize("title,code", [
    ("加權指數漲 6.03%，收 41,040.08 點", "direction_mismatch"),
    ("加權指數 ▲6.03%，收 41,040.08 點創新高", "direction_mismatch"),
    ("台積電重挫 6.03%，權值股全面走低收盤", "number_subject_mismatch"),
    ("電腦及週邊設備類股領漲，聯發科走強", "sector_not_allowed"),
    ("玻璃陶瓷類股大跌，加權指數收 41,040.08 點", "sector_not_allowed"),
    ("加權指數將續跌，收 41,040.08 點跌 6.03%", "outlook_pattern"),
    ("加權指數下跌 6.03 點，收 41,040.08 點", "unit_mismatch"),
    ("外資賣超拖累加權指數跌 6.03%", "cause_without_source"),
])
def test_the_title_gets_the_sentence_checks(close_pack, title, code):
    out = close_output(close_pack)
    out["title"] = title
    probs = [x for x in validate.validate(out, close_pack, "close") if x.hard and x.path == "title"]
    assert code in {x.code for x in probs}
    assert validate.drop(out, probs, "close").title_bad


def test_the_title_names_only_listed_stocks(close_pack):
    out = close_output(close_pack)
    out["title"] = "國泰金跌 6.03%，加權指數收 41,040.08 點"
    assert "stock_not_allowed" in codes(out, close_pack, names=["國泰金", "台積電"])


# -- forward-looking sentences -------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "〔中央社〕報導，法人預估台股短線可能震盪走高。", "〔中央社〕報導，法人預期台股短線將震盪走高。",
    "〔中央社〕指出，台股將受惠。", "〔中央社〕報導市場關注台股短線可能震盪走高。"])
def test_someone_else_s_forecast_is_not_an_approved_shape(close_pack, text):
    out = close_output(close_pack)
    out["tonight"][0]["para"] = p(s(text, "X001"))
    assert "outlook_pattern" in codes(out, close_pack)


def test_the_approved_shape_still_passes(close_pack):
    out = close_output(close_pack)
    out["tonight"][0]["para"] = p(s("〔中央社〕報導市場關注外資賣超 1,234.5 億元後的動向。", "X001"))
    assert "outlook_pattern" not in codes(out, close_pack)


@pytest.mark.parametrize("word", ["昨晚", "隔日", "次日", "下個交易日", "隔天", "明晚", "今晨", "昨夜", "翌日"])
def test_more_time_words(close_pack, word):
    close = fid(close_pack, "index_close", group="today")
    out = with_sentence(close_output(close_pack), "what_happened", f"加權指數{word}收 41,040.08 點。", close)
    assert "forbidden_word" in codes(out, close_pack)
    out = close_output(close_pack)
    out["title"] = f"加權指數{word}收 41,040.08 點，跌 6.03%"
    assert "forbidden_word" in codes(out, close_pack)


@pytest.mark.parametrize("word", ["評等", "評級", "佈局"])
def test_ratings_and_the_variant_of_buju_are_forbidden(close_pack, word):
    pct = fid(close_pack, "index_pct", group="today")
    out = with_sentence(close_output(close_pack), "what_happened", f"加權指數跌 6.03%，{word}。", pct)
    assert "forbidden_word" in codes(out, close_pack)


# -- two-character names -------------------------------------------------------------------------------------------
def test_two_character_names_off_the_list(close_pack):
    out = close_output(close_pack)
    bad = with_sentence(out, "chips", "〔中央社〕報導，鴻海與聯電帶動大盤。", "X001")
    assert "stock_not_allowed" in codes(bad, close_pack, names=["鴻海", "聯電", "聯發科"])
    bad = with_sentence(out, "chips", "〔中央社〕報導，廣達與緯創帶動電腦及週邊設備類股。", "X001")
    assert {"stock_not_allowed", "sector_not_allowed"} <= codes(bad, close_pack, names=["廣達", "緯創"])
    # a listed one, or a plain word, is fine
    ok = with_sentence(out, "chips", "〔中央社〕報導，外資賣超 1,234.5 億元，統一意見不多。", "X001")
    assert "stock_not_allowed" not in codes(ok, close_pack, names=["統一", "鴻海", "全新"])


# -- the gathering: freshness ----------------------------------------------------------------------------------------
W = gather.Window(ts(MON, 8), ts(MON, 15, 50), ts(MON, 15, 40), set(), ts(MON, 15, 45))
CITED = "外資今天賣超 1,234.5 億元，投信賣超 179.63 億元，自營商賣超 50 億元，三大法人合計賣超。"


def _verify(url, page_age, cited=CITED, claim="〔經濟日報〕報導，外資賣超 1,234.5 億元。", w=W):
    res = {_norm_url(url): SearchResult(url, "外資賣超千億", page_age)}
    cites = [{"type": "web_search_result_location", "url": url, "title": "外資賣超千億", "cited_text": cited}]
    return gather.verify("TWSE_INST.foreign", claim, cites, res, w, ("TWSE_INST.",))


@pytest.mark.parametrize("url,page_age", [
    ("https://money.udn.com/money/story/5607/8000001", "October 2, 2026"),
    ("https://money.udn.com/money/story/5607/8000001", "2024-11-15"),
    ("https://money.udn.com/money/story/5607/8000001", "45 days ago"),
    ("https://www.cna.com.tw/news/afe/202411150012.aspx", None),
])
def test_a_page_dated_by_day_must_be_inside_the_window(url, page_age):
    assert _verify(url, page_age) == (None, "outside_window")


def test_a_premarket_takes_the_previous_session_s_day():
    w = gather.Window(ts(MON, 13, 30), ts(TUE, 7), ts(TUE, 6, 55), set(), ts(TUE, 6, 56))
    fact, why = _verify("https://money.udn.com/money/story/5607/8000001", "2026-11-16", w=w)
    assert why is None and fact["date_only"] and fact["published_at"] == "2026-11-16"
    assert _verify("https://money.udn.com/money/story/5607/8000001", "2026-11-15", w=w) == (None, "outside_window")


def test_every_citation_is_checked_for_freshness():
    fresh = "https://www.cna.com.tw/news/afe/202611160123.aspx"
    old = "https://money.udn.com/money/story/5607/7000001"
    res = {_norm_url(fresh): SearchResult(fresh, "台股今天收盤", "2026-11-16T15:32:00+08:00"),
           _norm_url(old): SearchResult(old, "外資賣超", "2026-11-02T15:00:00+08:00")}
    cites = [{"type": "web_search_result_location", "url": fresh, "title": "台股今天收盤",
              "cited_text": "台股今天量縮下跌，外資持續站在賣方，盤面上電子權值股普遍走弱。"},
             {"type": "web_search_result_location", "url": old, "title": "外資賣超",
              "cited_text": "外資當天在集中市場賣超 987.6 億元，投信買超 12.3 億元，自營商賣超 4.5 億元。"}]
    claim = "〔中央社〕報導，外資賣超 987.6 億元。"
    fact, why = gather.verify("TWSE_INST.foreign", claim, cites, res, W, ("TWSE_INST.",))
    assert fact is None and why == "number_not_in_quote"  # 987.6 is only on the 11/02 page
    # two fresh pages: the source is the one holding the number
    res[_norm_url(old)] = SearchResult(old, "外資賣超", "2026-11-16T15:00:00+08:00")
    fact, why = gather.verify("TWSE_INST.foreign", "〔經濟日報〕報導，外資賣超 987.6 億元。", cites, res, W,
                              ("TWSE_INST.",))
    assert why is None and fact["url"] == old and fact["published_at"].startswith("2026-11-16T15:00")
    assert fact["quote"].startswith("外資當天在集中市場賣超 987.6 億元")


@pytest.mark.parametrize("claim,reason", [
    ("〔中央社〕報導，法人預期台股短線將震盪走高。", "outlook"),
    ("〔中央社〕報導，法人看好台股。", "outlook"),
    ("〔中央社〕報導，摩根士丹利將聯發科評級調升為優於大盤。", "rating"),
])
def test_forecasts_and_ratings_are_not_gathered(claim, reason):
    url = "https://www.cna.com.tw/news/afe/202611160123.aspx"
    cited = "法人預期台股短線將震盪走高，摩根士丹利將聯發科評級調升為優於大盤，外資看好台股後市表現。"
    res = {_norm_url(url): SearchResult(url, "台股", "2026-11-16T15:32:00+08:00")}
    cites = [{"type": "web_search_result_location", "url": url, "title": "台股", "cited_text": cited}]
    assert gather.verify("TW.reason", claim, cites, res, W, ("TW.reason",)) == (None, reason)


def test_a_scheduled_event_may_say_will():
    url = "https://www.cna.com.tw/news/afe/202611160124.aspx"
    cited = "美國勞工部將於 11/20 公布 10 月消費者物價指數，市場關注通膨走向與聯準會的利率決策。"
    res = {_norm_url(url): SearchResult(url, "美國 CPI", "2026-11-16T15:32:00+08:00")}
    cites = [{"type": "web_search_result_location", "url": url, "title": "美國 CPI", "cited_text": cited}]
    fact, why = gather.verify("EVENT.us_cpi", "〔中央社〕報導，美國勞工部將於 11/20 公布 10 月 CPI。", cites, res, W,
                              ("EVENT.",))
    assert why is None and fact is not None


# -- the shared research: one W per checked source -------------------------------------------------------------------
def test_shared_research_is_one_w_per_source_and_checked(market_db, us_on):
    market_db.add(AiWhyResearch(symbol="2330.TW", session=MON, phase="after_close", market="TW", one_liner="",
                                updated_at=datetime(2026, 11, 16, 6, tzinfo=UTC),
                                expires_at=datetime(2026, 11, 17, tzinfo=UTC), sources=[
        {"url": "https://example-a.test/flash", "title": "盤中速報", "outlet": None, "snippets": [],
         "page_age": "2026-11-16T13:00:00+08:00"},
        {"url": "https://www.cna.com.tw/news/afe/202611160200.aspx", "title": "台積電走低", "outlet": "中央社",
         "snippets": ["台積電 ADR 前晚下跌 3.2%，今天台積電開低走低。"], "page_age": "2026-11-16T13:10:00+08:00"},
        {"url": "https://money.udn.com/money/story/5607/9000002", "title": "三天前的報導", "outlet": "經濟日報",
         "snippets": ["台積電上週五漲 2%。"], "page_age": "2026-11-13T13:10:00+08:00"},
        {"url": "https://www.ctee.com.tw/news/20261116700001-430501", "title": "外資評等", "outlet": "工商時報",
         "snippets": ["外資調升台積電目標價。"], "page_age": "2026-11-16T12:00:00+08:00"},
    ]))
    market_db.commit()
    pk = pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16)).pack
    [w] = [x for x in pk["research"] if x["symbol"] == "2330.TW"]
    assert [x["url"] for x in w["sources"]] == ["https://www.cna.com.tw/news/afe/202611160200.aspx"]
    assert w["quotes"] == ["台積電 ADR 前晚下跌 3.2%，今天台積電開低走低。"]
    payload = {"highlights": [p({"text": "台積電受 ADR 下跌 3.2% 影響走低。", "refs": [w["id"]]})], "sections": [],
               "sources": {"web": []}}
    assemble.number_footnotes(payload, pk)
    assert payload["footnotes"][0]["url"] == "https://www.cna.com.tw/news/afe/202611160200.aspx"


# -- the turnover list's scope ---------------------------------------------------------------------------------------
def test_the_turnover_list_skips_the_innovation_board_and_disposed_stocks(market_db):
    day = mc.load_day(market_db, "TWSE", MON, ts(MON, 15, 40))
    lists = mc.rule_lists(market_db, day)
    names = {q.name for q in lists.by_value}
    assert "合一-創" not in names and "全新" not in names and "大飲" not in names
    assert "台積電" in names


# -- a data edition's full disclaimer ----------------------------------------------------------------------------------
def test_a_data_edition_never_says_ai_wrote_it(market_db, us_on):
    built = pack.build(market_db, "close", MON, cutoff=ts(MON, 15, 40), now=ts(MON, 16))
    ed = pack.edition_on("close", MON)
    payload = assemble.build(kind="close", report_id="mrp_x", edition_date=MON, period=ed.period,
                             next_period=ed.next_period, version=1, edition="data", pack=built.pack,
                             blocks=built.blocks, output=None, published_at=ts(MON, 14, 11),
                             first_published_at=ts(MON, 14, 11), as_of=ts(MON, 14, 11))
    assert payload["disclaimer_full"] == assemble.DISCLAIMER_FULL_DATA
    assert "AI" not in payload["disclaimer_full"] and "媒體報導" not in payload["disclaimer_full"]


# -- the NYSE table ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("url,ok", [
    ("https://www.nyse.com/markets/hours-calendars", True), ("https://nyse.com/x", True),
    ("https://example.org/nyse.com", False), ("https://evil-nyse.com.attacker.net/x", False),
    ("https://attacker.net/?q=nyse.com", False), ("https://notnyse.com/", False),
    ("http://www.nyse.com/x", False), ("https://user@www.nyse.com/x", False),
])
def test_the_nyse_source_must_be_on_nyse_com(url, ok):
    assert service.nyse_url_ok(url) is ok


def test_an_item_name_may_use_its_own_refs(pre_pack):
    out = premarket_output(pre_pack)
    out["watch"][0]["event"] = "鴻海 11/17（二）法說會"
    assert not [x for x in validate.validate(out, pre_pack, "premarket") if x.hard and x.path == "watch[0].event"]
    out["watch"][0]["event"] = "鴻海 12/03 法說會"  # a date neither the pack nor the item has
    assert ("watch[0].event", "date_not_sourced") in {
        (x.path, x.code) for x in validate.validate(out, pre_pack, "premarket") if x.hard}


def test_a_plain_word_holding_a_short_name_is_not_a_stock(close_pack):
    text = "〔中央社〕報導，東南亞股市下跌，外資賣超 1,234.5 億元。"
    out = with_sentence(close_output(close_pack), "chips", text, "X001")
    assert "stock_not_allowed" not in codes(out, close_pack, names=["南亞"])
