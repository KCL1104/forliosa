"""The state machine (contract §5, §17) on the conftest market, with the model faked behind the real SDK: a close
edition from the data edition to the AI edition, the push, the close and the table version; the blind test; budget
tiers; the alarm; refusals; revisions and dropped sections; stale runs; a closed day; retention."""

from __future__ import annotations

import copy
import zlib
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.ai.keypool import KeyPool
from forliosa.config import Settings, get_settings
from forliosa.models import (
    AiUsage,
    AiWhyResearch,
    MarketReport,
    MarketReportGather,
    MarketReportRun,
    MarketReportVersion,
)
from forliosa.reports import accounting, assemble, calls, compliance, gather, pack, pipeline
from forliosa.reports import settings as rs
from tests.ai.fake_anthropic import FakeAnthropic, text
from tests.reports.conftest import MON, TUE, ts
from tests.reports.helpers import close_output, fid, gather_reply, json_text, p, s, with_web

CNA = "https://www.cna.com.tw/news/afe/202611160123.aspx"
CITED = "外資今天賣超 1,234.5 億元，投信賣超 179.63 億元，自營商賣超 50 億元，三大法人合計賣超。"
TSMC_URL = "https://money.udn.com/money/story/5607/9000001"
TSMC_CITED = "台積電今天跌停附近震盪，外資連續賣超，市場關注美國出口管制消息與先進製程需求。"


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self) -> datetime:
        return self.t


@pytest.fixture()
def env(engine, market_db, monkeypatch):
    monkeypatch.setenv("MARKET_REPORTS_ENABLED", "true")
    monkeypatch.setenv("MARKET_REPORTS_INITIAL_MODE", "public")
    get_settings.cache_clear()
    monkeypatch.setattr(gather, "TOPIC_THREADS", 1)
    monkeypatch.setattr(pipeline, "_names", None)
    calls.reset_state()
    compliance.reset_state()
    fake = FakeAnthropic()
    pool = KeyPool.from_keys([(1, "sk-test-reports")], client_factory=fake.client, sleep=lambda _s: None)
    clock = Clock(ts(MON, 14, 11))
    deps = pipeline.Deps(session=lambda: Session(engine), pool=pool, submit=lambda fn: fn(), clock=clock)
    yield {"fake": fake, "deps": deps, "clock": clock, "engine": engine}
    get_settings.cache_clear()


def tick(env, at: datetime) -> pipeline.TickResult:
    env["clock"].t = at
    return pipeline.tick(at, env["deps"])


def pk_close(env, at=None) -> dict:
    with Session(env["engine"]) as db:
        return pack.build(db, "close", MON, cutoff=ts(MON, 15, 40), now=at or ts(MON, 15, 51)).pack


def script_gather(fake) -> None:
    fake.reply(text("沒有找到。"))  # MARKET_TODAY
    fake.reply(*gather_reply("TWSE_INST.foreign", "〔中央社〕報導，外資 11/16 賣超 1,234.5 億元。", CNA, "外資賣超千億",
                             CITED))
    fake.reply(*gather_reply("STOCK.2330", "〔經濟日報〕報導，台積電 11/16 下跌，外資連續賣超。", TSMC_URL,
                             "台積電震盪",
                             TSMC_CITED, page_age="2026-11-16T14:05:00+08:00"))
    fake.reply(text("沒有找到。"))  # TONIGHT


def report(env, kind="close", d=MON) -> MarketReport:
    with Session(env["engine"]) as db:
        r = db.scalar(select(MarketReport).where(MarketReport.kind == kind, MarketReport.edition_date == d))
        if r is not None:
            db.expunge(r)
        return r


def versions(env, rid) -> list[MarketReportVersion]:
    with Session(env["engine"]) as db:
        rows = list(db.scalars(select(MarketReportVersion).where(MarketReportVersion.report_id == rid)
                               .order_by(MarketReportVersion.version)))
        for r in rows:
            db.expunge(r)
        return rows


def runs(env, rid) -> list[MarketReportRun]:
    with Session(env["engine"]) as db:
        rows = list(db.scalars(select(MarketReportRun).where(MarketReportRun.report_id == rid)
                               .order_by(MarketReportRun.started_at, MarketReportRun.variant)))
        for r in rows:
            db.expunge(r)
        return rows


