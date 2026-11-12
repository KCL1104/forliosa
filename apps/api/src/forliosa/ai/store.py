"""Threads, messages, drafts, usage records and quotas.

A conversation is stored as the exact Messages-API messages (content blocks as returned by the API, thinking
signatures and web-search ``encrypted_content`` included) and replayed append-only: rows are never edited or
reordered, and a turn that failed or was refused is kept for display with ``in_context = False`` instead of
being deleted or rewritten. Each turn's AI answer for the history view (text, citations, drafts, tool steps,
error) is kept on one "display" row of that turn.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from forliosa.ai.pricing import CallUsage, billable_tokens, estimate_cost
from forliosa.api.errors import ApiError, not_found, unprocessable
from forliosa.config import Settings
from forliosa.ids import new_id
from forliosa.models import AiDraft, AiMessage, AiThread, AiUsage, BrokerAccount, User
from forliosa.models import Transaction as TxnModel
from forliosa.timeutil import TAIPEI, iso_taipei, now_taipei, now_utc

FEATURES = ("chat", "why", "import", "report")
TITLE_MAX = 40


def model_for(feature: str, settings: Settings) -> str:
    override = {"chat": settings.ai_model_chat, "why": settings.ai_model_why, "import": settings.ai_model_import,
                "report": settings.ai_model_report}.get(feature)
    return (override or settings.ai_model).strip()


# -- time windows (Taipei) ---------------------------------------------------------------------------------
def day_start(now: datetime | None = None) -> datetime:
    n = (now or now_taipei()).astimezone(TAIPEI)
    return n.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def month_start(now: datetime | None = None) -> datetime:
    n = (now or now_taipei()).astimezone(TAIPEI)
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


# -- threads -----------------------------------------------------------------------------------------------
def owned_thread(db: Session, user: User, thread_id: str) -> AiThread:
    t = db.get(AiThread, thread_id)
    if t is None or t.user_id != user.id:
        raise not_found("找不到這段對話")
    return t


def create_thread(db: Session, user: User, first_message: str, model: str) -> AiThread:
    title = " ".join(first_message.split())
    if len(title) > TITLE_MAX:
        title = title[:TITLE_MAX - 1] + "…"
    now = now_utc()
    t = AiThread(id=new_id("thr"), user_id=user.id, title=title, model=model, context_tokens=0, created_at=now,
                 updated_at=now)
    db.add(t)
    db.commit()
    return t


def api_history(db: Session, thread: AiThread) -> list[dict[str, Any]]:
    rows = db.scalars(select(AiMessage).where(AiMessage.thread_id == thread.id, AiMessage.in_context.is_(True))
                      .order_by(AiMessage.seq))
    return [{"role": r.role, "content": r.content} for r in rows]


@dataclass
class TurnDisplay:
    """What the history view shows for one AI answer."""

    text: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    draft_ids: list[str] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    error: dict[str, Any] | None = None
    stop_reason: str | None = None

    def meta(self) -> dict[str, Any]:
        return {"display": True, "citations": self.citations, "drafts": self.draft_ids,
                "tools": [{"name": t["name"], "label": t["label"]} for t in self.tools],
                "error": self.error, "stop_reason": self.stop_reason}


def save_turn(db: Session, thread: AiThread, user: User, turn_id: str, messages: list[dict[str, Any]], *,
              in_context: bool, user_text: str, display: TurnDisplay, context_tokens: int | None = None) -> None:
    """Append one turn. ``messages[0]`` is the user's message; the last assistant message carries the display."""
    base = (db.scalar(select(func.max(AiMessage.seq)).where(AiMessage.thread_id == thread.id)) or 0) + 1
    now = now_utc()
    rows: list[AiMessage] = []
    for i, m in enumerate(messages):
        rows.append(AiMessage(thread_id=thread.id, user_id=user.id, turn_id=turn_id, seq=base + i, role=m["role"],
                              content=m["content"], in_context=in_context, is_user_input=i == 0,
                              text=user_text if i == 0 else "", meta={}, created_at=now))
    last_ai = next((r for r in reversed(rows) if r.role == "assistant"), None)
    if last_ai is None:
        last_ai = AiMessage(thread_id=thread.id, user_id=user.id, turn_id=turn_id, seq=base + len(rows),
                            role="assistant", content=[], in_context=False, is_user_input=False, created_at=now)
        rows.append(last_ai)
    last_ai.text = display.text
    last_ai.meta = display.meta()
    db.add_all(rows)
    thread.updated_at = now
    if context_tokens is not None:
        thread.context_tokens = context_tokens
    db.commit()


