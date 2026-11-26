"""tw_news_search in a chat turn (產品負責人 2026-11-17; round-2 recommendation §4.6, §9.6–9.7): the LangSearch excerpt
reaches Claude in that turn only — a citation, the stored turn, the thread view and the shared research carry its
title line — the answer editor still sees it for its paste check, a replay of the scrubbed history that the API
refuses continues from the recap, nothing of it is logged, 省錢模式 notes never point to web search, and with the
switch off everything is as before. No network: LangSearch answers through a scripted client, Claude through the fake
Messages API. Every text here is SYNTHETIC."""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.ai import research, store
from forliosa.ai import tools as tools_mod
from forliosa.ai import tw_news as tw
from forliosa.ai.chat import COPY_CLOSE, COPY_OPEN, COPY_REMOVED, EDITOR_COPIES
from forliosa.ai.prompts import CHAT_SYSTEM, CHAT_SYSTEM_TW, ECONOMY_NOTE, ECONOMY_NOTE_TW, EDITOR_SYSTEM
from forliosa.models import AiMessage, AiWhyResearch
from forliosa.news import langsearch as ls
from forliosa.services import stock as stock_svc
from tests.ai.conftest import API, chat
from tests.ai.fake_anthropic import text, thinking, tool_use
from tests.ai.test_tools import NOT_STRICT

NOW = datetime(2026, 11, 17, 10, 40, tzinfo=UTC)  # 18:40 Taipei
KEY = "sk-ls-chat-77c2e1"
PAGE = {"route": "/stock/2330.TW", "symbol": "2330.TW"}
URL = "https://money.udn.com/money/story/5612/9880441"
URL2 = "https://ec.ltn.com.tw/article/breakingnews/5212345"
TITLE = "台積電法說會釋出正向展望"
TITLE2 = "台積電董事會核准資本預算"
SNIPPET = "外資最新報告指出台積電先進製程需求強勁，維持買進評等，目標價上調至 2,400 元。"
EXCERPT_MARK = "先進製程需求強勁，維持買進評等"  # a piece of the excerpt that must never leave the turn
LINE = f"經濟日報，11/16：{TITLE}"  # the title line that persists instead
NEWS_ITEM = {"published_at": "2026-11-16T09:00:00+08:00", "title": "台積電公告董事會決議", "category": "material_info",
             "source": "公告", "url": "https://mops.twse.com.tw/mops/web/t05st01", "sources": ["臺灣證券交易所"]}


def page(name: str, url: str, snippet: str, published: str = "2026-11-16T02:00:00.000Z") -> dict[str, Any]:
    return {"name": name, "url": url, "datePublished": published, "snippet": snippet}


def reply(*pages: dict[str, Any], status: int = 200) -> ls.Reply:
    return ls.Reply(status, {"code": 200, "data": {"webPages": {"value": list(pages)}}}, 10, 900, 2.0)


GOOD = reply(page(TITLE, URL, SNIPPET), page(TITLE2, URL2, "台積電董事會今天核准資本預算，用於擴充先進製程產能。"))


class FakeClient:
    def __init__(self, *replies: ls.Reply) -> None:
        self.replies = list(replies) or [GOOD]
        self.bodies: list[dict[str, Any]] = []

    def post(self, body: dict[str, Any], deadline: float | None = None) -> ls.Reply:
        self.bodies.append(dict(body))
        return self.replies[min(len(self.bodies) - 1, len(self.replies) - 1)]

    def close(self) -> None:
        pass


@pytest.fixture()
def langsearch(ai_env, monkeypatch):
    """AI_LANGSEARCH_ENABLED with a key; LangSearch answers from the scripted client; the tool's clock at NOW."""
    ai_env(AI_LANGSEARCH_ENABLED="true", LANGSEARCH_API_KEY=KEY)
    holder = {"client": FakeClient()}
    monkeypatch.setattr(ls.LangSearchClient, "from_settings", lambda settings: holder["client"])
    monkeypatch.setattr(tw, "_clock", lambda: NOW)
    monkeypatch.setattr(tw, "_sleep", lambda s: None)

    def use(*replies: ls.Reply) -> FakeClient:
        holder["client"] = FakeClient(*replies)
        return holder["client"]

    return use


