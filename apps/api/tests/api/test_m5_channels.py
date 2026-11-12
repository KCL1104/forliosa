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
from forliosa.services import channels
from forliosa.timeutil import now_utc
from tests.api.m5 import API, SHARE_DEFAULT, join, login, make_group
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