def test_close_day_from_data_to_ai_to_tables(env):
    fake = env["fake"]
    tick(env, ts(MON, 14, 5))
    assert report(env) is None  # before 14:10
    res = tick(env, ts(MON, 14, 11))
    r = report(env)
    assert r.state == "data" and r.visibility == "public" and "data edition" in res.actions[0]
    [v1] = versions(env, r.id)
    assert v1.edition == "data" and v1.payload["status_line"] == assemble.STATUS_WAITING
    assert v1.payload["title"].startswith("盤後重點 11/16（一）：加權指數 ▼6.03%")
    assert v1.payload["disclaimer_line"] == assemble.DISCLAIMER_DATA and v1.payload["model_line"] is None
    # the gathering at 15:40 (four topics, one call each)
    script_gather(fake)
    tick(env, ts(MON, 15, 41))
    with Session(env["engine"]) as db:
        [g] = db.scalars(select(MarketReportGather)).all()
        assert g.status == "ok" and [x["key"] for x in g.facts] == ["TWSE_INST.foreign", "STOCK.2330"]
    assert len(fake.requests) == 4 and all(q["body"]["tools"][0]["type"] == "web_search_20260318"
                                           for q in fake.requests)
    # writing at 15:50: draft, check, published
    out = close_output(with_web(pk_close(env)))
    fake.reply(json_text(out)).reply(json_text({"issues": []}))
    tick(env, ts(MON, 15, 51))
    r = report(env)
    assert r.state == "ai" and r.ai_published_at is not None
    [run] = runs(env, r.id)
    assert run.status == "ok" and run.purpose == "live" and run.tier == "normal"
    assert run.writer == {"model": "claude-opus-5-5", "effort": "high"} and run.metrics["on_time"] is True
    assert [c["step"] for c in run.calls if "step" in c] == ["write", "check"]
    assert any("raw_output" in c for c in run.calls)
    packed = zlib.decompress(run.pack_gz).decode()
    assert '"X001"' in packed and "1,234.5" in packed
    v2 = versions(env, r.id)[-1]
    assert v2.edition == "ai" and v2.writer["tier"] == "normal" and r.current_version_id == v2.id
    pay = v2.payload
    assert pay["has_ai"] and pay["title_origin"] == "ai" and pay["model_line"] == assemble.MODEL_LINE
    assert [sec["key"] for sec in pay["sections"]][:5] == ["what_happened", "sectors", "stocks", "chips", "tonight"]
    assert pay["sources"]["web"][0]["outlet"] == "中央社"
    public = assemble.public(pay)
    assert not assemble.has_id_strings(pay) and "quote" not in str(public) and "refs" not in str(public)
    # accounting: every call booked to nobody, per feature
    with Session(env["engine"]) as db:
        rows = db.scalars(select(AiUsage)).all()
        assert sorted({u.feature for u in rows}) == ["mreport_check", "mreport_gather", "mreport_write"]
        assert all(u.user_id is None for u in rows) and {u.thread_id for u in rows} >= {run.id}
        # the verified report about 台積電 joins the shared research of the session (sources only)
        res_row = db.get(AiWhyResearch, ("2330.TW", MON, "after_close"))
        assert res_row is not None and res_row.sources[0]["url"] == TSMC_URL and not res_row.one_liner
    # push at 16:00 (mode public: queued for no channel here), closed at 17:30, tables at 23:45
    tick(env, ts(MON, 16, 0))
    r = report(env)
    assert r.pushed_at is not None and r.push_edition == "ai"
    tick(env, ts(MON, 17, 31))
    assert report(env).closed_at is not None
    n = len(versions(env, r.id))
    tick(env, ts(MON, 23, 46))
    vs = versions(env, r.id)
    assert len(vs) == n + 1 and vs[-1].edition == "tables" and vs[-1].based_on == v2.id
    assert vs[-1].payload["title"] == pay["title"]  # the AI text stays
    tick(env, ts(MON, 23, 50))
    assert len(versions(env, r.id)) == n + 1  # once per slot
    assert report(env).current_version_id == vs[-1].id


