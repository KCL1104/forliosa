"""Analyst views: shared per symbol per trading day, charged to the user who triggered the search, every item
grounded in the search results the model received (URL + article date), never Forliosa's own opinion."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

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
TSMC = InstrumentInfo("2330.TW", "2330", "台積電", "TWSE", "stock", "TWD", aliases=("TSMC",))
NVDA = InstrumentInfo("NVDA", "NVDA", "NVIDIA", "US", "stock", "USD", aliases=("輝達", "NVIDIA Corporation"))
FUBON = InstrumentInfo("2881.TW", "2881", "富邦金", "TWSE", "stock", "TWD", aliases=("Fubon Financial",))


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
    ("https://news.cnyes.com/news/id/6200001", "花旗調降台積電評等至中立", "2026-10-28T09:00:00Z"),
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
    item("花旗", RESULTS[2][0], action="調降", rating_text="中立"),
]


def test_get_post_poll_then_shared_by_everyone(client, other_client, pool, fake, jobs, engine):
    assert client.get(URL).json() == {
        "status": "none", "symbol": "2330.TW", "as_of": None, "expires_at": None, "items": [],
        "disclaimer": analyst.ANALYST_DISCLAIMER, "notes": [],
        "conference": {"last": None, "next": None, "url": analyst.MOPS_CONFERENCE_URL}}
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
         "currency": "TWD", "date": "2026-11-10", "source_title": "大摩調升台積電目標價至1,350元",
         "url": RESULTS[0][0], "unnamed": False, "old": False},
        {"institution": "高盛", "action": "維持", "rating_text": "買進", "target_price": 1300.0, "currency": "TWD",
         "date": "2026-11-05", "source_title": "高盛維持台積電買進評等", "url": RESULTS[1][0], "unnamed": False,
         "old": False},
        {"institution": "花旗", "action": "調降", "rating_text": "中立", "target_price": None, "currency": "TWD",
         "date": "2026-10-28", "source_title": "花旗調降台積電評等至中立", "url": RESULTS[2][0], "unnamed": False,
         "old": False},
    ]
    # once ready, POST from anyone returns it: no new search, no new charge
    assert other_client.post(URL).json()["status"] == "ready" and jobs == [] and len(fake.requests) == 1

    req = fake.requests[0]["body"]
    assert req["model"] == "claude-haiku-5-5" and "stream" not in req and req["system"] == ANALYST_SYSTEM
    assert [t["name"] for t in req["tools"]] == ["web_search", "report_analyst_views"]  # no web_fetch
    assert req["tools"][0]["max_uses"] == 3 and req["tools"][1]["strict"] is True
    assert req["output_config"] == {"effort": "medium"}
    question = req["messages"][0]["content"]
    assert "台積電（2330.TW，上市，以新台幣交易）" in question and "2026-05-16" in question  # 180 days back


def test_prompts_keep_chat_rule_and_quote_only(client):
    # the chat prompt never gives its own target price; it may quote a named institution's, cited (2026-11-16)
    assert "也不給你自己的目標價" in CHAT_SYSTEM and "轉述具名機構已發表的目標價可以" in CHAT_SYSTEM
    assert ANALYST_SYSTEM != CHAT_SYSTEM
    for rule in ("不給你自己的評等、目標價或看法", "不計算平均", "上漲空間", "不排名", "不寫買進、賣出",
                 "逐字使用搜尋結果"):
        assert rule in ANALYST_SYSTEM
    assert ANALYST_TOOL["strict"] is True


def test_report_tool_has_no_optional_fields():
    """Strict tool input is generated in schema order: an optional field skipped early ended up inside the ``url``
    string in the live smoke. Every field is required (``null`` when missing), ``url`` first."""
    item_schema = ANALYST_TOOL["input_schema"]["properties"]["items"]["items"]
    assert list(item_schema["properties"]) == item_schema["required"] == [
        "url", "institution", "action", "rating_text", "target_price", "currency", "date"]
    assert {"type": "null"} in item_schema["properties"]["rating_text"]["anyOf"]
    assert {"type": "null"} in item_schema["properties"]["target_price"]["anyOf"]
    # nulls verify like missing values
    cand = {"url": RESULTS[1][0], "institution": "高盛", "action": "維持", "rating_text": "買進", "target_price": None,
            "currency": "TWD", "date": "2026-11-05"}
    items, _ = analyst.verify([cand, {**cand, "rating_text": None, "institution": "瑞銀"}],
                              [R(RESULTS[1][0])], TSMC, TODAY)
    assert [(i["institution"], i["rating_text"], i["target_price"]) for i in items] == [("高盛", "買進", None)]


def test_a_field_written_into_the_url_is_not_a_search_result(client, pool, fake, jobs):
    """The live failure: the rest of the item inside the url string. Never matched loosely: unavailable."""
    broken = item("滙豐證券", RESULTS[0][0] + "','target_price':3800,", action="調升")
    answer(fake, [broken])
    client.post(URL)
    jobs.pop()()
    assert client.get(URL).json()["status"] == "unavailable"


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
    answer(fake, [])  # RESULTS have 目標價／評等 headlines about 台積電
    client.post(URL)
    jobs.pop()()
    assert client.get(URL).json()["status"] == "unavailable"


def test_candidates_all_dropped_as_unverifiable_are_not_claimed_as_none(client, pool, fake, jobs, monkeypatch):
    """The model listed reports, but none could be checked (URL not among the results, no readable date): the
    entry is ``unavailable`` (retried after 10 minutes), never a shared "近期查無" for the whole day."""
    results = [("https://news.example.com/a", "台積電法說會重點整理", None)]  # no rating headline, no date
    answer(fake, [item("高盛", "https://news.example.com/a?utm=x", target_price=1300),     # url_not_in_results
                  item("瑞銀", "https://news.example.com/a", rating_text="買進")], results)  # date_unverified
    client.post(URL)
    jobs.pop()()
    out = client.get(URL).json()
    assert out["status"] == "unavailable" and out["items"] == [] and out["notes"] == ["14:10 之後可以再查一次。"]
    monkeypatch.setattr(analyst, "now_utc", lambda: NOW + timedelta(minutes=10))
    assert client.get(URL).json()["status"] == "none"  # can be searched again


def test_candidates_dropped_for_settled_reasons_are_ready_and_empty(client, pool, fake, jobs):
    """Every candidate checked and dropped for what it is (too old, unnamed, no rating): "近期查無" holds."""
    results = [("https://news.example.com/2026/04/01/tsmc", "台積電法說會重點整理", None),
               ("https://news.example.com/2026/11/10/tsmc", "台積電營收創新高", None)]
    answer(fake, [item("高盛", results[0][0], target_price=1300),     # too_old
                  item("法人", results[1][0], target_price=1500)], results)  # unnamed
    client.post(URL)
    jobs.pop()()
    out = client.get(URL).json()
    assert out["status"] == "ready" and out["items"] == []


def test_other_stocks_ratings_do_not_block_an_empty_report(client, pool, fake, jobs):
    """Searching a quieter stock often returns other stocks' ratings: an empty report is then a real "none"."""
    results = [("https://money.udn.com/money/story/5607/9101", "國泰金獲外資調升目標價", "2026-11-10"),
               ("https://news.cnyes.com/news/id/6200001", "外資調升 5 檔目標價", "2026-11-09")]
    answer(fake, [], results)
    client.post(URL)
    jobs.pop()()
    assert client.get(URL).json()["status"] == "ready"