def location(url: str, title: str, cited: str, index: int = 0) -> dict:
    return {"type": "search_result_location", "source": url, "title": title, "cited_text": cited,
            "search_result_index": index, "start_block_index": 0, "end_block_index": 1}


def tw_call(tid: str = "toolu_tw", intent: str = "news", symbol: str = "2330") -> dict:
    return tool_use(tid, "tw_news_search", {"symbol": symbol, "intent": intent, "days": 0})


def stored(engine, thread_id: str) -> str:
    with Session(engine) as db:
        rows = db.scalars(select(AiMessage).where(AiMessage.thread_id == thread_id)).all()
        return json.dumps([[r.content, r.meta, r.text] for r in rows], ensure_ascii=False)


def tool_results(body: dict) -> list[dict]:
    return [b for m in body["messages"] if m["role"] == "user" and isinstance(m["content"], list)
            for b in m["content"] if b.get("type") == "tool_result"]


# -- 9. citations -----------------------------------------------------------------------------------
def test_citation_redacted(client, pool, fake, langsearch, engine):
    ls_client = langsearch(GOOD)
    fake.reply(tw_call(), stop_reason="tool_use")
    fake.reply(text("法說會後外資看好先進製程需求。", [location(URL, TITLE, f"經濟日報，11/16：{SNIPPET}")]))
    status, events = chat(client, "台積電最近有什麼消息？", page=PAGE)
    assert status == 200 and [d["code"] for n, d in events if n == "error"] == []
    first, second = fake.requests[0]["body"], fake.requests[1]["body"]
    # the request: the tool offered (not strict), the prompt that routes Taiwan questions to it
    tw_def = next(t for t in first["tools"] if t["name"] == "tw_news_search")
    assert "strict" not in tw_def and first["system"][0]["text"] == CHAT_SYSTEM_TW
    assert sum(1 for t in first["tools"] if t.get("strict") is True) <= 20
    # Claude gets the excerpt in this turn, one search result per article, no numbering
    blocks = tool_results(second)[0]["content"]
    assert [(b["type"], b["source"]) for b in blocks] == [("search_result", URL), ("search_result", URL2)]
    first_text = blocks[0]["content"][0]["text"]
    assert EXCERPT_MARK in first_text and first_text.startswith("經濟日報，11/16")
    assert ls_client.bodies[0]["query"] == '"台積電"'
    # the browser gets the title line
    cites = [d for n, d in events if n == "citation"]
    assert cites == [{"url": URL, "title": TITLE, "cited_text": LINE, "outlet": "經濟日報"}]
    assert EXCERPT_MARK not in json.dumps(events, ensure_ascii=False)
    tools = [d for n, d in events if n == "tool"]
    assert tools[0]["label"] == "搜尋台灣新聞：2330 新聞"
    detail = client.get(f"{API}/ai/threads/{events[0][1]['id']}").json()
    assert detail["messages"][1]["citations"][0]["cited_text"] == LINE
    assert EXCERPT_MARK not in json.dumps(detail, ensure_ascii=False)


