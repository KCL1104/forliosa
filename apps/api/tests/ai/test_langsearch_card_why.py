"""The stock page's 法人觀點 card and 為什麼漲跌 sentence ask LangSearch first (產品負責人 2026-11-17, part 2): the
measured queries and filter of ``forliosa.ai.tw_news``, the AI's shared daily cap and the key's stop state, a cheap
extraction (card) or a sentence from the kept articles (why), and the web search exactly as before whenever
LangSearch gives nothing usable, is stopped or over its cap, or the switch is off. The LangSearch excerpt reaches
Claude in that one request only: no database row, API response or log line holds it. No network: LangSearch answers
through a scripted client, Claude through the fake Messages API. Every text here is SYNTHETIC."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy.orm import Session

from forliosa.ai import analyst, research
from forliosa.ai import tw_news as tw
from forliosa.ai import why as why_mod
from forliosa.ai.prompts import ANALYST_LS_SYSTEM, ANALYST_SYSTEM, WHY_SYSTEM, WHY_SYSTEM_TW, WHY_SYSTEM_TW_NO_INDEX
from forliosa.db import Base
from forliosa.models import AiAnalystViews, AiUsage, AiWhyCache, AiWhyResearch
from forliosa.news import langsearch as ls
from forliosa.news.outlets import outlet_name
from forliosa.services import stock as stock_svc
from tests.ai.conftest import API
from tests.ai.fake_anthropic import search_citation, server_tool_use, text, tool_use, web_search_result

NOW = datetime(2026, 11, 17, 10, 40, tzinfo=UTC)  # Tuesday 18:40 Taipei, a trading day
DAY = date(2026, 11, 17)
KEY = "sk-ls-card-5d0a91"
CARD = f"{API}/instruments/2330/analyst-views"
WHY = f"{API}/instruments/2330/why"

# -- LangSearch: the 法人 articles (dates in the URLs) ---------------------------------------------------------------
A1 = "https://www.cna.com.tw/news/afe/202611140123.aspx"
A2 = "https://www.ctee.com.tw/news/20261110700053-430502"
T1 = "外資調升台積電目標價"
T2 = "台積電法說後投顧評等出爐"
MARK = "法說會後先進製程需求續強"  # a piece of the first excerpt that must never leave the request
S1 = (f"摩根士丹利指出{MARK}，調升台積電目標價至2,400元，維持優於大盤評等。"
      "高盛維持台積電買進評等，目標價2,300元。")
S2 = "花旗調降台積電評等至中立，目標價1,900元。凱基投顧維持台積電增加持股評等，目標價2,200元。"
MARK2 = "凱基投顧維持台積電增加持股"
# -- LangSearch: the 為什麼漲跌 articles -----------------------------------------------------------------------------
W1 = "https://www.cna.com.tw/news/afe/202611170045.aspx"
WT1 = "台積電股價走弱 外資賣超擴大"
WMARK = "市場擔心先進製程訂單在明年上半年放緩"
WS1 = f"台積電今天股價下跌，外資賣超擴大，{WMARK}，拖累權值股表現。"


def page(name: str, url: str, snippet: str, published: str = "2026-11-14T02:00:00.000Z") -> dict[str, Any]:
    return {"name": name, "url": url, "datePublished": published, "snippet": snippet}


def reply(*pages: dict[str, Any], status: int = 200) -> ls.Reply:
    return ls.Reply(status, {"code": 200, "data": {"webPages": {"value": list(pages)}}}, 10, 900, 2.0)


ANALYST_REPLY = reply(page(T1, A1, S1), page(T2, A2, S2, "2026-11-10T03:00:00.000Z"))
WHY_REPLY = reply(page(WT1, W1, WS1, "2026-11-17T05:00:00.000Z"))
NOTHING = reply(page("美股收盤 道瓊上漲", "https://www.example.com/us/markets/202611170001", "道瓊工業指數上漲。"))


class FakeClient:
    def __init__(self, *replies: ls.Reply) -> None:
        self.replies = list(replies)
        self.bodies: list[dict[str, Any]] = []

    def post(self, body: dict[str, Any]) -> ls.Reply:
        self.bodies.append(dict(body))
        return self.replies[min(len(self.bodies) - 1, len(self.replies) - 1)]

    def close(self) -> None:
        pass

    @property
    def queries(self) -> list[str]:
        return [b["query"] for b in self.bodies]


@pytest.fixture()
def clock(monkeypatch):
    """The card's, the sentence's and LangSearch's clocks at NOW; card generations run inline via ``jobs``."""
    started: list = []
    monkeypatch.setattr(analyst, "spawn", lambda job, name: started.append(job))
    monkeypatch.setattr(analyst, "now_utc", lambda: NOW)
    monkeypatch.setattr(why_mod, "now_utc", lambda: NOW)
    monkeypatch.setattr(tw, "_clock", lambda: NOW)
    monkeypatch.setattr(tw, "_sleep", lambda s: None)
    monkeypatch.setattr(tw, "tier_for", lambda db, md, info, settings: "large")
    return started


