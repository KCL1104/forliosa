"""When the group part of 盤前 goes (產品負責人 2026-11-18, option A), judged by the one edition that may take it in:

* A blind test open to everyone whose blind-test editions are used up (the 6th trading day, or an admin-only edition
  that is not a blind-test one): no market push comes, so 「昨日你的群組」 goes alone at 07:30 — not 08:20 — and the
  頻道 tab stops saying 「盲測期間每份報告推一則投票連結」.
* Reports public, the 盤前重點 push already sent: a daily report written after it goes at once, not at 08:20.
* Friday's report waits over the weekend for Monday 07:30 (``send_due`` from Friday evening to Monday).
* Discord and Telegram both on: each channel's push takes in its own row (``daily:<id>:<kind>``); a channel whose
  market push keeps failing gets the group part alone at 08:20, and the market push's retry no longer carries it.
* Setting a channel up again does not cancel the waiting group part (it still goes once).
* The blind-test message with a long group section stays within the channel's limit: the vote link first, a cut line
  ends in 「…」, the disclaimer last.

``day`` here is a Friday session followed by a Monday session (found from the real calendar, so the weekend is always
in between).
"""

from __future__ import annotations

from collections import deque
from datetime import date, time, timedelta

import pytest
from sqlalchemy import select

from forliosa import disclaimer
from forliosa.config import get_settings
from forliosa.db import session_factory
from forliosa.models import GroupChannel, GroupDailyReport, MarketReport, NotificationOutbox
from forliosa.reports import pipeline, push
from forliosa.reports import settings as rs
from forliosa.services import notifications
from forliosa.timeutil import next_tw_trading_day, now_utc
from tests.api.m5 import API, trading_day
from tests.api.push_fake import BOT_TOKEN, BOT_USERNAME, WEBHOOK
from tests.api.test_channel_four_switches import PAYLOAD, at, premarket, queue, rows, send
from tests.api.test_group_daily import _channel, evening, family, run  # noqa: F401 - fixtures


@pytest.fixture()
def day() -> date:
    """The latest Friday session (at least 3 days back) whose next session is the Monday after it."""
    for n in range(3, 60):
        d = trading_day(n)
        if d.weekday() == 4 and next_tw_trading_day(d + timedelta(days=1)) == d + timedelta(days=3):
            return d
    raise AssertionError("no Friday followed by a Monday session in the last two months")


def _env(monkeypatch, mode: str, **extra: str) -> None:
    monkeypatch.setenv("MARKET_REPORTS_ENABLED", "true")
    monkeypatch.setenv("FRONTEND_URL", "https://forliosa.trade")
    for k, v in extra.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    with session_factory()() as db:
        rs.config(db).mode = mode
        db.commit()


@pytest.fixture()
def public(app, monkeypatch):
    _env(monkeypatch, "public", TELEGRAM_BOT_TOKEN=BOT_TOKEN, TELEGRAM_BOT_USERNAME=BOT_USERNAME)
    yield
    get_settings.cache_clear()


@pytest.fixture()
def trial_all(app, monkeypatch):
    _env(monkeypatch, "trial", MREPORT_TRIAL_AUDIENCE="all", AI_MREPORT_TRIAL_DAYS="1")
    yield
    get_settings.cache_clear()


def monday(day: date) -> date:
    return next_tw_trading_day(day + timedelta(days=1))


# -- the blind test open to everyone, its editions used up ------------------------------------------------------------
def started_long_ago(day: date) -> None:
    """The blind test started a month before (its 1 trading day of editions is long over)."""
    with session_factory()() as db:
        rs.config(db).trial_started_on = day - timedelta(days=30)
        db.commit()


def test_trial_all_after_the_trial_editions_the_group_part_is_at_0730(family, market, day, trial_all):  # noqa: F811
    """No edition made yet, and it will not be a blind-test one: nothing to wait for at 07:30."""
    fake = _channel(family)
    started_long_ago(day)
    run(market, evening(day, time(19, 0)))
    mon = monday(day)
    with session_factory()() as db:
        cfg = rs.config(db)
        assert not pipeline.is_trial_edition(db, cfg, "premarket", mon, get_settings())
        assert push.trial_pushing(db) and not push.market_coming(db, "premarket", mon)
    n = len(fake.discord)
    send(market, at(mon, 7, 29))
    assert len(fake.discord) == n
    send(market, at(mon, 7, 30))
    assert len(fake.discord) == n + 1 and fake.discord[-1].body["content"].startswith("Forliosa 群組「大學同學」日報")
    [row] = rows("daily")
    assert row.status == "sent" and row.last_error is None


