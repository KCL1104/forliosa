"""The market page's AI summary: one shared entry per trading day; a point is kept only with search results the
model really received and a report dated the session (or just after); nothing is shown when too little survives."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.ai import market_summary as ms
from forliosa.ai.analyst import SearchResult
from forliosa.ai.tools import excluded_tools, reset_excluded_tools
from forliosa.models import AiMarketSummary, AiUsage, IndexDaily
from forliosa.timeutil import TAIPEI
from tests.ai.fake_anthropic import server_tool_use, text, tool_use

DAY = date(2026, 11, 12)  # Thursday
NOW = datetime(2026, 11, 12, 7, 10, tzinfo=UTC)  # 15:10 Taipei, after the close
API = "/api/v1"

CNA = "https://www.cna.com.tw/news/afe/202611120301.aspx"
UDN = "https://money.udn.com/money/story/5607/9123456"
CNYES = "https://news.cnyes.com/news/id/6201234"
OLD = "https://www.ctee.com.tw/news/20261105700123-430201"
RESULTS = [
    (CNA, "台股收盤大漲270點 站上27200點", "November 12, 2026"),
    (UDN, "半導體領軍 電子類股全面收紅", "1 hour ago"),
    (CNYES, "三大法人買超 320 億元", None),  # no readable date
    (OLD, "台股上週回檔", "November 5, 2026"),  # an earlier session
]


def results_block(tid: str, results=RESULTS) -> dict:
    return {"type": "web_search_tool_result", "tool_use_id": tid,
            "content": [{"type": "web_search_result", "url": u, "title": t, "page_age": a, "encrypted_content": "E"}
                        for u, t, a in results]}


def answer(fake, headline: str, points: list[dict], results=RESULTS) -> None:
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "台股 收盤 11月12日"}),
               results_block("srvtoolu_1", results),
               tool_use("toolu_r", ms.TOOL_NAME, {"headline": headline, "points": points}),
               stop_reason="tool_use", usage={"server_tool_use": {"web_search_requests": 1}})


GOOD = [
    {"text": "加權指數終場上漲 270 點，收在 27,270 點。", "urls": [CNA]},
    {"text": "半導體類股領漲，電子類股全面收紅。", "urls": [UDN, CNYES]},
    {"text": "三大法人合計買超 320 億元。", "urls": [CNYES, CNA]},
]


@pytest.fixture(autouse=True)
def clean_tools():
    yield
    reset_excluded_tools()


@pytest.fixture()
def db(engine):
    with Session(engine) as session:
        yield session


def taiex(db: Session, change: str = "270.00") -> None:
    db.add(IndexDaily(name="發行量加權股價指數", date=DAY, market="TWSE", close=D("27270.00"), change=D(change),
                      change_pct=D("0.01"), source="twse-openapi"))
    db.commit()


def test_summary_day_is_the_latest_finished_session():
    at = lambda *a: datetime(*a, tzinfo=TAIPEI)  # noqa: E731
    assert ms.summary_day(at(2026, 11, 12, 13, 59)) == date(2026, 11, 11)  # still trading
    assert ms.summary_day(at(2026, 11, 12, 14, 0)) == DAY
    assert ms.summary_day(at(2026, 11, 14, 10, 0)) == date(2026, 11, 13)  # Saturday → Friday
    assert ms.summary_day(at(2026, 11, 16, 9, 30)) == date(2026, 11, 13)  # Monday morning → Friday


def test_question_quotes_only_official_numbers():
    q = ms.question(DAY, DAY, [ms.OfficialIndex("加權指數", D("27270.00"), D("270.00"), D("0.01")),
                                ms.OfficialIndex("櫃買指數", D("297.00"), D("-3.00"), D("-0.01"))])
    assert "交易日：2026-11-12（週四）" in q
    assert "加權指數收 27,270.00 點，漲 270.00 點（1.00%）" in q and "櫃買指數收 297.00 點，跌 3.00 點（1.00%）" in q
    assert "還沒有公布" in ms.question(DAY, DAY, [])


def test_generate_keeps_verified_points_and_records_usage(db, pool, fake):
    taiex(db)
    answer(fake, "加權指數收漲 1%，半導體領漲", GOOD)
    row = ms.generate(db, DAY, pool, ms.get_settings(), NOW)
    assert (row.status, row.headline, row.attempts) == ("ok", "加權指數收漲 1%，半導體領漲", 1)
    assert [p["text"] for p in row.points] == [p["text"] for p in GOOD]
    first = row.points[0]["sources"]
    assert first == [{"url": CNA, "title": "台股收盤大漲270點 站上27200點", "outlet": first[0]["outlet"],
                      "date": "2026-11-12"}] and first[0]["outlet"]
    # the undated result may stand beside a dated one, never alone
    assert [s["url"] for s in row.points[1]["sources"]] == [UDN, CNYES]
    usage = db.scalars(select(AiUsage)).all()
    assert [(u.feature, u.user_id, u.web_search_requests) for u in usage] == [("market_summary", None, 1)]
    sent = fake.requests[0]["body"]
    assert sent["system"] == ms.SYSTEM and "官方收盤數字：加權指數收 27,270.00 點" in sent["messages"][0]["content"]
    assert [t["name"] for t in sent["tools"]] == ["web_search", ms.TOOL_NAME]
    assert sent["tools"][0]["max_uses"] == ms.SEARCH_MAX_USES and "web_fetch" not in str(sent["tools"])
    assert ms.view(row)["points"][0]["sources"] == [{"url": CNA, "title": "台股收盤大漲270點 站上27200點",
                                                    "outlet": first[0]["outlet"]}]


def test_verify_drops_made_up_links_stale_reports_and_undated_only_points():
    results = [SearchResult(u, t, a) for u, t, a in RESULTS]
    report = {"headline": "加權指數收漲 1%", "points": [
        {"text": "有根據的一點。", "urls": [CNA]},
        {"text": "網址不在搜尋結果裡。", "urls": ["https://example.com/made-up"]},
        {"text": "只有上週的報導。", "urls": [OLD]},
        {"text": "只有沒有日期的報導。", "urls": [CNYES]},
        {"text": "有根據的一點。", "urls": [UDN]},  # repeated sentence
        {"text": "", "urls": [CNA]},
        {"text": "新舊都有：只留當天的。", "urls": [OLD, UDN]},
    ]}
    headline, points, dropped = ms.verify(report, results, DAY, DAY)
    assert headline == "加權指數收漲 1%"
    assert [p["text"] for p in points] == ["有根據的一點。", "新舊都有：只留當天的。"]
    assert [s["url"] for s in points[1]["sources"]] == [UDN]
    assert dropped == ["no_search_result_source", "no_search_result_source", "date_unverified", "empty_or_repeated",
                       "empty_or_repeated"]


def test_report_window_covers_the_weekend_but_not_next_week():
    friday = date(2026, 11, 13)

    def one(age):
        return ms.verify({"headline": "", "points": [{"text": "一點。", "urls": [CNYES]}]},
                         [SearchResult(CNYES, "t", age)], friday, date(2026, 11, 20))[1]

    assert one("November 15, 2026") and one("2026-11-16T01:00:00Z")
    assert not one("November 17, 2026") and not one("November 12, 2026")


def test_headline_that_contradicts_the_official_change_is_dropped(db, pool, fake):
    taiex(db, change="-270.00")
    answer(fake, "加權指數收漲 1%，半導體領漲", GOOD)
    row = ms.generate(db, DAY, pool, ms.get_settings(), NOW)
    assert row.status == "ok" and row.headline == "" and len(row.points) == 3
    assert ms.view(row)["headline"] is None


def test_too_little_survives_nothing_is_shown(db, pool, fake):
    answer(fake, "加權指數收漲", [GOOD[0], {"text": "編出來的。", "urls": ["https://example.com/x"]}])
    row = ms.generate(db, DAY, pool, ms.get_settings(), NOW)
    assert (row.status, row.headline, row.points) == ("empty", "", []) and ms.view(row) is None
    assert ms.latest(db, NOW) is None


def test_text_only_answer_is_nudged_once_then_fails(db, pool, fake):
    fake.reply(text("今天台股上漲。"))
    fake.reply(text("我無法回報。"))
    row = ms.generate(db, DAY, pool, ms.get_settings(), NOW)
    assert row.status == "failed" and len(fake.requests) == 2
    assert fake.requests[1]["body"]["messages"][-1] == {"role": "user", "content": ms.NUDGE}


def test_pause_turn_continues_on_the_same_key(db, pool, fake):
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "台股 收盤"}), stop_reason="pause_turn")
    answer(fake, "加權指數收漲", GOOD)
    row = ms.generate(db, DAY, pool, ms.get_settings(), NOW)
    assert row.status == "ok" and len(set(fake.keys_used)) == 1 and len(fake.requests) == 2


def test_api_error_marks_failed_and_refused_search_is_remembered(db, pool, fake):
    fake.error(400, "invalid_request_error", "Requests sent from a sandbox with restricted network access are not "
                                             "permitted to use the web_search tool.")
    row = ms.generate(db, DAY, pool, ms.get_settings(), NOW)
    assert row.status == "failed" and [t["type"] for t in excluded_tools()] == ["web_search_20260318"]
    assert ms.enabled(ms.get_settings(), pool) is False  # no search tool left: no further model calls
    assert ms.refresh(db, NOW, pool) is None and len(fake.requests) == 1


def test_refresh_generates_once_and_retries_failures_later(db, pool, fake):
    answer(fake, "加權指數收漲", GOOD[:1])  # one point: empty
    first = ms.refresh(db, NOW, pool)
    assert first.status == "empty" and first.attempts == 1
    assert ms.refresh(db, NOW + timedelta(minutes=10), pool) is None  # too soon
    answer(fake, "加權指數收漲", GOOD)
    again = ms.refresh(db, NOW + ms.RETRY_AFTER + timedelta(minutes=1), pool)
    assert (again.status, again.attempts) == ("ok", 2)
    assert ms.refresh(db, NOW + timedelta(hours=5), pool) is None and len(fake.requests) == 2  # finished: never again
    assert db.scalar(select(func.count()).select_from(AiMarketSummary)) == 1
    assert ms.latest(db, NOW)["date"] == DAY


def test_gives_up_after_the_daily_attempts(db, pool, fake):
    at = NOW
    for _ in range(ms.MAX_ATTEMPTS):
        fake.reply(text("沒有呼叫工具"))
        fake.reply(text("還是沒有"))
        assert ms.refresh(db, at, pool).status == "failed"
        at += ms.RETRY_AFTER + timedelta(minutes=1)
    assert ms.refresh(db, at, pool) is None


def test_without_a_key_or_switched_off_no_model_call(db, fake, monkeypatch):
    assert ms.enabled(ms.get_settings()) is False  # tests carry no API key
    assert ms.refresh(db, NOW) is None
    ms.ensure(db, NOW)  # never raises
    assert fake.requests == [] and db.scalar(select(func.count()).select_from(AiMarketSummary)) == 0


def test_switch_off(db, pool, fake, ai_env):
    ai_env(AI_MARKET_SUMMARY_ENABLED="false")
    assert ms.enabled(ms.get_settings(), pool) is False and ms.refresh(db, NOW, pool) is None


def test_page_visit_starts_one_background_generation(client, pool, fake, monkeypatch, engine):
    started: list = []
    monkeypatch.setattr(ms, "spawn", lambda job, name: started.append(job))
    monkeypatch.setattr(ms, "summary_day", lambda now=None: DAY)
    answer(fake, "加權指數收漲 1%", GOOD)
    first = client.get(f"{API}/market/overview").json()
    assert first["summary"] is None and len(started) == 1 and fake.requests == []  # off the request thread
    assert client.get(f"{API}/market/overview").json()["summary"] is None and len(started) == 1  # one at a time
    started.pop()()
    out = client.get(f"{API}/market/overview").json()["summary"]
    assert out["date"] == "2026-11-12" and out["headline"] == "加權指數收漲 1%" and len(out["points"]) == 3
    assert set(out["points"][0]["sources"][0]) == {"url", "title", "outlet"}
    assert len(started) == 0 and len(fake.requests) == 1  # a finished day is not generated again
