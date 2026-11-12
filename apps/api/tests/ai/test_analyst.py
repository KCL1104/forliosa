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
        {"institution": "花旗", "action": "調降", "rating_text": "中立", "target_price": None, "currency": "TWD",
         "date": "2026-10-28", "source_title": "花旗調降台積電評等至中立", "url": RESULTS[2][0]},
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
    results = [("https://news.example.com/2026/06/01/tsmc", "台積電法說會重點整理", None),
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
    assert n(TSMC, "大摩調升台積電目標價", age="June 1, 2026") == 0  # verifiably older than 90 days
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
])
def test_institution_key(name, key):
    assert analyst.institution_key(name) == key


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
               R("https://c.com/y", age=None), R("https://d.com/z", age="June 1, 2026"),
               R("https://e.com/w", age="2026-11-20")]
    items, dropped = analyst.verify([item("甲", "https://a.com/2026/11/09/tsmc", target_price=1, date="2026-10-01"),
                                     item("乙", "https://b.com/x", target_price=1),
                                     item("丙", "https://c.com/y", target_price=1),
                                     item("丁", "https://d.com/z", target_price=1),
                                     item("戊", "https://e.com/w", target_price=1)], results, TSMC, TODAY)
    # the URL date wins over page_age and over the model's own date
    assert [(i["institution"], i["date"]) for i in items] == [("甲", "2026-11-09"), ("乙", "2026-11-09")]
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
             item("美系外資", "https://n.com/7", rating_text="中立")]                  # unnamed
    items, dropped = analyst.verify(cands, results, TSMC, TODAY)
    assert reasons(dropped) == ["unnamed", "unnamed", "empty", "currency", "unnamed"]
    assert [(i["institution"], i["rating_text"], i["target_price"], i["action"]) for i in items] == [
        ("花旗", "中立", None, "維持"), ("大摩", "加碼", None, "維持"), ("高盛", None, 1300.5, "")]
    assert all(i["currency"] == "TWD" and i["source_title"] == "標題" for i in items)


def test_verify_newest_first_one_per_institution_at_most_five():
    results = [R(f"https://n.com/{k}", age=f"2026-11-0{k + 1}") for k in range(8)]
    cands = [item(f"範例{k}證券", f"https://n.com/{k}", rating_text="買進") for k in range(7)]
    cands.append(item("範例 6 證券", "https://n.com/7", rating_text="中立"))  # same institution, newer article
    items, dropped = analyst.verify(cands, results, NVDA, TODAY)
    assert [(i["institution"], i["date"]) for i in items] == [
        ("範例 6 證券", "2026-11-08"), ("範例5證券", "2026-11-06"), ("範例4證券", "2026-11-05"),
        ("範例3證券", "2026-11-04"), ("範例2證券", "2026-11-03")]
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
