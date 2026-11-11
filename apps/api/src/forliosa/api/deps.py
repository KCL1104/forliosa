"""Request dependencies: DB session, current user (httpOnly cookie session)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Depends, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from forliosa.api.errors import ApiError
from forliosa.config import get_settings
from forliosa.db import get_db
from forliosa.models import User, UserSession
from forliosa.timeutil import now_utc

COOKIE_NAME = "forliosa_session"


def _token_hash(token: str) -> str:
    key = get_settings().session_secret.encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


def create_session(db: Session, user: User, response: Response) -> None:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    expires = now_utc() + timedelta(days=settings.session_ttl_days)
    db.add(UserSession(id=_token_hash(token), user_id=user.id, expires_at=expires))
    db.commit()
    response.set_cookie(
        COOKIE_NAME, token, max_age=settings.session_ttl_days * 86400, httponly=True,
        secure=settings.secure_cookies, samesite="lax", path="/", domain=settings.cookie_domain,
    )


def destroy_session(db: Session, request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        db.execute(delete(UserSession).where(UserSession.id == _token_hash(token)))
        db.commit()
    settings = get_settings()
    response.delete_cookie(COOKIE_NAME, path="/", domain=settings.cookie_domain,
                           secure=settings.secure_cookies, httponly=True, samesite="lax")


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise ApiError(401, "unauthorized", "請先登入")
    sess = db.get(UserSession, _token_hash(token))
    if sess is None or _aware(sess.expires_at) <= now_utc():
        raise ApiError(401, "unauthorized", "登入已過期，請重新登入")
    user = db.get(User, sess.user_id)
    if user is None:
        raise ApiError(401, "unauthorized", "請先登入")
    return user


def purge_expired_sessions(db: Session) -> int:
    res = db.execute(delete(UserSession).where(UserSession.expires_at <= now_utc()))
    db.commit()
    return res.rowcount or 0


__all__ = ["COOKIE_NAME", "create_session", "current_user", "destroy_session", "get_db", "select"]
