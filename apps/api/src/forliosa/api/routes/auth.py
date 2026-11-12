"""Sign-in providers and Discord OAuth (M5). Dev login and logout stay in ``routes/users.py``."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from forliosa.api.deps import rotate_session
from forliosa.config import get_settings
from forliosa.db import get_db
from forliosa.services import discord_oauth as oauth

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("forliosa.oauth")


@router.get("/providers", summary="可用的登入方式（不需登入）")
def providers():
    settings = get_settings()
    return {"discord": settings.discord_enabled, "dev_login": settings.is_dev}


def _failure(code: str) -> RedirectResponse:
    return RedirectResponse(f"{get_settings().frontend_base}/login?error={code}", status_code=302)


def _forget_state(resp: RedirectResponse) -> RedirectResponse:
    settings = get_settings()
    resp.delete_cookie(oauth.state_cookie_name(settings), path="/", secure=settings.secure_cookies, httponly=True,
                       samesite="lax")
    return resp


@router.get("/discord/start", summary="以 Discord 登入：302 到 Discord 授權頁", response_class=RedirectResponse,
            status_code=302)
def discord_start(next: str | None = Query(default=None, max_length=2048)):
    settings = get_settings()
    if not settings.discord_enabled:
        return _failure("oauth_disabled")
    state, cookie = oauth.make_state(oauth.safe_next(next))
    resp = RedirectResponse(oauth.authorize_url(settings, state), status_code=302)
    resp.set_cookie(oauth.state_cookie_name(settings), cookie, max_age=oauth.STATE_TTL_SECONDS, httponly=True,
                    secure=settings.secure_cookies, samesite="lax", path="/")
    return resp


@router.get("/discord/callback", summary="Discord 授權回呼：建立 session 後 302 回前端",
            response_class=RedirectResponse, status_code=302)
def discord_callback(request: Request, code: str | None = Query(default=None, max_length=512),
                     state: str | None = Query(default=None, max_length=512),
                     error: str | None = Query(default=None, max_length=200),
                     db: Session = Depends(get_db)):
    settings = get_settings()
    cookie = request.cookies.get(oauth.state_cookie_name(settings))
    try:
        if not settings.discord_enabled:
            raise oauth.OAuthError("oauth_disabled")
        if error:
            raise oauth.OAuthError("oauth_denied" if error == "access_denied" else "oauth_failed")
        next_path = oauth.check_state(cookie, state)
        if not code:
            raise oauth.OAuthError("oauth_failed")
        profile = oauth.fetch_profile(settings, code)
        try:
            user = oauth.sign_in(db, profile)
        except IntegrityError:  # a concurrent first login of the same account
            db.rollback()
            raise oauth.OAuthError("oauth_failed") from None
    except oauth.OAuthError as exc:
        log.info("discord login failed: %s", exc.code)
        return _forget_state(_failure(exc.code))
    resp = RedirectResponse(f"{settings.frontend_base}{next_path}", status_code=302)
    rotate_session(db, request, user, resp)
    return _forget_state(resp)
