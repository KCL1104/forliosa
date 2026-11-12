"""Group push channels: one Discord webhook and one Telegram group chat per group (docs/api-contract.md 「分享（M5）」→
「推播」). Only the owner configures them; every member sees where the group pushes (``Group.push_targets``,
``GET /groups/{id}/channels``), and only the owner sees the webhook's last 4 characters.

* **Discord**: the URL is validated strictly (``pushers.parse_webhook_url``), a test message is sent *before* saving
  (any failure → 422 ``webhook_failed``), and the URL is stored encrypted (``crypto.encrypt_secret``); responses show
  only ``…/abcd``. The URL is never logged or echoed in an error. Every test message is a live request to Discord, so
  setting a webhook is limited to :data:`SETUP_LIMIT` attempts per user and per group in 10 minutes (429
  ``rate_limited``; process-local), and nothing is sent while ``pushers``' circuit breaker is open (429 too).
* **Telegram**: the owner asks for a one-time link code (12 characters from a 32-symbol alphabet = 60 bits, 10 minutes,
  only its SHA-256 stored; a new code replaces the group's unused ones) and sends ``/link <code>`` (or
  ``/link@<bot> <code>``) in the Telegram group. The worker polls ``getUpdates`` (:class:`TelegramPoller`; there is no
  public webhook endpoint), links the chat, and the bot replies with the group's name. ``migrate_to_chat_id`` moves
  the channel to the supergroup; the bot being removed (``my_chat_member`` left / kicked, or 403 on send) disables it.
  The poller drains the backlog within a time budget, ignores everything but ``/link`` before doing any work, and
  answers a failed ``/link`` at most once per chat per minute.

Setting a channel up again (or turning ``notify_trades`` back on) moves ``configured_at``: trades created before it are
never pushed.

**A new destination needs everyone's consent again**: when the owner points a channel somewhere else — a Discord webhook
with a different id, a different Telegram chat, or any destination after the channel was removed — every *other*
member's ``push`` toggle is turned off (the owner who set it keeps theirs); they see the new target in
``push_targets`` and turn ``push`` on again if they agree. The same webhook or chat set up again (and a supergroup
migration) is the same destination. A removed channel keeps its row as ``status = "removed"`` (no URL, no chat id) so a
later set-up is recognised as new; it is shown as not configured.
"""

from __future__ import annotations

import contextlib
import logging
import re
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from forliosa.api.errors import ApiError, not_found, unprocessable
from forliosa.config import Settings, get_settings
from forliosa.crypto import decrypt_secret, encrypt_secret, token_hash
from forliosa.models import Group, GroupChannel, GroupMember, GroupShareSetting, NotificationOutbox, TelegramLinkCode
from forliosa.services import pushers
from forliosa.textsafe import one_line
from forliosa.timeutil import iso_taipei, now_utc

log = logging.getLogger("forliosa.channels")

KINDS = ("discord", "telegram")
LINK_TTL = timedelta(minutes=10)
LINK_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I
LINK_LENGTH = 12
LINK_RE = re.compile(r"^/link(?:@([A-Za-z0-9_]{1,64}))?(?:\s+(\S{1,64}))?\s*$", re.IGNORECASE)
GROUP_CHATS = ("group", "supergroup")
REMOVED = "removed"
SETUP_LIMIT = 5  # Discord webhook set-ups (each one sends a test message) per user and per group …
SETUP_WINDOW_SECONDS = 600.0  # … in 10 minutes
POLL_BUDGET_SECONDS = 8.0  # one telegram_poll: getUpdates pages and their handling
POLL_MAX_PAGES = 10
REPLY_COOLDOWN_SECONDS = 60.0  # at most one "invalid code" / "add me to a group" answer per chat per minute
MAX_REPLIES_PER_POLL = 10


