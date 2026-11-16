"""2026-11-16 (「台達電今天為啥跌這麼多?」: about 19 s, nothing shown until the end): the answer editor streams its edit
as it is written; when the edit is dropped after part of it was shown, a ``text_reset`` event brings back the answer
as written. Also: the number check lets a date in parentheses become 今天, and every turn logs one line of timings."""

from __future__ import annotations

import itertools
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.ai import chat as chat_mod
from forliosa.ai.chat import keeps_numbers
from forliosa.ai.keypool import Route
from forliosa.models import AiMessage, AiUsage
from forliosa.timeutil import now_taipei
from tests.ai.conftest import chat
from tests.ai.fake_anthropic import search_citation, server_tool_use, text, web_search_result

DRAFT = "台積電 11/13 收 2,350 元，漲 0.43%。據鉅亨網報導，台積電(2330)最後一盤丟出4061張砍單。"
EDITED = "台積電 11/13 收 2350 元，漲 0.43%。尾盤有 4061 張賣單，漲幅收小。"
QUESTION = "台積電今天怎麼了？"
PAGE = {"route": "/stock/2330.TW", "symbol": "2330.TW"}


def web_turn(fake, before: str | None = None) -> None:
    fake.reply(*([text(before)] if before else []),
               server_tool_use("srvtoolu_1", "web_search", {"query": "台積電 11/13"}),
               web_search_result("srvtoolu_1", [{"url": "https://news.cnyes.com/a", "title": "鉅亨",
                                                 "encrypted_content": "ENC"}]),
               text(DRAFT, [search_citation("https://news.cnyes.com/a", "鉅亨", "最後一盤丟出4061張砍單")]),
               usage={"server_tool_use": {"web_search_requests": 1}})


def shown(events) -> str:
    """What the browser shows: ``text`` deltas appended, a ``text_reset`` replacing them."""
    out = ""
    for n, d in events:
        if n == "text":
            out += d["delta"]
        elif n == "text_reset":
            out = d["text"]
    return out


def answer_events(events) -> list[str]:
    """The editor step, the answer's text and any reset, in order (``tool:running``, ``text``, ``text_reset``…)."""
    out = []
    for n, d in events:
        if n == "tool" and d["name"] == "edit_answer":
            out.append(f"tool:{d['status']}")
        elif n in ("text", "text_reset"):
            out.append(n)
    return out


def stored_answer(engine) -> str:
    with Session(engine) as db:
        return db.scalars(select(AiMessage).where(AiMessage.role == "assistant")).all()[-1].text


def usage_stops(engine) -> list[str | None]:
    with Session(engine) as db:
        return [u.stop_reason for u in db.scalars(select(AiUsage).order_by(AiUsage.id))]


def test_the_edit_streams_as_it_is_written(client, pool, fake, engine, ai_env):
    ai_env(AI_ANSWER_EDITOR="true")
    web_turn(fake)
    fake.reply(text(EDITED))
    _, events = chat(client, QUESTION, page=PAGE)
    # the step starts, the edit arrives in pieces (the fake streams a text block as two deltas), then the step ends
    assert answer_events(events) == ["tool:running", "text", "text", "tool:done"]
    assert shown(events) == EDITED and "鉅亨網" not in shown(events)
    assert fake.requests[1]["body"]["stream"] is True and "文字編輯" in fake.requests[1]["body"]["system"]
    # no silent thinking before the first word (2026-11-16: 3 of 16 edits ran past the 4 s limit thinking)
    assert fake.requests[1]["body"]["thinking"] == {"type": "disabled"}
    assert stored_answer(engine) == EDITED
    assert usage_stops(engine) == ["end_turn", "end_turn"]


def test_white_space_around_the_edit_is_never_shown(client, pool, fake, engine, ai_env):
    ai_env(AI_ANSWER_EDITOR="true")
    web_turn(fake)
    fake.reply(text("\n\n" + EDITED + "\n"))
    _, events = chat(client, QUESTION, page=PAGE)
    # what streamed is exactly what is kept (grounding positions are in that text)
    assert shown(events) == EDITED and stored_answer(engine) == EDITED


