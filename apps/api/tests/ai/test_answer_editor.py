"""產品負責人 2026-11-15: an answer built on web search or the news tool is rewritten once by an editor call before it
is shown (copied source sentences, outlet names, tool talk). Measured on 11 questions: slop 1.5 -> 0.5 a question."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.ai.chat import keeps_numbers, remap_flags
from forliosa.config import Settings
from forliosa.models import AiMessage, AiUsage
from tests.ai.conftest import chat
from tests.ai.fake_anthropic import search_citation, server_tool_use, text, web_search_result

DRAFT = "台積電 11/13 收 2,350 元，漲 0.43%。據鉅亨網報導，台積電(2330)最後一盤丟出4061張砍單。"
EDITED = "台積電 11/13 收 2350 元，漲 0.43%。尾盤有 4061 張賣單，漲幅收小。"


def web_turn(fake):
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "台積電 11/13"}),
               web_search_result("srvtoolu_1", [{"url": "https://news.cnyes.com/a", "title": "鉅亨",
                                                 "encrypted_content": "ENC"}]),
               text(DRAFT, [search_citation("https://news.cnyes.com/a", "鉅亨", "最後一盤丟出4061張砍單")]),
               usage={"server_tool_use": {"web_search_requests": 1}})


def shown(events) -> str:
    return "".join(d["delta"] for n, d in events if n == "text")


def test_the_default_is_on(monkeypatch):
    monkeypatch.delenv("AI_ANSWER_EDITOR", raising=False)
    assert Settings(_env_file=None).ai_answer_editor is True


def test_a_web_answer_is_edited_before_it_is_shown(client, pool, fake, engine, ai_env):
    ai_env(AI_ANSWER_EDITOR="true")
    web_turn(fake)
    fake.reply(text(EDITED))
    status, events = chat(client, "台積電今天怎麼了？", page={"route": "/stock/2330.TW", "symbol": "2330.TW"})
    assert status == 200
    # the draft is never streamed; a step 「整理回答」 runs, then the edited answer streams
    assert shown(events) == EDITED and "鉅亨網" not in shown(events)
    steps = [(d["name"], d["status"], d["label"]) for n, d in events if n == "tool" and d["name"] == "edit_answer"]
    assert steps == [("edit_answer", "running", "整理回答"), ("edit_answer", "done", "整理回答")]
    assert [n for n, _ in events if n == "citation"]  # the footnotes stay
    # the editor call: no tools, the editor prompt, the draft as the user message
    body = fake.requests[1]["body"]
    assert "tools" not in body and "文字編輯" in body["system"] and body["messages"][0]["content"] == DRAFT
    with Session(engine) as db:
        ai = db.scalars(select(AiMessage).where(AiMessage.role == "assistant")).all()[-1]
        assert ai.text == EDITED  # the edited answer is what the thread keeps
        assert db.scalar(select(AiUsage).order_by(AiUsage.id.desc()).limit(1)).feature == "chat"  # charged as chat


def test_the_draft_is_shown_when_the_editor_fails_or_drops_a_number(client, pool, fake, ai_env):
    ai_env(AI_ANSWER_EDITOR="true")
    web_turn(fake)
    fake.error(500, "api_error", "editor down")
    _, events = chat(client, "台積電今天怎麼了？")
    assert shown(events) == DRAFT and not [n for n, d in events if n == "error"]
    web_turn(fake)
    fake.reply(text("台積電 11/13 收高，尾盤有賣壓。"))  # 2350, 0.43 and 4061 are gone
    _, events = chat(client, "台積電今天怎麼了？")
    assert shown(events) == DRAFT


def test_answers_without_web_search_are_not_edited(client, pool, fake, ai_env):
    ai_env(AI_ANSWER_EDITOR="true")
    fake.reply(text("你持有台積電 1 張。"))
    _, events = chat(client, "我有哪些持股？")
    assert shown(events) == "你持有台積電 1 張。" and len(fake.requests) == 1
    assert not [d for n, d in events if n == "tool" and d["name"] == "edit_answer"]


def test_off_switch(client, pool, fake, ai_env):
    ai_env(AI_ANSWER_EDITOR="false")
    web_turn(fake)
    _, events = chat(client, "台積電今天怎麼了？")
    assert shown(events) == DRAFT and len(fake.requests) == 1


def test_numbers_and_flag_remapping():
    assert keeps_numbers("收 2,350 元，漲 0.43%", "漲 0.43%，收 2350 元")
    assert not keeps_numbers("收 2,350 元，漲 0.43%", "收 2350 元")
    assert keeps_numbers("台積電(2330)收 2,350 元", "台積電收 2350 元")  # the copied 「名稱(代號)」 may go
    draft = "台積電漲。公司宣布 11/20 召開法說會，鉅亨網報導。"
    final = "台積電漲。公司宣布 11/20 召開法說會。"
    start = 10  # the edited part starts after 10 characters of streamed text
    flags = [{"index": 1, "start": start + 5, "end": start + 24, "text": "公司宣布 11/20 召開法說會，鉅亨網報導。",
              "reason": "x"},
             {"index": 0, "start": 2, "end": 6, "text": "前面的", "reason": "x"},
             {"index": 2, "start": start + 30, "end": start + 34, "text": "完全不一樣的一句話", "reason": "x"}]
    out = remap_flags(flags, draft, final, start)
    assert out[0]["text"] == "公司宣布 11/20 召開法說會。" and out[0]["start"] == start + 5
    assert out[1]["text"] == "前面的"  # before the edited part: unchanged
    assert len(out) == 2  # no close match: left out
