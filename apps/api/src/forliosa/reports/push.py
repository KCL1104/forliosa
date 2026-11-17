"""Market reports to group channels (contract §15): text and a link, never a picture.

* **Who**: only while the mode is ``public``, for a ``public`` report that is neither a backfill nor a blind-test
  edition. Every group may switch the pushes on (no plan needed): ``notify_premarket`` (off by default),
  ``notify_close`` (off), ``notify_weekly`` (on). One outbox row per channel (``kind="mreport"``), queued when the push
  time comes (:func:`enqueue`); re-checked when it is sent (:func:`send`: the mode, the channel and its switch, the
  report) — otherwise cancelled. The text is the report's current version at that moment.
* **Text**: the kind and date, the one-line disclaimer, the highlights (footnotes removed; a sentence that cites a
  report gets 「（出處見全文）」), a group section when there is one, the link, and the site's last line
  (``notifications.signed``: 「AI 整理的部分可能有錯。」＋``disclaimer.SHORT``, once — the group section's own last
  line is dropped). Discord ≤ 1,900 characters, Telegram ≤ 4,000 with that line: the group section is cut first,
  then each highlight to 80 characters, then to two highlights.
* **盤前重點 ＋「昨日你的群組」**: the group's 群組 AI 日報 of the previous session (boosted groups), with the same
  anonymity rules as the daily push (only members who push; the AI line only with ≥2 sharers…), whatever
  ``notify_daily`` says. A daily-report push of the same group and channel still waiting (it was held to 08:20 for
  this) is marked sent (``merged``) once the premarket push went out.
* **市場週報 ＋ 群組週報**: the group's weekly digest of the reviewed week, when its push is still waiting (held to Su\
nday
  21:30 for this), is folded in the same way.
* Never pushed: corrections, table refreshes, backfilled editions, anything personal; blind-test editions only as
  below.
* **盲測開給所有人** (``MREPORT_TRIAL_AUDIENCE=all``, mode ``trial``; 產品負責人 2026-11-17): a blind-test edition
  is pushed once, when at least two of A / B / C can be read (:func:`pipeline.maybe_push`), to the channels whose
  switch for the kind is on — one message (:func:`trial_text`): the kind and date with the disclaimer line, the data
  edition's rule-made title (never a variant's text: quoting one of the three first would favour it), 「盲測中：三種
  寫法，看完選一個。」 and the link to the vote page. Same outbox rows and dedupe keys; nothing is folded in (the
  group's daily and weekly pushes go on their own, as before).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
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
from forliosa.reports import settings as rs
from forliosa.reports.schedule import KIND_LABELS, md, md_wd, span
from forliosa.services import notifications, pushers
from forliosa.timeutil import TAIPEI, last_tw_trading_day, now_utc

log = logging.getLogger(__name__)

FLAG = {"premarket": "notify_premarket", "close": "notify_close", "weekly": "notify_weekly"}
LIMITS = {"discord": 1900, "telegram": 4000}
HIGHLIGHT_CUT = 80
LINE_AI = "AI 依公開資料整理，報告本文人人相同，不是投資建議。"
LINE_DATA = "依公開資料整理，這一版沒有 AI 段落，不是投資建議。"
SOURCE_NOTE = "（出處見全文）"
LINE_TRIAL = "盲測中：三種寫法，看完選一個。"
TRIAL_TITLE_CUT = 120


def pushing(db: Session, settings: Settings | None = None) -> bool:
    """Reports may be pushed at all: switched on, and the mode is public."""
    s = settings or get_settings()
    return bool(s.market_reports_enabled) and rs.mode(db, s) == "public"


def may_push(db: Session, report: MarketReport, settings: Settings | None = None) -> bool:
    return (pushing(db, settings) and report.visibility == "public" and not report.backfill and not report.trial
            and report.state != "skipped" and report.current_version_id is not None)


def trial_pushing(db: Session, settings: Settings | None = None) -> bool:
    """Blind-test editions may be pushed: switched on, the mode is trial and the blind test is open to everyone."""
    s = settings or get_settings()
    return bool(s.market_reports_enabled) and rs.mode(db, s) == "trial" and rs.trial_audience(db, s) == "all"


def may_push_trial(db: Session, report: MarketReport, settings: Settings | None = None) -> bool:
    return (bool(report.trial) and not report.backfill and report.state != "skipped"
            and report.current_version_id is not None and trial_pushing(db, settings))


def dedupe_key(report_id: str, group_id: str, kind: str) -> str:
    return f"mreport:{report_id}:{group_id}:{kind}"


def enqueue(db: Session, report: MarketReport, now: datetime | None = None, settings: Settings | None = None) -> int:
    """One outbox row per active channel whose switch for this kind is on (due now); a blind-test edition only while
    the blind test is open to everyone."""
    now = now or now_utc()
    if not (may_push_trial(db, report, settings) if report.trial else may_push(db, report, settings)):
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
    """The highlights as push lines: the sentences joined, a cited report marked 「（出處見全文）」."""
    out = []
    for p in payload.get("highlights") or []:
        parts = []
        for s in p.get("sentences") or []:
            text = str(s.get("text") or "").strip()
            if not text:
                continue
            if any(str(r).startswith("X") for r in s.get("refs") or []):
                text += SOURCE_NOTE
            parts.append(text)
        if parts:
            out.append(_t("".join(parts), kind))
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
    return notifications.signed(body[:limit].split("\n"), kind, ai=ai_of(group))


def title_body(title: str, label: str) -> str:
    """The title without its 「盤後重點 11/16（一）：」 head (the first line already says the kind and date)."""
    t = " ".join(str(title or "").split())
    if t.startswith(label) and "：" in t:
        return t.split("：", 1)[1].strip()
    return "" if t.startswith(label) else t


def trial_text(report: MarketReport, payload: dict[str, Any], kind: str, settings: Settings) -> str:
    """The blind-test message: the kind and date with the disclaimer line, the rule-made title of the data edition
    (an AI title — never the case for the data edition — is left out), the blind-test line and the vote link."""
    label = KIND_LABELS[report.kind]
    when = f"{span(report.period_start, report.period_end)} 回顧" if report.kind == "weekly" \
        else md_wd(report.edition_date)
    lines = [f"【{label} {when}】{LINE_AI}"]
    title = title_body(payload.get("title") or "", label) if payload.get("title_origin") != "ai" else ""
    if title:  # a rule-made title is one short line; cut a freak one so the vote link always fits
        title = _t(title, kind)
        lines.append(title if len(title) <= TRIAL_TITLE_CUT else title[:TRIAL_TITLE_CUT - 1] + "…")
    lines.append(LINE_TRIAL)
    url = link(report.id, settings)
    lines.append(f"投票：{url}" if url else "到 Forliosa 的「市場 → 報告」投票。")
    return notifications.signed(lines, kind)


# -- the group sections ---------------------------------------------------------------------------------------------
def _body_lines(full: str, heading: str) -> list[str]:
    """A daily / weekly push text without its title line, link line and last line (the disclaimer that
    ``notifications.signed`` adds: the report push ends with its own, once)."""
    tails = {disclaimer.SHORT, disclaimer.AI_NOTE + disclaimer.SHORT, disclaimer.AI}
    lines = full.split("\n")[1:]
    keep = [x for x in lines if x and not x.startswith(("完整日報：", "完整週報：")) and x not in tails]
    return [heading, *keep] if keep else []


def premarket_group(db: Session, group: Group, ch: GroupChannel, report: MarketReport, kind: str,
                    settings: Settings) -> tuple[list[str], GroupDailyReport | None]:
    """「昨日你的群組」: the 群組 AI 日報 of the session before the edition, as a channel may show it."""
    from forliosa.services import sharing

    prev = last_tw_trading_day(report.edition_date - timedelta(days=1))
    daily = db.scalar(select(GroupDailyReport).where(GroupDailyReport.group_id == group.id,
                                                     GroupDailyReport.trading_day == prev,
                                                     GroupDailyReport.status.in_(("ready", "failed"))))
    if daily is None:
        return [], None
    members = sharing.members_of(db, group.id)
    facts = daily.facts or {}
    live = sharing.daily_trades_live(db, facts, members, ch.configured_at)
    view = sharing.daily_facts_view(facts, members, pushing_only=True, live=live)
    if not (view["returns"] or view["common_holdings"] or view["trades"]):
        return [], daily
    summary = (daily.summary if daily.status == "ready" and daily.summary
               and sharing.daily_summary_visible(facts, members, live, pushing_only=True) else None)
    full = notifications.daily_text(group, daily, view, summary, kind, settings, same_day=False)
    return _body_lines(full, f"昨日你的群組（{md(prev)}）"), daily


def weekly_group(db: Session, group: Group, ch: GroupChannel, report: MarketReport, kind: str,
                 settings: Settings) -> tuple[list[str], NotificationOutbox | None]:
    """「你的群組上週」: the group's weekly digest of the reviewed week, when its push to this channel still waits."""
    from forliosa.services import sharing

    row = db.scalar(select(NotificationOutbox).join(GroupDigest, GroupDigest.id == NotificationOutbox.digest_id).where(
        NotificationOutbox.group_id == group.id, NotificationOutbox.channel_kind == ch.kind,
        NotificationOutbox.kind == "digest", NotificationOutbox.status == "pending",
        GroupDigest.week_end == report.period_end))
    if row is None:
        return [], None
    digest = db.get(GroupDigest, row.digest_id)
    if digest is None or digest.status != "ready" or not ch.notify_digest:
        return [], None
    members = sharing.members_of(db, group.id)
    if not any(m.shares("push") for m in members):
        return [], None
    view = sharing.digest_facts_view(digest.facts or {}, members, pushing_only=True)
    summary = digest.summary if sharing.digest_summary_pushable(digest.facts or {}, members) else None
    full = notifications.digest_text(group, digest, view, summary, kind, settings)
    lines = _body_lines(full, f"你的群組上週（{span(digest.week_start, digest.week_end)}）")
    return lines, row if lines else None


