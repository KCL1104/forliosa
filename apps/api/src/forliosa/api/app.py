"""FastAPI application factory."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from forliosa import logredact
from forliosa.api.errors import install_error_handlers
from forliosa.api.middleware import VIEW_AS_HEADER, OriginCheckMiddleware, ViewAsMiddleware
from forliosa.api.routes import (
    accounts,
    ai,
    auth,
    delegations,
    derivatives,
    discussions,
    groups,
    market,
    portfolio,
    recurring,
    stock,
    transactions,
    users,
    watchlist,
)
from forliosa.api.schemas import MarketStatus
from forliosa.config import DEFAULT_SESSION_SECRET, get_settings
from forliosa.datapolicy import attributions
from forliosa.db import get_db
from forliosa.market_calendar import market_status
from forliosa.marketdata.service import get_market_data

API_PREFIX = "/api/v1"


def dataset_status() -> dict[str, dict]:
    """``dataset_status`` rows (newest data date per dataset) for ``/meta/attributions``; empty without a DB."""
    from forliosa.db import session_factory
    from forliosa.models import DatasetStatus
    from forliosa.timeutil import iso_taipei

    try:
        with session_factory()() as db:
            return {r.key: {"data_date": r.data_date.isoformat() if r.data_date else None,
                            "fetched_at": iso_taipei(r.fetched_at) if r.fetched_at else None}
                    for r in db.query(DatasetStatus).all()}
    except Exception:  # an old database without the table: attributions still work
        logging.getLogger(__name__).warning("dataset_status unavailable", exc_info=True)
        return {}


def check_production_settings(settings) -> None:
    """Refuse to start in production with settings that would weaken login or sharing (no values are printed)."""
    if settings.session_secret == DEFAULT_SESSION_SECRET:
        raise RuntimeError("SESSION_SECRET must be set in production")
    if "*" in settings.cors_origins:
        # With credentials a wildcard would let any site make requests with the user's cookie.
        raise RuntimeError("CORS_ORIGINS must list the frontend origins explicitly in production (no *)")
    if not settings.frontend_url:
        raise RuntimeError("FRONTEND_URL must be set in production (login redirects and invite links use it)")
    if settings.frontend_url not in settings.cors_origins:
        raise RuntimeError("FRONTEND_URL must be one of CORS_ORIGINS")
    if not all(o.startswith("https://") for o in [settings.frontend_url, *settings.cors_origins]):
        raise RuntimeError("FRONTEND_URL and every CORS_ORIGINS entry must be https in production")
    if settings.discord_partially_configured:
        raise RuntimeError("DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET and DISCORD_REDIRECT_URI must be set together")
    if settings.discord_enabled and not (settings.discord_redirect_uri or "").startswith("https://"):
        raise RuntimeError("DISCORD_REDIRECT_URI must be https in production")


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.forliosa_env == "prod":
        check_production_settings(settings)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logredact.install()  # OAuth codes and invite tokens in URLs never reach the access log
    if settings.forliosa_env == "prod" and not settings.secure_cookies:
        logging.getLogger(__name__).warning("COOKIE_SECURE=false in production: the session cookie is sent over HTTP")
    app = FastAPI(
        title="Forliosa API",
        version="0.1.0",
        description="台股為主的投資管理 API：帳本、稅費、績效、行情。",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    # Inner to outer: view-as allow-list, CSRF origin check, then CORS outermost (so 403s carry CORS headers).
    app.add_middleware(ViewAsMiddleware, prefix=API_PREFIX)
    app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.cors_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "Last-Event-ID", VIEW_AS_HEADER],
    )
    install_error_handlers(app)

    api = APIRouter(prefix=API_PREFIX)

    @api.get("/health", tags=["meta"], summary="健康檢查")
    def health():
        md = get_market_data()
        return {"status": "ok", "env": settings.forliosa_env, "data_policy": md.policy, "providers": md.status()}

    @api.get("/meta/attributions", tags=["meta"], summary="資料來源與授權：每個資料集的顯名聲明（不需登入）")
    def meta_attributions():
        return attributions(get_market_data().policy, settings.taifex_conditional_confirmed, dataset_status())

    @api.get("/meta/market-status", response_model=MarketStatus, tags=["meta"],
             summary="台股現在是不是盤中（依官方行事曆；交易日 09:00–13:30 台北時間；不需登入）")
    def meta_market_status(db: Session = Depends(get_db)):
        return market_status(db)

    for module in (users, auth, accounts, market, stock, derivatives, transactions, portfolio, watchlist, recurring,
                   ai, delegations, groups, discussions):
        api.include_router(module.router)
    api.include_router(discussions.admin_router)
    app.include_router(api)
    return app
