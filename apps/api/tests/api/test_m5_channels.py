"""M5 push channels: Discord webhook (strict URL, test message first, encrypted at rest, hint only for the owner) and
Telegram linking through getUpdates (Discord and Telegram are faked; no test reaches the network)."""

from __future__ import annotations

import logging
import time
from datetime import timedelta

import httpx
import pytest

from forliosa.config import get_settings
from forliosa.crypto import decrypt_secret, token_hash
from forliosa.db import session_factory
from forliosa.logredact import RedactingFilter, redact_url
from forliosa.models import GroupChannel, TelegramLinkCode
from forliosa.services import channels, pushers
from forliosa.timeutil import now_utc
from tests.api.m5 import API, SHARE_ALL, SHARE_DEFAULT, join, login, make_group, set_share
from tests.api.push_fake import BOT_TOKEN, BOT_USERNAME, TOKEN, WEBHOOK, PushFake, tg_message


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


def put_discord(client, gid, url=WEBHOOK, **flags):
    return client.put(f"{API}/groups/{gid}/channels/discord", json={"webhook_url": url, **flags})


def channel_row(gid: str, kind: str) -> GroupChannel | None:
    with session_factory()() as db:
        row = db.get(GroupChannel, (gid, kind))
        if row is not None:
            db.expunge(row)
        return row


# -- Discord ------------------------------------------------------------------------------------------------------
def test_discord_tests_first_encrypts_and_shows_the_hint_only_to_the_owner(app, client, fake):
    g = make_group(client)
    member = login(app, "b@x.tw", "小明")
    join(client, member, g["id"])

    r = put_discord(client, g["id"], notify_trades=True, notify_digest=False)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["discord"] == {"configured": True, "status": "active", "disabled_reason": None,
                              "webhook_hint": "…/WXYZ", "notify_trades": True, "notify_digest": False}
    assert TOKEN not in r.text
    # the test message went to the canonical URL before saving, with mentions disabled
    assert len(fake.discord) == 1
    sent = fake.discord[0]
    assert sent.path == f"/api/webhooks/123456789012345678/{TOKEN}"
    assert sent.body["allowed_mentions"] == {"parse": []}
    assert "家族投資" in sent.body["content"]
    # encrypted at rest
    row = channel_row(g["id"], "discord")
    assert row is not None and TOKEN not in row.webhook_encrypted and row.webhook_hint == "WXYZ"
    assert decrypt_secret(row.webhook_encrypted) == WEBHOOK

    seen = member.get(f"{API}/groups/{g['id']}/channels").json()
    assert seen["discord"]["configured"] is True and seen["discord"]["webhook_hint"] is None
    assert seen["telegram"]["configured"] is False and seen["telegram_available"] is False
    assert member.get(f"{API}/groups/{g['id']}").json()["push_targets"] == [{"kind": "discord",
                                                                            "label": "Discord 頻道"}]
    # only the owner configures; non-members get 404
    assert put_discord(member, g["id"]).json()["error"]["code"] == "forbidden"
    assert member.patch(f"{API}/groups/{g['id']}/channels/discord", json={"notify_trades": False}).status_code == 403
    assert member.delete(f"{API}/groups/{g['id']}/channels/discord").status_code == 403
    outsider = login(app, "z@x.tw", "路人")
    assert outsider.get(f"{API}/groups/{g['id']}/channels").status_code == 404
    assert put_discord(outsider, g["id"]).status_code == 404


@pytest.mark.parametrize("url", [
    f"http://discord.com/api/webhooks/123456789012345678/{TOKEN}",
    f"https://discord.com.evil.example/api/webhooks/123456789012345678/{TOKEN}",
    f"https://evil.example/discord.com/api/webhooks/123456789012345678/{TOKEN}",
    f"https://user:pw@discord.com/api/webhooks/123456789012345678/{TOKEN}",
    f"https://evil.example@discord.com/api/webhooks/123456789012345678/{TOKEN}",
    f"https://discord.com:443/api/webhooks/123456789012345678/{TOKEN}",
    f"https://ptb.discord.com/api/webhooks/123456789012345678/{TOKEN}",
    f"https://discord.com/api/v10/webhooks/123456789012345678/{TOKEN}",
    f"https://discord.com/api/webhooks/123456789012345678/{TOKEN}/slack",
    f"https://discord.com/api/webhooks/123456789012345678/{TOKEN}?wait=true",
    f"https://discord.com/api/webhooks/123456789012345678/{TOKEN}#x",
    f"https://discord.com/api/webhooks/not-a-number/{TOKEN}",
    "https://discord.com/api/webhooks/123456789012345678/short",
    f" https://discord.com/api/webhooks/123456789012345678/{TOKEN}",
    f"https://discord.com\\@evil.example/api/webhooks/123456789012345678/{TOKEN}",
    f"https://discоrd.com/api/webhooks/123456789012345678/{TOKEN}",  # Cyrillic о
    "",
])
def test_webhook_url_is_validated_strictly_without_any_request(client, fake, url):
    g = make_group(client)
    r = put_discord(client, g["id"], url=url)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert TOKEN not in r.text
    assert fake.sent == []
    assert channel_row(g["id"], "discord") is None


