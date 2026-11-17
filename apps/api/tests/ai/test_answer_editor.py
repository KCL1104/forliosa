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


def test_the_editor_call_holds_no_pooled_connection(client, pool, fake, engine, ai_env, monkeypatch):
    """Like the answer's own model calls, the editor's stream starts with the turn's connection back in the pool, even
    when the turn read the database just before it."""
    from forliosa.ai.chat import ChatTurn

    real_editor = ChatTurn._editor_stream

    def read_first(self, thread, body, **kw):  # ``copies=`` since the LangSearch merge (7cc1a1e)
        self.db.scalar(select(AiMessage.id).limit(1))  # opens a read transaction on the turn's session
        return real_editor(self, thread, body, **kw)

    monkeypatch.setattr(ChatTurn, "_editor_stream", read_first)
    ai_env(AI_ANSWER_EDITOR="true")
    web_turn(fake)
    fake.reply(text(EDITED))
    replies, checked_out = list(fake.script), []
    fake.script.clear()

    def respond(_body):
        checked_out.append(engine.pool.checkedout())
        return replies.pop(0)

    fake.responder = respond
    status, events = chat(client, "台積電今天怎麼了？", page={"route": "/stock/2330.TW", "symbol": "2330.TW"})
    assert status == 200 and shown(events) == EDITED
    assert checked_out == [0, 0]  # the answer, then the editor


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
    # the space before a year that goes goes with it (2026-11-16: 「通過 第 3 季」 when the edit was dropped)
    ("11/11 公告 115 年第 3 季每股虧損 0.74 元。", "11/11 公告第 3 季每股虧損 0.74 元。"),
    ("董事會通過 115 年第 3 季合併財務報告", "董事會通過第 3 季合併財務報告"), ("- 115 年第 3 季虧損", "- 第 3 季虧損"),
    ("Q3 115 年第 3 季", "Q3 第 3 季"),
    # 「10 月 15 日」 is this year's 10/15 (the editor wrote it so); with a year, the year stays when it is not this one
    ("以上都是 10 月 15 日法說會之前的目標價", "以上都是 10/15 法說會之前的目標價"), ("10月15日", "10/15"),
    ("2025 年 10 月 15 日的報告", "2025/10/15 的報告"), ("2026 年 10 月 15 日的報告", "10/15 的報告"),
    ("10月6日至10月7日調升", "10/6 至 10/7 調升"),
    ("1999 年 10 月 15 日成立", "1999 年 10 月 15 日成立"), ("每年 10 月 15 日", "每年 10 月 15 日"),
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


# -- 2026-11-16, round 2: edits dropped for pasted source text, 「不列入」 and report dates; an invented unit ---------
TODAY = date(2026, 11, 16)
PASTED = "公司公告，11/10 15:02：本公司受邀參加永豐金證券匯立分公司舉辦之法人說明會"
OWN = "- 11/10 公告受邀參加永豐金證券匯立分公司的法人說明會，11/12 參加。"


def test_numbers_of_source_text_pasted_after_the_lines_own_words_may_go():
    from forliosa.ai.chat import copied_spans, missing_numbers

    draft = f"{OWN}{PASTED}\n- 11/11 董事會通過第 3 季財報。"
    edited = f"{OWN}\n- 11/11 董事會通過第 3 季財報。"
    assert missing_numbers(draft, edited, TODAY) == ["02", "15"]  # round 1: the edit was dropped for the 15:02
    assert missing_numbers(draft, edited, TODAY, [PASTED]) == []
    assert copied_spans(draft, [PASTED]) == [(len(OWN), len(OWN) + len(PASTED))]
    # the line's own numbers still count
    assert missing_numbers(draft, edited.replace("11/12 ", ""), TODAY, [PASTED]) == ["12"]
    # a short match is not a paste
    assert copied_spans("董事會通過財報", ["董事會通過財報"]) == []


def test_a_line_that_is_only_a_paste_keeps_its_facts():
    from forliosa.ai.chat import missing_numbers

    src = "公司公告，11/10 15:02：10 月營收 197.7 萬元，年增 42.23%"
    draft = f"- 11/10 公告營收。\n- {src}"
    # its date and time may go, the facts written only there may not
    assert missing_numbers(draft, "- 11/10 公告營收。\n- 10 月營收 197.7 萬元。", TODAY, [src]) == ["42.23"]
    assert missing_numbers(draft, "- 11/10 公告營收。\n- 10 月營收 197.7 萬元，年增 42.23%。", TODAY, [src]) == []


@pytest.mark.parametrize("sentence", [
    "另有一家澳系外資喊 4,410 元，但報導沒寫機構名稱，所以不列入。", "一家未具名外資喊 4,410 元。",
    "4,410 元的說法不計入。", "澳系外資 4,410 元的報告沒有寫出機構名稱。",
])
def test_more_vetting_sentences_may_go_with_their_numbers(sentence):
    from forliosa.ai.chat import missing_numbers

    assert missing_numbers("滙豐 10/14 調到 3,800 元。" + sentence, "滙豐 10/14 調到 3,800 元。") == []


