"""市場週報 push takes in the group's weekly digest (contract §15.3): with the weekly report push on and the reports
public, the digest push waits until Sunday 21:30; the 18:00 weekly push carries 「你的群組上週」 and the digest row is
marked merged. With the weekly push off the digest goes on Saturday as before."""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest
from sqlalchemy import select

from forliosa import disclaimer
from forliosa.config import get_settings
from forliosa.db import session_factory
from forliosa.models import MarketReport, NotificationOutbox
from forliosa.reports import pipeline, push
from forliosa.reports import settings as rs
from forliosa.services import notifications
from forliosa.timeutil import TAIPEI
from tests.api.m5 import API
from tests.api.push_fake import WEBHOOK, PushFake
from tests.api.test_m5_digest import FakeClaude, create, family, run_ai  # noqa: F401 - fixtures

PAYLOAD = {"has_ai": True, "calendar": {"groups": [{"rows": [{}], "folded": []}]}, "highlights": [
    {"sentences": [{"text": "加權指數週 ▲1.23%。", "refs": ["F001"]}]}]}


@pytest.fixture()
def public(app, monkeypatch):
    monkeypatch.setenv("MARKET_REPORTS_ENABLED", "true")
    get_settings.cache_clear()
    with session_factory()() as db:
        rs.config(db).mode = "public"
        db.commit()
    yield
    get_settings.cache_clear()


def test_weekly_push_takes_in_the_digest(family, market, public):  # noqa: F811
    g, a, sat = family["g"], family["a"], family["sat"]
    fake = PushFake().install()
    assert a.put(f"{API}/groups/{g['id']}/channels/discord", json={"webhook_url": WEBHOOK}).status_code == 200
    assert len(create(market, sat)) == 1
    run_ai(FakeClaude(), sat)
    sunday = sat + timedelta(days=1)
    with session_factory()() as db:
        [row] = db.scalars(select(NotificationOutbox).where(NotificationOutbox.kind == "digest")).all()
        assert row.not_before == datetime.combine(sunday, time(21, 30), TAIPEI)
        ed = pipeline.edition_on("weekly", sunday)
        r = pipeline.make_report(db, ed, ed.push_at, visibility="public")
        v = pipeline.new_version(db, r, edition="ai", payload=PAYLOAD, now=ed.push_at)
        r.current_version_id, r.state = v.id, "ai"
        db.commit()
        before = len(fake.discord)
        assert push.enqueue(db, db.get(MarketReport, r.id), ed.push_at) == 1
        notifications.send_due(db, market, now=ed.push_at + timedelta(minutes=1))
        assert len(fake.discord) == before + 1
        text = fake.discord[-1].body["content"]
        assert text.startswith(f"【市場週報 {ed.period[0].month}/{ed.period[0].day}–")
        assert "你的群組上週（" in text and "小明" in text and "下週行事曆" in text
        assert text.count(disclaimer.SHORT) == 1 and text.endswith(disclaimer.SHORT)  # once, last
        db.refresh(row)
        assert row.status == "sent" and row.last_error == "merged"
        notifications.send_due(db, market, now=datetime.combine(sunday, time(21, 31), TAIPEI))
        assert len(fake.discord) == before + 1


def test_digest_goes_on_saturday_when_the_weekly_push_is_off(family, market, public):  # noqa: F811
    g, a, sat = family["g"], family["a"], family["sat"]
    PushFake().install()
    assert a.put(f"{API}/groups/{g['id']}/channels/discord",
                 json={"webhook_url": WEBHOOK, "notify_weekly": False}).status_code == 200
    create(market, sat)
    run_ai(FakeClaude(), sat)
    with session_factory()() as db:
        [row] = db.scalars(select(NotificationOutbox).where(NotificationOutbox.kind == "digest")).all()
        assert row.not_before.astimezone(TAIPEI).date() == sat