def test_trial_all_an_admin_only_edition_does_not_hold_the_group_part(family, market, day, trial_all):  # noqa: F811
    """The edition was made, but admin-only and not a blind-test one (``may_push`` wants public): no push comes."""
    fake = _channel(family)
    started_long_ago(day)
    run(market, evening(day, time(23, 40)))
    mon = monday(day)
    with session_factory()() as db:
        ed = pipeline.edition_on("premarket", mon)
        r = pipeline.make_report(db, ed, ed.gather_at, visibility="admin", trial=False)
        assert not push.may_push(db, r) and not push.may_push_trial(db, r)
    n = len(fake.discord)
    send(market, at(mon, 7, 30))
    assert len(fake.discord) == n + 1 and "昨日你的群組" not in fake.discord[-1].body["content"]
    assert rows("daily")[0].status == "sent"


def test_trial_all_the_tab_stops_promising_vote_links_when_done(family, day, trial_all):  # noqa: F811
    a, g = family["a"], family["g"]
    url = f"{API}/groups/{g['id']}/channels"
    assert a.get(url).json()["market_reports_trial"] is True  # nothing made yet: blind-test editions still come
    mon = monday(day)
    sunday = day + timedelta(days=2)
    with session_factory()() as db:
        for kind, d in (("premarket", mon), ("close", mon), ("weekly", sunday)):
            ed = pipeline.edition_on(kind, d)
            r = pipeline.make_report(db, ed, ed.gather_at, visibility="admin", trial=True)
            r.closed_at = ed.close_at
        db.commit()
    out = a.get(url).json()
    assert out["market_reports_trial"] is False and out["market_reports_available"] is False


# -- reports public ----------------------------------------------------------------------------------------------------
def test_public_a_report_written_after_the_premarket_push_goes_at_once(family, market, day, public):  # noqa: F811
    fake = _channel(family)
    run(market, evening(day, time(23, 40)))
    mon = monday(day)
    with session_factory()() as db:  # written late: still being written while the 盤前重點 push goes
        daily = db.scalar(select(GroupDailyReport).where(GroupDailyReport.group_id == family["g"]["id"]))
        daily.status = "pending"
        db.execute(NotificationOutbox.__table__.delete().where(NotificationOutbox.kind == "daily"))
        db.commit()
    rid = premarket(mon)
    with session_factory()() as db:
        db.get(MarketReport, rid).pushed_at = at(mon, 7, 30)
        db.commit()
    n = len(fake.discord)
    queue(rid, at(mon, 7, 30))
    send(market, at(mon, 7, 31))
    assert len(fake.discord) == n + 1 and "昨日你的群組" not in fake.discord[-1].body["content"]
    with session_factory()() as db:
        daily = db.scalar(select(GroupDailyReport).where(GroupDailyReport.group_id == family["g"]["id"]))
        daily.status, daily.finished_at = "ready", at(mon, 7, 40)
        db.commit()
        assert notifications.enqueue_daily(db, daily, at(mon, 7, 40)) == 1
    send(market, at(mon, 7, 40))  # the push already went: nothing to wait for
    assert len(fake.discord) == n + 2 and fake.discord[-1].body["content"].startswith("Forliosa 群組「大學同學」日報")


def test_friday_report_waits_over_the_weekend_for_monday_0730(family, market, day):  # noqa: F811
    """Reports off: Friday's report is queued Friday evening and goes alone on Monday 07:30 — nothing on the weekend
    (no 盤前 on non-trading days)."""
    fake = _channel(family)
    run(market, evening(day, time(19, 0)))
    mon = monday(day)
    [row] = rows("daily")
    assert row.not_before == at(mon, 7, 30)
    n = len(fake.discord)
    for t in (evening(day, time(19, 1)), at(day + timedelta(days=1), 7, 30), at(day + timedelta(days=2), 7, 30),
              at(day + timedelta(days=2), 18), at(mon, 7, 29)):
        send(market, t)
    assert len(fake.discord) == n
    assert pipeline.edition_on("premarket", day + timedelta(days=1)) is None
    send(market, at(mon, 7, 30))
    assert len(fake.discord) == n + 1
    text = fake.discord[-1].body["content"]
    assert text.startswith("Forliosa 群組「大學同學」日報") and "當日報酬" in text  # sent after the day