@pytest.fixture()
def langsearch(ai_env, monkeypatch, clock):
    """AI_LANGSEARCH_ENABLED with a key; LangSearch answers from the scripted client."""
    ai_env(AI_LANGSEARCH_ENABLED="true", LANGSEARCH_API_KEY=KEY, AI_WHY_ENABLED=1, AI_WHY_BLOCKING=1)
    holder = {"client": FakeClient(ANALYST_REPLY)}
    monkeypatch.setattr(ls.LangSearchClient, "from_settings", lambda settings: holder["client"])

    def use(*replies: ls.Reply) -> FakeClient:
        holder["client"] = FakeClient(*replies)
        return holder["client"]

    return use


@pytest.fixture()
def rule_why(monkeypatch):
    rule = {"symbol": "2330.TW", "show": True, "headline": "台積電今天下跌 3.1%", "trade_date": DAY.isoformat(),
            "as_of": "2026-11-17T13:30:00+08:00", "reasons": [{"kind": "price_move", "text": "今天下跌 3.1%"}],
            "sources": ["Forliosa 規則計算"]}
    monkeypatch.setattr(stock_svc, "why", lambda db, md, symbol: dict(rule))
    return rule


def every_row(engine) -> str:
    """Every row of every table, as text (JSON columns included)."""
    out = []
    with engine.connect() as c:
        for t in Base.metadata.sorted_tables:
            out += [json.dumps([str(v) if not isinstance(v, dict | list) else v for v in r], ensure_ascii=False,
                               default=str) for r in c.execute(t.select())]
    return "\n".join(out)


def deployment_logs(caplog) -> None:
    """The deployment's level (the SDK's own debug log holds every request body), ours at DEBUG."""
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.DEBUG, logger="forliosa")


def report(*items: dict[str, Any]) -> dict:
    return tool_use("toolu_r", "report_analyst_views", {"items": list(items)})


def entry(institution: str, url: str, action: str, rating: str | None, target: float | None,
          when: str = "2026-11-14") -> dict[str, Any]:
    return {"url": url, "institution": institution, "action": action, "rating_text": rating, "target_price": target,
            "currency": "TWD", "date": when}


THREE = [entry("摩根士丹利", A1, "調升", "優於大盤", 2400), entry("高盛", A1, "維持", "買進", 2300),
         entry("花旗", A2, "調降", "中立", 1900, "2026-11-10")]
WEB_RESULTS = [("https://money.udn.com/money/story/5607/9101", "大摩調升台積電目標價至2,450元", "November 12, 2026"),
               ("https://news.cnyes.com/news/id/6200001", "瑞銀維持台積電買進評等", "2026-11-11T09:00:00Z")]