def test_the_rating_criteria_may_go_with_their_90():
    from forliosa.ai.chat import missing_numbers

    assert keeps_numbers("目前沒有禾榮科近 90 天內具名機構的評等與目標價資料。",
                         "目前沒有禾榮科機構評等與目標價的資料。")
    assert keeps_numbers("近 90 天內，具名外資的目標價多在 3,000 元以上。", "外資的目標價多在 3,000 元以上。")
    assert missing_numbers("台積電近 90 天漲 30%。", "台積電漲 30%。") == ["90"]  # the period of a fact is a fact


def test_a_report_date_counts_unless_the_edit_writes_it():
    from forliosa.ai.chat import missing_numbers

    draft = "- 外資持續賣超（11/15 報導）。"
    assert keeps_numbers(draft, "- 外資 11/15 持續賣超。", TODAY)
    assert keeps_numbers(draft, "- 外資 11 月 15 日持續賣超。", TODAY)
    assert keeps_numbers(draft, "- 外資昨天持續賣超。", TODAY)  # today is 11/16
    assert missing_numbers(draft, "- 外資持續賣超。", TODAY) == ["11", "15"]  # dropped with the 「報導」: caught


def test_an_edit_that_gives_a_number_a_scale_is_caught():
    from forliosa.ai.chat import added_scales

    draft = "10 月營收 197.7 萬元，年增 42.23%；本年累計6,806去年累計6,916，年減 1.59%。"
    assert added_scales(draft, "前十個月累計 6,806 萬元，去年同期為 6,916 萬元。") == ["6,806 萬", "6,916 萬"]
    assert added_scales(draft, "10 月營收 197.7 萬元，前十個月累計 6,806，去年同期 6,916。") == []
    assert added_scales("累計 6,806 千元", "累計 6,806 萬元") == ["6,806 萬"]  # 千 is not 萬
    assert added_scales("累計 6,806 仟元", "累計 6,806 千元") == []  # 仟 is 千
    assert added_scales("累計 6,806 千元", "累計 680.6 萬元") == []  # rescaled: a new number (the number check sees it)
    # a table's unit is in its header
    assert added_scales("| 營收（萬元） |\n|---|\n| 197.7 |", "營收 197.7 萬元") == []
    assert added_scales("增資上限 5600 萬", "增資上限 5,600 萬元") == []


def test_mops_boilerplate_and_the_site_before_a_notice_are_taken_out():
    from forliosa.ai.chat import strip_boilerplate

    footer = "完整財務業務資訊請至公開資訊觀測站之法人說明會一覽表或法說會項目下查閱。"
    assert strip_boilerplate(f"- 11/12 受邀參加法說會。{footer}") == "- 11/12 受邀參加法說會。"
    assert strip_boilerplate(f"11/12 受邀參加法說會，{footer}") == "11/12 受邀參加法說會。"
    assert strip_boilerplate("- 11/10 公告。\n- 詳細內容請至公開資訊觀測站查詢。\n- 11/11 公告。") == \
        "- 11/10 公告。\n- 11/11 公告。"
    assert strip_boilerplate("11/10 到 11/11 共有四則公開資訊觀測站公告：") == "11/10 到 11/11 共有四則公告："
    assert strip_boilerplate("公司在公開資訊觀測站公告增資") == "公司公告增資"
    assert strip_boilerplate("公開資訊觀測站顯示") == "公開資訊觀測站顯示"  # the rest is the editor's


def stored_answer(engine) -> str:
    with Session(engine) as db:
        return db.scalars(select(AiMessage).where(AiMessage.role == "assistant")).all()[-1].text


def cited_turn(fake, *blocks) -> None:
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "禾榮科 公告"}),
               web_search_result("srvtoolu_1", [{"url": "https://news.cnyes.com/a", "title": "鉅亨",
                                                 "encrypted_content": "ENC"}]),
               *blocks, usage={"server_tool_use": {"web_search_requests": 1}})


def test_an_edit_that_drops_pasted_source_text_is_kept(client, pool, fake, ai_env):
    ai_env(AI_ANSWER_EDITOR="true")
    cite = search_citation("https://news.cnyes.com/a", "鉅亨", PASTED)
    cited_turn(fake, text(OWN, [cite]), text(PASTED, [cite]))
    fake.reply(text(OWN))
    _, events = chat(client, "禾榮科最近有什麼消息？")
    assert shown(events) == OWN and not [n for n, _ in events if n == "text_reset"]