# -- 10. the stored turn ----------------------------------------------------------------------------
def test_save_turn_scrubbed(client, pool, fake, langsearch, engine, monkeypatch):
    monkeypatch.setattr(stock_svc, "news", lambda db, md, symbol: [NEWS_ITEM])
    langsearch(GOOD)
    fake.reply(tw_call(), tool_use("toolu_n", "get_news", {"symbol": "2330"}), stop_reason="tool_use")
    fake.reply(text("董事會有決議。", [location(NEWS_ITEM["url"], NEWS_ITEM["title"], "公司公告：董事會決議")]),
               text("外資看好需求。", [location(URL, TITLE, f"經濟日報，11/16：{SNIPPET}", 0)]))
    _status, events = chat(client, "台積電有什麼消息？", page=PAGE)
    tid = events[0][1]["id"]
    sent = tool_results(fake.requests[1]["body"])
    everything = stored(engine, tid)
    assert EXCERPT_MARK not in everything and LINE in everything
    with Session(engine) as db:
        rows = db.scalars(select(AiMessage).where(AiMessage.thread_id == tid).order_by(AiMessage.seq)).all()
        results = [b for r in rows if r.role == "user" and isinstance(r.content, list) for b in r.content
                   if b.get("type") == "tool_result"]
    by_id = {b["tool_use_id"]: b for b in results}
    assert by_id["toolu_n"] == next(b for b in sent if b["tool_use_id"] == "toolu_n")  # get_news as it was
    tw_blocks = by_id["toolu_tw"]["content"]
    assert tw_blocks[0] == {"type": "search_result", "source": URL, "title": TITLE,
                            "content": [{"type": "text", "text": LINE}], "citations": {"enabled": True}}


# -- 11. the shared research ------------------------------------------------------------------------
OVERVIEW = {"symbol": "2330.TW", "code": "2330", "name": "台積電", "market": "TWSE", "industry": "半導體業",
            "english_name": "TSMC", "quote": {"price": 2200.0, "change_pct": -0.03, "trade_date": "2026-11-17"},
            "market_context": {"taiex": {"name": "發行量加權股價指數", "date": "2026-11-17", "change_pct": -0.02}},
            "why_signals": []}


def test_research_remember_tw_only(client, pool, fake, langsearch, engine, monkeypatch):
    spec = tools_mod.TOOLS_BY_NAME["get_stock_overview"]
    monkeypatch.setitem(tools_mod.TOOLS_BY_NAME, "get_stock_overview",
                        dataclasses.replace(spec, handler=lambda ctx, args: dict(OVERVIEW)))
    langsearch(GOOD)
    fake.reply(tool_use("toolu_o", "get_stock_overview", {"symbol": "2330"}), tw_call(intent="why_move"),
               stop_reason="tool_use")
    fake.reply(text("台積電今天跌 3%，大盤跌 2%；外資看好需求。", [location(URL, TITLE, LINE + SNIPPET)]))
    status, _events = chat(client, "台積電今天為什麼跌？", page=PAGE)
    assert status == 200
    assert not any(b.get("name") == "web_search" for b in fake.requests[1]["body"]["messages"][2]["content"])
    with Session(engine) as db:
        rows = db.scalars(select(AiWhyResearch)).all()
        assert len(rows) == 1 and rows[0].searches == 1
        sources = rows[0].sources
    assert [s["url"] for s in sources] == [URL] and sources[0]["snippets"] == [LINE]
    assert EXCERPT_MARK not in json.dumps(sources, ensure_ascii=False)
    # the next asker's turn gets the title line as the shared search result
    assert research.blocks(research.Research(None, sources, None, NOW, 1))[0]["content"] == [
        {"type": "text", "text": LINE}]


# -- 12. the answer editor --------------------------------------------------------------------------
def test_editor_catches_paste_from_excerpt(client, pool, fake, langsearch, engine, ai_env, caplog):
    ai_env(AI_ANSWER_EDITOR="true")
    langsearch(GOOD)
    pasted = "外資最新報告指出台積電先進製程需求強勁，維持買進評等，目標價上調至 2,400 元"
    fake.reply(tw_call(intent="analyst_targets"), stop_reason="tool_use")
    fake.reply(text(f"外資把台積電目標價上調到 2,400 元。{pasted}", [location(URL, TITLE, SNIPPET)]))
    fake.error(500, "api_error", "editor down")  # the edit fails: the draft is shown, its paste left out
    with caplog.at_level(logging.INFO):
        _status, events = chat(client, "台積電最新的目標價？", page=PAGE)
    final = "".join(d["delta"] for n, d in events if n == "text")
    assert final == "外資把台積電目標價上調到 2,400 元。"
    dumped = json.dumps(events, ensure_ascii=False) + stored(engine, events[0][1]["id"]) + caplog.text
    assert EXCERPT_MARK not in dumped  # the excerpt never left the turn: not even the model's own copy of it is stored
    assert "外資把台積電目標價上調到 2,400 元。" in stored(engine, events[0][1]["id"])


