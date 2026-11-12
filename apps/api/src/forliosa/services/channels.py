"""Group push channels: one Discord webhook and one Telegram group chat per group (docs/api-contract.md 「分享（M5）」→
「推播」). Only the owner configures them; every member sees where the group pushes (``Group.push_targets``,
``GET /groups/{id}/channels``), and only the owner sees the webhook's last 4 characters.

* **Discord**: the URL is validated strictly (``pushers.parse_webhook_url``), a test message is sent *before* saving
  (any failure → 422 ``webhook_failed``), and the URL is stored encrypted (``crypto.encrypt_secret``); responses show
  only ``…/abcd``. The URL is never logged or echoed in an error.
* **Telegram**: the owner asks for a one-time link code (12 characters from a 32-symbol alphabet = 60 bits, 10 minutes,
  only its SHA-256 stored; a new code replaces the group's unused ones) and sends ``/link <code>`` (or
  ``/link@<bot> <code>``) in the Telegram group. The worker polls ``getUpdates`` (:func:`poll_telegram`; there is no
  public webhook endpoint), links the chat, and the bot replies with the group's name. ``migrate_to_chat_id`` moves
  the channel to the supergroup; the bot being removed (``my_chat_member`` left / kicked, or 403 on send) disables it.

Setting a channel up again (or turning ``notify_trades`` back on) moves ``configured_at``: trades created before it are
never pushed.
"""

from __future__ import annotations

import contextlib
import logging
import re
import secrets
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from forliosa.api.errors import ApiError, not_found, unprocessable
from forliosa.config import Settings, get_settings
from forliosa.crypto import encrypt_secret, token_hash
from forliosa.models import Group, GroupChannel, GroupMember, NotificationOutbox, TelegramLinkCode
from forliosa.services import pushers
from forliosa.timeutil import iso_taipei, now_utc

log = logging.getLogger("forliosa.channels")

KINDS = ("discord", "telegram")
LINK_TTL = timedelta(minutes=10)
LINK_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I
LINK_LENGTH = 12
LINK_RE = re.compile(r"^/link(?:@([A-Za-z0-9_]{1,64}))?(?:\s+(\S{1,64}))?\s*$", re.IGNORECASE)
GROUP_CHATS = ("group", "supergroup")


def owner_only(m: GroupMember) -> None:
    if m.role != "owner":
        raise ApiError(403, "forbidden", "只有擁有者可以設定推播頻道")


def _channel(db: Session, group_id: str, kind: str) -> GroupChannel | None:
    return db.get(GroupChannel, (group_id, kind))


def _cancel_pending(db: Session, group_id: str, kind: str, reason: str = "channel_changed") -> None:
    """Pending pushes of a channel that was set up again, removed or disabled are never sent (the rows stay as
    ``cancelled`` until the retention purge, so the same trade is not queued twice)."""
    db.execute(update(NotificationOutbox).where(NotificationOutbox.group_id == group_id,
                                                NotificationOutbox.channel_kind == kind,
                                                NotificationOutbox.status == "pending")
               .values(status="cancelled", last_error=reason))