def test_the_edit_gets_its_dates_fixed_and_boilerplate_dropped_too(client, pool, fake, engine, ai_env):
    """2026-11-16: the editor wrote 「10 月 15 日」 itself, after the draft's dates had been fixed."""
    ai_env(AI_ANSWER_EDITOR="true")
    date_turn(fake, "元富投顧 10/15 給目標價 700 元。")
    fake.reply(text("元富投顧 10 月 15 日給目標價 700 元。完整財務業務資訊請至公開資訊觀測站查閱。"))
    _, events = chat(client, "禾榮科的目標價？")
    fixed = "元富投顧 10/15 給目標價 700 元。"
    assert shown(events) == fixed and stored_answer(engine) == fixed
    assert [n for n, _ in events if n == "text_reset"] == ["text_reset"]  # the streamed edit is replaced once


def test_an_edit_that_invents_a_unit_is_dropped(client, pool, fake, ai_env):
    ai_env(AI_ANSWER_EDITOR="true")
    draft = "10 月營收 197.7 萬元，本年累計6,806去年累計6,916。"
    date_turn(fake, draft)
    fake.reply(text("10 月營收 197.7 萬元，前十個月累計 6,806 萬元，去年同期 6,916 萬元。"))
    _, events = chat(client, "禾榮科的營收？")
    assert shown(events) == draft


def test_the_prompts_carry_units_recency_and_no_source_names_for_notices():
    from forliosa.ai.prompts import CHAT_SYSTEM, EDITOR_SYSTEM

    section = CHAT_SYSTEM[CHAT_SYSTEM.index("## 機構評等與目標價"):CHAT_SYSTEM.index("## 技術分析與盤中價格")]
    for phrase in (
        # recency: the month in the query, the newest of each institution
        "「名稱 目標價 ○年○月」（○年○月 是「頁面情境」裡今天的年月）", "「名稱 外資 目標價 最新」",
        "找到的都是一個月以前的，換關鍵字再搜一次最新的", "同一家機構有好幾則時只寫最新的一則",
        # no 「所以不列入」, no criteria
        "也不說哪一家沒列入", "所以不列入」整句都不寫", "回答裡不出現「具名」「未具名」「近 90 天」「半年內」這類字",
        "不寫「最新的具名目標價」，寫「最新的目標價」",
        "不加條件（不寫「目前沒有近 90 天內具名機構的…」）",
    ):
        assert phrase in section, phrase
    for phrase in (
        "哪一則「不列入」，也不寫篩選的條件（「近 90 天內」「具名機構」）",
        # units from the source
        "數字的單位照來源寫：來源標示「單位：仟元」「千元」時，寫「6,806 千元」，或正確換算成「680.6 萬元」",
        "看不出單位的數字不寫，也不要自己補上單位",
        # no pasted tool text, no site names for a 公告, no boilerplate, report dates in the sentence
        "工具結果每一則開頭的「公司公告，11/10 15:02：」「鉅亨網，今天 09:12：」是給你看的出處與時間，不要抄進回答",
        "公告也一樣不寫網站名稱：寫「11/11 公告…」", "不寫「共有四則公開資訊觀測站公告」",
        "「完整財務業務資訊請至公開資訊觀測站…查閱」", "「10 月 15 日」", "不寫成「（10/14 報導）」",
    ):
        assert phrase in CHAT_SYSTEM, phrase
    for phrase in (
        "數字的單位照原稿：不新增、不更改單位或位數（千、萬、億、元、張、股、%），也不自己換算",
        "原稿的數字沒有單位，就照樣不寫單位（「本年累計6,806」不可寫成「6,806 萬元」）",
        "原稿寫「千元」就寫「千元」，不改成「萬元」",
        "「（11/15 報導）」「（約 10/9 報導）」這類括號拿掉時，日期一定要留下，寫進句子",
        "「公開資訊觀測站」也是網站名稱（「四則公開資訊觀測站公告」寫成「四則公告」）",
        "叫人去網站查閱的句子（「完整財務業務資訊請至公開資訊觀測站…查閱」）刪掉",
        # 2026-11-16 A/B: with 「公告與報導的制式文字…整句刪掉」 the edit dropped the opening sentence in 7 of 8
        "原文條列前的第一句要留在最前面，不要刪掉，也不要改成條列",
        "不採用、不列入、不可信", "所以不列入」", "「目前沒有機構評等與目標價的資料」",
    ):
        assert phrase in EDITOR_SYSTEM, phrase


def test_a_paste_with_spaces_and_a_number_in_chinese_still_match():
    """2026-11-16 round 2 live: 「…公告本公司董事會通過第 3 季合併財務報告」 (the cited 「第3季」 with spaces) and
    an edit that wrote 「第三季」 was dropped for the 3."""
    from forliosa.ai.chat import copied_spans, missing_numbers

    src = "公司公告，11/11 16:30：公告本公司董事會通過第3季合併財務報告"
    draft = "- 第三季合併財務報告已由董事會通過，公告本公司董事會通過第 3 季合併財務報告。"
    a = draft.index("公告本公司")
    assert copied_spans(draft, [src]) == [(a, len(draft) - 1)]
    assert missing_numbers(draft, "- 第三季合併財務報告已由董事會通過。", TODAY, [src]) == []
    assert keeps_numbers("前 10 個月累計 6,806 千元，第 3 季虧損", "前十個月累計 6,806 千元，第三季虧損")
    assert not keeps_numbers("第 3 季虧損 0.74 元", "第二季虧損 0.74 元")


