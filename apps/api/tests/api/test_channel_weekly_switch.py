"""The 週報 switch (產品負責人 2026-11-18, option A): 市場週報 ＋ the group's weekly digest in one message, Sunday
18:00.

* Reports off or paused: the digest goes alone on Sunday 18:00 — not on Saturday night.
* A ``trial`` mode left in the row by the removed blind test (2026-11-18) reads as public: the normal 市場週報 push
  takes the digest in; an admin-only edition does not hold it (alone at 18:00).
* Setting the channel up again (or disabled and set up again) keeps the waiting digest: it goes once; a row cancelled
  that way by the code before the change is not taken in.
* Through the change: a digest row queued for Saturday under the old times waits for Sunday (alone at 18:00, or taken
  in by the 18:00 push); a digest already pushed on Saturday is not taken in again.
* The group page shows a week's digest from Sunday 18:00, like the channels (and comments on it wait too).

The 盤前 side and the API are in ``test_channel_four_switches``; the public merge in
``test_market_report_digest_push``.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from forliosa import disclaimer
from forliosa.config import get_settings
from forliosa.db import session_factory
from forliosa.ids import new_id
from forliosa.models import Group, GroupChannel, GroupDigest, MarketReport, NotificationOutbox
from forliosa.reports import pipeline, push
from forliosa.reports import settings as rs
from forliosa.services import digests, notifications
from forliosa.timeutil import TAIPEI, now_utc
from tests.api.m5 import API, me_id
from tests.api.push_fake import WEBHOOK, PushFake
from tests.api.test_m5_digest import FakeClaude, create, family, run_ai  # noqa: F401 - fixtures

PAYLOAD = {"has_ai": True, "calendar": {"groups": []}, "highlights": [
    {"sentences": [{"text": "加權指數週 ▲1.23%。", "refs": ["F001"]}]}]}


def _env(monkeypatch, mode: str) -> None:
    monkeypatch.setenv("MARKET_REPORTS_ENABLED", "true")
    monkeypatch.setenv("FRONTEND_URL", "https://forliosa.trade")
    get_settings.cache_clear()
    with session_factory()() as db:
        rs.config(db).mode = mode
        db.commit()


@pytest.fixture()
def public(app, monkeypatch):
    _env(monkeypatch, "public")
    yield
    get_settings.cache_clear()


@pytest.fixture()
def trial_left(app, monkeypatch):
    """A ``trial`` mode left in the row (a database the migration has not reached) and MREPORT_TRIAL_AUDIENCE=all."""
    monkeypatch.setenv("MREPORT_TRIAL_AUDIENCE", "all")
    _env(monkeypatch, "trial")
    yield
    get_settings.cache_clear()


def at(d: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(d, time(h, m), TAIPEI)


def setup(family, market) -> tuple[PushFake, date]:  # noqa: F811
    """A Discord channel (週報 on by default) and the week's digest, ready on Saturday evening."""
    g, a, sat = family["g"], family["a"], family["sat"]
    fake = PushFake().install()
    assert a.put(f"{API}/groups/{g['id']}/channels/discord", json={"webhook_url": WEBHOOK}).status_code == 200
    assert len(create(market, sat)) == 1
    run_ai(FakeClaude(), sat)
    return fake, sat + timedelta(days=1)


def weekly(sunday: date) -> str:
    with session_factory()() as db:
        ed = pipeline.edition_on("weekly", sunday)
        r = pipeline.make_report(db, ed, ed.push_at, visibility="public")
        v = pipeline.new_version(db, r, edition="ai", payload=PAYLOAD, now=ed.push_at)
        r.current_version_id, r.state = v.id, "ai"
        db.commit()
        return r.id


def send(market, now: datetime) -> None:
    with session_factory()() as db:
        notifications.send_due(db, market, now=now)


def digest_rows() -> list[NotificationOutbox]:
    with session_factory()() as db:
        out = list(db.scalars(select(NotificationOutbox).where(NotificationOutbox.kind == "digest")))
        for r in out:
            db.expunge(r)
        return out


def queue(rid: str, now: datetime) -> int:
    with session_factory()() as db:
        return push.enqueue(db, db.get(MarketReport, rid), now)


