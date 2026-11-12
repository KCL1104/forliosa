"""群組 AI 週報 (docs/api-contract.md 「分享（M5）」→「群組 AI 週報」).

* **When**: the worker runs :func:`create_week` on Saturday from 20:00 (Taipei; catch-up until Sunday ends) for the
  week Monday–Friday that just ended. Weeks without a Taiwan trading day and groups where fewer than 2 members share
  ``returns`` get no digest. One digest per group and week (``uq_group_digest_week``).
* **Facts**: computed by the server from the sharing projection (``sharing.digest_week_facts``), stored by user_id
  and filtered by the *current* memberships and toggles on every read (:func:`digest_out`).
* **Model input**: only anonymous labels (成員 A, B … in a random order per digest) and numbers — no display names,
  user ids, group name or per-member holdings (only symbols held by two or more and industry counts). The summary is
  group-level, in Traditional Chinese, with no names, labels, buy / sell advice or target prices; an answer that names
  a label or mentions a target price is discarded (``failed``).
* **Calls**: one Message Batches request per digest through the key pool (``KeyPool.call``; ``digest.batch_id`` holds
  ``<slot>:<batch id>`` because a batch belongs to the workspace that created it). :func:`poll` collects results;
  when batches are unavailable (the endpoint is refused) or an item errored / expired, a normal Messages call is made
  instead (``batch_id = "direct"`` while it is retried). Usage is recorded as feature ``group_digest`` with no user
  (charged to nobody's AI quota; batch results at half price). A digest still pending 26 hours after it was created
  is marked failed.
* **Retention**: digests (with their comments, reactions and queued pushes) are deleted 26 weeks after their week.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
import secrets
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import anthropic
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from forliosa.ai import store
from forliosa.ai.keypool import KeyPool, KeysBusy, NoKeyAvailable, get_key_pool, is_failover_error
from forliosa.ai.pricing import CallUsage
from forliosa.api.errors import unprocessable
from forliosa.config import Settings, get_settings
from forliosa.ids import new_id
from forliosa.marketdata.service import MarketData
from forliosa.models import Group, GroupComment, GroupDigest, GroupReaction
from forliosa.services import notifications, sharing
from forliosa.timeutil import TAIPEI, iso_taipei, now_utc, today_taipei, tw_trading_days

log = logging.getLogger("forliosa.digests")

FEATURE = "group_digest"
MIN_RETURN_SHARERS = 2
GIVE_UP_AFTER = timedelta(hours=26)  # batches end within 24 hours
RETENTION_WEEKS = 26
MAX_TOKENS = 2048
MAX_SUMMARY_CHARS = 400
DIRECT = "direct"
DISCLAIMER = notifications.DISCLAIMER
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
# A summary that names a member label or talks about target prices / advice is not shown.
FORBIDDEN = re.compile(r"成員\s*[A-Z]|目標價|建議(?:買|賣|加碼|減碼|進場|出場)|(?:買進|賣出|加碼|減碼)建議")

SYSTEM = """你替一個親友投資群組寫「本週摘要」，會顯示在群組頁面上，所有成員都看得到。你只會拿到匿名的成員代號與數字。

規則：
1. 只描述群組整體：例如多數成員上漲或下跌、報酬分布的大致範圍、整體和「發行量加權股價報酬指數」與「元大台灣50」
   的比較、共同持股與產業集中的情形、交易是否頻繁。