@pytest.mark.parametrize(("draft", "fixed"), [
    # the label of a pasted 公告 item goes; its date stays unless the line has it (then its clock time goes too)
    ("- 11/10 公告受邀參加法說會。公開資訊觀測站，11/10 15:02：本公司受邀參加法說會",
     "- 11/10 公告受邀參加法說會。本公司受邀參加法說會"),
    ("- 董事會通過財報。公司公告，11/11 16:30：公告本公司董事會通過第3季合併財務報告",
     "- 董事會通過財報。11/11 16:30 公告本公司董事會通過第3季合併財務報告"),
    ("- 公司公告，今天 11/16 09:12：本公司董事會決議", "- 今天 11/16 09:12 本公司董事會決議"),
])
def test_a_pasted_notice_label_goes(draft, fixed):
    from forliosa.ai.chat import tidy_answer

    assert tidy_answer(draft, TODAY) == fixed
    assert keeps_numbers(draft, fixed, TODAY) or "15:02" in draft



# -- 2026-11-16, round 3 leftovers: the opening sentence, the rating rule's screening words ------------------------
@pytest.mark.parametrize(("draft", "edited", "kept"), [
    # the opening made a list item: back to a sentence, the rest of the list after a blank line
    ("台達電今天跌停，收 1,120 元。\n\n- 外資賣超。", "- 台達電今天跌停，收在 1,120 元。\n- 外資賣超。",
     "台達電今天跌停，收在 1,120 元。\n\n- 外資賣超。"),
    # the opening dropped and its fact folded into an item: the draft's first sentence comes back before the list
    ("台積電最新的目標價是小摩 11/12 的 3,300 元。其餘是法說會前後的報告。\n\n- 滙豐 10/14 調高到 3,800 元。",
     "- 滙豐 10/14 把目標價調高到 3,800 元。\n- 小摩 11/12 維持 3,300 元。",
     "台積電最新的目標價是小摩 11/12 的 3,300 元。\n\n- 滙豐 10/14 把目標價調高到 3,800 元。\n"
     "- 小摩 11/12 維持 3,300 元。"),
    # nothing to restore: the edit opens with a sentence, or the draft opened with a list itself
    ("台達電跌停。\n\n- 外資賣超。", "台達電今天跌停。\n\n- 外資賣超。", "台達電今天跌停。\n\n- 外資賣超。"),
    ("- 台達電跌停。\n- 外資賣超。", "- 台達電今天跌停。\n- 外資賣超。", "- 台達電今天跌停。\n- 外資賣超。"),
    ("### 重點\n台達電跌停。", "- 台達電跌停。", "- 台達電跌停。"),
    # the opening dropped and the edit's first item is the draft's first item (2026-11-16 review): the item stays
    # in the list, the opening comes back
    ("台積電最新的目標價是摩根大通 11/12 的 3,300 元。\n\n- 摩根大通 11/12 維持「優於大盤」評等，目標價 3,300 元。\n"
     "- 伯恩斯坦 11/9 調升，目標價 3,828 元。",
     "- 摩根大通 11/12 維持「優於大盤」評等，目標價 3,300 元。\n- 伯恩斯坦 11/9 調升，目標價 3,828 元。",
     "台積電最新的目標價是摩根大通 11/12 的 3,300 元。\n\n- 摩根大通 11/12 維持「優於大盤」評等，目標價 3,300 元。\n"
     "- 伯恩斯坦 11/9 調升，目標價 3,828 元。"),
    # the opening moved to the end: moved back, not written twice
    ("禾榮科目前沒有機構評等與目標價的資料。\n\n- 公司 11/10 參加永豐金證券舉辦的法說會。",
     "- 公司 11/10 參加永豐金證券舉辦的法說會。\n\n目前沒有禾榮科的機構評等與目標價資料。",
     "目前沒有禾榮科的機構評等與目標價資料。\n\n- 公司 11/10 參加永豐金證券舉辦的法說會。"),
])
def test_the_opening_sentence_stays_a_sentence(draft, edited, kept):
    from forliosa.ai.chat import keep_opening

    assert keep_opening(draft, edited) == kept


