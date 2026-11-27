"""Market reports to group channels (contract §15): text and a link, never a picture.

**Four switches per channel (產品負責人 2026-11-18, option A)**: ``notify_trades`` (交易動態, unchanged),
``notify_premarket`` (盤前, trading days 07:30), ``notify_close`` (盤後, trading days 16:00) and ``notify_weekly``
(週報, Sunday 18:00). One switch drives both parts of its message:

* **盤前** = the market 盤前重點 ＋「昨日你的群組」: the group's 群組 AI 日報 of the previous session (boosted groups
  only, :func:`premarket_group`), in one message. No daily report (a group that is not boosted, nobody who pushes):
  just the market part.
* **盤後** = 盤後重點 (no group part).
* **週報** = 市場週報 ＋「你的群組上週」: the group's weekly digest of the reviewed week (:func:`weekly_group`), in one
  message. The group digest is written on Saturday evening and goes out (and shows on the group page) on Sunday 18:00.
* **No market part** (reports switched off or paused): the switch still sends the group part alone at the same
  time — 「昨日你的群組」 at 07:30 of the next trading day, the group digest on Sunday 18:00
  (``notifications._send_daily`` / ``_send_digest``, timed by :func:`daily_due` / :func:`digest_due`).
  At that time :func:`market_coming` asks about that one edition: only while its push may still come for the
  channel is the group push held (08:20 / 21:30, after the market push's fallback) so the market push can take it
  in; a market push that never comes (a skipped edition, the worker down) leaves it to go alone then. Non-trading
  days have no 盤前 or 盤後; the 週報 is on Sunday whatever the week was.
* **Once per channel**: the group part has one outbox row per channel (``daily:<report>:<kind>`` /
  ``digest:<digest>:<kind>``). Whoever sends it — the market push that takes it in, or the group push alone — marks
  that row sent (``merged`` when taken in; a row is added when none was queued yet), and the market push never takes
  in a group part whose row is already sent (e.g. a daily report pushed the evening before, or a digest pushed on
  Saturday, by the code before 2026-11-18) or was cancelled by a channel change under that code. Rows queued before
  the change follow the new times when they come due; a channel set up again or disabled leaves them pending.

The rest:

* **Who**: only while the mode is ``public`` (the blind test was removed on 2026-11-18: every edition is public), for
  a ``public`` report that is not a backfill. Every group may switch the pushes on (no plan needed):
  ``notify_premarket`` (off by default), ``notify_close`` (off), ``notify_weekly`` (on). One outbox row per channel
  (``kind="mreport"``), queued when the push time comes (:func:`enqueue`); re-checked when it is sent (:func:`send`:
  the mode, the channel and its switch, the report) — otherwise cancelled. The text is the report's current version
  at that moment.
* **Text**: the kind and date, the one-line disclaimer, the highlights (footnotes removed; a sentence that cites a
  report gets 「（出處見全文）」), a group section when there is one, the link, and the site's last line
  (``notifications.signed``: 「AI 整理的部分可能有錯。」＋``disclaimer.SHORT``, once — the group section's own last
  line is dropped). Discord ≤ 1,900 characters, Telegram ≤ 4,000 with that line: the group section is cut first,
  then each highlight to 80 characters, then to two highlights.
* The group sections keep the anonymity rules of the group pushes (only members who push; the AI line only while
  everyone whose numbers went into it still pushes …).
* Never pushed: corrections, table refreshes, backfilled editions, anything personal.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa import disclaimer
from forliosa.config import Settings, get_settings
from forliosa.ids import new_id
from forliosa.models import (
    Group,
    GroupChannel,
    GroupDailyReport,
    GroupDigest,
    MarketReport,
    MarketReportVersion,
    NotificationOutbox,
)
from forliosa.reports import assemble
from forliosa.reports import settings as rs
from forliosa.reports.schedule import KIND_LABELS, md, md_wd, span
from forliosa.services import notifications, pushers
from forliosa.timeutil import TAIPEI, last_tw_trading_day, next_tw_trading_day, now_utc

log = logging.getLogger(__name__)

FLAG = {"premarket": "notify_premarket", "close": "notify_close", "weekly": "notify_weekly"}
LIMITS = {"discord": 1900, "telegram": 4000}
HIGHLIGHT_CUT = 80
LINE_AI = "AI 依公開資料整理，報告本文人人相同，不是投資建議。"
LINE_DATA = "依公開資料整理，這一版沒有 AI 段落，不是投資建議。"
SOURCE_NOTE = "（出處見全文）"
# The group parts (2026-11-18): 「昨日你的群組」 rides on 盤前 (trading days 07:30), the digest on 週報 (Sunday 18:00)
DAILY_SLOT, DAILY_HOLD = time(7, 30), time(8, 20)  # held past the premarket push's fallback (08:15)
DIGEST_HOLD = time(21, 30)  # held past the weekly push's close (21:00)
CHANNEL_CANCELS = ("channel_changed", "channel_disabled")  # ``channels._cancel_pending``


def pushing(db: Session, settings: Settings | None = None) -> bool:
    """Reports may be pushed at all: switched on, and the mode is public."""
    s = settings or get_settings()
    return bool(s.market_reports_enabled) and rs.mode(db, s) == "public"


def may_push(db: Session, report: MarketReport, settings: Settings | None = None) -> bool:
    return (pushing(db, settings) and report.visibility == "public" and not report.backfill
            and report.state != "skipped" and report.current_version_id is not None)


def _may_come(db: Session, report: MarketReport, s: Settings) -> bool:
    """A made edition that may still be pushed (its version may come later): like :func:`may_push` without the
    version."""
    if report.backfill or report.state == "skipped":
        return False
    return report.visibility == "public" and pushing(db, s)


def _edition_verdict(db: Session, kind: str, edition_date: date, s: Settings) -> tuple[str, str | None]:
    """``("coming", None)`` | ``("pushed", report id)`` | ``("no", None)`` for one edition (:func:`market_coming`)."""
    from forliosa.reports import pipeline

    if not s.market_reports_enabled:
        return "no", None
    report = pipeline.report_of(db, kind, edition_date)
    if report is not None:
        if report.pushed_at is not None:
            return "pushed", report.id
        return ("coming" if _may_come(db, report, s) else "no"), None
    if rs.mode(db, s) == "public":
        return "coming", None
    return "no", None


def market_coming(db: Session, kind: str, edition_date: date, channel: GroupChannel | None = None,
                  settings: Settings | None = None, cache: dict[tuple[str, date], tuple[str, str | None]] | None = None,
                  ) -> bool:
    """The market push of this one edition (``premarket`` / ``weekly`` of ``edition_date``) may still come to take the
    group part in — judged by that edition, not by the mode alone:

    * not made yet: reports public (not paused);
    * made, not pushed yet: one that may be pushed (public; not a backfill, not skipped);
    * pushed already: only while the push queued for ``channel`` still waits (it takes the part in when it is sent).

    Anything else — an admin-only edition, the mode paused, reports off, a push that already went — leaves the
    group part to go at its own time (07:30 / 18:00). ``cache``: the edition's verdict, shared by the rows of one
    run."""
    s = settings or get_settings()
    key = (kind, edition_date)
    if cache is not None and key in cache:
        verdict, report_id = cache[key]
    else:
        verdict, report_id = _edition_verdict(db, kind, edition_date, s)
        if cache is not None:
            cache[key] = (verdict, report_id)
    if verdict == "pushed":
        return channel is not None and report_id is not None and db.scalar(
            select(NotificationOutbox.id).where(
                NotificationOutbox.dedupe_key == dedupe_key(report_id, channel.group_id, channel.kind),
                NotificationOutbox.status == "pending")) is not None
    return verdict == "coming"


def dedupe_key(report_id: str, group_id: str, kind: str) -> str:
    return f"mreport:{report_id}:{group_id}:{kind}"


def enqueue(db: Session, report: MarketReport, now: datetime | None = None, settings: Settings | None = None) -> int:
    """One outbox row per active channel whose switch for this kind is on (due now)."""
    now = now or now_utc()
    if not may_push(db, report, settings):
        return 0
    flag = getattr(GroupChannel, FLAG[report.kind])
    added = 0
    for ch in db.scalars(select(GroupChannel).where(GroupChannel.status == "active", flag.is_(True))):
        key = dedupe_key(report.id, ch.group_id, ch.kind)
        if db.scalar(select(NotificationOutbox.id).where(NotificationOutbox.dedupe_key == key)):
            continue
        db.add(NotificationOutbox(id=new_id("ntf"), group_id=ch.group_id, channel_kind=ch.kind, kind="mreport",
                                  dedupe_key=key, market_report_id=report.id, status="pending", attempts=0,
                                  not_before=now, created_at=now))
        added += 1
    db.commit()
    return added


# -- text ------------------------------------------------------------------------------------------------------
def _t(text: Any, kind: str) -> str:
    return pushers.user_text(str(text), kind)


def highlight_lines(payload: dict[str, Any], kind: str) -> list[str]:
    """The highlights as push lines: the sentences joined, a cited report marked 「（出處見全文）」. The brief's rows
    (2026-11-27) carry their field's name (「位置：收在 5 日線…」: without it the row has no subject)."""
    out = []
    brief = payload.get("brief") or []
    rows = [(f"{r['label']}：", r["paragraph"]) for r in brief] or [("", p) for p in payload.get("highlights") or []]
    for head, p in rows:
        parts = []
        for s in p.get("sentences") or []:
            text = str(s.get("text") or "").strip()
            if not text:
                continue
            if any(str(r).startswith("X") for r in s.get("refs") or []):
                text += SOURCE_NOTE
            parts.append(text)
        if parts:
            out.append(_t(head + "".join(parts), kind))
    return out