2. 不點名，也不要寫出任何成員代號（不要出現「成員 A」這類字），不要猜測任何人的身分，不要評論誰做得好或不好。
3. 不給任何買進、賣出、加碼、減碼建議，不提目標價，不預測未來走勢。
4. 只使用提供的數字，不要補充新聞或其他資料；沒有資料的項目就略過。
5. 用繁體中文（台灣用語），2 到 4 句、150 字以內，純文字：不要標題、條列或 Markdown。"""


class BatchesUnavailable(Exception):
    """The Message Batches endpoint was refused (not found, not permitted, or the client has no batches)."""


# -- weeks ------------------------------------------------------------------------------------------------------
def digest_week(today: date) -> tuple[date, date]:
    """Monday and Friday of the latest week whose Friday is on or before ``today``."""
    friday = today - timedelta(days=(today.weekday() - 4) % 7)
    return friday - timedelta(days=4), friday


def create_week(db: Session, md: MarketData, today: date | None = None,
                now: datetime | None = None, settings: Settings | None = None) -> list[GroupDigest]:
    """Create the pending digests of the week that just ended (idempotent)."""
    settings = settings or get_settings()
    now = now or now_utc()
    week_start, week_end = digest_week(today or now.astimezone(TAIPEI).date())
    if not tw_trading_days(week_start, week_end):
        return []
    created: list[GroupDigest] = []
    for group in list(db.scalars(select(Group).order_by(Group.created_at, Group.id))):
        if db.scalar(select(GroupDigest.id).where(GroupDigest.group_id == group.id,
                                                  GroupDigest.week_start == week_start)):
            continue
        members = sharing.members_of(db, group.id)
        if sum(1 for m in members if m.shares("returns")) < MIN_RETURN_SHARERS:
            continue
        built = sharing.digest_week_facts(db, md, members, week_start, week_end)
        if built is None:
            continue
        facts, sources = built
        d = GroupDigest(id=new_id("gdg"), group_id=group.id, week_start=week_start, week_end=week_end,
                        status="pending", summary="", facts=facts, sources=sources,
                        model=store.model_for(FEATURE, settings), created_at=now)
        db.add(d)
        db.commit()
        created.append(d)
    if created:
        log.info("group digests %s: %d created", week_start.isoformat(), len(created))
    return created


# -- the model's input: labels and numbers only -----------------------------------------------------------------
def _label(i: int) -> str:
    return LETTERS[i] if i < len(LETTERS) else LETTERS[i // len(LETTERS) - 1] + LETTERS[i % len(LETTERS)]


def _pct(value: float | None) -> str:
    return "無資料" if value is None else f"{value * 100:+.2f}%"


def anonymous_prompt(digest: GroupDigest, members: list[sharing.Member],
                     shuffle: Callable[[list], None] | None = None) -> str:
    """What the model sees: anonymous labels in a random order, numbers, symbols held by two or more members and
    industry counts. Never a display name, user id, group name or one member's holdings."""
    facts = digest.facts or {}
    view = sharing.digest_facts_view(facts, members)  # members who still share (a retry days later sees less)
    values = [r["week_return_pct"] for r in view["returns"]]
    (shuffle or secrets.SystemRandom().shuffle)(values)
    lines = [f"期間：{digest.week_start.isoformat()}（週一）到 {digest.week_end.isoformat()}（週五），"
             f"{facts.get('trading_days', 0)} 個交易日。",
             f"成員本週報酬（{len(values)} 位有分享報酬率的成員，匿名、順序隨機）："]
    lines += [f"- 成員 {_label(i)}：{_pct(v)}" for i, v in enumerate(values)]
    bench = [f"{b['name']} {_pct(b['week_return_pct'])}" for b in facts.get("benchmarks", [])]
    lines.append("對照基準本週報酬：" + ("、".join(bench) if bench else "無資料"))
    common = [f"{c['name']}（{c['holder_count']} 人）" for c in view["common_holdings"][:10]]
    lines.append("兩人以上共同持有：" + ("、".join(common) if common else "無"))
    inds = [f"{i['industry']}（{i['holder_count']} 人）" for i in view["industries"][:10]]
    lines.append("持有各產業的人數：" + ("、".join(inds) if inds else "無資料"))
    lines.append(f"本週買賣筆數（只算有分享交易動態的成員）：{view['trades_count']}")
    return "\n".join(lines)


def request_params(prompt: str, model: str) -> dict[str, Any]:
    return {"model": model, "max_tokens": MAX_TOKENS, "system": SYSTEM,
            "messages": [{"role": "user", "content": prompt}], "output_config": {"effort": "low"}}


def _params(db: Session, d: GroupDigest) -> dict[str, Any]:
    return request_params(anonymous_prompt(d, sharing.members_of(db, d.group_id)), d.model)


# -- results ----------------------------------------------------------------------------------------------------
def _fail(d: GroupDigest, error: str, now: datetime) -> None:
    d.status, d.error, d.finished_at = "failed", error[:200], now


def _finish(db: Session, d: GroupDigest, msg: Any, slot: int | None, batch: bool, now: datetime) -> None:
    store.record_usage(db, user_id=None, thread_id=d.id, feature=FEATURE, model=getattr(msg, "model", None) or d.model,
                       key_slot=slot, usage=CallUsage.from_sdk(getattr(msg, "usage", None)),
                       stop_reason=getattr(msg, "stop_reason", None), batch=batch)
    text = " ".join("".join(getattr(b, "text", "") for b in msg.content
                            if getattr(b, "type", None) == "text").split())
    if getattr(msg, "stop_reason", None) not in ("end_turn", "stop_sequence"):
        _fail(d, f"stop_{getattr(msg, 'stop_reason', None)}", now)
    elif not text:
        _fail(d, "empty", now)
    elif FORBIDDEN.search(text):
        _fail(d, "rejected", now)
    else:
        d.status, d.summary, d.error, d.finished_at = "ready", text[:MAX_SUMMARY_CHARS], None, now
    db.commit()
    if d.status == "ready":
        notifications.enqueue_digest(db, d, now)