def shown(events: list) -> str:
    """What the browser ends up showing: the text deltas, or the last text_reset and what followed it."""
    out = ""
    for n, d in events:
        if n == "text":
            out += d["delta"]
        elif n == "text_reset":
            out = d["text"]
    return out


def everywhere(engine, client, events, tid: str) -> str:
    """The SSE events, every stored row of the thread, the thread view and the recap a key move re-sends."""
    from forliosa.models import AiThread

    with Session(engine) as db:
        recap = store.recap_messages(db, db.get(AiThread, tid))
    return (json.dumps(events, ensure_ascii=False) + stored(engine, tid)
            + json.dumps(client.get(f"{API}/ai/threads/{tid}").json(), ensure_ascii=False)
            + json.dumps(recap, ensure_ascii=False))


def test_a_copy_of_the_excerpts_wording_is_never_shown_or_stored(client, pool, fake, langsearch, engine, ai_env):
    """2026-11-17 review: the excerpt run the model copied into its answer was streamed, stored as ai_messages.text,
    shown in the thread and re-sent in a recap. The answer is held after tw_news_search; the copy goes before anything
    is shown — the editor failing, a line that is only the paste, and the editor turned off."""
    ai_env(AI_ANSWER_EDITOR="true")
    langsearch(GOOD)
    fake.reply(tw_call(), stop_reason="tool_use")
    fake.reply(text("台積電：先進製程需求強勁，維持買進評等。", [location(URL, TITLE, SNIPPET)]))
    fake.error(500, "api_error", "editor down")  # shown as written: strip_pastes alone kept this copy
    _status, events = chat(client, "台積電有什麼消息？", page=PAGE)
    tid = events[0][1]["id"]
    assert shown(events) == COPY_REMOVED  # its one sentence was the copy: no fragment of it is shown
    assert EXCERPT_MARK not in everywhere(engine, client, events, tid)

    # a line that is only the paste, the editor off: held all the same, then released without it
    ai_env(AI_ANSWER_EDITOR="false")
    whole = "外資最新報告指出台積電先進製程需求強勁，維持買進評等，目標價上調至 2,400 元。"
    fake.reply(tw_call("toolu_tw2"), stop_reason="tool_use")
    fake.reply(text(f"外資把台積電目標價上調到 2,400 元。\n{whole}\n其他沒有新消息。", [location(URL, TITLE, SNIPPET)]))
    _status, events = chat(client, "台積電有什麼新消息？", page=PAGE)
    tid = events[0][1]["id"]
    assert shown(events) == "外資把台積電目標價上調到 2,400 元。\n其他沒有新消息。"
    assert EXCERPT_MARK not in everywhere(engine, client, events, tid)


def test_an_edit_that_keeps_the_copy_is_checked_before_it_is_shown(client, pool, fake, langsearch, engine, ai_env):
    ai_env(AI_ANSWER_EDITOR="true")
    langsearch(GOOD)
    fake.reply(tw_call(), stop_reason="tool_use")
    fake.reply(text("台積電：先進製程需求強勁，維持買進評等；目標價上調至 2,400 元。", [location(URL, TITLE, SNIPPET)]))
    fake.reply(text("台積電：先進製程需求強勁，維持買進評等。目標價上調到 2,400 元。"))  # the editor kept the copy
    _status, events = chat(client, "台積電有什麼消息？", page=PAGE)
    assert "text_reset" not in [n for n, _ in events]  # nothing of the edit was streamed before it was checked
    assert shown(events) == "目標價上調到 2,400 元。"  # the sentence that kept the copy goes whole
    assert EXCERPT_MARK not in everywhere(engine, client, events, events[0][1]["id"])
    # the editor was asked to rewrite the copy, marked, under the rule beside its prompt
    edit = fake.requests[-1]["body"]
    assert edit["system"].startswith(EDITOR_SYSTEM.split("\n只輸出改寫後的回答")[0])
    assert edit["system"].endswith(f"\n{EDITOR_COPIES}\n只輸出改寫後的回答，不加任何說明。")
    assert f"{COPY_OPEN}先進製程需求強勁，維持買進評等{COPY_CLOSE}" in edit["messages"][0]["content"]