def test_reports_off_the_digest_goes_alone_on_sunday_1800(family, market):  # noqa: F811
    fake, sunday = setup(family, market)
    [row] = digest_rows()
    assert row.not_before == at(sunday, 18)
    n = len(fake.discord)
    send(market, at(sunday - timedelta(days=1), 21))  # Saturday night: not any more
    send(market, at(sunday, 17, 59))
    assert len(fake.discord) == n
    send(market, at(sunday, 18))
    assert len(fake.discord) == n + 1
    text = fake.discord[-1].body["content"]
    assert text.startswith("Forliosa 群組「家族投資」週報") and "小明" in text and "市場週報" not in text


def test_a_leftover_trial_mode_takes_the_digest_into_the_public_weekly_push(family, market, trial_left):  # noqa: F811
    """No vote message any more: the 市場週報 push is the normal public one with 「你的群組上週」 taken in."""
    fake, sunday = setup(family, market)
    [row] = digest_rows()
    assert row.not_before == at(sunday, 18)
    rid = weekly(sunday)
    n = len(fake.discord)
    send(market, at(sunday, 18))  # the edition is not pushed yet: the digest is held for it
    assert len(fake.discord) == n and digest_rows()[0].not_before == at(sunday, 21, 30)
    assert queue(rid, at(sunday, 18)) == 1
    send(market, at(sunday, 18, 1))
    assert len(fake.discord) == n + 1
    text = fake.discord[-1].body["content"]
    lines = text.split("\n")
    assert lines[0].startswith("【市場週報 ") and lines[1] == "・加權指數週 ▲1.23%。"
    assert f"全文與圖表：https://forliosa.trade/market/reports/{rid}" in lines
    assert any(x.startswith("你的群組上週（") for x in lines) and "小明" in text
    assert "盲測" not in text and "投票" not in text
    assert text.count(disclaimer.SHORT) == 1 and text.endswith(disclaimer.SHORT)
    [row] = digest_rows()
    assert row.status == "sent" and row.last_error == "merged"
    send(market, at(sunday, 21, 31))
    assert len(fake.discord) == n + 1


def test_a_row_queued_for_saturday_waits_for_sunday(family, market):  # noqa: F811
    """Queued before the deploy for Saturday 20:05 (the old times): re-timed to Sunday 18:00 when it comes due."""
    fake, sunday = setup(family, market)
    with session_factory()() as db:
        row = db.scalar(select(NotificationOutbox).where(NotificationOutbox.kind == "digest"))
        row.not_before = at(sunday - timedelta(days=1), 20, 5)
        db.commit()
    n = len(fake.discord)
    send(market, at(sunday - timedelta(days=1), 20, 6))
    assert len(fake.discord) == n and digest_rows()[0].not_before == at(sunday, 18)
    send(market, at(sunday, 18))
    send(market, at(sunday, 21, 31))
    assert len(fake.discord) == n + 1


def test_a_row_queued_for_saturday_is_taken_in_by_the_weekly_push(family, market, public):  # noqa: F811
    fake, sunday = setup(family, market)
    with session_factory()() as db:
        row = db.scalar(select(NotificationOutbox).where(NotificationOutbox.kind == "digest"))
        row.not_before = at(sunday - timedelta(days=1), 20, 5)
        db.commit()
    n = len(fake.discord)
    send(market, at(sunday - timedelta(days=1), 20, 6))
    assert len(fake.discord) == n and digest_rows()[0].not_before == at(sunday, 18)
    queue(weekly(sunday), at(sunday, 18))
    send(market, at(sunday, 18, 1))
    send(market, at(sunday, 21, 31))
    assert len(fake.discord) == n + 1 and "你的群組上週（" in fake.discord[-1].body["content"]
    assert digest_rows()[0].last_error == "merged"


def test_a_digest_pushed_on_saturday_is_not_taken_in_again(family, market, public):  # noqa: F811
    fake, sunday = setup(family, market)
    with session_factory()() as db:
        row = db.scalar(select(NotificationOutbox).where(NotificationOutbox.kind == "digest"))
        row.status, row.sent_at, row.attempts = "sent", at(sunday - timedelta(days=1), 20, 6), 1  # the old code
        db.commit()
    n = len(fake.discord)
    queue(weekly(sunday), at(sunday, 18))
    send(market, at(sunday, 18, 1))
    send(market, at(sunday, 21, 31))
    assert len(fake.discord) == n + 1
    text = fake.discord[-1].body["content"]
    assert text.startswith("【市場週報 ") and "你的群組上週" not in text