# -- sending -----------------------------------------------------------------------------------------------------
def send(db: Session, settings: Settings, row: NotificationOutbox, now: datetime) -> None:
    """Send one ``mreport`` row (re-checked first), folding in the group's daily or weekly push."""
    from forliosa.services.notifications import _apply, _cancel, _channel_ok, _deliver

    report = db.get(MarketReport, row.market_report_id) if row.market_report_id else None
    ch = db.get(GroupChannel, (row.group_id, row.channel_kind))
    group = db.get(Group, row.group_id)
    if report is None or group is None:
        _cancel([row], "gone")
        return
    if report.trial:
        _send_trial(db, settings, row, report, ch, now)
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
    lines: list[str] = []
    merged_daily: GroupDailyReport | None = None
    merged_digest: NotificationOutbox | None = None
    if report.kind == "premarket":
        lines, merged_daily = premarket_group(db, group, ch, report, ch.kind, settings)
    elif report.kind == "weekly":
        lines, merged_digest = weekly_group(db, group, ch, report, ch.kind, settings)
    msg = text(report, version.payload or {}, ch.kind, settings, lines)
    result = _deliver(db, ch, msg, settings)
    _apply(db, ch, [row], result, now)
    if not result.ok:
        return
    merged: list[NotificationOutbox] = []
    if merged_daily is not None:
        merged += list(db.scalars(select(NotificationOutbox).where(
            NotificationOutbox.group_id == group.id, NotificationOutbox.channel_kind == ch.kind,
            NotificationOutbox.kind == "daily", NotificationOutbox.status == "pending",
            NotificationOutbox.daily_report_id == merged_daily.id)))
    if merged_digest is not None and merged_digest.status == "pending":
        merged.append(merged_digest)
    for r in merged:
        r.status, r.last_error, r.sent_at = "sent", "merged", now


