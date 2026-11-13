"""每日收盤簡報: only for users who switched it on; facts by rules, AI notes verified against the search results;
one per user and trading day; kept 30 days; a briefing is the reader's own."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.ai import briefing as br
from forliosa.ai import store
from forliosa.ai.tools import reset_excluded_tools
from forliosa.config import get_settings
from forliosa.models import AiBriefing, AiUsage, DatasetStatus
from forliosa.timeutil import TAIPEI
from tests.ai.conftest import API, buy, chat, make_account
from tests.ai.fake_anthropic import server_tool_use, text, tool_use
from tests.ai.test_tools import user_by_email

DAY = date(2026, 11, 12)  # Thursday
NOW = datetime(2026, 11, 12, 14, 20, tzinfo=UTC)  # 22:20 Taipei, the first slot
CNA = "https://www.cna.com.tw/news/afe/202611120301.aspx"
UDN = "https://money.udn.com/money/story/5607/9123456"
OLD = "https://www.ctee.com.tw/news/20261105700123-430201"
RESULTS = [(CNA, "台積電法說後股價大漲", "November 12, 2026"), (UDN, "鴻海 10 月營收創同期新高", "2 hours ago"),
           (OLD, "台股上週回檔", "November 5, 2026")]


def results_block(tid: str) -> dict:
    return {"type": "web_search_tool_result", "tool_use_id": tid,
            "content": [{"type": "web_search_result", "url": u, "title": t, "page_age": a, "encrypted_content": "E"}
                        for u, t, a in RESULTS]}


def answer(fake, points: list[dict]) -> None:
    fake.reply(server_tool_use("srvtoolu_1", "web_search", {"query": "台積電 11月12日 股價"}),
               results_block("srvtoolu_1"), tool_use("toolu_r", br.TOOL_NAME, {"points": points}),
               stop_reason="tool_use", usage={"server_tool_use": {"web_search_requests": 1}})


GOOD = [{"text": "台積電法說會後獲法人買進，股價收漲。", "urls": [CNA]},
        {"text": "鴻海公布 10 月營收，創同期新高。", "urls": [UDN]}]


@pytest.fixture(autouse=True)
def clean_tools():
    yield
    reset_excluded_tools()


@pytest.fixture()
def db(engine):
    with Session(engine) as session:
        yield session


def switch_on(client, on: bool = True) -> None:
    r = client.patch(f"{API}/me/preferences", json={"daily_briefing": on})
    assert r.status_code == 200 and r.json()["preferences"]["daily_briefing"] is on


def me(db: Session, email: str = "demo@forliosa.local"):
    return user_by_email(db, email)


@pytest.fixture()
def holder(client):
    """The demo user with two holdings and the switch on."""
    acc = make_account(client)
    buy(client, acc, "2330", 1000, 600)
    buy(client, acc, "2317", 2000, 150)
    switch_on(client)
    return client


# -- the switch -------------------------------------------------------------------------------------------------
def test_the_switch_is_a_preference_and_off_by_default(client):
    assert client.get(f"{API}/me").json()["preferences"]["daily_briefing"] is False
    switch_on(client)
    assert client.get(f"{API}/me").json()["preferences"]["daily_briefing"] is True
    switch_on(client, False)
    assert client.patch(f"{API}/me/preferences", json={"daily_briefing": "yes please"}).status_code == 422


def test_nobody_gets_a_briefing_without_the_switch_or_without_anything_to_brief(client, other_client, db, market):
    acc = make_account(client)
    buy(client, acc, "2330", 1000, 600)  # holdings, switch off
    switch_on(other_client)  # switch on, nothing held or watched
    res = br.run(db, market, now=NOW, pool=None)
    assert (res.day, res.written) == (DAY, 0)
    assert db.scalar(select(func.count()).select_from(AiBriefing)) == 0


# -- facts ------------------------------------------------------------------------------------------------------
def test_facts_are_computed_from_the_ledger_and_the_watchlist(holder, db, market):
    assert holder.post(f"{API}/watchlist", json={"symbol": "2454"}).status_code in (200, 201)
    facts = br.build_facts(db, me(db), market, DAY)
    summary = holder.get(f"{API}/portfolio/summary").json()
    assert facts["market_value"] == summary["market_value"] and facts["day_change"] == summary["day_change"]
    assert (facts["holdings"], facts["unpriced"]) == (2, 0)
    assert len(facts["gainers"]) <= br.MOVERS and len(facts["losers"]) <= br.MOVERS
    assert all(m["change_pct"] > 0 for m in facts["gainers"]) and all(m["change_pct"] < 0 for m in facts["losers"])
    assert {m["symbol"] for m in [*facts["gainers"], *facts["losers"]]} <= {"2330.TW", "2317.TW"}
    assert all(abs(w["change_pct"]) >= float(br.WATCH_MOVE_PCT) for w in facts["watchlist"])
    assert "quantity" not in str(facts["gainers"]) and len(facts["upcoming"]) <= br.UPCOMING_MAX


def test_movers_are_the_largest_moves_on_each_side(db, market, client, monkeypatch):
    from forliosa.services import portfolio as svc

    make_account(client)

    def row(sym, pct, price=100.0):
        return {"symbol": f"{sym}.TW", "code": sym, "name": sym, "market": "TWSE", "type": "stock", "price": price,
                "day_change_pct": pct, "day_change": 1000 * (pct or 0), "is_demo": False}

    rows = [row("1101", 0.01), row("2330", 0.048), row("2317", 0.024), row("2454", -0.01), row("6488", -0.03),
            row("2603", -0.02), {**row("AAPL", None), "price": None, "market": "US"}]
    monkeypatch.setattr(svc, "holdings", lambda _state: rows)
    facts = br.build_facts(db, me(db), market, DAY)
    assert [m["code"] for m in facts["gainers"]] == ["2330", "2317"]
    assert [m["code"] for m in facts["losers"]] == ["6488", "2603"]
    assert (facts["holdings"], facts["unpriced"]) == (7, 1)
    # the model is asked about the two biggest moves, whichever side; small moves are not worth a search
    assert [m["code"] for m in br.ai_subjects(facts)] == ["2330", "6488"]
    assert br.ai_subjects({"gainers": [row("1101", 0.004)], "losers": [], "watchlist": []}) == []


# -- which day --------------------------------------------------------------------------------------------------
def test_a_briefing_waits_for_both_exchanges_closes(db):
    at = lambda *a: datetime(*a, tzinfo=TAIPEI)  # noqa: E731
    assert br.briefing_day(db, at(2026, 11, 12, 22, 20)) == DAY  # no archive at all (demo data): the session itself
    db.add_all([DatasetStatus(key="twse-openapi/price", data_date=date(2026, 11, 11), rows=1),
                DatasetStatus(key="tpex-openapi/price", data_date=DAY, rows=1)])
    db.commit()
    assert br.briefing_day(db, at(2026, 11, 12, 22, 20)) is None  # TWSE has not published the 12th yet
    db.get(DatasetStatus, "twse-openapi/price").data_date = DAY
    db.commit()
    assert br.briefing_day(db, at(2026, 11, 13, 6, 10)) == DAY  # the next morning's slot catches up
    assert br.briefing_day(db, at(2026, 11, 14, 8, 20)) is None  # Saturday: Friday's closes are not in
    assert br.briefing_day(db, at(2026, 11, 12, 13, 0)) == date(2026, 11, 11)  # still trading: the session before
    db.get(DatasetStatus, "twse-openapi/price").data_date = date(2026, 11, 6)
    db.get(DatasetStatus, "tpex-openapi/price").data_date = date(2026, 11, 6)
    db.commit()
    assert br.briefing_day(db, at(2026, 11, 12, 22, 20)) is None  # an archive a week behind is not briefed


# -- the AI's points ----------------------------------------------------------------------------------------------
def test_generate_keeps_verified_points_and_charges_the_user_one_question(holder, db, market, pool, fake, monkeypatch):
    monkeypatch.setattr(br, "ai_subjects", lambda facts: [
        {"symbol": "2330.TW", "code": "2330", "name": "台積電", "market": "TWSE", "type": "stock", "close": 1085.0,
         "change_pct": 0.0483, "day_change": 75000.0}])
    answer(fake, [*GOOD, {"text": "網址不在搜尋結果裡。", "urls": ["https://example.com/made-up"]},
                  {"text": "只有上週的報導。", "urls": [OLD]}])
    user = me(db)
    before = store.messages_today(db, user, NOW)
    res = br.run(db, market, now=NOW, pool=pool)
    assert (res.day, res.written, res.with_points) == (DAY, 1, 1)
    row = db.scalar(select(AiBriefing))
    assert (row.user_id, row.trading_day, row.ai_status, row.read_at) == (user.id, DAY, "ok", None)
    assert [p["text"] for p in row.points] == [p["text"] for p in GOOD]
    assert row.points[0]["sources"][0]["url"] == CNA and set(row.points[0]["sources"][0]) == {"url", "title", "outlet"}
    assert row.facts["holdings"] == 2
    # one usage row under the user, tied to the briefing: one question of the day, tokens in the month
    usage = db.scalars(select(AiUsage)).all()
    assert [(u.feature, u.user_id, u.thread_id, u.web_search_requests) for u in usage] == [
        ("briefing", user.id, row.id, 1)]
    assert store.messages_today(db, user, NOW) == before + 1
    # what the model was told: names, codes, closes and moves — nothing about quantities or money
    sent = fake.requests[0]["body"]
    assert sent["system"] == br.SYSTEM and [t["name"] for t in sent["tools"]] == ["web_search", br.TOOL_NAME]
    assert sent["tools"][0]["max_uses"] == br.SEARCH_MAX_USES
    q = sent["messages"][0]["content"]
    assert "交易日：2026-11-12（週四）" in q and "- 台積電（2330，股票）收 1085.0，漲 4.83%" in q
    assert str(row.facts["market_value"]) not in q and "75000" not in q and "1000" not in q.replace("1085", "")


def test_the_facts_stand_when_no_point_survives_or_the_call_fails(holder, db, market, pool, fake, monkeypatch):
    monkeypatch.setattr(br, "ai_subjects", lambda facts: [
        {"symbol": "2330.TW", "code": "2330", "name": "台積電", "market": "TWSE", "type": "stock", "close": 1085.0,
         "change_pct": 0.0483}])
    answer(fake, [{"text": "只有上週的報導。", "urls": [OLD]}])
    br.run(db, market, now=NOW, pool=pool)
    row = db.scalar(select(AiBriefing))
    assert (row.ai_status, row.points) == ("empty", []) and row.facts["holdings"] == 2

    # the next day: the API fails — still a briefing, facts only
    fake.error(500, "api_error")
    later = NOW + timedelta(days=1)
    res = br.run(db, market, now=later, pool=pool)
    assert res.written == 1
    second = db.scalar(select(AiBriefing).where(AiBriefing.trading_day == date(2026, 11, 13)))
    assert (second.ai_status, second.points) == ("failed", []) and second.facts["holdings"] == 2


SUBJECT = [{"symbol": "2330.TW", "code": "2330", "name": "台積電", "market": "TWSE", "type": "stock", "close": 1085.0,
            "change_pct": 0.0483}]


def test_without_a_key_the_briefing_has_facts_only(holder, db, market, monkeypatch):
    monkeypatch.setattr(br, "ai_subjects", lambda facts: SUBJECT)
    res = br.run(db, market, now=NOW)  # no key configured in the tests
    row = db.scalar(select(AiBriefing))
    assert res.written == 1 and (row.ai_status, row.points, row.model) == ("none", [], "")
    assert row.facts["holdings"] == 2 and db.scalar(select(func.count()).select_from(AiUsage)) == 0


def test_out_of_quota_the_briefing_has_facts_only(holder, db, market, pool, fake, ai_env, monkeypatch):
    monkeypatch.setattr(br, "ai_subjects", lambda facts: SUBJECT)
    ai_env(AI_DAILY_MESSAGE_LIMIT=1)
    fake.reply(text("好的。"))
    assert chat(holder, "今天如何？")[0] == 200  # the day's one question is used
    asked = len(fake.requests)
    user = me(db)
    assert not br.within_quota(db, user, get_settings())
    row = br.generate_for_user(db, user, market, DAY, pool, get_settings())
    assert (row.ai_status, row.points) == ("none", []) and row.facts["holdings"] == 2
    assert len(fake.requests) == asked  # no model call for the briefing
    # the month's tokens used up: the same
    ai_env(AI_DAILY_MESSAGE_LIMIT=50, AI_MONTHLY_TOKEN_BUDGET=1)
    assert not br.within_quota(db, user, get_settings())


def test_no_model_call_when_nothing_moved_enough(holder, db, market, pool, fake, monkeypatch):
    monkeypatch.setattr(br, "ai_subjects", lambda facts: [])
    res = br.run(db, market, now=NOW, pool=pool)
    assert res.written == 1 and fake.requests == []
    assert db.scalar(select(AiBriefing)).ai_status == "none"


def test_one_briefing_per_user_and_day_and_the_master_switch(holder, db, market, ai_env):
    assert br.run(db, market, now=NOW, pool=None).written == 1
    assert br.run(db, market, now=NOW + timedelta(hours=2), pool=None).written == 0  # the 23:50 slot: already there
    assert db.scalar(select(func.count()).select_from(AiBriefing)) == 1
    ai_env(AI_DAILY_BRIEFING_ENABLED="false")
    res = br.run(db, market, now=NOW + timedelta(days=1), pool=None, settings=get_settings())
    assert (res.day, res.written) == (None, 0)


def test_briefings_older_than_thirty_days_are_deleted(holder, db, market):
    user = me(db)
    for d in (date(2026, 10, 1), date(2026, 10, 20)):
        db.add(AiBriefing(id=f"brf_{d:%m%d}", user_id=user.id, trading_day=d, facts={}, points=[], ai_status="none"))
    db.commit()
    res = br.run(db, market, now=NOW, pool=None)
    assert res.purged == 1
    assert sorted(db.scalars(select(AiBriefing.trading_day))) == [date(2026, 10, 20), DAY]


# -- reading ------------------------------------------------------------------------------------------------------
def test_routes_serve_only_the_readers_own_briefings(holder, other_client, app, db, market):
    from fastapi.testclient import TestClient

    assert holder.get(f"{API}/ai/briefings/latest").json() is None
    assert holder.get(f"{API}/ai/briefings").json() == []
    now = datetime.now(UTC)
    res = br.run(db, market, now=now, pool=None)
    assert res.written == 1
    got = holder.get(f"{API}/ai/briefings/latest").json()
    assert got["date"] == res.day.isoformat() and got["read"] is False and got["points"] == []
    assert got["facts"]["holdings"] == 2 and set(got["facts"]) >= {"market_value", "day_change", "gainers", "losers",
                                                                 "watchlist", "upcoming", "unpriced", "is_demo"}
    assert [b["id"] for b in holder.get(f"{API}/ai/briefings?limit=5").json()] == [got["id"]]
    # somebody else: nothing of mine, and cannot mark mine read
    assert other_client.get(f"{API}/ai/briefings/latest").json() is None
    assert other_client.get(f"{API}/ai/briefings").json() == []
    assert other_client.post(f"{API}/ai/briefings/{got['id']}/read").status_code == 404
    assert holder.post(f"{API}/ai/briefings/{got['id']}/read").status_code == 204
    assert holder.get(f"{API}/ai/briefings/latest").json()["read"] is True
    assert holder.post(f"{API}/ai/briefings/nope/read").status_code == 404
    assert holder.get(f"{API}/ai/briefings?limit=99").status_code == 422
    for path in ("/ai/briefings/latest", "/ai/briefings"):
        assert TestClient(app).get(f"{API}{path}").status_code == 401


def test_latest_steps_aside_after_two_trading_days(holder, db, market):
    br.run(db, market, now=NOW, pool=None)
    user = me(db)
    at = lambda *a: datetime(*a, tzinfo=TAIPEI)  # noqa: E731
    assert br.latest(db, user, at(2026, 11, 13, 9, 0))["date"] == DAY  # Friday morning
    assert br.latest(db, user, at(2026, 11, 16, 9, 0))["date"] == DAY  # Monday morning: one session (Friday) later
    assert br.latest(db, user, at(2026, 11, 16, 15, 0)) is None  # Monday's close: two sessions later
    assert [b["date"] for b in br.recent(db, user)] == [DAY]  # still in the list


def test_account_export_and_deletion_cover_briefings(holder, db, market):
    br.run(db, market, now=NOW, pool=None)
    exported = holder.get(f"{API}/me/export").json()
    assert [b["trading_day"] for b in exported["ai"]["briefings"]] == ["2026-11-12"]
    r = holder.request("DELETE", f"{API}/me", json={"confirm": "刪除我的帳號"})
    assert r.status_code in (200, 204), r.text
    assert db.scalar(select(func.count()).select_from(AiBriefing)) == 0