def _transient(exc: BaseException) -> bool:
    return isinstance(exc, (KeysBusy, anthropic.APIConnectionError)) or is_failover_error(exc)


def _too_old(d: GroupDigest, now: datetime) -> bool:
    return now - d.created_at > GIVE_UP_AFTER


def run_direct(db: Session, d: GroupDigest, pool: KeyPool, now: datetime) -> None:
    """A normal Messages call for one digest (batches unavailable, or its batch item did not succeed)."""
    params = _params(db, d)
    try:
        raw, slot = pool.call(lambda c: c.messages.with_raw_response.create(**params),
                              costs=store.slot_month_costs(db))
        pool.observe(slot, raw.headers)
        msg = raw.parse()
    except Exception as exc:  # classified below; never logs request content
        db.rollback()
        if _transient(exc) and not _too_old(d, now):
            d.batch_id = DIRECT
        else:
            _fail(d, type(exc).__name__, now)
        db.commit()
        log.warning("group digest %s: model call failed (%s)", d.id, type(exc).__name__)
        return
    _finish(db, d, msg, slot, False, now)


def _create_batch(client: Any, requests: list[dict[str, Any]]) -> Any:
    try:
        return client.messages.batches.create(requests=requests)
    except (anthropic.NotFoundError, anthropic.PermissionDeniedError, anthropic.BadRequestError,
            anthropic.UnprocessableEntityError, AttributeError) as exc:
        # A refused endpoint (e.g. not available to this workspace) must not disable the key for everything else.
        raise BatchesUnavailable(type(exc).__name__) from exc


def _batch_call(fn: Callable[[Any], Any]) -> Callable[[Any], Any]:
    def call(client: Any) -> Any:
        try:
            return fn(client)
        except (anthropic.NotFoundError, anthropic.PermissionDeniedError, AttributeError) as exc:
            raise BatchesUnavailable(type(exc).__name__) from exc

    return call


def submit(db: Session, pool: KeyPool | None = None, settings: Settings | None = None,
           now: datetime | None = None) -> int:
    """Send every pending digest that is not in a batch yet as one Message Batches request (or, when batches are
    unavailable, as normal calls). Returns the number of digests handled."""
    settings = settings or get_settings()
    now = now or now_utc()
    pending = list(db.scalars(select(GroupDigest).where(GroupDigest.status == "pending",
                                                        GroupDigest.batch_id.is_(None))
                              .order_by(GroupDigest.created_at, GroupDigest.id)))
    if not pending:
        return 0
    if not settings.ai_digest_enabled:
        for d in pending:
            _fail(d, "ai_disabled", now)
        db.commit()
        return len(pending)
    pool = pool or get_key_pool()
    if not pool.available:
        for d in pending:
            _fail(d, "ai_unavailable", now)
        db.commit()
        return len(pending)
    requests = [{"custom_id": d.id, "params": _params(db, d)} for d in pending]
    try:
        batch, slot = pool.call(lambda c: _create_batch(c, requests), costs=store.slot_month_costs(db))
    except BatchesUnavailable as exc:
        log.info("group digests: batches unavailable (%s); using normal calls", exc)
        for d in pending:
            run_direct(db, d, pool, now)
        return len(pending)
    except Exception as exc:  # no key, busy, connection: try again on the next poll
        db.rollback()
        for d in pending:
            if _too_old(d, now):
                _fail(d, type(exc).__name__, now)
        db.commit()
        log.warning("group digests: batch not created (%s)", type(exc).__name__)
        return 0
    for d in pending:
        d.batch_id = f"{slot}:{batch.id}"
    db.commit()
    log.info("group digests: %d sent as one batch on key #%d", len(pending), slot)
    return len(pending)