def test_discordapp_host_is_accepted_and_canonicalised(client, fake):
    g = make_group(client)
    r = put_discord(client, g["id"], url=f"https://DiscordApp.com/api/webhooks/123456789012345678/{TOKEN}")
    assert r.status_code == 200, r.text
    assert fake.discord[0].host == "discordapp.com"


@pytest.mark.parametrize("failure", [404, 401, 500, 302, httpx.ConnectError("boom")])
def test_failed_test_message_saves_nothing(client, fake, failure):
    g = make_group(client)
    fake.discord_script.append(failure)
    r = put_discord(client, g["id"])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "webhook_failed"
    assert TOKEN not in r.text
    assert len(fake.discord) == 1  # a redirect is never followed
    assert channel_row(g["id"], "discord") is None


def test_patch_and_delete_discord(client, fake):
    g = make_group(client)
    assert client.patch(f"{API}/groups/{g['id']}/channels/discord", json={"notify_trades": False}).status_code == 404
    assert put_discord(client, g["id"]).status_code == 200
    before = channel_row(g["id"], "discord").configured_at
    r = client.patch(f"{API}/groups/{g['id']}/channels/discord", json={"notify_trades": False})
    assert r.status_code == 200 and r.json()["discord"]["notify_trades"] is False
    assert r.json()["discord"]["notify_digest"] is True
    r = client.patch(f"{API}/groups/{g['id']}/channels/discord", json={"notify_trades": True})
    assert r.json()["discord"]["notify_trades"] is True
    assert channel_row(g["id"], "discord").configured_at > before  # trades made while it was off are never pushed
    assert client.patch(f"{API}/groups/{g['id']}/channels/discord", json={"bogus": 1}).status_code == 422
    assert client.delete(f"{API}/groups/{g['id']}/channels/discord").status_code == 204
    assert client.get(f"{API}/groups/{g['id']}/channels").json()["discord"]["configured"] is False
    assert client.get(f"{API}/groups/{g['id']}").json()["push_targets"] == []


class Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_webhook_setup_is_rate_limited_per_user_and_group(app, client, fake):
    clock = Clock()
    channels.webhook_setups.clock = clock
    g = make_group(client)
    fake.discord_script.extend([401, 401])  # failed attempts count too
    codes = [put_discord(client, g["id"]).status_code for _ in range(5)]
    assert codes == [422, 422, 200, 200, 200]
    r = put_discord(client, g["id"])
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert len(fake.discord) == 5  # the sixth attempt never reached Discord
    other = make_group(client, "另一群")
    assert put_discord(client, other["id"]).status_code == 429  # the same user
    assert put_discord(client, g["id"], url="https://discord.com/api/webhooks/x/y").status_code == 422  # not counted
    stranger = login(app, "s@x.tw", "路人")
    assert put_discord(stranger, make_group(stranger, "他的群")["id"]).status_code == 200  # someone else
    clock.t += channels.SETUP_WINDOW_SECONDS + 1
    assert put_discord(client, g["id"]).status_code == 200


def test_sliding_limit_counts_every_key():
    clock = Clock()
    lim = channels.SlidingLimit(2, 60, clock)
    assert lim.hit(["user:a", "group:g"]) and lim.hit(["user:b", "group:g"])
    assert not lim.hit(["user:c", "group:g"])  # the group is at its limit …
    assert lim.hit(["user:c", "group:h"])  # … the user is not, and the refused attempt was not counted
    clock.t += 61
    assert lim.hit(["user:a", "group:g"])


