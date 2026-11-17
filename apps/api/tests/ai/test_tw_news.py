"""tw_news_search (產品負責人 2026-11-17; round-2 recommendation §9): the queries the server writes, the arguments of a
non-strict tool, when the tool is offered, the measured filter (one fixture per rule), udn's story-number dates, the
excerpt, what Claude gets, and the requests' caps, retries and refusals (shared with the news worker). No network:
LangSearch answers through a scripted client. Every text here is SYNTHETIC (written for these tests; no real article
text)."""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy.orm import Session

from forliosa.ai import tools as tools_mod
from forliosa.ai import tw_news as tw
from forliosa.ai.tools import ToolContext, client_tool_definitions, execute
from forliosa.config import get_settings
from forliosa.marketdata.base import InstrumentInfo
from forliosa.models import NewsArticle, NewsFetchState
from forliosa.news import langsearch as ls
from forliosa.news import service
from forliosa.news.normalize import make_terms
from forliosa.news.sources import RawItem

NOW = datetime(2026, 11, 17, 10, 40, tzinfo=UTC)  # 18:40 Taipei, a Tuesday (trading day)
KEY = "sk-ls-test-4b1d9e"
MIDNIGHT = datetime(2026, 11, 18, tzinfo=UTC)
TSMC = InstrumentInfo("2330.TW", "2330", "台積電", "TWSE", "stock", "TWD")
ACCTON = InstrumentInfo("2345.TW", "2345", "智邦", "TWSE", "stock", "TWD")
ETF = InstrumentInfo("0050.TW", "0050", "元大台灣50", "TWSE", "etf", "TWD")
TERMS = make_terms("台積電", "2330", taiwan=True)
EXCERPT = "外資最新報告指出台積電先進製程需求強勁維持買進評等目標價上調至二千四百元"  # synthetic, no digits


# -- helpers --------------------------------------------------------------------------------------------------------
def page(name: str, url: str, published: str | None = "2026-11-16T02:00:00.000Z", snippet: str = "",
         **extra: Any) -> dict[str, Any]:
    return {"name": name, "url": url, "datePublished": published, "snippet": snippet, **extra}


def answer(*pages: dict[str, Any], code: int = 200, msg: str | None = None) -> dict[str, Any]:
    return {"code": code, "msg": msg, "data": {"webPages": {"value": list(pages)}}}


def reply(*pages: dict[str, Any], status: int = 200, tokens: tuple[int, int] = (10, 900), latency: float = 2.0,
          payload: dict[str, Any] | None = None) -> ls.Reply:
    return ls.Reply(status, payload if payload is not None else answer(*pages), tokens[0], tokens[1], latency)


class FakeClient:
    """LangSearch's client, scripted: the replies in turn (the last repeats); an exception is raised."""

    def __init__(self, *replies: ls.Reply | Exception) -> None:
        self.replies = list(replies) or [reply()]
        self.bodies: list[dict[str, Any]] = []

    def post(self, body: dict[str, Any]) -> ls.Reply:
        self.bodies.append(dict(body))
        r = self.replies[min(len(self.bodies) - 1, len(self.replies) - 1)]
        if isinstance(r, Exception):
            raise r
        return r

    def close(self) -> None:
        pass

    @property
    def queries(self) -> list[str]:
        return [b["query"] for b in self.bodies]


def raw(title: str, url: str, published: datetime = datetime(2026, 11, 16, 2, tzinfo=UTC), text: str = "") -> RawItem:
    return ls.TextItem(title=title, url=url, published_at=published, text=text)


@pytest.fixture()
def aiset():
    return get_settings().model_copy(update={"ai_langsearch_enabled": True, "langsearch_api_key": SecretStr(KEY)})


@pytest.fixture()
def lsfake(monkeypatch):
    """The scripted client every request goes through; the clock stands at NOW and nothing really sleeps."""
    holder: dict[str, FakeClient] = {"client": FakeClient()}
    monkeypatch.setattr(ls.LangSearchClient, "from_settings", lambda settings: holder["client"])
    monkeypatch.setattr(tw, "_clock", lambda: NOW)
    monkeypatch.setattr(tw, "_sleep", lambda s: None)

    def use(*replies: ls.Reply | Exception) -> FakeClient:
        holder["client"] = FakeClient(*replies)
        return holder["client"]

    return use


@pytest.fixture()
def ctx(engine, market, aiset):
    db = Session(engine)
    yield ToolContext(db=db, user=None, md=market, tw_news=tw.TwNewsTurn.for_settings(aiset))  # type: ignore[arg-type]
    db.close()


def run(ctx: ToolContext, **args: Any) -> tuple[Any, Any]:
    out = execute(ctx, "tw_news_search", {"symbol": "", "days": 0, **args})
    if out.is_error:
        return out, out.content
    return out, (json.loads(out.content) if isinstance(out.content, str) else out.content)