def test_an_edit_that_lists_the_opening_is_shown_with_its_sentence_back(client, pool, fake, engine, ai_env):
    ai_env(AI_ANSWER_EDITOR="true")
    date_turn(fake, "元富投顧 10/2 給目標價 700 元。\n\n- 國票投顧 10/1 評等「區間操作」。")
    fake.reply(text("- 元富投顧 10/2 給的目標價是 700 元。\n- 國票投顧 10/1 評等「區間操作」。"))
    _, events = chat(client, "禾榮科的目標價？")
    fixed = "元富投顧 10/2 給的目標價是 700 元。\n\n- 國票投顧 10/1 評等「區間操作」。"
    assert shown(events) == fixed and stored_answer(engine) == fixed
    assert [n for n, _ in events if n == "text_reset"] == ["text_reset"]  # the streamed edit is replaced once


@pytest.mark.parametrize(("text_in", "text_out"), [
    ("台積電最新的具名目標價是小摩的 3,300 元。", "台積電最新的目標價是小摩的 3,300 元。"),
    ("台積電最新一筆具名機構的目標價是小摩的 3,300 元。", "台積電最新一筆機構的目標價是小摩的 3,300 元。"),
    ("近 90 天內，具名外資的目標價最高 4,410 元。", "外資的目標價最高 4,410 元。"),
    ("目前沒有近 90 天內具名機構的評等與目標價資料。", "目前沒有機構的評等與目標價資料。"),
    ("目前沒有近 90 天的機構評等。", "目前沒有機構評等。"),
    # not the rating rule's words
    ("近 90 天外資買超 1 萬張。", "近 90 天外資買超 1 萬張。"),
    ("一家未具名的日系外資調降目標價。", "一家未具名的日系外資調降目標價。"),
    # news wording about anonymity (2026-11-16 review: 「不願具名的外資分析師」 had become 「不願外資分析師」)
    ("一位不願具名的外資分析師表示，需求強勁。", "一位不願具名的外資分析師表示，需求強勁。"),
    ("據非具名的法人透露，營收將成長。", "據非具名的法人透露，營收將成長。"),
    ("要求不具名的券商主管說，市場過熱。", "要求不具名的券商主管說，市場過熱。"),
    # without 「具名」 the sentence would contradict its second half
    ("目前沒有具名的機構評等，只有一家日系外資調降目標價。", "目前沒有具名的機構評等，只有一家日系外資調降目標價。"),
    ("目前沒有具名機構的評等與目標價資料。", "目前沒有機構的評等與目標價資料。"),
])
def test_the_rating_rules_screening_words_go(text_in, text_out):
    from forliosa.ai.chat import tidy_answer

    assert tidy_answer(text_in, TODAY) == text_out


# -- 2026-11-16 re-measure: an editor that answered in English, a draft that pasted get_analyst_views' wording -----
TSMC_PASTES = ["小摩，11/12，維持，評等「優於大盤」，目標價 3,300 元",
               "高盛，10/6，調升，評等「買進」，目標價 3,300 元"]
TSMC_DRAFT = ("最新的目標價是小摩在 11/12 維持的 3,300 元。\n\n"
              f"- 小摩 11/12 維持「優於大盤」評等，目標價 3,300 元。{TSMC_PASTES[0]}\n"
              f"- 高盛 10/6 調升，評等「買進」，目標價 3,300 元。{TSMC_PASTES[1]}")
TSMC_BARE = ("最新的目標價是小摩在 11/12 維持的 3,300 元。\n\n- 小摩 11/12 維持「優於大盤」評等，目標價 3,300 元。\n"
             "- 高盛 10/6 調升，評等「買進」，目標價 3,300 元。")


def test_pastes_after_a_lines_own_words_go_when_the_line_says_their_numbers():
    from forliosa.ai.chat import strip_pastes

    assert strip_pastes(TSMC_DRAFT, TSMC_PASTES) == TSMC_BARE
    # a line that is only a paste, and a paste with a number the line does not say, stay
    only = f"- {TSMC_PASTES[0]}"
    assert strip_pastes(only, TSMC_PASTES) == only
    news = "10 月營收 197.7 萬元，年增 42.23%"
    line = f"- 公司 11/10 公告十月營收成長。{news}"
    assert strip_pastes(line, [news]) == line
    # the clock time of a pasted 公告 label is not a fact of the line
    assert strip_pastes(f"{OWN}{PASTED}", [PASTED]) == OWN


def test_an_editor_that_does_not_write_chinese_is_never_shown(client, pool, fake, ai_env):
    ai_env(AI_ANSWER_EDITOR="true")
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "台積電 目標價"}),
               web_search_result("srvtoolu_1", [{"url": "https://news.cnyes.com/a", "title": "鉅亨",
                                                 "encrypted_content": "ENC"}]),
               text(TSMC_DRAFT, [search_citation("https://news.cnyes.com/a", "鉅亨", x) for x in TSMC_PASTES]),
               usage={"server_tool_use": {"web_search_requests": 1}})
    fake.reply(text("I've got the new target price: the most recent one is Morgan Stanley's 3,300 yuan from 11/12. "
                    "Please paste the answer you'd like me to rewrite."))
    _, events = chat(client, "台積電的目標價是多少？")
    assert not any("I've" in d.get("delta", "") for n, d in events if n == "text")
    assert not [n for n, _ in events if n == "text_reset"]  # nothing of the edit was on screen
    assert shown(events) == TSMC_BARE  # the answer as written, without the pasted tool wording


