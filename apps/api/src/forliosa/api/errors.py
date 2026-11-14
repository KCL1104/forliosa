"""Contract error format: ``{"error": {"code": "...", "message": "..."}}``."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

_DEFAULT_MESSAGES = {
    400: ("bad_request", "送出的內容有問題，重新整理後再試。"),
    401: ("unauthorized", "請先登入"),
    403: ("forbidden", "沒有權限"),
    404: ("not_found", "找不到這個項目。"),
    405: ("method_not_allowed", "不支援這個操作"),
    409: ("conflict", "資料已經被改過，重新整理後再試。"),
    422: ("validation_error", "輸入資料格式錯誤"),
    429: ("rate_limited", "太頻繁了，等一下再試。"),
}


class ApiError(Exception):
    """``extra``: more fields of the error object, next to ``code`` and ``message`` (``retry_after_seconds``,
    ``until`` …); ``headers``: response headers (``Retry-After``)."""

    def __init__(self, status: int, code: str, message: str, details: Any = None,
                 extra: dict[str, Any] | None = None, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.extra = extra
        self.headers = headers


def not_found(message: str = "找不到資源") -> ApiError:
    return ApiError(404, "not_found", message)


def unprocessable(message: str, code: str = "validation_error", details: Any = None) -> ApiError:
    return ApiError(422, code, message, details)


def error_body(code: str, message: str, details: Any = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    err: dict[str, Any] = {**(extra or {}), "code": code, "message": message}
    if details is not None:
        err["details"] = details
    return {"error": err}


_FIELD_LABELS = {
    "email": "電子郵件", "name": "名稱", "currency": "幣別", "account_id": "帳戶", "symbol": "商品代號",
    "type": "交易類型", "trade_date": "交易日期", "quantity": "數量", "price": "價格", "amount": "金額",
    "fee": "手續費", "tax": "稅", "holdings": "持股", "as_of": "日期", "range": "區間", "symbols": "商品代號",
    "limit": "筆數", "cursor": "分頁游標", "date": "日期",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_req: Request, exc: ApiError):
        return JSONResponse(error_body(exc.code, exc.message, exc.details, exc.extra), status_code=exc.status,
                            headers=exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_req: Request, exc: StarletteHTTPException):
        code, default = _DEFAULT_MESSAGES.get(exc.status_code, ("error", "伺服器出了問題，等一下再試一次。"))
        message = exc.detail if isinstance(exc.detail, str) and exc.status_code != 404 else default
        if exc.status_code == 404 and isinstance(exc.detail, str) and exc.detail != "Not Found":
            message = exc.detail
        return JSONResponse(error_body(code, message), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_req: Request, exc: RequestValidationError):
        details = []
        for e in exc.errors():
            loc = [str(p) for p in e.get("loc", ()) if p not in ("body", "query", "path")]
            details.append({"field": ".".join(loc), "message": e.get("msg", "")})
        first = details[0]["field"].split(".")[0] if details else ""
        label = _FIELD_LABELS.get(first, first)
        message = f"輸入資料格式錯誤：{label}" if label else "輸入資料格式錯誤"
        return JSONResponse(error_body("validation_error", message, details), status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(_req: Request, exc: Exception):  # pragma: no cover - safety net
        log.exception("unhandled error: %s", exc)
        return JSONResponse(error_body("internal_error", "伺服器出了問題，等一下再試一次。"), status_code=500)
