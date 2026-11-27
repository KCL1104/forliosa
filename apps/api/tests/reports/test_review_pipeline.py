"""Review fixes of the state machine (2026-11-17): the push without a usable key and at the fallback time, a writing
attempt kept alive by its heartbeat and never published once abandoned, the replies of a failed attempt booked, the
reports' own key slot as the worker sees it, corrections of the title and highlights."""

from __future__ import annotations

import threading
import time
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.ai.keypool import KeyPool
from forliosa.api.errors import ApiError
from forliosa.models import MarketReport, MarketReportRun, User
from forliosa.reports import accounting, assemble, calls, pipeline, service
from forliosa.reports import settings as rs
from tests.ai.fake_anthropic import text
from tests.reports import test_pipeline
from tests.reports.conftest import MON, TUE, ts
from tests.reports.helpers import close_output, json_text, with_web
from tests.reports.test_pipeline import pk_close, report, runs, script_gather, tick, versions

env = test_pipeline.env  # the state machine tests' fixture (sessions, the fake model, the clock)
SUN = date(2026, 11, 22)


def _run(rid: str, run_id: str, attempt: int, status: str, at, *, variant=None, purpose="live",
         effort="high") -> MarketReportRun:
    return MarketReportRun(id=run_id, report_id=rid, variant=variant, purpose=purpose, attempt=attempt, status=status,
                           step="write" if status == "running" else "done", tier="normal",
                           writer={"model": "claude-opus-5-5", "effort": effort}, calls=[], cost_usd=Decimal(0),
                           metrics={}, started_at=at, heartbeat_at=at)


# -- the push ------------------------------------------------------------------------------------------------------
def test_no_usable_key_pushes_the_data_edition_on_time(env, us_on):
    env["deps"].pool = KeyPool([])
    env["deps"].settings = None
    tick(env, ts(MON, 14, 11))
    tick(env, ts(MON, 15, 51))
    tick(env, ts(MON, 16, 0))
    r = report(env)
    assert r.pushed_at is not None and r.push_edition == "data"  # 16:00, not never
    assert versions(env, r.id)[-1].payload["status_line"] != assemble.STATUS_WAITING  # no AI edition is coming
    tick(env, ts(TUE, 6, 56))
    tick(env, ts(TUE, 7, 30))
    pre = report(env, "premarket", TUE)
    assert pre.pushed_at is not None and pre.push_edition == "data"  # 07:30, not 08:15
    tick(env, ts(SUN, 16, 31))
    tick(env, ts(SUN, 18, 0))
    wk = report(env, "weekly", SUN)
    assert wk.pushed_at is not None and wk.push_edition == "data"  # 18:00


def test_an_attempt_running_at_the_fallback_time_does_not_stop_the_push(env):
    tick(env, ts(MON, 14, 11))
    r = report(env)
    with Session(env["engine"]) as db:
        db.add(_run(r.id, "mrr_1", 1, "failed", ts(MON, 15, 51)))
        db.add(_run(r.id, "mrr_2", 2, "running", ts(MON, 17, 25)))
        db.commit()
    tick(env, ts(MON, 17, 29))
    assert report(env).pushed_at is None  # still waiting for the AI edition
    tick(env, ts(MON, 17, 30))
    r = report(env)
    assert r.pushed_at is not None and r.push_edition == "data" and r.closed_at is not None


def test_a_worker_down_past_the_deadline_pushes_nothing(env):
    tick(env, ts(MON, 14, 11))
    tick(env, ts(MON, 17, 41))  # the first tick after 17:30 + PUSH_GRACE
    r = report(env)
    assert r.pushed_at is None and r.closed_at is not None
    assert pipeline.push_deadline(pipeline.edition_on("close", MON)) == ts(MON, 17, 40)
    assert pipeline.push_deadline(pipeline.edition_on("premarket", TUE)) == ts(TUE, 8, 40)