def test_an_edit_that_adds_a_conversion_is_caught():
    from forliosa.ai.chat import added_conversions

    draft = "- Aletheia 10/19 給的目標價是 5,000 新台幣／1,000 美元。"
    assert added_conversions(draft, "- Aletheia 10/19 的目標價訂為 5,000 新台幣，相當於 1,000 美元。") == ["相當於"]
    assert added_conversions(draft, "- Aletheia 10/19 的目標價是 5,000 新台幣與 1,000 美元。") == []
    assert added_conversions("營收約合 3 億元。", "營收約合 3 億元。") == []


def test_the_held_back_start_of_an_edit_keeps_its_spaces_and_line_breaks(client, pool, fake, ai_env):
    """The first EDITOR_HEAD_CHARS are held back until they show Chinese; the white space between the pieces that
    arrive meanwhile stays (a list after the opening keeps its blank line)."""
    ai_env(AI_ANSWER_EDITOR="true")
    web_turn(fake)
    edited = "台積電 11/13 收 2350 元。\n\n- 漲 0.43%。\n- 尾盤有 4061 張賣單。"
    fake.reply(*[text(edited[i:i + 3]) for i in range(0, len(edited), 3)])
    _, events = chat(client, "台積電今天怎麼了？")
    assert shown(events) == edited



# -- 2026-11-16 pre-deploy review: quotes inside a sentence, English names first, a split opening, 「不便具名」 -------
GARBLED = ("台積電 11/13 收 1,450 元，跌 1.2%。\n\n"
           "- 分析師指出，AI 需求強勁帶動先進製程產能滿載，公司對明年展望樂觀。")
GARBLED_SOURCE = "市場分析師表示，AI需求強勁帶動先進製程產能滿載，供應鏈訂單能見度直達明年。"
TARIFF = "法人表示美國關稅政策不確定性仍高，建議保守因應"


@pytest.mark.parametrize(("line", "source"), [
    # a quote inside a sentence (strip_pastes had made it 「- 分析師指出公司對明年展望樂觀。」 and so on)
    ("- 分析師指出，AI 需求強勁帶動先進製程產能滿載，公司對明年展望樂觀。", GARBLED_SOURCE),
    ("- 外資認為台積電受惠於輝達新一代 GPU 晶片的強勁需求，維持買進評等。",
     "外資報告指出，台積電受惠於輝達新一代GPU晶片的強勁需求，第4季營收可望再創新高。"),
    ("台積電 11/13 收 1,450 元，法人表示美國關稅政策不確定性仍高，短線震盪。", TARIFF),
    ("- 鉅亨網報導〈輝達財報優於預期 台積電供應鏈同步受惠〉，市場情緒偏多。",
     "輝達財報優於預期 台積電供應鏈同步受惠"),
    # inside its sentence, even with the line's numbers
    ("台積電 11/13 收 1,450 元，法人表示 11/13 收盤 1,450 元以下仍有賣壓，短線震盪。",
     "法人表示11/13收盤1,450元以下仍有賣壓"),
    # a sentence of its own without a number: nothing shows the line says it
    ("- 台積電 11/13 收 1,450 元。法人表示美國關稅政策不確定性仍高。", TARIFF),
])
def test_a_quote_inside_a_sentence_or_without_numbers_is_not_a_paste(line, source):
    from forliosa.ai.chat import strip_pastes

    assert strip_pastes(line, [source]) == line


def test_a_paste_goes_with_its_own_full_stop():
    from forliosa.ai.chat import strip_pastes

    line = f"- 小摩 11/12 維持「優於大盤」評等，目標價 3,300 元。{TSMC_PASTES[0]}。"
    assert strip_pastes(line, TSMC_PASTES) == "- 小摩 11/12 維持「優於大盤」評等，目標價 3,300 元。"
    own = "- 小摩 11/12 維持、高盛 10/6 調升，目標價都是 3,300 元。"
    assert strip_pastes(f"{own}{TSMC_PASTES[0]}。 {TSMC_PASTES[1]}", TSMC_PASTES) == own


def test_a_quote_in_the_answer_as_written_stays_whole(client, pool, fake, ai_env):
    ai_env(AI_ANSWER_EDITOR="true")
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "台積電 11/13"}),
               web_search_result("srvtoolu_1", [{"url": "https://news.cnyes.com/a", "title": "鉅亨",
                                                 "encrypted_content": "ENC"}]),
               text(GARBLED, [search_citation("https://news.cnyes.com/a", "鉅亨", GARBLED_SOURCE)]),
               usage={"server_tool_use": {"web_search_requests": 1}})
    fake.error(500, "api_error", "editor down")  # the edit is dropped: the answer as written
    _, events = chat(client, "台積電今天怎麼了？")
    assert shown(events) == GARBLED