def test_rating_headlines_count_only_this_stock():
    def n(info, *titles, url="https://news.example.com/a", age="2026-11-10"):
        return analyst.rating_headlines([R(url, t, age) for t in titles], info, TODAY)

    assert n(FUBON, "國泰金獲外資調升目標價", "外資調升 5 檔目標價") == 0
    assert n(FUBON, "富邦金獲外資調升目標價", "2881 評等調升") == 2
    assert n(FUBON, "中華信評維持富邦金評級") == 0  # a credit rating, not a broker's
    assert n(TSMC, "Morgan Stanley lifts TSMC price target", "大摩調升台積電目標價") == 2
    assert n(TSMC, "23301 目標價") == 0  # not 2330
    assert n(NVDA, "Nvidia upgrade cycle lifts demand", "NVIDIA earnings preview") == 0
    assert n(NVDA, "Morgan Stanley raises Nvidia price target", "NVDA upgraded to Buy", "輝達獲調升目標價") == 3
    assert n(TSMC, "大摩調升台積電目標價", age="April 1, 2026") == 0  # verifiably older than 180 days
    assert n(TSMC, "大摩調升台積電目標價", age="June 1, 2026") == 1  # 164 days: shown as 舊資料
    # an article whose candidate was dropped for what it is (an unnamed broker older than 30 days) is accounted for
    assert analyst.rating_headlines([R("https://n.com/a", "外資調降台積電目標價", "2026-10-01")], TSMC, TODAY,
                                    frozenset({"https://n.com/a"})) == 0
    assert n(TSMC, "大摩調升台積電目標價", age=None) == 1  # date unknown: still a hint
    # rating aggregators and rating pages do not count as evidence
    assert n(NVDA, "NVDA price target", url="https://tipranks.com/x") == 0
    assert n(NVDA, "NVIDIA Analyst Ratings", url="https://www.benzinga.com/quote/NVDA/analyst-ratings") == 0


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


def test_verify_one_per_institution_folds_aliases():
    results = [R("https://n.com/1", age="2026-11-10"), R("https://n.com/2", age="2026-11-05"),
               R("https://n.com/3", age="2026-11-04"), R("https://n.com/4", age="2026-11-03"),
               R("https://n.com/5", age="2026-11-02")]
    items, dropped = analyst.verify([item("大摩", "https://n.com/1", action="調升", target_price=1500),
                                     item("摩根士丹利", "https://n.com/2", target_price=1300),
                                     item("J.P. Morgan", "https://n.com/3", rating_text="Overweight"),
                                     item("小摩", "https://n.com/4", target_price=1400),
                                     item("美銀證券", "https://n.com/5", rating_text="買進")], results, TSMC, TODAY)
    # the newest of each institution, shown with the report's own wording
    assert [(i["institution"], i["date"]) for i in items] == [
        ("大摩", "2026-11-10"), ("J.P. Morgan", "2026-11-04"), ("美銀證券", "2026-11-02")]
    assert reasons(dropped) == ["duplicate", "duplicate"]
    assert [d.candidate["institution"] for d in dropped] == ["摩根士丹利", "小摩"]


@pytest.mark.parametrize(("name", "key"), [
    ("大摩", "morganstanley"), ("摩根士丹利", "morganstanley"), ("Morgan Stanley", "morganstanley"),
    ("台灣摩根士丹利證券", "morganstanley"), ("大摩分析師", "morganstanley"),
    ("Morgan Stanley analysts", "morganstanley"), ("小摩", "jpmorgan"), ("摩根大通證券", "jpmorgan"),
    ("JPMorgan", "jpmorgan"), ("J.P. Morgan Securities", "jpmorgan"), ("JPMorgan Chase & Co.", "jpmorgan"),
    ("美銀", "bofa"), ("美銀證券", "bofa"), ("美林", "bofa"),
    ("BofA Global Research", "bofa"), ("Bank of America", "bofa"), ("高盛", "goldmansachs"),
    ("Goldman Sachs", "goldmansachs"), ("花旗環球證券", "citi"), ("Citigroup", "citi"), ("Citi", "citi"),
    ("瑞銀", "ubs"), ("UBS", "ubs"), ("野村證券", "nomura"), ("Nomura", "nomura"), ("麥格理", "macquarie"),
    ("Macquarie Capital", "macquarie"), ("匯豐", "hsbc"), ("滙豐證券", "hsbc"), ("HSBC", "hsbc"),
    ("凱基投顧", "凱基"), ("凱基證券", "凱基"), ("Aletheia Capital", "aletheia"),
    # the model often adds the other-language name in parentheses (live smoke 2026-11-12)
    ("伯恩斯坦（Bernstein）", "bernstein"), ("花旗（Citi）", "citi"), ("大和證券（Daiwa）", "daiwa"),
    ("Goldman Sachs (高盛)", "goldmansachs"), ("美系外資（摩根士丹利）", "morganstanley"), ("外資（Analysts）", None),
    # not a named institution
    ("法人", None), ("外資", None), ("美系外資", None), ("歐系外資", None), ("美系外資 C", None), ("外資券商", None),
    ("外資券商 A", None), ("某外資", None), ("某外資券商", None), ("日系券商", None), ("國內投顧", None),
    ("外資分析師", None), ("Analysts", None), ("Wall Street analysts", None), ("Wall Street", None),
    ("brokers", None), ("a U.S. brokerage", None), ("TheStreet", None), ("市場共識", None),
    ("金控龍頭旗下投顧", None), ("老牌投顧", None),  # live 2026-11-16 (家登): describes a firm, does not name it
])
def test_institution_key(name, key):
    assert analyst.institution_key(name) == key