def web_card(fake) -> None:
    """The web-search card, as before: one search, two reports."""
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "台積電 目標價"}),
               {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1",
                "content": [{"type": "web_search_result", "url": u, "title": t, "page_age": a,
                             "encrypted_content": "E"} for u, t, a in WEB_RESULTS]},
               report(entry("摩根士丹利", WEB_RESULTS[0][0], "調升", "加碼", 2450, "2026-11-12"),
                      entry("瑞銀", WEB_RESULTS[1][0], "維持", "買進", 2350, "2026-11-11")),
               stop_reason="tool_use", usage={"server_tool_use": {"web_search_requests": 1}})


def web_why(fake, sentence: str = "法說會釋出保守展望，股價走弱。") -> None:
    fake.reply(server_tool_use("srvtoolu_w", "web_search", {"query": "台積電 2026-11-17"}),
               web_search_result("srvtoolu_w", [{"url": "https://www.cna.com.tw/n1", "title": "中央社",
                                                 "encrypted_content": "E"}]),
               text(sentence, [search_citation("https://www.cna.com.tw/n1", "中央社", "法說會釋出保守展望")]),
               usage={"server_tool_use": {"web_search_requests": 1}})


def run_card(client, jobs) -> dict:
    assert client.post(CARD).json()["status"] == "pending"
    jobs.pop()()
    return client.get(CARD).json()


def location(url: str, title: str, cited: str) -> dict:
    return {"type": "search_result_location", "source": url, "title": title, "cited_text": cited,
            "search_result_index": 0, "start_block_index": 0, "end_block_index": 1}


# -- the card ------------------------------------------------------------------------------------------------------
def test_card_from_langsearch(client, pool, fake, langsearch, clock, engine, caplog):
    ls_client = langsearch(ANALYST_REPLY)
    fake.reply(report(*THREE), stop_reason="tool_use")
    deployment_logs(caplog)
    out = run_card(client, clock)
    assert out["status"] == "ready" and out["as_of"].startswith("2026-11-17T18:40")
    assert out["items"] == [
        {"institution": "摩根士丹利", "action": "調升", "rating_text": "優於大盤", "target_price": 2400.0,
         "currency": "TWD", "date": "2026-11-14", "source_title": T1, "url": A1, "unnamed": False, "old": False},
        {"institution": "高盛", "action": "維持", "rating_text": "買進", "target_price": 2300.0, "currency": "TWD",
         "date": "2026-11-14", "source_title": T1, "url": A1, "unnamed": False, "old": False},
        {"institution": "花旗", "action": "調降", "rating_text": "中立", "target_price": 1900.0, "currency": "TWD",
         "date": "2026-11-10", "source_title": T2, "url": A2, "unnamed": False, "old": False},
    ]
    # LangSearch: the large-cap 法人 queries, 90 days, 600 characters, sent once each
    assert ls_client.queries == ['"台積電" 調升目標價', '"台積電" 調降目標價']
    assert {b["freshness"] for b in ls_client.bodies} == {"2026-08-19..2026-11-17"}
    assert {b["contents"]["text"]["max_characters"] for b in ls_client.bodies} == {600}
    # one cheap extraction call: AI_MODEL, no web search, the excerpts as search results (this request only)
    assert len(fake.requests) == 1
    req = fake.requests[0]["body"]
    assert req["model"] == "claude-haiku-5-5" and req["system"] == ANALYST_LS_SYSTEM
    assert [t["name"] for t in req["tools"]] == ["report_analyst_views"] and req["output_config"] == {"effort": "low"}
    content = req["messages"][0]["content"]
    assert [(b["type"], b["source"]) for b in content[:-1]] == [("search_result", A1), ("search_result", A2)]
    assert MARK in content[0]["content"][0]["text"] and "[1]" not in json.dumps(content, ensure_ascii=False)
    assert content[-1]["type"] == "text" and "台積電（2330.TW，上市" in content[-1]["text"]
    # charged like before; the AI's day counts both requests (the cap the chat and 為什麼漲跌 share)
    with Session(engine) as db:
        rows = db.query(AiUsage).filter(AiUsage.feature == "analyst").order_by(AiUsage.id).all()
        assert [r.stop_reason for r in rows] == ["started", "tool_use"] and rows[1].web_search_requests == 0
        assert ls.read_chat_usage(db, DAY).requests == 2
        assert db.get(AiAnalystViews, ("2330.TW", DAY)).model == "claude-haiku-5-5"
    # the excerpt is nowhere: not in a row, the API's JSON or the log
    for where in (every_row(engine), json.dumps(out, ensure_ascii=False), caplog.text):
        assert MARK not in where and MARK2 not in where
    assert T1 not in caplog.text and KEY not in caplog.text


