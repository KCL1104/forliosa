"""Group push: the notification outbox and its sender (docs/api-contract.md 「分享（M5）」→「推播」). The worker runs
:func:`enqueue_trades` and :func:`send_due` every minute; :func:`enqueue_digest` runs when a weekly digest is ready.

**Trades** (channels with ``notify_trades``): a member's trade is queued only while the member shares both ``trades``
and ``push`` in that group, its trade date is one of the last 3 calendar days (Taipei) and it was created after the
channel was set up and after the member (last) turned on ``push`` and ``trades``. It becomes due 15 minutes after it
was created; right before sending everything is checked again (deleted trade → its row went with it; toggles off,
member gone, channel off → ``cancelled``). One outbox row per transaction and channel (``dedupe_key``), so a trade is
never pushed twice — editing it after it was sent does not send it again. Due rows of the same feed item (member,
day, symbol, side) go out as one message; the price (share-weighted average, no fees) only with ``trade_prices``.

**Four switches per channel** (產品負責人 2026-11-18, option A; ``forliosa.reports.push``): 交易動態
(``notify_trades``), 盤前 (``notify_premarket``), 盤後 (``notify_close``) and 週報 (``notify_weekly``). The group's
daily report rides on 盤前 and its weekly digest on 週報 — in the market report's message when there is one, else
alone at the same time. ``notify_digest`` / ``notify_daily`` are no longer read (kept in the table for a safe
downgrade; the API maps writes of them onto ``notify_weekly`` / ``notify_premarket``).

**Digests** (channels with ``notify_weekly``): due on Sunday 18:00 after their week (``push.digest_due``; held to 21:30
only while that Sunday's 市場週報 push may still come for the channel, ``push.market_coming``), once the AI summary is
``ready``, with only the numbers of members who push (:func:`sharing.digest_facts_view` with ``pushing_only``); the
summary itself only while every member whose numbers went into it still pushes
(:func:`sharing.digest_summary_pushable`).

**Daily reports** (群組 AI 日報 of boosted groups; channels with ``notify_premarket``): queued when a report is
finished, due at 07:30 of the next Taiwan trading day (``push.daily_due``; held to 08:20 only while that day's 盤前重點
push may still come for the channel; at once when it finished later). The text has only the numbers of members who push
(:func:`sharing.daily_facts_view` with ``pushing_only``), only trades still there and created after the member's push
start (like trade pushes), and the AI paragraph only while every member whose numbers went into it still pushes and
every trade it counted is still sent. Sent after the trading day it says 當日報酬／那天的買賣 instead of 今日／今天.

Both are re-timed when they come due (rows queued before 2026-11-18 under the old times follow the new ones); whether
to hold them is asked at 07:30 / 18:00 about that one edition, so an admin-only edition, a push that already went,
reports paused or off never hold them. A group part that a market push already took in (its row
marked ``merged``) is never sent again. Setting a channel up again or a channel disabled does not cancel them (the
pushing members are checked again when they go).

**Market reports** (``kind="mreport"``, 市場報告 2026-11-17; ``forliosa.reports.push``): channels with
``notify_premarket`` / ``notify_close`` / ``notify_weekly``, only while the reports' mode is public. Sent before the
group's other rows of the same run: the 盤前 push takes in the group's daily report of the previous session, the 週報
push the weekly digest.

**Text**: every dynamic value (display names, the group name, instrument names, the AI summary) goes through
:func:`pushers.user_text` — one line, Discord markdown escaped, Telegram ``@`` as ＠ — so a name can never add a line,
a masked link or other formatting to a message. Every message ends with the site's short disclaimer
(:data:`forliosa.disclaimer.SHORT`, product owner 2026-11-17), exactly once.

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

from forliosa import disclaimer
from forliosa.config import Settings, get_settings
from forliosa.crypto import decrypt_secret
from forliosa.ids import new_id
from forliosa.marketdata.service import MarketData
from forliosa.models import (
    Group,
    GroupChannel,
    GroupDailyReport,
    GroupDigest,
    NotificationOutbox,
    TelegramLinkCode,
    Transaction,
)
from forliosa.services import channels, pushers, sharing
from forliosa.services.pushers import SendResult
from forliosa.timeutil import TAIPEI, now_utc

log = logging.getLogger("forliosa.notifications")

MAX_ATTEMPTS = 5
BACKOFF = timedelta(minutes=1)  # waits after failures 1–4: 1, 2, 4, 8 minutes; the 5th failure is final
SEND_BATCH = 200
OUTBOX_RETENTION = timedelta(days=30)
LINK_CODE_RETENTION = timedelta(days=1)
SIDE_LABEL = {"buy": "買進", "sell": "賣出"}
# The ``disclaimer`` field of weekly digests and daily reports (under their AI summary on the group page).
DISCLAIMER = disclaimer.AI
# The last line of every push (trades, digests, daily reports): what Forliosa is and is not.
PUSH_DISCLAIMER = disclaimer.SHORT


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
    """Queue a ready digest for the group's channels with 週報 on: due on Sunday 18:00 after its week (then held to
    21:30 when that Sunday's 市場週報 push may still take it in, :func:`_send_digest`); a row the market push already
    added as ``merged`` is not queued again."""
    from forliosa.reports.push import digest_due, digest_key

    now = now or now_utc()
    added = 0
    due = digest_due(digest.week_end, digest.finished_at or now, False)
    for ch in db.scalars(select(GroupChannel).where(GroupChannel.group_id == digest.group_id,
                                                    GroupChannel.status == "active",
                                                    GroupChannel.notify_weekly.is_(True))):
        key = digest_key(digest.id, ch.kind)
        if db.scalar(select(NotificationOutbox.id).where(NotificationOutbox.dedupe_key == key)):
            continue
        db.add(NotificationOutbox(id=new_id("ntf"), group_id=digest.group_id, channel_kind=ch.kind, kind="digest",
                                  dedupe_key=key, digest_id=digest.id, status="pending", attempts=0,
                                  not_before=due, created_at=now))
        added += 1
    db.commit()
    return added


def enqueue_daily(db: Session, report: GroupDailyReport, now: datetime | None = None) -> int:
    """Queue a finished daily report for the group's channels with 盤前 on: due at 07:30 of the next trading day (then
    held to 08:20 when that day's 盤前重點 push may still take it in, :func:`_send_daily`), at once when it finished
    later than that."""
    from forliosa.reports.push import daily_due, daily_key

    now = now or now_utc()
    added = 0
    due = daily_due(report.trading_day, report.finished_at or now, False)
    for ch in db.scalars(select(GroupChannel).where(GroupChannel.group_id == report.group_id,
                                                    GroupChannel.status == "active",
                                                    GroupChannel.notify_premarket.is_(True))):
        key = daily_key(report.id, ch.kind)
        if db.scalar(select(NotificationOutbox.id).where(NotificationOutbox.dedupe_key == key)):
            continue
        db.add(NotificationOutbox(id=new_id("ntf"), group_id=report.group_id, channel_kind=ch.kind, kind="daily",
                                  dedupe_key=key, daily_report_id=report.id, status="pending", attempts=0,
                                  not_before=due, created_at=now))
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


def signed(lines: list[str], kind: str, *, ai: bool = False) -> str:
    """A push / channel message: ``lines`` joined by newlines, then the site's disclaimer (:data:`PUSH_DISCLAIMER`,
    ``disclaimer.SHORT``) as the last line, exactly once.

    * ``kind``: ``"discord"`` or ``"telegram"`` (sets the length limit).
    * ``ai``: the message carries an AI-written paragraph. Start that line with ``disclaimer.AI_LABEL``
      (「AI 整理：」, see :func:`ai_line`); the last line then starts with ``disclaimer.AI_NOTE``
      (「AI 整理的部分可能有錯。」).
    * Discord (2,000) and Telegram (4,096) cut a long message at the end (``pushers``): a body too long for the
      channel is shortened first (ending in …), so the last line always arrives.

    Every push uses this (trades, weekly digests, daily reports; other features' pushes too, e.g. market reports):
    never append a disclaimer string by hand.
    """
    limit = pushers.DISCORD_MAX_CHARS if kind == "discord" else pushers.TELEGRAM_MAX_CHARS
    last = disclaimer.AI_NOTE + PUSH_DISCLAIMER if ai else PUSH_DISCLAIMER
    body = "\n".join(lines)
    room = limit - len(last) - 1
    if len(body) > room:
        body = body[:room - 1] + "…"
    return f"{body}\n{last}"


_signed = signed  # the name before the 2026-11-17 review; kept for branches that started from it — use ``signed``


def ai_line(text: str, kind: str) -> str:
    """An AI-written paragraph in a push: 「AI 整理：」 then the text (one line, escaped like other dynamic text).
    Pass ``ai=True`` to :func:`signed` for the same message."""
    return disclaimer.AI_LABEL + _t(text, kind)


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
    return signed([
        f"{_t(view['display_name'], kind)} {SIDE_LABEL.get(view['side'], view['side'])} "
        f"{_t(view['name'], kind)}（{_t(_code(view['symbol']), kind)}）",
        "・".join(line2),
        " ".join(x for x in (f"— Forliosa 群組「{_t(group.name, kind)}」", _link(settings)) if x),
    ], kind)


def digest_text(group: Group, digest: GroupDigest, view: dict[str, Any], summary: str | None, kind: str,
                settings: Settings) -> str:
    ws, we = digest.week_start, digest.week_end
    lines = [f"Forliosa 群組「{_t(group.name, kind)}」週報（{ws.month}/{ws.day}–{we.month}/{we.day}）"]
    if summary:
        lines.append(ai_line(summary, kind))
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
    return signed(lines, kind, ai=bool(summary))


DAILY_MAX_RETURNS = 20  # a channel message lists this many members' returns (Discord cuts at 2,000 characters)
DAILY_MAX_TRADES = 10


def daily_text(group: Group, report: GroupDailyReport, view: dict[str, Any], summary: str | None, kind: str,
               settings: Settings, same_day: bool = True) -> str:
    """The memo's format: a title line, the AI paragraph, then the numbers (one decimal, −), the link and the note.
    ``same_day``: sent on the trading day itself (今日報酬, 今天的買賣); else 當日報酬, 那天的買賣."""
    from forliosa.services.group_daily import pct1, weekday

    d = report.trading_day
    day_word, trades_word = ("今日", "今天") if same_day else ("當日", "那天")
    lines = [f"Forliosa 群組「{_t(group.name, kind)}」日報　{d.month}/{d.day}（{weekday(d)}）收盤"]
    if summary:
        lines.append(ai_line(summary, kind))
    returns = view["returns"]
    if returns:
        shown = "、".join(f"{_t(r['display_name'], kind)} {pct1(r['day_return_pct'], '−')}"
                         for r in returns[:DAILY_MAX_RETURNS])
        more = f" 等 {len(returns)} 人" if len(returns) > DAILY_MAX_RETURNS else ""
        lines.append(f"{day_word}報酬：{shown}{more}")
    bench = [b for b in view["benchmarks"] if b.get("day_return_pct") is not None]
    if bench:
        lines.append("對照：" + "、".join(f"{_t(b['name'], kind)} {pct1(b['day_return_pct'], '−')}" for b in bench))
    if view["common_holdings"]:
        lines.append("共同持股：" + "、".join(
            f"{_t(c['name'], kind)}（{c['holder_count']} 人）"
            + (f"{pct1(c['day_change_pct'], '−')}" if c.get("day_change_pct") is not None else "")
            for c in view["common_holdings"][:5]))
    if view["trades"]:
        items = [f"{SIDE_LABEL.get(t['side'], t['side'])} {_t(t['name'], kind)}"
                 + (f"（{t['count']} 筆）" if t["count"] > 1 else "") for t in view["trades"][:DAILY_MAX_TRADES]]
        more = f" 等 {view['trades_count']} 筆" if len(view["trades"]) > DAILY_MAX_TRADES else ""
        lines.append(f"{trades_word}的買賣：" + "、".join(items) + more)
    link = _link(settings)
    if link:
        lines.append(f"完整日報：{link}")
    return signed(lines, kind, ai=bool(summary))


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


def _send_digest(db: Session, settings: Settings, row: NotificationOutbox, now: datetime,
                 cache: dict | None = None) -> None:
    """The weekly digest alone (no 市場週報 push took it in): from Sunday 18:00 — held to 21:30 only while that
    Sunday's 市場週報 push may still come for this channel (``push.market_coming``; ``cache``: per run)."""
    from forliosa.reports.push import digest_due, market_coming, weekly_of

    ch = db.get(GroupChannel, (row.group_id, row.channel_kind))
    group = db.get(Group, row.group_id)
    digest = db.get(GroupDigest, row.digest_id) if row.digest_id else None
    if group is None or ch is None or not _channel_ok(ch, "notify_weekly"):
        _cancel([row], "channel_off")
        return
    if digest is None or digest.status != "ready":
        _cancel([row], "not_ready")
        return
    finished = digest.finished_at or row.created_at
    due = digest_due(digest.week_end, finished, False)
    if now >= due:  # asked at the slot, so the answer is about the edition as it is then
        due = digest_due(digest.week_end, finished,
                         market_coming(db, "weekly", weekly_of(digest.week_end), ch, settings, cache))
    if now < due:  # queued under the old times (Saturday), or the 市場週報 push may still take it in
        row.not_before = due
        return
    members = sharing.members_of(db, group.id)
    if not any(m.shares("push") for m in members):
        _cancel([row], "not_shared")
        return
    view = sharing.digest_facts_view(digest.facts or {}, members, pushing_only=True)
    summary = digest.summary if sharing.digest_summary_pushable(digest.facts or {}, members) else None
    text = digest_text(group, digest, view, summary, ch.kind, settings)
    _apply(db, ch, [row], _deliver(db, ch, text, settings), now)


def _send_daily(db: Session, settings: Settings, row: NotificationOutbox, now: datetime,
                cache: dict | None = None) -> None:
    """「昨日你的群組」 alone (no 盤前重點 push took it in): from 07:30 of the next trading day — held to 08:20 only
    while that day's 盤前重點 push may still come for this channel (``push.market_coming``; ``cache``: per run)."""
    from forliosa.reports.push import daily_due, market_coming, premarket_of

    ch = db.get(GroupChannel, (row.group_id, row.channel_kind))
    group = db.get(Group, row.group_id)
    report = db.get(GroupDailyReport, row.daily_report_id) if row.daily_report_id else None
    if group is None or ch is None or not _channel_ok(ch, "notify_premarket"):
        _cancel([row], "channel_off")
        return
    if report is None or report.status not in ("ready", "failed"):
        _cancel([row], "not_ready")
        return
    finished = report.finished_at or row.created_at
    due = daily_due(report.trading_day, finished, False)
    if now >= due:  # asked at the slot, so the answer is about the edition as it is then
        due = daily_due(report.trading_day, finished,
                        market_coming(db, "premarket", premarket_of(report.trading_day), ch, settings, cache))
    if now < due:  # queued under the old times (the same evening), or the 盤前重點 push may still take it in
        row.not_before = due
        return
    members = sharing.members_of(db, group.id)
    facts = report.facts or {}
    live = sharing.daily_trades_live(db, facts, members, ch.configured_at)  # not deleted, after the push start
    view = sharing.daily_facts_view(facts, members, pushing_only=True, live=live)
    if not (view["returns"] or view["common_holdings"] or view["trades"]):
        _cancel([row], "not_shared")
        return
    summary = (report.summary if report.status == "ready" and report.summary
               and sharing.daily_summary_visible(facts, members, live, pushing_only=True) else None)
    same_day = now.astimezone(TAIPEI).date() == report.trading_day
    text = daily_text(group, report, view, summary, ch.kind, settings, same_day)
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
    dailies: list[NotificationOutbox] = []
    mreports: list[NotificationOutbox] = []
    for r in rows:
        if r.kind == "mreport":
            mreports.append(r)
            continue
        if r.kind == "digest":
            digests.append(r)
            continue
        if r.kind == "daily":
            dailies.append(r)
            continue
        t = db.get(Transaction, r.transaction_id) if r.kind == "trade" and r.transaction_id else None
        if t is None:
            _cancel([r], "gone")
            continue
        trades[(r.group_id, r.channel_kind, t.user_id, t.trade_date, t.symbol, t.type)].append((r, t))
    if mreports:  # first: a market report push takes the group's waiting daily or weekly push in
        from forliosa.reports import push as mreport_push

        for r in mreports:
            if r.status == "pending":
                mreport_push.send(db, settings, r, now)
        db.flush()
    for (group_id, kind, *_), items in trades.items():
        if all(r.status == "pending" for r, _ in items):  # a channel disabled meanwhile cancelled its rows
            _send_trades(db, md, settings, group_id, kind, items, now)
    editions: dict = {}  # each market edition's verdict, asked once per run
    for r in digests:  # a merged one is already marked sent (the same object)
        if r.status == "pending":
            _send_digest(db, settings, r, now, editions)
    for r in dailies:
        if r.status == "pending":
            _send_daily(db, settings, r, now, editions)
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
