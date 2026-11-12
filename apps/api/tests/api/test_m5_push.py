"""M5 push of trades to group channels: who and what may be pushed, the 15-minute delay, re-checks at send time,
no resend after edits, retries with backoff, disabled channels (Discord and Telegram faked)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from forliosa.config import get_settings
from forliosa.db import session_factory
from forliosa.models import GroupChannel, NotificationOutbox
from forliosa.services import notifications
from forliosa.timeutil import now_utc, today_taipei
from tests.api.m5 import API, SHARE_ALL, SHARE_DEFAULT, account, join, login, make_group, set_share, trade
from tests.api.push_fake import BOT_TOKEN, BOT_USERNAME, WEBHOOK, PushFake

LATER = timedelta(minutes=16)


@pytest.fixture()
def fake() -> PushFake:
    return PushFake().install()


@pytest.fixture()
def telegram_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", BOT_USERNAME)
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


def run(market, at=None) -> tuple[int, int]:
    at = at or now_utc()
    with session_factory()() as db:
        return notifications.enqueue_trades(db, at), notifications.send_due(db, market, now=at)


def outbox() -> list[NotificationOutbox]:
    with session_factory()() as db:
        rows = list(db.scalars(select(NotificationOutbox).order_by(NotificationOutbox.created_at)))
        for r in rows:
            db.expunge(r)
        return rows


def setup_group(app, client, fake, share=None):
    g = make_group(client)
    b = login(app, "b@x.tw", "小明")
    join(client, b, g["id"], share or SHARE_ALL)
    r = client.put(f"{API}/groups/{g['id']}/channels/discord", json={"webhook_url": WEBHOOK})
    assert r.status_code == 200, r.text
    fake.sent.clear()
    return g, b


def test_trades_are_pushed_after_15_minutes_once_with_price(app, client, fake, market):
    g, b = setup_group(app, client, fake)
    c = login(app, "c@x.tw", "小華")
    join(client, c, g["id"], {**SHARE_ALL, "push": False})  # shares trades but does not push
    acc_b, acc_c = account(b), account(c)
    today = today_taipei()
    trade(b, acc_b["id"], "2330", "buy", today, 1000, 600)
    trade(b, acc_b["id"], "2330", "buy", today, 1000, 610)
    trade(c, acc_c["id"], "2317", "buy", today, 1000, 100)

    queued, _ = run(market)
    assert queued == 2 and fake.sent == []  # only 小明's two trades, and not before 15 minutes
    assert {r.user_id for r in outbox()} == {b.get(f"{API}/me").json()["id"]}

    run(market, now_utc() + LATER)
    assert len(fake.discord) == 1  # one feed item → one message
    body = fake.discord[0].body
    assert body["allowed_mentions"] == {"parse": []}
    text = body["content"]
    assert "小明 買進" in text and "（2330）" in text and "共 2 筆" in text and "成交均價 605.00 TWD" in text
    assert "小華" not in text and "1,000" not in text and "永豐" not in text
    assert all(r.status == "sent" for r in outbox())

    run(market, now_utc() + 2 * LATER)
    assert len(fake.discord) == 1  # never resent


def test_no_price_without_trade_prices_and_no_resend_after_edit(app, client, fake, market):
    _g, b = setup_group(app, client, fake, {**SHARE_ALL, "trade_prices": False})
    acc = account(b)
    t = trade(b, acc["id"], "2330", "buy", today_taipei(), 1000, 600)
    run(market)
    run(market, now_utc() + LATER)
    assert len(fake.discord) == 1 and "均價" not in fake.discord[0].body["content"]
    r = b.patch(f"{API}/transactions/{t['id']}", json={"price": 650})
    assert r.status_code == 200, r.text
    run(market, now_utc() + 2 * LATER)
    assert len(fake.discord) == 1


def test_only_trades_after_the_channel_and_the_toggles(app, client, fake, market):
    g = make_group(client)
    b = login(app, "b@x.tw", "小明")
    join(client, b, g["id"], {**SHARE_ALL, "push": False})
    acc = account(b)
    today = today_taipei()
    trade(b, acc["id"], "2330", "buy", today, 1000, 600)  # before the channel and before push
    assert client.put(f"{API}/groups/{g['id']}/channels/discord", json={"webhook_url": WEBHOOK}).status_code == 200
    trade(b, acc["id"], "2317", "buy", today, 1000, 100)  # after the channel, still before push
    set_share(b, g["id"], **{**SHARE_ALL, "push": True})
    trade(b, acc["id"], "2330", "sell", today, 500, 610)  # after both
    trade(b, acc["id"], "2454", "buy", today - timedelta(days=5), 1000, 900)  # too old a trade date
    queued, _ = run(market)
    assert queued == 1
    run(market, now_utc() + LATER)
    contents = [s.body["content"] for s in fake.discord[1:]]
    assert len(contents) == 1 and "賣出" in contents[0] and "（2330）" in contents[0]


def test_deleted_or_unshared_within_the_delay_is_never_sent(app, client, fake, market):
    g, b = setup_group(app, client, fake)
    acc = account(b)
    t1 = trade(b, acc["id"], "2330", "buy", today_taipei(), 1000, 600)
    run(market)
    assert b.delete(f"{API}/transactions/{t1['id']}").status_code == 204
    assert outbox() == []  # the row went with the transaction
    trade(b, acc["id"], "2317", "buy", today_taipei(), 1000, 100)
    run(market)
    set_share(b, g["id"], **{**SHARE_ALL, "push": False})
    set_share(b, g["id"], **SHARE_ALL)  # turned on again: trades made before that stay private
    run(market, now_utc() + LATER)
    assert fake.discord == []
    assert [r.status for r in outbox()] == ["cancelled"]


def test_leaving_the_group_cancels(app, client, fake, market):
    g, b = setup_group(app, client, fake)
    acc = account(b)
    trade(b, acc["id"], "2330", "buy", today_taipei(), 1000, 600)
    run(market)
    me = b.get(f"{API}/me").json()["id"]
    assert b.delete(f"{API}/groups/{g['id']}/members/{me}").status_code == 204
    run(market, now_utc() + LATER)
    assert fake.discord == [] and [r.status for r in outbox()] == ["cancelled"]


def test_retries_with_backoff_then_fails(app, client, fake, market):
    _g, b = setup_group(app, client, fake)
    acc = account(b)
    trade(b, acc["id"], "2330", "buy", today_taipei(), 1000, 600)
    fake.discord_status = 500
    t = now_utc() + LATER
    run(market, t)
    waits = []
    for _ in range(4):
        row = outbox()[0]
        assert row.status == "pending"
        waits.append(row.not_before - t)
        t = row.not_before
        run(market, t)
    row = outbox()[0]
    assert row.status == "failed" and row.attempts == 5 and row.last_error == "http_500"
    assert [round(w.total_seconds() / 60) for w in waits] == [1, 2, 4, 8]
    assert len(fake.discord) == 5


def test_rate_limit_waits_at_least_retry_after(app, client, fake, market):
    _g, b = setup_group(app, client, fake)
    acc = account(b)
    trade(b, acc["id"], "2330", "buy", today_taipei(), 1000, 600)
    fake.discord_script.append(429)
    t = now_utc() + LATER
    run(market, t)
    row = outbox()[0]
    assert row.status == "pending" and (row.not_before - t).total_seconds() >= 60
    run(market, row.not_before)
    assert outbox()[0].status == "sent"


@pytest.mark.parametrize("status", [404, 401])
def test_missing_webhook_disables_the_channel(app, client, fake, market, status):
    g, b = setup_group(app, client, fake)
    acc = account(b)
    trade(b, acc["id"], "2330", "buy", today_taipei(), 1000, 600)
    trade(b, acc["id"], "2317", "buy", today_taipei(), 1000, 100)
    fake.discord_status = status
    run(market, now_utc() + LATER)
    assert len(fake.discord) == 1  # the second message is not attempted
    seen = client.get(f"{API}/groups/{g['id']}/channels").json()["discord"]
    assert seen["status"] == "disabled" and seen["disabled_reason"] == "webhook_invalid"
    assert b.get(f"{API}/groups/{g['id']}").json()["push_targets"] == []
    assert sorted(r.status for r in outbox()) == ["cancelled", "failed"]


def add_telegram(group_id: str, chat_id: int = -1001) -> None:
    with session_factory()() as db:
        db.add(GroupChannel(group_id=group_id, kind="telegram", status="active", telegram_chat_id=chat_id,
                            chat_title="家族投資群", notify_trades=True, notify_digest=True,
                            configured_at=now_utc()))
        db.commit()


def test_telegram_plain_text_migration_and_removal(app, client, fake, market, telegram_env):
    g = make_group(client)
    b = login(app, "b@x.tw", "@everyone")
    join(client, b, g["id"], SHARE_ALL)
    add_telegram(g["id"])
    acc = account(b)
    trade(b, acc["id"], "2330", "buy", today_taipei(), 1000, 600)
    fake.telegram_script["sendMessage"] = __import__("collections").deque([
        (400, {"ok": False, "error_code": 400, "description": "Bad Request: group chat was upgraded",
               "parameters": {"migrate_to_chat_id": -1002002}})])
    run(market)
    run(market, now_utc() + LATER)
    sends = fake.telegram()
    assert [s.body["chat_id"] for s in sends] == [-1001, -1002002]
    assert "parse_mode" not in sends[-1].body and "＠everyone" in sends[-1].body["text"]
    with session_factory()() as db:
        assert db.get(GroupChannel, (g["id"], "telegram")).telegram_chat_id == -1002002
    assert outbox()[0].status == "sent"

    trade(b, acc["id"], "2317", "buy", today_taipei(), 1000, 100)
    fake.telegram_script["sendMessage"] = __import__("collections").deque([
        (403, {"ok": False, "error_code": 403, "description": "Forbidden: bot was kicked"})])
    run(market)
    run(market, now_utc() + LATER)
    ch = client.get(f"{API}/groups/{g['id']}/channels").json()["telegram"]
    assert ch["status"] == "disabled" and ch["disabled_reason"] == "bot_removed"


def test_channel_without_notify_trades_gets_nothing(app, client, fake, market):
    g, b = setup_group(app, client, fake)
    client.patch(f"{API}/groups/{g['id']}/channels/discord", json={"notify_trades": False})
    trade(b, account(b)["id"], "2330", "buy", today_taipei(), 1000, 600)
    assert run(market)[0] == 0
    run(market, now_utc() + LATER)
    assert fake.discord == []


def test_default_share_never_pushes(app, client, fake, market):
    _g, b = setup_group(app, client, fake, SHARE_DEFAULT)
    trade(b, account(b)["id"], "2330", "buy", today_taipei(), 1000, 600)
    assert run(market)[0] == 0
