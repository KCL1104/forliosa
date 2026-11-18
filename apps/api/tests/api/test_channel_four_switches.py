"""Four push switches per channel (產品負責人 2026-11-18, option A): 交易動態, 盤前, 盤後, 週報 — the 盤前 side and the
API.

* 盤前 (trading days 07:30) = 盤前重點 ＋「昨日你的群組」 in one message: reports public (also with a ``trial`` mode
  left from the removed blind test), or not (then the group part alone at 07:30); a group that is not boosted gets
  just the market part (or nothing);
  a market push that never comes leaves the group part to go alone at 08:20; nothing on non-trading days.
* Outbox dedupe through the change: a daily report sent the evening before (the old times) is not taken in again; a
  row queued under the old times waits for the next 盤前 and is taken in; a group part taken in without a queued row
  is never queued afterwards.
* API: the four switches out, ``notify_digest`` / ``notify_daily`` from older frontends written as ``notify_weekly`` /
  ``notify_premarket`` (a given new field wins), the old columns never written.

The 週報 side (the group digest on Sunday 18:00) is in ``test_channel_weekly_switch``; the migration in
``tests/test_migrations.py``.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from forliosa import disclaimer
from forliosa.config import get_settings
from forliosa.db import session_factory
from forliosa.models import GroupChannel, GroupDailyReport, MarketReport, NotificationOutbox
from forliosa.reports import pipeline, push
from forliosa.reports import settings as rs
from forliosa.services import digests, notifications
from forliosa.timeutil import TAIPEI, next_tw_trading_day
from tests.api.m5 import API
from tests.api.push_fake import WEBHOOK, PushFake
from tests.api.test_group_daily import _channel, day, evening, family, run  # noqa: F401 - fixtures

PAYLOAD = {"has_ai": True, "calendar": None, "highlights": [
    {"sentences": [{"text": "SPY 美股 11/16 漲 0.50%。", "refs": ["F001"]}]}]}


@pytest.fixture()
def public(app, monkeypatch):
    monkeypatch.setenv("MARKET_REPORTS_ENABLED", "true")
    monkeypatch.setenv("FRONTEND_URL", "https://forliosa.trade")
    get_settings.cache_clear()
    with session_factory()() as db:
        rs.config(db).mode = "public"
        db.commit()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def trial_left(app, monkeypatch):
    """What the removed blind test may have left (2026-11-18): a ``trial`` mode in the config row (a database the
    migration has not reached yet) and MREPORT_TRIAL_AUDIENCE=all on Railway. Both read as reports public."""
    monkeypatch.setenv("MARKET_REPORTS_ENABLED", "true")
    monkeypatch.setenv("MREPORT_TRIAL_AUDIENCE", "all")
    monkeypatch.setenv("FRONTEND_URL", "https://forliosa.trade")
    get_settings.cache_clear()
    with session_factory()() as db:
        rs.config(db).mode = "trial"
        db.commit()
    yield
    get_settings.cache_clear()


def at(d: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(d, time(h, m), TAIPEI)


def premarket(d: date) -> str:
    """A 盤前重點 edition of ``d`` ready to push: a public AI edition."""
    with session_factory()() as db:
        ed = pipeline.edition_on("premarket", d)
        r = pipeline.make_report(db, ed, ed.push_at, visibility="public")
        v = pipeline.new_version(db, r, edition="ai", payload=PAYLOAD, now=ed.push_at)
        r.current_version_id, r.state = v.id, "ai"
        db.commit()
        return r.id


def send(market, now: datetime) -> None:
    with session_factory()() as db:
        notifications.send_due(db, market, now=now)


def rows(kind: str, group_id: str | None = None) -> list[NotificationOutbox]:
    with session_factory()() as db:
        q = select(NotificationOutbox).where(NotificationOutbox.kind == kind)
        if group_id:
            q = q.where(NotificationOutbox.group_id == group_id)
        out = list(db.scalars(q))
        for r in out:
            db.expunge(r)
        return out


def queue(rid: str, now: datetime) -> int:
    with session_factory()() as db:
        return push.enqueue(db, db.get(MarketReport, rid), now)


# -- 盤前: each combination ----------------------------------------------------------------------------------------
def test_reports_off_the_group_part_goes_alone_at_0730(family, market, day):  # noqa: F811
    """Reports switched off: 盤前 still sends 「昨日你的群組」, alone, at 07:30 of the next
    trading day — not the same evening, not before 07:30."""
    fake = _channel(family)
    nxt = next_tw_trading_day(day + timedelta(days=1))
    run(market, evening(day, time(19, 0)))
    n = len(fake.discord)
    send(market, evening(day, time(19, 1)))
    send(market, at(nxt, 7, 29))
    assert len(fake.discord) == n
    send(market, at(nxt, 7, 30))
    assert len(fake.discord) == n + 1
    text = fake.discord[-1].body["content"]
    assert text.startswith("Forliosa 群組「大學同學」日報") and "小明" in text and "盤前重點" not in text
    assert rows("mreport") == [] and [r.status for r in rows("daily")] == ["sent"]


def test_public_one_message_and_not_boosted_gets_the_market_part_only(family, market, day, public):  # noqa: F811
    fake = _channel(family)
    free, a = family["free"], family["a"]
    assert a.put(f"{API}/groups/{free['id']}/channels/discord",
                 json={"webhook_url": WEBHOOK, "notify_premarket": True}).status_code == 200
    run(market, evening(day, time(23, 40)))
    assert rows("daily", free["id"]) == []  # no daily report: the group is not boosted
    nxt = next_tw_trading_day(day + timedelta(days=1))
    rid = premarket(nxt)
    n = len(fake.discord)
    assert queue(rid, at(nxt, 7, 30)) == 2
    send(market, at(nxt, 7, 31))
    texts = [s.body["content"] for s in fake.discord[n:]]
    assert len(texts) == 2 and all(t.startswith(f"【盤前重點 {nxt.month}/{nxt.day}（") for t in texts)
    assert sum(f"昨日你的群組（{day.month}/{day.day}）" in t for t in texts) == 1  # the boosted group's message
    assert all(t.count(disclaimer.SHORT) == 1 for t in texts)
    [daily] = rows("daily", family["g"]["id"])
    assert daily.status == "sent" and daily.last_error == "merged"
    send(market, at(nxt, 8, 30))
    assert len(fake.discord) == n + 2  # the daily report never goes on its own


def test_a_leftover_trial_mode_pushes_the_public_report_with_the_group_part(family, market, day, trial_left):  # noqa: F811
    """No vote message any more: with a ``trial`` mode left in the row the 盤前 push is the normal public one (title
    line, highlights, link) with 「昨日你的群組」 taken in — held at 07:30 for it, sent once."""
    fake = _channel(family)
    run(market, evening(day, time(23, 40)))
    nxt = next_tw_trading_day(day + timedelta(days=1))
    [daily] = rows("daily")
    assert daily.not_before == at(nxt, 7, 30)
    with session_factory()() as db:
        assert push.market_coming(db, "premarket", nxt)  # not made yet: reports are public
    send(market, at(nxt, 7, 30))  # the market push is not queued yet: the group part is held for it
    assert rows("daily")[0].not_before == at(nxt, 8, 20)
    rid = premarket(nxt)
    n = len(fake.discord)
    assert queue(rid, at(nxt, 7, 30)) == 1
    send(market, at(nxt, 7, 31))
    assert len(fake.discord) == n + 1
    text = fake.discord[-1].body["content"]
    lines = text.split("\n")
    assert lines[0] == f"【盤前重點 {nxt.month}/{nxt.day}（{'一二三四五六日'[nxt.weekday()]}）】" + push.LINE_AI
    assert lines[1] == "・SPY 美股 11/16 漲 0.50%。"
    assert f"昨日你的群組（{day.month}/{day.day}）" in lines and any("小明" in x for x in lines)
    assert f"全文與圖表：https://forliosa.trade/market/reports/{rid}" in lines
    assert "盲測" not in text and "投票" not in text and lines[-1].endswith(disclaimer.SHORT)
    [daily] = rows("daily")
    assert daily.status == "sent" and daily.last_error == "merged"
    send(market, at(nxt, 8, 30))
    assert len(fake.discord) == n + 1


def test_a_market_push_that_never_comes_leaves_the_group_part_alone_at_0820(family, market, day, public):  # noqa: F811
    fake = _channel(family)
    run(market, evening(day, time(23, 40)))
    nxt = next_tw_trading_day(day + timedelta(days=1))
    n = len(fake.discord)
    send(market, at(nxt, 8, 19))  # no premarket edition was pushed (skipped, the worker down …)
    assert len(fake.discord) == n
    send(market, at(nxt, 8, 20))
    assert len(fake.discord) == n + 1 and fake.discord[-1].body["content"].startswith("Forliosa 群組「大學同學」日報")


def test_premarket_off_sends_neither_part(family, market, day, public):  # noqa: F811
    fake = _channel(family, daily=False)
    run(market, evening(day, time(23, 40)))
    nxt = next_tw_trading_day(day + timedelta(days=1))
    n = len(fake.discord)
    assert rows("daily") == [] and queue(premarket(nxt), at(nxt, 7, 30)) == 0
    send(market, at(nxt, 9))
    assert len(fake.discord) == n


def test_no_premarket_on_non_trading_days():
    fri, sat = date(2026, 11, 20), date(2026, 11, 21)
    assert pipeline.edition_on("premarket", sat) is None and pipeline.edition_on("close", sat) is None
    assert push.daily_slot(fri) == at(date(2026, 11, 23), 7, 30)  # Friday's report: Monday's 盤前
    assert pipeline.edition_on("weekly", date(2026, 11, 22)) is not None  # 週報 every Sunday


# -- dedupe through the change ------------------------------------------------------------------------------------
def test_a_daily_report_sent_the_evening_before_is_not_taken_in_again(family, market, day, public):  # noqa: F811
    """Pushed on its own the evening before the deploy (old times): the next 盤前 has just the market part."""
    fake = _channel(family)
    run(market, evening(day, time(19, 0)))
    with session_factory()() as db:
        row = db.scalar(select(NotificationOutbox).where(NotificationOutbox.kind == "daily"))
        row.status, row.sent_at, row.attempts = "sent", evening(day, time(19, 0)), 1  # the old code sent it
        db.commit()
    nxt = next_tw_trading_day(day + timedelta(days=1))
    n = len(fake.discord)
    queue(premarket(nxt), at(nxt, 7, 30))
    send(market, at(nxt, 7, 31))
    send(market, at(nxt, 8, 30))
    assert len(fake.discord) == n + 1 and "昨日你的群組" not in fake.discord[-1].body["content"]


def test_a_row_queued_under_the_old_times_waits_and_is_taken_in(family, market, day, public):  # noqa: F811
    """Queued before the deploy to go the same evening: re-timed when it comes due, then taken in by 盤前 — once."""
    fake = _channel(family)
    run(market, evening(day, time(19, 0)))
    nxt = next_tw_trading_day(day + timedelta(days=1))
    with session_factory()() as db:
        row = db.scalar(select(NotificationOutbox).where(NotificationOutbox.kind == "daily"))
        row.not_before = evening(day, time(19, 0))  # the old 「at once」
        db.commit()
    n = len(fake.discord)
    send(market, evening(day, time(19, 1)))
    assert len(fake.discord) == n
    [row] = rows("daily")
    assert row.status == "pending" and row.not_before == at(nxt, 7, 30)  # whether to hold is asked at 07:30
    queue(premarket(nxt), at(nxt, 7, 30))
    send(market, at(nxt, 7, 31))
    send(market, at(nxt, 8, 21))
    assert len(fake.discord) == n + 1 and "昨日你的群組" in fake.discord[-1].body["content"]
    assert rows("daily")[0].last_error == "merged"


def test_taken_in_without_a_queued_row_is_never_queued_afterwards(family, market, day, public):  # noqa: F811
    """盤前 turned on after the report was finished (no row was queued): the premarket push takes the report in and
    records it, so queueing the report again finds it sent."""
    fake = _channel(family, daily=False)
    run(market, evening(day, time(23, 40)))
    assert rows("daily") == []
    g, a = family["g"], family["a"]
    a.patch(f"{API}/groups/{g['id']}/channels/discord", json={"notify_premarket": True})
    nxt = next_tw_trading_day(day + timedelta(days=1))
    n = len(fake.discord)
    queue(premarket(nxt), at(nxt, 7, 30))
    send(market, at(nxt, 7, 31))
    assert len(fake.discord) == n + 1 and "昨日你的群組" in fake.discord[-1].body["content"]
    [row] = rows("daily")
    assert row.status == "sent" and row.last_error == "merged" and row.channel_kind == "discord"
    with session_factory()() as db:
        report = db.scalar(select(GroupDailyReport).where(GroupDailyReport.group_id == g["id"]))
        assert notifications.enqueue_daily(db, report, at(nxt, 7, 40)) == 0
    send(market, at(nxt, 9))
    assert len(fake.discord) == n + 1


# -- API: four switches, old fields accepted ------------------------------------------------------------------------
def channel_row(gid: str) -> GroupChannel:
    with session_factory()() as db:
        row = db.get(GroupChannel, (gid, "discord"))
        db.expunge(row)
        return row


def test_api_four_switches_and_old_fields_from_older_frontends(family):  # noqa: F811
    PushFake().install()
    g, a = family["g"], family["a"]
    url = f"{API}/groups/{g['id']}/channels/discord"
    # an older frontend's set-up body: 週報 off, 日報 on
    r = a.put(url, json={"webhook_url": WEBHOOK, "notify_trades": True, "notify_digest": False, "notify_daily": True})
    assert r.status_code == 200, r.text
    d = r.json()["discord"]
    assert (d["notify_trades"], d["notify_premarket"], d["notify_close"], d["notify_weekly"]) == (True, True, False,
                                                                                                  False)
    assert d["notify_digest"] is False and d["notify_daily"] is True  # copies of 週報 / 盤前 for older frontends
    d = a.patch(url, json={"notify_digest": True}).json()["discord"]
    assert d["notify_weekly"] is True
    d = a.patch(url, json={"notify_daily": False}).json()["discord"]
    assert d["notify_premarket"] is False
    d = a.patch(url, json={"notify_daily": True, "notify_premarket": False}).json()["discord"]
    assert d["notify_premarket"] is False  # the new field wins
    d = a.patch(url, json={"notify_weekly": False, "notify_digest": True}).json()["discord"]
    assert d["notify_weekly"] is False
    d = a.patch(url, json={"notify_premarket": True, "notify_close": True, "notify_weekly": True}).json()["discord"]
    assert (d["notify_premarket"], d["notify_close"], d["notify_weekly"]) == (True, True, True)
    assert a.patch(url, json={"notify_bogus": True}).status_code == 422
    row = channel_row(g["id"])
    # the old columns were only lowered (old AND new) — 週報 was off for a while — never turned on again
    assert row.notify_daily is False and row.notify_digest is False
    # replacing the webhook keeps the switches that are not given
    d = a.put(url, json={"webhook_url": WEBHOOK}).json()["discord"]
    assert (d["notify_premarket"], d["notify_close"], d["notify_weekly"]) == (True, True, True)


def test_an_older_frontend_replacing_the_webhook_keeps_the_switches(family):  # noqa: F811
    """The old form sends 週報 / 日報 with its own defaults (on / off), not the channel's: replacing the webhook of a
    channel that is set up ignores them; a new destination (set up after it was removed) takes them."""
    PushFake().install()
    g, a = family["g"], family["a"]
    url = f"{API}/groups/{g['id']}/channels/discord"
    old_form = {"webhook_url": WEBHOOK, "notify_trades": True, "notify_digest": True, "notify_daily": False}
    r = a.put(url, json={"webhook_url": WEBHOOK, "notify_premarket": True, "notify_weekly": False})
    assert r.status_code == 200
    d = a.put(url, json=old_form).json()["discord"]
    assert (d["notify_premarket"], d["notify_weekly"]) == (True, False)  # not 盤前 off, 週報 on
    assert a.delete(url).status_code == 204
    d = a.put(url, json={**old_form, "notify_daily": True}).json()["discord"]
    assert (d["notify_premarket"], d["notify_close"], d["notify_weekly"]) == (True, False, True)


def test_switches_turned_off_lower_the_old_columns(family):  # noqa: F811
    """A rollback to code that reads ``notify_digest`` / ``notify_daily`` sends no more than today's switches: a new
    channel starts with the old defaults (週報 on, 日報 off); turning 週報 / 盤前 off lowers them, on never raises."""
    PushFake().install()
    g, a = family["g"], family["a"]
    url = f"{API}/groups/{g['id']}/channels/discord"
    a.put(url, json={"webhook_url": WEBHOOK, "notify_premarket": True})
    row = channel_row(g["id"])
    assert (row.notify_digest, row.notify_daily) == (True, False)
    a.patch(url, json={"notify_weekly": False})
    assert (channel_row(g["id"]).notify_digest, channel_row(g["id"]).notify_daily) == (False, False)
    a.patch(url, json={"notify_weekly": True})
    assert channel_row(g["id"]).notify_digest is False  # never turned on again
    with session_factory()() as db:  # a channel from before the change, 日報 on; then 盤前 turned off
        ch = db.get(GroupChannel, (g["id"], "discord"))
        ch.notify_daily = ch.notify_premarket = True
        db.commit()
    a.patch(url, json={"notify_premarket": False})
    assert channel_row(g["id"]).notify_daily is False


def test_api_channels_say_whether_the_market_part_comes(family, public):  # noqa: F811
    a, g = family["a"], family["g"]
    out = a.get(f"{API}/groups/{g['id']}/channels").json()
    assert out["market_reports_available"] is True and "market_reports_trial" not in out  # no blind-test line
    assert set(out["discord"]) >= {"notify_trades", "notify_premarket", "notify_close", "notify_weekly"}


def test_the_digest_comes_out_on_sunday_1800():
    fri = date(2026, 11, 20)
    assert digests.publish_at(fri) == at(date(2026, 11, 22), 18)
    assert digests.published_through(at(date(2026, 11, 22), 17, 59)) == date(2026, 11, 13)
    assert digests.published_through(at(date(2026, 11, 22), 18)) == fri
    assert digests.published_through(at(date(2026, 11, 21), 20, 30)) == date(2026, 11, 13)  # Saturday night: not yet
    assert digests.published_through(at(date(2026, 11, 25), 9)) == fri