# -- 1. the plan ----------------------------------------------------------------------------------------------------
def test_plan_queries():
    p = tw.plan("analyst_targets", TSMC, "large", 0, NOW)
    assert p.queries == ('"台積電" 調升目標價', '"台積電" 調降目標價')
    assert (p.freshness, p.max_chars, p.limit, p.strict_dates) == ("2026-08-19..2026-11-17", 600, 8, True)
    assert p.window_start == datetime(2026, 8, 19, tzinfo=UTC)
    # mid: one unquoted query; small and quiet too (產品負責人 2026-11-17: every cap size tries LangSearch first)
    for tier in ("mid", "small", "quiet"):
        assert tw.plan("analyst_targets", ACCTON, tier, 0, NOW).queries == ("智邦 目標價",)
    assert tw.plan("analyst_targets", ETF, "large", 0, NOW) is None  # an ETF has no broker targets: nothing is asked
    # news by tier
    for tier, start in (("large", "2026-11-10"), ("mid", "2026-11-03"), ("small", "2026-10-18"),
                        ("quiet", "2026-10-18")):
        p = tw.plan("news", TSMC, tier, 0, NOW)
        assert (p.queries, p.freshness, p.max_chars, p.limit) == (('"台積電"',), f"{start}..2026-11-17", 300, 10)
    assert tw.plan("why_move", TSMC, "mid", 0, NOW).freshness == "2026-11-16..2026-11-17"
    for intent, word, start in (("earnings_call", "法說會", "2026-10-03"), ("revenue", "營收", "2026-10-13"),
                                ("dividend", "配息", "2026-09-18")):
        p = tw.plan(intent, TSMC, "large", 0, NOW)
        assert (p.queries, p.freshness, p.limit, p.strict_dates) == ((f'"台積電" {word}',), f"{start}..2026-11-17", 8,
                                                                     True)
    # the market: 盤中 from 09:00 to 14:00 Taipei on a trading day, else 盤後; today only (a day without trading: from
    # the last trading day)
    at_14 = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)
    at_10 = datetime(2026, 11, 17, 2, 0, tzinfo=UTC)
    saturday = datetime(2026, 11, 21, 4, 0, tzinfo=UTC)
    assert (tw.plan("market", None, "large", 5, at_14).queries, tw.plan("market", None, "large", 0, at_14).freshness) \
        == (("台股 盤後",), "2026-11-17..2026-11-17")
    assert tw.plan("market", None, "large", 0, at_10).queries == ("台股 盤中",)
    assert tw.plan("market", None, "large", 0, saturday).freshness == "2026-11-20..2026-11-21"
    # days: news only (1-30)
    assert tw.plan("dividend", TSMC, "large", 5, NOW).days == 60
    assert tw.plan("news", TSMC, "large", 45, NOW).freshness == "2026-10-18..2026-11-17"
    assert tw.plan("news", TSMC, "large", 3, NOW).freshness == "2026-11-14..2026-11-17"
    # only the core of the short name goes into a query: no market suffix, no quotes, no extra spaces
    odd = InstrumentInfo("1234.TW", "1234", '永"冠  -KY', "TWSE", "stock", "TWD")
    assert tw.plan("news", odd, "mid", 0, NOW).queries == ('"永冠"',)
    with pytest.raises(ValueError):
        tw.plan("news", InstrumentInfo("9999.TW", "9999", "9999", "TWSE", "stock", "TWD"), "mid", 0, NOW)


def test_why_move_reaches_back_to_the_last_trading_day():
    """2026-11-17 review: why_move was the UTC dates D-1..D, so on Sunday and all Monday morning Friday's after-close
    news was out of range. Like ``why.from_langsearch``: from the day before the UTC date's last trading day."""
    sunday_evening = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)  # Sunday 20:00 Taipei
    monday_morning = datetime(2026, 11, 15, 23, 30, tzinfo=UTC)  # Monday 07:30 Taipei (still Sunday in UTC)
    monday_open = datetime(2026, 11, 16, 2, 0, tzinfo=UTC)  # Monday 10:00 Taipei
    for at in (sunday_evening, monday_morning):
        p = tw.plan("why_move", TSMC, "mid", 0, at)
        assert (p.freshness, p.window_start, p.days) == ("2026-11-12..2026-11-15", datetime(2026, 11, 12, tzinfo=UTC),
                                                        3)
        friday = raw("台積電宣布擴大美國投資", LTN.format(5200300), datetime(2026, 11, 13, 8, tzinfo=UTC))  # 16:00
        assert titles(keep([friday], "why_move", now=at)) == ["台積電宣布擴大美國投資"]
    assert tw.plan("why_move", TSMC, "mid", 0, monday_open).freshness == "2026-11-15..2026-11-16"
    # nothing found: the next step of 為什麼漲跌, not 「do not ask again」
    note = tw.none_note("why_move", "台積電", 3, economy=False)
    assert "tw_news_search（intent news，days 30）" in note and "web_search" in note and "不要換關鍵字" not in note
    eco = tw.none_note("why_move", "台積電", 3, economy=True)
    assert "intent news，days 30" in eco and "web_search" not in eco


def test_the_query_holds_only_the_short_name_and_fixed_words(ctx, lsfake):
    fake = lsfake(reply())
    for symbol in ("2330", "台積電", "2330.TW"):
        run(ctx, symbol=symbol, intent="news")
    assert fake.queries == ['"台積電"']  # the same stock and intent: one request (the turn's memo)
    run(ctx, symbol="2330", intent="dividend", days=12)
    assert fake.queries[-1] == '"台積電" 配息' and fake.bodies[-1]["freshness"] == "2026-09-18..2026-11-17"
    body = fake.bodies[0]
    assert body == {"query": '"台積電"', "freshness": "2026-11-03..2026-11-17", "summary": False, "count": 20,
                    "contents": {"text": {"max_characters": 300}}}


def test_only_the_ais_requests_read_the_text():
    payload = answer(page("台積電法說會", "https://money.udn.com/money/story/5612/9880441", snippet=EXCERPT))
    plain = ls.parse(payload, NOW)[0]
    assert type(plain) is RawItem and not hasattr(plain, "text")  # the news worker never reads it
    item = ls.parse(payload, NOW, with_text=True)[0]
    assert isinstance(item, ls.TextItem) and item.text == EXCERPT and EXCERPT not in repr(item)
    for v, want in (({"summary": "s"}, "s"), ({"contents": {"text": "c"}}, "c"), ({}, "")):
        assert ls.text_of(v) == want


def test_chat_request_body():
    assert ls.chat_request_body("x", "oneWeek", 600)["contents"] == {"text": {"max_characters": 600}}
    for bad in ((1, "oneWeek"), (1000, "oneWeek"), (300, "noLimit"), (300, "oneYear"), (300, "")):
        with pytest.raises(ValueError):
            ls.chat_request_body("x", bad[1], bad[0])
    # the news worker's body keeps its one-character cap
    assert ls.request_body('"台積電"', "oneDay", 20)["contents"] == {"text": {"max_characters": 1}}