def test_card_falls_back_with_fewer_than_two_named_firms(client, pool, fake, langsearch, clock, engine):
    langsearch(ANALYST_REPLY)
    # one named firm and an unnamed one: not enough for the card
    fake.reply(report(entry("摩根士丹利", A1, "調升", "優於大盤", 2400), entry("美系外資", A2, "維持", "買進", 2200)),
               stop_reason="tool_use")
    web_card(fake)
    out = run_card(client, clock)
    assert out["status"] == "ready" and [i["institution"] for i in out["items"]] == ["摩根士丹利", "瑞銀"]
    assert [i["url"] for i in out["items"]] == [WEB_RESULTS[0][0], WEB_RESULTS[1][0]]
    second = fake.requests[1]["body"]  # the web search, unchanged
    assert second["system"] == ANALYST_SYSTEM and [t["name"] for t in second["tools"]] == [
        "web_search", "report_analyst_views"]
    assert isinstance(second["messages"][0]["content"], str) and MARK not in json.dumps(second, ensure_ascii=False)
    assert MARK not in every_row(engine)
    with Session(engine) as db:  # the web model's entry, both calls charged to the generation
        assert db.get(AiAnalystViews, ("2330.TW", DAY)).model == "claude-haiku-5-5"
        assert db.query(AiUsage).filter(AiUsage.feature == "analyst").count() == 3


def test_card_falls_back_when_langsearch_keeps_nothing(client, pool, fake, langsearch, clock):
    ls_client = langsearch(NOTHING)
    web_card(fake)
    out = run_card(client, clock)
    assert out["status"] == "ready" and len(out["items"]) == 2
    assert len(ls_client.bodies) == 2 and len(fake.requests) == 1  # no extraction call: straight to the web
    assert fake.requests[0]["body"]["system"] == ANALYST_SYSTEM


def test_card_falls_back_when_the_daily_cap_is_used(client, pool, fake, langsearch, clock, engine):
    ls_client = langsearch(ANALYST_REPLY)
    with Session(engine) as db:  # the chat used the AI's 300 requests of the day
        ls._bump_chat(db, DAY, requests=300, at=NOW)
    web_card(fake)
    out = run_card(client, clock)
    assert out["status"] == "ready" and ls_client.bodies == []
    assert fake.requests[0]["body"]["system"] == ANALYST_SYSTEM


def test_shared_cap_card_then_why(client, pool, fake, langsearch, clock, rule_why, ai_env, engine):
    """The card's two requests and the sentence's one come out of the same AI cap."""
    ai_env(AI_LANGSEARCH_MAX_REQUESTS_PER_DAY=2)
    ls_client = langsearch(ANALYST_REPLY)
    fake.reply(report(*THREE), stop_reason="tool_use")
    assert run_card(client, clock)["status"] == "ready"
    web_why(fake)
    w = client.get(WHY).json()
    assert w["ai"] is True and len(ls_client.bodies) == 2  # the sentence asked nothing: the cap was used
    assert fake.requests[1]["body"]["system"] == WHY_SYSTEM