def test_a_real_target_after_a_price_fall_is_kept():
    """2026-11-16: Goldman's NT$4,120 for 台達電 at NT$1,240 (3.3 ×) was dropped as "another currency" by the 3 ×
    bound; the bound is 6 × now. The ADR mix-up only ever shows on the low side."""
    delta = InstrumentInfo("2308.TW", "2308", "台達電", "TWSE", "stock", "TWD", aliases=("DELTA",))
    results = [R(f"https://n.com/{k}") for k in range(3)]
    cands = [item("高盛", "https://n.com/0", target_price=4120), item("花旗", "https://n.com/1", target_price=7500),
             item("小摩", "https://n.com/2", target_price=150)]  # 6.05 × and 0.12 × the price: another currency
    items, dropped = analyst.verify(cands, results, delta, TODAY, reference=1240.0)
    assert [(i["institution"], i["target_price"]) for i in items] == [("高盛", 4120.0)]
    assert reasons(dropped) == ["currency", "currency"]
    assert analyst.TARGET_RATIO_MAX == 6.0


def test_a_twd_target_reported_as_usd_on_an_adr_page_is_dropped():
    """2026-11-16 review: on a US-listed ADR of a Taiwan company the mix-up shows on the high side (NT$145 for 2412
    reported as USD on CHT at US$40 is 3.6 ×), so US stocks keep the 3 × bound."""
    cht = InstrumentInfo("CHT", "CHT", "Chunghwa Telecom", "US", "stock", "USD", aliases=("中華電",))
    results = [R(f"https://n.com/{k}") for k in range(2)]
    cands = [item("凱基投顧", "https://n.com/0", target_price=145, currency="USD"),
             item("Citi", "https://n.com/1", target_price=48, currency="USD")]
    items, dropped = analyst.verify(cands, results, cht, TODAY, reference=40.0)
    assert [i["institution"] for i in items] == ["Citi"] and reasons(dropped) == ["currency"]
    assert analyst.TARGET_RATIO_MAX_US == 3.0


def test_verify_drops_a_target_far_from_the_last_price_as_another_currency():
    """The ADR's USD target reported as TWD (an internal filter: never shown, never compared in the output)."""
    results = [R(f"https://n.com/{k}") for k in range(4)]
    cands = [item("小摩", "https://n.com/0", target_price=400),           # TSM ADR's US$400 marked TWD
             item("伯恩斯坦", "https://n.com/1", target_price=3828),
             item("Aletheia", "https://n.com/2", target_price=5000),
             item("高盛", "https://n.com/3", rating_text="買進")]          # no target: nothing to check
    items, dropped = analyst.verify(cands, results, TSMC, TODAY, reference=2395.0)
    assert [i["institution"] for i in items] == ["伯恩斯坦", "Aletheia", "高盛"] and reasons(dropped) == ["currency"]
    items, dropped = analyst.verify(cands, results, TSMC, TODAY)  # no real price: no ratio check
    assert len(items) == 4 and dropped == []


def test_generation_uses_the_last_real_price_for_the_currency_check(client, pool, fake, jobs, monkeypatch):
    monkeypatch.setattr(analyst, "reference_price", lambda md, symbol: 2395.0 if symbol == "2330.TW" else None)
    answer(fake, [item("小摩", RESULTS[0][0], target_price=400), *GOOD[1:]])
    client.post(URL)
    jobs.pop()()
    out = client.get(URL).json()
    assert out["status"] == "ready" and [i["institution"] for i in out["items"]] == ["高盛", "花旗"]


def test_reference_price_is_never_a_demo_quote():
    from forliosa.marketdata.base import QuoteData

    class MD:
        def __init__(self, q):
            self.q = q

        def quote(self, symbol):
            if isinstance(self.q, Exception):
                raise self.q
            return self.q

    assert analyst.reference_price(MD(QuoteData("2330.TW", price=Decimal("2395"))), "2330.TW") == 2395.0
    assert analyst.reference_price(MD(QuoteData("2330.TW", prev_close=Decimal("2380"))), "2330.TW") == 2380.0
    assert analyst.reference_price(MD(QuoteData("2330.TW", price=Decimal("2395"), is_demo=True)), "2330.TW") is None
    assert analyst.reference_price(MD(None), "2330.TW") is None
    assert analyst.reference_price(MD(RuntimeError("down")), "2330.TW") is None


def test_verify_uses_the_article_date_and_drops_unverifiable_or_old():
    results = [R("https://a.com/2026/11/09/tsmc", age="2026-01-01"), R("https://b.com/x", age="3 days ago"),
               R("https://c.com/y", age=None), R("https://d.com/z", age="April 1, 2026"),
               R("https://e.com/w", age="2026-11-20"), R("https://f.com/v", age="June 1, 2026")]
    items, dropped = analyst.verify([item("甲", "https://a.com/2026/11/09/tsmc", target_price=1, date="2026-10-01"),
                                     item("乙", "https://b.com/x", target_price=1),
                                     item("丙", "https://c.com/y", target_price=1),
                                     item("丁", "https://d.com/z", target_price=1),
                                     item("戊", "https://e.com/w", target_price=1),
                                     item("己", "https://f.com/v", target_price=1)], results, TSMC, TODAY)
    # the URL date wins over page_age and over the model's own date; 91–180 days old: kept, marked old, last
    assert [(i["institution"], i["date"], i["old"]) for i in items] == [
        ("甲", "2026-11-09", False), ("乙", "2026-11-09", False), ("己", "2026-06-01", True)]
    assert reasons(dropped) == ["date_unverified", "too_old", "future"]


def test_verify_fields_never_invented():
    results = [R(f"https://n.com/{k}") for k in range(8)]
    cands = [item("法人", "https://n.com/0", target_price=1300),                       # unnamed
             item("Analysts", "https://n.com/1", rating_text="Buy"),                   # unnamed
             item("小摩", "https://n.com/2"),                                          # neither rating nor target
             item("花旗", "https://n.com/3", target_price=250, currency="USD"),         # the ADR's target
             item("花旗", "https://n.com/4", rating_text="中立", currency="USD"),       # no target: currency moot
             item("大摩", "https://n.com/5", rating_text="加碼", target_price=-1),      # nonsense target → none
             item("高盛", "https://n.com/6", rating_text="x" * 31, target_price=1300.5, action="未註明"),
             item("國內投顧", "https://n.com/7", rating_text="中立")]                  # unnamed, not foreign
    items, dropped = analyst.verify(cands, results, TSMC, TODAY)
    assert reasons(dropped) == ["unnamed", "unnamed", "empty", "currency", "unnamed"]
    assert [(i["institution"], i["rating_text"], i["target_price"], i["action"]) for i in items] == [
        ("花旗", "中立", None, "維持"), ("大摩", "加碼", None, "維持"), ("高盛", None, 1300.5, "")]
    assert all(i["currency"] == "TWD" and i["source_title"] == "標題" for i in items)
    assert not any(i["unnamed"] or i["old"] for i in items)