def test_circuit_breaker_stops_webhook_requests_after_many_invalid_answers(app, client, fake, monkeypatch):
    clock = Clock()
    pushers.discord_breaker.clock = clock
    monkeypatch.setattr(pushers, "BREAKER_THRESHOLD", 3)
    fake.discord_status = 401
    for _ in range(3):
        assert pushers.send_discord(WEBHOOK, "x").error == "http_401"
    paused = pushers.send_discord(WEBHOOK, "x")
    assert paused.error == "paused" and paused.retry and paused.retry_after == pushers.BREAKER_PAUSE_SECONDS
    assert len(fake.discord) == 3
    g = make_group(client)
    r = put_discord(client, g["id"])
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert len(fake.discord) == 3 and channel_row(g["id"], "discord") is None
    clock.t += pushers.BREAKER_PAUSE_SECONDS
    fake.discord_status = 204
    assert put_discord(client, g["id"]).status_code == 200


def test_a_new_destination_turns_the_other_members_push_off(app, client, fake):
    g = make_group(client)
    b = login(app, "b@x.tw", "小明")
    join(client, b, g["id"], SHARE_ALL)
    set_share(client, g["id"], returns=True, push=True)
    share = lambda c: c.get(f"{API}/groups/{g['id']}/share").json()["push"]  # noqa: E731
    other = WEBHOOK.replace("123456789012345678", "987654321098765432")

    assert put_discord(client, g["id"]).status_code == 200  # the group's first destination: consent stands
    assert share(b) is True
    assert put_discord(client, g["id"], notify_digest=False).status_code == 200  # the same webhook again
    assert share(b) is True
    assert put_discord(client, g["id"], url=other).status_code == 200  # somewhere else
    assert share(b) is False and share(client) is True  # the owner who set it keeps theirs
    set_share(b, g["id"], **SHARE_ALL)  # 小明 agrees to the new target
    assert client.delete(f"{API}/groups/{g['id']}/channels/discord").status_code == 204
    assert share(b) is True
    row = channel_row(g["id"], "discord")
    assert row.status == "removed" and row.webhook_encrypted is None and row.webhook_hint is None
    seen = client.get(f"{API}/groups/{g['id']}/channels").json()["discord"]
    assert seen["configured"] is False and seen["status"] is None and seen["webhook_hint"] is None
    assert client.patch(f"{API}/groups/{g['id']}/channels/discord", json={"notify_trades": False}).status_code == 404
    assert put_discord(client, g["id"], url=other).status_code == 200  # set up again after removal: new
    assert share(b) is False


def test_webhook_secret_never_reaches_the_logs(client, fake, caplog):
    caplog.set_level(logging.DEBUG)
    g = make_group(client)
    put_discord(client, g["id"])
    fake.discord_script.append(404)
    put_discord(client, g["id"])
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert TOKEN not in text