def test_stopped_key_falls_back_and_stays_stopped(client, pool, fake, langsearch, clock, rule_why, engine):
    """A 429 on the card's request stops the whole key until 00:00 UTC (the news worker too): the card and then the
    sentence take the web search, and LangSearch is not asked again."""
    ls_client = langsearch(reply(status=429))
    web_card(fake)
    assert run_card(client, clock)["status"] == "ready"
    asked = len(ls_client.bodies)
    assert asked >= 1 and fake.requests[0]["body"]["system"] == ANALYST_SYSTEM
    with Session(engine) as db:
        assert ls.read_chat_usage(db, DAY).stopped == "quota" and ls.key_stopped(db, DAY) == "quota"
    web_why(fake)
    assert client.get(WHY).json()["ai"] is True
    assert len(ls_client.bodies) == asked and fake.requests[1]["body"]["system"] == WHY_SYSTEM


def test_card_switch_off_is_the_old_card(client, pool, fake, clock, monkeypatch):
    monkeypatch.setattr(tw, "fetch", lambda *a, **k: pytest.fail("LangSearch asked with the switch off"))
    web_card(fake)
    out = run_card(client, clock)
    assert out["status"] == "ready" and len(fake.requests) == 1
    req = fake.requests[0]["body"]
    assert req["system"] == ANALYST_SYSTEM and [t["name"] for t in req["tools"]] == ["web_search",
                                                                                     "report_analyst_views"]


def test_card_us_stock_keeps_the_web_search(client, pool, fake, langsearch, clock, monkeypatch):
    monkeypatch.setattr(tw, "fetch", lambda *a, **k: pytest.fail("LangSearch asked for a US stock"))
    fake.reply(report(), stop_reason="tool_use")
    client.post(f"{API}/instruments/NVDA/analyst-views")
    clock.pop()()
    assert fake.requests[0]["body"]["system"] == ANALYST_SYSTEM


# -- 為什麼漲跌 ------------------------------------------------------------------------------------------------------
def line(url: str, title: str, md: str) -> str:
    return f"{outlet_name(url)}，{md}：{title}"


def test_why_from_langsearch(client, pool, fake, langsearch, rule_why, engine, caplog):
    ls_client = langsearch(WHY_REPLY)
    fake.reply(text("外資賣壓擴大，投資人擔心明年需求轉弱，股價走低。", [location(W1, WT1, f"中央社，11/17：{WS1}")]))
    deployment_logs(caplog)
    w = client.get(WHY).json()
    title_line = line(W1, WT1, "11/17")
    assert w["ai"] is True and w["headline"] == "外資賣壓擴大，投資人擔心明年需求轉弱，股價走低。"
    assert w["citations"] == [{"url": W1, "title": WT1, "cited_text": title_line}]
    assert ls_client.queries == ['"台積電"'] and ls_client.bodies[0]["freshness"] == "2026-11-16..2026-11-17"
    assert ls_client.bodies[0]["contents"]["text"]["max_characters"] == 300
    req = fake.requests[0]["body"]
    # no TAIEX close of the day: no market comparison, and nothing to take the market's move from
    assert "tools" not in req and req["system"] == WHY_SYSTEM_TW_NO_INDEX and req["model"] == "claude-haiku-5-5"
    content = req["messages"][0]["content"]
    assert content[0]["type"] == "search_result" and WMARK in content[0]["content"][0]["text"]
    assert "2026-11-17" in content[-1]["text"] and "加權指數" not in content[-1]["text"]
    with Session(engine) as db:
        row = db.get(AiWhyCache, ("2330.TW", DAY))
        assert row.status == "ok" and row.citations == w["citations"]
        # the chat's shared research is seeded with the title line, never the excerpt
        seeded = db.get(AiWhyResearch, ("2330.TW", DAY, research.AFTER_CLOSE))
        assert seeded is not None and seeded.sources[0]["snippets"] == [title_line]
        assert db.query(AiUsage).filter(AiUsage.feature == "why").count() == 1
        assert ls.read_chat_usage(db, DAY).requests == 1
    for where in (every_row(engine), json.dumps(w, ensure_ascii=False), caplog.text):
        assert WMARK not in where
    assert WT1 not in caplog.text