# -- an attempt kept alive, and never published once abandoned -------------------------------------------------------
def test_the_heartbeat_moves_while_a_call_streams(env, monkeypatch):
    tick(env, ts(MON, 14, 11))
    r = report(env)
    with Session(env["engine"]) as db:
        db.add(_run(r.id, "mrr_beat", 1, "running", ts(MON, 15, 51)))
        db.commit()
    env["clock"].t = ts(MON, 16, 30)
    with pipeline.heartbeat(env["deps"], "mrr_beat", every=0.02):
        time.sleep(0.2)
    [run] = runs(env, r.id)
    assert pipeline._aware(run.heartbeat_at) == ts(MON, 16, 30)
    pipeline.abandon_stale(Session(env["engine"]), ts(MON, 16, 40))
    assert runs(env, r.id)[0].status == "running"  # 10 minutes since the last beat: alive


def test_a_run_abandoned_meanwhile_never_publishes_and_no_second_attempt_doubles(env, monkeypatch):
    tick(env, ts(MON, 14, 11))
    script_gather(env["fake"])
    tick(env, ts(MON, 15, 41))
    out = close_output(with_web(pk_close(env)))
    env["fake"].reply(json_text(out)).reply(json_text({"issues": []}))
    started, release = threading.Event(), threading.Event()
    real = pipeline.write.write

    def slow_write(*a, **kw):
        started.set()
        release.wait(5)
        return real(*a, **kw)

    monkeypatch.setattr(pipeline.write, "write", slow_write)
    jobs: list = []
    env["deps"].submit = jobs.append
    tick(env, ts(MON, 15, 51))
    [job] = jobs
    t = threading.Thread(target=job)
    t.start()
    assert started.wait(5)
    with Session(env["engine"]) as db:  # the worker restarted elsewhere: the run is taken for dead
        run = db.scalars(select(MarketReportRun)).one()
        run.status, run.error = "abandoned", "stale"
        db.commit()
    release.set()
    t.join(10)
    [run] = runs(env, report(env).id)
    assert run.status == "abandoned" and run.error == "stale"
    assert [v.edition for v in versions(env, report(env).id)] == ["data"]  # never published
    assert run.calls and float(run.cost_usd) > 0  # its calls are still written down


def test_a_job_whose_run_is_no_longer_running_does_nothing(env):
    tick(env, ts(MON, 14, 11))
    r = report(env)
    with Session(env["engine"]) as db:
        db.add(_run(r.id, "mrr_gone", 1, "abandoned", ts(MON, 15, 51)))
        db.commit()
    pipeline._write_job(env["deps"], "mrr_gone")
    assert env["fake"].requests == [] and runs(env, r.id)[0].status == "abandoned"


def test_a_stream_past_its_total_time_is_stopped(env, monkeypatch):
    clock = iter(range(0, 100_000, 1000))
    monkeypatch.setattr(calls.time, "monotonic", lambda: next(clock))
    env["fake"].reply(text("x" * 50))
    client = env["deps"].key_pool().get(1).client
    with pytest.raises(calls.StreamTooLong):
        calls.stream(client, {"model": "claude-opus-5-5", "max_tokens": 10, "messages": []}, timeout=900)


def test_the_replies_of_a_failed_attempt_are_booked(env):
    tick(env, ts(MON, 14, 11))
    script_gather(env["fake"])
    tick(env, ts(MON, 15, 41))
    with Session(env["engine"]) as db:
        before = accounting.month_spend(db, ts(MON, 16))
    env["fake"].reply(text('{"title": "…'), stop_reason="max_tokens", usage={"output_tokens": 64000})
    env["fake"].error(529, "overloaded_error").error(529, "overloaded_error")
    tick(env, ts(MON, 15, 51))
    [run] = runs(env, report(env).id)
    with Session(env["engine"]) as db:
        after = accounting.month_spend(db, ts(MON, 16))
    assert run.status == "failed" and run.error == "OverloadedError"
    assert float(run.cost_usd) >= 1.28 and after - before >= Decimal("1.28")  # 64K Opus 5.5 output tokens
    assert [c["stop_reason"] for c in run.calls if "step" in c] == ["max_tokens"]