def test_the_page_shows_a_digest_from_sunday_1800(family, market):  # noqa: F811
    g, a = family["g"], family["a"]
    create(market, family["sat"])
    sunday = family["sat"] + timedelta(days=1)
    with session_factory()() as db:
        group = db.get(Group, g["id"])
        hidden = digests.digests_page(db, group, me_id(a), 10, None, now=at(sunday, 17, 59))
        shown = digests.digests_page(db, group, me_id(a), 10, None, now=at(sunday, 18))
    assert hidden["items"] == [] and len(shown["items"]) == 1
    # a week whose Sunday 18:00 is still to come: not listed, not open to comments (the real clock)
    friday = digests.published_through() + timedelta(days=7)
    with session_factory()() as db:
        d = GroupDigest(id=new_id("gdg"), group_id=g["id"], week_start=friday - timedelta(days=4), week_end=friday,
                        status="ready", summary="下週的週報", facts={}, sources=[], model="m", created_at=now_utc())
        db.add(d)
        db.commit()
        did = d.id
    items = a.get(f"{API}/groups/{g['id']}/digests").json()["items"]
    assert did not in [i["id"] for i in items] and len(items) == 1
    r = a.post(f"{API}/groups/{g['id']}/comments", json={"target": f"digest:{did}", "body": "讚"})
    assert r.status_code == 404


def test_an_admin_only_weekly_does_not_hold_the_digest(family, market, public):  # noqa: F811
    """This Sunday's 市場週報 was made admin-only (a CLI run): nothing takes the digest in — it goes alone at 18:00,
    not 21:30."""
    fake, sunday = setup(family, market)
    with session_factory()() as db:
        ed = pipeline.edition_on("weekly", sunday)
        pipeline.make_report(db, ed, ed.gather_at, visibility="admin")
        assert not push.market_coming(db, "weekly", sunday)
    n = len(fake.discord)
    send(market, at(sunday, 17, 59))
    assert len(fake.discord) == n
    send(market, at(sunday, 18))
    assert len(fake.discord) == n + 1
    assert fake.discord[-1].body["content"].startswith("Forliosa 群組「家族投資」週報")


def test_the_webhook_set_again_on_saturday_keeps_the_digest_for_sunday(family, market):  # noqa: F811
    """Reports off: the owner sets the webhook again on Saturday night, after the digest was queued — it still goes
    on Sunday 18:00, once."""
    fake, sunday = setup(family, market)
    g, a = family["g"], family["a"]
    assert a.put(f"{API}/groups/{g['id']}/channels/discord", json={"webhook_url": WEBHOOK}).status_code == 200
    assert digest_rows()[0].status == "pending"
    n = len(fake.discord)
    send(market, at(sunday, 18))
    send(market, at(sunday, 21, 31))
    assert len(fake.discord) == n + 1 and "小明" in fake.discord[-1].body["content"]


def test_disabled_and_set_up_again_the_weekly_push_takes_the_digest_in_once(family, market, public):  # noqa: F811
    fake, sunday = setup(family, market)
    g, a = family["g"], family["a"]
    with session_factory()() as db:
        from forliosa.services import channels

        channels.disable(db, db.get(GroupChannel, (g["id"], "discord")), "webhook_invalid")
        db.commit()
    assert digest_rows()[0].status == "pending"  # kept: checked again when it goes
    assert a.put(f"{API}/groups/{g['id']}/channels/discord", json={"webhook_url": WEBHOOK}).status_code == 200
    n = len(fake.discord)
    queue(weekly(sunday), at(sunday, 18))
    send(market, at(sunday, 18, 1))
    send(market, at(sunday, 21, 31))
    assert len(fake.discord) == n + 1 and "你的群組上週（" in fake.discord[-1].body["content"]
    [row] = digest_rows()
    assert row.status == "sent" and row.last_error == "merged"


def test_a_digest_cancelled_by_a_channel_change_before_the_deploy_is_not_taken_in(family, market,  # noqa: F811
                                                                                  public):
    """Cancelled by the code before 2026-11-18 when the channel was set up again: the 市場週報 push leaves it out."""
    fake, sunday = setup(family, market)
    with session_factory()() as db:
        row = db.scalar(select(NotificationOutbox).where(NotificationOutbox.kind == "digest"))
        row.status, row.last_error = "cancelled", "channel_changed"
        db.commit()
    n = len(fake.discord)
    queue(weekly(sunday), at(sunday, 18))
    send(market, at(sunday, 18, 1))
    assert len(fake.discord) == n + 1 and "你的群組上週" not in fake.discord[-1].body["content"]
    assert digest_rows()[0].status == "cancelled"