US_DRAFT = "NVIDIA（NVDA）11/13 收 186.5 美元，漲 1.2%。據 CNBC 報導，資料中心需求強勁。"
US_EDITED = "NVIDIA（NVDA）11/13 收 186.5 美元，漲 1.2%，資料中心需求強勁。"
MSFT_EDITED = "**Microsoft** 11/13 收 510 美元，跌 0.8%，資料中心需求強勁。"


def us_turn(fake, draft: str) -> None:
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "NVIDIA stock"}),
               web_search_result("srvtoolu_1", [{"url": "https://www.cnbc.com/a", "title": "CNBC",
                                                 "encrypted_content": "ENC"}]),
               text(draft, [search_citation("https://www.cnbc.com/a", "CNBC", "資料中心需求強勁")]),
               usage={"server_tool_use": {"web_search_requests": 1}})


@pytest.mark.parametrize(("draft", "edited"), [
    (US_DRAFT, US_EDITED),
    ("**Microsoft** 11/13 收 510 美元，跌 0.8%。據報導，資料中心需求強勁。", MSFT_EDITED),
    ("Microsoft 11/13 收 510 美元，跌 0.8%。據報導，資料中心需求強勁。", MSFT_EDITED),
])
def test_an_edit_that_starts_with_the_drafts_english_name_is_kept(client, pool, fake, ai_env, draft, edited):
    """2026-11-16 pre-deploy review: streamed a few characters at a time, an edit starting like its draft with an
    English name was dropped at 「NVIDIA（N」 (eight characters, none Chinese)."""
    ai_env(AI_ANSWER_EDITOR="true")
    us_turn(fake, draft)
    fake.reply(*[text(edited[i:i + 2]) for i in range(0, len(edited), 2)])
    _, events = chat(client, "今天怎麼了？")
    assert shown(events) == edited and not [n for n, _ in events if n == "text_reset"]


def test_an_english_editor_is_never_shown_after_an_english_start_either(client, pool, fake, ai_env):
    ai_env(AI_ANSWER_EDITOR="true")
    us_turn(fake, US_DRAFT)
    reply = "NVIDIA closed at $186.5 on 11/13, up 1.2%. Please paste the answer you'd like me to rewrite."
    fake.reply(*[text(reply[i:i + 2]) for i in range(0, len(reply), 2)])
    _, events = chat(client, "輝達今天怎麼了？")
    assert not any("closed" in d.get("delta", "") for n, d in events if n == "text")
    assert not [n for n, _ in events if n == "text_reset"]  # nothing of the edit was on screen
    assert shown(events) == US_DRAFT


@pytest.mark.parametrize("size", [1, 2, 3, 5])
@pytest.mark.parametrize(("draft", "edited"), [
    ("據 CNBC 報導，Microsoft 11/13 收 510 美元，跌 0.8%，資料中心需求強勁。",
     "Microsoft 11/13 收 510 美元，跌 0.8%，資料中心需求強勁。"),
    ("評等與目標價只有一筆：Morgan Stanley 11/12 維持 Overweight，目標價 230 美元，資料中心需求強勁。",
     "Morgan Stanley 11/12 維持 Overweight，目標價 230 美元，資料中心需求強勁。"),
    ("路透 11/13 報導，NVIDIA（NVDA）將擴大資本支出，資料中心需求強勁。",
     "NVIDIA（NVDA）11/13 傳出將擴大資本支出，資料中心需求強勁。"),
])
def test_an_edit_that_cut_a_chinese_lead_in_before_an_english_name_is_kept(client, pool, fake, ai_env, draft,
                                                                           edited, size):
    """Round 2 of the pre-deploy review: EDITOR_SYSTEM cuts 「據 CNBC 報導，」「評等與目標價只有一筆：」 and puts the
    subject first, so the edit starts with the English name after it; it was dropped at 「Microsof」 (eight
    characters, none Chinese) and the lead-in stayed on screen."""
    ai_env(AI_ANSWER_EDITOR="true")
    us_turn(fake, draft)
    fake.reply(*[text(edited[i:i + size]) for i in range(0, len(edited), size)])
    _, events = chat(client, "今天怎麼了？")
    assert shown(events) == edited and not [n for n, _ in events if n == "text_reset"]