# -- output ----------------------------------------------------------------------------------------------------
def channels_out(db: Session, group: Group, me: GroupMember, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    out: dict[str, Any] = {}
    for kind in KINDS:
        ch = _channel(db, group.id, kind)
        row: dict[str, Any] = {
            "configured": ch is not None, "status": ch.status if ch else None,
            "disabled_reason": ch.disabled_reason if ch else None,
            "notify_trades": bool(ch.notify_trades) if ch else True,
            "notify_digest": bool(ch.notify_digest) if ch else True,
        }
        if kind == "discord":
            hint = ch.webhook_hint if ch is not None and me.role == "owner" else None
            row["webhook_hint"] = f"…/{hint}" if hint else None
        else:
            row["chat_title"] = ch.chat_title if ch else None
        out[kind] = row
    out["telegram_available"] = settings.telegram_available
    return out


# -- Discord ------------------------------------------------------------------------------------------------------
def connect_message(group: Group) -> str:
    return (f"Forliosa 群組「{group.name}」的推播已連結到這個頻道。之後只有在 Forliosa 打開「推播」的成員，"
            "他們開放的交易動態與週報才會送到這裡。")


def put_discord(db: Session, group: Group, m: GroupMember, webhook_url: str, notify_trades: bool,
                notify_digest: bool) -> None:
    owner_only(m)
    url = pushers.parse_webhook_url(webhook_url)
    if url is None:
        raise unprocessable("Discord webhook 網址格式不正確（要是 https://discord.com/api/webhooks/… 的完整網址）")
    result = pushers.send_discord(url, connect_message(group))
    if not result.ok:
        raise unprocessable("無法送出測試訊息：請確認 webhook 還存在、網址完整，再試一次", code="webhook_failed")
    now = now_utc()
    ch = _channel(db, group.id, "discord")
    if ch is None:
        ch = GroupChannel(group_id=group.id, kind="discord")
        db.add(ch)
    _cancel_pending(db, group.id, "discord")
    ch.status, ch.disabled_reason = "active", None
    ch.webhook_encrypted, ch.webhook_hint = encrypt_secret(url), pushers.webhook_hint(url)
    ch.notify_trades, ch.notify_digest = notify_trades, notify_digest
    ch.configured_by, ch.configured_at, ch.updated_at = m.user_id, now, now
    db.commit()


def patch_channel(db: Session, group: Group, m: GroupMember, kind: str, changes: dict[str, Any]) -> None:
    owner_only(m)
    ch = _channel(db, group.id, kind)
    if ch is None:
        raise not_found("這個頻道還沒有設定")
    now = now_utc()
    if "notify_trades" in changes:
        on = bool(changes["notify_trades"])
        if on and not ch.notify_trades:
            ch.configured_at = now  # trades created while it was off are never pushed
        ch.notify_trades = on
    if "notify_digest" in changes:
        ch.notify_digest = bool(changes["notify_digest"])
    ch.updated_at = now
    db.commit()


def delete_channel(db: Session, group: Group, m: GroupMember, kind: str) -> None:
    owner_only(m)
    _cancel_pending(db, group.id, kind)
    if kind == "telegram":
        db.execute(delete(TelegramLinkCode).where(TelegramLinkCode.group_id == group.id))
    db.execute(delete(GroupChannel).where(GroupChannel.group_id == group.id, GroupChannel.kind == kind))
    db.commit()


def disable(db: Session, ch: GroupChannel, reason: str) -> None:
    """Stop pushing to a channel the service rejected (the owner sets it up again); pending pushes are dropped."""
    ch.status, ch.disabled_reason, ch.updated_at = "disabled", reason, now_utc()
    _cancel_pending(db, ch.group_id, ch.kind, "channel_disabled")
    log.info("group %s: %s channel disabled (%s)", ch.group_id, ch.kind, reason)


# -- Telegram -----------------------------------------------------------------------------------------------------
def new_link_code() -> str:
    return "".join(secrets.choice(LINK_ALPHABET) for _ in range(LINK_LENGTH))


def create_link_code(db: Session, group: Group, m: GroupMember, settings: Settings | None = None) -> dict[str, Any]:
    owner_only(m)
    settings = settings or get_settings()
    if not settings.telegram_available:
        raise ApiError(409, "telegram_unavailable", "伺服器還沒有設定 Telegram bot")
    code = new_link_code()
    now = now_utc()
    db.execute(delete(TelegramLinkCode).where(TelegramLinkCode.group_id == group.id,
                                              TelegramLinkCode.used_at.is_(None)))
    db.add(TelegramLinkCode(code_hash=token_hash(code), group_id=group.id, created_by=m.user_id,
                            expires_at=now + LINK_TTL, created_at=now))
    db.commit()
    return {"code": code, "bot_username": settings.telegram_bot_username, "expires_at": iso_taipei(now + LINK_TTL)}


def _plain(text: str) -> str:
    """User-chosen names in a Telegram message: a full-width ＠ so a name can never mention someone."""
    return text.replace("@", "＠")


def link_chat(db: Session, code: str, chat_id: int, chat_title: str, now: datetime | None = None) -> Group | None:
    """Consume a link code (single use, unexpired, created by the group's current owner) and point the group's
    Telegram channel at this chat. None when the code is not valid."""
    now = now or now_utc()
    row = db.get(TelegramLinkCode, token_hash(code.upper()))
    if row is None or row.used_at is not None or row.expires_at <= now:
        return None
    owner = db.get(GroupMember, (row.group_id, row.created_by))
    group = db.get(Group, row.group_id)
    if group is None or owner is None or owner.role != "owner":
        return None
    used = db.execute(update(TelegramLinkCode).where(TelegramLinkCode.code_hash == row.code_hash,
                                                     TelegramLinkCode.used_at.is_(None)).values(used_at=now)
                      .execution_options(synchronize_session=False))
    if not used.rowcount:
        return None
    ch = _channel(db, group.id, "telegram")
    if ch is None:
        ch = GroupChannel(group_id=group.id, kind="telegram", notify_trades=True, notify_digest=True)
        db.add(ch)
    _cancel_pending(db, group.id, "telegram")
    ch.status, ch.disabled_reason = "active", None
    ch.telegram_chat_id, ch.chat_title = chat_id, (chat_title or "Telegram 群組")[:255]
    ch.configured_by, ch.configured_at, ch.updated_at = row.created_by, now, now
    db.commit()
    return group


def _chat_channels(db: Session, chat_id: int) -> list[GroupChannel]:
    return list(db.scalars(select(GroupChannel).where(GroupChannel.kind == "telegram",
                                                      GroupChannel.telegram_chat_id == chat_id)))


def migrate_chat(db: Session, old_id: int, new_id: int) -> None:
    for ch in _chat_channels(db, old_id):
        ch.telegram_chat_id, ch.updated_at = new_id, now_utc()
    db.commit()


def handle_update(db: Session, token: str, bot_username: str, update_: dict[str, Any],
                  now: datetime | None = None) -> None:
    """One ``getUpdates`` item: ``/link`` commands, supergroup migration, title changes, the bot leaving a chat."""
    now = now or now_utc()
    member_update = update_.get("my_chat_member")
    if isinstance(member_update, dict):
        chat = member_update.get("chat") or {}
        status = (member_update.get("new_chat_member") or {}).get("status")
        if status in ("left", "kicked") and isinstance(chat.get("id"), int):
            for ch in _chat_channels(db, chat["id"]):
                if ch.status == "active":
                    disable(db, ch, "bot_removed")
            db.commit()
        return
    msg = update_.get("message")
    if not isinstance(msg, dict):
        return
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if not isinstance(chat_id, int):
        return
    if msg.get("migrate_to_chat_id") is not None:
        with contextlib.suppress(TypeError, ValueError):
            migrate_chat(db, chat_id, int(msg["migrate_to_chat_id"]))
        return
    if msg.get("new_chat_title"):
        for ch in _chat_channels(db, chat_id):
            ch.chat_title = str(msg["new_chat_title"])[:255]
        db.commit()
        return
    m = LINK_RE.match((msg.get("text") or "").strip())
    if not m:
        return
    addressed_to, code = m.group(1), m.group(2)
    if addressed_to and addressed_to.lower() != bot_username.lower():
        return  # a /link for another bot in the same group
    sent_at = msg.get("date")
    if isinstance(sent_at, int) and now.timestamp() - sent_at > LINK_TTL.total_seconds():
        return  # older than any code can live (e.g. replayed after a restart): stay quiet
    if chat.get("type") not in GROUP_CHATS:
        pushers.send_telegram(token, chat_id, "請先把我加進要接收推播的 Telegram 群組，再在群組裡傳送 /link 連結碼。")
        return
    group = link_chat(db, code, chat_id, str(chat.get("title") or ""), now) if code else None
    if group is None:
        pushers.send_telegram(token, chat_id, "連結碼無效或已過期，請在 Forliosa 的群組設定重新產生。")
        return
    log.info("group %s: Telegram channel linked", group.id)
    pushers.send_telegram(token, chat_id, f"已連結 Forliosa 群組「{_plain(group.name)}」。只有在 Forliosa 打開「推播」"
                                          "的成員，他們開放的交易動態與週報才會送到這裡。")


class TelegramPoller:
    """Polls ``getUpdates`` (no public webhook endpoint). The offset is kept in memory: after a restart Telegram
    resends unconfirmed updates, and ``/link`` messages older than a code's lifetime are ignored."""

    def __init__(self) -> None:
        self.offset: int | None = None

    def poll(self, db: Session, settings: Settings | None = None, now: datetime | None = None) -> int:
        settings = settings or get_settings()
        if not settings.telegram_available or settings.telegram_bot_token is None:
            return 0
        token = settings.telegram_bot_token.get_secret_value()
        result = pushers.telegram_updates(token, self.offset)
        if not result.ok or not isinstance(result.data, list):
            if result.error:
                log.warning("telegram getUpdates failed (%s)", result.error)
            return 0
        handled = 0
        for item in result.data:
            if not isinstance(item, dict) or not isinstance(item.get("update_id"), int):
                continue
            self.offset = max(self.offset or 0, item["update_id"] + 1)
            try:
                handle_update(db, token, settings.telegram_bot_username or "", item, now)
                handled += 1
            except Exception:  # one bad update must not block the others
                db.rollback()
                log.exception("telegram update %s failed", item["update_id"])
        return handled