def test_an_edit_that_loses_a_number_after_it_was_shown_is_reset(client, pool, fake, engine, ai_env):
    ai_env(AI_ANSWER_EDITOR="true")
    web_turn(fake, before="我查一下。")  # shown before the search: only the part after it is held and edited
    fake.reply(text("台積電 11/13 收高，尾盤有賣壓。"))  # 2350, 0.43 and 4061 are gone
    _, events = chat(client, QUESTION, page=PAGE)
    assert answer_events(events) == ["text", "text", "tool:running", "text", "text", "tool:done", "text_reset"]
    reset = next(d for n, d in events if n == "text_reset")
    assert reset == {"text": "我查一下。" + DRAFT}  # the whole answer of the turn, as written
    assert shown(events) == "我查一下。" + DRAFT and stored_answer(engine) == "我查一下。" + DRAFT
    assert [n for n, _ in events][-1] == "done" and not [n for n, _ in events if n == "error"]


def test_an_editor_stream_that_fails_or_stops_early_is_reset(client, pool, fake, engine, ai_env):
    ai_env(AI_ANSWER_EDITOR="true")
    web_turn(fake)
    fake.reply(text(EDITED), fail_after_text=True)  # an error event after the text
    _, events = chat(client, QUESTION, page=PAGE)
    assert answer_events(events) == ["tool:running", "text", "text", "tool:done", "text_reset"]
    assert shown(events) == DRAFT and stored_answer(engine) == DRAFT
    assert usage_stops(engine) == ["end_turn", "interrupted"]  # the cut-off editor call is billed and recorded
    web_turn(fake)
    fake.reply(text(EDITED), stop_reason="max_tokens")
    _, events = chat(client, QUESTION, page=PAGE)
    assert answer_events(events)[-1] == "text_reset" and shown(events) == DRAFT
    assert usage_stops(engine)[-1] == "max_tokens"


def test_an_edit_longer_than_allowed_is_cut_off_while_it_streams(client, pool, fake, ai_env):
    ai_env(AI_ANSWER_EDITOR="true")
    long = (EDITED * 10)[:300]  # the limit is max(200, twice the draft); the first half (150) is shown first
    web_turn(fake)
    fake.reply(text(long))
    _, events = chat(client, QUESTION, page=PAGE)
    assert answer_events(events) == ["tool:running", "text", "tool:done", "text_reset"]
    assert shown(events) == DRAFT
    # too long from the first piece on: nothing of it is shown, the answer as written streams
    web_turn(fake)
    fake.reply(text((EDITED * 20)[:500]))
    _, events = chat(client, QUESTION, page=PAGE)
    assert "text_reset" not in answer_events(events) and shown(events) == DRAFT


def test_a_late_first_word_or_a_slow_edit_shows_the_answer_as_written(client, pool, fake, engine, ai_env,
                                                                     monkeypatch, caplog):
    ai_env(AI_ANSWER_EDITOR="true")
    web_turn(fake)
    fake.reply(text(EDITED))
    ticks = itertools.count(0, 5)  # every reading of the clock is 5 s later: the first event is already late
    monkeypatch.setattr(chat_mod, "_clock", lambda: next(ticks))
    with caplog.at_level(logging.WARNING, logger="forliosa.ai.chat"):
        _, events = chat(client, QUESTION, page=PAGE)
    assert answer_events(events)[:2] == ["tool:running", "tool:done"] and "text_reset" not in answer_events(events)
    assert shown(events) == DRAFT and EDITED not in shown(events)
    assert any("no word after" in r.getMessage() for r in caplog.records)
    assert usage_stops(engine) == ["end_turn", "interrupted"]
    ticks2 = itertools.count(0, 30)  # past the total time as well
    monkeypatch.setattr(chat_mod, "_clock", lambda: next(ticks2))
    web_turn(fake)
    fake.reply(text(EDITED))
    with caplog.at_level(logging.WARNING, logger="forliosa.ai.chat"):
        _, events = chat(client, QUESTION, page=PAGE)
    assert shown(events) == DRAFT and any("not done after" in r.getMessage() for r in caplog.records)