def link(report_id: str, settings: Settings) -> str | None:
    """The report page, only with an explicit FRONTEND_URL (or in development): never a guessed address."""
    if settings.frontend_url or settings.is_dev:
        return f"{settings.frontend_base}/market/reports/{report_id}"
    return None


def _calendar_count(payload: dict[str, Any]) -> int:
    cal = payload.get("calendar") or {}
    return sum(len(g.get("rows") or []) + sum(int(f.get("count") or 0) for f in g.get("folded") or [])
               for g in cal.get("groups") or [])


def text(report: MarketReport, payload: dict[str, Any], kind: str, settings: Settings,
         group_lines: list[str] | None = None) -> str:
    """The channel message (``kind``: discord | telegram), cut to the channel's limit."""
    label = KIND_LABELS[report.kind]
    when = f"{span(report.period_start, report.period_end)} 回顧" if report.kind == "weekly" \
        else md_wd(report.edition_date)
    first = f"【{label} {when}】" + (LINE_AI if payload.get("has_ai") else LINE_DATA)
    # the close's own number first: the brief's rows (為什麼, 貢獻, 位置…) leave it to the page's number strip
    head = assemble.headline(payload)
    if head:
        first = f"{first}\n{_t(head, kind)}"
    highlights = highlight_lines(payload, kind)
    extra: list[str] = []
    if report.kind == "weekly" and report.next_start and report.next_end:
        n = _calendar_count(payload)
        extra.append(f"下週行事曆 {span(report.next_start, report.next_end)}：已排定 {n} 件（見全文）")
    url = link(report.id, settings)
    group = list(group_lines or [])

    def compose(hl: list[str], grp: list[str]) -> list[str]:
        lines = [first, *(f"・{h}" for h in hl), *extra, *grp]
        if url:
            lines.append(f"全文與圖表：{url}")
        return lines

    def ai_of(grp: list[str]) -> bool:
        return bool(payload.get("has_ai")) or any(x.startswith(disclaimer.AI_LABEL) for x in grp)

    # the site's last line (``notifications.signed``: 「AI 整理的部分可能有錯。」＋the short disclaimer) fits too
    limit = LIMITS.get(kind, 1900) - len(disclaimer.AI_NOTE + disclaimer.SHORT) - 1
    body = "\n".join(compose(highlights, group))
    if len(body) > limit and len(group) > 2:
        group = group[:2]  # the group section's heading and its first line
        body = "\n".join(compose(highlights, group))
    if len(body) > limit:
        highlights = [h if len(h) <= HIGHLIGHT_CUT else h[:HIGHLIGHT_CUT - 1] + "…" for h in highlights]
        body = "\n".join(compose(highlights, group))
    if len(body) > limit:
        group = group[:1]
        body = "\n".join(compose(highlights[:2], group))
    return notifications.signed(_cut(body, limit).split("\n"), kind, ai=ai_of(group))


