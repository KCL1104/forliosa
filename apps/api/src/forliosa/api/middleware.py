"""Site-wide request guards (pure ASGI middleware, inside CORS so their errors still carry CORS headers).

* :class:`OriginCheckMiddleware` — CSRF: a non-``GET``/``HEAD``/``OPTIONS`` request that carries ``Origin`` must come
  from one of ``CORS_ORIGINS``; otherwise 403 ``forbidden``. (Requests without ``Origin`` — curl, server-to-server —
  pass: browsers always send it on cross-site writes. ``CORS_ORIGINS=*``, refused in production, allows any.)
* :class:`ViewAsMiddleware` — ``X-Forliosa-View-As: <delegation id>``: a **default-deny route allow-list**. Only the
  read endpoints in :data:`VIEW_AS_READ` are served as the delegation's owner (``scope["state"]["view_as"]``, resolved
  and checked by ``api.deps.current_user``); endpoints that read no user data (:data:`VIEW_AS_IGNORED`) ignore the
  header; every other request is refused: writes with 403 ``read_only``, other reads with 403 ``view_as_not_allowed``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from forliosa.api.errors import error_body

VIEW_AS_HEADER = "x-forliosa-view-as"
DENIED = {"read_only": "唯讀查看模式不能修改資料", "view_as_not_allowed": "唯讀查看模式不提供這項功能"}
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_SEG = r"[^/]+"


def _compile(prefix: str, patterns: Iterable[str]) -> list[re.Pattern[str]]:
    return [re.compile(f"^{re.escape(prefix)}{p.replace('{seg}', _SEG)}/?$") for p in patterns]


# User-data reads served as the owner, limited to the delegated accounts (GET / HEAD only).
VIEW_AS_READ_PATHS = (
    "/accounts",
    "/accounts/{seg}/holdings",
    "/portfolio/summary",
    "/portfolio/holdings",
    "/portfolio/performance",
    "/portfolio/closed",
    "/portfolio/upcoming",
    "/transactions",
    "/transactions/{seg}",
    "/instruments/{seg}/position",
    "/instruments/{seg}/position/history",
    "/instruments/{seg}/events",
)
# Endpoints that read no user data: the header is ignored (they answer as the signed-in viewer).
VIEW_AS_IGNORED_PATHS = (
    "/health",
    "/meta/{seg}",
    "/auth/providers",
    "/me",
    "/instruments/search",
    "/instruments/{seg}",
    "/instruments/{seg}/quote",
    "/instruments/{seg}/history",
    "/instruments/{seg}/valuation",
    "/instruments/{seg}/revenue",
    "/instruments/{seg}/dividends",
    "/instruments/{seg}/overview",
    "/instruments/{seg}/intraday",
    "/instruments/{seg}/chips",
    "/instruments/{seg}/financials",
    "/instruments/{seg}/news",
    "/instruments/{seg}/why",
    "/quotes",
    "/stream/quotes",
    "/derivatives/{seg}",
    "/derivatives/futures/{seg}/history",
)


class ViewAsMiddleware:
    def __init__(self, app: ASGIApp, prefix: str):
        self.app = app
        self.read = _compile(prefix, VIEW_AS_READ_PATHS)
        self.ignored = _compile(prefix, VIEW_AS_IGNORED_PATHS)

    def classify(self, method: str, path: str) -> str:
        """``read`` (serve as owner) | ``ignore`` (header ignored) | ``read_only`` | ``view_as_not_allowed``."""
        if method == "OPTIONS":
            return "ignore"  # CORS preflight (answered by the CORS middleware before this one)
        if method not in ("GET", "HEAD"):
            return "read_only"
        if any(p.match(path) for p in self.read):
            return "read"
        if any(p.match(path) for p in self.ignored):
            return "ignore"
        return "view_as_not_allowed"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        raw = next((v for k, v in scope.get("headers", []) if k == VIEW_AS_HEADER.encode()), None)
        delegation_id = raw.decode("latin-1").strip() if raw is not None else ""
        if not delegation_id:
            await self.app(scope, receive, send)
            return
        verdict = self.classify(scope["method"], scope["path"])
        if verdict in DENIED:
            await JSONResponse(error_body(verdict, DENIED[verdict]), status_code=403)(scope, receive, send)
            return
        if verdict == "read":
            scope.setdefault("state", {})["view_as"] = delegation_id
        await self.app(scope, receive, send)


class OriginCheckMiddleware:
    def __init__(self, app: ASGIApp, allowed_origins: Iterable[str]):
        self.app = app
        self.allowed = frozenset(o.strip().rstrip("/").lower() for o in allowed_origins if o.strip())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in SAFE_METHODS and "*" not in self.allowed:
            origin = next((v for k, v in scope.get("headers", []) if k == b"origin"), None)
            if origin is not None and origin.decode("latin-1").strip().rstrip("/").lower() not in self.allowed:
                resp = JSONResponse(error_body("forbidden", "不允許從這個網站送出請求"), status_code=403)
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)