def test_why_from_langsearch_gets_the_days_index_close(client, pool, fake, langsearch, rule_why, engine,
                                                       monkeypatch):
    """2026-11-17 review: the prompt asked to compare the stock with the TAIEX, but the request had no index figure
    and no search to find one. The official close of the trading day goes into the question (the stock's own move
    beside it) and the comparison rule with it; another day's close is not used."""
    from decimal import Decimal as D

    from forliosa.marketdata.base import QuoteData
    from forliosa.marketdata.service import MarketData
    from forliosa.models import IndexDaily
    from forliosa.timeutil import TAIPEI

    real_quote = MarketData.quote
    q = QuoteData(symbol="2330.TW", price=D("1453.5"), prev_close=D("1500"), open=D("1500"), high=D("1500"),
                  low=D("1450"), volume=None, as_of=datetime(2026, 11, 17, 13, 30, tzinfo=TAIPEI), trade_date=DAY,
                  is_realtime=False, is_demo=True, source="demo")
    monkeypatch.setattr(MarketData, "quote", lambda self, sym, *a, **k: q if sym == "2330.TW" else
                        real_quote(self, sym, *a, **k))
    with Session(engine) as db:
        db.add(IndexDaily(name="發行量加權股價指數", date=date(2026, 11, 16), market="TWSE", close=D("27800"),
                          change=D("100"), change_pct=D("0.0036"), source="twse-openapi"))
        db.commit()
    langsearch(WHY_REPLY)
    fake.reply(text("外資賣壓擴大，股價走低。", [location(W1, WT1, f"中央社，11/17：{WS1}")]))
    assert client.get(WHY).json()["ai"] is True
    first = fake.requests[0]["body"]
    assert first["system"] == WHY_SYSTEM_TW_NO_INDEX  # only the day before: no comparison
    assert "加權指數" not in first["messages"][0]["content"][-1]["text"]
    assert "這一檔：跌 3.10%（11/17）" in first["messages"][0]["content"][-1]["text"]

    with Session(engine) as db:
        db.add(IndexDaily(name="發行量加權股價指數", date=DAY, market="TWSE", close=D("27216.2"), change=D("-583.8"),
                          change_pct=D("0.0210"), source="twse-openapi"))
        db.query(AiWhyCache).delete()
        db.commit()
    langsearch(WHY_REPLY)
    fake.reply(text("外資賣壓擴大，股價走低。", [location(W1, WT1, f"中央社，11/17：{WS1}")]))
    assert client.get(WHY).json()["ai"] is True
    req = fake.requests[-1]["body"]
    question = req["messages"][0]["content"][-1]["text"]
    assert req["system"] == WHY_SYSTEM_TW and "2 個百分點" in WHY_SYSTEM_TW and "附上的那個數字" in WHY_SYSTEM_TW
    assert "加權指數：跌 2.10%（11/17 收盤）" in question and "這一檔：跌 3.10%（11/17）" in question
    assert "2 個百分點" not in WHY_SYSTEM_TW_NO_INDEX and "不要寫大盤漲跌多少" in WHY_SYSTEM_TW_NO_INDEX


@pytest.mark.parametrize("kind", ["none", "no_citation", "pasted"])
def test_why_falls_back_to_the_web_search(client, pool, fake, langsearch, rule_why, engine, kind):
    langsearch(WHY_REPLY)
    if kind == "none":
        fake.reply(text("NONE"))
    elif kind == "no_citation":
        fake.reply(text("外資賣壓擴大，股價走低。"))
    else:  # a clause of the excerpt word for word
        fake.reply(text(f"{WMARK}，拖累權值股表現。", [location(W1, WT1, WS1)]))
    web_why(fake)
    w = client.get(WHY).json()
    assert w["ai"] is True and w["headline"] == "法說會釋出保守展望，股價走弱。"
    assert w["citations"][0]["url"] == "https://www.cna.com.tw/n1"
    second = fake.requests[1]["body"]
    assert second["system"] == WHY_SYSTEM and [t["name"] for t in second["tools"]] == ["web_search"]
    assert WMARK not in json.dumps(second, ensure_ascii=False) and WMARK not in every_row(engine)
    with Session(engine) as db:
        assert db.query(AiUsage).filter(AiUsage.feature == "why").count() == 2