def test_trial_writes_three_variants_for_admins_only(env, monkeypatch):
    monkeypatch.setenv("MARKET_REPORTS_INITIAL_MODE", "trial")
    get_settings.cache_clear()
    fake = env["fake"]
    tick(env, ts(MON, 14, 11))
    r = report(env)
    assert r.visibility == "admin" and r.trial
    script_gather(fake)
    tick(env, ts(MON, 15, 41))
    out = close_output(with_web(pk_close(env)))
    for _ in range(3):
        fake.reply(json_text(out)).reply(json_text({"issues": []}))
    tick(env, ts(MON, 15, 51))
    rs_ = runs(env, r.id)
    assert sorted(x.variant for x in rs_) == ["A", "B", "C"] and {x.purpose for x in rs_} == {"trial"}
    assert {(x.writer["model"], x.writer["effort"]) for x in rs_} == set(pipeline.TRIAL_DAILY)
    vs = versions(env, r.id)
    assert sorted(v.variant for v in vs if v.variant) == ["A", "B", "C"]
    r = report(env)
    assert r.state == "data" and next(v for v in vs if v.id == r.current_version_id).edition == "data"
    with Session(env["engine"]) as db:
        assert {u.feature for u in db.scalars(select(AiUsage))} == {"mreport_trial"}
        assert rs.config(db).trial_started_on == MON
        assert accounting.month_spend(db) == 0 and accounting.trial_spend(db) > 0
    tick(env, ts(MON, 16, 1))
    assert report(env).pushed_at is None  # never pushed in the trial


def test_trial_variants_beyond_the_cap_are_skipped(env, monkeypatch):
    monkeypatch.setenv("MARKET_REPORTS_INITIAL_MODE", "trial")
    get_settings.cache_clear()
    tick(env, ts(MON, 14, 11))
    assert report(env).trial
    env["deps"].settings = Settings(market_reports_enabled=True, ai_mreport_trial_budget_usd=1.0)
    tick(env, ts(MON, 15, 51))  # no gathering (it would not fit), then every variant skipped
    assert {x.status for x in runs(env, report(env).id)} == {"skipped_budget"}
    assert env["fake"].requests == []


def test_budget_tiers_change_the_writer(env):
    with Session(env["engine"]) as db:
        db.add(AiUsage(user_id=None, thread_id="x", feature="mreport_write", model="claude-opus-5-5",
                       cost_usd=Decimal("75"), created_at=ts(MON, 9)))
        db.commit()
    tick(env, ts(MON, 14, 11))
    script_gather(env["fake"])
    tick(env, ts(MON, 15, 41))
    out = close_output(with_web(pk_close(env)))
    env["fake"].reply(json_text(out)).reply(json_text({"issues": []}))
    tick(env, ts(MON, 15, 51))
    [run] = runs(env, report(env).id)
    assert run.tier == "sonnet" and run.writer == {"model": "claude-sonnet-5-5", "effort": "high"}
    with Session(env["engine"]) as db:
        db.add(AiUsage(user_id=None, thread_id="y", feature="mreport_write", model="claude-opus-5-5",
                       cost_usd=Decimal("10"), created_at=ts(MON, 9)))
        db.commit()
        assert accounting.tier(db, "close", ts(MON, 16), get_settings()) == "data_only"


def test_a_hard_problem_is_revised_then_its_section_dropped(env):
    tick(env, ts(MON, 14, 11))
    script_gather(env["fake"])
    tick(env, ts(MON, 15, 41))
    pk = with_web(pk_close(env))
    bad = close_output(pk)
    pct = fid(pk, "index_pct", group="today")
    bad["what_happened"] = [p(s("加權指數跌 6.03%，明天可能反彈。", pct)), bad["what_happened"][1]]
    env["fake"].reply(json_text(bad))  # draft: a hard problem, no check
    env["fake"].reply(json_text(bad))  # the revision still has it
    env["fake"].reply(json_text({"issues": []}))  # the check of what is left
    tick(env, ts(MON, 15, 51))
    [run] = runs(env, report(env).id)
    assert run.status == "ok" and run.metrics["revised"] and run.metrics["dropped_sections"] == 1
    body = env["fake"].requests[-2]["body"]
    assert body["messages"][1]["role"] == "assistant" and "forbidden_word" in body["messages"][2]["content"]
    pay = versions(env, report(env).id)[-1].payload
    dropped = next(sec for sec in pay["sections"] if sec["key"] == "what_happened")
    assert dropped["dropped"] == {"reasons": ["forbidden_word", "outlook_pattern"]}
    public = assemble.public(pay)
    kept = next(sec for sec in public["sections"] if sec["key"] == "what_happened")
    assert kept["origin"] == "data" and all(b["type"] != "text" for b in kept["blocks"])  # G1 only
    assert "明天" not in str(public)