def test_verify_newest_first_one_per_institution_at_most_eight():
    results = [R(f"https://n.com/{k}", age=f"2026-11-{k + 1:02d}") for k in range(11)]
    cands = [item(f"範例{k}證券", f"https://n.com/{k}", rating_text="買進") for k in range(10)]
    cands.append(item("範例 9 證券", "https://n.com/10", rating_text="中立"))  # same institution, newer article
    items, dropped = analyst.verify(cands, results, NVDA, TODAY)
    assert [(i["institution"], i["date"]) for i in items] == [
        ("範例 9 證券", "2026-11-11"), ("範例8證券", "2026-11-09"), ("範例7證券", "2026-11-08"),
        ("範例6證券", "2026-11-07"), ("範例5證券", "2026-11-06"), ("範例4證券", "2026-11-05"),
        ("範例3證券", "2026-11-04"), ("範例2證券", "2026-11-03")]
    assert reasons(dropped) == ["duplicate", "limit", "limit"] and all(i["currency"] == "USD" for i in items)


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
    # a year / month followed by a numeric id is not a date
    ("https://www.example.com/2026/09/284512/tsmc", None),
    ("https://www.example.com/news/2026/10/315678", None),
    ("https://www.example.com/2026/11/3/tsmc", date(2026, 11, 3)),
    ("https://www.example.com/news/2026_11_04_tsmc", date(2026, 11, 4)),
    ("https://www.example.com/2026-11/05/x", None),  # mixed separators
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


@pytest.mark.parametrize("url", [
    "https://www.tipranks.com/stocks/nvda/forecast",
    "https://tw.tradingview.com/symbols/TWSE-2330/forecast-price-target/",
    "https://tw.stock.yahoo.com/quote/2330.TW",
    "https://www.cnyes.com/twstock/Technical.aspx?code=2330",
    "https://invest.cnyes.com/twstock/TWS/2330",
    "https://invest.cnyes.com/usstock/detail/NVDA",
    "https://www.benzinga.com/quote/NVDA/analyst-ratings",
    "https://www.benzinga.com/analyst-stock-ratings/price-target/26/11/123/nvidia",
    "https://money.cnn.com/quote/forecast/forecast.html?symb=NVDA",
    "https://www.marketwatch.com/investing/stock/nvda/analystestimates",
    "https://www.nasdaq.com/market-activity/stocks/nvda/analyst-research",
    "https://www.zacks.com/stock/research/NVDA/price-target-stock-forecast",
    "https://www.investing.com/equities/nvidia-corp-consensus-estimates",
    "https://www.wsj.com/market-data/quotes/NVDA/research-ratings",
    "https://www.wallstreetzen.com/stocks/us/nasdaq/nvda/stock-forecast",
    "https://fintel.io/sfo/us/nvda",
    "https://public.com/stocks/nvda/forecast-price-target",
    "https://www.example.com/stocks/nvda/price-target",
    "https://www.example.com/nvda/consensus",
    # seen in the live smoke (2026-11-12)
    "https://www.marketscreener.com/quote/stock/TSMC-TAIWAN-SEMICONDUCTOR-6492349/consensus/",
    "https://simplywall.st/stocks/tw/semiconductors/twse-2330/taiwan-semiconductor-manufacturing-shares/future",
    "https://www.alphaspread.com/security/twse/2330/analyst-estimates",
    "https://valueinvesting.io/2330.TW/estimates",
    "https://finance.yahoo.com/quote/NVDA/analyst-insights/",
    "https://www.morningstar.com/stocks/xnas/nvda/quote",
    "https://www.chartmill.com/stock/quote/NVDA/analyst-ratings",
    "https://www.optionsanalysissuite.com/stocks/nvda/analyst-ratings",
    "https://tickernerd.com/stock/nvda-forecast/",
])
def test_rating_and_quote_pages_are_not_articles(url):
    assert not analyst.is_article(url)


@pytest.mark.parametrize("url", [
    "https://tw.stock.yahoo.com/news/abc-001000161.html",
    "https://news.cnyes.com/news/id/6200001",
    "https://www.marketwatch.com/story/nvidia-price-target-raised-2026-11-10",
    "https://www.nasdaq.com/articles/morgan-stanley-lifts-nvidia-target",
    "https://www.reuters.com/markets/2026/11/03/tsmc-raises-revenue-forecast/",  # dated: an article
    "https://www.cnbc.com/2026/11/10/nvidia-price-target.html",
    "https://finance.yahoo.com/markets/stocks/articles/analysts-cutting-price-targets-nvidia-200042618.html",
    "https://www.ctee.com.tw/news/20261014700084-439901",
    "https://finance.technews.tw/2026/10/16/tsmcs-third-quarter-results-were-impressive-earning-praise-from-foreign-investors",
])
def test_news_articles_are_articles(url):
    assert analyst.is_article(url)


def test_aggregators_are_dropped_by_verify():
    page = "https://goodinfo.tw/tw/StockDetail.asp?STOCK_ID=2330"
    items, dropped = analyst.verify([item("大摩", page, target_price=1)], [R(page)], TSMC, TODAY)
    assert items == [] and reasons(dropped) == ["not_article"]


def test_search_blocks_aggregators_unless_an_allow_list_is_set(ai_env):
    from forliosa.config import get_settings

    [search] = analyst.search_tools(get_settings())
    assert search["name"] == "web_search" and "tipranks.com" in search["blocked_domains"]
    assert "benzinga.com" in search["blocked_domains"] and "zacks.com" in search["blocked_domains"]
    ai_env(AI_WEB_SEARCH_ALLOWED_DOMAINS="recommended")
    [search] = analyst.search_tools(get_settings())
    assert "blocked_domains" not in search and search["allowed_domains"]


# -- 2026-11-16 decisions (the analyst / news memo) -----------------------------------------------------------
def test_unnamed_foreign_brokers_are_labelled_recent_only_at_most_two_never_folded():
    """Decision 2: 「日系外資」 → 「未具名外資（日系）」, at most 2, only within 30 days, never merged with a named one
    (M31's only report in the window named no firm)."""
    results = [R(f"https://n.com/{k}", age=a) for k, a in enumerate(
        ["2026-11-11", "2026-11-10", "2026-11-09", "2026-11-08", "2026-10-01", "2026-11-07"])]
    cands = [item("日系外資", "https://n.com/0", action="調降", target_price=1200),
             item("日系外資", "https://n.com/1", action="調降", target_price=1200),  # the same story elsewhere
             item("美系外資 C", "https://n.com/2", rating_text="中立"),
             item("某外資", "https://n.com/3", rating_text="買進"),                  # a third unnamed: past the cap
             item("歐系外資", "https://n.com/4", target_price=1500),                 # 42 days old
             item("野村", "https://n.com/5", target_price=1400)]
    items, dropped = analyst.verify(cands, results, TSMC, TODAY)
    assert [(i["institution"], i["date"], i["unnamed"]) for i in items] == [
        ("未具名外資（日系）", "2026-11-11", True), ("未具名外資（美系）", "2026-11-09", True),
        ("野村", "2026-11-07", False)]
    assert sorted(reasons(dropped)) == ["duplicate", "limit", "unnamed_old"]
    # 「美系外資（摩根士丹利）」 names a firm: a named item; 「國內投顧」「法人」 are not foreign brokers: dropped
    assert analyst.unnamed_label("美系外資（摩根士丹利）") == "未具名外資（美系）"  # but institution_key wins first
    assert analyst.institution_key("美系外資（摩根士丹利）") == "morganstanley"
    assert [analyst.unnamed_label(n) for n in ("外資", "外資券商 A", "港資券商", "國內投顧", "法人", "券商")] == [
        "未具名外資", "未具名外資", "未具名外資（港資）", None, None, None]


