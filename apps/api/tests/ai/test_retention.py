"""30-day retention: old threads (with their messages) and old drafts are deleted, recent ones and usage records
stay, usage records hold no message content; the CLI and the daily worker job run it."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from forliosa.ai import retention
from forliosa.models import AiDraft, AiMessage, AiThread, AiUsage
from forliosa.timeutil import now_utc
from tests.ai.conftest import API, chat
from tests.ai.fake_anthropic import text


def _age(engine, model, ident, days: int, column: str = "updated_at") -> None:
    with Session(engine) as db:
        row = db.get(model, ident)
        setattr(row, column, now_utc() - timedelta(days=days))
        db.commit()


def _draft(engine, user_id: str, thread_id: str | None, status: str, days: int) -> str:
    with Session(engine) as db:
        d = AiDraft(id=f"drf_{status}_{days}", user_id=user_id, thread_id=thread_id, status=status, payload={},
                    preview={}, notes=[], created_at=now_utc() - timedelta(days=days),
                    updated_at=now_utc() - timedelta(days=days))
        db.add(d)
        db.commit()
        return d.id


def test_purge_deletes_old_threads_messages_and_drafts(client, pool, fake, engine):
    fake.reply(text("舊的")).reply(text("新的"))
    old = chat(client, "舊對話")[1][0][1]["id"]
    new = chat(client, "新對話")[1][0][1]["id"]
    _age(engine, AiThread, old, 31)
    with Session(engine) as db:
        user_id = db.get(AiThread, new).user_id
    signed_old = _draft(engine, user_id, old, "signed", 40)
    pending_old = _draft(engine, user_id, new, "pending", 31)  # expired: never signed
    pending_recent = _draft(engine, user_id, old, "pending", 2)  # of the old thread, but itself recent
    discarded_recent = _draft(engine, user_id, None, "discarded", 29)
    with Session(engine) as db:
        assert retention.purge(db, 30, dry_run=True).threads == 1
        assert db.get(AiThread, old) is not None  # dry run deletes nothing
        result = retention.purge(db, 30)
    assert (result.threads, result.messages, result.drafts) == (1, 3, 2)  # user + page context + answer
    with Session(engine) as db:
        assert db.get(AiThread, old) is None and db.get(AiThread, new) is not None
        assert db.scalar(select(func.count()).select_from(AiMessage).where(AiMessage.thread_id == old)) == 0
        assert db.get(AiDraft, signed_old) is None and db.get(AiDraft, pending_old) is None
        kept = db.get(AiDraft, pending_recent)
        assert kept is not None and kept.thread_id is None and db.get(AiDraft, discarded_recent) is not None
        # usage stays for accounting, for both threads
        assert db.scalar(select(func.count()).select_from(AiUsage)) == 2
    assert client.get(f"{API}/ai/threads/{old}").status_code == 404
    assert client.get(f"{API}/ai/usage").json()["tokens_month"] > 0


def test_usage_rows_never_hold_message_content(client, pool, fake, engine):
    fake.reply(text("祕密回答內容"))
    chat(client, "祕密問題內容")
    columns = {c["name"] for c in inspect(engine).get_columns("ai_usage")}
    assert columns.isdisjoint({"text", "content", "message", "messages", "prompt", "meta"})
    with Session(engine) as db:
        row = db.scalars(select(AiUsage)).one()
        values = " ".join(str(getattr(row, c)) for c in columns)
    assert "祕密" not in values and row.key_slot == 1 and row.cost_usd > Decimal(0)


def test_cli_and_settings(engine, ai_env, capsys, monkeypatch):
    monkeypatch.setattr(retention, "session_factory", lambda: lambda: Session(engine))
    assert retention.main(["--dry-run"]) == 0
    assert "將刪除 0 段對話" in capsys.readouterr().out
    ai_env(AI_RETENTION_DAYS=0)
    assert retention.run() is None
    assert retention.main([]) == 0 and "關閉" in capsys.readouterr().out
    ai_env(AI_RETENTION_DAYS=7)
    assert retention.run().cutoff < now_utc() - timedelta(days=6)


def test_worker_runs_retention_daily(monkeypatch):
    from datetime import datetime, time

    from forliosa.timeutil import TAIPEI
    from forliosa.worker import Worker

    class _MD:  # the worker only needs a market data object for its other jobs
        pass

    job = next(j for j in Worker(md=_MD()).jobs if j.name == "ai_retention")  # type: ignore[arg-type]
    sunday = datetime(2026, 11, 15, 4, 25, tzinfo=TAIPEI)
    assert job.due(sunday, None) and not job.due(sunday, sunday)
    assert not job.due(datetime.combine(sunday.date(), time(3, 0), TAIPEI), None)
