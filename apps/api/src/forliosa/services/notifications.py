"""Group push: the notification outbox and its sender (docs/api-contract.md 「分享（M5）」→「推播」). The worker runs
:func:`enqueue_trades` and :func:`send_due` every minute; :func:`enqueue_digest` runs when a weekly digest is ready.

**Trades** (channels with ``notify_trades``): a member's trade is queued only while the member shares both ``trades``
and ``push`` in that group, its trade date is one of the last 3 calendar days (Taipei) and it was created after the
channel was set up and after the member (last) turned on ``push`` and ``trades``. It becomes due 15 minutes after it
was created; right before sending everything is checked again (deleted trade → its row went with it; toggles off,
member gone, channel off → ``cancelled``). One outbox row per transaction and channel (``dedupe_key``), so a trade is
never pushed twice — editing it after it was sent does not send it again. Due rows of the same feed item (member,
day, symbol, side) go out as one message; the price (share-weighted average, no fees) only with ``trade_prices``.

**Digests** (channels with ``notify_digest``): sent once the AI summary is ``ready``, with only the numbers of members
who push (:func:`sharing.digest_facts_view` with ``pushing_only``); the summary itself only while every member whose
numbers went into it still pushes (:func:`sharing.digest_summary_pushable`).

**Text**: every dynamic value (display names, the group name, instrument names, the AI summary) goes through
:func:`pushers.user_text` — one line, Discord markdown escaped, Telegram ``@`` as ＠ — so a name can never add a line,
a masked link or other formatting to a message.

**Delivery**: up to 5 attempts with exponential backoff (1, 2, 4, 8 minutes, or Discord's / Telegram's
``retry_after`` when longer); 401 / 404 from a Discord webhook, 403 or "chat not found" from Telegram → the channel is
disabled (``disabled_reason``) and its pending rows dropped. Errors are stored as short labels, never URLs.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from forliosa.config import Settings, get_settings
from forliosa.crypto import decrypt_secret
from forliosa.ids import new_id
from forliosa.marketdata.service import MarketData
from forliosa.models import Group, GroupChannel, GroupDigest, NotificationOutbox, TelegramLinkCode, Transaction
from forliosa.services import channels, pushers, sharing
from forliosa.services.pushers import SendResult
from forliosa.timeutil import now_utc

log = logging.getLogger("forliosa.notifications")

MAX_ATTEMPTS = 5
BACKOFF = timedelta(minutes=1)  # waits after failures 1–4: 1, 2, 4, 8 minutes; the 5th failure is final
SEND_BATCH = 200
OUTBOX_RETENTION = timedelta(days=30)
LINK_CODE_RETENTION = timedelta(days=1)
SIDE_LABEL = {"buy": "買進", "sell": "賣出"}
DISCLAIMER = "AI 分析僅供參考，不構成投資建議。"


# -- queueing --------------------------------------------------------------------------------------------------
def trade_key(group_id: str, kind: str, transaction_id: str) -> str:
    return f"trade:{group_id}:{kind}:{transaction_id}"


def enqueue_trades(db: Session, now: datetime | None = None) -> int:
    """Queue the trades that may be pushed (see the module docstring); each one once per channel."""
    now = now or now_utc()
    by_group: dict[str, list[GroupChannel]] = defaultdict(list)
    for ch in db.scalars(select(GroupChannel).where(GroupChannel.status == "active",
                                                    GroupChannel.notify_trades.is_(True))):
        by_group[ch.group_id].append(ch)
    added = 0
    for group_id, chs in by_group.items():
        candidates = sharing.push_trade_candidates(db, sharing.members_of(db, group_id), now)
        if not candidates:
            continue
        keys = [trade_key(group_id, ch.kind, t.id) for ch in chs for _, t in candidates]
        existing = set(db.scalars(select(NotificationOutbox.dedupe_key)
                                  .where(NotificationOutbox.dedupe_key.in_(keys))))
        for ch in chs:
            for member, t in candidates:
                start = sharing.push_start(member, ch.configured_at)
                key = trade_key(group_id, ch.kind, t.id)
                if start is None or t.created_at <= start or key in existing:
                    continue
                db.add(NotificationOutbox(
                    id=new_id("ntf"), group_id=group_id, channel_kind=ch.kind, kind="trade", dedupe_key=key,
                    user_id=member.user_id, transaction_id=t.id, status="pending", attempts=0,
                    not_before=t.created_at + sharing.PUSH_DELAY, created_at=now))
                existing.add(key)
                added += 1
    db.commit()
    return added


def enqueue_digest(db: Session, digest: GroupDigest, now: datetime | None = None) -> int:
    """Queue a ready digest for the group's channels that take digests."""
    now = now or now_utc()
    added = 0
    for ch in db.scalars(select(GroupChannel).where(GroupChannel.group_id == digest.group_id,
                                                    GroupChannel.status == "active",
                                                    GroupChannel.notify_digest.is_(True))):
        key = f"digest:{digest.id}:{ch.kind}"
        if db.scalar(select(NotificationOutbox.id).where(NotificationOutbox.dedupe_key == key)):
            continue
        db.add(NotificationOutbox(id=new_id("ntf"), group_id=digest.group_id, channel_kind=ch.kind, kind="digest",
                                  dedupe_key=key, digest_id=digest.id, status="pending", attempts=0,
                                  not_before=now, created_at=now))
        added += 1
    db.commit()
    return added