# -- 2. arguments -----------------------------------------------------------------------------------------------------
def test_args_validation(ctx, lsfake):
    fake = lsfake(reply())
    for args in ({"intent": "general"}, {"intent": "news", "days": "abc"}, {"intent": "news", "days": True},
                 {"intent": "news", "symbol": 2330}, {"intent": "news", "symbol": "台" * 41}, {"intent": None}):
        out, _ = run(ctx, **{"symbol": "2330", **args})
        assert out.is_error, args
    out, _ = run(ctx, symbol="2330", intent="news", keywords="擴產")  # not in the schema: refused by execute
    assert out.is_error and "不認得的參數 keywords" in out.content
    out = execute(ctx, "tw_news_search", {"symbol": "2330", "days": 0})
    assert out.is_error and "缺少 intent" in out.content
    out, data = run(ctx, symbol="AAPL", intent="news")
    assert not out.is_error and data["status"] == "error"
    assert "web_search" in data["note"] and "只查台股" in data["note"]
    assert fake.bodies == []  # none of these asked LangSearch
    out, _ = run(ctx, symbol="2330", intent="news", days="7")  # a numeric string is taken
    out2 = execute(ctx, "tw_news_search", {"symbol": "2330", "intent": "why_move"})  # days left out: 0
    assert not out.is_error and not out2.is_error and len(fake.bodies) == 2
    assert fake.bodies[0]["freshness"] == "2026-11-10..2026-11-17"


def test_the_tool_answers_only_when_offered(ctx, lsfake, engine):
    fake = lsfake(reply())
    off = ToolContext(db=ctx.db, user=None, md=ctx.md)  # type: ignore[arg-type]
    _out, data = run(off, symbol="2330", intent="news")
    assert data["status"] == "error" and "web_search" in data["note"] and fake.bodies == []
    _out, data = run(ToolContext(db=ctx.db, user=None, md=ctx.md, economy=True),  # type: ignore[arg-type]
                     symbol="2330", intent="news")
    assert "web_search" not in data["note"]


# -- 3. the tool list -------------------------------------------------------------------------------------------------
def test_tool_list(aiset):
    base = get_settings()
    defs = client_tool_definitions(base)
    assert "tw_news_search" not in {d["name"] for d in defs}  # off by default: the list of today
    on = client_tool_definitions(aiset)
    names = [d["name"] for d in on]
    assert "tw_news_search" in names and names == sorted(names) and on == client_tool_definitions(aiset)
    assert sum(1 for d in on if d.get("strict") is True) <= 20
    tw_def = next(d for d in on if d["name"] == "tw_news_search")
    assert "strict" not in tw_def and tw_def["input_schema"]["additionalProperties"] is False
    assert set(tw_def["input_schema"]["properties"]) == {"symbol", "intent", "days"}
    assert [d for d in on if d["name"] != "tw_news_search"] == defs  # every other tool exactly as before
    no_key = aiset.model_copy(update={"langsearch_api_key": None})
    assert "tw_news_search" not in {d["name"] for d in client_tool_definitions(no_key)}
    assert "tw_news_search" in {d["name"] for d in client_tool_definitions(aiset, economy=True)}
    no_eco = aiset.model_copy(update={"ai_langsearch_in_economy": False})
    assert "tw_news_search" not in {d["name"] for d in client_tool_definitions(no_eco, economy=True)}
    assert "tw_news_search" not in {d["name"] for d in client_tool_definitions(aiset, deep=True)}
    assert tools_mod.tool_label("tw_news_search", {"symbol": "2330", "intent": "analyst_targets"}) \
        == "搜尋台灣新聞：2330 目標價"
    assert tools_mod.tool_label("tw_news_search", {"symbol": "", "intent": "market"}) == "搜尋台灣新聞：大盤"


# -- 4. the filter ----------------------------------------------------------------------------------------------------
UDN = "https://money.udn.com/money/story/5612/{}"
LTN = "https://ec.ltn.com.tw/article/breakingnews/{}"
YAHOO = "https://tw.stock.yahoo.com/news/{}.html"


def keep(items: list[RawItem], intent: str = "news", tier: str = "large", close: float | None = None,
         stats: Counter[str] | None = None, now: datetime = NOW, days: int = 0) -> list[tw.Item]:
    p = tw.plan(intent, TSMC, tier, days, now)
    return tw.filter_items(items, p, terms=TERMS, code="2330", close=close, now=now,
                           stats=stats if stats is not None else Counter())


def titles(items: list[tw.Item]) -> list[str]:
    return [x.title for x in items]


def test_filters():
    s: Counter[str] = Counter()
    ok = raw("台積電法說會釋出正向展望", UDN.format(9880001))
    dropped = [
        raw("台積電(2330) 走勢圖", "https://www.example.com.tw/quote/2330"),  # quote page
        raw("台積電購05 權證 熱門", UDN.format(9880002)),  # warrant title
        raw("台積電 外電報導", "https://www.reuters.com/technology/x"),  # not a Taiwan site
        raw("台積電 討論", "https://vocus.cc/article/abc"),  # junk (not news)
        raw("台積電 筆記", "https://www.cmoney.tw/notes/abc"),
        raw("聯電法說會釋出正向展望", UDN.format(9880003)),  # the matcher: not about 台積電
    ]
    assert titles(keep([ok, *dropped], stats=s)) == ["台積電法說會釋出正向展望"]
    assert s["quote_page"] == 2 and s["not_taiwan"] == 1 and s["junk"] == 2 and s["not_about"] == 1

    # 世界日報's reprint of 聯合報系 news: kept for the 法人 intent only
    wj = raw("台積電 外資調升目標價", "https://www.worldjournal.com/wj/story/121347/9876543",
             text="外資調升台積電目標價至 2,400 元。")
    assert [x.outlet for x in keep([wj], "analyst_targets")] == [tw.WJ_OUTLET]
    assert keep([wj], "news") == []
    assert keep([raw("台積電 外資調升目標價", "https://www.worldjournal.com/wj/story/121999/9876543",
                     text="外資調升台積電目標價至 2,400 元。")], "analyst_targets") == []

    # 「這大廠」: the title does not name it; one sentence of the text names it with a target price (not on Yahoo)
    big = "某外資最新報告出爐。台積電目標價上調至 2,400 元，維持買進評等。"
    unnamed = raw("這大廠目標價至 2,400 元", LTN.format(5200001), text=big)
    assert titles(keep([unnamed], "analyst_targets")) == ["這大廠目標價至 2,400 元"]
    assert keep([raw("這大廠目標價至 2,400 元", YAHOO.format("big-1"), text=big)], "analyst_targets") == []
    # the name and a target in different sentences is not enough (v1 let Yahoo's side column through)
    apart = "台積電今天收高。另一家公司目標價上調至 300 元。"
    assert keep([raw("這大廠目標價至 300 元", LTN.format(5200002), text=apart)], "analyst_targets") == []

    # Yahoo's side column: the title stays, the text goes
    side = raw("台積電法說會釋出正向展望 三大重點", YAHOO.format("side-1"),
               text="其他新聞 ・ 3 小時前 某公司大漲 ・ 5 小時前 另一則")
    s = Counter()
    got = keep([side], stats=s)
    assert titles(got) == ["台積電法說會釋出正向展望 三大重點"] and got[0].excerpt == "" and s["side_text"] == 1