def _cut(body: str, limit: int) -> str:
    """The body within ``limit``: a last line cut short ends in 「…」 (the highlights come first)."""
    return body if len(body) <= limit else body[:limit - 1].rstrip() + "…"


# -- the group sections ---------------------------------------------------------------------------------------------
def daily_key(report_id: str, channel_kind: str) -> str:
    return f"daily:{report_id}:{channel_kind}"


def digest_key(digest_id: str, channel_kind: str) -> str:
    return f"digest:{digest_id}:{channel_kind}"


def _sent(db: Session, key: str) -> bool:
    """The group part is not for this channel any more: it already went (alone, or taken in by an earlier market push),
    or it was cancelled when the channel was set up again or disabled (code before 2026-11-18; such rows now stay
    pending)."""
    return db.scalar(select(NotificationOutbox.id).where(
        NotificationOutbox.dedupe_key == key,
        (NotificationOutbox.status == "sent") | ((NotificationOutbox.status == "cancelled")
                                                 & NotificationOutbox.last_error.in_(CHANNEL_CANCELS)))) is not None


def _body_lines(full: str, heading: str) -> list[str]:
    """A daily / weekly push text without its title line, link line and last line (the disclaimer that
    ``notifications.signed`` adds: the report push ends with its own, once)."""
    tails = {disclaimer.SHORT, disclaimer.AI_NOTE + disclaimer.SHORT, disclaimer.AI}
    lines = full.split("\n")[1:]
    keep = [x for x in lines if x and not x.startswith(("完整日報：", "完整週報：")) and x not in tails]
    return [heading, *keep] if keep else []


