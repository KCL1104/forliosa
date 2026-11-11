"""FastAPI application factory."""

from __future__ import annotations

import logging

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from forliosa.api.errors import install_error_handlers
from forliosa.api.routes import accounts, market, portfolio, transactions, users
from forliosa.config import DEFAULT_SESSION_SECRET, get_settings
from forliosa.marketdata.service import get_market_data

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.forliosa_env == "prod" and settings.session_secret == DEFAULT_SESSION_SECRET:
        raise RuntimeError("SESSION_SECRET must be set in production")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = FastAPI(
        title="Forliosa API",
        version="0.1.0",
        description="台股為主的投資管理 API：帳本、稅費、績效、行情。",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "Last-Event-ID"],
    )
    install_error_handlers(app)

    api = APIRouter(prefix=API_PREFIX)

    @api.get("/health", tags=["meta"], summary="健康檢查")
    def health():
        return {"status": "ok", "env": settings.forliosa_env, "providers": get_market_data().status()}

    for module in (users, accounts, market, transactions, portfolio):
        api.include_router(module.router)
    app.include_router(api)
    return app