def poll(db: Session, pool: KeyPool | None = None, settings: Settings | None = None,
         now: datetime | None = None) -> int:
    """Collect finished batches (and retry ``direct`` digests). Returns the number of digests finished."""
    settings = settings or get_settings()
    now = now or now_utc()
    rows = list(db.scalars(select(GroupDigest).where(GroupDigest.status == "pending",
                                                     GroupDigest.batch_id.is_not(None))))
    if not rows:
        return 0
    pool = pool or get_key_pool()
    done = 0
    by_batch: dict[str, list[GroupDigest]] = {}
    for d in rows:
        if d.batch_id == DIRECT:
            run_direct(db, d, pool, now)
            done += d.status != "pending"
        else:
            by_batch.setdefault(d.batch_id or "", []).append(d)
    for ref, digests in by_batch.items():
        slot_text, _, batch_id = ref.partition(":")
        try:
            slot = int(slot_text)
            batch, _ = pool.call(_batch_call(lambda c, b=batch_id: c.messages.batches.retrieve(b)), only=slot)
            ended = batch.processing_status == "ended"
            results = {}
            if ended:
                items, _ = pool.call(_batch_call(lambda c, b=batch_id: list(c.messages.batches.results(b))),
                                     only=slot)
                results = {r.custom_id: r for r in items}
        except Exception as exc:  # the slot is gone, or the batch cannot be read
            db.rollback()
            log.warning("group digest batch on key #%s unreadable (%s)", slot_text, type(exc).__name__)
            if all(_too_old(d, now) for d in digests) or isinstance(exc, (BatchesUnavailable, NoKeyAvailable,
                                                                          ValueError)):
                for d in digests:
                    run_direct(db, d, pool, now)
                    done += d.status != "pending"
            continue
        if not ended:
            if all(_too_old(d, now) for d in digests):
                for d in digests:
                    run_direct(db, d, pool, now)
                    done += d.status != "pending"
            continue
        for d in digests:
            r = results.get(d.id)
            if r is not None and getattr(r.result, "type", None) == "succeeded":
                _finish(db, d, r.result.message, slot, True, now)
            else:  # errored / expired / canceled / missing: one normal call instead
                run_direct(db, d, pool, now)
            done += d.status != "pending"
    return done


# -- reading ---------------------------------------------------------------------------------------------------------
def digest_out(d: GroupDigest, members: list[sharing.Member], counts: dict[str, int],
               reactions: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    facts = d.facts or {}
    target = f"digest:{d.id}"
    ready = d.status == "ready"
    return {
        "id": d.id, "status": d.status, "week_start": d.week_start, "week_end": d.week_end,
        "created_at": iso_taipei(d.created_at), "summary": d.summary if ready else "",
        "facts": sharing.digest_facts_view(facts, members), "notes": list(facts.get("notes", [])),
        "disclaimer": DISCLAIMER, "sources": list(d.sources or []), "is_demo": bool(facts.get("is_demo")),
        "comment_count": counts.get(target, 0) if ready else 0, "reactions": reactions.get(target, []) if ready else [],
    }


def _cursor(d: GroupDigest) -> str:
    return base64.urlsafe_b64encode(f"{d.week_start.isoformat()}|{d.id}".encode()).decode().rstrip("=")


def digests_page(db: Session, group: Group, me_id: str, limit: int, cursor: str | None) -> dict[str, Any]:
    """The group's digests, newest week first; facts filtered by the current memberships and toggles."""
    q = select(GroupDigest).where(GroupDigest.group_id == group.id)
    if cursor:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
            ws, did = raw.split("|", 1)
            after = date.fromisoformat(ws)
        except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
            raise unprocessable("分頁游標無效") from exc
        q = q.where((GroupDigest.week_start < after) | ((GroupDigest.week_start == after) & (GroupDigest.id < did)))
    rows = list(db.scalars(q.order_by(GroupDigest.week_start.desc(), GroupDigest.id.desc()).limit(limit + 1)))
    page = rows[:limit]
    members = sharing.members_of(db, group.id)
    counts, reactions = sharing.social_summary(db, group.id, [f"digest:{d.id}" for d in page if d.status == "ready"],
                                               me_id)
    return {"items": [digest_out(d, members, counts, reactions) for d in page],
            "next_cursor": _cursor(page[-1]) if len(rows) > limit else None}


# -- retention -------------------------------------------------------------------------------------------------------
def purge_old(db: Session, today: date | None = None) -> int:
    """Digests whose week started more than 26 weeks ago, with their comments and reactions (queued pushes go with
    them by foreign key)."""
    cutoff = (today or today_taipei()) - timedelta(weeks=RETENTION_WEEKS)
    old = list(db.scalars(select(GroupDigest).where(GroupDigest.week_start < cutoff)))
    for d in old:
        target = f"digest:{d.id}"
        db.execute(delete(GroupComment).where(GroupComment.group_id == d.group_id, GroupComment.target == target))
        db.execute(delete(GroupReaction).where(GroupReaction.group_id == d.group_id, GroupReaction.target == target))
        db.delete(d)
    db.commit()
    return len(old)