def test_redaction_of_push_urls():
    assert TOKEN not in redact_url(f'HTTP Request: POST {WEBHOOK} "HTTP/1.1 204 No Content"')
    assert BOT_TOKEN not in redact_url(f"POST https://api.telegram.org/bot{BOT_TOKEN}/sendMessage")
    assert BOT_TOKEN.split(":")[1] not in redact_url(f"token {BOT_TOKEN} leaked")
    record = logging.LogRecord("httpx", logging.INFO, __file__, 1, "HTTP Request: %s %s", ("POST",
                               httpx.URL(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates")), None)
    RedactingFilter().filter(record)
    assert BOT_TOKEN not in record.getMessage()
    try:
        raise RuntimeError(f"failed {WEBHOOK}")
    except RuntimeError:
        import sys

        rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "boom", (), sys.exc_info())
    RedactingFilter().filter(rec)
    assert TOKEN not in (rec.exc_text or "")


# -- Telegram -----------------------------------------------------------------------------------------------------
def link_code(client, gid) -> dict:
    r = client.post(f"{API}/groups/{gid}/channels/telegram/link")
    assert r.status_code == 200, r.text
    return r.json()


def poll(fake: PushFake, *updates, now=None) -> int:
    fake.updates = list(updates)
    poller = channels.TelegramPoller()
    with session_factory()() as db:
        return poller.poll(db, now=now)


def test_telegram_needs_a_bot(client):
    g = make_group(client)
    r = client.post(f"{API}/groups/{g['id']}/channels/telegram/link")
    assert r.status_code == 409 and r.json()["error"]["code"] == "telegram_unavailable"


def test_telegram_link_code_is_random_hashed_and_owner_only(app, client, fake, telegram_env):
    g = make_group(client)
    member = login(app, "b@x.tw", "小明")
    join(client, member, g["id"])
    assert member.post(f"{API}/groups/{g['id']}/channels/telegram/link").status_code == 403
    out = link_code(client, g["id"])
    assert out["bot_username"] == BOT_USERNAME and len(out["code"]) >= 10
    assert client.get(f"{API}/groups/{g['id']}/channels").json()["telegram_available"] is True
    with session_factory()() as db:
        rows = list(db.query(TelegramLinkCode).all())
        assert [r.code_hash for r in rows] == [token_hash(out["code"])]
    second = link_code(client, g["id"])  # a new code replaces the unused one
    assert second["code"] != out["code"]
    with session_factory()() as db:
        assert [r.code_hash for r in db.query(TelegramLinkCode).all()] == [token_hash(second["code"])]


def test_link_through_get_updates(app, client, fake, telegram_env):
    g = make_group(client)
    code = link_code(client, g["id"])["code"]
    poll(fake, tg_message(1, -100123, f"/link@{BOT_USERNAME.lower()} {code.lower()}"))
    ch = channel_row(g["id"], "telegram")
    assert ch is not None and ch.status == "active" and ch.telegram_chat_id == -100123
    assert ch.chat_title == "家族投資群"
    reply = fake.telegram()[-1].body
    assert reply["chat_id"] == -100123 and "家族投資" in reply["text"] and "parse_mode" not in reply
    seen = client.get(f"{API}/groups/{g['id']}/channels").json()["telegram"]
    assert seen == {"configured": True, "status": "active", "disabled_reason": None, "chat_title": "家族投資群",
                    "notify_trades": True, "notify_digest": True}
    assert client.get(f"{API}/groups/{g['id']}").json()["push_targets"] == [{"kind": "telegram",
                                                                            "label": "家族投資群"}]
    # single use
    poll(fake, tg_message(2, -100999, f"/link {code}"))
    assert channel_row(g["id"], "telegram").telegram_chat_id == -100123
    assert "無效" in fake.telegram()[-1].body["text"]


def test_link_edge_cases(client, fake, telegram_env):
    g = make_group(client)
    code = link_code(client, g["id"])["code"]
    n_before = len(fake.telegram())
    poll(fake, tg_message(1, -1001, f"/link@SomeOtherBot {code}"))  # for another bot: ignored silently
    poll(fake, tg_message(2, -1001, f"/link {code}", date=int(time.time()) - 3600))  # stale: ignored
    assert len(fake.telegram()) == n_before and channel_row(g["id"], "telegram") is None
    poll(fake, tg_message(3, 4242, f"/link {code}", chat_type="private"))  # a private chat: hint, code kept
    assert "群組" in fake.telegram()[-1].body["text"] and channel_row(g["id"], "telegram") is None
    poll(fake, tg_message(4, -1001, f"/link {code}"), now=now_utc() + timedelta(minutes=11))  # expired
    assert channel_row(g["id"], "telegram") is None
    code = link_code(client, g["id"])["code"]
    poll(fake, tg_message(5, -1001, f"/link {code}"))
    assert channel_row(g["id"], "telegram").telegram_chat_id == -1001
    # the group became a supergroup; then the title changed; then the bot was removed
    poll(fake, tg_message(6, -1001, "", migrate_to_chat_id=-1009999))
    assert channel_row(g["id"], "telegram").telegram_chat_id == -1009999
    poll(fake, tg_message(7, -1009999, "", new_chat_title="王家"))
    assert channel_row(g["id"], "telegram").chat_title == "王家"
    poll(fake, {"update_id": 8, "my_chat_member": {"chat": {"id": -1009999, "type": "supergroup"},
                                                    "new_chat_member": {"status": "kicked"}}})
    ch = channel_row(g["id"], "telegram")
    assert ch.status == "disabled" and ch.disabled_reason == "bot_removed"
    assert client.get(f"{API}/groups/{g['id']}").json()["push_targets"] == []


def test_link_code_of_a_former_owner_is_refused(app, client, fake, telegram_env):
    g = make_group(client)
    member = login(app, "b@x.tw", "小明")
    join(client, member, g["id"], SHARE_DEFAULT)
    code = link_code(client, g["id"])["code"]
    me = member.get(f"{API}/me").json()["id"]
    assert client.post(f"{API}/groups/{g['id']}/transfer", json={"user_id": me}).status_code == 200
    poll(fake, tg_message(1, -1001, f"/link {code}"))
    assert channel_row(g["id"], "telegram") is None


def test_relinking_another_chat_turns_the_other_members_push_off(app, client, fake, telegram_env):
    g = make_group(client)
    b = login(app, "b@x.tw", "小明")
    join(client, b, g["id"], SHARE_ALL)
    share = lambda: b.get(f"{API}/groups/{g['id']}/share").json()["push"]  # noqa: E731
    poll(fake, tg_message(1, -1001, f"/link {link_code(client, g['id'])['code']}"))
    assert share() is True  # the first chat
    poll(fake, tg_message(2, -1001, f"/link {link_code(client, g['id'])['code']}"))
    assert share() is True  # the same chat again
    poll(fake, tg_message(3, -1001, "", migrate_to_chat_id=-1002))
    assert share() is True  # the same chat, now a supergroup
    poll(fake, tg_message(4, -2002, f"/link {link_code(client, g['id'])['code']}", title="公開投資討論"))
    assert share() is False
    assert client.get(f"{API}/groups/{g['id']}").json()["push_targets"] == [{"kind": "telegram",
                                                                            "label": "公開投資討論"}]
    set_share(b, g["id"], **SHARE_ALL)
    assert client.delete(f"{API}/groups/{g['id']}/channels/telegram").status_code == 204
    assert client.get(f"{API}/groups/{g['id']}/channels").json()["telegram"]["configured"] is False
    poll(fake, tg_message(5, -2002, f"/link {link_code(client, g['id'])['code']}"))
    assert share() is False  # set up again after removal
    ch = channel_row(g["id"], "telegram")
    assert ch.status == "active" and ch.notify_trades and ch.notify_digest


def test_poller_drains_the_backlog_and_throttles_answers(client, fake, telegram_env):
    g = make_group(client)
    code = link_code(client, g["id"])["code"]
    flood = [tg_message(i, 5000 + i, "/link nope", chat_type="private") for i in range(1, 251)]
    flood += [tg_message(251, 6000, "hello there", chat_type="private")]  # not /link: nothing to do
    flood += [tg_message(252, -1001, f"/link@{BOT_USERNAME} {code}")]
    fake.updates = flood
    poller = channels.TelegramPoller()
    with session_factory()() as db:
        assert poller.poll(db) == 252
    assert poller.offset == 253
    assert len(fake.telegram("getUpdates")) == 3  # 100 + 100 + 52
    assert channel_row(g["id"], "telegram").telegram_chat_id == -1001  # the real /link was not lost
    replies = fake.telegram()
    assert len(replies) == channels.MAX_REPLIES_PER_POLL + 1 and "已連結" in replies[-1].body["text"]

    fake.sent.clear()
    fake.updates = [tg_message(300 + i, -7000, "/link bad") for i in range(5)]  # one chat, five tries
    with session_factory()() as db:
        poller.poll(db)
    assert len(fake.telegram()) == 1  # one answer per chat per minute


def test_poller_stops_at_its_time_budget_and_resumes(client, fake, telegram_env):
    class Ticking(Clock):
        def __call__(self) -> float:
            self.t += 1.0  # every look at the clock costs a second
            return self.t

    poller = channels.TelegramPoller(clock=Ticking())
    fake.updates = [tg_message(i, -1, "hello") for i in range(1, 31)]
    with session_factory()() as db:
        first = poller.poll(db)
        assert 0 < first < 30 and poller.offset == first + 1
        assert first + poller.poll(db) + poller.poll(db) + poller.poll(db) == 30


def test_poller_keeps_the_offset_and_never_logs_the_token(client, fake, telegram_env, caplog):
    caplog.set_level(logging.DEBUG)
    poller = channels.TelegramPoller()
    fake.updates = [tg_message(41, -1, "hello"), tg_message(42, -1, "/link")]
    with session_factory()() as db:
        poller.poll(db)
        assert poller.offset == 43
        poller.poll(db)
    assert fake.telegram("getUpdates")[-1].body["offset"] == 43
    fake.telegram_script["getUpdates"] = __import__("collections").deque([(500, {"ok": False})])
    with session_factory()() as db:
        poller.poll(db)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert BOT_TOKEN not in text and BOT_TOKEN.split(":")[1] not in text


def test_channels_and_digests_are_not_open_to_view_as(app, client, fake):
    g = make_group(client)
    member = login(app, "b@x.tw", "小明")
    join(client, member, g["id"])
    me = member.get(f"{API}/me").json()["id"]
    dlg = client.post(f"{API}/delegations", json={"viewer_user_id": me, "scope": "all"}).json()
    headers = {"X-Forliosa-View-As": dlg["id"]}
    for path in ("channels", "digests"):
        r = member.get(f"{API}/groups/{g['id']}/{path}", headers=headers)
        assert r.status_code == 403 and r.json()["error"]["code"] == "view_as_not_allowed"
    r = member.put(f"{API}/groups/{g['id']}/channels/discord", json={"webhook_url": WEBHOOK}, headers=headers)
    assert r.json()["error"]["code"] == "read_only"
    assert fake.sent == []