def test_named_recent_items_come_first_then_unnamed_then_old_up_to_eight():
    """Decisions 3–4: 8 items; reports 91–180 days old are kept as 舊資料 after the newer ones; unnamed brokers only
    fill room the named recent ones leave."""
    ages = [f"2026-11-{d:02d}" for d in (10, 9, 8)] + ["2026-11-11", "2026-11-05", "2026-11-04"] + \
        ["2026-05-15", "2026-06-15", "2026-07-15", "2026-08-01"]
    results = [R(f"https://n.com/{k}", age=a) for k, a in enumerate(ages)]
    cands = [item(f"範例{k}證券", f"https://n.com/{k}", rating_text="買進") for k in range(3)]
    cands += [item(n, f"https://n.com/{k}", rating_text="中立") for k, n in ((3, "日系外資"), (4, "美系外資"),
                                                                           (5, "歐系外資"))]
    cands += [item(f"舊{k}證券", f"https://n.com/{k}", rating_text="買進") for k in range(6, 10)]
    items, dropped = analyst.verify(cands, results, TSMC, TODAY)
    # 5/15 is 181 days old: too old; the rest of the old ones fill the room after 3 named + 2 unnamed
    assert [(i["institution"], i["old"]) for i in items] == [
        ("未具名外資（日系）", False), ("範例0證券", False), ("範例1證券", False), ("範例2證券", False),
        ("未具名外資（美系）", False), ("舊9證券", True), ("舊8證券", True), ("舊7證券", True)]
    assert sorted(reasons(dropped)) == ["limit", "too_old"]
    # with 8 named recent items, nothing else is shown
    many = [R(f"https://m.com/{k}", age=f"2026-11-{k + 1:02d}") for k in range(10)]
    cands = [item(f"甲{k}證券", f"https://m.com/{k}", rating_text="買進") for k in range(8)]
    cands += [item("日系外資", "https://m.com/8", rating_text="中立"), item("乙證券", "https://m.com/9",
                                                                         rating_text="買進")]
    many.append(R("https://m.com/old", age="2026-07-01"))
    cands.append(item("丙證券", "https://m.com/old", rating_text="買進"))
    items, dropped = analyst.verify(cands, many, TSMC, TODAY)
    assert len(items) == 8 and not any(i["unnamed"] or i["old"] for i in items)
    assert reasons(dropped) == ["limit", "limit", "limit"]


def test_one_institution_one_day_prefers_a_reputable_outlet():
    results = [R("https://blog.example.com/a", age="2026-11-10"), R("https://money.udn.com/money/story/5607/1",
                                                                     age="2026-11-10")]
    items, dropped = analyst.verify([item("大摩", "https://blog.example.com/a", target_price=1350),
                                     item("摩根士丹利", "https://money.udn.com/money/story/5607/1", target_price=1350)],
                                    results, TSMC, TODAY)
    assert [i["url"] for i in items] == ["https://money.udn.com/money/story/5607/1"]
    assert reasons(dropped) == ["duplicate"]


@pytest.mark.parametrize("url", [
    "https://aigc-note.cmoney.tw/answer/123", "https://www.cmoney.tw/forum/article/185082146",
    "https://www.cmnews.com.tw/article/cmoneyairesearcher-abc", "https://blog.fugle.tw/post/earnings-call-7799-2025-12-10",
    "https://histock.tw/stock/7799", "https://pchome.megatime.com.tw/stock/sid7799.html", "https://www.ptt.cc/bbs/Stock/M.1.html",
    # 2026-11-16 re-measure
    "https://finance.biggo.com.tw/quote/5203.TW", "https://stock.pchome.com.tw/stock/sid6533.html",
    "https://ww2.money-link.com.tw/TWStock/StockNews.aspx?SymId=6643", "https://www.fugle.tw/ai/6643",
    "https://agdstock.club/iic/5203-x", "https://www.fastbull.com/quotation-detail/10100_7799",
    "https://www.gurufocus.com/stock/ROCO:3680/forecast", "https://pchome.megatime.com.tw/m/stock/sid1784_1.html",
])
def test_ai_written_quote_and_forum_pages_are_not_articles(url):
    assert not analyst.is_article(url)


def test_chat_and_card_block_the_news_sides_list(ai_env):
    from types import SimpleNamespace

    from forliosa.ai.chat import ChatTurn
    from forliosa.ai.tools import CHAT_BLOCKED_DOMAINS, SEARCH_BLOCKED_DOMAINS, block_search, server_tools
    from forliosa.config import get_settings
    from forliosa.news.ai_search import SEARCH_BLOCKED
    from forliosa.news.outlets import NOT_NEWS_DOMAINS

    [search] = analyst.search_tools(get_settings())
    for host in ("cmoney.tw", "cmnews.com.tw", "fugle.tw", "histock.tw", "goodinfo.tw", "ptt.cc",
                 "finance.biggo.com.tw", "stock.pchome.com.tw", "benzinga.com"):
        assert host in search["blocked_domains"]
    assert search["blocked_domains"] == list(SEARCH_BLOCKED_DOMAINS) and len(SEARCH_BLOCKED_DOMAINS) <= 100
    assert "pchome.megatime.com.tw" not in SEARCH_BLOCKED_DOMAINS  # its /news pages are reprints (QUOTE_PATHS)
    # one list (2026-11-16 review: three lists had drifted apart): the news side's not-news domains in every one
    assert set(NOT_NEWS_DOMAINS) <= set(CHAT_BLOCKED_DOMAINS) <= set(SEARCH_BLOCKED_DOMAINS)
    assert set(NOT_NEWS_DOMAINS) <= set(SEARCH_BLOCKED)
    # chat keeps the rating sites that also publish news (a US stock's "why did it move")
    assert {"benzinga.com", "zacks.com"}.isdisjoint(CHAT_BLOCKED_DOMAINS)
    turn = SimpleNamespace(settings=get_settings(), deep=False, economy=False)
    chat_tools = ChatTurn.tools(turn)  # type: ignore[arg-type]
    assert next(t for t in chat_tools if t["name"] == "web_search")["blocked_domains"] == list(CHAT_BLOCKED_DOMAINS)
    chat_tools = block_search(server_tools(get_settings()), CHAT_BLOCKED_DOMAINS)
    assert "blocked_domains" in next(t for t in chat_tools if t["name"] == "web_fetch")  # still TWSE / MIS only
    assert next(t for t in chat_tools if t["name"] == "web_fetch")["blocked_domains"] == ["www.twse.com.tw",
                                                                                          "mis.twse.com.tw"]