# -- the reports' own key slot, as the worker sees it --------------------------------------------------------------
def test_the_admin_page_shows_the_worker_s_key_slot(env, monkeypatch):
    pool = KeyPool.from_keys([(1, "sk-a"), (4, "sk-b")], client_factory=env["fake"].client, sleep=lambda _s: None,
                             reserved=frozenset({4}))
    pool.get(4).disabled = True  # the worker's pool: #4 answered 401
    env["deps"].pool = pool
    tick(env, ts(MON, 14, 11))
    with Session(env["engine"]) as db:
        cfg = rs.config(db)
        assert cfg.key_state["slot"] == 4 and cfg.key_state["status"] == "disabled"
        assert "sk-" not in str(cfg.key_state)
        api_pool = KeyPool.from_keys([(1, "sk-a"), (4, "sk-b")], client_factory=env["fake"].client,
                                     reserved=frozenset({4}))  # the API process's own pool: #4 never used
        monkeypatch.setattr("forliosa.ai.keypool.get_key_pool", lambda: api_pool)
        key = service.overview(db, now=ts(MON, 14, 12))["key"]
        assert key == {"slot": 4, "status": "disabled", "note": calls.KEY_UNUSABLE_NOTE}
        key = service.overview(db, now=ts(MON, 15, 0))["key"]
        assert service.KEY_STALE_NOTE in key["note"]  # the worker has not written for 49 minutes


# -- corrections ---------------------------------------------------------------------------------------------------
def test_a_correction_puts_the_rule_made_title_and_highlights_back(env):
    tick(env, ts(MON, 14, 11))
    script_gather(env["fake"])
    tick(env, ts(MON, 15, 41))
    out = close_output(with_web(pk_close(env)))
    env["fake"].reply(json_text(out)).reply(json_text({"issues": []}))
    tick(env, ts(MON, 15, 51))
    r = report(env)
    with Session(env["engine"]) as db:
        u = User(id="usr_admin", email="admin@x.tw", display_name="管理員")
        db.add(u)
        db.commit()
        with pytest.raises(ApiError) as bad:
            service.correction(db, u, r.id, "拼錯段落", ["what_hapened"])
        assert bad.value.status == 422 and bad.value.details == {"field": "drop_sections"}
        got = service.correction(db, u, r.id, "標題的漲跌幅寫錯", ["title", "highlights"])
    assert got["title"].startswith("盤後重點 11/16（一）：加權指數") and got["title_origin"] == "rules"
    assert got["highlights_origin"] == "rules" and got["has_ai"] is True  # the sections are still AI
    # the brief keeps its fields: the writer's rows (貢獻, 籌碼) are gone, the server's stand in and are renumbered
    assert [(r["key"], r["origin"]) for r in got["brief"]] == [("drivers", "rules"), ("volume", "rules")]
    assert got["highlights"] == [r["paragraph"] for r in got["brief"]]
    # (both are Forliosa's own calculations of the day: one footnote, the first)
    assert [sent["cites"] for r in got["brief"] for sent in r["paragraph"]["sentences"]] == [[1], [1]]
    assert got["corrections"][0]["note"] == "標題的漲跌幅寫錯"
    with Session(env["engine"]) as db:
        u = db.get(User, "usr_admin")
        ai_keys = [s["key"] for s in versions(env, r.id)[-1].payload["sections"] if s["origin"] == "ai"]
        got = service.correction(db, u, r.id, "整份拿掉 AI 段落", ai_keys)
    assert got["has_ai"] is False and got["model_line"] is None
    assert got["disclaimer_full"] == assemble.DISCLAIMER_FULL_DATA and got["disclaimer_line"] == \
        assemble.DISCLAIMER_DATA
    with Session(env["engine"]) as db:
        assert db.get(MarketReport, r.id).current_version_id == versions(env, r.id)[-1].id