def test_dates():
    # the URL's date when it is three days or more from the engine's; closer, the engine's time (checked by the URL)
    far = raw("台積電法說會釋出正向展望", "https://www.chinatimes.com/realtimenews/20261020001234-260410",
              published=datetime(2026, 11, 15, 2, tzinfo=UTC))
    near = raw("台積電宣布擴大美國投資", "https://www.chinatimes.com/realtimenews/20261114001234-260410",
               published=datetime(2026, 11, 15, 2, tzinfo=UTC))
    got = {x.title: x for x in keep([far, near], days=30)}
    assert got["台積電法說會釋出正向展望"].date == datetime(2026, 10, 19, 16, tzinfo=UTC)  # 10/20 00:00 Taipei
    assert got["台積電法說會釋出正向展望"].date_src == "url"
    assert (got["台積電宣布擴大美國投資"].date, got["台積電宣布擴大美國投資"].date_src) == (
        datetime(2026, 11, 15, 2, tzinfo=UTC), "url")
    # outside the window: dropped
    old = "https://www.chinatimes.com/realtimenews/20261020001234-260410"
    assert keep([raw("台積電法說會釋出正向展望", old)]) == []

    # an engine date on the window's first day: unknown — dropped for the 法人 intent, kept marked for news
    first_analyst = datetime(2026, 8, 19, 3, tzinfo=UTC)
    s: Counter[str] = Counter()
    up = "外資把台積電目標價調升至 2,400 元。"
    assert keep([raw("台積電 外資調升目標價", LTN.format(5200003), first_analyst, up)], "analyst_targets", close=2300,
                stats=s) == []
    assert s["date_unknown"] == 1
    first_news = datetime(2026, 10, 18, 3, tzinfo=UTC)  # a small cap's 30-day window
    got = keep([raw("台積電宣布擴大美國投資", LTN.format(5200004), first_news)], tier="small")
    # 2026-11-17 review: its day is the window's first (or a burst's) — no M/D the model could write as the report's
    block = tw.blocks(got, date(2026, 11, 17))[0]
    assert got[0].unknown_date and block["text"] == "自由時報，日期未確認：（只有標題）"
    assert block["safe_text"] == "自由時報，日期未確認：台積電宣布擴大美國投資" and "10/18" not in json.dumps(block)
    description = tools_mod.TOOLS_BY_NAME["tw_news_search"].description
    assert "日期未確認 has no reliable date: write no date for it" in description

    # four engine-dated items on one day: a re-indexing burst
    day = datetime(2026, 9, 24, 3, tzinfo=UTC)
    burst = [raw(f"台積電 外資調升目標價 第{i}則", LTN.format(5200010 + i), day,
                 f"外資把台積電目標價調升至 2,4{i}0 元。") for i in range(4)]
    assert keep(burst, "analyst_targets", close=2300) == []
    assert len(keep(burst[:3], "analyst_targets", close=2300)) == 3


def test_stale_article_checks():
    when = datetime(2026, 10, 7, 3, tzinfo=UTC)  # engine date only (LTN has none in its URL)

    def one(text: str, close: float = 2200, title: str = "台積電 外資目標價") -> list[tw.Item]:
        s: Counter[str] = Counter()
        return keep([raw(title, LTN.format(5200100), when, text)], "analyst_targets", close=close, stats=s)

    assert one("外資把台積電目標價調升至 2,400 元。")  # passes
    assert one("台積電股價收在 880 元，外資目標價 1,500 元。") == []  # a price under half the close: an old article
    assert one("台積電股價收在 5,000 元，外資目標價 5,500 元。") == []  # over twice the close
    assert one("大摩把台積電目標價調降至 1,000 元。", close=2400) == []  # every target under half the close
    assert one("2025年外資喊台積電目標價 1,500 元。") == []  # dated to an earlier year
    # 2026-11-17 review: next year's forecast named first, the article's own (old) year after it
    assert one("外資預估台積電2026年EPS達70元，目標價2,400元，較2025年成長。") == []
    assert one("外資預估台積電2027年EPS達90元，目標價2,400元，較2026年成長。")  # this year and next: current
    assert one("2025 年以來外資把台積電目標價調升至 2,400 元。")  # 「以來」 is not a date of the report
    # a URL date is checked already: the three checks are for engine-only dates
    dated = raw("台積電 外資目標價", "https://www.chinatimes.com/realtimenews/20261007001234-260410",
                when, "台積電股價收在 880 元，外資目標價 1,500 元。")
    assert keep([dated], "analyst_targets", close=2200)
    # the 法人 intent keeps only items with analyst content
    assert keep([raw("台積電法說會釋出正向展望", LTN.format(5200101), when, "公司表示需求強勁。")],
                "analyst_targets", close=2200) == []


def test_dedupe_prefers_the_original_outlet():
    title = "台積電10月營收創同期新高"
    items = [raw(title, YAHOO.format("copy-1"), datetime(2026, 11, 10, 3, tzinfo=UTC)),
             raw(title, UDN.format(9870001), datetime(2026, 11, 10, 2, tzinfo=UTC)),
             raw("台積電法說會釋出正向展望", UDN.format(9880001), datetime(2026, 11, 16, 2, tzinfo=UTC))]
    got = tw.dedupe_items(keep(items))
    assert [(x.title, x.outlet) for x in got] == [("台積電法說會釋出正向展望", "經濟日報"), (title, "經濟日報")]