@pytest.mark.parametrize(("title", "host"), [
    ("本公司受邀參加永豐金證券匯立分公司舉辦之法人說明會", "永豐金證券匯立分公司"),
    ("本公司受邀參加Daiwa Investment Conference Singapore 2026", "Daiwa Investment Conference Singapore 2026"),
    ("豐興受國票綜合證券邀請召開法人說明會", "國票綜合證券"),
    ("大拓-KY 12/16參加康和證券舉辦之線上法說會", "康和證券"),
    ("本公司應凱基證券之邀請參加法人說明會", "凱基證券"),
    ("公告本公司召開法人說明會", None),
    ("本公司受邀參加法人說明會", None),
])
def test_conference_host(title, host):
    assert analyst.conference_host(title) == host


def _notice(db: Session, symbol: str, day: date, title: str, created: datetime, key: str, clause: str = "第12款",
            fact: date | None = None, detail: str = "") -> None:
    from forliosa.models import MarketEvent

    db.add(MarketEvent(key=key, symbol=symbol, date=day, type="material_info", title=title, detail=detail, url=None,
                       data={"clause": clause, "time": "150210", "fact_date": (fact or day).isoformat()},
                       source="twse-openapi", created_at=created))
    db.commit()


def test_the_question_carries_the_english_name_and_the_latest_conference(client, pool, fake, jobs, engine):
    from forliosa.models import CompanyProfile

    with Session(engine) as db:
        db.add(CompanyProfile(symbol="2330.TW", date=TODAY, values={"english_short_name": "TSMC"}, source="test",
                              fetched_at=NOW))
        db.commit()
        _notice(db, "2330.TW", date(2026, 10, 10), "本公司受邀參加凱基證券舉辦之法人說明會", NOW - timedelta(days=30),
                "c1", fact=date(2026, 10, 15))
        _notice(db, "2330.TW", date(2026, 11, 11), "本公司召開法人說明會", NOW, "c2", fact=date(2026, 11, 25))
    answer(fake, GOOD)
    out = client.post(URL).json()
    assert out["conference"] == {"last": {"date": "2026-10-15", "host": "凱基證券"},
                                 "next": {"date": "2026-11-25", "host": None}, "url": analyst.MOPS_CONFERENCE_URL}
    jobs.pop()()
    question = fake.requests[0]["body"]["messages"][0]["content"]
    assert "英文名稱：TSMC" in question and "最近一次法說會：2026-10-15（凱基證券舉辦）" in question


# 禾榮科's archived notice as it is (2026-11-16): 事實發生日 11/10, the 法說會 itself on 11/12
HNMC_DETAIL = ("1.召開法人說明會之日期:115/11/12 2.召開法人說明會之時間:14 時 00 分 3.召開法人說明會之地點:台北市 "
               "4.法人說明會擇要訊息:本公司受邀參加永豐金證券匯立分公司舉辦之法人說明會，說明公司營運概況及未來展望")


def test_the_conference_date_is_the_day_it_is_held_not_the_fact_date(engine):
    from forliosa.marketdata.base import InstrumentInfo

    hnmc = InstrumentInfo("7799.TW", "7799", "禾榮科", "TWSE", "stock", "TWD")
    with Session(engine) as db:
        _notice(db, "7799.TW", date(2026, 11, 10), "本公司受邀參加永豐金證券匯立分公司舉辦之法人說明會",
                datetime(2026, 11, 10, 7, 2, tzinfo=UTC), "hnmc", fact=date(2026, 11, 10), detail=HNMC_DETAIL)
        held = analyst.conference_info(db, hnmc, date(2026, 11, 16))
        assert held["last"] == {"date": "2026-11-12", "host": "永豐金證券匯立分公司"} and held["next"] is None
        ahead = analyst.conference_info(db, hnmc, date(2026, 11, 11))  # announced, not held yet
        assert ahead["last"] is None and ahead["next"] == {"date": "2026-11-12", "host": "永豐金證券匯立分公司"}
        assert analyst.query_hints(db, hnmc, date(2026, 11, 16)).conference == date(2026, 11, 12)
        # searched empty on 11/11 (after the notice was archived): the 法說會 of 11/12 searches again from 11/13
        since = datetime(2026, 11, 11, 6, 0, tzinfo=UTC)
        assert analyst.new_notice(db, "7799.TW", since, date(2026, 11, 12)) is False
        assert analyst.new_notice(db, "7799.TW", since, date(2026, 11, 13)) is True


def test_an_empty_result_is_kept_three_trading_days_unless_a_new_notice(client, other_client, pool, fake, jobs,
                                                                         engine, monkeypatch):
    """Decision 5: Thursday's empty search stands on Friday and Monday (shared, no new search or charge); Tuesday
    is a new search. A 法說會 notice archived after the search, or a 法說會 held since, searches again sooner."""
    answer(fake, [], results=[("https://news.example.com/2026/11/10/tsmc", "台積電法說會重點整理", None)])
    client.post(URL)
    jobs.pop()()
    thursday = client.get(URL).json()
    assert thursday["status"] == "ready" and thursday["items"] == []
    assert thursday["expires_at"] == "2026-11-17T00:00:00+08:00"  # Tuesday 00:00: kept Thu, Fri, Mon
    for later in (NOW + timedelta(days=1), NOW + timedelta(days=4, hours=9)):  # Friday 14:00, Monday 23:00
        monkeypatch.setattr(analyst, "now_utc", lambda later=later: later)
        out = other_client.post(URL).json()
        assert out["status"] == "ready" and out["as_of"] == thursday["as_of"] and jobs == []
    assert other_client.get(f"{API}/ai/usage").json()["messages_today"] == 0
    monkeypatch.setattr(analyst, "now_utc", lambda: NOW + timedelta(days=5))  # Tuesday 14:00
    assert client.get(URL).json()["status"] == "none"

    # a new 法說會 notice archived on Friday: searched again on Friday
    monkeypatch.setattr(analyst, "now_utc", lambda: NOW + timedelta(days=1))
    with Session(engine) as db:
        _notice(db, "2330.TW", date(2026, 11, 13), "本公司受邀參加元大證券舉辦之法人說明會", NOW + timedelta(hours=20),
                "n1", fact=date(2026, 11, 26))
    assert client.get(URL).json()["status"] == "none"
    answer(fake, GOOD)
    assert client.post(URL).json()["status"] == "pending" and len(jobs) == 1


