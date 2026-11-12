"""AI data retention: ``uv run python -m forliosa.ai.retention [--days N] [--dry-run]``.

Deletes what is older than ``AI_RETENTION_DAYS`` (default 30) since its last activity:

* ``ai_threads`` whose ``updated_at`` (the last turn) is older, with all their ``ai_messages`` (stored content
  blocks, web-search ``encrypted_content``, recaps and display rows);
* ``ai_drafts`` whose ``updated_at`` is older: signed or discarded ones (resolved — a signed draft's transaction
  stays in the ledger) and pending ones (expired: the user never signed them).

``ai_usage`` rows are kept for accounting (tokens, slot, estimated cost; they never hold message content), and
so is the shared ``ai_why_cache``. The worker runs this daily (``forliosa.worker``); ``AI_RETENTION_DAYS=0``
turns it off.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from forliosa.config import get_settings
from forliosa.db import session_factory
from forliosa.models import AiDraft, AiMessage, AiThread
from forliosa.timeutil import now_utc

log = logging.getLogger(__name__)
CHUNK = 500


@dataclass(frozen=True)
class PurgeResult:
    threads: int
    messages: int
    drafts: int
    cutoff: datetime


def purge(db: Session, days: int, now: datetime | None = None, dry_run: bool = False) -> PurgeResult:
    """Delete AI threads / messages / drafts whose last activity is more than ``days`` days ago."""
    if days <= 0:
        raise ValueError("retention days must be positive")
    cutoff = (now or now_utc()) - timedelta(days=days)
    thread_ids = list(db.scalars(select(AiThread.id).where(AiThread.updated_at < cutoff)))
    n_messages = 0
    for i in range(0, len(thread_ids), CHUNK):
        ids = thread_ids[i:i + CHUNK]
        n_messages += db.scalar(select(func.count()).select_from(AiMessage).where(AiMessage.thread_id.in_(ids))) or 0
    n_drafts = db.scalar(select(func.count()).select_from(AiDraft).where(AiDraft.updated_at < cutoff)) or 0
    if not dry_run:
        for i in range(0, len(thread_ids), CHUNK):
            ids = thread_ids[i:i + CHUNK]
            db.execute(delete(AiMessage).where(AiMessage.thread_id.in_(ids)))
            # recent drafts of an old thread stay (they expire on their own clock)
            db.execute(update(AiDraft).where(AiDraft.thread_id.in_(ids)).values(thread_id=None))
            db.execute(delete(AiThread).where(AiThread.id.in_(ids)))
        db.execute(delete(AiDraft).where(AiDraft.updated_at < cutoff))
        db.commit()
    result = PurgeResult(len(thread_ids), n_messages, n_drafts, cutoff)
    log.info("AI retention (%d days%s): %d threads, %d messages, %d drafts older than %s", days,
             ", dry run" if dry_run else "", result.threads, result.messages, result.drafts, cutoff.isoformat())
    return result


def run(days: int | None = None, dry_run: bool = False) -> PurgeResult | None:
    days = get_settings().ai_retention_days if days is None else days
    if days <= 0:
        log.info("AI retention is off (AI_RETENTION_DAYS=%d)", days)
        return None
    with session_factory()() as db:
        return purge(db, days, dry_run=dry_run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Delete AI conversations and drafts past the retention period")
    parser.add_argument("--days", type=int, default=None, help="override AI_RETENTION_DAYS (default 30)")
    parser.add_argument("--dry-run", action="store_true", help="only count what would be deleted")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    result = run(args.days, args.dry_run)
    if result is None:
        print("AI 資料保存期限關閉（AI_RETENTION_DAYS=0），沒有刪除任何資料。")
        return 0
    verb = "將刪除" if args.dry_run else "已刪除"
    print(f"{verb} {result.threads} 段對話、{result.messages} 則訊息、{result.drafts} 筆草稿"
          f"（最後活動早於 {result.cutoff:%Y-%m-%d %H:%M} UTC）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
