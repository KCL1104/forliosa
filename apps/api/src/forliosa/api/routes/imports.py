"""匯入對帳單 v1: ``POST /imports/statement`` reads a statement or screenshots and checks every row (stores nothing).

The body is JSON with base64 page images (the browser decrypts and renders a PDF itself; see ``ai.importer``). It is
read here with a hard cap — ``Content-Length`` first, then counted while it streams in — because nothing else limits a
request body (413 past ``IMPORT_MAX_BODY_MB``). The body is never logged: validation errors name the field, never
echo its value.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import threading

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlalchemy.orm import Session

from forliosa.ai.importer import Page, scrub
from forliosa.api.deps import current_user
from forliosa.api.errors import ApiError
from forliosa.api.schemas_imports import StatementImportIn, StatementImportOut, inline_schema
from forliosa.config import Settings, get_settings
from forliosa.db import get_db
from forliosa.marketdata.service import get_market_data
from forliosa.models import User
from forliosa.services import imports as svc

router = APIRouter(prefix="/imports", tags=["imports"])

TOO_LARGE = "檔案太大。PDF 分開匯入，或少選幾張截圖。"
_MAGIC = {"image/jpeg": (b"\xff\xd8\xff",), "image/png": (b"\x89PNG\r\n\x1a\n",)}


def sniff(head: bytes) -> str | None:
    """The image type its first bytes say it is (JPEG, PNG or WebP), else None."""
    for media_type, prefixes in _MAGIC.items():
        if head.startswith(prefixes):
            return media_type
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


async def read_capped(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise ApiError(413, "too_large", TOO_LARGE)
        except ValueError:
            raise ApiError(400, "bad_request", "送出的內容有問題，重新整理後再試。") from None
    parts: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise ApiError(413, "too_large", TOO_LARGE)
        parts.append(chunk)
    return b"".join(parts)


def parse_body(body: bytes, settings: Settings) -> tuple[StatementImportIn, list[Page]]:
    """The request as pages: 422 for a malformed body (naming the field only), 413 past ``IMPORT_MAX_PAGES``,
    422 ``unsupported_file`` for data that is not a JPEG, PNG or WebP image."""
    try:
        raw = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ApiError(422, "validation_error", "送出的內容不是 JSON。") from None
    pages = raw.get("pages") if isinstance(raw, dict) else None
    if isinstance(pages, list) and len(pages) > settings.import_max_pages:
        raise ApiError(413, "too_large", f"一次最多 {settings.import_max_pages} 頁。")
    try:
        data = StatementImportIn.model_validate(raw)
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors(include_input=False)})
        raise ApiError(422, "validation_error", "送出的內容格式不對。", details={"fields": fields[:10]}) from None
    out: list[Page] = []
    for n, p in enumerate(data.pages, start=1):
        b64 = p.data.split(",", 1)[1] if p.data.startswith("data:") else p.data
        try:
            head = base64.b64decode(b64[:24], validate=True)
            base64.b64decode(b64, validate=True)  # the whole string: the API refuses broken base64
        except (binascii.Error, ValueError):
            raise ApiError(422, "unsupported_file", f"第 {n} 頁不是圖片。") from None
        kind = sniff(head)
        if kind is None:
            raise ApiError(422, "unsupported_file", "只收 JPEG、PNG、WebP 圖片。")
        # the declared type is not trusted: the API needs the real one
        out.append(Page(n, kind, b64, scrub(p.text) if p.text else None))
    return data, out


@router.post("/statement", response_model=StatementImportOut,
             summary="匯入對帳單：AI 讀 PDF 頁面或截圖、伺服器逐列驗算（什麼都不存）",
             openapi_extra={"requestBody": {"required": True, "content": {
                 "application/json": {"schema": inline_schema(StatementImportIn)}}}})
async def read_statement(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    settings = get_settings()
    svc.require_access(user, settings)
    body = await read_capped(request, int(settings.import_max_body_mb * 1024 * 1024))
    data, pages = parse_body(body, settings)
    del body
    # 取消 in the browser closes the request: the read goes on in its thread, but skips the second reading
    gone = threading.Event()
    watcher = asyncio.create_task(_watch_disconnect(request, gone))
    try:
        return await run_in_threadpool(svc.read_statement, db, user, data.account_id, pages, get_market_data(),
                                       settings, cancelled=gone.is_set)
    finally:
        watcher.cancel()


async def _watch_disconnect(request: Request, gone: threading.Event, every: float = 1.0) -> None:
    while not await request.is_disconnected():
        await asyncio.sleep(every)
    gone.set()
