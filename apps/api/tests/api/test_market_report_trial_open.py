"""盲測開給所有登入的人（產品負責人 2026-11-17：「我讓我的朋友們一起選」; ``MREPORT_TRIAL_AUDIENCE``).

* audience ``admins`` (default): nothing changes — a member gets 404 on a blind-test edition and its new endpoints;
* audience ``all``: a member lists and reads the edition and its A / B / C in the public form (no refs, ids, models or
  costs before the reveal, and nothing that tells when each was written), votes once and changes the vote, cannot
  reveal; admins' and members' votes are counted together and the admin page shows them apart; after the reveal the
  vote is closed (the admin endpoint too) and the labels are named; 「還在寫」 only while a variant can still come;
* pushes: only while the mode is trial and the audience all, once per edition and channel, only to channels whose
  switch for the kind is on, with the vote link and no variant's text; never after the push deadline; re-checked
  when sent.
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from forliosa import disclaimer
from forliosa.config import get_settings
from forliosa.db import session_factory
from forliosa.models import MarketReport, MarketReportRun, MarketReportVersion, MarketReportVote, NotificationOutbox
from forliosa.reports import assemble, pack, pipeline, push, service
from forliosa.reports import settings as rs
from forliosa.services import notifications
from forliosa.timeutil import TAIPEI, iso_taipei, now_utc
from tests.api.m5 import API, make_group
from tests.api.push_fake import WEBHOOK, PushFake
from tests.reports.conftest import MON, seed_market, ts
from tests.reports.helpers import INST_X, close_output, with_web

ID = re.compile(r"\b[FXCNW]\d{3}\b")


@pytest.fixture()
def on(app, monkeypatch):
    monkeypatch.setenv("MARKET_REPORTS_ENABLED", "true")
    monkeypatch.setenv("FRONTEND_URL", "https://forliosa.trade")
    get_settings.cache_clear()
    with session_factory()() as db:
        seed_market(db)
    yield
    get_settings.cache_clear()


@pytest.fixture()
def everyone(on, monkeypatch):
    monkeypatch.setenv("MREPORT_TRIAL_AUDIENCE", "all")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def admin_on(monkeypatch, email="demo@forliosa.local"):
    monkeypatch.setattr(get_settings(), "admin_emails", [email])


def make_trial(d=MON, ready="ABC", running="", published=None) -> str:
    """A blind-test close edition the way the pipeline leaves it: the data edition is current (rule-made title), and
    each label in ``ready`` has a finished run and its own AI version (with refs, as stored); ``running`` ones are
    still being written."""
    published = published or now_utc()
    with session_factory()() as db:
        ed = pipeline.edition_on("close", d)
        r = pipeline.make_report(db, ed, published, visibility="admin", trial=True)
        built = pack.build(db, "close", d, cutoff=ts(d, 15, 40), now=ts(d, 16))
        pk = with_web(built.pack, INST_X)
        common = dict(kind="close", report_id=r.id, edition_date=d, period=ed.period, next_period=ed.next_period,
                      version=0, pack=pk, blocks=built.blocks, published_at=published, first_published_at=published,
                      as_of=ts(d, 15, 40))
        data = assemble.build(**common, edition="data", output=None)
        v = pipeline.new_version(db, r, edition="data", payload=data, now=published)
        r.current_version_id, r.state, r.first_published_at = v.id, "data", published
        for label, (model, effort) in zip("ABC", pipeline.TRIAL_DAILY, strict=True):
            if label not in ready and label not in running:
                continue
            run = MarketReportRun(id=f"mrr_{r.id[-6:]}{label}", report_id=r.id, variant=label, purpose="trial",
                                  attempt=1, status="ok" if label in ready else "running",
                                  step="done" if label in ready else "write", tier="normal",
                                  writer={"model": model, "effort": effort}, calls=[], cost_usd=0.5,
                                  metrics={"on_time": True, "cost_usd": 1.25, "policy_violations": 0,
                                           "subject_mismatches": 0, "inferred_dates": 0, "dropped_sections": 0,
                                           "data_only": False, "seconds": 300} if label in ready else {},
                                  started_at=published, heartbeat_at=published,
                                  finished_at=published if label in ready else None)
            db.add(run)
            db.flush()
            if label in ready:
                ai = assemble.build(**common, edition="ai", output=close_output(pk), title_origin="ai",
                                    highlights_origin="ai")
                ai["highlights"][0]["sentences"][0]["text"] = f"只在 {label} 版的句子。"
                pipeline.new_version(db, r, edition="ai", payload=ai, now=published, variant=label,
                                     writer={"model": model, "effort": effort, "tier": "normal"}, run_id=run.id,
                                     validation={})
                r.ai_published_at = r.ai_published_at or published
        db.commit()
        return r.id


# -- audience admins: nothing changes ------------------------------------------------------------------------------
def test_admins_only_by_default(on, client, other_client, monkeypatch):
    admin_on(monkeypatch)
    rid = make_trial()
    for path in (f"/market/reports/{rid}", f"/market/reports/{rid}/trial", f"/market/reports/{rid}/variants/A"):
        r = other_client.get(f"{API}{path}")
        assert r.status_code == 404 and r.json()["error"]["message"] == "找不到這份報告"
    assert other_client.put(f"{API}/market/reports/{rid}/vote", json={"preferred": "A"}).status_code == 404
    st = other_client.get(f"{API}/market/reports/status").json()
    assert st == {"available": False, "mode": None, "unread": False, "latest": [], "trial_open": False}
    assert other_client.get(f"{API}/market/reports").json()["items"] == []
    # the admin reads the data edition as before (no 「trial」 page) and the member endpoints are 404 for him too
    body = client.get(f"{API}/market/reports/{rid}").json()
    assert body["trial"] is False and body["edition"] == "data"
    assert client.get(f"{API}/market/reports/{rid}/trial").status_code == 404
    with session_factory()() as db:
        assert rs.trial_audience(db) == "admins" and not push.trial_pushing(db)


# -- audience all ----------------------------------------------------------------------------------------------------
def test_members_list_read_and_vote(everyone, client, other_client, monkeypatch):
    admin_on(monkeypatch)
    rid = make_trial(ready="AB", running="C")
    st = other_client.get(f"{API}/market/reports/status").json()
    assert st["available"] and st["trial_open"] and st["mode"] is None and st["unread"] is True
    [s] = st["latest"]
    assert s["id"] == rid and s["trial"] is True and s["my_vote"] is None and s["kind_label"] == "盤後重點"
    assert s["title"].startswith("盤後重點 11/16（一）")  # the data edition's rule-made title, the same for A / B / C
    [row] = other_client.get(f"{API}/market/reports").json()["items"]
    assert row["id"] == rid and row["trial"] is True
    assert other_client.get(f"{API}/market/reports/{rid}").json()["trial"] is True
    t = other_client.get(f"{API}/market/reports/{rid}/trial").json()
    assert [(v["label"], v["state"]) for v in t["variants"]] == [("A", "ready"), ("B", "ready"), ("C", "writing")]
    assert all(v.get("writer") is None for v in t["variants"])
    assert t["can_vote"] and not t["revealed"] and t["votes"] is None and t["result"] is None and t["my_vote"] is None
    # a variant: the public form — no refs, no ids, no model, no cost
    r = other_client.get(f"{API}/market/reports/{rid}/variants/B")
    assert r.status_code == 200
    raw = r.text
    assert not ID.search(raw) and '"refs"' not in raw and '"quote"' not in raw
    assert "claude-" not in raw and "opus" not in raw.lower() and "sonnet" not in raw.lower() and "cost" not in raw
    body = r.json()
    assert body["variant"] == "B" and body["trial"] is True and body["has_ai"]
    assert body["highlights"][0]["sentences"][0]["text"] == "只在 B 版的句子。"
    assert other_client.get(f"{API}/market/reports/{rid}/variants/C").json()["error"]["code"] == "variant_running"
    # vote, change the vote: one row per user and edition
    assert other_client.put(f"{API}/market/reports/{rid}/vote", json={"preferred": "A"}).json()["my_vote"] == "A"
    assert other_client.put(f"{API}/market/reports/{rid}/vote", json={"preferred": "B"}).json()["my_vote"] == "B"
    bad = other_client.put(f"{API}/market/reports/{rid}/vote", json={"preferred": "C"})  # not readable yet
    assert bad.status_code == 422 and bad.json()["error"]["details"] == {"field": "preferred"}
    assert other_client.put(f"{API}/market/reports/{rid}/vote", json={"preferred": "D"}).status_code == 422
    assert other_client.get(f"{API}/market/reports/status").json()["latest"][0]["my_vote"] == "B"
    with session_factory()() as db:
        rows = list(db.scalars(select(MarketReportVote).where(MarketReportVote.report_id == rid)))
        assert [(v.preferred, v.by_admin) for v in rows] == [("B", False)]
    # members never reach the admin side: no reveal, no admin variant (refs), no admin trial list
    assert other_client.post(f"{API}/admin/market-reports/trial/reveal", json={"force": True}).status_code == 404
    assert other_client.get(f"{API}/admin/market-reports/{rid}/variants/A").status_code == 404
    assert other_client.get(f"{API}/admin/market-reports/trial").status_code == 404


def test_the_three_variants_do_not_tell_when_each_was_written(everyone, other_client):
    """Each variant's own ``published_at`` (its finish time) and ``version`` (numbered in the order they finished)
    would hint which setting wrote it: all three answer the edition's (the first variant's time, the data edition's
    number)."""
    rid = make_trial()
    first = now_utc() - timedelta(hours=2)
    with session_factory()() as db:
        db.get(MarketReport, rid).ai_published_at = first
        vs = sorted(db.scalars(select(MarketReportVersion).where(MarketReportVersion.report_id == rid,
                                                                  MarketReportVersion.variant.is_not(None))),
                    key=lambda v: v.variant)
        for i, v in enumerate(vs):  # finished 1, 5 and 9 minutes after the first one was ready
            v.payload = {**v.payload, "published_at": iso_taipei(first + timedelta(minutes=4 * i + 1))}
        assert sorted(v.version for v in vs) == [2, 3, 4]  # stored in the order they finished
        db.commit()
    bodies = [other_client.get(f"{API}/market/reports/{rid}/variants/{label}").json() for label in "ABC"]
    assert {b["published_at"] for b in bodies} == {iso_taipei(first)}
    assert {b["version"] for b in bodies} == {1}  # the data edition's number
    assert len({b["first_published_at"] for b in bodies}) == 1 and len({b["as_of"] for b in bodies}) == 1


def test_a_variant_is_writing_only_while_it_can_still_come(everyone, other_client):
    """「還在寫」 only while a run is being written or the worker may still start (or retry) one — not paused, before
    the push fallback time, a usable key, attempts left; else 「沒有寫成」 (the page then shows the data edition)."""
    rid = make_trial(ready="A", running="B")  # C: no run yet
    t = other_client.get(f"{API}/market/reports/{rid}/trial").json()  # the edition is past its fallback time
    assert [(v["label"], v["state"]) for v in t["variants"]] == [("A", "ready"), ("B", "writing"), ("C", "none")]
    ed = pipeline.edition_on("close", MON)
    s = get_settings()
    with session_factory()() as db:
        r = db.get(MarketReport, rid)
        assert service._writes_may_start(db, r, s, now=ed.write_at)
        assert service._variant_state(db, r, "C", s, may_start=True)[0] == "writing"
        assert not service._writes_may_start(db, r, s, now=ed.push_fallback_at)
        cfg = rs.config(db)
        mode, cfg.mode = cfg.mode, "paused"
        db.commit()
        assert not service._writes_may_start(db, r, s, now=ed.write_at)
        cfg.mode, cfg.key_state = mode, {"slot": 3, "status": "disabled", "note": "目前不能用，只發資料版。"}
        db.commit()
        assert not service._writes_may_start(db, r, s, now=ed.write_at)
        cfg.key_state = {"slot": 3, "status": "ok", "note": None}
        db.commit()
        assert service._writes_may_start(db, r, s, now=ed.write_at)
        # a failed first attempt: retried while the worker may; none once it may not or no attempt is left
        at = ts(MON, 15, 55)
        db.add(MarketReportRun(id=f"mrr_{rid[-6:]}Cf", report_id=rid, variant="C", purpose="trial", attempt=1,
                               status="failed", step="write", tier="normal",
                               writer={"model": pipeline.TRIAL_DAILY[2][0], "effort": pipeline.TRIAL_DAILY[2][1]},
                               calls=[], cost_usd=0, metrics={}, started_at=at, heartbeat_at=at, finished_at=at))
        db.commit()
        assert service._variant_state(db, r, "C", s, may_start=True)[0] == "writing"
        assert service._variant_state(db, r, "C", s, may_start=False)[0] == "none"
        assert service._variant_state(db, r, "C", s.model_copy(update={"ai_mreport_max_attempts": 1}),
                                      may_start=True)[0] == "none"
        assert service._variant_state(db, r, "B", s, may_start=False)[0] == "writing"  # still being written
        r.closed_at = now_utc()
        db.commit()
        assert service._variant_state(db, r, "C", s, may_start=True)[0] == "none"


def test_admin_sees_votes_by_voter_type_and_the_reveal_closes_the_vote(everyone, app, client, other_client,
                                                                       monkeypatch):
    from tests.api.m5 import login

    admin_on(monkeypatch)
    rid = make_trial()
    third = login(app, "third@forliosa.local", "第三人")
    assert other_client.put(f"{API}/market/reports/{rid}/vote", json={"preferred": "C"}).status_code == 200
    assert third.put(f"{API}/market/reports/{rid}/vote", json={"preferred": "C"}).status_code == 200
    # the admin votes on the admin page (with a note) and again on the members' page: still one vote, note kept
    assert client.put(f"{API}/admin/market-reports/{rid}/vote", json={"preferred": "A", "note": "好讀"}).status_code \
        == 200
    assert client.put(f"{API}/market/reports/{rid}/vote", json={"preferred": "B"}).json()["my_vote"] == "B"
    trial = client.get(f"{API}/admin/market-reports/trial").json()
    assert trial["audience"] == "all" and trial["voters"] == {"admins": 1, "members": 2}
    [row] = trial["reports"]
    assert row["my_vote"] == {"preferred": "B", "note": "好讀"}
    assert row["votes"] == {"all": {"A": 0, "B": 1, "C": 2}, "admins": {"A": 0, "B": 1, "C": 0},
                            "members": {"A": 0, "B": 0, "C": 2}}
    ov = client.get(f"{API}/admin/market-reports/overview").json()
    assert ov["trial_audience"] == "all" and ov["trial_audience_source"] == "default"
    out = client.post(f"{API}/admin/market-reports/trial/reveal", json={"force": True}).json()
    close = next(k for k in out["kinds"] if k["kind"] == "close")
    assert sum(x["votes"] for x in close["rows"]) == 3
    assert sum(x["votes_admins"] for x in close["rows"]) == 1 and sum(x["votes_members"] for x in close["rows"]) == 2
    # after the reveal: members see the settings and the votes; the vote is closed
    t = other_client.get(f"{API}/market/reports/{rid}/trial").json()
    assert t["revealed"] and not t["can_vote"] and t["votes"] == {"A": 0, "B": 1, "C": 2} and t["my_vote"] == "C"
    assert [v["writer"] for v in t["variants"]] == [{"model": m, "effort": e} for m, e in pipeline.TRIAL_DAILY]
    res = t["result"]
    assert res["kind"] == "close" and sum(x["votes"] for x in res["rows"]) == 3
    assert res["top"] == [{"model": pipeline.TRIAL_DAILY[2][0], "effort": pipeline.TRIAL_DAILY[2][1]}]
    assert res["chosen"] is None
    client.put(f"{API}/admin/market-reports/config", json={"writers": {"close": {"model": "claude-opus-5-5",
                                                                                  "effort": "high"}}})
    assert other_client.get(f"{API}/market/reports/{rid}/trial").json()["result"]["chosen"] == \
        {"model": "claude-opus-5-5", "effort": "high"}
    late = other_client.put(f"{API}/market/reports/{rid}/vote", json={"preferred": "A"})
    assert late.status_code == 409 and late.json()["error"]["code"] == "trial_revealed"


def test_the_admin_vote_is_closed_after_the_reveal_too(everyone, app, client, other_client, monkeypatch):
    """Members see the votes and the result after the reveal: the admin endpoint takes no new or changed pick either
    (the note of the same pick may still be written)."""
    from tests.api.m5 import login

    monkeypatch.setattr(get_settings(), "admin_emails", ["demo@forliosa.local", "third@forliosa.local"])
    rid = make_trial()
    third = login(app, "third@forliosa.local", "第三人")  # an admin who has not voted
    assert other_client.put(f"{API}/market/reports/{rid}/vote", json={"preferred": "C"}).status_code == 200
    assert client.put(f"{API}/admin/market-reports/{rid}/vote", json={"preferred": "B", "note": ""}).status_code == 200
    assert client.post(f"{API}/admin/market-reports/trial/reveal", json={"force": True}).status_code == 200
    before = other_client.get(f"{API}/market/reports/{rid}/trial").json()
    assert before["votes"] == {"A": 0, "B": 1, "C": 1}
    for c, body in ((client, {"preferred": "A", "note": ""}), (third, {"preferred": "A", "note": ""})):
        r = c.put(f"{API}/admin/market-reports/{rid}/vote", json=body)
        assert r.status_code == 409 and r.json()["error"]["code"] == "trial_revealed"
    r = client.put(f"{API}/admin/market-reports/{rid}/vote", json={"preferred": "B", "note": "標題好讀"})
    assert r.status_code == 200 and r.json()["note"] == "標題好讀"
    after = other_client.get(f"{API}/market/reports/{rid}/trial").json()
    assert after["votes"] == before["votes"] and after["result"] == before["result"]
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(MarketReportVote)) == 2


def test_admin_page_switches_the_audience(on, client, other_client, monkeypatch):
    admin_on(monkeypatch)
    rid = make_trial()
    assert other_client.get(f"{API}/market/reports/{rid}/trial").status_code == 404
    r = client.put(f"{API}/admin/market-reports/config", json={"trial_audience": "all"})
    assert r.status_code == 200 and r.json()["trial_audience"] == "all" and r.json()["trial_audience_source"] == "admin"
    assert r.json()["notice"].startswith("盲測開給所有登入的人")
    assert other_client.get(f"{API}/market/reports/{rid}/trial").status_code == 200
    assert client.put(f"{API}/admin/market-reports/config", json={"trial_audience": "everyone"}).status_code == 422
    r = client.put(f"{API}/admin/market-reports/config", json={"trial_audience": None})  # back to the env value
    assert r.json()["trial_audience"] == "admins" and r.json()["trial_audience_source"] == "default"
    assert other_client.get(f"{API}/market/reports/{rid}").status_code == 404


def test_only_blind_test_editions_open_up(everyone, other_client):
    """A trial-mode edition after the blind test (admin-only, not a blind-test one) stays hidden."""
    with session_factory()() as db:
        ed = pipeline.edition_on("close", MON)
        r = pipeline.make_report(db, ed, now_utc(), visibility="admin", trial=False)
        v = pipeline.new_version(db, r, edition="data", payload={"title": "x", "has_ai": False}, now=now_utc())
        r.current_version_id, r.state, r.first_published_at = v.id, "data", now_utc()
        db.commit()
        rid = r.id
    assert other_client.get(f"{API}/market/reports/{rid}").status_code == 404
    assert other_client.get(f"{API}/market/reports").json()["items"] == []


def test_unread_counts_from_the_first_variant(everyone, other_client):
    rid = make_trial(ready="", running="AB", published=now_utc() - timedelta(hours=1))
    st = other_client.get(f"{API}/market/reports/status").json()
    assert st["available"] and st["unread"] is False  # nothing to vote on yet
    assert other_client.post(f"{API}/market/reports/seen").status_code == 204
    with session_factory()() as db:
        db.get(MarketReport, rid).ai_published_at = now_utc() + timedelta(minutes=1)
        db.commit()
    assert other_client.get(f"{API}/market/reports/status").json()["unread"] is True


def test_view_as_reads_but_never_votes(everyone, other_client):
    rid = make_trial()
    h = {"X-Forliosa-View-As": "dlg_someone"}
    assert other_client.get(f"{API}/market/reports/{rid}/trial", headers=h).status_code == 200
    assert other_client.get(f"{API}/market/reports/{rid}/variants/A", headers=h).status_code == 200
    r = other_client.put(f"{API}/market/reports/{rid}/vote", headers=h, json={"preferred": "A"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "read_only"


def test_deleting_the_account_removes_a_members_vote(everyone, other_client, engine):
    from sqlalchemy.orm import Session

    from tests.api.test_account import CONFIRM

    rid = make_trial()
    assert other_client.put(f"{API}/market/reports/{rid}/vote", json={"preferred": "A"}).status_code == 200
    assert other_client.request("DELETE", f"{API}/me", json=CONFIRM).status_code == 204
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(MarketReportVote)) == 0


# -- pushes ------------------------------------------------------------------------------------------------------------
def _channels(client):
    """Two groups with a Discord channel: 「開了」 has the close switch on, 「沒開」 leaves it off (the default)."""
    fake = PushFake().install()
    on_g, off_g = make_group(client, "開了"), make_group(client, "沒開")
    for g in (on_g, off_g):
        assert client.put(f"{API}/groups/{g['id']}/channels/discord", json={"webhook_url": WEBHOOK}).status_code == 200
    r = client.patch(f"{API}/groups/{on_g['id']}/channels/discord", json={"notify_close": True})
    assert r.json()["discord"]["notify_close"] is True
    return fake, on_g, off_g


def _queued() -> list[NotificationOutbox]:
    with session_factory()() as db:
        rows = list(db.scalars(select(NotificationOutbox).where(NotificationOutbox.kind == "mreport")))
        for r in rows:
            db.expunge(r)
        return rows


def test_trial_push_once_per_edition_to_channels_with_the_switch_on(everyone, client, market):
    fake, on_g, off_g = _channels(client)
    ch = client.get(f"{API}/groups/{on_g['id']}/channels").json()
    assert ch["market_reports_trial"] is True and ch["market_reports_available"] is False  # the switches show
    assert client.get(f"{API}/groups/{off_g['id']}/channels").json()["discord"]["notify_close"] is False
    rid = make_trial(ready="AB", running="C")
    ed = pipeline.edition_on("close", MON)
    deps = SimpleNamespace(s=get_settings())
    with session_factory()() as db:
        report = db.get(MarketReport, rid)
        res = pipeline.TickResult()
        pipeline.maybe_push_trial(db, report, ed, ed.push_at - timedelta(minutes=1), deps, res)
        pipeline.maybe_push_trial(db, report, ed, ed.push_at, deps, res)  # C is still being written: wait
        assert report.pushed_at is None and _queued() == []
        pipeline.maybe_push_trial(db, report, ed, ed.push_fallback_at, deps, res)  # fallback time: two are enough
        assert report.pushed_at is not None and report.push_edition == "trial"
        assert push.enqueue(db, report, ed.push_fallback_at) == 0  # once per edition and channel
    [row] = _queued()
    assert row.group_id == on_g["id"] and row.dedupe_key == f"mreport:{rid}:{on_g['id']}:discord"
    before = len(fake.discord)
    with session_factory()() as db:
        notifications.send_due(db, market, now=ed.push_fallback_at + timedelta(minutes=1))
    assert len(fake.discord) == before + 1
    text = fake.discord[-1].body["content"]
    lines = text.split("\n")
    assert lines[0] == "【盤後重點 11/16（一）】" + push.LINE_AI
    assert lines[1].startswith("加權指數")  # the data edition's rule-made title without its head
    assert lines[2] == "盲測中：三種寫法，看完選一個。"
    assert lines[3] == f"投票：https://forliosa.trade/market/reports/{rid}"
    assert lines[-1] == disclaimer.SHORT and text.count(disclaimer.SHORT) == 1
    assert "只在" not in text and "AI 整理：" not in text  # no variant's text: none of the three is favoured
    assert len(text) <= 1900
    assert _queued()[0].status == "sent"


def test_trial_push_needs_two_readable_variants(everyone, client):
    _channels(client)
    rid = make_trial(ready="A")
    ed = pipeline.edition_on("close", MON)
    with session_factory()() as db:
        report = db.get(MarketReport, rid)
        pipeline.maybe_push_trial(db, report, ed, ed.push_fallback_at, SimpleNamespace(s=get_settings()),
                                  pipeline.TickResult())
        assert report.pushed_at is None
    assert _queued() == []


def test_the_tick_pushes_a_trial_edition_once_and_never_after_the_deadline(everyone, client):
    """``maybe_push`` (what the tick calls) hands a blind-test edition to the trial push: nothing at or after the push
    deadline (the worker was down), once from the push time."""
    _channels(client)
    rid = make_trial()
    ed = pipeline.edition_on("close", MON)
    deps = SimpleNamespace(s=get_settings())
    with session_factory()() as db:
        report = db.get(MarketReport, rid)
        pipeline.maybe_push(db, report, ed, pipeline.push_deadline(ed), deps, rs.config(db), pipeline.TickResult())
        assert report.pushed_at is None
    assert _queued() == []
    with session_factory()() as db:
        report = db.get(MarketReport, rid)
        res = pipeline.TickResult()
        pipeline.maybe_push(db, report, ed, ed.push_at, deps, rs.config(db), res)
        assert report.push_edition == "trial" and report.pushed_at is not None
        pipeline.maybe_push(db, report, ed, ed.push_at + timedelta(minutes=10), deps, rs.config(db), res)
    assert len(_queued()) == 1


def test_no_trial_push_for_admins_or_out_of_trial_mode(on, client, monkeypatch):
    _channels(client)
    rid = make_trial()
    ed = pipeline.edition_on("close", MON)
    with session_factory()() as db:
        report = db.get(MarketReport, rid)
        assert push.enqueue(db, report, ed.push_at) == 0  # audience admins
        cfg = rs.config(db)
        cfg.trial_audience, cfg.mode = "all", "public"
        db.commit()
        assert push.enqueue(db, report, ed.push_at) == 0  # the trial is over
        cfg.mode = "trial"
        db.commit()
        assert push.enqueue(db, report, ed.push_at) == 1
    with session_factory()() as db:
        ch = db.scalars(select(NotificationOutbox)).all()
        assert len(ch) == 1


def test_trial_push_rechecked_when_sent(everyone, client, market):
    fake, _, _ = _channels(client)
    rid = make_trial()
    at = datetime.combine(MON, time(16), TAIPEI)
    with session_factory()() as db:
        assert push.enqueue(db, db.get(MarketReport, rid), at) == 1
        rs.config(db).trial_audience = "admins"  # switched back on the admin page
        db.commit()
        before = len(fake.discord)
        notifications.send_due(db, market, now=at + timedelta(minutes=1))
    assert len(fake.discord) == before
    [row] = _queued()
    assert row.status == "cancelled" and row.last_error == "trial_closed"


def test_trial_text_without_a_link_and_cut_to_the_limit():
    settings = SimpleNamespace(frontend_url=None, is_dev=False, frontend_base="")
    r = SimpleNamespace(id="mrp_1", kind="weekly", edition_date=MON, period_start=MON - timedelta(days=6),
                        period_end=MON - timedelta(days=2), next_start=None, next_end=None)
    t = push.trial_text(r, {"title": "市場週報 11/10–11/14：加權指數週 ▲1.00%", "title_origin": "rules"}, "telegram",
                        settings)
    lines = t.split("\n")
    assert lines[0].startswith("【市場週報 11/10–11/14 回顧】") and lines[1] == "加權指數週 ▲1.00%"
    assert lines[3] == "到 Forliosa 的「市場 → 報告」投票。" and lines[-1] == disclaimer.SHORT
    ai = push.trial_text(r, {"title": "AI 寫的標題", "title_origin": "ai"}, "discord", settings)
    assert "AI 寫的標題" not in ai
    long = push.trial_text(r, {"title": "長" * 3000, "title_origin": "rules"}, "discord", settings)
    assert len(long) <= 1900 and long.endswith(disclaimer.SHORT)
    assert long.split("\n")[1].endswith("…") and push.LINE_TRIAL in long and "投票。" in long  # the vote line stays