def test_an_english_editor_using_the_drafts_names_is_still_never_shown(client, pool, fake, ai_env):
    ai_env(AI_ANSWER_EDITOR="true")
    draft = "評等與目標價只有一筆：Morgan Stanley 11/12 維持 Overweight，目標價 230 美元，資料中心需求強勁。"
    us_turn(fake, draft)
    reply = "Morgan Stanley 11/12 maintained Overweight with a $230 target. 資料中心需求強勁。"
    fake.reply(*[text(reply[i:i + 2]) for i in range(0, len(reply), 2)])
    _, events = chat(client, "今天怎麼了？")
    assert not any("maint" in d.get("delta", "") for n, d in events if n == "text")
    assert not [n for n, _ in events if n == "text_reset"]  # nothing of the edit was on screen
    assert shown(events) == draft


DAHUA_1 ="大華今天跌 6.9%，大盤跌 2.1%，跌幅是大盤的三倍。"
DAHUA_2 = "外資 11/13 把評等從「買進」調降到「中立」，目標價從 85 元降到 62 元，市場擔心明年車用訂單衰退。"
UMC_2 = "11/14 傳出與格芯合併的談判破局，市場對成熟製程整併的預期落空，外資轉為賣超。"
MTK_1 = "最新的目標價是高盛 11/10 的 1,800 元，評等「買進」。"
MTK_2 = "其餘幾家在 10 月法說會前後調整，區間 1,500 到 1,750 元。"
MTK_ITEMS = "- 高盛 11/10 調升到 1,800 元。\n- 摩根士丹利 10/30 維持 1,650 元。"


@pytest.mark.parametrize(("draft", "edited", "kept"), [
    # a two-sentence opening split into two items: its first half opens, the second stays in the list (it was
    # moved up instead)
    (f"{DAHUA_1}主因是{DAHUA_2}\n\n- 外資賣超 3,200 張。\n- 投信賣超 500 張。",
     f"- 大華今天跌 6.9%，大盤跌 2.1%。\n- {DAHUA_2}\n- 外資賣超 3,200 張。\n- 投信賣超 500 張。",
     f"大華今天跌 6.9%，大盤跌 2.1%。\n\n- {DAHUA_2}\n- 外資賣超 3,200 張。\n- 投信賣超 500 張。"),
    ("聯電今天跌 3.2%，大盤跌 0.4%。主因是 11/14 傳出與格芯合併的談判破局，市場對成熟製程的整併預期落空，"
     "外資轉為賣超。\n\n- 外資賣超 2.3 萬張。",
     f"- 聯電今天跌 3.2%，大盤跌 0.4%。\n- {UMC_2}\n- 外資賣超 2.3 萬張。",
     f"聯電今天跌 3.2%，大盤跌 0.4%。\n\n- {UMC_2}\n- 外資賣超 2.3 萬張。"),
    # its first item closer to a draft item than to the whole opening, but nearly all of it the opening's words
    ("聯發科最新的目標價是高盛 11/10 的 1,800 元，評等「買進」。其餘幾家都在 10 月法說會前後調整，"
     f"區間在 1,500 到 1,750 元之間。\n\n{MTK_ITEMS}",
     f"- {MTK_1}\n- {MTK_2}\n{MTK_ITEMS}",
     f"{MTK_1}\n\n- {MTK_2}\n{MTK_ITEMS}"),
    # the first item reworded too much to tell: the second sentence alone is not moved up, the first comes back
    (f"{DAHUA_1}主因是{DAHUA_2}\n\n- 外資賣超 3,200 張。",
     f"- 跌得比大盤多。\n- {DAHUA_2}\n- 外資賣超 3,200 張。",
     f"{DAHUA_1}\n\n- 跌得比大盤多。\n- {DAHUA_2}\n- 外資賣超 3,200 張。"),
])
def test_an_opening_split_into_items_keeps_its_first_half_first(draft, edited, kept):
    from forliosa.ai.chat import keep_opening

    assert keep_opening(draft, edited) == kept


@pytest.mark.parametrize("sentence", [
    "一位不便具名的法人表示，第 4 季營收可望季增 5%。", "一位不方便具名的外資分析師指出，需求強勁。",
    "一位不肯具名的外資分析師透露，訂單滿載。", "一位拒絕具名的券商主管說，價格將上漲。",
    "一位婉拒具名的投顧老師認為，股價偏高。",
    # round 2: a negated modal before 「具名」
    "一位因未獲授權而無法具名的外資分析師表示，需求強勁。", "一位不能具名的外資分析師表示，需求強勁。",
    "一位未能具名的券商主管表示，訂單滿載。", "一位不宜具名的投顧分析師認為，股價偏高。",
    "一位不得具名的法人說，價格將上漲。", "一位要求不要具名的法人表示，需求強勁。",
])
def test_more_news_wording_about_anonymity_stays(sentence):
    from forliosa.ai.chat import tidy_answer

    assert tidy_answer(sentence, TODAY) == sentence
    assert tidy_answer("台積電最新的具名目標價是小摩的 3,300 元。", TODAY) == "台積電最新的目標價是小摩的 3,300 元。"
    assert tidy_answer("目前尚無具名券商的評等。", TODAY) == "目前尚無券商的評等。"