def test_dates_in_parentheses_may_become_today():
    # 2026-11-16 E3: the edit was dropped for the 16 of 「今（16）日」
    assert keeps_numbers("今（16）日台股震盪幅度加大，台達電（2308）跳空重挫 7%", "今天台股震盪加大，台達電跳空重挫 7%")
    assert keeps_numbers("昨（15）日收 1,240 元，本（11）月營收 1,234 億元", "昨天收 1240 元，11 月營收 1234 億元")
    assert keeps_numbers("今(2026)年 EPS 30 元", "今年 EPS 30 元")
    assert keeps_numbers("週一（16日）外資賣超 120 億元；（11月13日）收 1,240 元",
                         "今天外資賣超 120 億元；11/13 收 1240 元")
    assert keeps_numbers("週五（11/13）收 1,240 元", "上週五收 1240 元")
    # only the date itself: the same number elsewhere still has to stay, and a dropped figure is still caught
    assert not keeps_numbers("今（16）日成交 16 萬張", "今天成交量放大")
    assert not keeps_numbers("今（16）日跌 7%，大盤跌 3%", "今天跌 7%")


MON = date(2026, 11, 16)


def test_news_flash_codes_and_todays_date_may_become_today():
    # 2026-11-16 why_1: a clean edit was reset to the draft for the 2308 of cnyes's 「台達電(2308-TW)」
    assert keeps_numbers("台達電(2308-TW)下跌120元。", "台達電下跌 120 元。")
    assert keeps_numbers("台達電（2308-TWO）漲停", "台達電漲停")
    # today's or yesterday's date written as a day, 11/16 or 11月16日 may become 今天／昨天
    flash = "台達電(2308-TW)16日09:59下跌120元，報1120元。"
    assert keeps_numbers(flash, "台達電今天 09:59 跌 120 元，報 1120 元。", MON)
    assert keeps_numbers("台達電（2308.TW）16日盤中跌停。", "台達電今天盤中跌停。", MON)
    assert keeps_numbers("11/16 盤中觸及跌停 1120 元，11/13 收 1,240 元",
                         "今天盤中觸及跌停，報 1120 元，11/13 收 1240 元", MON)
    assert keeps_numbers("11月15日外資賣超；15日收 1,240 元", "昨天外資賣超，昨天收 1240 元", MON)
    # not without the date of today (a function call without it, an edit without 今天, another day) …
    assert not keeps_numbers(flash, "台達電今天 09:59 跌 120 元，報 1120 元。")
    assert not keeps_numbers(flash, "台達電 09:59 跌 120 元，報 1120 元。", MON)
    assert not keeps_numbers("台達電（2308）30日股價一度跌停至1,335元。", "台達電今天股價一度跌停至 1,335 元。", MON)
    assert not keeps_numbers("台達電 16日跌停，18日除息", "台達電今天跌停", MON)
    assert not keeps_numbers("11/13 收 1,240 元", "今天收 1240 元", MON)
    # a rounded restatement may go when the exact figure stays (2026-11-16 why_6: 「約 4%」 merged into 「4.14%」) …
    assert keeps_numbers("大盤同時跌約 4%。加權指數跌 1806.45 點，跌幅 4.14%", "加權指數跌 1806.45 點，約 4.14%", MON)
    assert keeps_numbers("跌幅約 9.7%，盤中跌 9.68%", "盤中跌 9.68%", MON)
    assert not keeps_numbers("大盤約跌 4%，台達電跌 9.68%", "台達電跌 9.68%", MON)  # nothing it rounds
    assert not keeps_numbers("大盤跌 4%，加權指數跌 4.14%", "加權指數跌 4.14%", MON)  # not written as a rounding
    # … nor a number of days, or a figure of a quote line the editor left out (2026-11-16 a_0050_1)
    assert not keeps_numbers("16日均線在 1,200 元", "今天均線在 1200 元", MON)
    assert not keeps_numbers("0050.TW 98.10 4.40 4.29%，成交 172,713 張", "0050 今天盤中 98.10 元，跌 4.29%", MON)