def test_a_copy_is_dropped_by_whole_sentences_never_leaving_fragments(client, pool, fake, langsearch, engine, ai_env):
    """2026-11-17 live check (台積電最近有什麼新聞？): cutting only the copied words out of an edit that kept them
    showed 「-在論壇上表示，…」, 「…409.27 億美元，將」 and 「- 79%，其中…」. The sentence holding a copy goes whole;
    the other sentences and list items stay as they were; a list item left empty goes."""
    ai_env(AI_ANSWER_EDITOR="true")
    langsearch(reply(page(TITLE, URL, "台積電總裁致詞時強調供應鏈大同盟的重要性並呼籲夥伴一起投資在地產能。台積電董事會"
                                      "核准資本預算約409.27億美元將用於擴充先進製程產能與廠房建置")))
    draft = ("台積電 11/17 舉辦供應鏈論壇。\n\n"
             "- 總裁致詞時強調供應鏈大同盟的重要性並呼籲夥伴一起投資。另外談到在地採購。\n"
             "- 論壇聚焦 AI 技術合作。\n"
             "- 董事會 11/7 核准資本預算約 409.27 億美元，將用於擴充先進製程產能與廠房建置。\n"
             "- 2 奈米第 3 季占 8% 營收。")
    fake.reply(tw_call(), stop_reason="tool_use")
    fake.reply(text(draft, [location(URL, TITLE, "x")]))
    fake.reply(text(draft))  # the editor changed nothing
    _status, events = chat(client, "台積電最近有什麼新聞？", page=PAGE)
    assert shown(events) == ("台積電 11/17 舉辦供應鏈論壇。\n\n- 另外談到在地採購。\n- 論壇聚焦 AI 技術合作。\n"
                             "- 2 奈米第 3 季占 8% 營收。")
    tid = events[0][1]["id"]
    assert "大同盟" not in everywhere(engine, client, events, tid)
    assert "廠房建置" not in everywhere(engine, client, events, tid)

    # an editor that rewrote the marked copies in its own words: the whole answer is shown
    rewritten = ("台積電 11/17 舉辦供應鏈論壇。\n\n- 總裁在會中請供應商一起擴大在台投資。另外談到在地採購。\n"
                 "- 論壇聚焦 AI 技術合作。\n- 董事會 11/7 通過約 409.27 億美元的資本預算，用來蓋廠、擴充先進製程。\n"
                 "- 2 奈米第 3 季占 8% 營收。")
    fake.reply(tw_call("toolu_tw2"), stop_reason="tool_use")
    fake.reply(text(draft, [location(URL, TITLE, "x")]))
    fake.reply(text(rewritten.replace("總裁", f"{COPY_OPEN}總裁").replace("投資。", f"投資{COPY_CLOSE}。")))
    _status, events = chat(client, "台積電還有什麼新聞？", page=PAGE)
    assert shown(events) == rewritten  # a mark the editor left in is taken out


def test_restated_facts_are_kept_shown_stored_and_replayed(client, pool, fake, langsearch, engine):
    """2026-11-17 review: removing every 12-character overlap cut the model's own facts (a broker's rating and target)
    out of the stored turn, so a follow-up ran on an answer without them while the screen still showed them."""
    langsearch(GOOD)
    answer = "外資維持買進評等，目標價上調至 2,400 元（11/16）。"
    fake.reply(tw_call(intent="analyst_targets"), stop_reason="tool_use")
    fake.reply(text(answer, [location(URL, TITLE, SNIPPET)]))
    _status, events = chat(client, "台積電最新的目標價？", page=PAGE)
    tid = events[0][1]["id"]
    assert shown(events) == answer
    fake.reply(text("平均目標價要看各家的報告。"))
    chat(client, "那平均目標價呢？", thread_id=tid, page=PAGE)
    replayed = [b for m in fake.requests[-1]["body"]["messages"] if m["role"] == "assistant"
                for b in m["content"] if b.get("type") == "text"]
    assert [b["text"] for b in replayed] == [answer]  # the model's own words, as shown
    assert client.get(f"{API}/ai/threads/{tid}").json()["messages"][1]["text"] == answer


