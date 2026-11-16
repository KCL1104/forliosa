"""``get_analyst_views`` (2026-11-16, 「禾榮科 最近有甚麼消息嗎? 機構給出的評級與目標價為何?」 was answered from web
search alone: a forum post, an unnamed 「美系外資」 and an AI-written page). Chat now reads the stock page's 法人觀點
entry of today — named institutions, each from a dated article — before it searches. The tool only reads: no search,
no charge, no new row."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.ai import analyst, tools
from forliosa.ai.prompts import CHAT_SYSTEM
from forliosa.ai.tools import TOOLS_BY_NAME, ToolContext, execute, tool_label
from forliosa.marketdata.service import get_market_data
from forliosa.models import AiAnalystViews, AiUsage, User
from tests.ai.conftest import chat
from tests.ai.fake_anthropic import text, tool_use

NOW = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)  # Monday 18:00 Taipei, after the close
UDN = "https://money.udn.com/money/story/5607/9101"
CNA = "https://www.cna.com.tw/news/afe/202610280123.aspx"
ITEMS = [
    {"institution": "元大投顧", "action": "調升", "rating_text": "買進", "target_price": 1350.0, "currency": "TWD",
     "date": "2026-11-10", "source_title": "元大投顧調升台積電目標價至1,350元", "url": UDN},
    {"institution": "花旗", "action": "", "rating_text": "中立", "target_price": None, "currency": "TWD",
     "date": "2026-10-28", "source_title": "花旗調降台積電評等至中立", "url": CNA},
]


@pytest.fixture()
def ctx(client, engine, monkeypatch):
    monkeypatch.setattr(tools, "now_utc", lambda: NOW)
    monkeypatch.setattr(tools, "today_taipei", lambda: date(2026, 11, 16))
    db = Session(engine)
    me = db.scalar(select(User).where(User.email == "demo@forliosa.local"))
    yield ToolContext(db=db, user=me, md=get_market_data())
    db.close()


def entry(db: Session, status: str = "ready", items: list | None = None, created: datetime | None = None,
          symbol: str = "2330.TW") -> None:
    created = created or NOW - timedelta(hours=1)
    db.add(AiAnalystViews(symbol=symbol, trading_day=analyst.trading_day(NOW), status=status,
                          items=ITEMS if items is None else items, notes=[], model="claude-haiku-5-5",
                          generation_id="anv_test", requested_by=None, created_at=created,
                          finished_at=None if status == "pending" else created, expires_at=created + analyst.TTL))
    db.commit()


def rows(db: Session) -> tuple[int, int]:
    return (db.scalar(select(func.count()).select_from(AiAnalystViews)),
            db.scalar(select(func.count()).select_from(AiUsage)))


def test_todays_analyst_views_come_back_as_citable_search_results(ctx):
    entry(ctx.db)
    before = rows(ctx.db)
    out = execute(ctx, "get_analyst_views", {"symbol": "2330"})
    assert not out.is_error
    assert [(b["type"], b["source"], b["title"], b["citations"]) for b in out.content] == [
        ("search_result", UDN, "元大投顧調升台積電目標價至1,350元", {"enabled": True}),
        ("search_result", CNA, "花旗調降台積電評等至中立", {"enabled": True})]
    # institution, date (no year this year), what changed, the rating as published, the target as written
    assert [b["content"][0]["text"] for b in out.content] == ["元大投顧，11/10，調升，評等「買進」，目標價 1,350 元",
                                                               "花旗，10/28，評等「中立」"]
    assert out.outlets == {}  # 出處 shows the article's own title and host
    assert rows(ctx.db) == before  # read only: nothing searched, charged or stored


@pytest.mark.parametrize(("status", "items", "age", "expected", "words"), [
    (None, None, None, "none", "今天還沒有人在個股頁查這一檔的法人觀點"),
    ("pending", [], timedelta(minutes=1), "pending", "還在整理"),
    ("pending", [], timedelta(minutes=10), "unavailable", "今天沒有查到"),  # the generation died
    ("unavailable", [], timedelta(minutes=1), "unavailable", "今天沒有查到"),
    ("ready", [], timedelta(hours=1), "ready", "沒有近 90 天具名機構的評等或目標價"),
    ("ready", ITEMS, timedelta(hours=25), "none", "今天還沒有人在個股頁查"),  # expired
])
def test_without_items_the_tool_says_so_and_points_to_web_search(ctx, status, items, age, expected, words):
    import json

    if status is not None:
        entry(ctx.db, status, items, created=NOW - age)
    before = rows(ctx.db)
    out = execute(ctx, "get_analyst_views", {"symbol": "2330"})
    res = json.loads(out.content)
    assert not out.is_error and res["status"] == expected and res["symbol"] == "2330.TW"
    assert words in res["note"] and "web_search" in res["note"] and "具名機構" in res["note"]
    assert rows(ctx.db) == before  # an expired or stale entry is not purged or rewritten here


def test_an_etf_has_no_analyst_views(ctx):
    import json

    out = execute(ctx, "get_analyst_views", {"symbol": "0050"})
    assert not out.is_error and json.loads(out.content)["status"] == "none"
    assert "ETF 沒有個別機構的評等與目標價" in json.loads(out.content)["note"]


def test_the_line_writes_a_year_only_for_another_year_and_us_dollar_targets():
    item = {"institution": "Morgan Stanley", "action": "維持", "rating_text": "Overweight", "target_price": 231.5,
            "currency": "USD", "date": "2026-12-28"}
    assert tools._analyst_line(item, date(2027, 1, 5)) == "Morgan Stanley，2026/12/28，維持，評等「Overweight」，目標價 US$231.5"
    assert tools._analyst_line({**item, "currency": "TWD", "target_price": 700.0, "rating_text": None},
                               date(2026, 12, 30)) == "Morgan Stanley，12/28，維持，目標價 700 元"


def test_the_tool_is_registered_with_a_label():
    spec = TOOLS_BY_NAME["get_analyst_views"]
    assert spec.required == ("symbol",) and "法人觀點" in spec.description and "read-only" in spec.description
    assert tool_label("get_analyst_views", {"symbol": "2330"}) == "查看 2330 法人觀點"


def test_the_prompt_sends_rating_questions_to_the_card_first_and_drops_weak_sources_silently():
    assert CHAT_SYSTEM.index("## 為什麼漲跌") < CHAT_SYSTEM.index("## 機構評等與目標價") \
        < CHAT_SYSTEM.index("## 技術分析與盤中價格")
    section = CHAT_SYSTEM[CHAT_SYSTEM.index("## 機構評等與目標價"):CHAT_SYSTEM.index("## 技術分析與盤中價格")]
    for phrase in (
        "先用 get_analyst_views", "再用 web_search 找近 90 天的新聞報導",
        "具名機構（券商、投顧、投資銀行）給的評等與目標價", "目標價彙整頁、股價行情頁、論壇、AI 整理的頁面上的數字不寫",
        "「法人」「美系外資」這類沒寫出機構名稱的不寫", "超過 90 天、出處或日期不明的也不寫",
        "不寫的就不提：不說找到幾筆、哪一則不採用、為什麼不用",
        "評等照來源的用詞寫（例如「買進」「中立」「加碼」）", "不寫成網站自己的分類（「看多」）",
        "表格的欄位名稱（「多空評等」「預估 EPS」）", "寫預估 EPS 時寫出是哪一年的預估",
        "不算平均或上漲空間", "目前沒有機構評等與目標價的資料",
    ):
        assert phrase in section, phrase
    # the standing rule: a named institution's published target may be quoted, never the AI's own
    assert "也不給你自己的目標價（轉述具名機構已發表的目標價可以，寫出機構並附引用）" in CHAT_SYSTEM


def test_a_chat_turn_cites_the_cards_items(client, pool, fake, engine, monkeypatch):
    monkeypatch.setattr(tools, "now_utc", lambda: NOW)
    monkeypatch.setattr(tools, "today_taipei", lambda: date(2026, 11, 16))
    with Session(engine) as db:
        entry(db)
    fake.reply(tool_use("toolu_a", "get_analyst_views", {"symbol": "2330"}), stop_reason="tool_use")
    cite = {"type": "search_result_location", "source": UDN, "title": ITEMS[0]["source_title"],
            "cited_text": "元大投顧，11/10，調升，評等「買進」，目標價 1,350 元", "search_result_index": 0,
            "start_block_index": 0, "end_block_index": 1}
    fake.reply(text("元大投顧 11/10 調升評等至「買進」，目標價 1,350 元。", [cite]))
    status, events = chat(client, "台積電的目標價是多少？", page={"route": "/stock/2330.TW", "symbol": "2330.TW"})
    assert status == 200
    steps = [(d["name"], d["status"], d["label"]) for n, d in events if n == "tool"]
    assert steps == [("get_analyst_views", "running", "查看 2330 法人觀點"),
                     ("get_analyst_views", "done", "查看 2330 法人觀點")]
    result = fake.requests[1]["body"]["messages"][-1]["content"][0]
    assert [b["source"] for b in result["content"]] == [UDN, CNA]
    assert [d for n, d in events if n == "citation"] == [
        {"url": UDN, "title": ITEMS[0]["source_title"], "cited_text": cite["cited_text"]}]
    assert "get_analyst_views" in [t["name"] for t in fake.requests[0]["body"]["tools"]]