def test_a_cnyes_flash_edited_to_today_is_kept(client, pool, fake, engine, ai_env, caplog):
    ai_env(AI_ANSWER_EDITOR="true")
    day = now_taipei().day  # the turn's own today
    flash = f"台達電今天盤中跌停。台達電(2308-TW){day}日09:59下跌120元，股價跌停報1120.0元。"
    edit = "台達電今天盤中跌停，09:59 跌 120 元，報 1120 元。"
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "台達電 跌停"}),
               web_search_result("srvtoolu_1", [{"url": "https://news.cnyes.com/b", "title": "鉅亨",
                                                 "encrypted_content": "ENC"}]),
               text(flash, [search_citation("https://news.cnyes.com/b", "鉅亨", "下跌120元")]),
               usage={"server_tool_use": {"web_search_requests": 1}})
    fake.reply(text(edit))
    _, events = chat(client, QUESTION, page=PAGE)
    assert "text_reset" not in answer_events(events) and shown(events) == edit and stored_answer(engine) == edit


def test_headings_the_edit_adds_become_plain_lines(client, pool, fake, engine, ai_env):
    # 2026-11-16: with thinking off the editor made the first sentence a ### heading in 8 to 15 of 33 edits
    ai_env(AI_ANSWER_EDITOR="true")
    web_turn(fake)
    fake.reply(text("### 台積電 11/13 收高\n\n" + EDITED + "\n## 尾盤\n- 4061 張 # 賣單"))
    _, events = chat(client, QUESTION, page=PAGE)
    want = "台積電 11/13 收高\n\n" + EDITED + "\n尾盤\n- 4061 張 # 賣單"  # a # inside a line stays
    assert shown(events) == want and stored_answer(engine) == want


def test_the_heading_filter_works_on_any_split_and_only_at_line_starts():
    edit = "### 標題一\n內文 #2 名\n   ## 標題二\n- 第一點"
    for size in (1, 2, 3, 5, len(edit)):
        f = chat_mod._HeadingFilter()
        assert "".join(f.feed(edit[i:i + size]) for i in range(0, len(edit), size)) == \
            "標題一\n內文 #2 名\n   標題二\n- 第一點"


def test_an_answer_with_headings_keeps_the_edits_headings(client, pool, fake, engine, ai_env):
    ai_env(AI_ANSWER_EDITOR="true")
    draft = "### 台積電\n" + DRAFT
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "台積電 11/13"}),
               web_search_result("srvtoolu_1", [{"url": "https://news.cnyes.com/a", "title": "鉅亨",
                                                 "encrypted_content": "ENC"}]),
               text(draft, [search_citation("https://news.cnyes.com/a", "鉅亨", "最後一盤丟出4061張砍單")]),
               usage={"server_tool_use": {"web_search_requests": 1}})
    fake.reply(text("### 台積電\n" + EDITED))
    _, events = chat(client, QUESTION, page=PAGE)
    assert shown(events) == "### 台積電\n" + EDITED


def test_the_editor_thinks_only_where_it_cannot_be_turned_off():
    # Haiku 5.5 accepts thinking off at effort low; Opus 5.5 and Sonnet 5.5 answer 400, so they keep the default
    assert chat_mod._editor_thinking("claude-haiku-5-5") == {"thinking": {"type": "disabled"}}
    assert chat_mod._editor_thinking("claude-opus-5-5") == {}
    assert chat_mod._editor_thinking("claude-sonnet-5-5") == {}


def test_every_turn_logs_one_line_of_timings(client, pool, fake, ai_env, caplog, monkeypatch):
    ai_env(AI_ANSWER_EDITOR="true")
    web_turn(fake)
    fake.reply(text(EDITED))
    real_route = pool.route

    def cooling(*args, **kwargs):  # the pinned slot cools down for a moment: the turn waits for it
        r = real_route(*args, **kwargs)
        return Route(r.slot, 2.0)

    monkeypatch.setattr(pool, "route", cooling)
    with caplog.at_level(logging.INFO, logger="forliosa.ai.chat"):
        _, events = chat(client, QUESTION, page=PAGE)
    lines = [r.getMessage() for r in caplog.records if "timings" in r.getMessage()]
    assert len(lines) == 1
    line = lines[0]
    thread_id = events[0][1]["id"]
    assert line.startswith(f"AI turn {thread_id[:16]} timings (s): ") and thread_id not in line  # a prefix only
    for part in ("wait 2.00 key #", "setup ", "call1 start ", " headers ", " first ", "editor start ", "edited",
                 "first text ", "total "):
        assert part in line, part
    assert QUESTION not in line and "台積電" not in line  # no user content
    assert any("(sticky)" in r.getMessage() and "waits 2.0s" in r.getMessage() for r in caplog.records)