# -- 13. replaying the scrubbed history -------------------------------------------------------------
def test_replay_after_scrub_falls_back_to_recap(client, pool, fake, langsearch, engine):
    langsearch(GOOD)
    fake.reply(thinking("sig-1"), tw_call(), stop_reason="tool_use")
    fake.reply(thinking("sig-2"), text("外資看好需求。", [location(URL, TITLE, f"經濟日報，11/16：{SNIPPET}")]))
    tid = chat(client, "台積電有什麼消息？", page=PAGE)[1][0][1]["id"]
    fake.error(400, "invalid_request_error", "messages.2.content.0: Invalid `signature` in `thinking` block. The "
                                             "block is bound to a different conversation.").reply(text("好的。"))
    _status, events = chat(client, "那法說會呢？", thread_id=tid, page=PAGE)
    assert "error" not in [n for n, _ in events]
    replay, retry = fake.requests[-2]["body"], fake.requests[-1]["body"]
    assert EXCERPT_MARK not in json.dumps(replay, ensure_ascii=False)  # the scrubbed history, title lines only
    assert LINE in json.dumps(replay, ensure_ascii=False)
    assert [m["role"] for m in retry["messages"]] == ["user", "assistant", "user", "system"]  # the recap
    assert "sig-1" not in json.dumps(retry["messages"]) and EXCERPT_MARK not in json.dumps(retry, ensure_ascii=False)


# -- 14. logs ---------------------------------------------------------------------------------------
def test_no_text_in_logs(client, pool, fake, langsearch, caplog):
    langsearch(GOOD)
    fake.reply(tw_call(), stop_reason="tool_use")
    fake.reply(text("外資看好需求。", [location(URL, TITLE, f"經濟日報，11/16：{SNIPPET}")]))
    caplog.set_level(logging.INFO)  # the deployment's level (the SDK's own debug log holds every request body)
    caplog.set_level(logging.DEBUG, logger="forliosa")
    chat(client, "台積電有什麼消息？", page=PAGE)
    assert "tw_news_search: 1 requests" in caplog.text  # the turn's counts are logged
    for secret in (EXCERPT_MARK, KEY, "Authorization", "Bearer"):
        assert secret not in caplog.text, secret


# -- 15. 省錢模式 ---------------------------------------------------------------------------------------
def test_economy_notes(client, pool, fake, langsearch, monkeypatch):
    monkeypatch.setattr(store, "check_quota", lambda *a, **k: True)  # the month's budget is spent
    langsearch(reply(status=500))
    fake.reply(tw_call("t1"), tw_call("t2", symbol="AAPL"), tool_use("t3", "get_analyst_views", {"symbol": "2330"}),
               stop_reason="tool_use")
    fake.reply(tw_call("t4", intent="dividend"), stop_reason="tool_use")
    fake.reply(text("目前沒有這項資料。"))
    status, _events = chat(client, "台積電有什麼消息？", page=PAGE)
    assert status == 200
    body = fake.requests[-1]["body"]
    names = {t["name"] for t in body["tools"]}
    assert "tw_news_search" in names and not {"web_search", "web_fetch"} & names
    assert body["system"][0]["text"] == CHAT_SYSTEM_TW
    context = body["messages"][1]["content"]
    assert ECONOMY_NOTE_TW in context and "tw_news_search" in ECONOMY_NOTE_TW
    results = tool_results(body)
    assert len(results) == 4
    for r in results:
        assert "web_search" not in json.dumps(r, ensure_ascii=False), r
    assert "tw_news_search" in json.loads(results[2]["content"])["note"]  # the card points to the tool first