class SlidingLimit:
    """At most ``limit`` hits per key in a sliding window (process-local; a hit counts for every key at once)."""

    def __init__(self, limit: int, window: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit, self.window, self.clock = limit, window, clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque[float]:
        q = self._hits.get(key) or deque()
        while q and q[0] <= now - self.window:
            q.popleft()
        return q

    def hit(self, keys: Iterable[str]) -> bool:
        """Count one attempt for every key; False (nothing counted) when any key is at its limit."""
        keys = list(keys)
        with self._lock:
            now = self.clock()
            queues = {k: self._recent(k, now) for k in keys}
            if any(len(q) >= self.limit for q in queues.values()):
                return False
            for k, q in queues.items():
                q.append(now)
                self._hits[k] = q
            if len(self._hits) > 10_000:  # forget keys with no recent attempt
                self._hits = {k: q for k, q in self._hits.items() if q and q[-1] > now - self.window}
            return True


webhook_setups = SlidingLimit(SETUP_LIMIT, SETUP_WINDOW_SECONDS)


def reset_state() -> None:
    """Tests: forget the set-up attempts."""
    global webhook_setups
    webhook_setups = SlidingLimit(SETUP_LIMIT, SETUP_WINDOW_SECONDS)


def owner_only(m: GroupMember) -> None:
    if m.role != "owner":
        raise ApiError(403, "forbidden", "只有擁有者可以設定推播頻道")


def _channel(db: Session, group_id: str, kind: str) -> GroupChannel | None:
    """The group's channel of this kind, also when it was removed (``status = "removed"``)."""
    return db.get(GroupChannel, (group_id, kind))


def _configured(db: Session, group_id: str, kind: str) -> GroupChannel | None:
    ch = _channel(db, group_id, kind)
    return None if ch is None or ch.status == REMOVED else ch


def _reset_others_push(db: Session, group_id: str, keep_user_id: str | None, now: datetime) -> None:
    """A new destination: every other member's ``push`` goes off until they turn it on again for this target."""
    db.execute(update(GroupShareSetting).where(GroupShareSetting.group_id == group_id,
                                               GroupShareSetting.user_id != (keep_user_id or ""),
                                               GroupShareSetting.push.is_(True))
               .values(push=False, updated_at=now))


def _webhook_id(ch: GroupChannel) -> str | None:
    if ch.status == REMOVED or not ch.webhook_encrypted:
        return None
    url = decrypt_secret(ch.webhook_encrypted)
    return pushers.webhook_id(url) if url else None


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
        ch = _configured(db, group.id, kind)
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
    return (f"Forliosa 群組「{pushers.user_text(group.name, 'discord')}」的推播已連結到這個頻道。之後只有在 Forliosa "
            "打開「推播」的成員，他們開放的交易動態與週報才會送到這裡。")


def put_discord(db: Session, group: Group, m: GroupMember, webhook_url: str, notify_trades: bool,
                notify_digest: bool) -> None:
    owner_only(m)
    url = pushers.parse_webhook_url(webhook_url)
    if url is None:
        raise unprocessable("Discord webhook 網址格式不正確（要是 https://discord.com/api/webhooks/… 的完整網址）")
    if not webhook_setups.hit((f"user:{m.user_id}", f"group:{group.id}")):
        raise ApiError(429, "rate_limited", "Discord webhook 設定得太頻繁，請 10 分鐘後再試")
    result = pushers.send_discord(url, connect_message(group))
    if result.error == "paused":
        raise ApiError(429, "rate_limited", "暫時無法連到 Discord，請 10 分鐘後再試")
    if not result.ok:
        raise unprocessable("無法送出測試訊息：請確認 webhook 還存在、網址完整，再試一次", code="webhook_failed")
    now = now_utc()
    ch = _channel(db, group.id, "discord")
    if ch is None:
        ch = GroupChannel(group_id=group.id, kind="discord")
        db.add(ch)
    elif _webhook_id(ch) != pushers.webhook_id(url):
        _reset_others_push(db, group.id, m.user_id, now)
    _cancel_pending(db, group.id, "discord")
    ch.status, ch.disabled_reason = "active", None
    ch.webhook_encrypted, ch.webhook_hint = encrypt_secret(url), pushers.webhook_hint(url)
    ch.notify_trades, ch.notify_digest = notify_trades, notify_digest
    ch.configured_by, ch.configured_at, ch.updated_at = m.user_id, now, now
    db.commit()


def patch_channel(db: Session, group: Group, m: GroupMember, kind: str, changes: dict[str, Any]) -> None:
    owner_only(m)
    ch = _configured(db, group.id, kind)
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
    """Remove a channel: pending pushes cancelled, the URL / chat id forgotten; the row stays as ``removed`` so that
    setting one up later counts as a new destination."""
    owner_only(m)
    _cancel_pending(db, group.id, kind)
    if kind == "telegram":
        db.execute(delete(TelegramLinkCode).where(TelegramLinkCode.group_id == group.id))
    ch = _channel(db, group.id, kind)
    if ch is not None:
        ch.status, ch.disabled_reason, ch.updated_at = REMOVED, None, now_utc()
        ch.webhook_encrypted = ch.webhook_hint = None
        ch.telegram_chat_id, ch.chat_title = None, None
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
    else:
        if ch.telegram_chat_id != chat_id:  # another chat, or set up again after it was removed
            _reset_others_push(db, group.id, row.created_by, now)
        if ch.status == REMOVED:
            ch.notify_trades, ch.notify_digest = True, True
    _cancel_pending(db, group.id, "telegram")
    ch.status, ch.disabled_reason = "active", None
    ch.telegram_chat_id, ch.chat_title = chat_id, (one_line(chat_title) or "Telegram 群組")[:255]
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
                  now: datetime | None = None, may_reply: Callable[[int], bool] = lambda _chat_id: True) -> None:
    """One ``getUpdates`` item: ``/link`` commands, supergroup migration, title changes, the bot leaving a chat.
    Anything else (any other text, in a group or a private chat) is ignored before any work. ``may_reply(chat_id)``
    decides whether a failed ``/link`` is answered (the poller throttles those answers)."""
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
            ch.chat_title = (one_line(str(msg["new_chat_title"])) or "Telegram 群組")[:255]
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
        if may_reply(chat_id):
            pushers.send_telegram(token, chat_id,
                                  "請先把我加進要接收推播的 Telegram 群組，再在群組裡傳送 /link 連結碼。")
        return
    group = link_chat(db, code, chat_id, str(chat.get("title") or ""), now) if code else None
    if group is None:
        if may_reply(chat_id):
            pushers.send_telegram(token, chat_id, "連結碼無效或已過期，請在 Forliosa 的群組設定重新產生。")
        return
    log.info("group %s: Telegram channel linked", group.id)
    pushers.send_telegram(token, chat_id, f"已連結 Forliosa 群組「{pushers.user_text(group.name, 'telegram')}」。"
                                          "只有在 Forliosa 打開「推播」的成員，他們開放的交易動態與週報才會送到這裡。")


