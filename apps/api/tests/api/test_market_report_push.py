"""市場報告 pushes to group channels (contract §15): the switches (盤前、盤後 off, 週報 on); the text (disclaimer
line, highlights, 「出處見全文」, the link, the limits); the 盤前 push takes in the group's daily report of the previous
session (「昨日你的群組」) and the held daily push is marked merged; paused or turned-off pushes are cancelled. The
combinations of the four switches (2026-11-18) are in ``test_channel_four_switches``."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from forliosa import disclaimer
from forliosa.config import get_settings
from forliosa.db import session_factory
from forliosa.models import MarketReport, NotificationOutbox
from forliosa.reports import pipeline, push
from forliosa.reports import settings as rs
from forliosa.services import notifications
from forliosa.timeutil import TAIPEI, next_tw_trading_day
from tests.api.m5 import API, make_group
from tests.api.push_fake import WEBHOOK, PushFake
from tests.api.test_group_daily import _channel, day, evening, family, run  # noqa: F401 - fixtures

PAYLOAD = {"has_ai": True, "calendar": None, "highlights": [
    {"sentences": [{"text": "SPY 美股 11/16 漲 0.50%。", "refs": ["F001"]}]},
    {"sentences": [{"text": "〔中央社〕報導，台積電 ADR 美股 11/16 跌 1.00%。", "refs": ["X001"]}]},
    {"sentences": [{"text": "已排定：鴻海（2317）11/17（二）法說會。", "refs": ["C001"]}]}]}


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


def make(kind: str, d: date, payload: dict | None = None) -> str:
    with session_factory()() as db:
        ed = pipeline.edition_on(kind, d)
        now = ed.push_at
        r = pipeline.make_report(db, ed, now, visibility="public")
        v = pipeline.new_version(db, r, edition="ai", payload=payload or PAYLOAD, now=now)
        r.current_version_id, r.state = v.id, "ai"
        db.commit()
        return r.id


def queue_and_send(rid: str, at: datetime, market) -> int:
    with session_factory()() as db:
        n = push.enqueue(db, db.get(MarketReport, rid), at)
        notifications.send_due(db, market, now=at + timedelta(minutes=1))
        return n


def test_switches_defaults_and_availability(app, client, monkeypatch):
    g = make_group(client)
    fake = PushFake().install()
    assert client.put(f"{API}/groups/{g['id']}/channels/discord", json={"webhook_url": WEBHOOK}).status_code == 200
    ch = client.get(f"{API}/groups/{g['id']}/channels").json()
    assert ch["discord"]["notify_premarket"] is False and ch["discord"]["notify_close"] is False
    assert ch["discord"]["notify_weekly"] is True and ch["market_reports_available"] is False
    r = client.patch(f"{API}/groups/{g['id']}/channels/discord",
                     json={"notify_premarket": True, "notify_weekly": False})
    assert r.json()["discord"]["notify_premarket"] is True and r.json()["discord"]["notify_weekly"] is False
    monkeypatch.setenv("MARKET_REPORTS_ENABLED", "true")
    get_settings.cache_clear()
    with session_factory()() as db:
        rs.config(db).mode = "public"
        db.commit()
    assert client.get(f"{API}/groups/{g['id']}/channels").json()["market_reports_available"] is True
    assert fake.discord  # the connect message
    get_settings.cache_clear()


def test_text_template_and_limits():
    settings = SimpleNamespace(frontend_url="https://forliosa.trade", is_dev=False, frontend_base="https://forliosa.trade")
    r = SimpleNamespace(id="mrp_1", kind="premarket", edition_date=date(2026, 11, 18), period_start=date(2026, 11, 18),
                        period_end=date(2026, 11, 18), next_start=None, next_end=None)
    t = push.text(r, PAYLOAD, "discord", settings)
    lines = t.split("\n")
    assert lines[0] == "【盤前重點 11/18（三）】AI 依公開資料整理，報告本文人人相同，不是投資建議。"
    assert lines[2].endswith("（出處見全文）") and not lines[1].endswith("（出處見全文）")
    assert lines[-2] == "全文與圖表：https://forliosa.trade/market/reports/mrp_1"
    # the site's last line, once (notifications.signed; 2026-11-17 disclaimers)
    assert lines[-1] == disclaimer.AI_NOTE + disclaimer.SHORT and t.count(disclaimer.SHORT) == 1
    data = push.text(r, {**PAYLOAD, "has_ai": False}, "telegram", settings)
    assert data.split("\n")[0].endswith("依公開資料整理，這一版沒有 AI 段落，不是投資建議。")
    assert data.split("\n")[-1] == disclaimer.SHORT
    long = {**PAYLOAD, "highlights": [{"sentences": [{"text": "長" * 900, "refs": ["F001"]}]}] * 3}
    cut = push.text(r, long, "discord", settings, ["昨日你的群組（11/17）", *("小明 +1.0%" for _ in range(10))])
    assert len(cut) <= 1900 and "…" in cut and cut.endswith(disclaimer.SHORT)
    w = SimpleNamespace(id="mrp_2", kind="weekly", edition_date=date(2026, 11, 22), period_start=date(2026, 11, 16),
                        period_end=date(2026, 11, 20), next_start=date(2026, 11, 23), next_end=date(2026, 11, 27))
    cal = {"groups": [{"rows": [{}, {}], "folded": [{"count": 3}]}]}
    wt = push.text(w, {**PAYLOAD, "calendar": cal}, "discord", settings)
    assert wt.startswith("【市場週報 11/16–11/20 回顧】") and "下週行事曆 11/23–11/27：已排定 5 件（見全文）" in wt
    nolink = SimpleNamespace(frontend_url=None, is_dev=False, frontend_base="")
    assert "全文與圖表" not in push.text(r, PAYLOAD, "discord", nolink)


def test_when_the_group_parts_are_due():
    """盤前 07:30 of the next trading day (held to 08:20 while a market part may take it in), 週報 Sunday 18:00 (held
    to 21:30); finished later than that: at once."""
    mon, fri = date(2026, 11, 16), date(2026, 11, 20)
    at = lambda d, h, m=0: datetime.combine(d, time(h, m), TAIPEI)  # noqa: E731
    tue, sat, sun = date(2026, 11, 17), date(2026, 11, 21), date(2026, 11, 22)
    assert push.daily_due(mon, at(mon, 23, 40), True) == at(tue, 8, 20)
    assert push.daily_due(mon, at(mon, 23, 40), False) == at(tue, 7, 30)  # no market part: alone at 07:30
    assert push.daily_due(fri, at(fri, 19), False) == at(date(2026, 11, 23), 7, 30)  # no 盤前 on the weekend
    assert push.daily_due(mon, at(tue, 9), True) == at(tue, 9)
    assert push.digest_due(fri, at(sat, 20, 5), True) == at(sun, 21, 30)
    assert push.digest_due(fri, at(sat, 20, 5), False) == at(sun, 18)
    assert push.digest_due(fri, at(sun, 19), False) == at(sun, 19)


def test_premarket_push_takes_in_yesterdays_group(family, market, day, public):  # noqa: F811
    fake = _channel(family)  # 盤前 on: it carries 「昨日你的群組」
    g = family["g"]
    run(market, evening(day, time(23, 40)))
    nxt = next_tw_trading_day(day + timedelta(days=1))
    with session_factory()() as db:
        [row] = db.scalars(select(NotificationOutbox).where(NotificationOutbox.kind == "daily")).all()
        assert row.not_before == datetime.combine(nxt, time(7, 30), TAIPEI)  # the slot; held then if a push comes
    before = len(fake.discord)
    rid = make("premarket", nxt)
    assert queue_and_send(rid, datetime.combine(nxt, time(7, 30), TAIPEI), market) == 1
    assert len(fake.discord) == before + 1
    text = fake.discord[-1].body["content"]
    assert text.startswith(f"【盤前重點 {nxt.month}/{nxt.day}（")
    assert f"昨日你的群組（{day.month}/{day.day}）" in text and "小明" in text and "示範使用者" not in text
    body = text.rstrip().split("\n")
    assert body[-2].endswith(f"/market/reports/{rid}") and body[-1].endswith(disclaimer.SHORT)
    assert text.count(disclaimer.SHORT) == 1  # the folded daily report's own last line is not repeated
    with session_factory()() as db:
        daily = db.scalar(select(NotificationOutbox).where(NotificationOutbox.kind == "daily"))
        mrow = db.scalar(select(NotificationOutbox).where(NotificationOutbox.kind == "mreport"))
        assert daily.status == "sent" and daily.last_error == "merged"
        assert mrow.status == "sent" and mrow.dedupe_key == f"mreport:{rid}:{g['id']}:discord"
        notifications.send_due(db, market, now=datetime.combine(nxt, time(8, 30), TAIPEI))
    assert len(fake.discord) == before + 1  # the daily report is not sent on its own


def test_switch_off_or_pause_cancels(family, market, day, public):  # noqa: F811
    _channel(family, daily=False)
    g, a = family["g"], family["a"]
    a.patch(f"{API}/groups/{g['id']}/channels/discord", json={"notify_close": True})
    rid = make("close", day)
    at = datetime.combine(day, time(16), TAIPEI)
    with session_factory()() as db:
        assert push.enqueue(db, db.get(MarketReport, rid), at) == 1
        assert push.enqueue(db, db.get(MarketReport, rid), at) == 0  # once per channel
        rs.config(db).mode = "paused"
        db.commit()
        notifications.send_due(db, market, now=at + timedelta(minutes=1))
        row = db.scalar(select(NotificationOutbox).where(NotificationOutbox.kind == "mreport"))
        assert row.status == "cancelled" and row.last_error == "not_public"


def test_trial_and_backfill_are_never_pushed(family, day, public):  # noqa: F811
    _channel(family, daily=False)
    rid = make("close", day)
    with session_factory()() as db:
        r = db.get(MarketReport, rid)
        r.trial = True
        db.commit()
        assert push.enqueue(db, r, datetime.combine(day, time(16), TAIPEI)) == 0
        r.trial, r.backfill = False, True
        db.commit()
        assert push.enqueue(db, r, datetime.combine(day, time(16), TAIPEI)) == 0
