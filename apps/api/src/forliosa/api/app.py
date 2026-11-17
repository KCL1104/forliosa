"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from starlette.middleware.gzip import GZipMiddleware

from forliosa import logredact, perf
from forliosa.api.deps import TAB_HEADER
from forliosa.api.errors import install_error_handlers
from forliosa.api.middleware import VIEW_AS_HEADER, OriginCheckMiddleware, ViewAsMiddleware
from forliosa.api.routes import (
    accounts,
    admin,
    admin_reports,
    ai,
    auth,
    briefings,
    delegations,
    derivatives,
    discussions,
    events,
    groups,
    imports,
    market,
    market_page,
    market_reports,
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


def warm_up_in_background() -> None:
    """At start-up (``forliosa.main``, not the tests): build the instrument master and shioaji-data's latest closes
    before the first request needs them, then freeze the long-lived objects out of the garbage collector's full
    collections (``forliosa.perf.freeze_heap``) — once: a freeze pins whatever is alive at that moment, in-flight
    requests included, so repeating it (it ran after every hourly master rebuild) kept their cyclic garbage forever."""
    import threading

    def run() -> None:
        log = logging.getLogger(__name__)
        try:
            get_market_data().warm_up()
        except Exception:  # requests build what is missing themselves, as before
            log.warning("warm-up failed", exc_info=True)
        perf.freeze_heap()
        log.info("warm-up done")

    threading.Thread(target=run, name="warm-up", daemon=True).start()


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


SHUTDOWN_SIGNALS = (signal.SIGTERM, signal.SIGINT)


def close_streams_on_signal(hub, loop: asyncio.AbstractEventLoop) -> Callable[[], None]:
    """End every realtime stream as soon as the process is told to stop; returns the function that undoes this.

    uvicorn (0.54) handles SIGTERM by waiting up to ``--timeout-graceful-shutdown`` for open connections, cancelling
    what is left, and only then running the lifespan shutdown. A stream never ends by itself, so without this every
    deploy would wait the full grace period and cut each stream with an error instead of ``bye{rotate}``. uvicorn's
    own handler (already installed when the lifespan starts) is chained, not replaced. Signals can only be handled on
    the main thread: elsewhere (tests that run the server in a thread) this does nothing."""
    if threading.current_thread() is not threading.main_thread():
        return lambda: None
    installed: dict[int, tuple[Callable, Callable]] = {}
    for sig in SHUTDOWN_SIGNALS:
        prev = signal.getsignal(sig)
        if not callable(prev):  # nobody stops gracefully on this signal (default action or ignored): leave it
            continue

        def handler(signum, frame, prev=prev):
            with contextlib.suppress(RuntimeError):  # the loop is already closed
                loop.call_soon_threadsafe(hub.shutdown)
            prev(signum, frame)

        signal.signal(sig, handler)
        installed[sig] = (handler, prev)

    def restore() -> None:
        for sig, (handler, prev) in installed.items():
            if signal.getsignal(sig) is handler:
                signal.signal(sig, prev)

    return restore


@asynccontextmanager
async def realtime_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """The realtime hub of this process (``forliosa.realtime.hub``): on PostgreSQL it LISTENs for the events every
    process commits; on SQLite it hears this process's own commits. SIGTERM ends the open streams at once
    (:func:`close_streams_on_signal`)."""
    from forliosa.db import get_engine
    from forliosa.realtime.hub import Hub, HubConfig

    settings = get_settings()
    hub = None
    if settings.realtime_enabled:
        engine = get_engine()
        pg_url = engine.url.render_as_string(hide_password=False) if engine.dialect.name == "postgresql" else None
        hub = Hub(HubConfig.from_settings(settings), postgres_url=pg_url)
        await hub.start()
    restore = close_streams_on_signal(hub, asyncio.get_running_loop()) if hub is not None else (lambda: None)
    app.state.realtime_hub = hub
    try:
        yield
    finally:
        restore()
        app.state.realtime_hub = None
        if hub is not None:
            await hub.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.forliosa_env == "prod":
        check_production_settings(settings)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logredact.install()  # OAuth codes and invite tokens in URLs never reach the access log
    if settings.google_misconfigured:
        # Google is optional: a half-set configuration must not take the API down (names only, no values).
        logging.getLogger(__name__).warning(
            "Google login is off: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI must all be set"
            " (and the redirect URI must be https in production)")
    if settings.forliosa_env == "prod" and not settings.secure_cookies:
        logging.getLogger(__name__).warning("COOKIE_SECURE=false in production: the session cookie is sent over HTTP")
    app = FastAPI(
        title="Forliosa API",
        version="0.1.0",
        description="台股為主的投資管理 API：帳本、稅費、績效、行情。",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        lifespan=realtime_lifespan,
    )
    # Inner to outer: view-as allow-list, CSRF origin check, then CORS outermost (so 403s carry CORS headers).
    app.add_middleware(ViewAsMiddleware, prefix=API_PREFIX)
    app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.cors_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "Last-Event-ID", VIEW_AS_HEADER, TAB_HEADER],
        # The web app reads the API from another origin: without this the browser hides Retry-After from it, and the
        # realtime client could not wait as long as a 429 / 503 (realtime_off, realtime_busy) asks.
        expose_headers=["Retry-After"],
    )
    # JSON over 1 KB is gzipped (the API's domain is DNS-only at Cloudflare, so nothing compressed it: the watchlist,
    # polled every minute, was 41 KB, 6 KB gzipped). Server-sent events are never compressed (Starlette's default).
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
    # Outermost: the slow-request log times the whole request, CORS and compression included (``forliosa.perf``).
    app.add_middleware(perf.SlowRequestMiddleware, prefix=API_PREFIX)
    perf.install_gc_log()
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

    for module in (users, auth, accounts, market, market_page, market_reports, stock, derivatives, transactions,
                   portfolio, watchlist, recurring, ai, briefings, delegations, groups, discussions, imports, events):
        api.include_router(module.router)
    api.include_router(discussions.admin_router)
    api.include_router(admin.router)  # the back office: overview, news takedown blocklist
    api.include_router(admin_reports.router)  # the back office: 市場報告 (blind test, settings, hand-kept tables)
    app.include_router(api)
    return app