def test_compliance_issues_lead_to_a_revision(env):
    tick(env, ts(MON, 14, 11))
    script_gather(env["fake"])
    tick(env, ts(MON, 15, 41))
    out = close_output(with_web(pk_close(env)))
    quote = out["sectors"][0]["sentences"][0]["text"][:5]
    env["fake"].reply(json_text(out))
    env["fake"].reply(json_text({"issues": [{"path": "sectors[0].sentences[0]", "category": "direction",
                                             "quote": quote}]}))
    env["fake"].reply(json_text(out))  # the revision (same text)
    env["fake"].reply(json_text({"issues": [{"path": "sectors[0].sentences[0]", "category": "direction",
                                             "quote": quote}]}))
    tick(env, ts(MON, 15, 51))
    [run] = runs(env, report(env).id)
    assert run.status == "ok" and run.metrics["dropped_sections"] == 1
    pay = versions(env, report(env).id)[-1].payload
    assert next(sec for sec in pay["sections"] if sec["key"] == "sectors")["dropped"]["reasons"] == \
        ["compliance:direction"]


def test_a_refusal_publishes_nothing_and_says_so(env):
    tick(env, ts(MON, 14, 11))
    script_gather(env["fake"])
    tick(env, ts(MON, 15, 41))
    env["fake"].reply(text(""), stop_reason="refusal", stop_details={"type": "refusal", "category": "cyber"})
    tick(env, ts(MON, 15, 51))
    r = report(env)
    [run] = runs(env, r.id)
    assert run.status == "data_only" and run.error == "refusal:cyber" and run.metrics["refusal_category"] == "cyber"
    assert r.state == "data"
    assert versions(env, r.id)[-1].payload["status_line"] == assemble.STATUS_DATA_ONLY
    tick(env, ts(MON, 15, 55))
    assert len(runs(env, r.id)) == 1  # no retry after a refusal
    tick(env, ts(MON, 16, 0))
    assert report(env).push_edition == "data"  # no AI edition will come: the data edition goes at 16:00


def test_failures_are_retried_up_to_the_limit(env):
    tick(env, ts(MON, 14, 11))
    script_gather(env["fake"])
    tick(env, ts(MON, 15, 41))
    env["fake"].reply(text("not json"))
    tick(env, ts(MON, 15, 51))
    env["fake"].reply(text("still not json"))
    tick(env, ts(MON, 15, 52))
    tick(env, ts(MON, 15, 53))
    assert [x.status for x in runs(env, report(env).id)] == ["failed", "failed"]
    tick(env, ts(MON, 16, 0))
    assert report(env).push_edition == "data"


def test_the_alarm_stops_further_calls(env):
    tick(env, ts(MON, 14, 11))
    script_gather(env["fake"])
    tick(env, ts(MON, 15, 41))
    env["deps"].settings = Settings(market_reports_enabled=True, ai_mreport_run_alarm_usd=0.000001)
    out = close_output(with_web(pk_close(env)))
    env["fake"].reply(json_text(out))
    n = len(env["fake"].requests)
    tick(env, ts(MON, 15, 51))
    [run] = runs(env, report(env).id)
    assert run.status == "data_only" and run.error == "alarm" and len(env["fake"].requests) == n + 1


def test_a_result_after_the_close_is_abandoned(env):
    tick(env, ts(MON, 14, 11))
    r = report(env)
    with Session(env["engine"]) as db:
        run = MarketReportRun(id="mrr_late", report_id=r.id, purpose="live", attempt=1, status="running",
                              step="write", tier="normal", writer={"model": "claude-opus-5-5", "effort": "high"},
                              calls=[], cost_usd=Decimal(0), metrics={}, started_at=ts(MON, 17),
                              heartbeat_at=ts(MON, 17))
        db.add(run)
        db.commit()
    out = close_output(pk_close(env))
    out["chips"] = [p(s("上市三大法人尚未取得可引用的報導。", fid(pk_close(env), "index_close", group="today")))]
    env["fake"].reply(json_text(out)).reply(json_text({"issues": []}))
    env["clock"].t = ts(MON, 17, 31)
    with Session(env["engine"]) as db:
        pipeline.attempt(db, db.get(MarketReportRun, "mrr_late"), env["deps"])
    [run] = runs(env, r.id)
    assert run.status == "abandoned" and run.error == "after_close"
    assert report(env).state == "data"