# -- Discord and Telegram ----------------------------------------------------------------------------------------------
def add_telegram(group_id: str) -> None:
    with session_factory()() as db:
        db.add(GroupChannel(group_id=group_id, kind="telegram", status="active", telegram_chat_id=-1001,
                            chat_title="大學同學群", notify_trades=True, notify_premarket=True, notify_close=False,
                            notify_weekly=True, configured_at=now_utc()))
        db.commit()


def test_discord_and_telegram_each_take_in_their_own_row(family, market, day, public):  # noqa: F811
    fake = _channel(family)
    g = family["g"]
    add_telegram(g["id"])
    run(market, evening(day, time(23, 40)))
    assert sorted(r.channel_kind for r in rows("daily")) == ["discord", "telegram"]
    mon = monday(day)
    rid = premarket(mon)
    with session_factory()() as db:
        db.get(MarketReport, rid).pushed_at = at(mon, 7, 30)
        db.commit()
    assert queue(rid, at(mon, 7, 30)) == 2
    fake.telegram_script["sendMessage"] = deque([(500, {"ok": False})] * 2)  # Telegram down for a while
    send(market, at(mon, 7, 31))
    assert "昨日你的群組" in fake.discord[-1].body["content"]
    by_kind = {r.channel_kind: r for r in rows("daily")}
    assert (by_kind["discord"].status, by_kind["discord"].last_error) == ("sent", "merged")
    assert by_kind["telegram"].status == "pending"  # only the channel whose push went is marked
    send(market, at(mon, 8, 19))  # the Telegram market push is still waiting: the group part waits for it
    assert len(fake.telegram()) == 2  # both attempts of the market push failed
    assert {r.channel_kind: r.status for r in rows("daily")}["telegram"] == "pending"
    send(market, at(mon, 8, 20))  # held no longer: alone
    tg = fake.telegram()
    assert tg[-1].body["text"].startswith("Forliosa 群組「大學同學」日報")
    assert {r.channel_kind: r.status for r in rows("daily")}["telegram"] == "sent"
    send(market, at(mon, 9))  # the market push's retry: without the group part, which already went
    last = fake.telegram()[-1].body["text"]
    assert last.startswith(f"【盤前重點 {mon.month}/{mon.day}（") and "昨日你的群組" not in last
    assert sum("昨日你的群組" in s.body["content"] for s in fake.discord) == 1
    assert sum("昨日你的群組" in s.body["text"] or "日報" in s.body["text"].split("\n")[0]
               for s in fake.telegram()[2:]) == 1  # the group part reached Telegram once


def test_setting_the_channel_up_again_keeps_the_waiting_group_part(family, market, day):  # noqa: F811
    """Reports off: the webhook set again (or the channel disabled and set up again) while the report waits for
    Monday 07:30 — it still goes, once."""
    fake = _channel(family)
    g, a = family["g"], family["a"]
    run(market, evening(day, time(19, 0)))
    assert a.put(f"{API}/groups/{g['id']}/channels/discord", json={"webhook_url": WEBHOOK}).status_code == 200
    [row] = rows("daily")
    assert row.status == "pending"
    mon = monday(day)
    n = len(fake.discord)
    send(market, at(mon, 7, 30))
    send(market, at(mon, 9))
    assert len(fake.discord) == n + 1 and fake.discord[-1].body["content"].startswith("Forliosa 群組「大學同學」日報")


# -- the blind-test message within the limit ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["discord", "telegram"])
def test_trial_text_with_a_long_group_section_stays_within_the_limit(kind):
    report = MarketReport(id="mrp_x", kind="premarket", edition_date=date(2026, 11, 23),
                          period_start=date(2026, 11, 23), period_end=date(2026, 11, 23))
    settings = get_settings()
    long_line = "成員報酬：" + "小明 +1.23%、" * 600
    url = push.link(report.id, settings)
    for group in (["昨日你的群組（11/20）", long_line, "第二行"], ["昨日你的群組（11/20）", long_line]):
        msg = push.trial_text(report, PAYLOAD, kind, settings, group)
        lines = msg.split("\n")
        assert len(msg) <= push.LIMITS[kind]
        assert lines[-1] == disclaimer.SHORT and msg.count(disclaimer.SHORT) == 1
        assert push.LINE_TRIAL in lines and (f"投票：{url}" in lines if url else lines[2].startswith("到 Forliosa"))
        assert lines[-2].endswith("…") and "第二行" not in msg  # the group section cut, the cut line marked
    msg = push.text(report, PAYLOAD, kind, settings, ["昨日你的群組（11/20）", long_line])
    assert len(msg) <= push.LIMITS[kind] and msg.endswith(disclaimer.SHORT)