class TelegramPoller:
    """Polls ``getUpdates`` (no public webhook endpoint). The offset is kept in memory: after a restart Telegram
    resends unconfirmed updates, and ``/link`` messages older than a code's lifetime are ignored.

    One :meth:`poll` drains the backlog page by page (up to :data:`POLL_MAX_PAGES` pages of 100) within
    :data:`POLL_BUDGET_SECONDS`; updates it did not reach stay unconfirmed and come again next time. Answers to failed
    ``/link`` commands (private chats, invalid codes) go out at most once per chat per minute and at most
    :data:`MAX_REPLIES_PER_POLL` per poll, so a flood of messages cannot turn into a flood of blocking replies."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.offset: int | None = None
        self.clock = clock
        self._replied: dict[int, float] = {}
        self._replies_left = MAX_REPLIES_PER_POLL

    def _may_reply(self, chat_id: int) -> bool:
        now = self.clock()
        last = self._replied.get(chat_id)
        if self._replies_left <= 0 or (last is not None and now - last < REPLY_COOLDOWN_SECONDS):
            return False
        self._replies_left -= 1
        self._replied[chat_id] = now
        if len(self._replied) > 10_000:
            self._replied = {c: t for c, t in self._replied.items() if now - t < REPLY_COOLDOWN_SECONDS}
        return True

    def poll(self, db: Session, settings: Settings | None = None, now: datetime | None = None) -> int:
        settings = settings or get_settings()
        if not settings.telegram_available or settings.telegram_bot_token is None:
            return 0
        token = settings.telegram_bot_token.get_secret_value()
        started = self.clock()
        self._replies_left = MAX_REPLIES_PER_POLL
        handled = 0
        for _page in range(POLL_MAX_PAGES):
            result = pushers.telegram_updates(token, self.offset)
            if not result.ok or not isinstance(result.data, list):
                if result.error:
                    log.warning("telegram getUpdates failed (%s)", result.error)
                break
            for item in result.data:
                if self.clock() - started > POLL_BUDGET_SECONDS:
                    return handled  # the rest stay unconfirmed: the next poll gets them again
                if not isinstance(item, dict) or not isinstance(item.get("update_id"), int):
                    continue
                self.offset = max(self.offset or 0, item["update_id"] + 1)
                try:
                    handle_update(db, token, settings.telegram_bot_username or "", item, now, self._may_reply)
                    handled += 1
                except Exception:  # one bad update must not block the others
                    db.rollback()
                    log.exception("telegram update %s failed", item["update_id"])
            if len(result.data) < pushers.TELEGRAM_UPDATES_LIMIT or self.clock() - started > POLL_BUDGET_SECONDS:
                break
        return handled