def premarket_group(db: Session, group: Group, ch: GroupChannel, report: MarketReport, kind: str,
                    settings: Settings) -> tuple[list[str], GroupDailyReport | None]:
    """「昨日你的群組」: the 群組 AI 日報 of the session before the edition, as a channel may show it — unless it
    already went to this channel (then nothing: never twice)."""
    from forliosa.services import sharing

    prev = last_tw_trading_day(report.edition_date - timedelta(days=1))
    daily = db.scalar(select(GroupDailyReport).where(GroupDailyReport.group_id == group.id,
                                                     GroupDailyReport.trading_day == prev,
                                                     GroupDailyReport.status.in_(("ready", "failed"))))
    if daily is None or _sent(db, daily_key(daily.id, ch.kind)):
        return [], None
    members = sharing.members_of(db, group.id)
    facts = daily.facts or {}
    live = sharing.daily_trades_live(db, facts, members, ch.configured_at)
    view = sharing.daily_facts_view(facts, members, pushing_only=True, live=live)
    if not (view["returns"] or view["common_holdings"] or view["trades"]):
        return [], None
    summary = (daily.summary if daily.status == "ready" and daily.summary
               and sharing.daily_summary_visible(facts, members, live, pushing_only=True) else None)
    full = notifications.daily_text(group, daily, view, summary, kind, settings, same_day=False)
    lines = _body_lines(full, f"昨日你的群組（{md(prev)}）")
    return lines, daily if lines else None


def weekly_group(db: Session, group: Group, ch: GroupChannel, report: MarketReport, kind: str,
                 settings: Settings) -> tuple[list[str], GroupDigest | None]:
    """「你的群組上週」: the group's weekly digest of the reviewed week, as a channel may show it — unless it already
    went to this channel."""
    from forliosa.services import sharing

    digest = db.scalar(select(GroupDigest).where(GroupDigest.group_id == group.id,
                                                 GroupDigest.week_end == report.period_end))
    if digest is None or digest.status != "ready" or _sent(db, digest_key(digest.id, ch.kind)):
        return [], None
    members = sharing.members_of(db, group.id)
    if not any(m.shares("push") for m in members):
        return [], None
    view = sharing.digest_facts_view(digest.facts or {}, members, pushing_only=True)
    summary = digest.summary if sharing.digest_summary_pushable(digest.facts or {}, members) else None
    full = notifications.digest_text(group, digest, view, summary, kind, settings)
    lines = _body_lines(full, f"你的群組上週（{span(digest.week_start, digest.week_end)}）")
    return lines, digest if lines else None


