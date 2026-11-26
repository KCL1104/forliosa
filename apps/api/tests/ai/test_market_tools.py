"""The chat's market-wide tools and its follow-up questions (產品負責人 2026-11-26: 「明天可以關注哪些個股？」 was
refused; the answer should organise the scheduled events, the day's rankings and the reports' market focus, draw a
comparison chart of the stocks it names and offer 2–3 follow-up questions)."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.ai import market_tools
from forliosa.ai.prompts import CHAT_SYSTEM
from forliosa.ai.tools import TOOLS_BY_NAME, ToolContext, execute
from forliosa.marketdata.service import get_market_data
from forliosa.models import MarketEvent, User
from forliosa.timeutil import next_tw_trading_day, today_taipei
from tests.ai.conftest import API, buy, chat, make_account
from tests.ai.fake_anthropic import text, tool_use


@pytest.fixture()
def ctx(client, engine):
    make_account(client)  # the demo user exists and has an account
    db = Session(engine)
    me = db.scalar(select(User).where(User.email == "demo@forliosa.local"))
    yield ToolContext(db=db, user=me, md=get_market_data())
    db.close()


def run(ctx, name, **args):
    out = execute(ctx, name, args)
    return out, (json.loads(out.content) if not out.is_error and out.content[:1] in "{[" else out.content)


# -- suggest_follow_ups ------------------------------------------------------------------------------------------
def test_follow_ups_are_cleaned():
    clean = market_tools.clean_follow_ups
    assert clean(["台積電法說會說了什麼？", " 台積電法說會說了什麼？ ", "該不該買台積電？", "台積電明天會漲到多少？",
                  "看 https://x.tw", "嗎", "「台達電這次配多少股利？」", "聯發科的本益比？"]) == \
        ["台積電法說會說了什麼？", "台達電這次配多少股利？", "聯發科的本益比？"]
    assert clean("台積電？") == [] and clean([1, None]) == []


def test_a_turn_ending_with_follow_ups_makes_no_further_call(client, pool, fake):
    fake.reply(text("11/27 的重點在台達電除息。"),
               tool_use("toolu_f", "suggest_follow_ups",
                        {"questions": ["台達電這次配多少股利？", "要不要買台達電？", "台達電最近有什麼新聞？"]}),
               stop_reason="tool_use")
    status, events = chat(client, "明天可以關注哪些個股？")
    assert status == 200
    assert len(fake.requests) == 1  # the answer was complete: no call just to end the turn
    follow = [d for n, d in events if n == "follow_ups"]
    assert follow == [{"questions": ["台達電這次配多少股利？", "台達電最近有什麼新聞？"]}]
    assert not any(n == "tool" for n, _ in events)  # no progress line for it
    done = events[-1]
    assert done[0] == "done" and done[1]["stop_reason"] == "end_turn"
    thread_id = done[1]["thread_id"]
    detail = client.get(f"{API}/ai/threads/{thread_id}").json()
    assert detail["messages"][-1]["follow_ups"] == ["台達電這次配多少股利？", "台達電最近有什麼新聞？"]

    # the next question replays the tool_use with its result, then the new question
    fake.reply(text("每股配 5 元。"))
    status, events = chat(client, "台達電這次配多少股利？", thread_id=thread_id)
    assert status == 200
    messages = fake.requests[1]["body"]["messages"]
    i = next(i for i, m in enumerate(messages) if m["role"] == "assistant")
    assert any(b.get("type") == "tool_use" and b["name"] == "suggest_follow_ups" for b in messages[i]["content"])
    result = messages[i + 1]
    assert result["role"] == "user" and result["content"][0]["type"] == "tool_result"
    assert result["content"][0]["tool_use_id"] == "toolu_f"
    assert messages[i + 2]["role"] == "user" and messages[i + 2]["content"][0]["text"] == "台達電這次配多少股利？"
    # a turn without them keeps none
    detail = client.get(f"{API}/ai/threads/{thread_id}").json()
    assert detail["messages"][-1]["follow_ups"] == []


def test_follow_ups_before_the_answer_ask_for_the_answer(client, pool, fake):
    # QA 2026-11-26 (Sonnet): called beside draw_chart before any text; the result must not say 「不要再寫任何文字」
    from forliosa.ai.chat import FOLLOW_UPS_EARLY

    fake.reply(tool_use("toolu_f", "suggest_follow_ups",
                        {"questions": ["智邦法說會會說什麼？", "健策為什麼被處置？"]}), stop_reason="tool_use")
    fake.reply(text("11/27 的重點在智邦法說會。"),
               tool_use("toolu_g", "suggest_follow_ups",
                        {"questions": ["智邦上次法說會說了什麼？", "健策為什麼被處置？"]}), stop_reason="tool_use")
    status, events = chat(client, "明天可以關注哪些個股？")
    assert status == 200 and len(fake.requests) == 2  # the second call's follow-ups end the turn
    result = fake.requests[1]["body"]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and result["content"] == FOLLOW_UPS_EARLY and result["is_error"] is True
    assert "".join(d["delta"] for n, d in events if n == "text") == "11/27 的重點在智邦法說會。"
    # only the questions asked after the answer are kept
    follow = [d for n, d in events if n == "follow_ups"]
    assert follow == [{"questions": ["智邦上次法說會說了什麼？", "健策為什麼被處置？"]}]


def test_follow_ups_asked_only_before_the_answer_are_used_after_it(client, pool, fake):
    asked = {"questions": ["智邦法說會會說什麼？", "健策為什麼被處置？", "要不要買智邦？"]}
    fake.reply(tool_use("toolu_f", "suggest_follow_ups", asked), stop_reason="tool_use")
    fake.reply(text("11/27 的重點在智邦法說會。"))
    status, events = chat(client, "明天可以關注哪些個股？")
    assert status == 200 and len(fake.requests) == 2
    follow = [d for n, d in events if n == "follow_ups"]
    assert follow == [{"questions": ["智邦法說會會說什麼？", "健策為什麼被處置？"]}]  # cleaned like any other
    detail = client.get(f"{API}/ai/threads/{events[-1][1]['thread_id']}").json()
    assert detail["messages"][-1]["follow_ups"] == ["智邦法說會會說什麼？", "健策為什麼被處置？"]


def test_follow_ups_beside_other_tools_continue_the_turn(client, pool, fake):
    acc = make_account(client)
    buy(client, acc, "2330", 1000, 600)
    fake.reply(text("我查一下。"), tool_use("toolu_1", "get_holdings", {}),
               tool_use("toolu_f", "suggest_follow_ups", {"questions": ["台積電最近有什麼新聞？", "台積電的本益比？"]}),
               stop_reason="tool_use")
    fake.reply(text("你持有台積電 1 張。"))
    status, events = chat(client, "我有哪些持股？")
    assert status == 200 and len(fake.requests) == 2
    follow = [d for n, d in events if n == "follow_ups"]
    assert follow == [{"questions": ["台積電最近有什麼新聞？", "台積電的本益比？"]}]
    assert [(d["name"], d["status"]) for n, d in events if n == "tool"] == [("get_holdings", "running"),
                                                                            ("get_holdings", "done")]
    results = fake.requests[1]["body"]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["toolu_1", "toolu_f"]  # in the model's order


def test_follow_ups_written_as_text_become_follow_ups(client, pool, fake):
    # QA 2026-11-26: the model wrote the call into its answer instead of calling the tool
    fake.reply(text('目前算不出今年以來的報酬。\n\nsuggest_follow_ups({"questions": ["我今年領了多少股利？", '
                    '"台積電目前的走勢如何？"]})'))
    status, events = chat(client, "我今年賺多少？")
    assert status == 200
    follow = [d for n, d in events if n == "follow_ups"]
    assert follow == [{"questions": ["我今年領了多少股利？", "台積電目前的走勢如何？"]}]
    detail = client.get(f"{API}/ai/threads/{events[-1][1]['thread_id']}").json()
    assert detail["messages"][-1]["text"].strip() == "目前算不出今年以來的報酬。"
    assert detail["messages"][-1]["follow_ups"] == ["我今年領了多少股利？", "台積電目前的走勢如何？"]


def test_up_to_five_follow_ups():
    asked = [f"台積電第 {n} 個問題？" for n in range(1, 8)]
    assert market_tools.clean_follow_ups(asked) == asked[:5]


def test_a_look_ahead_conversation_runs_on_the_look_ahead_model(client, pool, fake):
    from forliosa.ai.prompts import is_lookahead

    assert is_lookahead("明天可以關注哪些個股？") and is_lookahead("下週有什麼看點")
    assert not is_lookahead("最近有哪些股票要除息？") and not is_lookahead("台積電現在可以買嗎？")
    fake.reply(text("11/27 的重點在法說會。"))
    status, events = chat(client, "明天可以關注哪些個股？")
    assert status == 200 and fake.requests[0]["body"]["model"] == "claude-sonnet-5-5"
    thread_id = events[-1][1]["thread_id"]
    assert events[-1][1]["model"] == "claude-sonnet-5-5"
    # the conversation keeps its model, whatever is asked next
    fake.reply(text("台積電 11/26 收 2,145 元。"))
    chat(client, "台積電呢？", thread_id=thread_id)
    assert fake.requests[1]["body"]["model"] == "claude-sonnet-5-5"
    # any other first question: the chat model
    fake.reply(text("你持有台積電。"))
    chat(client, "我有哪些持股？")
    assert fake.requests[2]["body"]["model"] == "claude-haiku-5-5"


def test_invalid_follow_ups_are_an_error_the_model_sees(ctx):
    out = execute(ctx, "suggest_follow_ups", {"questions": ["要不要買？"]})
    assert out.is_error and "3–5" in out.content
    out = execute(ctx, "suggest_follow_ups", {"questions": ["台積電的本益比？", "台積電的殖利率？"]})
    assert not out.is_error and out.follow_ups == ["台積電的本益比？", "台積電的殖利率？"]


# -- get_market_calendar -----------------------------------------------------------------------------------------
def test_calendar_lists_yours_first_and_counts_the_rest(client, ctx, engine):
    acc = make_account(client, "第二個")
    buy(client, acc, "2330", 1000, 600)
    assert client.post(f"{API}/watchlist", json={"symbol": "2454.TW"}).status_code in (200, 201)
    day = next_tw_trading_day(today_taipei() + timedelta(days=1))
    with Session(engine) as db:
        db.add_all([MarketEvent(key=f"t-{s}", symbol=s, date=day, type="ex_dividend", title="除息", detail="",
                                data={}, source="twse-openapi")
                    for s in ("2330.TW", "2454.TW", "1234.TW")])
        db.commit()
    out, res = run(ctx, "get_market_calendar", date_from="", date_to="")
    assert not out.is_error
    assert res["from"] == res["to"] == res["next_tw_trading_day"] == day.isoformat()
    yours = {e["code"]: e["yours"] for e in res["events"] if e.get("yours")}
    assert yours == {"2330": "持有", "2454": "觀察"}
    assert res["events"][0]["kind"] == "除權息"
    # 1234 has no close (no market cap): counted under others with its name, never listed as one of the largest
    assert "1234" not in {e.get("code") for e in res["events"]}
    assert res["others"] == [{"kind": "除權息", "count": 1, "examples": ["1234"]}]
    assert "市值前 100 名" in res["rules"]


def test_calendar_of_one_kind_lists_every_company_with_the_amount(client, ctx, engine):
    day = next_tw_trading_day(today_taipei() + timedelta(days=1))
    with Session(engine) as db:
        db.add_all([MarketEvent(key="k-1", symbol="1234.TW", date=day, type="ex_dividend", title="除息", detail="",
                                data={"cash": "4.00000000", "stock_ratio": "0.05"}, source="twse-openapi"),
                     MarketEvent(key="k-2", symbol="00878.TW", date=day, type="ex_dividend", title="除息", detail="",
                                 data={"cash": None, "stock_ratio": None}, source="twse-openapi"),
                     MarketEvent(key="k-3", symbol="2330.TW", date=day, type="shareholder_meeting", title="股東會",
                                 detail="", data={}, source="twse-openapi")])
        db.commit()
    out, res = run(ctx, "get_market_calendar", date_from="", date_to="", kind="除息")
    assert not out.is_error and res["rules"].startswith("只查除權息")
    rows = {e["code"]: e for e in res["events"]}
    assert set(rows) == {"1234", "00878"} and res["others"] == []  # every company, no shareholder meeting
    assert rows["1234"]["amount"] == "每股現金 4 元、每千股配 50 股"
    assert rows["00878"]["amount"] == "金額還沒公告"
    out = execute(ctx, "get_market_calendar", {"date_from": "", "date_to": "", "kind": "月營收"})
    assert out.is_error and "法說會" in out.content


def test_performance_of_a_period(client, ctx):
    out, res = run(ctx, "get_performance", range="YTD")
    assert not out.is_error and res["range"] == "今年以來"
    out = execute(ctx, "get_performance", {"range": "2Y"})
    assert out.is_error and "YTD" in out.content


def test_calendar_checks_its_dates(ctx):
    out = execute(ctx, "get_market_calendar", {"date_from": "11/27", "date_to": ""})
    assert out.is_error and "YYYY-MM-DD" in out.content
    start = today_taipei()
    out, res = run(ctx, "get_market_calendar", date_from=(start + timedelta(days=30)).isoformat(),
                   date_to=start.isoformat())
    assert res["from"] == start.isoformat() and any("最多查 14 天" in n for n in res["notes"])


# -- get_market_overview / get_watchlist / get_market_report ------------------------------------------------------
def test_overview_has_the_rule_lists(ctx):
    out, res = run(ctx, "get_market_overview")
    assert not out.is_error
    assert {"indices", "breadth", "sectors_best", "sectors_worst", "gainers", "losers", "most_traded",
            "limit_up_top_by_value", "limit_down_top_by_value", "units"} <= set(res)


def test_percentages_are_written_out():
    # QA 2026-11-26: a fraction (0.025) came back as 「漲 0.03%」; the tools give the percentage as text
    assert market_tools.pct(0.0251) == "+2.51%" and market_tools.pct(-0.012) == "−1.20%"
    assert market_tools.pct(0) == "0.00%" and market_tools.pct(None) is None


def test_watchlist(client, ctx):
    _out, res = run(ctx, "get_watchlist")
    assert res == {"count": 0, "items": [], "note": "觀察清單是空的"}
    assert client.post(f"{API}/watchlist", json={"symbol": "2454.TW"}).status_code in (200, 201)
    _out, res = run(ctx, "get_watchlist")
    assert res["count"] == 1 and res["items"][0]["symbol"] == "2454.TW"


def test_report_off_or_missing(ctx):
    out, res = run(ctx, "get_market_report", kind="latest")
    assert res["status"] == "none"
    out = execute(ctx, "get_market_report", {"kind": "monthly"})
    assert out.is_error


def test_report_news_become_citable_results(ctx, monkeypatch):
    from forliosa.reports import service as rs

    payload = {
        "kind_label": "盤後重點", "edition_label": "11/26（四）", "published_at": "2026-11-26T16:00:00+08:00",
        "title": "加權指數跌 1.2%",
        "highlights": [{"sentences": [{"text": "加權指數跌 1.2%。", "cites": [1]},
                                      {"text": "市場關注美國 11/27 公布的物價數據。", "cites": [2]}]}],
        "sections": [{"key": "focus", "title": "市場焦點", "blocks": [
            {"type": "items", "items": [{"title": "被動元件", "paragraphs": [
                {"sentences": [{"text": "國巨等被動元件股跌停。", "cites": [2, 3]}]}]}]}]}],
        "footnotes": [{"n": 1, "kind": "data", "label": "證交所 11/26", "outlet": None, "url": None},
                      {"n": 2, "kind": "web", "label": "台股收黑 外資賣超", "outlet": "中央社",
                       "url": "https://www.cna.com.tw/news/1", "date_label": "11/26 14:05"},
                      {"n": 3, "kind": "web", "label": "被動元件重挫", "outlet": "經濟日報",
                       "url": "https://money.udn.com/2", "date_label": "11/26 13:50"}],
    }
    monkeypatch.setattr(rs, "enabled", lambda settings=None: True)
    monkeypatch.setattr(rs, "latest", lambda db, user, kind: payload)
    out = execute(ctx, "get_market_report", {"kind": "latest"})
    assert not out.is_error and isinstance(out.content, list)
    by_url = {b["source"]: b for b in out.content}
    assert set(by_url) == {"https://www.cna.com.tw/news/1", "https://money.udn.com/2"}
    cna = by_url["https://www.cna.com.tw/news/1"]["content"][0]["text"]
    assert cna.startswith("11/26（四）盤後重點（引用中央社，11/26 14:05）：")
    assert "市場關注美國 11/27 公布的物價數據。" in cna and "被動元件：國巨等被動元件股跌停。" in cna
    assert "加權指數跌 1.2%" not in cna  # a data sentence is not credited to the article
    assert out.outlets == {"https://www.cna.com.tw/news/1": "中央社", "https://money.udn.com/2": "經濟日報"}


# -- the prompt --------------------------------------------------------------------------------------------------
def test_the_prompt_organises_instead_of_refusing():
    assert "## 明天看點與市場整理" in CHAT_SYSTEM and "不拒絕" in CHAT_SYSTEM
    assert "kind compare，range 3M" in CHAT_SYSTEM
    assert "## 該不該買賣、哪一檔好、現在能不能進場" in CHAT_SYSTEM and "不寫「我不能替你判斷」" in CHAT_SYSTEM
    assert "估值一定寫本益比、股價淨值比與殖利率" in CHAT_SYSTEM and "給 3 到 5 個" in CHAT_SYSTEM
    assert "## 接著問" in CHAT_SYSTEM and "suggest_follow_ups" in CHAT_SYSTEM
    for name in ("get_market_calendar", "get_market_overview", "get_market_report", "get_watchlist", "get_performance"):
        assert name in CHAT_SYSTEM and name in TOOLS_BY_NAME