def test_a_conference_held_since_the_empty_search_searches_again(client, pool, fake, jobs, engine, monkeypatch):
    with Session(engine) as db:  # announced long before the search, held on Friday 11/13
        _notice(db, "2330.TW", date(2026, 11, 2), "本公司召開法人說明會", NOW - timedelta(days=10), "h1",
                fact=date(2026, 11, 13))
    answer(fake, [], results=[("https://news.example.com/2026/11/10/tsmc", "台積電法說會重點整理", None)])
    client.post(URL)
    jobs.pop()()
    monkeypatch.setattr(analyst, "now_utc", lambda: NOW + timedelta(hours=18))  # Friday 08:00: held today
    assert client.get(URL).json()["status"] == "ready"
    monkeypatch.setattr(analyst, "now_utc", lambda: NOW + timedelta(days=4))  # Monday: held since the search
    assert client.get(URL).json()["status"] == "none"
    with Session(engine) as db:
        assert analyst.new_notice(db, "2330.TW", NOW, date(2026, 11, 13)) is False
        assert analyst.new_notice(db, "2330.TW", NOW, date(2026, 11, 16)) is True


def test_a_result_with_items_is_not_kept_past_its_day(client, pool, fake, jobs, monkeypatch):
    answer(fake, GOOD)
    client.post(URL)
    jobs.pop()()
    assert client.get(URL).json()["expires_at"] == "2026-11-13T14:00:00+08:00"
    monkeypatch.setattr(analyst, "now_utc", lambda: NOW + timedelta(hours=18))  # Friday 08:00
    assert client.get(URL).json()["status"] == "none"


# -- 2026-11-16 re-measure: M31 searched as 晶心科, 家登 empty where another search found UBS ---------------------
def test_an_empty_report_from_searches_for_another_stock_is_not_claimed_as_none(client, pool, fake, jobs):
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "聯電 目標價"}),
               results_block("srvtoolu_1", [("https://news.example.com/2026/11/10/umc", "聯電法說會", None)]),
               tool_use("toolu_r", "report_analyst_views", {"items": []}),
               stop_reason="tool_use", usage={"server_tool_use": {"web_search_requests": 1}})
    client.post(URL)
    jobs.pop()()
    assert client.get(URL).json()["status"] == "unavailable"  # searched again after 10 minutes, not kept 3 days


def test_query_terms_take_the_full_name_and_its_first_two_characters():
    m31 = InstrumentInfo("6643.TWO", "6643", "M31", "TPEX", "stock", "TWD")
    terms = analyst.query_terms(m31, analyst.Hints(full_name="円星科技"))
    assert analyst._mentions("M31 6643 目標價", terms) and analyst._mentions("円星 目標價", terms)
    assert not analyst._mentions("晶心科 目標價", terms) and not analyst._mentions("M310 目標價", terms)


def test_an_empty_result_of_a_stock_rated_in_the_last_year_is_not_kept(client, pool, fake, jobs, monkeypatch,
                                                                    engine):
    """A rating headline 191 days old (outside the card's 180 days): the stock is covered, so its empty result is
    searched again on the next trading day instead of standing for 3 trading days."""
    answer(fake, [], results=[("https://news.example.com/2026/05/05/tsmc", "外資調升台積電目標價", None)])
    client.post(URL)
    jobs.pop()()
    out = client.get(URL).json()
    assert out["status"] == "ready" and out["items"] == []
    assert out["expires_at"] == "2026-11-13T14:00:00+08:00"  # 24 hours, not Tuesday 00:00
    # the next trading day searches again from its start, not only once the entry expires (2026-11-16 review: Friday
    # 09:30 still read Thursday's empty result, and the chat tool was told there was nothing)
    with Session(engine) as db:
        assert analyst.cached(db, "2330.TW", NOW + timedelta(hours=18))["status"] == "none"  # the chat tool
    for later in (timedelta(hours=18), timedelta(hours=23, minutes=59), timedelta(days=1)):
        monkeypatch.setattr(analyst, "now_utc", lambda later=later: NOW + later)
        assert client.get(URL).json()["status"] == "none"
    monkeypatch.setattr(analyst, "now_utc", lambda: NOW + timedelta(hours=19, minutes=30))  # Friday 09:30
    answer(fake, [])
    assert client.post(URL).json()["status"] == "pending" and len(jobs) == 1


def test_the_question_names_the_company_and_how_to_search_a_short_name():
    from forliosa.ai.prompts import analyst_question

    q = analyst_question("M31", "6643.TWO", "TPEX", "TWD", "2026-11-16", "2026-05-20", full_name="円星科技")
    assert "公司全名：円星科技" in q and "「M31 6643 目標價」" in q
    q = analyst_question("禾榮科", "7799.TW", "TWSE", "TWD", "2026-11-16", "2026-05-20", english="HNMC",
                         conference="2026-11-12", host="永豐金證券匯立分公司")
    assert "英文名稱：HNMC（簡稱，英文搜尋要加 Taiwan）" in q
    assert "最近一次法說會：2026-11-12（永豐金證券匯立分公司舉辦）" in q and "可以搜：「禾榮科 永豐金 目標價」" in q
    # the old example 「名稱 法說會 主辦券商」 was searched word for word in 4 of 9 cards
    assert "法說會 主辦券商" not in ANALYST_SYSTEM
    assert "用券商的名字搜（例如「禾榮科 永豐金 目標價」）" in ANALYST_SYSTEM


def test_an_unnamed_broker_with_a_named_ones_target_that_week_is_left_out():
    """2026-11-16 re-measure, 台達電: 「美系外資」 2,300 (11/10) was 大摩's 2,300 (11/11) retold; listed twice."""
    delta = InstrumentInfo("2308.TW", "2308", "台達電", "TWSE", "stock", "TWD")
    results = [R("https://n.com/0", age="2026-11-11"), R("https://n.com/1", age="2026-11-10"),
               R("https://n.com/2", age="2026-11-09")]
    cands = [item("大摩", "https://n.com/0", rating_text="優於大盤", target_price=2300),
             item("美系外資", "https://n.com/1", rating_text="建議加碼", target_price=2300),
             item("日系外資", "https://n.com/2", rating_text="中立", target_price=1900)]
    items, dropped = analyst.verify(cands, results, delta, TODAY)
    assert [(i["institution"], i["target_price"]) for i in items] == [("大摩", 2300.0), ("未具名外資（日系）", 1900.0)]
    assert reasons(dropped) == ["duplicate"]