def test_why_nothing_kept_goes_straight_to_the_web(client, pool, fake, langsearch, rule_why):
    ls_client = langsearch(NOTHING)
    web_why(fake)
    assert client.get(WHY).json()["ai"] is True
    assert len(ls_client.bodies) == 1 and len(fake.requests) == 1
    assert fake.requests[0]["body"]["system"] == WHY_SYSTEM


def test_why_cap_used_goes_to_the_web(client, pool, fake, langsearch, rule_why, engine):
    ls_client = langsearch(WHY_REPLY)
    with Session(engine) as db:
        ls._bump_chat(db, DAY, tokens=3_000_000, at=NOW)  # the token cap this time
    web_why(fake)
    assert client.get(WHY).json()["ai"] is True and ls_client.bodies == []
    assert fake.requests[0]["body"]["system"] == WHY_SYSTEM


def test_why_switch_off_is_the_old_sentence(client, pool, fake, clock, rule_why, ai_env, monkeypatch):
    ai_env(AI_WHY_ENABLED=1, AI_WHY_BLOCKING=1)
    monkeypatch.setattr(tw, "fetch", lambda *a, **k: pytest.fail("LangSearch asked with the switch off"))
    web_why(fake)
    w = client.get(WHY).json()
    assert w["ai"] is True and w["citations"] == [
        {"url": "https://www.cna.com.tw/n1", "title": "中央社", "cited_text": "法說會釋出保守展望"}]
    req = fake.requests[0]["body"]
    assert req["system"] == WHY_SYSTEM and [t["name"] for t in req["tools"]] == ["web_search"]
    assert isinstance(req["messages"][0]["content"], str)


def test_why_key_missing_is_the_old_sentence(client, pool, fake, clock, rule_why, ai_env, monkeypatch):
    ai_env(AI_WHY_ENABLED=1, AI_WHY_BLOCKING=1, AI_LANGSEARCH_ENABLED="true")  # no LANGSEARCH_API_KEY
    monkeypatch.setattr(tw, "fetch", lambda *a, **k: pytest.fail("LangSearch asked without a key"))
    web_why(fake)
    assert client.get(WHY).json()["ai"] is True and fake.requests[0]["body"]["system"] == WHY_SYSTEM


def test_shared_research_note_points_to_langsearch_first():
    """A chat turn answering from the shared research looks newer Taiwan news up in tw_news_search before the web
    search when the tool is offered; without it (and for a US stock) the note is as before."""
    from forliosa.marketdata.base import InstrumentInfo

    entry_ = research.Research(facts=None, sources=[{"url": W1, "title": WT1, "snippets": ["中央社，11/17：標題"]}],
                               one_liner=None, updated_at=NOW, searches=1)
    tsmc = InstrumentInfo("2330.TW", "2330", "台積電", "TWSE", "stock", "TWD")
    nvda = InstrumentInfo("NVDA", "NVDA", "NVIDIA", "US", "stock", "USD")
    tw_found = research.Lookup(research.Key("2330.TW", "TWSE", DAY, research.AFTER_CLOSE), tsmc, entry_)
    us_found = research.Lookup(research.Key("NVDA", "US", date(2026, 11, 16), research.AFTER_CLOSE), nvda, entry_)
    old = ("不用再呼叫 get_news 或 web_search；只有使用者要更新的消息、研究裡缺這一檔或大盤今天的漲跌時，"
           "才再用 web_search 找。")
    assert old in research.note(tw_found) and old in research.note(us_found, tw_news=True)
    new = research.note(tw_found, tw_news=True)
    assert "先用 tw_news_search（intent why_move），不夠或外電再用 web_search" in new and old not in new
