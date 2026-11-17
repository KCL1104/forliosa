"""``GET /api/v1/events``: realtime invalidations as Server-Sent Events (docs/api-contract.md 「即時更新」).

The stream never carries data: each event is a topic and a few ids the user can already see (``realtime.events``);
the browser refetches through the normal endpoints. Always the signed-in user's own stream (``X-Forliosa-View-As`` is
ignored: ``ledger.viewas`` events name the delegation). ``async`` and without ``Depends(get_db)``: an open stream holds
neither a worker thread nor a pooled database connection; the login is checked with a short session of its own.
"""

from __future__ import annotations

import logging
from datetime import UTC

from fastapi import APIRouter, Query, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from forliosa.api.deps import COOKIE_NAME, _token_hash, session_key
from forliosa.api.errors import ApiError
from forliosa.config import get_settings
from forliosa.db import session_factory
from forliosa.models import User, UserSession
from forliosa.realtime.hub import Conn, Hub, Refused
from forliosa.timeutil import now_utc

log = logging.getLogger(__name__)
router = APIRouter(tags=["realtime"])

OFF_RETRY_AFTER = 600  # seconds: REALTIME_ENABLED=false (the web app polls meanwhile)
REFUSED_MESSAGES = {
    "too_many_streams": "連線太頻繁，等一下再試。",
    "realtime_busy": "即時更新暫時忙碌，稍後自動重試。",
}


def _session_row(db, sid: str) -> UserSession | None:
    sess = db.get(UserSession, sid)
    if sess is None:
        return None
    expires = sess.expires_at if sess.expires_at.tzinfo else sess.expires_at.replace(tzinfo=UTC)
    return sess if expires > now_utc() else None


def _identify(sid: str) -> tuple[str, bool] | None:
    """(user id, site admin?) of a valid login session; None otherwise."""
    from forliosa.services.discussions import is_site_admin

    with session_factory()() as db:
        sess = _session_row(db, sid)
        user = db.get(User, sess.user_id) if sess is not None else None
        return (user.id, is_site_admin(user)) if user is not None else None


def _still_valid(sid: str) -> bool:
    with session_factory()() as db:
        return _session_row(db, sid) is not None


def _origin_allowed(request: Request) -> bool:
    origin = request.headers.get("origin")
    allowed = {o.strip().rstrip("/").lower() for o in get_settings().cors_origins}
    return origin is None or "*" in allowed or origin.strip().rstrip("/").lower() in allowed


class EventStream(StreamingResponse):
    """The stream leaves the hub however it ends (rotation, the browser leaving, a server shutdown)."""

    def __init__(self, hub: Hub, conn: Conn, body):
        super().__init__(body, media_type="text/event-stream",
                         headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})
        self.hub, self.conn = hub, conn

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.hub.unregister(self.conn)


@router.get("/events", summary="即時更新：哪些資料變了（Server-Sent Events；只有種類與 id，不含資料）",
            response_class=StreamingResponse,
            responses={200: {"content": {"text/event-stream": {}}}})
async def events(request: Request,
                 last: str | None = Query(default=None, max_length=64,
                                          description="上次收到的事件 id（也可用 Last-Event-ID 標頭）")):
    hub: Hub | None = getattr(request.app.state, "realtime_hub", None)
    if hub is None or not get_settings().realtime_enabled:
        raise ApiError(503, "realtime_off", "即時更新目前關閉", extra={"retry_after_seconds": OFF_RETRY_AFTER},
                       headers={"Retry-After": str(OFF_RETRY_AFTER)})
    if not _origin_allowed(request):
        raise ApiError(403, "forbidden", "不允許從這個網站連線")
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise ApiError(401, "unauthorized", "請先登入")
    sid = _token_hash(token)
    ident = await run_in_threadpool(_identify, sid)
    if ident is None:
        raise ApiError(401, "unauthorized", "登入已過期，請重新登入")
    user_id, is_admin = ident
    try:
        hub.admit(user_id)
    except Refused as exc:
        raise ApiError(exc.status, exc.code, REFUSED_MESSAGES[exc.code], extra={"retry_after_seconds": exc.retry_after},
                       headers={"Retry-After": str(exc.retry_after)}) from None
    last = last or request.headers.get("last-event-id") or None
    conn, mode = hub.register(user_id, session_key(sid), is_admin, last)
    hello_id = hub.position

    async def check() -> bool:
        try:
            return await run_in_threadpool(_still_valid, sid)
        except Exception as exc:  # the database is briefly unreachable: keep the stream, check again later
            log.warning("realtime: session re-check failed (%s)", type(exc).__name__)
            return True

    return EventStream(hub, conn, hub.stream(conn, mode, hello_id, check))
