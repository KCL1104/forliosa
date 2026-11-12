"""Grounding check: after a turn that used web search / fetch, uncited news-like sentences are listed in a
``grounding`` event (and kept with the answer) so the UI can mark them 「無來源」."""

from __future__ import annotations

from forliosa.ai.grounding import Segment, check, sentences
from tests.ai.conftest import API, buy, chat, make_account
from tests.ai.fake_anthropic import search_citation, server_tool_use, text, tool_use, web_search_result

CLAIM = "董事會批准投資 Anthropic 與 OpenAI。"


def test_check_flags_only_uncited_news_claims():
    t = ("台積電今天上漲 3%。主因是法說會上調展望。" + CLAIM
         + "建議分散投資。聯準會 9 月降息。11/12 收盤 1,050 元，▲3.5%。")
    cited = Segment(t.index("主因"), t.index(CLAIM), True)
    items = check(t, [Segment(0, cited.start, False), cited, Segment(cited.end, len(t), False)])
    assert [i["text"] for i in items] == [CLAIM, "聯準會 9 月降息。"]
    first = items[0]
    assert (first["start"], first["end"]) == (t.index(CLAIM), t.index(CLAIM) + len(CLAIM))
    assert first["reason"] == "uncited_news_claim" and "verb:批准" in first["signals"]
    assert first["index"] == 2 and t[first["start"]:first["end"]] == first["text"]
    # a cited block covering the claim clears it; plain data sentences are never flagged
    assert check(CLAIM, [Segment(0, 5, True)]) == []
    assert check("營收成長 3.5%，毛利率 53%。持股市值 120 萬。", []) == []


def test_sentences_keep_offsets():
    t = "第一句。\n・第二點；第三點\n\n最後"
    assert [t[a:b] for a, b in sentences(t)] == ["第一句。", "・第二點；", "第三點", "最後"]


def _search_turn(fake, *blocks):
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "台積電 董事會"}),
               web_search_result("srvtoolu_1", [{"url": "https://www.cna.com.tw/a", "title": "中央社",
                                                 "encrypted_content": "E"}]),
               *blocks, usage={"server_tool_use": {"web_search_requests": 1}})


def test_grounding_event_after_web_search(client, pool, fake):
    _search_turn(fake, text("台積電今天上漲。"),
                 text("法說會上調全年展望。", [search_citation("https://www.cna.com.tw/a", "中央社", "上調展望")]),
                 text(CLAIM))
    _status, events = chat(client, "台積電今天有什麼新聞？")
    names = [n for n, _ in events]
    assert names[-2:] == ["grounding", "done"]
    items = events[-2][1]["items"]
    answer = "".join(d["delta"] for n, d in events if n == "text")
    assert [i["text"] for i in items] == [CLAIM] and answer[items[0]["start"]:items[0]["end"]] == CLAIM
    detail = client.get(f"{API}/ai/threads/{events[0][1]['id']}").json()
    assert detail["messages"][1]["grounding"] == items


def test_offsets_span_tool_rounds(client, pool, fake):
    acc = make_account(client)
    buy(client, acc, "2330", 1000, 600)
    fake.reply(text("我查一下。"), tool_use("toolu_1", "get_holdings", {}), stop_reason="tool_use")
    _search_turn(fake, text("你持有台積電 1 張。" + CLAIM))
    _status, events = chat(client, "我的台積電有什麼新聞？")
    answer = "".join(d["delta"] for n, d in events if n == "text")
    items = next(d for n, d in events if n == "grounding")["items"]
    assert answer.startswith("我查一下。\n\n") and answer[items[0]["start"]:items[0]["end"]] == CLAIM


def test_no_grounding_event_without_web_search(client, pool, fake):
    fake.reply(text(CLAIM))
    _status, events = chat(client, "台積電呢？")
    assert "grounding" not in [n for n, _ in events]
    detail = client.get(f"{API}/ai/threads/{events[0][1]['id']}").json()
    assert detail["messages"][1]["grounding"] == []