def _send_trial(db: Session, settings: Settings, row: NotificationOutbox, report: MarketReport,
                ch: GroupChannel | None, now: datetime) -> None:
    """A blind-test edition's one message (re-checked: still open to everyone, the channel and its switch on)."""
    from forliosa.services.notifications import _apply, _cancel, _channel_ok, _deliver

    if not may_push_trial(db, report, settings):
        _cancel([row], "trial_closed")
        return
    if ch is None or not _channel_ok(ch, FLAG[report.kind]):
        _cancel([row], "channel_off")
        return
    version = db.get(MarketReportVersion, report.current_version_id) if report.current_version_id else None
    if version is None:
        _cancel([row], "not_ready")
        return
    _apply(db, ch, [row], _deliver(db, ch, trial_text(report, version.payload or {}, ch.kind, settings), settings),
           now)


# -- holding the group pushes for a merge ------------------------------------------------------------------------
def daily_hold(ch: GroupChannel, due: datetime, reports_on: bool) -> datetime:
    """A daily-report push due at 07:30 on a Taiwan trading day waits until 08:20 when the premarket push to the same
    channel is on (the premarket push takes it in). ``reports_on``: :func:`pushing`, read once by the caller."""
    from forliosa.timeutil import is_tw_trading_day

    t = due.astimezone(TAIPEI)
    if (t.hour, t.minute) == (7, 30) and is_tw_trading_day(t.date()) and ch.notify_premarket and reports_on:
        return datetime.combine(t.date(), datetime.min.time(), TAIPEI) + timedelta(hours=8, minutes=20)
    return due


def digest_hold(ch: GroupChannel, due: datetime, reports_on: bool) -> datetime:
    """A weekly-digest push waits until the next Sunday 21:30 when the weekly report push to the same channel is on."""
    if not (ch.notify_weekly and reports_on):
        return due
    t = due.astimezone(TAIPEI)
    sunday: date = t.date() + timedelta(days=(6 - t.weekday()) % 7)
    hold = datetime.combine(sunday, datetime.min.time(), TAIPEI) + timedelta(hours=21, minutes=30)
    return hold if hold > due else due