# -- 5. udn's story numbers -----------------------------------------------------------------------------------------
def test_udn_calibration(engine):
    pts = [("udn", 9_700_000, date(2026, 9, 1)), ("udn", 9_700_400, date(2026, 9, 1)),
           ("udn", 9_800_000, date(2026, 10, 1)), ("udn", 9_900_000, date(2026, 10, 31)),
           ("wj", 1_000_000, date(2026, 9, 1)), ("wj", 1_000_600, date(2026, 10, 1))]
    cal = tw.UdnCalibration.from_points(pts)
    assert set(cal.series) == {"udn"}  # 世界日報 has only two days: no series
    assert cal.date_of(UDN.format(9_850_000)) == date(2026, 10, 16)
    assert cal.date_of("https://udn.com/news/story/7238/9850000") == date(2026, 10, 16)  # one numbering
    assert cal.date_of(UDN.format(9_600_000)) is None  # before the range
    assert cal.date_of(UDN.format(9_905_000)) == date(2026, 11, 2)  # up to two days past the newest point
    assert cal.date_of(UDN.format(9_990_000)) is None
    assert cal.date_of("https://www.worldjournal.com/wj/story/121347/1000300") is None
    wj = tw.UdnCalibration.from_points([*pts, ("wj", 1_001_200, date(2026, 11, 1))])
    assert wj.date_of("https://www.worldjournal.com/wj/story/121347/1000300") == date(2026, 9, 16)  # its own series
    assert wj.date_of(UDN.format(1_000_300)) is None
    # read from the stored headlines (not LangSearch's own dates), and used by article_date
    with Session(engine) as db:
        for i, (sid, day) in enumerate(((9_700_000, 1), (9_800_000, 31), (9_900_000, 61))):
            at = datetime(2026, 9, 1, 2, tzinfo=UTC) + timedelta(days=day - 1)
            db.add(NewsArticle(symbol="2330.TW", url_key=f"k{i}", url=UDN.format(sid), title="t", outlet="經濟日報",
                               domain="money.udn.com", published_at=at, source="gdelt"))
        db.add(NewsArticle(symbol="2330.TW", url_key="ls", url=UDN.format(9_990_000), title="t", outlet="經濟日報",
                           domain="money.udn.com", published_at=datetime(2026, 9, 2, tzinfo=UTC), source="langsearch"))
        db.commit()
        cal = tw.calibration(db, NOW)
    when, src = tw.article_date(UDN.format(9_850_000), datetime(2026, 11, 16, tzinfo=UTC), cal)
    assert (when, src) == (datetime(2026, 10, 16, tzinfo=tw.TAIPEI), "url")


# -- 6. the excerpt ---------------------------------------------------------------------------------------------------
def test_excerpt():
    title = "台積電法說會釋出正向展望與資本支出計畫"
    text = (f"{title} 聽新聞 0:00 / 1:23 本文共 627 字 （記者王小明／攝） 公司今天舉行法說會。"
            + "台積電表示下季毛利率可望維持高檔。" + "天氣很好大家出門。" * 40
            + "財務長說明年資本支出將再增加。")
    clean = tw.clean_text(text, title)
    assert not clean.startswith(title) and "聽新聞" not in clean and "本文共" not in clean and "攝" not in clean
    ex = tw.excerpt_of(clean, "earnings_call", "台積電")
    assert len(ex) <= 300
    assert ex.index("下季毛利率") < ex.index("資本支出") and "天氣很好" not in ex  # matching sentences, in order
    assert len(tw.excerpt_of("台積電" + "很長的句子" * 100, "news", "台積電")) == 300


# -- 7. what Claude gets ----------------------------------------------------------------------------------------------
def test_blocks():
    items = [tw.Item("台積電法說會釋出正向展望", UDN.format(9880001), "經濟日報", "money.udn.com",
                     datetime(2026, 11, 10, 2, tzinfo=UTC), "url", excerpt=EXCERPT),
             tw.Item("台積電去年的舊聞", LTN.format(5200200), "自由時報", "ec.ltn.com.tw",
                     datetime(2025, 12, 1, 2, tzinfo=UTC), "engine")]
    b = tw.blocks(items, date(2026, 11, 17))
    assert b[0]["text"] == f"經濟日報，11/10：{EXCERPT}"
    assert b[0]["safe_text"] == "經濟日報，11/10：台積電法說會釋出正向展望"
    assert b[1]["text"] == "自由時報，2025/12/1，日期依搜尋引擎：（只有標題）"
    assert all(x["private"] for x in b) and not any("[" in x["text"] for x in b)
    content = tools_mod.citable_content(tools_mod.Citable(b))
    assert content[0] == {"type": "search_result", "source": UDN.format(9880001), "title": "台積電法說會釋出正向展望",
                          "content": [{"type": "text", "text": f"經濟日報，11/10：{EXCERPT}"}],
                          "citations": {"enabled": True}}
    assert all("citations" not in t for c in content for t in c["content"])


def test_smoke_leak_check_counts_the_excerpt_only():
    """2026-11-17 review: the manual --tw-news check compared the cited title line with the item's whole text, and
    「Yahoo股市，11/10：」 alone is 14 characters: a correct redaction was reported as a leak."""
    from forliosa.ai.smoke import cites_excerpt

    for outlet, src in (("Yahoo股市", "url"), ("中時新聞網", "url"), ("FTNN 新聞網", "url"), ("Yahoo新聞", "engine")):
        item = tw.Item("台積電法說會釋出正向展望", YAHOO.format("x-1"), outlet, "tw.stock.yahoo.com",
                       datetime(2026, 11, 10, 2, tzinfo=UTC), src, excerpt=EXCERPT)
        b = tw.blocks([item], date(2026, 11, 17))[0]
        assert not cites_excerpt(b["safe_text"], [b["text"]], set()), outlet  # the title line: not a leak
        assert not cites_excerpt(b["safe_text"], [b["text"]], {b["safe_text"]})
        assert cites_excerpt(b["text"], [b["text"]], {b["safe_text"]})  # the excerpt itself is
        assert cites_excerpt(EXCERPT[5:30], [b["text"]], {b["safe_text"]})


