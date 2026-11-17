"""市場報告 API (contract §14, §16): signed-in only; admin-only editions stay hidden from members (404); the public form
never shows ids, refs or quotes; the list pages; old versions; the unread dot; the view-as rules; switched off; the
admin side (settings, the blind test, the reveal, corrections, the hand-kept tables)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import pytest

from forliosa.config import get_settings
from forliosa.db import session_factory
from forliosa.models import MarketReport, MarketReportRun, MarketReportVersion
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


def make(kind="close", d=MON, visibility="public", ai=True, trial=False, published=None) -> str:
    """An edition with a data version and (``ai``) an AI version, published ``published`` (default: now)."""
    published = published or now_utc()
    with session_factory()() as db:
        ed = pipeline.edition_on(kind, d)
        r = pipeline.make_report(db, ed, published, visibility=visibility, trial=trial)
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
    rid = make(visibility="admin", trial=True)
    admin_on(monkeypatch)
    assert other_client.get(f"{API}/market/reports/{rid}").status_code == 404
    assert other_client.get(f"{API}/market/reports/{rid}").json()["error"]["message"] == "找不到這份報告"
    st = other_client.get(f"{API}/market/reports/status").json()
    assert st["available"] is False and st["mode"] is None and st["latest"] == []
    assert other_client.get(f"{API}/market/reports").json()["items"] == []
    # the admin reads it (the current version: here the AI one)
    st = client.get(f"{API}/market/reports/status").json()
    assert st["available"] and st["mode"] == "trial"
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
    assert ov["enabled"] and ov["mode"] == "trial" and ov["month"]["budget_usd"] == 80.0
    assert ov["month"]["tier"] == "normal" and ov["month"]["label"].endswith("月")
    assert ov["trial"]["budget_usd"] == 45.0 and list(ov["writers"]) == ["premarket", "close", "weekly"]
    assert all(w is None for w in ov["writers"].values())  # 盲測中: no model named
    assert ov["trial_running"] and ov["trial"]["days_total"] == 5 and ov["trial"]["weekly_done"] is False
    assert ov["key"] == {"slot": None, "status": "ok", "note": None}
    assert set(ov["manual"]) >= {"nyse_next", "nyse_unverified", "macro_next_14d", "earnings_next_14d"}
    r = client.put(f"{API}/admin/market-reports/config", json={"mode": "public"})
    assert r.status_code == 200 and r.json()["notice"].startswith("之後的新報告會對所有登入的人公開")
    r = client.put(f"{API}/admin/market-reports/config",
                   json={"writers": {"close": {"model": "claude-sonnet-5-5", "effort": "high"}}})
    w = r.json()["writers"]  # public now: the writers are named
    assert {k: w["close"][k] for k in ("model", "effort", "source")} == \
        {"model": "claude-sonnet-5-5", "effort": "high", "source": "admin"}
    assert w["premarket"]["source"] == "default" and r.json()["notice"] is None
    assert client.put(f"{API}/admin/market-reports/config",
                      json={"writers": {"close": {"model": "claude-fable-5-2", "effort": "high"}}}).status_code == 422
    assert client.put(f"{API}/admin/market-reports/config",
                      json={"writers": {"close": {"model": "claude-opus-5-5", "effort": "max"}}}).status_code == 422
    with session_factory()() as db:
        assert rs.config(db).mode == "public"


def _trial_runs(rid: str) -> None:
    with session_factory()() as db:
        r = db.get(MarketReport, rid)
        for label, (model, effort) in zip("ABC", pipeline.TRIAL_DAILY, strict=True):
            db.add(MarketReportRun(id=f"mrr_{rid[-6:]}{label}", report_id=rid, variant=label, purpose="trial",
                                   attempt=1, status="ok", step="done", tier="normal",
                                   writer={"model": model, "effort": effort}, calls=[], cost_usd=0.5,
                                   metrics={"on_time": True, "cost_usd": 0.5 if model.endswith("sonnet-5-5") else 1.0,
                                            "policy_violations": 0, "subject_mismatches": 0, "inferred_dates": 0,
                                            "dropped_sections": 0, "data_only": False, "seconds": 300},
                                   started_at=now_utc(), heartbeat_at=now_utc(), finished_at=now_utc()))
            cur = db.get(MarketReportVersion, r.current_version_id)
            db.add(MarketReportVersion(id=f"mrv_{rid[-6:]}{label}", report_id=rid, version=10 + "ABC".index(label),
                                       variant=label, edition="ai", payload=cur.payload,
                                       writer={"model": model, "effort": effort, "tier": "normal"},
                                       run_id=f"mrr_{rid[-6:]}{label}",
                                       validation={"first": [{"path": "title", "code": "style_word"}]},
                                       created_at=now_utc()))
        r.closed_at = now_utc()
        db.commit()


def test_blind_test_votes_and_reveal(on, client, other_client, monkeypatch):
    admin_on(monkeypatch)
    rid = make(visibility="admin", trial=True)
    _trial_runs(rid)
    trial = client.get(f"{API}/admin/market-reports/trial").json()
    assert trial["reveal"] is None and trial["days_done"] == 1 and trial["finished"] is False
    [row] = trial["reports"]
    assert [v["label"] for v in row["variants"]] == ["A", "B", "C"]
    assert all("writer" not in v and "cost_usd" not in v["metrics"] for v in row["variants"])
    assert all(v["metrics"]["revised"] is False and v["metrics"]["refusal_category"] is None for v in row["variants"])
    ov = client.get(f"{API}/admin/market-reports/overview").json()
    assert all(x["model"] is None and x["cost_usd"] is None for x in ov["runs"] if x["purpose"] == "trial")
    v = client.get(f"{API}/admin/market-reports/{rid}/variants/B").json()
    assert v["variant"] == "B" and v.get("writer") is None
    assert v["validation"]["first_problems"] == [{"code": "style_word", "path": "title"}]
    assert v["validation"]["dropped"] == [] and v["validation"]["revised"] is False
    assert any(s.get("refs") for p in v["highlights"] for s in p["sentences"])
    assert client.put(f"{API}/admin/market-reports/{rid}/vote", json={"preferred": "B", "note": "比較清楚"}).json() == \
        {"report_id": rid, "preferred": "B", "note": "比較清楚"}
    assert client.put(f"{API}/admin/market-reports/{rid}/vote", json={"preferred": "D"}).status_code == 422
    r = client.post(f"{API}/admin/market-reports/trial/reveal", json={})
    assert r.status_code == 409 and "盲測還沒做完（1/9 份日報、週報 0/1）" in r.json()["error"]["message"]
    out = client.post(f"{API}/admin/market-reports/trial/reveal", json={"force": True}).json()
    assert out["complete"] is False and [k["kind"] for k in out["kinds"]] == ["premarket", "close", "weekly"]
    close = next(k for k in out["kinds"] if k["kind"] == "close")
    assert close["kind_label"] == "盤後重點" and close["suggested"] == {"model": "claude-sonnet-5-5", "effort": "high"}
    by = {(x["writer"]["model"], x["writer"]["effort"]): x for x in close["rows"]}
    assert by[("claude-opus-5-5", "high")]["passed"] and by[pipeline.TRIAL_DAILY[1]]["avg_cost_usd"] == 1.0
    assert sum(x["votes"] for x in close["rows"]) == 1 and all(x["reports"] == 1 for x in close["rows"])
    pre = next(k for k in out["kinds"] if k["kind"] == "premarket")
    assert pre["suggested"] is None and all(not x["passed"] and x["reports"] == 0 for x in pre["rows"])
    trial = client.get(f"{API}/admin/market-reports/trial").json()
    assert trial["reveal"]["kinds"] == out["kinds"]
    assert trial["reports"][0]["variants"][0]["writer"]["model"].startswith("claude-")
    # revealed: the models are named now
    v = client.get(f"{API}/admin/market-reports/{rid}/variants/B").json()
    assert v["writer"]["model"].startswith("claude-")
    assert other_client.get(f"{API}/admin/market-reports/trial").status_code == 404


def test_trial_variants_pending_running_and_missing(on, client, monkeypatch):
    """A variant with no run yet is 「pending」; one still writing answers 409 ``variant_running``; one that ended
    without an AI version (data only, skipped) is 404."""
    admin_on(monkeypatch)
    rid = make(visibility="admin", trial=True)
    with session_factory()() as db:
        for label, status in (("A", "running"), ("B", "data_only")):
            db.add(MarketReportRun(id=f"mrr_{rid[-6:]}{label}", report_id=rid, variant=label, purpose="trial",
                                   attempt=1, status=status, step="write" if status == "running" else "done",
                                   tier="normal", writer={"model": "claude-opus-5-5", "effort": "high"}, calls=[],
                                   cost_usd=0, metrics={} if status == "running" else {"data_only": True},
                                   started_at=now_utc(), heartbeat_at=now_utc()))
        db.commit()
    [row] = client.get(f"{API}/admin/market-reports/trial").json()["reports"]
    a, b, c = row["variants"]
    assert a["status"] == "running" and a["on_time"] is None and a["metrics"] is None
    assert b["status"] == "data_only" and b["metrics"]["data_only"] is True and b["metrics"]["dropped_sections"] == 0
    assert c == {"label": "C", "status": "pending", "attempts": 0, "finished_at": None, "on_time": None,
                 "published": False, "problems": None, "metrics": None}
    r = client.get(f"{API}/admin/market-reports/{rid}/variants/A")
    assert r.status_code == 409 and r.json()["error"]["code"] == "variant_running"
    assert client.get(f"{API}/admin/market-reports/{rid}/variants/B").status_code == 404
    assert client.get(f"{API}/admin/market-reports/{rid}/variants/C").status_code == 404


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


def test_tz_time_is_today():
    assert datetime(2026, 11, 16, tzinfo=TAIPEI).date() == MON


def test_deleting_the_account_removes_seen_and_votes(on, client, monkeypatch, engine):
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from forliosa.models import MarketReportRead, MarketReportVote

    admin_on(monkeypatch)
    rid = make(visibility="admin", trial=True)
    assert client.post(f"{API}/market/reports/seen").status_code == 204
    assert client.put(f"{API}/admin/market-reports/{rid}/vote", json={"preferred": "A"}).status_code == 200
    from tests.api.test_account import CONFIRM

    r = client.request("DELETE", f"{API}/me", json=CONFIRM)
    assert r.status_code == 204, r.text
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(MarketReportRead)) == 0
        assert db.scalar(select(func.count()).select_from(MarketReportVote)) == 0