# -- message text (plain text: Discord markdown escaped in every dynamic value, no parse_mode on Telegram) --------
def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:+.2f}%"


def _price(value: float) -> str:
    return f"{value:,.2f}" if round(value, 2) == value else f"{value:,.4f}".rstrip("0")


def _code(symbol: str) -> str:
    return symbol.split(".", 1)[0]


def _link(settings: Settings) -> str | None:
    """The group page, only with an explicit FRONTEND_URL (or in development): never a guessed address."""
    if settings.frontend_url or settings.is_dev:
        return f"{settings.frontend_base}/groups"
    return None


def _t(text: Any, kind: str) -> str:
    """Names and other text from users or data sources (not the numbers formatted here): one line, Discord markdown
    escaped, Telegram ＠."""
    return pushers.user_text(str(text), kind)


def trade_text(group: Group, view: dict[str, Any], kind: str, settings: Settings) -> str:
    d = view["trade_date"]
    line2 = [f"{d.month}/{d.day}"]
    if view["count"] > 1:
        line2.append(f"共 {view['count']} 筆")
    if "price" in view and view["price"] is not None:
        line2.append(f"成交均價 {_price(view['price'])} {view['currency']}")
    return "\n".join([
        f"{_t(view['display_name'], kind)} {SIDE_LABEL.get(view['side'], view['side'])} "
        f"{_t(view['name'], kind)}（{_t(_code(view['symbol']), kind)}）",
        "・".join(line2),
        " ".join(x for x in (f"— Forliosa 群組「{_t(group.name, kind)}」", _link(settings)) if x),
    ])


def digest_text(group: Group, digest: GroupDigest, view: dict[str, Any], summary: str | None, kind: str,
                settings: Settings) -> str:
    ws, we = digest.week_start, digest.week_end
    lines = [f"Forliosa 群組「{_t(group.name, kind)}」週報（{ws.month}/{ws.day}–{we.month}/{we.day}）"]
    if summary:
        lines.append(_t(summary, kind))
    if view["returns"]:
        lines.append("本週報酬：" + "、".join(f"{_t(r['display_name'], kind)} {_pct(r['week_return_pct'])}"
                                         for r in view["returns"]))
    if view["benchmarks"]:
        lines.append("對照：" + "、".join(f"{_t(b['name'], kind)} {_pct(b['week_return_pct'])}"
                                       for b in view["benchmarks"]))
    if view["common_holdings"]:
        lines.append("共同持股：" + "、".join(f"{_t(c['name'], kind)}（{c['holder_count']} 人）"
                                         for c in view["common_holdings"][:5]))
    if view["trades_count"]:
        lines.append(f"本週交易動態：{view['trades_count']} 筆")
    link = _link(settings)
    if link:
        lines.append(f"完整週報：{link}")
    if summary:
        lines.append(DISCLAIMER)
    return "\n".join(lines)


# -- sending --------------------------------------------------------------------------------------------------------
def _deliver(db: Session, ch: GroupChannel, text: str, settings: Settings) -> SendResult:
    if ch.kind == "discord":
        url = decrypt_secret(ch.webhook_encrypted) if ch.webhook_encrypted else None
        if url is None:  # SESSION_SECRET was rotated: the owner sets the channel again
            return SendResult(False, "undecryptable", disable="webhook_unreadable")
        return pushers.send_discord(url, text)
    if not settings.telegram_available or settings.telegram_bot_token is None or ch.telegram_chat_id is None:
        return SendResult(False, "telegram_unavailable", retry=True)
    token = settings.telegram_bot_token.get_secret_value()
    result = pushers.send_telegram(token, ch.telegram_chat_id, text)
    if result.migrate_to is not None:  # the group became a supergroup: follow it and send once more
        channels.migrate_chat(db, ch.telegram_chat_id, result.migrate_to)
        result = pushers.send_telegram(token, result.migrate_to, text)
    return result


def _cancel(rows: list[NotificationOutbox], reason: str) -> None:
    for r in rows:
        r.status, r.last_error = "cancelled", reason