def test_scrub_messages():
    redact = {UDN.format(9880001): "經濟日報，11/10：台積電法說會釋出正向展望"}
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "台積電有什麼消息？"}]},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "tw_news_search",
                                           "input": {"symbol": "2330", "intent": "news", "days": 0}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": [
            {"type": "search_result", "source": UDN.format(9880001), "title": "台積電法說會釋出正向展望",
             "content": [{"type": "text", "text": f"經濟日報，11/10：{EXCERPT}"}], "citations": {"enabled": True}},
            {"type": "search_result", "source": "https://other.example.com.tw/a", "title": "get_news 的標題",
             "content": [{"type": "text", "text": "某報，11/10：get_news 的標題"}], "citations": {"enabled": True}}]}]},
        {"role": "assistant", "content": [{"type": "text", "text": "需求強勁。", "citations": [
            {"type": "search_result_location", "source": UDN.format(9880001), "title": "台積電法說會釋出正向展望",
             "cited_text": EXCERPT, "search_result_index": 0, "start_block_index": 0, "end_block_index": 1}]}]},
    ]
    before = json.dumps(messages, ensure_ascii=False)
    out = tw.scrub_messages(messages, redact)
    assert json.dumps(messages, ensure_ascii=False) == before  # a copy: the turn's own history is untouched
    dumped = json.dumps(out, ensure_ascii=False)
    assert EXCERPT not in dumped and "台積電法說會釋出正向展望" in dumped
    assert out[2]["content"][0]["content"][1] == messages[2]["content"][0]["content"][1]  # other results as they were
    assert out[3]["content"][0]["citations"][0]["cited_text"] == redact[UDN.format(9880001)]
    assert out[:2] == messages[:2]
    assert tw.scrub_messages(messages, {}) is messages


def test_scrub_messages_leaves_get_news_with_the_same_link():
    """2026-11-17 review: LangSearch's headlines are stored, so get_news can return the very link tw_news_search did;
    only the tw_news_search result (by its tool_use_id) and a citation of its excerpt are rewritten."""
    url = UDN.format(9880001)
    line = "經濟日報，11/10：台積電法說會釋出正向展望"
    news_block = {"type": "search_result", "source": url, "title": "台積電法說會釋出正向展望",
                  "content": [{"type": "text", "text": "經濟日報，11/10 10:02：台積電法說會釋出正向展望"},
                              {"type": "text", "text": "主題：AI；類股：半導體"}], "citations": {"enabled": True}}
    tw_block = {"type": "search_result", "source": url, "title": "台積電法說會釋出正向展望",
                "content": [{"type": "text", "text": f"經濟日報，11/10：{EXCERPT}"}], "citations": {"enabled": True}}
    cite_news = {"type": "search_result_location", "source": url, "title": "台積電法說會釋出正向展望",
                 "cited_text": "經濟日報，11/10 10:02：台積電法說會釋出正向展望主題：AI；類股：半導體",
                 "search_result_index": 0, "start_block_index": 0, "end_block_index": 2}
    cite_tw = {"type": "search_result_location", "source": url, "title": "台積電法說會釋出正向展望",
               "cited_text": EXCERPT, "search_result_index": 1, "start_block_index": 0, "end_block_index": 1}
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "台積電有什麼消息？"}]},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "n1", "name": "get_news", "input": {"symbol": "2330"}},
            {"type": "tool_use", "id": "t1", "name": "tw_news_search", "input": {"symbol": "2330", "intent": "news"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "n1", "content": [news_block]},
                                     {"type": "tool_result", "tool_use_id": "t1", "content": [tw_block]}]},
        {"role": "assistant", "content": [{"type": "text", "text": "法說會釋出正向展望。", "citations": [cite_news]},
                                          {"type": "text", "text": "需求強勁。", "citations": [cite_tw]}]},
    ]
    out = tw.scrub_messages(messages, {url: line})
    assert out[2]["content"][0]["content"] == [news_block]  # get_news as it was, its time and tags included
    assert out[2]["content"][1]["content"][0]["content"] == [{"type": "text", "text": line}]
    assert out[3]["content"][0]["citations"] == [cite_news]
    assert out[3]["content"][1]["citations"][0]["cited_text"] == line
    assert EXCERPT not in json.dumps(out, ensure_ascii=False)


def test_scrub_messages_keeps_the_models_facts():
    """2026-11-17 review: the model's own sentences restating a broker's target or the month's revenue stay in the
    stored (and replayed) turn; only a copy of an excerpt's wording goes — looked for across the text blocks."""
    url = UDN.format(9880001)
    excerpt = ("經濟日報，11/10：摩根士丹利（大摩）最新報告將台積電目標價調升至1,500元，維持加碼評等。台積電10月營收"
               "3,367.6億元，月增7.1%，年增16.9%，創同期新高。法人指出先進製程需求強勁且產能持續滿載")
    facts = ["大摩將目標價調升至1,500元，維持加碼評等（11/10）。",
             "台積電 10 月營收 3,367.6 億元，月增 7.1%，年增 16.9%。",
             "台積電 10 月營收為 3,367.6 億元，月增 7.1%、年增 16.9%。"]
    copied = ["法人說先進製程需", "求強勁且產能持續滿載。"]  # one copy split by a citation's block boundary
    messages = [{"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "tw_news_search",
                                                   "input": {}}]},
                {"role": "assistant", "content": [{"type": "text", "text": t} for t in [*facts, *copied]]}]
    out = tw.scrub_messages(messages, {url: "經濟日報，11/10：台積電目標價調升"}, [excerpt])
    texts = [b["text"] for b in out[1]["content"]]
    assert texts[:3] == facts  # byte for byte
    # the sentence that copied it goes whole, in both blocks (never a fragment such as 「法人說」)
    assert texts[3:] == ["（略）", "（略）"] and "產能持續滿載" not in json.dumps(out, ensure_ascii=False)


