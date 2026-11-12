"""Analyst views: shared per symbol per trading day, charged to the user who triggered the search, every item
grounded in the search results the model received (URL + article date), never Forliosa's own opinion."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from forliosa.ai import analyst
from forliosa.ai.prompts import ANALYST_SYSTEM, ANALYST_TOOL, CHAT_SYSTEM
from forliosa.ai.tools import excluded_tools, reset_excluded_tools
from forliosa.marketdata.base import InstrumentInfo
from forliosa.models import AiAnalystViews, AiUsage
from tests.ai.conftest import API, KEYS
from tests.ai.fake_anthropic import server_tool_use, text, tool_use

NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)  # Thursday 14:00 Taipei
TODAY = date(2026, 11, 12)
URL = f"{API}/instruments/2330/analyst-views"
TSMC = InstrumentInfo("2330.TW", "2330", "台積電", "TWSE", "stock", "TWD")
NVDA = InstrumentInfo("NVDA", "NVDA", "NVIDIA", "US", "stock", "USD")


@pytest.fixture()
def jobs(monkeypatch):
    """Background generations are collected instead of started; ``jobs.pop()()`` runs one inline."""
    started: list = []
    monkeypatch.setattr(analyst, "spawn", lambda job, name: started.append(job))
    monkeypatch.setattr(analyst, "now_utc", lambda: NOW)
    yield started
    reset_excluded_tools()


def results_block(tid: str, results: list[tuple[str, str, str | None]]) -> dict:
    return {"type": "web_search_tool_result", "tool_use_id": tid,
            "content": [{"type": "web_search_result", "url": u, "title": t, "page_age": a, "encrypted_content": "E"}
                        for u, t, a in results]}


RESULTS = [
    ("https://money.udn.com/money/story/5607/9101", "大摩調升台積電目標價至1,350元", "November 10, 2026"),
    ("https://www.cna.com.tw/news/afe/202611050123.aspx", "高盛維持台積電買進評等", None),
    ("https://news.cnyes.com/news/id/6200001", "美系外資調降台積電評等至中立", "2026-10-28T09:00:00Z"),
]


def item(institution: str, url: str, **kw) -> dict:
    return {"institution": institution, "action": kw.pop("action", "維持"), "currency": kw.pop("currency", "TWD"),
            "date": kw.pop("date", "2026-11-10"), "url": url, **kw}


def answer(fake, items: list[dict], results=RESULTS) -> None:
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "台積電 目標價"}),
               results_block("srvtoolu_1", results),
               tool_use("toolu_r", "report_analyst_views", {"items": items}),
               stop_reason="tool_use", usage={"server_tool_use": {"web_search_requests": 1}})


GOOD = [
    item("摩根士丹利", RESULTS[0][0], action="調升", rating_text="加碼", target_price=1350),
    item("高盛", RESULTS[1][0], rating_text="買進", target_price=1300, date="2026-11-05"),
    item("美系外資 C", RESULTS[2][0], action="調降", rating_text="中立"),
]


def test_get_post_poll_then_shared_by_everyone(client, other_client, pool, fake, jobs, engine):
    assert client.get(URL).json() == {"status": "none", "symbol": "2330.TW", "as_of": None, "expires_at": None,
                                      "items": [], "disclaimer": analyst.ANALYST_DISCLAIMER, "notes": []}
    answer(fake, GOOD)
    r = client.post(URL)
    assert r.status_code == 200 and r.json()["status"] == "pending" and len(jobs) == 1
    assert client.get(URL).json()["status"] == "pending" and fake.requests == []  # off the request thread
    assert other_client.post(URL).json()["status"] == "pending" and len(jobs) == 1  # no second search
    jobs.pop()()
    out = other_client.get(URL).json()
    assert out["status"] == "ready" and out["as_of"].startswith("2026-11-12T14:00")
    assert out["expires_at"] == "2026-11-13T14:00:00+08:00"
    assert out["items"] == [
        {"institution": "摩根士丹利", "action": "調升", "rating_text": "加碼", "target_price": 1350.0,
         "currency": "TWD",
         "date": "2026-11-10", "source_title": "大摩調升台積電目標價至1,350元", "url": RESULTS[0][0]},
        {"institution": "高盛", "action": "維持", "rating_text": "買進", "target_price": 1300.0, "currency": "TWD",
         "date": "2026-11-05", "source_title": "高盛維持台積電買進評等", "url": RESULTS[1][0]},
        {"institution": "美系外資 C", "action": "調降", "rating_text": "中立", "target_price": None, "currency": "TWD",
         "date": "2026-10-28", "source_title": "美系外資調降台積電評等至中立", "url": RESULTS[2][0]},
    ]
    # once ready, POST from anyone returns it: no new search, no new charge
    assert other_client.post(URL).json()["status"] == "ready" and jobs == [] and len(fake.requests) == 1

    req = fake.requests[0]["body"]
    assert req["model"] == "claude-haiku-5-5" and "stream" not in req and req["system"] == ANALYST_SYSTEM
    assert [t["name"] for t in req["tools"]] == ["web_search", "report_analyst_views"]  # no web_fetch
    assert req["tools"][0]["max_uses"] == 3 and req["tools"][1]["strict"] is True
    assert req["output_config"] == {"effort": "medium"}
    question = req["messages"][0]["content"]
    assert "台積電（2330.TW，上市，以新台幣交易）" in question and "2026-08-14" in question


def test_prompts_keep_chat_rule_and_quote_only(client):
    assert "也不給目標價" in CHAT_SYSTEM  # the chat prompt is unchanged
    assert ANALYST_SYSTEM != CHAT_SYSTEM
    for rule in ("不給你自己的評等、目標價或看法", "不計算平均", "上漲空間", "不排名", "不寫買進、賣出",
                 "逐字使用搜尋結果"):
        assert rule in ANALYST_SYSTEM
    assert ANALYST_TOOL["strict"] is True


def test_charged_to_the_triggering_user_only(client, other_client, pool, fake, jobs, engine):
    answer(fake, GOOD)
    client.post(URL)
    jobs.pop()()
    other_client.post(URL)
    mine, theirs = client.get(f"{API}/ai/usage").json(), other_client.get(f"{API}/ai/usage").json()
    assert mine["messages_today"] == 1 and mine["tokens_month"] > 0 and mine["cost_usd_month"] > 0
    assert theirs["messages_today"] == 0 and theirs["tokens_month"] == 0
    with Session(engine) as db:
        rows = db.query(AiUsage).filter(AiUsage.feature == "analyst").order_by(AiUsage.id).all()
        assert [r.stop_reason for r in rows] == ["started", "tool_use"]
        assert len({r.thread_id for r in rows}) == 1 and rows[1].web_search_requests == 1
        assert rows[1].key_slot is not None


def test_daily_limit_blocks_a_new_search(client, pool, fake, jobs, ai_env):
    ai_env(AI_DAILY_MESSAGE_LIMIT=1)
    answer(fake, GOOD)
    client.post(URL)
    jobs.pop()()
    r = client.post(f"{API}/instruments/NVDA/analyst-views")
    assert r.status_code == 429 and r.json()["error"]["code"] == "ai_daily_limit" and jobs == []
    assert client.post(URL).json()["status"] == "ready"  # an existing entry is still free


def test_stocks_only(client, pool, jobs):
    for method in ("get", "post"):
        r = getattr(client, method)(f"{API}/instruments/0050/analyst-views")
        assert r.status_code == 422 and r.json()["error"]["code"] == "analyst_views_stocks_only"
    assert client.get(f"{API}/instruments/NOPE123/analyst-views").status_code == 404
    assert jobs == []


def test_no_key_is_503(client, jobs):
    r = client.post(URL)
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_unavailable"


def test_turned_off_answers_unavailable_without_charge(client, pool, fake, jobs, ai_env):
    ai_env(AI_ANALYST_ENABLED=0)
    out = client.post(URL).json()
    assert out["status"] == "unavailable" and out["notes"] == [analyst.NOTE_OFF] and jobs == []
    assert client.get(f"{API}/ai/usage").json()["messages_today"] == 0


def test_deleted_24_hours_after_creation(client, pool, fake, jobs, engine, monkeypatch):
    friday = NOW + timedelta(days=1)  # Friday 14:00 Taipei; Saturday reads Friday's entry
    monkeypatch.setattr(analyst, "now_utc", lambda: friday)
    answer(fake, GOOD)
    client.post(URL)
    jobs.pop()()
    monkeypatch.setattr(analyst, "now_utc", lambda: friday + timedelta(hours=23, minutes=59))
    assert client.get(URL).json()["status"] == "ready"
    monkeypatch.setattr(analyst, "now_utc", lambda: friday + timedelta(hours=24))
    assert client.get(URL).json()["status"] == "none"
    with Session(engine) as db:
        assert db.query(AiAnalystViews).count() == 0


def test_new_trading_day_is_a_new_entry(client, pool, fake, jobs, monkeypatch):
    answer(fake, GOOD)
    client.post(URL)
    jobs.pop()()
    # Friday 08:00 Taipei: a new trading day, although Thursday's entry has not expired yet
    monkeypatch.setattr(analyst, "now_utc", lambda: NOW + timedelta(hours=18))
    assert client.get(URL).json()["status"] == "none"
    # Saturday 01:00 Taipei after a Friday search: still Friday's entry
    answer(fake, GOOD)
    client.post(URL)
    jobs.pop()()
    monkeypatch.setattr(analyst, "now_utc", lambda: NOW + timedelta(hours=35))
    assert client.get(URL).json()["status"] == "ready"


def test_failure_is_unavailable_and_retried_later(client, pool, fake, jobs, monkeypatch):
    fake.error(400, "invalid_request_error", "something else is wrong")
    client.post(URL)
    jobs.pop()()
    out = client.get(URL).json()
    assert out["status"] == "unavailable" and out["items"] == [] and out["notes"] == ["14:10 之後可以再查一次。"]
    assert client.post(URL).json()["status"] == "unavailable" and jobs == []  # no retry storm
    monkeypatch.setattr(analyst, "now_utc", lambda: NOW + timedelta(minutes=10))
    assert client.get(URL).json()["status"] == "none"  # the page offers the search again
    answer(fake, GOOD)
    assert client.post(URL).json()["status"] == "pending"
    jobs.pop()()
    assert client.get(URL).json()["status"] == "ready"
    assert client.get(f"{API}/ai/usage").json()["messages_today"] == 2  # both searches counted


def test_refused_web_search_is_excluded(client, pool, fake, jobs):
    fake.error(400, "invalid_request_error", "Requests from this sandbox are not allowed to use tool "
                                             "web_search_20260318")
    client.post(URL)
    jobs.pop()()
    assert client.get(URL).json()["status"] == "unavailable"
    assert [t["type"] for t in excluded_tools()] == ["web_search_20260318"]


def test_refusal_and_text_only_answers(client, pool, fake, jobs):
    fake.reply(text(""), stop_reason="refusal")
    client.post(URL)
    jobs.pop()()
    assert client.get(URL).json()["status"] == "unavailable"


def test_text_answer_gets_one_nudge_on_the_same_slot(client, pool, fake, jobs):
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "台積電 目標價"}),
               results_block("srvtoolu_1", RESULTS), text("大摩調升目標價。"))
    fake.reply(tool_use("toolu_r", "report_analyst_views", {"items": GOOD[:1]}), stop_reason="tool_use")
    client.post(URL)
    jobs.pop()()
    out = client.get(URL).json()
    assert out["status"] == "ready" and [i["institution"] for i in out["items"]] == ["摩根士丹利"]
    assert fake.keys_used[0] == fake.keys_used[1]
    second = fake.requests[1]["body"]["messages"]
    assert second[-1]["role"] == "user" and "report_analyst_views" in second[-1]["content"]
    assert second[-2]["content"][1]["type"] == "web_search_tool_result"  # search results resent unchanged


def test_still_text_after_the_nudge_is_unavailable(client, pool, fake, jobs):
    fake.reply(text("找不到。"))
    fake.reply(text("真的找不到。"))
    client.post(URL)
    jobs.pop()()
    assert client.get(URL).json()["status"] == "unavailable" and len(fake.requests) == 2


def test_pause_turn_continues_on_the_same_slot(client, pool, fake, jobs):
    fake.reply(server_tool_use("srvtoolu_p", "web_search", {"query": "台積電"}), stop_reason="pause_turn")
    answer(fake, GOOD)
    client.post(URL)
    jobs.pop()()
    assert client.get(URL).json()["status"] == "ready"
    assert fake.keys_used[0] == fake.keys_used[1] and fake.keys_used[0] in KEYS
    assert fake.requests[1]["body"]["messages"][-1]["content"][0]["type"] == "server_tool_use"


def test_stale_pending_reads_as_unavailable(client, pool, fake, jobs, monkeypatch):
    answer(fake, GOOD)
    client.post(URL)
    jobs.clear()  # the process died before the job ran
    monkeypatch.setattr(analyst, "now_utc", lambda: NOW + timedelta(minutes=6))
    out = client.get(URL).json()
    assert out["status"] == "unavailable" and out["notes"] == ["14:16 之後可以再查一次。"]


def test_empty_report_is_ready_with_no_items(client, pool, fake, jobs):
    answer(fake, [], results=[("https://news.example.com/2026/11/10/tsmc", "台積電法說會重點整理", None)])
    client.post(URL)
    jobs.pop()()
    out = client.get(URL).json()
    assert out["status"] == "ready" and out["items"] == [] and out["as_of"]


def test_empty_report_despite_rating_headlines_is_not_claimed_as_none(client, pool, fake, jobs):
    answer(fake, [])  # RESULTS have 目標價／評等 headlines
    client.post(URL)
    jobs.pop()()
    assert client.get(URL).json()["status"] == "unavailable"
    # rating aggregators do not count as evidence
    assert analyst.rating_headlines([analyst.SearchResult("https://tipranks.com/x", "NVDA price target", None)]) == 0


# -- verification --------------------------------------------------------------------------------------------
def R(url: str, title: str = "標題", age: str | None = "2026-11-10") -> analyst.SearchResult:
    return analyst.SearchResult(url, title, age)


def reasons(dropped: list[analyst.Dropped]) -> list[str]:
    return [d.reason for d in dropped]


def test_verify_only_urls_from_the_search_results():
    results = [R("https://example.com/a")]
    items, dropped = analyst.verify([item("大摩", "https://example.com/a", target_price=1350),
                                     item("小摩", "https://example.com/made-up", target_price=1400)],
                                    results, TSMC, TODAY)
    assert [i["institution"] for i in items] == ["大摩"] and reasons(dropped) == ["url_not_in_results"]
    # trivial spelling differences of the same URL match (scheme, www, trailing slash, fragment)
    items, _ = analyst.verify([item("大摩", "http://www.example.com/a/#top", target_price=1)], results, TSMC, TODAY)
    assert items[0]["url"] == "https://example.com/a"
    # a percent-encoded result URL written back decoded still matches; the shown URL is the search result's own
    encoded = "https://tw.stock.yahoo.com/news/%E5%8F%B0%E7%A9%8D%E9%9B%BB-001000161.html"
    items, _ = analyst.verify([item("伯恩斯坦", "https://tw.stock.yahoo.com/news/台積電-001000161.html",
                                    target_price=3828)], [R(encoded)], TSMC, TODAY)
    assert items[0]["url"] == encoded


def test_verify_uses_the_article_date_and_drops_unverifiable_or_old():
    results = [R("https://a.com/2026/11/09/tsmc", age="2026-01-01"), R("https://b.com/x", age="3 days ago"),
               R("https://c.com/y", age=None), R("https://d.com/z", age="June 1, 2026"),
               R("https://e.com/w", age="2026-11-20")]
    items, dropped = analyst.verify([item("A", "https://a.com/2026/11/09/tsmc", target_price=1, date="2026-10-01"),
                                     item("B", "https://b.com/x", target_price=1),
                                     item("C", "https://c.com/y", target_price=1),
                                     item("D", "https://d.com/z", target_price=1),
                                     item("E", "https://e.com/w", target_price=1)], results, TSMC, TODAY)
    # the URL date wins over page_age and over the model's own date
    assert [(i["institution"], i["date"]) for i in items] == [("A", "2026-11-09"), ("B", "2026-11-09")]
    assert reasons(dropped) == ["date_unverified", "too_old", "future"]


def test_verify_fields_never_invented():
    results = [R(f"https://n.com/{k}") for k in range(8)]
    cands = [item("法人", "https://n.com/0", target_price=1300),                       # unnamed
             item("Analysts", "https://n.com/1", rating_text="Buy"),                   # unnamed
             item("小摩", "https://n.com/2"),                                          # neither rating nor target
             item("美系外資", "https://n.com/3", target_price=250, currency="USD"),     # the ADR's target
             item("美系外資", "https://n.com/4", rating_text="中立", currency="USD"),   # no target: currency moot
             item("大摩", "https://n.com/5", rating_text="加碼", target_price=-1),      # nonsense target → none
             item("高盛", "https://n.com/6", rating_text="x" * 31, target_price=1300.5, action="未註明")]
    items, dropped = analyst.verify(cands, results, TSMC, TODAY)
    assert reasons(dropped) == ["unnamed", "unnamed", "empty", "currency"]
    assert [(i["institution"], i["rating_text"], i["target_price"], i["action"]) for i in items] == [
        ("美系外資", "中立", None, "維持"), ("大摩", "加碼", None, "維持"), ("高盛", None, 1300.5, "")]
    assert all(i["currency"] == "TWD" and i["source_title"] == "標題" for i in items)


def test_verify_newest_first_one_per_institution_at_most_five():
    results = [R(f"https://n.com/{k}", age=f"2026-11-0{k + 1}") for k in range(8)]
    cands = [item(f"機構{k}", f"https://n.com/{k}", rating_text="買進") for k in range(7)]
    cands.append(item("機構 6", "https://n.com/7", rating_text="中立"))  # same institution, newer article
    items, dropped = analyst.verify(cands, results, NVDA, TODAY)
    assert [(i["institution"], i["date"]) for i in items] == [
        ("機構 6", "2026-11-08"), ("機構5", "2026-11-06"), ("機構4", "2026-11-05"), ("機構3", "2026-11-04"),
        ("機構2", "2026-11-03")]
    assert reasons(dropped) == ["duplicate"] and all(i["currency"] == "USD" for i in items)


@pytest.mark.parametrize(("age", "expected"), [
    ("2026-11-10", date(2026, 11, 10)), ("2026-11-09T20:00:00Z", date(2026, 11, 10)),
    ("November 3, 2026", date(2026, 11, 3)), ("Nov 3, 2026", date(2026, 11, 3)), ("3 November 2026", date(2026, 11, 3)),
    ("2026年11月3日", date(2026, 11, 3)), ("2 days ago", date(2026, 11, 10)), ("1 week ago", date(2026, 11, 5)),
    ("5 hours ago", TODAY), ("", None), (None, None), ("yesterday-ish", None),
])
def test_page_age(age, expected):
    assert analyst.date_from_page_age(age, TODAY) == expected


@pytest.mark.parametrize(("url", "expected"), [
    ("https://www.cna.com.tw/news/afe/202611050123.aspx", date(2026, 11, 5)),
    ("https://www.ctee.com.tw/news/20261104700053-430101", date(2026, 11, 4)),
    ("https://www.reuters.com/markets/2026/11/03/tsmc-target/", date(2026, 11, 3)),
    ("https://example.com/2026-10-30-nvda", date(2026, 10, 30)),
    ("https://news.cnyes.com/news/id/6200001", None),
    ("https://example.com/story/20261399", None),
    ("https://2026.example.com/a?d=20261105", None),  # only the path counts
])
def test_url_date(url, expected):
    assert analyst.date_from_url(url) == expected


def test_trading_day_key():
    assert analyst.trading_day(datetime(2026, 11, 14, 2, 0, tzinfo=UTC)) == date(2026, 11, 13)  # Saturday → Friday
    assert analyst.trading_day(datetime(2026, 11, 12, 16, 30, tzinfo=UTC)) == date(2026, 11, 13)  # 00:30 Fri Taipei


def test_reported_items_tolerates_json_strings():
    good = GOOD[:2]
    shapes = [{"items": good}, {"items": json.dumps(good, ensure_ascii=False)},
              {"items": [json.dumps(g, ensure_ascii=False) for g in good]}, json.dumps({"items": good})]
    for inp in shapes:
        block = {"type": "tool_use", "id": "t", "name": "report_analyst_views", "input": inp}
        assert analyst.reported_items([block]) == good
    assert analyst.reported_items([{"type": "tool_use", "id": "t", "name": "report_analyst_views",
                                    "input": {"items": "not json"}}]) == []
    assert analyst.reported_items([text("沒有")]) is None


def test_stringified_report_end_to_end(client, pool, fake, jobs):
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "台積電 目標價"}),
               results_block("srvtoolu_1", RESULTS),
               tool_use("toolu_r", "report_analyst_views", {"items": json.dumps(GOOD, ensure_ascii=False)}),
               stop_reason="tool_use")
    client.post(URL)
    jobs.pop()()
    assert len(client.get(URL).json()["items"]) == 3


def test_aggregators_and_quote_pages_are_not_articles():
    assert not analyst.is_article("https://www.tipranks.com/stocks/nvda/forecast")
    assert not analyst.is_article("https://tw.tradingview.com/symbols/TWSE-2330/forecast-price-target/")
    assert not analyst.is_article("https://tw.stock.yahoo.com/quote/2330.TW")
    assert analyst.is_article("https://tw.stock.yahoo.com/news/abc-001000161.html")
    assert not analyst.is_article("https://www.cnyes.com/twstock/Technical.aspx?code=2330")
    assert analyst.is_article("https://news.cnyes.com/news/id/6200001")
    page = "https://goodinfo.tw/tw/StockDetail.asp?STOCK_ID=2330"
    items, dropped = analyst.verify([item("大摩", page, target_price=1)], [R(page)], TSMC, TODAY)
    assert items == [] and reasons(dropped) == ["not_article"]


def test_search_blocks_aggregators_unless_an_allow_list_is_set(ai_env):
    from forliosa.config import get_settings

    [search] = analyst.search_tools(get_settings())
    assert search["name"] == "web_search" and "tipranks.com" in search["blocked_domains"]
    ai_env(AI_WEB_SEARCH_ALLOWED_DOMAINS="recommended")
    [search] = analyst.search_tools(get_settings())
    assert "blocked_domains" not in search and search["allowed_domains"]