def _apply(db: Session, ch: GroupChannel, rows: list[NotificationOutbox], result: SendResult, now: datetime) -> None:
    for r in rows:
        r.attempts += 1
        if result.ok:
            r.status, r.sent_at, r.last_error = "sent", now, None
            continue
        r.last_error = result.error
        if result.retry and not result.disable and r.attempts < MAX_ATTEMPTS:
            wait = BACKOFF * (2 ** (r.attempts - 1))
            if result.retry_after is not None:
                wait = max(wait, timedelta(seconds=result.retry_after))
            r.not_before = now + wait
        else:
            r.status = "failed"
    if result.disable:
        db.flush()  # these rows are no longer pending; disabling cancels the channel's other pending rows
        channels.disable(db, ch, result.disable)
    if not result.ok:
        log.info("group %s: %s push failed (%s)", ch.group_id, ch.kind, result.error)


def _channel_ok(ch: GroupChannel | None, flag: str) -> bool:
    return ch is not None and ch.status == "active" and bool(getattr(ch, flag))


def _send_trades(db: Session, md: MarketData, settings: Settings, group_id: str, kind: str,
                 items: list[tuple[NotificationOutbox, Transaction]], now: datetime) -> None:
    ch = db.get(GroupChannel, (group_id, kind))
    group = db.get(Group, group_id)
    if group is None or ch is None or not _channel_ok(ch, "notify_trades"):
        _cancel([r for r, _ in items], "channel_off")
        return
    user_id = items[0][1].user_id
    member = next((m for m in sharing.members_of(db, group_id) if m.user_id == user_id), None)
    ok = [(r, t) for r, t in items
          if member is not None and sharing.still_pushable(db, member, t, ch.configured_at, now)]
    _cancel([r for r, t in items if (r, t) not in ok], "not_shared")
    if not ok or member is None:
        return
    text = trade_text(group, sharing.push_trade_view(md, member, [t for _, t in ok]), kind, settings)
    _apply(db, ch, [r for r, _ in ok], _deliver(db, ch, text, settings), now)


def _send_digest(db: Session, settings: Settings, row: NotificationOutbox, now: datetime) -> None:
    ch = db.get(GroupChannel, (row.group_id, row.channel_kind))
    group = db.get(Group, row.group_id)
    digest = db.get(GroupDigest, row.digest_id) if row.digest_id else None
    if group is None or ch is None or not _channel_ok(ch, "notify_digest"):
        _cancel([row], "channel_off")
        return
    if digest is None or digest.status != "ready":
        _cancel([row], "not_ready")
        return
    members = sharing.members_of(db, group.id)
    if not any(m.shares("push") for m in members):
        _cancel([row], "not_shared")
        return
    view = sharing.digest_facts_view(digest.facts or {}, members, pushing_only=True)
    summary = digest.summary if sharing.digest_summary_pushable(digest.facts or {}, members) else None
    text = digest_text(group, digest, view, summary, ch.kind, settings)
    _apply(db, ch, [row], _deliver(db, ch, text, settings), now)


def send_due(db: Session, md: MarketData, settings: Settings | None = None, now: datetime | None = None) -> int:
    """Send every due pending row (re-checking what may be shown). Returns the number of rows handled."""
    settings = settings or get_settings()
    now = now or now_utc()
    rows = list(db.scalars(select(NotificationOutbox).where(NotificationOutbox.status == "pending",
                                                            NotificationOutbox.not_before <= now)
                           .order_by(NotificationOutbox.not_before, NotificationOutbox.created_at,
                                     NotificationOutbox.id).limit(SEND_BATCH)))
    trades: dict[tuple, list[tuple[NotificationOutbox, Transaction]]] = defaultdict(list)
    digests: list[NotificationOutbox] = []
    for r in rows:
        if r.kind == "digest":
            digests.append(r)
            continue
        t = db.get(Transaction, r.transaction_id) if r.kind == "trade" and r.transaction_id else None
        if t is None:
            _cancel([r], "gone")
            continue
        trades[(r.group_id, r.channel_kind, t.user_id, t.trade_date, t.symbol, t.type)].append((r, t))
    for (group_id, kind, *_), items in trades.items():
        if all(r.status == "pending" for r, _ in items):  # a channel disabled meanwhile cancelled its rows
            _send_trades(db, md, settings, group_id, kind, items, now)
    for r in digests:
        if r.status == "pending":
            _send_digest(db, settings, r, now)
    db.commit()
    return len(rows)


# -- retention ------------------------------------------------------------------------------------------------------
def purge_old(db: Session, now: datetime | None = None) -> int:
    """Finished outbox rows after 30 days (they only guard against sending twice within the 3-day window) and link
    codes a day after they expired."""
    now = now or now_utc()
    n = db.execute(delete(NotificationOutbox).where(NotificationOutbox.created_at < now - OUTBOX_RETENTION)).rowcount
    n += db.execute(delete(TelegramLinkCode).where(TelegramLinkCode.expires_at < now - LINK_CODE_RETENTION)).rowcount
    db.commit()
    return n or 0
