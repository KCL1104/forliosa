"""AI (M4): streaming chat (SSE), threads, drafts, suggestions and usage."""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from forliosa.ai import store
from forliosa.ai.chat import ChatTurn
from forliosa.ai.keypool import get_key_pool
from forliosa.ai.schemas import (
    ChatIn,
    DraftCard,
    DraftPatch,
    Suggestions,
    ThreadDetail,
    ThreadPage,
    Usage,
)
from forliosa.ai.suggestions import suggestions as build_suggestions
from forliosa.api.deps import current_user
from forliosa.api.errors import ApiError
from forliosa.config import get_settings
from forliosa.db import get_db, session_factory
from forliosa.marketdata.service import get_market_data
from forliosa.models import User

router = APIRouter(prefix="/ai", tags=["ai"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


CHAT_DOC = {200: {"content": {"text/event-stream": {}},
                  "description": "事件：thread、text、tool、citation、draft、error、done（見 docs/api-contract.md）"}}


@router.post("/chat", summary="AI 對話（SSE 串流）", response_class=StreamingResponse, responses=CHAT_DOC)
def chat(body: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    settings = get_settings()
    pool = get_key_pool()
    if not pool.available:
        raise ApiError(503, "ai_unavailable", "AI 功能尚未設定（沒有可用的 API 金鑰）")
    store.check_quota(db, user, settings)
    if body.thread_id:
        thread = store.owned_thread(db, user, body.thread_id)
        if thread.context_tokens >= settings.ai_thread_max_context_tokens:
            raise ApiError(409, "thread_too_long", "這段對話已經很長了，請開一段新對話繼續問。")
    user_id = user.id

    def events() -> Iterator[str]:
        # Own session: the request-scoped one is closed once streaming starts.
        with session_factory()() as sdb:
            me = sdb.get(User, user_id)
            turn = ChatTurn(sdb, me, get_market_data(), pool, settings)
            for name, data in turn.run(thread_id=body.thread_id, message=body.message, route=body.page.route,
                                       symbol=body.page.symbol, privacy=body.privacy):
                yield sse(name, data)

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/threads", response_model=ThreadPage, summary="對話紀錄（最近更新的在前）")
def list_threads(limit: int = Query(30, ge=1, le=100), cursor: str | None = None,
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    return store.list_threads(db, user, limit, cursor)


@router.get("/threads/{thread_id}", response_model=ThreadDetail, summary="一段對話的內容")
def get_thread(thread_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return store.thread_detail(db, user, thread_id)


@router.delete("/threads/{thread_id}", status_code=204, summary="刪除對話（草稿保留）")
def delete_thread(thread_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    store.delete_thread(db, user, thread_id)
    return Response(status_code=204)


@router.get("/drafts", response_model=list[DraftCard], summary="AI 交易草稿（預設只列待確認）")
def list_drafts(status: str = Query("pending", pattern="^(pending|signed|discarded|all)$"),
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    return store.list_drafts(db, user, None if status == "all" else status)


@router.patch("/drafts/{draft_id}", response_model=DraftCard,
              summary="標示草稿已簽名（附交易 id）、捨棄，或復原後回到待簽名")
def update_draft(draft_id: str, body: DraftPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return store.update_draft(db, user, draft_id, body.status, body.transaction_id)


@router.get("/suggestions", response_model=Suggestions, summary="依頁面與資料自動出現的問題與動作（規則，不呼叫模型）")
def get_suggestions(route: str = Query("/", max_length=200), symbol: str | None = Query(None, max_length=20),
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    return build_suggestions(db, user, get_market_data(), route, symbol)


@router.get("/usage", response_model=Usage, summary="今天的提問數、本月 token 用量與上限")
def get_usage(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return store.usage_summary(db, user, get_settings(), get_key_pool().available)