def test_stale_runs_are_abandoned(env):
    tick(env, ts(MON, 14, 11))
    r = report(env)
    with Session(env["engine"]) as db:
        db.add(MarketReportRun(id="mrr_stale", report_id=r.id, purpose="live", attempt=1, status="running",
                               step="write", tier="normal", writer={"model": "claude-opus-5-5", "effort": "high"},
                               calls=[], cost_usd=Decimal(0), metrics={}, started_at=ts(MON, 14, 12),
                               heartbeat_at=ts(MON, 14, 12)))
        db.commit()
    tick(env, ts(MON, 14, 40))
    assert runs(env, r.id)[0].status == "abandoned"


def test_a_day_without_a_session_is_skipped(env):
    tick(env, ts(TUE, 14, 11))
    r = report(env, "close", TUE)
    assert r.state == "pending"
    tick(env, ts(TUE, 15, 1))
    r = report(env, "close", TUE)
    assert r.state == "skipped" and r.current_version_id is None and "no_session" in r.notes
    tick(env, ts(TUE, 15, 51))
    assert runs(env, r.id) == [] and env["fake"].requests == []


def test_paused_makes_nothing(env):
    with Session(env["engine"]) as db:
        cfg = rs.config(db)
        cfg.mode = "paused"
        db.commit()
    tick(env, ts(MON, 14, 11))
    assert report(env) is None


def test_premarket_waits_for_the_ai_edition_then_falls_back(env, us_on):
    env["deps"].settings = None
    tick(env, ts(TUE, 6, 56))
    r = report(env, "premarket", TUE)
    assert r.state == "data"
    with Session(env["engine"]) as db:  # an attempt still running at 07:30: the push waits
        db.add(MarketReportRun(id="mrr_run", report_id=r.id, purpose="live", attempt=1, status="running",
                               step="write", tier="normal", writer={"model": "claude-opus-5-5", "effort": "high"},
                               calls=[], cost_usd=Decimal(0), metrics={}, started_at=ts(TUE, 7, 25),
                               heartbeat_at=ts(TUE, 7, 25)))
        db.add(MarketReportGather(id="mrg_x", report_id=r.id, status="failed", topics=[], facts=[], disagreements=[],
                                  cost_usd=Decimal(0), started_at=ts(TUE, 6, 15)))
        db.commit()
    tick(env, ts(TUE, 7, 30))
    assert report(env, "premarket", TUE).pushed_at is None
    tick(env, ts(TUE, 8, 15))
    r = report(env, "premarket", TUE)
    assert r.pushed_at is not None and r.push_edition == "data"
    tick(env, ts(TUE, 8, 41))
    r = report(env, "premarket", TUE)
    assert r.closed_at is not None
    assert versions(env, r.id)[-1].payload["status_line"] == assemble.STATUS_DATA_ONLY


def test_retention(env):
    tick(env, ts(MON, 14, 11))
    with Session(env["engine"]) as db:
        assert pipeline.purge_old(db, now=ts(MON + timedelta(days=730), 12)) == 0
        assert pipeline.purge_old(db, now=ts(MON + timedelta(days=731), 12)) == 1
        assert db.scalars(select(MarketReportVersion)).all() == []


def test_cli_backfill_is_admin_only_and_never_pushed(env):
    with Session(env["engine"]) as db:
        r = pipeline.backfill_data(db, "close", MON, env["deps"], now=ts(date(2026, 11, 20), 10))
        assert r.backfill and r.visibility == "admin" and r.state == "data"
        v = pipeline.current(db, r)
        assert v.payload["status_line"] == assemble.STATUS_DATA_ONLY
    tick(env, ts(MON, 16, 1))
    assert report(env).pushed_at is None


def test_correction_and_copy_are_independent(env):
    tick(env, ts(MON, 14, 11))
    r = report(env)
    from forliosa.models import User
    from forliosa.reports import service

    with Session(env["engine"]) as db:
        u = User(id="usr_admin", email="admin@x.tw", display_name="管理員")
        db.add(u)
        db.commit()
        out = service.correction(db, u, r.id, "加權指數的漲跌點數寫錯", ["what_happened"])
    assert out["edition"] == "correction" and out["corrections"][0]["note"] == "加權指數的漲跌點數寫錯"
    vs = versions(env, r.id)
    assert vs[-1].edition == "correction" and vs[-1].correction_note == "加權指數的漲跌點數寫錯"
    assert copy.deepcopy(vs[0].payload).get("corrections") == []
