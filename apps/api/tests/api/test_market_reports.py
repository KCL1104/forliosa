"""市場報告 API (contract §14, §16): signed-in only; admin-only editions stay hidden from members (404); the public form
never shows ids, refs or quotes; the list pages; old versions; the unread dot; the view-as rules; switched off; the
admin side (settings, corrections, the hand-kept tables). The blind test was removed on 2026-11-18: its member and
admin endpoints are 404, every edition is public."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import pytest

from forliosa.config import get_settings
from forliosa.db import session_factory
from forliosa.reports import assemble, pack, pipeline
from forliosa.reports import settings as rs
from forliosa.timeutil import TAIPEI, now_utc
from tests.api.m5 import API
from tests.reports.conftest import MON, TUE, seed_market, ts
from tests.reports.helpers import INST_X, close_output, with_web


@pytest.fixture()
def on(app, monkeypatch):
    monkeypatch.setenv("MARKET_REPORTS_ENABLED", "true")
    get_settings.cache_clear()
    with session_factory()() as db:
        seed_market(db)
    yield
    get_settings.cache_clear()


def make(kind="close", d=MON, visibility="public", ai=True, published=None) -> str:
    """An edition with a data version and (``ai``) an AI version, published ``published`` (default: now)."""
    published = published or now_utc()
    with session_factory()() as db:
        ed = pipeline.edition_on(kind, d)
        r = pipeline.make_report(db, ed, published, visibility=visibility)
        built = pack.build(db, kind, d, cutoff=ts(d, 15, 40), now=ts(d, 16))
        pk = with_web(built.pack, INST_X)
        output = close_output(pk) if ai else None
        payload = assemble.build(kind=kind, report_id=r.id, edition_date=d, period=ed.period,
                                 next_period=ed.next_period, version=0, edition="ai" if ai else "data", pack=pk,
                                 blocks=built.blocks, output=output, published_at=published,
                                 first_published_at=published, as_of=ts(d, 15, 40), title_origin="ai",
                                 highlights_origin="ai")
        v = pipeline.new_version(db, r, edition="ai" if ai else "data", payload=payload, now=published)
        r.current_version_id, r.state, r.first_published_at = v.id, "ai" if ai else "data", published
        db.commit()
        return r.id


def admin_on(monkeypatch, email="demo@forliosa.local"):
    monkeypatch.setattr(get_settings(), "admin_emails", [email])


def test_switched_off(app, client):
    assert client.get(f"{API}/market/reports/status").json() == {"available": False, "mode": None, "unread": False,
                                                                 "latest": []}
    assert client.get(f"{API}/market/reports").json() == {"items": [], "next_cursor": None}
    assert client.get(f"{API}/market/reports/latest").json() is None


def test_signed_in_only(app, on):
    from fastapi.testclient import TestClient

    anon = TestClient(app)
    assert anon.get(f"{API}/market/reports/status").status_code == 401
    assert anon.get(f"{API}/market/reports/latest").status_code == 401


def test_admin_editions_are_hidden_from_members(on, client, other_client, monkeypatch):
    rid = make(visibility="admin")
    admin_on(monkeypatch)
    assert other_client.get(f"{API}/market/reports/{rid}").status_code == 404
    assert other_client.get(f"{API}/market/reports/{rid}").json()["error"]["message"] == "找不到這份報告"
    st = other_client.get(f"{API}/market/reports/status").json()
    assert st["available"] is False and st["mode"] is None and st["latest"] == []
    assert other_client.get(f"{API}/market/reports").json()["items"] == []
    # the admin reads it (the current version: here the AI one)
    st = client.get(f"{API}/market/reports/status").json()
    assert st["available"] and st["mode"] == "public"
    assert client.get(f"{API}/market/reports/{rid}").status_code == 200


def test_public_report_has_no_ids_refs_or_quotes(on, client, other_client):
    rid = make()
    r = other_client.get(f"{API}/market/reports/{rid}")
    assert r.status_code == 200
    raw = r.text
    assert not re.search(r"\b[FXCNW]\d{3}\b", raw) and '"refs"' not in raw and '"quote"' not in raw
    body = r.json()
    assert body["kind_label"] == "盤後重點" and body["edition_label"] == "11/16（一）" and body["has_ai"]
    assert body["model_line"] == assemble.MODEL_LINE and body["disclaimer_line"] == assemble.DISCLAIMER_AI
    cites = [c for p in body["highlights"] for s in p["sentences"] for c in s["cites"]]
    assert cites and {f["n"] for f in body["footnotes"]} >= set(cites)
    assert body["sources"]["web"][0]["outlet"] == "中央社"
    assert other_client.get(f"{API}/market/reports/latest?kind=close").json()["id"] == rid


def test_list_pages_and_versions(on, other_client):
    ids = [make("close", MON), make("premarket", TUE, ai=False)]
    first = other_client.get(f"{API}/market/reports?limit=1").json()
    assert [x["id"] for x in first["items"]] == [ids[1]] and first["next_cursor"]
    second = other_client.get(f"{API}/market/reports?limit=1&cursor={first['next_cursor']}").json()
    assert [x["id"] for x in second["items"]] == [ids[0]] and second["next_cursor"] is None
    pre = other_client.get(f"{API}/market/reports?kind=premarket").json()["items"][0]
    assert pre["has_ai"] is False and pre["prev_session"] == MON.isoformat()  # the session 「昨日你的群組」 is about
    assert second["items"][0]["prev_session"] is None
    assert other_client.get(f"{API}/market/reports?cursor=%%%").status_code == 422
    assert other_client.get(f"{API}/market/reports/{ids[0]}?version=1").json()["version"] == 1
    assert other_client.get(f"{API}/market/reports/{ids[0]}?version=9").status_code == 404


def test_unread_and_seen(on, other_client):
    make(published=now_utc() - timedelta(days=3))
    assert other_client.get(f"{API}/market/reports/status").json()["unread"] is False  # older than 24 h, no record
    make("premarket", TUE, ai=False)
    assert other_client.get(f"{API}/market/reports/status").json()["unread"] is True
    assert other_client.post(f"{API}/market/reports/seen").status_code == 204
    assert other_client.get(f"{API}/market/reports/status").json()["unread"] is False


def test_view_as_reads_but_never_marks_seen(on, other_client):
    make()
    h = {"X-Forliosa-View-As": "dlg_someone"}
    assert other_client.get(f"{API}/market/reports/status", headers=h).status_code == 200
    assert other_client.get(f"{API}/market/reports/latest", headers=h).status_code == 200
    r = other_client.post(f"{API}/market/reports/seen", headers=h)
    assert r.status_code == 403 and r.json()["error"]["code"] == "read_only"
    assert other_client.get(f"{API}/admin/market-reports/overview", headers=h).status_code == 403


# -- admin ---------------------------------------------------------------------------------------------------------
def test_admin_endpoints_are_404_for_members_before_the_body(on, other_client):
    assert other_client.get(f"{API}/admin/market-reports/overview").status_code == 404
    assert other_client.put(f"{API}/admin/market-reports/config", json={"mode": "nope"}).status_code == 404
    assert other_client.post(f"{API}/admin/market-calendar/macro", json={}).status_code == 404


def test_config_and_overview(on, client, monkeypatch):
    admin_on(monkeypatch)
    ov = client.get(f"{API}/admin/market-reports/overview").json()
    assert ov["enabled"] and ov["mode"] == "public" and ov["month"]["budget_usd"] == 80.0
    assert ov["month"]["tier"] == "normal" and ov["month"]["label"].endswith("月")
    assert list(ov["writers"]) == ["premarket", "close", "weekly"]
    # the blind test is gone: every kind names its writer, the env default Opus 5.5 at high
    assert all({k: w[k] for k in ("model", "effort", "source")} ==
               {"model": "claude-opus-5-5", "effort": "high", "source": "default"} for w in ov["writers"].values())
    assert not {"trial", "trial_running", "trial_audience", "trial_audience_source"} & set(ov)
    assert ov["key"] == {"slot": None, "status": "ok", "note": None}
    assert set(ov["manual"]) >= {"nyse_next", "nyse_unverified", "macro_next_14d", "earnings_next_14d"}
    for gone in ({"mode": "trial"}, {"trial_audience": "all"}):  # the blind test's settings are refused
        assert client.put(f"{API}/admin/market-reports/config", json=gone).status_code == 422
    assert client.put(f"{API}/admin/market-reports/config", json={"mode": "paused"}).json()["mode"] == "paused"
    r = client.put(f"{API}/admin/market-reports/config", json={"mode": "public"})
    assert r.status_code == 200 and r.json()["notice"].startswith("之後的新報告會對所有登入的人公開")
    r = client.put(f"{API}/admin/market-reports/config",
                   json={"writers": {"close": {"model": "claude-sonnet-5-5", "effort": "high"}}})
    w = r.json()["writers"]
    assert {k: w["close"][k] for k in ("model", "effort", "source")} == \
        {"model": "claude-sonnet-5-5", "effort": "high", "source": "admin"}
    assert w["premarket"]["source"] == "default" and r.json()["notice"] is None
    assert client.put(f"{API}/admin/market-reports/config",
                      json={"writers": {"close": {"model": "claude-fable-5-2", "effort": "high"}}}).status_code == 422
    assert client.put(f"{API}/admin/market-reports/config",
                      json={"writers": {"close": {"model": "claude-opus-5-5", "effort": "max"}}}).status_code == 422
    with session_factory()() as db:
        assert rs.config(db).mode == "public"


def test_the_blind_test_endpoints_are_gone(on, client, other_client, monkeypatch):
    """產品負責人 2026-11-18: 「盲測的部分就直接拔掉吧」 — the member (A / B / C, vote) and admin (list, variants,
    vote, reveal) routes answer 404 for everyone, admins included."""
    admin_on(monkeypatch)
    rid = make()
    for c in (client, other_client):
        assert c.get(f"{API}/market/reports/{rid}/trial").status_code == 404
        assert c.get(f"{API}/market/reports/{rid}/variants/A").status_code == 404
        assert c.put(f"{API}/market/reports/{rid}/vote", json={"preferred": "A"}).status_code in (404, 405)
    assert client.get(f"{API}/admin/market-reports/trial").status_code == 404
    assert client.post(f"{API}/admin/market-reports/trial/reveal", json={}).status_code in (404, 405)
    assert client.get(f"{API}/admin/market-reports/{rid}/variants/B").status_code == 404
    assert client.put(f"{API}/admin/market-reports/{rid}/vote", json={"preferred": "B"}).status_code in (404, 405)
    body = other_client.get(f"{API}/market/reports/{rid}").json()
    assert "trial" not in body and "variant" not in body
    summary = other_client.get(f"{API}/market/reports").json()["items"][0]
    assert "trial" not in summary and "my_vote" not in summary
    assert "trial_open" not in other_client.get(f"{API}/market/reports/status").json()


def test_corrections(on, client, other_client, monkeypatch):
    admin_on(monkeypatch)
    rid = make()
    r = client.post(f"{API}/admin/market-reports/{rid}/corrections",
                    json={"note": "櫃買指數的漲跌幅寫錯", "drop_sections": ["what_happened"]})
    assert r.status_code == 200
    body = other_client.get(f"{API}/market/reports/{rid}").json()
    assert body["edition"] == "correction" and body["corrections"][0]["note"].endswith("櫃買指數的漲跌幅寫錯")
    wh = next(s for s in body["sections"] if s["key"] == "what_happened")
    assert wh["origin"] == "data" and all(b["type"] != "text" for b in wh["blocks"])
    assert other_client.get(f"{API}/market/reports").json()["items"][0]["corrected"] is True
    assert client.post(f"{API}/admin/market-reports/{rid}/corrections", json={"note": ""}).status_code == 422
    typo = client.post(f"{API}/admin/market-reports/{rid}/corrections", json={"note": "x", "drop_sections": ["typo"]})
    assert typo.status_code == 422 and typo.json()["error"]["details"] == {"field": "drop_sections"}


def test_rebuild_data(on, client, monkeypatch):
    admin_on(monkeypatch)
    r = client.post(f"{API}/admin/market-reports/rebuild-data", json={"kind": "close", "edition_date": "2026-11-16"})
    assert r.status_code == 200 and r.json()["kind"] == "close"
    bad = client.post(f"{API}/admin/market-reports/rebuild-data", json={"kind": "close", "edition_date": "2026-11-15"})
    assert bad.status_code == 422 and bad.json()["error"]["details"] == {"field": "edition_date"}


def test_hand_kept_tables(on, client, monkeypatch):
    admin_on(monkeypatch)
    ok = {"name": "感恩節", "kind": "closed", "source_url": "https://www.nyse.com/markets/hours-calendars",
          "verified": True}
    r = client.put(f"{API}/admin/market-calendar/nyse/2026-11-26", json=ok)
    assert r.status_code == 200 and r.json()["verified"] and r.json()["date_label"] == "11/26（四）"
    from forliosa.timeutil import is_us_trading_day

    assert not is_us_trading_day(date(2026, 11, 26))
    early = client.put(f"{API}/admin/market-calendar/nyse/2026-11-27", json={**ok, "kind": "early_close"})
    assert early.status_code == 422 and early.json()["error"]["details"] == {"field": "close_time_et"}
    bad_url = client.put(f"{API}/admin/market-calendar/nyse/2026-12-25", json={**ok, "source_url": "https://x.com"})
    lookalike = client.put(f"{API}/admin/market-calendar/nyse/2026-12-25",
                           json={**ok, "source_url": "https://example.org/nyse.com"})
    assert lookalike.status_code == 422
    assert bad_url.status_code == 422
    assert client.delete(f"{API}/admin/market-calendar/nyse/2026-11-26").status_code == 204
    macro = {"event_date": "2026-11-25", "local_time": "08:30", "tz": "America/New_York", "country": "US",
             "title": "美國 10 月 PCE 物價指數", "agency": "BEA", "official_url": "https://www.bea.gov/news/schedule",
             "sectors": ["半導體"]}
    r = client.post(f"{API}/admin/market-calendar/macro", json=macro)
    assert r.status_code == 201 and r.json()["taipei_label"] == "台北 11/25 21:30"
    bad = client.post(f"{API}/admin/market-calendar/macro", json={**macro, "official_url": "https://www.cnbc.com/x"})
    assert bad.status_code == 422 and bad.json()["error"]["details"] == {"field": "official_url"}
    assert "只能連到官方網站" in bad.json()["error"]["message"]
    bad_sec = client.post(f"{API}/admin/market-calendar/macro", json={**macro, "sectors": ["AI"]})
    assert bad_sec.status_code == 422
    assert len(client.get(f"{API}/admin/market-calendar/macro?from=2026-11-20&to=2026-11-30").json()) == 1
    earn = {"symbol": "nvda", "company": "NVIDIA", "report_date": "2026-11-19", "timing": "amc",
            "sectors": ["半導體"]}
    r = client.post(f"{API}/admin/market-calendar/us-earnings", json=earn)
    assert r.status_code == 201 and r.json()["symbol"] == "NVDA" and "台北 11/20" in r.json()["taipei_label"]
    assert client.post(f"{API}/admin/market-calendar/us-earnings", json=earn).status_code == 409
    eid = r.json()["id"]
    assert client.delete(f"{API}/admin/market-calendar/us-earnings/{eid}").status_code == 204
    assert client.get(f"{API}/admin/market-calendar/us-earnings").json() == []


def test_a_one_digit_hour_is_stored_with_two(on, client, monkeypatch):
    # 「9:30」 would make 「美東 11/19 9:30（台北 …）」, which the US-time check does not read as converted
    admin_on(monkeypatch)
    earn = {"symbol": "nvda", "company": "NVIDIA", "report_date": "2026-11-19", "timing": "bmo", "time_et": "9:30",
            "sectors": ["半導體"]}
    r = client.post(f"{API}/admin/market-calendar/us-earnings", json=earn)
    assert r.status_code == 201 and r.json()["time_et"] == "09:30"
    assert r.json()["taipei_label"] == "美東 11/19 09:30（台北 11/19 22:30）"
    early = {"name": "感恩節後一天", "kind": "early_close", "close_time_et": "9:30",
             "source_url": "https://www.nyse.com/markets/hours-calendars"}
    r = client.put(f"{API}/admin/market-calendar/nyse/2026-11-27", json=early)
    assert r.status_code == 200 and r.json()["close_time_et"] == "09:30"
    from forliosa.timeutil import set_us_calendar

    set_us_calendar([])


def test_tz_time_is_today():
    assert datetime(2026, 11, 16, tzinfo=TAIPEI).date() == MON


def test_deleting_the_account_removes_seen_and_votes(on, client, monkeypatch, engine):
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from forliosa.models import MarketReportRead, MarketReportVote, User

    admin_on(monkeypatch)
    rid = make(visibility="admin")
    assert client.post(f"{API}/market/reports/seen").status_code == 204
    with Session(engine) as db:  # an old blind-test vote (history from before 2026-11-18)
        uid = db.scalar(select(User.id).where(User.email == "demo@forliosa.local"))
        db.add(MarketReportVote(report_id=rid, user_id=uid, preferred="A", note="", by_admin=True))
        db.commit()
    from tests.api.test_account import CONFIRM

    r = client.request("DELETE", f"{API}/me", json=CONFIRM)
    assert r.status_code == 204, r.text
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(MarketReportRead)) == 0
        assert db.scalar(select(func.count()).select_from(MarketReportVote)) == 0
