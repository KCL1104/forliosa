"""The gathering (contract §8): the request (the repo's web search, direct calls only, the allowed domains, the quota,
fallbacks), parsing ``[KEY]`` paragraphs with their citations, and every reason a fact is dropped; outlets that
disagree on a number."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import delete

from forliosa.ai.analyst import SearchResult
from forliosa.ai.market_summary import _norm_url
from forliosa.config import Settings
from forliosa.models import PriceDaily
from forliosa.reports import calls, gather, pack, prompts
from forliosa.reports import marketcalc as mc
from forliosa.timeutil import TAIPEI
from tests.ai.fake_anthropic import FakeAnthropic, search_citation, server_tool_use, text, web_search_result
from tests.reports.conftest import MON, TUE, ts
from tests.reports.helpers import gather_reply

W = gather.Window(datetime(2026, 11, 16, 8, tzinfo=TAIPEI), datetime(2026, 11, 16, 15, 50, tzinfo=TAIPEI),
                  datetime(2026, 11, 16, 15, 40, tzinfo=TAIPEI), {date(2026, 11, 13)},
                  datetime(2026, 11, 16, 15, 45, tzinfo=TAIPEI))
CNA = "https://www.cna.com.tw/news/afe/202611160123.aspx"
CITED = "外資今天賣超 1,234.5 億元，投信賣超 179.63 億元，自營商賣超 50 億元，三大法人合計賣超。"


@pytest.fixture(autouse=True)
def one_thread(monkeypatch):
    monkeypatch.setattr(gather, "TOPIC_THREADS", 1)
    calls.reset_state()


def topic(name="TWSE_INST", kind="close", quota=1):
    return gather.Topic(name, quota, "brief", gather.TOPICS[kind][name][2])


def collect(*blocks_per_topic, topic_obj=None):
    fake = FakeAnthropic()
    for blocks in blocks_per_topic:
        fake.reply(*blocks)
    client = fake.client("sk-test")
    t = topic_obj or topic()

    def call(kw, only):
        return calls.create(client, kw), 1

    res = gather.run_topics([t] * len(blocks_per_topic), "claude-sonnet-5-5", "low", call, Settings())
    return gather.collect(res, W), fake


def collect_one(*replies):
    """One topic whose calls get ``replies`` in turn (an answer, then the turn asking again for citations)."""
    fake = FakeAnthropic()
    for blocks in replies:
        fake.reply(*blocks)
    client = fake.client("sk-test")
    res = gather.run_topics([topic()], "claude-sonnet-5-5", "low", lambda kw, only: (calls.create(client, kw), 1),
                            Settings())
    return gather.collect(res, W), fake


def test_request_shape():
    fake = FakeAnthropic().reply(text("沒有找到。"))
    client = fake.client("sk-test")
    gather.run_topics([topic(quota=2)], "claude-sonnet-5-5", "low", lambda kw, only: (calls.create(client, kw), 1),
                      Settings())
    body, headers = fake.requests[0]["body"], fake.requests[0]["headers"]
    tool = body["tools"][0]
    assert tool["type"] == "web_search_20260318" and tool["allowed_callers"] == ["direct"] and tool["max_uses"] == 2
    assert not set(tool["allowed_domains"]) & {"reuters.com", "wsj.com", "ft.com", "apnews.com", "marketwatch.com",
                                                "barrons.com", "twse.com.tw", "tpex.org.tw", "taifex.com.tw"}
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in headers["anthropic-beta"]
    assert body["output_config"] == {"effort": "low"} and "thinking" not in body
    assert body["model"] == "claude-sonnet-5-5" and body["max_tokens"] == 8000


def test_a_cited_fact_is_kept_with_its_subject_and_quote():
    out, _ = collect(gather_reply("TWSE_INST.foreign", "〔中央社〕報導，外資 11/16 賣超 1,234.5 億元。", CNA,
                                  "外資賣超千億", CITED))
    [x] = out.facts
    assert x["id"] == "X001" and x["subject"] == "外資" and x["outlet"] == "中央社" and x["numbers"] == ["1234.5"]
    assert x["published_at"].startswith("2026-11-16T15:32") and not x["date_only"] and x["quote"] == CITED
    assert out.topics[0]["kept"] == 1


@pytest.mark.parametrize("change,reason", [
    ({"key": "MACRO.cpi"}, "bad_key"),
    ({"cite_url": "https://www.cna.com.tw/news/other.aspx"}, "url_not_in_results"),
    ({"page_age": "2026-11-16"}, "no_publish_time"),  # a close edition: same day, date only, no publish time
    ({"page_age": "2026-11-16T16:30:00+08:00"}, "outside_window"),
    ({"page_age": None, "url": "https://www.cna.com.tw/news/afe/x.aspx"}, "time_unknown"),
    ({"cited": "外資賣超"}, "related_headline"),
    ({"claim": "〔中央社〕報導，外資 11/16 賣超 2,000 億元。"}, "number_not_in_quote"),
    ({"claim": "〔中央社〕報導，外資 11/16 賣超 1,234.5 億元，目標價上調。"}, "rating"),
])
def test_dropped(change, reason):
    url = change.get("url", CNA)
    blocks = [server_tool_use("s1", "web_search", {"query": "q"}),
              web_search_result("s1", [{"url": url, "title": "外資賣超千億",
                                        "page_age": change.get("page_age", "2026-11-16T15:32:00+08:00")}]),
              text(f"[{change.get('key', 'TWSE_INST.foreign')}] "),
              text(change.get("claim", "〔中央社〕報導，外資 11/16 賣超 1,234.5 億元。"),
                   [search_citation(change.get("cite_url", url), "外資賣超千億", change.get("cited", CITED))]),
              text("\n\n")]
    out, _ = collect(blocks)
    assert out.facts == [] and out.topics[0]["dropped"] == {reason: 1}


def test_no_citation_and_us_facts_need_their_session_date():
    out, _ = collect([text("[TWSE_INST.foreign] 〔中央社〕報導，外資賣超 1,234.5 億元。")])
    assert out.topics[0]["dropped"] == {"no_citation": 1}  # asked again (no scripted reply): the first answer stands
    assert out.topics[0]["asked_again"] and out.topics[0]["error"] is None
    us = topic("US_MARKET", "premarket")
    url = "https://www.cnbc.com/2026/11/13/stocks.html"
    cited = "The S&P 500 rose 0.4% on Thursday as chip stocks rallied; Nasdaq gained 0.6% in the session."
    out, _ = collect(gather_reply("US.market", "〔CNBC〕報導，標普 500 漲 0.4%。", url, "Stocks rally", cited,
                                  page_age="2026-11-16T10:00:00+08:00"), topic_obj=us)
    assert out.topics[0]["dropped"] == {"no_us_session_date": 1}
    out, _ = collect(gather_reply("US.market", "〔CNBC〕報導，美股 11/13 標普 500 漲 0.4%。", url, "Stocks rally",
                                  cited, page_age="2026-11-16T10:00:00+08:00"), topic_obj=us)
    assert len(out.facts) == 1 and out.facts[0]["us_session"] == "2026-11-13"


def test_index_points_are_dropped():
    us = topic("US_MARKET", "premarket")
    url = "https://www.cnbc.com/2026/11/13/stocks.html"
    cited = "The Philadelphia semiconductor index closed at 6,123.45 points on Thursday, up 1.2% on the day."
    out, _ = collect(gather_reply("US.semis", "〔CNBC〕報導，美股 11/13 費半收 6,123.45 點。", url, "Chips", cited,
                                  page_age="2026-11-16T10:00:00+08:00"), topic_obj=us)
    assert out.topics[0]["dropped"] == {"index_points": 1}


def test_outlets_that_disagree():
    udn = "https://money.udn.com/money/story/5607/9000000"
    cnyes = "https://news.cnyes.com/news/id/6000000"
    cited2 = "投信今天賣超 179.62 億元，外資賣超 1,234.5 億元，三大法人合計賣超金額擴大。"
    cited1 = "投信今天賣超 179.63 億元，外資賣超 1,234.5 億元，三大法人合計賣超金額擴大。"
    blocks = [server_tool_use("s1", "web_search", {"query": "q"}),
              web_search_result("s1", [
                  {"url": cnyes, "title": "投信賣超 鉅亨", "page_age": "2026-11-16T15:35:00+08:00"},
                  {"url": CNA, "title": "投信賣超 中央社", "page_age": "2026-11-16T15:32:00+08:00"},
                  {"url": udn, "title": "法人動向 經濟日報", "page_age": "2026-11-16T15:31:00+08:00"}]),
              text("[TWSE_INST.trust] "), text("〔鉅亨網〕報導，投信賣超 179.62 億元。",
                                                [search_citation(cnyes, "投信賣超 鉅亨", cited2)]), text("\n\n"),
              text("[TWSE_INST.trust] "), text("〔中央社〕報導，投信賣超 179.63 億元。",
                                                [search_citation(CNA, "投信賣超 中央社", cited1)]), text("\n\n")]
    out, _ = collect(blocks)
    assert [x["outlet"] for x in out.facts] == ["中央社"]
    [d] = out.disagreements
    assert d["kept"]["outlet"] == "中央社" and d["others"][0]["outlet"] == "鉅亨網"
    assert "以中央社為準" in d["text"] and "179.62" in d["text"]


def test_pause_turn_is_continued_on_the_same_slot():
    fake = FakeAnthropic()
    fake.reply(server_tool_use("s1", "web_search", {"query": "q"}), stop_reason="pause_turn")
    fake.reply(*gather_reply("TWSE_INST.foreign", "〔中央社〕報導，外資 11/16 賣超 1,234.5 億元。", CNA, "外資賣超千億",
                             CITED))
    client = fake.client("sk-test")
    slots = []

    def call(kw, only):
        slots.append(only)
        return calls.create(client, kw), 3

    res = gather.run_topics([topic()], "claude-sonnet-5-5", "low", call, Settings())
    assert slots == [None, 3] and len(res[0].msgs) == 2
    assert fake.requests[1]["body"]["messages"][-1]["role"] == "assistant"


def test_topics_follow_the_kind_and_the_long_holiday():
    pk = {"web_window": {"from": "a", "to": "b"}, "dates": {"us_sessions": ["2026-11-13"]}, "edition_label": "x",
          "stocks": [], "research": [], "facts": [], "sectors": []}
    names = [t.name for t in gather.topics_for("close", pk)]
    assert names == ["MARKET_TODAY", "TWSE_INST", "TONIGHT"]  # no listed stock: no STOCK_REASONS
    pre = {t.name: t.quota for t in gather.topics_for("premarket", pk, long_holiday=True)}
    assert pre["US_MARKET"] == 5 and pre["MACRO"] == 4 and pre["NIGHT"] == 2


def test_stock_reasons_pick_the_biggest_without_research():
    pk = {"facts": [{"id": "F1", "value": -1616}, {"id": "F2", "value": -12}, {"id": "F3", "value": 0.1}],
          "research": [{"symbol": "2317.TW"}],
          "stocks": [{"symbol": "3008.TW", "code": "3008", "name": "大立光", "lists": [], "facts": {"contrib": "F2"}},
                     {"symbol": "2330.TW", "code": "2330", "name": "台積電", "lists": [], "facts": {"contrib": "F1"}},
                     {"symbol": "2317.TW", "code": "2317", "name": "鴻海", "lists": [], "facts": {}},
                     {"symbol": "0050.TW", "code": "0050", "name": "元大台灣50", "lists": ["對照基準"], "facts": {}}]}
    assert gather.stock_reason_names(pk) == ["台積電（2330）", "大立光（3008）"]


# -- 2026-11-17 dry run: freshness of pages dated by day alone (P0-2) ---------------------------------------------
# a premarket (window from the previous close, cut-off 06:55, searched at 06:16) and a weekly (Sunday 16:30)
PRE = gather.Window(ts(MON, 13, 30), ts(TUE, 7), ts(TUE, 6, 55), {MON}, ts(TUE, 6, 16))
SUN = date(2026, 11, 22)
WEEK = gather.Window(ts(date(2026, 11, 14), 0), ts(SUN, 16, 50), ts(SUN, 16, 30), set(), ts(SUN, 16, 31))
UDN = "https://money.udn.com/money/story/5607/9882230"


def check(page_age, w=W, *, url=UDN, cited=CITED, title="外資賣超千億",
          claim="〔經濟日報〕報導，外資賣超 1,234.5 億元。", key="TWSE_INST.foreign", extra=()):
    res = {_norm_url(url): SearchResult(url, title, page_age)}
    cites = [{"type": "web_search_result_location", "url": url, "title": title, "cited_text": cited},
             *({"type": "web_search_result_location", "url": url, "title": title, "cited_text": x} for x in extra)]
    return gather.verify(key, claim, cites, res, w, (key.split(".")[0] + ".",))


def test_a_premarket_keeps_a_page_of_0_days_ago_found_inside_its_window():
    # the engine counts days in UTC (the third dry run): at 06:16 Taipei it is still 11/16 there, so "0 days ago" is
    # the previous session's day and "1 days ago" (11/15 08:00 to 11/16 08:00 Taipei) is before the window
    fact, why = check("0 days ago", PRE)
    assert why is None and fact["date_only"] and fact["published_at"] == "2026-11-16"
    assert check("1 days ago", PRE) == (None, "outside_window")
    # a page dated the cut-off's own day, found inside the window
    fact, why = check("2026-11-17", PRE)
    assert why is None and fact["date_only"] and fact["published_at"] == "2026-11-17"
    # a rebuild after the window (searched at 17:46, 09:46 UTC): "0 days ago" may be after the cut-off
    late = gather.Window(PRE.start, PRE.end, PRE.cutoff, PRE.us_sessions, ts(TUE, 17, 46))
    assert check("0 days ago", late) == (None, "no_publish_time")
    assert check("2026-11-17", late) == (None, "no_publish_time")


def test_a_weekly_keeps_a_page_of_its_own_sunday():
    fact, why = check("0 days ago", WEEK)
    assert why is None and fact["published_at"] == "2026-11-22"


@pytest.mark.parametrize("stamp,kept", [
    ("2026-11-16 15:32 經濟日報／記者王小明／台北即時報導", "2026-11-16T15:32:00+08:00"),
    ("2026/11/16 14:05 經濟日報 記者王小明／台北即時報導", "2026-11-16T14:05:00+08:00"),
    ("2026年11月16日 13:40 經濟日報 記者王小明／台北報導", "2026-11-16T13:40:00+08:00"),
    ("115/11/16 15:01 中央社記者王小明台北16日電", "2026-11-16T15:01:00+08:00"),
    ("2026-11-16 07:30 經濟日報／記者王小明／台北即時報導", None),  # before the window opened (a pre-open story)
    ("2026-11-16 15:49 經濟日報／記者王小明／台北即時報導", None),  # after the search
    ("2026-11-15 15:32 經濟日報／記者王小明／台北即時報導", None),  # another day
])
def test_a_close_edition_needs_the_publish_time_of_a_same_day_page(stamp, kept):
    fact, why = check("0 days ago", extra=(stamp,))
    if kept is None:
        assert (fact, why) == (None, "no_publish_time")
    else:
        assert why is None and fact["published_at"] == kept and not fact["date_only"]


def test_a_close_edition_reads_the_publish_time_in_the_title():
    fact, why = check("0 days ago", title="外資賣超千億 2026-11-16 15:20")
    assert why is None and fact["published_at"] == "2026-11-16T15:20:00+08:00"
    assert check("0 days ago") == (None, "no_publish_time")


def test_in_window_for_pages_dated_by_day():
    assert gather.in_window(TUE, PRE) and gather.in_window(MON, PRE)
    assert not gather.in_window(MON, W)  # W is a close edition on 11/16: its window starts that morning
    assert gather.in_window(SUN, WEEK)
    assert not gather.in_window(date(2026, 11, 18), PRE)


# -- quote pages, citations, quotas (P1-3) ----------------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "https://www.cnyes.com/twstock/?code=2731", "https://invest.cnyes.com/INDEX/TWS/TSE01",
    "https://www.cnyes.com/archive/twstock/idx_technical/0000t.htm", "https://www.moneydj.com/z/zc/zca/zca_2330.djhtm",
    "https://www.cnbc.com/quotes/NVDA",
])
def test_quote_pages_are_never_a_source(url):
    assert gather.quote_page(url)
    assert check("2026-11-16T15:32:00+08:00", url=url)[1] in ("quote_page", "domain")


def test_news_pages_are_not_quote_pages():
    for url in (CNA, UDN, "https://news.cnyes.com/news/id/6664138",
                "https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=38f9b8fc"):
        assert not gather.quote_page(url)
    assert check("2026-11-16T15:32:00+08:00", url="https://www.moneydj.com/z/zc/zca/zca_2330.djhtm") == \
        (None, "quote_page")


def test_the_search_keeps_to_cnyes_news():
    assert "news.cnyes.com" in calls.REPORT_SEARCH_DOMAINS and "cnyes.com" not in calls.REPORT_SEARCH_DOMAINS
    assert check("2026-11-16T15:32:00+08:00", url="https://www.cnyes.com/twstock/2330")[1] == "domain"
    assert check("2026-11-16T15:32:00+08:00", url="https://news.cnyes.com/news/id/6000002")[1] is None


def test_every_topic_may_search_two_or_three_times_and_is_told_so():
    for kind, topics in gather.TOPICS.items():
        assert all(2 <= q <= 3 for q, _what, _keys in topics.values()), kind
    pk = {"web_window": {"from": "2026-11-16T08:00:00+08:00", "to": "2026-11-16T15:50:00+08:00"}, "dates": {},
          "edition_label": "11/16（一）", "stocks": [], "research": [], "facts": [], "sectors": []}
    [today, *_] = gather.topics_for("close", pk)
    assert today.quota == 3 and "搜尋最多 3 次" in today.brief and "2026-11-16 15:32" in today.brief
    assert "報價頁" in prompts.GATHER_SYSTEM and "沒有引用的段落一律丟掉" in prompts.GATHER_SYSTEM


UNCITED = [server_tool_use("s1", "web_search", {"query": "q"}),
           web_search_result("s1", [{"url": CNA, "title": "外資賣超千億", "page_age": "2026-11-16T15:32:00+08:00"}]),
           text("[TWSE_INST.foreign] 〔中央社〕報導，外資 11/16 賣超 1,234.5 億元。\n\n"
                "[TWSE_INST.trust] 〔中央社〕報導，投信 11/16 賣超 179.63 億元。")]
CITED_AGAIN = [text("[TWSE_INST.foreign] "),
               text("〔中央社〕報導，外資 11/16 賣超 1,234.5 億元。", [search_citation(CNA, "外資賣超千億", CITED)]),
               text("\n\n[TWSE_INST.trust] "),
               text("〔中央社〕報導，投信 11/16 賣超 179.63 億元。", [search_citation(CNA, "外資賣超千億", CITED)])]


def test_an_uncited_answer_is_asked_again_once():
    out, fake = collect_one(UNCITED, CITED_AGAIN)
    assert len(fake.requests) == 2
    again = fake.requests[1]["body"]
    assert again["messages"][-1] == {"role": "user", "content": prompts.CITE_AGAIN}
    assert again["messages"][-2]["role"] == "assistant"
    assert [b["type"] for b in again["messages"][-2]["content"]][:2] == ["server_tool_use", "web_search_tool_result"]
    assert again["tools"][0]["max_uses"] == gather.CITE_RETRY_SEARCHES
    assert [x["key"] for x in out.facts] == ["TWSE_INST.foreign", "TWSE_INST.trust"]  # cites the first search
    assert out.topics[0]["asked_again"] and out.topics[0]["dropped"] == {}


def test_a_worse_second_answer_keeps_the_first():
    first = [*gather_reply("TWSE_INST.foreign", "〔中央社〕報導，外資 11/16 賣超 1,234.5 億元。", CNA, "外資賣超千億",
                           CITED), text("[TWSE_INST.trust] 〔中央社〕報導，投信 11/16 賣超 179.63 億元。")]
    out, fake = collect_one(first, [text("沒有找到。")])
    assert len(fake.requests) == 2 and [x["key"] for x in out.facts] == ["TWSE_INST.foreign"]
    assert out.topics[0]["dropped"] == {"no_citation": 1}


def test_a_mostly_cited_answer_is_not_asked_again():
    blocks = [*gather_reply("TWSE_INST.foreign", "〔中央社〕報導，外資 11/16 賣超 1,234.5 億元。", CNA, "外資賣超千億",
                            CITED),
              text("[TWSE_INST.dealer] "), text("〔中央社〕報導，自營商 11/16 賣超 50 億元。",
                                                 [search_citation(CNA, "外資賣超千億", CITED)]), text("\n\n"),
              text("[TWSE_INST.trust] 〔中央社〕報導，投信 11/16 賣超 179.63 億元。")]
    out, fake = collect(blocks)
    assert len(fake.requests) == 1 and "asked_again" not in out.topics[0]
    assert len(out.facts) == 2 and out.topics[0]["dropped"] == {"no_citation": 1}


def test_citation_counts():
    content = [text("前言。\n\n[A.x] 沒有引用。\n\n"), text("[B.y] "),
               text("有引用。", [search_citation(CNA, "t", CITED)])]
    assert gather.citation_counts(content) == (1, 1) and gather.needs_citations(content)


# -- readings of the market (P2-9) --------------------------------------------------------------------------------
@pytest.mark.parametrize("claim", ["〔經濟日報〕報導，分析師指出台股短線利空出盡。",
                                   "〔經濟日報〕報導，法人認為利多出盡。",
                                   "〔經濟日報〕報導，分析師說電子股遭到錯殺。"])
def test_readings_of_the_market_are_not_gathered(claim):
    cited = "分析師指出台股短線利空出盡，法人認為利多出盡，電子股遭到錯殺，外資賣超 1,234.5 億元。"
    assert check("2026-11-16T15:32:00+08:00", cited=cited, claim=claim, key="TW.reason") == (None, "outlook")


# -- US sessions (P2-13) and the US trading day of a fact -------------------------------------------------------
def test_the_brief_and_the_window_take_the_edition_s_us_sessions_without_us_prices(market_db):
    market_db.execute(delete(PriceDaily).where(PriceDaily.source == mc.US_SOURCE))
    market_db.flush()
    pk = pack.build(market_db, "premarket", TUE, policy="commercial", now=ts(TUE, 6, 15)).pack
    assert pk["dates"]["us_sessions"] == [] and pk["web_window"]["us_sessions"] == ["2026-11-16"]
    us = next(t for t in gather.topics_for("premarket", pk) if t.name == "US_MARKET")
    assert "涵蓋的美股交易日：11/16" in us.brief
    assert gather.window(pk, ts(TUE, 6, 16)).us_sessions == {MON}
    # a pack stored before the field: the dates with US closes
    old = {**pk, "web_window": {k: v for k, v in pk["web_window"].items() if k != "us_sessions"},
           "dates": {**pk["dates"], "us_sessions": ["2026-11-13"]}}
    assert gather.us_sessions_of(old) == ["2026-11-13"]


def test_a_us_fact_names_a_session_that_ended_before_the_cut_off_day():
    url = "https://www.cnbc.com/2026/11/16/stock-market-today.html"
    cited = "The S&P 500 fell 0.8% on Monday as chip stocks slid; the Nasdaq Composite lost 1.2% in the session."
    args = {"url": url, "cited": cited, "title": "Stocks fall", "key": "US.market"}
    fact, why = check("0 days ago", PRE, claim="〔CNBC〕報導，美股 11/16 標普 500 跌 0.8%。", **args)
    assert why is None and fact["us_session"] == "2026-11-16"
    # 11/17 is the Taipei date of the story: the US session of 11/17 had not happened by 06:55
    assert check("0 days ago", PRE, claim="〔CNBC〕報導，美股 11/17 標普 500 跌 0.8%。", **args) == \
        (None, "no_us_session_date")
    # a scheduled earnings date may be the cut-off's own day (tonight)
    tonight = "Nvidia is scheduled to report quarterly results after the bell on Tuesday, Nov. 17, analysts said."
    close17 = gather.Window(ts(TUE, 8), ts(TUE, 15, 50), ts(TUE, 15, 40), set(), ts(TUE, 15, 45))
    fact, why = check("2026-11-17T10:00:00+08:00", close17, url="https://www.cnbc.com/2026/11/17/nvidia-earnings.html",
                      cited=tonight, title="Nvidia earnings", key="US.earnings.nvda",
                      claim="〔CNBC〕報導，輝達排定美股 11/17 盤後公布財報。")
    assert why is None and fact["us_session"] == "2026-11-17"


# -- review of the dry-run fixes: a publish time is where pages put one (P0-2) ---------------------------------------
@pytest.mark.parametrize("passage", [
    "台積電訂 2026/11/16 14:00 召開法說會，會中將說明第四季營運展望與資本支出。",
    "台指期 11 月合約將於 11/16 13:30 結算，結算價以最後 15 分鐘的成交價計算。",
    "2026/11/16 13:30 台指期結算，外資空單部位成為市場焦點。",
    "鴻海科技日 11/16 14:00 登場，外資賣超 1,234.5 億元。",
    "市場收盤 11/16 13:35 (UTC+8) 加權指數下跌。",
])
def test_the_time_of_a_scheduled_event_is_not_a_publish_time(passage):
    assert check("0 days ago", extra=(passage,)) == (None, "no_publish_time")


@pytest.mark.parametrize("passage,kept", [
    ("2026/11/16 14:35\n台股今天量縮下跌，外資賣超。", "14:35"),  # the date line of the page
    ("發布時間：2026-11-16 14:20", "14:20"),
    ("鉅亨網記者王小明 台北 2026/11/16 14:05", "14:05"),
    ("2026-11-16 15:10 鉅亨網新聞中心", "15:10"),
    ("2026/11/16 15:01 記者王小明／台北報導", "15:01"),
])
def test_a_byline_or_a_dateline_is_a_publish_time(passage, kept):
    fact, why = check("0 days ago", extra=(passage,))
    assert why is None and fact["published_at"] == f"2026-11-16T{kept}:00+08:00" and not fact["date_only"]


def test_an_event_time_in_a_title_is_not_a_publish_time():
    assert check("0 days ago", title="台積電法說會 2026-11-16 14:00") == (None, "no_publish_time")


def test_a_short_dateline_cited_on_its_own_dates_its_page():
    # 「2026/11/16 14:05」 is under 20 characters: never a source of the fact, but it still dates the page
    fact, why = check("0 days ago", extra=("2026/11/16 14:05",))
    assert why is None and fact["published_at"] == "2026-11-16T14:05:00+08:00" and fact["quote"] == CITED
    assert check("0 days ago", extra=("外資賣超",)) == (None, "no_publish_time")
    # a short passage of another page dates nothing here
    other = "https://money.udn.com/money/story/5607/9882231"
    res = {_norm_url(UDN): SearchResult(UDN, "外資賣超千億", "0 days ago"),
           _norm_url(other): SearchResult(other, "台股收盤", "0 days ago")}
    cites = [{"type": "web_search_result_location", "url": UDN, "title": "外資賣超千億", "cited_text": CITED},
             {"type": "web_search_result_location", "url": other, "title": "台股收盤",
              "cited_text": "2026/11/16 14:05"}]
    assert gather.verify("TWSE_INST.foreign", "〔經濟日報〕報導，外資賣超 1,234.5 億元。", cites, res, W,
                         ("TWSE_INST.",)) == (None, "no_publish_time")


# -- the US sessions the edition covers (P2-13) ----------------------------------------------------------------------
SEMIS = {"url": "https://www.cnbc.com/2026/11/16/chip-stocks.html", "title": "Chip stocks", "key": "US.semis",
         "cited": "The Philadelphia semiconductor index fell 5.28% while the chip stocks slid 2.10% in the session."}


def test_a_us_fact_of_an_older_session_is_not_overnight_news():
    assert check("0 days ago", PRE, claim="〔CNBC〕報導，美股 11/13 費城半導體指數跌 5.28%。", **SEMIS) == \
        (None, "no_us_session_date")
    fact, why = check("0 days ago", PRE, claim="〔CNBC〕報導，美股 11/16 費城半導體指數跌 5.28%。", **SEMIS)
    assert why is None and fact["us_session"] == "2026-11-16"
    # every US date of the claim is one the edition covers
    assert check("0 days ago", PRE, claim="〔CNBC〕報導，美股 11/16 費半跌 5.28%，美股 11/13 跌 2.10%。", **SEMIS) == \
        (None, "no_us_session_date")


def test_a_weekly_takes_the_us_sessions_of_its_week():
    week = gather.Window(WEEK.start, WEEK.end, WEEK.cutoff, {date(2026, 11, d) for d in range(16, 21)}, WEEK.now)
    fact, why = check("1 days ago", week, claim="〔CNBC〕報導，美股 11/20 費城半導體指數跌 5.28%。", **SEMIS)
    assert why is None and fact["us_session"] == "2026-11-20"
    assert check("1 days ago", week, claim="〔CNBC〕報導，美股 11/13 費城半導體指數跌 5.28%。", **SEMIS) == \
        (None, "no_us_session_date")


def test_an_edition_with_no_us_session_takes_no_us_fact_but_earnings_dates():
    none = gather.Window(PRE.start, PRE.end, PRE.cutoff, set(), PRE.now)  # the day after a US holiday
    assert check("0 days ago", none, claim="〔CNBC〕報導，美股 11/16 費城半導體指數跌 5.28%。", **SEMIS) == \
        (None, "no_us_session_date")
    nvda = {**SEMIS, "key": "US.earnings.nvda",
            "cited": "Nvidia is scheduled to report quarterly results after the bell on Monday, Nov. 16, "
                     "analysts said."}
    fact, why = check("0 days ago", none, claim="〔CNBC〕報導，輝達排定美股 11/16 盤後公布財報。", **nvda)
    assert why is None and fact["us_session"] == "2026-11-16"
    # a pack stored before ``web_window.us_sessions`` and without US closes: any session before the cut-off day
    old = gather.Window(PRE.start, PRE.end, PRE.cutoff, None, PRE.now)
    assert check("0 days ago", old, claim="〔CNBC〕報導，美股 11/13 費城半導體指數跌 5.28%。", **SEMIS)[1] is None


def test_the_window_knows_when_the_edition_covers_no_us_session():
    base = {"web_window": {"from": "2026-11-16T13:30:00+08:00", "to": "2026-11-17T07:00:00+08:00"},
            "cutoff": "2026-11-17T06:55:00+08:00", "dates": {"us_sessions": []}}
    assert gather.window({**base, "web_window": {**base["web_window"], "us_sessions": []}}, PRE.now).us_sessions \
        == set()
    assert gather.window(base, PRE.now).us_sessions is None  # an old pack without US closes
    assert gather.window({**base, "dates": {"us_sessions": ["2026-11-16"]}}, PRE.now).us_sessions == {MON}


# -- each topic is checked at the time of its own searches (P0-2) --------------------------------------------------
def test_a_slow_topic_does_not_drop_the_other_topics_same_day_pages():
    fake = FakeAnthropic()
    for _ in range(2):
        fake.reply(*gather_reply("TWSE_INST.foreign", "〔中央社〕報導，外資 11/16 賣超 1,234.5 億元。", CNA,
                                 "外資賣超千億", CITED, page_age="2026-11-17"))
    client = fake.client("sk-test")
    times = iter([ts(TUE, 6, 30), ts(TUE, 7, 10)])  # the first topic replied in time, the second after 07:00
    res = gather.run_topics([topic(), topic()], "claude-sonnet-5-5", "low",
                            lambda kw, only: (calls.create(client, kw), 1), Settings(), clock=lambda: next(times))
    assert [r.replied_at for r in res] == [ts(TUE, 6, 30), ts(TUE, 7, 10)]
    out = gather.collect(res, gather.Window(PRE.start, PRE.end, PRE.cutoff, PRE.us_sessions, ts(TUE, 7, 12)))
    assert [t["kept"] for t in out.topics] == [1, 0] and out.topics[1]["dropped"] == {"no_publish_time": 1}
    assert out.facts[0]["published_at"] == "2026-11-17"
