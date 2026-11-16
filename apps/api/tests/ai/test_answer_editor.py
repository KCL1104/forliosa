"""產品負責人 2026-11-15: an answer built on web search or the news tool is rewritten once by an editor call before it
is shown (copied source sentences, outlet names, tool talk). Measured on 11 questions: slop 1.5 -> 0.5 a question."""

from __future__ import annotations

from datetime import date

import pytest
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
    """What the browser shows: ``text`` deltas appended, a ``text_reset`` (the streamed edit was dropped) replacing
    them."""
    out = ""
    for n, d in events:
        if n == "text":
            out += d["delta"]
        elif n == "text_reset":
            out = d["text"]
    return out


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


def test_the_number_check_allows_years_codes_and_rounded_or_rescaled_duplicates():
    assert keeps_numbers("聯發科（2454.TW）2026年11月13日漲停，升7%，收漲 7.01%", "聯發科 11/13 漲停，收漲 7.01%")
    assert keeps_numbers("將於 115 年 12 月 21 日下市；2026/11/04 融資 3.51 萬張", "12/21 下市；11/4 融資 35,144 張")
    assert keeps_numbers("4 月營收 46,736,664 千元", "4 月營收 467.37 億元")
    assert not keeps_numbers("目標價 400 元，日系 320 元", "目標價 400 元")  # a different number is not a rounding


def test_links_and_leaked_source_indexes_are_not_facts_the_editor_must_keep():
    """2026-11-16 effort A/B: edits that removed a pasted link or 「8-1 來源」 were reverted to the worse draft."""
    from forliosa.ai.chat import keeps_numbers, missing_numbers

    draft = ("台達電今天跌 9.7%，見[新聞](https://www.businesstoday.com.tw/article/2026/11/16/202611160123)。"
             "這是 8-1 來源所寫的數字。")
    edited = "台達電今天跌 9.7%。"
    assert keeps_numbers(draft, edited)
    assert missing_numbers("看 https://news.cnyes.com/news/id/6200001 與來源 3，台達電跌 9.7%", "台達電跌 9.7%") == []
    # a real figure outside the link still counts
    assert missing_numbers("台達電跌 9.7%，外資賣超 1,411 張，見 https://x.tw/a/1411", "台達電跌 9.7%") == ["1411"]


# -- 2026-11-16, 禾榮科: 「另有一則目標價 1,418 元的說法…因此不採用」, 「115 年第 3 季」, 「2026/10/02」 --------
VETTED = ("元富投顧 10/2 給目標價 700 元。"
          "另有一則目標價 1,418 元的說法，來源是 AI 生成的整理頁面，出處與日期都不明，因此不採用。")


def test_a_sentence_about_a_source_left_out_may_go_with_its_numbers():
    from forliosa.ai.chat import missing_numbers

    assert keeps_numbers(VETTED, "元富投顧 10/2 給目標價 700 元。")
    assert keeps_numbers("- 元富 700 元。\n- 網路上的 AI 整理頁提到富邦 1,418 元，但無法確認原始報告，因此不採用。",
                         "- 元富 700 元。")
    # the rest of the answer still counts: dropping the quoted target is caught
    assert missing_numbers(VETTED, "另有一則說法不採用。") == ["10", "2", "700"]
    # a number of the vetting sentence that is also elsewhere in the draft still counts
    assert missing_numbers("富邦 1,418 元。另有 1,418 元的說法，來源不明，因此不採用。", "富邦。") == ["1418"]


@pytest.mark.parametrize(("draft", "fixed"), [
    ("11/11 公告 115 年第 3 季每股虧損 0.74 元。", "11/11 公告 第 3 季每股虧損 0.74 元。"),
    ("元富投顧 2026/10/02 發布報告", "元富投顧 10/2 發布報告"),
    ("2025/10/02 的報告", "2025/10/2 的報告"),
    ("115 年 12 月 21 日下市", "12/21 下市"), ("115年12月21日下市", "12/21 下市"), ("115/12/21 下市", "12/21 下市"),
    ("2026年11月12日起", "11/12 起"), ("2026-10-02 發布", "10/2 發布"), ("114 年度第 4 季", "2025 年第 4 季"),
    ("115年10月營收 198 萬元", "10 月營收 198 萬元"), ("114年10月營收", "2025 年 10 月營收"),
    ("115 年前三季", "前三季"), ("10/02 發布", "10/2 發布"),
    # not dates, or already written the prompt's way: unchanged
    ("20日均線", "20日均線"), ("增資上限 5600 萬", "增資上限 5600 萬"), ("台積電 2330", "台積電 2330"),
    ("目標價 1,418 元", "目標價 1,418 元"), ("11/13 收 478 元", "11/13 收 478 元"), ("2026/11 營收", "2026/11 營收"),
    ("09:59 跌 2%", "09:59 跌 2%"), ("1/2 的股份", "1/2 的股份"), ("成立 115 年", "成立 115 年"),
    # links are left as they are
    ("見 https://x.tw/2026/10/02/a 與 [新聞](https://y.tw/2026/10/02)",
     "見 https://x.tw/2026/10/02/a 與 [新聞](https://y.tw/2026/10/02)"),
])
def test_dates_are_written_the_prompts_way(draft, fixed):
    from forliosa.ai.chat import normalize_dates

    assert normalize_dates(draft, date(2026, 11, 16)) == fixed
    assert keeps_numbers(draft, fixed, date(2026, 11, 16))


def test_the_year_decides_whether_a_date_keeps_it():
    from forliosa.ai.chat import normalize_dates

    assert normalize_dates("2026/12/28 調升，115 年第 4 季", date(2027, 1, 5)) == "2026/12/28 調升，2026 年第 4 季"


def date_turn(fake, draft: str) -> None:
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "禾榮科 目標價"}),
               web_search_result("srvtoolu_1", [{"url": "https://news.cnyes.com/a", "title": "鉅亨",
                                                 "encrypted_content": "ENC"}]),
               text(draft, [search_citation("https://news.cnyes.com/a", "鉅亨", "目標價 700")]),
               usage={"server_tool_use": {"web_search_requests": 1}})


def test_the_draft_dates_are_fixed_for_the_editor_and_when_its_edit_is_dropped(client, pool, fake, ai_env):
    from forliosa.timeutil import today_taipei

    ai_env(AI_ANSWER_EDITOR="true")
    year = today_taipei().year
    draft = f"元富投顧 {year}/10/02 給目標價 700 元。{year - 1911} 年第 3 季每股虧損 0.74 元。"
    fixed = "元富投顧 10/2 給目標價 700 元。第 3 季每股虧損 0.74 元。"
    date_turn(fake, draft)
    fake.error(500, "api_error", "editor down")
    _, events = chat(client, "禾榮科的目標價？")
    assert shown(events) == fixed  # the answer as written, with the dates fixed
    date_turn(fake, draft)
    fake.reply(text(fixed))
    _, events = chat(client, "禾榮科的目標價？")
    assert fake.requests[-1]["body"]["messages"][0]["content"] == fixed and shown(events) == fixed


def test_an_edit_that_drops_a_vetting_sentence_is_kept(client, pool, fake, ai_env):
    ai_env(AI_ANSWER_EDITOR="true")
    date_turn(fake, VETTED)
    fake.reply(text("元富投顧 10/2 給目標價 700 元。"))
    _, events = chat(client, "禾榮科的目標價？")
    assert shown(events) == "元富投顧 10/2 給目標價 700 元。"
    assert not [n for n, _ in events if n == "text_reset"]