def _group_part(db: Session, group: Group, ch: GroupChannel, report: MarketReport,
                settings: Settings) -> tuple[list[str], GroupDailyReport | GroupDigest | None]:
    if report.kind == "premarket":
        return premarket_group(db, group, ch, report, ch.kind, settings)
    if report.kind == "weekly":
        return weekly_group(db, group, ch, report, ch.kind, settings)
    return [], None


def mark_merged(db: Session, ch: GroupChannel, part: GroupDailyReport | GroupDigest, now: datetime) -> None:
    """The group part went out inside a market push: its outbox row for this channel is marked sent (``merged``), or
    added as sent when none was queued yet — so the group push never sends it again."""
    daily = isinstance(part, GroupDailyReport)
    key = daily_key(part.id, ch.kind) if daily else digest_key(part.id, ch.kind)
    row = db.scalar(select(NotificationOutbox).where(NotificationOutbox.dedupe_key == key))
    if row is None:
        row = NotificationOutbox(id=new_id("ntf"), group_id=ch.group_id, channel_kind=ch.kind,
                                 kind="daily" if daily else "digest", dedupe_key=key, attempts=0, not_before=now,
                                 created_at=now, **({"daily_report_id": part.id} if daily else {"digest_id": part.id}))
        db.add(row)
    row.status, row.last_error, row.sent_at = "sent", "merged", now


# -- sending -----------------------------------------------------------------------------------------------------
def send(db: Session, settings: Settings, row: NotificationOutbox, now: datetime) -> None:
    """Send one ``mreport`` row (re-checked first), taking in the group's part (盤前, 週報)."""
    from forliosa.services.notifications import _apply, _cancel, _channel_ok, _deliver

    report = db.get(MarketReport, row.market_report_id) if row.market_report_id else None
    ch = db.get(GroupChannel, (row.group_id, row.channel_kind))
    group = db.get(Group, row.group_id)
    if report is None or group is None:
        _cancel([row], "gone")
        return
    if not may_push(db, report, settings):
        _cancel([row], "not_public")
        return
    if ch is None or not _channel_ok(ch, FLAG[report.kind]):
        _cancel([row], "channel_off")
        return
    version = db.get(MarketReportVersion, report.current_version_id) if report.current_version_id else None
    if version is None:
        _cancel([row], "not_ready")
        return
    lines, part = _group_part(db, group, ch, report, settings)
    payload = version.payload or {}
    msg = text(report, payload, ch.kind, settings, lines)
    result = _deliver(db, ch, msg, settings)
    _apply(db, ch, [row], result, now)
    if result.ok and part is not None:
        mark_merged(db, ch, part, now)


# -- when the group parts go -------------------------------------------------------------------------------------------
def premarket_of(trading_day: date) -> date:
    """The 盤前 edition that carries a session's 群組 AI 日報: the next Taiwan trading day."""
    return next_tw_trading_day(trading_day + timedelta(days=1))


def weekly_of(week_end: date) -> date:
    """The 週報 edition that carries a week's digest: the Sunday after its Friday (``week_end``)."""
    return week_end + timedelta(days=(6 - week_end.weekday()) % 7)


def daily_slot(trading_day: date) -> datetime:
    """The 盤前 push that carries a session's 群組 AI 日報: 07:30 of the next Taiwan trading day."""
    return datetime.combine(premarket_of(trading_day), DAILY_SLOT, TAIPEI)


def daily_due(trading_day: date, finished: datetime, market: bool) -> datetime:
    """When a daily report's group push is due: the 盤前 slot after its session — held until 08:20 while that
    edition's market push may still take it in (``market``: :func:`market_coming`, asked at the slot) — or at once when
    it finished later than that."""
    slot = daily_slot(trading_day)
    if market:
        slot = datetime.combine(slot.astimezone(TAIPEI).date(), DAILY_HOLD, TAIPEI)
    return max(slot, finished)


def digest_due(week_end: date, finished: datetime, market: bool) -> datetime:
    """When a weekly digest's group push is due: Sunday 18:00 after its week (``digests.publish_at``) — held until
    21:30 while that Sunday's 市場週報 push may still take it in — or at once when it finished later than that."""
    from forliosa.services.digests import publish_at

    slot = publish_at(week_end)
    if market:
        slot = datetime.combine(slot.astimezone(TAIPEI).date(), DIGEST_HOLD, TAIPEI)
    return max(slot, finished)