def test_tier_for_keeps_an_empty_ranking_for_the_hour(monkeypatch, aiset):
    """2026-11-17 review: with no ranks yet (a fresh or demo database) every call read them again."""
    calls: list[int] = []
    monkeypatch.setattr(ls, "read_tier", lambda db, symbol: None)
    monkeypatch.setattr(ls, "market_cap_ranks", lambda db, md: calls.append(1) or {})
    for _ in range(5):
        assert tw.tier_for(None, None, TSMC, aiset) == "mid"  # type: ignore[arg-type]
    assert len(calls) == 1
    tw.reset_caches()
    tw.tier_for(None, None, TSMC, aiset)  # type: ignore[arg-type]
    assert len(calls) == 2


# -- 8. requests: retries, refusals and caps ------------------------------------------------------------------------
GOOD_TITLES = ("台積電宣布擴大美國亞利桑那州投資", "台積電法說會釋出正向展望", "台積電董事會核准資本預算")


def good(n: int = 2) -> ls.Reply:
    return reply(*[page(GOOD_TITLES[i], UDN.format(9880100 + i), snippet=f"{GOOD_TITLES[i]}。{EXCERPT}")
                   for i in range(n)])


def test_retry_on_a_slow_empty_answer(ctx, lsfake):
    fake = lsfake(reply(latency=9.0), good())
    _out, data = run(ctx, symbol="2330", intent="news")
    assert len(fake.bodies) == 2 and isinstance(data, list) and len(data) == 2
    assert ctx.tw_news.requests == 1  # the retry is not one of the turn's three
    fast = lsfake(reply(latency=1.0), good())
    _, data = run(ctx, symbol="2330", intent="why_move")
    # why_move found nothing: the note points to the next step of 為什麼漲跌 (the month's news, then the web for 外電)
    assert len(fast.bodies) == 1 and data["status"] == "none" and "intent news，days 30" in data["note"]
    with Session(ctx.db.get_bind()) as db:
        assert ls.read_chat_usage(db, NOW.date()).requests == 3  # the retry counts toward the day


@pytest.mark.parametrize(("first", "why"), [
    (reply(status=429), "quota"),
    (reply(payload=answer(code=429, msg="daily quota exceeded")), "quota"),
    (reply(status=401), "blocked"),
    (reply(status=403), "blocked"),
    (reply(status=302), "blocked"),
])
def test_a_refusal_stops_chat_and_news_until_midnight(ctx, lsfake, first, why):
    fake = lsfake(first, good())
    _, data = run(ctx, symbol="2330", intent="news")
    assert data["status"] == "error" and "web_search" in data["note"] and len(fake.bodies) == 1
    db = ctx.db
    db.expire_all()
    # booked on the AI's day (the worker's ladder reads only its own refusals), and the whole key stops
    assert ls.read_chat_usage(db, NOW.date()).stopped == why and ls.read_usage(db, NOW.date()).stopped == ""
    assert ls.key_stopped(db, NOW.date()) == why and ls.status(db, ctx.tw_news.settings, NOW)["stopped"] == why
    wide = db.get(NewsFetchState, (ls.SOURCE_KEY, service.SOURCE_WIDE))
    assert wide.backoff_until.replace(tzinfo=UTC) == MIDNIGHT and not service._source_open(db, ls.SOURCE_KEY, NOW)
    _, again = run(ctx, symbol="2330", intent="dividend")
    assert again["status"] == "error" and len(fake.bodies) == 1  # nothing more is sent today
    with pytest.raises(ls.ChatUnavailable):
        ls.chat_search(db, ctx.tw_news.settings, ['"台積電"'], "oneWeek", max_characters=300, clock=lambda: NOW,
                       sleep=lambda s: None)


def test_two_outages_pause_the_key(ctx, lsfake, aiset):
    fake = lsfake(reply(status=503), reply(status=502), good())
    _, a = run(ctx, symbol="2330", intent="news")
    _, b = run(ctx, symbol="2330", intent="dividend")
    assert a["status"] == b["status"] == "error" and len(fake.bodies) == 2
    wide = ctx.db.get(NewsFetchState, (ls.SOURCE_KEY, service.SOURCE_WIDE))
    assert wide is not None and wide.last_status == "unreachable" and wide.backoff_until is not None
    fresh = tw.TwNewsTurn.for_settings(aiset)
    _, c = run(ToolContext(db=ctx.db, user=None, md=ctx.md, tw_news=fresh), symbol="2330",  # type: ignore[arg-type]
               intent="revenue")
    assert c["status"] == "error" and len(fake.bodies) == 2  # paused


def test_an_answer_over_the_token_guard_stops_the_ai_for_the_day(ctx, lsfake):
    fake = lsfake(reply(*good().payload["data"]["webPages"]["value"], tokens=(10, 25_000)), good())
    _, data = run(ctx, symbol="2330", intent="news")
    assert data["status"] == "error"  # its results are not used
    assert ls.read_chat_usage(ctx.db, NOW.date()).stopped == "contract"
    assert service._source_open(ctx.db, ls.SOURCE_KEY, NOW)  # the news worker goes on
    _, again = run(ctx, symbol="2330", intent="dividend")
    assert again["status"] == "error" and len(fake.bodies) == 1


def test_daily_caps(ctx, lsfake, aiset, engine):
    fake = lsfake(good())
    ctx.tw_news.settings = aiset.model_copy(update={"ai_langsearch_max_requests_per_day": 1})
    _, a = run(ctx, symbol="2330", intent="news")
    _, b = run(ctx, symbol="2330", intent="dividend")
    assert isinstance(a, list) and b["status"] == "error" and len(fake.bodies) == 1
    with Session(engine) as db:
        ls._bump_chat(db, NOW.date(), tokens=3_000_000)
    turn = tw.TwNewsTurn.for_settings(aiset.model_copy(update={"ai_langsearch_max_requests_per_day": 50}))
    _, c = run(ToolContext(db=ctx.db, user=None, md=ctx.md, tw_news=turn), symbol="2330",  # type: ignore[arg-type]
               intent="revenue")
    assert c["status"] == "error" and len(fake.bodies) == 1  # the day's tokens are spent