def _encode_cursor(t: AiThread) -> str:
    return base64.urlsafe_b64encode(f"{t.updated_at.astimezone(UTC).isoformat()}|{t.id}".encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        ts, tid = raw.split("|", 1)
        return datetime.fromisoformat(ts), tid
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise unprocessable("分頁游標無效") from exc


def list_threads(db: Session, user: User, limit: int = 30, cursor: str | None = None) -> dict[str, Any]:
    q = select(AiThread).where(AiThread.user_id == user.id)
    if cursor:
        ts, tid = _decode_cursor(cursor)
        q = q.where(or_(AiThread.updated_at < ts, and_(AiThread.updated_at == ts, AiThread.id < tid)))
    rows = list(db.scalars(q.order_by(AiThread.updated_at.desc(), AiThread.id.desc()).limit(limit + 1)))
    page = rows[:limit]
    previews: dict[str, str] = {}
    if page:
        ids = [t.id for t in page]
        counts = dict(db.execute(select(AiMessage.thread_id, func.count()).where(
            AiMessage.thread_id.in_(ids), AiMessage.is_user_input.is_(True)).group_by(AiMessage.thread_id)).all())
        for r in db.scalars(select(AiMessage).where(AiMessage.thread_id.in_(ids), AiMessage.role == "assistant",
                                                    AiMessage.text != "").order_by(AiMessage.seq)):
            previews[r.thread_id] = r.text
    else:
        counts = {}
    items = [{"id": t.id, "title": t.title, "created_at": iso_taipei(t.created_at),
              "updated_at": iso_taipei(t.updated_at), "message_count": counts.get(t.id, 0),
              "preview": (previews.get(t.id) or "")[:80]} for t in page]
    return {"items": items, "next_cursor": _encode_cursor(page[-1]) if len(rows) > limit else None}


def thread_detail(db: Session, user: User, thread_id: str) -> dict[str, Any]:
    from forliosa.ai.tools import draft_card

    t = owned_thread(db, user, thread_id)
    rows = list(db.scalars(select(AiMessage).where(AiMessage.thread_id == t.id).order_by(AiMessage.seq)))
    draft_ids = [d for r in rows for d in (r.meta or {}).get("drafts", [])]
    drafts = {d.id: d for d in db.scalars(select(AiDraft).where(AiDraft.id.in_(draft_ids)))} if draft_ids else {}
    accounts = {a.id: a for a in db.scalars(select(BrokerAccount).where(BrokerAccount.user_id == user.id))}
    messages = []
    for r in rows:
        meta = r.meta or {}
        if r.is_user_input:
            messages.append({"id": str(r.id), "turn_id": r.turn_id, "role": "user", "text": r.text,
                             "at": iso_taipei(r.created_at)})
        elif meta.get("display"):
            cards = [draft_card(drafts[d], accounts.get((drafts[d].payload or {}).get("account_id")))
                     for d in meta.get("drafts", []) if d in drafts]
            messages.append({"id": str(r.id), "turn_id": r.turn_id, "role": "ai", "text": r.text,
                             "citations": meta.get("citations", []), "drafts": cards,
                             "tools": meta.get("tools", []), "error": meta.get("error"),
                             "at": iso_taipei(r.created_at)})
    return {"id": t.id, "title": t.title, "model": t.model, "created_at": iso_taipei(t.created_at),
            "updated_at": iso_taipei(t.updated_at), "messages": messages}


def delete_thread(db: Session, user: User, thread_id: str) -> None:
    t = owned_thread(db, user, thread_id)
    for d in db.scalars(select(AiDraft).where(AiDraft.thread_id == t.id)):
        d.thread_id = None
    db.delete(t)
    db.commit()


# -- drafts ------------------------------------------------------------------------------------------------
def list_drafts(db: Session, user: User, status: str | None = "pending") -> list[dict[str, Any]]:
    from forliosa.ai.tools import draft_card

    q = select(AiDraft).where(AiDraft.user_id == user.id)
    if status:
        q = q.where(AiDraft.status == status)
    accounts = {a.id: a for a in db.scalars(select(BrokerAccount).where(BrokerAccount.user_id == user.id))}
    return [draft_card(d, accounts.get((d.payload or {}).get("account_id")))
            for d in db.scalars(q.order_by(AiDraft.created_at.desc()).limit(100))]


def update_draft(db: Session, user: User, draft_id: str, status: str, transaction_id: str | None) -> dict[str, Any]:
    from forliosa.ai.tools import draft_card

    d = db.get(AiDraft, draft_id)
    if d is None or d.user_id != user.id:
        raise not_found("找不到草稿")
    if status == "signed":
        if not transaction_id:
            raise unprocessable("簽名的草稿要附上建立的交易 transaction_id")
        txn = db.get(TxnModel, transaction_id)
        if txn is None or txn.user_id != user.id:
            raise not_found("找不到交易")
    d.status = status
    if status == "signed":
        d.transaction_id = transaction_id
    elif status == "pending":
        d.transaction_id = None  # undo: the transaction was deleted, the draft waits for a signature again
    d.updated_at = now_utc()
    db.commit()
    account = db.get(BrokerAccount, (d.payload or {}).get("account_id") or "")
    return draft_card(d, account if account is not None and account.user_id == user.id else None)


# -- usage and quotas --------------------------------------------------------------------------------------
def record_usage(db: Session, *, user_id: str | None, thread_id: str | None, feature: str, model: str,
                 key_index: int | None, usage: CallUsage, stop_reason: str | None) -> AiUsage:
    row = AiUsage(user_id=user_id, thread_id=thread_id, feature=feature, model=model, key_index=key_index,
                  input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                  cache_creation_input_tokens=usage.cache_creation_input_tokens,
                  cache_read_input_tokens=usage.cache_read_input_tokens,
                  web_search_requests=usage.web_search_requests, web_fetch_requests=usage.web_fetch_requests,
                  cost_usd=estimate_cost(model, usage), stop_reason=stop_reason, created_at=now_utc())
    db.add(row)
    db.commit()
    return row


def messages_today(db: Session, user: User, now: datetime | None = None) -> int:
    return db.scalar(select(func.count()).select_from(AiMessage).where(
        AiMessage.user_id == user.id, AiMessage.is_user_input.is_(True),
        AiMessage.created_at >= day_start(now))) or 0


def month_usage(db: Session, user: User, now: datetime | None = None) -> tuple[int, Decimal]:
    """Billable tokens and estimated cost (USD) this Taipei month. The shared "why" cache is not charged to the
    user who happened to trigger it."""
    rows = db.execute(select(AiUsage.input_tokens, AiUsage.output_tokens, AiUsage.cache_creation_input_tokens,
                             AiUsage.cache_read_input_tokens, AiUsage.cost_usd).where(
        AiUsage.user_id == user.id, AiUsage.feature != "why", AiUsage.created_at >= month_start(now))).all()
    tokens = sum(billable_tokens(CallUsage(i, o, cw, cr)) for i, o, cw, cr, _ in rows)
    cost = sum((Decimal(c or 0) for *_, c in rows), Decimal(0))
    return tokens, cost


def check_quota(db: Session, user: User, settings: Settings, now: datetime | None = None) -> None:
    if settings.ai_daily_message_limit > 0 and messages_today(db, user, now) >= settings.ai_daily_message_limit:
        raise ApiError(429, "ai_daily_limit",
                       f"今天的 AI 提問已達 {settings.ai_daily_message_limit} 則上限，明天再繼續問吧。")
    if settings.ai_monthly_token_budget > 0 and month_usage(db, user, now)[0] >= settings.ai_monthly_token_budget:
        raise ApiError(429, "ai_monthly_budget", "這個月的 AI 用量已達上限，下個月 1 日會重新計算。")


def usage_summary(db: Session, user: User, settings: Settings, available: bool) -> dict[str, Any]:
    now = now_taipei()
    used_msgs = messages_today(db, user, now)
    tokens, cost = month_usage(db, user, now)
    daily, budget = settings.ai_daily_message_limit, settings.ai_monthly_token_budget
    return {
        "date": now.date().isoformat(),
        "month": now.strftime("%Y-%m"),
        "messages_today": used_msgs,
        "daily_message_limit": daily or None,
        "messages_remaining": max(0, daily - used_msgs) if daily else None,
        "tokens_month": tokens,
        "monthly_token_budget": budget or None,
        "tokens_remaining": max(0, budget - tokens) if budget else None,
        "cost_usd_month": float(cost.quantize(Decimal("0.0001"))),
        "model": model_for("chat", settings),
        "available": available,
    }
