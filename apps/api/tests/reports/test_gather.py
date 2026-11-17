"""The gathering (contract §8): the request (the repo's web search, direct calls only, the allowed domains, the quota,
fallbacks), parsing ``[KEY]`` paragraphs with their citations, and every reason a fact is dropped; outlets that
disagree on a number."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from forliosa.config import Settings
from forliosa.reports import calls, gather
from forliosa.timeutil import TAIPEI
from tests.ai.fake_anthropic import FakeAnthropic, search_citation, server_tool_use, text, web_search_result
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
    ({"page_age": "2026-11-16"}, "outside_window"),  # same day, date only
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
    assert out.topics[0]["dropped"] == {"no_citation": 1}
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
    assert pre["US_MARKET"] == 4 and pre["MACRO"] == 3 and pre["NIGHT"] == 1


def test_stock_reasons_pick_the_biggest_without_research():
    pk = {"facts": [{"id": "F1", "value": -1616}, {"id": "F2", "value": -12}, {"id": "F3", "value": 0.1}],
          "research": [{"symbol": "2317.TW"}],
          "stocks": [{"symbol": "3008.TW", "code": "3008", "name": "大立光", "lists": [], "facts": {"contrib": "F2"}},
                     {"symbol": "2330.TW", "code": "2330", "name": "台積電", "lists": [], "facts": {"contrib": "F1"}},
                     {"symbol": "2317.TW", "code": "2317", "name": "鴻海", "lists": [], "facts": {}},
                     {"symbol": "0050.TW", "code": "0050", "name": "元大台灣50", "lists": ["對照基準"], "facts": {}}]}
    assert gather.stock_reason_names(pk) == ["台積電（2330）", "大立光（3008）"]