def test_per_turn_cap_and_memo(ctx, lsfake, monkeypatch):
    monkeypatch.setattr(tw, "tier_for", lambda db, md, info, settings: "large")
    fake = lsfake(good())
    run(ctx, symbol="2330", intent="analyst_targets")  # two requests, side by side
    assert fake.queries == ['"台積電" 調升目標價', '"台積電" 調降目標價']
    assert all(b["contents"] == {"text": {"max_characters": 600}} for b in fake.bodies)
    run(ctx, symbol="台積電", intent="analyst_targets")  # the same call: the turn's memo
    assert len(fake.bodies) == 2
    run(ctx, symbol="2330", intent="news")
    _, d = run(ctx, symbol="2330", intent="dividend")
    assert len(fake.bodies) == 3 and ctx.tw_news.requests == 3
    assert d["status"] == "error" and "已經查過 3 次" in d["note"] and "web_search" in d["note"]
    assert ctx.tw_news.calls == ["analyst_targets:none", "news:ok"]  # the refused third is not a call


def test_a_refusal_beside_another_request_counts_both(ctx, lsfake, monkeypatch):
    monkeypatch.setattr(tw, "tier_for", lambda db, md, info, settings: "large")
    fake = lsfake(reply(status=429), good())
    _, data = run(ctx, symbol="2330", intent="analyst_targets")
    assert data["status"] == "error" and len(fake.bodies) == 2 and ctx.tw_news.requests == 2
    assert ls.read_chat_usage(ctx.db, NOW.date()).tokens == 1820  # both answers' tokens are booked


def test_the_ai_cap_is_taken_in_one_update(engine, aiset, monkeypatch):
    """2026-11-17 review: the day's count was read, and the requests added only after the gap, so callers side by side
    (chat turns, the card, 為什麼漲跌) all saw room and together went over the cap. What is sent now is what one
    conditional UPDATE took: here every caller reads a stale count of 0."""
    settings = aiset.model_copy(update={"ai_langsearch_max_requests_per_day": 3})
    pair = ['"台積電" 調升目標價', '"台積電" 調降目標價']

    def ask(db: Session, client: FakeClient, queries: list[str], chars: int = 600) -> ls.ChatBatch:
        return ls.chat_search(db, settings, queries, "2026-08-19..2026-11-17", max_characters=chars, client=client,
                              clock=lambda: NOW, sleep=lambda s: None)

    real = ls.read_chat_usage
    monkeypatch.setattr(ls, "read_chat_usage", lambda db, day: ls.DayUsage(day))
    with Session(engine) as db:
        ls._bump_chat(db, NOW.date(), requests=3, at=NOW - timedelta(minutes=1))  # the others used the day meanwhile
        fake = FakeClient(good())
        with pytest.raises(ls.ChatUnavailable) as refused:
            ask(db, fake, pair)
        assert refused.value.reason == "requests_cap" and fake.bodies == []
        ls._bump_chat(db, NOW.date(), requests=-1)  # one left: one of the pair goes
        batch = ask(db, fake, pair)
        assert fake.queries == ['"台積電" 調升目標價'] and batch.requests == 1
        assert real(db, NOW.date()).requests == 3
        # the slow empty answer's second try is taken from the cap too
        ls._bump_chat(db, NOW.date(), requests=-1)
        slow = FakeClient(reply(latency=9.0), good())
        ask(db, slow, ['"台積電"'], 300)
        assert len(slow.bodies) == 1 and real(db, NOW.date()).requests == 3


def test_the_analysts_two_requests_start_one_interval_apart(engine, aiset):
    """The real client and limiter: the second request starts one interval after the first starts."""
    import httpx

    starts: list[float] = []
    clock = [0.0]

    def handler(request: httpx.Request) -> httpx.Response:
        starts.append(clock[0])
        return httpx.Response(200, json=answer())

    limiter = ls.RateLimiter(per_host={ls.HOST: 1.5})
    limiter._clock = lambda: clock[0]

    def sleep(s: float) -> None:
        clock[0] += s

    limiter._sleep = sleep
    client = ls.LangSearchClient(KEY, limiter=limiter, transport=httpx.MockTransport(handler))
    with Session(engine) as db:
        batch = ls.chat_search(db, aiset, ['"台積電" 調升目標價', '"台積電" 調降目標價'], "2026-08-19..2026-11-17",
                               max_characters=600, client=client, clock=lambda: NOW, sleep=lambda s: None)
    assert batch.requests == 2 and sorted(starts) == [0.0, 1.5]


def test_no_text_or_key_in_logs(ctx, lsfake, caplog):
    lsfake(good())
    with caplog.at_level(logging.DEBUG):
        run(ctx, symbol="2330", intent="news")
    assert caplog.records and EXCERPT not in caplog.text and KEY not in caplog.text and "Bearer" not in caplog.text
    assert GOOD_TITLES[0] not in caplog.text  # not even a title


def test_status_shows_the_ai_day(engine, aiset):
    with Session(engine) as db:
        ls._bump_chat(db, NOW.date(), requests=2, tokens=1234, at=NOW)
        st = ls.status(db, aiset, NOW)
        assert (st["ai_enabled"], st["ai_requests"], st["ai_tokens"], st["ai_request_cap"], st["ai_stopped"]) == (
            True, 2, 1234, 300, None)
        assert st["requests"] == 0  # the worker's day is apart
        assert ls.last_request_at(db) == NOW  # the gap between requests counts the AI's too


def test_admin_overview_takes_an_ai_refusal(engine, aiset):
    """An AI request refused (429) books ``quota`` on the AI's day: /admin's schema takes it (it allowed only
    ``contract``, so the overview would have failed validation for the rest of the UTC day)."""
    from forliosa.api.schemas_admin import AdminLangSearch
    from forliosa.services.admin import langsearch_summary

    with Session(engine) as db:
        ls._bump_chat(db, NOW.date(), requests=1, at=NOW)
        ls._book_outcome(db, NOW.date(), NOW, ls.LangSearchQuota("LangSearch HTTP 429"), 1000, side="chat")
        st = ls.status(db, aiset, NOW)
        assert (st["stopped"], st["ai_stopped"]) == ("quota", "quota")
        out = AdminLangSearch.model_validate(langsearch_summary(db, NOW))
        assert (out.stopped, out.ai_stopped) == ("quota", "quota")