def test_without_the_economy_switch_the_tool_goes(client, pool, fake, langsearch, ai_env, monkeypatch):
    ai_env(AI_LANGSEARCH_IN_ECONOMY="false")
    monkeypatch.setattr(store, "check_quota", lambda *a, **k: True)
    fake.reply(text("好"))
    chat(client, "台積電有什麼消息？", page=PAGE)
    body = fake.requests[-1]["body"]
    assert "tw_news_search" not in {t["name"] for t in body["tools"]} and body["system"][0]["text"] == CHAT_SYSTEM
    assert ECONOMY_NOTE in body["messages"][1]["content"]


# -- the switch -------------------------------------------------------------------------------------
def test_switched_off_everything_is_as_before(client, pool, fake, monkeypatch):
    posted: list[Any] = []
    monkeypatch.setattr(ls.LangSearchClient, "from_settings", lambda settings: posted.append(1))
    fake.reply(tool_use("t1", "get_analyst_views", {"symbol": "2330"}), stop_reason="tool_use")
    fake.reply(text("好"))
    chat(client, "台積電的目標價？", page=PAGE)
    first = fake.requests[0]["body"]
    assert first["system"][0]["text"] == CHAT_SYSTEM and "tw_news_search" not in {t["name"] for t in first["tools"]}
    assert all(t.get("strict") is True for t in first["tools"] if "input_schema" in t and t["name"] not in NOT_STRICT)
    note = json.loads(tool_results(fake.requests[1]["body"])[0]["content"])["note"]
    assert note == tools_mod._ANALYST_NOTES["none"] and posted == []


def test_deep_search_is_left_as_it_was(client, pool, fake, langsearch):
    fake.reply(text("好"))
    chat(client, "深入研究台積電", page=PAGE, mode="deep")
    body = fake.requests[-1]["body"]
    assert "tw_news_search" not in {t["name"] for t in body["tools"]} and body["system"][0]["text"] == CHAT_SYSTEM


def test_the_card_points_to_the_tool(client, pool, fake, langsearch):
    fake.reply(tool_use("t1", "get_analyst_views", {"symbol": "2330"}),
               tool_use("t2", "get_analyst_views", {"symbol": "AAPL"}), stop_reason="tool_use")
    fake.reply(text("好"))
    chat(client, "台積電和蘋果的目標價？", page=PAGE)
    notes = [json.loads(r["content"])["note"] for r in tool_results(fake.requests[1]["body"])]
    assert "tw_news_search（intent analyst_targets）" in notes[0] and "web_search" in notes[0]
    assert notes[1] == tools_mod._ANALYST_NOTES["none"]  # a US stock: the web, as before


# -- the manual live check (its code path, on fakes) ------------------------------------------------------------
def test_smoke_tw_news_prints_counts_only(client, pool, fake, langsearch, engine, capsys):
    from forliosa.ai.smoke import check_tw_news
    from forliosa.config import get_settings
    from forliosa.marketdata.service import get_market_data
    from forliosa.models import User
    from tests.ai.fake_anthropic import Reply

    def responder(body: dict) -> Reply:
        last = [m for m in body["messages"] if m["role"] == "user"][-1]
        results = [b for b in last["content"] if isinstance(b, dict) and b.get("type") == "tool_result"] \
            if isinstance(last["content"], list) else []
        if not results:
            return Reply([tw_call(f"toolu_{len(fake.requests)}")], "tool_use")
        found = results[0]["content"] if isinstance(results[0]["content"], list) else []
        cites = [location(found[0]["source"], found[0]["title"], found[0]["content"][0]["text"])] if found else []
        return Reply([text("外資看好需求。", cites)])

    fake.responder = responder
    with Session(engine) as db:
        user = db.scalar(select(User).where(User.email == "demo@forliosa.local"))
        assert check_tw_news(db, user, get_market_data(), pool, get_settings()) == 0
    out = capsys.readouterr().out
    assert out.count("✓") == 4 and "含摘錄的引用 0 個" in out
    assert EXCERPT_MARK not in out and TITLE not in out and KEY not in out