# -- 2026-11-16 pre-deploy review: a US stock searched by its brand, searches that failed ------------------------
SEC_NAMES = [("PLTR", 1321655, "Palantir Technologies Inc."), ("AMZN", 1018724, "AMAZON COM INC"),
             ("TWN", 804123, "TAIWAN FUND INC"), ("TSM", 1046179, "TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD"),
             ("GSBD", 1572694, "Goldman Sachs BDC, Inc."), ("GS", 886982, "GOLDMAN SACHS GROUP INC"),
             ("APLE", 1418121, "Apple Hospitality REIT, Inc."), ("AAPL", 320193, "Apple Inc."),
             ("TROW", 1113169, "PRICE T ROWE GROUP INC"), ("JEF", 96223, "Jefferies Financial Group Inc."),
             ("BRK-A", 1067983, "BERKSHIRE HATHAWAY INC"), ("BRK-B", 1067983, "BERKSHIRE HATHAWAY INC")]


def us_stock(engine, symbol: str) -> tuple[InstrumentInfo, analyst.Hints]:
    from forliosa.models import SecTicker

    with Session(engine) as db:
        if db.get(SecTicker, "PLTR") is None:
            db.add_all(SecTicker(ticker=t, cik=cik, title=title) for t, cik, title in SEC_NAMES)
            db.commit()
        name = next(title for t, _, title in SEC_NAMES if t == symbol)
        info = InstrumentInfo(symbol, symbol, name, "US", "stock", "USD", None, source="sec-edgar")
        return info, analyst.query_hints(db, info, TODAY)


def test_a_us_stock_searched_by_the_first_word_of_its_name_is_on_target(pool, fake, engine):
    """SEC names a US stock 「Palantir Technologies Inc.」; searches and headlines say 「Palantir」. A search
    「Palantir analyst price target」 was taken for one about another stock, so an empty result was never 「查無」
    (each retry another question), and a headline 「Palantir price target raised…」 was not one about it."""
    from forliosa.config import Settings

    pltr, hints = us_stock(engine, "PLTR")
    assert hints.brand == "palantir"
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "Palantir analyst price target"}),
               results_block("srvtoolu_1", [("https://news.example.com/2026/11/10/pltr", "Palantir earnings preview",
                                             None)]),
               tool_use("toolu_r", "report_analyst_views", {"items": []}),
               stop_reason="tool_use", usage={"server_tool_use": {"web_search_requests": 1}})
    out = analyst.run_model(pltr, TODAY, "anv_t", pool, Settings(_env_file=None), lambda slot, msg: None, hints=hints)
    assert (out.status, out.reason) == ("ready", None)
    headline = R("https://news.example.com/2026/11/10/pltr", "Palantir price target raised to $200 at Wedbush")
    assert analyst.rating_headlines([headline], pltr, TODAY, brand=hints.brand) == 1
    amzn, hints = us_stock(engine, "AMZN")
    terms = analyst.query_terms(amzn, hints)
    assert analyst._mentions("Amazon analyst price target", terms)
    assert not analyst._mentions("Palantir analyst price target", terms)
    # a one-word name and Taiwan stocks are left as they were
    assert analyst.stock_terms(NVDA) == ["nvda", "nvidia", "輝達"]
    assert analyst.stock_terms(TSMC) == ["2330", "tsmc", "台積電"]


@pytest.mark.parametrize(("symbol", "query", "title"), [
    ("TWN", "Taiwan Fund analyst rating", "Taiwan Semiconductor price target raised to $400 at Needham"),
    ("GSBD", "Goldman Sachs BDC analyst price target", "Goldman Sachs raises Nvidia price target to $250"),
    ("APLE", "Apple Hospitality REIT analyst price target", "Apple price target raised to $300 at Wedbush"),
    ("TROW", "T. Rowe Price TROW analyst rating", "Nvidia price target raised to $250 at UBS"),
    ("JEF", "Jefferies Financial Group JEF price target", "Nvidia price target raised to $250 at Jefferies"),
])
def test_a_first_word_shared_with_another_company_is_not_its_name(pool, fake, engine, symbol, query, title):
    """Round 2 of the pre-deploy review: with every multi-word US name's first word taken for the stock, a rating
    headline of another company sharing it (Taiwan Semiconductor for The Taiwan Fund, Goldman Sachs rating Nvidia for
    Goldman Sachs BDC) or a broker's (Jefferies) or a headline word (T. Rowe Price is 「PRICE T ROWE GROUP INC」) made
    an empty result 「unavailable」 every time: never 「查無」, each retry another question and web search."""
    from forliosa.config import Settings

    info, hints = us_stock(engine, symbol)
    assert hints.brand is None
    url = "https://www.reuters.com/markets/2026/11/10/rating"
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": query}),
               results_block("srvtoolu_1", [(url, title, None)]),
               tool_use("toolu_r", "report_analyst_views", {"items": []}),
               stop_reason="tool_use", usage={"server_tool_use": {"web_search_requests": 1}})
    out = analyst.run_model(info, TODAY, "anv_t", pool, Settings(_env_file=None), lambda slot, msg: None, hints=hints)
    assert (out.status, out.reason, out.covered) == ("ready", None, False)
    # a word one company has (Berkshire's two share classes are one CIK) is still its name
    assert us_stock(engine, "BRK-B")[1].brand == "berkshire"


@pytest.mark.parametrize(("codes", "status"), [
    (["too_many_requests", "unavailable"], "unavailable"),
    (["too_many_requests", None], "unavailable"),  # one search failed, one answered: not 「查無」 either
    (["max_uses_exceeded", None], "ready"),  # the searches allowed were made
])
def test_an_empty_report_after_failed_searches_is_not_claimed_as_none(client, pool, fake, jobs, codes, status):
    """2026-11-16 pre-deploy review: every search answered too_many_requests / unavailable, the model reported an
    empty list, and 2330 was 「近期查無」 for 3 trading days for everyone."""
    blocks = []
    for n, code in enumerate(codes):
        tid = f"srvtoolu_{n}"
        blocks.append(server_tool_use(tid, "web_search", {"query": "台積電 目標價"}))
        if code is None:
            blocks.append(results_block(tid, [("https://news.example.com/2026/11/10/a", "台積電法說會", None)]))
        else:
            blocks.append({"type": "web_search_tool_result", "tool_use_id": tid,
                           "content": {"type": "web_search_tool_result_error", "error_code": code}})
    fake.reply(*blocks, tool_use("toolu_r", "report_analyst_views", {"items": []}),
               stop_reason="tool_use", usage={"server_tool_use": {"web_search_requests": len(codes)}})
    client.post(URL)
    jobs.pop()()
    out = client.get(URL).json()
    assert out["status"] == status and out["items"] == []
    if status == "unavailable":
        assert out["notes"] == ["14:10 之後可以再查一次。"] and out["expires_at"] == "2026-11-13T14:00:00+08:00"
